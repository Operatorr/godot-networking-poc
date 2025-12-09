# Feature Specification: Player Character System

**Feature Branch**: `002-player-character`
**Created**: 2025-12-09
**Status**: Draft
**Input**: User description: "Player Character System with base scene, movement, animations, aiming, shooting, and HP system"

## Clarifications

### Session 2025-12-09

- Q: What should the player movement speed be? → A: 200 pixels/second (configurable via exported variable for testing)
- Q: What should the projectile speed and maximum range be? → A: 400 px/s speed, 600px range (both configurable via @export variables)
- Q: How should character animations be implemented? → A: AnimatedSprite2D with sprite sheets
- Q: What game perspective should be used? → A: True top-down (camera directly above, simple rotation math)
- Q: What collision layers should be used? → A: 4 layers - Player (1), Environment (2), Player Projectiles (3), Enemy (4)
- Q: What frame budget should the player character system stay within per frame? → A: 2ms per frame (scales across all players, verify during stress testing)
- Q: Should projectiles use object pooling to manage memory allocation? → A: Yes, implement object pooling with pre-allocated pool
- Q: What level of debug observability should the player character system provide? → A: Debug overlay showing HP, position, state, velocity (toggleable)
- Q: What should be the maximum number of active projectiles per player (pool size)? → A: 16 projectiles per player
- Q: How should the system handle invalid or corrupted player state? → A: Auto-correct to valid state and log warning

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Core Movement (Priority: P1)

As a player, I want to move my character in any direction using WASD keys so that I can navigate the game world freely and responsively.

**Why this priority**: Movement is the most fundamental player interaction. Without movement, no other gameplay mechanics can be tested or experienced. This is the foundation upon which all other character features depend.

**Independent Test**: Can be fully tested by spawning a player character in an empty scene, pressing WASD keys, and verifying 8-directional movement occurs smoothly. Delivers the core navigational value.

**Acceptance Scenarios**:

1. **Given** a player character on screen, **When** I press W, **Then** the character moves upward
2. **Given** a player character on screen, **When** I press S, **Then** the character moves downward
3. **Given** a player character on screen, **When** I press A, **Then** the character moves left
4. **Given** a player character on screen, **When** I press D, **Then** the character moves right
5. **Given** a player character on screen, **When** I press W+D simultaneously, **Then** the character moves diagonally up-right at normalized speed
6. **Given** a moving character, **When** I release all movement keys, **Then** the character stops moving and transitions to idle state

---

### User Story 2 - Mouse Aiming (Priority: P2)

As a player, I want my character to aim toward my mouse cursor so that I can target enemies and objects intuitively.

**Why this priority**: Aiming is essential for the shooting mechanic and provides visual feedback about where the player is facing. This must work before shooting can be implemented.

**Independent Test**: Can be tested by moving the mouse cursor around the screen and verifying the character rotates to face the cursor position continuously.

**Acceptance Scenarios**:

1. **Given** a player character on screen, **When** I move my mouse cursor, **Then** the character rotates to face the cursor position
2. **Given** a player character aiming right, **When** I move my cursor to the left side of the character, **Then** the character rotates to face left
3. **Given** a player character moving, **When** I move my mouse cursor, **Then** the character continues moving while rotating to face the cursor

---

### User Story 3 - Shooting Mechanics (Priority: P3)

As a player, I want to shoot projectiles toward my mouse cursor when I click so that I can attack enemies and interact with the game world offensively.

**Why this priority**: Shooting is the primary offensive action. It depends on the aiming system (P2) being functional and provides the core combat loop.

**Independent Test**: Can be tested by clicking the mouse and verifying a projectile spawns and travels toward the cursor position.

**Acceptance Scenarios**:

1. **Given** a player character aiming at a position, **When** I left-click, **Then** a projectile spawns at the character and travels toward the aim direction
2. **Given** a projectile in flight, **When** it travels beyond maximum range, **Then** the projectile is destroyed
3. **Given** a player character, **When** I hold left-click, **Then** the character fires at the defined fire rate (no instant continuous fire)

---

### User Story 4 - Animation States (Priority: P4)

As a player, I want to see my character animate appropriately based on their current action so that the game feels responsive and alive.

**Why this priority**: Animations enhance visual feedback but are not strictly required for gameplay mechanics to function. The game can work with placeholder visuals.

**Independent Test**: Can be tested by performing each action (standing, moving, shooting, taking damage) and verifying appropriate animations play.

**Acceptance Scenarios**:

1. **Given** a stationary character, **When** no input is provided, **Then** the idle animation plays
2. **Given** a stationary character, **When** I press a movement key, **Then** the walk animation plays
3. **Given** a character, **When** I left-click to shoot, **Then** the attack animation plays
4. **Given** a character with HP, **When** the character takes damage, **Then** the hit animation plays briefly

---

### User Story 5 - Health System (Priority: P5)

As a player, I want my character to have health points that decrease when taking damage and result in death when depleted so that there are stakes and consequences in gameplay.

**Why this priority**: HP system creates game stakes but requires other systems (like projectiles hitting targets) to fully test damage scenarios. Can be initially tested with debug commands.

**Independent Test**: Can be tested by applying damage to the character via debug input and verifying HP decreases, and that the character dies when HP reaches zero.

**Acceptance Scenarios**:

1. **Given** a character with full HP, **When** the character takes damage, **Then** HP decreases by the damage amount
2. **Given** a character with HP above zero, **When** HP is reduced to zero or below, **Then** the character enters death state
3. **Given** a character in death state, **When** death occurs, **Then** appropriate death handling triggers (respawn, game over, etc.)
4. **Given** a character, **When** I check their HP, **Then** I can see current and maximum HP values

---

### Edge Cases

- What happens when the player moves against a wall or collision boundary? (Character should stop at the boundary without jittering)
- How does the system handle rapid direction changes? (State machine should transition smoothly without animation glitches)
- What happens when shooting at exactly the character's position? (Projectile should have a minimum spawn offset to prevent self-collision)
- How does the system handle negative HP values? (HP should be clamped at zero)
- What happens when mouse cursor is directly on the character? (Aiming should default to last valid direction or forward)
- How does the system handle diagonal movement speed? (Movement vector should be normalized to prevent faster diagonal movement)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a base player scene with sprite rendering and collision detection
- **FR-002**: System MUST support 8-directional movement using WASD keys at 200 pixels/second default speed (configurable via @export variable)
- **FR-003**: System MUST normalize diagonal movement speed to match cardinal direction speed
- **FR-004**: System MUST implement a movement state machine with at minimum idle and moving states
- **FR-005**: System MUST rotate the player character to face the mouse cursor position continuously
- **FR-006**: System MUST spawn projectiles when the player left-clicks
- **FR-007**: Projectiles MUST travel in the direction the player is aiming at 400 pixels/second default speed (configurable via @export)
- **FR-008**: Projectiles MUST be destroyed after traveling 600px maximum range (configurable via @export) or hitting an obstacle
- **FR-009**: System MUST implement animation states for idle, walking, attacking, and taking damage using AnimatedSprite2D with sprite sheets
- **FR-010**: Animation transitions MUST be handled via AnimatedSprite2D.play() calls triggered by state changes
- **FR-011**: System MUST track player HP as a numeric value with defined maximum
- **FR-012**: System MUST decrease HP when damage is applied to the player
- **FR-013**: System MUST trigger death handling when HP reaches zero
- **FR-014**: System MUST prevent HP from going below zero (clamp at minimum)
- **FR-015**: System MUST handle collision detection between player and environment using defined collision layers: Player (1), Environment (2), Player Projectiles (3), Enemy (4)
- **FR-016**: Player MUST be on layer 1 and mask layers 2 (environment) and 4 (enemies)
- **FR-017**: Player Projectiles MUST be on layer 3 and mask layers 2 (environment) and 4 (enemies), ignoring layer 1 (player)

### Non-Functional Requirements

- **NFR-001**: Player character system MUST complete all per-frame updates within 2ms to maintain 60+ fps with headroom for networking and other systems. This budget applies per-player and should be verified during multiplayer stress testing.
- **NFR-002**: Projectiles MUST use object pooling with pre-allocated instances to prevent garbage collection stutters and reduce allocation overhead during gameplay.
- **NFR-003**: System MUST provide a toggleable debug overlay displaying HP, position, movement state, and velocity for development and testing purposes.
- **NFR-004**: Projectile pool MUST be sized at 16 projectiles per player maximum. When pool is exhausted, oldest projectile is recycled.
- **NFR-005**: System MUST auto-correct invalid player state (e.g., HP > max, NaN position) to valid values and log a warning for debugging. No crashes or asserts in release builds.

### Key Entities

- **Player**: The controllable character entity with position, rotation, HP, movement state, and configurable movement speed (@export). Contains references to sprite, collision shape, and animation controller.
- **Projectile**: A moving entity spawned by the player when shooting. Has position, velocity/direction, configurable speed (@export, default 400 px/s), damage value, and configurable maximum range (@export, default 600px). Managed via object pool to prevent allocation overhead.
- **HP Component**: Health tracking component with current HP, maximum HP, and methods for taking damage and checking death condition.
- **Movement State**: State machine state representing current movement status (idle, walking) with associated animation.
- **Animation State**: Current animation being played (idle, walk, attack, hit) managed via AnimatedSprite2D and SpriteFrames resource.
- **Collision Layers**: Layer 1 (Player), Layer 2 (Environment), Layer 3 (Player Projectiles), Layer 4 (Enemy) - configured in project settings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Player character responds to movement input within 1 frame (immediate feedback)
- **SC-002**: Movement in all 8 directions feels consistent (diagonal speed equals cardinal speed)
- **SC-003**: Character rotation tracks mouse cursor smoothly without visible stuttering or lag
- **SC-004**: Projectiles spawn and travel visibly toward the aimed direction
- **SC-005**: Animation transitions occur without visible pops, glitches, or delays greater than 100ms
- **SC-006**: HP changes are accurately reflected when damage is applied
- **SC-007**: Death state triggers reliably when HP reaches zero (100% of the time)
- **SC-008**: Player can complete a full gameplay loop: move, aim, shoot, and take damage without crashes or freezes

## Assumptions

- The game uses a true top-down perspective (camera directly above) with simple rotation math via look_at()
- Standard desktop input is available (keyboard + mouse)
- The game runs at a stable frame rate where frame-based input detection is reliable
- Projectiles use simple linear motion without complex physics simulation
- A single player character exists at a time (no multiplayer considerations in this spec)
- Death handling will be defined in a separate feature (this spec only triggers the death state)
- Fire rate for shooting defaults to a reasonable value (approximately 3 shots per second) to prevent spam
- Starting HP defaults to 100 with damage values relative to this scale
