"""Button entity pro Lock/Unlock + PnC open/close."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SchargeCoordinator
from .entity import SchargeEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SchargeButtonDescription(ButtonEntityDescription):
    """Popis button entity s async action."""
    press_fn: Callable[[SchargeCoordinator], Awaitable[bool]] = lambda _: None


BUTTONS: list[SchargeButtonDescription] = [
    SchargeButtonDescription(
        key="c_1_lock",
        name="Connector 1 Lock",
        icon="mdi:lock",
        press_fn=lambda c: c.send_electronic_lock(1, "lock"),
    ),
    SchargeButtonDescription(
        key="c_1_unlock",
        name="Connector 1 Unlock",
        icon="mdi:lock-open",
        press_fn=lambda c: c.send_electronic_lock(1, "unlock"),
    ),
    SchargeButtonDescription(
        key="c_1_pnc_open",
        name="Connector 1 PnC open",
        icon="mdi:lock-open-variant",
        press_fn=lambda c: c.send_pnc_set(1, "open"),
    ),
    SchargeButtonDescription(
        key="c_1_pnc_close",
        name="Connector 1 PnC close",
        icon="mdi:lock",
        press_fn=lambda c: c.send_pnc_set(1, "close"),
    ),
    SchargeButtonDescription(
        key="c_2_lock",
        name="Connector 2 Lock",
        icon="mdi:lock",
        press_fn=lambda c: c.send_electronic_lock(2, "lock"),
    ),
    SchargeButtonDescription(
        key="c_2_unlock",
        name="Connector 2 Unlock",
        icon="mdi:lock-open",
        press_fn=lambda c: c.send_electronic_lock(2, "unlock"),
    ),
    SchargeButtonDescription(
        key="c_2_pnc_open",
        name="Connector 2 PnC open",
        icon="mdi:lock-open-variant",
        press_fn=lambda c: c.send_pnc_set(2, "open"),
    ),
    SchargeButtonDescription(
        key="c_2_pnc_close",
        name="Connector 2 PnC close",
        icon="mdi:lock",
        press_fn=lambda c: c.send_pnc_set(2, "close"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SchargeButton(coordinator, desc) for desc in BUTTONS
    )


class SchargeButton(SchargeEntity, ButtonEntity):
    entity_description: SchargeButtonDescription

    def __init__(
        self,
        coordinator: SchargeCoordinator,
        description: SchargeButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.serial}_{description.key}_btn"

    async def async_press(self) -> None:
        _LOGGER.info("Button pressed: %s", self.entity_description.key)
        await self.entity_description.press_fn(self.coordinator)
