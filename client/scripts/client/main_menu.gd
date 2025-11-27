## MainMenu - Client main menu with server connection UI
## Handles WebSocket connection to game server via NetworkManager
extends Control

## UI Node references
@onready var server_address_input: LineEdit = $CenterContainer/VBoxContainer/ServerAddressContainer/ServerAddressInput
@onready var connect_button: Button = $CenterContainer/VBoxContainer/ConnectButton
@onready var status_label: Label = $CenterContainer/VBoxContainer/StatusLabel
@onready var quit_button: Button = $CenterContainer/VBoxContainer/QuitButton

## Track if we're currently connected
var is_connected: bool = false


func _ready() -> void:
	# Connect UI signals
	connect_button.pressed.connect(_on_connect_pressed)
	quit_button.pressed.connect(_on_quit_pressed)

	# Connect NetworkManager signals
	NetworkManager.connected_to_server.connect(_on_connected)
	NetworkManager.disconnected_from_server.connect(_on_disconnected)
	NetworkManager.connection_error.connect(_on_connection_error)

	# Set default server address
	server_address_input.text = "ws://localhost:8080"
	_update_status("Disconnected")

	# Notify GameManager we're in main menu
	GameManager.change_state(GameManager.GameState.MAIN_MENU)


func _on_connect_pressed() -> void:
	if is_connected:
		# Disconnect if already connected
		NetworkManager.disconnect_from_server("User disconnect")
		return

	var url = server_address_input.text.strip_edges()
	if url.is_empty():
		_update_status("Please enter a server address")
		return

	connect_button.disabled = true
	_update_status("Connecting...")
	NetworkManager.connect_to_server(url)


func _on_connected() -> void:
	is_connected = true
	_update_status("Connected!")
	connect_button.text = "Disconnect"
	connect_button.disabled = false

	# Transition to loading/arena after brief delay
	await get_tree().create_timer(0.5).timeout
	GameManager.change_state(GameManager.GameState.LOADING)


func _on_disconnected(reason: String) -> void:
	is_connected = false
	_update_status("Disconnected: " + reason)
	connect_button.text = "Connect to Server"
	connect_button.disabled = false


func _on_connection_error(error: String) -> void:
	is_connected = false
	_update_status("Error: " + error)
	connect_button.text = "Connect to Server"
	connect_button.disabled = false


func _on_quit_pressed() -> void:
	get_tree().quit()


func _update_status(text: String) -> void:
	status_label.text = text
