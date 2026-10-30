# Grimdark UI review captures

[Latest aged-bronze revision](BRONZE.md) compares the current palette and frameless death screen against `db05991`, with 34 matched pairs. [Historical hybrid material revision](HYBRID.md) preserves the earlier silver/blood-panel comparison. The original-baseline gallery below also points to the latest captures.

31 before/after pairs captured from real Godot 4.7.2 scenes. Before uses commit `bb583d4`; after uses the implementation committed alongside this gallery. Both use the same offline fixture, names, resource values and window sizes. No account credentials or live server data are used.

The first four pairs are unscaled crops of the 1280×720 captures. All other images are complete viewport captures; click an image for its original resolution. The neutral terrain and fixed monster/NPC/landmark markers are a fixture for checking minimap clipping and marker styles, not replacement world art. HUD, world-map, death and connection screens share that fixture.

## Reproduce

```sh
godot --windowed --path client res://scenes/test/ui_review_capture.tscn -- --capture=/absolute/output/path
```

For the before version, extract `git archive bb583d4 client` into a temporary directory, copy the current capture script and its scene into the extracted client, provide the built `client/bin` GDExtension, and run an editor import before capturing. The fixture is compatible with both versions. For a baseline older than the launch override, also copy the current `client/autoload/game_manager.gd` into the temporary extraction so it honors `--windowed` before loading settings; this changes no captured UI. It redirects region reads to localhost and does not save preferences. Use `--auth-only` to capture only login and character creation, including narrow layouts and valid-name/Hardcore states. Captures require a graphical display. Native window and rendered texture dimensions are checked before saving.

Crops from `hud-1280.png`: bars `(120,610)-(1160,720)`; minimap/kill feed `(1040,0)-(1280,300)`; leaderboard `(0,0)-(280,200)`. The partial bars use the same crop from `hud-partial-1280.png`.

The shared theme also reaches login, character creation, dialogs, loading and connection/death screens; these are included even where layout was unchanged. Inventory/equipment/tooltip scenes are empty, unused scaffolds, not playable menus. Narrow HUD captures document the existing world stretch policy; this change does not introduce touch controls.

## Gallery

### Health, mana, energy and action slots — full

| Before | After |
| --- | --- |
| ![Before: Health, mana, energy and action slots — full](before/bars-full.png) | ![After: Health, mana, energy and action slots — full](after/bars-full.png) |

### Resource bars and action cooldowns — partial / empty

| Before | After |
| --- | --- |
| ![Before: Resource bars and action cooldowns — partial / empty](before/bars-partial.png) | ![After: Resource bars and action cooldowns — partial / empty](after/bars-partial.png) |

### Minimap and kill feed

| Before | After |
| --- | --- |
| ![Before: Minimap and kill feed](before/minimap.png) | ![After: Minimap and kill feed](after/minimap.png) |

### Leaderboard

| Before | After |
| --- | --- |
| ![Before: Leaderboard](before/leaderboard.png) | ![After: Leaderboard](after/leaderboard.png) |

### Complete HUD — 1280×720

| Before | After |
| --- | --- |
| ![Before: Complete HUD — 1280×720](before/hud-1280.png) | ![After: Complete HUD — 1280×720](after/hud-1280.png) |

### Complete HUD — partial resources

| Before | After |
| --- | --- |
| ![Before: Complete HUD — partial resources](before/hud-partial-1280.png) | ![After: Complete HUD — partial resources](after/hud-partial-1280.png) |

### Pause menu

| Before | After |
| --- | --- |
| ![Before: Pause menu](before/pause-1280.png) | ![After: Pause menu](after/pause-1280.png) |

### In-game settings

| Before | After |
| --- | --- |
| ![Before: In-game settings](before/settings-ingame-1280.png) | ![After: In-game settings](after/settings-ingame-1280.png) |

### In-game key bindings

| Before | After |
| --- | --- |
| ![Before: In-game key bindings](before/keybinds-1280.png) | ![After: In-game key bindings](after/keybinds-1280.png) |

### Main menu — long region label

| Before | After |
| --- | --- |
| ![Before: Main menu — long region label](before/main-1280.png) | ![After: Main menu — long region label](after/main-1280.png) |

### Main menu — 390×844

| Before | After |
| --- | --- |
| ![Before: Main menu — 390×844](before/main-390.png) | ![After: Main menu — 390×844](after/main-390.png) |

### Settings — audio

| Before | After |
| --- | --- |
| ![Before: Settings — audio](before/settings-1280.png) | ![After: Settings — audio](after/settings-1280.png) |

### Settings — video

| Before | After |
| --- | --- |
| ![Before: Settings — video](before/settings-video-1280.png) | ![After: Settings — video](after/settings-video-1280.png) |

### Settings — controls

| Before | After |
| --- | --- |
| ![Before: Settings — controls](before/settings-controls-1280.png) | ![After: Settings — controls](after/settings-controls-1280.png) |

### Settings — 390×844

