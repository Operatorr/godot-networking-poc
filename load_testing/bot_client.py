"""
OmegaRealmBot - Load testing bot client for Omega Realm game server.

Implements the binary WebSocket protocol (little-endian) to simulate
player connections. Used for validating server performance under load.

Protocol reference: client/scripts/shared/networking/packet_types.gd
"""

import asyncio
import heapq
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
    BATCH = 11
    # Client -> Server: ack a received full-state Baseline (#14). Bots do not send
    # this today; the server's 100-tick cadence floor covers non-acking clients, so
    # a bot that never acks still receives baselines (no regression). Mirrored here
    # only to keep this enum in lockstep with packet_types.gd.
    BASELINE_ACK = 12
    # Client -> Server: "a monster projectile hit me" (client-detected, server-validated).
    # Monster->player hits are client-authoritative under the RotMG-style PvE netcode, so a
    # client that never reports takes no monster damage. Bots send this so they behave like
    # real players. See docs/netcode/hit-authority-model.md.
    LOCAL_HIT_REPORT = 13


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
    # Entity fired a projectile. source_id = owner entity id, target_id = projectile id.
    # Bots track this to learn projectile ownership (see OmegaRealmBot._handle_game_event).
    PROJECTILE_FIRED = 12


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

# Mirrored gameplay constants from client/scripts/shared/game_constants.gd.
# Keep these in sync with the authoritative server values so bots make legal
# decisions while still using only network-visible state.
SERVER_TICK_RATE = 30.0
PLAYER_SPEED = 200.0
PLAYER_SPRINT_MULTIPLIER = 1.6
PLAYER_SPRINT_SPEED = PLAYER_SPEED * PLAYER_SPRINT_MULTIPLIER
MAP_MIN_X = -1000.0
MAP_MIN_Y = -1000.0
MAP_MAX_X = 1000.0
MAP_MAX_Y = 1000.0
PROJECTILE_SPEED = 400.0
PROJECTILE_MAX_DISTANCE = 800.0
PROJECTILE_RADIUS = 8.0
# Entity-id range boundary (invariant: players 1–999, projectiles 10000–29999,
# monsters 30000–39999). A projectile is monster-owned iff its PROJECTILE_FIRED
# source_id >= this. Mirrors game_constants.gd MONSTER_ENTITY_ID_START.
MONSTER_ENTITY_ID_START = 30000
PLAYER_HITBOX_RADIUS = 16.0
MONSTER_HITBOX_RADIUS = 16.0
MONSTER_PROJECTILE_SPEED = 300.0
MONSTER_ATTACK_RANGE = 200.0
MONSTER_FLEE_DISTANCE = 100.0
MONSTER_DETECTION_RANGE = 650.0
BOT_AOI_RADIUS = 1000.0
BOT_OBSTACLE_LOOKAHEAD = 80.0
BOT_BOUNDARY_AVOID_DISTANCE = 130.0
BOT_SEPARATION_DISTANCE = 90.0
BOT_INPUT_INTERVAL = 0.1
NAV_CELL_SIZE = 100.0
NAV_COLUMNS = int((MAP_MAX_X - MAP_MIN_X) / NAV_CELL_SIZE)
NAV_ROWS = int((MAP_MAX_Y - MAP_MIN_Y) / NAV_CELL_SIZE)
INF = float("inf")

STRATEGY_STATE_HUNT = "hunt"
STRATEGY_STATE_ENGAGE = "engage"
STRATEGY_STATE_FLANK = "flank"
STRATEGY_STATE_EVADE = "evade"
STRATEGY_STATE_DEAD = "dead"

ARENA_OBSTACLES: tuple[tuple[float, float, float, float], ...] = (
    (-20.0, -200.0, 40.0, 160.0),
    (-20.0, 40.0, 40.0, 160.0),
    (-200.0, -20.0, 160.0, 40.0),
    (40.0, -20.0, 160.0, 40.0),
    (-700.0, -700.0, 150.0, 30.0),
    (-700.0, -700.0, 30.0, 150.0),
    (550.0, -700.0, 150.0, 30.0),
    (670.0, -700.0, 30.0, 150.0),
    (-700.0, 670.0, 150.0, 30.0),
    (-700.0, 550.0, 30.0, 150.0),
    (550.0, 670.0, 150.0, 30.0),
    (670.0, 550.0, 30.0, 150.0),
    (-450.0, -350.0, 100.0, 25.0),
    (350.0, -350.0, 100.0, 25.0),
    (-450.0, 325.0, 100.0, 25.0),
    (350.0, 325.0, 100.0, 25.0),
)

ARENA_PLAYER_SPAWNS: tuple[tuple[float, float], ...] = (
    (-800.0, -800.0),
    (0.0, -800.0),
    (800.0, -800.0),
    (-800.0, 0.0),
    (800.0, 0.0),
    (-800.0, 800.0),
    (0.0, 800.0),
    (800.0, 800.0),
    (-450.0, 450.0),
    (450.0, -450.0),
)

ARENA_MONSTER_SPAWNS: tuple[tuple[float, float], ...] = (
    (-450.0, -800.0),
    (450.0, -800.0),
    (-900.0, -450.0),
    (900.0, -450.0),
    (-900.0, 450.0),
    (900.0, 450.0),
    (-450.0, 800.0),
    (450.0, 800.0),
    (0.0, -500.0),
    (0.0, 500.0),
    (-500.0, 0.0),
    (500.0, 0.0),
)

HUNT_PATROL_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, -760.0),
    (760.0, -760.0),
    (760.0, 0.0),
    (760.0, 760.0),
    (0.0, 760.0),
    (-760.0, 760.0),
    (-760.0, 0.0),
    (-760.0, -760.0),
    (-520.0, -520.0),
    (520.0, -520.0),
    (520.0, 520.0),
    (-520.0, 520.0),
    (0.0, -520.0),
    (520.0, 0.0),
    (0.0, 520.0),
    (-520.0, 0.0),
)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _clamp_difficulty(value: float) -> float:
    try:
        return _clamp(float(value), 0.0, 1.0)
    except (TypeError, ValueError):
        return 1.0


def _length(x: float, y: float) -> float:
    return math.sqrt(x * x + y * y)


def _normalize(x: float, y: float) -> tuple[float, float]:
    length = _length(x, y)
    if length < 0.001:
        return 0.0, 0.0
    return x / length, y / length


def _distance_point_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    abx = bx - ax
    aby = by - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq <= 0.0001:
        return _length(px - ax, py - ay)
    t = _clamp(((px - ax) * abx + (py - ay) * aby) / ab_len_sq, 0.0, 1.0)
    closest_x = ax + abx * t
    closest_y = ay + aby * t
    return _length(px - closest_x, py - closest_y)


def _point_in_rect(px: float, py: float, rect: tuple[float, float, float, float]) -> bool:
    rx, ry, rw, rh = rect
    return rx <= px <= rx + rw and ry <= py <= ry + rh


def _expanded_rect(rect: tuple[float, float, float, float], radius: float) -> tuple[float, float, float, float]:
    rx, ry, rw, rh = rect
    return rx - radius, ry - radius, rw + radius * 2.0, rh + radius * 2.0


def circle_intersects_obstacle(x: float, y: float, radius: float) -> bool:
    for obs in ARENA_OBSTACLES:
        if _point_in_rect(x, y, _expanded_rect(obs, radius)):
            return True
    return False


def _line_rect_intersection(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    rect: tuple[float, float, float, float],
) -> tuple[float, float] | None:
    rx, ry, rw, rh = rect
    dx = bx - ax
    dy = by - ay
    t_min = 0.0
    t_max = 1.0

    if abs(dx) < 0.0001:
        if ax < rx or ax > rx + rw:
            return None
    else:
        t1 = (rx - ax) / dx
        t2 = (rx + rw - ax) / dx
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return None

    if abs(dy) < 0.0001:
        if ay < ry or ay > ry + rh:
            return None
    else:
        t1 = (ry - ay) / dy
        t2 = (ry + rh - ay) / dy
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return None

    if 0.0 <= t_min <= 1.0:
        return ax + dx * t_min, ay + dy * t_min
    return None


