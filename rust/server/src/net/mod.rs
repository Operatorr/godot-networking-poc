//! Networking / I/O subsystems — broadcast pipeline, outbound staging, metrics,
//! auth, and the side-thread clients to the Go API.
//!
//! Re-exported flat at the crate root (see `main.rs`): `crate::broadcast`, etc.
pub mod api_client;
pub mod auth;
pub mod broadcast;
pub mod metrics;
pub mod outbox;
pub mod progression_client;
