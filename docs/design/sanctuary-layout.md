# Sanctuary Town Grid Layout — v1

## 0. Design Goal

The Sanctuary should feel like a dense, ruined medieval town, not a clean crossroads hub.

The town is a multiplayer safe lobby with:

- PvP disabled.
- Banks.
- Vendors.
- Equipment buying/selling.
- Glory/account progression.
- Player trading.
- NPC interaction.
- Arena portal.
- World exit portal.
- Social gathering spaces.
- Enterable buildings.

The layout is inspired by cramped medieval towns such as Visby, but darker: more Diablo / Tristram, less fairytale village.

Core feeling:

> A dying pilgrim city trapped behind old walls. Crooked alleys, black stone, dead gardens, ruined chapels, desperate trade, and a cursed fountain that still works for reasons nobody trusts.

---

# 1. Global Scale

## Tile size

```gdscript
const TILE := 32
```

## New town bounds

Old bounds:

```gdscript
Rect2(-1856.0, -1856.0, 3712.0, 3712.0)
```

New bounds:

```gdscript
const TOWN_RECT := Rect2(-3328.0, -3072.0, 6656.0, 6144.0)
```

Grid equivalent:

```gdscript
const GRID_MIN := Vector2i(-104, -96)
const GRID_MAX := Vector2i(104, 96)
```

This gives:

```text
Width:  208 tiles = 6656 px
Height: 192 tiles = 6144 px
```

## Coordinate convention

All layout tables use **grid coordinates** first.

World conversion:

```gdscript
func grid_to_world(cell: Vector2i) -> Vector2:
    return Vector2(cell.x * TILE, cell.y * TILE)

func grid_rect_to_world(rect: Rect2i) -> Rect2:
    return Rect2(
        rect.position.x * TILE,
        rect.position.y * TILE,
        rect.size.x * TILE,
        rect.size.y * TILE
    )
```

A building footprint like:

```gdscript
Rect2i(-12, -40, 24, 18)
```

means:

```text
x = -384 px
y = -1280 px
w = 768 px
h = 576 px
```

---

# 2. High-Level Town Shape

The town is not centered on the fountain.

The town is divided into dense districts:

| District                |             Grid Area | Purpose                                         |
| ----------------------- | --------------------: | ----------------------------------------------- |
| West Gate Refuge        | x -96..-58, y -24..18 | Spawn, social arrival, notice boards            |
| Priest Court            |  x -26..16, y -32..-4 | Fountain, civic landmark                        |
| Cathedral Ward          | x -38..24, y -82..-36 | Cathedral, priest, graveyard, cloister          |
| Tavern Row              | x -58..-24, y -20..12 | Social hub, inn/tavern                          |
| Merchant Bend           |    x 2..50, y -24..26 | Bank, blacksmith, potion shop, equipment vendor |
| Guild Backstreets       |   x -62..-6, y 12..54 | Warrior, rogue, training yards                  |
| Mage Quarter            |  x 42..82, y -54..-16 | Mage trainer, tower ruin, apothecary edge       |
| Lower Sanctum           |   x -26..62, y 36..80 | Arena portal, world gate, catacomb seal         |
| Ruined Residential Ring |            throughout | filler buildings, alleys, ruins                 |
| Rampart Margin          |            outer ring | walls, gates, towers, dead grass                |

---

# 3. New Key Positions

```gdscript
const SPAWN_POS := Vector2(-2496.0, -128.0)
const FOUNTAIN_POS := Vector2(-384.0, -640.0)
const FOUNTAIN_RADIUS := 64.0
const ARENA_PORTAL_POS := Vector2(1344.0, 1792.0)
const WORLD_GATE_POS := Vector2(-896.0, 2048.0)
```

Grid positions:

```gdscript
const SPAWN_CELL := Vector2i(-78, -4)
const FOUNTAIN_CELL := Vector2i(-12, -20)
const ARENA_PORTAL_CELL := Vector2i(42, 56)
const WORLD_GATE_CELL := Vector2i(-28, 64)
```

---

# 4. Decorative Rampart and Hard Boundary

The hard boundary remains invisible/functional through `OfflineArena`.

The visible town wall is inside the hard boundary.

## Rampart ring

```gdscript
const RAMPART_OUTER := Rect2i(-96, -88, 192, 176)
const RAMPART_INNER := Rect2i(-90, -82, 180, 164)
```

This creates a 6-tile-thick decorative defensive band.

## Rampart wall cells

Generate wall cells where:

```gdscript
cell inside RAMPART_OUTER and not inside RAMPART_INNER
```

Then carve gates and breaches.

## Main gates

### West Gate

```gdscript
GATE_WEST = Rect2i(-96, -10, 8, 14)
```

This is the main player arrival gate.

### East Postern Gate

```gdscript
GATE_EAST = Rect2i(88, -26, 8, 10)
```

A smaller smuggler / service gate.

### South World Gate Gap

```gdscript
GATE_SOUTH_WORLD = Rect2i(-36, 82, 18, 6)
```

This aligns with the World Gate descent.

### South Portal Service Breach

```gdscript
GATE_SOUTH_PORTAL = Rect2i(34, 82, 18, 6)
```

This visually supports the Arena Portal yard.

## Collapsed rampart breaches

These are visually broken, but mostly blocked by rubble colliders.

```gdscript
RAMPART_BREACHES = [
    Rect2i(-74, -88, 10, 6), # north-west collapsed wall
    Rect2i(58, -88, 12, 6),  # north-east broken crenelation
    Rect2i(-96, 48, 6, 14),  # west lower ruined section
    Rect2i(90, 38, 6, 18),   # east cracked section
]
```

Most breach cells should remain blocked by rubble props. Do not make all breaches walkable.

---

# 5. Road System

Roads are not straight avenues. They are stamped from weighted polylines.

Each road has:

- `points`: grid coordinates.
- `width`: tile radius/diameter approximation.
- `ground`: visual type.
- `priority`: higher priority overwrites mud/grass.

## Road stamping rule

For each segment between points:

1. Rasterize a thick line.
2. Width is measured in tiles.
3. Stamp a rough edge with deterministic noise.
4. Add cobble center and mud/ash shoulders.
5. Avoid perfectly clean borders.

Recommended road cell output:

- center: `cobble_dark`
- edge: `broken_cobble`
- outer edge: `mud_ash`

## Roads table

```gdscript
const ROADS := {
    "west_gate_to_priest_court": {
        "points": [
            Vector2i(-92, -4),
            Vector2i(-78, -4),
            Vector2i(-65, -6),
            Vector2i(-52, -9),
            Vector2i(-40, -13),
            Vector2i(-27, -17),
            Vector2i(-12, -20),
        ],
        "width": 7,
        "ground": "dark_cobble",
        "priority": 50,
    },

    "priest_court_to_cathedral": {
        "points": [
            Vector2i(-12, -20),
            Vector2i(-10, -29),
            Vector2i(-8, -38),
            Vector2i(-7, -48),
            Vector2i(-6, -58),
        ],
        "width": 6,
        "ground": "processional_cobble",
        "priority": 55,
    },

    "merchant_bend": {
        "points": [
            Vector2i(-12, -20),
            Vector2i(0, -18),
            Vector2i(12, -13),
            Vector2i(22, -6),
            Vector2i(26, 5),
            Vector2i(18, 15),
            Vector2i(4, 20),
        ],
        "width": 6,
        "ground": "market_cobble",
        "priority": 54,
    },

    "lower_sanctum_descent": {
        "points": [
            Vector2i(-12, -20),
            Vector2i(-10, -6),
            Vector2i(-4, 7),
            Vector2i(8, 22),
            Vector2i(24, 39),
            Vector2i(42, 56),
        ],
        "width": 6,
        "ground": "broken_cobble",
        "priority": 52,
    },

    "world_gate_descent": {
        "points": [
            Vector2i(-20, 3),
            Vector2i(-26, 18),
            Vector2i(-31, 35),
            Vector2i(-30, 51),
            Vector2i(-28, 64),
            Vector2i(-27, 83),
        ],
        "width": 5,
        "ground": "mud_cobble",
        "priority": 51,
    },

    "tavern_row": {
        "points": [
            Vector2i(-65, -6),
            Vector2i(-57, 2),
            Vector2i(-47, 5),
            Vector2i(-37, 3),
            Vector2i(-26, -2),
        ],
        "width": 5,
        "ground": "wet_cobble",
        "priority": 49,
    },

    "gallows_lane": {
        "points": [
            Vector2i(-48, 4),
            Vector2i(-43, 14),
            Vector2i(-37, 24),
            Vector2i(-29, 34),
            Vector2i(-18, 43),
        ],
        "width": 3,
        "ground": "narrow_mud_cobble",
        "priority": 56,
    },

    "blacksmith_cut": {
        "points": [
            Vector2i(-64, 10),
            Vector2i(-52, 16),
            Vector2i(-41, 21),
            Vector2i(-31, 20),
        ],
        "width": 4,
        "ground": "coal_cobble",
        "priority": 53,
    },

    "east_postern_path": {
        "points": [
            Vector2i(22, -6),
            Vector2i(36, -13),
            Vector2i(52, -19),
            Vector2i(69, -22),
            Vector2i(91, -21),
        ],
        "width": 4,
        "ground": "narrow_cobble",
        "priority": 48,
    },

    "mage_quarter_stair_lane": {
        "points": [
            Vector2i(36, -13),
            Vector2i(47, -24),
            Vector2i(58, -35),
            Vector2i(66, -45),
        ],
        "width": 4,
        "ground": "cold_cobble",
        "priority": 50,
    },

    "cathedral_cloister_walk": {
        "points": [
            Vector2i(-8, -48),
            Vector2i(-22, -51),
            Vector2i(-36, -56),
            Vector2i(-48, -62),
        ],
        "width": 4,
        "ground": "old_stone",
        "priority": 48,
    },

    "graveyard_walk": {
        "points": [
            Vector2i(-6, -58),
            Vector2i(11, -60),
            Vector2i(28, -63),
            Vector2i(42, -68),
        ],
        "width": 3,
        "ground": "grave_stone_path",
        "priority": 48,
    }
}
```

---

# 6. Plazas and Open Spaces

Plazas are irregular polygons or rough rects, not circles.

## Priest Court / Fountain Plaza

```gdscript
const PRIEST_COURT_POLY := [
    Vector2i(-28, -28),
    Vector2i(-14, -34),
    Vector2i(5, -31),
    Vector2i(16, -22),
    Vector2i(11, -9),
    Vector2i(-5, -5),
    Vector2i(-24, -10),
    Vector2i(-33, -19),
]
```

Ground:

- `dark_civic_cobble`
- cracked edges
- blood-brown stains
- bone-white candle clusters
- soul-teal fountain glow

## West Gate Refuge Yard

```gdscript
const WEST_GATE_YARD := Rect2i(-91, -16, 33, 26)
```

Ground:

- mud
- broken cobble
- ash grass
- refugee tent footprints

## Merchant Bend Plaza

```gdscript
const MERCHANT_BEND_POLY := [
    Vector2i(3, -13),
    Vector2i(23, -16),
    Vector2i(39, -5),
    Vector2i(37, 14),
    Vector2i(20, 26),
    Vector2i(2, 21),
    Vector2i(-2, 4),
]
```

## Lower Sanctum Portal Yard

```gdscript
const PORTAL_YARD_POLY := [
    Vector2i(23, 42),
    Vector2i(48, 38),
    Vector2i(64, 52),
    Vector2i(61, 72),
    Vector2i(40, 80),
    Vector2i(20, 69),
]
```

## World Gate Killing Ground

```gdscript
const WORLD_GATE_YARD := Rect2i(-43, 52, 31, 30)
```

## Cathedral Forecourt

```gdscript
const CATHEDRAL_FORECOURT := [
    Vector2i(-24, -58),
    Vector2i(12, -59),
    Vector2i(20, -49),
    Vector2i(8, -40),
    Vector2i(-17, -41),
    Vector2i(-29, -50),
]
```

---

# 7. Enterable Building Rules

All primary service buildings are enterable.

A building is generated from:

- footprint rect
- perimeter wall cells
- door gap
- interior floor cells
- interior furniture
- NPC positions
- optional external props

## Wall rule for buildings

For each building footprint:

```text
Wall cells are the perimeter cells of the footprint.
Interior cells are footprint inset by 1 tile.
Door cells are removed from the perimeter.
```

