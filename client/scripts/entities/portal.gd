## Portal - reusable level/scene-switch trigger.
##
## One scene serves every travel point in the game: Sanctuary -> Arena today,
## world entrances and dungeon entry/exit later. Walk into the ring and press
## `interact` to travel. Destinations route through SceneManager; CUSTOM_SCENE
## switches to an arbitrary .tscn path for content that has no SceneName.
##
## A destination may require a live server connection (ARENA): the portal then
## dials the region the main menu stashed in
## GameManager.player_data["selected_region_url"] and only switches scenes once
## NetworkManager reports the link is open. Connection progress and failures
## are shown on the portal's own prompt label.
class_name Portal
extends Area2D

signal activated(portal: Portal)

enum Destination { ARENA, SANCTUARY, MAIN_MENU, PRACTICE, CUSTOM_SCENE }

const CONNECT_TIMEOUT_SEC := 10.0
const ERROR_PROMPT_SEC := 2.5

## Visual placeholder palette (style guide: Soft Teal / Sun Gold / Cloud White).
const RING_COLOR := Color("e7a93c")
const GLOW_COLOR := Color("62c9c1")
const CORE_COLOR := Color(0.95, 0.99, 0.98, 0.85)

@export var portal_name: String = "Portal"
@export var destination: Destination = Destination.ARENA
## Only used when destination == CUSTOM_SCENE.
@export_file("*.tscn") var custom_scene_path: String = ""
## Dial the game server before switching (online destinations like the Arena).
@export var requires_connection: bool = false
@export var use_loading_screen: bool = true
## Sprite texture; the drawn placeholder ring is used while this is missing.
@export var texture_path: String = ""
## Optional horizontal spritesheet strip; preferred over texture_path.
@export var animation_sheet_path: String = ""
@export var animation_frames: int = 9
@export var animation_fps: float = 8.0

var _player_inside := false
var _busy := false
var _has_visual := false

@onready var _sprite: Sprite2D = $Sprite2D
@onready var _name_label: Label = $NameLabel
@onready var _prompt_label: Label = $PromptLabel


func _ready() -> void:
	add_to_group("minimap_landmark")  # yellow dot on the minimap (e.g. the Arena Portal)
	_name_label.text = portal_name
	_prompt_label.visible = false
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)

	if not animation_sheet_path.is_empty() and ResourceLoader.exists(animation_sheet_path):
		var animated := AnimatedSprite2D.new()
		animated.sprite_frames = SpriteStrip.make_frames(load(animation_sheet_path), animation_frames, animation_fps)
		animated.play("idle")
		add_child(animated)
		_has_visual = true
	elif not texture_path.is_empty() and ResourceLoader.exists(texture_path):
		_sprite.texture = load(texture_path)
		_has_visual = true
	else:
		queue_redraw()


func _draw() -> void:
	if _has_visual:
		return
	draw_circle(Vector2.ZERO, 44.0, GLOW_COLOR * Color(1, 1, 1, 0.35))
	draw_circle(Vector2.ZERO, 34.0, GLOW_COLOR)
	draw_circle(Vector2.ZERO, 18.0, CORE_COLOR)
	draw_arc(Vector2.ZERO, 44.0, 0.0, TAU, 48, RING_COLOR, 4.0)


func _unhandled_input(event: InputEvent) -> void:
	if not _player_inside or _busy:
		return
	if event.is_action_pressed("interact"):
		get_viewport().set_input_as_handled()
		_activate()


func _on_body_entered(body: Node2D) -> void:
	if body is Player:
		_player_inside = true
		_show_default_prompt()


func _on_body_exited(body: Node2D) -> void:
	if body is Player:
		_player_inside = false
		_prompt_label.visible = false


func _activate() -> void:
	if _busy:
		return
	_busy = true
	activated.emit(self)

	if requires_connection:
		# Each destination lives on its own server instance (Arena = region:8081, Sanctuary =
		# region:8082). Always (re)connect to the destination's instance so traveling from the
		# connected Sanctuary into the Arena lands on the Arena server, not the Sanctuary one.
		var connected: bool = await _connect_to_destination_instance()
		if not connected:
			_busy = false
			if _player_inside:
				_show_default_prompt()
			return

	_travel()


## Route to the destination scene. The portal only moves the local client;
## everything gameplay-authoritative still happens server-side after arrival.
func _travel() -> void:
	match destination:
		Destination.ARENA:
			SceneManager.goto_arena()
		Destination.SANCTUARY:
			SceneManager.goto_sanctuary()
		Destination.MAIN_MENU:
			SceneManager.goto_main_menu()
		Destination.PRACTICE:
			SceneManager.goto_practice()
		Destination.CUSTOM_SCENE:
			if custom_scene_path.is_empty():
				push_error("[Portal] %s: CUSTOM_SCENE destination without custom_scene_path" % portal_name)
				_busy = false
				return
			SceneManager.change_scene_to_path(custom_scene_path, use_loading_screen)


