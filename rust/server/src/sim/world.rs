//! The authoritative world: one instance per process (D13), advanced by the single synchronous
//! tick (D8). Exact tick order ported from `_process_server_tick` (extraction server-tick §4.3):
//! inputs → shoot spawns → confirms → projectiles/spawner/timers → monster AI → position
//! history → collisions → backstop (new, D11) → snapshot broadcast → monster cleanup.

use crate::ability::{self, AbilityKind};
use crate::auth::{region_from_string, TicketVerifier};
use crate::broadcast::{BroadcastService, EntityData};
use crate::combat::{self, Backstop, HitReportLimiter};
use crate::config::ServerConfig;
use crate::leaderboard::Leaderboard;
use crate::monster::{MonsterAi, MonsterManager, MonsterSpawner};
use crate::outbox::Outbox;
use crate::player::{PeerKey, PendingShot, PlayerState, QueuedInput};
use crate::progression_client::{ProgressionClient, ProgressionJob};
use crate::projectile::ProjectileManager;
use crate::rng::Pcg32;
use crate::world_entity::WorldEntityManager;
use protocol::types::{
    action_type, auth_result_code, disconnect_reason, entity_flags, game_event_type, result_code,
};
use protocol::{
    ActionConfirm, AuthOk, AuthResult, ClientPacket, GameEvent, GameEventData, ServerPacket,
};
use sim_core::constants::*;
use sim_core::Vec2;
use tracing::{debug, info};

/// 50% chance for a monster to drop a Healthorb on death; the orb heals this much HP.
const HEALTHORB_DROP_CHANCE: f64 = 0.5;
const HEALTHORB_HEAL: i32 = 25;

/// Rogue Shadowstep tuning (server-authoritative; not predicted).
/// Max blink distance when the Rogue casts on empty ground (no target near the cursor): the
/// landing point is the cursor clamped to this range from the Rogue, then clamped to arena bounds.
const ROGUE_BLINK_RANGE: f32 = 450.0;
/// AoE radius (around the landing point) of the Shadowstep strike that damages monsters on landing.
/// Must be ≥ `PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS` (= 32) so the monster the Rogue landed
/// behind is always inside the blast; the extra margin is a small splash to nearby monsters.
const ROGUE_SHADOWSTEP_LANDING_RADIUS: f32 = 100.0;
/// How often dirty progression is flushed to the API (s).
const PROGRESS_FLUSH_INTERVAL: f64 = 10.0;

pub const LEADERBOARD_BROADCAST_INTERVAL: f64 = 5.0;
const MIN_SNAPSHOT_FLOOR: usize = 256;

pub struct World {
    pub config: ServerConfig,
    pub players: crate::player::PlayerManager,
    pub projectiles: ProjectileManager,
    pub monsters: MonsterManager,
    pub world_entities: WorldEntityManager,
    pub spawner: MonsterSpawner,
    pub ai: MonsterAi,
    pub leaderboard: Leaderboard,
    pub broadcast: BroadcastService,
    pub backstop: Backstop,
    pub hit_limiter: HitReportLimiter,
    pub verifier: TicketVerifier,
    pub rng: Pcg32,
    /// Server→API progression I/O (None in tests / no-API dev).
    pub progression: Option<ProgressionClient>,
    /// PvP collisions (player projectiles vs players) — off in a Sanctuary instance.
    pub pvp_enabled: bool,
    pub tick_count: u64,
    snapshot_accumulator: f64,
    snapshot_interval: f64,
    leaderboard_timer: f64,
    progress_flush_timer: f64,
}

impl World {
    pub fn new(
        config: ServerConfig,
        verifier: TicketVerifier,
        rng: Pcg32,
        progression: Option<ProgressionClient>,
    ) -> Self {
        let snapshot_interval = 1.0 / config.snapshot_rate_hz().max(1) as f64;
        let pvp_enabled = config.pvp_enabled();
        let monsters_enabled = config.monsters_enabled();
        let is_sanctuary = config.is_sanctuary();
        let mut world = Self {
            broadcast: BroadcastService::new(
                config.aoi_radius,
                config.aoi_exit_radius,
                config.lod_near_radius,
                config.lod_mid_radius,
                config.max_snapshot_bytes,
            ),
            spawner: MonsterSpawner::new(config.monster_spawn_rate),
            ai: MonsterAi::new(config.monster_ai_difficulty),
            players: crate::player::PlayerManager::new(),
            projectiles: ProjectileManager::new(),
            monsters: MonsterManager::new(),
            world_entities: WorldEntityManager::new(),
            leaderboard: Leaderboard::new(),
            backstop: Backstop::default(),
            hit_limiter: HitReportLimiter::default(),
            verifier,
            rng,
            progression,
            pvp_enabled,
            tick_count: 0,
            snapshot_accumulator: 0.0,
            snapshot_interval,
            leaderboard_timer: 0.0,
            progress_flush_timer: 0.0,
            config,
        };
        // Sanctuary: no monsters, town spawn anchors. (Arena keeps the defaults.)
        world.spawner.enabled = monsters_enabled;
        if is_sanctuary {
            world
                .players
                .set_spawn_points(sim_core::constants::SANCTUARY_PLAYER_SPAWNS.to_vec());
        }
        world
    }

    // ── Connection lifecycle ────────────────────────────────────────────────

    /// Returns Err(reason) when the peer must be disconnected immediately.
    pub fn on_peer_connected(&mut self, peer: PeerKey, connect_data: u32) -> Result<(), u32> {
        if (connect_data & 0xFF) as u8 != protocol::PROTOCOL_VERSION {
            info!(
                "peer {peer} rejected: protocol version {}",
                connect_data & 0xFF
            );
            return Err(disconnect_reason::INVALID_AUTH);
        }
        if self.players.player_count() >= self.config.max_players {
            info!("peer {peer} rejected: server full");
            return Err(disconnect_reason::KICKED);
        }
        if self.players.add_player(peer).is_none() {
            return Err(disconnect_reason::KICKED);
        }
        self.broadcast.get_or_create_delta_cache(peer);
        info!("peer {peer} connected (pre-auth)");
        Ok(())
    }

    pub fn on_peer_disconnected(&mut self, peer: PeerKey, outbox: &mut Outbox) {
        if let Some(state) = self.players.get(peer) {
            let entity_id = state.entity_id;
            // Final progression write-back so a clean disconnect persists level/XP.
            if let Some(prog) = &self.progression {
                if state.progression_dirty
                    && state.progression_hydrated
                    && state.character_id < 1_000_000
                {
                    prog.submit(ProgressionJob::Progress {
                        character_id: state.character_id,
                        level: state.level,
                        experience: state.experience,
                    });
                }
            }
            self.leaderboard.remove_player(entity_id);
            outbox.broadcast(combat::leaderboard_event(&self.leaderboard));
        }
        self.players.remove_player(peer);
        self.hit_limiter.remove_peer(peer);
        self.broadcast.remove_peer(peer);
        info!("peer {peer} disconnected");
        // No "player left" GAME_EVENT — departure replicates via delta-stream removal.
    }

    // ── Message handling (between ticks, arrival order) ────────────────────

    pub fn on_packet(
        &mut self,
        peer: PeerKey,
        packet: ClientPacket,
        now_ms: u64,
        now_unix_ms: u64,
        outbox: &mut Outbox,
    ) {
        // Messages from peers without a PlayerState are dropped (lifecycle §6.17).
        if self.players.get(peer).is_none() {
            return;
        }
        match packet {
            ClientPacket::ConnectAuth(auth) => self.handle_auth(peer, auth, now_unix_ms, outbox),
            ClientPacket::PlayerInput(input) => {
                // Single choke point for client floats entering the sim. The wire decode already
                // bounds these (i16 dequant can't produce NaN/Inf), but guard here too so no
                // future ingest path can poison sim math: a NaN aim_angle would slip past the
                // `< 1e-5` direction guard and corrupt every projectile/snapshot it touches.
                let aim_angle = input.aim_angle as f64;
                let position = Vec2::new(input.position.0, input.position.1);
                let cursor = Vec2::new(input.cursor.0, input.cursor.1);
                if !aim_angle.is_finite()
                    || !position.x.is_finite()
                    || !position.y.is_finite()
                    || !cursor.x.is_finite()
                    || !cursor.y.is_finite()
                {
                    debug!("dropping non-finite PlayerInput from peer {peer}");
                    return;
                }
                self.players.queue_player_input(
                    peer,
                    QueuedInput {
                        input_flags: input.input_flags,
                        sequence: input.sequence,
                        aim_angle,
                        position,
                        cursor,
                        client_render_tick: input.client_render_tick,
                        client_rtt_ms: input.client_rtt_ms,
                    },
                );
            }
            ClientPacket::BaselineAck { baseline_tick } => {
                self.broadcast
                    .mark_baseline_acked(peer, baseline_tick as u64);
            }
            ClientPacket::RequestFullState => {
                let entities = self.collect_entities();
                self.broadcast.handle_full_state_request(
                    peer,
                    &entities,
                    &self.players,
                    self.tick_count,
                    (now_ms & 0xFFFF_FFFF) as u32,
                    outbox,
                );
            }
            ClientPacket::RespawnRequest => self.handle_respawn_request(peer, outbox),
            ClientPacket::LocalHitReport { projectile_id } => {
                combat::handle_local_hit_report(
                    peer,
                    projectile_id,
                    &mut self.players,
                    &mut self.projectiles,
                    &mut self.leaderboard,
                    &mut self.hit_limiter,
                    &mut self.backstop,
                    outbox,
                    now_ms,
                );
            }
        }
    }

