## MainMenu - Main menu with character display and game entry
## Handles character display, region selection, and arena connection
extends Control

const MenuFontHelper := preload("res://scripts/ui/helpers/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")
const ConfirmDialogScene := preload("res://scenes/ui/dialogs/confirm_dialog.tscn")
const MENU_BACKGROUND_PATH := "res://assets/ui/backgrounds/menu_background_004.jpg"
const TITLE_FONT_PATH := "res://assets/fonts/CormorantUnicase-Bold.ttf"
const TITLE_COLOR := Color(0.12, 0.12, 0.11)
const TITLE_OUTLINE_COLOR := Color.BLACK
const TITLE_GLOW_COLOR := Color(0.62, 0.62, 0.58, 0.58)
const REGION_REFRESH_INTERVAL := 5.0
## Upper bound on awaiting the Sanctuary link (NetworkManager's own connect timeout is shorter).
const CONNECT_TIMEOUT_SEC := 10.0

## Character card run-cycle preview: holder box footprint and the on-screen height every
## class canvas is scaled to (so classes with different canvases preview alike). The canvas
## is scaled to ~2x the swatch so the *figure* — which only fills part of its canvas — ends
## up roughly the size of the 64px colour swatch; the transparent padding overflows invisibly.
const CHARACTER_PREVIEW_SIZE := 80.0
const CHARACTER_PREVIEW_SPRITE_PX := 128.0

## UI Node references
@onready var menu_background: Control = $MenuBackground
@onready var character_panel: Control = $CenterContainer/VBoxContainer/CharacterPanel
@onready var player_color_picker: ColorPickerButton = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/PlayerColorPicker
@onready var character_name_label: Label = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/CharacterInfo/CharacterNameLabel
@onready var character_class_label: Label = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/CharacterInfo/CharacterLabel
@onready var delete_button: Button = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer/DeleteButton
@onready var region_dropdown: OptionButton = $CenterContainer/VBoxContainer/RegionDropdown
@onready var enter_world_button: Button = $CenterContainer/VBoxContainer/EnterWorldButton
@onready var enter_arena_button: Button = $CenterContainer/VBoxContainer/EnterArenaButton
@onready var practice_button: Button = $BottomLeftActions/PracticeButton
@onready var offline_sandbox_button: Button = $BottomLeftActions/OfflineSandboxButton
@onready var settings_button: Button = $CenterContainer/VBoxContainer/SettingsButton
@onready var logout_button: Button = $CenterContainer/VBoxContainer/LogoutButton
@onready var exit_button: Button = $CenterContainer/VBoxContainer/ExitButton
@onready var status_label: Label = $CenterContainer/VBoxContainer/StatusLabel
@onready var glory_label: Label = $CenterContainer/VBoxContainer/GloryLabel
@onready var error_dialog: PopupPanel = $ErrorDialog

## Looping run-cycle preview of the player's character, shown left of the color picker.
## Built programmatically and slotted as the first item in the character card's HBox.
var _character_preview_holder: Control = null
var _character_preview_sprite: AnimatedSprite2D = null

## Shown in place of the character card when no character exists; routes to creation.
var _create_character_button: Button = null

## Track connection state
var _is_connecting: bool = false
var _region_fetch_in_flight: bool = false
var _region_refresh_timer: float = 0.0
var _is_deleting: bool = false

