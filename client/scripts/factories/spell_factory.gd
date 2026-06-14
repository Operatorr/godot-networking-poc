## SpellFactory - Build class abilities/spells (Factory + Flyweight).
##
## Concrete EntityFactory for abilities. Each spell archetype is shared, immutable
## data (the *Flyweight*) loaded once from the ability definitions; the *Factory*
## hands out configured ability instances that reference that shared data plus the
## small per-cast/per-owner state. Avoids duplicating heavy ability data per caster.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The "definition" is the shared spell/ability data (Flyweight); the base
## scene (where one applies) is the ability/effect prefab; the result is a
## configured ability bound to its owner.
##
## Authority note: "the client requests, the server decides." Casting is a request;
## the server validates cooldowns, costs, and effects. This factory builds the
## client-side ability for input/prediction/VFX only — it is not the cast authority.
##
## Governing docs: docs/systems/abilities.md, docs/gdd/classes/.
##
## TODO:
##  - Load + cache shared ability data (the Flyweight pool) by spell id.
##  - Build a per-owner ability instance referencing the shared data.
##  - Wire cooldown/cost display and predicted cast VFX (display-only).
class_name SpellFactory
extends EntityFactory


## Build a configured ability instance for an owner from a spell id.
func create_spell(_spell_id: String) -> Node:
	return null


func _get_base_scene() -> PackedScene:
	return null


func _configure(_entity: Node, _definition: Dictionary) -> void:
	pass
