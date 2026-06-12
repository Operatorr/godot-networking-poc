//! The snapshot/broadcast pipeline: AoI filter with hysteresis, per-peer delta caches,
//! the byte-budget priority scheduler, and baseline/ack bookkeeping — port of
//! `server_broadcast_service.gd` / `delta_state_cache.gd` / `snapshot_scheduler.gd` /
//! `spatial_grid.gd` (extraction server-tick §4.8–4.9).
//!
//! Budget accounting deviates from the GDScript's fixed 10/3-byte size table in one way:
//! predicted sizes are the REAL bit-level record sizes of the redesigned protocol (D3), so the
//! budget reflects actual wire bytes. Semantics (greedy admission in priority order, pinned
//! removals bypass-and-consume, deferral keeps entries dirty) are identical.

use crate::outbox::Outbox;
use crate::player::{PeerKey, PlayerManager};
use protocol::types::{delta_mask, game_event_type};
use protocol::{EntityRecord, GameEvent, GameEventData, ServerPacket, Snapshot};
use sim_core::Vec2;
use std::collections::HashMap;

pub const DELTA_FULL_STATE_INTERVAL: u64 = 100;
pub const BASELINE_ACK_TIMEOUT_TICKS: u64 = 30;
/// Position-equality epsilon: half the 0.1-unit wire quantization step, strict `<` per axis.
pub const POSITION_EPSILON: f32 = 0.05;
/// Full-state entity cap carried from the old 65535-byte frame (per-packet diagnostic parity).
pub const STATE_MAX_FULL_ENTITIES: usize = 7280;

// Scheduler constants (extraction server-tick §2.3).
const PRIORITY_PLAYER: i64 = 10;
const PRIORITY_PROJECTILE: i64 = 8;
const PRIORITY_MONSTER: i64 = 4;
const PRIORITY_DEFAULT: i64 = 1;
const DISTANCE_PENALTY_BY_LOD: [i64; 3] = [0, 4, 8];

pub const LOD_NEAR: u8 = 0;
pub const LOD_MID: u8 = 1;
pub const LOD_FAR: u8 = 2;

/// The per-entity data the snapshot pipeline consumes (`to_entity_data` equivalents).
#[derive(Debug, Clone, Copy)]
pub struct EntityData {
    pub id: u16,
    pub position: Vec2,
    pub animation: u8,
    pub flags: u16,
}

// ── Delta state cache (one per peer) ────────────────────────────────────────

#[derive(Debug, Clone)]
struct CachedEntityState {
    position: Vec2,
    animation: u8,
    flags: u16,
    last_tick_sent: u64,
    is_new: bool,
}

#[derive(Default)]
pub struct DeltaStateCache {
    cache: HashMap<u16, CachedEntityState>,
    baseline_tick: u64,
    acked_baseline_tick: u64,
    /// 0 = none outstanding (sentinel — a genuine baseline at tick 0 cannot exist).
    pending_baseline_tick: u64,
}

impl DeltaStateCache {
    pub fn calculate_delta_mask(&self, entity_id: u16, current: &EntityData, tick: u64) -> u8 {
        let Some(cached) = self.cache.get(&entity_id) else {
            return delta_mask::FULL;
        };
        if cached.is_new {
            return delta_mask::FULL;
        }
        if tick - self.baseline_tick >= DELTA_FULL_STATE_INTERVAL {
            return delta_mask::FULL;
        }
        let mut mask = 0u8;
        let positions_equal = (cached.position.x - current.position.x).abs() < POSITION_EPSILON
            && (cached.position.y - current.position.y).abs() < POSITION_EPSILON;
        if !positions_equal {
            mask |= delta_mask::POSITION;
        }
        if cached.animation != current.animation {
            mask |= delta_mask::ANIMATION;
        }
        if cached.flags != current.flags {
            mask |= delta_mask::FLAGS;
        }
        mask
    }

    fn update_cache(&mut self, entity_id: u16, state: &EntityData, tick: u64) {
        let e = self.cache.entry(entity_id).or_insert(CachedEntityState {
            position: Vec2::ZERO,
            animation: 0,
            flags: 0,
            last_tick_sent: 0,
            is_new: true,
        });
        e.position = state.position;
        e.animation = state.animation;
        e.flags = state.flags;
        e.last_tick_sent = tick;
        e.is_new = false;
    }

