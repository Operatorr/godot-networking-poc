//! Shared wire-level enums and flag constants. Values match the GDScript protocol wherever the
//! field survives the redesign (extraction/wire-protocol.md §2), so decoded values keep their
//! meaning for the GDScript layers above the codec.

/// C→S packet type bytes.
pub mod client_type {
    pub const CONNECT_AUTH: u8 = 1;
    pub const PLAYER_INPUT: u8 = 2;
    pub const BASELINE_ACK: u8 = 3;
    pub const REQUEST_FULL_STATE: u8 = 4;
    pub const RESPAWN_REQUEST: u8 = 5;
    pub const LOCAL_HIT_REPORT: u8 = 6;
}

/// S→C packet type bytes (disjoint from C→S so a misrouted packet can never alias).
pub mod server_type {
    pub const AUTH_RESULT: u8 = 64;
    pub const SNAPSHOT: u8 = 65;
    pub const ACTION_CONFIRM: u8 = 66;
    pub const GAME_EVENT: u8 = 67;
    pub const SERVER_METRICS: u8 = 68;
}

/// Entity types — same values as GDScript `PacketTypes.EntityType`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum EntityType {
    Player = 1,
    Monster = 2,
    Projectile = 3,
    /// World effects spawned by abilities/loot (healthorb, mine, dot-zone, spinning bible).
    /// On the wire these are kind 3 (the 4th 2-bit kind tag); the specific kind is the
    /// `world_effect` subtype, derived from the id sub-band (see `world_effect_subtype_for_id`).
    WorldEffect = 4,
}

/// Entity id ranges — the repo-wide invariant (players 1–999, projectiles 10000–29999,
/// monsters 30000–39999, world effects 40000–49999).
pub const PLAYER_ID_MAX: u16 = 999;
pub const PROJECTILE_ID_START: u16 = 10000;
pub const PROJECTILE_ID_END: u16 = 29999;
pub const MONSTER_ID_START: u16 = 30000;
pub const MONSTER_ID_END: u16 = 39999;
pub const WORLD_EFFECT_ID_START: u16 = 40000;
pub const WORLD_EFFECT_ID_END: u16 = 49999;

/// Hard upper bound on the entity count a single decoded Snapshot may carry. The wire field is a
/// u16 (≤65535), but no legitimate AoI-filtered snapshot approaches that: a peer sees at most a few
/// hundred entities. This caps decode-time loop iterations so an attacker-controlled count cannot
/// drive a 65k-iteration parse against a truncated buffer. Generous (4096) so it never rejects a
/// valid frame, while staying far below the u16 ceiling. Also used as the decode pre-allocation
/// reserve.
pub const MAX_SNAPSHOT_ENTITIES: usize = 4096;

/// World-effect subtypes — the id band 40000–49999 is partitioned into four 2500-id sub-bands,
/// one per subtype, so the subtype is implicit in the id (always present, even on delta records,
/// without a separate wire field). The server allocates ids within the matching sub-band.
pub mod world_effect {
    use super::WORLD_EFFECT_ID_START;
    pub const HEALTHORB: u8 = 0;
    pub const MINE: u8 = 1;
    pub const DOT_ZONE: u8 = 2;
    pub const BIBLE: u8 = 3;
    /// Ids per subtype sub-band.
    pub const STRIDE: u16 = 2500;
    /// First id of `subtype`'s sub-band.
    pub const fn band_start(subtype: u8) -> u16 {
        WORLD_EFFECT_ID_START + (subtype as u16) * STRIDE
    }
}

pub fn entity_type_for_id(id: u16) -> Option<EntityType> {
    match id {
        1..=PLAYER_ID_MAX => Some(EntityType::Player),
        PROJECTILE_ID_START..=PROJECTILE_ID_END => Some(EntityType::Projectile),
        MONSTER_ID_START..=MONSTER_ID_END => Some(EntityType::Monster),
        WORLD_EFFECT_ID_START..=WORLD_EFFECT_ID_END => Some(EntityType::WorldEffect),
        _ => None,
    }
}

/// The world-effect subtype (`world_effect::*`) for a world-effect id, or `None` if `id` is not
/// in the world-effect band. Derived from which 2500-id sub-band the id falls into.
pub fn world_effect_subtype_for_id(id: u16) -> Option<u8> {
    if !(WORLD_EFFECT_ID_START..=WORLD_EFFECT_ID_END).contains(&id) {
        return None;
    }
    Some(((id - WORLD_EFFECT_ID_START) / world_effect::STRIDE) as u8)
}

/// Animation states (u8 on the wire, 3 bits in snapshot records) — GDScript `AnimationState`.
pub mod anim {
    pub const IDLE: u8 = 0;
    pub const WALK: u8 = 1;
    pub const RUN: u8 = 2;
    pub const ATTACK: u8 = 3;
    pub const HIT: u8 = 4;
    pub const DEATH: u8 = 5;
    pub const SPAWN: u8 = 6;
    pub const MAX: u8 = 6;
}

/// Input flags bitfield (u16) — GDScript `INPUT_FLAG_*`, bit 8 = dash.
pub mod input_flags {
    pub const MOVE_UP: u16 = 1 << 0;
    pub const MOVE_DOWN: u16 = 1 << 1;
    pub const MOVE_LEFT: u16 = 1 << 2;
    pub const MOVE_RIGHT: u16 = 1 << 3;
    pub const SHOOT: u16 = 1 << 4;
    pub const ABILITY: u16 = 1 << 5;
    pub const SPRINT: u16 = 1 << 6;
    pub const INTERACT: u16 = 1 << 7;
    pub const DASH: u16 = 1 << 8;
}