    fn handle_auth(
        &mut self,
        peer: PeerKey,
        auth: protocol::ConnectAuth,
        now_unix_ms: u64,
        outbox: &mut Outbox,
    ) {
        // Ignore re-auth from an already-authenticated peer (M6): a second ConnectAuth would
        // otherwise overwrite the established identity (character_id/name/class) and re-fire the
        // join broadcasts — an identity-swap vector. First successful auth wins for a peer's life.
        if self.players.get(peer).is_some_and(|s| s.authenticated) {
            debug!("ignoring re-auth from already-authenticated peer {peer}");
            return;
        }
        if auth.protocol_version != protocol::PROTOCOL_VERSION {
            outbox.send(
                peer,
                ServerPacket::AuthResult(AuthResult {
                    result: auth_result_code::BAD_VERSION,
                    ok: None,
                }),
            );
            outbox.kick(peer, disconnect_reason::INVALID_AUTH);
            return;
        }
        let verdict = {
            let mut v = self.verifier.verify(auth.ticket.as_ref(), now_unix_ms);
            // Region check uses the instance's region (config) — local/dev maps to ASIA.
            if v == auth_result_code::OK {
                if let Some(ticket) = &auth.ticket {
                    if ticket.region != region_from_string(&self.config.region) {
                        v = auth_result_code::WRONG_REGION;
                    }
                }
            }
            v
        };
        if verdict != auth_result_code::OK {
            info!("peer {peer} auth rejected: code {verdict}");
            outbox.send(
                peer,
                ServerPacket::AuthResult(AuthResult {
                    result: verdict,
                    ok: None,
                }),
            );
            outbox.kick(peer, disconnect_reason::INVALID_AUTH);
            return;
        }

        let advertised = auth.bandwidth_budget_bps;
        let effective = if advertised > 0 {
            advertised
        } else {
            self.config.default_client_bandwidth_bps
        }
        .clamp(
            self.config.min_client_bandwidth_bps,
            self.config.max_client_bandwidth_bps,
        );
        let rate = self.config.snapshot_rate_hz().max(1);
        let per_peer_bytes = ((effective as f64 / rate as f64).trunc() as usize)
            .clamp(MIN_SNAPSHOT_FLOOR, self.config.max_snapshot_bytes);

        let (entity_id, name, color, class, level, position, character_id) = {
            let Some(state) = self.players.get_mut(peer) else {
                return;
            };
            state.authenticated = true;
            // Signed ticket is authoritative; the dev/unsigned path trusts ConnectAuth.character_id
            // so server-authoritative progression still hydrates locally. 0/absent ⇒ a unique
            // placeholder (≥ 1_000_000) that maps to no DB row (hydrate is skipped).
            state.character_id = auth
                .ticket
                .as_ref()
                .map(|t| t.character_id)
                .filter(|&c| c != 0)
                .or(Some(auth.character_id).filter(|&c| c != 0))
                .unwrap_or(1_000_000 + state.entity_id as u32);
            state.character_name = auth.character_name.clone();
            state.player_color = auth.color;
            // Class is client-chosen identity metadata; clamp out-of-range to Zealot (0). Apply the
            // class + level-scaled stats now (level/XP default to 1/0 until the async hydrate lands).
            let class = if auth.class > 6 { 0 } else { auth.class };
            state.apply_class_and_level(class, 1, 0);
            state.progression_hydrated = false;
            state.bandwidth_budget_bps = effective;
            state.max_snapshot_bytes = per_peer_bytes;
            (
                state.entity_id,
                state.character_name.clone(),
                state.player_color,
                state.player_class,
                state.level,
                state.position,
                state.character_id,
            )
        };
        // Kick off the async level/XP/mode hydrate (real character ids only).
        if character_id < 1_000_000 {
            if let Some(prog) = &self.progression {
                prog.submit(ProgressionJob::Hydrate { peer, character_id });
            }
        }
        self.broadcast.set_peer_byte_budget(peer, per_peer_bytes);
        info!("peer {peer} authenticated as entity {entity_id} '{name}' (budget {per_peer_bytes} B/snap)");

        // Explicit auth answer (new in the redesign): instant Authority sync.
        outbox.send(
            peer,
            ServerPacket::AuthResult(AuthResult {
                result: auth_result_code::OK,
                ok: Some(AuthOk {
                    entity_id,
                    server_tick: self.tick_count as u32,
                    tick_rate: self.config.tick_rate.min(255) as u8,
                }),
            }),
        );
        // PLAYER_INFO fan-out order (lifecycle §4.4): newcomer to all (incl. self), then every
        // OTHER authenticated player to the newcomer, then leaderboard register + broadcast.
        outbox.broadcast(crate::broadcast::player_info_event(
            entity_id, &name, position, color, class, level,
        ));
        let others: Vec<ServerPacket> = self
            .players
            .players
            .iter()
            .filter(|p| p.authenticated && p.peer != peer)
            .map(|p| {
                crate::broadcast::player_info_event(
                    p.entity_id,
                    &p.character_name,
                    p.position,
                    p.player_color,
                    p.player_class,
                    p.level,
                )
            })
            .collect();
        for pkt in others {
            outbox.send(peer, pkt);
        }
        self.leaderboard.register_player(entity_id);
        outbox.broadcast(combat::leaderboard_event(&self.leaderboard));
    }

