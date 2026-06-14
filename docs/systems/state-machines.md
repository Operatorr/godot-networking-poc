# State machines (player life, movement, monster AI, scene, connection)

**Status:** Implemented (verified 2026-06-14 against the Rust port).

The POC runs six distinct finite state machines, split across the **Rust omega-server** and the
**Godot client**. None share a base class — each is a hand-rolled `enum` plus a `match` (or `if`)
transition block. This doc enumerates the states, the transitions, where each lives, and which side
owns it, so you can reason about every authoritative or UI state change in one place.

> **Post-Rust-port reality.** The only authoritative server is the Rust `omega-server` binary
> (`rust/server/`), a single-threaded synchronous 30 Hz tick over `rusty_enet` (`=0.4.0`); one
> process = one instance. The two server-side gameplay machines (player movement, monster AI) now
> live in `rust/sim_core/` and `rust/server/`; the client-side machines (scene flow, connection
> lifecycle) live in GDScript. The GDScript headless server is **retired** (`NetworkManager`
> refuses server mode) and is being deleted — do **not** cite `client/scripts/server/*.gd` as live
> code. Wire/transport facts below are the [server contract](../server/contract.md).

| Machine | Enum / values | Owner | Where |
|---|---|---|---|
| Player life | `LifeState` Alive / Dead / Invulnerable | **Server (Rust)** | `rust/server/src/player.rs` |
| Player animation (movement-derived) | `anim` IDLE / WALK / RUN / ATTACK / HIT / DEATH / SPAWN | Server (derived), replicated | `rust/protocol/src/types.rs` (`mod anim`), derived in `rust/server/src/player.rs` |
| Player movement | `MoveState` Idle / Walking / Sprinting / Dashing / KnockedBack / Stunned / AbilityMovement / Charging | **Shared sim** (`rust/sim_core`): server-authoritative + client-predicted | `rust/sim_core/src/movement.rs` |
| Monster AI | `AiState` Idle / Chase / Attack / Flee | **Server (Rust)** | `rust/server/src/monster.rs` |
| Game / scene state | `GameState` INITIALIZING / MAIN_MENU / LOADING / IN_ARENA / PAUSED / EXITING | Client | `client/autoload/game_manager.gd`, `client/autoload/scene_manager.gd` |
| Connection lifecycle | `ConnectionState` DISCONNECTED / CONNECTING / CONNECTED / RECONNECTING / ERROR | Client | `client/autoload/network_manager.gd` |

The first four are server-side (Rust); the last two are client-side (GDScript). Player movement is
the one machine that runs on **both** sides: the server owns the authoritative `MovementSm`, and the
client runs the *same compiled crate* through the `client_ext` GDExtension (`PredictionSim`), so
prediction cannot diverge by construction.

---

## 1. Player life — `LifeState` (server-authoritative)

`enum LifeState { Alive, Dead, Invulnerable }` on the Rust `PlayerState`
(`rust/server/src/player.rs`). One per connected player, owned by the server. The client never
sets it; it only *reflects* it via the `INVULNERABLE` / `ALIVE` bits in each entity's 16-bit
`entity_flags` field in the Snapshot (`rust/protocol/src/types.rs`, `mod entity_flags`).

| From | To | Trigger | Evidence |
|---|---|---|---|
| Alive | Dead | `take_damage` drops health ≤ 0 → `mark_dead` | `player.rs` `take_damage`, `mark_dead` |
| Invulnerable | (stays) | invuln absorbs damage silently; `take_damage` returns false | `player.rs` `take_damage` |
| Dead | Invulnerable | client `RespawnRequest` after the timer gate → `reset_for_respawn` | `world.rs` `handle_respawn_request`; `player.rs` `reset_for_respawn` |
| Invulnerable | Alive | active move/SHOOT input, OR the `INVULNERABILITY_DURATION` (3.0 s) timer | `player.rs` `step` (`has_active_input`), `update_invulnerability`, `end_invulnerability` |

Details:
- **Death** (`mark_dead`) zeros velocity/input, resets the movement SM, clears the input + pending-shot
  queues, sets `respawn_timer = RESPAWN_DELAY` (3.0 s, `rust/sim_core/src/constants.rs`), bumps
  `deaths`, records `last_killer_id`, and sets `anim::DEATH`. It is idempotent (guards on
  already-`Dead`). Dead players are **not despawned** — they keep replicating with flags == VISIBLE
  and animation DEATH.
