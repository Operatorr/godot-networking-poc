//! Omega Realm load-testing bot swarm — Rust port of `load_testing/bot_swarm.py` for the
//! ENet/UDP server. Links the `protocol` crate directly (zero codec drift) and predicts bot
//! movement with `sim_core` (zero sim drift).
//!
//! Usage:
//!   omega-load-test --scenario baseline
//!   omega-load-test --bots 75 --duration 120 --server 10.0.0.1:8081
//!
//! The server must be running (`./scripts/run_server.sh`) with unsigned tickets allowed
//! (the dev default) — bots authenticate ticket-less.

mod assertions;
mod behavior;
mod bot;
mod metrics;
mod rng;
mod ticket;

use behavior::{BehaviorKind, VALID_BEHAVIORS};
use bot::{Bot, Phase};
use serde_json::{json, Value};
use std::net::{SocketAddr, ToSocketAddrs};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use ticket::{TicketClient, SYNTHETIC_ID_BASE};
use tracing::{error, info, warn};

struct Scenario {
    name: &'static str,
    bots: usize,
    duration: u64,
    behavior: BehaviorKind,
    description: &'static str,
}

const SCENARIOS: &[Scenario] = &[
    Scenario {
        name: "baseline",
        bots: 50,
        duration: 120,
        behavior: BehaviorKind::Default,
        description: "Baseline validation (50 bots, 2 min)",
    },
    Scenario {
        name: "target",
        bots: 100,
        duration: 300,
        behavior: BehaviorKind::Default,
        description: "Target load validation (100 bots, 5 min)",
    },
    Scenario {
        name: "stress",
        bots: 200,
        duration: 300,
        behavior: BehaviorKind::Default,
        description: "Stress test / find breaking point (200 bots, 5 min)",
    },
    Scenario {
        name: "idle",
        bots: 100,
        duration: 120,
        behavior: BehaviorKind::Idle,
        description: "Idle baseline (100 connected bots, 2 min)",
    },
    Scenario {
        name: "movement",
        bots: 100,
        duration: 120,
        behavior: BehaviorKind::Movement,
        description: "Movement throughput (100 bots moving, 2 min)",
    },
    Scenario {
        name: "combat",
        bots: 100,
        duration: 120,
        behavior: BehaviorKind::Combat,
        description: "Combat stress (100 bots constant shooting, 2 min)",
    },
    Scenario {
        name: "clustered",
        bots: 100,
        duration: 120,
        behavior: BehaviorKind::Clustered,
        description: "AoI worst case (100 bots clustered, 2 min)",
    },
    Scenario {
        name: "strategy",
        bots: 10,
        duration: 0,
        behavior: BehaviorKind::Strategy,
        description: "Gameplay bots (10 bots, run until stopped)",
    },
];

const USAGE: &str = "\
Omega Realm Load Testing Bot Swarm (ENet/Rust)

USAGE:
    omega-load-test [OPTIONS]

OPTIONS:
    -s, --server <HOST:PORT>   Game server address (default: 127.0.0.1:8081)
    -b, --bots <N>             Number of bots to spawn
    -d, --duration <SECS>      Test duration in seconds (0 = run until Ctrl-C)
        --scenario <NAME>      baseline | target | stress | idle | movement |
                               combat | clustered | strategy
        --stagger <MS>         Milliseconds between bot connections (default: 100)
        --behavior <NAME>      default | idle | movement | combat | clustered | strategy
        --difficulty <0..1>    Bot tactical difficulty (default: 1.0)
        --input-hz <HZ>        Input send rate (default: 30, like the real client)
        --bandwidth-budget <BPS>  Advertised per-peer budget in ConnectAuth (0 = server default)
        --seed <U64>           Seed bots as (seed ^ bot_id) for reproducible runs (default: entropy)
    -o, --output <PATH>        JSON report path (default: report_<timestamp>.json)
        --no-report            Skip the JSON report and success-criteria exit code
        --assertions <MODE>    strict | warn | off — regression assertions (default: warn)
        --rate-budget <BPS>    Bytes/sec gate for the per-peer-budget assertion (0 skips)
        --aoi-exit-radius <U>  AoI cull assertion radius (default: 1100)
        --ticket-api-url <URL> API origin for signed-ticket auth (env: OMEGA_TICKET_API).
                               Set with --ticket-secret to join a fail-closed server; unset =
                               ticket-less (server must allow unsigned). e.g. https://host
        --ticket-secret <TOK>  Load-test ticket-endpoint secret (env: OMEGA_LOAD_TEST_SECRET)
        --region <NAME>        Region the minted tickets pin (default: asia; must match server)
    -v, --verbose              Debug logging
    -h, --help                 This help

