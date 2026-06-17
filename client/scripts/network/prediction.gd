## PredictionController - Client-side prediction with server reconciliation
## Provides immediate local movement feedback while maintaining server authority
## Attach as child node to player scene, call setup() to initialize
class_name PredictionController
extends Node

## Preloaded so the GDExtension/headless class cache can't fail to resolve the
## global class during startup (repo convention: const named exactly like the class).
const ChargeTrail := preload("res://scripts/entities/world_effects/charge_trail.gd")


#region Signals
## Emitted when a server correction is applied
signal correction_applied(correction_amount: float)
## Emitted when prediction mismatches server (before reconciliation)
signal prediction_mismatch(predicted_pos: Vector2, server_pos: Vector2)
## Emitted when reconciliation completes
signal reconciliation_complete(replayed_inputs: int)
## Emitted when the local player's visual position changes.
signal visual_position_updated(visual_position: Vector2, is_discontinuous: bool)
## Cosmetic-only: emitted on the SHOOT rising-edge (and while held, gated to the
## server auto-fire cadence) so the client can draw an immediate muzzle flash
## without waiting for the PROJECTILE_FIRED round-trip. This does NOT spawn
## a Projectile and does NOT touch predicted_position or the input buffer.
signal shoot_predicted(muzzle_position: Vector2, aim_direction: Vector2)
#endregion


#region Configuration
## Correction interpolation speed (higher = snappier corrections)
@export var interpolation_speed: float = 12.0
## Maximum stored inputs (matches 8-bit sequence range)
@export var max_buffer_size: int = 256
## Enable debug output
@export var debug_logging: bool = false
## Enable low-volume shoot diagnostics for projectile/server sync issues
@export var projectile_sync_debug_logging: bool = false
## Threshold for instant teleport vs smooth correction (units)
@export var teleport_threshold: float = 150.0
## Ignore tiny quantization jitter from compressed server positions.
@export var server_position_epsilon: float = 4.0
#endregion


#region State Variables
## Reference to the controlled player node
var player_node: Node2D = null

## Optional remote-entity interpolation reference for shoot diagnostics
var interpolation_controller: InterpolationController = null

## Local player's entity ID (set during spawn/connection)
var local_entity_id: int = -1

## Current predicted position (authoritative client-side)
var predicted_position: Vector2 = Vector2.ZERO

## Current predicted velocity
var predicted_velocity: Vector2 = Vector2.ZERO

## True after receiving and applying at least one authoritative server position.
var has_authoritative_position: bool = false

## Last acknowledged sequence number from server (-1 = none yet)
var last_ack_sequence: int = -1

## Current input sequence number (0-255, wrapping)
var current_sequence: int = 0

## Input buffer: sequence_number (int) -> InputSnapshot
var input_buffer: Dictionary = {}

## Smooth correction state
var correction_target: Vector2 = Vector2.ZERO
var is_correcting: bool = false

## Server tick tracking for ordering
var last_server_tick: int = 0

## Input send rate limiting. Match the authoritative server tick interval.
var input_send_timer: float = 0.0
const INPUT_SEND_INTERVAL: float = GameConstants.SERVER_TICK_INTERVAL

## Only snap the predicted dash/RMB-ability cooldown to the server's authoritative value when
## they diverge by more than this (seconds). The predicted cooldown is committed at press time,
## so it normally runs ~RTT ahead of the value the server reports back; this threshold sits well
## above typical RTT so that benign offset never jitters the HUD, while a genuine desync — a
## refused / lost / cooldown-boundary dash leaves a multi-second gap — is pulled back into phase
## within ~1 RTT. See _handle_action_confirm.
const COOLDOWN_RECONCILE_EPSILON: float = 0.75

## Comms-loss safety ceiling: max time to follow the server through a knockback before force-resuming
## prediction. KNOCKED_BACK is only sent on flag *edges* (cached-vs-current delta), so a sustained or
## chained knockback exposes no per-tick re-affirmation. The ceiling is re-armed by every update that
## still shows the flag set (rising edge + each full-state baseline, sent every DELTA_FULL_STATE_INTERVAL
## = 100 ticks ≈ 3.3 s), so it must outlast that interval — otherwise it force-resumes mid-knockback and
## reintroduces the tug-of-war it exists to prevent. Genuine release is detected from the falling edge
## (including via the next baseline); this ceiling only fires if flag deltas AND baselines both stop.
const KNOCKBACK_FOLLOW_MAX_SECONDS: float = 4.0

## Current frame's accumulated input flags
var current_input_flags: int = 0

## When true, _capture_input_flags returns 0 (pause menu / modal open). See set_input_suppressed.
var _input_suppressed: bool = false

## Dash is edge-triggered. We latch the rising edge of the dash action and keep
## the INPUT_FLAG_DASH bit set until the next input is sent to the server, so a
## tap between 30 Hz sends is never dropped. Cleared in _send_input_to_server.
var _dash_latched: bool = false

## Last time (seconds) the cosmetic shoot feedback fired, used to gate held-fire
## to the server's SHOOT_COOLDOWN auto-fire cadence. -INF so the first shot fires.
var _last_predicted_shot_time: float = -INF

## Whether prediction and input sending are enabled for the local player.
var prediction_enabled: bool = true

## Last seen state of our own DAZED entity flag (edge-detected: snapshot flags
## are delta-compressed, so they arrive only when they change or on baselines).
var _own_dazed: bool = false

## True while the server's authoritative KNOCKED_BACK flag is set for the local player. The client
## never predicts knockback (apply_knockback is server-only — see rust/sim_core movement.rs), so
## while it's set we FREEZE input-driven prediction and just follow the server's position. Otherwise
## the input-driven sim pushes against the server's knockback and the reconcile lerp chases a moving
## target — the visible twitch. Slaved on the flag edge exactly like _own_dazed.
var _own_knocked_back: bool = false
## Latest authoritative server position for the local player (from snapshots / ActionConfirm) — the
## follow target while knocked back.
var _server_follow_position: Vector2 = Vector2.ZERO
var _has_server_follow_position: bool = false
## Comms-loss safety ceiling, re-armed by every update that still shows KNOCKED_BACK; force-resumes
## prediction at 0 only if flag deltas AND baselines both stop (see KNOCKBACK_FOLLOW_MAX_SECONDS).
var _knockback_follow_time_left: float = 0.0

## The shared Rust simulation core (migration-spec D5): prediction runs LITERALLY the same
## compiled code as the server's authoritative step, so movement divergence is zero by
## construction. Owns the movement state machine (dash/sprint/knockback timers, stamina/mana).
var _sim: PredictionSim = PredictionSim.new()

