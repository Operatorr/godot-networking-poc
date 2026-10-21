//! The diagnostic reader must track the real encoder, not a hand-built lookalike.
#[allow(dead_code)]
#[path = "../../../scripts/load_campaign/udp_control_record.rs"]
mod recorder;

use protocol::{ClientPacket, ConnectAuth, PROTOCOL_VERSION};

fn enet_command(payload: &[u8]) -> Vec<u8> {
    let mut datagram = vec![0, 1, 0x86, 1, 0, 1];
    datagram.extend_from_slice(&(payload.len() as u16).to_be_bytes());
    datagram.extend_from_slice(payload);
    datagram
}

fn unsigned(name: &str, character_id: u32) -> Vec<u8> {
    ClientPacket::ConnectAuth(ConnectAuth {
        protocol_version: PROTOCOL_VERSION,
        ticket: None,
        character_id,
        character_name: name.into(),
        color: (69, 135, 255),
        class: 4,
        bandwidth_budget_bps: 0,
    })
    .encode()
}

#[test]
fn actual_unsigned_encoder_maps_bot_identity_after_character_id() {
    for id in [0_u16, 7, 999] {
        for character_id in [0, 0x0102_0304] {
            let payload = unsigned(&format!("LoadBot{id:03}"), character_id);
            let rows = recorder::commands(&enet_command(&payload)).unwrap();
            assert_eq!(rows.len(), 1);
            assert_eq!(rows[0][15], 1, "mapping missing for bot {id}");
            assert_eq!(u16::from_le_bytes([rows[0][13], rows[0][14]]), id);
        }
    }
}

#[test]
fn non_bot_or_incomplete_name_never_creates_a_mapping() {
    for name in ["Player", "LoadBot", "LoadBot70000"] {
        let rows = recorder::commands(&enet_command(&unsigned(name, 0))).unwrap();
        assert_eq!(rows[0][15], 0);
    }
    let mut payload = unsigned("LoadBot007", 0);
    payload.truncate(12);
    let rows = recorder::commands(&enet_command(&payload)).unwrap();
    assert_eq!(rows[0][15], 0);
}
