//! Per-class stats and RMB-ability configuration — the server-side source of truth that mirrors
//! `client/data/classes/<id>.json` and `docs/classes/`. Base stats scale per level via
//! `sim_core::progression::scale_stat`; the ability config feeds both the shared `MovementSm`
//! (mana cost / cooldown / charge tuning, so prediction matches) and the server-only effect
//! dispatch in `world.rs`.

use sim_core::progression::scale_stat;

/// Which RMB effect a class has. Derived from `player_class`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AbilityKind {
    /// Zealot — 3 orbs orbit the caster, sweep-damaging monsters (world entities).
    SpinningBibles,
    /// Mage — instant AOE explosion at the cursor.
    Mageblast,
    /// Void Hunter — spread of piercing projectiles.
    Multishot,
    /// Engineer — drop a proximity Mine.
    Mine,
    /// Plague Seer — place a damage-over-time zone at the cursor.
    PlagueZone,
    /// Warrior — Charge (predicted movement + invuln) then an AOE blast.
    Charge,
    /// Rogue — Shadowstep to the nearest monster near the cursor, else Stealth.
    Shadowstep,
}

/// `ABILITY_EFFECT` effect ids (mirror `PacketTypes` on the client). Select the transient VFX.
pub mod effect {
    pub const MAGEBLAST: u8 = 0;
    pub const CHARGE_BLAST: u8 = 1;
    pub const MINE_DETONATION: u8 = 2;
    pub const SHADOWSTEP: u8 = 3;
}

/// Static per-class tuning. One ability per class, so the ability params live inline. All damage
/// numbers are pre-scaling bases; `*_per_level` are linear increments applied with `scale_stat`.
#[derive(Debug, Clone, Copy)]
pub struct ClassStats {
    pub kind: AbilityKind,
    // ── Base stats + per-level scaling ──
    pub base_hp: f64,
    pub hp_per_level: f64,
    pub base_speed: f64,
    pub speed_per_level: f64,
    pub base_damage: f64,
    pub damage_per_level: f64,
    /// Stamina regen (u/s) while not sprinting. Mage is deliberately lower than Warrior/Rogue.
    pub stamina_regen_per_sec: f64,
    // ── RMB ability ──
    pub ability_mana: f64,
    pub ability_cooldown: f64,
    /// Generic ability magnitude (per-hit / blast / hitscan / dps depending on kind).
    pub ability_damage: i32,
    /// Generic ability radius (blast / zone / orbit / search depending on kind).
    pub ability_radius: f32,
    /// Generic ability duration (bibles / dot-zone / stealth) or 0.
    pub ability_duration: f64,
    /// Max cast range for cursor-targeted abilities (Mageblast / Plague Zone), else 0.
    pub ability_cast_range: f32,
    /// Charge speed (Warrior) — `>0` marks the ability as a predicted Charge in the SM.
    pub charge_speed: f64,
    /// Charge max distance (Warrior).
    pub charge_distance: f64,
    /// Total mana a FULL charge drains over its distance (Warrior), beyond the activation cost.
    /// The charge ends early (blast) if mana runs out first. 0 for non-charge classes.
    pub charge_mana_drain: f64,
    /// Multishot projectile count (Void Hunter), else 0.
    pub multishot_count: u32,
    /// Multishot spread (radians, total cone) and pierce target cap.
    pub multishot_spread: f64,
    pub multishot_pierce: u8,
}

/// Index by `player_class` (0=Zealot … 6=Mage). Out-of-range clamps to Zealot.
pub fn stats_for_class(class: u8) -> &'static ClassStats {
    let idx = if class as usize >= CLASS_STATS.len() {
        0
    } else {
        class as usize
    };
    &CLASS_STATS[idx]
}

#[allow(dead_code)] // convenience accessor used in tests and by future call sites
pub fn ability_for_class(class: u8) -> AbilityKind {
    stats_for_class(class).kind
}

/// Effective (level-scaled) max HP for a class.
pub fn effective_max_health(class: u8, level: u16) -> i32 {
    let s = stats_for_class(class);
    scale_stat(s.base_hp, s.hp_per_level, level).round() as i32
}

/// Effective (level-scaled) base move speed for a class.
pub fn effective_base_speed(class: u8, level: u16) -> f64 {
    let s = stats_for_class(class);
    scale_stat(s.base_speed, s.speed_per_level, level)
}

/// Effective (level-scaled) primary-attack damage for a class.
pub fn effective_primary_damage(class: u8, level: u16) -> i32 {
    let s = stats_for_class(class);
    scale_stat(s.base_damage, s.damage_per_level, level).round() as i32
}

