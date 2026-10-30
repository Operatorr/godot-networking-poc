# Grimdark UI review captures

26 before/after pairs captured from real Godot 4.7.2 scenes. Before uses commit `bb583d4`; after uses the implementation committed alongside this gallery. Both use the same offline fixture, names, resource values and window sizes. No account credentials or live server data are used.

The first four pairs are unscaled crops of the 1280×720 captures. All other images are complete viewport captures; click an image for its original resolution. The neutral terrain is a fixture for checking minimap clipping, not replacement world art. HUD, world-map, death and connection screens share that fixture.

## Reproduce

```sh
godot --path client res://scenes/test/ui_review_capture.tscn -- --capture=/absolute/output/path
```

For the before version, extract `git archive bb583d4 client` into a temporary directory, copy the current capture script and its scene into the extracted client, provide the built `client/bin` GDExtension, and run an editor import before capturing. The fixture is compatible with both versions. It redirects region reads to localhost and does not save preferences. Captures require a graphical display. Native window and rendered texture dimensions are checked before saving.

Crops from `hud-1280.png`: bars `(280,630)-(1000,720)`; minimap/kill feed `(1090,0)-(1280,220)`; leaderboard `(0,0)-(280,200)`. The partial bars use the same crop from `hud-partial-1280.png`.

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
