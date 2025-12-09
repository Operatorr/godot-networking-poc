# Implementation Plan: Main Menu UI

**Branch**: `001-main-menu-ui` | **Date**: 2025-12-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-main-menu-ui/spec.md`

## Summary

Implement a complete Main Menu UI system for the Omega Networking multiplayer game client featuring authentication (login screen with external registration), character creation for new players, region selection, and audio feedback. The system integrates with the existing AuthManager for JWT authentication and GameManager for player state, routing players to either main menu (returning players) or character creation (new players) based on character existence.

## Technical Context

**Language/Version**: GDScript (Godot 4.5)
**Backend Language**: Go 1.21+
**Primary Dependencies**:
- Godot 4.5 (Engine)
- Existing autoloads: AuthManager, GameManager, SceneManager, AudioManager, NetworkManager
- Go API server with existing handlers: auth, character, region

**Storage**:
- Server: PostgreSQL (users, characters), Redis (sessions, regions)
- Client: `user://` filesystem (settings.json, auth_token.dat)

**Testing**: Manual integration testing (Godot client against API server)

**Target Platform**: Desktop (Windows, macOS, Linux)

**Project Type**: Monorepo (Godot client + Go API)

**Performance Goals**:
- Menu load < 3 seconds (SC-006)
- Launch to arena < 10 seconds with saved preferences (SC-001)
- Audio feedback < 50ms (SC-004)

**Constraints**:
- Single character slot per account
- Character names unique per region
- Name: 3-16 alphanumeric characters + underscore
- External registration (browser redirect)

**Scale/Scope**: 3 main screens (Login, Main Menu, Character Creation) + modal dialogs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Server Authority | PASS | Character creation validated server-side; name uniqueness enforced by API |
| II. Code Quality Standards | PASS | All scripts will use static typing; follow client/server/shared convention |
| III. Test-First for Critical Paths | N/A | Menu UI is not a critical networking path (auth is via existing AuthManager) |
| IV. User Experience Consistency | PASS | Error handling with user-friendly messages; connection retry with clear feedback |
| V. Performance Budgets | N/A | Menu UI does not impact server tick rate or bandwidth budgets |

**Pre-Design Gate**: PASS - No violations requiring justification.

## Project Structure

### Documentation (this feature)

```text
specs/001-main-menu-ui/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (via /speckit.tasks)
```

### Source Code (repository root)

```text
client/
├── scenes/
│   └── client/
│       └── menus/
│           ├── login_screen.tscn          # NEW: Login UI
│           ├── main_menu.tscn             # MODIFY: Add character display, region selector
│           ├── character_creation.tscn    # NEW: Character creation UI
│           └── components/
│               └── error_dialog.tscn      # NEW: Reusable error modal
│
├── scripts/
│   └── client/
│       ├── login_screen.gd                # NEW: Login logic
│       ├── main_menu.gd                   # MODIFY: Existing main menu
│       ├── character_creation.gd          # NEW: Character creation logic
│       └── ui/
│           └── error_dialog.gd            # NEW: Error dialog controller
│
├── autoload/
│   ├── auth_manager.gd                    # EXISTING: No changes needed
│   ├── game_manager.gd                    # EXISTING: No changes needed
│   ├── scene_manager.gd                   # EXISTING: Paths already defined
│   └── audio_manager.gd                   # EXISTING: Add button_hover/click sounds
│
└── assets/
    └── audio/
        └── sfx/
            ├── button_hover.ogg           # NEW: Hover sound asset
            └── button_click.ogg           # NEW: Click sound asset

api/
├── cmd/server/main.go                     # EXISTING: No changes needed
└── internal/
    └── handlers/
        └── character.go                   # EXISTING: Character creation endpoint ready
```

**Structure Decision**: Follows existing monorepo structure defined in CLAUDE.md. New UI scenes go in `client/scenes/client/menus/`. Scripts in `client/scripts/client/`. Audio assets in `client/assets/audio/sfx/`.

## Complexity Tracking

> No violations identified. All functionality fits within existing architecture.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |

## Phase 0: Research Summary

See [research.md](./research.md) for detailed findings.

### Key Decisions

1. **UI Framework**: Native Godot Control nodes (no external UI framework)
2. **Scene Structure**: Three separate scenes (Login, MainMenu, CharacterCreation) with SceneManager transitions
3. **Error Handling**: Custom modal dialog component for all error states
4. **Audio Integration**: Use existing AudioManager with new sound assets
5. **Region Data**: Fetched from API `/api/regions` endpoint at runtime

## Phase 1: Design Artifacts

- [data-model.md](./data-model.md) - Client-side data structures
- [contracts/](./contracts/) - API contract definitions
- [quickstart.md](./quickstart.md) - Development setup guide
