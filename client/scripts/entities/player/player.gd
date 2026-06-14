## Player - Main player controller script
## Handles movement, aiming, shooting, and state management
class_name Player
extends CharacterBody2D

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

## Movement speed in pixels per second
@export var speed: float = 200.0

## Maximum distance projectiles travel
@export var projectile_range: float = GameConstants.PROJECTILE_MAX_DISTANCE

## Seconds between shots (fire rate)
@export var fire_rate: float = 0.3

## Whether this player should spawn gameplay projectiles locally.
## Networked arenas disable this; the server owns projectile spawning there.
@export var local_projectile_spawning_enabled: bool = true

## When true, the PredictionController is the sole authority over this player's
## position — Player.gd skips its own move_and_slide() integration so the two
## don't fight (the "steering boat" double-movement bug). Aiming/animation stay on.
@export var prediction_owns_movement: bool = false

## Current movement state
var movement_state: MovementState = MovementState.IDLE

## Predicted 7-state movement model for the local networked player (dash/sprint/
## knockback/stun/ability + stamina/mana). The PredictionController consults this
## each tick; the server runs an identical authoritative instance. Created in
## _ready(); unused for non-local players and offline movement. See
## movement_state_machine.gd and docs/systems/players-movement-state-machine.md.
var movement_sm: MovementStateMachine = null

## Last HP we observed, so the hp_changed hook can tell damage from healing.
var _last_known_hp: int = 100

## Circling-stars visual shown while dazed. Online it follows the server's
## DAZED entity flag (mirrored into movement_sm by the PredictionController);
## offline movement_sm dazes itself on a sprinting hit. Both paths surface
## here through the SM's daze_started/daze_ended signals.
var _daze_indicator: DazeIndicator = null

## Current action state
var action_state: ActionState = ActionState.NONE

## Fallback when mouse at player position
var last_aim_direction: Vector2 = Vector2.RIGHT

## Whether input processing is enabled
var _input_enabled: bool = true
var player_color: Color = Color(0.27, 0.53, 1.0)

## True when class spritesheets (SheetLibrary) drive the visuals; false falls
## back to the legacy procedural frames (assets missing, e.g. fresh checkout).
var _uses_sheets: bool = false

## 8-way facing row (SheetLibrary.DIR_ORDER index) derived from aim each frame.
var _facing_row: int = 0

## Facing row latched when a one-shot action (attack/hit/death) starts, so the
## animation doesn't restart when the aim crosses an octant mid-swing.
var _action_row: int = 0

## Speed observed from actual position deltas. Works no matter who integrates
## the position (offline move_and_slide vs PredictionController) and drives the
## idle/run/sprint/dash locomotion animation choice.
var _observed_speed: float = 0.0
var _last_observed_pos: Vector2 = Vector2.ZERO
var _has_observed_pos: bool = false

## When true, take_damage() ignores incoming damage (debug/sandbox tool).
var invulnerable: bool = false

## Footstep timing
var _footstep_timer: float = 0.0
const FOOTSTEP_WALK_INTERVAL := 0.3
const FOOTSTEP_SPRINT_INTERVAL := 0.2

## One-shot action animations (attack/hit) are cleared by THIS timer, not by
## animation_finished: a class sheet that lacks "attack" art aliases it to a LOOPING
## "idle" (sheet_library.gd), so animation_finished never fires and the action used to
## stick forever (the player froze mid-run). The attack timer is the fire_rate so the
## attack pose stays in sync with the attack speed; locomotion resumes when it expires.
var _action_timer: float = 0.0
const HIT_ANIM_SECONDS := 0.25

## Per-class RMB ability mana cost, indexed by PacketTypes.PlayerClass (Zealot…Mage). Offline
## parity with client/data/classes/*.json and the Rust sim's per-class config.
const _ABILITY_MANA_COST := [35.0, 30.0, 35.0, 35.0, 40.0, 30.0, 40.0]

