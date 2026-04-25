## ErrorDialog - Reusable error dialog controller
## Shows error messages with retry and close options
extends PopupPanel

## Signals
signal retry_pressed
signal closed

## UI node references
@onready var title_label: Label = $MarginContainer/VBoxContainer/TitleLabel
@onready var message_label: Label = $MarginContainer/VBoxContainer/MessageLabel
@onready var retry_button: Button = $MarginContainer/VBoxContainer/ButtonContainer/RetryButton
@onready var close_button: Button = $MarginContainer/VBoxContainer/ButtonContainer/CloseButton

## Dialog configuration
var show_retry: bool = true

const PURPLE_BASE := Color(0.13, 0.05, 0.22, 1.0)
const PURPLE_BORDER := Color(0.46, 0.18, 0.74, 1.0)
const TEXT_PRIMARY := Color(0.92, 0.86, 1.0, 1.0)
const TEXT_SECONDARY := Color(0.78, 0.68, 0.9, 1.0)


func _ready() -> void:
	_apply_theme()

	# Connect button signals
	retry_button.pressed.connect(_on_retry_pressed)
	close_button.pressed.connect(_on_close_pressed)

	# Connect popup close signal
	popup_hide.connect(_on_popup_hide)


func _apply_theme() -> void:
	var panel_style := StyleBoxFlat.new()
	panel_style.bg_color = PURPLE_BASE
	panel_style.border_color = PURPLE_BORDER
	panel_style.set_border_width_all(2)
	panel_style.corner_radius_top_left = 8
	panel_style.corner_radius_top_right = 8
	panel_style.corner_radius_bottom_left = 8
	panel_style.corner_radius_bottom_right = 8
	panel_style.shadow_color = Color(0.0, 0.0, 0.0, 0.45)
	panel_style.shadow_size = 18
	add_theme_stylebox_override("panel", panel_style)

	title_label.add_theme_color_override("font_color", TEXT_PRIMARY)
	message_label.add_theme_color_override("font_color", TEXT_SECONDARY)


## Show the error dialog with title and message
func show_error(error_title: String, error_message: String, allow_retry: bool = true) -> void:
	title_label.text = error_title
	message_label.text = error_message
	show_retry = allow_retry
	retry_button.visible = allow_retry

	# Center on screen and show
	popup_centered()
	call_deferred("_focus_message")


func _focus_message() -> void:
	message_label.focus_mode = Control.FOCUS_ALL
	message_label.grab_focus()
	retry_button.release_focus()
	close_button.release_focus()


## Hide the dialog
func hide_dialog() -> void:
	hide()


func _on_retry_pressed() -> void:
	hide()
	retry_pressed.emit()


func _on_close_pressed() -> void:
	hide()


func _on_popup_hide() -> void:
	closed.emit()
