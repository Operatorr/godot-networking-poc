# Lifecycle — connection, auth, spawn, death, respawn, disconnect, leaderboard, Go API surface

> Generated extraction notes for the Rust port — derived from GDScript at commit on branch
> feature/rust-port. Source of truth is the GDScript until cutover.

Commit at extraction: `9e661497a994dcdb2a0d07f73724604af7b01cc5`.

---

## 1. Overview

This document specifies the **server-side player lifecycle**:

```
TCP/WebSocket accept → peer_id assigned → ServerMain._on_client_connected
    → PlayerManager.add_player (entity_id assigned, spawn position chosen, PlayerState created, UNAUTHENTICATED)
→ client sends CONNECT_AUTH → ServerMain._handle_auth_request
    → authenticated=true, identity + color + bandwidth budget stored
    → PLAYER_INFO broadcast (new player to all; all existing players to new client)
    → leaderboard registration + leaderboard broadcast
→ per-tick input queueing / draining (PLAYER_INPUT)
→ death (HP→0 in collision stage) → DAMAGE + KILL/KILL_PVP events, respawn_timer = 3 s
→ client sends RESPAWN_REQUEST after timer → respawn at next round-robin spawn, 3 s invulnerability,
    RESPAWN event broadcast
→ disconnect (socket close or 5 s heartbeat timeout) → leaderboard removal + broadcast,
    PlayerState destroyed, per-peer caches destroyed
```

Plus three adjacent concerns owned by the same files:

- The **in-memory leaderboard** (PvP kills only, top-10, no persistence).
- The **only outbound HTTP call the game server makes today**: the region-status heartbeat
  (`POST /api/regions/heartbeat`, every 2 s).
- The **Go API surface the client uses for identity** (login / register / refresh / character),
  which defines the identity fields (`character_id`, `character_name`, …) that flow into
  `CONNECT_AUTH`. Per migration-spec **D9** the Rust server replaces the trust-the-client auth with
  Ed25519 ticket verification — the fields documented here are what the ticket must carry.

**Where it sits in the tick flow** (`server_main.gd:213-283`): connection/disconnection/auth/respawn
are **event-driven** (signal/message handlers that run between ticks, on the Godot main thread —
there is no concurrency). The per-tick parts of the lifecycle are: input drain + move acks (tick
step 1), invulnerability + respawn timer decrements and the 5 s leaderboard broadcast timer (tick
step 2 inside `_update_game_state`), and position-history recording (tick step 4). The region
heartbeat runs off the **frame** loop (`_process`), not the tick loop.

The current auth is explicitly **trust-the-client**: `server_main.gd:702` is
`# TODO: Validate character_id with API server`. The JWT in `CONNECT_AUTH` is never read by the
server.

---

## 2. Constants

### Server lifecycle constants

| Constant | Value | Unit | Source |
|---|---|---|---|
| `LEADERBOARD_BROADCAST_INTERVAL` | `5.0` | seconds | `client/scripts/server/server_main.gd:46` |
| `REGION_STATUS_HEARTBEAT_INTERVAL` | `2.0` | seconds | `client/scripts/server/server_main.gd:47` |
| `MIN_SNAPSHOT_FLOOR` | `256` | bytes | `client/scripts/server/server_main.gd:51` |
| `LOCAL_HIT_REPORT_MAX_PER_SECOND` | `20` | reports/s | `client/scripts/server/server_main.gd:760` |
| `LOCAL_HIT_VALIDATION_MARGIN` | `64.0` | world units | `client/scripts/server/server_main.gd:766` |
| `monster_spawn_rate` (export var) | `GameConstants.MONSTER_SPAWN_RATE * 2.0` = `0.4` | monsters/s | `client/scripts/server/server_main.gd:13` |
| `POSITION_HISTORY_TICKS` | `8` | ticks | `client/scripts/server/player_manager.gd:25` |
| `_next_entity_id` initial value | `1` | — | `client/scripts/server/player_manager.gd:28` |
| `_spawn_index` initial value | `0` | — | `client/scripts/server/player_manager.gd:31` |

### PlayerState constants / initial values

| Constant | Value | Unit | Source |
|---|---|---|---|
| `STALE_INPUT_TICK_LIMIT` | `6` | ticks | `client/scripts/server/player_state.gd:80` |
| `MAX_INPUT_QUEUE_SIZE` | `10` | inputs | `client/scripts/server/player_state.gd:106` |
| `health` / `max_health` initial | `100` / `100` | HP (int) | `client/scripts/server/player_state.gd:58-59` |
| default `player_color` | `Color(0.27, 0.53, 1.0)` (alpha 1.0) | RGBA floats | `client/scripts/server/player_state.gd:15` |
| initial `entity_flags` | `ENTITY_FLAG_ALIVE \| ENTITY_FLAG_VISIBLE` = `33` | bitfield | `client/scripts/server/player_state.gd:74` |
| initial `animation_state` | `IDLE` = `0` | enum | `client/scripts/server/player_state.gd:73` |
| `last_killer_id` initial / sentinel | `-1` | entity id | `client/scripts/server/player_state.gd:70` |

### GameConstants used by this subsystem

| Constant | Value | Unit | Source (`client/scripts/shared/game_constants.gd`) |
|---|---|---|---|
| `SERVER_TICK_RATE` | `30.0` | Hz | :22 |
| `SHOOT_COOLDOWN` | `0.3` | seconds | :364 |
| `RESPAWN_DELAY` | `3.0` | seconds | :367 |
| `INVULNERABILITY_DURATION` | `3.0` | seconds | :370 |
| `PLAYER_PROJECTILE_DAMAGE` | `25` | HP | :439 |
| `MONSTER_PROJECTILE_DAMAGE` | `10` | HP | :436 |
| `PLAYER_KNOCKBACK_BASE_FORCE` | `450.0` | units/s impulse | :96 |
| `MONSTER_ENTITY_ID_START` | `30000` | entity id | :386 |
| `PROJECTILE_ENTITY_ID_START` / `_END` | `10000` / `29999` | entity id | :339-340 |
| `MAP_MIN` / `MAP_MAX` | `(-1000.0,-1000.0)` / `(1000.0,1000.0)` | world units | :177-180 |
| `PLAYER_HITBOX_RADIUS` | `16.0` | world units | :343 |
| `PROJECTILE_RADIUS` | `8.0` | world units | :335 |
| `ARENA_PLAYER_SPAWNS` | 10 positions, **in this order**: `(-800,-800)`, `(0,-800)`, `(800,-800)`, `(-800,0)`, `(800,0)`, `(-800,800)`, `(0,800)`, `(800,800)`, `(-450,450)`, `(450,-450)` | world units | :199-210 |

### ServerConfig defaults (JSON file / env can override; getters re-read the dict)

| Key | Default | Notes | Source (`client/scripts/server/server_config.gd`) |
|---|---|---|---|
| `port` | `8081` | game-server listen port | :8 |
| `tick_rate` | `int(GameConstants.SERVER_TICK_RATE)` = `30` | Hz; env `GAME_SERVER_TICK_RATE` overrides (highest precedence, :160-164) | :13 |
| `max_players` | `100` | capacity check at connect | :14 |
| `region` | `"local"` | sent in region heartbeat | :15 |
| `debug_logging` | `true` | | :16 |
| `heartbeat_timeout_seconds` | `5.0` | **DEAD CONFIG** — no caller (see §6) | :17 |
| `api_server_url` | `"http://localhost:8080"` | region heartbeat target; empty string disables the publisher | :18 |
| `snapshot_rate_hz` | `0` → resolves to `tick_rate`; raw value clamped to `min(raw, tick_rate)` when > 0 | :33, getter :102-107 |
| `max_snapshot_bytes` | `1200` | getter clamps to `>= 0` | :37, :109-110 |
| `default_client_bandwidth_bps` | `120000` | bytes/s | :43 |
| `max_client_bandwidth_bps` | `200000` | bytes/s, hard cap | :45 |
| `min_client_bandwidth_bps` | `24000` | bytes/s, floor | :47 |

