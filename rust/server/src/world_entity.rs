//! Server-authoritative ability/loot world entities (protocol kind 3): spinning bibles, mines,
//! DOT zones, and healthorbs. They live in the world tick, apply effects via the shared damage /
//! heal paths, and replicate in snapshots through the world-effect id band (40000–49999,
//! partitioned by subtype). `update_all` is pure-ish: it mutates entity position/lifetime/state
//! and RETURNS the damage/heal/VFX events for `world.rs` to apply (keeping borrows simple).

use protocol::types::{world_effect, WORLD_EFFECT_ID_END};
use sim_core::Vec2;
use std::collections::HashMap;

/// Per-monster rehit cooldown (s) is keyed in the Bible kind.
#[derive(Debug, Clone)]
pub enum WorldEntityKind {
    /// Heals a player +`amount` HP on walk-over, then despawns.
    Healthorb { amount: i32 },
    /// Arms after `arm_left`, detonates when a monster enters `trigger_radius`, dealing `damage`
    /// in `blast_radius`. Expires after its lifetime if never triggered.
    Mine {
        owner_id: u16,
        trigger_radius: f32,
        blast_radius: f32,
        damage: i32,
        arm_left: f64,
    },
    /// Damages monsters inside `radius` for `dps` (applied as integer ticks via an accumulator).
    DotZone {
        owner_id: u16,
        radius: f32,
        dps: i32,
        damage_accum: f64,
    },
    /// Orbits its owner; sweep-damages monsters it overlaps with a per-monster rehit cooldown.
    Bible {
        owner_id: u16,
        radius: f32, // hit radius of the orb itself
        orbit_radius: f32,
        damage: i32,
        phase: f64,
        angular_speed: f64,
        rehit_interval: f64,
        rehit: HashMap<u16, f64>,
    },
}

#[derive(Debug, Clone)]
pub struct WorldEntity {
    pub entity_id: u16,
    pub position: Vec2,
    pub kind: WorldEntityKind,
    pub lifetime_left: f64,
    pub alive: bool,
}

/// Damage to apply to a monster (funnelled through `combat::apply_monster_damage`).
#[derive(Debug, Clone, Copy)]
pub struct MonsterDamage {
    pub monster_id: u16,
    pub amount: i32,
    pub owner_id: u16,
}

/// Healthorb pickup → heal a player.
#[derive(Debug, Clone, Copy)]
pub struct PlayerHeal {
    pub player_id: u16,
    pub amount: i32,
    pub orb_id: u16,
}

/// A transient VFX to broadcast (mine detonation, etc.).
#[derive(Debug, Clone, Copy)]
pub struct EffectEvent {
    pub effect_id: u8,
    pub position: Vec2,
    pub radius: u16,
}

#[derive(Debug, Default)]
pub struct WorldEntityOutcome {
    pub monster_damage: Vec<MonsterDamage>,
    pub player_heals: Vec<PlayerHeal>,
    pub effects: Vec<EffectEvent>,
}

/// Hitbox radii for proximity tests (reuse the shared player/monster radii feel).
const MONSTER_HIT_RADIUS: f32 = 16.0;
const PLAYER_PICKUP_RADIUS: f32 = 20.0;
/// Healthorbs linger this long before vanishing if no one grabs them.
pub const HEALTHORB_LIFETIME: f64 = 20.0;

pub struct WorldEntityManager {
    pub entities: Vec<WorldEntity>,
    /// Per-subtype id cursor (round-robin within each 2500-id sub-band).
    cursors: [u16; 4],
}

impl Default for WorldEntityManager {
    fn default() -> Self {
        Self::new()
    }
}

impl WorldEntityManager {
    pub fn new() -> Self {
        Self {
            entities: Vec::new(),
            cursors: [
                world_effect::band_start(world_effect::HEALTHORB),
                world_effect::band_start(world_effect::MINE),
                world_effect::band_start(world_effect::DOT_ZONE),
                world_effect::band_start(world_effect::BIBLE),
            ],
        }
    }

    pub fn count(&self) -> usize {
        self.entities.len()
    }

    /// Allocate the next free id in `subtype`'s sub-band (skip-if-live, wraps within the band).
    fn allocate_id(&mut self, subtype: u8) -> Option<u16> {
        let band_start = world_effect::band_start(subtype);
        let band_end = (band_start + world_effect::STRIDE - 1).min(WORLD_EFFECT_ID_END);
        let span = (band_end - band_start + 1) as usize;
        let cursor = &mut self.cursors[subtype as usize];
        for _ in 0..span {
            let candidate = *cursor;
            *cursor += 1;
            if *cursor > band_end {
                *cursor = band_start;
            }
            if !self.entities.iter().any(|e| e.entity_id == candidate) {
                return Some(candidate);
            }
        }
        None
    }

