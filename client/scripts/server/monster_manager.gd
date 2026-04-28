## MonsterManager - Server-side monster management system
## Handles monster spawning, tracking, and cleanup
## Used by ServerMain for all monster-related operations
class_name MonsterManager
extends RefCounted


class MonsterPositionSnapshot extends RefCounted:
	var entity_id: int = 0
	var position: Vector2 = Vector2.ZERO
	var is_alive: bool = true

	static func create(p_entity_id: int, p_position: Vector2) -> MonsterPositionSnapshot:
		var snapshot := MonsterPositionSnapshot.new()
		snapshot.entity_id = p_entity_id
		snapshot.position = p_position
		snapshot.is_alive = true
		return snapshot


## All active monsters: entity_id -> MonsterState
var monsters: Dictionary = {}

## Entity ID counter for unique monster entity IDs
## Uses a u16-safe reserved range to avoid collision with players (1+) and projectiles (10000+).
var _next_entity_id: int = GameConstants.MONSTER_ENTITY_ID_START

## Debug logging flag
var debug_logging: bool = true

## Recent per-tick monster positions used for player projectile lag compensation.
var _position_history: Dictionary = {}  # server_tick -> Array[MonsterPositionSnapshot]
var _position_history_ticks: Array[int] = []
const POSITION_HISTORY_TICKS := 8


## Spawn a new monster at the given position
## Returns the created MonsterState
func spawn_monster(position: Vector2) -> MonsterState:
	var entity_id := _allocate_entity_id()
	if entity_id < 0:
		push_warning("[MonsterManager] No available monster entity IDs")
		return null

	var state = MonsterState.create(entity_id, position, GameConstants.MONSTER_HEALTH)
	monsters[entity_id] = state

	if debug_logging:
		print("[MonsterManager] Monster spawned: entity=%d, pos=%s, health=%d" % [
			entity_id, position, state.health
		])

	return state


## Allocate the next free monster entity ID from the reserved range.
func _allocate_entity_id() -> int:
	var range_size := GameConstants.MONSTER_ENTITY_ID_END - GameConstants.MONSTER_ENTITY_ID_START + 1
	for i in range(range_size):
		var candidate := _next_entity_id
		_next_entity_id += 1
		if _next_entity_id > GameConstants.MONSTER_ENTITY_ID_END:
			_next_entity_id = GameConstants.MONSTER_ENTITY_ID_START

		if not monsters.has(candidate):
			return candidate

	return -1


## Remove a monster by entity_id
func remove_monster(entity_id: int) -> void:
	if not monsters.has(entity_id):
		return

	monsters.erase(entity_id)

	if debug_logging:
		print("[MonsterManager] Monster removed: entity=%d" % entity_id)


## Get a monster by entity_id
func get_monster(entity_id: int) -> MonsterState:
	return monsters.get(entity_id, null)


## Get current monster count
func get_monster_count() -> int:
	return monsters.size()


## Get current alive monster count
func get_alive_monster_count() -> int:
	var count := 0
	for state: MonsterState in monsters.values():
		if state.is_alive:
			count += 1
	return count


## Get all active monsters as an array
func get_all_monsters() -> Array[MonsterState]:
	var result: Array[MonsterState] = []
	for state in monsters.values():
		result.append(state)
	return result


## Get only alive monsters
func get_alive_monsters() -> Array[MonsterState]:
	var result: Array[MonsterState] = []
	for state: MonsterState in monsters.values():
		if state.is_alive:
			result.append(state)
	return result


## Record alive monster positions for this authoritative tick.
func record_position_snapshot(server_tick: int) -> void:
	var snapshot: Array[MonsterPositionSnapshot] = []
	for state: MonsterState in monsters.values():
		if state.is_alive:
			snapshot.append(MonsterPositionSnapshot.create(state.entity_id, state.position))

	_position_history[server_tick] = snapshot
	_position_history_ticks.append(server_tick)

	while _position_history_ticks.size() > POSITION_HISTORY_TICKS:
		var old_tick: int = _position_history_ticks.pop_front()
		_position_history.erase(old_tick)


## Get alive monster positions from a recent tick, falling back gracefully if the
## requested tick is outside the short history window.
func get_alive_monster_snapshot(server_tick: int) -> Array:
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

	return get_alive_monsters()


## Find the nearest currently-alive monster for spawn diagnostics.
func get_closest_alive_monster(position: Vector2) -> MonsterState:
	var closest: MonsterState = null
	var closest_dist_sq := INF

	for state: MonsterState in monsters.values():
		if not state.is_alive:
			continue

		var dist_sq := position.distance_squared_to(state.position)
		if dist_sq < closest_dist_sq:
			closest = state
			closest_dist_sq = dist_sq

	return closest


## Remove dead monsters from the manager after death updates/events have been sent.
func cleanup_dead_monsters() -> void:
	var to_remove: Array[int] = []
	for entity_id: int in monsters.keys():
		var state: MonsterState = monsters[entity_id]
		if not state.is_alive:
			to_remove.append(entity_id)

	for entity_id in to_remove:
		remove_monster(entity_id)


## Collect state updates for all active monsters.
## Dead monsters remain in the manager until end-of-tick cleanup so clients receive
## one final death animation/flag update before the explicit despawn delta.
## Returns array of entity data dictionaries for StateUpdatePacket
func collect_state_updates() -> Array[Dictionary]:
	var updates: Array[Dictionary] = []

	for state: MonsterState in monsters.values():
		updates.append(state.to_entity_data())

	return updates


## Clear all monsters (for shutdown or round reset)
func clear_all() -> void:
	monsters.clear()
	_position_history.clear()
	_position_history_ticks.clear()
	if debug_logging:
		print("[MonsterManager] All monsters cleared")
