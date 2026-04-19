"""Number entity pro LoadBalance slider."""
from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    LOADBALANCE_MAX,
    LOADBALANCE_MIN,
    LOADBALANCE_STEP,
)
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SchargeLoadBalance(coordinator)])


class SchargeLoadBalance(SchargeEntity, NumberEntity):
    """LoadBalance (W) — hlavní páka pro PV-driven modulaci nabíjení."""

    _attr_native_min_value = LOADBALANCE_MIN
    _attr_native_max_value = LOADBALANCE_MAX
    _attr_native_step = LOADBALANCE_STEP
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = NumberDeviceClass.POWER
    _attr_mode = NumberMode.SLIDER

    _attr_translation_key = "loadbalance_set"

    def __init__(self, coordinator: SchargeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_loadbalance_set"
        self._attr_icon = "mdi:speedometer"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.device_data is None:
            return None
        return self.coordinator.device_data.load_balance

    async def async_set_native_value(self, value: float) -> None:
        watts = int(value)
        if watts < LOADBALANCE_MIN or watts > LOADBALANCE_MAX:
            _LOGGER.warning("LoadBalance %d mimo rozsah (%d-%d)",
                            watts, LOADBALANCE_MIN, LOADBALANCE_MAX)
            return
        ok = await self.coordinator.send_loadbalance(watts)
        if not ok:
            _LOGGER.warning("LoadBalance command nezdařeno")
