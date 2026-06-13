//! The arena geometry + the analytic mover — THE function the networked sim runs on
//! (extraction §4.1–4.5). No physics engine: pure rect math against 16 static obstacles and the
//! ±1000 bounds clamp. The ±1005 scene walls are visual scenery and play no role here.
//!
//! ## World-geometry "set once, single thread" contract
//!
//! The active [`WorldGeometry`] is a thread-local that the whole module reads. The sim is
//! single-threaded in production (the server's tick thread; the client's main/render thread), so
//! each such thread MUST call [`set_world_geometry`] exactly once before running any bounds /
//! obstacle / movement query. A thread that never sets it would silently fall back to the Arena
//! default — which on a Sanctuary instance would corrupt collision (Arena obstacles + ±1000
//! bounds instead of the wider walk-through town). To catch that, debug builds track whether the
//! geometry was set and `debug_assert!` it on every read; release builds keep the Arena default
//! (unchanged behavior) so a misconfigured deploy degrades rather than panics.

use crate::constants::{MAP_MAX, MAP_MIN, MONSTER_HITBOX_RADIUS, PLAYER_HITBOX_RADIUS};
use crate::rect::Rect;
use crate::vec2::Vec2;
use std::cell::Cell;

/// Per-instance world geometry (D13: one process = one Instance). The Arena uses the ±1000 bounds
/// with the 16 static obstacles; a Sanctuary instance uses the larger town bounds and NO obstacles
/// (walk-through). Both the authoritative server and the client predictor must agree, so it is set
/// ONCE (at server start / at client scene entry) and read by every bounds/obstacle function.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WorldGeometry {
    pub min: Vec2,
    pub max: Vec2,
    /// When false, the obstacle passes are skipped entirely (bounds-clamp only).
    pub obstacles_enabled: bool,
}

/// Default = the Arena (existing behavior, byte-identical).
pub const ARENA_GEOMETRY: WorldGeometry = WorldGeometry {
    min: MAP_MIN,
    max: MAP_MAX,
    obstacles_enabled: true,
};

thread_local! {
    // Thread-local (not a global): the sim runs single-threaded in production (the server tick
    // thread; the client's main/render thread), and per-test isolation comes for free since
    // libtest runs each test on its own thread that re-initializes to the Arena default.
    static WORLD: Cell<WorldGeometry> = const { Cell::new(ARENA_GEOMETRY) };

    // Debug-only: was `set_world_geometry` called on this thread? Reads `debug_assert!` it, to
    // catch a thread that silently inherited the Arena default (see the module-level contract).
    static WORLD_INITIALIZED: Cell<bool> = const { Cell::new(false) };
}

/// Set the active instance's world geometry. Call once before the sim runs.
pub fn set_world_geometry(min: Vec2, max: Vec2, obstacles_enabled: bool) {
    WORLD.with(|w| {
        w.set(WorldGeometry {
            min,
            max,
            obstacles_enabled,
        })
    });
    #[cfg(debug_assertions)]
    WORLD_INITIALIZED.with(|i| i.set(true));
}

/// Debug-only guard: in debug builds, assert the active thread set its geometry before reading it.
/// No-op in release (the Arena default stands, unchanged behavior).
#[inline]
fn debug_assert_world_initialized() {
    #[cfg(debug_assertions)]
    WORLD_INITIALIZED.with(|i| {
        debug_assert!(
            i.get(),
            "world_geometry() read before set_world_geometry() on this thread — the Arena default \
             would silently apply (wrong for a Sanctuary instance). Call set_world_geometry() once \
             at server start / client scene entry. See arena.rs module docs."
        );
    });
}

/// The active instance's world geometry.
pub fn world_geometry() -> WorldGeometry {
    debug_assert_world_initialized();
    WORLD.with(|w| w.get())
}

fn obstacles_active() -> bool {
    debug_assert_world_initialized();
    WORLD.with(|w| w.get().obstacles_enabled)
}

