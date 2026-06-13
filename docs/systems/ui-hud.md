# UI, HUD & menus

**Status:** Implemented (verified 2026-06-03 against code).

A catalogue of the client-side presentation layer: the pre-game menu flow, the in-Arena HUD, and
the combat effects. **All of this is client-only** — none of it runs on the headless server, and
none of it is authoritative. HUD widgets are pure projections of state the server already decided
(HP, kills, ping); menus drive auth/connection. Nothing here is predicted or validated.

> Terms per [`../CONTEXT.md`](../CONTEXT.md): **Local player**, **Remote entity**, **Game event**,
> **AoI**. The HUD reads the same buffers the renderer does — it never queries the server directly.

## Scene flow (pre-game)

Routed by `SceneManager` (`scene_manager.gd`), scene constants at `:11-15`:

```
login_screen ──login ok──▶ has character? ──no──▶ character_creation ──┐
     ▲                          │ yes                                  │
     │ logout                   ▼                                      ▼
     └──────────────────── main_menu ──Enter World / connect──▶ (loading) ──▶ arena_base
```

| Screen | Script | Does |
| --- | --- | --- |
| Login | `login_screen.gd` | Username/password → `AuthManager.login` (JWT); auto-login on saved token (`:201`); always routes to the **main menu** (the menu handles the no-character case). Themed art/font, button audio. |
| Character creation | `character_creation.gd` | Validates name (3–16 chars, `^[a-zA-Z0-9_]+$`, `:9-11`); a **class picker** (looping south-facing run-cycle preview from `SheetLibrary.class_frames` + 7 class buttons) sets the class sent in `POST /api/character/create`; stores name+class in `GameManager`, → main menu. **Back to Main Menu** returns without logging out (non-destructive cancel). |
| Main menu | `main_menu.gd` | **With a character** — character card: a looping **run-cycle preview** of the character (south-facing `run_0` from `SheetLibrary.class_frames`, tinted to match) sits left of the player-colour picker; the colour picker (tints the class sprite — see [`players-movement.md`](players-movement.md)) live-updates the preview tint; class label, and a **Delete** button on the right (`DELETE /api/character` after a confirm → swaps the card for the Create Character button, stays on the menu). **Without a character** — the card is replaced by a **Create Character** button (`→ goto_character_creation`) and **Enter World is disabled**. Region dropdown from `GET /api/regions`; **Enter World** stashes the region URL and `SceneManager.goto_sanctuary()` (the town hub; its Arena portal dials the server). |
| Loading | `loading_screen.gd` | "ENTERING THE ARENA" overlay with pulsing glow + animated dots; shown/hidden by `SceneManager._show_loading_screen` (`scene_manager.gd:240-271`) during transitions. |

`SceneManager` skips routing for `res://scenes/test/*` (`scene_manager.gd:78`).

### Menu support scripts

| File | Role |
| --- | --- |
| `ui/error_dialog.gd` | Reusable `PopupPanel` with title/message + optional Retry; used by login, character creation, main menu. `popup_window = false` so it survives click-outside/focus loss; it closes only via its buttons. |
| `ui/menu_button_helper.gd` | Applies the shared `StyleBoxTexture` button art + sizing to a button list. |
| `ui/menu_font_helper.gd` | Recursively applies `CormorantUnicase-Bold` to every `Control` in a tree (`:7-25`). |
| `region_info.gd` | Region DTO (`from_dict`, `is_available`, `get_display_text`) backing the dropdown. |
| `user_preferences.gd` | `RefCounted`, persists selected region + player colour to `user://preferences.json` (`:6`). The **only** client-side persistence here. |

## In-Arena HUD

The HUD lives on an `HUDLayer` (`CanvasLayer`) built by `arena_base.gd._setup_hud` (`:243-293`) in
client mode only. Each widget is `extends Control` and builds its own sub-tree in `_ready`.

