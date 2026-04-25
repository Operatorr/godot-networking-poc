## SettingsMenu - In-game settings panel accessible from pause menu
## Volume sliders, fullscreen toggle, VSync toggle
extends Control

signal back_pressed

var _panel: PanelContainer = null
var _master_slider: HSlider = null
var _music_slider: HSlider = null
var _sfx_slider: HSlider = null
var _fullscreen_check: CheckButton = null
var _vsync_check: CheckButton = null


func _ready() -> void:
	visible = false
	_build_ui()
	_load_settings()


func _build_ui() -> void:
	# Dark overlay background
	var bg := ColorRect.new()
	bg.color = Color(0.0, 0.0, 0.0, 0.7)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(bg)

	# Center panel
	_panel = PanelContainer.new()
	_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	_panel.offset_left = -200
	_panel.offset_right = 200
	_panel.offset_top = -220
	_panel.offset_bottom = 220

	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.08, 0.06, 0.08, 0.95)
	style.border_color = Color(0.3, 0.1, 0.15)
	style.border_width_left = 2
	style.border_width_right = 2
	style.border_width_top = 2
	style.border_width_bottom = 2
	style.corner_radius_top_left = 8
	style.corner_radius_top_right = 8
	style.corner_radius_bottom_left = 8
	style.corner_radius_bottom_right = 8
	style.content_margin_left = 30
	style.content_margin_right = 30
	style.content_margin_top = 20
	style.content_margin_bottom = 20
	_panel.add_theme_stylebox_override("panel", style)
	add_child(_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 15)
	_panel.add_child(vbox)

	# Title
	var title := Label.new()
	title.text = "SETTINGS"
	title.add_theme_font_size_override("font_size", 28)
	title.add_theme_color_override("font_color", Color(0.9, 0.85, 0.8))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	# Separator
	vbox.add_child(HSeparator.new())

	# Master Volume
	_master_slider = _create_slider(vbox, "Master Volume")

	# Music Volume
	_music_slider = _create_slider(vbox, "Music Volume")

	# SFX Volume
	_sfx_slider = _create_slider(vbox, "SFX Volume")

	# Separator
	vbox.add_child(HSeparator.new())

	# Fullscreen
	_fullscreen_check = CheckButton.new()
	_fullscreen_check.text = "Fullscreen"
	_fullscreen_check.add_theme_font_size_override("font_size", 16)
	_fullscreen_check.toggled.connect(_on_fullscreen_toggled)
	vbox.add_child(_fullscreen_check)

	# VSync
	_vsync_check = CheckButton.new()
	_vsync_check.text = "VSync"
	_vsync_check.add_theme_font_size_override("font_size", 16)
	_vsync_check.toggled.connect(_on_vsync_toggled)
	vbox.add_child(_vsync_check)

	# Separator
	vbox.add_child(HSeparator.new())

	# Back button
	var back_btn := Button.new()
	back_btn.text = "BACK"
	back_btn.custom_minimum_size = Vector2(200, 40)
	back_btn.add_theme_font_size_override("font_size", 18)
	back_btn.pressed.connect(_on_back_pressed)
	vbox.add_child(back_btn)


func _create_slider(parent: VBoxContainer, label_text: String) -> HSlider:
	var hbox := HBoxContainer.new()
	hbox.add_theme_constant_override("separation", 10)
	parent.add_child(hbox)

	var label := Label.new()
	label.text = label_text
	label.add_theme_font_size_override("font_size", 16)
	label.custom_minimum_size = Vector2(130, 0)
	hbox.add_child(label)

	var slider := HSlider.new()
	slider.min_value = 0.0
	slider.max_value = 1.0
	slider.step = 0.05
	slider.value = 1.0
	slider.custom_minimum_size = Vector2(150, 20)
	slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	hbox.add_child(slider)

	var value_label := Label.new()
	value_label.text = "100%"
	value_label.add_theme_font_size_override("font_size", 14)
	value_label.custom_minimum_size = Vector2(45, 0)
	hbox.add_child(value_label)

	slider.value_changed.connect(func(val: float):
		value_label.text = "%d%%" % int(val * 100)
	)

	return slider


func _load_settings() -> void:
	var game_mgr := _get_game_manager()
	if game_mgr == null:
		return

	_master_slider.value = game_mgr.settings.get("master_volume", 1.0)
	_music_slider.value = game_mgr.settings.get("music_volume", 0.8)
	_sfx_slider.value = game_mgr.settings.get("sfx_volume", 1.0)
	_fullscreen_check.button_pressed = game_mgr.settings.get("fullscreen", false)
	_vsync_check.button_pressed = game_mgr.settings.get("vsync", true)

	# Connect slider changes after loading values
	_master_slider.value_changed.connect(_on_master_changed)
	_music_slider.value_changed.connect(_on_music_changed)
	_sfx_slider.value_changed.connect(_on_sfx_changed)


func _on_master_changed(val: float) -> void:
	_update_setting("master_volume", val)
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.set_master_volume(val)


func _on_music_changed(val: float) -> void:
	_update_setting("music_volume", val)
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.set_music_volume(val)


func _on_sfx_changed(val: float) -> void:
	_update_setting("sfx_volume", val)
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.set_sfx_volume(val)


func _on_fullscreen_toggled(pressed: bool) -> void:
	_update_setting("fullscreen", pressed)
	if pressed:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	else:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)


func _on_vsync_toggled(pressed: bool) -> void:
	_update_setting("vsync", pressed)
	DisplayServer.window_set_vsync_mode(
		DisplayServer.VSYNC_ENABLED if pressed else DisplayServer.VSYNC_DISABLED
	)


func _update_setting(key: String, value: Variant) -> void:
	var game_mgr := _get_game_manager()
	if game_mgr:
		game_mgr.settings[key] = value


func _on_back_pressed() -> void:
	visible = false
	back_pressed.emit()


func _get_game_manager() -> Node:
	return get_tree().root.get_node_or_null("GameManager")
