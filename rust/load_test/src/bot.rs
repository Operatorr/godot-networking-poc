//! One simulated player: its own ENet host/socket (so the server exercises the same per-peer
//! paths as for a real client), the auth handshake, snapshot/event tracking, and an input loop
//! whose movement prediction runs the real `sim_core::step_movement` — the same code the server
//! integrates against, so the positions the bot reports in `PlayerInput` are exactly what a real
//! client would predict.
//!
//! Lifecycle: ENet connect (`data` low byte = PROTOCOL_VERSION) → `ConnectAuth` with no ticket
//! (dev mode; requires the server's `allow_unsigned_tickets`, the default) → `AuthResult` →
//! 30 Hz inputs on ch2, `BaselineAck` per baseline on ch1, `LocalHitReport` for monster shots
//! (rate-limited like the real client), `RespawnRequest` 3.2 s after death.

use crate::behavior::{BehaviorKind, BehaviorState, KnownEntity, View};
use crate::metrics::BotMetrics;
use crate::rng::Pcg32;
use protocol::types::{delta_mask, disconnect_reason, entity_flags, MONSTER_ID_START};
use protocol::{ClientPacket, ConnectAuth, PlayerInput, ServerPacket, Snapshot};
use rusty_enet as enet;
use sim_core::{input_flags, movement_direction, step_movement, MovementSm, Vec2};
use std::collections::{HashMap, HashSet, VecDeque};
use std::net::{SocketAddr, UdpSocket};
use tracing::debug;

const CONNECT_TIMEOUT_S: f64 = 15.0;
/// D11 true-overlap radius: projectile 8 u + player hitbox 16 u.
const HIT_RADIUS: f32 = 24.0;
/// Mirror of the server's LOCAL_HIT_REPORT_MAX_PER_SECOND quota.
const HIT_REPORTS_MAX_PER_SECOND: usize = 20;
const RESPAWN_DELAY_S: f64 = 3.2;
const RESPAWN_REQUEST_MIN_INTERVAL_S: f64 = 1.0;
/// ENet seeds RTT at 500 ms; skip samples until real measurements settle.
const RTT_WARMUP_S: f64 = 2.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    /// ENet connect in flight.
    Connecting,
    /// Connected; ConnectAuth sent, awaiting AuthResult.
    Authing,
    /// Authenticated and playing.
    Running,
    /// We asked to disconnect; awaiting the ENet disconnect event.
    Closing,
    /// Clean shutdown complete.
    Closed,
    /// Connect/auth failure or unexpected drop; terminal.
    Failed,
}

pub struct Bot {
    pub id: u32,
    pub phase: Phase,
    pub metrics: BotMetrics,
    pub entity_id: u16,
    host: enet::Host<UdpSocket>,
    peer_key: usize,
    behavior: BehaviorState,
    rng: Pcg32,
    /// Player class — one of Warrior(4)/Rogue(5)/Mage(6), assigned round-robin by bot id so a
    /// swarm is split evenly across the three playable classes. Sent in ConnectAuth.
    player_class: u8,
    sm: MovementSm,
    pos: Vec2,
    vel: Vec2,
    seq: u8,
    last_aim: f32,
    input_interval: f64,
    next_input_at: f64,
    next_stats_at: f64,
    connect_started_at: f64,
    running_since: f64,
    last_rtt_ms: f64,
    server_tick_rate: u8,
    bandwidth_budget_bps: u32,
    entities: HashMap<u16, KnownEntity>,
    /// projectile id → owner entity id (from PROJECTILE_FIRED).
    projectile_owners: HashMap<u16, u16>,
    reported_projectiles: HashSet<u16>,
    hit_report_times: VecDeque<f64>,
    dead_since: Option<f64>,
    last_respawn_request_at: f64,
    /// True once we hold a server-authoritative own position (first baseline/confirm).
    pos_synced: bool,
    /// AoI observations pause until this time after a teleport (respawn): the server's AoI set
    /// needs a snapshot to re-evaluate around the new position, and stale far entities would
    /// otherwise log as false cull violations.
    aoi_grace_until: f64,
    /// Own authoritative HP, learned from `ActionConfirm.health` (the only HP source on the wire —
    /// snapshots carry no HP). `max_health` is the running max ever seen (full on spawn, so it
    /// converges to the true class/level max); together they give the HP fraction the strategy AI
    /// uses to decide whether to break off and grab a Healthorb.
    health: u16,
    max_health: u16,
}

