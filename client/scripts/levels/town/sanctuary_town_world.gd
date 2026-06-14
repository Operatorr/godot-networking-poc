## SanctuaryTownWorld — the redesigned Sanctuary as a self-contained, code-generated placeholder
## city: a dense, ruined, gothic medieval pilgrim town (Diablo / Tristram tone, NOT a clean hub).
##
## Everything here is a CODE-GENERATED PLACEHOLDER (no PNGs) except three kept art pieces wired by
## the level: the fountain sheet, the NPC sprites, and the Arena portal sheet. The whole city is
## data-driven from the GRID tables below (system of record: docs/design/sanctuary-layout.md and
## docs/design/sanctuary-redesign-spec.md), so it is easy to author now and swap for real art later.
##
## This builder is deliberately decoupled from the networked ArenaBase: it is a plain Node2D that
## paints ground, ramparts, buildings, interiors, props, landmarks, the fountain and the decorative
## World Gate, then wires wind-sway / glow shaders and drifting ash + leaf particles so the dead
## town still breathes. The level (sanctuary.gd) instantiates it; an offline preview can too.
##
## REPLACING PLACEHOLDERS: every placeholder is in the "placeholder" group and carries meta
## (placeholder=true, replace_with, kind, footprint). The scene tree mirrors the tables
## (World/Buildings/<Key>, World/Props, World/Ground, World/WallVisuals). Swap a slot's drawn node
## for a Sprite2D/tileset at the same transform; nothing else changes.
##
## COORDINATES: all tables are authored in GRID cells (Vector2i / Rect2i). World px = grid * TILE.
class_name SanctuaryTownWorld
extends Node2D

const SanctuaryPropsScript := preload("res://scripts/levels/town/sanctuary_props.gd")
const SWAY_SHADER: Shader = preload("res://assets/shaders/town/sway.gdshader")
const GLOW_SHADER: Shader = preload("res://assets/shaders/town/glow.gdshader")

## Environment collision layer (mirrors ArenaBase.ENVIRONMENT_COLLISION_LAYER = 8). Town colliders
## are cosmetic — Sanctuary movement is server-authoritative walk-through (no obstacles) — but they
## are tagged here for future local/offline use, matching the established prop-collider pattern.
const ENVIRONMENT_COLLISION_LAYER := 8

const TILE := 32.0

# --- City bounds (redesign spec §1) -------------------------------------------------
## Grid -104..104 x -96..96 → world 6656 × 6144 px. Kept in lockstep with the server's
## SANCTUARY_MAP_MIN/MAX (rust/sim_core/src/constants.rs) and sanctuary.gd _world_geometry().
const TOWN_RECT := Rect2(-3328.0, -3072.0, 6656.0, 6144.0)
const GRID_MIN := Vector2i(-104, -96)
const GRID_MAX := Vector2i(104, 96)

const SPAWN_CELL := Vector2i(-78, -4)            # West Gate refuge yard
const FOUNTAIN_CELL := Vector2i(-12, -20)        # crooked Priest Court
const FOUNTAIN_RADIUS := 64.0
const ARENA_PORTAL_CELL := Vector2i(42, 56)      # Lower Sanctum
const WORLD_GATE_CELL := Vector2i(-28, 64)       # decorative, sealed

## Server-authoritative spawn anchors mirror rust SANCTUARY_PLAYER_SPAWNS; kept for client use.
const SPAWN_POINTS: Array = [
	Vector2i(-78, -4), Vector2i(-80, -7), Vector2i(-76, -1), Vector2i(-73, -5),
	Vector2i(-82, 2), Vector2i(-74, 4), Vector2i(-85, -2), Vector2i(-71, -9),
]

# --- Grim palette (redesign spec §8) ------------------------------------------------
const ABYSS := Color("050706")
const IRON := Color("252928")
const ASH := Color("555852")
const UMBER := Color("3a211a")
const BLOOD := Color("4a1512")
const RUST := Color("8a261f")
const GOLD := Color("9b7428")
const BONE := Color("d8d0bc")
const TAUPE := Color("7a6253")
const SULFUR := Color("c69a2e")
const VIOLET := Color("5b3a8e")
const ELDRITCH := Color("2b183d")
const MAGENTA := Color("8a2d55")
const VBLUE := Color("1d3557")
const TEAL := Color("1c6c73")

## Wall materials → oblique [top, face, edge] colors. Faces are kept dark for the 3/4 read.
enum Mat { STONE, DARK_WOOD, COAL_STONE, CATHEDRAL, COLD_STONE, RAMPART, CHARRED }

## Ground visual styles (resolved to colors in _GroundLayer). Maps the spec's many road / floor
## strings onto a manageable set of grim surfaces.
enum G {
	MUD, MUD_ASH, COBBLE_DARK, COBBLE_BROKEN, COBBLE_WET, COBBLE_PROC, COBBLE_MARKET,
	COBBLE_COAL, COBBLE_COLD, COBBLE_NARROW, GRAVE_PATH, OLD_STONE, CIVIC, PLAZA,
	ASH_GRASS, BLOOD_GROUND, INT_WOOD, INT_STONE, INT_COLD, INT_COAL, ELDRITCH_GROUND,
}

## Spec ground/floor string → G style.
const GROUND_NAMES := {
	"dark_cobble": G.COBBLE_DARK, "processional_cobble": G.COBBLE_PROC,
	"market_cobble": G.COBBLE_MARKET, "broken_cobble": G.COBBLE_BROKEN,
	"mud_cobble": G.COBBLE_BROKEN, "wet_cobble": G.COBBLE_WET,
	"narrow_mud_cobble": G.COBBLE_BROKEN, "coal_cobble": G.COBBLE_COAL,
	"narrow_cobble": G.COBBLE_NARROW, "cold_cobble": G.COBBLE_COLD,
	"old_stone": G.OLD_STONE, "grave_stone_path": G.GRAVE_PATH,
	"dark_civic_cobble": G.CIVIC, "mud_ash": G.MUD_ASH, "mud": G.MUD,
	"cold_cathedral_stone": G.INT_COLD, "dark_wood": G.INT_WOOD,
	"stained_wood": G.INT_WOOD, "rough_wood": G.INT_WOOD, "dark_stone": G.INT_STONE,
	"stained_stone": G.INT_STONE, "coal_stone": G.INT_COAL,
	"worn_training_stone": G.INT_STONE, "cold_stone": G.INT_COLD,
}

# =============================================================================
# CITY DATA  (GRID coordinates; world = grid * TILE)
# =============================================================================

## Decorative rampart ring (spec §4). Hard boundary stays the server's job; this is the visible wall.
const RAMPART_OUTER := Rect2i(-96, -88, 192, 176)
const RAMPART_INNER := Rect2i(-90, -82, 180, 164)
const GATES := [
	Rect2i(-96, -10, 8, 14),   # West Gate (main arrival)
	Rect2i(88, -26, 8, 10),    # East postern (service)
	Rect2i(-36, 82, 18, 6),    # South world-gate gap
	Rect2i(34, 82, 18, 6),     # South portal service breach
]
const RAMPART_BREACHES := [
	Rect2i(-74, -88, 10, 6), Rect2i(58, -88, 12, 6),
	Rect2i(-96, 48, 6, 14), Rect2i(90, 38, 6, 18),
]

## Roads — weighted polylines stamped with rough edges (spec §5).
const ROADS := [
	{"points": [Vector2i(-92, -4), Vector2i(-78, -4), Vector2i(-65, -6), Vector2i(-52, -9), Vector2i(-40, -13), Vector2i(-27, -17), Vector2i(-12, -20)], "width": 7, "ground": "dark_cobble", "priority": 50},
	{"points": [Vector2i(-12, -20), Vector2i(-10, -29), Vector2i(-8, -38), Vector2i(-7, -48), Vector2i(-6, -58)], "width": 6, "ground": "processional_cobble", "priority": 55},
	{"points": [Vector2i(-12, -20), Vector2i(0, -18), Vector2i(12, -13), Vector2i(22, -6), Vector2i(26, 5), Vector2i(18, 15), Vector2i(4, 20)], "width": 6, "ground": "market_cobble", "priority": 54},
	{"points": [Vector2i(-12, -20), Vector2i(-10, -6), Vector2i(-4, 7), Vector2i(8, 22), Vector2i(24, 39), Vector2i(42, 56)], "width": 6, "ground": "broken_cobble", "priority": 52},
	{"points": [Vector2i(-20, 3), Vector2i(-26, 18), Vector2i(-31, 35), Vector2i(-30, 51), Vector2i(-28, 64), Vector2i(-27, 83)], "width": 5, "ground": "mud_cobble", "priority": 51},
	{"points": [Vector2i(-65, -6), Vector2i(-57, 2), Vector2i(-47, 5), Vector2i(-37, 3), Vector2i(-26, -2)], "width": 5, "ground": "wet_cobble", "priority": 49},
	{"points": [Vector2i(-48, 4), Vector2i(-43, 14), Vector2i(-37, 24), Vector2i(-29, 34), Vector2i(-18, 43)], "width": 3, "ground": "narrow_mud_cobble", "priority": 56},
	{"points": [Vector2i(-64, 10), Vector2i(-52, 16), Vector2i(-41, 21), Vector2i(-31, 20)], "width": 4, "ground": "coal_cobble", "priority": 53},
	{"points": [Vector2i(22, -6), Vector2i(36, -13), Vector2i(52, -19), Vector2i(69, -22), Vector2i(91, -21)], "width": 4, "ground": "narrow_cobble", "priority": 48},
	{"points": [Vector2i(36, -13), Vector2i(47, -24), Vector2i(58, -35), Vector2i(66, -45)], "width": 4, "ground": "cold_cobble", "priority": 50},
	{"points": [Vector2i(-8, -48), Vector2i(-22, -51), Vector2i(-36, -56), Vector2i(-48, -62)], "width": 4, "ground": "old_stone", "priority": 48},
	{"points": [Vector2i(-6, -58), Vector2i(11, -60), Vector2i(28, -63), Vector2i(42, -68)], "width": 3, "ground": "grave_stone_path", "priority": 48},
]

