# Hybrid material UI review (historical)

Before: PR revision `8ba33b5`. After: the hybrid material implementation at `db05991`. The current revision is in [BRONZE.md](BRONZE.md). These are real Godot captures using the same offline fixture, not concept images. The previous revision’s captures are preserved verbatim in `hybrid-before/`.

Everyday UI uses iron PNG material below transparent SVG rims; red actions use tinted iron. Blood wear and skull ornament are confined to the death panel. Native text, focus, input and dropdown layout remain separate. The health/mana/energy fill geometry and 8-pixel HUD gaps are preserved.

## Validation

- Godot editor import after importing the new PNG assets: no errors.
- Scene/reference validation: 499 files, 0 errors, 0 warnings.
- Theme generator: deterministic; `git diff --check` clean.
- `ui_theme_regression.tscn`: inherited button-state apertures, native UI navigation, long dropdowns, narrow layouts, death action focus and scaled clicks.
- `hud_bar_regression.tscn`: resource bounds, transparent troughs and clamped values.
- `window_mode_regression.tscn`: no fullscreen test launch or preference mutation.
- `settings_save_regression.tscn`: settings persistence/navigation.
- Windowed capture fixture: 1280×720, 1920×1080 and 390×844; checked PNG dimensions.

## Reproduce

```sh
python3 scripts/art/build_ui_theme.py
godot --headless --editor --path client --import --quit
godot --headless --path client res://scenes/test/ui_theme_regression.tscn
godot --windowed --path client res://scenes/test/ui_review_capture.tscn -- --capture=/absolute/output/path
```

## Before / after

### Main menu — long region label

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Main menu — long region label](hybrid-before/main-1280.png) | ![After: Main menu — long region label](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-1280.png) |

### Login

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Login](hybrid-before/login_screen-1280.png) | ![After: Login](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/login_screen-1280.png) |

### Character creation

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Character creation](hybrid-before/character_creation-1280.png) | ![After: Character creation](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character_creation-1280.png) |

### Character creation — valid name and Hardcore selection

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore selection](hybrid-before/character-ready-1280.png) | ![After: Character creation — valid name and Hardcore selection](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character-ready-1280.png) |

### Pause menu

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Pause menu](hybrid-before/pause-1280.png) | ![After: Pause menu](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/pause-1280.png) |

### Softcore death

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Softcore death](hybrid-before/death-softcore-1280.png) | ![After: Softcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-softcore-1280.png) |

### Hardcore death

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Hardcore death](hybrid-before/death-hardcore-1280.png) | ![After: Hardcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-hardcore-1280.png) |

### Health, mana, energy and action slots — full

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Health, mana, energy and action slots — full](hybrid-before/bars-full.png) | ![After: Health, mana, energy and action slots — full](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/bars-full.png) |

### Resource bars and action cooldowns — partial / empty

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Resource bars and action cooldowns — partial / empty](hybrid-before/bars-partial.png) | ![After: Resource bars and action cooldowns — partial / empty](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/bars-partial.png) |

### Character creation — valid name and Hardcore, 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore, 390×844](hybrid-before/character-ready-390.png) | ![After: Character creation — valid name and Hardcore, 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character-ready-390.png) |

### Character creation — 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Character creation — 390×844](hybrid-before/character_creation-390.png) | ![After: Character creation — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character_creation-390.png) |

### Confirmation dialog

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Confirmation dialog](hybrid-before/confirm_dialog-1280.png) | ![After: Confirmation dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/confirm_dialog-1280.png) |

### Connection lost

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Connection lost](hybrid-before/connection-lost-1280.png) | ![After: Connection lost](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/connection-lost-1280.png) |

### Error / retry dialog

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Error / retry dialog](hybrid-before/error_dialog-1280.png) | ![After: Error / retry dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/error_dialog-1280.png) |

### Complete HUD — 1280×720

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Complete HUD — 1280×720](hybrid-before/hud-1280.png) | ![After: Complete HUD — 1280×720](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-1280.png) |

### HUD — 1920×1080

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: HUD — 1920×1080](hybrid-before/hud-1920.png) | ![After: HUD — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-1920.png) |

### HUD — 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: HUD — 390×844](hybrid-before/hud-390.png) | ![After: HUD — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-390.png) |

### empty resources

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: empty resources](hybrid-before/hud-empty-1280.png) | ![After: empty resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-empty-1280.png) |

### Complete HUD — partial resources

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Complete HUD — partial resources](hybrid-before/hud-partial-1280.png) | ![After: Complete HUD — partial resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-partial-1280.png) |

### In-game key bindings

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: In-game key bindings](hybrid-before/keybinds-1280.png) | ![After: In-game key bindings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/keybinds-1280.png) |

### Leaderboard

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Leaderboard](hybrid-before/leaderboard.png) | ![After: Leaderboard](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/leaderboard.png) |

### Loading

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Loading](hybrid-before/loading_screen-1280.png) | ![After: Loading](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/loading_screen-1280.png) |

### Login — 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Login — 390×844](hybrid-before/login_screen-390.png) | ![After: Login — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/login_screen-390.png) |

### Main menu — 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Main menu — 390×844](hybrid-before/main-390.png) | ![After: Main menu — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-390.png) |

### Minimap and kill feed

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Minimap and kill feed](hybrid-before/minimap.png) | ![After: Minimap and kill feed](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/minimap.png) |

### Settings — audio

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Settings — audio](hybrid-before/settings-1280.png) | ![After: Settings — audio](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-1280.png) |

### Settings — controls

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Settings — controls](hybrid-before/settings-controls-1280.png) | ![After: Settings — controls](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-controls-1280.png) |

### Settings — 390×844

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Settings — 390×844](hybrid-before/settings-controls-390.png) | ![After: Settings — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-controls-390.png) |

### In-game settings

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: In-game settings](hybrid-before/settings-ingame-1280.png) | ![After: In-game settings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-ingame-1280.png) |

### Settings — video

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: Settings — video](hybrid-before/settings-video-1280.png) | ![After: Settings — video](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-video-1280.png) |

### World map

| Previous PR | Hybrid materials |
| --- | --- |
| ![Before: World map](hybrid-before/world-map-1280.png) | ![After: World map](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/world-map-1280.png) |

## Additional size checks

### Main menu — 1920×1080

![Main menu 1920](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-1920.png)

### Death panels — 390×844

| Softcore | Hardcore |
| --- | --- |
| ![Softcore narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-softcore-390.png) | ![Hardcore narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-hardcore-390.png) |
