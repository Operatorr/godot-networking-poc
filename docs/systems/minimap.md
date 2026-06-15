# Minimap

**Status:** Implemented (2026-06-15). Client-only, cosmetic, non-authoritative.

The minimap is a zoomed-out top-down view of the **actual game world** that follows the local
player, with dynamic entities filtered out of the backdrop and re-drawn as coloured dots. A
fullscreen map overlay (**M**) shows the whole level. Works identically in the Arena, the Sanctuary,
and the offline modes.

## Architecture — render once, then pan a static texture

The level terrain never changes after it builds, so it is rendered **once** into a static texture
and reused — there is **no per-frame world rendering** (an earlier design re-rendered the whole world
into an always-on `SubViewport` every frame and tanked FPS, because the town/arena terrain is a few
huge canvas items with thousands of cached draw-commands that get fully re-submitted per viewport).

1. **`scenes/ui/hud/world_map_view.tscn`** (`WorldMapView`, `ui/hud/world_map_view.gd`) — a
   `SubViewport` owned by `GameHud`. `setup_world_map(bounds)` sizes it to the level's aspect (longest
   side `MAX_RESOLUTION = 2048`), frames the **whole level** with a `Camera2D`
   (`zoom = size / bounds.size`), shares the main world, renders **only terrain**
   (`canvas_cull_mask = MINIMAP_TERRAIN_BIT`), then sets `render_target_update_mode = UPDATE_ONCE`
   after two frames (so the terrain's queued `_draw()` has run) and goes idle. Its `get_texture()` is
   the static whole-level map.

   > **World-share gotcha:** `world_2d = get_tree().root.get_world_2d()`, **not**
   > `get_viewport().world_2d` — `get_viewport()` on a `SubViewport` returns the SubViewport *itself*,
   > so that form silently no-ops and the viewport renders its own empty world.

2. **`scenes/ui/hud/minimap.tscn`** (`Minimap`, `ui/hud/minimap.gd`) — the HUD widget. `GameHud` hands
   it the static texture + bounds (`set_world_map`) and the local player (`set_minimap_player`). Each
   frame it draws the whole texture under a world→minimap transform centred on the player
   (`dest = mc + (bounds.position - player) * MINIMAP_ZOOM`, size `bounds.size * MINIMAP_ZOOM`) and
   relies on `clip_contents` to crop it to the frame — i.e. it **pans a window** of the static map.
   Then it overlays the dots and the decorative frame. Per frame: one (clipped) textured quad + a few
   dots.

3. **`scenes/ui/hud/map_overlay.tscn`** (`MapOverlay`, `ui/hud/map_overlay.gd`) — the fullscreen map
   (see below). It shows the **whole** static texture aspect-fit, so it needs no viewport of its own.

`GameHud.setup_world_map(bounds)` is called once per level from `arena_base.gd`/`offline_arena.gd`
`_setup_hud`; `bounds` comes from the level's `get_map_bounds()` (ArenaBase → play-field;
Sanctuary → `TOWN_RECT`; OfflineArena → `arena_rect`).

### Terrain whitelist (how entities are filtered out)

Terrain is *whitelisted*: terrain CanvasItems set
`visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY` (main layer 1 **plus** the minimap
bit), and `WorldMapView.canvas_cull_mask` is the minimap bit only. Everything else stays on the
default layer 1 and never renders into the map texture.

**Cascade gotcha:** a viewport that culls a CanvasItem also hides its **entire subtree**, regardless
of the children's own `visibility_layer` (Godot's split-screen/parallax rule). So every *intermediate
container* a terrain node sits under must also carry the minimap bit — not just the leaf that draws.
Terrain set today: the Arena root `_draw` floor + `TileMapLayer` + the `Props` container & its prop
sprites (`arena_base.gd`); the offline `_draw` floor host (`offline_arena.gd`); and the Sanctuary
`TownWorld` root + its ground and rampart layers (`sanctuary.gd` / `town/sanctuary_town_world.gd`).
The `EntityContainer` deliberately stays on layer 1, so the player/monster/projectile subtree is
culled and represented only by dots.

### Dots (decoupled via groups)

Entities self-register in `_ready`; the minimap/overlay iterate the groups each frame and project
each member's `global_position` into screen space (the minimap centres on the player; the overlay
maps the level bounds onto its panel):

| Group | Joiner | Dot |
| --- | --- | --- |
| `minimap_player_local` | `Player` (local) | green marker (white ring), at centre |
| `minimap_player_remote` | `RemotePlayer` | red dot with a purple border |
| `minimap_monster` | `Monster`, `OfflineMonster`, `TargetDummy` | red |
| `minimap_npc` | `TownNpc` | green |
| `minimap_landmark` | `Portal` (e.g. the Arena Portal) | yellow — clamped to the rim so it stays findable when off-view |

Because dots come from groups (not the network buffer), the minimap needs no `interpolation_controller`
and works the same offline. The widget draws only the background when it has no texture/player yet
(test scenes / headless / the few frames before the one-time render lands).

## Fullscreen map overlay (M)

`MapOverlay` is a Diablo-style fullscreen map toggled by the `toggle_map` action (**M**, rebindable in
Settings → Keyboard Controls). It is **non-blocking** (`mouse_filter = IGNORE`) — the game keeps
running while it's open — dims the screen, draws the **whole** static world-map texture aspect-fit
into a centred panel, and overlays the group dots mapped by their normalised position within the
level bounds. No viewport of its own and no per-frame world render: opening it costs one texture blit
+ dots.

## The eight questions

- **Client:** everything — the one-time terrain render, the texture pan, the dot overlay.
- **Server:** nothing; the map scenes only instantiate client-side (in `GameHud`).
- **Predicted:** nothing — dots read live `global_position`; the pan tracks the (already
  predicted/interpolated) player.
- **Replicated:** indirectly — entity positions arrive via the normal entity sync; the map just reads
  the resulting nodes.
- **Persisted:** nothing (the `toggle_map` keybind persists via `UserPreferences`).
- **Validated:** nothing — cosmetic.
- **Can fail:** the `WorldMapView` must render *after* the terrain's `_draw()` (handled by the
  two-frame defer) or the map is blank; a level with no terrain on the minimap layer renders an empty
  backdrop (dots still work). The static texture assumes terrain is immutable — re-call
  `setup_world_map` if a level ever changes terrain at runtime.
- **Tested:** `_ui_smoke` instantiation harness (HUD + `setup_world_map` + map toggle) in headless;
  otherwise manual/visual — confirm terrain backdrop, player-follow pan, the **M** overlay, and
  correct dots in Arena / Sanctuary / Sandbox, with FPS unaffected.

## See also

- [`ui-hud.md`](ui-hud.md) — the HUD the minimap is part of
- [`players-movement.md`](players-movement.md) — the local player the minimap follows
