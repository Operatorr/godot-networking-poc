# Quickstart: Player Character System

**Feature Branch**: `002-player-character`
**Date**: 2025-12-09

## Prerequisites

- Godot 4.5 installed
- Project cloned and opened in Godot editor
- On branch `002-player-character`

## File Locations

After implementation, the following files will exist:

```
client/
├── scenes/shared/
│   ├── player/
│   │   ├── player.tscn           # Main player scene
│   │   └── debug_overlay.tscn    # Debug HUD (child of player)
│   └── projectile/
│       └── projectile.tscn       # Projectile scene (pooled)
├── scripts/shared/
│   ├── player/
│   │   ├── player.gd             # Main player controller
│   │   ├── hp_component.gd       # Health tracking
│   │   └── debug_overlay.gd      # Debug display
│   └── projectile/
│       ├── projectile.gd         # Individual projectile
│       └── projectile_pool.gd    # Object pool manager
└── assets/sprites/player/        # Placeholder sprites
```

## Testing the Player Character

### Step 1: Create a Test Scene

1. Create a new scene: `client/scenes/test/player_test.tscn`
2. Add a Node2D as root, rename to "PlayerTest"
3. Instance the player scene as a child:
   - Right-click → Instance Child Scene
   - Select `res://scenes/shared/player/player.tscn`
4. Position player at center: (960, 540)

### Step 2: Run the Test Scene

```bash
# From terminal (optional)
cd client
godot --path . scenes/test/player_test.tscn
```

Or press F6 in Godot editor with the test scene open.

### Step 3: Verify Controls

| Input | Expected Behavior |
|-------|-------------------|
| W | Move up |
| A | Move left |
| S | Move down |
| D | Move right |
| W+D | Move diagonally up-right (normalized speed) |
| Mouse move | Character rotates to face cursor |
| Left click | Fires projectile toward cursor |
| Hold left click | Fires at rate limit (0.3s interval) |

### Step 4: Test Debug Overlay

1. Add input action `toggle_debug`:
   - Project → Project Settings → Input Map
   - Add action "toggle_debug"
   - Assign key (e.g., F3)

2. Press F3 (or assigned key) to toggle debug overlay
3. Verify overlay shows:
   - Current HP (100/100)
   - Position (updating as you move)
   - State (IDLE/WALKING)
   - Velocity (updating as you move)

### Step 5: Test HP System

Add a test script to simulate damage:

```gdscript
# Attach to PlayerTest root node
extends Node2D

func _input(event: InputEvent) -> void:
    if event.is_action_pressed("ui_accept"):  # Space bar
        var player := $Player
        player.take_damage(25)
        print("Player HP: ", player.hp_component.current_hp)
```

Press Space 4 times → Player should die (HP: 100 → 75 → 50 → 25 → 0)

## Exported Variables

Customize in Inspector panel when selecting Player node:

| Variable | Default | Description |
|----------|---------|-------------|
| Speed | 200.0 | Movement speed (px/s) |
| Projectile Range | 600.0 | Max projectile distance |
| Fire Rate | 0.3 | Seconds between shots |

HPComponent (child node):

| Variable | Default | Description |
|----------|---------|-------------|
| Max HP | 100 | Starting/maximum health |

## Placeholder Assets

Until final sprites are ready, use these placeholders:

### Player Sprite (32x32 colored square)
- Create in Godot: New Texture2D → PlaceholderTexture2D
- Or use a simple colored rectangle

### Animation Setup
1. Select AnimatedSprite2D
2. Create new SpriteFrames resource
3. Add animations:
   - `idle`: 1 frame (or 2-4 for breathing)
   - `walk`: 4 frames
   - `attack`: 3 frames (one-shot)
   - `hit`: 2 frames (one-shot)

## Common Issues

### Player not moving
- Check Input Map has `move_up`, `move_down`, `move_left`, `move_right`
- Verify player script is attached to CharacterBody2D

### Projectiles not appearing
- Check ProjectilePool is child of Player
- Verify projectile.tscn exists at correct path
- Check collision layers (projectiles should be on layer 3)

### Diagonal movement too fast
- Ensure using `Input.get_vector()` (auto-normalizes)
- NOT manually combining `is_action_pressed` checks

### Debug overlay not showing
- Add `toggle_debug` input action
- Check DebugOverlay CanvasLayer is child of Player
- Verify `visible` property is being toggled

## Integration with Existing Systems

### Using GameConstants

The player respects existing constants from `game_constants.gd`:

```gdscript
# In player.gd
var effective_speed := speed  # Uses @export, can be overridden

# For consistency with server, prefer GameConstants:
# var effective_speed := GameConstants.PLAYER_SPEED
```

### Connecting to NetworkManager

```gdscript
# In game scene that manages player
func _ready() -> void:
    player.state_changed.connect(NetworkManager.send_player_state)
    NetworkManager.state_update_received.connect(player.apply_state)
```

### Connecting to Game Events

```gdscript
# Handle player death
player.hp_component.died.connect(_on_player_died)

func _on_player_died() -> void:
    # Trigger respawn, game over, etc.
    pass
```
