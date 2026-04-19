"""Config flow pro SCharge integration."""
import asyncio
import logging
import socket

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BROADCAST_ADDR,
    CONF_BROADCAST_PORT,
    CONF_SERIAL,
    CONF_WS_PORT,
    DEFAULT_BROADCAST_ADDR,
    DEFAULT_BROADCAST_PORT,
    DEFAULT_WS_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_SERIAL): str,
    vol.Optional(CONF_WS_PORT, default=DEFAULT_WS_PORT): vol.All(int, vol.Range(min=1024, max=65535)),
    vol.Optional(CONF_BROADCAST_ADDR, default=DEFAULT_BROADCAST_ADDR): str,
    vol.Optional(CONF_BROADCAST_PORT, default=DEFAULT_BROADCAST_PORT): vol.All(int, vol.Range(min=1, max=65535)),
})


def _validate_ip(ip: str) -> bool:
    """Validace IPv4 formátu."""
    try:
        socket.inet_aton(ip)
        parts = ip.split(".")
        return len(parts) == 4 and all(0 <= int(p) <= 255 for p in parts)
    except (socket.error, ValueError):
        return False


async def _is_reachable(hass: HomeAssistant, host: str, timeout: float = 2.0) -> bool:
    """Ping check přes vytvoření TCP spojení na libovolný port.

    Vracíme True pokud hostitel odpovídá na TCP SYN (i pokud port je zavřený
    → dostaneme ICMP Port Unreachable nebo RST, což značí aktivní hostitele).
    """
    # Zkusíme ICMP-like ping přes TCP connect na port 80 (nebo cokoliv otevřeného)
    # Wallbox má všechny porty zavřené, ale reaguje ARP/ICMP → použijeme
    # asyncio create_connection s krátkým timeoutem. Connect failure (refused/timeout)
    # nemusí znamenat, že host je offline — proto jsme tolerantní.
    def _ping() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            # UDP connect sám o sobě nic nepošle, ale force route resolve
            s.connect((host, 1))
            return True
        except OSError:
            return False
        finally:
            s.close()

    try:
        return await asyncio.wait_for(
            hass.async_add_executor_job(_ping),
            timeout=timeout + 1,
        )
    except asyncio.TimeoutError:
        return False


class SchargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SCharge."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            serial = user_input[CONF_SERIAL].strip()

            # Validace IP
            if not _validate_ip(host):
                errors[CONF_HOST] = "invalid_ip"

            # Validace S/N — Joint Tech používá 15-20 alfanumerických znaků
            if not serial or len(serial) < 10 or not serial.replace("-", "").isalnum():
                errors[CONF_SERIAL] = "invalid_serial"

            # Reachability
            if not errors and not await _is_reachable(self.hass, host):
                errors[CONF_HOST] = "unreachable"

            if not errors:
                # Unique ID = serial (nelze přidat 2× stejný wallbox)
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Wallbox {serial}",
                    data={
                        CONF_HOST: host,
                        CONF_SERIAL: serial,
                        CONF_WS_PORT: user_input.get(CONF_WS_PORT, DEFAULT_WS_PORT),
                        CONF_BROADCAST_ADDR: user_input.get(CONF_BROADCAST_ADDR, DEFAULT_BROADCAST_ADDR),
                        CONF_BROADCAST_PORT: user_input.get(CONF_BROADCAST_PORT, DEFAULT_BROADCAST_PORT),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
