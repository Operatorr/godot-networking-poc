## MainMenu - Main menu with character display and game entry
## Handles character display, region selection, and arena connection
extends Control

## UI Node references
@onready var character_panel: Control = $CenterContainer/VBoxContainer/CharacterPanel
@onready var character_portrait: TextureRect = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/CharacterPortrait
@onready var character_name_label: Label = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/CharacterInfo/CharacterNameLabel
@onready var region_dropdown: OptionButton = $CenterContainer/VBoxContainer/RegionDropdown
@onready var enter_world_button: Button = $CenterContainer/VBoxContainer/EnterWorldButton
@onready var logout_button: Button = $CenterContainer/VBoxContainer/LogoutButton
@onready var exit_button: Button = $CenterContainer/VBoxContainer/ExitButton
@onready var status_label: Label = $CenterContainer/VBoxContainer/StatusLabel
@onready var error_dialog: PopupPanel = $ErrorDialog

## Track connection state
var _is_connecting: bool = false

## Cached regions data
var regions: Array[RegionInfo] = []

## User preferences
var preferences: UserPreferences


func _ready() -> void:
	# Apply dark cosmic horror theme
	_apply_dark_theme()

	# Connect UI signals
	enter_world_button.pressed.connect(_on_enter_world_pressed)
	logout_button.pressed.connect(_on_logout_pressed)
	exit_button.pressed.connect(_on_exit_pressed)
	region_dropdown.item_selected.connect(_on_region_selected)

	# Connect ErrorDialog signals
	error_dialog.retry_pressed.connect(_on_error_retry)
	error_dialog.closed.connect(_on_error_closed)

	# Connect NetworkManager signals for connection handling
	NetworkManager.connected_to_server.connect(_on_connected_to_server)
	NetworkManager.disconnected_from_server.connect(_on_disconnected_from_server)
	NetworkManager.connection_error.connect(_on_connection_error)

	# Connect AuthManager signals
	AuthManager.logout_completed.connect(_on_logout_completed)

	# Load user preferences
	preferences = UserPreferences.load_preferences()

	# Update UI
	_update_character_display()
	_toggle_enter_world_visibility()

	# Fetch regions from API
	_fetch_regions()

	# Setup button audio
	_setup_button_audio()

	# Start background music
	AudioManager.play_music("menu_bgm")

	# Update status
	_update_status("Ready")

	print("[MainMenu] Ready")


## Apply dark cosmic horror theme to menu elements
func _apply_dark_theme() -> void:
	# Dark background
	var bg := ColorRect.new()
	bg.color = Color(0.04, 0.02, 0.06, 1.0)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.z_index = -1
	add_child(bg)
	move_child(bg, 0)

	# Style title
	var title_label: Label = $CenterContainer/VBoxContainer/TitleLabel
	if title_label:
		title_label.add_theme_color_override("font_color", Color(0.27, 0.53, 1.0))

	# Style status label
	if status_label:
		status_label.add_theme_color_override("font_color", Color(0.4, 1.0, 0.8, 0.7))


## Update character display panel
func _update_character_display() -> void:
	var player_data := GameManager.get_player_data()
	var char_name: String = player_data.get("character_name", "")

	if char_name.is_empty():
		character_name_label.text = "No Character"
		character_panel.visible = false
	else:
		character_name_label.text = char_name
		character_panel.visible = true

	# Portrait would be loaded from character data if available
	# For now, use placeholder
	# character_portrait.texture = load("res://assets/portraits/default.png")


## Toggle Enter World button visibility based on character existence
func _toggle_enter_world_visibility() -> void:
	enter_world_button.visible = GameManager.has_character()


## Fetch available regions from API
func _fetch_regions() -> void:
	# Create HTTP request for regions
	var http := HTTPRequest.new()
	add_child(http)
	http.request_completed.connect(_on_regions_fetched.bind(http))

	var url := AuthManager.api_base_url + "/api/regions"
	var error := http.request(url)

	if error != OK:
		push_warning("[MainMenu] Failed to request regions: %d" % error)
		_populate_default_regions()


## Handle regions API response
func _on_regions_fetched(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, http: HTTPRequest) -> void:
	http.queue_free()

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		push_warning("[MainMenu] Failed to fetch regions, using defaults")
		_populate_default_regions()
		return

	var json := JSON.new()
	var parse_result := json.parse(body.get_string_from_utf8())

	if parse_result != OK:
		push_warning("[MainMenu] Failed to parse regions response")
		_populate_default_regions()
		return

	var region_data_list: Array = []
	if json.data is Array:
		region_data_list = json.data
	elif json.data is Dictionary and json.data.has("regions") and json.data["regions"] is Array:
		region_data_list = json.data["regions"]
	else:
		push_warning("[MainMenu] Failed to parse regions response")
		_populate_default_regions()
		return

	regions.clear()
	for region_data: Dictionary in region_data_list:
		regions.append(RegionInfo.from_dict(region_data))

	_populate_region_dropdown()


