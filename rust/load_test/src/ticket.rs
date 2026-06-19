//! Signed-ticket fetch for authenticated load-test joins.
//!
//! A fail-closed live server (`allow_unsigned_tickets=false`) rejects the swarm's ticket-less
//! joins with `BAD_TICKET`. Rather than weaken the server, each bot fetches a real Ed25519
//! ticket from the Go API's load-test endpoint (`POST /api/loadtest/ticket`, guarded by a
//! shared secret) for a SYNTHETIC `character_id` (>= 1_000_000) — an id the server excludes
//! from all DB I/O, so the bots authenticate for real without touching any character row.
//!
//! Mirrors the server's HTTP-client pattern (`rust/server/src/net/api_client.rs`): one pooled
//! `ureq::Agent`, blocking calls (the swarm is single-threaded by design — no async runtime).

use base64::Engine;
use protocol::Ticket;
use serde_json::{json, Value};
use std::time::Duration;

/// Lowest `character_id` the server treats as synthetic (no progression hydrate / write-back /
/// permadeath). MUST match `rust/server/src/sim/world.rs` and the Go endpoint's
/// `LoadTestCharacterIDMin`. Bots mint `SYNTHETIC_ID_BASE + bot_id`.
pub const SYNTHETIC_ID_BASE: u32 = 1_000_000;

/// Mints signed tickets for load-test bots by calling the Go API. Holds a pooled HTTP agent so
/// repeated per-bot fetches reuse one TLS connection.
pub struct TicketClient {
    agent: ureq::Agent,
    url: String,
    secret: String,
    region: String,
}

impl TicketClient {
    /// `api_base_url` is the API origin (e.g. `https://gsapi.marrowtech.app`); the endpoint path
    /// is appended. `region` must match the target instance's configured region (the server
    /// rejects a region mismatch with `WRONG_REGION`).
    pub fn new(api_base_url: &str, secret: String, region: String) -> Self {
        let agent: ureq::Agent = ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(10)))
            .build()
            .into();
        let url = format!("{}/api/loadtest/ticket", api_base_url.trim_end_matches('/'));
        Self {
            agent,
            url,
            secret,
            region,
        }
    }

    /// Fetch a signed ticket for `character_id`. Blocking; returns a wire-ready [`Ticket`] or a
    /// human-readable error (the ureq error Display carries the HTTP status — 503 = endpoint
    /// disabled, 401 = bad secret, 400 = id below the synthetic floor or bad region).
    pub fn fetch(&self, character_id: u32) -> Result<Ticket, String> {
        let body = json!({ "character_id": character_id, "region_id": self.region });
        let mut resp = self
            .agent
            .post(&self.url)
            .header("X-Loadtest-Token", &self.secret)
            .send_json(&body)
            .map_err(|e| format!("ticket request failed: {e}"))?;
        let v: Value = resp
            .body_mut()
            .read_json()
            .map_err(|e| format!("ticket response parse failed: {e}"))?;
        let b64 = v
            .get("ticket")
            .and_then(Value::as_str)
            .ok_or_else(|| "ticket response missing 'ticket' field".to_string())?;
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .map_err(|e| format!("ticket base64 decode failed: {e}"))?;
        Ticket::from_bytes(&bytes).map_err(|e| format!("ticket decode failed: {e:?}"))
    }
}