const ZEALOT: ClassStats = ClassStats {
    kind: AbilityKind::SpinningBibles,
    stamina_regen_per_sec: 20.0,
    base_hp: 120.0,
    hp_per_level: 8.0,
    base_speed: 195.0,
    speed_per_level: 0.5,
    base_damage: 22.0,
    damage_per_level: 2.0,
    ability_mana: 35.0,
    ability_cooldown: 8.0,
    ability_damage: 15,
    ability_radius: 80.0, // orbit radius
    ability_duration: 5.0,
    ability_cast_range: 0.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

const VOID_HUNTER: ClassStats = ClassStats {
    kind: AbilityKind::Multishot,
    stamina_regen_per_sec: 20.0,
    base_hp: 90.0,
    hp_per_level: 5.0,
    base_speed: 205.0,
    speed_per_level: 0.7,
    base_damage: 26.0,
    damage_per_level: 2.5,
    ability_mana: 30.0,
    ability_cooldown: 5.0,
    ability_damage: 18,
    ability_radius: 0.0,
    ability_duration: 0.0,
    ability_cast_range: 0.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 5,
    multishot_spread: 0.488_692, // 28° total cone
    multishot_pierce: 4,
};

const ENGINEER: ClassStats = ClassStats {
    kind: AbilityKind::Mine,
    stamina_regen_per_sec: 20.0,
    base_hp: 100.0,
    hp_per_level: 6.0,
    base_speed: 195.0,
    speed_per_level: 0.5,
    base_damage: 24.0,
    damage_per_level: 2.0,
    ability_mana: 35.0,
    ability_cooldown: 8.0,
    ability_damage: 60,
    ability_radius: 120.0,  // blast radius
    ability_duration: 30.0, // mine lifetime
    ability_cast_range: 0.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

const PLAGUE_SEER: ClassStats = ClassStats {
    kind: AbilityKind::PlagueZone,
    stamina_regen_per_sec: 20.0,
    base_hp: 95.0,
    hp_per_level: 5.0,
    base_speed: 195.0,
    speed_per_level: 0.5,
    base_damage: 20.0,
    damage_per_level: 2.0,
    ability_mana: 35.0,
    ability_cooldown: 7.0,
    ability_damage: 12, // dps
    ability_radius: 100.0,
    ability_duration: 5.0,
    ability_cast_range: 500.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

const WARRIOR: ClassStats = ClassStats {
    kind: AbilityKind::Charge,
    stamina_regen_per_sec: 20.0,
    base_hp: 130.0,
    hp_per_level: 9.0,
    base_speed: 200.0,
    speed_per_level: 0.6,
    base_damage: 25.0,
    damage_per_level: 2.5,
    ability_mana: 30.0, // activation cost (the charge then drains more per unit — see below)
    ability_cooldown: 4.5, // halved from 9.0
    ability_damage: 50, // blast damage
    ability_radius: 120.0,
    ability_duration: 0.0,
    ability_cast_range: 0.0,
    charge_speed: 720.0,
    charge_distance: 945.0, // steerable charge — follows the cursor; +50% range over the old 630
    // Mana drained over the DRAINING portion of a full charge (the first 40% is drain-free — the
    // activation always buys a minimum charge). ~40 total with the 30 activation cost.
    charge_mana_drain: 10.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

const ROGUE: ClassStats = ClassStats {
    kind: AbilityKind::Shadowstep,
    stamina_regen_per_sec: 20.0,
    base_hp: 85.0,
    hp_per_level: 4.0,
    base_speed: 215.0,
    speed_per_level: 0.9,
    base_damage: 24.0,
    damage_per_level: 2.0,
    ability_mana: 30.0,
    ability_cooldown: 10.0,
    ability_damage: 85,    // hitscan damage
    ability_radius: 160.0, // cursor search radius
    ability_duration: 5.0, // stealth duration
    ability_cast_range: 0.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

const MAGE: ClassStats = ClassStats {
    kind: AbilityKind::Mageblast,
    stamina_regen_per_sec: 14.0, // 30% below Warrior/Rogue — Mage relies on mana, not stamina
    base_hp: 80.0,
    hp_per_level: 4.0,
    base_speed: 195.0,
    speed_per_level: 0.5,
    base_damage: 28.0,
    damage_per_level: 3.0,
    ability_mana: 40.0,
    ability_cooldown: 6.0,
    ability_damage: 55,
    ability_radius: 144.0, // +20% blast radius
    ability_duration: 0.0,
    ability_cast_range: 600.0,
    charge_speed: 0.0,
    charge_distance: 0.0,
    charge_mana_drain: 0.0,
    multishot_count: 0,
    multishot_spread: 0.0,
    multishot_pierce: 0,
};

/// Order MUST match the class enum (0=Zealot … 6=Mage).
pub static CLASS_STATS: [ClassStats; 7] = [
    ZEALOT,
    VOID_HUNTER,
    ENGINEER,
    PLAGUE_SEER,
    WARRIOR,
    ROGUE,
    MAGE,
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn class_table_indices_match_enum() {
        assert_eq!(ability_for_class(0), AbilityKind::SpinningBibles);
        assert_eq!(ability_for_class(4), AbilityKind::Charge);
        assert_eq!(ability_for_class(6), AbilityKind::Mageblast);
        // Out-of-range clamps to Zealot.
        assert_eq!(ability_for_class(200), AbilityKind::SpinningBibles);
    }

    #[test]
    fn stats_scale_with_level() {
        // Warrior HP 130 +9/lvl.
        assert_eq!(effective_max_health(4, 1), 130);
        assert_eq!(effective_max_health(4, 2), 139);
        // Mage damage 28 +3/lvl.
        assert_eq!(effective_primary_damage(6, 1), 28);
        assert_eq!(effective_primary_damage(6, 11), 58);
        // Rogue speed 215 +0.9/lvl.
        assert!((effective_base_speed(5, 1) - 215.0).abs() < 1e-9);
        assert!((effective_base_speed(5, 11) - 224.0).abs() < 1e-9);
    }

    #[test]
    fn charge_only_for_warrior() {
        for c in 0..7u8 {
            let is_warrior = c == 4;
            assert_eq!(stats_for_class(c).charge_speed > 0.0, is_warrior);
        }
    }
}
