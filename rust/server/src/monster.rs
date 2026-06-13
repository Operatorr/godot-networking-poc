//! Monster subsystem — definitions, per-monster state, the four-state AI, the three-layer spawn
//! director, id allocation, and the lag-comp position history. Port of `monster_*.gd` per
//! extraction monsters.md. All RNG goes through the sim-owned PCG (seedable for tests).

use crate::player::{PlayerManager, PositionSnapshot};
use crate::projectile::ProjectileManager;
use crate::rng::Pcg32;
use protocol::types::{anim, entity_flags};
use sim_core::constants::*;
use sim_core::{arena, Rect, Vec2};

#[derive(Debug, Clone)]
pub struct MonsterDefinition {
    #[allow(dead_code)] // kept for logging/debug parity
    pub id: &'static str,
    pub ai_profile: &'static str,
    pub max_health: i32,
    pub move_speed: f32,
    pub hitbox_radius: f32,
    pub detection_range: f32,
    pub lose_interest_range: f32,
    pub retarget_interval: f64,
    pub attack_range: f32,
    pub flee_distance: f32,
    pub preferred_distance: f32,
    pub shoot_cooldown: f64,
    pub attack_duration: f64,
    pub projectile_speed: f32,
    pub steering_randomness: f64,
    pub avoidance_distance: f32,
    /// Experience granted to every player within XP_SHARE_RADIUS when this monster dies.
    /// Scales with the monster's strength/tier (Tier 1 Toxic Slime = 20); 0 = no XP (dummies).
    pub xp_reward: u32,
}

/// The shipped catalogue (client/data/monsters/*.json) embedded; unknown ids fall back to
/// toxic_slime, matching MonsterDatabase semantics.
pub fn definition(type_id: &str) -> &'static MonsterDefinition {
    match type_id {
        "target_dummy" => &TARGET_DUMMY,
        _ => &TOXIC_SLIME,
    }
}

pub static TOXIC_SLIME: MonsterDefinition = MonsterDefinition {
    id: "toxic_slime",
    ai_profile: "ranged_kiter",
    max_health: 50,
    move_speed: 120.0,
    hitbox_radius: 16.0,
    detection_range: 650.0,
    lose_interest_range: 900.0,
    retarget_interval: 1.0,
    attack_range: 200.0,
    flee_distance: 100.0,
    preferred_distance: 150.0,
    shoot_cooldown: 0.75,
    attack_duration: 0.5,
    projectile_speed: 300.0,
    steering_randomness: 0.15,
    avoidance_distance: 50.0,
    xp_reward: 20,
};

