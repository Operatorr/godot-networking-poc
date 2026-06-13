//! Server configuration — same keys/defaults as `server_config.gd` (extraction server-tick §2.7),
//! plus the new D9 auth keys. JSON file → env overrides; unknown keys warn and are dropped;
//! numbers accept both int and float JSON encodings (Godot's parser produced floats).

use serde_json::Value;
use std::path::Path;
use tracing::warn;

#[derive(Debug, Clone)]
pub struct ServerConfig {
    pub port: u16,
    pub tick_rate: u32,
    pub max_players: usize,
    pub region: String,
    /// Instance kind: "arena" (combat: monsters + PvP, ±1000 + pillars) or "sanctuary" (safe town:
    /// no monsters, PvP off, ±1856 walk-through). One process = one Instance (D13).
    pub mode: String,
    pub debug_logging: bool,
    pub api_server_url: String,
    pub aoi_radius: f32,
    pub aoi_exit_radius: f32,
    pub lod_near_radius: f32,
    pub lod_mid_radius: f32,
    pub snapshot_rate_hz_raw: u32,
    pub max_snapshot_bytes: usize,
    pub default_client_bandwidth_bps: u32,
    pub max_client_bandwidth_bps: u32,
    pub min_client_bandwidth_bps: u32,
    pub monster_ai_difficulty: f64,
    pub monster_spawn_rate: f64,
    /// D9 seam: accept ticket-less ConnectAuth (POC parity with the trust-the-client flow).
    pub allow_unsigned_tickets: bool,
    /// Ed25519 public key (hex, 32 bytes) for ticket verification; env `OMEGA_TICKET_PUBKEY`.
    pub ticket_pubkey_hex: String,
    /// Advertised connect URL for the region heartbeat; empty = let the Go API substitute its
    /// static per-region default (replaces the old hardcoded ws://localhost:<port> wart).
    pub advertise_url: String,
    /// D11 backstop: ticks of grace after a blatant authoritative overlap before the server
    /// applies the hit itself. Must comfortably exceed render-delay + RTT (floor ≈ 15 @ 30 Hz).
    pub backstop_grace_ticks: u64,
    /// Prometheus exporter listen port (0 disables).
    pub metrics_port: u16,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            port: 8081,
            tick_rate: 30,
            max_players: 100,
            region: "local".into(),
            mode: "arena".into(),
            debug_logging: true,
            api_server_url: "http://localhost:8080".into(),
            aoi_radius: 1000.0,
            aoi_exit_radius: 1100.0,
            lod_near_radius: 400.0,
            lod_mid_radius: 1000.0,
            snapshot_rate_hz_raw: 0,
            max_snapshot_bytes: 1200,
            default_client_bandwidth_bps: 120_000,
            max_client_bandwidth_bps: 200_000,
            min_client_bandwidth_bps: 24_000,
            monster_ai_difficulty: 0.85,
            // Live value is the server_main.tscn scene override (0.1), not the 0.4 export
            // default on ServerMain (extraction server-tick §2.1).
            monster_spawn_rate: 0.1,
            allow_unsigned_tickets: true,
            ticket_pubkey_hex: String::new(),
            advertise_url: String::new(),
            backstop_grace_ticks: 20,
            metrics_port: 9100,
        }
    }
}

impl ServerConfig {
    /// Effective snapshot rate: raw `<= 0` → tick rate; else `min(raw, tick_rate)`.
    pub fn snapshot_rate_hz(&self) -> u32 {
        if self.snapshot_rate_hz_raw == 0 {
            self.tick_rate
        } else {
            self.snapshot_rate_hz_raw.min(self.tick_rate)
        }
    }

    pub fn tick_interval(&self) -> f64 {
        1.0 / self.tick_rate.max(1) as f64
    }

    /// True for a Sanctuary instance (case-insensitive).
    pub fn is_sanctuary(&self) -> bool {
        self.mode.eq_ignore_ascii_case("sanctuary")
    }

    /// PvP collisions (player projectiles hitting players) are on only in the Arena.
    pub fn pvp_enabled(&self) -> bool {
        !self.is_sanctuary()
    }

    /// Monsters spawn only in the Arena.
    pub fn monsters_enabled(&self) -> bool {
        !self.is_sanctuary()
    }

    pub fn load(path: Option<&Path>) -> ServerConfig {
        let mut cfg = ServerConfig::default();
        if let Some(p) = path {
            match std::fs::read_to_string(p) {
                Ok(text) => match serde_json::from_str::<Value>(&text) {
                    Ok(Value::Object(map)) => {
                        for (k, v) in &map {
                            cfg.apply_key(k, v);
                        }
                    }
                    Ok(_) => warn!("config {p:?} is not a JSON object; using defaults"),
                    Err(e) => warn!("config {p:?} parse error: {e}; using defaults"),
                },
                Err(e) => warn!("config {p:?} unreadable: {e}; using defaults"),
            }
        }
        cfg.apply_env();
        cfg.validate();
        cfg
    }

