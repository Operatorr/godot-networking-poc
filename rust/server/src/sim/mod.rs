//! Simulation/gameplay subsystems — the authoritative world and its entities.
//!
//! Physically groups the per-entity and per-tick sim modules. They are re-exported
//! flat at the crate root (see `main.rs`), so the rest of the crate refers to them
//! as `crate::player`, `crate::monster`, … rather than `crate::sim::player`.
pub mod ability;
pub mod combat;
pub mod leaderboard;
pub mod monster;
pub mod player;
pub mod projectile;
pub mod rng;
pub mod world;
pub mod world_entity;
