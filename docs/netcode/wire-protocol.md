# Wire protocol & packet formats

**Status:** Implemented (verified 2026-06-04 against code; #11 u16 widen, #13 `CONNECT_AUTH` budget,
#14 `BASELINE_ACK`, and #15 `SERVER_METRICS` `sched_*` fields all landed).

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

`packet_types.gd:16-29`. Direction and payload size as built today:

| #  | Type                | Dir   | Payload                              | Schema                       |
| -- | ------------------- | ----- | ------------------------------------ | ---------------------------- |
| 1  | `PLAYER_INPUT`      | C→S   | 16 B fixed                           | `player_input_packet.gd`     |
| 2  | `STATE_UPDATE`      | S→C   | variable (Snapshot)                  | `state_update_packet.gd`     |
| 3  | `GAME_EVENT`        | S→C   | variable, per event type             | `game_event_packet.gd`       |
| 4  | `HEARTBEAT`         | C↔S   | 4 B (`[u32 timestamp_ms]`)           | `heartbeat_packet.gd`        |
| 5  | `ACTION_CONFIRM`    | S→C   | 9 B                                  | `action_confirm_packet.gd`   |
| 6  | `CONNECT_AUTH`      | C→S   | variable (strings + budget)          | `auth_packet.gd`             |
| 7  | `DISCONNECT`        | C→S   | 5 B                                  | `disconnect_packet.gd`       |
| 8  | `REQUEST_FULL_STATE`| C→S   | empty (header only)                  | —                            |
| 9  | `RESPAWN_REQUEST`   | C→S   | empty (header only)                  | —                            |
| 10 | `SERVER_METRICS`    | S→C   | variable (1/sec)                     | —                            |
| 11 | `BATCH`             | S→C   | framed sub-packets                   | (transport)                  |
| 12 | `BASELINE_ACK`      | C→S   | 4 B (`[u32 baseline_tick]`)          | — (inline in `network_manager.gd`) |

`is_valid_type()` accepts `1..12` (`packet_types.gd:133-134`).

## STATE_UPDATE — the Snapshot

`state_update_packet.gd`. Two modes selected by `state_flags` bit `STATE_FLAG_IS_DELTA`
(`packet_types.gd:78`). The packet prefix (wire header + state header) differs by mode:

**Full-state Snapshot** — 10-byte prefix (was 9 before the u16 widen), then 9 bytes/entity:

```
[u8 type=2][u16 len]        3  wire header
[u32 server_tick]           4
[u8 state_flags]            1  (delta bit clear)
[u16 entity_count]          2  ← u16 (was u8); ceiling is now the byte budget, not 255
per entity (9 B):
  [u16 entity_id]           2
  [u8 entity_type]          1  (1=PLAYER 2=MONSTER 3=PROJECTILE)
  [s16 pos_x][s16 pos_y]    4  0.1-unit
  [u8 animation_state]      1
  [u8 flags]                1  (ENTITY_FLAG_* bitfield)
```

`state_update_packet.gd:5-14`, write `:193-204`, read `:253-263`, `ENTITY_SIZE := 9` (`:32`).

**Delta Snapshot** — 14-byte prefix (adds `baseline_tick`; was 13 before the u16 widen), then 3–10 bytes/entity:

```
[u8 type=2][u16 len]        3
[u32 server_tick]           4
[u8 state_flags]            1  (STATE_FLAG_IS_DELTA set)
[u32 baseline_tick]         4  ← tick of the Baseline this diffs against
[u16 entity_count]          2  ← u16 (was u8); ceiling is now the byte budget, not 255
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

`state_update_packet.gd:16-27`, write `:208-231`, read `:267-311`, sizes `:366-383`. The smallest
delta entity (3 B) is a bare removal; the largest (10 B) is an inline full-state entity inside a
delta packet (e.g. a freshly-spawned entity). A position-only delta is 7 B.

### Delta mask (8-bit, `packet_types.gd:68-74`)

| Bit | Constant                 | Meaning                                   |
| --- | ------------------------ | ----------------------------------------- |
| 0   | `DELTA_MASK_POSITION`    | position present (4 B)                    |
| 1   | `DELTA_MASK_ANIMATION`   | animation present (1 B)                   |
| 2   | `DELTA_MASK_FLAGS`       | flags present (1 B)                       |
| 6   | `DELTA_MASK_REMOVED`     | despawn marker, no payload                |
| 7   | `DELTA_MASK_FULL_STATE`  | full entity inline (Baseline of one)      |

Bits 3–5 are unused. The Snapshot reader merges each delta against the client's last known state
for that `entity_id` (`state_update_packet.gd:289-309`); unchanged fields are carried forward, so
a stale-but-present entity costs only its 3-byte id+mask.

### Baseline cadence

`DELTA_FULL_STATE_INTERVAL := 100` (`packet_types.gd:85`): the server forces a full-state
Baseline every 100 Ticks regardless of what changed (~3.3 s at the 30 Hz tick; the inline comment
is now correct; see [`server-tick-broadcast.md`](server-tick-broadcast.md)). The client now
**acks** each received Baseline via a `BASELINE_ACK` packet (below); the server tracks the per-peer
acked/pending Baseline and resends on a gap rather than waiting out the full 100-Tick cadence. This
ack path is **inert on today's TCP** transport (reliable in-order delivery never drops a Baseline)
— it is forward-looking for the [ADR 0003](../adr/0003-enet-udp-transport.md) ENet/UDP transport,
where a dropped ch0 datagram is real.

### Resolved: `entity_count` was a u8 capping a Snapshot at 255 entities

**Fixed (2026-06-04).** Both writers previously capped the count with `mini(entities.size(), 255)`
on a **u8** field, so any Snapshot with >255 entities was **silently truncated** — and the
periodic, **unbudgeted** Baseline (which emits every AoI entity at full 9/10 bytes) was the most
likely place to brush it.

`entity_count` is now a **u16**. The wire field's numeric ceiling is
`STATE_MAX_ENTITIES = 65535` (`packet_types.gd:13`), but that is **not** the real
per-packet limit: a Snapshot is bounded by `MAX_PACKET_SIZE` (the `u16` payload-length
frame, 65535 B). So the **full-state** writer caps emission at the byte-derived
`STATE_MAX_FULL_ENTITIES = (MAX_PACKET_SIZE − FULL_STATE_HEADER_BYTES) / ENTITY_SIZE = 7280`
(`state_update_packet.gd:38-46,210`) — the most entities that fit one Baseline in a frame
(7280×9 + 10 = 65530 ≤ 65535) — while the **delta** writer keeps the `STATE_MAX_ENTITIES`
field cap (`:225`) because delta packets are byte-bounded by the per-peer `SnapshotScheduler`
budget (`max_snapshot_bytes`, ~1200 B) long before the count matters. Both readers
`read_u16` (`:268,283`). The old hard 255 cliff is **gone**, and a packet now runs out of
*bytes* (not *count*) first. The broadcast service increments a `snapshot_count_overflow`
diagnostic and `push_warning`s if a Baseline would exceed the full-state frame cap
(`server_broadcast_service.gd:506-512`), surfaced via `SERVER_METRICS`. This was a wire change
with **no `PROTOCOL_VERSION` byte added** (see "wire-v3" below — the remaining size
optimizations are still unbuilt).

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

### Input-flag bitfield (`packet_types.gd:51-58`)

`MOVE_UP=1<<0, MOVE_DOWN=1<<1, MOVE_LEFT=1<<2, MOVE_RIGHT=1<<3, SHOOT=1<<4, ABILITY=1<<5,
SPRINT=1<<6, INTERACT=1<<7`. Encode/decode helpers at `packet_types.gd:138-162`.

### Entity-flag bitfield (`packet_types.gd:60-66`)

`ALIVE=1<<0, MOVING=1<<1, ATTACKING=1<<2, INVULNERABLE=1<<3, STUNNED=1<<4, VISIBLE=1<<5`.
Carried in the entity `flags` byte of STATE_UPDATE; bits 6–7 free.

## GAME_EVENT — discrete occurrences

`game_event_packet.gd`. Common 5-byte head then per-type tail (write `:142-188`, read `:192-251`):

```
[u8 event_type][u16 source_id][u16 target_id]   5 B head
… type-specific tail …
```

`GameEventType` (`packet_types.gd:88-101`) and the tail each one serializes:

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
`[u8 reason_code][u32 timestamp_ms]`, `reason_code` from `DisconnectReason` (`packet_types.gd:104-111`).

**CONNECT_AUTH** (C→S, variable) — `auth_packet.gd`:
`[string token][string char_id][string char_name][u8 region][u8 r][u8 g][u8 b][u32 bandwidth_budget_bps]`.
Strings are length-prefixed `[u16 len][utf8]` (`packet_writer.gd:100-115`). `region` is the `Region`
enum (`auth_packet.gd:13-18`). Color is optional-on-wire (read only if ≥3 bytes remain). The trailing
**`[u32 bandwidth_budget_bps]`** is the client's advertised egress budget in bytes/sec (#13,
`auth_packet.gd:33,82-85`); it is append-only and **length-gated on read** (old clients omit it and the
server then falls back to `default_client_bandwidth_bps`). u32 because a realistic budget (~60k–200k B/s)
overflows u16. The server clamps it to `[min,max]` config and derives each peer's per-Snapshot byte cap
`= clamp(budget / snapshot_rate_hz, 256, max_snapshot_bytes)` — see
[`server-tick-broadcast.md`](server-tick-broadcast.md).

**BASELINE_ACK** (C→S, 4 B payload) — encoded/decoded inline in `network_manager.gd` (`:848`-ish
encode, `:1017` decode), not a `*_packet.gd` class: `[u32 baseline_tick]`. The client sends one on
**every** received full-state Baseline, carrying that Baseline's `server_tick`
(`interpolation_controller.gd:185`); the server marks the per-peer Baseline acked
(`server_broadcast_service.gd:446-452` → `delta_state_cache.gd:218-224`). **Inert on TCP** (Baselines
don't drop); forward-looking for the [ADR 0003](../adr/0003-enet-udp-transport.md) ENet transport.

**SERVER_METRICS** (S→C, fixed-length, 1 Hz) — encoded inline in `network_manager.gd:863-880`,
decoded `:1003-1015`. A flat little-endian record (no entity loop):

```
[u32 tick_count]                4
[u16 avg_tick_time_ms ×100]     2  fixed-point ×100
[u16 max_tick_time_ms ×100]     2  fixed-point ×100
[u16 player_count]              2
[u16 entity_count]              2
[u32 total_bytes_sent]          4
[u32 total_bytes_received]      4
[u32 avg_bandwidth_per_client]  4  bytes/sec
── appended scheduler diagnostics (#15) ──
[u16 sched_entities_deferred]   2
[u16 sched_max_queue_age_ticks] 2
[u8  sched_peers_at_budget_pct] 1
[u16 sched_peers_evaluated]     2
[u16 sched_snapshot_overflow]   2  (the #11 wire-cap overflow counter)
```

The five trailing `sched_*` fields are the scheduler diagnostics plumbed from
`ServerBroadcastService.last_tick_diagnostics` → `ServerMetrics` → this packet → the HUD
`server_status` panel. They are a **fixed-length append** — encode and decode must stay in lockstep
(`mini()`/`clampi()` guard against u16/u8 overflow at the 1000-player target). See
[`performance-budgets.md`](performance-budgets.md).

## Planned: wire-v3 (remaining size optimizations)

The load-bearing **`entity_count` u8 → u16** widen **shipped (2026-06-04)** — see "Resolved" above.
Two encoding-only optimizations from the original v3 list remain unbuilt (tracked in
`plans/CODEX_NETWORK_PERFORMANCE_UPGRADES.md` Phase 4):

1. **s8 small-delta positions** — most per-tick movement is ≤±12.7 units (player speed 200 ⇒
   ~6.7 u/tick at 30 Hz), so a 1-byte-per-axis small-delta mode would halve the 4-byte position
   field for the common case, falling back to s16 only on large jumps/teleports.
2. **Drop redundant `entity_type` in deltas** — `entity_type` never changes after spawn, yet a
   full-state delta entity re-sends it every Baseline (`state_update_packet.gd:220,279`); the
   client already caches it from the prior full state.

Each is encoding-only. Note that **no protocol-version byte was added** with the u16 widen — there is
still no version byte on the wire, so either remaining optimization would need a compatibility
strategy of its own.

## The eight questions

- **Client:** encodes `PLAYER_INPUT`/`CONNECT_AUTH` (with the trailing bandwidth budget)/`HEARTBEAT`/`DISCONNECT`/`REQUEST_FULL_STATE`/`RESPAWN_REQUEST`/`BASELINE_ACK`; decodes every S→C packet.
- **Server:** encodes `STATE_UPDATE`/`GAME_EVENT`/`ACTION_CONFIRM`/`HEARTBEAT`/`SERVER_METRICS`, packs them into `BATCH`; decodes client input/auth.
- **Predicted:** nothing here — the wire format carries predicted *inputs* (`PLAYER_INPUT`) and authoritative *corrections* (`ACTION_CONFIRM`), but encoding itself predicts nothing.
- **Replicated:** all world state, as quantized full-state or delta entities in `STATE_UPDATE`, diffed against a Baseline every 100 Ticks.
- **Persisted:** nothing — the wire layer is in-memory framing only; the Go API persists accounts/characters/leaderboard out of band.
- **Validated:** `PacketReader._check_bounds` guards every read against buffer underflow (`packet_reader.gd:29-33`); `is_valid_type` range-checks the type byte; the u16 length bounds the frame.
- **Can fail:** a Baseline above the full-state frame cap (`STATE_MAX_FULL_ENTITIES = 7280`) is **truncated to fit** `MAX_PACKET_SIZE` rather than overflowing the `u16` length frame — far harder to hit than the old u8 255 cap (unreachable at the 100-player POC), and signalled by `snapshot_count_overflow`; a dropped Baseline is repaired by the `BASELINE_ACK` resend path (inert on TCP, live on the planned ENet transport); position outside ±3276.7 → clamped (irrelevant inside the 2000² Arena).
- **Tested:** round-trip unit tests on each `*_packet.gd` (`write()` → `from_buffer()`); the Python bot decoder tracks the u16 `entity_count`, the appended `SERVER_METRICS` `sched_*` fields, and the trailing `CONNECT_AUTH` budget in lockstep; the `BASELINE_ACK` resend path has **no** loss-injection test today (it is inert on TCP).

## See also

- [`server-tick-broadcast.md`](server-tick-broadcast.md) — when Snapshots are built and the Baseline cadence
- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — which entities make it into a viewer's Snapshot (and the byte budget)
- [`transport-websocket.md`](transport-websocket.md) — `BATCH` framing and the channel these bytes ride on
- [`client-prediction.md`](client-prediction.md) — how `PLAYER_INPUT` sequence numbers drive Reconciliation
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Snapshot, Baseline, Game event, Authority sync)
