## ClientConfig - JSON configuration loader for game client
## Loads configuration from JSON files with fallback to defaults
class_name ClientConfig
extends RefCounted

## Default configuration values
const DEFAULTS := {
	"api_base_url": "https://omega.marrowtech.app",
	"use_local_api": false,
	"local_api_base_url": "http://localhost:8080",
	"api_timeout_seconds": 10.0,
	"debug_logging": true,
	"projectile_sync_debug_logging": true
}

## Configuration file paths (priority order)
const CONFIG_PATH_USER := "user://client_config.json"
const CONFIG_PATH_RES := "res://data/config/client_config.json"

## Loaded configuration
var _config: Dictionary = {}

## Client settings

## Resolved API base URL. Flip `use_local_api` to true in client_config.json to point the
## client at the local Go API (`local_api_base_url`) instead of `api_base_url` (production) —
## a one-line toggle for local testing, no need to edit/restore the prod URL.
var api_base_url: String:
	get:
		if use_local_api:
			return _config.get("local_api_base_url", DEFAULTS.local_api_base_url)
		return _config.get("api_base_url", DEFAULTS.api_base_url)

## Toggle: when true, api_base_url resolves to local_api_base_url.
var use_local_api: bool:
	get: return _config.get("use_local_api", DEFAULTS.use_local_api)

## The local API address used when use_local_api is true.
var local_api_base_url: String:
	get: return _config.get("local_api_base_url", DEFAULTS.local_api_base_url)

var api_timeout_seconds: float:
	get: return _config.get("api_timeout_seconds", DEFAULTS.api_timeout_seconds)

var debug_logging: bool:
	get: return _config.get("debug_logging", DEFAULTS.debug_logging)

var projectile_sync_debug_logging: bool:
	get: return _config.get("projectile_sync_debug_logging", DEFAULTS.projectile_sync_debug_logging)


## Initialize and load configuration
func _init() -> void:
	load_config()


## Load configuration from JSON file
## Priority: user:// path (for overrides) > res:// path (embedded) > defaults
func load_config() -> void:
	_config = DEFAULTS.duplicate()

	# Try user:// path first (allows runtime override)
	if FileAccess.file_exists(CONFIG_PATH_USER):
		var loaded = _load_json_file(CONFIG_PATH_USER)
		if loaded != null:
			_merge_config(loaded)
			if _config.get("debug_logging", false):
				print("[ClientConfig] Loaded config from: %s" % CONFIG_PATH_USER)
			return

	# Fall back to res:// path (embedded in export)
	if FileAccess.file_exists(CONFIG_PATH_RES):
		var loaded = _load_json_file(CONFIG_PATH_RES)
		if loaded != null:
			_merge_config(loaded)
			if _config.get("debug_logging", false):
				print("[ClientConfig] Loaded config from: %s" % CONFIG_PATH_RES)
			return

	if _config.get("debug_logging", false):
		print("[ClientConfig] No config file found, using defaults")


## Load JSON from file path
func _load_json_file(path: String) -> Variant:
	var file = FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("[ClientConfig] Failed to open: %s (Error: %d)" % [path, FileAccess.get_open_error()])
		return null

	var content = file.get_as_text()
	file.close()

	var json = JSON.new()
	var error = json.parse(content)
	if error != OK:
		push_error("[ClientConfig] JSON parse error in %s at line %d: %s" % [
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
			push_warning("[ClientConfig] Unknown config key: %s" % key)


## Get raw config dictionary
func get_config() -> Dictionary:
	return _config.duplicate()


## Print current configuration
func print_config() -> void:
	print("[ClientConfig] Current configuration:")
	print("  api_base_url: %s  (use_local_api: %s)" % [api_base_url, str(use_local_api)])
	print("  api_timeout_seconds: %.1fs" % api_timeout_seconds)
	print("  debug_logging: %s" % str(debug_logging))
	print("  projectile_sync_debug_logging: %s" % str(projectile_sync_debug_logging))
