"""S-charge Wallbox integration for Home Assistant."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

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
from .coordinator import SchargeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor", "number", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SCharge from a config entry."""
    _LOGGER.info("Setting up scharge entry %s", entry.entry_id)

    coordinator = SchargeCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        serial=entry.data[CONF_SERIAL],
        host=entry.data.get(CONF_HOST),
        ws_port=entry.data.get(CONF_WS_PORT, DEFAULT_WS_PORT),
        broadcast_addr=entry.data.get(CONF_BROADCAST_ADDR, DEFAULT_BROADCAST_ADDR),
        broadcast_port=entry.data.get(CONF_BROADCAST_PORT, DEFAULT_BROADCAST_PORT),
    )

    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SchargeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unload_ok
