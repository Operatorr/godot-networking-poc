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

## Normalized direction vector
var direction: Vector2 = Vector2.RIGHT

## Movement speed (units per second)
var speed: float = GameConstants.PROJECTILE_SPEED

## Total distance traveled since spawn
var distance_traveled: float = 0.0

## Whether the projectile is still active
var alive: bool = true


## Create a new ProjectileState
static func create(p_entity_id: int, p_owner_id: int, p_position: Vector2, p_direction: Vector2) -> ProjectileState:
	var state = ProjectileState.new()
	state.entity_id = p_entity_id
	state.owner_id = p_owner_id
	state.position = p_position
	state.direction = p_direction.normalized()
	state.speed = GameConstants.PROJECTILE_SPEED
	state.distance_traveled = 0.0
	state.alive = true
	return state


## Update projectile position based on delta time
## Returns true if projectile should be removed (expired or out of bounds)
func update(delta: float) -> bool:
	if not alive:
		return true

	# Move projectile
	var movement := direction * speed * delta
	position += movement
	distance_traveled += movement.length()

	# Check max distance
	if distance_traveled >= GameConstants.PROJECTILE_MAX_DISTANCE:
		alive = false
		return true

	# Check map boundaries
	if not GameConstants.is_within_bounds(position):
		alive = false
		return true

	return false


## Check if projectile has expired (exceeded max distance)
func is_expired() -> bool:
	return distance_traveled >= GameConstants.PROJECTILE_MAX_DISTANCE


## Check if projectile is out of map bounds
func is_out_of_bounds() -> bool:
	return not GameConstants.is_within_bounds(position)


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
		"direction": direction,
		"speed": speed,
		"distance_traveled": distance_traveled,
		"alive": alive
	}