SCENARIOS:
    baseline  - 50 bots, 2 minutes (validate basic functionality)
    target    - 100 bots, 5 minutes (validate success metrics)
    stress    - 200 bots, 5 minutes (find breaking point; needs max_players >= 200)
    strategy  - 10 gameplay bots, run until interrupted

EXAMPLES:
    omega-load-test --scenario baseline
    omega-load-test --scenario strategy --no-report
    omega-load-test --bots 75 --duration 120 --server 10.0.0.1:8081
";

struct Args {
    server: String,
    bots: Option<usize>,
    duration: Option<u64>,
    scenario: Option<&'static Scenario>,
    stagger_ms: f64,
    output: Option<String>,
    behavior: Option<BehaviorKind>,
    difficulty: f64,
    input_hz: f64,
    bandwidth_budget: u32,
    /// When set, bots are seeded `seed ^ bot_id` for reproducible swarm runs; unset = entropy.
    seed: Option<u64>,
    no_report: bool,
    assertions: AssertionMode,
    rate_budget: u64,
    aoi_exit_radius: f64,
    verbose: bool,
    /// API origin for signed-ticket auth (e.g. `https://gsapi.marrowtech.app`). When set with
    /// `ticket_secret`, each bot fetches a real ticket and joins authenticated; unset = the
    /// ticket-less dev path (server must allow unsigned). Env fallback: `OMEGA_TICKET_API`.
    ticket_api_url: Option<String>,
    /// Shared secret for the load-test ticket endpoint. Env fallback: `OMEGA_LOAD_TEST_SECRET`.
    ticket_secret: Option<String>,
    /// Region the minted tickets pin; must match the target instance (else `WRONG_REGION`).
    region: String,
}

#[derive(PartialEq, Clone, Copy)]
enum AssertionMode {
    Strict,
    Warn,
    Off,
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args {
        server: "127.0.0.1:8081".into(),
        bots: None,
        duration: None,
        scenario: None,
        stagger_ms: 100.0,
        output: None,
        behavior: None,
        difficulty: 1.0,
        input_hz: 30.0,
        bandwidth_budget: 0,
        seed: None,
        no_report: false,
        assertions: AssertionMode::Warn,
        rate_budget: 0,
        aoi_exit_radius: 1100.0,
        verbose: false,
        // Default from env so the wrapper script and bare invocations agree; --flags override below.
        ticket_api_url: std::env::var("OMEGA_TICKET_API")
            .ok()
            .filter(|s| !s.is_empty()),
        ticket_secret: std::env::var("OMEGA_LOAD_TEST_SECRET")
            .ok()
            .filter(|s| !s.is_empty()),
        region: "asia".into(),
    };
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    let value = |i: &mut usize| -> Result<String, String> {
        *i += 1;
        argv.get(*i)
            .cloned()
            .ok_or_else(|| format!("{} expects a value", argv[*i - 1]))
    };
    while i < argv.len() {
        match argv[i].as_str() {
            "--server" | "-s" => args.server = value(&mut i)?,
            "--bots" | "-b" => {
                args.bots = Some(value(&mut i)?.parse().map_err(|e| format!("--bots: {e}"))?)
            }
            "--duration" | "-d" => {
                args.duration = Some(
                    value(&mut i)?
                        .parse()
                        .map_err(|e| format!("--duration: {e}"))?,
                )
            }
            "--scenario" => {
                let name = value(&mut i)?;
                args.scenario = Some(
                    SCENARIOS
                        .iter()
                        .find(|s| s.name == name)
                        .ok_or_else(|| format!("unknown scenario '{name}'"))?,
                );
            }
            "--stagger" => {
                args.stagger_ms = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--stagger: {e}"))?
            }
            "--output" | "-o" => args.output = Some(value(&mut i)?),
            "--behavior" => {
                let name = value(&mut i)?;
                args.behavior = Some(BehaviorKind::parse(&name).ok_or_else(|| {
                    format!(
                        "unknown behavior '{name}' (valid: {})",
                        VALID_BEHAVIORS.join(", ")
                    )
                })?);
            }
            "--difficulty" => {
                let d: f64 = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--difficulty: {e}"))?;
                if !d.is_finite() {
                    return Err(format!(
                        "--difficulty: must be a finite number in 0..1 (got {d})"
                    ));
                }
                args.difficulty = d;
            }
            "--input-hz" => {
                args.input_hz = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--input-hz: {e}"))?
            }
            "--bandwidth-budget" => {
                args.bandwidth_budget = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--bandwidth-budget: {e}"))?
            }
            "--seed" => {
                args.seed = Some(value(&mut i)?.parse().map_err(|e| format!("--seed: {e}"))?)
            }
            "--no-report" => args.no_report = true,
            "--assertions" => {
                args.assertions = match value(&mut i)?.as_str() {
                    "strict" => AssertionMode::Strict,
                    "warn" => AssertionMode::Warn,
                    "off" => AssertionMode::Off,
                    other => return Err(format!("--assertions: unknown mode '{other}'")),
                }
            }
            "--rate-budget" => {
                args.rate_budget = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--rate-budget: {e}"))?
            }
            "--aoi-exit-radius" => {
                args.aoi_exit_radius = value(&mut i)?
                    .parse()
                    .map_err(|e| format!("--aoi-exit-radius: {e}"))?
            }
            "--ticket-api-url" => args.ticket_api_url = Some(value(&mut i)?),
            "--ticket-secret" => args.ticket_secret = Some(value(&mut i)?),
            "--region" => args.region = value(&mut i)?,
            "--verbose" | "-v" => args.verbose = true,
            "--help" | "-h" => {
                print!("{USAGE}");
                std::process::exit(0);
            }
            other => return Err(format!("unknown argument '{other}' (see --help)")),
        }
        i += 1;
    }
    args.difficulty = args.difficulty.clamp(0.0, 1.0);
    Ok(args)
}

