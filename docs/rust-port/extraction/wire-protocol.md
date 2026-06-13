# Wire protocol — extraction notes for the Rust port

> Generated extraction notes for the Rust port — derived from GDScript at commit
> `9e661497a994dcdb2a0d07f73724604af7b01cc5` on branch `feature/rust-port`. Source of truth is the
> GDScript until cutover.

This document specifies the **current** wire protocol byte-exactly. Per D3/D7 the new protocol is a
redesign (shared Rust `protocol` crate, hand-rolled bit codec), so semantics matter more than exact
bytes — but every byte is documented here so the redesign provably carries every field. Per D2,
`HEARTBEAT` and `BATCH` are dropped in the redesign (ENet subsumes them) **but** the clock-sync
payload (`server_ms`) that `HEARTBEAT` carries today must be relocated into a new packet, and the
per-message reliability of everything `BATCH` coalesces must be mapped onto ENet channels.

Where the existing `docs/netcode/wire-protocol.md` disagrees with the code, **the code wins**; the
discrepancies found are called out explicitly (HEARTBEAT is 8 B not 4 B; REQUEST_FULL_STATE /
RESPAWN_REQUEST carry a 4-byte timestamp, not empty; `is_valid_type` accepts 1..13, not 1..12).

---

## 1. Overview

The wire protocol is a hand-written little-endian binary format. Every packet in both directions is
framed `[u8 type][u16 payload_length][payload…]`. It is produced/consumed by:

- `client/scripts/shared/networking/packet_writer.gd` / `packet_reader.gd` — primitive codecs
  (shared by client and server; both roles run the same Godot project).
- `client/scripts/shared/networking/packet_types.gd` — all enums, flags, masks, constants.
- `client/scripts/shared/networking/packets/*.gd` — per-packet schema classes.
- `client/autoload/network_manager.gd` `_encode_packet` (line 794) / `_decode_packet` (line 948) —
  the **live** encode/decode dispatch (some packets — HEARTBEAT, SERVER_METRICS, BASELINE_ACK,
  LOCAL_HIT_REPORT, REQUEST_FULL_STATE, RESPAWN_REQUEST — are encoded inline here, not in a
  `*_packet.gd` class).
- `client/scripts/server/delta_state_cache.gd` — per-peer server-side delta/baseline bookkeeping.
- `client/autoload/transport/transport.gd` / `websocket_transport.gd` — the transport seam under it
  (WebSocket over TCP today; everything protocol-level sits above the seam).

**Position in the tick/frame flow.** The server's 30 Hz tick produces snapshots and events; the
socket is serviced once per **render frame** (`NetworkManager._process`), not per tick. Server
egress for one tick is coalesced into BATCH frames between `begin_batch()` (tick start) and
`flush_batches()` (tick end). The client sends one WebSocket message per packet immediately
(`network_manager.gd:694-711`), with `PLAYER_INPUT` produced at 30 Hz from `_physics_process`.
Inbound on both sides is **fully drained** every frame in FIFO order.

---

## 2. Constants

### 2.1 Framing & sizes (`packet_types.gd`, `packet_writer.gd`, `state_update_packet.gd`)

| Constant | Value | Unit | Source |
|---|---|---|---|
| `HEADER_SIZE` | 3 | bytes (`[u8 type][u16 length]`) | `packet_types.gd:7` |
| `MAX_PACKET_SIZE` | 65535 | bytes (u16 length ceiling) | `packet_types.gd:10` |
| `STATE_MAX_ENTITIES` | 65535 | count (u16 field ceiling, **not** the real cap) | `packet_types.gd:16` |
| `ENTITY_SIZE` | 9 | bytes per full-state entity | `state_update_packet.gd:32` |
| `DELTA_ENTITY_MIN_SIZE` | 3 | bytes (id + mask) | `state_update_packet.gd:34` |
| `FULL_STATE_HEADER_BYTES` | 3 + 4 + 1 + 2 = 10 | bytes (wire hdr + tick + flags + count) | `state_update_packet.gd:38` |
| `STATE_MAX_FULL_ENTITIES` | (65535 − 10) / 9 = **7280** (integer division) | entities per full-state packet | `state_update_packet.gd:46` |
| `INITIAL_CAPACITY` | 256 | bytes (writer initial buffer) | `packet_writer.gd:12` |
| `BATCH_MAX_PACKETS` | 255 | inner packets per BATCH (u8 count) | `network_manager.gd:77` |
| `BATCH_MAX_INNER_BYTES` | 65535 − 1 = 65534 | bytes of inner packets per BATCH | `network_manager.gd:80` |

### 2.2 Quantization scales (`packet_writer.gd:15-19`, mirrored `packet_reader.gd:15-19`)

| Constant | Value | Meaning |
|---|---|---|
| `POSITION_SCALE` | 10.0 | position × 10 → s16 (0.1-unit precision, range −3276.8 … +3276.7) |
| `VELOCITY_SCALE` | 10.0 | velocity × 10 → s16 (0.1-unit precision) |
| `ANGLE_SCALE` | 100.0 | radians × 100 → s16 (0.01-rad precision, range ±327.67 rad) |

### 2.3 Packet types (`packet_types.gd:19-33`, duplicated as `MessageType` in `network_manager.gd:16-30` — must stay in lockstep)

| Id | Name | Direction | Payload size | Frequency |
|---|---|---|---|---|
| 1 | `PLAYER_INPUT` | C→S | 17 B fixed | 30 Hz (every client physics tick while in game) |
| 2 | `STATE_UPDATE` | S→C | variable | per peer at `snapshot_rate_hz` (default = tick rate = 30 Hz) |
| 3 | `GAME_EVENT` | S→C | variable per event type | event-driven |
| 4 | `HEARTBEAT` | C↔S | **8 B** (`[u32 timestamp][u32 server_ms]`) — see §4.6 | C→S 1 Hz; S→C immediate echo per received |
| 5 | `ACTION_CONFIRM` | S→C | 11 B fixed | ~30 Hz per player (one per processed input) |
| 6 | `CONNECT_AUTH` | C→S | variable (strings + trailing fields) | once per connection (idempotent re-send guard) |
| 7 | `DISCONNECT` | C→S | 5 B fixed | once on clean disconnect |
| 8 | `REQUEST_FULL_STATE` | C→S | **4 B** (`[u32 timestamp_ms]`) | on broken delta chain; retry ≥2 s apart, max 3 |
| 9 | `RESPAWN_REQUEST` | C→S | **4 B** (`[u32 timestamp_ms]`) | on demand (death screen) |
| 10 | `SERVER_METRICS` | S→C | 33 B fixed | 1 Hz broadcast |
| 11 | `BATCH` | S→C only | `[u8 count][inner packets…]` | 0+ per tick per peer, at end-of-tick flush |
| 12 | `BASELINE_ACK` | C→S | 4 B (`[u32 baseline_tick]`) | once per received Baseline (~every 100 ticks steady-state) |
| 13 | `LOCAL_HIT_REPORT` | C→S | 2 B (`[u16 projectile_id]`) | event-driven (client-detected monster-projectile hit on self) |

`is_valid_type(t)` accepts `1 <= t <= 13` (`packet_types.gd:141-142` — the range upper bound is
`Type.LOCAL_HIT_REPORT`). Note: `docs/netcode/wire-protocol.md` says 1..12; that is stale.

### 2.4 Entity types (`packet_types.gd:36-40`)

| Value | Name |
|---|---|
| 1 | `PLAYER` |
| 2 | `MONSTER` |
| 3 | `PROJECTILE` |

### 2.5 Animation states — u8 on wire (`packet_types.gd:43-51`)

