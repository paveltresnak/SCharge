"""
S-charge BLE core protocol — transport-agnostic.

Handles:
- Message envelope (JSON with messageTypeId, uniqueId, action, payload)
- BLE chunking (20 B per packet, '#' terminator)
- Reassembly from incoming NOTIFY stream
- Auto-ACK (mt=5 request -> mt=6 ACK with matching uniqueId)
- Connection state machine (disconnected, handshaking, connected)

Designed to work on both CPython and MicroPython without modification.
No BLE / network / asyncio dependencies — caller provides transport.

See protocol specification in docs/2026-04-19-wallbox-integrace-dokumentace.md
section 11.
"""

try:
    import ujson as json  # MicroPython
except ImportError:
    import json  # CPython

import time


# ─── Protocol constants ────────────────────────────────────────────────────────

TERMINATOR = b"#"          # byte 0x23, message delimiter on both TX and RX
CHUNK_SIZE = 20            # ATT MTU 23 - 3 B header = 20 B max per write/notify


# ─── Message envelope ──────────────────────────────────────────────────────────


class Message(object):
    """One JSON message on the wire (without '#' terminator).

    Wire format:
        {"messageTypeId": "5" | "6",
         "uniqueId": "<id>",
         "action": "<ActionName>",    # present only for mt=5 requests
         "payload": { ... }}
    """

    __slots__ = ("message_type_id", "unique_id", "action", "payload")

    def __init__(self, message_type_id, unique_id, action=None, payload=None):
        self.message_type_id = message_type_id  # "5" or "6"
        self.unique_id = unique_id
        self.action = action
        self.payload = payload if payload is not None else {}

    # ---- serialization ----

    def to_dict(self):
        d = {"messageTypeId": self.message_type_id, "uniqueId": self.unique_id}
        if self.action is not None:
            d["action"] = self.action
        d["payload"] = self.payload
        return d

    def to_json(self):
        """JSON-encode (no terminator, no chunking)."""
        return json.dumps(self.to_dict())

    def to_bytes(self):
        """Encode to bytes ready for BLE write (JSON + '#' terminator)."""
        return self.to_json().encode("utf-8") + TERMINATOR

    # ---- deserialization ----

    @classmethod
    def from_dict(cls, d):
        return cls(
            message_type_id=d.get("messageTypeId"),
            unique_id=d.get("uniqueId"),
            action=d.get("action"),
            payload=d.get("payload") or {},
        )

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_bytes(cls, data):
        """Parse bytes (without terminator) into Message."""
        return cls.from_json(data.decode("utf-8"))

    # ---- predicates ----

    @property
    def is_request(self):
        """True if this is a request (mt=5, needs an ACK in response)."""
        return self.message_type_id == "5"

    @property
    def is_ack(self):
        """True if this is an acknowledgment (mt=6)."""
        return self.message_type_id == "6"

    def __repr__(self):
        if self.action:
            return "<Message mt=%s action=%s id=%s>" % (
                self.message_type_id,
                self.action,
                self.unique_id,
            )
        return "<Message mt=%s ack id=%s>" % (self.message_type_id, self.unique_id)


# ─── Chunking / reassembly ─────────────────────────────────────────────────────


def chunk_message(msg_bytes, chunk_size=CHUNK_SIZE):
    """Split serialized bytes (with '#' terminator) into BLE-sized chunks.

    Returns list of bytes; each chunk is at most ``chunk_size`` bytes.
    The terminator '#' ends up in the last chunk naturally.
    """
    return [msg_bytes[i:i + chunk_size] for i in range(0, len(msg_bytes), chunk_size)]


