//! `--measured-window`: the common scored interval the DigitalOcean capacity contract asks for.
//!
//! Generator shards (swarm threads, not the glossary's server **Shard**) each own their bots end
//! to end: socket, ENet host and sim state are created, polled and dropped on one thread. Nothing
//! here ever blocks a shard. Readiness is a value the coordinator reads and a window is a value
//! the shards read, so every ENet owner keeps polling from its first connect until it drains:
//!
//! ```text
//! bot i connects at i x stagger -> all N authenticated -> 2 s warmup -> publish a FUTURE start/end
//!   -> every shard acknowledges start -> hold -> every shard acknowledges end and freezes
//!   -> end guard (still connected, still polling) -> drain -> footer + fsync -> window.json
//! ```
//!
//! This module reports what happened and scores nothing. `scripts/do_session/measurement_window.py`
//! decides from these files whether the window is proven. The exit status says only whether the
//! evidence is finished: 0 window recorded, 1 window not established or incomplete, 4 a recorder
//! failed. A legacy `report.json` is written alongside as a labelled whole-run diagnostic.

use crate::behavior::BehaviorKind;
use crate::bot::{Bot, Phase};
use crate::metrics;
use rusty_enet as enet;
use serde_json::{json, Value};
use std::fs::{File, OpenOptions};
use std::io::{self, BufWriter, Write};
use std::net::{SocketAddr, UdpSocket};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{error, info, warn};

pub const SCHEMA: &str = "omega.measurement/2";
/// The accepted RTT warmup after the final authentication.
pub const WARMUP_NS: u64 = 2_000_000_000;
/// How far ahead the shared start is published, so every shard can see it before it arrives.
pub const PUBLISH_LEAD_NS: u64 = 1_000_000_000;
/// Still connected after the window, so the server's population is provable past its end even
/// with wall-clock uncertainty between the hosts.
pub const END_GUARD_NS: u64 = 2_000_000_000;
pub const DRAIN_NS: u64 = 1_500_000_000;
/// Upper bounds in ms; the final bucket is above the last bound. Counts, never quantiles.
pub const GAP_BOUNDS_MS: [u64; 7] = [10, 20, 30, 35, 40, 50, 100];
/// A shard that has not polled for this long is logged by the coordinator, independently of the
/// shard, because a wedged thread cannot report itself. Evidence only; the proof applies the limit.
const STALL_REPORT_NS: u64 = 500_000_000;
const SAMPLE_INTERVAL_NS: u64 = 1_000_000_000;
const COORDINATOR_POLL: Duration = Duration::from_millis(2);
const JOIN_MARGIN_NS: u64 = 2_000_000_000;
pub const BOT_FIELDS: [&str; 20] = [
    "id",
    "phase",
    "alive",
    "sent",
    "send_errors",
    "missed_slots",
    "dead_frames",
    "decode_failures",
    "errors",
    "panics",
    "snapshots",
    "rx_bytes",
    "tx_bytes",
    "socket_sent",
    "socket_zero_sends",
    "socket_send_errors",
    "socket_received",
    "socket_receive_errors",
    "gap_max_ns",
    "peer",
];

// ---- faults -------------------------------------------------------------------------------------

/// Deliberate failures for the fault battery. Nothing reaches this list unless the binary was
/// built with the `fault-injection` feature: release builds have no `--fault` argument at all.
#[derive(Debug, Clone, PartialEq)]
pub enum Fault {
    /// Sleep inside the shard's own loop, as a starved thread would.
    Starve {
        shard: usize,
        anchor: Anchor,
        offset_s: f64,
        ms: u64,
    },
    /// Leave the shard's loop early and drop its bots.
    ExitShard {
        shard: usize,
        anchor: Anchor,
        offset_s: f64,
    },
    /// The bot stays connected and polled but stops offering input.
    MuteBot {
        bot: u32,
        anchor: Anchor,
        offset_s: f64,
    },
    /// Stop writing this shard's file without a footer, as a full disk would.
    TruncateRecorder {
        shard: usize,
        anchor: Anchor,
        offset_s: f64,
    },
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Anchor {
    /// All N authenticated.
    Barrier,
    /// The published window start.
    Window,
}

/// `starve:<shard>:<anchor>:<offset_s>:<ms>`, `exit:<shard>:<anchor>:<offset_s>`,
/// `mute:<bot>:<anchor>:<offset_s>`, `truncate:<shard>:<anchor>:<offset_s>`.
#[allow(dead_code)]
pub fn parse_fault(text: &str) -> Result<Fault, String> {
    let parts: Vec<&str> = text.split(':').collect();
    let number = |index: usize| -> Result<f64, String> {
        parts
            .get(index)
            .and_then(|value| value.parse().ok())
            .ok_or_else(|| format!("bad fault '{text}'"))
    };
    let anchor = match parts.get(2) {
        Some(&"barrier") => Anchor::Barrier,
        Some(&"window") => Anchor::Window,
        _ => return Err(format!("bad fault anchor in '{text}'")),
    };
    let owner = number(1)? as usize;
    let offset_s = number(3)?;
    match parts[0] {
        "starve" => Ok(Fault::Starve {
            shard: owner,
            anchor,
            offset_s,
            ms: number(4)? as u64,
        }),
        "exit" => Ok(Fault::ExitShard {
            shard: owner,
            anchor,
            offset_s,
        }),
        "mute" => Ok(Fault::MuteBot {
            bot: owner as u32,
            anchor,
            offset_s,
        }),
        "truncate" => Ok(Fault::TruncateRecorder {
            shard: owner,
            anchor,
            offset_s,
        }),
        _ => Err(format!("unknown fault '{text}'")),
    }
}

// ---- input schedule -----------------------------------------------------------------------------

/// A fixed grid from the moment of authentication: slot k is due at `anchor + k x interval`.
/// What a window was owed is arithmetic over the grid, whatever the polls managed to do.
#[derive(Debug, Clone)]
pub struct InputSchedule {
    interval_ns: u64,
    anchor_ns: Option<u64>,
    next_slot: u64,
}

impl InputSchedule {
    pub fn new(interval_ns: u64) -> Self {
        Self {
            interval_ns: interval_ns.max(1),
            anchor_ns: None,
            next_slot: 0,
        }
    }

    pub fn anchor(&mut self, now_ns: u64) {
        self.anchor_ns = Some(now_ns);
        self.next_slot = 0;
    }

    pub fn due(&self, now_ns: u64) -> bool {
        self.anchor_ns
            .is_some_and(|anchor| now_ns >= anchor + self.next_slot * self.interval_ns)
    }

    /// The newest slot that is due, and how many older ones are given up. Never a burst.
    pub fn take(&mut self, now_ns: u64) -> (u64, u64) {
        let Some(anchor) = self.anchor_ns else {
            return (0, 0);
        };
        let slot = now_ns.saturating_sub(anchor) / self.interval_ns;
        let missed = slot.saturating_sub(self.next_slot);
        self.next_slot = slot + 1;
        (anchor + slot * self.interval_ns, missed)
    }

    /// Slots k >= 0 with `start <= anchor + k x interval < end`. `None` before authentication,
    /// because a bot with no schedule was owed an unknown amount, not zero.
    pub fn scheduled_between(&self, start_ns: u64, end_ns: u64) -> Option<u64> {
        let anchor = self.anchor_ns?;
        let slots_before = |t: u64| -> u64 { t.saturating_sub(anchor).div_ceil(self.interval_ns) };
        Some(slots_before(end_ns) - slots_before(start_ns))
    }
}

// ---- per-bot record -----------------------------------------------------------------------------

#[derive(Debug, Clone, Copy)]
pub struct Disconnected {
    pub at_ns: u64,
    pub reason: u32,
    pub expected: bool,
}

/// One bot's evidence. Plain data that stays on the owning shard.
#[derive(Debug)]
pub struct BotRecord {
    now_ns: u64,
    window: Option<(u64, u64)>,
    pub connected_ns: Option<u64>,
    pub authenticated_ns: Option<u64>,
    pub entity_id: Option<u16>,
    pub schedule: InputSchedule,
    current_slot_ns: u64,
    pub sent: u64,
    pub send_errors: u64,
    pub missed_slots: u64,
    pub dead_frames: u64,
    last_input_ns: Option<u64>,
    pub gap_max_ns: u64,
    pub window_sent: u64,
    pub window_send_errors: u64,
    pub window_dead_frames: u64,
    pub window_gap_buckets: [u64; 8],
    pub window_gap_max_ns: u64,
    pub last_window_input_ns: Option<u64>,
    peer_samples: Vec<(u64, f64, u32)>,
    pub disconnected: Option<Disconnected>,
    muted: bool,
}

impl BotRecord {
    pub fn new(now_ns: u64, schedule: InputSchedule) -> Self {
        Self {
            now_ns,
            window: None,
            connected_ns: None,
            authenticated_ns: None,
            entity_id: None,
            schedule,
            current_slot_ns: 0,
            sent: 0,
            send_errors: 0,
            missed_slots: 0,
            dead_frames: 0,
            last_input_ns: None,
            gap_max_ns: 0,
            window_sent: 0,
            window_send_errors: 0,
            window_dead_frames: 0,
            window_gap_buckets: [0; 8],
            window_gap_max_ns: 0,
            last_window_input_ns: None,
            peer_samples: Vec::new(),
            disconnected: None,
            muted: false,
        }
    }

