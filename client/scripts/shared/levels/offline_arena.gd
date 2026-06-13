## OfflineArena - shared base for the fully client-authoritative offline modes
## (Practice and Offline Sandbox).
##
## There is NO server, NO NetworkManager, and NO PredictionController here: the
## local Player owns its own movement (prediction_owns_movement = false), so it
## sprints, shoots (with sound), and takes damage entirely client-side. This base
## owns the parts that arena_base.gd normally gets from the prediction/network
## layer - player spawn, camera, HUD, pause/leave, shoot audio, and routing local
## projectile hits to enemies - so the two offline scenes can't drift apart.
##
## Subclasses override _configure() (set room rect/colors/zoom/spawn) and
## _populate() (spawn enemies + extra UI). They generally should NOT override
## _ready(); use the hooks instead.
class_name OfflineArena
extends Node2D

const PLAYER_SCENE_PATH := "res://scenes/shared/player/player.tscn"
const PAUSE_MENU_PATH := "res://scripts/client/hud/pause_menu.gd"
## Preloaded so the class resolves during headless startup (per AGENTS.md).
const ExperienceBar := preload("res://scripts/client/hud/experience_bar.gd")

const ENVIRONMENT_COLLISION_LAYER := 8
## Camera jump beyond this (player teleport/respawn) snaps instead of interpolating.
const CAMERA_SNAP_DISTANCE := 250.0

# --- Configuration (override in _configure) -------------------------------------
var arena_rect: Rect2 = Rect2(GameConstants.MAP_MIN, GameConstants.MAP_MAX - GameConstants.MAP_MIN)
var wall_thickness: float = 10.0
var grid_cell_size: float = 64.0
var floor_color: Color = Color(0.06, 0.04, 0.04, 1.0)
var grid_color: Color = Color(0.16, 0.08, 0.14, 1.0)
var border_color: Color = Color(0.6, 0.1, 0.1, 1.0)
var border_width: float = 4.0

# --- Runtime --------------------------------------------------------------------
var local_player: Player = null
var camera: Camera2D = null
var hud_layer: CanvasLayer = null
var hp_bar: Control = null
var stamina_bar: Control = null
var ability_slots: Control = null
var mana_bar: Control = null
var pause_menu: Control = null

var _cached_audio_manager: Node = null
var _is_leaving: bool = false


func _ready() -> void:
	_configure()
	GameManager.change_state(GameManager.GameState.IN_ARENA)
	_build_boundaries()
	_spawn_player()
	_setup_camera()
	_setup_hud()
	_populate()
	queue_redraw()

	# Pool projectiles exist after the player's first frame.
	await get_tree().process_frame
	_connect_enemy_hit_signals()
	_start_music()


func _physics_process(_delta: float) -> void:
	# Follow on the physics tick so the camera (physics-interpolated, like the
	# player) moves in lockstep with it instead of fighting interpolation. A large
	# jump (teleport/respawn) snaps and resets interpolation to avoid a streak.
	if camera and local_player and is_instance_valid(local_player):
		var target := local_player.position
		if camera.position.distance_to(target) > CAMERA_SNAP_DISTANCE:
			camera.position = target
			camera.reset_physics_interpolation()
		else:
			camera.position = target


func _process(delta: float) -> void:
	# Sprint zoom — identical feel to the arena (GameConstants is the single source).
	if camera and local_player and is_instance_valid(local_player):
		var target_zoom := GameConstants.CAMERA_ZOOM_DEFAULT
		if local_player.is_sprinting():
			target_zoom = GameConstants.CAMERA_ZOOM_SPRINT
		camera.zoom = camera.zoom.lerp(target_zoom, clampf(delta * GameConstants.CAMERA_ZOOM_SPEED, 0.0, 1.0))

	if local_player and is_instance_valid(local_player):
		if hp_bar and local_player.hp_component:
			hp_bar.update_hp(local_player.hp_component.current_hp, local_player.hp_component.max_hp)
		# Offline has no server/ACTION_CONFIRM, so poll the player's own SM each frame.
		if local_player.movement_sm:
			if stamina_bar:
				stamina_bar.update_value(local_player.movement_sm.stamina, GameConstants.PLAYER_STAMINA_MAX)
				if stamina_bar.has_method("set_exhausted"):
					stamina_bar.set_exhausted(local_player.movement_sm.is_exhausted())
			if mana_bar:
				mana_bar.update_value(local_player.movement_sm.mana, GameConstants.PLAYER_MANA_MAX)

	_process_extra(delta)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("exit_to_menu"):
		if event is InputEventKey and event.echo:
			return
		get_viewport().set_input_as_handled()
		_leave()


