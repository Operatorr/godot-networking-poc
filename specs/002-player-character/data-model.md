# Data Model: Player Character System

**Feature Branch**: `002-player-character`
**Date**: 2025-12-09

## Entity Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Player                               │
│  (CharacterBody2D)                                          │
├─────────────────────────────────────────────────────────────┤
│  Properties:                                                 │
│  - speed: float = 200.0                                     │
│  - projectile_range: float = 600.0                          │
│  - fire_rate: float = 0.3                                   │
│                                                              │
│  State:                                                      │
│  - movement_state: MovementState                            │
│  - action_state: ActionState                                │
│  - last_aim_direction: Vector2                              │
├─────────────────────────────────────────────────────────────┤
│  Children:                                                   │
│  ├── AnimatedSprite2D                                       │
│  ├── CollisionShape2D (CircleShape2D, r=16)                │
│  ├── HPComponent (Node)                                     │
│  ├── ProjectilePool (Node)                                  │
│  ├── ShootCooldownTimer (Timer)                            │
│  └── DebugOverlay (CanvasLayer, optional)                  │
└─────────────────────────────────────────────────────────────┘
         │
         │ owns
         ▼
┌─────────────────────────────────────────────────────────────┐
│                      HPComponent                             │
│  (Node)                                                      │
├─────────────────────────────────────────────────────────────┤
│  Properties:                                                 │
│  - max_hp: int = 100                                        │
│  - current_hp: int = 100                                    │
│  - is_dead: bool = false                                    │
│                                                              │
│  Signals:                                                    │
│  - hp_changed(new_hp: int, max_hp: int)                    │
│  - died()                                                    │
├─────────────────────────────────────────────────────────────┤
│  Methods:                                                    │
│  - take_damage(amount: int) -> void                         │
│  - heal(amount: int) -> void                                │
│  - reset() -> void                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     ProjectilePool                           │
│  (Node)                                                      │
├─────────────────────────────────────────────────────────────┤
│  Constants:                                                  │
│  - POOL_SIZE: int = 16                                      │
│                                                              │
│  State:                                                      │
│  - pool: Array[Projectile]                                  │
│  - active_projectiles: Array[Projectile]                   │
├─────────────────────────────────────────────────────────────┤
│  Methods:                                                    │
│  - spawn(position: Vector2, direction: Vector2) -> Projectile│
│  - return_projectile(p: Projectile) -> void                 │
└─────────────────────────────────────────────────────────────┘
         │
         │ manages
         ▼
┌─────────────────────────────────────────────────────────────┐
│                       Projectile                             │
│  (Area2D)                                                    │
├─────────────────────────────────────────────────────────────┤
│  Properties:                                                 │
│  - speed: float = 400.0                                     │
│  - max_distance: float = 600.0                              │
│  - damage: int = 25                                         │
│                                                              │
│  State:                                                      │
│  - direction: Vector2                                       │
│  - distance_traveled: float = 0.0                           │
│  - owner_pool: ProjectilePool                               │
├─────────────────────────────────────────────────────────────┤
│  Children:                                                   │
│  ├── Sprite2D (or AnimatedSprite2D)                        │
│  └── CollisionShape2D (CircleShape2D, r=8)                 │
└─────────────────────────────────────────────────────────────┘
```

## Entity Definitions

### Player

The main controllable character entity.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `speed` | `float` | `200.0` | Movement speed in pixels/second. @export for testing. |
| `projectile_range` | `float` | `600.0` | Max distance projectiles travel. @export for testing. |
| `fire_rate` | `float` | `0.3` | Seconds between shots. @export for testing. |
| `movement_state` | `MovementState` | `IDLE` | Current movement state (IDLE, WALKING). |
| `action_state` | `ActionState` | `NONE` | Current action state (NONE, ATTACKING, HIT, DEAD). |
| `last_aim_direction` | `Vector2` | `Vector2.RIGHT` | Fallback when mouse at player position. |

**Collision Configuration**:
- Layer: 1 (Players)
- Mask: 2 (Monsters), 4 (Environment)

**Signals**:
- `shot_fired(position: Vector2, direction: Vector2)` - Emitted when player shoots

### HPComponent

Health tracking component attached to Player.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_hp` | `int` | `100` | Maximum health points. @export for configuration. |
| `current_hp` | `int` | `100` | Current health points. |
| `is_dead` | `bool` | `false` | Prevents further damage after death. |

**Signals**:
- `hp_changed(new_hp: int, max_hp: int)` - Emitted on any HP change
- `died()` - Emitted when HP reaches zero

**Validation Rules**:
- `current_hp` clamped to `[0, max_hp]`
- `take_damage()` ignored if `is_dead == true`
- `heal()` does not revive (ignored if `is_dead == true`)
- Invalid state (HP > max, HP < 0) auto-corrects and logs warning (NFR-005)

### Projectile

Individual projectile entity managed by pool.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `speed` | `float` | `400.0` | Movement speed in pixels/second. |
| `max_distance` | `float` | `600.0` | Maximum travel distance before deactivation. |
| `damage` | `int` | `25` | Damage dealt on hit. |
| `direction` | `Vector2` | `Vector2.ZERO` | Normalized travel direction. |
| `distance_traveled` | `float` | `0.0` | Tracks distance for range limit. |
| `owner_pool` | `ProjectilePool` | `null` | Reference to managing pool for return. |