`IDLE=0, WALK=1, RUN=2, ATTACK=3, HIT=4, DEATH=5, SPAWN=6`.

### 2.6 Input flags — u16 on wire (`packet_types.gd:56-64`)

| Bit | Constant | Key |
|---|---|---|
| 0 | `INPUT_FLAG_MOVE_UP` | W |
| 1 | `INPUT_FLAG_MOVE_DOWN` | S |
| 2 | `INPUT_FLAG_MOVE_LEFT` | A |
| 3 | `INPUT_FLAG_MOVE_RIGHT` | D |
| 4 | `INPUT_FLAG_SHOOT` | LMB |
| 5 | `INPUT_FLAG_ABILITY` | RMB / ability |
| 6 | `INPUT_FLAG_SPRINT` | Shift |
| 7 | `INPUT_FLAG_INTERACT` | E |
| 8 | `INPUT_FLAG_DASH` | Space — **edge-triggered dash request** (this bit forced the field u8→u16) |

Bits 9–15 unused.

### 2.7 Entity flags — u8 on wire (`packet_types.gd:67-74`)

| Bit | Constant |
|---|---|
| 0 | `ENTITY_FLAG_ALIVE` |
| 1 | `ENTITY_FLAG_MOVING` |
| 2 | `ENTITY_FLAG_ATTACKING` |
| 3 | `ENTITY_FLAG_INVULNERABLE` |
| 4 | `ENTITY_FLAG_STUNNED` |
| 5 | `ENTITY_FLAG_VISIBLE` |
| 6 | `ENTITY_FLAG_DASHING` (movement SM in DASHING state) |
| 7 | `ENTITY_FLAG_KNOCKED_BACK` (movement SM in KNOCKED_BACK state) |

Default encode when an entity dict omits keys: `alive=true, visible=true`, everything else false
(`packet_types.gd:176-186`).

### 2.8 Delta masks — u8 on wire (`packet_types.gd:78-82`)

| Bit | Constant | Payload if set |
|---|---|---|
| 0 | `DELTA_MASK_POSITION` | 4 B (2×s16) |
| 1 | `DELTA_MASK_ANIMATION` | 1 B (u8) |
| 2 | `DELTA_MASK_FLAGS` | 1 B (u8) |
| 6 | `DELTA_MASK_REMOVED` | none (despawn marker) |
| 7 | `DELTA_MASK_FULL_STATE` | 7 B (type 1 + pos 4 + anim 1 + flags 1) — overrides bits 0–2 |

Bits 3–5 unused.

### 2.9 State-update packet flags — u8 on wire (`packet_types.gd:86-87`)

| Bit | Constant | Meaning |
|---|---|---|
| 0 | `STATE_FLAG_IS_DELTA` | packet uses the delta layout (carries `baseline_tick`) |
| 1 | `STATE_FLAG_BASELINE` | packet is a Baseline (full-state layout; client must ack) |

In practice the server emits either `state_flags = STATE_FLAG_BASELINE` (=2, full-state layout) or
`state_flags = STATE_FLAG_IS_DELTA` (=1, delta layout). Never both.

### 2.10 Baseline / delta cadence

| Constant | Value | Unit | Source |
|---|---|---|---|
| `DELTA_FULL_STATE_INTERVAL` | 100 | ticks between forced Baselines (~3.33 s @ 30 Hz) | `packet_types.gd:93` |
| `BASELINE_ACK_TIMEOUT_TICKS` | 30 | ticks before an un-acked Baseline is resent | `delta_state_cache.gd:49` |
| position-equality epsilon | 0.05 | units (half the 0.1 quantization step), strict `<` | `delta_state_cache.gd:119` |
| `FULL_STATE_REQUEST_TIMEOUT_MS` | 2000 | ms before client retries REQUEST_FULL_STATE | `interpolation_controller.gd:111` |
| `FULL_STATE_MAX_RETRIES` | 3 | attempts, then client clears all entity buffers | `interpolation_controller.gd:112` |

### 2.11 Game event types (`packet_types.gd:96-109`)

`DAMAGE=1, KILL=2, RESPAWN=3, EFFECT_APPLY=4, EFFECT_REMOVE=5, PICKUP=6, LEVEL_UP=7,
CHAT_MESSAGE=8, PLAYER_INFO=9, KILL_PVP=10, LEADERBOARD_UPDATE=11, PROJECTILE_FIRED=12`.

### 2.12 Disconnect reasons (`packet_types.gd:112-119`)

`USER_QUIT=0, TIMEOUT=1, KICKED=2, SERVER_SHUTDOWN=3, INVALID_AUTH=4, DUPLICATE_SESSION=5`.

### 2.13 ACTION_CONFIRM enums (`action_confirm_packet.gd:16-31`)

`ActionType: MOVE=0, SHOOT=1, ABILITY=2, INTERACT=3`.
`ResultCode: SUCCESS=0, FAILED_INVALID_POSITION=1, FAILED_COOLDOWN=2, FAILED_NO_TARGET=3,
FAILED_BLOCKED=4, FAILED_INVALID_STATE=5`.

### 2.14 CONNECT_AUTH region enum (`auth_packet.gd:13-18`)

`ASIA=0, EUROPE=1, US_WEST=2, US_EAST=3`. `region_from_string` is case-insensitive and defaults to
`ASIA` for any unknown string (`auth_packet.gd:120-126`).

### 2.15 Heartbeat / clock-sync / connection constants (`network_manager.gd`)

| Constant / var | Value | Unit | Source line |
|---|---|---|---|
| `heartbeat_interval` | 1.0 | s (client send cadence) | :108 |
| `heartbeat_timeout_seconds` (client) | 5.0 | s of silence → disconnect | :111 |
| `server_heartbeat_timeout` | 5.0 | s of silence per peer → kick | :65 |
| `UINT32_WRAP` | 4294967296 | (2^32, for RTT wrap correction) | :112 |
| `MAX_REASONABLE_PING_MS` | 10000 | ms; larger samples discarded entirely | :113 |
| `SERVER_CLOCK_FILTER_ALPHA` | 0.2 | EMA weight for clock-offset samples | :121 |
| `DEFAULT_CLIENT_BUDGET` | 120000 | bytes/s advertised in CONNECT_AUTH if unset | :85 |
| `connection_timeout_seconds` | 5.0 | s (poll loop in 0.1 s steps) | :103 |
| `base_reconnect_delay` | 1.0 | s; backoff = min(1.0 × 2^attempts, 32.0) | :100 |
| `max_reconnect_delay` | 32.0 | s | :101 |
| `max_reconnect_attempts` | 5 | attempts | :99 |
| default server port | 8080 | from `ServerConfig` | :91, :158 |

### 2.16 Server-side budget config (`server_config.gd` DEFAULTS, `server_main.gd`)

| Constant | Value | Source |
|---|---|---|
| `snapshot_rate_hz` | 0 → falls back to tick rate (30); clamped to (0, tick_rate] | `server_config.gd:33,102-108` |
| `max_snapshot_bytes` | 1200 | `server_config.gd:37` |
| `default_client_bandwidth_bps` | 120000 | `server_config.gd:43` |
| `max_client_bandwidth_bps` | 200000 | `server_config.gd:45` |
| `min_client_bandwidth_bps` | 24000 | `server_config.gd:47` |
| `MIN_SNAPSHOT_FLOOR` | 256 bytes | `server_main.gd:51` |

---

## 3. Data structures

### 3.1 PacketWriter (`packet_writer.gd`)

| Field | Type | Initial |
|---|---|---|
| `_buffer` | growable byte array | sized `INITIAL_CAPACITY` (256) or caller-given |
| `_position` | int | 0 |

