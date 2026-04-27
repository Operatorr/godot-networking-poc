## ProjectileManager - Server-side projectile management system
## Handles projectile spawning, updates, collision detection, and cleanup
## Used by ServerMain for all projectile-related operations
class_name ProjectileManager
extends RefCounted

## All active projectiles: entity_id -> ProjectileState
var projectiles: Dictionary = {}

## Entity ID counter for unique projectile entity IDs
## Starting at 10000 to avoid collision with player entity IDs
var _next_entity_id: int = 10000

## Debug logging flag
var debug_logging: bool = true

## Spatial grid cell size for collision partitioning.
## Chosen so the max collision radius (~24 units) fits within one cell,
## meaning we only need to check the 3x3 neighbourhood.
const GRID_CELL_SIZE := 64.0


## Spawn a new projectile
## Returns the created ProjectileState or null if spawn failed
func spawn_projectile(owner_id: int, position: Vector2, direction: Vector2) -> ProjectileState:
	# Validate direction
	if direction.is_zero_approx():
		if debug_logging:
			print("[ProjectileManager] Cannot spawn projectile with zero direction")
		return null

	var entity_id = _next_entity_id
	_next_entity_id += 1

	var state = ProjectileState.create(entity_id, owner_id, position, direction)
	projectiles[entity_id] = state

	if debug_logging:
		print("[ProjectileManager] Projectile spawned: entity=%d, owner=%d, pos=%s, dir=%s" % [
			entity_id, owner_id, position, direction
		])

	return state


## Remove a projectile by entity_id
func remove_projectile(entity_id: int) -> void:
	if not projectiles.has(entity_id):
		return

	projectiles.erase(entity_id)

	if debug_logging:
		print("[ProjectileManager] Projectile removed: entity=%d" % entity_id)


## Update all projectiles and return IDs of projectiles that should be removed
func update_all(delta: float) -> Array[int]:
	var to_remove: Array[int] = []

	for entity_id: int in projectiles.keys():
		var state: ProjectileState = projectiles[entity_id]
		var should_remove := state.update(delta)

		if should_remove:
			to_remove.append(entity_id)

	# Remove expired/out-of-bounds projectiles
	for entity_id in to_remove:
		remove_projectile(entity_id)

	return to_remove


## Build a spatial hash grid from an array of entities that have a .position field.
## Returns Dictionary[Vector2i, Array] mapping grid cells to entities.
func _build_entity_grid(entities: Array) -> Dictionary:
	var grid: Dictionary = {}
	for entity in entities:
		var cell := Vector2i(
			floori(entity.position.x / GRID_CELL_SIZE),
			floori(entity.position.y / GRID_CELL_SIZE)
		)
		if not grid.has(cell):
			grid[cell] = []
		grid[cell].append(entity)
	return grid


## Query entities in the same or adjacent cells (3x3 neighbourhood).
func _query_nearby(grid: Dictionary, pos: Vector2) -> Array:
	var result: Array = []
	var cx := floori(pos.x / GRID_CELL_SIZE)
	var cy := floori(pos.y / GRID_CELL_SIZE)
	for dx in range(-1, 2):
		for dy in range(-1, 2):
			var cell := Vector2i(cx + dx, cy + dy)
			if grid.has(cell):
				result.append_array(grid[cell])
	return result


## Check collisions between projectiles and players using spatial grid.
## Returns array of hit events: { projectile_id, target_id, owner_id, position }
func check_collisions_with_players(player_manager: PlayerManager) -> Array[Dictionary]:
	var hits: Array[Dictionary] = []
	var to_remove: Array[int] = []

	# Build spatial grid from alive players
	var alive_players := player_manager.get_alive_players()
	var player_grid := _build_entity_grid(alive_players)

	for entity_id: int in projectiles.keys():
		var proj: ProjectileState = projectiles[entity_id]

		if not proj.alive:
			continue

		# Only check players in nearby cells
		var nearby_players: Array = _query_nearby(player_grid, proj.position)

		for player in nearby_players:
			# Don't hit the owner
			if proj.owner_id == player.entity_id:
				continue

			# Check distance for collision
			var dist := proj.position.distance_to(player.position)
			var collision_dist := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS

			if dist < collision_dist:
				# Hit detected
				proj.alive = false
				to_remove.append(entity_id)

				hits.append({
					"projectile_id": entity_id,
					"target_id": player.entity_id,
					"owner_id": proj.owner_id,
					"position": proj.position
				})

				if debug_logging:
					print("[ProjectileManager] Hit: projectile=%d hit player=%d at %s" % [
						entity_id, player.entity_id, proj.position
					])

				# Only hit one target per projectile
				break

	# Remove projectiles that hit something
	for eid in to_remove:
		remove_projectile(eid)

	return hits


## Check collisions between projectiles and monsters using spatial grid.
## Only player projectiles can hit monsters.
## Returns array of hit events: { projectile_id, target_id, owner_id, position }
func check_collisions_with_monsters(monster_manager: MonsterManager) -> Array[Dictionary]:
	var hits: Array[Dictionary] = []
	var to_remove: Array[int] = []

	# Build spatial grid from alive monsters
	var alive_monsters := monster_manager.get_alive_monsters()
	var monster_grid := _build_entity_grid(alive_monsters)

	for entity_id: int in projectiles.keys():
		var proj: ProjectileState = projectiles[entity_id]

		if not proj.alive:
			continue

		# Only player projectiles can hit monsters.
		if proj.owner_id >= GameConstants.MONSTER_ENTITY_ID_START:
			continue

		# Only check monsters in nearby cells
		var nearby_monsters: Array = _query_nearby(monster_grid, proj.position)

		for monster in nearby_monsters:
			# Check distance for collision
			var dist := proj.position.distance_to(monster.position)
			var collision_dist := GameConstants.PROJECTILE_RADIUS + GameConstants.MONSTER_HITBOX_RADIUS

			if dist < collision_dist:
				# Hit detected
				proj.alive = false
				to_remove.append(entity_id)

				hits.append({
					"projectile_id": entity_id,
					"target_id": monster.entity_id,
					"owner_id": proj.owner_id,
					"position": proj.position
				})

				if debug_logging:
					print("[ProjectileManager] Hit: projectile=%d hit monster=%d at %s" % [
						entity_id, monster.entity_id, proj.position
					])

				# Only hit one target per projectile
				break

	# Remove projectiles that hit something
	for eid in to_remove:
		remove_projectile(eid)

	return hits


## Collect state updates for all active projectiles
## Returns array of entity data dictionaries for StateUpdatePacket
func collect_state_updates() -> Array[Dictionary]:
	var updates: Array[Dictionary] = []

	for state: ProjectileState in projectiles.values():
		if state.alive:
			updates.append(state.to_entity_data())

	return updates


## Get a projectile by entity_id
func get_projectile(entity_id: int) -> ProjectileState:
	return projectiles.get(entity_id, null)


## Get current projectile count
func get_projectile_count() -> int:
	return projectiles.size()


## Get all active projectiles as an array
func get_all_projectiles() -> Array[ProjectileState]:
	var result: Array[ProjectileState] = []
	for state in projectiles.values():
		result.append(state)
	return result


## Clear all projectiles (for shutdown or round reset)
func clear_all() -> void:
	projectiles.clear()
	if debug_logging:
		print("[ProjectileManager] All projectiles cleared")
