## Sanctuary — the safe-hub city the player enters when entering the world.
##
## Fully client-local (OfflineArena subclass, like Practice): no server, no
## prediction. The Arena portal on the south dais is what dials the game server
## and moves the player into the authoritative Arena.
##
## ============================================================================
## REDESIGN (vast walled city, code-generated placeholders)
## ============================================================================
## This is a large Tibia-style walled city you can walk through AND enter the
## buildings of, rendered in a 3/4 oblique top-down look (Hammerwatch / Heroes
## of Hammerwatch): walls are drawn as raised blocks with a lit top face and a
## shadowed south "front" face, and a couple of districts sit on RAISED TERRACES
## reached by walkable stair ramps.
##
## EVERYTHING here is a CODE-GENERATED PLACEHOLDER (no PNGs) except the three
## art pieces the design keeps: the Fountain, the NPCs, and the Arena Portal.
## The whole city is data-driven from the tables below so it is easy to author
## and, later, to swap for real art.
##
## ---- HOW TO REPLACE PLACEHOLDERS WITH REAL ART ----------------------------
## Every placeholder element is tagged so you can find it in the running scene:
##   * grouped under the "placeholder" node group, and
##   * carrying meta: `placeholder=true`, `replace_with="<asset hint>"`,
##     plus geometry meta (`footprint`, `kind`, …).
## The scene tree mirrors the tables: `World/Buildings/<Key>`, `World/Props/*`,
## `World/Terraces/*`, `World/Stairs/*`, `Ground` (floor), `WallVisuals`,
## `CityColliders` (the solid grid). To drop in real assets: pick the slot node,
## read its meta, and replace its drawn placeholder with your Sprite2D/tileset at
## the same transform. The collision grid (`CityColliders`) is independent of the
## visuals, so swapping art never changes where walls block.
##
## Layout + districts are documented in docs/design/sanctuary-layout.md (system
## of record) and follow docs/design/SANCTUARY_STYLEGUIDE.md.
extends OfflineArena

const NPC_SCENE: PackedScene = preload("res://scenes/shared/npc/npc.tscn")
const PORTAL_SCENE: PackedScene = preload("res://scenes/shared/portal/portal.tscn")
## Reused confirm modal for the priest's church sacrifice prompt.
const ConfirmDialogScene: PackedScene = preload("res://scenes/client/menus/components/confirm_dialog.tscn")

## The three KEPT art pieces live here (fountain + portal). NPC art is in NPC_TEXTURE_DIR.
## All other town PNGs (buildings, floor tiles, old props) were removed in the redesign.
const TOWN_TEXTURE_DIR := "res://assets/sprites/environment/town/"
const NPC_TEXTURE_DIR := "res://assets/sprites/npcs/"

# --- Style-guide palette (docs/design/SANCTUARY_STYLEGUIDE.md) ---------------------
const GRASS_COLOR := Color("70b94a")        # Meadow Green
const GRASS_COLOR_ALT := Color("6aae45")    # checker variation
const CLOVER_COLOR := Color("4fa33d")       # Clover Green
const COBBLE_COLOR := Color("bfaf94")       # Warm Stone (roads)
const COBBLE_SEAM := Color("a3937a")        # cobble seam / edge
const PLAZA_COLOR := Color("cdbd9f")        # lighter plaza stone
const WOOD_FLOOR := Color("b8793a")         # Honey Brown (interiors)
const WOOD_FLOOR_ALT := Color("a96d34")
const STONE_FLOOR := Color("d8cdb6")        # pale stone interior / terrace top
const STONE_FLOOR_ALT := Color("cabd9f")
const WATER_COLOR := Color("62c9c1")        # Soft Teal
const WATER_EDGE := Color("8fded6")
const STAIR_COLOR := Color("c7b89a")        # stair ramp
const STAIR_SEAM := Color("9b8b6e")

const CREAM := Color("f7e7c4")              # Sanctuary Cream (plaster top)
const CLOUD_WHITE := Color("fffbef")        # Cloud White (stone top)
const HONEY := Color("b8793a")              # timber beams
const HONEY_DARK := Color("8a5a2b")
const WARM_STONE := Color("bfaf94")
const STONE_DARK := Color("8d7f68")
const PLASTER_FACE := Color("c9a86f")       # shadowed cream

# --- Tiles / dimensions -----------------------------------------------------------
const TILE := 32.0                          # grid cell (matches 32 px player sprite)
const WALL_H_BUILDING := 28.0               # oblique wall face height (taller = stronger 3/4 read)
const WALL_H_RAMPART := 36.0
const WALL_H_CLIFF := 20.0                  # raised-terrace edge

## Wall materials → (top color, face color). Roofs are intentionally absent so the
## interiors are visible from above (you walk in through the door).
enum Mat { STONE, PLASTER, TIMBER, RAMPART, CLIFF }

## Interior / ground floor types.
enum FloorType { NONE = -1, COBBLE, PLAZA, WOOD, STONE, RUG }

# --- City bounds ------------------------------------------------------------------
## Hard boundary (OfflineArena builds walls here). A grass margin sits between the
## decorative rampart and this edge.
const TOWN_RECT := Rect2(-1856.0, -1856.0, 3712.0, 3712.0)
const SPAWN_POS := Vector2(0.0, 192.0)      # south rim of the fountain plaza
const FOUNTAIN_POS := Vector2(0.0, 0.0)
const FOUNTAIN_RADIUS := 64.0
const PLAZA_CENTER := Vector2.ZERO
const PLAZA_RADIUS := 304.0
const PORTAL_POS := Vector2(0.0, 1280.0)

# =============================================================================
# CITY DATA  (everything below is a placeholder authored in tile-aligned px)
# =============================================================================

## Cobble roads / courts / squares (FloorType.COBBLE unless noted). Tile-aligned.
const ROADS: Array[Dictionary] = [
	{"rect": Rect2(-64.0, -1024.0, 128.0, 2112.0)},     # Grand Avenue (N–S: cathedral → dais)
	{"rect": Rect2(-1696.0, -64.0, 3392.0, 128.0)},     # Market/Guild Street (E–W: west gate → east gate)
	{"rect": Rect2(-192.0, -1184.0, 384.0, 160.0)},     # Cathedral forecourt (foot of the stairs)
	{"rect": Rect2(-1344.0, -320.0, 768.0, 640.0)},     # Guild Court
	{"rect": Rect2(768.0, -288.0, 640.0, 576.0), "type": FloorType.PLAZA},  # Market Square
	{"rect": Rect2(640.0, -576.0, 128.0, 512.0)},       # Bank connector
	{"rect": Rect2(-896.0, 832.0, 256.0, 96.0)},        # Inn approach
]

## Decorative reflecting pools (FloorType water; no collider — shallow, walkable).
const POOLS: Array[Dictionary] = [
	{"rect": Rect2(-1568.0, 1216.0, 256.0, 192.0)},     # SW garden pool
	{"rect": Rect2(1280.0, -1440.0, 224.0, 192.0)},     # NE garden pool
]

