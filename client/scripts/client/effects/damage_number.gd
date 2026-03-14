## DamageNumber - Floating damage text that rises and fades
## Spawned at damage location, auto-frees after animation
class_name DamageNumber
extends Node2D

const RISE_DISTANCE := 80.0
const DURATION := 0.8
const FADE_START := 0.5

var _amount: int = 0
var _color: Color = Color.RED
var _timer: float = 0.0
var _start_pos: Vector2 = Vector2.ZERO
var _offset_x: float = 0.0


## Initialize and start animation
func setup(amount: int, world_pos: Vector2, is_dealt: bool = false) -> void:
	_amount = amount
	_start_pos = world_pos
	global_position = world_pos
	_offset_x = randf_range(-15.0, 15.0)

	if is_dealt:
		_color = Color(0.27, 1.0, 0.27)  # Sickly green for damage dealt
	else:
		_color = Color(1.0, 0.2, 0.1)  # Red for damage taken


func _process(delta: float) -> void:
	_timer += delta
	if _timer >= DURATION:
		queue_free()
		return

	var t := _timer / DURATION
	# Rise with deceleration
	var rise := RISE_DISTANCE * (1.0 - pow(1.0 - t, 2.0))
	global_position = _start_pos + Vector2(_offset_x * t, -rise)

	queue_redraw()


func _draw() -> void:
	var t := _timer / DURATION
	# Fade in last portion
	var alpha := 1.0
	if t > FADE_START:
		alpha = 1.0 - (t - FADE_START) / (1.0 - FADE_START)

	var font := ThemeDB.fallback_font
	var font_size := 18 + mini(_amount / 10, 4)  # Bigger for bigger hits
	var text := str(_amount)

	var c := _color
	c.a = alpha

	# Draw shadow
	var shadow := Color(0, 0, 0, alpha * 0.6)
	draw_string(font, Vector2(1, 1), text, HORIZONTAL_ALIGNMENT_CENTER, -1, font_size, shadow)
	# Draw text
	draw_string(font, Vector2.ZERO, text, HORIZONTAL_ALIGNMENT_CENTER, -1, font_size, c)
