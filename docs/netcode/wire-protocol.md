# Wire protocol & packet formats

**Status:** Implemented (verified 2026-06-03 against code).

> The binary format every byte on the wire conforms to. All numbers here are read directly from
> `packet_writer.gd` / `packet_reader.gd` and the per-packet schema classes under
> `client/scripts/shared/networking/packets/`. Little-endian throughout (Godot default,
> `packet_writer.gd:3`). This doc covers **encoding**; for *when* and *to whom* Snapshots are sent
> see [`server-tick-broadcast.md`](server-tick-broadcast.md) and [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md),
> and for the channel they ride on see [`transport-websocket.md`](transport-websocket.md).

## Frame header

Every packet — client→server and server→client — begins with a 3-byte header
(`packet_types.gd:7` `HEADER_SIZE := 3`):

| Field            | Type | Bytes | Notes                                              |
| ---------------- | ---- | ----- | -------------------------------------------------- |
| `type`           | u8   | 1     | `PacketTypes.Type` enum                            |
| `payload_length` | u16  | 2     | payload bytes after the header                     |

Written by `packet_writer.write_header()` (a placeholder length) then patched by
`finalize_header()` (`packet_writer.gd:191-203`). `MAX_PACKET_SIZE = 65535`
(`packet_types.gd:10`) — the u16 length field can't describe a larger payload.

The transport stacks **multiple** such framed packets into one `BATCH` (type 11) WebSocket frame
server→client (`packet_types.gd:24`); the reader peels them off by `payload_length`. See
[`transport-websocket.md`](transport-websocket.md).

## Quantization

Positions, velocities and angles are quantized to fixed-point s16 (`packet_writer.gd:126-159`,
`packet_reader.gd:154-176`):

| Quantity | Scale                  | Wire   | Precision | Range (clamped)        |
| -------- | ---------------------- | ------ | --------- | ---------------------- |
| position | `POSITION_SCALE = 10`  | 2×s16  | 0.1 unit  | −3276.8 … +3276.7      |
| velocity | `VELOCITY_SCALE = 10`  | 2×s16  | 0.1 unit  | −3276.8 … +3276.7      |
| aim      | `ANGLE_SCALE = 100`    | 1×s16  | 0.01 rad  | ±327.67 rad            |

A `Vector2` therefore costs **4 bytes** on the wire. The Arena is only 2000×2000
(`MAP_MIN −1000,−1000 .. MAP_MAX 1000,1000`), well inside the ±3276.7 range, so position clamping
never bites in normal play.

## Message types (`PacketTypes.Type`)

`packet_types.gd:13-25`. Direction and payload size as built today:

| #  | Type                | Dir   | Payload                              | Schema                       |
| -- | ------------------- | ----- | ------------------------------------ | ---------------------------- |
| 1  | `PLAYER_INPUT`      | C→S   | 16 B fixed                           | `player_input_packet.gd`     |
| 2  | `STATE_UPDATE`      | S→C   | variable (Snapshot)                  | `state_update_packet.gd`     |
| 3  | `GAME_EVENT`        | S→C   | variable, per event type             | `game_event_packet.gd`       |
| 4  | `HEARTBEAT`         | C↔S   | 4 B (`[u32 timestamp_ms]`)           | `heartbeat_packet.gd`        |
| 5  | `ACTION_CONFIRM`    | S→C   | 9 B                                  | `action_confirm_packet.gd`   |
| 6  | `CONNECT_AUTH`      | C→S   | variable (strings)                   | `auth_packet.gd`             |
| 7  | `DISCONNECT`        | C→S   | 5 B                                  | `disconnect_packet.gd`       |
| 8  | `REQUEST_FULL_STATE`| C→S   | empty (header only)                  | —                            |
| 9  | `RESPAWN_REQUEST`   | C→S   | empty (header only)                  | —                            |
| 10 | `SERVER_METRICS`    | S→C   | variable (1/sec)                     | —                            |
| 11 | `BATCH`             | S→C   | framed sub-packets                   | (transport)                  |

`is_valid_type()` accepts `1..11` (`packet_types.gd:125-126`).

## STATE_UPDATE — the Snapshot

`state_update_packet.gd`. Two modes selected by `state_flags` bit `STATE_FLAG_IS_DELTA`
(`packet_types.gd:74`). The packet prefix (wire header + state header) differs by mode:

**Full-state Snapshot** — 10-byte prefix, then 9 bytes/entity:

```
[u8 type=2][u16 len]        3  wire header
[u32 server_tick]           4
[u8 state_flags]            1  (delta bit clear)
[u8 entity_count]           1  ← u8: HARD CAP 255
per entity (9 B):
  [u16 entity_id]           2
  [u8 entity_type]          1  (1=PLAYER 2=MONSTER 3=PROJECTILE)
  [s16 pos_x][s16 pos_y]    4  0.1-unit
  [u8 animation_state]      1
  [u8 flags]                1  (ENTITY_FLAG_* bitfield)
```

`state_update_packet.gd:5-14`, write `:193-202`, read `:249-259`, `ENTITY_SIZE := 9` (`:32`).

**Delta Snapshot** — 14-byte prefix (adds `baseline_tick`), then 3–10 bytes/entity:

```
[u8 type=2][u16 len]        3
[u32 server_tick]           4
[u8 state_flags]            1  (STATE_FLAG_IS_DELTA set)
[u32 baseline_tick]         4  ← tick of the Baseline this diffs against
[u8 entity_count]           1  ← u8: HARD CAP 255
per entity (variable):
  [u16 entity_id]           2
  [u8 delta_mask]           1
  ── then, gated by delta_mask ──
  full state  (DELTA_MASK_FULL_STATE): type1 + pos4 + anim1 + flags1  → 10 B total
  removed     (DELTA_MASK_REMOVED):    nothing                        →  3 B total
  position    (DELTA_MASK_POSITION):   pos4
  animation   (DELTA_MASK_ANIMATION):  anim1
  flags       (DELTA_MASK_FLAGS):      flags1
```

`state_update_packet.gd:16-27`, write `:206-227`, read `:263-307`, sizes `:362-379`. The smallest
delta entity (3 B) is a bare removal; the largest (10 B) is an inline full-state entity inside a
delta packet (e.g. a freshly-spawned entity). A position-only delta is 7 B.

### Delta mask (8-bit, `packet_types.gd:64-70`)

| Bit | Constant                 | Meaning                                   |
| --- | ------------------------ | ----------------------------------------- |
| 0   | `DELTA_MASK_POSITION`    | position present (4 B)                    |
| 1   | `DELTA_MASK_ANIMATION`   | animation present (1 B)                   |
| 2   | `DELTA_MASK_FLAGS`       | flags present (1 B)                       |
| 6   | `DELTA_MASK_REMOVED`     | despawn marker, no payload                |
| 7   | `DELTA_MASK_FULL_STATE`  | full entity inline (Baseline of one)      |

Bits 3–5 are unused. The Snapshot reader merges each delta against the client's last known state
for that `entity_id` (`state_update_packet.gd:285-305`); unchanged fields are carried forward, so
a stale-but-present entity costs only its 3-byte id+mask.

### Baseline cadence

`DELTA_FULL_STATE_INTERVAL := 100` (`packet_types.gd:78`): the server forces a full-state
Baseline every 100 Ticks regardless of what changed (the inline comment "~5 seconds at 20Hz" is
**stale** — the server ticks at 30 Hz, so this is ~3.3 s; see [`server-tick-broadcast.md`](server-tick-broadcast.md)).
There is **no Baseline ack** — the client cannot tell the server which Baseline it actually holds;
it trusts that a delta's `baseline_tick` matches state it kept. A dropped Baseline followed by
deltas reconstructs against a wrong prior until the next forced Baseline.

### Correctness cliff: u8 `entity_count` caps a Snapshot at 255 entities

Both writers cap the count with `mini(entities.size(), 255)` (`state_update_packet.gd:194,207`).
`entity_count` is a **u8** — a Snapshot physically cannot describe more than 255 entities, and the
overflow is **silently truncated**, not split across packets. At MMO target densities this is a
real ceiling: 200 players + up to 100 monsters (`MONSTER_MAX_COUNT`) + projectiles can exceed 255
*visible* entities for one viewer. The per-viewer AoI + budget scheduler
([`interest-mgmt-aoi.md`](interest-mgmt-aoi.md)) usually keeps a single viewer's list under that,
but nothing in the wire layer *enforces* it: if the scheduler hands ≥256 entities to `write()`,
entities past index 254 vanish for that client with no error. Worse, the periodic **Baseline is
unbudgeted** — it tries to emit every AoI entity at full 9/10 bytes, so it is the most likely place
to brush the cap (and the per-peer 1200-byte snapshot budget). Wire-v3 (below) lifts this to u16.

