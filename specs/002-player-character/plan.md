# Implementation Plan: Player Character System

**Branch**: `002-player-character` | **Date**: 2025-12-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-player-character/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

Implement a complete player character system for a top-down multiplayer game featuring 8-directional WASD movement (200 px/s), mouse-based aiming with character rotation, projectile-based shooting with object pooling (400 px/s, 600px range, 16 projectiles/pool), sprite sheet animations via AnimatedSprite2D (idle, walk, attack, hit), and an HP system with damage/death handling. The system must stay within 2ms frame budget and provide debug observability.

## Technical Context

**Language/Version**: GDScript (Godot 4.5)
**Primary Dependencies**: Godot Engine 4.5 (built-in physics, CharacterBody2D, AnimatedSprite2D)
**Storage**: N/A (player state managed in memory; persistence handled by separate systems)
**Testing**: GUT (Godot Unit Testing) or manual playtesting with debug overlay
**Target Platform**: Desktop (Windows, macOS, Linux) - both client and headless server
**Project Type**: Single Godot project with dual client/server exports (monorepo structure)
**Performance Goals**: 2ms per-frame budget per player, 60+ fps, object pooling for projectiles
**Constraints**: <2ms frame budget (scales across all players), 16 projectile pool per player
**Scale/Scope**: Single-player local testing initially, will integrate with networking later

**Existing Infrastructure**:
- Input actions already defined: `move_up`, `move_down`, `move_left`, `move_right`, `shoot`
- GameConstants already contains: `PLAYER_SPEED` (200), `PROJECTILE_SPEED` (400), `PROJECTILE_MAX_DISTANCE` (800), `SHOOT_COOLDOWN` (0.3)
- Collision layers exist but differ from spec: Player(1), Monster(2), Projectile(3), Environment(4)
- Spec requires: Player(1), Environment(2), Player Projectiles(3), Enemy(4)

**Clarifications Resolved** (see [research.md](./research.md)):
1. **Collision layers**: Use existing project.godot config (Player=1, Monster=2, Projectile=3, Environment=4)
2. **Fire rate**: Use GameConstants value (0.3s cooldown)
3. **Projectile range**: Use spec value (600px) via @export, GameConstants (800px) remains for server
4. **Death handling**: Emit signal only; parent systems handle respawn/game over

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Implementation Gates (from Constitution v1.0.0)

| Principle | Requirement | Status | Notes |
|-----------|-------------|--------|-------|
| **I. Server Authority** | Client-side prediction permitted; server reconciles | ✅ PASS | Single-player system; will integrate with existing server validation |
| **II. Code Quality** | Static typing, client/server/shared convention, @export docs | ✅ PASS | Will use static typing throughout; scenes/scripts go in shared/ |
| **III. Test-First** | Tests for network messages, validation logic | ⚠️ N/A | No network protocol changes in this feature |
| **IV. UX Consistency** | Input-to-visual <16ms, no rubber-banding | ✅ PASS | Local-only system, no network latency |
| **V. Performance Budgets** | Object pooling for projectiles, delta compression | ✅ PASS | Projectile pooling specified in requirements |

### Compliance Notes

- **Code Organization**: Player character scenes/scripts will be placed in `client/scenes/shared/` and `client/scripts/shared/` per CLAUDE.md conventions since they're used by both client and server.
- **Static Typing**: All GDScript will use explicit type hints for parameters and return values.
- **Object Pooling**: Projectiles will use pre-allocated pool (16 per player) per NFR-002.
- **Debug Observability**: Toggleable debug overlay per NFR-003.

## Project Structure

### Documentation (this feature)

```text
specs/002-player-character/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
client/                              # Godot 4.5 Project
├── project.godot                   # Project configuration (input actions, layers)
├── scenes/
│   └── shared/                     # Shared entities (used by client and server)
│       ├── player/
│       │   ├── player.tscn         # Player scene (CharacterBody2D root)
│       │   └── debug_overlay.tscn  # Debug HUD overlay (toggleable)
│       └── projectile/
│           └── projectile.tscn     # Projectile scene (Area2D root)
├── scripts/
│   └── shared/
│       ├── player/
│       │   ├── player.gd           # Main player controller script
│       │   ├── hp_component.gd     # Health tracking component
│       │   ├── movement_state.gd   # Movement state machine
│       │   └── debug_overlay.gd    # Debug overlay script
│       └── projectile/
│           ├── projectile.gd       # Single projectile behavior
│           └── projectile_pool.gd  # Object pool manager
└── assets/
    └── sprites/
        └── player/                  # Player sprite sheets (idle, walk, attack, hit)
```

**Structure Decision**: Following the monorepo structure from `CLAUDE.md`, all player character code is placed in `shared/` subdirectories since both client and server need access to player physics, state, and projectile logic. Client-only UI elements (debug overlay) could technically go in `client/` but are placed in `shared/` for simplicity as the server simply won't display them.

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 1 design completion.*

| Principle | Post-Design Status | Verification |
|-----------|-------------------|--------------|
| **I. Server Authority** | ✅ PASS | Player exposes `get_state()`/`apply_state()` for server reconciliation |
| **II. Code Quality** | ✅ PASS | All interfaces use static typing; code in `shared/` directory |
| **III. Test-First** | ⚠️ N/A | No network protocol changes; manual testing via debug overlay |
| **IV. UX Consistency** | ✅ PASS | Input-to-visual within single frame; state machine prevents animation glitches |
| **V. Performance Budgets** | ✅ PASS | ProjectilePool (16 instances); estimated <0.5ms per player |

**All gates pass. Ready for task generation.**

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *None* | - | - |

## Generated Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Research | [research.md](./research.md) | ✅ Complete |
| Data Model | [data-model.md](./data-model.md) | ✅ Complete |
| Contracts | [contracts/player-interface.md](./contracts/player-interface.md) | ✅ Complete |
| Quickstart | [quickstart.md](./quickstart.md) | ✅ Complete |
| Tasks | tasks.md | ⏳ Pending (`/speckit.tasks` command) |
