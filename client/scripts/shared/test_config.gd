## TestConfig - Loads test configuration from .env.test file
## Used for automated testing with pre-configured credentials
class_name TestConfig
extends RefCounted

## Configuration values
var username: String = ""
var password: String = ""
var character_name: String = ""
var realm: String = "Asia"
var api_server_url: String = "http://localhost:8080"
var game_server_host: String = "localhost"
var game_server_port: int = 8081

## Whether config was loaded successfully
var is_loaded: bool = false

## Path to .env.test file (relative to project root)
const ENV_FILE_PATH := "res://../.env.test"

## Alternative paths to try
const ENV_PATHS: Array[String] = [
	"res://../.env.test",
	"user://../.env.test",
]


## Load configuration from .env.test file
func load_config() -> bool:
	# Try each path
	for path in ENV_PATHS:
		if _try_load_file(path):
			is_loaded = true
			return true

	# Try absolute path from project root
	var abs_path := _get_project_root() + "/.env.test"
	if _try_load_file(abs_path):
		is_loaded = true
		return true

	push_warning("[TestConfig] Could not find .env.test file")
	return false


func _try_load_file(path: String) -> bool:
	if not FileAccess.file_exists(path):
		return false

	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return false

	print("[TestConfig] Loading config from: %s" % path)

	while not file.eof_reached():
		var line := file.get_line().strip_edges()

		# Skip empty lines and comments
		if line.is_empty() or line.begins_with("#"):
			continue

		# Parse KEY=VALUE
		var equals_pos := line.find("=")
		if equals_pos == -1:
			continue

		var key := line.substr(0, equals_pos).strip_edges()
		var value := line.substr(equals_pos + 1).strip_edges()

		# Remove quotes if present
		if value.begins_with("\"") and value.ends_with("\""):
			value = value.substr(1, value.length() - 2)
		elif value.begins_with("'") and value.ends_with("'"):
			value = value.substr(1, value.length() - 2)

		_set_value(key, value)

	file.close()
	return true


func _set_value(key: String, value: String) -> void:
	match key:
		"TEST_USERNAME":
			username = value
		"TEST_PASSWORD":
			password = value
		"TEST_CHARACTER_NAME":
			character_name = value
		"TEST_REALM":
			realm = value
		"API_SERVER_URL":
			api_server_url = value
		"GAME_SERVER_HOST":
			game_server_host = value
		"GAME_SERVER_PORT":
			game_server_port = int(value) if value.is_valid_int() else 8081


func _get_project_root() -> String:
	# Get the executable/project path and go up from client/
	var path := OS.get_executable_path().get_base_dir()

	# If running from editor, use the project path
	if OS.has_feature("editor"):
		path = ProjectSettings.globalize_path("res://")

	# Go up one level from client/
	if path.ends_with("/client") or path.ends_with("/client/"):
		path = path.get_base_dir()

	return path


## Print loaded configuration (for debugging)
func print_config() -> void:
	print("[TestConfig] Configuration:")
	print("  Username: %s" % username)
	print("  Password: %s" % ("*" * password.length() if not password.is_empty() else "(not set)"))
	print("  Character: %s" % (character_name if not character_name.is_empty() else "(first available)"))
	print("  Realm: %s" % realm)
	print("  API URL: %s" % api_server_url)
	print("  Game Server: %s:%d" % [game_server_host, game_server_port])


## Check if required fields are set
func is_valid() -> bool:
	return not username.is_empty() and not password.is_empty()