- **Respawn is client-requested, not automatic.** The server counts `respawn_timer` down each tick
  (`world.rs` step → `update_respawn_timer`); the client sends a `RespawnRequest` (C→S type 5, ch1
  reliable). `handle_respawn_request` silently rejects while `is_alive || respawn_timer > 0.0` (the
  client retries), then `reset_for_respawn` enters `Invulnerable` with `invulnerability_timer =
  INVULNERABILITY_DURATION` (3.0 s), `anim::SPAWN`, and broadcasts a `RESPAWN` GameEvent carrying the
  spawn position.
- **Invulnerability ends two ways**: (a) the player acts — `step()` calls `end_invulnerability()`
  when `has_active_input()` sees any move or SHOOT flag (sprint/dash/ability/interact alone do **not**
  break it); or (b) the 3 s timer expires via `update_invulnerability`. Either path routes through
  `end_invulnerability()`, which returns to `Alive` and clears the `INVULNERABLE` flag.
  - **Caveat (Warrior charge):** charge-invulnerability is orthogonal — `update_entity_flags` sets
    `INVULNERABLE` while `movement_sm.is_charging()` even when the life state is `Alive`, and
    `take_damage` absorbs damage during a charge. This is movement-SM state, not a `LifeState`
    transition.
- **Dead players are inert**: `step()` early-returns while `Dead` (no input ingestion, zeroed
  velocity); damage/input are dropped.

---

## 2. Player animation (movement-derived) — `anim`

`mod anim { IDLE=0, WALK=1, RUN=2, ATTACK=3, HIT=4, DEATH=5, SPAWN=6 }`
(`rust/protocol/src/types.rs`; 3 bits on the wire inside each Snapshot record). This is not a
separate controller — it is *derived* every tick from the player's movement and input, then
replicated in the Snapshot's per-entity `anim` field.

Server precedence, top-down, in `PlayerState::update_animation_state` (`rust/server/src/player.rs`):

| Result | Condition |
|---|---|
| DEATH | `!is_alive` |
| ATTACK | SHOOT flag held |
| RUN | moving (`velocity.length_squared() > 0.01`) **and** SPRINT flag |
| WALK | moving, not sprinting |
| IDLE | otherwise (no movement) |

HIT and SPAWN are set imperatively elsewhere, not by this derivation: HIT on a non-fatal
`take_damage` (`player.rs`), SPAWN by `reset_for_respawn`. Monsters reuse the same enum but only
ever emit IDLE / WALK / ATTACK (`rust/server/src/monster.rs` `update_monster` animation sync;
HIT/DEATH are set in `MonsterState::take_damage`). The client reads `anim` purely for visuals
(remote-entity animation); it is never predicted.

---

## 3. Player movement — `MoveState` (shared sim: server-authoritative + client-predicted)

`enum MoveState { Idle, Walking, Sprinting, Dashing, KnockedBack, Stunned, AbilityMovement,
Charging }` (`rust/sim_core/src/movement.rs`). This is the one **shared** machine: the server owns
the authoritative `MovementSm` on `PlayerState` and drives it once per tick via
`sim_core::step_player`; the client runs an identical `MovementSm` through the `PredictionSim`
GDExtension wrapper for responsiveness. Same compiled crate ⇒ zero divergence by construction.

