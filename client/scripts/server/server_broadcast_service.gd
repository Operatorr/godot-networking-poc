## ServerBroadcastService - Handles state broadcasting and delta compression
## Extracted from ServerMain to isolate network broadcast concerns
class_name ServerBroadcastService
extends RefCounted

const DeltaStateCacheClass = preload("res://scripts/server/delta_state_cache.gd")

var debug_logging: bool = false

## Leaderboard management
var leaderboard_manager: LeaderboardManager = null

## Delta state caches per client (TASK-021)
var delta_caches: Dictionary = {}  # peer_id -> DeltaStateCache


## Broadcast state updates to all connected clients (delta-compressed)
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

	for state: PlayerState in player_manager.get_all_players():
		all_entities.append(state.to_entity_data())

	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		all_entities.append(proj_data)

	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		all_entities.append(monster_data)

	# Send delta-compressed updates to each client
	for state: PlayerState in player_manager.get_all_players():
		var peer_id: int = state.peer_id
		var cache = get_or_create_delta_cache(peer_id)

		var needs_baseline: bool = cache.needs_full_state_for_interval(tick_count)

		var packet_data: Dictionary
		if needs_baseline:
			packet_data = _create_full_state_packet(all_entities, cache, tick_count)
		else:
			packet_data = _create_delta_packet(all_entities, cache, tick_count)

		network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)


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

	for state: PlayerState in player_manager.get_all_players():
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
		var players := player_manager.get_all_players()
		entries = []
		for state: PlayerState in players:
			entries.append({"entity_id": state.entity_id, "pvp_kills": state.pvp_kills})
		entries.sort_custom(func(a, b): return a.pvp_kills > b.pvp_kills)
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
		state.character_name
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
		if state.peer_id == peer_id:
			continue  # Skip self

		var event_packet = GameEventPacket.create_player_info(
			state.entity_id,
			state.character_name
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


## Clear all delta caches
func clear_all_caches() -> void:
	delta_caches.clear()


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
func _create_delta_packet(entities: Array[Dictionary], cache, tick_count: int) -> Dictionary:
	var entity_data: Array[Dictionary] = []
	var active_entity_ids: Array[int] = []

	for entity in entities:
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

		entity_data.append({
			"entity_id": entity_id,
			"entity_type": current_state.entity_type,
			"position": current_state.position,
			"animation_state": current_state.animation_state,
			"flags": current_state.flags,
			"delta_mask": delta_mask
		})

		cache.update_cache(entity_id, current_state, tick_count)

	cache.cleanup_stale_entities(active_entity_ids)

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"baseline_tick": cache.get_baseline_tick(),
		"entities": entity_data
	}
