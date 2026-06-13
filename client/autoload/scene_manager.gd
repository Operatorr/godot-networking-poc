## SceneManager - Scene transition handling singleton
## Manages scene transitions, loading screens, and resource cleanup
## Coordinates scene changes between Main Menu, Arena, and Loading screens
extends Node

## Runtime mode detection
var is_server: bool = false

## Scene paths (updated for client/server/shared structure)
const SCENE_MAIN = "res://scenes/main.tscn"
const SCENE_LOGIN = "res://scenes/client/menus/login_screen.tscn"
const SCENE_MAIN_MENU = "res://scenes/client/menus/main_menu.tscn"
const SCENE_CHARACTER_CREATION = "res://scenes/client/menus/character_creation.tscn"
const SCENE_LOADING = "res://scenes/client/menus/loading_screen.tscn"
const SCENE_ARENA = "res://scenes/shared/arena/arena_base.tscn"
const SCENE_SANCTUARY = "res://scenes/shared/sanctuary/sanctuary.tscn"
const SCENE_PRACTICE = "res://scenes/shared/levels/practice.tscn"
const SCENE_OFFLINE_SANDBOX = "res://scenes/test/sandbox.tscn"
const SCENE_GAME_UI = "res://scenes/client/components/game_ui.tscn"
const SCENE_SERVER_MAIN = "res://scenes/server/server_main.tscn"

## Scene names enum
enum SceneName {
	MAIN,
	LOGIN,
	MAIN_MENU,
	CHARACTER_CREATION,
	LOADING,
	ARENA,
	SANCTUARY,
	PRACTICE,
	OFFLINE_SANDBOX,
	GAME_UI,
	SERVER_MAIN
}

## Signals
signal scene_change_started(from_scene: String, to_scene: String)
signal scene_change_completed(scene_name: String)
signal loading_progress_updated(progress: float)
signal scene_loaded(scene: Node)

## Current scene state
var current_scene: Node = null
var current_scene_name: String = ""
var is_transitioning: bool = false

## Loading state
var loading_screen: Node = null
## High CanvasLayer that hosts the loading screen so it renders ABOVE the newly-added
## scene during the swap (a plain Control on root would be drawn under it, leaking a
## half-rendered frame — the "half sanctuary / half black" entry glitch).
var _loading_layer: CanvasLayer = null
var is_loading: bool = false
var load_progress: Array = []

## Scene cache (optional - for faster transitions)
var scene_cache: Dictionary = {}
var enable_scene_caching: bool = false

