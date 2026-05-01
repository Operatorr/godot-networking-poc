## ServerBroadcastService - Handles state broadcasting and delta compression
## Extracted from ServerMain to isolate network broadcast concerns
class_name ServerBroadcastService
extends RefCounted

const DeltaStateCacheClass = preload("res://scripts/server/delta_state_cache.gd")
const LeaderboardManager := preload("res://scripts/server/leaderboard_manager.gd")

## LOD tier identifiers used for distance-scaled update frequency (TASK-065).
const LOD_NEAR := 0
const LOD_MID := 1
const LOD_FAR := 2

var debug_logging: bool = false

## Leaderboard management
var leaderboard_manager: LeaderboardManager = null

## Delta state caches per client (TASK-021)
var delta_caches: Dictionary = {}  # peer_id -> DeltaStateCache

## Area of Interest radius (0 = disabled, send all entities) (TASK-064)
var aoi_radius: float = 0.0

## AoI exit radius for hysteresis (TASK-064). Once an entity becomes visible to
## a client it stays visible until distance exceeds this larger radius. Prevents
## edge flicker for entities oscillating around aoi_radius. Falls back to
## aoi_radius when set to 0.
var aoi_exit_radius: float = 0.0

## LOD radii for update-frequency scaling (TASK-065). Distances are squared to
## avoid sqrt during the per-entity hot path.
var lod_near_radius_sq: float = 0.0
var lod_mid_radius_sq: float = 0.0

## LOD position-update intervals in ticks for each LOD tier (TASK-065).
## Indexed by LOD_NEAR/LOD_MID/LOD_FAR.
var lod_intervals: Array[int] = [1, 2, 4]

## Per-client visible entity tracking for AoI exit notifications
var client_visible_entities: Dictionary = {}  # peer_id -> Dictionary{entity_id: true}


## Broadcast state updates to all connected clients (delta-compressed, AoI-filtered)
func broadcast_state_updates(
	player_manager: PlayerManager,
	projectile_manager: ProjectileManager,
	monster_manager: MonsterManager,
	network_manager: Node,
	tick_count: int
) -> void:
	if player_manager.get_player_count() == 0:
		return

	if network_manager == null:
		return

	# Collect all entity states
	var all_entities: Array[Dictionary] = []

	for state: PlayerState in player_manager.get_authenticated_players():
		all_entities.append(state.to_entity_data())

	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		all_entities.append(proj_data)

	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		all_entities.append(monster_data)

	# Send delta-compressed updates to each client
	var aoi_enabled := aoi_radius > 0.0
	var aoi_enter_radius_sq := aoi_radius * aoi_radius
	var aoi_exit_sq: float = aoi_exit_radius * aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_enter_radius_sq
	var lod_throttling_enabled := aoi_enabled and (lod_intervals[LOD_MID] > 1 or lod_intervals[LOD_FAR] > 1)

	for state: PlayerState in player_manager.get_authenticated_players():
		var peer_id: int = state.peer_id
		var cache = get_or_create_delta_cache(peer_id)

		# AoI filter (TASK-064): only send entities within hysteresis-aware radius
		# of this client's player. Visible entities are returned alongside a
		# parallel LOD-tier array indexed by position, avoiding the per-entity
		# Dictionary.duplicate() that would otherwise allocate at scale (§7.2 of
		# NETWORK_PERFORMANCE_UPGRADES.md).
		var prev_visible: Dictionary = client_visible_entities.get(peer_id, {})
		var visible_entities: Array[Dictionary]
		var visible_lods: PackedByteArray = PackedByteArray()
		if aoi_enabled:
			var aoi_result: Dictionary = _filter_entities_by_aoi(
				all_entities, state, aoi_enter_radius_sq, aoi_exit_sq, prev_visible, lod_throttling_enabled
			)
			visible_entities = aoi_result.entities
			visible_lods = aoi_result.lods
		else:
			visible_entities = all_entities

		# Track visible entity set for AoI exit cleanup
		var current_visible_ids: Dictionary = {}
		for entity in visible_entities:
			var entity_id: int = entity.get("id", -1)
			if entity_id >= 0:
				current_visible_ids[entity_id] = true

		# Track entities that left AoI so delta packets can explicitly despawn them.
		var removed_entity_ids: Array[int] = []
		if aoi_enabled:
			for eid in prev_visible:
				if not current_visible_ids.has(eid):
					removed_entity_ids.append(int(eid))
		client_visible_entities[peer_id] = current_visible_ids

		var needs_baseline: bool = cache.needs_full_state_for_interval(tick_count)

		var packet_data: Dictionary
		if needs_baseline and removed_entity_ids.is_empty():
			packet_data = _create_full_state_packet(visible_entities, cache, tick_count)
		else:
			packet_data = _create_delta_packet(visible_entities, cache, tick_count, removed_entity_ids, lod_throttling_enabled, visible_lods)

		network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)


