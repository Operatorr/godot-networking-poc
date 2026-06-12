## Sanctuary - the safe-hub town the player enters when entering the world.
##
## Fully client-local (OfflineArena subclass, like Practice): no server, no
## prediction. The Arena portal on the south dais is what dials the game server
## and moves the player into the authoritative Arena.
##
## Layout, districts, and every coordinate below are specified in
## docs/design/sanctuary-layout.md (the system of record for this scene) and
## follow docs/design/SANCTUARY_STYLEGUIDE.md. The town is data-driven: tables
## here mirror the doc's tables, and _populate() builds everything from them.
## Visuals are drawn placeholders until the PixelLab sprite pass fills
## assets/sprites/environment/town/ and assets/sprites/npcs/.
extends OfflineArena

const NPC_SCENE: PackedScene = preload("res://scenes/shared/npc/npc.tscn")
const PORTAL_SCENE: PackedScene = preload("res://scenes/shared/portal/portal.tscn")

const TOWN_TEXTURE_DIR := "res://assets/sprites/environment/town/"
const NPC_TEXTURE_DIR := "res://assets/sprites/npcs/"

# --- Style guide palette ----------------------------------------------------------
const GRASS_COLOR := Color("70b94a")        # Meadow Green
const PAVE_COLOR := Color("bfaf94")         # Warm Stone
const PAVE_EDGE_COLOR := Color("a3937a")
const HEDGE_COLOR := Color("4fa33d")        # Clover Green
const WALL_COLOR := Color("f7e7c4")         # Sanctuary Cream
const ROOF_RED := Color("c65b4a")           # Brick Red
const ROOF_BLUE := Color("3c8ccf")          # Banner Blue
const DOOR_COLOR := Color("b8793a")         # Honey Brown
const WATER_COLOR := Color("62c9c1")        # Soft Teal
const STONE_WHITE := Color("fffbef")        # Cloud White

# --- Town geometry (docs/design/sanctuary-layout.md) ------------------------------
const TOWN_RECT := Rect2(-800.0, -800.0, 1600.0, 1600.0)
const SPAWN_POS := Vector2(0.0, 128.0)
const PLAZA_CENTER := Vector2.ZERO
const PLAZA_RADIUS := 240.0
const DAIS_CENTER := Vector2(0.0, 580.0)
const DAIS_RADIUS := 110.0
const FOUNTAIN_RADIUS := 64.0

const PAVED_RECTS: Array[Rect2] = [
	Rect2(-56.0, -576.0, 112.0, 1232.0),   # Cathedral Way / Portal Way (N-S avenue)
	Rect2(-704.0, -48.0, 1408.0, 96.0),    # Guild Row / Market Street (E-W)
	Rect2(-160.0, -576.0, 320.0, 176.0),   # Church forecourt
	Rect2(-700.0, -200.0, 280.0, 400.0),   # Guild Court
	Rect2(320.0, -160.0, 360.0, 320.0),    # Market square
	Rect2(264.0, -256.0, 112.0, 240.0),    # Bank connector
]

## Buildings: solid colliders (environment layer) + facade. `roof` picks the
## style-guide roof color (blue = official/magical, red = homes and shops).
const BUILDINGS: Array[Dictionary] = [
	{
		"key": "church",
		"name": "Church of the Dawn",
		"center": Vector2(0.0, -688.0),
		"size": Vector2(320.0, 224.0),
		"door": "S",
		"roof": "blue",
	},
	{
		"key": "bank",
		"name": "Bank of the Sanctuary",
		"center": Vector2(320.0, -320.0),
		"size": Vector2(192.0, 160.0),
		"door": "S",
		"roof": "blue",
	},
	{
		"key": "warriors_guild",
		"name": "Warriors' Guild",
		"center": Vector2(-560.0, -256.0),
		"size": Vector2(224.0, 176.0),
		"door": "S",
		"roof": "red",
	},
	{
		"key": "mages_guild",
		"name": "Mages' Guild",
		"center": Vector2(-704.0, 0.0),
		"size": Vector2(176.0, 176.0),
		"door": "E",
		"roof": "blue",
	},
	{
		"key": "rogues_guild",
		"name": "Rogues' Guild",
		"center": Vector2(-560.0, 256.0),
		"size": Vector2(224.0, 176.0),
		"door": "N",
		"roof": "red",
	},
	{
		"key": "potion_shop",
		"name": "The Bubbling Flask",
		"center": Vector2(480.0, -224.0),
		"size": Vector2(144.0, 128.0),
		"door": "S",
		"roof": "red",
	},
	{
		"key": "equipment_shop",
		"name": "Hammer & Hilt",
		"center": Vector2(480.0, 224.0),
		"size": Vector2(160.0, 128.0),
		"door": "N",
		"roof": "red",
	},
]

