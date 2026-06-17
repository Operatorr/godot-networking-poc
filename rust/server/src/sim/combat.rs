//! Damage application, kill broadcasting, LOCAL_HIT_REPORT validation, and the D11 lenient
//! backstop — port of `server_collision_handler.gd` + `server_main.gd` hit handling
//! (extraction combat §4.8–4.12, §4.16).

use crate::ability::StatusEffect;
use crate::leaderboard::Leaderboard;
use crate::monster::MonsterManager;
use crate::outbox::Outbox;
use crate::player::{PeerKey, PlayerManager};
use crate::projectile::ProjectileManager;
use protocol::types::game_event_type;
use protocol::{GameEvent, GameEventData, ServerPacket};
use sim_core::constants::*;
use sim_core::progression;
use sim_core::{hit, MoveState, Vec2};
use std::collections::HashMap;
use tracing::debug;

pub const LOCAL_HIT_REPORT_MAX_PER_SECOND: u32 = 20;
pub const LOCAL_HIT_VALIDATION_MARGIN: f32 = 64.0;
/// 8 + 16 + 64 — the anti-grief plausibility bound; strictly larger than the 24 u hit window
/// by design (D11 invariant #4: it is NOT a hit re-check).
pub const LOCAL_HIT_PLAUSIBILITY_THRESHOLD: f32 =
    PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS + LOCAL_HIT_VALIDATION_MARGIN;

pub fn leaderboard_event(lb: &Leaderboard) -> ServerPacket {
    ServerPacket::GameEvent(GameEvent {
        event_type: game_event_type::LEADERBOARD_UPDATE,
        source_id: 0,
        target_id: 0,
        data: GameEventData::Leaderboard {
            entries: lb.top_n(10),
        },
    })
}

/// Everything a hit needs to resolve knockback: where it landed, which way the projectile was
/// travelling, and how hard that projectile knocks back (per-spawn, so weapons/abilities/items
/// can vary it).
#[derive(Debug, Clone, Copy)]
pub struct HitImpact {
    pub position: Vec2,
    /// Normalized projectile travel direction; `Vec2::ZERO` = unknown (fall back to
    /// away-from-impact geometry).
    pub direction: Vec2,
    pub knockback_force: f64,
}

impl HitImpact {
    pub fn from_projectile(proj: &crate::projectile::ProjectileState) -> Self {
        Self {
            position: proj.position,
            direction: proj.direction,
            knockback_force: proj.knockback_force,
        }
    }
}

/// The shared damage path for every PROJECTILE player hit (PvP collision, validated client report,
/// and the backstop). Damage is the flat per-source constant selected by owner-id range; a
/// projectile carries no extra status effects beyond the sprint-hit daze, so it delegates to
/// `apply_player_damage` with an empty effect list.
pub fn apply_player_hit(
    owner_id: u16,
    target_id: u16,
    players: &mut PlayerManager,
    leaderboard: &mut Leaderboard,
    outbox: &mut Outbox,
    impact: Option<HitImpact>,
) {
    let damage = if owner_id >= MONSTER_ENTITY_ID_START {
        MONSTER_PROJECTILE_DAMAGE
    } else {
        PLAYER_PROJECTILE_DAMAGE
    };
    apply_player_damage(
        owner_id,
        target_id,
        damage,
        &[],
        players,
        leaderboard,
        outbox,
        impact,
    );
}

