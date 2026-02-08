## ConnectionLostOverlay - Shown when connection to server is lost
## Displays reconnection status and handles timeout
extends Control


var _status_label: Label = null
var _spinner_angle: float = 0.0
var _reconnect_timeout: float = 15.0
var _timer: float = 0.0
var _is_active: bool = false

signal reconnect_failed


func _ready() -> void:
	_build_ui()
	visible = false
	mouse_filter = Control.MOUSE_FILTER_STOP


func _build_ui() -> void:
	# Full-screen dark overlay
	var bg := ColorRect.new()
	bg.color = Color(0.0, 0.0, 0.0, 0.85)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(bg)

	# Center container
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 20)
	center.add_child(vbox)

	# Title
	var title := Label.new()
	title.text = "CONNECTION LOST"
	title.add_theme_font_size_override("font_size", 32)
	title.add_theme_color_override("font_color", Color(1.0, 0.3, 0.3))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	# Status
	_status_label = Label.new()
	_status_label.text = "Attempting to reconnect..."
	_status_label.add_theme_font_size_override("font_size", 18)
	_status_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7))
	_status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(_status_label)


func _process(delta: float) -> void:
	if not _is_active:
		return

	_timer += delta
	if _timer >= _reconnect_timeout:
		_is_active = false
		_status_label.text = "Connection failed. Returning to main menu..."
		reconnect_failed.emit()


## Show the overlay (called when disconnect detected)
func show_overlay() -> void:
	_is_active = true
	_timer = 0.0
	_status_label.text = "Attempting to reconnect..."
	visible = true


## Hide the overlay (called when reconnected)
func hide_overlay() -> void:
	_is_active = false
	visible = false
