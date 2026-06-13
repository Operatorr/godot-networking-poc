## HPBarControl - Bottom-center HP bar display
## Shows current/max HP with color-coded progress bar
extends Control


var _bar_track: TextureRect = null
var _bar_fill = null
var _bar_frame: TextureRect = null
var _hp_label: Label = null

var _current_hp: int = 100
var _max_hp: int = 100
var _flash_timer: float = 0.0

const BAR_HEIGHT := 36.0
const DAMAGE_FLASH_SECONDS := 0.3
const FRAME_TEXTURE := preload("res://assets/ui/hud/player_health_bar_frame.png")
const TRACK_TEXTURE := preload("res://assets/ui/hud/player_health_bar_track.png")
const FILL_TEXTURE := preload("res://assets/ui/hud/player_health_bar_fill.png")
const TexturedProgressFill := preload("res://scripts/client/hud/textured_progress_fill.gd")
const FILL_LEFT := 40.0
const FILL_TOP := 9.0
const FILL_RIGHT := 22.0
const FILL_BOTTOM := 9.0

# Configurable layout (set by arena_base before add_child so the bar can sit
# left-of-center, making room for the Mana bar to its right).
var bar_width: float = 300.0
## Horizontal offset from the bottom-center anchor (negative = left of center).
## Defaults to centered for a 300-wide bar; arena/offline HUDs override it.
var offset_x: float = -150.0
## Vertical offset from the bottom anchor (negative = up from the bottom edge).
var offset_y: float = -60.0


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(false)


func _build_ui() -> void:
	# Anchor to the bottom-center of the viewport, then place the rect with explicit
	# offsets RELATIVE to that anchor (offset_x left of center, offset_y up from the
	# bottom). Using offsets — not `position` — avoids the absolute-parent-coords trap
	# that pushed the bar off-screen.
	anchor_left = 0.5
	anchor_right = 0.5
	anchor_top = 1.0
	anchor_bottom = 1.0
	offset_left = offset_x
	offset_top = offset_y
	offset_right = offset_x + bar_width
	offset_bottom = offset_y + BAR_HEIGHT

	var fill_rect := _get_fill_rect()

	_bar_track = _make_texture_rect(TRACK_TEXTURE, fill_rect.position, fill_rect.size)
	add_child(_bar_track)

	_bar_fill = TexturedProgressFill.new()
	_bar_fill.texture = FILL_TEXTURE
	_bar_fill.position = fill_rect.position
	_bar_fill.size = fill_rect.size
	add_child(_bar_fill)

	_bar_frame = _make_texture_rect(FRAME_TEXTURE, Vector2.ZERO, Vector2(bar_width, BAR_HEIGHT))
	add_child(_bar_frame)

	# HP text
	_hp_label = Label.new()
	_hp_label.add_theme_font_size_override("font_size", 14)
	_hp_label.add_theme_color_override("font_color", Color.WHITE)
	_hp_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hp_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_hp_label.position = Vector2.ZERO
	_hp_label.size = Vector2(bar_width, BAR_HEIGHT)
	add_child(_hp_label)

	_update_display()


func _process(delta: float) -> void:
	if _flash_timer > 0.0:
		_flash_timer -= delta
		_bar_fill.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 50.0)
		if _flash_timer <= 0.0:
			_bar_fill.modulate.a = 1.0
			set_process(false)


## Update HP from external source
func update_hp(current: int, max_hp: int) -> void:
	current = maxi(current, 0)
	max_hp = maxi(max_hp, 1)
	if current == _current_hp and max_hp == _max_hp:
		return

	var took_damage := current < _current_hp
	_current_hp = current
	_max_hp = max_hp
	_update_display()
	if took_damage:
		_flash_timer = DAMAGE_FLASH_SECONDS
		set_process(true)


func _update_display() -> void:
	if _hp_label == null:
		return

	_hp_label.text = "%d / %d HP" % [_current_hp, _max_hp]

	var ratio := clampf(float(_current_hp) / float(_max_hp), 0.0, 1.0)
	_bar_fill.progress = ratio

	var alpha: float = _bar_fill.modulate.a
	# Keep the authored blood-red texture, but warm it as HP drops.
	if ratio > 0.6:
		_bar_fill.modulate = Color(1.0, 1.0, 1.0, alpha)
	elif ratio > 0.3:
		_bar_fill.modulate = Color(1.15, 0.88, 0.55, alpha)
	else:
		_bar_fill.modulate = Color(1.25, 0.55, 0.55, alpha)


func _get_fill_rect() -> Rect2:
	return Rect2(
		Vector2(FILL_LEFT, FILL_TOP),
		Vector2(bar_width - FILL_LEFT - FILL_RIGHT, BAR_HEIGHT - FILL_TOP - FILL_BOTTOM)
	)


func _make_texture_rect(texture: Texture2D, rect_position: Vector2, rect_size: Vector2) -> TextureRect:
	var texture_rect := TextureRect.new()
	texture_rect.texture = texture
	texture_rect.position = rect_position
	texture_rect.size = rect_size
	texture_rect.stretch_mode = TextureRect.STRETCH_SCALE
	texture_rect.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return texture_rect
