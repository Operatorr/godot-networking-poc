## Display typography for headings/actions; body text keeps the readable system font.
extends RefCounted

const MENU_FONT: FontFile = preload("res://assets/fonts/CormorantUnicase-Bold.ttf")


static func apply_to_tree(root: Node) -> void:
	if root is Button and not (root is CheckButton or root is CheckBox):
		root.add_theme_font_override("font", MENU_FONT)
	elif root is Label and ("Title" in root.name or "Heading" in root.name):
		root.add_theme_font_override("font", MENU_FONT)
	for child in root.get_children():
		apply_to_tree(child)
