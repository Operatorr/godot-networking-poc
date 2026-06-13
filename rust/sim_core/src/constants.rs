//! Every shared game constant, exact values from `game_constants.gd` (extraction §2).
//! Names follow the GDScript constants so cross-referencing stays mechanical.

use crate::vec2::Vec2;

// ── Network simulation ──────────────────────────────────────────────────────
pub const SERVER_TICK_RATE: f64 = 30.0;
pub const SERVER_TICK_INTERVAL: f64 = 1.0 / SERVER_TICK_RATE;
pub const REMOTE_ENTITY_RENDER_DELAY_TICKS: u32 = 2;
pub const MAX_PVE_PROJECTILE_COMPENSATION_TICKS: u32 = 6;
pub const MAX_PVP_PROJECTILE_COMPENSATION_TICKS: u32 = 4;

// ── Movement speeds ─────────────────────────────────────────────────────────
pub const PLAYER_SPEED: f64 = 200.0;
pub const PLAYER_SPRINT_MULTIPLIER: f64 = 1.6;
pub const PLAYER_SPRINT_SPEED: f64 = PLAYER_SPEED * PLAYER_SPRINT_MULTIPLIER;

// ── Dash ────────────────────────────────────────────────────────────────────
pub const PLAYER_DASH_MULTIPLIER: f64 = 3.6;
pub const PLAYER_DASH_SPEED: f64 = PLAYER_SPEED * PLAYER_DASH_MULTIPLIER;
pub const PLAYER_DASH_DURATION: f64 = 0.4;
/// START-relative: the clock begins when the dash begins (usable gap ≈ 5.1 s).
pub const PLAYER_DASH_COOLDOWN: f64 = 5.5;

// ── Knockback ───────────────────────────────────────────────────────────────
pub const PLAYER_KNOCKBACK_DECAY: f64 = 9.0;
pub const PLAYER_KNOCKBACK_END_SPEED: f64 = 12.0;
pub const PLAYER_KNOCKBACK_BASE_FORCE: f64 = 450.0;
/// Per-projectile knockback impulse (u/s). Carried on each ProjectileState so future
/// weapons/items/abilities can vary it per shot; the `apply_knockback` multiplier is the
/// buff/debuff hook on top.
pub const PLAYER_PROJECTILE_KNOCKBACK_FORCE: f64 = PLAYER_KNOCKBACK_BASE_FORCE;
pub const MONSTER_PROJECTILE_KNOCKBACK_FORCE: f64 = PLAYER_KNOCKBACK_BASE_FORCE;

// ── Daze ────────────────────────────────────────────────────────────────────
/// Hit while SPRINTING ⇒ dazed: sprint and dash are locked out for the duration;
/// walking stays allowed (reduced control, not a stun).
pub const PLAYER_DAZE_DURATION: f64 = 1.5;

// ── Stamina / mana ──────────────────────────────────────────────────────────
pub const PLAYER_STAMINA_MAX: f64 = 100.0;
pub const PLAYER_STAMINA_DRAIN_PER_SEC: f64 = 35.0;
pub const PLAYER_STAMINA_REGEN_PER_SEC: f64 = 20.0;
/// Legacy minimum-to-sprint threshold. The exhaustion model lets stamina deplete fully
/// instead (sprint allowed while `stamina > 0` and not exhausted), so this is retained only
/// for the simplified reconciliation replay gate.
pub const PLAYER_STAMINA_SPRINT_MIN: f64 = 5.0;
/// Sprinting to 0 stamina EXHAUSTS the player: sprint is locked out and stamina regen is
/// paused for this long (the HUD blinks the stamina bar during it).
pub const PLAYER_STAMINA_EXHAUST_DURATION: f64 = 3.0;
pub const PLAYER_MANA_MAX: f64 = 100.0;
/// Mana regen, nerfed 20% (was 10.0) to make the new RMB class abilities a real resource cost.
/// Mirrored in `client/scripts/shared/game_constants.gd` — both run the shared MovementSm, so
/// they MUST match or mana prediction desyncs.
pub const PLAYER_MANA_REGEN_PER_SEC: f64 = 8.0;
/// Default ability mana cost (the SM falls back to this until a class config is applied; the
/// real per-class costs live in the class data and are pushed in via `set_ability_config`).
pub const PLAYER_MANA_ABILITY_COST: f64 = 25.0;

// ── Status-effect speed modifier bounds ─────────────────────────────────────
pub const PLAYER_SPEED_MULT_MIN: f64 = 0.25;
pub const PLAYER_SPEED_MULT_MAX: f64 = 2.5;

// ── Movement validation thresholds (server) ─────────────────────────────────
/// Informational only — never branched on (extraction §5.17).
pub const POSITION_TOLERANCE: f32 = 75.0;
/// Deviation strictly above ⇒ correction packet.
pub const CORRECTION_THRESHOLD: f32 = 112.5;
/// Deviation strictly above ⇒ cheat flag + correction.
pub const TELEPORT_THRESHOLD: f32 = 150.0;

// ── Map bounds ──────────────────────────────────────────────────────────────
pub const MAP_MIN: Vec2 = Vec2::new(-1000.0, -1000.0);
pub const MAP_MAX: Vec2 = Vec2::new(1000.0, 1000.0);

