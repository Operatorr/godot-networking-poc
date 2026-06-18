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

## Glory = floor(total lifetime XP / GLORY_XP_DIVISOR). Mirrors the Go API + Rust server
## (api/internal/progression/progression.go, rust/sim_core/src/progression.rs) so the client
## can display the EXACT Glory the server credits on a hardcore death without a wire field.
const GLORY_XP_DIVISOR := 100

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
	"character_mode": "softcore",  ## "softcore" (respawn) or "hardcore" (permadeath on death)
	"glory": 0  ## Account-scoped Glory (survives a hardcore permadeath); kept consistent with clear_player_data
}

## Game settings.
## window_mode: "windowed_fullscreen" (Godot 4's WINDOW_MODE_FULLSCREEN — borderless,
## non-exclusive fullscreen that covers the screen; the default) or "windowed" (a small
## centered window). The Settings → Video tab toggles it. Replaces the old boolean
## "fullscreen" key (migrated away in _load_settings).
##
## The project BOOTS windowed (project.godot window/size/mode=0) on purpose: on macOS
## WINDOW_MODE_FULLSCREEN opens a native fullscreen Space with an animated transition, and
## leaving that Space on the autoload's first frame is unreliable — a saved "windowed"
## preference wouldn't stick. _load_settings() applies the saved/default window_mode at
## startup, so we only ever transition INTO fullscreen at runtime (the reliable direction).
var settings: Dictionary = {
	"master_volume": 1.0,
	"music_volume": 0.8,
	"sfx_volume": 1.0,
	"window_mode": "windowed_fullscreen",
	"vsync": true
}

## Window size used for the "windowed" (small) mode. Centered on the current screen.
const WINDOWED_SMALL_SIZE := Vector2i(1280, 720)

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

## Debounced settings save: update_setting() sets _settings_save_pending and (re)starts a short
## one-shot timer instead of writing to disk on every change (e.g. each volume-slider step).
## When the timer fires, _flush_settings_save() does one write. Window_mode/vsync persist the
## same way. A pending save is also force-flushed on shutdown by _notification() (window close
## or tree teardown) so a change made inside the debounce window isn't lost on quit.
const SETTINGS_SAVE_DEBOUNCE := 0.5
var _settings_save_pending: bool = false
var _settings_save_timer: SceneTreeTimer = null

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
	# Force-flush any debounced save so a last-moment change isn't lost on quit.
	_settings_save_pending = false
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
		# Persist on a short debounce so a rapid stream of changes (e.g. a dragged volume
		# slider) doesn't write to disk on every step. window_mode/vsync persist the same
		# way; the timer fires well before a normal quit (EXITING also force-flushes).
		_schedule_settings_save()
		print("[GameManager] Setting updated - %s: %s" % [setting_name, str(value)])
	else:
		push_warning("[GameManager] update_setting: unknown setting '%s' (ignored)" % setting_name)

## Mark settings dirty and (re)start the debounce timer so the next quiet window triggers one
## save. Restarting on each call coalesces a burst of updates into a single disk write.
func _schedule_settings_save() -> void:
	_settings_save_pending = true
	if _settings_save_timer != null and _settings_save_timer.time_left > 0.0:
		# A timer is already counting down; let it keep running rather than spawning another.
		return
	_settings_save_timer = get_tree().create_timer(SETTINGS_SAVE_DEBOUNCE)
	_settings_save_timer.timeout.connect(_flush_settings_save)

## Write settings to disk once if a save is pending. Called when the debounce timer fires.
func _flush_settings_save() -> void:
	_settings_save_timer = null
	if not _settings_save_pending:
		return
	_settings_save_pending = false
	_save_settings()

## Force-write any pending debounced settings on shutdown so a last-moment change (e.g. toggling
## a setting then quitting inside the SETTINGS_SAVE_DEBOUNCE window) isn't lost. The SceneTreeTimer
## that normally triggers the write won't fire during teardown, so flush synchronously here.
## NOTIFICATION_WM_CLOSE_REQUEST covers a normal window close / Cmd-Q; NOTIFICATION_EXIT_TREE covers
## get_tree().quit() (the in-game Exit buttons). A hard kill (SIGKILL) can't be caught.
func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST or what == NOTIFICATION_EXIT_TREE:
		_flush_settings_save()

