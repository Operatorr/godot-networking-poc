# Tasks: Main Menu UI

**Input**: Design documents from `/specs/001-main-menu-ui/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: Not explicitly requested - test tasks omitted per Task Generation Rules.

**Organization**: Tasks grouped by user story priority (P0 → P3) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Exact file paths included in descriptions

## Path Conventions

- **Godot Client**: `client/scenes/`, `client/scripts/`, `client/autoload/`
- **Go API**: `api/internal/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and scene/script structure creation

- [ ] T001 Create menus directory structure at client/scenes/client/menus/
- [ ] T002 Create components directory at client/scenes/client/menus/components/
- [ ] T003 Create UI scripts directory at client/scripts/client/ui/
- [ ] T004 [P] Add placeholder audio files at client/assets/audio/sfx/button_hover.ogg and client/assets/audio/sfx/button_click.ogg

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure required by ALL user stories before implementation begins

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 Add LOGIN scene constant and SceneName.LOGIN enum value to client/autoload/scene_manager.gd
- [ ] T006 Add goto_login() convenience method to client/autoload/scene_manager.gd
- [ ] T007 Add goto_character_creation() method to client/autoload/scene_manager.gd (if not exists)
- [ ] T008 Update SceneManager._ready() to check AuthManager state and route to login/main_menu/character_creation in client/autoload/scene_manager.gd
- [ ] T009 [P] Create RegionInfo class in client/scripts/client/region_info.gd (per data-model.md)
- [ ] T010 [P] Create UserPreferences class in client/scripts/client/user_preferences.gd (per data-model.md)
- [ ] T011 [P] Create reusable ErrorDialog scene at client/scenes/client/menus/components/error_dialog.tscn (PopupPanel with title, message, retry/close buttons)
- [ ] T012 [P] Create ErrorDialog controller script at client/scripts/client/ui/error_dialog.gd (signals: retry_pressed, closed)
- [ ] T013 Add button_hover and button_click sounds to AudioManager audio_library in client/autoload/audio_manager.gd
- [ ] T014 Add play_button_hover() and play_button_click() methods to AudioManager in client/autoload/audio_manager.gd (if not exists)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Login to Account (Priority: P0) 🎯 MVP

**Goal**: Players can authenticate with username/password and navigate to main menu or character creation

**Independent Test**: Enter valid credentials on login screen, verify AuthManager authenticates and transitions to correct screen

### Implementation for User Story 1

- [ ] T015 [US1] Create login_screen.tscn scene with VBoxContainer layout at client/scenes/client/menus/login_screen.tscn
- [ ] T016 [US1] Add username LineEdit with placeholder text to login_screen.tscn
- [ ] T017 [US1] Add password LineEdit with secret mode enabled to login_screen.tscn
- [ ] T018 [US1] Add Login button to login_screen.tscn
- [ ] T019 [US1] Add focus neighbors for Tab navigation between username, password, and Login button in login_screen.tscn
- [ ] T020 [US1] Create login_screen.gd script at client/scripts/client/login_screen.gd
- [ ] T021 [US1] Connect AuthManager signals (login_successful, login_failed) in login_screen.gd
- [ ] T022 [US1] Implement _on_login_pressed() to call AuthManager.login(username, password) in login_screen.gd
- [ ] T023 [US1] Implement _on_login_successful(user_data) to navigate to main_menu or character_creation based on character_id in login_screen.gd
- [ ] T024 [US1] Implement _on_login_failed(error) to show ErrorDialog with error message in login_screen.gd
- [ ] T025 [US1] Add auto-login check on _ready() for saved valid token via AuthManager.is_logged_in() in login_screen.gd
- [ ] T026 [US1] Disable Login button while login is in progress to prevent duplicate requests in login_screen.gd
- [ ] T027 [US1] Instance ErrorDialog component in login_screen.tscn
- [ ] T028 [US1] Handle API unreachable error with retry option via ErrorDialog in login_screen.gd

**Checkpoint**: User Story 1 (Login) is fully functional and testable independently

---

## Phase 4: User Story 2 - Navigate to Account Registration (Priority: P0)

**Goal**: New players can access external registration website from login screen

**Independent Test**: Click "Create Account" on login screen, verify external URL opens in default browser

### Implementation for User Story 2

- [ ] T029 [US2] Add Create Account button to login_screen.tscn below Login button
- [ ] T030 [US2] Add Forgot Password link/button to login_screen.tscn
- [ ] T031 [US2] Add @export var registration_url: String to login_screen.gd with default URL
- [ ] T032 [US2] Add @export var forgot_password_url: String to login_screen.gd with default URL
- [ ] T033 [US2] Implement _on_create_account_pressed() to call OS.shell_open(registration_url) in login_screen.gd
- [ ] T034 [US2] Implement _on_forgot_password_pressed() to call OS.shell_open(forgot_password_url) in login_screen.gd