/// The shared damage core for every player hit — projectiles (via `apply_player_hit`) AND instant
/// abilities that PvP (Mageblast). Applies `damage` from `owner_id`; DAMAGE broadcasts the APPLIED
/// delta; zero applied (dead/invulnerable/unauthenticated) ⇒ no event at all; status effects,
/// daze and knockback only on survival.
///
/// On survival, three things land in order: (1) the sprint-hit daze (any target caught SPRINTING),
/// (2) every `StatusEffect` the source inflicts — the Strategy dispatch: one `match` arm per
/// effect, so new effects on any spell/ability are added in exactly one place, (3) knockback if an
/// `impact` is supplied. Knockback pushes along the projectile's TRAVEL direction (predictable
/// "shot from the left ⇒ thrown to the right"), not away from the impact point — the discrete-tick
/// overlap test can place the impact point past the target's center, which made away-from-impact
/// feel random. AoE abilities pass `impact = None` (no knockback).
#[allow(clippy::too_many_arguments)]
pub fn apply_player_damage(
    owner_id: u16,
    target_id: u16,
    damage: i32,
    effects: &[StatusEffect],
    players: &mut PlayerManager,
    leaderboard: &mut Leaderboard,
    outbox: &mut Outbox,
    impact: Option<HitImpact>,
) {
    // Defense-in-depth: never let a source damage/daze/knockback itself. Callers already filter
    // (AoE excludes the caster; projectiles can't target their owner), but enforcing it here keeps
    // a future caller from silently enabling self-damage. Safe for PvE — monster owner ids are in a
    // disjoint range (>= MONSTER_ENTITY_ID_START) and can never equal a player target id.
    if owner_id == target_id {
        return;
    }
    let Some(target) = players.get_by_entity_id_mut(target_id) else {
        return;
    };
    if !target.authenticated {
        return;
    }
    let was_sprinting = target.movement_sm.state() == MoveState::Sprinting;
    let previous = target.health;
    let killed = target.take_damage(damage, owner_id as i32);
    let applied = previous - target.health;
    if applied <= 0 {
        return;
    }
    if !killed {
        if was_sprinting {
            target.movement_sm.apply_daze(PLAYER_DAZE_DURATION);
        }
        for effect in effects {
            match *effect {
                StatusEffect::Daze { secs } => target.movement_sm.apply_daze(secs),
            }
        }
        if let Some(impact) = impact {
            let knock_dir = if impact.direction != Vec2::ZERO && impact.direction.is_finite() {
                impact.direction
            } else if impact.position.is_finite() {
                target.position - impact.position
            } else {
                Vec2::ZERO
            };
            if knock_dir.length() > 0.01 {
                target
                    .movement_sm
                    .apply_knockback(knock_dir, impact.knockback_force, 1.0);
            }
        }
    }
    outbox.broadcast(ServerPacket::GameEvent(GameEvent {
        event_type: game_event_type::DAMAGE,
        source_id: owner_id,
        target_id,
        data: GameEventData::Damage {
            amount: applied as u16,
            damage_type: 0,
        },
    }));
    if killed {
        broadcast_player_kill(owner_id, target_id, players, leaderboard, outbox);
    }
}

fn broadcast_player_kill(
    killer_id: u16,
    victim_id: u16,
    players: &mut PlayerManager,
    leaderboard: &mut Leaderboard,
    outbox: &mut Outbox,
) {
    if killer_id < MONSTER_ENTITY_ID_START {
        // PvP branch.
        if killer_id == victim_id {
            return;
        }
        // Capture the victim's death position + level before any mutation: the kill XP mirrors a
        // monster kill (the victim is "worth" a monster of their level — see
        // progression::xp_reward_for_level) and is shared by proximity to where they fell.
        let Some((victim_pos, victim_level)) = players
            .get_by_entity_id(victim_id)
            .map(|v| (v.position, v.level))
        else {
            return;
        };
        let killer_exists_authenticated = match players.get_by_entity_id(killer_id) {
            Some(k) if !k.authenticated => return, // unauthenticated killer suppresses the event
            Some(_) => true,
            None => false, // disconnected killer: event still broadcasts, no credit
        };
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::KILL_PVP,
            source_id: killer_id,
            target_id: victim_id,
            data: GameEventData::None,
        }));
        if killer_exists_authenticated {
            if let Some(killer) = players.get_by_entity_id_mut(killer_id) {
                killer.pvp_kills += 1;
            }
            leaderboard.record_pvp_kill(killer_id, victim_id);
            // No inline broadcast: record_pvp_kill marks the board dirty and the tick loop flushes a
            // single leaderboard snapshot at end-of-tick, coalescing AoE multi-kills (see World::tick).
        }
        // Award shared XP to every living player near the kill (the killer + any co-contributor),
        // exactly like a monster kill. Granted even if the last-hit killer disconnected, so the
        // other contributor in a brawl still gets credit.
        let xp = progression::xp_reward_for_level(victim_level);
        grant_shared_kill_experience(victim_pos, xp, players, outbox);
    } else {
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::KILL,
            source_id: killer_id,
            target_id: victim_id,
            data: GameEventData::None,
        }));
    }
}

/// Tick step 5 — players pass first, then monsters pass (extraction combat §1). Returns the
/// positions of monsters killed this pass, so the caller can roll healthorb drops (which need the
/// world RNG + the world-entity manager, not held here).
pub fn process_collisions(
    projectiles: &mut ProjectileManager,
    players: &mut PlayerManager,
    monsters: &mut MonsterManager,
    leaderboard: &mut Leaderboard,
    outbox: &mut Outbox,
    pvp_enabled: bool,
) -> Vec<Vec2> {
    // PvP pass — disabled in the safe Sanctuary (you can shoot, but projectiles don't hit players).
    if pvp_enabled {
        let player_hits = projectiles.check_collisions_with_players(players);
        for h in player_hits {
            apply_player_hit(
                h.owner_id,
                h.target_id,
                players,
                leaderboard,
                outbox,
                Some(HitImpact {
                    position: h.position,
                    direction: h.direction,
                    knockback_force: h.knockback_force,
                }),
            );
        }
    }

    // PvE pass (player projectiles vs lag-rewound monsters).
    let mut killed_positions = Vec::new();
    let monster_hits =
        projectiles.check_collisions_with_monsters(|t| monsters.get_alive_snapshot(t));
    for h in monster_hits {
        // Per-projectile class+level-scaled damage; 0 ⇒ legacy flat constant.
        let amount = if h.damage > 0 {
            h.damage
        } else {
            PLAYER_PROJECTILE_DAMAGE
        };
        if let Some(pos) =
            apply_monster_damage(h.target_id, amount, h.owner_id, monsters, players, outbox)
        {
            killed_positions.push(pos);
        }
    }
    killed_positions
}

