## LoginScreen - Handles user authentication flow
## Connects to AuthManager for JWT-based login
extends Control

const TestConfigScript := preload("res://scripts/shared/test_config.gd")
const MENU_BACKGROUND_PATH := "res://assets/ui/backgrounds/menu_background.png"

## External URLs for registration and password recovery
@export var registration_url: String = "https://example.com/register"
@export var forgot_password_url: String = "https://example.com/forgot-password"
@export var prefill_test_credentials_from_env: bool = false

## UI node references
@onready var menu_background: TextureRect = $MenuBackground
@onready var username_input: LineEdit = $CenterContainer/VBoxContainer/UsernameInput
@onready var password_input: LineEdit = $CenterContainer/VBoxContainer/PasswordInput
@onready var login_button: Button = $CenterContainer/VBoxContainer/LoginButton
@onready var create_account_button: Button = $CenterContainer/VBoxContainer/CreateAccountButton
@onready var forgot_password_button: Button = $CenterContainer/VBoxContainer/ForgotPasswordButton
@onready var error_dialog: PopupPanel = $ErrorDialog

## Track login state to prevent duplicate requests
var is_logging_in: bool = false


func _ready() -> void:
	# Apply the same menu theme used by the post-login menu.
	_apply_dark_theme()

	# Connect UI signals
	login_button.pressed.connect(_on_login_pressed)
	create_account_button.pressed.connect(_on_create_account_pressed)
	forgot_password_button.pressed.connect(_on_forgot_password_pressed)

	# Connect AuthManager signals
	AuthManager.login_successful.connect(_on_login_successful)
	AuthManager.login_failed.connect(_on_login_failed)

	# Connect ErrorDialog signals
	error_dialog.retry_pressed.connect(_on_error_retry)
	error_dialog.closed.connect(_on_error_closed)

	# Setup focus navigation
	_setup_focus_navigation()

	# Prefill local test credentials when enabled for debug/editor runs.
	_prefill_test_credentials()

	# Setup button audio
	_setup_button_audio()

	# Start background music
	AudioManager.play_music("menu_bgm")

	# Check for auto-login with saved token
	_check_auto_login()

	# Set initial focus
	username_input.grab_focus()

	print("[LoginScreen] Ready")


## Apply dark cosmic horror theme to login elements
func _apply_dark_theme() -> void:
	# Keep the shared menu background non-interactive and full screen.
	if menu_background:
		var background_texture := load(MENU_BACKGROUND_PATH) as Texture2D
		if background_texture:
			menu_background.texture = background_texture
		else:
			push_warning("[LoginScreen] Failed to load menu background: %s" % MENU_BACKGROUND_PATH)
		menu_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
		menu_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		menu_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		menu_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED

	# Style title
	var title_label: Label = $CenterContainer/VBoxContainer/TitleLabel
	if title_label:
		title_label.add_theme_color_override("font_color", Color(0.27, 0.53, 1.0))

	# Style subtitle
	var subtitle_label: Label = $CenterContainer/VBoxContainer/SubtitleLabel
	if subtitle_label:
		subtitle_label.add_theme_color_override("font_color", Color(0.4, 1.0, 0.8, 0.7))


## Setup Tab navigation between inputs
func _setup_focus_navigation() -> void:
	# Username -> Password -> Login button cycle
	username_input.focus_neighbor_bottom = password_input.get_path()
	username_input.focus_next = password_input.get_path()

	password_input.focus_neighbor_top = username_input.get_path()
	password_input.focus_neighbor_bottom = login_button.get_path()
	password_input.focus_next = login_button.get_path()
	password_input.focus_previous = username_input.get_path()

	login_button.focus_neighbor_top = password_input.get_path()
	login_button.focus_previous = password_input.get_path()


## Check if user has saved valid token for auto-login
func _check_auto_login() -> void:
	if AuthManager.is_logged_in():
		print("[LoginScreen] Valid token found, checking character state...")
		# User is already logged in, navigate accordingly
		_navigate_after_login()


