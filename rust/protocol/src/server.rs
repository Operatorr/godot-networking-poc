//! Server→client packets.

use crate::bits::{BitReader, BitWriter};
use crate::error::DecodeError;
use crate::quant::{dequant_coord, quant_coord};
use crate::snapshot::Snapshot;
use crate::types::{game_event_type, server_type};

/// New in the redesign (D9): the explicit auth answer. `Ok` carries the entity id, giving the
/// client Authority sync without waiting for the PLAYER_INFO broadcast (which is still sent for
/// names/colors of everyone).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthResult {
    /// `types::auth_result_code` value.
    pub result: u8,
    /// Present iff `result == OK`.
    pub ok: Option<AuthOk>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthOk {
    pub entity_id: u16,
    pub server_tick: u32,
    pub tick_rate: u8,
}

/// ACTION_CONFIRM successor — same fields as today (extraction §4.16). Owner-only, ~one per
/// processed input; rides ch0 (a newer confirm supersedes a lost one).
#[derive(Debug, Clone, PartialEq)]
pub struct ActionConfirm {
    pub sequence: u8,
    pub action: u8,
    pub position: (f32, f32),
    pub result: u8,
    pub server_tick: u16,
    pub stamina: u8,
    pub mana: u8,
    /// Authoritative dash + RMB-ability cooldowns (deciseconds; `quant_cooldown`). The owner
    /// reconciles its PREDICTED cooldowns against these so a refused / lost / cooldown-boundary
    /// dash or cast can't leave the client's cooldown permanently out of phase with the server.
    pub dash_cooldown: u8,
    pub ability_cooldown: u8,
    /// Authoritative current HP for the owner's HUD bar. HP is not carried in snapshots, so the
    /// owner reconciles its display-only HP against this (like stamina/mana above) — keeping the
    /// bar in step with server-side regen and any damage the client's delta tracking missed.
    pub health: u16,
}

/// GAME_EVENT — common head + per-type tail, identical semantics to today (extraction §4.15).
#[derive(Debug, Clone, PartialEq)]
pub struct GameEvent {
    pub event_type: u8,
    pub source_id: u16,
    pub target_id: u16,
    pub data: GameEventData,
}