/// Accept bare `host:port` plus old muscle-memory schemes (`ws://`, `udp://`, `enet://`).
fn resolve_server(server: &str) -> Result<SocketAddr, String> {
    let stripped = server
        .trim_start_matches("ws://")
        .trim_start_matches("udp://")
        .trim_start_matches("enet://");
    stripped
        .to_socket_addrs()
        .map_err(|e| format!("cannot resolve '{stripped}': {e}"))?
        .next()
        .ok_or_else(|| format!("'{stripped}' resolved to no addresses"))
}

fn main() {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("error: {e}\n\n{USAGE}");
            std::process::exit(2);
        }
    };
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| {
                tracing_subscriber::EnvFilter::new(if args.verbose { "debug" } else { "info" })
            }),
        )
        .init();

    let (bot_count, duration, behavior) = match args.scenario {
        Some(s) => {
            info!("Scenario: {} - {}", s.name, s.description);
            (
                args.bots.unwrap_or(s.bots),
                args.duration.unwrap_or(s.duration),
                args.behavior.unwrap_or(s.behavior),
            )
        }
        None => (
            args.bots.unwrap_or(50),
            args.duration.unwrap_or(120),
            args.behavior.unwrap_or(BehaviorKind::Default),
        ),
    };
    let server_addr = match resolve_server(&args.server) {
        Ok(a) => a,
        Err(e) => {
            error!("{e}");
            std::process::exit(2);
        }
    };

    // Initialize the sim's world geometry on this (single) thread before any bot steps
    // `sim_core`. The swarm is single-threaded — every bot's `step_movement` runs here on main —
    // so one call configures them all. Without it, a debug build would `debug_assert!` on the
    // first geometry read; release silently falls back to the same Arena default. The load test
    // exercises the Arena instance (see README), so the Arena geometry is the correct match.
    sim_core::set_world_geometry(
        sim_core::ARENA_GEOMETRY.min,
        sim_core::ARENA_GEOMETRY.max,
        sim_core::ARENA_GEOMETRY.obstacles_enabled,
    );

    let stop = Arc::new(AtomicBool::new(false));
    {
        let stop = stop.clone();
        if let Err(e) = ctrlc::set_handler(move || stop.store(true, Ordering::SeqCst)) {
            warn!("failed to install Ctrl-C handler: {e}");
        }
    }

    let start = Instant::now();
    let now = || start.elapsed().as_secs_f64();
    info!(
        "Starting load test: {bot_count} bots, {} duration, behavior={}, difficulty={:.2}, server={}",
        if duration == 0 { "until interrupted".into() } else { format!("{duration}s") },
        behavior.name(),
        args.difficulty,
        args.server
    );

    // Each bot owns one UDP socket (one file descriptor), so a 1000-bot swarm needs ~1000+ fds.
    // A low `ulimit -n` (macOS defaults to 256) makes binds fail mid-spawn, surfacing only as
    // per-bot "failed to start". Warn loudly up front so the cause isn't misread. We have no
    // `libc` dependency to read the live soft limit cheaply, so this is a static heuristic plus a
    // pointer to raise it.
    if bot_count >= 200 {
        warn!(
            "Spawning {bot_count} bots — each needs its own UDP socket (file descriptor). If bots \
             fail to start mid-spawn, raise the open-file limit first: `ulimit -n {}` (macOS \
             defaults to 256).",
            (bot_count + 256).next_power_of_two()
        );
    }

    // ── Phase 1: spawn bots (staggered, sequential settle like the Python harness) ─────────
    // Note: the spawn loop settles each new bot by polling EVERY bot already up (O(n²) overall),
    // and the whole swarm runs on this single thread over blocking ENet polling. The load
    // generator is therefore CPU-bound on one core past a few hundred bots — at high counts a low
    // client-side tick rate is the generator saturating, not the server; read results accordingly.
    // Signed-ticket auth. The API URL is the TRIGGER (set by --live, or --ticket-api-url /
    // OMEGA_TICKET_API): present + a secret ⇒ each bot fetches a real Ed25519 ticket (for a
    // synthetic character_id) and joins authenticated, as a fail-closed server requires. No URL
    // ⇒ ticket-less (the dev/unsigned path) EVEN IF a stray OMEGA_LOAD_TEST_SECRET lingers in the
    // env — so persisting that secret in ~/.zshrc doesn't break local, unsigned runs. A URL with
    // no secret is a real misconfiguration (you meant to authenticate) — fail loud.
    let ticket_client = match (&args.ticket_api_url, &args.ticket_secret) {
        (Some(url), Some(secret)) => {
            info!(
                "Signed-ticket auth ENABLED via {url} (region={})",
                args.region
            );
            Some(TicketClient::new(url, secret.clone(), args.region.clone()))
        }
        (Some(_), None) => {
            error!(
                "ticket auth: --ticket-api-url / OMEGA_TICKET_API is set but no \
                 --ticket-secret / OMEGA_LOAD_TEST_SECRET — cannot mint tickets"
            );
            std::process::exit(2);
        }
        (None, _) => None,
    };

    info!("Phase 1: Spawning bots...");
    let mut bots: Vec<Bot> = Vec::with_capacity(bot_count);
    let mut stillborn: Vec<metrics::BotMetrics> = Vec::new();
    for i in 0..bot_count {
        if stop.load(Ordering::SeqCst) {
            break;
        }
        // Authenticated runs mint one ticket per bot just before connect (well within the
        // API's short TTL). A fetch failure makes that bot stillborn; the swarm continues.
        let bot_ticket = if let Some(tc) = &ticket_client {
            let character_id = SYNTHETIC_ID_BASE + i as u32 + 1;
            match tc.fetch(character_id) {
                Ok(t) => Some(t),
                Err(e) => {
                    warn!("Bot {} ticket fetch failed: {e}", i + 1);
                    stillborn.push(metrics::BotMetrics {
                        bot_id: i as u32 + 1,
                        behavior: behavior.name(),
                        error_count: 1,
                        last_error: format!("ticket fetch failed: {e}"),
                        ..Default::default()
                    });
                    continue;
                }
            }
        } else {
            None
        };
        match Bot::connect(
            i as u32 + 1,
            server_addr,
            behavior,
            args.difficulty,
            args.input_hz,
            args.bandwidth_budget,
            args.seed,
            bot_ticket,
            now(),
        ) {
            Ok(b) => bots.push(b),
            Err(e) => {
                warn!("Bot {} failed to start: {e}", i + 1);
                stillborn.push(metrics::BotMetrics {
                    bot_id: i as u32 + 1,
                    behavior: behavior.name(),
                    error_count: 1,
                    last_error: e.to_string(),
                    ..Default::default()
                });
                continue;
            }
        }
        // Settle this bot (poll everyone meanwhile), then stagger before the next connect.
        let idx = bots.len() - 1;
        while !bots[idx].is_settled() && !stop.load(Ordering::SeqCst) {
            poll_all(&mut bots, now());
            std::thread::sleep(Duration::from_millis(1));
        }
        if bots[idx].phase == Phase::Failed {
            warn!(
                "Bot {} failed to connect: {}",
                i + 1,
                bots[idx].metrics.last_error
            );
        }
        let connected = bots.iter().filter(|b| b.phase == Phase::Running).count();
        if (i + 1) % 10 == 0 {
            info!("Connected {connected}/{} bots...", i + 1);
        }
        let stagger_until = now() + args.stagger_ms / 1000.0;
        while now() < stagger_until && !stop.load(Ordering::SeqCst) {
            poll_all(&mut bots, now());
            std::thread::sleep(Duration::from_millis(1));
        }
    }
    let connected = bots.iter().filter(|b| b.phase == Phase::Running).count();
    info!(
        "Spawned {} bots, {connected} connected successfully",
        bots.len() + stillborn.len()
    );

    // ── Phase 2: run ────────────────────────────────────────────────────────────────────────
    let mut time_series: Vec<Value> = Vec::new();
    let run_started = now();
    if connected == 0 {
        error!("No bots connected! Aborting test.");
    } else {
        info!(
            "Phase 2: Running test for {} with {connected} bots...",
            if duration == 0 {
                "until interrupted".into()
            } else {
                format!("{duration} seconds")
            }
        );
        let mut next_sample_at = run_started + 5.0;
        while !stop.load(Ordering::SeqCst)
            && (duration == 0 || now() - run_started < duration as f64)
        {
            poll_all(&mut bots, now());
            if now() >= next_sample_at {
                next_sample_at += 5.0;
                time_series.push(sample_time_series(&bots, now() - run_started));
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        if stop.load(Ordering::SeqCst) {
            info!("Interrupted; disconnecting bots...");
        }
    }

    // ── Phase 3: disconnect + collect ───────────────────────────────────────────────────────
    info!("Phase 3: Collecting metrics...");
    let t = now();
    for b in &mut bots {
        b.begin_disconnect(t);
    }
    let drain_deadline = now() + 1.5;
    while now() < drain_deadline && bots.iter().any(|b| !b.is_terminal()) {
        poll_all(&mut bots, now());
        std::thread::sleep(Duration::from_millis(1));
    }
    for b in &mut bots {
        b.force_close();
    }

    let elapsed = now() - run_started;
    let effective_duration = if duration > 0 && !stop.load(Ordering::SeqCst) {
        duration as f64
    } else {
        elapsed
    };
    let all_metrics: Vec<&metrics::BotMetrics> = bots
        .iter()
        .map(|b| &b.metrics)
        .chain(stillborn.iter())
        .collect();
    let agg = metrics::aggregate(all_metrics.iter().copied(), effective_duration);

    let assertion_results = if args.assertions == AssertionMode::Off {
        Vec::new()
    } else {
        let cfg = assertions::AssertionConfig {
            aoi_exit_radius: args.aoi_exit_radius,
            rate_budget_bytes_per_sec: args.rate_budget,
        };
        assertions::run_all(&all_metrics, effective_duration, &cfg)
    };

    let unix_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    if args.no_report {
        if !assertion_results.is_empty() {
            println!("{}", assertions::format_results(&assertion_results));
        }
        if agg.connected_bots == 0 {
            std::process::exit(1);
        }
        if args.assertions == AssertionMode::Strict && assertion_results.iter().any(|r| !r.passed) {
            std::process::exit(2);
        }
        return;
    }

    println!(
        "{}",
        metrics::generate_report(&agg, &args.server, unix_secs)
    );
    if !assertion_results.is_empty() {
        println!("{}\n", assertions::format_results(&assertion_results));
    }

    let per_bot: Vec<Value> = all_metrics.iter().map(|m| m.summary()).collect();
    let report = metrics::report_json(
        &agg,
        per_bot,
        &args.server,
        unix_secs,
        &time_series,
        &assertion_results,
    );
    let output_path = args
        .output
        .unwrap_or_else(|| format!("report_{}.json", metrics::compact_timestamp(unix_secs)));
    match serde_json::to_string_pretty(&report) {
        Ok(json) => match std::fs::write(&output_path, json) {
            Ok(()) => info!("JSON report saved to: {output_path}"),
            Err(e) => error!("failed to write {output_path}: {e}"),
        },
        Err(e) => error!("failed to serialize report JSON: {e}"),
    }

    let all_passed = metrics::evaluate_success(&agg).iter().all(|c| c.passed);
    if args.assertions == AssertionMode::Strict && assertion_results.iter().any(|r| !r.passed) {
        std::process::exit(2);
    }
    std::process::exit(if all_passed { 0 } else { 1 });
}

fn poll_all(bots: &mut [Bot], now: f64) {
    for b in bots.iter_mut() {
        // Per-bot panic boundary: a panic inside one bot's poll (a decode/sim/ENet edge case)
        // must not unwind through the swarm and kill every other bot. Catch it, mark that one bot
        // crashed (counted in the crash metric), and keep going. `&mut Bot` isn't `UnwindSafe`,
        // but a caught panic only ever sends the bot terminal, so asserting unwind-safety is sound.
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| b.poll(now)));
        if let Err(payload) = result {
            let msg = panic_message(payload.as_ref());
            error!("bot {} panicked in poll: {msg}", b.id);
            b.mark_crashed(format!("panic in poll: {msg}"));
        }
    }
}