Growth: on overflow, `new_size = max(required, buffer.size() * 2)` (`packet_writer.gd:29-33`).
`get_buffer()` returns a copy trimmed to `_position`.

### 3.2 PacketReader (`packet_reader.gd`)

| Field | Type | Initial |
|---|---|---|
| `_buffer` | byte array | the input |
| `_position` | int | 0 |
| `_size` | int | `buffer.size()` |

### 3.3 DeltaStateCache — one per connected peer, server-side (`delta_state_cache.gd`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `_cache` | map entity_id → CachedEntityState | `{}` | |
| `_baseline_tick` | int | 0 | tick of last Baseline **sent** |
| `_acked_baseline_tick` | int | 0 | highest Baseline tick the peer has acked |
| `_pending_baseline_tick` | int | 0 | Baseline sent, not yet acked; **0 = none outstanding** (sentinel) |
| `peer_id` | int | 0 | debugging only |
| `debug_logging` | bool | false | |

`CachedEntityState` (inner class, `delta_state_cache.gd:10-33`):

| Field | Type | Initial | Valid range |
|---|---|---|---|
| `entity_id` | int | 0 | u16 on the wire (1–999 players, 10000–29999 projectiles, 30000–39999 monsters) |
| `entity_type` | int | 1 (PLAYER) | 1–3 |
| `position` | Vector2 (2×f32) | (0, 0) | arena (−1000,−1000)..(1000,1000); wire-clamped ±3276.7 |
| `animation_state` | int | 0 (IDLE) | 0–6 |
| `flags` | int | 0 | u8 bitfield |
| `last_tick_sent` | int | 0 | server tick |
| `is_new` | bool | true | true until first send; forces FULL_STATE mask |

### 3.4 Client clock-sync state (`network_manager.gd:119-121`)

| Field | Type | Initial | Notes |
|---|---|---|---|
| `server_clock_offset_ms` | float (f64) | 0.0 | EMA-filtered `server_ms − estimated local time of server stamp` |
| `server_clock_offset_samples` | int | 0 | 0 = "no sync yet" sentinel; `get_server_time_ms()` returns 0 until ≥1 |

### 3.5 Batching state, server mode (`network_manager.gd:74-75`)

| Field | Type | Initial |
|---|---|---|
| `_batching_active` | bool | false |
| `_pending_batches` | map peer_id → array of encoded packets | `{}` |

### 3.6 Transport seam (`transport.gd`)

Abstract interface; `LinkState` enum: `OPEN=0, CONNECTING=1, CLOSING=2, CLOSED=3`; `Role` enum:
`CLIENT=0, SERVER=1`. Normalized server events (drained in observation order):
`{kind:"connected", peer_id}`, `{kind:"closed", peer_id}`, `{kind:"packet", peer_id, bytes}`.
**Contract: packet events must preserve per-peer FIFO receive order** (`transport.gd:63-69`).

WebSocketTransport state (`websocket_transport.gd`): `_ws_client` (client socket), `_ws_server`
(TCP listener), `_connected_peers` (peer_id → socket), `_peer_open_seen` (peer_id → bool, ensures
exactly one "connected" event per peer), `_pending_events` (array, rebuilt each poll).
**`peer_id = randi()`** — a uniformly random 32-bit unsigned int, *not* sequential
(`websocket_transport.gd:65`). Collisions are possible and unguarded.

---

## 4. Algorithms

All multi-byte integers are **little-endian**. GDScript `int` is a 64-bit signed integer;
`Vector2` components are 32-bit floats; loose float arithmetic is 64-bit.

### 4.1 Primitive writes (`packet_writer.gd`)

```
write_u8(v):   store (v & 0xFF) as 1 byte
write_s8(v):   store low 8 bits two's-complement
write_u16(v):  store (v & 0xFFFF) LE
write_s16(v):  store low 16 bits two's-complement LE
write_u32(v):  store (v & 0xFFFFFFFF) LE
write_s32(v):  store low 32 bits two's-complement LE
write_float32(v): IEEE-754 single LE (4 B)   — unused by current packets
write_float64(v): IEEE-754 double LE (8 B)   — unused by current packets
write_bool(v): write_u8(1 or 0)
write_string(s):
    bytes = UTF-8 encoding of s
    write_u16(bytes.len())          # NOT clamped — len > 65535 wraps the prefix; see §5
    append bytes                    # all of them, even if len wrapped
write_bytes(b): append raw
```

Unsigned writes mask; **signed writes do not clamp** (Godot `encode_s16` truncates to the low 16
bits two's-complement). All call sites that write quantized values clamp explicitly first.

### 4.2 Quantization (`packet_writer.gd:126-159`, `packet_reader.gd:154-176`)

```
encode_position/velocity(vec):                 # write_vector2_compressed / write_velocity_compressed
    qx = trunc_toward_zero(vec.x * 10.0)       # GDScript int(float) TRUNCATES TOWARD ZERO
    qy = trunc_toward_zero(vec.y * 10.0)
    qx = clamp(qx, -32768, 32767); qy = clamp(qy, -32768, 32767)
    write_s16(qx); write_s16(qy)               # 4 bytes total

decode_position/velocity():
    x = f32_or_f64(read_s16()) / 10.0
    y = read_s16() / 10.0
    return Vector2(x, y)                       # stored as 2×f32

encode_angle(rad):                             # write_angle_compressed
    q = trunc_toward_zero(rad * 100.0); q = clamp(q, -32768, 32767); write_s16(q)
decode_angle(): return read_s16() / 100.0
```

Notes: `vec.x` is f32; the multiply promotes to f64; truncation is toward zero (−1.26·10 = −12.6 →
−12, not −13). Round-trip is **not** identity (lossy by design, ≤0.1 unit / ≤0.01 rad error).

### 4.3 Color quantization (`game_event_packet.gd:290-302`, `auth_packet.gd:143-155`,
`network_manager.gd:940-943` — three identical copies)

```
encode: for each of r,g,b (f32 0..1): write_u8(clamp(round_half_away_from_zero(c * 255.0), 0, 255))
decode: Color(read_u8()/255.0, read_u8()/255.0, read_u8()/255.0, alpha=1.0)
```

Godot `roundi` rounds half away from zero. Default player color everywhere:
`Color(0.27, 0.53, 1.0)` → bytes (69, 135, 255).

### 4.4 Header framing (`packet_writer.gd:191-203`, `packet_reader.gd:199-220`)

```
write_header(type): write_u8(type); write_u16(0)        # length placeholder
... write payload ...
finalize_header(): payload_length = _position - 3; patch u16 at offset 1
                                                        # length > 65535 WRAPS silently — see §5
read side: read_header() -> {type: read_u8(), payload_length: read_u16()}
PacketReader.from_packet(buffer): new reader, skip(3)
```

### 4.5 Primitive reads — underflow behavior (`packet_reader.gd:29-33,57-126`)

Every read first checks `_position + needed <= _size`. **On failure: logs an error, returns
0 / 0.0 / "" / empty array, and does NOT advance the position.** There is no exception and no
abort: a truncated packet decodes into zeroed fields silently (see §5). `read_string` reads the u16
length first (advancing 2 bytes) and returns "" if the body is out of bounds, leaving the position
after the length prefix. `skip(n)` clamps to size. `peek_packet_type()` returns −1 on an empty
buffer.

### 4.6 HEARTBEAT and clock sync — the live wire path

**Wire payload is 8 bytes in BOTH directions** (`network_manager.gd:799-805` encode, `:967-974`
decode): `[u32 timestamp][u32 server_ms]`.

