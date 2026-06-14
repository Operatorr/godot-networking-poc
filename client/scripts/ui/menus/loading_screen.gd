## LoadingScreen - Dark atmospheric loading overlay
## Pulsing bioluminescent text with cosmic horror aesthetic
extends Control


var _title_label: Label = null
var _dots_label: Label = null
var _dot_timer: float = 0.0
var _dot_count: int = 0
const DOT_INTERVAL := 0.4


func _ready() -> void:
	_build_ui()


func _build_ui() -> void:
	# Full-screen dark background
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.02, 0.06, 1.0)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	# Center container
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 8)
	center.add_child(vbox)

	# Title
	_title_label = Label.new()
	_title_label.text = "ENTERING THE ARENA"
	_title_label.add_theme_font_size_override("font_size", 36)
	_title_label.add_theme_color_override("font_color", Color(0.27, 0.53, 1.0))
	_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(_title_label)

	# Animated dots
	_dots_label = Label.new()
	_dots_label.text = "."
	_dots_label.add_theme_font_size_override("font_size", 36)
	_dots_label.add_theme_color_override("font_color", Color(0.4, 1.0, 0.8))
	_dots_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(_dots_label)


func _process(delta: float) -> void:
	# Animate dots
	_dot_timer += delta
	if _dot_timer >= DOT_INTERVAL:
		_dot_timer -= DOT_INTERVAL
		_dot_count = (_dot_count + 1) % 4
		_dots_label.text = ".".repeat(_dot_count + 1)

	# Pulse title glow
	var t := Time.get_ticks_msec() / 1000.0
	var pulse := 0.6 + 0.4 * sin(t * TAU * 0.5)
	_title_label.modulate.a = pulse


## Called by SceneManager
func show_loading() -> void:
	visible = true


## Called by SceneManager
func hide_loading() -> void:
	visible = false
