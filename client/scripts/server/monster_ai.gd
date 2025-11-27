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


# =============================================================================
# INITIALIZATION
# =============================================================================

## Initialize AI system with required managers
func _init(player_manager: PlayerManager, projectile_manager: ProjectileManager) -> void:
	_player_manager = player_manager
	_projectile_manager = projectile_manager


# =============================================================================
# MAIN UPDATE LOOP
# =============================================================================

## Update AI for all monsters
## Returns number of projectiles spawned this tick
func update_all(monsters: Array[MonsterState], delta: float) -> int:
	var projectiles_spawned := 0
	for monster in monsters:
		if _update_monster(monster, delta):
			projectiles_spawned += 1
	return projectiles_spawned


## Update AI for a single monster
## Returns true if monster spawned a projectile this tick
func _update_monster(monster: MonsterState, delta: float) -> bool:
	if not monster.is_alive:
		return false

	# Update timers
	monster.update_timers(delta)

	# Re-evaluate target periodically
	if monster.retarget_timer >= GameConstants.MONSTER_RETARGET_INTERVAL:
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

## Select nearest alive player as target
func _select_target(monster: MonsterState) -> void:
	var players := _player_manager.get_alive_players()
	if players.is_empty():
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return

	var nearest_player: PlayerState = null
	var nearest_dist := INF

	for player in players:
		var dist := monster.position.distance_to(player.position)
		if dist < nearest_dist:
			nearest_dist = dist
			nearest_player = player

	# Check if target is within detection range
	if nearest_dist <= GameConstants.MONSTER_DETECTION_RANGE:
		monster.target_id = nearest_player.entity_id
	elif nearest_dist > GameConstants.MONSTER_LOSE_INTEREST_DISTANCE:
		# Lost target - too far away
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)


## Get target player state (returns null if invalid)
func _get_target(monster: MonsterState) -> PlayerState:
	if monster.target_id == 0:
		return null
	return _player_manager.get_player_by_entity_id(monster.target_id)


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
	if distance < GameConstants.MONSTER_FLEE_DISTANCE:
		_transition_to_state(monster, AIState.FLEE)
		return

	# Check if in attack range
	if distance <= GameConstants.MONSTER_ATTACK_RANGE:
		_transition_to_state(monster, AIState.ATTACK)
		return

	# Calculate movement direction with steering
	var desired_direction := to_target.normalized()
	monster.move_direction = _apply_steering(monster, desired_direction)

	# Move monster
	_move_monster(monster, delta)


## ATTACK state - stop and shoot, then resume movement
## Returns true if projectile was spawned
func _process_attack_state(monster: MonsterState, _delta: float) -> bool:
	monster.move_direction = Vector2.ZERO
	monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_MOVING
	var spawned := false

	var target := _get_target(monster)
	if target == null or not target.is_alive:
		monster.target_id = 0
		_transition_to_state(monster, AIState.IDLE)
		return false

	var to_target := target.position - monster.position
	var distance := to_target.length()

	# Check if player rushed too close (flee)
	if distance < GameConstants.MONSTER_FLEE_DISTANCE:
		_transition_to_state(monster, AIState.FLEE)
		return false

	# Check if target moved out of range (with hysteresis to prevent oscillation)
	if distance > GameConstants.MONSTER_ATTACK_RANGE * 1.2:
		_transition_to_state(monster, AIState.CHASE)
		return false

	# Try to shoot
	if monster.can_shoot():
		spawned = _spawn_monster_projectile(monster, to_target.normalized())
		monster.start_shoot_cooldown()
		monster.attack_timer = GameConstants.MONSTER_ATTACK_DURATION

	# After attack duration, consider resuming chase
	if monster.attack_timer <= 0.0 and monster.shoot_cooldown <= 0.0:
		# Stay in attack if still in range, otherwise chase
		if distance > GameConstants.MONSTER_ATTACK_RANGE:
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
	if distance >= GameConstants.MONSTER_PREFERRED_DISTANCE:
		if distance <= GameConstants.MONSTER_ATTACK_RANGE:
			_transition_to_state(monster, AIState.ATTACK)
		else:
			_transition_to_state(monster, AIState.CHASE)
		return

	# Move away from target
	var flee_direction := -to_target.normalized()
	monster.move_direction = _apply_steering(monster, flee_direction)

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
	# Add random steering offset for natural movement
	var steered := desired_direction + monster.steering_offset * GameConstants.MONSTER_STEERING_RANDOMNESS

	# Simple obstacle avoidance - check map boundaries
	var future_pos := monster.position + steered * GameConstants.MONSTER_AVOIDANCE_DISTANCE
	if not GameConstants.is_within_bounds(future_pos):
		# Reflect direction away from boundary
		if future_pos.x < GameConstants.MAP_MIN.x or future_pos.x > GameConstants.MAP_MAX.x:
			steered.x *= -1
		if future_pos.y < GameConstants.MAP_MIN.y or future_pos.y > GameConstants.MAP_MAX.y:
			steered.y *= -1

	return steered.normalized()


## Update random steering offset for natural movement
func _update_steering_offset(monster: MonsterState) -> void:
	monster.steering_offset = Vector2(
		randf_range(-1.0, 1.0),
		randf_range(-1.0, 1.0)
	).normalized()
	monster.steering_timer = randf_range(0.5, 1.5)


## Move monster based on current direction
func _move_monster(monster: MonsterState, delta: float) -> void:
	if monster.move_direction.is_zero_approx():
		monster.entity_flags &= ~PacketTypes.ENTITY_FLAG_MOVING
		return

	var velocity := monster.move_direction * GameConstants.MONSTER_SPEED
	var new_position := monster.position + velocity * delta

	# Clamp to map boundaries
	monster.position = GameConstants.clamp_to_bounds(new_position)

	# Update entity flags
	monster.entity_flags |= PacketTypes.ENTITY_FLAG_MOVING


# =============================================================================
# COMBAT
# =============================================================================

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