- Client → server (1 Hz, `network_manager.gd:722-725`): `timestamp = Time.get_ticks_msec()`
  (masked to u32 by `write_u32`), `server_ms = 0`.
- Server → client: consumed at NetworkManager level (never forwarded to the sim,
  `network_manager.gd:510-517`). The server updates `peer_last_heartbeat[peer]` and **immediately**
  replies with the **echoed** client `timestamp` and `server_ms = Time.get_ticks_msec() & 0xFFFFFFFF`
  (the server's monotonic ms clock, u32-wrapped).

The standalone `heartbeat_packet.gd` class writes only 4 bytes (`[u32 timestamp]`) — it is **not**
the live path and is stale relative to `_encode_packet`. The wire-protocol doc's "4 B" claim is
likewise stale. A 4-byte heartbeat would still parse: `read_u32` for `server_ms` underflows →
returns 0 → the clock-sample branch is skipped (`server_ms == 0` check).

**Client clock-offset estimation** (`network_manager.gd:728-771`):

```
on heartbeat reply {timestamp, server_ms}:
    if timestamp missing: return
    ping_ms = elapsed_u32(timestamp)                 # see below
    if ping_ms > 10000: return                       # bogus; also skip clock sample
    stats.ping_ms = ping_ms
    if server_ms == 0: return                        # old server / unstamped
    arrival_local = Time.get_ticks_msec() & 0xFFFFFFFF
    server_send_local = arrival_local - trunc_toward_zero(ping_ms / 2.0)
    sample = float(server_ms - server_send_local)
    if samples == 0: offset = sample                 # first sample: take directly
    else:            offset = lerp(offset, sample, 0.2)   # EMA, alpha = 0.2
    samples += 1

elapsed_u32(ts):
    e = (now_ms & 0xFFFFFFFF) - (ts & 0xFFFFFFFF)
    if e < 0: e += 4294967296                        # u32 wrap correction
    return e

get_server_time_ms():
    if samples == 0: return 0                        # "no sync yet" sentinel
    return int(round((now_ms & 0xFFFFFFFF) + offset))
```

The interpolation layer consumes `get_server_time_ms()`. **The redesigned protocol must carry
`server_ms` somewhere** (D2 relocates it; ENet supplies RTT/keepalive natively but not the server
wall clock). The reply also doubles as the liveness signal: client disconnects after 5 s without
any HEARTBEAT reply; server kicks a peer after 5 s without a client HEARTBEAT.

### 4.7 PLAYER_INPUT (type 1) — 17-byte payload (`player_input_packet.gd:79-99`)

```
write:  vector2_compressed(position)      # 4 B — client's predicted position (server validates)
        velocity_compressed(velocity)     # 4 B
        u16(input_flags)                  # 2 B — bitfield §2.6
        angle_compressed(aim_angle)       # 2 B — radians × 100
        u8(sequence_number)               # 1 B — wraps at 256 (created with seq & 0xFF)
        u16(client_render_tick)           # 2 B — server tick remotes were rendered at (& 0xFFFF)
        u16(client_rtt_ms)                # 2 B — clamped 0..65535 at creation
read: same order, same widths.
```

`sequence_number` is the reconciliation key; the client replay buffer is 256 deep.
`client_render_tick` feeds PvE lag compensation; it is the **low 16 bits** of the server tick.

### 4.8 STATE_UPDATE (type 2) — the Snapshot (`state_update_packet.gd`)

Mode selected by `state_flags` bit 0 (`STATE_FLAG_IS_DELTA`).

**Full-state layout** (used by Baselines, which also set bit 1 `STATE_FLAG_BASELINE`):

```
[u32 server_tick]        4
[u8  state_flags]        1     # delta bit clear; BASELINE bit set on baselines
[u16 entity_count]       2
per entity (9 B):
  [u16 entity_id] [u8 entity_type] [s16 x][s16 y] [u8 animation_state] [u8 flags]
```

Writer (`:205-219`): `emitted = min(entities.len(), 7280)`; writes `emitted` as the count, then
exactly `emitted` entities — header and loop can never diverge; overflow is **silent truncation**
(the broadcast service separately counts `snapshot_count_overflow` and warns,
`server_broadcast_service.gd:510-512`). **`baseline_tick` is NOT serialized in full-state mode**
even though the server-side dict carries it.

**Delta layout**:

```
[u32 server_tick]        4
[u8  state_flags]        1     # IS_DELTA set
[u32 baseline_tick]      4     # tick of the Baseline this diffs against
[u16 entity_count]       2
per entity (3–10 B):
  [u16 entity_id] [u8 delta_mask]
  if mask has FULL_STATE (bit 7):  [u8 entity_type][s16 x][s16 y][u8 anim][u8 flags]   (10 B total)
  elif mask has REMOVED (bit 6):   nothing                                              (3 B total)
  else, in this exact order:
       if bit 0 (POSITION):  [s16 x][s16 y]
       if bit 1 (ANIMATION): [u8 anim]
       if bit 2 (FLAGS):     [u8 flags]
```

Delta writer caps the count at 65535 (`:225`); in practice the per-peer byte budget (~256–1200 B)
binds long before that. Note the FULL_STATE check happens **before** the REMOVED check on both
write and read — a mask with both bits set is treated as full-state.

**Reader** (`:251-326`): reads per the layout. For delta entities, missing fields are filled from a
caller-provided `last_states` map; for a REMOVED entity, `flags` is forced to 0 and type/pos/anim
come from `last_states`. **The live client decode path calls `StateUpdatePacket.read(reader)`
WITHOUT `last_states`** (`network_manager.gd:983`), so unsent fields decode as placeholder defaults
(`position=(0,0)`, `anim=IDLE`, `flags=0`, `type=PLAYER`); the real merge against last-known state
happens downstream in `InterpolationController` keyed on `delta_mask`. **Port rule: after decode,
only the fields named by `delta_mask` are authoritative.**

### 4.9 Server-side snapshot construction (delta vs Baseline decision)

Per peer per snapshot tick (`server_broadcast_service.gd:140-227`):

```
visible = AoI filter (hysteresis enter/exit radii) of all entities; self always included
removed_entity_ids = previously-visible ids no longer visible (AoI exits)
needs_baseline = cache.needs_full_state_for_interval(tick)        # tick - baseline_tick >= 100
              or cache.needs_baseline_resend(tick)                # see §4.11
if needs_baseline and removed_entity_ids.is_empty():
    packet = full-state Baseline (all visible entities, delta_mask = FULL_STATE each;
             cache.update_cache(each); cache.reset_baseline(tick);
             dict: {tick, state_flags: BASELINE, baseline_tick: tick, entities})
else:
    packet = delta packet (see below)
send STATE_UPDATE to peer
```

**Quirk:** if a Baseline is due but entities left AoI this tick, a **delta is sent instead**; the
interval condition stays true, so the Baseline goes out on the next tick with no AoI exits.

**Delta packet construction** (`server_broadcast_service.gd:526-661`):

1. AoI-exit removals staged first, **pinned** (always emitted), `delta_mask = REMOVED`.
2. For each visible entity: `delta_mask = cache.calculate_delta_mask(...)` (§4.10);
   **mask == 0 → entity omitted entirely** (unchanged entities cost zero bytes, not 3).
3. Stale cache entries (in cache but not in the active set —
   `cache.cleanup_stale_entities(active_ids)` erases them and returns the ids) staged as
   additional pinned REMOVED deltas (skipping ids already in step 1).
4. A priority scheduler selects entries within the per-peer byte budget
   (`_budget_for_peer(peer)`, default `max_snapshot_bytes` = 1200; per-peer cap derived at auth,
   §4.14). Pinned removals always fit (budget floor 256 B). **Selection reorders entities — the
   client must not assume any entity ordering.** Deferred entities keep their stale cache entry and
   re-compete next tick.
5. For each entity actually emitted, `cache.update_cache_partial(id, state, mask, tick)` (§4.12).
6. Resulting dict: `{tick, state_flags: IS_DELTA, baseline_tick: cache.get_baseline_tick(), entities}`.

### 4.10 Delta mask calculation (`delta_state_cache.gd:79-124`)

```
calculate_delta_mask(entity_id, current, tick):
    if entity_id not in cache:           return FULL_STATE          # bit 7
    cached = cache[entity_id]
    if cached.is_new:                    return FULL_STATE
    if tick - _baseline_tick >= 100:     return FULL_STATE          # interval forces full
    mask = 0
    if not positions_equal(cached.position, current.position): mask |= POSITION
    if cached.animation_state != current.animation_state:      mask |= ANIMATION
    if cached.flags != current.flags:                          mask |= FLAGS
    return mask                                                     # may be 0 (caller omits entity)

positions_equal(a, b): |a.x − b.x| < 0.05 AND |a.y − b.y| < 0.05    # strict <, f32 components
```

### 4.11 Baseline ack flow (BASELINE_ACK, type 12)

Server, on sending a Baseline (`delta_state_cache.gd:207-212`):
`_baseline_tick = tick; _pending_baseline_tick = tick`.

Client, on receiving a packet with `STATE_FLAG_BASELINE` set
(`interpolation_controller.gd:173-187`): sets `last_baseline_tick = server_tick`, clears the
full-state-request retry state, and sends `BASELINE_ACK {baseline_tick: server_tick}`. **The
Baseline is a full-state packet and carries no `baseline_tick` on the wire — the ack echoes the
packet's `server_tick`.** Wire payload: `[u32 baseline_tick]` (`network_manager.gd:890-895` encode,
`:1031-1033` decode).

