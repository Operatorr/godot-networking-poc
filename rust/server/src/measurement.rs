//! Opt-in benchmark evidence. No wire or simulation changes; unset OMEGA_MEASURE_DIR
//! leaves collection disabled. I/O errors fail visibly rather than yielding valid-looking data.
use crate::world::World;
use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub const WINDOW_EVIDENCE_SCHEMA: &str = "omega.measurement/2";

/// One tight wall/monotonic pair in this process's own monotonic domain.
fn clock_pair(origin: Instant) -> serde_json::Value {
    let wall = || {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    };
    let before = wall();
    let mono = origin.elapsed().as_nanos();
    let after = wall();
    serde_json::json!({"wall_before_ns": before, "mono_ns": mono, "wall_after_ns": after})
}

/// The kernel's identity for this process where it exposes one; `null` otherwise, never a guess.
fn kernel_start_id() -> Option<String> {
    let text = std::fs::read_to_string("/proc/self/stat").ok()?;
    let rest = &text[text.rfind(')')? + 2..];
    Some(format!("ticks:{}", rest.split_whitespace().nth(19)?))
}

fn boot_id() -> Option<String> {
    std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
        .ok()
        .map(|text| text.trim().to_string())
}

/// Cumulative timing buckets: retain interval counts without averaging percentiles.
#[derive(Debug, Default, serde::Serialize)]
pub struct Timing {
    count: u64,
    total_ns: u128,
    max_ns: u128,
    buckets: [u64; 10],
}

pub const TIMING_BOUNDS_US: [u128; 9] = [100, 500, 1000, 5000, 10000, 20000, 33333, 50000, 100000];

impl Timing {
    pub fn record(&mut self, elapsed: std::time::Duration) {
        let ns = elapsed.as_nanos();
        self.count += 1;
        self.total_ns += ns;
        self.max_ns = self.max_ns.max(ns);
        let bucket = TIMING_BOUNDS_US
            .iter()
            .position(|bound| ns <= bound * 1000)
            .unwrap_or(9);
        self.buckets[bucket] += 1;
    }
}

#[derive(Default, serde::Serialize)]
pub struct LoopPhases {
    pub service_and_route: Timing,
    pub world_tick: Timing,
    /// Subset of `world_tick`: entity collection + per-peer Snapshot scheduling/encoding
    /// (`World::last_snapshot_build`). `world_tick - snapshot_build` is the pure simulation cost.
    pub snapshot_build: Timing,
    pub outbox_flush: Timing,
    pub enet_flush: Timing,
}

/// This process's cumulative CPU time and resident memory, read from procfs at 1 Hz so a run
/// report can say "the server used N% of one core" without an external sampler. Linux only;
/// other platforms report `None` and the report falls back to the host sampler.
#[derive(Debug, Default, serde::Serialize)]
pub struct ProcessSample {
    pub user_s: f64,
    pub system_s: f64,
    pub rss_bytes: u64,
    pub threads: u64,
}

/// ENet's own view of the connected peers at sample time: smoothed loss ratio and RTT per
/// peer (`enet_peer` throttle statistics), aggregated. A rising `loss_mean_pct` with flat
/// kernel counters on the client side means the SERVER is not receiving acks (receive-buffer
/// drops) and is retransmitting — the reliable-storm feedback loop.
#[derive(Debug, Default, serde::Serialize)]
pub struct EnetPeerStats {
    pub peers: u64,
    pub rtt_mean_ms: f64,
    pub rtt_max_ms: f64,
    pub loss_mean_pct: f64,
    pub loss_max_pct: f64,
    /// Instantaneous sums of ENet's per-peer interval counters (reset by ENet every
    /// `PEER_PACKET_LOSS_INTERVAL`); only the ratio of the two is meaningful.
    pub packets_sent_sum: u64,
    pub packets_lost_sum: u64,
}

