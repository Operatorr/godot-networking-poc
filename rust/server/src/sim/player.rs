//! Server-side player state + manager — port of `player_state.gd` / `player_manager.gd`
//! (extraction sim-movement §4.7, lifecycle §3/§4).

use crate::ability;
use protocol::types::{anim, entity_flags};
use sim_core::constants::*;
use sim_core::progression;
use sim_core::{arena, input_flags as inflag, step_movement, MoveState, MovementSm, Vec2};

pub type PeerKey = usize;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifeState {
    Alive,
    Dead,
    Invulnerable,
}

/// One drained PLAYER_INPUT packet, pre-converted from the wire.
#[derive(Debug, Clone)]
pub struct QueuedInput {
    pub input_flags: u16,
    pub sequence: u8,
    pub aim_angle: f64,
    pub position: Vec2,
    /// Mouse world position — the target for cursor-aimed abilities.
    pub cursor: Vec2,
    pub client_render_tick: u16,
    pub client_rtt_ms: u16,
}

/// A rising-edge SHOOT captured at ingest (extraction combat §4.4a).
#[derive(Debug, Clone)]
pub struct PendingShot {
    pub aim_angle: f64,
    /// `None` = the Vector2.INF "absent" sentinel.
    pub client_position: Option<Vec2>,
    pub client_render_tick: u16,
    pub client_rtt_ms: u16,
}

#[derive(Debug, Clone)]
pub struct Validation {
    #[allow(dead_code)] // carried for diagnostics parity with the GDScript move_results
    pub deviation: f32,
    pub correction_needed: bool,
    pub server_position: Vec2,
    pub cheat_detected: bool,
    pub sequence: u8,
}

pub struct PlayerState {
    pub peer: PeerKey,
    pub entity_id: u16,
    pub character_id: u32,
    pub character_name: String,
    pub player_color: (u8, u8, u8),
    /// Player class (0=Zealot … 6=Mage). Identity metadata from ConnectAuth, clamped on join
    /// (> 6 → 0); not validated against account data yet.
    pub player_class: u8,
    pub bandwidth_budget_bps: u32,
    pub max_snapshot_bytes: usize,
    pub authenticated: bool,

    pub position: Vec2,
    pub velocity: Vec2,
    pub aim_angle: f64,
    pub movement_sm: MovementSm,

    pub input_flags: u16,
    pub last_input_sequence: u8,
    pub last_client_render_tick: u16,
    pub last_client_rtt_ms: u16,
    pub last_client_position: Vec2,
    pub has_client_position: bool,
    /// Latest mouse world position (for cursor-aimed ability dispatch).
    pub last_cursor: Vec2,
    pub last_input_received_tick: u64,
    pub pending_dash: bool,
    pub input_queue: Vec<QueuedInput>,
    pub pending_shots: Vec<PendingShot>,

    pub health: i32,
    pub max_health: i32,
    pub is_alive: bool,
    pub life_state: LifeState,
    pub shoot_cooldown: f64,
    pub invulnerability_timer: f64,
    pub respawn_timer: f64,
    pub pvp_kills: u32,
    pub monster_kills: u32,
    pub deaths: u32,
    pub last_killer_id: i32,

    // ── Server-authoritative progression (hydrated from the Go API on join, written back) ──
    pub level: u16,
    pub experience: u32,
    /// Hardcore = permadeath: death converts XP→Glory and deletes the character (vs softcore
    /// respawn). Hydrated from the character's `mode`.
    pub mode_hardcore: bool,
    /// Set whenever level/XP changed and the API write-back is pending.
    pub progression_dirty: bool,
    /// True once the async hydrate from the API has applied (so we don't write back placeholder
    /// level-1 state over a real character before it loads).
    pub progression_hydrated: bool,
    /// True once a hardcore death has been reported to the API (one-shot Glory/permadeath).
    pub death_reported: bool,