def line_intersects_obstacle(ax: float, ay: float, bx: float, by: float) -> bool:
    for obs in ARENA_OBSTACLES:
        if _line_rect_intersection(ax, ay, bx, by, obs) is not None:
            return True
    return False


def _movement_hits_obstacle(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    radius: float,
) -> bool:
    if circle_intersects_obstacle(bx, by, radius):
        return True
    for obs in ARENA_OBSTACLES:
        if _line_rect_intersection(ax, ay, bx, by, _expanded_rect(obs, radius)) is not None:
            return True
    return False


def move_with_obstacle_collision(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    radius: float,
) -> tuple[float, float]:
    target_x = _clamp(bx, MAP_MIN_X, MAP_MAX_X)
    target_y = _clamp(by, MAP_MIN_Y, MAP_MAX_Y)
    if not _movement_hits_obstacle(ax, ay, target_x, target_y, radius):
        return target_x, target_y

    x_target = (_clamp(target_x, MAP_MIN_X, MAP_MAX_X), _clamp(ay, MAP_MIN_Y, MAP_MAX_Y))
    y_target = (_clamp(ax, MAP_MIN_X, MAP_MAX_X), _clamp(target_y, MAP_MIN_Y, MAP_MAX_Y))
    best_x, best_y = ax, ay
    best_dist_sq = (target_x - ax) ** 2 + (target_y - ay) ** 2

    if not _movement_hits_obstacle(ax, ay, x_target[0], x_target[1], radius):
        best_x, best_y = x_target
        best_dist_sq = (target_x - best_x) ** 2 + (target_y - best_y) ** 2

    if not _movement_hits_obstacle(ax, ay, y_target[0], y_target[1], radius):
        y_dist_sq = (target_x - y_target[0]) ** 2 + (target_y - y_target[1]) ** 2
        if y_dist_sq < best_dist_sq:
            best_x, best_y = y_target

    return best_x, best_y


def _is_walkable_point(x: float, y: float, radius: float = PLAYER_HITBOX_RADIUS) -> bool:
    return (
        MAP_MIN_X + radius <= x <= MAP_MAX_X - radius
        and MAP_MIN_Y + radius <= y <= MAP_MAX_Y - radius
        and not circle_intersects_obstacle(x, y, radius)
    )


def _world_to_nav_cell(x: float, y: float) -> tuple[int, int]:
    col = int((x - MAP_MIN_X) / NAV_CELL_SIZE)
    row = int((y - MAP_MIN_Y) / NAV_CELL_SIZE)
    return max(0, min(NAV_COLUMNS - 1, col)), max(0, min(NAV_ROWS - 1, row))


def _nav_cell_center(cell: tuple[int, int]) -> tuple[float, float]:
    col, row = cell
    return (
        MAP_MIN_X + (col + 0.5) * NAV_CELL_SIZE,
        MAP_MIN_Y + (row + 0.5) * NAV_CELL_SIZE,
    )


def _is_walkable_nav_cell(cell: tuple[int, int]) -> bool:
    col, row = cell
    if col < 0 or row < 0 or col >= NAV_COLUMNS or row >= NAV_ROWS:
        return False
    x, y = _nav_cell_center(cell)
    return _is_walkable_point(x, y)


def _nearest_walkable_nav_cell(x: float, y: float) -> tuple[int, int]:
    start = _world_to_nav_cell(x, y)
    if _is_walkable_nav_cell(start):
        return start

    for radius in range(1, max(NAV_COLUMNS, NAV_ROWS)):
        candidates: list[tuple[int, int]] = []
        for dx in range(-radius, radius + 1):
            candidates.append((start[0] + dx, start[1] - radius))
            candidates.append((start[0] + dx, start[1] + radius))
        for dy in range(-radius + 1, radius):
            candidates.append((start[0] - radius, start[1] + dy))
            candidates.append((start[0] + radius, start[1] + dy))
        walkable = [cell for cell in candidates if _is_walkable_nav_cell(cell)]
        if walkable:
            return min(walkable, key=lambda cell: (_nav_cell_center(cell)[0] - x) ** 2 + (_nav_cell_center(cell)[1] - y) ** 2)
    return start


def _find_nav_path(start_x: float, start_y: float, goal_x: float, goal_y: float) -> list[tuple[float, float]]:
    start = _nearest_walkable_nav_cell(start_x, start_y)
    goal = _nearest_walkable_nav_cell(goal_x, goal_y)
    if start == goal:
        return [(goal_x, goal_y)] if _is_walkable_point(goal_x, goal_y) else [_nav_cell_center(goal)]

    def heuristic(cell: tuple[int, int]) -> float:
        return math.hypot(goal[0] - cell[0], goal[1] - cell[1])

    open_set: list[tuple[float, float, tuple[int, int]]] = []
    heapq.heappush(open_set, (heuristic(start), 0.0, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], float] = {start: 0.0}
    closed: set[tuple[int, int]] = set()
    neighbors = (
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    )

    while open_set:
        _, current_cost, current = heapq.heappop(open_set)
        if current in closed:
            continue
        if current == goal:
            cells: list[tuple[int, int]] = [current]
            while current in came_from:
                current = came_from[current]
                cells.append(current)
            cells.reverse()
            path = [_nav_cell_center(cell) for cell in cells[1:]]
            if _is_walkable_point(goal_x, goal_y):
                path.append((goal_x, goal_y))
            return _smooth_nav_path(start_x, start_y, path)

        closed.add(current)
        for dx, dy in neighbors:
            neighbor = (current[0] + dx, current[1] + dy)
            if not _is_walkable_nav_cell(neighbor):
                continue
            if dx != 0 and dy != 0:
                if not _is_walkable_nav_cell((current[0] + dx, current[1])) or not _is_walkable_nav_cell((current[0], current[1] + dy)):
                    continue
            current_x, current_y = _nav_cell_center(current)
            neighbor_x, neighbor_y = _nav_cell_center(neighbor)
            if _movement_hits_obstacle(current_x, current_y, neighbor_x, neighbor_y, PLAYER_HITBOX_RADIUS):
                continue
            step_cost = 1.4142 if dx != 0 and dy != 0 else 1.0
            tentative = current_cost + step_cost
            if tentative >= g_score.get(neighbor, INF):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            heapq.heappush(open_set, (tentative + heuristic(neighbor), tentative, neighbor))

    fallback = _nav_cell_center(goal)
    return [(fallback[0], fallback[1])]


def _smooth_nav_path(start_x: float, start_y: float, path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(path) <= 1:
        return path

    result: list[tuple[float, float]] = []
    anchor_x = start_x
    anchor_y = start_y
    index = 0
    while index < len(path):
        furthest = index
        for candidate in range(len(path) - 1, index - 1, -1):
            px, py = path[candidate]
            if not _movement_hits_obstacle(anchor_x, anchor_y, px, py, PLAYER_HITBOX_RADIUS):
                furthest = candidate
                break
        waypoint = path[furthest]
        result.append(waypoint)
        anchor_x, anchor_y = waypoint
        index = furthest + 1
    return result


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
    bandwidth_budget_bps: int = 0,
) -> bytes:
    """Build CONNECT_AUTH packet.
    Format: [string token][string char_id][string char_name][u8 region]
            [optional rgb][optional u32 bandwidth_budget_bps]
    Strings are: [u16 length][utf8 bytes]
    The trailing u32 budget (#13) is server-clamped to [min,max]; 0 means "let the
    server decide". The server reads it length-gated AFTER the color triple, so we
    only append it when a color is present (otherwise it would misalign).
    """
    payload = bytearray()
    for s in (token, character_id, character_name):
        encoded = s.encode("utf-8")
        payload += struct.pack("<H", len(encoded))
        payload += encoded
    payload += struct.pack("<B", region)
    if player_color is not None:
        payload += bytes(max(0, min(255, int(c))) for c in player_color[:3])
        payload += struct.pack("<I", max(0, int(bandwidth_budget_bps)))
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


