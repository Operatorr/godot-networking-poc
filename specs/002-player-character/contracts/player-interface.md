# Player Interface Contract

**Feature Branch**: `002-player-character`
**Date**: 2025-12-09

## Overview

This document defines the public interface of the Player entity for integration with other game systems (networking, UI, game manager).

## Class: Player

**Extends**: `CharacterBody2D`
**Script Path**: `res://scripts/shared/player/player.gd`
**Scene Path**: `res://scenes/shared/player/player.tscn`

### Exported Properties

```gdscript
## Movement speed in pixels per second
@export var speed: float = 200.0

## Maximum distance projectiles travel
@export var projectile_range: float = 600.0

## Seconds between shots (fire rate)
@export var fire_rate: float = 0.3
```

### Public Properties (Read-Only)

```gdscript
## Current movement state
var movement_state: MovementState { get }

## Current action state
var action_state: ActionState { get }

## Reference to HP component for external queries
var hp_component: HPComponent { get }

## Whether the player is currently dead
var is_dead: bool { get }
```

### Signals

```gdscript
## Emitted when the player fires a projectile
## @param position: World position where projectile spawns
## @param direction: Normalized direction vector
signal shot_fired(position: Vector2, direction: Vector2)

## Emitted when player state changes (for networking)
## @param state_data: Dictionary containing serializable state
signal state_changed(state_data: Dictionary)
```

### Public Methods

```gdscript
## Apply damage to the player
## @param amount: Damage points to subtract from HP
## @return: Remaining HP after damage
func take_damage(amount: int) -> int

## Heal the player (does nothing if dead)
## @param amount: HP points to restore
## @return: New HP value after healing
func heal(amount: int) -> int

## Reset player to initial state (full HP, idle state)
## Used for respawn systems
func reset() -> void

## Get current state as serializable dictionary
## Used for networking state sync
## @return: Dictionary with position, rotation, hp, states
func get_state() -> Dictionary

## Apply state from dictionary (server reconciliation)
## @param state: Dictionary from get_state() format
func apply_state(state: Dictionary) -> void

## Enable/disable player input processing
## Used when game is paused or in menus
## @param enabled: Whether to process input
func set_input_enabled(enabled: bool) -> void
```

### State Dictionary Format

```gdscript
{
    "position": Vector2,      # Global position
    "rotation": float,        # Rotation in radians
    "velocity": Vector2,      # Current velocity
    "hp": int,                # Current HP
    "max_hp": int,            # Maximum HP
    "movement_state": int,    # MovementState enum value
    "action_state": int,      # ActionState enum value
    "is_dead": bool           # Death flag
}
```

---

## Class: HPComponent

**Extends**: `Node`
**Script Path**: `res://scripts/shared/player/hp_component.gd`

### Exported Properties

```gdscript
## Maximum health points
@export var max_hp: int = 100
```

### Public Properties

```gdscript
## Current health points (read-only externally)
var current_hp: int { get }

## Whether entity is dead
var is_dead: bool { get }
```

### Signals

```gdscript
## Emitted when HP changes
## @param new_hp: Current HP after change
## @param max_hp: Maximum HP for percentage calculations
signal hp_changed(new_hp: int, max_hp: int)

## Emitted when HP reaches zero
signal died()
```

### Public Methods

```gdscript
## Apply damage, respecting is_dead flag
## @param amount: Damage to apply (positive integer)
func take_damage(amount: int) -> void

## Restore HP, clamped to max_hp
## @param amount: HP to restore (positive integer)
func heal(amount: int) -> void

## Reset to full HP and clear is_dead flag
func reset() -> void

## Set HP directly (for server reconciliation)
## Auto-corrects invalid values per NFR-005
## @param hp: New HP value
func set_hp(hp: int) -> void
```

---

## Class: ProjectilePool

**Extends**: `Node`
**Script Path**: `res://scripts/shared/projectile/projectile_pool.gd`

### Constants

```gdscript
## Maximum pooled projectiles per player
const POOL_SIZE: int = 16
```

### Public Methods

```gdscript
## Spawn a projectile from the pool
## Recycles oldest if pool exhausted
## @param position: Spawn world position
## @param direction: Normalized direction vector
## @param max_distance: Maximum travel distance
## @return: The activated projectile
func spawn(position: Vector2, direction: Vector2, max_distance: float) -> Projectile

## Return a projectile to the pool
## Called automatically by Projectile.deactivate()
## @param projectile: The projectile to return
func return_projectile(projectile: Projectile) -> void

## Get count of currently active projectiles
## @return: Number of active projectiles
func get_active_count() -> int

## Deactivate all projectiles (e.g., on player death)
func deactivate_all() -> void
```

---

## Class: Projectile

**Extends**: `Area2D`
**Script Path**: `res://scripts/shared/projectile/projectile.gd`
**Scene Path**: `res://scenes/shared/projectile/projectile.tscn`

### Public Properties

```gdscript
## Damage dealt on hit (configured by spawner)
var damage: int = 25

## Movement speed in pixels/second
var speed: float = 400.0
```

### Signals

```gdscript
## Emitted when projectile hits something
## @param body: The colliding body
signal hit(body: Node2D)
```

### Public Methods

```gdscript
## Activate projectile (called by pool)
## @param pos: Starting position
## @param dir: Normalized direction
## @param max_dist: Maximum travel distance
## @param pool: Owning pool reference
func activate(pos: Vector2, dir: Vector2, max_dist: float, pool: ProjectilePool) -> void

## Deactivate and return to pool
func deactivate() -> void
```

---

## Collision Layer Reference

| Layer | Name | Used By |
|-------|------|---------|
| 1 | Players | Player CharacterBody2D |
| 2 | Monsters | Enemy entities |
| 3 | Projectiles | Projectile Area2D |
| 4 | Environment | Walls, obstacles |

### Player Collision Setup

```gdscript
# Player (CharacterBody2D)
collision_layer = 1   # Is on Players layer
collision_mask = 2|4  # Collides with Monsters, Environment

# Player Projectile (Area2D)
collision_layer = 3   # Is on Projectiles layer
collision_mask = 2|4  # Collides with Monsters, Environment (not Players)
```

---

## Usage Examples

### Spawning a Player

```gdscript
var player_scene := preload("res://scenes/shared/player/player.tscn")
var player := player_scene.instantiate()
player.global_position = spawn_point
add_child(player)

# Connect to signals
player.shot_fired.connect(_on_player_shot)
player.hp_component.died.connect(_on_player_died)
```

### Applying Server State

```gdscript
func _on_state_update_received(state: Dictionary) -> void:
    player.apply_state(state)
```

### Dealing Damage to Player

```gdscript
func _on_monster_attack_hit(target: Node2D) -> void:
    if target.has_method("take_damage"):
        target.take_damage(MONSTER_DAMAGE)
```