## Fade transition overlay
var _fade_layer: CanvasLayer = null
var _fade_rect: ColorRect = null
const FADE_DURATION := 0.3

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	print("[SceneManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	# Get current scene
	var root = get_tree().root
	current_scene = root.get_child(root.get_child_count() - 1)

	if current_scene:
		current_scene_name = current_scene.scene_file_path
		print("[SceneManager] Current scene: %s" % current_scene_name)

	# Create fade transition overlay
	_setup_fade_overlay()

	# Wait for other autoloads to initialize
	await get_tree().process_frame

	# Skip routing for test scenes (run via F6 or headless CLI)
	if _is_standalone_scene(current_scene_name):
		print("[SceneManager] Standalone scene detected, skipping route")
		return

	# If server, load server scene
	if is_server:
		print("[SceneManager] Loading server scene...")
		change_scene(SceneName.SERVER_MAIN, false)
	else:
		# Client: Route based on auth state
		_route_to_initial_scene()

## Route to initial scene based on authentication and character state
func _route_to_initial_scene() -> void:
	var auth_mgr = get_tree().root.get_node_or_null("AuthManager")
	var game_mgr = get_tree().root.get_node_or_null("GameManager")

	# Check if user is logged in
	if auth_mgr and auth_mgr.is_logged_in():
		print("[SceneManager] User is logged in, checking character state...")
		# Check if user has a character
		if game_mgr and game_mgr.has_character():
			print("[SceneManager] User has character, going to main menu")
			change_scene(SceneName.MAIN_MENU, false)
		else:
			print("[SceneManager] User has no character, going to character creation")
			change_scene(SceneName.CHARACTER_CREATION, false)
	else:
		print("[SceneManager] User not logged in, going to login screen")
		change_scene(SceneName.LOGIN, false)

## Change to a specific scene
func change_scene(scene_name: SceneName, use_loading_screen: bool = false) -> void:
	var scene_path = _get_scene_path(scene_name)
	if scene_path.is_empty():
		print("[SceneManager] Invalid scene name: %d" % scene_name)
		return

	# Update GameManager state
	_update_game_state_for_scene(scene_name)

	await change_scene_to_path(scene_path, use_loading_screen)


## Change to an arbitrary scene file. Used by Portal for destinations that have
## no SceneName (dungeons, sub-worlds); GameManager state is left untouched.
func change_scene_to_path(scene_path: String, use_loading_screen: bool = false) -> void:
	if is_transitioning:
		print("[SceneManager] Scene transition already in progress")
		return

	print("[SceneManager] Changing scene to: %s" % scene_path)

	is_transitioning = true
	scene_change_started.emit(current_scene_name, scene_path)

	if use_loading_screen:
		await _change_scene_with_loading(scene_path)
	else:
		await _change_scene_direct(scene_path)

	is_transitioning = false

## Direct scene change with fade transition
func _change_scene_direct(scene_path: String) -> void:
	print("[SceneManager] Performing direct scene change to: %s" % scene_path)

	# Fade out
	if not is_server:
		await _fade_out()

	# Clean up current scene
	if current_scene:
		_cleanup_scene(current_scene)
		current_scene.queue_free()

	# Load new scene
	var new_scene = _load_scene(scene_path)

	if new_scene == null:
		print("[SceneManager] Failed to load scene: %s" % scene_path)
		if not is_server:
			await _fade_in()
		return

	# Add new scene to tree
	get_tree().root.add_child(new_scene)
	get_tree().current_scene = new_scene

	current_scene = new_scene
	current_scene_name = scene_path

	# Fade in
	if not is_server:
		await _fade_in()

	print("[SceneManager] Scene changed to: %s" % scene_path)
	scene_change_completed.emit(scene_path)
	scene_loaded.emit(new_scene)

## Scene change with loading screen
func _change_scene_with_loading(scene_path: String) -> void:
	print("[SceneManager] Performing scene change with loading screen to: %s" % scene_path)

	# Show loading screen
	await _show_loading_screen()

	# Start background loading
	var error = ResourceLoader.load_threaded_request(scene_path)

	if error != OK:
		print("[SceneManager] Failed to start loading scene: %s (Error: %d)" % [scene_path, error])
		await _hide_loading_screen()
		return

	is_loading = true

	# Wait for scene to load
	while is_loading:
		var status = ResourceLoader.load_threaded_get_status(scene_path, load_progress)

		match status:
			ResourceLoader.THREAD_LOAD_IN_PROGRESS:
				var progress = load_progress[0] if load_progress.size() > 0 else 0.0
				loading_progress_updated.emit(progress)
				await get_tree().create_timer(0.1).timeout

			ResourceLoader.THREAD_LOAD_LOADED:
				loading_progress_updated.emit(1.0)
				is_loading = false

			ResourceLoader.THREAD_LOAD_FAILED, ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
				print("[SceneManager] Failed to load scene: %s" % scene_path)
				is_loading = false
				await _hide_loading_screen()
				return

	# Get loaded scene
	var packed_scene = ResourceLoader.load_threaded_get(scene_path)

	if packed_scene == null:
		print("[SceneManager] Failed to get loaded scene")
		await _hide_loading_screen()
		return

	# Clean up current scene
	if current_scene:
		_cleanup_scene(current_scene)
		current_scene.queue_free()

	# Instance new scene
	var new_scene = packed_scene.instantiate()

	# Add new scene to tree
	get_tree().root.add_child(new_scene)
	get_tree().current_scene = new_scene

	current_scene = new_scene
	current_scene_name = scene_path

	# Hide loading screen
	await _hide_loading_screen()

	print("[SceneManager] Scene changed to: %s" % scene_path)
	scene_change_completed.emit(scene_path)
	scene_loaded.emit(new_scene)

## Show loading screen
func _show_loading_screen() -> void:
	if loading_screen != null:
		return

	print("[SceneManager] Showing loading screen")

	# Check if loading screen scene exists
	if not ResourceLoader.exists(SCENE_LOADING):
		print("[SceneManager] Loading screen scene not found: %s" % SCENE_LOADING)
		return

	var loading_scene = load(SCENE_LOADING)
	if loading_scene:
		loading_screen = loading_scene.instantiate()
		# Host the loading screen on a high CanvasLayer (below the fade overlay at 128)
		# so it stays on top of the swapped-in scene until explicitly hidden.
		_loading_layer = CanvasLayer.new()
		_loading_layer.layer = 100
		get_tree().root.add_child(_loading_layer)
		_loading_layer.add_child(loading_screen)

		# If loading screen has an animation, play it
		if loading_screen.has_method("show_loading"):
			loading_screen.show_loading()

		await get_tree().create_timer(0.3).timeout  # Brief delay for visual feedback

## Hide loading screen
func _hide_loading_screen() -> void:
	if loading_screen == null:
		return

	print("[SceneManager] Hiding loading screen")

	# If loading screen has an animation, play it
	if loading_screen.has_method("hide_loading"):
		loading_screen.hide_loading()
		await get_tree().create_timer(0.3).timeout

	# Free the host layer (which frees the loading screen child).
	if _loading_layer != null:
		_loading_layer.queue_free()
		_loading_layer = null
	loading_screen = null

## Load scene from path
func _load_scene(scene_path: String) -> Node:
	# Check cache first
	if enable_scene_caching and scene_cache.has(scene_path):
		print("[SceneManager] Loading scene from cache: %s" % scene_path)
		return scene_cache[scene_path].instantiate()

	# Load scene
	if not ResourceLoader.exists(scene_path):
		print("[SceneManager] Scene not found: %s" % scene_path)
		return null

	var packed_scene = load(scene_path)

	if packed_scene == null:
		print("[SceneManager] Failed to load scene: %s" % scene_path)
		return null

	# Cache if enabled
	if enable_scene_caching:
		scene_cache[scene_path] = packed_scene

	return packed_scene.instantiate()

## Get scene path from enum
func _get_scene_path(scene_name: SceneName) -> String:
	match scene_name:
		SceneName.MAIN:
			return SCENE_MAIN
		SceneName.LOGIN:
			return SCENE_LOGIN
		SceneName.MAIN_MENU:
			return SCENE_MAIN_MENU
		SceneName.CHARACTER_CREATION:
			return SCENE_CHARACTER_CREATION
		SceneName.LOADING:
			return SCENE_LOADING
		SceneName.ARENA:
			return SCENE_ARENA
		SceneName.SANCTUARY:
			return SCENE_SANCTUARY
		SceneName.PRACTICE:
			return SCENE_PRACTICE
		SceneName.OFFLINE_SANDBOX:
			return SCENE_OFFLINE_SANDBOX
		SceneName.GAME_UI:
			return SCENE_GAME_UI
		SceneName.SERVER_MAIN:
			return SCENE_SERVER_MAIN
		_:
			return ""

## Update GameManager state based on scene
func _update_game_state_for_scene(scene_name: SceneName) -> void:
	# GameManager may not be initialized yet, defer update
	if not is_node_ready():
		return

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if not game_mgr:
		return

	match scene_name:
		SceneName.LOGIN, SceneName.MAIN_MENU, SceneName.CHARACTER_CREATION:
			game_mgr.change_state(game_mgr.GameState.MAIN_MENU)
		SceneName.LOADING:
			game_mgr.change_state(game_mgr.GameState.LOADING)
		SceneName.ARENA, SceneName.SANCTUARY, SceneName.PRACTICE, SceneName.OFFLINE_SANDBOX:
			game_mgr.change_state(game_mgr.GameState.IN_ARENA)

## Cleanup scene before transition
func _cleanup_scene(scene: Node) -> void:
	print("[SceneManager] Cleaning up scene: %s" % scene.name)

	# NOTE: the networked scenes (Arena AND Sanctuary) now each own their server-connection
	# lifecycle — the Arena↔Sanctuary portal/leave handlers disconnect from the old instance
	# and dial the new one explicitly, and the main menu dials the Sanctuary before entering.
	# SceneManager must NOT disconnect here: a transition between the two instances opens the
	# NEXT connection *before* the old scene is freed, and a blind disconnect here would kill
	# that fresh link (the 0.3s fade window is long enough for a localhost handshake to finish).

	# Give scene a chance to cleanup
	if scene.has_method("on_scene_exit"):
		scene.on_scene_exit()

	# Clear any timers or signals
	for child in scene.get_children():
		if child is Timer:
			child.stop()

## Convenience methods for common transitions

## Go to login screen
func goto_login() -> void:
	change_scene(SceneName.LOGIN, false)

## Go to main menu
func goto_main_menu() -> void:
	change_scene(SceneName.MAIN_MENU, false)

## Go to character creation
func goto_character_creation() -> void:
	change_scene(SceneName.CHARACTER_CREATION, false)

## Go to arena (with loading screen)
func goto_arena() -> void:
	change_scene(SceneName.ARENA, true)


## Go to the Sanctuary town hub (offline; entering the world lands here)
func goto_sanctuary() -> void:
	change_scene(SceneName.SANCTUARY, false)

## Go to offline practice level
func goto_practice() -> void:
	change_scene(SceneName.PRACTICE, false)

## Go to offline sandbox test scene
func goto_offline_sandbox() -> void:
	change_scene(SceneName.OFFLINE_SANDBOX, false)

## Reload current scene
func reload_current_scene() -> void:
	if current_scene_name.is_empty():
		print("[SceneManager] No current scene to reload")
		return

	print("[SceneManager] Reloading current scene: %s" % current_scene_name)
	var scene_path = current_scene_name
	await _change_scene_direct(scene_path)

## Get current scene node
func get_current_scene() -> Node:
	return current_scene

## Check if currently transitioning
func is_scene_transitioning() -> bool:
	return is_transitioning

## Enable or disable scene caching
func set_scene_caching(enabled: bool) -> void:
	enable_scene_caching = enabled
	print("[SceneManager] Scene caching %s" % ("enabled" if enabled else "disabled"))

	if not enabled:
		scene_cache.clear()

## Preload a scene into cache
func preload_scene(scene_name: SceneName) -> void:
	if not enable_scene_caching:
		print("[SceneManager] Scene caching is disabled")
		return

	var scene_path = _get_scene_path(scene_name)
	if scene_path.is_empty():
		return

	if scene_cache.has(scene_path):
		print("[SceneManager] Scene already cached: %s" % scene_path)
		return

	if not ResourceLoader.exists(scene_path):
		print("[SceneManager] Scene not found: %s" % scene_path)
		return

	print("[SceneManager] Preloading scene: %s" % scene_path)
	var packed_scene = load(scene_path)
	if packed_scene:
		scene_cache[scene_path] = packed_scene
		print("[SceneManager] Scene preloaded successfully")

## Clear scene cache
func clear_cache() -> void:
	scene_cache.clear()
	print("[SceneManager] Scene cache cleared")


func _is_standalone_scene(scene_path: String) -> bool:
	return scene_path.begins_with("res://scenes/test/") \
		or scene_path == SCENE_PRACTICE \
		or scene_path == SCENE_OFFLINE_SANDBOX


## Set up the fade overlay CanvasLayer
func _setup_fade_overlay() -> void:
	if is_server:
		return
	_fade_layer = CanvasLayer.new()
	_fade_layer.layer = 128  # Above everything
	add_child(_fade_layer)

	_fade_rect = ColorRect.new()
	_fade_rect.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_fade_rect.color = Color(0, 0, 0, 0)
	_fade_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_fade_layer.add_child(_fade_rect)


## Fade to black
func _fade_out() -> void:
	if _fade_rect == null:
		return
	_fade_rect.color = Color(0, 0, 0, 0)
	var tween := create_tween()
	tween.tween_property(_fade_rect, "color:a", 1.0, FADE_DURATION)
	await tween.finished


## Fade from black
func _fade_in() -> void:
	if _fade_rect == null:
		return
	_fade_rect.color = Color(0, 0, 0, 1)
	var tween := create_tween()
	tween.tween_property(_fade_rect, "color:a", 0.0, FADE_DURATION)
	await tween.finished
