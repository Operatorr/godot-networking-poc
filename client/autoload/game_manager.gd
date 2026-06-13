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

## Emitted when the player's level/XP changes (HUD listens). `leveled_up` is true on
## the frame a level boundary was crossed. Now driven by authoritative PROGRESS
## events (set_progression), not local XP math. See docs/systems/PROGRESSION.md.
signal experience_updated(level: int, experience: int, xp_to_next: int, leveled_up: bool)

## Cosmetic-only "+N XP" floater hint. Emitted on an EXP_GAIN event for the local
## player; does NOT change level/experience (the server owns those). Listeners may
## spawn a floating number; ignoring it is fine.
signal experience_gained(amount: int)

## Progression curve — DISPLAY ONLY. The server (+ Go API) now own level/XP and
## persistence; the client never writes it back. The curve below only sizes the
## HUD XP bar (xp_to_next_level) from the authoritative level the server sends via
## PROGRESS events (set_progression). See docs/systems/PROGRESSION.md.
const XP_FIRST_LEVEL := 100   ## Level 1 -> 2 == 5 Toxic Slimes (20 XP each)
const XP_LEVEL_SLOPE := 200   ## Level L -> L+1 for L >= 2 == 10 same-level mobs
const MAX_PLAYER_LEVEL := 50

## Current game state
var current_state: GameState = GameState.INITIALIZING

