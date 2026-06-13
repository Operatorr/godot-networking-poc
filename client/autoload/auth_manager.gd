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

## API server configuration (loaded from client_config.json)
var api_base_url: String = "http://localhost:8080"
var api_timeout: float = 10.0

## Client configuration
var _client_config: ClientConfig = null

## Authentication state
var current_state: AuthState = AuthState.LOGGED_OUT
var jwt_token: String = ""
var refresh_token: String = ""
var token_expiry: int = 0

## Runtime mode detection
var is_server: bool = false

## Called when the node enters the scene tree
func _ready() -> void:
	# Detect if running as dedicated server
	is_server = (OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless") and not _is_test_scene()

	print("[AuthManager] Initializing in %s mode..." % ("SERVER" if is_server else "CLIENT"))

	# Server doesn't need HTTP client or authentication
	if is_server:
		return

	# Load client configuration
	_client_config = ClientConfig.new()
	api_base_url = _client_config.api_base_url
	api_timeout = _client_config.api_timeout_seconds

	if _client_config.debug_logging:
		_client_config.print_config()

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

## Create a dedicated HTTPRequest for a single API call.
## Each request gets its own node so overlapping calls cannot interfere.
func _create_http_request() -> HTTPRequest:
	var req := HTTPRequest.new()
	add_child(req)
	req.timeout = api_timeout
	return req

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

	var req := _create_http_request()
	req.request_completed.connect(_on_login_completed.bind(req), CONNECT_ONE_SHOT)

	var error = req.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] HTTP Request failed: %d" % error)
		_change_state(AuthState.ERROR)
		login_failed.emit(_format_request_start_error("login", error))
		req.queue_free()

## Handle login response
func _on_login_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, req: HTTPRequest) -> void:
	req.queue_free()

	if result != HTTPRequest.RESULT_SUCCESS:
		print("[AuthManager] Login request failed: %d" % result)
		_change_state(AuthState.ERROR)
		login_failed.emit(_format_request_result_error("login", result))
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

	var data: Dictionary = json.data

	# Store tokens
	jwt_token = _variant_to_string(data.get("access_token", data.get("token", "")))
	refresh_token = _variant_to_string(data.get("refresh_token", ""))
	token_expiry = int(data.get("expiry", 0))

	# Update GameManager with user data
	var user_data: Dictionary = _extract_user_data(data)
	var character: Dictionary = _extract_character_data(data)
	if not character.is_empty():
		_merge_character_data(user_data, character)
		_complete_login(user_data)
	else:
		_fetch_character_after_login(user_data)

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

	var req := _create_http_request()
	req.request_completed.connect(_on_register_completed.bind(req), CONNECT_ONE_SHOT)

	var error = req.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] HTTP Request failed: %d" % error)
		_change_state(AuthState.ERROR)
		register_failed.emit(_format_request_start_error("registration", error))
		req.queue_free()

## Handle registration response
func _on_register_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, req: HTTPRequest) -> void:
	req.queue_free()

	if result != HTTPRequest.RESULT_SUCCESS:
		print("[AuthManager] Registration request failed: %d" % result)
		_change_state(AuthState.ERROR)
		register_failed.emit(_format_request_result_error("registration", result))
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

	var data: Dictionary = json.data

	# Store tokens
	jwt_token = _variant_to_string(data.get("access_token", data.get("token", "")))
	refresh_token = _variant_to_string(data.get("refresh_token", ""))
	token_expiry = int(data.get("expiry", 0))

	# Update GameManager with user data
	var user_data: Dictionary = _extract_user_data(data)

	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		game_mgr.set_player_data(user_data)

	# Save token
	_save_token()

	print("[AuthManager] Registration successful for user: %s" % user_data.get("username", "unknown"))
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

	var req := _create_http_request()
	req.request_completed.connect(_on_refresh_completed.bind(req), CONNECT_ONE_SHOT)

	var error = req.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[AuthManager] Token refresh request failed: %d" % error)
		req.queue_free()

## Handle token refresh response
func _on_refresh_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, req: HTTPRequest) -> void:
	req.queue_free()

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

	var data: Dictionary = json.data
	jwt_token = _variant_to_string(data.get("access_token", data.get("token", "")))
	token_expiry = int(data.get("expiry", 0))

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


