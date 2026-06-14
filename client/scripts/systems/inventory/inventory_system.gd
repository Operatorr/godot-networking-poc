## InventorySystem - Client inventory view.
##
## Displays the player's inventory (items, stacks, slots) for UI interaction. The
## Go API / server own authoritative inventory persistence — the client requests,
## the server decides; this node mirrors the server-held inventory and forwards
## move/use/drop requests to the API, then reflects the authoritative result. It
## never creates or destroys items locally.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): item metadata (name, icon, stack size, rarity) comes from item JSON
## definitions resolved via ItemGenerator/LootTable; the owned-item set comes from
## the API.
##
## Governing docs: docs/gdd/loot.md, docs/gdd/index.md.
##
## # TODO:
##   - Cache the server-held item list; expose slot/stack queries for the UI.
##   - request_move/use/drop: send to the API, await authoritative result, refresh.
##   - Emit an inventory_changed signal on any authoritative update.
class_name InventorySystem
extends Node


## Pull the authoritative inventory from the API/server into the view.
func sync_from_server(items: Array) -> void:
	# TODO: replace cached items with the authoritative set; emit inventory_changed.
	pass


## Item record at a slot (display only): {} if empty.
func get_item_at(slot_index: int) -> Dictionary:
	# TODO: return cached item record for the slot.
	return {}


## Request a slot move (server is authoritative; result arrives via sync_from_server).
func request_move(from_slot: int, to_slot: int) -> void:
	# TODO: send move request to the API.
	pass
