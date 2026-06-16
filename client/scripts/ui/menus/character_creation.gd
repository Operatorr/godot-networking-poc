## CharacterCreation - Handles new character creation flow
## Validates name and creates character via API
extends Control

const MenuFontHelper := preload("res://scripts/ui/helpers/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")

## Name validation constants
const MIN_NAME_LENGTH: int = 3
const MAX_NAME_LENGTH: int = 16
const NAME_PATTERN: String = "^[a-zA-Z0-9_]+$"

## UI node references
@onready var name_input: LineEdit = $CenterContainer/VBoxContainer/NameInput
@onready var validation_label: Label = $CenterContainer/VBoxContainer/ValidationLabel
@onready var create_button: Button = $CenterContainer/VBoxContainer/CreateButton
@onready var back_button: Button = $CenterContainer/VBoxContainer/BackButton
@onready var error_dialog: PopupPanel = $ErrorDialog

## Track creation state to prevent duplicate requests
var is_creating: bool = false

## Guards the one-shot self-heal retry when the API reports "User already has a character"
## (HTTP 409 / code "character_exists"). This happens when a hardcore permadeath delete hasn't
## committed yet by the time the player re-creates; we re-sync against /api/character/me and
## retry once. Without the guard a persistent 409 would loop forever.
var _conflict_retry_used: bool = false

## HTTP request for character creation
var http_request: HTTPRequest

## Selected class (PacketTypes.PlayerClass). The color swatch on the main menu still
## tints the sprite — class chooses which class artwork is tinted.
var _selected_class: int = PacketTypes.PlayerClass.WARRIOR
var _class_buttons: Array[Button] = []
var _class_preview_holder: Control = null
var _class_preview_sprite: AnimatedSprite2D = null

## Class preview: holder footprint and the on-screen height each class canvas is scaled to.
## ~2x the old 96px idle thumbnail so the (partial-canvas) figure reads clearly.
const CLASS_PREVIEW_HOLDER := 180.0
const CLASS_PREVIEW_SPRITE_PX := 192.0

## Selected permadeath mode ("softcore" or "hardcore"), sent in the create body. Default
## Softcore. Hardcore is the permadeath ruleset (ADR 0005).
var _selected_mode: String = "softcore"
var _mode_buttons: Array[Button] = []


func _ready() -> void:
	MenuFontHelper.apply_to_tree(self)
	MenuButtonHelper.apply_to_buttons([create_button, back_button])

	# Create HTTP request node
	http_request = HTTPRequest.new()
	add_child(http_request)

	# Connect UI signals
	name_input.text_changed.connect(_on_name_text_changed)
	create_button.pressed.connect(_on_create_pressed)
	back_button.pressed.connect(_on_back_pressed)

	# Connect ErrorDialog signals
	error_dialog.retry_pressed.connect(_on_error_retry)
	error_dialog.closed.connect(_on_error_closed)

	# Setup focus navigation
	_setup_focus_navigation()

	# Setup button audio
	_setup_button_audio()

	# Build the class picker (sprite preview + class buttons)
	_build_class_picker()

	# Build the Softcore/Hardcore mode picker (defaults to Softcore)
	_build_mode_picker()

	# Set max length
	name_input.max_length = MAX_NAME_LENGTH

	# Initial validation state
	_validate_name(name_input.text)

	# Set initial focus
	name_input.grab_focus()

	print("[CharacterCreation] Ready")


## Setup Tab navigation
func _setup_focus_navigation() -> void:
	name_input.focus_neighbor_bottom = create_button.get_path()
	name_input.focus_next = create_button.get_path()

	create_button.focus_neighbor_top = name_input.get_path()
	create_button.focus_previous = name_input.get_path()


## Validate character name
func _validate_name(character_name: String) -> bool:
	var stripped := character_name.strip_edges()

	# Check length
	if stripped.length() < MIN_NAME_LENGTH:
		_show_validation_error("Name must be at least %d characters" % MIN_NAME_LENGTH)
		return false

	if stripped.length() > MAX_NAME_LENGTH:
		_show_validation_error("Name must not exceed %d characters" % MAX_NAME_LENGTH)
		return false

	# Check pattern (alphanumeric + underscore only)
	var regex := RegEx.new()
	regex.compile(NAME_PATTERN)
	var result := regex.search(stripped)

	if result == null or result.get_string() != stripped:
		_show_validation_error("Name can only contain letters, numbers, and underscores")
		return false

	_show_validation_success("Name is valid")
	return true