## Irregular plazas / yards (spec §6). Polygons fill point-by-point; rects fill directly.
const PRIEST_COURT_POLY := [Vector2i(-28, -28), Vector2i(-14, -34), Vector2i(5, -31), Vector2i(16, -22), Vector2i(11, -9), Vector2i(-5, -5), Vector2i(-24, -10), Vector2i(-33, -19)]
const MERCHANT_BEND_POLY := [Vector2i(3, -13), Vector2i(23, -16), Vector2i(39, -5), Vector2i(37, 14), Vector2i(20, 26), Vector2i(2, 21), Vector2i(-2, 4)]
const PORTAL_YARD_POLY := [Vector2i(23, 42), Vector2i(48, 38), Vector2i(64, 52), Vector2i(61, 72), Vector2i(40, 80), Vector2i(20, 69)]
const CATHEDRAL_FORECOURT := [Vector2i(-24, -58), Vector2i(12, -59), Vector2i(20, -49), Vector2i(8, -40), Vector2i(-17, -41), Vector2i(-29, -50)]
const WEST_GATE_YARD := Rect2i(-91, -16, 33, 26)
const WORLD_GATE_YARD := Rect2i(-43, 52, 31, 30)

## Primary enterable buildings (spec §8). `mat` = exterior wall material; `floor` = interior ground.
const BUILDINGS := [
	{"key": "cathedral_of_ash", "name": "Cathedral of Ash", "rect": Rect2i(-22, -78, 36, 24), "door_side": "S", "door_center": -4, "door_width": 5, "height": 48.0, "mat": Mat.CATHEDRAL, "floor": "cold_cathedral_stone", "plaque": true},
	{"key": "last_lantern_tavern", "name": "The Last Lantern", "rect": Rect2i(-52, -9, 17, 14), "door_side": "E", "door_center": -2, "door_width": 4, "height": 32.0, "mat": Mat.DARK_WOOD, "floor": "dark_wood", "plaque": true},
	{"key": "ledger_house_bank", "name": "Ledger House", "rect": Rect2i(8, 9, 16, 13), "door_side": "S", "door_center": 15, "door_width": 3, "height": 34.0, "mat": Mat.STONE, "floor": "dark_stone", "plaque": true},
	{"key": "hammer_and_hilt", "name": "Hammer & Hilt", "rect": Rect2i(-55, 14, 17, 13), "door_side": "N", "door_center": -47, "door_width": 3, "height": 30.0, "mat": Mat.COAL_STONE, "floor": "coal_stone", "plaque": true},
	{"key": "bubbling_flask", "name": "The Bubbling Flask", "rect": Rect2i(31, -8, 13, 11), "door_side": "W", "door_center": -3, "door_width": 3, "height": 30.0, "mat": Mat.DARK_WOOD, "floor": "stained_wood", "plaque": true},
	{"key": "equipment_exchange", "name": "The Iron Reliquary", "rect": Rect2i(28, 11, 15, 12), "door_side": "W", "door_center": 17, "door_width": 3, "height": 32.0, "mat": Mat.DARK_WOOD, "floor": "dark_wood", "plaque": true},
	{"key": "old_barracks", "name": "Old Barracks", "rect": Rect2i(-72, 17, 19, 14), "door_side": "E", "door_center": 24, "door_width": 4, "height": 32.0, "mat": Mat.STONE, "floor": "worn_training_stone", "plaque": true},
	{"key": "gallows_den", "name": "Gallows Den", "rect": Rect2i(-31, 35, 14, 12), "door_side": "S", "door_center": -24, "door_width": 2, "height": 28.0, "mat": Mat.DARK_WOOD, "floor": "dark_wood", "plaque": true},
	{"key": "cracked_observatory", "name": "The Cracked Observatory", "rect": Rect2i(59, -49, 16, 18), "door_side": "W", "door_center": -39, "door_width": 3, "height": 40.0, "mat": Mat.COLD_STONE, "floor": "cold_stone", "plaque": true},
	{"key": "pilgrim_storehouse", "name": "Pilgrim Storehouse", "rect": Rect2i(-82, -29, 13, 11), "door_side": "S", "door_center": -76, "door_width": 3, "height": 28.0, "mat": Mat.STONE, "floor": "rough_wood", "plaque": true},
	{"key": "corpse_washer", "name": "Corpse Washer's House", "rect": Rect2i(-77, 42, 12, 11), "door_side": "E", "door_center": 47, "door_width": 2, "height": 26.0, "mat": Mat.STONE, "floor": "stained_stone", "plaque": true},
]

## Filler buildings make the town dense (spec §9). enterable=false (visual door); ruin>0 drops walls.
const FILLER_BUILDINGS := [
	{"rect": Rect2i(-70, -19, 10, 9), "door_side": "S", "door_center": -65, "door_width": 2, "kind": "locked_home"},
	{"rect": Rect2i(-62, -28, 9, 8), "door_side": "E", "door_center": -24, "door_width": 2, "kind": "burned_home", "ruin": 0.25},
	{"rect": Rect2i(-35, -20, 9, 10), "door_side": "W", "door_center": -15, "door_width": 2, "kind": "leaning_house"},
	{"rect": Rect2i(0, -46, 12, 10), "door_side": "S", "door_center": 6, "door_width": 3, "kind": "scriptorium_ruin", "ruin": 0.35},
	{"rect": Rect2i(-31, -42, 10, 9), "door_side": "S", "door_center": -26, "door_width": 2, "kind": "candle_maker"},
	{"rect": Rect2i(20, -72, 11, 10), "door_side": "W", "door_center": -67, "door_width": 2, "kind": "grave_keeper_house"},
	{"rect": Rect2i(36, -75, 12, 13), "door_side": "S", "door_center": 42, "door_width": 3, "kind": "ossuary_chapel", "ruin": 0.3},
	{"rect": Rect2i(45, -26, 10, 9), "door_side": "S", "door_center": 50, "door_width": 2, "kind": "locked_home"},
	{"rect": Rect2i(51, -13, 9, 8), "door_side": "W", "door_center": -9, "door_width": 2, "kind": "locked_home"},
	{"rect": Rect2i(45, 9, 13, 12), "door_side": "W", "door_center": 15, "door_width": 3, "kind": "warehouse"},
	{"rect": Rect2i(13, -31, 10, 9), "door_side": "S", "door_center": 18, "door_width": 2, "kind": "butcher_ruin", "ruin": 0.3},
	{"rect": Rect2i(-56, 42, 10, 10), "door_side": "N", "door_center": -51, "door_width": 2, "kind": "plague_house"},
	{"rect": Rect2i(-44, 51, 9, 9), "door_side": "E", "door_center": 55, "door_width": 2, "kind": "plague_house"},
	{"rect": Rect2i(-5, 47, 11, 9), "door_side": "W", "door_center": 51, "door_width": 2, "kind": "collapsed_home", "ruin": 0.4},
	{"rect": Rect2i(8, 55, 12, 10), "door_side": "S", "door_center": 14, "door_width": 2, "kind": "lower_storehouse"},
	{"rect": Rect2i(59, 40, 12, 11), "door_side": "W", "door_center": 45, "door_width": 2, "kind": "caretaker_house"},
	{"rect": Rect2i(24, 70, 9, 8), "door_side": "N", "door_center": 29, "door_width": 2, "kind": "burned_home", "ruin": 0.3},
	{"rect": Rect2i(36, 73, 9, 8), "door_side": "N", "door_center": 40, "door_width": 2, "kind": "burned_home", "ruin": 0.3},
	{"rect": Rect2i(-89, 10, 8, 7), "door_side": "E", "door_center": 13, "door_width": 2, "kind": "shed"},
	{"rect": Rect2i(-88, -26, 8, 7), "door_side": "E", "door_center": -23, "door_width": 2, "kind": "shed"},
]