## Reusable confirm dialog for character deletion (created on demand). Untyped because
## ConfirmDialog has no class_name (loaded via the scene) — methods resolve dynamically.
var _delete_confirm = null
var _delete_request: HTTPRequest = null

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
	enter_arena_button.pressed.connect(_on_enter_arena_pressed)
	practice_button.pressed.connect(_on_practice_pressed)
	offline_sandbox_button.pressed.connect(_on_offline_sandbox_pressed)
	settings_button.pressed.connect(_on_settings_pressed)
	logout_button.pressed.connect(_on_logout_pressed)
	exit_button.pressed.connect(_on_exit_pressed)
	region_dropdown.item_selected.connect(_on_region_selected)
	player_color_picker.color_changed.connect(_on_player_color_changed)
	delete_button.pressed.connect(_on_delete_pressed)

	# Connect ErrorDialog signals
	error_dialog.retry_pressed.connect(_on_error_retry)
	error_dialog.closed.connect(_on_error_closed)

	# Connect NetworkManager signals for connection handling
	NetworkManager.connected_to_server.connect(_on_connected_to_server)
	NetworkManager.disconnected_from_server.connect(_on_disconnected_from_server)
	NetworkManager.connection_error.connect(_on_connection_error)

	# Connect AuthManager signals
	AuthManager.logout_completed.connect(_on_logout_completed)
	AuthManager.character_refreshed.connect(_on_character_refreshed)

	# Load user preferences
	preferences = UserPreferences.load_preferences()
	GameManager.player_data["player_color"] = preferences.player_color
	player_color_picker.color = preferences.player_color

	# Build the looping character run-cycle preview (left of the color picker)
	_build_character_preview()

	# Build the "Create Character" button shown when no character exists
	_build_create_character_button()

	# Update UI
	_update_character_display()
	_toggle_enter_world_visibility()
	_update_glory_display()

	# Fetch regions from API
	_fetch_regions()

	# Re-confirm authoritative character + Glory from the API. This keeps the menu honest after
	# an async hardcore permadeath (deleted character, freshly-credited Glory) without needing a
	# re-login, and prevents the stale "create character" path. Updates the UI when it lands.
	AuthManager.refresh_character()

	# Setup button audio
	_setup_button_audio()

	# Start background music
	AudioManager.play_music("menu_bgm")

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

	MenuButtonHelper.apply_to_buttons([enter_world_button, enter_arena_button, practice_button, offline_sandbox_button, settings_button, logout_button, exit_button])


## Update character display panel
func _update_character_display() -> void:
	var player_data := GameManager.get_player_data()
	var char_name: String = player_data.get("character_name", "")

	var has_character := not char_name.is_empty()
	if has_character:
		character_name_label.text = char_name
	else:
		character_name_label.text = "No Character"
	# Show the character card when one exists, otherwise the "Create Character" button.
	character_panel.visible = has_character
	if _create_character_button:
		_create_character_button.visible = not has_character

	# Sublabel shows the character's class instead of the generic "Character".
	if character_class_label:
		var class_id: int = int(player_data.get("player_class", PacketTypes.PlayerClass.ZEALOT))
		character_class_label.text = PacketTypes.class_id_to_name(class_id)

	if player_color_picker:
		player_color_picker.color = player_data.get("player_color", UserPreferences.DEFAULT_PLAYER_COLOR)

	# Refresh the run-cycle preview to the current class + color.
	_update_character_preview()


## Build the looping character run-cycle preview and slot it as the first item in the
## character card's HBox (left of the color picker). The sprite mirrors the in-game class
## artwork, faces south (run_0 = downwards), and is tinted by the player color the same way
## Player.set_player_color does.
func _build_character_preview() -> void:
	var hbox: HBoxContainer = $CenterContainer/VBoxContainer/CharacterPanel/HBoxContainer

	_character_preview_holder = Control.new()
	_character_preview_holder.name = "CharacterPreview"
	_character_preview_holder.custom_minimum_size = Vector2(CHARACTER_PREVIEW_SIZE, CHARACTER_PREVIEW_SIZE)
	_character_preview_holder.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	_character_preview_holder.mouse_filter = Control.MOUSE_FILTER_IGNORE

	_character_preview_sprite = AnimatedSprite2D.new()
	_character_preview_sprite.centered = true
	_character_preview_holder.add_child(_character_preview_sprite)
	# Keep the sprite centered whenever the container resizes the holder.
	_character_preview_holder.resized.connect(_recenter_character_preview)

	hbox.add_child(_character_preview_holder)
	hbox.move_child(_character_preview_holder, 0)
	_recenter_character_preview()


func _recenter_character_preview() -> void:
	if _character_preview_sprite and _character_preview_holder:
		_character_preview_sprite.position = _character_preview_holder.size * 0.5


