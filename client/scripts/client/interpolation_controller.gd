## InterpolationController - Client-side state interpolation for remote entities
## Smooths remote players', monsters', and projectiles' movements between server updates
## Renders entities slightly behind real-time and interpolates between known server states
class_name InterpolationController
extends Node


#region Constants
## Number of ticks to render behind real-time (100ms at 20Hz)
## Provides jitter absorption and smooth interpolation window
const RENDER_DELAY_TICKS := 2

## Consecutive missing updates before despawning entity
## 3 ticks = 150ms grace period
const DESPAWN_THRESHOLD := 3

## Maximum ticks to extrapolate before freezing entity
## 2 ticks = 100ms of extrapolation
const MAX_EXTRAPOLATION_TICKS := 2

## Distance threshold for instant teleport vs interpolation
## Matches GameConstants.TELEPORT_THRESHOLD
const TELEPORT_THRESHOLD := 150.0
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

## Estimated tick interval in seconds (calibrated from received packets)
var estimated_tick_interval: float = 0.05  ## 20Hz default

## Time when last state update was received
var last_update_time_ms: int = 0

## Set of entity IDs received in the most recent state update
var entities_in_last_update: Dictionary = {}
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
	var server_tick: int = data.get("server_tick", 0)
	var entities: Array = data.get("entities", [])

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

		current_server_tick = server_tick
		render_tick = maxi(0, server_tick - RENDER_DELAY_TICKS)
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

		# Skip local player - handled by PredictionController
		if entity_id == local_entity_id:
			continue

		entities_in_last_update[entity_id] = true

		var position: Vector2 = entity_data.get("position", Vector2.ZERO)
		var entity_type: int = entity_data.get("entity_type", PacketTypes.EntityType.PLAYER)
		var animation_state: int = entity_data.get("animation_state", PacketTypes.AnimationState.IDLE)
		var flags: int = entity_data.get("flags", 0)

		# Check if this is a new entity (spawn detection)
		if not entity_buffers.has(entity_id):
			_handle_entity_spawn(entity_id, entity_type, position, animation_state, flags, server_tick)
		else:
			_handle_entity_update(entity_id, position, animation_state, flags, entity_type, server_tick)

	# Check for despawns (entities we know about but weren't in this update)
	_check_for_despawns()

	if debug_logging and entities.size() > 0:
		var remote_count := entities_in_last_update.size()
		print("[Interpolation] Tick %d: Processed %d remote entities" % [server_tick, remote_count])
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

	# Unregister node (don't destroy - let EntityManager handle that)
	entity_nodes.erase(entity_id)

	# Emit signal for external EntityManager to remove visual node
	entity_despawned.emit(entity_id)
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
	current_server_tick = 0
	render_tick = 0

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
		"render_delay_ms": RENDER_DELAY_TICKS * estimated_tick_interval * 1000.0,
		"estimated_tick_interval_ms": estimated_tick_interval * 1000.0,
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
