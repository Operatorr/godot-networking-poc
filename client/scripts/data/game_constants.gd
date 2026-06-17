## GameConstants - Shared game configuration values
## Used by both client and server to ensure consistent physics
class_name GameConstants
extends RefCounted


# =============================================================================
# NETWORK SIMULATION
# =============================================================================

## Authoritative server simulation rate. THE single client-side authority for
## input/prediction/interpolation cadence. game_manager.gd applies this to
## Engine.physics_ticks_per_second at startup so the client _physics_process
## clock follows it (project.godot physics_ticks_per_second is only a fallback).
##
## To run an HONEST 30-vs-60 Hz trial you must move BOTH knobs together:
##   1. set this constant to 60.0 (drives the client clock + INPUT_SEND_INTERVAL)
##   2. set server_config.json tick_rate to 60 (drives the server sim; JSON wins
##      at runtime over server_config.gd's GameConstants-derived default)
## and optionally server_config.json snapshot_rate_hz (0 = follow tick = 60).
## Revert = set all back to 30. See docs/netcode/perf-notes/tick-rate-30-vs-60.md.
const SERVER_TICK_RATE := 30.0

## Authoritative server simulation interval in seconds.
const SERVER_TICK_INTERVAL := 1.0 / SERVER_TICK_RATE

## Remote entities are rendered this many authoritative ticks behind the newest
## snapshot. Server-side lag compensation rewinds monsters by the same amount
## for player projectile collision checks.
## TICK-DERIVED: wall-clock meaning halves at 60 Hz (66.7 ms @30 -> 33.3 ms @60).
## Adaptive (interp seeds from SERVER_TICK_INTERVAL) so this is mostly fine, but
## the remote-smoothness margin shrinks at 60 Hz. See perf-notes/tick-rate-30-vs-60.md.
const REMOTE_ENTITY_RENDER_DELAY_TICKS := 2

## PvE-only projectile lag compensation cap. PvP should use a lower cap and
## stricter validation when player-vs-player projectile compensation is added.
## TICK-DERIVED: server_main computes max_compensation_seconds = TICKS / tick_rate,
## so the rewind window auto-scales from 200 ms @30 to 100 ms @60 (tighter — PvE
## hits get slightly harder to land at 60 Hz). See perf-notes/tick-rate-30-vs-60.md.
const MAX_PVE_PROJECTILE_COMPENSATION_TICKS := 6

## PvP-only cap — stricter than PvE so you cannot "shoot around corners" a peeker
## who has already broken line of sight. ~133 ms at 30 Hz.
## TICK-DERIVED: like the PvE cap, auto-scales to ~66.7 ms at 60 Hz.
const MAX_PVP_PROJECTILE_COMPENSATION_TICKS := 4


# =============================================================================
# MOVEMENT SPEEDS
# =============================================================================

## Base movement speed (units per second)
const PLAYER_SPEED := 200.0

## Sprint speed multiplier (sprint = base * multiplier)
const PLAYER_SPRINT_MULTIPLIER := 1.6

## Calculated sprint speed for reference: 320 units/sec
const PLAYER_SPRINT_SPEED := PLAYER_SPEED * PLAYER_SPRINT_MULTIPLIER

## How strongly the player-chosen color tints class spritesheets (0 = class art
## untouched, 1 = full modulate). The swatch keeps class identity while letting
## players slightly recolor their character. White picks no tint. Kept subtle.
const CLASS_SPRITE_TINT_STRENGTH := 0.25


# =============================================================================
# DASH
# =============================================================================
# Server-authoritative burst movement triggered instantly on the dash input.
# Both client (predicted) and server drive the shared MovementStateMachine with
# these values, so they MUST stay identical on both sides.

## Dash speed = base * this multiplier (3.6x => 720 u/s).
const PLAYER_DASH_MULTIPLIER := 3.6

