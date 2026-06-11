//! The authoritative world: one instance per process (D13), advanced by the single synchronous
//! tick (D8). Exact tick order ported from `_process_server_tick` (extraction server-tick §4.3):
//! inputs → shoot spawns → confirms → projectiles/spawner/timers → monster AI → position
//! history → collisions → backstop (new, D11) → snapshot broadcast → monster cleanup.

use crate::auth::{region_from_string, TicketVerifier};
use crate::broadcast::{BroadcastService, EntityData};
use crate::combat::{self, Backstop, HitReportLimiter};
use crate::config::ServerConfig;
use crate::leaderboard::Leaderboard;
use crate::monster::{MonsterAi, MonsterManager, MonsterSpawner};
use crate::outbox::Outbox;
use crate::player::{PeerKey, PendingShot, PlayerState, QueuedInput};
use crate::projectile::ProjectileManager;
use crate::rng::Pcg32;
use protocol::types::{
    action_type, auth_result_code, disconnect_reason, entity_flags, game_event_type, result_code,
};
use protocol::{
    ActionConfirm, AuthOk, AuthResult, ClientPacket, GameEvent, GameEventData, ServerPacket,
};
use sim_core::constants::*;
use sim_core::Vec2;
use tracing::{debug, info};

pub const LEADERBOARD_BROADCAST_INTERVAL: f64 = 5.0;
const MIN_SNAPSHOT_FLOOR: usize = 256;

pub struct World {
    pub config: ServerConfig,
    pub players: crate::player::PlayerManager,
    pub projectiles: ProjectileManager,
    pub monsters: MonsterManager,
    pub spawner: MonsterSpawner,
    pub ai: MonsterAi,
    pub leaderboard: Leaderboard,
    pub broadcast: BroadcastService,
    pub backstop: Backstop,
    pub hit_limiter: HitReportLimiter,
    pub verifier: TicketVerifier,
    pub rng: Pcg32,
    pub tick_count: u64,
    snapshot_accumulator: f64,
    snapshot_interval: f64,
    leaderboard_timer: f64,
}

impl World {
    pub fn new(config: ServerConfig, verifier: TicketVerifier, rng: Pcg32) -> Self {
        let snapshot_interval = 1.0 / config.snapshot_rate_hz().max(1) as f64;
        Self {
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
            leaderboard: Leaderboard::new(),
            backstop: Backstop::default(),
            hit_limiter: HitReportLimiter::default(),
            verifier,
            rng,
            tick_count: 0,
            snapshot_accumulator: 0.0,
            snapshot_interval,
            leaderboard_timer: 0.0,
            config,
        }
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
                self.players.queue_player_input(
                    peer,
                    QueuedInput {
                        input_flags: input.input_flags,
                        sequence: input.sequence,
                        aim_angle: input.aim_angle as f64,
                        position: Vec2::new(input.position.0, input.position.1),
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
        // Re-auth is unguarded (parity): overwrites identity and re-fires the broadcasts.
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

        let (entity_id, name, color, position) = {
            let Some(state) = self.players.get_mut(peer) else {
                return;
            };
            state.authenticated = true;
            // Dev mode (no ticket): server-assigned placeholder, unique among concurrent
            // players, so the D10 hydrate seam and per-character logs stay usable.
            state.character_id = auth
                .ticket
                .as_ref()
                .map(|t| t.character_id)
                .unwrap_or(1_000_000 + state.entity_id as u32);
            state.character_name = auth.character_name.clone();
            state.player_color = auth.color;
            state.bandwidth_budget_bps = effective;
            state.max_snapshot_bytes = per_peer_bytes;
            (
                state.entity_id,
                state.character_name.clone(),
                state.player_color,
                state.position,
            )
        };
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
            entity_id, &name, position, color,
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

        // 1. Inputs → movement steps → shoot spawns → move confirmations.
        let move_results = self.players.process_all_inputs(tick_dt, self.tick_count);
        self.process_shoot_inputs(outbox);
        for r in &move_results {
            if r.cheat_detected {
                debug!(
                    "cheat flagged: peer {} deviation past teleport threshold",
                    r.peer
                );
            }
            outbox.send(
                r.peer,
                ServerPacket::ActionConfirm(ActionConfirm {
                    sequence: r.sequence,
                    action: action_type::MOVE,
                    position: (r.position.x, r.position.y),
                    result: if r.success {
                        result_code::SUCCESS
                    } else {
                        result_code::FAILED_INVALID_POSITION
                    },
                    server_tick: (self.tick_count & 0xFFFF) as u16,
                    stamina: r.stamina,
                    mana: r.mana,
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
        }
        self.leaderboard_timer += tick_dt;
        if self.leaderboard_timer >= LEADERBOARD_BROADCAST_INTERVAL {
            self.leaderboard_timer = 0.0;
            outbox.broadcast(combat::leaderboard_event(&self.leaderboard));
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

        // 5. Collisions (players pass, then monsters pass).
        combat::process_collisions(
            &mut self.projectiles,
            &mut self.players,
            &mut self.monsters,
            &mut self.leaderboard,
            outbox,
            self.tick_count,
        );

        // 5b. D11 backstop (new): blatant unreported monster-bullet overlaps.
        self.backstop.update(
            self.config.backstop_grace_ticks,
            self.tick_count,
            &mut self.players,
            &mut self.projectiles,
            &mut self.leaderboard,
            outbox,
        );

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
        if let Some(proj) = self.projectiles.spawn_projectile(
            owner_id,
            spawn_pos,
            aim_dir,
            self.tick_count,
            rewind,
            pvp_rewind,
            PROJECTILE_SPEED,
            PLAYER_PROJECTILE_KNOCKBACK_FORCE,
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
        let config = ServerConfig::default();
        let verifier = TicketVerifier::new("", true, 0).unwrap();
        World::new(config, verifier, Pcg32::new(1234))
    }

    fn auth_packet(name: &str) -> ClientPacket {
        ClientPacket::ConnectAuth(protocol::ConnectAuth {
            protocol_version: protocol::PROTOCOL_VERSION,
            ticket: None,
            character_name: name.into(),
            color: (69, 135, 255),
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
        assert!((after.x - start.x - 200.0 / 30.0).abs() < 0.01);
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
}