impl Bot {
    #[allow(clippy::too_many_arguments)]
    pub fn connect(
        id: u32,
        server: SocketAddr,
        behavior: BehaviorKind,
        difficulty: f64,
        input_hz: f64,
        bandwidth_budget_bps: u32,
        seed: Option<u64>,
        now: f64,
    ) -> std::io::Result<Self> {
        let socket = UdpSocket::bind(("0.0.0.0", 0))?;
        let mut host = enet::Host::new(
            socket,
            enet::HostSettings {
                peer_limit: 1,
                channel_limit: protocol::CHANNEL_COUNT,
                ..Default::default()
            },
        )
        .map_err(|e| std::io::Error::other(format!("enet host: {e:?}")))?;
        let peer_key = host
            .connect(
                server,
                protocol::CHANNEL_COUNT,
                protocol::PROTOCOL_VERSION as u32,
            )
            .map_err(|_| std::io::Error::other("no available peer slot"))?
            .id()
            .0;
        let metrics = BotMetrics {
            bot_id: id,
            behavior: behavior.name(),
            ..Default::default()
        };
        // Reproducible per-bot stream when `--seed` is given (`seed ^ bot_id`, matching the rng
        // module contract); otherwise fall back to entropy for an unseeded run.
        let rng = match seed {
            Some(s) => Pcg32::new(s ^ id as u64),
            None => Pcg32::from_entropy(id as u64),
        };
        // Only the three playable classes are spawned, round-robin by bot id so a swarm is split
        // evenly (3 bots → 1 Warrior, 1 Rogue, 1 Mage). The other classes are disabled, and an even
        // split makes test runs reproducible and easy to read. ids: Warrior=4, Rogue=5, Mage=6.
        const SPAWN_CLASSES: [u8; 3] = [4, 5, 6];
        let player_class = SPAWN_CLASSES[(id as usize).wrapping_sub(1) % SPAWN_CLASSES.len()];
        debug!("bot {id} assigned class {player_class}");
        Ok(Self {
            id,
            phase: Phase::Connecting,
            metrics,
            entity_id: 0,
            host,
            peer_key,
            behavior: BehaviorState::new(behavior, difficulty, player_class),
            rng,
            player_class,
            sm: MovementSm::new(),
            pos: Vec2::ZERO,
            vel: Vec2::ZERO,
            seq: 0,
            last_aim: 0.0,
            input_interval: 1.0 / input_hz.max(1.0),
            next_input_at: 0.0,
            next_stats_at: 0.0,
            connect_started_at: now,
            running_since: 0.0,
            last_rtt_ms: 0.0,
            server_tick_rate: 30,
            bandwidth_budget_bps,
            entities: HashMap::new(),
            projectile_owners: HashMap::new(),
            reported_projectiles: HashSet::new(),
            hit_report_times: VecDeque::new(),
            dead_since: None,
            last_respawn_request_at: f64::NEG_INFINITY,
            pos_synced: false,
            health: 0,
            max_health: 0,
            aoi_grace_until: 0.0,
        })
    }

    pub fn is_settled(&self) -> bool {
        !matches!(self.phase, Phase::Connecting | Phase::Authing)
    }

    pub fn is_terminal(&self) -> bool {
        matches!(self.phase, Phase::Closed | Phase::Failed)
    }

    /// Drive the bot: drain ENet events, then run the input/stat clocks.
    pub fn poll(&mut self, now: f64) {
        if self.is_terminal() {
            return;
        }
        self.drain_events(now);
        match self.phase {
            Phase::Running => {
                if now >= self.next_input_at {
                    self.input_step(now);
                }
                if now >= self.next_stats_at {
                    self.sample_stats(now);
                }
            }
            Phase::Connecting | Phase::Authing
                if now - self.connect_started_at > CONNECT_TIMEOUT_S =>
            {
                self.fail("connect timeout".into());
                self.host.peer_mut(enet::PeerID(self.peer_key)).reset();
            }
            _ => {}
        }
    }

