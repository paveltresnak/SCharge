"""Sensor entity pro SCharge wallbox."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity


@dataclass(frozen=True, kw_only=True)
class SchargeSensorDescription(SensorEntityDescription):
    """Popis sensor entity s extraktorem hodnoty z coordinatoru."""
    value_fn: Callable[[SchargeCoordinator], Any] = lambda _: None


def _connector(coord: SchargeCoordinator, which, field: str) -> Any:
    """Helper: získat pole z SynchroData nebo SynchroStatus."""
    if which == 1:
        sd = coord.synchro_data.connector_main if coord.synchro_data else None
        ss = coord.synchro_status.connector_main if coord.synchro_status else None
    else:
        sd = coord.synchro_data.connector_vice if coord.synchro_data else None
        ss = coord.synchro_status.connector_vice if coord.synchro_status else None

    for src in (sd, ss):
        if src is not None and hasattr(src, field):
            return getattr(src, field)
    return None


# ─── Sensor descriptions ───────────────────────────────────────────────────────


def _connector_sensors(which: str, label: str) -> list[SchargeSensorDescription]:
    return [
        SchargeSensorDescription(
            key=f"c_{which}_voltage",
            translation_key=f"c_{which}_voltage",
            name=f"{label} Voltage",
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=1,
            value_fn=lambda c, w=which: _connector(c, w, "voltage"),
        ),
        SchargeSensorDescription(
            key=f"c_{which}_current",
            translation_key=f"c_{which}_current",
            name=f"{label} Current",
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            value_fn=lambda c, w=which: _connector(c, w, "current"),
        ),
        SchargeSensorDescription(
            key=f"c_{which}_power",
            translation_key=f"c_{which}_power",
            name=f"{label} Power",
            native_unit_of_measurement=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            value_fn=lambda c, w=which: _connector(c, w, "power"),
        ),
        SchargeSensorDescription(
            key=f"c_{which}_energy",
            translation_key=f"c_{which}_energy",
            name=f"{label} Energy (session)",
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
            state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=3,
            value_fn=lambda c, w=which: _connector(c, w, "electric_work"),
        ),
        SchargeSensorDescription(
            key=f"c_{which}_charging_time",
            translation_key=f"c_{which}_charging_time",
            name=f"{label} Charging time",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda c, w=which: _connector(c, w, "charging_time"),
        ),
        SchargeSensorDescription(
            key=f"c_{which}_status",
            translation_key=f"c_{which}_status",
            name=f"{label} Status",
            value_fn=lambda c, w=which: _connector(c, w, "charge_status"),
        ),
    ]


SENSORS: list[SchargeSensorDescription] = [
    *_connector_sensors(1, "Connector 1"),
    *_connector_sensors(2, "Connector 2"),
    # Meter (external MID if present)
    SchargeSensorDescription(
        key="meter_voltage",
        translation_key="meter_voltage",
        name="Meter Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.synchro_data.meter_info.voltage if c.synchro_data else None,
    ),
    SchargeSensorDescription(
        key="meter_current",
        translation_key="meter_current",
        name="Meter Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.synchro_data.meter_info.current if c.synchro_data else None,
    ),
    SchargeSensorDescription(
        key="meter_power",
        translation_key="meter_power",
        name="Meter Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.synchro_data.meter_info.power if c.synchro_data else None,
    ),
    # Globální
    SchargeSensorDescription(
        key="loadbalance",
        translation_key="loadbalance",
        name="Load balance",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=0,
        value_fn=lambda c: c.device_data.load_balance if c.device_data else None,
    ),
    SchargeSensorDescription(
        key="total_power",
        translation_key="total_power",
        name="Lifetime energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device_data.total_power if c.device_data else None,
    ),
    SchargeSensorDescription(
        key="charge_times",
        translation_key="charge_times",
        name="Charging sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device_data.charge_times if c.device_data else None,
    ),
    SchargeSensorDescription(
        key="rssi",
        translation_key="rssi",
        name="WiFi RSSI",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device_data.rssi if c.device_data else None,
    ),
    SchargeSensorDescription(
        key="sw_version",
        translation_key="sw_version",
        name="Firmware version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device_data.s_version if c.device_data else None,
    ),
    SchargeSensorDescription(
        key="evse_type",
        translation_key="evse_type",
        name="EVSE type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device_data.evse_type if c.device_data else None,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Nastavit sensor entity pro config entry."""
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SchargeSensor(coordinator, desc) for desc in SENSORS
    )


class SchargeSensor(SchargeEntity, SensorEntity):
    """Sensor pro wallbox."""

    entity_description: SchargeSensorDescription

    def __init__(
        self,
        coordinator: SchargeCoordinator,
        description: SchargeSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)
