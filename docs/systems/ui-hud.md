# UI, HUD & menus

**Status:** Implemented (verified 2026-06-15 against code; HUD refactored from procedural GDScript
into one reusable `game_hud.tscn` composed of per-widget scenes).

A catalogue of the client-side presentation layer: the pre-game menu flow, the in-Arena HUD, and
the combat effects. **All of this is client-only** — none of it runs on the headless server, and
none of it is authoritative. HUD widgets are pure projections of state the server already decided
(HP, kills, ping); menus drive auth/connection. Nothing here is predicted or validated.

> Terms per [`../CONTEXT.md`](../CONTEXT.md): **Local player**, **Remote entity**, **Game event**,
> **AoI**. The HUD reads the same buffers the renderer does — it never queries the server directly.

## Scene flow (pre-game)

Routed by `SceneManager` (`scene_manager.gd`), scene constants at `:11-17` (SCENE_LOGIN … SCENE_SANCTUARY, incl. SETTINGS/ARENA/SANCTUARY):

```
login_screen ──login ok──▶ has character? ──no──▶ character_creation ──┐
     ▲                          │ yes                                  │
     │ logout                   ▼                                      ▼
     └──────────────────── main_menu ──Enter World──▶ sanctuary ──portal──▶ arena_base
                              │  └──Enter Arena──▶ (loading) ──▶ arena_base
                              └──Settings──▶ settings_screen ──Back──▶ main_menu
```

| Screen | Script | Does |
| --- | --- | --- |
| Login | `login_screen.gd` | Username/password → `AuthManager.login` (JWT); auto-login on saved token (`:201`); always routes to the **main menu** (the menu handles the no-character case). Themed art/font, button audio. A **"Use local server (dev)"** checkbox switches the auth/account API between production (`ClientConfig.production_api_base_url`) and the local Go API (`local_api_base_url`) via `AuthManager.set_use_local_api`, persisting the choice to `UserPreferences.use_local_api` (logs out any active session so the next login re-auths against the new server). |
| Character creation | `character_creation.gd` | Validates name (3–16 chars, `^[a-zA-Z0-9_]+$`, `:9-11`); a **class picker** (looping south-facing run-cycle preview from `SheetLibrary.class_frames` + 7 class buttons) sets the class sent in `POST /api/character/create`; stores name+class in `GameManager`, → main menu. **Back to Main Menu** returns without logging out (non-destructive cancel). |
| Main menu | `main_menu.gd` | Shows the account's **Glory** (sulfur-yellow `GloryLabel`) at the top, under the title. **With a character** — character card: a looping **run-cycle preview** (south-facing `run_0` from `SheetLibrary.class_frames`, tinted to match) sits left of the player-colour picker; the colour picker (tints the class sprite — see [`players-movement.md`](players-movement.md)) live-updates the preview tint; **username above class** (name white, class grey beneath), and a **Delete** button on the right (`DELETE /api/character` after a confirm → swaps the card for the Create Character button, stays on the menu). **Without a character** — the card is replaced by a **Create Character** button (`→ goto_character_creation`) and **Enter World / Enter Arena are disabled**. Region dropdown (`GET /api/regions`, width-matched to the buttons); **Enter World** dials the region's Sanctuary (8082) and `goto_sanctuary()`; **Enter Arena** dials the region's Arena (8081) directly and `goto_arena()`, skipping the town. **Settings** (above Logout) → `goto_settings()`. On entry it calls `AuthManager.refresh_character()` to re-confirm the character + Glory from the API (keeps the menu honest after an async permadeath). |
| Settings | `settings_screen.gd` (`settings_screen.tscn`) | Standalone tabbed Settings reached from the menu's **Settings** button. **Audio** tab: Master/Music/SFX sliders (→ `GameManager.update_setting` → `AudioManager`). **Video** tab: a **Windowed Fullscreen** toggle (on = `window_mode` `windowed_fullscreen`, off = a small centred window) + **VSync**. **Controls** tab: read-only listing of every action (WASD, Shoot LMB, Ability RMB, Dash Space, Sprint, Interact, Map, Pause, Return to Sanctuary, Exit) and its live binding. **Back** → main menu. |
| Loading | `loading_screen.gd` | "ENTERING THE ARENA" overlay with pulsing glow + animated dots; shown/hidden by `SceneManager._show_loading_screen` (`scene_manager.gd:256-281`) during transitions. |

`SceneManager` skips routing for `res://scenes/test/*` (`scene_manager.gd:78`).

### Menu support scripts

| File | Role |
| --- | --- |
| `ui/error_dialog.gd` | Reusable `PopupPanel` with title/message + optional Retry; used by login, character creation, main menu. `popup_window = false` so it survives click-outside/focus loss; it closes only via its buttons. |
| `ui/menu_button_helper.gd` | Applies the shared `StyleBoxTexture` button art + sizing to a button list. |
| `ui/menu_font_helper.gd` | Recursively applies `CormorantUnicase-Bold` to every `Control` in a tree (`:7-25`). |
| `region_info.gd` | Region DTO (`from_dict`, `is_available`, `get_display_text`) backing the dropdown. |
| `user_preferences.gd` | `RefCounted`, persists selected region + player colour + keybinds + the **local-API toggle** (`use_local_api`) to `user://preferences.json` (`:6`). The **only** client-side persistence here. |

