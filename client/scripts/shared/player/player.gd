## Player - Main player controller script
## Handles movement, aiming, shooting, and state management
class_name Player
extends CharacterBody2D

const HPComponent := preload("res://scripts/shared/player/hp_component.gd")
const Projectile := preload("res://scripts/shared/projectile/projectile.gd")
const ProjectilePool := preload("res://scripts/shared/projectile/projectile_pool.gd")
const ProceduralSprites := preload("res://scripts/shared/visuals/procedural_sprites.gd")

## Movement state enum
enum MovementState {
	IDLE,    ## No movement input, playing idle animation
	WALKING  ## Movement input active, playing walk animation
}

## Action state enum
enum ActionState {
	NONE,      ## No action in progress
	ATTACKING, ## Attack animation playing (does not block movement)
	HIT,       ## Hit stun animation playing (blocks movement briefly)
	DEAD       ## Death state (blocks all processing)
}

## Emitted when the player fires a projectile
signal shot_fired(position: Vector2, direction: Vector2)

## Emitted when player state changes (for networking)
signal state_changed(state_data: Dictionary)

## Movement speed in pixels per second
@export var speed: float = 200.0

## Maximum distance projectiles travel
@export var projectile_range: float = 600.0

## Seconds between shots (fire rate)
@export var fire_rate: float = 0.3

## Current movement state
var movement_state: MovementState = MovementState.IDLE

## Current action state
var action_state: ActionState = ActionState.NONE

## Fallback when mouse at player position
var last_aim_direction: Vector2 = Vector2.RIGHT

## Whether input processing is enabled
var _input_enabled: bool = true

## Footstep timing
var _footstep_timer: float = 0.0
const FOOTSTEP_WALK_INTERVAL := 0.3
const FOOTSTEP_SPRINT_INTERVAL := 0.2

## Reference to HP component
@onready var hp_component: HPComponent = $HPComponent

## Reference to projectile pool
@onready var projectile_pool: ProjectilePool = $ProjectilePool

## Reference to shoot cooldown timer
@onready var shoot_cooldown_timer: Timer = $ShootCooldownTimer

## Reference to animated sprite
@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D


func _ready() -> void:
	# Set motion mode for top-down game (no gravity)
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING

	# Apply procedural sprites
	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_player_frames()
		animated_sprite.modulate = Color.WHITE  # Override the placeholder blue tint

	# Connect HP component signals
	if hp_component:
		hp_component.died.connect(_on_hp_component_died)

	# Connect animation finished signal
	if animated_sprite:
		animated_sprite.animation_finished.connect(_on_animation_finished)

	# Configure shoot cooldown timer
	if shoot_cooldown_timer:
		shoot_cooldown_timer.wait_time = fire_rate
		shoot_cooldown_timer.one_shot = true


func _physics_process(delta: float) -> void:
	# Dead state blocks all processing
	if action_state == ActionState.DEAD:
		return

	# Hit state blocks movement briefly
	if action_state == ActionState.HIT:
		velocity = Vector2.ZERO
		move_and_slide()
		return

	# Handle input if enabled
	if _input_enabled:
		_handle_movement()
		_handle_aiming()
		_handle_shooting()

	# Apply movement
	move_and_slide()

	# Footstep audio
	_update_footsteps(delta)

	# Update animation
	_update_animation()


## Handle WASD movement input
func _handle_movement() -> void:
	var input_dir := Input.get_vector("move_left", "move_right", "move_up", "move_down")

	if input_dir != Vector2.ZERO:
		velocity = input_dir * speed
		_set_movement_state(MovementState.WALKING)
	else:
		velocity = Vector2.ZERO
		_set_movement_state(MovementState.IDLE)


## Handle mouse aiming
func _handle_aiming() -> void:
	var mouse_pos := get_global_mouse_position()
	var direction := mouse_pos - global_position

	# Handle edge case: mouse at player position
	if direction.length_squared() < 1.0:
		direction = last_aim_direction
	else:
		last_aim_direction = direction.normalized()

	rotation = direction.angle()


## Handle shooting input
func _handle_shooting() -> void:
	if Input.is_action_pressed("shoot") and shoot_cooldown_timer.is_stopped():
		_shoot()


## Fire a projectile
func _shoot() -> void:
	if projectile_pool == null:
		return

	# Calculate spawn position (offset from player center)
	var spawn_offset := 20.0
	var spawn_pos := global_position + last_aim_direction * spawn_offset

	# Spawn projectile from pool
	var projectile: Projectile = projectile_pool.spawn(spawn_pos, last_aim_direction, projectile_range)

	if projectile:
		# Start cooldown
		shoot_cooldown_timer.start()

		# Emit signal for networking
		shot_fired.emit(spawn_pos, last_aim_direction)

		# Trigger attack animation
		_set_action_state(ActionState.ATTACKING)