## Point the preview at the current class's south-facing run cycle, looping. Hides the sprite
## when the class sheet is absent (no procedural fallback in the menu preview).
func _update_character_preview() -> void:
	if _character_preview_sprite == null:
		return

	var class_id: int = int(GameManager.get_player_data().get("player_class", PacketTypes.PlayerClass.ZEALOT))
	var frames := SheetLibrary.class_frames(class_id)
	var anim := SheetLibrary.anim_for("run", 0)  # row 0 = south (downwards)
	if frames == null or not frames.has_animation(anim):
		_character_preview_sprite.visible = false
		return

	_character_preview_sprite.visible = true
	_character_preview_sprite.sprite_frames = frames
	# Fit the source canvas height to a fixed on-screen size so every class previews alike.
	var tex := frames.get_frame_texture(anim, 0)
	var src_h := tex.get_size().y if tex else CHARACTER_PREVIEW_SPRITE_PX
	if src_h > 0.0:
		_character_preview_sprite.scale = Vector2.ONE * (CHARACTER_PREVIEW_SPRITE_PX / src_h)
	_character_preview_sprite.play(anim)
	_apply_character_preview_tint()


## Tint the preview toward the player color exactly like Player.set_player_color does.
func _apply_character_preview_tint() -> void:
	if _character_preview_sprite == null:
		return
	var color: Color = GameManager.get_player_data().get("player_color", UserPreferences.DEFAULT_PLAYER_COLOR)
	_character_preview_sprite.modulate = Color.WHITE.lerp(color, GameConstants.CLASS_SPRITE_TINT_STRENGTH)


## Build the "Create Character" button, slotted where the character card sits in the VBox.
## Visible only when no character exists (toggled in _update_character_display).
func _build_create_character_button() -> void:
	var vbox: VBoxContainer = $CenterContainer/VBoxContainer
	_create_character_button = Button.new()
	_create_character_button.name = "CreateCharacterButton"
	_create_character_button.text = "Create Character"
	_create_character_button.custom_minimum_size = Vector2(400, 80)
	_create_character_button.add_theme_font_size_override("font_size", 20)
	_create_character_button.pressed.connect(_on_create_character_pressed)
	_create_character_button.mouse_entered.connect(func(): AudioManager.play_button_hover())
	_create_character_button.pressed.connect(func(): AudioManager.play_button_click())
	vbox.add_child(_create_character_button)
	# Sit it just below the (hidden) character card so it occupies the card's slot.
	vbox.move_child(_create_character_button, character_panel.get_index() + 1)
	MenuButtonHelper.apply_to_buttons([_create_character_button])


## Route to the character creation screen.
func _on_create_character_pressed() -> void:
	SceneManager.goto_character_creation()


## Enable Enter World / Enter Arena only when a character exists (kept visible but disabled
## otherwise — both routes drop the player into a live, server-authoritative session).
func _toggle_enter_world_visibility() -> void:
	var has_character := GameManager.has_character()
	enter_world_button.disabled = not has_character
	enter_arena_button.disabled = not has_character


## Refresh the account Glory shown at the top of the menu from the cached player data.
func _update_glory_display() -> void:
	if glory_label:
		glory_label.text = "Glory: %d" % int(GameManager.get_player_data().get("glory", 0))


