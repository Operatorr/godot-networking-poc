//! The Snapshot (STATE_UPDATE successor) — byte-aligned header + bitstream entity records.
//!
//! Layout (contract.md):
//! ```text
//! [u8 type=65][u32 server_tick][u32 server_ms][u8 flags]
//! if IS_DELTA: [u32 baseline_tick]
//! [u16 entity_count]
//! bitstream of entity records, final byte zero-padded
//! ```
//!
//! Typed entity id: `[2-bit kind][offset]` — player: 10-bit offset (id 1–999), projectile:
//! 15-bit offset (id-10000), monster: 14-bit offset (id-30000). The kind replaces the old
//! separate `u8 entity_type`.
//!
//! `server_ms` is the relocated HEARTBEAT clock-sync payload (D2): the server's monotonic ms
//! clock, u32-wrapped, stamped on every snapshot.

use crate::bits::{BitReader, BitWriter};
use crate::error::DecodeError;
use crate::quant::{dequant_coord, quant_coord};
use crate::types::{
    delta_mask, entity_type_for_id, snapshot_flags, EntityType, MONSTER_ID_START,
    PROJECTILE_ID_START,
};

#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub server_tick: u32,
    pub server_ms: u32,
    pub is_baseline: bool,
    /// `Some(tick)` means delta mode (diffed against that Baseline). `None` means full-state.
    pub baseline_tick: Option<u32>,
    pub entities: Vec<EntityRecord>,
}

/// One entity in a Snapshot. For baseline/full records every field is present; for delta
/// records only the fields named by `delta_mask` are authoritative (the rest are `None`).
#[derive(Debug, Clone, PartialEq)]
pub struct EntityRecord {
    pub entity_id: u16,
    /// Bits from `types::delta_mask`. Baseline records carry `FULL`.
    pub delta_mask: u8,
    pub position: Option<(f32, f32)>,
    pub animation: Option<u8>,
    pub flags: Option<u16>,
}

impl EntityRecord {
    pub fn full(entity_id: u16, position: (f32, f32), animation: u8, flags: u16) -> Self {
        Self {
            entity_id,
            delta_mask: delta_mask::FULL,
            position: Some(position),
            animation: Some(animation),
            flags: Some(flags),
        }
    }

    pub fn removed(entity_id: u16) -> Self {
        Self {
            entity_id,
            delta_mask: delta_mask::REMOVED,
            position: None,
            animation: None,
            flags: None,
        }
    }

    pub fn entity_type(&self) -> Option<EntityType> {
        entity_type_for_id(self.entity_id)
    }

    /// Wire size of this record in bits (id + mask/fields). Used by the per-peer byte budget.
    pub fn wire_bits(&self, in_baseline: bool) -> usize {
        let id_bits = match entity_type_for_id(self.entity_id) {
            Some(EntityType::Player) => 2 + 10,
            Some(EntityType::Projectile) => 2 + 15,
            Some(EntityType::Monster) => 2 + 14,
            None => 0,
        };
        if in_baseline {
            return id_bits + 3 + 16 + 32;
        }
        let mut bits = id_bits + 5;
        if self.delta_mask & delta_mask::FULL != 0 {
            bits += 3 + 16 + 32;
        } else if self.delta_mask & delta_mask::REMOVED == 0 {
            if self.delta_mask & delta_mask::POSITION != 0 {
                bits += 32;
            }
            if self.delta_mask & delta_mask::ANIMATION != 0 {
                bits += 3;
            }
            if self.delta_mask & delta_mask::FLAGS != 0 {
                bits += 16;
            }
        }
        bits
    }
}

fn write_typed_id(w: &mut BitWriter, id: u16) {
    match entity_type_for_id(id) {
        Some(EntityType::Player) => {
            w.write_bits(0, 2);
            w.write_bits(id as u32, 10);
        }
        Some(EntityType::Projectile) => {
            w.write_bits(1, 2);
            w.write_bits((id - PROJECTILE_ID_START) as u32, 15);
        }
        Some(EntityType::Monster) => {
            w.write_bits(2, 2);
            w.write_bits((id - MONSTER_ID_START) as u32, 14);
        }
        None => {
            // Out-of-range ids must never be encoded; the encoder asserts in debug and emits
            // the reserved kind so a release build produces a decode error, not silent aliasing.
            debug_assert!(false, "entity id {id} outside the invariant ranges");
            w.write_bits(3, 2);
        }
    }
}

fn read_typed_id(r: &mut BitReader) -> Result<u16, DecodeError> {
    match r.read_bits(2)? {
        0 => {
            let off = r.read_bits(10)? as u16;
            if off == 0 || off > 999 {
                return Err(DecodeError::BadValue("player id"));
            }
            Ok(off)
        }
        1 => {
            let off = r.read_bits(15)? as u16;
            if off > 19999 {
                return Err(DecodeError::BadValue("projectile id"));
            }
            Ok(PROJECTILE_ID_START + off)
        }
        2 => {
            let off = r.read_bits(14)? as u16;
            if off > 9999 {
                return Err(DecodeError::BadValue("monster id"));
            }
            Ok(MONSTER_ID_START + off)
        }
        _ => Err(DecodeError::BadValue("entity kind")),
    }
}

