## Minimap - top-right minimap.
##
## Authored as scenes/ui/hud/minimap.tscn. The world backdrop is a STATIC texture of the whole level
## terrain, rendered once by a WorldMapView (scripts/ui/hud/world_map_view.gd) and handed in via
## set_world_map(). Each frame the minimap draws that texture under a world→minimap transform centred
## on the local player (so it pans/follows) — clipped to the frame — then overlays coloured dots from
## groups. No per-frame world rendering: drawing one (clipped) texture + a few dots is cheap.
## Dots: monsters=red, NPCs=green, other players=red+purple border, local player=green marker,
## landmarks (e.g. the Arena Portal)=yellow.
class_name Minimap
extends Control

const MINIMAP_SIZE := 180.0
## Keep dots inside the decorative frame border.
const EDGE_MARGIN := 16.0

const BG_COLOR := Color(0.05, 0.05, 0.07, 0.85)
const MONSTER_COLOR := Color(0.9, 0.2, 0.2)
const NPC_COLOR := Color(0.3, 0.9, 0.4)
## Intentionally the same red as MONSTER_COLOR — remote players are distinguished by the purple border.
const REMOTE_PLAYER_COLOR := Color(0.9, 0.2, 0.2)
const REMOTE_PLAYER_BORDER := Color(0.6, 0.25, 0.95)
const LOCAL_PLAYER_COLOR := Color(0.3, 0.95, 0.4)
const LOCAL_PLAYER_BORDER := Color(1.0, 1.0, 1.0, 0.9)
const LANDMARK_COLOR := Color(1.0, 0.85, 0.2)

## Redraw cadence (Hz). Entity dots only move at the server tick rate and the player sits dead
## centre, so refreshing the pan/dots ~30×/s is smooth enough — no need to scan the entity groups
## and rebuild the draw every render frame (which on a high-refresh display is pure waste).
const REDRAW_HZ := 30.0

## Set by the level (the dot frame-of-reference + the pan centre).
var local_player: Node2D = null

var _map_texture: Texture2D = null
var _map_bounds: Rect2 = Rect2()
var _redraw_accum: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip_contents = true  # the whole-level texture is drawn oversized and clipped to the frame
	# Only scan/redraw while actually on screen (offline modes can hide the minimap).
	visibility_changed.connect(func() -> void: set_process(is_visible_in_tree()))
	set_process(is_visible_in_tree())


## Hand in the static whole-level terrain texture and the world bounds it covers.
func set_world_map(texture: Texture2D, bounds: Rect2) -> void:
	_map_texture = texture
	_map_bounds = bounds
	queue_redraw()


func _process(delta: float) -> void:
	_redraw_accum += delta
	if _redraw_accum < 1.0 / REDRAW_HZ:
		return
	_redraw_accum = 0.0
	queue_redraw()


func _draw() -> void:
	var rect := Rect2(Vector2.ZERO, Vector2(MINIMAP_SIZE, MINIMAP_SIZE))
	draw_rect(rect, BG_COLOR, true)

	if local_player == null or not is_instance_valid(local_player):
		return

	var player_world: Vector2 = local_player.global_position
	var zoom := GameConstants.MINIMAP_ZOOM
	var mc := rect.size * 0.5

	# Draw the whole static map texture under the world→minimap transform (clipped to the frame):
	# a world point W maps to mc + (W - player_world) * zoom, so the player sits at the centre.
	if _map_texture != null and _map_bounds.size.x > 0.0 and _map_bounds.size.y > 0.0:
		var dest_pos := mc + (_map_bounds.position - player_world) * zoom
		draw_texture_rect(_map_texture, Rect2(dest_pos, _map_bounds.size * zoom), false)

	var max_r := MINIMAP_SIZE * 0.5 - EDGE_MARGIN
	_draw_dots("minimap_monster", player_world, zoom, mc, max_r, MONSTER_COLOR, 3.0, false, Color(0, 0, 0, 0))
	_draw_dots("minimap_npc", player_world, zoom, mc, max_r, NPC_COLOR, 3.0, false, Color(0, 0, 0, 0))
	# Remote players hide while stealthed (same as their world sprite) — a minimap dot would leak
	# an invisible player's position.
	_draw_dots("minimap_player_remote", player_world, zoom, mc, max_r, REMOTE_PLAYER_COLOR, 3.0, false, REMOTE_PLAYER_BORDER, true)
	# Landmarks clamp to the rim so they stay findable when off the visible window.
	_draw_dots("minimap_landmark", player_world, zoom, mc, max_r, LANDMARK_COLOR, 3.5, true, Color(0, 0, 0, 0))
	# Draw the local player last so it sits on top.
	_draw_dots("minimap_player_local", player_world, zoom, mc, max_r, LOCAL_PLAYER_COLOR, 4.0, false, LOCAL_PLAYER_BORDER)


func _draw_dots(group: String, center_world: Vector2, zoom: float, mc: Vector2, max_r: float,
		color: Color, radius: float, clamp_to_edge: bool, border: Color, hide_stealthed: bool = false) -> void:
	for node in get_tree().get_nodes_in_group(group):
		if not (node is Node2D) or not is_instance_valid(node):
			continue
		if hide_stealthed and node is RemotePlayer and (node as RemotePlayer).is_stealthed():
			continue
		var p := mc + ((node as Node2D).global_position - center_world) * zoom
		var off := p - mc
		if off.length() > max_r:
			if clamp_to_edge:
				p = mc + off.normalized() * max_r
			else:
				continue
		if border.a > 0.0:
			draw_circle(p, radius + 1.5, border)
		draw_circle(p, radius, color)