    fn handle_respawn_request(&mut self, peer: PeerKey, outbox: &mut Outbox) {
        let Some(state) = self.players.get(peer) else {
            return;
        };
        if state.is_alive || state.respawn_timer > 0.0 {
            return; // silent rejection — the client retries
        }
        let spawn = self.players.next_spawn_position();
        let Some(state) = self.players.get_mut(peer) else {
            return;
        };
        state.reset_for_respawn(spawn);
        let entity_id = state.entity_id;
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::RESPAWN,
            source_id: 0,
            target_id: entity_id,
            data: GameEventData::Respawn {
                x: spawn.x,
                y: spawn.y,
            },
        }));
    }

    // ── The tick ────────────────────────────────────────────────────────────

    pub fn tick(&mut self, now_ms: u64, outbox: &mut Outbox) {
        self.tick_count += 1;
        let tick_dt = self.config.tick_interval();

        // Snapshot cadence with the runaway-drift guard (at most one snapshot per catch-up burst).
        let mut snapshot_due = false;
        self.snapshot_accumulator += tick_dt;
        if self.snapshot_accumulator >= self.snapshot_interval {
            self.snapshot_accumulator -= self.snapshot_interval;
            if self.snapshot_accumulator > self.snapshot_interval {
                self.snapshot_accumulator = 0.0;
            }
            snapshot_due = true;
        }

        // 0. Apply any async progression replies (hydrate / death) — non-blocking.
        self.poll_progression(outbox);

        // 1. Inputs → movement steps → shoot/ability spawns → move confirmations.
        let move_results = self.players.process_all_inputs(tick_dt, self.tick_count);
        self.process_shoot_inputs(outbox);
        self.process_ability_activations(outbox);
        self.process_charge_blasts(outbox);
        for r in &move_results {
            if r.cheat_detected {
                debug!(
                    "cheat flagged: peer {} deviation past teleport threshold",
                    r.peer
                );
            }
            // Send the LIVE post-ability position so a Rogue shadowstep teleport (which moves the
            // player after the movement step) reconciles to the corrected spot. mana + the dash /
            // ability cooldowns are also re-read live so an ability cast this tick reflects in the
            // bar immediately and the owner can reconcile its PREDICTED cooldowns against the
            // authoritative ones (otherwise a refused / lost / boundary-timed dash drifts them
            // permanently out of phase — the dash-desync bug).
            let (pos, mana, dash_cd, ability_cd, health) = self
                .players
                .get(r.peer)
                .map(|p| {
                    (
                        p.position,
                        protocol::quant_resource(p.movement_sm.mana()),
                        protocol::quant_cooldown(p.movement_sm.dash_cooldown_remaining()),
                        protocol::quant_cooldown(p.movement_sm.ability_cooldown_remaining()),
                        p.health.clamp(0, u16::MAX as i32) as u16,
                    )
                })
                .unwrap_or((r.position, r.mana, 0, 0, 0));
            outbox.send(
                r.peer,
                ServerPacket::ActionConfirm(ActionConfirm {
                    sequence: r.sequence,
                    action: action_type::MOVE,
                    position: (pos.x, pos.y),
                    result: if r.success {
                        result_code::SUCCESS
                    } else {
                        result_code::FAILED_INVALID_POSITION
                    },
                    server_tick: (self.tick_count & 0xFFFF) as u16,
                    stamina: r.stamina,
                    mana,
                    dash_cooldown: dash_cd,
                    ability_cooldown: ability_cd,
                    health,
                }),
            );
        }

        // 2. Game state: projectiles integrate, spawner, invuln (all) + respawn (auth) timers,
        //    leaderboard cadence (tick time).
        self.projectiles.update_all(tick_dt);
        // Ids freed by integration deaths can be recycled by monster fire later THIS tick;
        // purge their backstop entries now so a recycled id starts clean.
        self.backstop.purge_dead(&self.projectiles);
        self.spawner
            .update(tick_dt, &mut self.monsters, &self.players, &mut self.rng);
        for p in &mut self.players.players {
            p.update_invulnerability(tick_dt);
        }
        for p in self.players.players.iter_mut().filter(|p| p.authenticated) {
            p.update_respawn_timer(tick_dt);
            p.update_stealth(tick_dt);
            p.update_health_regen(tick_dt);
        }
        // Periodic progression write-back + one-shot hardcore-death Glory/permadeath.
        self.progress_flush_timer += tick_dt;
        if self.progress_flush_timer >= PROGRESS_FLUSH_INTERVAL {
            self.progress_flush_timer = 0.0;
            self.flush_dirty_progression();
        }
        self.process_hardcore_deaths();
        self.leaderboard_timer += tick_dt;
        let leaderboard_cadence_due = self.leaderboard_timer >= LEADERBOARD_BROADCAST_INTERVAL;
        if leaderboard_cadence_due {
            self.leaderboard_timer = 0.0;
        }

        // 3. Monster AI (+ fire events: position (0,0), tick 0, non-zero projectile id — D11).
        let fire_events = self.ai.update_all(
            &mut self.monsters,
            &self.players,
            &mut self.projectiles,
            tick_dt,
            now_ms,
            &mut self.rng,
        );
        for e in fire_events {
            outbox.broadcast(ServerPacket::GameEvent(GameEvent {
                event_type: game_event_type::PROJECTILE_FIRED,
                source_id: e.source_id,
                target_id: e.projectile_id,
                data: GameEventData::ProjectileFired {
                    x: 0.0,
                    y: 0.0,
                    fire_tick: 0,
                },
            }));
        }

        // 4. Lag-comp position history (post-movement, pre-collision).
        self.monsters.record_position_snapshot(self.tick_count);
        self.players.record_position_snapshot(self.tick_count);

        // 5. Collisions (players pass, then monsters pass). Killed monsters may drop healthorbs —
        //    the roll happens here (world RNG + entity manager live on `self`, not in combat.rs),
        //    AFTER the collision pass so the shared PCG stream order stays deterministic.
        let killed = combat::process_collisions(
            &mut self.projectiles,
            &mut self.players,
            &mut self.monsters,
            &mut self.leaderboard,
            outbox,
            self.pvp_enabled,
        );
        self.roll_healthorbs(&killed);

        // 5b. D11 backstop (new): blatant unreported monster-bullet overlaps.
        self.backstop.update(
            self.config.backstop_grace_ticks,
            self.tick_count,
            &mut self.players,
            &mut self.projectiles,
            &mut self.leaderboard,
            outbox,
        );

        // 5c. Ability/loot world entities (bibles orbit + sweep, mines, DOT zones, healthorb
        //     pickups). Damage funnels through the same monster-damage path; more kills can drop
        //     more orbs.
        self.tick_world_entities(tick_dt, outbox);

        // 5d. Coalesced leaderboard broadcast: one snapshot per tick at most. Every kill path above
        //     (collisions, D11 backstop, ability AoE, world entities) marks the board dirty rather
        //     than broadcasting inline, so an AoE that wipes several players emits a single update.
        //     Also fires on the periodic cadence so HUDs stay fresh even with no recent kills.
        if leaderboard_cadence_due || self.leaderboard.take_dirty() {
            outbox.broadcast(combat::leaderboard_event(&self.leaderboard));
        }

        // 6. Snapshot broadcast.
        if snapshot_due {
            let entities = self.collect_entities();
            self.broadcast.broadcast_state_updates(
                &entities,
                &self.players,
                self.tick_count,
                (now_ms & 0xFFFF_FFFF) as u32,
                outbox,
            );
            // REMOVED records for disconnected players are now built into every peer's delta
            // cache; their entity ids are safe to recycle.
            self.players.release_quarantined_ids();
        }

        // 7. Cleanup — dead monsters got exactly one death snapshot.
        self.monsters.cleanup_dead_monsters();
    }

    /// Authenticated players (incl. dead) + alive projectiles + ALL monsters (incl.
    /// dead-pending-cleanup).
    pub fn collect_entities(&self) -> Vec<EntityData> {
        let mut out = Vec::with_capacity(
            self.players.player_count() + self.projectiles.count() + self.monsters.count(),
        );
        for p in self.players.players.iter().filter(|p| p.authenticated) {
            out.push(EntityData {
                id: p.entity_id,
                position: p.position,
                animation: p.animation_state,
                flags: p.entity_flags,
            });
        }
        for proj in self.projectiles.projectiles.iter().filter(|p| p.alive) {
            out.push(EntityData {
                id: proj.entity_id,
                position: proj.position,
                animation: projectile_animation_octant(proj.direction),
                flags: if proj.alive { entity_flags::VISIBLE } else { 0 },
            });
        }
        for m in &self.monsters.monsters {
            out.push(EntityData {
                id: m.entity_id,
                position: m.position,
                animation: m.animation_state,
                flags: m.entity_flags,
            });
        }
        // World effects (kind 3): healthorbs, mines, dot-zones, bibles. The id self-classifies the
        // subtype; the client picks the visual from the id band.
        for e in self.world_entities.entities.iter().filter(|e| e.alive) {
            out.push(EntityData {
                id: e.entity_id,
                position: e.position,
                animation: protocol::types::anim::IDLE,
                flags: entity_flags::VISIBLE,
            });
        }
        out
    }

    // ── Shoot pipeline (extraction combat §4.4b–c) ──────────────────────────

    fn process_shoot_inputs(&mut self, outbox: &mut Outbox) {
        for i in 0..self.players.players.len() {
            let pending: Vec<PendingShot> =
                std::mem::take(&mut self.players.players[i].pending_shots);
            let mut fired_this_tick = false;
            for shot in &pending {
                if !fired_this_tick {
                    fired_this_tick = true; // set BEFORE knowing if the spawn succeeds
                    self.try_spawn_projectile(i, shot, outbox);
                }
                // Surplus same-tick edges are drained and dropped.
            }
            let state = &self.players.players[i];
            if !fired_this_tick && state.is_shoot_held() && state.can_shoot() {
                let held = state.held_shot_input();
                self.try_spawn_projectile(i, &held, outbox);
            }
        }
    }

    fn try_spawn_projectile(
        &mut self,
        player_index: usize,
        shot: &PendingShot,
        outbox: &mut Outbox,
    ) {
        let state = &mut self.players.players[player_index];
        // Shooting breaks invulnerability even if the cooldown blocks the shot.
        if state.life_state == crate::player::LifeState::Invulnerable {
            state.end_invulnerability();
        }
        if !state.can_shoot() {
            return;
        }
        let aim_dir = Vec2::from_angle(shot.aim_angle);
        let fire_origin = validated_fire_origin(state, shot, self.config.tick_rate);
        let (rewind, pvp_rewind) = pve_compensation(shot, self.tick_count, self.config.tick_rate);
        let spawn_pos = fire_origin + aim_dir * (PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0);
        let owner_id = state.entity_id;
        let primary_damage = state.primary_damage();
        let max_distance = ability::stats_for_class(state.player_class).projectile_max_distance;
        if let Some(proj) = self.projectiles.spawn_projectile_ex(
            owner_id,
            spawn_pos,
            aim_dir,
            self.tick_count,
            rewind,
            pvp_rewind,
            PROJECTILE_SPEED,
            PLAYER_PROJECTILE_KNOCKBACK_FORCE,
            primary_damage,
            0,
            max_distance,
        ) {
            let projectile_id = proj.entity_id;
            self.players.players[player_index].start_shoot_cooldown();
            outbox.broadcast(ServerPacket::GameEvent(GameEvent {
                event_type: game_event_type::PROJECTILE_FIRED,
                source_id: owner_id,
                target_id: projectile_id,
                data: GameEventData::ProjectileFired {
                    x: spawn_pos.x,
                    y: spawn_pos.y,
                    fire_tick: (self.tick_count & 0xFFFF) as u16,
                },
            }));
        }
        // Failure: no cooldown, no broadcast — but the pending edge was already consumed.
    }

    // ── RMB class abilities ─────────────────────────────────────────────────

    /// Dispatch INSTANT ability casts (the SM flagged `took_ability_this_tick`). Warrior charge is
    /// movement, handled in `process_charge_blasts`.
    fn process_ability_activations(&mut self, outbox: &mut Outbox) {
        for i in 0..self.players.players.len() {
            let cast = {
                let s = &self.players.players[i];
                s.authenticated && s.is_alive && s.movement_sm.took_ability_this_tick()
            };
            if cast {
                self.activate_ability(i, outbox);
            }
        }
    }

    fn activate_ability(&mut self, i: usize, outbox: &mut Outbox) {
        let (class, owner_id, pos, cursor, aim_angle) = {
            let s = &self.players.players[i];
            (
                s.player_class,
                s.entity_id,
                s.position,
                s.last_cursor,
                s.aim_angle,
            )
        };
        let stats = ability::stats_for_class(class);
        match stats.kind {
            AbilityKind::SpinningBibles => {
                self.world_entities.spawn_bibles(
                    owner_id,
                    pos,
                    3,
                    stats.ability_radius,
                    stats.ability_damage,
                    3.0,
                    stats.ability_duration,
                    0.4,
                );
            }
            AbilityKind::Mageblast => {
                let center = clamp_cast_target(pos, cursor, stats.ability_cast_range);
                self.aoe_damage_monsters(
                    center,
                    stats.ability_radius,
                    stats.ability_damage,
                    owner_id,
                    outbox,
                );
                // PvP: the blast also damages and dazes players in radius (Mage's `ability_effects`).
                self.aoe_damage_players(
                    center,
                    stats.ability_radius,
                    stats.ability_damage,
                    owner_id,
                    stats.ability_effects,
                    outbox,
                );
                self.broadcast_ability_effect(
                    ability::effect::MAGEBLAST,
                    center,
                    stats.ability_radius as u16,
                    owner_id,
                    outbox,
                );
            }
            AbilityKind::Multishot => {
                self.spawn_multishot(owner_id, pos, cursor, aim_angle, stats, outbox);
            }
            AbilityKind::Mine => {
                self.world_entities.spawn_mine(
                    pos,
                    owner_id,
                    60.0,
                    stats.ability_radius,
                    stats.ability_damage,
                    0.5,
                    stats.ability_duration,
                );
            }
            AbilityKind::PlagueZone => {
                let center = clamp_cast_target(pos, cursor, stats.ability_cast_range);
                self.world_entities.spawn_dot_zone(
                    center,
                    owner_id,
                    stats.ability_radius,
                    stats.ability_damage,
                    stats.ability_duration,
                );
            }
            AbilityKind::Shadowstep => {
                self.shadowstep(i, owner_id, pos, cursor, stats, outbox);
            }
            AbilityKind::Charge => { /* movement ability — handled in process_charge_blasts */ }
        }
    }

    /// Void Hunter multishot — a spread of piercing projectiles toward the cursor (or aim).
    fn spawn_multishot(
        &mut self,
        owner_id: u16,
        pos: Vec2,
        cursor: Vec2,
        aim_angle: f64,
        stats: &ability::ClassStats,
        outbox: &mut Outbox,
    ) {
        let base_dir = {
            let to = cursor - pos;
            if to.length() > 1e-3 {
                to.normalized()
            } else {
                Vec2::from_angle(aim_angle)
            }
        };
        let count = stats.multishot_count.max(1);
        for k in 0..count {
            let t = if count > 1 {
                k as f64 / (count - 1) as f64 - 0.5
            } else {
                0.0
            };
            let dir = rotate_vec(base_dir, t * stats.multishot_spread);
            let spawn_pos = pos + dir * (PLAYER_HITBOX_RADIUS + PROJECTILE_RADIUS + 2.0);
            if let Some(proj) = self.projectiles.spawn_projectile_ex(
                owner_id,
                spawn_pos,
                dir,
                self.tick_count,
                0,
                0,
                PROJECTILE_SPEED,
                PLAYER_PROJECTILE_KNOCKBACK_FORCE,
                stats.ability_damage,
                stats.multishot_pierce,
                stats.projectile_max_distance,
            ) {
                let projectile_id = proj.entity_id;
                outbox.broadcast(ServerPacket::GameEvent(GameEvent {
                    event_type: game_event_type::PROJECTILE_FIRED,
                    source_id: owner_id,
                    target_id: projectile_id,
                    data: GameEventData::ProjectileFired {
                        x: spawn_pos.x,
                        y: spawn_pos.y,
                        fire_tick: (self.tick_count & 0xFFFF) as u16,
                    },
                }));
            }
        }
    }

    /// Rogue Shadowstep — the assassin ALWAYS teleports, strikes, then vanishes:
    ///
    /// 1. Pick the target. A MONSTER is always preferred: find the nearest-to-cursor alive monster
    ///    within `ability_radius` FIRST; only if NO monster is in range do we consider other
    ///    players/bots. This stops an equidistant/closer player from stealing the lock-on and the
    ///    landing AoE from whiffing every monster. Land BEHIND whichever target is chosen (opposite
    ///    its facing — see `behind_offset`).
    /// 2. If neither a monster nor a player is found, blink to the cursor clamped to
    ///    `ROGUE_BLINK_RANGE` from the Rogue.
    /// 3. The landing point is resolved against static obstacles (the same mover monsters use) so
    ///    the Rogue never teleports into a wall.
    /// 4. On landing: zero velocity, interrupt to idle, set the new position.
    /// 5. Deal `ability_damage` as a PvE-only AoE to monsters within `ROGUE_SHADOWSTEP_LANDING_RADIUS`
    ///    of the landing point (the primary monster target is always inside this radius).
    /// 6. Enter Stealth (vanish) and broadcast the SHADOWSTEP VFX at the landing position.
    ///
    /// The teleport is server-authoritative (the client reconciles to the corrected position).
    fn shadowstep(
        &mut self,
        i: usize,
        owner_id: u16,
        pos: Vec2,
        cursor: Vec2,
        stats: &ability::ClassStats,
        outbox: &mut Outbox,
    ) {
        let search_r2 = stats.ability_radius * stats.ability_radius;

        // Target priority: a MONSTER always wins if any monster is in range. Find the nearest-to-
        // cursor alive monster within the search radius FIRST; capture (position, facing) so we can
        // land behind it.
        let mut best: Option<(Vec2, Vec2)> = None; // (target_pos, facing)
        let mut best_d2 = search_r2;
        for m in self.monsters.monsters.iter() {
            if !m.is_alive {
                continue;
            }
            let d2 = m.position.distance_squared_to(cursor);
            if d2 <= best_d2 {
                best_d2 = d2;
                best = Some((m.position, self.monster_facing(m)));
            }
        }

        // Only if NO monster was found in range do we consider other players/bots (exclude the
        // caster; entity-id ranges keep out projectiles/world entities). Players require
        // `authenticated` — they only exist as targetable entities once they've joined the world —
        // whereas a spawned monster is targetable the moment it is alive (it has no auth concept).
        if best.is_none() {
            let mut best_player_d2 = search_r2;
            for p in self.players.players.iter() {
                if p.entity_id == owner_id || !p.authenticated || !p.is_alive {
                    continue;
                }
                let d2 = p.position.distance_squared_to(cursor);
                if d2 <= best_player_d2 {
                    best_player_d2 = d2;
                    best = Some((p.position, player_facing(p)));
                }
            }
        }

        let raw_pos = if let Some((target_pos, facing)) = best {
            // Land behind the target, one player+target radius away.
            let land_offset = PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS;
            let behind = behind_offset(facing, orig_offset(pos, target_pos));
            sim_core::arena::clamp_to_bounds(target_pos + behind * land_offset)
        } else {
            // Empty ground: blink toward the cursor, capped at the blink range.
            sim_core::arena::clamp_to_bounds(clamp_cast_target(pos, cursor, ROGUE_BLINK_RANGE))
        };

        // Resolve the landing against static obstacles (same mover the monster AI uses) so a blink
        // that would end inside a wall is slid/pulled back to the nearest reachable point.
        let new_pos =
            sim_core::arena::move_with_obstacle_collision(pos, raw_pos, PLAYER_HITBOX_RADIUS);

        {
            let s = &mut self.players.players[i];
            s.position = new_pos;
            s.velocity = Vec2::ZERO;
            s.movement_sm.interrupt_to_idle();
        }

        // PvE strike on landing: AoE to monsters only (never players/bots).
        self.aoe_damage_monsters(
            new_pos,
            ROGUE_SHADOWSTEP_LANDING_RADIUS,
            stats.ability_damage,
            owner_id,
            outbox,
        );

        // The assassin vanishes AFTER striking. Stealth is INTENTIONALLY permanent for its full
        // duration: it is NOT broken by casting or shooting (the old `break_stealth` call was
        // deliberately removed). The Rogue stays invisible until `update_stealth` runs out the timer.
        self.players.players[i].enter_stealth(stats.ability_duration);
        // Recompute the entity flags THIS tick so the STEALTH flag is in the snapshot immediately:
        // shadowstep runs in `process_ability_activations`, AFTER `process_all_inputs` already
        // rebuilt the flags, so without this the flag would be deferred one tick.
        self.players.players[i].update_entity_flags();
        self.broadcast_ability_effect(
            ability::effect::SHADOWSTEP,
            new_pos,
            ROGUE_SHADOWSTEP_LANDING_RADIUS as u16,
            owner_id,
            outbox,
        );
    }

    /// A monster's facing for Shadowstep "land behind" targeting: its attack/aim direction (toward
    /// its current target) while attacking, else its travel direction, else `Vec2::ZERO` (idle ⇒
    /// caller falls back to the original-offset direction).
    fn monster_facing(&self, m: &crate::monster::MonsterState) -> Vec2 {
        use crate::monster::AiState;
        if matches!(m.ai_state, AiState::Attack) || m.attack_timer > 0.0 {
            if let Some(t) = self.players.get_by_entity_id(m.target_id) {
                let to = t.position - m.position;
                if to.length() > 1e-3 {
                    return to.normalized();
                }
            }
        }
        m.move_direction // already unit-length while moving, ZERO while idle
    }

    /// Warrior charge: on charge-end (release / max-distance via the SM, or enemy contact detected
    /// here) spawn the AOE blast exactly once.
    fn process_charge_blasts(&mut self, outbox: &mut Outbox) {
        for i in 0..self.players.players.len() {
            let (auth, alive, class, pos, owner_id, charging, ended) = {
                let s = &self.players.players[i];
                (
                    s.authenticated,
                    s.is_alive,
                    s.player_class,
                    s.position,
                    s.entity_id,
                    s.movement_sm.is_charging(),
                    s.movement_sm.charge_ended_this_tick(),
                )
            };
            if !auth || !alive {
                continue;
            }
            let stats = ability::stats_for_class(class);
            if stats.kind != AbilityKind::Charge {
                continue;
            }
            let mut blast = ended;
            if !ended && charging {
                let contact = self.monsters.monsters.iter().any(|m| {
                    m.is_alive
                        && m.position.distance_to(pos)
                            < PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS
                });
                if contact {
                    self.players.players[i].movement_sm.end_charge();
                    blast = true;
                }
            }
            if blast {
                self.aoe_damage_monsters(
                    pos,
                    stats.ability_radius,
                    stats.ability_damage,
                    owner_id,
                    outbox,
                );
                self.broadcast_ability_effect(
                    ability::effect::CHARGE_BLAST,
                    pos,
                    stats.ability_radius as u16,
                    owner_id,
                    outbox,
                );
            }
        }
    }

    /// Apply instant AOE damage to every alive monster within `radius` of `center`, rolling
    /// healthorbs on kills.
    fn aoe_damage_monsters(
        &mut self,
        center: Vec2,
        radius: f32,
        damage: i32,
        owner_id: u16,
        outbox: &mut Outbox,
    ) {
        let r2 = radius * radius;
        let ids: Vec<u16> = self
            .monsters
            .monsters
            .iter()
            .filter(|m| m.is_alive && m.position.distance_squared_to(center) <= r2)
            .map(|m| m.entity_id)
            .collect();
        let mut killed = Vec::new();
        for id in ids {
            if let Some(p) = combat::apply_monster_damage(
                id,
                damage,
                owner_id,
                &mut self.monsters,
                &mut self.players,
                outbox,
            ) {
                killed.push(p);
            }
        }
        self.roll_healthorbs(&killed);
    }

    /// PvP mirror of `aoe_damage_monsters`: apply an instant ability's `damage` + on-hit `effects`
    /// to every OTHER alive, authenticated player within `radius` of `center`. Routes through the
    /// shared `combat::apply_player_damage`, so kills, shared XP, the leaderboard and the DAMAGE
    /// broadcast all match the projectile path; the daze/effects then replicate via the existing
    /// DAZED entity flag (no new wire format). No knockback — an AoE has no single travel
    /// direction. Skips the caster; a no-op where PvP is disabled (the safe Sanctuary).
    fn aoe_damage_players(
        &mut self,
        center: Vec2,
        radius: f32,
        damage: i32,
        owner_id: u16,
        effects: &'static [ability::StatusEffect],
        outbox: &mut Outbox,
    ) {
        if !self.pvp_enabled {
            return;
        }
        let r2 = radius * radius;
        let ids: Vec<u16> = self
            .players
            .players
            .iter()
            .filter(|p| {
                p.authenticated
                    && p.is_alive
                    && p.entity_id != owner_id
                    && p.position.distance_squared_to(center) <= r2
            })
            .map(|p| p.entity_id)
            .collect();
        for id in ids {
            combat::apply_player_damage(
                owner_id,
                id,
                damage,
                effects,
                &mut self.players,
                &mut self.leaderboard,
                outbox,
                None,
            );
        }
    }

    /// 50% Healthorb drop per killed monster (uses the world PCG so the order is deterministic).
    fn roll_healthorbs(&mut self, positions: &[Vec2]) {
        for &pos in positions {
            if self.rng.randf() < HEALTHORB_DROP_CHANCE {
                self.world_entities.spawn_healthorb(pos, HEALTHORB_HEAL);
            }
        }
    }

    fn broadcast_ability_effect(
        &self,
        effect_id: u8,
        pos: Vec2,
        radius: u16,
        source_id: u16,
        outbox: &mut Outbox,
    ) {
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::ABILITY_EFFECT,
            source_id,
            target_id: 0,
            data: GameEventData::AbilityEffect {
                effect_id,
                x: pos.x,
                y: pos.y,
                radius,
            },
        }));
    }

    /// Advance ability/loot world entities and apply their effects (monster damage, player heals,
    /// VFX). Mirrors the kind+subtype id partition for replication via `collect_entities`.
    fn tick_world_entities(&mut self, dt: f64, outbox: &mut Outbox) {
        let players: Vec<(u16, Vec2, bool)> = self
            .players
            .players
            .iter()
            .filter(|p| p.authenticated)
            .map(|p| (p.entity_id, p.position, p.is_alive))
            .collect();
        let monsters: Vec<(u16, Vec2, bool)> = self
            .monsters
            .monsters
            .iter()
            .map(|m| (m.entity_id, m.position, m.is_alive))
            .collect();
        let outcome = self.world_entities.update_all(dt, &players, &monsters);

        let mut killed = Vec::new();
        for d in &outcome.monster_damage {
            if let Some(p) = combat::apply_monster_damage(
                d.monster_id,
                d.amount,
                d.owner_id,
                &mut self.monsters,
                &mut self.players,
                outbox,
            ) {
                killed.push(p);
            }
        }
        self.roll_healthorbs(&killed);

        for h in &outcome.player_heals {
            if let Some(p) = self.players.get_by_entity_id_mut(h.player_id) {
                let healed = p.heal(h.amount);
                if healed > 0 {
                    outbox.broadcast(ServerPacket::GameEvent(GameEvent {
                        event_type: game_event_type::PICKUP,
                        source_id: h.orb_id,
                        target_id: h.player_id,
                        data: GameEventData::Pickup {
                            kind: 0,
                            amount: healed as u16,
                        },
                    }));
                }
            }
        }

        for e in &outcome.effects {
            self.broadcast_ability_effect(e.effect_id, e.position, e.radius, 0, outbox);
        }
    }

    // ── Server-authoritative progression I/O ────────────────────────────────

    /// Apply async hydrate / death replies (non-blocking) at the top of each tick.
    fn poll_progression(&mut self, outbox: &mut Outbox) {
        let (hydrates, deaths) = match &self.progression {
            Some(prog) => (
                prog.hydrate_rx.try_iter().collect::<Vec<_>>(),
                prog.death_rx.try_iter().collect::<Vec<_>>(),
            ),
            None => (Vec::new(), Vec::new()),
        };
        for h in hydrates {
            if let Some(p) = self.players.get_mut(h.peer) {
                if !p.authenticated || p.character_id != h.character_id {
                    continue;
                }
                let Some(state) = h.state else {
                    // Hydrate failed — fail CLOSED rather than play a possibly-hardcore character
                    // as softcore (no permadeath). Kick so the client retries a clean join.
                    info!(
                        "hydrate failed for char {} (peer {}); kicking to avoid softcore fallback",
                        h.character_id, h.peer
                    );
                    outbox.kick(h.peer, disconnect_reason::KICKED);
                    continue;
                };
                p.apply_class_and_level(p.player_class, state.level, state.experience);
                p.mode_hardcore = state.mode_hardcore;
                p.progression_hydrated = true;
                p.progression_dirty = false;
                let move_speed_q = (p.effective_move_speed() / 4.0).round().clamp(0.0, 255.0) as u8;
                let (peer, entity_id, level, experience) =
                    (p.peer, p.entity_id, p.level, p.experience);
                let (name, color, class, position) = (
                    p.character_name.clone(),
                    p.player_color,
                    p.player_class,
                    p.position,
                );
                outbox.send(
                    peer,
                    ServerPacket::GameEvent(GameEvent {
                        event_type: game_event_type::PROGRESS,
                        source_id: entity_id,
                        target_id: entity_id,
                        data: GameEventData::Progress {
                            level,
                            experience,
                            move_speed_q,
                        },
                    }),
                );
                // Join broadcast PLAYER_INFO with the pre-hydrate default level (1); now that the
                // real level has landed, re-broadcast so every OTHER client's leaderboard shows it.
                outbox.broadcast(crate::broadcast::player_info_event(
                    entity_id, &name, position, color, class, level,
                ));
            }
        }
        for d in deaths {
            info!(
                "character {} death processed: glory +{} (deleted: {})",
                d.character_id, d.glory_awarded, d.character_deleted
            );
            if d.character_deleted {
                // Hardcore permadeath: the character row is gone — disconnect so the client
                // returns to character creation.
                outbox.kick(d.peer, disconnect_reason::KICKED);
            }
        }
    }

    /// Write back any dirty level/XP (real characters only).
    fn flush_dirty_progression(&mut self) {
        let Some(prog) = &self.progression else {
            return;
        };
        for p in self.players.players.iter_mut() {
            if p.authenticated
                && p.progression_dirty
                && p.progression_hydrated
                && p.character_id < 1_000_000
            {
                prog.submit(ProgressionJob::Progress {
                    character_id: p.character_id,
                    level: p.level,
                    experience: p.experience,
                });
                p.progression_dirty = false;
            }
        }
    }

    /// One-shot hardcore-death Glory conversion + permadeath delete via the API.
    fn process_hardcore_deaths(&mut self) {
        let mut report: Vec<(PeerKey, u32)> = Vec::new();
        for p in self.players.players.iter_mut() {
            if p.authenticated
                && !p.is_alive
                && p.mode_hardcore
                && p.progression_hydrated
                && !p.death_reported
                && p.character_id < 1_000_000
            {
                p.death_reported = true;
                report.push((p.peer, p.character_id));
            }
        }
        if let Some(prog) = &self.progression {
            for (peer, character_id) in report {
                prog.submit(ProgressionJob::Death { peer, character_id });
            }
        }
    }
}

