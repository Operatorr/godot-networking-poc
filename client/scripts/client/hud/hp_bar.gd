## HPBarControl - Bottom-center HP bar display
## Shows current/max HP with color-coded progress bar
extends Control


var _bar_bg: ColorRect = null
var _bar_fill: ColorRect = null
var _hp_label: Label = null

var _current_hp: int = 100
var _max_hp: int = 100
var _flash_timer: float = 0.0

const BAR_WIDTH := 300.0
const BAR_HEIGHT := 24.0
const DAMAGE_FLASH_SECONDS := 0.3


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(false)


func _build_ui() -> void:
	# Position at bottom center
	set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	position = Vector2(-BAR_WIDTH / 2.0, -60)
	size = Vector2(BAR_WIDTH, BAR_HEIGHT + 30)

	# Bar background
	_bar_bg = ColorRect.new()
	_bar_bg.color = Color(0.15, 0.15, 0.15, 0.9)
	_bar_bg.position = Vector2.ZERO
	_bar_bg.size = Vector2(BAR_WIDTH, BAR_HEIGHT)
	add_child(_bar_bg)

	# Bar fill
	_bar_fill = ColorRect.new()
	_bar_fill.color = Color(0.2, 0.8, 0.2)
	_bar_fill.position = Vector2(2, 2)
	_bar_fill.size = Vector2(BAR_WIDTH - 4, BAR_HEIGHT - 4)
	add_child(_bar_fill)

	# HP text
	_hp_label = Label.new()
	_hp_label.add_theme_font_size_override("font_size", 14)
	_hp_label.add_theme_color_override("font_color", Color.WHITE)
	_hp_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hp_label.position = Vector2(0, 2)
	_hp_label.size = Vector2(BAR_WIDTH, BAR_HEIGHT)
	add_child(_hp_label)

	_update_display()


func _process(delta: float) -> void:
	if _flash_timer > 0.0:
		_flash_timer -= delta
		_bar_fill.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 50.0)
		if _flash_timer <= 0.0:
			_bar_fill.modulate.a = 1.0
			set_process(false)


## Update HP from external source
func update_hp(current: int, max_hp: int) -> void:
	current = maxi(current, 0)
	max_hp = maxi(max_hp, 1)
	if current == _current_hp and max_hp == _max_hp:
		return

	var took_damage := current < _current_hp
	_current_hp = current
	_max_hp = max_hp
	_update_display()
	if took_damage:
		_flash_timer = DAMAGE_FLASH_SECONDS
		set_process(true)


func _update_display() -> void:
	if _hp_label == null:
		return

	_hp_label.text = "%d / %d HP" % [_current_hp, _max_hp]

	var ratio := clampf(float(_current_hp) / float(_max_hp), 0.0, 1.0)
	_bar_fill.size.x = (BAR_WIDTH - 4) * ratio

	# Color gradient: green -> yellow -> red
	if ratio > 0.6:
		_bar_fill.color = Color(0.2, 0.8, 0.2)
	elif ratio > 0.3:
		_bar_fill.color = Color(0.9, 0.7, 0.1)
	else:
		_bar_fill.color = Color(0.9, 0.2, 0.1)
