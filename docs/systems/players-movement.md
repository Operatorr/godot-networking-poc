# Players & movement

**Status:** Implemented (verified 2026-06-14 against `rust/` + `client/`). The Local player is
predicted by the **shared Rust `sim_core`** (run through the `client_ext` GDExtension) and is
authoritatively integrated by the **Rust `omega-server`** running the *same* compiled crate, so
prediction cannot diverge by construction. The old "double-movement / steering boat" bug is
**fixed** — the `prediction_owns_movement` seam (below) makes the `PredictionController` the sole
mover of the networked Local player.

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md): **Local player** is predicted and owned
> between corrections; every other character is a **Remote entity**, drawn by **Interpolation**,
> never predicted. **Tick** (server sim step, 30 Hz) ≠ **Frame** (client draw) ≠ **Snapshot**
> (the `Snapshot` broadcast, type 65).

> **One authority.** The only authoritative server is the Rust **`omega-server`** binary
> (`rust/server/`), a single-threaded synchronous 30 Hz tick over `rusty_enet`. The legacy
> GDScript headless server is retired (NetworkManager refuses server mode); the scripts under
> `client/scripts/server/` are parity-only ground truth and do **not** run. Movement authority
> lives in `rust/server/src/sim/player.rs`; the shared per-step integration lives in
> `rust/sim_core/src/step.rs`.

## What a player is

On the client a player is one `CharacterBody2D`, `MOTION_MODE_FLOATING` (top-down, no gravity).
There are two visual classes:

| Class | Script | Moved by | Collision | Input |
|---|---|---|---|---|
| Local player | `Player` (`client/scripts/entities/player/player.gd`) | `PredictionController` (sole owner) | layer 1 / mask 6 (`player.tscn:58-59`; mask 6 = Walls + Monsters) | yes — predicted |
| Remote entity (player) | `RemotePlayer` (`remote_player.gd`) | `InterpolationController` | layer 1 / mask 4 (`remote_player.tscn:55-56`) | none |

`RemotePlayer` runs **no** `_physics_process` and processes no input; its position is written by
interpolation and its animation/flags come straight from Snapshot data via `update_from_network()`.

On the **server** a player is a `PlayerState` (`rust/server/src/sim/player.rs`): an `entity_id` in
**1–999** (`PLAYER_ENTITY_ID_MAX`, recycled within range), a `position`/`velocity`, an `aim_angle`,
a `MovementSm` (the shared movement state machine), HP, and the per-class progression hydrated from
the Go API. Client collision *layers* are cosmetic only — the server's collision is the analytic
mover in `sim_core` (`move_with_obstacle_collision`), not Godot physics. The Local player carries
the same **7-state movement state machine** (`MovementSm` in `rust/sim_core`, mirrored by
`MovementStateMachine` in GDScript) with two resources — **stamina** (gates sprint) and **mana**
(gates the RMB class ability) — alongside HP; dash, charge, knockback, and stun are first-class
states. See [`players-movement-state-machine.md`](players-movement-state-machine.md).

## Movement model

The shared per-step integration is one function — `step_movement()`
(`rust/sim_core/src/step.rs`) — called identically by the server's `PlayerState::step`
(`rust/server/src/sim/player.rs`) and by the client predictor (`PredictionSim::step`, driven from
`prediction.gd::_apply_local_prediction`). One step is: **SM tick → integrate velocity → analytic
obstacle mover → recompute realized velocity**.

| Quantity | Value | Source |
|---|---|---|
| Base speed | per-class, level-scaled (≈195–215 u/s at level 1) | `ability::effective_base_speed` (`rust/server/src/sim/ability.rs`); mirrored in `prediction.gd` `CLASS_ABILITY_CONFIG` |
| Sprint | gated by stamina + exhaustion + daze | `MovementSm` (`rust/sim_core/src/movement.rs`) |
| Dash / Warrior Charge / Rogue Shadowstep | dash 720 u/s; Charge 720 u/s × 945 u, steerable (follows the cursor) and draining Mana per unit travelled (`set_charge_mana_drain`); blink to cursor | `MovementSm`; class config pushed via `set_ability_config` |
| Direction | normalized WASD vector | `movement_direction()` (`rust/sim_core/src/step.rs`); client mirror `prediction.gd::_get_direction_from_flags` |
| Hitbox radius | `PLAYER_HITBOX_RADIUS` 16 | `rust/sim_core/src/constants.rs` |