## PLAYER_INPUT — client intent (16-byte payload)

`player_input_packet.gd:1-11`, write `:79-86`, read `:90-99`. Fixed 16 bytes:

| Field               | Type    | Bytes | Notes                                            |
| ------------------- | ------- | ----- | ------------------------------------------------ |
| position            | 2×s16   | 4     | client's predicted position (for validation)     |
| velocity            | 2×s16   | 4     | quantized velocity                               |
| input_flags         | u8      | 1     | WASD + shoot/ability/sprint/interact bitfield    |
| aim_angle           | s16     | 2     | radians ×100                                     |
| sequence_number     | u8      | 1     | **wraps at 256** — Reconciliation key            |
| client_render_tick  | u16     | 2     | server tick remote entities were rendered at     |
| client_rtt_ms       | u16     | 2     | client-measured RTT, clamped 0…65535             |

Sent at 30 Hz from `_physics_process` (see [`client-prediction.md`](client-prediction.md)). The
8-bit `sequence_number` (`:50` `seq & 0xFF`) bounds the server's replay window — the client's
replay buffer is 256 deep. `client_render_tick` lets the server reconstruct what the shooter saw
for PvE [Lag compensation](../CONTEXT.md); `client_rtt_ms` feeds server-side latency stats.

### Input-flag bitfield (`packet_types.gd:47-54`)

`MOVE_UP=1<<0, MOVE_DOWN=1<<1, MOVE_LEFT=1<<2, MOVE_RIGHT=1<<3, SHOOT=1<<4, ABILITY=1<<5,
SPRINT=1<<6, INTERACT=1<<7`. Encode/decode helpers at `packet_types.gd:130-154`.

### Entity-flag bitfield (`packet_types.gd:57-62`)

`ALIVE=1<<0, MOVING=1<<1, ATTACKING=1<<2, INVULNERABLE=1<<3, STUNNED=1<<4, VISIBLE=1<<5`.
Carried in the entity `flags` byte of STATE_UPDATE; bits 6–7 free.

## GAME_EVENT — discrete occurrences

`game_event_packet.gd`. Common 5-byte head then per-type tail (write `:142-188`, read `:192-251`):

```
[u8 event_type][u16 source_id][u16 target_id]   5 B head
… type-specific tail …
```

`GameEventType` (`packet_types.gd:81-94`) and the tail each one serializes:

| #  | Event                | Tail on the wire                                              |
| -- | -------------------- | ------------------------------------------------------------ |
| 1  | `DAMAGE`             | `[u16 amount][u8 damage_type]`                               |
| 2  | `KILL`               | — (ids only)                                                  |
| 3  | `RESPAWN`            | `[s16 pos_x][s16 pos_y]` (entity in `target_id`)            |
| 4  | `EFFECT_APPLY`       | `[u8 effect_id][u16 duration_ms]`                            |
| 5  | `EFFECT_REMOVE`      | `[u8 effect_id]`                                             |
| 6  | `PICKUP`             | — (not serialized today)                                     |
| 7  | `LEVEL_UP`           | — (not serialized today)                                     |
| 8  | `CHAT_MESSAGE`       | — (not serialized today)                                     |
| 9  | `PLAYER_INFO`        | `[string name][s16 pos_x][s16 pos_y][u8 r][u8 g][u8 b]`     |
| 10 | `KILL_PVP`           | — (ids only)                                                  |
| 11 | `LEADERBOARD_UPDATE` | `[u8 n] n×([u16 entity_id][u16 pvp_kills])`                  |
| 12 | `PROJECTILE_FIRED`   | `[s16 pos_x][s16 pos_y][u16 server_tick]`                    |

Note the id convention: `PLAYER_INFO` and `RESPAWN` carry the subject in `target_id` with
`source_id=0` (`game_event_packet.gd:78-79,98`). `PLAYER_INFO` is the [Authority sync](../CONTEXT.md)
signal — it tells a client its own entity id, name, server-authoritative spawn position and color.
The trailing color is read defensively (`:236` only if ≥3 bytes remain), so old clients/packets
without it still parse.

