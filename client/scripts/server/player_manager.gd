## PlayerManager - Server-side player management system
## Handles player connections, disconnections, and state management
## Used by ServerMain for all player-related operations
class_name PlayerManager
extends RefCounted


class PlayerPositionSnapshot extends RefCounted:
	var entity_id: int = 0
	var position: Vector2 = Vector2.ZERO

	static func create(p_entity_id: int, p_position: Vector2) -> PlayerPositionSnapshot:
		var snapshot := PlayerPositionSnapshot.new()
		snapshot.entity_id = p_entity_id
		snapshot.position = p_position
		return snapshot


## All connected players: peer_id -> PlayerState
var players: Dictionary = {}

## Recent per-tick player positions used for PvP projectile lag compensation.
var _position_history: Dictionary = {}  # server_tick -> Array[PlayerPositionSnapshot]
var _position_history_ticks: Array[int] = []
const POSITION_HISTORY_TICKS := 8

## Entity ID counter for unique player entity IDs
var _next_entity_id: int = 1

## Round-robin index into shared arena spawn positions
var _spawn_index: int = 0

## Debug logging flag
var debug_logging: bool = true


## Add a new player when they connect
func add_player(peer_id: int) -> PlayerState:
	if players.has(peer_id):
		if debug_logging:
			print("[PlayerManager] Player already exists: %d" % peer_id)
		return players[peer_id]

	var entity_id = _next_entity_id
	_next_entity_id += 1

	var spawn_pos = _get_spawn_position()
	var state = PlayerState.create(peer_id, entity_id, spawn_pos)

	players[peer_id] = state

	if debug_logging:
		print("[PlayerManager] Player added: peer=%d, entity=%d, pos=%s" % [peer_id, entity_id, spawn_pos])

	return state


## Remove a player when they disconnect
func remove_player(peer_id: int) -> void:
	if not players.has(peer_id):
		if debug_logging:
			print("[PlayerManager] Cannot remove unknown player: %d" % peer_id)
		return

	var state: PlayerState = players[peer_id]
	players.erase(peer_id)

	if debug_logging:
		print("[PlayerManager] Player removed: peer=%d, entity=%d" % [peer_id, state.entity_id])


## Get a player by peer_id
func get_player(peer_id: int) -> PlayerState:
	return players.get(peer_id, null)


## Get a player by entity_id
func get_player_by_entity_id(entity_id: int) -> PlayerState:
	for state in players.values():
		if state.entity_id == entity_id:
			return state
	return null


## Get current player count
func get_player_count() -> int:
	return players.size()


## Get all players as an array
func get_all_players() -> Array[PlayerState]:
	var result: Array[PlayerState] = []
	for state in players.values():
		result.append(state)
	return result


## Queue input for a player
func queue_player_input(peer_id: int, input_data: Dictionary) -> void:
	var state = get_player(peer_id)
	if state == null:
		if debug_logging:
			print("[PlayerManager] Cannot queue input for unknown player: %d" % peer_id)
		return
	if not state.authenticated:
		if debug_logging:
			print("[PlayerManager] Ignoring input from unauthenticated player: %d" % peer_id)
		return

	state.queue_input(input_data)


## Process all queued inputs for all players and advance one server tick.
## Drains each player's queued inputs into the persistent input model, then
## simulates exactly one tick of movement. Returns a single move-confirmation
## per player per tick (using the latest ingested sequence) so clients can
## prune their prediction buffer and reconcile if the server flagged a drift.
func process_all_inputs(delta: float, server_tick: int) -> Array[Dictionary]:
	var move_results: Array[Dictionary] = []

	for state: PlayerState in players.values():
		if not state.authenticated:
			continue

		# Drain queued inputs into the persistent flags. Rising-edge SHOOT events
		# are recorded in state.pending_shots for ServerMain to consume.
		var had_input := state.has_queued_input()
		while state.has_queued_input():
			state.ingest_input(state.pop_input(), server_tick)

		# Simulate exactly one tick using the persistent flags.
		var validation = state.step(delta, server_tick)

		# Only ack the client when we ingested at least one fresh input;
		# otherwise we'd flood ACTION_CONFIRM with stale sequences.
		if had_input:
			move_results.append({
				"peer_id": state.peer_id,
				"sequence": validation.sequence,
				"position": validation.server_position,
				"success": not validation.correction_needed,
				"cheat_detected": validation.cheat_detected,
				"deviation": validation.deviation,
				"stamina": roundi(state.movement_sm.stamina),
				"mana": roundi(state.movement_sm.mana)
			})

	return move_results


## Collect state updates for broadcasting to clients
## Returns a dictionary ready to be sent via NetworkManager.broadcast_to_clients()
func collect_state_updates(server_tick: int) -> Dictionary:
	var entities: Array[Dictionary] = []

	for state: PlayerState in players.values():
		entities.append(state.to_entity_data())

	return {
		"tick": server_tick,
		"entities": entities
	}