## In-Arena HUD

The HUD is a single reusable scene — `scenes/ui/hud/game_hud.tscn` (`GameHud`, a `CanvasLayer`) —
that composes one editable `.tscn` per widget. Every world (Arena, Sanctuary, the offline modes)
instantiates it the same way: `arena_base.gd._setup_hud` / `offline_arena.gd._setup_hud` call
`load(GAME_HUD_PATH).instantiate()`, name it `HUDLayer` (so `get_hud_layer()` keeps working), and
talk to its typed widget refs (`hud.health_bar`, `hud.kill_feed`, …) plus four re-emitted signals
(`respawn_requested`, `main_menu_requested`, `leave_arena_requested`, `reconnect_failed`). `@export`
toggles (`show_leaderboard` / `show_server_status` / `show_kill_feed`) let the offline modes hide the
networked-only widgets. Each widget is its own scene under `scenes/ui/hud/` with the script on the
root and `@onready` node refs — no procedural `_build_ui()`.

| Widget | Script | Shows / does | Anchor |
| --- | --- | --- | --- |
| HP bar | `hud/health_bar.gd` (`health_bar.tscn`) | current/max HP, colour-graded green→yellow→red via `tint_progress`, damage flash 0.3 s. | bottom-centre, **left slot** |
| Mana bar | `hud/resource_bar.gd` (`mana_bar.tscn`) | current/max mana, driven by `movement_sm.mana_changed`. | bottom-centre, **right slot** |
| Stamina bar | `hud/resource_bar.gd` (`stamina_bar.tscn`) | sprint stamina (thin, spans the ability-bar width), driven by `movement_sm.stamina_changed`; frame flashes red when exhausted. | bottom-centre, **above the ability bar** |
| Ability bar | `hud/ability_bar.gd` (`ability_bar.tscn`) | six slot frames + key labels; the SPACE slot draws a radial dash-cooldown wedge and the RMB slot a class-ability-cooldown wedge from `movement_sm` (both timers are owned by the Rust sim online and mirrored into the SM via `set_predicted_cooldowns`; offline the SM ticks them itself). | bottom-centre, **between HP & Mana** |
<!-- The bars are now `TextureProgressBar` (texture_under = track, texture_progress = fill, fill_mode = left-to-right) sized to the trough inset, with the frame sprite as a sibling overlay. The HP colour grade / damage flash drive `tint_progress`; the stamina exhaustion blink drives the frame node's `modulate`. -->
<!-- Camera-zoom and sprint footsteps key off `Player.is_sprinting()` (sprint held AND moving AND not exhausted/dazed AND stamina > 0), NOT the raw `sprint` action, so both stop the instant the sim refuses to sprint. -->

