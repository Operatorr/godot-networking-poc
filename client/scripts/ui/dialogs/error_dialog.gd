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

const DialogStyle := preload("res://scripts/ui/dialogs/dialog_style.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")


func _ready() -> void:
	_apply_theme()

	# Connect button signals
	retry_button.pressed.connect(_on_retry_pressed)
	close_button.pressed.connect(_on_close_pressed)

	# Connect popup close signal
	popup_hide.connect(_on_popup_hide)


func _apply_theme() -> void:
	DialogStyle.apply_panel_style(self)
	DialogStyle.apply_text_colors(title_label, message_label)
	MenuButtonHelper.apply_to_button(retry_button, false)
	MenuButtonHelper.apply_to_button(close_button, false)


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
