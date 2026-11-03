## Reference-plan Sanctuary. Layout cells and shared Rust solids are baked from layout.json.
class_name SanctuaryTownWorld
extends Node2D

const TILE := 32
const TOWN_RECT := Rect2(-3328, -3072, 6656, 6144)
const ATLAS := preload("res://assets/sprites/environment/sanctuary/materials.png")
const INTERIORS := preload("res://assets/sprites/environment/sanctuary/interiors.png")
const WALL_TILES: TileSet = preload("res://assets/tilesets/sanctuary/walls.tres")
const MASONRY_SHADER: Shader = preload("res://assets/shaders/town/masonry.gdshader")
const MASONRY_TEXTURE: Texture2D = preload("res://assets/sprites/environment/sanctuary/wall-materials.png")
const PROP_REGIONS_PATH := "res://assets/sprites/environment/sanctuary/interiors-regions.json"
const LAYOUT_PATH := "res://data/world/sanctuary/layout.json"
var layout: Dictionary
var _tiles: TileSet
var _masonry_material: ShaderMaterial
var _prop_textures: Array[AtlasTexture] = []
var _ground: TileMapLayer
var _walls: TileMapLayer
var _shore: TileMapLayer
var _gates: TileMapLayer
var _wall_shapes: Dictionary = {}
var _atlas_cell: int
var _roof_groups: Array[TileMapLayer] = []
var _interior_by_cell: Dictionary = {}
var _visible_interior := ""
var _observer: WeakRef

func set_roof_observer(player: Node2D) -> void:
	_observer = weakref(player)
	update_roofs(player.global_position)

func _process(_delta: float) -> void:
	if _observer == null:
		return
	var player := _observer.get_ref() as Node2D
	if is_instance_valid(player):
		update_roofs(player.global_position)

## Presentation only: no physics signals, scene switches, or server mutations.
## Explicit world-to-local conversion also supports offline preview/test observers.
func update_roofs(world_position: Vector2) -> void:
	var cell := Vector2i((to_local(world_position) / TILE).floor())
	var interior: String = _interior_by_cell.get(cell, "")
	if interior == _visible_interior:
		return
	_visible_interior = interior
	for roof: TileMapLayer in _roof_groups:
		roof.visible = roof.get_meta("building_id") != interior

func interior_at(world_position: Vector2) -> String:
	return _interior_by_cell.get(Vector2i((to_local(world_position) / TILE).floor()), "")

func roof_is_visible(building_id: String) -> bool:
	for roof: TileMapLayer in _roof_groups:
		if roof.get_meta("building_id") == building_id:
			return roof.visible
	return false