## Show validation error message
func _show_validation_error(message: String) -> void:
	validation_label.text = message
	validation_label.add_theme_color_override("font_color", Color.RED)
	create_button.disabled = true


## Show validation success message
func _show_validation_success(message: String) -> void:
	validation_label.text = message
	validation_label.add_theme_color_override("font_color", Color.GREEN)
	create_button.disabled = false


## Handle name input text change (real-time validation)
func _on_name_text_changed(new_text: String) -> void:
	_validate_name(new_text)


## Handle create button press. `user_initiated` is true for genuine user presses (button /
## Enter / error-dialog retry) and false for the internal stale-409 self-heal retry — only a
## fresh user-initiated create re-arms the one-shot self-heal, so a persistent 409 can't loop.
func _on_create_pressed(user_initiated: bool = true) -> void:
	if is_creating:
		return

	if user_initiated:
		_conflict_retry_used = false

	var character_name := name_input.text.strip_edges()

	# Final validation
	if not _validate_name(character_name):
		return

	# Disable button and start creation
	is_creating = true
	create_button.disabled = true
	create_button.text = "Creating..."

	print("[CharacterCreation] Creating character: %s" % character_name)
	_create_character(character_name)


## Build the class picker: a large sprite preview plus one toggle button per class.
## The preview loops the south-facing (downwards) run cycle from each class's spritesheet.
func _build_class_picker() -> void:
	var vbox: VBoxContainer = $CenterContainer/VBoxContainer

	var section := VBoxContainer.new()
	section.name = "ClassSection"
	section.add_theme_constant_override("separation", 8)

	var heading := Label.new()
	heading.text = "Choose Class"
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	section.add_child(heading)

	_class_preview_holder = Control.new()
	_class_preview_holder.custom_minimum_size = Vector2(CLASS_PREVIEW_HOLDER, CLASS_PREVIEW_HOLDER)
	_class_preview_holder.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_class_preview_holder.mouse_filter = Control.MOUSE_FILTER_IGNORE
	section.add_child(_class_preview_holder)

	_class_preview_sprite = AnimatedSprite2D.new()
	_class_preview_sprite.centered = true
	_class_preview_holder.add_child(_class_preview_sprite)
	# Keep the sprite centered whenever the container resizes the holder.
	_class_preview_holder.resized.connect(_recenter_class_preview)
	_recenter_class_preview()

	var grid := GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 6)
	grid.add_theme_constant_override("v_separation", 6)
	grid.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	section.add_child(grid)

	var group := ButtonGroup.new()
	for class_id in PacketTypes.CLASS_DISPLAY_NAMES.size():
		var btn := Button.new()
		btn.toggle_mode = true
		btn.button_group = group
		btn.text = String(PacketTypes.CLASS_DISPLAY_NAMES[class_id])
		btn.custom_minimum_size = Vector2(122, 40)
		btn.add_theme_font_size_override("font_size", 13)
		btn.toggled.connect(_on_class_toggled.bind(class_id))
		btn.mouse_entered.connect(func(): AudioManager.play_button_hover())
		# Pre-alpha scope: hide classes that are not yet playable (kept in the enum so
		# array indices stay class-id-aligned and the deferred art/data survives).
		if not PacketTypes.is_class_playable(class_id):
			btn.disabled = true
			btn.visible = false
		grid.add_child(btn)
		_class_buttons.append(btn)

	vbox.add_child(section)
	# Slot the picker in just below the validation label, above the create button.
	vbox.move_child(section, validation_label.get_index() + 1)

	# Seed the default selection without firing the toggled handler (no click sound).
	_class_buttons[_selected_class].set_pressed_no_signal(true)
	_update_class_preview()


func _on_class_toggled(pressed: bool, class_id: int) -> void:
	if not pressed:
		return
	_selected_class = class_id
	AudioManager.play_button_click()
	_update_class_preview()


func _recenter_class_preview() -> void:
	if _class_preview_sprite and _class_preview_holder:
		_class_preview_sprite.position = _class_preview_holder.size * 0.5


