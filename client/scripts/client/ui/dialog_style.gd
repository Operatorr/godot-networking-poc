## DialogStyle - shared visual style for modal popups (error + confirm prompts) so every
## dialog in the game follows the same purple cosmic-horror design. Used via preload, not a
## global class_name, so it resolves in headless startup (matches MenuButtonHelper).
extends RefCounted

const PURPLE_BASE := Color(0.13, 0.05, 0.22, 1.0)
const PURPLE_BORDER := Color(0.46, 0.18, 0.74, 1.0)
const TEXT_PRIMARY := Color(0.92, 0.86, 1.0, 1.0)
const TEXT_SECONDARY := Color(0.78, 0.68, 0.9, 1.0)


## Apply the shared panel background/border/shadow to a PopupPanel.
static func apply_panel_style(popup: PopupPanel) -> void:
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
	popup.add_theme_stylebox_override("panel", panel_style)


## Apply the shared title/message font colors.
static func apply_text_colors(title_label: Label, message_label: Label) -> void:
	title_label.add_theme_color_override("font_color", TEXT_PRIMARY)
	message_label.add_theme_color_override("font_color", TEXT_SECONDARY)
