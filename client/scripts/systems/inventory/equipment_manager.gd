## EquipmentManager - Equipped gear & ability-slot grants view.
##
## Displays which items are equipped and which abilities they grant to the action
## bar (Slots 1-4). The server/API own equip state and the authoritative ability
## loadout — the client requests, the server decides; this node mirrors that state,
## forwards equip/unequip requests to the API, and reflects the granted abilities
## into the action-bar UI. It never changes the authoritative loadout itself.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): equipment slot layout and per-item ability grants come from item JSON
## definitions; equipped state comes from the API. Resolved ability ids feed the
## action bar (see StatusEffectManager / abilities for runtime use).
##
## Governing docs: docs/gdd/index.md (Action-bar, Slots 1-4), docs/gdd/loot.md,
## docs/systems/abilities.md.
##
## # TODO:
##   - Cache equipped-by-slot; resolve each item's granted ability for Slots 1-4.
##   - request_equip/unequip: send to the API, await authoritative result, refresh.
##   - Emit equipment_changed / loadout_changed signals for the HUD/action bar.
class_name EquipmentManager
extends Node

## Action-bar ability slots granted by equipped gear.
const ABILITY_SLOT_COUNT: int = 4


## Pull authoritative equipped gear from the API/server into the view.
func sync_from_server(equipped: Dictionary) -> void:
	# TODO: replace cached equip state; re-resolve granted abilities; emit signals.
	pass


## Ability id granted to an action-bar slot (1-4) by the equipped gear; "" if none.
func get_ability_for_slot(slot_index: int) -> String:
	# TODO: resolve from the item equipped in the corresponding equipment slot.
	return ""


## Request equipping an item (server is authoritative; result via sync_from_server).
func request_equip(item_id: String, equipment_slot: String) -> void:
	# TODO: send equip request to the API.
	pass