# =============================================================================
# VIRTUAL HOOKS (override in subclasses)
# =============================================================================

## Set arena_rect, colors, zoom, wall_thickness, etc. before anything is built.
func _configure() -> void:
	pass


## Spawn enemies and any extra HUD/overlays. Runs after player + HUD exist.
func _populate() -> void:
	pass


## Per-frame extra work for subclasses (camera + HP bar already handled).
func _process_extra(_delta: float) -> void:
	pass


## World position the local player spawns at. Defaults to the room center.
func _get_spawn_position() -> Vector2:
	return arena_rect.get_center()


# =============================================================================
# SETUP
# =============================================================================

func _build_boundaries() -> void:
	var body := StaticBody2D.new()
	body.name = "Boundaries"
	body.collision_layer = ENVIRONMENT_COLLISION_LAYER
	body.collision_mask = 0
	add_child(body)

	var center := arena_rect.get_center()
	var half := wall_thickness * 0.5
	var walls := [
		{
			"name": "TopWall",
			"position": Vector2(center.x, arena_rect.position.y - half),
			"size": Vector2(arena_rect.size.x + wall_thickness * 2.0, wall_thickness),
		},
		{
			"name": "BottomWall",
			"position": Vector2(center.x, arena_rect.position.y + arena_rect.size.y + half),
			"size": Vector2(arena_rect.size.x + wall_thickness * 2.0, wall_thickness),
		},
		{
			"name": "LeftWall",
			"position": Vector2(arena_rect.position.x - half, center.y),
			"size": Vector2(wall_thickness, arena_rect.size.y),
		},
		{
			"name": "RightWall",
			"position": Vector2(arena_rect.position.x + arena_rect.size.x + half, center.y),
			"size": Vector2(wall_thickness, arena_rect.size.y),
		},
	]

	for wall_data: Dictionary in walls:
		var shape := CollisionShape2D.new()
		shape.name = wall_data["name"]
		shape.position = wall_data["position"]
		var rect := RectangleShape2D.new()
		rect.size = wall_data["size"]
		shape.shape = rect
		body.add_child(shape)


func _spawn_player() -> void:
	var player_scene := load(PLAYER_SCENE_PATH)
	if player_scene == null:
		push_error("[OfflineArena] Failed to load player scene")
		return

	local_player = player_scene.instantiate() as Player
	local_player.name = "OfflinePlayer"
	local_player.position = _get_spawn_position()
	# Collide with the offline boundary walls (environment layer).
	local_player.collision_mask |= ENVIRONMENT_COLLISION_LAYER
	local_player.set_player_color(GameManager.player_data.get("player_color", Color(0.27, 0.53, 1.0)))
	# Player.gd is the sole mover here (no PredictionController), so let it run
	# move_and_slide and spawn its own projectiles.
	local_player.prediction_owns_movement = false
	local_player.set_input_enabled(true)
	local_player.set_local_projectile_spawning_enabled(true)
	add_child(local_player)

	# Shoot audio + muzzle flash (online these come from the prediction layer).
	local_player.shot_fired.connect(_on_local_player_shot)


func _setup_camera() -> void:
	camera = Camera2D.new()
	camera.name = "OfflineCamera"
	camera.zoom = GameConstants.CAMERA_ZOOM_DEFAULT
	camera.position_smoothing_enabled = false
	camera.process_callback = Camera2D.CAMERA2D_PROCESS_PHYSICS
	add_child(camera)
	camera.set_physics_interpolation_mode(Node.PHYSICS_INTERPOLATION_MODE_ON)
	camera.make_current()

	if local_player and is_instance_valid(local_player):
		camera.position = local_player.position
		camera.reset_physics_interpolation()