/// Obstacle definitions, world coordinates, exact values from `game_constants.gd:480-502`.
pub const OBSTACLES: [Rect; 16] = [
    // Center cross — creates 4 approach lanes
    Rect::new(-20.0, -200.0, 40.0, 160.0), // center north pillar
    Rect::new(-20.0, 40.0, 40.0, 160.0),   // center south pillar
    Rect::new(-200.0, -20.0, 160.0, 40.0), // center west pillar
    Rect::new(40.0, -20.0, 160.0, 40.0),   // center east pillar
    // Corner cover walls
    Rect::new(-700.0, -700.0, 150.0, 30.0), // NW horizontal
    Rect::new(-700.0, -700.0, 30.0, 150.0), // NW vertical
    Rect::new(550.0, -700.0, 150.0, 30.0),  // NE horizontal
    Rect::new(670.0, -700.0, 30.0, 150.0),  // NE vertical
    Rect::new(-700.0, 670.0, 150.0, 30.0),  // SW horizontal
    Rect::new(-700.0, 550.0, 30.0, 150.0),  // SW vertical
    Rect::new(550.0, 670.0, 150.0, 30.0),   // SE horizontal
    Rect::new(670.0, 550.0, 30.0, 150.0),   // SE vertical
    // Mid-field barriers — break up sight lines
    Rect::new(-450.0, -350.0, 100.0, 25.0), // NW mid barrier
    Rect::new(350.0, -350.0, 100.0, 25.0),  // NE mid barrier
    Rect::new(-450.0, 325.0, 100.0, 25.0),  // SW mid barrier
    Rect::new(350.0, 325.0, 100.0, 25.0),   // SE mid barrier
];

/// Clamp a position (the entity CENTER — the radius is deliberately not subtracted) to the map.
pub fn clamp_to_bounds(pos: Vec2) -> Vec2 {
    let g = world_geometry();
    Vec2::new(pos.x.clamp(g.min.x, g.max.x), pos.y.clamp(g.min.y, g.max.y))
}

pub fn is_within_bounds(pos: Vec2) -> bool {
    let g = world_geometry();
    pos.x >= g.min.x && pos.x <= g.max.x && pos.y >= g.min.y && pos.y <= g.max.y
}

pub fn is_circle_within_bounds(pos: Vec2, radius: f32) -> bool {
    let g = world_geometry();
    pos.x - radius >= g.min.x
        && pos.x + radius <= g.max.x
        && pos.y - radius >= g.min.y
        && pos.y + radius <= g.max.y
}

/// Point-in-any-obstacle (unexpanded). No obstacles in a Sanctuary instance.
pub fn is_point_in_obstacle(point: Vec2) -> bool {
    obstacles_active() && OBSTACLES.iter().any(|o| o.has_point(point))
}

/// Chebyshev (radius-expanded rect) circle test — NOT true circle-vs-AABB; corners are square.
/// Parity requires this exact shape (extraction §4.2). No obstacles in a Sanctuary instance.
pub fn circle_intersects_obstacle(center: Vec2, radius: f32) -> bool {
    obstacles_active()
        && OBSTACLES
            .iter()
            .any(|o| o.expanded(radius).has_point(center))
}

