# Historical aged-bronze UI and frameless death screen

Before: `db05991` (silver hybrid UI). After: `9e0d2f8`. The [current accent revision](ACCENTS.md) preserves the bronze HUD and restores silver menu hardware. All 34 pairs use real Godot captures and the same offline fixture.

The shared hardware now uses muted brown-bronze shadows and restrained warm highlights. Iron PNG surfaces, native typography, crimson actions and resource-fill colors remain. Softcore and Hardcore death content retains its skull artwork, text, button, layout and screen dimming, with no panel frame or textured background.

## Validation

- `ui_theme_regression.tscn`: material apertures, input/focus, dropdown spacing, narrow menus, frameless death content and transformed button clicks.
- `hud_bar_regression.tscn`: complete resource troughs, transparent frames and clamped values.
- `window_mode_regression.tscn` and `settings_save_regression.tscn`.
- Windowed capture fixture: 1280×720, 1920×1080 and 390×844. All PNG dimensions verified.
- Scene/reference checker: 499 files, 0 errors, 0 warnings. Editor import and `git diff --check` clean.

## Reproduce

```sh
python3 scripts/art/build_ui_theme.py
godot --headless --editor --path client --import --quit
godot --windowed --path client res://scenes/test/ui_review_capture.tscn -- --capture=/absolute/output/path
```

## Before / after

### Main menu — long region label

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Main menu — long region label](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-1280.png) | ![After: Main menu — long region label](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-1280.png) |

### Hardcore death

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Hardcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-hardcore-1280.png) | ![After: Hardcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-hardcore-1280.png) |

### Softcore death

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Softcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-softcore-1280.png) | ![After: Softcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-softcore-1280.png) |

### Login

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Login](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/login_screen-1280.png) | ![After: Login](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/login_screen-1280.png) |

### Character creation

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Character creation](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character_creation-1280.png) | ![After: Character creation](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character_creation-1280.png) |

### Pause menu

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Pause menu](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/pause-1280.png) | ![After: Pause menu](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/pause-1280.png) |

### Health, mana, energy and action slots — full

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Health, mana, energy and action slots — full](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/bars-full.png) | ![After: Health, mana, energy and action slots — full](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/bars-full.png) |

### Resource bars and action cooldowns — partial / empty

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Resource bars and action cooldowns — partial / empty](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/bars-partial.png) | ![After: Resource bars and action cooldowns — partial / empty](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/bars-partial.png) |

### Character creation — valid name and Hardcore selection

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore selection](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character-ready-1280.png) | ![After: Character creation — valid name and Hardcore selection](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character-ready-1280.png) |

### Character creation — valid name and Hardcore, 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore, 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character-ready-390.png) | ![After: Character creation — valid name and Hardcore, 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character-ready-390.png) |

### Character creation — 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Character creation — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/character_creation-390.png) | ![After: Character creation — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character_creation-390.png) |

### Confirmation dialog

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Confirmation dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/confirm_dialog-1280.png) | ![After: Confirmation dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/confirm_dialog-1280.png) |

### Connection lost

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Connection lost](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/connection-lost-1280.png) | ![After: Connection lost](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/connection-lost-1280.png) |

### Hardcore death — narrow

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Hardcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-hardcore-390.png) | ![After: Hardcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-hardcore-390.png) |

### Softcore death — narrow

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Softcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/death-softcore-390.png) | ![After: Softcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-softcore-390.png) |

### Error / retry dialog

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Error / retry dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/error_dialog-1280.png) | ![After: Error / retry dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/error_dialog-1280.png) |

### Complete HUD — 1280×720

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Complete HUD — 1280×720](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-1280.png) | ![After: Complete HUD — 1280×720](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-1280.png) |

### HUD — 1920×1080

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: HUD — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-1920.png) | ![After: HUD — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-1920.png) |

### HUD — 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: HUD — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-390.png) | ![After: HUD — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-390.png) |

### empty resources

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: empty resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-empty-1280.png) | ![After: empty resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-empty-1280.png) |

### Complete HUD — partial resources

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Complete HUD — partial resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/hud-partial-1280.png) | ![After: Complete HUD — partial resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-partial-1280.png) |

### In-game key bindings

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: In-game key bindings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/keybinds-1280.png) | ![After: In-game key bindings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/keybinds-1280.png) |

### Leaderboard

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Leaderboard](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/leaderboard.png) | ![After: Leaderboard](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/leaderboard.png) |

### Loading

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Loading](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/loading_screen-1280.png) | ![After: Loading](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/loading_screen-1280.png) |

### Login — 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Login — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/login_screen-390.png) | ![After: Login — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/login_screen-390.png) |

### Main menu — 1920×1080

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Main menu — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-1920.png) | ![After: Main menu — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-1920.png) |

### Main menu — 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Main menu — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/main-390.png) | ![After: Main menu — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-390.png) |

### Minimap and kill feed

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Minimap and kill feed](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/minimap.png) | ![After: Minimap and kill feed](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/minimap.png) |

### Settings — audio

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Settings — audio](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-1280.png) | ![After: Settings — audio](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-1280.png) |

### Settings — controls

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Settings — controls](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-controls-1280.png) | ![After: Settings — controls](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-controls-1280.png) |

### Settings — 390×844

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Settings — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-controls-390.png) | ![After: Settings — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-controls-390.png) |

### In-game settings

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: In-game settings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-ingame-1280.png) | ![After: In-game settings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-ingame-1280.png) |

### Settings — video

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: Settings — video](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/settings-video-1280.png) | ![After: Settings — video](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-video-1280.png) |

### World map

| Previous silver UI | Aged bronze / frameless death |
| --- | --- |
| ![Before: World map](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/db05991ce1e9b41bc9a25a7ab1816996b6e301f8/docs/reviews/grimdark-ui/after/world-map-1280.png) | ![After: World map](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/world-map-1280.png) |
