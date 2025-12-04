## EntityStateBuffer - Per-entity circular buffer for state interpolation
## Stores historical state snapshots to enable smooth interpolation between server updates
## Ring buffer implementation to avoid dynamic allocation
class_name EntityStateBuffer
extends RefCounted


#region Constants
## Maximum snapshots to store (250ms of history at 20Hz tick rate)
## 2 ticks for render delay + 3 ticks safety margin for jitter
const BUFFER_SIZE := 5

## Tick interval in seconds (server runs at 20Hz)
const TICK_INTERVAL_SEC := 0.05
#endregion


#region Inner Classes
## Single point-in-time state snapshot for an entity
class EntitySnapshot extends RefCounted:
	## Server tick when this state was generated
	var server_tick: int = 0
	## Local timestamp when received (milliseconds)
	var timestamp_ms: int = 0
	## Entity position
	var position: Vector2 = Vector2.ZERO
	## Animation state enum value
	var animation_state: int = PacketTypes.AnimationState.IDLE
	## Entity flags bitfield
	var flags: int = 0
	## Entity type (PLAYER, MONSTER, PROJECTILE)
	var entity_type: int = PacketTypes.EntityType.PLAYER

	static func create(
		tick: int,
		pos: Vector2,
		anim: int,
		flg: int,
		etype: int
	) -> EntitySnapshot:
		var snapshot := EntitySnapshot.new()
		snapshot.server_tick = tick
		snapshot.timestamp_ms = Time.get_ticks_msec()
		snapshot.position = pos
		snapshot.animation_state = anim
		snapshot.flags = flg
		snapshot.entity_type = etype
		return snapshot

	func is_alive() -> bool:
		return (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0

	func is_moving() -> bool:
		return (flags & PacketTypes.ENTITY_FLAG_MOVING) != 0
#endregion


#region State Variables
## Entity ID this buffer belongs to
var entity_id: int = 0

## Circular buffer of snapshots
var snapshots: Array[EntitySnapshot] = []

## Current write position in ring buffer
var write_index: int = 0

## Number of valid snapshots in buffer (may be less than BUFFER_SIZE initially)
var snapshot_count: int = 0

## Most recent server tick added to buffer
var last_tick_added: int = -1

## Server tick when entity first appeared (for spawn detection)
var spawn_tick: int = -1

## Whether this entity is pending despawn (missing from recent updates)
var despawn_pending: bool = false

## Estimated tick interval in milliseconds (calibrated from received packets)
var estimated_tick_interval_ms: float = 50.0
#endregion


#region Lifecycle
func _init() -> void:
	# Pre-allocate buffer slots
	snapshots.resize(BUFFER_SIZE)
	for i in range(BUFFER_SIZE):
		snapshots[i] = null


static func create_for_entity(id: int) -> EntityStateBuffer:
	var buffer := EntityStateBuffer.new()
	buffer.entity_id = id
	return buffer
#endregion


#region Buffer Operations
## Add a new snapshot to the buffer
## Returns true if this is the first snapshot (entity just spawned)
func add_snapshot(
	server_tick: int,
	position: Vector2,
	animation_state: int,
	flags: int,
	entity_type: int
) -> bool:
	var is_spawn := spawn_tick < 0

	# Update spawn tick on first snapshot
	if is_spawn:
		spawn_tick = server_tick

	# Skip duplicate ticks
	if server_tick == last_tick_added:
		return false

	# Calibrate tick interval from consecutive packets
	if last_tick_added >= 0 and snapshot_count > 0:
		var prev_snapshot := _get_most_recent_snapshot()
		if prev_snapshot != null:
			var tick_delta := server_tick - last_tick_added
			var time_delta := Time.get_ticks_msec() - prev_snapshot.timestamp_ms
			if tick_delta > 0 and time_delta > 0:
				var measured_interval := float(time_delta) / float(tick_delta)
				# Smoothly adjust estimate
				estimated_tick_interval_ms = lerpf(
					estimated_tick_interval_ms,
					measured_interval,
					0.1
				)

	# Create and store snapshot
	var snapshot := EntitySnapshot.create(
		server_tick,
		position,
		animation_state,
		flags,
		entity_type
	)

	snapshots[write_index] = snapshot
	write_index = (write_index + 1) % BUFFER_SIZE
	snapshot_count = mini(snapshot_count + 1, BUFFER_SIZE)
	last_tick_added = server_tick

	# Clear despawn flag since we received an update
	despawn_pending = false

	return is_spawn


## Get two snapshots that bracket the given render tick for interpolation
## Returns [snapshot_before, snapshot_after, interpolation_factor]
## If only one valid snapshot exists, returns [snapshot, null, 0.0]
## If no valid snapshots exist, returns [null, null, 0.0]
func get_interpolation_data(render_tick: int) -> Array:
	if snapshot_count == 0:
		return [null, null, 0.0]

	var before: EntitySnapshot = null
	var after: EntitySnapshot = null

	# Find the two snapshots that bracket render_tick
	for i in range(BUFFER_SIZE):
		var snapshot: EntitySnapshot = snapshots[i]
		if snapshot == null:
			continue

		if snapshot.server_tick <= render_tick:
			if before == null or snapshot.server_tick > before.server_tick:
				before = snapshot
		else:  # snapshot.server_tick > render_tick
			if after == null or snapshot.server_tick < after.server_tick:
				after = snapshot

	# Calculate interpolation factor
	if before == null:
		# render_tick is before all snapshots - use earliest
		return [after, null, 0.0] if after != null else [null, null, 0.0]

	if after == null:
		# render_tick is after all snapshots - use latest (may need extrapolation)
		return [before, null, 1.0]

	# Both snapshots available - calculate interpolation factor
	var tick_range := after.server_tick - before.server_tick
	if tick_range <= 0:
		return [after, null, 1.0]

	var progress := float(render_tick - before.server_tick) / float(tick_range)
	return [before, after, clampf(progress, 0.0, 1.0)]


## Get most recent snapshot regardless of tick
func _get_most_recent_snapshot() -> EntitySnapshot:
	var most_recent: EntitySnapshot = null
	var highest_tick := -1

	for i in range(BUFFER_SIZE):
		var snapshot: EntitySnapshot = snapshots[i]
		if snapshot != null and snapshot.server_tick > highest_tick:
			highest_tick = snapshot.server_tick
			most_recent = snapshot

	return most_recent


## Get the latest position (for initial spawn positioning)
func get_latest_position() -> Vector2:
	var snapshot := _get_most_recent_snapshot()
	return snapshot.position if snapshot != null else Vector2.ZERO


## Get the latest entity type
func get_entity_type() -> int:
	var snapshot := _get_most_recent_snapshot()
	return snapshot.entity_type if snapshot != null else PacketTypes.EntityType.PLAYER


## Get latest animation state (for snap transitions)
func get_latest_animation_state() -> int:
	var snapshot := _get_most_recent_snapshot()
	return snapshot.animation_state if snapshot != null else PacketTypes.AnimationState.IDLE


## Get latest flags
func get_latest_flags() -> int:
	var snapshot := _get_most_recent_snapshot()
	return snapshot.flags if snapshot != null else 0


## Check if entity is alive according to latest snapshot
func is_entity_alive() -> bool:
	var snapshot := _get_most_recent_snapshot()
	return snapshot != null and snapshot.is_alive()


## Clear all snapshots (used after teleport)
func clear() -> void:
	for i in range(BUFFER_SIZE):
		snapshots[i] = null
	write_index = 0
	snapshot_count = 0
	last_tick_added = -1
	# Note: spawn_tick is NOT reset - entity is still the same


## Get time since last snapshot was received (milliseconds)
func get_time_since_last_update_ms() -> int:
	var snapshot := _get_most_recent_snapshot()
	if snapshot == null:
		return 0
	return Time.get_ticks_msec() - snapshot.timestamp_ms


## Estimate position at a given tick using extrapolation from last two snapshots
## Used for buffer underrun scenarios
func extrapolate_position(target_tick: int) -> Vector2:
	if snapshot_count < 2:
		var snapshot := _get_most_recent_snapshot()
		return snapshot.position if snapshot != null else Vector2.ZERO

	# Find two most recent snapshots
	var first: EntitySnapshot = null
	var second: EntitySnapshot = null

	for i in range(BUFFER_SIZE):
		var snapshot: EntitySnapshot = snapshots[i]
		if snapshot == null:
			continue

		if second == null or snapshot.server_tick > second.server_tick:
			first = second
			second = snapshot
		elif first == null or snapshot.server_tick > first.server_tick:
			first = snapshot

	if first == null or second == null:
		return second.position if second != null else Vector2.ZERO

	# Calculate velocity from the two snapshots
	var tick_delta := second.server_tick - first.server_tick
	if tick_delta <= 0:
		return second.position

	var velocity := (second.position - first.position) / float(tick_delta)

	# Extrapolate to target tick
	var extrapolation_ticks := target_tick - second.server_tick
	return second.position + velocity * float(extrapolation_ticks)
#endregion


#region Debug
func get_debug_info() -> Dictionary:
	return {
		"entity_id": entity_id,
		"snapshot_count": snapshot_count,
		"last_tick_added": last_tick_added,
		"spawn_tick": spawn_tick,
		"despawn_pending": despawn_pending,
		"estimated_tick_interval_ms": estimated_tick_interval_ms,
		"time_since_update_ms": get_time_since_last_update_ms()
	}
#endregion