## Authenticate a player with character data
func authenticate_player(
	peer_id: int,
	character_id: String,
	character_name: String,
	player_color: Color = Color(0.27, 0.53, 1.0),
	budget_bps: int = 0
) -> bool:
	var state = get_player(peer_id)
	if state == null:
		if debug_logging:
			print("[PlayerManager] Cannot authenticate unknown player: %d" % peer_id)
		return false

	state.authenticated = true
	state.character_id = character_id
	state.character_name = character_name
	state.player_color = player_color
	state.bandwidth_budget_bps = budget_bps

	if debug_logging:
		print("[PlayerManager] Player authenticated: peer=%d, char=%s, name=%s" % [peer_id, character_id, character_name])

	return true


## Update heartbeat timestamp for a player
func update_heartbeat(peer_id: int) -> void:
	var state = get_player(peer_id)
	if state != null:
		state.last_heartbeat = Time.get_ticks_msec() / 1000.0


## Check for timed out players
## Returns array of peer_ids that have timed out
func check_heartbeat_timeouts(timeout_seconds: float) -> Array[int]:
	var current_time = Time.get_ticks_msec() / 1000.0
	var timed_out: Array[int] = []

	for peer_id: int in players.keys():
		var state: PlayerState = players[peer_id]
		if current_time - state.last_heartbeat > timeout_seconds:
			timed_out.append(peer_id)

	return timed_out


## Get the next spawn position (round-robin)
func _get_spawn_position() -> Vector2:
	var spawn_points := GameConstants.get_valid_player_spawns()
	if spawn_points.is_empty():
		push_warning("[PlayerManager] No valid arena player spawns configured; using map center")
		return GameConstants.clamp_to_bounds(Vector2.ZERO)

	var pos := spawn_points[_spawn_index % spawn_points.size()]
	_spawn_index = (_spawn_index + 1) % spawn_points.size()
	return pos


## Respawn a player at a spawn point
func respawn_player(peer_id: int) -> bool:
	var state = get_player(peer_id)
	if state == null:
		return false

	var spawn_pos = _get_spawn_position()
	state.reset_for_respawn(spawn_pos)

	if debug_logging:
		print("[PlayerManager] Player respawned: peer=%d, pos=%s" % [peer_id, spawn_pos])

	return true


## Get all authenticated players
func get_authenticated_players() -> Array[PlayerState]:
	var result: Array[PlayerState] = []
	for state: PlayerState in players.values():
		if state.authenticated:
			result.append(state)
	return result


## Get all alive players
func get_alive_players() -> Array[PlayerState]:
	var result: Array[PlayerState] = []
	for state: PlayerState in players.values():
		if state.authenticated and state.is_alive:
			result.append(state)
	return result


## Record alive player positions for this authoritative tick.
func record_position_snapshot(server_tick: int) -> void:
	var snapshot: Array[PlayerPositionSnapshot] = []
	for state: PlayerState in players.values():
		if state.authenticated and state.is_alive:
			snapshot.append(PlayerPositionSnapshot.create(state.entity_id, state.position))

	_position_history[server_tick] = snapshot
	_position_history_ticks.append(server_tick)

	while _position_history_ticks.size() > POSITION_HISTORY_TICKS:
		var old_tick: int = _position_history_ticks.pop_front()
		_position_history.erase(old_tick)


## Get alive player positions from a recent tick, falling back gracefully if the
## requested tick is outside the short history window.
func get_alive_player_snapshot(server_tick: int) -> Array:
	if _position_history.has(server_tick):
		return _position_history[server_tick]

	var best_tick := -1
	for tick: int in _position_history_ticks:
		if tick <= server_tick and tick > best_tick:
			best_tick = tick

	if best_tick >= 0:
		return _position_history[best_tick]

	if not _position_history_ticks.is_empty():
		return _position_history[_position_history_ticks[0]]

	return get_alive_players()


## Recent authoritative positions for a player entity across the history window
## (oldest first), including the live position. Used to validate client-reported
## monster-projectile hits against where the player actually was.
func get_recent_positions(entity_id: int) -> Array:
	var positions: Array = []
	for tick: int in _position_history_ticks:
		for snap in _position_history[tick]:
			if snap.entity_id == entity_id:
				positions.append(snap.position)
				break
	var live := get_player_by_entity_id(entity_id)
	if live != null:
		positions.append(live.position)
	return positions


## Check if a peer is connected
func has_player(peer_id: int) -> bool:
	return players.has(peer_id)


## Clear all players (for shutdown)
func clear_all() -> void:
	players.clear()
	_position_history.clear()
	_position_history_ticks.clear()
	if debug_logging:
		print("[PlayerManager] All players cleared")