    // ── Survival ──
    /// Fractional HP regen carry (HP is integer; regen scales with level).
    pub health_regen_accum: f64,
    /// Rogue Stealth: while > 0 the player is invisible to AI targeting.
    pub stealth_timer: f64,

    pub animation_state: u8,
    pub entity_flags: u16,
}

impl PlayerState {
    pub fn new(peer: PeerKey, entity_id: u16, spawn: Vec2) -> Self {
        Self {
            peer,
            entity_id,
            character_id: 0,
            character_name: String::new(),
            player_color: (69, 135, 255), // Color(0.27, 0.53, 1.0) quantized
            player_class: 0,              // Zealot
            bandwidth_budget_bps: 0,
            max_snapshot_bytes: 0,
            authenticated: false,
            position: spawn,
            velocity: Vec2::ZERO,
            aim_angle: 0.0,
            movement_sm: MovementSm::new(),
            input_flags: 0,
            last_input_sequence: 0,
            last_client_render_tick: 0,
            last_client_rtt_ms: 0,
            last_client_position: Vec2::ZERO,
            has_client_position: false,
            last_cursor: Vec2::ZERO,
            last_input_received_tick: 0,
            pending_dash: false,
            input_queue: Vec::new(),
            pending_shots: Vec::new(),
            health: 100,
            max_health: 100,
            is_alive: true,
            life_state: LifeState::Alive,
            shoot_cooldown: 0.0,
            invulnerability_timer: 0.0,
            respawn_timer: 0.0,
            pvp_kills: 0,
            monster_kills: 0,
            deaths: 0,
            last_killer_id: -1,
            level: 1,
            experience: 0,
            mode_hardcore: false,
            progression_dirty: false,
            progression_hydrated: false,
            death_reported: false,
            health_regen_accum: 0.0,
            stealth_timer: 0.0,
            animation_state: anim::IDLE,
            entity_flags: entity_flags::ALIVE | entity_flags::VISIBLE,
        }
    }

    /// Apply the class + level: recompute the level-scaled max HP / base move speed / primary
    /// damage and push the per-class ability config into the shared MovementSm (so prediction
    /// matches). Called on auth, on hydrate, and on every level-up. Raising the HP cap also raises
    /// current HP by the same delta (a level-up partially heals); the cap never lowers current HP.
    pub fn apply_class_and_level(&mut self, class: u8, level: u16, experience: u32) {
        self.player_class = if class > 6 { 0 } else { class };
        self.level = level.clamp(1, progression::MAX_PLAYER_LEVEL);
        self.experience = experience;
        let new_max = ability::effective_max_health(self.player_class, self.level).max(1);
        let delta = new_max - self.max_health;
        self.max_health = new_max;
        if delta > 0 {
            self.health = (self.health + delta).min(new_max);
        } else {
            self.health = self.health.min(new_max);
        }
        let s = ability::stats_for_class(self.player_class);
        self.movement_sm
            .set_base_speed(ability::effective_base_speed(self.player_class, self.level));
        self.movement_sm.set_stamina_regen(s.stamina_regen_per_sec);
        self.movement_sm.set_ability_config(
            s.ability_mana,
            s.ability_cooldown,
            s.charge_speed,
            s.charge_distance,
        );
    }

    /// Class+level-scaled primary-attack damage (used at projectile spawn).
    pub fn primary_damage(&self) -> i32 {
        ability::effective_primary_damage(self.player_class, self.level)
    }

    /// Effective base move speed (for the PROGRESS event's `move_speed_q`).
    pub fn effective_move_speed(&self) -> f64 {
        ability::effective_base_speed(self.player_class, self.level)
    }

