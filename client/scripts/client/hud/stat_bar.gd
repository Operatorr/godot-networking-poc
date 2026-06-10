## StatBar - Generic bottom-anchored resource bar (background + fill + optional label).
##
## Reusable Control used for the Stamina and Mana HUD bars. Position and size are
## configured from arena_base before the node enters the tree, so a single script
## drives several differently-shaped bars. Modelled on hp_bar.gd but without the
## HP-specific colour gradient / damage flash. Update it via update_value().
extends Control


var _bar_bg: ColorRect = null
var _bar_fill: ColorRect = null
var _label: Label = null

var _current: float = 0.0
var _maximum: float = 100.0

# --- Configuration (set by the owner BEFORE add_child, i.e. before _ready) ---
## Bar width in base-resolution pixels.
var bar_width: float = 300.0
## Bar height in base-resolution pixels.
var bar_height: float = 24.0
## Horizontal offset from the bottom-center anchor (negative = left of center).
## Owners always override this; default centers a 300-wide bar.
var offset_x: float = -150.0
## Vertical offset from the bottom anchor (negative = up from the bottom edge).
var offset_y: float = -60.0
## Fill colour.
var fill_color: Color = Color(0.2, 0.4, 0.9)
## Background colour.
var bg_color: Color = Color(0.15, 0.15, 0.15, 0.9)
## Whether to draw a centered numeric label.
var show_label: bool = false


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

	_bar_bg = ColorRect.new()
	_bar_bg.color = bg_color
	_bar_bg.position = Vector2.ZERO
	_bar_bg.size = Vector2(bar_width, bar_height)
	add_child(_bar_bg)

	_bar_fill = ColorRect.new()
	_bar_fill.color = fill_color
	_bar_fill.position = Vector2(2, 2)
	_bar_fill.size = Vector2(bar_width - 4, bar_height - 4)
	add_child(_bar_fill)

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


func _update_display() -> void:
	if _bar_fill == null:
		return
	var ratio := clampf(_current / _maximum, 0.0, 1.0)
	_bar_fill.size.x = (bar_width - 4) * ratio
	if _label != null:
		_label.text = "%d / %d" % [roundi(_current), roundi(_maximum)]
