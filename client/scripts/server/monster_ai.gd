## MonsterAI - Server-side monster AI behavior system
## Handles state machine logic, target selection, steering, and combat
## Used by ServerMain to update all monster behaviors each tick
class_name MonsterAI
extends RefCounted


## AI States
enum AIState {
	IDLE = 0,      ## No target, standing still
	CHASE = 1,     ## Moving toward target
	ATTACK = 2,    ## Stopped, shooting at target
	FLEE = 3       ## Moving away from target (ranged monsters)
}


## Reference to player manager for target selection
var _player_manager: PlayerManager = null

## Reference to projectile manager for spawning monster projectiles
var _projectile_manager: ProjectileManager = null

## Debug logging flag
var debug_logging: bool = false

## Tactical difficulty for server-side monsters, 0.0..1.0.
var difficulty: float = 0.85


# =============================================================================
# INITIALIZATION
# =============================================================================

## Initialize AI system with required managers
func _init(player_manager: PlayerManager, projectile_manager: ProjectileManager, p_difficulty: float = 0.85) -> void:
	_player_manager = player_manager
	_projectile_manager = projectile_manager
	difficulty = clampf(p_difficulty, 0.0, 1.0)


# =============================================================================
# MAIN UPDATE LOOP
# =============================================================================

## Update AI for all monsters.
## Returns entity IDs for monsters that spawned projectiles this tick.
func update_all(monsters: Array[MonsterState], delta: float) -> Array[int]:
	var fired_entity_ids: Array[int] = []
	for monster in monsters:
		if _update_monster(monster, delta):
			fired_entity_ids.append(monster.entity_id)
	return fired_entity_ids


## Update AI for a single monster
## Returns true if monster spawned a projectile this tick
func _update_monster(monster: MonsterState, delta: float) -> bool:
	if not monster.is_alive:
		return false

	# Update timers
	monster.update_timers(delta)

	# Re-evaluate target periodically, and immediately for idle monsters
	# so newly spawned enemies do not wait before entering the fight.
	if monster.target_id == 0 or monster.retarget_timer >= _get_retarget_interval():
		monster.retarget_timer = 0.0
		_select_target(monster)

	# Update steering randomness
	if monster.steering_timer <= 0.0:
		_update_steering_offset(monster)

	# Run state machine
	var spawned_projectile := false
	match monster.ai_state:
		AIState.IDLE:
			_process_idle_state(monster, delta)
		AIState.CHASE:
			_process_chase_state(monster, delta)
		AIState.ATTACK:
			spawned_projectile = _process_attack_state(monster, delta)
		AIState.FLEE:
			_process_flee_state(monster, delta)

	# Update animation state based on AI state
	_update_animation(monster)

	return spawned_projectile


# =============================================================================
# TARGET SELECTION
# =============================================================================

## Select the highest-scoring alive player as target
func _select_target(monster: MonsterState) -> void:
	var players := _player_manager.get_alive_players()
	if players.is_empty():
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return

	var best_player: PlayerState = null
	var best_score := -INF

	for player in players:
		var score := _score_target(monster, player)
		if score > best_score:
			best_score = score
			best_player = player

	# Check if target is within detection range. Detection should be larger than
	# the spawn visibility radius so spawned monsters begin moving toward players.
	if best_player == null:
		return

	var dist_sq := monster.position.distance_squared_to(best_player.position)
	var detection_range := _get_detection_range()
	var lose_interest_distance := _get_lose_interest_distance()
	if dist_sq <= detection_range * detection_range:
		monster.target_id = best_player.entity_id
	elif dist_sq > lose_interest_distance * lose_interest_distance:
		# Lost target - too far away
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)


## Score target threat using distance, activity, health, and target stickiness.
func _score_target(monster: MonsterState, player: PlayerState) -> float:
	if player == null or not player.is_alive:
		return -INF

	var distance := monster.position.distance_to(player.position)
	if distance > _get_lose_interest_distance():
		return -INF

	var distance_score := clampf(1.0 - distance / _get_detection_range(), 0.0, 1.0) * 45.0
	var close_threat := clampf(1.0 - distance / maxf(1.0, _get_attack_range()), 0.0, 1.0) * 25.0
	var movement_threat := clampf(player.velocity.length() / GameConstants.PLAYER_SPRINT_SPEED, 0.0, 1.0) * 10.0
	var shooting_threat := 18.0 if player.is_shoot_held() else 0.0
	var weakened_bonus := clampf(1.0 - float(player.health) / maxf(1.0, float(player.max_health)), 0.0, 1.0) * 8.0
	var stickiness := 18.0 * (0.5 + difficulty * 0.5) if player.entity_id == monster.target_id else 0.0
	return 35.0 + distance_score + close_threat + movement_threat + shooting_threat + weakened_bonus + stickiness


