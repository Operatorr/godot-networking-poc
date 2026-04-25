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

## Post-respawn invulnerability duration (seconds)
const INVULNERABILITY_DURATION := 3.0


# =============================================================================
# MONSTER CONSTANTS
# =============================================================================

## Monster spawn rate (monsters per second)
## 0.2 = 1 monster every 5 seconds
const MONSTER_SPAWN_RATE := 0.2

## Maximum active monsters in arena
const MONSTER_MAX_COUNT := 20

## Player visibility radius (spawn monsters outside this distance from players)
const MONSTER_VISIBILITY_RADIUS := 300.0

## Maximum attempts to find valid spawn position before using fallback
const MONSTER_SPAWN_ATTEMPTS := 10

## Default monster health
const MONSTER_HEALTH := 50

## Monster hitbox radius for collision
const MONSTER_HITBOX_RADIUS := 16.0


# =============================================================================
# MONSTER AI CONSTANTS
# =============================================================================

## Monster movement speed (60% of player speed)
const MONSTER_SPEED := 120.0

## Monster projectile speed (75% of player projectile speed)
const MONSTER_PROJECTILE_SPEED := 300.0

## Monster projectile damage
const MONSTER_PROJECTILE_DAMAGE := 10

## Player projectile damage to monsters
const PLAYER_PROJECTILE_DAMAGE := 25

## Attack range - distance at which monster will stop and shoot
const MONSTER_ATTACK_RANGE := 200.0

## Flee distance - monster flees if player closer than this
const MONSTER_FLEE_DISTANCE := 100.0

## Preferred distance for ranged monsters (maintain this distance when fleeing)
const MONSTER_PREFERRED_DISTANCE := 150.0

## Detection range - monster starts chasing if player within this range
const MONSTER_DETECTION_RANGE := 250.0

## Shoot cooldown for monsters (2.5x player cooldown)
const MONSTER_SHOOT_COOLDOWN := 0.75

## Attack duration - time spent in attack state before resuming movement
const MONSTER_ATTACK_DURATION := 0.5

## Obstacle avoidance lookahead distance
const MONSTER_AVOIDANCE_DISTANCE := 50.0

## Steering randomness factor (0.0-1.0)
const MONSTER_STEERING_RANDOMNESS := 0.15

## Time between target re-evaluation (seconds)
const MONSTER_RETARGET_INTERVAL := 1.0

## Lose interest distance - stop chasing if player beyond this
const MONSTER_LOSE_INTEREST_DISTANCE := 400.0


# =============================================================================
# ARENA OBSTACLES
# =============================================================================

## Obstacle definitions: Array of Rect2(position, size) in world coordinates
## Strategic placement creating cover, lanes, and choke points
static var ARENA_OBSTACLES: Array[Rect2] = [
	# Center cross - creates 4 approach lanes
	Rect2(Vector2(-20, -200), Vector2(40, 160)),     # Center north pillar
	Rect2(Vector2(-20, 40), Vector2(40, 160)),        # Center south pillar
	Rect2(Vector2(-200, -20), Vector2(160, 40)),      # Center west pillar
	Rect2(Vector2(40, -20), Vector2(160, 40)),        # Center east pillar

	# Corner cover walls
	Rect2(Vector2(-700, -700), Vector2(150, 30)),     # NW horizontal
	Rect2(Vector2(-700, -700), Vector2(30, 150)),     # NW vertical
	Rect2(Vector2(550, -700), Vector2(150, 30)),      # NE horizontal
	Rect2(Vector2(670, -700), Vector2(30, 150)),      # NE vertical
	Rect2(Vector2(-700, 670), Vector2(150, 30)),      # SW horizontal
	Rect2(Vector2(-700, 550), Vector2(30, 150)),      # SW vertical
	Rect2(Vector2(550, 670), Vector2(150, 30)),       # SE horizontal
	Rect2(Vector2(670, 550), Vector2(30, 150)),       # SE vertical

	# Mid-field barriers - break up sight lines
	Rect2(Vector2(-450, -350), Vector2(100, 25)),     # NW mid barrier
	Rect2(Vector2(350, -350), Vector2(100, 25)),      # NE mid barrier
	Rect2(Vector2(-450, 325), Vector2(100, 25)),      # SW mid barrier
	Rect2(Vector2(350, 325), Vector2(100, 25)),       # SE mid barrier
]


