## MenuButtonHelper - Applies the shared menu button art and sizing.
extends RefCounted

const BUTTON_TEXTURE_PATH := "res://assets/ui/buttons/login_button_normal.png"
const BUTTON_DISABLED_TEXTURE_PATH := "res://assets/ui/buttons/login_button_disabled.png"
const BUTTON_TEXTURE_MARGINS := Vector4(32, 18, 32, 18)
const BUTTON_MINIMUM_SIZE := Vector2(320, 72)
const BUTTON_STATE_COLORS := {
	"normal": Color(1.0, 1.0, 1.0, 1.0),
	"hover": Color(1.18, 1.18, 1.12, 1.0),
	"pressed": Color(0.62, 0.62, 0.58, 1.0),
	"disabled": Color(0.72, 0.72, 0.68, 0.82),
}


## Apply the shared button art + sizing to a list of full-size menu buttons.
static func apply_to_buttons(buttons: Array[Button]) -> void:
	var styleboxes := _build_styleboxes()
	if styleboxes.is_empty():
		return
	for button in buttons:
		_style_button(button, styleboxes, true)


## Apply the shared button art to a single button. `enforce_min_size` = false keeps the
## button's own (smaller) size — used by the reusable ThemedButton for compact buttons.
static func apply_to_button(button: Button, enforce_min_size: bool = true) -> void:
	var styleboxes := _build_styleboxes()
	if styleboxes.is_empty():
		return
	_style_button(button, styleboxes, enforce_min_size)


static func _build_styleboxes() -> Dictionary:
	var button_texture := load(BUTTON_TEXTURE_PATH) as Texture2D
	if not button_texture:
		push_warning("[MenuButtonHelper] Failed to load button texture: %s" % BUTTON_TEXTURE_PATH)
		return {}

	var disabled_button_texture := load(BUTTON_DISABLED_TEXTURE_PATH) as Texture2D
	if not disabled_button_texture:
		push_warning("[MenuButtonHelper] Failed to load disabled button texture: %s" % BUTTON_DISABLED_TEXTURE_PATH)
		disabled_button_texture = button_texture

	var button_styleboxes := {}
	for state: String in BUTTON_STATE_COLORS:
		var state_texture := disabled_button_texture if state == "disabled" else button_texture
		button_styleboxes[state] = _create_button_stylebox(state_texture, BUTTON_STATE_COLORS[state])
	return button_styleboxes


static func _style_button(button: Button, button_styleboxes: Dictionary, enforce_min_size: bool) -> void:
	button.flat = false
	if enforce_min_size:
		button.custom_minimum_size = Vector2(
			maxf(button.custom_minimum_size.x, BUTTON_MINIMUM_SIZE.x),
			maxf(button.custom_minimum_size.y, BUTTON_MINIMUM_SIZE.y)
		)
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.add_theme_font_size_override("font_size", 24 if enforce_min_size else 16)
	button.add_theme_color_override("font_color", Color(0.88, 0.86, 0.78))
	button.add_theme_color_override("font_hover_color", Color(1.0, 0.98, 0.9))
	button.add_theme_color_override("font_pressed_color", Color(0.62, 0.6, 0.54))
	button.add_theme_color_override("font_disabled_color", Color(0.46, 0.46, 0.43))

	button.add_theme_stylebox_override("normal", button_styleboxes["normal"])
	button.add_theme_stylebox_override("focus", button_styleboxes["normal"])
	button.add_theme_stylebox_override("hover", button_styleboxes["hover"])
	button.add_theme_stylebox_override("pressed", button_styleboxes["pressed"])
	button.add_theme_stylebox_override("disabled", button_styleboxes["disabled"])


static func _create_button_stylebox(texture: Texture2D, modulate_color: Color) -> StyleBoxTexture:
	var stylebox := StyleBoxTexture.new()
	stylebox.texture = texture
	stylebox.modulate_color = modulate_color
	stylebox.texture_margin_left = BUTTON_TEXTURE_MARGINS.x
	stylebox.texture_margin_top = BUTTON_TEXTURE_MARGINS.y
	stylebox.texture_margin_right = BUTTON_TEXTURE_MARGINS.z
	stylebox.texture_margin_bottom = BUTTON_TEXTURE_MARGINS.w
	stylebox.content_margin_left = 18.0
	stylebox.content_margin_top = 10.0
	stylebox.content_margin_right = 18.0
	stylebox.content_margin_bottom = 10.0
	return stylebox
