# Feature Specification: Main Menu UI

**Feature Branch**: `001-main-menu-ui`
**Created**: 2025-12-04
**Status**: Draft
**Input**: User description: "Main Menu UI with play button, exit button, player name input, character creation, region selection, and audio feedback"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Login to Account (Priority: P0)

A player launches the game and needs to authenticate with their existing account to access their character and play.

**Why this priority**: Authentication is required before any other functionality. Without login, players cannot access their characters or game features.

**Independent Test**: Can be fully tested by entering valid credentials on login screen and verifying successful authentication via AuthManager signals.

**Acceptance Scenarios**:

1. **Given** the login screen is displayed, **When** the player enters valid username/password and clicks "Login", **Then** AuthManager authenticates and transitions to main menu (if character exists) or character creation (if no character)
2. **Given** the login screen is displayed, **When** the player enters invalid credentials, **Then** an error message is displayed and player remains on login screen
3. **Given** the player has a saved valid token, **When** the game launches, **Then** the player is automatically logged in and sees main menu or character creation
4. **Given** the login screen is displayed, **When** the API is unreachable, **Then** a modal/alert displays with retry option

---

### User Story 2 - Navigate to Account Registration (Priority: P0)

A new player wants to create an account via the external website to start playing the game.

**Why this priority**: New players must know how to create accounts to access the game.

**Independent Test**: Can be fully tested by clicking "Create Account" on login screen and verifying the external registration URL opens in the user's default browser.

**Acceptance Scenarios**:

1. **Given** the login screen is displayed, **When** the player clicks "Create Account", **Then** the external registration website URL opens in the user's default browser
2. **Given** the browser opens, **When** the player completes registration on the website, **Then** they can return to the game and log in with their new credentials

---

### User Story 3 - Enter Game Arena (Priority: P1)

A logged-in player with an existing character wants to quickly enter the arena to start playing. They click "Enter World" and are connected to the game arena in their selected region.

**Why this priority**: This is the core gameplay entry - players expect to start playing with minimal friction after login.

**Independent Test**: Can be fully tested by clicking "Enter World" on main menu and verifying the player transitions from menu to arena scene and establishes connection to game server.

**Acceptance Scenarios**:

1. **Given** the main menu is displayed with "Enter World" button enabled (character exists), **When** the player clicks "Enter World", **Then** the game transitions to the arena scene and connects to the game server in the selected region
2. **Given** no network connection is available, **When** the player clicks "Enter World", **Then** a modal/alert displays with retry option

---

### User Story 4 - Set Player Identity (Priority: P2)

A newly registered player (or logged-in player without a character) wants to create their character with a unique name before entering the game so other players can identify them in the arena.

**Why this priority**: Player identity is essential for multiplayer interaction. Players need to distinguish themselves from others.

**Independent Test**: Can be fully tested by clicking "Play" as a new player, being redirected to character creation screen, entering a name, clicking "Create", and verifying the character is created and player returns to main menu with character displayed.

**Acceptance Scenarios**:

1. **Given** the player has no existing character and clicks "Play", **When** redirected to character creation screen and enters a valid name (3-16 characters) and clicks "Create", **Then** the character slot is created via the backend API and player returns to main menu with character displayed
2. **Given** the character creation screen is displayed, **When** the player enters an invalid name (too short, too long, or contains prohibited characters), **Then** an appropriate validation error is displayed
3. **Given** the player previously created a character, **When** they launch the game, **Then** their character is displayed on the main menu with "Enter World" button

---

### User Story 5 - Select Game Region (Priority: P2)

A player wants to select their preferred server region to minimize latency and play with others in their geographic area.

**Why this priority**: Region selection directly impacts gameplay quality (latency) and social experience (playing with regional community).

**Independent Test**: Can be fully tested by selecting a region from the dropdown, verifying the selection is saved, and confirming connection attempts use the selected region.

**Acceptance Scenarios**:

1. **Given** the main menu displays a region dropdown, **When** the player clicks the dropdown, **Then** they see options for Asia, Europe, and US-West
2. **Given** the player selects a region, **When** they click "Play", **Then** the game connects to a server in the selected region
3. **Given** the player previously selected a region, **When** they return to the main menu, **Then** their previous selection is preserved