Config file precedence: `user://server_config.json` > `res://data/config/server_config.json` >
`DEFAULTS`; unknown keys are warned and ignored (`server_config.gd:129-194`). Env override applies
after whichever file loads.

### NetworkManager / transport constants relevant to lifecycle

| Constant | Value | Unit | Source (`client/autoload/network_manager.gd`) |
|---|---|---|---|
| `server_heartbeat_timeout` | `5.0` | seconds | :65 |
| `heartbeat_interval` (client send) | `1.0` | seconds | :108 |
| `DEFAULT_CLIENT_BUDGET` (client advert) | `120000` | bytes/s | :85 |
| peer_id assignment | `randi()` (random u32) per accepted socket | — | `client/autoload/transport/websocket_transport.gd:65` |

### Client-side (AuthManager / GameManager / EntityNameCache)

| Constant | Value | Source |
|---|---|---|
| `api_base_url` default | `"http://localhost:8080"` (overridden by ClientConfig) | `client/autoload/auth_manager.gd:25` |
| `api_timeout` default | `10.0` s | `client/autoload/auth_manager.gd:26` |
| token refresh lead time | `300` s before `token_expiry` (only if `token_expiry > 0`) | `client/autoload/auth_manager.gd:73` |
| token save path | `user://auth_token.dat` (JSON) | `client/autoload/auth_manager.gd:358` |
| `player_data.selected_region` default | `"Asia"` | `client/autoload/game_manager.gd:28` |
| `player_data.player_color` default | `Color(0.27, 0.53, 1.0)` | `client/autoload/game_manager.gd:30` |
| `local_player_entity_id` sentinel | `-1` (unset) | `client/autoload/game_manager.gd:55` |
| EntityNameCache fallback name | `"Player_%d" % entity_id` | `client/autoload/entity_name_cache.gd:72` |
| EntityNameCache fallback color | `Color(0.27, 0.53, 1.0)` | `client/autoload/entity_name_cache.gd:79` |

### Go API constants

| Constant | Value | Source |
|---|---|---|
| `regionRuntimeStatusTTL` (Redis TTL of a heartbeat) | `5 * time.Second` | `api/internal/handlers/region.go:24` |
| `regionProbeTimeout` (TCP reachability probe) | `500 * time.Millisecond` | `api/internal/handlers/region.go:23` |
| heartbeat auth env var | `REGION_HEARTBEAT_TOKEN` (both sides; empty = no auth) | `region.go:99`, `server_main.gd:892` |

### Enums (wire values — must match exactly)

`PacketTypes.GameEventType` (`client/scripts/shared/networking/packet_types.gd:96-109`):
`DAMAGE=1, KILL=2, RESPAWN=3, EFFECT_APPLY=4, EFFECT_REMOVE=5, PICKUP=6, LEVEL_UP=7,
CHAT_MESSAGE=8, PLAYER_INFO=9, KILL_PVP=10, LEADERBOARD_UPDATE=11, PROJECTILE_FIRED=12`.

`PacketTypes.DisconnectReason` (`packet_types.gd:112-119`):
`USER_QUIT=0, TIMEOUT=1, KICKED=2, SERVER_SHUTDOWN=3, INVALID_AUTH=4, DUPLICATE_SESSION=5`.

`PlayerState.PlayerLifeState` (`player_state.gd:8`): `ALIVE=0, DEAD=1, INVULNERABLE=2`.

`AuthPacket.Region` (`client/scripts/shared/networking/packets/auth_packet.gd:13-18`):
`ASIA=0, EUROPE=1, US_WEST=2, US_EAST=3`.

`PacketTypes.AnimationState`: `IDLE=0, WALK=1, RUN=2, ATTACK=3, HIT=4, DEATH=5, SPAWN=6`.

Entity flag bits (`packet_types.gd:67-74`): `ALIVE=1, MOVING=2, ATTACKING=4, INVULNERABLE=8,
STUNNED=16, VISIBLE=32, DASHING=64, KNOCKED_BACK=128`.

---

## 3. Data structures

### PlayerManager (`player_manager.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `players` | map `peer_id:int → PlayerState` | empty | the only player registry |
| `_position_history` | map `server_tick:int → Array<PlayerPositionSnapshot>` | empty | only **authenticated AND alive** players are recorded |
| `_position_history_ticks` | ordered list of recorded ticks | empty | FIFO, max length 8 |
| `_next_entity_id` | int | `1` | monotonically increasing, **never reset, never recycled** (not even by `clear_all`) |
| `_spawn_index` | int | `0` | round-robin cursor over valid spawns, **never reset**; shared by connect-spawn and respawn |
| `debug_logging` | bool | `true` | overwritten from config at boot |

`PlayerPositionSnapshot` (`player_manager.gd:8-16`): `{ entity_id: int = 0, position: Vector2 = (0,0) }`.

### PlayerState (`player_state.gd`) — full field list

| Field | Type | Initial | Valid range / notes |
|---|---|---|---|
| `entity_id` | int | 0 → set at create | intended 1–999 (see hazard §6.1) |
| `peer_id` | int | 0 → set at create | random u32 from transport |
| `character_id` | String | `""` | set at auth; opaque (Go DB int serialized as string client-side) |
| `character_name` | String | `""` | set at auth; may legitimately be `""` |
| `player_color` | Color | `(0.27, 0.53, 1.0, 1.0)` | set at auth; RGB quantized to u8 on the wire |
| `bandwidth_budget_bps` | int | `0` | set at auth to the clamped effective budget |
| `max_snapshot_bytes` | int | `0` | set at auth; 0 = "use service default" |
| `connected_at` | float | `Time.get_ticks_msec()/1000.0` at create | seconds since engine start |
| `authenticated` | bool | `false` | flipped only by `authenticate_player` (never back to false) |
| `last_heartbeat` | float | = `connected_at` | **dead field** — `update_heartbeat` has no caller |
| `position` | Vector2 | spawn position | clamped to map bounds by movement |
| `velocity` | Vector2 | `(0,0)` | recomputed each tick |
| `aim_angle` | float | `0.0` | radians |
| `movement_sm` | MovementStateMachine | fresh instance | see movement extraction doc |
| `input_flags` | int | `0` | u16 bitfield, persists between inputs |
| `last_input_sequence` | int | `0` | echoed in move acks |
| `last_client_render_tick` | int | `0` | u16 from input stream |
| `last_client_rtt_ms` | int | `0` | clamped 0..65535 at use sites |
| `last_client_position` | Vector2 | `(0,0)` | only meaningful when `has_client_position` |
| `has_client_position` | bool | `false` | reset on respawn |
| `last_input_received_tick` | int | `0` | 0 = "never received" sentinel (stale-input check skipped) |
| `pending_shots` | Array<Dictionary> | empty | rising-edge SHOOT queue |
| `_pending_dash` | bool | `false` | latched dash request |
| `input_queue` | Array<Dictionary> | empty | max 10, drop-oldest on overflow |
| `health` / `max_health` | int | `100` / `100` | health clamped ≥ 0 on damage |
| `is_alive` | bool | `true` | |
| `shoot_cooldown` | float | `0.0` | seconds remaining |
| `life_state` | PlayerLifeState | `ALIVE` | |
| `invulnerability_timer` | float | `0.0` | seconds remaining; can go negative transiently before reset |
| `respawn_timer` | float | `0.0` | seconds remaining; clamped ≥ 0 |
| `pvp_kills` / `monster_kills` / `deaths` | int | `0` | per-session counters on the state (separate from leaderboard entries) |
| `last_killer_id` | int | `-1` | entity id of last killer; `-1` = none |
| `animation_state` | int | `IDLE` (0) | |
| `entity_flags` | int | `33` (ALIVE\|VISIBLE) | |

### LeaderboardManager (`leaderboard_manager.gd`)

| Field | Type | Initial |
|---|---|---|
| `_entries` | map `entity_id:int → LeaderboardEntry` | empty |
| `_top_entries` | Array<LeaderboardEntry> (sorted cache) | empty |

