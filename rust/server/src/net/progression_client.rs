//! Server→API progression I/O on a dedicated thread (D8: no HTTP on the hot tick). Mirrors the
//! region-heartbeat pattern in `api_client.rs`: the tick thread submits jobs over an mpsc channel;
//! hydrate/death replies come back over reply channels the world polls with `try_recv` each tick
//! (never blocking the tick). Endpoints + the `X-Server-Token` auth match `api/internal/handlers/
//! internal.go` exactly. If `SERVER_API_TOKEN` is unset, the header is omitted (dev parity with
//! the heartbeat token).

use serde::{Deserialize, Serialize};
use std::sync::mpsc::{Receiver, Sender};
use std::time::Duration;
use tracing::{debug, warn};

pub enum ProgressionJob {
    /// Load a character's level/XP/mode at join. Reply → `hydrate_rx`.
    Hydrate { peer: usize, character_id: u32 },
    /// Write back level/XP (fire-and-forget).
    Progress {
        character_id: u32,
        level: u16,
        experience: u32,
    },
    /// Atomic Glory conversion (+ hardcore permadeath delete) on death. Reply → `death_rx`.
    Death { peer: usize, character_id: u32 },
}

#[derive(Debug, Clone)]
pub struct HydrateResult {
    pub peer: usize,
    pub character_id: u32,
    /// `None` ⇒ the hydrate failed (request error or parse error). The world MUST NOT fall back to
    /// softcore defaults for a real character — a hardcore character played as softcore would
    /// silently lose permadeath. The world kicks the peer so they retry a clean join instead.
    pub state: Option<HydrateState>,
}

#[derive(Debug, Clone)]
pub struct HydrateState {
    pub level: u16,
    pub experience: u32,
    pub mode_hardcore: bool,
}

#[derive(Debug, Clone)]
pub struct DeathResult {
    pub peer: usize,
    pub character_id: u32,
    pub glory_awarded: i64,
    pub character_deleted: bool,
}

pub struct ProgressionClient {
    job_tx: Sender<ProgressionJob>,
    pub hydrate_rx: Receiver<HydrateResult>,
    pub death_rx: Receiver<DeathResult>,
}

impl ProgressionClient {
    pub fn submit(&self, job: ProgressionJob) {
        // The worker thread outlives the world; a send only fails if it panicked.
        let _ = self.job_tx.send(job);
    }
}

#[derive(Deserialize)]
struct CharStateDto {
    level: i64,
    experience: i64,
    mode: String,
}

#[derive(Serialize)]
struct ProgressDto {
    level: u16,
    experience: u32,
}

#[derive(Deserialize)]
struct DeathDto {
    glory_awarded: i64,
    character_deleted: bool,
}

pub fn spawn(api_server_url: String) -> ProgressionClient {
    let (job_tx, job_rx) = std::sync::mpsc::channel::<ProgressionJob>();
    let (hydrate_tx, hydrate_rx) = std::sync::mpsc::channel::<HydrateResult>();
    let (death_tx, death_rx) = std::sync::mpsc::channel::<DeathResult>();
    std::thread::Builder::new()
        .name("api-progression".into())
        .spawn(move || {
            let agent: ureq::Agent = ureq::Agent::config_builder()
                .timeout_global(Some(Duration::from_secs(5)))
                .build()
                .into();
            let base = api_server_url.trim_end_matches('/').to_string();
            let token = std::env::var("SERVER_API_TOKEN").unwrap_or_default();
            while let Ok(job) = job_rx.recv() {
                match job {
                    ProgressionJob::Hydrate { peer, character_id } => {
                        let url = format!("{base}/api/internal/characters/{character_id}");
                        let mut req = agent.get(&url);
                        if !token.is_empty() {
                            req = req.header("X-Server-Token", &token);
                        }
                        match req.call() {
                            Ok(mut resp) => match resp.body_mut().read_json::<CharStateDto>() {
                                Ok(dto) => {
                                    let _ = hydrate_tx.send(HydrateResult {
                                        peer,
                                        character_id,
                                        state: Some(HydrateState {
                                            level: dto.level.clamp(1, 65535) as u16,
                                            experience: dto.experience.max(0) as u32,
                                            mode_hardcore: dto.mode == "hardcore",
                                        }),
                                    });
                                }
                                Err(e) => {
                                    warn!("hydrate parse failed (char {character_id}): {e}");
                                    let _ = hydrate_tx.send(HydrateResult {
                                        peer,
                                        character_id,
                                        state: None,
                                    });
                                }
                            },
                            Err(e) => {
                                // Fail CLOSED: don't let a hardcore character be played as softcore
                                // just because the API was unreachable. Signal failure so the world
                                // kicks the peer (raised from debug! — this is operationally real).
                                warn!("hydrate request failed (char {character_id}): {e}");
                                let _ = hydrate_tx.send(HydrateResult {
                                    peer,
                                    character_id,
                                    state: None,
                                });
                            }
                        }
                    }
                    ProgressionJob::Progress {
                        character_id,
                        level,
                        experience,
                    } => {
                        let url = format!("{base}/api/internal/characters/{character_id}/progress");
                        let mut req = agent.post(&url);
                        if !token.is_empty() {
                            req = req.header("X-Server-Token", &token);
                        }
                        if let Err(e) = req.send_json(ProgressDto { level, experience }) {
                            debug!("progress write failed (char {character_id}): {e}");
                        }
                    }
                    ProgressionJob::Death { peer, character_id } => {
                        let url = format!("{base}/api/internal/characters/{character_id}/death");
                        let mut req = agent.post(&url);
                        if !token.is_empty() {
                            req = req.header("X-Server-Token", &token);
                        }
                        match req.send_empty() {
                            Ok(mut resp) => match resp.body_mut().read_json::<DeathDto>() {
                                Ok(dto) => {
                                    let _ = death_tx.send(DeathResult {
                                        peer,
                                        character_id,
                                        glory_awarded: dto.glory_awarded,
                                        character_deleted: dto.character_deleted,
                                    });
                                }
                                Err(e) => warn!("death parse failed (char {character_id}): {e}"),
                            },
                            Err(e) => warn!("death request failed (char {character_id}): {e}"),
                        }
                    }
                }
            }
        })
        .expect("spawn progression thread");
    ProgressionClient {
        job_tx,
        hydrate_rx,
        death_rx,
    }
}
