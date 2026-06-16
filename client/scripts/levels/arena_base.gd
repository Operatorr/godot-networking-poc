## ArenaBase - Arena scene controller
## Manages spawn points, draws arena floor, and provides arena utilities
## Used by both client (visual) and server (spawn logic)
## In client mode: sets up local player, interpolation, entity management, camera, HUD
extends Node2D
## Global class so subclasses (e.g. Sanctuary) can `extends ArenaBase` and headless
## startup resolves the base class without a path-based preload.
class_name ArenaBase

## Preloaded player scene for local player
const PLAYER_SCENE_PATH := "res://scenes/entities/player/player.tscn"

## Tile atlas generation
const TILE_ATLAS_COLUMNS := 3
const ENVIRONMENT_COLLISION_LAYER := 8
const TILEMAP_Z_INDEX := -10

## The shared HUD scene. Loaded at runtime (never preloaded / ext-referenced by a level scene)
## so the client-only HUD scripts stay out of the headless parse graph — see game_hud.gd.
const GAME_HUD_PATH := "res://scenes/ui/hud/game_hud.tscn"

## Arena dimensions from GameConstants
var arena_min: Vector2 = GameConstants.MAP_MIN
var arena_max: Vector2 = GameConstants.MAP_MAX

## Cached spawn point arrays
var _player_spawns: Array[Vector2] = []
var _monster_spawns: Array[Vector2] = []

## Floor drawing colors - Cosmic horror organic tissue aesthetic
const FLOOR_COLOR := Color(0.06, 0.04, 0.04, 1.0)    # Dark organic tissue
const GRID_COLOR := Color(0.16, 0.08, 0.14, 1.0)     # Pulsing vein lines
const BORDER_COLOR := Color(0.6, 0.1, 0.1, 1.0)      # Throbbing red border
const GRID_CELL_SIZE := 64.0
const BORDER_WIDTH := 4.0
const VEIN_BRANCH_COLOR := Color(0.2, 0.06, 0.1, 0.4)  # Subtle branching veins

## Runtime mode
var is_server: bool = false

## When false, _draw() paints nothing — a subclass (e.g. the Sanctuary) supplies its own
## ground/decor layers and must not have the dark arena grid/border drawn over them.
var _draws_arena_floor: bool = true

## When false, _draw() skips the opaque FLOOR_COLOR fill AND the vein grid + branches (the
## sprite ground layer is the look now); only obstacles + border still draw on top. Set false by
## _build_arena_floor_decor() once the sprite-based ground layer is in place, so the textured
## floor shows through the grimdark overlay.
var _paint_solid_floor: bool = true

## Client-only components (null in server mode)
var local_player: Player = null
var prediction_controller: PredictionController = null
var interpolation_controller: InterpolationController = null
var client_entity_manager: ClientEntityManager = null
var local_hit_detector: LocalHitDetector = null
var camera: Camera2D = null

## Screen effects (null in server mode)
var screen_effects: ScreenEffects = null

## The shared HUD (null in server mode). Instanced in _setup_hud(); the refs below mirror its
## widgets so the existing per-widget code in this script keeps working unchanged.
var hud: GameHud = null
var death_screen: Control = null
var hp_bar: Control = null
var stamina_bar: Control = null
var ability_bar: Control = null
var mana_bar: Control = null
var kill_feed: Control = null
var minimap: Control = null
var leaderboard: Control = null
var server_status: Control = null
var pause_menu: Control = null
var connection_lost_overlay: Control = null

## Last known killer for death screen
var _last_killer_id: int = -1
var _local_death_feedback_played: bool = false
## Set when the local player suffered a hardcore (permadeath) death. The server converts
## XP→Glory, deletes the character, then kicks us; this flag both selects the permadeath
## death screen and suppresses the reconnect overlay for that expected disconnect.
var _hardcore_death: bool = false
## Glory this death converts, snapshotted at death time so the death screen and the later
## main-menu fold-in show the SAME number even if a late PROGRESS event changes level/XP after.
var _death_glory: int = 0

## Cached AudioManager reference (lazy-initialized)
var _cached_audio_manager: Node = null

## Track if client has been initialized
var _client_initialized: bool = false
var _is_leaving_arena: bool = false

## True once the local player has been snapped to an authoritative server state.
var _local_player_authority_synced: bool = false

## Low-volume projectile sync diagnostics from client config.
var projectile_sync_debug_logging: bool = false

## Camera zoom settings live in GameConstants (single source of truth) so the
## arena and the offline modes share one look. See GameConstants.CAMERA_ZOOM_*.
const SERVER_STATUS_MAX_PLAYERS := 100

## Kill streak tracking
var _kill_streak_count: int = 0
var _kill_streak_timer: float = 0.0
const KILL_STREAK_WINDOW := 5.0  # Seconds between kills to count as streak


func _ready() -> void:
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	# The arena floor _draw()n by this node shows in BOTH the main view and the minimap
	# (terrain whitelist — see GameConstants / scripts/ui/hud/minimap.gd).
	visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY

	_build_level_environment()
	_rebuild_spawn_markers()
	_cache_spawn_points()

	if is_server:
		# Server doesn't need visuals
		set_process(false)
	else:
		queue_redraw()
		_setup_client()


## Build the level's static environment (tilemap floor, walls, obstacle cells, and — on the
## client — cosmetic props). Overridable so a subclass can be a different "level": the
## Sanctuary replaces this with its own town builders and its own EntityContainer.
## Runs in BOTH server and client mode, before _setup_client().
func _build_level_environment() -> void:
	_setup_arena_tilemap()
	if not is_server:
		_build_arena_floor_decor()
		_build_arena_props()


## The world geometry [min, max, obstacles_enabled] of the instance this scene connects to.
## Pushed into the shared prediction sim in _setup_client() BEFORE the first predicted step so
## client prediction matches the server. Defaults to the Arena (±1000 with obstacles); the
## Sanctuary overrides this to its ±1856 walk-through bounds.
func _world_geometry() -> Array:
	return [Vector2(-1000.0, -1000.0), Vector2(1000.0, 1000.0), true]


## Overridable hook called at the END of _setup_client() (client only), once the camera,
## interpolation, ClientEntityManager, prediction, and HUD all exist. A subclass (Sanctuary)
## builds decor/NPCs/portal here when they need the entity container or HUD layer present.
func _after_client_setup() -> void:
	pass


## Forward a world-geometry change into the prediction sim owned by the PredictionController.
## Must run on the main thread (prediction's thread) BEFORE the first predicted step — the sim
## geometry is a thread-local in the shared Rust core. Guarded so it is a no-op before the
## controller spawns or if the GDExtension lacks the method.
func set_world_geometry(min_bound: Vector2, max_bound: Vector2, obstacles_enabled: bool) -> void:
	if prediction_controller == null:
		return
	if prediction_controller.has_method("set_world_geometry"):
		prediction_controller.set_world_geometry(min_bound, max_bound, obstacles_enabled)


func _process(delta: float) -> void:
	if is_server:
		return

	# Update entity visuals from interpolation data
	if client_entity_manager:
		client_entity_manager.update_entity_visuals()
		if server_status and server_status.has_method("update_monster_count"):
			server_status.update_monster_count(
				client_entity_manager.monster_entities.size(),
				GameConstants.MONSTER_MAX_COUNT
			)

	# Client-side incoming monster-projectile hit detection runs after visuals so
	# it tests against the positions actually on screen this frame.
	if local_hit_detector:
		local_hit_detector.update()

	if camera and local_player and is_instance_valid(local_player):
		# Camera zoom on sprint — gated on the actual sprint state (not raw input) so the
		# zoom snaps back the instant the player is exhausted and can no longer sprint.
		var target_zoom := GameConstants.CAMERA_ZOOM_DEFAULT
		if local_player.is_sprinting():
			target_zoom = GameConstants.CAMERA_ZOOM_SPRINT
		camera.zoom = camera.zoom.lerp(target_zoom, clampf(delta * GameConstants.CAMERA_ZOOM_SPEED, 0.0, 1.0))

	# Kill streak timer decay
	if _kill_streak_timer > 0.0:
		_kill_streak_timer -= delta
		if _kill_streak_timer <= 0.0:
			_kill_streak_count = 0

	# Invulnerability shield visual
	_update_invuln_shield()


func _snap_camera_to(target_position: Vector2) -> void:
	if camera == null:
		return

	camera.position = target_position
	camera.reset_smoothing()
	camera.reset_physics_interpolation()


func _on_local_player_visual_position_updated(target_position: Vector2, is_discontinuous: bool) -> void:
	if camera == null:
		return

	if is_discontinuous:
		_snap_camera_to(target_position)
	else:
		camera.position = target_position


