//! Seedable PCG32 owned by the sim — replaces Godot's process-global RNG (extraction monsters §7:
//! match distributions and call sites, not the stream; seedable for tests).

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

    pub fn from_entropy() -> Self {
        let seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0x853c49e6748fea9b)
            ^ (std::process::id() as u64).rotate_left(32);
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

    /// Uniform in [from, to) — Godot `randf_range` equivalent.
    pub fn randf_range(&mut self, from: f64, to: f64) -> f64 {
        from + (to - from) * self.randf()
    }

    /// Godot `randi() % n` equivalent.
    pub fn rand_index(&mut self, n: usize) -> usize {
        if n == 0 {
            return 0;
        }
        (self.next_u32() as usize) % n
    }
}