    /// Start a graceful disconnect; `poll` until `is_terminal` (or give up after a grace window).
    pub fn begin_disconnect(&mut self, now: f64) {
        match self.phase {
            Phase::Running | Phase::Authing | Phase::Connecting => {
                self.sample_stats(now);
                self.host
                    .peer_mut(enet::PeerID(self.peer_key))
                    .disconnect(disconnect_reason::USER_QUIT);
                self.phase = Phase::Closing;
            }
            _ => {}
        }
    }

    pub fn force_close(&mut self) {
        if !self.is_terminal() {
            self.host.peer_mut(enet::PeerID(self.peer_key)).reset();
            self.phase = Phase::Closed;
        }
    }

    /// Mark this bot crashed after a caught panic in `poll` (see `poll_all`). A single bad bot
    /// (e.g. a decode/sim edge case) must not take down the whole swarm, so the caller catches the
    /// unwind and routes it here: the bot goes terminal-Failed and is counted in the crash metric,
    /// while every other bot keeps running.
    pub fn mark_crashed(&mut self, error: String) {
        self.metrics.panic_count += 1;
        self.fail(error);
    }

    fn fail(&mut self, error: String) {
        debug!("bot {}: {error}", self.id);
        self.metrics.error_count += 1;
        self.metrics.last_error = error;
        self.phase = Phase::Failed;
    }

    // ── ENet event pump ─────────────────────────────────────────────────────

    fn drain_events(&mut self, now: f64) {
        loop {
            let event = match self.host.service() {
                Ok(Some(event)) => event.no_ref(),
                Ok(None) => return,
                Err(e) => {
                    self.fail(format!("enet service error: {e:?}"));
                    return;
                }
            };
            match event {
                enet::EventNoRef::Connect { .. } => {
                    if self.phase == Phase::Connecting {
                        self.send(&ClientPacket::ConnectAuth(ConnectAuth {
                            protocol_version: protocol::PROTOCOL_VERSION,
                            ticket: None, // dev mode (unsigned); D9 tickets come from the Go API
                            character_id: 0, // dev: no real character row to hydrate
                            character_name: format!("LoadBot{:03}", self.id),
                            color: color_for(self.id),
                            class: self.player_class,
                            bandwidth_budget_bps: self.bandwidth_budget_bps,
                        }));
                        self.phase = Phase::Authing;
                    }
                }
                enet::EventNoRef::Disconnect { data, .. } => {
                    if self.phase == Phase::Closing {
                        self.phase = Phase::Closed;
                    } else {
                        self.metrics.unexpected_disconnect = true;
                        self.fail(format!("server disconnected (reason {data})"));
                    }
                    return;
                }
                enet::EventNoRef::Receive { packet, .. } => {
                    self.metrics.packets_received += 1;
                    self.metrics.bytes_received += packet.data().len() as u64;
                    match ServerPacket::decode(packet.data()) {
                        Ok(pkt) => self.handle_server_packet(pkt, now),
                        Err(e) => {
                            self.metrics.decode_failures += 1;
                            debug!("bot {}: bad server packet: {e}", self.id);
                        }
                    }
                }
            }
        }
    }