| Level / XP bar | `hud/experience_bar.gd` | `Lv N — exp / next` + progress fill; driven by `GameManager.experience_updated`, flashes on level-up. Shown in the Arena **and** offline hubs. See [`PROGRESSION.md`](PROGRESSION.md). | top-centre |
| Minimap | `hud/minimap.gd` (`minimap.tscn`) | top-down view of the **real world**: the level terrain is rendered **once** into a static texture by `WorldMapView` (`hud/world_map_view.gd`, terrain-only via the visibility-layer whitelist); the minimap **pans a clipped window** of it centred on the player and overlays group dots — monsters red, NPCs green, other players red+purple, local player green marker, landmarks (Arena Portal) yellow. No per-frame world render. See [`minimap.md`](minimap.md). | top-right |
| Map overlay | `hud/map_overlay.gd` (`map_overlay.tscn`) | Diablo-style fullscreen, semi-transparent map toggled by **M** (`toggle_map`, rebindable); shows the **whole** static `WorldMapView` texture aspect-fit + dots. Non-blocking (game keeps running), no viewport/render of its own. See [`minimap.md`](minimap.md). | full-rect overlay |
| Kill feed | `hud/kill_feed.gd` | last 3 "X eliminated Y" lines, each fades after 3 s (`:6-7,52`). | top-right, under minimap |
| Leaderboard | `hud/leaderboard.gd` | top 3 by PvP kills, **Tab** expands to top 10 (`:6-7,79-83`); highlights Local player + flash on kill (`:162-185`). | top-left |
| Server status | `hud/server_status.gd` | player/monster counts, ping (colour-coded), FPS; refreshes every 1 s (`:13,68-94`); reads `NetworkManager.get_stats()`. | bottom-left |
| Death screen | `hud/death_screen.gd` | "YOU DIED" + killer name (via `EntityNameCache`). **Softcore:** respawn countdown (`RESPAWN_DELAY`), Space to respawn → `respawn_requested`, then re-emitted every `RESPAWN_RETRY_INTERVAL` until the `RESPAWN` event arrives (`hide_death` stops it). The retry is required because the server silently drops a request whose `respawn_timer` hasn't elapsed, and on localhost the client countdown and that timer expire in a dead heat — a single request loses the race and the screen would stick on "Respawning…" forever (the load-test bots retry for the same reason). **Hardcore:** no countdown — "Your Glory will be remembered" + "**+N Glory earned**" (sulfur-yellow; `N` = `GameManager.glory_for_death()`, the client recompute of the exact amount the server credited — identical curve+divisor, no wire field, see [`PROGRESSION.md`](PROGRESSION.md)) + "Back to Main Menu" button → `main_menu_requested`; the server has already converted XP→Glory + deleted the character, then kicks the client (the expected kick is ignored, not shown as a reconnect). `arena_base` picks the variant via `GameManager.is_hardcore()`. | full-rect overlay |
| Pause menu | `hud/pause_menu.gd` | Esc toggles; Resume / Settings / Leave. **Game keeps running** (multiplayer). The leave button label is contextual (`set_leave_button_text`): the Arena returns to the **Sanctuary** ("RETURN TO SANCTUARY"), offline hubs exit to the menu. **T / tilde** also returns to the Sanctuary from the Arena (`return_to_sanctuary` action). | full-rect overlay |
| Settings menu | `hud/settings_menu.gd` | in-game (pause) settings: volume sliders + a **Windowed Fullscreen** toggle (drives `GameManager.settings.window_mode`, shared with the launch default and the standalone Settings screen) + VSync + a **Keyboard Controls** page that lists/rebinds actions via `InputMap`, persisting to `user://preferences.json` (`UserPreferences.keybinds`, applied at startup). | child of pause menu |
| Connection-lost overlay | `hud/connection_lost_overlay.gd` | "CONNECTION LOST" + reconnect status; after 15 s emits `reconnect_failed` → return to menu (`:7,55-63`). | full-rect overlay |

### The server-safe HUD pattern

`arena_base.tscn` can be parsed by headless tooling, and the HUD scripts reference client-only
autoloads (`NetworkManager`, `GameManager`). To keep the HUD scene out of any headless instantiation
path, `game_hud.tscn` is **never** `[ext_resource]`-referenced or `preload`ed by a level scene — the
levels load it at runtime inside the **client-only** `_setup_hud()`:

```gdscript
const GAME_HUD_PATH := "res://scenes/ui/hud/game_hud.tscn"
hud = load(GAME_HUD_PATH).instantiate()   # runtime load(), never preload
hud.name = "HUDLayer"
add_child(hud)
```

`_setup_hud` runs only from `_setup_client` (client mode), so on the server the HUD scene is never
instantiated and its widget `_ready`s never run. The level then reads typed widget refs off `hud`
(`hud.health_bar`, `hud.death_screen`, …) and connects the four re-emitted signals — no
`has_method`/`has_signal` guards needed.

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
- **Persisted:** `user://preferences.json` (region, player colour, **keyboard rebinds**, **local-API toggle**) and in-session `GameManager.settings` (incl. `window_mode` — the game **launches in windowed-fullscreen** by default; `_load_settings` migrates the legacy boolean `fullscreen` key away); accounts/characters (incl. class, **level + experience**) and **account Glory** persist via the Go API.
- **Validated:** client-side input only — name regex/length (`character_creation.gd:72-94`); the server re-decides all gameplay.
- **Can fail:** `[ext_resource]`-referencing `game_hud.tscn` from a level scene would pull the client-only HUD scripts into the headless parse graph (so it's always `load()`ed at runtime); stale `EntityNameCache` shows blank killer/feed names; region fetch failure falls back to defaults (`main_menu.gd._populate_default_regions`). **Character creation** can return HTTP 409 `{"error":"User already has a character","code":"character_exists"}` while a hardcore permadeath delete is still in flight — `character_creation.gd` self-heals by re-syncing `/api/character/me` (`AuthManager.refresh_character`) and either routing to the surviving character or retrying the create once.
- **Tested:** `scenes/test/hud_bar_regression.tscn` exercises the health bar (instantiates `health_bar.tscn`, asserts the fill ratio); otherwise manual/visual. The offline Sandbox now reuses the shared `GameHud` (kill feed / leaderboard / minimap / death screen) instead of bespoke overlays.

## See also

- [`players-movement.md`](players-movement.md) — HP bar & death screen react to player state
- [`combat-hits.md`](combat-hits.md) — Game events that drive kill feed, damage numbers, screen effects
- [`audio.md`](audio.md) — button/combat sounds triggered alongside this UI
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — why the FPS counter (server status) can read 100 while motion looks like 30
- [`minimap.md`](minimap.md) — the shared-`World2D` SubViewport minimap + group-driven dots
