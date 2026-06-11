//! Per-bot metrics, swarm aggregation, the POC success criteria, and report rendering — a port
//! of the Python harness's `BotMetrics`/`AggregatedMetrics` with the transport-era measurements
//! swapped for ENet-native ones: latency is the ENet RTT (the HEARTBEAT echo died with the
//! WebSocket protocol — clock sync now rides `Snapshot.server_ms`), and packet loss is ENet's
//! measured mean instead of the old snapshot-tick-gap estimate.

use protocol::ServerMetrics;
use serde_json::{json, Value};

/// Success criteria from the POC epic (unchanged from the Python harness).
pub const SERVER_FPS_MIN: f64 = 30.0;
pub const LATENCY_AVG_MAX_MS: f64 = 100.0;
pub const LATENCY_P95_MAX_MS: f64 = 150.0;
pub const BANDWIDTH_PER_PLAYER_MAX_KBPS: f64 = 5.0;
pub const PACKET_LOSS_MAX_PCT: f64 = 2.0;
pub const CRASH_RATE_MAX_PCT: f64 = 5.0;

#[derive(Debug, Default)]
pub struct BotMetrics {
    pub bot_id: u32,
    pub behavior: &'static str,
    pub latencies_ms: Vec<f64>,
    pub packets_sent: u64,
    pub packets_received: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,
    pub state_updates_received: u64,
    pub baselines_received: u64,
    pub action_confirms_received: u64,
    pub game_events_received: u64,
    pub hit_reports_sent: u64,
    pub respawn_requests_sent: u64,
    pub first_server_tick: Option<u32>,
    pub last_server_tick: u32,
    pub connection_time_ms: f64,
    /// Reached the authenticated Running state at least once.
    pub connected_ok: bool,
    /// The server (or transport) dropped us without our asking.
    pub unexpected_disconnect: bool,
    pub error_count: u64,
    pub last_error: String,
    /// Server packets that failed `ServerPacket::decode` — must be zero (strict decode).
    pub decode_failures: u64,
    /// ENet's mean packet-loss ratio (0..1), last sampled value.
    pub enet_packet_loss: f64,
    /// Farthest replicated entity ever observed (AoI cull assertion input).
    pub max_observed_entity_distance: f32,
    /// Latest SERVER_METRICS packet, with the elapsed-seconds timestamp it arrived at.
    pub latest_server_metrics: Option<(f64, ServerMetrics)>,
}

impl BotMetrics {
    pub fn avg_latency(&self) -> f64 {
        if self.latencies_ms.is_empty() {
            0.0
        } else {
            self.latencies_ms.iter().sum::<f64>() / self.latencies_ms.len() as f64
        }
    }

    pub fn summary(&self) -> Value {
        json!({
            "bot_id": self.bot_id,
            "behavior": self.behavior,
            "connected": self.connected_ok,
            "unexpected_disconnect": self.unexpected_disconnect,
            "connection_time_ms": round1(self.connection_time_ms),
            "latency_avg_ms": round1(self.avg_latency()),
            "latency_p95_ms": round1(percentile(&self.latencies_ms, 0.95)),
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "state_updates_received": self.state_updates_received,
            "baselines_received": self.baselines_received,
            "action_confirms_received": self.action_confirms_received,
            "game_events_received": self.game_events_received,
            "hit_reports_sent": self.hit_reports_sent,
            "respawn_requests_sent": self.respawn_requests_sent,
            "decode_failures": self.decode_failures,
            "enet_packet_loss_pct": round2(self.enet_packet_loss * 100.0),
            "max_observed_entity_distance": round1(self.max_observed_entity_distance as f64),
            "error_count": self.error_count,
            "last_error": self.last_error,
        })
    }
}

/// `sorted[int(len * q)]` — same indexing as the Python harness.
pub fn percentile(samples: &[f64], q: f64) -> f64 {
    if samples.is_empty() {
        return 0.0;
    }
    let mut sorted: Vec<f64> = samples.to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let idx = ((sorted.len() as f64 * q) as usize).min(sorted.len() - 1);
    sorted[idx]
}

