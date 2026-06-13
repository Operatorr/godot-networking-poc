# Client integration — extraction notes for the Rust port

> Generated extraction notes for the Rust port — derived from GDScript at commit on branch
> feature/rust-port. Source of truth is the GDScript until cutover.

Subsystem: the **client-side integration surface** — `NetworkManager` (connection lifecycle,
packet encode/decode/dispatch, clock sync), the `Transport` seam (`WebSocketTransport`),
`PredictionController` (local-player prediction + reconciliation), `InterpolationController` +
`EntityStateBuffer` (remote-entity snapshot buffering and rendering), and `ClientEntityManager`
(visual entity lifecycle). Decision-log context: **D2** (ENet, 3 channels), **D5** (shared
`sim_core` via GDExtension), **D6** (codec in the extension, no GDScript codec), **D7**
(shared Rust `protocol` crate), **D8** (30 Hz single-thread tick), **D11** (hit authority).

Source files (all paths relative to repo root):

| File | Role |
|---|---|
| `client/autoload/network_manager.gd` | Autoload singleton. Dual-mode (client/server) socket lifecycle, packet codec, dispatch, heartbeat/clock sync, reconnect, stats. |
| `client/autoload/transport/transport.gd` | Abstract transport seam (`Transport`, `RefCounted`). |
| `client/autoload/transport/websocket_transport.gd` | Concrete WebSocket/TCP transport below the seam. |
| `client/scripts/client/prediction.gd` | `PredictionController` (Node, child of local player). |
| `client/scripts/client/interpolation_controller.gd` | `InterpolationController` (Node, child of arena). |
| `client/scripts/client/entity_state_buffer.gd` | `EntityStateBuffer` (RefCounted), per-entity 5-slot ring. |
| `client/scripts/client/client_entity_manager.gd` | `ClientEntityManager` (Node), visual spawn/despawn. |

---

## 1. Overview

The client runs Godot's physics loop at **30 Hz** (`Engine.physics_ticks_per_second` is set
from `GameConstants.SERVER_TICK_RATE`; see `game_manager.gd:70` per
`docs/netcode/latency-budget.md`). Per physics tick, in this order of node processing:

1. **`NetworkManager._process(delta)`** (runs in `_process`, i.e. every *render frame*, not
   physics frame) — polls the transport, drains inbound packets FIFO, decodes each, handles
   HEARTBEAT internally, and **emits `server_message_received(message_type, data)`** for
   everything else. All downstream handlers are signal listeners; dispatch is synchronous
   within the emit.
2. **`PredictionController._physics_process(delta)`** (30 Hz) — samples input, advances the
   local player's predicted position via the shared movement state machine + analytic obstacle
   mover, eases any in-flight correction, and sends one `PLAYER_INPUT` per server-tick
   interval.
3. **`InterpolationController._physics_process(delta)`** (30 Hz) — advances a sub-tick
   accumulator and writes interpolated positions into every registered remote-entity node,
   rendering them at `render_tick = current_server_tick − round(adaptive delay 1–3 ticks)`.
4. **`ClientEntityManager`** — purely reactive: spawns/despawns visual nodes on
   `InterpolationController` signals, and `update_entity_visuals()` (called per frame by the
   arena) snaps animation/flags to latest.

Reconciliation inputs arrive over two packet types: `ACTION_CONFIRM` (per-input ack with
corrected position + stamina/mana) and `STATE_UPDATE` (the local player's own entity inside a
snapshot). Remote entities are never predicted; the local player is never interpolated.

```
            ┌──────────────── server packets ────────────────┐
WebSocket ─► NetworkManager._process ─► server_message_received(type, data)
                  │ (HEARTBEAT intercepted: RTT + clock offset)
                  ├─► PredictionController._on_server_message   (ACTION_CONFIRM, STATE_UPDATE)
                  ├─► InterpolationController._on_server_message (STATE_UPDATE)
                  ├─► ArenaBase._on_server_message               (GAME_EVENT, STATE_UPDATE)
                  ├─► ServerStatus._on_server_message            (SERVER_METRICS)
                  └─► EntityNameCache._on_server_message         (GAME_EVENT / PLAYER_INFO)
```

`NetworkManager` also contains the **server-mode** path (the same Godot binary is the current
server). That entire path is replaced by the Rust server and is documented here only as far as
it defines the contract the client observes (heartbeat reply stamping, batch framing).

---

## 2. Constants

All values are exact; do not round. "u" = world units (pixels at 1:1).

### NetworkManager (`client/autoload/network_manager.gd`)

| Constant / default | Value | Unit | Source |
|---|---|---|---|
| `MessageType.PLAYER_INPUT` | 1 | enum | network_manager.gd:17 (mirrors PacketTypes.Type, packet_types.gd:19–33) |
| `MessageType.STATE_UPDATE` | 2 | enum | network_manager.gd:18 |
| `MessageType.GAME_EVENT` | 3 | enum | network_manager.gd:19 |
| `MessageType.HEARTBEAT` | 4 | enum | network_manager.gd:20 |
| `MessageType.ACTION_CONFIRM` | 5 | enum | network_manager.gd:21 |
| `MessageType.CONNECT_AUTH` | 6 | enum | network_manager.gd:22 |
| `MessageType.DISCONNECT` | 7 | enum | network_manager.gd:23 |
| `MessageType.REQUEST_FULL_STATE` | 8 | enum | network_manager.gd:24 |
| `MessageType.RESPAWN_REQUEST` | 9 | enum | network_manager.gd:25 |
| `MessageType.SERVER_METRICS` | 10 | enum | network_manager.gd:26 |
| `MessageType.BATCH` | 11 | enum | network_manager.gd:27 (deleted per D2) |
| `MessageType.BASELINE_ACK` | 12 | enum | network_manager.gd:28 |
| `MessageType.LOCAL_HIT_REPORT` | 13 | enum | network_manager.gd:29 |
| `BATCH_MAX_PACKETS` | 255 | packets | network_manager.gd:77 |
| `BATCH_MAX_INNER_BYTES` | 65534 (`MAX_PACKET_SIZE − 1`) | bytes | network_manager.gd:80 |
| `DEFAULT_CLIENT_BUDGET` | 120000 | bytes/sec | network_manager.gd:85 |
| `server_heartbeat_timeout` | 5.0 | s | network_manager.gd:65 (server mode) |
| `server_port` default | 8080 | port | network_manager.gd:91 |
| `max_reconnect_attempts` | 5 | count | network_manager.gd:99 |
| `base_reconnect_delay` | 1.0 | s | network_manager.gd:100 |
| `max_reconnect_delay` | 32.0 | s | network_manager.gd:101 |
| `connection_timeout_seconds` | 5.0 | s | network_manager.gd:103 |
| connection poll step | 0.1 | s | network_manager.gd:330–331 |
| `heartbeat_interval` | 1.0 | s | network_manager.gd:108 |
| `heartbeat_timeout_seconds` | 5.0 | s | network_manager.gd:111 |
| `UINT32_WRAP` | 4294967296 | — | network_manager.gd:112 |
| `MAX_REASONABLE_PING_MS` | 10000 | ms | network_manager.gd:113 |
| `SERVER_CLOCK_FILTER_ALPHA` | 0.2 | EMA weight | network_manager.gd:121 |
| WebSocket close code used everywhere | 1000 | — | network_manager.gd:356, 434, 521, 669, 680 |
| Default auth region | `"Asia"` | string | network_manager.gd:384 |
| Default player color | `Color(0.27, 0.53, 1.0)` | rgb floats | network_manager.gd:385 |

### Wire-protocol constants referenced by this subsystem (`client/scripts/shared/networking/packet_types.gd`)

| Constant | Value | Source |
|---|---|---|
| `HEADER_SIZE` | 3 (`[u8 type][u16 payload_len]`, little-endian u16) | packet_types.gd:7 |
| `MAX_PACKET_SIZE` | 65535 | packet_types.gd:10 |
| `INPUT_FLAG_MOVE_UP` | 1 (1<<0) | packet_types.gd:56 |
| `INPUT_FLAG_MOVE_DOWN` | 2 (1<<1) | packet_types.gd:57 |
| `INPUT_FLAG_MOVE_LEFT` | 4 (1<<2) | packet_types.gd:58 |
| `INPUT_FLAG_MOVE_RIGHT` | 8 (1<<3) | packet_types.gd:59 |
| `INPUT_FLAG_SHOOT` | 16 (1<<4) | packet_types.gd:60 |
| `INPUT_FLAG_ABILITY` | 32 (1<<5) | packet_types.gd:61 |
| `INPUT_FLAG_SPRINT` | 64 (1<<6) | packet_types.gd:62 |
| `INPUT_FLAG_INTERACT` | 128 (1<<7) | packet_types.gd:63 |
| `INPUT_FLAG_DASH` | 256 (1<<8) — input flags are a **u16** on the wire | packet_types.gd:64 |
| `ENTITY_FLAG_ALIVE` | 1 | packet_types.gd:67 |
| `ENTITY_FLAG_MOVING` | 2 | packet_types.gd:68 |
| `ENTITY_FLAG_ATTACKING` | 4 | packet_types.gd:69 |
| `ENTITY_FLAG_INVULNERABLE` | 8 | packet_types.gd:70 |
| `ENTITY_FLAG_STUNNED` | 16 | packet_types.gd:71 |
| `ENTITY_FLAG_VISIBLE` | 32 | packet_types.gd:72 |
| `ENTITY_FLAG_DASHING` | 64 | packet_types.gd:73 |
| `ENTITY_FLAG_KNOCKED_BACK` | 128 | packet_types.gd:74 |
| `DELTA_MASK_POSITION` | 1 (1<<0) | packet_types.gd:78 |
| `DELTA_MASK_ANIMATION` | 2 (1<<1) | packet_types.gd:79 |
| `DELTA_MASK_FLAGS` | 4 (1<<2) | packet_types.gd:80 |
| `DELTA_MASK_REMOVED` | 64 (1<<6) | packet_types.gd:81 |
| `DELTA_MASK_FULL_STATE` | 128 (1<<7) | packet_types.gd:82 |
| `STATE_FLAG_IS_DELTA` | 1 (1<<0) | packet_types.gd:86 |
| `STATE_FLAG_BASELINE` | 2 (1<<1) | packet_types.gd:87 |
| `EntityType.PLAYER` / `MONSTER` / `PROJECTILE` | 1 / 2 / 3 | packet_types.gd:36–40 |
| `AnimationState` IDLE..SPAWN | 0,1,2,3,4,5,6 | packet_types.gd:43–51 |
| `DisconnectReason` USER_QUIT..DUPLICATE_SESSION | 0,1,2,3,4,5 | packet_types.gd:112–119 |
| `GameEventType` (DAMAGE=1 … PROJECTILE_FIRED=12) | 1–12 | packet_types.gd:96–109 |
| `ActionConfirmPacket.ActionType` MOVE/SHOOT/ABILITY/INTERACT | 0/1/2/3 | action_confirm_packet.gd:16–21 |
| `ActionConfirmPacket.ResultCode` SUCCESS..FAILED_INVALID_STATE | 0..5 | action_confirm_packet.gd:24–31 |

### PredictionController (`client/scripts/client/prediction.gd`)

| Constant / export default | Value | Unit | Source |
|---|---|---|---|
| `interpolation_speed` (export) | 12.0 | 1/s lerp rate | prediction.gd:27 |
| `max_buffer_size` (export) | 256 | inputs | prediction.gd:29 (**never enforced in code** — see §5) |
| `teleport_threshold` (export) | 150.0 | u | prediction.gd:35 |
| `server_position_epsilon` (export) | 4.0 | u | prediction.gd:37 |
| `INPUT_SEND_INTERVAL` | `GameConstants.SERVER_TICK_INTERVAL` = 1.0/30.0 ≈ 0.0333333… | s | prediction.gd:78, game_constants.gd:25 |
| sequence width | 8-bit, wraps at 256 (`& 0xFF`) | — | prediction.gd:451 |
| wrap-compare half-window | forward distance < 128 ⇒ "before" | — | prediction.gd:445 |
| smooth-correction stop distance | 1.0 | u | prediction.gd:743 |
| `_last_predicted_shot_time` initial | −INF | s | prediction.gd:90 |
| muzzle offset | `PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0` = 16.0+8.0+2.0 = 26.0 | u | prediction.gd:310–312 |
| `local_entity_id` initial | −1 (sentinel: unknown) | — | prediction.gd:49 |
| `last_ack_sequence` initial | −1 (sentinel: none) | — | prediction.gd:61 |

