//! The 7-state movement state machine — a verbatim port of `movement_state_machine.gd`
//! (extraction §4.6). Deterministic: never reads input devices; all edges and held states arrive
//! as `tick()` arguments. Timers are f64 decremented `max(0.0, x - dt)` — the exact accumulation
//! order matters (a dash lasts 13 ticks at 30 Hz because of f64 residue; see extraction §4.11).
//!
//! GDScript signals are not ported; callers diff `state()` before/after `tick()` for
//! transition-driven effects (HUD/audio live client-side).

use crate::constants::*;
use crate::vec2::{is_equal_approx_f64, Vec2};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum MoveState {
    Idle = 0,
    Walking = 1,
    Sprinting = 2,
    Dashing = 3,
    KnockedBack = 4,
    Stunned = 5,
    AbilityMovement = 6,
    /// Warrior Charge: held-input dash along the aim/move direction, INVULNERABLE, up to a max
    /// distance. Ends on release, max-distance, or (server-side) enemy contact — the server then
    /// spawns the AOE blast. Predicted on the client (purely directional, no target lookup).
    Charging = 7,
}

#[derive(Debug, Clone)]
pub struct MovementSm {
    state: MoveState,
    stamina: f64,
    mana: f64,
    dash_time_left: f64,
    dash_cooldown_left: f64,
    stun_time_left: f64,
    daze_time_left: f64,
    dash_velocity: Vec2,
    knockback_velocity: Vec2,
    ability_velocity: Vec2,
    speed_multiplier: f64,
    prev_dash_held: bool,
    prev_ability_held: bool,
    // ── Per-class config (set once when the class/level is known; preserved across reset) ──
    /// Base ground speed for this class+level (replaces the global PLAYER_SPEED).
    base_speed: f64,
    /// Mana cost of the RMB ability for this class.
    ability_cost: f64,
    /// Cooldown (s) of the RMB ability for this class. 0 = no cooldown.
    ability_cooldown_max: f64,
    /// >0 marks the RMB ability as a Charge (Warrior): this is the charge speed (u/s).
    charge_speed: f64,
    /// Max charge distance (units) before the charge ends on its own.
    charge_max_distance: f64,
    // ── Ability runtime state ──
    ability_cooldown_left: f64,
    /// Sprint-exhaustion lockout: while > 0, sprint is refused and stamina regen is paused.
    /// Set when sprinting drains stamina to 0.
    exhaust_time_left: f64,
    /// Transient: an INSTANT ability (non-charge) cast + spent mana this tick. The server reads it
    /// to dispatch the effect; the client to play cast VFX. Cleared at the top of every tick.
    ability_fired: bool,
    /// Transient: the charge ended NATURALLY this tick (release or max-distance), so the server
    /// should spawn the AOE blast. NOT set by `end_charge`/stun/teleport (those are not "blasts").
    charge_just_ended: bool,
    charge_velocity: Vec2,
    charge_distance_left: f64,
}

impl Default for MovementSm {
    fn default() -> Self {
        Self::new()
    }
}

impl MovementSm {
    pub fn new() -> Self {
        Self {
            state: MoveState::Idle,
            stamina: PLAYER_STAMINA_MAX,
            mana: PLAYER_MANA_MAX,
            dash_time_left: 0.0,
            dash_cooldown_left: 0.0,
            stun_time_left: 0.0,
            daze_time_left: 0.0,
            dash_velocity: Vec2::ZERO,
            knockback_velocity: Vec2::ZERO,
            ability_velocity: Vec2::ZERO,
            speed_multiplier: 1.0,
            prev_dash_held: false,
            prev_ability_held: false,
            base_speed: PLAYER_SPEED,
            ability_cost: PLAYER_MANA_ABILITY_COST,
            ability_cooldown_max: 0.0,
            charge_speed: 0.0,
            charge_max_distance: 0.0,
            ability_cooldown_left: 0.0,
            exhaust_time_left: 0.0,
            ability_fired: false,
            charge_just_ended: false,
            charge_velocity: Vec2::ZERO,
            charge_distance_left: 0.0,
        }
    }

    /// Configure per-class movement/ability tuning. Set once when the class+level is known
    /// (server on join/level-up; client on class load and on each PROGRESS event). Identical
    /// values on both sides keep prediction in lockstep. `charge_speed > 0` ⇒ the RMB ability is
    /// a Charge (Warrior); otherwise it is an instant cast handled server-side.
    pub fn set_ability_config(
        &mut self,
        cost: f64,
        cooldown: f64,
        charge_speed: f64,
        charge_max_distance: f64,
    ) {
        self.ability_cost = cost.max(0.0);
        self.ability_cooldown_max = cooldown.max(0.0);
        self.charge_speed = charge_speed.max(0.0);
        self.charge_max_distance = charge_max_distance.max(0.0);
    }

