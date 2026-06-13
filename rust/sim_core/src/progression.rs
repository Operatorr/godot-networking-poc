//! Shared progression math — the level curve, Glory conversion, health-regen equation, and
//! per-level stat scaling. Lives in sim_core so the authoritative server and (for display) the
//! client compute identical numbers; the Go API ports the same curve for the death/sacrifice
//! Glory conversion. Ported from `game_manager.gd` (which used to OWN leveling client-side).
//!
//! See docs/systems/PROGRESSION.md and docs/classes/.

/// Max character level. Reaching it caps XP (the bar sits full). Was 99 client-side; the design
/// now tops out at 50, where health regen reaches its 5 hp/s ceiling.
pub const MAX_PLAYER_LEVEL: u16 = 50;

/// XP to go from level 1 → 2 (a deliberately-cheap first level).
pub const XP_FIRST_LEVEL: u32 = 100;
/// Slope for level L → L+1 (L ≥ 2): `XP_LEVEL_SLOPE * L` (≈ 10 same-level monster kills per level).
pub const XP_LEVEL_SLOPE: u32 = 200;

/// Glory = floor(total lifetime XP ÷ this). Tunable; 100 means a level-50 character converts to a
/// meaningful-but-bounded Glory sum. See [`glory_for`].
pub const GLORY_XP_DIVISOR: u32 = 100;

/// Health regen at level 1 (hp/s) — 1 hp every 5 seconds.
pub const HEALTH_REGEN_MIN_PER_SEC: f64 = 0.2;
/// Health regen at level [`MAX_PLAYER_LEVEL`] (hp/s) — 5 hp every second.
pub const HEALTH_REGEN_MAX_PER_SEC: f64 = 5.0;

/// XP required to advance FROM `level` to the next level. 0 at (or above) the cap.
pub fn xp_to_next_level(level: u16) -> u32 {
    if level >= MAX_PLAYER_LEVEL {
        0
    } else if level <= 1 {
        XP_FIRST_LEVEL
    } else {
        XP_LEVEL_SLOPE * level as u32
    }
}

/// Total lifetime XP a character at (`level`, `experience`) has earned — the sum of every prior
/// level's cost plus the current in-level progress. The basis for Glory conversion.
pub fn total_lifetime_xp(level: u16, experience: u32) -> u64 {
    let mut total = experience as u64;
    let mut l = 1u16;
    while l < level && l < MAX_PLAYER_LEVEL {
        total += xp_to_next_level(l) as u64;
        l += 1;
    }
    total
}

/// Glory awarded when a character at (`level`, `experience`) dies (hardcore) or is sacrificed
/// (softcore): `floor(total_lifetime_xp / GLORY_XP_DIVISOR)`.
pub fn glory_for(level: u16, experience: u32) -> u64 {
    total_lifetime_xp(level, experience) / GLORY_XP_DIVISOR as u64
}

/// Apply `experience` to a character at `level`, resolving any level-ups via the curve. Returns
/// `(new_level, new_experience)`. XP at the cap is discarded (bar sits full). Mirrors the old
/// client `grant_experience` loop exactly.
pub fn apply_experience(level: u16, experience: u32, gained: u32) -> (u16, u32) {
    let mut level = level.clamp(1, MAX_PLAYER_LEVEL);
    let mut experience = experience as u64 + gained as u64;
    while level < MAX_PLAYER_LEVEL {
        let need = xp_to_next_level(level) as u64;
        if need == 0 || experience < need {
            break;
        }
        experience -= need;
        level += 1;
    }
    if level >= MAX_PLAYER_LEVEL {
        experience = 0;
    }
    (level, experience.min(u32::MAX as u64) as u32)
}

/// Health regenerated per second at `level` — a smooth lerp from 0.2 hp/s (L1) to 5.0 hp/s (L50).
pub fn health_regen_per_sec(level: u16) -> f64 {
    let level = level.clamp(1, MAX_PLAYER_LEVEL);
    let t = (level - 1) as f64 / (MAX_PLAYER_LEVEL - 1) as f64;
    HEALTH_REGEN_MIN_PER_SEC + t * (HEALTH_REGEN_MAX_PER_SEC - HEALTH_REGEN_MIN_PER_SEC)
}

/// Linear per-level stat scaling: `base + per_level * (level - 1)`. Used for HP, move speed,
/// primary damage, etc. so a class's stats grow exactly as documented in the class data.
pub fn scale_stat(base: f64, per_level: f64, level: u16) -> f64 {
    base + per_level * (level.clamp(1, MAX_PLAYER_LEVEL) - 1) as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn curve_matches_legacy_client() {
        assert_eq!(xp_to_next_level(1), 100);
        assert_eq!(xp_to_next_level(2), 400);
        assert_eq!(xp_to_next_level(10), 2000);
        assert_eq!(xp_to_next_level(MAX_PLAYER_LEVEL), 0);
    }

    #[test]
    fn level_ups_resolve() {
        // 100 XP at level 1 → exactly level 2, 0 progress.
        assert_eq!(apply_experience(1, 0, 100), (2, 0));
        // 99 XP at level 1 → still level 1.
        assert_eq!(apply_experience(1, 0, 99), (1, 99));
        // Overshoot carries into the next level.
        assert_eq!(apply_experience(1, 0, 150), (2, 50));
    }

    #[test]
    fn cap_discards_overflow() {
        let (lvl, xp) = apply_experience(MAX_PLAYER_LEVEL, 0, 100_000);
        assert_eq!(lvl, MAX_PLAYER_LEVEL);
        assert_eq!(xp, 0);
    }

    #[test]
    fn glory_is_floor_of_total_over_divisor() {
        // Level 2 with 0 progress = 100 lifetime XP = 1 Glory.
        assert_eq!(total_lifetime_xp(2, 0), 100);
        assert_eq!(glory_for(2, 0), 1);
        // Level 3 = 100 + 400 = 500 lifetime XP = 5 Glory.
        assert_eq!(total_lifetime_xp(3, 0), 500);
        assert_eq!(glory_for(3, 0), 5);
    }

    #[test]
    fn health_regen_hits_endpoints() {
        assert!((health_regen_per_sec(1) - 0.2).abs() < 1e-9);
        assert!((health_regen_per_sec(MAX_PLAYER_LEVEL) - 5.0).abs() < 1e-9);
        // Monotonic, mid-range between endpoints.
        let mid = health_regen_per_sec(25);
        assert!(mid > 0.2 && mid < 5.0);
    }

    #[test]
    fn scale_stat_linear() {
        assert_eq!(scale_stat(100.0, 8.0, 1), 100.0);
        assert_eq!(scale_stat(100.0, 8.0, 2), 108.0);
        assert_eq!(scale_stat(100.0, 8.0, 50), 100.0 + 8.0 * 49.0);
    }
}
