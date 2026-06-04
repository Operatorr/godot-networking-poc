## ServerBroadcastService - Handles state broadcasting and delta compression
## Extracted from ServerMain to isolate network broadcast concerns
class_name ServerBroadcastService
extends RefCounted

const DeltaStateCacheClass = preload("res://scripts/server/delta_state_cache.gd")
const LeaderboardManager := preload("res://scripts/server/leaderboard_manager.gd")
const SnapshotSchedulerClass := preload("res://scripts/server/snapshot_scheduler.gd")

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

## Per-client visible entity tracking for AoI exit notifications
var client_visible_entities: Dictionary = {}  # peer_id -> Dictionary{entity_id: true}

## Per-snapshot byte budget for the priority scheduler (§1.2). 0 disables the
## budget so the scheduler still sorts but never defers.
var max_snapshot_bytes: int = 1200

## Per-peer SnapshotScheduler instances. Created lazily alongside delta caches.
var snapshot_schedulers: Dictionary = {}  # peer_id -> SnapshotScheduler

## Per-peer resolved snapshot byte cap (#13), set at auth from the client's
## advertised bandwidth budget. Unset peers fall back to the service-global
## `max_snapshot_bytes` via `_budget_for_peer` (NEVER 0 — see snapshot_scheduler.gd
## where max_bytes<=0 disables the budget instead of tightening it).
var peer_snapshot_bytes: Dictionary = {}  # peer_id -> int

## Shared current-tick AoI broad-phase (#9). Rebuilt once per tick by
## `build_aoi_grid` from final entity positions, then queried per peer so the
## AoI scan touches O(entities-in-band) instead of O(all entities). Holds the
## same entity-data list broadcast assembles, so it is built only once.
var _tick_entities: Array[Dictionary] = []
var _tick_grid: SpatialGrid = null

## Diagnostics published from the most recent broadcast tick. ServerMain reads
## these into ServerMetrics for the SERVER_METRICS broadcast (§8.2).
var last_tick_diagnostics: Dictionary = {
	"entities_deferred_per_tick": 0,
	"max_queue_age_ticks": 0,
	"peers_at_budget_pct": 0,
	"peers_evaluated": 0,
	"snapshot_count_overflow": 0
}


## Build the shared current-tick entity list + spatial broad-phase grid once per
## tick (#9). Called from ServerMain after all positions are final and before
## broadcast. Stashes both on `_tick_entities` / `_tick_grid` so the per-peer AoI
## scan queries the grid instead of re-walking every entity. Cell size is
## aoi_exit_radius/4 so the grid stays cheap (few large cells); queries use the
## exit radius so hysteresis-retained entities are never missed. Returns the
## grid for convenience. Skips work when there are no players (broadcast
## early-returns in that case anyway).
func build_aoi_grid(
	player_manager: PlayerManager,
	projectile_manager: ProjectileManager,
	monster_manager: MonsterManager
) -> SpatialGrid:
	var entities: Array[Dictionary] = []

	for state: PlayerState in player_manager.get_authenticated_players():
		entities.append(state.to_entity_data())

	var projectile_updates = projectile_manager.collect_state_updates()
	for proj_data in projectile_updates:
		entities.append(proj_data)

	var monster_updates = monster_manager.collect_state_updates()
	for monster_data in monster_updates:
		entities.append(monster_data)

	_tick_entities = entities

	# Cell size = aoi_exit_radius/4 (the roadmap's aoi_radius/4 hint, sized off the
	# larger exit radius). Fall back to a sane default when AoI is disabled.
	var effective_exit: float = aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_radius
	var cell: float = effective_exit / 4.0 if effective_exit > 0.0 else 256.0
	_tick_grid = SpatialGrid.new(cell)
	for entity in entities:
		_tick_grid.insert(entity, entity.get("position", Vector2.ZERO))

	return _tick_grid


