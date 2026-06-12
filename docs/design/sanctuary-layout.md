# Sanctuary — Town Layout & Scene Design

Status: **implemented** (scene + layout); sprite pass via PixelLab in progress.
Style: [`SANCTUARY_STYLEGUIDE.md`](SANCTUARY_STYLEGUIDE.md) + `Style Guide Sheet.png`.

The Sanctuary is the player's safe hub. **Entering the world now lands you here, not the
Arena.** The town is a fully client-local scene (no server connection, like Practice): you
walk, browse NPCs, then take the **Arena portal**, which dials the selected region's game
server and only then loads the Arena. This keeps unauthenticated connections from idling
open while a player shops, and lets the town work offline.

## Flow

```
Main Menu ── Enter World ──> Sanctuary (offline hub)
                                 │  Arena Portal (interact)
                                 │  └─ NetworkManager.connect_to_server(selected region)
                                 ▼
                               Arena (server-authoritative)
```

- The main menu still owns region selection; it stashes the chosen region's URL in
  `GameManager.player_data["selected_region_url"]` before `SceneManager.goto_sanctuary()`.
- `Portal` (`scripts/shared/portal.gd`) is the **reusable level/scene-switch script** — it
  will also serve world entrances and dungeon entry/exit. Destination is an exported enum
  (`ARENA`, `SANCTUARY`, `MAIN_MENU`, `PRACTICE`, `CUSTOM_SCENE` + scene path);
  `requires_connection` makes it dial the server first.

## City planning

A compact radial-axial plan (classic European town logic) so every district is legible
from the spawn point:

- **Center — Fountain Plaza.** The healing fountain is the spawn landmark; the whole town
  reads from here. Plaza is a 240 u-radius paved circle.
- **Sacred axis (north).** Cathedral Way runs due north from the fountain and terminates
  the vista at the **Church of the Dawn** — the tallest silhouette in town, on a raised
  forecourt. The **Priest** (glory spending / account skill tree) serves at its doors.
- **Civic northeast.** The **Bank** sits on its own connector street between plaza and
  market — prominent, near the money.
- **Commerce east — Market Street.** Widens into a market square: **Potion Vendor** (north
  side), **Equipment Vendor** (south side), open stalls at the east end.
- **Guilds west — Guild Row.** Ends in a U-shaped Guild Court enclosed by the **Warriors'
  Guild** (north), **Mages' Guild** (west), **Rogues' Guild** (south) — class trainers in
  front of each hall.
- **Travel south — Portal Way.** Leads to the Portal Dais, a round plinth holding the
  **Arena portal** (and future world/dungeon portals).
- Green space fills the quadrants: lawns, trees, flower beds; lantern posts pace the two
  axes; benches ring the plaza.

```
                      N
        ┌──────────[CHURCH]──────────┐
        │      ░forecourt░    [BANK] │
        │ [WAR GUILD]   ║      │     │
        │┌──────┐       ║      ├──[POTIONS]
        ││GUILD ╠═══════╬══════╪═[market sq]
        │└COURT ┘       ║      ├──[EQUIPMENT]
        │ [ROGUE GUILD] ║   (stalls)│
        │           (FOUNTAIN)      │
        │               ║           │
        │          (PORTAL DAIS)    │
        └───────────────────────────┘
                      S
```

## Coordinates

World units = pixels (project convention). North = −Y. Town rect: `(-800,-800)..(800,800)`
with boundary walls (OfflineArena pattern). Spawn: `(0, 128)` — south rim of the fountain.

### Paved ground (cobble over grass)

| Area | Geometry |
| --- | --- |
| Fountain Plaza | circle r 240 @ (0, 0) |
| Cathedral/Portal Way (N–S avenue) | rect x −56..56, y −576..656 |
| Guild Row / Market Street (E–W) | rect x −704..704, y −48..48 |
| Church forecourt | rect x −160..160, y −576..−400 |
| Guild Court | rect x −700..−420, y −200..200 |
| Market square | rect x 320..680, y −160..160 |
| Bank connector | rect x 264..376, y −256..−16 |
| Portal Dais | circle r 110 @ (0, 580) |