## Reference to HP component
@onready var hp_component: HPComponent = $HPComponent

## Reference to projectile pool
@onready var projectile_pool: ProjectilePool = $ProjectilePool

## Reference to shoot cooldown timer
@onready var shoot_cooldown_timer: Timer = $ShootCooldownTimer

## Reference to animated sprite
@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D


func _ready() -> void:
	# Guard against a silent desync: the per-class cost table must have exactly one entry
	# per PacketTypes.PlayerClass, so adding a class can't index past the end (or alias).
	# CLASS_DISPLAY_NAMES is the canonical one-per-class list (PlayerClass enum mirror).
	assert(
		_ABILITY_MANA_COST.size() == PacketTypes.CLASS_DISPLAY_NAMES.size(),
		"_ABILITY_MANA_COST must have one entry per PacketTypes.PlayerClass"
	)

	# Set motion mode for top-down game (no gravity)
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING

	# Class spritesheet when the generated art is present, else procedural fallback
	if animated_sprite:
		player_color = _get_configured_player_color()
		var player_class := _get_configured_player_class()
		var sheet_frames := SheetLibrary.class_frames(player_class)
		if sheet_frames != null:
			animated_sprite.sprite_frames = sheet_frames
			# Normalize differing source canvases to a uniform in-world size.
			animated_sprite.scale = Vector2.ONE * SheetLibrary.class_sprite_scale(player_class)
			_uses_sheets = true
		else:
			animated_sprite.sprite_frames = ProceduralSprites.create_player_frames_for_color(player_color)
		# Class sheets are tinted by the chosen color (the procedural fallback bakes the
		# color into its frames instead); _class_tint() returns WHITE when not using sheets.
		animated_sprite.modulate = _class_tint(1.0)

	# Predicted movement state machine for the local networked player.
	movement_sm = MovementStateMachine.new()
	movement_sm.daze_started.connect(func(_duration: float) -> void: set_dazed(true))
	movement_sm.daze_ended.connect(func() -> void: set_dazed(false))
	# Per-class ability mana cost + offline RMB preview (Sanctuary/practice). Online the Rust sim
	# owns this and the real effect arrives as a server ABILITY_EFFECT.
	movement_sm.ability_cost = _ability_mana_cost_for_class(_get_configured_player_class())
	movement_sm.ability_triggered.connect(_on_offline_ability_triggered)

	_daze_indicator = DazeIndicator.new()
	add_child(_daze_indicator)

	# Connect HP component signals
	if hp_component:
		hp_component.died.connect(_on_hp_component_died)
		hp_component.hp_changed.connect(_on_hp_changed)
		_last_known_hp = hp_component.current_hp

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

	# Clear one-shot action states on a timer (NOT animation_finished — see _action_timer).
	# This is what unsticks the attack: it returns to locomotion after one attack interval.
	if action_state == ActionState.ATTACKING or action_state == ActionState.HIT:
		_action_timer = maxf(0.0, _action_timer - delta)
		if _action_timer <= 0.0:
			action_state = ActionState.NONE

	# Note: the HIT action state is purely cosmetic (a brief flash animation) and
	# does NOT block movement. _update_animation() still prioritizes the "hit"
	# animation, and _on_animation_finished() clears HIT back to NONE. Blocking
	# movement here used to lock the player offline (online it was masked because
	# the PredictionController owns movement); a bullet-hell must stay responsive.

	# Handle input if enabled. _handle_movement still runs under prediction
	# ownership so movement_state (and thus animation) stays correct; only the
	# position integration below is skipped. Aim first so an offline dash with no
	# WASD held fires toward the current cursor.
	if _input_enabled:
		_handle_aiming()
		_handle_movement(delta)
		_handle_shooting()

	# Apply movement — but NOT when the PredictionController owns this player's
	# position, or the two integrators fight (the "steering boat" bug).
	if not prediction_owns_movement:
		move_and_slide()

	# Footstep audio
	_update_footsteps(delta)

	# Track real movement speed AND direction from position deltas (integrator-
	# agnostic: works under offline move_and_slide and online prediction ownership).
	var move_step := Vector2.ZERO
	if _has_observed_pos and delta > 0.0:
		move_step = global_position - _last_observed_pos
		_observed_speed = move_step.length() / delta
	_last_observed_pos = global_position
	_has_observed_pos = true

	# Directional sheets: the body still rotates toward the aim (rotation drives
	# shooting), but the artwork must not spin — counter-rotate the sprite and pick
	# the 8-way row from the MOVEMENT direction, kept when stationary so the player
	# faces where they last moved. The aim now steers only shooting, not the run
	# cycle; this matches RemotePlayer (remote_player.gd).
	if _uses_sheets and animated_sprite:
		animated_sprite.global_rotation = 0.0
		if _observed_speed > 10.0 and move_step != Vector2.ZERO:
			_facing_row = SheetLibrary.row_from_angle(move_step.angle())

	# Update animation
	_update_animation()