pub static TARGET_DUMMY: MonsterDefinition = MonsterDefinition {
    id: "target_dummy",
    ai_profile: "stationary_dummy",
    max_health: 100,
    move_speed: 0.0,
    hitbox_radius: 18.0,
    detection_range: 0.0,
    lose_interest_range: 0.0,
    retarget_interval: 999.0,
    attack_range: 0.0,
    flee_distance: 0.0,
    preferred_distance: 0.0,
    shoot_cooldown: 999.0,
    attack_duration: 0.0,
    projectile_speed: 0.0,
    steering_randomness: 0.0,
    avoidance_distance: 0.0,
    xp_reward: 0,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AiState {
    Idle,
    Chase,
    Attack,
    Flee,
}

pub struct MonsterState {
    pub entity_id: u16,
    pub definition: &'static MonsterDefinition,
    pub position: Vec2,
    pub health: i32,
    #[allow(dead_code)] // no live consumer (parity with monster_state.gd)
    pub max_health: i32,
    pub is_alive: bool,
    pub animation_state: u8,
    pub entity_flags: u16,
    pub ai_state: AiState,
    /// 0 = no target, else a player entity id.
    pub target_id: u16,
    pub shoot_cooldown: f64,
    pub last_fired_projectile_id: u16,
    pub attack_timer: f64,
    pub retarget_timer: f64,
    pub move_direction: Vec2,
    pub steering_offset: Vec2,
    /// Decremented without clamp — may go negative (extraction monsters §4.3).
    pub steering_timer: f64,
}

impl MonsterState {
    pub fn new(entity_id: u16, position: Vec2, def: &'static MonsterDefinition) -> Self {
        Self {
            entity_id,
            definition: def,
            position,
            health: def.max_health,
            max_health: def.max_health,
            is_alive: true,
            animation_state: anim::IDLE,
            entity_flags: entity_flags::ALIVE | entity_flags::VISIBLE,
            ai_state: AiState::Idle,
            target_id: 0,
            shoot_cooldown: 0.0,
            last_fired_projectile_id: 0,
            attack_timer: 0.0,
            retarget_timer: 0.0,
            move_direction: Vec2::ZERO,
            steering_offset: Vec2::ZERO,
            steering_timer: 0.0,
        }
    }

    /// Exact order (extraction monsters §4.3).
    pub fn update_timers(&mut self, delta: f64) {
        if self.shoot_cooldown > 0.0 {
            self.shoot_cooldown = (self.shoot_cooldown - delta).max(0.0);
        }
        if self.attack_timer > 0.0 {
            self.attack_timer = (self.attack_timer - delta).max(0.0);
        }
        self.retarget_timer += delta;
        self.steering_timer -= delta;
    }

    pub fn can_shoot(&self) -> bool {
        self.is_alive && self.shoot_cooldown <= 0.0
    }

    /// Returns true iff this killed the monster.
    pub fn take_damage(&mut self, amount: i32) -> bool {
        if !self.is_alive || amount <= 0 {
            return false;
        }
        self.health = (self.health - amount).max(0);
        if self.health == 0 {
            self.is_alive = false;
            self.move_direction = Vec2::ZERO;
            self.entity_flags &=
                !(entity_flags::ALIVE | entity_flags::MOVING | entity_flags::ATTACKING);
            self.animation_state = anim::DEATH;
            return true;
        }
        self.animation_state = anim::HIT; // overwritten next AI tick while alive
        false
    }
}

// ── Manager ─────────────────────────────────────────────────────────────────

pub struct MonsterManager {
    /// Registry insertion order (GDScript Dictionary semantics).
    pub monsters: Vec<MonsterState>,
    next_entity_id: u16,
    position_history: Vec<(u64, Vec<PositionSnapshot>)>,
}

pub const POSITION_HISTORY_TICKS: usize = 8;

impl Default for MonsterManager {
    fn default() -> Self {
        Self::new()
    }
}

impl MonsterManager {
    pub fn new() -> Self {
        Self {
            monsters: Vec::new(),
            next_entity_id: MONSTER_ENTITY_ID_START,
            position_history: Vec::new(),
        }
    }

    /// Monotonic cursor 30000→39999 with wraparound; skip-if-live; cursor advances even on
    /// skipped candidates; None when all 10000 ids are live.
    fn allocate_entity_id(&mut self) -> Option<u16> {
        let range_size = (MONSTER_ENTITY_ID_END - MONSTER_ENTITY_ID_START + 1) as usize;
        for _ in 0..range_size {
            let candidate = self.next_entity_id;
            self.next_entity_id += 1;
            if self.next_entity_id > MONSTER_ENTITY_ID_END {
                self.next_entity_id = MONSTER_ENTITY_ID_START;
            }
            if !self.monsters.iter().any(|m| m.entity_id == candidate) {
                return Some(candidate);
            }
        }
        None
    }

    pub fn spawn_monster(&mut self, position: Vec2, type_id: &str) -> Option<&MonsterState> {
        let entity_id = self.allocate_entity_id()?;
        self.monsters
            .push(MonsterState::new(entity_id, position, definition(type_id)));
        self.monsters.last()
    }

    #[allow(dead_code)]
    pub fn get(&self, entity_id: u16) -> Option<&MonsterState> {
        self.monsters.iter().find(|m| m.entity_id == entity_id)
    }

    pub fn get_mut(&mut self, entity_id: u16) -> Option<&mut MonsterState> {
        self.monsters.iter_mut().find(|m| m.entity_id == entity_id)
    }

    pub fn alive_count(&self) -> usize {
        self.monsters.iter().filter(|m| m.is_alive).count()
    }

    pub fn count(&self) -> usize {
        self.monsters.len()
    }

    pub fn closest_alive_distance_sq(&self, position: Vec2) -> Option<f32> {
        self.monsters
            .iter()
            .filter(|m| m.is_alive)
            .map(|m| m.position.distance_squared_to(position))
            .fold(None, |best, d| match best {
                Some(b) if b <= d => Some(b),
                _ => Some(d),
            })
    }

    /// Tick step 4: alive monsters only, post-AI-movement, pre-collision.
    pub fn record_position_snapshot(&mut self, server_tick: u64) {
        let snapshot: Vec<PositionSnapshot> = self
            .monsters
            .iter()
            .filter(|m| m.is_alive)
            .map(|m| PositionSnapshot {
                entity_id: m.entity_id,
                position: m.position,
            })
            .collect();
        self.position_history.push((server_tick, snapshot));
        while self.position_history.len() > POSITION_HISTORY_TICKS {
            self.position_history.remove(0);
        }
    }

    /// Fallback chain: exact → newest ≤ requested → oldest stored → live alive monsters.
    pub fn get_alive_snapshot(&self, server_tick: u64) -> Vec<PositionSnapshot> {
        if let Some((_, snap)) = self
            .position_history
            .iter()
            .find(|(t, _)| *t == server_tick)
        {
            return snap.clone();
        }
        if let Some((_, snap)) = self
            .position_history
            .iter()
            .filter(|(t, _)| *t <= server_tick)
            .max_by_key(|(t, _)| *t)
        {
            return snap.clone();
        }
        if let Some((_, snap)) = self.position_history.first() {
            return snap.clone();
        }
        self.monsters
            .iter()
            .filter(|m| m.is_alive)
            .map(|m| PositionSnapshot {
                entity_id: m.entity_id,
                position: m.position,
            })
            .collect()
    }

    /// Tick step 7 — strictly after the broadcast step so the death state replicates once.
    pub fn cleanup_dead_monsters(&mut self) {
        self.monsters.retain(|m| m.is_alive);
    }

    /// Shutdown path.
    #[allow(dead_code)]
    pub fn clear_all(&mut self) {
        self.monsters.clear();
        self.position_history.clear();
    }
}

// ── Spawner ─────────────────────────────────────────────────────────────────

struct SpawnRegion {
    rect: Rect,
    last_player_time: f64,
    player_count: usize,
}

pub struct MonsterSpawner {
    pub spawn_rate: f64,
    pub enabled: bool,
    spawn_timer: f64,
    director_time: f64,
    regions: Vec<SpawnRegion>,
}

impl MonsterSpawner {
    pub fn new(spawn_rate: f64) -> Self {
        // 4×4 grid of 500×500 cells over the 2000×2000 map, row-major from MAP_MIN.
        let mut regions = Vec::with_capacity(16);
        for y in 0..MONSTER_SPAWN_REGION_ROWS {
            for x in 0..MONSTER_SPAWN_REGION_COLUMNS {
                regions.push(SpawnRegion {
                    rect: Rect::new(
                        MAP_MIN.x + x as f32 * 500.0,
                        MAP_MIN.y + y as f32 * 500.0,
                        500.0,
                        500.0,
                    ),
                    last_player_time: -9999.0,
                    player_count: 0,
                });
            }
        }
        Self {
            spawn_rate: spawn_rate.max(0.01),
            enabled: true,
            spawn_timer: 0.0,
            director_time: 0.0,
            regions,
        }
    }

    /// Once per tick. Accumulator pauses at the population cap (no catch-up burst).
    pub fn update(
        &mut self,
        delta: f64,
        monsters: &mut MonsterManager,
        players: &PlayerManager,
        rng: &mut Pcg32,
    ) {
        if !self.enabled {
            return;
        }
        self.director_time += delta;
        self.update_region_player_state(players);

        if monsters.alive_count() >= MONSTER_MAX_COUNT {
            return; // BEFORE the timer accumulates
        }
        self.spawn_timer += delta;
        let spawn_interval = 1.0 / self.spawn_rate;
        while self.spawn_timer >= spawn_interval {
            self.spawn_timer -= spawn_interval;
            if monsters.alive_count() >= MONSTER_MAX_COUNT {
                break;
            }
            if let Some(pos) = self.select_spawn_position(monsters, players, rng) {
                monsters.spawn_monster(pos, "toxic_slime");
            }
            // A failed placement consumes the slot — no retry until the next interval.
        }
    }

    fn region_index_for(&self, pos: Vec2) -> Option<usize> {
        if !arena::is_within_bounds(pos) {
            return None;
        }
        let rel_x = pos.x - MAP_MIN.x;
        let rel_y = pos.y - MAP_MIN.y;
        let x = ((rel_x / 2000.0 * 4.0).floor() as i32).clamp(0, 3) as usize;
        let y = ((rel_y / 2000.0 * 4.0).floor() as i32).clamp(0, 3) as usize;
        Some(y * 4 + x)
    }

    fn update_region_player_state(&mut self, players: &PlayerManager) {
        for r in &mut self.regions {
            r.player_count = 0;
        }
        let director_time = self.director_time;
        for p in players
            .players
            .iter()
            .filter(|p| p.authenticated && p.is_alive)
        {
            if let Some(idx) = self.region_index_for(p.position) {
                self.regions[idx].player_count += 1;
                self.regions[idx].last_player_time = director_time;
            }
        }
    }

    fn select_spawn_position(
        &self,
        monsters: &MonsterManager,
        players: &PlayerManager,
        rng: &mut Pcg32,
    ) -> Option<Vec2> {
        let alive_players: Vec<&crate::player::PlayerState> = players
            .players
            .iter()
            .filter(|p| p.authenticated && p.is_alive)
            .collect();
        if alive_players.is_empty() {
            return None;
        }
        // The visibility gate counts EVERY alive player, including pre-auth connections
        // (GDScript parity: a monster must not pop within sight of a just-spawned body).
        let visibility: Vec<Vec2> = players
            .players
            .iter()
            .filter(|p| p.is_alive)
            .map(|p| p.position)
            .collect();

        // Layer 0: fixed anchors.
        if let Some(p) = self.select_anchor_position(monsters, &visibility, rng) {
            return Some(p);
        }

        // Budget split between the procedural layers.
        let cap = MONSTER_MAX_COUNT as i64;
        let regional_budget = ((MONSTER_MAX_COUNT as f64 * MONSTER_REGIONAL_SPAWN_RATIO).round()
            as i64)
            .clamp(0, cap);
        let encounter_budget = cap - regional_budget;
        let (regional_count, encounter_count) = self.count_alive_by_layer(monsters, &alive_players);
        let regional_deficit = regional_budget - regional_count as i64;
        let encounter_deficit = encounter_budget - encounter_count as i64;

        let mut prefer_regional = regional_deficit > encounter_deficit;
        if regional_deficit > 0 && encounter_deficit > 0 {
            prefer_regional = rng.randf() < MONSTER_REGIONAL_SPAWN_RATIO;
        }

        let primary = if prefer_regional {
            self.select_regional_position(monsters, &visibility, rng)
        } else {
            self.select_encounter_position(monsters, &alive_players, &visibility, rng)
        };
        if primary.is_some() {
            return primary;
        }
        if prefer_regional {
            self.select_encounter_position(monsters, &alive_players, &visibility, rng)
        } else {
            self.select_regional_position(monsters, &visibility, rng)
        }
    }

    fn select_anchor_position(
        &self,
        monsters: &MonsterManager,
        visibility: &[Vec2],
        rng: &mut Pcg32,
    ) -> Option<Vec2> {
        let anchors: Vec<Vec2> = ARENA_MONSTER_SPAWNS
            .iter()
            .copied()
            .filter(|p| arena::is_valid_monster_spawn_position(*p))
            .collect();
        if anchors.is_empty() {
            return None;
        }
        let start = rng.rand_index(anchors.len());
        for i in 0..anchors.len() {
            let pos = anchors[(start + i) % anchors.len()];
            if self.is_valid_spawn_position(pos, monsters, visibility) {
                return Some(pos);
            }
        }
        None
    }

    fn select_encounter_position(
        &self,
        monsters: &MonsterManager,
        alive_players: &[&crate::player::PlayerState],
        visibility: &[Vec2],
        rng: &mut Pcg32,
    ) -> Option<Vec2> {
        for _ in 0..MONSTER_SPAWN_ATTEMPTS {
            let target = alive_players[rng.rand_index(alive_players.len())];
            let angle = rng.randf() * std::f64::consts::TAU;
            let distance = rng.randf_range(
                MONSTER_SPAWN_MIN_DISTANCE as f64,
                MONSTER_SPAWN_MAX_DISTANCE as f64,
            );
            let pos = target.position
                + Vec2::new(angle.cos() as f32, angle.sin() as f32) * distance as f32;
            if self.is_valid_spawn_position(pos, monsters, visibility) {
                return Some(pos);
            }
        }
        None
    }

    fn select_regional_position(
        &self,
        monsters: &MonsterManager,
        visibility: &[Vec2],
        rng: &mut Pcg32,
    ) -> Option<Vec2> {
        let counts = self.count_alive_by_region(monsters);
        // score + jitter, sort descending, ties ascending by index.
        let mut ranked: Vec<(usize, f64)> = self
            .regions
            .iter()
            .enumerate()
            .map(|(i, r)| (i, self.score_region(r, counts[i]) + rng.randf()))
            .collect();
        ranked.sort_by(|a, b| {
            b.1.partial_cmp(&a.1)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then(a.0.cmp(&b.0))
        });
        for (idx, _) in ranked {
            let rect = &self.regions[idx].rect;
            for _ in 0..MONSTER_SPAWN_REGION_CANDIDATES {
                let pos = Vec2::new(
                    rng.randf_range(
                        rect.position.x as f64,
                        (rect.position.x + rect.size.x) as f64,
                    ) as f32,
                    rng.randf_range(
                        rect.position.y as f64,
                        (rect.position.y + rect.size.y) as f64,
                    ) as f32,
                );
                if self.is_valid_spawn_position(pos, monsters, visibility) {
                    return Some(pos);
                }
            }
        }
        None
    }

    fn score_region(&self, region: &SpawnRegion, count: usize) -> f64 {
        if count >= MONSTER_SPAWN_REGION_SOFT_CAP {
            return -1000.0 - count as f64;
        }
        let target = (1 + region.player_count).min(MONSTER_SPAWN_REGION_SOFT_CAP);
        let deficit = target.saturating_sub(count) as f64;
        let time_since_visit = (self.director_time - region.last_player_time).clamp(0.0, 120.0);
        deficit * 100.0 + time_since_visit * 0.2 + region.player_count as f64 * 20.0
            - count as f64 * 25.0
    }

    fn count_alive_by_region(&self, monsters: &MonsterManager) -> [usize; 16] {
        let mut counts = [0usize; 16];
        for m in monsters.monsters.iter().filter(|m| m.is_alive) {
            if let Some(idx) = self.region_index_for(m.position) {
                counts[idx] += 1;
            }
        }
        counts
    }

    /// Encounter = within the GLOBAL detection range (650, not difficulty-scaled) of any alive
    /// player; else regional.
    fn count_alive_by_layer(
        &self,
        monsters: &MonsterManager,
        alive_players: &[&crate::player::PlayerState],
    ) -> (usize, usize) {
        let range_sq = MONSTER_DETECTION_RANGE * MONSTER_DETECTION_RANGE;
        let mut regional = 0;
        let mut encounter = 0;
        for m in monsters.monsters.iter().filter(|m| m.is_alive) {
            let near = alive_players
                .iter()
                .any(|p| p.position.distance_squared_to(m.position) <= range_sq);
            if near {
                encounter += 1;
            } else {
                regional += 1;
            }
        }
        (regional, encounter)
    }

    /// Validity: in bounds → not in a (global-radius) expanded obstacle → spawn separation →
    /// not visible to any alive player (strict <; includes pre-auth bodies).
    fn is_valid_spawn_position(
        &self,
        pos: Vec2,
        monsters: &MonsterManager,
        visibility: &[Vec2],
    ) -> bool {
        if !arena::is_within_bounds(pos) {
            return false;
        }
        if arena::circle_intersects_obstacle(pos, MONSTER_HITBOX_RADIUS) {
            return false;
        }
        if let Some(d_sq) = monsters.closest_alive_distance_sq(pos) {
            if d_sq < MONSTER_SPAWN_SEPARATION * MONSTER_SPAWN_SEPARATION {
                return false;
            }
        }
        for p in visibility {
            if p.distance_to(pos) < MONSTER_VISIBILITY_RADIUS {
                return false;
            }
        }
        true
    }
}

// ── AI ──────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy)]
pub struct FireEvent {
    pub source_id: u16,
    /// Always non-zero — D11 carried-forward invariant #3.
    pub projectile_id: u16,
}

pub struct MonsterAi {
    pub difficulty: f64,
}

impl MonsterAi {
    pub fn new(difficulty: f64) -> Self {
        Self {
            difficulty: difficulty.clamp(0.0, 1.0),
        }
    }

    // Difficulty-scaled effective values (unclamped lerps — extraction monsters §2.4).
    fn retarget_interval(&self, def: &MonsterDefinition) -> f64 {
        lerp(def.retarget_interval * 1.35, 0.28, self.difficulty)
    }
    fn detection_range(&self, def: &MonsterDefinition) -> f32 {
        lerp(
            def.detection_range as f64 * 0.8,
            def.lose_interest_range as f64,
            self.difficulty,
        ) as f32
    }
    fn lose_interest_distance(&self, def: &MonsterDefinition) -> f32 {
        lerp(
            def.lose_interest_range as f64 * 0.85,
            def.lose_interest_range as f64 * 1.25,
            self.difficulty,
        ) as f32
    }
    fn attack_range(&self, def: &MonsterDefinition) -> f32 {
        let cap = (PROJECTILE_MAX_DISTANCE as f64 * 0.72).min(540.0);
        lerp(def.attack_range as f64, cap, self.difficulty) as f32
    }
    fn flee_distance(&self, def: &MonsterDefinition) -> f32 {
        lerp(
            def.flee_distance as f64 * 0.75,
            def.flee_distance as f64 * 1.75,
            self.difficulty,
        ) as f32
    }
    fn preferred_distance(&self, def: &MonsterDefinition) -> f32 {
        lerp(def.preferred_distance as f64, 340.0, self.difficulty) as f32
    }

    /// Per-tick driver over alive monsters in registry order. Returns fire events.
    #[allow(clippy::too_many_arguments)]
    pub fn update_all(
        &self,
        monsters: &mut MonsterManager,
        players: &PlayerManager,
        projectiles: &mut ProjectileManager,
        delta: f64,
        now_ms: u64,
        rng: &mut Pcg32,
    ) -> Vec<FireEvent> {
        let mut events = Vec::new();
        for i in 0..monsters.monsters.len() {
            if !monsters.monsters[i].is_alive {
                continue;
            }
            if self.update_monster(
                &mut monsters.monsters[i],
                players,
                projectiles,
                delta,
                now_ms,
                rng,
            ) {
                let m = &monsters.monsters[i];
                events.push(FireEvent {
                    source_id: m.entity_id,
                    projectile_id: m.last_fired_projectile_id,
                });
            }
        }
        events
    }

    fn update_monster(
        &self,
        monster: &mut MonsterState,
        players: &PlayerManager,
        projectiles: &mut ProjectileManager,
        delta: f64,
        now_ms: u64,
        rng: &mut Pcg32,
    ) -> bool {
        if monster.definition.ai_profile == "stationary_dummy" {
            monster.update_timers(delta);
            monster.target_id = 0;
            monster.move_direction = Vec2::ZERO;
            monster.ai_state = AiState::Idle;
            monster.entity_flags &= !(entity_flags::MOVING | entity_flags::ATTACKING);
            monster.animation_state = anim::IDLE;
            return false;
        }

        monster.update_timers(delta);

        // Rogue Stealth: a monster actively drops aggro the moment its target turns invisible.
        if monster.target_id != 0 {
            if let Some(t) = players.get_by_entity_id(monster.target_id) {
                if t.entity_flags & entity_flags::STEALTH != 0 {
                    monster.target_id = 0;
                    self.transition(monster, AiState::Idle);
                }
            }
        }

        if monster.target_id == 0
            || monster.retarget_timer >= self.retarget_interval(monster.definition)
        {
            monster.retarget_timer = 0.0;
            self.select_target(monster, players);
        }

        if monster.steering_timer <= 0.0 {
            // Normalized random direction; refresh period 0.35..lerp(1.5, 0.8, d).
            let v = Vec2::new(
                rng.randf_range(-1.0, 1.0) as f32,
                rng.randf_range(-1.0, 1.0) as f32,
            );
            monster.steering_offset = v.normalized();
            monster.steering_timer = rng.randf_range(0.35, lerp(1.5, 0.8, self.difficulty));
        }

        let fired = match monster.ai_state {
            AiState::Idle => {
                self.process_idle(monster, players);
                false
            }
            AiState::Chase => {
                self.process_chase(monster, players, delta);
                false
            }
            AiState::Attack => {
                self.process_attack(monster, players, projectiles, delta, now_ms, rng)
            }
            AiState::Flee => {
                self.process_flee(monster, players, delta, now_ms);
                false
            }
        };

        // Animation sync — overwrites HIT each alive tick.
        monster.animation_state = match monster.ai_state {
            AiState::Idle => anim::IDLE,
            AiState::Chase | AiState::Flee => anim::WALK,
            AiState::Attack => anim::ATTACK,
        };
        fired
    }

    fn transition(&self, monster: &mut MonsterState, new: AiState) {
        if monster.ai_state == new {
            return;
        }
        monster.ai_state = new;
        match new {
            AiState::Attack => {
                monster.attack_timer = 0.0;
                monster.entity_flags |= entity_flags::ATTACKING;
            }
            AiState::Idle => {
                monster.move_direction = Vec2::ZERO;
                monster.entity_flags &= !(entity_flags::MOVING | entity_flags::ATTACKING);
            }
            AiState::Chase | AiState::Flee => {
                monster.entity_flags &= !entity_flags::ATTACKING;
            }
        }
    }

    /// Threat-scored target selection with detection/lose-interest hysteresis. The "drop on
    /// lose-interest" branch is effectively dead code (every too-far player scores −INF and the
    /// strict `>` never selects) — observable behavior: a targeted monster never goes idle from
    /// distance alone. Ported as-is (extraction monsters §5.3).
    fn select_target(&self, monster: &mut MonsterState, players: &PlayerManager) {
        let alive: Vec<&crate::player::PlayerState> = players
            .players
            .iter()
            .filter(|p| p.authenticated && p.is_alive)
            .collect();
        if alive.is_empty() {
            monster.target_id = 0;
            self.transition(monster, AiState::Idle);
            return;
        }
        let mut best: Option<&crate::player::PlayerState> = None;
        let mut best_score = f64::NEG_INFINITY;
        for p in &alive {
            let score = self.score_target(monster, p);
            if score > best_score {
                best_score = score;
                best = Some(p);
            }
        }
        let Some(best) = best else {
            return; // all scored −INF: KEEP the current target unchanged
        };
        let dist_sq = (best.position - monster.position).length_squared();
        let detection = self.detection_range(monster.definition);
        let lose = self.lose_interest_distance(monster.definition);
        if dist_sq <= detection * detection {
            monster.target_id = best.entity_id;
        } else if dist_sq > lose * lose {
            monster.target_id = 0;
            self.transition(monster, AiState::Idle);
        }
        // else: hysteresis band — target unchanged.
    }

    fn score_target(&self, monster: &MonsterState, player: &crate::player::PlayerState) -> f64 {
        if !player.is_alive {
            return f64::NEG_INFINITY;
        }
        // Rogue Stealth is invisible to AI targeting (it can still be hit by projectiles it walks
        // into — stealth only affects targeting, not collision).
        if player.entity_flags & entity_flags::STEALTH != 0 {
            return f64::NEG_INFINITY;
        }
        let def = monster.definition;
        let distance = (monster.position - player.position).length() as f64;
        if distance > self.lose_interest_distance(def) as f64 {
            return f64::NEG_INFINITY;
        }
        let distance_score =
            (1.0 - distance / self.detection_range(def) as f64).clamp(0.0, 1.0) * 45.0;
        let close_threat =
            (1.0 - distance / (self.attack_range(def) as f64).max(1.0)).clamp(0.0, 1.0) * 25.0;
        let movement_threat =
            (player.velocity.length() as f64 / PLAYER_SPRINT_SPEED).clamp(0.0, 1.0) * 10.0;
        let shooting_threat = if player.is_shoot_held() { 18.0 } else { 0.0 };
        let weakened_bonus = (1.0 - player.health as f64 / (player.max_health as f64).max(1.0))
            .clamp(0.0, 1.0)
            * 8.0;
        let stickiness = if player.entity_id == monster.target_id {
            18.0 * (0.5 + self.difficulty * 0.5)
        } else {
            0.0
        };
        35.0 + distance_score
            + close_threat
            + movement_threat
            + shooting_threat
            + weakened_bonus
            + stickiness
    }

    fn target<'a>(
        &self,
        monster: &MonsterState,
        players: &'a PlayerManager,
    ) -> Option<&'a crate::player::PlayerState> {
        if monster.target_id == 0 {
            return None;
        }
        players.get_by_entity_id(monster.target_id)
    }

    fn process_idle(&self, monster: &mut MonsterState, players: &PlayerManager) {
        monster.move_direction = Vec2::ZERO;
        monster.entity_flags &= !entity_flags::MOVING;
        if monster.target_id != 0 {
            if let Some(t) = self.target(monster, players) {
                if t.is_alive {
                    self.transition(monster, AiState::Chase);
                }
            }
        }
    }

    fn process_chase(&self, monster: &mut MonsterState, players: &PlayerManager, delta: f64) {
        let Some(target) = self.target(monster, players).filter(|t| t.is_alive) else {
            monster.target_id = 0;
            self.transition(monster, AiState::Idle);
            return;
        };
        let to_target = target.position - monster.position;
        let distance = to_target.length();
        if distance < self.flee_distance(monster.definition) {
            self.transition(monster, AiState::Flee);
            return;
        }
        if distance <= self.attack_range(monster.definition) {
            self.transition(monster, AiState::Attack);
            return;
        }
        monster.move_direction = self.apply_steering(monster, to_target.normalized());
        self.move_monster(monster, delta);
    }

    fn process_attack(
        &self,
        monster: &mut MonsterState,
        players: &PlayerManager,
        projectiles: &mut ProjectileManager,
        delta: f64,
        now_ms: u64,
        rng: &mut Pcg32,
    ) -> bool {
        let Some(target) = self.target(monster, players).filter(|t| t.is_alive) else {
            monster.target_id = 0;
            self.transition(monster, AiState::Idle);
            return false;
        };
        let target_position = target.position;
        let target_velocity = target.velocity;
        let to_target = target_position - monster.position;
        let distance = to_target.length();

        if (distance as f64)
            < self.flee_distance(monster.definition) as f64 * (0.75 + self.difficulty * 0.25)
        {
            self.transition(monster, AiState::Flee);
            return false;
        }
        if distance > self.attack_range(monster.definition) * 1.2 {
            self.transition(monster, AiState::Chase);
            return false;
        }

        // Kite/strafe while attacking.
        let desired = self.combat_move_direction(monster, target_position, distance, now_ms);
        monster.move_direction = self.apply_steering(monster, desired);
        self.move_monster(monster, delta);

        let mut fired = false;
        if monster.can_shoot() {
            let dir = self.predictive_aim_direction(monster, target_position, target_velocity, rng);
            let def = monster.definition;
            let spawn_pos = monster.position + dir * (def.hitbox_radius + PROJECTILE_RADIUS + 2.0);
            if let Some(proj) = projectiles.spawn_projectile(
                monster.entity_id,
                spawn_pos,
                dir,
                0,
                0,
                0,
                def.projectile_speed,
                MONSTER_PROJECTILE_KNOCKBACK_FORCE,
            ) {
                monster.last_fired_projectile_id = proj.entity_id;
                fired = true;
                monster.shoot_cooldown = def.shoot_cooldown;
                monster.attack_timer = def.attack_duration;
            }
        }

        if monster.attack_timer <= 0.0
            && monster.shoot_cooldown <= 0.0
            && distance > self.attack_range(monster.definition)
        {
            self.transition(monster, AiState::Chase);
        }
        fired
    }

    fn process_flee(
        &self,
        monster: &mut MonsterState,
        players: &PlayerManager,
        delta: f64,
        now_ms: u64,
    ) {
        let Some(target) = self.target(monster, players).filter(|t| t.is_alive) else {
            monster.target_id = 0;
            self.transition(monster, AiState::Idle);
            return;
        };
        let to_target = target.position - monster.position;
        let distance = to_target.length();
        if distance >= self.preferred_distance(monster.definition) {
            let next = if distance <= self.attack_range(monster.definition) {
                AiState::Attack
            } else {
                AiState::Chase
            };
            self.transition(monster, next);
            return;
        }
        let flee_direction = -to_target.normalized();
        let strafe = perp(flee_direction) * self.strafe_sign(monster, now_ms);
        let combined =
            (flee_direction + strafe * ((0.25 + self.difficulty * 0.45) as f32)).normalized();
        monster.move_direction = self.apply_steering(monster, combined);
        self.move_monster(monster, delta);
    }

    fn apply_steering(&self, monster: &MonsterState, desired: Vec2) -> Vec2 {
        if is_zero_approx(desired) {
            return Vec2::ZERO;
        }
        let def = monster.definition;
        let randomness = def.steering_randomness * lerp(1.25, 0.35, self.difficulty);
        let mut steered = desired + monster.steering_offset * randomness as f32;

        // Boundary reflection on a lookahead probe.
        let future = monster.position + steered * def.avoidance_distance;
        if !arena::is_within_bounds(future) {
            if future.x < MAP_MIN.x || future.x > MAP_MAX.x {
                steered.x = -steered.x;
            }
            if future.y < MAP_MIN.y || future.y > MAP_MAX.y {
                steered.y = -steered.y;
            }
        }
        if arena::circle_intersects_obstacle(future, def.hitbox_radius) {
            steered = self.find_clear_steering_direction(monster, steered.normalized());
        }
        steered.normalized()
    }

    fn find_clear_steering_direction(&self, monster: &MonsterState, desired: Vec2) -> Vec2 {
        use std::f32::consts::{FRAC_PI_2, FRAC_PI_4, PI};
        let def = monster.definition;
        let mut best_direction = -desired;
        let mut best_clearance = -1.0f32;
        for offset in [FRAC_PI_4, -FRAC_PI_4, FRAC_PI_2, -FRAC_PI_2, PI] {
            let candidate = rotated(desired, offset).normalized();
            let probe = monster.position + candidate * def.avoidance_distance;
            let mut clearance = if arena::circle_intersects_obstacle(probe, def.hitbox_radius) {
                0.0
            } else {
                1.0
            };
            clearance +=
                ((probe - monster.position).length() / def.avoidance_distance).clamp(0.0, 1.0);
            if clearance > best_clearance {
                best_clearance = clearance;
                best_direction = candidate;
            }
        }
        best_direction
    }

    fn move_monster(&self, monster: &mut MonsterState, delta: f64) {
        if is_zero_approx(monster.move_direction) {
            monster.entity_flags &= !entity_flags::MOVING;
            return;
        }
        let velocity = monster.move_direction * monster.definition.move_speed;
        let new_position = monster.position + velocity * delta as f32;
        monster.position = arena::move_with_obstacle_collision(
            monster.position,
            new_position,
            monster.definition.hitbox_radius,
        );
        monster.entity_flags |= entity_flags::MOVING;
    }

    fn combat_move_direction(
        &self,
        monster: &MonsterState,
        target_position: Vec2,
        distance: f32,
        now_ms: u64,
    ) -> Vec2 {
        let to_target = target_position - monster.position;
        if is_zero_approx(to_target) {
            return Vec2::ZERO;
        }
        let toward = to_target.normalized();
        let away = -toward;
        let strafe = perp(toward) * self.strafe_sign(monster, now_ms);
        let preferred = self.preferred_distance(monster.definition);

        let mut radial = Vec2::ZERO;
        if distance < preferred * 0.82 {
            radial = away * ((0.85 + self.difficulty * 0.35) as f32);
        } else if distance > preferred * 1.18 {
            radial = toward * ((0.25 + self.difficulty * 0.25) as f32);
        }
        (strafe * ((0.75 + self.difficulty * 0.45) as f32) + radial).normalized()
    }

    /// 1.4 s flip period with per-entity phase offset. The GDScript used engine-uptime ms;
    /// here it's server-uptime ms — same observable behavior.
    fn strafe_sign(&self, monster: &MonsterState, now_ms: u64) -> f32 {
        let phase = now_ms / 1400 + monster.entity_id as u64;
        if phase.is_multiple_of(2) {
            1.0
        } else {
            -1.0
        }
    }

    fn predictive_aim_direction(
        &self,
        monster: &MonsterState,
        target_position: Vec2,
        target_velocity: Vec2,
        rng: &mut Pcg32,
    ) -> Vec2 {
        let predicted = predict_target_position(
            monster.position,
            target_position,
            target_velocity,
            monster.definition.projectile_speed,
        );
        let mut direction = predicted - monster.position;
        if is_zero_approx(direction) {
            direction = target_position - monster.position;
        }
        if is_zero_approx(direction) {
            direction = Vec2::new(1.0, 0.0);
        }
        let max_error = (1.0 - self.difficulty) * 0.22;
        if max_error > 0.001 {
            direction = rotated(direction, rng.randf_range(-max_error, max_error) as f32);
        }
        direction.normalized()
    }
}

