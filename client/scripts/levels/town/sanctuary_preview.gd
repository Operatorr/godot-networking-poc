## Offline runtime and screenshot harness for the reference-plan Sanctuary island.
extends Node2D

const SanctuaryTownWorld := preload("res://scripts/levels/town/sanctuary_town_world.gd")
const NPC_SCENE: PackedScene = preload("res://scenes/entities/npc/npc.tscn")
const PORTAL_SCENE: PackedScene = preload("res://scenes/entities/portal/portal.tscn")

const OUT_DIR := "/tmp/sanctuary_preview"
const WIN := Vector2i(1600, 1480)

var _camera: Camera2D = null


func _ready() -> void:
	y_sort_enabled = true # Same shared sort domain as the networked Sanctuary.
	RenderingServer.set_default_clear_color(Color(0.015, 0.02, 0.02))

	var town = SanctuaryTownWorld.new()
	town.name = "TownWorld"
	add_child(town)
	town.build()
	var collision_cells: Dictionary = {}
	for p: Array in town.layout.walls:
		collision_cells[Vector2i(p[0], p[1])] = true
	# Solid Temple column bases use column art, never an extra masonry block.
	for y in [-4, 1, 6, 11]:
		for x in [7, 21]:
			assert(collision_cells.has(Vector2i(x, y)), "Column must retain shared collision")
			assert(town.get_node("Masonry").get_cell_source_id(Vector2i(x, y)) == -1, "Column base is double-rendered as a wall")
	# Regression: real map cells must choose different atlas shapes by connectivity.
	var seen_shapes: Dictionary = {}
	for p: Array in town.layout.walls:
		var c := Vector2i(p[0], p[1])
		seen_shapes[town.get_node("Masonry").get_cell_atlas_coords(c)] = true
	assert(seen_shapes.size() >= 10, "Wall renderer repeats one horizontal tile")
	# Fixed points on the actual Temple: SE corner, NW corner and a north-facing T.
	for fixture: Array in [[Vector2i(25,18), 9], [Vector2i(3,-9), 6], [Vector2i(10,-3), 11]]:
		var tile: TileData = town.get_node("Masonry").get_cell_tile_data(fixture[0])
		assert((int(tile.get_custom_data("connections")) & 15) == fixture[1])
	# All 47 topology variants are registered, including filled inside corners.
	assert(town._wall_shapes.size() == 47)
	print("[SanctuaryPreview] directional wall and corner checks passed")
	town.build_npcs(town, NPC_SCENE, "res://assets/sprites/npcs/", Callable())
	town.build_arena_portal(town, PORTAL_SCENE, "res://assets/sprites/environment/town/")

	# Check direct teleports between interiors, exit, and world-to-local conversion.
	var previous_id := ""
	town.position = Vector2(96, -64)
	for building: Dictionary in town.layout.buildings:
		var pos: Vector2 = town.to_global(town._point(building.interior_anchor))
		town.update_roofs(pos)
		assert(town.interior_at(pos) == building.id)
		assert(not town.roof_is_visible(building.id))
		if not previous_id.is_empty():
			assert(town.roof_is_visible(previous_id))
		previous_id = building.id
	town.update_roofs(Vector2(-3300, -3000))
	for building: Dictionary in town.layout.buildings:
		assert(town.roof_is_visible(building.id))
	town.position = Vector2.ZERO
	# Prove the live observer path follows a local player's movement as well.
	var observer := Node2D.new()
	add_child(observer)
	observer.position = town._point(town.layout.spawn)
	town.set_roof_observer(observer)
	assert(not town.roof_is_visible("temple"))
	observer.position = Vector2(-3300, -3000)
	await get_tree().process_frame
	await get_tree().process_frame
	assert(town.roof_is_visible("temple"))
	observer.queue_free()
	await get_tree().process_frame
	print("[SanctuaryPreview] all interior roof entry/exit, teleport and observer checks passed")

	_camera = Camera2D.new()
	_camera.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	_camera.process_callback = Camera2D.CAMERA2D_PROCESS_IDLE
	add_child(_camera)
	_camera.make_current()

	if DisplayServer.get_name() == "headless":
		# Dummy renderer can't produce pixels; just prove the build didn't crash.
		await get_tree().process_frame
		await get_tree().process_frame
		print("[SanctuaryPreview] headless build OK (no screenshot in headless mode)")
		get_tree().quit()
		return

	DirAccess.make_dir_recursive_absolute(OUT_DIR)
	get_window().size = WIN
	await get_tree().process_frame
	if not await _verify_depth_rendering(town):
		get_tree().quit(1)
		return

	# Whole town (centred at origin) + a tour of districts.
	var house: Dictionary = town.layout.buildings[1]
	for candidate: Dictionary in town.layout.buildings:
		var bounds: Array = candidate.bounds
		if candidate.kind == "housing" and bounds[2] >= 8 and bounds[2] <= 14 and bounds[3] >= 8 and bounds[3] <= 15:
			house = candidate
			break
	# Inspect every atlas slot, including furniture reserved for future housing.
	var prop_names := ["Column", "Basin", "Altar", "Carpet", "Bed", "Dining table", "Chest", "Bookcase", "Stairs", "Desk", "Potion counter", "Bank counter", "Brazier", "Bench", "Cabinet", "Barrels"]
	for index in range(16):
		var pos := Vector2(5000 + (index % 4) * 128, (index / 4) * 112)
		town._prop_sprite(index, pos, Vector2(80, 80))
		town._label(pos + Vector2(0, 44), prop_names[index])
	# All connected wall shapes use the real material, scale and sort setup.
	var wall_gallery := town._wall_layer("WallMaterialGallery", 0)
	wall_gallery.position = Vector2(4600, 1000)
	var wall_index := 0
	for mask: int in town._wall_shapes:
		wall_gallery.set_cell(Vector2i((wall_index % 8) * 3, (wall_index / 8) * 3), 0, town._wall_shapes[mask])
		wall_index += 1
	var shots := [
		{"name": "10_wall_family", "pos": Vector2(4952, 1240), "zoom": 1.7, "observer": Vector2(-3300, -3000)},
		{"name": "09_prop_family", "pos": Vector2(5192, 180), "zoom": 2.0, "observer": Vector2(-3300, -3000)},
		{"name": "08_column_detail", "pos": Vector2(240, -144), "zoom": 4.0, "observer": town._point(town.layout.spawn)},
		{"name": "06_wall_corner", "pos": Vector2(816, 576), "zoom": 3.0, "observer": town._point(town.layout.spawn)},
		{"name": "07_wall_junction", "pos": Vector2(336, -80), "zoom": 3.0, "observer": town._point(town.layout.spawn)},
		{"name": "00_full_town", "pos": Vector2.ZERO, "zoom": 0.16, "observer": Vector2(-3300, -3000)},
		{"name": "01_temple_inside", "pos": town._point(town.layout.spawn), "zoom": 1.1, "observer": town._point(town.layout.spawn)},
		{"name": "02_temple_roof", "pos": town._point(town.layout.spawn), "zoom": 1.1, "observer": Vector2(-3300, -3000)},
		{"name": "03_housing_inside", "pos": town._point(house.interior_anchor), "zoom": 1.1, "observer": town._point(house.interior_anchor)},
		{"name": "04_bank", "pos": town._point(town.layout.bank), "zoom": 1.1, "observer": town._point(town.layout.bank)},
		{"name": "05_vendor", "pos": town._point(town.layout.vendor), "zoom": 1.1, "observer": town._point(town.layout.vendor)},
	]
	for s: Dictionary in shots:
		town.update_roofs(s["observer"])
		_camera.position = s["pos"]
		_camera.zoom = Vector2(s["zoom"], s["zoom"])
		_camera.reset_physics_interpolation()
		_camera.force_update_scroll()
		# Let the layout settle and a real frame draw before grabbing pixels.
		for _i in range(4):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		var path := "%s/%s.png" % [OUT_DIR, s["name"]]
		img.save_png(path)
		print("[SanctuaryPreview] saved ", path)

	print("[SanctuaryPreview] done")
	get_tree().quit()