### GameConstants used by this subsystem (`client/scripts/shared/game_constants.gd`)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `SERVER_TICK_RATE` | 30.0 | Hz | game_constants.gd:22 |
| `SERVER_TICK_INTERVAL` | 1.0/30.0 | s | game_constants.gd:25 |
| `REMOTE_ENTITY_RENDER_DELAY_TICKS` | 2 | ticks | game_constants.gd:33 |
| `PLAYER_SPEED` | 200.0 | u/s | game_constants.gd:53 |
| `PLAYER_SPRINT_MULTIPLIER` | 1.6 | × | game_constants.gd:56 |
| `PLAYER_SPRINT_SPEED` | 320.0 (200.0×1.6) | u/s | game_constants.gd:59 |
| `PLAYER_STAMINA_SPRINT_MIN` | 5.0 | stamina | game_constants.gd:113 |
| `PLAYER_STAMINA_MAX` / `PLAYER_MANA_MAX` | 100.0 / 100.0 | — | game_constants.gd:104,121 |
| `TELEPORT_THRESHOLD` | 150.0 | u | game_constants.gd:169 |
| `PROJECTILE_RADIUS` | 8.0 | u | game_constants.gd:335 |
| `PLAYER_HITBOX_RADIUS` | 16.0 | u | game_constants.gd:343 |
| `SHOOT_COOLDOWN` | 0.3 | s | game_constants.gd:364 |
| `MONSTER_ENTITY_ID_START` | 30000 | id | game_constants.gd:386 |

### InterpolationController (`client/scripts/client/interpolation_controller.gd`)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `RENDER_DELAY_TICKS` (seed) | 2 | ticks | interpolation_controller.gd:11 |
| `MIN_RENDER_DELAY_TICKS` | 1 | ticks | interpolation_controller.gd:16 |
| `MAX_RENDER_DELAY_TICKS` | 3 | ticks | interpolation_controller.gd:17 |
| `DESPAWN_THRESHOLD` | 3 | consecutive missing full snapshots | interpolation_controller.gd:21 |
| `MAX_EXTRAPOLATION_TICKS` | 2 | ticks | interpolation_controller.gd:25 |
| `TELEPORT_THRESHOLD` | 150.0 (= GameConstants) | u | interpolation_controller.gd:31 |
| `interpolation_speed` (export, **unused in code**) | 12.0 | — | interpolation_controller.gd:57 |
| tick-interval EMA alpha | 0.1 | — | interpolation_controller.gd:205 |
| jitter EMA alpha | 0.1 | — | interpolation_controller.gd:210 |
| render-delay target | `interval_ms + 2.0 × jitter_ms`, in ticks, clamped [1,3] | — | interpolation_controller.gd:212–217 |
| render-delay adapt rate (grow / shrink) | 0.5 / 0.05 | lerp weight per snapshot | interpolation_controller.gd:222 |
| interval floor in target calc | 0.001 | ms | interpolation_controller.gd:211 |
| `estimated_tick_interval` initial | `SERVER_TICK_INTERVAL` = 1/30 s | s | interpolation_controller.gd:83 |
| `FULL_STATE_REQUEST_TIMEOUT_MS` | 2000 | ms | interpolation_controller.gd:111 |
| `FULL_STATE_MAX_RETRIES` | 3 | count | interpolation_controller.gd:112 |

### EntityStateBuffer (`client/scripts/client/entity_state_buffer.gd`)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `BUFFER_SIZE` | 5 | snapshots (ring) | entity_state_buffer.gd:11 |
| `TICK_INTERVAL_SEC` | `SERVER_TICK_INTERVAL` = 1/30 (declared, **never read**) | s | entity_state_buffer.gd:15 |
| `estimated_tick_interval_ms` initial | `SERVER_TICK_INTERVAL * 1000.0` ≈ 33.333…  | ms | entity_state_buffer.gd:82 |
| calibration EMA alpha | 0.1 | — | entity_state_buffer.gd:130–134 |
| `last_tick_added` / `spawn_tick` initial | −1 / −1 (sentinels) | tick | entity_state_buffer.gd:73,76 |

### ClientEntityManager (`client/scripts/client/client_entity_manager.gd`)

| Constant | Value | Source |
|---|---|---|
| `NETWORK_PROJECTILE_POOL_SIZE` | 64 | client_entity_manager.gd:28 |
| Scene paths (remote player / monster / projectile) | `res://scenes/shared/player/remote_player.tscn`, `.../monster/monster.tscn`, `.../projectile/projectile.tscn` | client_entity_manager.gd:8–10 |
| player-owned projectile id test | `0 < source_id < 30000` | client_entity_manager.gd:559 |

---

## 3. Data structures

All Godot `Dictionary` types are insertion-ordered hash maps with `Variant` keys/values.
Iteration order is insertion order; **no algorithm below depends on iteration order** except
where noted. `Vector2` is two **float32** components in Godot's C++ core, but all GDScript
arithmetic on them is performed via float64 paths with float32 storage (see §7 hazards).

### NetworkManager state (client mode)

| Field | Type | Initial | Range / notes |
|---|---|---|---|
| `is_server` | bool | computed at `_ready` | `OS.has_feature("dedicated_server") or DisplayServer.get_name()=="headless"`, and **not** a test scene (network_manager.gd:141, 174–186) |
| `current_state` | enum ConnectionState {DISCONNECTED=0, CONNECTING=1, CONNECTED=2, RECONNECTING=3, ERROR=4} | DISCONNECTED | network_manager.gd:7–13,88 |
| `server_url` | String | "" | the ws:// URL last attempted |
| `auth_token` | String | "" | JWT from Go API |
| `_auth_handshake_sent` | bool | false | idempotency latch; cleared on `_complete_connection` and `_on_connection_closed` |
| `reconnect_attempts` | int | 0 | 0..5 |
| `reconnect_timer` | float | 0.0 | countdown seconds while RECONNECTING |
| `_connection_attempt_id` | int | 0 | monotonic; staleness guard for the async wait loop |
| `_had_successful_connection` | bool | false | gates auto-reconnect vs. error-emit |
| `heartbeat_timer` | float | 0.0 | accumulates `_process` delta |
| `last_heartbeat_received` | float | 0.0 | seconds (`Time.get_ticks_msec()/1000.0`) |
| `server_clock_offset_ms` | float | 0.0 | EMA of `server_ms − (local_ms − rtt/2)` |
| `server_clock_offset_samples` | int | 0 | 0 ⇒ "no sync yet" |
| `stats` | Dictionary | `{packets_sent:0, packets_received:0, bytes_sent:0, bytes_received:0, ping_ms:0.0, last_ping_time:0.0}` | network_manager.gd:124–131 |
| `_transport` | Transport | `WebSocketTransport.new()` with role | network_manager.gd:145–146 |

Server-mode-only fields (`peer_connection_announced`, `peer_last_heartbeat`,
`peer_bytes_sent`, `_batching_active`, `_pending_batches`, `bytes_sent_by_type`) are replaced
wholesale by the Rust server and not detailed further (semantics in §4.1.9 where they define
client-visible behavior).

### Transport seam (`transport.gd`)

`enum LinkState { OPEN=0, CONNECTING=1, CLOSING=2, CLOSED=3 }`, `enum Role { CLIENT=0,
SERVER=1 }`. WebSocketTransport maps `WebSocketPeer.STATE_*` onto LinkState
(websocket_transport.gd:34–45); anything not OPEN/CONNECTING/CLOSING maps to CLOSED.
Client-side concrete state: `_ws_client: WebSocketPeer` (null until first connect, nulled by
`client_reset()`).

### PredictionController state

| Field | Type | Initial | Range / notes |
|---|---|---|---|
| `player_node` | Node2D | null | the local player visual node |
| `interpolation_controller` | InterpolationController | null | optional, for `client_render_tick` + diagnostics |
| `local_entity_id` | int | −1 | players 1–999; −1 = unknown |
| `predicted_position` | Vector2 | (0,0) | authoritative client-side logical position |
| `predicted_velocity` | Vector2 | (0,0) | realized (post-collision) velocity |
| `has_authoritative_position` | bool | false | true after first server position applied |
| `last_ack_sequence` | int | −1 | −1 or 0–255 |
| `current_sequence` | int | 0 | 0–255, next unused sequence |
| `input_buffer` | Dictionary int→InputSnapshot | {} | logically ≤256 entries (8-bit key space; wrap **overwrites**) |
| `correction_target` | Vector2 | (0,0) | retargeted to `predicted_position` every correcting frame |
| `is_correcting` | bool | false | smooth-correction in flight |
| `last_server_tick` | int | 0 | latest tick seen via ack or snapshot |
| `input_send_timer` | float | 0.0 | accumulator, carries remainder (`-= INTERVAL`) |
| `current_input_flags` | int | 0 | u16 bitfield |
| `_dash_latched` | bool | false | rising-edge latch, cleared after each send |
| `_last_predicted_shot_time` | float | −INF | seconds |
| `prediction_enabled` | bool | true | master switch |

`InputSnapshot` (inner class, prediction.gd:99–120): `sequence:int`, `input_flags:int`,
`position_before:Vector2`, `position_after:Vector2`, `velocity:Vector2`, `aim_angle:float`,
`delta:float` (always `INPUT_SEND_INTERVAL`), `timestamp:float` (local seconds; informational
only — never read by any algorithm).

### InterpolationController state

| Field | Type | Initial |
|---|---|---|
| `entity_buffers` | Dictionary int→EntityStateBuffer | {} |
| `entity_nodes` | Dictionary int→Node2D | {} |
| `missing_update_count` | Dictionary int→int | {} |
| `current_server_tick` | int | 0 |
| `render_tick` | int | 0 |
| `tick_accumulator` | float | 0.0 |
| `estimated_tick_interval` | float (s) | 1/30 |
| `estimated_jitter_ms` | float | 0.0 |
| `render_delay_ticks_smooth` | float | 2.0 |
| `last_update_time_ms` | int | 0 |
| `entities_in_last_update` | Dictionary int→bool | {} (remote ids only) |
| `entity_last_states` | Dictionary int→{entity_type:int, position:Vector2, animation_state:int, flags:int} | {} |
| `last_baseline_tick` | int | 0 |
| `needs_full_state_sync` | bool | false |
| `_full_state_request_time` | int (ms) | 0 (0 = no pending request) |
| `_full_state_retry_count` | int | 0 (0..3) |

### EntityStateBuffer

Per entity: `entity_id:int`, `snapshots: Array[EntitySnapshot]` sized 5 and pre-filled with
null, `write_index:int = 0`, `snapshot_count:int = 0` (0..5), `last_tick_added:int = −1`,
`spawn_tick:int = −1`, `despawn_pending:bool = false`, `estimated_tick_interval_ms:float ≈
33.333` (calibrated but **never consumed** by interpolation math — interpolation uses the
controller-level estimate).

`EntitySnapshot`: `server_tick:int`, `timestamp_ms:int` (local receipt time), `position:Vector2`,
`animation_state:int` (default IDLE=0), `flags:int` (u8 bitfield), `entity_type:int` (default
PLAYER=1).

### ClientEntityManager

`player_entities: Dictionary int→RemotePlayer`, `monster_entities: Dictionary int→Monster`,
`_dead_monster_effects_played: Dictionary int→bool`, `_projectile_pool: Array[Projectile]`
(≤64), `_active_projectiles: Dictionary int→Projectile`, `_active_projectile_order: Array[int]`
(spawn order, oldest first), `_projectile_sources: Dictionary int→int` (projectile_id →
source entity_id), `_player_prev_anim: Dictionary int→int`.

---

## 4. Algorithms