## Interior furniture (spec §10), as {kind, lx, ly} local grid centers within the building rect.
const INTERIORS := {
	"cathedral_of_ash": [
		{"kind": "altar", "lx": 18.0, "ly": 4.5}, {"kind": "glory_shrine", "lx": 18.0, "ly": 2.0},
		{"kind": "pew_left_01", "lx": 10.5, "ly": 11.0}, {"kind": "pew_right_01", "lx": 25.5, "ly": 11.0},
		{"kind": "pew_left_02", "lx": 10.5, "ly": 15.0}, {"kind": "pew_right_02", "lx": 25.5, "ly": 15.0},
		{"kind": "candle_cluster", "lx": 5.0, "ly": 6.0}, {"kind": "candle_cluster", "lx": 31.0, "ly": 6.0},
		{"kind": "broken_statue", "lx": 3.5, "ly": 18.5}, {"kind": "confession_cell", "lx": 32.0, "ly": 19.0},
	],
	"last_lantern_tavern": [
		{"kind": "bar_counter", "lx": 3.5, "ly": 6.0}, {"kind": "fireplace", "lx": 9.0, "ly": 2.0},
		{"kind": "table", "lx": 8.5, "ly": 6.5}, {"kind": "table", "lx": 13.5, "ly": 8.5},
		{"kind": "barrels", "lx": 3.5, "ly": 11.0}, {"kind": "notice_wall", "lx": 13.5, "ly": 1.5},
	],
	"ledger_house_bank": [
		{"kind": "counter", "lx": 8.0, "ly": 4.0}, {"kind": "vault_door", "lx": 12.5, "ly": 2.0},
		{"kind": "ledger_table", "lx": 6.0, "ly": 8.5}, {"kind": "lockbox_stack", "lx": 11.5, "ly": 8.5},
	],
	"hammer_and_hilt": [
		{"kind": "forge", "lx": 4.0, "ly": 4.0}, {"kind": "anvil", "lx": 8.0, "ly": 6.0},
		{"kind": "weapon_rack", "lx": 13.5, "ly": 3.0}, {"kind": "armor_stand", "lx": 13.5, "ly": 8.5},
		{"kind": "coal_pile", "lx": 4.5, "ly": 10.0},
	],
	"bubbling_flask": [
		{"kind": "vendor_counter", "lx": 3.0, "ly": 5.5}, {"kind": "shelf_potions", "lx": 8.5, "ly": 2.0},
		{"kind": "shelf_potions", "lx": 8.5, "ly": 9.0}, {"kind": "cauldron", "lx": 8.5, "ly": 5.5},
	],
	"equipment_exchange": [
		{"kind": "counter", "lx": 3.0, "ly": 6.0}, {"kind": "armor_rack", "lx": 8.5, "ly": 3.5},
		{"kind": "weapon_rack", "lx": 12.5, "ly": 3.5}, {"kind": "chest", "lx": 9.0, "ly": 9.0},
	],
	"old_barracks": [
		{"kind": "training_dummy", "lx": 5.0, "ly": 5.0}, {"kind": "training_dummy", "lx": 9.0, "ly": 5.0},
		{"kind": "weapon_rack", "lx": 15.0, "ly": 3.0}, {"kind": "broken_table", "lx": 6.0, "ly": 10.0},
		{"kind": "armor_pile", "lx": 14.5, "ly": 10.5},
	],
	"gallows_den": [
		{"kind": "knife_table", "lx": 6.0, "ly": 4.0}, {"kind": "hidden_chest", "lx": 11.0, "ly": 3.0},
		{"kind": "map_wall", "lx": 5.5, "ly": 1.5}, {"kind": "sleeping_roll", "lx": 10.5, "ly": 8.0},
	],
	"cracked_observatory": [
		{"kind": "void_crack", "lx": 8.5, "ly": 6.5}, {"kind": "bookcase", "lx": 3.5, "ly": 6.0},
		{"kind": "broken_telescope", "lx": 10.5, "ly": 3.5}, {"kind": "ritual_table", "lx": 10.0, "ly": 11.5},
		{"kind": "floating_stones", "lx": 13.0, "ly": 8.0},
	],
	"pilgrim_storehouse": [
		{"kind": "barrels", "lx": 3.0, "ly": 3.0}, {"kind": "chest", "lx": 9.5, "ly": 3.5},
		{"kind": "table", "lx": 6.5, "ly": 7.5},
	],
	"corpse_washer": [
		{"kind": "ledger_table", "lx": 3.5, "ly": 4.0}, {"kind": "candle_cluster", "lx": 8.5, "ly": 3.0},
		{"kind": "chest", "lx": 8.0, "ly": 7.5},
	],
}

## Landmarks (spec §13): ground-tinted zones + scattered fill.
const LANDMARKS := [
	{"kind": "ruined_garden", "rect": Rect2i(-54, -68, 22, 20), "ground": G.ASH_GRASS},
	{"kind": "graveyard_ossuary", "rect": Rect2i(18, -80, 34, 22), "ground": G.GRAVE_PATH},
	{"kind": "muddy_ruin_park", "rect": Rect2i(-82, 36, 31, 28), "ground": G.ASH_GRASS},
	{"kind": "execution_corner", "rect": Rect2i(-39, 28, 18, 12), "ground": G.BLOOD_GROUND},
	{"kind": "player_trade_arcade", "rect": Rect2i(3, 25, 24, 8), "ground": G.COBBLE_MARKET},
	{"kind": "portal_yard", "rect": Rect2i(23, 42, 41, 38), "ground": G.ELDRITCH_GROUND},
]

## Stair ramps — walkable visual rises (spec §15), drawn as banded ground.
const STAIRS := [
	{"rects": [Rect2i(-13, -54, 14, 2), Rect2i(-12, -52, 13, 2), Rect2i(-11, -50, 12, 2)], "dir": "S"},
	{"rects": [Rect2i(55, -31, 8, 2), Rect2i(56, -33, 8, 2)], "dir": "S"},
	{"rects": [Rect2i(22, 39, 12, 2), Rect2i(24, 41, 12, 2), Rect2i(26, 43, 12, 2)], "dir": "S"},
	{"rects": [Rect2i(-32, 58, 9, 2), Rect2i(-33, 60, 10, 2), Rect2i(-34, 62, 11, 2)], "dir": "S"},
]