## Handle WASD movement input.
## Online (prediction_owns_movement): the PredictionController owns velocity AND the
## movement state machine, so this only keeps the animation movement_state in sync.
## Offline (practice/sandbox): the SAME `movement_sm` is the authoritative mover here,
## so dash/sprint/knockback/stun + stamina/mana all work with one shared player script.
func _handle_movement(delta: float) -> void:
	var input_dir := Input.get_vector("move_left", "move_right", "move_up", "move_down")

	if prediction_owns_movement:
		_set_movement_state(MovementState.WALKING if input_dir != Vector2.ZERO else MovementState.IDLE)
		return

	if movement_sm != null:
		# is_action_just_pressed gives the dash a clean one-frame rising edge; the SM
		# detects the edge internally. _physics_process runs at the 30 Hz sim rate.
		velocity = movement_sm.tick(
			delta,
			input_dir,
			Input.is_action_pressed("sprint"),
			Input.is_action_just_pressed("dash"),
			Input.is_action_pressed("ability"),
			Input.is_action_pressed("shoot"),
			last_aim_direction
		)
	else:
		velocity = input_dir * GameConstants.get_movement_speed(Input.is_action_pressed("sprint"))

	_set_movement_state(MovementState.WALKING if velocity != Vector2.ZERO else MovementState.IDLE)


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
	if not local_projectile_spawning_enabled:
		return

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
		# Offline-spawned projectiles carry the local player's class art.
		if projectile.has_method("set_projectile_class"):
			projectile.set_projectile_class(_get_configured_player_class())

		# Start cooldown
		shoot_cooldown_timer.start()

		# Emit signal for networking
		shot_fired.emit(spawn_pos, last_aim_direction)

		# Trigger attack animation
		_set_action_state(ActionState.ATTACKING)


func _ability_mana_cost_for_class(class_id: int) -> float:
	if class_id >= 0 and class_id < _ABILITY_MANA_COST.size():
		return _ABILITY_MANA_COST[class_id]
	return GameConstants.PLAYER_MANA_ABILITY_COST


## Offline RMB preview: the GDScript SM (offline mover) fired an ability and paid the mana cost.
## Spawn a cosmetic per-class visual so RMB visibly does something in the Sanctuary. Online this
## SM's tick() isn't driven for the local player, so this never fires there.
func _on_offline_ability_triggered() -> void:
	if prediction_owns_movement:
		return
	var world := get_parent()
	if world == null:
		return
	OfflineAbilityPreview.play(world, self, _get_configured_player_class(), get_global_mouse_position())


## Offline Rogue stealth preview: dim the sprite for `duration` seconds.
func apply_stealth_preview(duration: float) -> void:
	if animated_sprite == null:
		return
	var dim := animated_sprite.modulate
	dim.a = 0.35
	animated_sprite.modulate = dim
	var tree := get_tree()
	if tree == null:
		return
	tree.create_timer(duration).timeout.connect(func() -> void:
		if is_instance_valid(self) and animated_sprite != null:
			var restored := animated_sprite.modulate
			restored.a = 1.0
			animated_sprite.modulate = restored
	)


