# State machines (player life, movement, scene, connection, AI)

**Status:** Implemented (verified 2026-06-03 against code).

The POC runs five distinct finite state machines, split across server and client. None
share a base class — each is a hand-rolled `enum` plus a `match` (or `if`) transition block.
This doc enumerates the states, the transitions, where each lives, and which side owns it,
so you can reason about every authoritative or UI state change in one place.

| Machine | Enum / values | Owner | Where |
|---|---|---|---|
| Player life | `PlayerLifeState` ALIVE / DEAD / INVULNERABLE | Server | `player_state.gd:8` |
| Player animation (movement-derived) | `AnimationState` IDLE / WALK / RUN / ATTACK / HIT / DEATH / SPAWN | Server (derived), replicated | `packet_types.gd:35`, `player_state.gd:318` |
| Game / scene state | `GameState` INITIALIZING / MAIN_MENU / LOADING / IN_ARENA / PAUSED / EXITING | Both (different routes) | `game_manager.gd:6`, `scene_manager.gd:20` |
| Connection lifecycle | `ConnectionState` DISCONNECTED / CONNECTING / CONNECTED / RECONNECTING / ERROR | Client | `network_manager.gd:7` |
| Monster AI | `AIState` IDLE / CHASE / ATTACK / FLEE | Server | `monster_ai.gd:9` |

---

## 1. Player life — `PlayerLifeState` (server-authoritative)

`enum PlayerLifeState { ALIVE, DEAD, INVULNERABLE }` (`player_state.gd:8`). One per connected
player, held on the server `PlayerState`. The client never sets it; it only *reflects* it via
the `ENTITY_FLAG_INVULNERABLE` / `ENTITY_FLAG_ALIVE` bits in each Snapshot.

| From | To | Trigger | Evidence |
|---|---|---|---|
| ALIVE | DEAD | `take_damage` drops health ≤ 0 → `_mark_dead` | `player_state.gd:384,393` |
| INVULNERABLE | DEAD | (cannot — invuln blocks damage; `take_damage` returns false) | `player_state.gd:379` |
| DEAD | INVULNERABLE | respawn after `RESPAWN_DELAY` 3.0 s → `reset_for_respawn` | `player_state.gd:413,353` |
| INVULNERABLE | ALIVE | active move/shoot input, OR `INVULNERABILITY_DURATION` 3.0 s timer | `player_state.gd:225,422` |

Details:
- **Death** zeros velocity/input, clears the input + pending-shot queues, sets `respawn_timer =
  RESPAWN_DELAY` (3.0 s), bumps `deaths`, records `last_killer_id`, sets `AnimationState.DEATH`
  (`player_state.gd:397-409`). `_mark_dead` is idempotent (guards on already-DEAD, `:394`).
- **Respawn** is driven by `update_respawn_timer` counting `respawn_timer` to 0
  (`player_state.gd:413-418`); `reset_for_respawn` then enters INVULNERABLE with
  `invulnerability_timer = INVULNERABILITY_DURATION` (3.0 s) and `AnimationState.SPAWN`
  (`:353-369`).
- **Invulnerability ends two ways**: (a) the player acts — `step()` calls `end_invulnerability()`
  when `has_active_input()` sees any move or SHOOT flag (`player_state.gd:225-226,443-447`); or
  (b) the 3 s timer expires via `update_invulnerability` (`:422-430`). Either path routes through
  `end_invulnerability()` (`:434`), which clears `ENTITY_FLAG_INVULNERABLE`.
- **Dead players are inert**: `ingest_input` discards input while DEAD (`player_state.gd:135`),
  and `step()` early-returns with zeroed velocity (`:207-218`).

---

## 2. Player animation (movement-derived) — `AnimationState`

`enum AnimationState { IDLE, WALK, RUN, ATTACK, HIT, DEATH, SPAWN }` (`packet_types.gd:35`).
This is not a separate controller — it is *derived* every Tick from the player's movement and
input, then replicated in the Snapshot's per-entity `anim` byte. The spec's "IDLE/WALKING"
movement machine is exactly these states.

Server precedence, top-down, in `_update_animation_state()` (`player_state.gd:318-329`):

| Result | Condition |
|---|---|
| DEATH | `not is_alive` |
| ATTACK | SHOOT flag held |
| RUN | moving (`velocity² > 0.01`) **and** SPRINT flag |
| WALK | moving, not sprinting |
| IDLE | otherwise (no movement) |

