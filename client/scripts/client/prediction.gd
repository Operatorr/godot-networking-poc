## PredictionController - Client-side prediction with server reconciliation
## Provides immediate local movement feedback while maintaining server authority
## Attach as child node to player scene, call setup() to initialize
class_name PredictionController
extends Node


#region Signals
## Emitted when a server correction is applied
signal correction_applied(correction_amount: float)
## Emitted when prediction mismatches server (before reconciliation)
signal prediction_mismatch(predicted_pos: Vector2, server_pos: Vector2)
## Emitted when reconciliation completes
signal reconciliation_complete(replayed_inputs: int)
## Emitted when the local player's visual position changes.
signal visual_position_updated(visual_position: Vector2, is_discontinuous: bool)
## Cosmetic-only: emitted on the SHOOT rising-edge (and while held, gated to the
## server auto-fire cadence) so the client can draw an immediate muzzle flash
## without waiting for the PROJECTILE_FIRED round-trip. This does NOT spawn
## a Projectile and does NOT touch predicted_position or the input buffer.
signal shoot_predicted(muzzle_position: Vector2, aim_direction: Vector2)
#endregion


#region Configuration
## Correction interpolation speed (higher = snappier corrections)
@export var interpolation_speed: float = 12.0
## Maximum stored inputs (matches 8-bit sequence range)
@export var max_buffer_size: int = 256
## Enable debug output
@export var debug_logging: bool = false
## Enable low-volume shoot diagnostics for projectile/server sync issues
@export var projectile_sync_debug_logging: bool = false
## Threshold for instant teleport vs smooth correction (units)
@export var teleport_threshold: float = 150.0
## Ignore tiny quantization jitter from compressed server positions.
@export var server_position_epsilon: float = 4.0
#endregion


#region State Variables
## Reference to the controlled player node
var player_node: Node2D = null

## Optional remote-entity interpolation reference for shoot diagnostics
var interpolation_controller: InterpolationController = null

## Local player's entity ID (set during spawn/connection)
var local_entity_id: int = -1

## Current predicted position (authoritative client-side)
var predicted_position: Vector2 = Vector2.ZERO

## Current predicted velocity
var predicted_velocity: Vector2 = Vector2.ZERO

## True after receiving and applying at least one authoritative server position.
var has_authoritative_position: bool = false

## Last acknowledged sequence number from server (-1 = none yet)
var last_ack_sequence: int = -1

## Current input sequence number (0-255, wrapping)
var current_sequence: int = 0

## Input buffer: sequence_number (int) -> InputSnapshot
var input_buffer: Dictionary = {}

## Smooth correction state
var correction_target: Vector2 = Vector2.ZERO
var is_correcting: bool = false

## Server tick tracking for ordering
var last_server_tick: int = 0

## Input send rate limiting. Match the authoritative server tick interval.
var input_send_timer: float = 0.0
const INPUT_SEND_INTERVAL: float = GameConstants.SERVER_TICK_INTERVAL

## Current frame's accumulated input flags
var current_input_flags: int = 0

## Last time (seconds) the cosmetic shoot feedback fired, used to gate held-fire
## to the server's SHOOT_COOLDOWN auto-fire cadence. -INF so the first shot fires.
var _last_predicted_shot_time: float = -INF

## Whether prediction and input sending are enabled for the local player.
var prediction_enabled: bool = true
#endregion


#region Inner Classes
## Snapshot of input state for reconciliation replay
class InputSnapshot:
	var sequence: int = 0
	var input_flags: int = 0
	var position_before: Vector2 = Vector2.ZERO
	var position_after: Vector2 = Vector2.ZERO
	var velocity: Vector2 = Vector2.ZERO
	var aim_angle: float = 0.0
	var delta: float = 0.0
	var timestamp: float = 0.0

	static func create(seq: int, flags: int, pos_before: Vector2, pos_after: Vector2,
					   vel: Vector2, angle: float, dt: float) -> InputSnapshot:
		var snapshot := InputSnapshot.new()
		snapshot.sequence = seq
		snapshot.input_flags = flags
		snapshot.position_before = pos_before
		snapshot.position_after = pos_after
		snapshot.velocity = vel
		snapshot.aim_angle = angle
		snapshot.delta = dt
		snapshot.timestamp = Time.get_ticks_msec() / 1000.0
		return snapshot
#endregion


