## MovementStateMachine - Shared 7-state player movement model.
##
## Driven IDENTICALLY by the server (authoritative, in PlayerState.step) and the
## client (predicted, in PredictionController._apply_local_prediction). Both sides
## call tick() once per simulation step with the same derived inputs, so the
## prediction stays in step with the server and the existing position-reconciliation
## path corrects any divergence (e.g. a dash the server rejected). Because of that,
## this class must stay deterministic: it NEVER reads Input directly — all edges and
## held states arrive as tick() arguments.
##
## States (the spec): IDLE, WALKING, SPRINTING, DASHING, KNOCKED_BACK, STUNNED,
## ABILITY_MOVEMENT. Follows the codebase enum + match-dispatch + centralized
## _transition_to convention (see monster_ai.gd); timers are floats decremented
## with maxf(0.0, x - delta).
##
## Status-effect hooks (Haste/Slow speed mods; Root/Stun/Daze) are real methods left
## as placeholders for a future StatusEffectManager (search: TODO(StatusEffectManager)).
class_name MovementStateMachine
extends RefCounted


#region Enums
enum State {
	IDLE,             ## No movement input
	WALKING,          ## Movement input at base speed
	SPRINTING,        ## Movement input, sprint held, stamina available
	DASHING,          ## Fixed-duration burst, on cooldown
	KNOCKED_BACK,     ## External impulse, decelerating
	STUNNED,          ## Input blocked for a duration
	ABILITY_MOVEMENT  ## External system owns the velocity
}
#endregion


#region Signals (full event system for movement state changes)
## Emitted on every accepted state change.
signal movement_state_changed(from_state: State, to_state: State)
signal dash_started(direction: Vector2)
signal dash_ended()
signal sprint_started()
signal sprint_ended()
signal knockback_started(direction: Vector2, force: float)
signal knockback_ended()
signal stun_started(duration: float)
signal stun_ended()
signal daze_started(duration: float)
signal daze_ended()
signal stamina_changed(current: float, maximum: float)
signal mana_changed(current: float, maximum: float)
## Emitted on the rising/falling edge of sprint exhaustion (HUD blinks the stamina bar).
signal exhausted_changed(active: bool)
## Emitted on the RMB rising edge when the mana cost was paid. Offline (Sanctuary/practice)
## the player script reacts with a local per-class ability VFX preview; online the real effect
## is server-authoritative (this SM's tick() isn't driven for the local player there).
signal ability_triggered()
#endregion


#region State
var state: State = State.IDLE

## Resources (server-authoritative; client predicts, corrected via ACTION_CONFIRM).
var stamina: float = GameConstants.PLAYER_STAMINA_MAX
var mana: float = GameConstants.PLAYER_MANA_MAX

## RMB ability mana cost. The owner sets this per class (offline parity with the Rust sim's
## per-class config); defaults to the legacy flat cost.
var ability_cost: float = GameConstants.PLAYER_MANA_ABILITY_COST

## RMB ability cooldown (seconds). The owner sets this per class; 0 = no cooldown. The HUD
## ability bar reads it (with get_ability_cooldown_remaining) to draw the RMB slot's wedge.
var ability_cooldown_max: float = 0.0

## Per-class stamina regen (u/s) while not sprinting. The owner sets this per class (offline
## parity with the Rust sim's set_stamina_regen); e.g. the Mage regenerates slower.
var stamina_regen: float = GameConstants.PLAYER_STAMINA_REGEN_PER_SEC

# Timers (seconds), decremented maxf(0.0, x - delta).
var _dash_time_left: float = 0.0
var _dash_cooldown_left: float = 0.0   ## START-relative (begins when the dash begins)
var _ability_cooldown_left: float = 0.0  ## START-relative (begins when the RMB ability fires)
var _stun_time_left: float = 0.0
var _daze_time_left: float = 0.0       ## Daze is a timer, not a state: coexists with KNOCKED_BACK
var _exhaust_time_left: float = 0.0    ## Sprint-exhaustion lockout (no sprint, no regen, bar blinks)

