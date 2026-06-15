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

## Active hit-flash tween, kept so a fresh hit kills the prior one instead of
## stacking concurrent tweens that fight over modulate.
var _hit_flash_tween: Tween = null


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	add_to_group("minimap_monster")  # red dot on the minimap

	# Pull appearance + HP from the data-driven monster definition. The wire does
	# not yet carry a per-monster archetype, so all monsters render as the default
	# (Toxic Slime); once a subtype byte is added this keys off the real archetype.
	var definition := MonsterDatabase.get_shared().get_default_definition()
	max_hp = definition.max_health
	current_hp = definition.max_health

	# Generated toxic-slime spritesheet when present, else the procedural
	# palette-driven fallback from the monster definition.
	if animated_sprite:
		var sheet_frames := SheetLibrary.monster_frames("toxic_slime")
		if sheet_frames != null:
			animated_sprite.sprite_frames = sheet_frames
		else:
			animated_sprite.sprite_frames = ProceduralSprites.create_monster_frames_from_colors(
				definition.core_color, definition.glow_color, definition.shell_color
			)
		animated_sprite.modulate = Color.WHITE  # Override placeholder tint
		animated_sprite.play("idle")


## Update visual state from network data
func update_from_network(animation_state: int, flags: int) -> void:
	# The generated slime sheet has no dedicated hit frames (aliased to idle),
	# so flash the sprite red on the HIT edge to keep damage readable.
	if animation_state == PacketTypes.AnimationState.HIT \
			and current_animation_state != PacketTypes.AnimationState.HIT:
		_flash_hit()
	current_animation_state = animation_state
	current_flags = flags

	_update_animation(animation_state)
	_update_flags(flags)


func _flash_hit() -> void:
	if animated_sprite == null:
		return
	# Kill any in-flight flash so rapid hits don't stack tweens that fight over modulate.
	if _hit_flash_tween != null and _hit_flash_tween.is_valid():
		_hit_flash_tween.kill()
	animated_sprite.modulate = Color(1.0, 0.35, 0.35)
	# Restore to the flags-derived base color (e.g. dimmed under stealth), not hardcoded white.
	_hit_flash_tween = create_tween()
	_hit_flash_tween.tween_property(animated_sprite, "modulate", _base_modulate(), 0.18)


## Base sprite modulate implied by the current entity flags (white normally, dimmed
## under stealth). The hit-flash restores to this so it doesn't clobber flag-driven tint.
func _base_modulate() -> Color:
	if (current_flags & PacketTypes.ENTITY_FLAG_STEALTH) != 0:
		return Color(1.0, 1.0, 1.0, 0.35)
	return Color.WHITE


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

	# Apply the flag-driven base tint (e.g. stealth dim) unless a hit-flash is mid-
	# tween — the flash restores to _base_modulate() itself, so don't clobber it.
	if animated_sprite != null and (_hit_flash_tween == null or not _hit_flash_tween.is_valid()):
		animated_sprite.modulate = _base_modulate()


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
