//! HitAuthority — pure, dependency-free predicates for the PvPvE hit-authority model, ported
//! verbatim from `hit_authority.gd`. Shared (via this crate) by the client incoming-hit detector,
//! the server report validator, and the server-authoritative skip checks, so the rules can only
//! drift in one place (migration-spec D11).

use crate::arena::closest_point_on_segment;
use crate::constants::MONSTER_ENTITY_ID_START;
use crate::vec2::Vec2;

/// A projectile is client-authoritative for the victim's dodge iff it is monster-owned.
/// Player-fired (PvP) projectiles stay server-authoritative.
pub fn is_client_authoritative(owner_id: u16) -> bool {
    owner_id >= MONSTER_ENTITY_ID_START
}

/// Client swept hit test: does the bullet's render-frame travel (prev → cur) pass within
/// `hit_radius` of the rendered self position? Strict `<`.
pub fn swept_hit(self_pos: Vec2, prev_pos: Vec2, cur_pos: Vec2, hit_radius: f32) -> bool {
    let closest = closest_point_on_segment(self_pos, prev_pos, cur_pos);
    self_pos.distance_to(closest) < hit_radius
}

/// Reconstruct a still-alive straight-flying bullet's spawn point from its current position,
/// unit direction, and distance traveled. Exact while the bullet has not been clamped by an
/// obstacle.
pub fn flight_origin(current_position: Vec2, direction: Vec2, distance_traveled: f32) -> Vec2 {
    current_position - direction * distance_traveled
}

/// Server plausibility test: does the bullet's straight-line flight pass within `threshold` of
/// ANY of the player's recent authoritative positions? Generous anti-grief bound — NOT a
/// pixel-accurate re-check.
pub fn is_hit_plausible(
    flight_start: Vec2,
    flight_end: Vec2,
    recent_positions: &[Vec2],
    threshold: f32,
) -> bool {
    recent_positions.iter().any(|pos| {
        let closest = closest_point_on_segment(*pos, flight_start, flight_end);
        pos.distance_to(closest) < threshold
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn authority_split_by_owner_range() {
        assert!(!is_client_authoritative(1)); // player-owned ⇒ server decides
        assert!(!is_client_authoritative(999));
        assert!(is_client_authoritative(30000)); // monster-owned ⇒ client decides own dodge
        assert!(is_client_authoritative(39999));
    }

    #[test]
    fn swept_hit_detects_pass_through() {
        // Bullet crosses directly over the player between frames.
        assert!(swept_hit(
            Vec2::new(0.0, 0.0),
            Vec2::new(-50.0, 0.0),
            Vec2::new(50.0, 0.0),
            16.0
        ));
        // Misses by more than the radius.
        assert!(!swept_hit(
            Vec2::new(0.0, 20.0),
            Vec2::new(-50.0, 0.0),
            Vec2::new(50.0, 0.0),
            16.0
        ));
    }

    #[test]
    fn swept_hit_strict_inequality() {
        assert!(!swept_hit(
            Vec2::new(0.0, 16.0),
            Vec2::new(-50.0, 0.0),
            Vec2::new(50.0, 0.0),
            16.0
        ));
    }

    #[test]
    fn flight_origin_reconstructs() {
        let origin = flight_origin(Vec2::new(100.0, 0.0), Vec2::new(1.0, 0.0), 60.0);
        assert_eq!(origin, Vec2::new(40.0, 0.0));
    }

    #[test]
    fn plausibility_over_recent_positions() {
        let recent = [Vec2::new(0.0, 100.0), Vec2::new(0.0, 30.0)];
        assert!(is_hit_plausible(
            Vec2::new(-100.0, 0.0),
            Vec2::new(100.0, 0.0),
            &recent,
            40.0
        ));
        assert!(!is_hit_plausible(
            Vec2::new(-100.0, 0.0),
            Vec2::new(100.0, 0.0),
            &recent[..1],
            40.0
        ));
        assert!(!is_hit_plausible(
            Vec2::new(-100.0, 0.0),
            Vec2::new(100.0, 0.0),
            &[],
            40.0
        ));
    }
}