/// Apply `amount` damage to a monster from `owner_id`: broadcasts the applied DAMAGE and, on a
/// kill, the KILL event + server-authoritative XP, returning the monster's position (for the
/// caller's healthorb roll). Returns `None` if nothing was applied or the monster is gone. Shared
/// by the PvE projectile pass and every ability that hits monsters (bibles, mine, dot-zone,
/// mageblast, multishot, charge blast, shadowstep).
pub fn apply_monster_damage(
    monster_id: u16,
    amount: i32,
    owner_id: u16,
    monsters: &mut MonsterManager,
    players: &mut PlayerManager,
    outbox: &mut Outbox,
) -> Option<Vec2> {
    let (applied, killed, monster_pos, xp_reward) = {
        let monster = monsters.get_mut(monster_id)?;
        let previous = monster.health;
        let killed = monster.take_damage(amount);
        let applied = previous - monster.health;
        (
            applied,
            killed,
            monster.position,
            monster.definition.xp_reward,
        )
    };
    if applied <= 0 {
        return None;
    }
    outbox.broadcast(ServerPacket::GameEvent(GameEvent {
        event_type: game_event_type::DAMAGE,
        source_id: owner_id,
        target_id: monster_id,
        data: GameEventData::Damage {
            amount: applied as u16,
            damage_type: 0,
        },
    }));
    if killed {
        if let Some(killer) = players.get_by_entity_id_mut(owner_id) {
            if killer.authenticated {
                killer.monster_kills += 1;
            }
        }
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::KILL,
            source_id: owner_id,
            target_id: monster_id,
            data: GameEventData::None,
        }));
        grant_shared_kill_experience(monster_pos, xp_reward, players, outbox);
        return Some(monster_pos);
    }
    None
}

/// Server-authoritative XP grant on a kill (monster OR player). Every alive, authenticated player
/// within XP_SHARE_RADIUS of `death_pos` gets the full reward (no split) — so in a brawl every
/// contributor in range is rewarded, exactly like a monster kill. The SERVER owns leveling now: it
/// accumulates XP, resolves level-ups (recomputing class+level stats and fully restoring HP+mana),
/// marks progression dirty for the API write-back, and emits a PROGRESS event (authoritative HUD)
/// plus a cosmetic EXP_GAIN floater.
fn grant_shared_kill_experience(
    death_pos: Vec2,
    xp_reward: u32,
    players: &mut PlayerManager,
    outbox: &mut Outbox,
) {
    if xp_reward == 0 {
        return;
    }
    let radius_sq = XP_SHARE_RADIUS * XP_SHARE_RADIUS;
    // The EXP_GAIN floater is a cosmetic u16 on the wire, so it SATURATES at 65535 — at high victim
    // levels xp_reward_for_level exceeds that (e.g. ~108k at level 50) and the displayed "+N" caps out.
    // The authoritative grant below uses the full u32 xp_reward, so leveling is unaffected; only the
    // floater text is clamped. Widening the floater would require a wire-protocol bump.
    let amount = xp_reward.min(u16::MAX as u32) as u16;
    for player in players.players.iter_mut() {
        if !player.authenticated || !player.is_alive {
            continue;
        }
        if player.position.distance_squared_to(death_pos) > radius_sq {
            continue;
        }
        // Cosmetic "+N" floater.
        outbox.broadcast(ServerPacket::GameEvent(GameEvent {
            event_type: game_event_type::EXP_GAIN,
            source_id: player.entity_id,
            target_id: 0,
            data: GameEventData::ExpGain { amount },
        }));
        let (new_level, new_xp) =
            progression::apply_experience(player.level, player.experience, xp_reward);
        let leveled_up = new_level != player.level;
        if leveled_up {
            player.apply_class_and_level(player.player_class, new_level, new_xp);
            // A level-up fully restores HP and mana. apply_class_and_level already raised the HP
            // cap (and partially healed by the delta); top both off to full here.
            player.health = player.max_health;
            player.movement_sm.refill_mana();
        } else {
            player.experience = new_xp;
        }
        player.progression_dirty = true;
        // Authoritative HUD update to the owner.
        let move_speed_q = (player.effective_move_speed() / 4.0)
            .round()
            .clamp(0.0, 255.0) as u8;
        outbox.send(
            player.peer,
            ServerPacket::GameEvent(GameEvent {
                event_type: game_event_type::PROGRESS,
                source_id: player.entity_id,
                target_id: player.entity_id,
                data: GameEventData::Progress {
                    level: player.level,
                    experience: player.experience,
                    move_speed_q,
                },
            }),
        );
        // Progress above is owner-only; on a level-up re-broadcast PLAYER_INFO so every other
        // client's leaderboard shows this player's new level (identity fields are unchanged).
        if leveled_up {
            outbox.broadcast(crate::broadcast::player_info_event(
                player.entity_id,
                &player.character_name,
                player.position,
                player.player_color,
                player.player_class,
                player.level,
            ));
        }
    }
}

