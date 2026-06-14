## PlayerClassMage - Mage client feel: ranged primary + Mageblast.
##
## Responsibility: concrete [PlayerClassBase] strategy for the Mage. Its RMB
## ability is **Mageblast** — an instant cursor-targeted AOE. NOTHING is
## predicted: the Mage does not move on cast, so the client only telegraphs the
## AOE circle and SENDS the request; the blast, its hits, and damage are entirely
## server-decided. Governing rule:
## **the client requests, the server decides** — the Mage stub deliberately
## leaves predict_ability_motion() as a no-op (inherited): zero predicted motion.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The ClassFactory instances this strategy for class id
## "mage" and feeds it that JSON (blast radius, range, primary cadence).
## Behaviour is STRATEGY + DATA, not a Player subclass.
## `ability_predicts_motion = false` for this class (no predicted movement).
##
## Governing docs: docs/gdd/classes/mage.md, docs/systems/abilities.md.
##
## TODO:
## - override load_definition() to read blast radius + cast range.
## - override draw_ability_preview() to draw the cursor AOE circle clamped to
##   range. (Do NOT override predict_ability_motion — Mageblast predicts
##   nothing.)
class_name PlayerClassMage
extends PlayerClassBase

## Mageblast AOE radius in world units (loaded from the class definition).
var blast_radius: float = 0.0

## Maximum cast range in world units (loaded from the class definition).
var cast_range: float = 0.0


## Draw the Mageblast telegraph (AOE circle) at the cursor, clamped to range.
## Pure display — the server resolves the actual blast and its hits.
# TODO: render the AOE circle clamped to cast_range.
func draw_ability_preview(_target: Vector2) -> void:
	pass