const NPCS: Array[Dictionary] = [
	{
		"key": "priest",
		"name": "Father Aldric",
		"title": "High Priest of the Dawn",
		"role": TownNpc.Role.PRIEST,
		"pos": Vector2(0.0, -540.0),
		"color": Color("ffd36a"),
		"dialog": "Welcome to the Sanctuary, child of the Dawn. When the altar is consecrated you will spend your hard-won Glory here — strengthening your account's skill tree so every hero you raise starts mightier. Return soon.",
	},
	{
		"key": "warrior_trainer",
		"name": "Master Brandt",
		"title": "Warriors' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER,
		"pos": Vector2(-560.0, -144.0),
		"color": Color("c65b4a"),
		"dialog": "The Warriors' Guild forges the front line — shield, steel, and stubbornness. Class training opens when the guild ledgers arrive. Until then, keep your blade sharp in the Arena.",
	},
	{
		"key": "mage_trainer",
		"name": "Archmagus Elowen",
		"title": "Mages' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER,
		"pos": Vector2(-608.0, 0.0),
		"color": Color("3c8ccf"),
		"dialog": "Magic is patience given form. The Mages' Guild will tutor those with the spark — once the sanctum is attuned. Mind the fountain; its water remembers every spell cast near it.",
	},
	{
		"key": "rogue_trainer",
		"name": "Shade Vesper",
		"title": "Rogues' Guild Trainer",
		"role": TownNpc.Role.CLASS_TRAINER,
		"pos": Vector2(-560.0, 144.0),
		"color": Color("4fa33d"),
		"dialog": "You found our hall — that's lesson one passed. The Rogues' Guild deals in speed, shadows, and exits. Training begins when the contracts are signed. Don't ask who signs them.",
	},
	{
		"key": "potion_vendor",
		"name": "Tilda Brewbloom",
		"title": "Alchemist",
		"role": TownNpc.Role.VENDOR,
		"pos": Vector2(480.0, -120.0),
		"color": Color("bda7e8"),
		"dialog": "Potions, tonics, and brews that only sometimes hiss! The Bubbling Flask opens its shelves once the first caravan arrives. Come back thirsty, adventurer.",
	},
	{
		"key": "equipment_vendor",
		"name": "Garrick Forgehand",
		"title": "Outfitter",
		"role": TownNpc.Role.VENDOR,
		"pos": Vector2(480.0, 120.0),
		"color": Color("b8793a"),
		"dialog": "Hammer & Hilt — finest arms and armor on this side of the portal. The forge is still heating, but soon you'll trade for gear worth dying a little less in.",
	},
	{
		"key": "banker",
		"name": "Goldwin Ledger",
		"title": "Bankmaster",
		"role": TownNpc.Role.BANKER,
		"pos": Vector2(320.0, -208.0),
		"color": Color("e7a93c"),
		"dialog": "The Bank of the Sanctuary: your valuables outlive your heroes here. Vault deposits open with the next charter. Until then, try not to carry everything into the Arena at once.",
	},
]