pub fn process_sample() -> Option<ProcessSample> {
    #[cfg(target_os = "linux")]
    {
        let stat = std::fs::read_to_string("/proc/self/stat").ok()?;
        // Field 2 (comm) may contain spaces; everything after the closing paren is whitespace-split.
        let rest = &stat[stat.rfind(')')? + 2..];
        let fields: Vec<&str> = rest.split_whitespace().collect();
        // After `comm`, index 0 = state (field 3), so utime (14) is index 11, stime (15) is 12,
        // num_threads (20) is 17, rss pages (24) is 21.
        let ticks_per_s = 100.0; // CLK_TCK on every mainstream Linux
        let utime: f64 = fields.get(11)?.parse().ok()?;
        let stime: f64 = fields.get(12)?.parse().ok()?;
        let threads: u64 = fields.get(17)?.parse().ok()?;
        let rss_pages: u64 = fields.get(21)?.parse().ok()?;
        return Some(ProcessSample {
            user_s: utime / ticks_per_s,
            system_s: stime / ticks_per_s,
            rss_bytes: rss_pages * 4096,
            threads,
        });
    }
    #[allow(unreachable_code)]
    None
}

#[derive(Default)]
struct DeferredObservation {
    pending: std::collections::HashMap<usize, std::collections::HashMap<u16, u64>>,
    seen: std::collections::HashSet<u16>,
    peer: usize,
    tick: u64,
}

thread_local! {
    static DEFERRED: std::cell::RefCell<Option<DeferredObservation>> = const { std::cell::RefCell::new(None) };
}

pub fn begin_schedule(peer: usize, tick: u64) {
    DEFERRED.with(|slot| {
        if let Some(state) = &mut *slot.borrow_mut() {
            state.peer = peer;
            state.tick = tick;
            state.seen.clear();
        }
    });
}

pub fn observe_candidate(entity: u16, deferred: bool) {
    DEFERRED.with(|slot| {
        if let Some(state) = &mut *slot.borrow_mut() {
            let pending = state.pending.entry(state.peer).or_default();
            if deferred {
                state.seen.insert(entity);
                pending.entry(entity).or_insert(state.tick);
            } else {
                pending.remove(&entity);
            }
        }
    });
}

pub fn end_schedule() {
    DEFERRED.with(|slot| {
        if let Some(state) = &mut *slot.borrow_mut() {
            if let Some(pending) = state.pending.get_mut(&state.peer) {
                pending.retain(|entity, _| state.seen.contains(entity));
            }
        }
    });
}

pub fn remove_peer(peer: usize) {
    DEFERRED.with(|slot| {
        if let Some(state) = &mut *slot.borrow_mut() {
            state.pending.remove(&peer);
        }
    });
}

pub struct Measurement {
    pub loop_phases: LoopPhases,
    directory: std::path::PathBuf,
    boundaries: Vec<(String, u128)>,
    window_loaded: bool,
    ticks: BufWriter<File>,
    samples: BufWriter<File>,
    /// `OMEGA_MEASURE_WINDOW_EVIDENCE` only: create-only auth/disconnect transitions and clock pairs.
    population: Option<BufWriter<File>>,
    population_rows: u64,
    tick_rows: u64,
    last_tick: u64,
    epoch_ns: u128,
    origin: Instant,
    pub sent: [[u64; 3]; 256],
    pub received: [[u64; 3]; 256],
    pub send_errors: u64,
    pub decode_errors: u64,
    /// Every GameEvent packet handed to ENet, whatever its delivery.
    pub event_sends: [u64; 256],
    /// The reliable subset of `event_sends` (what costs command-queue and ack work).
    pub reliable_event_sends: [u64; 256],
    pub source_events: [u64; 256],
    pub baselines: u64,
    pub deltas: u64,
}

