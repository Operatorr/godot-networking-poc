## MenuFontHelper - Applies the menu display font to every text-bearing Control.
extends RefCounted

const MENU_FONT: FontFile = preload("res://assets/fonts/CormorantUnicase-Bold.ttf")


static func apply_to_tree(root: Node) -> void:
	_apply_to_node(root)


static func _apply_to_node(node: Node) -> void:
	if node is Control:
		var control := node as Control
		control.add_theme_font_override("font", MENU_FONT)

		if control is OptionButton:
			var option_button := control as OptionButton
			option_button.get_popup().add_theme_font_override("font", MENU_FONT)

		if control is ColorPickerButton:
			var color_picker_button := control as ColorPickerButton
			_apply_to_node(color_picker_button.get_picker())

	for child in node.get_children():
		_apply_to_node(child)
