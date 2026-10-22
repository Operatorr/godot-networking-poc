//! Passive, opt-in input/delivery observations, cumulative between timestamped samples.
use std::fs::File;
use std::io::{BufWriter, Write};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

// Upper bounds in ms; final bucket is >100. These are counts, never averaged quantiles.
pub const GAP_BOUNDS_MS: [f64; 7] = [10.0, 20.0, 30.0, 35.0, 40.0, 50.0, 100.0];

pub struct BotObservation {
    pub inputs: u64,
    pub missed_schedules: u64,
    pub shoot_inputs: u64,
    pub ability_inputs: u64,
    pub input_gaps: [u64; 8],
    pub input_gap_max_ms: f64,
    pub snapshot_gaps: [u64; 8],
    pub snapshot_gap_max_ms: f64,
    pub baseline_reference_misses: u64,
    pub unknown_delta_entities: u64,
    pub last_baseline: Option<u32>,
    pub last_input: Option<Instant>,
    pub last_snapshot: Option<Instant>,
    pub last_snapshot_server_ms: u32,
    pub last_snapshot_tick: u32,
    pub last_delta: Option<Instant>,
    pub last_confirm: Option<Instant>,
    pub sent: [u64; 256],
    pub received: [u64; 256],
}

impl Default for BotObservation {
    fn default() -> Self {
        Self {
            inputs: 0,
            missed_schedules: 0,
            shoot_inputs: 0,
            ability_inputs: 0,
            input_gaps: [0; 8],
            input_gap_max_ms: 0.0,
            snapshot_gaps: [0; 8],
            snapshot_gap_max_ms: 0.0,
            baseline_reference_misses: 0,
            unknown_delta_entities: 0,
            last_baseline: None,
            last_input: None,
            last_snapshot: None,
            last_snapshot_server_ms: 0,
            last_snapshot_tick: 0,
            last_delta: None,
            last_confirm: None,
            sent: [0; 256],
            received: [0; 256],
        }
    }
}

pub fn observe_gap(previous: &mut Option<Instant>, buckets: &mut [u64; 8], maximum: &mut f64) {
    let now = Instant::now();
    if let Some(last) = *previous {
        let gap = now.duration_since(last).as_secs_f64() * 1000.0;
        buckets[GAP_BOUNDS_MS
            .iter()
            .position(|bound| gap <= *bound)
            .unwrap_or(7)] += 1;
        *maximum = maximum.max(gap);
    }
    *previous = Some(now);
}

pub struct Recorder {
    writer: BufWriter<File>,
    pub directory: std::path::PathBuf,
    origin: Instant,
    epoch_ns: u128,
    next_ramp_sample: Duration,
    completed_samples: u64,
    completed_observer_ns: u128,
}

impl Recorder {
    pub fn from_env() -> Option<Self> {
        let directory = std::path::PathBuf::from(std::env::var_os("OMEGA_MEASURE_DIR")?);
        std::fs::create_dir_all(&directory).unwrap();
        Some(Self {
            writer: BufWriter::with_capacity(
                1024 * 1024,
                File::create(directory.join("bots.ndjson")).unwrap(),
            ),
            directory,
            origin: Instant::now(),
            epoch_ns: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            next_ramp_sample: Duration::ZERO,
            completed_samples: 0,
            completed_observer_ns: 0,
        })
    }

    pub fn phase2(&self) {
        let stamp = self.epoch_ns + self.origin.elapsed().as_nanos();
        std::fs::write(
            self.directory.join("phase.json"),
            serde_json::json!({"phase2_utc_ns": stamp}).to_string(),
        )
        .unwrap();
    }

    pub fn sample(&mut self, bots: &[crate::bot::Bot], phase_s: f64, boundary: &str) {
        self.sample_phase(bots, Some(phase_s), "run", boundary);
    }

    /// Keep failed joins observable without changing the post-join measurement clock.
    pub fn sample_ramp(&mut self, bots: &[crate::bot::Bot]) {
        let elapsed = self.origin.elapsed();
        if elapsed >= self.next_ramp_sample {
            self.sample_phase(bots, None, "ramp", "");
            // Do not catch up missed observations in a burst after a long poll.
            self.next_ramp_sample = self.origin.elapsed() + Duration::from_secs(1);
        }
    }

    fn sample_phase(
        &mut self,
        bots: &[crate::bot::Bot],
        phase_s: Option<f64>,
        phase: &str,
        boundary: &str,
    ) {
        let observer_start = Instant::now();
        let mono = self.origin.elapsed().as_nanos();
        let observations: Vec<_> = bots.iter().map(|bot| bot.observation()).collect();
        writeln!(self.writer, "{}", serde_json::json!({"utc_ns": self.epoch_ns + mono, "mono_ns": mono,
            "phase": phase, "phase_s": phase_s, "boundary": boundary,
            "completed_samples": self.completed_samples, "completed_observer_ns": self.completed_observer_ns,
            "gap_bounds_ms": GAP_BOUNDS_MS, "bots": observations})).unwrap();
        self.writer.flush().unwrap();
        // The next row reports completed observation cost, including serialization/flush.
        self.completed_samples += 1;
        self.completed_observer_ns += observer_start.elapsed().as_nanos();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gap_buckets_count_actual_observations() {
        let mut previous = Some(Instant::now() - std::time::Duration::from_millis(200));
        let mut buckets = [0; 8];
        let mut maximum = 0.0;
        observe_gap(&mut previous, &mut buckets, &mut maximum);
        assert_eq!(buckets[7], 1);
        assert_eq!(buckets.iter().sum::<u64>(), 1);
        assert!(maximum >= 200.0);
    }
}