## Recommended minimum sizes

| Building Type     | Minimum Grid Size | Notes                          |
| ----------------- | ----------------: | ------------------------------ |
| Tiny filler house |             7 × 7 | may be locked                  |
| Shop              |            10 × 9 | enough for counter and shelves |
| Tavern            |           16 × 13 | multiplayer interior           |
| Bank              |           14 × 12 | counter, vault, queue          |
| Guild             |           16 × 13 | trainer + props                |
| Cathedral         |           30 × 22 | major landmark                 |
| Portal hall/yard  |           outdoor | use props/colliders            |

## Door size

| Door Type      |      Width |
| -------------- | ---------: |
| Cottage door   |    2 tiles |
| Shop door      |    3 tiles |
| Tavern door    |    4 tiles |
| Cathedral door |    5 tiles |
| Gate           | 8–18 tiles |

---

# 8. Primary Buildings

## Building table

```gdscript
const BUILDINGS := {
    "cathedral_of_ash": {
        "name": "Cathedral of Ash",
        "rect": Rect2i(-22, -78, 36, 24),
        "door_side": "S",
        "door_center": -4,
        "door_width": 5,
        "height_px": 48,
        "floor": "cold_cathedral_stone",
        "district": "cathedral_ward",
        "enterable": true,
        "replace_with": "cathedral_black_gothic_enterable",
    },

    "last_lantern_tavern": {
        "name": "The Last Lantern",
        "rect": Rect2i(-52, -9, 17, 14),
        "door_side": "E",
        "door_center": -2,
        "door_width": 4,
        "height_px": 32,
        "floor": "dark_wood",
        "district": "tavern_row",
        "enterable": true,
        "replace_with": "grim_tavern_enterable",
    },

    "ledger_house_bank": {
        "name": "Ledger House",
        "rect": Rect2i(8, 9, 16, 13),
        "door_side": "S",
        "door_center": 15,
        "door_width": 3,
        "height_px": 34,
        "floor": "dark_stone",
        "district": "merchant_bend",
        "enterable": true,
        "replace_with": "fortified_bank_counting_house",
    },

    "hammer_and_hilt": {
        "name": "Hammer & Hilt",
        "rect": Rect2i(-55, 14, 17, 13),
        "door_side": "N",
        "door_center": -47,
        "door_width": 3,
        "height_px": 30,
        "floor": "coal_stone",
        "district": "guild_backstreets",
        "enterable": true,
        "replace_with": "blacksmith_corner_forge",
    },

    "bubbling_flask": {
        "name": "The Bubbling Flask",
        "rect": Rect2i(31, -8, 13, 11),
        "door_side": "W",
        "door_center": -3,
        "door_width": 3,
        "height_px": 30,
        "floor": "stained_wood",
        "district": "merchant_bend",
        "enterable": true,
        "replace_with": "apothecary_leaning_house",
    },

    "equipment_exchange": {
        "name": "The Iron Reliquary",
        "rect": Rect2i(28, 11, 15, 12),
        "door_side": "W",
        "door_center": 17,
        "door_width": 3,
        "height_px": 32,
        "floor": "dark_wood",
        "district": "merchant_bend",
        "enterable": true,
        "replace_with": "equipment_vendor_reliquary",
    },

    "old_barracks": {
        "name": "Old Barracks",
        "rect": Rect2i(-72, 17, 19, 14),
        "door_side": "E",
        "door_center": 24,
        "door_width": 4,
        "height_px": 32,
        "floor": "worn_training_stone",
        "district": "guild_backstreets",
        "enterable": true,
        "replace_with": "ruined_barracks_training_hall",
    },

    "gallows_den": {
        "name": "Gallows Den",
        "rect": Rect2i(-31, 35, 14, 12),
        "door_side": "S",
        "door_center": -24,
        "door_width": 2,
        "height_px": 28,
        "floor": "dark_wood",
        "district": "guild_backstreets",
        "enterable": true,
        "replace_with": "hidden_rogue_den_backstreet",
    },

    "cracked_observatory": {
        "name": "The Cracked Observatory",
        "rect": Rect2i(59, -49, 16, 18),
        "door_side": "W",
        "door_center": -39,
        "door_width": 3,
        "height_px": 40,
        "floor": "cold_stone",
        "district": "mage_quarter",
        "enterable": true,
        "replace_with": "collapsed_mage_tower",
    },

    "pilgrim_storehouse": {
        "name": "Pilgrim Storehouse",
        "rect": Rect2i(-82, -29, 13, 11),
        "door_side": "S",
        "door_center": -76,
        "door_width": 3,
        "height_px": 28,
        "floor": "rough_wood",
        "district": "west_gate_refuge",
        "enterable": true,
        "replace_with": "storage_and_trade_house",
    },

    "corpse_washer": {
        "name": "Corpse Washer's House",
        "rect": Rect2i(-77, 42, 12, 11),
        "door_side": "E",
        "door_center": 47,
        "door_width": 2,
        "height_px": 26,
        "floor": "stained_stone",
        "district": "plague_green",
        "enterable": true,
        "replace_with": "corpse_washer_house",
    }
}
```

---

# 9. Filler Buildings

Filler buildings make the town feel real.

Not every filler building needs an NPC or gameplay function. Some are locked, collapsed, decorative, or future content.

## Filler building rules

- Use the same perimeter wall generator.
- `enterable = false` means door is visual only and blocked.
- `ruined = true` means some wall cells are removed visually but rubble colliders remain.
- Filler buildings should create narrow alleys.
- Avoid large empty areas.

