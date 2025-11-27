## GameConstants - Shared game configuration values
## Used by both client and server to ensure consistent physics
class_name GameConstants
extends RefCounted


# =============================================================================
# MOVEMENT SPEEDS
# =============================================================================

## Base movement speed (units per second)
const PLAYER_SPEED := 200.0

## Sprint speed multiplier (sprint = base * multiplier)
const PLAYER_SPRINT_MULTIPLIER := 1.6

## Calculated sprint speed for reference: 320 units/sec
const PLAYER_SPRINT_SPEED := PLAYER_SPEED * PLAYER_SPRINT_MULTIPLIER


# =============================================================================
# MOVEMENT VALIDATION THRESHOLDS
# =============================================================================

## Position tolerance - soft threshold for acceptable deviation (units)
## Allows ~230ms latency at max sprint speed (320 * 0.23 = 74)
const POSITION_TOLERANCE := 75.0

## Correction threshold - only send correction packets above this (units)
## Set to 1.5x tolerance to reduce network traffic
const CORRECTION_THRESHOLD := 112.5

## Teleport threshold - distance considered impossible/cheating (units)
## Movements above this are flagged as potential cheat attempts
const TELEPORT_THRESHOLD := 150.0


# =============================================================================
# MAP BOUNDARIES
# =============================================================================

## Minimum map coordinates
const MAP_MIN := Vector2(-1000.0, -1000.0)

## Maximum map coordinates
const MAP_MAX := Vector2(1000.0, 1000.0)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

## Clamp a position to map boundaries
static func clamp_to_bounds(pos: Vector2) -> Vector2:
	return Vector2(
		clampf(pos.x, MAP_MIN.x, MAP_MAX.x),
		clampf(pos.y, MAP_MIN.y, MAP_MAX.y)
	)


## Check if a position is within map boundaries
static func is_within_bounds(pos: Vector2) -> bool:
	return pos.x >= MAP_MIN.x and pos.x <= MAP_MAX.x \
		and pos.y >= MAP_MIN.y and pos.y <= MAP_MAX.y


## Get movement speed based on whether sprinting
static func get_movement_speed(is_sprinting: bool) -> float:
	if is_sprinting:
		return PLAYER_SPRINT_SPEED
	return PLAYER_SPEED


# =============================================================================
# PROJECTILE CONSTANTS
# =============================================================================

## Projectile movement speed (units per second)
const PROJECTILE_SPEED := 400.0

## Maximum travel distance before projectile despawns (units)
const PROJECTILE_MAX_DISTANCE := 800.0

## Projectile collision radius (units)
const PROJECTILE_RADIUS := 8.0

## Player hitbox radius for projectile collision (units)
const PLAYER_HITBOX_RADIUS := 16.0


# =============================================================================
# COMBAT CONSTANTS
# =============================================================================

## Cooldown between shots (seconds)
const SHOOT_COOLDOWN := 0.3