def build_local_hit_report(projectile_id: int) -> bytes:
    """Build LOCAL_HIT_REPORT packet. [u16 projectile_id]"""
    payload = struct.pack("<H", projectile_id & 0xFFFF)
    return build_header(MessageType.LOCAL_HIT_REPORT, payload)


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
    # 5-byte common header [u32 server_tick][u8 state_flags]; full-state then reads
    # a u16 entity_count at offset 5 (needs 7 bytes total). The delta path enforces
    # its own >=11 guard below before reading the count at offset 9.
    if len(payload) < 7:
        return {}
    server_tick, state_flags = struct.unpack_from("<IB", payload, 0)
    is_delta = bool(state_flags & STATE_FLAG_IS_DELTA)
    # Delta packets have a 4-byte baseline_tick before the u16 entity_count
    if is_delta:
        if len(payload) < 11:
            return {"server_tick": server_tick, "state_flags": state_flags, "is_delta": True, "entity_count": 0}
        entity_count = struct.unpack_from("<H", payload, 9)[0]
    else:
        entity_count = struct.unpack_from("<H", payload, 5)[0]
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
    vx: float = 0.0
    vy: float = 0.0
    last_seen_tick: int = 0
    last_seen_at: float = 0.0

    @property
    def alive(self) -> bool:
        return bool(self.flags & ENTITY_FLAG_ALIVE)

    @property
    def visible(self) -> bool:
        return bool(self.flags & ENTITY_FLAG_VISIBLE)

    def distance_sq_to(self, other: "EntitySnapshot") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def distance_to(self, other: "EntitySnapshot") -> float:
        return math.sqrt(self.distance_sq_to(other))


@dataclass
class TacticalDecision:
    move_x: float = 0.0
    move_y: float = 0.0
    aim_angle: float = 0.0
    shoot: bool = False
    sprint: bool = False
    target_id: int | None = None
    state: str = STRATEGY_STATE_HUNT