```gdscript
const FILLER_BUILDINGS := {
    "locked_home_west_01": {
        "rect": Rect2i(-70, -19, 10, 9),
        "door_side": "S",
        "door_center": -65,
        "door_width": 2,
        "enterable": false,
        "kind": "locked_home",
    },

    "burned_home_west_02": {
        "rect": Rect2i(-62, -28, 9, 8),
        "door_side": "E",
        "door_center": -24,
        "door_width": 2,
        "enterable": false,
        "kind": "burned_home",
        "ruined": true,
    },

    "leaning_house_tavern_01": {
        "rect": Rect2i(-35, -20, 9, 10),
        "door_side": "W",
        "door_center": -15,
        "door_width": 2,
        "enterable": false,
        "kind": "leaning_house",
    },

    "scriptorium_ruin": {
        "rect": Rect2i(0, -46, 12, 10),
        "door_side": "S",
        "door_center": 6,
        "door_width": 3,
        "enterable": false,
        "kind": "scriptorium_ruin",
        "ruined": true,
    },

    "candle_maker": {
        "rect": Rect2i(-31, -42, 10, 9),
        "door_side": "S",
        "door_center": -26,
        "door_width": 2,
        "enterable": false,
        "kind": "candle_maker",
    },

    "grave_keeper_house": {
        "rect": Rect2i(20, -72, 11, 10),
        "door_side": "W",
        "door_center": -67,
        "door_width": 2,
        "enterable": false,
        "kind": "grave_keeper_house",
    },

    "ossuary_chapel": {
        "rect": Rect2i(36, -75, 12, 13),
        "door_side": "S",
        "door_center": 42,
        "door_width": 3,
        "enterable": false,
        "kind": "ossuary_chapel",
        "ruined": true,
    },

    "east_locked_home_01": {
        "rect": Rect2i(45, -26, 10, 9),
        "door_side": "S",
        "door_center": 50,
        "door_width": 2,
        "enterable": false,
        "kind": "locked_home",
    },

    "east_locked_home_02": {
        "rect": Rect2i(51, -13, 9, 8),
        "door_side": "W",
        "door_center": -9,
        "door_width": 2,
        "enterable": false,
        "kind": "locked_home",
    },

    "market_warehouse": {
        "rect": Rect2i(45, 9, 13, 12),
        "door_side": "W",
        "door_center": 15,
        "door_width": 3,
        "enterable": false,
        "kind": "warehouse",
    },

    "butcher_ruin": {
        "rect": Rect2i(13, -31, 10, 9),
        "door_side": "S",
        "door_center": 18,
        "door_width": 2,
        "enterable": false,
        "kind": "butcher_ruin",
        "ruined": true,
    },

    "plague_house_01": {
        "rect": Rect2i(-56, 42, 10, 10),
        "door_side": "N",
        "door_center": -51,
        "door_width": 2,
        "enterable": false,
        "kind": "plague_house",
    },

    "plague_house_02": {
        "rect": Rect2i(-44, 51, 9, 9),
        "door_side": "E",
        "door_center": 55,
        "door_width": 2,
        "enterable": false,
        "kind": "plague_house",
    },

    "collapsed_home_lower_01": {
        "rect": Rect2i(-5, 47, 11, 9),
        "door_side": "W",
        "door_center": 51,
        "door_width": 2,
        "enterable": false,
        "kind": "collapsed_home",
        "ruined": true,
    },

    "lower_storehouse_01": {
        "rect": Rect2i(8, 55, 12, 10),
        "door_side": "S",
        "door_center": 14,
        "door_width": 2,
        "enterable": false,
        "kind": "lower_storehouse",
    },

    "portal_caretaker_house": {
        "rect": Rect2i(59, 40, 12, 11),
        "door_side": "W",
        "door_center": 45,
        "door_width": 2,
        "enterable": false,
        "kind": "caretaker_house",
    },

    "south_burned_row_01": {
        "rect": Rect2i(24, 70, 9, 8),
        "door_side": "N",
        "door_center": 29,
        "door_width": 2,
        "enterable": false,
        "kind": "burned_home",
        "ruined": true,
    },

    "south_burned_row_02": {
        "rect": Rect2i(36, 73, 9, 8),
        "door_side": "N",
        "door_center": 40,
        "door_width": 2,
        "enterable": false,
        "kind": "burned_home",
        "ruined": true,
    },

    "refugee_shed_01": {
        "rect": Rect2i(-89, 10, 8, 7),
        "door_side": "E",
        "door_center": 13,
        "door_width": 2,
        "enterable": false,
        "kind": "shed",
    },

    "refugee_shed_02": {
        "rect": Rect2i(-88, -26, 8, 7),
        "door_side": "E",
        "door_center": -23,
        "door_width": 2,
        "enterable": false,
        "kind": "shed",
    }
}
```

---

# 10. Interior Layouts

Interior coordinates are local to building rect.

Local coordinate:

```text
local_x = grid_x - rect.position.x
local_y = grid_y - rect.position.y
```

## Cathedral Interior

Building:

```gdscript
Rect2i(-22, -78, 36, 24)
```

Interior is:

```gdscript
Rect2i(-21, -77, 34, 22)
```

Furniture and interior props:

```gdscript
INTERIORS["cathedral_of_ash"] = [
    {"kind": "altar", "local": Rect2i(15, 3, 6, 3), "solid": true},
    {"kind": "glory_shrine", "local": Rect2i(16, 1, 4, 2), "solid": true},
    {"kind": "pew_left_01", "local": Rect2i(7, 10, 7, 2), "solid": true},
    {"kind": "pew_right_01", "local": Rect2i(22, 10, 7, 2), "solid": true},
    {"kind": "pew_left_02", "local": Rect2i(7, 14, 7, 2), "solid": true},
    {"kind": "pew_right_02", "local": Rect2i(22, 14, 7, 2), "solid": true},
    {"kind": "candle_cluster", "local": Rect2i(4, 5, 2, 2), "solid": false},
    {"kind": "candle_cluster", "local": Rect2i(30, 5, 2, 2), "solid": false},
    {"kind": "broken_statue", "local": Rect2i(2, 17, 3, 3), "solid": true},
    {"kind": "confession_cell", "local": Rect2i(30, 17, 4, 4), "solid": true},
]
```

NPC:

```gdscript
Father Aldric: grid Vector2i(-4, -72)
```

## Tavern Interior

Building:

```gdscript
Rect2i(-52, -9, 17, 14)
```

Interior props:

```gdscript
INTERIORS["last_lantern_tavern"] = [
    {"kind": "bar_counter", "local": Rect2i(2, 2, 3, 8), "solid": true},
    {"kind": "fireplace", "local": Rect2i(7, 1, 4, 2), "solid": true},
    {"kind": "table", "local": Rect2i(7, 5, 3, 3), "solid": true},
    {"kind": "table", "local": Rect2i(12, 7, 3, 3), "solid": true},
    {"kind": "barrels", "local": Rect2i(2, 10, 3, 2), "solid": true},
    {"kind": "notice_wall", "local": Rect2i(12, 1, 3, 1), "solid": false},
]
```

