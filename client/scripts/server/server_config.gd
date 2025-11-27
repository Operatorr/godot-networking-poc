## ServerConfig - JSON configuration loader for dedicated server
## Loads configuration from JSON files with fallback to defaults
class_name ServerConfig
extends RefCounted

## Default configuration values
const DEFAULTS := {
	"port": 8081,
	"tick_rate": 30,
	"max_players": 100,
	"region": "asia",
	"debug_logging": true,
	"heartbeat_timeout_seconds": 5.0,
	"api_server_url": "http://localhost:8080"
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
