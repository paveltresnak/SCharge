"""
ScargeCoordinator — srdce integrace.

Běží jako background task v HA eventloop:
- WebSocket SERVER na konfigurovatelném portu (wallbox se k nám připojuje jako client)
- UDP broadcast loop na port 3050 (discovery trigger)
- Auto-ACK příchozích mt=5 zpráv
- Dispatch stavu entitám přes async_dispatcher_send

Podporované TX příkazy (volané z entity):
- send_loadbalance(value_watts)
- send_electronic_lock(connector_id, purpose)
- send_pnc_set(connector_id, purpose)
"""
import asyncio
import json
import logging
import socket
import time

import websockets

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DEFAULT_BROADCAST_ADDR,
    DEFAULT_BROADCAST_INTERVAL,
    DEFAULT_BROADCAST_PORT,
    DEFAULT_WS_PORT,
    DOMAIN,
    SIGNAL_UPDATE,
    WS_SUBPROTOCOL,
)
from .protocol import Message, ProtocolState, chunk_message
from .actions import (
    DeviceData,
    SynchroData,
    SynchroStatus,
    NWireToDics,
    decode_payload,
    make_authorize,
    make_electronic_lock,
    make_load_balance,
    make_pnc_set,
)

_LOGGER = logging.getLogger(__name__)


