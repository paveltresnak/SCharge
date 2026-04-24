# Changelog

All notable changes to this project will be documented in this file.

Format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.5.1] — 2026-04-24

### Fixed
- **`number.wallbox_s_charge_konektor_{1,2}_nabijeci_proud` zaseknutý na 0** — wallbox nereportuje `reserveCurrent` ve `SynchroStatus` konzistentně (často 0), takže number.native_value byla vždy 0 → zavírací smyčka s PCC feedback automatikou nefungovala (condition `target != current` byla pořád true, nic se neměnilo).
- **Fix:** Optimistic tracking v `SchargeChargeCurrent`. Po úspěšném `Authorize Start` si entity pamatuje hodnotu lokálně (`_optimistic_value`) a vrací ji v `native_value` (fallback na `reserveCurrent` jen pokud optimistic není).
- PCC feedback automatika teď správně konverguje bez potřeby wallboxu echo-back.
- **Oprava jednotky výkonu konektoru** — wallbox posílá `power` v kW (ověřeno V×I×√3), ale sensor byl deklarován jako `UnitOfPower.WATT`. Opraveno na `UnitOfPower.KILO_WATT` pro `c_{1,2}_power` i `meter_power`. Precision upraven na 2 des. místa (zobrazení 10.75 kW místo 11 W).

## [0.5.0] — 2026-04-23

### Added
- **`Authorize` command** (`actions.make_authorize`, `coordinator.send_authorize`) — Start/Stop nabíjecí session s přesně zadaným proudem (A). Reverzováno z [matemat13/ha_s-charge](https://github.com/matemat13/ha_s-charge).
- **Per-connector `number.wallbox_s_charge_connector_{1,2}_charge_current`** — slider 6-32 A v HA UI. Posílá `Authorize Start` s novým proudem → wallbox mění aktuálně nabíjecí proud auta.
- Real per-session throttle, **nezávislý na `LoadBalance`** (ta je building-level ceiling).

### Why
LoadBalance (W) jsme dosud používali jako jediný throttle, ale testování ukázalo že wallbox ji často resetuje zpět na 14600 W a proto auto tahá svou OBC max (11 kW) bez ohledu na LB. Authorize příkaz s `current` parameterem reálně řídí proud na PWM signálu ke autu.

### Design
- `native_value` čte `reserveCurrent` ze `SynchroStatus` (target v A)
- `async_set_native_value(A)` pošle `Authorize(connector_id, "Start", A)` — funguje i během aktivního charging, throttluje za chodu

## [0.4.1] — 2026-04-19

### Added
- **Kompletní překlady entit** — všech 38 entit (sensors, binary_sensors, buttons, number, switch) má `translation_key` + záznamy v `cs.json`/`en.json`.
  Dříve byl přeložený jen config flow; entity názvy byly anglicky.
  Teď má HA v češtině názvy jako „Konektor 1 napětí", „Počet session", „Můstek HA", „Omezení výkonu" apod.

## [0.4.0] — 2026-04-19

### Added
- **Bridge switch** (`switch.wallbox_s_charge_bridge`) — umožňuje dočasně uvolnit wallbox pro mobilní aplikaci S-charge.
  Wallbox drží jen jednu aktivní WebSocket session — když je HA připojený, mobil se nepřipojí.
  OFF → HA zastaví UDP broadcast a zavře aktivní WS. Wallbox je uvolněn pro mobilní app. Entity se přepnou na `unavailable`.
  ON *(default)* → HA obnoví broadcast, wallbox se do ~3 s vrátí zpět k HA.
  Switch je v kategorii CONFIG (zobrazuje se u konfiguračních entit integrace).

## [0.3.1] — 2026-04-19

### Fixed
- **Connector Lock binary_sensor invertovaný** — HA konvence `BinarySensorDeviceClass.LOCK` znamená `on = odemčeno, off = zamčeno` (problem-state semantika).
  Wallbox ale reportuje `lock_status = True` když je fyzicky zamčený → po zamčení se na dashboardu zobrazovalo „Odemčeno" a naopak.
  Oprava: `value_fn` invertuje `lock_status` před předáním HA. Commandy (`ElectronicLock lock/unlock`) byly po celou dobu správné, jen zobrazení bylo obrácené.

## [0.3.0] — 2026-04-19

### ⚠️ Breaking changes
- **Konektory přejmenovány `main`/`vice` → `1`/`2`.** Všechny entity IDs změněny:
  - `sensor.scharge_main_*` → `sensor.scharge_1_*`
  - `sensor.scharge_vice_*` → `sensor.scharge_2_*`
  - Stejně pro `binary_sensor.*`, `button.*`.
- Display názvy: `Main Voltage` → `Connector 1 Voltage` atd.
- Pokud máš automation odkazující na staré entity IDs, bude je potřeba přemapovat.
- Wire protokol (`connectorMain`/`connectorVice` v JSONu wallboxu) zůstává beze změny — jen UI názvy.

### Fixed
- **Kritický bug:** `coordinator.async_stop` čekal infinite na `ws_server.wait_closed()`,
  protože wallbox nezavírá WS graceful. Teď má timeout 3 s na server close +
  2 s na active WS close. Bez fixu bylo reload/unload integrace nemožné.
- `README.md`: odstraněn inline changelog block (duplicita s CHANGELOG.md).
  README nyní odkazuje na CHANGELOG.md.

## [0.2.0] — 2026-04-19

### Changed
- `coordinator.py`: "Overwriting existing WS session" downgraded from WARNING to DEBUG log level.
  To je normální chování — wallbox občas reconnectuje před tím, než starý WS session graceful-closes.
  Zbytečný warning spam v HA logu.

### Added
- `CHANGELOG.md` — od teď budeme udržovat živý changelog.

### Notes
- Verze je stále **prerelease** (čeká na testování s reálným nabíjením Peugeot e-2008).
- Monitoring telemetrie ověřen (DeviceData, SynchroStatus, SynchroData).
- `LoadBalance` command ověřen (change 14600→12000→14600 W za ~10 s).
- Start/Stop session a `ElectronicLock`/`PnCSet` ještě nebylo testováno s reálným autem.

## [0.1.0] — 2026-04-19

### Added
- První verze HA custom integrace pro wallbox Joint Tech JNT-EVCD2 / Schlieger S-charge.
- WebSocket server + UDP broadcast discovery (`ocpp1.6` subprotocol).
- Protokol kompletně reverzovaný (BLE snoop + WiFi tcpdump).
- Config flow přes HA UI (IP + S/N, CS + EN překlady).
- 12 sensorů: voltage, current, power, energy per konektor, meter, RSSI, FW, ...
- 8 binary sensorů: connected, lock, PnC per konektor, NWire.
- `LoadBalance` slider (4000-14600 W) pro PV-driven modulaci.
- 8 buttons: Lock/Unlock/PnC open/close pro oba konektory.
- HACS-compatible struktura (hacs.json, icon, logo, dokumentace).

### Reverse-engineering artefacts
- Pcap z HCI snoop logu (BLE, 70 JSON zpráv).
- Pcap z WiFi capture (WebSocket + ocpp1.6).
- 60/60 unit testů protokolu pass (v WallBox/pico/tests/).