## Broadcast state updates to all connected clients (delta-compressed, AoI-filtered).
## Consumes the shared entity list + grid built this tick by `build_aoi_grid`.
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

	# Shared entity list + broad-phase grid assembled this tick (#9). Fall back to
	# building inline if ServerMain hasn't primed them (defensive — keeps this
	# callable standalone).
	if _tick_grid == null:
		build_aoi_grid(player_manager, projectile_manager, monster_manager)
	var all_entities: Array[Dictionary] = _tick_entities

	# Send delta-compressed updates to each client
	var aoi_enabled := aoi_radius > 0.0
	var aoi_enter_radius_sq := aoi_radius * aoi_radius
	var aoi_exit_sq: float = aoi_exit_radius * aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_enter_radius_sq

	# Reset per-tick scheduler diagnostics (§8.2). Aggregated below as each peer
	# is processed; surfaced via `last_tick_diagnostics` for ServerMetrics.
	var tick_total_deferred := 0
	var tick_max_queue_age := 0
	var tick_peers_at_budget := 0
	var tick_peers_evaluated := 0

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
			# Narrow to the grid's exit-radius candidate band (#9) instead of
			# walking every entity. Query the EXIT radius (the larger one) so
			# hysteresis-retained entities up to aoi_exit_radius are never missed;
			# the exact distance + hysteresis check stays in the filter below.
			var candidates: Array = _tick_grid.query_radius(state.position, aoi_exit_radius if aoi_exit_radius > aoi_radius else aoi_radius)
			# `tag_lod` is always true under AoI: the scheduler uses LOD tiers
			# as the distance penalty in priority calculation (§1.2).
			var aoi_result: Dictionary = _filter_entities_by_aoi(
				candidates, state, aoi_enter_radius_sq, aoi_exit_sq, prev_visible, true
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

		# Force a full-state Baseline on the 100-tick cadence FLOOR (never drop this —
		# non-acking clients/bots rely on it) OR proactively when a prior Baseline went
		# un-acked past the timeout (#14, inert on TCP, meaningful under #12 UDP).
		var needs_baseline: bool = cache.needs_full_state_for_interval(tick_count) or cache.needs_baseline_resend(tick_count)

		var packet_data: Dictionary
		if needs_baseline and removed_entity_ids.is_empty():
			packet_data = _create_full_state_packet(visible_entities, cache, tick_count)
		else:
			var scheduler := get_or_create_scheduler(peer_id)
			var sched_stats: Dictionary = {}
			# Per-peer byte cap (#13). Falls back to the service-global default for
			# peers with no advertised budget (never 0 — that would disable the cap).
			var peer_max := _budget_for_peer(peer_id)
			packet_data = _create_delta_packet(
				visible_entities,
				cache,
				tick_count,
				removed_entity_ids,
				visible_lods,
				scheduler,
				sched_stats,
				peer_max
			)
			tick_peers_evaluated += 1
			tick_total_deferred += int(sched_stats.get("deferred", 0))
			var age: int = int(sched_stats.get("max_queue_age", 0))
			if age > tick_max_queue_age:
				tick_max_queue_age = age
			if bool(sched_stats.get("hit_budget", false)):
				tick_peers_at_budget += 1

		network_manager.send_to_client(peer_id, NetworkManager.MessageType.STATE_UPDATE, packet_data)

	last_tick_diagnostics.entities_deferred_per_tick = tick_total_deferred
	last_tick_diagnostics.max_queue_age_ticks = tick_max_queue_age
	last_tick_diagnostics.peers_evaluated = tick_peers_evaluated
	last_tick_diagnostics.peers_at_budget_pct = (
		int(round(100.0 * float(tick_peers_at_budget) / float(tick_peers_evaluated)))
		if tick_peers_evaluated > 0 else 0
	)


## Filter entities by Area of Interest with hysteresis (TASK-064). Entities
## already visible to this client must travel beyond `exit_radius_sq` to drop
## out, while new entries must come within the tighter `enter_radius_sq` to
## appear. Returns `{entities, lods}` where `lods[i]` is the LOD tier for
## `entities[i]`, avoiding a per-entity Dictionary.duplicate() in the hot path.
func _filter_entities_by_aoi(
	candidates: Array,
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
	var self_seen := false

	for entity in candidates:
		var eid: int = entity.get("id", -1)
		# Always include self - the local player must never be culled.
		if eid == player_eid:
			entities.append(entity)
			if tag_lod:
				lods.append(LOD_NEAR)
			self_seen = true
			continue

		var entity_pos: Vector2 = entity.get("position", Vector2.ZERO)
		var dist_sq := player_pos.distance_squared_to(entity_pos)
		var threshold_sq := exit_radius_sq if prev_visible.has(eid) else enter_radius_sq
		if dist_sq > threshold_sq:
			continue

		entities.append(entity)
		if tag_lod:
			lods.append(_classify_lod(dist_sq))

	# Self-inclusion safety net (#9): the grid query is centred on the player, so
	# self is normally in `candidates` — but on a cell-edge with radius rounding
	# it could be excluded. Re-append from the authoritative player state so the
	# local player is never culled from its own snapshot.
	if not self_seen:
		entities.append(player.to_entity_data())
		if tag_lod:
			lods.append(LOD_NEAR)

	return {"entities": entities, "lods": lods}


## Classify an entity's LOD tier from its squared distance to the viewer.
func _classify_lod(dist_sq: float) -> int:
	if lod_near_radius_sq > 0.0 and dist_sq <= lod_near_radius_sq:
		return LOD_NEAR
	if lod_mid_radius_sq > 0.0 and dist_sq <= lod_mid_radius_sq:
		return LOD_MID
	return LOD_FAR


## Get or lazily create the snapshot scheduler for a given peer (§1.2).
func get_or_create_scheduler(peer_id: int) -> SnapshotSchedulerClass:
	if not snapshot_schedulers.has(peer_id):
		snapshot_schedulers[peer_id] = SnapshotSchedulerClass.new()
	return snapshot_schedulers[peer_id]


## Register the resolved per-peer snapshot byte cap (#13). Set at auth from the
## client's advertised bandwidth budget; ServerMain owns the snapshot rate.
func set_peer_byte_budget(peer_id: int, bytes: int) -> void:
	peer_snapshot_bytes[peer_id] = maxi(0, bytes)


## Resolve the snapshot byte cap for a peer (#13). Falls back to the service-global
## `max_snapshot_bytes` for unset peers (legacy / no-advert path). MUST NOT return 0
## for an unset peer: the scheduler treats max_bytes<=0 as "no budget, admit all",
## which would DISABLE the cap instead of applying the global default.
func _budget_for_peer(peer_id: int) -> int:
	return peer_snapshot_bytes.get(peer_id, max_snapshot_bytes)


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


## Record a client's Baseline acknowledgement (#14). On TCP this is informational
## (baselines are never dropped); under #12 UDP transport it lets the broadcast loop
## resend a lost Baseline before the 100-tick cadence floor.
func handle_baseline_ack(peer_id: int, acked_baseline_tick: int) -> void:
	var cache = delta_caches.get(peer_id, null)
	if cache == null:
		return
	cache.mark_baseline_acked(acked_baseline_tick)
	if debug_logging:
		print("[BroadcastService] peer %d acked baseline tick %d" % [peer_id, acked_baseline_tick])


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
	snapshot_schedulers.erase(peer_id)
	peer_snapshot_bytes.erase(peer_id)


## Clear all delta caches
func clear_all_caches() -> void:
	delta_caches.clear()
	client_visible_entities.clear()
	snapshot_schedulers.clear()
	peer_snapshot_bytes.clear()


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

	# A full-state baseline is bounded by MAX_PACKET_SIZE (the [u16 length] frame),
	# NOT by the u16 entity_count field — the writer truncates anything past the
	# byte-safe cap, so flag the limit that actually binds (#15). Baselines bypass
	# the per-peer snapshot byte budget, so this is the only overflow path.
	if entity_data.size() > StateUpdatePacket.STATE_MAX_FULL_ENTITIES:
		last_tick_diagnostics.snapshot_count_overflow += 1
		push_warning("[BroadcastService] Full-state entity count %d exceeds per-frame cap %d (MAX_PACKET_SIZE); overflow truncated" % [entity_data.size(), StateUpdatePacket.STATE_MAX_FULL_ENTITIES])

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"baseline_tick": tick_count,
		"entities": entity_data
	}


## Create a delta-compressed packet, using the priority scheduler (§1.2) to
## stay within `max_snapshot_bytes`. Removed entities (AoI exits and stale
## cache entries) are pinned so a client never loses an entity it had been
## tracking; everything else is sorted by priority and fits as budget allows.
func _create_delta_packet(
	entities: Array[Dictionary],
	cache,
	tick_count: int,
	removed_entity_ids: Array[int],
	lod_tiers: PackedByteArray,
	scheduler: SnapshotSchedulerClass,
	out_stats: Dictionary,
	peer_max_bytes: int
) -> Dictionary:
	scheduler.reset()

	# Pre-compute every candidate entry. We stage them in a parallel array so
	# the scheduler can address them by index after sorting.
	var staged: Array[Dictionary] = []
	var has_lod_tiers := lod_tiers.size() == entities.size()
	var active_entity_ids: Array[int] = []
	var removed_set: Dictionary = {}

	# Removed entries (AoI exits) — pinned, scheduler always emits.
	for entity_id in removed_entity_ids:
		if entity_id < 0:
			continue
		removed_set[entity_id] = true
		var idx := staged.size()
		staged.append({
			"entity_id": entity_id,
			"delta_mask": PacketTypes.DELTA_MASK_REMOVED,
		})
		scheduler.add_candidate(
			idx,
			entity_id,
			PacketTypes.EntityType.PLAYER,
			LOD_NEAR,
			PacketTypes.DELTA_MASK_REMOVED,
			SnapshotSchedulerClass.encoded_size_for_mask(PacketTypes.DELTA_MASK_REMOVED),
			0,
			true
		)

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

		var lod: int = lod_tiers[i] if has_lod_tiers else LOD_NEAR
		var cached_state = cache.get_cached_state(entity_id)
		var ticks_since_last := tick_count - int(cached_state.last_tick_sent) if cached_state else tick_count

		var idx := staged.size()
		staged.append({
			"entity_id": entity_id,
			"entity_type": current_state.entity_type,
			"position": current_state.position,
			"animation_state": current_state.animation_state,
			"flags": current_state.flags,
			"delta_mask": delta_mask,
			# Track for cache update after scheduling resolves.
			"_current_state": current_state,
		})
		scheduler.add_candidate(
			idx,
			entity_id,
			int(current_state.entity_type),
			lod,
			delta_mask,
			SnapshotSchedulerClass.encoded_size_for_mask(delta_mask),
			ticks_since_last,
			false
		)

	# Stale cache entries become explicit despawn deltas. Pinned for the same
	# reason as AoI exits: dropping them strands an entity on the client.
	var stale_entity_ids: Array[int] = cache.cleanup_stale_entities(active_entity_ids)
	for entity_id in stale_entity_ids:
		if removed_set.has(entity_id):
			continue
		var idx := staged.size()
		staged.append({
			"entity_id": entity_id,
			"delta_mask": PacketTypes.DELTA_MASK_REMOVED,
		})
		scheduler.add_candidate(
			idx,
			entity_id,
			PacketTypes.EntityType.PLAYER,
			LOD_NEAR,
			PacketTypes.DELTA_MASK_REMOVED,
			SnapshotSchedulerClass.encoded_size_for_mask(PacketTypes.DELTA_MASK_REMOVED),
			0,
			true
		)

	var result: SnapshotSchedulerClass.Result = scheduler.schedule(peer_max_bytes)

	var entity_data: Array[Dictionary] = []
	for idx in result.selected_indices:
		var entry: Dictionary = staged[idx]
		# Update the cache only for the entries that actually went out — deferred
		# entities keep their stale cache entry so they re-priority next tick.
		if entry.has("_current_state"):
			cache.update_cache_partial(
				entry.entity_id,
				entry["_current_state"],
				int(entry.delta_mask),
				tick_count
			)
			entry.erase("_current_state")
		entity_data.append(entry)

	out_stats["deferred"] = result.deferred_count
	out_stats["max_queue_age"] = result.max_queue_age_ticks
	out_stats["bytes_used"] = result.bytes_used
	out_stats["hit_budget"] = result.hit_budget
	out_stats["candidates"] = result.candidate_count

	return {
		"tick": tick_count,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"baseline_tick": cache.get_baseline_tick(),
		"entities": entity_data
	}
