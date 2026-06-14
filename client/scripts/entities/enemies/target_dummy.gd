## TargetDummy - stationary practice enemy with local HP and respawn.
## Used by offline practice scenes; grants no XP or progression.
class_name TargetDummy
extends CharacterBody2D

signal took_damage(amount: int)
signal killed(dummy: TargetDummy)
signal respawned(dummy: TargetDummy)

const DEFAULT_DEFINITION_ID := "target_dummy"

@export var definition_id: String = DEFAULT_DEFINITION_ID
@export var respawn_delay: float = 1.5

@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D

var definition: MonsterDefinition = null
var max_hp: int = GameConstants.MONSTER_HEALTH
var current_hp: int = GameConstants.MONSTER_HEALTH
var _is_dead: bool = false


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	add_to_group("enemies")
	add_to_group("target_dummies")

	definition = MonsterDatabase.get_shared().get_definition(definition_id)
	max_hp = definition.max_health
	current_hp = max_hp
	_apply_definition()
	if animated_sprite and not animated_sprite.animation_finished.is_connected(_on_animation_finished):
		animated_sprite.animation_finished.connect(_on_animation_finished)
	queue_redraw()


func take_damage(amount: int) -> bool:
	if _is_dead or amount <= 0:
		return false

	var old_hp := current_hp
	current_hp = clampi(current_hp - amount, 0, max_hp)
	queue_redraw()

	if current_hp < old_hp:
		took_damage.emit(old_hp - current_hp)
		_play_animation("hit")

	if current_hp == 0:
		_die()
		return true

	return false


func respawn() -> void:
	_is_dead = false
	current_hp = max_hp
	visible = true
	if collision_shape:
		collision_shape.disabled = false
	_play_animation("spawn")
	queue_redraw()
	respawned.emit(self)


func is_dead() -> bool:
	return _is_dead


func _apply_definition() -> void:
	if collision_shape and collision_shape.shape is CircleShape2D:
		var circle := collision_shape.shape as CircleShape2D
		circle.radius = definition.hitbox_radius

	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_monster_frames_from_colors(
			definition.core_color,
			definition.glow_color,
			definition.shell_color
		)
		animated_sprite.modulate = Color.WHITE
		animated_sprite.play("idle")


func _die() -> void:
	_is_dead = true
	visible = false
	if collision_shape:
		collision_shape.set_deferred("disabled", true)
	killed.emit(self)

	var timer := get_tree().create_timer(respawn_delay)
	timer.timeout.connect(respawn, CONNECT_ONE_SHOT)


func _play_animation(animation_name: StringName) -> void:
	if animated_sprite == null or animated_sprite.sprite_frames == null:
		return
	if not animated_sprite.sprite_frames.has_animation(animation_name):
		return
	animated_sprite.play(animation_name)


func _on_animation_finished() -> void:
	if _is_dead:
		return
	_play_animation("idle")


func _draw() -> void:
	if _is_dead:
		return

	var bar_width := 46.0
	var bar_height := 5.0
	var bar_y := -32.0
	var hp_ratio := clampf(float(current_hp) / float(maxi(max_hp, 1)), 0.0, 1.0)
	var bg_rect := Rect2(Vector2(-bar_width * 0.5, bar_y), Vector2(bar_width, bar_height))
	var hp_rect := Rect2(bg_rect.position, Vector2(bar_width * hp_ratio, bar_height))

	draw_rect(bg_rect, Color(0.08, 0.04, 0.03, 0.88), true)
	draw_rect(hp_rect, Color(0.95, 0.62, 0.18, 0.95), true)
	draw_rect(bg_rect, Color(0.22, 0.12, 0.06, 0.9), false, 1.0)
