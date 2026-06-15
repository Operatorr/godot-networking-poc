## ServerStatus - bottom-left server status display (players, monsters, ping, FPS, scheduler).
##
## Authored as scenes/ui/hud/server_status.tscn (a VBox of fixed Labels). Polls
## NetworkManager.get_stats() once a second and surfaces SERVER_METRICS scheduler diagnostics.
extends Control

const UPDATE_INTERVAL := 1.0

var _update_timer: float = 0.0

@onready var _player_count_label: Label = $VBox/PlayerCount
@onready var _monster_count_label: Label = $VBox/MonsterCount
@onready var _ping_label: Label = $VBox/Ping
@onready var _fps_label: Label = $VBox/FPS
@onready var _sched_label: Label = $VBox/Sched
@onready var _warning_label: Label = $VBox/Warning


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	# Surface SERVER_METRICS scheduler diagnostics (§8.2). This is the only
	# client consumer of SERVER_METRICS today.
	if NetworkManager.has_signal("server_message_received"):
		NetworkManager.server_message_received.connect(_on_server_message)


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


## Update player count externally.
func update_player_count(count: int, max_players: int, _region: String = "") -> void:
	_player_count_label.text = "Players: %d/%d" % [count, max_players]


## Update monster count externally.
func update_monster_count(count: int, max_monsters: int) -> void:
	_monster_count_label.text = "Monsters: %d/%d" % [count, max_monsters]


## Surface snapshot-scheduler diagnostics from the SERVER_METRICS broadcast (§8.2).
## Red/yellow tinting makes priority-budget starvation visible at a glance.
func _on_server_message(message_type: int, data: Dictionary) -> void:
	if message_type != NetworkManager.MessageType.SERVER_METRICS:
		return
	if _sched_label == null:
		return
	var deferred: int = int(data.get("sched_entities_deferred", 0))
	var queue_age: int = int(data.get("sched_max_queue_age_ticks", 0))
	var at_budget_pct: int = int(data.get("sched_peers_at_budget_pct", 0))
	var peers: int = int(data.get("sched_peers_evaluated", 0))
	var overflow: int = int(data.get("sched_snapshot_overflow", 0))
	_sched_label.text = "Sched: def %d | qage %d | budget %d%% | peers %d | ovf %d" % [
		deferred, queue_age, at_budget_pct, peers, overflow]

	# Color-code starvation: red when peers are hitting the byte budget, yellow
	# when queue age is climbing past the render-delay window (~3 ticks).
	if at_budget_pct > 0:
		_sched_label.add_theme_color_override("font_color", Color(0.9, 0.3, 0.3))
	elif queue_age > 3:
		_sched_label.add_theme_color_override("font_color", Color(0.9, 0.7, 0.2))
	else:
		_sched_label.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
