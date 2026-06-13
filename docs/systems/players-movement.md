# Players & movement

**Status:** Partial (verified 2026-06-03 against code). Movement, prediction, interpolation,
and validation are all implemented — but the **Local player is moved by two integrators at once**
(double-ownership). This doc is the canonical home for that bug; the fix is small but not yet applied.

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md): **Local player** is predicted and owned
> between corrections; every other character is a **Remote entity**, drawn by **Interpolation**,
> never predicted. **Tick** (server sim step, 30 Hz) ≠ **Frame** (client draw) ≠ **Snapshot**
> (`STATE_UPDATE` broadcast).

## What a player is

One `CharacterBody2D`, `MOTION_MODE_FLOATING` (top-down, no gravity), on collision **layer 1 /
mask 6** (`player.tscn:58-59`; mask 6 = Walls + Monsters). The Local player now carries a
**7-state movement state machine** (`MovementStateMachine`) with two resources — **stamina** (gates
sprint) and **mana** (gates the ability) — alongside HP; dash and knockback are first-class states.
See [`players-movement-state-machine.md`](players-movement-state-machine.md). There are two visual classes:

| Class | Script | Moved by | Collision | Input |
|---|---|---|---|---|
| Local player | `Player` (`player.gd:3`) | `PredictionController` (intended) | layer 1 / mask 6 (`player.tscn:58-59`) | yes — predicted |
| Remote entity (player) | `RemotePlayer` (`remote_player.gd:4`) | `InterpolationController` (`remote_player.gd:2`) | layer 1 / mask 4 (`remote_player.tscn:55-56`) | none |

`RemotePlayer` runs **no** `_physics_process` and processes no input; its position is written by
interpolation and its animation/flags come straight from Snapshot data via
`update_from_network()` (`remote_player.gd:54`).

## Movement model

| Quantity | Value | Source |
|---|---|---|
| Base speed | `PLAYER_SPEED` 200 u/s | `game_constants.gd:32` |
| Sprint multiplier | `PLAYER_SPRINT_MULTIPLIER` 1.6 | `game_constants.gd:35` |
| Sprint speed | `PLAYER_SPRINT_SPEED` 320 u/s | `game_constants.gd:38` |
| Direction | normalized WASD vector | `prediction.gd:283-295` |
| Hitbox radius | `PLAYER_HITBOX_RADIUS` 16 | `game_constants.gd:229` |

Direction comes from the four WASD flags summed into a vector, then `.normalized()`
(`prediction.gd:295`). That is **free analog direction** built from 8 discrete key combinations
(4 cardinals + 4 diagonals) — diagonals are not faster, and there is no facing quantization.
Aim is independent of movement (mouse angle, `prediction.gd:203-208`).

Collision against the **map bounds and arena obstacles** is analytic, not physics-engine:
`GameConstants.move_with_obstacle_collision()` (`game_constants.gd:398`) clamps to bounds and
slides axis-separated. The same function is used by the server, by prediction, and by reconciliation
replay — so all three integrate identically.

### Two movement state machines — animation vs. motion

There are now **two** distinct movement state machines, and they must not be confused:

- `Player.MovementState` — a two-state **animation-only** machine (`IDLE` / `WALKING`,
  `player.gd:7-10`) plus an orthogonal `ActionState` (NONE / ATTACKING / HIT / DEAD,
  `player.gd:13-18`) that drives sprite-animation priority. It is **not** the netcode movement source.
- `MovementStateMachine` — the **authoritative motion** machine (IDLE / WALKING / SPRINTING /
  DASHING / KNOCKED_BACK / STUNNED / ABILITY_MOVEMENT, `movement_state_machine.gd`). The server owns
  one per `PlayerState` and the client predicts an identical instance; it produces the velocity that
  `PredictionController._apply_local_prediction` and `PlayerState.step` integrate. This is the
  authoritative motion source for the Local player — see
  [`players-movement-state-machine.md`](players-movement-state-machine.md).

