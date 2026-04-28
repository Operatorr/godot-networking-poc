## ProjectileManager - Server-side projectile management system
## Handles projectile spawning, updates, collision detection, and cleanup
## Used by ServerMain for all projectile-related operations
class_name ProjectileManager
extends RefCounted

## All active projectiles: entity_id -> ProjectileState
var projectiles: Dictionary = {}

## Entity ID counter for unique projectile entity IDs
## Uses a u16-safe reserved range to avoid collision with player and monster IDs.
var _next_entity_id: int = GameConstants.PROJECTILE_ENTITY_ID_START

## Debug logging flag
var debug_logging: bool = true

## Spatial grid cell size for collision partitioning.
## Chosen so the max collision radius (~24 units) fits within one cell,
## meaning we only need to check the 3x3 neighbourhood.
const GRID_CELL_SIZE := 64.0


## Spawn a new projectile
## Returns the created ProjectileState or null if spawn failed
func spawn_projectile(
	owner_id: int,
	position: Vector2,
	direction: Vector2,
	spawn_tick: int = 0,
	collision_rewind_ticks: int = 0,
	client_render_tick: int = 0,
	client_rtt_ms: int = 0,
	lag_compensation_source: String = "none"
) -> ProjectileState:
	# Validate direction
	if direction.is_zero_approx():
		if debug_logging:
			print("[ProjectileManager] Cannot spawn projectile with zero direction")
		return null

	var entity_id := _allocate_entity_id()
	if entity_id < 0:
		push_warning("[ProjectileManager] No available projectile entity IDs")
		return null

	var state = ProjectileState.create(
		entity_id,
		owner_id,
		position,
		direction,
		spawn_tick,
		collision_rewind_ticks,
		client_render_tick,
		client_rtt_ms,
		lag_compensation_source
	)
	projectiles[entity_id] = state

	if debug_logging:
		print("[ProjectileManager] Projectile spawned: entity=%d, owner=%d, pos=%s, dir=%s, tick=%d, rewind_ticks=%d, compensation=%s, client_render_tick=%d, client_rtt_ms=%d" % [
			entity_id,
			owner_id,
			position,
			direction,
			spawn_tick,
			collision_rewind_ticks,
			lag_compensation_source,
			client_render_tick,
			client_rtt_ms
		])

	return state


## Allocate the next free projectile entity ID from the reserved range.
func _allocate_entity_id() -> int:
	var range_size := GameConstants.PROJECTILE_ENTITY_ID_END - GameConstants.PROJECTILE_ENTITY_ID_START + 1
	for i in range(range_size):
		var candidate := _next_entity_id
		_next_entity_id += 1
		if _next_entity_id > GameConstants.PROJECTILE_ENTITY_ID_END:
			_next_entity_id = GameConstants.PROJECTILE_ENTITY_ID_START

		if not projectiles.has(candidate):
			return candidate

	return -1


## Remove a projectile by entity_id
func remove_projectile(entity_id: int, reason: String = "") -> void:
	if not projectiles.has(entity_id):
		return

	var state: ProjectileState = projectiles[entity_id]
	if not reason.is_empty():
		state.removal_reason = reason
	elif state.removal_reason.is_empty():
		state.removal_reason = "removed"

	_log_projectile_removal(state)
	projectiles.erase(entity_id)


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
		var state: ProjectileState = projectiles.get(entity_id, null)
		var reason := state.removal_reason if state != null else "expired"
		remove_projectile(entity_id, reason)

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


func _closest_point_on_segment(point: Vector2, segment_start: Vector2, segment_end: Vector2) -> Vector2:
	var segment := segment_end - segment_start
	var length_sq := segment.length_squared()
	if length_sq <= 0.0001:
		return segment_start

	var t := clampf((point - segment_start).dot(segment) / length_sq, 0.0, 1.0)
	return segment_start + segment * t


func _distance_to_projectile_path(proj: ProjectileState, point: Vector2) -> float:
	return point.distance_to(_closest_point_on_segment(point, proj.previous_position, proj.position))


func _get_monster_list_for_tick(
	monster_manager: MonsterManager,
	collision_tick: int,
	monster_lists_by_tick: Dictionary
) -> Array:
	if not monster_lists_by_tick.has(collision_tick):
		monster_lists_by_tick[collision_tick] = monster_manager.get_alive_monster_snapshot(collision_tick)
	return monster_lists_by_tick[collision_tick]


func _get_monster_grid_for_tick(
	monster_manager: MonsterManager,
	collision_tick: int,
	monster_lists_by_tick: Dictionary,
	monster_grids_by_tick: Dictionary
) -> Dictionary:
	if not monster_grids_by_tick.has(collision_tick):
		var monsters := _get_monster_list_for_tick(monster_manager, collision_tick, monster_lists_by_tick)
		monster_grids_by_tick[collision_tick] = _build_entity_grid(monsters)
	return monster_grids_by_tick[collision_tick]


