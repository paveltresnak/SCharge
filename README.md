# SCharge — Home Assistant integration pro Wallbox S-charge

Home Assistant custom component pro wallboxy **Schlieger S-charge** /
**Joint Tech JNT-EVCD2** (a podobné OEM rebrandy). Umožňuje plné monitorování
a ovládání přes lokální WebSocket protokol (`ocpp1.6` subprotocol).

**Autor:** Pavel Třešňák (kompletní reverse engineering + implementace ve spolupráci
s Claude.AI — viz [projekt WallBox](https://github.com/paveltresnak/SCharge/tree/main/WallBox) pro reverse engineering dokumentaci).

## Protokol

Wallbox běží jako **WebSocket klient** — sám se připojí na discovery broadcast
z HA strany. Není potřeba žádný cloud, BLE ani externí hardware.

```
┌─────────────────────────────────────┐
│  Home Assistant                     │
│    custom_components/scharge/       │
│     ├── WS server (port 41515)      │
│     └── UDP broadcast (port 3050)   │
└──────────┬──────────────────────────┘
           │
           │  1. UDP broadcast "UDPHandShake" (source port 3050)
           │  2. Wallbox connects back via WebSocket (ocpp1.6)
           │  3. Wallbox sends telemetry (Heartbeat, DeviceData,
           │     SynchroStatus, SynchroData, NWireToDics)
           │  4. HA ACKs + sends LoadBalance / Lock / PnC commands
           ▼
┌─────────────────────────────────────┐
│  Wallbox (192.168.78.x)             │
│  S/N: 21003222073300155             │
└─────────────────────────────────────┘
```

## Instalace

### Manuální

1. Zkopírujte složku `custom_components/scharge/` do `/config/custom_components/`
   na Vašem Home Assistant (na Synology typicky:
   `/volume1/docker/homeassistant/config/custom_components/`)
2. **Restart Home Assistant**
3. **Settings → Devices & Services → + Add Integration → S-charge Wallbox**
4. Zadejte sériové číslo wallboxu (např. `21003222073300155`)

### HACS (po publikaci)

1. HACS → Integrations → 3-tečky → Custom repositories
2. Add `https://github.com/paveltresnak/SCharge` jako Integration
3. Download → Restart HA → Add Integration

## Požadavky

- Home Assistant Container / OS / Supervised (network_mode: host — výchozí)
- Python `websockets>=12.0` (automaticky nainstaluje HA)
- Wallbox + HA na stejné L2 broadcast doméně (UDP discovery)

## Poskytované entity

### Sensors (per konektor Main + Vice)

| Entity | Jednotka | Popis |
|---|---|---|
| `sensor.scharge_main_voltage` | V | Napětí |
| `sensor.scharge_main_current` | A | Proud |
| `sensor.scharge_main_power` | W | Okamžitý výkon |
| `sensor.scharge_main_energy` | kWh | Energie session |
| `sensor.scharge_main_charging_time` | text | Čas nabíjení (H:M:S) |
| `sensor.scharge_main_status` | text | idle / charging / ... |

Pro **Vice** konektor to samé.

### Binary sensors

| Entity | Popis |
|---|---|
| `binary_sensor.scharge_main_connected` | Auto je připojené |
| `binary_sensor.scharge_main_lock` | Elektronický zámek konektoru |
| `binary_sensor.scharge_main_pnc` | Plug-and-Charge stav |

### Globální sensors

| Entity | Jednotka | Popis |
|---|---|---|
| `sensor.scharge_loadbalance` | W | Aktuální max výkon |
| `sensor.scharge_total_power` | kWh | Kumulativní energie |
| `sensor.scharge_charge_times` | count | Počet session |
| `sensor.scharge_rssi` | dBm | WiFi signál wallboxu |
| `sensor.scharge_sw_version` | text | Firmware verze |

### Number (ovládání)

| Entity | Rozsah | Popis |
|---|---|---|
| `number.scharge_loadbalance` | 4000–14600 W | Slider pro nastavení max výkonu (PV-driven modulace) |

### Buttons (ovládání)

| Entity | Akce |
|---|---|
| `button.scharge_main_lock_btn` | Zamknout konektor 1 |
| `button.scharge_main_unlock_btn` | Odemknout konektor 1 |
| `button.scharge_main_pnc_open_btn` | Plug-and-Charge OPEN (bez auth) |
| `button.scharge_main_pnc_close_btn` | Plug-and-Charge CLOSE (auth required) |
| (stejné pro Vice konektor) | |

## Automatizace — PV-driven modulace

Základní automatizace pro modulaci nabíjecího výkonu dle solárního přebytku:

```yaml
- alias: "Wallbox - PV modulace"
  trigger:
    - platform: time_pattern
      seconds: /30
  condition:
    - condition: state
      entity_id: binary_sensor.scharge_main_connected
      state: "on"
  action:
    - variables:
        surplus: >
          {{ states('sensor.sofar_pv_prumer_5_min') | float(0)
             - states('sensor.dum_spotreba_bez_wb_virivka') | float(0) }}
        target: >
          {% if surplus < 4000 %} 4000
          {% elif surplus > 11000 %} 11000
          {% else %} {{ surplus | int }}
          {% endif %}
    - service: number.set_value
      target:
        entity_id: number.scharge_loadbalance
      data:
        value: "{{ target }}"
```

## Changelog

### 0.1.0 (2026-04-19)

- První release
- Protokol WebSocket + `ocpp1.6` + JSON envelope (reverse-engineered)
- Sensor entities (voltage, current, power, energy, charging time, status)
- Binary sensors (connected, lock, pnc)
- Number entity pro LoadBalance
- Buttons pro Lock/Unlock/PnC open/close
- Config flow přes UI, české + anglické překlady

## Licence

MIT — viz `LICENSE`.

## Poděkování

- `matemat13/ha_s-charge` — prvotní protokolová analýza (WebSocket/JSON discovery),
  která byla klíčovým vodítkem pro kompletní reverse engineering
- Claude.AI — spolupráce na návrhu a implementaci