## Read real rendered pixels, including the column/wall overlap reported in the Temple.
## A separate entity container exercises the same ancestry as networked players.
func _verify_depth_rendering(town: SanctuaryTownWorld) -> bool:
	town.update_roofs(town._point(town.layout.spawn))
	_camera.position = Vector2(288, -100)
	_camera.zoom = Vector2(4, 4)
	_camera.force_update_scroll()
	var column: Sprite2D
	for child: Node in town.get_children():
		if child is Sprite2D and child.texture == town._prop_textures[0] and child.position.distance_to(Vector2(240, -112)) < 32:
			column = child
	assert(column != null)
	var masonry := town.get_node("Masonry") as TileMapLayer
	column.hide()
	var wall_only := await _render_frame()
	masonry.hide()
	var floor_only := await _render_frame()
	column.show()
	var column_only := await _render_frame()
	masonry.show()
	var overlap := await _render_frame()
	var covered_samples := 0
	# Stay inside the opaque coping; antialiased perimeter pixels correctly
	# blend the prop beneath them and cannot equal a wall-over-floor reference.
	for y in range(-112, -96):
		for x in range(256, 264):
			var pixel := Vector2i(get_viewport().get_final_transform() * get_viewport().get_canvas_transform() * Vector2(x, y))
			var wall_color := wall_only.get_pixelv(pixel)
			var floor_color := floor_only.get_pixelv(pixel)
			if wall_color.is_equal_approx(floor_color) or column_only.get_pixelv(pixel).is_equal_approx(floor_color):
				continue
			covered_samples += 1
			if not overlap.get_pixelv(pixel).is_equal_approx(wall_color):
				push_error("Depth regression: Temple column draws over the wall in front of it at %s" % Vector2(x, y))
				return false
	assert(covered_samples > 20, "Column/wall depth probe must include overlapping opaque pixels")

	var entities := Node2D.new()
	entities.name = "EntityContainer"
	entities.y_sort_enabled = true
	add_child(entities)
	var actor := Node2D.new()
	entities.add_child(actor)
	var marker := Polygon2D.new()
	marker.polygon = PackedVector2Array([Vector2(-12, -60), Vector2(12, -60), Vector2(12, 40), Vector2(-12, 40)])
	marker.color = Color.MAGENTA
	actor.add_child(marker)
	for fixture: Dictionary in [
		{"name": "masonry", "probe": Vector2(336, -94), "behind": Vector2(336, -128), "front": Vector2(336, -48)},
		{"name": "column", "probe": Vector2(240, -122), "behind": Vector2(240, -144), "front": Vector2(240, -64)},
	]:
		actor.hide()
		var background := await _render_pixel(fixture.probe)
		actor.show()
		actor.position = fixture.behind
		var behind := await _render_pixel(fixture.probe)
		actor.position = fixture.front
		var in_front := await _render_pixel(fixture.probe)
		# Generated prop interiors contain a few near-opaque alpha pixels;
		# allow their tiny blend without accepting a visible foreground actor.
		var difference := Vector3(behind.r - background.r, behind.g - background.g, behind.b - background.b).abs()
		if maxf(difference.x, maxf(difference.y, difference.z)) > 3.0 / 255.0 or not in_front.is_equal_approx(Color.MAGENTA):
			push_error("Depth regression: actor must sort behind AND in front of %s across containers" % fixture.name)
			entities.queue_free()
			return false
	entities.queue_free()
	print("[SanctuaryPreview] rendered column/wall and actor behind/front depth checks passed")
	return true


func _render_pixel(world_position: Vector2) -> Color:
	var img := await _render_frame()
	var screen := Vector2i(get_viewport().get_final_transform() * get_viewport().get_canvas_transform() * world_position)
	return img.get_pixelv(screen)


func _render_frame() -> Image:
	for _frame in range(3):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	return get_viewport().get_texture().get_image()