func build() -> void:
	# Nested Y-sorted containers join their ancestor's sort domain. Keep solid
	# scenery at the actors' Z=0; fixed Z bands are reserved for floor and roofs.
	y_sort_enabled = true
	_masonry_material = ShaderMaterial.new()
	_masonry_material.shader = MASONRY_SHADER
	_masonry_material.set_shader_parameter("masonry", MASONRY_TEXTURE)
	var prop_manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(PROP_REGIONS_PATH))
	for entry: Dictionary in prop_manifest.regions:
		var r: Array = entry.rect
		var texture := AtlasTexture.new()
		texture.atlas = INTERIORS
		texture.region = Rect2(r[0], r[1], r[2], r[3])
		texture.filter_clip = true
		_prop_textures.append(texture)
	layout = JSON.parse_string(FileAccess.get_file_as_string(LAYOUT_PATH))
	_atlas_cell = ATLAS.get_width() / 4
	_tiles = TileSet.new()
	_tiles.tile_size = Vector2i(_atlas_cell, _atlas_cell)
	var atlas := TileSetAtlasSource.new()
	atlas.texture = ATLAS
	atlas.texture_region_size = _tiles.tile_size
	for y in range(4):
		for x in range(4):
			atlas.create_tile(Vector2i(x, y))
	_tiles.add_source(atlas, 0)
	_ground = _layer("Ground", -20)
	# Ground uses quarter-material subtiles: one material spans 128 world units,
	# avoiding the noisy eightfold downsampling of a full material per 32-unit cell.
	var ground_set := TileSet.new()
	ground_set.tile_size = Vector2i(_atlas_cell / 4, _atlas_cell / 4)
	var ground_atlas := TileSetAtlasSource.new()
	ground_atlas.texture = ATLAS
	ground_atlas.texture_region_size = ground_set.tile_size
	for gy in range(16):
		for gx in range(16):
			ground_atlas.create_tile(Vector2i(gx, gy))
	ground_set.add_source(ground_atlas, 0)
	_ground.tile_set = ground_set
	_ground.scale = Vector2.ONE * float(TILE) / ground_set.tile_size.x
	var wall_atlas := WALL_TILES.get_source(0) as TileSetAtlasSource
	for y in range(6):
		for x in range(8):
			var coords := Vector2i(x, y)
			if wall_atlas.has_tile(coords):
				var connections: int = wall_atlas.get_tile_data(coords, 0).get_custom_data("connections")
				_wall_shapes[connections] = coords
	_walls = _wall_layer("Masonry", 0)
	_shore = _wall_layer("Quay", 0)
	var quay_material := _masonry_material.duplicate() as ShaderMaterial
	quay_material.set_shader_parameter("carved_faces", false)
	_shore.material = quay_material
	_gates = _layer("SealedGates", 0)
	_gates.y_sort_enabled = true
	_gates.y_sort_origin = _atlas_cell / 2
	var shore_cells: Dictionary = {}
	var polygon := PackedVector2Array()
	for p: Array in layout.land_polygon:
		polygon.append(Vector2(p[0], p[1]))
	for y in range(-112, 112):
		for x in range(-120, 120):
			var cell := Vector2i(x, y)
			var land := Geometry2D.is_point_in_polygon(Vector2(cell) + Vector2(0.5, 0.5), polygon)
			_ground.set_cell(cell, 0, Vector2i((4 if land else 0) + posmod(x, 4), posmod(y, 4)))
			if land:
				for offset in [Vector2.LEFT, Vector2.RIGHT, Vector2.UP, Vector2.DOWN]:
					if not Geometry2D.is_point_in_polygon(Vector2(cell) + Vector2(0.5, 0.5) + offset, polygon):
						shore_cells[cell] = true
						break
	var wall_cells: Dictionary = {}
	for wall: Array in layout.walls:
		wall_cells[Vector2i(wall[0], wall[1])] = true
	# Column bases remain in layout.walls for shared collision, but their sole
	# visible representation is the column sprite. Remove them before adjacency
	# selection so nearby wall ends do not connect to an invisible wall tile.
	for building: Dictionary in layout.buildings:
		for cell: Vector2i in _column_cells(building):
			wall_cells.erase(cell)
	_paint_connected_walls(_walls, wall_cells)
	_paint_connected_walls(_shore, shore_cells)
	for building: Dictionary in layout.buildings:
		_building(building)
	for i in range(4):
		_paint(_gates, layout.gate_rects[i], Vector2i(1, 2))
		_label(_point(layout.gates[i]) + Vector2(0, 76), "SEALED GATE %d" % (i + 1))
		_torch(_point(layout.gates[i]) + Vector2(-70, 0))
		_torch(_point(layout.gates[i]) + Vector2(70, 0))
	_label(_point(layout.spawn) + Vector2(0, 24), "TEMPLE • ARRIVAL")
	_label(_point(layout.bank) + Vector2(0, 24), "BANK")
	_label(_point(layout.vendor) + Vector2(0, 24), "VENDOR")

## Connectivity: north=1, east=2, south=4, west=8; filled NE/SE/SW/NW=16/32/64/128.
## The entire mask is selected at once, including corners and three/four-way junctions.
func _paint_connected_walls(layer: TileMapLayer, cells: Dictionary) -> void:
	for cell: Vector2i in cells:
		var mask := 0
		if cells.has(cell + Vector2i.UP): mask |= 1
		if cells.has(cell + Vector2i.RIGHT): mask |= 2
		if cells.has(cell + Vector2i.DOWN): mask |= 4
		if cells.has(cell + Vector2i.LEFT): mask |= 8
		# Fill a corner only when its diagonal cell exists as well. This closes
		# solid 2x2 blocks without filling the notch inside an L-shaped wall.
		if mask & 3 == 3 and cells.has(cell + Vector2i(1, -1)): mask |= 16
		if mask & 6 == 6 and cells.has(cell + Vector2i(1, 1)): mask |= 32
		if mask & 12 == 12 and cells.has(cell + Vector2i(-1, 1)): mask |= 64
		if mask & 9 == 9 and cells.has(cell + Vector2i(-1, -1)): mask |= 128
		layer.set_cell(cell, 0, _wall_shapes[mask])

func _wall_layer(layer_name: String, depth: int) -> TileMapLayer:
	var layer := TileMapLayer.new()
	layer.name = layer_name
	layer.tile_set = WALL_TILES
	layer.material = _masonry_material
	layer.scale = Vector2.ONE * float(TILE) / WALL_TILES.tile_size.x
	layer.z_index = depth
	layer.y_sort_enabled = true
	# Sort at the south edge of the ground footprint, not the raised coping.
	layer.y_sort_origin = WALL_TILES.tile_size.y / 2
	layer.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	layer.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	layer.collision_enabled = false
	add_child(layer)
	return layer

