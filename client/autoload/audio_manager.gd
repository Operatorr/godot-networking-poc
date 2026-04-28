## AudioManager - Global audio system singleton
## Manages background music, sound effects, and audio settings
## Handles all audio playback throughout the game
extends Node

## Audio bus names
const MASTER_BUS = "Master"
const MUSIC_BUS = "Music"
const SFX_BUS = "SFX"
const MAIN_MENU_MUSIC := preload("res://assets/audio/music/main_menu.wav")
const ARENA_GAMEPLAY_MUSIC := preload("res://assets/audio/music/arena_gameplay.wav")
const MUSIC_FADE_SILENCE_DB = -40.0

## Audio categories
enum AudioCategory {
	MUSIC,
	SFX_UI,
	SFX_PLAYER,
	SFX_MONSTER,
	SFX_COMBAT
}

## Signals
signal music_changed(track_name: String)
signal volume_changed(bus_name: String, volume: float)

## Runtime mode detection
var is_server: bool = false

## Per-track music volume multipliers
@export_group("Music Track Volumes")
@export_range(0.0, 2.0, 0.01, "or_greater")
var menu_bgm_volume: float = 0.2
@export_range(0.0, 2.0, 0.01, "or_greater")
var arena_bgm_volume: float = 0.2

## Audio players
var music_player: AudioStreamPlayer = null
var ui_sfx_players: Array[AudioStreamPlayer] = []
var combat_sfx_players: Array[AudioStreamPlayer] = []

## Current music state
var current_music_track: String = ""
var music_volume: float = 0.8
var music_fade_duration: float = 1.0
var is_music_fading: bool = false
var _music_fade_tween: Tween = null

## Audio player pool settings
const UI_SFX_POOL_SIZE: int = 8
const COMBAT_SFX_POOL_SIZE: int = 16

## Audio library - populated with procedurally generated sounds at runtime
var audio_library: Dictionary = {
	"music": {},
	"sfx_ui": {},
	"sfx_player": {},
	"sfx_monster": {}
}

