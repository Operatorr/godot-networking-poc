## SettingsMenu - in-game settings panel accessible from the pause menu.
##
## Authored as scenes/ui/hud/settings_menu.tscn: the main panel (volume sliders, fullscreen /
## vsync toggles, buttons) and the Keyboard Controls sub-page shell are authored nodes; only
## the per-action rebind rows are generated in code (they're data-driven from REBINDABLE_ACTIONS).
extends Control

signal back_pressed

## Keyboard Controls sub-page state.
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
	["toggle_map", "Toggle Map"],
	["return_to_sanctuary", "Return to Sanctuary"],
	["exit_to_menu", "Exit to Menu"],
	["pause_menu", "Pause"],
]

@onready var _panel: PanelContainer = $Panel
@onready var _master_slider: HSlider = $Panel/VBox/MasterRow/MasterSlider
@onready var _master_value: Label = $Panel/VBox/MasterRow/MasterValue
@onready var _music_slider: HSlider = $Panel/VBox/MusicRow/MusicSlider
@onready var _music_value: Label = $Panel/VBox/MusicRow/MusicValue
@onready var _sfx_slider: HSlider = $Panel/VBox/SfxRow/SfxSlider
@onready var _sfx_value: Label = $Panel/VBox/SfxRow/SfxValue
@onready var _fullscreen_check: CheckButton = $Panel/VBox/FullscreenCheck
@onready var _vsync_check: CheckButton = $Panel/VBox/VsyncCheck
@onready var _controls_panel: PanelContainer = $ControlsPanel
@onready var _rows: VBoxContainer = $ControlsPanel/VBox/Scroll/Rows


func _ready() -> void:
	visible = false
	_prefs = UserPreferences.load_preferences()

	# Update each slider's percentage label live (matches the old build-time wiring).
	_master_slider.value_changed.connect(func(v: float): _master_value.text = "%d%%" % int(v * 100))
	_music_slider.value_changed.connect(func(v: float): _music_value.text = "%d%%" % int(v * 100))
	_sfx_slider.value_changed.connect(func(v: float): _sfx_value.text = "%d%%" % int(v * 100))

	_fullscreen_check.toggled.connect(_on_fullscreen_toggled)
	_vsync_check.toggled.connect(_on_vsync_toggled)
	$Panel/VBox/ControlsButton.pressed.connect(_show_controls)
	$Panel/VBox/BackButton.pressed.connect(_on_back_pressed)
	$ControlsPanel/VBox/ButtonRow/ResetButton.pressed.connect(_on_reset_keybinds)
	$ControlsPanel/VBox/ButtonRow/BackButton.pressed.connect(_hide_controls)

	_build_rebind_rows()
	_load_settings()


func _load_settings() -> void:
	var game_mgr := _get_game_manager()
	if game_mgr == null:
		return

	_master_slider.value = game_mgr.settings.get("master_volume", 1.0)
	_music_slider.value = game_mgr.settings.get("music_volume", 0.8)
	_sfx_slider.value = game_mgr.settings.get("sfx_volume", 1.0)
	# The "Fullscreen" toggle reflects window_mode (the launch-mode setting). Tolerate the
	# legacy boolean "fullscreen" key for settings files written before the migration.
	var mode := str(game_mgr.settings.get("window_mode", ""))
	if mode == "":
		mode = "windowed_fullscreen" if bool(game_mgr.settings.get("fullscreen", true)) else "windowed"
	# Use the no-signal setters so loading these toggles doesn't fire toggled -> re-apply
	# the window mode / vsync and write to disk on every open (the sliders avoid this by
	# connecting their value_changed handlers below, after their values are set).
	_fullscreen_check.set_pressed_no_signal(mode == "windowed_fullscreen")
	_vsync_check.set_pressed_no_signal(game_mgr.settings.get("vsync", true))

	# Connect slider changes after loading values (so loading doesn't re-apply audio).
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
	# Deliberate asymmetry: fullscreen persists IMMEDIATELY via GameManager.update_setting
	# (which writes to disk), because a window-mode flip is disruptive enough to be worth
	# remembering even if the user never confirms. Volume and vsync instead use the in-memory
	# _update_setting helper and rely on GameManager flushing settings on close/quit.
	# Route through GameManager so it stores window_mode AND applies it (windowed-fullscreen vs
	# a small centered window) the same way the standalone Settings screen and boot do.
	var game_mgr := _get_game_manager()
	if game_mgr:
		game_mgr.update_setting("window_mode", "windowed_fullscreen" if pressed else "windowed")
	elif pressed:
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

## Build one rebind row per action into the authored Rows container.
func _build_rebind_rows() -> void:
	for entry: Array in REBINDABLE_ACTIONS:
		var action_name := String(entry[0])
		if not InputMap.has_action(action_name):
			continue
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		_rows.add_child(row)

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
			var key_name := OS.get_keycode_string(physical)
			return key_name if not key_name.is_empty() else "—"
	return "—"
