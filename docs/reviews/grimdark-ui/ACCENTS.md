# Silver menu accents with bronze HUD

Before: `9e0d2f8` (all-bronze hardware). After: the revision committed alongside this gallery. All 34 matched pairs are actual Godot captures.

- Restore the approved `db05991` silver/iron menu frames and bronze sigil/focus accents for main, login, character creation, pause and shared menu controls.
- Preserve aged-bronze HUD hardware and the frameless death content, including every state of the bronze death action.
- Keep all four character-name field edges visible under fractional downscaling.
- Move Practice and Offline Sandbox to the screen's bottom-left corner. Keep the card centered on wide screens and reserve footer space on narrow screens.

## Validation

- Windowed `ui_theme_regression.tscn`: rendered character-name border pixels on all four sides at desktop/narrow widths, detached footer containment/non-overlap and real pointer clicks, inherited material states, dropdown caret/value spacing, character validation, keyboard navigation and frameless death action.
- `hud_bar_regression.tscn`, `window_mode_regression.tscn`, `settings_save_regression.tscn`.
- Scene/reference validator: 503 files, 0 errors, 0 warnings; clean editor import and deterministic regeneration.
- Menu SVGs byte-match `db05991`; HUD SVGs and every death-button frame byte-match `9e0d2f8`. The full 1280×720 HUD capture and the central Softcore/Hardcore death content are pixel-identical to the approved bronze version.
- Windowed captures at 1280×720, 1920×1080 and 390×844. Animated character previews and diagnostic FPS can vary between captures.

## Reproduce

```sh
python3 scripts/art/build_ui_theme.py
godot --headless --editor --path client --import --quit
godot --windowed --path client res://scenes/test/ui_review_capture.tscn -- --capture=/absolute/output/path
```

## Before / after

### Main menu — long region label

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Main menu — long region label](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-1280.png) | ![After: Main menu — long region label](after/main-1280.png) |

### Hardcore death

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Hardcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-hardcore-1280.png) | ![After: Hardcore death](after/death-hardcore-1280.png) |

### Softcore death

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Softcore death](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-softcore-1280.png) | ![After: Softcore death](after/death-softcore-1280.png) |

### Login

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Login](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/login_screen-1280.png) | ![After: Login](after/login_screen-1280.png) |

### Character creation

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Character creation](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character_creation-1280.png) | ![After: Character creation](after/character_creation-1280.png) |

### Pause menu

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Pause menu](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/pause-1280.png) | ![After: Pause menu](after/pause-1280.png) |

### Health, mana, energy and action slots — full

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Health, mana, energy and action slots — full](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/bars-full.png) | ![After: Health, mana, energy and action slots — full](after/bars-full.png) |

### Resource bars and action cooldowns — partial / empty

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Resource bars and action cooldowns — partial / empty](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/bars-partial.png) | ![After: Resource bars and action cooldowns — partial / empty](after/bars-partial.png) |

### Character creation — valid name and Hardcore selection

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore selection](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character-ready-1280.png) | ![After: Character creation — valid name and Hardcore selection](after/character-ready-1280.png) |

### Character creation — valid name and Hardcore, 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Character creation — valid name and Hardcore, 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character-ready-390.png) | ![After: Character creation — valid name and Hardcore, 390×844](after/character-ready-390.png) |

### Character creation — 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Character creation — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/character_creation-390.png) | ![After: Character creation — 390×844](after/character_creation-390.png) |

### Confirmation dialog

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Confirmation dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/confirm_dialog-1280.png) | ![After: Confirmation dialog](after/confirm_dialog-1280.png) |

### Connection lost

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Connection lost](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/connection-lost-1280.png) | ![After: Connection lost](after/connection-lost-1280.png) |

### Hardcore death — narrow

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Hardcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-hardcore-390.png) | ![After: Hardcore death — narrow](after/death-hardcore-390.png) |

### Softcore death — narrow

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Softcore death — narrow](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/death-softcore-390.png) | ![After: Softcore death — narrow](after/death-softcore-390.png) |

### Error / retry dialog

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Error / retry dialog](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/error_dialog-1280.png) | ![After: Error / retry dialog](after/error_dialog-1280.png) |

### Complete HUD — 1280×720

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Complete HUD — 1280×720](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-1280.png) | ![After: Complete HUD — 1280×720](after/hud-1280.png) |

### HUD — 1920×1080

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: HUD — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-1920.png) | ![After: HUD — 1920×1080](after/hud-1920.png) |

### HUD — 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: HUD — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-390.png) | ![After: HUD — 390×844](after/hud-390.png) |

### empty resources

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: empty resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-empty-1280.png) | ![After: empty resources](after/hud-empty-1280.png) |

### Complete HUD — partial resources

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Complete HUD — partial resources](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/hud-partial-1280.png) | ![After: Complete HUD — partial resources](after/hud-partial-1280.png) |

### In-game key bindings

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: In-game key bindings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/keybinds-1280.png) | ![After: In-game key bindings](after/keybinds-1280.png) |

### Leaderboard

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Leaderboard](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/leaderboard.png) | ![After: Leaderboard](after/leaderboard.png) |

### Loading

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Loading](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/loading_screen-1280.png) | ![After: Loading](after/loading_screen-1280.png) |

### Login — 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Login — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/login_screen-390.png) | ![After: Login — 390×844](after/login_screen-390.png) |

### Main menu — 1920×1080

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Main menu — 1920×1080](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-1920.png) | ![After: Main menu — 1920×1080](after/main-1920.png) |

### Main menu — 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Main menu — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/main-390.png) | ![After: Main menu — 390×844](after/main-390.png) |

### Minimap and kill feed

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Minimap and kill feed](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/minimap.png) | ![After: Minimap and kill feed](after/minimap.png) |

### Settings — audio

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Settings — audio](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-1280.png) | ![After: Settings — audio](after/settings-1280.png) |

### Settings — controls

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Settings — controls](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-controls-1280.png) | ![After: Settings — controls](after/settings-controls-1280.png) |

### Settings — 390×844

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Settings — 390×844](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-controls-390.png) | ![After: Settings — 390×844](after/settings-controls-390.png) |

### In-game settings

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: In-game settings](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-ingame-1280.png) | ![After: In-game settings](after/settings-ingame-1280.png) |

### Settings — video

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: Settings — video](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/settings-video-1280.png) | ![After: Settings — video](after/settings-video-1280.png) |

### World map

| Previous all-bronze UI | Mixed menu accents / preserved HUD and death |
| --- | --- |
| ![Before: World map](https://raw.githubusercontent.com/Operatorr/godot-networking-poc/9e0d2f8f37ce2e258556deffe30ce72705177e9b/docs/reviews/grimdark-ui/after/world-map-1280.png) | ![After: World map](after/world-map-1280.png) |

