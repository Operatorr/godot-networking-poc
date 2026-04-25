## PlayerState - Server-side player state container
## Holds all authoritative state for a connected player
## Created by PlayerManager when a client connects
class_name PlayerState
extends RefCounted

## Player life state for death/respawn/invulnerability flow
enum PlayerLifeState { ALIVE, DEAD, INVULNERABLE }

# Identity
var entity_id: int = 0          ## Unique ID for network sync
var peer_id: int = 0            ## WebSocket peer identifier
var character_id: String = ""
var character_name: String = ""

# Connection
var connected_at: float = 0.0
var authenticated: bool = false
var last_heartbeat: float = 0.0

# Position & Movement
var position: Vector2 = Vector2.ZERO
var velocity: Vector2 = Vector2.ZERO
var aim_angle: float = 0.0

# Input
var input_flags: int = 0
var last_input_sequence: int = 0
var input_queue: Array[Dictionary] = []

# Combat
var health: int = 100
var max_health: int = 100
var is_alive: bool = true
var shoot_cooldown: float = 0.0
var life_state: PlayerLifeState = PlayerLifeState.ALIVE
var invulnerability_timer: float = 0.0

# Stats tracking
var pvp_kills: int = 0
var monster_kills: int = 0
var deaths: int = 0
var last_killer_id: int = -1

# Animation & Flags
var animation_state: int = PacketTypes.AnimationState.IDLE
var entity_flags: int = PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE


## Create a new PlayerState with the given peer_id and entity_id
static func create(p_peer_id: int, p_entity_id: int, spawn_position: Vector2) -> PlayerState:
	var state = PlayerState.new()
	state.peer_id = p_peer_id
	state.entity_id = p_entity_id
	state.position = spawn_position
	state.connected_at = Time.get_ticks_msec() / 1000.0
	state.last_heartbeat = state.connected_at
	return state


## Convert to entity data dictionary for StateUpdatePacket
func to_entity_data() -> Dictionary:
	return {
		"id": entity_id,
		"type": PacketTypes.EntityType.PLAYER,
		"position": position,
		"animation": animation_state,
		"flags": entity_flags
	}


## Maximum queued inputs before overflow handling
const MAX_INPUT_QUEUE_SIZE := 10

## Queue an input for processing
func queue_input(input: Dictionary) -> void:
	if input_queue.size() >= MAX_INPUT_QUEUE_SIZE:
		# Drop oldest input to make room; log overflow for monitoring
		input_queue.pop_front()
		print("[PlayerState] Input queue overflow for entity %d: dropped oldest input (queue=%d)" % [entity_id, MAX_INPUT_QUEUE_SIZE])
	input_queue.append(input)


## Pop the next input from the queue
func pop_input() -> Dictionary:
	if input_queue.is_empty():
		return {}
	return input_queue.pop_front()


## Check if there are queued inputs
func has_queued_input() -> bool:
	return not input_queue.is_empty()


## Check if player can shoot (cooldown expired)
func can_shoot() -> bool:
	return is_alive and shoot_cooldown <= 0.0


## Start shoot cooldown after firing
func start_shoot_cooldown() -> void:
	shoot_cooldown = GameConstants.SHOOT_COOLDOWN


## Get the aim direction as a normalized Vector2
func get_aim_direction() -> Vector2:
	return Vector2.from_angle(aim_angle)


## Apply input with server-authoritative movement validation
## Returns validation result dictionary with correction info if needed
func apply_input(input: Dictionary, delta: float) -> Dictionary:
	# Dead players don't process input
	if life_state == PlayerLifeState.DEAD:
		return {"valid": true, "deviation": 0.0, "correction_needed": false, "server_position": position, "cheat_detected": false, "sequence": last_input_sequence}

	# Decrement shoot cooldown
	if shoot_cooldown > 0.0:
		shoot_cooldown = maxf(0.0, shoot_cooldown - delta)

	# Store raw input data
	input_flags = input.get("input_flags", 0)
	last_input_sequence = input.get("sequence", last_input_sequence)

	# End invulnerability if player moves or shoots
	if life_state == PlayerLifeState.INVULNERABLE and has_active_input():
		end_invulnerability()

	# Get client-reported position for validation
	var client_position: Vector2 = input.get("position", position)
	if not client_position is Vector2:
		client_position = position

	# Calculate server-authoritative movement from input flags
	var move_direction := _calculate_movement_direction(input_flags)
	var move_speed := _calculate_movement_speed(input_flags)

	# Calculate server-authoritative velocity and position
	velocity = move_direction * move_speed
	var previous_position := position
	var server_position := GameConstants.move_with_obstacle_collision(
		previous_position,
		previous_position + velocity * delta,
		GameConstants.PLAYER_HITBOX_RADIUS
	)
	if delta > 0.0:
		velocity = (server_position - previous_position) / delta

	# Validate client position against server calculation
	var validation := _validate_position(client_position, server_position)

	# Always use server-calculated position (authoritative)
	position = server_position

	# Update aim angle (trust client aim)
	aim_angle = input.get("aim_angle", aim_angle)

	# Update animation state based on movement
	_update_animation_state()

	# Update entity flags
	_update_entity_flags()

	return validation


## Calculate normalized movement direction from input flags
func _calculate_movement_direction(flags: int) -> Vector2:
	var direction := Vector2.ZERO

	if flags & PacketTypes.INPUT_FLAG_MOVE_UP:
		direction.y -= 1
	if flags & PacketTypes.INPUT_FLAG_MOVE_DOWN:
		direction.y += 1
	if flags & PacketTypes.INPUT_FLAG_MOVE_LEFT:
		direction.x -= 1
	if flags & PacketTypes.INPUT_FLAG_MOVE_RIGHT:
		direction.x += 1

	return direction.normalized()