## Get target player state (returns null if invalid)
func _get_target(monster: MonsterState) -> PlayerState:
	if monster.target_id == 0:
		return null
	return _player_manager.get_player_by_entity_id(monster.target_id)


func _get_retarget_interval() -> float:
	return lerpf(GameConstants.MONSTER_RETARGET_INTERVAL * 1.35, 0.28, difficulty)


func _get_detection_range() -> float:
	return lerpf(GameConstants.MONSTER_DETECTION_RANGE * 0.8, GameConstants.MONSTER_LOSE_INTEREST_DISTANCE, difficulty)


func _get_lose_interest_distance() -> float:
	return lerpf(GameConstants.MONSTER_LOSE_INTEREST_DISTANCE * 0.85, GameConstants.MONSTER_LOSE_INTEREST_DISTANCE * 1.25, difficulty)


func _get_attack_range() -> float:
	return lerpf(
		GameConstants.MONSTER_ATTACK_RANGE,
		minf(GameConstants.PROJECTILE_MAX_DISTANCE * 0.72, 540.0),
		difficulty
	)


func _get_flee_distance() -> float:
	return lerpf(GameConstants.MONSTER_FLEE_DISTANCE * 0.75, GameConstants.MONSTER_FLEE_DISTANCE * 1.75, difficulty)


func _get_preferred_distance() -> float:
	return lerpf(GameConstants.MONSTER_PREFERRED_DISTANCE, 340.0, difficulty)


# =============================================================================
# STATE MACHINE
# =============================================================================

## IDLE state - no target, wait for player to come in range
func _process_idle_state(monster: MonsterState, _delta: float) -> void:
	monster.move_direction = Vector2.ZERO
	monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_MOVING

	# Check for target
	if monster.target_id != 0:
		var target := _get_target(monster)
		if target != null and target.is_alive:
			_transition_to_state(monster, AIState.CHASE)


## CHASE state - move toward target until in attack range
func _process_chase_state(monster: MonsterState, delta: float) -> void:
	var target := _get_target(monster)
	if target == null or not target.is_alive:
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return

	var to_target := target.position - monster.position
	var distance := to_target.length()

	# Check if player is too close (flee behavior)
	if distance < _get_flee_distance():
		_transition_to_state(monster, AIState.FLEE)
		return

	# Check if in attack range
	if distance <= _get_attack_range():
		_transition_to_state(monster, AIState.ATTACK)
		return

	# Calculate movement direction with steering
	var desired_direction := to_target.normalized()
	monster.move_direction = _apply_steering(monster, desired_direction)

	# Move monster
	_move_monster(monster, delta)


## ATTACK state - orbit/kite while shooting, then resume chase if target escapes
## Returns true if projectile was spawned
func _process_attack_state(monster: MonsterState, delta: float) -> bool:
	var spawned := false

	var target := _get_target(monster)
	if target == null or not target.is_alive:
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return false

	var to_target := target.position - monster.position
	var distance := to_target.length()

	# Check if player rushed too close (flee)
	if distance < _get_flee_distance() * (0.75 + difficulty * 0.25):
		_transition_to_state(monster, AIState.FLEE)
		return false

	# Check if target moved out of range (with hysteresis to prevent oscillation)
	if distance > _get_attack_range() * 1.2:
		_transition_to_state(monster, AIState.CHASE)
		return false

	# Strafe while attacking instead of becoming a stationary target.
	var desired_move := _combat_move_direction(monster, target, distance)
	monster.move_direction = _apply_steering(monster, desired_move)
	_move_monster(monster, delta)

	# Try to shoot
	if monster.can_shoot():
		spawned = _spawn_monster_projectile(monster, _predictive_aim_direction(monster, target))
		if spawned:
			monster.start_shoot_cooldown()
			monster.attack_timer = GameConstants.MONSTER_ATTACK_DURATION

	# After attack duration, consider resuming chase
	if monster.attack_timer <= 0.0 and monster.shoot_cooldown <= 0.0:
		# Stay in attack if still in range, otherwise chase
		if distance > _get_attack_range():
			_transition_to_state(monster, AIState.CHASE)

	return spawned


