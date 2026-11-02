## Full-town roof/door regression tour. Uses the production town and a live
## observer; saves both outside and inside renders for every building.
extends Node2D

const SanctuaryTownWorld := preload("res://scripts/levels/town/sanctuary_town_world.gd")
const ACTOR := preload("res://scenes/entities/player/remote_player.tscn")
const OUT := "/tmp/sanctuary_roof_audit"
var _town: SanctuaryTownWorld
var _camera: Camera2D
var _actor: Node2D
var _walls: Dictionary = {}


func _ready() -> void:
	y_sort_enabled = true
	_town = SanctuaryTownWorld.new()
	add_child(_town)
	_town.build()
	var entities := Node2D.new()
	entities.name = "EntityContainer"
	entities.y_sort_enabled = true
	add_child(entities)
	_actor = ACTOR.instantiate()
	_actor.position = Vector2(-3300, -3000)
	entities.add_child(_actor)
	_town.set_roof_observer(_actor)
	for p: Array in _town.layout.walls:
		_walls[Vector2i(p[0], p[1])] = true
	_camera = Camera2D.new()
	_camera.process_callback = Camera2D.CAMERA2D_PROCESS_IDLE
	_camera.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	add_child(_camera)
	_camera.make_current()
	DirAccess.make_dir_recursive_absolute(OUT)
	get_window().size = Vector2i(1200, 800)
	await get_tree().process_frame
	var passed: bool = await _tour()
	get_tree().quit(0 if passed else 1)


func _tour() -> bool:
	var results: Array[Dictionary] = []
	var masonry := _town.get_node("Masonry") as TileMapLayer
	# All visual walls share the same grid as the authoritative layout. Their
	# top projection is art only; no independent per-building wall translation.
	for cell: Vector2i in masonry.get_used_cells():
		assert(masonry.to_global(masonry.map_to_local(cell)).is_equal_approx(
			_town.to_global((Vector2(cell) + Vector2(0.5, 0.5)) * 32.0)))
	var offset: Vector2 = SanctuaryTownWorld.WALL_TILES.get_meta("wall_top_offset")
	assert(offset == Vector2(-8, -24))
	for building: Dictionary in _town.layout.buildings:
		var roof := _town.get_node("Roof_" + str(building.id)) as TileMapLayer
		var owned: Dictionary = {}
		for p: Array in building.roof_cells:
			var cell := Vector2i(p[0], p[1])
			owned[cell] = true
			assert(roof.get_cell_source_id(cell) >= 0, "Missing roof tile in " + str(building.id))
			var expected := _town.to_global((Vector2(cell) + Vector2(0.5, 0.5)) * 32.0 + offset)
			# Odd source-atlas dimensions can contribute <0.1 world unit rounding.
			assert(roof.to_global(roof.map_to_local(cell)).distance_to(expected) < 0.1,
				"Roof is not on the wall-top plane: " + str(building.id))
		assert(roof.get_used_cells().size() == owned.size())
		for p: Array in building.floors:
			assert(owned.has(Vector2i(p[0], p[1])), "Uncovered interior")
		var street := Vector2i(building.street[0], building.street[1])
		var entrance := Vector2i(building.entrance[0], building.entrance[1])
		var anchor := Vector2i(building.interior_anchor[0], building.interior_anchor[1])
		var route := _route(entrance, anchor, owned)
		assert(not route.is_empty(), "No walk-in route: " + str(building.id))
		assert(_clear(street) and not owned.has(street))
		var r: Array = building.bounds
		_camera.position = Vector2((r[0] + r[2] * 0.5) * 32, (r[1] + r[3] * 0.5) * 32) + offset
		var viewport_size := get_viewport_rect().size
		var zoom := minf(2.5, minf(viewport_size.x / (r[2] * 32 + 192), viewport_size.y / (r[3] * 32 + 192)))
		_camera.zoom = Vector2.ONE * zoom
		_camera.force_update_scroll()
		await _observe(street)
		assert(_town.roof_is_visible(building.id), "Roof hidden from street")
		var outside: Image = await _capture(str(building.id) + "-outside")
		# Follow the doorway route in both directions. Roof decisions are made by
		# SanctuaryTownWorld._process, not direct calls to update_roofs in this test.
		for cell: Vector2i in route:
			await _observe(cell)
			assert(not _town.roof_is_visible(building.id), "Roof stayed on during entry")
			assert(_town.interior_at(_actor.global_position) == building.id)
		var inside: Image = await _capture(str(building.id) + "-inside")
		if outside != null:
			var probe_world := _town.to_global((Vector2(anchor) + Vector2(0.5, 0.5)) * 32.0 + offset)
			var pixel := Vector2i(get_viewport().get_final_transform() * get_viewport().get_canvas_transform() * probe_world)
			assert(not outside.get_pixelv(pixel).is_equal_approx(inside.get_pixelv(pixel)), "Roof visibility did not change the rendered interior")
		route.reverse()
		for cell: Vector2i in route:
			await _observe(cell)
			assert(not _town.roof_is_visible(building.id))
		await _observe(street)
		assert(_town.roof_is_visible(building.id), "Roof did not restore on exit")
		results.append({"id": building.id, "roof_cells": owned.size(), "route_steps": route.size(), "alignment": "pass", "entry": "pass", "exit": "pass", "rendered": outside != null})
		print("[RoofAudit] ", results.size(), "/", _town.layout.buildings.size(), " ", building.id, " alignment/entry/exit PASS")
	var report := FileAccess.open(OUT + "/report.json", FileAccess.WRITE)
	report.store_string(JSON.stringify({"buildings": results, "wall_cells_checked": masonry.get_used_cells().size(), "wall_top_offset": [offset.x, offset.y]}, "\t"))
	print("[RoofAudit] ALL ", results.size(), " buildings passed")
	return true


func _clear(cell: Vector2i) -> bool:
	# Same conservative 32-unit diameter clearance used by the collision bake.
	for delta in [Vector2i.ZERO, Vector2i.RIGHT, Vector2i.DOWN, Vector2i.ONE]:
		if _walls.has(cell + delta):
			return false
	return true


func _route(start: Vector2i, goal: Vector2i, owned: Dictionary) -> Array[Vector2i]:
	var queue: Array[Vector2i] = [start]
	var previous: Dictionary = {start: start}
	var cursor := 0
	while cursor < queue.size():
		var cell := queue[cursor]
		cursor += 1
		if cell == goal:
			var route: Array[Vector2i] = [goal]
			while route.back() != start:
				route.append(previous[route.back()])
			route.reverse()
			return route
		for delta in [Vector2i.LEFT, Vector2i.RIGHT, Vector2i.UP, Vector2i.DOWN]:
			var next: Vector2i = cell + delta
			if owned.has(next) and not previous.has(next) and _clear(next):
				previous[next] = cell
				queue.append(next)
	return []


func _observe(cell: Vector2i) -> void:
	_actor.position = (Vector2(cell) + Vector2(0.5, 0.5)) * 32.0
	await get_tree().process_frame
	await get_tree().process_frame


func _capture(label: String) -> Image:
	if DisplayServer.get_name() == "headless":
		return null
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(OUT + "/" + label + ".png")
	return img