## Calculated dash speed for reference: 720 units/sec.
const PLAYER_DASH_SPEED := PLAYER_SPEED * PLAYER_DASH_MULTIPLIER

## How long a single dash lasts (seconds).
const PLAYER_DASH_DURATION := 0.4

## Cooldown before the next dash is allowed (seconds). START-relative: the clock
## begins when the dash begins, so the usable gap is COOLDOWN - DURATION (~5.1 s).
const PLAYER_DASH_COOLDOWN := 5.5


# =============================================================================
# KNOCKBACK
# =============================================================================

## Exponential decay rate for knockback velocity (higher = snappier recovery).
## velocity *= exp(-rate * delta) each tick; ~9.0 settles in roughly half a second.
const PLAYER_KNOCKBACK_DECAY := 9.0

## Below this speed (u/s) knockback is considered finished and the SM exits to IDLE.
const PLAYER_KNOCKBACK_END_SPEED := 12.0

## Default knockback magnitude applied as direction * force * multiplier when a
## caller does not specify its own force.
const PLAYER_KNOCKBACK_BASE_FORCE := 450.0

## Per-projectile knockback impulse (u/s), carried on each projectile spawn so
## future weapons/abilities/items can vary it. The apply_knockback multiplier is
## the buff/debuff hook on top. Mirrors rust/sim_core/src/constants.rs.
const PLAYER_PROJECTILE_KNOCKBACK_FORCE := PLAYER_KNOCKBACK_BASE_FORCE
const MONSTER_PROJECTILE_KNOCKBACK_FORCE := PLAYER_KNOCKBACK_BASE_FORCE


# =============================================================================
# DAZE
# =============================================================================

## Hit while SPRINTING (or caught in a Mageblast) => dazed for this long: sprint and
## dash are locked out and walk speed is cut to PLAYER_DAZE_SPEED_MULTIPLIER; walking
## stays allowed (reduced control, not a stun). Server-authoritative; replicated via
## ENTITY_FLAG_DAZED. Mirrors rust/sim_core/src/constants.rs.
const PLAYER_DAZE_DURATION := 1.5

## Ground-speed multiplier while dazed — a 30% slow, the CC component of the daze.
const PLAYER_DAZE_SPEED_MULTIPLIER := 0.7

## Level cap. Mirrors MAX_PLAYER_LEVEL in rust/sim_core/src/progression.rs; used to clamp client-side
## class+level stat derivations (e.g. the HUD HP-bar cap) so they can't exceed the server's max.
const MAX_PLAYER_LEVEL := 50


# =============================================================================
# STAMINA (sprint resource)
# =============================================================================

## Maximum stamina pool.
const PLAYER_STAMINA_MAX := 100.0

## Stamina drained per second while SPRINTING.
const PLAYER_STAMINA_DRAIN_PER_SEC := 35.0

## Stamina regenerated per second while NOT sprinting.
const PLAYER_STAMINA_REGEN_PER_SEC := 20.0

## Legacy minimum-to-sprint threshold. No longer the sprint gate: the exhaustion model
## lets stamina deplete fully instead (sprint allowed while stamina > 0 and not exhausted —
## see movement_state_machine.gd want_sprint). Unused in GDScript; retained only to mirror
## rust/sim_core constants.rs PLAYER_STAMINA_SPRINT_MIN, which is likewise kept for reference.
const PLAYER_STAMINA_SPRINT_MIN := 5.0

## Sprinting to 0 stamina exhausts the player: sprint is locked out and stamina regen is
## paused for this long, and the stamina bar blinks. Mirrors rust/sim_core.
const PLAYER_STAMINA_EXHAUST_DURATION := 3.0


# =============================================================================
# MANA (ability resource)
# =============================================================================

## Maximum mana pool.
const PLAYER_MANA_MAX := 100.0

