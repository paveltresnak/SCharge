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


def _connector_n(coord: SchargeCoordinator, n: int, attr: str) -> bool | None:
    """Read bool-ish field from connector 1 (Main) or 2 (Vice).

    Wallbox wire protokol stále používá connectorMain/connectorVice v JSONu,
    ale v UI používáme čísla 1/2 podle zákazníkova přání.
    """
    if n == 1:
        ss = coord.synchro_status.connector_main if coord.synchro_status else None
        dd = coord.device_data.connector_main if coord.device_data else None
    else:
        ss = coord.synchro_status.connector_vice if coord.synchro_status else None
        dd = coord.device_data.connector_vice if coord.device_data else None
    for src in (ss, dd):
        if src is not None and hasattr(src, attr):
            return getattr(src, attr)
    return None


BINARY_SENSORS: list[SchargeBinarySensorDescription] = [
    # Main connector
    SchargeBinarySensorDescription(
        key="c_1_connected",
        translation_key="c_1_connected",
        name="Connector 1 Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda c: _connector_n(c, 1, "connection_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_1_lock",
        translation_key="c_1_lock",
        name="Connector 1 Lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda c: (not _connector_n(c, 1, "lock_status")) if _connector_n(c, 1, "lock_status") is not None else None,
    ),
    SchargeBinarySensorDescription(
        key="c_1_pnc",
        translation_key="c_1_pnc",
        name="Connector 1 PnC",
        value_fn=lambda c: _connector_n(c, 1, "pnc_status"),
    ),
    # Vice connector
    SchargeBinarySensorDescription(
        key="c_2_connected",
        translation_key="c_2_connected",
        name="Connector 2 Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda c: _connector_n(c, 2, "connection_status"),
    ),
    SchargeBinarySensorDescription(
        key="c_2_lock",
        translation_key="c_2_lock",
        name="Connector 2 Lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda c: (not _connector_n(c, 2, "lock_status")) if _connector_n(c, 2, "lock_status") is not None else None,
    ),
    SchargeBinarySensorDescription(
        key="c_2_pnc",
        translation_key="c_2_pnc",
        name="Connector 2 PnC",
        value_fn=lambda c: _connector_n(c, 2, "pnc_status"),
    ),
    # NWire
    SchargeBinarySensorDescription(
        key="nwire_exist",
        translation_key="nwire_exist",
        name="N-Wire exists",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.nwire.n_wire_exist if c.nwire else None,
    ),
    SchargeBinarySensorDescription(
        key="nwire_closed",
        translation_key="nwire_closed",
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
