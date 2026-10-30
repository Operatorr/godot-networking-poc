## PauseMenu - Esc-toggle pause overlay (game keeps running in the background).
##
## Authored as scenes/ui/hud/pause_menu.tscn (centered panel with Resume / Settings / Leave
## buttons + an instanced SettingsMenu child). Resume returns to gameplay; Leave emits
## leave_arena_requested (the level decides where that goes — see set_leave_button_text()).
extends Control

signal leave_arena_requested

@onready var _leave_button: Button = $Center/Panel/VBox/LeaveButton
@onready var _settings_menu: Control = $SettingsMenu


func _ready() -> void:
	visible = false
	mouse_filter = Control.MOUSE_FILTER_STOP
	$Center/Panel/VBox/ResumeButton.pressed.connect(_on_resume_pressed)
	$Center/Panel/VBox/SettingsButton.pressed.connect(_on_settings_pressed)
	_leave_button.pressed.connect(_on_leave_pressed)
	if _settings_menu and _settings_menu.has_signal("back_pressed"):
		_settings_menu.back_pressed.connect(_on_settings_back)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("pause_menu"):
		if visible and _settings_menu.visible:
			_settings_menu.go_back()
		else:
			toggle()
		get_viewport().set_input_as_handled()


## Override the leave button's label to match where it sends the player.
func set_leave_button_text(text: String) -> void:
	if _leave_button:
		_leave_button.text = text


## Toggle pause menu visibility.
func toggle() -> void:
	visible = not visible
	_settings_menu.visible = false
	$Center.visible = true
	if visible:
		$Center/Panel/VBox/ResumeButton.grab_focus()
	else:
		_release_menu_focus()


func _on_resume_pressed() -> void:
	visible = false
	_release_menu_focus()


func _on_settings_pressed() -> void:
	if _settings_menu:
		$Center.visible = false
		_settings_menu.visible = true
		_settings_menu.get_node("Panel/VBox/MasterRow/MasterSlider").grab_focus()


func _on_settings_back() -> void:
	$Center.visible = true
	$Center/Panel/VBox/SettingsButton.grab_focus()


func _release_menu_focus() -> void:
	var focused := get_viewport().gui_get_focus_owner()
	if focused != null and is_ancestor_of(focused):
		focused.release_focus()


func _on_leave_pressed() -> void:
	visible = false
	leave_arena_requested.emit()