# SM-owned velocities for the transient states.
var _dash_velocity: Vector2 = Vector2.ZERO
var _knockback_velocity: Vector2 = Vector2.ZERO
var _ability_velocity: Vector2 = Vector2.ZERO

## Aggregate Haste/Slow multiplier applied to ground speed, clamped.
## TODO(StatusEffectManager): query the manager each tick instead of caching.
var _speed_multiplier: float = 1.0

# Internal edge detection (so tick() can take held flags but act on rising edges).
var _prev_dash_held: bool = false
var _prev_ability_held: bool = false

var debug_logging: bool = false
#endregion


#region Per-tick driver
## Advance the SM one step and return the velocity to integrate this step.
##   move_dir      normalized WASD direction (may be Vector2.ZERO)
##   sprint_held   sprint input held this step
##   dash_held     dash input held this step (rising edge => dash)
##   ability_held  ability input held this step (rising edge => spend mana)
##   attacking     shoot input held this step (ends sprint)
##   aim_dir       normalized aim direction (dash target when move_dir is zero)
func tick(delta: float, move_dir: Vector2, sprint_held: bool, dash_held: bool,
		ability_held: bool, attacking: bool, aim_dir: Vector2) -> Vector2:
	_update_timers(delta)
	_update_stamina(delta)
	_update_mana(delta)

	# Rising-edge actions (computed from held flags so client and server agree).
	var dash_edge := dash_held and not _prev_dash_held
	var ability_edge := ability_held and not _prev_ability_held
	_prev_dash_held = dash_held
	_prev_ability_held = ability_held

	if dash_edge:
		try_dash(move_dir, aim_dir)
	if ability_edge:
		# Gate on cooldown then mana (mirrors the Rust sim's ability edge), and start the
		# cooldown only when the cast actually paid its cost.
		if _ability_cooldown_left <= 0.0 and try_use_mana(ability_cost):
			_ability_cooldown_left = ability_cooldown_max
			ability_triggered.emit()
	if attacking and state == State.SPRINTING:
		end_sprint()

	match state:
		State.IDLE, State.WALKING, State.SPRINTING:
			return _tick_grounded(move_dir, sprint_held)
		State.DASHING:
			return _tick_dashing()
		State.KNOCKED_BACK:
			return _tick_knockback(delta)
		State.STUNNED:
			return Vector2.ZERO
		State.ABILITY_MOVEMENT:
			return _ability_velocity
	return Vector2.ZERO


func _tick_grounded(move_dir: Vector2, sprint_held: bool) -> Vector2:
	if move_dir == Vector2.ZERO:
		_transition_to(State.IDLE)
		return Vector2.ZERO

	var want_sprint := sprint_held \
		and stamina > 0.0 \
		and _exhaust_time_left <= 0.0 \
		and not is_dazed()
	if want_sprint:
		_transition_to(State.SPRINTING)
	else:
		_transition_to(State.WALKING)
	return move_dir * get_ground_speed(want_sprint)


func _tick_dashing() -> Vector2:
	if _dash_time_left <= 0.0:
		_transition_to(State.IDLE)  # _tick_grounded re-derives WALK/SPRINT next step
		return Vector2.ZERO
	return _dash_velocity


func _tick_knockback(delta: float) -> Vector2:
	_knockback_velocity *= exp(-GameConstants.PLAYER_KNOCKBACK_DECAY * delta)
	if _knockback_velocity.length() <= GameConstants.PLAYER_KNOCKBACK_END_SPEED:
		_transition_to(State.IDLE)
		return Vector2.ZERO
	return _knockback_velocity
#endregion


#region Timers & resources
func _update_timers(delta: float) -> void:
	_dash_time_left = maxf(0.0, _dash_time_left - delta)
	_dash_cooldown_left = maxf(0.0, _dash_cooldown_left - delta)
	_ability_cooldown_left = maxf(0.0, _ability_cooldown_left - delta)
	if _daze_time_left > 0.0:
		_daze_time_left = maxf(0.0, _daze_time_left - delta)
		if _daze_time_left <= 0.0:
			daze_ended.emit()
	if state == State.STUNNED:
		_stun_time_left = maxf(0.0, _stun_time_left - delta)
		if _stun_time_left <= 0.0:
			_transition_to(State.IDLE)