/// Per-peer fixed-window rate limiter; counter increments BEFORE the check (reports 1–20 pass).
#[derive(Default)]
pub struct HitReportLimiter {
    windows: HashMap<PeerKey, (u64, u32)>, // (start_ms, count)
}

impl HitReportLimiter {
    pub fn allow(&mut self, peer: PeerKey, now_ms: u64) -> bool {
        let entry = self.windows.entry(peer).or_insert((0, 0));
        if now_ms - entry.0 >= 1000 {
            entry.0 = now_ms;
            entry.1 = 0;
        }
        entry.1 += 1;
        entry.1 <= LOCAL_HIT_REPORT_MAX_PER_SECOND
    }

    pub fn remove_peer(&mut self, peer: PeerKey) {
        self.windows.remove(&peer);
    }
}

/// LOCAL_HIT_REPORT validation gauntlet — exact gate order (extraction combat §4.12). Any
/// failure silently drops the report. On success the hit applies to the REPORTING peer's own
/// entity (D11 invariant #2) and the projectile despawns unconditionally.
#[allow(clippy::too_many_arguments)]
pub fn handle_local_hit_report(
    peer: PeerKey,
    projectile_id: u16,
    players: &mut PlayerManager,
    projectiles: &mut ProjectileManager,
    leaderboard: &mut Leaderboard,
    limiter: &mut HitReportLimiter,
    backstop: &mut Backstop,
    outbox: &mut Outbox,
    now_ms: u64,
) {
    if projectile_id == 0 {
        return;
    }
    let Some(player) = players.get(peer) else {
        return;
    };
    if !player.authenticated || !player.is_alive {
        return;
    }
    let entity_id = player.entity_id;
    if !limiter.allow(peer, now_ms) {
        debug!("hit report rate-limited for peer {peer}");
        return;
    }
    let Some(proj) = projectiles.get(projectile_id) else {
        return; // idempotent: a removed bullet (e.g. already backstopped) can't re-apply
    };
    if !proj.alive {
        return;
    }
    if !hit::is_client_authoritative(proj.owner_id) {
        return; // invariant #2: no PvP via client report
    }
    let flight_start = hit::flight_origin(proj.position, proj.direction, proj.distance_traveled);
    let recent = players.get_recent_positions(entity_id);
    if !hit::is_hit_plausible(
        flight_start,
        proj.position,
        &recent,
        LOCAL_HIT_PLAUSIBILITY_THRESHOLD,
    ) {
        debug!("implausible hit report: peer {peer} projectile {projectile_id}");
        return;
    }
    let owner_id = proj.owner_id;
    let impact = HitImpact::from_projectile(proj);
    apply_player_hit(
        owner_id,
        entity_id,
        players,
        leaderboard,
        outbox,
        Some(impact),
    );
    projectiles.remove_projectile(projectile_id, "player_hit");
    backstop.clear_projectile(projectile_id);
}

/// D11 lenient backstop — NEW code (off in GDScript, ON in the port). Catches egregious
/// never-reporters: if a monster bullet's authoritative swept path blatantly overlaps a player
/// (within the TRUE 24 u hit window — no looser) and no LOCAL_HIT_REPORT despawns the bullet
/// within the grace period, the server applies the hit through the same shared path.
/// It must stay blatant-overlap-only; a tight backstop would reintroduce the phantom-hit feel
/// the client-authoritative path exists to prevent (hit-authority-model invariant #4).
#[derive(Default)]
pub struct Backstop {
    /// (projectile_id, victim_entity_id) → tick of first blatant overlap.
    overlaps: HashMap<(u16, u16), u64>,
}

impl Backstop {
    pub fn clear_projectile(&mut self, projectile_id: u16) {
        self.overlaps.retain(|(pid, _), _| *pid != projectile_id);
    }