## Set up client-side systems
func _setup_client() -> void:
	if _client_initialized:
		return
	_client_initialized = true
	var client_config := ClientConfig.new()
	projectile_sync_debug_logging = client_config.projectile_sync_debug_logging

	var entity_container := get_entity_container()
	if entity_container == null:
		push_error("[ArenaBase] EntityContainer not found!")
		return

	# Create Camera2D for the client
	camera = Camera2D.new()
	camera.name = "ArenaCamera"
	camera.zoom = GameConstants.CAMERA_ZOOM_DEFAULT
	# The camera follows an already-interpolated target path. Camera2D position
	# smoothing is forced to physics mode when physics interpolation is enabled,
	# which adds warning noise and extra follow lag here.
	camera.position_smoothing_enabled = false
	# Match the callback Godot requires under physics interpolation before the
	# camera enters the tree, avoiding the engine-side override warning.
	camera.process_callback = Camera2D.CAMERA2D_PROCESS_PHYSICS
	add_child(camera)
	# Camera position is written on physics ticks by PredictionController, so let
	# Godot interpolate Camera2D between those physics states on render frames.
	camera.set_physics_interpolation_mode(Node.PHYSICS_INTERPOLATION_MODE_ON)

	# Create ScreenEffects
	screen_effects = ScreenEffects.new()
	screen_effects.name = "ScreenEffects"
	screen_effects.camera = camera
	add_child(screen_effects)

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

	# Spawn local player (creates the PredictionController that owns the shared sim).
	_spawn_local_player(entity_container)

	# Push THIS instance's world geometry into the prediction sim BEFORE the first predicted
	# step or the handshake — the sim geometry is a thread-local set on the main thread, and
	# prediction must match the server the moment authority syncs. A client returning from the
	# Sanctuary resets to the Arena geometry here (the Sanctuary overrides _world_geometry()).
	var geom := _world_geometry()
	set_world_geometry(geom[0], geom[1], geom[2])

	# Now that the message listener is wired, drive the auth handshake from the
	# arena so PLAYER_INFO cannot arrive before _on_server_message is connected.
	# Backstop: request a full state so a missed PLAYER_INFO can still recover.
	NetworkManager.send_auth_handshake()
	NetworkManager.send_message(NetworkManager.MessageType.REQUEST_FULL_STATE, {})

	# Set up HUD
	_setup_hud()

	# Start arena music
	var audio := _get_audio_manager()
	if audio:
		audio.play_music("arena_ambience")

	# Subclass decor/NPCs that need the client/HUD/entity-container to exist.
	_after_client_setup()

	print("[ArenaBase] Client setup complete")


## Spawn the local player and wire up prediction
func _spawn_local_player(entity_container: Node2D) -> void:
	var player_scene := load(PLAYER_SCENE_PATH)
	if player_scene == null:
		push_error("[ArenaBase] Failed to load player scene")
		return

	local_player = player_scene.instantiate()
	local_player.name = "LocalPlayer"
	local_player.position = Vector2.ZERO
	local_player.set_player_color(GameManager.player_data.get("player_color", Color(0.27, 0.53, 1.0)))
	local_player.visible = false
	entity_container.add_child(local_player)
	local_player.set_input_enabled(false)
	local_player.set_local_projectile_spawning_enabled(false)
	# PredictionController is the sole mover for the networked local player; stop
	# Player.gd from also running move_and_slide (kills the double-movement jitter).
	local_player.prediction_owns_movement = true

	# Connect local player signals for audio
	local_player.shot_fired.connect(_on_local_player_shot)

	# Create and attach PredictionController
	prediction_controller = PredictionController.new()
	prediction_controller.name = "PredictionController"
	prediction_controller.interpolation_controller = interpolation_controller
	prediction_controller.projectile_sync_debug_logging = projectile_sync_debug_logging
	prediction_controller.visual_position_updated.connect(_on_local_player_visual_position_updated)
	prediction_controller.shoot_predicted.connect(_on_local_shoot_predicted)
	local_player.add_child(prediction_controller)

	# Set up prediction in pending mode. Entity ID and spawn position come from server state.
	prediction_controller.setup(local_player, local_player.position)

	# Client-side detection of incoming monster projectiles (predicted self vs.
	# rendered bullet). The server validates each report before applying damage.
	local_hit_detector = LocalHitDetector.new()
	local_hit_detector.setup(prediction_controller, client_entity_manager, local_player)

	# Camera starts at player position
	if camera:
		_snap_camera_to(local_player.position)

	print("[ArenaBase] Local player spawned pending authoritative server state")


## Instance the shared HUD (a CanvasLayer named "HUDLayer") and wire it up. The per-widget
## refs mirror hud.* so the rest of this script keeps working unchanged.
func _setup_hud() -> void:
	hud = load(GAME_HUD_PATH).instantiate()
	hud.name = "HUDLayer"
	add_child(hud)

	hp_bar = hud.health_bar
	stamina_bar = hud.stamina_bar
	ability_bar = hud.ability_bar
	mana_bar = hud.mana_bar
	kill_feed = hud.kill_feed
	minimap = hud.minimap
	leaderboard = hud.leaderboard
	server_status = hud.server_status
	death_screen = hud.death_screen
	pause_menu = hud.pause_menu
	connection_lost_overlay = hud.connection_lost_overlay

	# Minimap/map follow the local player; render the level's static world-map texture once.
	hud.set_minimap_player(local_player)
	hud.setup_world_map(get_map_bounds())

	# The overlay widgets re-emit their actions through the HUD, so connect once here.
	hud.respawn_requested.connect(_on_respawn_requested)
	hud.main_menu_requested.connect(_on_main_menu_requested)
	hud.leave_arena_requested.connect(_on_leave_arena)
	hud.reconnect_failed.connect(_on_reconnect_failed)

	pause_menu.set_leave_button_text("RETURN TO SANCTUARY")
	# While the pause overlay is open, suppress input so clicking its buttons (a left
	# click = the shoot action) doesn't fire a shot through the PredictionController.
	pause_menu.visibility_changed.connect(_on_pause_menu_visibility_changed)

	_connect_local_hp_bar()

	print("[ArenaBase] HUD setup complete")


func _unhandled_input(event: InputEvent) -> void:
	# T / tilde return the player from the networked Arena to the Sanctuary hub.
	if event.is_action_pressed("return_to_sanctuary"):
		if event is InputEventKey and event.echo:
			return
		get_viewport().set_input_as_handled()
		_leave_arena()


## Handle server messages for arena-level events
func _on_server_message(message_type: int, data: Dictionary) -> void:
	match message_type:
		NetworkManager.MessageType.AUTH_RESULT:
			_handle_auth_result(data)
		NetworkManager.MessageType.GAME_EVENT:
			_handle_game_event(data)
		NetworkManager.MessageType.STATE_UPDATE:
			_handle_state_update_for_local_player(data)


## D9: the authoritative entity-id source. Wires the PredictionController directly so input
## flow never depends on the PLAYER_INFO name-match heuristic (which a duplicate character
## name could clobber).
func _handle_auth_result(data: Dictionary) -> void:
	if data.get("result", -1) != 0:
		return
	var entity_id: int = data.get("entity_id", -1)
	if entity_id <= 0:
		return
	GameManager.set_local_player_entity_id(entity_id)
	if prediction_controller:
		prediction_controller.set_local_entity_id(entity_id)
		print("[ArenaBase] Local player entity ID set from AUTH_RESULT: %d" % entity_id)


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
		PacketTypes.GameEventType.PROJECTILE_FIRED:
			_handle_projectile_fired_event(data)
		PacketTypes.GameEventType.EXP_GAIN:
			_handle_exp_gain_event(data)
		PacketTypes.GameEventType.PROGRESS:
			_handle_progress_event(data)
		PacketTypes.GameEventType.PICKUP:
			_handle_pickup_event(data)
		PacketTypes.GameEventType.ABILITY_EFFECT:
			_handle_ability_effect_event(data)


## COSMETIC ONLY. EXP_GAIN no longer drives leveling — the server owns level/XP and pushes
## it via PROGRESS events. For our own player we just spawn a green "+N XP" floater. The
## server emits one EXP_GAIN per nearby player; we keep only our own.
func _handle_exp_gain_event(data: Dictionary) -> void:
	if int(data.get("source_id", 0)) != GameManager.get_local_player_entity_id():
		return
	var amount := int(data.get("event_data", {}).get("amount", 0))
	if amount <= 0:
		return
	# Cosmetic hint (HUD may also listen via GameManager.experience_gained).
	GameManager.grant_experience(amount)
	if local_player and is_instance_valid(local_player):
		_spawn_xp_floater(amount, local_player.global_position)


## Authoritative progression update for a player. Mirrors level/XP into GameManager for the
## HUD and, for the LOCAL player, adopts the new base move speed into prediction so the
## predicted speed tracks the server. The server emits PROGRESS per player; target_id picks
## whose progression this is.
func _handle_progress_event(data: Dictionary) -> void:
	var target_id: int = data.get("target_id", -1)
	if target_id != GameManager.get_local_player_entity_id():
		return
	var event_data: Dictionary = data.get("event_data", {})
	var level := int(event_data.get("level", 1))
	var experience := int(event_data.get("experience", 0))
	var move_speed := int(event_data.get("move_speed", 0))
	GameManager.set_progression(level, experience, move_speed)
	if prediction_controller and move_speed > 0:
		prediction_controller.set_base_speed(float(move_speed))