    fn handle_server_packet(&mut self, packet: ServerPacket, now: f64) {
        match packet {
            ServerPacket::AuthResult(a) => match a.ok {
                Some(ok) if a.result == protocol::types::auth_result_code::OK => {
                    self.entity_id = ok.entity_id;
                    self.server_tick_rate = ok.tick_rate.max(1);
                    self.metrics.first_server_tick.get_or_insert(ok.server_tick);
                    self.metrics.last_server_tick = ok.server_tick;
                    self.metrics.connected_ok = true;
                    self.metrics.connection_time_ms = (now - self.connect_started_at) * 1000.0;
                    self.phase = Phase::Running;
                    self.running_since = now;
                    self.next_input_at = now;
                    self.next_stats_at = now + 1.0;
                    debug!("bot {} authenticated as entity {}", self.id, ok.entity_id);
                }
                _ => self.fail(format!("auth rejected (code {})", a.result)),
            },
            ServerPacket::Snapshot(s) => self.apply_snapshot(&s, now),
            ServerPacket::ActionConfirm(c) => {
                self.metrics.action_confirms_received += 1;
                // The confirm is the authoritative answer to our input: adopt position and
                // resources (poor man's reconciliation — bots don't replay).
                self.pos = Vec2::new(c.position.0, c.position.1);
                self.pos_synced = true;
                self.sm.set_resources(c.stamina as f64, c.mana as f64);
                // Track HP for the strategy AI's orb-seek decision. max_health is the running max
                // (HP is full on spawn/respawn, so this latches the true class/level max).
                self.health = c.health;
                self.max_health = self.max_health.max(c.health);
            }
            ServerPacket::GameEvent(e) => {
                self.metrics.game_events_received += 1;
                use protocol::types::game_event_type as t;
                match e.event_type {
                    t::PROJECTILE_FIRED => {
                        // target_id = projectile id, source_id = its owner. Record EVERY shot —
                        // monster, player, AND other bots — so the strategy AI can dodge incoming
                        // PvP fire, not just monster bullets. (`scan_for_monster_hits` re-filters to
                        // monster owners for client-authoritative PvE hit reports; PvP hits are
                        // server-authoritative and must never be self-reported.)
                        if e.target_id != 0 {
                            self.projectile_owners.insert(e.target_id, e.source_id);
                        }
                    }
                    t::KILL | t::KILL_PVP => {
                        if e.target_id == self.entity_id && self.dead_since.is_none() {
                            self.dead_since = Some(now);
                        }
                    }
                    t::RESPAWN if e.target_id == self.entity_id => {
                        if let protocol::GameEventData::Respawn { x, y } = e.data {
                            self.pos = Vec2::new(x, y);
                        }
                        self.dead_since = None;
                        self.sm.reset();
                        self.vel = Vec2::ZERO;
                        self.health = self.max_health; // respawn restores full HP
                        self.aoi_grace_until = now + 1.0;
                    }
                    _ => {}
                }
            }
            ServerPacket::ServerMetrics(m) => {
                self.metrics.latest_server_metrics = Some((now, m));
            }
        }
    }

    fn apply_snapshot(&mut self, s: &Snapshot, now: f64) {
        self.metrics.state_updates_received += 1;
        self.metrics.first_server_tick.get_or_insert(s.server_tick);
        self.metrics.last_server_tick = self.metrics.last_server_tick.max(s.server_tick);

        if s.is_baseline {
            self.metrics.baselines_received += 1;
            // A baseline is the full AoI state: replace the world model and ack it.
            self.entities.clear();
            self.send(&ClientPacket::BaselineAck {
                baseline_tick: s.server_tick,
            });
        }

        // Adopt our own authoritative position before measuring anyone else: records arrive in
        // arbitrary order, and AoI distances taken against a stale (or never-synced) own
        // position would log false cull violations.
        if let Some(p) = s
            .entities
            .iter()
            .find(|r| r.entity_id == self.entity_id)
            .and_then(|r| r.position)
        {
            if s.is_baseline || !self.pos_synced {
                self.pos = Vec2::new(p.0, p.1);
                self.pos_synced = true;
            }
        }

        let tick_rate = self.server_tick_rate as f32;
        for rec in &s.entities {
            if rec.delta_mask & delta_mask::FULL == 0 && rec.delta_mask & delta_mask::REMOVED != 0 {
                self.entities.remove(&rec.entity_id);
                self.projectile_owners.remove(&rec.entity_id);
                self.reported_projectiles.remove(&rec.entity_id);
                continue;
            }
            let e = self.entities.entry(rec.entity_id).or_insert(KnownEntity {
                pos: rec.position.unwrap_or((0.0, 0.0)),
                vel: (0.0, 0.0),
                anim: 0,
                flags: entity_flags::ALIVE,
                last_tick: s.server_tick,
            });
            if let Some(p) = rec.position {
                let dt_ticks = s.server_tick.saturating_sub(e.last_tick);
                if dt_ticks > 0 {
                    let dt = dt_ticks as f32 / tick_rate;
                    e.vel = ((p.0 - e.pos.0) / dt, (p.1 - e.pos.1) / dt);
                }
                e.pos = p;
            }
            if let Some(a) = rec.animation {
                e.anim = a;
            }
            if let Some(f) = rec.flags {
                e.flags = f;
            }
            e.last_tick = s.server_tick;

            if rec.entity_id == self.entity_id {
                // Death/revival from the replicated ALIVE bit (the events cover the rest).
                if let Some(f) = rec.flags {
                    if f & entity_flags::ALIVE == 0 {
                        self.dead_since.get_or_insert(now);
                    } else if self.dead_since.is_some() {
                        self.dead_since = None;
                        self.sm.reset();
                        if let Some(p) = rec.position {
                            self.pos = Vec2::new(p.0, p.1);
                        }
                        self.aoi_grace_until = now + 1.0;
                    }
                    // Daze slaved to the replicated DAZED flag (flags arrive on change, so
                    // this is edge-driven): apply the full duration on set, clear on drop —
                    // keeps the bot's predicted sprint in step with the authoritative walk.
                    if f & entity_flags::DAZED != 0 {
                        self.sm
                            .apply_daze(sim_core::constants::PLAYER_DAZE_DURATION);
                    } else {
                        self.sm.clear_daze();
                    }
                }
            } else if self.pos_synced && now >= self.aoi_grace_until {
                // AoI cull assertion input: how far away do we ever see entities?
                if let Some(p) = rec.position {
                    let (dx, dy) = (p.0 - self.pos.x, p.1 - self.pos.y);
                    let d = (dx * dx + dy * dy).sqrt();
                    if d > self.metrics.max_observed_entity_distance {
                        self.metrics.max_observed_entity_distance = d;
                    }
                }
            }
        }
    }

