## RemotePlayer - Visual representation of a remote (non-local) player
## Position is updated by InterpolationController, no local input processing
## Animations and flags are updated from network state
class_name RemotePlayer
extends CharacterBody2D

## Network entity ID
var entity_id: int = -1

## Character name for display
var character_name: String = ""

## Visual components
@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var name_label: Label = $NameLabel

## Current state from server
var current_animation_state: int = PacketTypes.AnimationState.IDLE
var current_flags: int = 0


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	# Apply procedural sprites (remote player variant)
	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_remote_player_frames()
		animated_sprite.modulate = Color.WHITE  # Override placeholder tint
		animated_sprite.play("idle")
	_update_name_label()


## Set the character name and update label
func set_character_name(name: String) -> void:
	character_name = name
	_update_name_label()


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
		_:
			anim_name = "idle"

	if animated_sprite.animation != anim_name:
		animated_sprite.play(anim_name)


## Update flags (alive, invulnerable, etc.)
func _update_flags(flags: int) -> void:
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0
	var is_invulnerable := (flags & PacketTypes.ENTITY_FLAG_INVULNERABLE) != 0

	visible = is_alive

	# Visual feedback for invulnerability (flashing)
	if animated_sprite:
		if is_invulnerable:
			animated_sprite.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 100.0)
		else:
			animated_sprite.modulate.a = 1.0


## Update name label
func _update_name_label() -> void:
	if name_label:
		name_label.text = character_name
		name_label.visible = not character_name.is_empty()
