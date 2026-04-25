## ProjectilePool - Object pool manager for projectiles
## Pre-allocates projectiles and recycles them for performance
class_name ProjectilePool
extends Node

## Maximum pooled projectiles per player
const POOL_SIZE: int = 16

## Path to projectile scene
const PROJECTILE_SCENE_PATH := "res://scenes/shared/projectile/projectile.tscn"

## All projectile instances
var pool: Array = []

## Currently active projectiles (FIFO order for recycling)
var active_projectiles: Array = []

## Preloaded projectile scene
var _projectile_scene: PackedScene = null


func _ready() -> void:
	_projectile_scene = load(PROJECTILE_SCENE_PATH)

	if _projectile_scene == null:
		push_error("ProjectilePool: Failed to load projectile scene at %s" % PROJECTILE_SCENE_PATH)
		return

	# Pre-allocate pool
	for i in POOL_SIZE:
		var projectile = _projectile_scene.instantiate()
		projectile.process_mode = Node.PROCESS_MODE_DISABLED
		projectile.visible = false
		projectile.monitoring = false
		projectile.monitorable = false
		add_child(projectile)
		pool.append(projectile)


## Spawn a projectile from the pool
## Recycles oldest if pool exhausted
## @param position: Spawn world position
## @param direction: Normalized direction vector
## @param max_distance: Maximum travel distance
## @return: The activated projectile
func spawn(pos: Vector2, dir: Vector2, max_dist: float):
	var projectile = null

	# Try to find inactive projectile
	for p in pool:
		if not p.visible:
			projectile = p
			break

	# Pool exhausted - recycle oldest
	if projectile == null and active_projectiles.size() > 0:
		projectile = active_projectiles.pop_front()
		projectile.deactivate()

	if projectile == null:
		push_warning("ProjectilePool: No available projectiles")
		return null

	# Activate and track
	projectile.activate(pos, dir, max_dist, self)
	active_projectiles.append(projectile)

	return projectile


## Return a projectile to the pool
## Called automatically by Projectile.deactivate()
## @param projectile: The projectile to return
func return_projectile(projectile) -> void:
	active_projectiles.erase(projectile)


## Get count of currently active projectiles
## @return: Number of active projectiles
func get_active_count() -> int:
	return active_projectiles.size()


## Deactivate all projectiles (e.g., on player death)
func deactivate_all() -> void:
	# Create a copy to avoid modification during iteration
	var to_deactivate := active_projectiles.duplicate()
	for projectile in to_deactivate:
		projectile.deactivate()
