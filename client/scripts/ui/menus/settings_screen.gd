## SettingsScreen - standalone Settings menu reached from the main menu's Settings button.
##
## A tabbed screen (Audio / Video / Controls) built entirely in code so there are no fragile
## node-path couplings:
##   • Audio   — Master / Music / SFX volume sliders, the same settings the in-game pause menu
##               exposes (wired through GameManager.update_setting → AudioManager).
##   • Video   — a "Windowed Fullscreen" toggle (on = borderless windowed-fullscreen, off = a
##               small window) plus a VSync toggle. Each toggle applies immediately and is
##               remembered for next launch.
##   • Controls — a read-only listing of every game control and its current binding.
## A Back button returns to the main menu. See docs/systems/UI-HUD.md.
extends Control

const MenuFontHelper := preload("res://scripts/ui/helpers/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")

## Read-only control listing for the Controls tab: [action_name, display_label]. Order is the
## order shown. Mouse-bound actions (shoot/ability) are included; the binding text is resolved
## live from the InputMap so rebinds done in the pause menu are reflected here.
const CONTROL_ROWS := [
	["move_up", "Move Up"],
	["move_down", "Move Down"],
	["move_left", "Move Left"],
	["move_right", "Move Right"],
	["shoot", "Shoot"],
	["ability", "Ability"],
	["dash", "Dash"],
	["sprint", "Sprint"],
	["interact", "Interact"],
	["toggle_map", "Toggle Map"],
	["pause_menu", "Pause Menu"],
	["return_to_sanctuary", "Return to Sanctuary"],
	["exit_to_menu", "Exit to Menu"],
]

var _back_button: Button = null

func _ready() -> void:
	_build_ui()
	MenuFontHelper.apply_to_tree(self)
	# Seed focus so keyboard/controller navigation works on this fullscreen menu.
	if is_instance_valid(_back_button):
		_back_button.grab_focus()


# =============================================================================
# Layout
# =============================================================================

func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.03, 0.05, 1.0)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var col := VBoxContainer.new()
	col.custom_minimum_size = Vector2(640, 0)
	col.add_theme_constant_override("separation", 16)
	center.add_child(col)

	var title := Label.new()
	title.text = "SETTINGS"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 40)
	title.add_theme_color_override("font_color", Color(0.9, 0.85, 0.8))
	col.add_child(title)

	var tabs := TabContainer.new()
	tabs.custom_minimum_size = Vector2(640, 460)
	tabs.add_child(_build_audio_tab())
	tabs.add_child(_build_video_tab())
	tabs.add_child(_build_controls_tab())
	col.add_child(tabs)

	var back := Button.new()
	back.text = "Back"
	back.custom_minimum_size = Vector2(320, 64)
	back.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	back.add_theme_font_size_override("font_size", 20)
	# Play the click SFX inside the handler, before navigation tears down the scene.
	back.pressed.connect(_on_back_pressed)
	back.mouse_entered.connect(func(): AudioManager.play_button_hover())
	col.add_child(back)
	MenuButtonHelper.apply_to_buttons([back])
	_back_button = back


# =============================================================================
# Audio tab
# =============================================================================

func _build_audio_tab() -> Control:
	var page := MarginContainer.new()
	page.name = "Audio"
	_pad(page)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 18)
	page.add_child(vbox)

	_add_volume_row(vbox, "Master Volume", _current_setting("master_volume", 1.0), _on_master_changed)
	_add_volume_row(vbox, "Music Volume", _current_setting("music_volume", 0.8), _on_music_changed)
	_add_volume_row(vbox, "SFX Volume", _current_setting("sfx_volume", 1.0), _on_sfx_changed)
	return page


## Build one labelled volume slider row with a live percentage label.
func _add_volume_row(
		parent: VBoxContainer, label_text: String, value: float, on_changed: Callable
) -> void:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	parent.add_child(row)

	var label := Label.new()
	label.text = label_text
	label.custom_minimum_size = Vector2(160, 0)
	label.add_theme_font_size_override("font_size", 18)
	row.add_child(label)

	var slider := HSlider.new()
	slider.min_value = 0.0
	slider.max_value = 1.0
	slider.step = 0.05
	slider.value = value
	slider.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	slider.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(slider)

	var value_label := Label.new()
	value_label.text = "%d%%" % int(round(value * 100.0))
	value_label.custom_minimum_size = Vector2(56, 0)
	value_label.add_theme_font_size_override("font_size", 16)
	row.add_child(value_label)

	slider.value_changed.connect(func(v: float): value_label.text = "%d%%" % int(round(v * 100.0)))
	slider.value_changed.connect(on_changed)


func _on_master_changed(v: float) -> void:
	_persist_setting("master_volume", v)


func _on_music_changed(v: float) -> void:
	_persist_setting("music_volume", v)


func _on_sfx_changed(v: float) -> void:
	_persist_setting("sfx_volume", v)


# =============================================================================
# Video tab
# =============================================================================

