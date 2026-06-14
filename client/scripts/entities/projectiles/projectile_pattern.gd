## ProjectilePattern - bullet-hell emission pattern descriptor.
##
## Responsibility: a data object that describes HOW a volley of projectiles is
## arranged at the moment of fire — spread (cone of N bullets), ring (M bullets
## evenly around a circle), or aimed (single/parallel toward the cursor). Used by
## casters and bosses to declare their fire patterns. It computes the per-bullet
## DIRECTIONS for a given aim; it does not spawn, move, or hit — the live
## [Projectile] + ProjectilePool render motion, and the server owns the real
## bullets and damage. Governing rule:
## **the client requests, the server decides** — a pattern is a display/preview
## and request-shaping descriptor; the server authoritatively spawns the volley.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. A pattern is parsed from a class/monster ability
## definition (type + count + spread/spin params), so new bullet patterns are
## added by DATA, not by subclassing the projectile. Composition: an ability
## references a ProjectilePattern; the projectile entity stays a single class.
##
## Governing docs: docs/systems/abilities.md, docs/gdd/MONSTERS.md (boss/caster
## patterns), docs/server/contract.md (projectile spawn).
##
## TODO:
## - define a kind enum (SPREAD / RING / AIMED) and load_definition(def).
## - directions_for(aim): return an Array of normalized Vector2 directions for
##   the volley given the aim direction.
class_name ProjectilePattern
extends RefCounted

## Pattern kind tag (0 spread / 1 ring / 2 aimed). Set from the definition.
var kind: int = 0

## Number of projectiles in the volley.
var count: int = 1

## Total spread arc (radians) for SPREAD; ignored by RING/AIMED.
var spread_radians: float = 0.0


## Parse a pattern definition Dictionary (from an ability's JSON) into the
## fields above.
# TODO: read kind/count/spread/spin params.
func load_definition(_def: Dictionary) -> void:
	pass


## Compute the per-bullet normalized directions for this pattern, given the
## world-space aim direction. Pure math; spawns nothing.
# TODO: build the Array<Vector2> per kind (spread cone / ring / aimed).
func directions_for(_aim: Vector2) -> Array:
	return []
