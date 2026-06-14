## LootTable - Tier + biome-gated drop table (display/preview only).
##
## Resolves which LootPool applies for a given content tier and biome, then asks
## that pool for a weighted-random drop preview. The server is authoritative for
## actual drops — the client requests, the server decides; this table exists to
## preview reward odds and mock loot screens, and to mirror server probabilities.
##
## Patterns: Strategy (tier/biome selects which pool/strategy resolves the drop) +
## Weighted-Random (the chosen pool rolls by weight). Data-driven (GDD: JSON
## definition -> Factory -> base scene -> configured entity): tier/biome gates and
## pool references come from a loot JSON definition; rolled item ids are realised
## into item records via ItemGenerator.
##
## Governing docs: docs/gdd/loot.md, docs/gdd/MONSTERS.md (tier/biome sourcing).
##
## TODO:
##   - Load tier/biome -> LootPool mapping from the loot JSON definition.
##   - resolve_pool(): pick the pool for (tier, biome) via the Strategy.
##   - roll(): delegate to the selected LootPool's weighted-random pick (preview).
class_name LootTable
extends RefCounted


## Select the LootPool gating a (tier, biome) pair. Returns null if none applies.
func resolve_pool(tier: int, biome: String) -> LootPool:
	# TODO: look up the tier/biome -> pool mapping from JSON.
	return null


## Roll a preview drop (item id) for a (tier, biome); "" for no drop. Display only.
func roll(tier: int, biome: String) -> String:
	# TODO: resolve_pool() then delegate to its weighted-random pick.
	return ""
