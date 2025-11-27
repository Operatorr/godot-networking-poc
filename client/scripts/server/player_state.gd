## PlayerState - Server-side player state container
## Holds all authoritative state for a connected player
## Created by PlayerManager when a client connects
class_name PlayerState
extends RefCounted

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


## Queue an input for processing
func queue_input(input: Dictionary) -> void:
	# Limit queue size to prevent memory issues
	if input_queue.size() < 10:
		input_queue.append(input)


## Pop the next input from the queue
func pop_input() -> Dictionary:
	if input_queue.is_empty():
		return {}
	return input_queue.pop_front()


## Check if there are queued inputs
func has_queued_input() -> bool:
	return not input_queue.is_empty()


## Apply input with server-authoritative movement validation
## Returns validation result dictionary with correction info if needed
func apply_input(input: Dictionary, delta: float) -> Dictionary:
	# Store raw input data
	input_flags = input.get("input_flags", 0)
	last_input_sequence = input.get("sequence", last_input_sequence)

	# Get client-reported position for validation
	var client_position: Vector2 = input.get("position", position)
	if not client_position is Vector2:
		client_position = position

	# Calculate server-authoritative movement from input flags
	var move_direction := _calculate_movement_direction(input_flags)
	var move_speed := _calculate_movement_speed(input_flags)

	# Calculate server-authoritative velocity and position
	velocity = move_direction * move_speed
	var server_position := position + velocity * delta

	# Clamp to map boundaries
	server_position = GameConstants.clamp_to_bounds(server_position)

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

	# Always visible for now (interest management in TASK-064)
	entity_flags |= PacketTypes.ENTITY_FLAG_VISIBLE


## Reset player state for respawn
func reset_for_respawn(spawn_position: Vector2) -> void:
	position = spawn_position
	velocity = Vector2.ZERO
	health = max_health
	is_alive = true
	input_flags = 0
	input_queue.clear()
	animation_state = PacketTypes.AnimationState.SPAWN
	entity_flags = PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE


## Take damage and return true if killed
func take_damage(amount: int) -> bool:
	if not is_alive:
		return false

	health = max(0, health - amount)

	if health <= 0:
		is_alive = false
		animation_state = PacketTypes.AnimationState.DEATH
		entity_flags &= ~PacketTypes.ENTITY_FLAG_ALIVE
		return true

	animation_state = PacketTypes.AnimationState.HIT
	return false


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
