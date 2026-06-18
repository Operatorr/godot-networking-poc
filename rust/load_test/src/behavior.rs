//! Bot behavior modes, ported from the Python harness (`load_testing/bot_client.py`, retired with
//! the WebSocket server). The five load behaviors (default/idle/movement/combat/clustered) keep
//! the original constants and probabilities. `strategy` is a **simplified** gameplay AI — target
//! selection, orbit-at-range, intercept aim with difficulty-scaled error, projectile dodging, and
//! dash usage are ported; the old A* waypoint hunt and flanking planner are not (the full version
//! lives in git history before the Rust port).

use crate::rng::Pcg32;
use protocol::types::{
    entity_flags, input_flags, world_effect, world_effect_subtype_for_id, MONSTER_ID_END,
    MONSTER_ID_START, PLAYER_ID_MAX,
};
use std::collections::HashMap;

/// Last-known wire state of one replicated entity, maintained by the bot from snapshots.
/// Velocity is estimated from successive position records (network-visible state only).
#[derive(Debug, Clone, Copy)]
pub struct KnownEntity {
    pub pos: (f32, f32),
    pub vel: (f32, f32),
    pub anim: u8,
    pub flags: u16,
    pub last_tick: u32,
}

/// What the behavior sees: the bot's own predicted state plus the replicated world.
pub struct View<'a> {
    pub my_id: u16,
    pub pos: (f32, f32),
    pub stamina: f64,
    /// Own HP as a fraction of max (1.0 = full). Drives the defensive orb-seek; the bot's only HP
    /// source is `ActionConfirm.health`, so this is `health / max_health_seen`.
    pub hp_fraction: f64,
    pub entities: &'a HashMap<u16, KnownEntity>,
    /// projectile id -> owner entity id, learned from PROJECTILE_FIRED events.
    pub projectile_owners: &'a HashMap<u16, u16>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BehaviorKind {
    Default,
    Idle,
    Movement,
    Combat,
    Clustered,
    Strategy,
}

impl BehaviorKind {
    pub fn parse(s: &str) -> Option<Self> {
        match s {
            "default" => Some(Self::Default),
            "idle" => Some(Self::Idle),
            "movement" => Some(Self::Movement),
            "combat" => Some(Self::Combat),
            "clustered" => Some(Self::Clustered),
            "strategy" => Some(Self::Strategy),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Default => "default",
            Self::Idle => "idle",
            Self::Movement => "movement",
            Self::Combat => "combat",
            Self::Clustered => "clustered",
            Self::Strategy => "strategy",
        }
    }
}

pub const VALID_BEHAVIORS: &[&str] = &[
    "default",
    "idle",
    "movement",
    "combat",
    "clustered",
    "strategy",
];

/// Player class ids that have a usable RMB ability. The load swarm only spawns these three
/// (see `bot.rs`), so the strategy AI only needs to know about them. Warrior charges; Rogue and
/// Mage cast an instant cursor-targeted ability.
pub const CLASS_WARRIOR: u8 = 4;
#[allow(dead_code)]
pub const CLASS_ROGUE: u8 = 5;
#[allow(dead_code)]
pub const CLASS_MAGE: u8 = 6;

/// One input frame's worth of intent: full `input_flags` (movement + SHOOT/SPRINT/DASH/ABILITY) +
/// aim, plus the cursor world position for cursor-targeted ability casts (`None` ⇒ the bot's own
/// position, the harmless default for non-casting frames).
#[derive(Debug, Clone, Copy)]
pub struct Decision {
    pub flags: u16,
    pub aim_angle: f32,
    pub cursor: Option<(f32, f32)>,
}

impl Decision {
    const IDLE: Decision = Decision {
        flags: 0,
        aim_angle: 0.0,
        cursor: None,
    };
}

// Direction options for the wander behaviors (4 cardinals, 2 diagonals, idle) — same set as
// the Python `_pick_direction`.
const WANDER_DIRS: [u16; 7] = [
    input_flags::MOVE_UP,
    input_flags::MOVE_DOWN,
    input_flags::MOVE_LEFT,
    input_flags::MOVE_RIGHT,
    input_flags::MOVE_UP | input_flags::MOVE_RIGHT,
    input_flags::MOVE_DOWN | input_flags::MOVE_LEFT,
    0,
];
const COMBAT_DIRS: [u16; 5] = [
    input_flags::MOVE_UP,
    input_flags::MOVE_DOWN,
    input_flags::MOVE_LEFT,
    input_flags::MOVE_RIGHT,
    0,
];

