## ServerStatusControl - Bottom-left server status display
## Shows player count, ping, FPS, and server info
extends Control


var _ping_label: Label = null
var _fps_label: Label = null
var _player_count_label: Label = null
var _warning_label: Label = null
var _update_timer: float = 0.0

const UPDATE_INTERVAL := 1.0


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _build_ui() -> void:
	# Position bottom-left
	anchor_left = 0.0
	anchor_right = 0.0
	anchor_top = 1.0
	anchor_bottom = 1.0
	offset_left = 20
	offset_right = 320
	offset_top = -100
	offset_bottom = -20

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 2)
	add_child(vbox)

	_player_count_label = Label.new()
	_player_count_label.add_theme_font_size_override("font_size", 12)
	_player_count_label.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
	_player_count_label.text = "Players: --"
	vbox.add_child(_player_count_label)

	_ping_label = Label.new()
	_ping_label.add_theme_font_size_override("font_size", 12)
	_ping_label.add_theme_color_override("font_color", Color(0.4, 0.9, 0.4))
	_ping_label.text = "Ping: --ms"
	vbox.add_child(_ping_label)

	_fps_label = Label.new()
	_fps_label.add_theme_font_size_override("font_size", 12)
	_fps_label.add_theme_color_override("font_color", Color(0.4, 0.9, 0.4))
	_fps_label.text = "FPS: --"
	vbox.add_child(_fps_label)

	_warning_label = Label.new()
	_warning_label.add_theme_font_size_override("font_size", 12)
	_warning_label.add_theme_color_override("font_color", Color(1.0, 0.3, 0.3))
	_warning_label.text = ""
	_warning_label.visible = false
	vbox.add_child(_warning_label)


func _process(delta: float) -> void:
	_update_timer += delta
	if _update_timer < UPDATE_INTERVAL:
		return
	_update_timer = 0.0

	_update_display()


func _update_display() -> void:
	var stats: Dictionary = NetworkManager.get_stats()
	var ping: float = stats.get("ping_ms", 0.0)

	_ping_label.text = "Ping: %dms" % int(ping)
	_fps_label.text = "FPS: %d" % Engine.get_frames_per_second()

	# Color code ping
	if ping < 100:
		_ping_label.add_theme_color_override("font_color", Color(0.4, 0.9, 0.4))
		_warning_label.visible = false
	elif ping < 200:
		_ping_label.add_theme_color_override("font_color", Color(0.9, 0.7, 0.2))
		_warning_label.visible = false
	else:
		_ping_label.add_theme_color_override("font_color", Color(0.9, 0.3, 0.3))
		_warning_label.text = "! High latency"
		_warning_label.visible = true


## Update player count externally (from leaderboard or server data)
func update_player_count(count: int, max_players: int, region: String) -> void:
	_player_count_label.text = "%d/%d Players Online (Server: %s)" % [count, max_players, region]