/// Entity flags bitfield (u16 on the wire) — GDScript `ENTITY_FLAG_*`. Bits 0–7 keep their
/// legacy u8 values; bits 8+ are the status-effect extension (DAZED first).
pub mod entity_flags {
    pub const ALIVE: u16 = 1 << 0;
    pub const MOVING: u16 = 1 << 1;
    pub const ATTACKING: u16 = 1 << 2;
    pub const INVULNERABLE: u16 = 1 << 3;
    pub const STUNNED: u16 = 1 << 4;
    pub const VISIBLE: u16 = 1 << 5;
    pub const DASHING: u16 = 1 << 6;
    pub const KNOCKED_BACK: u16 = 1 << 7;
    /// Movement SM daze timer active (sprint/dash locked out, walking allowed).
    pub const DAZED: u16 = 1 << 8;
    /// Rogue Stealth: the entity is invisible to AI targeting (monsters/bots drop aggro) and
    /// dimmed on clients. It can still be hit by projectiles it walks into — stealth only
    /// affects targeting, not collision.
    pub const STEALTH: u16 = 1 << 9;
}

/// Delta mask bits as used by `EntityRecord.delta_mask` in this crate. These are the NEW 5-bit
/// wire positions; the GDScript-facing decode in client_ext translates REMOVED/FULL back to the
/// legacy bit 6/7 constants the client scripts key on.
pub mod delta_mask {
    pub const POSITION: u8 = 1 << 0;
    pub const ANIMATION: u8 = 1 << 1;
    pub const FLAGS: u8 = 1 << 2;
    pub const REMOVED: u8 = 1 << 3;
    pub const FULL: u8 = 1 << 4;
}

/// Snapshot header flags — same values as GDScript `STATE_FLAG_*`.
pub mod snapshot_flags {
    pub const IS_DELTA: u8 = 1 << 0;
    pub const BASELINE: u8 = 1 << 1;
}

/// Game event types — GDScript `GameEventType`.
pub mod game_event_type {
    pub const DAMAGE: u8 = 1;
    pub const KILL: u8 = 2;
    pub const RESPAWN: u8 = 3;
    pub const EFFECT_APPLY: u8 = 4;
    pub const EFFECT_REMOVE: u8 = 5;
    pub const PICKUP: u8 = 6;
    pub const LEVEL_UP: u8 = 7;
    pub const CHAT_MESSAGE: u8 = 8;
    pub const PLAYER_INFO: u8 = 9;
    pub const KILL_PVP: u8 = 10;
    pub const LEADERBOARD_UPDATE: u8 = 11;
    pub const PROJECTILE_FIRED: u8 = 12;
    /// A player gained experience (e.g. a nearby monster died). Tail: [u16 amount].
    /// source_id = the player who gained it. Cosmetic-only "+XP" floater; the SERVER owns the
    /// level/XP accounting now (see PROGRESS) — this no longer drives client-side leveling.
    pub const EXP_GAIN: u8 = 13;
    /// A transient ability effect to render (explosion / charge-blast / shadowstep-blink /
    /// mine-detonation). Tail: [u8 effect_id][i16 x][i16 y][u16 radius]. `effect_id` selects the
    /// client VFX; position is the effect centre; radius (units) sizes it (0 = point effect).
    pub const ABILITY_EFFECT: u8 = 14;
    /// Server→owner authoritative level/XP for HUD display (the server owns leveling now).
    /// Tail: [u16 level][u32 experience][u8 move_speed_q] — `move_speed_q` is the effective base
    /// move speed ÷ 4 (clamped 0..255) so the client adopts the same speed without re-deriving it.
    pub const PROGRESS: u8 = 15;
}

/// ActionConfirm action types — GDScript `ActionConfirmPacket.ActionType`.
pub mod action_type {
    pub const MOVE: u8 = 0;
    pub const SHOOT: u8 = 1;
    pub const ABILITY: u8 = 2;
    pub const INTERACT: u8 = 3;
}

/// ActionConfirm result codes — GDScript `ActionConfirmPacket.ResultCode`.
pub mod result_code {
    pub const SUCCESS: u8 = 0;
    pub const FAILED_INVALID_POSITION: u8 = 1;
    pub const FAILED_COOLDOWN: u8 = 2;
    pub const FAILED_NO_TARGET: u8 = 3;
    pub const FAILED_BLOCKED: u8 = 4;
    pub const FAILED_INVALID_STATE: u8 = 5;
}

/// AuthResult result codes (new in the redesign — D9 gives auth an explicit reject path).
pub mod auth_result_code {
    pub const OK: u8 = 0;
    pub const BAD_VERSION: u8 = 1;
    pub const BAD_TICKET: u8 = 2;
    pub const EXPIRED: u8 = 3;
    pub const WRONG_REGION: u8 = 4;
    pub const SERVER_FULL: u8 = 5;
    pub const DUPLICATE_SESSION: u8 = 6;
}

/// Disconnect reasons, carried in the ENet disconnect `data: u32` — GDScript `DisconnectReason`.
pub mod disconnect_reason {
    pub const USER_QUIT: u32 = 0;
    pub const TIMEOUT: u32 = 1;
    pub const KICKED: u32 = 2;
    pub const SERVER_SHUTDOWN: u32 = 3;
    pub const INVALID_AUTH: u32 = 4;
    pub const DUPLICATE_SESSION: u32 = 5;
}

/// Regions — GDScript `AuthPacket.Region`.
pub mod region {
    pub const ASIA: u8 = 0;
    pub const EUROPE: u8 = 1;
    pub const US_WEST: u8 = 2;
    pub const US_EAST: u8 = 3;
}