// Strategy constants (ported values).
const SPRINT_STAMINA_FLOOR: f64 = 25.0;
const DASH_COOLDOWN_S: f64 = 5.5;
// Conservative self-throttle for RMB ability casts (Warrior Charge / Rogue Shadowstep). Longer
// than DASH so the swarm exercises abilities without spamming; the real cooldown + mana gate lives
// in `sim_core` / the server, where a refused cast costs nothing, so this only needs to be lenient.
const ABILITY_COOLDOWN_S: f64 = 6.0;
// Warrior Charge stats — mirror of the server's CLASS_STATS / warrior.json. The load-test crate
// links `sim_core` + `protocol` but NOT the server crate (where the per-class table lives), so these
// are duplicated here; keep them in lockstep with warrior.json (`ability.charge_speed`/`max_distance`).
const WARRIOR_CHARGE_SPEED: f64 = 720.0; // units/s
const WARRIOR_CHARGE_DISTANCE: f64 = 945.0; // units
const CHARGE_HOLD_MARGIN_S: f64 = 0.04; // small cushion over the exact travel time

// Hold the Warrior's ABILITY for the full charge travel time (distance / speed) plus a cushion so
// the steerable charge runs its course. Releasing immediately — as the old edge-triggered cast did —
// ended the charge after a single tick (the "charges ~1 unit" bug). The server ends the charge sooner
// on enemy contact / max distance, so erring long is harmless.
const CHARGE_HOLD_S: f64 = WARRIOR_CHARGE_DISTANCE / WARRIOR_CHARGE_SPEED + CHARGE_HOLD_MARGIN_S; // ≈1.35 s
const TARGET_MAX_RANGE: f32 = 1250.0; // 1.25 × AoI radius
const PROJECTILE_SPEED: f32 = 400.0;
const DODGE_RADIUS: f32 = 220.0;
// Defensive orb-seek: a bot below this HP fraction detours to the nearest Healthorb within
// ORB_SEEK_RADIUS while it keeps fighting (aim + SHOOT stay on the engaged target, dodge still
// overrides movement). Healthorbs are world-effect entities (id band 40000–42499) that already
// arrive in the AoI entity map, so this only reads state the bot already has.
const ORB_SEEK_HP_FRACTION: f64 = 0.60;
const ORB_SEEK_RADIUS: f32 = 800.0;
// A monster shot inside this radius and still closing is treated as a near-certain hit: the bot
// stops SPRINTING so the hit lands while WALKING. A sprint-hit Daze (sprint/dash lock + 30% slow
// for 1.5 s) is worse than the hit, so a real player would brake — this mirrors that.
const IMMINENT_HIT_RADIUS: f32 = 100.0;
// Python thresholded a normalized axis to ±1 above 35/speed (= 35/200).
const AXIS_THRESHOLD: f32 = 0.175;

pub struct BehaviorState {
    pub kind: BehaviorKind,
    difficulty: f64,
    /// The bot's class — decides how the RMB ability is exercised (Warrior charge vs instant cast).
    player_class: u8,
    dir_flags: u16,
    cached: Decision,
    next_decision_at: f64,
    last_dash_at: f64,
    last_ability_at: f64,
    /// While `now < this`, the Warrior keeps the ABILITY flag HELD so the steerable charge runs to
    /// completion (the server ends it on contact / max distance / release). `NEG_INFINITY` = not charging.
    ability_hold_until: f64,
    target: Option<u16>,
}

impl BehaviorState {
    pub fn new(kind: BehaviorKind, difficulty: f64, player_class: u8) -> Self {
        Self {
            kind,
            difficulty: difficulty.clamp(0.0, 1.0),
            player_class,
            dir_flags: 0,
            cached: Decision::IDLE,
            next_decision_at: 0.0,
            last_dash_at: f64::NEG_INFINITY,
            last_ability_at: f64::NEG_INFINITY,
            ability_hold_until: f64::NEG_INFINITY,
            target: None,
        }
    }

    pub fn decide(&mut self, view: &View, rng: &mut Pcg32, now: f64) -> Decision {
        match self.kind {
            BehaviorKind::Idle => Decision::IDLE,
            BehaviorKind::Default => self.wander(rng, 0.10, 0.20, &WANDER_DIRS),
            BehaviorKind::Movement => self.wander(rng, 0.10, 0.0, &WANDER_DIRS),
            BehaviorKind::Combat => self.wander(rng, 0.15, 1.0, &COMBAT_DIRS),
            BehaviorKind::Clustered => self.clustered(view, rng),
            BehaviorKind::Strategy => self.strategy(view, rng, now),
        }
    }

