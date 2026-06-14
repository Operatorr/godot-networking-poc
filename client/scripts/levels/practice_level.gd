## PracticeLevel - offline target-practice room (4 stationary dummies, N/E/S/W).
## A thin OfflineArena subclass: the base owns the player, camera, HUD, audio,
## pause/leave and projectile->enemy hit routing; this only defines the room and
## the dummies. Fully client-authoritative — no NetworkManager or server.
extends OfflineArena

const TARGET_DUMMY_SCENE: PackedScene = preload("res://scenes/entities/enemies/target_dummy.tscn")

const ROOM_RECT := Rect2(Vector2(-960.0, -693.0), Vector2(1920.0, 1386.0))
const DUMMY_RESPAWN_DELAY := 1.5
const DUMMY_SPAWNS := [
	{"name": "NorthDummy", "position": Vector2(0.0, -433.0)},
	{"name": "EastDummy", "position": Vector2(433.0, 0.0)},
	{"name": "SouthDummy", "position": Vector2(0.0, 433.0)},
	{"name": "WestDummy", "position": Vector2(-433.0, 0.0)},
]

var dummies: Array[TargetDummy] = []
var status_label: Label = null
var _dummy_kills: int = 0


func _configure() -> void:
	arena_rect = ROOM_RECT
	wall_thickness = 18.0
	grid_cell_size = 40.0
	floor_color = Color(0.075, 0.062, 0.052, 1.0)
	grid_color = Color(0.16, 0.12, 0.09, 0.55)
	border_color = Color(0.68, 0.36, 0.14, 1.0)
	border_width = 3.0


func _populate() -> void:
	_spawn_dummies()
	_build_status_label()


func _spawn_dummies() -> void:
	for spawn_data: Dictionary in DUMMY_SPAWNS:
		var dummy := TARGET_DUMMY_SCENE.instantiate() as TargetDummy
		if dummy == null:
			push_error("[PracticeLevel] Failed to instantiate target dummy")
			continue

		dummy.name = spawn_data["name"]
		dummy.position = spawn_data["position"]
		dummy.respawn_delay = DUMMY_RESPAWN_DELAY
		dummy.killed.connect(_on_dummy_killed)
		dummy.respawned.connect(_on_dummy_respawned)
		add_child(dummy)
		dummies.append(dummy)


func _build_status_label() -> void:
	status_label = Label.new()
	status_label.name = "StatusLabel"
	status_label.offset_left = 24.0
	status_label.offset_top = 20.0
	status_label.offset_right = 360.0
	status_label.offset_bottom = 72.0
	status_label.add_theme_font_size_override("font_size", 22)
	status_label.add_theme_color_override("font_color", Color(0.92, 0.84, 0.68, 1.0))
	hud_layer.add_child(status_label)
	_update_status()


func _on_dummy_killed(_dummy: TargetDummy) -> void:
	_dummy_kills += 1
	_update_status()


func _on_dummy_respawned(_dummy: TargetDummy) -> void:
	_update_status()


func _update_status() -> void:
	if status_label:
		status_label.text = "Practice\nDummies defeated: %d" % _dummy_kills