## Health pickup. Spawn a green "+amount" heal floater at the picked-up player's position and,
## for the local player, mirror the heal into the HUD HP bar (the server stays authoritative —
## the next state update reconciles the exact value). target_id = the player who picked it up.
func _handle_pickup_event(data: Dictionary) -> void:
	var event_data: Dictionary = data.get("event_data", {})
	if int(event_data.get("pickup_kind", -1)) != 0:  # 0 = healthorb
		return
	var amount := int(event_data.get("amount", 0))
	if amount <= 0:
		return

	var target_id: int = data.get("target_id", -1)
	var local_id := GameManager.get_local_player_entity_id()
	var world_pos := Vector2.ZERO

	if target_id == local_id and local_player and is_instance_valid(local_player):
		world_pos = local_player.global_position
		if local_player.hp_component:
			var healed := mini(
				local_player.hp_component.current_hp + amount,
				local_player.hp_component.max_hp
			)
			local_player.hp_component.set_hp(healed)
	elif client_entity_manager and client_entity_manager.player_entities.has(target_id):
		var remote: RemotePlayer = client_entity_manager.player_entities[target_id]
		if is_instance_valid(remote):
			world_pos = remote.global_position

	if world_pos != Vector2.ZERO:
		_spawn_heal_floater(amount, world_pos)


## Transient ability VFX at a world position, sized by radius and styled by effect_id:
## 0 mageblast (blue/white burst), 1 charge_blast (orange ring), 2 mine_detonation
## (red explosion), 3 shadowstep (purple blink). Self-frees after ~0.4s.
func _handle_ability_effect_event(data: Dictionary) -> void:
	var event_data: Dictionary = data.get("event_data", {})
	var effect_id := int(event_data.get("effect_id", 0))
	var world_pos: Vector2 = event_data.get("position", Vector2.ZERO)
	var radius := float(event_data.get("radius", 60))
	var vfx := _AbilityEffectVfx.new()
	vfx.effect_id = effect_id
	vfx.max_radius = maxf(radius, 8.0)
	vfx.position = world_pos
	_add_effect_to_arena(vfx)

	# Ability SFX: Mageblast (0) arcane detonation, Warrior Charge blast (1) heavy slam.
	# Effects 2 (mine detonation) and 3 (shadowstep) are intentionally silent here: the mine
	# has no dedicated detonation SFX, and shadowstep's audio cue is the separate "go invisible"
	# stealth sound played on the STEALTH flag rising edge (see _sync_local_player_state).
	if effect_id == 0:
		var audio := _get_audio_manager()
		if audio != null:
			audio.play_sfx("mageblast", AudioManager.AudioCategory.SFX_PLAYER)
	elif effect_id == 1:
		var audio := _get_audio_manager()
		if audio != null:
			audio.play_sfx("charge", AudioManager.AudioCategory.SFX_PLAYER)


## Handle PLAYER_INFO event - detect our own entity ID
func _handle_player_info(data: Dictionary) -> void:
	var entity_id: int = data.get("target_id", -1)
	var event_data: Dictionary = data.get("event_data", {})
	var char_name: String = event_data.get("character_name", "")
	var server_position: Vector2 = event_data.get("position", Vector2.ZERO)
	var player_color: Color = event_data.get("player_color", Color(0.27, 0.53, 1.0))
	if entity_id > 0:
		EntityNameCache.set_entity_color(entity_id, player_color)

	# Check if this is our own player info. AUTH_RESULT is the authoritative id source;
	# the name match only seeds the id when it is still unknown (legacy fallback), so a
	# duplicate character name can never clobber a known id.
	var known_id: int = GameManager.get_local_player_entity_id()
	var is_us: bool = entity_id > 0 and (
		entity_id == known_id
		or (known_id <= 0 and char_name == GameManager.player_data.get("character_name", ""))
	)
	if is_us:
		GameManager.set_local_player_entity_id(entity_id)

		if prediction_controller:
			prediction_controller.set_local_entity_id(entity_id)
			print("[ArenaBase] Local player entity ID set: %d" % entity_id)
		if local_player and is_instance_valid(local_player):
			local_player.set_player_color(player_color)

		# Force-sync to the server-authoritative spawn so we don't render at
		# Vector2.ZERO until the first STATE_UPDATE arrives. If a future
		# regression sends PLAYER_INFO without a position, the STATE_UPDATE
		# fallback in _handle_state_update_for_local_player still recovers.
		if prediction_controller and not _local_player_authority_synced:
			prediction_controller.force_sync(server_position)
			prediction_controller.set_prediction_enabled(true)
			_local_player_authority_synced = true
			if local_player and is_instance_valid(local_player):
				local_player.visible = true
				local_player.set_input_enabled(true)
			if camera:
				_snap_camera_to(server_position)
			print("[ArenaBase] Local player authority synced from PLAYER_INFO at %s" % server_position)

		# Clean up any accidentally spawned remote player for our entity
		# (can happen if STATE_UPDATE arrived before PLAYER_INFO)
		if client_entity_manager and client_entity_manager.player_entities.has(entity_id):
			client_entity_manager._despawn_remote_player(entity_id)
		if interpolation_controller:
			interpolation_controller.forget_entity(entity_id)
		return

	# Update name in remote player if it exists
	if client_entity_manager and client_entity_manager.player_entities.has(entity_id):
		var remote_player: RemotePlayer = client_entity_manager.player_entities[entity_id]
		if is_instance_valid(remote_player):
			remote_player.set_character_name(char_name)
			remote_player.set_player_color(player_color)


## Handle state updates to extract local player HP/flags
func _handle_state_update_for_local_player(data: Dictionary) -> void:
	var local_id := GameManager.get_local_player_entity_id()
	if local_id < 0:
		return

	var is_delta := (int(data.get("state_flags", 0)) & PacketTypes.STATE_FLAG_IS_DELTA) != 0
	var entities: Array = data.get("entities", [])
	for entity_data in entities:
		var entity_id: int = entity_data.get("entity_id", -1)
		if entity_id == local_id:
			var has_position := _entity_state_has_position(entity_data, is_delta)
			var has_flags := _entity_state_has_flags(entity_data, is_delta)
			if is_delta and not has_position and not has_flags:
				return
			if prediction_controller \
				and (not _local_player_authority_synced) \
				and has_position:
				var server_position: Vector2 = entity_data.get("position", local_player.position)
				prediction_controller.force_sync(server_position)
				prediction_controller.set_prediction_enabled(true)
				_local_player_authority_synced = true
				local_player.visible = true
				local_player.set_input_enabled(true)
				if camera:
					_snap_camera_to(server_position)
				print("[ArenaBase] Local player authority synced at %s" % server_position)
			# Only sync alive/invulnerable state when this packet actually carries
			# the flags field. Position-only deltas decode with flags=0, which would
			# otherwise be misread as "not alive" and falsely trigger the death screen.
			if has_flags:
				_sync_local_player_state(entity_data)
			break


