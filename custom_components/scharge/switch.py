"""Switch entity: sdílení wallboxu s mobilní aplikací + start/stop nabíjení."""
from __future__ import annotations

import logging
import time

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
#
# WHITELIST záměrně. Pozorovaný slovník (2026-07-16, FW E3P3_H_1.1.1_R5190,
# poskládaný z hlášení uživatelů — výrobce ho nikde nedokumentuje):
#   idle      — kabel odpojený, nic neběží
#   wait      — PŘECHODNĚ po Authorize Start, než auto začne brát proud (~4 s)
#   charging  — reálně nabíjí
#   finish    — session skončila, ale kabel zůstal v zásuvce. Sem se dostaneme
#               po našem Stopu, i když session ukončí samo auto (limit SoC).
#
# Ověřený stavový automat (2026-07-16, plný cyklus 2× po sobě):
#   charging --Stop--> finish --Start--> wait --> charging
# Start z 'finish' tedy FUNGUJE. (v0.7.2 tvrdila opak — mylně, viz v0.7.3.)
#
# Do whitelistu patří jen `charging`. `finish` je přesně ten stav, kvůli
# kterému v0.6.0 padala: blacklist `!= 'idle'` ho hlásil jako „nabíjím",
# uživatel dal Stop a wallbox ho odmítl (žádná session neběžela).
# Přechodný `wait` řeší _STARTING_GRACE níže, ne whitelist.
#
# Neznámý stav = „nenabíjí" (bezpečnější směr).
CHARGING_STATUSES = {"charging"}

# Jak dlouho po POTVRZENÉM Startu držet switch na `on`, i když telemetrie
# hlásí `wait`. Bez toho switch po stisknutí cvakne zpět na off a teprve pak
# na on — uživatel to čte jako „nefungovalo to". Po vypršení rozhoduje zase
# telemetrie: když auto nabíjet nezačne, switch poctivě spadne na off.
_STARTING_GRACE = 60.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SchargeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [SchargeBridgeSwitch(coordinator)]
    for cid in (1, 2):
        entities += [
            SchargeChargingSwitch(coordinator, cid),
            SchargeLockSwitch(coordinator, cid),
            SchargePnCSwitch(coordinator, cid),
        ]
    async_add_entities(entities)


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
        # monotonic deadline doby hájení po Startu (viz _STARTING_GRACE), nebo None
        self._starting_until: float | None = None

    @property
    def _charge_status(self) -> str | None:
        return self.coordinator.connector_status(self._connector_id)

    @property
    def is_on(self) -> bool | None:
        """Nabíjí se na tomhle konektoru?

        Pořadí: reálné nabíjení > rozjezd po Startu > telemetrie > optimismus.

        `wait` je záměrně mimo whitelist — znamená totiž jak „rozjíždím se",
        tak „kabel visí nad mrtvou session". Rozlišit je nelze podle stavu,
        jen podle toho, jestli jsme právě dali Start; proto _STARTING_GRACE.

        Telemetrie má jinak přednost před optimistickou hodnotou — jinak by
        switch po Startu zůstal viset na `on`, i když auto nabíjet nezačne
        nebo samo skončí na svém limitu SoC.
        """
        status = (self._charge_status or "").strip().lower()

        if status in CHARGING_STATUSES:
            return True

        # Rozjezd: Start potvrzen, auto ještě nebere proud (`wait`).
        if self._starting_until is not None:
            if time.monotonic() < self._starting_until:
                return True
            self._starting_until = None      # doba hájení vypršela

        if status:
            return False
        return self._optimistic

    async def _authorize(self, purpose: str) -> None:
        current = self.coordinator.last_authorized_current.get(
            self._connector_id, DEFAULT_AUTHORIZE_CURRENT)
        ok = await self.coordinator.send_authorize(self._connector_id, purpose, current)
        if not ok:
            raise HomeAssistantError(
                f"Wallbox odmítl Authorize {purpose} na konektoru "
                f"{self._connector_id} ({current} A) — stav nabíjení se nezměnil. "
                f"Aktuální stav konektoru: {self._charge_status!r}. "
                + self._reject_hint(purpose)
            )

    def _reject_hint(self, purpose: str) -> str:
        """Rada podle stavu — obecné „nedává to smysl" uživateli nepomůže."""
        status = (self._charge_status or "").strip().lower()
        if status == "finish":
            # 'finish' = session skončila, kabel zůstal v zásuvce. Start z tohoto stavu
            # NORMÁLNĚ FUNGUJE (ověřeno 2026-07-16: finish → wait → charging, opakovaně).
            # Když ho wallbox přesto odmítne, stav za to nemůže — nechce auto.
            return (
                "Session skončila, kabel zůstal v zásuvce. Start z tohoto stavu obvykle "
                "funguje, takže odmítnutí nejspíš znamená, že další nabíjení nepřijme "
                "AUTO — typicky když dosáhlo svého limitu SoC. Zkontroluj limit v autě; "
                "pomoct může i odpojit a znovu zapojit kabel."
            )
        if status == "idle":
            return "Konektor je prázdný — bez zapojeného auta není co spustit ani zastavit."
        if status == "charging" and purpose == "Start":
            return "Už se nabíjí, Start je zbytečný. Proud měň sliderem „nabíjecí proud“."
        return ("Wallbox příkaz přijme jen ve stavu, kdy dává smysl: Stop když session "
                "běží, Start když ji lze založit.")
        started = purpose == "Start"
        self._optimistic = started
        # Start: drž `on` přes fázi `wait`, než auto začne brát proud.
        # Stop: dobu hájení zahoď, ať switch může hned spadnout na off.
        self._starting_until = (time.monotonic() + _STARTING_GRACE) if started else None
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        _LOGGER.info("Charging switch ON — konektor %d", self._connector_id)
        await self._authorize("Start")

    async def async_turn_off(self, **kwargs) -> None:
        _LOGGER.info("Charging switch OFF — konektor %d", self._connector_id)
        await self._authorize("Stop")