`LeaderboardEntry`: `{ entity_id: int, pvp_kills: int = 0, deaths: int = 0 }`. **`deaths` is
tracked but never serialized** (only `entity_id` + `pvp_kills` go on the wire).

### ServerMain lifecycle state (`server_main.gd`)

| Field | Type | Initial |
|---|---|---|
| `server_running` | bool | false → true at init |
| `server_time` | float | `0.0` (accumulated frame delta) |
| `tick_count` | int | `0`, incremented at top of every tick |
| `leaderboard_timer` | float | `0.0` (accumulates `tick_interval` per tick) |
| `region_status_timer` | float | `0.0` (accumulates frame delta) |
| `region_status_request_in_flight` | bool | `false` |
| `region_status_warning_logged` | bool | `false` (one-shot warning latch, reset on success) |
| `_local_hit_report_window` | map `peer_id → {start_ms:int, count:int}` | empty |

### GameManager client state (`game_manager.gd`) — identity fields that feed CONNECT_AUTH

`player_data: Dictionary` initial:
`{"character_name": "", "character_id": "", "user_id": "", "selected_region": "Asia",
"session_id": "", "player_color": Color(0.27,0.53,1.0)}` (`game_manager.gd:24-31`).
`clear_player_data()` resets all except `selected_region` and `player_color`
(`game_manager.gd:233-243`). `is_authenticated()` = `user_id != "" AND character_id != ""`;
`has_character()` = `character_name != ""`.

### EntityNameCache client state (`entity_name_cache.gd`)

`entity_names: map entity_id → String`, `entity_colors: map entity_id → Color`. Populated from
`GAME_EVENT`/`PLAYER_INFO` only when `entity_id > 0` **and** `character_name != ""`
(`entity_name_cache.gd:50`). `set_entity_color` forces alpha to `1.0` (`:63`). Entries are
never auto-evicted on player disconnect (no removal hook is wired).

---

## 4. Algorithms

All pseudocode preserves exact order of operations. `tick_interval = 1.0 / config.tick_rate`
(float division, computed fresh at each use).

### 4.1 Connection accept — `_on_client_connected(peer_id)` (`server_main.gd:609-629`)

Triggered by the `server_client_connected` signal, which NetworkManager emits the first time a
WebSocket peer reaches OPEN (`network_manager.gd:205-211`). `peer_id` is a **random u32**
(`randi()`, `websocket_transport.gd:65`) — it has no relation to entity_id.

```
on client_connected(peer_id):
    if player_manager.player_count >= config.max_players:        # count includes UNauthenticated players
        log "Server full"
        network.disconnect_client(peer_id, "Server full")        # raw socket close, NO Disconnect packet
        return
    state = player_manager.add_player(peer_id)
    if state == null: log-and-return                             # cannot happen in practice
    broadcast_service.get_or_create_delta_cache(peer_id)         # delta cache exists from connect, pre-auth
```

`PlayerManager.add_player(peer_id)` (`player_manager.gd:38-55`):

```
if players contains peer_id: return players[peer_id]             # idempotent re-entry
entity_id = _next_entity_id; _next_entity_id += 1                # NO upper bound, NO recycling
spawn_pos = _get_spawn_position()                                # round-robin (4.2) — consumed even though
                                                                 # the player is not yet authenticated
state = PlayerState.create(peer_id, entity_id, spawn_pos)        # authenticated=false, hp=100, ALIVE
players[peer_id] = state
return state
```

The new player is **invisible to the sim** until authenticated: input is rejected
(`player_manager.gd:105-108`), `process_all_inputs` skips them (`:122-123`),
broadcasts iterate `get_authenticated_players()` only, and position snapshots skip them
(`:261`). But they **do** count toward `max_players` and they **do** receive broadcasts?
— No: broadcasts are per-authenticated-player loops, so an unauthenticated peer receives
nothing except direct replies. They appear in `get_all_players()` (used only by shutdown,
invuln timers, and the shoot pass — all no-ops for them).

### 4.2 Spawn position selection — `_get_spawn_position()` (`player_manager.gd:213-221`)

```
spawn_points = GameConstants.get_valid_player_spawns()
    # filters ARENA_PLAYER_SPAWNS (10 fixed points, order as listed in §2) keeping points where
    # the 16.0-radius circle is fully inside [-1000,1000]^2 AND does not intersect any
    # radius-expanded obstacle rect (game_constants.gd:295-312). With the current arena layout
    # all 10 pass; the filter is a guardrail and runs on EVERY call.
if spawn_points empty:
    warn; return clamp_to_bounds((0,0))                          # = (0,0)
pos = spawn_points[_spawn_index % spawn_points.size()]
_spawn_index = (_spawn_index + 1) % spawn_points.size()
return pos
```

One shared cursor for both connect-spawns and respawns; consumed in arrival/respawn order.

### 4.3 CONNECT_AUTH — `_handle_auth_request(peer_id, data)` (`server_main.gd:685-733`)

Routed from `_on_client_message` (`server_main.gd:653-681`), which **drops any message whose
peer has no PlayerState** (`:654`). The `data` dictionary is `AuthPacket.to_dict()` of the decoded
binary packet (`network_manager.gd:994-996`), i.e. keys:
`type ("CONNECT_AUTH"), token, character_id, character_name, region (int), region_name,
player_color (Color), bandwidth_budget_bps (int)`.
**Note:** `to_dict()` truncates tokens longer than 20 chars to `first20 + "..."`
(`auth_packet.gd:133`) — harmless today because the server never reads `token`.

CONNECT_AUTH wire payload (client→server, `auth_packet.gd:76-85` / live encode path
`network_manager.gd:848-856` — byte-identical):
`[u16 len + utf8 token][u16 len + utf8 character_id][u16 len + utf8 character_name]
[u8 region][u8 r][u8 g][u8 b][u32 bandwidth_budget_bps]`. Color and budget are trailing and
length-gated on read (old clients may omit; then defaults apply: color `(0.27,0.53,1.0)`,
budget `0`).

```
handle_auth_request(peer_id, data):
    character_id   = data.get("character_id", "")
    character_name = data.get("character_name", "Player_<peer_id>")
        # default fires ONLY when the key is absent; the binary path always provides the key,
        # so an empty client name stays "" (it is NOT replaced)
    player_color   = data.get("player_color", Color(0.27,0.53,1.0))

    advertised = int(data.get("bandwidth_budget_bps", 0))
    effective_budget = advertised if advertised > 0 else config.default_client_bandwidth_bps  # 120000
    effective_budget = clamp(effective_budget, config.min_client_bandwidth_bps,               # 24000
                                               config.max_client_bandwidth_bps)               # 200000

    # TODO at server_main.gd:702: Validate character_id with API server  ← trust-the-client today
    ok = player_manager.authenticate_player(peer_id, character_id, character_name,
                                            player_color, effective_budget)
    if not ok: return            # only fails when peer unknown; client gets NO nack of any kind

    rate = config.snapshot_rate_hz                       # 30 with defaults
    per_peer_bytes = int(effective_budget / float(max(1, rate)))   # float div then trunc toward 0
    per_peer_bytes = clamp(per_peer_bytes, MIN_SNAPSHOT_FLOOR=256, config.max_snapshot_bytes=1200)
        # defaults: 120000/30 = 4000 → clamped to 1200
    broadcast_service.set_peer_byte_budget(peer_id, per_peer_bytes)    # stored as max(0, bytes)
    state.max_snapshot_bytes = per_peer_bytes            # (re-fetches state; only if still present)

    broadcast_service.broadcast_player_info(peer_id, ...)            # 4.4 — to ALL clients
    broadcast_service.send_all_player_info_to_client(peer_id, ...)   # 4.4 — existing players to the newcomer
    if leaderboard_manager and state:
        leaderboard_manager.register_player(state.entity_id)          # creates 0-kill entry, rebuilds sort
        broadcast_service.broadcast_leaderboard(...)                  # immediate LEADERBOARD_UPDATE to all
```

