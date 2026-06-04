## ProjectileState - Server-side projectile state container
## Holds authoritative state for a single projectile
## Created by ProjectileManager when a player shoots
class_name ProjectileState
extends RefCounted

## Unique entity ID for network sync
var entity_id: int = 0

## Entity ID of the player who fired this projectile
var owner_id: int = 0

## Current position in world space
var position: Vector2 = Vector2.ZERO

## Previous tick position in world space, used for swept collision checks
var previous_position: Vector2 = Vector2.ZERO

## Normalized direction vector
var direction: Vector2 = Vector2.RIGHT

## Movement speed (units per second)
var speed: float = GameConstants.PROJECTILE_SPEED

## Total distance traveled since spawn
var distance_traveled: float = 0.0

## Whether the projectile is still active
var alive: bool = true

## Server tick when the projectile was spawned
var spawn_tick: int = 0

## Number of server ticks this projectile has simulated
var simulation_ticks: int = 0

## How many ticks to rewind monster positions for player projectile hits
var collision_rewind_ticks: int = 0

## How many ticks to rewind player positions for PvP projectile hits.
## Capped stricter than the PvE rewind to limit "shoot around corners".
var pvp_collision_rewind_ticks: int = 0

## Client timing metadata used to derive collision_rewind_ticks
var client_render_tick: int = 0
var client_rtt_ms: int = 0
var lag_compensation_source: String = "none"

## Last non-hit reason that made the projectile inactive
var removal_reason: String = ""

## Closest lag-compensated monster approach observed while the projectile lived
var closest_distance_to_monster: float = INF
var closest_monster_id: int = -1
var closest_monster_position: Vector2 = Vector2.ZERO
var closest_projectile_position: Vector2 = Vector2.ZERO
var closest_monster_tick: int = -1


## Create a new ProjectileState
static func create(
	p_entity_id: int,
	p_owner_id: int,
	p_position: Vector2,
	p_direction: Vector2,
	p_spawn_tick: int = 0,
	p_collision_rewind_ticks: int = 0,
	p_client_render_tick: int = 0,
	p_client_rtt_ms: int = 0,
	p_lag_compensation_source: String = "none",
	p_pvp_collision_rewind_ticks: int = 0
) -> ProjectileState:
	var state = ProjectileState.new()
	state.entity_id = p_entity_id
	state.owner_id = p_owner_id
	state.position = p_position
	state.previous_position = p_position
	state.direction = p_direction.normalized()
	state.speed = GameConstants.PROJECTILE_SPEED
	state.distance_traveled = 0.0
	state.alive = true
	state.spawn_tick = p_spawn_tick
	state.simulation_ticks = 0
	state.collision_rewind_ticks = p_collision_rewind_ticks
	state.pvp_collision_rewind_ticks = p_pvp_collision_rewind_ticks
	state.client_render_tick = p_client_render_tick
	state.client_rtt_ms = p_client_rtt_ms
	state.lag_compensation_source = p_lag_compensation_source
	state.removal_reason = ""
	state.closest_distance_to_monster = INF
	state.closest_monster_id = -1
	state.closest_monster_position = Vector2.ZERO
	state.closest_projectile_position = p_position
	state.closest_monster_tick = -1
	return state


## Update projectile position based on delta time
## Returns true if projectile should be removed (expired or out of bounds)
func update(delta: float) -> bool:
	if not alive:
		if removal_reason.is_empty():
			removal_reason = "inactive"
		return true

	# Move projectile
	var old_position := position
	previous_position = old_position
	var movement := direction * speed * delta
	position += movement
	distance_traveled += movement.length()
	simulation_ticks += 1

	# Check max distance
	if distance_traveled >= GameConstants.PROJECTILE_MAX_DISTANCE:
		alive = false
		removal_reason = "max_distance"
		return true

	# Check map boundaries
	if not GameConstants.is_within_bounds(position):
		alive = false
		removal_reason = "out_of_bounds"
		return true

	# Check obstacle collision (line segment from old to new position)
	var hit_point := GameConstants.line_intersects_obstacle(old_position, position)
	if hit_point != Vector2.INF:
		position = hit_point
		alive = false
		removal_reason = "obstacle"
		return true

	return false


## Check if projectile has expired (exceeded max distance)
func is_expired() -> bool:
	return distance_traveled >= GameConstants.PROJECTILE_MAX_DISTANCE


## Check if projectile is out of map bounds
func is_out_of_bounds() -> bool:
	return not GameConstants.is_within_bounds(position)


## Monster collision snapshots advance with projectile age in the same delayed
## world the firing client rendered when the shot was aimed.
func get_lag_compensated_monster_tick() -> int:
	if collision_rewind_ticks <= 0:
		return spawn_tick + simulation_ticks
	return maxi(0, spawn_tick - collision_rewind_ticks + simulation_ticks)


## Player collision snapshots advance with projectile age in the same delayed
## world the firing client rendered when the shot was aimed. Uses the stricter
## PvP rewind cap so peekers who have broken line of sight are not retro-hit.
func get_lag_compensated_player_tick() -> int:
	if pvp_collision_rewind_ticks <= 0:
		return spawn_tick + simulation_ticks
	return maxi(0, spawn_tick - pvp_collision_rewind_ticks + simulation_ticks)


func is_player_projectile() -> bool:
	return owner_id < GameConstants.MONSTER_ENTITY_ID_START


## Convert to entity data dictionary for StateUpdatePacket
func to_entity_data() -> Dictionary:
	# Calculate animation state based on direction (for visual rotation on client)
	# Use the angle in degrees divided into 8 directions (0-7)
	var angle := direction.angle()
	var animation_state := int(fmod(angle + PI, TAU) / TAU * 8) % 8

	return {
		"id": entity_id,
		"type": PacketTypes.EntityType.PROJECTILE,
		"position": position,
		"animation": animation_state,
		"flags": PacketTypes.ENTITY_FLAG_VISIBLE if alive else 0
	}


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"entity_id": entity_id,
		"owner_id": owner_id,
		"position": position,
		"previous_position": previous_position,
		"direction": direction,
		"speed": speed,
		"distance_traveled": distance_traveled,
		"alive": alive,
		"spawn_tick": spawn_tick,
		"simulation_ticks": simulation_ticks,
		"collision_rewind_ticks": collision_rewind_ticks,
		"pvp_collision_rewind_ticks": pvp_collision_rewind_ticks,
		"client_render_tick": client_render_tick,
		"client_rtt_ms": client_rtt_ms,
		"lag_compensation_source": lag_compensation_source,
		"removal_reason": removal_reason,
		"closest_distance_to_monster": closest_distance_to_monster,
		"closest_monster_id": closest_monster_id,
		"closest_monster_position": closest_monster_position,
		"closest_projectile_position": closest_projectile_position,
		"closest_monster_tick": closest_monster_tick
	}