impl Measurement {
    pub fn from_env() -> Option<Self> {
        let directory = std::env::var_os("OMEGA_MEASURE_DIR")?;
        DEFERRED.with(|slot| *slot.borrow_mut() = Some(DeferredObservation::default()));
        std::fs::create_dir_all(&directory).expect("create measurement directory");
        let directory = std::path::Path::new(&directory);
        // Common-window evidence never replaces an earlier recorder's bytes. Historical campaign
        // units reuse one directory across restarts, so they keep today's behavior when this is unset.
        let window_evidence = std::env::var_os("OMEGA_MEASURE_WINDOW_EVIDENCE").is_some();
        let open = |name: &str| -> std::io::Result<File> {
            if window_evidence {
                OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(directory.join(name))
            } else {
                File::create(directory.join(name))
            }
        };
        if std::env::var_os("OMEGA_AOI_AUDIT").is_some() {
            let mut writer = BufWriter::with_capacity(
                1024 * 1024,
                File::create(directory.join("aoi.csv")).expect("create AoI audit"),
            );
            writeln!(
                writer,
                "tick,server_ms,observer,x,y,baseline,full_request,records,positions,max_distance"
            )
            .unwrap();
            AOI_AUDIT.with(|slot| *slot.borrow_mut() = Some(AoiAudit { writer, rows: 0 }));
        }
        let mut ticks = BufWriter::with_capacity(
            1024 * 1024,
            open("ticks.csv").expect("create raw Tick evidence"),
        );
        writeln!(ticks, "utc_ns,mono_ns,tick,work_ns,accumulator_lag_s,authenticated,alive,monsters,projectiles,effects,deferred,max_queue_age,budget_pct,peers_evaluated,overflow,mean_x,mean_y,mean_radius_sq,pending_replication,max_deferred_wait_ticks,observer_ns").unwrap();
        let origin = Instant::now();
        let mut population = None;
        if window_evidence {
            let mut process = open("process.json").expect("create process evidence");
            writeln!(
                process,
                "{}",
                serde_json::json!({
                    "schema": WINDOW_EVIDENCE_SCHEMA, "role": "game", "pid": std::process::id(),
                    "kernel_start_id": kernel_start_id(), "boot_id": boot_id(),
                    "clock": clock_pair(origin),
                })
            )
            .expect("write process evidence");
            process.sync_all().expect("sync process evidence");
            population = Some(BufWriter::with_capacity(
                64 * 1024,
                open("population.ndjson").expect("create population evidence"),
            ));
        }
        Some(Self {
            population,
            population_rows: 0,
            tick_rows: 0,
            last_tick: 0,
            loop_phases: LoopPhases::default(),
            directory: directory.to_path_buf(),
            boundaries: Vec::new(),
            window_loaded: false,
            ticks,
            samples: BufWriter::new(open("server.ndjson").expect("create server evidence")),
            epoch_ns: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            origin,
            sent: [[0; 3]; 256],
            received: [[0; 3]; 256],
            send_errors: 0,
            decode_errors: 0,
            event_sends: [0; 256],
            reliable_event_sends: [0; 256],
            source_events: [0; 256],
            baselines: 0,
            deltas: 0,
        })
    }

