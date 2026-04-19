"""
S-charge action-specific payload helpers.

Decoders (for RX): parse incoming payload dicts into structured objects.
Builders (for TX): construct outgoing ``Message`` objects for known actions.

See protocol specification in docs/2026-04-19-wallbox-integrace-dokumentace.md
section 11 for payload structures.
"""

try:
    import utime as _time
except ImportError:
    import time as _time

from .protocol import Message


# ─── Decoders (RX payloads) ────────────────────────────────────────────────────


def _f(val, default=0.0):
    """Safely convert to float (payloads use string-encoded numbers)."""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _i(val, default=0):
    """Safely convert to int."""
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


class ConnectorInfo(object):
    """Subfield in DeviceData for each connector."""
    __slots__ = ("mini_current", "max_current", "connector_status",
                 "lock_status", "pnc_status")

    def __init__(self, raw):
        raw = raw or {}
        self.mini_current = _i(raw.get("miniCurrent"))
        self.max_current = _i(raw.get("maxCurrent"))
        self.connector_status = _i(raw.get("connectorStatus"))
        self.lock_status = bool(raw.get("lockStatus"))
        self.pnc_status = bool(raw.get("PncStatus"))

    def to_dict(self):
        return {
            "mini_current": self.mini_current,
            "max_current": self.max_current,
            "connector_status": self.connector_status,
            "lock_status": self.lock_status,
            "pnc_status": self.pnc_status,
        }


class DeviceData(object):
    """RX payload of ``DeviceData`` action (received once after handshake)."""
    __slots__ = ("charge_box_sn", "connector_main", "connector_vice",
                 "s_version", "h_version", "load_balance", "charge_times",
                 "cumulative_time", "total_power", "rssi", "evse_type",
                 "connector_number", "evse_phase", "is_has_lock", "is_has_meter")

    def __init__(self, payload):
        self.charge_box_sn = payload.get("chargeBoxSN")
        self.connector_main = ConnectorInfo(payload.get("connectorMain"))
        self.connector_vice = ConnectorInfo(payload.get("connectorVice"))
        self.s_version = payload.get("sVersion")
        self.h_version = payload.get("hVersion")
        self.load_balance = _i(payload.get("loadbalance"))
        self.charge_times = _i(payload.get("chargeTimes"))
        self.cumulative_time = _i(payload.get("cumulativeTime"))
        self.total_power = _i(payload.get("totalPower"))
        self.rssi = _i(payload.get("rssi"))
        self.evse_type = payload.get("evseType")
        self.connector_number = _i(payload.get("connectorNumber"))
        self.evse_phase = payload.get("evsePhase")
        self.is_has_lock = bool(payload.get("isHasLock"))
        self.is_has_meter = bool(payload.get("isHasMeter"))


class ConnectorTelemetry(object):
    """Subfield in SynchroData for each connector — live electrical readings."""
    __slots__ = ("voltage", "current", "power", "electric_work", "charging_time")

    def __init__(self, raw):
        raw = raw or {}
        # Note: all numeric values are STRINGS in the wire format
        self.voltage = _f(raw.get("voltage"))
        self.current = _f(raw.get("current"))
        self.power = _f(raw.get("power"))
        self.electric_work = _f(raw.get("electricWork"))
        self.charging_time = raw.get("chargingTime", "0:0:0")

    def to_dict(self):
        return {
            "voltage": self.voltage,
            "current": self.current,
            "power": self.power,
            "electric_work": self.electric_work,
            "charging_time": self.charging_time,
        }


class MeterInfo(object):
    """External MID meter readings (if connected)."""
    __slots__ = ("voltage", "current", "power")

    def __init__(self, raw):
        raw = raw or {}
        self.voltage = _f(raw.get("voltage"))
        self.current = _f(raw.get("current"))
        self.power = _f(raw.get("power"))


class SynchroData(object):
    """RX payload of ``SynchroData`` action (live telemetry, ~every 5 s)."""
    __slots__ = ("charge_box_sn", "connector_main", "connector_vice", "meter_info")

    def __init__(self, payload):
        self.charge_box_sn = payload.get("chargeBoxSN")
        self.connector_main = ConnectorTelemetry(payload.get("connectorMain"))
        self.connector_vice = ConnectorTelemetry(payload.get("connectorVice"))
        self.meter_info = MeterInfo(payload.get("meterInfo"))


class ConnectorStatus(object):
    """Subfield in SynchroStatus."""
    __slots__ = ("connection_status", "charge_status", "status_code",
                 "start_time", "end_time", "reserve_current")

    def __init__(self, raw):
        raw = raw or {}
        self.connection_status = bool(raw.get("connectionStatus"))
        self.charge_status = raw.get("chargeStatus", "idle")
        self.status_code = _i(raw.get("statusCode"))
        self.start_time = raw.get("startTime", "-")
        self.end_time = raw.get("endTime", "-")
        self.reserve_current = _i(raw.get("reserveCurrent"))