| Before | After |
| --- | --- |
| ![Before: Settings — 390×844](before/settings-controls-390.png) | ![After: Settings — 390×844](after/settings-controls-390.png) |

### Login

| Before | After |
| --- | --- |
| ![Before: Login](before/login_screen-1280.png) | ![After: Login](after/login_screen-1280.png) |

### Character creation

| Before | After |
| --- | --- |
| ![Before: Character creation](before/character_creation-1280.png) | ![After: Character creation](after/character_creation-1280.png) |

### Softcore death

| Before | After |
| --- | --- |
| ![Before: Softcore death](before/death-softcore-1280.png) | ![After: Softcore death](after/death-softcore-1280.png) |

### Hardcore death

| Before | After |
| --- | --- |
| ![Before: Hardcore death](before/death-hardcore-1280.png) | ![After: Hardcore death](after/death-hardcore-1280.png) |

### Confirmation dialog

| Before | After |
| --- | --- |
| ![Before: Confirmation dialog](before/confirm_dialog-1280.png) | ![After: Confirmation dialog](after/confirm_dialog-1280.png) |

### Error / retry dialog

| Before | After |
| --- | --- |
| ![Before: Error / retry dialog](before/error_dialog-1280.png) | ![After: Error / retry dialog](after/error_dialog-1280.png) |

### Connection lost

| Before | After |
| --- | --- |
| ![Before: Connection lost](before/connection-lost-1280.png) | ![After: Connection lost](after/connection-lost-1280.png) |

### Loading

| Before | After |
| --- | --- |
| ![Before: Loading](before/loading_screen-1280.png) | ![After: Loading](after/loading_screen-1280.png) |

### World map

| Before | After |
| --- | --- |
| ![Before: World map](before/world-map-1280.png) | ![After: World map](after/world-map-1280.png) |

### HUD — 1920×1080

| Before | After |
| --- | --- |
| ![Before: HUD — 1920×1080](before/hud-1920.png) | ![After: HUD — 1920×1080](after/hud-1920.png) |

### HUD — 390×844

| Before | After |
| --- | --- |
| ![Before: HUD — 390×844](before/hud-390.png) | ![After: HUD — 390×844](after/hud-390.png) |

### Login — 390×844

| Before | After |
| --- | --- |
| ![Before: Login — 390×844](before/login_screen-390.png) | ![After: Login — 390×844](after/login_screen-390.png) |

### Character creation — 390×844

| Before | After |
| --- | --- |
| ![Before: Character creation — 390×844](before/character_creation-390.png) | ![After: Character creation — 390×844](after/character_creation-390.png) |

### Character creation — valid name and Hardcore selection

| Before | After |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore selection](before/character-ready-1280.png) | ![After: Character creation — valid name and Hardcore selection](after/character-ready-1280.png) |

### Character creation — valid name and Hardcore, 390×844

| Before | After |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore, 390×844](before/character-ready-390.png) | ![After: Character creation — valid name and Hardcore, 390×844](after/character-ready-390.png) |

### HUD — empty resource bars

| Before | After |
| --- | --- |
| ![Before: empty resources](before/hud-empty-1280.png) | ![After: empty resources](after/hud-empty-1280.png) |

## HUD reference refinement

These four comparisons use the previous PR revision `9c6cba4` as the before image. They isolate the requested removal of the leaderboard frame, illustrated action slots and key badges, mirrored resource rails, and matching minimap/kill notification styling. Both revisions use the same windowed capture fixture. Unassigned action slots stay empty.

### Resource rails and action slots

| Previous PR version | Updated |
| --- | --- |
| ![Previous: Resource rails and action slots](revision-before/bars-full.png) | ![Updated: Resource rails and action slots](after/bars-full.png) |

### Partial resources and cooldowns

| Previous PR version | Updated |
| --- | --- |
| ![Previous: Partial resources and cooldowns](revision-before/bars-partial.png) | ![Updated: Partial resources and cooldowns](after/bars-partial.png) |

### Minimap and kill notifications

| Previous PR version | Updated |
| --- | --- |
| ![Previous: Minimap and kill notifications](revision-before/minimap.png) | ![Updated: Minimap and kill notifications](after/minimap.png) |

### Leaderboard without outer frame

| Previous PR version | Updated |
| --- | --- |
| ![Previous: Leaderboard without outer frame](revision-before/leaderboard.png) | ![Updated: Leaderboard without outer frame](after/leaderboard.png) |

## Resource-bar spacing and alignment

Before is PR revision `9933dba`. Both resource bars move up 4 logical pixels to share the action-slot centerline. HP/action, action/mana and energy/action gaps now use the same 8-pixel layout spacing as the slots themselves. Geometry checks cover 1280×720, 1920×1080 and 390×844 layouts.

| Before | After |
| --- | --- |
| ![Previous bar spacing](alignment-before/bars-full.png) | ![Aligned bars and equal gaps](after/bars-full.png) |
| ![Previous partial bars](alignment-before/bars-partial.png) | ![Aligned partial bars](after/bars-partial.png) |
