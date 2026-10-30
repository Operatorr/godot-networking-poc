## AbilityBar - bottom HUD action indicators with cooldown overlays and binding labels.
##
## Authored as scenes/ui/hud/ability_bar.tscn (root anchored bottom-center with six key
## Labels). The slot frames, the radial cooldown wedges, and the equipped ability icons are
## drawn in _draw() (they're tightly coupled cooldown VFX). The SPACE slot shows the local
## MovementStateMachine dash cooldown and the RMB slot the class ability cooldown (both timers
## are owned by the Rust sim online and mirrored into the SM); slots 2-5 are visual placeholders.
class_name AbilityBar
extends Control

# NOTE: the Key0..Key5 labels in ability_bar.tscn are positioned with a fixed x-stride that MUST
# equal SLOT_SIZE + SLOT_GAP (= 68px) so each key glyph lines up under its drawn slot frame. Keep
# the scene offsets and these constants in lockstep.
const SLOT_SIZE := 60.0
const SLOT_GAP := 8.0
const SLOT_COUNT := 6
const FRAME_TEXTURE := preload("res://assets/ui/grimdark/slot.svg")
const BADGE_TEXTURE := preload("res://assets/ui/grimdark/key_badge.svg")
const ICON_ATLAS := preload("res://assets/ui/grimdark/ability_icons.png")

var _icons: Array[AtlasTexture] = []
var _class_id: int = -1

var _movement_sm: MovementStateMachine = null
var _was_cooling_down: bool = false
var _binding_refresh: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	var cell := ICON_ATLAS.get_size() * 0.5
	for index in 4:
		var icon := AtlasTexture.new()
		icon.atlas = ICON_ATLAS
		icon.filter_clip = true
		icon.region = Rect2(Vector2(index % 2, floori(index / 2.0)) * cell, cell)
		_icons.append(icon)
	_refresh_binding_labels()
	set_process(true)


func bind_movement_state_machine(sm: MovementStateMachine) -> void:
	_movement_sm = sm
	_was_cooling_down = false
	queue_redraw()


func _process(delta: float) -> void:
	_binding_refresh += delta
	if _binding_refresh >= 0.5:
		_binding_refresh = 0.0
		_refresh_binding_labels()
	# Redraw while EITHER the dash (SPACE) or the RMB ability is cooling down — and for one frame
	# after it clears so the final wedge is erased.
	var is_cooling_down := _movement_sm != null \
		and (_movement_sm.get_dash_cooldown_remaining() > 0.0 \
			or _movement_sm.get_ability_cooldown_remaining() > 0.0)
	if is_cooling_down or _was_cooling_down:
		queue_redraw()
	_was_cooling_down = is_cooling_down


func _draw() -> void:
	for index in range(SLOT_COUNT):
		draw_texture_rect(FRAME_TEXTURE, _slot_rect(index), false, Color.WHITE if index < 2 else Color(0.52, 0.53, 0.50))
		if index < 2:
			draw_texture_rect(BADGE_TEXTURE, Rect2(_slot_rect(index).position + Vector2(6, 58), Vector2(48, 26)), false)

	# Equipped artwork: SPACE = dash, RMB = the class ability.
	_draw_slot_icon(0, "dash")
	_draw_slot_icon(1, "ability")

	if _movement_sm == null:
		return

	# SPACE (dash) cooldown wedge.
	var dash_remaining := _movement_sm.get_dash_cooldown_remaining()
	if dash_remaining > 0.0:
		var dash_ratio := clampf(dash_remaining / GameConstants.PLAYER_DASH_COOLDOWN, 0.0, 1.0)
		_draw_cooldown_wedge(_slot_rect(0), dash_ratio)
		_draw_cooldown_text(0, dash_remaining)

	# RMB (class ability) cooldown wedge. The per-class cooldown max lives on the SM (set by the
	# owner offline, mirrored from the Rust sim online); guard against a zero/unset max.
	var ability_remaining := _movement_sm.get_ability_cooldown_remaining()
	var ability_max := _movement_sm.ability_cooldown_max
	if ability_remaining > 0.0 and ability_max > 0.0:
		var ability_ratio := clampf(ability_remaining / ability_max, 0.0, 1.0)
		_draw_cooldown_wedge(_slot_rect(1), ability_ratio)
		_draw_cooldown_text(1, ability_remaining)


func _slot_rect(index: int) -> Rect2:
	var x := index * (SLOT_SIZE + SLOT_GAP)
	return Rect2(Vector2(x, 0.0), Vector2(SLOT_SIZE, SLOT_SIZE))


func _draw_cooldown_wedge(slot_rect: Rect2, ratio: float) -> void:
	var center := slot_rect.get_center()
	# Radius fits INSIDE the square (half-extent SLOT_SIZE/2) with a 1px inset, so the
	# radial sweep rotates within the slot instead of overflowing the frame.
	var radius := SLOT_SIZE * 0.5 - 8.0
	var start_angle := -PI / 2.0
	var end_angle := start_angle + TAU * ratio
	var points: PackedVector2Array = [center]
	var steps := maxi(6, ceili(48.0 * ratio))
	for step in range(steps + 1):
		var t := float(step) / float(steps)
		var angle := lerpf(start_angle, end_angle, t)
		points.append(center + Vector2(cos(angle), sin(angle)) * radius)
	draw_colored_polygon(points, Color(0.0, 0.0, 0.0, 0.55))


## Only equipped actions get artwork. Unassigned slots remain empty.
func _draw_slot_icon(index: int, kind: String) -> void:
	if _icons.is_empty():
		return
	var icon_index := 0
	if kind == "ability":
		match _class_id:
			PacketTypes.PlayerClass.WARRIOR: icon_index = 1
			PacketTypes.PlayerClass.ROGUE: icon_index = 2
			_: icon_index = 3
	draw_texture_rect(_icons[icon_index], _slot_rect(index).grow(-8), false)


func _draw_cooldown_text(index: int, remaining: float) -> void:
	var font := ThemeDB.fallback_font
	var text := "%.1f" % remaining
	var width := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x
	var origin := _slot_rect(index).get_center() + Vector2(-width * 0.5, 5)
	draw_string_outline(font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, 4, Color.BLACK)
	draw_string(font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(0.92, 0.88, 0.76))


func _refresh_binding_labels() -> void:
	var class_id := int(GameManager.player_data.get("player_class", PacketTypes.PlayerClass.WARRIOR))
	if class_id != _class_id:
		_class_id = class_id
		queue_redraw()
	for index in 2:
		var action := "dash" if index == 0 else "ability"
		var text := "—"
		for event in InputMap.action_get_events(action):
			if event is InputEventKey:
				text = OS.get_keycode_string(event.physical_keycode if event.physical_keycode != 0 else event.keycode).to_upper()
				break
			if event is InputEventMouseButton:
				match event.button_index:
					MOUSE_BUTTON_LEFT: text = "LMB"
					MOUSE_BUTTON_RIGHT: text = "RMB"
					MOUSE_BUTTON_MIDDLE: text = "MMB"
					_: text = "M%d" % event.button_index
				break
		get_node("Key%d" % index).text = text
