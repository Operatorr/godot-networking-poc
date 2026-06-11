# Desync / Ghost Player Fix Plan

## Context

The user reports a major client/server desync:
- A purple "ghost" player with the user's own name mirrors the user's movements but at a different position. All monsters target the ghost.
- Server logs are flooded with `CHEAT DETECTED: peer=… teleport attempt (deviation=…)` where the deviation grows monotonically (≈540 → 826 → 1422) and only flatlines when the player stops moving.
- After a server-side death/respawn, the deviation jumps to 1422.6, indicating the client never followed the respawn. AoI culling (radius 500) hides every monster except those near the server-side ghost, which is why the user only sees 1–2 monsters all attacking the ghost.

The "ghost" is the server-authoritative version of the local player being rendered as a remote entity, because the client never learned its own `entity_id`. The deviation grows because the server only advances player movement by `1/tick_rate` of motion per **received input**, not per real-time tick.

## Root Causes

### 1. Persistent-input speed mismatch (drives the growing CHEAT deviation)
- `client/scripts/server/server_main.gd:200` (`_process_client_inputs`) → `client/scripts/server/player_manager.gd:98` (`process_all_inputs`) → `client/scripts/server/player_state.gd:114` (`apply_input`).
- The server runs at 30 Hz (`server_config.gd:9`). The client sends inputs at 10 Hz (`prediction.gd:61`, `INPUT_SEND_INTERVAL = 0.1`).
- Each server tick pops every queued input and applies movement with `delta = 1/30 ≈ 33 ms`. Between sends only 1 input arrives, so the server applies ~33 ms of motion per ~100 ms of wall time — i.e., **the server walks at 1/3 client speed**.
- Client predicts at full speed (200 u/s × 0.1 s = 20 u per send window); server moves ~6.6 u → ~13 u/send divergence accumulates as 130 u/s of drift, easily reaching 540+ u in a few seconds. The deviation freezes only when input_flags=0 (player idle).

### 2. `local_player_entity_id` is never set (the ghost)
- `client/scripts/client/client_entity_manager.gd:129` filters out the local player by `entity_id == GameManager.get_local_player_entity_id()`. The id is set in `client/scripts/shared/arena_base.gd:313` (`_handle_player_info`) when a `PLAYER_INFO` GAME_EVENT with the matching `character_name` arrives.
- Race: `network_manager.gd:311` calls `send_auth_handshake()` the moment the WebSocket opens (during `_complete_connection`). The server immediately responds with `broadcast_player_info` (`server_main.gd:427`).
- At that point the client is still on the main menu (`main_menu.gd:248-260` waits 0.5 s then calls `SceneManager.goto_arena()`). Arena's signal subscription happens later in `arena_base._setup_client → line 167`. The PLAYER_INFO event is decoded but the `server_message_received` signal has no listener yet, so it's silently dropped. The id is never set; the local entity is rendered as a remote ghost forever.
- This also disables `_handle_respawn_event` (line 402, gated by `entity_id == local_id`), explaining why after server respawn the client never teleports → 1422 u deviation.

### 3. Initial spawn-position mismatch
- `client/scripts/shared/arena_base.gd:196`: `local_player.position = get_random_player_spawn()` chooses a random client-side spawn.
- `client/scripts/server/player_manager.gd:30 → _get_spawn_position`: server picks a deterministic round-robin spawn from the same list.
- Because PLAYER_INFO is missed (Bug 2), the client never force-syncs to the server's spawn either, so divergence is non-zero from frame 0 even before the speed bug accumulates more.

## Fix Strategy

### Fix A — Persistent-input model (server)

Change the server to keep the *current* input state per player and apply it every tick at the server's tick rate. New inputs overwrite the latest flags; shoot edges still spawn projectiles immediately. This makes the server simulate at the same rate as the client predicts.

**Files:**
- `client/scripts/server/player_state.gd`
  - Add fields: `current_input_flags: int`, `current_aim_angle: float`, `last_input_sequence: int`, `last_client_position: Vector2`, `last_input_received_tick: int`, `pending_shoot: bool`.
  - Replace `apply_input(input, delta)` with two methods:
    - `ingest_input(input, server_tick)` — record the latest flags/aim/position/sequence; set `pending_shoot` if `INPUT_FLAG_SHOOT` was newly pressed (rising edge tracked against the previous flag set).
    - `step(delta)` — called every tick. Computes movement from `current_input_flags` with `delta = tick_interval`, runs obstacle collision, validates the *latest* `last_client_position` against the server position once per tick, returns a correction dict.
  - Keep the dead/invulnerable handling and animation-state updates inside `step`.
  - Stale-input safety: if `server_tick - last_input_received_tick > N` ticks (e.g. 6 = 200 ms) zero out `current_input_flags` so a disconnecting client doesn't keep sliding.

- `client/scripts/server/player_manager.gd`
  - Replace the `process_all_inputs` while-loop with: drain queue → `ingest_input` for each → `step(delta)` exactly once per tick per player. Return the correction dict from `step`.
  - Add `get_pending_shots()` so `ServerMain._process_shoot_inputs` consumes one shoot edge per pending input rather than scanning the queue.