func _layer(layer_name: String, depth: int) -> TileMapLayer:
	var layer := TileMapLayer.new()
	layer.name = layer_name
	layer.tile_set = _tiles
	layer.scale = Vector2.ONE * float(TILE) / _atlas_cell
	layer.z_index = depth
	layer.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	layer.collision_enabled = false # Shared sim_core geometry owns movement.
	add_child(layer)
	return layer

func _paint(layer: TileMapLayer, r: Array, tile: Vector2i) -> void:
	for y in range(int(r[1]), int(r[1]+r[3])):
		for x in range(int(r[0]), int(r[0]+r[2])):
			var atlas_coord := tile
			if layer == _ground:
				atlas_coord = tile * 4 + Vector2i(posmod(x, 4), posmod(y, 4))
			layer.set_cell(Vector2i(x, y), 0, atlas_coord)

func _building(building: Dictionary) -> void:
	var id: String = building.id
	var temple: bool = building.kind == "temple"
	var floor_tile := Vector2i(3, 0) if temple else Vector2i(0, 2)
	if building.kind == "bank":
		floor_tile = Vector2i(3, 3)
	for p: Array in building.floors:
		var cell := Vector2i(p[0], p[1])
		_ground.set_cell(cell, 0, floor_tile * 4 + Vector2i(posmod(cell.x, 4), posmod(cell.y, 4)))
		_interior_by_cell[cell] = id
	var roof := _layer("Roof_" + id, 50)
	# Roof cells describe ground ownership. Their art sits on the raised wall
	# plane; applying this only to the visual layer keeps entry detection exact.
	roof.position = WALL_TILES.get_meta("wall_top_offset")
	roof.set_meta("building_id", id)
	roof.set_meta("housing_id", id if building.kind == "housing" else "")
	# Entire building, including partitions, belongs to one reveal group.
	for p: Array in building.roof_cells:
		var cell := Vector2i(p[0], p[1])
		roof.set_cell(cell, 0, Vector2i(3 if temple else 2, 1))
		_interior_by_cell[cell] = id
	_roof_groups.append(roof)
	_furnish(building)
	_torch(_point(building.entrance) + Vector2(-28, -8))
	_torch(_point(building.entrance) + Vector2(28, -8))
	# A stone threshold marks doors without covering their walkable opening.
	var door: Array = building.entrance
	_ground.set_cell(Vector2i(door[0], door[1]), 0, Vector2i(12 + posmod(door[0], 4), 8 + posmod(door[1], 4)))


func _column_cells(building: Dictionary) -> Array[Vector2i]:
	var cells: Array[Vector2i] = []
	if building.kind != "temple":
		return cells
	var r: Array = building.bounds
	for y in range(int(r[1]) + 5, int(r[1] + r[3]) - 4, 5):
		cells.append(Vector2i(int(r[0]) + 4, y))
		cells.append(Vector2i(int(r[0] + r[2]) - 5, y))
	return cells

func _furnish(building: Dictionary) -> void:
	var r: Array = building.bounds
	var x: int = r[0]
	var y: int = r[1]
	var w: int = r[2]
	var h: int = r[3]
	if building.kind == "temple":
		for cell: Vector2i in _column_cells(building):
			# Match the hall floor beneath the column, rather than exposing the
			# exterior cobble merely because this cell has authoritative collision.
			_paint(_ground, [cell.x, cell.y, 1, 1], Vector2i(3, 0))
			_furniture(0, cell, Vector2(52, 56), Vector2(0, -10))
		_furniture(1, Vector2i(x + 3, y + 3), Vector2(64, 64))
		_furniture(1, Vector2i(x + w - 4, y + 3), Vector2(64, 64))
		_furniture(2, Vector2i(x + w / 2, y + 3), Vector2(100, 64))
		_furniture(3, Vector2i(x + w / 2, y + h / 2), Vector2(96, 250))
	elif building.kind == "bank":
		_furniture(11, Vector2i(x + w / 2, y + 1), Vector2(mini(w * 24, 96), 48))
	elif building.kind == "vendor":
		_furniture(10, Vector2i(x + w / 2, y + 1), Vector2(mini(w * 24, 96), 48))
	else:
		# Sample interior dressing; housing ownership and player furniture are not persisted yet.
		if w >= 5 and h >= 5:
			_furniture(4, Vector2i(x + 1, y + 2), Vector2(44, 72))
			_furniture(6, Vector2i(x + w - 2, y + 1), Vector2(32, 32))
		if w >= 9 and h >= 9:
			_furniture(5, Vector2i(x + w - 4, y + h - 3), Vector2(72, 56))

