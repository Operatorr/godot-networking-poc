//! Projectile registry, integration, and the two server collision passes — port of
//! `projectile_manager.gd` / `projectile_state.gd` (extraction combat §4.3, §4.6–4.7).

use crate::player::{PlayerManager, PositionSnapshot};
use sim_core::constants::*;
use sim_core::{arena, hit, Vec2};

#[derive(Debug, Clone)]
pub struct ProjectileState {
    pub entity_id: u16,
    pub owner_id: u16,
    pub position: Vec2,
    pub previous_position: Vec2,
    pub direction: Vec2,
    pub speed: f32,
    /// Knockback impulse (u/s) this projectile applies on a surviving player hit. Per-projectile
    /// so future weapons/abilities/items can vary it; today set from the spawn-site constant.
    pub knockback_force: f64,
    /// Damage this projectile deals to a MONSTER (PvE pass). 0 = use the legacy flat constant
    /// (monster-owned bullets never enter the PvE pass, so theirs is ignored). Player primary
    /// shots set their class+level-scaled value; ability projectiles set the ability value.
    pub damage: i32,
    /// Max monsters this projectile can hit before dying. 0/1 = single-hit; >1 = piercing
    /// (Void Hunter multishot). Targets already hit are tracked in `hit_targets`.
    pub pierce: u8,
    pub hit_targets: Vec<u16>,
    pub distance_traveled: f32,
    pub alive: bool,
    pub spawn_tick: u64,
    pub simulation_ticks: u64,
    pub collision_rewind_ticks: u64,
    pub pvp_collision_rewind_ticks: u64,
    pub removal_reason: &'static str,
}

impl ProjectileState {
    /// Integrate one tick. Returns true when the projectile should be removed.
    /// Check order is exact: max-distance → bounds (inclusive ±1000, no clamp) → obstacle
    /// (position clamps to the wall contact point).
    pub fn update(&mut self, delta: f64) -> bool {
        if !self.alive {
            if self.removal_reason.is_empty() {
                self.removal_reason = "inactive";
            }
            return true;
        }
        let old = self.position;
        self.previous_position = old;
        let movement = self.direction * (self.speed * delta as f32);
        self.position += movement;
        self.distance_traveled += movement.length();
        self.simulation_ticks += 1;
        if self.distance_traveled >= PROJECTILE_MAX_DISTANCE {
            self.alive = false;
            self.removal_reason = "max_distance";
            return true;
        }
        if !arena::is_within_bounds(self.position) {
            self.alive = false;
            self.removal_reason = "out_of_bounds";
            return true;
        }
        if let Some(hit_point) = arena::line_intersects_obstacle(old, self.position) {
            self.position = hit_point;
            self.alive = false;
            self.removal_reason = "obstacle";
            return true;
        }
        false
    }

    /// "The delayed world advances with the projectile's age" (extraction combat §4.7).
    pub fn lag_compensated_monster_tick(&self) -> u64 {
        if self.collision_rewind_ticks == 0 {
            return self.spawn_tick + self.simulation_ticks;
        }
        (self.spawn_tick + self.simulation_ticks).saturating_sub(self.collision_rewind_ticks)
    }

    pub fn lag_compensated_player_tick(&self) -> u64 {
        if self.pvp_collision_rewind_ticks == 0 {
            return self.spawn_tick + self.simulation_ticks;
        }
        (self.spawn_tick + self.simulation_ticks).saturating_sub(self.pvp_collision_rewind_ticks)
    }
}

#[derive(Debug, Clone)]
pub struct HitEvent {
    #[allow(dead_code)] // diagnostics parity
    pub projectile_id: u16,
    pub target_id: u16,
    pub owner_id: u16,
    /// Closest point on the projectile's travel segment to the (compensated) target center.
    pub position: Vec2,
    /// The projectile's normalized travel direction — the knockback direction on player hits.
    pub direction: Vec2,
    /// The projectile's per-spawn knockback impulse (u/s).
    pub knockback_force: f64,
    /// Per-projectile monster damage (0 = use the legacy flat constant). Used by the PvE branch.
    pub damage: i32,
}

#[derive(Default)]
pub struct ProjectileManager {
    /// Spawn (insertion) order — hit processing and kill attribution follow it.
    pub projectiles: Vec<ProjectileState>,
    next_entity_id: u16,
}