- `client/scripts/server/server_main.gd`
  - `_process_shoot_inputs`: iterate `player_manager.get_pending_shots()` instead of walking `state.input_queue`.
  - Make sure `process_all_inputs` is still called once per tick (it already is).

This change makes server movement framerate-decoupled from client send rate. Combined with input dedupe, deviation should stay <CORRECTION_THRESHOLD (112.5) under normal play.

### Fix B — Auth/PLAYER_INFO ordering (defer auth until arena is ready)

Move the auth handshake out of `_complete_connection` and into `arena_base._setup_client` so the arena's signal handlers are bound before any server response arrives.

**Files:**
- `client/autoload/network_manager.gd`
  - Remove the auto-`send_auth_handshake()` call inside `_complete_connection` (lines 311–312). Keep `auth_token` storage.
  - Expose `auth_token`/`is_authenticated_pending` so callers can re-issue if needed.
  - Make `send_auth_handshake()` idempotent (no-op if already sent in this session).

- `client/scripts/shared/arena_base.gd`
  - In `_setup_client` (after `NetworkManager.server_message_received.connect(_on_server_message)` and before spawning the local player) call `NetworkManager.send_auth_handshake()`.
  - On reconnect (`_on_reconnected`): re-send auth handshake so PLAYER_INFO is re-broadcast to the client after a transient drop.

- `client/scripts/client/main_menu.gd`
  - No change to `connect_to_server`; the menu still passes the auth token. Auth just isn't sent until the arena is ready.

Defensive backstop: in `client/scripts/server/server_broadcast_service.gd::handle_full_state_request`, also re-send `PLAYER_INFO` for every authenticated player. Then trigger one `REQUEST_FULL_STATE` from `arena_base._setup_client` immediately after sending auth — this guarantees recovery if any future timing regression drops PLAYER_INFO.

### Fix C — Sync local player to server spawn

Once the local entity_id is reliably known (Fix B), force-sync position on first sighting.

**Files:**
- `client/scripts/shared/arena_base.gd::_handle_player_info` — when `entity_id` matches our `character_name`, call `prediction_controller.force_sync(server_position)`. The position can come from either:
  - Adding `position: Vector2` to the `PLAYER_INFO` GameEvent payload (preferred — adds 4 bytes, simple), OR
  - Reading the next STATE_UPDATE entry for our entity_id and using that.
  - Recommended: extend `PLAYER_INFO` with a quantized vector2 (writer.write_vector2_compressed) in `client/scripts/shared/networking/packets/game_event_packet.gd` and `client/autoload/network_manager.gd::_write_game_event_data`. Server populates it from `state.position` in `server_broadcast_service.broadcast_player_info`.

- `client/scripts/shared/arena_base.gd::_spawn_local_player` — drop the `get_random_player_spawn()` call; spawn at `Vector2.ZERO` (or last-known) and rely on `force_sync` from PLAYER_INFO. Hide `local_player.visible = false` until the entity_id is set, then show.

- `client/scripts/client/prediction.gd::force_sync` — already implemented (line 555). Reuse as-is.

## Critical Files (summary)

- `client/scripts/server/player_state.gd` — input model rewrite
- `client/scripts/server/player_manager.gd` — drain→ingest→step pipeline
- `client/scripts/server/server_main.gd` — pending shots consumption
- `client/autoload/network_manager.gd` — defer auth send; re-send on reconnect
- `client/scripts/shared/arena_base.gd` — send auth in `_setup_client`; force-sync in `_handle_player_info`; remove client-side random spawn
- `client/scripts/server/server_broadcast_service.gd` — include PLAYER_INFO in full-state response; add position to broadcast_player_info
- `client/scripts/shared/networking/packets/game_event_packet.gd` — extend PLAYER_INFO with position

## Verification

1. **Unit-level**: log `current_input_flags` per player tick on the server; verify movement direction matches across a 1 s capture.
2. **Local end-to-end**:
   - `./scripts/dev_local.sh` (api+server), launch client, log in as Opera.
   - Walk in a circle for 30 s. Server log must show **zero** `CHEAT DETECTED` lines, and `[ServerMain] Position correction` lines must show `deviation < 30` even at sprint.
   - There must be exactly one player visual; the local Player node and the server's authoritative entity coincide. Toggle the in-game debug overlay (if present) — server position should track the local sprite to within a few pixels.
3. **Death/respawn**: stand still, let monsters kill you. After respawn, the camera must teleport to the server-chosen spawn; the kill feed should still read "Monster killed Opera"; the client must regain control immediately and CHEAT DETECTED must remain at zero post-respawn.
4. **AoI sanity**: with player walking around the arena, monsters should pop in and out of view per the 500 u radius around the *local* player (not a stale server position).
5. **Reconnect**: kill the WebSocket via OS firewall briefly. After auto-reconnect, PLAYER_INFO is re-issued (Fix B reconnect hook) and entity_id stays consistent — no second ghost spawned.
6. **Bot stress**: run `./scripts/run_load_test.sh --scenario baseline` (Rust `omega-load-test` bot swarm). Server log should show no CHEAT spam.

## Out of Scope

- Bandwidth changes (PLAYER_INFO position adds 4 bytes; one-time per join, negligible).
- Reworking AoI radius or monster AI.
- Client-side prediction tuning (interpolation_speed, teleport_threshold) — current values are fine once authority converges.