    // ── Input loop ──────────────────────────────────────────────────────────

    fn input_step(&mut self, now: f64) {
        self.next_input_at += self.input_interval;
        if self.next_input_at < now {
            // Fell behind (host stall); don't burst-send to catch up.
            self.next_input_at = now + self.input_interval;
        }

        let mut flags: u16 = 0;
        // Cursor world position for cursor-targeted ability casts; `None` ⇒ the bot's own position.
        let mut cursor: Option<(f32, f32)> = None;
        if self.dead_since.is_some() {
            self.maybe_request_respawn(now);
            // Keep sending zero-input frames while dead, like an idle client.
        } else {
            let decision = {
                // HP fraction for the orb-seek decision; treat "unknown HP" (no confirm yet) as
                // full so a fresh bot never thinks it is hurt before its first ActionConfirm.
                let hp_fraction = if self.max_health > 0 {
                    self.health as f64 / self.max_health as f64
                } else {
                    1.0
                };
                let view = View {
                    my_id: self.entity_id,
                    pos: (self.pos.x, self.pos.y),
                    stamina: self.sm.stamina(),
                    hp_fraction,
                    entities: &self.entities,
                    projectile_owners: &self.projectile_owners,
                };
                self.behavior.decide(&view, &mut self.rng, now)
            };
            flags = decision.flags;
            self.last_aim = decision.aim_angle;
            cursor = decision.cursor;
            let aim = self.last_aim as f64;
            let aim_dir = Vec2::new(aim.cos() as f32, aim.sin() as f32);
            let result = step_movement(
                &mut self.sm,
                self.pos,
                self.input_interval,
                movement_direction(flags),
                flags & input_flags::SPRINT != 0,
                flags & input_flags::DASH != 0,
                flags & input_flags::ABILITY != 0,
                flags & input_flags::SHOOT != 0,
                aim_dir,
            );
            self.pos = result.position;
            self.vel = result.velocity;
            self.scan_for_monster_hits(now);
        }

        let input = ClientPacket::PlayerInput(PlayerInput {
            sequence: self.seq,
            input_flags: flags,
            aim_angle: self.last_aim,
            position: (self.pos.x, self.pos.y),
            velocity: (self.vel.x, self.vel.y),
            // Target world position for cursor-aimed casts (Rogue/Mage); own position otherwise.
            cursor: cursor.unwrap_or((self.pos.x, self.pos.y)),
            client_render_tick: (self.metrics.last_server_tick & 0xFFFF) as u16,
            client_rtt_ms: self.last_rtt_ms.clamp(0.0, u16::MAX as f64) as u16,
        });
        self.seq = self.seq.wrapping_add(1);
        self.send(&input);
    }