/// Clamp a cursor target to `max_range` from `origin` (0 = no clamp).
fn clamp_cast_target(origin: Vec2, cursor: Vec2, max_range: f32) -> Vec2 {
    if max_range <= 0.0 {
        return cursor;
    }
    let to = cursor - origin;
    let d = to.length();
    if d <= max_range || d < 1e-3 {
        cursor
    } else {
        origin + to * (max_range / d)
    }
}

/// Unit vector from `mpos` back toward `from` (the side a teleporting Rogue lands on).
fn orig_offset(from: Vec2, mpos: Vec2) -> Vec2 {
    let back = from - mpos;
    if back.length() > 1e-3 {
        back.normalized()
    } else {
        Vec2::new(-1.0, 0.0)
    }
}

/// Unit direction from a target's center to the point BEHIND it for a Rogue landing.
/// `facing` is the target's shoot/travel direction; "behind" is its opposite. When the target is
/// idle (`facing ≈ 0`), fall back to `fallback_dir` (the direction back toward the Rogue's origin).
fn behind_offset(facing: Vec2, fallback_dir: Vec2) -> Vec2 {
    if facing.length() > 1e-3 {
        (-facing).normalized()
    } else if fallback_dir.length() > 1e-3 {
        fallback_dir.normalized()
    } else {
        Vec2::new(-1.0, 0.0)
    }
}

