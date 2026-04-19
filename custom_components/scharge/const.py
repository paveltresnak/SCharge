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
