## SpellDefinition - Data-driven definition for one spell / ability.
##
## Parsed from the spell catalogue (res://data/spells/<id>.json) by
## [DatabaseLoader]. Data-driven / prototype pattern: a new ability is added by
## dropping in JSON, NOT by subclassing. One ability-execution path, configured
## by DATA (cost, cooldown, cast behaviour, the projectile it spawns).
##     JSON definition -> DatabaseLoader -> DefinitionCache -> Factory
##                     -> base ability/projectile scene -> configured cast.
##
## The client reads this to predict casts (cooldown gating, projectile spawn for
## responsiveness) and to drive HUD icons/tooltips. projectile_id references a
## ProjectileDefinition (resolved via the cache; named here in comments only).
##
## Authority note: "the client requests, the server decides." Predicted casts are
## reconciled against server confirms; the server owns cooldown/cost truth.
##
## Governing docs: systems/abilities.md, gdd/index.md.
##
## TODO:
## - Define fields: id, display_name, cooldown, mana/resource cost, cast type,
##   projectile_id, effect/animation hints, icon path.
## - Implement from_dict()/to_dict() mirroring MonsterDefinition's helpers.
## - Keep raw: Dictionary for round-trip fidelity.
class_name SpellDefinition
extends RefCounted

# --- Identity ---------------------------------------------------------------
var id: String = ""
var display_name: String = ""

# --- Cast tuning (client-predicted; server-authoritative) -------------------
var cooldown: float = 0.0

## Projectile this spell spawns (id into the projectile catalogue; see
## ProjectileDefinition). Empty for non-projectile abilities.
var projectile_id: String = ""

## Raw parsed dict, preserved for tooling round-trips.
var raw: Dictionary = {}


## Build a definition from a parsed JSON dictionary.
static func from_dict(p_id: String, dict: Dictionary) -> SpellDefinition:
	# TODO: parse identity, cost/cooldown, cast behaviour, projectile_id.
	return null


## Flatten back to a dictionary (debugging / tooling / CMS).
func to_dict() -> Dictionary:
	# TODO: mirror from_dict's shape.
	return {}
