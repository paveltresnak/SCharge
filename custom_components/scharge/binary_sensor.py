"""Binary sensor entity pro SCharge wallbox."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity


@dataclass(frozen=True, kw_only=True)
class SchargeBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor popis s value extraktorem."""
    value_fn: Callable[[SchargeCoordinator], bool | None] = lambda _: None


def _connector_main(coord: SchargeCoordinator, attr: str) -> bool | None:
    if coord.synchro_status and hasattr(coord.synchro_status.connector_main, attr):
        return getattr(coord.synchro_status.connector_main, attr)
    if coord.device_data and hasattr(coord.device_data.connector_main, attr):
        return getattr(coord.device_data.connector_main, attr)
    return None


def _connector_vice(coord: SchargeCoordinator, attr: str) -> bool | None:
    if coord.synchro_status and hasattr(coord.synchro_status.connector_vice, attr):
        return getattr(coord.synchro_status.connector_vice, attr)
    if coord.device_data and hasattr(coord.device_data.connector_vice, attr):
        return getattr(coord.device_data.connector_vice, attr)
    return None


BINARY_SENSORS: list[SchargeBinarySensorDescription] = [
    # Main connector
    SchargeBinarySensorDescription(
        key="c_main_connected",
        name="Main Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda c: _connector_main(c, "connection_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_main_lock",
        name="Main Lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda c: _connector_main(c, "lock_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_main_pnc",
        name="Main PnC",
        value_fn=lambda c: _connector_main(c, "pnc_status"),
    ),
    # Vice connector
    SchargeBinarySensorDescription(
        key="c_vice_connected",
        name="Vice Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda c: _connector_vice(c, "connection_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_vice_lock",
        name="Vice Lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda c: _connector_vice(c, "lock_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_vice_pnc",
        name="Vice PnC",
        value_fn=lambda c: _connector_vice(c, "pnc_status"),
    ),
    # NWire
    SchargeBinarySensorDescription(
        key="nwire_exist",
        name="N-Wire exists",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.nwire.n_wire_exist if c.nwire else None,
    ),
    SchargeBinarySensorDescription(
        key="nwire_closed",
        name="N-Wire closed",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.nwire.n_wire_closed if c.nwire else None,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SchargeBinarySensor(coordinator, desc) for desc in BINARY_SENSORS
    )


class SchargeBinarySensor(SchargeEntity, BinarySensorEntity):
    entity_description: SchargeBinarySensorDescription

    def __init__(
        self,
        coordinator: SchargeCoordinator,
        description: SchargeBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        val = self.entity_description.value_fn(self.coordinator)
        return bool(val) if val is not None else None
