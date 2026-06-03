## ServerConfig - JSON configuration loader for dedicated server
## Loads configuration from JSON files with fallback to defaults
class_name ServerConfig
extends RefCounted

## Default configuration values
const DEFAULTS := {
	"port": 8081,
	"tick_rate": 30,
	"max_players": 100,
	"region": "local",
	"debug_logging": true,
	"heartbeat_timeout_seconds": 5.0,
	"api_server_url": "http://localhost:8080",
	"aoi_radius": 1000.0,
	## AoI hysteresis: once an entity is visible it stays visible until the
	## viewer is more than aoi_exit_radius away. Avoids edge flicker where an
	## entity oscillating across the AoI boundary causes spawn/despawn churn.
	"aoi_exit_radius": 1100.0,
	## LOD radii (squared distance bands within AoI). Position-only deltas for
	## entities in the MID/FAR bands feed the scheduler's distance penalty (§1.2).
	"lod_near_radius": 400.0,
	"lod_mid_radius": 700.0,
	## Per-tick packet batching - merge multiple packets into one WebSocket frame.
	"packet_batching_enabled": true,
	## Snapshot rate (Hz). Decoupled from tick_rate so physics can run faster
	## than the snapshot stream sent to clients. Defaults to tick_rate when
	## set to 0 - no behavior change vs. pre-decouple.
	"snapshot_rate_hz": 0,
	## Per-peer per-snapshot byte budget for the priority scheduler (§1.2).
	## ~1200 fits a typical MTU-aligned WebSocket payload after framing overhead.
	## 0 disables the budget (scheduler still sorts but never defers).
	"max_snapshot_bytes": 1200,
	## Difficulty of server-side monster tactical behavior, clamped 0.0..1.0.
	"monster_ai_difficulty": 0.85
}

## Configuration file paths (priority order)
const CONFIG_PATH_USER := "user://server_config.json"
const CONFIG_PATH_RES := "res://data/config/server_config.json"

## Loaded configuration
var _config: Dictionary = {}

## Server settings
var port: int:
	get: return _config.get("port", DEFAULTS.port)

var tick_rate: int:
	get: return _config.get("tick_rate", DEFAULTS.tick_rate)

var max_players: int:
	get: return _config.get("max_players", DEFAULTS.max_players)

var region: String:
	get: return _config.get("region", DEFAULTS.region)

var debug_logging: bool:
	get: return _config.get("debug_logging", DEFAULTS.debug_logging)

var heartbeat_timeout_seconds: float:
	get: return _config.get("heartbeat_timeout_seconds", DEFAULTS.heartbeat_timeout_seconds)

var api_server_url: String:
	get: return _config.get("api_server_url", DEFAULTS.api_server_url)

var aoi_radius: float:
	get: return _config.get("aoi_radius", DEFAULTS.aoi_radius)

var aoi_exit_radius: float:
	get: return _config.get("aoi_exit_radius", DEFAULTS.aoi_exit_radius)

var lod_near_radius: float:
	get: return _config.get("lod_near_radius", DEFAULTS.lod_near_radius)

var lod_mid_radius: float:
	get: return _config.get("lod_mid_radius", DEFAULTS.lod_mid_radius)

var packet_batching_enabled: bool:
	get: return _config.get("packet_batching_enabled", DEFAULTS.packet_batching_enabled)

var monster_ai_difficulty: float:
	get: return clampf(_config.get("monster_ai_difficulty", DEFAULTS.monster_ai_difficulty), 0.0, 1.0)

## Effective snapshot rate, falling back to tick_rate when not configured. The
## snapshot loop never fires faster than the physics tick, so this value is
## clamped to (0, tick_rate].
var snapshot_rate_hz: int:
	get:
		var raw: int = _config.get("snapshot_rate_hz", DEFAULTS.snapshot_rate_hz)
		if raw <= 0:
			return tick_rate
		return mini(raw, tick_rate)

var max_snapshot_bytes: int:
	get: return maxi(0, _config.get("max_snapshot_bytes", DEFAULTS.max_snapshot_bytes))


## Initialize and load configuration
func _init() -> void:
	load_config()


## Load configuration from JSON file
## Priority: user:// path (for Docker mounts) > res:// path (embedded) > defaults
func load_config() -> void:
	_config = DEFAULTS.duplicate()

	# Try user:// path first (allows runtime override via Docker volumes)
	if FileAccess.file_exists(CONFIG_PATH_USER):
		var loaded = _load_json_file(CONFIG_PATH_USER)
		if loaded != null:
			_merge_config(loaded)
			print("[ServerConfig] Loaded config from: %s" % CONFIG_PATH_USER)
			return

	# Fall back to res:// path (embedded in export)
	if FileAccess.file_exists(CONFIG_PATH_RES):
		var loaded = _load_json_file(CONFIG_PATH_RES)
		if loaded != null:
			_merge_config(loaded)
			print("[ServerConfig] Loaded config from: %s" % CONFIG_PATH_RES)
			return

	print("[ServerConfig] No config file found, using defaults")


## Load JSON from file path
func _load_json_file(path: String) -> Variant:
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("[ServerConfig] Failed to open: %s (Error: %d)" % [path, FileAccess.get_open_error()])
		return null

	var content = file.get_as_text()
	file.close()

	var json = JSON.new()
	var error = json.parse(content)
	if error != OK:
		push_error("[ServerConfig] JSON parse error in %s at line %d: %s" % [
			path, json.get_error_line(), json.get_error_message()
		])
		return null

	return json.data


## Merge loaded config into current config (preserves defaults for missing keys)
func _merge_config(loaded: Dictionary) -> void:
	for key in loaded.keys():
		if DEFAULTS.has(key):
			_config[key] = loaded[key]
		else:
			push_warning("[ServerConfig] Unknown config key: %s" % key)


## Get raw config dictionary
func get_config() -> Dictionary:
	return _config.duplicate()


## Print current configuration
func print_config() -> void:
	print("[ServerConfig] Current configuration:")
	print("  port: %d" % port)
	print("  tick_rate: %d Hz" % tick_rate)
	print("  max_players: %d" % max_players)
	print("  region: %s" % region)
	print("  debug_logging: %s" % str(debug_logging))
	print("  heartbeat_timeout: %.1fs" % heartbeat_timeout_seconds)
	print("  api_server_url: %s" % api_server_url)
	print("  aoi_radius: %.1f (exit %.1f)" % [aoi_radius, aoi_exit_radius])
	print("  lod_radii: near=%.1f mid=%.1f" % [lod_near_radius, lod_mid_radius])
	print("  packet_batching: %s" % str(packet_batching_enabled))
	print("  snapshot_rate: %d Hz" % snapshot_rate_hz)
	print("  max_snapshot_bytes: %d" % max_snapshot_bytes)
	print("  monster_ai_difficulty: %.2f" % monster_ai_difficulty)
