## PlayerManager - Server-side player management system
## Handles player connections, disconnections, and state management
## Used by ServerMain for all player-related operations
class_name PlayerManager
extends RefCounted

## All connected players: peer_id -> PlayerState
var players: Dictionary = {}

## Entity ID counter for unique player entity IDs
var _next_entity_id: int = 1

## Fixed spawn points (placeholder until TASK-044)
var _spawn_points: Array[Vector2] = [
	Vector2(100, 100),
	Vector2(-100, 100),
	Vector2(100, -100),
	Vector2(-100, -100)
]
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

	state.queue_input(input_data)


## Process all queued inputs for all players
func process_all_inputs(_delta: float) -> void:
	for state: PlayerState in players.values():
		while state.has_queued_input():
			var input = state.pop_input()
			state.apply_input(input)


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
func authenticate_player(peer_id: int, character_id: String, character_name: String) -> bool:
	var state = get_player(peer_id)
	if state == null:
		if debug_logging:
			print("[PlayerManager] Cannot authenticate unknown player: %d" % peer_id)
		return false

	state.authenticated = true
	state.character_id = character_id
	state.character_name = character_name

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
	var pos = _spawn_points[_spawn_index]
	_spawn_index = (_spawn_index + 1) % _spawn_points.size()
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
		if state.is_alive:
			result.append(state)
	return result


## Check if a peer is connected
func has_player(peer_id: int) -> bool:
	return players.has(peer_id)


## Clear all players (for shutdown)
func clear_all() -> void:
	players.clear()
	if debug_logging:
		print("[PlayerManager] All players cleared")
