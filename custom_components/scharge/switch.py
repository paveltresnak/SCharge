"""Switch entity pro sdílení wallboxu s mobilní aplikací."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SchargeBridgeSwitch(coordinator)])


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