class MessageReassembler(object):
    """Accumulates incoming BLE NOTIFY chunks, yields complete messages.

    Typical usage::

        r = MessageReassembler()
        for chunk in notify_stream():
            for raw_msg in r.feed(chunk):
                msg = Message.from_bytes(raw_msg)
                handle(msg)
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, chunk):
        """Feed one incoming chunk. Returns list of complete messages (bytes, no terminator).

        May return 0, 1, or many messages depending on chunk boundaries.
        Empty messages (two terminators in a row) are filtered out.
        """
        self._buffer.extend(chunk)
        messages = []
        while True:
            idx = self._buffer.find(TERMINATOR)
            if idx < 0:
                break
            piece = bytes(self._buffer[:idx])
            del self._buffer[:idx + 1]
            if piece:  # skip empty pieces
                messages.append(piece)
        return messages

    def reset(self):
        """Clear buffer (call on disconnect)."""
        self._buffer = bytearray()


# ─── Protocol state ────────────────────────────────────────────────────────────


class ProtocolState(object):
    """Stateful S-charge protocol session.

    Handles:
    - Connection state tracking (disconnected / handshaking / connected)
    - Incoming chunk assembly -> parsed Messages
    - Auto-generation of mt=6 ACKs for every received mt=5 request
    - Unique ID generation for outgoing requests

    Does NOT handle BLE I/O — the transport layer is responsible for calling
    ``ingest_chunk(chunk)`` on each NOTIFY and transmitting the returned ACKs
    plus any caller-initiated outgoing messages.
    """

    # Connection states
    DISCONNECTED = "disconnected"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"

    def __init__(self, charge_box_sn, user_id="1"):
        self.charge_box_sn = charge_box_sn
        self.user_id = user_id
        self.state = self.DISCONNECTED
        self._reassembler = MessageReassembler()

    # ---- state transitions ----

    def on_ble_disconnected(self):
        """Called when BLE connection drops. Resets state."""
        self.state = self.DISCONNECTED
        self._reassembler.reset()

    def on_handshake_sent(self):
        """Called by transport after HandShake has been written."""
        self.state = self.HANDSHAKING

    def _mark_connected(self):
        """Internal: called when HandShake ACK with result=true arrives."""
        self.state = self.CONNECTED

    # ---- unique ID generation ----

    def next_unique_id(self):
        """Generate unique ID for app-initiated request.

        Format: milliseconds since Unix epoch as string (matches S-charge app).
        On Pi Pico 2W: ``time.time()`` returns seconds since 2000-01-01 by default
        unless NTP is synced — caller should ensure ``time.time()`` returns a
        sensible epoch (e.g. via ``mpremote rtc`` or NTP).
        """
        return str(int(time.time() * 1000))

    # ---- ACK construction ----

    def make_ack(self, incoming, result=None):
        """Build mt=6 ACK for a received mt=5 request.

        Some actions (HandShake, ElectronicLock, PnCSet) have ``result: true``
        in their ACK; others (SynchroData, SynchroStatus) have only chargeBoxSN.
        ``result`` may be True/False/None.
        """
        payload = {"chargeBoxSN": self.charge_box_sn}
        if result is not None:
            payload["result"] = result
        return Message(
            message_type_id="6",
            unique_id=incoming.unique_id,
            action=None,
            payload=payload,
        )

    # ---- ingest pipeline ----

    def ingest_chunk(self, chunk):
        """Feed one BLE NOTIFY chunk. Returns ``(messages, ack_responses)``.

        - ``messages``: list of parsed ``Message`` objects (both mt=5 and mt=6)
        - ``ack_responses``: list of ``Message`` objects (mt=6 ACKs) that the
          transport should write back to the wallbox for every incoming mt=5.

        Also detects HandShake ACK (mt=6 response to our initial HandShake) and
        transitions state to CONNECTED.
        """
        raw_msgs = self._reassembler.feed(chunk)
        parsed = []
        acks = []
        for raw in raw_msgs:
            try:
                msg = Message.from_bytes(raw)
            except (ValueError, UnicodeDecodeError):
                continue  # corrupt message, skip
            parsed.append(msg)

            if msg.is_request:
                acks.append(self.make_ack(msg))
            elif msg.is_ack and self.state == self.HANDSHAKING:
                # HandShake response arrived
                if msg.payload.get("result") is True:
                    self._mark_connected()
        return parsed, acks