## Apply individual setting
func _apply_setting(setting_name: String, value) -> void:
	# Server doesn't need display/audio settings
	if is_server:
		return

	match setting_name:
		"window_mode":
			_apply_window_mode(str(value))
		"vsync":
			if value:
				DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED)
			else:
				DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		"master_volume", "music_volume", "sfx_volume":
			# AudioManager will listen to settings_changed signal
			pass


## Apply the window mode. "windowed_fullscreen" = Godot 4's WINDOW_MODE_FULLSCREEN — borderless,
## non-exclusive windowed-fullscreen (the default launch mode); anything else = a small centered
## window.
func _apply_window_mode(mode: String) -> void:
	# Independent entry point (also called per-setting from _apply_setting), so it keeps its
	# own server guard even though the only current caller already short-circuits servers.
	if is_server:
		return
	if mode == "windowed_fullscreen":
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
		return
	# "windowed" (small): un-fullscreen, size, and center on the current screen. Clamp the size
	# to the screen and the centering offset to be non-negative so a screen smaller than
	# WINDOWED_SMALL_SIZE doesn't push the window partly off-screen.
	DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_WINDOWED)
	var screen := DisplayServer.window_get_current_screen()
	var screen_pos := DisplayServer.screen_get_position(screen)
	var screen_size := DisplayServer.screen_get_size(screen)
	var window_size := screen_size.min(WINDOWED_SMALL_SIZE)
	DisplayServer.window_set_size(window_size)
	var offset := Vector2i(maxi(0, screen_size.x - window_size.x), maxi(0, screen_size.y - window_size.y)) / 2
	DisplayServer.window_set_position(screen_pos + offset)

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

	# Migrate the legacy boolean "fullscreen" key away, honoring its old VALUE: a true
	# bool maps to windowed-fullscreen, false to the small window. Only seeds window_mode
	# when it's missing/empty, then drops the old key so it can't force a mode at boot.
	if settings.has("fullscreen"):
		if not settings.has("window_mode") or str(settings.get("window_mode")) == "":
			settings["window_mode"] = "windowed_fullscreen" if bool(settings.get("fullscreen", false)) else "windowed"
		settings.erase("fullscreen")

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

## Clear player data (logout / leaving a character). Account-scoped values that outlive a
## single character — selected region, the dynamically-set region connect URL, player color,
## and account Glory — are preserved so the menu still shows them and post-logout connect URLs
## survive (Glory survives a hardcore permadeath, where the character is gone but the account
## keeps the Glory it earned).
func clear_player_data() -> void:
	player_data = {
		"character_name": "",
		"character_id": "",
		"user_id": "",
		"selected_region": player_data.get("selected_region", "Asia"),
		"selected_region_url": player_data.get("selected_region_url", ""),
		"session_id": "",
		"player_color": player_data.get("player_color", Color(0.27, 0.53, 1.0)),
		"player_class": 0,
		"player_level": 1,
		"player_experience": 0,
		"player_move_speed": 0,
		"character_mode": "softcore",
		"glory": int(player_data.get("glory", 0))
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


## Total lifetime XP a character at (level, experience) has earned: the sum of every prior
## level's cost (capped at MAX_PLAYER_LEVEL) plus the current in-level progress. Mirrors Go
## progression.TotalLifetimeXP exactly (loop lvl = 1 ..< min(level, MAX_PLAYER_LEVEL)).
func total_lifetime_xp(level: int, experience: int) -> int:
	var total := maxi(0, experience)
	var lvl := 1
	while lvl < level and lvl < MAX_PLAYER_LEVEL:
		total += xp_to_next_level(lvl)
		lvl += 1
	return total


## Glory the server credits this character on a hardcore death: floor(total lifetime XP / GLORY_XP_DIVISOR).
## Read from the current authoritative level/experience (kept in sync by PROGRESS events).
func glory_for_death() -> int:
	return total_lifetime_xp(get_player_level(), get_player_experience()) / GLORY_XP_DIVISOR


func get_player_level() -> int:
	return maxi(1, int(player_data.get("player_level", 1)))


func get_player_experience() -> int:
	return maxi(0, int(player_data.get("player_experience", 0)))


func get_player_move_speed() -> int:
	return maxi(0, int(player_data.get("player_move_speed", 0)))


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
		or scene_path == "res://scenes/levels/offline/practice.tscn"
