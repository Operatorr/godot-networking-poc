## GameManager - Core game state management singleton
## Manages game state, player data, and coordinates between systems
extends Node

## Game state enumeration
enum GameState {
	INITIALIZING,      ## Game is starting up
	MAIN_MENU,         ## Player is in main menu
	LOADING,           ## Loading screen active
	IN_ARENA,          ## Player is in the arena
	PAUSED,            ## Game is paused
	EXITING            ## Game is shutting down
}

## Signals for state changes
signal game_state_changed(old_state: GameState, new_state: GameState)
signal player_data_updated()
signal settings_changed()

## Current game state
var current_state: GameState = GameState.INITIALIZING

## Player data
var player_data: Dictionary = {
	"character_name": "",
	"character_id": "",
	"user_id": "",
	"selected_region": "Asia",  ## Default region
	"session_id": ""
}

## Game settings
var settings: Dictionary = {
	"master_volume": 1.0,
	"music_volume": 0.8,
	"sfx_volume": 1.0,
	"fullscreen": false,
	"vsync": true
}

## Statistics tracking
var session_stats: Dictionary = {
	"pvp_kills": 0,
	"monster_kills": 0,
	"deaths": 0,
	"session_start_time": 0
}

## Runtime mode detection
var is_server: bool = false

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	print("[GameManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	if is_server:
		_initialize_server()
	else:
		_initialize_client()

	set_process(true)

## Initialize as server
func _initialize_server() -> void:
	print("[GameManager] Server initialization complete")
	# Server doesn't need settings or main menu state
	change_state(GameState.IN_ARENA)

## Initialize as client
func _initialize_client() -> void:
	_load_settings()
	change_state(GameState.MAIN_MENU)

## Change the current game state
func change_state(new_state: GameState) -> void:
	if current_state == new_state:
		return

	var old_state = current_state
	current_state = new_state

	print("[GameManager] State changed: %s -> %s" % [
		GameState.keys()[old_state],
		GameState.keys()[new_state]
	])

	game_state_changed.emit(old_state, new_state)
	_handle_state_transition(old_state, new_state)

## Handle state-specific transitions
func _handle_state_transition(_old_state: GameState, new_state: GameState) -> void:
	match new_state:
		GameState.MAIN_MENU:
			_on_enter_main_menu()
		GameState.IN_ARENA:
			_on_enter_arena()
		GameState.LOADING:
			_on_enter_loading()
		GameState.EXITING:
			_on_enter_exiting()

## Called when entering main menu
func _on_enter_main_menu() -> void:
	print("[GameManager] Entered main menu")
	# Reset session stats
	session_stats.deaths = 0
	session_stats.pvp_kills = 0
	session_stats.monster_kills = 0

## Called when entering arena
func _on_enter_arena() -> void:
	print("[GameManager] Entered arena")
	session_stats.session_start_time = Time.get_ticks_msec()

## Called when entering loading screen
func _on_enter_loading() -> void:
	print("[GameManager] Loading...")

## Called when exiting game
func _on_enter_exiting() -> void:
	print("[GameManager] Exiting game...")
	_save_settings()

## Set player data
func set_player_data(data: Dictionary) -> void:
	player_data.merge(data, true)
	player_data_updated.emit()
	print("[GameManager] Player data updated: %s" % player_data.get("character_name", "Unknown"))

## Get player data
func get_player_data() -> Dictionary:
	return player_data.duplicate()

## Update player stat
func update_stat(stat_name: String, value: int) -> void:
	if session_stats.has(stat_name):
		session_stats[stat_name] += value
		print("[GameManager] Stat updated - %s: %d" % [stat_name, session_stats[stat_name]])

## Get current statistics
func get_stats() -> Dictionary:
	return session_stats.duplicate()

## Update game setting
func update_setting(setting_name: String, value) -> void:
	if settings.has(setting_name):
		settings[setting_name] = value
		settings_changed.emit()
		_apply_setting(setting_name, value)
		print("[GameManager] Setting updated - %s: %s" % [setting_name, str(value)])

## Apply individual setting
func _apply_setting(setting_name: String, value) -> void:
	# Server doesn't need display/audio settings
	if is_server:
		return

	match setting_name:
		"fullscreen":
			if value:
				DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
			else:
				DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
		"vsync":
			if value:
				DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED)
			else:
				DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		"master_volume", "music_volume", "sfx_volume":
			# AudioManager will listen to settings_changed signal
			pass

## Load settings from file
func _load_settings() -> void:
	var save_path = "user://settings.json"
	if FileAccess.file_exists(save_path):
		var file = FileAccess.open(save_path, FileAccess.READ)
		if file:
			var json_string = file.get_as_text()
			var json = JSON.new()
			var error = json.parse(json_string)
			if error == OK:
				var loaded_settings = json.data
				if typeof(loaded_settings) == TYPE_DICTIONARY:
					settings.merge(loaded_settings, true)
					print("[GameManager] Settings loaded")
			file.close()

	# Apply all loaded settings
	for setting_name in settings:
		_apply_setting(setting_name, settings[setting_name])

## Save settings to file
func _save_settings() -> void:
	var save_path = "user://settings.json"
	var file = FileAccess.open(save_path, FileAccess.WRITE)
	if file:
		var json_string = JSON.stringify(settings, "\t")
		file.store_string(json_string)
		file.close()
		print("[GameManager] Settings saved")

## Check if player is authenticated
func is_authenticated() -> bool:
	return not player_data.user_id.is_empty() and not player_data.character_id.is_empty()

## Check if player has character
func has_character() -> bool:
	return not player_data.character_name.is_empty()

## Clear player data (logout)
func clear_player_data() -> void:
	player_data = {
		"character_name": "",
		"character_id": "",
		"user_id": "",
		"selected_region": player_data.get("selected_region", "Asia"),
		"session_id": ""
	}
	player_data_updated.emit()
	print("[GameManager] Player data cleared")

## Get session duration in seconds
func get_session_duration() -> float:
	if session_stats.session_start_time == 0:
		return 0.0
	return (Time.get_ticks_msec() - session_stats.session_start_time) / 1000.0