## Filter entities by Area of Interest with hysteresis (TASK-064). Entities
## already visible to this client must travel beyond `exit_radius_sq` to drop
## out, while new entries must come within the tighter `enter_radius_sq` to
## appear. Returns `{entities, lods}` where `lods[i]` is the LOD tier for
## `entities[i]`, avoiding a per-entity Dictionary.duplicate() in the hot path.
func _filter_entities_by_aoi(
	all_entities: Array[Dictionary],
	player: PlayerState,
	enter_radius_sq: float,
	exit_radius_sq: float,
	prev_visible: Dictionary,
	tag_lod: bool
) -> Dictionary:
	var entities: Array[Dictionary] = []
	var lods: PackedByteArray = PackedByteArray()
	var player_pos := player.position
	var player_eid: int = player.entity_id

	for entity in all_entities:
		var eid: int = entity.get("id", -1)
		# Always include self - the local player must never be culled.
		if eid == player_eid:
			entities.append(entity)
			if tag_lod:
				lods.append(LOD_NEAR)
			continue

		var entity_pos: Vector2 = entity.get("position", Vector2.ZERO)
		var dist_sq := player_pos.distance_squared_to(entity_pos)
		var threshold_sq := exit_radius_sq if prev_visible.has(eid) else enter_radius_sq
		if dist_sq > threshold_sq:
			continue

		entities.append(entity)
		if tag_lod:
			lods.append(_classify_lod(dist_sq))

	return {"entities": entities, "lods": lods}


## Classify an entity's LOD tier from its squared distance to the viewer.
func _classify_lod(dist_sq: float) -> int:
	if lod_near_radius_sq > 0.0 and dist_sq <= lod_near_radius_sq:
		return LOD_NEAR
	if lod_mid_radius_sq > 0.0 and dist_sq <= lod_mid_radius_sq:
		return LOD_MID
	return LOD_FAR


## Decide whether to emit a position-only delta for an entity at the given LOD
## tier this tick. Spreads the load across ticks using `entity_id` as an
## offset so all FAR entities don't bunch up on the same tick.
func _should_send_position_for_lod(entity_id: int, tick: int, lod: int) -> bool:
	var interval: int = lod_intervals[lod] if lod >= 0 and lod < lod_intervals.size() else 1
	if interval <= 1:
		return true
	return ((tick + entity_id) % interval) == 0


## Handle client request for full state sync
func handle_full_state_request(
	peer_id: int,
	player_manager: PlayerManager,
	projectile_manager: ProjectileManager,
	monster_manager: MonsterManager,
	network_manager: Node,
	tick_count: int
) -> void:
	if debug_logging:
		print("[BroadcastService] Full state request from peer %d" % peer_id)

	if network_manager == null:
		return

	var all_entities: Array[Dictionary] = []

	for state: PlayerState in player_manager.get_authenticated_players():
		all_entities.append(state.to_entity_data())

	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		all_entities.append(proj_data)

	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		all_entities.append(monster_data)

	var cache = get_or_create_delta_cache(peer_id)
	var packet_data = _create_full_state_packet(all_entities, cache, tick_count)

	network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)

	# Re-issue PLAYER_INFO for every authenticated player, including the
	# requester. This is the recovery path when the initial PLAYER_INFO was
	# missed (e.g. arrived before the client's listener was bound), and it is
	# what lets the client (re)discover its own entity_id.
	for state: PlayerState in player_manager.get_authenticated_players():
		var event_packet = GameEventPacket.create_player_info(
			state.entity_id,
			state.character_name,
			state.position,
			state.player_color
		)
		network_manager.send_to_client(
			peer_id,
			NetworkManager.MessageType.GAME_EVENT,
			event_packet.to_dict()
		)

	if debug_logging:
		print("[BroadcastService] Sent full state to peer %d (%d entities)" % [peer_id, all_entities.size()])


## Broadcast leaderboard update to all clients
func broadcast_leaderboard(player_manager: PlayerManager, network_manager: Node) -> void:
	if network_manager == null:
		return

	var entries: Array
	if leaderboard_manager:
		entries = leaderboard_manager.get_top_n(10)
	else:
		# Fallback: collect from player states directly
		var players := player_manager.get_authenticated_players()
		entries = []
		for state: PlayerState in players:
			entries.append({"entity_id": state.entity_id, "pvp_kills": state.pvp_kills})
		entries.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
			var a_kills := int(a.get("pvp_kills", 0))
			var b_kills := int(b.get("pvp_kills", 0))
			if a_kills == b_kills:
				return int(a.get("entity_id", 0)) < int(b.get("entity_id", 0))
			return a_kills > b_kills
		)
		if entries.size() > 10:
			entries.resize(10)

	var packet = GameEventPacket.create_leaderboard_update(entries)
	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		packet.to_dict()
	)


## Broadcast PLAYER_INFO event for a specific player to all clients
func broadcast_player_info(peer_id: int, player_manager: PlayerManager, network_manager: Node) -> void:
	var state = player_manager.get_player(peer_id)
	if state == null:
		return

	if network_manager == null:
		return

	var event_packet = GameEventPacket.create_player_info(
		state.entity_id,
		state.character_name,
		state.position,
		state.player_color
	)

	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		event_packet.to_dict()
	)