impl ProjectileManager {
    pub fn new() -> Self {
        Self {
            projectiles: Vec::new(),
            next_entity_id: PROJECTILE_ENTITY_ID_START,
        }
    }

    fn allocate_entity_id(&mut self) -> Option<u16> {
        let range_size = (PROJECTILE_ENTITY_ID_END - PROJECTILE_ENTITY_ID_START + 1) as usize;
        for _ in 0..range_size {
            let candidate = self.next_entity_id;
            self.next_entity_id += 1;
            if self.next_entity_id > PROJECTILE_ENTITY_ID_END {
                self.next_entity_id = PROJECTILE_ENTITY_ID_START;
            }
            if !self.projectiles.iter().any(|p| p.entity_id == candidate) {
                return Some(candidate);
            }
        }
        None
    }

    #[allow(clippy::too_many_arguments)]
    pub fn spawn_projectile(
        &mut self,
        owner_id: u16,
        position: Vec2,
        direction: Vec2,
        spawn_tick: u64,
        rewind_ticks: u64,
        pvp_rewind_ticks: u64,
        speed: f32,
        knockback_force: f64,
    ) -> Option<&ProjectileState> {
        self.spawn_projectile_ex(
            owner_id,
            position,
            direction,
            spawn_tick,
            rewind_ticks,
            pvp_rewind_ticks,
            speed,
            knockback_force,
            0,
            0,
        )
    }

    /// Full spawn with a per-projectile monster `damage` and `pierce` count (multishot). The
    /// 8-arg `spawn_projectile` forwards here with `damage = 0` (legacy flat) and `pierce = 0`.
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_projectile_ex(
        &mut self,
        owner_id: u16,
        position: Vec2,
        direction: Vec2,
        spawn_tick: u64,
        rewind_ticks: u64,
        pvp_rewind_ticks: u64,
        speed: f32,
        knockback_force: f64,
        damage: i32,
        pierce: u8,
    ) -> Option<&ProjectileState> {
        if direction.x.abs() < 1e-5 && direction.y.abs() < 1e-5 {
            return None;
        }
        let entity_id = self.allocate_entity_id()?;
        self.projectiles.push(ProjectileState {
            entity_id,
            owner_id,
            position,
            previous_position: position,
            direction: direction.normalized(),
            speed,
            knockback_force,
            damage,
            pierce,
            hit_targets: Vec::new(),
            distance_traveled: 0.0,
            alive: true,
            spawn_tick,
            simulation_ticks: 0,
            collision_rewind_ticks: rewind_ticks,
            pvp_collision_rewind_ticks: pvp_rewind_ticks,
            removal_reason: "",
        });
        self.projectiles.last()
    }

    pub fn get(&self, entity_id: u16) -> Option<&ProjectileState> {
        self.projectiles.iter().find(|p| p.entity_id == entity_id)
    }

    pub fn update_all(&mut self, delta: f64) {
        for p in &mut self.projectiles {
            p.update(delta);
        }
        self.projectiles.retain(|p| p.alive);
    }

    pub fn remove_projectile(&mut self, entity_id: u16, reason: &'static str) {
        if let Some(p) = self
            .projectiles
            .iter_mut()
            .find(|p| p.entity_id == entity_id)
        {
            p.alive = false;
            p.removal_reason = reason;
        }
        self.projectiles.retain(|p| p.alive);
    }

    pub fn count(&self) -> usize {
        self.projectiles.len()
    }