// ── Projectiles ─────────────────────────────────────────────────────────────
pub const PROJECTILE_SPEED: f32 = 400.0;
pub const PROJECTILE_MAX_DISTANCE: f32 = 800.0;
pub const PROJECTILE_RADIUS: f32 = 8.0;
pub const PROJECTILE_ENTITY_ID_START: u16 = 10000;
pub const PROJECTILE_ENTITY_ID_END: u16 = 29999;
pub const PLAYER_HITBOX_RADIUS: f32 = 16.0;
/// PvP defender compensation factor (0 = favour shooter, 1 = test at live position).
pub const PVP_DEFENDER_FAVOR: f32 = 0.25;

// ── Combat ──────────────────────────────────────────────────────────────────
pub const SHOOT_COOLDOWN: f64 = 0.3;
pub const RESPAWN_DELAY: f64 = 3.0;
pub const INVULNERABILITY_DURATION: f64 = 3.0;

// ── Monsters ────────────────────────────────────────────────────────────────
pub const MONSTER_SPAWN_RATE: f64 = 0.2;
pub const MONSTER_MAX_COUNT: usize = 100;
pub const MONSTER_ENTITY_ID_START: u16 = 30000;
pub const MONSTER_ENTITY_ID_END: u16 = 39999;
pub const MONSTER_VISIBILITY_RADIUS: f32 = 300.0;
pub const MONSTER_SPAWN_MIN_DISTANCE: f32 = 320.0;
pub const MONSTER_SPAWN_MAX_DISTANCE: f32 = 450.0;
pub const MONSTER_REGIONAL_SPAWN_RATIO: f64 = 0.6;
pub const MONSTER_SPAWN_REGION_COLUMNS: usize = 4;
pub const MONSTER_SPAWN_REGION_ROWS: usize = 4;
pub const MONSTER_SPAWN_REGION_SOFT_CAP: usize = 2;
pub const MONSTER_SPAWN_REGION_CANDIDATES: usize = 8;
pub const MONSTER_SPAWN_ATTEMPTS: usize = 20;
pub const MONSTER_HEALTH: i32 = 50;
pub const MONSTER_HITBOX_RADIUS: f32 = 16.0;
pub const MONSTER_SPAWN_SEPARATION: f32 = MONSTER_HITBOX_RADIUS * 2.25;

// ── Monster AI ──────────────────────────────────────────────────────────────
pub const MONSTER_SPEED: f32 = 120.0;
pub const MONSTER_PROJECTILE_SPEED: f32 = 300.0;
pub const MONSTER_PROJECTILE_DAMAGE: i32 = 10;
pub const PLAYER_PROJECTILE_DAMAGE: i32 = 25;
pub const MONSTER_ATTACK_RANGE: f32 = 200.0;
pub const MONSTER_FLEE_DISTANCE: f32 = 100.0;
pub const MONSTER_PREFERRED_DISTANCE: f32 = 150.0;
pub const MONSTER_DETECTION_RANGE: f32 = 650.0;
pub const MONSTER_SHOOT_COOLDOWN: f64 = 0.75;
pub const MONSTER_ATTACK_DURATION: f64 = 0.5;
pub const MONSTER_AVOIDANCE_DISTANCE: f32 = 50.0;
pub const MONSTER_STEERING_RANDOMNESS: f64 = 0.15;
pub const MONSTER_RETARGET_INTERVAL: f64 = 1.0;
pub const MONSTER_LOSE_INTEREST_DISTANCE: f32 = 900.0;

// ── Experience / progression ────────────────────────────────────────────────
/// Every alive player within this distance of a dying monster shares its full XP
/// reward (a friend nearby can boost you — no split). See docs/systems/PROGRESSION.md.
pub const XP_SHARE_RADIUS: f32 = 500.0;

// ── Player entity ids ───────────────────────────────────────────────────────
pub const PLAYER_ENTITY_ID_MIN: u16 = 1;
pub const PLAYER_ENTITY_ID_MAX: u16 = 999;

// ── Server input plumbing ───────────────────────────────────────────────────
/// Flags cleared when `server_tick - last_input_received_tick > STALE_INPUT_TICK_LIMIT`.
pub const STALE_INPUT_TICK_LIMIT: u64 = 6;
pub const MAX_INPUT_QUEUE_SIZE: usize = 10;

/// Shared arena player spawn positions (world coordinates).
pub const ARENA_PLAYER_SPAWNS: [Vec2; 10] = [
    Vec2::new(-800.0, -800.0),
    Vec2::new(0.0, -800.0),
    Vec2::new(800.0, -800.0),
    Vec2::new(-800.0, 0.0),
    Vec2::new(800.0, 0.0),
    Vec2::new(-800.0, 800.0),
    Vec2::new(0.0, 800.0),
    Vec2::new(800.0, 800.0),
    Vec2::new(-450.0, 450.0),
    Vec2::new(450.0, -450.0),
];

/// Shared preferred monster spawn anchors (world coordinates).
pub const ARENA_MONSTER_SPAWNS: [Vec2; 12] = [
    Vec2::new(-450.0, -800.0),
    Vec2::new(450.0, -800.0),
    Vec2::new(-900.0, -450.0),
    Vec2::new(900.0, -450.0),
    Vec2::new(-900.0, 450.0),
    Vec2::new(900.0, 450.0),
    Vec2::new(-450.0, 800.0),
    Vec2::new(450.0, 800.0),
    Vec2::new(0.0, -500.0),
    Vec2::new(0.0, 500.0),
    Vec2::new(-500.0, 0.0),
    Vec2::new(500.0, 0.0),
];
