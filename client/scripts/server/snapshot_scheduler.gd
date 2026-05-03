## SnapshotScheduler - Per-peer priority queue for delta-snapshot entity selection
##
## Replaces the modulo-based LOD throttling with a budget-driven scheduler
## (NETWORK_PERFORMANCE_UPGRADES.md §1.2). Each delta packet asks the scheduler
## which entities fit inside the per-snapshot byte budget; entities that do not
## fit accrue staleness and bubble up next tick, so no entity starves.
##
## Priority formula (per-entity, per-tick):
##   priority = importance(entity_type)
##            + ticks_since_last_sent
##            - distance_penalty(lod_tier)
##            + change_bonus(delta_mask)
##
## Pinned candidates (removals, AoI exits, cache cleanup) bypass the budget
## because dropping them would leave clients with stale entities that can only
## recover on the next baseline tick.
class_name SnapshotScheduler
extends RefCounted

const PRIORITY_PLAYER := 10
const PRIORITY_PROJECTILE := 8
const PRIORITY_MONSTER := 4
const PRIORITY_DEFAULT := 1

## Distance penalty by LOD tier (NEAR=0, MID=1, FAR=2). Read positionally.
const DISTANCE_PENALTY_BY_LOD: Array[int] = [0, 4, 8]


class Candidate extends RefCounted:
	var index: int = -1                  ## Caller-assigned key (e.g. entity-list index)
	var entity_id: int = 0
	var entity_type: int = 0
	var lod_tier: int = 0
	var delta_mask: int = 0
	var encoded_size: int = 0
	var ticks_since_last_sent: int = 0
	var priority: int = 0
	## Pinned candidates always make the cut. Use for removals / despawns whose
	## loss would orphan an entity on the client until the next baseline.
	var pinned: bool = false


class Result extends RefCounted:
	var selected_indices: PackedInt32Array = PackedInt32Array()
	var candidate_count: int = 0
	var deferred_count: int = 0
	var max_queue_age_ticks: int = 0
	var bytes_used: int = 0
	var hit_budget: bool = false


var _candidates: Array[Candidate] = []


## Clear scheduler state between ticks. Reuses Candidate objects via the array
## resize so we keep the per-peer allocation flat.
func reset() -> void:
	_candidates.clear()


## Register an entity as a candidate for this tick's snapshot.
func add_candidate(
	index: int,
	entity_id: int,
	entity_type: int,
	lod_tier: int,
	delta_mask: int,
	encoded_size: int,
	ticks_since_last_sent: int,
	pinned: bool = false
) -> void:
	var c := Candidate.new()
	c.index = index
	c.entity_id = entity_id
	c.entity_type = entity_type
	c.lod_tier = lod_tier
	c.delta_mask = delta_mask
	c.encoded_size = encoded_size
	c.ticks_since_last_sent = maxi(0, ticks_since_last_sent)
	c.pinned = pinned
	c.priority = compute_priority(entity_type, lod_tier, c.ticks_since_last_sent, delta_mask)
	_candidates.append(c)


## Run the scheduler. Returns selected indices in priority order plus the
## diagnostics needed by §8.2.
func schedule(max_bytes: int) -> Result:
	_candidates.sort_custom(_compare_priority)

	var result := Result.new()
	result.candidate_count = _candidates.size()
	var bytes := 0

	for c in _candidates:
		if c.ticks_since_last_sent > result.max_queue_age_ticks:
			result.max_queue_age_ticks = c.ticks_since_last_sent

		var fits := max_bytes <= 0 or bytes + c.encoded_size <= max_bytes
		if c.pinned or fits:
			result.selected_indices.append(c.index)
			bytes += c.encoded_size
		else:
			result.deferred_count += 1
			result.hit_budget = true

	result.bytes_used = bytes
	return result


## Sort comparator: priority descending, entity_id ascending as tiebreaker.
static func _compare_priority(a: Candidate, b: Candidate) -> bool:
	if a.priority != b.priority:
		return a.priority > b.priority
	return a.entity_id < b.entity_id


static func compute_priority(
	entity_type: int,
	lod_tier: int,
	ticks_since_last_sent: int,
	delta_mask: int
) -> int:
	return importance(entity_type) \
		+ ticks_since_last_sent \
		- distance_penalty(lod_tier) \
		+ change_bonus(delta_mask)


static func importance(entity_type: int) -> int:
	match entity_type:
		PacketTypes.EntityType.PLAYER: return PRIORITY_PLAYER
		PacketTypes.EntityType.PROJECTILE: return PRIORITY_PROJECTILE
		PacketTypes.EntityType.MONSTER: return PRIORITY_MONSTER
	return PRIORITY_DEFAULT


static func distance_penalty(lod_tier: int) -> int:
	if lod_tier >= 0 and lod_tier < DISTANCE_PENALTY_BY_LOD.size():
		return DISTANCE_PENALTY_BY_LOD[lod_tier]
	return 0


static func change_bonus(delta_mask: int) -> int:
	if (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0:
		return 6
	if (delta_mask & PacketTypes.DELTA_MASK_REMOVED) != 0:
		return 6
	var bonus := 0
	if (delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
		bonus += 2
	if (delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
		bonus += 2
	if (delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
		bonus += 2
	return bonus


## Predict the on-wire size of a delta entry given its delta_mask. Mirrors the
## logic in `state_update_packet.gd::_get_delta_entity_size` so the scheduler
## can budget without speculatively encoding.
static func encoded_size_for_mask(delta_mask: int) -> int:
	if (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0:
		return 10  # id(2) + mask(1) + type(1) + pos(4) + anim(1) + flags(1)
	if (delta_mask & PacketTypes.DELTA_MASK_REMOVED) != 0:
		return 3   # id(2) + mask(1)
	var size := 3
	if (delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0:
		size += 4
	if (delta_mask & PacketTypes.DELTA_MASK_ANIMATION) != 0:
		size += 1
	if (delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0:
		size += 1
	return size
