## ItemGenerator - Procedural item-roll preview (display only).
##
## Builds a PREVIEW of a procedurally-generated item (affixes, rarity, stat rolls)
## for tooltips and reward-screen mockups. The server is authoritative for every
## real item roll — the client requests, the server decides; any item shown here is
## illustrative until the API confirms the actual drop. Seeded previews must mirror
## the server's roll formula to avoid misleading the player.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): base item templates, affix pools, and rarity weights come from item
## JSON definitions; this Factory composes them into a configured item record that
## InventorySystem/EquipmentManager can display.
##
## Governing docs: docs/gdd/loot.md.
##
## TODO:
##   - Load base templates + affix pools from JSON; implement weighted affix rolls.
##   - generate(): compose base + rarity + affixes into an item record (preview).
##   - Mirror the server's seed/roll math so previews match confirmed drops.
class_name ItemGenerator
extends RefCounted


## Roll a preview item record from a base template + rarity (display/preview only).
func generate(base_item_id: String, rarity: int, seed: int) -> Dictionary:
	# TODO: pick affixes via weighted rolls; assemble the item record.
	return {}


## Resolve a base item template from its JSON definition.
func get_base_template(base_item_id: String) -> Dictionary:
	# TODO: load and return the base item JSON definition.
	return {}
