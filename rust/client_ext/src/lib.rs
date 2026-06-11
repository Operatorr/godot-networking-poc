//! Omega Realm client GDExtension (migration-spec D5/D6): exposes the shared `sim_core`
//! (prediction) and the `protocol` codec to GDScript. The client encodes/decodes packets by
//! calling this extension — there is no GDScript codec.
//!
//! Decoded packets are returned as Dictionaries with the LEGACY `NetworkManager.MessageType`
//! ids and the exact field shapes the GDScript listeners already consume
//! (extraction client-integration §6.1), so the dispatch fan-out stays unchanged. The new
//! `AuthResult` packet maps to message type 14.

use godot::prelude::*;
use protocol::types::snapshot_flags;
use protocol::{ClientPacket, ConnectAuth, PlayerInput, ServerPacket};
use sim_core::{arena, hit, MovementSm, Vec2 as SimVec2};

struct OmegaClientExt;

#[gdextension]
unsafe impl ExtensionLibrary for OmegaClientExt {}

// Legacy MessageType values (NetworkManager.MessageType) the decode surface reports.
const MSG_STATE_UPDATE: i64 = 2;
const MSG_GAME_EVENT: i64 = 3;
const MSG_ACTION_CONFIRM: i64 = 5;
const MSG_SERVER_METRICS: i64 = 10;
/// New in the redesign: the explicit auth answer (D9).
const MSG_AUTH_RESULT: i64 = 14;

// Legacy GDScript delta-mask bit values (PacketTypes.DELTA_MASK_*).
const LEGACY_MASK_POSITION: i64 = 1;
const LEGACY_MASK_ANIMATION: i64 = 2;
const LEGACY_MASK_FLAGS: i64 = 4;
const LEGACY_MASK_REMOVED: i64 = 64;
const LEGACY_MASK_FULL_STATE: i64 = 128;

fn legacy_mask(mask: u8) -> i64 {
    use protocol::types::delta_mask as m;
    let mut out = 0;
    if mask & m::POSITION != 0 {
        out |= LEGACY_MASK_POSITION;
    }
    if mask & m::ANIMATION != 0 {
        out |= LEGACY_MASK_ANIMATION;
    }
    if mask & m::FLAGS != 0 {
        out |= LEGACY_MASK_FLAGS;
    }
    if mask & m::REMOVED != 0 {
        out |= LEGACY_MASK_REMOVED;
    }
    if mask & m::FULL != 0 {
        out |= LEGACY_MASK_FULL_STATE;
    }
    out
}

fn v2(x: f32, y: f32) -> Vector2 {
    Vector2::new(x, y)
}

fn sim(v: Vector2) -> SimVec2 {
    SimVec2::new(v.x, v.y)
}

fn from_sim(v: SimVec2) -> Vector2 {
    Vector2::new(v.x, v.y)
}

/// The wire codec (D6/D7): one boundary call per packet, raw bytes across.
#[derive(GodotClass)]
#[class(init, base=RefCounted)]
pub struct ProtocolCodec {
    base: Base<RefCounted>,
}

#[godot_api]
impl ProtocolCodec {
    /// Protocol version for the ENet `connect_to_host` data argument and ConnectAuth.
    #[func]
    fn protocol_version() -> i64 {
        protocol::PROTOCOL_VERSION as i64
    }

    /// ENet channel plan (D2).
    #[func]
    fn channel_snapshot() -> i64 {
        protocol::CH_SNAPSHOT as i64
    }

    #[func]
    fn channel_reliable() -> i64 {
        protocol::CH_RELIABLE as i64
    }

    #[func]
    fn channel_input() -> i64 {
        protocol::CH_INPUT as i64
    }

    // ── Encode (client → server) ────────────────────────────────────────────

    #[allow(clippy::too_many_arguments)]
    #[func]
    fn encode_input(
        &self,
        position: Vector2,
        velocity: Vector2,
        input_flags: i64,
        aim_angle: f64,
        sequence: i64,
        client_render_tick: i64,
        client_rtt_ms: i64,
    ) -> PackedByteArray {
        let pkt = ClientPacket::PlayerInput(PlayerInput {
            sequence: (sequence & 0xFF) as u8,
            input_flags: (input_flags & 0xFFFF) as u16,
            aim_angle: aim_angle as f32,
            position: (position.x, position.y),
            velocity: (velocity.x, velocity.y),
            client_render_tick: (client_render_tick & 0xFFFF) as u16,
            client_rtt_ms: client_rtt_ms.clamp(0, 65535) as u16,
        });
        PackedByteArray::from(pkt.encode().as_slice())
    }