/// Slab-method segment-vs-rect intersection. Returns the first intersection point, or `None`.
/// Edges are INCLUSIVE here (unlike `has_point`) — the asymmetry is part of observed behavior
/// (extraction §4.3/§5.4). A `from` inside the rect returns `from` itself (t_min = 0 hit).
///
/// Scalar locals are f64 like GDScript's loose floats (component reads widen f32 → f64, the
/// t-quotients round once in f64); only the final `dir * t_min` narrows back to f32, exactly
/// where Godot's `Vector2 * float` does.
fn line_rect_intersection(from: Vec2, to: Vec2, rect: &Rect) -> Option<Vec2> {
    let dir = to - from;
    let mut t_min: f64 = 0.0;
    let mut t_max: f64 = 1.0;

    // X slab
    if (dir.x as f64).abs() < 0.0001 {
        if from.x < rect.position.x || from.x > rect.position.x + rect.size.x {
            return None;
        }
    } else {
        let mut t1 = (rect.position.x as f64 - from.x as f64) / dir.x as f64;
        let mut t2 = (rect.position.x as f64 + rect.size.x as f64 - from.x as f64) / dir.x as f64;
        if t1 > t2 {
            std::mem::swap(&mut t1, &mut t2);
        }
        t_min = t_min.max(t1);
        t_max = t_max.min(t2);
        if t_min > t_max {
            return None;
        }
    }

    // Y slab
    if (dir.y as f64).abs() < 0.0001 {
        if from.y < rect.position.y || from.y > rect.position.y + rect.size.y {
            return None;
        }
    } else {
        let mut t1 = (rect.position.y as f64 - from.y as f64) / dir.y as f64;
        let mut t2 = (rect.position.y as f64 + rect.size.y as f64 - from.y as f64) / dir.y as f64;
        if t1 > t2 {
            std::mem::swap(&mut t1, &mut t2);
        }
        t_min = t_min.max(t1);
        t_max = t_max.min(t2);
        if t_min > t_max {
            return None;
        }
    }

    if (0.0..=1.0).contains(&t_min) {
        Some(from + dir * t_min as f32)
    } else {
        None
    }
}

/// Does a swept circle move cross or end inside an obstacle?
fn movement_hits_obstacle(from: Vec2, to: Vec2, radius: f32) -> bool {
    if !obstacles_active() {
        return false;
    }
    if from.is_equal_approx(to) {
        return circle_intersects_obstacle(to, radius);
    }
    for obs in &OBSTACLES {
        let expanded = obs.expanded(radius);
        if expanded.has_point(to) {
            return true;
        }
        if line_rect_intersection(from, to, &expanded).is_some() {
            return true;
        }
    }
    false
}

/// THE mover (extraction §4.5). Clamps to bounds FIRST, then tries the direct move, then
/// axis-separated slides (strict `<` tie-break favours the X axis; one axis per step, no second
/// iteration; both blocked ⇒ no movement). No depenetration exists — a center inside an expanded
/// obstacle stays frozen, by (ported) design.
pub fn move_with_obstacle_collision(from: Vec2, to: Vec2, radius: f32) -> Vec2 {
    let target = clamp_to_bounds(to);
    if !movement_hits_obstacle(from, target, radius) {
        return target;
    }

    let x_target = clamp_to_bounds(Vec2::new(target.x, from.y));
    let y_target = clamp_to_bounds(Vec2::new(from.x, target.y));
    let mut best_position = from;
    let mut best_distance = from.distance_squared_to(target);

    if !movement_hits_obstacle(from, x_target, radius) {
        best_position = x_target;
        best_distance = best_position.distance_squared_to(target);
    }

    if !movement_hits_obstacle(from, y_target, radius) {
        let y_distance = y_target.distance_squared_to(target);
        if y_distance < best_distance {
            best_position = y_target;
        }
    }

    best_position
}

/// Closest point on segment [seg_start, seg_end] to `point` — shared by server swept collision
/// and the client incoming-projectile detector so both use identical math.
/// Scalars run in f64 (GDScript loose floats); `segment * t` narrows where Godot does.
pub fn closest_point_on_segment(point: Vec2, seg_start: Vec2, seg_end: Vec2) -> Vec2 {
    let segment = seg_end - seg_start;
    let length_sq = segment.length_squared() as f64;
    if length_sq <= 0.0001 {
        return seg_start;
    }
    let t = ((point - seg_start).dot(segment) as f64 / length_sq).clamp(0.0, 1.0);
    seg_start + segment * t as f32
}

/// First obstacle intersection of a (projectile) segment, or `None` — unexpanded rects.
/// No obstacles in a Sanctuary instance ⇒ projectiles only stop on bounds.
pub fn line_intersects_obstacle(from: Vec2, to: Vec2) -> Option<Vec2> {
    if !obstacles_active() {
        return None;
    }
    let mut closest: Option<Vec2> = None;
    let mut closest_dist = f32::INFINITY;
    for obs in &OBSTACLES {
        if let Some(p) = line_rect_intersection(from, to, obs) {
            let d = from.distance_squared_to(p);
            if d < closest_dist {
                closest = Some(p);
                closest_dist = d;
            }
        }
    }
    closest
}