    /// default/movement/combat: occasionally re-roll a persistent direction, shoot by chance,
    /// aim uniformly at random.
    fn wander(&mut self, rng: &mut Pcg32, repick: f64, shoot_p: f64, dirs: &[u16]) -> Decision {
        if rng.randf() < repick {
            self.dir_flags = dirs[rng.rand_index(dirs.len())];
        }
        let mut flags = self.dir_flags;
        if shoot_p >= 1.0 || (shoot_p > 0.0 && rng.randf() < shoot_p) {
            flags |= input_flags::SHOOT;
        }
        Decision {
            flags,
            aim_angle: rng.randf_range(-std::f64::consts::PI, std::f64::consts::PI) as f32,
            cursor: None,
        }
    }

    /// clustered: converge on the arena origin (AoI worst case), stop within 5 u, shoot 30%.
    fn clustered(&mut self, view: &View, rng: &mut Pcg32) -> Decision {
        let (dx, dy) = (-view.pos.0, -view.pos.1);
        let dist = (dx * dx + dy * dy).sqrt();
        let mut flags = if dist < 5.0 {
            0
        } else {
            flags_from_dir(dx, dy, 0.25)
        };
        if rng.randf() < 0.30 {
            flags |= input_flags::SHOOT;
        }
        Decision {
            flags,
            aim_angle: rng.randf_range(-std::f64::consts::PI, std::f64::consts::PI) as f32,
            cursor: None,
        }
    }

    fn strategy(&mut self, view: &View, rng: &mut Pcg32, now: f64) -> Decision {
        let mut decision = self.strategy_movement(view, rng, now);
        // The RMB ability is handled OUTSIDE the reaction cache so the Warrior charge can be held
        // for several ticks (see `apply_ability`); otherwise the cached-decision replays would drop
        // the ABILITY flag and cut the charge short.
        self.apply_ability(&mut decision, view, rng, now);
        decision
    }

    /// Movement + primary fire + dodge/sprint/dash. The reaction cache lives here; the RMB ability
    /// is layered on top by `apply_ability` every frame.
    fn strategy_movement(&mut self, view: &View, rng: &mut Pcg32, now: f64) -> Decision {
        // Reaction-time cache: expert (1.0) re-decides every 40 ms, novice (0.0) every 500 ms.
        // DASH is edge-triggered, so it is stripped from the cache after the first replay.
        if now < self.next_decision_at {
            let out = self.cached;
            self.cached.flags &= !input_flags::DASH;
            return out;
        }
        let d = self.difficulty;
        self.next_decision_at = now + 0.04 + (1.0 - d) * 0.46;

        let target = self.pick_target(view);
        self.target = target;
        let mut decision = match target.and_then(|id| view.entities.get(&id).map(|e| (id, *e))) {
            None => self.wander(rng, 0.10, 0.0, &WANDER_DIRS),
            Some((id, t)) => self.engage(view, rng, now, id, t),
        };

        // Defensive orb-seek overlay: when hurt below the HP floor and a Healthorb is within reach,
        // steer toward the nearest orb while KEEPING the engage aim + SHOOT — the bot chases the
        // heal and keeps firing at its target (or moves to the orb regardless when it has no
        // target). Movement only; the dodge overlay below still wins when a shot is incoming, so
        // the bot grabs the orb *while* dodging. Purely geometric (no RNG) — draw order unchanged.
        if view.hp_fraction < ORB_SEEK_HP_FRACTION {
            if let Some((ox, oy)) = nearest_healthorb(view) {
                let (dx, dy) = (ox - view.pos.0, oy - view.pos.1);
                decision.flags =
                    (decision.flags & !MOVE_MASK) | flags_from_dir(dx, dy, AXIS_THRESHOLD);
            }
        }

        // Projectile dodge overlay: steer perpendicular to the closest incoming shot — from a
        // monster, an enemy player, or another bot (anything not our own). Also flag a near-certain
        // *imminent* hit (very close + still closing) so the sprint gate can drop SPRINT — a hit
        // taken WALKING does not Daze, one taken SPRINTING does.
        let mut dodging = false;
        let mut imminent_hit = false;
        if let Some((px, py, pvx, pvy)) = nearest_incoming_projectile(view) {
            let (rx, ry) = (view.pos.0 - px, view.pos.1 - py);
            let dist2 = rx * rx + ry * ry;
            if dist2 < DODGE_RADIUS * DODGE_RADIUS {
                dodging = true;
                let speed = (pvx * pvx + pvy * pvy).sqrt();
                let (fx, fy) = if speed > 1.0 {
                    (pvx / speed, pvy / speed)
                } else {
                    let len = dist2.sqrt().max(1.0);
                    (-rx / len, -ry / len)
                };
                // Perpendicular, picking the side that moves away from the shot's path.
                let (perp_x, perp_y) = if rx * -fy + ry * fx >= 0.0 {
                    (-fy, fx)
                } else {
                    (fy, -fx)
                };
                decision.flags =
                    (decision.flags & !MOVE_MASK) | flags_from_dir(perp_x, perp_y, AXIS_THRESHOLD);
            }
            // Inside the imminent radius and still closing (the shot's velocity points toward the
            // bot, `v · (bot − shot) > 0`): an unavoidable hit, so brake out of the sprint.
            if dist2 < IMMINENT_HIT_RADIUS * IMMINENT_HIT_RADIUS && pvx * rx + pvy * ry > 0.0 {
                imminent_hit = true;
            }
        }

        // Sprint while repositioning or dodging, gated on the stamina meter like a human would —
        // but NEVER into a near-certain hit: braking avoids the sprint-hit Daze, which costs more
        // than the hit. (Daze keys off the SPRINTING state at the instant of impact — combat.rs.)
        if (dodging || decision.flags & MOVE_MASK != 0)
            && view.stamina > SPRINT_STAMINA_FLOOR
            && (dodging || d >= 0.6)
            && !imminent_hit
        {
            decision.flags |= input_flags::SPRINT;
        }

        // Dash: probabilistic, edge-triggered, 5.5 s cooldown, doubled urgency while dodging.
        let dash_chance = (0.02 + 0.08 * d) * if dodging { 2.0 } else { 1.0 };
        if decision.flags & MOVE_MASK != 0
            && now - self.last_dash_at >= DASH_COOLDOWN_S
            && rng.randf() < dash_chance
        {
            decision.flags |= input_flags::DASH;
            self.last_dash_at = now;
        }

        self.cached = decision;
        // DASH is edge-triggered; strip it so cached replays don't re-hold it. (ABILITY is added
        // later by `apply_ability`, never stored in the cache.)
        self.cached.flags &= !input_flags::DASH;
        decision
    }