## Buildings & terraces. Each is a tile-aligned enclosure (perimeter walls + a
## door/stair gap). `floor` fills the interior; FloorType.NONE leaves it open
## (terraces are open platforms — their interior is the raised stone top).
## `openings`: {side: "N"/"S"/"E"/"W", center: world-coord-along-side, width: tiles}.
const STRUCTURES: Array[Dictionary] = [
	# --- North: Cathedral on a raised terrace ---------------------------------
	{
		"key": "cathedral_terrace", "kind": "terrace",
		"rect": Rect2(-416.0, -1664.0, 832.0, 512.0),
		"material": Mat.CLIFF, "height": WALL_H_CLIFF, "floor": FloorType.STONE,
		"openings": [{"side": "S", "center": 0.0, "width": 6}],
		"replace_with": "cathedral_terrace_platform",
	},
	{
		"key": "church", "name": "Church of the Dawn", "kind": "building",
		"rect": Rect2(-288.0, -1600.0, 576.0, 384.0),
		"material": Mat.STONE, "height": WALL_H_BUILDING, "floor": FloorType.STONE,
		"openings": [{"side": "S", "center": 0.0, "width": 4}],
		"plaque": true, "replace_with": "church_building",
		"interior_props": [
			{"kind": "altar", "pos": Vector2(0.0, -1520.0)},
			{"kind": "candle", "pos": Vector2(-64.0, -1520.0)},
			{"kind": "candle", "pos": Vector2(64.0, -1520.0)},
			{"kind": "pew", "pos": Vector2(-96.0, -1392.0)},
			{"kind": "pew", "pos": Vector2(96.0, -1392.0)},
			{"kind": "pew", "pos": Vector2(-96.0, -1328.0)},
			{"kind": "pew", "pos": Vector2(96.0, -1328.0)},
		],
	},
	# --- West: Guild Quarter --------------------------------------------------
	{
		"key": "warriors_guild", "name": "Warriors' Guild", "kind": "building",
		"rect": Rect2(-1280.0, -672.0, 384.0, 352.0),
		"material": Mat.STONE, "height": WALL_H_BUILDING, "floor": FloorType.STONE,
		"openings": [{"side": "S", "center": -1088.0, "width": 4}],
		"plaque": true, "replace_with": "warriors_guild_building",
		"interior_props": [
			{"kind": "weapon_rack", "pos": Vector2(-1216.0, -608.0)},
			{"kind": "training_dummy", "pos": Vector2(-960.0, -608.0)},
			{"kind": "table", "pos": Vector2(-1088.0, -512.0)},
		],
	},
	{
		"key": "mages_guild", "name": "Mages' Guild", "kind": "building",
		"rect": Rect2(-1664.0, -672.0, 320.0, 352.0),
		"material": Mat.STONE, "height": WALL_H_BUILDING, "floor": FloorType.STONE,
		"openings": [{"side": "S", "center": -1504.0, "width": 4}],
		"plaque": true, "replace_with": "mages_guild_building",
		"interior_props": [
			{"kind": "bookshelf", "pos": Vector2(-1600.0, -608.0)},
			{"kind": "bookshelf", "pos": Vector2(-1408.0, -608.0)},
			{"kind": "table", "pos": Vector2(-1504.0, -448.0)},
		],
	},
	{
		"key": "rogues_guild", "name": "Rogues' Guild", "kind": "building",
		"rect": Rect2(-1280.0, 320.0, 384.0, 352.0),
		"material": Mat.STONE, "height": WALL_H_BUILDING, "floor": FloorType.STONE,
		"openings": [{"side": "N", "center": -1088.0, "width": 4}],
		"plaque": true, "replace_with": "rogues_guild_building",
		"interior_props": [
			{"kind": "crate", "pos": Vector2(-1216.0, 608.0)},
			{"kind": "barrel", "pos": Vector2(-960.0, 608.0)},
			{"kind": "table", "pos": Vector2(-1088.0, 512.0)},
		],
	},
	# --- Northeast: Bank ------------------------------------------------------
	{
		"key": "bank", "name": "Bank of the Sanctuary", "kind": "building",
		"rect": Rect2(512.0, -960.0, 384.0, 384.0),
		"material": Mat.STONE, "height": WALL_H_BUILDING, "floor": FloorType.STONE,
		"openings": [{"side": "S", "center": 704.0, "width": 4}],
		"plaque": true, "replace_with": "bank_building",
		"interior_props": [
			{"kind": "counter", "pos": Vector2(704.0, -624.0)},
			{"kind": "chest", "pos": Vector2(608.0, -880.0)},
			{"kind": "chest", "pos": Vector2(800.0, -880.0)},
		],
	},
	# --- East: Market Row -----------------------------------------------------
	{
		"key": "potion_shop", "name": "The Bubbling Flask", "kind": "building",
		"rect": Rect2(928.0, -576.0, 352.0, 320.0),
		"material": Mat.TIMBER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "S", "center": 1104.0, "width": 4}],
		"plaque": true, "replace_with": "potion_shop_building",
		"interior_props": [
			{"kind": "counter", "pos": Vector2(1104.0, -304.0)},
			{"kind": "shelf", "pos": Vector2(992.0, -512.0)},
			{"kind": "shelf", "pos": Vector2(1216.0, -512.0)},
		],
	},
	{
		"key": "equipment_shop", "name": "Hammer & Hilt", "kind": "building",
		"rect": Rect2(928.0, 256.0, 352.0, 320.0),
		"material": Mat.TIMBER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "N", "center": 1104.0, "width": 4}],
		"plaque": true, "replace_with": "equipment_shop_building",
		"interior_props": [
			{"kind": "counter", "pos": Vector2(1104.0, 528.0)},
			{"kind": "weapon_rack", "pos": Vector2(992.0, 320.0)},
			{"kind": "shelf", "pos": Vector2(1216.0, 320.0)},
		],
	},
	# --- Southwest: Inn -------------------------------------------------------
	{
		"key": "inn", "name": "The Resting Lantern", "kind": "building",
		"rect": Rect2(-1344.0, 704.0, 448.0, 384.0),
		"material": Mat.TIMBER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "E", "center": 896.0, "width": 4}],
		"plaque": true, "replace_with": "inn_building",
		"interior_props": [
			{"kind": "counter", "pos": Vector2(-1280.0, 768.0)},
			{"kind": "table", "pos": Vector2(-1088.0, 832.0)},
			{"kind": "table", "pos": Vector2(-1024.0, 960.0)},
			{"kind": "barrel", "pos": Vector2(-1280.0, 1024.0)},
			{"kind": "barrel", "pos": Vector2(-1216.0, 1024.0)},
		],
	},
	# --- Residential cottages -------------------------------------------------
	{
		"key": "house_north", "kind": "building",
		"rect": Rect2(-832.0, -1024.0, 256.0, 224.0),
		"material": Mat.PLASTER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "S", "center": -704.0, "width": 2}],
		"replace_with": "cottage",
		"interior_props": [
			{"kind": "bed", "pos": Vector2(-768.0, -960.0)},
			{"kind": "table", "pos": Vector2(-640.0, -896.0)},
		],
	},
	{
		"key": "house_se_a", "kind": "building",
		"rect": Rect2(512.0, 768.0, 256.0, 224.0),
		"material": Mat.PLASTER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "W", "center": 880.0, "width": 2}],
		"replace_with": "cottage",
		"interior_props": [
			{"kind": "bed", "pos": Vector2(704.0, 832.0)},
			{"kind": "table", "pos": Vector2(608.0, 928.0)},
		],
	},
	{
		"key": "house_se_b", "kind": "building",
		"rect": Rect2(960.0, 768.0, 256.0, 224.0),
		"material": Mat.PLASTER, "height": WALL_H_BUILDING, "floor": FloorType.WOOD,
		"openings": [{"side": "W", "center": 880.0, "width": 2}],
		"replace_with": "cottage",
		"interior_props": [
			{"kind": "bed", "pos": Vector2(1152.0, 832.0)},
			{"kind": "table", "pos": Vector2(1056.0, 928.0)},
		],
	},
	# --- South: Portal Dais (raised terrace) ----------------------------------
	{
		"key": "portal_dais", "kind": "terrace",
		"rect": Rect2(-256.0, 1088.0, 512.0, 384.0),
		"material": Mat.CLIFF, "height": WALL_H_CLIFF, "floor": FloorType.STONE,
		"openings": [{"side": "N", "center": 0.0, "width": 6}],
		"replace_with": "portal_dais_platform",
	},
]

## Stair ramps (walkable placeholders, NO collider): bridge a terrace top to the
## ground through the terrace's wall gap. Tagged for future multi-floor logic.
const STAIRS: Array[Dictionary] = [
	{"rect": Rect2(-96.0, -1184.0, 192.0, 96.0), "dir": "S"},   # Cathedral grand stairs
	{"rect": Rect2(-96.0, 1024.0, 192.0, 96.0), "dir": "N"},    # Portal dais stairs
]