**Collision Configuration**:
- Layer: 3 (Projectiles)
- Mask: 2 (Monsters), 4 (Environment)

**Signals**:
- `hit(body: Node2D)` - Emitted on collision before deactivation

**Lifecycle**:
1. `activate(pos, dir, max_dist)` - Called by pool to initialize
2. `_physics_process()` - Moves projectile, checks distance
3. `deactivate()` - Called when max distance reached or hit
4. Pool recycles for next use

### ProjectilePool

Object pool manager for projectiles.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `POOL_SIZE` | `int` | `16` | Maximum pooled projectiles (constant). |
| `pool` | `Array[Projectile]` | `[]` | All projectile instances. |
| `active_projectiles` | `Array[Projectile]` | `[]` | Currently active projectiles (FIFO order). |

**Methods**:

```gdscript
## Request a projectile from the pool
## Returns: Active projectile at specified position/direction
func spawn(position: Vector2, direction: Vector2, max_distance: float) -> Projectile

## Return a projectile to the pool (called by projectile on deactivate)
func return_projectile(projectile: Projectile) -> void
```

**Pool Exhaustion Behavior**:
- When all 16 projectiles active, recycles oldest (FIFO)
- Oldest projectile deactivated and reused for new shot
- No new allocations during gameplay

## Enumerations

### MovementState

```gdscript
enum MovementState {
    IDLE,    ## No movement input, playing idle animation
    WALKING  ## Movement input active, playing walk animation
}
```

### ActionState

```gdscript
enum ActionState {
    NONE,      ## No action in progress
    ATTACKING, ## Attack animation playing (does not block movement)
    HIT,       ## Hit stun animation playing (blocks movement briefly)
    DEAD       ## Death state (blocks all processing)
}
```

## State Transitions

### Movement State Machine

```
            ┌──────────────────────┐
            │                      │
            ▼                      │
       ┌────────┐   input!=0   ┌───────┐
       │  IDLE  │ ───────────► │WALKING│
       └────────┘              └───────┘
            ▲                      │
            │      input==0        │
            └──────────────────────┘
```

**Transition Conditions**:
- IDLE → WALKING: `Input.get_vector() != Vector2.ZERO`
- WALKING → IDLE: `Input.get_vector() == Vector2.ZERO`

### Action State Machine

```
                    ┌─────────────────────┐
                    │                     │
                    ▼                     │
              ┌──────────┐               │
     ┌───────►│   NONE   │◄──────┐       │
     │        └──────────┘       │       │
     │             │             │       │
     │   shoot     │   damage    │       │
     │             ▼             │       │
     │      ┌───────────┐        │       │
     │      │ ATTACKING │        │       │
     │      └───────────┘        │       │
     │             │             │       │
     │   anim_done │             │       │
     │             ▼             │       │
     └─────────────┘             │       │
                                 │       │
            damage               │       │
               │                 │       │
               ▼                 │       │
          ┌─────────┐            │       │
          │   HIT   │────────────┘       │
          └─────────┘  anim_done         │
               │                         │
               │ hp <= 0                 │
               ▼                         │
          ┌─────────┐                    │
          │  DEAD   │ (terminal state)   │
          └─────────┘                    │
```

**Transition Conditions**:
- NONE → ATTACKING: `shoot input && cooldown elapsed`
- ATTACKING → NONE: `attack animation finished`
- ANY → HIT: `take_damage() called && hp > 0`
- HIT → NONE: `hit animation finished`
- HIT → DEAD: `take_damage() caused hp <= 0`

## Scene Hierarchy

### player.tscn

```
Player (CharacterBody2D)
├── AnimatedSprite2D
│   └── [SpriteFrames resource with: idle, walk, attack, hit]
├── CollisionShape2D
│   └── CircleShape2D (radius: 16)
├── HPComponent (Node)
├── ProjectilePool (Node)
│   └── [16x Projectile instances as children]
├── ShootCooldownTimer (Timer)
│   └── wait_time: 0.3, one_shot: true
└── DebugOverlay (CanvasLayer)
    └── Label
```

### projectile.tscn

```
Projectile (Area2D)
├── Sprite2D
│   └── [Projectile texture]
└── CollisionShape2D
    └── CircleShape2D (radius: 8)
```

## Integration Points

### Signals to Connect

| Source | Signal | Receiver | Handler |
|--------|--------|----------|---------|
| HPComponent | `died` | Player | `_on_hp_component_died()` |
| HPComponent | `hp_changed` | DebugOverlay | `_on_hp_changed()` |
| AnimatedSprite2D | `animation_finished` | Player | `_on_animation_finished()` |
| ShootCooldownTimer | `timeout` | Player | (enables next shot) |
| Projectile | `hit` | Player/Game | `_on_projectile_hit()` |

### External Dependencies

| Dependency | File | Usage |
|------------|------|-------|
| GameConstants | `scripts/shared/game_constants.gd` | Speed values, damage constants |
| Input Actions | `project.godot` | move_up/down/left/right, shoot |
| Collision Layers | `project.godot` | Layer 1, 3 / Mask 2, 4 |