## Outdoor props — every district merged (spec §14 + §12), GRID positions. Solidity & FX come from
## SanctuaryProps.COLLIDERS / FX. "barrel_stack" is the spec's name for our "barrels".
const PROPS := [
	# West Gate Refuge
	{"kind": "refugee_tent", "cell": Vector2i(-84, -13)}, {"kind": "refugee_tent", "cell": Vector2i(-75, -14)},
	{"kind": "refugee_tent", "cell": Vector2i(-86, 7)}, {"kind": "broken_cart", "cell": Vector2i(-71, 5)},
	{"kind": "notice_board", "cell": Vector2i(-65, -1)}, {"kind": "trade_board", "cell": Vector2i(-63, 3)},
	{"kind": "barrels", "cell": Vector2i(-80, 11)}, {"kind": "dead_campfire", "cell": Vector2i(-76, -3)},
	{"kind": "hanging_lantern_post", "cell": Vector2i(-69, -8)}, {"kind": "hanging_lantern_post", "cell": Vector2i(-69, 8)},
	# Priest Court
	{"kind": "broken_statue", "cell": Vector2i(-18, -28)}, {"kind": "candle_cluster", "cell": Vector2i(-15, -23)},
	{"kind": "candle_cluster", "cell": Vector2i(-8, -17)}, {"kind": "prayer_strip_wall", "cell": Vector2i(6, -27)},
	{"kind": "dead_tree_small", "cell": Vector2i(5, -12)}, {"kind": "broken_bench", "cell": Vector2i(-24, -16)},
	{"kind": "broken_bench", "cell": Vector2i(6, -23)}, {"kind": "skull_reliquary", "cell": Vector2i(-4, -29)},
	# Cathedral Ward
	{"kind": "grave_marker", "cell": Vector2i(24, -68)}, {"kind": "grave_marker", "cell": Vector2i(29, -70)},
	{"kind": "grave_marker", "cell": Vector2i(35, -67)}, {"kind": "grave_marker", "cell": Vector2i(42, -72)},
	{"kind": "mausoleum", "cell": Vector2i(45, -63)}, {"kind": "dead_tree_large", "cell": Vector2i(32, -61)},
	{"kind": "bone_wall", "cell": Vector2i(20, -76)}, {"kind": "broken_arcade", "cell": Vector2i(-46, -61)},
	{"kind": "dry_well", "cell": Vector2i(-39, -55)}, {"kind": "cloister_dead_tree", "cell": Vector2i(-51, -52)},
	# Tavern Row
	{"kind": "tavern_sign", "cell": Vector2i(-35, -4)}, {"kind": "barrels", "cell": Vector2i(-42, 6)},
	{"kind": "vomit_stain", "cell": Vector2i(-45, 3)}, {"kind": "wanted_posters", "cell": Vector2i(-36, -12)},
	{"kind": "lantern_post", "cell": Vector2i(-41, -6)}, {"kind": "beggar_bedroll", "cell": Vector2i(-31, 2)},
	# Merchant Bend
	{"kind": "market_stall", "cell": Vector2i(7, -8)}, {"kind": "market_stall", "cell": Vector2i(17, -10)},
	{"kind": "market_stall", "cell": Vector2i(25, 0)}, {"kind": "hanging_cage", "cell": Vector2i(31, 6)},
	{"kind": "coin_scale_table", "cell": Vector2i(5, 12)}, {"kind": "lockbox_stack", "cell": Vector2i(25, 19)},
	{"kind": "forge_smoke_stack", "cell": Vector2i(-43, 13)}, {"kind": "coal_cart", "cell": Vector2i(-39, 27)},
	{"kind": "weapon_display", "cell": Vector2i(-51, 13)},
	# Guild Backstreets
	{"kind": "training_dummy", "cell": Vector2i(-67, 33)}, {"kind": "training_dummy", "cell": Vector2i(-61, 35)},
	{"kind": "blood_sand_patch", "cell": Vector2i(-64, 31)}, {"kind": "gallows", "cell": Vector2i(-32, 32)},
	{"kind": "sewer_grate", "cell": Vector2i(-24, 34)}, {"kind": "hanging_cloth", "cell": Vector2i(-20, 39)},
	{"kind": "knife_marks_wall", "cell": Vector2i(-18, 35)},
	# Mage Quarter
	{"kind": "void_crack_ground", "cell": Vector2i(56, -34)}, {"kind": "floating_stone", "cell": Vector2i(62, -29)},
	{"kind": "broken_telescope_large", "cell": Vector2i(75, -52)}, {"kind": "blue_brazier", "cell": Vector2i(55, -45)},
	{"kind": "blue_brazier", "cell": Vector2i(76, -35)}, {"kind": "forbidden_books_crate", "cell": Vector2i(51, -28)},
	# Lower Sanctum
	{"kind": "catacomb_seal", "cell": Vector2i(8, 52)}, {"kind": "warning_bell", "cell": Vector2i(18, 42)},
	{"kind": "kneeling_statue", "cell": Vector2i(30, 60)}, {"kind": "kneeling_statue", "cell": Vector2i(54, 60)},
	{"kind": "ash_pile", "cell": Vector2i(22, 69)}, {"kind": "ritual_blood_stain", "cell": Vector2i(42, 57)},
	# Arena Portal ring
	{"kind": "obelisk", "cell": Vector2i(34, 50)}, {"kind": "obelisk", "cell": Vector2i(50, 50)},
	{"kind": "obelisk", "cell": Vector2i(34, 64)}, {"kind": "obelisk", "cell": Vector2i(50, 64)},
	{"kind": "chain_post", "cell": Vector2i(38, 48)}, {"kind": "chain_post", "cell": Vector2i(46, 48)},
	{"kind": "kneeling_statue", "cell": Vector2i(42, 66)}, {"kind": "ritual_circle", "cell": Vector2i(42, 56)},
	# World Gate (decorative)
	{"kind": "broken_portcullis", "cell": Vector2i(-28, 77)}, {"kind": "warning_sign", "cell": Vector2i(-34, 60)},
	{"kind": "corpse_cart", "cell": Vector2i(-22, 58)}, {"kind": "ash_brazier", "cell": Vector2i(-35, 66)},
	{"kind": "ash_brazier", "cell": Vector2i(-21, 66)},
	# A few gate braziers (light is rare — only at the thresholds).
	{"kind": "ash_brazier", "cell": Vector2i(-87, -8)}, {"kind": "ash_brazier", "cell": Vector2i(-87, 8)},
]

## NPCs (spec §11). sprite = existing PNG in assets/sprites/npcs (or "" → placeholder figure).
const NPCS := [
	{"key": "father_aldric", "name": "Father Aldric", "title": "Priest of the Ash", "role": "PRIEST", "cell": Vector2i(-4, -72), "sprite": "priest.png", "color": "9b7428", "dialog": "Kneel if your knees still bend, pilgrim. The gods went silent before your grandfather drew breath, yet the bells we have left still ring. Offer your Glory at the shrine when the rite is consecrated — what you sacrifice here makes the next soul you raise a little harder to kill."},
	{"key": "master_brandt", "name": "Master Brandt", "title": "Drillmaster of the Old Barracks", "role": "CLASS_TRAINER", "cell": Vector2i(-61, 24), "sprite": "warrior_trainer.png", "color": "8a261f", "dialog": "Nobody here teaches heroism, recruit. We teach you to be the one who walks back through the gate. Warrior training opens when the guild ledgers arrive — bleed in the Arena until then."},
	{"key": "archmagus_elowen", "name": "Archmagus Elowen", "title": "Keeper of the Cracked Observatory", "role": "CLASS_TRAINER", "cell": Vector2i(67, -40), "sprite": "mage_trainer.png", "color": "5b3a8e", "dialog": "Mind the cracks in the floor — they mind you back. The scholars here understood too much and kept reading. When the sanctum is attuned I will teach you to do the same, carefully. Carefully is the whole lesson."},
	{"key": "shade_vesper", "name": "Shade Vesper", "title": "Of the Gallows Den", "role": "CLASS_TRAINER", "cell": Vector2i(-24, 42), "sprite": "rogue_trainer.png", "color": "1c6c73", "dialog": "You found the den past the gallows — lesson one, passed. We deal in speed, shadow, and knowing which door is still unlocked. Training begins once the contracts are signed. Don't ask whose blood signs them."},
	{"key": "tilda_brewbloom", "name": "Tilda Brewbloom", "title": "Apothecary of the Bubbling Flask", "role": "VENDOR", "cell": Vector2i(35, -3), "sprite": "potion_vendor.png", "color": "1c6c73", "dialog": "Tonics, salves, and a few brews that bite back. Everything on these shelves keeps a dying body upright one hour longer — and out here, an hour is a fortune. The stock opens with the first caravan that survives the road."},
	{"key": "garrick_forgehand", "name": "Garrick Forgehand", "title": "Smith of Hammer & Hilt", "role": "VENDOR", "cell": Vector2i(-47, 20), "sprite": "equipment_vendor.png", "color": "8a261f", "dialog": "The forge is cold blood and old iron, friend. I sell arms to people who will likely die in them — honest work in a dishonest age. The racks open for trade once the coal carts come through."},
	{"key": "goldwin_ledger", "name": "Goldwin Ledger", "title": "Bankmaster of Ledger House", "role": "BANKER", "cell": Vector2i(15, 14), "sprite": "banker.png", "color": "9b7428", "dialog": "Your valuables outlive your heroes here, behind iron the plague can't pick. Vault deposits open with the next charter. Until then — try not to carry your whole life through the portal at once."},
	{"key": "portal_warden", "name": "The Portal Warden", "title": "Binder of the Lower Sanctum", "role": "GENERIC", "cell": Vector2i(35, 54), "sprite": "", "color": "5b3a8e", "dialog": "Two doors out of this city, stranger. The Arena ring takes the willing. The World Gate is sealed — I keep it that way with iron, prayer, and blood that was not mine to give. Step onto the ritual stone when you mean to leave. Not before."},
	{"key": "innkeeper", "name": "Marta Voss", "title": "Keeper of The Last Lantern", "role": "GENERIC", "cell": Vector2i(-49, -4), "sprite": "", "color": "c69a2e", "dialog": "Sit by the fire while it still burns. This is the only warm room in a city the gods forgot — the ale is thin, the rumors are thick, and everyone here is waiting for a death they hope belongs to someone else."},
	{"key": "corpse_collector", "name": "Oren Gravesack", "title": "Corpse Collector", "role": "GENERIC", "cell": Vector2i(-78, 46), "sprite": "", "color": "7a6253", "dialog": "Don't mind the cart. Everyone rides it eventually — kings, pilgrims, heroes, the lot. I just make sure you get a marker before the plague pit takes you. It's more than most this side of the wall can promise."},
]

# --- Runtime ----------------------------------------------------------------------
var _ground: Dictionary = {}        # Vector2i -> G style id
var _ground_prio: Dictionary = {}   # Vector2i -> stamping priority
var _wall_cells: Dictionary = {}    # Vector2i -> [Mat, height]
var _stair_cells: Dictionary = {}   # Vector2i -> dir string
var _interior_prop_specs: Array = []  # {kind, pos(world), key}
var _scatter_props: Array = []      # {kind, cell} from landmark fills
var _props_container: Node2D = null
var _prop_body: StaticBody2D = null


# =============================================================================
# PUBLIC API
# =============================================================================

## Build the full static placeholder city under this node.
func build() -> void:
	_rasterize()
	_build_ground_layer()
	_build_wall_visuals()
	_build_buildings_meta()
	_build_props()
	_build_fountain()
	_build_world_gate_decoration()
	_build_ambient_particles()