## kind: tree | lantern | bench | stall | board | flowers
const PROPS: Array[Dictionary] = [
	{"kind": "board", "pos": Vector2(160.0, -96.0)},
	{"kind": "stall", "pos": Vector2(640.0, -64.0)},
	{"kind": "stall", "pos": Vector2(640.0, 64.0)},
	{"kind": "bench", "pos": Vector2(-150.0, -150.0)},
	{"kind": "bench", "pos": Vector2(150.0, -150.0)},
	{"kind": "bench", "pos": Vector2(-150.0, 150.0)},
	{"kind": "bench", "pos": Vector2(150.0, 150.0)},
	{"kind": "lantern", "pos": Vector2(-88.0, -480.0)},
	{"kind": "lantern", "pos": Vector2(88.0, -480.0)},
	{"kind": "lantern", "pos": Vector2(-88.0, -280.0)},
	{"kind": "lantern", "pos": Vector2(88.0, -280.0)},
	{"kind": "lantern", "pos": Vector2(-88.0, 280.0)},
	{"kind": "lantern", "pos": Vector2(88.0, 280.0)},
	{"kind": "lantern", "pos": Vector2(-88.0, 460.0)},
	{"kind": "lantern", "pos": Vector2(88.0, 460.0)},
	{"kind": "lantern", "pos": Vector2(-288.0, -88.0)},
	{"kind": "lantern", "pos": Vector2(-288.0, 88.0)},
	{"kind": "lantern", "pos": Vector2(288.0, -88.0)},
	{"kind": "lantern", "pos": Vector2(288.0, 88.0)},
	{"kind": "tree", "pos": Vector2(-700.0, -700.0)},
	{"kind": "tree", "pos": Vector2(-340.0, -420.0)},
	{"kind": "tree", "pos": Vector2(-700.0, 560.0)},
	{"kind": "tree", "pos": Vector2(-380.0, 480.0)},
	{"kind": "tree", "pos": Vector2(600.0, -420.0)},
	{"kind": "tree", "pos": Vector2(700.0, -560.0)},
	{"kind": "tree", "pos": Vector2(640.0, 420.0)},
	{"kind": "tree", "pos": Vector2(700.0, 700.0)},
	{"kind": "tree", "pos": Vector2(-180.0, 640.0)},
	{"kind": "tree", "pos": Vector2(200.0, 680.0)},
	{"kind": "flowers", "pos": Vector2(-200.0, -260.0)},
	{"kind": "flowers", "pos": Vector2(220.0, -240.0)},
	{"kind": "flowers", "pos": Vector2(-240.0, 220.0)},
	{"kind": "flowers", "pos": Vector2(240.0, 200.0)},
	{"kind": "flowers", "pos": Vector2(-120.0, -440.0)},
	{"kind": "flowers", "pos": Vector2(120.0, -440.0)},
	{"kind": "flowers", "pos": Vector2(-80.0, 660.0)},
	{"kind": "flowers", "pos": Vector2(80.0, 660.0)},
]

const GROUND_TILES_TEXTURE := TOWN_TEXTURE_DIR + "ground_tiles.png"
const GROUND_TILE_SIZE := 32
## Corner-Wang lookup for the PixelLab grass<->cobble tileset
## (ground_tiles_metadata.json): index bits SE=1, SW=2, NE=4, NW=8 paved;
## value is the tile's atlas cell in ground_tiles.png.
const WANG_ATLAS: Array[Vector2i] = [
	Vector2i(2, 1), Vector2i(3, 1), Vector2i(2, 2), Vector2i(1, 2),
	Vector2i(2, 0), Vector2i(3, 2), Vector2i(0, 1), Vector2i(3, 3),
	Vector2i(1, 1), Vector2i(2, 3), Vector2i(1, 0), Vector2i(0, 2),
	Vector2i(3, 0), Vector2i(0, 0), Vector2i(1, 3), Vector2i(0, 3),
]

