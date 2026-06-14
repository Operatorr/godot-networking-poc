## StatBar - Generic bottom-anchored resource bar (background + fill + optional label).
##
## Reusable Control used for the Stamina and Mana HUD bars. Position and size are
## configured from arena_base before the node enters the tree, so a single script
## drives several differently-shaped bars. Modelled on hp_bar.gd but without the
## HP-specific colour gradient / damage flash. Update it via update_value().
extends Control


var _bar_track: TextureRect = null
var _bar_fill = null
var _bar_frame: TextureRect = null
var _label: Label = null

var _current: float = 0.0
var _maximum: float = 100.0
## Sprint-exhaustion blink (stamina bar). While true, the frame flashes red.
var _exhausted: bool = false

# --- Configuration (set by the owner BEFORE add_child, i.e. before _ready) ---
## Bar width in base-resolution pixels.
var bar_width: float = 300.0
## Bar height in base-resolution pixels.
var bar_height: float = 36.0
## Horizontal offset from the bottom-center anchor (negative = left of center).
## Owners always override this; default centers a 300-wide bar.
var offset_x: float = -150.0
## Vertical offset from the bottom anchor (negative = up from the bottom edge).
var offset_y: float = -60.0
## Fill tint. Leave white to use the authored sprite colour.
var fill_color: Color = Color.WHITE
## Whether to draw a centered numeric label.
var show_label: bool = false

const MANA_FRAME_TEXTURE := preload("res://assets/ui/hud/player_mana_bar_frame.png")
const MANA_TRACK_TEXTURE := preload("res://assets/ui/hud/player_mana_bar_track.png")
const MANA_FILL_TEXTURE := preload("res://assets/ui/hud/player_mana_bar_fill.png")
const STAMINA_FRAME_TEXTURE := preload("res://assets/ui/hud/player_stamina_bar_frame.png")
const STAMINA_TRACK_TEXTURE := preload("res://assets/ui/hud/player_stamina_bar_track.png")
const STAMINA_FILL_TEXTURE := preload("res://assets/ui/hud/player_stamina_bar_fill.png")
const TexturedProgressFill := preload("res://scripts/ui/hud/textured_progress_fill.gd")


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(false)


func _build_ui() -> void:
	# Anchor bottom-center, then place with explicit offsets relative to that anchor
	# (see hp_bar.gd) so the bar lands on-screen regardless of viewport width.
	anchor_left = 0.5
	anchor_right = 0.5
	anchor_top = 1.0
	anchor_bottom = 1.0
	offset_left = offset_x
	offset_top = offset_y
	offset_right = offset_x + bar_width
	offset_bottom = offset_y + bar_height

	var fill_rect := _get_fill_rect()
	var textures := _get_textures()

	_bar_track = _make_texture_rect(textures["track"], fill_rect.position, fill_rect.size)
	add_child(_bar_track)

	_bar_fill = TexturedProgressFill.new()
	_bar_fill.texture = textures["fill"]
	_bar_fill.position = fill_rect.position
	_bar_fill.size = fill_rect.size
	_bar_fill.modulate = fill_color
	add_child(_bar_fill)

	_bar_frame = _make_texture_rect(textures["frame"], Vector2.ZERO, Vector2(bar_width, bar_height))
	add_child(_bar_frame)

	if show_label:
		_label = Label.new()
		_label.add_theme_font_size_override("font_size", 12)
		_label.add_theme_color_override("font_color", Color.WHITE)
		_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		_label.position = Vector2.ZERO
		_label.size = Vector2(bar_width, bar_height)
		add_child(_label)

	_update_display()


## Update the bar from an external resource value.
func update_value(current: float, maximum: float) -> void:
	_current = maxf(current, 0.0)
	_maximum = maxf(maximum, 1.0)
	_update_display()


## Toggle the sprint-exhaustion blink (wired from the movement SM's exhausted_changed).
func set_exhausted(active: bool) -> void:
	if _exhausted == active:
		return
	_exhausted = active
	set_process(active)
	if not active and _bar_frame != null:
		_bar_frame.modulate = Color.WHITE


func _process(_delta: float) -> void:
	if _bar_frame == null:
		return
	# Flash the frame red↔white so the empty bar still reads as "exhausted".
	var t := 0.5 + 0.5 * sin(Time.get_ticks_msec() / 80.0)
	_bar_frame.modulate = Color(1.0, 0.32, 0.32).lerp(Color.WHITE, t)


func _update_display() -> void:
	if _bar_fill == null:
		return
	var ratio := clampf(_current / _maximum, 0.0, 1.0)
	_bar_fill.progress = ratio
	if _label != null:
		_label.text = "%d / %d" % [roundi(_current), roundi(_maximum)]


func _get_fill_rect() -> Rect2:
	if bar_height <= 18.0:
		# Stamina: the 256-wide fill texture is squashed into this inset, so its right cap used to
		# render right at the frame's inner bevel and read as overflow — pull the right inset in.
		return Rect2(Vector2(6.0, 5.0), Vector2(bar_width - 16.0, bar_height - 10.0))
	return Rect2(Vector2(40.0, 9.0), Vector2(bar_width - 62.0, bar_height - 18.0))


func _get_textures() -> Dictionary:
	if bar_height <= 18.0:
		return {
			"frame": STAMINA_FRAME_TEXTURE,
			"track": STAMINA_TRACK_TEXTURE,
			"fill": STAMINA_FILL_TEXTURE,
		}
	return {
		"frame": MANA_FRAME_TEXTURE,
		"track": MANA_TRACK_TEXTURE,
		"fill": MANA_FILL_TEXTURE,
	}


func _make_texture_rect(texture: Texture2D, rect_position: Vector2, rect_size: Vector2) -> TextureRect:
	var texture_rect := TextureRect.new()
	texture_rect.texture = texture
	# IGNORE_SIZE so STRETCH_SCALE actually scales the texture down to `rect_size`. With the
	# default KEEP_SIZE the control's minimum size is forced up to the texture's native width
	# (the track sprite is 256 px), so the black track would render wider than the frame.
	texture_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	texture_rect.stretch_mode = TextureRect.STRETCH_SCALE
	texture_rect.position = rect_position
	texture_rect.size = rect_size
	texture_rect.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	texture_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return texture_rect