Server, on receiving the ack (`server_main.gd:674-678` → `server_broadcast_service.gd:446-452` →
`delta_state_cache.gd:218-224`):

```
mark_baseline_acked(acked):
    if acked >= _acked_baseline_tick:   _acked_baseline_tick = acked   # ignore stale/dup acks
    if acked >= _pending_baseline_tick: _pending_baseline_tick = 0     # clear resend timer
```

Resend check, evaluated every snapshot tick (`delta_state_cache.gd:230-235`):

```
needs_baseline_resend(tick):
    if _baseline_tick == 0: return false            # never sent one; interval path handles it
    return _pending_baseline_tick > 0 and (tick - _pending_baseline_tick) >= 30
```

On today's TCP this path is **inert** (baselines never drop); it exists for the UDP transport. The
100-tick interval is the floor that non-acking clients (bots) rely on — never removed.

### 4.12 Cache update after send (`delta_state_cache.gd:137-178`)

`update_cache(id, state, tick)` (Baseline path): overwrite position/anim/flags, set
`last_tick_sent = tick`, `is_new = false`.

`update_cache_partial(id, state, mask, tick)` (delta path): if mask has FULL_STATE, overwrite all
three tracked fields; otherwise overwrite **only** the fields whose bit is set — fields withheld
(e.g. LOD-throttled) keep the stale cached value and stay dirty for the next tick. Always updates
`entity_type`, `last_tick_sent = tick`, `is_new = false`. Creates the entry if absent.

### 4.13 REQUEST_FULL_STATE flow (type 8)

Client trigger (`interpolation_controller.gd:188-194`): a **delta** packet whose `baseline_tick !=
last_baseline_tick` while `last_baseline_tick > 0` ⇒ delta chain broken ⇒ `_request_full_state_sync()`
(`:334-356`):

```
if not connected: return
if retry_count >= 3: warn, clear_all_entities(), reset counters, return   # nuclear recovery
record request time; retry_count += 1
send REQUEST_FULL_STATE {}                     # encoded payload: [u32 Time.get_ticks_msec()]
```

A pending request is retried when 2000 ms pass without a Baseline arriving
(`interpolation_controller.gd:135-140`). Receiving any Baseline resets time/retry counters.

Server handler (`server_main.gd:665-669` → `server_broadcast_service.gd:312-362`): builds a
full-state packet of **ALL entities (not AoI-filtered)** — authenticated players + projectiles +
monsters — via `_create_full_state_packet` (which also `update_cache`s every entity and
`reset_baseline(tick)`, so this **counts as a Baseline**: `state_flags = STATE_FLAG_BASELINE`, the
client will ack it), then **re-sends a `PLAYER_INFO` GAME_EVENT for every authenticated player** to
the requester (the recovery path for a missed identity broadcast).

### 4.14 CONNECT_AUTH (type 6) and the bandwidth budget

Wire layout (`auth_packet.gd:76-100`; the live server-bound encode is
`network_manager.gd:848-856`, byte-identical):

```
[u16 len][utf8 token]            # JWT
[u16 len][utf8 character_id]
[u16 len][utf8 character_name]
[u8 region]                      # §2.14
[u8 r][u8 g][u8 b]               # player color; read only if >= 3 bytes remain (optional-on-wire)
[u32 bandwidth_budget_bps]       # trailing, read only if >= 4 bytes remain (length-gated append)
```

Encode writes `max(0, budget)`. Client default budget: 120000 B/s (`DEFAULT_CLIENT_BUDGET`;
`_get_client_bandwidth_budget()` forwards the configured default when player_data has 0/absent).

Server resolution (`server_main.gd:697-714`):

```
advertised = data.bandwidth_budget_bps (0 if absent)
effective  = advertised if advertised > 0 else 120000           # default_client_bandwidth_bps
effective  = clamp(effective, 24000, 200000)                    # min/max config
per_peer_bytes = trunc(effective / float(max(1, snapshot_rate_hz)))   # 30 Hz default
per_peer_bytes = clamp(per_peer_bytes, 256, 1200)               # MIN_SNAPSHOT_FLOOR, max_snapshot_bytes
```

This `per_peer_bytes` is the delta-snapshot byte budget used in §4.9 step 4. Baselines **bypass**
it (bounded only by the 7280-entity frame cap).

### 4.15 GAME_EVENT (type 3) (`game_event_packet.gd:142-251`)

Common 5-byte head, then a per-event tail:

```
[u8 event_type][u16 source_id][u16 target_id]
```

| Event | Tail (exact order) |
|---|---|
| `DAMAGE` (1) | `[u16 amount][u8 damage_type]` |
| `KILL` (2), `KILL_PVP` (10) | — none (ids only: source=killer, target=victim) |
| `RESPAWN` (3) | `[s16 x][s16 y]` (position ×10); subject in `target_id`, `source_id=0` |
| `EFFECT_APPLY` (4) | `[u8 effect_id][u16 duration_ms]` |
| `EFFECT_REMOVE` (5) | `[u8 effect_id]` |
| `PICKUP` (6), `LEVEL_UP` (7), `CHAT_MESSAGE` (8) | — not serialized today (head only, empty data on read) |
| `PLAYER_INFO` (9) | `[u16 len][utf8 character_name][s16 x][s16 y][u8 r][u8 g][u8 b]`; subject in `target_id`, `source_id=0`; color read only if ≥3 bytes remain (default `Color(0.27,0.53,1.0)`) |
| `LEADERBOARD_UPDATE` (11) | `[u8 n]` then n × `[u16 entity_id][u16 pvp_kills]`; server caps n at 10 |
| `PROJECTILE_FIRED` (12) | `[s16 x][s16 y][u16 server_tick]`; `source_id` = shooter, `target_id` = **projectile id (must be non-zero for monster shots — D11 invariant)** |