---

### User Story 6 - Exit Game (Priority: P3)

A player wants to close the game application gracefully from the main menu.

**Why this priority**: While essential, exit functionality is straightforward and players can always close via OS controls as a fallback.

**Independent Test**: Can be fully tested by clicking "Exit" and verifying the game application closes cleanly.

**Acceptance Scenarios**:

1. **Given** the main menu is displayed, **When** the player clicks "Exit", **Then** the game application closes gracefully
2. **Given** the player has unsaved preferences, **When** they click "Exit", **Then** preferences are saved before closing

---

### User Story 7 - Experience Menu Ambiance (Priority: P3)

A player experiences an immersive main menu with background music and responsive audio feedback on button interactions.

**Why this priority**: Audio polish enhances user experience but is not required for core functionality.

**Independent Test**: Can be fully tested by observing background music plays on menu load, hearing hover sounds when mousing over buttons, and hearing click sounds when pressing buttons.

**Acceptance Scenarios**:

1. **Given** the main menu loads, **When** the scene is ready, **Then** background music begins playing and loops continuously
2. **Given** any button is displayed, **When** the player hovers over it, **Then** a hover sound plays
3. **Given** any button is displayed, **When** the player clicks it, **Then** a click sound plays
4. **Given** audio is already playing, **When** a new sound is triggered, **Then** sounds do not overlap harshly or cut each other off

---

### Edge Cases

- What happens when login credentials are incorrect? (Display error message from AuthManager; player remains on login screen)
- What happens when saved token is expired on game launch? (AuthManager auto-clears; show login screen)
- What happens when the player enters a name that is already taken in their selected region? (Display error from backend API; name uniqueness is per-region)
- What happens when a player changes region but their name exists in the new region? (Region change is blocked with error message; player must choose a region where their name is available)
- How does system handle connection timeout to the game server? (Display retry option with timeout message)
- How does system handle backend API unreachable during character creation? (Display modal/alert window with error message and retry button; player stays on character creation screen)
- What happens when the player rapidly clicks the play button multiple times? (Disable button after first click to prevent duplicate connections)
- How does the menu handle focus when using keyboard navigation? (Support Tab navigation between controls)
- What happens when audio files fail to load? (Continue without audio, log error)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display a login screen when game launches and user is not authenticated (AuthManager.current_state == LOGGED_OUT)
- **FR-002**: Login screen MUST provide username and password input fields with "Login" button
- **FR-003**: Login screen MUST provide "Create Account" button that opens external registration URL in user's default browser via OS.shell_open()
- **FR-004**: Login screen MUST provide "Forgot Password" link that opens external password reset URL in user's default browser via OS.shell_open()
- **FR-004a**: Registration and password reset URLs MUST be configurable via project settings (export variables or config file)
- **FR-005**: System MUST integrate with existing AuthManager autoload for all authentication operations
- **FR-006**: System MUST handle AuthManager signals (login_successful, login_failed, auth_state_changed)
- **FR-007**: On successful login, if no character exists (character_id is empty), navigate to character creation screen; if character exists, show main menu
- **FR-008**: Main menu MUST provide "Enter World" button to connect to arena (only shown when character exists)
- **FR-009**: System MUST provide an "Exit" button that closes the game application
- **FR-010**: Character creation screen MUST provide a text input field for player name entry (3-16 alphanumeric characters)
- **FR-011**: Character creation screen MUST provide a "Create" button to submit player name and create character slot via backend API (using AuthManager JWT token)
- **FR-012**: Main menu MUST display existing character (name and 2D sprite/portrait) for returning players
- **FR-013**: System MUST provide a dropdown for region selection with options: Asia, Europe, US-West
- **FR-014**: System MUST validate player name input before submission (length, allowed characters)
- **FR-015**: System MUST persist player preferences (region) and auth token between game sessions locally (automatic, no "Remember Me" checkbox)
- **FR-016**: Character creation screen MUST NOT be accessible once a character exists (name is permanent)
- **FR-017**: System MUST allow region changes after character creation via the region dropdown
- **FR-018**: System MUST play looping background music when main menu is displayed
- **FR-019**: System MUST play hover sound effect when cursor enters any interactive button
- **FR-020**: System MUST play click sound effect when any button is pressed
- **FR-021**: System MUST disable buttons while operations are in progress to prevent duplicate requests
- **FR-022**: System MUST display modal/alert dialogs for error messages (invalid credentials, connection failure, API errors)
- **FR-023**: System MUST gracefully handle missing or failed audio assets without crashing
- **FR-024**: Main menu MUST provide "Logout" button to clear session and return to login screen

