//! Seedable PCG32 — same generator as the server's `rng.rs` (Godot-equivalent helpers), plus a
//! Box-Muller gaussian for the strategy bot's aim error.
//!
//! Per-bot streams: when the swarm is run with `--seed <base>`, each bot seeds its stream with
//! `Pcg32::new(base ^ bot_id)` ([`new`](Pcg32::new)) so runs are reproducible enough to compare
//! without being lockstep. Without `--seed`, bots seed from [`from_entropy`](Pcg32::from_entropy)
//! (wall clock ⊕ pid ⊕ bot_id) for a fresh non-reproducible run. The `^ bot_id` decorrelation is
//! the same in both paths; only the base differs.

pub struct Pcg32 {
    state: u64,
    inc: u64,
}

impl Pcg32 {
    pub fn new(seed: u64) -> Self {
        let mut rng = Self {
            state: 0,
            inc: (seed << 1) | 1,
        };
        rng.next_u32();
        rng.state = rng.state.wrapping_add(seed);
        rng.next_u32();
        rng
    }

    pub fn from_entropy(stream: u64) -> Self {
        let seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0x853c49e6748fea9b)
            ^ (std::process::id() as u64).rotate_left(32)
            ^ stream.rotate_left(17);
        Self::new(seed)
    }

    pub fn next_u32(&mut self) -> u32 {
        let old = self.state;
        self.state = old.wrapping_mul(6364136223846793005).wrapping_add(self.inc);
        let xorshifted = (((old >> 18) ^ old) >> 27) as u32;
        let rot = (old >> 59) as u32;
        xorshifted.rotate_right(rot)
    }

    /// Uniform in [0, 1) — Godot `randf` equivalent.
    pub fn randf(&mut self) -> f64 {
        (self.next_u32() >> 8) as f64 / (1u32 << 24) as f64
    }

    /// Uniform in [from, to).
    pub fn randf_range(&mut self, from: f64, to: f64) -> f64 {
        from + (to - from) * self.randf()
    }

    pub fn rand_index(&mut self, n: usize) -> usize {
        if n == 0 {
            return 0;
        }
        (self.next_u32() as usize) % n
    }

    /// Zero-mean gaussian sample (Box-Muller).
    pub fn gauss(&mut self, std_dev: f64) -> f64 {
        let u1 = self.randf().max(1e-12);
        let u2 = self.randf();
        std_dev * (-2.0 * u1.ln()).sqrt() * (std::f64::consts::TAU * u2).cos()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn randf_stays_in_unit_interval() {
        let mut rng = Pcg32::new(42);
        for _ in 0..10_000 {
            let v = rng.randf();
            assert!((0.0..1.0).contains(&v));
        }
    }

    #[test]
    fn gauss_is_roughly_centered() {
        let mut rng = Pcg32::new(7);
        let mean: f64 = (0..10_000).map(|_| rng.gauss(1.0)).sum::<f64>() / 10_000.0;
        assert!(mean.abs() < 0.05, "mean {mean}");
    }
}
