## MinimapControl - Top-right minimap showing entity positions
## Uses _draw() for manual rendering of arena, players, and monsters
extends Control


const MINIMAP_SIZE := 180.0
const VISION_RADIUS := 500.0
const BG_COLOR := Color(0.1, 0.1, 0.12, 0.8)
const BORDER_COLOR := Color(0.4, 0.4, 0.45, 1.0)
const SELF_COLOR := Color(0.2, 0.9, 0.3)
const PLAYER_COLOR := Color(0.9, 0.2, 0.2)
const MONSTER_COLOR := Color(0.9, 0.6, 0.1)

## References set by arena_base
var interpolation_controller: Node = null
var local_player: Node2D = null

var _arena_min: Vector2 = GameConstants.MAP_MIN
var _arena_max: Vector2 = GameConstants.MAP_MAX


func _ready() -> void:
	# Position top-right
	anchor_left = 1.0
	anchor_right = 1.0
	anchor_top = 0.0
	anchor_bottom = 0.0
	offset_left = -MINIMAP_SIZE - 20
	offset_right = -20
	offset_top = 20
	offset_bottom = 20 + MINIMAP_SIZE
	custom_minimum_size = Vector2(MINIMAP_SIZE, MINIMAP_SIZE)
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _process(_delta: float) -> void:
	queue_redraw()


func _draw() -> void:
	# Background
	draw_rect(Rect2(Vector2.ZERO, Vector2(MINIMAP_SIZE, MINIMAP_SIZE)), BG_COLOR, true)

	# Border
	draw_rect(Rect2(Vector2.ZERO, Vector2(MINIMAP_SIZE, MINIMAP_SIZE)), BORDER_COLOR, false, 2.0)

	if local_player == null or not is_instance_valid(local_player):
		return

	var player_pos := local_player.position

	# Draw self (green dot, always center-ish based on world pos)
	var self_map_pos := _world_to_minimap(player_pos)
	draw_circle(self_map_pos, 4.0, SELF_COLOR)

	if interpolation_controller == null:
		return

	# Draw other entities from interpolation controller
	var entities: Dictionary = interpolation_controller.entity_last_states
	for entity_id: int in entities:
		var entity_data: Dictionary = entities[entity_id]
		var pos: Vector2 = entity_data.get("position", Vector2.ZERO)
		var entity_type: int = entity_data.get("entity_type", 0)

		# Skip if too far
		if pos.distance_to(player_pos) > VISION_RADIUS:
			continue

		# Skip local player (already drawn)
		if entity_id == GameManager.get_local_player_entity_id():
			continue

		var map_pos := _world_to_minimap(pos)

		match entity_type:
			PacketTypes.EntityType.PLAYER:
				draw_circle(map_pos, 3.0, PLAYER_COLOR)
			PacketTypes.EntityType.MONSTER:
				draw_circle(map_pos, 3.0, MONSTER_COLOR)


func _world_to_minimap(world_pos: Vector2) -> Vector2:
	var arena_size := _arena_max - _arena_min
	var normalized := (world_pos - _arena_min) / arena_size
	return normalized * MINIMAP_SIZE