    /// Level-scaled health regen: smooth, only while alive and below max. Integer HP via a
    /// fractional accumulator. No regen while dead.
    pub fn update_health_regen(&mut self, delta: f64) {
        if !self.is_alive || self.health >= self.max_health {
            self.health_regen_accum = 0.0;
            return;
        }
        self.health_regen_accum += progression::health_regen_per_sec(self.level) * delta;
        while self.health_regen_accum >= 1.0 && self.health < self.max_health {
            self.health = (self.health + 1).min(self.max_health);
            self.health_regen_accum -= 1.0;
        }
    }

    /// Heal (Healthorb pickup). Clamps to max; no-op while dead. Returns the HP actually restored.
    pub fn heal(&mut self, amount: i32) -> i32 {
        if !self.is_alive || amount <= 0 || self.health >= self.max_health {
            return 0;
        }
        let before = self.health;
        self.health = (self.health + amount).min(self.max_health);
        self.health - before
    }

    /// Start (or refresh) Rogue Stealth.
    pub fn enter_stealth(&mut self, duration: f64) {
        self.stealth_timer = self.stealth_timer.max(duration);
    }

    pub fn is_stealthed(&self) -> bool {
        self.stealth_timer > 0.0
    }

    /// Stealth ends early when the Rogue deals damage (cast/shoot) — call on any offensive action.
    pub fn break_stealth(&mut self) {
        self.stealth_timer = 0.0;
    }

    pub fn update_stealth(&mut self, delta: f64) {
        if self.stealth_timer > 0.0 {
            self.stealth_timer = (self.stealth_timer - delta).max(0.0);
        }
    }

    /// Queue cap 10, drop-OLDEST on overflow.
    pub fn queue_input(&mut self, input: QueuedInput) {
        if self.input_queue.len() >= MAX_INPUT_QUEUE_SIZE {
            self.input_queue.remove(0);
        }
        self.input_queue.push(input);
    }

    /// Ingest one drained packet (extraction sim-movement §4.7.1). Dead players discard input
    /// entirely; SHOOT rising edges (vs the running persistent flags) queue pending shots; DASH
    /// latches across same-tick overwrites; the LAST packet's flags persist.
    pub fn ingest_input(&mut self, input: &QueuedInput, server_tick: u64) {
        if self.life_state == LifeState::Dead {
            return;
        }
        let was_shooting = self.input_flags & inflag::SHOOT != 0;
        let is_shooting = input.input_flags & inflag::SHOOT != 0;
        if is_shooting && !was_shooting {
            self.pending_shots.push(PendingShot {
                aim_angle: input.aim_angle,
                client_position: Some(input.position),
                client_render_tick: input.client_render_tick,
                client_rtt_ms: input.client_rtt_ms,
            });
        }
        if input.input_flags & inflag::DASH != 0 {
            self.pending_dash = true;
        }
        self.input_flags = input.input_flags;
        self.last_input_sequence = input.sequence;
        self.aim_angle = input.aim_angle;
        self.last_client_render_tick = input.client_render_tick;
        self.last_client_rtt_ms = input.client_rtt_ms;
        self.last_input_received_tick = server_tick;
        self.last_client_position = input.position;
        self.last_cursor = input.cursor;
        self.has_client_position = true;
    }