## Prop sprite files (under TOWN_TEXTURE_DIR) and the sprite-center offset that
## plants each prop's base on its layout position.
const PROP_SPRITES: Dictionary = {
	"tree": {"file": "tree.png", "offset": Vector2(0.0, -44.0)},
	"lantern": {"file": "lantern.png", "offset": Vector2(0.0, -24.0)},
	"bench": {"file": "bench.png", "offset": Vector2.ZERO},
	"stall": {"file": "stall.png", "offset": Vector2(0.0, -8.0)},
	"board": {"file": "board.png", "offset": Vector2(0.0, -12.0)},
	"flowers": {"file": "flowers.png", "offset": Vector2.ZERO},
}

var _fountain_has_visual := false
var _ground_layer: TileMapLayer = null
var _prop_textures: Dictionary = {}


func _configure() -> void:
	arena_rect = TOWN_RECT
	wall_thickness = 16.0


func _get_spawn_position() -> Vector2:
	return SPAWN_POS


func _populate() -> void:
	_build_ground_tilemap()
	_build_buildings()
	_build_fountain()
	_build_npcs()
	_build_portals()
	_build_props()
	_build_safe_zone_badge()


## Town music TBD - the only loaded tracks are arena/menu themes, neither fits
## a peaceful hub, so the Sanctuary stays quiet for now.
func _start_music() -> void:
	pass


# =============================================================================
# BUILDERS
# =============================================================================

## Paint the grass/cobble ground with the corner-Wang tileset: every 32 px cell
## samples its 4 corners against the paved-layout geometry and picks the
## matching transition tile. Falls back to _draw() when the texture is absent.
func _build_ground_tilemap() -> void:
	var texture := _load_texture(GROUND_TILES_TEXTURE)
	if texture == null:
		return

	var source := TileSetAtlasSource.new()
	source.texture = texture
	source.texture_region_size = Vector2i(GROUND_TILE_SIZE, GROUND_TILE_SIZE)
	for atlas_coords: Vector2i in WANG_ATLAS:
		source.create_tile(atlas_coords)

	var tile_set := TileSet.new()
	tile_set.tile_size = Vector2i(GROUND_TILE_SIZE, GROUND_TILE_SIZE)
	tile_set.add_source(source, 0)

	_ground_layer = TileMapLayer.new()
	_ground_layer.name = "Ground"
	_ground_layer.tile_set = tile_set
	_ground_layer.z_index = -10
	_ground_layer.position = TOWN_RECT.position
	add_child(_ground_layer)

	var cells := Vector2i(TOWN_RECT.size) / GROUND_TILE_SIZE
	for cy in cells.y:
		for cx in cells.x:
			var origin := TOWN_RECT.position + Vector2(cx, cy) * float(GROUND_TILE_SIZE)
			var mask := 0
			if _is_paved(origin + Vector2(GROUND_TILE_SIZE, GROUND_TILE_SIZE)):
				mask |= 1  # SE
			if _is_paved(origin + Vector2(0.0, GROUND_TILE_SIZE)):
				mask |= 2  # SW
			if _is_paved(origin + Vector2(GROUND_TILE_SIZE, 0.0)):
				mask |= 4  # NE
			if _is_paved(origin):
				mask |= 8  # NW
			_ground_layer.set_cell(Vector2i(cx, cy), 0, WANG_ATLAS[mask])


func _is_paved(point: Vector2) -> bool:
	if point.distance_to(PLAZA_CENTER) <= PLAZA_RADIUS:
		return true
	if point.distance_to(DAIS_CENTER) <= DAIS_RADIUS:
		return true
	for paved: Rect2 in PAVED_RECTS:
		if paved.has_point(point):
			return true
	return false