## Prefill credentials from .env.test for local development only.
func _prefill_test_credentials() -> void:
	if not prefill_test_credentials_from_env:
		return

	if not OS.has_feature("debug") and not OS.has_feature("editor"):
		return

	if not username_input.text.is_empty() or not password_input.text.is_empty():
		return

	var config: TestConfigScript = TestConfigScript.new()
	if not config.load_config() or not config.is_valid():
		return

	username_input.text = config.username
	password_input.text = config.password
	print("[LoginScreen] Prefilled test credentials for user: %s" % config.username)


## Handle login button press
func _on_login_pressed() -> void:
	if is_logging_in:
		return

	var username := username_input.text.strip_edges()
	var password := password_input.text

	# Basic validation
	if username.is_empty():
		_show_error("Validation Error", "Please enter your username.")
		username_input.grab_focus()
		return

	if password.is_empty():
		_show_error("Validation Error", "Please enter your password.")
		password_input.grab_focus()
		return

	# Disable login button and start login
	is_logging_in = true
	login_button.disabled = true
	login_button.text = "Logging in..."

	print("[LoginScreen] Attempting login for user: %s" % username)
	AuthManager.login(username, password)


## Handle successful login
func _on_login_successful(user_data: Dictionary) -> void:
	print("[LoginScreen] Login successful for user: %s" % user_data.get("username", "unknown"))
	is_logging_in = false
	login_button.disabled = false
	login_button.text = "Login"

	_navigate_after_login()


## Navigate to appropriate screen after successful login
func _navigate_after_login() -> void:
	# Check if user has a character
	if GameManager.has_character():
		print("[LoginScreen] User has character, navigating to main menu")
		SceneManager.goto_main_menu()
	else:
		print("[LoginScreen] User has no character, navigating to character creation")
		SceneManager.goto_character_creation()


## Handle login failure
func _on_login_failed(error: String) -> void:
	print("[LoginScreen] Login failed: %s" % error)
	is_logging_in = false
	login_button.disabled = false
	login_button.text = "Login"

	# Determine if error is retryable (API unreachable)
	var allow_retry := _is_network_error(error)
	_show_error("Login Failed", error, allow_retry)


## Check if error is a network/connection error
func _is_network_error(error: String) -> bool:
	var network_indicators := ["Network error", "Request failed", "Connection", "Timeout", "Cannot reach", "Cannot find", "did not respond"]
	for indicator in network_indicators:
		if error.to_lower().contains(indicator.to_lower()):
			return true
	return false


## Show error dialog
func _show_error(title: String, message: String, allow_retry: bool = false) -> void:
	error_dialog.show_error(title, message, allow_retry)


## Handle error dialog retry
func _on_error_retry() -> void:
	# Retry login with same credentials
	if not username_input.text.is_empty() and not password_input.text.is_empty():
		_on_login_pressed()


## Handle error dialog close
func _on_error_closed() -> void:
	# Focus back on username field
	username_input.grab_focus()


## Handle create account button - opens external URL
func _on_create_account_pressed() -> void:
	print("[LoginScreen] Opening registration URL: %s" % registration_url)
	var err := OS.shell_open(registration_url)
	if err != OK:
		push_warning("[LoginScreen] Failed to open registration URL: %d" % err)


## Handle forgot password button - opens external URL
func _on_forgot_password_pressed() -> void:
	print("[LoginScreen] Opening forgot password URL: %s" % forgot_password_url)
	var err := OS.shell_open(forgot_password_url)
	if err != OK:
		push_warning("[LoginScreen] Failed to open forgot password URL: %d" % err)


## Setup button audio for hover and click sounds
func _setup_button_audio() -> void:
	var buttons: Array[Button] = [login_button, create_account_button, forgot_password_button]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Allow Enter key to submit login from password field
func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		if password_input.has_focus():
			_on_login_pressed()