## Footstep alternation tracking
var _footstep_alt: bool = false

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	print("[AudioManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	# Server doesn't need audio
	if is_server:
		print("[AudioManager] Audio disabled in server mode")
		return

	# Setup audio buses before assigning players to them.
	_setup_audio_buses()

	# Create music player (client only)
	music_player = AudioStreamPlayer.new()
	music_player.bus = MASTER_BUS
	add_child(music_player)

	# Create UI SFX player pool
	for i in range(UI_SFX_POOL_SIZE):
		var player = AudioStreamPlayer.new()
		player.bus = SFX_BUS
		add_child(player)
		ui_sfx_players.append(player)

	# Create combat SFX player pool
	for i in range(COMBAT_SFX_POOL_SIZE):
		var player = AudioStreamPlayer.new()
		player.bus = SFX_BUS
		add_child(player)
		combat_sfx_players.append(player)

	# Generate all sounds procedurally
	_generate_procedural_audio()

	# Connect to GameManager settings
	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		if not game_mgr.settings_changed.is_connected(_on_settings_changed):
			game_mgr.settings_changed.connect(_on_settings_changed)
		_apply_volume_settings()

	print("[AudioManager] Initialized with %d UI players and %d combat players" % [
		UI_SFX_POOL_SIZE,
		COMBAT_SFX_POOL_SIZE
	])

## Setup audio buses
func _setup_audio_buses() -> void:
	var bus_count = AudioServer.bus_count

	# Check if buses exist, if not create them
	var has_music_bus = false
	var has_sfx_bus = false

	for i in range(bus_count):
		var bus_name = AudioServer.get_bus_name(i)
		if bus_name == MUSIC_BUS:
			has_music_bus = true
		elif bus_name == SFX_BUS:
			has_sfx_bus = true

	# Create missing buses
	if not has_music_bus:
		AudioServer.add_bus()
		AudioServer.set_bus_name(AudioServer.bus_count - 1, MUSIC_BUS)

	if not has_sfx_bus:
		AudioServer.add_bus()
		AudioServer.set_bus_name(AudioServer.bus_count - 1, SFX_BUS)

	var music_bus_idx := AudioServer.get_bus_index(MUSIC_BUS)
	if music_bus_idx != -1:
		AudioServer.set_bus_send(music_bus_idx, MASTER_BUS)
		AudioServer.set_bus_mute(music_bus_idx, false)

	var sfx_bus_idx := AudioServer.get_bus_index(SFX_BUS)
	if sfx_bus_idx != -1:
		AudioServer.set_bus_send(sfx_bus_idx, MASTER_BUS)
		AudioServer.set_bus_mute(sfx_bus_idx, false)

	print("[AudioManager] Audio buses configured")


## Generate all sounds procedurally using ProceduralAudio
func _generate_procedural_audio() -> void:
	print("[AudioManager] Generating procedural audio...")

	# Generate SFX
	var sfx := ProceduralAudio.generate_all_sounds()
	audio_library["sfx_ui"]["button_hover"] = sfx["button_hover"]
	audio_library["sfx_ui"]["button_click"] = sfx["button_click"]
	audio_library["sfx_player"]["player_shoot"] = sfx["player_shoot"]
	audio_library["sfx_player"]["player_hit"] = sfx["player_hit"]
	audio_library["sfx_player"]["player_death"] = sfx["player_death"]
	audio_library["sfx_player"]["player_kill"] = sfx["player_kill"]
	audio_library["sfx_player"]["projectile_impact"] = sfx["projectile_impact"]
	audio_library["sfx_player"]["footstep_l"] = sfx["footstep_l"]
	audio_library["sfx_player"]["footstep_r"] = sfx["footstep_r"]
	audio_library["sfx_monster"]["monster_shoot"] = sfx["monster_shoot"]
	audio_library["sfx_monster"]["monster_hit"] = sfx["monster_hit"]
	audio_library["sfx_monster"]["monster_death"] = sfx["monster_death"]
	audio_library["sfx_monster"]["monster_spawn"] = sfx["monster_spawn"]

	# Generate music
	var music := ProceduralAudio.generate_music()
	var menu_music: AudioStream = MAIN_MENU_MUSIC
	var arena_music: AudioStream = ARENA_GAMEPLAY_MUSIC
	if menu_music is AudioStreamWAV:
		menu_music.loop_mode = AudioStreamWAV.LOOP_FORWARD
	if arena_music is AudioStreamWAV:
		arena_music.loop_mode = AudioStreamWAV.LOOP_FORWARD

	audio_library["music"]["menu_bgm"] = menu_music
	audio_library["music"]["arena_ambience"] = arena_music

	print("[AudioManager] Procedural audio generation complete (%d SFX, %d music)" % [sfx.size(), music.size()])


## Play music track
func play_music(track_name: String, fade_in: bool = true) -> void:
	if is_server or music_player == null:
		return

	# Check if track exists in library
	if not audio_library.music.has(track_name):
		print("[AudioManager] Music track '%s' not found in library" % track_name)
		return

	var track = audio_library.music[track_name]
	var target_volume_db := _get_music_track_volume_db(track_name)

	if current_music_track == track_name and music_player.playing:
		_stop_music_fade()
		music_player.volume_db = target_volume_db
		print("[AudioManager] Music track '%s' already playing" % track_name)
		return

	if fade_in and music_player.playing:
		# Fade out current track, then fade in new track
		_fade_out_music(0.5)
		await get_tree().create_timer(0.5).timeout

	music_player.stream = track
	music_player.volume_db = target_volume_db
	music_player.play()

	current_music_track = track_name
	print("[AudioManager] Playing music: %s" % track_name)
	music_changed.emit(track_name)

## Stop music
func stop_music(fade_out: bool = true) -> void:
	if is_server or music_player == null:
		return

	if not music_player.playing:
		return

	if fade_out:
		_fade_out_music(music_fade_duration)
		await get_tree().create_timer(music_fade_duration).timeout

	music_player.stop()
	current_music_track = ""
	print("[AudioManager] Music stopped")

## Fade out music
func _fade_out_music(duration: float) -> void:
	_stop_music_fade()

	is_music_fading = true

	# Tween to silence
	_music_fade_tween = create_tween()
	_music_fade_tween.tween_property(music_player, "volume_db", MUSIC_FADE_SILENCE_DB, duration)
	_music_fade_tween.finished.connect(func():
		is_music_fading = false
		_music_fade_tween = null
	)

func _stop_music_fade() -> void:
	if _music_fade_tween != null:
		_music_fade_tween.kill()
		_music_fade_tween = null

	is_music_fading = false

func _get_music_track_volume_db(track_name: String) -> float:
	var track_volume := music_volume

	match track_name:
		"menu_bgm":
			track_volume *= menu_bgm_volume
		"arena_ambience":
			track_volume *= arena_bgm_volume

	return linear_to_db(track_volume) if track_volume > 0.0 else -80.0

## Play sound effect
func play_sfx(sfx_name: String, category: AudioCategory = AudioCategory.SFX_UI) -> void:
	if is_server:
		return

	var category_name = ""
	var player_pool: Array[AudioStreamPlayer] = []

	# Determine category and player pool
	match category:
		AudioCategory.SFX_UI:
			category_name = "sfx_ui"
			player_pool = ui_sfx_players
		AudioCategory.SFX_PLAYER:
			category_name = "sfx_player"
			player_pool = combat_sfx_players
		AudioCategory.SFX_MONSTER:
			category_name = "sfx_monster"
			player_pool = combat_sfx_players
		AudioCategory.SFX_COMBAT:
			category_name = "sfx_player"  # Fallback
			player_pool = combat_sfx_players

	# Check if sound exists
	if not audio_library.has(category_name) or not audio_library[category_name].has(sfx_name):
		print("[AudioManager] SFX '%s' not found in category '%s'" % [sfx_name, category_name])
		return

	var sfx = audio_library[category_name][sfx_name]

	# Find available player
	var player = _get_available_player(player_pool)
	if player == null:
		print("[AudioManager] No available player for SFX: %s" % sfx_name)
		return

	player.stream = sfx
	player.play()

## Get available audio player from pool
func _get_available_player(pool: Array[AudioStreamPlayer]) -> AudioStreamPlayer:
	# Try to find non-playing player
	for player in pool:
		if not player.playing:
			return player

	# All players busy, return first one (will interrupt)
	return pool[0] if pool.size() > 0 else null

## Play UI button hover sound
func play_button_hover() -> void:
	play_sfx("button_hover", AudioCategory.SFX_UI)

## Play UI button click sound
func play_button_click() -> void:
	play_sfx("button_click", AudioCategory.SFX_UI)

## Play player shoot sound
func play_player_shoot() -> void:
	play_sfx("player_shoot", AudioCategory.SFX_PLAYER)

## Play player hit sound
func play_player_hit() -> void:
	play_sfx("player_hit", AudioCategory.SFX_PLAYER)

## Play player death sound
func play_player_death() -> void:
	play_sfx("player_death", AudioCategory.SFX_PLAYER)

## Play player kill confirmation sound
func play_player_kill() -> void:
	play_sfx("player_kill", AudioCategory.SFX_PLAYER)

## Play monster shoot sound
func play_monster_shoot() -> void:
	play_sfx("monster_shoot", AudioCategory.SFX_MONSTER)

## Play monster hit sound
func play_monster_hit() -> void:
	play_sfx("monster_hit", AudioCategory.SFX_MONSTER)

## Play monster spawn sound
func play_monster_spawn() -> void:
	play_sfx("monster_spawn", AudioCategory.SFX_MONSTER)

## Play monster death sound
func play_monster_death() -> void:
	play_sfx("monster_death", AudioCategory.SFX_MONSTER)

## Play projectile impact sound
func play_projectile_impact() -> void:
	play_sfx("projectile_impact", AudioCategory.SFX_COMBAT)

## Play footstep sound (alternates L/R)
func play_footstep() -> void:
	var step_name := "footstep_l" if not _footstep_alt else "footstep_r"
	_footstep_alt = not _footstep_alt
	play_sfx(step_name, AudioCategory.SFX_PLAYER)

## Play a sound by name with optional volume override
## Automatically selects the correct category based on sound_name prefix
func play_sound(sound_name: String, volume_db: float = 0.0) -> void:
	var category := AudioCategory.SFX_UI
	if sound_name.begins_with("player_"):
		category = AudioCategory.SFX_PLAYER
	elif sound_name.begins_with("monster_"):
		category = AudioCategory.SFX_MONSTER
	elif sound_name.begins_with("projectile_"):
		category = AudioCategory.SFX_COMBAT

	var category_name := ""
	var player_pool: Array[AudioStreamPlayer] = []

	match category:
		AudioCategory.SFX_UI:
			category_name = "sfx_ui"
			player_pool = ui_sfx_players
		AudioCategory.SFX_PLAYER:
			category_name = "sfx_player"
			player_pool = combat_sfx_players
		AudioCategory.SFX_MONSTER:
			category_name = "sfx_monster"
			player_pool = combat_sfx_players
		AudioCategory.SFX_COMBAT:
			category_name = "sfx_player"
			player_pool = combat_sfx_players

	if not audio_library.has(category_name) or not audio_library[category_name].has(sound_name):
		return

	var sfx = audio_library[category_name][sound_name]
	var player = _get_available_player(player_pool)
	if player == null:
		return

	player.stream = sfx
	player.volume_db = volume_db
	player.play()

## Set master volume (0.0 to 1.0)
func set_master_volume(volume: float) -> void:
	_set_bus_volume(MASTER_BUS, volume)

## Set music volume (0.0 to 1.0)
func set_music_volume(volume: float) -> void:
	music_volume = clamp(volume, 0.0, 1.0)

	if music_player != null and music_player.playing and not is_music_fading:
		music_player.volume_db = _get_music_track_volume_db(current_music_track)

	print("[AudioManager] Set %s volume to %.2f" % [MUSIC_BUS, music_volume])
	volume_changed.emit(MUSIC_BUS, music_volume)

## Set SFX volume (0.0 to 1.0)
func set_sfx_volume(volume: float) -> void:
	_set_bus_volume(SFX_BUS, volume)

## Set bus volume
func _set_bus_volume(bus_name: String, volume: float) -> void:
	volume = clamp(volume, 0.0, 1.0)
	var bus_idx = AudioServer.get_bus_index(bus_name)

	if bus_idx == -1:
		print("[AudioManager] Bus '%s' not found" % bus_name)
		return

	# Convert linear volume (0.0-1.0) to dB (-80 to 0)
	var volume_db = linear_to_db(volume) if volume > 0.0 else -80.0
	AudioServer.set_bus_volume_db(bus_idx, volume_db)

	print("[AudioManager] Set %s volume to %.2f (%.1f dB)" % [bus_name, volume, volume_db])
	volume_changed.emit(bus_name, volume)

## Get bus volume (0.0 to 1.0)
func get_bus_volume(bus_name: String) -> float:
	if bus_name == MUSIC_BUS:
		return music_volume

	var bus_idx = AudioServer.get_bus_index(bus_name)
	if bus_idx == -1:
		return 0.0

	var volume_db = AudioServer.get_bus_volume_db(bus_idx)
	return db_to_linear(volume_db)

## Apply volume settings from GameManager
func _apply_volume_settings() -> void:
	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if not game_mgr:
		return

	set_master_volume(game_mgr.settings.get("master_volume", 1.0))
	set_music_volume(game_mgr.settings.get("music_volume", 0.8))
	set_sfx_volume(game_mgr.settings.get("sfx_volume", 1.0))

## Handle settings changed
func _on_settings_changed() -> void:
	_apply_volume_settings()

## Register audio asset (for runtime loading)
func register_audio(category: String, audio_name: String, stream: AudioStream) -> void:
	if not audio_library.has(category):
		audio_library[category] = {}

	audio_library[category][audio_name] = stream
	print("[AudioManager] Registered audio: %s/%s" % [category, audio_name])

## Check if music is playing
func is_music_playing() -> bool:
	if is_server or music_player == null:
		return false

	return music_player.playing

## Get current music track
func get_current_music() -> String:
	return current_music_track