    pub fn set_clock(&mut self, now_ns: u64, window: Option<(u64, u64)>) {
        self.now_ns = now_ns;
        self.window = window;
    }

    pub fn input_due(&self) -> bool {
        self.schedule.due(self.now_ns)
    }

    pub fn take_due_slot(&mut self) {
        let (slot_ns, missed) = self.schedule.take(self.now_ns);
        self.current_slot_ns = slot_ns;
        self.missed_slots += missed;
    }

    pub fn connected(&mut self) {
        self.connected_ns.get_or_insert(self.now_ns);
    }

    pub fn authenticated(&mut self, entity_id: u16) {
        self.authenticated_ns = Some(self.now_ns);
        self.entity_id = Some(entity_id);
        self.schedule.anchor(self.now_ns);
    }

    pub fn disconnected(&mut self, reason: u32, expected: bool) {
        self.disconnected.get_or_insert(Disconnected {
            at_ns: self.now_ns,
            reason,
            expected,
        });
    }

    pub fn input_muted(&self) -> bool {
        self.muted
    }

    pub fn mute(&mut self) {
        self.muted = true;
    }

    /// A frame scores for the window only if its slot is inside and it left before the end.
    fn slot_in_window(&self) -> bool {
        self.window.is_some_and(|(start, end)| {
            self.current_slot_ns >= start && self.current_slot_ns < end && self.now_ns < end
        })
    }

    pub fn note_dead_frame(&mut self, dead: bool) {
        if dead {
            self.dead_frames += 1;
            if self.slot_in_window() {
                self.window_dead_frames += 1;
            }
        }
    }

    pub fn input_sent(&mut self) {
        self.sent += 1;
        let gap = self
            .last_input_ns
            .map(|last| self.now_ns.saturating_sub(last));
        if let Some(gap) = gap {
            self.gap_max_ns = self.gap_max_ns.max(gap);
        }
        self.last_input_ns = Some(self.now_ns);
        if self.slot_in_window() {
            self.window_sent += 1;
            if let Some(last) = self.last_window_input_ns {
                let gap = self.now_ns.saturating_sub(last);
                self.window_gap_max_ns = self.window_gap_max_ns.max(gap);
                let bucket = GAP_BOUNDS_MS
                    .iter()
                    .position(|bound| gap <= bound * 1_000_000)
                    .unwrap_or(7);
                self.window_gap_buckets[bucket] += 1;
            }
            self.last_window_input_ns = Some(self.now_ns);
        }
    }

    pub fn input_failed(&mut self) {
        self.send_errors += 1;
        if self.slot_in_window() {
            self.window_send_errors += 1;
        }
    }

    pub fn peer_sample(&mut self, rtt_ms: f64, loss_raw: u32) {
        self.peer_samples.push((self.now_ns, rtt_ms, loss_raw));
    }

    pub fn take_peer_samples(&mut self) -> Vec<(u64, f64, u32)> {
        std::mem::take(&mut self.peer_samples)
    }
}

// ---- the bot's socket ---------------------------------------------------------------------------

#[derive(Debug, Default, Clone, Copy)]
pub struct SocketCounters {
    pub sent: u64,
    pub zero_sends: u64,
    pub send_errors: u64,
    pub received: u64,
    pub receive_errors: u64,
}

/// The stock `UdpSocket` adapter's behaviour, with what it would otherwise swallow counted.
#[derive(Debug)]
pub struct BotSocket {
    inner: UdpSocket,
    counters: SocketCounters,
}

impl BotSocket {
    pub fn new(inner: UdpSocket) -> Self {
        Self {
            inner,
            counters: SocketCounters::default(),
        }
    }

    pub fn local_port(&self) -> Option<u16> {
        self.inner.local_addr().ok().map(|addr| addr.port())
    }

    pub fn counters(&self) -> SocketCounters {
        self.counters
    }
}

impl enet::Socket for BotSocket {
    type Address = SocketAddr;
    type Error = io::Error;

    fn init(&mut self, options: enet::SocketOptions) -> io::Result<()> {
        <UdpSocket as enet::Socket>::init(&mut self.inner, options)
    }

    fn send(&mut self, address: SocketAddr, buffer: &[u8]) -> io::Result<usize> {
        let result = <UdpSocket as enet::Socket>::send(&mut self.inner, address, buffer);
        match &result {
            Ok(0) if !buffer.is_empty() => self.counters.zero_sends += 1,
            Ok(_) => self.counters.sent += 1,
            Err(_) => self.counters.send_errors += 1,
        }
        result
    }

    fn receive(
        &mut self,
        buffer: &mut [u8; enet::MTU_MAX],
    ) -> io::Result<Option<(SocketAddr, enet::PacketReceived)>> {
        let result = <UdpSocket as enet::Socket>::receive(&mut self.inner, buffer);
        match &result {
            Ok(Some(_)) => self.counters.received += 1,
            Ok(None) => {}
            Err(_) => self.counters.receive_errors += 1,
        }
        result
    }
}

// ---- configuration ------------------------------------------------------------------------------

/// Every control is explicit: a measured run has no defaults to drift.
#[derive(Debug, Clone)]
pub struct Controls {
    pub server_text: String,
    pub server: SocketAddr,
    pub bots: usize,
    pub threads: usize,
    pub stagger_ms: u64,
    pub behavior: BehaviorKind,
    pub difficulty: f64,
    pub input_hz: f64,
    pub seed: u64,
    pub hold_s: u64,
    pub readiness_timeout_s: f64,
    pub bandwidth_budget: u32,
    pub evidence_dir: PathBuf,
    pub report_path: PathBuf,
    pub faults: Vec<Fault>,
}

/// Accepted bound: the larger of 60 s or the nominal ramp plus 30 s (#60 section 3).
pub fn default_readiness_timeout_s(bots: usize, stagger_ms: u64) -> f64 {
    let ramp_s = bots as f64 * stagger_ms as f64 / 1000.0;
    (ramp_s + 30.0).max(60.0)
}

// ---- recorders ----------------------------------------------------------------------------------

/// Create-only. A second recorder over the same path fails instead of overwriting evidence.
fn create_new(path: &Path) -> io::Result<File> {
    OpenOptions::new().write(true).create_new(true).open(path)
}

fn wall_ns() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

/// The kernel's identity for this process where it exposes one; `null` otherwise, never a guess.
pub fn kernel_start_id() -> Option<String> {
    let text = std::fs::read_to_string("/proc/self/stat").ok()?;
    let rest = &text[text.rfind(')')? + 2..];
    Some(format!("ticks:{}", rest.split_whitespace().nth(19)?))
}

pub fn boot_id() -> Option<String> {
    std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .ok()
        .map(|text| text.trim().to_string())
}

/// One ordered, numbered, footered NDJSON stream. Numbering and the footer expose truncation;
/// the nonce exposes a file from another process. An I/O failure is kept and reported.
struct Stream {
    writer: BufWriter<File>,
    seq: u64,
    nonce: String,
    failure: Option<String>,
}

impl Stream {
    fn create(path: &Path, nonce: &str) -> io::Result<Self> {
        Ok(Self {
            writer: BufWriter::with_capacity(1024 * 1024, create_new(path)?),
            seq: 0,
            nonce: nonce.to_string(),
            failure: None,
        })
    }

    fn row(&mut self, kind: &str, mut row: Value) {
        row["k"] = json!(kind);
        row["seq"] = json!(self.seq);
        row["nonce"] = json!(self.nonce);
        self.seq += 1;
        if self.failure.is_none() {
            if let Err(error) = writeln!(self.writer, "{row}") {
                self.failure = Some(error.to_string());
            }
        }
    }

    fn flush(&mut self) {
        if self.failure.is_none() {
            if let Err(error) = self.writer.flush() {
                self.failure = Some(error.to_string());
            }
        }
    }