    /// `ticket` empty ⇒ dev-mode join (server must run with unsigned tickets allowed).
    /// A NON-empty but malformed ticket returns an empty PackedByteArray: silently downgrading
    /// corruption to an unsigned join would mask it (and join as the wrong identity on a
    /// dev server) — the caller must abort the handshake instead.
    #[func]
    fn encode_connect_auth(
        &self,
        character_name: GString,
        player_color: Color,
        bandwidth_budget_bps: i64,
        ticket: PackedByteArray,
    ) -> PackedByteArray {
        let ticket = if ticket.is_empty() {
            None
        } else {
            match protocol::Ticket::from_bytes(ticket.as_slice()) {
                Ok(t) => Some(t),
                Err(e) => {
                    godot_error!("encode_connect_auth: malformed ticket blob ({e}); refusing");
                    return PackedByteArray::new();
                }
            }
        };
        let quant = |c: f32| -> u8 { (c * 255.0).round().clamp(0.0, 255.0) as u8 };
        let pkt = ClientPacket::ConnectAuth(ConnectAuth {
            protocol_version: protocol::PROTOCOL_VERSION,
            ticket,
            character_name: character_name.to_string(),
            color: (
                quant(player_color.r),
                quant(player_color.g),
                quant(player_color.b),
            ),
            bandwidth_budget_bps: bandwidth_budget_bps.max(0) as u32,
        });
        PackedByteArray::from(pkt.encode().as_slice())
    }

    #[func]
    fn encode_baseline_ack(&self, baseline_tick: i64) -> PackedByteArray {
        let pkt = ClientPacket::BaselineAck {
            baseline_tick: baseline_tick as u32,
        };
        PackedByteArray::from(pkt.encode().as_slice())
    }

    #[func]
    fn encode_request_full_state(&self) -> PackedByteArray {
        PackedByteArray::from(ClientPacket::RequestFullState.encode().as_slice())
    }

    #[func]
    fn encode_respawn_request(&self) -> PackedByteArray {
        PackedByteArray::from(ClientPacket::RespawnRequest.encode().as_slice())
    }

    #[func]
    fn encode_local_hit_report(&self, projectile_id: i64) -> PackedByteArray {
        let pkt = ClientPacket::LocalHitReport {
            projectile_id: (projectile_id & 0xFFFF) as u16,
        };
        PackedByteArray::from(pkt.encode().as_slice())
    }

    // ── Decode (server → client) ────────────────────────────────────────────

