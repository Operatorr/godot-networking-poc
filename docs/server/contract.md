# Omega server — workspace & wire contract

**Status:** Active (as built) · **Companion:** [`design.md`](design.md) (architecture & rationale).
The wire format, crate APIs, and numerics below are the authoritative spec for `rust/` and the
Godot client extension.

## Workspace

```
rust/
├── Cargo.toml          # [workspace] members = protocol, sim_core, server, client_ext
├── protocol/           # packet structs + hand-rolled bit codec, PROTOCOL_VERSION
├── sim_core/           # movement SM, mover, arena, hit predicates (no godot/net deps)
├── server/             # bin: rusty_enet host, 30 Hz tick thread, ureq I/O thread
└── client_ext/         # cdylib (gdext): ProtocolCodec + PredictionSim + SimHit for GDScript
```

Dependency edges: `server → {protocol, sim_core}`, `client_ext → {protocol, sim_core, godot}`.
`protocol` and `sim_core` depend on nothing network- or Godot-related. Crate pins: rusty_enet
`=0.4.0`, godot 0.5.3 `api-4-6`, ed25519-dalek 2.2, ureq 3.x, tracing, metrics +
metrics-exporter-prometheus.

Extension artifacts are copied into the Godot project: `client/bin/<platform>/` +
`client/bin/omega_client_ext.gdextension` (`compatibility_minimum = 4.6`). Build script:
`scripts/build_client_ext.sh`.

## Numerics policy (sim_core + protocol)

- `Vec2 { x: f32, y: f32 }` — mirrors Godot's single-precision `Vector2`. All vector ops in f32.
- Scalar sim state (timers, stamina, mana, delta) is **f64** — mirrors GDScript loose floats.
  Scalar→vector application casts to f32 at the multiply (e.g. knockback decay:
  `vel *= exp(-9.0 * dt) as f32`).
- Quantization: positions/velocities ×10 **truncate toward zero** then clamp to i16; angles ×100
  same rule. Colors ×255 **round half away from zero** then clamp to u8. Two rules, kept distinct.
- Exact GDScript float parity is **not** load-bearing (client prediction runs this same crate),
  but algorithms are ported faithfully (order of operations, strict `<` comparisons,
  `maxf(0.0, t - dt)` timer decrements) so game feel matches the GDScript server.

## Channels

| Const | # | ENet mode | Rust send | Godot send flags |
|---|---|---|---|---|
| `CH_SNAPSHOT` | 0 | unreliable **sequenced** | `Packet::unreliable` | `0` |
| `CH_RELIABLE` | 1 | reliable ordered | `Packet::reliable` | `FLAG_RELIABLE` |
| `CH_INPUT` | 2 | unreliable sequenced | `Packet::unreliable` | `0` |

ch0: delta `Snapshot`s, `ActionConfirm`. ch1: `AuthResult`, `GameEvent`, `ServerMetrics`,
**baseline `Snapshot`s** (incl. full-state replies) (S→C); `ConnectAuth`, `BaselineAck`,
`RequestFullState`, `RespawnRequest`, `LocalHitReport` (C→S).
ch2: `PlayerInput`. Disconnect uses **native ENet disconnect** with the reason code in the
`data: u32` (no packet). `PROTOCOL_VERSION` rides the ENet connect `data: u32` (low byte) and is
re-checked in `ConnectAuth`; mismatch ⇒ server `disconnect(reason=INVALID_AUTH)` before auth.

Keep every ch0 datagram **< 1200 bytes** (MTU 1392; unreliable > MTU silently upgrades to
reliable-fragmented). The per-peer byte budget enforces this for delta snapshots. Baselines are
exempt from the budget and may exceed the MTU, which is exactly why they ride ch1 reliable
explicitly (must-arrive, acked, fragmentation is fine there). Ordering stays safe: the server
only emits deltas against an ACKED baseline, so no delta referencing tick T can be in flight
before the client holds baseline T.