    fn sync(&mut self) {
        self.flush();
        if self.failure.is_none() {
            if let Err(error) = self.writer.get_ref().sync_all() {
                self.failure = Some(error.to_string());
            }
        }
    }
}

// ---- coordination -------------------------------------------------------------------------------

struct ShardSlot {
    last_poll_ns: AtomicU64,
    observed_ns: AtomicU64,
    start_ack_ns: AtomicU64,
    end_ack_ns: AtomicU64,
    finished: AtomicBool,
    recorder_failed: AtomicBool,
}

impl ShardSlot {
    fn new() -> Self {
        Self {
            last_poll_ns: AtomicU64::new(0),
            observed_ns: AtomicU64::new(0),
            start_ack_ns: AtomicU64::new(0),
            end_ack_ns: AtomicU64::new(0),
            finished: AtomicBool::new(false),
            recorder_failed: AtomicBool::new(false),
        }
    }
}

/// Never blocks a reader. A shard's whole interaction with the barrier is a handful of atomics.
pub struct Coordinator {
    origin: Instant,
    authenticated: AtomicUsize,
    terminal_before_window: AtomicUsize,
    lost_after_auth: AtomicUsize,
    final_auth_ns: AtomicU64,
    barrier_ns: OnceLock<u64>,
    window: OnceLock<(u64, u64)>,
    drain: AtomicBool,
    slots: Vec<ShardSlot>,
    lost_rows: Mutex<Vec<Value>>,
}

impl Coordinator {
    fn new(origin: Instant, shards: usize) -> Self {
        Self {
            origin,
            authenticated: AtomicUsize::new(0),
            terminal_before_window: AtomicUsize::new(0),
            lost_after_auth: AtomicUsize::new(0),
            final_auth_ns: AtomicU64::new(0),
            barrier_ns: OnceLock::new(),
            window: OnceLock::new(),
            drain: AtomicBool::new(false),
            slots: (0..shards).map(|_| ShardSlot::new()).collect(),
            lost_rows: Mutex::new(Vec::new()),
        }
    }

    fn now_ns(&self) -> u64 {
        self.origin.elapsed().as_nanos() as u64
    }

    /// One tight wall/monotonic pair in this process's own monotonic domain.
    fn clock_pair(&self) -> Value {
        let before = wall_ns();
        let mono = self.now_ns();
        let after = wall_ns();
        json!({"wall_before_ns": before, "mono_ns": mono, "wall_after_ns": after})
    }
}

/// A fault's trigger point on the shard's clock, once its anchor is known.
fn fault_time(co: &Coordinator, anchor: Anchor, offset_s: f64) -> Option<u64> {
    let base = match anchor {
        Anchor::Barrier => *co.barrier_ns.get()?,
        Anchor::Window => co.window.get()?.0,
    };
    Some((base as f64 + offset_s * 1e9).max(0.0) as u64)
}

/// Whatever ends the thread, the coordinator hears of it.
struct ExitGuard<'a> {
    slot: &'a ShardSlot,
}

impl Drop for ExitGuard<'_> {
    fn drop(&mut self) {
        self.slot.finished.store(true, Ordering::SeqCst);
    }
}

struct ShardOutcome {
    metrics: Vec<metrics::BotMetrics>,
}

fn bot_row(bot: &mut Bot) -> Value {
    let phase = format!("{:?}", bot.phase);
    let alive = !bot.is_dead();
    let socket = bot.socket_counters();
    let (decode, errors, panics, snapshots, rx, tx) = (
        bot.metrics.decode_failures,
        bot.metrics.error_count,
        bot.metrics.panic_count,
        bot.metrics.state_updates_received,
        bot.metrics.bytes_received,
        bot.metrics.bytes_sent,
    );
    let id = bot.id;
    let Some(record) = bot.record_mut() else {
        return Value::Null;
    };
    let peer: Vec<Value> = record
        .take_peer_samples()
        .into_iter()
        .map(|(at, rtt, loss)| json!([at, rtt, loss]))
        .collect();
    json!([
        id,
        phase,
        alive,
        record.sent,
        record.send_errors,
        record.missed_slots,
        record.dead_frames,
        decode,
        errors,
        panics,
        snapshots,
        rx,
        tx,
        socket.sent,
        socket.zero_sends,
        socket.send_errors,
        socket.received,
        socket.receive_errors,
        record.gap_max_ns,
        peer
    ])
}

fn freeze_row(bot: &Bot, start_ns: u64, end_ns: u64) -> Value {
    let Some(record) = bot.record() else {
        return Value::Null;
    };
    let socket = bot.socket_counters();
    json!({
        "id": bot.id,
        "phase": format!("{:?}", bot.phase),
        "alive": !bot.is_dead(),
        "scheduled": record.schedule.scheduled_between(start_ns, end_ns),
        "sent": record.window_sent,
        "send_errors": record.window_send_errors,
        "dead_frames": record.window_dead_frames,
        "gap_buckets": record.window_gap_buckets,
        "gap_max_ns": record.window_gap_max_ns,
        "last_input_ns": record.last_window_input_ns,
        "decode_failures": bot.metrics.decode_failures,
        "errors": bot.metrics.error_count,
        "panics": bot.metrics.panic_count,
        "socket_send_errors": socket.send_errors,
        "socket_zero_sends": socket.zero_sends,
        "socket_receive_errors": socket.receive_errors,
        "disconnected": record.disconnected.map(|d| json!({"at_ns": d.at_ns, "reason": d.reason, "expected": d.expected})),
    })
}

