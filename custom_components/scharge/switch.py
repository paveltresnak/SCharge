"""Switch entity: sdílení wallboxu s mobilní aplikací + start/stop nabíjení."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity

_LOGGER = logging.getLogger(__name__)

# Proud poslaný v Authorize, když jsme ještě žádný potvrzený neviděli.
DEFAULT_AUTHORIZE_CURRENT = 16


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SchargeBridgeSwitch(coordinator),
        SchargeChargingSwitch(coordinator, 1),
        SchargeChargingSwitch(coordinator, 2),
    ])


class SchargeBridgeSwitch(SchargeEntity, SwitchEntity):
    """Bridge on/off — vypni abys uvolnil wallbox pro mobilní aplikaci.

    Wallbox drží pouze jednu aktivní WebSocket session. Když je HA
    připojený, mobilní aplikace (S-charge) se nepřipojí. Přepnutím
    tohoto switche na OFF zastaví HA UDP broadcast a zavře aktivní
    WS — wallbox pak akceptuje připojení od mobilu.

    Zpátky na ON → HA obnoví broadcast, wallbox se do cca 3 s vrátí
    k HA (pokud právě není v konverzaci s mobilem).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "bridge"
    _attr_icon = "mdi:bridge"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SchargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_bridge"

    @property
    def is_on(self) -> bool:
        return self.coordinator.bridge_enabled

    @property
    def available(self) -> bool:
        # Switch je pořád dostupný (i když je bridge vypnutý), ať ho
        # uživatel může zase zapnout.
        return True

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Bridge switch ON — resuming HA WS bridge")
        await self.coordinator.resume_bridge()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Bridge switch OFF — pausing HA WS bridge (freeing for mobile app)")
        await self.coordinator.pause_bridge()
        self.async_write_ha_state()


class SchargeChargingSwitch(SchargeEntity, SwitchEntity):
    """Start/stop nabíjení na konektoru přes Authorize Start/Stop.

    ⚠️ NEOVĚŘENO NA REÁLNÉM VOZE. Akce `Authorize` s purpose="Stop" pochází
    z reverse engineeringu matemat13/ha_s-charge; tahle integrace dosud posílala
    výhradně purpose="Start" (škrcení proudu). Wallbox zprávu prokazatelně
    parsuje a odpovídá na ni do ~0,3 s, ale s odpojeným autem vrací `result:
    false` na Start i Stop — takže se bez vozu v zásuvce nedá rozhodnout, jestli
    Stop reálně přeruší nabíjení a jestli ho Start rozjede zpět.

    Proto switch NIKDY nepřepne stav optimisticky: přepne se až po `result:
    true` od wallboxu, jinak vyhodí HomeAssistantError. Radši viditelná chyba
    než tiché tvrzení, že se něco stalo.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: SchargeCoordinator, connector_id: int) -> None:
        super().__init__(coordinator)
        self._connector_id = connector_id
        self._attr_unique_id = f"{coordinator.serial}_c_{connector_id}_charging"
        self._attr_translation_key = f"c_{connector_id}_charging"
        self._optimistic: bool | None = None

    @property
    def _charge_status(self) -> str | None:
        ss = self.coordinator.synchro_status
        if ss is None:
            return None
        src = ss.connector_main if self._connector_id == 1 else ss.connector_vice
        return getattr(src, "charge_status", None) if src else None

    @property
    def is_on(self) -> bool | None:
        """Nabíjí se na tomhle konektoru?

        Přednost má potvrzený příkaz; jinak odvozeno z telemetrie. Slovník
        chargeStatus známe zatím jen částečně ('idle' = nenabíjí), takže
        cokoli jiného bereme jako aktivní.
        """
        if self._optimistic is not None:
            return self._optimistic
        status = self._charge_status
        if status is None:
            return None
        return status != "idle"

    async def _authorize(self, purpose: str) -> None:
        current = self.coordinator.last_authorized_current.get(
            self._connector_id, DEFAULT_AUTHORIZE_CURRENT)
        ok = await self.coordinator.send_authorize(self._connector_id, purpose, current)
        if not ok:
            raise HomeAssistantError(
                f"Wallbox odmítl Authorize {purpose} na konektoru {self._connector_id} "
                f"({current} A). Nejčastěji proto, že v zásuvce není auto nebo neběží "
                f"session — stav nabíjení se nezměnil."
            )
        self._optimistic = (purpose == "Start")
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Charging switch ON — konektor %d", self._connector_id)
        await self._authorize("Start")

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Charging switch OFF — konektor %d", self._connector_id)
        await self._authorize("Stop")