Unknown event types: nothing written/read beyond the head. `event_type` values outside the enum
pass through the head parse with empty `event_data`.

### 4.16 ACTION_CONFIRM (type 5) — 11-byte payload (`action_confirm_packet.gd:88-108`;
live encode `network_manager.gd:839-846` identical)

```
[u8 sequence_number]      # echoes the client input seq being confirmed
[u8 action_type]          # §2.13
[s16 x][s16 y]            # server's authoritative position (×10)
[u8 result_code]          # §2.13
[u16 server_tick]         # low 16 bits of the server tick
[u8 stamina]              # clamp(value, 0, 255) on write — logical range 0–100
[u8 mana]                 # clamp(value, 0, 255) on write — logical range 0–100
```

Owner-only; ~30 Hz per player (one per fresh input processed). The stamina/mana tail is the
authoritative resource sync for the predicted movement state machine.

### 4.17 DISCONNECT (type 7) — 5-byte payload (`disconnect_packet.gd:37-47`; live encode
`network_manager.gd:858-860`)

`[u8 reason_code][u32 timestamp_ms]`. Reason resolved from a string by substring match
(`network_manager.gd:774-789`): contains "timeout"→1, "kick"→2, "server shutdown"→3,
"invalid auth"→4, "duplicate"→5, else 0. Server consumes DISCONNECT at NetworkManager level and
closes the peer (never forwarded to the sim).

### 4.18 SERVER_METRICS (type 10) — 33-byte payload, 1 Hz
(`network_manager.gd:871-888` encode, `:1013-1029` decode — no packet class; encode/decode must
stay in field-for-field lockstep)

```
[u32 tick_count]
[u16 avg_tick_time_ms_x100]    # int(ms * 100) — truncates; write_u16 MASKS (wraps > 655.35 ms!)
[u16 max_tick_time_ms_x100]    # same fixed-point ×100; decode divides by 100.0
[u16 player_count]
[u16 entity_count]
[u32 total_bytes_sent]
[u32 total_bytes_received]
[u32 avg_bandwidth_per_client] # bytes/sec, int-truncated from float
[u16 sched_entities_deferred]      # min(v, 65535) guard
[u16 sched_max_queue_age_ticks]    # min(v, 65535)
[u8  sched_peers_at_budget_pct]    # clamp(v, 0, 255)
[u16 sched_peers_evaluated]        # min(v, 65535)
[u16 sched_snapshot_overflow]      # min(v, 65535) — the Baseline frame-cap overflow counter
```

Note the asymmetric guards: the five `sched_*` fields are explicitly clamped, the two tick-time
fields are **not** (they wrap via the u16 mask).

### 4.19 LOCAL_HIT_REPORT (type 13) — 2-byte payload
(`network_manager.gd:897-901` encode, `:1035-1037` decode)

`[u16 projectile_id]` — "a monster projectile hit me", client-detected, server-validated. Applies
only to the **reporting peer's own** entity; the server rejects player-owned projectile ids (D11).

### 4.20 BATCH (type 11) — server-egress coalescing (TASK-066)

**Envelope**: `[u8 type=11][u16 payload_len][u8 count][inner packet 0][inner packet 1]…` where each
inner packet is a complete framed packet (own 3-byte header). Constraints: `count ≤ 255`
(`BATCH_MAX_PACKETS`), total inner bytes ≤ 65534 (`BATCH_MAX_INNER_BYTES`, leaving 1 byte of the
u16 payload for the count field).

**Build** (`network_manager.gd:555-640`): the server tick calls `begin_batch()`; every
`send_to_client` during the tick encodes the packet, tallies its bytes against its type
(`bytes_sent_by_type`), and queues it per-peer. `flush_batches()` at end-of-tick walks each peer
queue in FIFO order, greedily filling chunks:

```
for each queued packet:
    if chunk non-empty and (chunk.count == 255 or chunk_bytes + pkt.len > 65534):
        emit chunk; start new chunk
    if pkt.len > 65534: send pkt RAW (cannot fit any envelope); continue
    add pkt to chunk
emit final chunk
# emitting a chunk: 1 packet  -> sent RAW, no envelope
#                   2+ packets -> wrapped in a BATCH envelope
```

Only the envelope overhead (4 bytes: header + count) is tallied against the BATCH type.
`clear_batches()` discards the queue without sending (shutdown path). Sends to a peer whose link is
not OPEN are silently skipped at queue time (`send_to_client` guard, `:530-531`).

**Unwrap** (client only, `network_manager.gd:474-490`):

```
if packet.size() < 4: return
count = byte at offset 3; pos = 4
repeat count times:
    if pos + 3 > packet.size(): log "BATCH truncated"; STOP (inner packets so far were dispatched)
    inner_len = u16 at pos+1
    if pos + 3 + inner_len > packet.size(): log "overflows envelope"; STOP
    dispatch slice [pos, pos + 3 + inner_len)        # re-enters the dispatcher: nested BATCH
    pos += 3 + inner_len                             #   would unwrap recursively (never produced)
```

Inner packets are dispatched **in order**, so listeners observe the exact sequence the server
queued during its tick. The envelope's own `payload_len` is not validated against the buffer; the
parser trusts `packet.size()`. Clients never send BATCH; the server-side inbound handler does
**not** unwrap it (a client-sent BATCH would be forwarded to the sim as an unhandled type… after
passing `is_valid_type`).

### 4.21 Dispatch rules (who consumes what)

- Client inbound (`network_manager.gd:451-471`): size < 3 → drop. type == BATCH → unwrap.
  decode → empty → drop. type == HEARTBEAT → update `last_heartbeat_received`, run clock sync,
  **stop**. Else emit `server_message_received(type, data)`.
- Server inbound (`network_manager.gd:494-525`): decode → null/empty → drop. HEARTBEAT → update
  `peer_last_heartbeat`, immediate stamped echo, **stop**. DISCONNECT → close peer, **stop**.
  Else emit `server_client_message(peer_id, type, data)`; ServerMain routes PLAYER_INPUT /
  CONNECT_AUTH / REQUEST_FULL_STATE / RESPAWN_REQUEST / LOCAL_HIT_REPORT / BASELINE_ACK
  (`server_main.gd:660-681`).
- `_decode_packet` (`:948-959`): size < 3 → `{}`; `is_valid_type` fails → `{}` (logged). A decoded
  message missing a `type` key defaults to HEARTBEAT in both dispatchers
  (`message.get("type", MessageType.HEARTBEAT)`) — unreachable in practice but a quirk to not copy.

### 4.22 Transport (WebSocket over TCP) — observable behavior the port replaces with ENet

- Server: `TCPServer.listen(port)` (default 8080); accepts **at most one** pending connection per
  poll/frame; each accepted stream wrapped in a `WebSocketPeer`; `peer_id = randi()` (random u32).
  Per poll: poll every peer; first time a peer reads OPEN → one "connected" event; drain all
  available packets FIFO; state CLOSED → erase peer + "closed" event
  (`websocket_transport.gd:55-90`).
- Client: `WebSocketPeer.connect_to_url(url, TLSOptions.client())`. Connect loop polls every 0.1 s
  up to 5 s. Reconnect: exponential backoff `min(1.0 × 2^attempts, 32.0)` s, max 5 attempts; only
  auto-reconnects after at least one successful connection.
- One message per `send()`; WebSocket preserves message boundaries (no application-level
  re-framing needed on top of the `[type][len]` header — the header exists so BATCH can be peeled
  and for validation).