/// One shard's connect -> poll -> drain lifecycle. Nothing in this loop waits on another thread.
fn run_shard(shard: usize, controls: &Controls, co: &Coordinator, nonce: &str) -> ShardOutcome {
    let slot = &co.slots[shard];
    let _guard = ExitGuard { slot };
    // World geometry is thread-local in sim_core: this thread steps movement, so it sets its own.
    sim_core::set_world_geometry(
        sim_core::ARENA_GEOMETRY.min,
        sim_core::ARENA_GEOMETRY.max,
        sim_core::ARENA_GEOMETRY.obstacles_enabled,
    );
    let shards = co.slots.len();
    let path = controls.evidence_dir.join(format!("shard-{shard}.ndjson"));
    let mut stream = match Stream::create(&path, nonce) {
        Ok(stream) => stream,
        Err(error) => {
            error!("shard {shard}: cannot create {}: {error}", path.display());
            slot.recorder_failed.store(true, Ordering::SeqCst);
            return ShardOutcome {
                metrics: Vec::new(),
            };
        }
    };
    let ids: Vec<usize> = (shard..controls.bots).step_by(shards).collect();
    stream.row(
        "header",
        json!({
            "schema": SCHEMA, "shard": shard, "shards": shards, "thread": std::thread::current().name(),
            "bots": ids.iter().map(|i| i + 1).collect::<Vec<_>>(), "bot_fields": BOT_FIELDS, "gap_bounds_ms": GAP_BOUNDS_MS,
            "geometry": {"min": [sim_core::ARENA_GEOMETRY.min.x, sim_core::ARENA_GEOMETRY.min.y], "max": [sim_core::ARENA_GEOMETRY.max.x, sim_core::ARENA_GEOMETRY.max.y],
                         "obstacles_enabled": sim_core::ARENA_GEOMETRY.obstacles_enabled, "initialized_on_thread": true},
            "clock": co.clock_pair(),
        }),
    );
    stream.flush();

    let interval_ns = (1e9 / controls.input_hz.max(1.0)).round() as u64;
    let stagger_ns = controls.stagger_ms * 1_000_000;
    let mut bots: Vec<Bot> = Vec::with_capacity(ids.len());
    let mut last_phase: Vec<Phase> = Vec::with_capacity(ids.len());
    let mut stillborn: Vec<metrics::BotMetrics> = Vec::new();
    let mut next = 0usize;
    let mut window: Option<(u64, u64)> = None;
    let (mut started, mut ended) = (false, false);
    let mut last_poll: Option<u64> = None;
    let mut interval_polls = 0u64;
    let mut interval_max_gap = 0u64;
    let mut total_polls = 0u64;
    let mut max_gap_ns = 0u64;
    let mut next_sample = 0u64;
    let mut observer_ns = 0u64;
    let mut faults = controls.faults.clone();
    let mut left_early = false;
    let mut truncated = false;

    loop {
        let now = co.now_ns();
        if let Some(previous) = last_poll {
            let gap = now.saturating_sub(previous);
            interval_max_gap = interval_max_gap.max(gap);
            max_gap_ns = max_gap_ns.max(gap);
        }
        last_poll = Some(now);
        interval_polls += 1;
        total_polls += 1;
        slot.last_poll_ns.store(now, Ordering::SeqCst);

        if window.is_none() {
            if let Some(published) = co.window.get().copied() {
                window = Some(published);
                slot.observed_ns.store(now, Ordering::SeqCst);
                stream.row(
                    "window_observed",
                    json!({"mono_ns": now, "start_ns": published.0, "end_ns": published.1}),
                );
            }
        }

        // Global join cadence: bot i connects at its slot whichever shard owns it, and nothing
        // waits for a previous bot to settle. A slow handshake never moves the next slot.
        while next < ids.len()
            && now >= ids[next] as u64 * stagger_ns
            && !co.drain.load(Ordering::SeqCst)
        {
            let index = ids[next];
            let id = index as u32 + 1;
            let actual = co.now_ns();
            match Bot::connect(
                id,
                controls.server,
                controls.behavior,
                controls.difficulty,
                controls.input_hz,
                controls.bandwidth_budget,
                Some(controls.seed),
                None,
                actual as f64 / 1e9,
            ) {
                Ok(mut bot) => {
                    bot.enable_record(actual, interval_ns);
                    stream.row("join", json!({"bot": id, "scheduled_ns": index as u64 * stagger_ns, "actual_ns": actual, "local_port": bot.local_port()}));
                    last_phase.push(bot.phase);
                    bots.push(bot);
                }
                Err(error) => {
                    warn!("bot {id} failed to start: {error}");
                    stream.row("join", json!({"bot": id, "scheduled_ns": index as u64 * stagger_ns, "actual_ns": actual, "error": error.to_string()}));
                    co.terminal_before_window.fetch_add(1, Ordering::SeqCst);
                    stillborn.push(metrics::BotMetrics {
                        bot_id: id,
                        behavior: controls.behavior.name(),
                        error_count: 1,
                        last_error: error.to_string(),
                        ..Default::default()
                    });
                }
            }
            next += 1;
        }

        // Every bot gets its own time reading and panic boundary.
        for (index, bot) in bots.iter_mut().enumerate() {
            let at = co.now_ns();
            bot.set_record_clock(at, window);
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                bot.poll(at as f64 / 1e9)
            }));
            if let Err(payload) = result {
                let message = payload
                    .downcast_ref::<&str>()
                    .map(|text| text.to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "non-string panic payload".to_string());
                error!("bot {} panicked in poll: {message}", bot.id);
                bot.mark_crashed(format!("panic in poll: {message}"));
            }
            // Transitions move the shared population count. Nothing waits on it.
            let phase = bot.phase;
            if phase != last_phase[index] {
                let was = last_phase[index];
                last_phase[index] = phase;
                match phase {
                    Phase::Authing => {
                        stream.row("connected", json!({"bot": bot.id, "mono_ns": co.now_ns()}));
                    }
                    Phase::Running => {
                        let at = bot.record().and_then(|r| r.authenticated_ns).unwrap_or(at);
                        co.final_auth_ns.fetch_max(at, Ordering::SeqCst);
                        co.authenticated.fetch_add(1, Ordering::SeqCst);
                        stream.row(
                            "auth",
                            json!({"bot": bot.id, "mono_ns": at, "entity_id": bot.entity_id}),
                        );
                    }
                    Phase::Failed | Phase::Closed => {
                        let disconnected = bot.record().and_then(|r| r.disconnected);
                        let row = json!({"bot": bot.id, "mono_ns": co.now_ns(), "phase": format!("{phase:?}"), "error": bot.metrics.last_error,
                                         "unexpected": bot.metrics.unexpected_disconnect, "panics": bot.metrics.panic_count,
                                         "disconnected": disconnected.map(|d| json!({"at_ns": d.at_ns, "reason": d.reason, "expected": d.expected}))});
                        stream.row("bot_end", row.clone());
                        if was == Phase::Running {
                            co.authenticated.fetch_sub(1, Ordering::SeqCst);
                            co.lost_after_auth.fetch_add(1, Ordering::SeqCst);
                            if let Ok(mut rows) = co.lost_rows.lock() {
                                rows.push(row);
                            }
                        }
                        if co.window.get().is_none() {
                            co.terminal_before_window.fetch_add(1, Ordering::SeqCst);
                        }
                    }
                    _ => {}
                }
            }
        }

        let now = co.now_ns();
        if let Some((start, end)) = window {
            if !started && now >= start {
                started = true;
                slot.start_ack_ns.store(now, Ordering::SeqCst);
                stream.row("ack_start", json!({"mono_ns": now, "start_ns": start, "lateness_ns": now - start, "running": bots.iter().filter(|b| b.phase == Phase::Running).count()}));
                stream.flush();
            }
            if !ended && now >= end {
                ended = true;
                stream.row("ack_end", json!({"mono_ns": now, "end_ns": end, "lateness_ns": now - end, "running": bots.iter().filter(|b| b.phase == Phase::Running).count()}));
                stream.row("freeze", json!({"mono_ns": co.now_ns(), "start_ns": start, "end_ns": end,
                                            "bots": bots.iter().map(|b| freeze_row(b, start, end)).collect::<Vec<_>>(), "stillborn": stillborn.iter().map(|m| m.bot_id).collect::<Vec<_>>()}));
                stream.flush();
                slot.end_ack_ns.store(co.now_ns(), Ordering::SeqCst);
            }
        }

        if now >= next_sample {
            let observer = Instant::now();
            next_sample = now + SAMPLE_INTERVAL_NS;
            stream.row(
                "sample",
                json!({
                    "mono_ns": now, "clock": co.clock_pair(), "polls": interval_polls, "max_poll_gap_ns": interval_max_gap,
                    "completed_observer_ns": observer_ns,
                    "bots": bots.iter_mut().map(bot_row).collect::<Vec<_>>(),
                }),
            );
            stream.flush();
            interval_polls = 0;
            interval_max_gap = 0;
            observer_ns += observer.elapsed().as_nanos() as u64;
            if stream.failure.is_some() {
                slot.recorder_failed.store(true, Ordering::SeqCst);
            }
        }

        // Deliberate faults, only ever non-empty in a fault-injection build.
        let mut index = 0;
        while index < faults.len() {
            let (anchor, offset) = match &faults[index] {
                Fault::Starve {
                    anchor, offset_s, ..
                }
                | Fault::ExitShard {
                    anchor, offset_s, ..
                }
                | Fault::MuteBot {
                    anchor, offset_s, ..
                }
                | Fault::TruncateRecorder {
                    anchor, offset_s, ..
                } => (*anchor, *offset_s),
            };
            let due = fault_time(co, anchor, offset).is_some_and(|at| co.now_ns() >= at);
            if !due {
                index += 1;
                continue;
            }
            match faults.remove(index) {
                Fault::Starve {
                    shard: target, ms, ..
                } if target == shard => {
                    std::thread::sleep(Duration::from_millis(ms));
                }
                Fault::ExitShard { shard: target, .. } if target == shard => left_early = true,
                Fault::MuteBot { bot: target, .. } => {
                    if let Some(bot) = bots.iter_mut().find(|b| b.id == target) {
                        if let Some(record) = bot.record_mut() {
                            record.mute();
                        }
                    }
                }
                Fault::TruncateRecorder { shard: target, .. } if target == shard => {
                    truncated = true
                }
                _ => {}
            }
        }
        if left_early {
            break;
        }

        if co.drain.load(Ordering::SeqCst) {
            break;
        }
        std::thread::sleep(Duration::from_millis(1));
    }

    // ---- drain: outside the window by construction -------------------------------------------
    if !left_early {
        stream.row(
            "drain_start",
            json!({"mono_ns": co.now_ns(), "clock": co.clock_pair()}),
        );
        let begun = co.now_ns() as f64 / 1e9;
        for bot in &mut bots {
            let at = co.now_ns();
            bot.set_record_clock(at, window);
            bot.begin_disconnect(begun);
        }
        let deadline = co.now_ns() + DRAIN_NS;
        while co.now_ns() < deadline && bots.iter().any(|b| !b.is_terminal()) {
            for bot in &mut bots {
                let at = co.now_ns();
                bot.set_record_clock(at, window);
                let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    bot.poll(at as f64 / 1e9)
                }));
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        let unconfirmed = bots.iter().filter(|b| !b.is_terminal()).count();
        for bot in &mut bots {
            bot.force_close();
        }
        stream.row(
            "drain_end",
            json!({"mono_ns": co.now_ns(), "unconfirmed_disconnects": unconfirmed,
                                       "bots": bots.iter_mut().map(bot_row).collect::<Vec<_>>()}),
        );
    }

    if !truncated {
        stream.row(
            "footer",
            json!({
                "mono_ns": co.now_ns(), "clock": co.clock_pair(), "shard": shard, "left_early": left_early,
                "start_acked": started, "end_acked": ended, "polls": total_polls, "max_poll_gap_ns": max_gap_ns,
                "observer_ns": observer_ns, "recorder_failure": stream.failure,
            }),
        );
        stream.sync();
    }
    if stream.failure.is_some() {
        slot.recorder_failed.store(true, Ordering::SeqCst);
    }
    let mut metrics: Vec<metrics::BotMetrics> =
        bots.into_iter().map(|b| b.into_metrics()).collect();
    metrics.extend(stillborn);
    ShardOutcome { metrics }
}

