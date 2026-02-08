## LeaderboardManager - Server-side leaderboard tracking
## Tracks PvP kills per player, maintains sorted top-10 leaderboard
## In-memory only (no persistence for POC)
class_name LeaderboardManager
extends RefCounted


class LeaderboardEntry:
	var entity_id: int = 0
	var pvp_kills: int = 0
	var deaths: int = 0

	func _init(id: int = 0) -> void:
		entity_id = id


## All tracked player entries: entity_id -> LeaderboardEntry
var _entries: Dictionary = {}

## Cached sorted top-10 (rebuilt on each kill)
var _top_entries: Array = []

## Debug logging
var debug_logging: bool = false


## Record a PvP kill and rebuild the leaderboard
## Returns the top-10 entries for broadcast
func record_pvp_kill(killer_id: int, victim_id: int) -> Array:
	var killer_entry := _find_or_create_entry(killer_id)
	killer_entry.pvp_kills += 1

	var victim_entry := _find_or_create_entry(victim_id)
	victim_entry.deaths += 1

	_rebuild_top_entries()

	if debug_logging:
		print("[LeaderboardManager] PvP kill: %d killed %d (killer_kills=%d)" % [
			killer_id, victim_id, killer_entry.pvp_kills
		])

	return get_top_n(10)


## Get top N players sorted by pvp_kills descending
func get_top_n(count: int) -> Array:
	var result: Array = []
	var limit := mini(count, _top_entries.size())
	for i in limit:
		var entry: LeaderboardEntry = _top_entries[i]
		result.append({
			"entity_id": entry.entity_id,
			"pvp_kills": entry.pvp_kills
		})
	return result


## Register a player (call when player joins)
func register_player(entity_id: int) -> void:
	_find_or_create_entry(entity_id)


## Remove a player (call when player disconnects)
func remove_player(entity_id: int) -> void:
	_entries.erase(entity_id)
	_rebuild_top_entries()


## Get a player's kill count
func get_kills(entity_id: int) -> int:
	if _entries.has(entity_id):
		return (_entries[entity_id] as LeaderboardEntry).pvp_kills
	return 0


## Get a player's death count
func get_deaths(entity_id: int) -> int:
	if _entries.has(entity_id):
		return (_entries[entity_id] as LeaderboardEntry).deaths
	return 0


## Clear all entries
func clear() -> void:
	_entries.clear()
	_top_entries.clear()


func _find_or_create_entry(entity_id: int) -> LeaderboardEntry:
	if not _entries.has(entity_id):
		_entries[entity_id] = LeaderboardEntry.new(entity_id)
	return _entries[entity_id]


func _rebuild_top_entries() -> void:
	_top_entries = _entries.values()
	_top_entries.sort_custom(func(a: LeaderboardEntry, b: LeaderboardEntry):
		return a.pvp_kills > b.pvp_kills
	)