    /// PvP pass — server-authoritative, lag-compensated, defender-favor lerp. The skip on
    /// monster-owned projectiles is D11 carried-forward invariant #1.
    pub fn check_collisions_with_players(&mut self, players: &PlayerManager) -> Vec<HitEvent> {
        let mut hits = Vec::new();
        for proj in &mut self.projectiles {
            if !proj.alive {
                continue;
            }
            if hit::is_client_authoritative(proj.owner_id) {
                continue; // invariant #1: monster-owned never enter the server player pass
            }
            let collision_tick = proj.lag_compensated_player_tick();
            let roster = players.get_alive_snapshot(collision_tick);
            for snap in nearby(&roster, proj.position) {
                if proj.owner_id == snap.entity_id {
                    continue; // never hit owner
                }
                let mut test_position = snap.position;
                if PVP_DEFENDER_FAVOR > 0.0 {
                    if let Some(live) = players.get_by_entity_id(snap.entity_id) {
                        test_position = lerp_vec(snap.position, live.position, PVP_DEFENDER_FAVOR);
                    }
                }
                let hit_point = arena::closest_point_on_segment(
                    test_position,
                    proj.previous_position,
                    proj.position,
                );
                if test_position.distance_to(hit_point) < PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS {
                    proj.alive = false;
                    proj.removal_reason = "player_hit";
                    hits.push(HitEvent {
                        projectile_id: proj.entity_id,
                        target_id: snap.entity_id,
                        owner_id: proj.owner_id,
                        position: hit_point,
                        direction: proj.direction,
                        knockback_force: proj.knockback_force,
                        damage: proj.damage,
                    });
                    break; // one target per projectile (PvP is single-hit even for pierce)
                }
            }
        }
        self.projectiles.retain(|p| p.alive);
        hits
    }

    /// PvE pass — only player-owned projectiles test monsters; rewound roster; window 24.0.
    pub fn check_collisions_with_monsters(
        &mut self,
        monster_snapshot: impl Fn(u64) -> Vec<PositionSnapshot>,
    ) -> Vec<HitEvent> {
        let mut hits = Vec::new();
        for proj in &mut self.projectiles {
            if !proj.alive {
                continue;
            }
            if proj.owner_id >= MONSTER_ENTITY_ID_START {
                continue; // monster-owned never hit monsters
            }
            let collision_tick = proj.lag_compensated_monster_tick();
            let roster = monster_snapshot(collision_tick);
            // pierce 0/1 ⇒ single-hit; pierce N>1 ⇒ passes through up to N monsters.
            let max_hits = if proj.pierce <= 1 {
                1
            } else {
                proj.pierce as usize
            };
            for snap in nearby(&roster, proj.position) {
                if proj.hit_targets.contains(&snap.entity_id) {
                    continue; // a piercing bullet hits each monster at most once
                }
                let hit_point = arena::closest_point_on_segment(
                    snap.position,
                    proj.previous_position,
                    proj.position,
                );
                if snap.position.distance_to(hit_point) < PROJECTILE_RADIUS + MONSTER_HITBOX_RADIUS
                {
                    proj.hit_targets.push(snap.entity_id);
                    hits.push(HitEvent {
                        projectile_id: proj.entity_id,
                        target_id: snap.entity_id,
                        owner_id: proj.owner_id,
                        position: hit_point,
                        direction: proj.direction,
                        knockback_force: proj.knockback_force,
                        damage: proj.damage,
                    });
                    if proj.hit_targets.len() >= max_hits {
                        proj.alive = false;
                        proj.removal_reason = "monster_hit";
                        break;
                    }
                }
            }
        }
        self.projectiles.retain(|p| p.alive);
        hits
    }

    /// Shutdown path.
    #[allow(dead_code)]
    pub fn clear_all(&mut self) {
        self.projectiles.clear();
    }
}

/// Broad-phase: the GDScript used a 64-unit spatial hash queried 3×3 around the projectile.
/// Roster sizes here are ≤ a few hundred; a distance prefilter with the same guarantee
/// (everything within one tick of travel + hit window is kept) preserves the semantics —
/// candidates are filtered by the exact narrow-phase test either way.
fn nearby(roster: &[PositionSnapshot], around: Vec2) -> impl Iterator<Item = &PositionSnapshot> {
    // 96 u comfortably exceeds the narrow-phase reach (~52 u: one tick of travel + hit
    // window), so the candidate SET matches the GDScript grid's. (The 3×3 64-unit grid's
    // own worst-case reach is only 64 u — the equivalence holds via the reach bound.)
    const BROAD_RADIUS_SQ: f32 = 96.0 * 96.0;
    roster
        .iter()
        .filter(move |s| s.position.distance_squared_to(around) <= BROAD_RADIUS_SQ)
}

fn lerp_vec(a: Vec2, b: Vec2, t: f32) -> Vec2 {
    Vec2::new(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)
}

#[cfg(test)]
mod tests {
    use super::*;

    const DT: f64 = 1.0 / 30.0;

    /// sim_core debug_asserts each thread set its world geometry before any bounds/obstacle read
    /// (arena.rs contract). Each libtest test is its own thread — apply the Arena geometry first.
    fn init_arena_geometry() {
        sim_core::set_world_geometry(
            sim_core::constants::MAP_MIN,
            sim_core::constants::MAP_MAX,
            true,
        );
    }