// ---- the whole swarm ----------------------------------------------------------------------------

/// Runs the measured swarm and returns its exit status. Takes `stop` so tests own their own flag.
pub fn run(controls: Controls, stop: Arc<AtomicBool>) -> i32 {
    let origin = Instant::now();
    let nonce = format!("{:x}-{:x}", std::process::id(), wall_ns());
    if let Err(error) = std::fs::create_dir_all(&controls.evidence_dir) {
        error!("cannot create {}: {error}", controls.evidence_dir.display());
        return 4;
    }
    let shards = controls.threads;
    let co = Arc::new(Coordinator::new(origin, shards));
    let swarm = json!({
        "schema": SCHEMA, "nonce": nonce, "role": "bot", "pid": std::process::id(), "kernel_start_id": kernel_start_id(), "boot_id": boot_id(),
        "version": env!("CARGO_PKG_VERSION"), "clock": co.clock_pair(),
        "controls": {
            "server": controls.server_text, "bots": controls.bots, "threads": controls.threads, "bot_id_assignment": "round-robin", "join_stagger_ms": controls.stagger_ms,
            "behavior": controls.behavior.name(), "difficulty": controls.difficulty, "input_hz": controls.input_hz, "input_interval_ns": (1e9 / controls.input_hz.max(1.0)).round() as u64,
            "seed": controls.seed, "hold_s": controls.hold_s, "readiness_timeout_s": controls.readiness_timeout_s, "bandwidth_budget_bps": controls.bandwidth_budget,
            "warmup_ns": WARMUP_NS, "publish_lead_ns": PUBLISH_LEAD_NS, "end_guard_ns": END_GUARD_NS, "drain_ns": DRAIN_NS, "ticket_auth": false,
            "faults": controls.faults.iter().map(|fault| format!("{fault:?}")).collect::<Vec<_>>(),
        },
    });
    let write_swarm = create_new(&controls.evidence_dir.join("swarm.json")).and_then(|mut file| {
        writeln!(file, "{swarm}")?;
        file.sync_all()
    });
    if let Err(error) = write_swarm {
        error!("cannot create swarm.json: {error}");
        return 4;
    }
    let mut log = match Stream::create(&controls.evidence_dir.join("coordinator.ndjson"), &nonce) {
        Ok(stream) => stream,
        Err(error) => {
            error!("cannot create coordinator.ndjson: {error}");
            return 4;
        }
    };
    log.row(
        "header",
        json!({"schema": SCHEMA, "clock": co.clock_pair(), "pid": std::process::id()}),
    );
    log.sync();

    let mut handles = Vec::with_capacity(shards);
    for shard in 0..shards {
        let co_shard = co.clone();
        let cfg = controls.clone();
        let shard_nonce = nonce.clone();
        let handle = std::thread::Builder::new()
            .name(format!("swarm-{shard}"))
            .spawn(move || run_shard(shard, &cfg, &co_shard, &shard_nonce));
        match handle {
            Ok(handle) => handles.push(Some(handle)),
            Err(error) => {
                error!("cannot start shard {shard}: {error}");
                co.slots[shard].finished.store(true, Ordering::SeqCst);
                log.row(
                    "shard_not_started",
                    json!({"shard": shard, "error": error.to_string()}),
                );
                handles.push(None);
            }
        }
    }

    let readiness_ns = (controls.readiness_timeout_s * 1e9) as u64;
    let hold_ns = controls.hold_s * 1_000_000_000;
    let abort: Option<String> = coordinate(&controls, &co, &mut log, &stop, readiness_ns, hold_ns);

    // Bounded join: a wedged shard cannot hold the evidence of the others hostage.
    let join_by = co.now_ns() + DRAIN_NS + JOIN_MARGIN_NS;
    while co.now_ns() < join_by
        && !co
            .slots
            .iter()
            .all(|slot| slot.finished.load(Ordering::SeqCst))
    {
        std::thread::sleep(COORDINATOR_POLL);
    }
    let mut all_metrics: Vec<metrics::BotMetrics> = Vec::with_capacity(controls.bots);
    let mut unjoined: Vec<usize> = Vec::new();
    let mut panicked: Vec<usize> = Vec::new();
    for (shard, handle) in handles.into_iter().enumerate() {
        let Some(handle) = handle else { continue };
        if !co.slots[shard].finished.load(Ordering::SeqCst) {
            unjoined.push(shard);
            continue;
        }
        match handle.join() {
            Ok(outcome) => all_metrics.extend(outcome.metrics),
            Err(_) => panicked.push(shard),
        }
    }
    all_metrics.sort_by_key(|m| m.bot_id);

    let acks = |value: &AtomicU64| -> Option<u64> {
        match value.load(Ordering::SeqCst) {
            0 => None,
            at => Some(at),
        }
    };
    let window = co.window.get().copied();
    let every_ack = window.is_some()
        && co.slots.iter().all(|slot| {
            slot.start_ack_ns.load(Ordering::SeqCst) != 0
                && slot.end_ack_ns.load(Ordering::SeqCst) != 0
        });
    let status = match (&abort, window) {
        (Some(_), None) => "not_established",
        (Some(_), Some(_)) => "window_incomplete",
        (None, Some(_)) if every_ack && unjoined.is_empty() && panicked.is_empty() => {
            "window_recorded"
        }
        _ => "window_incomplete",
    };
    let recorder_failed = co
        .slots
        .iter()
        .any(|slot| slot.recorder_failed.load(Ordering::SeqCst));
    let lost_rows = co
        .lost_rows
        .lock()
        .map(|rows| rows.clone())
        .unwrap_or_default();
    let document = json!({
        "schema": SCHEMA, "nonce": nonce, "status": status, "reason": abort,
        "bots": controls.bots, "shards": shards, "hold_s": controls.hold_s,
        "final_auth_ns": co.barrier_ns.get().map(|_| co.final_auth_ns.load(Ordering::SeqCst)),
        "barrier_ns": co.barrier_ns.get(), "start_ns": window.map(|w| w.0), "end_ns": window.map(|w| w.1),
        "acks": co.slots.iter().enumerate().map(|(shard, slot)| json!({
            "shard": shard, "observed_ns": acks(&slot.observed_ns), "start_ack_ns": acks(&slot.start_ack_ns), "end_ack_ns": acks(&slot.end_ack_ns),
            "finished": slot.finished.load(Ordering::SeqCst), "recorder_failed": slot.recorder_failed.load(Ordering::SeqCst),
        })).collect::<Vec<_>>(),
        "unjoined_shards": unjoined, "panicked_shards": panicked,
        "lost_after_auth": co.lost_after_auth.load(Ordering::SeqCst), "lost_rows": lost_rows,
        "authenticated_at_end": co.authenticated.load(Ordering::SeqCst), "clock": co.clock_pair(),
    });
    log.row("footer", json!({"mono_ns": co.now_ns(), "clock": co.clock_pair(), "status": status, "recorder_failure": log.failure}));
    log.sync();
    let log_failed = log.failure.is_some();
    let write_window =
        create_new(&controls.evidence_dir.join("window.json")).and_then(|mut file| {
            writeln!(file, "{document}")?;
            file.sync_all()
        });
    if let Err(error) = &write_window {
        error!("cannot create window.json: {error}");
    }

    write_legacy_report(&controls, &all_metrics, status);
    info!(
        "Measured window: {status} {}",
        abort.as_deref().unwrap_or("")
    );
    if !unjoined.is_empty() {
        warn!("Leaving {} wedged shard(s) behind", unjoined.len());
    }
    if recorder_failed || log_failed || write_window.is_err() {
        return 4;
    }
    if status == "window_recorded" {
        0
    } else {
        1
    }
}