    /// Layer the RMB ability onto an already-decided movement frame. Runs every frame (not cached)
    /// so the Warrior charge can stay held across ticks. Targets the live `self.target`:
    ///
    /// * **Warrior** (charge): on a fresh cast, aim straight at the target, clear the strafe so the
    ///   charge launches toward it (the sim steers toward `aim_dir`), and HOLD ABILITY for
    ///   `CHARGE_HOLD_S` so the charge runs its course. The previous code released after one tick,
    ///   so the Warrior barely moved — the bug the user reported.
    /// * **Rogue / Mage** (instant): a single-frame cast with the cursor set on the target so the
    ///   blink / blast actually lands on them instead of the bot's own feet.
    fn apply_ability(&mut self, decision: &mut Decision, view: &View, rng: &mut Pcg32, now: f64) {
        let Some(target_id) = self.target else { return };
        let Some(t) = view.entities.get(&target_id).copied() else {
            return;
        };
        let aim_at_target =
            ((t.pos.1 - view.pos.1) as f64).atan2((t.pos.0 - view.pos.0) as f64) as f32;

        // Sustain an in-progress Warrior charge: keep ABILITY held and keep steering at the target.
        if now < self.ability_hold_until {
            decision.flags = (decision.flags & !MOVE_MASK) | input_flags::ABILITY;
            decision.aim_angle = aim_at_target;
            return;
        }

        // Start a new cast: only while engaging a target in shoot range, throttled by our own
        // cooldown and an occasional roll (the server's real cooldown + mana gate is authoritative;
        // a refused cast costs nothing, so this just keeps casts sparse).
        let ability_chance = 0.04 + 0.10 * self.difficulty;
        let ready = decision.flags & input_flags::SHOOT != 0
            && now - self.last_ability_at >= ABILITY_COOLDOWN_S
            && rng.randf() < ability_chance;
        if !ready {
            return;
        }
        self.last_ability_at = now;
        if self.player_class == CLASS_WARRIOR {
            // Launch the charge toward the target and hold it.
            decision.flags = (decision.flags & !MOVE_MASK) | input_flags::ABILITY;
            decision.aim_angle = aim_at_target;
            self.ability_hold_until = now + CHARGE_HOLD_S;
        } else {
            // Instant cursor-targeted cast (Rogue Shadowstep / Mage Mageblast).
            decision.flags |= input_flags::ABILITY;
            decision.cursor = Some(t.pos);
        }
    }

