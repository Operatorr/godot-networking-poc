# Arena visuals — generated class/monster/projectile art + props

**Status: Implemented** (2026-06-13)

The arena's placeholder procedural sprites were replaced with generated pixel art
(PixelLab MCP) following the grimdark style guide
([`../design/STYLE_GUIDE_SHEET.png`](../design/STYLE_GUIDE_SHEET.png)): 7 player
classes with 8-direction animation sets, the Toxic Slime with state animations,
one animated projectile per class (+ the slime glob), and ~16 cosmetic props
placed around the arena. The procedural sprites remain as the fallback whenever
the generated assets are missing, so a checkout without the art keeps working.

## The eight questions

- **Client:** everything in this doc — all art is render-only.
  [`SheetLibrary`](../../client/scripts/systems/visuals/sheet_library.gd) builds
  `SpriteFrames` from sheet directories at runtime;
  [`player.gd`](../../client/scripts/entities/player/player.gd),
  [`remote_player.gd`](../../client/scripts/entities/player/remote_player.gd),
  [`monster.gd`](../../client/scripts/entities/enemies/monster.gd),
  [`projectile.gd`](../../client/scripts/entities/projectiles/projectile.gd) consume
  them; [`arena_base.gd`](../../client/scripts/levels/arena_base.gd) builds the
  prop layer (`ARENA_PROPS` table → "Props" Node2D ordered just before
  `EntityContainer`).
- **Server:** knows nothing about any of this. The only server-side change is
  the `class: u8` identity byte (protocol v3) it stores, clamps (>6 → 0) and
  re-broadcasts in PLAYER_INFO — see
  [`../server/contract.md`](../server/contract.md).
- **Predicted:** nothing. The local player's animation *reads* predicted motion
  (observed speed from position deltas picks idle/run/sprint/dash) but feeds
  nothing back into the sim.
- **Replicated:** `class` in ConnectAuth → PLAYER_INFO (cached by
  `EntityNameCache.get_entity_class`); the existing 3-bit AnimationState and
  entity flags drive which animation plays. Remote facing is **derived**, not
  replicated: 8-way row from interpolated movement deltas; one-shot anims latch
  the row they started on.
- **Persisted:** nothing (the Go API's `characters.class` column exists but does
  not flow into the ticket yet — class is client-chosen identity metadata).
- **Validated:** server clamps class to 0..=6. Nothing else to validate —
  cosmetic.
- **Can fail:** missing sheet directory → `SheetLibrary` returns null and every
  consumer falls back to the legacy procedural frames (warning logged once per
  path). Missing animation inside a sheet → aliased per the fallback tables
  (e.g. a bot class without `attack` plays `idle`; slime `hit`/`spawn` alias
  `idle`, with a red modulate flash on HIT instead).
- **Tested:** `scenes/test/arena_visual_smoke.tscn` — instantiates the arena
  (props + tilemap), parks a camera on the graveyard cluster and lines up one
  remote player per class, a slime, and all 8 projectiles. Capture with:
  `godot --path client res://scenes/test/arena_visual_smoke.tscn
  --write-movie /tmp/shots/visual.png --fixed-fps 10 --quit-after 16`.

## Sprite ground floor (Implemented 2026-06-16)

The Arena floor is a sprite layer in `client/assets/sprites/environment/arena/`:
`ground_stone1.png` is the seamless **base** tiled across the whole arena, and
`ground_variation1.png` / `ground_variation2.png` are **detail decals** scattered on top.
(`ground_darken.png` is intentionally **unused** — it reads as out-of-arena dark ground.)
[`arena_base.gd`](../../client/scripts/levels/arena_base.gd) `_build_arena_floor_decor()`
loads them (same `ResourceLoader.exists` + graceful-skip rule as the props) and adds a
`_GroundDecorLayer` (Node2D) named **"GroundDecor"** whose `_draw()` tiles the base at
`GROUND_TILE_SIZE = 250` (250 divides the 2000-unit arena into an exact 8×8 grid, no
overshoot past the ±1005 walls) then scatters the detail decals over ~45% of cells, jittered
±70px so they don't grid-align. It carries `MINIMAP_TERRAIN_VISIBILITY` so the floor still
appears on the minimap.

- **z-order:** `z_index = TILEMAP_Z_INDEX + 1` (= −9), `z_as_relative = false`. So it draws
  above the collision/minimap `TileMapLayer` (−10) and **below** the node's own `_draw()`
  (z 0), which paints only the obstacles + red border on top. On success
  `_build_arena_floor_decor()` sets `_paint_solid_floor = false`, which makes `_draw()` skip
  the opaque `FLOOR_COLOR` fill **and the vein grid** — the texture is the floor now (no grid).
- **Fallback:** if the base texture doesn't load (a checkout without the art), the layer is
  not added, `_paint_solid_floor` stays true, and the old procedural `FLOOR_COLOR` floor +
  vein grid is drawn as before.
