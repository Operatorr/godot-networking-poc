## LoginCharacterTest - Headless integration test for login character hydration
extends Node

const TestConfigScript := preload("res://scripts/shared/test_config.gd")
const TIMEOUT_SECONDS := 15.0

var config: TestConfigScript = null
var is_finished: bool = false


func _ready() -> void:
	await get_tree().process_frame
	await get_tree().process_frame

	_start()


func _start() -> void:
	config = TestConfigScript.new()
	if not config.load_config():
		_fail("Failed to load .env.test")
		return

	if not config.is_valid():
		_fail("Invalid .env.test: missing TEST_USERNAME or TEST_PASSWORD")
		return

	if AuthManager.login_successful.is_connected(_on_login_successful):
		AuthManager.login_successful.disconnect(_on_login_successful)
	if AuthManager.login_failed.is_connected(_on_login_failed):
		AuthManager.login_failed.disconnect(_on_login_failed)

	AuthManager.login_successful.connect(_on_login_successful)
	AuthManager.login_failed.connect(_on_login_failed)

	get_tree().create_timer(TIMEOUT_SECONDS).timeout.connect(_on_timeout)

	AuthManager.logout()
	AuthManager.set_api_url(config.api_server_url)
	print("[LoginCharacterTest] Logging in as %s" % config.username)
	AuthManager.login(config.username, config.password)


func _on_login_successful(user_data: Dictionary) -> void:
	var username: String = str(user_data.get("username", ""))
	if username != config.username:
		_fail("Expected username '%s', got '%s'" % [config.username, username])
		return

	var character_id: String = str(user_data.get("character_id", ""))
	if character_id.is_empty():
		_fail("Login response did not include character_id")
		return

	var character_name: String = str(user_data.get("character_name", ""))
	if character_name.is_empty():
		_fail("Login response did not include character_name")
		return

	if not config.character_name.is_empty() and character_name != config.character_name:
		_fail("Expected character '%s', got '%s'" % [config.character_name, character_name])
		return

	if not GameManager.has_character():
		_fail("GameManager.has_character() was false after login")
		return

	_finish_success("Login loaded character '%s' (%s)" % [character_name, character_id])


func _on_login_failed(error: String) -> void:
	_fail("Login failed: %s" % error)


func _on_timeout() -> void:
	if not is_finished:
		_fail("Timed out waiting for login")


func _finish_success(message: String) -> void:
	is_finished = true
	print("[LoginCharacterTest] PASS: %s" % message)
	_disconnect_signals()
	get_tree().quit(0)


func _fail(message: String) -> void:
	is_finished = true
	push_error("[LoginCharacterTest] FAIL: %s" % message)
	_disconnect_signals()
	get_tree().quit(1)


func _disconnect_signals() -> void:
	if AuthManager.login_successful.is_connected(_on_login_successful):
		AuthManager.login_successful.disconnect(_on_login_successful)
	if AuthManager.login_failed.is_connected(_on_login_failed):
		AuthManager.login_failed.disconnect(_on_login_failed)
