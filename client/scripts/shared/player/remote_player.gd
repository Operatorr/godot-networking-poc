## RemotePlayer - Visual representation of a remote (non-local) player
## Position is updated by InterpolationController, no local input processing
## Animations and flags are updated from network state
class_name RemotePlayer
extends CharacterBody2D

## Network entity ID
var entity_id: int = -1

## Character name for display
var character_name: String = ""
var player_color: Color = Color(0.27, 0.53, 1.0)

## Visual components
@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var name_label: Label = $NameLabel

## Current state from server
var current_animation_state: int = PacketTypes.AnimationState.IDLE
var current_flags: int = 0

## Circling-stars visual driven by the replicated DAZED entity flag.
var _daze_indicator: DazeIndicator = null


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	_daze_indicator = DazeIndicator.new()
	add_child(_daze_indicator)
	# Apply procedural sprites (remote player variant)
	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_remote_player_frames_for_color(player_color)
		animated_sprite.modulate = Color.WHITE  # Override placeholder tint
		animated_sprite.play("idle")
	_update_name_label()


## Set the character name and update label
func set_character_name(display_name: String) -> void:
	character_name = display_name
	_update_name_label()


## Set the player color and regenerate procedural frames.
func set_player_color(color: Color) -> void:
	color.a = 1.0
	player_color = color
	if animated_sprite:
		var current_animation := animated_sprite.animation
		var alpha := animated_sprite.modulate.a
		animated_sprite.sprite_frames = ProceduralSprites.create_remote_player_frames_for_color(player_color)
		animated_sprite.modulate = Color(1, 1, 1, alpha)
		if not current_animation.is_empty() and animated_sprite.sprite_frames.has_animation(current_animation):
			animated_sprite.play(current_animation)


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
			anim_name = "idle"
		_:
			anim_name = "idle"

	if animated_sprite.animation != anim_name:
		animated_sprite.play(anim_name)


## Update flags (alive, invulnerable, dazed, etc.)
func _update_flags(flags: int) -> void:
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0
	var is_invulnerable := (flags & PacketTypes.ENTITY_FLAG_INVULNERABLE) != 0

	visible = (flags & PacketTypes.ENTITY_FLAG_VISIBLE) != 0
	if collision_shape:
		collision_shape.disabled = not is_alive

	if _daze_indicator:
		_daze_indicator.set_active(is_alive and (flags & PacketTypes.ENTITY_FLAG_DAZED) != 0)

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