    /// Set the per-class+level base ground speed (replaces the global PLAYER_SPEED default).
    pub fn set_base_speed(&mut self, base_speed: f64) {
        self.base_speed = base_speed.max(0.0);
    }

    /// Advance one simulation step and return the velocity to integrate this step.
    /// `move_dir` must already be normalized (may be exactly ZERO); `aim_dir` is the normalized
    /// aim direction (dash target when standing still). Exact GDScript order:
    /// timers → stamina (using the PREVIOUS tick's state) → mana → edge detection →
    /// dash/ability/attack actions → dispatch on the (possibly just-changed) state.
    #[allow(clippy::too_many_arguments)]
    pub fn tick(
        &mut self,
        delta: f64,
        move_dir: Vec2,
        sprint_held: bool,
        dash_held: bool,
        ability_held: bool,
        attacking: bool,
        aim_dir: Vec2,
    ) -> Vec2 {
        self.ability_fired = false;
        self.charge_just_ended = false;
        self.update_timers(delta);
        self.update_stamina(delta);
        self.update_mana(delta);

        let dash_edge = dash_held && !self.prev_dash_held;
        let ability_edge = ability_held && !self.prev_ability_held;
        self.prev_dash_held = dash_held;
        self.prev_ability_held = ability_held;

        if dash_edge {
            self.try_dash(move_dir, aim_dir);
        }
        if ability_edge {
            self.try_activate_ability(move_dir, aim_dir);
        }
        if attacking && self.state == MoveState::Sprinting {
            self.end_sprint();
        }

        match self.state {
            MoveState::Idle | MoveState::Walking | MoveState::Sprinting => {
                self.tick_grounded(move_dir, sprint_held)
            }
            MoveState::Dashing => self.tick_dashing(),
            MoveState::KnockedBack => self.tick_knockback(delta),
            MoveState::Stunned => Vec2::ZERO,
            MoveState::AbilityMovement => self.ability_velocity,
            MoveState::Charging => self.tick_charging(delta, ability_held),
        }
    }

    /// RMB ability edge: gate on cooldown + mana, then either start a Charge (Warrior) or mark an
    /// instant cast (`ability_fired`) for the server to dispatch. A refused cast costs nothing.
    fn try_activate_ability(&mut self, move_dir: Vec2, aim_dir: Vec2) {
        if self.ability_cooldown_left > 0.0 {
            return;
        }
        // Charge needs a direction; refuse (and don't spend) if there's no aim/move direction.
        let is_charge = self.charge_speed > 0.0;
        let charge_dir = if move_dir != Vec2::ZERO {
            move_dir
        } else {
            aim_dir
        };
        if is_charge && charge_dir == Vec2::ZERO {
            return;
        }
        if !self.try_use_mana(self.ability_cost) {
            return;
        }
        self.ability_cooldown_left = self.ability_cooldown_max;
        if is_charge {
            self.start_charge(charge_dir);
        } else {
            self.ability_fired = true;
        }
    }

    fn start_charge(&mut self, dir: Vec2) {
        if matches!(self.state, MoveState::Stunned | MoveState::KnockedBack) {
            return;
        }
        let dir = dir.normalized();
        if dir == Vec2::ZERO {
            return;
        }
        self.charge_velocity = dir * (self.charge_speed as f32);
        self.charge_distance_left = self.charge_max_distance;
        self.transition_to(MoveState::Charging);
    }

    fn tick_charging(&mut self, delta: f64, ability_held: bool) -> Vec2 {
        // End NATURALLY on release or once the max distance is spent — flag the blast. (Enemy
        // contact ends it server-side via `end_charge`, which the server pairs with its own blast;
        // stun/teleport clear the charge without a blast.)
        if !ability_held || self.charge_distance_left <= 0.0 {
            self.charge_velocity = Vec2::ZERO;
            self.charge_distance_left = 0.0;
            self.charge_just_ended = true;
            self.transition_to(MoveState::Idle);
            return Vec2::ZERO;
        }
        self.charge_distance_left =
            (self.charge_distance_left - self.charge_velocity.length() as f64 * delta).max(0.0);
        self.charge_velocity
    }

