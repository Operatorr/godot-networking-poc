## BottomBars - shared builder for the bottom-center HUD bar group.
##
## Single source of truth for the HP / Stamina / Mana layout so the networked arena
## (`arena_base.gd`) and the offline modes (`offline_arena.gd`) can't drift apart.
## Layout: HP + six ability slots + Mana horizontally centered, with the Stamina
## bar spanning only the ability slots directly above them.
class_name BottomBars
extends RefCounted

const HP_BAR_PATH := "res://scripts/client/hud/hp_bar.gd"
const STAT_BAR_PATH := "res://scripts/client/hud/stat_bar.gd"
const ABILITY_SLOTS_PATH := "res://scripts/client/hud/ability_slots.gd"

# Base-resolution pixels, bottom-center anchored.
const HP_BAR_WIDTH := 300.0
const MANA_BAR_WIDTH := 300.0
const ABILITY_SLOT_SIZE := 36.0
const ABILITY_SLOT_GAP := 4.0
const ABILITY_SLOT_COUNT := 6.0
const ABILITY_SLOTS_WIDTH := ABILITY_SLOT_SIZE * ABILITY_SLOT_COUNT + ABILITY_SLOT_GAP * (ABILITY_SLOT_COUNT - 1.0)
const BAR_GAP := 8.0
const BAR_GROUP_WIDTH := HP_BAR_WIDTH + BAR_GAP + ABILITY_SLOTS_WIDTH + BAR_GAP + MANA_BAR_WIDTH
const BAR_GROUP_LEFT := -BAR_GROUP_WIDTH / 2.0
const ABILITY_SLOTS_LEFT := BAR_GROUP_LEFT + HP_BAR_WIDTH + BAR_GAP
const BAR_ROW_OFFSET_Y := -66.0
const STAMINA_BAR_HEIGHT := 18.0
const STAMINA_BAR_OFFSET_Y := -90.0

const MANA_FILL_COLOR := Color.WHITE
const STAMINA_FILL_COLOR := Color.WHITE


## Build the bottom HUD group, add it to hud_layer, and return the nodes as
## { "hp": Control, "stamina": Control, "ability_slots": Control, "mana": Control }.
static func create(hud_layer: CanvasLayer) -> Dictionary:
	var hp := _make(HP_BAR_PATH, "HPBar")
	hp.bar_width = HP_BAR_WIDTH
	hp.offset_x = BAR_GROUP_LEFT
	hp.offset_y = BAR_ROW_OFFSET_Y
	hud_layer.add_child(hp)

	var ability_slots := _make(ABILITY_SLOTS_PATH, "AbilitySlots")
	ability_slots.offset_x = ABILITY_SLOTS_LEFT
	ability_slots.offset_y = BAR_ROW_OFFSET_Y
	hud_layer.add_child(ability_slots)

	var stamina := _make(STAT_BAR_PATH, "StaminaBar")
	stamina.bar_width = ABILITY_SLOTS_WIDTH
	stamina.bar_height = STAMINA_BAR_HEIGHT
	stamina.offset_x = ABILITY_SLOTS_LEFT
	stamina.offset_y = STAMINA_BAR_OFFSET_Y
	stamina.fill_color = STAMINA_FILL_COLOR
	hud_layer.add_child(stamina)

	var mana := _make(STAT_BAR_PATH, "ManaBar")
	mana.bar_width = MANA_BAR_WIDTH
	mana.bar_height = 36.0
	mana.offset_x = ABILITY_SLOTS_LEFT + ABILITY_SLOTS_WIDTH + BAR_GAP
	mana.offset_y = BAR_ROW_OFFSET_Y
	mana.fill_color = MANA_FILL_COLOR
	mana.show_label = true
	hud_layer.add_child(mana)

	return {"hp": hp, "stamina": stamina, "ability_slots": ability_slots, "mana": mana}


static func _make(script_path: String, node_name: String) -> Control:
	var node := Control.new()
	node.set_script(load(script_path))
	node.name = node_name
	return node
