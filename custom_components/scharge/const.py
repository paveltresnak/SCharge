"""Konstanty pro scharge integraci."""

DOMAIN = "scharge"

# Config entry keys
CONF_SERIAL = "serial"              # S/N wallboxu (= chargeBoxSN v protocolu)
CONF_HOST = "host"                  # IP adresa wallboxu (na LAN)
CONF_WS_PORT = "ws_port"            # Port pro WS listener (default 41515)
CONF_BROADCAST_ADDR = "broadcast_addr"  # Broadcast IP (default 255.255.255.255)
CONF_BROADCAST_PORT = "broadcast_port"  # UDP broadcast port (default 3050)

DEFAULT_WS_PORT = 41515
DEFAULT_BROADCAST_ADDR = "255.255.255.255"
DEFAULT_BROADCAST_PORT = 3050
DEFAULT_BROADCAST_INTERVAL = 3.0    # sekund

# Protocol constants
WS_SUBPROTOCOL = "ocpp1.6"

# Jak dlouho čekat na ACK wallboxu u odeslaného příkazu (mt=5).
# Naměřeno ~0,3 s; 5 s je rezerva na zatížený link.
ACK_TIMEOUT = 5.0

# ─── Watchdog mrtvého linku ────────────────────────────────────────────────
# Wallbox drží TCP spojení „ESTABLISHED", ale přestane posílat data — HA pak
# hlásí connected=True a tiše servíruje zastaralé hodnoty. Pozorováno naživo
# 2026-07-16: link byl mrtvý 101 minut, auto celou dobu nabíjelo a regulační
# automatika jela na 100 minut starých číslech. Nic na to neupozornilo.
#
# Práh podle měření 2026-10-10 (12 h telemetrie, 8 745 vzorků napětí konektoru):
# medián mezery 3,9 s, 99 % do 10 s, nejdelší mezera ZDRAVÉHO linku 45 s.
# Všechny delší mezery byly mrtvé linky (> 180 s). Mezera mezi ZMĚNAMI napětí
# je navíc horní odhad mezery mezi zprávami. 60 s tedy mrtvý link pozná
# spolehlivě a o ~2,5 min dřív než původních 180 s (detekce 60–75 s místo 3–4 min).
WATCHDOG_INTERVAL = 15.0     # s — jak často kontrolovat
WATCHDOG_STALE = 60.0        # s — bez jediné zprávy = mrtvý link
WATCHDOG_COOLDOWN = 300.0    # s — minimum mezi dvěma zásahy, ať se watchdog
                             # nezacyklí, když je wallbox opravdu pryč

# LoadBalance range (W) — pro wallbox 22 kW
LOADBALANCE_MIN = 4000
LOADBALANCE_MAX = 14600
LOADBALANCE_STEP = 100

# Signal pro dispatch entity updates
SIGNAL_UPDATE = f"{DOMAIN}_update_{{entry_id}}"

# Akce na wallboxu
ACTION_HANDSHAKE = "HandShake"
ACTION_HEARTBEAT = "Heartbeat"
ACTION_DEVICE_DATA = "DeviceData"
ACTION_SYNCHRO_STATUS = "SynchroStatus"
ACTION_SYNCHRO_DATA = "SynchroData"
ACTION_NWIRE_TO_DICS = "NWireToDics"
ACTION_LOAD_BALANCE = "LoadBalance"
ACTION_ELECTRONIC_LOCK = "ElectronicLock"
ACTION_PNC_SET = "PnCSet"
ACTION_GET_RECORD = "GetRecord"