## Instantiate the town NPCs under `parent`. `priest_listener` (if valid) is connected to the
## priest's `interacted` signal and the priest is set to suppress its own dialog (sacrifice flow).
func build_npcs(parent: Node2D, npc_scene: PackedScene, texture_dir: String, priest_listener: Callable = Callable()) -> void:
	var container := Node2D.new()
	container.name = "NPCs"
	parent.add_child(container)
	for entry: Dictionary in NPCS:
		var npc = npc_scene.instantiate()
		npc.name = String(entry["key"]).to_pascal_case()
		npc.position = grid_to_world(entry["cell"])
		npc.npc_name = entry["name"]
		npc.npc_title = entry["title"]
		npc.role = _npc_role(entry["role"])
		npc.dialog_text = entry["dialog"]
		npc.placeholder_color = Color(entry["color"])
		var sprite: String = entry["sprite"]
		npc.texture_path = (texture_dir + sprite) if not sprite.is_empty() else ""
		if entry["role"] == "PRIEST" and priest_listener.is_valid():
			npc.suppress_default_dialog = true
			npc.interacted.connect(priest_listener)
		container.add_child(npc)


## Build the functional Arena portal under `parent` using the kept portal art. Returns the node.
func build_arena_portal(parent: Node2D, portal_scene: PackedScene, town_texture_dir: String) -> Node:
	var portal = portal_scene.instantiate()
	portal.name = "ArenaPortal"
	portal.position = grid_to_world(ARENA_PORTAL_CELL)
	portal.portal_name = "Arena Portal"
	portal.destination = 0   # Portal.Destination.ARENA
	portal.requires_connection = true
	portal.texture_path = town_texture_dir + "portal.png"
	portal.animation_sheet_path = town_texture_dir + "portal_idle_sheet.png"
	parent.add_child(portal)
	# Cold corruption aura beneath the ritual ring.
	_add_glow(portal, Vector2.ZERO, VIOLET, 56.0, 1.8)
	return portal


func grid_to_world(cell: Vector2i) -> Vector2:
	return Vector2(cell.x * TILE, cell.y * TILE)


func grid_rect_to_world(r: Rect2i) -> Rect2:
	return Rect2(r.position.x * TILE, r.position.y * TILE, r.size.x * TILE, r.size.y * TILE)


# =============================================================================
# RASTERIZE
# =============================================================================

func _rasterize() -> void:
	# Landmark ground tints first (lowest priority), then roads/plazas over them.
	for lm: Dictionary in LANDMARKS:
		_fill_rect(lm["rect"], lm["ground"], 20)
	_fill_poly(CATHEDRAL_FORECOURT, G.COBBLE_PROC, 30)
	_fill_poly(PRIEST_COURT_POLY, G.CIVIC, 32)
	_fill_poly(MERCHANT_BEND_POLY, G.COBBLE_MARKET, 30)
	_fill_poly(PORTAL_YARD_POLY, G.ELDRITCH_GROUND, 30)
	_fill_rect(WEST_GATE_YARD, G.MUD, 30)
	_fill_rect(WORLD_GATE_YARD, G.BLOOD_GROUND, 30)

	for road: Dictionary in ROADS:
		_stamp_road(road)

	_rasterize_rampart()

	for b: Dictionary in BUILDINGS:
		_rasterize_building(b, false)
	for f: Dictionary in FILLER_BUILDINGS:
		_rasterize_building(f, true)

	# Stair bands (drawn on top of terrace edges).
	for st: Dictionary in STAIRS:
		for r: Rect2i in st["rects"]:
			for c: Vector2i in _rect_cells(r):
				_stair_cells[c] = st["dir"]

	_scatter_landmark_props()


func _stamp_road(road: Dictionary) -> void:
	var pts: Array = road["points"]
	var gid: int = GROUND_NAMES.get(road["ground"], G.COBBLE_DARK)
	var prio: int = road["priority"]
	var rad := maxi(1, int(round(float(road["width"]) / 2.0)))
	for i in range(pts.size() - 1):
		_stamp_segment(pts[i], pts[i + 1], rad, gid, prio)


func _stamp_segment(a: Vector2i, b: Vector2i, rad: int, gid: int, prio: int) -> void:
	var steps := maxi(absi(b.x - a.x), absi(b.y - a.y))
	for s in range(steps + 1):
		var t := float(s) / float(maxi(1, steps))
		var cx := int(round(lerpf(a.x, b.x, t)))
		var cy := int(round(lerpf(a.y, b.y, t)))
		for dx in range(-rad - 1, rad + 2):
			for dy in range(-rad - 1, rad + 2):
				var cell := Vector2i(cx + dx, cy + dy)
				var d := Vector2(dx, dy).length()
				if d <= float(rad) - 0.35:
					_set_ground(cell, gid, prio)
				elif d <= float(rad) + 0.5 and _cell_noise(cell) > 0.4:
					_set_ground(cell, gid, prio)               # rough edge
				elif d <= float(rad) + 1.4 and _cell_noise(cell) > 0.72:
					_set_ground(cell, G.MUD_ASH, prio - 2)       # ash/mud shoulder


func _rasterize_rampart() -> void:
	for c: Vector2i in _rect_cells(RAMPART_OUTER):
		if _rect_has(RAMPART_INNER, c):
			continue                                   # interior of the band
		if _in_any_gate(c) or _in_any_breach(c):
			continue                                   # carved opening
		_set_wall(c, Mat.RAMPART, 36.0)


func _rasterize_building(def: Dictionary, is_filler: bool) -> void:
	var r: Rect2i = def["rect"]
	var tx0 := r.position.x
	var ty0 := r.position.y
	var tx1 := tx0 + r.size.x - 1
	var ty1 := ty0 + r.size.y - 1
	var ruin: float = def.get("ruin", 0.0)
	var mat: int = def.get("mat", _filler_mat(def.get("kind", "")))
	var height: float = def.get("height", 28.0)
	var floor_name: String = def.get("floor", "dark_stone")
	var floor_gid: int = GROUND_NAMES.get(floor_name, G.INT_STONE)

	# Door gap cells.
	var gaps := {}
	for cell: Vector2i in _opening_cells(r, def["door_side"], def["door_center"], def["door_width"]):
		gaps[cell] = true

	# Interior floor (inset by 1) + door threshold patch.
	for x in range(tx0 + 1, tx1):
		for y in range(ty0 + 1, ty1):
			_set_ground(Vector2i(x, y), floor_gid, 60)
	for cell: Vector2i in gaps:
		_set_ground(cell, floor_gid, 60)

	# Perimeter walls (minus the door). Ruined fillers shed wall cells + leave rubble.
	for x in range(tx0, tx1 + 1):
		for y in range(ty0, ty1 + 1):
			var border := x == tx0 or x == tx1 or y == ty0 or y == ty1
			if not border or gaps.has(Vector2i(x, y)):
				continue
			var cell := Vector2i(x, y)
			if ruin > 0.0 and _cell_noise(cell) < ruin:
				if _cell_noise(cell + Vector2i(101, 7)) < 0.45:
					_scatter_props.append({"kind": "ash_pile", "cell": cell})
				continue
			_set_wall(cell, mat, height)

	# Filler flavor: plague chalk / candle / grave keeper markers near the door.
	if is_filler:
		_filler_flavor(def, gaps)


func _filler_flavor(def: Dictionary, gaps: Dictionary) -> void:
	var kind: String = def.get("kind", "")
	if gaps.is_empty():
		return
	var door: Vector2i = gaps.keys()[0]
	match kind:
		"plague_house":
			_scatter_props.append({"kind": "prayer_strip_wall", "cell": door})
		"candle_maker":
			_scatter_props.append({"kind": "candle_cluster", "cell": door + Vector2i(0, 1)})
		"grave_keeper_house":
			_scatter_props.append({"kind": "grave_marker", "cell": door + Vector2i(-1, 1)})
		"ossuary_chapel":
			_scatter_props.append({"kind": "bone_wall", "cell": door + Vector2i(0, 1)})


## Deterministic scatter for graveyards/parks to hit the spec's density targets.
func _scatter_landmark_props() -> void:
	for lm: Dictionary in LANDMARKS:
		var r: Rect2i = lm["rect"]
		match lm["kind"]:
			"graveyard_ossuary":
				_scatter_grid(r, 3, "grave_marker", 0.55)
			"muddy_ruin_park":
				_scatter_grid(r, 4, "grave_marker", 0.3)
				_scatter_grid(r, 7, "dead_tree_small", 0.5)
			"ruined_garden":
				_scatter_grid(r, 6, "dead_tree_small", 0.4)


func _scatter_grid(r: Rect2i, step: int, kind: String, chance: float) -> void:
	var x := r.position.x + 1
	while x < r.position.x + r.size.x - 1:
		var y := r.position.y + 1
		while y < r.position.y + r.size.y - 1:
			var cell := Vector2i(x, y)
			if _cell_noise(cell + Vector2i(33, 91)) < chance:
				_scatter_props.append({"kind": kind, "cell": cell})
			y += step
		x += step


# =============================================================================
# GROUND / WALL VISUALS
# =============================================================================

func _build_ground_layer() -> void:
	var ground := _GroundLayer.new()
	ground.name = "Ground"
	ground.z_index = -20
	ground.z_as_relative = false
	ground.town_rect = TOWN_RECT
	ground.cells = _ground
	ground.stairs = _stair_cells
	ground.styles = _ground_styles()
	add_child(ground)
	ground.queue_redraw()