#region Lifecycle
func _ready() -> void:
	# Connect to NetworkManager signals
	if NetworkManager.has_signal("server_message_received"):
		NetworkManager.server_message_received.connect(_on_server_message)

	# Initialize state
	_reset_state()


func _reset_state() -> void:
	input_buffer.clear()
	current_sequence = 0
	last_ack_sequence = -1
	is_correcting = false
	input_send_timer = 0.0
	current_input_flags = 0


## Initialize the controller with a player node
func setup(player: Node2D, initial_position: Vector2, entity_id: int = -1) -> void:
	player_node = player
	local_entity_id = entity_id
	predicted_position = initial_position
	correction_target = initial_position
	has_authoritative_position = false
	_reset_state()

	if debug_logging:
		print("[Prediction] Setup: entity_id=%d, pos=%s" % [entity_id, initial_position])
#endregion


#region Main Loop
func _physics_process(delta: float) -> void:
	if player_node == null:
		return

	# Skip if not connected
	if not NetworkManager.is_server_connected():
		_emit_visual_position_updated(false)
		return

	if not is_active():
		current_input_flags = 0
		predicted_velocity = Vector2.ZERO
		_emit_visual_position_updated(false)
		return

	# Step 1: Capture current frame's input
	var previous_input_flags := current_input_flags
	current_input_flags = _capture_input_flags()
	if projectile_sync_debug_logging:
		_log_shoot_edge(previous_input_flags, current_input_flags)

	# Step 1b: Emit cosmetic-only shoot feedback (muzzle flash). Fires on
	# the SHOOT rising-edge and, while held, at most once per SHOOT_COOLDOWN so it
	# mirrors the server's auto-fire cadence. Does not move the player or spawn a
	# real projectile — server stays authoritative for damage.
	_maybe_emit_shoot_predicted(previous_input_flags, current_input_flags)

	# Step 2: Apply local prediction immediately
	_apply_local_prediction(current_input_flags, delta)

	# Step 3: Handle smooth correction interpolation
	if is_correcting:
		_apply_smooth_correction(delta)

	# Step 4: Send input to server at the server tick cadence
	input_send_timer += delta
	if input_send_timer >= INPUT_SEND_INTERVAL:
		_send_input_to_server()
		input_send_timer -= INPUT_SEND_INTERVAL

	_emit_visual_position_updated(false)
#endregion