    /// Mask-aware: only fields whose bit is set are committed; withheld fields stay dirty
    /// (what makes deferral lossless — extraction server-tick gotcha #27).
    fn update_cache_partial(&mut self, entity_id: u16, state: &EntityData, mask: u8, tick: u64) {
        let e = self.cache.entry(entity_id).or_insert(CachedEntityState {
            position: Vec2::ZERO,
            animation: 0,
            flags: 0,
            last_tick_sent: 0,
            is_new: true,
        });
        if mask & delta_mask::FULL != 0 {
            e.position = state.position;
            e.animation = state.animation;
            e.flags = state.flags;
        } else {
            if mask & delta_mask::POSITION != 0 {
                e.position = state.position;
            }
            if mask & delta_mask::ANIMATION != 0 {
                e.animation = state.animation;
            }
            if mask & delta_mask::FLAGS != 0 {
                e.flags = state.flags;
            }
        }
        e.last_tick_sent = tick;
        e.is_new = false;
    }

    fn last_tick_sent(&self, entity_id: u16) -> Option<u64> {
        self.cache.get(&entity_id).map(|e| e.last_tick_sent)
    }

    /// Erase cache entries not in the active set; returns the erased ids (pinned despawns).
    fn cleanup_stale_entities(&mut self, active: &[u16]) -> Vec<u16> {
        let stale: Vec<u16> = self
            .cache
            .keys()
            .copied()
            .filter(|id| !active.contains(id))
            .collect();
        for id in &stale {
            self.cache.remove(id);
        }
        stale
    }

    pub fn needs_full_state_for_interval(&self, tick: u64) -> bool {
        tick - self.baseline_tick >= DELTA_FULL_STATE_INTERVAL
    }

    pub fn needs_baseline_resend(&self, tick: u64) -> bool {
        if self.baseline_tick == 0 {
            return false;
        }
        self.pending_baseline_tick > 0
            && tick - self.pending_baseline_tick >= BASELINE_ACK_TIMEOUT_TICKS
    }

    fn reset_baseline(&mut self, tick: u64) {
        self.baseline_tick = tick;
        self.pending_baseline_tick = tick;
    }

    pub fn mark_baseline_acked(&mut self, acked: u64) {
        if acked >= self.acked_baseline_tick {
            self.acked_baseline_tick = acked;
        }
        if acked >= self.pending_baseline_tick {
            self.pending_baseline_tick = 0;
        }
    }

    pub fn baseline_tick(&self) -> u64 {
        self.baseline_tick
    }
}

// ── Spatial grid (broad phase for AoI) ──────────────────────────────────────

pub struct SpatialGrid {
    cell_size: f32,
    buckets: HashMap<(i32, i32), Vec<usize>>,
}

impl SpatialGrid {
    pub fn new(cell_size: f32) -> Self {
        Self {
            cell_size: cell_size.max(1.0),
            buckets: HashMap::new(),
        }
    }

    fn cell_of(&self, pos: Vec2) -> (i32, i32) {
        // True floor — correct for negative coordinates (extraction H4).
        (
            (pos.x / self.cell_size).floor() as i32,
            (pos.y / self.cell_size).floor() as i32,
        )
    }

    pub fn insert(&mut self, index: usize, pos: Vec2) {
        self.buckets
            .entry(self.cell_of(pos))
            .or_default()
            .push(index);
    }

    /// Superset query: all items in the (2r+1)² cell square; the caller distance-filters.
    pub fn query_radius(&self, center: Vec2, radius: f32) -> Vec<usize> {
        let r_cells = (radius / self.cell_size).ceil() as i32;
        let (cx, cy) = self.cell_of(center);
        let mut out = Vec::new();
        for y in (cy - r_cells)..=(cy + r_cells) {
            for x in (cx - r_cells)..=(cx + r_cells) {
                if let Some(bucket) = self.buckets.get(&(x, y)) {
                    out.extend_from_slice(bucket);
                }
            }
        }
        out
    }
}

// ── Scheduler ───────────────────────────────────────────────────────────────

struct Candidate {
    index: usize,
    entity_id: u16,
    priority: i64,
    encoded_bits: usize,
    ticks_since_last_sent: u64,
    pinned: bool,
}

#[derive(Default)]
pub struct ScheduleStats {
    pub deferred: usize,
    pub max_queue_age_ticks: u64,
    pub hit_budget: bool,
}

