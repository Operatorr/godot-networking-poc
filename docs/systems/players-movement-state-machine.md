# Player movement state machine (dash · sprint · charge · knockback · stun · daze · stamina · mana)

**Status:** Implemented (Rust port). Canonical SM is `rust/sim_core/src/movement.rs` (`MovementSm`),
covered by the in-module unit tests there (`cargo test -p sim_core`). HUD/feel by live play-test is
the open manual step.

An **8-state, server-authoritative** movement model for the Local player, predicted on the client for
zero-latency feel. It replaces the old stateless `direction × speed` movement (sprint was a bare
multiplier) with a real state machine plus two resources (stamina, mana) and per-class tuning.

The **canonical definition lives in Rust**: `MovementSm` in `rust/sim_core/src/movement.rs`. It is
run **identically** by

- the authoritative server — `PlayerState::step` (`rust/server/src/player.rs`) calls
  `sim_core::step_movement` (`rust/sim_core/src/step.rs`), which calls `MovementSm::tick`; and
- the **client prediction** — the local player's predictor drives the **same compiled crate** through
  the `PredictionSim` GDExtension (`rust/client_ext/src/lib.rs`, owned by
  `client/scripts/client/prediction.gd`). Prediction cannot diverge from the server because it is the
  *same code*; the position-reconciliation path (snapshot vs. predicted) corrects any residual.

The GDScript `MovementStateMachine`
(`client/scripts/shared/player/movement_state_machine.gd`) is a **line-by-line mirror** of the Rust
SM, but it is **not** the online predictor. It is used in two narrower roles:

1. **Offline mover** (Practice / Sandbox / Sanctuary, `Player.prediction_owns_movement = false`):
   `Player._handle_movement` calls `movement_sm.tick()` as the sole authority (`player.gd`).
2. **HUD / status mirror** online: the predictor pushes corrected `stamina`/`mana`
   (`set_resources`), exhaustion (`set_exhausted_state`), and the DAZED edge into it so the existing
   signal-driven HUD (`stamina_changed`, `exhausted_changed`, `daze_started/ended`) keeps working.
   The signals exist only in the GDScript mirror — the Rust SM emits none (callers diff `state()`).

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md). **Tick** = the 30 Hz server sim step; the
> client predictor advances the SM at the same rate. Transport is **ENet/UDP** (3 channels —
> ch0 unreliable-sequenced snapshots/confirms, ch1 reliable-ordered auth/events/baselines, ch2
> unreliable-sequenced input), so input packets **can** be dropped/reordered — sequence numbers and
> reconciliation absorb that. See [`../server/contract.md`](../server/contract.md).

## States

```rust
enum MoveState { Idle, Walking, Sprinting, Dashing, KnockedBack, Stunned, AbilityMovement, Charging }
```