## Point the preview at the selected class's south-facing run cycle, looping. Hides the
## sprite when the class sheet is absent.
func _update_class_preview() -> void:
	if _class_preview_sprite == null:
		return

	var frames := SheetLibrary.class_frames(_selected_class)
	var anim := SheetLibrary.anim_for("run", 0)  # row 0 = south (downwards)
	if frames == null or not frames.has_animation(anim):
		_class_preview_sprite.visible = false
		return

	_class_preview_sprite.visible = true
	_class_preview_sprite.sprite_frames = frames
	# Fit the source canvas height to a fixed on-screen size so every class previews alike.
	var tex := frames.get_frame_texture(anim, 0)
	var src_h := tex.get_size().y if tex else CLASS_PREVIEW_SPRITE_PX
	if src_h > 0.0:
		_class_preview_sprite.scale = Vector2.ONE * (CLASS_PREVIEW_SPRITE_PX / src_h)
	_class_preview_sprite.play(anim)


## Build the permadeath-mode picker: a Softcore/Hardcore toggle group (mirrors the class
## picker's ButtonGroup pattern). Defaults to Softcore.
func _build_mode_picker() -> void:
	var vbox: VBoxContainer = $CenterContainer/VBoxContainer

	var section := VBoxContainer.new()
	section.name = "ModeSection"
	section.add_theme_constant_override("separation", 8)

	var heading := Label.new()
	heading.text = "Choose Mode"
	heading.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	section.add_child(heading)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	row.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	section.add_child(row)

	var group := ButtonGroup.new()
	# [mode key, button label]. Hardcore is explicitly labelled as permadeath.
	var modes := [["softcore", "Softcore"], ["hardcore", "Hardcore (permadeath)"]]
	for entry: Array in modes:
		var mode_key: String = entry[0]
		var btn := Button.new()
		btn.toggle_mode = true
		btn.button_group = group
		btn.text = String(entry[1])
		btn.custom_minimum_size = Vector2(186, 40)
		btn.add_theme_font_size_override("font_size", 13)
		btn.toggled.connect(_on_mode_toggled.bind(mode_key))
		btn.mouse_entered.connect(func(): AudioManager.play_button_hover())
		row.add_child(btn)
		_mode_buttons.append(btn)

	vbox.add_child(section)
	# Slot the mode picker just below the class picker (above the create button).
	var class_section := vbox.get_node_or_null("ClassSection")
	if class_section:
		vbox.move_child(section, class_section.get_index() + 1)

	# Seed the default Softcore selection without firing the toggled handler.
	_mode_buttons[0].set_pressed_no_signal(true)


func _on_mode_toggled(pressed: bool, mode_key: String) -> void:
	if not pressed:
		return
	_selected_mode = mode_key
	AudioManager.play_button_click()


## Create character via API
func _create_character(character_name: String) -> void:
	var url := AuthManager.api_base_url + "/api/character/create"
	var headers := [
		"Content-Type: application/json",
		AuthManager.get_auth_header()
	]
	var body := JSON.stringify({
		"name": character_name,
		"class": PacketTypes.class_id_to_name(_selected_class),
		"mode": _selected_mode
	})

	# Connect to request completion
	if http_request.request_completed.is_connected(_on_create_completed):
		http_request.request_completed.disconnect(_on_create_completed)
	http_request.request_completed.connect(_on_create_completed)

	var error := http_request.request(url, headers, HTTPClient.METHOD_POST, body)

	if error != OK:
		print("[CharacterCreation] HTTP Request failed: %d" % error)
		_on_create_failed("Network error: Failed to send request")


## Handle character creation response
func _on_create_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	http_request.request_completed.disconnect(_on_create_completed)

	is_creating = false
	create_button.disabled = false
	create_button.text = "Create Character"

	if result != HTTPRequest.RESULT_SUCCESS:
		print("[CharacterCreation] Request failed: %d" % result)
		_on_create_failed("Network error: Request failed")
		return

	var json := JSON.new()
	var parse_result := json.parse(body.get_string_from_utf8())

	if parse_result != OK:
		print("[CharacterCreation] Failed to parse response")
		_on_create_failed("Invalid server response")
		return

	if response_code == 201 or response_code == 200:
		# Success - extract character data
		var data: Dictionary = json.data
		var character: Dictionary = data.get("character", {})

		var character_name: String = character.get("name", "")
		var character_id: String = str(character.get("id", ""))

		# Update GameManager with character data (including the chosen class so the
		# sprite + CONNECT_AUTH class byte match the selection).
		GameManager.set_player_data({
			"character_name": character_name,
			"character_id": character_id,
			"player_class": _selected_class,
			"character_mode": str(character.get("mode", _selected_mode))
		})

		print("[CharacterCreation] Character created successfully: %s" % character_name)
		_on_create_successful()
		return

	# Stale "User already has a character" after a hardcore permadeath: the server-side delete
	# may not have committed yet (it runs async after the death kick). Re-confirm against the DB
	# and either route to the surviving character or retry the create once.
	if response_code == 409 and not _conflict_retry_used and _is_character_exists_conflict(json):
		_conflict_retry_used = true
		_resolve_create_conflict()
		return

	# Error response
	var error_message: String = "Character creation failed"
	if json.data is Dictionary:
		error_message = json.data.get("error", error_message)
	print("[CharacterCreation] Creation failed: %s" % error_message)
	_on_create_failed(error_message)