func _format_request_start_error(action: String, error: int) -> String:
	return "Could not start the %s request. Error code: %d" % [action, error]


func _format_request_result_error(action: String, result: int) -> String:
	match result:
		HTTPRequest.RESULT_CANT_CONNECT, HTTPRequest.RESULT_CONNECTION_ERROR, HTTPRequest.RESULT_NO_RESPONSE:
			return "Cannot reach the API server at %s. Make sure the API server is running, then try again." % api_base_url
		HTTPRequest.RESULT_CANT_RESOLVE:
			return "Cannot find the API server at %s. Check the server address and your network connection." % api_base_url
		HTTPRequest.RESULT_TIMEOUT:
			return "The API server at %s did not respond in time. Make sure it is running, then try again." % api_base_url
		HTTPRequest.RESULT_TLS_HANDSHAKE_ERROR:
			return "Could not establish a secure connection to the API server."
		_:
			return "%s request failed. Error code: %d" % [action.capitalize(), result]

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


func _extract_user_data(data: Dictionary) -> Dictionary:
	var user: Dictionary = {}
	var user_value: Variant = data.get("user", {})
	if user_value is Dictionary:
		user = user_value

	return {
		"user_id": _variant_to_string(data.get("user_id", user.get("id", ""))),
		"username": _variant_to_string(data.get("username", user.get("username", ""))),
		"character_id": _variant_to_string(data.get("character_id", "")),
		"character_name": _variant_to_string(data.get("character_name", ""))
	}


func _extract_character_data(data: Dictionary) -> Dictionary:
	var character_value: Variant = data.get("character", {})
	if character_value is Dictionary:
		return character_value
	return {}


func _merge_character_data(user_data: Dictionary, character: Dictionary) -> void:
	var character_id: String = _variant_to_string(character.get("id", character.get("character_id", "")))
	var character_name: String = _variant_to_string(character.get("name", character.get("character_name", "")))

	if not character_id.is_empty():
		user_data["character_id"] = character_id
	if not character_name.is_empty():
		user_data["character_name"] = character_name

	# Class is stored as a display-name string on the account; map it to the wire enum
	# so sprite selection and the CONNECT_AUTH class byte use the chosen class.
	if character.has("class"):
		user_data["player_class"] = PacketTypes.class_name_to_id(_variant_to_string(character.get("class", "")))
	if character.has("level"):
		user_data["player_level"] = int(character.get("level", 1))
	if character.has("experience"):
		user_data["player_experience"] = int(character.get("experience", 0))


func _fetch_character_after_login(user_data: Dictionary) -> void:
	if jwt_token.is_empty():
		_complete_login(user_data)
		return

	var req := _create_http_request()
	req.request_completed.connect(_on_login_character_completed.bind(req, user_data), CONNECT_ONE_SHOT)

	var error := req.request(
		api_base_url + "/api/character/me",
		[get_auth_header()],
		HTTPClient.METHOD_GET
	)

	if error != OK:
		push_warning("[AuthManager] Character lookup request failed: %d" % error)
		req.queue_free()
		_complete_login(user_data)


func _on_login_character_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, req: HTTPRequest, user_data: Dictionary) -> void:
	req.queue_free()

	if result != HTTPRequest.RESULT_SUCCESS:
		push_warning("[AuthManager] Character lookup failed: %d" % result)
		_complete_login(user_data)
		return

	if response_code == 200:
		var json := JSON.new()
		var parse_error := json.parse(body.get_string_from_utf8())
		if parse_error == OK and json.data is Dictionary:
			var character: Dictionary = json.data
			_merge_character_data(user_data, character)
		else:
			push_warning("[AuthManager] Failed to parse character lookup response")
	elif response_code != 404:
		push_warning("[AuthManager] Character lookup returned status: %d" % response_code)

	_complete_login(user_data)


func _complete_login(user_data: Dictionary) -> void:
	var game_mgr = get_tree().root.get_node_or_null("GameManager")
	if game_mgr:
		game_mgr.set_player_data(user_data)

	_save_token()

	print("[AuthManager] Login successful for user: %s" % user_data.get("username", "unknown"))
	_change_state(AuthState.LOGGED_IN)
	login_successful.emit(user_data)


func _variant_to_string(value: Variant) -> String:
	if value == null:
		return ""
	if value is float and is_equal_approx(value, float(int(value))):
		return str(int(value))
	return str(value)
