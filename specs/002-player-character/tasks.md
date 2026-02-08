# Tasks: Player Character System

**Input**: Design documents from `/specs/002-player-character/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/player-interface.md ✅, quickstart.md ✅

**Tests**: No automated tests requested - manual testing via debug overlay and quickstart.md scenarios

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md monorepo structure:
- Scenes: `client/scenes/shared/`
- Scripts: `client/scripts/shared/`
- Assets: `client/assets/sprites/player/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, directory structure, and placeholder assets

- [X] T001 Create directory structure for player character system: `client/scenes/shared/player/`, `client/scenes/shared/projectile/`, `client/scripts/shared/player/`, `client/scripts/shared/projectile/`
- [X] T002 [P] Add `toggle_debug` input action to `client/project.godot` (key: F3)
- [X] T003 [P] Create placeholder sprite assets in `client/assets/sprites/player/` (32x32 colored squares for player, 16x16 for projectile) - Using PlaceholderTexture2D

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core components that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Create base player scene `client/scenes/shared/player/player.tscn` with CharacterBody2D root, AnimatedSprite2D, CollisionShape2D (CircleShape2D r=16), configure collision layer 1 and mask 2,4
- [X] T005 Create base player script `client/scripts/shared/player/player.gd` with exported properties (speed, projectile_range, fire_rate), MovementState and ActionState enums, static typing
- [X] T006 [P] Create HPComponent script `client/scripts/shared/player/hp_component.gd` with max_hp, current_hp, is_dead properties, take_damage(), heal(), reset(), set_hp() methods, hp_changed and died signals
- [X] T007 [P] Create projectile scene `client/scenes/shared/projectile/projectile.tscn` with Area2D root, Sprite2D, CollisionShape2D (CircleShape2D r=8), configure collision layer 3 and mask 2,4
- [X] T008 [P] Create projectile script `client/scripts/shared/projectile/projectile.gd` with speed, max_distance, damage, direction, distance_traveled properties, activate(), deactivate() methods, hit signal
- [X] T009 Create ProjectilePool script `client/scripts/shared/projectile/projectile_pool.gd` with POOL_SIZE=16 constant, pool and active_projectiles arrays, spawn(), return_projectile(), get_active_count(), deactivate_all() methods
- [X] T010 Add HPComponent node to player scene, add ShootCooldownTimer (Timer, wait_time=0.3, one_shot=true) to player scene in `client/scenes/shared/player/player.tscn`
- [X] T011 Add ProjectilePool node as child of player in `client/scenes/shared/player/player.tscn`, wire up pool to instantiate 16 projectiles on _ready()

**Checkpoint**: Foundation ready - Player scene exists with all child nodes, projectile pool initialized, HP component functional

---

## Phase 3: User Story 1 - Core Movement (Priority: P1) 🎯 MVP

**Goal**: Player can move in 8 directions using WASD at 200 px/s with normalized diagonal speed

**Independent Test**: Spawn player in empty scene, press WASD keys, verify 8-directional movement occurs smoothly at consistent speed

### Implementation for User Story 1

- [X] T012 [US1] Implement movement input handling in `client/scripts/shared/player/player.gd` using Input.get_vector() for move_left/right/up/down actions
- [X] T013 [US1] Implement _physics_process() movement in `client/scripts/shared/player/player.gd` with velocity assignment and move_and_slide(), set motion_mode to MOTION_MODE_FLOATING
- [X] T014 [US1] Implement MovementState transitions (IDLE ↔ WALKING) in `client/scripts/shared/player/player.gd` based on input vector being zero or non-zero
- [X] T015 [US1] Add state getter methods get_state_name() and is_dead property accessor in `client/scripts/shared/player/player.gd`

**Checkpoint**: Player moves in all 8 directions with normalized diagonal speed, stops when keys released

---

## Phase 4: User Story 2 - Mouse Aiming (Priority: P2)

**Goal**: Player character rotates to continuously face the mouse cursor position

**Independent Test**: Move mouse cursor around screen, verify character rotates to face cursor position continuously

### Implementation for User Story 2