func _build_wall_visuals() -> void:
	var cells := _wall_cells.keys()
	cells.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		return a.y < b.y if a.y != b.y else a.x < b.x)
	var records: Array = []
	for cell: Vector2i in cells:
		var entry: Array = _wall_cells[cell]
		var cols := _mat_colors(entry[0])
		records.append({
			"rect": Rect2(Vector2(cell) * TILE, Vector2(TILE, TILE)),
			"top": cols[0], "face": cols[1], "edge": cols[2], "h": entry[1],
		})
	var layer := _WallLayer.new()
	layer.name = "WallVisuals"
	layer.z_index = -8
	layer.z_as_relative = false
	layer.records = records
	add_child(layer)
	layer.queue_redraw()


# =============================================================================
# BUILDINGS META + INTERIORS
# =============================================================================

func _build_buildings_meta() -> void:
	var container := Node2D.new()
	container.name = "Buildings"
	container.z_index = -6
	container.z_as_relative = false
	add_child(container)

	_prop_body = StaticBody2D.new()
	_prop_body.name = "TownColliders"
	_prop_body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	_prop_body.collision_mask = 0
	add_child(_prop_body)

	for b: Dictionary in BUILDINGS:
		var r: Rect2 = grid_rect_to_world(b["rect"])
		var slot := Marker2D.new()
		slot.name = String(b["key"]).to_pascal_case()
		slot.position = r.get_center()
		slot.add_to_group("placeholder")
		slot.set_meta("placeholder", true)
		slot.set_meta("kind", "building")
		slot.set_meta("footprint", r)
		slot.set_meta("replace_with", "building:" + String(b["key"]))
		container.add_child(slot)
		if b.get("plaque", false):
			_add_plaque(slot, String(b.get("name", "")), r.size.y)
		# Interior furniture.
		var interior: Array = INTERIORS.get(b["key"], [])
		if not interior.is_empty():
			var inode := Node2D.new()
			inode.name = slot.name + "Interior"
			inode.z_index = -5
			inode.z_as_relative = false
			container.add_child(inode)
			var base: Vector2i = b["rect"].position
			for ip: Dictionary in interior:
				var pos := Vector2((base.x + ip["lx"]) * TILE, (base.y + ip["ly"]) * TILE)
				_spawn_prop(inode, ip["kind"], pos, -5)


func _add_plaque(parent: Node2D, text: String, footprint_h: float) -> void:
	if text.is_empty():
		return
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.offset_left = -170.0
	label.offset_right = 170.0
	label.offset_top = -footprint_h * 0.5 - 36.0
	label.offset_bottom = -footprint_h * 0.5 - 12.0
	label.add_theme_font_size_override("font_size", 14)
	label.add_theme_color_override("font_color", Color(0.85, 0.78, 0.6))
	label.add_theme_color_override("font_outline_color", Color(0.02, 0.03, 0.03))
	label.add_theme_constant_override("outline_size", 5)
	parent.add_child(label)


# =============================================================================
# PROPS + FX
# =============================================================================

func _build_props() -> void:
	_props_container = Node2D.new()
	_props_container.name = "Props"
	_props_container.z_index = -4
	_props_container.z_as_relative = false
	add_child(_props_container)

	for p: Dictionary in PROPS:
		_spawn_prop(_props_container, p["kind"], grid_to_world(p["cell"]), -4)
	for p: Dictionary in _scatter_props:
		_spawn_prop(_props_container, p["kind"], grid_to_world(p["cell"]), -4)


## Spawn one placeholder prop (+ collider if solid, + wind/glow/particles per its FX tag).
func _spawn_prop(container: Node2D, kind: String, pos: Vector2, z: int) -> void:
	var prop = SanctuaryPropsScript.new()
	prop.name = kind.to_pascal_case()
	prop.kind = kind
	prop.palette = _palette()
	prop.position = pos
	prop.z_index = z
	prop.z_as_relative = false
	prop.add_to_group("placeholder")
	prop.set_meta("placeholder", true)
	prop.set_meta("kind", kind)
	prop.set_meta("replace_with", "prop:" + kind)
	container.add_child(prop)

	var col: Dictionary = SanctuaryPropsScript.collider_for(kind)
	if not col.is_empty() and _prop_body:
		var shape := CollisionShape2D.new()
		shape.position = pos
		if col.has("radius"):
			var circle := CircleShape2D.new()
			circle.radius = col["radius"]
			shape.shape = circle
		else:
			var rect := RectangleShape2D.new()
			rect.size = col["size"]
			shape.shape = rect
		_prop_body.add_child(shape)

	_attach_fx(prop, kind)


## Flat ground decals whose glow art is centred at y≈0 (so the halo must sit on them, not float up).
const FLAT_GLOW_KINDS := ["ritual_circle", "ritual_blood_stain", "void_crack_ground", "catacomb_seal"]


func _attach_fx(prop: Node2D, kind: String) -> void:
	var fx: String = SanctuaryPropsScript.fx_for(kind)
	if fx.is_empty():
		return
	if fx == "sway":
		var mat := ShaderMaterial.new()
		mat.shader = SWAY_SHADER
		mat.set_shader_parameter("phase", randf() * TAU)
		var tree := kind.contains("tree")
		# Top-hung cloth / signs / strips: the free hem (near y=0) sways while the nailed top stays
		# pinned — the inverse of a tree (canopy at -y sways, trunk pinned).
		var top_hung := kind.contains("cloth") or kind.contains("strip") or kind.contains("sign") \
			or kind.contains("banner") or kind.contains("poster")
		mat.set_shader_parameter("top_anchored", top_hung)
		mat.set_shader_parameter("sway_strength", 2.6 if tree else 4.2)
		mat.set_shader_parameter("sway_speed", 1.0 if tree else 1.6)
		mat.set_shader_parameter("anchor_height", 60.0 if tree else 34.0)
		prop.material = mat
		if tree:
			prop.add_child(_make_particles("leaves"))
	elif fx.begins_with("glow:"):
		var key := fx.substr(5)
		var color: Color = _palette().get(key, SULFUR)
		# Flat decals carry their light at y≈0; upright sources sit ~22px up.
		var gy := 0.0 if kind in FLAT_GLOW_KINDS else -22.0
		_add_glow(prop, Vector2(0.0, gy), color, 16.0, 2.4)
		if key == "sulfur":
			prop.add_child(_make_particles("fire"))
	elif fx.begins_with("particles:"):
		prop.add_child(_make_particles(fx.substr(10)))


## Additive pulsing glow halo (glow.gdshader) layered over a light source.
func _add_glow(parent: Node2D, local_pos: Vector2, color: Color, radius: float, speed: float) -> void:
	var halo := _GlowHalo.new()
	halo.position = local_pos
	halo.glow_color = color
	halo.radius = radius
	halo.z_index = 1
	halo.z_as_relative = true
	var mat := ShaderMaterial.new()
	mat.shader = GLOW_SHADER
	mat.set_shader_parameter("phase", randf() * TAU)
	mat.set_shader_parameter("pulse_speed", speed)
	halo.material = mat
	parent.add_child(halo)


## Continuous ambient emitter (NOT auto-freed — lives for the scene).
func _make_particles(kind: String) -> CPUParticles2D:
	var p := CPUParticles2D.new()
	p.emitting = true
	p.one_shot = false
	match kind:
		"leaves":
			p.amount = 6
			p.lifetime = 3.2
			p.position = Vector2(0.0, -42.0)
			p.direction = Vector2(1.0, 0.3)
			p.spread = 45.0
			p.gravity = Vector2(5.0, 10.0)
			p.initial_velocity_min = 8.0
			p.initial_velocity_max = 22.0
			p.scale_amount_min = 1.0
			p.scale_amount_max = 2.0
			p.color = Color(0.36, 0.30, 0.16, 0.7)
		"ash":
			p.amount = 10
			p.lifetime = 5.0
			p.direction = Vector2(0.2, 1.0)
			p.spread = 30.0
			p.gravity = Vector2(2.0, 7.0)
			p.initial_velocity_min = 4.0
			p.initial_velocity_max = 12.0
			p.scale_amount_min = 1.0
			p.scale_amount_max = 2.4
			p.color = Color(0.55, 0.53, 0.5, 0.45)
		"smoke":
			p.amount = 8
			p.lifetime = 2.6
			p.position = Vector2(0.0, -30.0)
			p.direction = Vector2(0.1, -1.0)
			p.spread = 18.0
			p.gravity = Vector2(2.0, -10.0)
			p.initial_velocity_min = 10.0
			p.initial_velocity_max = 24.0
			p.scale_amount_min = 2.0
			p.scale_amount_max = 5.0
			p.color = Color(0.16, 0.16, 0.15, 0.5)
		"fire":
			p.amount = 10
			p.lifetime = 0.7
			p.position = Vector2(0.0, -20.0)
			p.direction = Vector2(0.0, -1.0)
			p.spread = 22.0
			p.gravity = Vector2(0.0, -34.0)
			p.initial_velocity_min = 12.0
			p.initial_velocity_max = 30.0
			p.scale_amount_min = 1.5
			p.scale_amount_max = 3.0
			var fg := Gradient.new()
			fg.set_color(0, Color(0.93, 0.66, 0.2, 0.9))
			fg.set_color(1, Color(0.55, 0.12, 0.05, 0.0))
			p.color_ramp = fg
		"bubble":
			p.amount = 5
			p.lifetime = 1.1
			p.position = Vector2(0.0, -12.0)
			p.direction = Vector2(0.0, -1.0)
			p.spread = 14.0
			p.gravity = Vector2(0.0, -8.0)
			p.initial_velocity_min = 6.0
			p.initial_velocity_max = 14.0
			p.scale_amount_min = 1.0
			p.scale_amount_max = 2.0
			p.color = Color(0.42, 0.55, 0.2, 0.6)
	return p