`authenticate_player` (`player_manager.gd:166-188`): sets `authenticated = true`,
`character_id`, `character_name`, `player_color`, `bandwidth_budget_bps`. Returns `false` only if
the peer has no PlayerState. **There is no auth-success packet** — the client infers success by
receiving its own PLAYER_INFO. **Re-sending CONNECT_AUTH is not guarded**: a second auth from the
same peer overwrites identity and re-fires all the broadcasts.

### 4.4 PLAYER_INFO flow

Server → all clients on auth (`server_broadcast_service.gd:397-415`):
`GameEventPacket.create_player_info(entity_id, character_name, position, player_color)` →
`GAME_EVENT { event_type=9, source_id=0, target_id=entity_id,
event_data={character_name, position, player_color} }` broadcast to every connected peer.

Server → the new client only (`server_broadcast_service.gd:419-440`): one PLAYER_INFO per
**authenticated** player, **skipping the newcomer itself** (`state.peer_id == peer_id`
continue) — the newcomer's own PLAYER_INFO arrives via the broadcast above.

Recovery path: `REQUEST_FULL_STATE` re-sends PLAYER_INFO for **every authenticated player
including the requester** after the baseline state packet
(`server_broadcast_service.gd:348-359`). This is how a client that missed the original broadcast
(listener not yet bound) re-discovers its own entity_id.

Client consumption:

- `EntityNameCache._on_server_message` (`entity_name_cache.gd:38-53`): on
  `GAME_EVENT` (message_type literal `3`) with `event_type == PLAYER_INFO`, caches name+color iff
  `entity_id > 0 and character_name != ""`.
- `ArenaBase._handle_player_info` (`arena_base.gd:385-419`): caches color, then **identifies the
  local player by string equality** `char_name == GameManager.player_data["character_name"]`
  (`:396`) and `entity_id > 0` → `GameManager.set_local_player_entity_id(entity_id)`, then
  force-syncs prediction to the PLAYER_INFO `position` (the server-chosen spawn) exactly once per
  arena session.

PLAYER_INFO wire payload (`game_event_packet.gd:173-176`):
`[u8 9][u16 source_id=0][u16 target_id=entity_id][u16 len + utf8 name]
[s16 x*10][s16 y*10][u8 r][u8 g][u8 b]`. On read, color is length-gated: absent → default
`(0.27,0.53,1.0)` (`:236`).

### 4.5 Input queueing (lifecycle view)

`PLAYER_INPUT` → `player_manager.queue_player_input(peer_id, data)` (`player_manager.gd:99-110`):
drop if peer unknown; drop if `not authenticated`; else `state.queue_input(input)`.

`PlayerState.queue_input` (`player_state.gd:109-114`): if `input_queue.size() >= 10`, pop the
**oldest** (front) and log, then append.

Per tick, `process_all_inputs(delta, server_tick)` (`player_manager.gd:118-148`):

```
move_results = []
for each state in players.values():            # iteration order = Godot Dictionary insertion order;
    if not state.authenticated: continue       #   results must not depend on it
    had_input = state.has_queued_input()
    while state.has_queued_input():
        state.ingest_input(state.pop_input(), server_tick)   # FIFO drain; SHOOT rising edges queue
                                                             # into pending_shots; DASH latches; dead
                                                             # players discard inputs entirely
    validation = state.step(delta, server_tick)              # exactly ONE tick of movement (see
                                                             # movement extraction doc for the math)
    if had_input:
        move_results.append({ peer_id, sequence: validation.sequence,
                              position: validation.server_position,
                              success: not validation.correction_needed,
                              cheat_detected, deviation,
                              stamina: roundi(state.movement_sm.stamina),
                              mana:    roundi(state.movement_sm.mana) })
return move_results
```

ServerMain then sends one `ACTION_CONFIRM` per result via
`ActionConfirmPacket.create_move_confirm(sequence, position, tick_count, success, stamina, mana)`
(`server_main.gd:326-364`); a cheat detection only logs — **no kick, no penalty**.

Lifecycle-relevant pieces of `ingest_input` / `step` (`player_state.gd:147-289`):

- `ingest_input` **early-returns when `life_state == DEAD`** — dead players' inputs are discarded
  before they can touch flags or pending_shots (`:148-150`).
- `step` clears `input_flags` to 0 when
  `last_input_received_tick > 0 AND server_tick - last_input_received_tick > 6`
  (stale-input timeout, `:220-221`) so a silent/disconnecting client stops sliding.
- Dead players in `step`: velocity zeroed, flags cleared, `_pending_dash=false`, entity flags
  recomputed, returns a valid no-correction result carrying `last_input_sequence` (`:224-236`).
- An INVULNERABLE player ends invulnerability when any move/shoot input is held (`:243-244`)
  or when a shot attempt is processed (`server_main.gd:369-370`, **before** the cooldown check).

### 4.6 Death — damage application path

Death only happens inside the collision stage (tick step 5) or the validated client hit-report
path; both funnel through `ServerCollisionHandler.apply_player_hit`
(`server_collision_handler.gd:42-90`):

```
apply_player_hit(owner_id, target_id, ..., impact_position = Vector2.INF):
    target = player_manager.get_player_by_entity_id(target_id)    # linear scan over players
    if target == null or not target.authenticated: return
    damage = 25 (PLAYER_PROJECTILE_DAMAGE)
    if owner_id >= 30000 (MONSTER_ENTITY_ID_START): damage = 10 (MONSTER_PROJECTILE_DAMAGE)
    previous_health = target.health
    killed = target.take_damage(damage, owner_id)
    damage_applied = previous_health - target.health
    if damage_applied <= 0: return                                # invulnerable/dead → NO event at all
    if not killed and impact_position.is_finite():
        knock_dir = target.position - impact_position
        if knock_dir.length() > 0.01:
            target.movement_sm.apply_knockback(knock_dir, 450.0)
    broadcast GAME_EVENT DAMAGE { source_id=owner_id, target_id, amount=damage_applied, damage_type=0 }
    if killed: _broadcast_player_kill(owner_id, target_id, ...)
```

`PlayerState.take_damage(amount, source_id=-1)` (`player_state.gd:407-422`):

```
if not is_alive or amount <= 0: return false
if life_state == INVULNERABLE: return false
health = max(0, health - amount)          # integer math
if health <= 0: _mark_dead(source_id); return true
animation_state = HIT
return false
```

`_mark_dead(killer_id)` (`player_state.gd:426-444`) — runs **exactly once** (guard on already
DEAD):

```
is_alive = false; life_state = DEAD; health = 0; velocity = (0,0)
movement_sm.reset(); input_flags = 0; input_queue.clear(); pending_shots.clear()
_pending_dash = false; shoot_cooldown = 0.0
respawn_timer = RESPAWN_DELAY (3.0)
deaths += 1; last_killer_id = killer_id
animation_state = DEATH (5)
_update_entity_flags()        # → entity_flags = VISIBLE only (32): dead players keep replicating
```

Kill broadcast — `_broadcast_player_kill(killer_id, victim_id, ...)`
(`server_collision_handler.gd:147-183`):

```
if killer_id < 30000:                                  # player-vs-player branch
    if killer_id == victim_id: return                  # suicide: NO event, NO stats (cannot happen
                                                       #   today: own projectile can't hit owner)
    killer = get_player_by_entity_id(killer_id)        # may be null (disconnected after firing)
    if killer != null and not killer.authenticated: return    # unauthenticated killer suppresses event
    broadcast GAME_EVENT KILL_PVP { source_id=killer_id, target_id=victim_id }   # even if killer null
    if killer == null: return                          # no stats/leaderboard for disconnected killer
    killer.pvp_kills += 1
    leaderboard.record_pvp_kill(killer_id, victim_id)  # 4.10
    broadcast_leaderboard(...)                          # immediate push, on top of the 5 s cadence
else:                                                  # monster killed the player
    broadcast GAME_EVENT KILL { source_id=monster_id, target_id=victim_id }
    # NOTE: no leaderboard deaths increment for monster kills (deaths only counted in
    # record_pvp_kill), and PlayerState.deaths was already incremented in _mark_dead.
```

### 4.7 Respawn timers — per tick (`server_main.gd:603-606`, `player_state.gd:448-453`)

