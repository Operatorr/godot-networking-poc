## HealthBar - bottom-center HP bar (TextureProgressBar-backed scene).
##
## Authored as scenes/ui/hud/health_bar.tscn: a Track/Fill TextureProgressBar inside the
## trough inset, a Frame overlay, and a centered Label. Shows current/max HP and warms the
## fill colour as HP drops, with a brief damage flash. Drive it via update_hp().
class_name HealthBar
extends Control

const DAMAGE_FLASH_SECONDS := 0.3

var _current_hp: int = 100
var _max_hp: int = 100
var _flash_timer: float = 0.0

@onready var _fill: TextureProgressBar = $Fill
@onready var _label: Label = $Label


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(false)
	_update_display()


## Update HP from an external source.
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


func _process(delta: float) -> void:
	if _flash_timer <= 0.0:
		return
	_flash_timer -= delta
	var tint: Color = _fill.tint_progress
	if _flash_timer <= 0.0:
		tint.a = 1.0
		_fill.tint_progress = tint
		set_process(false)
		return
	tint.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 50.0)
	_fill.tint_progress = tint


func _update_display() -> void:
	if _fill == null or _label == null:
		return

	_label.text = "%d / %d HP" % [_current_hp, _max_hp]

	var ratio := clampf(float(_current_hp) / float(_max_hp), 0.0, 1.0)
	_fill.value = ratio

	var alpha: float = _fill.tint_progress.a
	# Keep the authored blood-red texture, but warm it as HP drops.
	if ratio > 0.6:
		_fill.tint_progress = Color(1.0, 1.0, 1.0, alpha)
	elif ratio > 0.3:
		_fill.tint_progress = Color(1.15, 0.88, 0.55, alpha)
	else:
		_fill.tint_progress = Color(1.25, 0.55, 0.55, alpha)


## --- Regression-test accessors (hud_bar_regression.tscn) -------------------------
## The TextureProgressBar IS the trough now, so the fill can never exceed it by
## construction; these expose the values the regression scene asserts on.
func get_fill_ratio() -> float:
	return _fill.value if _fill != null else 0.0


func get_fill_size() -> Vector2:
	return _fill.size if _fill != null else Vector2.ZERO