    /// Returns `{}` on a malformed packet (caller drops + logs). Otherwise a Dictionary with
    /// `"type"` set to the legacy MessageType id and the §6.1 field shapes.
    #[func]
    fn decode_server_packet(&self, bytes: PackedByteArray) -> VarDictionary {
        let mut out = VarDictionary::new();
        let pkt = match ServerPacket::decode(bytes.as_slice()) {
            Ok(p) => p,
            Err(e) => {
                godot_warn!("decode_server_packet: {e}");
                return out;
            }
        };
        match pkt {
            ServerPacket::AuthResult(r) => {
                out.set("type", MSG_AUTH_RESULT);
                out.set("result", r.result as i64);
                if let Some(ok) = r.ok {
                    out.set("entity_id", ok.entity_id as i64);
                    out.set("server_tick", ok.server_tick as i64);
                    out.set("tick_rate", ok.tick_rate as i64);
                }
            }
            ServerPacket::Snapshot(s) => {
                out.set("type", MSG_STATE_UPDATE);
                out.set("server_tick", s.server_tick as i64);
                out.set("server_ms", s.server_ms as i64);
                let mut flags = 0i64;
                if s.baseline_tick.is_some() {
                    flags |= snapshot_flags::IS_DELTA as i64;
                }
                if s.is_baseline {
                    flags |= snapshot_flags::BASELINE as i64;
                }
                out.set("state_flags", flags);
                out.set("baseline_tick", s.baseline_tick.unwrap_or(0) as i64);
                let mut entities = VarArray::new();
                for rec in &s.entities {
                    let mut e = VarDictionary::new();
                    e.set("entity_id", rec.entity_id as i64);
                    e.set(
                        "entity_type",
                        rec.entity_type().map(|t| t as i64).unwrap_or(1),
                    );
                    let (x, y) = rec.position.unwrap_or((0.0, 0.0));
                    e.set("position", v2(x, y));
                    e.set("animation_state", rec.animation.unwrap_or(0) as i64);
                    e.set("flags", rec.flags.unwrap_or(0) as i64);
                    e.set("delta_mask", legacy_mask(rec.delta_mask));
                    entities.push(&e.to_variant());
                }
                out.set("entities", &entities);
            }
            ServerPacket::ActionConfirm(c) => {
                out.set("type", MSG_ACTION_CONFIRM);
                out.set("sequence_number", c.sequence as i64);
                out.set("action_type", c.action as i64);
                out.set("corrected_position", v2(c.position.0, c.position.1));
                out.set("result_code", c.result as i64);
                out.set("server_tick", c.server_tick as i64);
                out.set("stamina", c.stamina as i64);
                out.set("mana", c.mana as i64);
            }
            ServerPacket::GameEvent(e) => {
                out.set("type", MSG_GAME_EVENT);
                out.set("event_type", e.event_type as i64);
                out.set("source_id", e.source_id as i64);
                out.set("target_id", e.target_id as i64);
                let mut data = VarDictionary::new();
                match e.data {
                    protocol::GameEventData::None => {}
                    protocol::GameEventData::Damage {
                        amount,
                        damage_type,
                    } => {
                        data.set("amount", amount as i64);
                        data.set("damage_type", damage_type as i64);
                    }
                    protocol::GameEventData::Respawn { x, y } => {
                        data.set("position", v2(x, y));
                    }
                    protocol::GameEventData::EffectApply {
                        effect_id,
                        duration_ms,
                    } => {
                        data.set("effect_id", effect_id as i64);
                        data.set("duration_ms", duration_ms as i64);
                    }
                    protocol::GameEventData::EffectRemove { effect_id } => {
                        data.set("effect_id", effect_id as i64);
                    }
                    protocol::GameEventData::PlayerInfo { name, x, y, color } => {
                        data.set("character_name", &GString::from(name.as_str()));
                        data.set("position", v2(x, y));
                        data.set(
                            "player_color",
                            Color::from_rgb(
                                color.0 as f32 / 255.0,
                                color.1 as f32 / 255.0,
                                color.2 as f32 / 255.0,
                            ),
                        );
                    }
                    protocol::GameEventData::Leaderboard { entries } => {
                        let mut arr = VarArray::new();
                        for (entity_id, pvp_kills) in entries {
                            let mut row = VarDictionary::new();
                            row.set("entity_id", entity_id as i64);
                            row.set("pvp_kills", pvp_kills as i64);
                            arr.push(&row.to_variant());
                        }
                        data.set("entries", &arr);
                    }
                    protocol::GameEventData::ProjectileFired { x, y, fire_tick } => {
                        data.set("position", v2(x, y));
                        data.set("server_tick", fire_tick as i64);
                    }
                }
                out.set("event_data", &data);
            }
            ServerPacket::ServerMetrics(m) => {
                out.set("type", MSG_SERVER_METRICS);
                out.set("tick_count", m.tick_count as i64);
                out.set("avg_tick_time_ms", m.avg_tick_time_ms_x100 as f64 / 100.0);
                out.set("max_tick_time_ms", m.max_tick_time_ms_x100 as f64 / 100.0);
                out.set("player_count", m.player_count as i64);
                out.set("entity_count", m.entity_count as i64);
                out.set("total_bytes_sent", m.total_bytes_sent as i64);
                out.set("total_bytes_received", m.total_bytes_received as i64);
                out.set(
                    "avg_bandwidth_per_client",
                    m.avg_bandwidth_per_client as i64,
                );
                out.set("sched_entities_deferred", m.sched_entities_deferred as i64);
                out.set(
                    "sched_max_queue_age_ticks",
                    m.sched_max_queue_age_ticks as i64,
                );
                out.set(
                    "sched_peers_at_budget_pct",
                    m.sched_peers_at_budget_pct as i64,
                );
                out.set("sched_peers_evaluated", m.sched_peers_evaluated as i64);
                out.set("sched_snapshot_overflow", m.sched_snapshot_overflow as i64);
            }
        }
        out
    }
}

/// The local player's prediction sim (D5): owns the shared `MovementSm` so prediction runs
/// LITERALLY the same code as the server's authoritative step.
#[derive(GodotClass)]
#[class(init, base=RefCounted)]
pub struct PredictionSim {
    base: Base<RefCounted>,
    sm: MovementSm,
}