## Set movement state with transition
func _set_movement_state(new_state: MovementState) -> void:
	if movement_state != new_state:
		movement_state = new_state


## Set action state with transition
func _set_action_state(new_state: ActionState) -> void:
	if action_state != new_state:
		action_state = new_state


## Update animation based on current state
func _update_animation() -> void:
	if animated_sprite == null:
		return

	# Action state takes priority
	match action_state:
		ActionState.ATTACKING:
			if animated_sprite.animation != "attack":
				animated_sprite.play("attack")
			return
		ActionState.HIT:
			if animated_sprite.animation != "hit":
				animated_sprite.play("hit")
			return
		ActionState.DEAD:
			if animated_sprite.animation != "death":
				animated_sprite.play("death")
			return

	# Movement state animations
	match movement_state:
		MovementState.IDLE:
			if animated_sprite.animation != "idle":
				animated_sprite.play("idle")
		MovementState.WALKING:
			if animated_sprite.animation != "walk":
				animated_sprite.play("walk")


## Update footstep audio timer
func _update_footsteps(delta: float) -> void:
	if movement_state != MovementState.WALKING:
		_footstep_timer = 0.0
		return

	var interval := FOOTSTEP_SPRINT_INTERVAL if Input.is_action_pressed("sprint") else FOOTSTEP_WALK_INTERVAL
	_footstep_timer += delta
	if _footstep_timer >= interval:
		_footstep_timer -= interval
		var audio := Engine.get_singleton("AudioManager") if Engine.has_singleton("AudioManager") else null
		if audio == null:
			var tree := get_tree()
			if tree:
				audio = tree.root.get_node_or_null("AudioManager")
		if audio and audio.has_method("play_footstep"):
			audio.play_footstep()


func _on_animation_finished() -> void:
	# Return from one-shot action animations to NONE
	if action_state == ActionState.ATTACKING or action_state == ActionState.HIT:
		action_state = ActionState.NONE


func _on_hp_component_died() -> void:
	action_state = ActionState.DEAD
	velocity = Vector2.ZERO
	_input_enabled = false

	# Deactivate all projectiles
	if projectile_pool:
		projectile_pool.deactivate_all()


## Apply damage to the player
## @param amount: Damage points to subtract from HP
## @return: Remaining HP after damage
func take_damage(amount: int) -> int:
	if hp_component:
		hp_component.take_damage(amount)

		# Trigger hit animation if still alive
		if not hp_component.is_dead:
			_set_action_state(ActionState.HIT)

		return hp_component.current_hp
	return 0


## Heal the player (does nothing if dead)
## @param amount: HP points to restore
## @return: New HP value after healing
func heal(amount: int) -> int:
	if hp_component:
		hp_component.heal(amount)
		return hp_component.current_hp
	return 0


## Reset player to initial state (full HP, idle state)
## Used for respawn systems
func reset() -> void:
	if hp_component:
		hp_component.reset()

	movement_state = MovementState.IDLE
	action_state = ActionState.NONE
	_input_enabled = true
	velocity = Vector2.ZERO
	last_aim_direction = Vector2.RIGHT

	if projectile_pool:
		projectile_pool.deactivate_all()


## Get current state as serializable dictionary
## Used for networking state sync
## @return: Dictionary with position, rotation, hp, states
func get_state() -> Dictionary:
	return {
		"position": global_position,
		"rotation": rotation,
		"velocity": velocity,
		"hp": hp_component.current_hp if hp_component else 0,
		"max_hp": hp_component.max_hp if hp_component else 100,
		"movement_state": movement_state,
		"action_state": action_state,
		"is_dead": is_dead
	}


## Apply state from dictionary (server reconciliation)
## @param state: Dictionary from get_state() format
func apply_state(state: Dictionary) -> void:
	if state.has("position"):
		global_position = state["position"]
	if state.has("rotation"):
		rotation = state["rotation"]
	if state.has("velocity"):
		velocity = state["velocity"]
	if state.has("hp") and hp_component:
		hp_component.set_hp(state["hp"])
	if state.has("movement_state"):
		movement_state = state["movement_state"] as MovementState
	if state.has("action_state"):
		action_state = state["action_state"] as ActionState


## Enable/disable player input processing
## Used when game is paused or in menus
## @param enabled: Whether to process input
func set_input_enabled(enabled: bool) -> void:
	_input_enabled = enabled


## Get readable state name for debugging
func get_state_name() -> String:
	var movement_str: String = MovementState.keys()[movement_state]
	var action_str: String = ActionState.keys()[action_state]
	return "%s / %s" % [movement_str, action_str]


## Whether the player is currently dead
var is_dead: bool:
	get:
		return hp_component.is_dead if hp_component else false
