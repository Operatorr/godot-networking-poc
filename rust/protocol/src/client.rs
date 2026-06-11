//! Client→server packets.

use crate::bits::{BitReader, BitWriter};
use crate::error::DecodeError;
use crate::quant::{dequant_angle, dequant_coord, quant_angle, quant_coord};
use crate::types::client_type;

/// Ed25519 session ticket (D9). The Go API signs `payload_bytes`; the server verifies with its
/// public key only. Payload layout: `[u8 ticket_version][u32 character_id][u8 region]
/// [u64 issued_at_unix_ms][u64 expires_at_unix_ms]` = 22 bytes, then the 64-byte signature.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ticket {
    pub ticket_version: u8,
    pub character_id: u32,
    pub region: u8,
    pub issued_at_ms: u64,
    pub expires_at_ms: u64,
    pub signature: [u8; 64],
}

pub const TICKET_PAYLOAD_LEN: usize = 22;
pub const TICKET_LEN: usize = TICKET_PAYLOAD_LEN + 64;

impl Ticket {
    /// The exact bytes the Go API signs (and the server verifies).
    pub fn payload_bytes(&self) -> [u8; TICKET_PAYLOAD_LEN] {
        let mut out = [0u8; TICKET_PAYLOAD_LEN];
        out[0] = self.ticket_version;
        out[1..5].copy_from_slice(&self.character_id.to_le_bytes());
        out[5] = self.region;
        out[6..14].copy_from_slice(&self.issued_at_ms.to_le_bytes());
        out[14..22].copy_from_slice(&self.expires_at_ms.to_le_bytes());
        out
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        let mut v = self.payload_bytes().to_vec();
        v.extend_from_slice(&self.signature);
        v
    }