def _tracked_snapshot(
    entity_id: int,
    entity_type: int,
    x: float,
    y: float,
    animation_state: int,
    flags: int,
    previous: EntitySnapshot | None,
    server_tick: int,
) -> EntitySnapshot:
    snapshot = EntitySnapshot(
        entity_id,
        entity_type,
        x,
        y,
        animation_state,
        flags,
        last_seen_tick=server_tick,
        last_seen_at=time.monotonic(),
    )
    if previous is None:
        return snapshot

    tick_delta = max(1, server_tick - previous.last_seen_tick)
    dt = tick_delta / SERVER_TICK_RATE
    if abs(x - previous.x) > 0.01 or abs(y - previous.y) > 0.01:
        snapshot.vx = (x - previous.x) / dt
        snapshot.vy = (y - previous.y) / dt
    else:
        snapshot.vx = 0.0
        snapshot.vy = 0.0
    return snapshot


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
    # tick(4) + flags(1) + u16 count(2) = 7 byte minimum for a full-state header
    if len(payload) < 7:
        return {}

    offset = 0
    server_tick = struct.unpack_from("<I", payload, offset)[0]
    offset += 4
    state_flags, offset = _read_u8(payload, offset)
    is_delta = bool(state_flags & STATE_FLAG_IS_DELTA)
    baseline_tick = 0
    if is_delta:
        # baseline_tick(4) + u16 count(2) = 6 bytes still required at this offset
        if len(payload) < offset + 6:
            return {"server_tick": server_tick, "state_flags": state_flags, "is_delta": True, "entities": []}
        baseline_tick = struct.unpack_from("<I", payload, offset)[0]
        offset += 4

    entity_count, offset = _read_u16(payload, offset)
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
            snapshot = _tracked_snapshot(
                entity_id,
                entity_type,
                qx / POSITION_SCALE,
                qy / POSITION_SCALE,
                animation_state,
                flags,
                last_states.get(entity_id),
                server_tick,
            )
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
            snapshot = _tracked_snapshot(
                entity_id,
                entity_type,
                qx / POSITION_SCALE,
                qy / POSITION_SCALE,
                animation_state,
                flags,
                previous,
                server_tick,
            )
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
            snapshot = _tracked_snapshot(
                entity_id,
                entity_type,
                x,
                y,
                animation_state,
                flags,
                previous,
                server_tick,
            )

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
            [u16 sched_deferred][u16 sched_qage][u8 sched_budget_pct]
            [u16 sched_peers][u16 sched_overflow]
    Total: 33 bytes (legacy 24-byte payloads still decode the leading 8 fields).
    """
    if len(payload) < 24:
        return {}
    tick, avg_tick_100, max_tick_100, players, entities, bytes_sent, bytes_recv, avg_bw = \
        struct.unpack_from("<IHHHHIII", payload, 0)
    result = {
        "tick_count": tick,
        "avg_tick_time_ms": avg_tick_100 / 100.0,
        "max_tick_time_ms": max_tick_100 / 100.0,
        "player_count": players,
        "entity_count": entities,
        "total_bytes_sent": bytes_sent,
        "total_bytes_received": bytes_recv,
        "avg_bandwidth_per_client": avg_bw,
    }
    # Scheduler diagnostics (§8.2). Appended in lockstep with the GDScript
    # encode (network_manager.gd SERVER_METRICS case).
    if len(payload) >= 33:
        deferred, qage, budget_pct, peers, overflow = \
            struct.unpack_from("<HHBHH", payload, 24)
        result["sched_entities_deferred"] = deferred
        result["sched_max_queue_age_ticks"] = qage
        result["sched_peers_at_budget_pct"] = budget_pct
        result["sched_peers_evaluated"] = peers
        result["sched_snapshot_overflow"] = overflow
    return result


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
    # --- Phase 2 §8.3 regression-assertion fields ---
    # BATCH envelopes that truncated, overflowed, or otherwise failed to fully unwrap.
    # Inner packet decode failures bubble up here too so a single counter is the gate.
    decode_failures: int = 0
    # Per-entity observation log: entity_id -> list of (server_tick, distance_to_self).
    # Populated only after this bot knows its own entity_id. Used to validate AoI culling
    # and LOD cadence — the only knobs the server exposes that bots can independently see.
    entity_observations: dict[int, list[tuple[int, float]]] = field(default_factory=dict)
    # Max distance to any entity observed in a STATE_UPDATE while bot's own position is known.
    # Should never exceed server's aoi_exit_radius (plus a small tolerance for race conditions
    # where the entity exited AoI on the same tick we received the snapshot).
    max_observed_entity_distance: float = 0.0
    # Per-second outbound byte samples for rolling-window budget assertion.
    # List of (monotonic_seconds, cumulative_bytes_received). Sampled by the time-series
    # collector in bot_swarm so we can compute peak 1s rates without tracking per-packet.
    bytes_received_samples: list[tuple[float, int]] = field(default_factory=list)

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

    def __init__(
        self,
        bot_id: int,
        server_url: str,
        token: str = "",
        behavior: str = BEHAVIOR_DEFAULT,
        difficulty: float = 1.0,
        bandwidth_budget_bps: int = 0,
    ):
        self.bot_id = bot_id
        self.server_url = server_url
        self.character_id, self.character_name = generate_bot_identity(bot_id)
        self.player_color = generate_bright_color(bot_id)
        self.token = token
        self.behavior = behavior
        self.difficulty = _clamp_difficulty(difficulty)
        # Advertised CONNECT_AUTH egress budget (#13). 0 = let the server decide.
        self.bandwidth_budget_bps = max(0, int(bandwidth_budget_bps))
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
        self._input_flags = 0
        self._last_heartbeat_sent = 0.0
        self._last_input_sent = 0.0
        self._last_rtt_ms = 0
        self._latest_server_tick = 0
        self._entity_id: int | None = None
        self._entities: dict[int, EntitySnapshot] = {}
        self._dead_since: float | None = None
        # Client-side monster-hit reporting (so bots take monster damage like real
        # players). Report each projectile at most once; rate-limit to match the
        # server's per-peer cap (LOCAL_HIT_REPORT_MAX_PER_SECOND = 20).
        self._reported_projectile_ids: set[int] = set()
        self._hit_report_window_start = 0.0
        self._hit_report_count = 0
        # projectile_id -> owner entity id, learned from PROJECTILE_FIRED. Lets us
        # report only monster-owned bullets (PvE hits the server can honour) instead
        # of spending hit-report quota on player-fired bullets it will reject.
        self._projectile_sources: dict[int, int] = {}
        self._last_respawn_sent = 0.0
        self._target_id: int | None = None
        self._last_decision_time = 0.0
        self._decision_cache: TacticalDecision | None = None
        self._explore_angle = random.uniform(-math.pi, math.pi)
        self._explore_until = 0.0
        self._strafe_dir = 1.0 if bot_id % 2 == 0 else -1.0
        self._strategy_state = STRATEGY_STATE_HUNT
        self._hunt_goal: tuple[float, float] | None = None
        self._hunt_path: list[tuple[float, float]] = []
        self._hunt_path_index = 0
        self._hunt_goal_started_at = 0.0
        self._hunt_last_progress_pos = (self._pos_x, self._pos_y)
        self._hunt_last_progress_at = 0.0
        self._hunt_goal_visits: dict[tuple[float, float], float] = {}
        self._blocked_target_id: int | None = None
        self._blocked_since = 0.0
        self._last_clear_shot_at = 0.0
        self._flank_target_id: int | None = None
        self._flank_goal: tuple[float, float] | None = None
        self._flank_path: list[tuple[float, float]] = []
        self._flank_path_index = 0
        self._flank_started_at = 0.0
        self._flank_last_progress_pos = (self._pos_x, self._pos_y)
        self._flank_last_progress_at = 0.0

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
                self.token, self.character_id, self.character_name, 0,
                self.player_color, self.bandwidth_budget_bps
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

            # Detect incoming projectiles and report hits so bots take monster damage
            # like real players (runs at the 50Hz poll rate; cheap distance check).
            if self.behavior != BEHAVIOR_IDLE:
                await self._detect_and_report_hits()

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
                self._latest_server_tick & 0xFFFF,
                self._last_rtt_ms,
            )
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
        except ConnectionClosed:
            self._running = False

    async def _send_strategy_input(self):
        """Send PLAYER_INPUT from a difficulty-scaled tactical gameplay strategy."""
        if self.ws is None:
            return

        now = time.monotonic()
        self_snapshot = self._get_self_snapshot()
        if self_snapshot is not None:
            self._pos_x = self_snapshot.x
            self._pos_y = self_snapshot.y
            if not self_snapshot.alive:
                self._strategy_state = STRATEGY_STATE_DEAD
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

        decision = self._get_strategy_decision(now, self_snapshot)
        self._aim_angle = decision.aim_angle
        self._set_velocity_from_direction(decision.move_x, decision.move_y, sprint=decision.sprint)

        dt = BOT_INPUT_INTERVAL
        self._pos_x, self._pos_y = move_with_obstacle_collision(
            self._pos_x,
            self._pos_y,
            self._pos_x + self._vel_x * dt,
            self._pos_y + self._vel_y * dt,
            PLAYER_HITBOX_RADIUS,
        )
        shoot_flag = INPUT_FLAG_SHOOT if decision.shoot else 0
        await self._send_input_packet(shoot_flag)

    def select_target(self, now: float | None = None) -> EntitySnapshot | None:
        """Select the best visible combat target using score, threat, and stickiness."""
        self_snapshot = self._get_self_snapshot()
        origin = self_snapshot or EntitySnapshot(-1, EntityType.PLAYER, self._pos_x, self._pos_y)
        now = time.monotonic() if now is None else now

        best: EntitySnapshot | None = None
        best_score = -INF
        for entity in self._entities.values():
            score = self._score_target(entity, origin, now)
            if score > best_score:
                best = entity
                best_score = score

        if best is not None and best_score > -INF:
            self._target_id = best.entity_id
            return best
        self._target_id = None
        self._reset_blocked_target()
        self._reset_flank()
        return None

    def _score_target(self, entity: EntitySnapshot, origin: EntitySnapshot, now: float | None = None) -> float:
        if entity.entity_id == self._entity_id:
            return -INF
        if entity.entity_type not in (EntityType.PLAYER, EntityType.MONSTER):
            return -INF
        if not entity.alive or not entity.visible:
            return -INF

        dist = entity.distance_to(origin)
        if dist > BOT_AOI_RADIUS * 1.25:
            return -INF

        now = time.monotonic() if now is None else now
        age = 0.0 if entity.last_seen_at <= 0.0 else max(0.0, now - entity.last_seen_at)
        freshness = _clamp(1.0 - age / 1.5, 0.0, 1.0)
        distance_score = _clamp(1.0 - dist / BOT_AOI_RADIUS, 0.0, 1.0) * 35.0

        if entity.entity_type == EntityType.MONSTER:
            base_score = 65.0
            threat_score = _clamp(1.0 - dist / MONSTER_DETECTION_RANGE, 0.0, 1.0) * 22.0
        else:
            base_score = 30.0
            threat_score = _clamp(1.0 - dist / 520.0, 0.0, 1.0) * 30.0

        speed = _length(entity.vx, entity.vy)
        movement_threat = _clamp(speed / PLAYER_SPRINT_SPEED, 0.0, 1.0) * 8.0
        stickiness = 22.0 * (0.5 + self.difficulty * 0.5) if entity.entity_id == self._target_id else 0.0
        return base_score + distance_score + threat_score + movement_threat + freshness * 12.0 + stickiness

    def _get_strategy_decision(self, now: float, self_snapshot: EntitySnapshot | None) -> TacticalDecision:
        reaction_interval = 0.04 + (1.0 - self.difficulty) * 0.46
        if self._decision_cache is None or now - self._last_decision_time >= reaction_interval:
            self._decision_cache = self._compute_strategy_decision(now, self_snapshot)
            self._last_decision_time = now
        return self._decision_cache

    def _compute_strategy_decision(
        self,
        now: float | None = None,
        self_snapshot: EntitySnapshot | None = None,
    ) -> TacticalDecision:
        now = time.monotonic() if now is None else now
        origin = self_snapshot or self._get_self_snapshot() or EntitySnapshot(
            -1, EntityType.PLAYER, self._pos_x, self._pos_y
        )
        target = self.select_target(now)

        if target is None:
            decision = self._hunt_decision(origin, now)
        else:
            self._strategy_state = STRATEGY_STATE_ENGAGE
            dx = target.x - origin.x
            dy = target.y - origin.y
            dist = max(0.001, _length(dx, dy))
            move_x, move_y, sprint = self._movement_for_target(origin, target, dist, now)
            decision = TacticalDecision(move_x, move_y, self._aim_angle, False, sprint, target.entity_id, STRATEGY_STATE_ENGAGE)

        dodge = self._best_projectile_dodge(origin)
        if dodge is not None:
            self._strategy_state = STRATEGY_STATE_EVADE
            dodge_x, dodge_y, urgency = dodge
            decision.move_x = decision.move_x * 0.35 + dodge_x * (1.2 + urgency)
            decision.move_y = decision.move_y * 0.35 + dodge_y * (1.2 + urgency)
            decision.sprint = urgency > 0.25 or self.difficulty >= 0.6
            decision.state = STRATEGY_STATE_EVADE

        sep_x, sep_y = self._target_separation_vector(origin)
        decision.move_x += sep_x * 0.45
        decision.move_y += sep_y * 0.45
        decision.move_x, decision.move_y = self._steer_around_static_hazards(
            origin.x,
            origin.y,
            decision.move_x,
            decision.move_y,
        )
        decision.move_x, decision.move_y = self._quantize_movement_direction(
            decision.move_x,
            decision.move_y,
            decision.sprint,
        )

        if target is not None:
            decision = self._finalize_target_decision(origin, target, decision, now)
        return decision

    def _finalize_target_decision(
        self,
        origin: EntitySnapshot,
        target: EntitySnapshot,
        decision: TacticalDecision,
        now: float,
    ) -> TacticalDecision:
        decision = self._aim_and_score_shot(origin, target, decision, apply_error=True)
        if decision.shoot:
            self._reset_blocked_target()
            if decision.state != STRATEGY_STATE_FLANK:
                self._reset_flank()
            self._last_clear_shot_at = now
            return decision

        fire_x, fire_y = self._project_fire_origin(origin, decision.move_x, decision.move_y, decision.sprint)
        predicted_x, predicted_y = self._predict_target_position(target, PROJECTILE_SPEED, EntitySnapshot(-1, EntityType.PLAYER, fire_x, fire_y))
        clear_shot = self._line_of_fire_clear(fire_x, fire_y, predicted_x, predicted_y)
        if clear_shot:
            self._reset_blocked_target()
            self._last_clear_shot_at = now
            return decision

        self._record_blocked_target(target.entity_id, now)
        if decision.state != STRATEGY_STATE_EVADE and self._should_flank_blocked_target(target, now):
            flank_decision = self._flank_decision(origin, target, now)
            flank_decision.move_x, flank_decision.move_y = self._steer_around_static_hazards(
                origin.x,
                origin.y,
                flank_decision.move_x,
                flank_decision.move_y,
            )
            flank_decision.move_x, flank_decision.move_y = self._quantize_movement_direction(
                flank_decision.move_x,
                flank_decision.move_y,
                flank_decision.sprint,
            )
            return self._aim_and_score_shot(origin, target, flank_decision, apply_error=False)

        return decision

    def _aim_and_score_shot(
        self,
        origin: EntitySnapshot,
        target: EntitySnapshot,
        decision: TacticalDecision,
        apply_error: bool,
    ) -> TacticalDecision:
        fire_x, fire_y = self._project_fire_origin(
            origin,
            decision.move_x,
            decision.move_y,
            decision.sprint,
        )
        aim_origin = EntitySnapshot(-1, EntityType.PLAYER, fire_x, fire_y)
        predicted_x, predicted_y = self._predict_target_position(target, PROJECTILE_SPEED, aim_origin)
        decision.aim_angle = math.atan2(predicted_y - fire_y, predicted_x - fire_x)
        if apply_error:
            decision.aim_angle += self._difficulty_aim_error(_length(target.x - fire_x, target.y - fire_y))

        clear_shot = self._line_of_fire_clear(fire_x, fire_y, predicted_x, predicted_y)
        shoot_range = self._accurate_shoot_range(target)
        fire_distance = _length(target.x - fire_x, target.y - fire_y)
        decision.shoot = clear_shot and fire_distance <= shoot_range
        return decision

    def _record_blocked_target(self, target_id: int, now: float) -> None:
        if self._blocked_target_id != target_id:
            self._blocked_target_id = target_id
            self._blocked_since = now

    def _reset_blocked_target(self) -> None:
        self._blocked_target_id = None
        self._blocked_since = 0.0

    def _should_flank_blocked_target(self, target: EntitySnapshot, now: float) -> bool:
        if self._blocked_target_id != target.entity_id or self._blocked_since <= 0.0:
            return False
        delay = 1.4 - self.difficulty * 0.9
        return now - self._blocked_since >= delay

    def _reset_flank(self) -> None:
        self._flank_target_id = None
        self._flank_goal = None
        self._flank_path = []
        self._flank_path_index = 0
        self._flank_started_at = 0.0

    def _flank_decision(self, origin: EntitySnapshot, target: EntitySnapshot, now: float) -> TacticalDecision:
        self._strategy_state = STRATEGY_STATE_FLANK
        if self._flank_needs_replan(origin, target, now):
            self._set_flank_goal(origin, target, now)

        waypoint = self._current_flank_waypoint(origin)
        if waypoint is None:
            self._set_flank_goal(origin, target, now)
            waypoint = self._current_flank_waypoint(origin)

        if waypoint is None:
            dx = target.x - origin.x
            dy = target.y - origin.y
        else:
            dx = waypoint[0] - origin.x
            dy = waypoint[1] - origin.y

        move_x, move_y = _normalize(dx, dy)
        aim_angle = math.atan2(target.y - origin.y, target.x - origin.x)
        return TacticalDecision(move_x, move_y, aim_angle, False, True, target.entity_id, STRATEGY_STATE_FLANK)

    def _flank_needs_replan(self, origin: EntitySnapshot, target: EntitySnapshot, now: float) -> bool:
        if self._flank_target_id != target.entity_id or self._flank_goal is None:
            return True
        if now - self._flank_started_at > 8.0:
            return True
        if self._flank_goal is not None and _length(self._flank_goal[0] - origin.x, self._flank_goal[1] - origin.y) < 70.0:
            return True

        moved = _length(origin.x - self._flank_last_progress_pos[0], origin.y - self._flank_last_progress_pos[1])
        if moved >= 45.0:
            self._flank_last_progress_pos = (origin.x, origin.y)
            self._flank_last_progress_at = now
            return False
        return now - self._flank_last_progress_at > 1.8

    def _set_flank_goal(self, origin: EntitySnapshot, target: EntitySnapshot, now: float) -> None:
        self._flank_target_id = target.entity_id
        self._flank_goal = self._choose_flank_goal(origin, target)
        if self._flank_goal is None:
            self._flank_goal = self._choose_hunt_goal(origin, now)
        self._flank_path = _find_nav_path(origin.x, origin.y, self._flank_goal[0], self._flank_goal[1])
        self._flank_path_index = 0
        self._flank_started_at = now
        self._flank_last_progress_pos = (origin.x, origin.y)
        self._flank_last_progress_at = now

    def _current_flank_waypoint(self, origin: EntitySnapshot) -> tuple[float, float] | None:
        while self._flank_path_index < len(self._flank_path):
            waypoint = self._flank_path[self._flank_path_index]
            if _length(waypoint[0] - origin.x, waypoint[1] - origin.y) >= 65.0:
                return waypoint
            self._flank_path_index += 1

        if self._flank_goal is not None and _length(self._flank_goal[0] - origin.x, self._flank_goal[1] - origin.y) >= 65.0:
            return self._flank_goal
        return None

    def _choose_flank_goal(self, origin: EntitySnapshot, target: EntitySnapshot) -> tuple[float, float] | None:
        base_angle = math.atan2(origin.y - target.y, origin.x - target.x)
        angle_offsets = (
            math.pi * 0.5,
            -math.pi * 0.5,
            math.pi * 0.75,
            -math.pi * 0.75,
            math.pi,
            math.pi * 0.25,
            -math.pi * 0.25,
        )
        radii = (260.0, 340.0, 430.0, 520.0)
        best_goal: tuple[float, float] | None = None
        best_score = INF

        for radius in radii:
            for offset in angle_offsets:
                angle = base_angle + offset
                goal = (
                    _clamp(target.x + math.cos(angle) * radius, MAP_MIN_X + 70.0, MAP_MAX_X - 70.0),
                    _clamp(target.y + math.sin(angle) * radius, MAP_MIN_Y + 70.0, MAP_MAX_Y - 70.0),
                )
                if not _is_walkable_point(goal[0], goal[1]):
                    continue
                if not self._line_of_fire_clear(goal[0], goal[1], target.x, target.y):
                    continue

                path = _find_nav_path(origin.x, origin.y, goal[0], goal[1])
                if not path:
                    continue
                path_cost = self._path_length((origin.x, origin.y), path)
                target_distance = _length(goal[0] - target.x, goal[1] - target.y)
                distance_penalty = abs(target_distance - 340.0) * 0.35
                side_bonus = -80.0 if abs(offset) <= math.pi * 0.55 else 0.0
                score = path_cost + distance_penalty + side_bonus
                if score < best_score:
                    best_score = score
                    best_goal = goal

        return best_goal

    def _path_length(self, start: tuple[float, float], path: list[tuple[float, float]]) -> float:
        total = 0.0
        from_x, from_y = start
        for to_x, to_y in path:
            total += _length(to_x - from_x, to_y - from_y)
            from_x, from_y = to_x, to_y
        return total

    def _hunt_decision(self, origin: EntitySnapshot, now: float) -> TacticalDecision:
        self._strategy_state = STRATEGY_STATE_HUNT
        if self._hunt_last_progress_at <= 0.0:
            self._hunt_last_progress_at = now
            self._hunt_last_progress_pos = (origin.x, origin.y)

        if self._hunt_goal is None or self._hunt_goal_reached(origin) or self._hunt_is_stale_or_stuck(origin, now):
            self._set_hunt_goal(self._choose_hunt_goal(origin, now), origin, now)

        waypoint = self._current_hunt_waypoint(origin)
        if waypoint is None:
            self._set_hunt_goal(self._choose_hunt_goal(origin, now), origin, now)
            waypoint = self._current_hunt_waypoint(origin)

        if waypoint is None:
            move_x, move_y = self._exploration_direction(origin, now)
            aim_angle = math.atan2(move_y, move_x) if move_x != 0.0 or move_y != 0.0 else self._aim_angle
            return TacticalDecision(move_x, move_y, aim_angle, False, True, None, STRATEGY_STATE_HUNT)

        dx = waypoint[0] - origin.x
        dy = waypoint[1] - origin.y
        move_x, move_y = _normalize(dx, dy)
        aim_angle = math.atan2(move_y, move_x) if move_x != 0.0 or move_y != 0.0 else self._aim_angle
        return TacticalDecision(move_x, move_y, aim_angle, False, True, None, STRATEGY_STATE_HUNT)

    def _hunt_goal_reached(self, origin: EntitySnapshot) -> bool:
        if self._hunt_goal is None:
            return True
        return _length(self._hunt_goal[0] - origin.x, self._hunt_goal[1] - origin.y) < 85.0

    def _hunt_is_stale_or_stuck(self, origin: EntitySnapshot, now: float) -> bool:
        if self._hunt_goal_started_at > 0.0 and now - self._hunt_goal_started_at > 24.0:
            return True

        moved = _length(origin.x - self._hunt_last_progress_pos[0], origin.y - self._hunt_last_progress_pos[1])
        if moved >= 45.0:
            self._hunt_last_progress_pos = (origin.x, origin.y)
            self._hunt_last_progress_at = now
            return False

        return now - self._hunt_last_progress_at > 2.2

    def _set_hunt_goal(self, goal: tuple[float, float], origin: EntitySnapshot, now: float) -> None:
        if self._hunt_goal is not None:
            self._hunt_goal_visits[self._hunt_goal] = now

        self._hunt_goal = goal
        self._hunt_path = _find_nav_path(origin.x, origin.y, goal[0], goal[1])
        self._hunt_path_index = 0
        self._hunt_goal_started_at = now
        self._hunt_last_progress_pos = (origin.x, origin.y)
        self._hunt_last_progress_at = now
        self._explore_angle = math.atan2(goal[1] - origin.y, goal[0] - origin.x)

    def _current_hunt_waypoint(self, origin: EntitySnapshot) -> tuple[float, float] | None:
        while self._hunt_path_index < len(self._hunt_path):
            waypoint = self._hunt_path[self._hunt_path_index]
            if _length(waypoint[0] - origin.x, waypoint[1] - origin.y) >= 70.0:
                return waypoint
            self._hunt_path_index += 1

        if self._hunt_goal is not None and not self._hunt_goal_reached(origin):
            return self._hunt_goal
        return None

    def _choose_hunt_goal(self, origin: EntitySnapshot, now: float) -> tuple[float, float]:
        candidates = list(dict.fromkeys(ARENA_MONSTER_SPAWNS + ARENA_PLAYER_SPAWNS + HUNT_PATROL_POINTS))
        best_goal: tuple[float, float] | None = None
        best_score = -INF

        for goal in candidates:
            if not _is_walkable_point(goal[0], goal[1]):
                continue
            dist = _length(goal[0] - origin.x, goal[1] - origin.y)
            if dist < 180.0:
                continue

            last_visit = self._hunt_goal_visits.get(goal, 0.0)
            revisit_score = 40.0 if last_visit <= 0.0 else _clamp((now - last_visit) / 20.0, 0.0, 1.0) * 40.0
            distance_score = _clamp(dist / 1100.0, 0.0, 1.0) * 25.0
            type_score = 25.0 if goal in ARENA_MONSTER_SPAWNS else 14.0 if goal in ARENA_PLAYER_SPAWNS else 8.0
            bot_spread = ((self.bot_id * 37 + int(goal[0] * 0.13) + int(goal[1] * 0.07)) % 17) * 0.5
            random_jitter = random.uniform(0.0, 8.0)
            same_goal_penalty = 35.0 if goal == self._hunt_goal else 0.0
            score = revisit_score + distance_score + type_score + bot_spread + random_jitter - same_goal_penalty

            if score > best_score:
                best_score = score
                best_goal = goal

        if best_goal is not None:
            return best_goal

        angle = math.atan2(-origin.y, -origin.x) + random.uniform(-1.1, 1.1)
        fallback = (
            _clamp(origin.x + math.cos(angle) * 520.0, MAP_MIN_X + 120.0, MAP_MAX_X - 120.0),
            _clamp(origin.y + math.sin(angle) * 520.0, MAP_MIN_Y + 120.0, MAP_MAX_Y - 120.0),
        )
        if _is_walkable_point(fallback[0], fallback[1]):
            return fallback
        cell = _nearest_walkable_nav_cell(fallback[0], fallback[1])
        return _nav_cell_center(cell)

    def _movement_for_target(
        self,
        origin: EntitySnapshot,
        target: EntitySnapshot,
        dist: float,
        now: float,
    ) -> tuple[float, float, bool]:
        dx = target.x - origin.x
        dy = target.y - origin.y
        toward_x, toward_y = _normalize(dx, dy)
        perp_x = -toward_y * self._strafe_dir
        perp_y = toward_x * self._strafe_dir

        if int(now * 0.45 + self.bot_id) % 2 == 0:
            self._strafe_dir = 1.0
        else:
            self._strafe_dir = -1.0

        if target.entity_type == EntityType.MONSTER:
            preferred_min = 260.0 + self.difficulty * 40.0
            preferred_max = 360.0 + self.difficulty * 80.0
            hard_close = MONSTER_FLEE_DISTANCE + 65.0
        else:
            preferred_min = 260.0 + self.difficulty * 45.0
            preferred_max = 460.0 + self.difficulty * 100.0
            hard_close = 210.0

        if dist < hard_close:
            return -toward_x + perp_x * 0.45, -toward_y + perp_y * 0.45, True
        if dist < preferred_min:
            return -toward_x * 0.85 + perp_x * 0.65, -toward_y * 0.85 + perp_y * 0.65, self.difficulty > 0.55
        if dist > preferred_max:
            sprint = dist > preferred_max + 220.0 and self.difficulty > 0.35
            return toward_x + perp_x * 0.16, toward_y + perp_y * 0.16, sprint

        radial_bias = 0.0
        midpoint = (preferred_min + preferred_max) * 0.5
        if dist < midpoint:
            radial_bias = -0.25
        elif dist > midpoint + 80.0:
            radial_bias = 0.20
        orbit_weight = 0.45 + self.difficulty * 0.25
        return (
            perp_x * orbit_weight + toward_x * radial_bias,
            perp_y * orbit_weight + toward_y * radial_bias,
            False,
        )

    def _accurate_shoot_range(self, target: EntitySnapshot) -> float:
        if target.entity_type == EntityType.MONSTER:
            return 520.0 + self.difficulty * 100.0
        return 580.0 + self.difficulty * 80.0

    def _predict_target_position(
        self,
        target: EntitySnapshot,
        projectile_speed: float = PROJECTILE_SPEED,
        origin: EntitySnapshot | None = None,
    ) -> tuple[float, float]:
        origin = origin or self._get_self_snapshot() or EntitySnapshot(
            -1, EntityType.PLAYER, self._pos_x, self._pos_y
        )
        rx = target.x - origin.x
        ry = target.y - origin.y
        tvx = target.vx
        tvy = target.vy
        a = tvx * tvx + tvy * tvy - projectile_speed * projectile_speed
        b = 2.0 * (rx * tvx + ry * tvy)
        c = rx * rx + ry * ry
        t = math.sqrt(c) / max(1.0, projectile_speed)

        if abs(a) < 0.0001:
            if abs(b) > 0.0001:
                linear_t = -c / b
                if linear_t > 0.0:
                    t = linear_t
        else:
            disc = b * b - 4.0 * a * c
            if disc >= 0.0:
                root = math.sqrt(disc)
                t1 = (-b - root) / (2.0 * a)
                t2 = (-b + root) / (2.0 * a)
                candidates = [candidate for candidate in (t1, t2) if candidate > 0.0]
                if candidates:
                    t = min(candidates)

        reaction_lead = (1.0 - self.difficulty) * 0.10
        t = _clamp(t + reaction_lead, 0.0, 2.2)
        return target.x + tvx * t, target.y + tvy * t

    def _difficulty_aim_error(self, distance: float) -> float:
        max_error = (1.0 - self.difficulty) * (0.18 + min(distance, PROJECTILE_MAX_DISTANCE) / PROJECTILE_MAX_DISTANCE * 0.16)
        if max_error <= 0.0001:
            return 0.0
        return random.gauss(0.0, max_error)

    def _best_projectile_dodge(self, origin: EntitySnapshot) -> tuple[float, float, float] | None:
        best: tuple[float, float, float] | None = None
        for projectile in self._entities.values():
            if projectile.entity_type != EntityType.PROJECTILE or not projectile.visible:
                continue
            dodge = self._projectile_dodge_vector(projectile, origin)
            if dodge is None:
                continue
            if best is None or dodge[2] > best[2]:
                best = dodge
        return best

    def _projectile_dodge_vector(
        self,
        projectile: EntitySnapshot,
        origin: EntitySnapshot | None = None,
    ) -> tuple[float, float, float] | None:
        origin = origin or self._get_self_snapshot() or EntitySnapshot(
            -1, EntityType.PLAYER, self._pos_x, self._pos_y
        )
        pvx = projectile.vx
        pvy = projectile.vy
        speed = _length(pvx, pvy)
        if speed < 20.0:
            return None

        rel_x = origin.x - projectile.x
        rel_y = origin.y - projectile.y
        closing = rel_x * pvx + rel_y * pvy
        if closing <= 0.0:
            return None

        time_to_closest = closing / (speed * speed)
        reaction_window = 0.45 + self.difficulty * 0.65
        if time_to_closest < -0.05 or time_to_closest > reaction_window:
            return None

        closest_x = projectile.x + pvx * time_to_closest
        closest_y = projectile.y + pvy * time_to_closest
        miss_distance = _length(origin.x - closest_x, origin.y - closest_y)
        danger_radius = PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 18.0 + self.difficulty * 22.0
        if miss_distance > danger_radius:
            return None

        perp_x = -pvy / speed
        perp_y = pvx / speed
        away_x = origin.x - closest_x
        away_y = origin.y - closest_y
        if _length(away_x, away_y) < 0.001:
            perp_x *= self._strafe_dir
            perp_y *= self._strafe_dir
        elif away_x * perp_x + away_y * perp_y < 0.0:
            perp_x *= -1.0
            perp_y *= -1.0

        urgency = _clamp(1.0 - (time_to_closest / max(0.001, reaction_window)), 0.0, 1.0)
        return perp_x, perp_y, urgency

    def _target_separation_vector(self, origin: EntitySnapshot) -> tuple[float, float]:
        sep_x = 0.0
        sep_y = 0.0
        for entity in self._entities.values():
            if entity.entity_id == self._entity_id or not entity.alive:
                continue
            if entity.entity_type not in (EntityType.PLAYER, EntityType.MONSTER):
                continue
            dx = origin.x - entity.x
            dy = origin.y - entity.y
            dist = _length(dx, dy)
            if 0.001 < dist < BOT_SEPARATION_DISTANCE:
                weight = (BOT_SEPARATION_DISTANCE - dist) / BOT_SEPARATION_DISTANCE
                sep_x += (dx / dist) * weight
                sep_y += (dy / dist) * weight
        return sep_x, sep_y

    def _exploration_direction(self, origin: EntitySnapshot, now: float) -> tuple[float, float]:
        if now >= self._explore_until:
            if abs(origin.x) > 760.0 or abs(origin.y) > 760.0:
                self._explore_angle = math.atan2(-origin.y, -origin.x) + random.uniform(-0.7, 0.7)
            else:
                self._explore_angle = random.uniform(-math.pi, math.pi)
            self._explore_until = now + random.uniform(1.2, 3.2)
        return math.cos(self._explore_angle), math.sin(self._explore_angle)

    def _steer_around_static_hazards(
        self,
        x: float,
        y: float,
        move_x: float,
        move_y: float,
    ) -> tuple[float, float]:
        move_x, move_y = _normalize(move_x, move_y)
        avoid_x = 0.0
        avoid_y = 0.0

        if x < MAP_MIN_X + BOT_BOUNDARY_AVOID_DISTANCE:
            avoid_x += (MAP_MIN_X + BOT_BOUNDARY_AVOID_DISTANCE - x) / BOT_BOUNDARY_AVOID_DISTANCE
        elif x > MAP_MAX_X - BOT_BOUNDARY_AVOID_DISTANCE:
            avoid_x -= (x - (MAP_MAX_X - BOT_BOUNDARY_AVOID_DISTANCE)) / BOT_BOUNDARY_AVOID_DISTANCE
        if y < MAP_MIN_Y + BOT_BOUNDARY_AVOID_DISTANCE:
            avoid_y += (MAP_MIN_Y + BOT_BOUNDARY_AVOID_DISTANCE - y) / BOT_BOUNDARY_AVOID_DISTANCE
        elif y > MAP_MAX_Y - BOT_BOUNDARY_AVOID_DISTANCE:
            avoid_y -= (y - (MAP_MAX_Y - BOT_BOUNDARY_AVOID_DISTANCE)) / BOT_BOUNDARY_AVOID_DISTANCE

        look_x = x + move_x * BOT_OBSTACLE_LOOKAHEAD
        look_y = y + move_y * BOT_OBSTACLE_LOOKAHEAD
        if circle_intersects_obstacle(look_x, look_y, PLAYER_HITBOX_RADIUS):
            best_x, best_y = -move_y, move_x
            best_clearance = -1.0
            for angle_offset in (math.pi / 4.0, -math.pi / 4.0, math.pi / 2.0, -math.pi / 2.0, math.pi):
                angle = math.atan2(move_y, move_x) + angle_offset
                cand_x = math.cos(angle)
                cand_y = math.sin(angle)
                probe_x = x + cand_x * BOT_OBSTACLE_LOOKAHEAD
                probe_y = y + cand_y * BOT_OBSTACLE_LOOKAHEAD
                clearance = 0.0 if circle_intersects_obstacle(probe_x, probe_y, PLAYER_HITBOX_RADIUS) else 1.0
                clearance += min(
                    _distance_point_to_segment(probe_x, probe_y, x, y, look_x, look_y) / BOT_OBSTACLE_LOOKAHEAD,
                    1.0,
                )
                if clearance > best_clearance:
                    best_clearance = clearance
                    best_x, best_y = cand_x, cand_y
            avoid_x += best_x * 1.2
            avoid_y += best_y * 1.2

        return _normalize(move_x + avoid_x, move_y + avoid_y)

    def _line_of_fire_clear(self, ax: float, ay: float, bx: float, by: float) -> bool:
        return not line_intersects_obstacle(ax, ay, bx, by)

    def _quantize_movement_direction(self, x: float, y: float, sprint: bool = False) -> tuple[float, float]:
        nx, ny = _normalize(x, y)
        if nx == 0.0 and ny == 0.0:
            return 0.0, 0.0

        speed = PLAYER_SPRINT_SPEED if sprint else PLAYER_SPEED
        threshold = 35.0 / speed
        qx = 0.0
        qy = 0.0
        if abs(nx) > threshold:
            qx = 1.0 if nx > 0.0 else -1.0
        if abs(ny) > threshold:
            qy = 1.0 if ny > 0.0 else -1.0
        return _normalize(qx, qy)

    def _project_fire_origin(
        self,
        origin: EntitySnapshot,
        move_x: float,
        move_y: float,
        sprint: bool,
        dt: float = BOT_INPUT_INTERVAL,
    ) -> tuple[float, float]:
        qx, qy = self._quantize_movement_direction(move_x, move_y, sprint)
        if qx == 0.0 and qy == 0.0:
            return origin.x, origin.y

        speed = PLAYER_SPRINT_SPEED if sprint else PLAYER_SPEED
        return move_with_obstacle_collision(
            origin.x,
            origin.y,
            origin.x + qx * speed * dt,
            origin.y + qy * speed * dt,
            PLAYER_HITBOX_RADIUS,
        )

    def _get_self_snapshot(self) -> EntitySnapshot | None:
        if self._entity_id is None:
            return None
        return self._entities.get(self._entity_id)

    def _set_velocity_from_direction(self, x: float, y: float, sprint: bool) -> None:
        x, y = self._quantize_movement_direction(x, y, sprint)
        if x == 0.0 and y == 0.0:
            self._vel_x = 0.0
            self._vel_y = 0.0
        else:
            speed = PLAYER_SPRINT_SPEED if sprint else PLAYER_SPEED
            self._vel_x = x * speed
            self._vel_y = y * speed
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
                self._latest_server_tick & 0xFFFF,
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

    def _allow_hit_report(self) -> bool:
        """Per-bot 1-second sliding-window cap, mirroring the server's
        LOCAL_HIT_REPORT_MAX_PER_SECOND = 20 so we never spam reports."""
        now = time.monotonic()
        if now - self._hit_report_window_start >= 1.0:
            self._hit_report_window_start = now
            self._hit_report_count = 0
        self._hit_report_count += 1
        return self._hit_report_count <= 20

    async def _send_local_hit_report(self, projectile_id: int):
        if self.ws is None:
            return
        try:
            pkt = build_local_hit_report(projectile_id)
            await self.ws.send(pkt)
            self.metrics.packets_sent += 1
            self.metrics.bytes_sent += len(pkt)
        except ConnectionClosed:
            self._running = False

    async def _detect_and_report_hits(self):
        """Client-side detection of incoming projectiles, mirroring the real client's
        LocalHitDetector: when a monster-owned projectile overlaps our position, report
        it so the server can apply monster damage. Only monster-owned bullets are PvE
        hits the server will honour, so we filter on ownership (learned from
        PROJECTILE_FIRED) before consuming hit-report quota — reporting player-fired
        bullets would still spend our local and the server's per-second quota on reports
        that can only be rejected, starving legitimate monster hits in combat/clustered
        runs. See docs/netcode/hit-authority-model.md."""
        if self.ws is None or self._entity_id is None or self._dead_since is not None:
            return

        hit_radius = PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS
        hit_radius_sq = hit_radius * hit_radius
        seen_projectiles: set[int] = set()

        for projectile in self._entities.values():
            if projectile.entity_type != EntityType.PROJECTILE or not projectile.visible:
                continue
            # Skip non-monster bullets: an unknown owner means we never saw the spawn
            # (can't claim a PvE hit), and a player owner would be rejected server-side.
            owner_id = self._projectile_sources.get(projectile.entity_id)
            if owner_id is None or owner_id < MONSTER_ENTITY_ID_START:
                continue
            seen_projectiles.add(projectile.entity_id)
            if projectile.entity_id in self._reported_projectile_ids:
                continue
            dx = projectile.x - self._pos_x
            dy = projectile.y - self._pos_y
            if dx * dx + dy * dy < hit_radius_sq and self._allow_hit_report():
                await self._send_local_hit_report(projectile.entity_id)
                self._reported_projectile_ids.add(projectile.entity_id)

        # Drop tracking for monster bullets that have despawned so the set stays bounded.
        self._reported_projectile_ids &= seen_projectiles

    def _handle_message(self, data: bytes):
        """Parse incoming binary packet(s) and update metrics."""
        offset = 0
        while offset + HEADER_SIZE <= len(data):
            msg_type, payload_len = struct.unpack_from("<BH", data, offset)
            packet_end = offset + HEADER_SIZE + payload_len
            if packet_end > len(data):
                logger.debug(
                    "Bot %d: Truncated packet type=%d payload_len=%d frame_len=%d offset=%d",
                    self.bot_id,
                    msg_type,
                    payload_len,
                    len(data),
                    offset,
                )
                return
            payload = data[offset + HEADER_SIZE:packet_end]
            self._handle_single_message(msg_type, payload)
            offset = packet_end

        if offset != len(data):
            logger.debug("Bot %d: Ignored %d trailing packet bytes", self.bot_id, len(data) - offset)

    def _handle_single_message(self, msg_type: int, payload: bytes):
        """Handle one decoded packet payload."""
        if msg_type == MessageType.BATCH:
            self._handle_batch_payload(payload)
            return

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
                self._latest_server_tick = header["server_tick"]
                self.metrics.server_ticks_seen.append(self._latest_server_tick)
            parsed = parse_state_update(payload, self._entities)
            if parsed:
                # Drop ownership entries for despawned projectiles so the map stays
                # bounded (mirrors the real client erasing _projectile_sources on
                # entity removal). Only delta packets carry explicit removals.
                for removed_id in parsed.get("removed", ()):
                    self._projectile_sources.pop(removed_id, None)
            if parsed and self._entity_id is not None:
                self_snapshot = self._entities.get(self._entity_id)
                if self_snapshot is not None:
                    self._pos_x = self_snapshot.x
                    self._pos_y = self_snapshot.y
                self._record_observations_for_assertions(parsed)

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

    def _handle_batch_payload(self, payload: bytes):
        """Unwrap a server BATCH packet: [u8 count][inner packets...]"""
        if not payload:
            self.metrics.decode_failures += 1
            return

        count = payload[0]
        offset = 1
        for index in range(count):
            if offset + HEADER_SIZE > len(payload):
                self.metrics.decode_failures += 1
                logger.debug("Bot %d: Truncated batch at packet %d/%d", self.bot_id, index, count)
                return
            msg_type, payload_len = struct.unpack_from("<BH", payload, offset)
            packet_end = offset + HEADER_SIZE + payload_len
            if packet_end > len(payload):
                self.metrics.decode_failures += 1
                logger.debug("Bot %d: Batch packet %d/%d overflows envelope", self.bot_id, index, count)
                return
            inner_payload = payload[offset + HEADER_SIZE:packet_end]
            self._handle_single_message(msg_type, inner_payload)
            offset = packet_end

    def _record_observations_for_assertions(self, parsed: dict):
        """Track per-entity observation distance + tick for §8.3 regression assertions.

        Cheap: appends one tuple per visible entity per state update, keyed by entity_id.
        Storage bounded by entity_observations_cap to avoid runaway memory in long runs.
        """
        entities = parsed.get("entities") or []
        if not entities:
            return
        own_id = self._entity_id
        my_x = self._pos_x
        my_y = self._pos_y
        observations = self.metrics.entity_observations
        max_seen = self.metrics.max_observed_entity_distance
        for snap in entities:
            entity_id = snap.entity_id
            if entity_id == own_id:
                continue
            dx = snap.x - my_x
            dy = snap.y - my_y
            distance = math.sqrt(dx * dx + dy * dy)
            if distance > max_seen:
                max_seen = distance
            log = observations.get(entity_id)
            if log is None:
                log = []
                observations[entity_id] = log
            # Cap per-entity history to keep memory bounded at long durations / stress runs.
            # 4096 samples × ~24 bytes/tuple × 100 entities ≈ ~10 MB worst case per bot.
            if len(log) < 4096:
                log.append((snap.last_seen_tick, distance))
        self.metrics.max_observed_entity_distance = max_seen

    def _handle_game_event(self, event: dict):
        if not event:
            return

        event_type = event.get("event_type")
        source_id = event.get("source_id", 0)
        target_id = event.get("target_id", 0)
        event_data = event.get("event_data", {})

        if event_type == GameEventType.PROJECTILE_FIRED:
            # source_id = owner entity id, target_id = projectile id. Record ownership
            # so _detect_and_report_hits reports only monster-owned bullets. Erased
            # when the projectile is removed (see _handle_single_message STATE_UPDATE).
            if target_id > 0:
                self._projectile_sources[target_id] = source_id
        elif event_type == GameEventType.PLAYER_INFO:
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