- Nothing is tuned: no buffer sizing, no NODELAY, no backpressure handling (`send() != OK` is
  logged and dropped).
- Per ENet redesign (D2): ch0 unreliable-sequenced = STATE_UPDATE (+ ACTION_CONFIRM), ch1
  reliable-ordered = GAME_EVENT / CONNECT_AUTH / DISCONNECT / BASELINE_ACK / REQUEST_FULL_STATE /
  RESPAWN_REQUEST, ch2 unreliable-sequenced = PLAYER_INPUT. HEARTBEAT/BATCH deleted (server_ms
  relocated).

---

## 5. Edge cases & gotchas

1. **Truncated packets decode as zeros, silently.** `PacketReader` underflow returns 0/""/empty and
   keeps going. A truncated STATE_UPDATE yields garbage entities (id 0, pos (0,0)) rather than an
   error. The Rust port should hard-fail the packet instead; nothing downstream relies on the
   zero-fill behavior.
2. **`finalize_header` wraps silently** if the payload exceeds 65535 bytes (u16 mask). The only
   guard is the full-state 7280-entity cap; every other packet is small by construction. A Rust
   encoder should assert/error instead.
3. **`write_string` does not clamp the length prefix.** A string with > 65535 UTF-8 bytes writes a
   wrapped u16 length and then all the bytes — corrupting the frame. Reachable in principle via a
   long character name/token in CONNECT_AUTH or PLAYER_INFO. Port must clamp or reject.
4. **HEARTBEAT is 8 bytes on the live path** (`_encode_packet`), even though `heartbeat_packet.gd`
   and the wire-protocol doc say 4. Client sends `server_ms = 0`; `server_ms == 0` is the sentinel
   for "no clock sample in this reply."
5. **REQUEST_FULL_STATE and RESPAWN_REQUEST are not empty**: both carry `[u32 timestamp_ms]`
   (`network_manager.gd:862-869`). The server reads the u32 but ignores the value.
6. **`is_valid_type` accepts 1..13**, including S→C types arriving at the server and vice versa.
   There is no direction check — a client could send the server a STATE_UPDATE and it would decode
   and be emitted to ServerMain (then ignored as unhandled). Port may tighten this.
7. **`server_tick` width is inconsistent**: u32 in STATE_UPDATE, but **u16** in ACTION_CONFIRM,
   PROJECTILE_FIRED, and `client_render_tick`. The u16 fields wrap every 65536 ticks (~36.4 min at
   30 Hz). Consumers compare them against the full tick; the redesign should pick one width (or
   define wrapping comparison) deliberately.
8. **`sequence_number` is u8 and wraps at 256** (`seq & 0xFF` at creation). Reconciliation matches
   on the wrapped value; the replay window must stay < 256.
9. **`Time.get_ticks_msec()` exceeds u32 after ~49.7 days**; all wire timestamps are u32-masked and
   the RTT math corrects a single wrap (`elapsed += 2^32` once). Sessions outliving two wraps
   between heartbeats (impossible at 1 Hz) would break; do the same masking in Rust.
10. **Position quantization truncates toward zero**, does not round. A position of −0.04 encodes as
    0. Together with the 0.05 delta epsilon this means sub-0.05 motion never transmits.
11. **Delta epsilon is strict `<` 0.05 per axis** (both axes must be within epsilon to be "equal").
    Replicate exactly or delta cadence changes (a parity-visible behavior).
12. **A delta entity with mask 0 is omitted entirely** — there is no "keepalive" entry per entity.
    Client-side entity timeout logic must tolerate arbitrarily long silences within a baseline
    interval.
13. **REMOVED handling**: `mark_entity_removed` just erases the cache entry. If the entity later
    re-enters AoI it is "not in cache" → automatic FULL_STATE. REMOVED beats POSITION etc. (no
    payload), but FULL_STATE beats REMOVED if both bits ever set (write and read both check
    FULL_STATE first).
14. **Baseline deferral on AoI exits** (§4.9): `needs_baseline && removals present` ⇒ delta this
    tick, baseline next eligible tick. The 100-tick interval check is `>=` against the *sent*
    baseline tick, so the baseline lands at the first removal-free tick after expiry.
15. **`_pending_baseline_tick = 0` is a sentinel** ("none outstanding"). A genuine baseline at tick
    0 cannot exist (the first baseline goes out when `tick − 0 >= 100`, i.e. tick 100).
    `needs_baseline_resend` also early-returns false while `_baseline_tick == 0`.
16. **BASELINE_ACK acks `server_tick`, not a wire `baseline_tick`** — the Baseline (full-state
    layout) doesn't carry `baseline_tick`. Acks are monotonic-max; stale/duplicate acks are
    ignored.
17. **Full-state response to REQUEST_FULL_STATE ignores AoI** — it contains *all* entities on the
    server and resets the peer's baseline state. It also re-sends PLAYER_INFO for every
    authenticated player (this is how a client discovers its own entity id; "Authority sync").
18. **`peer_id = randi()`** — random u32, no collision guard, not related to entity ids (entity ids
    on the wire are u16: players 1–999, projectiles 10000–29999, monsters 30000–39999).
19. **Disconnect cleanup**: server erases the peer's delta cache, visible-set, scheduler, and byte
    budget (`server_broadcast_service.gd:464-468`); NetworkManager erases heartbeat/announce/bytes
    state. A "closed" event for a never-announced peer does not emit `server_client_disconnected`.
20. **Stale doc fields**: `wire-protocol.md` rows "HEARTBEAT 4 B", "REQUEST_FULL_STATE empty",
    "RESPAWN_REQUEST empty", "`is_valid_type` accepts 1..12", and its §"Entity-flag bitfield… bits
    6–7 free" (bits 6/7 are DASHING/KNOCKED_BACK) are out of date vs code.
21. **SERVER_METRICS tick-time fields wrap** above 655.35 ms (u16 mask, no clamp); the five
    `sched_*` fields are clamped. Decode divides by 100.0.
22. **Color bytes use round-half-away-from-zero** (`roundi`), not truncation like positions.
23. **PLAYER_INFO color and CONNECT_AUTH color/budget are length-gated optional reads**
    (`remaining() >= 3` / `>= 4`). The redesign can make them mandatory, but the port of the *Go
    bot decoder / old clients* assumption disappears with the protocol version handshake (D7).
24. **GDScript `int(x)` semantics** used in encodes: truncation toward zero (f64 → i64), then
    explicit clamps where present. `write_u16(int(ms*100))` with a negative input would mask to a
    huge u16 — tick times are never negative in practice.
25. **No protocol version byte exists anywhere on the wire today.** The redesign adds one in the
    handshake (D7).

---

## 6. Cross-subsystem contracts

### Provided to / expected from other subsystems

- **Server tick/broadcast** (`server-tick-broadcast` extraction): calls `begin_batch()` at tick
  start, `send_to_client(peer, type, data_dict)` during, `flush_batches()` at tick end;
  `broadcast_to_clients(type, data)` fans out per peer. STATE_UPDATE data dict contract:
  `{tick:int, state_flags:int, baseline_tick:int, entities:[{entity_id, entity_type, position,
  animation_state, flags, delta_mask}]}` (entity dicts also accept legacy keys `id`, `type`,
  `animation` via `add_entity_dict`, `state_update_packet.gd:156-167`).
- **DeltaStateCache API** (server broadcast → cache): `calculate_delta_mask(id, state, tick) -> int`,
  `update_cache(id, state, tick)`, `update_cache_partial(id, state, mask, tick)`,
  `cleanup_stale_entities(active_ids) -> removed_ids`, `needs_full_state_for_interval(tick) -> bool`,
  `needs_baseline_resend(tick) -> bool`, `reset_baseline(tick)`, `mark_baseline_acked(tick)`,
  `get_baseline_tick() -> int`.