Pseudocode is language-neutral; `&` is bitwise AND; integer ops are arbitrary-precision GDScript
ints (64-bit signed in practice); float literals are float64 in GDScript expressions.

### 4.1 NetworkManager

#### 4.1.1 Mode detection and init — `_ready` (network_manager.gd:139–153)

```
is_server = (OS feature "dedicated_server" OR display server == "headless") AND NOT test_scene
transport = WebSocketTransport(role = SERVER if is_server else CLIENT)
if is_server: server_listen(port from ServerConfig, default 8080); state = CONNECTED on OK
else: nothing (waits for connect_to_server)
```
Test-scene check (`:174–186`): current scene path starts with `res://scenes/test/` or equals
`res://scenes/shared/levels/practice.tscn`.

#### 4.1.2 Client connect — `connect_to_server(url, token, is_reconnect=false)` (network_manager.gd:283–311)

```
if state == CONNECTED:  log, return            # idempotent
if state == CONNECTING: log, return
if not is_reconnect: reconnect_attempts = 0; _had_successful_connection = false
server_url = url; auth_token = token; state = CONNECTING
attempt_id = ++_connection_attempt_id
err = transport.client_connect(url)             # WebSocketPeer.connect_to_url(url, TLSOptions.client())
if err != OK: _fail_connection_attempt(format_error(url), is_reconnect)
else: await _wait_for_connection(attempt_id, is_reconnect)
```

`_wait_for_connection` (`:314–334`): loop while `elapsed < 5.0`:
- if `attempt_id != _connection_attempt_id`: return (a newer attempt superseded this one).
- poll transport; if state OPEN → `_complete_connection()`, return; if CLOSED →
  `_fail_connection_attempt(...)`, return.
- await a 0.1 s scene-tree timer; `elapsed += 0.1`.
On loop exhaustion: timeout → `_fail_connection_attempt(...)`.

`_complete_connection` (`:337–350`): state = CONNECTED, `reconnect_attempts = 0`,
`_had_successful_connection = true`, `last_heartbeat_received = now_s`,
`_auth_handshake_sent = false`, emit `connected_to_server`. **Auth is intentionally NOT sent
here** — the arena drives it after wiring its listener (arena_base.gd:221).

`_fail_connection_attempt(msg, is_reconnect)` (`:353–362`): state = ERROR;
`transport.client_close(1000, "")`; `transport.client_reset()` (drops the socket object);
if `is_reconnect OR _had_successful_connection` → `_schedule_reconnect()` else emit
`connection_error(msg)`.

#### 4.1.3 Reconnect backoff — `_schedule_reconnect` (network_manager.gd:1051–1075)

```
if server_url empty: state = DISCONNECTED; return
if reconnect_attempts >= 5: state = ERROR; emit connection_error("Failed to reconnect after N attempts"); return
delay = min(1.0 * 2^reconnect_attempts, 32.0)     # 1,2,4,8,16 s for attempts 0..4
reconnect_timer = delay; reconnect_attempts += 1; state = RECONNECTING
```
While RECONNECTING, `_process_client` counts `reconnect_timer -= delta`; at ≤0 it calls
`connect_to_server(server_url, auth_token, true)` (`:277–280`, `:1073–1075`).

#### 4.1.4 Connected-state pump — `_process_connected(delta)` (network_manager.gd:241–274)

Runs every **render frame** (`_process`), not physics frame:
```
transport.client_poll()
state = transport.client_state()
if state == OPEN:
    for buf in transport.client_take_packets():     # drain ALL available, FIFO
        _handle_incoming_packet(buf)
    heartbeat_timer += delta
    if heartbeat_timer >= 1.0: heartbeat_timer = 0.0; send_heartbeat()   # reset to 0, not -=
    if (now_s − last_heartbeat_received) > 5.0:
        emit heartbeat_timeout; disconnect_from_server("Heartbeat timeout")
elif state == CLOSING: log only
elif state == CLOSED:
    info = transport.client_close_info()
    _on_connection_closed(info.reason)   # state=DISCONNECTED, _auth_handshake_sent=false,
                                         # emit disconnected_from_server(reason),
                                         # if _had_successful_connection: _schedule_reconnect()
```

#### 4.1.5 Inbound dispatch — `_handle_incoming_packet` / `_dispatch_received_buffer` (network_manager.gd:441–489)

```
stats.packets_received += 1; stats.bytes_received += buf.size()
dispatch(buf):
    if buf.size() < 3: log "undersized", drop
    type = buf[0]                                # u8 at offset 0
    if type == BATCH(11): unwrap (below); return
    message = _decode_packet(buf)                # full decode, see 4.1.8
    if message null/empty: log "failed decode", drop
    mtype = message.type
    if mtype == HEARTBEAT:
        last_heartbeat_received = now_s
        _handle_heartbeat_response(message)      # RTT + clock offset, see 4.1.7
    else:
        emit server_message_received(mtype, message.data)   # synchronous fan-out
```

BATCH unwrap (`_dispatch_batch_buffer`, `:474–489`) — wire `[u8 11][u16 payload_len][u8
count][N inner packets]`:
```
if buf.size() < 4: drop
count = buf[3]; pos = 4
repeat count times (index i):
    if pos + 3 > buf.size(): log "truncated at i/count"; stop
    inner_len = u16 at pos+1 (little-endian)
    inner_size = 3 + inner_len
    if pos + inner_size > buf.size(): log "inner overflows"; stop
    dispatch(buf[pos .. pos+inner_size])        # recursive — a nested BATCH would recurse
    pos += inner_size
```
Inner packets are dispatched **in order**, preserving the server's per-tick queue order.
(Per D2 the BATCH envelope is deleted; ENet coalesces instead. The ordering guarantee must be
preserved per channel.)

#### 4.1.6 Outbound — `send_message(type, data) -> bool` (network_manager.gd:694–711)

```
if current_state != CONNECTED: log, return false
if transport.client_state() != OPEN: log, return false
packet = _encode_packet(type, data)
if transport.client_send(packet) == OK:
    stats.packets_sent += 1; stats.bytes_sent += packet.size(); return true
else: log, return false
```
`send_to_server` is an alias (`:714–715`). `send_player_input(input_data)` =
`send_message(PLAYER_INPUT, input_data)` (`:718–719`).

`send_heartbeat` (`:722–725`): `send_message(HEARTBEAT, {timestamp: Time.get_ticks_msec()})`;
`stats.last_ping_time = now_s`. Encoded as `[u32 timestamp][u32 server_ms=0]` (8-byte payload).

`send_auth_handshake` (`:372–406`) — idempotent per connection session:
```
if _auth_handshake_sent: return
if auth_token empty: log skip, return
if state != CONNECTED: log skip, return
read from GameManager.player_data (if the GameManager autoload exists):
    character_id (def ""), character_name (def ""), region (def "Asia"),
    player_color (def Color(0.27,0.53,1.0))
auth_data = { token, character_id, character_name, region, player_color,
              bandwidth_budget_bps: _get_client_bandwidth_budget() }
if send_message(CONNECT_AUTH, auth_data): _auth_handshake_sent = true
# on send failure the latch stays false so a retry is allowed
```
`_get_client_bandwidth_budget` (`:413–420`): `int(player_data.bandwidth_budget_bps)` if
GameManager exists else 120000; any value ≤0 is replaced with 120000.

`disconnect_from_server(reason="User disconnect")` (`:424–437`):
```
if transport CLOSED or state DISCONNECTED: return
send_message(DISCONNECT, {reason: reason_code(reason)})   # best-effort, still CONNECTED here
transport.client_close(1000, reason)
state = DISCONNECTED
emit disconnected_from_server(reason)                      # NOTE: no auto-reconnect on this path
```
`_get_disconnect_reason_code` (`:774–789`): if reason is already int, pass through; else
lowercase substring match **in this order**: "timeout"→1, "kick"→2, "server shutdown"→3,
"invalid auth"→4, "duplicate"→5, else 0 (USER_QUIT).

`is_server_connected()` (`:1078–1080`) = `current_state == CONNECTED AND transport state ==
OPEN`. This is the liveness predicate used by prediction and interpolation.

#### 4.1.7 Clock sync — `_handle_heartbeat_response` (network_manager.gd:728–754) and `get_server_time_ms` (`:760–763`)

The server replies to every client heartbeat with `{timestamp: echoed_client_u32, server_ms:
server_ticks_msec & 0xFFFFFFFF}` (`:510–517`, server mode).

```
data = message.data;  if no "timestamp": return
ping_ms = elapsed_u32(data.timestamp)             # see below
if ping_ms <= 10000: stats.ping_ms = ping_ms      # else discard sample entirely (also skips clock)
else: return
server_ms = int(data.server_ms);  if server_ms == 0: return    # 0 = "not stamped"
arrival_local = Time.get_ticks_msec() & 0xFFFFFFFF
server_send_local = arrival_local − int(ping_ms / 2.0)         # float div, trunc toward zero
sample = float(server_ms − server_send_local)
if samples == 0: offset = sample
else: offset = lerp(offset, sample, 0.2)          # EMA, alpha 0.2
samples += 1
```

`_elapsed_msec_since_u32(ts)` (`:766–771`): `elapsed = (now & 0xFFFFFFFF) − (ts & 0xFFFFFFFF);
if elapsed < 0: elapsed += 4294967296`. Handles one u32 wrap (~49.7 days).

`get_server_time_ms()`: returns **0** until `samples > 0`; else
`int(round(float(now & 0xFFFFFFFF) + offset))`. Note: result is in the server's
`Time.get_ticks_msec()` domain masked to u32. *Currently no consumer in the listed files calls
this* (interpolation is tick-based, not server-clock-based), but the HUD and future
time-straddle interpolation rely on it; D2 relocates the `server_ms` payload, not the math.

#### 4.1.8 Codec — `_encode_packet` (network_manager.gd:794–904) / `_decode_packet` (`:948–1039`)

Header: `writer.write_header(type)` writes `[u8 type][u16 placeholder]`;
`finalize_header()` backfills payload length (u16 little-endian). Decode validates
`size ≥ 3` and `1 ≤ type ≤ 13` (`PacketTypes.is_valid_type`); invalid → `{}` (dropped).

Client-relevant payloads (exact field order):

| Type | Direction | Payload |
|---|---|---|
| HEARTBEAT (4) | both | `[u32 timestamp][u32 server_ms]` (client sends server_ms=0) |
| PLAYER_INPUT (1) | C→S | `[s16 pos_x×10][s16 pos_y×10][s16 vel_x][s16 vel_y][u16 input_flags][s16 aim][u8 seq][u16 client_render_tick][u16 client_rtt_ms]` = 17 B (player_input_packet.gd:79–87; position quantized 0.1 u) |
| STATE_UPDATE (2) | S→C | decoded by `StateUpdatePacket.read` → dict (see contract §6) |
| GAME_EVENT (3) | S→C | `[u8 event_type][u16 source_id][u16 target_id][event-specific]` → `GameEventPacket.read` |
| ACTION_CONFIRM (5) | S→C | `[u8 sequence_number][u8 action_type][s16,s16 corrected_position×10][u8 result_code][u16 server_tick][u8 stamina][u8 mana]` |
| CONNECT_AUTH (6) | C→S | `[str token][str character_id][str character_name][u8 region][u8 r][u8 g][u8 b][u32 bandwidth_budget_bps]` — color bytes are `clamp(round(c*255),0,255)` (`:940–943`); budget is `max(0, int(value))` |
| DISCONNECT (7) | C→S | `[u8 reason_code][u32 local_ms]` |
| REQUEST_FULL_STATE (8) | C→S | `[u32 local_ms]` (timestamp only; ignored by handlers) |
| RESPAWN_REQUEST (9) | C→S | `[u32 local_ms]` |
| SERVER_METRICS (10) | S→C | `[u32 tick_count][u16 avg_tick_ms×100][u16 max_tick_ms×100][u16 players][u16 entities][u32 bytes_sent][u32 bytes_recv][u32 avg_bw][u16 sched_deferred][u16 sched_max_age][u8 sched_at_budget_pct][u16 sched_evaluated][u16 sched_overflow]` |
| BASELINE_ACK (12) | C→S | `[u32 baseline_tick]` |
| LOCAL_HIT_REPORT (13) | C→S | `[u16 projectile_id]` |