NPC:

```gdscript
Innkeeper / Rumor Broker: grid Vector2i(-49, -4)
```

## Bank Interior

```gdscript
INTERIORS["ledger_house_bank"] = [
    {"kind": "bank_counter", "local": Rect2i(2, 3, 12, 2), "solid": true},
    {"kind": "vault_door", "local": Rect2i(11, 1, 3, 2), "solid": true},
    {"kind": "ledger_table", "local": Rect2i(4, 7, 4, 3), "solid": true},
    {"kind": "lockbox_stack", "local": Rect2i(10, 7, 3, 3), "solid": true},
]
```

NPC:

```gdscript
Goldwin Ledger: grid Vector2i(15, 14)
```

## Blacksmith Interior

```gdscript
INTERIORS["hammer_and_hilt"] = [
    {"kind": "forge", "local": Rect2i(2, 2, 4, 4), "solid": true},
    {"kind": "anvil", "local": Rect2i(7, 5, 2, 2), "solid": true},
    {"kind": "weapon_rack", "local": Rect2i(12, 2, 3, 2), "solid": true},
    {"kind": "armor_stand", "local": Rect2i(12, 7, 3, 3), "solid": true},
    {"kind": "coal_pile", "local": Rect2i(3, 9, 3, 2), "solid": true},
]
```

NPC:

```gdscript
Garrick Forgehand: grid Vector2i(-47, 20)
```

## Potion Shop Interior

```gdscript
INTERIORS["bubbling_flask"] = [
    {"kind": "vendor_counter", "local": Rect2i(2, 2, 2, 7), "solid": true},
    {"kind": "shelf_potions", "local": Rect2i(6, 1, 5, 2), "solid": true},
    {"kind": "shelf_potions", "local": Rect2i(6, 8, 5, 2), "solid": true},
    {"kind": "cauldron", "local": Rect2i(7, 4, 3, 3), "solid": true},
]
```

NPC:

```gdscript
Tilda Brewbloom: grid Vector2i(35, -3)
```

## Equipment Vendor Interior

```gdscript
INTERIORS["equipment_exchange"] = [
    {"kind": "counter", "local": Rect2i(2, 2, 2, 8), "solid": true},
    {"kind": "armor_rack", "local": Rect2i(7, 2, 3, 3), "solid": true},
    {"kind": "weapon_rack", "local": Rect2i(11, 2, 3, 3), "solid": true},
    {"kind": "chest", "local": Rect2i(8, 8, 2, 2), "solid": true},
]
```

NPC:

```gdscript
Equipment Vendor: grid Vector2i(32, 17)
```

## Old Barracks Interior

```gdscript
INTERIORS["old_barracks"] = [
    {"kind": "training_dummy", "local": Rect2i(4, 4, 2, 2), "solid": true},
    {"kind": "training_dummy", "local": Rect2i(8, 4, 2, 2), "solid": true},
    {"kind": "weapon_rack", "local": Rect2i(13, 2, 4, 2), "solid": true},
    {"kind": "broken_table", "local": Rect2i(4, 9, 4, 2), "solid": true},
    {"kind": "armor_pile", "local": Rect2i(13, 9, 3, 3), "solid": true},
]
```

NPC:

```gdscript
Master Brandt: grid Vector2i(-61, 24)
```

## Rogue Den Interior

```gdscript
INTERIORS["gallows_den"] = [
    {"kind": "knife_table", "local": Rect2i(4, 3, 4, 2), "solid": true},
    {"kind": "hidden_chest", "local": Rect2i(10, 2, 2, 2), "solid": true},
    {"kind": "map_wall", "local": Rect2i(3, 1, 5, 1), "solid": false},
    {"kind": "sleeping_roll", "local": Rect2i(9, 7, 3, 2), "solid": false},
]
```

NPC:

```gdscript
Shade Vesper: grid Vector2i(-24, 42)
```

## Mage Observatory Interior

```gdscript
INTERIORS["cracked_observatory"] = [
    {"kind": "void_crack", "local": Rect2i(7, 5, 3, 3), "solid": false},
    {"kind": "bookcase", "local": Rect2i(2, 2, 3, 8), "solid": true},
    {"kind": "broken_telescope", "local": Rect2i(8, 2, 5, 3), "solid": true},
    {"kind": "ritual_table", "local": Rect2i(8, 10, 4, 3), "solid": true},
    {"kind": "floating_stones", "local": Rect2i(12, 7, 2, 2), "solid": false},
]
```

NPC:

```gdscript
Archmagus Elowen: grid Vector2i(67, -40)
```

---

# 11. NPC Table

```gdscript
const NPCS := {
    "father_aldric": {
        "name": "Father Aldric",
        "role": "Glory / account progression",
        "pos": Vector2i(-4, -72),
        "building": "cathedral_of_ash",
        "sprite": "assets/sprites/npcs/father_aldric.png",
    },

    "master_brandt": {
        "name": "Master Brandt",
        "role": "Warrior trainer",
        "pos": Vector2i(-61, 24),
        "building": "old_barracks",
        "sprite": "assets/sprites/npcs/master_brandt.png",
    },

    "archmagus_elowen": {
        "name": "Archmagus Elowen",
        "role": "Mage trainer",
        "pos": Vector2i(67, -40),
        "building": "cracked_observatory",
        "sprite": "assets/sprites/npcs/archmagus_elowen.png",
    },

    "shade_vesper": {
        "name": "Shade Vesper",
        "role": "Rogue trainer",
        "pos": Vector2i(-24, 42),
        "building": "gallows_den",
        "sprite": "assets/sprites/npcs/shade_vesper.png",
    },

    "tilda_brewbloom": {
        "name": "Tilda Brewbloom",
        "role": "Potion vendor",
        "pos": Vector2i(35, -3),
        "building": "bubbling_flask",
        "sprite": "assets/sprites/npcs/tilda_brewbloom.png",
    },

    "garrick_forgehand": {
        "name": "Garrick Forgehand",
        "role": "Equipment crafting / blacksmith",
        "pos": Vector2i(-47, 20),
        "building": "hammer_and_hilt",
        "sprite": "assets/sprites/npcs/garrick_forgehand.png",
    },

    "goldwin_ledger": {
        "name": "Goldwin Ledger",
        "role": "Bankmaster",
        "pos": Vector2i(15, 14),
        "building": "ledger_house_bank",
        "sprite": "assets/sprites/npcs/goldwin_ledger.png",
    },

    "portal_warden": {
        "name": "The Portal Warden",
        "role": "Arena / World portal explanation",
        "pos": Vector2i(35, 54),
        "building": "",
        "sprite": "assets/sprites/npcs/portal_warden.png",
    },

    "innkeeper": {
        "name": "Marta Voss",
        "role": "Innkeeper / rumors",
        "pos": Vector2i(-49, -4),
        "building": "last_lantern_tavern",
        "sprite": "assets/sprites/npcs/innkeeper.png",
    },

    "corpse_collector": {
        "name": "Oren Gravesack",
        "role": "Flavor NPC / death lore",
        "pos": Vector2i(-78, 46),
        "building": "",
        "sprite": "assets/sprites/npcs/corpse_collector.png",
    }
}
```