func _projectile_diagnostics_enabled() -> bool:
	return debug_logging


func _track_closest_monster(
	proj: ProjectileState,
	monsters: Array,
	collision_tick: int
) -> void:
	for monster in monsters:
		var closest_point: Vector2 = _closest_point_on_segment(monster.position, proj.previous_position, proj.position)
		var dist: float = monster.position.distance_to(closest_point)
		if dist < proj.closest_distance_to_monster:
			proj.closest_distance_to_monster = dist
			proj.closest_monster_id = monster.entity_id
			proj.closest_monster_position = monster.position
			proj.closest_projectile_position = closest_point
			proj.closest_monster_tick = collision_tick


func _log_projectile_removal(state: ProjectileState) -> void:
	if not _projectile_diagnostics_enabled():
		return

	if state.is_player_projectile() and not state.removal_reason.ends_with("_hit"):
		var closest_text := "none"
		if state.closest_monster_id >= 0:
			closest_text = "monster=%d dist=%.2f monster_pos=%s projectile_pos=%s snapshot_tick=%d" % [
				state.closest_monster_id,
				state.closest_distance_to_monster,
				state.closest_monster_position,
				state.closest_projectile_position,
				state.closest_monster_tick
			]

		print("[ProjectileManager] Player projectile removed without hit: entity=%d owner=%d reason=%s pos=%s distance=%.1f rewind_ticks=%d compensation=%s client_render_tick=%d client_rtt_ms=%d closest=%s" % [
			state.entity_id,
			state.owner_id,
			state.removal_reason,
			state.position,
			state.distance_traveled,
			state.collision_rewind_ticks,
			state.lag_compensation_source,
			state.client_render_tick,
			state.client_rtt_ms,
			closest_text
		])
		return

	print("[ProjectileManager] Projectile removed: entity=%d reason=%s" % [
		state.entity_id,
		state.removal_reason
	])


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
				proj.removal_reason = "player_hit"
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
		remove_projectile(eid, "player_hit")

	return hits


## Check collisions between projectiles and monsters using spatial grid.
## Only player projectiles can hit monsters.
## Returns array of hit events: { projectile_id, target_id, owner_id, position }
func check_collisions_with_monsters(monster_manager: MonsterManager) -> Array[Dictionary]:
	var hits: Array[Dictionary] = []
	var to_remove: Array[int] = []
	var monster_lists_by_tick: Dictionary = {}
	var monster_grids_by_tick: Dictionary = {}

	for entity_id: int in projectiles.keys():
		var proj: ProjectileState = projectiles[entity_id]

		if not proj.alive:
			continue

		# Only player projectiles can hit monsters.
		if proj.owner_id >= GameConstants.MONSTER_ENTITY_ID_START:
			continue

		var collision_tick := proj.get_lag_compensated_monster_tick()
		if _projectile_diagnostics_enabled():
			var collision_monsters := _get_monster_list_for_tick(monster_manager, collision_tick, monster_lists_by_tick)
			_track_closest_monster(proj, collision_monsters, collision_tick)

		# Only check monsters in nearby cells
		var monster_grid := _get_monster_grid_for_tick(
			monster_manager,
			collision_tick,
			monster_lists_by_tick,
			monster_grids_by_tick
		)
		var nearby_monsters: Array = _query_nearby(monster_grid, proj.position)

		for monster in nearby_monsters:
			# Check swept projectile path against the lag-compensated monster position.
			var hit_position: Vector2 = _closest_point_on_segment(monster.position, proj.previous_position, proj.position)
			var dist: float = monster.position.distance_to(hit_position)
			var collision_dist := GameConstants.PROJECTILE_RADIUS + GameConstants.MONSTER_HITBOX_RADIUS

			if dist < collision_dist:
				# Hit detected
				proj.alive = false
				proj.removal_reason = "monster_hit"
				to_remove.append(entity_id)

				hits.append({
					"projectile_id": entity_id,
					"target_id": monster.entity_id,
					"owner_id": proj.owner_id,
					"position": hit_position
				})

				if debug_logging:
					var current_monster := monster_manager.get_monster(monster.entity_id)
					var current_pos := current_monster.position if current_monster != null else Vector2.INF
					print("[ProjectileManager] Lag-compensated hit: projectile=%d hit monster=%d at %s dist=%.2f snapshot_tick=%d snapshot_pos=%s current_pos=%s" % [
						entity_id, monster.entity_id, hit_position, dist, collision_tick, monster.position, current_pos
					])

				# Only hit one target per projectile
				break

	# Remove projectiles that hit something
	for eid in to_remove:
		remove_projectile(eid, "monster_hit")

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
