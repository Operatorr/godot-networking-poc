## Shared button sizing; visual states come from the project Theme.
extends RefCounted

const BUTTON_MINIMUM_SIZE := Vector2(320, 52)


static func apply_to_buttons(buttons: Array[Button]) -> void:
	for button in buttons:
		apply_to_button(button)


static func apply_to_button(button: Button, enforce_min_size: bool = true) -> void:
	button.flat = false
	if enforce_min_size:
		button.custom_minimum_size = Vector2(maxf(button.custom_minimum_size.x, BUTTON_MINIMUM_SIZE.x), BUTTON_MINIMUM_SIZE.y)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.add_theme_font_size_override("font_size", 22 if enforce_min_size else 16)