    fn tick_grounded(&mut self, move_dir: Vec2, sprint_held: bool) -> Vec2 {
        if move_dir == Vec2::ZERO {
            self.transition_to(MoveState::Idle);
            return Vec2::ZERO;
        }
        // Sprint until stamina is fully gone; exhaustion (not a 5-stamina floor) is what stops it.
        let want_sprint =
            sprint_held && self.stamina > 0.0 && self.exhaust_time_left <= 0.0 && !self.is_dazed();
        if want_sprint {
            self.transition_to(MoveState::Sprinting);
        } else {
            self.transition_to(MoveState::Walking);
        }
        move_dir * (self.ground_speed(want_sprint) as f32)
    }

    fn tick_dashing(&mut self) -> Vec2 {
        if self.dash_time_left <= 0.0 {
            self.transition_to(MoveState::Idle); // grounded re-derives WALK/SPRINT next step
            return Vec2::ZERO;
        }
        self.dash_velocity
    }

    fn tick_knockback(&mut self, delta: f64) -> Vec2 {
        // Decay FIRST, then test, then move.
        self.knockback_velocity *= (-PLAYER_KNOCKBACK_DECAY * delta).exp() as f32;
        if self.knockback_velocity.length() as f64 <= PLAYER_KNOCKBACK_END_SPEED {
            self.transition_to(MoveState::Idle);
            return Vec2::ZERO;
        }
        self.knockback_velocity
    }

    fn update_timers(&mut self, delta: f64) {
        self.dash_time_left = (self.dash_time_left - delta).max(0.0);
        self.dash_cooldown_left = (self.dash_cooldown_left - delta).max(0.0);
        self.ability_cooldown_left = (self.ability_cooldown_left - delta).max(0.0);
        self.daze_time_left = (self.daze_time_left - delta).max(0.0);
        if self.state == MoveState::Stunned {
            self.stun_time_left = (self.stun_time_left - delta).max(0.0);
            if self.stun_time_left <= 0.0 {
                self.transition_to(MoveState::Idle);
            }
        }
    }

    fn update_stamina(&mut self, delta: f64) {
        // Uses LAST tick's state — runs before this tick's state re-derivation.
        if self.exhaust_time_left > 0.0 {
            // Exhausted: regen is paused for the lockout (the bar blinks client-side).
            self.exhaust_time_left = (self.exhaust_time_left - delta).max(0.0);
            return;
        }
        if self.state == MoveState::Sprinting {
            self.stamina = (self.stamina - PLAYER_STAMINA_DRAIN_PER_SEC * delta).max(0.0);
            if self.stamina <= 0.0 {
                self.exhaust_time_left = PLAYER_STAMINA_EXHAUST_DURATION;
            }
        } else {
            self.stamina =
                (self.stamina + PLAYER_STAMINA_REGEN_PER_SEC * delta).min(PLAYER_STAMINA_MAX);
        }
    }

    fn update_mana(&mut self, delta: f64) {
        if self.mana >= PLAYER_MANA_MAX {
            return;
        }
        self.mana = (self.mana + PLAYER_MANA_REGEN_PER_SEC * delta).min(PLAYER_MANA_MAX);
    }

    /// Guard table: STUNNED only releases to IDLE (via its own timer); KNOCKED_BACK rides out
    /// unless a stun or an ability interrupts it.
    fn can_transition(&self, to: MoveState) -> bool {
        if self.state == MoveState::Stunned && to != MoveState::Idle {
            return false;
        }
        if self.state == MoveState::KnockedBack
            && !matches!(
                to,
                MoveState::Idle | MoveState::Stunned | MoveState::AbilityMovement
            )
        {
            return false;
        }
        true
    }

    fn transition_to(&mut self, to: MoveState) {
        if self.state == to {
            return;
        }
        if !self.can_transition(to) {
            return;
        }
        self.state = to;
    }

    /// Instant dash on the dash edge. Direction = move direction, or aim direction when standing
    /// still. Refusal does NOT start the cooldown.
    pub fn try_dash(&mut self, move_dir: Vec2, aim_dir: Vec2) -> bool {
        if self.dash_cooldown_left > 0.0 {
            return false;
        }
        if self.is_dazed() {
            return false;
        }
        if matches!(
            self.state,
            MoveState::Stunned
                | MoveState::KnockedBack
                | MoveState::AbilityMovement
                | MoveState::Charging
        ) {
            return false;
        }
        let dir = if move_dir != Vec2::ZERO {
            move_dir
        } else {
            aim_dir
        };
        if dir == Vec2::ZERO {
            return false;
        }
        let dir = dir.normalized();
        self.dash_velocity = dir * ((PLAYER_DASH_SPEED * self.speed_multiplier) as f32);
        self.dash_time_left = PLAYER_DASH_DURATION;
        self.dash_cooldown_left = PLAYER_DASH_COOLDOWN; // cooldown starts NOW (start-relative)
        self.transition_to(MoveState::Dashing);
        true
    }