## FLEE state - move away from target to maintain distance
func _process_flee_state(monster: MonsterState, delta: float) -> void:
	var target := _get_target(monster)
	if target == null or not target.is_alive:
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return

	var to_target := target.position - monster.position
	var distance := to_target.length()

	# If reached preferred distance, switch to attack or chase
	if distance >= _get_preferred_distance():
		if distance <= _get_attack_range():
			_transition_to_state(monster, AIState.ATTACK)
		else:
			_transition_to_state(monster, AIState.CHASE)
		return

	# Move away from target with a strafe bias to avoid straight retreats.
	var flee_direction := -to_target.normalized()
	var strafe := Vector2(-flee_direction.y, flee_direction.x) * _get_strafe_sign(monster)
	monster.move_direction = _apply_steering(monster, (flee_direction + strafe * (0.25 + difficulty * 0.45)).normalized())

	# Move monster
	_move_monster(monster, delta)


## Transition to a new AI state
func _transition_to_state(monster: MonsterState, new_state: int) -> void:
	if monster.ai_state == new_state:
		return

	var old_state := monster.ai_state
	monster.ai_state = new_state

	# Reset state-specific timers and flags
	match new_state:
		AIState.ATTACK:
			monster.attack_timer = 0.0
			monster.entity_flags |= PacketTypes.ENTITY_FLAG_ATTACKING
		AIState.IDLE:
			monster.move_direction = Vector2.ZERO
			monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_MOVING
			monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_ATTACKING
		AIState.CHASE, AIState.FLEE:
			monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_ATTACKING

	if debug_logging:
		print("[MonsterAI] Monster %d: %s -> %s" % [
			monster.entity_id,
			AIState.keys()[old_state],
			AIState.keys()[new_state]
		])


# =============================================================================
# STEERING AND MOVEMENT
# =============================================================================

## Apply steering with randomness and obstacle avoidance
func _apply_steering(monster: MonsterState, desired_direction: Vector2) -> Vector2:
	if desired_direction.is_zero_approx():
		return Vector2.ZERO

	# Add random steering offset for natural movement
	var randomness := GameConstants.MONSTER_STEERING_RANDOMNESS * lerpf(1.25, 0.35, difficulty)
	var steered := desired_direction + monster.steering_offset * randomness

	# Simple obstacle avoidance - check map boundaries
	var future_pos := monster.position + steered * GameConstants.MONSTER_AVOIDANCE_DISTANCE
	if not GameConstants.is_within_bounds(future_pos):
		# Reflect direction away from boundary
		if future_pos.x < GameConstants.MAP_MIN.x or future_pos.x > GameConstants.MAP_MAX.x:
			steered.x *= -1
		if future_pos.y < GameConstants.MAP_MIN.y or future_pos.y > GameConstants.MAP_MAX.y:
			steered.y *= -1

	if GameConstants.circle_intersects_obstacle(future_pos, GameConstants.MONSTER_HITBOX_RADIUS):
		steered = _find_clear_steering_direction(monster, steered.normalized())

	return steered.normalized()


## Find a nearby steering direction that does not immediately enter an obstacle.
func _find_clear_steering_direction(monster: MonsterState, desired_direction: Vector2) -> Vector2:
	var best_direction := -desired_direction
	var best_clearance := -1.0
	for offset in [PI / 4.0, -PI / 4.0, PI / 2.0, -PI / 2.0, PI]:
		var candidate := desired_direction.rotated(offset).normalized()
		var probe := monster.position + candidate * GameConstants.MONSTER_AVOIDANCE_DISTANCE
		var clearance := 0.0 if GameConstants.circle_intersects_obstacle(probe, GameConstants.MONSTER_HITBOX_RADIUS) else 1.0
		clearance += clampf(probe.distance_to(monster.position) / GameConstants.MONSTER_AVOIDANCE_DISTANCE, 0.0, 1.0)
		if clearance > best_clearance:
			best_clearance = clearance
			best_direction = candidate
	return best_direction


## Update random steering offset for natural movement
func _update_steering_offset(monster: MonsterState) -> void:
	monster.steering_offset = Vector2(
		randf_range(-1.0, 1.0),
		randf_range(-1.0, 1.0)
	).normalized()
	monster.steering_timer = randf_range(0.35, lerpf(1.5, 0.8, difficulty))


