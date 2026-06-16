//! Bot behavior modes, ported from the Python harness (`load_testing/bot_client.py`, retired with
//! the WebSocket server). The five load behaviors (default/idle/movement/combat/clustered) keep
//! the original constants and probabilities. `strategy` is a **simplified** gameplay AI — target
//! selection, orbit-at-range, intercept aim with difficulty-scaled error, projectile dodging, and
//! dash usage are ported; the old A* waypoint hunt and flanking planner are not (the full version
//! lives in git history before the Rust port).

use crate::rng::Pcg32;
use protocol::types::{entity_flags, input_flags, MONSTER_ID_END, MONSTER_ID_START, PLAYER_ID_MAX};
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

/// One input frame's worth of intent: full `input_flags` (movement + SHOOT/SPRINT/DASH) + aim.
#[derive(Debug, Clone, Copy)]
pub struct Decision {
    pub flags: u16,
    pub aim_angle: f32,
}

impl Decision {
    const IDLE: Decision = Decision {
        flags: 0,
        aim_angle: 0.0,
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
const TARGET_MAX_RANGE: f32 = 1250.0; // 1.25 × AoI radius
const PROJECTILE_SPEED: f32 = 400.0;
const DODGE_RADIUS: f32 = 220.0;
// Python thresholded a normalized axis to ±1 above 35/speed (= 35/200).
const AXIS_THRESHOLD: f32 = 0.175;

pub struct BehaviorState {
    pub kind: BehaviorKind,
    difficulty: f64,
    dir_flags: u16,
    cached: Decision,
    next_decision_at: f64,
    last_dash_at: f64,
    last_ability_at: f64,
    target: Option<u16>,
}

impl BehaviorState {
    pub fn new(kind: BehaviorKind, difficulty: f64) -> Self {
        Self {
            kind,
            difficulty: difficulty.clamp(0.0, 1.0),
            dir_flags: 0,
            cached: Decision::IDLE,
            next_decision_at: 0.0,
            last_dash_at: f64::NEG_INFINITY,
            last_ability_at: f64::NEG_INFINITY,
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
        }
    }

    fn strategy(&mut self, view: &View, rng: &mut Pcg32, now: f64) -> Decision {
        // Reaction-time cache: expert (1.0) re-decides every 40 ms, novice (0.0) every 500 ms.
        // DASH and ABILITY are edge-triggered, so they are stripped from the cache after the first
        // replay.
        if now < self.next_decision_at {
            let out = self.cached;
            self.cached.flags &= !(input_flags::DASH | input_flags::ABILITY);
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

        // Projectile dodge overlay: steer perpendicular to the closest incoming monster shot.
        let mut dodging = false;
        if let Some((px, py, pvx, pvy)) = nearest_monster_projectile(view) {
            let (rx, ry) = (view.pos.0 - px, view.pos.1 - py);
            if rx * rx + ry * ry < DODGE_RADIUS * DODGE_RADIUS {
                dodging = true;
                let speed = (pvx * pvx + pvy * pvy).sqrt();
                let (fx, fy) = if speed > 1.0 {
                    (pvx / speed, pvy / speed)
                } else {
                    let len = (rx * rx + ry * ry).sqrt().max(1.0);
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
        }

        // Sprint while repositioning or dodging, gated on the stamina meter like a human would.
        if (dodging || decision.flags & MOVE_MASK != 0)
            && view.stamina > SPRINT_STAMINA_FLOOR
            && (dodging || d >= 0.6)
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

        // Ability (RMB): conservative, edge-triggered cast so the swarm exercises Warrior Charge /
        // Rogue Shadowstep. Only fire when we are actually engaging a target in shoot range (the
        // SHOOT flag is set by `engage` exactly then), and only occasionally, throttled by our own
        // cooldown like DASH. The real cooldown + mana gate lives server-side, where a refused cast
        // costs nothing, so this self-throttle just needs to keep casts sparse.
        let ability_chance = 0.04 + 0.10 * d;
        if self.target.is_some()
            && decision.flags & input_flags::SHOOT != 0
            && now - self.last_ability_at >= ABILITY_COOLDOWN_S
            && rng.randf() < ability_chance
        {
            decision.flags |= input_flags::ABILITY;
            self.last_ability_at = now;
        }

        self.cached = decision;
        // DASH and ABILITY are edge-triggered; strip them so cached replays don't re-hold them.
        self.cached.flags &= !(input_flags::DASH | input_flags::ABILITY);
        decision
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

fn nearest_monster_projectile(view: &View) -> Option<(f32, f32, f32, f32)> {
    view.projectile_owners
        .iter()
        .filter(|(_, owner)| **owner >= MONSTER_ID_START)
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
        View {
            my_id: 1,
            pos: (500.0, 0.0),
            stamina: 100.0,
            entities,
            projectile_owners: owners,
        }
    }

    #[test]
    fn idle_never_moves_or_shoots() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Idle, 1.0);
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
        let mut b = BehaviorState::new(BehaviorKind::Movement, 1.0);
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
        let mut b = BehaviorState::new(BehaviorKind::Combat, 1.0);
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
        let mut b = BehaviorState::new(BehaviorKind::Clustered, 1.0);
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
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0);
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
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0);
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

    #[test]
    fn strategy_caches_decisions_and_strips_dash_replays() {
        let entities = HashMap::new();
        let owners = HashMap::new();
        let mut b = BehaviorState::new(BehaviorKind::Strategy, 1.0);
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
}