**Checkpoint**: User Stories 1 AND 2 (Login + Registration Link) are both working

---

## Phase 5: User Story 3 - Enter Game Arena (Priority: P1)

**Goal**: Players with existing character can click "Enter World" to connect to arena

**Independent Test**: Click "Enter World" on main menu, verify transition to arena scene with server connection

### Implementation for User Story 3

- [ ] T035 [US3] Create or modify main_menu.tscn at client/scenes/client/menus/main_menu.tscn with VBoxContainer layout
- [ ] T036 [US3] Add character display panel (TextureRect for portrait, Label for name) to main_menu.tscn
- [ ] T037 [US3] Add Enter World button (visible only when character exists) to main_menu.tscn
- [ ] T038 [US3] Create or modify main_menu.gd script at client/scripts/client/main_menu.gd
- [ ] T039 [US3] Implement _update_character_display() to show character name and portrait from GameManager.player_data in main_menu.gd
- [ ] T040 [US3] Toggle Enter World button visibility based on character existence in main_menu.gd
- [ ] T041 [US3] Implement _on_enter_world_pressed() to transition to arena scene via SceneManager in main_menu.gd
- [ ] T042 [US3] Disable Enter World button after click to prevent duplicate connections in main_menu.gd
- [ ] T043 [US3] Instance ErrorDialog component in main_menu.tscn
- [ ] T044 [US3] Handle connection failure with retry option via ErrorDialog in main_menu.gd

**Checkpoint**: User Story 3 (Enter Arena) is functional for players with characters

---

## Phase 6: User Story 4 - Set Player Identity (Priority: P2)

**Goal**: New players create character with unique name before entering game

**Independent Test**: Login as new player, enter name, click Create, verify character created and returned to main menu

### Implementation for User Story 4

- [ ] T045 [US4] Create character_creation.tscn scene at client/scenes/client/menus/character_creation.tscn
- [ ] T046 [US4] Add name input LineEdit with max_length=16 to character_creation.tscn
- [ ] T047 [US4] Add name validation feedback Label (for inline errors) to character_creation.tscn
- [ ] T048 [US4] Add Create button to character_creation.tscn
- [ ] T049 [US4] Add focus neighbors for Tab navigation between name input and Create button in character_creation.tscn
- [ ] T050 [US4] Create character_creation.gd script at client/scripts/client/character_creation.gd
- [ ] T051 [US4] Implement validate_character_name(name) with regex ^[a-zA-Z0-9_]+$ and length 3-16 in character_creation.gd
- [ ] T052 [US4] Implement real-time validation on name input text_changed signal in character_creation.gd
- [ ] T053 [US4] Disable Create button when validation fails in character_creation.gd
- [ ] T054 [US4] Implement _on_create_pressed() to POST to /api/character/create with JWT auth in character_creation.gd
- [ ] T055 [US4] Handle successful creation: update GameManager.player_data and navigate to main_menu in character_creation.gd
- [ ] T056 [US4] Instance ErrorDialog component in character_creation.tscn
- [ ] T057 [US4] Handle server errors (name taken, API error) with ErrorDialog and retry in character_creation.gd
- [ ] T058 [US4] Disable Create button while request is in progress in character_creation.gd

**Checkpoint**: User Story 4 (Character Creation) is functional for new players

---

## Phase 7: User Story 5 - Select Game Region (Priority: P2)

**Goal**: Players select server region for optimal latency

**Independent Test**: Open region dropdown, select region, verify selection persists across restarts

### Implementation for User Story 5

- [ ] T059 [US5] Add region dropdown (OptionButton) to main_menu.tscn
- [ ] T060 [US5] Implement _fetch_regions() to GET /api/regions and populate dropdown in main_menu.gd
- [ ] T061 [US5] Display region status and player count in dropdown items in main_menu.gd
- [ ] T062 [US5] Load saved region preference on _ready() via UserPreferences.load() in main_menu.gd
- [ ] T063 [US5] Implement _on_region_selected() to update GameManager.player_data.selected_region in main_menu.gd
- [ ] T064 [US5] Save region preference to user://preferences.json via UserPreferences.save() in main_menu.gd
- [ ] T065 [US5] Disable unavailable regions (offline or full) in dropdown in main_menu.gd

**Checkpoint**: User Story 5 (Region Selection) is functional with persistence

---

## Phase 8: User Story 6 - Exit Game (Priority: P3)

**Goal**: Players can close the game gracefully from main menu

**Independent Test**: Click Exit, verify game closes cleanly with preferences saved

### Implementation for User Story 6

- [ ] T066 [US6] Add Exit button to main_menu.tscn
- [ ] T067 [US6] Implement _on_exit_pressed() to save preferences and call get_tree().quit() in main_menu.gd

**Checkpoint**: User Story 6 (Exit Game) is functional

---

