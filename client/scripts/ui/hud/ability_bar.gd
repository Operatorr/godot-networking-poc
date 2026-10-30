## AbilityBar - bottom HUD action indicators with cooldown overlays and binding labels.
##
## Authored as scenes/ui/hud/ability_bar.tscn (root anchored bottom-center with six key
## Labels). The slot frames, the radial cooldown wedges, and the usable-ability glyphs are
## drawn in _draw() (they're tightly coupled cooldown VFX). The SPACE slot shows the local
## MovementStateMachine dash cooldown and the RMB slot the class ability cooldown (both timers
## are owned by the Rust sim online and mirrored into the SM); slots 2-5 are visual placeholders.
class_name AbilityBar
extends Control

# NOTE: the Key0..Key5 labels in ability_bar.tscn are positioned with a fixed x-stride that MUST
# equal SLOT_SIZE + SLOT_GAP (= 54px) so each key glyph lines up under its drawn slot frame. Keep
# the scene offsets and these constants in lockstep.
const SLOT_SIZE := 48.0
const SLOT_GAP := 6.0
const SLOT_COUNT := 6
const FRAME_TEXTURE := preload("res://assets/ui/grimdark/slot.svg")

var _movement_sm: MovementStateMachine = null
var _was_cooling_down: bool = false
var _binding_refresh: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
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
		if index >= 2:
			var c := _slot_rect(index).get_center()
			draw_line(c - Vector2(5, 0), c + Vector2(5, 0), Color(0.30, 0.31, 0.28))

	# Usable-ability glyphs: SPACE = dash, RMB = the class ability.
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


## Draw a small usable-ability glyph in a slot (dimmed while the corresponding ability is cooling down).
func _draw_slot_icon(index: int, kind: String) -> void:
	var c := _slot_rect(index).get_center() - Vector2.ZERO  # sit above the key label
	var col := Color(0.95, 0.88, 0.55, 0.95)
	if _movement_sm != null:
		if kind == "dash" and _movement_sm.get_dash_cooldown_remaining() > 0.0:
			col.a = 0.30
		elif kind == "ability" and _movement_sm.get_ability_cooldown_remaining() > 0.0:
			col.a = 0.30
	match kind:
		"dash":
			# Double chevron » (a "dash forward" cue): two right-pointing triangles.
			var s := 7.0
			for off in [-3.0, 1.5]:
				var p := c + Vector2(off, 0.0)
				draw_colored_polygon(PackedVector2Array([
					p + Vector2(-s * 0.5, -s), p + Vector2(s * 0.6, 0.0), p + Vector2(-s * 0.5, s)
				]), col)
		"ability":
			# 4-point sparkle (a "spell ready" cue).
			var r := 10.0
			var r2 := 3.4
			draw_colored_polygon(PackedVector2Array([
				c + Vector2(0, -r), c + Vector2(r2, -r2), c + Vector2(r, 0), c + Vector2(r2, r2),
				c + Vector2(0, r), c + Vector2(-r2, r2), c + Vector2(-r, 0), c + Vector2(-r2, -r2)
			]), col)


func _draw_cooldown_text(index: int, remaining: float) -> void:
	var font := ThemeDB.fallback_font
	var text := "%.1f" % remaining
	var width := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14).x
	var origin := _slot_rect(index).get_center() + Vector2(-width * 0.5, 5)
	draw_string_outline(font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, 4, Color.BLACK)
	draw_string(font, origin, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(0.92, 0.88, 0.76))


func _refresh_binding_labels() -> void:
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
