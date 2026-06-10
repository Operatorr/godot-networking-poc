## BottomBars - shared builder for the bottom-center HUD bar group.
##
## Single source of truth for the HP / Stamina / Mana layout so the networked arena
## (`arena_base.gd`) and the offline modes (`offline_arena.gd`) can't drift apart.
## Layout: HP (left) + gap + Mana (right) horizontally centered, with the Stamina
## bar spanning the full combined width directly above them.
class_name BottomBars
extends RefCounted

const HP_BAR_PATH := "res://scripts/client/hud/hp_bar.gd"
const STAT_BAR_PATH := "res://scripts/client/hud/stat_bar.gd"

# Base-resolution pixels, bottom-center anchored.
const HP_BAR_WIDTH := 300.0
const MANA_BAR_WIDTH := 200.0
const BAR_GAP := 8.0
const BAR_GROUP_WIDTH := HP_BAR_WIDTH + BAR_GAP + MANA_BAR_WIDTH   # 508
const BAR_GROUP_LEFT := -BAR_GROUP_WIDTH / 2.0                     # -254
const BAR_ROW_OFFSET_Y := -60.0
const STAMINA_BAR_HEIGHT := 14.0
const STAMINA_BAR_OFFSET_Y := -80.0

const MANA_FILL_COLOR := Color(0.25, 0.45, 0.95)
const STAMINA_FILL_COLOR := Color(0.85, 0.78, 0.2)


## Build the three bars, add them to hud_layer, and return them as
## { "hp": Control, "stamina": Control, "mana": Control }.
static func create(hud_layer: CanvasLayer) -> Dictionary:
	var hp := _make(HP_BAR_PATH, "HPBar")
	hp.bar_width = HP_BAR_WIDTH
	hp.offset_x = BAR_GROUP_LEFT
	hp.offset_y = BAR_ROW_OFFSET_Y
	hud_layer.add_child(hp)

	var mana := _make(STAT_BAR_PATH, "ManaBar")
	mana.bar_width = MANA_BAR_WIDTH
	mana.bar_height = 24.0
	mana.offset_x = BAR_GROUP_LEFT + HP_BAR_WIDTH + BAR_GAP
	mana.offset_y = BAR_ROW_OFFSET_Y
	mana.fill_color = MANA_FILL_COLOR
	mana.show_label = true
	hud_layer.add_child(mana)

	var stamina := _make(STAT_BAR_PATH, "StaminaBar")
	stamina.bar_width = BAR_GROUP_WIDTH
	stamina.bar_height = STAMINA_BAR_HEIGHT
	stamina.offset_x = BAR_GROUP_LEFT
	stamina.offset_y = STAMINA_BAR_OFFSET_Y
	stamina.fill_color = STAMINA_FILL_COLOR
	hud_layer.add_child(stamina)

	return {"hp": hp, "stamina": stamina, "mana": mana}


static func _make(script_path: String, node_name: String) -> Control:
	var node := Control.new()
	node.set_script(load(script_path))
	node.name = node_name
	return node
