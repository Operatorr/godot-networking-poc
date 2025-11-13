## AudioManager - Global audio system singleton
## Manages background music, sound effects, and audio settings
## Handles all audio playback throughout the game
extends Node

## Audio bus names
const MASTER_BUS = "Master"
const MUSIC_BUS = "Music"
const SFX_BUS = "SFX"

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

## Audio players
var music_player: AudioStreamPlayer = null
var ui_sfx_players: Array[AudioStreamPlayer] = []
var combat_sfx_players: Array[AudioStreamPlayer] = []

## Current music state
var current_music_track: String = ""
var music_fade_duration: float = 1.0
var is_music_fading: bool = false

## Audio player pool settings
const UI_SFX_POOL_SIZE: int = 8
const COMBAT_SFX_POOL_SIZE: int = 16

## Audio library (will be populated as assets are added)
var audio_library: Dictionary = {
	"music": {
		# "menu_bgm": preload("res://assets/audio/music/menu_bgm.ogg"),
		# "arena_ambience": preload("res://assets/audio/ambience/arena_ambience.ogg")
	},
	"sfx_ui": {
		# "button_hover": preload("res://assets/audio/sfx/button_hover.ogg"),
		# "button_click": preload("res://assets/audio/sfx/button_click.ogg")
	},
	"sfx_player": {
		# "player_shoot": preload("res://assets/audio/sfx/player_shoot.ogg"),
		# "player_hit": preload("res://assets/audio/sfx/player_hit.ogg"),
		# "player_death": preload("res://assets/audio/sfx/player_death.ogg")
	},
	"sfx_monster": {
		# "monster_shoot": preload("res://assets/audio/sfx/monster_shoot.ogg"),
		# "monster_hit": preload("res://assets/audio/sfx/monster_hit.ogg"),
		# "monster_death": preload("res://assets/audio/sfx/monster_death.ogg")
	}
}

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	print("[AudioManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	# Server doesn't need audio
	if is_server:
		print("[AudioManager] Audio disabled in server mode")
		return

	# Create music player (client only)
	music_player = AudioStreamPlayer.new()
	music_player.bus = MUSIC_BUS
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

	# Setup audio buses if they don't exist
	_setup_audio_buses()

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
		AudioServer.set_bus_send(AudioServer.get_bus_index(MUSIC_BUS), MASTER_BUS)

	if not has_sfx_bus:
		AudioServer.add_bus()
		AudioServer.set_bus_name(AudioServer.bus_count - 1, SFX_BUS)
		AudioServer.set_bus_send(AudioServer.get_bus_index(SFX_BUS), MASTER_BUS)

	print("[AudioManager] Audio buses configured")

## Play music track
func play_music(track_name: String, fade_in: bool = true) -> void:
	if current_music_track == track_name and music_player.playing:
		print("[AudioManager] Music track '%s' already playing" % track_name)
		return

	# Check if track exists in library
	if not audio_library.music.has(track_name):
		print("[AudioManager] Music track '%s' not found in library" % track_name)
		return

	var track = audio_library.music[track_name]

	if fade_in and music_player.playing:
		# Fade out current track, then fade in new track
		_fade_out_music(0.5)
		await get_tree().create_timer(0.5).timeout

	music_player.stream = track
	music_player.play()

	if fade_in:
		_fade_in_music(music_fade_duration)

	current_music_track = track_name
	print("[AudioManager] Playing music: %s" % track_name)
	music_changed.emit(track_name)

## Stop music
func stop_music(fade_out: bool = true) -> void:
	if not music_player.playing:
		return

	if fade_out:
		_fade_out_music(music_fade_duration)
		await get_tree().create_timer(music_fade_duration).timeout

	music_player.stop()
	current_music_track = ""
	print("[AudioManager] Music stopped")

## Fade in music
func _fade_in_music(duration: float) -> void:
	if is_music_fading:
		return

	is_music_fading = true
	var music_bus_idx = AudioServer.get_bus_index(MUSIC_BUS)
	var target_volume = AudioServer.get_bus_volume_db(music_bus_idx)

	# Start from silence
	AudioServer.set_bus_volume_db(music_bus_idx, -80.0)

	# Tween to target volume
	var tween = create_tween()
	tween.tween_method(
		func(vol): AudioServer.set_bus_volume_db(music_bus_idx, vol),
		-80.0,
		target_volume,
		duration
	)
	tween.finished.connect(func(): is_music_fading = false)

## Fade out music
func _fade_out_music(duration: float) -> void:
	if is_music_fading:
		return

	is_music_fading = true
	var music_bus_idx = AudioServer.get_bus_index(MUSIC_BUS)
	var current_volume = AudioServer.get_bus_volume_db(music_bus_idx)

	# Tween to silence
	var tween = create_tween()
	tween.tween_method(
		func(vol): AudioServer.set_bus_volume_db(music_bus_idx, vol),
		current_volume,
		-80.0,
		duration
	)
	tween.finished.connect(func(): is_music_fading = false)

## Play sound effect
func play_sfx(sfx_name: String, category: AudioCategory = AudioCategory.SFX_UI) -> void:
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

## Play monster shoot sound
func play_monster_shoot() -> void:
	play_sfx("monster_shoot", AudioCategory.SFX_MONSTER)

## Play monster hit sound
func play_monster_hit() -> void:
	play_sfx("monster_hit", AudioCategory.SFX_MONSTER)

## Play monster death sound
func play_monster_death() -> void:
	play_sfx("monster_death", AudioCategory.SFX_MONSTER)

## Set master volume (0.0 to 1.0)
func set_master_volume(volume: float) -> void:
	_set_bus_volume(MASTER_BUS, volume)

## Set music volume (0.0 to 1.0)
func set_music_volume(volume: float) -> void:
	_set_bus_volume(MUSIC_BUS, volume)

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
	return music_player.playing

## Get current music track
func get_current_music() -> String:
	return current_music_track