    /// Replaces (does not stack with) any in-flight knockback. Refused while STUNNED by the
    /// guard table. Server-only caller today; the client never predicts knockback.
    pub fn apply_knockback(&mut self, direction: Vec2, force: f64, multiplier: f64) {
        if direction == Vec2::ZERO || force <= 0.0 {
            return;
        }
        let dir = direction.normalized();
        self.knockback_velocity = dir * ((force * multiplier) as f32);
        self.transition_to(MoveState::KnockedBack);
    }

    pub fn end_sprint(&mut self) {
        if self.state != MoveState::Sprinting {
            return;
        }
        self.transition_to(MoveState::Walking);
    }

    /// Stun blocks movement for `duration` and cancels an in-progress dash or charge.
    pub fn apply_stun(&mut self, duration: f64) {
        if duration <= 0.0 {
            return;
        }
        self.stun_time_left = duration;
        self.dash_time_left = 0.0;
        self.charge_distance_left = 0.0;
        self.charge_velocity = Vec2::ZERO;
        self.transition_to(MoveState::Stunned);
    }

    /// Daze reduces control instead of blocking it: sprint and dash are refused while the
    /// timer runs; walking (and knockback/ability velocities) proceed normally. Not a state —
    /// it coexists with KNOCKED_BACK (the usual companion on a hit). Re-application extends,
    /// never shortens.
    pub fn apply_daze(&mut self, duration: f64) {
        if duration <= 0.0 {
            return;
        }
        self.daze_time_left = self.daze_time_left.max(duration);
        self.end_sprint();
    }

    /// Authoritative release (server → client via the DAZED entity flag clearing).
    pub fn clear_daze(&mut self) {
        self.daze_time_left = 0.0;
    }

    pub fn start_ability_movement(&mut self, initial_velocity: Vec2) {
        if self.state == MoveState::Stunned {
            return;
        }
        self.ability_velocity = initial_velocity;
        self.transition_to(MoveState::AbilityMovement);
    }

    pub fn set_ability_velocity(&mut self, velocity: Vec2) {
        self.ability_velocity = velocity;
    }

    pub fn end_ability_movement(&mut self) {
        if self.state != MoveState::AbilityMovement {
            return;
        }
        self.ability_velocity = Vec2::ZERO;
        self.transition_to(MoveState::Idle);
    }

    pub fn try_use_mana(&mut self, cost: f64) -> bool {
        if cost <= 0.0 {
            return true;
        }
        if self.mana < cost {
            return false;
        }
        self.mana = (self.mana - cost).max(0.0);
        true
    }

    pub fn apply_speed_modifier(&mut self, multiplier: f64) {
        self.speed_multiplier = multiplier.clamp(PLAYER_SPEED_MULT_MIN, PLAYER_SPEED_MULT_MAX);
    }

    pub fn clear_speed_modifier(&mut self) {
        self.speed_multiplier = 1.0;
    }

    /// Effective ground speed (walk or sprint) including the speed multiplier. Used by both live
    /// prediction and reconciliation replay so they agree.
    pub fn ground_speed(&self, is_sprinting: bool) -> f64 {
        let base = if is_sprinting {
            self.base_speed * PLAYER_SPRINT_MULTIPLIER
        } else {
            self.base_speed
        };
        base * self.speed_multiplier
    }

    /// Authoritatively set resources (server → owner correction via ActionConfirm). Assignment is
    /// epsilon-gated exactly like the GDScript (`is_equal_approx`).
    pub fn set_resources(&mut self, new_stamina: f64, new_mana: f64) {
        let clamped_stamina = new_stamina.clamp(0.0, PLAYER_STAMINA_MAX);
        let clamped_mana = new_mana.clamp(0.0, PLAYER_MANA_MAX);
        if !is_equal_approx_f64(clamped_stamina, self.stamina) {
            self.stamina = clamped_stamina;
        }
        if !is_equal_approx_f64(clamped_mana, self.mana) {
            self.mana = clamped_mana;
        }
    }