fn write_full_fields(w: &mut BitWriter, rec: &EntityRecord) {
    let (x, y) = rec.position.unwrap_or((0.0, 0.0));
    w.write_bits(rec.animation.unwrap_or(0) as u32, 3);
    w.write_bits(rec.flags.unwrap_or(0) as u32, 16);
    w.write_bits(quant_coord(x) as u16 as u32, 16);
    w.write_bits(quant_coord(y) as u16 as u32, 16);
}

fn read_full_fields(r: &mut BitReader, entity_id: u16) -> Result<EntityRecord, DecodeError> {
    let animation = r.read_bits(3)? as u8;
    let flags = r.read_bits(16)? as u16;
    let x = dequant_coord(r.read_bits(16)? as u16 as i16);
    let y = dequant_coord(r.read_bits(16)? as u16 as i16);
    Ok(EntityRecord {
        entity_id,
        delta_mask: delta_mask::FULL,
        position: Some((x, y)),
        animation: Some(animation),
        flags: Some(flags),
    })
}

impl Snapshot {
    pub(crate) fn encode_body(&self, w: &mut BitWriter) {
        // Decode rejects IS_DELTA|BASELINE; a count above u16 would wrap and desync the reader.
        debug_assert!(
            !(self.is_baseline && self.baseline_tick.is_some()),
            "snapshot cannot be both baseline and delta"
        );
        debug_assert!(
            self.entities.len() <= u16::MAX as usize,
            "snapshot entity count overflows the u16 wire field"
        );
        w.write_u32(self.server_tick);
        w.write_u32(self.server_ms);
        let mut flags = 0u8;
        if self.baseline_tick.is_some() {
            flags |= snapshot_flags::IS_DELTA;
        }
        if self.is_baseline {
            flags |= snapshot_flags::BASELINE;
        }
        w.write_u8(flags);
        if let Some(bt) = self.baseline_tick {
            w.write_u32(bt);
        }
        w.write_u16(self.entities.len() as u16);
        if self.baseline_tick.is_none() {
            // Full-state layout: every record is a full record (mask implicit).
            for rec in &self.entities {
                write_typed_id(w, rec.entity_id);
                write_full_fields(w, rec);
            }
        } else {
            for rec in &self.entities {
                write_typed_id(w, rec.entity_id);
                w.write_bits(rec.delta_mask as u32, 5);
                if rec.delta_mask & delta_mask::FULL != 0 {
                    write_full_fields(w, rec);
                } else if rec.delta_mask & delta_mask::REMOVED != 0 {
                    // no payload
                } else {
                    if rec.delta_mask & delta_mask::POSITION != 0 {
                        let (x, y) = rec.position.unwrap_or((0.0, 0.0));
                        w.write_bits(quant_coord(x) as u16 as u32, 16);
                        w.write_bits(quant_coord(y) as u16 as u32, 16);
                    }
                    if rec.delta_mask & delta_mask::ANIMATION != 0 {
                        w.write_bits(rec.animation.unwrap_or(0) as u32, 3);
                    }
                    if rec.delta_mask & delta_mask::FLAGS != 0 {
                        w.write_bits(rec.flags.unwrap_or(0) as u32, 16);
                    }
                }
            }
        }
        w.align();
    }

