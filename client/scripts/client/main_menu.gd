## MainMenu - Main menu with character display and game entry
## Handles character display, region selection, and arena connection
extends Control

const MenuFontHelper := preload("res://scripts/client/ui/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/client/ui/menu_button_helper.gd")
const MENU_BACKGROUND_PATH := "res://assets/ui/backgrounds/menu_background_004.jpg"
const TITLE_FONT_PATH := "res://assets/fonts/CormorantUnicase-Bold.ttf"
const TITLE_COLOR := Color(0.12, 0.12, 0.11)
const TITLE_OUTLINE_COLOR := Color.BLACK
const TITLE_GLOW_COLOR := Color(0.62, 0.62, 0.58, 0.58)
const REGION_REFRESH_INTERVAL := 5.0

## UI Node references
@onready var menu_background: Control = $MenuBackground
@onready var character_panel: Control = $CenterContainer/VBoxContainer/CharacterPanel
@onready var player_color_picker: ColorPickerButton = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/PlayerColorPicker
@onready var character_name_label: Label = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/CharacterInfo/CharacterNameLabel
@onready var region_dropdown: OptionButton = $CenterContainer/VBoxContainer/RegionDropdown
@onready var enter_world_button: Button = $CenterContainer/VBoxContainer/EnterWorldButton
@onready var practice_button: Button = $BottomLeftActions/PracticeButton
@onready var offline_sandbox_button: Button = $BottomLeftActions/OfflineSandboxButton
@onready var logout_button: Button = $CenterContainer/VBoxContainer/LogoutButton
@onready var exit_button: Button = $CenterContainer/VBoxContainer/ExitButton
@onready var status_label: Label = $CenterContainer/VBoxContainer/StatusLabel
@onready var error_dialog: PopupPanel = $ErrorDialog

## Track connection state
var _is_connecting: bool = false
var _region_fetch_in_flight: bool = false
var _region_refresh_timer: float = 0.0

## Cached regions data
var regions: Array[RegionInfo] = []

## User preferences
var preferences: UserPreferences


func _ready() -> void:
	# Apply dark cosmic horror theme
	_apply_dark_theme()
	MenuFontHelper.apply_to_tree(self)

	# Connect UI signals
	enter_world_button.pressed.connect(_on_enter_world_pressed)
	practice_button.pressed.connect(_on_practice_pressed)
	offline_sandbox_button.pressed.connect(_on_offline_sandbox_pressed)
	logout_button.pressed.connect(_on_logout_pressed)
	exit_button.pressed.connect(_on_exit_pressed)
	region_dropdown.item_selected.connect(_on_region_selected)
	player_color_picker.color_changed.connect(_on_player_color_changed)

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
	GameManager.player_data["player_color"] = preferences.player_color
	player_color_picker.color = preferences.player_color

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


func _process(delta: float) -> void:
	_region_refresh_timer += delta
	if _region_refresh_timer >= REGION_REFRESH_INTERVAL:
		_region_refresh_timer = 0.0
		_fetch_regions()


## Apply dark cosmic horror theme to menu elements
func _apply_dark_theme() -> void:
	# Keep the menu background non-interactive and full screen.
	if menu_background:
		menu_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
		menu_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

		if menu_background is TextureRect:
			var texture_background := menu_background as TextureRect
			var background_texture := load(MENU_BACKGROUND_PATH) as Texture2D
			if background_texture:
				texture_background.texture = background_texture
			else:
				push_warning("[MainMenu] Failed to load menu background: %s" % MENU_BACKGROUND_PATH)
			texture_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			texture_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		elif menu_background is VideoStreamPlayer:
			var video_background := menu_background as VideoStreamPlayer
			video_background.expand = true
			video_background.loop = true
			if video_background.stream != null and not video_background.is_playing():
				video_background.play()
		else:
			push_warning("[MainMenu] Unsupported MenuBackground node type: %s" % menu_background.get_class())

	# Style title
	var title_label: Label = $CenterContainer/VBoxContainer/TitleLabel
	if title_label:
		var title_font := load(TITLE_FONT_PATH) as FontFile
		if title_font:
			title_label.add_theme_font_override("font", title_font)
		else:
			push_warning("[MainMenu] Failed to load title font: %s" % TITLE_FONT_PATH)

		title_label.text = "OMEGA REALM"
		title_label.add_theme_color_override("font_color", TITLE_COLOR)
		title_label.add_theme_color_override("font_outline_color", TITLE_OUTLINE_COLOR)
		title_label.add_theme_color_override("font_shadow_color", TITLE_GLOW_COLOR)
		title_label.add_theme_constant_override("outline_size", 8)
		title_label.add_theme_constant_override("shadow_offset_x", 0)
		title_label.add_theme_constant_override("shadow_offset_y", 0)
		title_label.add_theme_constant_override("shadow_outline_size", 12)
		title_label.add_theme_font_size_override("font_size", 56)

	# Style status label
	if status_label:
		status_label.add_theme_color_override("font_color", Color.WHITE)

	MenuButtonHelper.apply_to_buttons([enter_world_button, practice_button, offline_sandbox_button, logout_button, exit_button])


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

	if player_color_picker:
		player_color_picker.color = player_data.get("player_color", UserPreferences.DEFAULT_PLAYER_COLOR)


## Toggle Enter World button visibility based on character existence
func _toggle_enter_world_visibility() -> void:
	enter_world_button.visible = GameManager.has_character()


## Fetch available regions from API
func _fetch_regions() -> void:
	if _region_fetch_in_flight:
		return

	# Create HTTP request for regions
	var http := HTTPRequest.new()
	add_child(http)
	http.request_completed.connect(_on_regions_fetched.bind(http))
	_region_fetch_in_flight = true

	var url := AuthManager.api_base_url + "/api/regions"
	var error := http.request(url)

	if error != OK:
		_region_fetch_in_flight = false
		http.queue_free()
		push_warning("[MainMenu] Failed to request regions: %d" % error)
		_populate_default_regions()


## Handle regions API response
func _on_regions_fetched(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray, http: HTTPRequest) -> void:
	http.queue_free()
	_region_fetch_in_flight = false

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
		{"id": "local", "name": "Local", "websocket_url": "ws://localhost:8081", "status": "online", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "us-west", "name": "US West", "websocket_url": "ws://us-west.omegagame.io:9001", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "us-east", "name": "US East", "websocket_url": "ws://localhost:8081", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "europe", "name": "Europe", "websocket_url": "ws://localhost:8082", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "asia", "name": "Asia", "websocket_url": "ws://localhost:8083", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS}
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


## Handle local player color selection
func _on_player_color_changed(color: Color) -> void:
	color.a = 1.0
	GameManager.player_data["player_color"] = color
	preferences.player_color = color
	preferences.save()


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


## Handle Practice button press
func _on_practice_pressed() -> void:
	if _is_connecting:
		return

	preferences.save()
	_update_status("Loading practice...")
	SceneManager.goto_practice()


## Handle Offline Sandbox button press
func _on_offline_sandbox_pressed() -> void:
	if _is_connecting:
		return

	preferences.save()
	_update_status("Loading sandbox...")
	SceneManager.goto_offline_sandbox()


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
	var buttons: Array[Button] = [
		enter_world_button,
		practice_button,
		offline_sandbox_button,
		logout_button,
		exit_button
	]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Called when scene is about to exit
func on_scene_exit() -> void:
	pass