func _build_buildings() -> void:
	var container := Node2D.new()
	container.name = "Buildings"
	add_child(container)

	for entry: Dictionary in BUILDINGS:
		var center: Vector2 = entry["center"]
		var size: Vector2 = entry["size"]

		var body := StaticBody2D.new()
		body.name = entry["key"].to_pascal_case()
		body.position = center
		body.collision_layer = ENVIRONMENT_COLLISION_LAYER
		body.collision_mask = 0
		container.add_child(body)

		var shape := CollisionShape2D.new()
		var rect := RectangleShape2D.new()
		rect.size = size
		shape.shape = rect
		body.add_child(shape)

		var texture := _load_texture(TOWN_TEXTURE_DIR + entry["key"] + ".png")
		if texture:
			var sprite := Sprite2D.new()
			sprite.texture = texture
			# Bottom-align the facade with the footprint so taller sprites
			# (roofs, towers) overhang to the north instead of the entrance.
			sprite.position.y = size.y * 0.5 - texture.get_height() * 0.5
			body.add_child(sprite)
		else:
			_add_building_placeholder(body, entry)

		var label := Label.new()
		label.text = entry["name"]
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.offset_left = -size.x * 0.5
		label.offset_right = size.x * 0.5
		label.offset_top = -size.y * 0.5 - 30.0
		label.offset_bottom = -size.y * 0.5 - 6.0
		label.add_theme_font_size_override("font_size", 15)
		label.add_theme_color_override("font_color", Color(1.0, 0.98, 0.88))
		label.add_theme_color_override("font_outline_color", Color(0.12, 0.1, 0.08))
		label.add_theme_constant_override("outline_size", 4)
		body.add_child(label)


## Placeholder facade: cream walls, roof slab, door strip on the entrance side.
func _add_building_placeholder(body: StaticBody2D, entry: Dictionary) -> void:
	var size: Vector2 = entry["size"]
	var half := size * 0.5
	var roof_color: Color = ROOF_BLUE if entry["roof"] == "blue" else ROOF_RED

	var walls := Polygon2D.new()
	walls.polygon = PackedVector2Array([
		Vector2(-half.x, -half.y), Vector2(half.x, -half.y),
		Vector2(half.x, half.y), Vector2(-half.x, half.y),
	])
	walls.color = WALL_COLOR
	body.add_child(walls)

	var roof := Polygon2D.new()
	var roof_bottom := -half.y + size.y * 0.55
	roof.polygon = PackedVector2Array([
		Vector2(-half.x, -half.y), Vector2(half.x, -half.y),
		Vector2(half.x, roof_bottom), Vector2(-half.x, roof_bottom),
	])
	roof.color = roof_color
	body.add_child(roof)

	var door := Polygon2D.new()
	var dw := 24.0
	match entry["door"]:
		"S":
			door.polygon = PackedVector2Array([
				Vector2(-dw, half.y - 14.0), Vector2(dw, half.y - 14.0),
				Vector2(dw, half.y), Vector2(-dw, half.y),
			])
		"N":
			door.polygon = PackedVector2Array([
				Vector2(-dw, -half.y), Vector2(dw, -half.y),
				Vector2(dw, -half.y + 14.0), Vector2(-dw, -half.y + 14.0),
			])
		"E":
			door.polygon = PackedVector2Array([
				Vector2(half.x - 14.0, -dw), Vector2(half.x, -dw),
				Vector2(half.x, dw), Vector2(half.x - 14.0, dw),
			])
		"W":
			door.polygon = PackedVector2Array([
				Vector2(-half.x, -dw), Vector2(-half.x + 14.0, -dw),
				Vector2(-half.x + 14.0, dw), Vector2(-half.x, dw),
			])
	door.color = DOOR_COLOR
	body.add_child(door)


func _build_fountain() -> void:
	var body := StaticBody2D.new()
	body.name = "Fountain"
	body.position = PLAZA_CENTER
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	add_child(body)

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
	# Without a texture the fountain is drawn in _draw().


