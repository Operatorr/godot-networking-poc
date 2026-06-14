//! Omega Realm authoritative game server — one process = one Instance (migration-spec D13).
//!
//! The main thread IS the tick thread (D8): a fixed 30 Hz accumulator loop over a non-blocking
//! `rusty_enet` host. ENet is serviced in ~1 ms slices so acks/retransmits stay timely between
//! ticks (extraction rust-stack §1); messages are processed in arrival order between ticks,
//! matching the GDScript's frame-loop handler semantics.

mod config;
mod net;
mod sim;

// The sim/ and net/ subdirectories group the subsystems physically; the rest of the
// crate still refers to them flat (crate::player, crate::broadcast, …) via these
// re-exports, so module moves don't churn every `crate::…` path.
pub(crate) use net::{api_client, auth, broadcast, metrics, outbox, progression_client};
pub(crate) use sim::{
    ability, combat, leaderboard, monster, player, projectile, rng, world, world_entity,
};

use config::ServerConfig;
use outbox::{Outbox, Target};
use protocol::{ClientPacket, ServerPacket};
use rusty_enet as enet;
use std::collections::HashSet;
use std::net::UdpSocket;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{info, warn};

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let args: Vec<String> = std::env::args().collect();
    let mut config_path: Option<PathBuf> = None;
    let mut allow_unsigned_override: Option<bool> = None;
    let mut mode_override: Option<String> = None;
    let mut port_override: Option<u16> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--config" if i + 1 < args.len() => {
                config_path = Some(PathBuf::from(&args[i + 1]));
                i += 1;
            }
            "--mode" if i + 1 < args.len() => {
                mode_override = Some(args[i + 1].clone());
                i += 1;
            }
            "--port" if i + 1 < args.len() => {
                match args[i + 1].parse::<u16>() {
                    Ok(p) if p != 0 => port_override = Some(p),
                    _ => {
                        eprintln!(
                            "fatal: --port '{}' is not a valid port (1..=65535)",
                            args[i + 1]
                        );
                        std::process::exit(2);
                    }
                }
                i += 1;
            }
            "--allow-unsigned-tickets" => allow_unsigned_override = Some(true),
            "--require-tickets" => allow_unsigned_override = Some(false),
            other => warn!("unknown argument '{other}' ignored"),
        }
        i += 1;
    }
    // Default config search path mirrors the Godot server's embedded config.
    let default_path = PathBuf::from("server_config.json");
    let fallback = PathBuf::from("../client/data/config/server_config.json");
    let path = config_path.or_else(|| {
        if default_path.exists() {
            Some(default_path)
        } else if fallback.exists() {
            Some(fallback)
        } else {
            None
        }
    });
    let mut config = ServerConfig::load(path.as_deref());
    if let Some(allow) = allow_unsigned_override {
        config.allow_unsigned_tickets = allow;
    }
    if let Some(mode) = mode_override {
        config.mode = mode;
    }
    if let Some(port) = port_override {
        config.port = port;
    }
    // Re-validate: a `--mode` typo or other CLI override must be caught the same way a bad JSON
    // value is (load() already validated the file-derived config before the overrides landed).
    config.validate();

    // Defense-in-depth: unsigned tickets are a dev/load-test affordance only. If they're enabled
    // on a non-local (production) region, that's almost certainly a misconfiguration — shout.
    if config.allow_unsigned_tickets && !config.region.eq_ignore_ascii_case("local") {
        warn!(
            "SECURITY: allow_unsigned_tickets is TRUE on non-local region '{}' — auth is OPEN. \
             Set OMEGA_ALLOW_UNSIGNED_TICKETS=false (or --require-tickets) in production.",
            config.region
        );
    }

    // Apply this instance's world geometry ONCE, on the tick thread (this thread), before the sim
    // runs. Arena = ±1000 + 16 pillars; Sanctuary = ±3328×±3072 walk-through. The client sets the same
    // geometry on scene entry so prediction matches.
    if config.is_sanctuary() {
        sim_core::set_world_geometry(
            sim_core::constants::SANCTUARY_MAP_MIN,
            sim_core::constants::SANCTUARY_MAP_MAX,
            false,
        );
        info!("instance mode: SANCTUARY — no monsters, PvP off, ±3328×±3072 walk-through town");
    } else {
        sim_core::set_world_geometry(
            sim_core::constants::MAP_MIN,
            sim_core::constants::MAP_MAX,
            true,
        );
        info!("instance mode: ARENA — monsters + PvP, ±1000 with pillars");
    }
    info!("config: {config:?}");

    if config.metrics_port != 0 {
        match metrics_exporter_prometheus::PrometheusBuilder::new()
            // Loopback-only: metrics are scraped over an SSH tunnel / local Prometheus, never
            // exposed publicly (the UDP game socket below stays on 0.0.0.0 — it must be public).
            .with_http_listener(([127, 0, 0, 1], config.metrics_port))
            .install()
        {
            Ok(()) => info!("prometheus metrics on 127.0.0.1:{}", config.metrics_port),
            Err(e) => warn!("metrics exporter failed to start: {e}"),
        }
    }

    let verifier = auth::TicketVerifier::new(
        &config.ticket_pubkey_hex,
        config.allow_unsigned_tickets,
        auth::region_from_string(&config.region),
    )
    .unwrap_or_else(|e| {
        warn!("{e}; falling back to unsigned-ticket mode");
        auth::TicketVerifier::new("", true, auth::region_from_string(&config.region)).unwrap()
    });
    if config.allow_unsigned_tickets {
        warn!("dev mode: unsigned tickets accepted (--require-tickets + OMEGA_TICKET_PUBKEY for production)");
    }

    let socket = UdpSocket::bind(("0.0.0.0", config.port)).expect("bind UDP game port");
    let mut host = enet::Host::new(
        socket,
        enet::HostSettings {
            peer_limit: config.max_players.max(1) * 2, // headroom for pre-auth churn
            channel_limit: protocol::CHANNEL_COUNT,
            ..Default::default()
        },
    )
    .expect("create ENet host");
    info!(
        "listening on udp/{} ({} channels)",
        config.port,
        protocol::CHANNEL_COUNT
    );

    let heartbeat_tx = if config.api_server_url.is_empty() {
        None
    } else {
        Some(api_client::spawn_heartbeat_thread(
            config.api_server_url.clone(),
        ))
    };
    // Server→API progression I/O (level/XP hydrate + write-back, Glory/permadeath on death).
    let progression = if config.api_server_url.is_empty() {
        None
    } else {
        Some(progression_client::spawn(config.api_server_url.clone()))
    };

    let start = Instant::now();
    let now_ms = |s: Instant| s.elapsed().as_millis() as u64;
    let unix_ms = || {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    };

    let tick_interval = config.tick_interval();
    let advertise_url = config.advertise_url.clone();
    let region = config.region.clone();
    let max_players = config.max_players;
    let mut world = world::World::new(config, verifier, rng::Pcg32::from_entropy(), progression);
    let mut outbox = Outbox::new();
    let mut collector = metrics::MetricsCollector::default();
    let mut connected: HashSet<usize> = HashSet::new();

    let mut last_loop = Instant::now();
    let mut tick_timer: f64 = 0.0;
    let mut last_metrics_ms: u64 = 0;
    // None = not yet published; the first loop iteration publishes immediately so the
    // instance is visible in the region list at boot (parity with the GDScript init publish).
    let mut last_heartbeat_ms: Option<u64> = None;

    // Graceful shutdown (parity with GDScript shutdown(): reasoned DISCONNECT to every peer
    // instead of letting clients hit the ENet timeout).
    let shutdown = Arc::new(AtomicBool::new(false));
    {
        let shutdown = shutdown.clone();
        if let Err(e) = ctrlc::set_handler(move || shutdown.store(true, Ordering::SeqCst)) {
            warn!("failed to install shutdown handler: {e}");
        }
    }

    while !shutdown.load(Ordering::SeqCst) {
        // Drain ENet events (handlers run between ticks, in arrival order).
        loop {
            match host.service() {
                Ok(Some(event)) => {
                    let event = event.no_ref();
                    match event {
                        enet::EventNoRef::Connect { peer, data } => {
                            let key = peer.0;
                            match world.on_peer_connected(key, data) {
                                Ok(()) => {
                                    connected.insert(key);
                                }
                                Err(reason) => {
                                    host.peer_mut(peer).disconnect(reason);
                                }
                            }
                        }
                        enet::EventNoRef::Disconnect { peer, .. } => {
                            let key = peer.0;
                            if connected.remove(&key) {
                                world.on_peer_disconnected(key, &mut outbox);
                                collector.remove_peer(key);
                            }
                        }
                        enet::EventNoRef::Receive {
                            peer,
                            channel_id: _,
                            packet,
                        } => {
                            let key = peer.0;
                            collector.record_received(packet.data().len());
                            match ClientPacket::decode(packet.data()) {
                                Ok(pkt) => {
                                    world.on_packet(key, pkt, now_ms(start), unix_ms(), &mut outbox)
                                }
                                Err(e) => {
                                    tracing::debug!("bad packet from peer {key}: {e}");
                                }
                            }
                        }
                    }
                }
                Ok(None) => break,
                Err(e) => {
                    warn!("enet service error: {e:?}");
                    break;
                }
            }
        }
        flush_outbox(&mut outbox, &mut host, &connected, &mut collector);

        // Fixed-tick accumulator with fractional-remainder carry; unbounded catch-up like the
        // GDScript (the snapshot accumulator's drift guard caps bursts to one snapshot).
        let now = Instant::now();
        tick_timer += now.duration_since(last_loop).as_secs_f64();
        last_loop = now;
        while tick_timer >= tick_interval {
            tick_timer -= tick_interval;
            let tick_start = Instant::now();
            world.tick(now_ms(start), &mut outbox);
            flush_outbox(&mut outbox, &mut host, &connected, &mut collector);
            host.flush();
            collector.record_tick_time(tick_start.elapsed().as_secs_f64() * 1000.0);
        }

        // 1 Hz metrics (skip when empty, parity with GDScript).
        let t_ms = now_ms(start);
        if t_ms.saturating_sub(last_metrics_ms) >= 1000 {
            last_metrics_ms = t_ms;
            let entity_count =
                world.projectiles.count() + world.monsters.count() + world.world_entities.count();
            let player_count = world.players.player_count();
            let pkt = collector.build_packet(
                world.tick_count,
                player_count,
                entity_count,
                &world.broadcast.diagnostics,
                t_ms,
            );
            if player_count > 0 {
                outbox.broadcast(ServerPacket::ServerMetrics(pkt));
                flush_outbox(&mut outbox, &mut host, &connected, &mut collector);
            }
        }

        // 2 s region heartbeat (wall time, immediate at boot), fire-and-forget via the I/O thread.
        if let Some(tx) = &heartbeat_tx {
            if last_heartbeat_ms.is_none_or(|last| t_ms.saturating_sub(last) >= 2000) {
                last_heartbeat_ms = Some(t_ms);
                let _ = tx.send(api_client::RegionStatus {
                    region_id: region.clone(),
                    active_players: world.players.player_count(),
                    max_players,
                    connect_url: advertise_url.clone(),
                    status: "online".into(),
                });
            }
        }

        std::thread::sleep(Duration::from_millis(1));
    }

    // Reasoned disconnect to every connected peer, then a short service window so the
    // disconnect packets actually leave before the process exits.
    info!("shutting down: notifying {} peer(s)", connected.len());
    for &key in &connected {
        host.peer_mut(enet::PeerID(key))
            .disconnect(protocol::types::disconnect_reason::SERVER_SHUTDOWN);
    }
    let deadline = Instant::now() + Duration::from_millis(500);
    while Instant::now() < deadline {
        match host.service() {
            Ok(Some(_)) => {}
            Ok(None) => std::thread::sleep(Duration::from_millis(5)),
            Err(_) => break,
        }
    }
    info!("shutdown complete");
}