## Mana regenerated per second. MUST match the Rust sim_core constant (2.0) or
## ability-cost prediction desyncs from the authoritative server. Cut 75% (was 8.0) so RMB
## class abilities are a real resource cost.
const PLAYER_MANA_REGEN_PER_SEC := 2.0

## Mana consumed by a single ability use (gates the ability input).
const PLAYER_MANA_ABILITY_COST := 25.0


# =============================================================================
# STATUS-EFFECT SPEED MODIFIERS (placeholder bounds for a future manager)
# =============================================================================

## Clamp the aggregate Haste/Slow speed multiplier so stacks stay sane.
const PLAYER_SPEED_MULT_MIN := 0.25
const PLAYER_SPEED_MULT_MAX := 2.5


# =============================================================================
# CAMERA
# =============================================================================
# Single source of truth for gameplay camera zoom. Used by the online arena and
# the offline modes alike so all gameplay scenes look identical.

## Default gameplay camera zoom.
const CAMERA_ZOOM_DEFAULT := Vector2(1.5, 1.5)

## Zoom while sprinting (slightly zoomed out for a wider view).
const CAMERA_ZOOM_SPRINT := Vector2(1.35, 1.35)

## Lerp rate (per second) used to ease between default and sprint zoom.
const CAMERA_ZOOM_SPEED := 3.0


# =============================================================================
# MINIMAP
# Single source of truth for the minimap's terrain whitelist. The level terrain is rendered ONCE
# into a static texture by a WorldMapView SubViewport (scripts/ui/hud/world_map_view.gd) that
# renders ONLY canvas items whose visibility_layer includes MINIMAP_TERRAIN_BIT, so dynamic entity
# sprites (default layer 1 only) never appear there and are drawn as dots instead
# (scripts/ui/hud/minimap.gd, map_overlay.gd). Terrain CanvasItems set
# visibility_layer = MINIMAP_TERRAIN_VISIBILITY (= main layer 1 | the minimap bit).

## Visibility-layer bit the world-map SubViewport renders (its canvas_cull_mask).
const MINIMAP_TERRAIN_BIT := 2

## visibility_layer terrain CanvasItems use so they show in BOTH the main view and the
## minimap (bit 1 = the default main-view layer, plus the minimap bit).
const MINIMAP_TERRAIN_VISIBILITY := 1 | MINIMAP_TERRAIN_BIT

## World→minimap pixel scale: the HUD minimap shows MINIMAP_SIZE / MINIMAP_ZOOM world units across,
## panned to keep the local player centred (scripts/ui/hud/minimap.gd).
const MINIMAP_ZOOM := 0.08


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

## PvP defender compensation (Option 2 — server-authoritative, no client trust).
## Server PvP hit detection rewinds the defender to the SHOOTER's view (favour
## shooter), which is why a fleeing defender can feel "hit after I dodged". This
## factor pulls the *tested* defender position from the shooter-rewound position
## back toward the defender's CURRENT authoritative position:
##   0.0 = pure favour-shooter (original behaviour)
##   1.0 = test at the defender's live position (favour defender; shooters must lead)
## It trades a little shooter precision for defender dodge-feel and stays fully
## server-authoritative. High-ping defenders are pulled further (their rewind was
## larger), so the effect already scales with the defender's latency. Tune with
## 2-client, mixed-ping play-tests. See docs/netcode/hit-authority-model.md.
const PVP_DEFENDER_FAVOR := 0.25


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


## Closest point on segment [seg_start, seg_end] to a point, clamped to the
## segment bounds. Shared by server swept-collision and the client-side incoming
## projectile hit detector so both sides use byte-identical math.
static func closest_point_on_segment(point: Vector2, seg_start: Vector2, seg_end: Vector2) -> Vector2:
	var segment := seg_end - seg_start
	var length_sq := segment.length_squared()
	if length_sq <= 0.0001:
		return seg_start

	var t := clampf((point - seg_start).dot(segment) / length_sq, 0.0, 1.0)
	return seg_start + segment * t


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
