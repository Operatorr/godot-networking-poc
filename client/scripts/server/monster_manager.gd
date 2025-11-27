## MonsterManager - Server-side monster management system
## Handles monster spawning, tracking, and cleanup
## Used by ServerMain for all monster-related operations
class_name MonsterManager
extends RefCounted

## All active monsters: entity_id -> MonsterState
var monsters: Dictionary = {}

## Entity ID counter for unique monster entity IDs
## Starting at 100000 to avoid collision with player (1+) and projectile (10000+) IDs
var _next_entity_id: int = 100000

## Debug logging flag
var debug_logging: bool = true


## Spawn a new monster at the given position
## Returns the created MonsterState
func spawn_monster(position: Vector2) -> MonsterState:
	var entity_id = _next_entity_id
	_next_entity_id += 1

	var state = MonsterState.create(entity_id, position, GameConstants.MONSTER_HEALTH)
	monsters[entity_id] = state

	if debug_logging:
		print("[MonsterManager] Monster spawned: entity=%d, pos=%s, health=%d" % [
			entity_id, position, state.health
		])

	return state


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
