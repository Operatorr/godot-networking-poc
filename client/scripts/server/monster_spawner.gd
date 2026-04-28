## MonsterSpawner - Endless monster spawning system
## Handles spawn timing and position selection outside player visibility
## Used by ServerMain to populate the arena with monsters
class_name MonsterSpawner
extends RefCounted

## Reference to monster manager for spawning
var _monster_manager: MonsterManager = null

## Reference to player manager for visibility checks
var _player_manager: PlayerManager = null

## Configurable spawn rate in monsters per second.
var spawn_rate: float = GameConstants.MONSTER_SPAWN_RATE

## Time accumulator for spawn rate
var _spawn_timer: float = 0.0

## Director time, used for regional visit recency scoring
var _director_time: float = 0.0

## Regional spawn cells used by the background population layer
var _regions: Array[Dictionary] = []

## Whether spawning is enabled
var enabled: bool = true

## Debug logging flag
var debug_logging: bool = true


## Initialize spawner with required managers
func _init(
	monster_manager: MonsterManager,
	player_manager: PlayerManager,
	initial_spawn_rate: float = GameConstants.MONSTER_SPAWN_RATE
) -> void:
	_monster_manager = monster_manager
	_player_manager = player_manager
	spawn_rate = maxf(initial_spawn_rate, 0.01)
	_build_spawn_regions()


## Update spawner - call once per tick
## delta: time since last tick in seconds
func update(delta: float) -> void:
	if not enabled:
		return

	if _monster_manager == null or _player_manager == null:
		return

	_director_time += delta
	_update_region_player_state()

	# Check if at max capacity
	if _monster_manager.get_alive_monster_count() >= GameConstants.MONSTER_MAX_COUNT:
		return

	# Accumulate spawn time
	_spawn_timer += delta

	# Calculate spawn interval from rate
	var spawn_interval := 1.0 / spawn_rate

	# Spawn monsters while timer exceeds interval
	while _spawn_timer >= spawn_interval:
		_spawn_timer -= spawn_interval

		# Check capacity again in case we spawned one
		if _monster_manager.get_alive_monster_count() >= GameConstants.MONSTER_MAX_COUNT:
			break

		_try_spawn_monster()


## Attempt to spawn a monster at a valid position
func _try_spawn_monster() -> MonsterState:
	var position := _select_spawn_position()

	if position == Vector2.INF:
		if debug_logging:
			print("[MonsterSpawner] Failed to find valid spawn position")
		return null

	return _monster_manager.spawn_monster(position)


## Select a spawn position from the regional population or encounter pressure layer.
func _select_spawn_position() -> Vector2:
	var alive_players := _player_manager.get_alive_players()
	if alive_players.is_empty():
		return Vector2.INF

	var anchor_position := _select_anchor_spawn_position()
	if anchor_position != Vector2.INF:
		return anchor_position

	var regional_budget := _get_regional_budget()
	var encounter_budget := GameConstants.MONSTER_MAX_COUNT - regional_budget
	var counts := _count_alive_monsters_by_layer()
	var regional_deficit := regional_budget - int(counts.get("regional", 0))
	var encounter_deficit := encounter_budget - int(counts.get("encounter", 0))

	var prefer_regional := regional_deficit > encounter_deficit
	if regional_deficit > 0 and encounter_deficit > 0:
		prefer_regional = randf() < GameConstants.MONSTER_REGIONAL_SPAWN_RATIO

	var primary := _select_regional_spawn_position() if prefer_regional else _select_encounter_spawn_position()
	if primary != Vector2.INF:
		return primary

	# Fallback to the other layer. If both fail, delay this spawn.
	if prefer_regional:
		return _select_encounter_spawn_position()
	return _select_regional_spawn_position()


## Prefer shared arena monster anchors before falling back to procedural director samples.
func _select_anchor_spawn_position() -> Vector2:
	var anchors := GameConstants.get_valid_monster_spawns()
	if anchors.is_empty():
		return Vector2.INF

	var start_index := randi() % anchors.size()
	for i in range(anchors.size()):
		var position := anchors[(start_index + i) % anchors.size()]
		if _is_valid_spawn_position(position):
			return position

	return Vector2.INF


