## ArenaBase - Arena scene controller
## Manages spawn points, draws arena floor, and provides arena utilities
## Used by both client (visual) and server (spawn logic)
## In client mode: sets up local player, interpolation, entity management, camera, HUD
extends Node2D

## Preloaded player scene for local player
const PLAYER_SCENE_PATH := "res://scenes/shared/player/player.tscn"

## HUD script paths (loaded at runtime to avoid server-mode issues)
const DEATH_SCREEN_PATH := "res://scripts/client/hud/death_screen.gd"
const HP_BAR_PATH := "res://scripts/client/hud/hp_bar.gd"
const KILL_FEED_PATH := "res://scripts/client/hud/kill_feed.gd"
const MINIMAP_PATH := "res://scripts/client/hud/minimap.gd"
const LEADERBOARD_PATH := "res://scripts/client/hud/leaderboard.gd"
const SERVER_STATUS_PATH := "res://scripts/client/hud/server_status.gd"
const PAUSE_MENU_PATH := "res://scripts/client/hud/pause_menu.gd"
const CONNECTION_LOST_PATH := "res://scripts/client/hud/connection_lost_overlay.gd"

## Arena dimensions from GameConstants
var arena_min: Vector2 = GameConstants.MAP_MIN
var arena_max: Vector2 = GameConstants.MAP_MAX

## Cached spawn point arrays
var _player_spawns: Array[Vector2] = []
var _monster_spawns: Array[Vector2] = []

## Floor drawing colors
const FLOOR_COLOR := Color(0.12, 0.12, 0.15, 1.0)
const GRID_COLOR := Color(0.18, 0.18, 0.22, 1.0)
const BORDER_COLOR := Color(0.4, 0.15, 0.15, 1.0)
const GRID_CELL_SIZE := 64.0
const BORDER_WIDTH := 4.0

## Runtime mode
var is_server: bool = false

## Client-only components (null in server mode)
var local_player: Player = null
var prediction_controller: PredictionController = null
var interpolation_controller: InterpolationController = null
var client_entity_manager: ClientEntityManager = null
var camera: Camera2D = null

## HUD components (null in server mode)
var death_screen: Control = null
var hp_bar: Control = null
var kill_feed: Control = null
var minimap: Control = null
var leaderboard: Control = null
var server_status: Control = null
var pause_menu: Control = null
var connection_lost_overlay: Control = null

## Last known killer for death screen
var _last_killer_id: int = -1

## Track if client has been initialized
var _client_initialized: bool = false


func _ready() -> void:
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	_cache_spawn_points()

	if is_server:
		# Server doesn't need visuals
		set_process(false)
	else:
		queue_redraw()
		_setup_client()


func _process(_delta: float) -> void:
	if is_server:
		return

	# Update entity visuals from interpolation data
	if client_entity_manager:
		client_entity_manager.update_entity_visuals()

	# Camera follows local player
	if camera and local_player and is_instance_valid(local_player):
		camera.position = local_player.position

	# Update HP bar from local player
	_update_hp_bar()


## Set up client-side systems
func _setup_client() -> void:
	if _client_initialized:
		return
	_client_initialized = true

	var entity_container := get_entity_container()
	if entity_container == null:
		push_error("[ArenaBase] EntityContainer not found!")
		return

	# Create Camera2D for the client
	camera = Camera2D.new()
	camera.name = "ArenaCamera"
	camera.zoom = Vector2(1.5, 1.5)
	camera.position_smoothing_enabled = true
	camera.position_smoothing_speed = 10.0
	add_child(camera)

	# Create InterpolationController for remote entities
	interpolation_controller = InterpolationController.new()
	interpolation_controller.name = "InterpolationController"
	add_child(interpolation_controller)

	# Create ClientEntityManager
	client_entity_manager = ClientEntityManager.new()
	client_entity_manager.name = "ClientEntityManager"
	add_child(client_entity_manager)
	client_entity_manager.setup(entity_container, interpolation_controller)

	# Listen for auth response to spawn local player
	NetworkManager.server_message_received.connect(_on_server_message)

	# Listen for connection events
	NetworkManager.disconnected_from_server.connect(_on_disconnected)
	NetworkManager.connected_to_server.connect(_on_reconnected)

	# Spawn local player
	_spawn_local_player(entity_container)

	# Set up HUD
	_setup_hud()

	print("[ArenaBase] Client setup complete")