### Key Entities

- **Player Profile**: Represents the player's identity and preferences (name, selected region, created timestamp)
- **Region**: Available server regions for gameplay (Asia, Europe, US-West)
- **Character Slot**: Backend record linking player name to their game identity

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Players can navigate from launch to arena in under 10 seconds (assuming saved preferences)
- **SC-002**: 95% of name validation errors are caught client-side before API submission
- **SC-003**: Region selection persists correctly across 100% of game restarts
- **SC-004**: All buttons provide audio feedback within 50ms of interaction
- **SC-005**: Background music loops seamlessly without audible gaps or pops
- **SC-006**: Main menu loads and becomes interactive within 3 seconds of game launch

## Clarifications

### Session 2025-12-04

- Q: How many character slots can a player create? → A: Single character only (one slot per account)
- Q: What is the uniqueness scope for character names? → A: Unique per region (same name can exist in different regions)
- Q: Can players modify their character after creation? → A: Region changeable, name permanent
- Q: How should menu state differ for new vs returning players? → A: Separate screens (WoW-style): returning players see character display + "Enter World"; new players pressing Play go to character creation screen first
- Q: What visual representation should the character have on main menu? → A: 2D sprite/portrait of player character
- Q: How should the system behave when the backend API is unreachable during character creation? → A: Show modal/alert window with error and retry button (WoW-style)
- Q: What minimum Godot version should this feature target? → A: Godot 4.5
- Q: What level of logging/observability is needed for menu operations? → A: Basic (errors + key user actions like login, region change)
- Q: How should the client authenticate with the backend API? → A: Use existing AuthManager (JWT auth with username/password); UI integrates login screen only
- Q: How should account registration be handled? → A: External website only; login screen provides "Create Account" button that opens registration URL via OS.shell_open()
- Q: What URL should the "Create Account" button open? → A: Configurable URL in project settings
- Q: Should login include "Remember Me" or auto-persist? → A: Automatic (always persist token)
- Q: Should login screen include "Forgot Password" link? → A: Yes, opens external website URL

## Technical Constraints

- **Engine**: Godot 4.5 (minimum version)
- **Language**: GDScript
- **Observability**: Basic logging (errors + key user actions: character creation, region selection, connection attempts)

## Integration Dependencies

- **AuthManager** (`client/autoload/auth_manager.gd`): Existing JWT authentication singleton
  - Provides: `login()`, `logout()`, `is_logged_in()`, `get_auth_header()`
  - Signals: `login_successful`, `login_failed`, `auth_state_changed`
  - User data from login includes: `user_id`, `username`, `character_id`, `character_name`
- **GameManager**: Existing game state singleton (stores player data via `set_player_data()`)
- **Backend API**: Go server at configurable `api_base_url` (default: `http://localhost:8080`)
  - `/api/auth/login` - POST username/password
  - `/api/auth/refresh` - POST refresh token
- **External Registration Website**: URL for account creation (configurable; opened via `OS.shell_open()`)

## Assumptions

- Players have exactly one character slot per account (no multi-character support in initial release)
- Character 2D sprite/portrait asset will be provided for display on main menu
- Backend API for character slot creation exists and follows standard REST conventions
- Audio assets (music, hover sound, click sound) will be provided as .ogg or .wav files
- Game server addresses for each region are configured in the network layer
- Player preferences can be stored locally using Godot's user:// filesystem
- Default region is US-West if no previous selection exists
- Alphanumeric characters include a-z, A-Z, 0-9, and underscore
