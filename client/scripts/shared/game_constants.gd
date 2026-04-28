## GameConstants - Shared game configuration values
## Used by both client and server to ensure consistent physics
class_name GameConstants
extends RefCounted


# =============================================================================
# NETWORK SIMULATION
# =============================================================================

## Authoritative server simulation rate.
const SERVER_TICK_RATE := 30.0

## Authoritative server simulation interval in seconds.
const SERVER_TICK_INTERVAL := 1.0 / SERVER_TICK_RATE

## Remote entities are rendered this many authoritative ticks behind the newest
## snapshot. Server-side lag compensation rewinds monsters by the same amount
## for player projectile collision checks.
const REMOTE_ENTITY_RENDER_DELAY_TICKS := 2

## PvE-only projectile lag compensation cap. PvP should use a lower cap and
## stricter validation when player-vs-player projectile compensation is added.
const MAX_PVE_PROJECTILE_COMPENSATION_TICKS := 6


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
# ARENA LAYOUT
# =============================================================================

## Arena tile dimensions. 40x40 over the existing 2000-unit map gives 50-unit tiles.
const ARENA_TILE_COLUMNS := 40
const ARENA_TILE_ROWS := 40
const ARENA_TILE_SIZE := 50.0
const ARENA_TILE_SOURCE_ID := 0

## Atlas coordinates used by the generated arena TileSet.
const ARENA_FLOOR_TILE := Vector2i(0, 0)
const ARENA_BORDER_TILE := Vector2i(1, 0)
const ARENA_OBSTACLE_TILE := Vector2i(2, 0)

## Shared arena player spawn positions in world coordinates.
static var ARENA_PLAYER_SPAWNS: Array[Vector2] = [
	Vector2(-800.0, -800.0),
	Vector2(0.0, -800.0),
	Vector2(800.0, -800.0),
	Vector2(-800.0, 0.0),
	Vector2(800.0, 0.0),
	Vector2(-800.0, 800.0),
	Vector2(0.0, 800.0),
	Vector2(800.0, 800.0),
	Vector2(-450.0, 450.0),
	Vector2(450.0, -450.0),
]

## Shared preferred monster spawn anchors in world coordinates.
static var ARENA_MONSTER_SPAWNS: Array[Vector2] = [
	Vector2(-450.0, -800.0),
	Vector2(450.0, -800.0),
	Vector2(-900.0, -450.0),
	Vector2(900.0, -450.0),
	Vector2(-900.0, 450.0),
	Vector2(900.0, 450.0),
	Vector2(-450.0, 800.0),
	Vector2(450.0, 800.0),
	Vector2(0.0, -500.0),
	Vector2(0.0, 500.0),
	Vector2(-500.0, 0.0),
	Vector2(500.0, 0.0),
]


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


## Check if a circle is fully within map boundaries
static func is_circle_within_bounds(pos: Vector2, radius: float) -> bool:
	return pos.x - radius >= MAP_MIN.x and pos.x + radius <= MAP_MAX.x \
		and pos.y - radius >= MAP_MIN.y and pos.y + radius <= MAP_MAX.y


## Get movement speed based on whether sprinting
static func get_movement_speed(is_sprinting: bool) -> float:
	if is_sprinting:
		return PLAYER_SPRINT_SPEED
	return PLAYER_SPEED


## Get a world-space rectangle for an arena tile.
static func get_arena_tile_rect(tile_coords: Vector2i) -> Rect2:
	return Rect2(
		MAP_MIN + Vector2(float(tile_coords.x), float(tile_coords.y)) * ARENA_TILE_SIZE,
		Vector2(ARENA_TILE_SIZE, ARENA_TILE_SIZE)
	)


## Check if the tile is on the arena border.
static func is_arena_border_tile(tile_coords: Vector2i) -> bool:
	return tile_coords.x == 0 \
		or tile_coords.y == 0 \
		or tile_coords.x == ARENA_TILE_COLUMNS - 1 \
		or tile_coords.y == ARENA_TILE_ROWS - 1


## Check if an arena tile overlaps any obstacle rectangle.
static func is_arena_obstacle_tile(tile_coords: Vector2i) -> bool:
	var tile_rect := get_arena_tile_rect(tile_coords)
	for obs in ARENA_OBSTACLES:
		if tile_rect.intersects(obs, true):
			return true
	return false


## Get the atlas tile for a world-layout cell.
static func get_arena_tile_type(tile_coords: Vector2i) -> Vector2i:
	if is_arena_border_tile(tile_coords):
		return ARENA_BORDER_TILE
	if is_arena_obstacle_tile(tile_coords):
		return ARENA_OBSTACLE_TILE
	return ARENA_FLOOR_TILE


