"""Base Entity pro SCharge — device info, availability, update dispatch."""
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import SchargeCoordinator


class SchargeEntity(Entity):
    """Základní entity se shared logic."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SchargeCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            name=f"Wallbox S-charge ({coordinator.serial})",
            manufacturer="Joint Tech (Schlieger)",
            model="JNT-EVCD2/AC44",
            sw_version=None,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    async def async_added_to_hass(self) -> None:
        """Subscribe k dispatcher signálům."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.coordinator.signal_update, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Propagovat změnu stavu HA."""
        # Aktualizovat sw_version pokud ji máme
        dd = self.coordinator.device_data
        if dd and dd.s_version:
            self._attr_device_info["sw_version"] = dd.s_version
        self.async_write_ha_state()