## NPCs — KEPT ART (assets/sprites/npcs/). Placed inside their themed buildings.
const NPCS: Array[Dictionary] = [
	{
		"key": "priest", "name": "Father Aldric", "title": "High Priest of the Dawn",
		"role": TownNpc.Role.PRIEST, "pos": Vector2(0.0, -1312.0), "color": Color("ffd36a"),
		"dialog": "Welcome to the Sanctuary, child of the Dawn. When the altar is consecrated you will spend your hard-won Glory here — strengthening your account's skill tree so every hero you raise starts mightier. Return soon.",
	},
	{
		"key": "warrior_trainer", "name": "Master Brandt", "title": "Warriors' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER, "pos": Vector2(-1088.0, -432.0), "color": Color("c65b4a"),
		"dialog": "The Warriors' Guild forges the front line — shield, steel, and stubbornness. Class training opens when the guild ledgers arrive. Until then, keep your blade sharp in the Arena.",
	},
	{
		"key": "mage_trainer", "name": "Archmagus Elowen", "title": "Mages' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER, "pos": Vector2(-1504.0, -432.0), "color": Color("3c8ccf"),
		"dialog": "Magic is patience given form. The Mages' Guild will tutor those with the spark — once the sanctum is attuned. Mind the fountain; its water remembers every spell cast near it.",
	},
	{
		"key": "rogue_trainer", "name": "Shade Vesper", "title": "Rogues' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER, "pos": Vector2(-1088.0, 432.0), "color": Color("4fa33d"),
		"dialog": "You found our hall — that's lesson one passed. The Rogues' Guild deals in speed, shadows, and exits. Training begins when the contracts are signed. Don't ask who signs them.",
	},
	{
		"key": "potion_vendor", "name": "Tilda Brewbloom", "title": "Alchemist",
		"role": TownNpc.Role.VENDOR, "pos": Vector2(1104.0, -400.0), "color": Color("bda7e8"),
		"dialog": "Potions, tonics, and brews that only sometimes hiss! The Bubbling Flask opens its shelves once the first caravan arrives. Come back thirsty, adventurer.",
	},
	{
		"key": "equipment_vendor", "name": "Garrick Forgehand", "title": "Outfitter",
		"role": TownNpc.Role.VENDOR, "pos": Vector2(1104.0, 400.0), "color": Color("b8793a"),
		"dialog": "Hammer & Hilt — finest arms and armor on this side of the portal. The forge is still heating, but soon you'll trade for gear worth dying a little less in.",
	},
	{
		"key": "banker", "name": "Goldwin Ledger", "title": "Bankmaster",
		"role": TownNpc.Role.BANKER, "pos": Vector2(704.0, -700.0), "color": Color("e7a93c"),
		"dialog": "The Bank of the Sanctuary: your valuables outlive your heroes here. Vault deposits open with the next charter. Until then, try not to carry everything into the Arena at once.",
	},
]

## Outdoor props. Generic kinds (bench/barrel/crate/stall/table/counter/...) are
## drawn as oblique boxes; specials (tree/lantern/well/flowerbed/banner/sign/
## notice_board) have bespoke placeholder art. `solid` props get a collider.
const PROPS: Array[Dictionary] = [
	# Plaza ring: benches + lanterns + a notice board + a well.
	{"kind": "notice_board", "pos": Vector2(232.0, -120.0)},
	{"kind": "well", "pos": Vector2(-232.0, 232.0)},
	{"kind": "bench", "pos": Vector2(-200.0, -150.0)},
	{"kind": "bench", "pos": Vector2(200.0, -150.0)},
	{"kind": "bench", "pos": Vector2(-200.0, 150.0)},
	{"kind": "bench", "pos": Vector2(200.0, 150.0)},
	# Market stalls in the market square.
	{"kind": "stall", "pos": Vector2(880.0, -200.0)},
	{"kind": "stall", "pos": Vector2(1296.0, -200.0)},
	{"kind": "stall", "pos": Vector2(880.0, 200.0)},
	{"kind": "stall", "pos": Vector2(1296.0, 200.0)},
	{"kind": "barrel", "pos": Vector2(1080.0, 200.0)},
	{"kind": "crate", "pos": Vector2(1128.0, 200.0)},
	# Signposts at the two avenue crossings.
	{"kind": "signpost", "pos": Vector2(160.0, -160.0)},
	{"kind": "signpost", "pos": Vector2(-1392.0, -160.0)},
	{"kind": "signpost", "pos": Vector2(1392.0, 160.0)},
	# Gate banners.
	{"kind": "banner", "pos": Vector2(-1712.0, -120.0)},
	{"kind": "banner", "pos": Vector2(-1712.0, 120.0)},
	{"kind": "banner", "pos": Vector2(1712.0, -120.0)},
	{"kind": "banner", "pos": Vector2(1712.0, 120.0)},
	# Garden trees (quadrant corners, away from buildings).
	{"kind": "tree", "pos": Vector2(-1456.0, -1424.0)},
	{"kind": "tree", "pos": Vector2(-1280.0, -1280.0)},
	{"kind": "tree", "pos": Vector2(-1536.0, -1120.0)},
	{"kind": "tree", "pos": Vector2(1456.0, -1424.0)},
	{"kind": "tree", "pos": Vector2(1280.0, -1120.0)},
	{"kind": "tree", "pos": Vector2(-1456.0, 1456.0)},
	{"kind": "tree", "pos": Vector2(-1216.0, 1392.0)},
	{"kind": "tree", "pos": Vector2(1456.0, 1456.0)},
	{"kind": "tree", "pos": Vector2(1232.0, 1312.0)},
	{"kind": "tree", "pos": Vector2(1488.0, 1216.0)},
	{"kind": "tree", "pos": Vector2(-512.0, 1376.0)},
	{"kind": "tree", "pos": Vector2(512.0, 1376.0)},
	# Flower beds.
	{"kind": "flowerbed", "pos": Vector2(-1376.0, -1280.0)},
	{"kind": "flowerbed", "pos": Vector2(1376.0, -1280.0)},
	{"kind": "flowerbed", "pos": Vector2(-1376.0, 1296.0)},
	{"kind": "flowerbed", "pos": Vector2(1360.0, 1376.0)},
	{"kind": "flowerbed", "pos": Vector2(-352.0, -1392.0)},
	{"kind": "flowerbed", "pos": Vector2(352.0, -1392.0)},
	{"kind": "flowerbed", "pos": Vector2(-160.0, -1120.0)},
	{"kind": "flowerbed", "pos": Vector2(160.0, -1120.0)},
	{"kind": "planter", "pos": Vector2(-120.0, 1120.0)},
	{"kind": "planter", "pos": Vector2(120.0, 1120.0)},
]

## Lantern posts auto-placed in pairs along the two avenues (see _build_props).
const LANTERN_AVENUE_STEP := 256.0
const LANTERN_OFFSET := 96.0

# --- Runtime ----------------------------------------------------------------------
var _wall_cells: Dictionary = {}            # Vector2i -> [Mat, height]
var _floor_ops: Array = []                  # draw ops for the ground layer
var _world: Node2D = null
var _fountain_has_visual := false

## Church sacrifice flow (priest interaction). Created on demand.
var _sacrifice_confirm = null               # ConfirmDialog instance (untyped — no class_name)
var _sacrifice_request: HTTPRequest = null
var _sacrifice_in_flight := false


func _configure() -> void:
	arena_rect = TOWN_RECT
	wall_thickness = 32.0


func _get_spawn_position() -> Vector2:
	return SPAWN_POS


func _populate() -> void:
	_world = Node2D.new()
	_world.name = "World"
	_world.z_index = -4                       # props/npcs/portal/fountain below the player (z 0)
	add_child(_world)

	_rasterize()                              # fill _wall_cells + _floor_ops from the tables
	_build_ground_layer()                     # z -20: floors, roads, interiors, stairs, pools
	_build_wall_visuals()                     # z -8: oblique raised walls
	_build_city_colliders()                   # solid grid: a collider on every wall cell
	_build_buildings_meta()                   # named replaceable slots + plaques + interior props
	_build_terrace_meta()
	_build_stairs_meta()
	_build_fountain()                         # KEEP sprite
	_build_npcs()                             # KEEP sprites
	_build_portal()                           # KEEP sprite
	_build_props()
	_build_safe_zone_badge()