HIT and SPAWN are set imperatively elsewhere, not by this derivation: HIT on a non-fatal
`take_damage` (`player_state.gd:388`), SPAWN by `reset_for_respawn` (`:368`). Monsters reuse the
same enum but only ever emit IDLE / WALK / ATTACK (`monster_ai.gd:508-518`). The client reads
`anim` purely for visuals (Remote entity animation); it is never predicted.

---

## 3. Game / scene flow — `GameState` + `SceneManager` routing

Two cooperating pieces:

**`GameManager.GameState`** (`game_manager.gd:6`): INITIALIZING / MAIN_MENU / LOADING /
IN_ARENA / PAUSED / EXITING. `change_state` is a guarded setter (no-op if unchanged) that emits
`game_state_changed` and dispatches `_handle_state_transition` (`game_manager.gd:83-108`).
- Server boots straight to IN_ARENA (`_initialize_server`, `:72-75`).
- Client boots to MAIN_MENU after loading settings (`_initialize_client`, `:78-80`).
- PAUSED and EXITING exist in the enum; EXITING has an enter-handler that saves settings
  (`:128-130`). PAUSED has no handler branch (HUD pause is UI-only).

**`SceneManager`** owns the actual scene swaps and drives `GameState` as a side effect via
`_update_game_state_for_scene` (`scene_manager.gd:324-339`): the menu scenes →
`GameState.MAIN_MENU`, LOADING → LOADING, ARENA → IN_ARENA.

Client initial routing, after one frame, in `_route_to_initial_scene` (`scene_manager.gd:91-107`):

| Condition | Scene |
|---|---|
| not logged in | LOGIN (`scene_manager.gd:107`) |
| logged in, no character | CHARACTER_CREATION (`:104`) |
| logged in, has character | MAIN_MENU (`:101`) |

Server routing: `_ready` sends it directly to `SERVER_MAIN` (`scene_manager.gd:83-85`).

**Test-scene escape hatch:** `_ready` returns early — **skipping all routing** — when the current
scene path begins with `res://scenes/test/` (`scene_manager.gd:77-80`). `GameManager` mirrors
this: its server-mode detection is suppressed for test scenes so a headless test scene still runs
as a client (`game_manager.gd:60,256-263`). This is why test scenes (`sandbox.tscn`,
`auto_join_arena.tscn`) build their world inline instead of being routed.

Transitions go through `change_scene` (`scene_manager.gd:110`), which guards re-entrancy with
`is_transitioning`, fades (client only), cleans up the old scene, and on arena exit disconnects
the network (`_cleanup_scene`, `:342-350`).

---

## 4. Connection lifecycle — `ConnectionState` (client)

`enum ConnectionState { DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, ERROR }`
(`network_manager.gd:7`). Client-only; the server side tracks per-peer WebSocket ready-states
directly, not this enum. Polled in `_process_client` via a `match` on `current_state`
(`network_manager.gd:222-227`) — note: polled per render Frame, not per Tick.

| From | To | Trigger | Evidence |
|---|---|---|---|
| DISCONNECTED | CONNECTING | `connect_to_server` | `network_manager.gd:288` |
| CONNECTING | CONNECTED | socket reaches `STATE_OPEN` → `_complete_connection` | `network_manager.gd:319,333-346` |
| CONNECTING | ERROR | timeout 5 s or socket closed → `_fail_connection_attempt` | `network_manager.gd:312,323,349-359` |
| CONNECTED | DISCONNECTED | clean `disconnect_from_server`, or heartbeat timeout 5 s | `network_manager.gd:405-418,250-255` |
| CONNECTED | DISCONNECTED | socket observed CLOSED → `_on_connection_closed` | `network_manager.gd:260,996-999` |
| ERROR / DISCONNECTED | RECONNECTING | `_schedule_reconnect` (had a prior success) | `network_manager.gd:356,1001,1024` |
| RECONNECTING | CONNECTING | backoff timer elapses → `_attempt_reconnect` | `network_manager.gd:267-270,1027-1029` |
| RECONNECTING | ERROR | `reconnect_attempts ≥ max` (5) | `network_manager.gd:1012-1016` |

Sub-flows:
- **Auth handshake** is *not* part of the enum. On reaching CONNECTED, `_complete_connection`
  resets `_auth_handshake_sent = false` and lets the arena scene fire `send_auth_handshake`
  (`CONNECT_AUTH`) once its listener is bound (`network_manager.gd:340-344,369-402`). The send is
  idempotent per session. Authoritative identity arrives later via `PLAYER_INFO` (Authority sync).