---

# 12. Portals

## Arena Portal

```gdscript
const PORTALS := {
    "arena_portal": {
        "name": "Arena Portal",
        "pos": Vector2i(42, 56),
        "requires_connection": true,
        "destination": "arena",
        "region_url_source": "GameManager.player_data.selected_region_url",
        "visual_radius": 4,
        "interaction_radius": 3,
        "replace_with": "town/portal_idle_sheet.png",
    },

    "world_gate": {
        "name": "World Gate",
        "pos": Vector2i(-28, 64),
        "requires_connection": true,
        "destination": "world",
        "region_url_source": "GameManager.player_data.selected_region_url",
        "visual_radius": 5,
        "interaction_radius": 4,
        "replace_with": "world_gate_mist_exit",
    }
}
```

## Arena Portal props

```gdscript
PORTAL_PROPS = [
    {"kind": "obelisk", "pos": Vector2i(34, 50), "solid": true},
    {"kind": "obelisk", "pos": Vector2i(50, 50), "solid": true},
    {"kind": "obelisk", "pos": Vector2i(34, 64), "solid": true},
    {"kind": "obelisk", "pos": Vector2i(50, 64), "solid": true},
    {"kind": "chain_post", "pos": Vector2i(38, 48), "solid": true},
    {"kind": "chain_post", "pos": Vector2i(46, 48), "solid": true},
    {"kind": "kneeling_statue", "pos": Vector2i(42, 66), "solid": true},
    {"kind": "ritual_circle", "pos": Vector2i(42, 56), "solid": false},
]
```

## World Gate props

```gdscript
WORLD_GATE_PROPS = [
    {"kind": "broken_portcullis", "pos": Vector2i(-28, 77), "solid": true},
    {"kind": "warning_sign", "pos": Vector2i(-34, 60), "solid": true},
    {"kind": "corpse_cart", "pos": Vector2i(-22, 58), "solid": true},
    {"kind": "ash_brazier", "pos": Vector2i(-35, 66), "solid": true},
    {"kind": "ash_brazier", "pos": Vector2i(-21, 66), "solid": true},
]
```

---

# 13. Landmarks

```gdscript
const LANDMARKS := {
    "cursed_fountain": {
        "pos": Vector2i(-12, -20),
        "radius_tiles": 2,
        "collider_radius_px": 64,
        "replace_with": "town/fountain_idle_sheet.png",
        "glow": "soul_teal",
    },

    "dead_cloister": {
        "rect": Rect2i(-54, -68, 22, 20),
        "kind": "ruined_garden",
        "solid_edges": true,
    },

    "ossuary_yard": {
        "rect": Rect2i(18, -80, 34, 22),
        "kind": "graveyard_ossuary",
        "solid_edges": false,
    },

    "plague_green": {
        "rect": Rect2i(-82, 36, 31, 28),
        "kind": "muddy_ruin_park",
        "solid_edges": false,
    },

    "gallows_square": {
        "rect": Rect2i(-39, 28, 18, 12),
        "kind": "execution_corner",
        "solid_edges": false,
    },

    "broken_arcade_trade": {
        "rect": Rect2i(3, 25, 24, 8),
        "kind": "player_trade_arcade",
        "solid_edges": true,
    },

    "catacomb_seal": {
        "pos": Vector2i(8, 52),
        "radius_tiles": 3,
        "kind": "sealed_stairs",
        "solid": true,
    }
}
```

---

# 14. Outdoor Prop Placement

Props are exact grid placements.

## West Gate Refuge props

```gdscript
const PROPS_WEST_GATE := [
    {"kind": "refugee_tent", "pos": Vector2i(-84, -13), "solid": true},
    {"kind": "refugee_tent", "pos": Vector2i(-75, -14), "solid": true},
    {"kind": "refugee_tent", "pos": Vector2i(-86, 7), "solid": true},
    {"kind": "broken_cart", "pos": Vector2i(-71, 5), "solid": true},
    {"kind": "notice_board", "pos": Vector2i(-65, -1), "solid": true},
    {"kind": "trade_board", "pos": Vector2i(-63, 3), "solid": true},
    {"kind": "barrel_stack", "pos": Vector2i(-80, 11), "solid": true},
    {"kind": "dead_campfire", "pos": Vector2i(-76, -3), "solid": false},
    {"kind": "hanging_lantern_post", "pos": Vector2i(-69, -8), "solid": true},
    {"kind": "hanging_lantern_post", "pos": Vector2i(-69, 8), "solid": true},
]
```

## Priest Court props

```gdscript
const PROPS_PRIEST_COURT := [
    {"kind": "broken_statue", "pos": Vector2i(-18, -28), "solid": true},
    {"kind": "candle_cluster", "pos": Vector2i(-15, -23), "solid": false},
    {"kind": "candle_cluster", "pos": Vector2i(-8, -17), "solid": false},
    {"kind": "prayer_strip_wall", "pos": Vector2i(6, -27), "solid": false},
    {"kind": "dead_tree_small", "pos": Vector2i(5, -12), "solid": true},
    {"kind": "broken_bench", "pos": Vector2i(-24, -16), "solid": true},
    {"kind": "broken_bench", "pos": Vector2i(6, -23), "solid": true},
    {"kind": "skull_reliquary", "pos": Vector2i(-4, -29), "solid": true},
]
```