## Cached capability flag for _sim.has_method("is_charging") so the per-tick charge-loop SFX
## driver doesn't probe the GDExtension every physics frame. Set when the sim is configured.
var _sim_has_is_charging := false

## Per-class ability tuning pushed into PredictionSim.set_ability_config / set_base_speed /
## set_stamina_regen so the predicted ability cast/charge/stamina matches the server. Indexed by
## PacketTypes.PlayerClass (0..6): [mana_cost, cooldown, charge_speed, charge_max_distance,
## base_move_speed, stamina_regen, charge_mana_drain]. Only the Warrior (4) has charge_speed > 0
## (⇒ Warrior charge in the Rust sim) and a charge_mana_drain (mana bled per unit travelled); only
## the Mage (6) regenerates stamina slower. These mirror the values in
## client/data/classes/<class>.json (ability + stats.move_speed_base + stats.stamina_regen_per_sec).
const CLASS_ABILITY_CONFIG := [
	[35.0, 8.0, 0.0, 0.0, 195.0, 20.0, 0.0],      # 0 Zealot
	[30.0, 5.0, 0.0, 0.0, 205.0, 20.0, 0.0],      # 1 Void Hunter
	[35.0, 8.0, 0.0, 0.0, 195.0, 20.0, 0.0],      # 2 Engineer
	[35.0, 7.0, 0.0, 0.0, 195.0, 20.0, 0.0],      # 3 Plague Seer
	[30.0, 4.5, 720.0, 945.0, 200.0, 20.0, 10.0], # 4 Warrior (steerable charge; 30 activation + 10 mana spread over the draining (post-40%) distance; ~40 total; 4.5s cd)
	[30.0, 10.0, 0.0, 0.0, 215.0, 20.0, 0.0],     # 5 Rogue
	[40.0, 6.0, 0.0, 0.0, 195.0, 14.0, 0.0],      # 6 Mage (slower stamina regen)
]

## Last seen state of our own DASHING entity flag, used to slave a Warrior charge end to
## the server. When the server clears DASHING but PredictionSim still thinks it is charging,
## we call end_charge() so the predicted charge releases exactly when the server's does.
var _own_dashing: bool = false

## Last seen predicted charge state, so the looping "while charging" rumble fires on the charge
## edges (Warrior). Charge-specific — the regular dash is a different state, so it won't trigger.
## Distinct from _own_dashing, which edges on the server's DASHING flag (covering the plain dash
## too) to slave the charge END to the server; this one edges on the predicted is_charging state.
var _was_charging: bool = false

## Active shader-driven charge trail (Warrior), parented to the player while charging.
## Created on the charge rising edge and released (faded out) on the falling edge.
var _charge_trail: ChargeTrail = null
#endregion


#region Inner Classes
## Snapshot of input state for reconciliation replay
class InputSnapshot:
	var sequence: int = 0
	var input_flags: int = 0
	var position_before: Vector2 = Vector2.ZERO
	var position_after: Vector2 = Vector2.ZERO
	var velocity: Vector2 = Vector2.ZERO
	var aim_angle: float = 0.0
	var delta: float = 0.0
	var timestamp: float = 0.0
	## Predicted dash / RMB-ability cooldown (seconds) at the moment this input was sent. The
	## ActionConfirm for this sequence reports the server's authoritative cooldown for the SAME
	## input, so the owner can detect a desync per-sequence (see _handle_action_confirm) without a
	## stale in-flight confirm cancelling a freshly-predicted cooldown.
	var dash_cooldown: float = 0.0
	var ability_cooldown: float = 0.0

	static func create(seq: int, flags: int, pos_before: Vector2, pos_after: Vector2,
					   vel: Vector2, angle: float, dt: float,
					   dash_cd: float = 0.0, ability_cd: float = 0.0) -> InputSnapshot:
		var snapshot := InputSnapshot.new()
		snapshot.sequence = seq
		snapshot.input_flags = flags
		snapshot.position_before = pos_before
		snapshot.position_after = pos_after
		snapshot.velocity = vel
		snapshot.aim_angle = angle
		snapshot.delta = dt
		snapshot.dash_cooldown = dash_cd
		snapshot.ability_cooldown = ability_cd
		snapshot.timestamp = Time.get_ticks_msec() / 1000.0
		return snapshot
#endregion


#region Lifecycle
func _ready() -> void:
	# Connect to NetworkManager signals
	if NetworkManager.has_signal("server_message_received"):
		NetworkManager.server_message_received.connect(_on_server_message)

	# Initialize state
	_reset_state()


func _reset_state() -> void:
	input_buffer.clear()
	current_sequence = 0
	last_ack_sequence = -1
	is_correcting = false
	input_send_timer = 0.0
	current_input_flags = 0
	_own_knocked_back = false
	_has_server_follow_position = false
	_knockback_follow_time_left = 0.0


## Initialize the controller with a player node
func setup(player: Node2D, initial_position: Vector2, entity_id: int = -1) -> void:
	player_node = player
	local_entity_id = entity_id
	predicted_position = initial_position
	correction_target = initial_position
	has_authoritative_position = false
	_reset_state()

	if debug_logging:
		print("[Prediction] Setup: entity_id=%d, pos=%s" % [entity_id, initial_position])

	# Push the local player's class ability tuning + base move speed into the Rust sim so
	# predicted ability casts/charge match the server. Reads the class from GameManager.
	_configure_ability_for_local_class()


