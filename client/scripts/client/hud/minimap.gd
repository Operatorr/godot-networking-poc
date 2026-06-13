## MinimapControl - Top-right minimap showing entity positions
## Uses _draw() for manual rendering of arena, players, and monsters
extends Control


const MINIMAP_SIZE := 180.0
const MAP_PADDING := 18.0
const VISION_RADIUS := 500.0
const BG_COLOR := Color(0.1, 0.1, 0.12, 0.8)
const SELF_COLOR := Color(0.2, 0.9, 0.3)
const PLAYER_COLOR := Color(0.9, 0.2, 0.2)
const MONSTER_COLOR := Color(0.9, 0.6, 0.1)
const OBSTACLE_COLOR := Color(0.25, 0.1, 0.15, 0.8)
const FRAME_TEXTURE := preload("res://assets/ui/hud/player_minimap_frame.png")

## References set by arena_base
var interpolation_controller: Node = null
var local_player: Node2D = null

var _arena_min: Vector2 = GameConstants.MAP_MIN
var _arena_max: Vector2 = GameConstants.MAP_MAX
var _frame: TextureRect = null


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

	_frame = TextureRect.new()
	_frame.texture = FRAME_TEXTURE
	_frame.position = Vector2.ZERO
	_frame.size = Vector2(MINIMAP_SIZE, MINIMAP_SIZE)
	_frame.stretch_mode = TextureRect.STRETCH_SCALE
	_frame.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_frame)


func _process(_delta: float) -> void:
	queue_redraw()


func _draw() -> void:
	var map_rect := _get_map_rect()

	# Background
	draw_rect(map_rect, BG_COLOR, true)

	# Draw obstacles
	for obs: Rect2 in GameConstants.ARENA_OBSTACLES:
		var map_pos := _world_to_minimap(obs.position)
		var arena_size := _arena_max - _arena_min
		var map_size := obs.size / arena_size * map_rect.size
		draw_rect(Rect2(map_pos, map_size), OBSTACLE_COLOR, true)

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
	return _get_map_rect().position + normalized * _get_map_rect().size


func _get_map_rect() -> Rect2:
	var padding := Vector2(MAP_PADDING, MAP_PADDING)
	return Rect2(padding, Vector2(MINIMAP_SIZE, MINIMAP_SIZE) - padding * 2.0)
