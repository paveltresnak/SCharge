"""Button entity pro Lock/Unlock + PnC open/close."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
        translation_key="c_1_lock",
        name="Connector 1 Lock",
        icon="mdi:lock",
        press_fn=lambda c: c.send_electronic_lock(1, "lock"),
    ),
    SchargeButtonDescription(
        key="c_1_unlock",
        translation_key="c_1_unlock",
        name="Connector 1 Unlock",
        icon="mdi:lock-open",
        press_fn=lambda c: c.send_electronic_lock(1, "unlock"),
    ),
    SchargeButtonDescription(
        key="c_1_pnc_open",
        translation_key="c_1_pnc_open",
        name="Connector 1 PnC open",
        icon="mdi:flash-auto",
        press_fn=lambda c: c.send_pnc_set(1, "open"),
    ),
    SchargeButtonDescription(
        key="c_1_pnc_close",
        translation_key="c_1_pnc_close",
        name="Connector 1 PnC close",
        icon="mdi:card-account-details",
        press_fn=lambda c: c.send_pnc_set(1, "close"),
    ),
    SchargeButtonDescription(
        key="c_2_lock",
        translation_key="c_2_lock",
        name="Connector 2 Lock",
        icon="mdi:lock",
        press_fn=lambda c: c.send_electronic_lock(2, "lock"),
    ),
    SchargeButtonDescription(
        key="c_2_unlock",
        translation_key="c_2_unlock",
        name="Connector 2 Unlock",
        icon="mdi:lock-open",
        press_fn=lambda c: c.send_electronic_lock(2, "unlock"),
    ),
    SchargeButtonDescription(
        key="c_2_pnc_open",
        translation_key="c_2_pnc_open",
        name="Connector 2 PnC open",
        icon="mdi:flash-auto",
        press_fn=lambda c: c.send_pnc_set(2, "open"),
    ),
    SchargeButtonDescription(
        key="c_2_pnc_close",
        translation_key="c_2_pnc_close",
        name="Connector 2 PnC close",
        icon="mdi:card-account-details",
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
        """Poslat příkaz a NEZAMLČET, když ho wallbox odmítne.

        Do v0.7.0 se návratová hodnota zahazovala — přestože `press_fn` je
        typovaná jako `Awaitable[bool]`. Od v0.6.0, kdy `send_*` vrací skutečné
        potvrzení wallboxu (`result` z ACK), to znamenalo, že tlačítko odmítnutý
        příkaz **tiše spolklo** a tvářilo se úspěšně. Switche přitom na totéž
        hlásí chybu — stejná akce, dvě různá chování.
        """
        _LOGGER.info("Button pressed: %s", self.entity_description.key)
        ok = await self.entity_description.press_fn(self.coordinator)
        # `is False` schválně: výchozí press_fn vrací None (= nevíme), a to
        # není důvod křičet. Chyba jen na explicitní odmítnutí wallboxem.
        if ok is False:
            raise HomeAssistantError(
                f"Wallbox odmítl akci {self.entity_description.name!r} "
                f"— nic se nezměnilo. Příkaz přijme jen ve stavu, kdy dává smysl. "
                f"Stav konektorů: {self.coordinator.status_summary()}."
            )