# =============================================================================
# FOUNTAIN / WORLD GATE / AMBIENCE
# =============================================================================

## The cursed fountain — KEPT ART. Sits in the crooked Priest Court with a sickly soul-teal aura.
func _build_fountain() -> void:
	var body := StaticBody2D.new()
	body.name = "Fountain"
	body.position = grid_to_world(FOUNTAIN_CELL)
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	body.z_index = 2
	body.z_as_relative = false
	add_child(body)

	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = FOUNTAIN_RADIUS
	shape.shape = circle
	body.add_child(shape)

	# Soul-teal glow under the basin (drawn even if the sprite is missing).
	_add_glow(body, Vector2.ZERO, TEAL, FOUNTAIN_RADIUS + 8.0, 1.4)

	var sheet := _load_texture("res://assets/sprites/environment/town/fountain_idle_sheet.png")
	if sheet:
		var animated := AnimatedSprite2D.new()
		animated.sprite_frames = SpriteStrip.make_frames(sheet, 9, 6.0)
		animated.play("idle")
		body.add_child(animated)
		return
	var tex := _load_texture("res://assets/sprites/environment/town/fountain.png")
	if tex:
		var sprite := Sprite2D.new()
		sprite.texture = tex
		body.add_child(sprite)
	else:
		var draw := _FountainFallback.new()
		draw.radius = FOUNTAIN_RADIUS
		draw.palette = _palette()
		body.add_child(draw)


## The World Gate is decorative (sealed) — its props already render via PROPS; add a cold mist
## marker + a faint sealed glow so it reads as a dead threshold, no functional portal.
func _build_world_gate_decoration() -> void:
	var marker := Node2D.new()
	marker.name = "WorldGateSealed"
	marker.position = grid_to_world(WORLD_GATE_CELL)
	marker.z_index = -3
	marker.z_as_relative = false
	marker.add_to_group("placeholder")
	marker.set_meta("placeholder", true)
	marker.set_meta("kind", "world_gate_sealed")
	marker.set_meta("replace_with", "world_gate_mist_exit")
	add_child(marker)
	_add_glow(marker, Vector2.ZERO, ELDRITCH.lightened(0.1), 30.0, 1.1)


## Drifting ash over the whole city — one wide emitter (spec §16 audio/atmosphere: "soft ash fall").
func _build_ambient_particles() -> void:
	var ash := _make_particles("ash")
	ash.name = "AshFall"
	ash.amount = 140
	ash.lifetime = 8.0
	ash.preprocess = 4.0
	ash.position = Vector2(0.0, -200.0)
	ash.emission_shape = CPUParticles2D.EMISSION_SHAPE_RECTANGLE
	ash.emission_rect_extents = Vector2(TOWN_RECT.size.x * 0.5, TOWN_RECT.size.y * 0.5)
	ash.z_index = 6
	ash.z_as_relative = false
	add_child(ash)


# =============================================================================
# HELPERS
# =============================================================================

func _set_ground(cell: Vector2i, gid: int, prio: int) -> void:
	if cell.x < GRID_MIN.x or cell.x > GRID_MAX.x or cell.y < GRID_MIN.y or cell.y > GRID_MAX.y:
		return
	if _ground_prio.get(cell, -1) >= prio:
		return
	_ground[cell] = gid
	_ground_prio[cell] = prio


func _set_wall(cell: Vector2i, mat: int, height: float) -> void:
	_wall_cells[cell] = [mat, height]


## Deterministic 0..1 hash for rough edges / scatter (no RNG so rebuilds are identical).
func _cell_noise(cell: Vector2i) -> float:
	var h := int(cell.x * 374761393 + cell.y * 668265263)
	h = (h ^ (h >> 13)) * 1274126177
	h = h ^ (h >> 16)
	return float(absi(h) % 10000) / 10000.0


func _rect_cells(r: Rect2i) -> Array:
	var out: Array = []
	for x in range(r.position.x, r.position.x + r.size.x):
		for y in range(r.position.y, r.position.y + r.size.y):
			out.append(Vector2i(x, y))
	return out


func _rect_has(r: Rect2i, c: Vector2i) -> bool:
	return c.x >= r.position.x and c.x < r.position.x + r.size.x \
		and c.y >= r.position.y and c.y < r.position.y + r.size.y


func _in_any_gate(c: Vector2i) -> bool:
	for g: Rect2i in GATES:
		if _rect_has(g, c):
			return true
	return false


func _in_any_breach(c: Vector2i) -> bool:
	for b: Rect2i in RAMPART_BREACHES:
		if _rect_has(b, c):
			return true
	return false


func _fill_rect(r: Rect2i, gid: int, prio: int) -> void:
	for c: Vector2i in _rect_cells(r):
		_set_ground(c, gid, prio)


func _fill_poly(poly: Array, gid: int, prio: int) -> void:
	var minx := 9999
	var miny := 9999
	var maxx := -9999
	var maxy := -9999
	for p: Vector2i in poly:
		minx = mini(minx, p.x); miny = mini(miny, p.y)
		maxx = maxi(maxx, p.x); maxy = maxi(maxy, p.y)
	var pf := PackedVector2Array()
	for p: Vector2i in poly:
		pf.append(Vector2(p))
	for x in range(minx, maxx + 1):
		for y in range(miny, maxy + 1):
			if Geometry2D.is_point_in_polygon(Vector2(x, y), pf):
				_set_ground(Vector2i(x, y), gid, prio)


## Door cells along one side of a footprint (grid). door_center is grid x (N/S) or grid y (E/W).
func _opening_cells(r: Rect2i, side: String, center: int, width: int) -> Array:
	var tx0 := r.position.x
	var ty0 := r.position.y
	var tx1 := tx0 + r.size.x - 1
	var ty1 := ty0 + r.size.y - 1
	var cells: Array = []
	var start := center - int(floor(width / 2.0))
	if side == "N" or side == "S":
		var ty := ty0 if side == "N" else ty1
		for i in range(width):
			cells.append(Vector2i(clampi(start + i, tx0, tx1), ty))
	else:
		var tx := tx0 if side == "W" else tx1
		for i in range(width):
			cells.append(Vector2i(tx, clampi(start + i, ty0, ty1)))
	return cells


func _filler_mat(kind: String) -> int:
	match kind:
		"burned_home", "collapsed_home", "butcher_ruin", "scriptorium_ruin":
			return Mat.CHARRED
		"shed", "leaning_house", "warehouse", "lower_storehouse", "caretaker_house":
			return Mat.DARK_WOOD
		_:
			return Mat.STONE


func _npc_role(role: String) -> int:
	# TownNpc.Role { GENERIC, PRIEST, CLASS_TRAINER, VENDOR, BANKER }
	match role:
		"PRIEST": return 1
		"CLASS_TRAINER": return 2
		"VENDOR": return 3
		"BANKER": return 4
		_: return 0


func _load_texture(path: String) -> Texture2D:
	if ResourceLoader.exists(path):
		return load(path) as Texture2D
	return null


## Wall material → [top (sunlit), face (shadowed south), edge (top highlight)].
func _mat_colors(mat: int) -> Array:
	match mat:
		Mat.DARK_WOOD:
			return [UMBER.lightened(0.12), UMBER.darkened(0.45), TAUPE.darkened(0.2)]
		Mat.COAL_STONE:
			return [IRON.lightened(0.05), ABYSS, ASH.darkened(0.25)]
		Mat.CATHEDRAL:
			return [ASH.darkened(0.05), IRON.darkened(0.2), GOLD.darkened(0.1)]
		Mat.COLD_STONE:
			return [Color("36404a"), Color("141a22"), VBLUE.lightened(0.2)]
		Mat.RAMPART:
			return [ASH.darkened(0.1), IRON, ASH.lightened(0.1)]
		Mat.CHARRED:
			return [IRON.darkened(0.3), ABYSS, BLOOD.darkened(0.2)]
		_:  # STONE
			return [IRON.lightened(0.12), ABYSS.lightened(0.04), ASH.darkened(0.1)]