func _build_npcs() -> void:
	var container := Node2D.new()
	container.name = "NPCs"
	add_child(container)

	for entry: Dictionary in NPCS:
		var npc := NPC_SCENE.instantiate() as TownNpc
		npc.name = entry["key"].to_pascal_case()
		npc.position = entry["pos"]
		npc.npc_name = entry["name"]
		npc.npc_title = entry["title"]
		npc.role = entry["role"]
		npc.dialog_text = entry["dialog"]
		npc.placeholder_color = entry["color"]
		npc.texture_path = NPC_TEXTURE_DIR + entry["key"] + ".png"
		container.add_child(npc)


func _build_portals() -> void:
	var portal := PORTAL_SCENE.instantiate() as Portal
	portal.name = "ArenaPortal"
	portal.position = DAIS_CENTER
	portal.portal_name = "Arena Portal"
	portal.destination = Portal.Destination.ARENA
	portal.requires_connection = true
	portal.texture_path = TOWN_TEXTURE_DIR + "portal.png"
	portal.animation_sheet_path = TOWN_TEXTURE_DIR + "portal_idle_sheet.png"
	add_child(portal)


## Props: sprite (when the PixelLab texture exists) + a small collider so solid
## props block movement. Textureless kinds fall back to _draw().
func _build_props() -> void:
	var container := StaticBody2D.new()
	container.name = "Props"
	container.collision_layer = ENVIRONMENT_COLLISION_LAYER
	container.collision_mask = 0
	add_child(container)

	for kind: String in PROP_SPRITES:
		var texture := _load_texture(TOWN_TEXTURE_DIR + PROP_SPRITES[kind]["file"])
		if texture:
			_prop_textures[kind] = texture

	for prop: Dictionary in PROPS:
		var pos: Vector2 = prop["pos"]
		var kind: String = prop["kind"]

		if _prop_textures.has(kind):
			var sprite := Sprite2D.new()
			sprite.texture = _prop_textures[kind]
			sprite.position = pos + (PROP_SPRITES[kind]["offset"] as Vector2)
			container.add_child(sprite)

		match kind:
			"tree":
				_add_circle_collider(container, pos, 14.0)
			"lantern":
				_add_circle_collider(container, pos, 6.0)
			"bench":
				_add_rect_collider(container, pos, Vector2(44.0, 14.0))
			"stall":
				_add_rect_collider(container, pos, Vector2(56.0, 44.0))
			"board":
				_add_rect_collider(container, pos, Vector2(48.0, 12.0))
			_:
				pass  # flowers are walkable


func _add_circle_collider(body: StaticBody2D, pos: Vector2, radius: float) -> void:
	var shape := CollisionShape2D.new()
	shape.position = pos
	var circle := CircleShape2D.new()
	circle.radius = radius
	shape.shape = circle
	body.add_child(shape)


func _add_rect_collider(body: StaticBody2D, pos: Vector2, size: Vector2) -> void:
	var shape := CollisionShape2D.new()
	shape.position = pos
	var rect := RectangleShape2D.new()
	rect.size = size
	shape.shape = rect
	body.add_child(shape)


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
	hint.text = "The Arena Portal waits on the dais south of the fountain"
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	hint.offset_left = -260.0
	hint.offset_right = 260.0
	hint.offset_top = 50.0
	hint.offset_bottom = 72.0
	hint.add_theme_font_size_override("font_size", 13)
	hint.add_theme_color_override("font_color", Color(0.96, 0.94, 0.86, 0.85))
	hud_layer.add_child(hint)


func _load_texture(path: String) -> Texture2D:
	if ResourceLoader.exists(path):
		return load(path) as Texture2D
	return null


# =============================================================================
# PLACEHOLDER GROUND + PROP RENDERING
# =============================================================================