func _build_video_tab() -> Control:
	var page := MarginContainer.new()
	page.name = "Video"
	_pad(page)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 18)
	page.add_child(vbox)

	var hint := Label.new()
	hint.text = "Window"
	hint.add_theme_font_size_override("font_size", 16)
	hint.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
	vbox.add_child(hint)

	var fullscreen_check := CheckButton.new()
	fullscreen_check.text = "Windowed Fullscreen"
	fullscreen_check.tooltip_text = "On: borderless windowed-fullscreen. Off: a small window."
	fullscreen_check.add_theme_font_size_override("font_size", 18)
	fullscreen_check.button_pressed = _current_window_mode() == "windowed_fullscreen"
	fullscreen_check.toggled.connect(_on_windowed_fullscreen_toggled)
	vbox.add_child(fullscreen_check)

	var vsync_check := CheckButton.new()
	vsync_check.text = "VSync"
	vsync_check.add_theme_font_size_override("font_size", 18)
	vsync_check.button_pressed = bool(_current_setting("vsync", true))
	vsync_check.toggled.connect(_on_vsync_toggled)
	vbox.add_child(vsync_check)

	return page


func _on_windowed_fullscreen_toggled(pressed: bool) -> void:
	_persist_setting("window_mode", "windowed_fullscreen" if pressed else "windowed")


func _on_vsync_toggled(pressed: bool) -> void:
	_persist_setting("vsync", pressed)


# =============================================================================
# Controls tab (read-only listing)
# =============================================================================

func _build_controls_tab() -> Control:
	var page := MarginContainer.new()
	page.name = "Controls"
	_pad(page)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 8)
	page.add_child(vbox)

	var hint := Label.new()
	hint.text = "Rebind keyboard controls from the in-game pause menu."
	hint.add_theme_font_size_override("font_size", 13)
	hint.add_theme_color_override("font_color", Color(0.55, 0.55, 0.55))
	vbox.add_child(hint)

	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(0, 360)
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.add_child(scroll)

	var rows := VBoxContainer.new()
	rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rows.add_theme_constant_override("separation", 6)
	scroll.add_child(rows)

	for entry: Array in CONTROL_ROWS:
		var action_name := String(entry[0])
		if not InputMap.has_action(action_name):
			continue
		var row := HBoxContainer.new()
		row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_theme_constant_override("separation", 10)
		rows.add_child(row)

		var name_label := Label.new()
		name_label.text = String(entry[1])
		name_label.custom_minimum_size = Vector2(260, 0)
		name_label.add_theme_font_size_override("font_size", 16)
		row.add_child(name_label)

		var key_label := Label.new()
		key_label.text = _binding_label_for_action(action_name)
		key_label.add_theme_font_size_override("font_size", 16)
		key_label.add_theme_color_override("font_color", Color(0.85, 0.8, 0.6))
		key_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(key_label)

	return page


## Human-readable binding (key name or mouse button) for an action's first event.
func _binding_label_for_action(action_name: String) -> String:
	for event in InputMap.action_get_events(action_name):
		if event is InputEventKey:
			var key_event := event as InputEventKey
			var physical := key_event.physical_keycode
			if physical == 0:
				physical = key_event.keycode
			var key_name := OS.get_keycode_string(physical)
			if not key_name.is_empty():
				return key_name
		elif event is InputEventMouseButton:
			match (event as InputEventMouseButton).button_index:
				MOUSE_BUTTON_LEFT:
					return "Left Mouse"
				MOUSE_BUTTON_RIGHT:
					return "Right Mouse"
				MOUSE_BUTTON_MIDDLE:
					return "Middle Mouse"
				_:
					return "Mouse Button"
	return "—"


# =============================================================================
# Helpers
# =============================================================================

func _pad(container: MarginContainer) -> void:
	for side in ["left", "right", "top", "bottom"]:
		container.add_theme_constant_override("margin_" + side, 24)


## Read a GameManager setting with a fallback (GameManager is an autoload singleton).
func _current_setting(key: String, default_value: Variant) -> Variant:
	if GameManager and GameManager.settings.has(key):
		return GameManager.settings[key]
	return default_value


## Resolve the current window mode, tolerating the legacy boolean "fullscreen" key.
func _current_window_mode() -> String:
	if GameManager == null:
		return "windowed_fullscreen"
	if GameManager.settings.has("window_mode"):
		return str(GameManager.settings["window_mode"])
	if GameManager.settings.has("fullscreen"):
		return "windowed_fullscreen" if bool(GameManager.settings["fullscreen"]) else "windowed"
	return "windowed_fullscreen"


## Persist + apply a setting through GameManager.update_setting (which stores it, applies it, and
## emits settings_changed so AudioManager re-applies volumes and window_mode / vsync take effect).
func _persist_setting(key: String, value: Variant) -> void:
	if GameManager:
		GameManager.update_setting(key, value)


func _on_back_pressed() -> void:
	AudioManager.play_button_click()
	SceneManager.return_from_settings()