    /// Drop entries whose projectile died. Must ALSO run right after projectile integration
    /// (before monster AI fires): an id freed mid-tick can be recycled by a same-tick spawn,
    /// and a recycled id must not inherit the dead bullet's pending overlap.
    pub fn purge_dead(&mut self, projectiles: &ProjectileManager) {
        self.overlaps
            .retain(|(pid, _), _| projectiles.get(*pid).map(|p| p.alive).unwrap_or(false));
    }

    /// Run each tick AFTER projectile integration and BEFORE the snapshot broadcast.
    pub fn update(
        &mut self,
        grace_ticks: u64,
        tick: u64,
        players: &mut PlayerManager,
        projectiles: &mut ProjectileManager,
        leaderboard: &mut Leaderboard,
        outbox: &mut Outbox,
    ) {
        // Record first blatant overlaps for live monster-owned projectiles.
        for proj in &projectiles.projectiles {
            if !proj.alive || !hit::is_client_authoritative(proj.owner_id) {
                continue;
            }
            for player in players
                .players
                .iter()
                .filter(|p| p.authenticated && p.is_alive)
            {
                // Records on the TRUE 24 u window only (HIT_BACKSTOP_OVERLAP_UNITS), tying the
                // "blatant overlap only" D11 invariant to the shared sim_core constant.
                if hit::is_backstop_overlap(player.position, proj.previous_position, proj.position)
                {
                    self.overlaps
                        .entry((proj.entity_id, player.entity_id))
                        .or_insert(tick);
                }
            }
        }

        // Apply expired overlaps. A despawned projectile (validated report / wall / range) or a
        // dead victim cancels the pending entry. Sorted so simultaneous expiries apply in a
        // deterministic order (HashMap iteration is not).
        let mut expired: Vec<(u16, u16)> = self
            .overlaps
            .iter()
            .filter(|(_, &t)| hit::backstop_grace_elapsed(t, tick, grace_ticks))
            .map(|(&k, _)| k)
            .collect();
        expired.sort_unstable();
        for (projectile_id, victim_id) in expired {
            self.overlaps.remove(&(projectile_id, victim_id));
            let Some(proj) = projectiles.get(projectile_id) else {
                continue;
            };
            // Re-check authority: guards against an id recycled into a player-owned bullet.
            if !proj.alive || !hit::is_client_authoritative(proj.owner_id) {
                continue;
            }
            let victim_alive = players
                .get_by_entity_id(victim_id)
                .map(|p| p.is_alive)
                .unwrap_or(false);
            if !victim_alive {
                continue;
            }
            let owner_id = proj.owner_id;
            let impact = HitImpact::from_projectile(proj);
            debug!("backstop applying hit: projectile {projectile_id} → player {victim_id}");
            metrics::counter!("backstop_hits_total").increment(1);
            apply_player_hit(
                owner_id,
                victim_id,
                players,
                leaderboard,
                outbox,
                Some(impact),
            );
            projectiles.remove_projectile(projectile_id, "player_hit");
            self.clear_projectile(projectile_id);
        }

        // Drop bookkeeping for projectiles that no longer exist.
        self.overlaps
            .retain(|(pid, _), _| projectiles.get(*pid).map(|p| p.alive).unwrap_or(false));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// sim_core debug_asserts that each thread set its world geometry before any bounds/obstacle
    /// read (arena.rs "set once, single thread" contract). Each libtest test runs on its own thread,
    /// so every test must apply the Arena geometry first.
    fn init_arena_geometry() {
        sim_core::set_world_geometry(
            sim_core::constants::MAP_MIN,
            sim_core::constants::MAP_MAX,
            true,
        );
    }

    fn setup() -> (PlayerManager, ProjectileManager, Leaderboard, Outbox) {
        init_arena_geometry();
        let mut players = PlayerManager::new();
        let p = players.add_player(1).unwrap();
        p.authenticated = true;
        (
            players,
            ProjectileManager::new(),
            Leaderboard::new(),
            Outbox::new(),
        )
    }

    fn spawn_monster_bullet_at(projectiles: &mut ProjectileManager, pos: Vec2) -> u16 {
        projectiles
            .spawn_projectile(
                30001,
                pos,
                Vec2::new(1.0, 0.0),
                0,
                0,
                0,
                300.0,
                MONSTER_PROJECTILE_KNOCKBACK_FORCE,
            )
            .unwrap()
            .entity_id
    }

    #[test]
    fn report_applies_to_reporter_only_and_despawns() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let player_pos = players.players[0].position;
        let pid = spawn_monster_bullet_at(&mut projectiles, player_pos - Vec2::new(5.0, 0.0));
        players.record_position_snapshot(1);
        let mut limiter = HitReportLimiter::default();
        let mut backstop = Backstop::default();
        handle_local_hit_report(
            1,
            pid,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut limiter,
            &mut backstop,
            &mut outbox,
            0,
        );
        assert_eq!(players.players[0].health, 100 - MONSTER_PROJECTILE_DAMAGE);
        assert!(projectiles.get(pid).is_none(), "bullet must despawn");
        // A DAMAGE event was broadcast.
        assert!(outbox.messages.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::DAMAGE
        )));
    }

    #[test]
    fn report_rejects_player_owned_projectiles() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let player_pos = players.players[0].position;
        let pid = projectiles
            .spawn_projectile(
                2,
                player_pos,
                Vec2::new(1.0, 0.0),
                0,
                0,
                0,
                400.0,
                PLAYER_PROJECTILE_KNOCKBACK_FORCE,
            )
            .unwrap()
            .entity_id;
        players.record_position_snapshot(1);
        let mut limiter = HitReportLimiter::default();
        let mut backstop = Backstop::default();
        handle_local_hit_report(
            1,
            pid,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut limiter,
            &mut backstop,
            &mut outbox,
            0,
        );
        assert_eq!(
            players.players[0].health, 100,
            "no PvP via client report (invariant #2)"
        );
        assert!(
            projectiles.get(pid).is_some(),
            "player-owned bullet must survive"
        );
    }

    #[test]
    fn report_rejects_implausible_flight() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        // Bullet flying far away from any recent player position (>88 u off-path).
        let far = players.players[0].position + Vec2::new(0.0, 300.0);
        let pid = spawn_monster_bullet_at(&mut projectiles, far);
        players.record_position_snapshot(1);
        let mut limiter = HitReportLimiter::default();
        let mut backstop = Backstop::default();
        handle_local_hit_report(
            1,
            pid,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut limiter,
            &mut backstop,
            &mut outbox,
            0,
        );
        assert_eq!(players.players[0].health, 100);
        assert!(projectiles.get(pid).is_some());
    }

    #[test]
    fn rate_limiter_allows_20_per_window() {
        let mut limiter = HitReportLimiter::default();
        for i in 0..20 {
            assert!(limiter.allow(1, 100), "report {i} should pass");
        }
        assert!(!limiter.allow(1, 100), "21st must fail");
        assert!(limiter.allow(1, 1200), "window reset after 1 s");
    }

    #[test]
    fn backstop_applies_after_grace_when_unreported() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let player_pos = players.players[0].position;
        // Bullet passes straight through the player this tick.
        let pid = spawn_monster_bullet_at(&mut projectiles, player_pos - Vec2::new(12.0, 0.0));
        // Manually set up the swept segment crossing the player.
        if let Some(p) = projectiles
            .projectiles
            .iter_mut()
            .find(|p| p.entity_id == pid)
        {
            p.previous_position = player_pos - Vec2::new(12.0, 0.0);
            p.position = player_pos + Vec2::new(12.0, 0.0);
        }
        let mut backstop = Backstop::default();
        backstop.update(
            20,
            100,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );
        assert_eq!(players.players[0].health, 100, "no hit during grace");
        // 20 ticks later, still unreported (keep segment overlapping is not required —
        // the recorded overlap is what counts).
        backstop.update(
            20,
            120,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );
        assert_eq!(players.players[0].health, 100 - MONSTER_PROJECTILE_DAMAGE);
        assert!(
            projectiles.get(pid).is_none(),
            "backstopped bullet despawns"
        );
    }

    #[test]
    fn backstop_entry_dies_with_projectile_before_id_recycling() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let player_pos = players.players[0].position;
        let pid = spawn_monster_bullet_at(&mut projectiles, player_pos - Vec2::new(12.0, 0.0));
        if let Some(p) = projectiles
            .projectiles
            .iter_mut()
            .find(|p| p.entity_id == pid)
        {
            p.previous_position = player_pos - Vec2::new(12.0, 0.0);
            p.position = player_pos + Vec2::new(12.0, 0.0);
        }
        let mut backstop = Backstop::default();
        backstop.update(
            20,
            100,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );

        // The bullet dies mid-tick (wall/range) — purge_dead runs before any same-tick spawn
        // can recycle the id (the world loop's ordering guarantee).
        projectiles.remove_projectile(pid, "test");
        backstop.purge_dead(&projectiles);

        // A NEW bullet recycles the id far from the player; the old overlap must not fire.
        let recycled = loop {
            let id =
                spawn_monster_bullet_at(&mut projectiles, player_pos + Vec2::new(400.0, 400.0));
            if id == pid {
                break id;
            }
            projectiles.remove_projectile(id, "test");
        };
        backstop.update(
            20,
            130,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );
        assert_eq!(
            players.players[0].health, 100,
            "recycled id must not inherit the dead bullet's overlap"
        );
        assert!(projectiles.get(recycled).is_some(), "new bullet untouched");
    }

    #[test]
    fn backstop_yields_to_validated_report() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let player_pos = players.players[0].position;
        let pid = spawn_monster_bullet_at(&mut projectiles, player_pos - Vec2::new(5.0, 0.0));
        if let Some(p) = projectiles
            .projectiles
            .iter_mut()
            .find(|p| p.entity_id == pid)
        {
            p.previous_position = player_pos - Vec2::new(12.0, 0.0);
            p.position = player_pos + Vec2::new(12.0, 0.0);
        }
        players.record_position_snapshot(1);
        let mut backstop = Backstop::default();
        let mut limiter = HitReportLimiter::default();
        backstop.update(
            20,
            100,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );
        // The report arrives within the grace window.
        handle_local_hit_report(
            1,
            pid,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut limiter,
            &mut backstop,
            &mut outbox,
            0,
        );
        let hp_after_report = players.players[0].health;
        assert_eq!(hp_after_report, 100 - MONSTER_PROJECTILE_DAMAGE);
        // Grace expiry must NOT double-apply (projectile gone, bookkeeping cleared).
        backstop.update(
            20,
            200,
            &mut players,
            &mut projectiles,
            &mut lb,
            &mut outbox,
        );
        assert_eq!(players.players[0].health, hp_after_report);
    }

    #[test]
    fn knockback_follows_projectile_travel_direction() {
        let (mut players, _projectiles, mut lb, mut outbox) = setup();
        let target_pos = players.players[0].position;
        // Projectile travelling +X whose impact point ended up PAST the target's center —
        // away-from-impact would push backwards; travel direction must win.
        apply_player_hit(
            30001,
            1,
            &mut players,
            &mut lb,
            &mut outbox,
            Some(HitImpact {
                position: target_pos + Vec2::new(5.0, 0.0),
                direction: Vec2::new(1.0, 0.0),
                knockback_force: PLAYER_KNOCKBACK_BASE_FORCE,
            }),
        );
        let sm = &players.players[0].movement_sm;
        assert_eq!(sm.state(), MoveState::KnockedBack);
        // First knockback tick must move in +X.
        let v = players.players[0].movement_sm.tick(
            1.0 / 30.0,
            Vec2::ZERO,
            false,
            false,
            false,
            false,
            Vec2::new(1.0, 0.0),
        );
        assert!(v.x > 0.0, "knockback must push along travel dir, got {v:?}");
        assert!(v.y.abs() < 1e-3);
    }

    #[test]
    fn hit_while_sprinting_dazes_walking_does_not() {
        let (mut players, _projectiles, mut lb, mut outbox) = setup();
        let dt = 1.0 / 30.0;
        let right = Vec2::new(1.0, 0.0);
        // Enter SPRINTING.
        players.players[0]
            .movement_sm
            .tick(dt, right, true, false, false, false, right);
        assert_eq!(players.players[0].movement_sm.state(), MoveState::Sprinting);
        apply_player_hit(30001, 1, &mut players, &mut lb, &mut outbox, None);
        assert!(
            players.players[0].movement_sm.is_dazed(),
            "sprinting target must be dazed on hit"
        );

        // Second player, WALKING: no daze.
        let p2 = players.add_player(2).unwrap();
        p2.authenticated = true;
        p2.movement_sm
            .tick(dt, right, false, false, false, false, right);
        assert_eq!(p2.movement_sm.state(), MoveState::Walking);
        let p2_id = p2.entity_id;
        apply_player_hit(30001, p2_id, &mut players, &mut lb, &mut outbox, None);
        assert!(
            !players.players[1].movement_sm.is_dazed(),
            "walking target must NOT be dazed"
        );
    }

    #[test]
    fn ability_effect_dazes_walking_target_with_explicit_damage() {
        // The Mageblast path: explicit ability damage + an unconditional Daze effect, on a target
        // that is NOT sprinting (so the sprint-hit daze does not fire — only the effect does).
        let (mut players, _projectiles, mut lb, mut outbox) = setup();
        let id = players.players[0].entity_id;
        let before = players.players[0].health;
        assert_ne!(
            players.players[0].movement_sm.state(),
            MoveState::Sprinting,
            "target must be walking for this test"
        );
        apply_player_damage(
            2, // a player-owned source (no kill here, so owner lookup is irrelevant)
            id,
            55, // explicit ability damage, not the flat projectile constant
            &[StatusEffect::Daze {
                secs: PLAYER_DAZE_DURATION,
            }],
            &mut players,
            &mut lb,
            &mut outbox,
            None, // AoE: no knockback impact
        );
        assert_eq!(
            players.players[0].health,
            before - 55,
            "explicit ability damage is applied (not the flat constant)"
        );
        assert!(
            players.players[0].movement_sm.is_dazed(),
            "the Daze effect fires on a walking target"
        );
    }

    #[test]
    fn invulnerable_target_takes_no_damage_no_event() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        players.players[0].life_state = crate::player::LifeState::Invulnerable;
        let _ = &mut projectiles;
        apply_player_hit(
            30001,
            players.players[0].entity_id,
            &mut players,
            &mut lb,
            &mut outbox,
            None,
        );
        assert_eq!(players.players[0].health, 100);
        assert!(
            outbox.messages.is_empty(),
            "zero applied damage ⇒ no event at all"
        );
    }

    #[test]
    fn pvp_disabled_skips_player_hits() {
        init_arena_geometry();
        let mut players = PlayerManager::new();
        players.add_player(1).unwrap().authenticated = true;
        players.add_player(2).unwrap().authenticated = true;
        let mut projectiles = ProjectileManager::new();
        let mut monsters = MonsterManager::new();
        let mut lb = Leaderboard::new();
        let mut outbox = Outbox::new();
        let shooter = players.players[0].entity_id;
        let victim_pos = players.players[1].position;
        players.record_position_snapshot(1);
        // A shooter-owned projectile travelling straight through the victim.
        projectiles
            .spawn_projectile(
                shooter,
                victim_pos - Vec2::new(20.0, 0.0),
                Vec2::new(1.0, 0.0),
                1,
                0,
                0,
                400.0,
                PLAYER_PROJECTILE_KNOCKBACK_FORCE,
            )
            .unwrap();
        projectiles.update_all(1.0 / 30.0);
        let max_hp = players.players[1].max_health;
        // PvP OFF (Sanctuary): the player pass is skipped — no damage, no DAMAGE event.
        let killed = process_collisions(
            &mut projectiles,
            &mut players,
            &mut monsters,
            &mut lb,
            &mut outbox,
            false,
        );
        assert!(killed.is_empty());
        assert_eq!(
            players.players[1].health, max_hp,
            "no PvP damage when pvp_enabled is false"
        );
        assert!(
            !outbox.messages.iter().any(|(_, p)| matches!(
                p,
                ServerPacket::GameEvent(e) if e.event_type == game_event_type::DAMAGE
            )),
            "no DAMAGE event in the safe Sanctuary"
        );
    }

    #[test]
    fn pvp_kill_grants_shared_xp_by_victim_level() {
        let (mut players, _projectiles, mut lb, mut outbox) = setup(); // adds authed peer 1
        for peer in [2usize, 3, 4] {
            players.add_player(peer).unwrap().authenticated = true;
        }
        // Killer (1) + near bystander (3) co-located with the victim (2); far bystander (4) well
        // outside XP_SHARE_RADIUS.
        for p in players.players.iter_mut() {
            p.position = Vec2::ZERO;
        }
        let far_id = players.get(4).unwrap().entity_id;
        players.get_by_entity_id_mut(far_id).unwrap().position = Vec2::new(5000.0, 0.0);

        let killer_id = players.get(1).unwrap().entity_id;
        let victim_id = players.get(2).unwrap().entity_id;
        // Victim is level 3 → worth 132 XP (monster table); low HP so the hit kills.
        {
            let v = players.get_mut(2).unwrap();
            v.apply_class_and_level(v.player_class, 3, 0);
            v.health = 10;
        }

        apply_player_hit(
            killer_id,
            victim_id,
            &mut players,
            &mut lb,
            &mut outbox,
            None,
        );

        assert!(!players.get(2).unwrap().is_alive, "victim died");
        assert_eq!(players.get(2).unwrap().level, 3, "victim level unchanged");
        // 132 XP at level 1 → level 2 with 32 progress (100 to reach level 2).
        let killer = players.get(1).unwrap();
        assert_eq!(
            (killer.level, killer.experience),
            (2, 32),
            "killer got full XP"
        );
        // Killer's level-up fully restores HP.
        assert_eq!(killer.health, killer.max_health, "level-up refills HP");
        let near = players.get(3).unwrap();
        assert_eq!(
            (near.level, near.experience),
            (2, 32),
            "co-contributor got full XP"
        );
        let far = players.get(4).unwrap();
        assert_eq!(
            (far.level, far.experience),
            (1, 0),
            "out-of-range player got no XP"
        );
    }

    #[test]
    fn kill_increments_deaths_and_broadcasts() {
        let (mut players, mut projectiles, mut lb, mut outbox) = setup();
        let _ = &mut projectiles;
        players.players[0].health = 10;
        apply_player_hit(
            30001,
            players.players[0].entity_id,
            &mut players,
            &mut lb,
            &mut outbox,
            None,
        );
        assert!(!players.players[0].is_alive);
        assert_eq!(players.players[0].deaths, 1);
        assert_eq!(players.players[0].respawn_timer, RESPAWN_DELAY);
        assert!(outbox.messages.iter().any(|(_, p)| matches!(
            p,
            ServerPacket::GameEvent(e) if e.event_type == game_event_type::KILL
        )));
    }
}