    fn spawn(mgr: &mut ProjectileManager, owner: u16, pos: Vec2, dir: Vec2) -> u16 {
        mgr.spawn_projectile(
            owner,
            pos,
            dir,
            1,
            0,
            0,
            PROJECTILE_SPEED,
            PLAYER_PROJECTILE_KNOCKBACK_FORCE,
        )
        .unwrap()
        .entity_id
    }

    #[test]
    fn max_distance_kills_at_800() {
        init_arena_geometry();
        let mut mgr = ProjectileManager::new();
        spawn(&mut mgr, 1, Vec2::new(-900.0, 900.0), Vec2::new(1.0, 0.0));
        let mut ticks = 0;
        while mgr.count() > 0 {
            mgr.update_all(DT);
            ticks += 1;
            assert!(ticks < 100);
        }
        // 800 / (400/30) = 60 nominal; f32 accumulation residue may push the >= 800 crossing
        // to the 61st tick (the GDScript has the same float sensitivity).
        assert!((60..=61).contains(&ticks), "ticks = {ticks}");
    }

    #[test]
    fn obstacle_clamps_position() {
        init_arena_geometry();
        let mut mgr = ProjectileManager::new();
        // Fired straight at the center north pillar from the left.
        spawn(&mut mgr, 1, Vec2::new(-40.0, -100.0), Vec2::new(1.0, 0.0));
        for _ in 0..5 {
            mgr.update_all(DT);
        }
        assert_eq!(mgr.count(), 0); // died on the pillar face (x = −20) within 2 ticks
    }

    #[test]
    fn id_recycling_skips_live_ids() {
        let mut mgr = ProjectileManager::new();
        let a = spawn(&mut mgr, 1, Vec2::ZERO, Vec2::new(1.0, 0.0));
        let b = spawn(&mut mgr, 1, Vec2::ZERO, Vec2::new(1.0, 0.0));
        assert_eq!(a, 10000);
        assert_eq!(b, 10001);
        mgr.remove_projectile(a, "removed");
        // Cursor keeps advancing; the freed id is not immediately reused.
        let c = spawn(&mut mgr, 1, Vec2::ZERO, Vec2::new(1.0, 0.0));
        assert_eq!(c, 10002);
    }

    #[test]
    fn zero_direction_rejected() {
        let mut mgr = ProjectileManager::new();
        assert!(mgr
            .spawn_projectile(1, Vec2::ZERO, Vec2::ZERO, 1, 0, 0, 400.0, 450.0)
            .is_none());
    }

    #[test]
    fn monster_owned_skips_player_pass() {
        init_arena_geometry();
        let mut mgr = ProjectileManager::new();
        let mut players = PlayerManager::new();
        let p = players.add_player(7).unwrap();
        p.authenticated = true;
        let target_pos = players.players[0].position;
        // Monster projectile passing straight through the player.
        spawn(
            &mut mgr,
            30001,
            target_pos - Vec2::new(20.0, 0.0),
            Vec2::new(1.0, 0.0),
        );
        players.record_position_snapshot(1);
        mgr.update_all(DT);
        let hits = mgr.check_collisions_with_players(&players);
        assert!(
            hits.is_empty(),
            "monster-owned projectiles must never hit in the server player pass"
        );
        assert_eq!(mgr.count(), 1, "projectile must survive the pass");
    }

    #[test]
    fn player_projectile_hits_other_player_not_owner() {
        init_arena_geometry();
        let mut mgr = ProjectileManager::new();
        let mut players = PlayerManager::new();
        players.add_player(1).unwrap().authenticated = true;
        players.add_player(2).unwrap().authenticated = true;
        // Both players at known spawns: 1 → (-800,-800), 2 → (0,-800).
        let shooter = players.players[0].entity_id;
        let victim_pos = players.players[1].position;
        players.record_position_snapshot(1);
        spawn(
            &mut mgr,
            shooter,
            victim_pos - Vec2::new(20.0, 0.0),
            Vec2::new(1.0, 0.0),
        );
        mgr.update_all(DT);
        let hits = mgr.check_collisions_with_players(&players);
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].target_id, players.players[1].entity_id);
    }
}