| Widget | Script | Shows / does | Anchor |
| --- | --- | --- | --- |
| HP bar | `hud/hp_bar.gd` | current/max HP, colour-graded green→yellow→red, damage flash 0.3 s; width/offset configurable so it sits in the left slot. | bottom-centre, **left slot** |
| Mana bar | `hud/stat_bar.gd` | current/max mana (blue), driven by `movement_sm.mana_changed`. | bottom-centre, **right slot** |
| Stamina bar | `hud/stat_bar.gd` | sprint stamina (thin, spans HP+Mana width), driven by `movement_sm.stamina_changed`. | bottom-centre, **above HP/Mana** |
| Level / XP bar | `hud/experience_bar.gd` | `Lv N — exp / next` + progress fill; driven by `GameManager.experience_updated`, flashes on level-up. Shown in the Arena **and** offline hubs. See [`PROGRESSION.md`](PROGRESSION.md). | top-centre |
| Minimap | `hud/minimap.gd` | `_draw()` of arena, obstacles, self (green), players (red), monsters (orange) within 500 u (`:6-13,68-88`); reads `interpolation_controller.entity_last_states`. | top-right |
| Kill feed | `hud/kill_feed.gd` | last 3 "X eliminated Y" lines, each fades after 3 s (`:6-7,52`). | top-right, under minimap |
| Leaderboard | `hud/leaderboard.gd` | top 3 by PvP kills, **Tab** expands to top 10 (`:6-7,79-83`); highlights Local player + flash on kill (`:162-185`). | top-left |
| Server status | `hud/server_status.gd` | player/monster counts, ping (colour-coded), FPS; refreshes every 1 s (`:13,68-94`); reads `NetworkManager.get_stats()`. | bottom-left |
| Death screen | `hud/death_screen.gd` | "YOU DIED" + killer name (via `EntityNameCache`), respawn countdown (`RESPAWN_DELAY`), Space to respawn → `respawn_requested` (`:102-118,87-98`). | full-rect overlay |
| Pause menu | `hud/pause_menu.gd` | Esc toggles; Resume / Settings / Leave. **Game keeps running** (multiplayer). The leave button label is contextual (`set_leave_button_text`): the Arena returns to the **Sanctuary** ("RETURN TO SANCTUARY"), offline hubs exit to the menu. **T / tilde** also returns to the Sanctuary from the Arena (`return_to_sanctuary` action). | full-rect overlay |
| Settings menu | `hud/settings_menu.gd` | volume sliders + fullscreen/VSync toggles (persisted to `GameManager.settings`) + a **Keyboard Controls** page that lists/rebinds actions via `InputMap`, persisting to `user://preferences.json` (`UserPreferences.keybinds`, applied at startup). | child of pause menu |
| Connection-lost overlay | `hud/connection_lost_overlay.gd` | "CONNECTION LOST" + reconnect status; after 15 s emits `reconnect_failed` → return to menu (`:7,55-63`). | full-rect overlay |

### The server-safe HUD-creation pattern

The Arena scene exports to **both** client and headless server. A HUD `Control` script referencing
client-only globals would fail to parse during headless startup, so `arena_base.gd` never names the
classes or `preload`s the scenes. Instead it stores **string paths** (`arena_base.gd:16-23`) and
instantiates lazily:

```gdscript
func _create_hud_component(script_path: String, node_name: String) -> Control:
    var node := Control.new()
    node.set_script(load(script_path))   # runtime load(), never preload
    node.name = node_name
    return node
```

(`arena_base.gd:296-301`.) Components are typed as plain `Control` (`:55-62`); wiring is done via
`has_method`/`has_signal` guards and duck-typed property assignment (e.g. minimap refs at `:261-262`,
death-screen signal at `:276-277`). On the server, `_setup_hud` is never reached, so none of these
scripts ever load.

## Effects (combat juice)

Spawned into the Arena by `arena_base.gd` in response to Game events / local damage. All client-only,
cosmetic, auto-freeing.

| File | Role |
| --- | --- |
| `effects/damage_number.gd` | `DamageNumber` (`Node2D`): floating number that rises + fades over 0.8 s; green for damage dealt, red for taken (`:6-8,18-27`). Spawned at `arena_base.gd:544`. |
| `effects/particle_effects.gd` | `ParticleEffects` factory of one-shot `CPUParticles2D` — muzzle flash, hit sparks, death explosion, gore, spawn ring, projectile trail; each `_auto_free`s. |
| `effects/screen_effects.gd` | `ScreenEffects` (`Node`): camera shake (hit/kill/death presets `:7-9`), screen flash, 50 ms hit-stop via `Engine.time_scale` (`:96-101`). Camera ref set by `arena_base` (`:163-164`). |

## The eight questions

- **Client:** everything in this doc — menus, HUD widgets, effects; pure presentation.
- **Server:** nothing; the headless export never loads these scripts (`_setup_hud` is client-only).
- **Predicted:** nothing — the HUD reflects already-decided state (HP, kills, ping), never forecasts.
- **Replicated:** HUD values arrive via `STATE_UPDATE` (HP, positions) and `GAME_EVENT` (kills, death) and are merely displayed.
- **Persisted:** `user://preferences.json` (region, player colour, **keyboard rebinds**) and in-session `GameManager.settings`; accounts/characters (incl. class, **level + experience**) persist via the Go API.
- **Validated:** client-side input only — name regex/length (`character_creation.gd:72-94`); the server re-decides all gameplay.
- **Can fail:** missing `has_method`/`has_signal` guard would crash headless startup; stale `EntityNameCache` shows blank killer/feed names; region fetch failure falls back to defaults (`main_menu.gd:244`).
- **Tested:** manual/visual only — no automated UI tests. Sandbox scenes use inline overlays because `arena_base.tscn` can't load in test scenes (see `MEMORY.md`).

## See also

- [`players-movement.md`](players-movement.md) — HP bar & death screen react to player state
- [`combat-hits.md`](combat-hits.md) — Game events that drive kill feed, damage numbers, screen effects
- [`audio.md`](audio.md) — button/combat sounds triggered alongside this UI
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — why the FPS counter (server status) can read 100 while motion looks like 30
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — the `entity_last_states` buffer the minimap reads