## Cathedral Ward props

```gdscript
const PROPS_CATHEDRAL := [
    {"kind": "grave_marker", "pos": Vector2i(24, -68), "solid": true},
    {"kind": "grave_marker", "pos": Vector2i(29, -70), "solid": true},
    {"kind": "grave_marker", "pos": Vector2i(35, -67), "solid": true},
    {"kind": "grave_marker", "pos": Vector2i(42, -72), "solid": true},
    {"kind": "mausoleum", "pos": Vector2i(45, -63), "solid": true},
    {"kind": "dead_tree_large", "pos": Vector2i(32, -61), "solid": true},
    {"kind": "bone_wall", "pos": Vector2i(20, -76), "solid": true},
    {"kind": "broken_arcade", "pos": Vector2i(-46, -61), "solid": true},
    {"kind": "dry_well", "pos": Vector2i(-39, -55), "solid": true},
    {"kind": "cloister_dead_tree", "pos": Vector2i(-51, -52), "solid": true},
]
```

## Tavern Row props

```gdscript
const PROPS_TAVERN_ROW := [
    {"kind": "tavern_sign", "pos": Vector2i(-35, -4), "solid": false},
    {"kind": "barrel_stack", "pos": Vector2i(-42, 6), "solid": true},
    {"kind": "vomit_stain", "pos": Vector2i(-45, 3), "solid": false},
    {"kind": "wanted_posters", "pos": Vector2i(-36, -12), "solid": false},
    {"kind": "lantern_post", "pos": Vector2i(-41, -6), "solid": true},
    {"kind": "beggar_bedroll", "pos": Vector2i(-31, 2), "solid": false},
]
```

## Merchant Bend props

```gdscript
const PROPS_MERCHANT := [
    {"kind": "market_stall", "pos": Vector2i(7, -8), "solid": true},
    {"kind": "market_stall", "pos": Vector2i(17, -10), "solid": true},
    {"kind": "market_stall", "pos": Vector2i(25, 0), "solid": true},
    {"kind": "hanging_cage", "pos": Vector2i(31, 6), "solid": true},
    {"kind": "coin_scale_table", "pos": Vector2i(5, 12), "solid": true},
    {"kind": "lockbox_stack", "pos": Vector2i(25, 19), "solid": true},
    {"kind": "forge_smoke_stack", "pos": Vector2i(-43, 13), "solid": true},
    {"kind": "coal_cart", "pos": Vector2i(-39, 27), "solid": true},
    {"kind": "weapon_display", "pos": Vector2i(-51, 13), "solid": true},
]
```

## Guild Backstreet props

```gdscript
const PROPS_GUILD_BACKSTREETS := [
    {"kind": "training_dummy", "pos": Vector2i(-67, 33), "solid": true},
    {"kind": "training_dummy", "pos": Vector2i(-61, 35), "solid": true},
    {"kind": "blood_sand_patch", "pos": Vector2i(-64, 31), "solid": false},
    {"kind": "gallows", "pos": Vector2i(-32, 32), "solid": true},
    {"kind": "sewer_grate", "pos": Vector2i(-24, 34), "solid": false},
    {"kind": "hanging_cloth", "pos": Vector2i(-20, 39), "solid": false},
    {"kind": "knife_marks_wall", "pos": Vector2i(-18, 35), "solid": false},
]
```

## Mage Quarter props

```gdscript
const PROPS_MAGE_QUARTER := [
    {"kind": "void_crack_ground", "pos": Vector2i(56, -34), "solid": false},
    {"kind": "floating_stone", "pos": Vector2i(62, -29), "solid": false},
    {"kind": "broken_telescope_large", "pos": Vector2i(75, -52), "solid": true},
    {"kind": "blue_brazier", "pos": Vector2i(55, -45), "solid": true},
    {"kind": "blue_brazier", "pos": Vector2i(76, -35), "solid": true},
    {"kind": "forbidden_books_crate", "pos": Vector2i(51, -28), "solid": true},
]
```

## Lower Sanctum props

```gdscript
const PROPS_LOWER_SANCTUM := [
    {"kind": "catacomb_seal", "pos": Vector2i(8, 52), "solid": true},
    {"kind": "warning_bell", "pos": Vector2i(18, 42), "solid": true},
    {"kind": "kneeling_statue", "pos": Vector2i(30, 60), "solid": true},
    {"kind": "kneeling_statue", "pos": Vector2i(54, 60), "solid": true},
    {"kind": "ash_pile", "pos": Vector2i(22, 69), "solid": false},
    {"kind": "ritual_blood_stain", "pos": Vector2i(42, 57), "solid": false},
]
```

---

# 15. Stairs and Elevation Placeholders

Still use one gameplay Z-level for now.

Stairs are walkable ground tiles with visual rise.

```gdscript
const STAIRS := {
    "cathedral_saints_steps": {
        "rects": [
            Rect2i(-13, -54, 14, 2),
            Rect2i(-12, -52, 13, 2),
            Rect2i(-11, -50, 12, 2),
        ],
        "walkable": true,
        "future": "elevation/floor-switch",
    },

    "mage_quarter_steps": {
        "rects": [
            Rect2i(55, -31, 8, 2),
            Rect2i(56, -33, 8, 2),
        ],
        "walkable": true,
        "future": "elevation/floor-switch",
    },

    "lower_sanctum_steps": {
        "rects": [
            Rect2i(22, 39, 12, 2),
            Rect2i(24, 41, 12, 2),
            Rect2i(26, 43, 12, 2),
        ],
        "walkable": true,
        "future": "elevation/floor-switch",
    },

    "world_gate_descent_steps": {
        "rects": [
            Rect2i(-32, 58, 9, 2),
            Rect2i(-33, 60, 10, 2),
            Rect2i(-34, 62, 11, 2),
        ],
        "walkable": true,
        "future": "elevation/floor-switch",
    }
}
```

---

# 16. Collision Rules

## Collision layers

```gdscript
const ENVIRONMENT_COLLISION_LAYER := 8
```

## Solid sources

The following produce colliders:

- rampart wall cells
- building wall cells
- solid furniture
- solid props
- solid landmark objects
- rubble piles
- locked doors
- portal obelisks
- fountain collider

## Non-solid sources

The following do not produce colliders:

- roads
- stains
- decals
- candles
- small cloth
- prayer strips
- glow effects
- shallow water
- walkable stairs

## Greedy collider merge

Use greedy row merging for tile solids.

Recommended:

1. Create boolean solid grid.
2. Merge horizontal runs.
3. Optionally merge vertical rectangles after row pass.
4. Create `CollisionShape2D` rectangles.

## Door gaps

Door cells must not be solid unless the building is non-enterable.

For non-enterable filler buildings:

- keep visual door
- add invisible locked-door collider at the door gap

---

# 17. Wall Generation

## Building perimeter generation

```gdscript
func add_building_walls(rect: Rect2i, door_side: String, door_center: int, door_width: int, enterable: bool) -> void:
    for x in range(rect.position.x, rect.position.x + rect.size.x):
        add_wall_if_not_door(Vector2i(x, rect.position.y), rect, door_side, door_center, door_width, enterable)
        add_wall_if_not_door(Vector2i(x, rect.position.y + rect.size.y - 1), rect, door_side, door_center, door_width, enterable)

    for y in range(rect.position.y, rect.position.y + rect.size.y):
        add_wall_if_not_door(Vector2i(rect.position.x, y), rect, door_side, door_center, door_width, enterable)
        add_wall_if_not_door(Vector2i(rect.position.x + rect.size.x - 1, y), rect, door_side, door_center, door_width, enterable)
```

## Door interpretation

For north/south doors:

- `door_center` is grid x.

For east/west doors:

- `door_center` is grid y.

Door span:

```gdscript
var half := door_width / 2
```

Remove cells from:

```text
door_center - half through door_center + half
```

For even widths, bias one tile to the right/down.

---

# 18. Spawn Rules

Spawn should not be a single point if the town is multiplayer.

```gdscript
const SPAWN_POINTS := [
    Vector2i(-78, -4),
    Vector2i(-80, -7),
    Vector2i(-76, -1),
    Vector2i(-73, -5),
    Vector2i(-82, 2),
    Vector2i(-74, 4),
    Vector2i(-85, -2),
    Vector2i(-71, -9),
]
```

World conversion:

```gdscript
spawn_world = grid_to_world(SPAWN_POINTS.pick_random())
```

Spawn area should be clear of props.

Minimum free radius:

- 3 tiles around each spawn.

---

# 19. Player Navigation Widths

Minimum widths:

| Space                       |    Minimum Width |
| --------------------------- | ---------------: |
| Major road                  |        6–7 tiles |
| Market road                 |        5–6 tiles |
| Alley                       |          3 tiles |
| Secret-feeling alley        |  2 tiles, rarely |
| Building doorway            |        2–5 tiles |
| Multiplayer gathering plaza | 18+ tiles across |
| Portal interaction area     | 10+ tiles across |

Avoid 1-tile alleys. They will feel bad in multiplayer.

---

# 20. Visual Density Targets

Approximate target counts:

| Thing                       |  Count |
| --------------------------- | -----: |
| Primary enterable buildings |  10–12 |
| Filler buildings            |  20–35 |
| NPCs                        |  10–16 |
| Large landmarks             |   7–10 |
| Outdoor props               | 80–150 |
| Lanterns / braziers         |  25–45 |
| Grave markers               |  30–60 |
| Road splines                |  10–14 |
| Distinct plazas/yards       |    5–7 |

---

# 21. Recommended First Implementation Order

1. Increase `TOWN_RECT`.
2. Add grid conversion helpers.
3. Add rampart ring and gate cuts.
4. Stamp road splines.
5. Add plazas.
6. Add primary building footprints.
7. Generate building walls, interiors, and doors.
8. Add collision merge.
9. Add NPCs.
10. Add portals.
11. Add landmarks.
12. Add outdoor props.
13. Add filler buildings.
14. Run headless load test.
15. Screenshot whole town.
16. Screenshot each district.
17. Adjust alley widths and prop collisions.

---

# 22. Replacement Constants

Replace the old constants with:

```gdscript
# --- City bounds ------------------------------------------------------------------

const TILE := 32

# Larger Sanctuary bounds.
# Grid: -104..104 x -96..96
# World: 6656 x 6144 px
const TOWN_RECT := Rect2(-3328.0, -3072.0, 6656.0, 6144.0)

# Multiplayer spawn yard near the west gate.
const SPAWN_POS := Vector2(-2496.0, -128.0)

# Fountain is no longer the city center.
# It sits in the crooked Priest Court.
const FOUNTAIN_POS := Vector2(-384.0, -640.0)
const FOUNTAIN_RADIUS := 64.0

# Irregular plaza replaces circular central plaza.
const PLAZA_CENTER := Vector2(-384.0, -640.0)
const PLAZA_RADIUS := 224.0 # only used for fallback/debug, not final shape

# Arena portal in Lower Sanctum.
const PORTAL_POS := Vector2(1344.0, 1792.0)

# New world gate.
const WORLD_GATE_POS := Vector2(-896.0, 2048.0)
```

---

# 23. Design Validation Checklist

The layout is successful if:

- The player does not immediately see the whole town from spawn.
- The fountain is memorable, but not geometrically central.
- The cathedral dominates the northern skyline.
- The tavern feels like the social heart.
- Vendors are findable but not arranged like a UI menu.
- Guild trainers feel embedded in districts.
- There are at least 3 ways to reach the fountain.
- There are at least 2 ways to reach Merchant Bend.
- There are narrow alleys, but no multiplayer-hostile chokepoints.
- Every service building has enough interior space.
- The Arena Portal and World Gate feel like separate destinations.
- The town reads as miserable, old, and inhabited.
- Filler buildings create density.
- Ruins and parks create breathing room without becoming cheerful.
- Screenshot review shows a town, not a crossroad.

---

# 24. Most Important Rule

Do not place things symmetrically unless they are religious, military, or ritual structures.

Medieval town logic should be:

```text
old sacred thing first
walls around it later
houses attached wherever space allowed
commerce on traffic bends
guilds in repurposed buildings
ruins left where rebuilding failed
portals isolated where sane people avoid them
```

That is the Sanctuary.