## Whether this state entity contains an authoritative position field.
func _entity_state_has_position(entity_data: Dictionary, is_delta: bool) -> bool:
	if not is_delta:
		return true

	var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
	return (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0 \
		or (delta_mask & PacketTypes.DELTA_MASK_POSITION) != 0


## Whether this state entity contains an authoritative flags field. Delta
## packets without DELTA_MASK_FLAGS arrive with flags=0 from the decoder, so
## consumers must gate alive/dead reads on this check.
func _entity_state_has_flags(entity_data: Dictionary, is_delta: bool) -> bool:
	if not is_delta:
		return true

	var delta_mask: int = entity_data.get("delta_mask", PacketTypes.DELTA_MASK_FULL_STATE)
	return (delta_mask & PacketTypes.DELTA_MASK_FULL_STATE) != 0 \
		or (delta_mask & PacketTypes.DELTA_MASK_FLAGS) != 0


## Sync local player state from server (HP, flags, etc.)
func _sync_local_player_state(entity_data: Dictionary) -> void:
	if local_player == null or not is_instance_valid(local_player):
		return

	var flags: int = entity_data.get("flags", 0)
	var is_alive := (flags & PacketTypes.ENTITY_FLAG_ALIVE) != 0

	# Sync alive state - detect death
	if not is_alive:
		if local_player.action_state != Player.ActionState.DEAD:
			local_player.action_state = Player.ActionState.DEAD
			local_player.movement_state = Player.MovementState.IDLE
			local_player.velocity = Vector2.ZERO
			local_player.set_input_enabled(false)
			if prediction_controller:
				prediction_controller.set_prediction_enabled(false)
			if local_player.hp_component:
				local_player.hp_component.set_hp(0)
		_play_local_death_feedback()

	# Sync invulnerability visual, then Rogue stealth dim. Stealth wins when both are set.
	var is_invulnerable := (flags & PacketTypes.ENTITY_FLAG_INVULNERABLE) != 0
	var is_stealthed := (flags & PacketTypes.ENTITY_FLAG_STEALTH) != 0
	_is_invulnerable = is_invulnerable

	# Play the "go invisible" cue once, on the frame the local player turns stealthed
	# (Shadowstep grants stealth on every cast). Falling edge just resets the latch.
	if is_stealthed and not _local_stealthed:
		var stealth_audio := _get_audio_manager()
		if stealth_audio:
			stealth_audio.play_go_invisible()
	_local_stealthed = is_stealthed

	if local_player.animated_sprite:
		if is_stealthed:
			if local_player.animated_sprite.modulate.a != 0.35:
				local_player.animated_sprite.modulate.a = 0.35
		elif is_invulnerable:
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
		local_player.visible = true
		local_player.set_input_enabled(true)
		_local_player_authority_synced = true

		if prediction_controller:
			# The server resets its movement state machine on respawn; mirror it in the
			# shared Rust sim so dash cooldown / stamina start fresh on both sides.
			prediction_controller.reset_sim()
			prediction_controller.force_sync(respawn_pos)
			prediction_controller.set_prediction_enabled(true)
		if local_hit_detector:
			local_hit_detector.reset()
		if camera:
			_snap_camera_to(respawn_pos)

		# Hide death screen
		if death_screen:
			death_screen.hide_death()

		_is_invulnerable = true
		_last_killer_id = -1
		_local_death_feedback_played = false
		_local_stealthed = false
		print("[ArenaBase] Local player respawned at %s" % respawn_pos)


## Handle damage event
func _handle_damage_event(data: Dictionary) -> void:
	var target_id: int = data.get("target_id", -1)
	var local_id := GameManager.get_local_player_entity_id()
	var amount: int = data.get("event_data", {}).get("amount", 0)
	var source_id: int = data.get("source_id", -1)

	if target_id >= GameConstants.MONSTER_ENTITY_ID_START and client_entity_manager:
		client_entity_manager.apply_monster_damage(target_id, amount)
		return

	if target_id == local_id and local_player and is_instance_valid(local_player):
		if source_id > 0:
			_last_killer_id = source_id

		if amount > 0 and local_player.hp_component:
			var was_dead := local_player.hp_component.is_dead
			local_player.hp_component.take_damage(amount)
			var is_dead := local_player.hp_component.is_dead

			if is_dead and not was_dead:
				local_player.movement_state = Player.MovementState.IDLE
				local_player.velocity = Vector2.ZERO
				local_player.set_input_enabled(false)
				if prediction_controller:
					prediction_controller.set_prediction_enabled(false)
				_play_local_death_feedback()
			else:
				# Play hit sound for local player taking damage
				var audio := _get_audio_manager()
				if audio:
					audio.play_player_hit()

			# Spawn damage number
			_spawn_damage_number(amount, local_player.global_position, false)

			if not is_dead:
				# Screen shake + red flash on hit
				if screen_effects:
					screen_effects.shake(ScreenEffects.SHAKE_HIT)
					screen_effects.flash_damage()

				# Hit sparks at player position
				var sparks := ParticleEffects.create_hit_sparks(local_player.global_position)
				_add_effect_to_arena(sparks)


## Play local death audio, particles, screen effects, and UI exactly once.
func _play_local_death_feedback() -> void:
	if _local_death_feedback_played:
		return
	if local_player == null or not is_instance_valid(local_player):
		return

	_local_death_feedback_played = true

	var audio := _get_audio_manager()
	if audio:
		audio.play_player_death()

	if screen_effects:
		screen_effects.shake(ScreenEffects.SHAKE_DEATH)
		screen_effects.flash_death()

	var death_particles := ParticleEffects.create_death_explosion(local_player.global_position, Color(0.27, 0.53, 1.0))
	_add_effect_to_arena(death_particles)
	var gore := ParticleEffects.create_gore_splatter(local_player.global_position)
	_add_effect_to_arena(gore)

	if death_screen:
		# Hardcore = permadeath: the server has already converted XP→Glory and deleted the
		# character (and will kick us shortly). Show the "Your Glory will be remembered"
		# screen with a Back to Main Menu button instead of the respawn countdown.
		if GameManager.is_hardcore():
			_hardcore_death = true
			# The server will kick us once the character is deleted. Stop NetworkManager from
			# auto-reconnecting into that kick — otherwise it re-auths and the server spawns us
			# again in the background behind the death screen.
			NetworkManager.suppress_auto_reconnect()
			# Show how much Glory the fallen hero converted. The client recomputes the exact
			# value the Go API credited from the authoritative level/XP (shared curve+divisor),
			# so no protocol change is needed (Glory stays off the game wire — ADR 0006).
			# Snapshot it once here so the menu fold-in (_on_main_menu_requested) reuses the same
			# number — a late PROGRESS event can't make the two readings diverge.
			_death_glory = GameManager.glory_for_death()
			death_screen.show_death_hardcore(_last_killer_id, _death_glory)
		else:
			death_screen.show_death(_last_killer_id)


## Handle authoritative projectile fire event for remote player and monster audio.
func _handle_projectile_fired_event(data: Dictionary) -> void:
	var source_id: int = data.get("source_id", -1)
	var projectile_id: int = data.get("target_id", 0)
	var local_id := GameManager.get_local_player_entity_id()
	if source_id <= 0:
		return
	if client_entity_manager and projectile_id > 0:
		client_entity_manager.register_projectile_source(projectile_id, source_id)

	if source_id == local_id:
		_log_local_projectile_fired_event(data)
		_play_local_projectile_fired_feedback(data)
		return

	var audio := _get_audio_manager()
	if audio == null:
		return

	if source_id >= GameConstants.MONSTER_ENTITY_ID_START:
		if client_entity_manager == null or not client_entity_manager.monster_entities.has(source_id):
			return
		audio.play_monster_shoot()
		return

	if client_entity_manager == null or not client_entity_manager.player_entities.has(source_id):
		return
	audio.play_player_shoot()


func _log_local_projectile_fired_event(data: Dictionary) -> void:
	if not projectile_sync_debug_logging or prediction_controller == null:
		return

	var event_data: Dictionary = data.get("event_data", {})
	if not event_data.has("position"):
		return

	var projectile_id: int = data.get("target_id", 0)
	var server_spawn_pos: Vector2 = event_data.get("position", Vector2.ZERO)
	var server_tick: int = event_data.get("server_tick", 0)
	var predicted_pos := prediction_controller.predicted_position
	var expected_muzzle_offset := GameConstants.PLAYER_HITBOX_RADIUS + GameConstants.PROJECTILE_RADIUS + 2.0

	print("[ArenaBase] Local PROJECTILE_FIRED: projectile=%d server_tick=%d server_spawn_pos=%s predicted_player_pos=%s delta=%.2f expected_muzzle_offset=%.2f" % [
		projectile_id,
		server_tick,
		server_spawn_pos,
		predicted_pos,
		server_spawn_pos.distance_to(predicted_pos),
		expected_muzzle_offset
	])


## Server PROJECTILE_FIRED arrival for the LOCAL player. Cosmetics (muzzle flash,
## audio) are now driven instantly off the predicted shoot edge
## (_on_local_shoot_predicted), so this path intentionally does NOT redraw a flash
## or replay audio — that would double-fire one trigger pull. Projectile-source
## registration and logging happen in _handle_projectile_fired_event.
func _play_local_projectile_fired_feedback(_data: Dictionary) -> void:
	pass


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

		# Track kill streak
		_kill_streak_count += 1
		_kill_streak_timer = KILL_STREAK_WINDOW

		# Show kill notification (with streak if applicable)
		if _kill_streak_count >= 3:
			_show_streak_notification(_kill_streak_count)
		elif _kill_streak_count == 2:
			_show_kill_notification(victim_name, "DOUBLE KILL!")
		else:
			_show_kill_notification(victim_name)

		# Play kill sound effect
		var audio := _get_audio_manager()
		if audio:
			audio.play_player_kill()

		# Kill effects: hit stop + medium shake
		if screen_effects:
			screen_effects.hit_stop()
			screen_effects.shake(ScreenEffects.SHAKE_KILL)

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
	if killer_id == local_id and victim_id >= GameConstants.MONSTER_ENTITY_ID_START:
		GameManager.update_stat("monster_kills", 1)

	if victim_id >= GameConstants.MONSTER_ENTITY_ID_START and client_entity_manager:
		client_entity_manager.apply_monster_death(victim_id)

	# Monster killed a player - show in kill feed
	if killer_id >= GameConstants.MONSTER_ENTITY_ID_START and victim_id < GameConstants.MONSTER_ENTITY_ID_START:
		if victim_id == local_id:
			GameManager.update_stat("deaths", 1)
		if kill_feed:
			var victim_name := EntityNameCache.get_entity_name(victim_id)
			# Display name comes from the monster catalogue (data-driven). The wire
			# carries no per-monster archetype yet, so this is the default type.
			var monster_name := MonsterDatabase.get_shared().get_default_definition().display_name
			kill_feed.add_kill(monster_name, victim_name)


## Handle leaderboard update
func _handle_leaderboard_update(data: Dictionary) -> void:
	var entries: Array = data.get("event_data", {}).get("entries", [])
	if leaderboard:
		leaderboard.update_entries(entries)

	# Update server status player count from leaderboard entry count
	if server_status:
		server_status.update_player_count(entries.size(), SERVER_STATUS_MAX_PLAYERS)


## Immediate cosmetic feedback for the local player's predicted shoot edge.
## Cosmetic only — draws a muzzle flash and plays audio the instant the
## trigger is pulled, without waiting for the server PROJECTILE_FIRED round-trip.
## Does NOT spawn a Projectile and does NOT touch prediction state.
func _on_local_shoot_predicted(muzzle: Vector2, dir: Vector2) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_player_shoot()

	var flash := ParticleEffects.create_muzzle_flash(muzzle, dir)
	_add_effect_to_arena(flash)


## Handle local player shooting (for audio + effects)
func _on_local_player_shot(pos: Vector2, dir: Vector2) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_player_shoot()

	# Muzzle flash effect
	var flash := ParticleEffects.create_muzzle_flash(pos, dir)
	_add_effect_to_arena(flash)


func _on_respawn_requested() -> void:
	NetworkManager.send_message(NetworkManager.MessageType.RESPAWN_REQUEST, {})


## Hardcore "Back to Main Menu" pressed. The character is already gone server-side (XP→Glory
## converted, row deleted), so clear the local character data and return to the main menu.
func _on_main_menu_requested() -> void:
	if _is_leaving_arena:
		return
	_is_leaving_arena = true

	var audio := _get_audio_manager()
	if audio:
		audio.stop_music()
	NetworkManager.disconnect_from_server("Hardcore permadeath")
	# Reflect the Glory this death converted in the cached account total so the menu shows the
	# updated number. The server credited it, but /api/character/me can't return it once the
	# character row is deleted — so fold the converted amount in here before clearing the run.
	GameManager.player_data["glory"] = int(GameManager.get_player_data().get("glory", 0)) + _death_glory
	GameManager.clear_player_data()
	SceneManager.goto_main_menu()


## Show a "You eliminated [Name]" notification for the local player
func _show_kill_notification(victim_name: String, title: String = "") -> void:
	var hud_layer := get_hud_layer()
	if hud_layer == null:
		return

	var label := Label.new()
	label.text = "You eliminated %s" % victim_name
	if not title.is_empty():
		label.text = "%s\n%s" % [title, label.text]
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


## Invulnerability shield circle - drawn as a child of local player
var _shield_node: Node2D = null
var _is_invulnerable: bool = false

## Tracks the local player's STEALTH flag so the "go invisible" SFX fires once on the
## rising edge (the frame stealth turns on), not every snapshot while stealthed.
var _local_stealthed: bool = false

func _update_invuln_shield() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return

	if _is_invulnerable:
		if _shield_node == null:
			_shield_node = _InvulnShield.new()
			local_player.add_child(_shield_node)
		_shield_node.visible = true
	else:
		if _shield_node != null:
			_shield_node.visible = false


## Inner class for drawing the invulnerability shield
class _InvulnShield extends Node2D:
	func _process(_delta: float) -> void:
		queue_redraw()

	func _draw() -> void:
		var t := Time.get_ticks_msec() / 500.0
		var pulse := 0.6 + 0.4 * sin(t * TAU)
		var radius := 22.0 + sin(t * TAU * 0.7) * 3.0
		var shield_color := Color(0.27, 0.53, 1.0, 0.25 * pulse)
		draw_circle(Vector2.ZERO, radius, shield_color)
		# Outer ring
		var ring_color := Color(0.4, 0.7, 1.0, 0.5 * pulse)
		draw_arc(Vector2.ZERO, radius, 0, TAU, 32, ring_color, 2.0)


## Show kill streak notification
func _show_streak_notification(streak: int) -> void:
	var streak_text: String
	match streak:
		3: streak_text = "TRIPLE KILL!"
		4: streak_text = "QUAD KILL!"
		_: streak_text = "RAMPAGE! (%d kills)" % streak

	var hud_layer := get_hud_layer()
	if hud_layer == null:
		return

	var label := Label.new()
	label.text = streak_text
	label.add_theme_font_size_override("font_size", 30)
	label.add_theme_color_override("font_color", Color(1.0, 0.8, 0.1))  # Gold
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	label.offset_top = -50
	label.offset_bottom = -10
	label.offset_left = -200
	label.offset_right = 200
	hud_layer.add_child(label)

	# Escalating shake
	if screen_effects:
		screen_effects.shake(ScreenEffects.SHAKE_KILL + float(streak) * 2.0, 0.4)

	# Animate out
	var tween := label.create_tween()
	tween.tween_property(label, "modulate:a", 0.0, 1.5).set_delay(1.5)
	tween.tween_callback(label.queue_free)


## Spawn a floating damage number at world position
func _spawn_damage_number(amount: int, world_pos: Vector2, is_dealt: bool) -> void:
	var dmg_num := DamageNumber.new()
	dmg_num.setup(amount, world_pos, is_dealt)
	var container := get_entity_container()
	if container:
		container.add_child(dmg_num)


## Spawn a Sulfur Yellow "+N XP" floater (cosmetic, from an EXP_GAIN event).
func _spawn_xp_floater(amount: int, world_pos: Vector2) -> void:
	_spawn_text_floater("+%d XP" % amount, world_pos, Color("c69a2e"))


## Spawn a Soul Teal "+N" heal floater (from a PICKUP heal event).
func _spawn_heal_floater(amount: int, world_pos: Vector2) -> void:
	_spawn_text_floater("+%d" % amount, world_pos, Color("1c6c73"))


## Shared rising-and-fading text floater (reuses the damage-number motion/style).
func _spawn_text_floater(text: String, world_pos: Vector2, color: Color) -> void:
	var floater := _TextFloater.new()
	floater.setup(text, world_pos, color)
	var container := get_entity_container()
	if container:
		container.add_child(floater)


## Add a visual effect node to the arena entity container
func _add_effect_to_arena(effect: Node2D) -> void:
	var container := get_entity_container()
	if container:
		container.add_child(effect)


## Get AudioManager singleton (cached)
func _get_audio_manager() -> Node:
	if _cached_audio_manager == null or not is_instance_valid(_cached_audio_manager):
		_cached_audio_manager = get_tree().root.get_node_or_null("AudioManager")
	return _cached_audio_manager


## Update HP bar from local player's HP component
func _update_hp_bar() -> void:
	if hp_bar == null or local_player == null or not is_instance_valid(local_player):
		return
	if local_player.hp_component == null:
		return
	hp_bar.update_hp(local_player.hp_component.current_hp, local_player.hp_component.max_hp)


func _connect_local_hp_bar() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return
	if local_player.hp_component == null:
		return
	if not local_player.hp_component.hp_changed.is_connected(_on_local_hp_changed):
		local_player.hp_component.hp_changed.connect(_on_local_hp_changed)
	_update_hp_bar()
	_connect_local_resource_bars()


func _on_local_hp_changed(current_hp: int, max_hp: int) -> void:
	if hp_bar:
		hp_bar.update_hp(current_hp, max_hp)


## Wire the Stamina/Mana bars to the local player's predicted movement state machine.
func _connect_local_resource_bars() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return
	var sm: MovementStateMachine = local_player.movement_sm
	if sm == null:
		return
	if stamina_bar != null and not sm.stamina_changed.is_connected(_on_local_stamina_changed):
		sm.stamina_changed.connect(_on_local_stamina_changed)
		stamina_bar.update_value(sm.stamina, GameConstants.PLAYER_STAMINA_MAX)
	if stamina_bar != null and stamina_bar.has_method("set_exhausted") \
			and not sm.exhausted_changed.is_connected(_on_local_exhausted_changed):
		sm.exhausted_changed.connect(_on_local_exhausted_changed)
	if mana_bar != null and not sm.mana_changed.is_connected(_on_local_mana_changed):
		sm.mana_changed.connect(_on_local_mana_changed)
		mana_bar.update_value(sm.mana, GameConstants.PLAYER_MANA_MAX)
	if ability_bar != null:
		ability_bar.bind_movement_state_machine(sm)


func _on_local_stamina_changed(current: float, maximum: float) -> void:
	if stamina_bar:
		stamina_bar.update_value(current, maximum)


func _on_local_mana_changed(current: float, maximum: float) -> void:
	if mana_bar:
		mana_bar.update_value(current, maximum)


func _on_local_exhausted_changed(active: bool) -> void:
	if stamina_bar and stamina_bar.has_method("set_exhausted"):
		stamina_bar.set_exhausted(active)


## Handle disconnect from server
func _on_disconnected(_reason: String) -> void:
	# A hardcore death ends with the server kicking us (character deleted). That disconnect
	# is expected — keep the permadeath death screen up and don't offer to reconnect.
	if _hardcore_death:
		return
	if GameManager.current_state == GameManager.GameState.IN_ARENA:
		if connection_lost_overlay:
			connection_lost_overlay.show_overlay()


## Handle reconnection to server
func _on_reconnected() -> void:
	if connection_lost_overlay and connection_lost_overlay.visible:
		connection_lost_overlay.hide_overlay()

	# _complete_connection cleared _auth_handshake_sent already; re-issue so the
	# server re-broadcasts PLAYER_INFO and we can rediscover our entity_id.
	NetworkManager.send_auth_handshake()
	NetworkManager.send_message(NetworkManager.MessageType.REQUEST_FULL_STATE, {})


## Handle reconnect failure - return to main menu
func _on_reconnect_failed() -> void:
	_leave_arena()


## Pause overlay opened/closed: gate the local player's input. Online the player's own
## input is already disabled (prediction owns it), so we suppress the PredictionController.
func _on_pause_menu_visibility_changed() -> void:
	if prediction_controller:
		prediction_controller.set_input_suppressed(pause_menu != null and pause_menu.visible)


## Handle leave arena request from pause menu
func _on_leave_arena() -> void:
	_leave_arena()


## Leave the Arena and return to the Sanctuary hub. Both are now networked instances on the
## same region host (Arena = :8081, Sanctuary = :8082), so this disconnects from the Arena and
## RECONNECTS to the Sanctuary instance before switching scenes — otherwise the Sanctuary scene
## would come up with no server link. (The Sanctuary, not the main menu, is the town the player
## returns to; SceneManager sets the IN_ARENA game state for it.)
func _leave_arena() -> void:
	if _is_leaving_arena:
		return
	_is_leaving_arena = true

	var audio := _get_audio_manager()
	if audio:
		audio.stop_music()
	GameManager.persist_progression()  # flush any unsaved XP before tearing down

	# Drop the Arena link, then dial the Sanctuary instance (region host on the Sanctuary port).
	NetworkManager.disconnect_from_server("Return to Sanctuary")
	await get_tree().process_frame

	var region_url: String = GameManager.player_data.get("selected_region_url", "")
	if region_url.is_empty():
		# No region stashed (shouldn't happen from a live Arena) — fall back to the menu.
		SceneManager.goto_main_menu()
		return

	var sanctuary_url := NetworkManager.sanctuary_url_for_region(region_url)
	NetworkManager.connect_to_server(sanctuary_url, AuthManager.get_token())
	# Switch scenes immediately; the Sanctuary's _setup_client drives the handshake once the
	# link opens (connect_to_server awaits the link internally and emits connected_to_server).
	SceneManager.goto_sanctuary()


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
		if local_player and is_instance_valid(local_player) and local_player.hp_component:
			if local_player.hp_component.hp_changed.is_connected(_on_local_hp_changed):
				local_player.hp_component.hp_changed.disconnect(_on_local_hp_changed)

		# Cleanup client resources
		if client_entity_manager:
			client_entity_manager.clear_all()
		if interpolation_controller:
			interpolation_controller.clear_all_entities()

		GameManager.clear_local_player_entity_id()
		_local_player_authority_synced = false
		_local_death_feedback_played = false

	print("[ArenaBase] Scene exit cleanup complete")


## ---------------------------------------------------------------------------
## Arena props (cosmetic only — the server sim knows nothing about them).
## Statement pieces decorate the authoritative ARENA_OBSTACLES geometry
## (corner Ls, center cross, mid barriers) so visuals match collision; the
## rest is set dressing scattered on open floor away from the spawn ring.
## Pattern mirrors sanctuary.gd: const tables + texture-or-skip fallback.
## ---------------------------------------------------------------------------

const ARENA_PROP_TEXTURE_DIR := "res://assets/sprites/environment/arena/"

## Sprite-based arena floor. `ground_stone1` is the seamless BASE tiled across the whole arena;
## `ground_variation1/2` are DETAIL decals scattered on top (jittered so they don't grid-align).
## `ground_darken` is intentionally unused (it reads as out-of-arena dark ground).
## Drawn UNDER the obstacle/border _draw() overlay (z just above the TileMapLayer).
const GROUND_BASE_FILE := "ground_stone1.png"
const GROUND_DETAIL_FILES := ["ground_variation1.png", "ground_variation2.png"]
## 250 divides the 2000-unit arena evenly (8x8), so the base tiles fill it with no overshoot.
const GROUND_TILE_SIZE := 250.0

## kind -> {file, flat}. Standing props (flat=false) are bottom-planted on
## their position; flat props (decals, piles) center on it.
const ARENA_PROP_SPRITES := {
	"statue_weeping": {"file": "statue_weeping.png", "flat": false},
	"pillar_broken": {"file": "pillar_broken.png", "flat": false},
	"brazier": {"file": "brazier.png", "flat": false},
	"banner_stand": {"file": "banner_stand.png", "flat": false},
	"gravestone_cross": {"file": "gravestone_cross.png", "flat": false},
	"funerary_urn": {"file": "funerary_urn.png", "flat": false},
	"candelabra": {"file": "candelabra.png", "flat": false},
	"corrupted_crystal": {"file": "corrupted_crystal.png", "flat": false},
	"dead_tree": {"file": "dead_tree.png", "flat": false},
	"spike_barricade": {"file": "spike_barricade.png", "flat": false},
	"altar": {"file": "altar.png", "flat": false},
	"bone_pile": {"file": "bone_pile.png", "flat": true},
	"skull_pile": {"file": "skull_pile.png", "flat": true},
	"rubble": {"file": "rubble.png", "flat": true},
	"ritual_circle": {"file": "ritual_circle.png", "flat": true},
	"blood_stain": {"file": "blood_stain.png", "flat": true},
}

## Pixels the standing-prop artwork keeps below its visual base (shadows).
const ARENA_PROP_FOOT := 6.0

const ARENA_PROPS: Array[Dictionary] = [
	# Weeping statues guard the corner cover walls (inside each L).
	{"kind": "statue_weeping", "pos": Vector2(-610, -615)},
	{"kind": "statue_weeping", "pos": Vector2(610, -615)},
	{"kind": "statue_weeping", "pos": Vector2(-610, 660)},
	{"kind": "statue_weeping", "pos": Vector2(610, 660)},
	{"kind": "candelabra", "pos": Vector2(-545, -630)},
	{"kind": "candelabra", "pos": Vector2(545, -630)},
	{"kind": "candelabra", "pos": Vector2(-545, 645)},
	{"kind": "candelabra", "pos": Vector2(545, 645)},
	# Broken pillars cap the four ends of the center cross.
	{"kind": "pillar_broken", "pos": Vector2(0, -205)},
	{"kind": "pillar_broken", "pos": Vector2(0, 205)},
	{"kind": "pillar_broken", "pos": Vector2(-205, 0)},
	{"kind": "pillar_broken", "pos": Vector2(205, 0)},
	# Banners mark the diagonal approaches to the center.
	{"kind": "banner_stand", "pos": Vector2(-85, -85)},
	{"kind": "banner_stand", "pos": Vector2(85, -85)},
	{"kind": "banner_stand", "pos": Vector2(-85, 85)},
	{"kind": "banner_stand", "pos": Vector2(85, 85)},
	# Braziers light the mid-field barriers.
	{"kind": "brazier", "pos": Vector2(-400, -345)},
	{"kind": "brazier", "pos": Vector2(400, -345)},
	{"kind": "brazier", "pos": Vector2(-400, 343)},
	{"kind": "brazier", "pos": Vector2(400, 343)},
	# Corrupted crystals as mid-edge landmarks.
	{"kind": "corrupted_crystal", "pos": Vector2(0, -660)},
	{"kind": "corrupted_crystal", "pos": Vector2(660, 0)},
	{"kind": "corrupted_crystal", "pos": Vector2(0, 660)},
	{"kind": "corrupted_crystal", "pos": Vector2(-660, 0)},
	# Graveyard cluster in the south-west quadrant.
	{"kind": "gravestone_cross", "pos": Vector2(-520, 380)},
	{"kind": "gravestone_cross", "pos": Vector2(-455, 425)},
	{"kind": "gravestone_cross", "pos": Vector2(-390, 372)},
	{"kind": "gravestone_cross", "pos": Vector2(-545, 462)},
	{"kind": "gravestone_cross", "pos": Vector2(-430, 487)},
	{"kind": "funerary_urn", "pos": Vector2(-355, 440)},
	{"kind": "bone_pile", "pos": Vector2(-500, 428)},
	{"kind": "skull_pile", "pos": Vector2(-412, 412)},
	# Dead trees + altar in the north-east quadrant.
	{"kind": "dead_tree", "pos": Vector2(470, -480)},
	{"kind": "dead_tree", "pos": Vector2(585, -390)},
	{"kind": "altar", "pos": Vector2(500, -560)},
	{"kind": "ritual_circle", "pos": Vector2(500, -480)},
	{"kind": "funerary_urn", "pos": Vector2(545, -652)},
	# Spike barricades near the north-west and south-east lanes.
	{"kind": "spike_barricade", "pos": Vector2(-450, -550)},
	{"kind": "spike_barricade", "pos": Vector2(450, 550)},
	# Set dressing scattered on open floor.
	{"kind": "rubble", "pos": Vector2(-150, -600)},
	{"kind": "rubble", "pos": Vector2(300, -520)},
	{"kind": "rubble", "pos": Vector2(620, -120)},
	{"kind": "rubble", "pos": Vector2(520, 300)},
	{"kind": "rubble", "pos": Vector2(-620, 140)},
	{"kind": "rubble", "pos": Vector2(-300, 560)},
	{"kind": "rubble", "pos": Vector2(150, 640)},
	{"kind": "rubble", "pos": Vector2(-640, -300)},
	{"kind": "bone_pile", "pos": Vector2(250, -650)},
	{"kind": "bone_pile", "pos": Vector2(-250, 230)},
	{"kind": "bone_pile", "pos": Vector2(640, 250)},
	{"kind": "bone_pile", "pos": Vector2(-360, -460)},
	{"kind": "skull_pile", "pos": Vector2(220, 420)},
	{"kind": "skull_pile", "pos": Vector2(-660, -660)},
	{"kind": "blood_stain", "pos": Vector2(120, -300)},
	{"kind": "blood_stain", "pos": Vector2(-200, 80)},
	{"kind": "blood_stain", "pos": Vector2(380, 120)},
]


## Instance the cosmetic prop sprites. Missing textures are skipped silently
## (same graceful-fallback rule as sanctuary.gd) so the arena keeps working
## on checkouts without the generated art.
func _build_arena_props() -> void:
	# Free the old node IMMEDIATELY (not deferred queue_free) so a same-frame rebuild can't
	# add a second child with the same name before the queued free runs.
	var existing := get_node_or_null("Props")
	if existing:
		remove_child(existing)
		existing.free()
	var container := Node2D.new()
	container.name = "Props"
	# Carry the minimap bit on the container too: the minimap viewport culls a whole subtree if
	# an ancestor's visibility_layer misses its cull mask, which would hide the prop sprites.
	container.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	# Same z as entities, but ordered BEFORE EntityContainer in the tree so
	# props render above the _draw() floor yet under all dynamic entities.
	# (A negative z_index would put them under the parent's own _draw().)
	add_child(container)
	var entity_container := get_node_or_null("EntityContainer")
	if entity_container:
		move_child(container, entity_container.get_index())

	for prop: Dictionary in ARENA_PROPS:
		var kind: String = prop["kind"]
		var info: Dictionary = ARENA_PROP_SPRITES.get(kind, {})
		if info.is_empty():
			continue
		var path: String = ARENA_PROP_TEXTURE_DIR + String(info["file"])
		if not ResourceLoader.exists(path, "Texture2D"):
			continue
		var texture: Texture2D = load(path)
		if texture == null:
			continue
		var sprite := Sprite2D.new()
		sprite.texture = texture
		sprite.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
		var pos: Vector2 = prop["pos"]
		if not bool(info.get("flat", false)):
			# Plant the artwork's base on the position (sprites are centered).
			pos.y -= texture.get_height() / 2.0 - ARENA_PROP_FOOT
		sprite.position = pos
		container.add_child(sprite)
	print("[ArenaBase] Built %d arena props" % container.get_child_count())


## Build the sprite-based ground floor: a deterministic mix of the stone/variation tiles over
## the whole arena with the darken decal sparsely overlaid. Sits above the TileMapLayer and
## below the parent's vein-grid/obstacle/border _draw(). Missing textures are skipped silently
## (same graceful-fallback rule as _build_arena_props) — if no tiles load, the procedural floor
## stays. Client-only (called from _build_level_environment's non-server branch).
func _build_arena_floor_decor() -> void:
	# Free the old node IMMEDIATELY (not deferred queue_free) so a same-frame rebuild can't
	# add a second child with the same name before the queued free runs.
	var existing := get_node_or_null("GroundDecor")
	if existing:
		remove_child(existing)
		existing.free()

	var base_path := ARENA_PROP_TEXTURE_DIR + GROUND_BASE_FILE
	if not ResourceLoader.exists(base_path, "Texture2D"):
		# No base ground art on this checkout — keep the procedural FLOOR_COLOR floor.
		return
	var base_tex: Texture2D = load(base_path)
	if base_tex == null:
		return

	var details: Array[Texture2D] = []
	for fname: String in GROUND_DETAIL_FILES:
		var path := ARENA_PROP_TEXTURE_DIR + fname
		if not ResourceLoader.exists(path, "Texture2D"):
			continue
		var tex: Texture2D = load(path)
		if tex != null:
			details.append(tex)

	var layer := _GroundDecorLayer.new()
	layer.name = "GroundDecor"
	layer.arena_rect = Rect2(arena_min, arena_max - arena_min)
	layer.base_tex = base_tex
	layer.detail_texs = details
	layer.tile = GROUND_TILE_SIZE
	# Above the TileMapLayer (-10), below the parent node's own _draw() (z 0) so the obstacles
	# / red border still read on top.
	layer.z_index = TILEMAP_Z_INDEX + 1
	layer.z_as_relative = false
	# Carry the minimap terrain bit so the floor shows on the minimap like the old _draw() floor.
	layer.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	add_child(layer)
	move_child(layer, 0)

	# The sprites now provide the floor; stop the opaque FLOOR_COLOR fill + vein grid from
	# hiding them (_draw() gates both on _paint_solid_floor).
	_paint_solid_floor = false
	queue_redraw()
	print("[ArenaBase] Built sprite arena floor (stone base + %d detail decals)" % details.size())


## Set up the generated TileMapLayer backing the arena floor, walls, and obstacle cells.
func _setup_arena_tilemap() -> void:
	var tilemap := get_node_or_null("TileMapLayer") as TileMapLayer
	if tilemap == null:
		tilemap = TileMapLayer.new()
		tilemap.name = "TileMapLayer"
		add_child(tilemap)
		move_child(tilemap, 0)

	tilemap.position = GameConstants.MAP_MIN
	tilemap.z_index = TILEMAP_Z_INDEX
	tilemap.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	tilemap.collision_enabled = true
	tilemap.tile_set = _create_arena_tileset()
	tilemap.clear()

	for y in range(GameConstants.ARENA_TILE_ROWS):
		for x in range(GameConstants.ARENA_TILE_COLUMNS):
			var coords := Vector2i(x, y)
			tilemap.set_cell(
				coords,
				GameConstants.ARENA_TILE_SOURCE_ID,
				GameConstants.get_arena_tile_type(coords),
				0
			)


## Create a runtime TileSet with floor, border, and obstacle tiles.
func _create_arena_tileset() -> TileSet:
	var tile_size := Vector2i(
		int(GameConstants.ARENA_TILE_SIZE),
		int(GameConstants.ARENA_TILE_SIZE)
	)
	var tile_set := TileSet.new()
	tile_set.tile_size = tile_size
	tile_set.add_physics_layer()
	tile_set.set_physics_layer_collision_layer(0, ENVIRONMENT_COLLISION_LAYER)
	tile_set.set_physics_layer_collision_mask(0, 0)

	var atlas_source := TileSetAtlasSource.new()
	atlas_source.texture_region_size = tile_size
	atlas_source.texture = _create_arena_tile_atlas_texture(tile_size)
	atlas_source.create_tile(GameConstants.ARENA_FLOOR_TILE)
	atlas_source.create_tile(GameConstants.ARENA_BORDER_TILE)
	atlas_source.create_tile(GameConstants.ARENA_OBSTACLE_TILE)

	tile_set.add_source(atlas_source, GameConstants.ARENA_TILE_SOURCE_ID)
	_add_tile_collision(atlas_source, GameConstants.ARENA_BORDER_TILE, tile_size)
	_add_tile_collision(atlas_source, GameConstants.ARENA_OBSTACLE_TILE, tile_size)
	return tile_set


## Build a simple atlas texture so generated tiles are visible in editor and runtime.
func _create_arena_tile_atlas_texture(tile_size: Vector2i) -> Texture2D:
	var image := Image.create(
		tile_size.x * TILE_ATLAS_COLUMNS,
		tile_size.y,
		false,
		Image.FORMAT_RGBA8
	)
	image.fill(Color.TRANSPARENT)
	image.fill_rect(Rect2i(Vector2i.ZERO, tile_size), FLOOR_COLOR)
	image.fill_rect(Rect2i(Vector2i(tile_size.x, 0), tile_size), Color(0.18, 0.04, 0.06, 1.0))
	image.fill_rect(Rect2i(Vector2i(tile_size.x * 2, 0), tile_size), Color(0.12, 0.03, 0.05, 1.0))
	return ImageTexture.create_from_image(image)


## Add full-tile collision to a generated tile.
func _add_tile_collision(atlas_source: TileSetAtlasSource, atlas_coords: Vector2i, tile_size: Vector2i) -> void:
	var tile_data := atlas_source.get_tile_data(atlas_coords, 0)
	if tile_data == null:
		return

	var half_size := Vector2(float(tile_size.x), float(tile_size.y)) * 0.5
	var points := PackedVector2Array([
		Vector2(-half_size.x, -half_size.y),
		Vector2(half_size.x, -half_size.y),
		Vector2(half_size.x, half_size.y),
		Vector2(-half_size.x, half_size.y),
	])
	tile_data.set_collision_polygons_count(0, 1)
	tile_data.set_collision_polygon_points(0, 0, points)


## Rebuild spawn markers from shared constants so scene markers match runtime spawn data.
func _rebuild_spawn_markers() -> void:
	var spawn_container := get_node_or_null("SpawnPoints") as Node2D
	if spawn_container == null:
		spawn_container = Node2D.new()
		spawn_container.name = "SpawnPoints"
		add_child(spawn_container)

	for child in spawn_container.get_children():
		if child is Marker2D and (child.name.begins_with("PlayerSpawn") or child.name.begins_with("MonsterSpawn")):
			spawn_container.remove_child(child)
			child.free()

	_add_spawn_markers(spawn_container, "PlayerSpawn", GameConstants.get_valid_player_spawns())
	_add_spawn_markers(spawn_container, "MonsterSpawn", GameConstants.get_valid_monster_spawns())


## Add a named marker sequence to the spawn container.
func _add_spawn_markers(spawn_container: Node2D, prefix: String, positions: Array[Vector2]) -> void:
	for i in range(positions.size()):
		var marker := Marker2D.new()
		marker.name = "%s%d" % [prefix, i + 1]
		marker.position = positions[i]
		spawn_container.add_child(marker)


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
	return _player_spawns.duplicate()


## Get all monster spawn positions
func get_all_monster_spawns() -> Array[Vector2]:
	return _monster_spawns.duplicate()


## Get the EntityContainer node for adding dynamic entities
func get_entity_container() -> Node2D:
	return get_node_or_null("EntityContainer")


## Get the HUD layer for adding UI elements
func get_hud_layer() -> CanvasLayer:
	return get_node_or_null("HUDLayer")


## World-space bounds of this level, used to frame the static minimap/map texture. Defaults to the
## Arena play-field; the Sanctuary overrides this with the full walkable town rect.
func get_map_bounds() -> Rect2:
	return Rect2(arena_min, arena_max - arena_min)


## Draw arena floor and grid
func _draw() -> void:
	# A subclass (Sanctuary) suppresses the dark arena floor and paints its own ground layers.
	if not _draws_arena_floor:
		return

	# When the sprite-based ground layer is present (_build_arena_floor_decor) we skip the opaque
	# fill AND the vein grid / branches entirely — the floor texture is the look now. Only the
	# obstacles + border draw on top. The procedural floor + grid is the fallback when no art loads.
	var arena_rect := Rect2(arena_min, arena_max - arena_min)
	if _paint_solid_floor:
		draw_rect(arena_rect, FLOOR_COLOR, true)

		# Vein grid lines (organic tissue feel)
		var x := arena_min.x
		while x <= arena_max.x:
			draw_line(Vector2(x, arena_min.y), Vector2(x, arena_max.y), GRID_COLOR, 1.0)
			x += GRID_CELL_SIZE

		var y := arena_min.y
		while y <= arena_max.y:
			draw_line(Vector2(arena_min.x, y), Vector2(arena_max.x, y), GRID_COLOR, 1.0)
			y += GRID_CELL_SIZE

		# Branching veins from grid intersections
		_draw_vein_branches()

	# Draw obstacles
	_draw_obstacles()

	# Draw border with glow
	draw_rect(arena_rect, BORDER_COLOR, false, BORDER_WIDTH)
	# Inner border glow
	var inner_rect := Rect2(arena_min + Vector2(4, 4), arena_max - arena_min - Vector2(8, 8))
	var glow_color := BORDER_COLOR
	glow_color.a = 0.2
	draw_rect(inner_rect, glow_color, false, 2.0)


## Draw organic vein branches from grid intersections
func _draw_vein_branches() -> void:
	# Deterministic "random" branches using position-based seed
	var ix := arena_min.x
	while ix <= arena_max.x:
		var iy := arena_min.y
		while iy <= arena_max.y:
			# Use position hash to deterministically decide branch directions
			var hash_val := posmod(int(ix * 73.0 + iy * 137.0), 100)
			if hash_val < 30:  # 30% of intersections get branches
				var branch_len := 16.0 + float(hash_val % 4) * 8.0
				var angle := float(hash_val) * 0.7  # Deterministic angle
				var start := Vector2(ix, iy)
				var end := start + Vector2(cos(angle), sin(angle)) * branch_len
				# Clamp to arena
				end.x = clampf(end.x, arena_min.x, arena_max.x)
				end.y = clampf(end.y, arena_min.y, arena_max.y)
				draw_line(start, end, VEIN_BRANCH_COLOR, 1.0)
			iy += GRID_CELL_SIZE
		ix += GRID_CELL_SIZE


## Draw arena obstacles as dark organic wall segments
func _draw_obstacles() -> void:
	var wall_color := Color(0.15, 0.05, 0.08, 1.0)
	var edge_glow := Color(0.3, 0.08, 0.12, 0.6)

	for obs: Rect2 in GameConstants.ARENA_OBSTACLES:
		# Main wall body
		draw_rect(obs, wall_color, true)
		# Edge glow
		draw_rect(obs, edge_glow, false, 2.0)
		# Inner vein detail
		var inner := Rect2(obs.position + Vector2(4, 4), obs.size - Vector2(8, 8))
		if inner.size.x > 0 and inner.size.y > 0:
			var vein_color := Color(0.25, 0.06, 0.1, 0.3)
			draw_rect(inner, vein_color, false, 1.0)


## Rising-and-fading text floater (XP gains, heal pickups). Same motion as DamageNumber but
## draws arbitrary text instead of a bare number.
class _TextFloater extends Node2D:
	const RISE_DISTANCE := 70.0
	const DURATION := 0.9
	const FADE_START := 0.5

	var _text: String = ""
	var _color: Color = Color.WHITE
	var _timer: float = 0.0
	var _start_pos: Vector2 = Vector2.ZERO
	var _offset_x: float = 0.0

	func setup(text: String, world_pos: Vector2, color: Color) -> void:
		_text = text
		_color = color
		_start_pos = world_pos
		global_position = world_pos
		_offset_x = randf_range(-12.0, 12.0)

	func _process(delta: float) -> void:
		_timer += delta
		if _timer >= DURATION:
			queue_free()
			return
		var t := _timer / DURATION
		var rise := RISE_DISTANCE * (1.0 - pow(1.0 - t, 2.0))
		global_position = _start_pos + Vector2(_offset_x * t, -rise)
		queue_redraw()

	func _draw() -> void:
		var t := _timer / DURATION
		var alpha := 1.0
		if t > FADE_START:
			alpha = 1.0 - (t - FADE_START) / (1.0 - FADE_START)
		var font := ThemeDB.fallback_font
		var c := _color
		c.a = alpha
		draw_string(font, Vector2(1, 1), _text, HORIZONTAL_ALIGNMENT_CENTER, -1, 16, Color(0, 0, 0, alpha * 0.6))
		draw_string(font, Vector2.ZERO, _text, HORIZONTAL_ALIGNMENT_CENTER, -1, 16, c)


## Sprite-based arena ground floor. Tiles `base_tex` (the stone base) across `arena_rect`, then
## scatters `detail_texs` (the variation decals) on top at jittered positions so they read as
## ground detail rather than a grid. Drawn once on demand (queue_redraw), so the per-cell loop
## cost is paid only when the arena builds. Cosmetic only — the server sim knows nothing about it.
class _GroundDecorLayer extends Node2D:
	var arena_rect: Rect2 = Rect2()
	var base_tex: Texture2D = null
	var detail_texs: Array[Texture2D] = []
	var tile: float = 250.0

	func _draw() -> void:
		if base_tex == null or tile <= 0.0:
			return
		# 1) Tile the seamless stone base across the whole arena.
		var y := arena_rect.position.y
		while y < arena_rect.end.y:
			var x := arena_rect.position.x
			while x < arena_rect.end.x:
				draw_texture_rect(base_tex, Rect2(Vector2(x, y), Vector2(tile, tile)), false)
				x += tile
			y += tile
		# 2) Scatter the detail decals on top — ~45% of cells, jittered off the grid so they
		#    don't line up. Deterministic (hash of cell) so the floor looks identical every build.
		if detail_texs.is_empty():
			return
		var row := 0
		y = arena_rect.position.y
		while y < arena_rect.end.y:
			var col := 0
			var x := arena_rect.position.x
			while x < arena_rect.end.x:
				var h := posmod(row * 73 + col * 137, 100)
				if h < 45:
					var tex: Texture2D = detail_texs[posmod(row * 19 + col * 11, detail_texs.size())]
					var size := tex.get_size()
					# Jitter up to ~±70px so the decals don't grid-align with the base tiles.
					var jx := float(posmod(h * 7, 140)) - 70.0
					var jy := float(posmod(h * 13, 140)) - 70.0
					var pos := Vector2(x + (tile - size.x) * 0.5 + jx, y + (tile - size.y) * 0.5 + jy)
					draw_texture_rect(tex, Rect2(pos, size), false)
				x += tile
				col += 1
			y += tile
			row += 1


## Transient expanding-ring/burst VFX for an ABILITY_EFFECT event. Styled by effect_id and
## sized by the event radius; self-frees after ~0.4s. Pure cosmetics, no logic.
class _AbilityEffectVfx extends Node2D:
	const DURATION := 0.4

	## 0 mageblast, 1 charge_blast, 2 mine_detonation, 3 shadowstep_blink.
	var effect_id: int = 0
	var max_radius: float = 60.0
	var _timer: float = 0.0

	func _process(delta: float) -> void:
		_timer += delta
		if _timer >= DURATION:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var t: float = clampf(_timer / DURATION, 0.0, 1.0)
		var alpha := 1.0 - t
		var radius := max_radius * (0.2 + 0.8 * t)
		var fill := _fill_color()
		var ring := _ring_color()
		fill.a = 0.30 * alpha
		ring.a = 0.9 * alpha
		draw_circle(Vector2.ZERO, radius, fill)
		draw_arc(Vector2.ZERO, radius, 0.0, TAU, 48, ring, 3.0)
		# A second, brighter inner ring for punch.
		var inner := ring
		inner.a = 0.5 * alpha
		draw_arc(Vector2.ZERO, radius * 0.6, 0.0, TAU, 36, inner, 2.0)

	func _fill_color() -> Color:
		match effect_id:
			0: return Color(0.5, 0.7, 1.0)   # mageblast — blue/white
			1: return Color(1.0, 0.6, 0.2)   # charge_blast — orange
			2: return Color(1.0, 0.25, 0.15) # mine_detonation — red
			3: return Color(0.6, 0.3, 0.85)  # shadowstep — purple
			_: return Color(0.8, 0.8, 0.8)

	func _ring_color() -> Color:
		match effect_id:
			0: return Color(0.85, 0.95, 1.0)
			1: return Color(1.0, 0.8, 0.4)
			2: return Color(1.0, 0.5, 0.3)
			3: return Color(0.8, 0.5, 1.0)
			_: return Color(1.0, 1.0, 1.0)
