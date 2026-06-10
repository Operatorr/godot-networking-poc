## InterpolationController - Client-side state interpolation for remote entities
## Smooths remote players', monsters', and projectiles' movements between server updates
## Renders entities slightly behind real-time and interpolates between known server states
class_name InterpolationController
extends Node


#region Constants
## Base/default number of ticks to render behind real-time (~66ms at 30Hz).
## Used as the starting value; the EFFECTIVE delay is adaptive (see below).
const RENDER_DELAY_TICKS := GameConstants.REMOTE_ENTITY_RENDER_DELAY_TICKS

## Adaptive render-delay bounds. On a jitter-free LAN/localhost the effective delay
## collapses toward MIN (~33ms at 30Hz) instead of the old fixed ~66ms; under jitter
## it grows toward MAX. Smooth remote motion without a constant latency penalty.
const MIN_RENDER_DELAY_TICKS := 1
const MAX_RENDER_DELAY_TICKS := 3

## Consecutive missing updates before despawning entity
## 3 ticks = 150ms grace period
const DESPAWN_THRESHOLD := 3

## Maximum ticks to extrapolate before freezing entity
## 2 ticks = 100ms of extrapolation
const MAX_EXTRAPOLATION_TICKS := 2

## Distance threshold for instant teleport vs interpolation. Sourced from
## GameConstants so client and server validation stay in lockstep — drift
## here causes the client to smooth across genuine teleports (or, conversely,
## warp on legitimate fast movement).
const TELEPORT_THRESHOLD := GameConstants.TELEPORT_THRESHOLD
#endregion


#region Signals
## Emitted when a new remote entity appears in state updates
## External EntityManager should listen to instantiate visual node
signal entity_spawned(entity_id: int, entity_type: int, initial_position: Vector2)

## Emitted when an entity should be removed (missing from updates)
## External EntityManager should listen to remove visual node
signal entity_despawned(entity_id: int)

## Emitted when interpolation updates entity position (for debug/monitoring)
signal entity_position_updated(entity_id: int, position: Vector2)

## Emitted when an entity teleports (large position jump)
signal entity_teleported(entity_id: int, from_position: Vector2, to_position: Vector2)
#endregion


#region Configuration
## Enable debug logging
@export var debug_logging: bool = false

## Interpolation speed for smooth corrections (used when catching up)
@export var interpolation_speed: float = 12.0
#endregion


#region State Variables
## Per-entity state buffers: entity_id -> EntityStateBuffer
var entity_buffers: Dictionary = {}

## Registered visual nodes for position updates: entity_id -> Node2D
var entity_nodes: Dictionary = {}

## Track missing update count per entity for despawn detection
var missing_update_count: Dictionary = {}

## Current server tick (updated from state updates)
var current_server_tick: int = 0

## Render tick (current_server_tick - RENDER_DELAY_TICKS)
var render_tick: int = 0

## Accumulated time since last tick for sub-tick interpolation
var tick_accumulator: float = 0.0

## Estimated tick interval in seconds (calibrated from received packets).
## Seeded from the real server tick rate so timing is correct before calibration
## (was hardcoded 0.05 = 20Hz, causing micro-stutter until the EMA converged).
var estimated_tick_interval: float = GameConstants.SERVER_TICK_INTERVAL

## Smoothed estimate of snapshot inter-arrival jitter, in milliseconds.
var estimated_jitter_ms: float = 0.0

## Effective (adaptive) render delay in ticks, smoothed to avoid flapping between
## integer tick offsets. render_tick = current_server_tick - round(this).
var render_delay_ticks_smooth: float = float(RENDER_DELAY_TICKS)

## Time when last state update was received
var last_update_time_ms: int = 0

## Set of entity IDs received in the most recent state update
var entities_in_last_update: Dictionary = {}

## Per-entity last known state for delta reconstruction (TASK-021)
## entity_id -> { entity_type, position, animation_state, flags }
var entity_last_states: Dictionary = {}

## Last received baseline tick for delta validation (TASK-021)
var last_baseline_tick: int = 0

## Flag to request full state sync from server (TASK-021)
var needs_full_state_sync: bool = false

## Full state request timeout/retry tracking
var _full_state_request_time: int = 0  # msec when last request sent, 0 = no pending
var _full_state_retry_count: int = 0
const FULL_STATE_REQUEST_TIMEOUT_MS := 2000  # Retry after 2 seconds
const FULL_STATE_MAX_RETRIES := 3
#endregion


