# Research: Player Character System

**Feature Branch**: `002-player-character`
**Date**: 2025-12-09

## Resolved Clarifications

### 1. Collision Layer Configuration

**Decision**: Use existing project.godot layer configuration (keep current layers)

**Rationale**: The existing project already has a working collision layer setup with:
- Layer 1: Players
- Layer 2: Monsters
- Layer 3: Projectiles
- Layer 4: Environment

The spec's proposed layers (Player, Environment, Player Projectiles, Enemy) would require modifying existing monster and environment code. Since this is a POC with existing server infrastructure, maintaining consistency is more important.

**Alternatives Rejected**:
- Spec's layer configuration - Would break existing monster and projectile systems
- Adding new layers 5-8 - Unnecessary complexity

**Action**: Update spec to reflect existing layer configuration. Player character will use:
- Collision Layer: 1 (Players)
- Collision Mask: 2 (Monsters), 4 (Environment)

Player Projectiles will use:
- Collision Layer: 3 (Projectiles)
- Collision Mask: 2 (Monsters), 4 (Environment)

### 2. Fire Rate Alignment

**Decision**: Use GameConstants value (0.3s cooldown = 3.33 shots/sec)

**Rationale**: GameConstants already defines `SHOOT_COOLDOWN := 0.3` which is close to the spec's "approximately 3 shots per second". The difference (0.3s vs 0.33s) is negligible and using the existing constant ensures consistency with server validation.

**Alternatives Rejected**:
- Creating a new constant - Duplicates existing configuration
- Changing GameConstants - Would affect server-side validation

### 3. Projectile Range

**Decision**: Use spec value (600px) by making it configurable

**Rationale**: The spec explicitly states 600px as a clarified requirement. GameConstants has 800px for general projectile behavior. The player character should use @export variables as specified, defaulting to 600px.

**Implementation**:
```gdscript
## Maximum projectile travel distance in pixels
@export var projectile_range: float = 600.0
```

GameConstants.PROJECTILE_MAX_DISTANCE (800px) remains for server-side validation and other projectile types.

### 4. Death Handling

**Decision**: Emit signal only; let parent systems handle respawn/game over

**Rationale**: The spec states "Death handling will be defined in a separate feature (this spec only triggers the death state)". The HP component should:
1. Emit a `died` signal when HP reaches zero
2. Set a `is_dead` flag to prevent further damage
3. Not handle respawn or game over logic

**Implementation**:
```gdscript
signal died
signal hp_changed(new_hp: int, max_hp: int)

var is_dead: bool = false

func take_damage(amount: int) -> void:
    if is_dead:
        return
    current_hp = maxi(0, current_hp - amount)
    hp_changed.emit(current_hp, max_hp)
    if current_hp <= 0:
        is_dead = true
        died.emit()
```

## Best Practices Research

### CharacterBody2D Movement (Godot 4.5)

**Pattern**: Use `move_and_slide()` with `velocity` property

From Godot 4.5 documentation:
- `velocity` property stores movement in pixels/second
- `move_and_slide()` automatically applies delta time
- Use `Input.get_vector()` for clean 4-directional input
- Normalize diagonal movement automatically with `get_vector()`

**Recommended Implementation**:
```gdscript
extends CharacterBody2D

@export var speed: float = 200.0

func _physics_process(delta: float) -> void:
    var input_dir := Input.get_vector("move_left", "move_right", "move_up", "move_down")
    velocity = input_dir * speed
    move_and_slide()
```

**Key Points**:
- `motion_mode` should be `MOTION_MODE_FLOATING` for top-down games (no gravity)
- No need to multiply by delta - `move_and_slide()` handles it
- `Input.get_vector()` returns normalized vector (handles diagonal speed)

### AnimatedSprite2D State Management

**Pattern**: Direct `play()` calls triggered by state changes

From Godot 4.5 documentation:
- Use `animation` property to check current animation
- Use `play("animation_name")` to switch animations
- Connect to `animation_finished` signal for one-shot animations
- Use `flip_h` for horizontal direction changes

**Recommended Implementation**:
```gdscript
enum State { IDLE, WALKING, ATTACKING, HIT }
var current_state: State = State.IDLE

func set_state(new_state: State) -> void:
    if current_state == new_state:
        return
    current_state = new_state
    match new_state:
        State.IDLE:
            $AnimatedSprite2D.play("idle")
        State.WALKING:
            $AnimatedSprite2D.play("walk")
        State.ATTACKING:
            $AnimatedSprite2D.play("attack")
        State.HIT:
            $AnimatedSprite2D.play("hit")
```

**Key Points**:
- Attack and hit animations should be one-shots that return to idle/walk
- Use `animation_finished` signal to transition back after one-shots
- `flip_h` based on mouse position relative to player for horizontal facing

### Object Pooling for Projectiles

**Pattern**: Pre-allocate pool, deactivate instead of free, recycle oldest

From Constitution (NFR-002) and performance best practices:
- Pre-allocate 16 projectiles per player
- Use `visible` and `process_mode` to deactivate
- Track active projectiles in array
- Recycle oldest when pool exhausted