    fn apply_key(&mut self, key: &str, v: &Value) {
        fn as_u32(v: &Value) -> Option<u32> {
            v.as_u64()
                .map(|x| x as u32)
                .or_else(|| v.as_f64().map(|f| f.trunc() as u32))
        }
        fn as_f64(v: &Value) -> Option<f64> {
            v.as_f64()
        }
        match key {
            "port" => {
                if let Some(x) = as_u32(v) {
                    self.port = x as u16;
                }
            }
            "tick_rate" => {
                if let Some(x) = as_u32(v) {
                    self.tick_rate = x;
                }
            }
            "max_players" => {
                if let Some(x) = as_u32(v) {
                    self.max_players = x as usize;
                }
            }
            "region" => {
                if let Some(s) = v.as_str() {
                    self.region = s.to_string();
                }
            }
            "mode" => {
                if let Some(s) = v.as_str() {
                    self.mode = s.to_string();
                }
            }
            "debug_logging" => {
                if let Some(b) = v.as_bool() {
                    self.debug_logging = b;
                }
            }
            // Dead config carried in the file; the transport-level timeout is ENet-native now.
            "heartbeat_timeout_seconds" => {}
            "api_server_url" => {
                if let Some(s) = v.as_str() {
                    self.api_server_url = s.to_string();
                }
            }
            "aoi_radius" => {
                if let Some(x) = as_f64(v) {
                    self.aoi_radius = x as f32;
                }
            }
            "aoi_exit_radius" => {
                if let Some(x) = as_f64(v) {
                    self.aoi_exit_radius = x as f32;
                }
            }
            "lod_near_radius" => {
                if let Some(x) = as_f64(v) {
                    self.lod_near_radius = x as f32;
                }
            }
            "lod_mid_radius" => {
                if let Some(x) = as_f64(v) {
                    self.lod_mid_radius = x as f32;
                }
            }
            // BATCH died with ENet (D2); accept the key silently for old config files.
            "packet_batching_enabled" => {}
            "snapshot_rate_hz" => {
                if let Some(x) = as_u32(v) {
                    self.snapshot_rate_hz_raw = x;
                }
            }
            "max_snapshot_bytes" => {
                if let Some(x) = as_u32(v) {
                    self.max_snapshot_bytes = x as usize;
                }
            }
            "default_client_bandwidth_bps" => {
                if let Some(x) = as_u32(v) {
                    self.default_client_bandwidth_bps = x;
                }
            }
            "max_client_bandwidth_bps" => {
                if let Some(x) = as_u32(v) {
                    self.max_client_bandwidth_bps = x;
                }
            }
            "min_client_bandwidth_bps" => {
                if let Some(x) = as_u32(v) {
                    self.min_client_bandwidth_bps = x;
                }
            }
            "monster_ai_difficulty" => {
                if let Some(x) = as_f64(v) {
                    self.monster_ai_difficulty = x.clamp(0.0, 1.0);
                }
            }
            "monster_spawn_rate" => {
                if let Some(x) = as_f64(v) {
                    self.monster_spawn_rate = x;
                }
            }
            "allow_unsigned_tickets" => {
                if let Some(b) = v.as_bool() {
                    self.allow_unsigned_tickets = b;
                }
            }
            "advertise_url" => {
                if let Some(s) = v.as_str() {
                    self.advertise_url = s.to_string();
                }
            }
            "backstop_grace_ticks" => {
                if let Some(x) = as_u32(v) {
                    self.backstop_grace_ticks = x as u64;
                }
            }
            "metrics_port" => {
                if let Some(x) = as_u32(v) {
                    self.metrics_port = x as u16;
                }
            }
            other => warn!("unknown config key '{other}' ignored"),
        }
    }

    fn apply_env(&mut self) {
        if let Ok(v) = std::env::var("GAME_SERVER_TICK_RATE") {
            if let Ok(x) = v.parse::<u32>() {
                self.tick_rate = x;
            }
        }
        if let Ok(v) = std::env::var("GAME_SERVER_PORT") {
            if let Ok(x) = v.parse::<u16>() {
                self.port = x;
            }
        }
        if let Ok(v) = std::env::var("OMEGA_TICKET_PUBKEY") {
            self.ticket_pubkey_hex = v;
        }
        if let Ok(v) = std::env::var("OMEGA_ALLOW_UNSIGNED_TICKETS") {
            self.allow_unsigned_tickets = v == "1" || v.eq_ignore_ascii_case("true");
        }
    }

    /// The GDScript misbehaved on `tick_rate = 0` (infinite interval); validate instead.
    fn validate(&mut self) {
        if self.tick_rate == 0 {
            warn!("tick_rate 0 is invalid; using 30");
            self.tick_rate = 30;
        }
        if self.max_snapshot_bytes == 0 {
            warn!("max_snapshot_bytes 0 would disable the budget; using 1200");
            self.max_snapshot_bytes = 1200;
        }
        if self.monster_spawn_rate < 0.01 {
            self.monster_spawn_rate = 0.01;
        }
        // D11 invariant #4: the backstop must stay lenient. Floor ≈ render-delay + RTT @30 Hz.
        if self.backstop_grace_ticks < 15 {
            warn!(
                "backstop_grace_ticks {} is below the leniency floor; using 15",
                self.backstop_grace_ticks
            );
            self.backstop_grace_ticks = 15;
        }
    }
}