Per **D3/D7 the wire layout is redesigned** in the Rust `protocol` crate — the layouts above
are the *current* bytes, kept here because the **decoded dictionary fields** (the GDScript-facing
shape) are the contract the rewired client code consumes (see §6).

#### 4.1.9 Server-mode behaviors that define client-visible contract (replaced by Rust)

- Heartbeat reply: on a client HEARTBEAT, the server immediately replies with the echoed
  `timestamp` and `server_ms = Time.get_ticks_msec() & 0xFFFFFFFF` (`:510–517`). The Rust
  server must provide an equivalent `server_ms` source for clock sync (D2 relocates it).
- DISCONNECT from client closes the peer with code 1000 (`:519–522`).
- Peer heartbeat timeout: 5.0 s without HEARTBEAT → server closes peer (`:224–230`).
- Per-tick batching (`begin_batch`/`flush_batches`, `:555–640`): chunks capped at 255 packets
  and 65534 inner bytes; single-packet chunks sent unwrapped. Deleted per D2, but the
  *in-order-within-tick* delivery property must be preserved on each ENet channel.

#### 4.1.10 Signals emitted (client mode)

| Signal | Args | Emitted at |
|---|---|---|
| `connected_to_server` | — | network_manager.gd:350 |
| `disconnected_from_server` | `reason: String` | :437 (user), :1045 (link closed) |
| `connection_error` | `error: String` | :362 (first-connect fail), :1061 (backoff exhausted) |
| `server_message_received` | `message_type: int, data: Dictionary` | :471 |
| `heartbeat_timeout` | — | :265 |

### 4.2 Transport seam (client role)

Abstract methods (transport.gd:95–130): `client_connect(url)->Error`, `client_poll()`,
`client_state()->LinkState`, `client_take_packets()->Array[PackedByteArray]` (drain ALL
available, FIFO), `client_send(bytes)->Error`, `client_close(code, reason)`,
`client_close_info()->{code:int, reason:String}`, `client_reset()`. Base implementations
`push_error` ("not overridden") and return error defaults — the seam fails loudly, never
silently.

WebSocketTransport client specifics: `client_connect` creates a **fresh** `WebSocketPeer`
every call (websocket_transport.gd:126–128); `client_take_packets` loops
`get_available_packet_count() > 0` (`:143–149`); null `_ws_client` → state CLOSED, send
returns `ERR_UNCONFIGURED`, take returns []. The server role generates peer ids with
**`randi()`** (`:65`) — random 32-bit, no collision guard.

### 4.3 PredictionController

#### 4.3.1 Frame loop — `_physics_process(delta)` (prediction.gd:158–198), 30 Hz, `delta` = physics delta (nominally 1/30)

```
if player_node == null: return                                   # NO visual signal
if not NetworkManager.is_server_connected():
    emit visual_position_updated(player_node.position, false); return
if not is_active():                                              # see below
    current_input_flags = 0; predicted_velocity = ZERO
    emit visual_position_updated(..., false); return

prev_flags = current_input_flags
current_input_flags = capture_input_flags()                      # 4.3.2
maybe_emit_shoot_predicted(prev_flags, current_input_flags)      # 4.3.3 (cosmetic only)
apply_local_prediction(current_input_flags, delta)               # 4.3.4
if is_correcting: apply_smooth_correction(delta)                 # 4.3.8
input_send_timer += delta
if input_send_timer >= INPUT_SEND_INTERVAL:
    send_input_to_server()                                       # 4.3.5
    input_send_timer -= INPUT_SEND_INTERVAL                      # remainder carried over
emit visual_position_updated(player_node.position, false)
```

`is_active()` (`:784–785`) = `prediction_enabled AND player_node != null AND
local_entity_id >= 0 AND has_authoritative_position`. Until the first authoritative position
arrives, **no input is sent and nothing is predicted**.

Order matters: prediction moves the node *before* the smooth-correction lerp runs in the same
frame, and the input is sent with the *post-prediction* `predicted_position`.

#### 4.3.2 Input capture (`:203–232`)