Direction is the four WASD bits summed into a vector then `.normalized()` — opposite keys cancel
exactly, the zero vector stays zero, and **diagonals are not faster** (`step.rs`
`movement_direction`, with unit tests `opposite_keys_cancel` / `diagonal_not_faster`). That is free
analog direction built from 8 discrete key combinations; there is no facing quantization. Aim is
independent of movement (mouse world angle, `prediction.gd::_get_aim_angle`).

Collision against the **map bounds and arena obstacles** is analytic, not physics-engine:
`move_with_obstacle_collision()` (`rust/sim_core/src/arena.rs`) clamps to bounds and slides
axis-separated. Because both server and client call the *same compiled* `sim_core`, the server, the
prediction step, and the reconciliation replay integrate identically — the world geometry is set
per-instance (Arena ±1000 with obstacles; Sanctuary ±3328×±3072, no obstacles) via
`arena::set_world_geometry`, pushed into the client sim before the first predicted step
(`arena_base.gd`).

### Per-class movement abilities (predicted vs. server-only)

Only **Warrior Charge** and **Rogue Shadowstep (blink)** are *predicted* movement — they live in
`MovementSm` and run client-side through the shared sim, so they feel instant. Every other RMB class
ability (Mage/Plague Seer cast, etc.) costs Mana and produces a server-decided effect that arrives
as a `GameEvent`; it does not move the Local player's predicted position. Classes are the protocol
class byte `0 Zealot, 1 VoidHunter, 2 Engineer, 3 PlagueSeer, 4 Warrior, 5 Rogue, 6 Mage`; only
Warrior/Rogue/Mage are in pre-alpha scope. See [`abilities.md`](abilities.md) and
[`../server/contract.md`](../server/contract.md) (ConnectAuth class byte).

### Two state machines — animation vs. motion

Do not confuse them:

- `Player.MovementState` / `Player.ActionState` (`player.gd`) — an **animation-only** pair
  (IDLE/WALKING; NONE/ATTACKING/HIT/DEAD) that drives sprite-animation priority. It is **not** the
  netcode movement source.
- The **authoritative motion** machine is the shared `MovementSm` (`rust/sim_core/src/movement.rs`):
  IDLE / WALKING / SPRINTING / DASHING / CHARGING / KNOCKED_BACK / STUNNED. The server owns one per
  `PlayerState`; the client predicts an identical instance inside `PredictionSim`. It produces the
  velocity that `step_movement` integrates. See
  [`players-movement-state-machine.md`](players-movement-state-machine.md).

For a Remote entity the animation state and the DASHING / KNOCKED_BACK / STUNNED / DAZED / STEALTH
**entity flags** arrive over the wire (`rust/server/src/sim/player.rs::update_entity_flags`) and are
applied in `remote_player._update_animation()`.

### Directional sprites — facing follows movement, not aim

With class spritesheets active, the 8-way facing **row** is derived from the **movement direction**
(the observed position delta), kept when stationary — `player.gd` mirrors `remote_player.gd` so
local and remote players animate consistently. The body still rotates to the aim (that drives
shooting), but the artwork is counter-rotated and the row tracks motion. The locomotion tier
(idle/run/sprint/dash) comes from the observed speed against thresholds between the tier speeds
(`player.gd::_locomotion_base`).

## HP (server-authoritative)

On the server, HP is `PlayerState.health` / `max_health` (`rust/server/src/sim/player.rs`): level-scaled
max via `apply_class_and_level`, `take_damage` clamps to 0 and one-shot `mark_dead`, smooth
`update_health_regen`. On the client, `HPComponent` (`hp_component.gd`) is a **display/reconciliation
mirror only** — `set_hp()` is the authoritative path written from server `GameEvent`s and Snapshot
flags; the client never decides its own death. Death sets the entity's ALIVE flag off; dead players
keep replicating (animation DEATH, flags == VISIBLE) and are not despawned.

The death transition + respawn countdown on the client (`arena_base.gd::_enter_local_death`) is driven
**only** by server-authoritative signals — the reliable `KILL` / `KILL_PVP` event (exact server
timing), with the ALIVE-flag snapshot as a backstop — **never** by the client's predicted HP reaching
0. Letting predicted HP trigger death would start the respawn countdown before the server agreed the
player was dead, and the server would then reject the respawn (`is_alive` still true) until its real
HP drained — the "stuck on Respawning…" hang.