func _draw() -> void:
	# Fallback ground when the PixelLab tileset is absent; with the tilemap in
	# place only textureless pieces are drawn.
	if _ground_layer == null:
		draw_rect(TOWN_RECT, GRASS_COLOR, true)

		draw_circle(PLAZA_CENTER, PLAZA_RADIUS, PAVE_COLOR)
		draw_circle(DAIS_CENTER, DAIS_RADIUS, PAVE_COLOR)
		for paved: Rect2 in PAVED_RECTS:
			draw_rect(paved, PAVE_COLOR, true)

		draw_arc(PLAZA_CENTER, PLAZA_RADIUS - 6.0, 0.0, TAU, 96, PAVE_EDGE_COLOR, 3.0)
		draw_arc(DAIS_CENTER, DAIS_RADIUS - 5.0, 0.0, TAU, 64, PAVE_EDGE_COLOR, 3.0)

		# Hedge ring marking the safe-zone boundary.
		draw_rect(TOWN_RECT.grow(-5.0), HEDGE_COLOR, false, 10.0)

	if not _fountain_has_visual:
		_draw_fountain()

	for prop: Dictionary in PROPS:
		if not _prop_textures.has(prop["kind"]):
			_draw_prop(prop)


func _draw_fountain() -> void:
	draw_circle(PLAZA_CENTER, FOUNTAIN_RADIUS + 6.0, STONE_WHITE)
	draw_circle(PLAZA_CENTER, FOUNTAIN_RADIUS - 4.0, PAVE_EDGE_COLOR)
	draw_circle(PLAZA_CENTER, FOUNTAIN_RADIUS - 10.0, WATER_COLOR)
	draw_circle(PLAZA_CENTER, 16.0, STONE_WHITE)
	draw_circle(PLAZA_CENTER, 9.0, WATER_COLOR.lightened(0.3))


func _draw_prop(prop: Dictionary) -> void:
	var pos: Vector2 = prop["pos"]
	match prop["kind"]:
		"tree":
			draw_circle(pos, 9.0, Color("8a5a2b"))
			draw_circle(pos + Vector2(0.0, -14.0), 34.0, HEDGE_COLOR)
			draw_circle(pos + Vector2(-10.0, -22.0), 18.0, GRASS_COLOR.lightened(0.15))
		"lantern":
			draw_line(pos, pos + Vector2(0.0, -26.0), Color("8a5a2b"), 4.0)
			draw_circle(pos + Vector2(0.0, -30.0), 7.0, Color("ffe680"))
			draw_circle(pos + Vector2(0.0, -30.0), 11.0, Color(1.0, 0.9, 0.5, 0.25))
		"bench":
			draw_rect(Rect2(pos - Vector2(22.0, 7.0), Vector2(44.0, 14.0)), DOOR_COLOR, true)
			draw_rect(Rect2(pos - Vector2(22.0, 7.0), Vector2(44.0, 5.0)), DOOR_COLOR.lightened(0.2), true)
		"stall":
			draw_rect(Rect2(pos - Vector2(28.0, 22.0), Vector2(56.0, 44.0)), DOOR_COLOR, true)
			for i in 4:
				var stripe_color := ROOF_RED if i % 2 == 0 else STONE_WHITE
				draw_rect(Rect2(pos + Vector2(-28.0 + i * 14.0, -22.0), Vector2(14.0, 16.0)), stripe_color, true)
		"board":
			draw_rect(Rect2(pos - Vector2(24.0, 18.0), Vector2(48.0, 30.0)), DOOR_COLOR, true)
			draw_rect(Rect2(pos - Vector2(18.0, 12.0), Vector2(14.0, 16.0)), WALL_COLOR, true)
			draw_rect(Rect2(pos + Vector2(2.0, -12.0), Vector2(14.0, 16.0)), WALL_COLOR, true)
		"flowers":
			draw_circle(pos, 5.0, Color("f3a6be"))
			draw_circle(pos + Vector2(10.0, 4.0), 4.0, Color("ffe680"))
			draw_circle(pos + Vector2(-9.0, 6.0), 4.0, STONE_WHITE)
			draw_circle(pos + Vector2(2.0, 11.0), 4.0, Color("bda7e8"))
		_:
			pass
