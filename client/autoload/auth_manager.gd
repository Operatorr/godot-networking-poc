## AuthManager - Authentication management singleton
## Handles JWT authentication with Go API server
## Manages login/register flows and authentication state
extends Node

## Authentication states
enum AuthState {
	LOGGED_OUT,
	LOGGING_IN,
	LOGGED_IN,
	REGISTERING,
	ERROR
}

## Signals
signal login_successful(user_data: Dictionary)
signal login_failed(error: String)
signal register_successful(user_data: Dictionary)
signal register_failed(error: String)
signal logout_completed()
signal token_refreshed(new_token: String)
signal auth_state_changed(new_state: AuthState)

## API server configuration
var api_base_url: String = "http://localhost:8080"  ## Default, can be overridden
var api_timeout: float = 10.0

## Authentication state
var current_state: AuthState = AuthState.LOGGED_OUT
var jwt_token: String = ""
var refresh_token: String = ""
var token_expiry: int = 0

## Runtime mode detection
var is_server: bool = false

## HTTP request node
var http_request: HTTPRequest = null

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	print("[AuthManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	# Server doesn't need HTTP client or authentication
	if is_server:
		return

	# Create HTTP request node (client only)
	http_request = HTTPRequest.new()
	add_child(http_request)
	http_request.timeout = api_timeout

	# Try to load saved token
	_load_token()

	set_process(true)

## Process loop - check for token expiry
func _process(_delta: float) -> void:
	# Server doesn't need auth processing
	if is_server:
		return

	if current_state == AuthState.LOGGED_IN:
		# Check if token is about to expire (refresh 5 minutes before)
		var current_time = Time.get_unix_time_from_system()
		if token_expiry > 0 and current_time >= (token_expiry - 300):
			print("[AuthManager] Token expiring soon, refreshing...")
			refresh_auth_token()

## Login with username and password
func login(username: String, password: String) -> void:
	if current_state == AuthState.LOGGING_IN:
		print("[AuthManager] Login already in progress")
		return

	print("[AuthManager] Attempting login for user: %s" % username)
	_change_state(AuthState.LOGGING_IN)

	var url = api_base_url + "/api/auth/login"
	var headers = ["Content-Type: application/json"]
	var body = JSON.stringify({
		"username": username,
		"password": password
	})

	# Connect to request completion
	if not http_request.request_completed.is_connected(_on_login_completed):
		http_request.request_completed.connect(_on_login_completed)

	var error = http_request.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] HTTP Request failed: %d" % error)
		_change_state(AuthState.ERROR)
		login_failed.emit("Network error: %d" % error)

## Handle login response
func _on_login_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	http_request.request_completed.disconnect(_on_login_completed)

	if result != HTTPRequest.RESULT_SUCCESS:
		print("[AuthManager] Login request failed: %d" % result)
		_change_state(AuthState.ERROR)
		login_failed.emit("Request failed: %d" % result)
		return

	if response_code != 200:
		print("[AuthManager] Login failed with status: %d" % response_code)
		_change_state(AuthState.ERROR)
		var error_message = _parse_error_response(body)
		login_failed.emit(error_message)
		return

	# Parse response
	var json_string = body.get_string_from_utf8()
	var json = JSON.new()
	var parse_error = json.parse(json_string)

	if parse_error != OK:
		print("[AuthManager] Failed to parse login response")
		_change_state(AuthState.ERROR)
		login_failed.emit("Invalid response format")
		return

	var data = json.data

	# Store tokens
	jwt_token = data.get("token", "")
	refresh_token = data.get("refresh_token", "")
	token_expiry = data.get("expiry", 0)

	# Update GameManager with user data
	var user_data = {
		"user_id": data.get("user_id", ""),
		"username": data.get("username", ""),
		"character_id": data.get("character_id", ""),
		"character_name": data.get("character_name", "")
	}

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		game_mgr.set_player_data(user_data)

	# Save token
	_save_token()

	print("[AuthManager] Login successful for user: %s" % user_data.username)
	_change_state(AuthState.LOGGED_IN)
	login_successful.emit(user_data)

## Register new account
func register(username: String, email: String, password: String) -> void:
	if current_state == AuthState.REGISTERING:
		print("[AuthManager] Registration already in progress")
		return

	print("[AuthManager] Attempting registration for user: %s" % username)
	_change_state(AuthState.REGISTERING)

	var url = api_base_url + "/api/auth/register"
	var headers = ["Content-Type: application/json"]
	var body = JSON.stringify({
		"username": username,
		"email": email,
		"password": password
	})

	# Connect to request completion
	if not http_request.request_completed.is_connected(_on_register_completed):
		http_request.request_completed.connect(_on_register_completed)

	var error = http_request.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] HTTP Request failed: %d" % error)
		_change_state(AuthState.ERROR)
		register_failed.emit("Network error: %d" % error)