Bits set from held actions: move_up/down/left/right, shoot, ability, sprint, interact
(bits 0–7). **Dash is latched**: `Input.is_action_just_pressed("dash")` sets `_dash_latched =
true`; while latched, bit 8 is set every frame; the latch is cleared **only after a successful
`_send_input_to_server`** (`:510`), so a tap between 30 Hz sends appears in exactly one input
packet (but in possibly several *predicted* frames — the SM's own edge detection dedupes).

Aim (`_get_aim_angle`, `:235–240`): `predicted_position.angle_to_point(mouse_world)` — Godot
semantics: `atan2(mouse.y − pos.y, mouse.x − pos.x)`, radians in (−π, π]. Returns 0.0 when
`player_node == null`. Resolved fresh at every use (prediction tick and send time).

#### 4.3.3 Cosmetic shoot feedback (`:292–313`)

```
if player_node null or SHOOT bit not set: return
rising_edge = SHOOT bit not set in prev_flags
cooldown_elapsed = (now_s − _last_predicted_shot_time) >= 0.3
if not rising_edge and not cooldown_elapsed: return
_last_predicted_shot_time = now_s
aim = Vector2.from_angle(aim_angle)         # (cos, sin), unit length
muzzle = predicted_position + aim * 26.0    # 16 + 8 + 2
emit shoot_predicted(muzzle, aim)
```
Never touches `predicted_position` or the input buffer. Mirrors the server's auto-fire
cadence; the muzzle formula must match the server's projectile spawn origin.

#### 4.3.4 Local prediction (`:324–357`)

```
position_before = predicted_position
direction = direction_from_flags(flags)     # sum of unit axis components, then .normalized()
                                            #   zero vector normalizes to (0,0) — Godot semantics
sm = player_node.movement_sm if exposed else null
if sm != null:
    aim_dir = Vector2.from_angle(aim_angle)
    predicted_velocity = sm.tick(delta, direction,
        sprint_held = flags & SPRINT, dash_held = flags & DASH,
        ability_held = flags & ABILITY, attacking = flags & SHOOT, aim_dir)
else:
    predicted_velocity = direction * speed_from_flags(flags)     # stateless fallback
predicted_position = GameConstants.move_with_obstacle_collision(
    predicted_position, predicted_position + predicted_velocity * delta, 16.0)
if delta > 0.0:
    predicted_velocity = (predicted_position − position_before) / delta   # realized velocity
if not is_correcting: player_node.position = predicted_position           # visual follows
```

`speed_from_flags` (`:388–394`): if SM present, `sprint = sprint_bit AND sm.stamina > 5.0`,
return `sm.get_ground_speed(sprint)` (= 320.0 or 200.0 × haste/slow multiplier); else 320.0 if
sprint bit else 200.0.

`move_with_obstacle_collision(from, to, radius)` (game_constants.gd:525) is the **shared
analytic mover** (slides along axis-aligned obstacles and arena walls; full algorithm in the
sim-core extraction doc). It is pure (no Godot physics engine; no `move_and_slide`). Per D5
this is replaced by the same `sim_core` call on client and server.

**Parity-critical asymmetry:** the *live* prediction step uses the full SM velocity
(dash/knockback/stun included), but the *replay snapshot* (4.3.5) and *replay* (4.3.7) use the
stateless `direction × ground_speed` model only. This is deliberate (prediction.gd:386–388
comment): transient SM states are short and rarely span a correction; the next snapshot fixes
residue. A Rust port that "improves" replay to use the SM will change observable correction
behavior.

#### 4.3.5 Input send (`_send_input_to_server`, `:457–516`) — once per `INPUT_SEND_INTERVAL`

```
if not is_active() or not connected: return        # NOTE: sequence NOT advanced on early return
seq = current_sequence; current_sequence = (current_sequence + 1) & 0xFF
aim_angle = get_aim_angle()
client_render_tick = interp.render_tick & 0xFFFF   # or max(0, last_server_tick − 2) & 0xFFFF if no interp
client_rtt_ms = int(stats.ping_ms)

# replay snapshot — STATELESS model over exactly one tick interval:
replay_velocity = direction_from_flags(flags) * speed_from_flags(flags)
replay_end = move_with_obstacle_collision(predicted_position,
                 predicted_position + replay_velocity * (1/30), 16.0)
snapshot = InputSnapshot(seq, flags, before=predicted_position, after=replay_end,
                         vel=replay_velocity, aim_angle, delta=1/30)
input_buffer[seq] = snapshot; prune_acknowledged()

send PLAYER_INPUT { position: predicted_position, velocity: predicted_velocity,
                    keys: {up,down,left,right,shoot,ability,sprint,interact,dash},
                    aim_angle, sequence: seq, client_render_tick, client_rtt_ms }
_dash_latched = false
```

#### 4.3.6 Sequence arithmetic (`:425–452`)

- `_sequence_less_than(a, b)` (`:439–445`): `fwd = (b − a) & 0xFF; return 0 < fwd < 128`.
- `_is_sequence_acknowledged(seq)`: false if `last_ack_sequence < 0`; true if equal; else
  `_sequence_less_than(seq, last_ack_sequence)`.
- Prune (`:406–422`): collect all buffer keys that are acknowledged, then erase them
  (two-phase: collect keys, then erase — order irrelevant).
- Unacked collection (`_get_unacknowledged_sequences`, `:665–680`):
  `seq = (ack + 1) & 0xFF`; while `seq != current_sequence` and `safety < 256`: if in buffer,
  append; `seq = (seq+1) & 0xFF`. Returns in send order. With `ack = −1`, start is `0`.
  `current_sequence` itself (next unused) is never included.

#### 4.3.7 Server message handling and reconcile

`_on_server_message` (`:521–526`): only ACTION_CONFIRM and STATE_UPDATE.

`_handle_action_confirm(data)` (`:529–564`):
```
sequence = data.sequence_number; action_type = data.action_type
corrected = data.corrected_position; result = data.result_code; tick = data.server_tick
if action_type != MOVE(0): return
if sm != null and data has "stamina":
    sm.set_resources(float(data.stamina), float(data.mana))   # clamped 0..100 in SM
last_ack_sequence = sequence; last_server_tick = tick
if result != SUCCESS(0): reconcile(sequence, corrected)
elif not has_authoritative_position: force_sync(corrected)
elif distance(predicted_position, corrected) > 4.0: reconcile(sequence, corrected)
else: prune_acknowledged()
```

`_handle_state_update(data)` (`:567–588`):
```
last_server_tick = data.server_tick           # ALWAYS, even before local id is known
if local_entity_id < 0: return
find entity with entity_id == local_entity_id (linear scan, first match, break):
    mask = entity.delta_mask (default FULL_STATE=128)
    if is_delta and (mask & FULL_STATE)==0 and (mask & POSITION)==0: return  # no position info
    process_own_state_update(entity)
```

`_process_own_state_update(entity)` (`:591–609`):
```
server_pos = entity.position
if not has_authoritative_position: force_sync(server_pos); return
if input_buffer empty: apply_authoritative_without_replay(server_pos); return
if distance(predicted_position, server_pos) > 4.0:
    reconcile(last_ack_sequence, server_pos)      # may be −1 → replay everything buffered
```

`_reconcile(ack_sequence, server_position)` (`:614–662`) — exact order:
```
1. emit prediction_mismatch(predicted_position, server_position)
2. predicted_position = server_position; has_authoritative_position = true
3. for seq in unacked_sequences(ack_sequence): if buffered: replay_input(snapshot)
   replay_input (:683–700):
       direction = direction_from_flags(snapshot.input_flags)
       velocity  = direction * speed_from_flags(snapshot.input_flags)   # uses CURRENT sm stamina!
       before = predicted_position
       predicted_position = move_with_obstacle_collision(before, before + velocity*snapshot.delta, 16.0)
       if snapshot.delta > 0: velocity = (predicted_position − before)/snapshot.delta
       snapshot.position_after = predicted_position; snapshot.velocity = velocity   # mutated for future replays
4. visual_pos = player_node.position (or predicted_position if node null)
   correction_amount = distance(visual_pos, predicted_position)
5. if correction_amount > 150.0: instant correction
       (player_node.position = predicted_position; reset_physics_interpolation();
        emit visual_position_updated(pos, true); correction_target = predicted; is_correcting = false)
   else: smooth correction (correction_target = predicted_position; is_correcting = true)
6. emit correction_applied(correction_amount); emit reconciliation_complete(replayed_count)
7. prune_acknowledged()
```

`_apply_authoritative_position_without_replay(server_pos)` (`:827–839`):
```
disc = distance(predicted_position, server_pos)
predicted_position = server_pos; correction_target = server_pos; has_authoritative = true
if disc > 150.0: instant correction (as above)
elif disc > 4.0: start smooth correction
else: if not is_correcting: player_node.position = predicted_position
```

`force_sync(server_pos)` (`:753–766`): clear input_buffer; predicted_position =
correction_target = server_pos; predicted_velocity = ZERO; is_correcting = false;
has_authoritative_position = true; node.position = server_pos +
`reset_physics_interpolation()`; emit `visual_position_updated(pos, true)`.

#### 4.3.8 Smooth correction (`_apply_smooth_correction`, `:729–747`) — every predicted frame while `is_correcting`

```
if player_node null: is_correcting = false; return
correction_target = predicted_position                 # MOVING target, re-set every frame
new_visual = player_node.position.lerp(correction_target, 12.0 * delta)
    # Godot lerp: a + (b−a)*w, weight NOT clamped — at 30 Hz w = 0.4
if distance(new_visual, correction_target) < 1.0:
    player_node.position = correction_target; is_correcting = false
else:
    player_node.position = new_visual
```

`set_prediction_enabled(enabled)` (`:800–809`): on toggle, zero flags + velocity + timer,
clear input_buffer, stop correcting. `set_local_entity_id(id)` (`:818–819`) sets the id (the
arena calls it on PLAYER_INFO). `get_rendered_position()` (`:793–796`) returns
`player_node.position` (trails predicted during smooth correction) — used by the local hit
detector; must remain the *rendered* (not predicted) position per D11.

### 4.4 InterpolationController

#### 4.4.1 Frame loop — `_physics_process(delta)` (interpolation_controller.gd:126–150), 30 Hz

```
if entity_buffers empty: return
if not connected: return
if _full_state_request_time > 0 and (now_ms − _full_state_request_time) > 2000:
    request_full_state_sync()                  # retry; gives up after 3, then clear_all_entities()
tick_accumulator += delta
tick_progress = clamp(tick_accumulator / estimated_tick_interval, 0.0, 1.0)
interpolate_all_entities(tick_progress)
```

#### 4.4.2 Snapshot intake — `_process_state_update(data)` (`:162–278`)

```
server_tick = data.server_tick (fallback key "tick", default 0)
entities = data.entities; state_flags = data.state_flags; baseline_tick = data.baseline_tick
is_delta    = state_flags & 1
is_baseline = state_flags & 2

if is_baseline:
    last_baseline_tick = server_tick
    _full_state_request_time = 0; _full_state_retry_count = 0; needs_full_state_sync = false
    send BASELINE_ACK { baseline_tick: server_tick }    # ack the SNAPSHOT's tick, NOT data.baseline_tick
elif is_delta:
    if baseline_tick != last_baseline_tick and last_baseline_tick > 0:
        needs_full_state_sync = true; request_full_state_sync()   # broken delta chain
        # NOTE: the packet is still processed below — not dropped

if server_tick > current_server_tick:                    # strictly newer only
    if last_update_time_ms > 0:
        time_delta_ms = now_ms − last_update_time_ms
        tick_delta = server_tick − current_server_tick
        if tick_delta > 0 and time_delta_ms > 0:
            measured = time_delta_ms / 1000.0 / tick_delta            # seconds per tick
            estimated_tick_interval = lerp(estimated_tick_interval, measured, 0.1)
            # deviation vs the ALREADY-UPDATED estimate (order is load-bearing):
            interval_dev_ms = |measured − estimated_tick_interval| * 1000.0
            estimated_jitter_ms = lerp(estimated_jitter_ms, interval_dev_ms, 0.1)
            interval_ms = max(estimated_tick_interval * 1000.0, 0.001)
            target_ticks = clamp((interval_ms + 2.0*estimated_jitter_ms) / interval_ms, 1.0, 3.0)
            adapt_rate = 0.5 if target_ticks > render_delay_ticks_smooth else 0.05
            render_delay_ticks_smooth = lerp(render_delay_ticks_smooth, target_ticks, adapt_rate)
    current_server_tick = server_tick
    render_tick = max(0, server_tick − roundi(render_delay_ticks_smooth))
        # roundi = round half away from zero (2.5→3)
    tick_accumulator = 0.0
    last_update_time_ms = now_ms

entities_in_last_update.clear()
local_id = GameManager.get_local_player_entity_id()
for entity_data in entities:
    id = entity_data.entity_id (default −1); if id < 0: continue
    mask = entity_data.delta_mask (default FULL_STATE)
    if is_delta and (mask & REMOVED): explicit_despawn(id); continue
    if id == local_id: continue                      # prediction owns the local player
    entities_in_last_update[id] = true
    state = reconstruct_entity_state(entity_data, is_delta)     # 4.4.3
    if id not in entity_buffers: handle_spawn(...)              # 4.4.4
    else: handle_update(...)                                    # 4.4.4
    entity_last_states[id] = copy of {entity_type, position, animation_state, flags}

if not is_delta: check_for_despawns()                           # 4.4.5
```

#### 4.4.3 Delta reconstruction (`_reconstruct_entity_state`, `:282–318`)

```
if not is_delta or (mask & FULL_STATE): return fields as-received
  (defaults: entity_type=PLAYER(1), position=(0,0), animation_state=IDLE(0), flags=0)
else:
  last = entity_last_states.get(id, {})              # may be {} if state was never stored
  result = { entity_type: last.entity_type ?? received entity_type ?? PLAYER,
             position:  last.position ?? (0,0),
             animation_state: last.animation_state ?? IDLE,
             flags: last.flags ?? 0 }
  if mask & POSITION:  result.position = received position (?? keep)
  if mask & ANIMATION: result.animation_state = received (?? keep)
  if mask & FLAGS:     result.flags = received (?? keep)
```
A delta for an entity with no prior `entity_last_states` entry silently resolves
unspecified fields to defaults — position `(0,0)`. The teleport guard usually rescues this,
but it is observable behavior.

#### 4.4.4 Spawn / update (`:361–422`)

Spawn (`:361–384`): create `EntityStateBuffer.create_for_entity(id)`, `add_snapshot(tick,
pos, anim, flags, type)`, `entity_buffers[id] = buffer`, `missing_update_count[id] = 0`, emit
`entity_spawned(id, type, pos)`.

Update (`:387–422`):
```
last_pos = buffer.get_latest_position()
if distance(last_pos, new_pos) > 150.0:                 # strict >
    buffer.clear()                                      # spawn_tick preserved
    emit entity_teleported(id, last_pos, new_pos)
    if node registered and valid: node.position = new_pos; node.reset_physics_interpolation()
buffer.add_snapshot(tick, new_pos, anim, flags, type)   # added AFTER clear on teleport
missing_update_count[id] = 0
```

#### 4.4.5 Despawn paths

- Implicit (full snapshots only, `_check_for_despawns`, `:425–441`): every buffered id not in
  `entities_in_last_update` gets `missing_update_count += 1` and `buffer.despawn_pending =
  true`; at count ≥ 3 → `_despawn_entity(id)`. **Never runs for delta snapshots.**
- `_despawn_entity(id)` (`:444–457`): erase from `entity_buffers`, `missing_update_count`,
  `entity_last_states`, `entity_nodes`; emit `entity_despawned(id)` (node destruction is the
  ClientEntityManager's job).
- Explicit (`DELTA_MASK_REMOVED`, `:460–466`): if buffered → `_despawn_entity`; else erase
  any residue from the three maps without emitting.
- `forget_entity(id)` (`:471–475`): erase from all four maps, **no signal** — used when a
  pre-auth local-player snapshot was briefly classified as remote
  (client_entity_manager.gd:132–135).
- `clear_all_entities()` (`:661–677`): emits `entity_despawned` for every buffered id, then
  clears all maps and resets `current_server_tick`, `render_tick`, `last_baseline_tick`,
  full-state tracking to 0/false.

#### 4.4.6 Render interpolation (`_interpolate_all_entities` `:480–499`, `_calculate_interpolated_position` `:502–550`)

For each buffered entity with a registered, valid node (invalid nodes are unregistered
lazily): `node.position = calculate(buffer, tick_progress)`; emit `entity_position_updated`.

```
calculate(buffer, tick_progress):
    [before, after, factor] = buffer.get_interpolation_data(render_tick)
    if before == null: return buffer.get_latest_position()
    if after == null:
        if factor >= 1.0:                           # render_tick is past newest snapshot
            ticks_past = render_tick − before.server_tick
            if ticks_past <= 2: return buffer.extrapolate_position(render_tick)
            else: return before.position             # freeze
        else: return before.position                 # before-all-snapshots case (factor 0.0)
    base = before.position.lerp(after.position, factor)
    if tick_progress > 0.0:
        [nb, na, nf] = buffer.get_interpolation_data(render_tick + 1)
        if nb != null:
            next = nb.position.lerp(na.position, nf) if na != null else nb.position
            return base.lerp(next, tick_progress)    # sub-tick blend
    return base
```
Note the dead branch: when `before == null` and `after != null`, `get_interpolation_data`
returns `[after, null, 0.0]` — i.e. "before" is actually the *earliest future* snapshot and
factor 0.0 → snap to it.

Public getters (`:582–657`): `get_entity_position` (same bracket math, **no** sub-tick blend,
returns `(0,0)` if unknown), `get_entity_latest_server_position`,
`get_entity_animation_state` (latest, default IDLE), `get_entity_flags` (latest, default 0),
`get_entity_type` (latest, default PLAYER), `has_entity`, `get_all_entity_ids`,
`get_entities_by_type`.

`register_entity_node(id, node)` (`:556–570`): warns + refuses if no buffer; sets
`node.position = buffer.get_latest_position()` and `reset_physics_interpolation()`.

#### 4.4.7 Full-state re-sync (`_request_full_state_sync`, `:334–356`)

```
if not connected: return
if _full_state_retry_count >= 3:
    warn; clear_all_entities(); reset tracking (time=0, count=0, needs=false); return
_full_state_request_time = now_ms; _full_state_retry_count += 1
send REQUEST_FULL_STATE {}
```
Triggered by: broken delta chain (4.4.2) and timeout retry (4.4.1). Reset by any baseline.

### 4.5 EntityStateBuffer

#### `add_snapshot(server_tick, position, animation_state, flags, entity_type) -> bool` (`:104–153`)

```
is_spawn = (spawn_tick < 0); if is_spawn: spawn_tick = server_tick
if server_tick == last_tick_added: return false        # EQUALITY-ONLY duplicate drop;
                                                       # an OLDER tick is accepted and stored!
if last_tick_added >= 0 and snapshot_count > 0:
    prev = most_recent_snapshot()
    tick_delta = server_tick − last_tick_added
    time_delta = now_ms − prev.timestamp_ms
    if tick_delta > 0 and time_delta > 0:
        estimated_tick_interval_ms = lerp(est, time_delta / tick_delta, 0.1)   # never consumed
snapshots[write_index] = new EntitySnapshot(tick, now_ms, pos, anim, flags, type)
write_index = (write_index + 1) % 5
snapshot_count = min(snapshot_count + 1, 5)
last_tick_added = server_tick
despawn_pending = false
return is_spawn
```

#### `get_interpolation_data(render_tick) -> [before, after, factor]` (`:160–195`)

Linear scan over all 5 slots (null slots skipped):
- `before` = snapshot with the **highest** tick ≤ render_tick.
- `after` = snapshot with the **lowest** tick > render_tick.
Returns:
- no snapshots → `[null, null, 0.0]`
- `before == null` → `[after, null, 0.0]` (render before all data)
- `after == null` → `[before, null, 1.0]` (render past all data; 1.0 signals "extrapolate")
- both → `range = after.tick − before.tick`; if `range <= 0` → `[after, null, 1.0]`
  (defensive; unreachable given the selection); else
  `[before, after, clamp((render_tick − before.tick)/range, 0.0, 1.0)]` (float division).

#### `extrapolate_position(target_tick) -> Vector2` (`:262–294`)

```
if snapshot_count < 2: return latest position (or (0,0) if none)
second = newest snapshot; first = second-newest        # single-pass selection, see below
if first == null or second == null: return second.position (or (0,0))
tick_delta = second.tick − first.tick; if tick_delta <= 0: return second.position
velocity = (second.position − first.position) / float(tick_delta)   # units per tick
return second.position + velocity * float(target_tick − second.tick)
```
Selection pass (`:271–280`): for each non-null snapshot: if `second == null or tick >
second.tick`: `first = second; second = snapshot`; elif `first == null or tick > first.tick`:
`first = snapshot`. (Order-dependent on slot order but yields the two highest ticks since all
ticks are distinct.)

#### `clear()` (`:243–249`)

Null all slots, `write_index = 0`, `snapshot_count = 0`, `last_tick_added = −1`;
**`spawn_tick` is intentionally NOT reset** (same entity).

`_get_most_recent_snapshot` (`:199–209`): highest-tick scan, ties impossible (duplicates
dropped). All `get_latest_*` helpers fall back to defaults (position `(0,0)`, type PLAYER,
anim IDLE, flags 0) when empty.

### 4.6 ClientEntityManager

Spawn dispatch is **by `entity_type` from the packet, not by id range**
(`_on_entity_spawned`, client_entity_manager.gd:107–117). Despawn dispatch is by membership
lookup in the three maps, in order player → monster → projectile (`:121–127`).

- **Remote player** (`:131–162`): if `entity_id == GameManager.get_local_player_entity_id()`
  → `interpolation_controller.forget_entity(id)` and bail (pre-auth misclassification
  recovery). Else instantiate `remote_player.tscn`, set `entity_id`/`position`, apply cached
  name + color from `EntityNameCache`, add to container, register node with the interpolator.
- **Monster** (`:185–214`): instantiate, connect `took_damage`/`died` signals (audio/fx),
  add, play spawn audio + particles, register node.
- **Projectile** (`:265–293`): from a 64-deep pool. Pool slots are pre-instantiated disabled/
  invisible/non-monitoring nodes (`:90–103`). On spawn: position, reset color,
  `process_mode = DISABLED` (the **server controls movement** — the node is moved only by the
  interpolator writing `position`), visible, collision monitoring off, record in
  `_active_projectiles` + append id to `_active_projectile_order`, apply owner color if known,
  register node. Pool exhaustion (`:324–337`): evict the **oldest active** id
  (`_active_projectile_order[0]`) via `_despawn_projectile`, then pop from pool; if still
  empty return null (spawn silently skipped).
- **Despawn projectile** (`:297–320`): erase from maps + order array + `_projectile_sources`;
  unregister node; reset visual/collision state; return to pool (duplicate-push guarded).
- `apply_monster_damage(id, amount)` (`:238–246`): guard `amount > 0` and known id;
  `monster.set_hp(max(hp − amount, 0))` — local feedback for authoritative DAMAGE events.
- `apply_monster_death(id)` (`:250–261`): hp = 0, hide, play death effects once
  (`_dead_monster_effects_played` latch).
- `update_entity_visuals()` (`:350–383`): per frame, for players and monsters: pull latest
  anim/flags from the interpolator, call `update_from_network(anim, flags)`; on player anim
  *transition* play audio (HIT/DEATH) and sparks on HIT. Invalid (freed) nodes are erased
  lazily during iteration (safe in GDScript: `keys()` returns an array copy).
- `register_projectile_source(projectile_id, source_entity_id)` (`:506–510`): guards both
  ids > 0; records source; applies owner color (player-owned only: `0 < source < 30000`).
  Fed by authoritative `PROJECTILE_FIRED` events (arena layer).
- `get_monster_projectile_snapshots()` (`:517–527`): for D11's local hit detection — returns
  `[{id, position}]` for active projectiles whose source satisfies
  `HitAuthority.is_client_authoritative(source_id)` (= `source_id >= 30000`; unknown source
  (−1) excluded) **and** whose node is valid and `visible` (a locally-consumed hidden bullet
  is excluded by construction).
- `hide_projectile_locally(id)` / `show_projectile_locally(id)` / `is_projectile_active(id)`
  (`:533–552`): visibility toggles + liveness query used by the local hit report
  recovery loop (rejected/lost report ⇒ bullet must be re-shown or it becomes permanently
  undetectable).
- `clear_all()` (`:387–421`): free players + monsters, return all projectiles to pool, clear
  every map.

---

## 5. Edge cases & gotchas

**NetworkManager**
1. `get_server_time_ms()` returns **0** as the "no sync yet" sentinel; legitimate values are
   never 0 in practice but a port must keep the sentinel.
2. A heartbeat reply with `ping_ms > 10000` is discarded for **both** RTT and clock offset; a
   reply with `server_ms == 0` updates RTT but not the clock.
3. `int(ping_ms / 2.0)` truncates toward zero (GDScript `int()` of float).
4. Heartbeat send timer resets to exactly `0.0` (no remainder carry), unlike the prediction
   input timer which carries remainder (`-= INTERVAL`).
5. `disconnect_from_server` does **not** schedule a reconnect; an unexpected CLOSED link does
   (if `_had_successful_connection`). Both emit `disconnected_from_server`.
6. `_fail_connection_attempt` closes with code 1000 even when the socket never opened, then
   `client_reset()` (drops the WebSocketPeer object). Stale async waiters are neutralized by
   the attempt-id check, not by cancellation.
7. Undersized (<3 B) packets, unknown types (outside 1..13) and decode failures are silently
   dropped (logged).
8. A nested BATCH inside a BATCH would recurse (server never produces one). BATCH truncation
   guards abort the remainder, not the already-dispatched prefix.
9. Server-mode peer ids come from `randi()` with no collision check
   (websocket_transport.gd:65); they are transport-scoped and unrelated to entity ids.
10. `Time.get_ticks_msec()` is monotonic ms since engine start (no wall clock); all `& 0xFFFFFFFF`
    masks wrap at ~49.7 days. `stats.ping_ms` is a float assigned from an int elapsed.
11. `_dispatch_received_buffer` treats a decoded message lacking `"type"` as HEARTBEAT
    (`message.get("type", MessageType.HEARTBEAT)`) — unreachable today since decode always
    sets it, but the default exists.

**Prediction**
12. `max_buffer_size` (export, 256) is **never enforced**. The dictionary is bounded only by
    the 8-bit key space: after 256 unacked sends (~8.5 s) a wrapped sequence **silently
    overwrites** the old snapshot under the same key. There is no overflow error.
13. `last_ack_sequence = −1` start: `_get_unacknowledged_sequences(−1)` begins at seq 0;
    `_reconcile` driven from `_process_own_state_update` can therefore replay the entire
    buffer before any ack ever arrived.
14. Replay uses the **stateless** ground-speed model (no dash/knockback/SM state) and the
    **current** SM stamina at replay time (not the stamina at the original input) — see
    4.3.4. Sprint gating during replay can therefore differ from the live prediction that
    produced the snapshot.
15. The `delta` recorded in every snapshot is exactly `INPUT_SEND_INTERVAL` (1/30), not the
    real frame delta; the server applies one input per tick so replay matches authority, not
    the client's own live integration (which used per-frame `delta`). Live prediction and the
    stored replay path intentionally disagree at sub-tick granularity.
16. Zero input: `direction_from_flags(0)` → `Vector2.ZERO.normalized()` → `(0,0)` (Godot
    returns ZERO for zero-length normalize — Rust must not NaN here). Velocity becomes (0,0);
    the mover is still called with `from == to` and must return `from`.
17. `_apply_smooth_correction` lerp weight `12.0 * delta` is **unclamped** — if a physics
    frame ever exceeded 1/12 s the visual would overshoot the target (Godot `lerp` does not
    clamp the weight). At the fixed 30 Hz physics rate the weight is 0.4.
18. Smooth-correction completes by **distance** (<1.0 u to a target that moves every frame);
    while correcting, `_update_player_visual` is suppressed so the corrector owns the node.
19. Death/respawn is not special-cased here: the arena toggles
    `set_prediction_enabled(false/true)` and `force_sync` on RESPAWN. Disconnect: prediction
    keeps state but `is_server_connected()` gates the whole loop (only the visual signal
    keeps firing).
20. `_physics_process` with `player_node == null` returns **without** emitting
    `visual_position_updated` (consumers must not assume a signal every frame).
21. ACTION_CONFIRM with `action_type != 0` is ignored entirely (no ack-tracking update).
22. Stamina/mana from ACTION_CONFIRM are u8 (0–255) on the wire but clamped to 0..100 by
    `set_resources` (`clampf` + `is_equal_approx` change detection).

**Interpolation**
23. Out-of-order snapshot intake: the controller's tick state only advances on **strictly
    newer** `server_tick`, but entity buffers accept any tick except an exact duplicate of
    `last_tick_added` (equality-only check, entity_state_buffer.gd:118). On today's TCP this
    can't happen; over ENet ch0 (unreliable-**sequenced**) stale datagrams are dropped by the
    transport, so the port keeps equivalence — but if the channel were plain unreliable, an
    older tick would be written into the ring and could corrupt bracketing.
24. Broken delta chain: the offending delta packet is **still applied** (against the stale
    last-known states) while the full-state request goes out; recovery overwrites on the next
    baseline.
25. Delta packet for an unknown entity with only e.g. the ANIMATION bit set spawns the entity
    at position `(0,0)` (defaults from 4.4.3). The server's spawn path always sends
    FULL_STATE for new entities, so this is defensive-only behavior.
26. The despawn counter runs **only on full (non-delta) snapshots**, so an entity that leaves
    AoI is removed either by `DELTA_MASK_REMOVED` (delta mode) or after 3 consecutive full
    snapshots without it. `missing_update_count` increments once per full snapshot received,
    not per tick.
27. `clear_all_entities` emits `entity_despawned` for every entity (the entity manager frees
    nodes); `forget_entity` emits nothing.
28. Teleport (>150.0 u, strict) clears the position history but keeps `spawn_tick`; the new
    snapshot is added *after* the clear, so for one tick there is exactly one snapshot and
    rendering snaps/extrapolates from it.
29. `render_tick` can go to 0 (clamped via `max(0, …)`) at session start; `render_tick + 1`
    in the sub-tick blend can exceed the newest snapshot, in which case the "next" position
    resolves through the same bracket logic (extrapolation is **not** invoked by the
    sub-tick path — it returns `nb.position` when `na == null`; the `factor>=1` check only
    happens in the primary lookup).
30. Division guards: `tick_progress` divides by `estimated_tick_interval` (seeded 1/30, EMA
    toward measured > 0 — can never reach 0); the adaptive-delay math floors `interval_ms` at
    0.001; bracket factor divides by `range` only after `range > 0`; extrapolation divides by
    `tick_delta` only after `> 0`. The jitter EMA's deviation is computed against the
    **post-update** interval estimate — preserving this order matters for numeric parity.
31. The `interpolation_speed` export on the controller is dead config (never read).
32. `estimated_tick_interval_ms` inside EntityStateBuffer is calibrated but never consumed —
    do not port it as load-bearing.

**ClientEntityManager**
33. Entity classification for visuals comes from the packet `entity_type`, not id ranges; id
    ranges (players 1–999, projectiles 10000–29999, monsters 30000–39999) are used only by
    `_apply_projectile_color` (`source < 30000` ⇒ player-owned) and
    `HitAuthority.is_client_authoritative` (`>= 30000` ⇒ monster-owned ⇒ client-authoritative
    hit detection per D11).
34. Projectile pool exhaustion evicts the oldest active projectile (visual recycling under
    burst), and if eviction frees nothing the spawn is skipped with a warning — the entity
    still exists in the interpolator (buffer without node; position lookups work, nothing
    renders).
35. A projectile hidden by a local hit report stays in `_active_projectiles` (still "active")
    until the server's authoritative removal; `is_projectile_active` distinguishes
    "server confirmed (gone)" from "rejected/lost (still active)".
36. Erasing dictionary entries while iterating `keys()` is safe in GDScript because `keys()`
    returns a snapshot array; a Rust `HashMap` port must collect keys first or use
    `retain`.
37. Monster death effects are guaranteed once per entity id via
    `_dead_monster_effects_played`; the latch is erased on despawn, so an id **reused** by
    the server could replay effects (server monster ids 30000–39999 recycle).

---

## 6. Cross-subsystem contracts

### 6.1 Decoded packet dictionaries this subsystem consumes (from the codec)

These field names/types are the GDScript-facing shape the rewired client keeps even after the
codec moves into the Rust extension (D6/D7) — the extension must return equivalent
Dictionaries (or typed objects with the same data):

- **STATE_UPDATE** → `{ "server_tick": int, "state_flags": int, "baseline_tick": int,
  "entities": Array[Dictionary] }` where each entity dict carries
  `{ "entity_id": int, "entity_type": int (1|2|3), "position": Vector2,
  "animation_state": int (0..6), "flags": int (u8), "delta_mask": int (u8) }`. Positions are
  dequantized (wire 0.1 u → float). `delta_mask` defaults to `FULL_STATE` when absent.
  (Consumed: interpolation_controller.gd:163–268, prediction.gd:567–588.)
- **ACTION_CONFIRM** → `{ "sequence_number": int (0–255), "action_type": int (0..3),
  "corrected_position": Vector2, "result_code": int (0..5), "server_tick": int (u16),
  "stamina": int (0–255), "mana": int (0–255) }`. (Consumed: prediction.gd:529–564.)
- **GAME_EVENT** → `{ "event_type": int, "source_id": int, "target_id": int, …event
  fields… }` (consumed by ArenaBase/EntityNameCache — outside this doc's files, but the
  dispatch goes through the same signal).
- **SERVER_METRICS** → the 13 fields of §4.1.8 (consumed by `server_status.gd:121`).
- **HEARTBEAT** → `{ "timestamp": int(u32), "server_ms": int(u32) }` — intercepted inside
  NetworkManager, never re-emitted.

### 6.2 Outbound packets this subsystem produces

| Packet | Producer (file:line) | Fields |
|---|---|---|
| PLAYER_INPUT | prediction.gd:507 → network_manager.gd:718 | `position: Vector2, velocity: Vector2, keys: {up,down,left,right,shoot,ability,sprint,interact,dash}: bool, aim_angle: float, sequence: int(0–255), client_render_tick: int(u16), client_rtt_ms: int(u16)` |
| CONNECT_AUTH | network_manager.gd:372–406 (driven by arena_base.gd:221, 987) | `token, character_id, character_name, region, player_color, bandwidth_budget_bps` |
| BASELINE_ACK | interpolation_controller.gd:185 | `baseline_tick = the baseline snapshot's server_tick` |
| REQUEST_FULL_STATE | interpolation_controller.gd:350–353; arena_base.gd:222, 988 | `{}` |
| RESPAWN_REQUEST | arena_base.gd:800 | `{}` |
| LOCAL_HIT_REPORT | local_hit_detector.gd:123–126 | `projectile_id: int(u16)` |
| HEARTBEAT | network_manager.gd:722–725 | `timestamp` (deleted per D2; clock-sync payload relocates) |
| DISCONNECT | network_manager.gd:431 | `reason: int(u8)` |

### 6.3 `server_message_received` listeners (the dispatch fan-out the port must rewire)

| Listener | Connect site | Types handled | Mutates |
|---|---|---|---|
| `PredictionController._on_server_message` | prediction.gd:127–128 | ACTION_CONFIRM, STATE_UPDATE | `last_ack_sequence`, `last_server_tick`, `predicted_position`, `input_buffer`, SM stamina/mana, `player_node.position`, correction state |
| `InterpolationController._on_server_message` | interpolation_controller.gd:119–120 | STATE_UPDATE | `entity_buffers`, `entity_last_states`, `entities_in_last_update`, `current_server_tick`, `render_tick`, interval/jitter/delay estimates, baseline tracking; sends BASELINE_ACK / REQUEST_FULL_STATE |
| `ArenaBase._on_server_message` | arena_base.gd:209 (handler :355–361) | GAME_EVENT (PLAYER_INFO, RESPAWN, DAMAGE, KILL_PVP, PROJECTILE_FIRED, LEADERBOARD_UPDATE, …), STATE_UPDATE (local-player concerns: HP, death) | local player node, HUD, `ClientEntityManager` (damage/death/projectile-source), prediction id + force_sync |
| `ServerStatus._on_server_message` | server_status.gd:22–23 (handler :121) | SERVER_METRICS | HUD text only |
| `EntityNameCache._on_server_message` | entity_name_cache.gd:32–33 (filter :40, type==3) | GAME_EVENT / PLAYER_INFO | name + color cache; emits `entity_color_updated` |

### 6.4 Sim functions this subsystem calls (the D5 seam)

| Call | Signature (GDScript) | Used by |
|---|---|---|
| `GameConstants.move_with_obstacle_collision` | `static (from: Vector2, to: Vector2, radius: float) -> Vector2` (game_constants.gd:525) | prediction.gd:349–353, 470–474, 690–694 |
| `MovementStateMachine.tick` | `(delta: float, move_dir: Vector2, sprint_held: bool, dash_held: bool, ability_held: bool, attacking: bool, aim_dir: Vector2) -> Vector2` (movement_state_machine.gd:88) | prediction.gd:336–343 |
| `MovementStateMachine.get_ground_speed` | `(is_sprinting: bool) -> float` (movement_state_machine.gd:344) | prediction.gd:393 |
| `MovementStateMachine.set_resources` | `(new_stamina: float, new_mana: float) -> void` (clamps 0..100) (movement_state_machine.gd:379) | prediction.gd:548 |
| `MovementStateMachine.stamina` | `float` field read | prediction.gd:392 |
| `HitAuthority.is_client_authoritative` | `static (owner_id: int) -> bool` = `owner_id >= 30000` (hit_authority.gd:17–18) | client_entity_manager.gd:521 |

### 6.5 Other dependencies

- `GameManager.get_local_player_entity_id() -> int` (−1 sentinel until PLAYER_INFO) —
  interpolation_controller.gd:234, client_entity_manager.gd:132, 567.
- `GameManager.player_data: Dictionary` — auth fields + `player_color` +
  `bandwidth_budget_bps` (network_manager.gd:387–392, 415–417).
- `EntityNameCache.get_entity_name/get_entity_color/entity_color_updated` —
  client_entity_manager.gd:58–59, 148–150, 566–569.
- `NetworkManager.get_stats()["ping_ms"]` — prediction.gd:463–465 (`client_rtt_ms` field).
- Signals provided to the arena/HUD: `PredictionController.{correction_applied,
  prediction_mismatch, reconciliation_complete, visual_position_updated, shoot_predicted}`;
  `InterpolationController.{entity_spawned, entity_despawned, entity_position_updated,
  entity_teleported}`.
- Godot engine services used: `Input.is_action_pressed/just_pressed`,
  `Node2D.get_global_mouse_position()`, `Node2D.reset_physics_interpolation()` (suppresses
  the engine's render-side physics interpolation across discontinuities — every hard
  snap/teleport/registration calls it), `Time.get_ticks_msec()`, scene-tree timers.

---

## 7. Rust port hazards (checklist)

1. **Float semantics.** `Vector2` stores float32 components; GDScript intermediate arithmetic
   is float64. `sim_core` (D5) must pick ONE representation for both prediction and authority
   — that is the whole point of D5; the snap-rate monitor (D12) is the regression alarm.
   `lerpf(a,b,w) = a + (b−a)*w` with **no weight clamping**; `Vector2.lerp` likewise
   per-component. `clampf`, `maxi/mini`, `absf` are ordinary; `roundi` rounds **half away
   from zero** (Rust `f32::round` matches; `(x+0.5).floor()` does not for negatives).
2. **`Vector2.ZERO.normalized() == ZERO`** — Godot returns the zero vector; a naive Rust
   `v / v.length()` yields NaN. Zero-input frames hit this every time (§5.16).
3. **`angle_to_point`** = `atan2(to.y − from.y, to.x − from.x)`; y is **down-positive**
   (screen coords); `Vector2.from_angle(a) = (cos a, sin a)`.
4. **Frame vs tick timing.** NetworkManager pumps in `_process` (render rate, variable);
   prediction/interpolation run in `_physics_process` (fixed 30 Hz). Input send cadence
   carries remainder (`timer -= INTERVAL`); heartbeat does not (`timer = 0.0`). The replay
   snapshot delta is the constant 1/30 even though live prediction integrates with the real
   physics delta.
5. **Sequence wraparound.** 8-bit space, half-window 128 comparison
   (`(b−a) & 0xFF < 128`), buffer keyed by sequence — wrap silently overwrites (§5.12). Port
   the comparison exactly; do not "fix" it to 16-bit without changing the wire + ack both
   sides.
6. **Replay model asymmetry** (§5.14–15): replay = stateless `direction × ground_speed ×
   (1/30)` through the obstacle mover; live prediction = full SM velocity × real delta. Both
   call the same mover. Keep both paths; do not unify.
7. **Reconcile order of operations** (4.3.7): snap → replay → measure visual distance →
   choose instant (>150) vs smooth → emit → prune. Stamina/mana apply BEFORE the ack update;
   `last_ack_sequence`/`last_server_tick` update before the drift check.
8. **Epsilons are strict `>`**: 4.0 (drift), 150.0 (teleport, both subsystems), 1.0
   (correction stop), 0.3 s cooldown is `>=`.
9. **Clock sync math** (4.1.7): u32 masking, negative-wrap correction (+2^32), truncating
   `int(ping/2.0)`, 10000 ms sanity rejection (rejects RTT *and* clock sample), `server_ms ==
   0` sentinel, EMA α=0.2 with first-sample override, `get_server_time_ms()==0` sentinel.
   Under D2 the `server_ms` source relocates (HEARTBEAT is deleted) and RTT comes from
   ENet (`ENetPacketPeer.get_statistic(PEER_ROUND_TRIP_TIME)`); keep the offset filter
   behavior identical.
10. **Adaptive render delay** (4.4.2): EMA order is load-bearing — interval EMA updates
    first, deviation measured against the *updated* estimate, jitter EMA second, asymmetric
    adapt rate (0.5 grow / 0.05 shrink) compares against the **pre-update** smooth value.
    `roundi` of the smoothed value picks the integer delay; `max(0, …)` clamps render_tick.
11. **Snapshot intake under UDP.** The buffer's duplicate check is equality-only (§5.23);
    correctness relies on the transport never delivering an older snapshot after a newer one.
    ENet ch0 **must be sequenced** (drop-stale), exactly per the D2 channel plan, or the ring
    can store regressing ticks.
12. **Despawn semantics differ by snapshot mode** (§5.26): counter only in full mode;
    explicit `DELTA_MASK_REMOVED` in delta mode. The Rust server must keep emitting REMOVED
    markers or remote corpses linger.
13. **Delta reconstruction defaults** (§5.25): missing last-known state resolves to position
    (0,0), type PLAYER, anim IDLE, flags 0 — defensive but observable.
14. **`reset_physics_interpolation()`** must be called on every hard position discontinuity
    (instant correction, force_sync, teleport snap, node registration) — the project runs
    with `physics_interpolation=true`; omitting it makes the engine visually lerp across
    snaps. This is engine-side; the extension cannot do it — the GDScript glue keeps it.
15. **`move_and_slide` is NOT used by prediction.** The mover is the analytic
    `move_with_obstacle_collision` (pure function — slides along obstacle edges, stops at
    arena walls). The legacy `Player.gd` `move_and_slide` path is the known invariant
    violation (AGENTS.md) and must NOT be replicated; `sim_core` reimplements only the
    analytic mover.
16. **Dictionary semantics.** GDScript `Dictionary.keys()` returns a snapshot (safe erase
    during iteration); insertion order is preserved but no algorithm here requires it.
    Variant `.get(key, default)` patterns: missing key ⇒ default — port to
    `unwrap_or(default)`, not panics.
17. **Signal fan-out is synchronous and in connection order** — prediction connects in its
    `_ready`, interpolation in its own; the arena creates interpolation first
    (arena_base.gd:200) then connects its handler (:209). No handler depends on relative
    order today (they touch disjoint state), but the BASELINE_ACK send happens *inside* the
    STATE_UPDATE dispatch — re-entrant sends from handlers must be legal in the port.
18. **Sentinels**: `local_entity_id = −1`, `last_ack_sequence = −1`,
    `last_tick_added/spawn_tick = −1`, `_full_state_request_time = 0`,
    `server_clock_offset_samples = 0`, `_last_predicted_shot_time = −INF`,
    `_projectile_sources.get(...) = −1`.
19. **u16 truncation**: `client_render_tick & 0xFFFF` — server ticks exceed 65535 after ~36
    minutes; the lag-comp consumer must un-wrap the same way the GDScript server does today.
20. **`int()` casts** truncate toward zero (`client_rtt_ms`, budget); wire clamps:
    `clampi(rtt, 0, 65535)`, `maxi(0, budget)`, color `clampi(roundi(c*255), 0, 255)`,
    ACTION_CONFIRM stamina/mana `clampi(v, 0, 255)`.

---

## 8. PORT PLAN — every call site that must change

Per D2 (ENet, 3 channels), D6 (codec in the Rust GDExtension, no GDScript codec), D5/D11
(prediction + hit predicates call `sim_core` through the extension). Channel plan recap (D2):
**ch0** unreliable-sequenced = STATE_UPDATE (+ ACTION_CONFIRM); **ch1** reliable-ordered =
GAME_EVENT, CONNECT_AUTH, DISCONNECT, BASELINE_ACK, REQUEST_FULL_STATE, RESPAWN_REQUEST,
LOCAL_HIT_REPORT (one-shot, must-arrive ⇒ reliable); **ch2** unreliable-sequenced =
PLAYER_INPUT. HEARTBEAT and BATCH are deleted.

### (a) ENetConnection transport

| Call site | Today | Change |
|---|---|---|
| `client/autoload/transport/transport.gd` (whole file) | abstract seam | Replace with an ENet-shaped seam or delete: the seam's "drain FIFO packets" contract becomes "drain (channel, bytes) events"; LinkState maps from ENet connect/disconnect events. |
| `client/autoload/transport/websocket_transport.gd` (whole file) | WebSocketPeer/TCPServer | Delete. New `enet_transport.gd` using `ENetConnection.create_host()` + `connect_to_host(ip, port)` + `service()`; map `ENetConnection.EVENT_CONNECT/DISCONNECT/RECEIVE`. Server role deleted entirely (Rust owns it). |
| network_manager.gd:49–50 | `const Transport/WebSocketTransport := preload(...)` | Point at the ENet transport implementation. |
| network_manager.gd:145–146 | `_transport = WebSocketTransport.new(); role = …` | Instantiate ENet transport; server role removed (the binary no longer self-hosts — `_initialize_server` :156–167 and the whole server branch :196–230 die). |
| network_manager.gd:202–230 (`_process_server`) | server poll loop | Delete (Rust server). |
| network_manager.gd:246–253 (`_process_connected` drain) | `client_take_packets()` (no channel) | Drain `(channel, bytes)`; channel determines decode expectations; FIFO per channel. |
| network_manager.gd:255–266 (heartbeat send + timeout) | 1 Hz HEARTBEAT, 5 s timeout | Delete. ENet keepalive + `ENetPacketPeer.set_timeout()`; link death arrives as EVENT_DISCONNECT. `heartbeat_timeout` signal removed or re-sourced. |
| network_manager.gd:283–311 (`connect_to_server`) | `client_connect(url)` ws:// URL | Parse host:port (URL scheme changes — also touch `main_menu.gd:320` which passes `region.websocket_url`, and the Go API region payload that supplies it). |
| network_manager.gd:314–334 (`_wait_for_connection`) | 0.1 s polling on LinkState | Wait for EVENT_CONNECT with the same 5.0 s timeout + attempt-id staleness guard (keep behavior). |
| network_manager.gd:353–362 (`_fail_connection_attempt`) | `client_close(1000,…)+client_reset()` | `peer_disconnect_now()` / host destroy; keep reconnect gating logic untouched. |
| network_manager.gd:424–437 (`disconnect_from_server`) | DISCONNECT msg + close(1000) | Send DISCONNECT on **ch1 reliable**, then `peer_disconnect()` (graceful — lets ENet flush). |
| network_manager.gd:694–711 (`send_message`) | single un-channeled `client_send` | Add channel + flags parameter; route by type: PLAYER_INPUT→ch2 unreliable-seq, everything else client-sent→ch1 reliable. |
| network_manager.gd:718–719 (`send_player_input`) | alias | Pin to ch2. |
| network_manager.gd:721–725 (`send_heartbeat`) + :108–111 timers | client heartbeat | Delete (D2). |
| network_manager.gd:728–771 (clock sync + RTT) | from HEARTBEAT echo | RTT from `ENetPacketPeer.get_statistic(PEER_ROUND_TRIP_TIME)`; `server_ms` relocated into a server-stamped packet (e.g. snapshot header) — keep the EMA filter + sentinels identical (hazard #9). |
| network_manager.gd:451–489 (BATCH unwrap) | `[u8 11][u16][u8 N]…` envelope | Delete (D2); preserve in-order dispatch per channel. |
| network_manager.gd:530–690 (server send/batch/broadcast/peer mgmt) | server mode | Delete (Rust server). |
| network_manager.gd:1078–1080 (`is_server_connected`) | state + LinkState OPEN | Keep API; back with ENet peer state. Callers unchanged: prediction.gd:163,458; interpolation_controller.gd:131,335. |

### (b) Codec behind the Rust GDExtension (D6/D7 — no GDScript codec)

| Call site | Today | Change |
|---|---|---|
| network_manager.gd:794–904 (`_encode_packet` + :908–938 `_write_game_event_data` + :940–943 `_write_color_rgb`) | hand-written PacketWriter arms | Replace body with one extension call, e.g. `ProtocolCodec.encode(type, data) -> PackedByteArray` (returns channel too, or NetworkManager owns the type→channel map). |
| network_manager.gd:948–1039 (`_decode_packet`) | hand-written PacketReader arms | Replace with `ProtocolCodec.decode(bytes) -> Dictionary` returning the §6.1 shapes (incl. dequantized `Vector2` positions and `delta_mask` defaults). |
| network_manager.gd:807–809, 977–978 | `PlayerInputPacket.from_input_dict/read` | Covered by the codec call; delete `client/scripts/shared/networking/packets/player_input_packet.gd` usage. |
| network_manager.gd:811–830, 980–984 | `StateUpdatePacket` | Same — extension decodes STATE_UPDATE entities. |
| network_manager.gd:986–1000 | `GameEventPacket` / `ActionConfirmPacket` / `AuthPacket` / `DisconnectPacket` `.read` | Same. |
| network_manager.gd:852 | `AuthPacket.region_from_string` | Move mapping into the extension codec (or keep a constants-only GDScript helper). |
| network_manager.gd:957 | `PacketTypes.is_valid_type` | Extension decode returns null/err for invalid; keep drop-and-log behavior. |
| network_manager.gd:77–80, 452, 476–489, 949 | `PacketTypes.HEADER_SIZE/MAX_PACKET_SIZE` framing | Framing dies with the redesign (D7 owns layout); size guards move into the codec. |
| Constants consumers (NOT codec — keep accessible): prediction.gd:208–230, 338–341, 371–377, 389, 491–499, 542, 556, 570, 582–585 (`PacketTypes.INPUT_FLAG_*`, `DELTA_MASK_*`, `STATE_FLAG_IS_DELTA`, `ActionConfirmPacket.ActionType/ResultCode`); interpolation_controller.gd:169–170, 242–243, 287, 309–315 (+ EntityType/AnimationState defaults throughout); entity_state_buffer.gd:29–33, 52–55; client_entity_manager.gd:108–114, 367–370, 481–484 | GDScript class constants | Re-export from the extension (gdext constants) **or** keep `packet_types.gd` as a constants-only file with a parity test against the Rust `protocol` crate. Decide once; drift here is silent. |
| interpolation_controller.gd:185, 350–353; arena_base.gd:222, 800, 988; local_hit_detector.gd:123–126 | `NetworkManager.send_to_server(MessageType.X, {...})` | Unchanged API if NetworkManager keeps `MessageType` and the dict-in/dict-out surface (recommended); only the internals swap to the extension codec + channel routing. |

### (c) Prediction → `sim_core` through the extension (D5, D11)

| Call site | Today | Change |
|---|---|---|
| prediction.gd:336–343 | `sm.tick(delta, direction, sprint, dash, ability, shoot, aim_dir)` (GDScript MovementStateMachine) | Call the extension's sim-core player step (same arg order/semantics, returns velocity). The SM instance/state (stamina, mana, dash timers, `_prev_dash_held` edge state) moves into the extension object owned per local player. |
| prediction.gd:349–353 | `GameConstants.move_with_obstacle_collision(from, to, 16.0)` | Extension `sim_core` mover — byte-identical to the server's. |
| prediction.gd:392–394 | `sm.stamina` read + `sm.get_ground_speed(sprint)` | Extension getters (stamina query + ground speed incl. haste/slow multiplier). |
| prediction.gd:469–474 | replay-snapshot pre-computation (stateless model + mover) | Same extension mover; keep the stateless model (hazard #6). |
| prediction.gd:548 | `sm.set_resources(float(stamina), float(mana))` | Extension setter (clamping 0..100 inside sim_core so client and server clamp identically). |
| prediction.gd:683–700 (`_replay_input`) | stateless replay through the mover | Extension mover; consider batching the whole replay loop into ONE extension call (`replay_inputs(server_pos, [snapshots]) -> Vector2`) to cut ~0–255 boundary crossings per reconcile — behavior must remain step-for-step identical. |
| prediction.gd:78 | `INPUT_SEND_INTERVAL := GameConstants.SERVER_TICK_INTERVAL` | Source the tick interval from the extension (single authority for 1/30) or assert equality at startup. |
| prediction.gd:303, 310–312 | `GameConstants.SHOOT_COOLDOWN`, `PLAYER_HITBOX_RADIUS`, `PROJECTILE_RADIUS` (muzzle cosmetic) | Constants re-exported from sim_core/protocol so the flash matches the Rust server's spawn origin. |
| prediction.gd:364 (`_get_movement_sm`) | duck-typed `player_node.movement_sm` | Becomes the extension-backed SM handle; keep the null fallback (stateless path) for test nodes. |
| client_entity_manager.gd:521 | `HitAuthority.is_client_authoritative(source_id)` | sim_core hit predicate (D11 moves all HitAuthority predicates into the shared crate). |
| interpolation_controller.gd:31 | `TELEPORT_THRESHOLD := GameConstants.TELEPORT_THRESHOLD` | Source from the shared crate (server validation uses the same number; drift causes smoothing across genuine teleports). |
| local_hit_detector.gd (uses `HitAuthority.swept_hit` + `get_rendered_position()`) | GDScript swept test | sim_core swept-hit predicate; MUST keep testing the **rendered** position (prediction.gd:793–796), not predicted — D11 invariant. |

### Sequencing note (D14/M0)

The tracer bullet exercises exactly these seams: ENet transport (a) + codec (b) for
PLAYER_INPUT/STATE_UPDATE only + sim_core mover (c) for prediction + the reconcile loop
(4.3.7). Everything else (BATCH/heartbeat deletion, entity manager, adaptive delay) ports
unchanged on top.