## Check if a player spawn position is usable.
static func is_valid_player_spawn_position(pos: Vector2) -> bool:
	return is_circle_within_bounds(pos, PLAYER_HITBOX_RADIUS) \
		and not circle_intersects_obstacle(pos, PLAYER_HITBOX_RADIUS)


## Check if a monster spawn position is usable before player visibility checks.
static func is_valid_monster_spawn_position(pos: Vector2) -> bool:
	return is_circle_within_bounds(pos, MONSTER_HITBOX_RADIUS) \
		and not circle_intersects_obstacle(pos, MONSTER_HITBOX_RADIUS)


## Get shared player spawns, filtering invalid positions as a guardrail.
static func get_valid_player_spawns() -> Array[Vector2]:
	var result: Array[Vector2] = []
	for pos in ARENA_PLAYER_SPAWNS:
		if is_valid_player_spawn_position(pos):
			result.append(pos)
	return result


## Get shared monster spawn anchors, filtering invalid positions as a guardrail.
static func get_valid_monster_spawns() -> Array[Vector2]:
	var result: Array[Vector2] = []
	for pos in ARENA_MONSTER_SPAWNS:
		if is_valid_monster_spawn_position(pos):
			result.append(pos)
	return result


# =============================================================================
# PROJECTILE CONSTANTS
# =============================================================================

## Projectile movement speed (units per second)
const PROJECTILE_SPEED := 400.0

## Maximum travel distance before projectile despawns (units)
const PROJECTILE_MAX_DISTANCE := 800.0

## Projectile collision radius (units)
const PROJECTILE_RADIUS := 8.0

## Entity ID range reserved for projectiles.
## IDs must stay below the monster range because network entity IDs are u16.
const PROJECTILE_ENTITY_ID_START := 10000
const PROJECTILE_ENTITY_ID_END := 29999

## Player hitbox radius for projectile collision (units)
const PLAYER_HITBOX_RADIUS := 16.0


# =============================================================================
# COMBAT CONSTANTS
# =============================================================================

## Cooldown between shots (seconds)
const SHOOT_COOLDOWN := 0.3

## Delay before a dead player may manually request respawn (seconds)
const RESPAWN_DELAY := 3.0

## Post-respawn invulnerability duration (seconds)
const INVULNERABILITY_DURATION := 3.0


# =============================================================================
# MONSTER CONSTANTS
# =============================================================================

## Monster spawn rate (monsters per second)
## 0.2 = 1 monster every 5 seconds
const MONSTER_SPAWN_RATE := 0.2

## Maximum active monsters in arena
const MONSTER_MAX_COUNT := 100

## Entity ID range reserved for monsters.
## IDs must stay within u16 because the binary network protocol writes entity IDs as 16-bit values.
const MONSTER_ENTITY_ID_START := 30000
const MONSTER_ENTITY_ID_END := 39999

## Player visibility radius (spawn monsters outside this distance from players)
const MONSTER_VISIBILITY_RADIUS := 300.0

## Spawn monsters inside this band around players so they are outside direct visibility
## but still inside AoI/detection and will join the fight.
const MONSTER_SPAWN_MIN_DISTANCE := 320.0
const MONSTER_SPAWN_MAX_DISTANCE := 450.0

## Fraction of the monster budget reserved for regional map population.
## The remainder is used for encounter pressure around players.
const MONSTER_REGIONAL_SPAWN_RATIO := 0.6

## Spawn director grid dimensions for regional population.
const MONSTER_SPAWN_REGION_COLUMNS := 4
const MONSTER_SPAWN_REGION_ROWS := 4

## Soft per-region cap used by the regional population layer.
const MONSTER_SPAWN_REGION_SOFT_CAP := 2

## Candidate samples to test inside each selected region.
const MONSTER_SPAWN_REGION_CANDIDATES := 8

## Maximum attempts to find valid spawn position before using fallback
const MONSTER_SPAWN_ATTEMPTS := 20

## Default monster health
const MONSTER_HEALTH := 50

## Monster hitbox radius for collision
const MONSTER_HITBOX_RADIUS := 16.0

## Minimum center-to-center spacing for new monster spawns.
## Slightly larger than pure hitbox contact to avoid visually stacked spawns.
const MONSTER_SPAWN_SEPARATION := MONSTER_HITBOX_RADIUS * 2.25


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
## Must be greater than spawn visibility radius, otherwise freshly spawned
## monsters can remain idle just outside the player's view.
const MONSTER_DETECTION_RANGE := 650.0

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
const MONSTER_LOSE_INTEREST_DISTANCE := 900.0


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