func _update_stamina(delta: float) -> void:
	var before := stamina
	if _exhaust_time_left > 0.0:
		# Exhausted: regen is paused for the lockout (the stamina bar blinks client-side).
		_exhaust_time_left = maxf(0.0, _exhaust_time_left - delta)
		if _exhaust_time_left <= 0.0:
			exhausted_changed.emit(false)
		return
	if state == State.SPRINTING:
		stamina = maxf(0.0, stamina - GameConstants.PLAYER_STAMINA_DRAIN_PER_SEC * delta)
		if stamina <= 0.0:
			_exhaust_time_left = GameConstants.PLAYER_STAMINA_EXHAUST_DURATION
			exhausted_changed.emit(true)
	else:
		stamina = minf(GameConstants.PLAYER_STAMINA_MAX,
			stamina + stamina_regen * delta)
	if not is_equal_approx(before, stamina):
		stamina_changed.emit(stamina, GameConstants.PLAYER_STAMINA_MAX)


func _update_mana(delta: float) -> void:
	if mana >= GameConstants.PLAYER_MANA_MAX:
		return
	mana = minf(GameConstants.PLAYER_MANA_MAX,
		mana + GameConstants.PLAYER_MANA_REGEN_PER_SEC * delta)
	mana_changed.emit(mana, GameConstants.PLAYER_MANA_MAX)
#endregion


#region Transitions & validation
## Guard table: not every transition is legal.
func _can_transition(to_state: State) -> bool:
	# STUNNED only releases to IDLE via its own timer.
	if state == State.STUNNED and to_state != State.IDLE:
		return false
	# KNOCKED_BACK rides out unless a stun or an ability interrupts it.
	if state == State.KNOCKED_BACK and to_state not in [
			State.IDLE, State.STUNNED, State.ABILITY_MOVEMENT]:
		return false
	return true


func _transition_to(to_state: State) -> void:
	if state == to_state:
		return
	if not _can_transition(to_state):
		return

	var from_state := state
	state = to_state

	# Enter side-effects (signals whose payload the transition itself owns are
	# emitted by their trigger method: dash_started/knockback_started/stun_started).
	if to_state == State.SPRINTING:
		sprint_started.emit()

	# Exit side-effects, keyed on the state we are leaving.
	match from_state:
		State.SPRINTING:
			sprint_ended.emit()
		State.DASHING:
			dash_ended.emit()
		State.KNOCKED_BACK:
			knockback_ended.emit()
		State.STUNNED:
			stun_ended.emit()

	movement_state_changed.emit(from_state, to_state)
	if debug_logging:
		print("[MovementSM] %s -> %s" % [State.keys()[from_state], State.keys()[to_state]])
#endregion


#region Public API
## Instant dash on the dash edge. Guarded by cooldown and state validity.
## Direction is the move direction, or the aim direction when standing still.
func try_dash(move_dir: Vector2, aim_dir: Vector2) -> bool:
	if _dash_cooldown_left > 0.0:
		return false
	if is_dazed():
		return false
	if state in [State.STUNNED, State.KNOCKED_BACK, State.ABILITY_MOVEMENT]:
		return false
	var dir := move_dir if move_dir != Vector2.ZERO else aim_dir
	if dir == Vector2.ZERO:
		return false
	dir = dir.normalized()
	_dash_velocity = dir * (GameConstants.PLAYER_DASH_SPEED * _speed_multiplier)
	_dash_time_left = GameConstants.PLAYER_DASH_DURATION
	_dash_cooldown_left = GameConstants.PLAYER_DASH_COOLDOWN
	_transition_to(State.DASHING)
	dash_started.emit(dir)
	return true