    /// One movement step per tick (extraction sim-movement §4.7.2). Exact order preserved.
    pub fn step(&mut self, delta: f64, server_tick: u64) -> Validation {
        // 1. Stale input: flags zero after >6 ticks of silence (fresh connect/respawn exempt).
        if self.last_input_received_tick > 0
            && server_tick - self.last_input_received_tick > STALE_INPUT_TICK_LIMIT
        {
            self.input_flags = 0;
        }

        // 2. Dead: frozen, synthetic valid result.
        if self.life_state == LifeState::Dead {
            self.velocity = Vec2::ZERO;
            self.input_flags = 0;
            self.pending_dash = false;
            self.update_entity_flags();
            return Validation {
                deviation: 0.0,
                correction_needed: false,
                server_position: self.position,
                cheat_detected: false,
                sequence: self.last_input_sequence,
            };
        }

        // 3. Shoot cooldown decrement.
        if self.shoot_cooldown > 0.0 {
            self.shoot_cooldown = (self.shoot_cooldown - delta).max(0.0);
        }

        // 4. Active input breaks invulnerability (movement or SHOOT only).
        if self.life_state == LifeState::Invulnerable && self.has_active_input() {
            self.end_invulnerability();
        }

        // 5. Dash held = wire bit OR the latch; latch consumed exactly once.
        let dash_held = self.input_flags & inflag::DASH != 0 || self.pending_dash;
        self.pending_dash = false;

        // 6–9. SM tick → mover → realized velocity.
        let move_dir = sim_core::movement_direction(self.input_flags);
        let result = step_movement(
            &mut self.movement_sm,
            self.position,
            delta,
            move_dir,
            self.input_flags & inflag::SPRINT != 0,
            dash_held,
            self.input_flags & inflag::ABILITY != 0,
            self.input_flags & inflag::SHOOT != 0,
            Vec2::from_angle(self.aim_angle),
        );
        self.velocity = result.velocity;
        let server_position = result.position;
        self.position = server_position;

        // 10. Validation against the client's latest reported position.
        let validation = if self.has_client_position {
            let deviation = self.last_client_position.distance_to(server_position);
            let (correction_needed, cheat_detected) = if deviation > TELEPORT_THRESHOLD {
                (true, true)
            } else if deviation > CORRECTION_THRESHOLD {
                (true, false)
            } else {
                (false, false)
            };
            Validation {
                deviation,
                correction_needed,
                server_position,
                cheat_detected,
                sequence: self.last_input_sequence,
            }
        } else {
            Validation {
                deviation: 0.0,
                correction_needed: false,
                server_position,
                cheat_detected: false,
                sequence: self.last_input_sequence,
            }
        };

        // 11. Animation + flags.
        self.update_animation_state();
        self.update_entity_flags();
        validation
    }

    /// Movement or SHOOT input — sprint/dash/ability/interact alone do NOT break invulnerability.
    fn has_active_input(&self) -> bool {
        self.input_flags
            & (inflag::MOVE_UP
                | inflag::MOVE_DOWN
                | inflag::MOVE_LEFT
                | inflag::MOVE_RIGHT
                | inflag::SHOOT)
            != 0
    }

    fn update_animation_state(&mut self) {
        self.animation_state = if !self.is_alive {
            anim::DEATH
        } else if self.input_flags & inflag::SHOOT != 0 {
            anim::ATTACK
        } else if self.velocity.length_squared() > 0.01 {
            if self.input_flags & inflag::SPRINT != 0 {
                anim::RUN
            } else {
                anim::WALK
            }
        } else {
            anim::IDLE
        };
    }

    pub fn update_entity_flags(&mut self) {
        let mut f = 0u16;
        if self.is_alive {
            f |= entity_flags::ALIVE;
        }
        if self.velocity.length_squared() > 0.01 {
            f |= entity_flags::MOVING;
        }
        if self.input_flags & inflag::SHOOT != 0 {
            f |= entity_flags::ATTACKING;
        }
        // Charge-invulnerability is orthogonal to spawn invulnerability (which is broken by input);
        // the Warrior stays invulnerable for the whole charge even while moving.
        if self.life_state == LifeState::Invulnerable || self.movement_sm.is_charging() {
            f |= entity_flags::INVULNERABLE;
        }
        match self.movement_sm.state() {
            MoveState::Dashing | MoveState::Charging => f |= entity_flags::DASHING,
            MoveState::KnockedBack => f |= entity_flags::KNOCKED_BACK,
            MoveState::Stunned => f |= entity_flags::STUNNED,
            _ => {}
        }
        if self.movement_sm.is_dazed() {
            f |= entity_flags::DAZED;
        }
        if self.is_stealthed() {
            f |= entity_flags::STEALTH;
        }
        f |= entity_flags::VISIBLE;
        self.entity_flags = f;
    }