For a Remote entity the animation state (and the new DASHING / KNOCKED_BACK / STUNNED entity flags)
arrive over the wire and are applied in `remote_player._update_animation()` (`remote_player.gd:63`).

### Directional sprites — facing follows movement, not aim

With class spritesheets active, the 8-way facing **row** is derived from the **movement
direction** (the position delta), kept when stationary — `player.gd` mirrors `remote_player.gd`
so local and remote players animate consistently. Earlier the local player picked its row from
the **aim/cursor** angle, so the run cycle faced the mouse while strafing; the body still rotates
to the aim (that drives shooting), but the artwork is counter-rotated and the row tracks motion.
The locomotion tier (idle/run/sprint/dash) comes from the observed speed against thresholds
between the tier speeds (200 / 320 / 720 u/s) — sprint shows the sprint cycle, run shows run.

### Class sprite tint

The main-menu colour swatch tints the chosen **class** spritesheet via `modulate`, blended
toward the colour at `GameConstants.CLASS_SPRITE_TINT_STRENGTH` (white = untinted). It lets a
player slightly recolour their character while keeping class identity; the legacy procedural
fallback instead bakes the colour into regenerated frames. Applied identically in `player.gd`
and `remote_player.gd` (`_class_tint`).

## HP (the only stat)

`HPComponent` (`hp_component.gd:3`), a child node: `max_hp` default 100 (`hp_component.gd:13`),
`current_hp`, `is_dead`. `take_damage()` clamps to 0 and emits `died` at zero (`hp_component.gd:28-37`);
`set_hp()` is the server-reconciliation path and auto-clamps invalid values (`hp_component.gd:60-74`).
`Player._on_hp_component_died()` forces `ActionState.DEAD` and disables input (`player.gd:243-247`).
HP is server-authoritative; the client never decides its own death.

## Local player: predicted

The Local player is simulated immediately on input, before the server confirms — see
[`../netcode/client-prediction.md`](../netcode/client-prediction.md) for the full loop. In brief:

- Input is sampled **and** sent at 30 Hz inside `_physics_process` (`prediction.gd:142`,
  `:157`, `:169-172`; `INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`, `prediction.gd:71`).
- 8-bit wrapping sequence numbers; replay buffer up to 256 inputs (`prediction.gd:21`, `:57`, `:356-359`).
- Reconciliation snaps `predicted_position` to the server position when drift exceeds the
  epsilon `server_position_epsilon = 4` u, then replays unacked inputs (`prediction.gd:30`,
  `:458`, `:503`, `:511-559`).
- Visual correction: smooth lerp at `interpolation_speed = 12.0` (`prediction.gd:20`, `:632`),
  unless the correction exceeds `teleport_threshold = 150` u, which snaps instantly
  (`prediction.gd:28`, `:543`).

## Remote players: interpolated

Drawn ~66.7 ms (2 Ticks) in the past from buffered Snapshots — see
[`../netcode/interpolation.md`](../netcode/interpolation.md). `RemotePlayer` is a passive visual:
position written by `InterpolationController`, animation/flags from network state
(`remote_player.gd:2`, `:54-102`). Invulnerability flashes the sprite (`remote_player.gd:99-101`).

## Server validation (movement)

The server checks each input's resulting position against what its own simulation expects and
classifies the deviation by these thresholds:

| Threshold | Value | Meaning | Source |
|---|---|---|---|
| `POSITION_TOLERANCE` | 75 u | soft — within this, accept silently | `game_constants.gd:47` |
| `CORRECTION_THRESHOLD` | 112.5 u | above this, send a correction (1.5× tolerance) | `game_constants.gd:51` |
| `TELEPORT_THRESHOLD` | 150 u | above this, treat as impossible / cheat | `game_constants.gd:55` |