/// The barrier, on a thread that owns no ENet host. Returns why the run stopped early, if it did.
fn coordinate(
    controls: &Controls,
    co: &Coordinator,
    log: &mut Stream,
    stop: &AtomicBool,
    readiness_ns: u64,
    hold_ns: u64,
) -> Option<String> {
    let mut stalled = vec![false; co.slots.len()];
    let mut finished = vec![false; co.slots.len()];
    let mut next_clock = 0u64;
    let mut lost_seen = 0usize;
    let finish = |co: &Coordinator, log: &mut Stream, reason: &str| {
        co.drain.store(true, Ordering::SeqCst);
        log.row("abort", json!({"mono_ns": co.now_ns(), "reason": reason, "authenticated": co.authenticated.load(Ordering::SeqCst)}));
        log.sync();
    };
    loop {
        let now = co.now_ns();
        if now >= next_clock {
            next_clock = now + SAMPLE_INTERVAL_NS;
            log.row("clock", json!({"mono_ns": now, "clock": co.clock_pair(), "authenticated": co.authenticated.load(Ordering::SeqCst), "lost_after_auth": co.lost_after_auth.load(Ordering::SeqCst)}));
            log.flush();
        }
        for (shard, slot) in co.slots.iter().enumerate() {
            if slot.finished.load(Ordering::SeqCst) {
                if !finished[shard] {
                    finished[shard] = true;
                    log.row("shard_finished", json!({"shard": shard, "mono_ns": now, "during_drain": co.drain.load(Ordering::SeqCst)}));
                    log.flush();
                }
                continue;
            }
            let last = slot.last_poll_ns.load(Ordering::SeqCst);
            let stall = now.saturating_sub(last) > STALL_REPORT_NS;
            if stall && !stalled[shard] {
                log.row(
                    "shard_stall",
                    json!({"shard": shard, "mono_ns": now, "last_poll_ns": last}),
                );
                log.flush();
            }
            stalled[shard] = stall;
        }
        let lost = co.lost_after_auth.load(Ordering::SeqCst);
        if lost != lost_seen {
            lost_seen = lost;
            log.row("population_changed", json!({"mono_ns": now, "authenticated": co.authenticated.load(Ordering::SeqCst), "lost_after_auth": lost}));
            log.flush();
        }

        if stop.load(Ordering::SeqCst) {
            finish(co, log, "interrupted");
            return Some("interrupted".to_string());
        }
        let shard_gone = finished.iter().any(|gone| *gone);
        match co.window.get().copied() {
            None => {
                let reason = if shard_gone {
                    Some("shard_exited_before_window")
                } else if co.terminal_before_window.load(Ordering::SeqCst) > 0 {
                    Some("bot_failed_before_window")
                } else if now >= readiness_ns {
                    Some("readiness_timeout")
                } else {
                    None
                };
                if let Some(reason) = reason {
                    finish(co, log, reason);
                    return Some(reason.to_string());
                }
                let authenticated = co.authenticated.load(Ordering::SeqCst);
                if authenticated == controls.bots {
                    let barrier = co.final_auth_ns.load(Ordering::SeqCst);
                    if co.barrier_ns.get().is_none() {
                        let _ = co.barrier_ns.set(barrier);
                        log.row("barrier", json!({"mono_ns": now, "final_auth_ns": barrier, "authenticated": authenticated}));
                        log.sync();
                    }
                    if now >= barrier + WARMUP_NS {
                        let start = co.now_ns() + PUBLISH_LEAD_NS;
                        let published = (start, start + hold_ns);
                        // Durable before any shard can act on it.
                        log.row("window_published", json!({"mono_ns": co.now_ns(), "start_ns": published.0, "end_ns": published.1, "hold_ns": hold_ns, "final_auth_ns": barrier, "clock": co.clock_pair()}));
                        log.sync();
                        let _ = co.window.set(published);
                    }
                }
            }
            Some((_, end)) => {
                if now >= end + END_GUARD_NS {
                    co.drain.store(true, Ordering::SeqCst);
                    log.row("drain_requested", json!({"mono_ns": now, "clock": co.clock_pair(), "authenticated": co.authenticated.load(Ordering::SeqCst)}));
                    log.flush();
                    return None; // the shards drain from here; the caller bounds the join
                }
            }
        }
        std::thread::sleep(COORDINATOR_POLL);
    }
}