## Spawn the local player and wire up prediction
func _spawn_local_player(entity_container: Node2D) -> void:
	var player_scene := load(PLAYER_SCENE_PATH)
	if player_scene == null:
		push_error("[ArenaBase] Failed to load player scene")
		return

	local_player = player_scene.instantiate()
	local_player.name = "LocalPlayer"
	local_player.position = get_random_player_spawn()
	entity_container.add_child(local_player)

	# Connect local player signals for audio
	local_player.shot_fired.connect(_on_local_player_shot)

	# Create and attach PredictionController
	prediction_controller = PredictionController.new()
	prediction_controller.name = "PredictionController"
	local_player.add_child(prediction_controller)

	# Set up prediction with initial position
	# Entity ID will be set when we receive auth confirmation
	prediction_controller.setup(local_player, local_player.position)

	# Camera starts at player position
	if camera:
		camera.position = local_player.position

	print("[ArenaBase] Local player spawned at %s" % local_player.position)


## Set up HUD components on the HUDLayer
func _setup_hud() -> void:
	var hud_layer := get_hud_layer()
	if hud_layer == null:
		push_error("[ArenaBase] HUDLayer not found!")
		return

	# HP Bar (bottom center)
	hp_bar = _create_hud_component(HP_BAR_PATH, "HPBar")
	hud_layer.add_child(hp_bar)

	# Kill Feed (top right, below minimap)
	kill_feed = _create_hud_component(KILL_FEED_PATH, "KillFeed")
	hud_layer.add_child(kill_feed)

	# Minimap (top right)
	minimap = _create_hud_component(MINIMAP_PATH, "Minimap")
	hud_layer.add_child(minimap)
	# Wire minimap references after it's in tree
	minimap.interpolation_controller = interpolation_controller
	minimap.local_player = local_player

	# Leaderboard (top left)
	leaderboard = _create_hud_component(LEADERBOARD_PATH, "Leaderboard")
	hud_layer.add_child(leaderboard)

	# Server Status (bottom left)
	server_status = _create_hud_component(SERVER_STATUS_PATH, "ServerStatus")
	hud_layer.add_child(server_status)

	# Death Screen (full overlay, hidden by default)
	death_screen = _create_hud_component(DEATH_SCREEN_PATH, "DeathScreen")
	death_screen.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud_layer.add_child(death_screen)

	# Pause Menu (full overlay, hidden by default)
	pause_menu = _create_hud_component(PAUSE_MENU_PATH, "PauseMenu")
	pause_menu.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud_layer.add_child(pause_menu)
	pause_menu.leave_arena_requested.connect(_on_leave_arena)

	# Connection Lost Overlay (full overlay, hidden by default)
	connection_lost_overlay = _create_hud_component(CONNECTION_LOST_PATH, "ConnectionLost")
	connection_lost_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud_layer.add_child(connection_lost_overlay)
	connection_lost_overlay.reconnect_failed.connect(_on_reconnect_failed)

	print("[ArenaBase] HUD setup complete")


## Helper to create a HUD component from script path
func _create_hud_component(script_path: String, node_name: String) -> Control:
	var node := Control.new()
	node.set_script(load(script_path))
	node.name = node_name
	return node


## Handle server messages for arena-level events
func _on_server_message(message_type: int, data: Dictionary) -> void:
	match message_type:
		NetworkManager.MessageType.GAME_EVENT:
			_handle_game_event(data)
		NetworkManager.MessageType.STATE_UPDATE:
			_handle_state_update_for_local_player(data)


