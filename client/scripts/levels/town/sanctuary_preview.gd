## Offline preview harness for the redesigned Sanctuary town. Builds the full SanctuaryTownWorld
## (placeholders + shaders + particles + NPCs + decorative Arena portal) with NO network, frames it
## with a camera, and — when run windowed — saves screenshots of the whole town and key districts to
## /tmp for visual review. Run headless it is a pure runtime smoke test (build must not crash).
##
##   windowed (captures PNGs):  /Users/opera/bin/godot --path client res://scenes/test/sanctuary_preview.tscn
##   headless  (smoke only):    /Users/opera/bin/godot --headless --path client res://scenes/test/sanctuary_preview.tscn
extends Node2D

const SanctuaryTownWorldScript := preload("res://scripts/levels/town/sanctuary_town_world.gd")
const NPC_SCENE: PackedScene = preload("res://scenes/entities/npc/npc.tscn")
const PORTAL_SCENE: PackedScene = preload("res://scenes/entities/portal/portal.tscn")

const OUT_DIR := "/tmp/sanctuary_preview"
const WIN := Vector2i(1600, 1480)

var _camera: Camera2D = null


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.015, 0.02, 0.02))

	var town = SanctuaryTownWorldScript.new()
	town.name = "TownWorld"
	add_child(town)
	town.build()
	town.build_npcs(town, NPC_SCENE, "res://assets/sprites/npcs/", Callable())
	town.build_arena_portal(town, PORTAL_SCENE, "res://assets/sprites/environment/town/")

	_camera = Camera2D.new()
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

	# Whole town (centred at origin) + a tour of districts.
	var shots := [
		{"name": "00_full_town", "pos": Vector2(0, 0), "zoom": 0.22},
		{"name": "01_west_gate", "pos": Vector2(-2496, -128), "zoom": 0.7},
		{"name": "02_priest_court_fountain", "pos": Vector2(-384, -640), "zoom": 0.8},
		{"name": "03_cathedral_ward", "pos": Vector2(-128, -2080), "zoom": 0.6},
		{"name": "04_merchant_bend", "pos": Vector2(640, 96), "zoom": 0.7},
		{"name": "05_lower_sanctum_portals", "pos": Vector2(1088, 1920), "zoom": 0.65},
		{"name": "06_mage_quarter", "pos": Vector2(2112, -1280), "zoom": 0.7},
		{"name": "07_tavern_guild", "pos": Vector2(-1400, 700), "zoom": 0.6},
	]
	for s: Dictionary in shots:
		_camera.position = s["pos"]
		_camera.zoom = Vector2(s["zoom"], s["zoom"])
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
