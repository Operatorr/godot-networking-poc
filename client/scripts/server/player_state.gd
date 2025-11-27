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


## Apply input to update state (basic - no validation, that's TASK-013)
func apply_input(input: Dictionary) -> void:
	# Store raw input data
	input_flags = input.get("input_flags", 0)
	last_input_sequence = input.get("sequence", last_input_sequence)

	# Update position directly from client input (will be validated in TASK-013)
	var new_pos = input.get("position", position)
	if new_pos is Vector2:
		position = new_pos

	# Update velocity
	var new_vel = input.get("velocity", velocity)
	if new_vel is Vector2:
		velocity = new_vel

	# Update aim angle
	aim_angle = input.get("aim_angle", aim_angle)

	# Update animation state based on movement
	_update_animation_state()

	# Update entity flags
	_update_entity_flags()


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
