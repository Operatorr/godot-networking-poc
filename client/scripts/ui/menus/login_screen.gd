## LoginScreen - Handles user authentication flow
## Connects to AuthManager for JWT-based login
extends Control

const TestConfigScript := preload("res://scripts/utils/test_config.gd")
const MenuFontHelper := preload("res://scripts/ui/helpers/menu_font_helper.gd")
const MenuButtonHelper := preload("res://scripts/ui/helpers/menu_button_helper.gd")
const MENU_BACKGROUND_PATH := "res://assets/ui/backgrounds/menu_background_004.jpg"
const TITLE_FONT_PATH := "res://assets/fonts/CormorantUnicase-Bold.ttf"
const TITLE_COLOR := Color(0.85, 0.82, 0.74)
const TITLE_OUTLINE_COLOR := Color.BLACK
const TITLE_GLOW_COLOR := Color(0.22, 0.13, 0.07, 0.4)

## External URLs for registration and password recovery
@export var registration_url: String = "https://example.com/register"
@export var forgot_password_url: String = "https://example.com/forgot-password"
@export var prefill_test_credentials_from_env: bool = false

## UI node references
@onready var menu_background: Control = $MenuBackground
@onready var username_input: LineEdit = $CenterContainer/VBoxContainer/UsernameInput
@onready var password_input: LineEdit = $CenterContainer/VBoxContainer/PasswordInput
@onready var login_button: Button = $CenterContainer/VBoxContainer/LoginButton
@onready var create_account_button: Button = $CenterContainer/VBoxContainer/CreateAccountButton
@onready var forgot_password_button: Button = $CenterContainer/VBoxContainer/ForgotPasswordButton
@onready var settings_button: Button = $CenterContainer/VBoxContainer/SettingsButton
@onready var local_server_check: CheckButton = $CenterContainer/VBoxContainer/LocalServerCheck
@onready var exit_button: Button = $CenterContainer/VBoxContainer/ExitButton
@onready var error_dialog: PopupPanel = $ErrorDialog

## Track login state to prevent duplicate requests
var is_logging_in: bool = false


func _ready() -> void:
	# Apply the same menu theme used by the post-login menu.
	_apply_dark_theme()
	MenuFontHelper.apply_to_tree(self)

	# Connect UI signals
	login_button.pressed.connect(_on_login_pressed)
	create_account_button.pressed.connect(_on_create_account_pressed)
	forgot_password_button.pressed.connect(_on_forgot_password_pressed)
	settings_button.pressed.connect(_on_settings_pressed)

	# API target toggle: reflect the current resolved target, then switch + persist on change.
	local_server_check.button_pressed = AuthManager.is_using_local_api()
	local_server_check.toggled.connect(_on_local_server_toggled)

	# Quit the game from the login screen, mirroring the main menu's Exit button.
	exit_button.pressed.connect(_on_exit_pressed)

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
		menu_background.mouse_filter = Control.MOUSE_FILTER_IGNORE
		menu_background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)

		if menu_background is TextureRect:
			var texture_background := menu_background as TextureRect
			var background_texture := load(MENU_BACKGROUND_PATH) as Texture2D
			if background_texture:
				texture_background.texture = background_texture
			else:
				push_warning("[LoginScreen] Failed to load menu background: %s" % MENU_BACKGROUND_PATH)
			texture_background.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
			texture_background.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
		elif menu_background is VideoStreamPlayer:
			var video_background := menu_background as VideoStreamPlayer
			video_background.expand = true
			video_background.loop = true
			if video_background.stream != null and not video_background.is_playing():
				video_background.play()
		else:
			push_warning("[LoginScreen] Unsupported MenuBackground node type: %s" % menu_background.get_class())

	# Style title
	var title_label: Label = $CenterContainer/VBoxContainer/TitleLabel
	if title_label:
		var title_font := load(TITLE_FONT_PATH) as FontFile
		if title_font:
			title_label.add_theme_font_override("font", title_font)
		else:
			push_warning("[LoginScreen] Failed to load title font: %s" % TITLE_FONT_PATH)

		title_label.text = "OMEGA REALM"
		title_label.add_theme_color_override("font_color", TITLE_COLOR)
		title_label.add_theme_color_override("font_outline_color", TITLE_OUTLINE_COLOR)
		title_label.add_theme_color_override("font_shadow_color", TITLE_GLOW_COLOR)
		title_label.add_theme_constant_override("outline_size", 2)
		title_label.add_theme_constant_override("shadow_offset_x", 0)
		title_label.add_theme_constant_override("shadow_offset_y", 0)
		title_label.add_theme_constant_override("shadow_outline_size", 2)
		title_label.add_theme_font_size_override("font_size", 56)

	# Style subtitle
	var subtitle_label: Label = $CenterContainer/VBoxContainer/SubtitleLabel
	if subtitle_label:
		subtitle_label.add_theme_color_override("font_color", Color.WHITE)

	_apply_pixel_button_theme()


## Shared native button states, sizing and focus treatment.
func _apply_pixel_button_theme() -> void:
	MenuButtonHelper.apply_to_buttons([login_button, create_account_button, forgot_password_button, settings_button, exit_button])
	login_button.theme_type_variation = &"PrimaryButton"


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


## Switch the auth/account API between the local Go server and production, persisting the choice.
## A logged-in session is tied to the old server, so log out to force re-auth against the new one.
func _on_local_server_toggled(pressed: bool) -> void:
	AuthManager.set_use_local_api(pressed)
	if AuthManager.is_logged_in():
		AuthManager.logout()


## Handle exit button press
func _on_exit_pressed() -> void:
	print("[LoginScreen] Exiting game")
	get_tree().quit()


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


## Navigate after successful login. Always lands on the main menu now — the menu shows a
## "Create Character" button in place of the character card when no character exists.
func _navigate_after_login() -> void:
	print("[LoginScreen] Login complete, navigating to main menu")
	SceneManager.goto_main_menu()


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


## Open the standalone Settings screen (Audio / Video / Controls). Pass LOGIN so the Settings
## Back button returns here, not the authenticated main menu (a pre-login screen must not be a
## back-door into the post-login menu).
func _on_settings_pressed() -> void:
	SceneManager.goto_settings(SceneManager.SceneName.LOGIN)


## Setup button audio for hover and click sounds
func _setup_button_audio() -> void:
	var buttons: Array[Button] = [login_button, create_account_button, forgot_password_button, settings_button, exit_button]
	for button in buttons:
		button.mouse_entered.connect(func(): AudioManager.play_button_hover())
		button.pressed.connect(func(): AudioManager.play_button_click())


## Allow Enter key to submit login from password field
func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		if password_input.has_focus():
			_on_login_pressed()