    /// End an in-progress Charge (release / max-distance / server-side enemy contact). Idempotent.
    pub fn end_charge(&mut self) {
        if self.state != MoveState::Charging {
            return;
        }
        self.charge_velocity = Vec2::ZERO;
        self.charge_distance_left = 0.0;
        self.transition_to(MoveState::Idle);
    }

    /// Force back to a clean grounded state, clearing dash/charge/ability velocities — used by the
    /// server when it teleports a player (Rogue shadowstep) so prediction re-derives next tick.
    pub fn interrupt_to_idle(&mut self) {
        self.dash_time_left = 0.0;
        self.charge_distance_left = 0.0;
        self.charge_velocity = Vec2::ZERO;
        self.ability_velocity = Vec2::ZERO;
        self.knockback_velocity = Vec2::ZERO;
        self.state = MoveState::Idle;
    }

    /// Reset to a clean alive state (spawn / respawn / death). Per-class config (base speed,
    /// ability cost/cooldown, charge tuning) is PRESERVED — it belongs to the character, not the
    /// life, so respawning must not silently revert to the global defaults.
    pub fn reset(&mut self) {
        let base_speed = self.base_speed;
        let ability_cost = self.ability_cost;
        let ability_cooldown_max = self.ability_cooldown_max;
        let charge_speed = self.charge_speed;
        let charge_max_distance = self.charge_max_distance;
        *self = Self::new();
        self.base_speed = base_speed;
        self.ability_cost = ability_cost;
        self.ability_cooldown_max = ability_cooldown_max;
        self.charge_speed = charge_speed;
        self.charge_max_distance = charge_max_distance;
    }

    // ── Queries ─────────────────────────────────────────────────────────────

    pub fn state(&self) -> MoveState {
        self.state
    }

    pub fn stamina(&self) -> f64 {
        self.stamina
    }

    pub fn mana(&self) -> f64 {
        self.mana
    }

    pub fn dash_cooldown_remaining(&self) -> f64 {
        self.dash_cooldown_left
    }

    pub fn dash_time_remaining(&self) -> f64 {
        self.dash_time_left
    }

    pub fn stun_remaining(&self) -> f64 {
        self.stun_time_left
    }

    pub fn is_dazed(&self) -> bool {
        self.daze_time_left > 0.0
    }

    pub fn daze_remaining(&self) -> f64 {
        self.daze_time_left
    }

    /// Sprint-exhaustion lockout active (sprint refused, stamina regen paused, bar blinks).
    pub fn is_exhausted(&self) -> bool {
        self.exhaust_time_left > 0.0
    }

    /// An INSTANT (non-charge) RMB ability cast + spent mana this tick. Server dispatches the
    /// effect; client plays cast VFX. Transient — only true on the tick of the cast.
    pub fn took_ability_this_tick(&self) -> bool {
        self.ability_fired
    }

    pub fn is_charging(&self) -> bool {
        self.state == MoveState::Charging
    }

    /// The charge ended naturally (release / max-distance) this tick — the server spawns the
    /// AOE blast. Transient: only true on the ending tick.
    pub fn charge_ended_this_tick(&self) -> bool {
        self.charge_just_ended
    }

    pub fn ability_cooldown_remaining(&self) -> f64 {
        self.ability_cooldown_left
    }