    pub fn tick(&mut self, world: &World, tick_start: Instant, work_ns: u128, lag: f64) {
        let observer = Instant::now();
        AOI_AUDIT.with(|slot| {
            if let Some(audit) = slot.borrow_mut().as_mut() {
                audit.writer.flush().expect("flush AoI audit");
            }
        });
        let mono = tick_start.duration_since(self.origin).as_nanos();
        let mut authenticated = 0;
        let mut alive = 0;
        let (mut x, mut y, mut radius_sq) = (0.0_f64, 0.0_f64, 0.0_f64);
        for player in &world.players.players {
            if player.authenticated {
                authenticated += 1;
                if player.is_alive {
                    alive += 1;
                    x += f64::from(player.position.x);
                    y += f64::from(player.position.y);
                    radius_sq += f64::from(player.position.length_squared());
                }
            }
        }
        let denominator = f64::from(alive.max(1));
        let diag = &world.broadcast.diagnostics;
        let (pending, max_wait) = DEFERRED.with(|slot| {
            let state = slot.borrow();
            let Some(state) = state.as_ref() else {
                return (0, 0);
            };
            (
                state
                    .pending
                    .values()
                    .map(|entries| entries.len())
                    .sum::<usize>(),
                state
                    .pending
                    .values()
                    .flat_map(|entries| entries.values())
                    .map(|first| world.tick_count.saturating_sub(*first))
                    .max()
                    .unwrap_or(0),
            )
        });
        write!(
            self.ticks,
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},",
            self.epoch_ns + mono,
            mono,
            world.tick_count,
            work_ns,
            lag,
            authenticated,
            alive,
            world.monsters.count(),
            world.projectiles.count(),
            world.world_entities.count(),
            diag.entities_deferred_per_tick,
            diag.max_queue_age_ticks,
            diag.peers_at_budget_pct,
            diag.peers_evaluated,
            diag.snapshot_count_overflow,
            x / denominator,
            y / denominator,
            radius_sq / denominator
        )
        .unwrap();
        write!(self.ticks, "{pending},{max_wait},").unwrap();
        writeln!(self.ticks, "{}", observer.elapsed().as_nanos()).unwrap();
        self.tick_rows += 1;
        self.last_tick = world.tick_count;
    }

    fn population_row(&mut self, mut row: serde_json::Value) {
        let mono = self.origin.elapsed().as_nanos();
        row["seq"] = serde_json::json!(self.population_rows);
        row["mono_ns"] = serde_json::json!(mono);
        if let Some(writer) = &mut self.population {
            writeln!(writer, "{row}").expect("write population evidence");
            self.population_rows += 1;
        }
    }

    /// An authoritative population transition, with the server's own count just after it.
    pub fn population_event(
        &mut self,
        world: &World,
        event: &str,
        peer: usize,
        identity: Option<(u16, &str)>,
        reason: Option<u32>,
    ) {
        if self.population.is_none() {
            return;
        }
        let authenticated = world
            .players
            .players
            .iter()
            .filter(|player| player.authenticated)
            .count();
        self.population_row(serde_json::json!({
            "k": event, "peer": peer, "tick": world.tick_count, "entity_id": identity.map(|i| i.0),
            "name": identity.map(|i| i.1), "reason": reason, "authenticated_after": authenticated,
        }));
        if let Some(writer) = &mut self.population {
            writer.flush().expect("flush population evidence");
        }
    }

    /// Everything durable, then a create-only count that exposes any later truncation.
    pub fn finish(&mut self, world: &World, peers_at_shutdown: usize) {
        if self.population.is_none() {
            return;
        }
        let clock = clock_pair(self.origin);
        self.population_row(serde_json::json!({"k": "footer", "clock": clock}));
        let sync = |writer: &mut BufWriter<File>, name: &str| {
            writer.flush().expect(name);
            writer.get_ref().sync_all().expect(name);
        };
        sync(
            self.population.as_mut().unwrap(),
            "sync population evidence",
        );
        sync(&mut self.ticks, "sync raw Tick evidence");
        sync(&mut self.samples, "sync server evidence");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.directory.join("final.json"))
            .expect("create final evidence");
        writeln!(
            file,
            "{}",
            serde_json::json!({
                "schema": WINDOW_EVIDENCE_SCHEMA, "tick_rows": self.tick_rows, "last_tick": self.last_tick,
                "world_tick": world.tick_count, "population_rows": self.population_rows,
                "peers_at_shutdown": peers_at_shutdown, "clock": clock,
            })
        )
        .expect("write final evidence");
        file.sync_all().expect("sync final evidence");
    }

    pub fn sample(
        &mut self,
        world: &World,
        transport: Option<&crate::net::transport::TransportObservation>,
        enet: &EnetPeerStats,
    ) {
        if !self.window_loaded {
            if let Ok(text) = std::fs::read_to_string(self.directory.join("window.json")) {
                let window: std::collections::BTreeMap<String, u128> =
                    serde_json::from_str(&text).expect("valid measurement window");
                self.boundaries = window.into_iter().collect();
                self.window_loaded = true;
            }
        }
        self.write_sample(world, "", transport, Some(enet));
    }

    pub fn check_boundaries(&mut self, world: &World) {
        let now = self.epoch_ns + self.origin.elapsed().as_nanos();
        let due: Vec<_> = self
            .boundaries
            .iter()
            .filter(|(_, stamp)| *stamp <= now)
            .map(|(name, _)| name.clone())
            .collect();
        self.boundaries.retain(|(_, stamp)| *stamp > now);
        for name in due {
            self.write_sample(world, &name, None, None);
        }
    }

    fn write_sample(
        &mut self,
        world: &World,
        boundary: &str,
        transport: Option<&crate::net::transport::TransportObservation>,
        enet: Option<&EnetPeerStats>,
    ) {
        if self.population.is_some() {
            let clock = clock_pair(self.origin);
            self.population_row(
                serde_json::json!({"k": "clock", "clock": clock, "tick": world.tick_count}),
            );
            if let Some(writer) = &mut self.population {
                writer.flush().expect("flush population evidence");
            }
        }
        let mono = self.origin.elapsed().as_nanos();
        let bytes = |counts: &[[u64; 3]; 256]| {
            counts
                .iter()
                .enumerate()
                .filter(|(_, values)| values.iter().any(|v| *v > 0))
                .map(|(kind, values)| serde_json::json!([kind, values]))
                .collect::<Vec<_>>()
        };
        let positions: Vec<_> = world
            .players
            .players
            .iter()
            .filter(|p| p.authenticated)
            .map(|p| serde_json::json!([p.entity_id, p.is_alive, p.position.x, p.position.y]))
            .collect();
        writeln!(self.samples, "{}", serde_json::json!({
            "utc_ns": self.epoch_ns + mono, "mono_ns": mono,
            "boundary": boundary,
            "timing_bounds_us": TIMING_BOUNDS_US, "loop_phases": self.loop_phases,
            "transport": transport,
            "enet": enet,
            "process": process_sample(),
            "tick": world.tick_count,
            "sent_bytes_by_type_channel": bytes(&self.sent), "received_bytes_by_type_channel": bytes(&self.received),
            "send_errors": self.send_errors, "decode_errors": self.decode_errors,
            "event_sends": self.event_sends.as_slice(),
            "reliable_event_sends": self.reliable_event_sends.as_slice(), "baselines": self.baselines, "deltas": self.deltas,
            "source_events": self.source_events.as_slice(),
            "players": positions,
        })).unwrap();
        self.samples.flush().unwrap();
        self.ticks.flush().unwrap();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deferred_wait_starts_at_first_deferral_and_clears_on_admission_or_cull() {
        DEFERRED.with(|slot| *slot.borrow_mut() = Some(DeferredObservation::default()));
        begin_schedule(7, 5000);
        observe_candidate(30001, true);
        end_schedule();
        begin_schedule(7, 5001);
        observe_candidate(30001, true);
        end_schedule();
        DEFERRED.with(|slot| assert_eq!(slot.borrow().as_ref().unwrap().pending[&7][&30001], 5000));
        begin_schedule(7, 5002);
        observe_candidate(30001, false);
        observe_candidate(30002, true);
        end_schedule();
        DEFERRED.with(|slot| {
            assert!(!slot.borrow().as_ref().unwrap().pending[&7].contains_key(&30001))
        });
        begin_schedule(7, 5003);
        end_schedule();
        DEFERRED.with(|slot| assert!(slot.borrow().as_ref().unwrap().pending[&7].is_empty()));
    }
}

