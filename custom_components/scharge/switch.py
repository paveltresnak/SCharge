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

# chargeStatus hodnoty, které znamenají „reálně nabíjí".
# WHITELIST záměrně: pozorované hodnoty jsou zatím 'idle' (nenabíjí) a
# 'charging' (nabíjí), ale slovník má i mezistavy (kabel zapojený, session
# skončená autem na jeho limitu SoC). Ty NEJSOU 'idle' — blacklist
# `!= 'idle'` je proto hlásil jako nabíjení a Stop pak wallbox odmítal.
# Když se objeví další stav, je bezpečnější ho brát jako „nenabíjí".
CHARGING_STATUSES = {"charging"}


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

    Ověřeno na reálném voze (2026-07-16, uživatel integrace): Start i Stop
    fungují opakovaně. `Authorize Start` **zakládá session** — nejen škrtí
    proud; s vypnutým PnC je to jediná cesta, jak nabíjení rozjet z HA.
    (Pozor: proto i pohyb sliderem `nabíjecí proud` nabíjení nastartuje.)

    Wallbox příkaz přijme jen ve stavu, kdy dává smysl — jinak ACKne
    `result: false` a NIC neudělá. Proto switch nikdy nepřepíná stav
    optimisticky: přepne se až po `result: true`, jinak vyhodí
    HomeAssistantError. Radši viditelná chyba než tiché tvrzení, že se
    něco stalo.
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
        return self.coordinator.connector_status(self._connector_id)

    @property
    def is_on(self) -> bool | None:
        """Nabíjí se na tomhle konektoru?

        WHITELIST, ne blacklist: `on` výhradně pro CHARGING_STATUSES.

        Dřív to bylo `chargeStatus != 'idle'` a to byla chyba. Slovník má
        i mezistavy (kabel zapojený, ale session skončila — třeba když auto
        dosáhne svého limitu SoC). Ty nejsou 'idle', takže se switch tvářil
        „nabíjím", uživatel dal stop a wallbox ho odmítl (`result: false`),
        protože žádná session neběžela. Whitelist je proti neznámým stavům
        odolný: co není prokazatelně nabíjení, je vypnuto.

        Telemetrie má přednost před optimistickou hodnotou — jinak by switch
        po Startu zůstal viset na `on`, i když auto nabíjet nezačne nebo samo
        skončí.
        """
        status = self._charge_status
        if status is not None:
            return str(status).strip().lower() in CHARGING_STATUSES
        return self._optimistic

    async def _authorize(self, purpose: str) -> None:
        current = self.coordinator.last_authorized_current.get(
            self._connector_id, DEFAULT_AUTHORIZE_CURRENT)
        ok = await self.coordinator.send_authorize(self._connector_id, purpose, current)
        if not ok:
            raise HomeAssistantError(
                f"Wallbox odmítl Authorize {purpose} na konektoru "
                f"{self._connector_id} ({current} A) — stav nabíjení se nezměnil. "
                f"Wallbox tenhle příkaz přijme jen ve stavu, kdy dává smysl: Stop "
                f"když session běží, Start když ji lze založit. Časté příčiny: auto "
                f"není zapojené, session už sama skončila (auto dosáhlo svého limitu "
                f"SoC), nebo se právě nabíjí a Start je zbytečný. Aktuální stav "
                f"konektoru: {self._charge_status!r}."
            )
        self._optimistic = (purpose == "Start")
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Charging switch ON — konektor %d", self._connector_id)
        await self._authorize("Start")

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Charging switch OFF — konektor %d", self._connector_id)
        await self._authorize("Stop")