- **Client prediction** (`client-prediction` extraction): produces the PLAYER_INPUT dict
  `{position, velocity, keys:{up,down,left,right,shoot,ability,sprint,interact,dash}, aim_angle,
  sequence, client_render_tick, client_rtt_ms}` at 30 Hz; consumes ACTION_CONFIRM
  `{sequence_number, corrected_position, result_code, server_tick, stamina, mana}` for
  reconciliation keyed on the u8 sequence.
- **Interpolation** (`interpolation` extraction): consumes STATE_UPDATE dicts (with per-entity
  `delta_mask` — only masked fields authoritative); maintains `last_baseline_tick`; sends
  BASELINE_ACK on every Baseline and REQUEST_FULL_STATE on chain break; consumes
  `NetworkManager.get_server_time_ms()` (0 = unsynced sentinel) for render-time alignment.
- **Hit authority** (D11): LOCAL_HIT_REPORT `[u16 projectile_id]` C→S; monster PROJECTILE_FIRED
  GAME_EVENT must carry a non-zero projectile id in `target_id` plus spawn pos and (u16) fire tick.
- **Auth** (D9 replaces): CONNECT_AUTH carries token/char_id/char_name/region/color/budget; server
  answer is implicit (PLAYER_INFO broadcast = success; today there is no auth-failure packet — the
  server just never authenticates the peer).
- **Transport seam**: server role — `server_listen(port) -> err`, `server_poll()`,
  `server_take_events() -> [{kind, peer_id, bytes?}]` (per-peer FIFO), `server_send(peer, bytes) ->
  bool`, `server_close_peer(peer, code, reason)`, `server_peer_open(peer) -> bool`,
  `server_peer_ids() -> [int]`; client role — `client_connect(url) -> err`, `client_poll()`,
  `client_state() -> LinkState`, `client_take_packets() -> [bytes]` (FIFO), `client_send(bytes) ->
  err`, `client_close(code, reason)`, `client_close_info() -> {code, reason}`, `client_reset()`.
  The ENet implementation replaces exactly this surface.

---

## 7. Rust port hazards (checklist)

- [ ] **Little-endian everywhere**; Rust's default `to_le_bytes` matches — never use BE/network order.
- [ ] **Quantization truncates toward zero** (`int(v * 10.0)`), then clamps to ±32767/−32768. Rust:
      `(v * 10.0).trunc() as i64` then clamp then `as i16` — do **not** use `round()` or rely on
      `as i16` saturation alone (clamp first to match exactly; note −32768 is reachable).
- [ ] **f32 vs f64**: Vector2 components are f32; GDScript scalar math is f64. The delta epsilon
      compare (`absf(a.x − b.x) < 0.05`) operates on f32 values promoted to f64. Keep positions f32
      in `sim_core`/`protocol` or document the divergence.
- [ ] **Color: round-half-away-from-zero**; positions: truncate. Two different rules in one codec.
- [ ] **u8 sequence wrap (256)** and **u16 tick wrap (65536)** in ACTION_CONFIRM /
      PROJECTILE_FIRED / client_render_tick — use `wrapping_*` semantics, not widening.
- [ ] **u32 timestamp wrap** at 2^32 ms (~49.7 days) with the single-wrap correction in RTT math.
- [ ] **`server_ms == 0`, `samples == 0`, `_pending_baseline_tick == 0`, `peek == -1`** are
      sentinels — preserve them or redesign them away explicitly (Option/None is the Rust answer,
      but the *wire* value 0 for server_ms must keep meaning "unstamped" if interop matters
      mid-migration).
- [ ] **Clock-sync EMA**: first sample assigns directly; subsequent `lerp(old, new, 0.2)`;
      half-RTT truncated toward zero (`int(ping/2.0)`). The relocated server_ms packet (D2) must
      feed the same filter or interpolation timing shifts.
- [ ] **Delta-mask precedence**: FULL_STATE (bit 7) checked before REMOVED (bit 6) on both encode
      and decode; mask 0 ⇒ omit entity; masked-field write order is fixed: position, animation,
      flags.
- [ ] **`update_cache_partial`**: only emitted fields update the cache; deferred/withheld fields
      stay dirty. Getting this wrong silently starves LOD-throttled fields forever or re-sends
      everything.
- [ ] **Baseline interval is `>= 100` ticks from the last *sent* baseline**, deferred while AoI
      exits are pending that tick; resend after 30 un-acked ticks; the 100-tick floor must survive
      for non-acking clients (load-test bots).
- [ ] **Baselines bypass the per-peer byte budget** (only the 7280-entity frame cap applies);
      deltas are budgeted (clamp(budget / rate, 256, 1200) B). Don't budget the baseline.
- [ ] **Full-state truncation**: count field and emitted entities derive from one `min()`; if the
      Rust encoder errors instead of truncating, port the `snapshot_count_overflow` diagnostic.
- [ ] **Entity order within a snapshot is not meaningful** (scheduler reorders; removals pinned
      first as staged but selection may interleave) — the client must never assume order; a Rust
      `HashMap` iteration-order difference is fine, but pinned removals must always be emitted.
- [ ] **Reader underflow**: GDScript zero-fills and continues; Rust should return `Err` — verify no
      consumer depends on zero-fill (the 4-byte legacy heartbeat relying on `server_ms → 0` is the
      one known case; it disappears with the protocol redesign).
- [ ] **String fields**: u16-length-prefixed UTF-8, no length clamp on encode today — clamp/reject
      in Rust; on decode, invalid UTF-8 in GDScript produces a best-effort string, Rust should
      decide (lossy vs reject).
- [ ] **Frame-driven socket polling** (not tick-driven) and full-drain per frame; per-peer FIFO
      ordering through the transport is load-bearing for interpolation/reconciliation. ENet
      channels change the ordering domain: FIFO is then per-channel, and STATE_UPDATE vs GAME_EVENT
      cross-ordering guarantees TCP gave (e.g. PLAYER_INFO before the first snapshot referencing
      the entity) disappear — the client already tolerates unknown entities, but verify.
- [ ] **BATCH disappears** under ENet, but its *semantics* — "a tick's packets for a peer leave
      together, in order" — must be re-established or consciously dropped; latency accounting
      (end-of-tick flush ≈ up to one tick of queueing) changes.
- [ ] **HEARTBEAT disappears**, but three of its jobs need new homes: (1) `server_ms` clock sync →
      new packet (snapshot header is the natural carrier), (2) RTT → ENet native, (3) liveness
      timeout (5 s both sides) → ENet native timeout config.
- [ ] **HEARTBEAT/DISCONNECT are transport-level** (consumed in NetworkManager, never reach the
      sim) — keep that layering in the Rust server (ENet connect/disconnect events replace them).
- [ ] **No direction enforcement on packet types** today; the redesign should enforce C→S vs S→C
      type sets at decode.
- [ ] **No protocol version on the wire** today; D7 adds `PROTOCOL_VERSION` checked at handshake —
      don't forget to actually reject mismatches.
- [ ] **SERVER_METRICS stays** (D13) — fixed-length, field-for-field lockstep encode/decode; tick
      times are ×100 fixed-point u16 (unclamped/wrapping), sched fields clamped.
- [ ] **`randi()` peer ids** are an artifact of the WebSocket transport; ENet supplies peer
      handles. Anything keyed on peer_id (caches, budgets, heartbeats) must key on the new handle
      and be erased on disconnect exactly as today (§5.19).
