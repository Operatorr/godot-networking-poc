## StatSystem - Per-level stat scaling helpers (display only).
##
## Computes a stat's value at a given level for character-sheet and tooltip display:
##   value = base + per_lvl * (L - 1)
## The server/API hold the authoritative stats that actually drive the sim — the
## client requests, the server decides; this is a preview/display mirror so the UI
## can show "what you'll have at level N" without a round-trip.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): base + per_lvl come from a class/stat JSON definition (see gdd/classes/);
## resolved values feed the character sheet, not authoritative entity state.
##
## Governing docs: docs/gdd/classes/, docs/gdd/progression/,
## docs/systems/PROGRESSION.md.
##
## # TODO:
##   - Read base/per_lvl per stat from the class JSON definition.
##   - scale_stat(): base + per_lvl*(L-1); match server numeric policy.
##   - Provide a whole-sheet resolver for a given class+level for the UI.
class_name StatSystem
extends RefCounted


## Linear per-level scaling: base + per_lvl * (level - 1). Display only.
static func scale_stat(base: float, per_lvl: float, level: int) -> float:
	# TODO: return base + per_lvl * (level - 1).
	return base


## Resolve all stats for a class at a level into a flat {stat_name: value} sheet.
static func resolve_stats(class_id: String, level: int) -> Dictionary:
	# TODO: load class JSON def; scale each stat via scale_stat().
	return {}
