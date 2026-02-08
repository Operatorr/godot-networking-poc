## PauseMenu - Esc-toggle pause overlay
## Game continues running in background (multiplayer)
## Resume returns to gameplay, Leave Arena disconnects and returns to main menu
extends Control


signal leave_arena_requested

var _resume_button: Button = null
var _leave_button: Button = null


func _ready() -> void:
	_build_ui()
	visible = false
	mouse_filter = Control.MOUSE_FILTER_STOP


func _build_ui() -> void:
	# Full-screen semi-transparent background
	var bg := ColorRect.new()
	bg.color = Color(0.0, 0.0, 0.0, 0.7)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(bg)

	# Center container
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.12, 0.12, 0.12, 0.95)
	style.border_color = Color(0.4, 0.4, 0.4)
	style.border_width_top = 2
	style.border_width_bottom = 2
	style.border_width_left = 2
	style.border_width_right = 2
	style.corner_radius_top_left = 8
	style.corner_radius_top_right = 8
	style.corner_radius_bottom_left = 8
	style.corner_radius_bottom_right = 8
	style.content_margin_left = 40
	style.content_margin_right = 40
	style.content_margin_top = 40
	style.content_margin_bottom = 40
	panel.add_theme_stylebox_override("panel", style)
	center.add_child(panel)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 12)
	panel.add_child(vbox)

	# Title
	var title := Label.new()
	title.text = "PAUSED"
	title.add_theme_font_size_override("font_size", 36)
	title.add_theme_color_override("font_color", Color.WHITE)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	# Subtitle
	var subtitle := Label.new()
	subtitle.text = "Game continues in background"
	subtitle.add_theme_font_size_override("font_size", 14)
	subtitle.add_theme_color_override("font_color", Color(0.5, 0.5, 0.5))
	subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(subtitle)

	# Spacer
	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(0, 10)
	vbox.add_child(spacer)

	# Resume button
	_resume_button = Button.new()
	_resume_button.text = "RESUME"
	_resume_button.custom_minimum_size = Vector2(250, 48)
	_resume_button.add_theme_font_size_override("font_size", 18)
	_resume_button.pressed.connect(_on_resume_pressed)
	vbox.add_child(_resume_button)

	# Leave Arena button
	_leave_button = Button.new()
	_leave_button.text = "LEAVE ARENA"
	_leave_button.custom_minimum_size = Vector2(250, 48)
	_leave_button.add_theme_font_size_override("font_size", 18)
	_leave_button.pressed.connect(_on_leave_pressed)
	vbox.add_child(_leave_button)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause_menu"):
		toggle()
		get_viewport().set_input_as_handled()


## Toggle pause menu visibility
func toggle() -> void:
	visible = not visible


func _on_resume_pressed() -> void:
	visible = false


func _on_leave_pressed() -> void:
	visible = false
	leave_arena_requested.emit()