// Opt-in, bounded same-Tick AoI evidence. One row per constructed Snapshot, so
// an omitted observer record never has to be reconstructed from another Tick.
// Enabled alongside OMEGA_MEASURE_DIR only for this diagnostic condition.
thread_local! {
    static AOI_AUDIT: std::cell::RefCell<Option<AoiAudit>> = const { std::cell::RefCell::new(None) };
}
struct AoiAudit {
    writer: BufWriter<File>,
    rows: u64,
}

pub(crate) fn aoi_packet_bounds(
    snapshot: &protocol::Snapshot,
    observer: u16,
    center: sim_core::Vec2,
) -> (u64, f32) {
    let mut count = 0;
    let mut maximum = 0.0_f32;
    for r in &snapshot.entities {
        if r.entity_id == observer {
            continue;
        }
        if let Some((x, y)) = r.position {
            // Use the coordinates the receiver actually decodes, including truncation.
            let wire = sim_core::Vec2::new(
                protocol::dequant_coord(protocol::quant_coord(x)),
                protocol::dequant_coord(protocol::quant_coord(y)),
            );
            maximum = maximum.max(center.distance_to(wire));
            count += 1;
        }
    }
    (count, maximum)
}

pub fn audit_aoi_snapshot(
    snapshot: &protocol::Snapshot,
    observer: u16,
    center: sim_core::Vec2,
    full_request: bool,
) {
    AOI_AUDIT.with(|slot| {
        let mut slot = slot.borrow_mut();
        let Some(audit) = slot.as_mut() else {
            return;
        };
        assert!(
            audit.rows < 2_000_000,
            "AoI audit row bound exhausted; observation invalid"
        );
        let (count, maximum) = aoi_packet_bounds(snapshot, observer, center);
        writeln!(
            audit.writer,
            "{},{},{},{},{},{},{},{},{},{}",
            snapshot.server_tick,
            snapshot.server_ms,
            observer,
            center.x,
            center.y,
            snapshot.is_baseline,
            full_request,
            snapshot.entities.len(),
            count,
            maximum
        )
        .expect("write AoI audit");
        audit.rows += 1;
    });
}