class SchargeCoordinator:
    """Drží stav jednoho wallboxu, provozuje WS server + UDP broadcast."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        serial: str,
        host: str | None = None,
        ws_port: int = DEFAULT_WS_PORT,
        broadcast_addr: str = DEFAULT_BROADCAST_ADDR,
        broadcast_port: int = DEFAULT_BROADCAST_PORT,
        broadcast_interval: float = DEFAULT_BROADCAST_INTERVAL,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.serial = serial
        self.host = host           # IP wallboxu — informativně + unicast UDP fallback
        self.ws_port = ws_port
        self.broadcast_addr = broadcast_addr
        self.broadcast_port = broadcast_port
        self.broadcast_interval = broadcast_interval

        self.signal_update = SIGNAL_UPDATE.format(entry_id=entry_id)

        # Aktuální stav (naplněný z wallbox telemetrie)
        self.device_data: DeviceData | None = None
        self.synchro_status: SynchroStatus | None = None
        self.synchro_data: SynchroData | None = None
        self.nwire: NWireToDics | None = None
        self.connected: bool = False        # WS session up?
        self.last_heartbeat: float | None = None
        self.last_update: float | None = None

        # Výsledky LoadBalance ACK — aby entity věděla že command prošel
        self.last_loadbalance_set: int | None = None

        # Běžící WS client connection (k odeslání commandů)
        self._ws = None

        # Background tasks
        self._ws_server = None
        self._ws_server_task: asyncio.Task | None = None
        self._broadcast_task: asyncio.Task | None = None

        # Bridge enabled — když False, HA drží krok stranou a nechá WS session
        # pro mobilní aplikaci (UDP broadcast zastaven + aktivní WS zavřen).
        # WS server zůstává poslouchat, aby šlo obnovit bez restart integrace.
        self._bridge_enabled: bool = True

        # ProtocolState pro správu uniqueId a state tracking
        self._proto = ProtocolState(charge_box_sn=serial, user_id="1")

    # ─── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Spustit WS server + UDP broadcast loop."""
        _LOGGER.info("Starting SchargeCoordinator on port %d (SN=%s)",
                     self.ws_port, self.serial)

        # WS server
        self._ws_server = await websockets.serve(
            self._handle_connection,
            "0.0.0.0",
            self.ws_port,
            subprotocols=[WS_SUBPROTOCOL],
            ping_interval=None,   # wallbox nepodporuje WS ping
            ping_timeout=None,
        )
        _LOGGER.info("WS server listening on 0.0.0.0:%d", self.ws_port)

        # UDP broadcast loop (jen pokud je bridge zapnutý)
        if self._bridge_enabled:
            self._start_broadcast_task()

    # ─── Bridge enable/disable (pro sdílení wallboxu s mobilní app) ─────────

    @property
    def bridge_enabled(self) -> bool:
        return self._bridge_enabled

    def _start_broadcast_task(self) -> None:
        """Internal: spustit broadcast task, pokud neběží."""
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = self.hass.async_create_background_task(
                self._broadcast_loop(),
                name=f"{DOMAIN}_broadcast_{self.entry_id}",
            )

    async def _stop_broadcast_task(self) -> None:
        """Internal: zastavit broadcast task, pokud běží."""
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        self._broadcast_task = None

    async def pause_bridge(self) -> None:
        """Uvolnit wallbox pro mobilní aplikaci.

        Zastaví UDP broadcast a zavře aktivní WS — wallbox se odpojí a další
        UDP broadcast z mobilní app bude akceptován. WS server HA zůstává
        poslouchat, takže po resume_bridge() stačí obnovit broadcast a wallbox
        se sám vrátí zpět do HA.
        """
        if not self._bridge_enabled:
            return
        _LOGGER.info("Bridge paused — releasing wallbox for mobile app")
        self._bridge_enabled = False
        await self._stop_broadcast_task()
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2)
            except (asyncio.TimeoutError, Exception) as e:
                _LOGGER.debug("WS close timed out during bridge pause: %s", e)
            self._ws = None
        self.connected = False
        self._notify_entities()

    async def resume_bridge(self) -> None:
        """Obnovit HA ↔ wallbox spojení po pause_bridge()."""
        if self._bridge_enabled:
            return
        _LOGGER.info("Bridge resumed — restarting UDP broadcast discovery")
        self._bridge_enabled = True
        self._start_broadcast_task()
        # WS connect nás najde sám přes další broadcast cyklus (3 s)
        self._notify_entities()

    async def async_stop(self) -> None:
        """Zastavit vše. Must not block indefinitely — wallbox often doesn't
        close WS gracefully, so we use timeouts."""
        _LOGGER.info("Stopping SchargeCoordinator")
        # 1. Cancel UDP broadcast first
        await self._stop_broadcast_task()
        # 2. Close active WS connection (unblocks wait_closed below)
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2)
            except (asyncio.TimeoutError, Exception) as e:
                _LOGGER.debug("WS close timed out/failed: %s", e)
            self._ws = None
        # 3. Close WS server with timeout
        if self._ws_server:
            self._ws_server.close()
            try:
                await asyncio.wait_for(self._ws_server.wait_closed(), timeout=3)
            except asyncio.TimeoutError:
                _LOGGER.warning("WS server close timeout — forcing down")
        self.connected = False
        self._notify_entities()

    # ─── UDP broadcast ─────────────────────────────────────────────────────────

    async def _broadcast_loop(self) -> None:
        """Periodický UDP broadcast pro wallbox discovery."""
        # Bind na source port 3050 — KRITICKÉ, jinak wallbox ignoruje
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            udp.bind(("0.0.0.0", self.broadcast_port))
        except OSError as e:
            _LOGGER.error("Cannot bind UDP port %d: %s — discovery nebude fungovat",
                          self.broadcast_port, e)
            udp.close()
            return

        _LOGGER.info("UDP broadcast bound to port %d, interval %.1fs",
                     self.broadcast_port, self.broadcast_interval)

        try:
            while True:
                # Zjistit vlastní IP (adresa v LAN, kam má wallbox připojit)
                my_ip = self._get_lan_ip()
                payload = {
                    "messageTypeId": "5",
                    "uniqueId": str(int(time.time() * 1000)),
                    "action": "UDPHandShake",
                    "payload": {
                        "label": "APP",
                        "chargeBoxSN": self.serial,
                        "iPAddress": f"{my_ip}:{self.ws_port}",
                    },
                }
                msg = json.dumps(payload, separators=(",", ":")).encode()
                # Broadcast
                try:
                    udp.sendto(msg, (self.broadcast_addr, self.broadcast_port))
                except Exception as e:
                    _LOGGER.warning("UDP broadcast send failed: %s", e)
                # Unicast na IP wallboxu (fallback pro sítě, kde broadcast nefunguje)
                if self.host:
                    try:
                        udp.sendto(msg, (self.host, self.broadcast_port))
                    except Exception as e:
                        _LOGGER.debug("UDP unicast send failed: %s", e)
                await asyncio.sleep(self.broadcast_interval)
        except asyncio.CancelledError:
            _LOGGER.info("UDP broadcast loop cancelled")
            raise
        finally:
            udp.close()

    @staticmethod
    def _get_lan_ip() -> str:
        """Získat IP adresu pro LAN (kam má wallbox připojit zpět)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    # ─── WebSocket handler ─────────────────────────────────────────────────────

    async def _handle_connection(self, websocket) -> None:
        """Nová WS session z wallboxu."""
        try:
            path = websocket.request.path
        except Exception:
            path = "?"
        peer = getattr(websocket, "remote_address", "?")
        _LOGGER.info("WS connect from %s path=%s subprotocol=%s",
                     peer, path, websocket.subprotocol)

        # Pokud už máme aktivní session, starou zahodíme.
        # DEBUG úroveň — reconnect je normální chování wallboxu (každých ~10-15 min).
        if self._ws is not None and self._ws is not websocket:
            _LOGGER.debug("Overwriting existing WS session (normal reconnect)")

        self._ws = websocket
        self.connected = True
        self._notify_entities()

        try:
            async for raw in websocket:
                if not isinstance(raw, str):
                    _LOGGER.debug("Binary frame ignored (%d B)", len(raw))
                    continue
                await self._handle_message(raw)
        except websockets.exceptions.ConnectionClosed as e:
            _LOGGER.info("WS closed: %s", e)
        except Exception as e:
            _LOGGER.exception("WS handler error: %s", e)
        finally:
            if self._ws is websocket:
                self._ws = None
                self.connected = False
                self._notify_entities()

    async def _handle_message(self, raw: str) -> None:
        """Zpracovat jednu přijatou JSON zprávu."""
        try:
            msg = Message.from_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            _LOGGER.warning("Malformed message: %s", e)
            return

        self.last_update = time.time()

        if msg.is_ack:
            _LOGGER.debug("ACK received for uniqueId=%s payload=%s",
                          msg.unique_id, msg.payload)
            return

        if not msg.is_request:
            return

        # Auto-ACK každý mt=5 request
        ack = Message(
            message_type_id="6",
            unique_id=msg.unique_id,
            payload={"chargeBoxSN": self.serial},
        )
        try:
            await self._send_message(ack)
        except Exception as e:
            _LOGGER.warning("Failed to send ACK: %s", e)

        # Dispatch podle action
        action = msg.action
        payload = decode_payload(msg)

        if action == "Heartbeat":
            self.last_heartbeat = time.time()
        elif action == "DeviceData" and payload is not None:
            self.device_data = payload
        elif action == "SynchroStatus" and payload is not None:
            self.synchro_status = payload
        elif action == "SynchroData" and payload is not None:
            self.synchro_data = payload
        elif action == "NWireToDics" and payload is not None:
            self.nwire = payload
        else:
            _LOGGER.debug("Unhandled action: %s", action)

        self._notify_entities()

    # ─── TX helpers (volané z entity) ──────────────────────────────────────────

    async def _send_message(self, msg: Message) -> bool:
        """Odeslat zprávu přes aktuální WS. Vrátí True při úspěchu."""
        if self._ws is None:
            _LOGGER.warning("No active WS session, can't send %s", msg)
            return False
        try:
            await self._ws.send(msg.to_json())
            return True
        except Exception as e:
            _LOGGER.error("send failed: %s", e)
            return False

    async def send_loadbalance(self, watts: int) -> bool:
        """Poslat LoadBalance příkaz."""
        msg = make_load_balance(self._proto, watts)
        _LOGGER.info("TX LoadBalance(%d W) uid=%s", watts, msg.unique_id)
        ok = await self._send_message(msg)
        if ok:
            self.last_loadbalance_set = watts
        return ok

    async def send_authorize(self, connector_id: int, purpose: str, current: int) -> bool:
        """Start/Stop charging session at given current (A).

        Calling Start during active charging re-authorizes the session with a new
        current limit — this is how we throttle per-connector amperage for
        PV-driven modulation (more granular than building-level LoadBalance).
        """
        msg = make_authorize(self._proto, connector_id, purpose, current)
        _LOGGER.info("TX Authorize(c=%d, %s, %d A) uid=%s",
                     connector_id, purpose, current, msg.unique_id)
        return await self._send_message(msg)

    async def send_electronic_lock(self, connector_id: int, purpose: str) -> bool:
        """Lock/unlock electronic latch na konektoru."""
        msg = make_electronic_lock(self._proto, connector_id, purpose)
        _LOGGER.info("TX ElectronicLock(c=%d, %s) uid=%s",
                     connector_id, purpose, msg.unique_id)
        return await self._send_message(msg)

    async def send_pnc_set(self, connector_id: int, purpose: str) -> bool:
        """Open/close Plug-and-Charge."""
        msg = make_pnc_set(self._proto, connector_id, purpose)
        _LOGGER.info("TX PnCSet(c=%d, %s) uid=%s",
                     connector_id, purpose, msg.unique_id)
        return await self._send_message(msg)

    # ─── Notifikace entit ─────────────────────────────────────────────────────

    def _notify_entities(self) -> None:
        """Oznámit všem entitám, že se stav změnil."""
        async_dispatcher_send(self.hass, self.signal_update)