impl GameEvent {
    /// The data variant the decoder expects for this event_type (everything else is head-only).
    pub(crate) fn data_matches_type(&self) -> bool {
        use crate::types::game_event_type as t;
        match self.event_type {
            t::DAMAGE => matches!(self.data, GameEventData::Damage { .. }),
            t::RESPAWN => matches!(self.data, GameEventData::Respawn { .. }),
            t::EFFECT_APPLY => matches!(self.data, GameEventData::EffectApply { .. }),
            t::EFFECT_REMOVE => matches!(self.data, GameEventData::EffectRemove { .. }),
            t::PLAYER_INFO => matches!(self.data, GameEventData::PlayerInfo { .. }),
            t::LEADERBOARD_UPDATE => matches!(self.data, GameEventData::Leaderboard { .. }),
            t::PROJECTILE_FIRED => matches!(self.data, GameEventData::ProjectileFired { .. }),
            t::EXP_GAIN => matches!(self.data, GameEventData::ExpGain { .. }),
            t::ABILITY_EFFECT => matches!(self.data, GameEventData::AbilityEffect { .. }),
            t::PROGRESS => matches!(self.data, GameEventData::Progress { .. }),
            t::PICKUP => matches!(self.data, GameEventData::Pickup { .. }),
            _ => matches!(self.data, GameEventData::None),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum GameEventData {
    None,
    Damage {
        amount: u16,
        damage_type: u8,
    },
    Respawn {
        x: f32,
        y: f32,
    },
    EffectApply {
        effect_id: u8,
        duration_ms: u16,
    },
    EffectRemove {
        effect_id: u8,
    },
    PlayerInfo {
        name: String,
        x: f32,
        y: f32,
        color: (u8, u8, u8),
        /// Player class (0=Zealot … 6=Mage). Already server-clamped when broadcast.
        class: u8,
    },
    Leaderboard {
        entries: Vec<(u16, u16)>,
    },
    /// `target_id` of the enclosing event is the projectile id — MUST be non-zero for monster
    /// shots (D11 carried-forward invariant).
    ProjectileFired {
        x: f32,
        y: f32,
        fire_tick: u16,
    },
    /// Experience gained by `source_id` (a nearby monster died) — a cosmetic "+XP" floater.
    /// The SERVER owns level/XP accounting now (see `Progress`); this is display-only.
    ExpGain {
        amount: u16,
    },
    /// A transient ability effect to render at (`x`, `y`). `effect_id` selects the VFX (explosion,
    /// charge blast, shadowstep blink, mine detonation); `radius` (units) sizes it (0 = point).
    AbilityEffect {
        effect_id: u8,
        x: f32,
        y: f32,
        radius: u16,
    },
    /// Authoritative progression for the owning player's HUD. `move_speed_q` = effective base
    /// move speed ÷ 4 (clamped 0..255), so the client adopts the same speed without re-deriving it.
    Progress {
        level: u16,
        experience: u32,
        move_speed_q: u8,
    },
    /// A pickup was consumed by `target_id`. `kind` selects the pickup type (0 = healthorb);
    /// `amount` is the magnitude (e.g. HP restored), for the client's floater.
    Pickup {
        kind: u8,
        amount: u16,
    },
}

/// SERVER_METRICS — same 13-field set as today (extraction §4.18), 1 Hz.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ServerMetrics {
    pub tick_count: u32,
    pub avg_tick_time_ms_x100: u16,
    pub max_tick_time_ms_x100: u16,
    pub player_count: u16,
    pub entity_count: u16,
    pub total_bytes_sent: u32,
    pub total_bytes_received: u32,
    pub avg_bandwidth_per_client: u32,
    pub sched_entities_deferred: u16,
    pub sched_max_queue_age_ticks: u16,
    pub sched_peers_at_budget_pct: u8,
    pub sched_peers_evaluated: u16,
    pub sched_snapshot_overflow: u16,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ServerPacket {
    AuthResult(AuthResult),
    Snapshot(Snapshot),
    ActionConfirm(ActionConfirm),
    GameEvent(GameEvent),
    ServerMetrics(ServerMetrics),
}

impl ServerPacket {
    pub fn packet_type(&self) -> u8 {
        match self {
            ServerPacket::AuthResult(_) => server_type::AUTH_RESULT,
            ServerPacket::Snapshot(_) => server_type::SNAPSHOT,
            ServerPacket::ActionConfirm(_) => server_type::ACTION_CONFIRM,
            ServerPacket::GameEvent(_) => server_type::GAME_EVENT,
            ServerPacket::ServerMetrics(_) => server_type::SERVER_METRICS,
        }
    }

    /// The ENet channel this packet rides (D2 plan). Baselines (and full-state replies, which
    /// are baselines) are must-arrive and can exceed the unreliable MTU budget, so they ride
    /// the reliable channel explicitly instead of letting ENet silently upgrade an oversized
    /// ch0 datagram. Safe vs ordering: deltas only ever reference an ACKED baseline, so no
    /// delta referencing tick T can be in flight before the client has baseline T.
    pub fn channel(&self) -> u8 {
        match self {
            ServerPacket::Snapshot(s) if s.is_baseline => crate::CH_RELIABLE,
            ServerPacket::Snapshot(_) | ServerPacket::ActionConfirm(_) => crate::CH_SNAPSHOT,
            _ => crate::CH_RELIABLE,
        }
    }

    pub fn reliable(&self) -> bool {
        match self {
            ServerPacket::Snapshot(s) => s.is_baseline,
            ServerPacket::ActionConfirm(_) => false,
            _ => true,
        }
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut w = BitWriter::with_capacity(128);
        w.write_u8(self.packet_type());
        match self {
            ServerPacket::AuthResult(a) => {
                w.write_u8(a.result);
                if let Some(ok) = &a.ok {
                    w.write_u16(ok.entity_id);
                    w.write_u32(ok.server_tick);
                    w.write_u8(ok.tick_rate);
                }
            }
            ServerPacket::Snapshot(s) => s.encode_body(&mut w),
            ServerPacket::ActionConfirm(c) => {
                w.write_u8(c.sequence);
                w.write_u8(c.action);
                w.write_i16(quant_coord(c.position.0));
                w.write_i16(quant_coord(c.position.1));
                w.write_u8(c.result);
                w.write_u16(c.server_tick);
                w.write_u8(c.stamina);
                w.write_u8(c.mana);
                w.write_u8(c.dash_cooldown);
                w.write_u8(c.ability_cooldown);
                w.write_u16(c.health);
            }
            ServerPacket::GameEvent(e) => {
                // The decoder picks the data layout from event_type; a mismatched variant
                // encodes a packet the peer cannot read (UnexpectedEof / trailing data).
                debug_assert!(
                    e.data_matches_type(),
                    "GameEvent data variant does not match event_type {}",
                    e.event_type
                );
                w.write_u8(e.event_type);
                w.write_u16(e.source_id);
                w.write_u16(e.target_id);
                match &e.data {
                    GameEventData::None => {}
                    GameEventData::Damage {
                        amount,
                        damage_type,
                    } => {
                        w.write_u16(*amount);
                        w.write_u8(*damage_type);
                    }
                    GameEventData::Respawn { x, y } => {
                        w.write_i16(quant_coord(*x));
                        w.write_i16(quant_coord(*y));
                    }
                    GameEventData::EffectApply {
                        effect_id,
                        duration_ms,
                    } => {
                        w.write_u8(*effect_id);
                        w.write_u16(*duration_ms);
                    }
                    GameEventData::EffectRemove { effect_id } => w.write_u8(*effect_id),
                    GameEventData::PlayerInfo {
                        name,
                        x,
                        y,
                        color,
                        class,
                    } => {
                        w.write_str8(name);
                        w.write_i16(quant_coord(*x));
                        w.write_i16(quant_coord(*y));
                        w.write_u8(color.0);
                        w.write_u8(color.1);
                        w.write_u8(color.2);
                        w.write_u8(*class);
                    }
                    GameEventData::Leaderboard { entries } => {
                        let n = entries.len().min(10);
                        w.write_u8(n as u8);
                        for (id, kills) in entries.iter().take(n) {
                            w.write_u16(*id);
                            w.write_u16(*kills);
                        }
                    }
                    GameEventData::ProjectileFired { x, y, fire_tick } => {
                        w.write_i16(quant_coord(*x));
                        w.write_i16(quant_coord(*y));
                        w.write_u16(*fire_tick);
                    }
                    GameEventData::ExpGain { amount } => {
                        w.write_u16(*amount);
                    }
                    GameEventData::AbilityEffect {
                        effect_id,
                        x,
                        y,
                        radius,
                    } => {
                        w.write_u8(*effect_id);
                        w.write_i16(quant_coord(*x));
                        w.write_i16(quant_coord(*y));
                        w.write_u16(*radius);
                    }
                    GameEventData::Progress {
                        level,
                        experience,
                        move_speed_q,
                    } => {
                        w.write_u16(*level);
                        w.write_u32(*experience);
                        w.write_u8(*move_speed_q);
                    }
                    GameEventData::Pickup { kind, amount } => {
                        w.write_u8(*kind);
                        w.write_u16(*amount);
                    }
                }
            }
            ServerPacket::ServerMetrics(m) => {
                w.write_u32(m.tick_count);
                w.write_u16(m.avg_tick_time_ms_x100);
                w.write_u16(m.max_tick_time_ms_x100);
                w.write_u16(m.player_count);
                w.write_u16(m.entity_count);
                w.write_u32(m.total_bytes_sent);
                w.write_u32(m.total_bytes_received);
                w.write_u32(m.avg_bandwidth_per_client);
                w.write_u16(m.sched_entities_deferred);
                w.write_u16(m.sched_max_queue_age_ticks);
                w.write_u8(m.sched_peers_at_budget_pct);
                w.write_u16(m.sched_peers_evaluated);
                w.write_u16(m.sched_snapshot_overflow);
            }
        }
        w.finish()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, DecodeError> {
        let mut r = BitReader::new(bytes);
        let t = r.read_u8()?;
        let pkt = match t {
            server_type::AUTH_RESULT => {
                let result = r.read_u8()?;
                let ok = if result == crate::types::auth_result_code::OK {
                    Some(AuthOk {
                        entity_id: r.read_u16()?,
                        server_tick: r.read_u32()?,
                        tick_rate: r.read_u8()?,
                    })
                } else {
                    None
                };
                ServerPacket::AuthResult(AuthResult { result, ok })
            }
            server_type::SNAPSHOT => ServerPacket::Snapshot(Snapshot::decode_body(&mut r)?),
            server_type::ACTION_CONFIRM => ServerPacket::ActionConfirm(ActionConfirm {
                sequence: r.read_u8()?,
                action: r.read_u8()?,
                position: {
                    let x = dequant_coord(r.read_i16()?);
                    let y = dequant_coord(r.read_i16()?);
                    (x, y)
                },
                result: r.read_u8()?,
                server_tick: r.read_u16()?,
                stamina: r.read_u8()?,
                mana: r.read_u8()?,
                dash_cooldown: r.read_u8()?,
                ability_cooldown: r.read_u8()?,
                health: r.read_u16()?,
            }),
            server_type::GAME_EVENT => {
                let event_type = r.read_u8()?;
                let source_id = r.read_u16()?;
                let target_id = r.read_u16()?;
                let data = match event_type {
                    game_event_type::DAMAGE => GameEventData::Damage {
                        amount: r.read_u16()?,
                        damage_type: r.read_u8()?,
                    },
                    game_event_type::RESPAWN => GameEventData::Respawn {
                        x: dequant_coord(r.read_i16()?),
                        y: dequant_coord(r.read_i16()?),
                    },
                    game_event_type::EFFECT_APPLY => GameEventData::EffectApply {
                        effect_id: r.read_u8()?,
                        duration_ms: r.read_u16()?,
                    },
                    game_event_type::EFFECT_REMOVE => GameEventData::EffectRemove {
                        effect_id: r.read_u8()?,
                    },
                    game_event_type::PLAYER_INFO => GameEventData::PlayerInfo {
                        name: r.read_str8()?,
                        x: dequant_coord(r.read_i16()?),
                        y: dequant_coord(r.read_i16()?),
                        color: (r.read_u8()?, r.read_u8()?, r.read_u8()?),
                        class: r.read_u8()?,
                    },
                    game_event_type::LEADERBOARD_UPDATE => {
                        let n = r.read_u8()? as usize;
                        if n > 10 {
                            return Err(DecodeError::BadValue("leaderboard count"));
                        }
                        let mut entries = Vec::with_capacity(n);
                        for _ in 0..n {
                            entries.push((r.read_u16()?, r.read_u16()?));
                        }
                        GameEventData::Leaderboard { entries }
                    }
                    game_event_type::PROJECTILE_FIRED => GameEventData::ProjectileFired {
                        x: dequant_coord(r.read_i16()?),
                        y: dequant_coord(r.read_i16()?),
                        fire_tick: r.read_u16()?,
                    },
                    game_event_type::EXP_GAIN => GameEventData::ExpGain {
                        amount: r.read_u16()?,
                    },
                    game_event_type::ABILITY_EFFECT => GameEventData::AbilityEffect {
                        effect_id: r.read_u8()?,
                        x: dequant_coord(r.read_i16()?),
                        y: dequant_coord(r.read_i16()?),
                        radius: r.read_u16()?,
                    },
                    game_event_type::PROGRESS => GameEventData::Progress {
                        level: r.read_u16()?,
                        experience: r.read_u32()?,
                        move_speed_q: r.read_u8()?,
                    },
                    game_event_type::PICKUP => GameEventData::Pickup {
                        kind: r.read_u8()?,
                        amount: r.read_u16()?,
                    },
                    // KILL, KILL_PVP, LEVEL_UP, CHAT_MESSAGE — head only, same as today.
                    _ => GameEventData::None,
                };
                ServerPacket::GameEvent(GameEvent {
                    event_type,
                    source_id,
                    target_id,
                    data,
                })
            }
            server_type::SERVER_METRICS => ServerPacket::ServerMetrics(ServerMetrics {
                tick_count: r.read_u32()?,
                avg_tick_time_ms_x100: r.read_u16()?,
                max_tick_time_ms_x100: r.read_u16()?,
                player_count: r.read_u16()?,
                entity_count: r.read_u16()?,
                total_bytes_sent: r.read_u32()?,
                total_bytes_received: r.read_u32()?,
                avg_bandwidth_per_client: r.read_u32()?,
                sched_entities_deferred: r.read_u16()?,
                sched_max_queue_age_ticks: r.read_u16()?,
                sched_peers_at_budget_pct: r.read_u8()?,
                sched_peers_evaluated: r.read_u16()?,
                sched_snapshot_overflow: r.read_u16()?,
            }),
            other => return Err(DecodeError::BadPacketType(other)),
        };
        r.expect_end()?;
        Ok(pkt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{auth_result_code, game_event_type};

    fn rt(p: ServerPacket) -> ServerPacket {
        ServerPacket::decode(&p.encode()).unwrap()
    }

    #[test]
    fn auth_result_round_trip() {
        let ok = ServerPacket::AuthResult(AuthResult {
            result: auth_result_code::OK,
            ok: Some(AuthOk {
                entity_id: 7,
                server_tick: 1234,
                tick_rate: 30,
            }),
        });
        assert_eq!(rt(ok.clone()), ok);
        let rej = ServerPacket::AuthResult(AuthResult {
            result: auth_result_code::BAD_TICKET,
            ok: None,
        });
        assert_eq!(rt(rej.clone()), rej);
    }

    #[test]
    fn baselines_ride_the_reliable_channel() {
        let baseline = ServerPacket::Snapshot(crate::Snapshot {
            server_tick: 1,
            server_ms: 1,
            is_baseline: true,
            baseline_tick: None,
            entities: vec![],
        });
        assert_eq!(baseline.channel(), crate::CH_RELIABLE);
        assert!(baseline.reliable());

        let delta = ServerPacket::Snapshot(crate::Snapshot {
            server_tick: 2,
            server_ms: 2,
            is_baseline: false,
            baseline_tick: Some(1),
            entities: vec![],
        });
        assert_eq!(delta.channel(), crate::CH_SNAPSHOT);
        assert!(!delta.reliable());
    }

    #[test]
    fn action_confirm_round_trip() {
        let p = ServerPacket::ActionConfirm(ActionConfirm {
            sequence: 200,
            action: 0,
            position: (-450.5, 449.9),
            result: 0,
            server_tick: 60000,
            stamina: 73,
            mana: 100,
            dash_cooldown: 55,
            ability_cooldown: 100,
            health: 437,
        });
        match rt(p) {
            ServerPacket::ActionConfirm(c) => {
                assert_eq!(c.sequence, 200);
                assert!((c.position.0 + 450.5).abs() < 0.1);
                assert_eq!(c.stamina, 73);
                assert_eq!(c.dash_cooldown, 55);
                assert_eq!(c.ability_cooldown, 100);
                assert_eq!(c.health, 437);
            }
            other => panic!("wrong: {other:?}"),
        }
    }

    #[test]
    fn game_events_round_trip() {
        let cases = vec![
            GameEvent {
                event_type: game_event_type::DAMAGE,
                source_id: 30001,
                target_id: 5,
                data: GameEventData::Damage {
                    amount: 10,
                    damage_type: 0,
                },
            },
            GameEvent {
                event_type: game_event_type::KILL,
                source_id: 5,
                target_id: 30001,
                data: GameEventData::None,
            },
            GameEvent {
                event_type: game_event_type::RESPAWN,
                source_id: 0,
                target_id: 5,
                data: GameEventData::Respawn {
                    x: -800.0,
                    y: -800.0,
                },
            },
            GameEvent {
                event_type: game_event_type::PLAYER_INFO,
                source_id: 0,
                target_id: 5,
                data: GameEventData::PlayerInfo {
                    name: "Ωmega".into(),
                    x: 1.0,
                    y: -1.0,
                    color: (69, 135, 255),
                    class: 4,
                },
            },
            GameEvent {
                event_type: game_event_type::LEADERBOARD_UPDATE,
                source_id: 0,
                target_id: 0,
                data: GameEventData::Leaderboard {
                    entries: vec![(1, 5), (2, 3), (7, 1)],
                },
            },
            GameEvent {
                event_type: game_event_type::PROJECTILE_FIRED,
                source_id: 30001,
                target_id: 10042,
                data: GameEventData::ProjectileFired {
                    x: 3.0,
                    y: 4.0,
                    fire_tick: 999,
                },
            },
            GameEvent {
                event_type: game_event_type::EXP_GAIN,
                source_id: 7,
                target_id: 0,
                data: GameEventData::ExpGain { amount: 20 },
            },
            GameEvent {
                event_type: game_event_type::ABILITY_EFFECT,
                source_id: 5,
                target_id: 0,
                data: GameEventData::AbilityEffect {
                    effect_id: 2,
                    x: 120.0,
                    y: -80.0,
                    radius: 120,
                },
            },
            GameEvent {
                event_type: game_event_type::PROGRESS,
                source_id: 5,
                target_id: 5,
                data: GameEventData::Progress {
                    level: 23,
                    experience: 4321,
                    move_speed_q: 50,
                },
            },
            GameEvent {
                event_type: game_event_type::PICKUP,
                source_id: 40001,
                target_id: 5,
                data: GameEventData::Pickup { kind: 0, amount: 5 },
            },
        ];
        for e in cases {
            let p = ServerPacket::GameEvent(e.clone());
            match rt(p) {
                ServerPacket::GameEvent(d) => {
                    assert_eq!(d.event_type, e.event_type);
                    assert_eq!(d.source_id, e.source_id);
                    assert_eq!(d.target_id, e.target_id);
                    match (&d.data, &e.data) {
                        (
                            GameEventData::PlayerInfo {
                                name: a, class: ca, ..
                            },
                            GameEventData::PlayerInfo {
                                name: b, class: cb, ..
                            },
                        ) => {
                            assert_eq!(a, b);
                            assert_eq!(ca, cb);
                        }
                        (
                            GameEventData::Leaderboard { entries: a },
                            GameEventData::Leaderboard { entries: b },
                        ) => {
                            assert_eq!(a, b)
                        }
                        (
                            GameEventData::ExpGain { amount: a },
                            GameEventData::ExpGain { amount: b },
                        ) => {
                            assert_eq!(a, b)
                        }
                        (
                            GameEventData::AbilityEffect {
                                effect_id: a,
                                radius: ra,
                                ..
                            },
                            GameEventData::AbilityEffect {
                                effect_id: b,
                                radius: rb,
                                ..
                            },
                        ) => {
                            assert_eq!(a, b);
                            assert_eq!(ra, rb);
                        }
                        (
                            GameEventData::Progress {
                                level: a,
                                experience: ea,
                                move_speed_q: sa,
                            },
                            GameEventData::Progress {
                                level: b,
                                experience: eb,
                                move_speed_q: sb,
                            },
                        ) => {
                            assert_eq!(a, b);
                            assert_eq!(ea, eb);
                            assert_eq!(sa, sb);
                        }
                        (
                            GameEventData::Pickup {
                                kind: a,
                                amount: aa,
                            },
                            GameEventData::Pickup {
                                kind: b,
                                amount: ab,
                            },
                        ) => {
                            assert_eq!(a, b);
                            assert_eq!(aa, ab);
                        }
                        _ => {}
                    }
                }
                other => panic!("wrong: {other:?}"),
            }
        }
    }

    /// The codec is transport-only: an out-of-range class (> 6) round-trips untouched
    /// (the server clamps before broadcasting, but the wire accepts any u8).
    #[test]
    fn player_info_out_of_range_class_accepted_on_wire() {
        let p = ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::PLAYER_INFO,
            source_id: 0,
            target_id: 9,
            data: GameEventData::PlayerInfo {
                name: "Overflow".into(),
                x: 0.0,
                y: 0.0,
                color: (1, 2, 3),
                class: 255,
            },
        });
        match rt(p) {
            ServerPacket::GameEvent(GameEvent {
                data: GameEventData::PlayerInfo { class, .. },
                ..
            }) => assert_eq!(class, 255),
            other => panic!("wrong: {other:?}"),
        }
    }

    #[test]
    fn metrics_round_trip() {
        let m = ServerMetrics {
            tick_count: 100000,
            avg_tick_time_ms_x100: 250,
            max_tick_time_ms_x100: 1200,
            player_count: 512,
            entity_count: 1400,
            total_bytes_sent: 123456789,
            total_bytes_received: 987654,
            avg_bandwidth_per_client: 1800,
            sched_entities_deferred: 12,
            sched_max_queue_age_ticks: 3,
            sched_peers_at_budget_pct: 25,
            sched_peers_evaluated: 512,
            sched_snapshot_overflow: 0,
        };
        let p = ServerPacket::ServerMetrics(m.clone());
        assert_eq!(rt(p), ServerPacket::ServerMetrics(m));
    }

    #[test]
    fn client_types_rejected() {
        assert_eq!(
            ServerPacket::decode(&[1u8]),
            Err(DecodeError::BadPacketType(1))
        );
    }
}