/// A player's facing for Shadowstep "land behind" targeting: their aim direction while actively
/// shooting, else their travel/velocity direction, else `Vec2::ZERO` (idle ⇒ caller falls back).
fn player_facing(p: &PlayerState) -> Vec2 {
    if p.is_shoot_held() {
        return Vec2::from_angle(p.aim_angle);
    }
    if p.velocity.length() > 1e-3 {
        return p.velocity.normalized();
    }
    Vec2::ZERO
}

/// Rotate `v` by `phi` radians (CCW in math coordinates), mirroring Godot's `Vector2.rotated`.
fn rotate_vec(v: Vec2, phi: f64) -> Vec2 {
    let (s, c) = (phi.sin() as f32, phi.cos() as f32);
    Vec2::new(v.x * c - v.y * s, v.x * s + v.y * c)
}

/// Fire-origin validation (extraction combat §4.4d): use the client's stamped position as the
/// muzzle origin when within an RTT-scaled tolerance, clamped [16, 75].
fn validated_fire_origin(state: &PlayerState, shot: &PendingShot, tick_rate: u32) -> Vec2 {
    let Some(client_pos) = shot.client_position else {
        return state.position;
    };
    let rtt = shot.client_rtt_ms as f64;
    let one_way_s =
        (rtt * 0.0005).min(MAX_PVE_PROJECTILE_COMPENSATION_TICKS as f64 / tick_rate as f64);
    let tick_interval = 1.0 / tick_rate as f64;
    let predicted_gap = PLAYER_SPRINT_SPEED * (one_way_s + tick_interval);
    let tolerance = (predicted_gap + PROJECTILE_RADIUS as f64)
        .clamp((PROJECTILE_RADIUS * 2.0) as f64, POSITION_TOLERANCE as f64);
    if state.position.distance_to(client_pos) as f64 <= tolerance {
        client_pos
    } else {
        state.position
    }
}

