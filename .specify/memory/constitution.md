<!--
Sync Impact Report
==================
Version change: N/A → 1.0.0 (Initial creation)
Modified principles: N/A (new document)
Added sections:
  - Core Principles (5 principles)
  - Performance Standards
  - Quality Gates
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md: ✅ Compatible (Constitution Check section exists)
  - .specify/templates/spec-template.md: ✅ Compatible (Success Criteria aligns with performance requirements)
  - .specify/templates/tasks-template.md: ✅ Compatible (Checkpoint validation aligns with gates)
Follow-up TODOs: None
-->

# Omega Networking Constitution

## Core Principles

### I. Server Authority

All game state mutations MUST originate from or be validated by the authoritative Godot headless server. Clients MUST NOT trust local state for anything affecting gameplay outcomes. The server validates all player inputs, calculates all combat damage, and broadcasts canonical state to clients.

**Rationale**: Prevents cheating and ensures consistent game state across all connected players. Client-side prediction is permitted for responsiveness but MUST be reconciled with server state.

### II. Code Quality Standards

**GDScript Requirements**:
- All scripts MUST use static typing with explicit type hints for function parameters and return values
- Scripts MUST follow the client/server/shared directory convention defined in `CLAUDE.md`
- Shared code MUST NOT import client-only or server-only modules
- All exported variables MUST have documentation comments
- Signal connections MUST use typed callables where possible

**Go Requirements**:
- All functions MUST have error returns handled explicitly (no ignored errors)
- HTTP handlers MUST use structured logging with request context
- Database queries MUST use parameterized statements (no string concatenation)
- All public functions MUST have documentation comments

**Rationale**: Type safety catches bugs at development time rather than runtime. Consistent code organization enables safe sharing between client and server builds.

### III. Test-First for Critical Paths

Stress tests and integration tests MUST exist for:
1. WebSocket connection handling (connect, disconnect, reconnect)
2. State synchronization (delta compression, interest management)
3. Combat validation (damage calculation, hit detection)
4. Player capacity limits (must validate 500-1000 concurrent connections)

Tests MUST be written before implementation when adding or modifying:
- Network message types in the protocol
- Server-side validation logic
- Database schema changes

**Rationale**: The POC's primary goal is proving network scalability. Untested networking code creates cascading failures under load that are difficult to diagnose.

### IV. User Experience Consistency

**Latency Requirements**:
- Client-side prediction MUST be implemented for player movement
- Input-to-visual-feedback MUST occur within one client frame (16ms at 60fps)
- Server reconciliation MUST NOT cause visible rubber-banding for movements under 150ms RTT

**Visual Consistency**:
- All players in the same zone MUST see consistent entity positions (within delta compression tolerance)
- Combat events (damage numbers, hit effects) MUST appear synchronized across affected clients

**Error Handling**:
- Connection failures MUST display user-friendly messages (not technical errors)
- Reconnection MUST be automatic with exponential backoff
- Temporary disconnects (under 5 seconds) MUST NOT lose player state

**Rationale**: Players tolerate network imperfection if the game feels responsive and fair. Inconsistent state destroys competitive integrity.

### V. Performance Budgets

All code MUST respect these non-negotiable performance constraints (from `docs/ARCHITECTURE.md`):

| Metric | Budget | Measurement |
|--------|--------|-------------|
| Concurrent Players | 500-1000 per server | Bot client load testing |
| Server Tick Rate | ≥20 Hz under full load | Frame time monitoring |
| Per-Player Bandwidth | <2 KB/s average | Network profiler |
| Client-Server Latency (p95) | <150ms same-region | RTT measurement |
| CPU per Player | <0.5% per player | Server profiling |
| Memory per Player | <5 MB per player | Heap monitoring |

**Implementation Rules**:
- State updates MUST use delta compression (send changes only, not full state)
- Entity updates MUST use interest management (cull entities outside player's area)
- Binary packet format MUST be used for all high-frequency messages
- Server MUST operate at ≤80% capacity (safety margin for spikes)

**Rationale**: These targets define POC success. Code that violates budgets makes scaling impossible.

## Performance Standards

### Bandwidth Optimization (Priority Order)

1. **Delta Compression**: MUST send only changed fields. Full state snapshots reserved for initial sync and reconnection only.
2. **Interest Management**: MUST cull entities outside render distance before network serialization.
3. **Binary Protocol**: High-frequency messages (position updates, inputs) MUST use binary format, not JSON.
4. **Update Frequency Scaling**: Distant entities MUST update at lower frequency than nearby entities.

### CPU Optimization (Priority Order)

1. **Physics Pooling**: Frequently spawned entities (projectiles) MUST use object pooling.
2. **AI Culling**: AI behavior MUST only execute for entities near at least one player.
3. **Batch Processing**: Non-critical operations MUST batch across multiple frames.

## Quality Gates

### Pre-Merge Requirements

All pull requests MUST satisfy:

- [ ] No new GDScript or Go compilation errors
- [ ] Static typing coverage maintained (no untyped public APIs)
- [ ] Client/server code separation verified (no cross-contamination)
- [ ] Performance-critical changes include benchmark results
- [ ] Network protocol changes documented in protocol definition file

### Pre-Release Requirements

Before any release milestone:

- [ ] 500-player stress test passes (20 Hz tick rate maintained)
- [ ] Reconnection test passes (no state loss on 5-second disconnect)
- [ ] Memory leak test passes (24-hour server run, stable memory)
- [ ] All four stress test scenarios pass (Idle, Movement Storm, Combat Chaos, Peak Load)

## Governance

### Amendment Process

1. Proposed changes MUST be documented with rationale
2. Performance budget changes require benchmark evidence
3. Principle removals require migration plan for affected code
4. All amendments MUST update dependent templates (spec, plan, tasks)

### Compliance

- All pull requests MUST reference applicable principles
- Constitution violations MUST be justified in the Complexity Tracking section of implementation plans
- Unjustified violations block merge

### Versioning

- **MAJOR**: Principle removal or redefinition that invalidates existing code
- **MINOR**: New principle added or existing principle materially expanded
- **PATCH**: Clarifications, wording improvements, non-semantic changes

**Version**: 1.0.0 | **Ratified**: 2025-12-04 | **Last Amended**: 2025-12-04
