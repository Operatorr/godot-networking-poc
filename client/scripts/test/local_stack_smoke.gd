## Rendered, two-client integration smoke. Launched by scripts/smoke_local.py.
## The driver survives normal scene changes; gameplay uses the real scenes,
## PredictionController, ENet transport, signed tickets and portal travel.
extends Node

var _config: Dictionary = {}
var _phase := "starting"
var _entity_id := -1
var _snapshots := 0
var _confirms := 0
var _progress := false
var _self_seen := false
var _peer_id := -1
var _first_position := Vector2.INF
var _distance := 0.0
var _shots := 0
var _monster_events := 0
var _last_snapshot_ms := 0
var _failed := false
var _stopping := false
var _next_status_ms := 0
var _phase_started_ms := 0


func _ready() -> void:
	_run.call_deferred()


func _run() -> void:
	var config_path := OS.get_environment("OMEGA_SMOKE_CONFIG")
	if config_path.is_empty():
		_fail("Launch with ./scripts/smoke_local.py; this scene needs its disposable local stack")
		return
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(config_path))
	if not parsed is Dictionary:
		_fail("Invalid smoke configuration")
		return
	_config = parsed
	# Never use saved login state or an externally configured endpoint in this test.
	if not str(_config.get("api_url", "")).begins_with("http://127.0.0.1:"):
		_fail("The smoke API must be on loopback")
		return
	reparent(get_tree().root)
	AuthManager.api_base_url = _config.api_url
	AuthManager.jwt_token = _config.token
	AuthManager.refresh_token = ""
	AuthManager.token_expiry = 0
	AuthManager.current_state = AuthManager.AuthState.LOGGED_IN
	GameManager.set_player_data({
		"user_id": str(_config.user_id),
		"character_id": str(_config.character_id),
		"character_name": str(_config.character_name),
		"player_class": PacketTypes.PlayerClass.MAGE,
		"player_level": 1,
		"character_mode": "softcore",
		"selected_region": "local",
		"selected_region_url": "127.0.0.1:8082",
	})
	DisplayServer.window_set_title("Omega local smoke — " + str(_config.role))
	NetworkManager.server_message_received.connect(_on_message)
	NetworkManager.connection_error.connect(func(reason: String): _fail(reason))
	NetworkManager.disconnected_from_server.connect(_on_disconnected)
	get_tree().create_timer(19.0).timeout.connect(func(): _fail("Client watchdog expired"))
	_reset_phase("sanctuary")
	await NetworkManager.connect_to_server("127.0.0.1:8082", AuthManager.get_token())
	if not NetworkManager.is_server_connected():
		_fail("Sanctuary connection failed")
		return
	SceneManager.goto_sanctuary()


func _process(_delta: float) -> void:
	if _failed or _stopping or _config.is_empty():
		return
	var now := Time.get_ticks_msec()
	if now < _next_status_ms:
		return
	_next_status_ms = now + 100
	var command := FileAccess.get_file_as_string(str(_config.command_path)).strip_edges()
	if command == "quit":
		_finish()
		return
	if command == "arena" and _phase == "sanctuary":
		_travel_to_arena()
		return
	_drive_player()
	_write_status()


func _reset_phase(phase: String) -> void:
	_phase = phase
	_phase_started_ms = Time.get_ticks_msec()
	_entity_id = -1
	_snapshots = 0
	_confirms = 0
	_progress = false
	_self_seen = false
	_peer_id = -1
	_first_position = Vector2.INF
	_distance = 0.0
	_shots = 0
	_monster_events = 0
	_last_snapshot_ms = 0
	_release_input()
	print("[LocalStackSmoke] %s entering %s" % [_config.role, phase])


func _travel_to_arena() -> void:
	var scene := SceneManager.get_current_scene()
	var portal: Portal = null
	for node: Node in scene.find_children("*", "Area2D", true, false):
		if node is Portal and node.destination == Portal.Destination.ARENA:
			portal = node
			break
	if portal == null:
		_fail("Sanctuary has no Arena portal")
		return
	_reset_phase("arena")
	# Activate the real portal without spending the smoke budget walking across town.
	# It disconnects, obtains a fresh ticket, connects to :8081 and switches scenes.
	portal._activate()


func _drive_player() -> void:
	_release_input()
	var scene := SceneManager.get_current_scene()
	if not scene is ArenaBase or SceneManager.is_scene_transitioning():
		return
	if not scene._local_player_authority_synced or scene.local_player == null:
		return
	var direction := Vector2.RIGHT if _config.role == "client" else Vector2.LEFT
	if _phase == "sanctuary":
		# Oscillate within the spawn square; server confirms must show real movement.
		if (Time.get_ticks_msec() - _phase_started_ms) / 700 % 2 == 1:
			direction = -direction
	else:
		var player_position: Vector2 = scene.local_player.global_position
		var nearest: Node2D = null
		var best_distance := INF
		for monster: Node2D in scene.client_entity_manager.monster_entities.values():
			var distance := player_position.distance_squared_to(monster.global_position)
			if distance < best_distance:
				nearest = monster
				best_distance = distance
		if nearest != null:
			direction = (nearest.global_position - player_position).normalized()
			Input.action_press("shoot")
			if best_distance < 250.0 * 250.0:
				direction = Vector2.ZERO
		else:
			direction = -player_position.normalized()
	if absf(direction.x) > 0.3:
		Input.action_press("move_right" if direction.x > 0.0 else "move_left")
	if absf(direction.y) > 0.3:
		Input.action_press("move_down" if direction.y > 0.0 else "move_up")