/// Best-effort extraction of a panic payload's message (`&str` / `String` cases).
fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        "non-string panic payload".to_string()
    }
}

fn sample_time_series(bots: &[Bot], elapsed: f64) -> Value {
    let connected = bots.iter().filter(|b| b.phase == Phase::Running).count();
    let bytes_sent: u64 = bots.iter().map(|b| b.metrics.bytes_sent).sum();
    let bytes_received: u64 = bots.iter().map(|b| b.metrics.bytes_received).sum();
    let state_updates: u64 = bots.iter().map(|b| b.metrics.state_updates_received).sum();
    // Recent latency picture: the last 10 RTT samples of every bot.
    let recent: Vec<f64> = bots
        .iter()
        .flat_map(|b| b.metrics.latencies_ms.iter().rev().take(10).copied())
        .collect();
    let mut snap = json!({
        "elapsed_seconds": (elapsed * 10.0).round() / 10.0,
        "connected_bots": connected,
        "total_bytes_sent": bytes_sent,
        "total_bytes_received": bytes_received,
        "total_state_updates": state_updates,
    });
    if !recent.is_empty() {
        let avg = recent.iter().sum::<f64>() / recent.len() as f64;
        snap["latency_avg_ms"] = json!((avg * 10.0).round() / 10.0);
        snap["latency_p95_ms"] = json!((metrics::percentile(&recent, 0.95) * 10.0).round() / 10.0);
    }
    if let Some((_, sm)) = bots
        .iter()
        .filter_map(|b| b.metrics.latest_server_metrics.as_ref())
        .max_by(|a, b| a.0.total_cmp(&b.0))
    {
        snap["server_avg_tick_time_ms"] = json!(sm.avg_tick_time_ms_x100 as f64 / 100.0);
        snap["server_entity_count"] = json!(sm.entity_count);
    }
    info!(
        "[{:.0}s] bots={connected} bytes_recv={bytes_received} state_updates={state_updates}",
        elapsed
    );
    snap
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scenarios_match_the_python_harness() {
        let names: Vec<&str> = SCENARIOS.iter().map(|s| s.name).collect();
        assert_eq!(
            names,
            [
                "baseline",
                "target",
                "stress",
                "idle",
                "movement",
                "combat",
                "clustered",
                "strategy"
            ]
        );
        let baseline = &SCENARIOS[0];
        assert_eq!((baseline.bots, baseline.duration), (50, 120));
        let stress = &SCENARIOS[2];
        assert_eq!((stress.bots, stress.duration), (200, 300));
    }

    #[test]
    fn server_schemes_are_stripped() {
        assert_eq!(
            resolve_server("ws://127.0.0.1:8081").unwrap(),
            "127.0.0.1:8081".parse().unwrap()
        );
        assert_eq!(
            resolve_server("127.0.0.1:8081").unwrap(),
            "127.0.0.1:8081".parse().unwrap()
        );
        assert!(resolve_server("definitely-not-a-host:99999").is_err());
    }
}
