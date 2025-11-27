## MonsterSpawner - Endless monster spawning system
## Handles spawn timing and position selection outside player visibility
## Used by ServerMain to populate the arena with monsters
class_name MonsterSpawner
extends RefCounted

## Reference to monster manager for spawning
var _monster_manager: MonsterManager = null

## Reference to player manager for visibility checks
var _player_manager: PlayerManager = null

## Time accumulator for spawn rate
var _spawn_timer: float = 0.0

## Whether spawning is enabled
var enabled: bool = true

## Debug logging flag
var debug_logging: bool = true


## Initialize spawner with required managers
func _init(monster_manager: MonsterManager, player_manager: PlayerManager) -> void:
	_monster_manager = monster_manager
	_player_manager = player_manager


## Update spawner - call once per tick
## delta: time since last tick in seconds
func update(delta: float) -> void:
	if not enabled:
		return

	if _monster_manager == null or _player_manager == null:
		return

	# Check if at max capacity
	if _monster_manager.get_monster_count() >= GameConstants.MONSTER_MAX_COUNT:
		return

	# Accumulate spawn time
	_spawn_timer += delta

	# Calculate spawn interval from rate
	var spawn_interval := 1.0 / GameConstants.MONSTER_SPAWN_RATE

	# Spawn monsters while timer exceeds interval
	while _spawn_timer >= spawn_interval:
		_spawn_timer -= spawn_interval

		# Check capacity again in case we spawned one
		if _monster_manager.get_monster_count() >= GameConstants.MONSTER_MAX_COUNT:
			break

		_try_spawn_monster()


## Attempt to spawn a monster at a valid position
func _try_spawn_monster() -> MonsterState:
	var position := _get_random_spawn_position()

	if position == Vector2.INF:
		if debug_logging:
			print("[MonsterSpawner] Failed to find valid spawn position")
		return null

	return _monster_manager.spawn_monster(position)


## Get a random spawn position outside player visibility
## Returns Vector2.INF if no valid position found
func _get_random_spawn_position() -> Vector2:
	# Try multiple times to find position outside all player views
	for i in range(GameConstants.MONSTER_SPAWN_ATTEMPTS):
		# Random position anywhere in map bounds
		var position := Vector2(
			randf_range(GameConstants.MAP_MIN.x, GameConstants.MAP_MAX.x),
			randf_range(GameConstants.MAP_MIN.y, GameConstants.MAP_MAX.y)
		)

		if not _is_position_visible_to_players(position):
			return position

	# Fallback: spawn at edge of map if no valid position found
	return _get_edge_spawn_position()


## Check if a position is within visibility radius of any alive player
func _is_position_visible_to_players(position: Vector2) -> bool:
	if _player_manager == null:
		return false

	for player: PlayerState in _player_manager.get_all_players():
		if not player.is_alive:
			continue

		var distance := position.distance_to(player.position)
		if distance < GameConstants.MONSTER_VISIBILITY_RADIUS:
			return true

	return false


## Get a random spawn position at the edge of the map
## Used as fallback when normal spawning fails (e.g., many players covering the map)
func _get_edge_spawn_position() -> Vector2:
	# Choose a random edge (0=top, 1=right, 2=bottom, 3=left)
	var edge := randi() % 4
	var position := Vector2.ZERO

	match edge:
		0:  # Top edge
			position.x = randf_range(GameConstants.MAP_MIN.x, GameConstants.MAP_MAX.x)
			position.y = GameConstants.MAP_MIN.y + 50.0
		1:  # Right edge
			position.x = GameConstants.MAP_MAX.x - 50.0
			position.y = randf_range(GameConstants.MAP_MIN.y, GameConstants.MAP_MAX.y)
		2:  # Bottom edge
			position.x = randf_range(GameConstants.MAP_MIN.x, GameConstants.MAP_MAX.x)
			position.y = GameConstants.MAP_MAX.y - 50.0
		3:  # Left edge
			position.x = GameConstants.MAP_MIN.x + 50.0
			position.y = randf_range(GameConstants.MAP_MIN.y, GameConstants.MAP_MAX.y)

	if debug_logging:
		print("[MonsterSpawner] Using edge fallback spawn at %s" % position)

	return position


## Enable or disable spawning
func set_enabled(value: bool) -> void:
	enabled = value
	if debug_logging:
		print("[MonsterSpawner] Spawning %s" % ("enabled" if enabled else "disabled"))


## Reset spawner state (e.g., for round restart)
func reset() -> void:
	_spawn_timer = 0.0
	if debug_logging:
		print("[MonsterSpawner] Spawner reset")
