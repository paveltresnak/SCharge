# Changelog

All notable changes to this project will be documented in this file.

Format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