/// Standard projectile-intercept quadratic with the exact GDScript branches.
fn predict_target_position(origin: Vec2, tpos: Vec2, tvel: Vec2, pspeed: f32) -> Vec2 {
    let relative = tpos - origin;
    let a = (tvel.length_squared() - pspeed * pspeed) as f64;
    let b = (2.0 * relative.dot(tvel)) as f64;
    let c = relative.length_squared() as f64;
    let mut t = relative.length() as f64 / (pspeed as f64).max(1.0);
    if a.abs() < 0.0001 {
        if b.abs() > 0.0001 {
            let linear_t = -c / b;
            if linear_t > 0.0 {
                t = linear_t;
            }
        }
    } else {
        let disc = b * b - 4.0 * a * c;
        if disc >= 0.0 {
            let root = disc.sqrt();
            let t1 = (-b - root) / (2.0 * a);
            let t2 = (-b + root) / (2.0 * a);
            let mut best = f64::INFINITY;
            if t1 > 0.0 {
                best = best.min(t1);
            }
            if t2 > 0.0 {
                best = best.min(t2);
            }
            if best < f64::INFINITY {
                t = best;
            }
        }
    }
    t = t.clamp(0.0, 2.0);
    tpos + tvel * t as f32
}

fn lerp(a: f64, b: f64, t: f64) -> f64 {
    a + (b - a) * t
}