fn importance(entity_id: u16) -> i64 {
    use protocol::types::EntityType;
    match protocol::entity_type_for_id(entity_id) {
        Some(EntityType::Player) => PRIORITY_PLAYER,
        Some(EntityType::Projectile) => PRIORITY_PROJECTILE,
        Some(EntityType::Monster) => PRIORITY_MONSTER,
        None => PRIORITY_DEFAULT,
    }
}

fn change_bonus(mask: u8) -> i64 {
    if mask & delta_mask::FULL != 0 || mask & delta_mask::REMOVED != 0 {
        return 6;
    }
    let mut bonus = 0;
    for bit in [
        delta_mask::POSITION,
        delta_mask::ANIMATION,
        delta_mask::FLAGS,
    ] {
        if mask & bit != 0 {
            bonus += 2;
        }
    }
    bonus
}

/// Greedy admission in (priority desc, entity_id asc) order; pinned entries bypass AND consume
/// the budget; no early break (smaller items may still fit); `max_bytes == 0` disables.
fn schedule(candidates: &mut [Candidate], max_bytes: usize) -> (Vec<usize>, ScheduleStats, usize) {
    candidates.sort_by(|a, b| {
        b.priority
            .cmp(&a.priority)
            .then(a.entity_id.cmp(&b.entity_id))
    });
    let max_bits = max_bytes * 8;
    let mut bits = 0usize;
    let mut selected = Vec::with_capacity(candidates.len());
    let mut stats = ScheduleStats::default();
    for c in candidates.iter() {
        stats.max_queue_age_ticks = stats.max_queue_age_ticks.max(c.ticks_since_last_sent);
        let fits = max_bits == 0 || bits + c.encoded_bits <= max_bits;
        if c.pinned || fits {
            selected.push(c.index);
            bits += c.encoded_bits;
        } else {
            stats.deferred += 1;
            stats.hit_budget = true;
        }
    }
    (selected, stats, bits)
}

// ── Broadcast service ───────────────────────────────────────────────────────

#[derive(Default, Debug, Clone)]
pub struct TickDiagnostics {
    pub entities_deferred_per_tick: u64,
    pub max_queue_age_ticks: u64,
    pub peers_at_budget_pct: u8,
    pub peers_evaluated: u64,
    /// Cumulative for the service lifetime (only ever incremented).
    pub snapshot_count_overflow: u64,
}

pub struct BroadcastService {
    pub aoi_radius: f32,
    pub aoi_exit_radius: f32,
    pub lod_near_radius_sq: f32,
    pub lod_mid_radius_sq: f32,
    pub max_snapshot_bytes: usize,
    delta_caches: HashMap<PeerKey, DeltaStateCache>,
    visible_entities: HashMap<PeerKey, Vec<u16>>,
    peer_snapshot_bytes: HashMap<PeerKey, usize>,
    pub diagnostics: TickDiagnostics,
}

impl BroadcastService {
    pub fn new(
        aoi_radius: f32,
        aoi_exit_radius: f32,
        lod_near_radius: f32,
        lod_mid_radius: f32,
        max_snapshot_bytes: usize,
    ) -> Self {
        Self {
            aoi_radius,
            aoi_exit_radius,
            lod_near_radius_sq: lod_near_radius * lod_near_radius,
            lod_mid_radius_sq: lod_mid_radius * lod_mid_radius,
            max_snapshot_bytes,
            delta_caches: HashMap::new(),
            visible_entities: HashMap::new(),
            peer_snapshot_bytes: HashMap::new(),
            diagnostics: TickDiagnostics::default(),
        }
    }

    pub fn get_or_create_delta_cache(&mut self, peer: PeerKey) -> &mut DeltaStateCache {
        self.delta_caches.entry(peer).or_default()
    }

    pub fn remove_peer(&mut self, peer: PeerKey) {
        self.delta_caches.remove(&peer);
        self.visible_entities.remove(&peer);
        self.peer_snapshot_bytes.remove(&peer);
    }

    /// Stored as-is; missing entries fall back to `max_snapshot_bytes` (never 0 — 0 would
    /// disable the budget).
    pub fn set_peer_byte_budget(&mut self, peer: PeerKey, bytes: usize) {
        self.peer_snapshot_bytes.insert(peer, bytes);
    }