## Apply knockback (direction * force * multiplier) with smooth deceleration.
func apply_knockback(direction: Vector2, force: float, multiplier: float = 1.0) -> void:
	if direction == Vector2.ZERO or force <= 0.0:
		return
	var dir := direction.normalized()
	_knockback_velocity = dir * (force * multiplier)
	_transition_to(State.KNOCKED_BACK)
	knockback_started.emit(dir, force * multiplier)


## End sprint imperatively (spec: called on attack or on taking damage).
func end_sprint() -> void:
	if state != State.SPRINTING:
		return
	_transition_to(State.WALKING)  # exit-handler emits sprint_ended


## External system takes over movement (ability dash/pull/etc.).
func start_ability_movement(initial_velocity: Vector2 = Vector2.ZERO) -> void:
	if state == State.STUNNED:
		return
	_ability_velocity = initial_velocity
	_transition_to(State.ABILITY_MOVEMENT)


## Update the ability-controlled velocity (call each step while owned).
func set_ability_velocity(velocity: Vector2) -> void:
	_ability_velocity = velocity


func end_ability_movement() -> void:
	if state != State.ABILITY_MOVEMENT:
		return
	_ability_velocity = Vector2.ZERO
	_transition_to(State.IDLE)


## Spend mana if available. Returns true if the cost was paid.
func try_use_mana(cost: float) -> bool:
	if cost <= 0.0:
		return true
	if mana < cost:
		return false
	mana = maxf(0.0, mana - cost)
	mana_changed.emit(mana, GameConstants.PLAYER_MANA_MAX)
	return true
#endregion


#region Status-effect placeholders (real logic, no manager wiring yet)
## Haste/Slow: set the aggregate ground-speed multiplier (clamped).
## TODO(StatusEffectManager): the manager should own stacking and either call this
## or be queried per tick instead of caching a single multiplier here.
func apply_speed_modifier(multiplier: float) -> void:
	_speed_multiplier = clampf(multiplier,
		GameConstants.PLAYER_SPEED_MULT_MIN, GameConstants.PLAYER_SPEED_MULT_MAX)


func clear_speed_modifier() -> void:
	_speed_multiplier = 1.0


## Stun: block movement input for a duration. Cancels an in-progress dash.
func apply_stun(duration: float) -> void:
	if duration <= 0.0:
		return
	_stun_time_left = duration
	_dash_time_left = 0.0
	_transition_to(State.STUNNED)
	stun_started.emit(duration)


## Root: should allow actions but block movement. Treated as Stun until the
## StatusEffectManager differentiates the two.
## TODO(StatusEffectManager): allow actions while rooted.
func apply_root(duration: float) -> void:
	apply_stun(duration)


## Daze reduces control instead of blocking it: sprint and dash are refused while
## the timer runs; walking (and knockback/ability velocities) proceed normally.
## Not a state — it coexists with KNOCKED_BACK (the usual companion on a hit).
## Re-application extends, never shortens. Mirrors rust/sim_core MovementSm.
func apply_daze(duration: float) -> void:
	if duration <= 0.0:
		return
	var was_dazed := is_dazed()
	_daze_time_left = maxf(_daze_time_left, duration)
	end_sprint()
	if not was_dazed:
		daze_started.emit(duration)


## Authoritative release (server -> client via the DAZED entity flag clearing).
func clear_daze() -> void:
	if not is_dazed():
		return
	_daze_time_left = 0.0
	daze_ended.emit()
#endregion


#region Network placeholder
## Stub hook for broadcasting movement-state changes to other clients. Real
## replication is handled by the server's entity-flag path (ENTITY_FLAG_DASHING /
## KNOCKED_BACK / STUNNED in PlayerState._update_entity_flags); this remains a
## no-op extension point.
## TODO(netcode): richer per-event movement broadcast if remote feel needs it.
func broadcast_movement_state() -> void:
	pass
#endregion


#region Queries & debug
## Effective ground speed (walk or sprint) including the Haste/Slow multiplier.
## Used by both live prediction and reconciliation replay so they agree.
func get_ground_speed(is_sprinting: bool) -> float:
	var base := GameConstants.PLAYER_SPRINT_SPEED if is_sprinting else GameConstants.PLAYER_SPEED
	return base * _speed_multiplier