#[derive(Debug, Default)]
pub struct Aggregated {
    pub total_bots: usize,
    pub connected_bots: usize,
    pub disconnected_bots: usize,
    pub duration_seconds: f64,
    pub latency_min_ms: f64,
    pub latency_max_ms: f64,
    pub latency_avg_ms: f64,
    pub latency_p95_ms: f64,
    pub latency_p99_ms: f64,
    pub total_packets_sent: u64,
    pub total_packets_received: u64,
    pub total_bytes_sent: u64,
    pub total_bytes_received: u64,
    pub avg_bandwidth_per_player_kbps: f64,
    pub avg_state_updates_per_bot: f64,
    pub estimated_server_tick_rate: f64,
    pub packet_loss_pct: f64,
    pub total_errors: u64,
    pub total_decode_failures: u64,
    pub crash_rate_pct: f64,
    pub server_avg_tick_time_ms: f64,
    pub server_max_tick_time_ms: f64,
    pub server_entity_count: u16,
    pub server_player_count: u16,
    pub server_total_bytes_sent: u32,
    pub server_avg_bandwidth_per_client: u32,
}

pub fn aggregate<'a, I>(metrics: I, duration: f64) -> Aggregated
where
    I: IntoIterator<Item = &'a BotMetrics>,
{
    let metrics: Vec<&BotMetrics> = metrics.into_iter().collect();
    let mut agg = Aggregated {
        total_bots: metrics.len(),
        duration_seconds: duration,
        ..Default::default()
    };
    if metrics.is_empty() {
        return agg;
    }

    let mut all_latencies: Vec<f64> = Vec::new();
    let mut loss_samples: Vec<f64> = Vec::new();
    let mut total_state_updates: u64 = 0;
    let mut tick_min: Option<u32> = None;
    let mut tick_max: u32 = 0;
    let mut latest_sm: Option<&(f64, ServerMetrics)> = None;

    for m in &metrics {
        if m.connected_ok && !m.unexpected_disconnect {
            agg.connected_bots += 1;
        } else {
            agg.disconnected_bots += 1;
        }
        all_latencies.extend_from_slice(&m.latencies_ms);
        if m.connected_ok {
            loss_samples.push(m.enet_packet_loss);
        }
        total_state_updates += m.state_updates_received;
        if let Some(t) = m.first_server_tick {
            tick_min = Some(tick_min.map_or(t, |cur| cur.min(t)));
            tick_max = tick_max.max(m.last_server_tick);
        }
        agg.total_packets_sent += m.packets_sent;
        agg.total_packets_received += m.packets_received;
        agg.total_bytes_sent += m.bytes_sent;
        agg.total_bytes_received += m.bytes_received;
        agg.total_errors += m.error_count;
        agg.total_decode_failures += m.decode_failures;
        if let Some(sm) = &m.latest_server_metrics {
            if latest_sm.is_none_or(|cur| sm.0 > cur.0) {
                latest_sm = Some(sm);
            }
        }
    }

    if !all_latencies.is_empty() {
        all_latencies.sort_by(|a, b| a.total_cmp(b));
        agg.latency_min_ms = all_latencies[0];
        agg.latency_max_ms = *all_latencies.last().unwrap();
        agg.latency_avg_ms = all_latencies.iter().sum::<f64>() / all_latencies.len() as f64;
        agg.latency_p95_ms = percentile(&all_latencies, 0.95);
        agg.latency_p99_ms = percentile(&all_latencies, 0.99);
    }
    if duration > 0.0 && agg.connected_bots > 0 {
        let total = (agg.total_bytes_sent + agg.total_bytes_received) as f64;
        agg.avg_bandwidth_per_player_kbps = total / agg.connected_bots as f64 / duration / 1024.0;
    }
    if let Some(min) = tick_min {
        if duration > 0.0 && tick_max > min {
            agg.estimated_server_tick_rate = (tick_max - min) as f64 / duration;
        }
    }
    agg.avg_state_updates_per_bot = total_state_updates as f64 / metrics.len() as f64;
    if !loss_samples.is_empty() {
        agg.packet_loss_pct = loss_samples.iter().sum::<f64>() / loss_samples.len() as f64 * 100.0;
    }
    agg.crash_rate_pct = agg.disconnected_bots as f64 / agg.total_bots as f64 * 100.0;
    if let Some((_, sm)) = latest_sm {
        agg.server_avg_tick_time_ms = sm.avg_tick_time_ms_x100 as f64 / 100.0;
        agg.server_max_tick_time_ms = sm.max_tick_time_ms_x100 as f64 / 100.0;
        agg.server_entity_count = sm.entity_count;
        agg.server_player_count = sm.player_count;
        agg.server_total_bytes_sent = sm.total_bytes_sent;
        agg.server_avg_bandwidth_per_client = sm.avg_bandwidth_per_client;
    }
    agg
}

