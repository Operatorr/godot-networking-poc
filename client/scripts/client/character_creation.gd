## CharacterCreation - Handles new character creation flow
## Validates name and creates character via API
extends Control

const MenuFontHelper := preload("res://scripts/client/ui/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/client/ui/menu_button_helper.gd")

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

## HTTP request for character creation
var http_request: HTTPRequest


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


## Handle create button press
func _on_create_pressed() -> void:
	if is_creating:
		return

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


## Create character via API
func _create_character(character_name: String) -> void:
	var url := AuthManager.api_base_url + "/api/character/create"
	var headers := [
		"Content-Type: application/json",
		AuthManager.get_auth_header()
	]
	var body := JSON.stringify({"name": character_name})

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

		# Update GameManager with character data
		GameManager.set_player_data({
			"character_name": character_name,
			"character_id": character_id
		})

		print("[CharacterCreation] Character created successfully: %s" % character_name)
		_on_create_successful()
	else:
		# Error response
		var error_message: String = "Character creation failed"
		if json.data is Dictionary:
			error_message = json.data.get("error", error_message)
		print("[CharacterCreation] Creation failed: %s" % error_message)
		_on_create_failed(error_message)


## Handle successful character creation
func _on_create_successful() -> void:
	# Navigate to main menu
	SceneManager.goto_main_menu()


## Handle failed character creation
func _on_create_failed(error: String) -> void:
	# Check if retryable (network error vs validation error)
	var allow_retry := error.to_lower().contains("network") or error.to_lower().contains("request")
	error_dialog.show_error("Character Creation Failed", error, allow_retry)


## Handle back button press
func _on_back_pressed() -> void:
	# Go back to login (logout first)
	AuthManager.logout()


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
