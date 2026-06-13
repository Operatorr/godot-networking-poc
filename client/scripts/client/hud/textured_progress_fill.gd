## TexturedProgressFill - draws a left-to-right clipped fill texture.
##
## TextureRect can keep texture-driven minimum sizing, which is a poor fit for a
## resource bar whose visible width must shrink exactly with gameplay values.
extends Control


var texture: Texture2D = null:
	set(value):
		texture = value
		queue_redraw()

var progress: float = 1.0:
	set(value):
		progress = clampf(value, 0.0, 1.0)
		queue_redraw()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST


func _draw() -> void:
	if texture == null or progress <= 0.0:
		return

	var draw_width := floorf(size.x * progress)
	if draw_width <= 0.0:
		return

	var texture_size := texture.get_size()
	var source_width := floorf(texture_size.x * progress)
	draw_texture_rect_region(
		texture,
		Rect2(Vector2.ZERO, Vector2(draw_width, size.y)),
		Rect2(Vector2.ZERO, Vector2(source_width, texture_size.y)),
		Color.WHITE
	)