The HUD HP bar's **cap** is class+level-scaled to match the server's `max_health`: `Player`
mirrors the Rust `ClassStats` (`_HP_BASE` / `_HP_PER_LEVEL`) and computes
`max_hp = base + per_level·(level−1)` (`apply_level_scaled_max_hp`, applied at spawn and on every
`PROGRESS` event; a level-up fills to the new max, matching the server's full HP+mana restore). HP
itself is not carried in snapshots, so the bar's *current* value is reconciled the same way as
stamina/mana: `ActionConfirm` carries the owner's authoritative `health` (protocol v5), and
`prediction.gd::_handle_action_confirm` snaps `hp_component` to it each confirm — keeping the bar in
step with server-side regen and any damage the delta tracking missed. The reconciliation is gated to
**alive only** (`health > 0`); death never comes from HP, only the reliable KILL/KILL_PVP event.

## Local player: predicted

The Local player is simulated immediately on input, before the server confirms — see
[`../netcode/client-prediction.md`](../netcode/client-prediction.md) for the full loop. In brief
(`client/scripts/network/prediction.gd`):

- Input is captured every Frame and **sent at 30 Hz** inside `_physics_process`
  (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`). Each send carries WASD/action flags, aim angle,
  cursor world position, the client render tick, and RTT, on **ch2** (`PlayerInput`, type 2).
- Prediction calls `PredictionSim::step` — *literally the server's `step_movement`* — to advance
  `predicted_position`/`predicted_velocity` and the predicted stamina/mana.
- 8-bit wrapping sequence numbers; replay buffer up to 256 inputs (`max_buffer_size`).
- Reconciliation snaps `predicted_position` to the server position when drift exceeds
  `server_position_epsilon = 4` u, then replays unacked inputs through the deliberately-simplified
  stateless ground model `PredictionSim::replay_step` (`sim_core` `replay_ground_step` — ground
  speed only, never replays dash/charge/knockback/stun; brief states heal on the next Snapshot).
- Visual correction: smooth lerp at `interpolation_speed = 12.0`, unless the correction exceeds
  `teleport_threshold = 150` u, which snaps instantly (and `reset_physics_interpolation()` so the
  render lerp doesn't smear across the snap).
- The Local player slaves its DAZED and DASHING/CHARGING edges to the server's authoritative entity
  flags (`prediction.gd::_update_own_flags` / `_update_own_charge`) so a server-applied daze or a
  charge end releases the prediction exactly when the server does, instead of rubber-banding.

Confirmations ride **ch0** as `ActionConfirm` (type 66): `[seq][action][s16 qx][s16 qy][result]
[u16 server_tick][u8 stamina][u8 mana]` — see [`../server/contract.md`](../server/contract.md).
Quantization is wire-frozen: positions ×10 truncate-toward-zero clamped to `i16`; stamina/mana ×255
round-half-away clamped to `u8`.

## Remote players: interpolated

Drawn ~66.7 ms (2 Ticks) in the past from buffered Snapshots — see
[`../netcode/interpolation.md`](../netcode/interpolation.md). `RemotePlayer` is a passive visual:
position written by `InterpolationController`, animation/flags from network state. Invulnerability /
stealth flash or dim the sprite.

## Server authority & validation (movement)

Per tick the server drains each authenticated player's input queue (`ingest_input`), runs exactly
one `step` (`rust/server/src/sim/player.rs`), and records an 8-tick position history for lag
compensation. Ingest details: dead players discard input; SHOOT *rising edges* queue pending shots;
DASH latches across same-tick overwrites; the last packet's flags persist; flags zero out after
`STALE_INPUT_TICK_LIMIT = 6` ticks of silence. The input queue is capped at
`MAX_INPUT_QUEUE_SIZE = 10`, drop-oldest.

After integrating, `step` compares the **server's** resulting position to the client's last reported
position and classifies the deviation (`rust/sim_core/src/constants.rs`):

| Threshold | Value | Meaning | Source |
|---|---|---|---|
| `POSITION_TOLERANCE` | 75 u | informational only — **never branched on** | `constants.rs` |
| `CORRECTION_THRESHOLD` | 112.5 u | deviation strictly above ⇒ `correction_needed` (server sends a correction) | `constants.rs` |
| `TELEPORT_THRESHOLD` | 150 u | deviation strictly above ⇒ `cheat_detected` + correction | `constants.rs` |

The result is folded into a `MoveResult` (only for players that had fresh input) whose `position`
is the **server's** authoritative position and whose `success = !correction_needed`. A non-success
result becomes the `ActionConfirm` correction the client reconciles to. The client's own
`teleport_threshold` (150 u) is the *visual* snap cutoff and happens to match `TELEPORT_THRESHOLD`;
they are separate constants for separate jobs (server cheat flag vs. client correction style).
Governing rule everywhere: **the client requests, the server decides.**

## The `prediction_owns_movement` seam (the old double-movement bug, fixed)

**History:** the Local player used to drift/overshoot ("steering boat") because two integrators
owned the same node — `Player.gd`'s own `move_and_slide()` *and* the `PredictionController`'s
analytic writer — disagreeing on speed and collision model and leapfrogging each other.

**Fix (in effect on this branch):** `Player.prediction_owns_movement` is the single seam.
`arena_base.gd::_spawn_local_player` sets it `true` on the networked Local player and never re-enables
`Player.gd` movement:

- `local_player.set_input_enabled(false)`
- `local_player.set_local_projectile_spawning_enabled(false)` (server owns projectile spawning)
- `local_player.prediction_owns_movement = true`

With the seam on, `Player._physics_process` **skips its own `move_and_slide()`** (`player.gd`:
"`if not prediction_owns_movement: move_and_slide()`") and `_handle_movement` early-returns its
velocity integration, only keeping `movement_state` (animation) in sync. The `PredictionController`
is the sole writer of `player_node.position`. So even where `arena_base.gd` later calls
`set_input_enabled(true)` (on authority sync and on respawn), that re-enables only aim/animation
input — not a second integrator — and the bug cannot recur.

> **Offline parity:** the *same* `player.gd` drives offline practice/Sanctuary modes with
> `prediction_owns_movement = false`. There `Player.gd` is the authoritative mover and ticks its
> own GDScript `MovementStateMachine` (dash/sprint/knockback + stamina/mana) — one shared player
> script, two modes. See [`offline-modes.md`](offline-modes.md).

> Distinct from the "looks like 30 fps" stutter
> ([`../netcode/smoothness-render.md`](../netcode/smoothness-render.md)): that is a render-pacing
> problem affecting *all* motion; this seam is about *who integrates the Local player*. Both could
> be present independently.

## The eight questions

- **Client:** captures input, predicts the Local player via the shared `sim_core` step,
  interpolates Remote players, renders HP/animation, draws cosmetic muzzle flash.
- **Server:** authoritative — integrates every player with the *same* `sim_core` step, validates
  moves, owns HP and death, owns projectile spawning and progression.
- **Predicted:** the Local player's position/velocity + stamina/mana (`prediction.gd` →
  `PredictionSim`); Warrior Charge / Rogue Shadowstep blink. Nothing else.
- **Replicated:** every player's position, animation state, entity flags, HP via `Snapshot`
  (type 65) — deltas on ch0, baselines on ch1.
- **Persisted:** nothing in-match — gameplay state is server-authoritative and in-memory. Only
  account/character/progression/leaderboard persist, owned by the Go API (Postgres + Redis).
- **Validated:** server deviation vs. `CORRECTION_THRESHOLD` / `TELEPORT_THRESHOLD`
  (`POSITION_TOLERANCE` is informational); stale-input zeroing; queue cap; class byte clamp.
- **Can fail:** packet loss (heals on the next Snapshot reconcile); a server-applied
  knockback/daze the client hadn't predicted (slaved to the entity flag); double-movement is
  **resolved** by the `prediction_owns_movement` seam.
- **Tested:** `sim_core` unit tests (`rust/sim_core/src/step.rs`: walk speed, bounds clamp,
  diagonal/cancel, replay-matches-walk, replay-never-dashes); `cargo test --workspace`; the Godot
  net smoke (`scenes/test/net_smoke.tscn`) and the offline sandbox. No automated end-to-end
  movement-regression test in the engine yet.

## See also

- [`players-movement-state-machine.md`](players-movement-state-machine.md) — the 7-state `MovementSm` (stamina/mana, dash/charge/knockback/stun)
- [`../netcode/client-prediction.md`](../netcode/client-prediction.md) — the Local player prediction/reconciliation loop
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how Remote players are drawn
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — the separate 30 Hz render-pacing stutter
- [`../server/design.md`](../server/design.md) · [`../server/contract.md`](../server/contract.md) — server architecture & the as-built wire/API contract
- [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) — the two-netcode hit model (movement is server-authoritative)
- [`../CONTEXT.md`](../CONTEXT.md) · [`../../AGENTS.md`](../../AGENTS.md) — glossary and invariant list
