# Sanctuary — City Layout & Scene Design

Status: **redesigned** — a vast walled city you can walk through *and enter the buildings of*
(Tibia-style), rendered as **code-generated placeholders** in a 3/4 top-down **oblique**
look (Hammerwatch / Heroes of Hammerwatch). Real art is dropped in later.
Style: [`SANCTUARY_STYLEGUIDE.md`](SANCTUARY_STYLEGUIDE.md) + `Sanctuary Style Guide Sheet.png`.

The Sanctuary is the player's safe hub. **Entering the world lands you here, not the Arena.**
It is a fully client-local scene (no server connection, like Practice): you walk, explore,
browse NPCs, then take the **Arena portal**, which dials the selected region's game server and
only then loads the Arena. This keeps unauthenticated connections from idling open while a
player explores, and lets the town work offline.

## Flow

```
Main Menu ── Enter World ──> Sanctuary (offline hub)
                                 │  Arena Portal (interact)
                                 │  └─ NetworkManager.connect_to_server(selected region)
                                 ▼
                               Arena (server-authoritative)
```

- The main menu owns region selection; it stashes the chosen region's URL in
  `GameManager.player_data["selected_region_url"]` before `SceneManager.goto_sanctuary()`.
- `Portal` (`scripts/entities/portal.gd`) is the reusable level/scene-switch script;
  `requires_connection` makes it dial the server first.

## Rendering model (the oblique placeholder look)

The whole city is **data-driven** from `const` tables in
[`scripts/levels/sanctuary.gd`](../../client/scripts/levels/sanctuary.gd)
(`OfflineArena` subclass). Tables are "rasterized" onto a tile grid; layers then render it.

- **Tile grid.** `TILE = 32 px` (matches the 32 px player sprite; hitbox r16). North = −Y.
- **Oblique walls.** Every wall cell is drawn as a lifted **sunlit top** + a **shadowed south
  face** (+ base contact shadow). Cells are drawn north→south so southern faces overlap the
  walls behind them — only outer faces stay visible, the Hammerwatch wall read. Heights:
  buildings 28 px, rampart 36 px, raised-terrace cliffs 20 px.
- **Raised terraces + stairs.** The Cathedral and the Portal Dais sit on raised stone
  terraces (cliff-edge walls) reached by **walkable stair-ramp placeholders**. Single Z-level
  for now (stairs are walkable, no floor switch) — tagged `future = "elevation/floor-switch"`.
- **Roofs are intentionally absent** so interiors are visible from above; you walk in through
  the door gap (Tibia/Hammerwatch ground-floor behaviour).
- **Layers / z-order.** `Ground` (z −20) → `WallVisuals` (z −8) → `World` props/NPCs/
  fountain/portal (z −4) → player (z 0). The Sanctuary node's own `_draw` is overridden empty
  so `OfflineArena`'s dark arena grid never paints over the city.
- **Collision.** `CityColliders` is one `StaticBody2D` on `ENVIRONMENT_COLLISION_LAYER` (8);
  wall cells are greedy-merged per row into rectangle colliders — **every wall grid square is
  solid** (1346 wall cells → 447 colliders). Door/stair gaps carry no collider. Solid props
  get their own colliders under `PropColliders` / `InteriorProps`.

## City plan

A radial-axial walled city. Two avenues cross at the central **Fountain Plaza**; the
cathedral terminates the north vista, the portal dais the south; commerce east, guilds west.

```
                         N  (rampart, no gate — Cathedral backs it)
        ┌──────────────[CATHEDRAL TERRACE + stairs]──────────────┐
        │  [cottage]            │ Grand Avenue │      [Bank]      │
        │ [Mages][Warriors]     │              │   [Potion shop] │
   W ═══╪══ Guild Court ════[FOUNTAIN PLAZA]════ Market Sq ══════╪═══ E
  gate  │ [Rogues]              │              │  [Equip shop]   │  gate
        │ [Inn]   [cottage]     │              │ [cottage][cottage]
        │                [PORTAL DAIS + stairs]                  │
        └────────────────────────────────────────────────────────┘
                         S  (rampart, no gate — Dais backs it)
```

- **Bounds.** Town/boundary rect `(-1856,-1856)..(1856,1856)` (`OfflineArena` hard walls,
  `wall_thickness` 32). A decorative **rampart** ring (2 tiles thick, tiles ±53..±54 ≈ world
  ±1696..±1728) encloses the playable interior, with **east + west gates** (4 tiles wide,
  banners). North/south rampart is solid — the Cathedral and Dais back onto it. A grass moat
  margin sits between the rampart and the boundary.
- **Spawn** `(0, 192)` — south rim of the fountain plaza.

### Buildings (footprint rect, door side · all ENTERABLE)

