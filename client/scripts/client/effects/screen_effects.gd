## ScreenEffects - Camera shake, screen flash, and hit stop
## Attached to arena camera for combat feedback
class_name ScreenEffects
extends Node

## Shake intensity presets
const SHAKE_HIT := 3.0
const SHAKE_KILL := 6.0
const SHAKE_DEATH := 10.0

## Camera reference (set externally)
var camera: Camera2D = null

## Flash overlay (created at runtime)
var _flash_rect: ColorRect = null
var _flash_layer: CanvasLayer = null

## Shake state
var _shake_intensity: float = 0.0
var _shake_duration: float = 0.0
var _shake_timer: float = 0.0
var _original_offset: Vector2 = Vector2.ZERO


func _ready() -> void:
	_setup_flash_overlay()


func _process(delta: float) -> void:
	_update_shake(delta)


## Set up the flash overlay CanvasLayer + ColorRect
func _setup_flash_overlay() -> void:
	_flash_layer = CanvasLayer.new()
	_flash_layer.layer = 100  # Above everything
	add_child(_flash_layer)

	_flash_rect = ColorRect.new()
	_flash_rect.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_flash_rect.color = Color(0, 0, 0, 0)
	_flash_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_flash_layer.add_child(_flash_rect)


## Trigger screen shake
func shake(intensity: float, duration: float = 0.3) -> void:
	# Only upgrade shake, don't downgrade
	if intensity > _shake_intensity:
		_shake_intensity = intensity
		_shake_duration = duration
		_shake_timer = 0.0
		if camera:
			_original_offset = Vector2.ZERO


## Update camera shake
func _update_shake(delta: float) -> void:
	if _shake_intensity <= 0.0 or camera == null:
		return

	_shake_timer += delta
	if _shake_timer >= _shake_duration:
		_shake_intensity = 0.0
		camera.offset = _original_offset
		return

	# Decaying random offset
	var decay := 1.0 - (_shake_timer / _shake_duration)
	var offset_x := randf_range(-_shake_intensity, _shake_intensity) * decay
	var offset_y := randf_range(-_shake_intensity, _shake_intensity) * decay
	camera.offset = _original_offset + Vector2(offset_x, offset_y)


## Flash the screen a color
func flash(color: Color, duration: float = 0.15) -> void:
	if _flash_rect == null:
		return
	_flash_rect.color = color
	var tween := create_tween()
	tween.tween_property(_flash_rect, "color:a", 0.0, duration)


## Red damage flash
func flash_damage() -> void:
	flash(Color(0.8, 0.0, 0.0, 0.3), 0.2)


## White death flash
func flash_death() -> void:
	flash(Color(1.0, 1.0, 1.0, 0.5), 0.4)


## Hit stop (brief freeze frame) - 50ms
func hit_stop(duration: float = 0.05) -> void:
	Engine.time_scale = 0.05
	# Use a real-time timer to restore
	get_tree().create_timer(duration, true, false, true).timeout.connect(
		func(): Engine.time_scale = 1.0
	)
