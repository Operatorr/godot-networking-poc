//! Omega Realm wire protocol — the single source of truth for the wire format.
//!
//! Both the server binary and the client GDExtension link this crate (migration-spec D7), so
//! serialization drift between client and server is impossible by construction. The format is
//! the D3 redesign documented in `docs/rust-port/contract.md`; the behavioral reference for the
//! semantics it carries is `docs/rust-port/extraction/wire-protocol.md`.
//!
//! Framing: ENet preserves datagram boundaries, so every packet is `[u8 type][payload]` with no
//! length field. Multi-byte integers are little-endian. Snapshot entity records are a bitstream
//! (LSB-first). Decoding is strict: underflow, bad discriminants, or trailing data are errors —
//! the old GDScript zero-fill-and-continue behavior is deliberately not ported.

mod bits;
mod client;
mod error;
mod quant;
mod server;
mod snapshot;
pub mod types;

pub use bits::{BitReader, BitWriter};
pub use client::{ClientPacket, ConnectAuth, PlayerInput, Ticket, TICKET_PAYLOAD_LEN};
pub use error::DecodeError;
pub use quant::{
    dequant_angle, dequant_cooldown, dequant_coord, quant_angle, quant_cooldown, quant_coord,
    quant_resource,
};
pub use server::{
    ActionConfirm, AuthOk, AuthResult, GameEvent, GameEventData, ServerMetrics, ServerPacket,
};
pub use snapshot::{EntityRecord, Snapshot};
pub use types::*;

/// Bumped on every wire-format change; checked at handshake (ENet connect `data` low byte and
/// the `ConnectAuth` packet). Client and server refuse mismatched versions (D7).
pub const PROTOCOL_VERSION: u8 = 7; // v7: LEADERBOARD_UPDATE entries gain a trailing `deaths` u16 per
                                    // row (+2B/row) so the HUD can show a Kills:Deaths ratio; ranking
                                    // is still by kills. Deaths were already tracked in-memory.
                                    // v6: PlayerInfo.level (+2B) — server broadcasts each player's
                                    // level to ALL clients (leaderboard shows class+level), re-sent
                                    // on hydrate + level-up; owner still also gets owner-only Progress.
                                    // v5: ActionConfirm.health (+2B) — authoritative HP for the
                                    // owner's HUD bar (HP isn't in snapshots; reconciled like
                                    // stamina/mana so the bar tracks server-side regen).
                                    // v4: PlayerInput.cursor (+4B) + ConnectAuth.character_id;
                                    // 4th entity kind (world effects: healthorb/mine/dot-zone/
                                    // bible); entity_flags STEALTH (bit 9); ABILITY_EFFECT +
                                    // PROGRESS game events; PICKUP carries {kind, amount}.
                                    // v3: player class byte in ConnectAuth + PLAYER_INFO.
                                    // v2: entity_flags widened to 16 bits, DAZED in bit 8.

/// ENet channel plan (migration-spec D2).
pub const CH_SNAPSHOT: u8 = 0; // unreliable sequenced: Snapshot, ActionConfirm
pub const CH_RELIABLE: u8 = 1; // reliable ordered: auth, game events, acks, requests
pub const CH_INPUT: u8 = 2; // unreliable sequenced: PlayerInput
pub const CHANNEL_COUNT: usize = 3;

/// Keep every ch0 datagram under this: ENet silently upgrades unreliable packets larger than
/// the MTU (1392) to reliable-fragmented, reintroducing head-of-line blocking.
pub const MAX_UNRELIABLE_PAYLOAD: usize = 1200;
