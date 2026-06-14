## LootPool - A weighted pool of items for one tier/biome.
##
## Holds a set of (item_id, weight) entries and performs the weighted-random pick
## for a single tier/biome bucket. Consumed by LootTable, which selects the right
## pool per (tier, biome). The server is authoritative for real drops — the client
## requests, the server decides; this pool only previews odds and mocks loot
## screens, and must mirror the server's weights to stay honest.
##
## Pattern: Weighted-Random selection. Data-driven (GDD: JSON definition -> Factory
## -> base scene -> configured entity): entries and weights come from a loot JSON
## definition; chosen item ids are realised into item records via ItemGenerator.
##
## Governing docs: docs/gdd/loot.md.
##
## # TODO:
##   - Store entries as parallel item-id / weight arrays (or a records array).
##   - add_entry(): append an (item_id, weight); maintain a cumulative-weight cache.
##   - pick(): weighted-random select using a provided seed/rng (preview only).
class_name LootPool
extends RefCounted


## Register a weighted item entry in this pool.
func add_entry(item_id: String, weight: float) -> void:
	# TODO: append entry; invalidate/extend the cumulative-weight cache.
	pass


## Weighted-random pick of an item id from this pool; "" if empty. Display only.
func pick(seed: int) -> String:
	# TODO: roll against cumulative weights using the seed.
	return ""


## Total weight across all entries (normalisation / odds display).
func total_weight() -> float:
	# TODO: return the summed entry weights.
	return 0.0
