"""
OmegaRealmBot - Load testing bot client for Omega Realm game server.

Implements the binary WebSocket protocol (little-endian) to simulate
player connections. Used for validating server performance under load.

Protocol reference: client/scripts/shared/networking/packet_types.gd
"""

import asyncio
import struct
import time
import random
import math
import logging
from dataclasses import dataclass, field
from enum import IntEnum

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except ModuleNotFoundError:
    websockets = None

    class ConnectionClosed(Exception):
        pass

logger = logging.getLogger("bot_client")


# --- Protocol Constants (mirrors packet_types.gd) ---

class MessageType(IntEnum):
    PLAYER_INPUT = 1
    STATE_UPDATE = 2
    GAME_EVENT = 3
    HEARTBEAT = 4
    ACTION_CONFIRM = 5
    CONNECT_AUTH = 6
    DISCONNECT = 7
    REQUEST_FULL_STATE = 8
    RESPAWN_REQUEST = 9
    SERVER_METRICS = 10


class EntityType(IntEnum):
    PLAYER = 1
    MONSTER = 2
    PROJECTILE = 3


class GameEventType(IntEnum):
    DAMAGE = 1
    KILL = 2
    RESPAWN = 3
    EFFECT_APPLY = 4
    EFFECT_REMOVE = 5
    PICKUP = 6
    LEVEL_UP = 7
    CHAT_MESSAGE = 8
    PLAYER_INFO = 9
    KILL_PVP = 10
    LEADERBOARD_UPDATE = 11


# Input flag bits
INPUT_FLAG_MOVE_UP = 1 << 0
INPUT_FLAG_MOVE_DOWN = 1 << 1
INPUT_FLAG_MOVE_LEFT = 1 << 2
INPUT_FLAG_MOVE_RIGHT = 1 << 3
INPUT_FLAG_SHOOT = 1 << 4
INPUT_FLAG_ABILITY = 1 << 5
INPUT_FLAG_SPRINT = 1 << 6
INPUT_FLAG_INTERACT = 1 << 7

# State update flags
STATE_FLAG_IS_DELTA = 1 << 0
STATE_FLAG_BASELINE = 1 << 1

# Delta mask bits
DELTA_MASK_POSITION = 1 << 0
DELTA_MASK_ANIMATION = 1 << 1
DELTA_MASK_FLAGS = 1 << 2
DELTA_MASK_REMOVED = 1 << 6
DELTA_MASK_FULL_STATE = 1 << 7

ENTITY_FLAG_ALIVE = 1 << 0
ENTITY_FLAG_VISIBLE = 1 << 5

# Quantization scales
POSITION_SCALE = 10.0
VELOCITY_SCALE = 10.0
ANGLE_SCALE = 100.0

# Header size
HEADER_SIZE = 3  # [u8 type][u16 payload_length]


# --- Packet Builder (little-endian) ---

def build_header(msg_type: int, payload: bytes) -> bytes:
    """Build packet: [u8 type][u16 payload_length][payload]"""
    return struct.pack("<BH", msg_type, len(payload)) + payload


def build_connect_auth(
    token: str,
    character_id: str,
    character_name: str,
    region: int = 0,
    player_color: tuple[int, int, int] | None = None,
) -> bytes:
    """Build CONNECT_AUTH packet.
    Format: [string token][string char_id][string char_name][u8 region][optional rgb]
    Strings are: [u16 length][utf8 bytes]
    """
    payload = bytearray()
    for s in (token, character_id, character_name):
        encoded = s.encode("utf-8")
        payload += struct.pack("<H", len(encoded))
        payload += encoded
    payload += struct.pack("<B", region)
    if player_color is not None:
        payload += bytes(max(0, min(255, int(c))) for c in player_color[:3])
    return build_header(MessageType.CONNECT_AUTH, bytes(payload))