## Town stays quiet — no peaceful-hub track is loaded yet.
func _start_music() -> void:
	pass


## All visuals live in dedicated child layers (Ground / WallVisuals / World), so
## the Sanctuary node itself draws nothing. (Overriding keeps OfflineArena._draw —
## its dark arena grid/border — from painting over the city.)
func _draw() -> void:
	pass


# =============================================================================
# RASTERIZE  (tables -> wall grid + floor draw ops)
# =============================================================================

func _rasterize() -> void:
	# Base ground beneath everything.
	_floor_ops.append({"op": "grass", "rect": TOWN_RECT})

	# Decorative rampart-enclosed lawn already grass; add the paved network on top.
	for road: Dictionary in ROADS:
		var ftype: int = road.get("type", FloorType.COBBLE)
		_floor_ops.append(_floor_op(road["rect"], ftype))

	# Fountain plaza (circle).
	_floor_ops.append({"op": "plaza_circle", "center": PLAZA_CENTER, "radius": PLAZA_RADIUS})

	for pool: Dictionary in POOLS:
		_floor_ops.append({"op": "water", "rect": pool["rect"]})

	# Rampart ring (city wall) with east + west gates.
	_rasterize_rampart()

	# Buildings & terraces.
	for s: Dictionary in STRUCTURES:
		_rasterize_structure(s)

	# Stair ramps (drawn last so they sit on top of the terrace edge).
	for st: Dictionary in STAIRS:
		_floor_ops.append({"op": "stair", "rect": st["rect"], "dir": st["dir"]})


## City rampart: a 2-tile-thick stone ring just inside the playable area, with a
## 4-tile gate cut into the east and west sides (where Market/Guild Street exits).
func _rasterize_rampart() -> void:
	var outer := 54                           # tile half-extent of the rampart's outer edge
	var inner := outer - 1                    # 2-tile thickness
	for t in range(-outer, outer + 1):
		# West / East walls (two columns each side).
		for col: int in [-outer, -inner, inner, outer]:
			var on_gate: bool = (absi(col) >= inner) and t >= -2 and t <= 1
			if not on_gate:
				_set_wall(Vector2i(col, t), Mat.RAMPART, WALL_H_RAMPART)
		# North / South walls (two rows each side); no gates (cathedral / dais back them).
		for row: int in [-outer, -inner, inner, outer]:
			_set_wall(Vector2i(t, row), Mat.RAMPART, WALL_H_RAMPART)


## Rasterize one enclosure: perimeter walls (minus the door/stair gaps) + an
## interior floor op. Records wall cells for both rendering and collision.
func _rasterize_structure(def: Dictionary) -> void:
	var rect: Rect2 = def["rect"]
	var tx0 := int(round(rect.position.x / TILE))
	var ty0 := int(round(rect.position.y / TILE))
	var tx1 := tx0 + int(round(rect.size.x / TILE)) - 1
	var ty1 := ty0 + int(round(rect.size.y / TILE)) - 1
	var mat: int = def.get("material", Mat.STONE)
	var height: float = def.get("height", WALL_H_BUILDING)
	var floor_type: int = def.get("floor", FloorType.NONE)

	# Cells freed by doors/stairs.
	var gaps: Dictionary = {}
	for o: Dictionary in def.get("openings", []):
		for cell: Vector2i in _opening_cells(tx0, ty0, tx1, ty1, o):
			gaps[cell] = true

	# Interior floor fill (covers the door threshold cells too).
	if floor_type != FloorType.NONE:
		var inner_rect := Rect2(
			Vector2(float(tx0 + 1), float(ty0 + 1)) * TILE,
			Vector2(float(tx1 - tx0 - 1), float(ty1 - ty0 - 1)) * TILE
		)
		_floor_ops.append(_floor_op(inner_rect, floor_type))
		# Threshold patch so each doorway reads as floor, not wall/grass.
		for cell: Vector2i in gaps:
			_floor_ops.append(_floor_op(Rect2(Vector2(cell) * TILE, Vector2(TILE, TILE)), floor_type))

	# Perimeter walls (skip the gaps).
	for tx in range(tx0, tx1 + 1):
		for ty in range(ty0, ty1 + 1):
			var is_border := tx == tx0 or tx == tx1 or ty == ty0 or ty == ty1
			if is_border and not gaps.has(Vector2i(tx, ty)):
				_set_wall(Vector2i(tx, ty), mat, height)


## Tile cells along one side of an enclosure covered by an opening.
func _opening_cells(tx0: int, ty0: int, tx1: int, ty1: int, o: Dictionary) -> Array:
	var cells: Array = []
	var side: String = o["side"]
	var width: int = int(o["width"])
	var center: float = o["center"]
	if side == "N" or side == "S":
		var cc := int(round(center / TILE))
		var ty := ty0 if side == "N" else ty1
		var start := cc - int(floor(width / 2.0))
		for i in range(width):
			cells.append(Vector2i(clampi(start + i, tx0, tx1), ty))
	else:
		var cr := int(round(center / TILE))
		var tx := tx0 if side == "W" else tx1
		var start := cr - int(floor(width / 2.0))
		for i in range(width):
			cells.append(Vector2i(tx, clampi(start + i, ty0, ty1)))
	return cells


func _set_wall(cell: Vector2i, mat: int, height: float) -> void:
	_wall_cells[cell] = [mat, height]


# =============================================================================
# BUILDERS — VISUALS
# =============================================================================

func _build_ground_layer() -> void:
	var ground := _GroundLayer.new()
	ground.name = "Ground"
	ground.z_index = -20
	ground.ops = _floor_ops
	ground.palette = _palette()
	add_child(ground)
	move_child(ground, 0)
	ground.queue_redraw()


func _build_wall_visuals() -> void:
	# Flatten the wall grid into draw records sorted north→south so southern wall
	# faces correctly overlap the walls behind them (the oblique look).
	var cells := _wall_cells.keys()
	cells.sort_custom(func(a: Vector2i, b: Vector2i) -> bool:
		return a.y < b.y if a.y != b.y else a.x < b.x)

	var records: Array = []
	for cell: Vector2i in cells:
		var entry: Array = _wall_cells[cell]
		var cols := _mat_colors(entry[0])
		records.append({
			"rect": Rect2(Vector2(cell) * TILE, Vector2(TILE, TILE)),
			"top": cols[0],
			"face": cols[1],
			"edge": cols[2],
			"h": entry[1],
		})

	var layer := _WallLayer.new()
	layer.name = "WallVisuals"
	layer.z_index = -8
	layer.records = records
	add_child(layer)
	layer.queue_redraw()


## One static collider per merged horizontal run of wall cells — guarantees a
## solid cell everywhere a wall is drawn, with far fewer shapes than per-cell.
func _build_city_colliders() -> void:
	var body := StaticBody2D.new()
	body.name = "CityColliders"
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	add_child(body)

	# Group wall cells by row.
	var rows: Dictionary = {}
	for cell: Vector2i in _wall_cells:
		if not rows.has(cell.y):
			rows[cell.y] = []
		rows[cell.y].append(cell.x)

	var count := 0
	for row_y: int in rows:
		var xs: Array = rows[row_y]
		xs.sort()
		var run_start: int = xs[0]
		var prev: int = xs[0]
		for i in range(1, xs.size() + 1):
			var is_break: bool = i == xs.size() or int(xs[i]) != prev + 1
			if is_break:
				_add_run_collider(body, run_start, prev, row_y)
				count += 1
				if i < xs.size():
					run_start = xs[i]
					prev = xs[i]
			else:
				prev = xs[i]
	print("[Sanctuary] %d wall cells -> %d colliders" % [_wall_cells.size(), count])


func _add_run_collider(body: StaticBody2D, tx_start: int, tx_end: int, ty: int) -> void:
	var width := float(tx_end - tx_start + 1) * TILE
	var shape := CollisionShape2D.new()
	shape.position = Vector2(
		(float(tx_start) + float(tx_end - tx_start + 1) * 0.5) * TILE,
		(float(ty) + 0.5) * TILE
	)
	var rect := RectangleShape2D.new()
	rect.size = Vector2(width, TILE)
	shape.shape = rect
	body.add_child(shape)