pub struct Criterion {
    pub key: &'static str,
    pub criterion: String,
    pub value: String,
    pub passed: bool,
}

pub fn evaluate_success(agg: &Aggregated) -> Vec<Criterion> {
    vec![
        Criterion {
            key: "latency_avg",
            criterion: format!("Average latency < {LATENCY_AVG_MAX_MS:.0}ms"),
            value: format!("{:.1}ms", agg.latency_avg_ms),
            passed: agg.latency_avg_ms < LATENCY_AVG_MAX_MS,
        },
        Criterion {
            key: "latency_p95",
            criterion: format!("P95 latency < {LATENCY_P95_MAX_MS:.0}ms"),
            value: format!("{:.1}ms", agg.latency_p95_ms),
            passed: agg.latency_p95_ms < LATENCY_P95_MAX_MS,
        },
        Criterion {
            key: "bandwidth",
            criterion: format!("Bandwidth < {BANDWIDTH_PER_PLAYER_MAX_KBPS:.1} KB/s per player"),
            value: format!("{:.2} KB/s", agg.avg_bandwidth_per_player_kbps),
            passed: agg.avg_bandwidth_per_player_kbps < BANDWIDTH_PER_PLAYER_MAX_KBPS,
        },
        Criterion {
            key: "packet_loss",
            criterion: format!("Packet loss < {PACKET_LOSS_MAX_PCT:.1}%"),
            value: format!("{:.2}%", agg.packet_loss_pct),
            passed: agg.packet_loss_pct < PACKET_LOSS_MAX_PCT,
        },
        Criterion {
            key: "crash_rate",
            criterion: format!("Bot crash rate < {CRASH_RATE_MAX_PCT:.1}%"),
            value: format!("{:.1}%", agg.crash_rate_pct),
            passed: agg.crash_rate_pct < CRASH_RATE_MAX_PCT,
        },
        Criterion {
            key: "server_tick_rate",
            criterion: format!("Server tick rate > {SERVER_FPS_MIN:.0} Hz"),
            value: format!("{:.1} Hz", agg.estimated_server_tick_rate),
            passed: agg.estimated_server_tick_rate >= SERVER_FPS_MIN,
        },
    ]
}