### Buildings (center, footprint w×h, door side)

| Building | Center | Size | Door |
| --- | --- | --- | --- |
| Church of the Dawn | (0, −688) | 320×224 | S |
| Bank of the Sanctuary | (320, −320) | 192×160 | S |
| Warriors' Guild | (−560, −256) | 224×176 | S |
| Mages' Guild | (−704, 0) | 176×176 | E |
| Rogues' Guild | (−560, 256) | 224×176 | N |
| Potion Vendor — "The Bubbling Flask" | (480, −224) | 144×128 | S |
| Equipment Vendor — "Hammer & Hilt" | (480, 224) | 160×128 | N |

Buildings are solid colliders (environment layer 8) with facade sprites; NPCs stand at
their entrances. Walk-in interiors are a follow-up.

### NPCs (StaticBody2D, interact prompt, dialog panel)

| NPC | Role | Position |
| --- | --- | --- |
| Father Aldric — High Priest | Priest: spend Glory, account skill tree (UI stub) | (0, −540) |
| Master Brandt | Warrior class trainer | (−560, −144) |
| Archmagus Elowen | Mage class trainer | (−608, 0) |
| Shade Vesper | Rogue class trainer | (−560, 144) |
| Tilda Brewbloom | Potion vendor | (480, −120) |
| Garrick Forgehand | Equipment vendor | (480, 120) |
| Goldwin Ledger | Bankmaster | (320, −208) |

### Landmarks & props

| Prop | Positions |
| --- | --- |
| Healing Fountain (collider r 64) | (0, 0) |
| Arena Portal | (0, 580) |
| Notice board | (160, −96) |
| Market stalls | (640, −64), (640, 64) |
| Benches | (±150, ±150) — 4, plaza ring |
| Lantern posts | (±88, −480), (±88, −280), (±88, 280), (±88, 460), (±288, ±88) |
| Trees | (−700,−700), (−340,−420), (−700,560), (−380,480), (600,−420), (700,−560), (640,420), (700,700), (−180,640), (200,680) |
| Flower beds | plaza ring + forecourt edges (table in `sanctuary.gd`) |

## Scene & script inventory

| File | What |
| --- | --- |
| `client/scenes/shared/sanctuary/sanctuary.tscn` | Town scene (root + script; layout is data-driven) |
| `client/scripts/shared/levels/sanctuary.gd` | OfflineArena subclass; builds ground, buildings, NPCs, props, portal from the tables above |
| `client/scenes/shared/portal/portal.tscn` + `client/scripts/shared/portal.gd` | Reusable scene-switch portal |
| `client/scenes/shared/npc/npc.tscn` + `client/scripts/shared/npc.gd` | Interactable service NPC (prompt + dialog panel) |

The eight questions: **client** runs everything (town is client-local); **server** runs
nothing until the Arena portal dials it; nothing is **predicted/replicated/persisted**
(Glory/skill-tree spend will go through the Go API when implemented — the priest dialog is
a stub); **validated**: portal refuses to enter Arena without a region URL or on failed
connect; **fails**: connect timeout shows on the portal prompt and resets; **tested**:
headless scene-load smoke + manual walkthrough.

## Sprite manifest (PixelLab)

Saved under `client/assets/sprites/environment/town/` and `.../npcs/`. Player sprite is
32 px — buildings sized per the table above; tiles 32 px.

- Ground tileset: grass↔cobblestone Wang corner set, 32 px, high top-down.
- Buildings ×7 (church, bank, 3 guild halls, 2 shops), high top-down facades.
- Fountain (128), Arena portal (96, animated shimmer), market stall, bench, lantern post,
  notice board, tree, flower beds.
- NPC characters ×7 (top-down, 32 px, style-guide palette), south-facing idle frames.