    fn classify_lod(&self, dist_sq: f32) -> u8 {
        if self.lod_near_radius_sq > 0.0 && dist_sq <= self.lod_near_radius_sq {
            LOD_NEAR
        } else if self.lod_mid_radius_sq > 0.0 && dist_sq <= self.lod_mid_radius_sq {
            LOD_MID
        } else {
            LOD_FAR
        }
    }

    /// Per-snapshot-tick broadcast: one STATE_UPDATE per authenticated peer.
    #[allow(clippy::too_many_arguments)]
    pub fn broadcast_state_updates(
        &mut self,
        all_entities: &[EntityData],
        players: &PlayerManager,
        tick: u64,
        server_ms: u32,
        outbox: &mut Outbox,
    ) {
        let peers: Vec<(PeerKey, u16, Vec2)> = players
            .players
            .iter()
            .filter(|p| p.authenticated)
            .map(|p| (p.peer, p.entity_id, p.position))
            .collect();
        if peers.is_empty() {
            // Zero the per-tick fields so SERVER_METRICS doesn't re-broadcast stale numbers
            // while only pre-auth peers are connected.
            self.diagnostics.entities_deferred_per_tick = 0;
            self.diagnostics.max_queue_age_ticks = 0;
            self.diagnostics.peers_evaluated = 0;
            self.diagnostics.peers_at_budget_pct = 0;
            return;
        }

        let aoi_enabled = self.aoi_radius > 0.0;
        let effective_exit = if self.aoi_exit_radius > self.aoi_radius {
            self.aoi_exit_radius
        } else {
            self.aoi_radius
        };
        let cell = if effective_exit > 0.0 {
            effective_exit / 4.0
        } else {
            256.0
        };
        let mut grid = SpatialGrid::new(cell);
        for (i, e) in all_entities.iter().enumerate() {
            grid.insert(i, e.position);
        }
        let enter_sq = self.aoi_radius * self.aoi_radius;
        let exit_sq = if self.aoi_exit_radius > self.aoi_radius {
            self.aoi_exit_radius * self.aoi_exit_radius
        } else {
            enter_sq
        };

        let mut tick_total_deferred = 0u64;
        let mut tick_max_queue_age = 0u64;
        let mut tick_peers_at_budget = 0u64;
        let mut tick_peers_evaluated = 0u64;

        for (peer, self_entity_id, self_position) in peers {
            let prev_visible = self
                .visible_entities
                .get(&peer)
                .cloned()
                .unwrap_or_default();

            // AoI filter with hysteresis (strict >: exactly-on-radius stays visible).
            let mut visible: Vec<(usize, u8)> = Vec::new(); // (entity index, lod)
            let mut self_seen = false;
            if aoi_enabled {
                for idx in grid.query_radius(self_position, effective_exit) {
                    let e = &all_entities[idx];
                    if e.id == self_entity_id {
                        visible.push((idx, LOD_NEAR));
                        self_seen = true;
                        continue;
                    }
                    let dist_sq = self_position.distance_squared_to(e.position);
                    let threshold_sq = if prev_visible.contains(&e.id) {
                        exit_sq
                    } else {
                        enter_sq
                    };
                    if dist_sq > threshold_sq {
                        continue;
                    }
                    visible.push((idx, self.classify_lod(dist_sq)));
                }
                if !self_seen {
                    // Cell-edge rounding safety net: self is never culled.
                    if let Some(idx) = all_entities.iter().position(|e| e.id == self_entity_id) {
                        visible.push((idx, LOD_NEAR));
                    }
                }
            } else {
                visible = (0..all_entities.len()).map(|i| (i, LOD_NEAR)).collect();
            }

            let current_visible: Vec<u16> =
                visible.iter().map(|(i, _)| all_entities[*i].id).collect();
            let removed_entity_ids: Vec<u16> = if aoi_enabled {
                prev_visible
                    .iter()
                    .copied()
                    .filter(|id| !current_visible.contains(id))
                    .collect()
            } else {
                Vec::new()
            };
            self.visible_entities.insert(peer, current_visible);

            let cache = self.delta_caches.entry(peer).or_default();
            let needs_baseline =
                cache.needs_full_state_for_interval(tick) || cache.needs_baseline_resend(tick);

            let packet = if needs_baseline && removed_entity_ids.is_empty() {
                let entities: Vec<EntityData> =
                    visible.iter().map(|(i, _)| all_entities[*i]).collect();
                let snap = create_full_state_packet(&entities, cache, tick, server_ms);
                if entities.len() > STATE_MAX_FULL_ENTITIES {
                    self.diagnostics.snapshot_count_overflow += 1;
                }
                snap
            } else {
                let peer_max = self
                    .peer_snapshot_bytes
                    .get(&peer)
                    .copied()
                    .unwrap_or(self.max_snapshot_bytes);
                let (snap, stats) = create_delta_packet(
                    all_entities,
                    &visible,
                    cache,
                    tick,
                    server_ms,
                    &removed_entity_ids,
                    peer_max,
                );
                tick_peers_evaluated += 1;
                tick_total_deferred += stats.deferred as u64;
                tick_max_queue_age = tick_max_queue_age.max(stats.max_queue_age_ticks);
                if stats.hit_budget {
                    tick_peers_at_budget += 1;
                }
                snap
            };
            outbox.send(peer, ServerPacket::Snapshot(packet));
        }

        self.diagnostics.entities_deferred_per_tick = tick_total_deferred;
        self.diagnostics.max_queue_age_ticks = tick_max_queue_age;
        self.diagnostics.peers_evaluated = tick_peers_evaluated;
        self.diagnostics.peers_at_budget_pct = if tick_peers_evaluated > 0 {
            ((100.0 * tick_peers_at_budget as f64 / tick_peers_evaluated as f64).round() as i64)
                .clamp(0, 255) as u8
        } else {
            0
        };
    }