fn flush_outbox<S: enet::Socket>(
    outbox: &mut Outbox,
    host: &mut enet::Host<S>,
    connected: &HashSet<usize>,
    collector: &mut metrics::MetricsCollector,
) {
    for (target, packet) in outbox.drain() {
        let bytes = packet.encode();
        let channel = packet.channel();
        let reliable = packet.reliable();
        if !reliable && bytes.len() > protocol::MAX_UNRELIABLE_PAYLOAD {
            // An unreliable packet above the MTU silently upgrades to reliable-fragmented and
            // reintroduces head-of-line blocking — the budget should prevent this; log loudly.
            warn!(
                "oversized unreliable packet ({} B) on channel {channel}",
                bytes.len()
            );
        }
        match target {
            Target::Peer(key) => {
                if connected.contains(&key) {
                    let peer = host.peer_mut(enet::PeerID(key));
                    if peer.connected() {
                        let pkt = if reliable {
                            enet::Packet::reliable(bytes.as_slice())
                        } else {
                            enet::Packet::unreliable(bytes.as_slice())
                        };
                        if peer.send(channel, &pkt).is_ok() {
                            collector.record_sent(key, bytes.len());
                        }
                    }
                }
            }
            Target::Broadcast => {
                for &key in connected {
                    let peer = host.peer_mut(enet::PeerID(key));
                    if peer.connected() {
                        let pkt = if reliable {
                            enet::Packet::reliable(bytes.as_slice())
                        } else {
                            enet::Packet::unreliable(bytes.as_slice())
                        };
                        if peer.send(channel, &pkt).is_ok() {
                            collector.record_sent(key, bytes.len());
                        }
                    }
                }
            }
        }
    }
    for (key, reason) in std::mem::take(&mut outbox.kicks) {
        if connected.contains(&key) {
            // disconnect_later: the queued packets (e.g. the AuthResult nack) flush first.
            host.peer_mut(enet::PeerID(key)).disconnect_later(reason);
        }
    }
}