These are sized against max sprint speed (320 u/s): `POSITION_TOLERANCE` tolerates ~230 ms of
latency at sprint (`game_constants.gd:46`). The client's own `teleport_threshold` (150 u,
`prediction.gd:28`) is the *visual* snap cutoff and happens to match `TELEPORT_THRESHOLD`; they are
separate constants for separate jobs (server cheat flag vs. client correction style).

## The double-movement bug ("steering boat") — Partial / not fixed

**Symptom:** the Local player drifts/overshoots as if two hands are on the wheel — it accelerates
past where input should stop, then gets tugged back.

**Root cause: two integrators own the same node.** After [Authority sync](../CONTEXT.md), the arena
re-enables `Player.gd`'s own input on the networked Local player:

- `arena_base.gd:374` — on `PLAYER_INFO` authority sync
- `arena_base.gd:418` — on the `STATE_UPDATE` fallback authority sync
- `arena_base.gd:493` — on respawn

Each calls `local_player.set_input_enabled(true)`. With input enabled, `Player._physics_process`
runs `_handle_movement()` + `move_and_slide()` (`player.gd:91-109`, `:119-127`) — i.e. the
**CharacterBody2D physics integrator**, reading WASD itself at speed 200 with **no sprint** support
(`player.gd:24`). At the same time, `PredictionController._physics_process` reads the *same* WASD,
runs the **analytic** integrator (`move_with_obstacle_collision`, speed 200 / sprint 320), and
writes `player_node.position` directly (`prediction.gd:142`, `:262-280`, `:607`).

Two integrators, same `_physics_process` Tick, writing the same node:

1. `move_and_slide()` advances the body from `velocity` (Player.gd).
2. `PredictionController` then overwrites `position` with `predicted_position`.

They use different speeds (Player.gd ignores sprint) and different collision models
(`move_and_slide` mask-6 physics vs. analytic obstacle slide), so they disagree and leapfrog —
the visible "steering boat" wobble. The shooting half of `Player.gd` is already neutralised
(`set_local_projectile_spawning_enabled(false)` at `arena_base.gd:220`, and
`_handle_shooting` early-returns at `player.gd:146`), but **movement was not**.

**Fix:** make `PredictionController` the sole owner of the Local player's motion. Do **not**
re-enable `Player.gd` movement for the networked Local player — drop the
`set_input_enabled(true)` calls at `arena_base.gd:374/418/493` (or split input so only
animation/aim, not `_handle_movement`/`move_and_slide`, is driven by `Player.gd`). The Local
player should be moved by `predicted_position` only. This is invariant violation #1 in
[`../../AGENTS.md`](../../AGENTS.md).

> Distinct from the "looks like 30 fps" stutter
> ([`../netcode/smoothness-render.md`](../netcode/smoothness-render.md)): that is a render-pacing
> problem affecting *all* motion; this is two simulators fighting over the *Local player* only.
> Both can be present at once.

## The eight questions

- **Client:** samples input, predicts the Local player, interpolates Remote players, renders HP/animation.
- **Server:** authoritative — integrates every player, validates moves, owns HP and death.
- **Predicted:** the Local player's position/velocity (`prediction.gd`); nothing else.
- **Replicated:** every player's position, animation state, flags, HP via `STATE_UPDATE` Snapshots.
- **Persisted:** nothing in-match — player state is in-memory; only account/character data lives in the Go API.
- **Validated:** server distance check vs. `POSITION_TOLERANCE` / `CORRECTION_THRESHOLD` / `TELEPORT_THRESHOLD`.
- **Can fail:** double-movement (two integrators after `set_input_enabled(true)`) — the open bug above.
- **Tested:** offline arena sandbox (`scenes/test/sandbox.tscn`) and E2E auto-join; no automated movement regression test today.

## See also

- [`../netcode/client-prediction.md`](../netcode/client-prediction.md) — the Local player prediction/reconciliation loop
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how Remote players are drawn
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — the separate 30 Hz render-pacing stutter
- [`../CONTEXT.md`](../CONTEXT.md) · [`../../AGENTS.md`](../../AGENTS.md) — glossary and invariant list