class _ConfirmedConnectorSwitch(SchargeEntity, SwitchEntity):
    """Báze pro switche, které jen překlápí jedno pole konektoru.

    Sdílí pravidlo celé integrace: **nepřepínat optimisticky**. Stav se změní
    až když ho potvrdí telemetrie wallboxu; když wallbox příkaz odmítne
    (`result: false`), vyhodí se HomeAssistantError a stav se nehne.

    Potomek dodá: `_attr_field` (pole v telemetrii), `_command(on: bool)`
    a `_label`.
    """

    _attr_has_entity_name = True
    _attr_field: str = ""
    _label: str = ""

    def __init__(self, coordinator: SchargeCoordinator, connector_id: int,
                 key: str) -> None:
        super().__init__(coordinator)
        self._connector_id = connector_id
        self._attr_unique_id = f"{coordinator.serial}_c_{connector_id}_{key}"
        self._attr_translation_key = f"c_{connector_id}_{key}"

    @property
    def is_on(self) -> bool | None:
        val = self.coordinator.connector_attr(self._connector_id, self._attr_field)
        return None if val is None else bool(val)

    async def _command(self, turn_on: bool) -> bool:
        raise NotImplementedError

    async def _apply(self, turn_on: bool) -> None:
        _LOGGER.info("%s %s — konektor %d", self._label,
                     "ON" if turn_on else "OFF", self._connector_id)
        if not await self._command(turn_on):
            raise HomeAssistantError(
                f"Wallbox odmítl změnu {self._label!r} na konektoru "
                f"{self._connector_id} — stav se nezměnil."
            )
        # Stav nepřepisujeme: přijde s další telemetrií (á ~10 s).
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        await self._apply(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._apply(False)


class SchargeLockSwitch(_ConfirmedConnectorSwitch):
    """Elektronická západka konektoru. `on` = ZAMČENO.

    ⚠️ Pozor na inverzi: `binary_sensor..._lock` má `device_class=lock`, kde
    HA konvence je `on` = ODEMČENO (device classy mají „problem semantic").
    Proto tam v kódu je `not lock_status`. Tady je to switch bez device_class,
    kde uživatel čeká `on` = zamčeno → `lock_status` se bere **bez inverze**.
    Obě entity tak ukazují opačnou hodnotu a je to správně.
    """

    _attr_field = "lock_status"
    _label = "Zámek"
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: SchargeCoordinator, connector_id: int) -> None:
        super().__init__(coordinator, connector_id, "lock_switch")

    async def _command(self, turn_on: bool) -> bool:
        return await self.coordinator.send_electronic_lock(
            self._connector_id, "lock" if turn_on else "unlock")


class SchargePnCSwitch(_ConfirmedConnectorSwitch):
    """Plug-and-Charge. `on` = nabíjení začne po zapojení samo (bez autorizace).

    Wire protokol tomu říká `open` (= bez autorizace) / `close` (= autorizace
    nutná), což je matoucí — proto tu překlad na on/off.

    `off` je scénář „nabíjej jen na povel z HA": auto se po zapojení samo
    nerozjede a nabíjení spustíš switchem *Nabíjení konektor X* (nebo, pozor,
    i pohnutím slideru proudu — viz number.py).
    """

    _attr_field = "pnc_status"
    _label = "Plug and Charge"
    # Shodná ikona s tlačítkem „PnC open" — PnC není zámek (do v0.7.1 měla
    # obě PnC tlačítka lock/lock-open-variant, tedy k nerozeznání od západky).
    _attr_icon = "mdi:flash-auto"

    def __init__(self, coordinator: SchargeCoordinator, connector_id: int) -> None:
        super().__init__(coordinator, connector_id, "pnc_switch")

    async def _command(self, turn_on: bool) -> bool:
        return await self.coordinator.send_pnc_set(
            self._connector_id, "open" if turn_on else "close")