## Send PLAYER_INFO for all existing players to a newly connected client
func send_all_player_info_to_client(peer_id: int, player_manager: PlayerManager, network_manager: Node) -> void:
	if network_manager == null:
		return

	for state: PlayerState in player_manager.get_all_players():
		if not state.authenticated:
			continue
		if state.peer_id == peer_id:
			continue  # Skip self

		var event_packet = GameEventPacket.create_player_info(
			state.entity_id,
			state.character_name,
			state.position,
			state.player_color
		)

		network_manager.send_to_client(
			peer_id,
			NetworkManager.MessageType.GAME_EVENT,
			event_packet.to_dict()
		)


## Get or create delta cache for a client
func get_or_create_delta_cache(peer_id: int):
	if not delta_caches.has(peer_id):
		delta_caches[peer_id] = DeltaStateCacheClass.create_for_client(peer_id)
		delta_caches[peer_id].debug_logging = debug_logging
	return delta_caches[peer_id]


## Remove delta cache for a disconnected client
func remove_delta_cache(peer_id: int) -> void:
	delta_caches.erase(peer_id)
	client_visible_entities.erase(peer_id)


## Clear all delta caches
func clear_all_caches() -> void:
	delta_caches.clear()
	client_visible_entities.clear()


## Create a full state (baseline) packet
func _create_full_state_packet(entities: Array[Dictionary], cache, tick_count: int) -> Dictionary:
	var entity_data: Array[Dictionary] = []

	for entity in entities:
		var entity_id: int = entity.get("id", -1)
		if entity_id < 0:
			continue

		entity_data.append({
			"entity_id": entity_id,
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0),
			"delta_mask": PacketTypes.DELTA_MASK_FULL_STATE
		})

		cache.update_cache(entity_id, {
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0)
		}, tick_count)

	cache.reset_baseline(tick_count)

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"baseline_tick": tick_count,
		"entities": entity_data
	}


## Create a delta-compressed packet
func _create_delta_packet(
	entities: Array[Dictionary],
	cache,
	tick_count: int,
	removed_entity_ids: Array[int] = [],
	lod_throttling_enabled: bool = false,
	lod_tiers: PackedByteArray = PackedByteArray()
) -> Dictionary:
	var entity_data: Array[Dictionary] = []
	var active_entity_ids: Array[int] = []
	var removed_set: Dictionary = {}

	for entity_id in removed_entity_ids:
		if entity_id < 0:
			continue
		removed_set[entity_id] = true
		entity_data.append({
			"entity_id": entity_id,
			"delta_mask": PacketTypes.DELTA_MASK_REMOVED
		})

	var has_lod_tiers := lod_tiers.size() == entities.size()

	for i in entities.size():
		var entity: Dictionary = entities[i]
		var entity_id: int = entity.get("id", -1)
		if entity_id < 0:
			continue

		active_entity_ids.append(entity_id)

		var current_state := {
			"entity_type": entity.get("type", PacketTypes.EntityType.PLAYER),
			"position": entity.get("position", Vector2.ZERO),
			"animation_state": entity.get("animation", PacketTypes.AnimationState.IDLE),
			"flags": entity.get("flags", 0)
		}

		var delta_mask: int = cache.calculate_delta_mask(entity_id, current_state, tick_count)

		if delta_mask == 0:
			continue

		# TASK-065: Throttle position-only deltas for distant entities. State
		# transitions (animation/flag changes), full-state syncs, and brand-new
		# spawns are never throttled because they carry visible game events.
		if lod_throttling_enabled and (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) == 0:
			var lod: int = lod_tiers[i] if has_lod_tiers else LOD_NEAR
			if (delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0 \
					and not _should_send_position_for_lod(entity_id, tick_count, lod):
				delta_mask &= ~PacketTypes.DELTA_MASK_POSITION
				if delta_mask == 0:
					continue

		entity_data.append({
			"entity_id": entity_id,
			"entity_type": current_state.entity_type,
			"position": current_state.position,
			"animation_state": current_state.animation_state,
			"flags": current_state.flags,
			"delta_mask": delta_mask
		})

		# Use mask-aware update so a throttled position bit keeps the cache
		# dirty for the next eligible tick (otherwise we would clobber the
		# previously-cached value and never resend the missed move).
		cache.update_cache_partial(entity_id, current_state, delta_mask, tick_count)

	var stale_entity_ids: Array[int] = cache.cleanup_stale_entities(active_entity_ids)
	for entity_id in stale_entity_ids:
		if removed_set.has(entity_id):
			continue
		entity_data.append({
			"entity_id": entity_id,
			"delta_mask": PacketTypes.DELTA_MASK_REMOVED
		})

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"baseline_tick": cache.get_baseline_tick(),
		"entities": entity_data
	}