`MovementSm::tick(dt, move_dir, sprint, dash, ability, attacking, aim_dir)` runs a fixed intra-tick
order — timers → stamina (using the *previous* tick's state) → mana → edge detection →
dash/ability/attack actions → dispatch on the (possibly just-changed) state — then returns the
velocity to integrate. Transitions funnel through `transition_to`, which early-returns on same-state
and is gated by `can_transition` (the guard table below). GDScript signals are not ported; callers
diff `state()` before/after `tick()` for transition-driven effects (HUD/audio live client-side).

| From | To | Trigger | Guard |
|---|---|---|---|
| Idle/Walking/Sprinting | (each other) | move dir / sprint held | sprint needs `stamina > 0`, not exhausted, not dazed |
| Idle/Walking/Sprinting | Dashing | dash edge (`try_dash`) | cooldown ready, not dazed, not Stunned/KnockedBack/AbilityMovement/Charging, dir≠0 |
| Dashing | Idle | dash duration elapses (≈13 ticks, float residue) | — |
| Idle/Walking/Sprinting | Charging | RMB ability edge with `charge_speed > 0` (Warrior) | cooldown ready, mana ≥ cost, charge dir≠0, not Stunned/KnockedBack |
| Charging | Idle | RMB released, max distance spent, or server `end_charge` (enemy contact) | natural end flags the AOE blast (`charge_just_ended`); `end_charge`/stun/teleport do not |
| any (except Stunned/KnockedBack) | KnockedBack | `apply_knockback()` | dir≠0, force>0, finite; **server-only caller** (client never predicts knockback) |
| KnockedBack | Idle | velocity decays below `PLAYER_KNOCKBACK_END_SPEED` | interruptible only by Stunned/AbilityMovement |
| any | Stunned | `apply_stun()` | duration>0; cancels an in-progress dash or charge |
| Stunned | Idle | stun timer elapses | only the timer may release it |
| (most) | AbilityMovement | `start_ability_movement()` | not Stunned |
| AbilityMovement | Idle | `end_ability_movement()` | — |

Notes specific to the Rust port:
- **Guard table** (`can_transition`): `Stunned` only releases to `Idle` (via its own timer);
  `KnockedBack` rides out unless interrupted by `Stunned` / `AbilityMovement`.
- **Charging** is the protocol-v4 Class-ability state for the **Warrior Charge** (held-input dash
  along the aim/move direction, invulnerable, up to a max distance; ends → server spawns an AOE
  blast). It is fully **predicted** (purely directional, no target lookup). The Rogue **Shadowstep**
  blink is also predicted movement but is realized as a server teleport + `interrupt_to_idle`, not a
  dedicated state. Only Warrior/Rogue/Mage are in pre-alpha scope; the RMB ability spends **Mana**.
- **Instant (non-charge) abilities** set the transient `ability_fired` flag (no state change) for the
  server to dispatch; the client plays cast VFX. Cleared at the top of every tick.
- **Daze** (`apply_daze`, hit-while-sprinting) is **not a state** — it is a timer that refuses sprint
  and dash while it runs; walking proceeds. Replicated via the `DAZED` entity flag (bit 8).
  **Stealth** (Rogue, bit 9) and **Exhaustion** (sprint-stamina lockout) are likewise timer/flag
  states, not `MoveState`s.
- **Determinism:** timers decrement `max(0.0, x - dt)` in f64; the exact accumulation order is
  load-bearing (a dash lasts 13 ticks at 30 Hz from f64 residue). Knockback decay uses `f64::exp`
  (not bit-stable across libm), but it is server-only, so it cannot desync prediction (pinned by a
  CI bit test). Per-class tuning (`set_base_speed`, `set_ability_config`) is set identically on both
  sides and preserved across `reset()`.

Authoritative correction: movement-SM divergence is corrected by position reconciliation (replay via
`replay_step`) plus the `ActionConfirm` stamina/mana sync (`set_resources`, epsilon-gated). Full
detail — numbers, signals, reconciliation caveat, status effects — lives in
[`players-movement-state-machine.md`](players-movement-state-machine.md).

---

## 4. Monster AI — `AiState` (server-authoritative)

`enum AiState { Idle, Chase, Attack, Flee }` (`rust/server/src/monster.rs`). One per monster,
evaluated each tick by `MonsterAi::update_monster` → `match monster.ai_state`. Transitions funnel
through `transition`, which is a no-op on same-state and resets per-state flags. Full behavior —
target scoring, kiting, predictive aim, the three-layer spawn director — is documented in
[`monsters-ai.md`](monsters-ai.md); the transition map:

| From | To | Trigger | Evidence |
|---|---|---|---|
| (any) | Idle | no alive players / target lost / target turns Stealth (Rogue Shadowstep) | `monster.rs` `select_target`, `process_*` (target filter), Stealth aggro drop |
| Idle | Chase | a valid alive target acquired | `monster.rs` `process_idle` |
| Chase | Attack | distance ≤ attack range | `monster.rs` `process_chase` |
| Chase | Flee | distance < flee distance | `monster.rs` `process_chase` |
| Attack | Chase | distance > attack range·1.2 (hysteresis), or post-attack out of range | `monster.rs` `process_attack` |
| Attack | Flee | target rushed inside flee distance | `monster.rs` `process_attack` |
| Flee | Attack | reached preferred distance and within attack range | `monster.rs` `process_flee` |
| Flee | Chase | reached preferred distance but out of attack range | `monster.rs` `process_flee` |

Only `Attack` can fire a projectile (gated by `shoot_cooldown`; the fired flag bubbles up as a
`FireEvent`). All thresholds scale with a per-monster `difficulty` (0..1) via the `MonsterAi`
lerp helpers (`retarget_interval`, `detection_range`, `attack_range`, …). The `stationary_dummy`
profile (`target_dummy`) never leaves `Idle`. A targeted monster never goes idle from distance alone
(the lose-interest branch is effectively dead code — ported as-is, see `monsters-ai.md`). All RNG
goes through the sim-owned PCG (`rng::Pcg32`, seedable for tests).

---

## 5. Game / scene flow — `GameState` + `SceneManager` routing (client)

Client-only since the Rust port — the server has no `GameState`. Two cooperating pieces:

**`GameManager.GameState`** (`client/autoload/game_manager.gd`): INITIALIZING / MAIN_MENU / LOADING /
IN_ARENA / PAUSED / EXITING. `change_state` is a guarded setter (no-op if unchanged) that emits
`game_state_changed` and dispatches `_handle_state_transition`.
- The client boots to MAIN_MENU after loading settings.
- PAUSED and EXITING exist in the enum; EXITING has an enter-handler that saves settings. PAUSED has
  no handler branch (HUD pause is UI-only).

**`SceneManager`** owns the actual scene swaps and drives `GameState` as a side effect via
`_update_game_state_for_scene`: the menu scenes → `GameState.MAIN_MENU`, LOADING → LOADING,
ARENA → IN_ARENA.

Client initial routing, after one frame, in `_route_to_initial_scene`:

| Condition | Scene |
|---|---|
| not logged in | LOGIN |
| logged in, no character | CHARACTER_CREATION |
| logged in, has character | MAIN_MENU |

**Test-scene escape hatch:** `_ready` returns early — **skipping all routing** — when the current
scene path begins with `res://scenes/test/` (or is the practice level). This is why test scenes
(`sandbox.tscn`, `net_smoke.tscn`) build their world inline instead of being routed. `NetworkManager`
mirrors this check (`_is_test_scene`) so a headless test scene still runs as a client rather than
tripping the retired-server-mode guard.

Transitions go through `change_scene`, which guards re-entrancy with `is_transitioning`, fades
(client only), cleans up the old scene, and on arena exit disconnects the network.

---

## 6. Connection lifecycle — `ConnectionState` (client)

`enum ConnectionState { DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, ERROR }`
(`client/autoload/network_manager.gd`). Client-only. The transport is **ENet over UDP** through the
`ENetTransport` seam (the wire codec is the Rust `ProtocolCodec` GDExtension) — **not** Godot
High-Level Multiplayer, `MultiplayerSynchronizer`, `ENetMultiplayerPeer`, or WebSocket. There is no
app-level heartbeat: ENet provides native keepalive/RTT, and the clock-sync payload (`server_ms`)
rides every Snapshot. Polled in `_process` via a `match` on `current_state` (per render frame, not
per tick).

| From | To | Trigger | Evidence |
|---|---|---|---|
| DISCONNECTED | CONNECTING | `connect_to_server` | `network_manager.gd` `connect_to_server` |
| CONNECTING | CONNECTED | link reaches `LinkState.OPEN` → `_complete_connection` | `network_manager.gd` `_wait_for_connection`, `_complete_connection` |
| CONNECTING | ERROR | timeout (`connection_timeout_seconds` 5 s) or link CLOSED → `_fail_connection_attempt` | `network_manager.gd` `_wait_for_connection`, `_fail_connection_attempt` |
| CONNECTED | DISCONNECTED | clean `disconnect_from_server` | `network_manager.gd` `disconnect_from_server` |
| CONNECTED | DISCONNECTED | link observed CLOSED → `_on_connection_closed` | `network_manager.gd` `_process_connected`, `_on_connection_closed` |
| ERROR / DISCONNECTED | RECONNECTING | `_schedule_reconnect` (had a prior success) | `network_manager.gd` `_fail_connection_attempt`, `_on_connection_closed`, `_schedule_reconnect` |
| RECONNECTING | CONNECTING | backoff timer elapses → `_attempt_reconnect` | `network_manager.gd` `_process_reconnecting`, `_attempt_reconnect` |
| RECONNECTING | ERROR | `reconnect_attempts ≥ max` (5) | `network_manager.gd` `_schedule_reconnect` |
| RECONNECTING | DISCONNECTED | intentional `disconnect_from_server` cancels pending reconnect | `network_manager.gd` `disconnect_from_server` |

Sub-flows:
- **Auth handshake** is *not* part of the enum. On reaching CONNECTED, `_complete_connection` resets
  `_auth_handshake_sent = false` and lets the arena scene fire `send_auth_handshake` (`ConnectAuth`,
  ch1 reliable) once its listener is bound. The send is idempotent per session. Authentication is an
  **Ed25519 session ticket** minted by the Go API and verified locally by the server (dev default
  `--allow-unsigned-tickets`: an empty ticket is trusted). The explicit `AuthResult` (S→C, ch1)
  carries the entity id for instant Authority sync; `PLAYER_INFO` remains the name/color fallback.
- **Liveness** is ENet-native — no app heartbeat. RTT comes from `client_rtt_ms()`; a dropped link
  surfaces as `LinkState.CLOSED` in `_process_connected`. `server_ms` on each Snapshot feeds the EMA
  clock-offset filter (`_update_clock_from_server_ms`, alpha 0.2, u32-wrap-folded).
- **Reconnect backoff** is exponential: `delay = min(base·2^attempts, max)` = `min(1.0·2^n, 32.0)`
  → 1, 2, 4, 8, 16, capped at 32 s, for up to `max_reconnect_attempts` 5. A successful connect resets
  `reconnect_attempts` to 0. Auto-reconnect only fires if `server_url` is set and a prior connection
  succeeded (`_had_successful_connection`), so a first-attempt failure surfaces as a plain
  `connection_error`.
- **Suppressed reconnect** — an *expected* disconnect must not feed the backoff loop. The
  `_suppress_auto_reconnect` flag gates `_schedule_reconnect`: `_on_connection_closed` only
  reconnects when `_had_successful_connection and not _suppress_auto_reconnect`. Two callers set it:
  - **Hardcore (permadeath) death.** When the local player's death is detected as hardcore, the arena
    calls `NetworkManager.suppress_auto_reconnect()` *before* the server's kick lands. Without this
    the kick reconnects, re-auths, and the server re-spawns the now-deleted character behind the
    death screen — a respawn loop, since the server immediately re-kicks.
  - **Intentional disconnect.** `disconnect_from_server` sets the flag and, when already in
    RECONNECTING (transport closed, backoff timer ticking), forces DISCONNECTED + `client_reset`
    instead of early-returning — otherwise a pending reconnect fires after the user has left to the
    main menu / Sanctuary.

  The flag is cleared on the next fresh `connect_to_server` (non-reconnect path), so a later session
  reconnects normally.

---

## The eight questions

- **Client:** runs `ConnectionState`, `GameState` routing (`SceneManager`), the client copy of the
  movement `MovementSm` (prediction), and renders the replicated `anim` / flags. No authoritative
  game state.
- **Server:** owns `LifeState`, `AiState`, the authoritative movement `MovementSm`, and the
  movement-derived `anim`. There is no server-side `GameState` (one process = one instance).
- **Predicted:** the client predicts Local-player *position* AND the movement `MovementSm`
  (dash/sprint/charge + stamina/mana) by running the same `sim_core` crate. Knockback is **not**
  predicted (server-only). Life / animation / monster AI are authoritative-only and never predicted.
  Movement-SM divergence is corrected by position reconciliation plus the `ActionConfirm`
  stamina/mana sync.
- **Replicated:** life and movement status as `entity_flags` bits (ALIVE/INVULNERABLE/DASHING/
  KNOCKED_BACK/STUNNED/DAZED/STEALTH) and the per-entity `anim` byte in each Snapshot; monster AI
  state only via its resulting animation + movement.
- **Persisted:** none of these machines persist — all gameplay state is server-authoritative and
  **in-memory**. Only accounts/characters/leaderboard/regions/Glory persist, owned by the Go API
  (Postgres + Redis).
- **Validated:** life transitions gate on server health/timers; respawn is gated by `respawn_timer`
  and silently rejects early requests; dead-player input is dropped; connection transitions gate on
  link state and timeouts. Governing rule everywhere: **the client requests, the server decides.**
- **Can fail:** invuln can end a frame "early" on the input that also moves you; PAUSED has no
  `GameState` handler; reconnect gives up after 5 attempts → ERROR; a missed test-scene-path check
  would mis-route a test scene.
- **Tested:** the movement SM and monster AI have Rust unit tests in their modules
  (`movement.rs` / `monster.rs` `#[cfg(test)]`, including determinism bit-tests); server life/AI are
  exercised by the `omega-load-test` bot swarm and arena E2E test scenes (`net_smoke.tscn`); scene
  routing is verified manually.

## See also

- [`players-movement.md`](players-movement.md) — movement integration that feeds the animation states
- [`players-movement-state-machine.md`](players-movement-state-machine.md) — full `MoveState` detail (numbers, daze/charge, reconciliation)
- [`abilities.md`](abilities.md) — Class abilities (Warrior Charge, Rogue Shadowstep) behind the Charging/AbilityMovement states
- [`monsters-ai.md`](monsters-ai.md) — full `AiState` behavior, scoring, spawn director, and combat
- [`combat-hits.md`](combat-hits.md) — what drives Alive→Dead (the two-netcode hit model)
- [`../server/contract.md`](../server/contract.md) — the ENet/UDP transport and wire format behind `ConnectionState`
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Authority sync, Game event, Snapshot)
