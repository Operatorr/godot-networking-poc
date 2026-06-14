## ConfirmDialog - reusable confirm/cancel modal that shares the game's dialog design
## (same purple panel + themed buttons as ErrorDialog). Use for any "are you sure?" prompt.
##
##   var dlg := ConfirmDialogScene.instantiate()
##   add_child(dlg)
##   dlg.confirmed.connect(_do_the_thing)
##   dlg.show_confirm("Delete Character", "Permanently delete X?", "Delete", "Cancel")
extends PopupPanel

signal confirmed
signal cancelled

const DialogStyle := preload("res://scripts/ui/dialogs/dialog_style.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")

@onready var title_label: Label = $MarginContainer/VBoxContainer/TitleLabel
@onready var message_label: Label = $MarginContainer/VBoxContainer/MessageLabel
@onready var confirm_button: Button = $MarginContainer/VBoxContainer/ButtonContainer/ConfirmButton
@onready var cancel_button: Button = $MarginContainer/VBoxContainer/ButtonContainer/CancelButton

## Guards the popup_hide handler so an explicit Confirm/Cancel doesn't double-emit.
var _decided: bool = false


func _ready() -> void:
	DialogStyle.apply_panel_style(self)
	DialogStyle.apply_text_colors(title_label, message_label)
	MenuButtonHelper.apply_to_button(confirm_button, false)
	MenuButtonHelper.apply_to_button(cancel_button, false)

	confirm_button.pressed.connect(_on_confirm)
	cancel_button.pressed.connect(_on_cancel)
	popup_hide.connect(_on_popup_hide)


## Show the prompt. confirm_text/cancel_text label the two buttons.
func show_confirm(
	dialog_title: String,
	message: String,
	confirm_text: String = "Confirm",
	cancel_text: String = "Cancel"
) -> void:
	title_label.text = dialog_title
	message_label.text = message
	confirm_button.text = confirm_text
	cancel_button.text = cancel_text
	_decided = false
	popup_centered()
	cancel_button.grab_focus()


func _on_confirm() -> void:
	_decided = true
	hide()
	confirmed.emit()


func _on_cancel() -> void:
	_decided = true
	hide()
	cancelled.emit()


## Closing via Esc / click-outside counts as a cancel.
func _on_popup_hide() -> void:
	if not _decided:
		_decided = true
		cancelled.emit()