**Recommended Implementation**:
```gdscript
class_name ProjectilePool
extends Node

const POOL_SIZE: int = 16

var pool: Array[Projectile] = []
var active_projectiles: Array[Projectile] = []

func _ready() -> void:
    for i in POOL_SIZE:
        var projectile := preload("res://scenes/shared/projectile/projectile.tscn").instantiate()
        projectile.process_mode = Node.PROCESS_MODE_DISABLED
        projectile.visible = false
        add_child(projectile)
        pool.append(projectile)

func get_projectile() -> Projectile:
    # Try to find inactive projectile
    for p in pool:
        if not p.visible:
            return _activate(p)

    # Pool exhausted - recycle oldest
    var oldest := active_projectiles.pop_front()
    oldest.deactivate()
    return _activate(oldest)

func _activate(p: Projectile) -> Projectile:
    p.process_mode = Node.PROCESS_MODE_INHERIT
    p.visible = true
    active_projectiles.append(p)
    return p

func return_projectile(p: Projectile) -> void:
    p.process_mode = Node.PROCESS_MODE_DISABLED
    p.visible = false
    active_projectiles.erase(p)
```

**Key Points**:
- Use `process_mode` to completely disable physics processing
- `visible = false` hides sprite and collision
- Track active order for FIFO recycling
- No `queue_free()` - objects stay in scene tree

### Top-Down Aiming with Mouse

**Pattern**: Use `look_at()` or calculate angle from `get_global_mouse_position()`

**Recommended Implementation**:
```gdscript
func _physics_process(delta: float) -> void:
    var mouse_pos := get_global_mouse_position()
    var direction := (mouse_pos - global_position)

    # Handle edge case: mouse at player position
    if direction.length_squared() < 1.0:
        return  # Keep last valid rotation

    rotation = direction.angle()

    # Or use look_at for simpler code:
    # look_at(mouse_pos)
```

**Key Points**:
- `get_global_mouse_position()` returns world coordinates
- Handle edge case when mouse is directly on player
- `look_at()` is simpler but `angle()` gives more control
- For flip_h based sprites, compare `mouse_pos.x` to `global_position.x`

### State Machine Pattern (Simple Enum-Based)

**Pattern**: Enum states with transition validation

For this feature, a simple enum-based state machine is sufficient (not a full hierarchical FSM):

```gdscript
enum MovementState { IDLE, WALKING }
enum ActionState { NONE, ATTACKING, HIT, DEAD }

var movement_state: MovementState = MovementState.IDLE
var action_state: ActionState = ActionState.NONE

func _physics_process(delta: float) -> void:
    # Action states take priority over movement
    if action_state == ActionState.DEAD:
        return

    if action_state == ActionState.HIT:
        # Wait for hit animation to finish
        return

    # Process movement
    _handle_movement()
    _handle_aiming()

    # Can shoot while moving
    if action_state == ActionState.NONE:
        _handle_shooting()
```

**Key Points**:
- Separate movement state from action state (can move while shooting)
- Dead state blocks all processing
- Hit state is temporary (animation duration)
- Attack doesn't block movement in top-down shooter

### Debug Overlay Implementation

**Pattern**: CanvasLayer with Label nodes, toggled via input action

**Recommended Implementation**:
```gdscript
extends CanvasLayer

@onready var label: Label = $Label

var target_player: Node2D

func _input(event: InputEvent) -> void:
    if event.is_action_pressed("toggle_debug"):
        visible = not visible

func _process(delta: float) -> void:
    if not visible or not target_player:
        return

    label.text = """HP: %d/%d
Position: %s
State: %s
Velocity: %s""" % [
        target_player.hp_component.current_hp,
        target_player.hp_component.max_hp,
        str(target_player.global_position),
        target_player.get_state_name(),
        str(target_player.velocity)
    ]
```

**Key Points**:
- Use CanvasLayer to render above game world
- Toggle with input action (add "toggle_debug" to project.godot)
- Only process when visible
- Format with multiline string for readability

## Performance Considerations

### Frame Budget Compliance (2ms)

To stay within 2ms per frame:

1. **Input Processing**: O(1) - constant time
2. **Movement**: `move_and_slide()` ~0.1-0.2ms
3. **Aiming**: Single `atan2` call ~0.01ms
4. **Animation**: State check + play() ~0.05ms
5. **Projectile Pool**: Array lookup ~0.01ms

**Total estimated**: <0.5ms per player, well within budget

### Memory Efficiency

- Projectile pool: 16 instances x ~1KB = ~16KB per player
- Player scene: ~2-5KB (sprite, collision, script)
- Total per player: <25KB, within 5MB budget per constitution

## Dependencies

### Existing Systems to Integrate With

1. **GameConstants** (`client/scripts/shared/game_constants.gd`)
   - Use existing speed/projectile constants where applicable
   - Add new player-specific constants if needed

2. **Input Actions** (project.godot)
   - Existing: `move_up`, `move_down`, `move_left`, `move_right`, `shoot`
   - Need to add: `toggle_debug` for debug overlay

3. **Collision Layers** (project.godot)
   - Use existing layer 1 (Players), layer 3 (Projectiles)
   - Mask layer 2 (Monsters), layer 4 (Environment)

### Assets Required

- Placeholder sprites (can use colored rectangles initially):
  - Player idle (single frame or 2-4 frame loop)
  - Player walk (4-8 frames)
  - Player attack (3-4 frames)
  - Player hit (2-3 frames)
  - Projectile (single frame or 2-frame animation)