## G style → {fill, seam, fleck, chance} resolved for the ground layer.
func _ground_styles() -> Dictionary:
	return {
		G.MUD: {"fill": UMBER.darkened(0.2), "seam": ABYSS, "fleck": UMBER.darkened(0.35), "chance": 0.18},
		G.MUD_ASH: {"fill": Color("352c25"), "seam": ABYSS, "fleck": ASH.darkened(0.2), "chance": 0.2},
		G.COBBLE_DARK: {"fill": Color("2b2f2e"), "seam": ABYSS, "fleck": ASH.darkened(0.3), "chance": 0.22},
		G.COBBLE_BROKEN: {"fill": Color("33352f"), "seam": ABYSS, "fleck": UMBER.darkened(0.2), "chance": 0.28},
		G.COBBLE_WET: {"fill": Color("232a2c"), "seam": ABYSS, "fleck": VBLUE.lightened(0.1), "chance": 0.12},
		G.COBBLE_PROC: {"fill": ASH.darkened(0.05), "seam": IRON, "fleck": GOLD.darkened(0.2), "chance": 0.1},
		G.COBBLE_MARKET: {"fill": Color("4a443c"), "seam": IRON, "fleck": RUST.darkened(0.2), "chance": 0.14},
		G.COBBLE_COAL: {"fill": ABYSS.lightened(0.07), "seam": ABYSS, "fleck": IRON.lightened(0.1), "chance": 0.3},
		G.COBBLE_COLD: {"fill": Color("2a3138"), "seam": Color("12171c"), "fleck": VBLUE.lightened(0.15), "chance": 0.16},
		G.COBBLE_NARROW: {"fill": IRON.lightened(0.06), "seam": ABYSS, "fleck": ASH.darkened(0.3), "chance": 0.2},
		G.GRAVE_PATH: {"fill": ASH.darkened(0.18), "seam": IRON, "fleck": BONE.darkened(0.1), "chance": 0.18},
		G.OLD_STONE: {"fill": Color("3e3a33"), "seam": IRON, "fleck": GOLD.darkened(0.3), "chance": 0.12},
		G.CIVIC: {"fill": IRON.lightened(0.1), "seam": ABYSS, "fleck": BLOOD.lightened(0.05), "chance": 0.16},
		G.PLAZA: {"fill": ASH.darkened(0.1), "seam": IRON, "fleck": ASH.lightened(0.1), "chance": 0.1},
		G.ASH_GRASS: {"fill": Color("353a2d"), "seam": Color("23271c"), "fleck": Color("4a5238"), "chance": 0.3},
		G.BLOOD_GROUND: {"fill": UMBER.darkened(0.15), "seam": ABYSS, "fleck": BLOOD, "chance": 0.26},
		G.INT_WOOD: {"fill": UMBER.lightened(0.06), "seam": UMBER.darkened(0.4), "chance": 0.0, "planks": true},
		G.INT_STONE: {"fill": ASH.darkened(0.12), "seam": IRON, "fleck": ASH.lightened(0.05), "chance": 0.1},
		G.INT_COLD: {"fill": Color("3a4048"), "seam": Color("181d24"), "fleck": VBLUE.lightened(0.2), "chance": 0.1},
		G.INT_COAL: {"fill": ABYSS.lightened(0.06), "seam": ABYSS, "fleck": SULFUR.darkened(0.3), "chance": 0.12},
		G.ELDRITCH_GROUND: {"fill": ELDRITCH.lightened(0.06), "seam": ABYSS, "fleck": VIOLET, "chance": 0.18},
	}


func _palette() -> Dictionary:
	return SanctuaryPropsScript.default_palette()


# =============================================================================
# INNER DRAW LAYERS
# =============================================================================

## Ground renderer: dead-ground base (with coarse variation), then each special cell as a tile.
class _GroundLayer extends Node2D:
	const TILE := 32.0
	var town_rect: Rect2
	var cells: Dictionary = {}
	var stairs: Dictionary = {}
	var styles: Dictionary = {}

	func _draw() -> void:
		# Dead muddy-grey base for the whole town + a coarse checker so flat color reads as ground.
		var base := Color(0.16, 0.16, 0.14)
		draw_rect(town_rect, base, true)
		var step := 96.0
		var y := town_rect.position.y
		var ry := 0
		while y < town_rect.position.y + town_rect.size.y:
			var x := town_rect.position.x
			var rx := 0
			while x < town_rect.position.x + town_rect.size.x:
				if (rx + ry) % 2 == 0:
					draw_rect(Rect2(x, y, step, step), base.darkened(0.12), true)
				x += step; rx += 1
			y += step; ry += 1

		for cell: Vector2i in cells:
			_draw_cell(cell, styles.get(cells[cell], {}))
		for cell: Vector2i in stairs:
			_draw_stair_cell(cell)

	func _draw_cell(cell: Vector2i, style: Dictionary) -> void:
		if style.is_empty():
			return
		var o := Vector2(cell) * TILE
		draw_rect(Rect2(o, Vector2(TILE, TILE)), style["fill"], true)
		var seam: Color = style.get("seam", style["fill"])
		var seam_c := Color(seam.r, seam.g, seam.b, 0.4)
		if style.get("planks", false):
			draw_line(o, o + Vector2(0.0, TILE), seam_c, 1.0)
			draw_line(o + Vector2(0.0, TILE * 0.5), o + Vector2(TILE, TILE * 0.5), seam_c, 1.0)
		else:
			draw_rect(Rect2(o, Vector2(TILE, TILE)), seam_c, false, 1.0)
		var chance: float = style.get("chance", 0.0)
		if chance > 0.0 and style.has("fleck") and _noise(cell) < chance:
			var fp := o + Vector2(8.0 + _noise(cell + Vector2i(5, 9)) * 16.0, 8.0 + _noise(cell + Vector2i(2, 7)) * 16.0)
			draw_circle(fp, 2.0, style["fleck"])

	func _draw_stair_cell(cell: Vector2i) -> void:
		var o := Vector2(cell) * TILE
		draw_rect(Rect2(o, Vector2(TILE, TILE)), Color("47443b"), true)
		draw_line(o + Vector2(0.0, 6.0), o + Vector2(TILE, 6.0), Color("23211c"), 2.0)
		draw_line(o + Vector2(0.0, 20.0), o + Vector2(TILE, 20.0), Color("23211c"), 2.0)

	func _noise(cell: Vector2i) -> float:
		var h := int(cell.x * 374761393 + cell.y * 668265263)
		h = (h ^ (h >> 13)) * 1274126177
		h = h ^ (h >> 16)
		return float(absi(h) % 10000) / 10000.0


## Oblique raised-wall renderer (Hammerwatch look): lifted sunlit top + shadowed south face.
class _WallLayer extends Node2D:
	var records: Array = []

	func _draw() -> void:
		for rec: Dictionary in records:
			var rect: Rect2 = rec["rect"]
			var h: float = rec["h"]
			var face_c: Color = rec["face"]
			var top := Rect2(rect.position - Vector2(0.0, h), rect.size)
			var face := Rect2(rect.position + Vector2(0.0, rect.size.y - h), Vector2(rect.size.x, h))
			draw_rect(Rect2(rect.position + Vector2(0.0, rect.size.y), Vector2(rect.size.x, 5.0)), Color(0, 0, 0, 0.22))
			draw_rect(face, face_c)
			draw_rect(Rect2(face.position + Vector2(0.0, h - 3.0), Vector2(face.size.x, 3.0)), face_c.darkened(0.35))
			draw_rect(top, rec["top"])
			draw_rect(Rect2(top.position, Vector2(top.size.x, 3.0)), rec["edge"])
			var crease_y := top.position.y + top.size.y
			draw_line(Vector2(top.position.x, crease_y), Vector2(top.position.x + top.size.x, crease_y), face_c.darkened(0.2), 1.0)


## Additive glow halo drawn as soft concentric circles (the glow.gdshader breathes its alpha).
class _GlowHalo extends Node2D:
	var glow_color: Color = Color(1, 0.85, 0.45)
	var radius: float = 16.0

	func _draw() -> void:
		draw_circle(Vector2.ZERO, radius, Color(glow_color.r, glow_color.g, glow_color.b, 0.16))
		draw_circle(Vector2.ZERO, radius * 0.66, Color(glow_color.r, glow_color.g, glow_color.b, 0.28))
		draw_circle(Vector2.ZERO, radius * 0.33, Color(glow_color.r, glow_color.g, glow_color.b, 0.4))


## Drawn fallback fountain (only used if the kept sprite is missing).
class _FountainFallback extends Node2D:
	var radius: float = 64.0
	var palette: Dictionary = {}

	func _draw() -> void:
		draw_circle(Vector2.ZERO, radius + 4.0, palette["iron"])
		draw_circle(Vector2.ZERO, radius - 4.0, palette["stone_dark"])
		draw_circle(Vector2.ZERO, radius - 12.0, palette["teal"].darkened(0.2))
		draw_circle(Vector2.ZERO, 14.0, palette["bone"].darkened(0.1))
		draw_circle(Vector2.ZERO, 8.0, palette["teal"])