## Handle game events
func _handle_game_event(data: Dictionary) -> void:
	var event_type: int = data.get("event_type", 0)

	match event_type:
		PacketTypes.GameEventType.PLAYER_INFO:
			_handle_player_info(data)
		PacketTypes.GameEventType.RESPAWN:
			_handle_respawn_event(data)
		PacketTypes.GameEventType.DAMAGE:
			_handle_damage_event(data)
		PacketTypes.GameEventType.KILL_PVP:
			_handle_kill_pvp_event(data)
		PacketTypes.GameEventType.KILL:
			_handle_kill_event(data)
		PacketTypes.GameEventType.LEADERBOARD_UPDATE:
			_handle_leaderboard_update(data)


## Handle PLAYER_INFO event - detect our own entity ID
func _handle_player_info(data: Dictionary) -> void:
	var entity_id: int = data.get("target_id", -1)
	var char_name: String = data.get("event_data", {}).get("character_name", "")

	# Check if this is our own player info
	var our_char_name: String = GameManager.player_data.get("character_name", "")
	if char_name == our_char_name and entity_id > 0:
		# This is us! Set our entity ID
		GameManager.set_local_player_entity_id(entity_id)

		if prediction_controller:
			prediction_controller.local_entity_id = entity_id
			print("[ArenaBase] Local player entity ID set: %d" % entity_id)

		# Clean up any accidentally spawned remote player for our entity
		# (can happen if STATE_UPDATE arrived before PLAYER_INFO)
		if client_entity_manager and client_entity_manager.player_entities.has(entity_id):
			client_entity_manager._despawn_remote_player(entity_id)
		return

	# Update name in remote player if it exists
	if client_entity_manager and client_entity_manager.player_entities.has(entity_id):
		var remote_player: RemotePlayer = client_entity_manager.player_entities[entity_id]
		if is_instance_valid(remote_player):
			remote_player.set_character_name(char_name)


## Handle state updates to extract local player HP/flags
func _handle_state_update_for_local_player(data: Dictionary) -> void:
	var local_id := GameManager.get_local_player_entity_id()
	if local_id < 0:
		return

	var entities: Array = data.get("entities", [])
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id == local_id:
			_sync_local_player_state(entity_data)
			break


## Sync local player state from server (HP, flags, etc.)
func _sync_local_player_state(entity_data: Dictionary) -> void:
	if local_player == null or not is_instance_valid(local_player):
		return

	var flags: int = entity_data.get("flags", 0)
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0

	# Sync alive state - detect death
	if not is_alive and local_player.action_state != Player.ActionState.DEAD:
		local_player.action_state = Player.ActionState.DEAD
		local_player.velocity = Vector2.ZERO
		local_player.set_input_enabled(false)

		# Play death sound
		var audio := _get_audio_manager()
		if audio:
			audio.play_player_death()

		# Show death screen
		if death_screen:
			death_screen.show_death(_last_killer_id)

	# Sync invulnerability visual
	var is_invulnerable := (flags & PacketTypes.ENTITY_FLAG_INVULNERABLE) != 0
	if local_player.animated_sprite:
		if is_invulnerable:
			local_player.animated_sprite.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 100.0)
		elif local_player.animated_sprite.modulate.a != 1.0:
			local_player.animated_sprite.modulate.a = 1.0


## Handle respawn event
func _handle_respawn_event(data: Dictionary) -> void:
	var entity_id: int = data.get("target_id", -1)
	var local_id := GameManager.get_local_player_entity_id()

	if entity_id == local_id and local_player and is_instance_valid(local_player):
		var respawn_pos: Vector2 = data.get("event_data", {}).get("position", Vector2.ZERO)
		local_player.reset()
		local_player.position = respawn_pos

		if prediction_controller:
			prediction_controller.force_sync(respawn_pos)

		# Hide death screen
		if death_screen:
			death_screen.hide_death()

		_last_killer_id = -1
		print("[ArenaBase] Local player respawned at %s" % respawn_pos)


