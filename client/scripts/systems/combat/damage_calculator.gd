## DamageCalculator - Client-side damage math for floating numbers & previews.
##
## Mirrors the SERVER's damage formulas (sim_core / Go API) so the client can show
## floating damage numbers and tooltip previews the instant a hit lands, without a
## round-trip. This is DISPLAY ONLY: the client requests, the server decides — the
## authoritative damage applied to HP is computed server-side. If this math drifts
## from the server it produces a cosmetic mispredict, never an authority change.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): reads ability/weapon damage fields from the loaded JSON definitions; the
## resolved numbers feed the HUD/visuals layer, not the entity's authoritative state.
##
## Governing docs: docs/systems/combat-hits.md, docs/systems/abilities.md,
## docs/server/contract.md (numerics policy: f32 ops, truncate-toward-zero).
##
## TODO:
##   - Port the server damage formula (base + scaling per stat/level, crit, mitigation).
##   - Match server quantization/rounding exactly (truncate toward zero) to avoid
##     off-by-one mispredicts in the floating numbers.
##   - Expose a "preview" path for tooltips (min/max, expected) vs. a "resolved" path
##     for an actual landed hit.
class_name DamageCalculator
extends RefCounted


## Predicted damage for a single landed hit, for floating numbers (display only;
## server is authoritative — named preview_* to mirror preview_range and signal this
## never changes HP). attacker_stats / defender_stats are flat Dictionaries sourced
## from JSON defs + level: {stat_name: float}.
func preview_damage(attacker_stats: Dictionary, defender_stats: Dictionary, ability_id: String) -> int:
	# TODO: base + per-stat scaling, crit roll preview, defender mitigation, truncate.
	return 0


## Tooltip preview range for an ability at a given level: {"min": int, "max": int}.
func preview_range(ability_id: String, level: int) -> Dictionary:
	# TODO: compute min/max from ability JSON definition + scaling.
	return {}