## Phase 9: User Story 7 - Experience Menu Ambiance (Priority: P3)

**Goal**: Players experience immersive audio feedback in menus

**Independent Test**: Observe background music on menu load, hear hover/click sounds on button interactions

### Implementation for User Story 7

- [ ] T068 [US7] Start background music playback on main_menu _ready() via AudioManager in main_menu.gd
- [ ] T069 [US7] Add all buttons to "menu_buttons" group in login_screen.tscn
- [ ] T070 [US7] Add all buttons to "menu_buttons" group in main_menu.tscn
- [ ] T071 [US7] Add all buttons to "menu_buttons" group in character_creation.tscn
- [ ] T072 [US7] Implement button audio connection helper _setup_button_audio() in each menu script (login_screen.gd, main_menu.gd, character_creation.gd)
- [ ] T073 [US7] Connect mouse_entered signal to AudioManager.play_button_hover() for all menu buttons
- [ ] T074 [US7] Connect pressed signal to AudioManager.play_button_click() for all menu buttons
- [ ] T075 [US7] Handle missing audio assets gracefully (log error, continue without crash) in AudioManager

**Checkpoint**: User Story 7 (Audio Ambiance) is functional with graceful degradation

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Final improvements affecting multiple user stories

- [ ] T076 Add Logout button to main_menu.tscn
- [ ] T077 Implement _on_logout_pressed() to call AuthManager.logout() and navigate to login screen in main_menu.gd
- [ ] T078 [P] Verify Tab keyboard navigation works across all menu screens
- [ ] T079 [P] Verify all buttons disable during async operations (no duplicate requests)
- [ ] T080 [P] Add basic logging for key user actions (login, character creation, region selection) per spec
- [ ] T081 Validate full flow per quickstart.md testing checklist

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
- **User Stories (Phases 3-9)**: All depend on Foundational phase completion
  - US1 (Login) → US2 (Registration) builds on login_screen
  - US3 (Enter Arena) → US5 (Region) → US6 (Exit) → US7 (Audio) share main_menu
  - US4 (Character Creation) independent of main_menu
- **Polish (Phase 10)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P0)**: Foundational only - First to implement
- **US2 (P0)**: Builds on US1 (adds to login_screen.tscn)
- **US3 (P1)**: Foundational only - Can start after US1+US2 or in parallel (different scene)
- **US4 (P2)**: Foundational only - Can start in parallel with US3 (different scene)
- **US5 (P2)**: Builds on US3 (adds to main_menu.tscn)
- **US6 (P3)**: Builds on US3/US5 (adds to main_menu.tscn)
- **US7 (P3)**: Builds on all scenes (adds audio to all)

### Parallel Opportunities

**Within Setup (Phase 1)**:
- T004 (audio placeholders) can run parallel to T001-T003

**Within Foundational (Phase 2)**:
- T009, T010, T011, T012 (classes/scenes) can run in parallel
- T013, T014 (AudioManager) sequential
- T005-T008 (SceneManager) sequential

**User Stories**:
- US3 (main_menu) and US4 (character_creation) can run in parallel
- US1+US2 (login_screen) must complete before US3/US4 for full flow testing

---

## Parallel Example: Foundational Phase

```bash
# Launch in parallel (different files):
Task: "Create RegionInfo class in client/scripts/client/region_info.gd"
Task: "Create UserPreferences class in client/scripts/client/user_preferences.gd"
Task: "Create reusable ErrorDialog scene at client/scenes/client/menus/components/error_dialog.tscn"
Task: "Create ErrorDialog controller script at client/scripts/client/ui/error_dialog.gd"
```

## Parallel Example: User Stories 3 & 4

```bash
# After Foundational complete, launch in parallel:
Task: "Create or modify main_menu.tscn" (US3)
Task: "Create character_creation.tscn scene" (US4)
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: User Story 1 (Login)
4. Complete Phase 4: User Story 2 (Registration Link)
5. **STOP and VALIDATE**: Test login flow independently
6. Players can now authenticate and access registration

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1+US2 → Test login → Deploy (MVP with auth)
3. Add US3+US4 → Test character flow → Deploy (character creation + arena entry)
4. Add US5 → Test region selection → Deploy (region preference)
5. Add US6+US7 → Test polish → Deploy (exit + audio)
6. Complete Phase 10 → Final validation

### Parallel Team Strategy

With multiple developers after Foundational phase:
- Developer A: US1 + US2 (login_screen.tscn/gd)
- Developer B: US3 + US5 + US6 (main_menu.tscn/gd)
- Developer C: US4 (character_creation.tscn/gd)
- Then US7 (audio) after other stories merge

---

## Notes

- [P] tasks = different files, no dependencies on other [P] tasks
- [USn] label maps task to specific user story for traceability
- Each user story is independently testable after its phase completes
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Audio files (T004) are placeholders - replace with real assets when available
