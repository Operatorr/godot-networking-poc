# Client lifecycle and performance patterns

Modified from the existing Godot patterns skill for Omega Realm. See the parent
[SKILL.md](../SKILL.md) for architecture constraints and [MIT license](../LICENSE).

## Pool ownership and reset

Start with the existing implementations:

- [ClientEntityManager](../../../../client/scripts/network/client_entity_manager.gd)
  manages network entity maps and the network projectile pool.
- [ProjectilePool](../../../../client/scripts/systems/spawning/projectile_pool.gd)
  serves the existing local projectile path.

Before adding a generic pool, identify whether either owner already provides the needed
lifecycle. Pool acquisition must produce a fully configured entity before it can process,
render, or detect overlaps. Configure fields needed by `_ready()` before tree entry; set
world-space transforms after parenting when the parent transform matters.

For each reusable entity, account for:

- Identity: entity ID, ownership, spawn generation, and map registration.
- Simulation/presentation: transform, velocity, lifetime, interpolation history,
  discontinuity reset, visibility, modulation, animation, and material state.
- Collision: shape state, layers/masks, Area monitoring and monitorability.
- Async work: timers, tweens, awaited completions, callbacks, and signal connections.

On return, cancel or invalidate outstanding work, remove active registrations, disable
collision participation as appropriate, and reset fields that the next activation does
not overwrite. Hiding a node or disabling `_process()` does not remove physics overlaps.
Defer collision changes when called during a physics-query callback.

An old timer may resume after a node has been reused. Check activation/session identity
before applying its result; validity alone does not distinguish two uses of the same node.
Return must be idempotent: repeated despawn paths cannot add duplicate available entries.

Use bounded exhaustion behavior consistent with the current pool. Profile allocation,
linear membership searches, and removal at representative projectile counts before
replacing a working structure.

## Presentation state machines

Use a state machine when it clarifies a real UI/animation lifecycle. Shared movement
semantics remain in Rust `sim_core`; the client's movement facade mirrors predicted or
accepted state rather than defining independent online rules.

For a node-based presentation state machine:

1. Register states and verify the initial state belongs to the machine.
2. Resolve the next state before exiting the current state; handle no current state.
3. Define whether same-state requests are ignored or restart the state.
4. Give one system ownership of state callbacks to avoid double processing.
5. Cancel state-owned async work on exit and reject stale completions.
6. Handle reentrant transition requests deliberately, such as queuing them until the
   current enter/exit completes.

Consult [state-machine documentation](../../../../docs/systems/state-machines.md) and
the current implementation before introducing a second abstraction.

## Hot paths and large entity counts

- Cache stable node references; use existing entity maps instead of scene-tree/group
  scans per entity per Frame.
- Reuse buffers where measurements show allocation pressure. Prefer typed boundaries
  and concrete types over repeated Variant conversion in hot loops.
- Reduce needless per-entity processing only when the owner can still advance required
  lifetimes, network state, and gameplay feedback. Off-screen rendering is separate from
  simulation/network lifecycle.
- Profile representative visible entities, projectile bursts, and scene transitions.
  Pooling reduces allocation/destruction churn; it does not by itself prove a speedup.
- Reset interpolation on teleports, pool reuse, and other discontinuities using existing
  controller hooks. Camera/presentation changes must preserve render smoothness across FPS.

For a pooling change, exercise acquire → return → reacquire, duplicate return, exhaustion,
and return during pending callbacks. For presentation state changes, exercise normal
completion, interruption, and scene/session teardown. Use existing tests where they cover
the behavior; add regression coverage when a concrete bug warrants it.
