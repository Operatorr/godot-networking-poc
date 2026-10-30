---
name: performance-optimization
description: Measure Omega Realm client frame cost, Rust server Tick cost, and network load before optimizing. Use for stutter, crowded scenes, entity scaling, pooling, batching, allocation, or load-test regressions.
license: Apache-2.0
---

# Performance optimization

Read [performance budgets](../../../docs/netcode/performance-budgets.md), [server design](../../../docs/server/design.md), and the [load-test README](../../../rust/load_test/README.md). Distinguish measured gates, configured caps, and the 500–1000-player target.

## Workflow

1. Specify a repeatable workload, build, hardware, entity/player counts, duration, and target. Separate client Frame time, authoritative Tick duration, network latency/loss, and interpolation smoothness.
2. Measure the relevant owner: Godot profiler/render monitors for client CPU/GPU; server tick histograms and subsystem traces for simulation; swarm metrics for transport/load. Identify what the active renderer/build can actually expose.
3. Record distributions and spikes (for example p50/p95/p99), not only average FPS. Use warmed-up runs plus explicit cold-start measurements when investigating loading. Optimized builds matter; profiling instrumentation also adds overhead.
4. Find the limiting resource before changing code. Reduce unnecessary work, broad scans, repeated allocations, overdraw, or state changes based on evidence. Draw-call batching can reduce CPU submission cost as well as GPU overhead.
5. Preserve simulation semantics: fixed Tick, shared numerics, target validity, hit validation, RNG consumption, and packet bounds. Client culling cannot decide authoritative entity existence.
6. Reuse existing pools and registries. Define caps and overflow behavior; pool reset includes signals, physics participation, timers, tweens, materials, identity, and async work, not just visibility.
7. Re-measure the same workload after one focused change. Check that a CPU gain did not increase bandwidth, memory, frame latency, or stale-entity behavior. Keep/revert based on measured results.
8. Report before/after values, method, limitations, and the relevant regression check. Use targeted game/client checks for presentation changes and required Rust checks for Rust changes; do not claim scalability from an idle scene.

## References

- [Profiling and budgets](references/profiling-and-budgets.md): general techniques; sample asset budgets are not project targets.
- [Client lifecycle patterns](../godot-gdscript-patterns/references/client-patterns.md): safe pooling.
- [Render smoothness](../../../docs/netcode/smoothness-render.md): high FPS with judder can be an interpolation problem.
- [Game AI](../game-ai/SKILL.md) and [procedural generation](../procedural-gen/SKILL.md): bounded expensive work.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/performance-optimization) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
