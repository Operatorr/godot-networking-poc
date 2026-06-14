## AbilitySlots - bottom HUD placeholder spell slots with cooldown overlays.
##
## The SPACE slot is wired to the local MovementStateMachine dash cooldown. Other
## slots are visual placeholders until their abilities exist.
extends Control


const SLOT_SIZE := 36.0
const SLOT_GAP := 4.0
const SLOT_COUNT := 6
const TOTAL_WIDTH := SLOT_SIZE * SLOT_COUNT + SLOT_GAP * (SLOT_COUNT - 1)
const FRAME_TEXTURE := preload("res://assets/ui/hud/player_ability_slot_frame.png")

const SLOTS := [
	{"label": "SPACE", "action": "dash"},
	{"label": "RMB", "action": "ability"},
	{"label": "1", "action": ""},
	{"label": "2", "action": ""},
	{"label": "3", "action": ""},
	{"label": "4", "action": ""},
]

var offset_x: float = -TOTAL_WIDTH / 2.0
var offset_y: float = -66.0

var _movement_sm: MovementStateMachine = null
var _was_cooling_down: bool = false


func _ready() -> void:
	anchor_left = 0.5
	anchor_right = 0.5
	anchor_top = 1.0
	anchor_bottom = 1.0
	offset_left = offset_x
	offset_top = offset_y
	offset_right = offset_x + TOTAL_WIDTH
	offset_bottom = offset_y + SLOT_SIZE
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST

	_build_slots()
	set_process(true)


func bind_movement_state_machine(sm: MovementStateMachine) -> void:
	_movement_sm = sm
	_was_cooling_down = false
	queue_redraw()


func _process(_delta: float) -> void:
	var is_cooling_down := _movement_sm != null and _movement_sm.get_dash_cooldown_remaining() > 0.0
	if is_cooling_down or _was_cooling_down:
		queue_redraw()
	_was_cooling_down = is_cooling_down


func _draw() -> void:
	for index in range(SLOT_COUNT):
		draw_texture_rect(FRAME_TEXTURE, _slot_rect(index), false)

	# Usable-ability glyphs: SPACE = dash, RMB = the class ability.
	_draw_slot_icon(0, "dash")
	_draw_slot_icon(1, "ability")

	if _movement_sm == null:
		return
	var remaining := _movement_sm.get_dash_cooldown_remaining()
	if remaining <= 0.0:
		return
	var ratio := clampf(remaining / GameConstants.PLAYER_DASH_COOLDOWN, 0.0, 1.0)
	_draw_cooldown_wedge(_slot_rect(0), ratio)


func _build_slots() -> void:
	for index in range(SLOT_COUNT):
		var slot_rect := _slot_rect(index)

		var key_label := Label.new()
		key_label.text = SLOTS[index]["label"]
		# Span the FULL slot width and center (the old +1px inset read as right-shifted on
		# the wide "SPACE" label). clip_text keeps a long key from spilling past the frame.
		key_label.clip_text = true
		key_label.position = slot_rect.position + Vector2(0.0, SLOT_SIZE - 14.0)
		key_label.size = Vector2(SLOT_SIZE, 12.0)
		key_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		key_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		key_label.add_theme_font_size_override("font_size", 8)
		key_label.add_theme_color_override("font_color", Color(0.86, 0.82, 0.72, 1.0))
		key_label.add_theme_color_override("font_shadow_color", Color(0.0, 0.0, 0.0, 0.9))
		key_label.add_theme_constant_override("shadow_offset_x", 1)
		key_label.add_theme_constant_override("shadow_offset_y", 1)
		key_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
		add_child(key_label)


func _slot_rect(index: int) -> Rect2:
	var x := index * (SLOT_SIZE + SLOT_GAP)
	return Rect2(Vector2(x, 0.0), Vector2(SLOT_SIZE, SLOT_SIZE))


func _draw_cooldown_wedge(slot_rect: Rect2, ratio: float) -> void:
	var center := slot_rect.get_center()
	# Radius fits INSIDE the square (half-extent SLOT_SIZE/2) with a 1px inset, so the
	# radial sweep rotates within the slot instead of overflowing the frame.
	var radius := SLOT_SIZE * 0.5 - 1.0
	var start_angle := -PI / 2.0
	var end_angle := start_angle + TAU * ratio
	var points: PackedVector2Array = [center]
	var steps := maxi(6, ceili(48.0 * ratio))
	for step in range(steps + 1):
		var t := float(step) / float(steps)
		var angle := lerpf(start_angle, end_angle, t)
		points.append(center + Vector2(cos(angle), sin(angle)) * radius)
	draw_colored_polygon(points, Color(0.0, 0.0, 0.0, 0.55))


## Draw a small usable-ability glyph in a slot (dimmed while the dash is cooling down).
func _draw_slot_icon(index: int, kind: String) -> void:
	var c := _slot_rect(index).get_center() - Vector2(0.0, 4.0)  # sit above the key label
	var col := Color(0.95, 0.88, 0.55, 0.95)
	if kind == "dash" and _movement_sm != null and _movement_sm.get_dash_cooldown_remaining() > 0.0:
		col.a = 0.30
	match kind:
		"dash":
			# Double chevron » (a "dash forward" cue): two right-pointing triangles.
			var s := 4.5
			for off in [-3.0, 1.5]:
				var p := c + Vector2(off, 0.0)
				draw_colored_polygon(PackedVector2Array([
					p + Vector2(-s * 0.5, -s), p + Vector2(s * 0.6, 0.0), p + Vector2(-s * 0.5, s)
				]), col)
		"ability":
			# 4-point sparkle (a "spell ready" cue).
			var r := 6.0
			var r2 := 2.2
			draw_colored_polygon(PackedVector2Array([
				c + Vector2(0, -r), c + Vector2(r2, -r2), c + Vector2(r, 0), c + Vector2(r2, r2),
				c + Vector2(0, r), c + Vector2(-r2, r2), c + Vector2(-r, 0), c + Vector2(-r2, -r2)
			]), col)