Tick step 2 (`_update_game_state`) calls for **authenticated** players only:

```
update_respawn_timer(delta):                # delta = tick_interval
    if life_state != DEAD: return false
    respawn_timer = max(0.0, respawn_timer - delta)
    return respawn_timer <= 0.0             # return value DISCARDED by ServerMain —
                                            # the server NEVER auto-respawns
```

Invulnerability decrement runs the same tick step for **all** players
(`server_main.gd:597-599`, `player_state.gd:457-465`):

```
update_invulnerability(delta):
    if life_state != INVULNERABLE: return false
    invulnerability_timer -= delta          # no clamp; may pass below 0 before the check
    if invulnerability_timer <= 0.0: end_invulnerability(); return true
    return false

end_invulnerability():                      # player_state.gd:469-474
    if life_state != INVULNERABLE: return
    life_state = ALIVE; invulnerability_timer = 0.0
    entity_flags &= ~ENTITY_FLAG_INVULNERABLE
```

### 4.8 RESPAWN_REQUEST — `_handle_respawn_request(peer_id)` (`server_main.gd:737-756`)

Client sends `RESPAWN_REQUEST` (payload: `[u32 timestamp_ms]`, ignored by the server) from its
death-screen flow (`arena_base.gd:799-800`).

```
state = get_player(peer_id);  if null: return
if state.is_alive: return                       # reject: still alive
if state.respawn_timer > 0.0: return            # reject: timer not expired (silent — no nack)
_respawn_player_and_broadcast(peer_id)
```

`_respawn_player_and_broadcast` (`server_main.gd:840-864`):

```
state = get_player(peer_id); if null: return false
ok = player_manager.respawn_player(peer_id)     # picks NEXT round-robin spawn (4.2), then
                                                # state.reset_for_respawn(spawn_pos)
if not ok: return false
if network == null: return true
broadcast GAME_EVENT RESPAWN { source_id=0, target_id=state.entity_id,
                               event_data={position: state.position} }
return true
```

`reset_for_respawn(spawn_position)` (`player_state.gd:384-402`) — exact field resets:

```
position = spawn_position; velocity = (0,0)
health = max_health; is_alive = true
life_state = INVULNERABLE; invulnerability_timer = 3.0
movement_sm.reset()
respawn_timer = 0.0; shoot_cooldown = 0.0
input_flags = 0; input_queue.clear(); pending_shots.clear(); _pending_dash = false
has_client_position = false
last_input_received_tick = 0                 # re-arms the "first tick after connect" stale exemption
last_killer_id = -1
animation_state = SPAWN (6)
entity_flags = ALIVE|VISIBLE|INVULNERABLE (= 41)
```

Identity (`character_id`, name, color, budget), counters (`pvp_kills`, `monster_kills`,
`deaths`), `entity_id`, and `authenticated` all **survive** respawn. Per ADR 0005 this whole
respawn flow is **POC-only**: the target model is permadeath (death deletes the character at the
API); the Rust port keeps respawn until the persistence milestone (M3) replaces it.

### 4.9 Disconnect cleanup — `_on_client_disconnected(peer_id)` (`server_main.gd:633-649`)

Fired when the transport reports a closed socket (`network_manager.gd:214-222`) or when the
NetworkManager-level heartbeat watchdog trips (`network_manager.gd:224-230, 673-685`: a peer is
dropped when `now - peer_last_heartbeat[peer] > 5.0 s`; `peer_last_heartbeat` is refreshed by
every HEARTBEAT packet). Signal only fires for peers that had been announced as connected.

```
on client_disconnected(peer_id):
    state = player_manager.get_player(peer_id)              # may be null (e.g. "Server full" close)
    if leaderboard_manager and state:
        leaderboard_manager.remove_player(state.entity_id)  # BEFORE remove_player (needs entity_id)
        broadcast_leaderboard(...)                          # immediate update to remaining clients
    player_manager.remove_player(peer_id)                   # erases PlayerState; no event broadcast
    _local_hit_report_window.erase(peer_id)
    broadcast_service.remove_delta_cache(peer_id)           # erases delta cache, visible-entity set,
                                                            # snapshot scheduler, per-peer byte budget
```

There is **no GAME_EVENT for "player left"**. Remote clients learn of the departure via the
delta stream: the entity stops appearing in snapshots, so each remaining client's delta cache
emits a `DELTA_MASK_REMOVED` despawn for it (stale-entity cleanup in the broadcast subsystem).
Note `_position_history` is **not** purged: snapshots from the last ≤8 ticks still contain the
departed entity until the window rolls past them.

### 4.10 Leaderboard (`leaderboard_manager.gd`)

```
register_player(entity_id):                 # :63-67  (called at auth)
    if entity_id <= 0: return
    find_or_create entry; rebuild sorted cache

remove_player(entity_id):                   # :71-73  (called at disconnect)
    erase entry; rebuild sorted cache       # kills are FORGOTTEN on disconnect (in-memory only)

record_pvp_kill(killer_id, victim_id):      # :29-46  (called on PvP kill)
    if killer_id <= 0 or victim_id <= 0 or killer_id == victim_id: return top10
    killer_entry = find_or_create(killer_id); killer_entry.pvp_kills += 1
    victim_entry = find_or_create(victim_id); victim_entry.deaths += 1
    rebuild sorted cache; return top10

get_top_n(count):                           # :50-59
    first min(count, len) of sorted cache as [{entity_id, pvp_kills}]

sort order (rebuild, :102-108): pvp_kills DESC; ties broken by entity_id ASC.
    Comparator is a strict total order (entity ids unique) → deterministic regardless of
    sort stability.
```

Broadcast cadence: every 5.0 s of tick-time (`leaderboard_timer` accumulates `tick_interval`
per tick and resets to `0.0` on fire — `server_main.gd:510-513`), plus immediate broadcasts on
auth, on disconnect, and on every PvP kill. `broadcast_leaderboard`
(`server_broadcast_service.gd:366-393`) sends
`GAME_EVENT LEADERBOARD_UPDATE { source_id=0, target_id=0, entries: top10 }` to all clients. A
fallback path (leaderboard_manager null — unreachable in practice) sorts player states by
`pvp_kills` DESC / `entity_id` ASC and truncates to 10.

### 4.11 Region heartbeat — server → Go API (`server_main.gd:868-915`)

Setup at boot: skipped entirely iff `config.api_server_url` is empty; otherwise create the
HTTPRequest node and publish once immediately. Then from `_process` (frame loop):
`region_status_timer += frame_delta; if >= 2.0 { timer = 0.0; publish }`.

```
publish_region_status(status="online"):     # status parameter is never passed ≠ "online"
    if request node null OR a request is already in flight: return    # silently skipped this round
    url  = api_server_url.rstrip("/") + "/api/regions/heartbeat"      # rstrip removes ALL trailing '/'
    body = JSON {
        "region_id":      config.region,                      # default "local"
        "active_players": player_manager.get_player_count(),  # INCLUDES unauthenticated peers
        "max_players":    config.max_players,                 # default 100
        "websocket_url":  "ws://localhost:<config.port>",     # HARDCODED localhost (see §6)
        "status":         status
    }
    headers = ["Content-Type: application/json"]
    if env REGION_HEARTBEAT_TOKEN non-empty: headers += "X-Region-Heartbeat-Token: <token>"
    POST; on request-start error: in_flight=false, one-shot warning
    else in_flight = true
on completion: in_flight = false
    failure (result != SUCCESS or code not in [200,300)): one-shot warning (latched until next success)
    success: warning latch reset
```

Go handler `UpdateRegionHeartbeat` (`api/internal/handlers/region.go:91-178`), `POST` only:

1. If env `REGION_HEARTBEAT_TOKEN` set on the API: header `X-Region-Heartbeat-Token` must match
   exactly, else `401 {"error":"Unauthorized"}`.
2. Decode JSON body `{region_id, region, active_players, max_players, websocket_url, status}`
   (the Godot server sends all but `region`).