| Building | Footprint (x, y, w, h) | Door |
| --- | --- | --- |
| Church of the Dawn (on Cathedral Terrace) | (−288, −1600, 576, 384) | S |
| Cathedral Terrace (raised platform) | (−416, −1664, 832, 512) | S (stairs) |
| Warriors' Guild | (−1280, −672, 384, 352) | S |
| Mages' Guild | (−1664, −672, 320, 352) | S |
| Rogues' Guild | (−1280, 320, 384, 352) | N |
| Bank of the Sanctuary | (512, −960, 384, 384) | S |
| The Bubbling Flask (potions) | (928, −576, 352, 320) | S |
| Hammer & Hilt (equipment) | (928, 256, 352, 320) | N |
| The Resting Lantern (inn) | (−1344, 704, 448, 384) | E |
| Cottage (north) | (−832, −1024, 256, 224) | S |
| Cottage (SE a) | (512, 768, 256, 224) | W |
| Cottage (SE b) | (960, 768, 256, 224) | W |
| Portal Dais (raised platform) | (−256, 1088, 512, 384) | N (stairs) |

Each building is an enclosure of perimeter walls minus a door gap, with an **interior floor**
(wood/stone), **interior walls**, **furniture placeholders** (counter/shelf/table/bed/altar/
pews/weapon-rack/bookshelf/chests/barrels/crates), and its NPC standing inside.

### NPCs (kept art, `assets/sprites/npcs/`) — inside their themed building

| NPC | Role | Position |
| --- | --- | --- |
| Father Aldric — High Priest | Priest: spend Glory / account skill tree (stub) | (0, −1312) |
| Master Brandt | Warrior class trainer | (−1088, −432) |
| Archmagus Elowen | Mage class trainer | (−1504, −432) |
| Shade Vesper | Rogue class trainer | (−1088, 432) |
| Tilda Brewbloom | Potion vendor | (1104, −400) |
| Garrick Forgehand | Equipment vendor | (1104, 400) |
| Goldwin Ledger | Bankmaster | (704, −700) |

### Landmarks, stairs & ground

| Element | Geometry |
| --- | --- |
| Healing Fountain (kept art, collider r64) | (0, 0) |
| Arena Portal (kept art) | (0, 1280) |
| Cathedral grand stairs (walkable) | rect (−96, −1184, 192, 96) |
| Portal dais stairs (walkable) | rect (−96, 1024, 192, 96) |
| Grand Avenue (N–S cobble) | x −64..64, y −1024..1088 |
| Market/Guild Street (E–W cobble) | y −64..64, x −1696..1696 |
| Fountain Plaza (cobble circle) | r304 @ (0, 0) |
| Market Square (plaza) | (768, −288, 640, 576) |
| Guild Court / Bank connector / Forecourt / Inn approach | see `ROADS` table |
| Reflecting pools (decorative water) | SW (−1568, 1216, 256, 192), NE (1280, −1440, 224, 192) |
| Outdoor props | trees, lantern posts (auto along avenues), benches, market stalls, barrels/crates, signposts, gate banners, notice board, well, flower beds, planters |

## Assets — kept vs removed

- **Kept** (still real sprites): the **Fountain** (`town/fountain_idle_sheet.png`), the
  **Arena Portal** (`town/portal_idle_sheet.png`), and all **NPC** sprites (`npcs/*.png`).
- **Removed** (now code-generated placeholders): the 7 building PNGs, the `ground_tiles`
  Wang tileset + metadata, and the old prop PNGs (tree/lantern/bench/stall/board/flowers).

## Replacing placeholders with real art

Every placeholder element is **findable and tagged**:

- It is in the `"placeholder"` node **group** and carries meta `placeholder=true`,
  `replace_with=<hint>`, plus geometry meta (`footprint`, `kind`).
- The scene tree mirrors the tables: `World/Buildings/<Key>` (Marker2D slot + plaque +
  `<Key>Interior` furniture), `World/Terraces/*`, `World/Stairs/*`, `World/Props/*`,
  `Ground`, `WallVisuals`, `CityColliders`.
- Drop in art by replacing a slot's drawn placeholder with a `Sprite2D`/tileset at the same
  transform. **`CityColliders` is independent of the visuals**, so swapping art never changes
  where walls block. Stairs are tagged for future client-side multi-floor logic.

## Scene & script inventory

| File | What |
| --- | --- |
| `client/scenes/levels/hub/sanctuary.tscn` | Town scene (root + script; layout is data-driven) |
| `client/scripts/levels/sanctuary.gd` | `OfflineArena` subclass; rasterizes the city tables into ground/walls/colliders/buildings/props/terraces/stairs |
| `client/scenes/entities/portal/portal.tscn` + `scripts/entities/portal.gd` | Reusable scene-switch portal |
| `client/scenes/entities/npc/npc.tscn` + `scripts/entities/npc.gd` | Interactable service NPC (prompt + dialog panel) |

The eight questions: **client** runs everything (town is client-local); **server** runs
nothing until the Arena portal dials it; nothing is **predicted/replicated/persisted**
(Glory/skill-tree/shop/bank are stubs through the Go API when implemented); **validated**: the
portal refuses to enter the Arena without a region URL or on failed connect; **fails**: connect
timeout shows on the portal prompt and resets; **tested**: headless scene-load smoke (no
errors, "1346 wall cells → 447 colliders") + whole-city / district screenshot review.