def build_player_input(
    pos_x: float, pos_y: float,
    vel_x: float, vel_y: float,
    input_flags: int,
    aim_angle: float,
    sequence: int,
    client_render_tick: int = 0,
    client_rtt_ms: int = 0,
) -> bytes:
    """Build PLAYER_INPUT packet (16 bytes payload).
    Format: [s16 pos_x][s16 pos_y][s16 vel_x][s16 vel_y][u8 flags][s16 aim][u8 seq][u16 render_tick][u16 rtt_ms]
    """
    qpx = max(-32768, min(32767, int(pos_x * POSITION_SCALE)))
    qpy = max(-32768, min(32767, int(pos_y * POSITION_SCALE)))
    qvx = max(-32768, min(32767, int(vel_x * VELOCITY_SCALE)))
    qvy = max(-32768, min(32767, int(vel_y * VELOCITY_SCALE)))
    qaim = max(-32768, min(32767, int(aim_angle * ANGLE_SCALE)))
    payload = struct.pack(
        "<hhhhBhBHH",
        qpx, qpy, qvx, qvy,
        input_flags & 0xFF,
        qaim,
        sequence & 0xFF,
        client_render_tick & 0xFFFF,
        max(0, min(65535, int(client_rtt_ms))),
    )
    return build_header(MessageType.PLAYER_INPUT, payload)


def build_heartbeat(timestamp_ms: int) -> bytes:
    """Build HEARTBEAT packet (4 bytes payload). [u32 timestamp_ms]"""
    payload = struct.pack("<I", timestamp_ms & 0xFFFFFFFF)
    return build_header(MessageType.HEARTBEAT, payload)


def build_disconnect(reason: int = 0) -> bytes:
    """Build DISCONNECT packet. [u8 reason][u32 timestamp_ms]"""
    payload = struct.pack("<BI", reason, int(time.time() * 1000) & 0xFFFFFFFF)
    return build_header(MessageType.DISCONNECT, payload)


def build_respawn_request() -> bytes:
    """Build RESPAWN_REQUEST packet. [u32 timestamp_ms]"""
    payload = struct.pack("<I", int(time.time() * 1000) & 0xFFFFFFFF)
    return build_header(MessageType.RESPAWN_REQUEST, payload)


# --- Packet Parser (little-endian) ---

def parse_header(data: bytes) -> tuple[int, int, bytes]:
    """Parse packet header. Returns (msg_type, payload_length, payload_bytes)."""
    if len(data) < HEADER_SIZE:
        return -1, 0, b""
    msg_type, payload_len = struct.unpack_from("<BH", data, 0)
    payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
    return msg_type, payload_len, payload


def parse_heartbeat(payload: bytes) -> int:
    """Parse HEARTBEAT payload. Returns timestamp_ms."""
    if len(payload) < 4:
        return 0
    return struct.unpack_from("<I", payload, 0)[0]


def parse_state_update_header(payload: bytes) -> dict:
    """Parse STATE_UPDATE header (not full entity data - just enough for metrics).
    Returns dict with server_tick, state_flags, entity_count."""
    if len(payload) < 6:
        return {}
    server_tick, state_flags = struct.unpack_from("<IB", payload, 0)
    is_delta = bool(state_flags & STATE_FLAG_IS_DELTA)
    # Delta packets have a 4-byte baseline_tick before entity_count
    if is_delta:
        if len(payload) < 10:
            return {"server_tick": server_tick, "state_flags": state_flags, "is_delta": True, "entity_count": 0}
        entity_count = struct.unpack_from("<B", payload, 9)[0]
    else:
        entity_count = struct.unpack_from("<B", payload, 5)[0]
    return {
        "server_tick": server_tick,
        "state_flags": state_flags,
        "entity_count": entity_count,
        "is_delta": is_delta,
    }


@dataclass
class EntitySnapshot:
    entity_id: int
    entity_type: int
    x: float = 0.0
    y: float = 0.0
    animation_state: int = 0
    flags: int = ENTITY_FLAG_ALIVE | ENTITY_FLAG_VISIBLE

    @property
    def alive(self) -> bool:
        return bool(self.flags & ENTITY_FLAG_ALIVE)

    def distance_sq_to(self, other: "EntitySnapshot") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy


def _read_u8(payload: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<B", payload, offset)[0], offset + 1


def _read_u16(payload: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<H", payload, offset)[0], offset + 2


def _read_s16(payload: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<h", payload, offset)[0], offset + 2


def _read_string(payload: bytes, offset: int) -> tuple[str, int]:
    length, offset = _read_u16(payload, offset)
    raw = payload[offset:offset + length]
    return raw.decode("utf-8", errors="replace"), offset + length


def parse_state_update(payload: bytes, last_states: dict[int, EntitySnapshot] | None = None) -> dict:
    """Parse full/delta STATE_UPDATE payload and update an entity snapshot map."""
    if last_states is None:
        last_states = {}
    if len(payload) < 6:
        return {}

    offset = 0
    server_tick = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    state_flags, offset = _read_u8(payload, offset)
    is_delta = bool(state_flags & STATE_FLAG_IS_DELTA)
    baseline_tick = 0
    if is_delta:
        if len(payload) < offset + 5:
            return {"server_tick": server_tick, "state_flags": state_flags, "is_delta": True, "entities": []}
        baseline_tick = struct.unpack_from("<I", payload, offset)[0]
        offset += 4

    entity_count, offset = _read_u8(payload, offset)
    parsed: list[EntitySnapshot] = []
    removed: list[int] = []

    for _ in range(entity_count):
        if offset + 3 > len(payload):
            break

        entity_id, offset = _read_u16(payload, offset)

        if not is_delta:
            if offset + 7 > len(payload):
                break
            entity_type, offset = _read_u8(payload, offset)
            qx, offset = _read_s16(payload, offset)
            qy, offset = _read_s16(payload, offset)
            animation_state, offset = _read_u8(payload, offset)
            flags, offset = _read_u8(payload, offset)
            snapshot = EntitySnapshot(entity_id, entity_type, qx / POSITION_SCALE, qy / POSITION_SCALE, animation_state, flags)
            last_states[entity_id] = snapshot
            parsed.append(snapshot)
            continue

        delta_mask, offset = _read_u8(payload, offset)
        previous = last_states.get(entity_id, EntitySnapshot(entity_id, EntityType.PLAYER))

        if delta_mask & DELTA_MASK_REMOVED:
            last_states.pop(entity_id, None)
            removed.append(entity_id)
            continue

        if delta_mask & DELTA_MASK_FULL_STATE:
            if offset + 7 > len(payload):
                break
            entity_type, offset = _read_u8(payload, offset)
            qx, offset = _read_s16(payload, offset)
            qy, offset = _read_s16(payload, offset)
            animation_state, offset = _read_u8(payload, offset)
            flags, offset = _read_u8(payload, offset)
            snapshot = EntitySnapshot(entity_id, entity_type, qx / POSITION_SCALE, qy / POSITION_SCALE, animation_state, flags)
        else:
            entity_type = previous.entity_type
            x = previous.x
            y = previous.y
            animation_state = previous.animation_state
            flags = previous.flags
            if delta_mask & DELTA_MASK_POSITION:
                qx, offset = _read_s16(payload, offset)
                qy, offset = _read_s16(payload, offset)
                x = qx / POSITION_SCALE
                y = qy / POSITION_SCALE
            if delta_mask & DELTA_MASK_ANIMATION:
                animation_state, offset = _read_u8(payload, offset)
            if delta_mask & DELTA_MASK_FLAGS:
                flags, offset = _read_u8(payload, offset)
            snapshot = EntitySnapshot(entity_id, entity_type, x, y, animation_state, flags)

        last_states[entity_id] = snapshot
        parsed.append(snapshot)

    return {
        "server_tick": server_tick,
        "state_flags": state_flags,
        "baseline_tick": baseline_tick,
        "entity_count": entity_count,
        "is_delta": is_delta,
        "entities": parsed,
        "removed": removed,
    }


def parse_game_event(payload: bytes) -> dict:
    """Parse the GAME_EVENT fields bots need for identity and respawn state."""
    if len(payload) < 5:
        return {}

    offset = 0
    event_type, offset = _read_u8(payload, offset)
    source_id, offset = _read_u16(payload, offset)
    target_id, offset = _read_u16(payload, offset)
    event_data: dict = {}

    if event_type == GameEventType.PLAYER_INFO:
        character_name, offset = _read_string(payload, offset)
        if offset + 4 <= len(payload):
            qx, offset = _read_s16(payload, offset)
            qy, offset = _read_s16(payload, offset)
            event_data["position"] = (qx / POSITION_SCALE, qy / POSITION_SCALE)
        if offset + 3 <= len(payload):
            event_data["player_color"] = tuple(payload[offset:offset + 3])
        event_data["character_name"] = character_name
    elif event_type == GameEventType.RESPAWN and offset + 4 <= len(payload):
        qx, offset = _read_s16(payload, offset)
        qy, offset = _read_s16(payload, offset)
        event_data["position"] = (qx / POSITION_SCALE, qy / POSITION_SCALE)

    return {
        "event_type": event_type,
        "source_id": source_id,
        "target_id": target_id,
        "event_data": event_data,
    }


def parse_server_metrics(payload: bytes) -> dict:
    """Parse SERVER_METRICS payload.
    Format: [u32 tick][u16 avg_tick*100][u16 max_tick*100][u16 players][u16 entities]
            [u32 bytes_sent][u32 bytes_recv][u32 avg_bw_per_client]
    Total: 24 bytes
    """
    if len(payload) < 24:
        return {}
    tick, avg_tick_100, max_tick_100, players, entities, bytes_sent, bytes_recv, avg_bw = \
        struct.unpack_from("<IHHHHIII", payload, 0)
    return {
        "tick_count": tick,
        "avg_tick_time_ms": avg_tick_100 / 100.0,
        "max_tick_time_ms": max_tick_100 / 100.0,
        "player_count": players,
        "entity_count": entities,
        "total_bytes_sent": bytes_sent,
        "total_bytes_received": bytes_recv,
        "avg_bandwidth_per_client": avg_bw,
    }


# --- Metrics ---

@dataclass
class BotMetrics:
    """Per-bot metrics collected during load test."""
    latencies_ms: list[float] = field(default_factory=list)
    packets_sent: int = 0
    packets_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    state_updates_received: int = 0
    heartbeats_received: int = 0
    game_events_received: int = 0
    server_ticks_seen: list[int] = field(default_factory=list)
    connection_time_ms: float = 0.0
    disconnected: bool = False
    error_count: int = 0
    last_error: str = ""
    # Server-reported metrics (from SERVER_METRICS packets)
    server_metrics_snapshots: list[dict] = field(default_factory=list)

    @property
    def packet_loss_estimate(self) -> float:
        """Estimate packet loss from gaps in server tick sequence."""
        if len(self.server_ticks_seen) < 2:
            return 0.0
        ticks = sorted(self.server_ticks_seen)
        expected = ticks[-1] - ticks[0]
        if expected <= 0:
            return 0.0
        actual = len(ticks) - 1
        return max(0.0, 1.0 - (actual / expected))

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies_ms) / len(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def min_latency(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        idx = int(len(s) * 0.95)
        return s[min(idx, len(s) - 1)]

    @property
    def p99_latency(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        idx = int(len(s) * 0.99)
        return s[min(idx, len(s) - 1)]

    def summary(self) -> dict:
        result = {
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "state_updates": self.state_updates_received,
            "heartbeats": self.heartbeats_received,
            "latency_avg_ms": round(self.avg_latency, 1),
            "latency_min_ms": round(self.min_latency, 1),
            "latency_max_ms": round(self.max_latency, 1),
            "latency_p95_ms": round(self.p95_latency, 1),
            "latency_p99_ms": round(self.p99_latency, 1),
            "packet_loss_pct": round(self.packet_loss_estimate * 100, 2),
            "connection_time_ms": round(self.connection_time_ms, 1),
            "error_count": self.error_count,
        }
        if self.server_metrics_snapshots:
            result["latest_server_metrics"] = self.server_metrics_snapshots[-1]
        return result


# --- Bot Client ---

# Bot behavior modes for different benchmark scenarios
BEHAVIOR_DEFAULT = "default"       # Random movement + 20% shooting (original behavior)
BEHAVIOR_IDLE = "idle"             # Heartbeats only, no movement or shooting
BEHAVIOR_MOVEMENT = "movement"     # Movement without shooting
BEHAVIOR_COMBAT = "combat"         # Constant shooting + movement
BEHAVIOR_CLUSTERED = "clustered"   # All bots converge to center (worst case AoI)
BEHAVIOR_STRATEGY = "strategy"     # Gameplay bot: targets monsters, then players

VALID_BEHAVIORS = [
    BEHAVIOR_DEFAULT, BEHAVIOR_IDLE, BEHAVIOR_MOVEMENT, BEHAVIOR_COMBAT,
    BEHAVIOR_CLUSTERED, BEHAVIOR_STRATEGY,
]

BOT_ADJECTIVES = [
    "Bright", "Swift", "Solar", "Neon", "Vivid", "Prime", "Sharp", "Nova",
    "Quick", "Lunar", "Azure", "Crimson",
]
BOT_NOUNS = [
    "Rift", "Pulse", "Comet", "Warden", "Spark", "Vex", "Echo", "Runner",
    "Aegis", "Bolt", "Drift", "Flare",
]


def generate_bot_identity(bot_id: int) -> tuple[str, str]:
    adjective = BOT_ADJECTIVES[(bot_id - 1) % len(BOT_ADJECTIVES)]
    noun = BOT_NOUNS[((bot_id - 1) // len(BOT_ADJECTIVES)) % len(BOT_NOUNS)]
    name = f"{adjective}{noun}{bot_id % 100:02d}"
    return f"bot-{bot_id:04d}", name[:24]


def generate_bright_color(bot_id: int) -> tuple[int, int, int]:
    hue = ((bot_id * 0.61803398875) % 1.0)
    sector = int(hue * 6)
    frac = hue * 6 - sector
    value = 255
    min_channel = 80
    mid = int(min_channel + frac * (value - min_channel))
    inv_mid = int(value - frac * (value - min_channel))
    match sector % 6:
        case 0:
            return value, mid, min_channel
        case 1:
            return inv_mid, value, min_channel
        case 2:
            return min_channel, value, mid
        case 3:
            return min_channel, inv_mid, value
        case 4:
            return mid, min_channel, value
        case _:
            return value, min_channel, inv_mid


class OmegaRealmBot:
    """A single load-testing bot that connects to the game server via WebSocket."""

    def __init__(self, bot_id: int, server_url: str, token: str = "", behavior: str = BEHAVIOR_DEFAULT):
        self.bot_id = bot_id
        self.server_url = server_url
        self.character_id, self.character_name = generate_bot_identity(bot_id)
        self.player_color = generate_bright_color(bot_id)
        self.token = token
        self.behavior = behavior
        self.ws = None
        self.metrics = BotMetrics()
        self._running = False
        self._sequence = 0
        if behavior == BEHAVIOR_CLUSTERED:
            # All clustered bots start near origin
            self._pos_x = random.uniform(-10.0, 10.0)
            self._pos_y = random.uniform(-10.0, 10.0)
        else:
            self._pos_x = random.uniform(-200.0, 200.0)
            self._pos_y = random.uniform(-200.0, 200.0)
        self._vel_x = 0.0
        self._vel_y = 0.0
        self._aim_angle = 0.0
        self._last_heartbeat_sent = 0.0
        self._last_input_sent = 0.0
        self._last_rtt_ms = 0
        self._entity_id: int | None = None
        self._entities: dict[int, EntitySnapshot] = {}
        self._dead_since: float | None = None
        self._last_respawn_sent = 0.0

    async def connect(self, timeout: float = 10.0) -> bool:
        """Connect to the game server and send auth handshake."""
        try:
            if websockets is None:
                raise RuntimeError("Missing dependency: install load_testing/requirements.txt")
            t0 = time.monotonic()
            self.ws = await asyncio.wait_for(
                websockets.connect(self.server_url, max_size=2**20, ping_interval=None),
                timeout=timeout,
            )
            self.metrics.connection_time_ms = (time.monotonic() - t0) * 1000

            # Send CONNECT_AUTH
            auth_packet = build_connect_auth(
                self.token, self.character_id, self.character_name, 0, self.player_color
            )
            await self.ws.send(auth_packet)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(auth_packet)

            logger.debug(f"Bot {self.bot_id}: Connected and auth sent")
            return True
        except Exception as e:
            self.metrics.error_count += 1
            self.metrics.disconnected = True
            self.metrics.last_error = str(e)
            logger.warning(f"Bot {self.bot_id}: Connection failed: {e}")
            return False

    async def disconnect(self):
        """Send disconnect packet and close connection."""
        if self.ws is None:
            return
        try:
            pkt = build_disconnect(0)  # USER_QUIT
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
            await self.ws.close()
        except Exception:
            pass
        finally:
            self.ws = None

    async def run(self, duration_seconds: float):
        """Run the bot for the specified duration, sending inputs and processing responses."""
        self._running = True
        start = time.monotonic()

        # Create concurrent tasks for sending and receiving
        send_task = asyncio.create_task(self._send_loop(start, duration_seconds))
        recv_task = asyncio.create_task(self._recv_loop(start, duration_seconds))

        try:
            await asyncio.gather(send_task, recv_task)
        except Exception as e:
            self.metrics.error_count += 1
            self.metrics.last_error = str(e)
            logger.debug(f"Bot {self.bot_id}: Run ended with: {e}")
        finally:
            self._running = False

    async def _send_loop(self, start: float, duration: float):
        """Send player inputs at ~10Hz and heartbeats at ~1Hz."""
        input_interval = 1.0 / 10.0  # 10Hz input rate
        heartbeat_interval = 1.0

        while self._within_duration(start, duration) and self._running:
            now = time.monotonic()

            # Send heartbeat every ~1 second
            if now - self._last_heartbeat_sent >= heartbeat_interval:
                await self._send_heartbeat()
                self._last_heartbeat_sent = now

            # Send player input at ~10Hz (skip for idle behavior)
            if self.behavior != BEHAVIOR_IDLE and now - self._last_input_sent >= input_interval:
                if self.behavior == BEHAVIOR_STRATEGY:
                    await self._send_strategy_input()
                else:
                    await self._send_random_input()
                self._last_input_sent = now

            await asyncio.sleep(0.02)  # 50Hz poll rate for timing accuracy

    async def _recv_loop(self, start: float, duration: float):
        """Receive and parse server messages."""
        try:
            while self._within_duration(start, duration) and self._running:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                    if isinstance(msg, bytes):
                        self.metrics.packets_received += 1
                        self.metrics.bytes_received += len(msg)
                        self._handle_message(msg)
                except asyncio.TimeoutError:
                    continue
        except ConnectionClosed:
            self.metrics.disconnected = True
            logger.debug(f"Bot {self.bot_id}: Connection closed by server")

    def _within_duration(self, start: float, duration: float) -> bool:
        return duration <= 0 or time.monotonic() - start < duration

    async def _send_heartbeat(self):
        """Send heartbeat with current timestamp."""
        if self.ws is None:
            return
        try:
            ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
            pkt = build_heartbeat(ts)
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
        except ConnectionClosed:
            self._running = False

    async def _send_random_input(self):
        """Send PLAYER_INPUT based on configured behavior."""
        if self.ws is None:
            return

        shoot_flag = 0

        if self.behavior == BEHAVIOR_CLUSTERED:
            # Move toward origin (0,0)
            dx = -self._pos_x
            dy = -self._pos_y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 5.0:
                speed = 200.0
                self._vel_x = (dx / dist) * speed
                self._vel_y = (dy / dist) * speed
                self._input_flags = 0
                if self._vel_y < -50: self._input_flags |= INPUT_FLAG_MOVE_UP
                if self._vel_y > 50: self._input_flags |= INPUT_FLAG_MOVE_DOWN
                if self._vel_x < -50: self._input_flags |= INPUT_FLAG_MOVE_LEFT
                if self._vel_x > 50: self._input_flags |= INPUT_FLAG_MOVE_RIGHT
            else:
                self._vel_x = 0
                self._vel_y = 0
                self._input_flags = 0
            shoot_flag = INPUT_FLAG_SHOOT if random.random() < 0.3 else 0

        elif self.behavior == BEHAVIOR_COMBAT:
            # Random movement + constant shooting
            if random.random() < 0.15:
                directions = [
                    (INPUT_FLAG_MOVE_UP, 0, -200),
                    (INPUT_FLAG_MOVE_DOWN, 0, 200),
                    (INPUT_FLAG_MOVE_LEFT, -200, 0),
                    (INPUT_FLAG_MOVE_RIGHT, 200, 0),
                ]
                flags, vx, vy = random.choice(directions)
                self._vel_x = vx
                self._vel_y = vy
                self._input_flags = flags
            else:
                self._input_flags = getattr(self, "_input_flags", 0)
            shoot_flag = INPUT_FLAG_SHOOT  # Always shooting

        elif self.behavior == BEHAVIOR_MOVEMENT:
            # Movement only, no shooting
            if random.random() < 0.1:
                directions = [
                    (INPUT_FLAG_MOVE_UP, 0, -200),
                    (INPUT_FLAG_MOVE_DOWN, 0, 200),
                    (INPUT_FLAG_MOVE_LEFT, -200, 0),
                    (INPUT_FLAG_MOVE_RIGHT, 200, 0),
                    (INPUT_FLAG_MOVE_UP | INPUT_FLAG_MOVE_RIGHT, 141, -141),
                    (INPUT_FLAG_MOVE_DOWN | INPUT_FLAG_MOVE_LEFT, -141, 141),
                    (0, 0, 0),
                ]
                flags, vx, vy = random.choice(directions)
                self._vel_x = vx
                self._vel_y = vy
                self._input_flags = flags
            else:
                self._input_flags = getattr(self, "_input_flags", 0)
            shoot_flag = 0  # Never shoot

        else:  # BEHAVIOR_DEFAULT
            if random.random() < 0.1:
                directions = [
                    (INPUT_FLAG_MOVE_UP, 0, -200),
                    (INPUT_FLAG_MOVE_DOWN, 0, 200),
                    (INPUT_FLAG_MOVE_LEFT, -200, 0),
                    (INPUT_FLAG_MOVE_RIGHT, 200, 0),
                    (INPUT_FLAG_MOVE_UP | INPUT_FLAG_MOVE_RIGHT, 141, -141),
                    (INPUT_FLAG_MOVE_DOWN | INPUT_FLAG_MOVE_LEFT, -141, 141),
                    (0, 0, 0),
                ]
                flags, vx, vy = random.choice(directions)
                self._vel_x = vx
                self._vel_y = vy
                self._input_flags = flags
            else:
                self._input_flags = getattr(self, "_input_flags", 0)
            shoot_flag = INPUT_FLAG_SHOOT if random.random() < 0.2 else 0

        # Random aim angle
        self._aim_angle = random.uniform(-math.pi, math.pi)

        # Update simulated position (clamped to map bounds)
        dt = 0.1  # 10Hz
        self._pos_x = max(-1000, min(1000, self._pos_x + self._vel_x * dt))
        self._pos_y = max(-1000, min(1000, self._pos_y + self._vel_y * dt))

        self._sequence = (self._sequence + 1) & 0xFF

        try:
            pkt = build_player_input(
                self._pos_x, self._pos_y,
                self._vel_x, self._vel_y,
                self._input_flags | shoot_flag,
                self._aim_angle,
                self._sequence,
                0,  # No render interpolation in the headless load-test bot.
                self._last_rtt_ms,
            )
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
        except ConnectionClosed:
            self._running = False

    async def _send_strategy_input(self):
        """Send PLAYER_INPUT from a simple target-seeking gameplay strategy."""
        if self.ws is None:
            return

        now = time.monotonic()
        self_snapshot = self._get_self_snapshot()
        if self_snapshot is not None:
            self._pos_x = self_snapshot.x
            self._pos_y = self_snapshot.y
            if not self_snapshot.alive:
                if self._dead_since is None:
                    self._dead_since = now
                self._vel_x = 0.0
                self._vel_y = 0.0
                self._input_flags = 0
                if now - self._dead_since >= 3.2 and now - self._last_respawn_sent >= 1.0:
                    await self._send_respawn_request()
                    self._last_respawn_sent = now
                await self._send_input_packet(0)
                return
            self._dead_since = None

        target = self.select_target()
        shoot_flag = 0
        self._input_flags = 0

        if target is not None:
            dx = target.x - self._pos_x
            dy = target.y - self._pos_y
            dist = max(0.001, math.sqrt(dx * dx + dy * dy))
            self._aim_angle = math.atan2(dy, dx)

            desired_min = 260.0 if target.entity_type == EntityType.MONSTER else 220.0
            desired_max = 520.0
            move_x = 0.0
            move_y = 0.0

            if dist > desired_max:
                move_x = dx / dist
                move_y = dy / dist
            elif dist < desired_min:
                move_x = -dx / dist
                move_y = -dy / dist
            else:
                strafe = 1.0 if (self.bot_id + int(time.monotonic() * 2)) % 2 == 0 else -1.0
                move_x = (-dy / dist) * strafe
                move_y = (dx / dist) * strafe
                shoot_flag = INPUT_FLAG_SHOOT

            self._set_velocity_from_direction(move_x, move_y, sprint=False)
            if dist <= 650.0:
                shoot_flag = INPUT_FLAG_SHOOT
        else:
            if random.random() < 0.05:
                angle = random.uniform(-math.pi, math.pi)
                self._set_velocity_from_direction(math.cos(angle), math.sin(angle), sprint=False)
            else:
                self._set_input_flags_from_velocity()
            self._aim_angle = random.uniform(-math.pi, math.pi)

        dt = 0.1
        self._pos_x = max(-1000, min(1000, self._pos_x + self._vel_x * dt))
        self._pos_y = max(-1000, min(1000, self._pos_y + self._vel_y * dt))
        await self._send_input_packet(shoot_flag)

    def select_target(self) -> EntitySnapshot | None:
        """Prefer nearest alive monster, then nearest alive non-self player."""
        self_snapshot = self._get_self_snapshot()
        origin = self_snapshot or EntitySnapshot(-1, EntityType.PLAYER, self._pos_x, self._pos_y)
        self_id = self._entity_id

        monsters = [
            e for e in self._entities.values()
            if e.entity_type == EntityType.MONSTER and e.alive
        ]
        if monsters:
            return min(monsters, key=lambda e: e.distance_sq_to(origin))

        players = [
            e for e in self._entities.values()
            if e.entity_type == EntityType.PLAYER and e.alive and e.entity_id != self_id
        ]
        if players:
            return min(players, key=lambda e: e.distance_sq_to(origin))

        return None

    def _get_self_snapshot(self) -> EntitySnapshot | None:
        if self._entity_id is None:
            return None
        return self._entities.get(self._entity_id)

    def _set_velocity_from_direction(self, x: float, y: float, sprint: bool) -> None:
        length = math.sqrt(x * x + y * y)
        if length < 0.001:
            self._vel_x = 0.0
            self._vel_y = 0.0
        else:
            speed = 320.0 if sprint else 200.0
            self._vel_x = (x / length) * speed
            self._vel_y = (y / length) * speed
        self._set_input_flags_from_velocity(sprint)

    def _set_input_flags_from_velocity(self, sprint: bool = False) -> None:
        flags = 0
        if self._vel_y < -35:
            flags |= INPUT_FLAG_MOVE_UP
        if self._vel_y > 35:
            flags |= INPUT_FLAG_MOVE_DOWN
        if self._vel_x < -35:
            flags |= INPUT_FLAG_MOVE_LEFT
        if self._vel_x > 35:
            flags |= INPUT_FLAG_MOVE_RIGHT
        if sprint:
            flags |= INPUT_FLAG_SPRINT
        self._input_flags = flags

    async def _send_input_packet(self, extra_flags: int = 0):
        self._sequence = (self._sequence + 1) & 0xFF
        try:
            pkt = build_player_input(
                self._pos_x, self._pos_y,
                self._vel_x, self._vel_y,
                self._input_flags | extra_flags,
                self._aim_angle,
                self._sequence,
                0,
                self._last_rtt_ms,
            )
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
        except ConnectionClosed:
            self._running = False

    async def _send_respawn_request(self):
        if self.ws is None:
            return
        try:
            pkt = build_respawn_request()
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
            logger.debug(f"Bot {self.bot_id}: Respawn requested")
        except ConnectionClosed:
            self._running = False

    def _handle_message(self, data: bytes):
        """Parse incoming binary packet and update metrics."""
        msg_type, payload_len, payload = parse_header(data)

        if msg_type == MessageType.HEARTBEAT:
            self.metrics.heartbeats_received += 1
            if len(payload) >= 4:
                server_ts = parse_heartbeat(payload)
                # RTT: compare server echo timestamp with our clock
                now_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
                # The server echoes back our timestamp, so RTT = now - sent_timestamp
                rtt = now_ms - server_ts
                if 0 < rtt < 10000:  # Sanity check (0-10s)
                    self._last_rtt_ms = rtt
                    self.metrics.latencies_ms.append(rtt)

        elif msg_type == MessageType.STATE_UPDATE:
            self.metrics.state_updates_received += 1
            header = parse_state_update_header(payload)
            if header and "server_tick" in header:
                self.metrics.server_ticks_seen.append(header["server_tick"])
            parsed = parse_state_update(payload, self._entities)
            if parsed and self._entity_id is not None:
                self_snapshot = self._entities.get(self._entity_id)
                if self_snapshot is not None:
                    self._pos_x = self_snapshot.x
                    self._pos_y = self_snapshot.y

        elif msg_type == MessageType.GAME_EVENT:
            self.metrics.game_events_received += 1
            event = parse_game_event(payload)
            self._handle_game_event(event)

        elif msg_type == MessageType.ACTION_CONFIRM:
            pass  # Bot doesn't need to process confirmations

        elif msg_type == MessageType.SERVER_METRICS:
            sm = parse_server_metrics(payload)
            if sm:
                sm["received_at"] = time.monotonic()
                self.metrics.server_metrics_snapshots.append(sm)

    def _handle_game_event(self, event: dict):
        if not event:
            return

        event_type = event.get("event_type")
        target_id = event.get("target_id", 0)
        event_data = event.get("event_data", {})

        if event_type == GameEventType.PLAYER_INFO:
            if event_data.get("character_name") == self.character_name:
                self._entity_id = target_id
                pos = event_data.get("position")
                if pos:
                    self._pos_x, self._pos_y = pos
                logger.debug(f"Bot {self.bot_id}: Assigned entity_id={self._entity_id}")
        elif event_type == GameEventType.RESPAWN and target_id == self._entity_id:
            self._dead_since = None
            pos = event_data.get("position")
            if pos:
                self._pos_x, self._pos_y = pos

    def __repr__(self):
        return f"OmegaRealmBot(id={self.bot_id}, name={self.character_name})"
