## MonsterManager - Server-side monster management system
## Handles monster spawning, tracking, and cleanup
## Used by ServerMain for all monster-related operations
class_name MonsterManager
extends RefCounted

## All active monsters: entity_id -> MonsterState
var monsters: Dictionary = {}

## Entity ID counter for unique monster entity IDs
## Uses a u16-safe reserved range to avoid collision with players (1+) and projectiles (10000+).
var _next_entity_id: int = GameConstants.MONSTER_ENTITY_ID_START

## Debug logging flag
var debug_logging: bool = true


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


## Remove dead monsters from the manager after death updates/events have been sent.
func cleanup_dead_monsters() -> void:
	var to_remove: Array[int] = []
	for entity_id: int in monsters.keys():
		var state: MonsterState = monsters[entity_id]
		if not state.is_alive:
			to_remove.append(entity_id)

	for entity_id in to_remove:
		remove_monster(entity_id)


## Collect state updates for all active monsters
## Returns array of entity data dictionaries for StateUpdatePacket
func collect_state_updates() -> Array[Dictionary]:
	var updates: Array[Dictionary] = []

	for state: MonsterState in monsters.values():
		if state.is_alive:
			updates.append(state.to_entity_data())

	return updates


## Clear all monsters (for shutdown or round reset)
func clear_all() -> void:
	monsters.clear()
	if debug_logging:
		print("[MonsterManager] All monsters cleared")