## Push the local player's class ability config + base move speed into PredictionSim so
## prediction matches the server. Reads the class id from GameManager.player_data and the
## tuning from CLASS_ABILITY_CONFIG (mirrors client/data/classes/<class>.json). Safe to call
## more than once (e.g. on setup and again if the class becomes known later).
func _configure_ability_for_local_class() -> void:
	var class_id := int(GameManager.player_data.get("player_class", PacketTypes.PlayerClass.ZEALOT))
	class_id = clampi(class_id, 0, CLASS_ABILITY_CONFIG.size() - 1)
	var cfg: Array = CLASS_ABILITY_CONFIG[class_id]
	# Cache the is_charging capability once; the per-tick charge-loop SFX driver reads the bool
	# instead of probing the GDExtension every physics frame.
	_sim_has_is_charging = _sim.has_method("is_charging")
	if _sim.has_method("set_ability_config"):
		_sim.set_ability_config(float(cfg[0]), float(cfg[1]), float(cfg[2]), float(cfg[3]))
	# cfg[6] (charge_mana_drain) is only nonzero for the Warrior. has_method guards a stale
	# GDExtension binary; warn loudly when the config needs the drain but the sim can't take it,
	# so the silent Warrior-charge divergence is surfaced rather than mispredicted in silence.
	if _sim.has_method("set_charge_mana_drain"):
		_sim.set_charge_mana_drain(float(cfg[6]))
	elif cfg[6] > 0.0:
		push_warning("[Prediction] PredictionSim lacks set_charge_mana_drain; Warrior charge will mispredict - rebuild client_ext")
	if _sim.has_method("set_base_speed"):
		_sim.set_base_speed(float(cfg[4]))
	if _sim.has_method("set_stamina_regen"):
		_sim.set_stamina_regen(float(cfg[5]))
	# Mirror the ability cooldown MAX into the GDScript SM so the HUD ability bar can compute the
	# RMB wedge ratio online (the Rust sim owns the live countdown, pushed each step into the SM).
	var sm := _get_movement_sm()
	if sm != null:
		sm.ability_cooldown_max = float(cfg[1])
#endregion


#region Main Loop
func _physics_process(delta: float) -> void:
	# Drive the looping Warrior-charge rumble from the predicted charge state. Evaluated up front
	# (before the early-returns) so it also stops on disconnect / inactive / death / freed player.
	# Cheap guards first; the actual sim probe (is_charging) runs last and only when reachable.
	var charging := player_node != null and NetworkManager.is_server_connected() and is_active() \
		and _sim != null and _sim_has_is_charging and _sim.is_charging()
	_drive_charge_loop_sfx(charging)
	_drive_charge_trail(charging)

	if player_node == null:
		return

	# Skip if not connected
	if not NetworkManager.is_server_connected():
		_emit_visual_position_updated(false)
		return

	if not is_active():
		current_input_flags = 0
		predicted_velocity = Vector2.ZERO
		_emit_visual_position_updated(false)
		return

	# Step 1: Capture current frame's input
	var previous_input_flags := current_input_flags
	current_input_flags = _capture_input_flags()
	if projectile_sync_debug_logging:
		_log_shoot_edge(previous_input_flags, current_input_flags)

	# Step 1b: Emit cosmetic-only shoot feedback (muzzle flash). Fires on
	# the SHOOT rising-edge and, while held, at most once per SHOOT_COOLDOWN so it
	# mirrors the server's auto-fire cadence. Does not move the player or spawn a
	# real projectile — server stays authoritative for damage.
	_maybe_emit_shoot_predicted(previous_input_flags, current_input_flags)

	# Step 2: Apply local prediction immediately
	_apply_local_prediction(current_input_flags, delta)

	# Step 3: Handle smooth correction interpolation
	if is_correcting:
		_apply_smooth_correction(delta)

	# Step 4: Send input to server at the server tick cadence
	input_send_timer += delta
	if input_send_timer >= INPUT_SEND_INTERVAL:
		_send_input_to_server()
		input_send_timer -= INPUT_SEND_INTERVAL

	_emit_visual_position_updated(false)
#endregion