/// PvE lag-comp rewind derivation (extraction combat §4.4e): resolve the u16 client render tick
/// against the full tick counter; RTT fallback `2 + ceil(rtt/2 / tick_ms)`; caps 6 (PvE) / 4 (PvP).
fn pve_compensation(shot: &PendingShot, tick_count: u64, tick_rate: u32) -> (u64, u64) {
    let crt16 = shot.client_render_tick;
    let rewind = if crt16 > 0 {
        let server16 = (tick_count & 0xFFFF) as i64;
        let mut diff = crt16 as i64 - server16;
        if diff > 32767 {
            diff -= 65536;
        } else if diff < -32768 {
            diff += 65536;
        }
        let resolved = tick_count as i64 + diff;
        let rewind = tick_count as i64 - resolved;
        if rewind >= 0 {
            Some(rewind.clamp(0, MAX_PVE_PROJECTILE_COMPENSATION_TICKS as i64) as u64)
        } else {
            None // client claims a FUTURE tick → fallback
        }
    } else {
        None
    };
    let rewind = rewind.unwrap_or_else(|| {
        let rtt = shot.client_rtt_ms as f64;
        let one_way_ticks = if rtt > 0.0 {
            ((rtt * 0.5) / (1000.0 / tick_rate as f64)).ceil() as u64
        } else {
            0
        };
        (REMOTE_ENTITY_RENDER_DELAY_TICKS as u64 + one_way_ticks)
            .min(MAX_PVE_PROJECTILE_COMPENSATION_TICKS as u64)
    });
    let pvp_rewind = rewind.min(MAX_PVP_PROJECTILE_COMPENSATION_TICKS as u64);
    (rewind, pvp_rewind)
}