## True if the create response is the "user already has a character" conflict (matched by the
## machine-readable code, with a fallback to the human string for older API builds).
func _is_character_exists_conflict(json: JSON) -> bool:
	if not (json.data is Dictionary):
		return false
	var data: Dictionary = json.data
	if str(data.get("code", "")) == "character_exists":
		return true
	return str(data.get("error", "")).to_lower().contains("already has a character")


## How long to wait for the refresh_character round-trip before giving up (seconds), so a
## stalled /api/character/me request can't pin the create button in "Finalizing..." forever.
const CONFLICT_REFRESH_TIMEOUT_SEC: float = 10.0


## Self-heal the stale 409: re-sync /api/character/me, then either route to the surviving
## character (the account really does have one) or retry the create once (the permadeath
## delete has now committed, so the slot is free). The 404 branch of refresh_character also
## clears the stale local character data so we observe the true server-side state.
func _resolve_create_conflict() -> void:
	create_button.text = "Finalizing..."
	create_button.disabled = true
	is_creating = true

	AuthManager.refresh_character()

	# Race the signal against a timeout so a stalled request can't hang the button forever.
	var timer := get_tree().create_timer(CONFLICT_REFRESH_TIMEOUT_SEC)
	var resolved := {"done": false, "has_character": false}
	var on_refreshed := func(has_character: bool) -> void:
		if resolved["done"]:
			return
		resolved["done"] = true
		resolved["has_character"] = has_character
	AuthManager.character_refreshed.connect(on_refreshed, CONNECT_ONE_SHOT)

	while not resolved["done"] and timer.time_left > 0.0:
		await get_tree().process_frame

	# The user may have left this screen during the round-trip — bail before touching nodes.
	if not is_inside_tree():
		return

	if not resolved["done"]:
		# Timed out: re-enable the create button and surface a connection-style error.
		if AuthManager.character_refreshed.is_connected(on_refreshed):
			AuthManager.character_refreshed.disconnect(on_refreshed)
		is_creating = false
		create_button.disabled = false
		create_button.text = "Create Character"
		print("[CharacterCreation] Conflict resolution timed out")
		_on_create_failed("Network error: Timed out confirming character status")
		return

	if resolved["has_character"]:
		# The account really does have a character — surface a brief note so the typed-name
		# request isn't silently discarded before we route back to the menu.
		print("[CharacterCreation] Account already has a character; returning to menu")
		validation_label.text = "You already have a character - returning to menu"
		validation_label.add_theme_color_override("font_color", Color.YELLOW)
		_on_create_successful()
		return

	# DB confirms no character — the permadeath delete committed. Retry the create once.
	# Internal retry: don't re-arm the self-heal (keeps the 409 recovery strictly one-shot).
	print("[CharacterCreation] Conflict cleared (no character server-side); retrying create")
	is_creating = false
	_on_create_pressed(false)


## Handle successful character creation
func _on_create_successful() -> void:
	# Navigate to main menu
	SceneManager.goto_main_menu()


## Handle failed character creation
func _on_create_failed(error: String) -> void:
	# Check if retryable (network error vs validation error)
	var allow_retry := error.to_lower().contains("network") or error.to_lower().contains("request")
	error_dialog.show_error("Character Creation Failed", error, allow_retry)


## Handle back button press: return to the main menu (no logout). The menu shows a
## "Create Character" button when no character exists, so cancelling is non-destructive.
func _on_back_pressed() -> void:
	SceneManager.goto_main_menu()


## Handle error dialog retry
func _on_error_retry() -> void:
	_on_create_pressed()


## Handle error dialog close
func _on_error_closed() -> void:
	name_input.grab_focus()


## Setup button audio for hover and click sounds
func _setup_button_audio() -> void:
	var buttons: Array[Button] = [create_button, back_button]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Allow Enter key to submit from name input
func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		if name_input.has_focus() and not create_button.disabled:
			_on_create_pressed()
