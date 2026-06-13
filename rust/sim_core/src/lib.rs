//! Omega Realm shared simulation core (migration-spec D5).
//!
//! Movement, collision, dash/knockback/stamina, and the hit-authority predicates — written once,
//! linked by both the server binary (authoritative) and the client GDExtension (prediction), so
//! movement divergence between prediction and authority is zero by construction.
//!
//! Ported from the GDScript at commit 9e66149 per `docs/rust-port/extraction/sim-movement.md`.
//! Numerics policy (contract.md): `Vec2` ops in f32 (mirrors Godot's single-precision Vector2);
//! scalar sim state (timers, stamina, mana, delta) in f64 (mirrors GDScript loose floats);
//! scalar→vector application casts to f32 at the multiply.

pub mod arena;
pub mod constants;
pub mod hit;
mod movement;
pub mod progression;
mod rect;
mod step;
mod vec2;

pub use arena::{set_world_geometry, world_geometry, WorldGeometry, ARENA_GEOMETRY};
pub use movement::{MoveState, MovementSm};
pub use rect::Rect;
pub use step::{
    flags as input_flags, movement_direction, replay_ground_step, step_movement, StepResult,
};
pub use vec2::{is_equal_approx_f64, Vec2};