## Set movement state with transition
func _set_movement_state(new_state: MovementState) -> void:
	if movement_state != new_state:
		movement_state = new_state


## Set action state with transition. One-shot actions latch the facing row and arm the
## clear timer so they end in sync with the attack speed even when the animation loops.
func _set_action_state(new_state: ActionState) -> void:
	if action_state != new_state:
		action_state = new_state
		_action_row = _facing_row
		match new_state:
			ActionState.ATTACKING:
				_action_timer = fire_rate
			ActionState.HIT:
				_action_timer = HIT_ANIM_SECONDS
			_:
				_action_timer = 0.0


## Update animation based on current state
func _update_animation() -> void:
	if animated_sprite == null:
		return

	if _uses_sheets:
		_update_animation_directional()
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


## Directional (spritesheet) animation: one-shot actions play on the facing row
## latched when the action started; locomotion picks idle/run/sprint/dash from
## the observed speed so it is correct under any position integrator.
func _update_animation_directional() -> void:
	match action_state:
		ActionState.DEAD:
			_play_directional("death", _action_row)
			return
		ActionState.HIT:
			_play_directional("hit", _action_row)
			return
		ActionState.ATTACKING:
			_play_directional("attack", _action_row)
			return
	_play_directional(_locomotion_base(), _facing_row)


## Locomotion animation from observed speed. Thresholds sit between the tier
## speeds (200 / 320 / 720 u/s) so interpolation noise doesn't flicker tiers.
func _locomotion_base() -> String:
	if _observed_speed < 10.0:
		return "idle"
	if _observed_speed >= GameConstants.PLAYER_DASH_SPEED * 0.8:
		return "dash"
	if _observed_speed >= (GameConstants.PLAYER_SPEED + GameConstants.PLAYER_SPRINT_SPEED) * 0.5:
		return "sprint"
	return "run"


func _play_directional(base: String, row: int) -> void:
	var anim := SheetLibrary.anim_for(base, row)
	if animated_sprite.animation != anim and animated_sprite.sprite_frames.has_animation(anim):
		animated_sprite.play(anim)


## Update footstep audio timer
func _update_footsteps(delta: float) -> void:
	if movement_state != MovementState.WALKING:
		_footstep_timer = 0.0
		return

	var interval := FOOTSTEP_SPRINT_INTERVAL if is_sprinting() else FOOTSTEP_WALK_INTERVAL
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


## True when the local player is genuinely sprinting: sprint held, actively moving,
## and NOT blocked by exhaustion / empty stamina / daze. Mirrors sim_core's want_sprint
## gate so the cosmetic feedback (camera zoom + faster sprint footsteps) stops the instant
## the sim refuses to sprint. Both the Rust sim (online) and this SM (offline) already cap
## movement to walk speed when exhausted; this keeps the feedback in lockstep instead of
## keying off the raw `sprint` input (which stays held while exhausted).
func is_sprinting() -> bool:
	if movement_sm == null:
		return false
	if movement_state != MovementState.WALKING:
		return false
	if not Input.is_action_pressed("sprint"):
		return false
	return movement_sm.stamina > 0.0 and not movement_sm.is_exhausted() and not movement_sm.is_dazed()


func _on_animation_finished() -> void:
	# HIT can end as soon as its (non-looping) animation finishes. ATTACKING is cleared
	# only by _action_timer so it stays in sync with the attack speed (and so a class
	# sheet whose "attack" aliases to looping "idle" can't stick — that anim never emits
	# animation_finished). See _action_timer.
	if action_state == ActionState.HIT:
		action_state = ActionState.NONE


