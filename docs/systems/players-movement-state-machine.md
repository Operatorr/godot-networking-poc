# Player movement state machine (dash · sprint · knockback · stun · daze · stamina · mana)

**Status:** Implemented (verified 2026-06-11 against code; HUD layout verified by import, not yet
by a live play-test). Updated 2026-06-12: real daze (hit while sprinting), knockback along
projectile travel direction with per-projectile force.

A **7-state, server-authoritative** movement model for the Local player, predicted on the client for
zero-latency feel. It replaces the old stateless `direction × speed` movement (sprint was a bare
multiplier) with a real state machine plus two resources. One shared class —
`MovementStateMachine` (`client/scripts/shared/player/movement_state_machine.gd`) — is driven
**identically** by the server (`PlayerState.step`) and the client (`PredictionController.
_apply_local_prediction`), so prediction stays in step and the existing position-reconciliation path
corrects any divergence.

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md). **Tick** (30 Hz server sim) = **Frame** here
> (the client `_physics_process` runs at the server tick rate), so client and server advance the SM
> in near-lockstep. Transport is reliable TCP/WebSocket, so input is never dropped.

## States

`enum State { IDLE, WALKING, SPRINTING, DASHING, KNOCKED_BACK, STUNNED, ABILITY_MOVEMENT }`

| State | Velocity each tick | Enters when | Leaves to |
|---|---|---|---|
| IDLE | zero | no move input | WALKING/SPRINTING on input |
| WALKING | `dir × base × speed_mult` | move input, not sprinting | IDLE / SPRINTING / DASHING / … |
| SPRINTING | `dir × sprint × speed_mult` | move + sprint held + stamina > MIN | WALKING when released/empty/attacked/damaged |
| DASHING | constant dash velocity | dash edge (cooldown ready) | IDLE after `DASH_DURATION` |
| KNOCKED_BACK | decaying impulse | `apply_knockback()` | IDLE below `END_SPEED` |
| STUNNED | zero (input blocked) | `apply_stun()` / `apply_root()` | IDLE when the stun timer ends |
| ABILITY_MOVEMENT | externally-set velocity | `start_ability_movement()` | IDLE on `end_ability_movement()` |

**Daze is a timer, not a state.** `apply_daze(duration)` locks out sprint and dash (walking,
knockback, and ability velocities proceed normally) and coexists with KNOCKED_BACK — the usual
companion on a hit. Applied server-side when a player is **hit while SPRINTING**
(`combat::apply_player_hit` in `rust/server`); replicated via `ENTITY_FLAG_DAZED` (bit 8 — entity
flags are u16 on the wire since protocol v2). The client slaves its predicted daze to that flag
(apply on the rising edge, `clear_daze()` on the falling edge — `PredictionController.
_update_own_flags`) and shows the `DazeIndicator` circling-stars visual above the player's head
(local and remote). Offline modes apply the same rule locally in `Player._on_hp_changed`. Bots
mirror the flag the same way (`rust/load_test/src/bot.rs`).

## Numbers (all in `game_constants.gd`)

| Quantity | Constant | Value |
|---|---|---|
| Dash speed | `PLAYER_DASH_SPEED` = base × `PLAYER_DASH_MULTIPLIER` | 600 u/s (3×) |
| Dash duration | `PLAYER_DASH_DURATION` | 0.4 s |
| Dash cooldown | `PLAYER_DASH_COOLDOWN` (START-relative) | 5.5 s (≈5.1 s usable gap) |
| Knockback decay / end / base force | `PLAYER_KNOCKBACK_DECAY` / `_END_SPEED` / `_BASE_FORCE` | 9.0 / 12 u/s / 450 |
| Per-projectile knockback force | `PLAYER/MONSTER_PROJECTILE_KNOCKBACK_FORCE` | 450 (varies per weapon/item later) |
| Daze duration (hit while sprinting) | `PLAYER_DAZE_DURATION` | 1.5 s |
| Stamina max / drain / regen / sprint-min | `PLAYER_STAMINA_*` | 100 / 35 ps / 20 ps / 5 |
| Mana max / regen / ability cost | `PLAYER_MANA_*` | 100 / 10 ps / 25 |
| Speed-mult clamp (Haste/Slow) | `PLAYER_SPEED_MULT_MIN/MAX` | 0.25 … 2.5 |

