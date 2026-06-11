//! The shared per-step movement integration used identically by the authoritative server step
//! (`PlayerState.step`) and the client predictor (`_apply_local_prediction`), plus the
//! deliberately-simplified reconciliation replay model (extraction §4.7–4.9).

use crate::arena::move_with_obstacle_collision;
use crate::constants::{PLAYER_HITBOX_RADIUS, PLAYER_STAMINA_SPRINT_MIN};
use crate::movement::MovementSm;
use crate::vec2::Vec2;

/// Input-flag bits (mirror of `protocol::input_flags`; duplicated here so sim_core stays free of
/// the protocol dependency edge — the values are wire-frozen).
pub mod flags {
    pub const MOVE_UP: u16 = 1 << 0;
    pub const MOVE_DOWN: u16 = 1 << 1;
    pub const MOVE_LEFT: u16 = 1 << 2;
    pub const MOVE_RIGHT: u16 = 1 << 3;
    pub const SHOOT: u16 = 1 << 4;
    pub const ABILITY: u16 = 1 << 5;
    pub const SPRINT: u16 = 1 << 6;
    pub const INTERACT: u16 = 1 << 7;
    pub const DASH: u16 = 1 << 8;
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StepResult {
    pub position: Vec2,
    /// Realized velocity `(position_after − position_before) / dt` — reflects slides/clamps and
    /// feeds the MOVING flag, animation, and the input packet velocity field.
    pub velocity: Vec2,
}

/// WASD flags → normalized direction. Opposite keys cancel exactly; the zero vector normalizes
/// to zero; diagonals are not faster.
pub fn movement_direction(input_flags: u16) -> Vec2 {
    let mut d = Vec2::ZERO;
    if input_flags & flags::MOVE_UP != 0 {
        d.y -= 1.0;
    }
    if input_flags & flags::MOVE_DOWN != 0 {
        d.y += 1.0;
    }
    if input_flags & flags::MOVE_LEFT != 0 {
        d.x -= 1.0;
    }
    if input_flags & flags::MOVE_RIGHT != 0 {
        d.x += 1.0;
    }
    d.normalized()
}

/// One full movement step: SM tick → integrate → analytic mover → realized velocity.
/// `dash_held` is passed separately because the server ORs in its `_pending_dash` latch.
#[allow(clippy::too_many_arguments)]
pub fn step_movement(
    sm: &mut MovementSm,
    position: Vec2,
    delta: f64,
    move_dir: Vec2,
    sprint_held: bool,
    dash_held: bool,
    ability_held: bool,
    attacking: bool,
    aim_dir: Vec2,
) -> StepResult {
    let velocity = sm.tick(
        delta,
        move_dir,
        sprint_held,
        dash_held,
        ability_held,
        attacking,
        aim_dir,
    );
    let target = position + velocity * (delta as f32);
    let new_position = move_with_obstacle_collision(position, target, PLAYER_HITBOX_RADIUS);
    let realized = if delta > 0.0 {
        // Componentwise division like Godot's `Vector2 / float` (not multiply-by-reciprocal).
        (new_position - position) / (delta as f32)
    } else {
        velocity
    };
    StepResult {
        position: new_position,
        velocity: realized,
    }
}

/// Reconciliation replay — the deliberately-simplified ground-speed-only model (extraction
/// §4.9): sprint gated by the SM's CURRENT stamina and daze (not snapshot-time), never replays
/// dash/knockback/stun velocities. Does not mutate the SM.
pub fn replay_ground_step(
    sm: &MovementSm,
    position: Vec2,
    input_flags: u16,
    delta: f64,
) -> StepResult {
    let direction = movement_direction(input_flags);
    let sprint = input_flags & flags::SPRINT != 0
        && sm.stamina() > PLAYER_STAMINA_SPRINT_MIN
        && !sm.is_dazed();
    let velocity = direction * (sm.ground_speed(sprint) as f32);
    let target = position + velocity * (delta as f32);
    let new_position = move_with_obstacle_collision(position, target, PLAYER_HITBOX_RADIUS);
    let realized = if delta > 0.0 {
        (new_position - position) / (delta as f32)
    } else {
        velocity
    };
    StepResult {
        position: new_position,
        velocity: realized,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f64 = 1.0 / 30.0;

    #[test]
    fn opposite_keys_cancel() {
        assert_eq!(
            movement_direction(flags::MOVE_UP | flags::MOVE_DOWN),
            Vec2::ZERO
        );
    }

    #[test]
    fn diagonal_not_faster() {
        let d = movement_direction(flags::MOVE_UP | flags::MOVE_RIGHT);
        assert!((d.length() - 1.0).abs() < 1e-6);
    }

    #[test]
    fn walk_step_moves_at_player_speed() {
        let mut sm = MovementSm::new();
        let r = step_movement(
            &mut sm,
            Vec2::new(-800.0, -800.0),
            DT,
            movement_direction(flags::MOVE_RIGHT),
            false,
            false,
            false,
            false,
            Vec2::new(1.0, 0.0),
        );
        assert!((r.position.x - (-800.0 + 200.0 / 30.0)).abs() < 0.01);
        assert!((r.velocity.x - 200.0).abs() < 0.5);
    }

    #[test]
    fn realized_velocity_reflects_bounds_clamp() {
        let mut sm = MovementSm::new();
        // Walking right at the east edge: position clamps, realized velocity is zero.
        let r = step_movement(
            &mut sm,
            Vec2::new(1000.0, 0.0),
            DT,
            movement_direction(flags::MOVE_RIGHT),
            false,
            false,
            false,
            false,
            Vec2::new(1.0, 0.0),
        );
        assert_eq!(r.position, Vec2::new(1000.0, 0.0));
        assert_eq!(r.velocity, Vec2::ZERO);
    }

    #[test]
    fn replay_matches_walk_prediction_for_plain_movement() {
        // For plain WASD movement (no dash/sprint edge cases) the replay model and the full SM
        // produce identical positions.
        let mut sm = MovementSm::new();
        let start = Vec2::new(100.0, 100.0);
        let live = step_movement(
            &mut sm,
            start,
            DT,
            movement_direction(flags::MOVE_DOWN),
            false,
            false,
            false,
            false,
            Vec2::new(1.0, 0.0),
        );
        let sm2 = MovementSm::new();
        let replayed = replay_ground_step(&sm2, start, flags::MOVE_DOWN, DT);
        assert_eq!(live.position, replayed.position);
    }

    #[test]
    fn replay_never_dashes() {
        let sm = MovementSm::new();
        let r = replay_ground_step(&sm, Vec2::ZERO, flags::MOVE_RIGHT | flags::DASH, DT);
        // Ground speed only — 200 u/s, not 720.
        assert!((r.velocity.x - 200.0).abs() < 0.5);
    }
}