    /// Nearest alive monster within range wins; otherwise nearest other player. Sticky: the
    /// current target is kept while it stays alive and in range.
    fn pick_target(&self, view: &View) -> Option<u16> {
        if let Some(id) = self.target {
            if let Some(e) = view.entities.get(&id) {
                if e.flags & entity_flags::ALIVE != 0
                    && e.flags & entity_flags::STEALTH == 0
                    && dist(view.pos, e.pos) <= TARGET_MAX_RANGE
                {
                    return Some(id);
                }
            }
        }
        let nearest = |pred: &dyn Fn(u16) -> bool| {
            view.entities
                .iter()
                .filter(|(id, e)| {
                    pred(**id)
                        && **id != view.my_id
                        && e.flags & entity_flags::ALIVE != 0
                        && e.flags & entity_flags::STEALTH == 0
                })
                .map(|(id, e)| (*id, dist(view.pos, e.pos)))
                .filter(|(_, d)| *d <= TARGET_MAX_RANGE)
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .map(|(id, _)| id)
        };
        nearest(&|id| (MONSTER_ID_START..=MONSTER_ID_END).contains(&id))
            .or_else(|| nearest(&|id| (1..=PLAYER_ID_MAX).contains(&id)))
    }

    /// Orbit the target inside a difficulty-scaled preferred range band and shoot with
    /// intercept-lead aim plus difficulty-scaled gaussian error.
    fn engage(
        &mut self,
        view: &View,
        rng: &mut Pcg32,
        now: f64,
        target_id: u16,
        t: KnownEntity,
    ) -> Decision {
        let d = self.difficulty as f32;
        let is_monster = target_id >= MONSTER_ID_START;
        let (pref_min, pref_max, shoot_range) = if is_monster {
            (260.0 + 40.0 * d, 360.0 + 80.0 * d, 520.0 + 100.0 * d)
        } else {
            (260.0 + 45.0 * d, 460.0 + 100.0 * d, 580.0 + 80.0 * d)
        };
        let (tx, ty) = (t.pos.0 - view.pos.0, t.pos.1 - view.pos.1);
        let range = (tx * tx + ty * ty).sqrt().max(1.0);
        let (nx, ny) = (tx / range, ty / range);

        let (mx, my) = if range > pref_max {
            (nx, ny) // close in
        } else if range < pref_min {
            (-nx, -ny) // back off
        } else {
            // Strafe perpendicular; flip side on a slow per-bot clock like the original.
            let side = if ((now * 0.45) as i64 + view.my_id as i64) % 2 == 0 {
                1.0
            } else {
                -1.0
            };
            (-ny * side, nx * side)
        };
        let mut flags = flags_from_dir(mx, my, AXIS_THRESHOLD);

        let mut aim = (ty as f64).atan2(tx as f64);
        if range <= shoot_range {
            // Intercept lead using the velocity estimated from snapshots.
            let lead = range / PROJECTILE_SPEED;
            let (ix, iy) = (t.pos.0 + t.vel.0 * lead, t.pos.1 + t.vel.1 * lead);
            aim = ((iy - view.pos.1) as f64).atan2((ix - view.pos.0) as f64);
            let max_err =
                (1.0 - self.difficulty) * (0.18 + (range.min(800.0) / 800.0) as f64 * 0.16);
            aim += rng.gauss(max_err);
            flags |= input_flags::SHOOT;
        }
        Decision {
            flags,
            aim_angle: aim as f32,
            cursor: None,
        }
    }
}

const MOVE_MASK: u16 = input_flags::MOVE_UP
    | input_flags::MOVE_DOWN
    | input_flags::MOVE_LEFT
    | input_flags::MOVE_RIGHT;

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    (dx * dx + dy * dy).sqrt()
}

/// Direction vector → WASD flags. Each axis activates above `threshold` of the normalized vector.
fn flags_from_dir(dx: f32, dy: f32, threshold: f32) -> u16 {
    let len = (dx * dx + dy * dy).sqrt();
    if len < 1e-6 {
        return 0;
    }
    let (nx, ny) = (dx / len, dy / len);
    let mut f = 0;
    if ny < -threshold {
        f |= input_flags::MOVE_UP;
    }
    if ny > threshold {
        f |= input_flags::MOVE_DOWN;
    }
    if nx < -threshold {
        f |= input_flags::MOVE_LEFT;
    }
    if nx > threshold {
        f |= input_flags::MOVE_RIGHT;
    }
    f
}