#[godot_api]
impl PredictionSim {
    /// One full prediction step: SM tick → analytic mover → realized velocity.
    /// Mirrors the server's `PlayerState.step` movement stages exactly.
    #[allow(clippy::too_many_arguments)]
    #[func]
    fn step(
        &mut self,
        delta: f64,
        position: Vector2,
        move_dir: Vector2,
        sprint_held: bool,
        dash_held: bool,
        ability_held: bool,
        attacking: bool,
        aim_dir: Vector2,
    ) -> VarDictionary {
        let result = sim_core::step_movement(
            &mut self.sm,
            sim(position),
            delta,
            sim(move_dir),
            sprint_held,
            dash_held,
            ability_held,
            attacking,
            sim(aim_dir),
        );
        let mut out = VarDictionary::new();
        out.set("position", from_sim(result.position));
        out.set("velocity", from_sim(result.velocity));
        out.set("state", self.sm.state() as i64);
        out.set("stamina", self.sm.stamina());
        out.set("mana", self.sm.mana());
        out.set("dash_cooldown", self.sm.dash_cooldown_remaining());
        out
    }

    /// Reconciliation replay step — the deliberately-stateless ground-speed model (sprint
    /// gated by CURRENT stamina; never dash/knockback). Does not mutate the SM.
    #[func]
    fn replay_step(&self, position: Vector2, input_flags: i64, delta: f64) -> VarDictionary {
        let result = sim_core::replay_ground_step(
            &self.sm,
            sim(position),
            (input_flags & 0xFFFF) as u16,
            delta,
        );
        let mut out = VarDictionary::new();
        out.set("position", from_sim(result.position));
        out.set("velocity", from_sim(result.velocity));
        out
    }

    #[func]
    fn movement_direction(&self, input_flags: i64) -> Vector2 {
        from_sim(sim_core::movement_direction((input_flags & 0xFFFF) as u16))
    }

    #[func]
    fn ground_speed(&self, is_sprinting: bool) -> f64 {
        self.sm.ground_speed(is_sprinting)
    }

    #[func]
    fn stamina(&self) -> f64 {
        self.sm.stamina()
    }

    #[func]
    fn mana(&self) -> f64 {
        self.sm.mana()
    }

    #[func]
    fn movement_state(&self) -> i64 {
        self.sm.state() as i64
    }

    /// Authoritative resource correction from ActionConfirm (clamped 0..100 inside sim_core so
    /// client and server clamp identically).
    #[func]
    fn set_resources(&mut self, new_stamina: f64, new_mana: f64) {
        self.sm.set_resources(new_stamina, new_mana);
    }

    /// Daze slaved to the server's DAZED entity flag: apply on the rising edge (sprint/dash
    /// lock out locally so prediction matches the authoritative walk), clear when the flag
    /// drops. The local timer self-expires as a lost-packet backstop.
    #[func]
    fn apply_daze(&mut self, duration: f64) {
        self.sm.apply_daze(duration);
    }

    #[func]
    fn clear_daze(&mut self) {
        self.sm.clear_daze();
    }

    #[func]
    fn is_dazed(&self) -> bool {
        self.sm.is_dazed()
    }

    /// Reset to a clean alive state (spawn / respawn).
    #[func]
    fn reset(&mut self) {
        self.sm.reset();
    }

    /// The shared analytic mover — byte-identical to the server's.
    #[func]
    fn move_with_obstacle_collision(&self, from: Vector2, to: Vector2, radius: f32) -> Vector2 {
        from_sim(arena::move_with_obstacle_collision(
            sim(from),
            sim(to),
            radius,
        ))
    }

    #[func]
    fn tick_interval(&self) -> f64 {
        sim_core::constants::SERVER_TICK_INTERVAL
    }
}

/// The hit-authority predicates (D11) — shared with the server through sim_core, so the rules
/// can only drift in one place.
#[derive(GodotClass)]
#[class(init, base=RefCounted)]
pub struct SimHit {
    base: Base<RefCounted>,
}

#[godot_api]
impl SimHit {
    #[func]
    fn is_client_authoritative(owner_id: i64) -> bool {
        owner_id >= 0 && hit::is_client_authoritative(owner_id.min(u16::MAX as i64) as u16)
    }

    #[func]
    fn swept_hit(self_pos: Vector2, prev_pos: Vector2, cur_pos: Vector2, hit_radius: f32) -> bool {
        hit::swept_hit(sim(self_pos), sim(prev_pos), sim(cur_pos), hit_radius)
    }

    #[func]
    fn flight_origin(
        current_position: Vector2,
        direction: Vector2,
        distance_traveled: f32,
    ) -> Vector2 {
        from_sim(hit::flight_origin(
            sim(current_position),
            sim(direction),
            distance_traveled,
        ))
    }
}