pub fn generate_report(agg: &Aggregated, server: &str, unix_secs: u64) -> String {
    let success = evaluate_success(agg);
    let all_passed = success.iter().all(|c| c.passed);
    let mut lines = vec![
        String::new(),
        "=".repeat(60),
        "  Omega Realm Load Test Report (ENet/Rust)".into(),
        "=".repeat(60),
        String::new(),
        "Test Configuration:".into(),
        format!("  Bot Count:       {}", agg.total_bots),
        format!("  Duration:        {:.0} seconds", agg.duration_seconds),
        format!("  Server:          {server}"),
        format!("  Timestamp:       {} (UTC)", iso8601_utc(unix_secs)),
        String::new(),
        "Connection Summary:".into(),
        format!("  Connected:       {}", agg.connected_bots),
        format!("  Disconnected:    {}", agg.disconnected_bots),
        format!("  Errors:          {}", agg.total_errors),
        format!("  Decode Failures: {}", agg.total_decode_failures),
        String::new(),
        "Server Metrics (client-estimated):".into(),
        format!(
            "  Est. Tick Rate:  {:.1} Hz",
            agg.estimated_server_tick_rate
        ),
        format!(
            "  State Updates:   {:.0} per bot (avg)",
            agg.avg_state_updates_per_bot
        ),
        String::new(),
        "Server Metrics (server-reported):".into(),
        format!("  Avg Tick Time:   {:.2}ms", agg.server_avg_tick_time_ms),
        format!("  Max Tick Time:   {:.2}ms", agg.server_max_tick_time_ms),
        format!("  Players:         {}", agg.server_player_count),
        format!("  Entity Count:    {}", agg.server_entity_count),
        format!("  Total Bytes Out: {}", agg.server_total_bytes_sent),
        format!(
            "  Avg BW/Client:   {} bytes",
            agg.server_avg_bandwidth_per_client
        ),
        String::new(),
        "Network Metrics:".into(),
        format!("  Packets Sent:    {}", agg.total_packets_sent),
        format!("  Packets Recv:    {}", agg.total_packets_received),
        format!(
            "  Bandwidth/Player: {:.2} KB/s",
            agg.avg_bandwidth_per_player_kbps
        ),
        String::new(),
        "Latency Distribution (ENet RTT):".into(),
        format!("  Min:             {:.1}ms", agg.latency_min_ms),
        format!("  Avg:             {:.1}ms", agg.latency_avg_ms),
        format!("  Max:             {:.1}ms", agg.latency_max_ms),
        format!("  P95:             {:.1}ms", agg.latency_p95_ms),
        format!("  P99:             {:.1}ms", agg.latency_p99_ms),
        format!("  Packet Loss:     {:.2}%", agg.packet_loss_pct),
        String::new(),
        "Success Criteria:".into(),
    ];
    for c in &success {
        let icon = if c.passed { "PASS" } else { "FAIL" };
        lines.push(format!("  [{icon}] {}: {}", c.criterion, c.value));
    }
    lines.push(String::new());
    lines.push("-".repeat(60));
    lines.push(format!(
        "  Conclusion: {}",
        if all_passed {
            "ALL CRITERIA MET"
        } else {
            "SOME CRITERIA FAILED"
        }
    ));
    lines.push("-".repeat(60));
    lines.push(String::new());
    lines.join("\n")
}