#region Input Capture
func _capture_input_flags() -> int:
	# Paused / modal open: ignore all input so UI clicks don't shoot.
	if _input_suppressed:
		return 0

	var flags := 0

	# Movement (WASD)
	if Input.is_action_pressed("move_up"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_UP
	if Input.is_action_pressed("move_down"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_DOWN
	if Input.is_action_pressed("move_left"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_LEFT
	if Input.is_action_pressed("move_right"):
		flags |= PacketTypes.INPUT_FLAG_MOVE_RIGHT

	# Actions
	if Input.is_action_pressed("shoot"):
		flags |= PacketTypes.INPUT_FLAG_SHOOT
	if Input.is_action_pressed("ability"):
		flags |= PacketTypes.INPUT_FLAG_ABILITY
	if Input.is_action_pressed("sprint"):
		flags |= PacketTypes.INPUT_FLAG_SPRINT
	if Input.is_action_pressed("interact"):
		flags |= PacketTypes.INPUT_FLAG_INTERACT

	# Dash: latch the rising edge until the next send so the tap is never dropped.
	if Input.is_action_just_pressed("dash"):
		_dash_latched = true
	if _dash_latched:
		flags |= PacketTypes.INPUT_FLAG_DASH

	return flags


func _get_aim_angle() -> float:
	if player_node == null:
		return 0.0
	# Calculate angle from player to mouse
	var mouse_pos := player_node.get_global_mouse_position()
	return predicted_position.angle_to_point(mouse_pos)


## Mouse position in WORLD coordinates — the cursor the server needs for cursor-targeted
## abilities (Mage/Plague Seer cast point, Rogue blink/Shadowstep target). Falls back to
## the predicted position when the player node is unavailable.
func _get_cursor_world() -> Vector2:
	if player_node == null:
		return predicted_position
	return player_node.get_global_mouse_position()


func _log_shoot_edge(previous_flags: int, new_flags: int) -> void:
	var was_shooting := (previous_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	var is_shooting := (new_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	if not is_shooting or was_shooting or player_node == null:
		return

	var mouse_pos := player_node.get_global_mouse_position()
	var aim_angle := predicted_position.angle_to_point(mouse_pos)
	var monster_text := "none"

	if interpolation_controller != null:
		var monster_ids := interpolation_controller.get_entities_by_type(PacketTypes.EntityType.MONSTER)
		var lines: Array[String] = []
		for monster_id: int in monster_ids:
			var rendered_pos := interpolation_controller.get_entity_position(monster_id)
			var latest_pos := interpolation_controller.get_entity_latest_server_position(monster_id)
			lines.append("%d rendered=%s latest=%s gap=%.2f" % [
				monster_id,
				rendered_pos,
				latest_pos,
				rendered_pos.distance_to(latest_pos)
			])

		if not lines.is_empty():
			monster_text = ""
			for line in lines:
				if not monster_text.is_empty():
					monster_text += "; "
				monster_text += line

	var render_tick := interpolation_controller.render_tick if interpolation_controller != null else -1
	var newest_tick := interpolation_controller.current_server_tick if interpolation_controller != null else -1
	print("[Prediction] Shoot edge: local_entity=%d predicted_pos=%s mouse_world=%s aim_angle=%.4f server_tick=%d render_tick=%d monsters=[%s]" % [
		local_entity_id,
		predicted_position,
		mouse_pos,
		aim_angle,
		newest_tick,
		render_tick,
		monster_text
	])


## Cosmetic-only shoot feedback gate. Emits shoot_predicted on the SHOOT
## rising-edge, and while SHOOT stays held re-emits at most once per
## SHOOT_COOLDOWN to mirror the server's auto-fire cadence (server_main
## _process_shoot_inputs). Computes the muzzle origin exactly like the server
## (server_main._try_spawn_projectile) so the flash lines up with the real
## projectile. Purely visual — never writes predicted_position or the buffer.
func _maybe_emit_shoot_predicted(previous_flags: int, new_flags: int) -> void:
	if player_node == null:
		return

	var is_shooting := (new_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	if not is_shooting:
		return

	var was_shooting := (previous_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0
	var now := Time.get_ticks_msec() / 1000.0
	var rising_edge := not was_shooting
	var cooldown_elapsed := (now - _last_predicted_shot_time) >= GameConstants.SHOOT_COOLDOWN
	if not rising_edge and not cooldown_elapsed:
		return

	_last_predicted_shot_time = now

	var aim_direction := Vector2.from_angle(_get_aim_angle())
	var muzzle := predicted_position + aim_direction * (
		GameConstants.PLAYER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0
	)
	shoot_predicted.emit(muzzle, aim_direction)


func _get_client_render_tick() -> int:
	if interpolation_controller != null:
		return interpolation_controller.render_tick & 0xFFFF
	return maxi(0, last_server_tick - GameConstants.REMOTE_ENTITY_RENDER_DELAY_TICKS) & 0xFFFF
#endregion


#region Local Prediction
func _apply_local_prediction(input_flags: int, delta: float) -> void:
	# While the server owns our motion (knockback), don't predict from input — follow the server.
	# The client never applies knockback locally, so predicting here just fights the server.
	if _own_knocked_back:
		_follow_server_through_knockback(delta)
		return

	# Drive the shared Rust sim_core (D5): movement state machine tick + analytic obstacle
	# mover + realized-velocity recompute, in one extension call — the exact code the server
	# runs authoritatively. The reconcile path corrects position if real divergence appears
	# (e.g. an unacked server-side knockback).
	var direction := _get_direction_from_flags(input_flags)
	var aim_dir := Vector2.from_angle(_get_aim_angle())
	var result: Dictionary = _sim.step(
		delta,
		predicted_position,
		direction,
		(input_flags & PacketTypes.INPUT_FLAG_SPRINT) != 0,
		(input_flags & PacketTypes.INPUT_FLAG_DASH) != 0,
		(input_flags & PacketTypes.INPUT_FLAG_ABILITY) != 0,
		(input_flags & PacketTypes.INPUT_FLAG_SHOOT) != 0,
		aim_dir
	)
	predicted_position = result["position"]
	predicted_velocity = result["velocity"]

	# Mirror the predicted resources into the GDScript SM so HUD bars (stamina/mana signals)
	# keep working; the Rust sim owns the actual prediction state.
	var sm := _get_movement_sm()
	if sm != null:
		sm.set_resources(result["stamina"], result["mana"])
		# Mirror sprint-exhaustion so the stamina bar blinks identically online (the Rust sim
		# owns the lockout; the SM here only relays the edge to the HUD).
		if sm.has_method("set_exhausted_state"):
			sm.set_exhausted_state(bool(result.get("exhausted", false)))
		# Mirror the dash + RMB-ability cooldown timers (the Rust sim owns them online) so the HUD
		# ability bar draws both slot wedges. Without this the GDScript SM's timers stay 0 online.
		if sm.has_method("set_predicted_cooldowns"):
			sm.set_predicted_cooldowns(
				float(result.get("dash_cooldown", 0.0)),
				float(result.get("ability_cooldown", 0.0)))

	# Update visual position (unless correcting)
	_update_player_visual()


## Follow the server through a server-owned knockback instead of predicting it. The sim is still
## stepped with NEUTRAL input so its daze/cooldown/stamina timers keep counting with the server, but
## its position output is ignored: the rendered position is eased toward the latest authoritative
## server position (set by snapshots / ActionConfirm). One target ⇒ no tug-of-war, no jitter.
func _follow_server_through_knockback(delta: float) -> void:
	# Lost-flag backstop: if the falling-edge KNOCKED_BACK delta never arrives, resume anyway.
	_knockback_follow_time_left = maxf(0.0, _knockback_follow_time_left - delta)
	if _knockback_follow_time_left <= 0.0:
		_own_knocked_back = false
		_resume_prediction_after_knockback()
		return

	# Advance the sim's timers only (neutral input ⇒ no movement, no edges); mirror resources and
	# cooldowns to the HUD SM exactly like the normal path so the bars/wedges don't freeze.
	var aim_dir := Vector2.from_angle(_get_aim_angle())
	var result: Dictionary = _sim.step(delta, predicted_position, Vector2.ZERO, false, false, false, false, aim_dir)
	var sm := _get_movement_sm()
	if sm != null:
		sm.set_resources(result["stamina"], result["mana"])
		if sm.has_method("set_exhausted_state"):
			sm.set_exhausted_state(bool(result.get("exhausted", false)))
		if sm.has_method("set_predicted_cooldowns"):
			sm.set_predicted_cooldowns(
				float(result.get("dash_cooldown", 0.0)),
				float(result.get("ability_cooldown", 0.0)))

	# Ease the predicted position toward the server's authoritative position. Frame-rate-independent
	# exponential smoothing (1 - e^(-k·dt)) so the convergence rate is identical at 60 and 144 FPS.
	if _has_server_follow_position:
		var t := 1.0 - exp(-interpolation_speed * delta)
		var before := predicted_position
		predicted_position = predicted_position.lerp(_server_follow_position, t)
		predicted_velocity = ((predicted_position - before) / delta) if delta > 0.0 else Vector2.ZERO
	_update_player_visual()


## Resume normal prediction when a knockback ends (falling edge, or the backstop fires). Snap the
## logical position to where the server left us and drop the now-stale input buffer + any in-flight
## correction, so resumed prediction starts clean (the buffered inputs were consumed as knockback,
## never as movement, so replaying them would re-introduce divergence).
func _resume_prediction_after_knockback() -> void:
	if _has_server_follow_position:
		predicted_position = _server_follow_position
	predicted_velocity = Vector2.ZERO
	correction_target = predicted_position
	is_correcting = false
	input_buffer.clear()


## The local player's predicted movement state machine, or null if the controlled
## node does not expose one.
func _get_movement_sm() -> MovementStateMachine:
	if player_node != null and "movement_sm" in player_node:
		return player_node.movement_sm
	return null


func _get_direction_from_flags(flags: int) -> Vector2:
	var direction := Vector2.ZERO

	if flags & PacketTypes.INPUT_FLAG_MOVE_UP:
		direction.y -= 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_DOWN:
		direction.y += 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_LEFT:
		direction.x -= 1.0
	if flags & PacketTypes.INPUT_FLAG_MOVE_RIGHT:
		direction.x += 1.0

	return direction.normalized()
#endregion


#region Input Buffer Management
func _store_input(snapshot: InputSnapshot) -> void:
	input_buffer[snapshot.sequence] = snapshot

	# Prune old acknowledged inputs
	_prune_acknowledged_inputs()


func _prune_acknowledged_inputs() -> void:
	if last_ack_sequence < 0:
		return

	var keys_to_remove: Array[int] = []

	for seq: int in input_buffer.keys():
		if _is_sequence_acknowledged(seq):
			keys_to_remove.append(seq)

	for seq in keys_to_remove:
		input_buffer.erase(seq)

	if debug_logging and keys_to_remove.size() > 0:
		print("[Prediction] Pruned %d acknowledged inputs, buffer size: %d" % [
			keys_to_remove.size(), input_buffer.size()
		])


func _is_sequence_acknowledged(seq: int) -> bool:
	# A sequence is acknowledged if it's "before or equal to" last_ack_sequence
	# accounting for 8-bit wraparound
	if last_ack_sequence < 0:
		return false

	if seq == last_ack_sequence:
		return true

	return _sequence_less_than(seq, last_ack_sequence)


## Compare two 8-bit sequence numbers with wraparound
## Returns true if seq_a came before seq_b
func _sequence_less_than(seq_a: int, seq_b: int) -> bool:
	# Calculate forward distance (seq_a -> seq_b going up)
	var forward_dist := (seq_b - seq_a) & 0xFF

	# If forward distance is in lower half (0-127), seq_a is less
	# If forward distance is in upper half (128-255), seq_b wrapped and is less
	return forward_dist > 0 and forward_dist < 128


## Get the next sequence number with wrap
func _advance_sequence() -> int:
	var seq := current_sequence
	current_sequence = (current_sequence + 1) & 0xFF
	return seq
#endregion


#region Network Communication
func _send_input_to_server() -> void:
	if not is_active() or not NetworkManager.is_server_connected():
		return

	var seq := _advance_sequence()
	var aim_angle := _get_aim_angle()
	var cursor_world := _get_cursor_world()
	var network_stats := NetworkManager.get_stats()
	var client_render_tick := _get_client_render_tick()
	var client_rtt_ms := int(network_stats.get("ping_ms", 0.0))

	# Store one replay snapshot per sent input. The server applies one input over
	# one authoritative tick, so replay uses the same interval. The stateless ground
	# model runs through the same Rust mover the server uses.
	var replay: Dictionary = _sim.replay_step(predicted_position, current_input_flags, INPUT_SEND_INTERVAL)
	# Record the PREDICTED cooldowns alongside the input so the ActionConfirm for this sequence can
	# be compared against what we predicted at this exact point (see _handle_action_confirm).
	var snap_dash_cd := _sim.dash_cooldown_remaining() if _sim.has_method("dash_cooldown_remaining") else 0.0
	var snap_ability_cd := _sim.ability_cooldown_remaining() if _sim.has_method("ability_cooldown_remaining") else 0.0
	var snapshot := InputSnapshot.create(
		seq,
		current_input_flags,
		predicted_position,
		replay["position"],
		replay["velocity"],
		aim_angle,
		INPUT_SEND_INTERVAL,
		snap_dash_cd,
		snap_ability_cd
	)
	_store_input(snapshot)

	# Build input data dictionary matching expected format
	var input_data := {
		"position": predicted_position,
		"velocity": predicted_velocity,
		"input_flags": current_input_flags,
		"keys": {
			"up": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_UP),
			"down": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_DOWN),
			"left": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_LEFT),
			"right": bool(current_input_flags & PacketTypes.INPUT_FLAG_MOVE_RIGHT),
			"shoot": bool(current_input_flags & PacketTypes.INPUT_FLAG_SHOOT),
			"ability": bool(current_input_flags & PacketTypes.INPUT_FLAG_ABILITY),
			"sprint": bool(current_input_flags & PacketTypes.INPUT_FLAG_SPRINT),
			"interact": bool(current_input_flags & PacketTypes.INPUT_FLAG_INTERACT),
			"dash": bool(current_input_flags & PacketTypes.INPUT_FLAG_DASH)
		},
		"aim_angle": aim_angle,
		"cursor": cursor_world,
		"sequence": seq,
		"client_render_tick": client_render_tick,
		"client_rtt_ms": client_rtt_ms
	}

	NetworkManager.send_player_input(input_data)

	# The dash edge has now been sent to the server; release the latch so the bit
	# is set in exactly one input packet.
	_dash_latched = false

	if debug_logging:
		print("[Prediction] Sent input: seq=%d, pos=%s, flags=%d, render_tick=%d, rtt_ms=%d" % [
			seq, predicted_position, current_input_flags, client_render_tick, client_rtt_ms
		])
#endregion


#region Server Message Handling
func _on_server_message(message_type: int, data: Dictionary) -> void:
	match message_type:
		NetworkManager.MessageType.ACTION_CONFIRM:
			_handle_action_confirm(data)
		NetworkManager.MessageType.STATE_UPDATE:
			_handle_state_update(data)


func _handle_action_confirm(data: Dictionary) -> void:
	var sequence: int = data.get("sequence_number", 0)
	var action_type: int = data.get("action_type", 0)
	var corrected_position: Vector2 = data.get("corrected_position", Vector2.ZERO)
	var result_code: int = data.get("result_code", 0)
	var server_tick: int = data.get("server_tick", 0)

	if debug_logging:
		print("[Prediction] ActionConfirm: seq=%d, action=%d, result=%d, pos=%s, tick=%d" % [
			sequence, action_type, result_code, corrected_position, server_tick
		])

	# Only handle MOVE action type
	if action_type != PacketTypes.ActionType.MOVE:
		return

	# Apply the authoritative stamina/mana that rode along with this confirmation —
	# into the Rust sim (the prediction authority) and mirrored to the GDScript SM
	# for HUD signals.
	if data.has("stamina"):
		_sim.set_resources(float(data.get("stamina", 100)), float(data.get("mana", 100)))
		var sm := _get_movement_sm()
		if sm != null:
			sm.set_resources(_sim.stamina(), _sim.mana())

	# Authoritative current HP for the HUD bar. The bar is a display mirror (start full, minus
	# DAMAGE, plus PICKUP heals) that can't see server-side regen, so it drifts low; this snaps it
	# back to the server's value. ONLY while alive — death is server-authoritative (the reliable
	# KILL/KILL_PVP event drives it, see arena_base._enter_local_death), so a 0 here must not
	# trigger the client death path. set_hp clamps to the class+level max_hp (which matches the
	# server's max_health).
	if data.has("health") and player_node != null and "hp_component" in player_node:
		var hp := int(data.get("health", 0))
		var hp_comp = player_node.hp_component
		if hp > 0 and hp_comp != null:
			hp_comp.set_hp(hp)

	# Reconcile the predicted dash + RMB-ability cooldowns against the server's authoritative ones,
	# which ride along on this confirm. The cooldowns are committed locally on the PREDICTED
	# dash/cast, so without this they drift permanently out of phase whenever the server refuses /
	# never receives a dash, or it's fired at the cooldown boundary (the server's cooldown lags the
	# client's by ~RTT). Symptom: the HUD shows a cooldown the server isn't enforcing — you lunge a
	# couple units, snap back, and the dash never lands — then a later press "while on cooldown"
	# actually dashes because the server cleared its timer long ago.
	#
	# Compared PER-SEQUENCE (not against the live cooldown): the confirm reports the server's
	# cooldown for the input it's acking, so we diff it against what we PREDICTED when we sent that
	# same input (input_buffer snapshot). This is essential — confirms still in flight for inputs
	# sent BEFORE a dash legitimately read cooldown 0 on the server, and diffing those against the
	# live (just-started) cooldown would cancel a correct prediction for ~1 RTT on every dash.
	_reconcile_cooldowns(sequence, data)

	# Update tracking
	last_ack_sequence = sequence
	last_server_tick = server_tick

	# Track the authoritative position as the knockback-follow target.
	_server_follow_position = corrected_position
	_has_server_follow_position = true

	# While the server owns our motion (knockback), follow it (handled in _apply_local_prediction)
	# and never replay inputs from here — the freeze exists precisely to avoid that divergence.
	if _own_knocked_back:
		_prune_acknowledged_inputs()
		return

	# Check if correction is needed
	# result_code != SUCCESS means the server sent us a correction
	if result_code != PacketTypes.ResultCode.SUCCESS:
		_reconcile(sequence, corrected_position)
	else:
		if not has_authoritative_position:
			force_sync(corrected_position)
		elif predicted_position.distance_to(corrected_position) > server_position_epsilon:
			_reconcile(sequence, corrected_position)
		else:
			_prune_acknowledged_inputs()


## Pull the predicted dash + RMB-ability cooldowns back into phase with the server's authoritative
## values for the acked input (`sequence`). For each, diff the server's value against what we
## predicted when we SENT that input (the per-sequence snapshot). A gap beyond the reconcile
## epsilon is a genuine desync; we shift the LIVE cooldown by that gap (so the ~RTT of real time
## that elapsed since the send cancels out exactly) and propagate the same shift to the snapshots
## of inputs still in flight, so the rest of that batch — which recorded the pre-correction
## prediction — doesn't re-apply the correction. No-op (the common case) when they already agree.
func _reconcile_cooldowns(sequence: int, data: Dictionary) -> void:
	if not input_buffer.has(sequence):
		return
	var snap: InputSnapshot = input_buffer[sequence]
	if data.has("dash_cooldown") and _sim.has_method("set_dash_cooldown") \
			and _sim.has_method("dash_cooldown_remaining"):
		var gap := float(data.get("dash_cooldown", 0.0)) - snap.dash_cooldown
		if absf(gap) > COOLDOWN_RECONCILE_EPSILON:
			_sim.set_dash_cooldown(maxf(0.0, _sim.dash_cooldown_remaining() + gap))
			_shift_buffered_cooldowns(sequence, gap, true)
	if data.has("ability_cooldown") and _sim.has_method("set_ability_cooldown") \
			and _sim.has_method("ability_cooldown_remaining"):
		var gap_ability := float(data.get("ability_cooldown", 0.0)) - snap.ability_cooldown
		if absf(gap_ability) > COOLDOWN_RECONCILE_EPSILON:
			_sim.set_ability_cooldown(maxf(0.0, _sim.ability_cooldown_remaining() + gap_ability))
			_shift_buffered_cooldowns(sequence, gap_ability, false)


## Apply a cooldown phase correction to every still-in-flight input snapshot (sequence AFTER
## `acked`) so the remaining confirms in this batch — which recorded the pre-correction prediction
## — compare against the corrected baseline and don't double-apply the same shift.
func _shift_buffered_cooldowns(acked: int, delta: float, is_dash: bool) -> void:
	for seq: int in input_buffer.keys():
		if not _sequence_less_than(acked, seq):
			continue
		var snap: InputSnapshot = input_buffer[seq]
		if is_dash:
			snap.dash_cooldown = maxf(0.0, snap.dash_cooldown + delta)
		else:
			snap.ability_cooldown = maxf(0.0, snap.ability_cooldown + delta)


func _handle_state_update(data: Dictionary) -> void:
	var server_tick: int = data.get("server_tick", 0)
	var entities: Array = data.get("entities", [])
	var is_delta := (int(data.get("state_flags", 0)) & PacketTypes.STATE_FLAG_IS_DELTA) != 0

	last_server_tick = server_tick

	# Skip if we don't know our entity ID
	if local_entity_id < 0:
		return

	# Find our entity in the update
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id == local_entity_id:
			var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
			var has_flags := not is_delta \
				or (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0 \
				or (delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0
			if has_flags:
				_update_own_flags(int(entity_data.get("flags", 0)))
			if is_delta \
				and (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) == 0 \
				and (delta_mask & PacketTypes.DELTA_MASK_POSITION) == 0:
				return
			_process_own_state_update(entity_data)
			break


## Slave the local daze to the server's authoritative DAZED flag: on the rising
## edge the Rust sim stops sprinting/dashing with the server (so prediction does
## not rubber-band through the whole daze), on the falling edge it releases
## exactly when the server does. The local timer self-expires as a lost-packet
## backstop. The GDScript SM is mirrored too so its daze signals drive the
## Player's daze indicator.
func _update_own_flags(flags: int) -> void:
	_update_own_charge(flags)

	# Slave the knockback-follow to the server's KNOCKED_BACK flag. On the rising edge we cancel any
	# in-flight predictive correction (so it doesn't fight the follow) and arm the lost-flag backstop;
	# on the falling edge we resume prediction cleanly from the server's last position.
	var knocked_back := (flags & PacketTypes.ENTITY_FLAG_KNOCKED_BACK) != 0
	if knocked_back != _own_knocked_back:
		_own_knocked_back = knocked_back
		if knocked_back:
			is_correcting = false  # don't let an in-flight correction fight the follow
		else:
			_resume_prediction_after_knockback()
	# Re-arm the comms-loss ceiling on every update that still shows the flag (rising edge + each
	# baseline). Because the flag is not re-sent per tick, a sustained/chained knockback would otherwise
	# expire the timer mid-knockback; refreshing it on baselines keeps the follow alive while the server
	# really is still knocking us back, and the ceiling only matters once updates stop entirely.
	if knocked_back:
		_knockback_follow_time_left = KNOCKBACK_FOLLOW_MAX_SECONDS

	var dazed := (flags & PacketTypes.ENTITY_FLAG_DAZED) != 0
	if dazed == _own_dazed:
		return
	_own_dazed = dazed
	if dazed:
		_sim.apply_daze(GameConstants.PLAYER_DAZE_DURATION)
	else:
		_sim.clear_daze()
	var sm := _get_movement_sm()
	if sm != null:
		if dazed:
			sm.apply_daze(GameConstants.PLAYER_DAZE_DURATION)
		else:
			sm.clear_daze()


## Slave a Warrior charge end to the server, mirroring the DAZED slaving above. The
## charge is the DASHING movement state on the wire; when the server clears DASHING but
## PredictionSim still thinks we are charging, release the predicted charge so it ends
## exactly when the server's does (no rubber-band through the rest of the charge path).
func _update_own_charge(flags: int) -> void:
	var dashing := (flags & PacketTypes.ENTITY_FLAG_DASHING) != 0
	if dashing == _own_dashing:
		return
	_own_dashing = dashing
	if not dashing and _sim.has_method("is_charging") and _sim.is_charging():
		if _sim.has_method("end_charge"):
			_sim.end_charge()


## Start/stop the looping "while charging" rumble on the predicted charge edges.
func _drive_charge_loop_sfx(charging: bool) -> void:
	if charging == _was_charging:
		return
	_was_charging = charging
	if charging:
		AudioManager.play_charge_loop()
	else:
		AudioManager.stop_charge_loop()


## Attach/release the shader-driven charge trail (Warrior) on the charge edges.
## Edge-detected via _charge_trail's existence so it mirrors the charge-loop SFX.
func _drive_charge_trail(charging: bool) -> void:
	if charging:
		if _charge_trail == null and player_node != null and is_instance_valid(player_node):
			_charge_trail = ChargeTrail.create()
			player_node.add_child(_charge_trail)
	elif _charge_trail != null:
		if is_instance_valid(_charge_trail):
			_charge_trail.finish()  # stop emitting; self-frees once embers fade
		_charge_trail = null


## Safety: stop the charge rumble if the controller is freed mid-charge (scene change), since
## _physics_process won't run to clear it (the AudioManager autoload outlives this node).
func _exit_tree() -> void:
	if _was_charging:
		AudioManager.stop_charge_loop()
		_was_charging = false
	if _charge_trail != null and is_instance_valid(_charge_trail):
		_charge_trail.finish()
	_charge_trail = null


func _process_own_state_update(entity_data: Dictionary) -> void:
	var server_position: Vector2 = entity_data.get("position", Vector2.ZERO)
	_server_follow_position = server_position
	_has_server_follow_position = true

	if not has_authoritative_position:
		force_sync(server_position)
		return

	# Server owns our motion during knockback — follow it (eased in _follow_server_through_knockback)
	# and do NOT replay inputs: the client never predicted the knockback, so a reconcile-replay from
	# here re-introduces the divergence the freeze removes. Keep the buffer from growing.
	if _own_knocked_back:
		_prune_acknowledged_inputs()
		return

	# If no unacknowledged inputs, sync directly to server position
	if input_buffer.is_empty():
		_apply_authoritative_position_without_replay(server_position)
		return

	# Otherwise, check for significant drift (possible packet loss)
	var discrepancy := predicted_position.distance_to(server_position)

	if discrepancy > server_position_epsilon:
		if debug_logging:
			print("[Prediction] StateUpdate drift detected (%.2f), reconciling from server position" % discrepancy)
		_reconcile(last_ack_sequence, server_position)
#endregion


#region Reconciliation
func _reconcile(ack_sequence: int, server_position: Vector2) -> void:
	var discrepancy := predicted_position.distance_to(server_position)

	if debug_logging:
		print("[Prediction] Reconciling: seq=%d, discrepancy=%.2f" % [ack_sequence, discrepancy])
		print("[Prediction]   Predicted: %s, Server: %s" % [predicted_position, server_position])

	prediction_mismatch.emit(predicted_position, server_position)

	# Step 1: Reset to server's authoritative position
	predicted_position = server_position
	has_authoritative_position = true

	# Step 2: Collect and replay unacknowledged inputs in order
	var unacked_sequences := _get_unacknowledged_sequences(ack_sequence)
	var replayed_count := 0

	for seq in unacked_sequences:
		if input_buffer.has(seq):
			var snapshot: InputSnapshot = input_buffer[seq]
			_replay_input(snapshot)
			replayed_count += 1

	if debug_logging:
		print("[Prediction]   Replayed %d inputs" % replayed_count)
		print("[Prediction]   Final predicted: %s" % predicted_position)

	# Step 3: Calculate visual correction needed
	var visual_pos := player_node.position if player_node else predicted_position
	var correction_amount := visual_pos.distance_to(predicted_position)

	# Step 4: Apply correction (instant or smooth)
	if correction_amount > teleport_threshold:
		_apply_instant_correction()
		if debug_logging:
			print("[Prediction]   Applied instant correction (%.2f > %.2f)" % [
				correction_amount, teleport_threshold
			])
	else:
		_start_smooth_correction(visual_pos)
		if debug_logging:
			print("[Prediction]   Starting smooth correction (%.2f)" % correction_amount)

	# Step 5: Emit signals
	correction_applied.emit(correction_amount)
	reconciliation_complete.emit(replayed_count)

	# Step 6: Prune acknowledged inputs
	_prune_acknowledged_inputs()


func _get_unacknowledged_sequences(ack_sequence: int) -> Array[int]:
	## Returns unacknowledged sequence numbers in order
	var result: Array[int] = []

	# Start from one after the acknowledged sequence
	var seq := (ack_sequence + 1) & 0xFF

	# Iterate up to current_sequence
	var safety := 0
	while seq != current_sequence and safety < 256:
		if input_buffer.has(seq):
			result.append(seq)
		seq = (seq + 1) & 0xFF
		safety += 1

	return result


func _replay_input(snapshot: InputSnapshot) -> void:
	## Re-simulate this input from current predicted_position through the Rust sim's
	## stateless ground model (deliberately NOT the full state machine: dash/knockback
	## are brief, rarely span a correction, and any residual heals on the next snapshot).
	var replay: Dictionary = _sim.replay_step(predicted_position, snapshot.input_flags, snapshot.delta)
	predicted_position = replay["position"]

	# Update snapshot for potential future replays
	snapshot.position_after = predicted_position
	snapshot.velocity = replay["velocity"]
#endregion


#region Visual Updates
func _update_player_visual() -> void:
	if player_node == null:
		return

	if not is_correcting:
		player_node.position = predicted_position


func _start_smooth_correction(_from_position: Vector2) -> void:
	correction_target = predicted_position
	is_correcting = true


func _apply_instant_correction() -> void:
	if player_node != null:
		player_node.position = predicted_position
		# Hard correction is a discontinuity — don't let physics_interpolation
		# visually lerp the local player across the snap.
		player_node.reset_physics_interpolation()
		_emit_visual_position_updated(true)
	correction_target = predicted_position
	is_correcting = false


func _apply_smooth_correction(delta: float) -> void:
	if player_node == null:
		is_correcting = false
		return

	# Target is the current predicted position (moves each frame)
	correction_target = predicted_position

	# Frame-rate-independent exponential interpolation toward target (1 - e^(-k·dt)): same convergence
	# rate regardless of FPS, unlike the raw interpolation_speed * delta approximation.
	var current_visual := player_node.position
	var new_visual := current_visual.lerp(correction_target, 1.0 - exp(-interpolation_speed * delta))

	# Check if close enough to stop correcting
	var remaining := new_visual.distance_to(correction_target)
	if remaining < 1.0:
		player_node.position = correction_target
		is_correcting = false
	else:
		player_node.position = new_visual
#endregion


#region Utility
## Force sync with server (for recovery scenarios)
func force_sync(server_position: Vector2) -> void:
	input_buffer.clear()
	predicted_position = server_position
	predicted_velocity = Vector2.ZERO
	correction_target = server_position
	is_correcting = false
	has_authoritative_position = true
	if player_node:
		player_node.position = server_position
		player_node.reset_physics_interpolation()
	_emit_visual_position_updated(true)

	if debug_logging:
		print("[Prediction] Force synced to %s" % server_position)


## Get current state for debugging
func get_debug_info() -> Dictionary:
	return {
		"predicted_position": predicted_position,
		"predicted_velocity": predicted_velocity,
		"current_sequence": current_sequence,
		"last_ack_sequence": last_ack_sequence,
		"buffer_size": input_buffer.size(),
		"is_correcting": is_correcting,
		"local_entity_id": local_entity_id,
		"has_authoritative_position": has_authoritative_position
	}


## Check if prediction is active
func is_active() -> bool:
	return prediction_enabled and player_node != null and local_entity_id >= 0 and has_authoritative_position


## World-space position at which the local player is currently rendered. While a
## smooth correction is in flight this trails predicted_position — the correction
## target moves each frame while player_node.position only lerps toward it — so
## callers that must match exactly what the player sees on screen (e.g.
## LocalHitDetector) should test against this, not predicted_position.
func get_rendered_position() -> Vector2:
	if player_node != null:
		return player_node.position
	return predicted_position


## Suppress all input capture (e.g. while the pause menu is open) so clicking UI
## buttons doesn't register as shoot/ability and movement keys are ignored. Prediction
## and networking keep running; only the polled input is forced to zero.
func set_input_suppressed(suppressed: bool) -> void:
	if _input_suppressed == suppressed:
		return
	_input_suppressed = suppressed
	if suppressed:
		current_input_flags = 0


## Enable or disable local prediction and outbound input.
func set_prediction_enabled(enabled: bool) -> void:
	if prediction_enabled == enabled:
		return

	prediction_enabled = enabled
	current_input_flags = 0
	predicted_velocity = Vector2.ZERO
	input_send_timer = 0.0
	input_buffer.clear()
	is_correcting = false


func _emit_visual_position_updated(is_discontinuous: bool) -> void:
	if player_node:
		visual_position_updated.emit(player_node.position, is_discontinuous)


## Set local entity ID once PLAYER_INFO identifies this client.
func set_local_entity_id(entity_id: int) -> void:
	local_entity_id = entity_id


## Reset the shared Rust sim to a clean alive state. Mirrors the server's movement-SM
## reset on respawn (dash cooldown cleared, stamina/mana full, daze cleared).
func reset_sim() -> void:
	_sim.reset()
	_own_dazed = false
	_own_dashing = false
	# Re-apply the per-class ability tuning the reset may have cleared.
	_configure_ability_for_local_class()


## Adopt an authoritative base move speed (from a server PROGRESS event) into the Rust sim
## so prediction speed tracks the player's level. No-op if the GDExtension lacks the method.
func set_base_speed(base_speed: float) -> void:
	if base_speed > 0.0 and _sim.has_method("set_base_speed"):
		_sim.set_base_speed(base_speed)


## Set the connected instance's world geometry on the shared sim (Arena = ±1000 + obstacles;
## Sanctuary = ±1856, no obstacles). The sim geometry is a thread-local in the Rust core, so
## this MUST run on the same (main) thread that calls step(), before the first predicted step.
## No-op if the GDExtension lacks the method.
func set_world_geometry(min_bound: Vector2, max_bound: Vector2, obstacles_enabled: bool) -> void:
	if _sim.has_method("set_world_geometry"):
		_sim.set_world_geometry(min_bound, max_bound, obstacles_enabled)


## Check if the controller has applied an authoritative spawn/server position.
func has_authoritative_sync() -> bool:
	return has_authoritative_position


func _apply_authoritative_position_without_replay(server_position: Vector2) -> void:
	var discrepancy := predicted_position.distance_to(server_position)
	predicted_position = server_position
	correction_target = server_position
	has_authoritative_position = true

	if discrepancy > teleport_threshold:
		_apply_instant_correction()
	elif discrepancy > server_position_epsilon:
		var visual_pos := player_node.position if player_node else predicted_position
		_start_smooth_correction(visual_pos)
	else:
		_update_player_visual()
#endregion