#region Lifecycle
func _ready() -> void:
	# Connect to NetworkManager signals
	if NetworkManager.has_signal("server_message_received"):
		NetworkManager.server_message_received.connect(_on_server_message)

	if debug_logging:
		print("[Interpolation] Controller initialized")


func _physics_process(delta: float) -> void:
	# Only process if we have entities and are receiving updates
	if entity_buffers.is_empty():
		return

	if not NetworkManager.is_server_connected():
		return

	# Check for full state request timeout and retry
	if _full_state_request_time > 0:
		var elapsed := Time.get_ticks_msec() - _full_state_request_time
		if elapsed > FULL_STATE_REQUEST_TIMEOUT_MS:
			if debug_logging:
				print("[Interpolation] Full state request timed out after %dms" % elapsed)
			_request_full_state_sync()

	# Accumulate time for sub-tick interpolation
	tick_accumulator += delta

	# Calculate how far we are into the current tick (0.0 to 1.0)
	var tick_progress := tick_accumulator / estimated_tick_interval
	tick_progress = clampf(tick_progress, 0.0, 1.0)

	# Apply interpolation to all remote entities
	_interpolate_all_entities(tick_progress)
#endregion


#region Network Message Handling
func _on_server_message(message_type: int, data: Dictionary) -> void:
	if message_type != NetworkManager.MessageType.STATE_UPDATE:
		return

	_process_state_update(data)


