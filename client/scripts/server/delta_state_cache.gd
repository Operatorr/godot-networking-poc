## DeltaStateCache - Per-client state caching for delta compression (TASK-021)
## Tracks the last-sent state of each entity to calculate deltas
## Reduces bandwidth by only transmitting changed fields
class_name DeltaStateCache
extends RefCounted


#region Inner Class: Cached Entity State
## Stores the last-sent state for a single entity
class CachedEntityState extends RefCounted:
	var entity_id: int = 0
	var entity_type: int = PacketTypes.EntityType.PLAYER
	var position: Vector2 = Vector2.ZERO
	var animation_state: int = PacketTypes.AnimationState.IDLE
	var flags: int = 0
	var last_tick_sent: int = 0
	var is_new: bool = true  ## True if entity hasn't been sent yet

	static func create(id: int, type: int) -> CachedEntityState:
		var state = CachedEntityState.new()
		state.entity_id = id
		state.entity_type = type
		state.is_new = true
		return state

	## Update cached state after sending
	func update(pos: Vector2, anim: int, flg: int, tick: int) -> void:
		position = pos
		animation_state = anim
		flags = flg
		last_tick_sent = tick
		is_new = false
#endregion


#region Cache State
## Per-entity cached states: entity_id -> CachedEntityState
var _cache: Dictionary = {}

## Tick when the last baseline (full state) was sent
var _baseline_tick: int = 0

## Peer ID this cache belongs to (for debugging)
var peer_id: int = 0

## Enable debug logging
var debug_logging: bool = false
#endregion


#region Lifecycle
func _init() -> void:
	_cache = {}
	_baseline_tick = 0


## Factory method to create cache for a specific client
static func create_for_client(client_peer_id: int):
	# Note: Can't use class_name in static func due to GDScript limitation
	var script = load("res://scripts/server/delta_state_cache.gd")
	var cache = script.new()
	cache.peer_id = client_peer_id
	return cache
#endregion


#region Delta Calculation
## Calculate the delta mask for an entity compared to cached state
## Returns bitmask indicating which fields changed
## Returns DELTA_MASK_FULL_STATE if entity is new or needs full state
func calculate_delta_mask(entity_id: int, current_state: Dictionary, current_tick: int) -> int:
	# New entity - send full state
	if not _cache.has(entity_id):
		return PacketTypes.DELTA_MASK_FULL_STATE

	var cached: CachedEntityState = _cache[entity_id]

	# Entity was just added - send full state
	if cached.is_new:
		return PacketTypes.DELTA_MASK_FULL_STATE

	# Check if forced full state interval has passed
	if needs_full_state_for_interval(current_tick):
		return PacketTypes.DELTA_MASK_FULL_STATE

	# Calculate delta mask based on changed fields
	var delta_mask: int = 0

	# Check position change
	var current_pos: Vector2 = current_state.get("position", Vector2.ZERO)
	if not _positions_equal(cached.position, current_pos):
		delta_mask |= PacketTypes.DELTA_MASK_POSITION

	# Check animation state change
	var current_anim: int = current_state.get("animation_state", PacketTypes.AnimationState.IDLE)
	if cached.animation_state != current_anim:
		delta_mask |= PacketTypes.DELTA_MASK_ANIMATION

	# Check flags change
	var current_flags: int = current_state.get("flags", 0)
	if cached.flags != current_flags:
		delta_mask |= PacketTypes.DELTA_MASK_FLAGS

	return delta_mask


## Check if two positions are equal (within quantization precision)
## Uses 0.1 precision to match PacketWriter.POSITION_SCALE
func _positions_equal(a: Vector2, b: Vector2) -> bool:
	# Using 0.05 as threshold (half of 0.1 quantization step)
	return absf(a.x - b.x) < 0.05 and absf(a.y - b.y) < 0.05


## Check if we should send full state due to interval
func needs_full_state_for_interval(current_tick: int) -> bool:
	return current_tick - _baseline_tick >= PacketTypes.DELTA_FULL_STATE_INTERVAL
#endregion