fn write_legacy_report(controls: &Controls, bots: &[metrics::BotMetrics], status: &str) {
    let references: Vec<&metrics::BotMetrics> = bots.iter().collect();
    let aggregate = metrics::aggregate(references.iter().copied(), controls.hold_s as f64);
    let unix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let per_bot: Vec<Value> = references.iter().map(|m| m.summary()).collect();
    let mut report =
        metrics::report_json(&aggregate, per_bot, &controls.server_text, unix, &[], &[]);
    // Whole-run fields, ramp and drain included. They decide nothing here.
    report["legacy_whole_run_diagnostic"] = json!(true);
    report["measured_window_status"] = json!(status);
    match serde_json::to_string_pretty(&report) {
        Ok(text) => {
            if let Err(error) = create_new(&controls.report_path)
                .and_then(|mut file| file.write_all(text.as_bytes()))
            {
                error!(
                    "failed to write {}: {error}",
                    controls.report_path.display()
                );
            }
        }
        Err(error) => error!("failed to serialize report JSON: {error}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use protocol::types::auth_result_code;
    use protocol::{AuthOk, AuthResult, ClientPacket, ServerPacket};
    use std::collections::HashMap;

    #[test]
    fn scheduled_frames_come_from_the_grid_not_the_polls() {
        let mut schedule = InputSchedule::new(100);
        assert_eq!(
            schedule.scheduled_between(0, 1000),
            None,
            "no schedule before auth is unknown, not zero"
        );
        schedule.anchor(50);
        // Slots at 50, 150, ... 950 fall inside [0, 1000).
        assert_eq!(schedule.scheduled_between(0, 1000), Some(10));
        // A boundary exactly on a slot: start is inclusive, end exclusive.
        assert_eq!(schedule.scheduled_between(150, 250), Some(1));
        assert_eq!(schedule.scheduled_between(151, 250), Some(0));
        assert_eq!(schedule.scheduled_between(150, 251), Some(2));
    }

    #[test]
    fn a_stall_gives_up_slots_instead_of_bursting() {
        let mut schedule = InputSchedule::new(100);
        schedule.anchor(0);
        assert!(schedule.due(0));
        assert_eq!(schedule.take(0), (0, 0));
        assert!(!schedule.due(99));
        // Polled again 1.05 slots of time later than slot 9: one frame, nine slots given up.
        assert_eq!(schedule.take(950), (900, 8));
        assert!(!schedule.due(950));
        assert!(schedule.due(1000));
    }

    #[test]
    fn frames_score_only_inside_the_window() {
        let mut record = BotRecord::new(0, InputSchedule::new(100));
        record.set_clock(0, Some((100, 300)));
        record.authenticated(7);
        for at in [0u64, 100, 200, 300] {
            record.set_clock(at, Some((100, 300)));
            record.take_due_slot();
            record.input_sent();
        }
        assert_eq!(record.sent, 4);
        assert_eq!(record.window_sent, 2);
        assert_eq!(record.schedule.scheduled_between(100, 300), Some(2));
        // A slot inside the window that only got out after its end does not score.
        record.set_clock(310, Some((100, 400)));
        record.current_slot_ns = 300;
        record.window = Some((100, 305));
        record.input_sent();
        assert_eq!(record.window_sent, 2);
    }

    #[test]
    fn round_robin_ownership_is_deterministic() {
        let owned =
            |shard: usize| -> Vec<usize> { (shard..10).step_by(4).map(|i| i + 1).collect() };
        assert_eq!(owned(0), [1, 5, 9]);
        assert_eq!(owned(1), [2, 6, 10]);
        assert_eq!(owned(2), [3, 7]);
        assert_eq!(owned(3), [4, 8]);
    }

    #[test]
    fn faults_parse_and_reject_garbage() {
        assert_eq!(
            parse_fault("starve:1:window:0.5:1200").unwrap(),
            Fault::Starve {
                shard: 1,
                anchor: Anchor::Window,
                offset_s: 0.5,
                ms: 1200
            }
        );
        assert_eq!(
            parse_fault("mute:3:barrier:1").unwrap(),
            Fault::MuteBot {
                bot: 3,
                anchor: Anchor::Barrier,
                offset_s: 1.0
            }
        );
        assert!(parse_fault("starve:1:nope:0:1").is_err());
        assert!(parse_fault("explode:1:window:0").is_err());
    }

    // ---- real threads, real sockets, a small real ENet server ---------------------------------

    /// Answers ConnectAuth, after a delay for chosen bots. Disconnects chosen bots at a chosen time.
    struct MiniServer {
        address: SocketAddr,
        stop: Arc<AtomicBool>,
        handle: Option<std::thread::JoinHandle<HashMap<String, u64>>>,
    }

    #[derive(Default, Clone)]
    struct Script {
        auth_delay: HashMap<String, Duration>,
        never_auth: Vec<String>,
        kick_after: Option<(String, Duration)>,
        kill_after: Option<(String, Duration)>,
    }

    impl MiniServer {
        fn start(script: Script) -> Self {
            let socket = UdpSocket::bind("127.0.0.1:0").unwrap();
            let address = socket.local_addr().unwrap();
            let stop = Arc::new(AtomicBool::new(false));
            let flag = stop.clone();
            let handle = std::thread::spawn(move || {
                let mut host = enet::Host::new(
                    socket,
                    enet::HostSettings {
                        peer_limit: 64,
                        channel_limit: protocol::CHANNEL_COUNT,
                        ..Default::default()
                    },
                )
                .unwrap();
                let started = Instant::now();
                let mut names: HashMap<usize, String> = HashMap::new();
                let mut pending: Vec<(Instant, usize)> = Vec::new();
                let mut inputs: HashMap<String, u64> = HashMap::new();
                let mut kick = script.kick_after.clone();
                let mut kill = script.kill_after.clone();
                let mut entities: HashMap<usize, u16> = HashMap::new();
                let mut next_entity = 1u16;
                while !flag.load(Ordering::SeqCst) {
                    while let Ok(Some(event)) = host.service() {
                        if let enet::EventNoRef::Receive { peer, packet, .. } = event.no_ref() {
                            match ClientPacket::decode(packet.data()) {
                                Ok(ClientPacket::ConnectAuth(auth)) => {
                                    let name = auth.character_name.clone();
                                    names.insert(peer.0, name.clone());
                                    if !script.never_auth.contains(&name) {
                                        let delay = script
                                            .auth_delay
                                            .get(&name)
                                            .copied()
                                            .unwrap_or_default();
                                        pending.push((Instant::now() + delay, peer.0));
                                    }
                                }
                                Ok(ClientPacket::PlayerInput(_)) => {
                                    if let Some(name) = names.get(&peer.0) {
                                        *inputs.entry(name.clone()).or_default() += 1;
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    let now = Instant::now();
                    let due: Vec<usize> = pending
                        .iter()
                        .filter(|(at, _)| *at <= now)
                        .map(|(_, key)| *key)
                        .collect();
                    pending.retain(|(at, _)| *at > now);
                    for key in due {
                        entities.insert(key, next_entity);
                        let result = ServerPacket::AuthResult(AuthResult {
                            result: auth_result_code::OK,
                            ok: Some(AuthOk {
                                entity_id: next_entity,
                                server_tick: 0,
                                tick_rate: 30,
                            }),
                        });
                        next_entity += 1;
                        let bytes = result.encode();
                        let _ = host
                            .peer_mut(enet::PeerID(key))
                            .send(1, &enet::Packet::reliable(bytes.as_slice()));
                    }
                    if let Some((name, after)) = &kill {
                        if started.elapsed() >= *after {
                            if let Some((key, _)) = names.iter().find(|(_, value)| *value == name) {
                                let event = ServerPacket::GameEvent(protocol::GameEvent {
                                    event_type: protocol::types::game_event_type::KILL,
                                    source_id: 30000,
                                    target_id: entities[key],
                                    data: protocol::GameEventData::None,
                                });
                                let bytes = event.encode();
                                let _ = host
                                    .peer_mut(enet::PeerID(*key))
                                    .send(1, &enet::Packet::reliable(bytes.as_slice()));
                            }
                            kill = None;
                        }
                    }
                    if let Some((name, after)) = &kick {
                        if started.elapsed() >= *after {
                            if let Some((key, _)) = names.iter().find(|(_, value)| *value == name) {
                                host.peer_mut(enet::PeerID(*key)).disconnect(77);
                            }
                            kick = None;
                        }
                    }
                    std::thread::sleep(Duration::from_millis(1));
                }
                inputs
            });
            Self {
                address,
                stop,
                handle: Some(handle),
            }
        }

        fn finish(mut self) -> HashMap<String, u64> {
            self.stop.store(true, Ordering::SeqCst);
            self.handle.take().unwrap().join().unwrap()
        }
    }

    impl Drop for MiniServer {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::SeqCst);
        }
    }

    fn temp_dir(label: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "omega-measured-{label}-{}-{:x}",
            std::process::id(),
            wall_ns()
        ));
        std::fs::create_dir_all(&path).unwrap();
        path
    }

    fn controls(server: &MiniServer, dir: &Path, bots: usize, hold_s: u64) -> Controls {
        Controls {
            server_text: server.address.to_string(),
            server: server.address,
            bots,
            threads: 4,
            stagger_ms: 20,
            behavior: BehaviorKind::Idle,
            difficulty: 1.0,
            input_hz: 30.0,
            seed: 1,
            hold_s,
            readiness_timeout_s: 8.0,
            bandwidth_budget: 0,
            evidence_dir: dir.join("swarm"),
            report_path: dir.join("report.json"),
            faults: Vec::new(),
        }
    }

    fn rows(dir: &Path, shard: usize) -> Vec<Value> {
        std::fs::read_to_string(dir.join("swarm").join(format!("shard-{shard}.ndjson")))
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect()
    }

    fn window(dir: &Path) -> Value {
        serde_json::from_str(&std::fs::read_to_string(dir.join("swarm/window.json")).unwrap())
            .unwrap()
    }

    fn name(id: u32) -> String {
        format!("LoadBot{id:03}")
    }

    #[test]
    fn four_shards_share_one_future_window_and_every_one_acknowledges_it() {
        let dir = temp_dir("complete");
        let server = MiniServer::start(Script::default());
        let code = run(
            controls(&server, &dir, 9, 1),
            Arc::new(AtomicBool::new(false)),
        );
        let inputs = server.finish();
        assert_eq!(code, 0);
        let document = window(&dir);
        assert_eq!(document["status"], "window_recorded");
        let (start, end) = (
            document["start_ns"].as_u64().unwrap(),
            document["end_ns"].as_u64().unwrap(),
        );
        assert_eq!(end - start, 1_000_000_000);
        let final_auth = document["final_auth_ns"].as_u64().unwrap();
        assert!(
            start >= final_auth + WARMUP_NS + PUBLISH_LEAD_NS,
            "warmup and lead both precede the start"
        );
        let mut owned = Vec::new();
        for (shard, ack) in document["acks"].as_array().unwrap().iter().enumerate() {
            assert!(
                ack["observed_ns"].as_u64().unwrap() < start,
                "the shard saw the window before it began"
            );
            assert!(ack["start_ack_ns"].as_u64().unwrap() >= start);
            assert!(ack["end_ack_ns"].as_u64().unwrap() >= end);
            let shard_rows = rows(&dir, shard);
            assert_eq!(shard_rows[0]["k"], "header");
            assert_eq!(shard_rows[0]["geometry"]["initialized_on_thread"], true);
            assert_eq!(shard_rows.last().unwrap()["k"], "footer");
            for (index, row) in shard_rows.iter().enumerate() {
                assert_eq!(row["seq"], index as u64, "contiguous numbering");
            }
            let freeze = shard_rows.iter().find(|row| row["k"] == "freeze").unwrap();
            for bot in freeze["bots"].as_array().unwrap() {
                let scheduled = bot["scheduled"].as_u64().unwrap();
                assert!((29..=31).contains(&scheduled), "{scheduled}");
                assert!(bot["sent"].as_u64().unwrap() <= scheduled);
                assert!(bot["sent"].as_u64().unwrap() >= scheduled - 1);
                owned.push((bot["id"].as_u64().unwrap() as usize - 1) % 4 == shard);
            }
            // The freeze comes before any drain row.
            let freeze_seq = freeze["seq"].as_u64().unwrap();
            let drain_seq = shard_rows
                .iter()
                .find(|row| row["k"] == "drain_start")
                .unwrap()["seq"]
                .as_u64()
                .unwrap();
            assert!(freeze_seq < drain_seq);
        }
        assert_eq!(owned.len(), 9);
        assert!(owned.iter().all(|ok| *ok), "round-robin ownership");
        assert_eq!(inputs.len(), 9, "every bot's input reached the server");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_delayed_final_auth_keeps_every_shard_polling_and_moves_the_window() {
        let dir = temp_dir("delayed");
        let mut script = Script::default();
        script
            .auth_delay
            .insert(name(5), Duration::from_millis(1500));
        let server = MiniServer::start(script);
        let code = run(
            controls(&server, &dir, 8, 1),
            Arc::new(AtomicBool::new(false)),
        );
        server.finish();
        assert_eq!(code, 0);
        let document = window(&dir);
        let final_auth = document["final_auth_ns"].as_u64().unwrap();
        assert!(final_auth >= 1_500_000_000, "{final_auth}");
        assert!(document["start_ns"].as_u64().unwrap() >= final_auth + WARMUP_NS);
        // Bot 6 joined after the delayed bot's slot, on its slot: no settling behind a slow bot.
        for shard in 0..4 {
            let shard_rows = rows(&dir, shard);
            for join in shard_rows.iter().filter(|row| row["k"] == "join") {
                let late = join["actual_ns"]
                    .as_u64()
                    .unwrap()
                    .saturating_sub(join["scheduled_ns"].as_u64().unwrap());
                assert!(late < 200_000_000, "stagger slipped by {late}");
            }
            // Other shards were polling throughout the barrier, not parked on it.
            let footer = shard_rows.last().unwrap();
            assert!(
                footer["max_poll_gap_ns"].as_u64().unwrap() < 400_000_000,
                "{footer}"
            );
        }
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_auth_that_never_arrives_is_a_readiness_timeout_with_no_window() {
        let dir = temp_dir("timeout");
        let mut script = Script::default();
        script.never_auth.push(name(2));
        let server = MiniServer::start(script);
        let mut config = controls(&server, &dir, 4, 1);
        config.readiness_timeout_s = 1.0;
        let code = run(config, Arc::new(AtomicBool::new(false)));
        server.finish();
        assert_eq!(code, 1);
        let document = window(&dir);
        assert_eq!(document["status"], "not_established");
        assert_eq!(document["reason"], "readiness_timeout");
        assert!(document["start_ns"].is_null());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_early_shard_exit_leaves_the_other_shards_running_and_no_end_ack() {
        let dir = temp_dir("exit");
        let server = MiniServer::start(Script::default());
        let mut config = controls(&server, &dir, 8, 2);
        config.faults = vec![Fault::ExitShard {
            shard: 1,
            anchor: Anchor::Window,
            offset_s: 0.5,
        }];
        let code = run(config, Arc::new(AtomicBool::new(false)));
        server.finish();
        assert_eq!(code, 1);
        let document = window(&dir);
        assert_eq!(document["status"], "window_incomplete");
        let acks = document["acks"].as_array().unwrap();
        assert!(
            acks[1]["end_ack_ns"].is_null(),
            "the shard that left never acknowledged the end"
        );
        for shard in [0usize, 2, 3] {
            assert!(acks[shard]["end_ack_ns"].as_u64().is_some());
        }
        assert_eq!(rows(&dir, 1).last().unwrap()["left_early"], true);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_starved_shard_records_its_gap_and_loses_its_scheduled_frames() {
        let dir = temp_dir("starve");
        let server = MiniServer::start(Script::default());
        let mut config = controls(&server, &dir, 8, 2);
        config.faults = vec![Fault::Starve {
            shard: 2,
            anchor: Anchor::Window,
            offset_s: 0.3,
            ms: 900,
        }];
        let code = run(config, Arc::new(AtomicBool::new(false)));
        server.finish();
        assert_eq!(
            code, 0,
            "the window was recorded; judging it belongs to the proof"
        );
        let starved = rows(&dir, 2);
        assert!(starved.last().unwrap()["max_poll_gap_ns"].as_u64().unwrap() >= 900_000_000);
        let freeze = starved.iter().find(|row| row["k"] == "freeze").unwrap();
        for bot in freeze["bots"].as_array().unwrap() {
            let (sent, scheduled) = (
                bot["sent"].as_u64().unwrap(),
                bot["scheduled"].as_u64().unwrap(),
            );
            assert!(sent * 100 < scheduled * 99, "{sent}/{scheduled}");
            assert!(bot["gap_max_ns"].as_u64().unwrap() >= 800_000_000);
        }
        // The other shards were never parked by it.
        let healthy = rows(&dir, 0);
        for bot in healthy.iter().find(|row| row["k"] == "freeze").unwrap()["bots"]
            .as_array()
            .unwrap()
        {
            assert!(bot["sent"].as_u64().unwrap() * 100 >= bot["scheduled"].as_u64().unwrap() * 96);
        }
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_muted_bot_stays_connected_and_its_missing_input_is_visible() {
        let dir = temp_dir("mute");
        let server = MiniServer::start(Script::default());
        let mut config = controls(&server, &dir, 4, 2);
        config.faults = vec![Fault::MuteBot {
            bot: 3,
            anchor: Anchor::Window,
            offset_s: 0.0,
        }];
        let code = run(config, Arc::new(AtomicBool::new(false)));
        server.finish();
        assert_eq!(code, 0);
        let freeze_rows = rows(&dir, 2);
        let freeze = freeze_rows.iter().find(|row| row["k"] == "freeze").unwrap();
        let bot = &freeze["bots"][0];
        assert_eq!(bot["id"], 3);
        assert_eq!(bot["phase"], "Running", "connected and polled");
        assert_eq!(bot["sent"], 0);
        assert!(bot["scheduled"].as_u64().unwrap() >= 59);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_dead_but_connected_bot_keeps_offering_idle_input() {
        let dir = temp_dir("dead");
        // Killed before the window opens, and nothing ever respawns it.
        let script = Script {
            kill_after: Some((name(3), Duration::from_millis(1000))),
            ..Default::default()
        };
        let server = MiniServer::start(script);
        let code = run(
            controls(&server, &dir, 4, 2),
            Arc::new(AtomicBool::new(false)),
        );
        server.finish();
        assert_eq!(code, 0);
        let rows = rows(&dir, 2);
        let bot = &rows.iter().find(|row| row["k"] == "freeze").unwrap()["bots"][0];
        assert_eq!(bot["id"], 3);
        assert_eq!(bot["alive"], false);
        assert_eq!(bot["phase"], "Running", "dead in the game, connected to it");
        let (sent, scheduled) = (
            bot["sent"].as_u64().unwrap(),
            bot["scheduled"].as_u64().unwrap(),
        );
        assert!(sent * 100 >= scheduled * 99, "{sent}/{scheduled}");
        assert_eq!(
            bot["dead_frames"].as_u64().unwrap(),
            sent,
            "every frame in the window was an idle one"
        );
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn a_server_disconnect_in_the_window_is_recorded_with_its_reason() {
        let dir = temp_dir("kick");
        // 4 bots at 20 ms, then 2 s warmup + 1 s lead: this lands inside the 3 s hold.
        let script = Script {
            kick_after: Some((name(2), Duration::from_millis(4500))),
            ..Default::default()
        };
        let server = MiniServer::start(script);
        let code = run(
            controls(&server, &dir, 4, 3),
            Arc::new(AtomicBool::new(false)),
        );
        server.finish();
        assert_eq!(code, 0);
        let document = window(&dir);
        assert_eq!(document["lost_after_auth"], 1);
        assert_eq!(document["lost_rows"][0]["bot"], 2);
        assert_eq!(document["lost_rows"][0]["disconnected"]["reason"], 77);
        assert_eq!(document["lost_rows"][0]["disconnected"]["expected"], false);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn existing_evidence_is_never_overwritten() {
        let dir = temp_dir("overwrite");
        std::fs::create_dir_all(dir.join("swarm")).unwrap();
        std::fs::write(dir.join("swarm/swarm.json"), "kept").unwrap();
        let server = MiniServer::start(Script::default());
        let code = run(
            controls(&server, &dir, 4, 1),
            Arc::new(AtomicBool::new(false)),
        );
        server.finish();
        assert_eq!(code, 4);
        assert_eq!(
            std::fs::read_to_string(dir.join("swarm/swarm.json")).unwrap(),
            "kept"
        );
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn an_interrupted_window_is_incomplete_not_complete() {
        let dir = temp_dir("interrupt");
        let server = MiniServer::start(Script::default());
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let setter = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(4200));
            flag.store(true, Ordering::SeqCst);
        });
        let code = run(controls(&server, &dir, 4, 10), stop);
        setter.join().unwrap();
        server.finish();
        assert_eq!(code, 1);
        let document = window(&dir);
        assert_eq!(document["status"], "window_incomplete");
        assert_eq!(document["reason"], "interrupted");
        std::fs::remove_dir_all(dir).unwrap();
    }
}