## Select a pressure spawn near players, outside direct visibility.
func _select_encounter_spawn_position() -> Vector2:
	var alive_players := _player_manager.get_alive_players()
	if alive_players.is_empty():
		return Vector2.INF

	for i in range(GameConstants.MONSTER_SPAWN_ATTEMPTS):
		var target_player: PlayerState = alive_players[randi() % alive_players.size()]
		var angle := randf() * TAU
		var distance := randf_range(
			GameConstants.MONSTER_SPAWN_MIN_DISTANCE,
			GameConstants.MONSTER_SPAWN_MAX_DISTANCE
		)
		var position := target_player.position + Vector2.from_angle(angle) * distance

		if _is_valid_spawn_position(position):
			return position

	return Vector2.INF


## Select a regional spawn to maintain background map population.
func _select_regional_spawn_position() -> Vector2:
	if _regions.is_empty():
		return Vector2.INF

	var region_counts := _count_alive_monsters_by_region()
	var ranked_regions := _get_ranked_regions(region_counts)

	for region in ranked_regions:
		var position := _sample_valid_position_in_region(region)
		if position != Vector2.INF:
			return position

	return Vector2.INF


## Build a coarse grid across the arena for regional population spawning.
func _build_spawn_regions() -> void:
	_regions.clear()

	var map_size := GameConstants.MAP_MAX - GameConstants.MAP_MIN
	var cell_size := Vector2(
		map_size.x / float(GameConstants.MONSTER_SPAWN_REGION_COLUMNS),
		map_size.y / float(GameConstants.MONSTER_SPAWN_REGION_ROWS)
	)

	var index := 0
	for y in range(GameConstants.MONSTER_SPAWN_REGION_ROWS):
		for x in range(GameConstants.MONSTER_SPAWN_REGION_COLUMNS):
			var rect := Rect2(
				GameConstants.MAP_MIN + Vector2(cell_size.x * x, cell_size.y * y),
				cell_size
			)
			_regions.append({
				"index": index,
				"rect": rect,
				"last_player_time": -9999.0,
				"player_count": 0
			})
			index += 1


## Update player counts and visit recency per region.
func _update_region_player_state() -> void:
	for region in _regions:
		region["player_count"] = 0

	for player: PlayerState in _player_manager.get_alive_players():
		var region_index := _get_region_index_for_position(player.position)
		if region_index < 0:
			continue

		var region: Dictionary = _regions[region_index]
		region["player_count"] = int(region.get("player_count", 0)) + 1
		region["last_player_time"] = _director_time


## Count alive monsters by regional cell.
func _count_alive_monsters_by_region() -> Dictionary:
	var counts := {}
	for monster: MonsterState in _monster_manager.get_alive_monsters():
		var region_index := _get_region_index_for_position(monster.position)
		if region_index < 0:
			continue
		counts[region_index] = int(counts.get(region_index, 0)) + 1
	return counts


## Count alive monsters by director layer.
func _count_alive_monsters_by_layer() -> Dictionary:
	var encounter_count := 0
	var regional_count := 0

	for monster: MonsterState in _monster_manager.get_alive_monsters():
		if _is_position_near_any_player(monster.position, GameConstants.MONSTER_DETECTION_RANGE):
			encounter_count += 1
		else:
			regional_count += 1

	return {
		"regional": regional_count,
		"encounter": encounter_count
	}


## Rank regions by underpopulation, player density, and visit recency.
func _get_ranked_regions(region_counts: Dictionary) -> Array[Dictionary]:
	var ranked: Array[Dictionary] = []
	for region in _regions:
		var scored_region := region.duplicate()
		scored_region["_spawn_score"] = _score_region(region, region_counts) + randf()
		ranked.append(scored_region)

	ranked.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var a_score := float(a.get("_spawn_score", 0.0))
		var b_score := float(b.get("_spawn_score", 0.0))
		if is_equal_approx(a_score, b_score):
			return int(a.get("index", 0)) < int(b.get("index", 0))
		return a_score > b_score
	)
	return ranked