(`repr(u8)` 0..7; the GDScript mirror's `enum State` matches indices 0..6 and adds Charge handling.)

| State | Velocity each tick | Enters when | Leaves to |
|---|---|---|---|
| Idle | zero | no move input | Walking/Sprinting on input |
| Walking | `dir × base_speed × speed_mult` | move input, not sprinting | Idle / Sprinting / Dashing / … |
| Sprinting | `dir × base_speed × 1.6 × speed_mult` | move + sprint held + stamina > 0 + not exhausted + not dazed | Walking when released/exhausted/attacked/damaged |
| Dashing | constant dash velocity | dash edge (cooldown ready, not dazed/stunned/KB/ability/charge) | Idle after `DASH_DURATION` |
| KnockedBack | decaying impulse (`exp`) | `apply_knockback()` (server only) | Idle below `END_SPEED`; or Stunned/AbilityMovement |
| Stunned | zero (input blocked) | `apply_stun()` / `apply_root()` | Idle when the stun timer ends |
| AbilityMovement | externally-set velocity | `start_ability_movement()` | Idle on `end_ability_movement()` |
| Charging | constant charge velocity, **INVULNERABLE** | RMB edge when the class ability is a Charge (`charge_speed > 0`) | Idle on RMB release, max-distance, stun, or server `end_charge()` |

**Charging** is the Warrior Charge (`rust/sim_core/src/movement.rs` `start_charge` / `tick_charging`):
a *held-input* directional dash (along move-dir, or aim-dir when standing still), invulnerable, up to
`charge_max_distance`. It is purely directional (no target lookup) so the client predicts it; on the
**natural** end (RMB release or max-distance) the SM sets `charge_just_ended`, and the server spawns
the AOE blast (`rust/server/src/world.rs` `process_charge_blasts`). Server-side enemy contact ends it
via `end_charge()` (server pairs its own blast); stun/teleport clear the charge **without** a blast.

**Daze is a timer, not a state.** `apply_daze(duration)` locks out sprint and dash and ends any
in-progress sprint; walking, knockback, and ability/charge velocities proceed normally. It coexists
with KnockedBack — the usual companion on a hit. Re-application **extends, never shortens**
(`daze_time_left.max(duration)`). Applied server-side when a player is **hit while Sprinting**
(`rust/server/src/combat.rs` `apply_player_hit` — `was_sprinting` → `apply_daze(PLAYER_DAZE_DURATION)`);
replicated via the `DAZED` entity flag (bit 8; entity flags are u16 since protocol v2). The client
slaves its predicted daze to that flag — apply on the rising edge, `clear_daze()` on the falling edge
(`prediction.gd` `_update_own_flags`) — and shows the `DazeIndicator` circling-stars visual above the
player's head (local + remote). Offline, `Player._on_hp_changed` applies the same rule locally. Bots
mirror the flag (`rust/load_test/src/bot.rs`).

## Numbers

Canonical in `rust/sim_core/src/constants.rs`; the GDScript mirror is `game_constants.gd`. Both must
agree by construction (they are read-checked against each other).

| Quantity | Constant | Value |
|---|---|---|
| Base ground speed (default; per-class overrides via `set_base_speed`) | `PLAYER_SPEED` | 200 u/s |
| Sprint speed | `PLAYER_SPEED × PLAYER_SPRINT_MULTIPLIER` | 200 × 1.6 = 320 u/s |
| Dash speed | `PLAYER_SPEED × PLAYER_DASH_MULTIPLIER` | 200 × 3.6 = 720 u/s |
| Dash duration | `PLAYER_DASH_DURATION` | 0.4 s (13 ticks — f64 residue, see test) |
| Dash cooldown (START-relative) | `PLAYER_DASH_COOLDOWN` | 5.5 s |
| Knockback decay / end / base force | `PLAYER_KNOCKBACK_DECAY` / `_END_SPEED` / `_BASE_FORCE` | 9.0 / 12 u/s / 450 |
| Per-projectile knockback force | `PLAYER/MONSTER_PROJECTILE_KNOCKBACK_FORCE` | 450 (per-projectile so weapons can vary) |
| Daze duration (hit while sprinting) | `PLAYER_DAZE_DURATION` | 1.5 s |
| Stamina max / drain / regen | `PLAYER_STAMINA_*` | 100 / 35 ps / 20 ps |
| Sprint-exhaustion lockout | `PLAYER_STAMINA_EXHAUST_DURATION` | 3.0 s (no sprint, no regen) |
| Mana max / regen / default ability cost | `PLAYER_MANA_*` | 100 / 8 ps / 25 |
| Speed-mult clamp (Haste/Slow) | `PLAYER_SPEED_MULT_MIN/MAX` | 0.25 … 2.5 |

**Stamina model (changed):** sprint drains to **0**, not to a 5-stamina floor; reaching 0 triggers a
3 s **exhaustion lockout** during which sprint is refused and regen is paused (`update_stamina`,
`is_exhausted`). The HUD blinks the stamina bar on the lockout edge.

**Per-class tuning** is set once when class+level is known (server on join/level-up; client on class
load and each PROGRESS event), via `set_base_speed` and `set_ability_config(cost, cooldown,
charge_speed, charge_max_distance)`. Identical values both sides keep prediction in lockstep, and
they survive `reset()` (they belong to the character, not the life). Per-class stats live in
`rust/server/src/ability.rs` (`effective_base_speed`, `stats_for_class`); only Warrior (Charge,
`charge_speed = 720`), Rogue, and Mage are in pre-alpha scope.

**Triggers.** Dash is **edge-triggered** on `dash` (Spacebar): the client latches the press and sets
`INPUT_FLAG_DASH` (bit 8, `input_flags` is u16) in exactly one input; the server detects the rising
edge (latched in `PlayerState.pending_dash` against same-tick overwrite, OR-ed into `dash_held` in
`player.rs` step). Dash direction is the move direction, or the **aim direction** when standing still.
Sprint activates while `INPUT_FLAG_SPRINT` (bit 6) is held and drains stamina; it ends on attack
(`INPUT_FLAG_SHOOT` held) or on taking damage. The RMB ability (`INPUT_FLAG_ABILITY`, bit 5,
edge-detected) gates on cooldown + mana (`try_activate_ability`): a Charge class starts Charging, any
other class marks `ability_fired` (an *instant* cast) for the server to dispatch.

## Status effects

`apply_speed_modifier()` / `clear_speed_modifier()` (Haste/Slow, clamped) and `apply_root()` (→ stun
today) remain placeholders for a future manager (search `TODO(StatusEffectManager)` in the GDScript
mirror). **Daze is real** (see above): a sprint/dash lockout timer with `is_dazed()` /
`daze_remaining()`, the `DAZED` wire bit, and `clear_daze()`. Stun cancels an in-progress dash **or**
charge; daze refuses new dashes without touching the cooldown. Knockback is applied server-side from
projectile impacts (`combat::apply_player_hit`) **along the projectile's travel direction**
(predictable "shot from the left ⇒ thrown right"; fallback away-from-impact only when direction is
unknown — the discrete-tick overlap test can place the impact point past the target's center). The
impulse is the projectile's per-spawn `knockback_force`; the `apply_knockback(dir, force, multiplier)`
multiplier is the buff/debuff hook on top. **All `*_finite` guards** in the Rust SM reject NaN/Inf
inputs (force, durations, resource sets, ability config) so a corrupt value cannot poison the sim.

## Replication & the reconciliation caveat

Movement state is replicated to remote viewers via entity flags — `DASHING` (bit 6; **also set while
Charging**), `KNOCKED_BACK` (bit 7), `STUNNED` (bit 4), `DAZED` (bit 8), and `STEALTH` (bit 9,
protocol v4, Rogue) — set in `PlayerState::update_entity_flags` (`rust/server/src/player.rs`).
Charging also forces `INVULNERABLE` (bit 3). Stamina/mana are an **owner-only** sync riding the
~30 Hz `ActionConfirm` (type 66, ch0; two trailing `u8` resource bytes quantized `clamp(round(v),
0, 255)`), applied via `MovementSm::set_resources` (epsilon-gated). See
[`../server/contract.md`](../server/contract.md).

Reconciliation replay (`sim_core::replay_ground_step`) recomputes position from the SM's **ground**
speed (walk/sprint, gated by the SM's *current* stamina/exhaustion/daze, Haste/Slow-scaled —
`ground_speed`). It intentionally does **not** re-simulate dash/knockback/stun/charge velocity during
replay: those transient states are brief and start on the same input on both sides; any residual is
fixed by the next snapshot. Because input is over **unreliable** ch2, a dropped input is recovered by
the next packet's flags plus reconciliation rather than retransmission.

## The eight questions

- **Client:** the **local player** predicts the full SM (state, dash/charge/knockback/stun,
  stamina/mana) through the Rust `PredictionSim` GDExtension, driven by `prediction.gd`. **Offline**
  (Practice/Sandbox) the GDScript `Player.movement_sm` is the sole mover (`Player._handle_movement`).
  Remotes render the replicated entity flags only.
- **Server:** owns the authoritative `MovementSm` on `PlayerState.movement_sm`, ticked in `step()`
  via `step_movement`; validates dash cooldown, sprint stamina-gating, mana cost; applies knockback
  and daze from hits; dispatches instant abilities (`world.rs::process_instant_abilities`) and charge
  blasts (`process_charge_blasts`); sets entity flags.
- **Predicted:** dash, charge, sprint speed, stun, both resources — and (for the local player only)
  daze slaved to the wire flag. Knockback is **server-only** — the client never predicts it (the
  `tick_knockback` `exp()` branch is dead on the client; KB position comes from snapshots).
- **Replicated:** DASHING/KNOCKED_BACK/STUNNED/DAZED/STEALTH entity flags + INVULNERABLE during
  charge, to everyone; stamina/mana to the owner via `ActionConfirm`.
- **Persisted:** none — all in-memory. Only account/character/progression persist (Go API,
  Postgres+Redis). Per-class SM tuning is re-derived from the character on join, not stored in the SM.
- **Validated:** cooldown, stamina/mana, exhaustion, and the `can_transition` guard table are enforced
  on the authoritative server; a rejected dash/charge is pulled back by position reconciliation.
- **Can fail:** a dropped/late input is absorbed by the next packet + reconciliation; a transient
  state spanning a correction can hitch (replay uses ground speed); stamina drain lags entry into
  Sprinting by one tick (≈33 ms, deterministic); Root collapses onto Stun until a real
  `StatusEffectManager` exists; a dropped DAZED-flag delta is repaired by the next baseline and bounded
  by the local daze timer self-expiring.
- **Tested:** `rust/sim_core/src/movement.rs` `#[cfg(test)]` covers idle→walk, per-class speed,
  sprint-deplete→exhaust→recover, dash (13 ticks / start-relative cooldown / stationary-aim /
  refusal-skips-cooldown), knockback decay + pinned `exp` bits, stun guard table + dash-cancel,
  daze (blocks sprint/dash not walking, extend-never-shorten, coexists-with-KB), instant-ability
  fire + cooldown, charge (start/move/release, max-distance, server end-on-contact), non-finite-input
  no-ops, and bitwise determinism. `sim_core::step` tests cover the integrate+mover path.

## See also

- [`players-movement.md`](players-movement.md) — base movement, prediction, the animation-only `Player.MovementState`
- [`abilities.md`](abilities.md) — class abilities (Warrior Charge, Rogue Shadowstep, Mage blast) and the cursor/RMB input
- [`state-machines.md`](state-machines.md) — all state machines in one place
- [`../server/contract.md`](../server/contract.md) — `input_flags` u16 (dash/ability bits), u16 entity flags, `ActionConfirm` resources, wire format as built
- [`../netcode/client-prediction.md`](../netcode/client-prediction.md) — the prediction/reconciliation loop the SM plugs into
