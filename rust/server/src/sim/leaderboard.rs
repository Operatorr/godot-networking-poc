//! In-memory PvP leaderboard — port of `leaderboard_manager.gd` (extraction lifecycle §4.10).
//! POC-only: kills are forgotten on disconnect; persistence belongs to the Go API (ADR 0005).

#[derive(Debug, Clone)]
struct Entry {
    entity_id: u16,
    pvp_kills: u16,
    /// Serialized alongside kills since protocol v7 so the HUD can show a Kills:Deaths ratio.
    deaths: u16,
}

#[derive(Default)]
pub struct Leaderboard {
    entries: Vec<Entry>,
    /// Set by `record_pvp_kill`; lets the tick loop coalesce many kills in one tick (e.g. an AoE
    /// wiping several players) into a single end-of-tick broadcast instead of one snapshot per kill.
    dirty: bool,
}

impl Leaderboard {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register_player(&mut self, entity_id: u16) {
        if entity_id == 0 {
            return;
        }
        if !self.entries.iter().any(|e| e.entity_id == entity_id) {
            self.entries.push(Entry {
                entity_id,
                pvp_kills: 0,
                deaths: 0,
            });
        }
    }

    pub fn remove_player(&mut self, entity_id: u16) {
        self.entries.retain(|e| e.entity_id != entity_id);
    }

    pub fn record_pvp_kill(&mut self, killer_id: u16, victim_id: u16) {
        if killer_id == 0 || victim_id == 0 || killer_id == victim_id {
            return;
        }
        self.find_or_create(killer_id).pvp_kills += 1;
        self.find_or_create(victim_id).deaths += 1;
        self.dirty = true;
    }

    /// Returns whether the board changed since the last call and clears the flag — the tick loop
    /// uses this to emit at most one leaderboard broadcast per tick regardless of how many kills
    /// landed (an AoE multi-kill marks dirty once per victim but broadcasts only once).
    pub fn take_dirty(&mut self) -> bool {
        let was = self.dirty;
        self.dirty = false;
        was
    }

    fn find_or_create(&mut self, entity_id: u16) -> &mut Entry {
        if let Some(idx) = self.entries.iter().position(|e| e.entity_id == entity_id) {
            return &mut self.entries[idx];
        }
        self.entries.push(Entry {
            entity_id,
            pvp_kills: 0,
            deaths: 0,
        });
        self.entries.last_mut().unwrap()
    }

    /// Kills DESC, entity_id ASC tiebreak — a strict total order. Returns
    /// `(entity_id, pvp_kills, deaths)`; ranking is by kills, deaths ride along for the HUD's K:D.
    pub fn top_n(&self, count: usize) -> Vec<(u16, u16, u16)> {
        let mut sorted: Vec<&Entry> = self.entries.iter().collect();
        sorted.sort_by(|a, b| {
            b.pvp_kills
                .cmp(&a.pvp_kills)
                .then(a.entity_id.cmp(&b.entity_id))
        });
        sorted
            .into_iter()
            .take(count)
            .map(|e| (e.entity_id, e.pvp_kills, e.deaths))
            .collect()
    }

    /// Shutdown path.
    #[allow(dead_code)]
    pub fn clear(&mut self) {
        self.entries.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordering_and_truncation() {
        let mut lb = Leaderboard::new();
        for id in 1..=12 {
            lb.register_player(id);
        }
        lb.record_pvp_kill(5, 1);
        lb.record_pvp_kill(5, 2);
        lb.record_pvp_kill(3, 5);
        let top = lb.top_n(10);
        assert_eq!(top.len(), 10);
        assert_eq!(top[0], (5, 2, 1)); // 2 kills, died once (to player 3)
        assert_eq!(top[1], (3, 1, 0));
        assert_eq!(top[2], (1, 0, 1)); // ties broken by entity_id ascending; player 1 died once
    }

    #[test]
    fn disconnect_forgets_kills() {
        let mut lb = Leaderboard::new();
        lb.register_player(1);
        lb.record_pvp_kill(1, 2);
        lb.remove_player(1);
        assert!(lb.top_n(10).iter().all(|(id, _, _)| *id != 1));
    }

    #[test]
    fn suicide_ignored() {
        let mut lb = Leaderboard::new();
        lb.register_player(1);
        lb.record_pvp_kill(1, 1);
        assert_eq!(lb.top_n(1)[0], (1, 0, 0));
    }
}