3. `region_id` lowercased+trimmed; falls back to `region` field; must be a valid region id
   (valid set per `models`: `local`, `asia`, `europe`, `us-west`), else `400`.
4. `max_players <= 0` → region's static default. `active_players < 0` → `0`; clamped to
   `<= max_players`.
5. `status` lowercased+trimmed; empty → `"online"`; anything other than
   `online|offline|maintenance` → `"online"`.
6. `websocket_url` trimmed; empty → region's static default.
7. Stored in Redis as region runtime status with **TTL 5 s** (so a server that stops
   heartbeating disappears from the live list within 5 s). Reply `200 {"status":"ok"}`.

This is the **only** HTTP call the game server makes. There is no shutdown "offline" publish —
the TTL is the liveness mechanism.

### 4.12 Server shutdown — `shutdown(reason)` (`server_main.gd:950-978`)

```
server_running = false
if network != null:
    network.clear_batches()                          # discard half-built tick batch
    for each state in player_manager.get_all_players():    # INCLUDING unauthenticated
        send_to_client(state.peer_id, DISCONNECT, {reason: DisconnectReason.SERVER_SHUTDOWN (3)})
player_manager.clear_all()          # players + position history (does NOT reset _next_entity_id
                                    # or _spawn_index)
projectile_manager.clear_all(); monster_manager.clear_all(); monster_ai = null
leaderboard.clear(); broadcast_service.clear_all_caches(); game_entities.clear(); metrics.clear()
```

`_exit_tree` calls `shutdown("Scene exit")` if still running.

### 4.13 Position history (lifecycle-adjacent, used by hit validation)

`record_position_snapshot(server_tick)` (`player_manager.gd:258-269`) — tick step 4, **before**
collisions: appends `{entity_id, position}` for every authenticated **and alive** player under
key `server_tick`; FIFO-trims to the most recent 8 ticks.

`get_recent_positions(entity_id)` (`player_manager.gd:295-305`): walks all recorded ticks oldest
→ newest, appending that entity's snapshot position when present, then appends the **live**
position if the entity still exists. Used by `_local_hit_is_plausible` (`server_main.gd:830-836`)
with threshold `8.0 + 16.0 + 64.0 = 88.0` units.

`get_alive_player_snapshot(server_tick)` (`player_manager.gd:274-289`) fallback chain: exact tick
→ greatest recorded tick `<= server_tick` → **oldest** recorded tick → live
`get_alive_players()` array (note: that last fallback returns `PlayerState`s, not snapshots —
callers only read `entity_id`/`position`, which both types expose).

### 4.14 LOCAL_HIT_REPORT lifecycle gates (`server_main.gd:776-820`)

Documented fully in the combat extraction; the lifecycle-owned parts:

- Rejected unless the reporting player exists, is `authenticated`, and `is_alive`.
- Sliding-window rate limit per peer: window resets when `now_ms - start_ms >= 1000`; the counter
  increments **before** the check; allowed while `count <= 20`. State erased on disconnect.

### 4.15 Client identity flow (AuthManager → GameManager → CONNECT_AUTH)

Go API endpoints used by the client (`api/cmd/server/main.go:80-95`):

| Endpoint | Method | Auth | Request body | Success response |
|---|---|---|---|---|
| `/api/auth/login` | POST | none | `{"username","password"}` | `200` `AuthResponse` |
| `/api/auth/register` | POST | none | `{"username","email","password"}` (client omits optional `region`) | `201` or `200` `AuthResponse` |
| `/api/auth/refresh` | POST | `Authorization: Bearer <refresh_token>` + body `{"refresh_token"}` | | `200` `AuthResponse` |
| `/api/character/me` | GET | `Authorization: Bearer <jwt>` | — | `200` character JSON; `404` = no character |
| `/api/character/create` | POST | Bearer | `{"name","class","race","realm","mode","level"}` | `CharacterSuccessResponse` |
| `/api/regions` | GET | none | — | `{"regions":[Region]}` |
| `/api/regions/select` | POST | Bearer | `{"region_id"}` | `{message, region, websocket_url}` |

`AuthResponse` (`api/internal/handlers/auth.go:44-49`):
`{"access_token": string, "refresh_token": string, "user": User, "character": Character?}`.
`User` = `{id:int, username, email, region, created_at}` (`models.go:7-13`).
`Character` = `{id:int, user_id:int, name, class, race, realm, mode, level:int, created_at}`
(`models.go:17-26`). **There is no `expiry` field** — see §6.10.

Client extraction (`auth_manager.gd:430-459, 503-520`):

```
jwt_token     = str(data["access_token"] or data["token"] or "")
refresh_token = str(data["refresh_token"] or "")
token_expiry  = int(data.get("expiry", 0))            # always 0 with today's Go API
user_data = { user_id:        str(data.user_id or data.user.id),     # int → "1" via
              username:       str(data.username or data.user.username),  # _variant_to_string
              character_id:   str(data.character_id or ""),              # (whole floats → int str)
              character_name: str(data.character_name or "") }
if data.character present: character_id = str(character.id or character.character_id)
                           character_name = str(character.name or character.character_name)
                           (only overwrite when non-empty)
else: GET /api/character/me and merge the same way (404 / failure → proceed without)
GameManager.set_player_data(user_data)   # Dictionary.merge(overwrite=true) into player_data
save token JSON to user://auth_token.dat
```

So the identity tuple available at CONNECT_AUTH time is:
**`character_id`** (stringified DB int, e.g. `"1"`), **`character_name`** (display name, the
client's self-identification key), `user_id`, `username`, `selected_region` (string, default
`"Asia"`), `player_color`. The Rust D9 ticket must carry at least
`{character_id, region/shard, issued_at, expiry}`; `character_name`/color can then be loaded
server-side instead of trusted (closing the §6.4 spoof).

The handshake is **arena-driven**: NetworkManager deliberately does not auth on connect
(`network_manager.gd:344-348`); the arena scene calls `send_auth_handshake()` once its listener
is bound; the call is idempotent per connection (`_auth_handshake_sent` flag, reset on
connect/close).

---

## 5. GAME_EVENT catalogue (server → client, wire format)

Common envelope (`game_event_packet.gd:142-146`): header `[u8 type=3][u16 payload_len]`, then
`[u8 event_type][u16 source_id][u16 target_id]` + per-type data. `vector2_compressed` =
`[s16 trunc(x*10)][s16 trunc(y*10)]`, components clamped to `[-32768, 32767]`; **`int()` cast
truncates toward zero**, it does not floor (`packet_writer.gd:126-134`). `string` =
`[u16 byte_len][utf8 bytes]`. Color = `[u8 r][u8 g][u8 b]`, each `clamp(round(c*255), 0, 255)`;
alpha never on the wire, forced 1.0 on read.

| Event | event_type | source_id | target_id | Extra payload | Emitted when |
|---|---|---|---|---|---|
| DAMAGE | 1 | attacker entity (player or monster projectile **owner**) | victim entity | `[u16 amount][u8 damage_type=0]` | every applied hit, players AND monsters (`server_collision_handler.gd:76-82, 117-123`) |
| KILL | 2 | killer entity | victim entity | none | monster died (`:132-137`) or monster killed a player (`:179-183`) |
| RESPAWN | 3 | 0 | respawned player entity | `vector2_compressed position` | granted respawn (`server_main.gd:855-859`) |
| PLAYER_INFO | 9 | 0 | player entity | `string name + vector2_compressed position + rgb color` | auth broadcast, newcomer catch-up, full-state recovery (§4.4) |
| KILL_PVP | 10 | killer player entity | victim player entity | none | player killed player (`server_collision_handler.gd:164-168`) |
| LEADERBOARD_UPDATE | 11 | 0 | 0 | `[u8 count] + count × ([u16 entity_id][u16 pvp_kills])` | every 5 s + on auth/disconnect/PvP-kill (§4.10) |
| PROJECTILE_FIRED | 12 | shooter entity | projectile entity id | `vector2_compressed spawn_pos + [u16 server_tick]` | player shot (`server_main.gd:414`, with position+tick) and monster shot (`server_main.gd:527-533`, **position=(0,0), server_tick=0**) |