# =============================================================================
# BUILDERS — REPLACEABLE SLOTS / METADATA
# =============================================================================

## A named Marker2D per building so each is findable in the scene tree, carrying
## its footprint + replace hint, plus a name plaque and interior furniture.
func _build_buildings_meta() -> void:
	var container := Node2D.new()
	container.name = "Buildings"
	_world.add_child(container)

	var prop_body := StaticBody2D.new()
	prop_body.name = "InteriorProps"
	prop_body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	prop_body.collision_mask = 0
	_world.add_child(prop_body)

	for s: Dictionary in STRUCTURES:
		if s.get("kind", "building") != "building":
			continue
		var rect: Rect2 = s["rect"]
		var slot := Marker2D.new()
		slot.name = String(s["key"]).to_pascal_case()
		slot.position = rect.get_center()
		slot.add_to_group("placeholder")
		slot.set_meta("placeholder", true)
		slot.set_meta("kind", "building")
		slot.set_meta("footprint", rect)
		slot.set_meta("replace_with", s.get("replace_with", "building"))
		container.add_child(slot)

		if s.get("plaque", false):
			_add_plaque(slot, String(s.get("name", "")), rect.size.y)

		var interior_props: Array = s.get("interior_props", [])
		if not interior_props.is_empty():
			# A per-building visuals container at the origin (props use absolute
			# world coords), so each building's furniture is findable in the tree
			# under World/Buildings/<Key>Interior. Colliders stay on the flat body.
			var interior := Node2D.new()
			interior.name = slot.name + "Interior"
			container.add_child(interior)
			for ip: Dictionary in interior_props:
				_spawn_prop(interior, prop_body, ip["kind"], ip["pos"])


func _add_plaque(parent: Node2D, text: String, footprint_h: float) -> void:
	if text.is_empty():
		return
	var label := Label.new()
	label.text = text
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.offset_left = -160.0
	label.offset_right = 160.0
	label.offset_top = -footprint_h * 0.5 - 34.0
	label.offset_bottom = -footprint_h * 0.5 - 10.0
	label.add_theme_font_size_override("font_size", 15)
	label.add_theme_color_override("font_color", Color(1.0, 0.98, 0.88))
	label.add_theme_color_override("font_outline_color", Color(0.12, 0.1, 0.08))
	label.add_theme_constant_override("outline_size", 4)
	parent.add_child(label)


func _build_terrace_meta() -> void:
	var container := Node2D.new()
	container.name = "Terraces"
	_world.add_child(container)
	for s: Dictionary in STRUCTURES:
		if s.get("kind", "") != "terrace":
			continue
		var rect: Rect2 = s["rect"]
		var slot := Marker2D.new()
		slot.name = String(s["key"]).to_pascal_case()
		slot.position = rect.get_center()
		slot.add_to_group("placeholder")
		slot.set_meta("placeholder", true)
		slot.set_meta("kind", "terrace")
		slot.set_meta("footprint", rect)
		slot.set_meta("replace_with", s.get("replace_with", "terrace"))
		container.add_child(slot)


func _build_stairs_meta() -> void:
	var container := Node2D.new()
	container.name = "Stairs"
	_world.add_child(container)
	for i in range(STAIRS.size()):
		var st: Dictionary = STAIRS[i]
		var rect: Rect2 = st["rect"]
		var slot := Marker2D.new()
		slot.name = "Stair%d" % (i + 1)
		slot.position = rect.get_center()
		slot.add_to_group("placeholder")
		slot.set_meta("placeholder", true)
		slot.set_meta("kind", "stair")
		slot.set_meta("footprint", rect)
		slot.set_meta("replace_with", "stairs")
		# Stairs are walkable now; tagged for future client-side multi-floor logic.
		slot.set_meta("future", "elevation/floor-switch")
		container.add_child(slot)


# =============================================================================
# BUILDERS — KEPT ART (fountain, npcs, portal)
# =============================================================================

func _build_fountain() -> void:
	var body := StaticBody2D.new()
	body.name = "Fountain"
	body.position = FOUNTAIN_POS
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	body.z_index = 2                          # above the player so the basin reads as 3D
	_world.add_child(body)

	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = FOUNTAIN_RADIUS
	shape.shape = circle
	body.add_child(shape)

	var sheet := _load_texture(TOWN_TEXTURE_DIR + "fountain_idle_sheet.png")
	if sheet:
		var animated := AnimatedSprite2D.new()
		animated.sprite_frames = SpriteStrip.make_frames(sheet, 9, 6.0)
		animated.play("idle")
		body.add_child(animated)
		_fountain_has_visual = true
		return

	var texture := _load_texture(TOWN_TEXTURE_DIR + "fountain.png")
	if texture:
		var sprite := Sprite2D.new()
		sprite.texture = texture
		body.add_child(sprite)
		_fountain_has_visual = true
	else:
		# Drawn fallback if the kept art is ever missing.
		var draw := _Fountain.new()
		draw.radius = FOUNTAIN_RADIUS
		draw.palette = _palette()
		body.add_child(draw)


func _build_npcs() -> void:
	var container := Node2D.new()
	container.name = "NPCs"
	_world.add_child(container)

	for entry: Dictionary in NPCS:
		var npc := NPC_SCENE.instantiate() as TownNpc
		npc.name = String(entry["key"]).to_pascal_case()
		npc.position = entry["pos"]
		npc.npc_name = entry["name"]
		npc.npc_title = entry["title"]
		npc.role = entry["role"]
		npc.dialog_text = entry["dialog"]
		npc.placeholder_color = entry["color"]
		npc.texture_path = NPC_TEXTURE_DIR + String(entry["key"]) + ".png"
		# The priest opens the sacrifice confirm instead of the built-in info dialog.
		if entry["role"] == TownNpc.Role.PRIEST:
			npc.suppress_default_dialog = true
			npc.interacted.connect(_on_npc_interacted)
		container.add_child(npc)


func _build_portal() -> void:
	var portal := PORTAL_SCENE.instantiate() as Portal
	portal.name = "ArenaPortal"
	portal.position = PORTAL_POS
	portal.portal_name = "Arena Portal"
	portal.destination = Portal.Destination.ARENA
	portal.requires_connection = true
	portal.texture_path = TOWN_TEXTURE_DIR + "portal.png"
	portal.animation_sheet_path = TOWN_TEXTURE_DIR + "portal_idle_sheet.png"
	_world.add_child(portal)


# =============================================================================
# CHURCH SACRIFICE  (priest interaction)
# =============================================================================

## The priest was interacted with: open the sacrifice confirm prompt.
func _on_npc_interacted(npc: TownNpc) -> void:
	if npc == null or npc.role != TownNpc.Role.PRIEST:
		return
	if _sacrifice_in_flight:
		return
	if _sacrifice_confirm == null:
		_sacrifice_confirm = ConfirmDialogScene.instantiate()
		add_child(_sacrifice_confirm)
		_sacrifice_confirm.confirmed.connect(_on_sacrifice_confirmed)
	_sacrifice_confirm.show_confirm(
		"Sacrifice Character",
		"Sacrifice your character to the gods? This deletes it and converts your XP to Glory.",
		"Sacrifice",
		"Cancel"
	)


## Confirmed sacrifice: POST /api/character/sacrifice with the JWT auth header.
func _on_sacrifice_confirmed() -> void:
	if _sacrifice_in_flight:
		return
	var header := AuthManager.get_auth_header()
	if header.is_empty():
		push_warning("[Sanctuary] Cannot sacrifice: not authenticated")
		return

	_sacrifice_in_flight = true
	if _sacrifice_request == null:
		_sacrifice_request = HTTPRequest.new()
		add_child(_sacrifice_request)
	if _sacrifice_request.request_completed.is_connected(_on_sacrifice_completed):
		_sacrifice_request.request_completed.disconnect(_on_sacrifice_completed)
	_sacrifice_request.request_completed.connect(_on_sacrifice_completed)

	var url := AuthManager.api_base_url + "/api/character/sacrifice"
	var headers := ["Content-Type: application/json", header]
	var error := _sacrifice_request.request(url, headers, HTTPClient.METHOD_POST, "{}")
	if error != OK:
		_sacrifice_in_flight = false
		push_warning("[Sanctuary] Sacrifice request failed to start: %d" % error)