    /// REQUEST_FULL_STATE reply: ALL entities, no AoI filter; counts as a Baseline; then a
    /// PLAYER_INFO replay for every authenticated player (Authority-sync recovery).
    pub fn handle_full_state_request(
        &mut self,
        peer: PeerKey,
        all_entities: &[EntityData],
        players: &PlayerManager,
        tick: u64,
        server_ms: u32,
        outbox: &mut Outbox,
    ) {
        let cache = self.delta_caches.entry(peer).or_default();
        let snap = create_full_state_packet(all_entities, cache, tick, server_ms);
        if all_entities.len() > STATE_MAX_FULL_ENTITIES {
            self.diagnostics.snapshot_count_overflow += 1;
        }
        outbox.send(peer, ServerPacket::Snapshot(snap));
        for p in players.players.iter().filter(|p| p.authenticated) {
            outbox.send(
                peer,
                player_info_event(
                    p.entity_id,
                    &p.character_name,
                    p.position,
                    p.player_color,
                    p.player_class,
                ),
            );
        }
    }

    pub fn mark_baseline_acked(&mut self, peer: PeerKey, baseline_tick: u64) {
        if let Some(cache) = self.delta_caches.get_mut(&peer) {
            cache.mark_baseline_acked(baseline_tick);
        }
    }

    /// Shutdown path.
    #[allow(dead_code)]
    pub fn clear_all_caches(&mut self) {
        self.delta_caches.clear();
        self.visible_entities.clear();
        self.peer_snapshot_bytes.clear();
    }
}

pub fn player_info_event(
    entity_id: u16,
    name: &str,
    position: Vec2,
    color: (u8, u8, u8),
    class: u8,
) -> ServerPacket {
    ServerPacket::GameEvent(GameEvent {
        event_type: game_event_type::PLAYER_INFO,
        source_id: 0,
        target_id: entity_id,
        data: GameEventData::PlayerInfo {
            name: name.to_string(),
            x: position.x,
            y: position.y,
            color,
            class,
        },
    })
}

/// Deviation from GDScript: only the entities that actually make the packet are cached
/// (GDScript cached all, then truncated on the wire — stranding unsent entities as "sent").
fn create_full_state_packet(
    entities: &[EntityData],
    cache: &mut DeltaStateCache,
    tick: u64,
    server_ms: u32,
) -> Snapshot {
    let mut records = Vec::with_capacity(entities.len().min(STATE_MAX_FULL_ENTITIES));
    for e in entities.iter().take(STATE_MAX_FULL_ENTITIES) {
        records.push(EntityRecord::full(
            e.id,
            (e.position.x, e.position.y),
            e.animation,
            e.flags,
        ));
        cache.update_cache(e.id, e, tick);
    }
    cache.reset_baseline(tick);
    Snapshot {
        server_tick: tick as u32,
        server_ms,
        is_baseline: true,
        baseline_tick: None,
        entities: records,
    }
}