- [X] T016 [US2] Implement mouse aiming in _physics_process() of `client/scripts/shared/player/player.gd` using get_global_mouse_position() and rotation = direction.angle()
- [X] T017 [US2] Handle edge case when mouse at player position in `client/scripts/shared/player/player.gd` - use last_aim_direction fallback, update last_aim_direction when valid direction exists

**Checkpoint**: Player rotates to face mouse cursor, handles edge case of mouse directly on player

---

## Phase 5: User Story 3 - Shooting Mechanics (Priority: P3)

**Goal**: Player fires projectiles toward mouse cursor on left-click with fire rate limiting and 600px range

**Independent Test**: Click mouse, verify projectile spawns and travels toward cursor, despawns at 600px

### Implementation for User Story 3

- [X] T018 [US3] Implement shoot input detection in `client/scripts/shared/player/player.gd` checking for "shoot" action and ShootCooldownTimer.is_stopped()
- [X] T019 [US3] Implement _shoot() method in `client/scripts/shared/player/player.gd` that gets projectile from pool, calculates spawn offset, starts cooldown timer, emits shot_fired signal
- [X] T020 [US3] Implement projectile _physics_process() movement in `client/scripts/shared/projectile/projectile.gd` with delta-based movement, distance tracking, deactivate when max_distance reached
- [X] T021 [US3] Implement projectile collision handling in `client/scripts/shared/projectile/projectile.gd` using body_entered signal, emit hit signal, call deactivate()
- [X] T022 [US3] Connect projectile deactivation to pool return in `client/scripts/shared/projectile/projectile_pool.gd` return_projectile() method

**Checkpoint**: Projectiles fire on click, travel toward cursor, despawn at range limit or on collision, pool recycles oldest when exhausted

---

## Phase 6: User Story 4 - Animation States (Priority: P4)

**Goal**: Player displays appropriate animations for idle, walking, attacking, and taking damage

**Independent Test**: Perform each action (stand still, move, shoot, take damage) and verify corresponding animation plays

### Implementation for User Story 4

- [X] T023 [US4] Create SpriteFrames resource with idle, walk, attack, hit animations using placeholder sprites, attach to AnimatedSprite2D in `client/scenes/shared/player/player.tscn`
- [X] T024 [US4] Implement animation switching in `client/scripts/shared/player/player.gd` _update_animation() method calling AnimatedSprite2D.play() based on current movement_state and action_state
- [X] T025 [US4] Wire animation_finished signal to _on_animation_finished() in `client/scripts/shared/player/player.gd` to transition back from ATTACKING/HIT to NONE
- [X] T026 [US4] Trigger attack animation when shooting by setting action_state to ATTACKING in _shoot() method in `client/scripts/shared/player/player.gd`
- [X] T027 [US4] Trigger hit animation when taking damage by setting action_state to HIT in take_damage() method in `client/scripts/shared/player/player.gd`

**Checkpoint**: All animation states display correctly, one-shot animations (attack, hit) return to idle/walk

---

## Phase 7: User Story 5 - Health System (Priority: P5)

**Goal**: Player has HP that decreases on damage and triggers death when depleted

**Independent Test**: Apply damage via debug input, verify HP decreases, verify death state triggers at 0 HP

### Implementation for User Story 5

- [X] T028 [US5] Implement Player.take_damage() wrapper in `client/scripts/shared/player/player.gd` that calls hp_component.take_damage() and triggers HIT animation
- [X] T029 [US5] Implement Player.heal() wrapper in `client/scripts/shared/player/player.gd` that calls hp_component.heal()
- [X] T030 [US5] Connect HPComponent.died signal to _on_hp_component_died() in `client/scripts/shared/player/player.gd`, set action_state to DEAD, disable input processing
- [X] T031 [US5] Implement Player.reset() in `client/scripts/shared/player/player.gd` that calls hp_component.reset(), sets states to initial values, deactivates all projectiles
- [X] T032 [US5] Implement NFR-005 state validation in HPComponent.set_hp() in `client/scripts/shared/player/hp_component.gd` - clamp HP to [0, max_hp], log warning on auto-correction

**Checkpoint**: HP system fully functional, death state blocks all processing, reset enables respawn

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Debug overlay, networking hooks, state serialization, final integration

