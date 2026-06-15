## MapOverlay - fullscreen, semi-transparent Diablo-style map. Toggled with the "toggle_map" action (M).
##
## Authored as scenes/ui/hud/map_overlay.tscn. Shows the STATIC whole-level terrain texture (rendered
## once by WorldMapView, handed in via set_world_map()) aspect-fit into a centred panel, with the
## group dots mapped onto it. Non-blocking: the game keeps running while it's open (mouse_filter
## IGNORE). There is no per-frame world rendering — opening the map costs one texture blit + dots.
class_name MapOverlay
extends Control

## Map panel as a fraction of the screen's shorter side.
const MAP_FRACTION := 0.82

const BG_DIM := Color(0, 0, 0, 0.45)
const MAP_FRAME := Color(0.6, 0.55, 0.42, 0.5)
const EMPTY_BG := Color(0.05, 0.05, 0.07, 0.85)
const MONSTER_COLOR := Color(0.9, 0.2, 0.2)
const NPC_COLOR := Color(0.3, 0.9, 0.4)
const REMOTE_PLAYER_COLOR := Color(0.9, 0.2, 0.2)
const REMOTE_PLAYER_BORDER := Color(0.6, 0.25, 0.95)
const LOCAL_PLAYER_COLOR := Color(0.3, 0.95, 0.4)
const LOCAL_PLAYER_BORDER := Color(1, 1, 1, 0.9)
const LANDMARK_COLOR := Color(1.0, 0.85, 0.2)

var local_player: Node2D = null

var _map_texture: Texture2D = null
var _map_bounds: Rect2 = Rect2()


func _ready() -> void:
	visible = false
	mouse_filter = Control.MOUSE_FILTER_IGNORE  # non-blocking; the game keeps running
	set_process(false)


## Hand in the static whole-level terrain texture and the world bounds it covers.
func set_world_map(texture: Texture2D, bounds: Rect2) -> void:
	_map_texture = texture
	_map_bounds = bounds
	queue_redraw()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_map"):
		toggle()
		get_viewport().set_input_as_handled()


func toggle() -> void:
	set_open(not visible)


func set_open(open: bool) -> void:
	visible = open
	set_process(open)
	queue_redraw()


func _process(_delta: float) -> void:
	queue_redraw()


## The centred panel the level map is drawn into, aspect-fit to the level's bounds.
func _map_rect() -> Rect2:
	var avail := minf(size.x, size.y) * MAP_FRACTION
	if _map_bounds.size.x <= 0.0 or _map_bounds.size.y <= 0.0:
		return Rect2((size - Vector2(avail, avail)) * 0.5, Vector2(avail, avail))
	var fit := minf(avail / _map_bounds.size.x, avail / _map_bounds.size.y)
	var panel := _map_bounds.size * fit
	return Rect2((size - panel) * 0.5, panel)


func _draw() -> void:
	if not visible:
		return
	draw_rect(Rect2(Vector2.ZERO, size), BG_DIM, true)

	var rect := _map_rect()
	if _map_texture != null and _map_bounds.size.x > 0.0:
		draw_texture_rect(_map_texture, rect, false, Color(1, 1, 1, 0.9))
	else:
		draw_rect(rect, EMPTY_BG, true)
	draw_rect(rect, MAP_FRAME, false, 2.0)

	if _map_bounds.size.x <= 0.0 or _map_bounds.size.y <= 0.0:
		return

	_draw_dots("minimap_monster", rect, MONSTER_COLOR, 4.0, Color(0, 0, 0, 0))
	_draw_dots("minimap_npc", rect, NPC_COLOR, 4.0, Color(0, 0, 0, 0))
	_draw_dots("minimap_player_remote", rect, REMOTE_PLAYER_COLOR, 4.0, REMOTE_PLAYER_BORDER)
	_draw_dots("minimap_landmark", rect, LANDMARK_COLOR, 5.0, Color(0, 0, 0, 0))
	_draw_dots("minimap_player_local", rect, LOCAL_PLAYER_COLOR, 5.0, LOCAL_PLAYER_BORDER)


## Map a group's members onto the panel by their normalised position within the level bounds.
func _draw_dots(group: String, rect: Rect2, color: Color, radius: float, border: Color) -> void:
	for node in get_tree().get_nodes_in_group(group):
		if not (node is Node2D) or not is_instance_valid(node):
			continue
		var u := ((node as Node2D).global_position - _map_bounds.position) / _map_bounds.size
		var p := rect.position + Vector2(clampf(u.x, 0.0, 1.0), clampf(u.y, 0.0, 1.0)) * rect.size
		if border.a > 0.0:
			draw_circle(p, radius + 1.5, border)
		draw_circle(p, radius, color)