    pub fn is_input_locked(&self) -> bool {
        matches!(
            self.state,
            MoveState::Dashing
                | MoveState::KnockedBack
                | MoveState::Stunned
                | MoveState::AbilityMovement
                | MoveState::Charging
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f64 = 1.0 / 30.0;
    const RIGHT: Vec2 = Vec2::new(1.0, 0.0);

    fn idle_tick(sm: &mut MovementSm) -> Vec2 {
        sm.tick(DT, Vec2::ZERO, false, false, false, false, RIGHT)
    }

    #[test]
    fn dash_lasts_exactly_13_ticks() {
        // Float-residue off-by-one (extraction §4.11): 0.4 − 12×(1/30) leaves a positive f64
        // residue, so the dash returns 720 u/s for 13 ticks (edge tick + 12).
        let mut sm = MovementSm::new();
        let mut dash_ticks = 0;
        for tick in 0..30 {
            let dash_held = tick == 0;
            let v = sm.tick(DT, Vec2::ZERO, false, dash_held, false, false, RIGHT);
            if v.length() > 700.0 {
                dash_ticks += 1;
            }
        }
        assert_eq!(dash_ticks, 13);
    }

    #[test]
    fn dash_cooldown_start_relative() {
        let mut sm = MovementSm::new();
        assert!(
            sm.tick(DT, Vec2::ZERO, false, true, false, false, RIGHT)
                .length()
                > 700.0
        );
        // 5.5 s = 165 nominal decrements, but sequential f64 `max(0, x − 1/30)` leaves a positive
        // residue (same effect that makes the dash last 13 ticks), so the cooldown clears on the
        // 166th decrement after the dash tick.
        let mut ticks_to_clear = 0;
        while sm.dash_cooldown_remaining() > 0.0 {
            assert!(
                !sm.try_dash(RIGHT, Vec2::ZERO),
                "dash must be refused while cooling down"
            );
            idle_tick(&mut sm);
            ticks_to_clear += 1;
            assert!(ticks_to_clear < 200, "cooldown never cleared");
        }
        assert_eq!(ticks_to_clear, 166);
        assert!(sm.try_dash(RIGHT, Vec2::ZERO));
    }

    #[test]
    fn stationary_dash_uses_aim_and_refusal_skips_cooldown() {
        let mut sm = MovementSm::new();
        // Both zero ⇒ refused, cooldown NOT started.
        assert!(!sm.try_dash(Vec2::ZERO, Vec2::ZERO));
        assert_eq!(sm.dash_cooldown_remaining(), 0.0);
        // Aim fallback works.
        assert!(sm.try_dash(Vec2::ZERO, Vec2::new(0.0, -1.0)));
        assert_eq!(sm.state(), MoveState::Dashing);
    }

    #[test]
    fn knockback_moves_for_12_ticks() {
        let mut sm = MovementSm::new();
        sm.apply_knockback(RIGHT, PLAYER_KNOCKBACK_BASE_FORCE, 1.0);
        let mut moving_ticks = 0;
        for _ in 0..30 {
            let v = idle_tick(&mut sm);
            if v != Vec2::ZERO {
                moving_ticks += 1;
            }
        }
        assert_eq!(moving_ticks, 12); // 13th decayed tick falls to ≈9.11 ≤ 12 ⇒ ends
        assert_eq!(sm.state(), MoveState::Idle);
    }

    #[test]
    fn sprint_depletes_then_exhausts() {
        let mut sm = MovementSm::new();
        // Continuous sprint from full stamina until the first non-sprint tick: stamina drains to 0
        // (no 5-stamina floor anymore), which EXHAUSTS the player.
        let mut continuous = 0;
        loop {
            let v = sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
            if v.length() > 300.0 {
                continuous += 1;
                assert!(continuous < 120, "never exhausted");
            } else {
                break;
            }
        }
        assert!((80..=92).contains(&continuous), "continuous = {continuous}");
        assert!(sm.is_exhausted(), "depleting stamina must exhaust");
        assert!(sm.stamina() <= 0.01);
        // While exhausted: sprint refused (walk speed) and stamina does NOT regen.
        let v = sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
        assert!(v.length() < 300.0, "exhausted ⇒ no sprint");
        assert!(sm.stamina() <= 0.01, "no regen while exhausted");
        // After the 3 s lockout + recovery, stamina regenerates and sprint works again.
        for _ in 0..200 {
            sm.tick(DT, Vec2::ZERO, false, false, false, false, RIGHT);
        }
        assert!(!sm.is_exhausted());
        assert!(sm.stamina() > 50.0, "stamina = {}", sm.stamina());
        let v2 = sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
        assert!(v2.length() > 300.0, "sprint resumes after recovery");
    }

    #[test]
    fn attacking_while_sprinting_keeps_sprint_speed() {
        let mut sm = MovementSm::new();
        sm.tick(DT, RIGHT, true, false, false, false, RIGHT); // enter SPRINTING
        let v = sm.tick(DT, RIGHT, true, false, false, true, RIGHT); // attack
        assert!((v.length() - 320.0).abs() < 0.5, "speed = {}", v.length());
        assert_eq!(sm.state(), MoveState::Sprinting); // re-derived the same tick
    }

    #[test]
    fn stun_guard_table() {
        let mut sm = MovementSm::new();
        sm.apply_stun(0.5);
        assert_eq!(sm.state(), MoveState::Stunned);
        // Knockback refused while stunned.
        sm.apply_knockback(RIGHT, 450.0, 1.0);
        assert_eq!(sm.state(), MoveState::Stunned);
        // Movement input cannot leave STUNNED.
        let v = sm.tick(DT, RIGHT, false, false, false, false, RIGHT);
        assert_eq!(v, Vec2::ZERO);
        assert_eq!(sm.state(), MoveState::Stunned);
        // Timer release → IDLE.
        for _ in 0..20 {
            idle_tick(&mut sm);
        }
        assert_eq!(sm.state(), MoveState::Idle);
    }

    #[test]
    fn stun_cancels_dash() {
        let mut sm = MovementSm::new();
        assert!(sm.try_dash(RIGHT, Vec2::ZERO));
        sm.apply_stun(0.2);
        assert_eq!(sm.state(), MoveState::Stunned);
        assert_eq!(sm.dash_time_remaining(), 0.0);
    }

    #[test]
    fn knockback_interrupts_dash_and_rides_out() {
        let mut sm = MovementSm::new();
        assert!(sm.try_dash(RIGHT, Vec2::ZERO));
        sm.apply_knockback(Vec2::new(0.0, 1.0), 450.0, 1.0);
        assert_eq!(sm.state(), MoveState::KnockedBack);
        // Grounded transition refused while knocked back.
        sm.tick(DT, RIGHT, false, false, false, false, RIGHT);
        assert_eq!(sm.state(), MoveState::KnockedBack);
    }

    #[test]
    fn daze_blocks_sprint_and_dash_but_not_walking() {
        let mut sm = MovementSm::new();
        sm.tick(DT, RIGHT, true, false, false, false, RIGHT); // enter SPRINTING
        assert_eq!(sm.state(), MoveState::Sprinting);
        sm.apply_daze(0.5);
        assert_eq!(sm.state(), MoveState::Walking, "daze ends the sprint");
        // Sprint held but refused while dazed — walking speed only.
        let v = sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
        assert!((v.length() - 200.0).abs() < 0.5, "speed = {}", v.length());
        assert_eq!(sm.state(), MoveState::Walking);
        // Dash refused while dazed; refusal does not start the cooldown.
        assert!(!sm.try_dash(RIGHT, Vec2::ZERO));
        assert_eq!(sm.dash_cooldown_remaining(), 0.0);
        // Timer expires (0.5 s ≈ 15 ticks; 2 already spent) → sprint resumes.
        for _ in 0..15 {
            sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
        }
        assert!(!sm.is_dazed());
        let v = sm.tick(DT, RIGHT, true, false, false, false, RIGHT);
        assert!(v.length() > 300.0, "sprint must resume after daze");
    }

    #[test]
    fn daze_extends_never_shortens() {
        let mut sm = MovementSm::new();
        sm.apply_daze(1.0);
        sm.apply_daze(0.2);
        assert!((sm.daze_remaining() - 1.0).abs() < 1e-9);
        sm.clear_daze();
        assert!(!sm.is_dazed());
    }

    #[test]
    fn daze_coexists_with_knockback() {
        let mut sm = MovementSm::new();
        sm.apply_daze(1.0);
        sm.apply_knockback(RIGHT, PLAYER_KNOCKBACK_BASE_FORCE, 1.0);
        assert_eq!(sm.state(), MoveState::KnockedBack);
        assert!(sm.is_dazed());
    }

    #[test]
    fn ability_edge_spends_mana() {
        let mut sm = MovementSm::new();
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!((sm.mana() - 75.0).abs() < 0.1, "mana = {}", sm.mana());
        // Held (no edge) ⇒ no second spend.
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!(sm.mana() > 74.9);
    }

    #[test]
    fn set_resources_clamps() {
        let mut sm = MovementSm::new();
        sm.set_resources(-50.0, 500.0);
        assert_eq!(sm.stamina(), 0.0);
        assert_eq!(sm.mana(), 100.0);
    }

    #[test]
    fn determinism_bitwise() {
        let run = || {
            let mut sm = MovementSm::new();
            let mut acc: Vec<u32> = Vec::new();
            for i in 0..1000u32 {
                let dir = if i % 3 == 0 {
                    RIGHT
                } else {
                    Vec2::new(0.0, 1.0).normalized()
                };
                let v = sm.tick(
                    DT,
                    dir,
                    i % 5 != 0,
                    i % 97 == 0,
                    i % 31 == 0,
                    i % 7 == 0,
                    RIGHT,
                );
                acc.push(v.x.to_bits());
                acc.push(v.y.to_bits());
            }
            acc
        };
        assert_eq!(run(), run());
    }

    #[test]
    fn charge_starts_moves_and_ends_on_release() {
        let mut sm = MovementSm::new();
        sm.set_ability_config(40.0, 9.0, 720.0, 420.0);
        // Edge with ability held, aiming right, standing still ⇒ charge toward aim.
        let v = sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert_eq!(sm.state(), MoveState::Charging);
        assert!(sm.is_charging());
        assert!(
            (v.length() - 720.0).abs() < 0.5,
            "charge speed = {}",
            v.length()
        );
        // Mana spent, cooldown started, no instant-fire flag (the effect is the blast on end).
        assert!((sm.mana() - 60.0).abs() < 0.1, "mana = {}", sm.mana());
        assert!(sm.ability_cooldown_remaining() > 0.0);
        assert!(!sm.took_ability_this_tick());
        // Releasing RMB ends the charge.
        let v2 = sm.tick(DT, Vec2::ZERO, false, false, false, false, RIGHT);
        assert_eq!(v2, Vec2::ZERO);
        assert_eq!(sm.state(), MoveState::Idle);
    }

    #[test]
    fn charge_ends_at_max_distance() {
        let mut sm = MovementSm::new();
        // 720 u/s over 100 u ⇒ ~5 ticks even while RMB stays held.
        sm.set_ability_config(40.0, 9.0, 720.0, 100.0);
        let mut charging_ticks = 0;
        for _ in 0..30 {
            let v = sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
            if sm.is_charging() || v.length() > 700.0 {
                charging_ticks += 1;
            }
        }
        assert!(
            (4..=7).contains(&charging_ticks),
            "charging_ticks = {charging_ticks}"
        );
        assert_eq!(sm.state(), MoveState::Idle);
    }

    #[test]
    fn server_can_end_charge_on_contact() {
        let mut sm = MovementSm::new();
        sm.set_ability_config(40.0, 9.0, 720.0, 420.0);
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!(sm.is_charging());
        sm.end_charge(); // server: hit a monster
        assert_eq!(sm.state(), MoveState::Idle);
        assert!(!sm.is_charging());
    }

    #[test]
    fn per_class_base_speed_changes_walk_and_sprint_speed() {
        let mut sm = MovementSm::new();
        sm.set_base_speed(215.0); // Rogue
        let v = sm.tick(DT, RIGHT, false, false, false, false, RIGHT);
        assert!(
            (v.length() - 215.0).abs() < 0.5,
            "walk speed = {}",
            v.length()
        );
        assert!((sm.ground_speed(true) - 215.0 * PLAYER_SPRINT_MULTIPLIER).abs() < 1e-9);
    }

    #[test]
    fn base_speed_and_ability_config_survive_reset() {
        let mut sm = MovementSm::new();
        sm.set_base_speed(215.0);
        sm.set_ability_config(30.0, 10.0, 0.0, 0.0);
        sm.reset();
        assert!((sm.ground_speed(false) - 215.0).abs() < 1e-9);
        // Ability cost preserved: a cast spends 30, not the default 25.
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!((sm.mana() - 70.0).abs() < 0.1, "mana = {}", sm.mana());
    }

    #[test]
    fn instant_ability_sets_fired_flag_and_respects_cooldown() {
        let mut sm = MovementSm::new();
        sm.set_ability_config(30.0, 0.5, 0.0, 0.0); // instant, 0.5s cooldown
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!(sm.took_ability_this_tick());
        assert!((sm.mana() - 70.0).abs() < 0.1);
        assert!(sm.ability_cooldown_remaining() > 0.0);
        // Release, then re-press during the cooldown ⇒ refused (no fire, no second spend).
        sm.tick(DT, Vec2::ZERO, false, false, false, false, RIGHT);
        let mana_before = sm.mana();
        sm.tick(DT, Vec2::ZERO, false, false, true, false, RIGHT);
        assert!(!sm.took_ability_this_tick());
        assert!((sm.mana() - mana_before).abs() < 0.5);
    }

    #[test]
    fn charge_determinism_bitwise() {
        let run = || {
            let mut sm = MovementSm::new();
            sm.set_ability_config(40.0, 9.0, 720.0, 420.0);
            sm.set_base_speed(200.0);
            let mut acc: Vec<u32> = Vec::new();
            for i in 0..600u32 {
                let ability_held = (i % 120) < 20; // press + hold a charge periodically
                let dir = if i % 2 == 0 {
                    RIGHT
                } else {
                    Vec2::new(0.0, 1.0).normalized()
                };
                let v = sm.tick(DT, dir, false, false, ability_held, false, RIGHT);
                acc.push(v.x.to_bits());
                acc.push(v.y.to_bits());
            }
            acc
        };
        assert_eq!(run(), run());
    }
}