## Score a region for background population spawning.
func _score_region(region: Dictionary, region_counts: Dictionary) -> float:
	var region_index: int = region.get("index", -1)
	var monster_count := int(region_counts.get(region_index, 0))
	if monster_count >= GameConstants.MONSTER_SPAWN_REGION_SOFT_CAP:
		return -1000.0 - float(monster_count)

	var target_count := _get_target_count_for_region(region)
	var deficit := maxf(0.0, float(target_count - monster_count))
	var last_player_time := float(region.get("last_player_time", -9999.0))
	var time_since_visit := clampf(_director_time - last_player_time, 0.0, 120.0)
	var player_count := int(region.get("player_count", 0))

	return deficit * 100.0 \
		+ time_since_visit * 0.2 \
		+ float(player_count) * 20.0 \
		- float(monster_count) * 25.0


## Target count for a region. Regions with players get extra demand, while
## the soft cap prevents them from consuming the whole regional layer.
func _get_target_count_for_region(region: Dictionary) -> int:
	return mini(
		GameConstants.MONSTER_SPAWN_REGION_SOFT_CAP,
		1 + int(region.get("player_count", 0))
	)


## Sample valid positions inside a region.
func _sample_valid_position_in_region(region: Dictionary) -> Vector2:
	var rect: Rect2 = region.get("rect", Rect2())

	for i in range(GameConstants.MONSTER_SPAWN_REGION_CANDIDATES):
		var position := Vector2(
			randf_range(rect.position.x, rect.position.x + rect.size.x),
			randf_range(rect.position.y, rect.position.y + rect.size.y)
		)

		if _is_valid_spawn_position(position):
			return position

	return Vector2.INF


## Check if a candidate monster spawn position is usable.
func _is_valid_spawn_position(position: Vector2) -> bool:
	if not GameConstants.is_within_bounds(position):
		return false

	if GameConstants.circle_intersects_obstacle(position, GameConstants.MONSTER_HITBOX_RADIUS):
		return false

	if _would_overlap_existing_monster(position):
		return false

	if _is_position_visible_to_players(position):
		return false

	return true


## Check whether a spawn would overlap an existing alive monster.
func _would_overlap_existing_monster(position: Vector2) -> bool:
	if _monster_manager == null:
		return false

	var closest := _monster_manager.get_closest_alive_monster(position)
	if closest == null:
		return false

	var min_distance := GameConstants.MONSTER_SPAWN_SEPARATION
	return closest.position.distance_squared_to(position) < min_distance * min_distance


## Check whether a point is within distance of any alive player.
func _is_position_near_any_player(position: Vector2, distance: float) -> bool:
	var distance_sq := distance * distance
	for player: PlayerState in _player_manager.get_alive_players():
		if player.position.distance_squared_to(position) <= distance_sq:
			return true
	return false


## Find the spawn region containing a position.
func _get_region_index_for_position(position: Vector2) -> int:
	if not GameConstants.is_within_bounds(position):
		return -1

	var map_size := GameConstants.MAP_MAX - GameConstants.MAP_MIN
	var relative := position - GameConstants.MAP_MIN
	var x := clampi(
		floori(relative.x / map_size.x * GameConstants.MONSTER_SPAWN_REGION_COLUMNS),
		0,
		GameConstants.MONSTER_SPAWN_REGION_COLUMNS - 1
	)
	var y := clampi(
		floori(relative.y / map_size.y * GameConstants.MONSTER_SPAWN_REGION_ROWS),
		0,
		GameConstants.MONSTER_SPAWN_REGION_ROWS - 1
	)

	return y * GameConstants.MONSTER_SPAWN_REGION_COLUMNS + x


## Regional layer budget from global cap.
func _get_regional_budget() -> int:
	return clampi(
		int(round(GameConstants.MONSTER_MAX_COUNT * GameConstants.MONSTER_REGIONAL_SPAWN_RATIO)),
		0,
		GameConstants.MONSTER_MAX_COUNT
	)


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


## Enable or disable spawning
func set_enabled(value: bool) -> void:
	enabled = value
	if debug_logging:
		print("[MonsterSpawner] Spawning %s" % ("enabled" if enabled else "disabled"))


## Reset spawner state (e.g., for round restart)
func reset() -> void:
	_spawn_timer = 0.0
	_director_time = 0.0
	for region in _regions:
		region["last_player_time"] = -9999.0
		region["player_count"] = 0
	if debug_logging:
		print("[MonsterSpawner] Spawner reset")
