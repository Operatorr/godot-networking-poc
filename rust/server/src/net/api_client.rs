//! Region-status heartbeat to the Go API — the only outbound HTTP call today (extraction
//! lifecycle §4.11). Runs on a dedicated I/O thread (D8: no async in the hot loop); the tick
//! thread sends it status snapshots over a channel; one request in flight at a time by
//! construction (the thread is synchronous).

use serde::Serialize;
use std::sync::mpsc::{Receiver, Sender};
use std::time::Duration;
use tracing::{debug, warn};

#[derive(Debug, Clone, Serialize)]
pub struct RegionStatus {
    pub region_id: String,
    pub active_players: usize,
    pub max_players: usize,
    /// The configured advertise URL — a bare host:port for the ENet/UDP game server
    /// (empty = the API substitutes its static per-region default).
    pub connect_url: String,
    pub status: String,
}

pub fn spawn_heartbeat_thread(api_server_url: String) -> Sender<RegionStatus> {
    let (tx, rx): (Sender<RegionStatus>, Receiver<RegionStatus>) = std::sync::mpsc::channel();
    std::thread::Builder::new()
        .name("api-heartbeat".into())
        .spawn(move || {
            let agent: ureq::Agent = ureq::Agent::config_builder()
                .timeout_global(Some(Duration::from_secs(5)))
                .build()
                .into();
            let url = format!(
                "{}/api/regions/heartbeat",
                api_server_url.trim_end_matches('/')
            );
            let token = std::env::var("REGION_HEARTBEAT_TOKEN").unwrap_or_default();
            let mut warned = false;
            while let Ok(status) = rx.recv() {
                // Coalesce: only the newest queued status matters.
                let status = rx.try_iter().last().unwrap_or(status);
                let mut req = agent.post(&url);
                if !token.is_empty() {
                    req = req.header("X-Region-Heartbeat-Token", &token);
                }
                match req.send_json(&status) {
                    Ok(_) => {
                        if warned {
                            debug!("region heartbeat recovered");
                        }
                        warned = false;
                    }
                    Err(e) => {
                        if !warned {
                            warn!("region heartbeat failed (logged once per streak): {e}");
                            warned = true;
                        }
                    }
                }
            }
        })
        .expect("spawn heartbeat thread");
    tx
}