class SynchroStatus(object):
    """RX payload of ``SynchroStatus`` action (connector state on change)."""
    __slots__ = ("charge_box_sn", "connector_main", "connector_vice")

    def __init__(self, payload):
        self.charge_box_sn = payload.get("chargeBoxSN")
        self.connector_main = ConnectorStatus(payload.get("connectorMain"))
        self.connector_vice = ConnectorStatus(payload.get("connectorVice"))


class NWireToDics(object):
    """RX payload of ``NWireToDics`` action (neutral wire detection)."""
    __slots__ = ("charge_box_sn", "n_wire_exist", "n_wire_closed")

    def __init__(self, payload):
        self.charge_box_sn = payload.get("chargeBoxSN")
        self.n_wire_exist = bool(payload.get("NWireExist"))
        self.n_wire_closed = bool(payload.get("NWireClosed"))


# ─── Dispatch table for decoding RX actions ────────────────────────────────────

RX_DECODERS = {
    "DeviceData": DeviceData,
    "SynchroData": SynchroData,
    "SynchroStatus": SynchroStatus,
    "NWireToDics": NWireToDics,
}


def decode_payload(message):
    """Return a typed payload object for a known RX action, or None if unknown.

    ``message`` is a ``Message`` instance with ``message_type_id == "5"`` (mt=5
    request) and a recognized ``action``.
    """
    if not message.is_request or not message.action:
        return None
    decoder = RX_DECODERS.get(message.action)
    if decoder is None:
        return None
    return decoder(message.payload)


# ─── Builders (TX) ─────────────────────────────────────────────────────────────


def _iso8601_utc(ts=None):
    """Format Unix timestamp as ISO8601 UTC string 'YYYY-MM-DDTHH:MM:SSZ'.

    Avoids datetime module (unavailable in MicroPython).
    """
    if ts is None:
        ts = _time.time()
    # time.gmtime returns struct_time (y, mo, d, h, mi, s, wd, yd, [isdst])
    g = _time.gmtime(int(ts))
    # MicroPython: g[0..5], CPython: same
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (g[0], g[1], g[2], g[3], g[4], g[5])


def make_handshake(state, timestamp=None):
    """Construct initial HandShake request.

    ``state`` is a ``ProtocolState`` instance; provides charge_box_sn, user_id.
    ``timestamp`` — optional Unix seconds for the ``currentTime`` field;
    if None, ``time.time()`` is used.

    Returns a ``Message`` ready to be serialized + chunked + transmitted.
    """
    return Message(
        message_type_id="5",
        unique_id=state.next_unique_id(),
        action="HandShake",
        payload={
            "userId": state.user_id,
            "chargeBoxSN": state.charge_box_sn,
            "currentTime": _iso8601_utc(timestamp),
            "connectionKey": state.charge_box_sn,  # S/N acts as auth key
        },
    )


def make_load_balance(state, value_watts):
    """Set max charging power in watts (4000-14600 W observed range).

    This is the primary mechanism for PV-driven current modulation.
    """
    return Message(
        message_type_id="5",
        unique_id=state.next_unique_id(),
        action="LoadBalance",
        payload={
            "userId": state.user_id,
            "chargeBoxSN": state.charge_box_sn,
            "value": int(value_watts),
        },
    )


def make_electronic_lock(state, connector_id, purpose):
    """Lock/unlock a connector's electronic latch.

    ``connector_id``: 1 (Main) or 2 (Vice)
    ``purpose``: "lock" or "unlock"
    """
    if purpose not in ("lock", "unlock"):
        raise ValueError("purpose must be 'lock' or 'unlock'")
    if connector_id not in (1, 2):
        raise ValueError("connector_id must be 1 or 2")
    return Message(
        message_type_id="5",
        unique_id=state.next_unique_id(),
        action="ElectronicLock",
        payload={
            "userId": state.user_id,
            "chargeBoxSN": state.charge_box_sn,
            "connectorId": connector_id,
            "purpose": purpose,
        },
    )


def make_pnc_set(state, connector_id, purpose):
    """Open/close Plug-and-Charge authorization on a connector.

    ``purpose``: "open" (no auth needed) or "close" (auth required)
    """
    if purpose not in ("open", "close"):
        raise ValueError("purpose must be 'open' or 'close'")
    if connector_id not in (1, 2):
        raise ValueError("connector_id must be 1 or 2")
    return Message(
        message_type_id="5",
        unique_id=state.next_unique_id(),
        action="PnCSet",
        payload={
            "userId": state.user_id,
            "chargeBoxSN": state.charge_box_sn,
            "connectorId": connector_id,
            "purpose": purpose,
        },
    )


def make_get_record(state, start_date, end_date, record_type="charge"):
    """Fetch charging history between two dates.

    ``start_date`` / ``end_date``: "YYYY-MM-DD" strings
    """
    return Message(
        message_type_id="5",
        unique_id=state.next_unique_id(),
        action="GetRecord",
        payload={
            "userId": state.user_id,
            "chargeBoxSN": state.charge_box_sn,
            "recordType": record_type,
            "startTime": start_date,
            "endTime": end_date,
        },
    )
