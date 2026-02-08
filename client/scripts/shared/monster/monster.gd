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
	if animated_sprite:
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
	current_hp = hp

	if hp < old_hp:
		took_damage.emit(old_hp - hp)


## Get readable debug info
func get_debug_info() -> Dictionary:
	return {
		"entity_id": entity_id,
		"position": global_position,
		"animation": current_animation_state,
		"flags": current_flags,
		"hp": current_hp
	}