## New wire format (replaces `[u8 type][u16 len]` framing)

ENet preserves datagram boundaries ⇒ **no length field**. Every packet: `[u8 type][payload]`.
All multi-byte integers little-endian. Bit-level fields are packed LSB-first within a byte stream
by `BitWriter`/`BitReader` (protocol-internal). Strings: u8-length-prefixed UTF-8 (names are short;
encode clamps, decode rejects invalid UTF-8). Decode is strict: underflow or trailing bytes ⇒ `Err`.

### Packet type ids

C→S: `ConnectAuth=1, PlayerInput=2, BaselineAck=3, RequestFullState=4, RespawnRequest=5,
LocalHitReport=6`. S→C: `AuthResult=64, Snapshot=65, ActionConfirm=66, GameEvent=67,
ServerMetrics=68`. Direction is enforced at decode (server decoder accepts only C→S set and
vice versa).

### Typed entity id (bit-level, used inside Snapshot)

`[2-bit kind][offset]` — kind 0 = player (10-bit offset, id = offset, range 1–999), kind 1 =
projectile (15-bit offset, id = 10000 + offset), kind 2 = monster (14-bit offset, id = 30000 +
offset). **Kind 3 (protocol v4) = world effect** (14-bit offset, id = 40000 + offset, range
40000–49999), used for lingering ability effects and Healthorbs. Carries what the old `u16 id + u8
type` carried in 12/17/16 bits.

The world-effect band (40000–49999) is partitioned into 2500-id sub-bands by subtype: `0` healthorb
(40000–42499), `1` mine (42500–44999), `2` dot-zone (45000–47499), `3` bible (47500–49999). These
ride the normal snapshot/AoI/delta machinery like any entity. See
[`../systems/abilities.md`](../systems/abilities.md).

### Snapshot (type 65; deltas ch0, baselines ch1) — the redesigned STATE_UPDATE

Byte-aligned header, then a bitstream of entity records:

```
[u8 type=65][u32 server_tick][u32 server_ms][u8 flags]      # flags bit0 = IS_DELTA, bit1 = BASELINE
if IS_DELTA: [u32 baseline_tick]
[u16 entity_count]
then bitstream:
  Baseline / full record:  [typed-id][3-bit anim][16-bit entity_flags][16-bit qx][16-bit qy]
  Delta record:            [typed-id][5-bit mask]
                           mask bit0 POSITION  -> [16-bit qx][16-bit qy]
                           mask bit1 ANIMATION -> [3-bit anim]
                           mask bit2 FLAGS     -> [16-bit entity_flags]
                           mask bit3 REMOVED   -> nothing
                           mask bit4 FULL      -> full-record fields (anim, flags, qx, qy)
final byte padded with zeros
```

Entity flags are **16 bits** since protocol v2 (were 8): bits 0–7 keep the legacy values
(ALIVE, MOVING, ATTACKING, INVULNERABLE, STUNNED, VISIBLE, DASHING, KNOCKED_BACK); bit 8 =
DAZED (daze timer active — sprint/dash locked out, walking allowed); bit 9 = **STEALTH**
(protocol v4 — invisible to AI targeting; set by Rogue Shadowstep, see
[`../systems/abilities.md`](../systems/abilities.md)); bits 10–15 reserved for future status effects.
Protocol v3 added the per-player class byte to ConnectAuth and PLAYER_INFO (see those sections).

`server_ms` (server monotonic ms, u32-wrapped) is the **relocated HEARTBEAT clock-sync** — every
snapshot carries it; the client feeds the same EMA filter (first sample direct, then alpha 0.2)
using ENet-native RTT for the half-trip estimate. Mask precedence on decode: FULL before REMOVED.
Mask 0 entities are omitted by the encoder (cost zero bits). Entity order is not meaningful.
Baseline packets set `BASELINE`, never `IS_DELTA`; the client acks with `BaselineAck{server_tick}`.
Delta/baseline cadence and ack/resend as built: 100-tick baseline interval, 30-tick resend,
per-peer budget clamp 256..1200 B, baselines exempt from the budget.