**Triggers.** Dash is **edge-triggered** on `dash` (Spacebar) — the client latches the press and
sets `INPUT_FLAG_DASH` (bit 8; `input_flags` widened u8→u16) in exactly one input; the server detects
the rising edge (latched in `PlayerState._pending_dash` against same-tick overwrite). Dash direction
is the move direction, or the **aim direction** when standing still. Sprint activates while held and
drains stamina; it ends on attack (SHOOT held) or on taking damage (`Player._on_hp_changed`
decrease → `end_sprint()`). The ability input (RMB) spends mana via `try_use_mana()`.

## Status effects

`apply_speed_modifier()` / `clear_speed_modifier()` (Haste/Slow, clamped) and `apply_root()`→stun
remain placeholders for a future manager (search `TODO(StatusEffectManager)`). **Daze is real**
(see above): a sprint/dash lockout timer with `is_dazed()` / `get_daze_remaining()` queries,
`daze_started` / `daze_ended` signals, and the `ENTITY_FLAG_DAZED` wire bit. Stun cancels an
in-progress dash; daze refuses new dashes without touching the cooldown. Knockback is applied
server-side from projectile impacts (`combat::apply_player_hit`) **along the projectile's travel
direction** (predictable "shot from the left ⇒ thrown right"; fallback: away from the impact point
when no direction is known — the old away-from-impact rule felt random because the discrete-tick
overlap test can place the impact point past the target's center). The impulse is the projectile's
per-spawn `knockback_force` — per-projectile so future weapons/items/abilities can vary it; the
`apply_knockback(dir, force, multiplier)` multiplier is the buff/debuff hook on top.

## Replication & the reconciliation caveat

Movement state is replicated to remote viewers via four entity flags — `ENTITY_FLAG_DASHING`,
`ENTITY_FLAG_KNOCKED_BACK` (bits 6/7), `ENTITY_FLAG_STUNNED`, and `ENTITY_FLAG_DAZED` (bit 8;
entity flags are u16 on the wire since protocol v2). Stamina/mana are an **owner-only**
sync riding the ~30 Hz `ACTION_CONFIRM` (two trailing bytes), applied via `set_resources()`.

Reconciliation replay (`prediction._replay_input`) recomputes position from the SM's **ground**
speed (walk/sprint, stamina-gated, Haste/Slow-scaled — `get_ground_speed`). It intentionally does
**not** re-simulate dash/knockback/stun velocity during replay: those transient states are brief and,
because both sides start them on the same input over reliable TCP, rarely span a correction. Any
residual is fixed by the next snapshot.

## The eight questions

- **Client:** predicts the full SM (state, dash/knockback/stun, stamina/mana) on `Player.movement_sm`,
  consulted each tick by `PredictionController` online. **Offline** (Practice/Sandbox) the same
  `Player.movement_sm` is the sole mover (`Player._handle_movement` when `prediction_owns_movement =
  false`), so dash/sprint/stamina work there from the one shared player script. Renders the replicated
  entity flags for remotes.
- **Server:** owns the authoritative SM on `PlayerState.movement_sm`, driven in `step()`; validates
  dash cooldown, sprint stamina-gating, mana cost; applies knockback from hits; sets entity flags.
- **Predicted:** dash, sprint speed, knockback, stun, and both resources — predicted locally for feel.
- **Replicated:** DASHING/KNOCKED_BACK/STUNNED/DAZED entity flags to everyone; stamina/mana to the
  owner via `ACTION_CONFIRM`.
- **Persisted:** none — all in-memory; only account/character/stats persist (Go API).
- **Validated:** cooldown, stamina/mana, and the `_can_transition` guard table are enforced on the
  authoritative server; a rejected dash is pulled back by position reconciliation.
- **Can fail:** under packet stall a transient state spanning a correction can hitch (replay uses
  ground speed); stamina drain lags entry into SPRINTING by one tick (≈33 ms, harmless & deterministic);
  Root collapses onto Stun until a real `StatusEffectManager` exists; a dropped DAZED flag delta is
  repaired by the next baseline and bounded by the local daze timer self-expiring.
- **Tested:** SM behavior covered by a headless assertion harness (idle→walk, sprint+stamina, dash
  3×/0.4 s/cooldown, knockback decay, stun block+release, no-dash-while-stunned, mana spend, ability
  override); server boots and ticks clean; full networked play-test of feel/HUD is the open manual step.

## See also

- [`players-movement.md`](players-movement.md) — base movement, prediction, the animation-only `Player.MovementState`
- [`state-machines.md`](state-machines.md) — all six state machines in one place (§6)
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — `input_flags` u16 + dash bit, entity flags, `ACTION_CONFIRM` resources
- [`../netcode/client-prediction.md`](../netcode/client-prediction.md) — the prediction/reconciliation loop the SM plugs into