## Handle damage event
func _handle_damage_event(data: Dictionary) -> void:
	var target_id: int = data.get("target_id", -1)
	var local_id := GameManager.get_local_player_entity_id()

	if target_id == local_id and local_player and is_instance_valid(local_player):
		var amount: int = data.get("event_data", {}).get("amount", 0)
		if amount > 0 and local_player.hp_component:
			local_player.hp_component.take_damage(amount)

			# Play hit sound for local player taking damage
			var audio := _get_audio_manager()
			if audio:
				audio.play_player_hit()

		# Track killer for death screen
		var source_id: int = data.get("source_id", -1)
		if source_id > 0:
			_last_killer_id = source_id


## Handle PvP kill event (for kill feed)
func _handle_kill_pvp_event(data: Dictionary) -> void:
	var killer_id: int = data.get("source_id", 0)
	var victim_id: int = data.get("target_id", 0)

	var killer_name := EntityNameCache.get_entity_name(killer_id)
	var victim_name := EntityNameCache.get_entity_name(victim_id)

	# Kill feed message for all clients
	if kill_feed:
		kill_feed.add_kill(killer_name, victim_name)

	# Update local stats
	var local_id := GameManager.get_local_player_entity_id()
	if killer_id == local_id:
		GameManager.update_stat("pvp_kills", 1)

		# Show "You eliminated [Name]" notification for the killer
		_show_kill_notification(victim_name)

		# Play kill sound effect
		_get_audio_manager().play_player_kill()

		# Flash killer's name in leaderboard
		if leaderboard:
			leaderboard.flash_player(killer_id)

	if victim_id == local_id:
		GameManager.update_stat("deaths", 1)


## Handle generic kill event (PvE)
func _handle_kill_event(data: Dictionary) -> void:
	var killer_id: int = data.get("source_id", 0)
	var victim_id: int = data.get("target_id", 0)
	var local_id := GameManager.get_local_player_entity_id()

	# Player killed a monster
	if killer_id == local_id and victim_id >= 100000:
		GameManager.update_stat("monster_kills", 1)

	# Monster killed a player - show in kill feed
	if killer_id >= 100000 and victim_id < 100000 and kill_feed:
		var victim_name := EntityNameCache.get_entity_name(victim_id)
		kill_feed.add_kill("Monster", victim_name)


## Handle leaderboard update
func _handle_leaderboard_update(data: Dictionary) -> void:
	var entries: Array = data.get("event_data", {}).get("entries", [])
	if leaderboard:
		leaderboard.update_entries(entries)

	# Update server status player count from leaderboard entry count
	if server_status:
		var region: String = GameManager.player_data.get("selected_region", "")
		server_status.update_player_count(entries.size(), 100, region)


## Handle local player shooting (for audio)
func _on_local_player_shot(_pos: Vector2, _dir: Vector2) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_player_shoot()


## Show a "You eliminated [Name]" notification for the local player
func _show_kill_notification(victim_name: String) -> void:
	var hud_layer := get_hud_layer()
	if hud_layer == null:
		return

	var label := Label.new()
	label.text = "You eliminated %s" % victim_name
	label.add_theme_font_size_override("font_size", 22)
	label.add_theme_color_override("font_color", Color(1.0, 0.3, 0.3))
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER

	# Position top-center, below server status
	label.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	label.offset_top = 70
	label.offset_bottom = 100
	label.offset_left = -200
	label.offset_right = 200

	hud_layer.add_child(label)

	# Fade out after 2 seconds, then free
	var tween := label.create_tween()
	tween.tween_property(label, "modulate:a", 0.0, 1.0).set_delay(2.0)
	tween.tween_callback(label.queue_free)


## Get AudioManager singleton
func _get_audio_manager() -> Node:
	return get_tree().root.get_node_or_null("AudioManager")


## Update HP bar from local player's HP component
func _update_hp_bar() -> void:
	if hp_bar == null or local_player == null or not is_instance_valid(local_player):
		return
	if local_player.hp_component == null:
		return
	hp_bar.update_hp(local_player.hp_component.current_hp, local_player.hp_component.max_hp)


## Handle disconnect from server
func _on_disconnected(_reason: String) -> void:
	if GameManager.current_state == GameManager.GameState.IN_ARENA:
		if connection_lost_overlay:
			connection_lost_overlay.show_overlay()