## Smaller fixed packets

**ACTION_CONFIRM** (S→C, 9 B payload) — `action_confirm_packet.gd:79-84`:
`[u8 sequence_number][u8 action_type][s16 x][s16 y][u8 result_code][u16 server_tick]`. Echoes a
client input `sequence_number` with the server's authoritative position and a result code
(`ResultCode` enum `:22-29`) for Reconciliation.

**HEARTBEAT** (C↔S, 4 B payload) — `heartbeat_packet.gd:30-31`: `[u32 timestamp_ms]`. Sent 1 Hz;
the server's reply carries `server_ms`, which the client uses for clock-offset estimation (EMA,
α 0.2) and RTT. Connection times out after 5 s of silence. See
[`transport-websocket.md`](transport-websocket.md).

**DISCONNECT** (C→S, 5 B payload) — `disconnect_packet.gd:37-39`:
`[u8 reason_code][u32 timestamp_ms]`, `reason_code` from `DisconnectReason` (`packet_types.gd:97-104`).

**CONNECT_AUTH** (C→S, variable) — `auth_packet.gd:70-75`:
`[string token][string char_id][string char_name][u8 region][u8 r][u8 g][u8 b]`. Strings are
length-prefixed `[u16 len][utf8]` (`packet_writer.gd:100-115`). `region` is the `Region` enum
(`auth_packet.gd:13-18`). Color is optional-on-wire (read only if ≥3 bytes remain, `:85`).

## Planned: wire-v3

Not built. Tracked in `plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md` (Phase 4). Three changes:

1. **`entity_count` u8 → u16** in STATE_UPDATE — removes the 255-entity silent-truncation cliff
   above (the load-bearing fix).
2. **s8 small-delta positions** — most per-tick movement is ≤±12.7 units (player speed 200 ⇒
   ~6.7 u/tick at 30 Hz), so a 1-byte-per-axis small-delta mode would halve the 4-byte position
   field for the common case, falling back to s16 only on large jumps/teleports.
3. **Drop redundant `entity_type` in deltas** — `entity_type` never changes after spawn, yet a
   full-state delta entity re-sends it every Baseline (`state_update_packet.gd:216,275`); the
   client already caches it from the prior full state.

Each is encoding-only and gated behind a protocol-version negotiation that does not exist today
(there is no version byte on the wire — adding one is implied by v3).

## The eight questions

- **Client:** encodes `PLAYER_INPUT`/`CONNECT_AUTH`/`HEARTBEAT`/`DISCONNECT`/`REQUEST_FULL_STATE`/`RESPAWN_REQUEST`; decodes every S→C packet.
- **Server:** encodes `STATE_UPDATE`/`GAME_EVENT`/`ACTION_CONFIRM`/`HEARTBEAT`/`SERVER_METRICS`, packs them into `BATCH`; decodes client input/auth.
- **Predicted:** nothing here — the wire format carries predicted *inputs* (`PLAYER_INPUT`) and authoritative *corrections* (`ACTION_CONFIRM`), but encoding itself predicts nothing.
- **Replicated:** all world state, as quantized full-state or delta entities in `STATE_UPDATE`, diffed against a Baseline every 100 Ticks.
- **Persisted:** nothing — the wire layer is in-memory framing only; the Go API persists accounts/characters/leaderboard out of band.
- **Validated:** `PacketReader._check_bounds` guards every read against buffer underflow (`packet_reader.gd:29-33`); `is_valid_type` range-checks the type byte; the u16 length bounds the frame.
- **Can fail:** Snapshot exceeding 255 entities → silent truncation (u8 cap); dropped Baseline with no ack → deltas reconstruct against wrong state until the next forced Baseline; position outside ±3276.7 → clamped (irrelevant inside the 2000² Arena).
- **Tested:** round-trip unit tests on each `*_packet.gd` (`write()` → `from_buffer()`); the truncation cliff and missing-Baseline-ack paths have **no** test today.

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — when Snapshots are built and the Baseline cadence
- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — which entities make it into a viewer's Snapshot (and the byte budget)
- [`transport-websocket.md`](transport-websocket.md) — `BATCH` framing and the channel these bytes ride on
- [`client-prediction.md`](client-prediction.md) — how `PLAYER_INPUT` sequence numbers drive Reconciliation
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Snapshot, Baseline, Game event, Authority sync)