`EFFECT_APPLY (4)`, `EFFECT_REMOVE (5)`, `PICKUP (6)`, `LEVEL_UP (7)`, `CHAT_MESSAGE (8)` exist in
the enum/codec but are never emitted by the server today. Unknown event types serialize with **no
extra payload** (silent empty body, `game_event_packet.gd:185-188`).

Other lifecycle packets: `RESPAWN_REQUEST (9)` client→server `[u32 ticks_ms]` (payload ignored);
`DISCONNECT (7)` `[u8 reason][u32 ticks_ms]`; `CONNECT_AUTH (6)` see §4.3.

---

## 6. Edge cases & gotchas

1. **Entity id exhaustion / collision (real bug to decide on).** `_next_entity_id` increments
   forever and is never recycled or reset — not on disconnect, not by `clear_all`. The
   "players 1–999" invariant holds only while **lifetime total connections < 1000**. After 9999
   connections the player range collides with projectile ids (10000+); ids are written as u16 on
   the wire, so beyond 65535 they wrap/truncate in packets while remaining distinct in server
   memory. The GDScript does nothing about any of this. The Rust port should recycle ids within
   1–999 (per migration-spec D8 slotmap plan) — a deliberate, documented deviation.
2. **Spawn cursor is shared and never resets.** Connects and respawns consume the same
   round-robin sequence; `_spawn_index` survives `clear_all()`. Spawn position is assigned at
   **connect** (pre-auth), so a peer that connects and never auths still consumes a slot in the
   rotation.
3. **Unauthenticated peers occupy capacity.** `max_players` is checked against
   `players.size()`, which includes connected-but-never-authenticated peers. There is no
   auth deadline/timeout kick (the only reaper is the 5 s transport heartbeat watchdog, which a
   malicious client can satisfy forever without authenticating).
4. **Self-identification by display name.** The client recognizes "its own" PLAYER_INFO by
   `character_name` string equality (`arena_base.gd:396`). Two players with the same name break
   local-id discovery (the first PLAYER_INFO with a matching name wins). The server does not
   enforce name uniqueness. An empty client-sent name is kept as `""` (the
   `"Player_%d"` default in `_handle_auth_request` only applies when the key is absent, which the
   binary codec never does) — and EntityNameCache refuses to cache empty names.
5. **No auth nack, no auth response.** A failed `authenticate_player` (unknown peer) is silent.
   The "Server full" rejection closes the socket without sending a DISCONNECT packet
   (`disconnect_client` is a raw close, `network_manager.gd:665-669`). `INVALID_AUTH`/`KICKED`/
   `DUPLICATE_SESSION` reason codes exist but are never sent.
