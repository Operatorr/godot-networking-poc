## EntityNameCache - Client-side entity name resolution singleton
## Maps entity IDs to character names for display purposes
## Auto-populates from PLAYER_INFO game events received from server
extends Node

## Entity ID to character name mapping
var entity_names: Dictionary = {}  # entity_id (int) -> character_name (String)
## Entity ID to player color mapping
var entity_colors: Dictionary = {}  # entity_id (int) -> Color

signal entity_color_updated(entity_id: int, player_color: Color)

## Runtime mode detection
var _is_server: bool = false


func _ready() -> void:
	_is_server = OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"

	if not _is_server:
		_connect_to_network_manager()


## Connect to NetworkManager to receive PLAYER_INFO events
func _connect_to_network_manager() -> void:
	var network_manager = get_tree().root.get_node_or_null("NetworkManager")
	if network_manager == null:
		# NetworkManager may load after us; retry next frame
		await get_tree().process_frame
		network_manager = get_tree().root.get_node_or_null("NetworkManager")

	if network_manager and network_manager.has_signal("server_message_received"):
		network_manager.server_message_received.connect(_on_server_message)
		print("[EntityNameCache] Connected to NetworkManager for PLAYER_INFO events")


## Handle server messages, filtering for GAME_EVENT with PLAYER_INFO
func _on_server_message(message_type: int, data: Dictionary) -> void:
	# Only handle GAME_EVENT messages
	if message_type != 3:  # NetworkManager.MessageType.GAME_EVENT
		return

	var event_type: int = data.get("event_type", 0)
	if event_type == PacketTypes.GameEventType.PLAYER_INFO:
		var entity_id: int = data.get("target_id", 0)
		var event_data: Dictionary = data.get("event_data", {})
		var character_name: String = event_data.get("character_name", "")
		var player_color: Color = event_data.get("player_color", Color(0.27, 0.53, 1.0))

		if entity_id > 0 and not character_name.is_empty():
			set_entity_name(entity_id, character_name)
			set_entity_color(entity_id, player_color)
			print("[EntityNameCache] Cached: entity %d -> '%s' color=%s" % [entity_id, character_name, player_color])


## Add or update entity name
func set_entity_name(entity_id: int, character_name: String) -> void:
	entity_names[entity_id] = character_name


## Add or update entity color
func set_entity_color(entity_id: int, player_color: Color) -> void:
	player_color.a = 1.0
	entity_colors[entity_id] = player_color
	entity_color_updated.emit(entity_id, player_color)


## Get entity name with fallback
func get_entity_name(entity_id: int) -> String:
	if entity_names.has(entity_id):
		return entity_names[entity_id]
	return "Player_%d" % entity_id


## Get entity color with fallback
func get_entity_color(entity_id: int) -> Color:
	if entity_colors.has(entity_id):
		return entity_colors[entity_id]
	return Color(0.27, 0.53, 1.0)


## Check if an entity name is cached
func has_entity_name(entity_id: int) -> bool:
	return entity_names.has(entity_id)


## Get total cached names count
func get_cached_count() -> int:
	return entity_names.size()


## Clear all cached names
func clear() -> void:
	entity_names.clear()
	entity_colors.clear()


## Remove specific entity name
func remove_entity_name(entity_id: int) -> void:
	entity_names.erase(entity_id)
	entity_colors.erase(entity_id)