- **Scope:** Arena only. The Sanctuary overrides `_build_level_environment()` (and sets
  `_draws_arena_floor = false`), so it never builds this layer — it paints its own town ground.

## Sheet format (the contract between the art pipeline and the client)

A *sheet asset* is a directory of `<anim>.png` grids plus a `meta.json`:

```
client/assets/sprites/players/<class_key>/   zealot, void_hunter, engineer,
                                             plague_seer, warrior, rogue, mage
client/assets/sprites/monsters/toxic_slime/
client/assets/sprites/projectiles/<class_key|slime>/
client/assets/sprites/environment/arena/<prop>.png   (plain single sprites)
```

- Directional sheets: one row per direction, fixed order
  `south, south-east, east, north-east, north, north-west, west, south-west`
  (`SheetLibrary.DIR_ORDER` == the assembler's `DIR_ORDER`); one column per
  frame. SpriteFrames animations are named `<anim>_<row>`.
- 1-direction sheets (slime, projectiles): single row, plain `<anim>` names.
- `meta.json`: `{canvas, directional, dir_order, anims: {<anim>: {frames, fps,
  loop, png}}}` — written by the assembler, single source of truth for frame
  counts and playback speed.
- **Per-class canvas normalization:** class sheets are not all the same source
  canvas — the bot classes are 92px, the redesigned **Zealot is 128px**.
  `SheetLibrary.class_sprite_scale(class_id)` returns
  `REFERENCE_CANVAS_PX (92) / canvas_height`, applied to the `AnimatedSprite2D`
  scale in `player.gd`/`remote_player.gd` so every class renders the same
  in-world size (92px → 1.0, 128px Zealot → ~0.72). It's purely cosmetic — the
  `CharacterBody2D` collision shape is unscaled. The procedural fallback keeps
  scale 1.0.
- Facing math: octant = `round(angle / 45°)` with 0° = +X/east, CW (+Y down);
  `SheetLibrary.OCTANT_TO_ROW` maps octants to rows. Projectile art must point
  **right**; art that ships rotated gets a per-class offset in
  `SheetLibrary._PROJECTILE_ROT_OFFSET_DEG`.

Animation sets as generated: **zealot** (the player) idle/run/sprint/dash/
attack/hit/death; **bot classes** idle/run/death; **toxic_slime**
idle/walk/attack/death; every projectile has a looping `fly`.

## Class identity on the wire (protocol v3)

`PacketTypes.PlayerClass`: ZEALOT=0, VOID_HUNTER=1, ENGINEER=2, PLAGUE_SEER=3,
WARRIOR=4, ROGUE=5, MAGE=6. The client sends its class in ConnectAuth (currently
always ZEALOT — "the player looks like the Zealot"); **load-test bots roll a
uniformly random class** at construction (`rust/load_test/src/bot.rs`, PCG32)
so a bot swarm shows the whole roster. The server stores + clamps it and
broadcasts PLAYER_INFO `[... r g b class]`; `EntityNameCache` caches it and
`RemotePlayer.set_player_class` swaps the sheet. Projectiles pick their art from
the **firing entity's** class (`client_entity_manager._apply_projectile_color`,
which knows the `source_id`); monster projectiles use the slime glob.

## Regenerating / extending the art

All PixelLab account UUIDs are recorded in
[`../../scripts/art/pixellab_manifest.json`](../../scripts/art/pixellab_manifest.json).
Characters and objects persist in the account; **map objects (props) auto-delete
~8 h after creation** — regenerate rather than re-download.

Pipeline (see `scripts/art/`):
1. Generate via the PixelLab MCP (characters: v3 mode, 48 px, low top-down;
   animations: template mode for locomotion 1 gen/direction, v3 custom for
   sprint/dash/attack; props: `create_map_object`, ~1 gen each).
2. Download the character/object zip from
   `https://api.pixellab.ai/mcp/{characters|objects}/<id>/download` (refuses
   while jobs are still running; per-call animation folders are slugs of the
   action description — cardinals and diagonals of one logical animation land
   in suffixed sibling folders).
3. `scripts/art/assemble_character.py <extract> <CharFolder> <out_dir>
   <map.json>` merges folders by prefix into logical animations and emits the
   grid sheets + `meta.json` (via `assemble_pixellab_sheets.py`, which also
   handles the 1-direction objects).
4. `godot --headless --import` from `client/` so the editor cache picks up the
   new PNGs, then run the visual smoke above.

Account/job constraints that shaped the pipeline: max 10 concurrent jobs
(an 8-direction animation call = 8 slots), raw CDN frame URLs 403 outside the
MCP session (use the zip endpoints), `create_1_direction_object` returns a
multi-candidate review pack (16–64 candidates for ~20 gens) — `item_descriptions`
cycle in order, which is how all 8 projectile designs came from one call.