fn is_zero_approx(v: Vec2) -> bool {
    v.x.abs() < 1e-5 && v.y.abs() < 1e-5
}

fn perp(v: Vec2) -> Vec2 {
    Vec2::new(-v.y, v.x)
}

/// Godot `Vector2.rotated(phi)` — CCW in math coordinates.
fn rotated(v: Vec2, phi: f32) -> Vec2 {
    let (s, c) = (phi.sin(), phi.cos());
    Vec2::new(v.x * c - v.y * s, v.x * s + v.y * c)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// sim_core debug_asserts each thread set its world geometry before any bounds/obstacle read
    /// (arena.rs contract). Each libtest test is its own thread — apply the Arena geometry first.
    fn init_arena_geometry() {
        sim_core::set_world_geometry(
            sim_core::constants::MAP_MIN,
            sim_core::constants::MAP_MAX,
            true,
        );
    }

    fn world_with_player(pos: Vec2) -> PlayerManager {
        init_arena_geometry();
        let mut players = PlayerManager::new();
        let p = players.add_player(1).unwrap();
        p.authenticated = true;
        p.position = pos;
        players
    }

    #[test]
    fn monster_fires_with_nonzero_projectile_id() {
        let ai = MonsterAi::new(0.85);
        let mut monsters = MonsterManager::new();
        let mut projectiles = ProjectileManager::new();
        let mut rng = Pcg32::new(42);
        // Player inside attack range; monster idle with a fresh target.
        let players = world_with_player(Vec2::new(100.0, -600.0));
        monsters.spawn_monster(Vec2::new(0.0, -600.0), "toxic_slime");
        let mut fired_events = Vec::new();
        for _ in 0..120 {
            let ev = ai.update_all(
                &mut monsters,
                &players,
                &mut projectiles,
                1.0 / 30.0,
                0,
                &mut rng,
            );
            fired_events.extend(ev);
        }
        assert!(
            !fired_events.is_empty(),
            "monster should have fired within 4 s"
        );
        for e in &fired_events {
            assert!(
                e.projectile_id >= 10000,
                "D11 invariant: non-zero projectile id"
            );
            assert!(e.source_id >= 30000);
        }
        // Monster projectile speed override: 300, not 400.
        assert!(projectiles.projectiles.iter().all(|p| p.speed == 300.0));
    }

    #[test]
    fn targeted_monster_never_drops_target_by_distance() {
        let ai = MonsterAi::new(0.85);
        let mut monsters = MonsterManager::new();
        let mut projectiles = ProjectileManager::new();
        let mut rng = Pcg32::new(7);
        let mut players = world_with_player(Vec2::new(100.0, 0.0));
        // Use a clear spot away from obstacles.
        monsters.spawn_monster(Vec2::new(300.0, -600.0), "toxic_slime");
        players.players[0].position = Vec2::new(350.0, -600.0);
        ai.update_all(
            &mut monsters,
            &players,
            &mut projectiles,
            1.0 / 30.0,
            0,
            &mut rng,
        );
        assert_ne!(monsters.monsters[0].target_id, 0);
        // Teleport the player far away — beyond lose-interest.
        players.players[0].position = Vec2::new(-999.0, 999.0);
        for _ in 0..120 {
            ai.update_all(
                &mut monsters,
                &players,
                &mut projectiles,
                1.0 / 30.0,
                0,
                &mut rng,
            );
        }
        // Dead-code lose-interest: target retained, monster keeps chasing (extraction §5.3).
        assert_ne!(monsters.monsters[0].target_id, 0);
        assert_eq!(monsters.monsters[0].ai_state, AiState::Chase);
    }

    #[test]
    fn dummy_profile_stays_idle() {
        let ai = MonsterAi::new(0.85);
        let mut monsters = MonsterManager::new();
        let mut projectiles = ProjectileManager::new();
        let mut rng = Pcg32::new(1);
        let players = world_with_player(Vec2::new(10.0, -600.0));
        monsters.spawn_monster(Vec2::new(0.0, -600.0), "target_dummy");
        for _ in 0..60 {
            let ev = ai.update_all(
                &mut monsters,
                &players,
                &mut projectiles,
                1.0 / 30.0,
                0,
                &mut rng,
            );
            assert!(ev.is_empty());
        }
        assert_eq!(monsters.monsters[0].ai_state, AiState::Idle);
        assert_eq!(monsters.monsters[0].position, Vec2::new(0.0, -600.0));
    }

    #[test]
    fn spawner_respects_visibility_and_cap() {
        let mut spawner = MonsterSpawner::new(100.0); // very fast for the test
        let mut monsters = MonsterManager::new();
        let players = world_with_player(Vec2::new(0.0, 0.0));
        let mut rng = Pcg32::new(99);
        for _ in 0..300 {
            spawner.update(1.0 / 30.0, &mut monsters, &players, &mut rng);
        }
        assert!(monsters.alive_count() <= MONSTER_MAX_COUNT);
        assert!(monsters.alive_count() > 0);
        for m in &monsters.monsters {
            let d = m.position.distance_to(Vec2::ZERO);
            assert!(
                d >= MONSTER_VISIBILITY_RADIUS,
                "spawned visible to player at {d}"
            );
        }
    }

    #[test]
    fn take_damage_two_hits_kill_slime() {
        let mut m = MonsterState::new(30000, Vec2::ZERO, &TOXIC_SLIME);
        assert!(!m.take_damage(25));
        assert_eq!(m.animation_state, anim::HIT);
        assert!(m.take_damage(25));
        assert!(!m.is_alive);
        assert_eq!(m.animation_state, anim::DEATH);
        assert_eq!(m.entity_flags, entity_flags::VISIBLE);
    }

    #[test]
    fn monster_id_allocation_wraps_and_recycles() {
        let mut mgr = MonsterManager::new();
        let a = mgr
            .spawn_monster(Vec2::ZERO, "toxic_slime")
            .unwrap()
            .entity_id;
        let b = mgr
            .spawn_monster(Vec2::ZERO, "toxic_slime")
            .unwrap()
            .entity_id;
        assert_eq!(a, 30000);
        assert_eq!(b, 30001);
        mgr.get_mut(a).unwrap().is_alive = false;
        mgr.cleanup_dead_monsters();
        let c = mgr
            .spawn_monster(Vec2::ZERO, "toxic_slime")
            .unwrap()
            .entity_id;
        assert_eq!(c, 30002, "freed ids recycle only after cursor wraparound");
    }
}