    pub fn from_bytes(b: &[u8]) -> Result<Self, DecodeError> {
        if b.len() != TICKET_LEN {
            return Err(DecodeError::BadValue("ticket length"));
        }
        let mut signature = [0u8; 64];
        signature.copy_from_slice(&b[TICKET_PAYLOAD_LEN..]);
        Ok(Ticket {
            ticket_version: b[0],
            character_id: u32::from_le_bytes(b[1..5].try_into().unwrap()),
            region: b[5],
            issued_at_ms: u64::from_le_bytes(b[6..14].try_into().unwrap()),
            expires_at_ms: u64::from_le_bytes(b[14..22].try_into().unwrap()),
            signature,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ConnectAuth {
    pub protocol_version: u8,
    /// `None` = dev-mode join (`ticket_len == 0`); accepted only when the server runs with
    /// `--allow-unsigned-tickets` (POC parity with today's trust-the-client flow).
    pub ticket: Option<Ticket>,
    pub character_name: String,
    pub color: (u8, u8, u8),
    pub bandwidth_budget_bps: u32,
}

/// PLAYER_INPUT successor — field semantics identical to today (extraction §4.7); the position
/// is the client's predicted position which the server validates, `sequence` wraps at 256,
/// `client_render_tick` is the low 16 bits of the server tick the remotes were rendered at.
#[derive(Debug, Clone, PartialEq)]
pub struct PlayerInput {
    pub sequence: u8,
    pub input_flags: u16,
    pub aim_angle: f32,
    pub position: (f32, f32),
    pub velocity: (f32, f32),
    pub client_render_tick: u16,
    pub client_rtt_ms: u16,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ClientPacket {
    ConnectAuth(ConnectAuth),
    PlayerInput(PlayerInput),
    BaselineAck { baseline_tick: u32 },
    RequestFullState,
    RespawnRequest,
    LocalHitReport { projectile_id: u16 },
}

impl ClientPacket {
    pub fn packet_type(&self) -> u8 {
        match self {
            ClientPacket::ConnectAuth(_) => client_type::CONNECT_AUTH,
            ClientPacket::PlayerInput(_) => client_type::PLAYER_INPUT,
            ClientPacket::BaselineAck { .. } => client_type::BASELINE_ACK,
            ClientPacket::RequestFullState => client_type::REQUEST_FULL_STATE,
            ClientPacket::RespawnRequest => client_type::RESPAWN_REQUEST,
            ClientPacket::LocalHitReport { .. } => client_type::LOCAL_HIT_REPORT,
        }
    }

    /// The ENet channel this packet rides (D2 plan).
    pub fn channel(&self) -> u8 {
        match self {
            ClientPacket::PlayerInput(_) => crate::CH_INPUT,
            _ => crate::CH_RELIABLE,
        }
    }

    /// True for packets that must be sent reliably.
    pub fn reliable(&self) -> bool {
        !matches!(self, ClientPacket::PlayerInput(_))
    }

    pub fn encode(&self) -> Vec<u8> {
        let mut w = BitWriter::with_capacity(64);
        w.write_u8(self.packet_type());
        match self {
            ClientPacket::ConnectAuth(a) => {
                w.write_u8(a.protocol_version);
                match &a.ticket {
                    Some(t) => {
                        let tb = t.to_bytes();
                        w.write_u16(tb.len() as u16);
                        w.write_bytes(&tb);
                    }
                    None => w.write_u16(0),
                }
                w.write_str8(&a.character_name);
                w.write_u8(a.color.0);
                w.write_u8(a.color.1);
                w.write_u8(a.color.2);
                w.write_u32(a.bandwidth_budget_bps);
            }
            ClientPacket::PlayerInput(i) => {
                w.write_u8(i.sequence);
                w.write_u16(i.input_flags);
                w.write_i16(quant_angle(i.aim_angle));
                w.write_i16(quant_coord(i.position.0));
                w.write_i16(quant_coord(i.position.1));
                w.write_i16(quant_coord(i.velocity.0));
                w.write_i16(quant_coord(i.velocity.1));
                w.write_u16(i.client_render_tick);
                w.write_u16(i.client_rtt_ms);
            }
            ClientPacket::BaselineAck { baseline_tick } => w.write_u32(*baseline_tick),
            ClientPacket::RequestFullState | ClientPacket::RespawnRequest => {}
            ClientPacket::LocalHitReport { projectile_id } => w.write_u16(*projectile_id),
        }
        w.finish()
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, DecodeError> {
        let mut r = BitReader::new(bytes);
        let t = r.read_u8()?;
        let pkt = match t {
            client_type::CONNECT_AUTH => {
                let protocol_version = r.read_u8()?;
                let ticket_len = r.read_u16()? as usize;
                let ticket = if ticket_len == 0 {
                    None
                } else {
                    Some(Ticket::from_bytes(r.read_bytes(ticket_len)?)?)
                };
                let character_name = r.read_str8()?;
                let color = (r.read_u8()?, r.read_u8()?, r.read_u8()?);
                let bandwidth_budget_bps = r.read_u32()?;
                ClientPacket::ConnectAuth(ConnectAuth {
                    protocol_version,
                    ticket,
                    character_name,
                    color,
                    bandwidth_budget_bps,
                })
            }
            client_type::PLAYER_INPUT => ClientPacket::PlayerInput(PlayerInput {
                sequence: r.read_u8()?,
                input_flags: r.read_u16()?,
                aim_angle: dequant_angle(r.read_i16()?),
                position: {
                    let x = dequant_coord(r.read_i16()?);
                    let y = dequant_coord(r.read_i16()?);
                    (x, y)
                },
                velocity: {
                    let x = dequant_coord(r.read_i16()?);
                    let y = dequant_coord(r.read_i16()?);
                    (x, y)
                },
                client_render_tick: r.read_u16()?,
                client_rtt_ms: r.read_u16()?,
            }),
            client_type::BASELINE_ACK => ClientPacket::BaselineAck {
                baseline_tick: r.read_u32()?,
            },
            client_type::REQUEST_FULL_STATE => ClientPacket::RequestFullState,
            client_type::RESPAWN_REQUEST => ClientPacket::RespawnRequest,
            client_type::LOCAL_HIT_REPORT => ClientPacket::LocalHitReport {
                projectile_id: r.read_u16()?,
            },
            other => return Err(DecodeError::BadPacketType(other)),
        };
        r.expect_end()?;
        Ok(pkt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::input_flags;

    fn rt(p: ClientPacket) -> ClientPacket {
        ClientPacket::decode(&p.encode()).unwrap()
    }

    #[test]
    fn connect_auth_round_trip_with_ticket() {
        let t = Ticket {
            ticket_version: 1,
            character_id: 4242,
            region: 1,
            issued_at_ms: 1_700_000_000_000,
            expires_at_ms: 1_700_000_045_000,
            signature: [7u8; 64],
        };
        let p = ClientPacket::ConnectAuth(ConnectAuth {
            protocol_version: crate::PROTOCOL_VERSION,
            ticket: Some(t.clone()),
            character_name: "Tester".into(),
            color: (69, 135, 255),
            bandwidth_budget_bps: 120_000,
        });
        match rt(p) {
            ClientPacket::ConnectAuth(a) => {
                assert_eq!(a.ticket, Some(t));
                assert_eq!(a.character_name, "Tester");
                assert_eq!(a.color, (69, 135, 255));
                assert_eq!(a.bandwidth_budget_bps, 120_000);
            }
            other => panic!("wrong: {other:?}"),
        }
    }

    #[test]
    fn connect_auth_dev_mode_round_trip() {
        let p = ClientPacket::ConnectAuth(ConnectAuth {
            protocol_version: 1,
            ticket: None,
            character_name: "Dev".into(),
            color: (0, 0, 0),
            bandwidth_budget_bps: 0,
        });
        match rt(p) {
            ClientPacket::ConnectAuth(a) => assert!(a.ticket.is_none()),
            other => panic!("wrong: {other:?}"),
        }
    }

    #[test]
    fn player_input_round_trip() {
        let p = ClientPacket::PlayerInput(PlayerInput {
            sequence: 255,
            input_flags: input_flags::MOVE_UP | input_flags::SPRINT | input_flags::DASH,
            aim_angle: -1.57,
            position: (-800.0, 432.1),
            velocity: (320.0, -120.5),
            client_render_tick: 65535,
            client_rtt_ms: 47,
        });
        let q = rt(p.clone());
        match (p, q) {
            (ClientPacket::PlayerInput(a), ClientPacket::PlayerInput(b)) => {
                assert_eq!(a.sequence, b.sequence);
                assert_eq!(a.input_flags, b.input_flags);
                assert!((a.aim_angle - b.aim_angle).abs() < 0.01);
                assert!((a.position.0 - b.position.0).abs() < 0.1);
                assert!((a.velocity.1 - b.velocity.1).abs() < 0.1);
                assert_eq!(a.client_render_tick, b.client_render_tick);
                assert_eq!(a.client_rtt_ms, b.client_rtt_ms);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn small_packets_round_trip() {
        assert_eq!(
            rt(ClientPacket::BaselineAck { baseline_tick: 100 }),
            ClientPacket::BaselineAck { baseline_tick: 100 }
        );
        assert_eq!(
            rt(ClientPacket::RequestFullState),
            ClientPacket::RequestFullState
        );
        assert_eq!(
            rt(ClientPacket::RespawnRequest),
            ClientPacket::RespawnRequest
        );
        assert_eq!(
            rt(ClientPacket::LocalHitReport {
                projectile_id: 10001
            }),
            ClientPacket::LocalHitReport {
                projectile_id: 10001
            }
        );
    }

    #[test]
    fn input_packet_is_18_bytes() {
        let p = ClientPacket::PlayerInput(PlayerInput {
            sequence: 0,
            input_flags: 0,
            aim_angle: 0.0,
            position: (0.0, 0.0),
            velocity: (0.0, 0.0),
            client_render_tick: 0,
            client_rtt_ms: 0,
        });
        assert_eq!(p.encode().len(), 18);
    }

    #[test]
    fn truncated_packet_errors() {
        let p = ClientPacket::PlayerInput(PlayerInput {
            sequence: 1,
            input_flags: 0,
            aim_angle: 0.0,
            position: (0.0, 0.0),
            velocity: (0.0, 0.0),
            client_render_tick: 0,
            client_rtt_ms: 0,
        });
        let bytes = p.encode();
        assert_eq!(
            ClientPacket::decode(&bytes[..bytes.len() - 1]),
            Err(DecodeError::UnexpectedEof)
        );
    }

    #[test]
    fn server_types_rejected() {
        assert_eq!(
            ClientPacket::decode(&[64u8]),
            Err(DecodeError::BadPacketType(64))
        );
    }
}
