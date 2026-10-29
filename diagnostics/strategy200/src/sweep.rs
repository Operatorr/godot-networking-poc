//! Fixed-size whole-sweep observations; no per-event instrumentation.
use serde_json::{json, Value};
use std::{cell::RefCell, sync::OnceLock, time::Instant};

const BOUNDS_NS: [u64; 7] = [100_000, 500_000, 1_000_000, 5_000_000, 10_000_000, 33_333_333, 100_000_000];

pub fn event_budget() -> usize {
    static BUDGET: OnceLock<usize> = OnceLock::new();
    *BUDGET.get_or_init(|| match std::env::var("OMEGA_BOT_EVENT_BUDGET").as_deref() {
        Err(std::env::VarError::NotPresent) | Ok("0") => 0,
        Ok("32") => 32,
        _ => panic!("OMEGA_BOT_EVENT_BUDGET must be absent, 0 or 32"),
    })
}

fn enabled() -> bool {
    #[cfg(feature = "synthetic-replay")]
    if let Some(enabled) = REPLAY_ENABLED.with(|e| e.get()) { return enabled; }
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| match std::env::var("OMEGA_SWEEP_OBSERVER").as_deref() {
        Err(std::env::VarError::NotPresent) | Ok("0") => false,
        Ok("1") => true,
        _ => panic!("OMEGA_SWEEP_OBSERVER must be absent, 0 or 1"),
    })
}

pub fn validate() {
    event_budget();
    enabled();
    assert!(std::env::var_os("OMEGA_NATIVE_DIAG").is_none(), "native observer forbidden in this diagnostic condition");
}

#[derive(Default)]
pub struct Observer {
    sweeps: u64,
    bot_visits: u64,
    total_ns: u128,
    max_ns: u64,
    buckets: [u64; 8],
}

impl Observer {
    pub fn start(enabled: bool) -> Option<Instant> {
        enabled.then(Instant::now)
    }
    pub fn finish(&mut self, started: Option<Instant>, bots: usize) {
        if let Some(started) = started {
            let elapsed = started.elapsed().as_nanos().min(u64::MAX as u128) as u64;
            self.sweeps = self.sweeps.checked_add(1).expect("sweep count overflow");
            self.bot_visits = self.bot_visits.checked_add(bots as u64).expect("visit count overflow");
            self.total_ns = self.total_ns.checked_add(u128::from(elapsed)).expect("duration overflow");
            self.max_ns = self.max_ns.max(elapsed);
            let bucket = BOUNDS_NS.iter().position(|b| elapsed <= *b).unwrap_or(7);
            self.buckets[bucket] = self.buckets[bucket].checked_add(1).expect("histogram overflow");
        }
    }
    pub fn snapshot(&self) -> Value {
        json!({"completed_sweeps": self.sweeps, "bot_visits": self.bot_visits,
            "total_ns": self.total_ns, "max_ns": self.max_ns, "buckets": self.buckets,
            "bounds_ns": BOUNDS_NS, "scope": "Whole poll_all only; excludes sleep, recorder, exporter and observer finish bookkeeping"})
    }
}

thread_local! { static OBSERVER: RefCell<Observer> = RefCell::new(Observer::default()); }
#[cfg(feature = "synthetic-replay")]
thread_local! { static REPLAY_ENABLED: std::cell::Cell<Option<bool>> = const { std::cell::Cell::new(None) }; }
#[cfg(feature = "synthetic-replay")]
pub fn configure_replay(enabled: bool) {
    REPLAY_ENABLED.with(|e| e.set(Some(enabled)));
    OBSERVER.with(|o| *o.borrow_mut() = Observer::default());
}

pub fn global_start() -> Option<Instant> {
    Observer::start(enabled())
}
pub fn global_finish(started: Option<Instant>, bots: usize) {
    if started.is_some() {
        OBSERVER.with(|o| o.borrow_mut().finish(started, bots));
    }
}
pub fn global_snapshot() -> Value {
    if enabled() { OBSERVER.with(|o| o.borrow().snapshot()) } else { Value::Null }
}