func _furniture(index: int, cell: Vector2i, size: Vector2, offset := Vector2.ZERO) -> void:
	_prop_sprite(index, (Vector2(cell) + Vector2(0.5, 0.5)) * TILE + offset, size)

func _prop_sprite(index: int, pos: Vector2, size: Vector2) -> Sprite2D:
	var region: AtlasTexture = _prop_textures[index]
	var sprite := Sprite2D.new()
	sprite.texture = region
	sprite.position = pos
	# Cropped alpha bounds remove cell padding without changing the source raster.
	# Uniform fitting preserves the authored overhead projection on every prop.
	var fit := minf(size.x / region.region.size.x, size.y / region.region.size.y)
	sprite.scale = Vector2.ONE * fit
	# Only the flat floor textile is stretched to the authored nave runner footprint.
	if index == 3:
		sprite.scale = size / region.region.size
	else:
		# Preserve the picture's placement while sorting at its ground-contact
		# base. Sprite offset is in texture pixels, position is in world units.
		sprite.position.y += region.region.size.y * fit * 0.5
		sprite.offset.y = -region.region.size.y * 0.5
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	sprite.z_index = -15 if index == 3 else 0
	add_child(sprite)
	return sprite

func _point(p: Array) -> Vector2:
	return (Vector2(p[0], p[1]) + Vector2(0.5, 0.5)) * TILE

func _label(pos: Vector2, text: String) -> void:
	var label := Label.new()
	label.text = text
	label.z_index = 20
	label.position = pos - Vector2(150, 0)
	label.size.x = 300
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_font_size_override("font_size", 14)
	label.add_theme_color_override("font_color", Color("d0b783"))
	label.add_theme_constant_override("outline_size", 4)
	add_child(label)

func _torch(pos: Vector2) -> void:
	var glow := GradientTexture2D.new()
	glow.width = 64
	glow.height = 64
	glow.fill = GradientTexture2D.FILL_RADIAL
	glow.fill_from = Vector2(0.5, 0.5)
	glow.fill_to = Vector2(1, 0.5)
	glow.gradient = Gradient.new()
	glow.gradient.colors = PackedColorArray([Color(1, 0.6, 0.15, 0.65), Color(1, 0.3, 0.05, 0)])
	var sprite := Sprite2D.new()
	sprite.texture = glow
	sprite.position = pos
	sprite.z_index = -12 # Ground illumination stays beneath solid scenery.
	add_child(sprite)
	_prop_sprite(12, pos, Vector2(26, 26))


## A valid `priest_listener` receives the priest's `interacted` signal and replaces his default
## dialog (the Sanctuary's sacrifice flow).
func build_npcs(parent: Node2D, scene: PackedScene, texture_dir: String, priest_listener: Callable = Callable()) -> void:
	var entries := [
		["Father Aldric", "Priest of the Ash", "priest", TownNpc.Role.PRIEST, "priest.png", "Kneel if your knees still bend, pilgrim. The gods went silent before your grandfather drew breath, yet the bells we have left still ring. Offer your Glory at the shrine when the rite is consecrated — what you sacrifice here makes the next soul you raise a little harder to kill."],
		["Goldwin Ledger", "Bank", "bank", TownNpc.Role.BANKER, "banker.png", "Welcome to the bank. Banking services are not yet available."],
		["Tilda Brewbloom", "Vendor", "vendor", TownNpc.Role.VENDOR, "potion_vendor.png", "My supplies are being counted. Trading is not yet available."]]
	for entry: Array in entries:
		var npc = scene.instantiate()
		npc.npc_name = entry[0]
		npc.npc_title = entry[1]
		npc.position = _point(layout[entry[2]])
		npc.role = entry[3]
		npc.texture_path = texture_dir + entry[4]
		npc.dialog_text = entry[5]
		if npc.role == TownNpc.Role.PRIEST and priest_listener.is_valid():
			npc.suppress_default_dialog = true
			npc.interacted.connect(priest_listener)
		parent.add_child(npc)

func build_arena_portal(parent: Node2D, scene: PackedScene, texture_dir: String) -> Node:
	var portal = scene.instantiate()
	portal.name = "ArenaPortal"
	portal.position = _point(layout.arena)
	portal.portal_name = "Arena Portal"
	portal.destination = 0
	portal.requires_connection = true
	portal.texture_path = texture_dir + "portal.png"
	portal.animation_sheet_path = texture_dir + "portal_idle_sheet.png"
	parent.add_child(portal)
	return portal