pub fn is_valid_player_spawn_position(pos: Vec2) -> bool {
    is_circle_within_bounds(pos, PLAYER_HITBOX_RADIUS)
        && !circle_intersects_obstacle(pos, PLAYER_HITBOX_RADIUS)
}

pub fn is_valid_monster_spawn_position(pos: Vec2) -> bool {
    is_circle_within_bounds(pos, MONSTER_HITBOX_RADIUS)
        && !circle_intersects_obstacle(pos, MONSTER_HITBOX_RADIUS)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Explicitly honor the "set once before any read" contract on this test's thread (libtest
    /// gives each test its own thread, so this satisfies the debug-build initialized guard). The
    /// value equals the Arena default, so behavior is unchanged.
    fn init_arena() {
        set_world_geometry(
            ARENA_GEOMETRY.min,
            ARENA_GEOMETRY.max,
            ARENA_GEOMETRY.obstacles_enabled,
        );
    }

    #[test]
    fn clamp_center_to_1000() {
        init_arena();
        let p = clamp_to_bounds(Vec2::new(-2000.0, 1500.0));
        assert_eq!(p, Vec2::new(-1000.0, 1000.0));
    }

    #[test]
    fn free_move_returns_target() {
        init_arena();
        let r = move_with_obstacle_collision(
            Vec2::new(-800.0, -800.0),
            Vec2::new(-790.0, -800.0),
            16.0,
        );
        assert_eq!(r, Vec2::new(-790.0, -800.0));
    }

    #[test]
    fn diagonal_into_wall_slides_full_axis_component() {
        init_arena();
        // Center north pillar spans x −20..20, y −200..−40; expanded by 16: x −36..36, y −216..−24.
        // Approach from the left, moving right+down along the pillar's left face.
        let from = Vec2::new(-40.0, -150.0);
        let to = Vec2::new(-30.0, -140.0); // direct move ends inside expanded rect
        let r = move_with_obstacle_collision(from, to, 16.0);
        // X slide (−30, −150) is still inside expanded x range? −30 > −36 ⇒ blocked.
        // Y slide (−40, −140) is outside expanded x range ⇒ free.
        assert_eq!(r, Vec2::new(-40.0, -140.0));
    }

    #[test]
    fn blocked_both_axes_freezes() {
        init_arena();
        // Surrounded: heading straight into the expanded rect with both slides blocked.
        let from = Vec2::new(-37.0, -150.0); // 1 unit left of expanded edge (−36)
        let to = Vec2::new(-25.0, -150.0); // inside expanded rect
        let r = move_with_obstacle_collision(from, to, 16.0);
        // X slide = target (inside) ⇒ blocked; Y slide = from (zero move, not inside) ⇒ valid
        // but equal to `from`. distance check: y_target == from, dist(from,target) unchanged ⇒
        // y_distance == best_distance, strict < fails ⇒ stays `from`.
        assert_eq!(r, from);
    }

    #[test]
    fn expanded_upper_edge_exclusive() {
        init_arena();
        // Center exactly on the expanded max-x edge of the NE mid barrier:
        // barrier x 350..450 expanded by 16 ⇒ 334..466. has_point(466,…) must be false.
        assert!(!circle_intersects_obstacle(Vec2::new(466.0, -337.5), 16.0));
        // …whereas one ulp inside is a hit.
        assert!(circle_intersects_obstacle(Vec2::new(465.99, -337.5), 16.0));
    }

    #[test]
    fn swept_test_prevents_tunneling() {
        init_arena();
        // Mid barrier is 25 thick; a 200-unit step would pass clean over it without the sweep.
        let from = Vec2::new(-400.0, -450.0);
        let to = Vec2::new(-400.0, -250.0);
        let r = move_with_obstacle_collision(from, to, 16.0);
        assert_ne!(
            r, to,
            "swept test must block tunneling through the NW mid barrier"
        );
    }

    #[test]
    fn closest_point_degenerate_segment() {
        let p = closest_point_on_segment(
            Vec2::new(5.0, 5.0),
            Vec2::new(1.0, 1.0),
            Vec2::new(1.0, 1.0),
        );
        assert_eq!(p, Vec2::new(1.0, 1.0));
    }

    #[test]
    fn projectile_line_hits_unexpanded_rect() {
        init_arena();
        // Straight through the center north pillar.
        let hit = line_intersects_obstacle(Vec2::new(-100.0, -100.0), Vec2::new(100.0, -100.0));
        assert!(hit.is_some());
        let p = hit.unwrap();
        assert!(
            (p.x - (-20.0)).abs() < 0.001,
            "first hit on the left face, got {p:?}"
        );
    }

    #[test]
    fn all_player_spawns_valid() {
        init_arena();
        for s in crate::constants::ARENA_PLAYER_SPAWNS {
            assert!(is_valid_player_spawn_position(s), "spawn {s:?} invalid");
        }
    }

    #[test]
    fn inside_expanded_rect_freezes_forever() {
        init_arena();
        // No depenetration: starting inside, every move (including zero) reports a hit.
        let inside = Vec2::new(0.0, -100.0); // inside the center north pillar itself
        let r = move_with_obstacle_collision(inside, Vec2::new(0.0, -300.0), 16.0);
        assert_eq!(r, inside);
    }

    #[test]
    #[cfg(debug_assertions)]
    fn debug_guard_fires_when_geometry_unset() {
        // A fresh thread that never calls set_world_geometry must trip the debug guard on the
        // first geometry read. (Release builds skip this — the Arena default stands.)
        let joined = std::thread::spawn(|| {
            // Reading geometry without an init call: debug_assert must panic.
            let _ = world_geometry();
        })
        .join();
        assert!(
            joined.is_err(),
            "world_geometry() must debug_assert when read before set_world_geometry()"
        );
    }

    #[test]
    fn sanctuary_geometry_widens_bounds_and_drops_obstacles() {
        // Honor the set-once contract on this thread; the value equals the Arena default.
        init_arena();
        assert_eq!(world_geometry(), ARENA_GEOMETRY);
        // Sanctuary: ±1856 town bounds, no obstacles.
        set_world_geometry(
            Vec2::new(-1856.0, -1856.0),
            Vec2::new(1856.0, 1856.0),
            false,
        );
        // Bounds clamp at the wider extent (a position the Arena would have clamped to ±1000).
        assert_eq!(
            clamp_to_bounds(Vec2::new(-1500.0, 1500.0)),
            Vec2::new(-1500.0, 1500.0)
        );
        assert_eq!(
            clamp_to_bounds(Vec2::new(-3000.0, 0.0)),
            Vec2::new(-1856.0, 0.0)
        );
        // The center north pillar no longer blocks: a move straight through it succeeds.
        assert!(!circle_intersects_obstacle(Vec2::new(0.0, -100.0), 16.0));
        let r =
            move_with_obstacle_collision(Vec2::new(-100.0, -100.0), Vec2::new(100.0, -100.0), 16.0);
        assert_eq!(r, Vec2::new(100.0, -100.0), "no obstacles ⇒ free move");
        // Projectiles only stop on bounds (no obstacle hit).
        assert!(
            line_intersects_obstacle(Vec2::new(-100.0, -100.0), Vec2::new(100.0, -100.0)).is_none()
        );

        // Restore the Arena default and confirm the obstacle is back.
        set_world_geometry(ARENA_GEOMETRY.min, ARENA_GEOMETRY.max, true);
        assert!(circle_intersects_obstacle(Vec2::new(0.0, -100.0), 16.0));
        assert_eq!(
            clamp_to_bounds(Vec2::new(-1500.0, 0.0)),
            Vec2::new(-1000.0, 0.0)
        );
    }
}
