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


## Check collisions between projectiles and players
## Returns array of hit events: { projectile_id, target_id, position }
func check_collisions_with_players(player_manager: PlayerManager) -> Array[Dictionary]:
	var hits: Array[Dictionary] = []
	var to_remove: Array[int] = []

	for entity_id: int in projectiles.keys():
		var proj: ProjectileState = projectiles[entity_id]

		if not proj.alive:
			continue

		# Check against all alive players
		for player: PlayerState in player_manager.get_alive_players():
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
	for entity_id in to_remove:
		remove_projectile(entity_id)

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