- [X] T033 [P] Create debug overlay scene `client/scenes/shared/player/debug_overlay.tscn` with CanvasLayer root and Label child
- [X] T034 [P] Create debug overlay script `client/scripts/shared/player/debug_overlay.gd` with toggle on toggle_debug input, display HP, position, state, velocity
- [X] T035 Add DebugOverlay as child of player in `client/scenes/shared/player/player.tscn`, wire target_player reference
- [X] T036 Implement get_state() method in `client/scripts/shared/player/player.gd` returning Dictionary with position, rotation, velocity, hp, max_hp, movement_state, action_state, is_dead
- [X] T037 Implement apply_state() method in `client/scripts/shared/player/player.gd` applying Dictionary values for server reconciliation
- [X] T038 Implement set_input_enabled() method in `client/scripts/shared/player/player.gd` to enable/disable input processing for pause/menu states
- [X] T039 Create test scene `client/scenes/test/player_test.tscn` per quickstart.md with Node2D root and instanced player
- [ ] T040 Run quickstart.md validation - verify all controls work, debug overlay toggles, HP system responds to damage

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational phase completion
- **User Story 2 (Phase 4)**: Depends on Foundational phase completion (can run parallel to US1)
- **User Story 3 (Phase 5)**: Depends on Foundational phase completion (can run parallel to US1/US2)
- **User Story 4 (Phase 6)**: Depends on US1 (movement states) and US3 (shooting for attack animation)
- **User Story 5 (Phase 7)**: Depends on Foundational phase (HPComponent must exist)
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - No dependencies on other stories ✅ MVP
- **User Story 2 (P2)**: Can start after Foundational - Independent of US1
- **User Story 3 (P3)**: Can start after Foundational - Independent of US1/US2 (uses aiming direction but can use rotation)
- **User Story 4 (P4)**: Soft dependency on US1 (walk animation) and US3 (attack animation) - can stub with placeholders
- **User Story 5 (P5)**: Can start after Foundational - Independent of other stories

### Within Each User Story

- Core implementation before integration
- State changes before animations
- Story complete before moving to next priority (recommended) or parallel implementation

### Parallel Opportunities

**Phase 1 (Setup)**: T002 and T003 can run in parallel with T001

**Phase 2 (Foundational)**:
- T006, T007, T008 can run in parallel (different files)
- T004 and T005 must complete before T010 and T011

**User Stories (Phases 3-7)**:
- US1, US2, US3, US5 can be developed in parallel after Foundational
- US4 depends on movement states (US1) and shooting (US3)

**Phase 8 (Polish)**:
- T033 and T034 can run in parallel (scene vs script)
- T036, T037, T038 are sequential (same file)

---

## Parallel Example: Foundational Phase

```bash
# After T004 and T005 complete, launch these in parallel:
Task: "Create HPComponent script" (T006)
Task: "Create projectile scene" (T007)
Task: "Create projectile script" (T008)
```

## Parallel Example: User Stories 1-3

```bash
# After Foundational phase, can launch in parallel:
Task: "Implement movement input handling" (T012) - US1
Task: "Implement mouse aiming" (T016) - US2
Task: "Implement shoot input detection" (T018) - US3
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 - Core Movement
4. **STOP and VALIDATE**: Test player movement independently using quickstart.md
5. Deploy/demo if ready - Player can move in 8 directions

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test movement → **MVP Complete**
3. Add User Story 2 → Test aiming → Player can move and aim
4. Add User Story 3 → Test shooting → Player can move, aim, and shoot
5. Add User Story 4 → Test animations → Full visual feedback
6. Add User Story 5 → Test HP system → Complete gameplay loop
7. Polish phase → Debug overlay, networking hooks

### Suggested MVP Scope

**Minimum Viable Player**: User Stories 1-3 (Movement, Aiming, Shooting)
- This gives a playable character that can navigate and attack
- Animation and HP can be added incrementally

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Use existing collision layers from project.godot (Player=1, Monster=2, Projectile=3, Environment=4)
- Use existing input actions (move_up/down/left/right, shoot) - only add toggle_debug