## Player data
var player_data: Dictionary = {
	"character_name": "",
	"character_id": "",
	"user_id": "",
	"selected_region": "Asia",  ## Default region
	"session_id": "",
	"player_color": Color(0.27, 0.53, 1.0),
	"player_class": 0,  ## PacketTypes.PlayerClass.ZEALOT
	"player_level": 1,
	"player_experience": 0,
	"player_move_speed": 0,  ## Effective base move speed from the latest PROGRESS event (0 = unknown)
	"character_mode": "softcore"  ## "softcore" (respawn) or "hardcore" (permadeath on death)
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

## Local player's network entity ID (set when spawned in arena)
## Used by PredictionController for reconciliation
var local_player_entity_id: int = -1

## Guards the one-time physics-tick alignment below so it never re-applies.
var _physics_tick_rate_applied: bool = false

## Progression is now server-authoritative (Rust server + Go API persist it). The
## client no longer PATCHes /api/character with level/XP, so there is no dirty state
## or flush timer to track anymore.

## Called when the node enters the scene tree
func _ready() -> void:
	# Make GameConstants.SERVER_TICK_RATE the single authority for the client
	# clock: align Engine.physics_ticks_per_second (drives _physics_process for
	# prediction/interpolation) with the sim cadence ONCE at startup, before the
	# arena loads. project.godot physics_ticks_per_second=30 is only the fallback.
	# Runs in both client+server mode (harmless on the server, which ticks via a
	# manual accumulator on config.tick_rate, not _physics_process).
	if not _physics_tick_rate_applied:
		_physics_tick_rate_applied = true
		Engine.physics_ticks_per_second = int(GameConstants.SERVER_TICK_RATE)

	# Detect if running as dedicated server
	is_server = (OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless") and not _is_test_scene()

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
	# Apply any custom keyboard rebinds onto the InputMap before gameplay starts
	# (Settings → Keyboard Controls persists them to user://preferences.json).
	UserPreferences.load_preferences().apply_keybinds()
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

## True when the active character is hardcore (permadeath). On hardcore death the server
## converts XP→Glory and deletes the character, so the client shows the permadeath death
## screen ("Your Glory will be remembered" + Back to Main Menu) instead of respawning.
func is_hardcore() -> bool:
	return String(player_data.get("character_mode", "softcore")).to_lower() == "hardcore"

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
		"session_id": "",
		"player_color": player_data.get("player_color", Color(0.27, 0.53, 1.0)),
		"player_class": 0,
		"player_level": 1,
		"player_experience": 0,
		"player_move_speed": 0,
		"character_mode": "softcore"
	}
	player_data_updated.emit()
	print("[GameManager] Player data cleared")

## Get session duration in seconds
func get_session_duration() -> float:
	if session_stats.session_start_time == 0:
		return 0.0
	return (Time.get_ticks_msec() - session_stats.session_start_time) / 1000.0


## Set local player's network entity ID
func set_local_player_entity_id(id: int) -> void:
	local_player_entity_id = id
	print("[GameManager] Local player entity ID set: %d" % id)


## Get local player's network entity ID
func get_local_player_entity_id() -> int:
	return local_player_entity_id


## Clear local player entity ID (on disconnect/logout)
func clear_local_player_entity_id() -> void:
	local_player_entity_id = -1
	print("[GameManager] Local player entity ID cleared")


## XP required to advance FROM `level` to the next. Level 1 is intentionally cheap
## (a quick first level); thereafter it scales so ~10 same-level kills == one level.
func xp_to_next_level(level: int) -> int:
	if level >= MAX_PLAYER_LEVEL:
		return 0
	if level <= 1:
		return XP_FIRST_LEVEL
	return XP_LEVEL_SLOPE * level


func get_player_level() -> int:
	return maxi(1, int(player_data.get("player_level", 1)))


func get_player_experience() -> int:
	return maxi(0, int(player_data.get("player_experience", 0)))


func get_player_move_speed() -> int:
	return maxi(0, int(player_data.get("player_move_speed", 0)))


## Seed progression from the account (after login). Emits experience_updated so the HUD
## initializes. Level/XP are display-only now; the server stays authoritative.
func init_progression(level: int, experience: int) -> void:
	player_data["player_level"] = clampi(level, 1, MAX_PLAYER_LEVEL)
	player_data["player_experience"] = maxi(0, experience)
	experience_updated.emit(
		get_player_level(), get_player_experience(), xp_to_next_level(get_player_level()), false
	)


## Reset local progression display to a brand-new character (level 1, no XP). The DB is
## authoritative; this only keeps the local display from leaking a deleted/old character's
## level into the next one. Does NOT persist (the server owns persistence).
func reset_progression() -> void:
	player_data["player_level"] = 1
	player_data["player_experience"] = 0
	player_data["player_move_speed"] = 0
	experience_updated.emit(1, 0, xp_to_next_level(1), false)


## Authoritative progression update from a server PROGRESS event. The server (+ Go API)
## own level/XP/persistence now, so this just mirrors the values into player_data for the
## HUD and stores the effective base move speed (prediction adopts it separately). The
## `leveled_up` flag is derived from the level rising vs. the last known value.
func set_progression(level: int, experience: int, move_speed: int) -> void:
	var prev_level := get_player_level()
	var clamped_level := clampi(level, 1, MAX_PLAYER_LEVEL)
	player_data["player_level"] = clamped_level
	player_data["player_experience"] = maxi(0, experience)
	if move_speed > 0:
		player_data["player_move_speed"] = move_speed
	experience_updated.emit(
		clamped_level, get_player_experience(), xp_to_next_level(clamped_level), clamped_level > prev_level
	)


## COSMETIC ONLY. The server owns leveling now (it sends authoritative PROGRESS events),
## so this no longer mutates level/XP or persists anything — it only emits a "+N XP"
## floater hint for the HUD. Kept so existing EXP_GAIN callers stay valid.
func grant_experience(amount: int) -> void:
	if amount <= 0:
		return
	experience_gained.emit(amount)


## No-op. Progression persistence moved to the server + Go API; the client must never
## PATCH /api/character with level/XP or it would clobber the authoritative value. Kept
## as an inert stub so existing callers (e.g. arena teardown) stay valid.
func persist_progression() -> void:
	pass


func _is_test_scene() -> bool:
	var current_scene: Node = get_tree().current_scene
	if current_scene == null:
		var root := get_tree().root
		if root.get_child_count() > 0:
			current_scene = root.get_child(root.get_child_count() - 1)

	if current_scene == null:
		return false

	var scene_path := current_scene.scene_file_path
	return scene_path.begins_with("res://scenes/test/") \
		or scene_path == "res://scenes/shared/levels/practice.tscn"