func _process_state_update(data: Dictionary) -> void:
	var server_tick: int = data.get("server_tick", data.get("tick", 0))
	var entities: Array = data.get("entities", [])
	var state_flags: int = data.get("state_flags", 0)
	var baseline_tick: int = data.get("baseline_tick", 0)

	# Check if this is a delta packet (TASK-021)
	var is_delta := (state_flags & PacketTypes.STATE_FLAG_IS_DELTA) != 0
	var is_baseline := (state_flags & PacketTypes.STATE_FLAG_BASELINE) != 0

	# Handle baseline tick tracking for delta validation
	if is_baseline:
		last_baseline_tick = server_tick
		# Reset full state request tracking - server answered
		_full_state_request_time = 0
		_full_state_retry_count = 0
		needs_full_state_sync = false
		# Ack the Baseline so the server can clear its resend timer (#14). The forced
		# Baseline is sent as a FULL-STATE packet and carries NO baseline_tick on the
		# wire, so we ack server_tick (the tick we tagged the Baseline with), NOT
		# data.baseline_tick. Fires once per received Baseline. INERT on today's
		# WebSocket/TCP transport (baselines are never dropped); forward-looking
		# scaffold for the UDP transport (#12). send_to_server no-ops if disconnected.
		NetworkManager.send_to_server(NetworkManager.MessageType.BASELINE_ACK, {"baseline_tick": server_tick})
		if debug_logging:
			print("[Interpolation] Received baseline packet at tick %d" % server_tick)
	elif is_delta:
		# Validate delta chain - if baseline_tick doesn't match, request full sync
		if baseline_tick != last_baseline_tick and last_baseline_tick > 0:
			if debug_logging:
				print("[Interpolation] Delta chain broken: expected baseline %d, got %d" % [last_baseline_tick, baseline_tick])
			needs_full_state_sync = true
			_request_full_state_sync()

	# Update tick tracking
	if server_tick > current_server_tick:
		# Calibrate tick interval from time between updates
		if last_update_time_ms > 0:
			var time_delta := Time.get_ticks_msec() - last_update_time_ms
			var tick_delta := server_tick - current_server_tick
			if tick_delta > 0 and time_delta > 0:
				var measured_interval := float(time_delta) / 1000.0 / float(tick_delta)
				# Smoothly adjust estimate
				estimated_tick_interval = lerpf(estimated_tick_interval, measured_interval, 0.1)
				# Adapt render delay to measured jitter: target = one snapshot
				# interval + 2x jitter margin, clamped to [MIN, MAX] ticks and
				# smoothed so it doesn't flap between integer tick offsets.
				var interval_dev_ms := absf(measured_interval - estimated_tick_interval) * 1000.0
				estimated_jitter_ms = lerpf(estimated_jitter_ms, interval_dev_ms, 0.1)
				var interval_ms := maxf(estimated_tick_interval * 1000.0, 0.001)
				var target_ms := interval_ms + 2.0 * estimated_jitter_ms
				var target_ticks := clampf(
					target_ms / interval_ms,
					float(MIN_RENDER_DELAY_TICKS),
					float(MAX_RENDER_DELAY_TICKS)
				)
				# Asymmetric: add buffer FAST when jitter rises (absorb a spike within
				# a frame or two so it never stutters), shed it SLOWLY when the link
				# calms (so a clean LAN/localhost link collapses toward MIN ~33 ms
				# without flapping back into stutter).
				var adapt_rate := 0.5 if target_ticks > render_delay_ticks_smooth else 0.05
				render_delay_ticks_smooth = lerpf(render_delay_ticks_smooth, target_ticks, adapt_rate)

		current_server_tick = server_tick
		render_tick = maxi(0, server_tick - roundi(render_delay_ticks_smooth))
		tick_accumulator = 0.0
		last_update_time_ms = Time.get_ticks_msec()

	# Track which entities are in this update
	entities_in_last_update.clear()

	# Get local player entity ID to filter it out
	var local_entity_id := GameManager.get_local_player_entity_id()

	# Process each entity in the update
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id < 0:
			continue

		var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
		if is_delta and (delta_mask & PacketTypes.DELTA_MASK_REMOVED) != 0:
			_handle_explicit_despawn(entity_id)
			continue

		# Skip local player - handled by PredictionController
		if entity_id == local_entity_id:
			continue

		entities_in_last_update[entity_id] = true

		# Reconstruct full state from delta if needed (TASK-021)
		var reconstructed_data: Dictionary = _reconstruct_entity_state(entity_data, is_delta)

		var position: Vector2 = reconstructed_data.get("position", Vector2.ZERO)
		var entity_type: int = reconstructed_data.get("entity_type", PacketTypes.EntityType.PLAYER)
		var animation_state: int = reconstructed_data.get("animation_state", PacketTypes.AnimationState.IDLE)
		var flags: int = reconstructed_data.get("flags", 0)

		# Check if this is a new entity (spawn detection)
		if not entity_buffers.has(entity_id):
			_handle_entity_spawn(entity_id, entity_type, position, animation_state, flags, server_tick)
		else:
			_handle_entity_update(entity_id, position, animation_state, flags, entity_type, server_tick)

		# Store reconstructed state for future delta reconstruction (TASK-021)
		_update_last_known_state(entity_id, reconstructed_data)

	# Check for despawns (entities we know about but weren't in this update)
	# Note: In delta mode, entities with no changes are not sent, so don't despawn them
	if not is_delta:
		_check_for_despawns()

	if debug_logging and entities.size() > 0:
		var remote_count := entities_in_last_update.size()
		var mode_str := "delta" if is_delta else ("baseline" if is_baseline else "full")
		print("[Interpolation] Tick %d (%s): Processed %d remote entities" % [server_tick, mode_str, remote_count])