func _release_input() -> void:
	for action: String in ["move_up", "move_down", "move_left", "move_right", "shoot"]:
		Input.action_release(action)


func _on_message(kind: int, data: Dictionary) -> void:
	match kind:
		NetworkManager.MessageType.AUTH_RESULT:
			if int(data.get("result", -1)) != 0:
				_fail("Authentication rejected: %s" % data.get("result", -1))
			else:
				_entity_id = int(data.get("entity_id", -1))
		NetworkManager.MessageType.STATE_UPDATE:
			_snapshots += 1
			_last_snapshot_ms = Time.get_ticks_msec()
			for entity: Dictionary in data.get("entities", []):
				if int(entity.get("entity_id", -1)) == _entity_id:
					_self_seen = true
		NetworkManager.MessageType.ACTION_CONFIRM:
			_confirms += 1
			var position: Vector2 = data.get("corrected_position", Vector2.INF)
			if position.is_finite():
				if not _first_position.is_finite():
					_first_position = position
				_distance = maxf(_distance, _first_position.distance_to(position))
		NetworkManager.MessageType.GAME_EVENT:
			var event_type: int = data.get("event_type", -1)
			var source: int = data.get("source_id", -1)
			var target: int = data.get("target_id", -1)
			if event_type == PacketTypes.GameEventType.PLAYER_INFO:
				if data.get("event_data", {}).get("character_name", "") == _config.peer_name:
					_peer_id = target
			elif event_type == PacketTypes.GameEventType.PROGRESS and target == _entity_id:
				_progress = true
			elif event_type == PacketTypes.GameEventType.PROJECTILE_FIRED and source == _entity_id:
				_shots += 1
			elif event_type == PacketTypes.GameEventType.DAMAGE:
				if (source == _entity_id and target >= 30000 and target < 40000) \
						or (target == _entity_id and source >= 30000 and source < 40000):
					_monster_events += 1


func _write_status() -> void:
	var scene := SceneManager.get_current_scene()
	var rendered_peer := false
	var monster_count := 0
	var authority_synced := false
	if scene is ArenaBase and scene.client_entity_manager != null:
		rendered_peer = scene.client_entity_manager.player_entities.has(_peer_id)
		monster_count = scene.client_entity_manager.monster_entities.size()
		authority_synced = scene._local_player_authority_synced
	var expected_scene := SceneManager.SCENE_SANCTUARY if _phase == "sanctuary" else SceneManager.SCENE_ARENA
	var ready := not _failed and scene != null and scene.scene_file_path == expected_scene \
		and not SceneManager.is_scene_transitioning() and authority_synced \
		and _entity_id > 0 and _self_seen and rendered_peer and _progress \
		and _snapshots >= 5 and _confirms >= 3 and _distance > 5.0 \
		and Time.get_ticks_msec() - _last_snapshot_ms < 1000
	if _phase == "arena":
		ready = ready and monster_count > 0 and _shots > 0
	var status := {
		"role": _config.role, "phase": _phase, "ready": ready, "failed": _failed,
		"entity_id": _entity_id, "peer_id": _peer_id, "peer_rendered": rendered_peer,
		"snapshots": _snapshots, "confirms": _confirms, "hydrated": _progress,
		"movement": _distance, "shots": _shots, "monsters": monster_count,
		"monster_interactions": _monster_events,
	}
	var path := str(_config.status_path)
	var file := FileAccess.open(path + ".tmp", FileAccess.WRITE)
	file.store_string(JSON.stringify(status))
	file.close()
	DirAccess.rename_absolute(path + ".tmp", path)


func _on_disconnected(reason: String) -> void:
	if reason not in ["Portal travel", "smoke complete"]:
		_fail("Unexpected disconnect: " + reason)


func _finish() -> void:
	_stopping = true
	_release_input()
	var scene := SceneManager.get_current_scene()
	if scene is ArenaBase:
		scene._is_leaving_arena = true
	NetworkManager.disconnect_from_server("smoke complete")
	AudioManager.stop_music(false)
	AudioManager.stop_charge_loop()
	for player: Node in AudioManager.get_children():
		if player is AudioStreamPlayer or player is AudioStreamPlayer2D:
			player.stop()
			player.stream = null
	if is_instance_valid(scene):
		scene.queue_free()
	SceneManager.current_scene = null
	get_tree().current_scene = null
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.15).timeout
	print("[LocalStackSmoke] %s PASS" % _config.role)
	get_tree().quit(0)


func _fail(reason: String) -> void:
	if _failed:
		return
	_failed = true
	push_error("[LocalStackSmoke] FAIL: " + reason)
	if not _config.is_empty():
		_write_status()
	get_tree().quit(1)