## Handle registration response
func _on_register_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	http_request.request_completed.disconnect(_on_register_completed)

	if result != HTTPRequest.RESULT_SUCCESS:
		print("[AuthManager] Registration request failed: %d" % result)
		_change_state(AuthState.ERROR)
		register_failed.emit("Request failed: %d" % result)
		return

	if response_code != 201 and response_code != 200:
		print("[AuthManager] Registration failed with status: %d" % response_code)
		_change_state(AuthState.ERROR)
		var error_message = _parse_error_response(body)
		register_failed.emit(error_message)
		return

	# Parse response
	var json_string = body.get_string_from_utf8()
	var json = JSON.new()
	var parse_error = json.parse(json_string)

	if parse_error != OK:
		print("[AuthManager] Failed to parse registration response")
		_change_state(AuthState.ERROR)
		register_failed.emit("Invalid response format")
		return

	var data = json.data

	# Store tokens
	jwt_token = data.get("token", "")
	refresh_token = data.get("refresh_token", "")
	token_expiry = data.get("expiry", 0)

	# Update GameManager with user data
	var user_data = {
		"user_id": data.get("user_id", ""),
		"username": data.get("username", "")
	}

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		game_mgr.set_player_data(user_data)

	# Save token
	_save_token()

	print("[AuthManager] Registration successful for user: %s" % user_data.username)
	_change_state(AuthState.LOGGED_IN)
	register_successful.emit(user_data)

## Logout and clear tokens
func logout() -> void:
	print("[AuthManager] Logging out...")

	jwt_token = ""
	refresh_token = ""
	token_expiry = 0

	# Clear saved token
	_clear_saved_token()

	# Clear game manager data
	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		game_mgr.clear_player_data()

	_change_state(AuthState.LOGGED_OUT)
	logout_completed.emit()

	print("[AuthManager] Logout completed")

## Refresh authentication token
func refresh_auth_token() -> void:
	if refresh_token.is_empty():
		print("[AuthManager] No refresh token available")
		logout()
		return

	print("[AuthManager] Refreshing authentication token...")

	var url = api_base_url + "/api/auth/refresh"
	var headers = [
		"Content-Type: application/json",
		"Authorization: Bearer " + refresh_token
	]
	var body = JSON.stringify({"refresh_token": refresh_token})

	# Connect to request completion
	if not http_request.request_completed.is_connected(_on_refresh_completed):
		http_request.request_completed.connect(_on_refresh_completed)

	var error = http_request.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] Token refresh request failed: %d" % error)

## Handle token refresh response
func _on_refresh_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	http_request.request_completed.disconnect(_on_refresh_completed)

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		print("[AuthManager] Token refresh failed, logging out...")
		logout()
		return

	var json_string = body.get_string_from_utf8()
	var json = JSON.new()
	var parse_error = json.parse(json_string)

	if parse_error != OK:
		print("[AuthManager] Failed to parse refresh response")
		logout()
		return

	var data = json.data
	jwt_token = data.get("token", "")
	token_expiry = data.get("expiry", 0)

	_save_token()

	print("[AuthManager] Token refreshed successfully")
	token_refreshed.emit(jwt_token)

## Get authorization header
func get_auth_header() -> String:
	if jwt_token.is_empty():
		return ""
	return "Authorization: Bearer " + jwt_token

## Check if user is logged in
func is_logged_in() -> bool:
	return current_state == AuthState.LOGGED_IN and not jwt_token.is_empty()

## Get JWT token
func get_token() -> String:
	return jwt_token

## Change authentication state
func _change_state(new_state: AuthState) -> void:
	if current_state != new_state:
		current_state = new_state
		print("[AuthManager] State changed to: %s" % AuthState.keys()[new_state])
		auth_state_changed.emit(new_state)

## Parse error response
func _parse_error_response(body: PackedByteArray) -> String:
	var json_string = body.get_string_from_utf8()
	var json = JSON.new()
	var error = json.parse(json_string)

	if error == OK and json.data is Dictionary:
		return json.data.get("error", "Unknown error")

	return "Unknown error"

## Save token to file
func _save_token() -> void:
	var save_path = "user://auth_token.dat"
	var file = FileAccess.open(save_path, FileAccess.WRITE)

	if file:
		var token_data = {
			"jwt_token": jwt_token,
			"refresh_token": refresh_token,
			"token_expiry": token_expiry
		}
		var json_string = JSON.stringify(token_data)
		file.store_string(json_string)
		file.close()
		print("[AuthManager] Token saved")

## Load token from file
func _load_token() -> void:
	var save_path = "user://auth_token.dat"

	if not FileAccess.file_exists(save_path):
		return

	var file = FileAccess.open(save_path, FileAccess.READ)
	if file:
		var json_string = file.get_as_text()
		var json = JSON.new()
		var error = json.parse(json_string)

		if error == OK and json.data is Dictionary:
			var token_data = json.data
			jwt_token = token_data.get("jwt_token", "")
			refresh_token = token_data.get("refresh_token", "")
			token_expiry = token_data.get("token_expiry", 0)

			# Check if token is still valid
			var current_time = Time.get_unix_time_from_system()
			if token_expiry > current_time:
				print("[AuthManager] Loaded valid token from storage")
				_change_state(AuthState.LOGGED_IN)
			else:
				print("[AuthManager] Stored token expired")
				_clear_saved_token()

		file.close()

## Clear saved token
func _clear_saved_token() -> void:
	var save_path = "user://auth_token.dat"
	if FileAccess.file_exists(save_path):
		DirAccess.remove_absolute(save_path)
		print("[AuthManager] Saved token cleared")

## Set API base URL (for configuration)
func set_api_url(url: String) -> void:
	api_base_url = url
	print("[AuthManager] API URL set to: %s" % url)