fn create_delta_packet(
    all_entities: &[EntityData],
    visible: &[(usize, u8)],
    cache: &mut DeltaStateCache,
    tick: u64,
    server_ms: u32,
    removed_entity_ids: &[u16],
    peer_max_bytes: usize,
) -> (Snapshot, ScheduleStats) {
    struct Staged {
        record: EntityRecord,
        current: Option<EntityData>,
        mask: u8,
    }
    let mut staged: Vec<Staged> = Vec::new();
    let mut candidates: Vec<Candidate> = Vec::new();
    let mut removed_set: Vec<u16> = Vec::new();
    let mut active_entity_ids: Vec<u16> = Vec::new();

    // 1. AoI-exit removals — pinned.
    for &entity_id in removed_entity_ids {
        removed_set.push(entity_id);
        let record = EntityRecord::removed(entity_id);
        let bits = record.wire_bits(false);
        staged.push(Staged {
            record,
            current: None,
            mask: delta_mask::REMOVED,
        });
        candidates.push(Candidate {
            index: staged.len() - 1,
            entity_id,
            priority: PRIORITY_PLAYER + change_bonus(delta_mask::REMOVED),
            encoded_bits: bits,
            ticks_since_last_sent: 0,
            pinned: true,
        });
    }

    // 2. Visible entities with a non-zero delta mask.
    for &(idx, lod) in visible {
        let e = &all_entities[idx];
        active_entity_ids.push(e.id);
        let mask = cache.calculate_delta_mask(e.id, e, tick);
        if mask == 0 {
            continue; // unchanged entities cost zero bytes
        }
        let ticks_since = match cache.last_tick_sent(e.id) {
            Some(t) => tick - t,
            None => tick, // new-entity priority ≈ tick_count — preserved (gotcha #4)
        };
        let record = if mask & delta_mask::FULL != 0 {
            EntityRecord::full(e.id, (e.position.x, e.position.y), e.animation, e.flags)
        } else {
            EntityRecord {
                entity_id: e.id,
                delta_mask: mask,
                position: (mask & delta_mask::POSITION != 0)
                    .then_some((e.position.x, e.position.y)),
                animation: (mask & delta_mask::ANIMATION != 0).then_some(e.animation),
                flags: (mask & delta_mask::FLAGS != 0).then_some(e.flags),
            }
        };
        let bits = record.wire_bits(false);
        staged.push(Staged {
            record,
            current: Some(*e),
            mask,
        });
        candidates.push(Candidate {
            index: staged.len() - 1,
            entity_id: e.id,
            priority: importance(e.id) + ticks_since as i64
                - DISTANCE_PENALTY_BY_LOD
                    .get(lod as usize)
                    .copied()
                    .unwrap_or(0)
                + change_bonus(mask),
            encoded_bits: bits,
            ticks_since_last_sent: ticks_since,
            pinned: false,
        });
    }

    // 3. Stale cache entries (left AoI tracking entirely) — pinned despawns.
    for entity_id in cache.cleanup_stale_entities(&active_entity_ids) {
        if removed_set.contains(&entity_id) {
            continue;
        }
        let record = EntityRecord::removed(entity_id);
        let bits = record.wire_bits(false);
        staged.push(Staged {
            record,
            current: None,
            mask: delta_mask::REMOVED,
        });
        candidates.push(Candidate {
            index: staged.len() - 1,
            entity_id,
            priority: PRIORITY_PLAYER + change_bonus(delta_mask::REMOVED),
            encoded_bits: bits,
            ticks_since_last_sent: 0,
            pinned: true,
        });
    }

    let (selected, stats, _bits) = schedule(&mut candidates, peer_max_bytes);
    let mut records = Vec::with_capacity(selected.len());
    for idx in selected {
        let s = &staged[idx];
        if let Some(current) = &s.current {
            cache.update_cache_partial(s.record.entity_id, current, s.mask, tick);
        }
        records.push(s.record.clone());
    }

    (
        Snapshot {
            server_tick: tick as u32,
            server_ms,
            is_baseline: false,
            baseline_tick: Some(cache.baseline_tick() as u32),
            entities: records,
        },
        stats,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entity(id: u16, x: f32, y: f32) -> EntityData {
        EntityData {
            id,
            position: Vec2::new(x, y),
            animation: 0,
            flags: 0x21,
        }
    }

    #[test]
    fn first_contact_is_full_state_mask() {
        let cache = DeltaStateCache::default();
        let mask = cache.calculate_delta_mask(1, &entity(1, 0.0, 0.0), 5);
        assert_eq!(mask, delta_mask::FULL);
    }

    #[test]
    fn sub_epsilon_motion_is_mask_zero() {
        let mut cache = DeltaStateCache::default();
        let e = entity(1, 10.0, 10.0);
        cache.update_cache(1, &e, 1);
        cache.reset_baseline(1);
        let moved = entity(1, 10.04, 10.04);
        assert_eq!(cache.calculate_delta_mask(1, &moved, 2), 0);
        let moved_more = entity(1, 10.06, 10.0);
        assert_eq!(
            cache.calculate_delta_mask(1, &moved_more, 2),
            delta_mask::POSITION
        );
    }

    #[test]
    fn baseline_interval_forces_full() {
        let mut cache = DeltaStateCache::default();
        let e = entity(1, 0.0, 0.0);
        cache.update_cache(1, &e, 1);
        cache.reset_baseline(1);
        assert_eq!(cache.calculate_delta_mask(1, &e, 100), 0);
        assert_eq!(cache.calculate_delta_mask(1, &e, 101), delta_mask::FULL);
    }

    #[test]
    fn baseline_ack_and_resend_flow() {
        let mut cache = DeltaStateCache::default();
        assert!(!cache.needs_baseline_resend(50)); // never sent one
        cache.reset_baseline(100);
        assert!(!cache.needs_baseline_resend(120));
        assert!(cache.needs_baseline_resend(130)); // 30 un-acked ticks
        cache.mark_baseline_acked(100);
        assert!(!cache.needs_baseline_resend(200));
        // Stale acks are ignored.
        cache.reset_baseline(300);
        cache.mark_baseline_acked(100);
        assert!(cache.needs_baseline_resend(330));
    }

    #[test]
    fn scheduler_pinned_bypasses_budget() {
        let mut candidates = vec![
            Candidate {
                index: 0,
                entity_id: 1,
                priority: 100,
                encoded_bits: 8000,
                ticks_since_last_sent: 0,
                pinned: false,
            },
            Candidate {
                index: 1,
                entity_id: 2,
                priority: 1,
                encoded_bits: 8000,
                ticks_since_last_sent: 5,
                pinned: true,
            },
        ];
        let (selected, stats, _) = schedule(&mut candidates, 100); // 800 bits budget
        assert_eq!(
            selected,
            vec![1],
            "pinned admitted, oversized non-pinned deferred"
        );
        assert_eq!(stats.deferred, 1);
        assert!(stats.hit_budget);
        assert_eq!(stats.max_queue_age_ticks, 5);
    }

    #[test]
    fn scheduler_no_early_break() {
        let mut candidates = vec![
            Candidate {
                index: 0,
                entity_id: 1,
                priority: 10,
                encoded_bits: 900,
                ticks_since_last_sent: 0,
                pinned: false,
            },
            Candidate {
                index: 1,
                entity_id: 2,
                priority: 5,
                encoded_bits: 50,
                ticks_since_last_sent: 0,
                pinned: false,
            },
        ];
        let (selected, stats, _) = schedule(&mut candidates, 100); // 800 bits
        assert_eq!(
            selected,
            vec![1],
            "smaller lower-priority item still admitted"
        );
        assert_eq!(stats.deferred, 1);
    }

    #[test]
    fn broadcast_emits_baseline_then_deltas_then_removal() {
        let mut svc = BroadcastService::new(1000.0, 1100.0, 400.0, 1000.0, 1200);
        let mut players = PlayerManager::new();
        let p = players.add_player(1).unwrap();
        p.authenticated = true;
        p.position = Vec2::new(0.0, 600.0); // clear of obstacles
        let self_id = players.players[0].entity_id;

        let mut outbox = Outbox::new();
        // Tick 100: interval forces a baseline (baseline_tick starts 0).
        let entities = vec![entity(self_id, 0.0, 600.0), entity(30005, 100.0, 600.0)];
        svc.broadcast_state_updates(&entities, &players, 100, 0, &mut outbox);
        let msgs = outbox.drain();
        assert_eq!(msgs.len(), 1);
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert!(s.is_baseline);
        assert_eq!(s.entities.len(), 2);

        // Next tick: nothing changed → empty delta.
        svc.mark_baseline_acked(1, 100);
        svc.broadcast_state_updates(&entities, &players, 101, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert!(!s.is_baseline);
        assert_eq!(s.baseline_tick, Some(100));
        assert_eq!(s.entities.len(), 0);

        // Monster moves → position-only delta.
        let entities2 = vec![entity(self_id, 0.0, 600.0), entity(30005, 104.0, 600.0)];
        svc.broadcast_state_updates(&entities2, &players, 102, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert_eq!(s.entities.len(), 1);
        assert_eq!(s.entities[0].entity_id, 30005);
        assert_eq!(s.entities[0].delta_mask, delta_mask::POSITION);

        // Monster leaves the entity set entirely → stale-cache pinned REMOVED.
        let entities3 = vec![entity(self_id, 0.0, 600.0)];
        svc.broadcast_state_updates(&entities3, &players, 103, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert_eq!(s.entities.len(), 1);
        assert_eq!(s.entities[0].delta_mask, delta_mask::REMOVED);
        assert_eq!(s.entities[0].entity_id, 30005);
    }

    #[test]
    fn aoi_hysteresis_keeps_on_ring_entities() {
        let mut svc = BroadcastService::new(1000.0, 1100.0, 400.0, 1000.0, 1200);
        let mut players = PlayerManager::new();
        let p = players.add_player(1).unwrap();
        p.authenticated = true;
        p.position = Vec2::new(0.0, 0.0);
        let self_id = players.players[0].entity_id;
        let mut outbox = Outbox::new();

        // Monster exactly at the enter radius: strict > culling keeps it.
        let entities = vec![entity(self_id, 0.0, 0.0), entity(30001, 1000.0, 0.0)];
        svc.broadcast_state_updates(&entities, &players, 100, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert_eq!(s.entities.len(), 2, "exactly-on-radius entity is visible");

        // Move to 1050 — outside enter but inside exit: visible by hysteresis.
        let entities2 = vec![entity(self_id, 0.0, 0.0), entity(30001, 1050.0, 0.0)];
        svc.broadcast_state_updates(&entities2, &players, 101, 0, &mut outbox);
        outbox.drain();
        // Move to 1101 — beyond exit: a pinned REMOVED delta this tick.
        let entities3 = vec![entity(self_id, 0.0, 0.0), entity(30001, 1101.0, 0.0)];
        svc.broadcast_state_updates(&entities3, &players, 102, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert!(s
            .entities
            .iter()
            .any(|r| r.entity_id == 30001 && r.delta_mask & delta_mask::REMOVED != 0));
    }

    #[test]
    fn baseline_deferred_when_removals_pending() {
        let mut svc = BroadcastService::new(1000.0, 1100.0, 400.0, 1000.0, 1200);
        let mut players = PlayerManager::new();
        let p = players.add_player(1).unwrap();
        p.authenticated = true;
        p.position = Vec2::new(0.0, 0.0);
        let self_id = players.players[0].entity_id;
        let mut outbox = Outbox::new();

        // Establish visibility of a monster pre-baseline.
        let entities = vec![entity(self_id, 0.0, 0.0), entity(30001, 500.0, 0.0)];
        svc.broadcast_state_updates(&entities, &players, 50, 0, &mut outbox);
        outbox.drain();
        // At tick 150 a baseline is due, but the monster exits AoI the same tick ⇒ delta sent
        // instead (gotcha #3); the IS_DELTA packet carries the OLD baseline_tick (0).
        let entities2 = vec![entity(self_id, 0.0, 0.0), entity(30001, 1200.0, 0.0)];
        svc.broadcast_state_updates(&entities2, &players, 150, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert!(
            !s.is_baseline,
            "baseline must defer while AoI exits are pending"
        );
        assert_eq!(s.baseline_tick, Some(0));
        // Next tick (no removals): the true baseline goes out.
        let entities3 = vec![entity(self_id, 0.0, 0.0)];
        svc.broadcast_state_updates(&entities3, &players, 151, 0, &mut outbox);
        let msgs = outbox.drain();
        let ServerPacket::Snapshot(s) = &msgs[0].1 else {
            panic!()
        };
        assert!(s.is_baseline);
    }
}