func _setup_hud() -> void:
	hud_layer = CanvasLayer.new()
	hud_layer.name = "HUDLayer"
	add_child(hud_layer)

	# HP / Stamina / Mana bar group — shared layout with the networked arena.
	var bars := BottomBars.create(hud_layer)
	hp_bar = bars["hp"]
	stamina_bar = bars["stamina"]
	ability_slots = bars["ability_slots"]
	mana_bar = bars["mana"]
	if ability_slots and local_player and local_player.movement_sm:
		ability_slots.bind_movement_state_machine(local_player.movement_sm)

	# Level / XP bar (top-center). Offline hubs grant no XP but still show the level.
	var xp_bar := ExperienceBar.new()
	xp_bar.name = "ExperienceBar"
	hud_layer.add_child(xp_bar)
	if local_player and local_player.hp_component:
		hp_bar.update_hp(local_player.hp_component.current_hp, local_player.hp_component.max_hp)

	pause_menu = _create_hud_component(PAUSE_MENU_PATH, "PauseMenu")
	pause_menu.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	hud_layer.add_child(pause_menu)
	# Offline hubs (Sanctuary/Practice) have no arena/server to leave — exit to the menu.
	pause_menu.set_leave_button_text("EXIT TO MENU")
	pause_menu.leave_arena_requested.connect(_leave)
	# Disable the local player's input while paused so clicking pause buttons (left
	# click = the shoot action) doesn't spawn a projectile offline.
	pause_menu.visibility_changed.connect(_on_pause_menu_visibility_changed)


func _on_pause_menu_visibility_changed() -> void:
	if local_player and is_instance_valid(local_player):
		local_player.set_input_enabled(not (pause_menu != null and pause_menu.visible))


func _create_hud_component(script_path: String, node_name: String) -> Control:
	var node := Control.new()
	node.set_script(load(script_path))
	node.name = node_name
	return node


# =============================================================================
# COMBAT WIRING
# =============================================================================

## Route the local player's projectile hits to any enemy. Connected once to the
## whole pool; the group check happens at hit-time so enemies spawned later (e.g.
## a sandbox slime) are covered without re-connecting.
func _connect_enemy_hit_signals() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return
	if local_player.projectile_pool == null:
		return

	for projectile: Projectile in local_player.projectile_pool.pool:
		var hit_callable := Callable(self, "_on_player_projectile_hit").bind(projectile)
		if not projectile.hit.is_connected(hit_callable):
			projectile.hit.connect(hit_callable)


func _on_player_projectile_hit(body: Node2D, projectile: Projectile) -> void:
	if body == null or not is_instance_valid(body):
		return
	if body.is_in_group("enemies") and body.has_method("take_damage"):
		body.take_damage(projectile.damage)


func _on_local_player_shot(pos: Vector2, dir: Vector2) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_player_shoot()

	var flash := ParticleEffects.create_muzzle_flash(pos, dir)
	add_child(flash)


# =============================================================================
# AUDIO / LEAVE / EXIT
# =============================================================================

func _start_music() -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_music("arena_ambience")


func _get_audio_manager() -> Node:
	if _cached_audio_manager == null or not is_instance_valid(_cached_audio_manager):
		_cached_audio_manager = get_tree().root.get_node_or_null("AudioManager")
	return _cached_audio_manager


func _leave() -> void:
	if _is_leaving:
		return
	_is_leaving = true

	var audio := _get_audio_manager()
	if audio:
		audio.stop_music()
	GameManager.change_state(GameManager.GameState.MAIN_MENU)
	SceneManager.goto_main_menu()


func on_scene_exit() -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.stop_music()


# =============================================================================
# RENDER
# =============================================================================

func _draw() -> void:
	draw_rect(arena_rect, floor_color, true)

	var x := arena_rect.position.x
	var right := arena_rect.position.x + arena_rect.size.x
	var bottom := arena_rect.position.y + arena_rect.size.y
	while x <= right:
		draw_line(Vector2(x, arena_rect.position.y), Vector2(x, bottom), grid_color, 1.0)
		x += grid_cell_size

	var y := arena_rect.position.y
	while y <= bottom:
		draw_line(Vector2(arena_rect.position.x, y), Vector2(right, y), grid_color, 1.0)
		y += grid_cell_size

	draw_rect(arena_rect, border_color, false, border_width)