## Calculate movement speed based on sprint flag
func _calculate_movement_speed(flags: int) -> float:
	var is_sprinting := bool(flags & PacketTypes.INPUT_FLAG_SPRINT)
	return GameConstants.get_movement_speed(is_sprinting)


## Validate client position against server-calculated position
## Returns a dictionary with validation results
func _validate_position(client_pos: Vector2, server_pos: Vector2) -> Dictionary:
	var deviation := client_pos.distance_to(server_pos)

	var result := {
		"valid": true,
		"deviation": deviation,
		"correction_needed": false,
		"server_position": server_pos,
		"cheat_detected": false,
		"sequence": last_input_sequence
	}

	# Check for teleportation (impossible movement)
	if deviation > GameConstants.TELEPORT_THRESHOLD:
		result.valid = false
		result.correction_needed = true
		result.cheat_detected = true
		return result

	# Check if correction packet should be sent (significant deviation)
	if deviation > GameConstants.CORRECTION_THRESHOLD:
		result.valid = false
		result.correction_needed = true
		return result

	# Within tolerance - no correction needed
	return result


## Update animation state based on current input/state
func _update_animation_state() -> void:
	if not is_alive:
		animation_state = PacketTypes.AnimationState.DEATH
	elif input_flags & PacketTypes.INPUT_FLAG_SHOOT:
		animation_state = PacketTypes.AnimationState.ATTACK
	elif velocity.length_squared() > 0.01:
		if input_flags & PacketTypes.INPUT_FLAG_SPRINT:
			animation_state = PacketTypes.AnimationState.RUN
		else:
			animation_state = PacketTypes.AnimationState.WALK
	else:
		animation_state = PacketTypes.AnimationState.IDLE


## Update entity flags based on current state
func _update_entity_flags() -> void:
	entity_flags = 0

	if is_alive:
		entity_flags |= PacketTypes.ENTITY_FLAG_ALIVE

	if velocity.length_squared() > 0.01:
		entity_flags |= PacketTypes.ENTITY_FLAG_MOVING

	if input_flags & PacketTypes.INPUT_FLAG_SHOOT:
		entity_flags |= PacketTypes.ENTITY_FLAG_ATTACKING

	if life_state == PlayerLifeState.INVULNERABLE:
		entity_flags |= PacketTypes.ENTITY_FLAG_INVULNERABLE

	# Always visible for now (interest management in TASK-064)
	entity_flags |= PacketTypes.ENTITY_FLAG_VISIBLE


## Reset player state for respawn (with invulnerability)
func reset_for_respawn(spawn_position: Vector2) -> void:
	position = spawn_position
	velocity = Vector2.ZERO
	health = max_health
	is_alive = true
	life_state = PlayerLifeState.INVULNERABLE
	invulnerability_timer = GameConstants.INVULNERABILITY_DURATION
	shoot_cooldown = 0.0
	input_flags = 0
	input_queue.clear()
	animation_state = PacketTypes.AnimationState.SPAWN
	entity_flags = PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE | PacketTypes.ENTITY_FLAG_INVULNERABLE


## Take damage and return true if killed
## Returns false if player is dead, invulnerable, or survives
func take_damage(amount: int) -> bool:
	if not is_alive:
		return false

	# Invulnerable players cannot take damage
	if life_state == PlayerLifeState.INVULNERABLE:
		return false

	health = max(0, health - amount)

	if health <= 0:
		is_alive = false
		life_state = PlayerLifeState.DEAD
		deaths += 1
		animation_state = PacketTypes.AnimationState.DEATH
		entity_flags &= ~PacketTypes.ENTITY_FLAG_ALIVE
		return true

	animation_state = PacketTypes.AnimationState.HIT
	return false


## Update invulnerability timer, returns true if invulnerability just ended
func update_invulnerability(delta: float) -> bool:
	if life_state != PlayerLifeState.INVULNERABLE:
		return false

	invulnerability_timer -= delta
	if invulnerability_timer <= 0.0:
		end_invulnerability()
		return true
	return false


## End invulnerability (called on timer expiry or player action)
func end_invulnerability() -> void:
	if life_state != PlayerLifeState.INVULNERABLE:
		return
	life_state = PlayerLifeState.ALIVE
	invulnerability_timer = 0.0
	entity_flags &= ~PacketTypes.ENTITY_FLAG_INVULNERABLE


## Check if player has movement or shoot input (ends invulnerability)
func has_active_input() -> bool:
	var move_flags := PacketTypes.INPUT_FLAG_MOVE_UP | PacketTypes.INPUT_FLAG_MOVE_DOWN | \
		PacketTypes.INPUT_FLAG_MOVE_LEFT | PacketTypes.INPUT_FLAG_MOVE_RIGHT
	var action_flags := PacketTypes.INPUT_FLAG_SHOOT
	return (input_flags & (move_flags | action_flags)) != 0


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"entity_id": entity_id,
		"peer_id": peer_id,
		"character_id": character_id,
		"character_name": character_name,
		"authenticated": authenticated,
		"position": position,
		"velocity": velocity,
		"health": health,
		"is_alive": is_alive,
		"animation_state": animation_state,
		"entity_flags": entity_flags,
		"input_queue_size": input_queue.size()
	}