## Handle reconnection to server
func _on_reconnected() -> void:
	if connection_lost_overlay and connection_lost_overlay.visible:
		connection_lost_overlay.hide_overlay()


## Handle reconnect failure - return to main menu
func _on_reconnect_failed() -> void:
	_leave_arena()


## Handle leave arena request from pause menu
func _on_leave_arena() -> void:
	_leave_arena()


## Leave arena: disconnect and return to main menu
func _leave_arena() -> void:
	GameManager.change_state(GameManager.GameState.MAIN_MENU)
	NetworkManager.disconnect_from_server("Leave arena")
	SceneManager.goto_main_menu()


## Called when exiting the arena scene
func on_scene_exit() -> void:
	if not is_server:
		# Disconnect signals
		if NetworkManager.server_message_received.is_connected(_on_server_message):
			NetworkManager.server_message_received.disconnect(_on_server_message)
		if NetworkManager.disconnected_from_server.is_connected(_on_disconnected):
			NetworkManager.disconnected_from_server.disconnect(_on_disconnected)
		if NetworkManager.connected_to_server.is_connected(_on_reconnected):
			NetworkManager.connected_to_server.disconnect(_on_reconnected)

		# Cleanup client resources
		if client_entity_manager:
			client_entity_manager.clear_all()
		if interpolation_controller:
			interpolation_controller.clear_all_entities()

		GameManager.clear_local_player_entity_id()

	print("[ArenaBase] Scene exit cleanup complete")


## Cache spawn point positions from child Marker2D nodes
func _cache_spawn_points() -> void:
	_player_spawns.clear()
	_monster_spawns.clear()

	var spawn_container = get_node_or_null("SpawnPoints")
	if spawn_container == null:
		push_warning("[ArenaBase] SpawnPoints node not found")
		return

	for child in spawn_container.get_children():
		if child is Marker2D:
			if child.name.begins_with("PlayerSpawn"):
				_player_spawns.append(child.position)
			elif child.name.begins_with("MonsterSpawn"):
				_monster_spawns.append(child.position)

	print("[ArenaBase] Cached %d player spawns, %d monster spawns" % [
		_player_spawns.size(), _monster_spawns.size()
	])


## Get a random player spawn position
func get_random_player_spawn() -> Vector2:
	if _player_spawns.is_empty():
		return Vector2.ZERO
	return _player_spawns[randi() % _player_spawns.size()]


## Get a random monster spawn position
func get_random_monster_spawn() -> Vector2:
	if _monster_spawns.is_empty():
		return Vector2.ZERO
	return _monster_spawns[randi() % _monster_spawns.size()]


## Get all player spawn positions
func get_all_player_spawns() -> Array[Vector2]:
	return _player_spawns


## Get all monster spawn positions
func get_all_monster_spawns() -> Array[Vector2]:
	return _monster_spawns


## Get the EntityContainer node for adding dynamic entities
func get_entity_container() -> Node2D:
	return get_node_or_null("EntityContainer")


## Get the HUD layer for adding UI elements
func get_hud_layer() -> CanvasLayer:
	return get_node_or_null("HUDLayer")


## Draw arena floor and grid
func _draw() -> void:
	# Draw floor background
	var arena_rect := Rect2(arena_min, arena_max - arena_min)
	draw_rect(arena_rect, FLOOR_COLOR, true)

	# Draw grid lines
	var x := arena_min.x
	while x <= arena_max.x:
		draw_line(Vector2(x, arena_min.y), Vector2(x, arena_max.y), GRID_COLOR, 1.0)
		x += GRID_CELL_SIZE

	var y := arena_min.y
	while y <= arena_max.y:
		draw_line(Vector2(arena_min.x, y), Vector2(arena_max.x, y), GRID_COLOR, 1.0)
		y += GRID_CELL_SIZE

	# Draw border
	draw_rect(arena_rect, BORDER_COLOR, false, BORDER_WIDTH)
