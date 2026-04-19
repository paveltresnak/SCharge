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

### Sensors (per konektor 1 + 2)

Wallbox má 2 zásuvky (konektory). V wire protokolu (JSON) jsou označené
`connectorMain` / `connectorVice`, ale v UI (entity IDs, display názvy) používáme
čísla `1` / `2` podle pořadí fyzických zásuvek na zařízení.

| Entity | Jednotka | Popis |
|---|---|---|
| `sensor.scharge_1_voltage` | V | Napětí konektor 1 |
| `sensor.scharge_1_current` | A | Proud konektor 1 |
| `sensor.scharge_1_power` | W | Okamžitý výkon konektor 1 |
| `sensor.scharge_1_energy_session` | kWh | Energie aktuální session |
| `sensor.scharge_1_charging_time` | text | Čas nabíjení (H:M:S) |
| `sensor.scharge_1_status` | text | idle / charging / ... |

Pro **konektor 2** to samé (`sensor.scharge_2_voltage`, ...).

### Binary sensors

| Entity | Popis |
|---|---|
| `binary_sensor.scharge_1_connected` | Auto je připojené (konektor 1) |
| `binary_sensor.scharge_1_lock` | Elektronický zámek konektoru 1 |
| `binary_sensor.scharge_1_pnc` | Plug-and-Charge stav (konektor 1) |
| `binary_sensor.scharge_2_connected` | Auto je připojené (konektor 2) |
| `binary_sensor.scharge_2_lock` | Elektronický zámek konektoru 2 |
| `binary_sensor.scharge_2_pnc` | Plug-and-Charge stav (konektor 2) |
| `binary_sensor.scharge_nwire_exist` | N-Wire detekován (diagnostika) |
| `binary_sensor.scharge_nwire_closed` | N-Wire relé sepnuto (diagnostika) |

### Globální sensors

| Entity | Jednotka | Popis |
|---|---|---|
| `sensor.scharge_loadbalance` | W | Aktuální max výkon |
| `sensor.scharge_total_power` | kWh | Kumulativní energie |
| `sensor.scharge_charge_times` | count | Počet session |
| `sensor.scharge_meter_voltage` | V | Napětí externího MID metru (pokud je) |
| `sensor.scharge_meter_current` | A | Proud externího MID metru |
| `sensor.scharge_meter_power` | W | Výkon externího MID metru |
| `sensor.scharge_rssi` | dBm | WiFi signál wallboxu |
| `sensor.scharge_sw_version` | text | Firmware verze |
| `sensor.scharge_evse_type` | text | Model / typ wallboxu |

### Number (ovládání)

| Entity | Rozsah | Popis |
|---|---|---|
| `number.scharge_loadbalance` | 4000–14600 W | Slider pro nastavení max výkonu (PV-driven modulace) |

### Buttons (ovládání)

| Entity | Akce |
|---|---|
| `button.scharge_1_lock_btn` | Zamknout konektor 1 |
| `button.scharge_1_unlock_btn` | Odemknout konektor 1 |
| `button.scharge_1_pnc_open_btn` | Plug-and-Charge OPEN — konektor 1 (bez auth) |
| `button.scharge_1_pnc_close_btn` | Plug-and-Charge CLOSE — konektor 1 (auth required) |
| `button.scharge_2_lock_btn` | Zamknout konektor 2 |
| `button.scharge_2_unlock_btn` | Odemknout konektor 2 |
| `button.scharge_2_pnc_open_btn` | Plug-and-Charge OPEN — konektor 2 |
| `button.scharge_2_pnc_close_btn` | Plug-and-Charge CLOSE — konektor 2 |

## Automatizace — PV-driven modulace

Základní automatizace pro modulaci nabíjecího výkonu dle solárního přebytku:

```yaml
- alias: "Wallbox - PV modulace"
  trigger:
    - platform: time_pattern
      seconds: /30
  condition:
    - condition: state
      entity_id: binary_sensor.scharge_1_connected
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

Kompletní historie změn: viz [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT — viz `LICENSE`.

## Poděkování

- `matemat13/ha_s-charge` — prvotní protokolová analýza (WebSocket/JSON discovery),
  která byla klíčovým vodítkem pro kompletní reverse engineering
- Claude.AI — spolupráce na návrhu a implementaci
