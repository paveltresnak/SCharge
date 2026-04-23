"""Number entity pro LoadBalance + per-connector charging current."""
from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfPower
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

# Per-connector charging current limits (from DeviceData telemetry typical range)
CHARGE_CURRENT_MIN = 6
CHARGE_CURRENT_MAX = 32
CHARGE_CURRENT_STEP = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SchargeLoadBalance(coordinator),
        SchargeChargeCurrent(coordinator, 1),
        SchargeChargeCurrent(coordinator, 2),
    ])


class SchargeLoadBalance(SchargeEntity, NumberEntity):
    """LoadBalance (W) — building-level ceiling for whole wallbox."""

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


class SchargeChargeCurrent(SchargeEntity, NumberEntity):
    """Charging current per connector (A) — REAL per-session throttle.

    Uses Authorize action with purpose=Start + new current to throttle active
    charging session. More granular than LoadBalance (building-wide ceiling).
    """

    _attr_native_min_value = CHARGE_CURRENT_MIN
    _attr_native_max_value = CHARGE_CURRENT_MAX
    _attr_native_step = CHARGE_CURRENT_STEP
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: SchargeCoordinator, connector_id: int) -> None:
        super().__init__(coordinator)
        self._connector_id = connector_id
        self._attr_unique_id = f"{coordinator.serial}_c_{connector_id}_charge_current_set"
        self._attr_translation_key = f"c_{connector_id}_charge_current"
        self._attr_icon = "mdi:current-ac"

    @property
    def native_value(self) -> float | None:
        """Return reserveCurrent from SynchroStatus (target charging current)."""
        if self.coordinator.synchro_status is None:
            return None
        src = (self.coordinator.synchro_status.connector_main if self._connector_id == 1
               else self.coordinator.synchro_status.connector_vice)
        if src is None:
            return None
        return getattr(src, "reserve_current", None)

    async def async_set_native_value(self, value: float) -> None:
        amps = int(value)
        if amps < CHARGE_CURRENT_MIN or amps > CHARGE_CURRENT_MAX:
            _LOGGER.warning("ChargeCurrent %d A mimo rozsah (%d-%d)",
                            amps, CHARGE_CURRENT_MIN, CHARGE_CURRENT_MAX)
            return
        ok = await self.coordinator.send_authorize(self._connector_id, "Start", amps)
        if not ok:
            _LOGGER.warning("Authorize Start (c=%d, %d A) nezdařeno",
                            self._connector_id, amps)
