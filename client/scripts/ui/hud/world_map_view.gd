## WorldMapView - renders the level's STATIC terrain ONCE into a texture for the minimap + map.
##
## A SubViewport that frames the WHOLE level (configure() with the level's world bounds), shares the
## main World2D, renders only terrain (canvas_cull_mask = MINIMAP_TERRAIN_BIT), and updates EXACTLY
## ONCE after the terrain has drawn — then goes idle (zero per-frame cost). The HUD minimap pans a
## window of get_texture(); the map overlay shows the whole texture. Terrain never changes after the
## level builds, so a single render is enough — this replaces the old per-frame UPDATE_ALWAYS render
## that re-rasterised the entire (huge) town/arena every frame and tanked FPS.
class_name WorldMapView
extends SubViewport

## Longest texture side in pixels (the other axis follows the level's aspect).
const MAX_RESOLUTION := 2048

@onready var _camera: Camera2D = $Camera


func _ready() -> void:
	# Share the MAIN viewport's 2D world (NB: get_viewport() on a SubViewport returns itself).
	world_2d = get_tree().root.get_world_2d()
	canvas_cull_mask = GameConstants.MINIMAP_TERRAIN_BIT
	render_target_update_mode = SubViewport.UPDATE_DISABLED


## Frame `bounds` (world Rect2) and schedule the one-time render once the terrain has drawn.
func configure(bounds: Rect2) -> void:
	if bounds.size.x <= 0.0 or bounds.size.y <= 0.0:
		return
	# Texture sized to the level's aspect, longest side = MAX_RESOLUTION.
	var longest := maxf(bounds.size.x, bounds.size.y)
	size = Vector2i(
		maxi(1, roundi(MAX_RESOLUTION * bounds.size.x / longest)),
		maxi(1, roundi(MAX_RESOLUTION * bounds.size.y / longest))
	)
	_camera.global_position = bounds.get_center()
	# Camera2D shows viewport_size / zoom world units; we want exactly bounds.size to fill it.
	_camera.zoom = Vector2(float(size.x) / bounds.size.x, float(size.y) / bounds.size.y)
	# No make_current(): a Camera2D parented under a SubViewport is automatically that
	# viewport's current camera, and the World2D is shared with the main viewport.
	_render_once_deferred()


func _render_once_deferred() -> void:
	# Wait for the terrain's queued _draw() to execute, then capture a single frame.
	await get_tree().process_frame
	await get_tree().process_frame
	# The level may have been torn down during the two-frame wait (fast scene swap / test exit).
	if not is_inside_tree():
		return
	render_target_update_mode = SubViewport.UPDATE_ONCE