func is_input_locked() -> bool:
	return state == State.DASHING or state == State.KNOCKED_BACK \
		or state == State.STUNNED or state == State.ABILITY_MOVEMENT


func get_state_name() -> String:
	return State.keys()[state]


func get_dash_cooldown_remaining() -> float:
	return _dash_cooldown_left


func get_ability_cooldown_remaining() -> float:
	return _ability_cooldown_left


## Online mirror: the Rust PredictionSim owns the dash/ability cooldown timers (this SM's tick()
## isn't driven for the local player online), so the PredictionController pushes them here each
## step so the HUD ability bar can draw both slot wedges identically online and offline.
func set_predicted_cooldowns(dash_remaining: float, ability_remaining: float) -> void:
	_dash_cooldown_left = maxf(0.0, dash_remaining)
	_ability_cooldown_left = maxf(0.0, ability_remaining)


func get_dash_time_remaining() -> float:
	return _dash_time_left


func get_stun_remaining() -> float:
	return _stun_time_left


func is_dazed() -> bool:
	return _daze_time_left > 0.0


## Sprint-exhaustion lockout active (offline) or mirrored from the server (online).
func is_exhausted() -> bool:
	return _exhaust_time_left > 0.0


## Online mirror: the Rust prediction sim owns exhaustion; the PredictionController pushes its
## state here each step so the HUD (connected to exhausted_changed) blinks identically. Emits
## only on the edge.
func set_exhausted_state(active: bool) -> void:
	var was := _exhaust_time_left > 0.0
	if active == was:
		return
	# A small positive timer marks "active" without competing with the offline countdown.
	_exhaust_time_left = GameConstants.PLAYER_STAMINA_EXHAUST_DURATION if active else 0.0
	exhausted_changed.emit(active)


func get_daze_remaining() -> float:
	return _daze_time_left


func get_stamina() -> float:
	return stamina


func get_mana() -> float:
	return mana


## Authoritatively set resources (server -> owner correction via ACTION_CONFIRM).
func set_resources(new_stamina: float, new_mana: float) -> void:
	var clamped_stamina := clampf(new_stamina, 0.0, GameConstants.PLAYER_STAMINA_MAX)
	var clamped_mana := clampf(new_mana, 0.0, GameConstants.PLAYER_MANA_MAX)
	if not is_equal_approx(clamped_stamina, stamina):
		stamina = clamped_stamina
		stamina_changed.emit(stamina, GameConstants.PLAYER_STAMINA_MAX)
	if not is_equal_approx(clamped_mana, mana):
		mana = clamped_mana
		mana_changed.emit(mana, GameConstants.PLAYER_MANA_MAX)


## Reset to a clean alive state (respawn / spawn).
func reset() -> void:
	state = State.IDLE
	stamina = GameConstants.PLAYER_STAMINA_MAX
	mana = GameConstants.PLAYER_MANA_MAX
	_dash_time_left = 0.0
	_dash_cooldown_left = 0.0
	_ability_cooldown_left = 0.0
	_stun_time_left = 0.0
	_daze_time_left = 0.0
	if _exhaust_time_left > 0.0:
		_exhaust_time_left = 0.0
		exhausted_changed.emit(false)
	_dash_velocity = Vector2.ZERO
	_knockback_velocity = Vector2.ZERO
	_ability_velocity = Vector2.ZERO
	_speed_multiplier = 1.0
	_prev_dash_held = false
	_prev_ability_held = false


func get_debug_info() -> Dictionary:
	return {
		"state": get_state_name(),
		"dash_cooldown": _dash_cooldown_left,
		"dash_time_left": _dash_time_left,
		"stun_remaining": _stun_time_left,
		"daze_remaining": _daze_time_left,
		"stamina": stamina,
		"mana": mana,
		"speed_multiplier": _speed_multiplier,
	}
#endregion