## Resolve this destination's server-instance address from the region the main menu stashed.
## Arena → region host:8081; Sanctuary → region host:8082. Empty when no region is selected.
func _destination_instance_url() -> String:
	var region_url: String = GameManager.player_data.get("selected_region_url", "")
	if region_url.is_empty():
		return ""
	match destination:
		Destination.SANCTUARY:
			return NetworkManager.sanctuary_url_for_region(region_url)
		_:
			# ARENA (and any other online destination) uses the region's advertised instance.
			return NetworkManager.arena_url_for_region(region_url)


## Dial the destination's server instance. Disconnects from any current instance first so a
## different one (e.g. leaving the Sanctuary for the Arena) is left cleanly. Returns true once
## connected.
func _connect_to_destination_instance() -> bool:
	var url := _destination_instance_url()
	if url.is_empty():
		await _show_error_prompt("No realm selected - pick a region in the main menu")
		return false

	# Drop the current link (e.g. the Sanctuary) before dialing the destination instance.
	if NetworkManager.is_server_connected():
		NetworkManager.disconnect_from_server("Portal travel")
		await get_tree().process_frame

	_set_prompt("Connecting to realm...")
	NetworkManager.connect_to_server(url, AuthManager.get_token())

	var state := {"done": false, "ok": false, "reason": ""}
	var on_connected := func() -> void:
		state["done"] = true
		state["ok"] = true
	var on_error := func(error: String) -> void:
		state["done"] = true
		state["reason"] = error
	var on_disconnected := func(reason: String) -> void:
		state["done"] = true
		state["reason"] = reason

	NetworkManager.connected_to_server.connect(on_connected)
	NetworkManager.connection_error.connect(on_error)
	NetworkManager.disconnected_from_server.connect(on_disconnected)

	var waited := 0.0
	while not state["done"] and waited < CONNECT_TIMEOUT_SEC:
		await get_tree().process_frame
		# If the portal was freed mid-await, tear the signal connections down so the
		# captured lambdas can't fire on a freed node, then bail. Disconnect inline here
		# (NetworkManager is a persistent autoload) — don't call a method on freed self.
		if not is_instance_valid(self):
			if NetworkManager.connected_to_server.is_connected(on_connected):
				NetworkManager.connected_to_server.disconnect(on_connected)
			if NetworkManager.connection_error.is_connected(on_error):
				NetworkManager.connection_error.disconnect(on_error)
			if NetworkManager.disconnected_from_server.is_connected(on_disconnected):
				NetworkManager.disconnected_from_server.disconnect(on_disconnected)
			return false
		waited += get_process_delta_time()

	_disconnect_connection_handlers(on_connected, on_error, on_disconnected)

	if state["ok"]:
		_set_prompt("Connected!")
		return true

	var reason: String = state["reason"]
	if reason.is_empty():
		reason = "Connection timed out"
	await _show_error_prompt(reason)
	return false


## Disconnect the transient connection-result handlers, tolerating an already-removed
## connection (e.g. NetworkManager re-emitted/disconnected) so early exit stays safe.
func _disconnect_connection_handlers(on_connected: Callable, on_error: Callable, on_disconnected: Callable) -> void:
	if NetworkManager.connected_to_server.is_connected(on_connected):
		NetworkManager.connected_to_server.disconnect(on_connected)
	if NetworkManager.connection_error.is_connected(on_error):
		NetworkManager.connection_error.disconnect(on_error)
	if NetworkManager.disconnected_from_server.is_connected(on_disconnected):
		NetworkManager.disconnected_from_server.disconnect(on_disconnected)


func _show_default_prompt() -> void:
	_set_prompt("Press %s to enter" % _interact_key_name())


func _set_prompt(text: String) -> void:
	_prompt_label.text = text
	_prompt_label.visible = true


func _show_error_prompt(text: String) -> void:
	_set_prompt(text)
	await get_tree().create_timer(ERROR_PROMPT_SEC).timeout
	if _player_inside:
		_show_default_prompt()
	else:
		_prompt_label.visible = false


func _interact_key_name() -> String:
	for event: InputEvent in InputMap.action_get_events("interact"):
		if event is InputEventKey:
			var key: Key = event.physical_keycode if event.physical_keycode != KEY_NONE else event.keycode
			return OS.get_keycode_string(key)
	return "E"