## Move monster based on current direction
func _move_monster(monster: MonsterState, delta: float) -> void:
	if monster.move_direction.is_zero_approx():
		monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_MOVING
		return

	var velocity := monster.move_direction * GameConstants.MONSTER_SPEED
	var new_position := monster.position + velocity * delta

	# Resolve against map boundaries and arena obstacles
	monster.position = GameConstants.move_with_obstacle_collision(
		monster.position,
		new_position,
		GameConstants.MONSTER_HITBOX_RADIUS
	)

	# Update entity flags
	monster.entity_flags |= PacketTypes.ENTITY_FLAG_MOVING


# =============================================================================
# COMBAT
# =============================================================================

## Movement vector used while in weapon range.
func _combat_move_direction(monster: MonsterState, target: PlayerState, distance: float) -> Vector2:
	var to_target := target.position - monster.position
	if to_target.is_zero_approx():
		return Vector2.ZERO

	var toward := to_target.normalized()
	var away := -toward
	var strafe := Vector2(-toward.y, toward.x) * _get_strafe_sign(monster)
	var preferred := _get_preferred_distance()
	var radial := Vector2.ZERO

	if distance < preferred * 0.82:
		radial = away * (0.85 + difficulty * 0.35)
	elif distance > preferred * 1.18:
		radial = toward * (0.25 + difficulty * 0.25)

	return (strafe * (0.75 + difficulty * 0.45) + radial).normalized()


func _get_strafe_sign(monster: MonsterState) -> float:
	var phase := int(Time.get_ticks_msec() / 1400) + monster.entity_id
	return 1.0 if phase % 2 == 0 else -1.0


## Predict the target position using visible server-authoritative velocity.
func _predictive_aim_direction(monster: MonsterState, target: PlayerState) -> Vector2:
	var predicted := _predict_target_position(
		monster.position,
		target.position,
		target.velocity,
		GameConstants.MONSTER_PROJECTILE_SPEED
	)
	var direction := predicted - monster.position
	if direction.is_zero_approx():
		direction = target.position - monster.position
	if direction.is_zero_approx():
		direction = Vector2.RIGHT

	var max_error := (1.0 - difficulty) * 0.22
	if max_error > 0.001:
		direction = direction.rotated(randf_range(-max_error, max_error))
	return direction.normalized()


func _predict_target_position(origin: Vector2, target_position: Vector2, target_velocity: Vector2, projectile_speed: float) -> Vector2:
	var relative := target_position - origin
	var a := target_velocity.length_squared() - projectile_speed * projectile_speed
	var b := 2.0 * relative.dot(target_velocity)
	var c := relative.length_squared()
	var t := relative.length() / maxf(1.0, projectile_speed)

	if absf(a) < 0.0001:
		if absf(b) > 0.0001:
			var linear_t := -c / b
			if linear_t > 0.0:
				t = linear_t
	else:
		var discriminant := b * b - 4.0 * a * c
		if discriminant >= 0.0:
			var root := sqrt(discriminant)
			var t1 := (-b - root) / (2.0 * a)
			var t2 := (-b + root) / (2.0 * a)
			var best := INF
			if t1 > 0.0:
				best = minf(best, t1)
			if t2 > 0.0:
				best = minf(best, t2)
			if best < INF:
				t = best

	t = clampf(t, 0.0, 2.0)
	return target_position + target_velocity * t


## Spawn a projectile from the monster
func _spawn_monster_projectile(monster: MonsterState, direction: Vector2) -> bool:
	if _projectile_manager == null:
		return false

	# Spawn position slightly in front of monster to avoid self-collision
	var spawn_offset := direction * (GameConstants.MONSTER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0)
	var spawn_position := monster.position + spawn_offset

	var projectile := _projectile_manager.spawn_projectile(
		monster.entity_id,
		spawn_position,
		direction
	)

	if projectile != null:
		# Override speed for monster projectiles (slower than player projectiles)
		projectile.speed = GameConstants.MONSTER_PROJECTILE_SPEED

		if debug_logging:
			print("[MonsterAI] Monster %d fired projectile toward %s" % [
				monster.entity_id, direction
			])
		return true

	return false


## Update animation state based on AI state
func _update_animation(monster: MonsterState) -> void:
	if not monster.is_alive:
		return

	match monster.ai_state:
		AIState.IDLE:
			monster.animation_state = PacketTypes.AnimationState.IDLE
		AIState.CHASE, AIState.FLEE:
			monster.animation_state = PacketTypes.AnimationState.WALK
		AIState.ATTACK:
			monster.animation_state = PacketTypes.AnimationState.ATTACK