#region Input Capture
func _capture_input_flags() -> int:
	var flags := 0

	# Movement (WASD)
	if Input.is_action_pressed("move_up"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_UP
	if Input.is_action_pressed("move_down"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_DOWN
	if Input.is_action_pressed("move_left"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_LEFT
	if Input.is_action_pressed("move_right"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_RIGHT

	# Actions
	if Input.is_action_pressed("shoot"):
		flags |= PacketTypes.INPUT_FLAG_SHOOT
	if Input.is_action_pressed("ability"):
		flags |= PacketTypes.INPUT_FLAG_ABILITY
	if Input.is_action_pressed("sprint"):
		flags |= PacketTypes.INPUT_FLAG_SPRINT
	if Input.is_action_pressed("interact"):
		flags |= PacketTypes.INPUT_FLAG_INTERACT

	return flags


func _get_aim_angle() -> float:
	if player_node == null:
		return 0.0
	# Calculate angle from player to mouse
	var mouse_pos := player_node.get_global_mouse_position()
	return predicted_position.angle_to_point(mouse_pos)


func _log_shoot_edge(previous_flags: int, new_flags: int) -> void:
	var was_shooting := (previous_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	var is_shooting := (new_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	if not is_shooting or was_shooting or player_node == null:
		return

	var mouse_pos := player_node.get_global_mouse_position()
	var aim_angle := predicted_position.angle_to_point(mouse_pos)
	var monster_text := "none"

	if interpolation_controller != null:
		var monster_ids := interpolation_controller.get_entities_by_type(PacketTypes.EntityType.MONSTER)
		var lines: Array[String] = []
		for monster_id: int in monster_ids:
			var rendered_pos := interpolation_controller.get_entity_position(monster_id)
			var latest_pos := interpolation_controller.get_entity_latest_server_position(monster_id)
			lines.append("%d rendered=%s latest=%s gap=%.2f" % [
				monster_id,
				rendered_pos,
				latest_pos,
				rendered_pos.distance_to(latest_pos)
			])

		if not lines.is_empty():
			monster_text = ""
			for line in lines:
				if not monster_text.is_empty():
					monster_text += "; "
				monster_text += line

	var render_tick := interpolation_controller.render_tick if interpolation_controller != null else -1
	var newest_tick := interpolation_controller.current_server_tick if interpolation_controller != null else -1
	print("[Prediction] Shoot edge: local_entity=%d predicted_pos=%s mouse_world=%s aim_angle=%.4f server_tick=%d render_tick=%d monsters=[%s]" % [
		local_entity_id,
		predicted_position,
		mouse_pos,
		aim_angle,
		newest_tick,
		render_tick,
		monster_text
	])


## Cosmetic-only shoot feedback gate. Emits shoot_predicted on the SHOOT
## rising-edge, and while SHOOT stays held re-emits at most once per
## SHOOT_COOLDOWN to mirror the server's auto-fire cadence (server_main
## _process_shoot_inputs). Computes the muzzle origin exactly like the server
## (server_main._try_spawn_projectile) so the flash lines up with the real
## projectile. Purely visual — never writes predicted_position or the buffer.
func _maybe_emit_shoot_predicted(previous_flags: int, new_flags: int) -> void:
	if player_node == null:
		return

	var is_shooting := (new_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	if not is_shooting:
		return

	var was_shooting := (previous_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	var now := Time.get_ticks_msec() / 1000.0
	var rising_edge := not was_shooting
	var cooldown_elapsed := (now - _last_predicted_shot_time) >= GameConstants.SHOOT_COOLDOWN
	if not rising_edge and not cooldown_elapsed:
		return

	_last_predicted_shot_time = now

	var aim_direction := Vector2.from_angle(_get_aim_angle())
	var muzzle := predicted_position + aim_direction * (
		GameConstants.PLAYER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0
	)
	shoot_predicted.emit(muzzle, aim_direction)


func _get_client_render_tick() -> int:
	if interpolation_controller != null:
		return interpolation_controller.render_tick & 0xFFFF
	return maxi(0, last_server_tick - GameConstants.REMOTE_ENTITY_RENDER_DELAY_TICKS) & 0xFFFF
#endregion


#region Local Prediction
func _apply_local_prediction(input_flags: int, delta: float) -> void:
	var position_before := predicted_position

	# Calculate movement from input flags
	var direction := _get_direction_from_flags(input_flags)
	var speed := _get_speed_from_flags(input_flags)

	# Update velocity and position
	predicted_velocity = direction * speed
	predicted_position = GameConstants.move_with_obstacle_collision(
		predicted_position,
		predicted_position + predicted_velocity * delta,
		GameConstants.PLAYER_HITBOX_RADIUS
	)
	if delta > 0.0:
		predicted_velocity = (predicted_position - position_before) / delta

	# Update visual position (unless correcting)
	_update_player_visual()


func _get_direction_from_flags(flags: int) -> Vector2:
	var direction := Vector2.ZERO

	if flags & PacketTypes.INPUT_FLAG_MOVE_UP:
		direction.y -= 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_DOWN:
		direction.y += 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_LEFT:
		direction.x -= 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_RIGHT:
		direction.x += 1.0

	return direction.normalized()


func _get_speed_from_flags(flags: int) -> float:
	if flags & PacketTypes.INPUT_FLAG_SPRINT:
		return GameConstants.PLAYER_SPRINT_SPEED
	return GameConstants.PLAYER_SPEED
#endregion


#region Input Buffer Management
func _store_input(snapshot: InputSnapshot) -> void:
	input_buffer[snapshot.sequence] = snapshot

	# Prune old acknowledged inputs
	_prune_acknowledged_inputs()


func _prune_acknowledged_inputs() -> void:
	if last_ack_sequence < 0:
		return

	var keys_to_remove: Array[int] = []

	for seq: int in input_buffer.keys():
		if _is_sequence_acknowledged(seq):
			keys_to_remove.append(seq)

	for seq in keys_to_remove:
		input_buffer.erase(seq)

	if debug_logging and keys_to_remove.size() > 0:
		print("[Prediction] Pruned %d acknowledged inputs, buffer size: %d" % [
			keys_to_remove.size(), input_buffer.size()
		])


func _is_sequence_acknowledged(seq: int) -> bool:
	# A sequence is acknowledged if it's "before or equal to" last_ack_sequence
	# accounting for 8-bit wraparound
	if last_ack_sequence < 0:
		return false

	if seq == last_ack_sequence:
		return true

	return _sequence_less_than(seq, last_ack_sequence)


## Compare two 8-bit sequence numbers with wraparound
## Returns true if seq_a came before seq_b
func _sequence_less_than(seq_a: int, seq_b: int) -> bool:
	# Calculate forward distance (seq_a -> seq_b going up)
	var forward_dist := (seq_b - seq_a) & 0xFF

	# If forward distance is in lower half (0-127), seq_a is less
	# If forward distance is in upper half (128-255), seq_b wrapped and is less
	return forward_dist > 0 and forward_dist < 128


## Get the next sequence number with wrap
func _advance_sequence() -> int:
	var seq := current_sequence
	current_sequence = (current_sequence + 1) & 0xFF
	return seq
#endregion


#region Network Communication
func _send_input_to_server() -> void:
	if not is_active() or not NetworkManager.is_server_connected():
		return

	var seq := _advance_sequence()
	var aim_angle := _get_aim_angle()
	var network_stats := NetworkManager.get_stats()
	var client_render_tick := _get_client_render_tick()
	var client_rtt_ms := int(network_stats.get("ping_ms", 0.0))

	# Store one replay snapshot per sent input. The server applies one input over
	# one authoritative tick, so replay uses the same interval.
	var replay_velocity := _get_direction_from_flags(current_input_flags) * _get_speed_from_flags(current_input_flags)
	var replay_end := GameConstants.move_with_obstacle_collision(
		predicted_position,
		predicted_position + replay_velocity * INPUT_SEND_INTERVAL,
		GameConstants.PLAYER_HITBOX_RADIUS
	)
	var snapshot := InputSnapshot.create(
		seq,
		current_input_flags,
		predicted_position,
		replay_end,
		replay_velocity,
		aim_angle,
		INPUT_SEND_INTERVAL
	)
	_store_input(snapshot)

	# Build input data dictionary matching expected format
	var input_data := {
		"position": predicted_position,
		"velocity": predicted_velocity,
		"keys": {
			"up": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_UP),
			"down": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_DOWN),
			"left": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_LEFT),
			"right": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_RIGHT),
			"shoot": bool(current_input_flags & PacketTypes.INPUT_FLAG_SHOOT),
			"ability": bool(current_input_flags & PacketTypes.INPUT_FLAG_ABILITY),
			"sprint": bool(current_input_flags & PacketTypes.INPUT_FLAG_SPRINT),
			"interact": bool(current_input_flags & PacketTypes.INPUT_FLAG_INTERACT)
		},
		"aim_angle": aim_angle,
		"sequence": seq,
		"client_render_tick": client_render_tick,
		"client_rtt_ms": client_rtt_ms
	}

	NetworkManager.send_player_input(input_data)

	if debug_logging:
		print("[Prediction] Sent input: seq=%d, pos=%s, flags=%d, render_tick=%d, rtt_ms=%d" % [
			seq, predicted_position, current_input_flags, client_render_tick, client_rtt_ms
		])
#endregion


#region Server Message Handling
func _on_server_message(message_type: int, data: Dictionary) -> void:
	match message_type:
		NetworkManager.MessageType.ACTION_CONFIRM:
			_handle_action_confirm(data)
		NetworkManager.MessageType.STATE_UPDATE:
			_handle_state_update(data)


func _handle_action_confirm(data: Dictionary) -> void:
	var sequence: int = data.get("sequence_number", 0)
	var action_type: int = data.get("action_type", 0)
	var corrected_position: Vector2 = data.get("corrected_position", Vector2.ZERO)
	var result_code: int = data.get("result_code", 0)
	var server_tick: int = data.get("server_tick", 0)

	if debug_logging:
		print("[Prediction] ActionConfirm: seq=%d, action=%d, result=%d, pos=%s, tick=%d" % [
			sequence, action_type, result_code, corrected_position, server_tick
		])

	# Only handle MOVE action type
	if action_type != ActionConfirmPacket.ActionType.MOVE:
		return

	# Update tracking
	last_ack_sequence = sequence
	last_server_tick = server_tick

	# Check if correction is needed
	# result_code != SUCCESS means the server sent us a correction
	if result_code != ActionConfirmPacket.ResultCode.SUCCESS:
		_reconcile(sequence, corrected_position)
	else:
		if not has_authoritative_position:
			force_sync(corrected_position)
		elif predicted_position.distance_to(corrected_position) > server_position_epsilon:
			_reconcile(sequence, corrected_position)
		else:
			_prune_acknowledged_inputs()


func _handle_state_update(data: Dictionary) -> void:
	var server_tick: int = data.get("server_tick", 0)
	var entities: Array = data.get("entities", [])
	var is_delta := (int(data.get("state_flags", 0)) & PacketTypes.STATE_FLAG_IS_DELTA) != 0

	last_server_tick = server_tick

	# Skip if we don't know our entity ID
	if local_entity_id < 0:
		return

	# Find our entity in the update
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id == local_entity_id:
			var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
			if is_delta \
				and (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) == 0 \
				and (delta_mask & PacketTypes.DELTA_MASK_POSITION) == 0:
				return
			_process_own_state_update(entity_data)
			break


func _process_own_state_update(entity_data: Dictionary) -> void:
	var server_position: Vector2 = entity_data.get("position", Vector2.ZERO)

	if not has_authoritative_position:
		force_sync(server_position)
		return

	# If no unacknowledged inputs, sync directly to server position
	if input_buffer.is_empty():
		_apply_authoritative_position_without_replay(server_position)
		return

	# Otherwise, check for significant drift (possible packet loss)
	var discrepancy := predicted_position.distance_to(server_position)

	if discrepancy > server_position_epsilon:
		if debug_logging:
			print("[Prediction] StateUpdate drift detected (%.2f), reconciling from server position" % discrepancy)
		_reconcile(last_ack_sequence, server_position)
#endregion


#region Reconciliation
func _reconcile(ack_sequence: int, server_position: Vector2) -> void:
	var discrepancy := predicted_position.distance_to(server_position)

	if debug_logging:
		print("[Prediction] Reconciling: seq=%d, discrepancy=%.2f" % [ack_sequence, discrepancy])
		print("[Prediction]   Predicted: %s, Server: %s" % [predicted_position, server_position])

	prediction_mismatch.emit(predicted_position, server_position)

	# Step 1: Reset to server's authoritative position
	predicted_position = server_position
	has_authoritative_position = true

	# Step 2: Collect and replay unacknowledged inputs in order
	var unacked_sequences := _get_unacknowledged_sequences(ack_sequence)
	var replayed_count := 0

	for seq in unacked_sequences:
		if input_buffer.has(seq):
			var snapshot: InputSnapshot = input_buffer[seq]
			_replay_input(snapshot)
			replayed_count += 1

	if debug_logging:
		print("[Prediction]   Replayed %d inputs" % replayed_count)
		print("[Prediction]   Final predicted: %s" % predicted_position)

	# Step 3: Calculate visual correction needed
	var visual_pos := player_node.position if player_node else predicted_position
	var correction_amount := visual_pos.distance_to(predicted_position)

	# Step 4: Apply correction (instant or smooth)
	if correction_amount > teleport_threshold:
		_apply_instant_correction()
		if debug_logging:
			print("[Prediction]   Applied instant correction (%.2f > %.2f)" % [
				correction_amount, teleport_threshold
			])
	else:
		_start_smooth_correction(visual_pos)
		if debug_logging:
			print("[Prediction]   Starting smooth correction (%.2f)" % correction_amount)

	# Step 5: Emit signals
	correction_applied.emit(correction_amount)
	reconciliation_complete.emit(replayed_count)

	# Step 6: Prune acknowledged inputs
	_prune_acknowledged_inputs()


func _get_unacknowledged_sequences(ack_sequence: int) -> Array[int]:
	## Returns unacknowledged sequence numbers in order
	var result: Array[int] = []

	# Start from one after the acknowledged sequence
	var seq := (ack_sequence + 1) & 0xFF

	# Iterate up to current_sequence
	var safety := 0
	while seq != current_sequence and safety < 256:
		if input_buffer.has(seq):
			result.append(seq)
		seq = (seq + 1) & 0xFF
		safety += 1

	return result


func _replay_input(snapshot: InputSnapshot) -> void:
	## Re-simulate this input from current predicted_position
	var direction := _get_direction_from_flags(snapshot.input_flags)
	var speed := _get_speed_from_flags(snapshot.input_flags)

	var velocity := direction * speed
	var position_before := predicted_position
	predicted_position = GameConstants.move_with_obstacle_collision(
		predicted_position,
		predicted_position + velocity * snapshot.delta,
		GameConstants.PLAYER_HITBOX_RADIUS
	)
	if snapshot.delta > 0.0:
		velocity = (predicted_position - position_before) / snapshot.delta

	# Update snapshot for potential future replays
	snapshot.position_after = predicted_position
	snapshot.velocity = velocity
#endregion


#region Visual Updates
func _update_player_visual() -> void:
	if player_node == null:
		return

	if not is_correcting:
		player_node.position = predicted_position


func _start_smooth_correction(_from_position: Vector2) -> void:
	correction_target = predicted_position
	is_correcting = true


func _apply_instant_correction() -> void:
	if player_node != null:
		player_node.position = predicted_position
		# Hard correction is a discontinuity — don't let physics_interpolation
		# visually lerp the local player across the snap.
		player_node.reset_physics_interpolation()
		_emit_visual_position_updated(true)
	correction_target = predicted_position
	is_correcting = false


func _apply_smooth_correction(delta: float) -> void:
	if player_node == null:
		is_correcting = false
		return

	# Target is the current predicted position (moves each frame)
	correction_target = predicted_position

	# Exponential interpolation toward target
	var current_visual := player_node.position
	var new_visual := current_visual.lerp(correction_target, interpolation_speed * delta)

	# Check if close enough to stop correcting
	var remaining := new_visual.distance_to(correction_target)
	if remaining < 1.0:
		player_node.position = correction_target
		is_correcting = false
	else:
		player_node.position = new_visual
#endregion


#region Utility
## Force sync with server (for recovery scenarios)
func force_sync(server_position: Vector2) -> void:
	input_buffer.clear()
	predicted_position = server_position
	predicted_velocity = Vector2.ZERO
	correction_target = server_position
	is_correcting = false
	has_authoritative_position = true
	if player_node:
		player_node.position = server_position
		player_node.reset_physics_interpolation()
	_emit_visual_position_updated(true)

	if debug_logging:
		print("[Prediction] Force synced to %s" % server_position)


## Get current state for debugging
func get_debug_info() -> Dictionary:
	return {
		"predicted_position": predicted_position,
		"predicted_velocity": predicted_velocity,
		"current_sequence": current_sequence,
		"last_ack_sequence": last_ack_sequence,
		"buffer_size": input_buffer.size(),
		"is_correcting": is_correcting,
		"local_entity_id": local_entity_id,
		"has_authoritative_position": has_authoritative_position
	}


## Check if prediction is active
func is_active() -> bool:
	return prediction_enabled and player_node != null and local_entity_id >= 0 and has_authoritative_position


## World-space position at which the local player is currently rendered. While a
## smooth correction is in flight this trails predicted_position — the correction
## target moves each frame while player_node.position only lerps toward it — so
## callers that must match exactly what the player sees on screen (e.g.
## LocalHitDetector) should test against this, not predicted_position.
func get_rendered_position() -> Vector2:
	if player_node != null:
		return player_node.position
	return predicted_position


## Enable or disable local prediction and outbound input.
func set_prediction_enabled(enabled: bool) -> void:
	if prediction_enabled == enabled:
		return

	prediction_enabled = enabled
	current_input_flags = 0
	predicted_velocity = Vector2.ZERO
	input_send_timer = 0.0
	input_buffer.clear()
	is_correcting = false


func _emit_visual_position_updated(is_discontinuous: bool) -> void:
	if player_node:
		visual_position_updated.emit(player_node.position, is_discontinuous)


## Set local entity ID once PLAYER_INFO identifies this client.
func set_local_entity_id(entity_id: int) -> void:
	local_entity_id = entity_id


## Check if the controller has applied an authoritative spawn/server position.
func has_authoritative_sync() -> bool:
	return has_authoritative_position


func _apply_authoritative_position_without_replay(server_position: Vector2) -> void:
	var discrepancy := predicted_position.distance_to(server_position)
	predicted_position = server_position
	correction_target = server_position
	has_authoritative_position = true

	if discrepancy > teleport_threshold:
		_apply_instant_correction()
	elif discrepancy > server_position_epsilon:
		var visual_pos := player_node.position if player_node else predicted_position
		_start_smooth_correction(visual_pos)
	else:
		_update_player_visual()
#endregion