## Populate region dropdown with fetched data
func _populate_region_dropdown() -> void:
	region_dropdown.clear()

	var selected_index := 0
	for i in range(regions.size()):
		var region := regions[i]
		if not region.is_available():
			continue

		region_dropdown.add_item(region.get_display_text(), i)

		# Select saved preference
		if region.id == preferences.selected_region:
			selected_index = region_dropdown.get_item_count() - 1

	if region_dropdown.get_item_count() > 0:
		region_dropdown.select(selected_index)
		var selected_region_index := region_dropdown.get_item_id(selected_index)
		GameManager.player_data["selected_region"] = regions[selected_region_index].id


## Populate default regions if API fails
func _populate_default_regions() -> void:
	regions.clear()

	var default_regions := [
		{"id": "local", "name": "Local", "websocket_url": "ws://localhost:8081", "status": "online", "active_players": 0, "max_players": 1000},
		{"id": "us-west", "name": "US West", "websocket_url": "ws://us-west.omegagame.io:9001", "status": "offline", "active_players": 0, "max_players": 1000},
		{"id": "us-east", "name": "US East", "websocket_url": "ws://localhost:8081", "status": "offline", "active_players": 0, "max_players": 1000},
		{"id": "europe", "name": "Europe", "websocket_url": "ws://localhost:8082", "status": "offline", "active_players": 0, "max_players": 1000},
		{"id": "asia", "name": "Asia", "websocket_url": "ws://localhost:8083", "status": "offline", "active_players": 0, "max_players": 1000}
	]

	for data in default_regions:
		regions.append(RegionInfo.from_dict(data))

	_populate_region_dropdown()


## Handle region selection
func _on_region_selected(index: int) -> void:
	if index < 0 or index >= region_dropdown.get_item_count():
		return

	var region_index := region_dropdown.get_item_id(index)
	if region_index < 0 or region_index >= regions.size():
		return

	var region := regions[region_index]
	GameManager.player_data["selected_region"] = region.id
	preferences.selected_region = region.id
	preferences.save()

	print("[MainMenu] Selected region: %s" % region.name)


## Handle Enter World button press
func _on_enter_world_pressed() -> void:
	if _is_connecting:
		return

	if regions.is_empty():
		_show_error("Connection Error", "No regions available. Please try again later.")
		return

	var selected_index := region_dropdown.selected
	if selected_index < 0 or selected_index >= region_dropdown.get_item_count():
		_show_error("Connection Error", "Please select a region.")
		return

	var region_index := region_dropdown.get_item_id(selected_index)
	if region_index < 0 or region_index >= regions.size():
		_show_error("Connection Error", "Please select a region.")
		return

	var region := regions[region_index]
	if not region.is_available():
		_show_error("Region Unavailable", "The selected region is currently unavailable.")
		return

	# Disable button and start connection
	_is_connecting = true
	enter_world_button.disabled = true
	_update_status("Connecting to %s..." % region.name)

	print("[MainMenu] Connecting to region: %s at %s" % [region.name, region.websocket_url])
	NetworkManager.connect_to_server(region.websocket_url, AuthManager.get_token())


## Handle successful server connection
func _on_connected_to_server() -> void:
	print("[MainMenu] Connected to server")
	_is_connecting = false
	enter_world_button.disabled = false
	_update_status("Connected!")

	# Transition to arena after brief delay
	await get_tree().create_timer(0.5).timeout
	SceneManager.goto_arena()


## Handle server disconnection
func _on_disconnected_from_server(reason: String) -> void:
	print("[MainMenu] Disconnected from server: %s" % reason)
	_is_connecting = false
	enter_world_button.disabled = false
	_update_status("Disconnected")


## Handle connection error
func _on_connection_error(error: String) -> void:
	print("[MainMenu] Connection error: %s" % error)
	_is_connecting = false
	enter_world_button.disabled = false
	_update_status("Connection failed")
	_show_error("Connection Error", error, true)


## Handle logout button press
func _on_logout_pressed() -> void:
	print("[MainMenu] Logging out...")
	preferences.save()
	AuthManager.logout()


## Handle logout completion
func _on_logout_completed() -> void:
	print("[MainMenu] Logout completed, navigating to login")
	SceneManager.goto_login()


## Handle exit button press
func _on_exit_pressed() -> void:
	print("[MainMenu] Exiting game")
	preferences.save()
	get_tree().quit()


## Show error dialog
func _show_error(title: String, message: String, allow_retry: bool = false) -> void:
	error_dialog.show_error(title, message, allow_retry)


## Handle error dialog retry
func _on_error_retry() -> void:
	_on_enter_world_pressed()


## Handle error dialog close
func _on_error_closed() -> void:
	pass


## Update status label
func _update_status(text: String) -> void:
	status_label.text = text


## Setup button audio for hover and click sounds
func _setup_button_audio() -> void:
	var buttons: Array[Button] = [enter_world_button, logout_button, exit_button]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Called when scene is about to exit
func on_scene_exit() -> void:
	# Stop music when leaving main menu
	AudioManager.stop_music()
