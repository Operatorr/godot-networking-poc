//! Server metrics — the SERVER_METRICS packet source data (extraction server-tick §4.10–4.11)
//! plus Prometheus gauges (D13). One monotonic clock; tick-time fields saturate instead of
//! wrapping (deliberate fix of the u16-wrap hazard H12).

use protocol::ServerMetrics;
use std::collections::VecDeque;

const METRICS_SAMPLE_SIZE: usize = 30;

#[derive(Default)]
pub struct MetricsCollector {
    tick_times_ms: VecDeque<f64>,
    pub total_bytes_sent: u64,
    pub total_bytes_received: u64,
    pub bytes_sent_per_peer: std::collections::HashMap<usize, u64>,
    prev_total_peer_bytes: u64,
    prev_metrics_ms: u64,
    pub last_metrics_ms: u64,
}

impl MetricsCollector {
    pub fn record_tick_time(&mut self, ms: f64) {
        self.tick_times_ms.push_back(ms);
        if self.tick_times_ms.len() > METRICS_SAMPLE_SIZE {
            self.tick_times_ms.pop_front();
        }
        metrics::histogram!("tick_duration_ms").record(ms);
    }

    pub fn record_sent(&mut self, peer: usize, bytes: usize) {
        self.total_bytes_sent += bytes as u64;
        *self.bytes_sent_per_peer.entry(peer).or_insert(0) += bytes as u64;
    }

    pub fn record_received(&mut self, bytes: usize) {
        self.total_bytes_received += bytes as u64;
    }

    pub fn remove_peer(&mut self, peer: usize) {
        self.bytes_sent_per_peer.remove(&peer);
    }

    /// 1 Hz packet build. `entity_count` excludes players (parity with the GDScript).
    pub fn build_packet(
        &mut self,
        tick_count: u64,
        player_count: usize,
        entity_count: usize,
        diag: &crate::broadcast::TickDiagnostics,
        now_ms: u64,
    ) -> ServerMetrics {
        // saturating_sub: the very first call has prev_metrics_ms == 0, and a non-monotonic clock
        // read would otherwise underflow into a huge bogus elapsed.
        let elapsed_s = now_ms.saturating_sub(self.prev_metrics_ms) as f64 / 1000.0;
        let peer_count = self.bytes_sent_per_peer.len();
        let avg_bandwidth = if peer_count > 0 && elapsed_s > 0.0 {
            let total: u64 = self.bytes_sent_per_peer.values().sum();
            let delta = total.saturating_sub(self.prev_total_peer_bytes);
            self.prev_total_peer_bytes = total;
            delta as f64 / elapsed_s / peer_count as f64
        } else {
            self.prev_total_peer_bytes = 0;
            0.0
        };
        let (avg_ms, max_ms) = if self.tick_times_ms.is_empty() {
            (0.0, 0.0)
        } else {
            let sum: f64 = self.tick_times_ms.iter().sum();
            let max = self.tick_times_ms.iter().cloned().fold(0.0, f64::max);
            (sum / self.tick_times_ms.len() as f64, max)
        };
        self.prev_metrics_ms = now_ms;
        self.last_metrics_ms = now_ms;

        metrics::gauge!("players_online").set(player_count as f64);
        metrics::gauge!("entities").set(entity_count as f64);
        metrics::gauge!("avg_tick_time_ms").set(avg_ms);
        metrics::gauge!("avg_bandwidth_per_client_bytes").set(avg_bandwidth);
        metrics::gauge!("snapshot_entities_deferred").set(diag.entities_deferred_per_tick as f64);

        ServerMetrics {
            tick_count: tick_count as u32,
            avg_tick_time_ms_x100: sat_x100(avg_ms),
            max_tick_time_ms_x100: sat_x100(max_ms),
            player_count: player_count.min(65535) as u16,
            entity_count: entity_count.min(65535) as u16,
            total_bytes_sent: self.total_bytes_sent as u32,
            total_bytes_received: self.total_bytes_received as u32,
            avg_bandwidth_per_client: avg_bandwidth.trunc() as u32,
            sched_entities_deferred: diag.entities_deferred_per_tick.min(65535) as u16,
            sched_max_queue_age_ticks: diag.max_queue_age_ticks.min(65535) as u16,
            sched_peers_at_budget_pct: diag.peers_at_budget_pct,
            sched_peers_evaluated: diag.peers_evaluated.min(65535) as u16,
            sched_snapshot_overflow: diag.snapshot_count_overflow.min(65535) as u16,
        }
    }
}

fn sat_x100(ms: f64) -> u16 {
    (ms * 100.0).trunc().clamp(0.0, 65535.0) as u16
}
