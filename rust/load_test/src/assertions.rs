//! Regression assertions ported from `regression_assertions.py` (Phase 2 §8.3).
//!
//! Three of the four originals carry over. `lod_cadence` does not: the WebSocket server sent
//! MID/FAR entities on fixed tick intervals, which the assertion checked via median tick gaps;
//! the Rust server replaced that with a byte-budget priority scheduler (LOD is a distance
//! *penalty*, see `server/src/broadcast.rs`), so per-band cadence is emergent and has no
//! configured expected value to assert against. The scheduler's health is visible instead in the
//! SERVER_METRICS `sched_*` fields captured in every report.

use crate::metrics::BotMetrics;
use serde_json::{json, Value};

const AOI_TOLERANCE_UNITS: f64 = 50.0;
const AOI_BOT_PASS_RATIO: f64 = 0.95;

pub struct AssertionConfig {
    /// Server `aoi_exit_radius` (hysteresis outer edge) the cull assertion gates on.
    pub aoi_exit_radius: f64,
    /// Bytes/sec budget for the per-peer assertion; 0 skips it.
    pub rate_budget_bytes_per_sec: u64,
}

impl Default for AssertionConfig {
    fn default() -> Self {
        Self {
            aoi_exit_radius: 1100.0,
            rate_budget_bytes_per_sec: 0,
        }
    }
}

pub struct AssertionResult {
    pub name: &'static str,
    pub passed: bool,
    pub skipped: bool,
    pub message: String,
    pub details: Value,
}

pub fn run_all(
    metrics: &[&BotMetrics],
    duration_seconds: f64,
    cfg: &AssertionConfig,
) -> Vec<AssertionResult> {
    vec![
        assert_aoi_cull(metrics, cfg),
        assert_decode_clean(metrics),
        assert_per_peer_budget(metrics, duration_seconds, cfg),
    ]
}

/// No bot may observe entities meaningfully beyond the AoI exit radius. 95% of eligible bots
/// must pass (the tolerance absorbs the exit-hysteresis race on fast movers).
fn assert_aoi_cull(metrics: &[&BotMetrics], cfg: &AssertionConfig) -> AssertionResult {
    let threshold = cfg.aoi_exit_radius + AOI_TOLERANCE_UNITS;
    let eligible: Vec<&&BotMetrics> = metrics
        .iter()
        .filter(|m| m.max_observed_entity_distance > 0.0)
        .collect();
    if eligible.is_empty() {
        return AssertionResult {
            name: "aoi_cull",
            passed: true,
            skipped: true,
            message: "skipped: no entity observations".into(),
            details: Value::Null,
        };
    }
    let violators: Vec<Value> = eligible
        .iter()
        .filter(|m| (m.max_observed_entity_distance as f64) > threshold)
        .map(|m| json!({"bot_id": m.bot_id, "max_distance": m.max_observed_entity_distance}))
        .collect();
    let pass_ratio = (eligible.len() - violators.len()) as f64 / eligible.len() as f64;
    AssertionResult {
        name: "aoi_cull",
        passed: pass_ratio >= AOI_BOT_PASS_RATIO,
        skipped: false,
        message: format!(
            "{}/{} bots within {threshold:.0} u ({:.0}% required)",
            eligible.len() - violators.len(),
            eligible.len(),
            AOI_BOT_PASS_RATIO * 100.0
        ),
        details: json!({
            "threshold": threshold,
            "eligible_bots": eligible.len(),
            "violators": violators,
        }),
    }
}

/// Every server packet must decode strictly — one failure means codec drift or corruption.
/// (Successor of `batch_decode_clean`; the BATCH envelope died with the WebSocket transport.)
fn assert_decode_clean(metrics: &[&BotMetrics]) -> AssertionResult {
    let failing: Vec<Value> = metrics
        .iter()
        .filter(|m| m.decode_failures > 0)
        .map(|m| json!({"bot_id": m.bot_id, "decode_failures": m.decode_failures}))
        .collect();
    let total: u64 = metrics.iter().map(|m| m.decode_failures).sum();
    AssertionResult {
        name: "decode_clean",
        passed: total == 0,
        skipped: false,
        message: if total == 0 {
            "no decode failures".into()
        } else {
            format!("{total} decode failure(s) across {} bot(s)", failing.len())
        },
        details: json!({ "failing_bots": failing }),
    }
}

/// Each bot's received byte rate must respect the advertised per-peer bandwidth budget.
fn assert_per_peer_budget(
    metrics: &[&BotMetrics],
    duration_seconds: f64,
    cfg: &AssertionConfig,
) -> AssertionResult {
    if cfg.rate_budget_bytes_per_sec == 0 || duration_seconds <= 0.0 {
        return AssertionResult {
            name: "per_peer_budget",
            passed: true,
            skipped: true,
            message: "skipped: no --rate-budget configured".into(),
            details: Value::Null,
        };
    }
    let budget = cfg.rate_budget_bytes_per_sec as f64;
    let violators: Vec<Value> = metrics
        .iter()
        .filter(|m| m.connected_ok)
        .filter_map(|m| {
            let rate = m.bytes_received as f64 / duration_seconds;
            (rate > budget).then(|| json!({"bot_id": m.bot_id, "bytes_per_sec": rate.round()}))
        })
        .collect();
    AssertionResult {
        name: "per_peer_budget",
        passed: violators.is_empty(),
        skipped: false,
        message: format!("{} bot(s) over the {budget:.0} B/s budget", violators.len()),
        details: json!({"budget": budget, "violators": violators}),
    }
}

pub fn format_results(results: &[AssertionResult]) -> String {
    let mut lines = vec!["Regression Assertions (§8.3):".to_string()];
    for r in results {
        let icon = if r.skipped {
            "SKIP"
        } else if r.passed {
            "PASS"
        } else {
            "FAIL"
        };
        lines.push(format!("  [{icon}] {}: {}", r.name, r.message));
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bot(id: u32) -> BotMetrics {
        BotMetrics {
            bot_id: id,
            connected_ok: true,
            ..Default::default()
        }
    }

    #[test]
    fn aoi_cull_skips_without_observations_and_fails_on_violators() {
        let a = bot(1);
        let r = run_all(&[&a], 10.0, &AssertionConfig::default());
        assert!(r[0].skipped);

        let mut b = bot(2);
        b.max_observed_entity_distance = 2000.0;
        let r = assert_aoi_cull(&[&b], &AssertionConfig::default());
        assert!(!r.passed);

        let mut c = bot(3);
        c.max_observed_entity_distance = 1100.0;
        let r = assert_aoi_cull(&[&c], &AssertionConfig::default());
        assert!(r.passed);
    }

    #[test]
    fn decode_clean_fails_on_any_failure() {
        let mut a = bot(1);
        assert!(assert_decode_clean(&[&a]).passed);
        a.decode_failures = 1;
        assert!(!assert_decode_clean(&[&a]).passed);
    }

    #[test]
    fn per_peer_budget_gates_on_config() {
        let mut a = bot(1);
        a.bytes_received = 100_000;
        let off = AssertionConfig::default();
        assert!(assert_per_peer_budget(&[&a], 10.0, &off).skipped);

        let on = AssertionConfig {
            rate_budget_bytes_per_sec: 5_000,
            ..Default::default()
        };
        // 10 kB/s against a 5 kB/s budget.
        assert!(!assert_per_peer_budget(&[&a], 10.0, &on).passed);
        a.bytes_received = 40_000;
        assert!(assert_per_peer_budget(&[&a], 10.0, &on).passed);
    }
}