    pub fn can_shoot(&self) -> bool {
        self.authenticated && self.is_alive && self.shoot_cooldown <= 0.0
    }

    pub fn is_shoot_held(&self) -> bool {
        self.input_flags & inflag::SHOOT != 0
    }

    pub fn start_shoot_cooldown(&mut self) {
        self.shoot_cooldown = SHOOT_COOLDOWN;
    }

    /// Synthesized shot input for held auto-fire (extraction combat §4.4b).
    pub fn held_shot_input(&self) -> PendingShot {
        PendingShot {
            aim_angle: self.aim_angle,
            client_position: if self.has_client_position {
                Some(self.last_client_position)
            } else {
                None
            },
            client_render_tick: self.last_client_render_tick,
            client_rtt_ms: self.last_client_rtt_ms,
        }
    }

    /// Integer damage; INVULNERABLE absorbs silently. Returns true iff this killed.
    pub fn take_damage(&mut self, amount: i32, source_id: i32) -> bool {
        if !self.is_alive || amount <= 0 {
            return false;
        }
        // Spawn invulnerability OR an in-progress Warrior charge absorbs damage silently.
        if self.life_state == LifeState::Invulnerable || self.movement_sm.is_charging() {
            return false;
        }
        self.health = (self.health - amount).max(0);
        if self.health <= 0 {
            self.mark_dead(source_id);
            return true;
        }
        self.animation_state = anim::HIT;
        false
    }

    /// One-shot death (extraction combat §4.9). Dead players keep replicating with
    /// flags == VISIBLE and animation DEATH — they are not despawned.
    pub fn mark_dead(&mut self, killer_id: i32) {
        if self.life_state == LifeState::Dead {
            return;
        }
        self.is_alive = false;
        self.life_state = LifeState::Dead;
        self.health = 0;
        self.velocity = Vec2::ZERO;
        self.movement_sm.reset();
        self.input_flags = 0;
        self.input_queue.clear();
        self.pending_shots.clear();
        self.pending_dash = false;
        self.shoot_cooldown = 0.0;
        self.respawn_timer = RESPAWN_DELAY;
        self.deaths += 1;
        self.last_killer_id = killer_id;
        self.stealth_timer = 0.0;
        self.health_regen_accum = 0.0;
        self.animation_state = anim::DEATH;
        self.update_entity_flags();
    }

    pub fn reset_for_respawn(&mut self, spawn: Vec2) {
        self.position = spawn;
        self.velocity = Vec2::ZERO;
        self.health = self.max_health;
        self.is_alive = true;
        self.life_state = LifeState::Invulnerable;
        self.invulnerability_timer = INVULNERABILITY_DURATION;
        self.movement_sm.reset();
        self.respawn_timer = 0.0;
        self.shoot_cooldown = 0.0;
        self.input_flags = 0;
        self.input_queue.clear();
        self.pending_shots.clear();
        self.pending_dash = false;
        self.has_client_position = false;
        self.last_input_received_tick = 0;
        self.last_killer_id = -1;
        self.stealth_timer = 0.0;
        self.health_regen_accum = 0.0;
        self.death_reported = false;
        self.animation_state = anim::SPAWN;
        self.entity_flags =
            entity_flags::ALIVE | entity_flags::VISIBLE | entity_flags::INVULNERABLE;
    }

    /// Timer decrements without clamping (may pass below 0 within the ending tick).
    pub fn update_invulnerability(&mut self, delta: f64) {
        if self.life_state != LifeState::Invulnerable {
            return;
        }
        self.invulnerability_timer -= delta;
        if self.invulnerability_timer <= 0.0 {
            self.end_invulnerability();
        }
    }

    pub fn end_invulnerability(&mut self) {
        if self.life_state != LifeState::Invulnerable {
            return;
        }
        self.life_state = LifeState::Alive;
        self.invulnerability_timer = 0.0;
        self.entity_flags &= !entity_flags::INVULNERABLE;
    }