#region Cache Management
## Get cached state for an entity (or create new if doesn't exist)
func get_or_create_cached_state(entity_id: int, entity_type: int) -> CachedEntityState:
	if not _cache.has(entity_id):
		_cache[entity_id] = CachedEntityState.create(entity_id, entity_type)
	return _cache[entity_id]


## Update cache after successfully sending state
func update_cache(entity_id: int, state: Dictionary, tick: int) -> void:
	var entity_type: int = state.get("entity_type", PacketTypes.EntityType.PLAYER)

	if not _cache.has(entity_id):
		_cache[entity_id] = CachedEntityState.create(entity_id, entity_type)

	var cached: CachedEntityState = _cache[entity_id]
	cached.update(
		state.get("position", Vector2.ZERO),
		state.get("animation_state", PacketTypes.AnimationState.IDLE),
		state.get("flags", 0),
		tick
	)


## Mask-aware update used after sending a partial delta. Only fields whose bit
## is set in `mask` are written into the cache, so LOD-throttled fields keep
## their previous cached value and remain dirty for the next eligible tick.
func update_cache_partial(entity_id: int, state: Dictionary, mask: int, tick: int) -> void:
	var entity_type: int = state.get("entity_type", PacketTypes.EntityType.PLAYER)

	if not _cache.has(entity_id):
		_cache[entity_id] = CachedEntityState.create(entity_id, entity_type)

	var cached: CachedEntityState = _cache[entity_id]
	cached.entity_type = entity_type

	# Full state always rewrites every tracked field.
	if (mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0:
		cached.position = state.get("position", Vector2.ZERO)
		cached.animation_state = state.get("animation_state", PacketTypes.AnimationState.IDLE)
		cached.flags = state.get("flags", 0)
	else:
		if (mask & PacketTypes.DELTA_MASK_POSITION) != 0:
			cached.position = state.get("position", Vector2.ZERO)
		if (mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
			cached.animation_state = state.get("animation_state", PacketTypes.AnimationState.IDLE)
		if (mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
			cached.flags = state.get("flags", 0)

	cached.last_tick_sent = tick
	cached.is_new = false


## Update cache for all entities after a full state broadcast
func update_cache_batch(entities: Array, tick: int) -> void:
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id >= 0:
			update_cache(entity_id, entity_data, tick)


## Mark an entity as removed (no longer tracked)
func mark_entity_removed(entity_id: int) -> void:
	_cache.erase(entity_id)
	if debug_logging:
		print("[DeltaCache] Entity %d removed from cache (peer=%d)" % [entity_id, peer_id])


## Check if entity exists in cache
func has_entity(entity_id: int) -> bool:
	return _cache.has(entity_id)


## Get cached state for an entity (returns null if not cached)
func get_cached_state(entity_id: int) -> CachedEntityState:
	return _cache.get(entity_id, null)


## Reset baseline tick (call after sending full state)
func reset_baseline(tick: int) -> void:
	_baseline_tick = tick
	if debug_logging:
		print("[DeltaCache] Baseline reset to tick %d (peer=%d)" % [tick, peer_id])


## Clear all cached states
func clear() -> void:
	_cache.clear()
	_baseline_tick = 0
	if debug_logging:
		print("[DeltaCache] Cache cleared (peer=%d)" % peer_id)


## Get number of cached entities
func get_entity_count() -> int:
	return _cache.size()


## Get baseline tick
func get_baseline_tick() -> int:
	return _baseline_tick


## Remove entities not in the provided set (cleanup stale entries)
## Returns removed entity IDs so callers can send explicit despawn deltas.
func cleanup_stale_entities(active_entity_ids: Array[int]) -> Array[int]:
	var active_set: Dictionary = {}
	for id in active_entity_ids:
		active_set[id] = true

	var to_remove: Array[int] = []
	for entity_id: int in _cache.keys():
		if not active_set.has(entity_id):
			to_remove.append(entity_id)

	for entity_id in to_remove:
		mark_entity_removed(entity_id)

	return to_remove
#endregion


#region Debug
func get_debug_info() -> Dictionary:
	return {
		"peer_id": peer_id,
		"entity_count": _cache.size(),
		"baseline_tick": _baseline_tick
	}
#endregion