## Check if a point collides with any obstacle
static func is_point_in_obstacle(point: Vector2) -> bool:
	for obs in ARENA_OBSTACLES:
		if obs.has_point(point):
			return true
	return false


## Check if a circle collides with any obstacle
static func circle_intersects_obstacle(center: Vector2, radius: float) -> bool:
	for obs in ARENA_OBSTACLES:
		# Expand rect by radius and check point
		var expanded := Rect2(obs.position - Vector2(radius, radius), obs.size + Vector2(radius * 2, radius * 2))
		if expanded.has_point(center):
			return true
	return false


## Resolve movement against map bounds and arena obstacles.
## Attempts axis-separated sliding when direct movement would hit a wall.
static func move_with_obstacle_collision(from: Vector2, to: Vector2, radius: float) -> Vector2:
	var target := clamp_to_bounds(to)
	if not _movement_hits_obstacle(from, target, radius):
		return target

	var x_target := clamp_to_bounds(Vector2(target.x, from.y))
	var y_target := clamp_to_bounds(Vector2(from.x, target.y))
	var best_position := from
	var best_distance := from.distance_squared_to(target)

	if not _movement_hits_obstacle(from, x_target, radius):
		best_position = x_target
		best_distance = best_position.distance_squared_to(target)

	if not _movement_hits_obstacle(from, y_target, radius):
		var y_distance := y_target.distance_squared_to(target)
		if y_distance < best_distance:
			best_position = y_target

	return best_position


## Check if a swept circle movement crosses or ends inside an obstacle.
static func _movement_hits_obstacle(from: Vector2, to: Vector2, radius: float) -> bool:
	if from.is_equal_approx(to):
		return circle_intersects_obstacle(to, radius)

	for obs in ARENA_OBSTACLES:
		var expanded := Rect2(obs.position - Vector2(radius, radius), obs.size + Vector2(radius * 2, radius * 2))
		if expanded.has_point(to):
			return true
		if _line_rect_intersection(from, to, expanded) != Vector2.INF:
			return true

	return false


## Check if a line segment intersects any obstacle (for projectile collision)
## Returns the first intersection point or Vector2.INF if no intersection
static func line_intersects_obstacle(from: Vector2, to: Vector2) -> Vector2:
	var closest := Vector2.INF
	var closest_dist := INF

	for obs in ARENA_OBSTACLES:
		var intersection := _line_rect_intersection(from, to, obs)
		if intersection != Vector2.INF:
			var dist := from.distance_squared_to(intersection)
			if dist < closest_dist:
				closest = intersection
				closest_dist = dist

	return closest


## Line-rectangle intersection helper
static func _line_rect_intersection(from: Vector2, to: Vector2, rect: Rect2) -> Vector2:
	var dir := to - from
	var t_min := 0.0
	var t_max := 1.0

	# Check X axis
	if abs(dir.x) < 0.0001:
		if from.x < rect.position.x or from.x > rect.position.x + rect.size.x:
			return Vector2.INF
	else:
		var t1 := (rect.position.x - from.x) / dir.x
		var t2 := (rect.position.x + rect.size.x - from.x) / dir.x
		if t1 > t2:
			var tmp := t1
			t1 = t2
			t2 = tmp
		t_min = maxf(t_min, t1)
		t_max = minf(t_max, t2)
		if t_min > t_max:
			return Vector2.INF

	# Check Y axis
	if abs(dir.y) < 0.0001:
		if from.y < rect.position.y or from.y > rect.position.y + rect.size.y:
			return Vector2.INF
	else:
		var t1 := (rect.position.y - from.y) / dir.y
		var t2 := (rect.position.y + rect.size.y - from.y) / dir.y
		if t1 > t2:
			var tmp := t1
			t1 = t2
			t2 = tmp
		t_min = maxf(t_min, t1)
		t_max = minf(t_max, t2)
		if t_min > t_max:
			return Vector2.INF

	if t_min >= 0.0 and t_min <= 1.0:
		return from + dir * t_min
	return Vector2.INF