## Reconstruct full entity state from delta packet (TASK-021)
func _reconstruct_entity_state(entity_data: Dictionary, is_delta: bool) -> Dictionary:
	var entity_id: int = entity_data.get("entity_id", -1)
	var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)

	# If full state (baseline, new spawn, or periodic sync), use as-is
	if not is_delta or (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0:
		return {
			"entity_id": entity_id,
			"entity_type": entity_data.get("entity_type", PacketTypes.EntityType.PLAYER),
			"position": entity_data.get("position", Vector2.ZERO),
			"animation_state": entity_data.get("animation_state", PacketTypes.AnimationState.IDLE),
			"flags": entity_data.get("flags", 0)
		}

	# Delta packet - merge with last known state
	var last_state: Dictionary = entity_last_states.get(entity_id, {})

	# Start with last known state
	var result := {
		"entity_id": entity_id,
		"entity_type": last_state.get("entity_type", entity_data.get("entity_type", PacketTypes.EntityType.PLAYER)),
		"position": last_state.get("position", Vector2.ZERO),
		"animation_state": last_state.get("animation_state", PacketTypes.AnimationState.IDLE),
		"flags": last_state.get("flags", 0)
	}

	# Apply delta fields
	if (delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
		result.position = entity_data.get("position", result.position)

	if (delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
		result.animation_state = entity_data.get("animation_state", result.animation_state)

	if (delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
		result.flags = entity_data.get("flags", result.flags)

	return result


## Update last known state for an entity (TASK-021)
func _update_last_known_state(entity_id: int, state: Dictionary) -> void:
	entity_last_states[entity_id] = {
		"entity_type": state.get("entity_type", PacketTypes.EntityType.PLAYER),
		"position": state.get("position", Vector2.ZERO),
		"animation_state": state.get("animation_state", PacketTypes.AnimationState.IDLE),
		"flags": state.get("flags", 0)
	}


## Request full state sync from server (TASK-021)
## Tracks send time and retries up to FULL_STATE_MAX_RETRIES.
## If all retries fail, clears interpolation buffers so the client can recover.
func _request_full_state_sync() -> void:
	if not NetworkManager.is_server_connected():
		return

	# Check retry limit
	if _full_state_retry_count >= FULL_STATE_MAX_RETRIES:
		push_warning("[Interpolation] Full state sync failed after %d retries, clearing buffers" % FULL_STATE_MAX_RETRIES)
		clear_all_entities()
		_full_state_request_time = 0
		_full_state_retry_count = 0
		needs_full_state_sync = false
		return

	_full_state_request_time = Time.get_ticks_msec()
	_full_state_retry_count += 1

	NetworkManager.send_to_server(
		NetworkManager.MessageType.REQUEST_FULL_STATE,
		{}
	)

	if debug_logging:
		print("[Interpolation] Requested full state sync (attempt %d/%d)" % [_full_state_retry_count, FULL_STATE_MAX_RETRIES])
#endregion


#region Entity Lifecycle
func _handle_entity_spawn(
	entity_id: int,
	entity_type: int,
	position: Vector2,
	animation_state: int,
	flags: int,
	server_tick: int
) -> void:
	# Create state buffer for new entity
	var buffer := EntityStateBuffer.create_for_entity(entity_id)
	buffer.add_snapshot(server_tick, position, animation_state, flags, entity_type)
	entity_buffers[entity_id] = buffer

	# Reset missing counter
	missing_update_count[entity_id] = 0

	if debug_logging:
		var type_name := _get_entity_type_name(entity_type)
		print("[Interpolation] Entity spawned: id=%d, type=%s, pos=%s" % [
			entity_id, type_name, position
		])

	# Emit signal for external EntityManager to create visual node
	entity_spawned.emit(entity_id, entity_type, position)


func _handle_entity_update(
	entity_id: int,
	position: Vector2,
	animation_state: int,
	flags: int,
	entity_type: int,
	server_tick: int
) -> void:
	var buffer: EntityStateBuffer = entity_buffers[entity_id]

	# Check for teleportation (large position jump)
	var last_position := buffer.get_latest_position()
	var distance := last_position.distance_to(position)

	if distance > TELEPORT_THRESHOLD:
		if debug_logging:
			print("[Interpolation] Entity %d teleported: %.2f units" % [entity_id, distance])

		# Clear buffer and snap to new position
		buffer.clear()
		entity_teleported.emit(entity_id, last_position, position)

		# Immediately update visual node if registered
		if entity_nodes.has(entity_id):
			var node: Node2D = entity_nodes[entity_id]
			if is_instance_valid(node):
				node.position = position
				# Discontinuous jump: reset interpolation so physics_interpolation
				# doesn't visually lerp the node across the teleport.
				node.reset_physics_interpolation()

	# Add new snapshot to buffer
	buffer.add_snapshot(server_tick, position, animation_state, flags, entity_type)

	# Reset missing counter
	missing_update_count[entity_id] = 0


func _check_for_despawns() -> void:
	var entities_to_despawn: Array[int] = []

	for entity_id: int in entity_buffers.keys():
		if not entities_in_last_update.has(entity_id):
			# Entity was not in this update
			missing_update_count[entity_id] = missing_update_count.get(entity_id, 0) + 1

			var buffer: EntityStateBuffer = entity_buffers[entity_id]
			buffer.despawn_pending = true

			if missing_update_count[entity_id] >= DESPAWN_THRESHOLD:
				entities_to_despawn.append(entity_id)

	# Process despawns
	for entity_id in entities_to_despawn:
		_despawn_entity(entity_id)


func _despawn_entity(entity_id: int) -> void:
	if debug_logging:
		print("[Interpolation] Entity despawned: id=%d" % entity_id)

	# Clean up buffer
	entity_buffers.erase(entity_id)
	missing_update_count.erase(entity_id)
	entity_last_states.erase(entity_id)  # TASK-021

	# Unregister node (don't destroy - let EntityManager handle that)
	entity_nodes.erase(entity_id)

	# Emit signal for external EntityManager to remove visual node
	entity_despawned.emit(entity_id)


func _handle_explicit_despawn(entity_id: int) -> void:
	if entity_buffers.has(entity_id):
		_despawn_entity(entity_id)
	else:
		missing_update_count.erase(entity_id)
		entity_last_states.erase(entity_id)
		entity_nodes.erase(entity_id)


## Forget an entity without requiring a server despawn marker.
## Used when a pre-auth local player snapshot was briefly classified as remote.
func forget_entity(entity_id: int) -> void:
	entity_buffers.erase(entity_id)
	missing_update_count.erase(entity_id)
	entity_last_states.erase(entity_id)
	entity_nodes.erase(entity_id)
#endregion


#region Interpolation Logic
func _interpolate_all_entities(tick_progress: float) -> void:
	for entity_id: int in entity_buffers.keys():
		var buffer: EntityStateBuffer = entity_buffers[entity_id]

		# Skip if no visual node registered
		if not entity_nodes.has(entity_id):
			continue

		var node: Node2D = entity_nodes[entity_id]
		if not is_instance_valid(node):
			entity_nodes.erase(entity_id)
			continue

		# Calculate interpolated position
		var interpolated_position := _calculate_interpolated_position(buffer, tick_progress)

		# Apply to visual node
		node.position = interpolated_position

		entity_position_updated.emit(entity_id, interpolated_position)


func _calculate_interpolated_position(buffer: EntityStateBuffer, tick_progress: float) -> Vector2:
	# Get interpolation data for current render tick
	var interp_data: Array = buffer.get_interpolation_data(render_tick)
	var before: EntityStateBuffer.EntitySnapshot = interp_data[0]
	var after: EntityStateBuffer.EntitySnapshot = interp_data[1]
	var factor: float = interp_data[2]

	# No snapshots available - shouldn't happen but handle gracefully
	if before == null:
		return buffer.get_latest_position()

	# Only have one snapshot (just spawned or missing data)
	if after == null:
		# Check if we need to extrapolate
		if factor >= 1.0:
			# We're past the last known state - extrapolate
			var ticks_past := render_tick - before.server_tick
			if ticks_past <= MAX_EXTRAPOLATION_TICKS:
				return buffer.extrapolate_position(render_tick)
			else:
				# Beyond max extrapolation - freeze at last known position
				return before.position
		else:
			# We're before the first known state - snap to it
			return before.position

	# Normal interpolation between two snapshots
	var base_position := before.position.lerp(after.position, factor)

	# Add sub-tick interpolation for smoother motion
	# This interpolates between the current and next interpolated positions
	if tick_progress > 0.0:
		# Estimate what the next tick's interpolated position would be
		var next_interp_data: Array = buffer.get_interpolation_data(render_tick + 1)
		var next_before: EntityStateBuffer.EntitySnapshot = next_interp_data[0]
		var next_after: EntityStateBuffer.EntitySnapshot = next_interp_data[1]
		var next_factor: float = next_interp_data[2]

		if next_before != null:
			var next_position: Vector2
			if next_after != null:
				next_position = next_before.position.lerp(next_after.position, next_factor)
			else:
				next_position = next_before.position

			# Blend between current and next based on tick progress
			return base_position.lerp(next_position, tick_progress)

	return base_position
#endregion


#region Public API for EntityManager
## Register a visual node for an entity (call after creating the node)
func register_entity_node(entity_id: int, node: Node2D) -> void:
	if not entity_buffers.has(entity_id):
		push_warning("[Interpolation] Cannot register node for unknown entity: %d" % entity_id)
		return

	entity_nodes[entity_id] = node

	# Set initial position from buffer
	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	node.position = buffer.get_latest_position()
	# Fresh placement is a discontinuity — don't lerp from the node's old transform.
	node.reset_physics_interpolation()

	if debug_logging:
		print("[Interpolation] Node registered for entity %d" % entity_id)


## Unregister a visual node (call before destroying the node)
func unregister_entity_node(entity_id: int) -> void:
	entity_nodes.erase(entity_id)

	if debug_logging:
		print("[Interpolation] Node unregistered for entity %d" % entity_id)


## Get current interpolated position for an entity
func get_entity_position(entity_id: int) -> Vector2:
	if not entity_buffers.has(entity_id):
		return Vector2.ZERO

	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	var interp_data: Array = buffer.get_interpolation_data(render_tick)
	var before: EntityStateBuffer.EntitySnapshot = interp_data[0]
	var after: EntityStateBuffer.EntitySnapshot = interp_data[1]
	var factor: float = interp_data[2]

	if before == null:
		return Vector2.ZERO

	if after == null:
		return before.position

	return before.position.lerp(after.position, factor)


## Get the newest server position in the interpolation buffer for diagnostics.
func get_entity_latest_server_position(entity_id: int) -> Vector2:
	if not entity_buffers.has(entity_id):
		return Vector2.ZERO

	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	return buffer.get_latest_position()


## Get animation state for an entity (not interpolated - snaps to latest)
func get_entity_animation_state(entity_id: int) -> int:
	if not entity_buffers.has(entity_id):
		return PacketTypes.AnimationState.IDLE

	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	return buffer.get_latest_animation_state()


## Get entity flags (not interpolated - snaps to latest)
func get_entity_flags(entity_id: int) -> int:
	if not entity_buffers.has(entity_id):
		return 0

	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	return buffer.get_latest_flags()


## Get entity type
func get_entity_type(entity_id: int) -> int:
	if not entity_buffers.has(entity_id):
		return PacketTypes.EntityType.PLAYER

	var buffer: EntityStateBuffer = entity_buffers[entity_id]
	return buffer.get_entity_type()


## Check if entity exists in interpolation system
func has_entity(entity_id: int) -> bool:
	return entity_buffers.has(entity_id)


## Get all tracked entity IDs
func get_all_entity_ids() -> Array[int]:
	var ids: Array[int] = []
	for id: int in entity_buffers.keys():
		ids.append(id)
	return ids


## Get entities by type
func get_entities_by_type(entity_type: int) -> Array[int]:
	var ids: Array[int] = []
	for id: int in entity_buffers.keys():
		var buffer: EntityStateBuffer = entity_buffers[id]
		if buffer.get_entity_type() == entity_type:
			ids.append(id)
	return ids


## Force clear all entities (use on disconnect/scene change)
func clear_all_entities() -> void:
	for entity_id: int in entity_buffers.keys():
		entity_despawned.emit(entity_id)

	entity_buffers.clear()
	entity_nodes.clear()
	missing_update_count.clear()
	entity_last_states.clear()  # TASK-021
	current_server_tick = 0
	render_tick = 0
	last_baseline_tick = 0  # TASK-021
	needs_full_state_sync = false  # TASK-021
	_full_state_request_time = 0
	_full_state_retry_count = 0

	if debug_logging:
		print("[Interpolation] All entities cleared")
#endregion


#region Debug and Diagnostics
func get_debug_info() -> Dictionary:
	var entity_count := entity_buffers.size()
	var registered_nodes := entity_nodes.size()

	var players := get_entities_by_type(PacketTypes.EntityType.PLAYER).size()
	var monsters := get_entities_by_type(PacketTypes.EntityType.MONSTER).size()
	var projectiles := get_entities_by_type(PacketTypes.EntityType.PROJECTILE).size()

	return {
		"current_server_tick": current_server_tick,
		"render_tick": render_tick,
		"render_delay_ticks": render_delay_ticks_smooth,
		"render_delay_ms": render_delay_ticks_smooth * estimated_tick_interval * 1000.0,
		"estimated_tick_interval_ms": estimated_tick_interval * 1000.0,
		"estimated_jitter_ms": estimated_jitter_ms,
		"entity_count": entity_count,
		"registered_nodes": registered_nodes,
		"players": players,
		"monsters": monsters,
		"projectiles": projectiles
	}


func _get_entity_type_name(entity_type: int) -> String:
	match entity_type:
		PacketTypes.EntityType.PLAYER:
			return "PLAYER"
		PacketTypes.EntityType.MONSTER:
			return "MONSTER"
		PacketTypes.EntityType.PROJECTILE:
			return "PROJECTILE"
		_:
			return "UNKNOWN"
#endregion
