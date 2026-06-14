## ItemFactory - Procedural item generation (Factory + Builder + Prototype).
##
## Concrete EntityFactory for loot. Combines three patterns: a base-type
## *Prototype* (the item's archetype data), a *Builder* that layers rolled
## affixes/modifiers onto it, and the *Factory* entry point that produces the
## final configured item from a generation spec (rarity, item level, biome).
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The "definition" is the base item + affix data (from the loot tables);
## the base scene is the item prefab; the result is one rolled, configured item.
##
## Authority note: "the client requests, the server decides." The SERVER rolls the
## authoritative drop (which base, which affixes, which values). This client factory
## reconstructs/displays that item from server data; it must not roll loot itself
## except for purely cosmetic preview, never for gameplay value.
##
## Governing docs: docs/gdd/loot.md, docs/gdd/progression/.
##
## TODO:
##  - Define the generation spec (base id, rarity, item level, affix pool).
##  - Builder step: apply rolled affixes/modifiers from server data.
##  - Prototype step: clone the base archetype before building.
##  - Resolve the base item scene and render the configured item.
class_name ItemFactory
extends EntityFactory


## Build a configured item from a server-provided item spec.
func create_item(_item_spec: Dictionary) -> Node:
	return null


func _get_base_scene() -> PackedScene:
	return null


func _configure(_entity: Node, _definition: Dictionary) -> void:
	pass
