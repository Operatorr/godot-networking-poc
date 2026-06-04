## Monster - Client-side monster visual representation
## Receives state updates from network (via InterpolationController)
## No local AI - purely visual rendering of server-authoritative state
class_name Monster
extends CharacterBody2D

## Emitted when monster takes damage (for audio/effects)
signal took_damage(amount: int)

## Emitted when monster dies (for audio/effects)
signal died()

## Network entity ID
var entity_id: int = -1

## Visual components
@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D

## Current animation state from server
var current_animation_state: int = PacketTypes.AnimationState.IDLE

## Current entity flags from server
var current_flags: int = 0

## HP tracking for visual feedback
var current_hp: int = GameConstants.MONSTER_HEALTH
var max_hp: int = GameConstants.MONSTER_HEALTH


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING

	# Pull appearance + HP from the data-driven monster definition. The wire does
	# not yet carry a per-monster archetype, so all monsters render as the default
	# (Toxic Slime); once a subtype byte is added this keys off the real archetype.
	var definition := MonsterDatabase.get_shared().get_default_definition()
	max_hp = definition.max_health
	current_hp = definition.max_health

	# Apply procedural sprites (monster variant) from the definition's palette
	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_monster_frames_from_colors(
			definition.core_color, definition.glow_color, definition.shell_color
		)
		animated_sprite.modulate = Color.WHITE  # Override placeholder tint
		animated_sprite.play("idle")


## Update visual state from network data
func update_from_network(animation_state: int, flags: int) -> void:
	current_animation_state = animation_state
	current_flags = flags

	_update_animation(animation_state)
	_update_flags(flags)


## Update animation based on server state
func _update_animation(anim_state: int) -> void:
	if animated_sprite == null:
		return

	var anim_name: String
	match anim_state:
		PacketTypes.AnimationState.IDLE:
			anim_name = "idle"
		PacketTypes.AnimationState.WALK:
			anim_name = "walk"
		PacketTypes.AnimationState.ATTACK:
			anim_name = "attack"
		PacketTypes.AnimationState.HIT:
			anim_name = "hit"
		PacketTypes.AnimationState.DEATH:
			anim_name = "death"
		PacketTypes.AnimationState.SPAWN:
			anim_name = "spawn"
		_:
			anim_name = "idle"

	if animated_sprite.animation != anim_name:
		animated_sprite.play(anim_name)


## Update visual flags (alive, moving, etc.)
func _update_flags(flags: int) -> void:
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0

	if not is_alive and visible:
		died.emit()

	visible = is_alive


## Set HP for visual feedback
func set_hp(hp: int) -> void:
	var old_hp := current_hp
	current_hp = clampi(hp, 0, max_hp)
	queue_redraw()

	if current_hp < old_hp:
		took_damage.emit(old_hp - current_hp)


func _draw() -> void:
	# Draw HP bar above monster when damaged
	if current_hp >= max_hp or current_hp <= 0:
		return

	var bar_width := 40.0
	var bar_height := 4.0
	var bar_y := -25.0  # Above sprite
	var hp_ratio := clampf(float(current_hp) / float(maxi(max_hp, 1)), 0.0, 1.0)

	# Background
	draw_rect(Rect2(Vector2(-bar_width / 2, bar_y), Vector2(bar_width, bar_height)), Color(0.1, 0.05, 0.05, 0.8), true)

	# HP fill (green → yellow → red)
	var fill_color: Color
	if hp_ratio > 0.6:
		fill_color = Color(0.2, 0.8, 0.2)
	elif hp_ratio > 0.3:
		fill_color = Color(0.8, 0.8, 0.2)
	else:
		fill_color = Color(0.8, 0.2, 0.2)

	draw_rect(Rect2(Vector2(-bar_width / 2, bar_y), Vector2(bar_width * hp_ratio, bar_height)), fill_color, true)

	# Border
	draw_rect(Rect2(Vector2(-bar_width / 2, bar_y), Vector2(bar_width, bar_height)), Color(0.3, 0.15, 0.15, 0.6), false, 1.0)


## Get readable debug info
func get_debug_info() -> Dictionary:
	return {
		"entity_id": entity_id,
		"position": global_position,
		"animation": current_animation_state,
		"flags": current_flags,
		"hp": current_hp
	}
