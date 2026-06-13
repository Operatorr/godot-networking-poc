## ThemedButton - reusable button that wears the shared Omega Realm button art.
##
## Drop this script onto any Button (or `ThemedButton.new()`) so every button in the
## game looks the same. By default it keeps the button's own size (compact buttons like
## the delete button or dialog actions); set `enforce_min_size` to also apply the large
## full-width menu-button sizing.
class_name ThemedButton
extends Button

const MenuButtonHelper := preload("res://scripts/client/ui/menu_button_helper.gd")

## When true, also stretch to the standard 320×72 menu-button size.
@export var enforce_min_size: bool = false


func _ready() -> void:
	MenuButtonHelper.apply_to_button(self, enforce_min_size)
