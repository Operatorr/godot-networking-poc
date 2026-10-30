## DialogStyle - shared visual style for modal popups (error + confirm prompts) so every
## dialog in the game follows the shared iron/bone/crimson theme. Used via preload, not a
## global class_name, so it resolves in headless startup (matches MenuButtonHelper).
extends RefCounted

const SHARED_THEME: Theme = preload("res://themes/grimdark.tres")
const TEXT_PRIMARY := Color(0.85, 0.82, 0.74, 1.0)
const TEXT_SECONDARY := Color(0.68, 0.67, 0.61, 1.0)


## Apply the shared panel background/border/shadow to a PopupPanel.
static func apply_panel_style(popup: PopupPanel) -> void:
	popup.add_theme_stylebox_override("panel", SHARED_THEME.get_stylebox("panel", "PopupPanel"))


## Apply the shared title/message font colors.
static func apply_text_colors(title_label: Label, message_label: Label) -> void:
	title_label.add_theme_color_override("font_color", TEXT_PRIMARY)
	title_label.theme_type_variation = &"DisplayLabel"
	message_label.add_theme_color_override("font_color", TEXT_SECONDARY)