6. **Re-auth is unguarded.** A second CONNECT_AUTH from the same peer overwrites
   identity/color/budget and re-broadcasts PLAYER_INFO + leaderboard. Entity id, position, HP
   are kept (since `add_player` is idempotent and auth doesn't respawn).
7. **Death edge cases.** `take_damage` with `amount <= 0` is a no-op returning false. Damage to
   an INVULNERABLE or dead player produces **no DAMAGE event** (`damage_applied <= 0` early
   return). The kill path: a killer who disconnected after firing still produces the KILL_PVP
   broadcast but no leaderboard/stat credit; a killer that exists but is somehow
   unauthenticated suppresses the KILL_PVP event entirely; killer==victim returns before any
   broadcast. Monster-kills-player emits `KILL` (not `KILL_PVP`) and does not touch the
   leaderboard (the victim's leaderboard `deaths` field only increments on PvP kills — and is
   never transmitted anyway).
8. **Respawn race window.** Respawn is granted only when `is_alive == false` and
   `respawn_timer <= 0.0` exactly at message-processing time. Because timers decrement in tick
   step 2 and messages are handled between ticks, a request arriving slightly early is silently
   dropped — the client must retry (the client UI does this). The discarded return value of
   `update_respawn_timer` means there is no server-initiated respawn whatsoever.
9. **Disconnect leaves traces.** Position history retains the departed entity for ≤ 8 ticks;
   EntityNameCache on clients keeps the name/color forever (until scene change clears it);
   leaderboard entry is removed (kills forgotten — by design, ADR 0005: leaderboard persistence
   belongs to the Go API, in-memory board is POC-only).
10. **Client token expiry handling is vestigial.** The Go API sends no `expiry`; the client
    therefore stores `token_expiry = 0`, never auto-refreshes (`token_expiry > 0` gate,
    `auth_manager.gd:73`), and on restart `_load_token` treats the saved token as expired
    (`token_expiry > current_time` is false) and deletes it. Login never survives a restart.
    Irrelevant to the Rust server but relevant when designing D9 ticket TTLs.
11. **Heartbeat dead code.** `PlayerManager.update_heartbeat` / `check_heartbeat_timeouts` and
    `ServerConfig.heartbeat_timeout_seconds` have **zero callers**. The live timeout mechanism is
    NetworkManager's transport-level watchdog (5.0 s, `network_manager.gd:65,224-230`). Do not
    port the dead path.
12. **Region heartbeat quirks.** `websocket_url` is hardcoded `ws://localhost:<port>` — correct
    only for single-host deployments; the Go API substitutes its static per-region URL when the
    field is empty, but it is never empty, so the hardcoded value wins (Redis TTL 5 s scopes the
    damage). `active_players` includes unauthenticated peers. The in-flight guard means a slow
    API (>2 s) silently halves the cadence. Heartbeats stop on shutdown without an "offline"
    publish; the 5 s Redis TTL is the only liveness signal. The Go side accepts the heartbeat
    with **no auth at all** unless `REGION_HEARTBEAT_TOKEN` is set in the API's environment.
13. **`_get_spawn_position` division-by-zero is guarded** (empty-spawn fallback to `(0,0)`), but
    note the fallback would put players at the map center inside the central cross obstacle's
    lane gap — only reachable if `ARENA_PLAYER_SPAWNS` were all invalidated.
14. **`get_player_by_entity_id` is O(n) linear scan** over the players dict
    (`player_manager.gd:78-82`); it runs per hit application. Fine in Rust with a secondary
    index, but preserve the "first match wins" semantics (entity ids are unique so it never
    matters).
15. **Dictionary iteration order.** `players.values()` iterates in insertion order in Godot.
    Nothing in the lifecycle depends on it semantically (move acks are per-peer, broadcasts are
    per-peer), but tick-internal ordering of move acks / shot processing follows join order today.
16. **Color quantization round-trip.** `Color(0.27,0.53,1.0)` → wire `(69,135,255)` → decode
    `(0.270588…, 0.529412…, 1.0)`. Comparisons must never assume exact float equality of colors
    across the wire.
17. **`_on_client_message` drops everything from unknown peers** (`server_main.gd:654`) — a
    message racing ahead of the `connected` event, or after disconnect cleanup, is ignored.
    CONNECT_AUTH therefore only works **after** the PlayerState exists.

---

## 7. Cross-subsystem contracts

### Expects from the transport (NetworkManager seam)

- `signal server_client_connected(peer_id: int)` — once per peer, after socket OPEN.
- `signal server_client_disconnected(peer_id: int)` — once per announced peer, on close or 5 s
  heartbeat timeout. HEARTBEAT and DISCONNECT packets are consumed at the transport layer and
  never reach ServerMain.
- `signal server_client_message(peer_id: int, message_type: int, data: Dictionary)` — decoded
  packets, with `data` as documented per type in §4.3/§5.
- `send_to_client(peer_id, message_type, data)`, `broadcast_to_clients(message_type, data)`,
  `disconnect_client(peer_id, reason_string)` (raw close), `begin_batch()/flush_batches()/
  clear_batches()`, `get_stats()`, `peer_bytes_sent`.

### Provides to the broadcast subsystem

- `PlayerManager.get_authenticated_players() -> Array[PlayerState]` — the broadcast population.
- `PlayerState.to_entity_data() -> {id, type=EntityType.PLAYER(1), position, animation, flags}`
  (`player_state.gd:95-102`) — the per-entity snapshot record.
- `PlayerState.peer_id`, `.position` (AoI center), `.max_snapshot_bytes`.
- At auth: `broadcast_service.set_peer_byte_budget(peer_id, bytes)`; at connect/disconnect:
  `get_or_create_delta_cache(peer_id)` / `remove_delta_cache(peer_id)`.

### Provides to combat / movement

- `PlayerManager.get_player(peer_id)`, `get_player_by_entity_id(entity_id)`,
  `get_alive_players()`, `get_alive_player_snapshot(server_tick)`,
  `get_recent_positions(entity_id)`.
- `PlayerState.take_damage(amount: int, source_id: int = -1) -> bool` (true = killed) — the
  **only** damage entry point; the invulnerability and death state machines live behind it.
- `PlayerState.can_shoot()` = `authenticated AND is_alive AND shoot_cooldown <= 0.0`;
  `start_shoot_cooldown()` sets 0.3 s.
- `movement_sm.apply_knockback(direction, 450.0)` on surviving hit.

### Expects from the Go API

- `POST /api/regions/heartbeat` accepting §4.11's payload, optional
  `X-Region-Heartbeat-Token`, Redis TTL 5 s.
- (Client-side) the auth/character endpoints of §4.15 producing the identity tuple.

### Tick-loop integration points (order within `_process_server_tick`, `server_main.gd:213-283`)

1. `player_manager.process_all_inputs(tick_interval, tick_count)` → ACTION_CONFIRM per player
   that had fresh input.
2. `_update_invulnerability_timers`, `_update_respawn_timers`, leaderboard 5 s timer (inside
   `_update_game_state`).
3. `player_manager.record_position_snapshot(tick_count)` (step 4, pre-collision).
4. Collision stage may call `apply_player_hit` → death (§4.6).
5. Message handlers (auth/respawn/hit-report) run **outside** the tick, between frames.

---

## 8. Rust port hazards (checklist)

- [ ] **Entity-id allocation**: GDScript never recycles and overflows the 1–999 range silently
  (§6.1). D8's slotmap-with-recycling is a *deviation* — make it explicit, and keep ids ≤ 999 so
  the u16 wire encoding and the `owner_id >= 30000` monster check stay valid.
- [ ] **Spawn at connect, not at auth**: the spawn position (and round-robin cursor advance)
  happens in `add_player`, before authentication. PLAYER_INFO later carries that exact position
  and the client force-syncs prediction to it — if Rust assigns spawn at auth instead, nothing
  breaks observably, but the cursor sequence under mixed connect/auth/respawn interleavings
  changes. Decide and document.
- [ ] **One shared round-robin cursor** for connects *and* respawns, modulo the **filtered**
  valid-spawn list (re-filtered every call), never reset. Reproduce exactly or accept divergent
  spawn sequences.
- [ ] **No auth validation today**: the Rust server adds Ed25519 verification (D9). Everything
  downstream of `authenticate_player` (PLAYER_INFO fan-out order, leaderboard registration,
  budget derivation `clamp(trunc(budget / snapshot_rate), 256, 1200)` with **float division then
  truncation toward zero**) must be preserved bit-for-bit.
- [ ] **Silent failure modes**: no auth nack, no respawn nack, "Server full" = bare socket close.
  Clients are built around these silences (retry loops, REQUEST_FULL_STATE recovery). Don't
  "helpfully" add error packets without revising the client.
- [ ] **Respawn gating order**: `is_alive` check **before** `respawn_timer` check; timer
  decremented only for authenticated players; `maxf(0.0, t - delta)` clamping; the server never
  auto-respawns. Timer comparisons are `> 0.0` (request rejected at exactly 0.0? no — rejected
  only when *strictly positive*, so the tick that clamps to 0.0 makes the player eligible).
- [ ] **Death is one-shot**: `_mark_dead` guards on already-DEAD; deaths counter, killer id,
  respawn timer, input purge all happen there and only there. Dead players keep replicating with
  `entity_flags == VISIBLE(32)` and `animation == DEATH(5)` — do not despawn them.
- [ ] **Damage math is integer**, `health = max(0, health - amount)`; DAMAGE event carries
  `previous_health - health` (the *applied* delta), and **no event** is emitted when the delta
  is ≤ 0 (invulnerable/dead). Damage selection by `owner_id >= 30000`, not by projectile type.
- [ ] **Kill-event branching** (§4.6): suicide → nothing; disconnected killer → KILL_PVP but no
  credit; unauthenticated killer → nothing; monster killer → KILL. Leaderboard `deaths` increments
  only via `record_pvp_kill`.
- [ ] **Leaderboard determinism**: kills DESC, entity_id ASC tiebreak; top-10 truncation; entries
  erased (kills forgotten) on disconnect; broadcast on the 5 s tick-time cadence **plus**
  immediate pushes on auth/disconnect/kill — both paths must exist or client HUDs lag.
- [ ] **Timers count tick-time, not wall-time** (leaderboard 5 s, respawn 3 s, invuln 3 s, shoot
  cooldown 0.3 s decrement in `step`) — they accumulate `1/tick_rate` per tick. The **region
  heartbeat is wall-clock frame time** (2 s of `_process` delta). Don't unify them.
- [ ] **Invulnerability ends three ways** (timer expiry; movement/shoot input held in `step`;
  shot attempt in `_try_spawn_projectile` *before* the cooldown check). The timer may go negative
  for one tick before reset — only the `<= 0.0` check matters.
- [ ] **Stale-input timeout**: flags cleared when `server_tick - last_input_received_tick > 6`
  with the `last_input_received_tick > 0` sentinel exemption (fresh connect/respawn). Off-by-one
  matters: strictly greater than 6.
- [ ] **Input queue overflow drops the OLDEST** (pop_front), capacity exactly 10; dead players
  discard inputs at ingest, not at queue time (a dead player's queue still fills and drains).
- [ ] **PLAYER_INFO fan-out order at auth**: (1) newcomer's info to all (including self), (2) all
  *other* authenticated players' info to newcomer (self skipped), (3) leaderboard register +
  broadcast. The client's local-id discovery depends on (1) including self and on the name-match
  heuristic (§6.4).
- [ ] **Wire quantization**: positions in GAME_EVENTs are `trunc(x*10)` (toward zero, NOT floor —
  negative coordinates differ!) clamped to s16; colors `round(c*255)` clamped u8; strings u16-length
  UTF-8. Tokens >65535 bytes would silently corrupt (u16 length) — irrelevant after D9.
- [ ] **Heartbeat/timeout ownership**: the live 5 s reaper is the transport layer; PlayerManager's
  heartbeat API is dead code. Under ENet (D2) this is subsumed by ENet timeouts — delete, don't
  port; but keep the *cleanup-on-disconnect order* (leaderboard removal **before** player removal,
  because it needs entity_id).
- [ ] **No "player left" GAME_EVENT** — departure is communicated only through delta-stream entity
  removal. Don't invent one.
- [ ] **Region heartbeat payload**: keep field names (`region_id`, `active_players`,
  `max_players`, `websocket_url`, `status`), 2 s cadence, in-flight skip, the optional shared
  token header, and the 5 s Redis TTL semantics; fix the hardcoded
  `ws://localhost:<port>` consciously (config), since D13 generalizes this into instance liveness
  registration.
- [ ] **Identity fields for the D9 ticket**: today's trust-the-client tuple is
  `character_id` (string-encoded int), `character_name` (display, non-unique, may be empty),
  `region` (u8 enum, currently ignored server-side), `player_color` (RGB u8×3), and
  `bandwidth_budget_bps` (u32). The ticket should carry `character_id` + region; name/color move
  to server-side lookup or stay client-supplied cosmetics — decide, then update the client's
  name-equality self-identification (§6.4) accordingly (safer: send the client its own entity_id
  explicitly in an auth-accepted message).
- [ ] **Everything is single-threaded today** — handlers mutate state between ticks with no
  locking. The Rust single-tick-thread design (D8) must funnel network events into the tick
  thread, preserving "messages processed in arrival order, between ticks" semantics.