## AuthManager finished re-syncing /api/character/me — reflect the true character + Glory state.
func _on_character_refreshed(_has_character: bool) -> void:
	_update_character_display()
	_toggle_enter_world_visibility()
	_update_glory_display()


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

	# Offline fallback shown only when the /api/regions fetch fails. connect_url is a bare
	# host:port (ENet/UDP); these are placeholders, so all but Local are marked offline.
	var default_regions := [
		{"id": "local", "name": "Local", "connect_url": "localhost:8081", "status": "online", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "us-west", "name": "US West", "connect_url": "", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "us-east", "name": "US East", "connect_url": "", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "europe", "name": "Europe", "connect_url": "", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS},
		{"id": "asia", "name": "Asia", "connect_url": "", "status": "offline", "active_players": 0, "max_players": RegionInfo.DEFAULT_MAX_PLAYERS}
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

	# Live-update the run-cycle preview tint to match the new color.
	_apply_character_preview_tint()


## Ask for confirmation before deleting the character.
func _on_delete_pressed() -> void:
	if _is_deleting or not GameManager.has_character():
		return

	var char_name: String = GameManager.get_player_data().get("character_name", "your character")
	if _delete_confirm == null:
		_delete_confirm = ConfirmDialogScene.instantiate()
		add_child(_delete_confirm)
		_delete_confirm.confirmed.connect(_on_delete_confirmed)
	_delete_confirm.show_confirm(
		"Delete Character",
		"Permanently delete \"%s\"? This cannot be undone." % char_name,
		"Delete",
		"Cancel"
	)


## Confirmed deletion: call the API to remove the character.
func _on_delete_confirmed() -> void:
	if _is_deleting:
		return
	_is_deleting = true
	delete_button.disabled = true
	_update_status("Deleting character...")

	if _delete_request == null:
		_delete_request = HTTPRequest.new()
		add_child(_delete_request)
	if _delete_request.request_completed.is_connected(_on_delete_completed):
		_delete_request.request_completed.disconnect(_on_delete_completed)
	_delete_request.request_completed.connect(_on_delete_completed)

	var url := AuthManager.api_base_url + "/api/character"
	var headers := [AuthManager.get_auth_header()]
	var error := _delete_request.request(url, headers, HTTPClient.METHOD_DELETE)
	if error != OK:
		_on_delete_failed("Network error: failed to send request")


## Handle the delete API response.
func _on_delete_completed(result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	_delete_request.request_completed.disconnect(_on_delete_completed)
	_is_deleting = false
	delete_button.disabled = false

	if result != HTTPRequest.RESULT_SUCCESS:
		_on_delete_failed("Network error: request failed")
		return

	if response_code == 200 or response_code == 204:
		# Character removed: drop local state and route back to creation.
		GameManager.clear_local_player_entity_id()
		GameManager.player_data["character_name"] = ""
		GameManager.player_data["character_id"] = ""
		GameManager.player_data["player_class"] = PacketTypes.PlayerClass.ZEALOT
		# Belt-and-suspenders: the DB is authoritative, but reset the local level/XP
		# display so a deleted character's level can't leak into the next one (the
		# old XP-carryover bug). reset_progression() emits experience_updated too.
		GameManager.reset_progression()
		GameManager.player_data_updated.emit()
		_update_status("Character deleted")
		print("[MainMenu] Character deleted; showing Create Character on the menu")
		# Stay on the menu: swap the card for the Create Character button and gate Enter World.
		_update_character_display()
		_toggle_enter_world_visibility()
	else:
		_on_delete_failed("Server returned status %d" % response_code)


func _on_delete_failed(message: String) -> void:
	_is_deleting = false
	delete_button.disabled = false
	_update_status("Delete failed")
	_show_error("Delete Failed", message, false)


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

	# Entering the world now joins the NETWORKED Sanctuary instance (the region host on the
	# Sanctuary port, 8082). The Arena portal in town later disconnects and dials the same
	# region's Arena instance (8081), so stash the region URL where Portal looks for it.
	GameManager.player_data["selected_region_url"] = region.connect_url
	preferences.save()

	enter_world_button.disabled = true
	_is_connecting = true
	_update_status("Connecting to the Sanctuary...")

	var sanctuary_url := NetworkManager.sanctuary_url_for_region(region.connect_url)
	print("[MainMenu] Connecting to Sanctuary instance %s (region %s)" % [sanctuary_url, region.name])

	var connected: bool = await _connect_and_wait(sanctuary_url)
	_is_connecting = false
	if not connected:
		# NetworkManager emits connection_error on a failed dial, which _on_connection_error
		# turns into the error dialog + button re-enable; just reset the status here so the
		# two paths don't stack duplicate dialogs.
		enter_world_button.disabled = false
		_update_status("Could not reach the Sanctuary")
		return

	_update_status("Entering the Sanctuary...")
	enter_world_button.disabled = false
	SceneManager.goto_sanctuary()


## Handle Enter Arena: skip the Sanctuary and dial the region's ARENA instance (port 8081)
## directly, then load the arena scene. Mirrors _on_enter_world_pressed but targets the Arena
## URL and goto_arena(); the region URL is still stashed so the in-arena "return to Sanctuary"
## route knows where to go.
func _on_enter_arena_pressed() -> void:
	if _is_connecting:
		return

	var region := _selected_region_or_error()
	if region == null:
		return

	GameManager.player_data["selected_region_url"] = region.connect_url
	preferences.save()

	enter_world_button.disabled = true
	enter_arena_button.disabled = true
	_is_connecting = true
	_update_status("Connecting to the Arena...")

	var arena_url := NetworkManager.arena_url_for_region(region.connect_url)
	print("[MainMenu] Connecting to Arena instance %s (region %s)" % [arena_url, region.name])

	var connected: bool = await _connect_and_wait(arena_url)
	_is_connecting = false
	if not connected:
		enter_world_button.disabled = false
		enter_arena_button.disabled = false
		_update_status("Could not reach the Arena")
		return

	_update_status("Entering the Arena...")
	enter_world_button.disabled = false
	enter_arena_button.disabled = false
	SceneManager.goto_arena()


## Resolve the currently selected, available region, surfacing the same errors as Enter World.
## Returns null (after showing an error dialog) when no valid region is selected.
func _selected_region_or_error() -> RegionInfo:
	if regions.is_empty():
		_show_error("Connection Error", "No regions available. Please try again later.")
		return null

	var selected_index := region_dropdown.selected
	if selected_index < 0 or selected_index >= region_dropdown.get_item_count():
		_show_error("Connection Error", "Please select a region.")
		return null

	var region_index := region_dropdown.get_item_id(selected_index)
	if region_index < 0 or region_index >= regions.size():
		_show_error("Connection Error", "Please select a region.")
		return null

	var region := regions[region_index]
	if not region.is_available():
		_show_error("Region Unavailable", "The selected region is currently unavailable.")
		return null
	return region


## Open the standalone Settings screen (Audio / Video / Controls).
func _on_settings_pressed() -> void:
	SceneManager.goto_settings()


## Dial a game-server instance and await the link opening, mirroring Portal._connect_to_destination_instance.
## Returns true once NetworkManager reports the connection is open, false on error/timeout.
func _connect_and_wait(url: String) -> bool:
	if NetworkManager.is_server_connected():
		# Already linked to some instance — drop it so we land on the requested one.
		NetworkManager.disconnect_from_server("Switching instance")
		await get_tree().process_frame

	NetworkManager.connect_to_server(url, AuthManager.get_token())

	var state := {"done": false, "ok": false}
	var on_connected := func() -> void:
		state["done"] = true
		state["ok"] = true
	var on_error := func(_error: String) -> void:
		state["done"] = true
	var on_disconnected := func(_reason: String) -> void:
		state["done"] = true

	NetworkManager.connected_to_server.connect(on_connected)
	NetworkManager.connection_error.connect(on_error)
	NetworkManager.disconnected_from_server.connect(on_disconnected)

	var waited := 0.0
	while not state["done"] and waited < CONNECT_TIMEOUT_SEC:
		await get_tree().process_frame
		waited += get_process_delta_time()

	NetworkManager.connected_to_server.disconnect(on_connected)
	NetworkManager.connection_error.disconnect(on_error)
	NetworkManager.disconnected_from_server.disconnect(on_disconnected)

	return state["ok"]


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


## Handle successful server connection. The menu no longer dials the server
## itself (the Sanctuary's Arena portal does), so this only updates status.
func _on_connected_to_server() -> void:
	print("[MainMenu] Connected to server")
	_is_connecting = false
	enter_world_button.disabled = false
	_update_status("Connected!")


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
		enter_arena_button,
		practice_button,
		offline_sandbox_button,
		settings_button,
		logout_button,
		exit_button
	]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Called when scene is about to exit
func on_scene_exit() -> void:
	pass