/// Nearest Healthorb (world-effect subtype 0) within `ORB_SEEK_RADIUS`, or `None`. Orbs are static,
/// so only the position is returned. They live in the AoI entity map keyed by id (band 40000–42499).
fn nearest_healthorb(view: &View) -> Option<(f32, f32)> {
    view.entities
        .iter()
        .filter(|(id, _)| world_effect_subtype_for_id(**id) == Some(world_effect::HEALTHORB))
        .map(|(_, e)| (dist(view.pos, e.pos), e.pos))
        .filter(|(d, _)| *d <= ORB_SEEK_RADIUS)
        .min_by(|a, b| a.0.total_cmp(&b.0))
        .map(|(_, pos)| pos)
}

/// Nearest incoming projectile NOT owned by this bot — monster, enemy player, or other bot — as
/// `(x, y, vx, vy)`. Owners are learned from `PROJECTILE_FIRED`; the bot's own shots are excluded
/// so it never dodges its own fire.
fn nearest_incoming_projectile(view: &View) -> Option<(f32, f32, f32, f32)> {
    view.projectile_owners
        .iter()
        .filter(|(_, owner)| **owner != view.my_id)
        .filter_map(|(pid, _)| view.entities.get(pid))
        .map(|e| (dist(view.pos, e.pos), e))
        .min_by(|a, b| a.0.total_cmp(&b.0))
        .map(|(_, e)| (e.pos.0, e.pos.1, e.vel.0, e.vel.1))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn empty_view<'a>(
        entities: &'a HashMap<u16, KnownEntity>,
        owners: &'a HashMap<u16, u16>,
    ) -> View<'a> {
        view_with_hp(entities, owners, 1.0)
    }

    fn view_with_hp<'a>(
        entities: &'a HashMap<u16, KnownEntity>,
        owners: &'a HashMap<u16, u16>,
        hp_fraction: f64,
    ) -> View<'a> {
        View {
            my_id: 1,
            pos: (500.0, 0.0),
            stamina: 100.0,
            hp_fraction,
            entities,
            projectile_owners: owners,
        }
    }

    #[test]
    fn idle_never_moves_or_shoots() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Idle, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(1);
        for _ in 0..100 {
            assert_eq!(
                b.decide(&empty_view(&entities, &owners), &mut rng, 0.0)
                    .flags,
                0
            );
        }
    }

    #[test]
    fn movement_never_shoots() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Movement, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(2);
        for _ in 0..200 {
            let d = b.decide(&empty_view(&entities, &owners), &mut rng, 0.0);
            assert_eq!(d.flags & input_flags::SHOOT, 0);
        }
    }

    #[test]
    fn combat_always_shoots() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Combat, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(3);
        for _ in 0..50 {
            let d = b.decide(&empty_view(&entities, &owners), &mut rng, 0.0);
            assert_ne!(d.flags & input_flags::SHOOT, 0);
        }
    }

    #[test]
    fn clustered_converges_on_origin() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Clustered, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(4);
        // From (500, 0) the bot must move left.
        let d = b.decide(&empty_view(&entities, &owners), &mut rng, 0.0);
        assert_ne!(d.flags & input_flags::MOVE_LEFT, 0);
        assert_eq!(d.flags & input_flags::MOVE_RIGHT, 0);
    }

    #[test]
    fn strategy_targets_and_shoots_a_close_monster() {
        let mut entities = HashMap::new();
        entities.insert(
            30001,
            KnownEntity {
                pos: (700.0, 0.0),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(5);
        // 200 u away from (500,0): inside shoot range, inside pref_min -> back off + shoot.
        let d = b.decide(&empty_view(&entities, &owners), &mut rng, 100.0);
        assert_ne!(d.flags & input_flags::SHOOT, 0);
        assert_ne!(
            d.flags & input_flags::MOVE_LEFT,
            0,
            "should back away (left)"
        );
        // Aim roughly toward +x (monster sits due east).
        assert!(d.aim_angle.abs() < 0.6, "aim {} not eastish", d.aim_angle);
    }

    #[test]
    fn strategy_ignores_stealthed_player() {
        // A single ALIVE+STEALTH player sits within targeting range. Bots must NOT acquire or shoot
        // it — the assassin is invisible (mirrors the server monster AI, which also skips STEALTH).
        let mut entities = HashMap::new();
        entities.insert(
            7,
            KnownEntity {
                pos: (700.0, 0.0),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE | entity_flags::STEALTH,
                last_tick: 1,
            },
        );
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        // pick_target must find nobody.
        assert_eq!(b.pick_target(&empty_view(&entities, &owners)), None);
        // And with only a stealthed target around, the strategy bot never shoots.
        let mut rng = Pcg32::new(7);
        for _ in 0..50 {
            let d = b.decide(&empty_view(&entities, &owners), &mut rng, 100.0);
            assert_eq!(
                d.flags & input_flags::SHOOT,
                0,
                "must not shoot a stealthed player"
            );
        }

        // Once the player drops STEALTH it is acquired again.
        entities.insert(
            7,
            KnownEntity {
                pos: (700.0, 0.0),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        assert_eq!(b.pick_target(&empty_view(&entities, &owners)), Some(7));
        // …and the bot now actually engages it: 200 u away is inside shoot range, so a fresh
        // decision must SHOOT (advance `now` past the reaction cache to force a re-decide).
        let mut now = 200.0;
        let shot = (0..50).any(|_| {
            now += 1.0;
            b.decide(&empty_view(&entities, &owners), &mut rng, now)
                .flags
                & input_flags::SHOOT
                != 0
        });
        assert!(shot, "should shoot a de-stealthed player in range");
    }

    /// A monster due east at 200 u — inside shoot range for the strategy AI.
    fn lone_monster_east() -> HashMap<u16, KnownEntity> {
        let mut entities = HashMap::new();
        entities.insert(
            30001,
            KnownEntity {
                pos: (700.0, 0.0),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        entities
    }

    #[test]
    fn warrior_holds_charge_and_steers_at_target() {
        let entities = lone_monster_east();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_WARRIOR);
        let mut rng = Pcg32::new(11);
        // Advance frames until the Warrior begins a charge (gated by a cooldown + a random roll).
        let mut now = 100.0;
        let mut charging = false;
        for _ in 0..1200 {
            let d = b.decide(&empty_view(&entities, &owners), &mut rng, now);
            if d.flags & input_flags::ABILITY != 0 {
                // A charge clears the strafe and aims straight at the target (due east ≈ 0 rad).
                assert_eq!(d.flags & MOVE_MASK, 0, "charge clears movement");
                assert!(
                    d.aim_angle.abs() < 0.2,
                    "charge aims at target, got {}",
                    d.aim_angle
                );
                charging = true;
                break;
            }
            now += 1.0 / 30.0;
        }
        assert!(charging, "warrior should eventually start a charge");
        // The next frame still HOLDS the ability — the charge is not released after one tick.
        let next = b.decide(&empty_view(&entities, &owners), &mut rng, now + 1.0 / 30.0);
        assert_ne!(
            next.flags & input_flags::ABILITY,
            0,
            "the charge must stay held across ticks"
        );
        assert_eq!(next.flags & MOVE_MASK, 0);
    }

    #[test]
    fn mage_cast_targets_the_cursor() {
        let entities = lone_monster_east();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(13);
        let mut now = 100.0;
        let mut cast_cursor = None;
        for _ in 0..1200 {
            let d = b.decide(&empty_view(&entities, &owners), &mut rng, now);
            if d.flags & input_flags::ABILITY != 0 {
                cast_cursor = d.cursor;
                break;
            }
            now += 1.0 / 30.0;
        }
        assert_eq!(
            cast_cursor,
            Some((700.0, 0.0)),
            "a Mage cast must put the cursor on the target, not the bot's own position"
        );
    }

    #[test]
    fn strategy_caches_decisions_and_strips_dash_replays() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(6);
        let first = b.decide(&empty_view(&entities, &owners), &mut rng, 0.0);
        // Within the reaction interval the cached decision replays, minus any DASH edge.
        let second = b.decide(&empty_view(&entities, &owners), &mut rng, 0.001);
        assert_eq!(
            second.flags & !input_flags::DASH,
            first.flags & !input_flags::DASH
        );
        assert_eq!(
            second.flags & input_flags::DASH & first.flags,
            second.flags & input_flags::DASH
        );
    }

    /// A Healthorb due south of the bot, well inside the seek range.
    fn orb_south() -> (u16, KnownEntity) {
        (
            world_effect::band_start(world_effect::HEALTHORB), // 40000
            KnownEntity {
                pos: (500.0, 300.0),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        )
    }

    #[test]
    fn hurt_bot_seeks_healthorb_while_still_shooting() {
        // 40% HP + a monster 200 u east + an orb 300 u south: the bot steers toward the orb
        // (south) instead of the engage back-off (west), yet keeps firing at the monster (east).
        let mut entities = lone_monster_east();
        let (orb_id, orb) = orb_south();
        entities.insert(orb_id, orb);
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(31);
        let d = b.decide(&view_with_hp(&entities, &owners, 0.40), &mut rng, 100.0);
        assert_ne!(
            d.flags & input_flags::MOVE_DOWN,
            0,
            "should steer toward the orb (south)"
        );
        assert_eq!(
            d.flags & input_flags::MOVE_LEFT,
            0,
            "orb-seek replaces the engage back-off"
        );
        assert_ne!(
            d.flags & input_flags::SHOOT,
            0,
            "keeps firing at the target while seeking the orb"
        );
        assert!(d.aim_angle.abs() < 0.6, "aim {} not eastish", d.aim_angle);
    }

    #[test]
    fn healthy_bot_ignores_healthorb() {
        // Same scene at full HP: no detour — the bot engages normally (backs off west from the
        // 200 u monster) and never heads south toward the orb.
        let mut entities = lone_monster_east();
        let (orb_id, orb) = orb_south();
        entities.insert(orb_id, orb);
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(32);
        let d = b.decide(&view_with_hp(&entities, &owners, 1.0), &mut rng, 100.0);
        assert_eq!(
            d.flags & input_flags::MOVE_DOWN,
            0,
            "a healthy bot must not chase the orb"
        );
        assert_ne!(
            d.flags & input_flags::MOVE_LEFT,
            0,
            "engages normally (backs off west)"
        );
    }

    fn closing_monster_shot(pos: (f32, f32)) -> (HashMap<u16, KnownEntity>, HashMap<u16, u16>) {
        let mut entities = HashMap::new();
        entities.insert(
            10001,
            KnownEntity {
                pos,
                vel: (-400.0, 0.0), // heading due west, into a bot sitting at (500, 0)
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        let mut owners = HashMap::new();
        owners.insert(10001u16, 30000u16); // projectile owned by a monster
        (entities, owners)
    }

    #[test]
    fn imminent_monster_shot_brakes_sprint() {
        // A monster shot right on top of the bot and still closing is a near-certain hit: the bot
        // must NOT sprint (a sprint-hit would Daze it), though it still dodges (moves).
        let (entities, owners) = closing_monster_shot((560.0, 0.0)); // 60 u east → imminent
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(21);
        let d = b.decide(&view_with_hp(&entities, &owners, 1.0), &mut rng, 100.0);
        assert_ne!(d.flags & MOVE_MASK, 0, "should still dodge the shot");
        assert_eq!(
            d.flags & input_flags::SPRINT,
            0,
            "must brake — never sprint into a near-certain hit"
        );

        // The same shot still a bit away (inside dodge range, outside imminent range) keeps the
        // sprint on: escape while there is still room.
        let (far, owners) = closing_monster_shot((700.0, 0.0)); // 200 u east → not yet imminent
        let mut b2 = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng2 = Pcg32::new(22);
        let d2 = b2.decide(&view_with_hp(&far, &owners, 1.0), &mut rng2, 100.0);
        assert_ne!(
            d2.flags & input_flags::SPRINT,
            0,
            "should sprint to escape a not-yet-imminent shot"
        );
    }

    #[test]
    fn dodges_player_projectile_not_just_monster() {
        // A shot owned by a *player* (id 7), 120 u east and closing. Monster-only dodging ignored
        // this (the "easy to hit the bot" playtest bug); now the bot dodges PvP fire too — the
        // shot heads due west, so the perpendicular evade is due north (MOVE_UP).
        let mut entities = HashMap::new();
        entities.insert(
            12345, // projectile-band id
            KnownEntity {
                pos: (620.0, 0.0),
                vel: (-400.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        let mut owners = HashMap::new();
        owners.insert(12345u16, 7u16); // owned by player 7, not a monster
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(41);
        let d = b.decide(&view_with_hp(&entities, &owners, 1.0), &mut rng, 100.0);
        assert_ne!(
            d.flags & input_flags::MOVE_UP,
            0,
            "should dodge a player's projectile (perpendicular = north)"
        );
    }

    #[test]
    fn ignores_own_projectile() {
        // The bot's own shot must never trigger a dodge. It engages a monster 200 u east (backs
        // off west) with its OWN projectile 150 u south: movement stays the engage back-off (west)
        // and does NOT steer east as a dodge of that shot would.
        let mut entities = lone_monster_east(); // monster 30001 at (700, 0)
        entities.insert(
            12345,
            KnownEntity {
                pos: (500.0, 150.0),
                vel: (0.0, -400.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: 1,
            },
        );
        let mut owners = HashMap::new();
        owners.insert(12345u16, 1u16); // my_id == 1 → our own shot
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0, CLASS_MAGE);
        let mut rng = Pcg32::new(42);
        let d = b.decide(&view_with_hp(&entities, &owners, 1.0), &mut rng, 100.0);
        assert_ne!(
            d.flags & input_flags::MOVE_LEFT,
            0,
            "engages normally — does not dodge its own shot"
        );
        assert_eq!(
            d.flags & input_flags::MOVE_RIGHT,
            0,
            "must not dodge its own projectile"
        );
    }
}