- **Heartbeat** runs only in CONNECTED: send 1 Hz (`heartbeat_interval` 1.0), and if no heartbeat
  received for `heartbeat_timeout_seconds` 5.0 s, emit `heartbeat_timeout` and disconnect
  (`network_manager.gd:244-255`). The server mirrors this with a 5 s per-peer timeout (`:215-219`).
- **Reconnect backoff** is exponential: `delay = min(base·2^attempts, max)` =
  `min(1.0·2^n, 32.0)` → 1, 2, 4, 8, 16, then capped at 32 s, for up to
  `max_reconnect_attempts` 5 (`network_manager.gd:83-87,1019-1021`). A successful connect resets
  `reconnect_attempts` to 0 (`:336`). Auto-reconnect only fires if `server_url` is set and a prior
  connection succeeded (`_had_successful_connection`), so a first-attempt failure surfaces as a
  plain `connection_error` (`:356-359,1005-1010`).

---

## 5. Monster AI — `AIState` (server)

`enum AIState { IDLE, CHASE, ATTACK, FLEE }` (`monster_ai.gd:9`). One per monster, evaluated each
Tick by `MonsterAI._update_monster` → `match monster.ai_state` (`monster_ai.gd:76-84`).
Transitions funnel through `_transition_to_state`, which is a no-op on same-state and resets
per-state timers/flags (`monster_ai.gd:301-325`). Full behavior — target scoring, kiting,
predictive aim — is documented in [`monsters-ai.md`](monsters-ai.md); the transition map:

| From | To | Trigger | Evidence |
|---|---|---|---|
| (any) | IDLE | no alive players / target lost / out of lose-interest range | `monster_ai.gd:100-101,123-126,202-203` |
| IDLE | CHASE | a valid alive target acquired | `monster_ai.gd:192-195` |
| CHASE | ATTACK | distance ≤ attack range | `monster_ai.gd:215-216` |
| CHASE | FLEE | distance < flee distance | `monster_ai.gd:210-211` |
| ATTACK | CHASE | distance > attack range·1.2 (hysteresis), or post-attack out of range | `monster_ai.gd:247-248,266-267` |
| ATTACK | FLEE | target rushed inside flee distance | `monster_ai.gd:242-243` |
| FLEE | ATTACK | reached preferred distance and within attack range | `monster_ai.gd:284-286` |
| FLEE | CHASE | reached preferred distance but out of attack range | `monster_ai.gd:287-288` |

Only ATTACK can fire a projectile (gated by cooldown, returns the fired flag up the stack;
`monster_ai.gd:257-261`). All thresholds scale with a per-monster `difficulty` (0..1) via the
`_get_*` lerp helpers (`monster_ai.gd:154-179`).

---

## The eight questions

- **Client:** runs `ConnectionState`, `GameState` routing (`SceneManager`), and renders the
  replicated `AnimationState` / invuln flag — no authoritative state.
- **Server:** owns `PlayerLifeState`, `AIState`, the movement-derived `AnimationState`, and its
  own `GameState` (boots to IN_ARENA).
- **Predicted:** none of these — state-machine transitions are authoritative; the client predicts
  only Local-player *position*, never life/animation/AI state.
- **Replicated:** life (as flags) and animation per-entity in each Snapshot; AI state only via its
  resulting animation + movement.
- **Persisted:** none — all five are in-memory; only account/character/stats persist (Go API).
- **Validated:** life transitions gate on server health/timers; dead-player input is dropped
  (`player_state.gd:135`); connection transitions gate on socket ready-state and timeouts.
- **Can fail:** invuln can end a frame "early" on the input that also moves you; PAUSED has no
  `GameState` handler; reconnect gives up after 5 attempts → ERROR; a missed test-scene-path check
  would mis-route a test scene to LOGIN/SERVER_MAIN.
- **Tested:** server life/AI machines exercised by the bot swarm and arena E2E test scenes; scene
  routing is verified manually; no isolated unit test per machine today.

## See also

- [`players-movement.md`](players-movement.md) — movement integration that feeds the animation states
- [`monsters-ai.md`](monsters-ai.md) — full `AIState` behavior, scoring, and combat
- [`combat-hits.md`](combat-hits.md) — what drives ALIVE→DEAD (damage and hit resolution)
- [`../netcode/transport-websocket.md`](../netcode/transport-websocket.md) — the transport behind `ConnectionState`
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Authority sync, Game event, Snapshot)