    pub fn update_respawn_timer(&mut self, delta: f64) {
        if self.life_state != LifeState::Dead {
            return;
        }
        self.respawn_timer = (self.respawn_timer - delta).max(0.0);
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PositionSnapshot {
    pub entity_id: u16,
    pub position: Vec2,
}

pub struct PlayerManager {
    /// Insertion (connect) order — iteration order matches GDScript Dictionary semantics.
    pub players: Vec<PlayerState>,
    /// Spawn anchors for this instance (Arena anchors by default; the Sanctuary sets town anchors).
    spawn_points: Vec<Vec2>,
    position_history: Vec<(u64, Vec<PositionSnapshot>)>,
    /// Deliberate deviation from GDScript (documented in lifecycle §6.1): ids recycle within
    /// 1–999 so the invariant holds for > 999 lifetime connections.
    free_ids: Vec<u16>,
    /// Ids freed since the last snapshot broadcast. Quarantined until the broadcast has built
    /// the REMOVED records: immediate reuse would let a newcomer inherit remote delta caches
    /// (no REMOVED, no FULL — the old player would silently morph into the new one).
    quarantined_ids: Vec<u16>,
    next_entity_id: u16,
    spawn_index: usize,
}

pub const POSITION_HISTORY_TICKS: usize = 8;

impl Default for PlayerManager {
    fn default() -> Self {
        Self::new()
    }
}

impl PlayerManager {
    pub fn new() -> Self {
        Self {
            players: Vec::new(),
            spawn_points: ARENA_PLAYER_SPAWNS.to_vec(),
            position_history: Vec::new(),
            free_ids: Vec::new(),
            quarantined_ids: Vec::new(),
            next_entity_id: 1,
            spawn_index: 0,
        }
    }

    /// Override the spawn anchors (e.g. the Sanctuary's town spawns). Resets the round-robin cursor.
    pub fn set_spawn_points(&mut self, points: Vec<Vec2>) {
        if !points.is_empty() {
            self.spawn_points = points;
            self.spawn_index = 0;
        }
    }

    pub fn add_player(&mut self, peer: PeerKey) -> Option<&mut PlayerState> {
        if self.players.iter().any(|p| p.peer == peer) {
            return self.players.iter_mut().find(|p| p.peer == peer);
        }
        let entity_id = if let Some(id) = self.free_ids.pop() {
            id
        } else if self.next_entity_id <= PLAYER_ENTITY_ID_MAX {
            let id = self.next_entity_id;
            self.next_entity_id += 1;
            id
        } else {
            return None; // 999 concurrent players — beyond POC capacity
        };
        let spawn = self.next_spawn_position();
        self.players.push(PlayerState::new(peer, entity_id, spawn));
        self.players.last_mut()
    }

    pub fn remove_player(&mut self, peer: PeerKey) -> Option<PlayerState> {
        let idx = self.players.iter().position(|p| p.peer == peer)?;
        let state = self.players.remove(idx);
        self.quarantined_ids.push(state.entity_id);
        Some(state)
    }

    /// Call once per snapshot broadcast, AFTER the broadcast: the freed ids' REMOVED records
    /// are now built into every peer's delta cache, so reuse is safe.
    pub fn release_quarantined_ids(&mut self) {
        self.free_ids.append(&mut self.quarantined_ids);
    }

    /// Shared round-robin cursor over the (re-filtered) valid spawn list, used by both
    /// connect-spawns and respawns; never reset.
    pub fn next_spawn_position(&mut self) -> Vec2 {
        let spawns: Vec<Vec2> = self
            .spawn_points
            .iter()
            .copied()
            .filter(|p| arena::is_valid_player_spawn_position(*p))
            .collect();
        if spawns.is_empty() {
            return arena::clamp_to_bounds(Vec2::ZERO);
        }
        let pos = spawns[self.spawn_index % spawns.len()];
        self.spawn_index = (self.spawn_index + 1) % spawns.len();
        pos
    }

    pub fn get(&self, peer: PeerKey) -> Option<&PlayerState> {
        self.players.iter().find(|p| p.peer == peer)
    }

    pub fn get_mut(&mut self, peer: PeerKey) -> Option<&mut PlayerState> {
        self.players.iter_mut().find(|p| p.peer == peer)
    }

    pub fn get_by_entity_id(&self, entity_id: u16) -> Option<&PlayerState> {
        self.players.iter().find(|p| p.entity_id == entity_id)
    }

    pub fn get_by_entity_id_mut(&mut self, entity_id: u16) -> Option<&mut PlayerState> {
        self.players.iter_mut().find(|p| p.entity_id == entity_id)
    }

    pub fn player_count(&self) -> usize {
        self.players.len()
    }

    pub fn queue_player_input(&mut self, peer: PeerKey, input: QueuedInput) {
        if let Some(p) = self.get_mut(peer) {
            if p.authenticated {
                p.queue_input(input);
            }
        }
    }

    /// Tick step 1: drain queues, step movement once per authenticated player, return move
    /// results only for players that had fresh input.
    pub fn process_all_inputs(&mut self, delta: f64, server_tick: u64) -> Vec<MoveResult> {
        let mut results = Vec::new();
        for state in &mut self.players {
            if !state.authenticated {
                continue;
            }
            let had_input = !state.input_queue.is_empty();
            let drained: Vec<QueuedInput> = state.input_queue.drain(..).collect();
            for input in &drained {
                state.ingest_input(input, server_tick);
            }
            let validation = state.step(delta, server_tick);
            if had_input {
                results.push(MoveResult {
                    peer: state.peer,
                    sequence: validation.sequence,
                    position: validation.server_position,
                    success: !validation.correction_needed,
                    cheat_detected: validation.cheat_detected,
                    stamina: protocol::quant_resource(state.movement_sm.stamina()),
                    mana: protocol::quant_resource(state.movement_sm.mana()),
                });
            }
        }
        results
    }

    /// Tick step 4: record authenticated-and-alive player positions (post-movement,
    /// pre-collision), depth 8 ticks.
    pub fn record_position_snapshot(&mut self, server_tick: u64) {
        let snapshot: Vec<PositionSnapshot> = self
            .players
            .iter()
            .filter(|p| p.authenticated && p.is_alive)
            .map(|p| PositionSnapshot {
                entity_id: p.entity_id,
                position: p.position,
            })
            .collect();
        self.position_history.push((server_tick, snapshot));
        while self.position_history.len() > POSITION_HISTORY_TICKS {
            self.position_history.remove(0);
        }
    }

    /// Fallback chain: exact tick → newest ≤ requested → OLDEST stored → live alive players.
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
        self.players
            .iter()
            .filter(|p| p.authenticated && p.is_alive)
            .map(|p| PositionSnapshot {
                entity_id: p.entity_id,
                position: p.position,
            })
            .collect()
    }

    /// Recorded positions oldest-first plus the live position — up to 9 entries (hit
    /// plausibility input).
    pub fn get_recent_positions(&self, entity_id: u16) -> Vec<Vec2> {
        let mut out = Vec::new();
        for (_, snap) in &self.position_history {
            if let Some(s) = snap.iter().find(|s| s.entity_id == entity_id) {
                out.push(s.position);
            }
        }
        if let Some(p) = self.get_by_entity_id(entity_id) {
            out.push(p.position);
        }
        out
    }
}

#[derive(Debug, Clone)]
pub struct MoveResult {
    pub peer: PeerKey,
    pub sequence: u8,
    pub position: Vec2,
    pub success: bool,
    pub cheat_detected: bool,
    pub stamina: u8,
    pub mana: u8,
}