## Handle the sacrifice API response: on success clear the local character and route to
## character creation. The DB is authoritative; the local reset keeps the display clean.
func _on_sacrifice_completed(result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	_sacrifice_in_flight = false
	if _sacrifice_request and _sacrifice_request.request_completed.is_connected(_on_sacrifice_completed):
		_sacrifice_request.request_completed.disconnect(_on_sacrifice_completed)

	if result != HTTPRequest.RESULT_SUCCESS:
		push_warning("[Sanctuary] Sacrifice request failed: %d" % result)
		return

	if response_code == 200 or response_code == 204:
		# Character sacrificed: drop local character state and route to creation.
		GameManager.clear_local_player_entity_id()
		GameManager.player_data["character_name"] = ""
		GameManager.player_data["character_id"] = ""
		GameManager.player_data["player_class"] = PacketTypes.PlayerClass.ZEALOT
		GameManager.reset_progression()
		GameManager.player_data_updated.emit()
		print("[Sanctuary] Character sacrificed; routing to character creation")
		SceneManager.goto_character_creation()
	else:
		push_warning("[Sanctuary] Sacrifice returned status %d" % response_code)


# =============================================================================
# BUILDERS — PROPS
# =============================================================================

func _build_props() -> void:
	var container := Node2D.new()
	container.name = "Props"
	_world.add_child(container)

	var body := StaticBody2D.new()
	body.name = "PropColliders"
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	_world.add_child(body)

	for prop: Dictionary in PROPS:
		_spawn_prop(container, body, prop["kind"], prop["pos"])

	_build_avenue_lanterns(container, body)


## Lantern posts marching down both avenues in pairs.
func _build_avenue_lanterns(container: Node2D, body: StaticBody2D) -> void:
	var y := -896.0
	while y <= 960.0:
		if absf(y) > 320.0:                   # skip the plaza ring (handled by benches)
			_spawn_prop(container, body, "lantern", Vector2(-LANTERN_OFFSET, y))
			_spawn_prop(container, body, "lantern", Vector2(LANTERN_OFFSET, y))
		y += LANTERN_AVENUE_STEP
	var x := -1408.0
	while x <= 1408.0:
		if absf(x) > 320.0:
			_spawn_prop(container, body, "lantern", Vector2(x, -LANTERN_OFFSET))
			_spawn_prop(container, body, "lantern", Vector2(x, LANTERN_OFFSET))
		x += LANTERN_AVENUE_STEP


## Spawn one prop placeholder node (+ collider if solid). Tagged for replacement.
func _spawn_prop(container: Node2D, body: StaticBody2D, kind: String, pos: Vector2) -> void:
	var prop := _Prop.new()
	prop.name = kind.to_pascal_case()         # findable in the tree (Godot dedupes dupes)
	prop.kind = kind
	prop.position = pos
	prop.palette = _palette()
	prop.add_to_group("placeholder")
	prop.set_meta("placeholder", true)
	prop.set_meta("kind", kind)
	prop.set_meta("replace_with", "prop:%s" % kind)
	container.add_child(prop)

	var col: Dictionary = _PROP_COLLIDERS.get(kind, {})
	if col.is_empty():
		return
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
	body.add_child(shape)


## Collider footprints for solid props (kinds not listed are walkable decor).
const _PROP_COLLIDERS: Dictionary = {
	"tree": {"radius": 14.0},
	"lantern": {"radius": 6.0},
	"well": {"radius": 26.0},
	"bench": {"size": Vector2(48.0, 16.0)},
	"stall": {"size": Vector2(56.0, 44.0)},
	"notice_board": {"size": Vector2(48.0, 14.0)},
	"signpost": {"radius": 7.0},
	"barrel": {"radius": 12.0},
	"crate": {"size": Vector2(26.0, 26.0)},
	"counter": {"size": Vector2(96.0, 28.0)},
	"shelf": {"size": Vector2(64.0, 24.0)},
	"table": {"size": Vector2(44.0, 32.0)},
	"bed": {"size": Vector2(48.0, 64.0)},
	"chest": {"size": Vector2(40.0, 28.0)},
	"altar": {"size": Vector2(72.0, 40.0)},
	"weapon_rack": {"size": Vector2(56.0, 20.0)},
	"bookshelf": {"size": Vector2(64.0, 22.0)},
	"training_dummy": {"radius": 14.0},
	"pew": {"size": Vector2(72.0, 18.0)},
}


# =============================================================================
# HUD
# =============================================================================

func _build_safe_zone_badge() -> void:
	var badge := Label.new()
	badge.name = "SafeZoneBadge"
	badge.text = "SANCTUARY  •  SAFE ZONE"
	badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	badge.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	badge.offset_left = -220.0
	badge.offset_right = 220.0
	badge.offset_top = 16.0
	badge.offset_bottom = 48.0
	badge.add_theme_font_size_override("font_size", 22)
	badge.add_theme_color_override("font_color", Color("ffd36a"))
	badge.add_theme_color_override("font_outline_color", Color("3c8ccf"))
	badge.add_theme_constant_override("outline_size", 6)
	hud_layer.add_child(badge)

	var hint := Label.new()
	hint.name = "TravelHint"
	hint.text = "Explore the city — the Arena Portal waits on the dais to the south"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	hint.offset_left = -300.0
	hint.offset_right = 300.0
	hint.offset_top = 50.0
	hint.offset_bottom = 72.0
	hint.add_theme_font_size_override("font_size", 13)
	hint.add_theme_color_override("font_color", Color(0.96, 0.94, 0.86, 0.85))
	hud_layer.add_child(hint)


# =============================================================================
# HELPERS
# =============================================================================

func _load_texture(path: String) -> Texture2D:
	if ResourceLoader.exists(path):
		return load(path) as Texture2D
	return null


## Wall material -> [top, face, edge] colors (resolved here so the inner draw
## layer stays free of outer-scope enum references).
func _mat_colors(mat: int) -> Array:
	# [top (sunlit), face (shadowed front), edge (top highlight)]. Faces are kept
	# deliberately dark so the raised 3/4 oblique read is unmistakable.
	match mat:
		Mat.PLASTER:
			return [CREAM, Color("8a5a2b"), CLOUD_WHITE]
		Mat.TIMBER:
			return [CREAM, Color("6e4724"), CLOUD_WHITE]
		Mat.RAMPART:
			return [WARM_STONE, Color("5f5747"), Color("e7dcc4")]
		Mat.CLIFF:
			return [STONE_FLOOR, Color("6f6450"), CLOUD_WHITE]
		_:
			return [CLOUD_WHITE, Color("796f5a"), CLOUD_WHITE]  # STONE


## Floor type -> draw style (fill, seam, planks) resolved in the outer scope.
func _floor_style(ftype: int) -> Dictionary:
	match ftype:
		FloorType.PLAZA:
			return {"fill": PLAZA_COLOR, "seam": COBBLE_SEAM, "planks": false}
		FloorType.WOOD:
			return {"fill": WOOD_FLOOR, "seam": WOOD_FLOOR_ALT, "planks": true}
		FloorType.STONE:
			return {"fill": STONE_FLOOR, "seam": STONE_FLOOR_ALT, "planks": false}
		FloorType.RUG:
			return {"fill": PLAZA_COLOR, "seam": COBBLE_SEAM, "planks": false}
		_:
			return {"fill": COBBLE_COLOR, "seam": COBBLE_SEAM, "planks": false}  # COBBLE


func _floor_op(rect: Rect2, ftype: int) -> Dictionary:
	var style := _floor_style(ftype)
	return {
		"op": "floor", "rect": rect,
		"fill": style["fill"], "seam": style["seam"], "planks": style["planks"],
	}


## Colors handed to the drawing layers/props (inner classes can't read outer consts).
func _palette() -> Dictionary:
	return {
		"grass": GRASS_COLOR, "grass_alt": GRASS_COLOR_ALT, "clover": CLOVER_COLOR,
		"cobble": COBBLE_COLOR, "cobble_seam": COBBLE_SEAM, "plaza": PLAZA_COLOR,
		"wood": WOOD_FLOOR, "wood_alt": WOOD_FLOOR_ALT,
		"stone": STONE_FLOOR, "stone_alt": STONE_FLOOR_ALT,
		"water": WATER_COLOR, "water_edge": WATER_EDGE,
		"stair": STAIR_COLOR, "stair_seam": STAIR_SEAM,
		"cream": CREAM, "cloud": CLOUD_WHITE, "honey": HONEY, "honey_dark": HONEY_DARK,
		"warm_stone": WARM_STONE, "stone_dark": STONE_DARK, "plaster_face": PLASTER_FACE,
	}


# =============================================================================
# DRAW LAYERS / PLACEHOLDER ART (inner classes — self-contained _draw nodes)
# =============================================================================

## Oblique raised-wall renderer. Each footprint cell is drawn as a lifted top
## surface + a shadowed south face; back-to-front order leaves only outer faces
## visible, producing the Hammerwatch wall look.
class _WallLayer extends Node2D:
	## Each record carries pre-resolved colors: {rect, top, face, edge, h},
	## pre-sorted north→south.
	var records: Array = []

	func _draw() -> void:
		for rec: Dictionary in records:
			var rect: Rect2 = rec["rect"]
			var h: float = rec["h"]
			var face_c: Color = rec["face"]
			var top := Rect2(rect.position - Vector2(0.0, h), rect.size)
			var face := Rect2(rect.position + Vector2(0.0, rect.size.y - h), Vector2(rect.size.x, h))
			# Contact shadow on the ground at the wall base (interior cells get
			# overdrawn by the next row's top, so only outer faces keep theirs).
			draw_rect(Rect2(rect.position + Vector2(0.0, rect.size.y), Vector2(rect.size.x, 5.0)), Color(0, 0, 0, 0.18))
			draw_rect(face, face_c)                                            # shadowed front face
			draw_rect(Rect2(face.position + Vector2(0.0, h - 3.0), Vector2(face.size.x, 3.0)), face_c.darkened(0.3))  # base line
			draw_rect(top, rec["top"])                                         # lifted sunlit top
			draw_rect(Rect2(top.position, Vector2(top.size.x, 3.0)), rec["edge"])  # back/top highlight
			# Crease where the top meets the front face.
			var crease_y := top.position.y + top.size.y
			draw_line(Vector2(top.position.x, crease_y), Vector2(top.position.x + top.size.x, crease_y), face_c.darkened(0.15), 1.0)


## Ground renderer: grass base, paved network, interiors, pools, stairs, plus a
## faint tile grid and sparse detail so flat color reads as tiled stone/wood.
class _GroundLayer extends Node2D:
	const TILE := 32.0
	var ops: Array = []
	var palette: Dictionary = {}

	func _draw() -> void:
		for op: Dictionary in ops:
			match op["op"]:
				"grass": _draw_grass(op["rect"])
				"floor": _draw_floor(op)
				"plaza_circle": _draw_plaza_circle(op["center"], op["radius"])
				"water": _draw_water(op["rect"])
				"stair": _draw_stair(op["rect"], op["dir"])

	func _draw_grass(rect: Rect2) -> void:
		draw_rect(rect, palette["grass"], true)
		# Checker + clover tufts for texture (deterministic).
		var step := 64.0
		var y := rect.position.y
		var ry := 0
		while y < rect.position.y + rect.size.y:
			var x := rect.position.x
			var rx := 0
			while x < rect.position.x + rect.size.x:
				if (rx + ry) % 2 == 0:
					draw_rect(Rect2(x, y, step, step), palette["grass_alt"], true)
				if posmod(rx * 7 + ry * 13, 11) == 0:
					draw_circle(Vector2(x + 32.0, y + 32.0), 3.0, palette["clover"])
				x += step
				rx += 1
			y += step
			ry += 1

	func _draw_floor(op: Dictionary) -> void:
		draw_rect(op["rect"], op["fill"], true)
		_draw_tile_grid(op["rect"], op["seam"], op["planks"])

	## Faint seams every tile (wood = planks: seams one way + lighter run).
	func _draw_tile_grid(rect: Rect2, seam: Color, planks: bool) -> void:
		var seam_c := Color(seam.r, seam.g, seam.b, 0.35)
		var x := rect.position.x
		while x <= rect.position.x + rect.size.x:
			draw_line(Vector2(x, rect.position.y), Vector2(x, rect.position.y + rect.size.y), seam_c, 1.0)
			x += TILE
		if planks:
			return
		var y := rect.position.y
		while y <= rect.position.y + rect.size.y:
			draw_line(Vector2(rect.position.x, y), Vector2(rect.position.x + rect.size.x, y), seam_c, 1.0)
			y += TILE

	func _draw_plaza_circle(center: Vector2, radius: float) -> void:
		draw_circle(center, radius, palette["plaza"])
		draw_arc(center, radius - 4.0, 0.0, TAU, 96, palette["cobble_seam"], 3.0)
		draw_arc(center, radius * 0.62, 0.0, TAU, 80, Color(palette["cobble_seam"].r, palette["cobble_seam"].g, palette["cobble_seam"].b, 0.5), 2.0)

	func _draw_water(rect: Rect2) -> void:
		draw_rect(rect, palette["water"], true)
		draw_rect(rect, palette["water_edge"], false, 3.0)
		draw_rect(rect.grow(-10.0), Color(palette["water_edge"].r, palette["water_edge"].g, palette["water_edge"].b, 0.4), false, 2.0)

	func _draw_stair(rect: Rect2, dir: String) -> void:
		draw_rect(rect, palette["stair"], true)
		# Tread lines perpendicular to the climb direction.
		if dir == "N" or dir == "S":
			var y := rect.position.y + 8.0
			while y < rect.position.y + rect.size.y:
				draw_line(Vector2(rect.position.x, y), Vector2(rect.position.x + rect.size.x, y), palette["stair_seam"], 2.0)
				y += 16.0
		else:
			var x := rect.position.x + 8.0
			while x < rect.position.x + rect.size.x:
				draw_line(Vector2(x, rect.position.y), Vector2(x, rect.position.y + rect.size.y), palette["stair_seam"], 2.0)
				x += 16.0


## Drawn fallback fountain (only used if the kept sprite is missing).
class _Fountain extends Node2D:
	var radius: float = 64.0
	var palette: Dictionary = {}
	func _draw() -> void:
		draw_circle(Vector2.ZERO, radius + 6.0, palette["cloud"])
		draw_circle(Vector2.ZERO, radius - 4.0, palette["cobble_seam"])
		draw_circle(Vector2.ZERO, radius - 10.0, palette["water"])
		draw_circle(Vector2.ZERO, 16.0, palette["cloud"])
		draw_circle(Vector2.ZERO, 9.0, palette["water_edge"])


## All placeholder props. Generic furniture is an oblique box; a handful of
## outdoor pieces get bespoke art. Sized to roughly match their colliders.
class _Prop extends Node2D:
	var kind: String = "crate"
	var palette: Dictionary = {}

	func _draw() -> void:
		match kind:
			"tree": _draw_tree()
			"lantern": _draw_lantern()
			"well": _draw_well()
			"flowerbed": _draw_flowerbed()
			"planter": _draw_planter()
			"banner": _draw_banner()
			"signpost": _draw_signpost()
			"notice_board": _draw_notice_board()
			"stall": _draw_stall()
			"bed": _draw_box(Vector2(48.0, 64.0), 8.0, Color("e9e3d2"), Color("b8793a"), "bed")
			"counter": _draw_box(Vector2(96.0, 28.0), 14.0, palette["honey"], palette["honey_dark"])
			"shelf": _draw_box(Vector2(64.0, 24.0), 18.0, palette["honey"], palette["honey_dark"])
			"bookshelf": _draw_box(Vector2(64.0, 22.0), 24.0, Color("8a5a2b"), Color("5e3d1d"))
			"weapon_rack": _draw_box(Vector2(56.0, 20.0), 26.0, Color("9c8a6a"), Color("6f6044"))
			"table": _draw_box(Vector2(44.0, 32.0), 12.0, palette["honey"], palette["honey_dark"])
			"chest": _draw_box(Vector2(40.0, 28.0), 14.0, Color("b8793a"), Color("8a5a2b"))
			"altar": _draw_box(Vector2(72.0, 40.0), 18.0, palette["cloud"], palette["warm_stone"])
			"pew": _draw_box(Vector2(72.0, 18.0), 12.0, palette["honey"], palette["honey_dark"])
			"barrel": _draw_barrel()
			"crate": _draw_box(Vector2(26.0, 26.0), 16.0, palette["honey"], palette["honey_dark"])
			"candle": _draw_candle()
			"training_dummy": _draw_training_dummy()
			_: _draw_box(Vector2(28.0, 28.0), 14.0, palette["honey"], palette["honey_dark"])

	## Oblique box: shadow + south face + lifted top.
	func _draw_box(size: Vector2, h: float, top: Color, face: Color, _tag: String = "") -> void:
		var half := size * 0.5
		draw_circle(Vector2(0.0, half.y), maxf(half.x, half.y), Color(0, 0, 0, 0.12))  # soft shadow
		var top_rect := Rect2(-half.x, -half.y - h, size.x, size.y)
		var face_rect := Rect2(-half.x, half.y - h, size.x, h)
		draw_rect(face_rect, face, true)
		draw_rect(top_rect, top, true)
		draw_rect(Rect2(top_rect.position, Vector2(size.x, 2.0)), top.lightened(0.25), true)
		draw_rect(top_rect, face.darkened(0.1), false, 1.0)

	func _draw_tree() -> void:
		draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.12))
		draw_rect(Rect2(-5.0, -10.0, 10.0, 18.0), palette["honey_dark"], true)  # trunk
		draw_circle(Vector2(0.0, -34.0), 34.0, palette["clover"])
		draw_circle(Vector2(-12.0, -44.0), 20.0, palette["grass"].lightened(0.12))
		draw_circle(Vector2(14.0, -38.0), 18.0, palette["grass"].lightened(0.05))

	func _draw_lantern() -> void:
		draw_circle(Vector2(0.0, 2.0), 5.0, Color(0, 0, 0, 0.15))
		draw_line(Vector2.ZERO, Vector2(0.0, -30.0), palette["honey_dark"], 4.0)
		draw_circle(Vector2(0.0, -34.0), 6.0, Color("e7a93c"))
		draw_circle(Vector2(0.0, -34.0), 10.0, Color(1.0, 0.9, 0.5, 0.25))

	func _draw_well() -> void:
		draw_circle(Vector2(0.0, 6.0), 28.0, Color(0, 0, 0, 0.12))
		draw_circle(Vector2.ZERO, 26.0, palette["warm_stone"])
		draw_circle(Vector2.ZERO, 18.0, palette["stone_dark"])
		draw_circle(Vector2.ZERO, 13.0, Color(0.1, 0.12, 0.16, 0.9))
		draw_rect(Rect2(-28.0, -44.0, 56.0, 8.0), palette["honey_dark"], true)  # roof beam
		draw_line(Vector2(-22.0, -8.0), Vector2(-22.0, -44.0), palette["honey_dark"], 4.0)
		draw_line(Vector2(22.0, -8.0), Vector2(22.0, -44.0), palette["honey_dark"], 4.0)

	func _draw_flowerbed() -> void:
		draw_circle(Vector2.ZERO, 18.0, palette["clover"])
		draw_circle(Vector2(-7.0, -3.0), 4.0, Color("f3a6be"))
		draw_circle(Vector2(8.0, 2.0), 4.0, Color("ffe680"))
		draw_circle(Vector2(0.0, 8.0), 4.0, Color("bda7e8"))
		draw_circle(Vector2(2.0, -8.0), 4.0, Color("fffbef"))

	func _draw_planter() -> void:
		draw_rect(Rect2(-16.0, -6.0, 32.0, 16.0), palette["honey"], true)
		draw_rect(Rect2(-16.0, -6.0, 32.0, 4.0), Color("5e3d1d"), true)
		draw_circle(Vector2(-7.0, -10.0), 4.0, Color("f3a6be"))
		draw_circle(Vector2(6.0, -11.0), 4.0, Color("ffe680"))

	func _draw_banner() -> void:
		draw_line(Vector2(0.0, 4.0), Vector2(0.0, -48.0), palette["honey_dark"], 3.0)
		draw_rect(Rect2(-12.0, -46.0, 24.0, 30.0), Color("3c8ccf"), true)
		draw_rect(Rect2(-12.0, -46.0, 24.0, 6.0), Color("ffd36a"), true)
		draw_colored_polygon(PackedVector2Array([
			Vector2(-12.0, -16.0), Vector2(12.0, -16.0), Vector2(0.0, -8.0)
		]), Color("3c8ccf"))

	func _draw_signpost() -> void:
		draw_line(Vector2(0.0, 2.0), Vector2(0.0, -34.0), palette["honey_dark"], 4.0)
		draw_rect(Rect2(-18.0, -32.0, 36.0, 12.0), palette["honey"], true)
		draw_rect(Rect2(-18.0, -32.0, 36.0, 12.0), Color("5e3d1d"), false, 1.0)

	func _draw_notice_board() -> void:
		draw_rect(Rect2(-24.0, -34.0, 48.0, 30.0), palette["honey"], true)
		draw_rect(Rect2(-24.0, -34.0, 48.0, 30.0), palette["honey_dark"], false, 2.0)
		draw_rect(Rect2(-18.0, -28.0, 14.0, 16.0), palette["cream"], true)
		draw_rect(Rect2(2.0, -28.0, 14.0, 16.0), palette["cream"], true)

	func _draw_stall() -> void:
		_draw_box(Vector2(56.0, 30.0), 8.0, palette["honey"], palette["honey_dark"])
		# Striped awning.
		for i in range(4):
			var c: Color = Color("e85345") if i % 2 == 0 else palette["cloud"]
			draw_rect(Rect2(-28.0 + i * 14.0, -34.0, 14.0, 14.0), c, true)

	func _draw_barrel() -> void:
		draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.12))
		draw_rect(Rect2(-11.0, -22.0, 22.0, 28.0), palette["honey"], true)
		draw_rect(Rect2(-11.0, -16.0, 22.0, 3.0), palette["honey_dark"], true)
		draw_rect(Rect2(-11.0, -4.0, 22.0, 3.0), palette["honey_dark"], true)
		draw_ellipse_top(Vector2(0.0, -22.0), 11.0, 4.0, palette["honey"].lightened(0.2))

	func draw_ellipse_top(center: Vector2, rx: float, ry: float, color: Color) -> void:
		var pts := PackedVector2Array()
		for i in range(17):
			var a := TAU * float(i) / 16.0
			pts.append(center + Vector2(cos(a) * rx, sin(a) * ry))
		draw_colored_polygon(pts, color)

	func _draw_candle() -> void:
		draw_rect(Rect2(-3.0, -14.0, 6.0, 16.0), palette["cream"], true)
		draw_circle(Vector2(0.0, -16.0), 3.0, Color("ffe680"))
		draw_circle(Vector2(0.0, -16.0), 6.0, Color(1.0, 0.9, 0.5, 0.25))

	func _draw_training_dummy() -> void:
		draw_circle(Vector2(0.0, 4.0), 12.0, Color(0, 0, 0, 0.12))
		draw_rect(Rect2(-4.0, -10.0, 8.0, 18.0), palette["honey_dark"], true)
		draw_circle(Vector2(0.0, -20.0), 11.0, Color("c9a86f"))
		draw_rect(Rect2(-13.0, -24.0, 26.0, 8.0), Color("9c8a6a"), true)
