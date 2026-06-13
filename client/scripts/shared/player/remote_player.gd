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

## Replicated class (PacketTypes.PlayerClass) from PLAYER_INFO; picks the
## class spritesheet when the generated art is present.
var player_class: int = PacketTypes.PlayerClass.ZEALOT

## True when class spritesheets (SheetLibrary) drive the visuals; false falls
## back to the legacy color-tinted procedural frames.
var _uses_sheets: bool = false

## 8-way facing row derived from interpolated movement; kept when stationary.
var _facing_row: int = 0

## Facing row latched when a one-shot action (attack/hit/death) starts.
var _action_row: int = 0

## Speed observed from interpolated position deltas — refines the replicated
## WALK state into run/sprint/dash tiers and steers the facing row.
var _observed_speed: float = 0.0
var _last_observed_pos: Vector2 = Vector2.ZERO
var _has_observed_pos: bool = false

## Circling-stars visual driven by the replicated DAZED entity flag.
var _daze_indicator: DazeIndicator = null


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	_daze_indicator = DazeIndicator.new()
	add_child(_daze_indicator)
	_apply_sprite_frames()
	_update_name_label()


func _process(delta: float) -> void:
	if delta <= 0.0:
		return
	if _has_observed_pos:
		var step := global_position - _last_observed_pos
		_observed_speed = step.length() / delta
		if _observed_speed > 10.0:
			_facing_row = SheetLibrary.row_from_angle(step.angle())
	_last_observed_pos = global_position
	_has_observed_pos = true
	if _uses_sheets:
		_update_animation(current_animation_state)


## Pick the class sheet when available, else the procedural fallback.
func _apply_sprite_frames() -> void:
	if animated_sprite == null:
		return
	var alpha := animated_sprite.modulate.a
	var sheet_frames := SheetLibrary.class_frames(player_class)
	if sheet_frames != null:
		animated_sprite.sprite_frames = sheet_frames
		# Normalize differing source canvases to a uniform in-world size.
		animated_sprite.scale = Vector2.ONE * SheetLibrary.class_sprite_scale(player_class)
		_uses_sheets = true
	else:
		animated_sprite.sprite_frames = ProceduralSprites.create_remote_player_frames_for_color(player_color)
		animated_sprite.scale = Vector2.ONE
		_uses_sheets = false
	animated_sprite.modulate = _class_tint(alpha)
	_update_animation(current_animation_state)


## Set the character name and update label
func set_character_name(display_name: String) -> void:
	character_name = display_name
	_update_name_label()


## Set the player color. Class sheets are tinted via modulate (matching the local
## Player) so the swatch slightly recolors a remote player; the procedural fallback
## bakes the color into regenerated frames.
func set_player_color(color: Color) -> void:
	color.a = 1.0
	player_color = color
	if animated_sprite == null:
		return
	var alpha := animated_sprite.modulate.a
	if _uses_sheets:
		animated_sprite.modulate = _class_tint(alpha)
	else:
		var current_animation := animated_sprite.animation
		animated_sprite.sprite_frames = ProceduralSprites.create_remote_player_frames_for_color(player_color)
		animated_sprite.modulate = Color(1, 1, 1, alpha)
		if not current_animation.is_empty() and animated_sprite.sprite_frames.has_animation(current_animation):
			animated_sprite.play(current_animation)


## Modulate color that tints class sheets toward the player color, preserving alpha.
## Returns plain white (no tint) when the procedural fallback is in use.
func _class_tint(alpha: float) -> Color:
	if not _uses_sheets:
		return Color(1, 1, 1, alpha)
	var tint := Color.WHITE.lerp(player_color, GameConstants.CLASS_SPRITE_TINT_STRENGTH)
	tint.a = alpha
	return tint


## Set the replicated class (from PLAYER_INFO via EntityNameCache) and swap to
## that class's spritesheet.
func set_player_class(class_id: int) -> void:
	var clamped := clampi(class_id, 0, SheetLibrary.CLASS_KEYS.size() - 1)
	if clamped == player_class and _uses_sheets:
		return
	player_class = clamped
	_apply_sprite_frames()


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

	if _uses_sheets:
		_update_animation_directional(anim_state)
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


## Directional sheet animation. One-shot actions (attack/hit/death) latch the
## facing row they started on; movement states pick the locomotion tier from
## the observed interpolated speed.
func _update_animation_directional(anim_state: int) -> void:
	var base: String
	var row := _facing_row
	match anim_state:
		PacketTypes.AnimationState.ATTACK:
			base = "attack"
			row = _latched_action_row(anim_state)
		PacketTypes.AnimationState.HIT:
			base = "hit"
			row = _latched_action_row(anim_state)
		PacketTypes.AnimationState.DEATH:
			base = "death"
			row = _latched_action_row(anim_state)
		_:
			base = _locomotion_base()

	var sf_anim := SheetLibrary.anim_for(base, row)
	if animated_sprite.animation != sf_anim and animated_sprite.sprite_frames.has_animation(sf_anim):
		animated_sprite.play(sf_anim)


var _last_action_state: int = -1


func _latched_action_row(anim_state: int) -> int:
	if anim_state != _last_action_state:
		_last_action_state = anim_state
		_action_row = _facing_row
	return _action_row


## Locomotion tier from observed speed; thresholds match Player.gd so local
## and remote players animate consistently.
func _locomotion_base() -> String:
	_last_action_state = -1
	if _observed_speed < 10.0:
		return "idle"
	if _observed_speed >= GameConstants.PLAYER_DASH_SPEED * 0.8:
		return "dash"
	if _observed_speed >= (GameConstants.PLAYER_SPEED + GameConstants.PLAYER_SPRINT_SPEED) * 0.5:
		return "sprint"
	return "run"


## Update flags (alive, invulnerable, dazed, etc.)
func _update_flags(flags: int) -> void:
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0
	var is_invulnerable := (flags & PacketTypes.ENTITY_FLAG_INVULNERABLE) != 0

	visible = (flags & PacketTypes.ENTITY_FLAG_VISIBLE) != 0
	if collision_shape:
		collision_shape.disabled = not is_alive

	if _daze_indicator:
		_daze_indicator.set_active(is_alive and (flags & PacketTypes.ENTITY_FLAG_DAZED) != 0)

	# Visual feedback for invulnerability (flashing), then Rogue stealth dim. Stealth wins
	# when both are set (a stealthed player reads as faded, not flashing).
	var is_stealthed := (flags & PacketTypes.ENTITY_FLAG_STEALTH) != 0
	if animated_sprite:
		if is_stealthed:
			animated_sprite.modulate.a = 0.35
		elif is_invulnerable:
			animated_sprite.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 100.0)
		else:
			animated_sprite.modulate.a = 1.0


## Update name label
func _update_name_label() -> void:
	if name_label:
		name_label.text = character_name
		name_label.visible = not character_name.is_empty()