### PlayerInput (type 2, ch2) — 22 B (was 18 B; protocol v4 adds the cursor)

`[u8 type][u8 seq][u16 input_flags][s16 aim_angle_q][s16 qx][s16 qy][s16 qvx][s16 qvy]
[u16 client_render_tick][u16 client_rtt_ms][s16 cursor_qx][s16 cursor_qy]`

Field semantics as built (seq wraps at 256; render_tick = low 16 bits of server tick;
position is the client's predicted position, server validates against thresholds). **Protocol v4**
appends the **cursor** as two `s16` (world position, 0.1-unit quantization, +4 B) — the aim point for
the Class ability (point-target Mageblast/Plague Zone clamp to `max_cast_range`; target-search
Shadowstep searches near it; movement Charge uses it for direction). One of the `input_flags` bits is
the RMB **ability-held** flag. See [`../systems/abilities.md`](../systems/abilities.md).

### ActionConfirm (type 66, ch0) — 12 B

`[u8 type][u8 seq][u8 action][s16 qx][s16 qy][u8 result][u16 server_tick][u8 stamina][u8 mana]`
(stamina/mana = `clamp(round(v), 0, 255)`).

### ConnectAuth (type 1, ch1)

`[u8 type][u8 protocol_version][u16 ticket_len][ticket bytes][u8 name_len][utf8 name]
[u8 r][u8 g][u8 b][u8 class][u32 character_id][u32 bandwidth_budget_bps]`

`class` (since protocol v3) is the player class: `0=Zealot, 1=VoidHunter, 2=Engineer,
3=PlagueSeer, 4=Warrior, 5=Rogue, 6=Mage`. It is **identity metadata chosen by the client** —
the codec accepts any u8 on the wire; the server clamps on join (values > 6 are treated as 0)
and does **not** validate it against account data yet. The clamped value is echoed back in
every PLAYER_INFO broadcast.

`character_id` (`u32`, **protocol v4**) tells the server *which* character to **hydrate** level/XP
for from the Go API (the ADR 0005 hydrate-on-join step; progression is now server-authoritative — see
[`../systems/PROGRESSION.md`](../systems/PROGRESSION.md) and [ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md)).
In signed-ticket mode it must match the `character_id` inside the verified ticket; in dev mode
(`--allow-unsigned-tickets`) the server trusts it like the rest of the self-reported identity.

Ticket blob: `[u8 ticket_version=1][u32 character_id][u8 region][u64 issued_at_unix_ms]
[u64 expires_at_unix_ms][64-byte Ed25519 signature]` — all multi-byte fields **little-endian**;
signature over the 22 preceding payload bytes, signed by the Go API. Dev mode
(`--allow-unsigned-tickets`): `ticket_len == 0` is accepted and `character_id` is assigned by the
server (a placeholder unique among concurrent players; POC parity with today's trust-the-client).
A non-empty but malformed ticket is refused client-side — the codec returns empty bytes and the
handshake aborts (no silent unsigned downgrade).

Minting API (implemented): `POST /api/character/ticket` (JWT-protected) returns
`{ "ticket": "<base64 of the 86-byte blob>", "character_id", "region", "expires_at_ms" }`. The
region `u8` map mirrors `region_from_string` (`asia`/`local`/unknown→0, `europe`→1, `us-west`→2,
`us-east`→3). The payload layout is pinned to the verifier by a shared test vector
(`api/internal/auth/ticket_test.go` ⇄ `rust/server/src/auth.rs::go_cross_language_ticket_vector`).
Env: `OMEGA_TICKET_PRIVKEY` (api.env, 32-byte hex seed) ⇄ `OMEGA_TICKET_PUBKEY` (server.env);
generate a pair with `go run ./cmd/gen_ticket_key`.

> The full HTTP/JSON surface of the Go API (auth, characters, regions, leaderboard) — as
> consumed by web/CMS clients — is documented in [`../api/cms-api.md`](../api/cms-api.md).
> This section covers only the game-connect ticket the Rust server verifies.

### AuthResult (type 64, ch1)

`[u8 type][u8 result]` then on success: `[u16 entity_id][u32 server_tick][u8 tick_rate]`.
result: `0=OK, 1=BAD_VERSION, 2=BAD_TICKET, 3=EXPIRED, 4=WRONG_REGION, 5=SERVER_FULL,
6=DUPLICATE_SESSION`. Success also fast-paths Authority sync (client learns its entity id without
waiting for the PLAYER_INFO broadcast, which is still sent for names/colors).

### GameEvent (type 67, ch1)

`[u8 type][u8 event_type][u16 source_id][u16 target_id][tail]` — event types and tails as built,
except where protocol v4 noted: DAMAGE `[u16 amount][u8 dmg_type]`;
KILL/KILL_PVP none; RESPAWN `[s16 qx][s16 qy]`; PLAYER_INFO
`[u8 len][utf8 name][s16 qx][s16 qy][u8 r][u8 g][u8 b][u8 class]`
(class since protocol v3 — server-clamped to 0..=6, see ConnectAuth);
LEADERBOARD_UPDATE `[u8 n]{n × [u16 id][u16 kills]}`; PROJECTILE_FIRED
`[s16 qx][s16 qy][u16 fire_tick]` with target_id = projectile id (**non-zero for monster shots** —
hit-authority invariant); EXP_GAIN=13 `[u16 amount]` with source_id = the player who earned it (one event
per nearby player when a monster dies — the HUD "+XP" pop only; progression itself is now
server-authoritative, see [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md)).

**Protocol v4 additions:**
- **PICKUP=6** now carries `[u8 kind][u16 amount]` (was empty) — `kind` identifies the picked-up
  world effect (e.g. Healthorb), `amount` the magnitude (Healthorb heals +5 HP); target_id = the
  picked-up entity. Server-authoritative pickup.
- **ABILITY_EFFECT=14** `[u16 effect_id][s16 qx][s16 qy][u16 radius]` with source_id = the casting
  player — a one-shot VFX/SFX cue for a Class ability (blast/cast/hitscan center + radius). All
  ability *damage* is decided server-side; this event is the client's render hook. See
  [`../systems/abilities.md`](../systems/abilities.md).
- **PROGRESS=15** `[u16 level][u32 experience][s16 move_speed_q]` with source_id = the player — the
  authoritative level/XP/move-speed push that replaced the old client-owned level number (see
  [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md) and
  [ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md)).

### ServerMetrics (type 68, ch1) — 1 Hz

33-byte field set (as built), prefixed by the type byte.

### BaselineAck (3): `[u8 type][u32 baseline_tick]` · RequestFullState (4) / RespawnRequest (5):
`[u8 type]` · LocalHitReport (6): `[u8 type][u16 projectile_id]`

## Protocol v4 — the Class-ability + server-authoritative-progression bump

`PROTOCOL_VERSION` advances to **4** (v3 added the class byte; v4 adds the ability system and moves
progression server-side). The full delta versus v3, in one place — each is detailed in its section
above:

| Change | Where | Delta |
|---|---|---|
| Cursor target | `PlayerInput` (type 2) | append `[s16 cursor_qx][s16 cursor_qy]` → **22 B** (was 18); + an RMB ability-held `input_flags` bit |
| Character id | `ConnectAuth` (type 1) | insert `[u32 character_id]` (hydrate which character — ADR 0005) |
| World-effect entity kind | typed-id (in Snapshot) | **kind tag 3**, id band **40000–49999**, 2500-id sub-bands: 0 healthorb, 1 mine, 2 dot-zone, 3 bible |
| `STEALTH` flag | 16-bit entity_flags | **bit 9** (invisible to AI targeting; Rogue Shadowstep) |
| `ABILITY_EFFECT=14` | `GameEvent` (type 67) | new: `[u16 effect_id][s16 qx][s16 qy][u16 radius]` (ability VFX cue) |
| `PROGRESS=15` | `GameEvent` (type 67) | new: `[u16 level][u32 experience][s16 move_speed_q]` (authoritative progression push) |
| `PICKUP=6` payload | `GameEvent` (type 67) | now `[u8 kind][u16 amount]` (was empty) — Healthorb +5 HP etc. |

Lockstep client/server deploy as always (DIY versioning): a v3↔v4 mismatch is refused at the
handshake (`ConnectAuth` re-check). The new fields are all server-authoritative in effect — abilities,
progression, and pickups are decided by the server; the client request (ability flag + cursor) stays
advisory, per "the client requests, the server decides." See
[`../systems/abilities.md`](../systems/abilities.md) and [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md).

## sim_core public API (consumed by server + client_ext)

```rust
pub mod constants;                         // every GameConstants value, exact names/values
pub struct Vec2 { pub x: f32, pub y: f32 } // f32 ops mirroring Godot Vector2 (incl. normalized()
                                           // -> ZERO on zero vector, is_equal_approx)
pub mod arena {
    pub const OBSTACLES: [Rect; 16];
    pub fn clamp_to_bounds(p: Vec2) -> Vec2;
    pub fn circle_intersects_obstacle(c: Vec2, r: f32) -> bool;     // Chebyshev expanded-rect test
    pub fn move_with_obstacle_collision(from: Vec2, to: Vec2, radius: f32) -> Vec2;
    pub fn line_intersects_obstacle(from: Vec2, to: Vec2) -> Option<Vec2>;
    pub fn closest_point_on_segment(p: Vec2, a: Vec2, b: Vec2) -> Vec2;
    pub fn is_valid_player_spawn_position(p: Vec2) -> bool;         // + monster variant
}
pub enum MoveState { Idle, Walking, Sprinting, Dashing, KnockedBack, Stunned, AbilityMovement }
pub struct MovementSm { /* state, stamina/mana f64, timers, velocities, edge latches */ }
impl MovementSm {
    pub fn tick(&mut self, dt: f64, move_dir: Vec2, sprint: bool, dash: bool,
                ability: bool, attacking: bool, aim_dir: Vec2) -> Vec2;   // velocity to integrate
    pub fn try_dash(&mut self, move_dir: Vec2, aim_dir: Vec2) -> bool;
    pub fn apply_knockback(&mut self, dir: Vec2, force: f64, multiplier: f64);
    pub fn end_sprint(&mut self); pub fn apply_stun(&mut self, d: f64);
    pub fn set_resources(&mut self, stamina: f64, mana: f64); pub fn reset(&mut self);
    pub fn ground_speed(&self, sprinting: bool) -> f32;
    // queries: state(), stamina(), mana(), dash_cooldown_remaining(), is_input_locked(), …
}
pub struct InputCmd { pub flags: u16, pub aim_angle: f32 }   // helpers: move_dir(), aim_dir(), …
pub fn step_player(sm: &mut MovementSm, pos: Vec2, dt: f64, cmd: &InputCmd) -> StepResult;
    // tick SM -> integrate velocity*dt -> move_with_obstacle_collision -> realized velocity
pub struct StepResult { pub position: Vec2, pub velocity: Vec2 /* realized */ }
pub mod hit {
    pub fn is_client_authoritative(owner_id: u16) -> bool;     // owner >= 30000
    pub fn swept_hit(self_pos: Vec2, prev: Vec2, cur: Vec2, hit_radius: f32) -> bool;
    pub fn flight_origin(cur: Vec2, dir: Vec2, dist: f32) -> Vec2;
    pub fn is_hit_plausible(start: Vec2, end: Vec2, recent: &[Vec2], threshold: f32) -> bool;
}
```

`MovementSm` keeps GDScript's exact transition guards, the `_prev_dash_held` edge latch, the
intra-tick order (timers → stamina(previous state) → mana → edges → actions → dispatch), and
**no depenetration** (a center inside an expanded obstacle freezes — port verbatim).

## client_ext GDScript surface

- `ProtocolCodec` (RefCounted, `#[class(init)]`): `encode_connect_auth(...)`, `encode_input(...)`,
  `encode_baseline_ack(tick)`, `encode_request_full_state()`, `encode_respawn_request()`,
  `encode_local_hit_report(projectile_id)` → `PackedByteArray`; `decode_server_packet(bytes:
  PackedByteArray) -> Dictionary` (key `"type"`, then per-packet keys mirroring the decoded
  dicts — snapshot entities as `Array[Dictionary]` with `entity_id/entity_type/position/
  animation_state/flags/delta_mask`). One boundary call per packet.
- `PredictionSim` (RefCounted): wraps a `MovementSm`; `step(delta, position, move_dir, sprint,
  dash, ability, attacking, aim_dir) -> Dictionary {position, velocity, state, stamina, mana,
  dash_cooldown, moving}`; `replay_step(position, input_flags, delta) -> Dictionary`
  (reconciliation replay); `set_resources(stamina, mana)`, `reset()`, plus query/config helpers
  (`stamina()`, `mana()`, `movement_state()`, `set_world_geometry(...)`, `set_ability_config(...)`,
  daze/charge helpers).
- `SimHit` (RefCounted): the static hit predicates shared with the server — `swept_hit(self_pos,
  prev, cur, hit_radius)`, `is_client_authoritative(owner_id)`, `flight_origin(...)`.

## Server architecture

Single 30 Hz tick thread owning the ENet host and the whole world. Per tick: drain
`host.service()` → decode → route; apply inputs (per-player latched flags, `_pending_dash`,
6-tick stale timeout); step players via `sim_core::step_player`; monster AI; record monster
position history (lag comp ring, ≥ 6 ticks); step projectiles + collision pass (two-netcode model:
server skips monster-owned vs players, validates `LocalHitReport` plausibility, lenient
backstop ON); deaths/respawns/leaderboard; build + send per-peer snapshots (AoI grid + hysteresis,
DeltaStateCache port, byte budget) + ActionConfirms + events; `host.flush()`; sleep remainder
(1–5 ms slices with `service()` to keep ENet acks timely). Side I/O (Go API heartbeat,
persistence seam) on a separate thread over `std::sync::mpsc`; Prometheus exporter on its own
listener; `SERVER_METRICS` packet kept.

The 2 s region heartbeat (`POST /api/regions/heartbeat`, Redis TTL 5 s) is the **sole liveness
signal** for `GET /api/regions` and `POST /api/regions/select`: the API lists a region iff a
fresh heartbeat reports it online. The WebSocket-era TCP reachability probe is gone — the
server is UDP-only (ADR 0003), so there is no TCP endpoint to probe.

Config: `server_config.json`-compatible keys + env/CLI overrides; `--allow-unsigned-tickets`
defaults **on** for the POC (it's the load-test/dev default in `deployment/env/server.env`),
**off** when you require signed tickets; Ed25519 public key via
`OMEGA_TICKET_PUBKEY` (hex/base64) when enforcement is on.

## Invariants (enforced in review + tests)

Entity id ranges (players 1–999, projectiles 10000–29999, monsters 30000–39999) · arena bounds
±1000, walls ±1005 (visual; sim clamps center to ±1000) · 0.1-unit position quantization ·
delta-vs-baseline with acks · per-peer byte budget with 256 B floor / 1200 B cap, baselines
exempt · hit-authority invariants (server skips `owner_id >= 30000` in its player-collision
pass; `LocalHitReport` applies only to the reporter's own entity and rejects player-owned
projectiles; monster `PROJECTILE_FIRED` carries non-zero projectile id; client tests against
rendered position) · the client requests, the server decides.