    /// Monster→player hits are client-authoritative (RotMG model): a bot that never reports
    /// takes no monster damage, so report true overlaps like a real client would. Once per
    /// projectile, ≤ 20/s (mirrors the server's quota — exceeding it just wastes packets).
    fn scan_for_monster_hits(&mut self, now: f64) {
        while self.hit_report_times.front().is_some_and(|t| now - t > 1.0) {
            self.hit_report_times.pop_front();
        }
        let mut hits: Vec<u16> = Vec::new();
        for (&pid, &owner) in &self.projectile_owners {
            if owner < MONSTER_ID_START || self.reported_projectiles.contains(&pid) {
                continue;
            }
            let Some(e) = self.entities.get(&pid) else {
                continue;
            };
            let (dx, dy) = (e.pos.0 - self.pos.x, e.pos.1 - self.pos.y);
            if dx * dx + dy * dy < HIT_RADIUS * HIT_RADIUS {
                hits.push(pid);
            }
        }
        for pid in hits {
            if self.hit_report_times.len() >= HIT_REPORTS_MAX_PER_SECOND {
                break;
            }
            self.reported_projectiles.insert(pid);
            self.hit_report_times.push_back(now);
            self.metrics.hit_reports_sent += 1;
            self.send(&ClientPacket::LocalHitReport { projectile_id: pid });
        }
    }

    fn maybe_request_respawn(&mut self, now: f64) {
        let Some(since) = self.dead_since else { return };
        if now - since >= RESPAWN_DELAY_S
            && now - self.last_respawn_request_at >= RESPAWN_REQUEST_MIN_INTERVAL_S
        {
            self.last_respawn_request_at = now;
            self.metrics.respawn_requests_sent += 1;
            self.send(&ClientPacket::RespawnRequest);
        }
    }

    fn sample_stats(&mut self, now: f64) {
        self.next_stats_at = now + 1.0;
        let peer = self.host.peer_mut(enet::PeerID(self.peer_key));
        if peer.connected() {
            let rtt = peer.round_trip_time().as_secs_f64() * 1000.0;
            self.last_rtt_ms = rtt;
            if now - self.running_since >= RTT_WARMUP_S {
                self.metrics.latencies_ms.push(rtt);
            }
            // ENET_PEER_PACKET_LOSS_SCALE = 1 << 16.
            self.metrics.enet_packet_loss = peer.packet_loss() as f64 / 65536.0;
        }
    }

    fn send(&mut self, packet: &ClientPacket) {
        let bytes = packet.encode();
        let enet_packet = if packet.reliable() {
            enet::Packet::reliable(bytes.as_slice())
        } else {
            enet::Packet::unreliable(bytes.as_slice())
        };
        let peer = self.host.peer_mut(enet::PeerID(self.peer_key));
        match peer.send(packet.channel(), &enet_packet) {
            Ok(()) => {
                self.metrics.packets_sent += 1;
                self.metrics.bytes_sent += bytes.len() as u64;
            }
            Err(e) => {
                // A swallowed send failure hides lost handshakes (ConnectAuth/BaselineAck) and
                // inputs. Count and log it so the failure is observable in the report rather than
                // vanishing.
                self.metrics.send_failures += 1;
                debug!(
                    "bot {}: send failed on channel {}: {e}",
                    self.id,
                    packet.channel()
                );
            }
        }
    }
}

/// Deterministic per-bot color so swarms look distinguishable in a spectating client.
fn color_for(id: u32) -> (u8, u8, u8) {
    let h = id.wrapping_mul(2654435761);
    (
        64 + (h & 0x7F) as u8 + 64,
        64 + ((h >> 8) & 0x7F) as u8 + 64,
        64 + ((h >> 16) & 0x7F) as u8 + 64,
    )
}
