---
name: game-ai
description: Design and tune Omega Realm's authoritative Rust monster decisions, targeting, steering, and bounded pathfinding. Use when changing enemy behavior, FSM transitions, perception, or AI cost at multiplayer scale.
license: Apache-2.0
---

# Authoritative game AI

Read [monster AI](../../../docs/systems/monsters-ai.md), [monster architecture](../../../docs/systems/monster-architecture.md), and [server design](../../../docs/server/design.md). Online monsters are Remote entities: Godot interpolates/animates their state; the Rust server decides behavior.

## Workflow

1. Trace `rust/server/src/sim/monster.rs` and its definitions before adding abstractions. Keep decision selection, movement/steering, and presentation distinct.
2. Extend the existing Idle/Chase/Attack/Flee state machine when sufficient. Write entry/exit conditions, timers, target invalidation, and interrupt precedence. Use hysteresis/stickiness where thresholds otherwise oscillate.
3. Make perception explicit: range, alive/authenticated state, visibility/Stealth, current-target validity, and tie-breaking. Test loss of target during attack and removal/reuse of an entity ID.
4. Keep gameplay timers on the authoritative Tick and use the server RNG path. Preserve deterministic iteration and RNG consumption when changing code that participates in replay or parity.
5. Budget perception/pathfinding separately from movement. Cache only with clear invalidation, bound searches, and measure dense-player scenarios before changing decision cadence. A lower sensing cadence must not skip required movement/combat updates.
6. Add navigation only when geometry requires it. Account for agent clearance, obstacle changes, unreachable goals, and stale paths; a Godot navigation node cannot become the online simulation authority.
7. If an FSM becomes unwieldy, use the behavior-tree reference to assess memory, reactive priorities, abort/reset, and utility scores. Introduce a runtime only when concrete behavior warrants it.
8. Verify state transitions, cooldowns, dead/hidden targets, bounded work, and server cost with representative monsters/players. Treat offline AI as a separate mode and compare intended parity explicitly.

## References

- [FSMs, behavior trees, and utility scoring](references/behavior-trees.md).
- [A*, graph costs, and path budgets](references/pathfinding.md).
- [Performance](../performance-optimization/SKILL.md) and [server contract](../../../docs/server/contract.md).
- [Bot AI](../../../docs/systems/bot-ai.md): distinct player-bot behavior; inspect its owner before editing.

## Source

Adapted from [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills/tree/19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9/skills/disciplines/game-ai) at `19d93f97c9c1ea0f8b306e77aa81e0d3e352d3e9`.
Modified for Omega Realm: scoped the workflow to existing project owners and Godot 4.7 where applicable, removed unrelated skill dependencies, and corrected conflicting examples. Modified references carry their own notices. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