    fn spawn(&mut self, subtype: u8, position: Vec2, kind: WorldEntityKind, lifetime: f64) -> u16 {
        let Some(entity_id) = self.allocate_id(subtype) else {
            return 0;
        };
        self.entities.push(WorldEntity {
            entity_id,
            position,
            kind,
            lifetime_left: lifetime,
            alive: true,
        });
        entity_id
    }

    pub fn spawn_healthorb(&mut self, position: Vec2, amount: i32) -> u16 {
        self.spawn(
            world_effect::HEALTHORB,
            position,
            WorldEntityKind::Healthorb { amount },
            HEALTHORB_LIFETIME,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn spawn_mine(
        &mut self,
        position: Vec2,
        owner_id: u16,
        trigger_radius: f32,
        blast_radius: f32,
        damage: i32,
        arm_delay: f64,
        lifetime: f64,
    ) -> u16 {
        self.spawn(
            world_effect::MINE,
            position,
            WorldEntityKind::Mine {
                owner_id,
                trigger_radius,
                blast_radius,
                damage,
                arm_left: arm_delay,
            },
            lifetime,
        )
    }

    pub fn spawn_dot_zone(
        &mut self,
        position: Vec2,
        owner_id: u16,
        radius: f32,
        dps: i32,
        duration: f64,
    ) -> u16 {
        self.spawn(
            world_effect::DOT_ZONE,
            position,
            WorldEntityKind::DotZone {
                owner_id,
                radius,
                dps,
                damage_accum: 0.0,
            },
            duration,
        )
    }

    /// Spawn `count` bibles evenly phased around the owner.
    #[allow(clippy::too_many_arguments)]
    pub fn spawn_bibles(
        &mut self,
        owner_id: u16,
        owner_pos: Vec2,
        count: u32,
        orbit_radius: f32,
        damage: i32,
        angular_speed: f64,
        duration: f64,
        rehit_interval: f64,
    ) {
        for i in 0..count {
            let phase = std::f64::consts::TAU * i as f64 / count.max(1) as f64;
            let pos = owner_pos
                + Vec2::new(
                    (orbit_radius as f64 * phase.cos()) as f32,
                    (orbit_radius as f64 * phase.sin()) as f32,
                );
            self.spawn(
                world_effect::BIBLE,
                pos,
                WorldEntityKind::Bible {
                    owner_id,
                    radius: 12.0,
                    orbit_radius,
                    damage,
                    phase,
                    angular_speed,
                    rehit_interval,
                    rehit: HashMap::new(),
                },
                duration,
            );
        }
    }

    /// Advance all world entities one tick. `player_pos(id)` / monster roster are read-only
    /// lookups; returns the effects to apply. Lifetime expiry + triggers despawn here.
    pub fn update_all(
        &mut self,
        delta: f64,
        players: &[(u16, Vec2, bool)],
        monsters: &[(u16, Vec2, bool)],
    ) -> WorldEntityOutcome {
        let mut out = WorldEntityOutcome::default();
        for ent in &mut self.entities {
            if !ent.alive {
                continue;
            }
            ent.lifetime_left -= delta;
            if ent.lifetime_left <= 0.0 {
                ent.alive = false;
                continue;
            }
            match &mut ent.kind {
                WorldEntityKind::Healthorb { amount } => {
                    for (pid, ppos, alive) in players {
                        if *alive && ppos.distance_to(ent.position) < PLAYER_PICKUP_RADIUS {
                            out.player_heals.push(PlayerHeal {
                                player_id: *pid,
                                amount: *amount,
                                orb_id: ent.entity_id,
                            });
                            ent.alive = false;
                            break;
                        }
                    }
                }
                WorldEntityKind::Mine {
                    owner_id,
                    trigger_radius,
                    blast_radius,
                    damage,
                    arm_left,
                } => {
                    if *arm_left > 0.0 {
                        *arm_left = (*arm_left - delta).max(0.0);
                        continue;
                    }
                    let triggered = monsters.iter().any(|(_, mpos, alive)| {
                        *alive && mpos.distance_to(ent.position) < *trigger_radius
                    });
                    if triggered {
                        for (mid, mpos, alive) in monsters {
                            if *alive && mpos.distance_to(ent.position) < *blast_radius {
                                out.monster_damage.push(MonsterDamage {
                                    monster_id: *mid,
                                    amount: *damage,
                                    owner_id: *owner_id,
                                });
                            }
                        }
                        out.effects.push(EffectEvent {
                            effect_id: crate::ability::effect::MINE_DETONATION,
                            position: ent.position,
                            radius: *blast_radius as u16,
                        });
                        ent.alive = false;
                    }
                }
                WorldEntityKind::DotZone {
                    owner_id,
                    radius,
                    dps,
                    damage_accum,
                } => {
                    *damage_accum += *dps as f64 * delta;
                    let whole = damage_accum.floor();
                    if whole >= 1.0 {
                        *damage_accum -= whole;
                        let amount = whole as i32;
                        for (mid, mpos, alive) in monsters {
                            if *alive && mpos.distance_to(ent.position) < *radius {
                                out.monster_damage.push(MonsterDamage {
                                    monster_id: *mid,
                                    amount,
                                    owner_id: *owner_id,
                                });
                            }
                        }
                    }
                }
                WorldEntityKind::Bible {
                    owner_id,
                    radius,
                    orbit_radius,
                    damage,
                    phase,
                    angular_speed,
                    rehit_interval,
                    rehit,
                } => {
                    // Re-anchor to the owner's current position and advance the orbit.
                    let owner_pos = players
                        .iter()
                        .find(|(id, _, _)| id == owner_id)
                        .map(|(_, p, _)| *p);
                    let Some(owner_pos) = owner_pos else {
                        ent.alive = false; // owner gone → drop the orb
                        continue;
                    };
                    *phase += *angular_speed * delta;
                    ent.position = owner_pos
                        + Vec2::new(
                            (*orbit_radius as f64 * phase.cos()) as f32,
                            (*orbit_radius as f64 * phase.sin()) as f32,
                        );
                    // Tick per-monster rehit cooldowns.
                    for cd in rehit.values_mut() {
                        *cd = (*cd - delta).max(0.0);
                    }
                    rehit.retain(|_, cd| *cd > 0.0);
                    let reach = *radius + MONSTER_HIT_RADIUS;
                    for (mid, mpos, alive) in monsters {
                        if !*alive {
                            continue;
                        }
                        if mpos.distance_to(ent.position) < reach
                            && rehit.get(mid).copied().unwrap_or(0.0) <= 0.0
                        {
                            out.monster_damage.push(MonsterDamage {
                                monster_id: *mid,
                                amount: *damage,
                                owner_id: *owner_id,
                            });
                            rehit.insert(*mid, *rehit_interval);
                        }
                    }
                }
            }
        }
        self.entities.retain(|e| e.alive);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn healthorb_heals_nearby_player_and_despawns() {
        let mut mgr = WorldEntityManager::new();
        let id = mgr.spawn_healthorb(Vec2::new(0.0, 0.0), 5);
        assert!((40000..42500).contains(&id));
        let players = [(1u16, Vec2::new(5.0, 0.0), true)];
        let out = mgr.update_all(1.0 / 30.0, &players, &[]);
        assert_eq!(out.player_heals.len(), 1);
        assert_eq!(out.player_heals[0].amount, 5);
        assert_eq!(mgr.count(), 0, "orb despawns on pickup");
    }

    #[test]
    fn mine_arms_then_detonates_on_monster() {
        let mut mgr = WorldEntityManager::new();
        mgr.spawn_mine(Vec2::ZERO, 1, 60.0, 120.0, 60, 0.0, 30.0);
        let monsters = [(30000u16, Vec2::new(40.0, 0.0), true)];
        let out = mgr.update_all(1.0 / 30.0, &[], &monsters);
        assert_eq!(out.monster_damage.len(), 1);
        assert_eq!(out.monster_damage[0].amount, 60);
        assert_eq!(out.effects.len(), 1);
        assert_eq!(mgr.count(), 0, "mine despawns after detonation");
    }

    #[test]
    fn dot_zone_accumulates_integer_damage() {
        let mut mgr = WorldEntityManager::new();
        mgr.spawn_dot_zone(Vec2::ZERO, 1, 100.0, 12, 5.0);
        let monsters = [(30000u16, Vec2::new(10.0, 0.0), true)];
        // 12 dps over 1 s of ticks ≈ 12 integer points of damage emitted.
        let mut total = 0;
        for _ in 0..30 {
            let out = mgr.update_all(1.0 / 30.0, &[], &monsters);
            total += out.monster_damage.iter().map(|d| d.amount).sum::<i32>();
        }
        assert!((11..=13).contains(&total), "dot total = {total}");
    }

    #[test]
    fn bible_orbits_owner_and_rehits_on_cooldown() {
        let mut mgr = WorldEntityManager::new();
        mgr.spawn_bibles(1, Vec2::ZERO, 3, 80.0, 15, 3.0, 5.0, 0.4);
        assert_eq!(mgr.count(), 3);
        // Place a monster right where a bible orbits.
        let players = [(1u16, Vec2::ZERO, true)];
        let monsters = [(30000u16, Vec2::new(80.0, 0.0), true)];
        let mut hits = 0;
        for _ in 0..60 {
            let out = mgr.update_all(1.0 / 30.0, &players, &monsters);
            hits += out.monster_damage.len();
        }
        assert!(hits >= 1, "a bible should sweep the monster");
    }
}