## Taking damage ends a sprint (spec), and a hit WHILE sprinting dazes (sprint/dash
## locked out for PLAYER_DAZE_DURATION). Uses the authoritative HP signal (server-owned
## HP), and only reacts to decreases so heals / upward reconciliation don't cancel sprint.
## Online the SM is a mirror and never enters SPRINTING (the Rust sim predicts; the
## server applies the authoritative daze) — this path is the OFFLINE parity rule.
func _on_hp_changed(new_hp: int, _max_hp: int) -> void:
	if new_hp < _last_known_hp and movement_sm != null:
		if movement_sm.state == MovementStateMachine.State.SPRINTING:
			movement_sm.apply_daze(GameConstants.PLAYER_DAZE_DURATION)
		movement_sm.end_sprint()
	_last_known_hp = new_hp


## Show/hide the daze stars. Called via the SM daze signals and directly by the
## PredictionController when the server's DAZED flag edges.
func set_dazed(active: bool) -> void:
	if _daze_indicator != null:
		_daze_indicator.set_active(active)


func _on_hp_component_died() -> void:
	action_state = ActionState.DEAD
	movement_state = MovementState.IDLE
	velocity = Vector2.ZERO
	_input_enabled = false

	# Deactivate all projectiles
	if projectile_pool:
		projectile_pool.deactivate_all()


## Apply damage to the player
## @param amount: Damage points to subtract from HP
## @return: Remaining HP after damage
func take_damage(amount: int) -> int:
	if invulnerable:
		return hp_component.current_hp if hp_component else 0

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
	if movement_sm != null:
		movement_sm.reset()  # silent reset — clear the indicator explicitly
	set_dazed(false)
	if hp_component != null:
		_last_known_hp = hp_component.current_hp

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


## Enable/disable local gameplay projectile spawning.
func set_local_projectile_spawning_enabled(enabled: bool) -> void:
	local_projectile_spawning_enabled = enabled


## Apply the selected player color. Class spritesheets are tinted via modulate so the
## swatch slightly recolors the class artwork; the legacy procedural fallback instead
## bakes the color into freshly generated frames.
func set_player_color(color: Color) -> void:
	color.a = 1.0
	player_color = color
	if animated_sprite == null:
		return
	var alpha := animated_sprite.modulate.a
	if _uses_sheets:
		animated_sprite.modulate = _class_tint(alpha)
	else:
		animated_sprite.sprite_frames = ProceduralSprites.create_player_frames_for_color(player_color)
		animated_sprite.modulate = Color(1, 1, 1, alpha)


## Modulate color that tints class sheets toward the player color, preserving alpha.
## Returns plain white (no tint) when the procedural fallback is in use.
func _class_tint(alpha: float) -> Color:
	if not _uses_sheets:
		return Color(1, 1, 1, alpha)
	var tint := Color.WHITE.lerp(player_color, GameConstants.CLASS_SPRITE_TINT_STRENGTH)
	tint.a = alpha
	return tint


func _get_configured_player_color() -> Color:
	var tree := get_tree()
	if tree == null:
		return player_color
	var game_mgr = tree.root.get_node_or_null("GameManager")
	if game_mgr == null:
		return player_color
	return game_mgr.player_data.get("player_color", player_color)


## The local player's class (PacketTypes.PlayerClass). Defaults to Zealot —
## the same value NetworkManager sends in ConnectAuth.
func _get_configured_player_class() -> int:
	var tree := get_tree()
	if tree == null:
		return PacketTypes.PlayerClass.ZEALOT
	var game_mgr = tree.root.get_node_or_null("GameManager")
	if game_mgr == null:
		return PacketTypes.PlayerClass.ZEALOT
	return game_mgr.player_data.get("player_class", PacketTypes.PlayerClass.ZEALOT)


## Get readable state name for debugging
func get_state_name() -> String:
	var movement_str: String = MovementState.keys()[movement_state]
	var action_str: String = ActionState.keys()[action_state]
	return "%s / %s" % [movement_str, action_str]


## Whether the player is currently dead
var is_dead: bool:
	get:
		return hp_component.is_dead if hp_component else false