    pub(crate) fn decode_body(r: &mut BitReader) -> Result<Self, DecodeError> {
        let server_tick = r.read_u32()?;
        let server_ms = r.read_u32()?;
        let flags = r.read_u8()?;
        let is_delta = flags & snapshot_flags::IS_DELTA != 0;
        let is_baseline = flags & snapshot_flags::BASELINE != 0;
        if is_delta && is_baseline {
            return Err(DecodeError::BadValue("snapshot flags"));
        }
        let baseline_tick = if is_delta { Some(r.read_u32()?) } else { None };
        let count = r.read_u16()? as usize;
        let mut entities = Vec::with_capacity(count.min(4096));
        for _ in 0..count {
            let entity_id = read_typed_id(r)?;
            if !is_delta {
                entities.push(read_full_fields(r, entity_id)?);
                continue;
            }
            let mask = r.read_bits(5)? as u8;
            // Precedence ported verbatim: FULL before REMOVED (extraction §4.8).
            if mask & delta_mask::FULL != 0 {
                let mut rec = read_full_fields(r, entity_id)?;
                rec.delta_mask = mask;
                entities.push(rec);
            } else if mask & delta_mask::REMOVED != 0 {
                entities.push(EntityRecord {
                    entity_id,
                    delta_mask: mask,
                    position: None,
                    animation: None,
                    flags: None,
                });
            } else {
                let position = if mask & delta_mask::POSITION != 0 {
                    let x = dequant_coord(r.read_bits(16)? as u16 as i16);
                    let y = dequant_coord(r.read_bits(16)? as u16 as i16);
                    Some((x, y))
                } else {
                    None
                };
                let animation = if mask & delta_mask::ANIMATION != 0 {
                    Some(r.read_bits(3)? as u8)
                } else {
                    None
                };
                let eflags = if mask & delta_mask::FLAGS != 0 {
                    Some(r.read_bits(16)? as u16)
                } else {
                    None
                };
                entities.push(EntityRecord {
                    entity_id,
                    delta_mask: mask,
                    position,
                    animation,
                    flags: eflags,
                });
            }
        }
        Ok(Snapshot {
            server_tick,
            server_ms,
            is_baseline,
            baseline_tick,
            entities,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::server::ServerPacket;

    fn round_trip(s: Snapshot) -> Snapshot {
        let bytes = ServerPacket::Snapshot(s).encode();
        match ServerPacket::decode(&bytes).unwrap() {
            ServerPacket::Snapshot(s) => s,
            other => panic!("wrong packet: {other:?}"),
        }
    }

    #[test]
    fn baseline_round_trip() {
        let s = Snapshot {
            server_tick: 12345,
            server_ms: 99999,
            is_baseline: true,
            baseline_tick: None,
            entities: vec![
                EntityRecord::full(1, (-800.0, -800.0), 1, 0b0010_0001),
                EntityRecord::full(999, (1000.0, -1000.0), 6, 0xFF),
                EntityRecord::full(10000, (0.5, -0.5), 0, 0x21),
                EntityRecord::full(29999, (123.4, -567.8), 0, 0x21),
                EntityRecord::full(30000, (50.0, 50.0), 2, 0x23),
                EntityRecord::full(39999, (-999.9, 999.9), 5, 0x20),
            ],
        };
        let rt = round_trip(s.clone());
        assert_eq!(rt.server_tick, s.server_tick);
        assert_eq!(rt.server_ms, s.server_ms);
        assert!(rt.is_baseline);
        assert_eq!(rt.entities.len(), 6);
        for (a, b) in rt.entities.iter().zip(s.entities.iter()) {
            assert_eq!(a.entity_id, b.entity_id);
            assert_eq!(a.animation, b.animation);
            assert_eq!(a.flags, b.flags);
            let (ax, ay) = a.position.unwrap();
            let (bx, by) = b.position.unwrap();
            assert!((ax - bx).abs() < 0.1 && (ay - by).abs() < 0.1);
        }
    }

    #[test]
    fn delta_round_trip_all_mask_shapes() {
        let s = Snapshot {
            server_tick: 200,
            server_ms: 1,
            is_baseline: false,
            baseline_tick: Some(100),
            entities: vec![
                EntityRecord {
                    entity_id: 7,
                    delta_mask: delta_mask::POSITION,
                    position: Some((1.5, -2.5)),
                    animation: None,
                    flags: None,
                },
                EntityRecord {
                    entity_id: 30005,
                    delta_mask: delta_mask::ANIMATION | delta_mask::FLAGS,
                    position: None,
                    animation: Some(3),
                    flags: Some(0x07),
                },
                EntityRecord::removed(10123),
                EntityRecord::full(42, (10.0, 20.0), 2, 0x21),
                EntityRecord {
                    entity_id: 1,
                    delta_mask: delta_mask::POSITION | delta_mask::ANIMATION | delta_mask::FLAGS,
                    position: Some((-100.0, 100.0)),
                    animation: Some(1),
                    flags: Some(0x61),
                },
            ],
        };
        let rt = round_trip(s.clone());
        assert_eq!(rt.baseline_tick, Some(100));
        assert_eq!(rt.entities.len(), 5);
        assert_eq!(rt.entities[0].delta_mask, delta_mask::POSITION);
        assert_eq!(rt.entities[1].animation, Some(3));
        assert_eq!(rt.entities[1].flags, Some(0x07));
        assert_eq!(rt.entities[2].delta_mask, delta_mask::REMOVED);
        assert_eq!(rt.entities[2].entity_id, 10123);
        assert!(rt.entities[3].delta_mask & delta_mask::FULL != 0);
        assert_eq!(rt.entities[4].entity_id, 1);
    }

    #[test]
    fn empty_delta_round_trip() {
        let s = Snapshot {
            server_tick: 5,
            server_ms: 0,
            is_baseline: false,
            baseline_tick: Some(0),
            entities: vec![],
        };
        let rt = round_trip(s);
        assert_eq!(rt.entities.len(), 0);
    }

    #[test]
    fn wire_bits_matches_encoded_size() {
        // 3 players full-state: header is 1+4+4+1+2 = 12 bytes; records 3 × (12+3+16+32 bits).
        let s = Snapshot {
            server_tick: 1,
            server_ms: 2,
            is_baseline: true,
            baseline_tick: None,
            entities: (1..=3)
                .map(|i| EntityRecord::full(i, (0.0, 0.0), 0, 0))
                .collect(),
        };
        let record_bits: usize = s.entities.iter().map(|e| e.wire_bits(true)).sum();
        let expected = 12 + record_bits.div_ceil(8);
        let bytes = ServerPacket::Snapshot(s).encode();
        assert_eq!(bytes.len(), expected);
    }
}
