# Offline modes (Practice & Sandbox)

**Status:** Implemented (added 2026-06-10). Two fully **client-authoritative** scenes for
playtesting gameplay without a server: **Practice** (target dummies) and **Offline Sandbox** (debug
playground + a real client-AI enemy). Reached from the main menu's bottom-left buttons.

> Vocabulary follows [`../CONTEXT.md`](../CONTEXT.md). These modes deliberately break the normal
> authority model: there is **no Server, no `NetworkManager`, no `PredictionController`, no
> Interpolation**. The Local player owns its own position and the whole simulation runs on the
> client. They exist to test feel/UI/AI in isolation from the netcode — see
> [`../netcode/overview.md`](../netcode/overview.md) for the real online model.

## Why these exist / why they were buggy

Online, the server simulates everything and the client's `PredictionController` is what actually
*moves* the Local player, applies sprint speed, and plays the shoot sound; `Player.gd` is only
"half a system" (it animates + reads input, and `prediction_owns_movement = true` makes it skip its
own `move_and_slide`). The first offline implementation dropped a raw `Player.gd` into two separate
hand-rolled scenes with no prediction layer, so sprint, shoot audio, and damage-recovery silently
went missing and the scenes diverged. The fix made `Player.gd` self-sufficient when it owns its own
movement and collapsed both scenes onto a shared base.

## The shared spine: `OfflineArena`

`OfflineArena` (`client/scripts/levels/offline_arena.gd`) is the base both modes extend. It
owns everything the online `arena_base.gd` gets from the prediction/network layer:

| Concern | How |
|---|---|
| Boundary walls | `StaticBody2D` on environment layer 8, built from `arena_rect`. |
| Local player | `player.tscn` at the room center; `prediction_owns_movement = false`, input + local projectile spawning **on**, `collision_mask \|= 8`. |
| Camera | `Camera2D.make_current()`, follows the player on the physics tick; default + sprint zoom come from `GameConstants.CAMERA_ZOOM_*` (shared with the arena — one source of truth); snaps + `reset_physics_interpolation()` on teleports. |
| HUD | HP / Stamina / Mana bar group (shared `BottomBars` layout, identical to the networked arena) + pause menu (its **Leave Arena** → `_leave()` → main menu). Stamina/mana are polled from the player's `movement_sm` each frame (no server here). |
| Shoot feedback | connects `Player.shot_fired` → `AudioManager.play_player_shoot()` + muzzle flash. |
| Damage routing | one connection to the player's projectile pool; on hit, `body.take_damage()` if `body` is in group `enemies`. |
| Leaving | `exit_to_menu` (T) **or** Esc→pause→Leave both call `_leave()`. |

Subclasses override `_configure()` (room rect, colors, zoom, spawn) and `_populate()` (enemies +
extra UI); they should not override `_ready()`.

## What runs where

| | Practice (`practice_level.gd`) | Sandbox (`sandbox.gd`) |
|---|---|---|
| Room | warm room, kept size (`ROOM_RECT` 2880×2080) | standard arena bounds (`MAP_MIN..MAP_MAX`) |
| Enemies | 4 `TargetDummy` (N/E/S/W), stationary, **respawn** | "Spawn Toxic Slime" button → `OfflineMonster`, **no respawn** |
| Extras | "Dummies defeated" counter | debug keys 1–7, death overlay, kill-feed/minimap/leaderboard |

- **Local player** (Practice & Sandbox): `Player` moving itself via `move_and_slide`, but the velocity
  now comes from the **same `MovementStateMachine`** the networked player predicts — so dash, sprint,
  knockback, stun, and stamina/mana all work offline from the one shared player script
  (`Player._handle_movement` drives `movement_sm` when `prediction_owns_movement = false`). See
  [`players-movement-state-machine.md`](players-movement-state-machine.md). Shooting uses the local
  `ProjectilePool` (mask 10 = Monsters + Environment).
- **Target dummy** (`target_dummy.gd`, def `target_dummy.json`): stationary, `xp: 0`,
  `ai_profile: "stationary_dummy"`, respawns on a timer. In group `enemies`.
- **OfflineMonster** (`offline_monster.gd`, scene `offline_monster.tscn`): a self-contained
  **client-side** AI enemy, data-driven from the same `MonsterDefinition` JSON the server reads. It
  mirrors the *intent* of `monster_ai.gd` (idle / chase / attack-kite / flee) in a compact form;
  it does **not** reproduce the server's steering/threat math. Its own `ProjectilePool` uses mask 9
  (Players + Environment) so its bullets hit the player and walls but never other monsters. Frees
  itself on death (no respawn). In group `enemies`.

## Predicted / Replicated / Persisted / Validated

- **Predicted:** nothing — there is no prediction or reconciliation. The client *is* the authority.
- **Replicated:** nothing — no `STATE_UPDATE`, no sockets. All entities are local nodes.
- **Persisted:** nothing — no Go API calls. The selected `player_color`/`character_name` are read
  from `GameManager.player_data` only for cosmetics.
- **Validated:** nothing server-side. Sandbox invulnerability is a client flag
  (`Player.invulnerable`) honored in `Player.take_damage()`.

## Damage flow (offline)

- Player bullet (mask 10) → hits a `TargetDummy`/`OfflineMonster` (layer 2) → `OfflineArena`
  routes `take_damage(projectile.damage)`.
- `OfflineMonster` bullet (mask 9) → hits `Player` (layer 1) → `Player.take_damage(projectile_damage)`
  (ignored while `invulnerable`). Walls (layer 8) stop both kinds of bullet.
- The `HIT` action state is **cosmetic only** and does not block movement (a bullet-hell must stay
  responsive; online this was masked because prediction owned movement).

## What can fail

- A pooled projectile teleporting to its new spawn renders a one-frame streak under global physics
  interpolation — fixed by `reset_physics_interpolation()` in `Projectile.activate()`.
- `OfflineMonster` AI is intentionally simpler than the server AI; behavior parity with online is
  approximate, not exact.
- If `AudioManager` is absent (it is an autoload, so normally present) shoot/music calls no-op.

## How it is tested

Manual, in-engine (no automated coverage yet): run the client, enter each mode, and verify movement,
sprint, shoot sound, single clean projectiles, dummy kill/respawn, slime chase/kite/shoot + no
respawn, the Sandbox 1–7 debug keys, and Esc/T → main menu. See the verification section of the
exec note for the offline-modes refactor.
