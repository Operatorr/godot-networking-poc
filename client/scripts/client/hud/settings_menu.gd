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

## Keyboard Controls sub-page.
var _controls_panel: PanelContainer = null
var _prefs: UserPreferences = null
var _rebind_buttons: Dictionary = {}  # action_name -> Button
var _listening_action: String = ""

## Actions exposed on the Keyboard Controls page: [action_name, display_label].
## Mouse-bound actions (shoot/ability) are intentionally omitted — this page rebinds
## keyboard keys only.
const REBINDABLE_ACTIONS := [
	["move_up", "Move Up"],
	["move_down", "Move Down"],
	["move_left", "Move Left"],
	["move_right", "Move Right"],
	["sprint", "Sprint"],
	["dash", "Dash"],
	["interact", "Interact"],
	["return_to_sanctuary", "Return to Sanctuary"],
	["exit_to_menu", "Exit to Menu"],
	["pause_menu", "Pause"],
]


func _ready() -> void:
	visible = false
	_prefs = UserPreferences.load_preferences()
	_build_ui()
	_build_controls_panel()
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

	# Keyboard Controls page
	var controls_btn := Button.new()
	controls_btn.text = "KEYBOARD CONTROLS"
	controls_btn.custom_minimum_size = Vector2(200, 40)
	controls_btn.add_theme_font_size_override("font_size", 18)
	controls_btn.pressed.connect(_show_controls)
	vbox.add_child(controls_btn)

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


# =============================================================================
# Keyboard Controls page
# =============================================================================

func _build_controls_panel() -> void:
	_controls_panel = PanelContainer.new()
	_controls_panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	_controls_panel.offset_left = -230
	_controls_panel.offset_right = 230
	_controls_panel.offset_top = -260
	_controls_panel.offset_bottom = 260

	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.08, 0.06, 0.08, 0.97)
	style.border_color = Color(0.3, 0.1, 0.15)
	style.border_width_left = 2
	style.border_width_right = 2
	style.border_width_top = 2
	style.border_width_bottom = 2
	style.corner_radius_top_left = 8
	style.corner_radius_top_right = 8
	style.corner_radius_bottom_left = 8
	style.corner_radius_bottom_right = 8
	style.content_margin_left = 28
	style.content_margin_right = 28
	style.content_margin_top = 20
	style.content_margin_bottom = 20
	_controls_panel.add_theme_stylebox_override("panel", style)
	_controls_panel.visible = false
	add_child(_controls_panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 10)
	_controls_panel.add_child(vbox)

	var title := Label.new()
	title.text = "KEYBOARD CONTROLS"
	title.add_theme_font_size_override("font_size", 24)
	title.add_theme_color_override("font_color", Color(0.9, 0.85, 0.8))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	var hint := Label.new()
	hint.text = "Click a key to rebind it. Esc cancels."
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color(0.5, 0.5, 0.5))
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(hint)

	vbox.add_child(HSeparator.new())

	# Scrollable list of action rows.
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(380, 320)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	vbox.add_child(scroll)

	var rows := VBoxContainer.new()
	rows.add_theme_constant_override("separation", 6)
	rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(rows)

	for entry: Array in REBINDABLE_ACTIONS:
		var action_name := String(entry[0])
		if not InputMap.has_action(action_name):
			continue
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		rows.add_child(row)

		var label := Label.new()
		label.text = String(entry[1])
		label.add_theme_font_size_override("font_size", 16)
		label.custom_minimum_size = Vector2(210, 0)
		row.add_child(label)

		var rebind_btn := Button.new()
		rebind_btn.custom_minimum_size = Vector2(150, 32)
		rebind_btn.add_theme_font_size_override("font_size", 14)
		rebind_btn.pressed.connect(_on_rebind_pressed.bind(action_name))
		row.add_child(rebind_btn)
		_rebind_buttons[action_name] = rebind_btn

	vbox.add_child(HSeparator.new())

	var btn_row := HBoxContainer.new()
	btn_row.add_theme_constant_override("separation", 10)
	btn_row.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_child(btn_row)

	var reset_btn := Button.new()
	reset_btn.text = "RESET TO DEFAULTS"
	reset_btn.custom_minimum_size = Vector2(190, 38)
	reset_btn.add_theme_font_size_override("font_size", 15)
	reset_btn.pressed.connect(_on_reset_keybinds)
	btn_row.add_child(reset_btn)

	var back_btn := Button.new()
	back_btn.text = "BACK"
	back_btn.custom_minimum_size = Vector2(150, 38)
	back_btn.add_theme_font_size_override("font_size", 15)
	back_btn.pressed.connect(_hide_controls)
	btn_row.add_child(back_btn)

	_refresh_keybind_labels()


func _show_controls() -> void:
	if _panel:
		_panel.visible = false
	if _controls_panel:
		_controls_panel.visible = true
	_refresh_keybind_labels()


func _hide_controls() -> void:
	_cancel_listening()
	if _controls_panel:
		_controls_panel.visible = false
	if _panel:
		_panel.visible = true


## Update every rebind button to show the key currently bound to its action.
func _refresh_keybind_labels() -> void:
	for action_name: Variant in _rebind_buttons.keys():
		var btn: Button = _rebind_buttons[action_name]
		if is_instance_valid(btn):
			btn.text = _key_label_for_action(String(action_name))


func _on_rebind_pressed(action_name: String) -> void:
	# Cancel any in-progress capture, then arm this one.
	_cancel_listening()
	_listening_action = action_name
	var btn: Button = _rebind_buttons.get(action_name, null)
	if is_instance_valid(btn):
		btn.text = "Press a key…"


func _cancel_listening() -> void:
	if _listening_action.is_empty():
		return
	var prev := _listening_action
	_listening_action = ""
	var btn: Button = _rebind_buttons.get(prev, null)
	if is_instance_valid(btn):
		btn.text = _key_label_for_action(prev)


func _input(event: InputEvent) -> void:
	if _listening_action.is_empty() or not visible:
		return
	if not (event is InputEventKey):
		return
	var key_event := event as InputEventKey
	if not key_event.pressed or key_event.echo:
		return

	get_viewport().set_input_as_handled()

	# Escape cancels the capture without changing the binding.
	if key_event.keycode == KEY_ESCAPE:
		_cancel_listening()
		return

	var physical := key_event.physical_keycode
	if physical == 0:
		physical = key_event.keycode
	var action_name := _listening_action
	_listening_action = ""

	if _prefs:
		_prefs.rebind_action_key(action_name, physical)
		_prefs.save()
	_refresh_keybind_labels()


func _on_reset_keybinds() -> void:
	_cancel_listening()
	if _prefs:
		_prefs.reset_keybinds_to_defaults()
		_prefs.save()
	_refresh_keybind_labels()


## Readable name of the keyboard key currently bound to an action.
func _key_label_for_action(action_name: String) -> String:
	if not InputMap.has_action(action_name):
		return "—"
	for event in InputMap.action_get_events(action_name):
		if event is InputEventKey:
			var key_event := event as InputEventKey
			var physical := key_event.physical_keycode
			if physical == 0:
				physical = key_event.keycode
			var name := OS.get_keycode_string(physical)
			return name if not name.is_empty() else "—"
	return "—"
