## SceneManager - Scene transition handling singleton
## Manages scene transitions, loading screens, and resource cleanup
## Coordinates scene changes between Main Menu, Arena, and Loading screens
extends Node

## Runtime mode detection
var is_server: bool = false

## Scene paths (updated for client/server/shared structure)
const SCENE_MAIN = "res://scenes/main.tscn"
const SCENE_MAIN_MENU = "res://scenes/client/menus/main_menu.tscn"
const SCENE_CHARACTER_CREATION = "res://scenes/client/menus/character_creation.tscn"
const SCENE_LOADING = "res://scenes/client/menus/loading_screen.tscn"
const SCENE_ARENA = "res://scenes/shared/game/arena.tscn"
const SCENE_GAME_UI = "res://scenes/client/components/game_ui.tscn"
const SCENE_SERVER_MAIN = "res://scenes/server/server_main.tscn"

## Scene names enum
enum SceneName {
	MAIN,
	MAIN_MENU,
	CHARACTER_CREATION,
	LOADING,
	ARENA,
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
var is_loading: bool = false
var load_progress: Array = []

## Scene cache (optional - for faster transitions)
var scene_cache: Dictionary = {}
var enable_scene_caching: bool = false

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

	# Wait for other autoloads to initialize
	await get_tree().process_frame

	# If server, load server scene
	if is_server:
		print("[SceneManager] Loading server scene...")
		change_scene(SceneName.SERVER_MAIN, false)

## Change to a specific scene
func change_scene(scene_name: SceneName, use_loading_screen: bool = false) -> void:
	if is_transitioning:
		print("[SceneManager] Scene transition already in progress")
		return

	var scene_path = _get_scene_path(scene_name)
	if scene_path.is_empty():
		print("[SceneManager] Invalid scene name: %d" % scene_name)
		return

	print("[SceneManager] Changing scene to: %s" % scene_path)

	is_transitioning = true
	scene_change_started.emit(current_scene_name, scene_path)

	# Update GameManager state
	_update_game_state_for_scene(scene_name)

	if use_loading_screen:
		await _change_scene_with_loading(scene_path)
	else:
		await _change_scene_direct(scene_path)

	is_transitioning = false

## Direct scene change (no loading screen)
func _change_scene_direct(scene_path: String) -> void:
	print("[SceneManager] Performing direct scene change to: %s" % scene_path)

	# Clean up current scene
	if current_scene:
		_cleanup_scene(current_scene)
		current_scene.queue_free()

	# Load new scene
	var new_scene = _load_scene(scene_path)

	if new_scene == null:
		print("[SceneManager] Failed to load scene: %s" % scene_path)
		return

	# Add new scene to tree
	get_tree().root.add_child(new_scene)
	get_tree().current_scene = new_scene

	current_scene = new_scene
	current_scene_name = scene_path

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
		get_tree().root.add_child(loading_screen)

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

	loading_screen.queue_free()
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
		SceneName.MAIN_MENU:
			return SCENE_MAIN_MENU
		SceneName.CHARACTER_CREATION:
			return SCENE_CHARACTER_CREATION
		SceneName.LOADING:
			return SCENE_LOADING
		SceneName.ARENA:
			return SCENE_ARENA
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
		SceneName.MAIN_MENU, SceneName.CHARACTER_CREATION:
			game_mgr.change_state(game_mgr.GameState.MAIN_MENU)
		SceneName.LOADING:
			game_mgr.change_state(game_mgr.GameState.LOADING)
		SceneName.ARENA:
			game_mgr.change_state(game_mgr.GameState.IN_ARENA)

## Cleanup scene before transition
func _cleanup_scene(scene: Node) -> void:
	print("[SceneManager] Cleaning up scene: %s" % scene.name)

	# Disconnect from server if in arena
	var net_mgr = get_tree().root.get_node_or_null("NetworkManager")
	if net_mgr and net_mgr.is_server_connected():
		if current_scene_name == SCENE_ARENA:
			print("[SceneManager] Disconnecting from game server...")
			net_mgr.disconnect_from_server("Scene change")

	# Give scene a chance to cleanup
	if scene.has_method("on_scene_exit"):
		scene.on_scene_exit()

	# Clear any timers or signals
	for child in scene.get_children():
		if child is Timer:
			child.stop()

## Convenience methods for common transitions

## Go to main menu
func goto_main_menu() -> void:
	change_scene(SceneName.MAIN_MENU, false)

## Go to character creation
func goto_character_creation() -> void:
	change_scene(SceneName.CHARACTER_CREATION, false)

## Go to arena (with loading screen)
func goto_arena() -> void:
	change_scene(SceneName.ARENA, true)

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