/// Projectile replication animation: direction octant (extraction combat §4.15).
fn projectile_animation_octant(direction: Vec2) -> u8 {
    let angle = (direction.y as f64).atan2(direction.x as f64);
    let two_pi = std::f64::consts::TAU;
    let norm = (angle + std::f64::consts::PI).rem_euclid(two_pi);
    ((norm / two_pi * 8.0).trunc() as i64 % 8) as u8
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::outbox::Target;

    fn test_world() -> World {
        // sim_core now debug_asserts that each thread set its geometry before any bounds/obstacle
        // read (arena.rs "set once, single thread" contract). main() does this at server start; a
        // unit test runs on its own libtest thread, so it must apply the Arena geometry itself.
        sim_core::set_world_geometry(
            sim_core::constants::MAP_MIN,
            sim_core::constants::MAP_MAX,
            true,
        );
        let config = ServerConfig::default();
        let verifier = TicketVerifier::new("", true, 0).unwrap();
        World::new(config, verifier, Pcg32::new(1234), None)
    }

    fn sanctuary_world() -> World {
        // The server sets geometry in main(); a test must apply it on its own (isolated) thread.
        sim_core::set_world_geometry(
            sim_core::constants::SANCTUARY_MAP_MIN,
            sim_core::constants::SANCTUARY_MAP_MAX,
            false,
        );
        let config = ServerConfig {
            mode: "sanctuary".into(),
            ..ServerConfig::default()
        };
        let verifier = TicketVerifier::new("", true, 0).unwrap();
        World::new(config, verifier, Pcg32::new(1234), None)
    }

    fn auth_packet(name: &str) -> ClientPacket {
        auth_packet_with_class(name, 0)
    }

    fn auth_packet_with_class(name: &str, class: u8) -> ClientPacket {
        ClientPacket::ConnectAuth(protocol::ConnectAuth {
            protocol_version: protocol::PROTOCOL_VERSION,
            ticket: None,
            character_id: 0,
            character_name: name.into(),
            color: (69, 135, 255),
            class,
            bandwidth_budget_bps: 0,
        })
    }

    fn join(world: &mut World, peer: PeerKey, name: &str) -> u16 {
        world
            .on_peer_connected(peer, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(peer, auth_packet(name), 0, 0, &mut outbox);
        world.players.get(peer).unwrap().entity_id
    }

    fn input(seq: u8, flags: u16, pos: Vec2) -> ClientPacket {
        ClientPacket::PlayerInput(protocol::PlayerInput {
            sequence: seq,
            input_flags: flags,
            aim_angle: 0.0,
            position: (pos.x, pos.y),
            velocity: (0.0, 0.0),
            cursor: (0.0, 0.0),
            client_render_tick: 0,
            client_rtt_ms: 0,
        })
    }

    #[test]
    fn join_flow_produces_auth_result_and_player_info() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet("Alice"), 0, 0, &mut outbox);
        let msgs = outbox.drain();
        // AuthResult OK to the peer.
        assert!(msgs.iter().any(|(t, p)| *t == Target::Peer(1)
            && matches!(p, ServerPacket::AuthResult(r) if r.result == auth_result_code::OK)));
        // PLAYER_INFO broadcast.
        assert!(msgs.iter().any(|(t, p)| *t == Target::Broadcast
            && matches!(p, ServerPacket::GameEvent(e) if e.event_type == game_event_type::PLAYER_INFO)));
        // Leaderboard broadcast.
        assert!(msgs.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::LEADERBOARD_UPDATE
        )));
    }

    /// Join stores the client-chosen class, clamping out-of-range values (> 6) to 0 (Zealot);
    /// the PLAYER_INFO broadcast carries the clamped value.
    #[test]
    fn join_clamps_player_class() {
        let mut world = test_world();

        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Mage", 6), 0, 0, &mut outbox);
        assert_eq!(world.players.get(1).unwrap().player_class, 6);

        world
            .on_peer_connected(2, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(2, auth_packet_with_class("Hacker", 7), 0, 0, &mut outbox);
        assert_eq!(world.players.get(2).unwrap().player_class, 0);
        let entity_id = world.players.get(2).unwrap().entity_id;
        let msgs = outbox.drain();
        assert!(msgs.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::PLAYER_INFO
                && e.target_id == entity_id
                && matches!(e.data, protocol::GameEventData::PlayerInfo { class: 0, .. })
        )));
    }

    #[test]
    fn bad_protocol_version_rejected_at_connect() {
        let mut world = test_world();
        assert!(world.on_peer_connected(1, 0xFF).is_err());
    }

    #[test]
    fn input_moves_player_and_confirms() {
        let mut world = test_world();
        join(&mut world, 1, "Mover");
        let start = world.players.get(1).unwrap().position;
        let mut outbox = Outbox::new();
        world.on_packet(
            1,
            input(1, sim_core::input_flags::MOVE_RIGHT, start),
            0,
            0,
            &mut outbox,
        );
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        // Default join class is Zealot (base move speed 195/s after per-class stats land).
        let zealot_speed = ability::effective_base_speed(0, 1);
        assert!((after.x - start.x - (zealot_speed as f32) / 30.0).abs() < 0.01);
        let msgs = outbox.drain();
        assert!(msgs.iter().any(|(t, p)| *t == Target::Peer(1)
            && matches!(p, ServerPacket::ActionConfirm(c) if c.sequence == 1 && c.result == result_code::SUCCESS)));
        // Snapshot also goes out every tick at default rates.
        assert!(msgs
            .iter()
            .any(|(_, p)| matches!(p, ServerPacket::Snapshot(_))));
    }

    #[test]
    fn shoot_spawns_projectile_and_broadcasts_fire_event() {
        let mut world = test_world();
        join(&mut world, 1, "Shooter");
        let pos = world.players.get(1).unwrap().position;
        let mut outbox = Outbox::new();
        world.on_packet(
            1,
            input(1, sim_core::input_flags::SHOOT, pos),
            0,
            0,
            &mut outbox,
        );
        world.tick(33, &mut outbox);
        assert_eq!(world.projectiles.count(), 1);
        let msgs = outbox.drain();
        let fired: Vec<_> = msgs
            .iter()
            .filter_map(|(_, p)| match p {
                ServerPacket::GameEvent(e) if e.event_type == game_event_type::PROJECTILE_FIRED => {
                    Some(e)
                }
                _ => None,
            })
            .collect();
        assert_eq!(fired.len(), 1);
        assert!(fired[0].target_id >= 10000, "projectile id in target_id");
        match &fired[0].data {
            GameEventData::ProjectileFired { fire_tick, .. } => assert_eq!(*fire_tick, 1),
            other => panic!("wrong data: {other:?}"),
        }
        // Shooting also ended spawn invulnerability if any and started the cooldown.
        assert!(world.players.get(1).unwrap().shoot_cooldown > 0.0);
    }

    #[test]
    fn mageblast_aoe_damages_and_dazes_players_in_radius() {
        let mut world = test_world();
        world.pvp_enabled = true;
        let caster = join(&mut world, 1, "Mage");
        let victim = join(&mut world, 2, "Victim");
        let far = join(&mut world, 3, "Bystander");
        // Caster + victim at the blast centre; the bystander is well outside the 144 radius.
        world.players.get_by_entity_id_mut(caster).unwrap().position = Vec2::new(0.0, 0.0);
        world.players.get_by_entity_id_mut(victim).unwrap().position = Vec2::new(50.0, 0.0);
        world.players.get_by_entity_id_mut(far).unwrap().position = Vec2::new(500.0, 0.0);
        let caster_hp = world.players.get_by_entity_id(caster).unwrap().health;
        let victim_hp = world.players.get_by_entity_id(victim).unwrap().health;
        let far_hp = world.players.get_by_entity_id(far).unwrap().health;

        let mut outbox = Outbox::new();
        world.aoe_damage_players(
            Vec2::new(0.0, 0.0),
            144.0,
            55,
            caster,
            &[ability::StatusEffect::Daze {
                secs: sim_core::constants::PLAYER_DAZE_DURATION,
            }],
            &mut outbox,
        );

        // Victim in radius: takes the blast damage and is dazed.
        let v = world.players.get_by_entity_id(victim).unwrap();
        assert_eq!(v.health, victim_hp - 55, "victim took Mageblast damage");
        assert!(v.movement_sm.is_dazed(), "victim dazed by Mageblast");
        // Caster: never caught by their own blast despite being at the centre.
        let c = world.players.get_by_entity_id(caster).unwrap();
        assert_eq!(c.health, caster_hp, "caster unharmed by own blast");
        assert!(!c.movement_sm.is_dazed(), "caster not self-dazed");
        // Bystander outside the radius: untouched.
        let f = world.players.get_by_entity_id(far).unwrap();
        assert_eq!(f.health, far_hp, "out-of-radius player untouched");
        assert!(!f.movement_sm.is_dazed());
    }

    #[test]
    fn mageblast_aoe_is_noop_when_pvp_disabled() {
        let mut world = test_world();
        world.pvp_enabled = false; // safe Sanctuary semantics
        let caster = join(&mut world, 1, "Mage");
        let victim = join(&mut world, 2, "Victim");
        world.players.get_by_entity_id_mut(caster).unwrap().position = Vec2::ZERO;
        world.players.get_by_entity_id_mut(victim).unwrap().position = Vec2::new(50.0, 0.0);
        let victim_hp = world.players.get_by_entity_id(victim).unwrap().health;
        let mut outbox = Outbox::new();
        world.aoe_damage_players(
            Vec2::ZERO,
            144.0,
            55,
            caster,
            &[ability::StatusEffect::Daze {
                secs: sim_core::constants::PLAYER_DAZE_DURATION,
            }],
            &mut outbox,
        );
        let v = world.players.get_by_entity_id(victim).unwrap();
        assert_eq!(v.health, victim_hp, "no PvP damage when pvp disabled");
        assert!(!v.movement_sm.is_dazed(), "no daze when pvp disabled");
    }

    #[test]
    fn respawn_flow_with_timer_gate() {
        let mut world = test_world();
        join(&mut world, 1, "Dier");
        world.players.players[0].health = 1;
        let entity_id = world.players.players[0].entity_id;
        let mut outbox = Outbox::new();
        combat::apply_player_hit(
            30001,
            entity_id,
            &mut world.players,
            &mut world.leaderboard,
            &mut outbox,
            None,
        );
        assert!(!world.players.players[0].is_alive);
        // Immediate respawn request rejected (timer 3.0).
        world.on_packet(1, ClientPacket::RespawnRequest, 0, 0, &mut outbox);
        assert!(!world.players.players[0].is_alive);
        // After 91 ticks (> 3 s) the timer clamps to 0 and the request is granted.
        for _ in 0..91 {
            world.tick(0, &mut outbox);
        }
        outbox.drain();
        world.on_packet(1, ClientPacket::RespawnRequest, 0, 0, &mut outbox);
        assert!(world.players.players[0].is_alive);
        assert_eq!(
            world.players.players[0].life_state,
            crate::player::LifeState::Invulnerable
        );
        let msgs = outbox.drain();
        assert!(msgs.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::RESPAWN && e.target_id == entity_id
        )));
    }

    #[test]
    fn monsters_spawn_and_replicate_over_time() {
        let mut world = test_world();
        join(&mut world, 1, "Bait");
        let mut outbox = Outbox::new();
        // 40 s of ticks at spawn rate 0.1/s ⇒ ~4 monsters.
        for t in 0..1200 {
            world.tick(t * 33, &mut outbox);
            outbox.drain();
        }
        assert!(
            world.monsters.alive_count() >= 2,
            "alive: {}",
            world.monsters.alive_count()
        );
    }

    #[test]
    fn projectile_octant_animation() {
        assert_eq!(projectile_animation_octant(Vec2::new(1.0, 0.0)), 4);
        assert_eq!(projectile_animation_octant(Vec2::new(-1.0, 0.0)), 0);
    }

    #[test]
    fn sanctuary_mode_is_a_safe_town() {
        let mut world = sanctuary_world();
        assert!(!world.pvp_enabled, "PvP off in the sanctuary");
        assert!(!world.spawner.enabled, "spawner off in the sanctuary");
        // Player spawns in the West Gate Refuge yard (grid x≈-78), deep in the western town and
        // well outside the ±800 arena ring (redesign spec §9). All anchors sit at x < -2000.
        let id = join(&mut world, 1, "Townie");
        let pos = world.players.get_by_entity_id(id).unwrap().position;
        assert!(
            pos.x < -2000.0,
            "spawned at the west gate refuge, got {pos:?}"
        );
        // No monsters ever spawn, even over a long run that fills the arena.
        let mut outbox = Outbox::new();
        for t in 0..600 {
            world.tick(t * 33, &mut outbox);
            outbox.drain();
        }
        assert_eq!(
            world.monsters.alive_count(),
            0,
            "no monsters in the sanctuary"
        );
    }

    fn cast_input(seq: u8, pos: Vec2, cursor: Vec2) -> ClientPacket {
        ClientPacket::PlayerInput(protocol::PlayerInput {
            sequence: seq,
            input_flags: sim_core::input_flags::ABILITY,
            aim_angle: 0.0,
            position: (pos.x, pos.y),
            velocity: (0.0, 0.0),
            cursor: (cursor.x, cursor.y),
            client_render_tick: 0,
            client_rtt_ms: 0,
        })
    }

    #[test]
    fn mage_blast_damages_monster_at_cursor() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Mage", 6), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        let mpos = ppos + Vec2::new(150.0, 0.0); // within the 600 cast range
        world.monsters.spawn_monster(mpos, "toxic_slime");
        outbox.drain();
        // RMB cast with the cursor on the monster.
        world.on_packet(1, cast_input(1, ppos, mpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        // Mage blast deals 55 ≥ the slime's 50 HP ⇒ killed; an ABILITY_EFFECT VFX is broadcast.
        assert!(
            !world.monsters.monsters.iter().any(|m| m.is_alive),
            "mageblast should have killed the toxic slime"
        );
        let msgs = outbox.drain();
        assert!(msgs.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::ABILITY_EFFECT
        )));
        // Mana was spent (Mage ability costs 40).
        assert!(world.players.get(1).unwrap().movement_sm.mana() < 100.0);
    }

    #[test]
    fn rogue_blinks_toward_cursor_on_empty_ground() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // No targets anywhere: blink toward a cursor that is FAR beyond the blink range — the
        // landing must be capped at ROGUE_BLINK_RANGE (450) from the Rogue, not snapped in place.
        let cursor = ppos + Vec2::new(900.0, 0.0);
        world.on_packet(1, cast_input(1, ppos, cursor), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        let moved = after.distance_to(ppos);
        assert!(
            moved > 1.0,
            "rogue must always teleport, even on empty ground (moved {moved})"
        );
        assert!(
            (moved - ROGUE_BLINK_RANGE).abs() < 1.0,
            "empty-ground blink must be capped at the blink range (moved {moved}, cap {ROGUE_BLINK_RANGE})"
        );
        // And it always vanishes.
        assert!(world.players.get(1).unwrap().is_stealthed());
    }

    #[test]
    fn rogue_lands_behind_target_facing() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // A tanky monster near the cursor with a KNOWN travel direction (+X). The Rogue must land
        // BEHIND it — on the −X side — regardless of which side the Rogue came from (+X here).
        let mpos = ppos + Vec2::new(300.0, 0.0);
        let mid = world
            .monsters
            .spawn_monster(mpos, "target_dummy")
            .unwrap()
            .entity_id;
        world.monsters.get_mut(mid).unwrap().move_direction = Vec2::new(1.0, 0.0);
        outbox.drain();
        world.on_packet(1, cast_input(1, ppos, mpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        // Behind a +X-facing target ⇒ on the −X side of the monster.
        assert!(
            after.x < mpos.x - 1.0,
            "rogue should land behind (−X of) a +X-facing target (landed at {after:?}, monster {mpos:?})"
        );
        assert!(
            (after.y - mpos.y).abs() < 1.0,
            "landing should be straight behind on the facing axis"
        );
    }

    #[test]
    fn rogue_lands_behind_player_bot_target() {
        // A Rogue can Shadowstep onto ANOTHER PLAYER/BOT, not just monsters: with a second
        // connected player at the cursor and NO monsters around, the Rogue must land adjacent-
        // and-behind it (the player branch of the target search). This would fail on the old
        // monsters-only Shadowstep (which would stealth in place, far from the bot).
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        world
            .on_peer_connected(2, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        world.on_packet(2, auth_packet_with_class("Warrior", 4), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // Park the "bot" right at the cursor; no monsters exist, so it must be the chosen target.
        let bpos = ppos + Vec2::new(300.0, 0.0);
        world.players.get_mut(2).unwrap().position = bpos;
        outbox.drain();
        world.on_packet(1, cast_input(1, ppos, bpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        // Landed adjacent to the bot (targeted) and behind it (−X of it), NOT stranded at ppos.
        assert!(
            after.distance_to(bpos) <= PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS + 1.0,
            "rogue should land adjacent to the targeted bot (landed {after:?}, bot {bpos:?})"
        );
        assert!(
            after.x < bpos.x - 1.0,
            "rogue should land behind the bot, not on the cursor"
        );
        // Players/bots are never damaged by Shadowstep (PvE only).
        assert!(world.players.get(2).unwrap().is_alive);
    }

    #[test]
    fn rogue_shadowstep_damages_monster_at_landing() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // A monster right at the cursor (within the 160 search radius). The 85 AoE on landing
        // kills the 50-HP slime, and the Rogue ends up adjacent to where it died.
        let mpos = ppos + Vec2::new(300.0, 0.0);
        world.monsters.spawn_monster(mpos, "toxic_slime");
        outbox.drain();
        world.on_packet(1, cast_input(1, ppos, mpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        assert!(
            after.distance_to(mpos) < ROGUE_SHADOWSTEP_LANDING_RADIUS,
            "rogue should land next to the targeted monster"
        );
        assert!(
            !world.monsters.monsters.iter().any(|m| m.is_alive),
            "the landing AoE should have killed the toxic slime"
        );
        let msgs = outbox.drain();
        assert!(msgs.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::ABILITY_EFFECT
        )));
    }

    #[test]
    fn rogue_always_enters_stealth_on_cast() {
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // Land behind a monster (the strike case) — the Rogue must STILL vanish afterward.
        let mpos = ppos + Vec2::new(120.0, 0.0);
        world.monsters.spawn_monster(mpos, "toxic_slime");
        world.on_packet(1, cast_input(1, ppos, mpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        assert!(
            world.players.get(1).unwrap().is_stealthed(),
            "rogue must enter stealth after every cast"
        );
        // shadowstep recomputes the flags on the casting tick, so the STEALTH flag is present in
        // THIS tick's snapshot (no one-tick deferral).
        assert!(
            world.players.get(1).unwrap().entity_flags & entity_flags::STEALTH != 0,
            "STEALTH flag must apply on the casting tick"
        );
    }

    #[test]
    fn rogue_prefers_monster_even_when_player_is_closer() {
        // A monster IN RANGE always wins targeting over a player/bot, even one nearer the cursor.
        // Otherwise the player would steal the lock-on and the landing AoE would whiff the monster.
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        world
            .on_peer_connected(2, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        world.on_packet(2, auth_packet_with_class("Warrior", 4), 0, 0, &mut outbox);
        let ppos = world.players.get(1).unwrap().position;
        // Cursor in open ground. A monster sits a bit FARTHER from the cursor than the bot, yet it
        // must still be the chosen target (monster-first priority), so the Rogue lands behind the
        // MONSTER and the AoE kills it.
        let cursor = ppos + Vec2::new(300.0, 0.0);
        let mpos = cursor + Vec2::new(40.0, 0.0); // 40 u from cursor (within the search radius)
        let bpos = cursor + Vec2::new(10.0, 0.0); // 10 u from cursor (CLOSER than the monster)
        world.players.get_mut(2).unwrap().position = bpos;
        world.monsters.spawn_monster(mpos, "toxic_slime");
        outbox.drain();
        world.on_packet(1, cast_input(1, ppos, cursor), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        // Landed adjacent to the MONSTER (not the closer bot), and the AoE killed the slime.
        assert!(
            after.distance_to(mpos) <= PLAYER_HITBOX_RADIUS + MONSTER_HITBOX_RADIUS + 1.0,
            "rogue should land behind the MONSTER, not the closer bot (landed {after:?}, monster {mpos:?}, bot {bpos:?})"
        );
        assert!(
            !world.monsters.monsters.iter().any(|m| m.is_alive),
            "the landing AoE should have killed the toxic slime"
        );
        // The bot, well outside the AoE, is unharmed.
        assert!(world.players.get(2).unwrap().is_alive);
    }

    #[test]
    fn rogue_landing_resolved_against_wall() {
        // Targeting a monster pressed against an obstacle, the "behind" point would fall inside the
        // wall; the obstacle-aware mover must keep the Rogue out of the obstacle while staying
        // roughly behind the target.
        let mut world = test_world();
        world
            .on_peer_connected(1, protocol::PROTOCOL_VERSION as u32)
            .unwrap();
        let mut outbox = Outbox::new();
        world.on_packet(1, auth_packet_with_class("Rogue", 5), 0, 0, &mut outbox);
        // Center north pillar spans x −20..20, y −200..−40 (expanded by 16 ⇒ x −36..36, y −216..−24).
        // Put the Rogue down-left of the pillar and a −X-facing monster just left of the pillar:
        // landing behind it (the +X side) lands INSIDE the expanded pillar, which the mover must
        // resolve (here it slides along Y, the free axis).
        world.players.get_mut(1).unwrap().position = Vec2::new(-300.0, -200.0);
        let ppos = world.players.get(1).unwrap().position;
        let mpos = Vec2::new(-30.0, -120.0); // just left of the pillar, within search range of cursor
        let mid = world
            .monsters
            .spawn_monster(mpos, "target_dummy")
            .unwrap()
            .entity_id;
        world.monsters.get_mut(mid).unwrap().move_direction = Vec2::new(-1.0, 0.0); // faces −X ⇒ behind is +X (into the pillar)
        outbox.drain();
        world.on_packet(1, cast_input(1, ppos, mpos), 0, 0, &mut outbox);
        world.tick(33, &mut outbox);
        let after = world.players.get(1).unwrap().position;
        // The mover must not leave the Rogue inside the (expanded) pillar.
        assert!(
            !sim_core::arena::circle_intersects_obstacle(after, PLAYER_HITBOX_RADIUS),
            "landing must be resolved out of the obstacle (landed {after:?})"
        );
        // Still teleported away from the origin (didn't freeze in place).
        assert!(
            after.distance_to(ppos) > 1.0,
            "rogue should still teleport toward the target (landed {after:?}, origin {ppos:?})"
        );
    }
}