#[allow(clippy::too_many_arguments)]
pub fn report_json(
    agg: &Aggregated,
    per_bot: Vec<Value>,
    server: &str,
    unix_secs: u64,
    time_series: &[Value],
    assertions: &[crate::assertions::AssertionResult],
) -> Value {
    let success: Value = evaluate_success(agg)
        .iter()
        .map(|c| {
            (
                c.key.to_string(),
                json!({"passed": c.passed, "value": c.value}),
            )
        })
        .collect::<serde_json::Map<String, Value>>()
        .into();
    let mut report = json!({
        "timestamp": iso8601_utc(unix_secs),
        "config": {
            "bot_count": agg.total_bots,
            "duration_seconds": agg.duration_seconds,
            "server": server,
        },
        "aggregated": {
            "connected_bots": agg.connected_bots,
            "disconnected_bots": agg.disconnected_bots,
            "total_errors": agg.total_errors,
            "total_decode_failures": agg.total_decode_failures,
            "latency_min_ms": round1(agg.latency_min_ms),
            "latency_avg_ms": round1(agg.latency_avg_ms),
            "latency_max_ms": round1(agg.latency_max_ms),
            "latency_p95_ms": round1(agg.latency_p95_ms),
            "latency_p99_ms": round1(agg.latency_p99_ms),
            "packet_loss_pct": round2(agg.packet_loss_pct),
            "bandwidth_per_player_kbps": round2(agg.avg_bandwidth_per_player_kbps),
            "estimated_tick_rate": round1(agg.estimated_server_tick_rate),
            "total_packets_sent": agg.total_packets_sent,
            "total_packets_received": agg.total_packets_received,
        },
        "server_reported": {
            "avg_tick_time_ms": round2(agg.server_avg_tick_time_ms),
            "max_tick_time_ms": round2(agg.server_max_tick_time_ms),
            "player_count": agg.server_player_count,
            "entity_count": agg.server_entity_count,
            "total_bytes_sent": agg.server_total_bytes_sent,
            "avg_bandwidth_per_client": agg.server_avg_bandwidth_per_client,
        },
        "success_criteria": success,
        "time_series": time_series,
        "per_bot": per_bot,
    });
    if !assertions.is_empty() {
        report["regression_assertions"] = assertions
            .iter()
            .map(|r| {
                json!({
                    "name": r.name,
                    "passed": r.passed,
                    "skipped": r.skipped,
                    "message": r.message,
                    "details": r.details,
                })
            })
            .collect();
    }
    report
}

fn round1(v: f64) -> f64 {
    (v * 10.0).round() / 10.0
}

fn round2(v: f64) -> f64 {
    (v * 100.0).round() / 100.0
}

/// Unix seconds → `YYYY-MM-DDTHH:MM:SSZ` (Howard Hinnant's civil-from-days algorithm; avoids a
/// chrono dependency for one timestamp).
pub fn iso8601_utc(unix_secs: u64) -> String {
    let (y, m, d) = civil_from_days((unix_secs / 86_400) as i64);
    let s = unix_secs % 86_400;
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z",
        s / 3600,
        (s / 60) % 60,
        s % 60
    )
}

/// Unix seconds → `YYYYmmdd_HHMMSS` for the default report filename.
pub fn compact_timestamp(unix_secs: u64) -> String {
    let (y, m, d) = civil_from_days((unix_secs / 86_400) as i64);
    let s = unix_secs % 86_400;
    format!(
        "{y:04}{m:02}{d:02}_{:02}{:02}{:02}",
        s / 3600,
        (s / 60) % 60,
        s % 60
    )
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iso8601_known_values() {
        assert_eq!(iso8601_utc(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso8601_utc(1_700_000_000), "2023-11-14T22:13:20Z");
    }

    #[test]
    fn percentile_matches_python_indexing() {
        let samples: Vec<f64> = (1..=100).map(|i| i as f64).collect();
        assert_eq!(percentile(&samples, 0.95), 96.0); // sorted[int(100*0.95)] = sorted[95]
        assert_eq!(percentile(&[], 0.95), 0.0);
    }

    #[test]
    fn aggregate_counts_connections_and_estimates_tick_rate() {
        let mut a = BotMetrics {
            connected_ok: true,
            first_server_tick: Some(100),
            last_server_tick: 400,
            latencies_ms: vec![10.0, 20.0],
            ..Default::default()
        };
        a.bytes_received = 10_240;
        let b = BotMetrics {
            connected_ok: false,
            last_error: "connect timeout".into(),
            ..Default::default()
        };
        let agg = aggregate([&a, &b], 10.0);
        assert_eq!(agg.connected_bots, 1);
        assert_eq!(agg.disconnected_bots, 1);
        assert_eq!(agg.crash_rate_pct, 50.0);
        assert!((agg.estimated_server_tick_rate - 30.0).abs() < 1e-9);
        assert!((agg.latency_avg_ms - 15.0).abs() < 1e-9);
        // (10240 + 0) bytes / 1 connected bot / 10 s / 1024 = 1 KB/s
        assert!((agg.avg_bandwidth_per_player_kbps - 1.0).abs() < 1e-9);
    }
}
