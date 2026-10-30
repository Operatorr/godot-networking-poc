@tool
class_name LayeredUIStyle
extends StyleBox
## Shared native-control skin: raster material beneath a transparent vector rim.
## No overlay Controls, so text, input, focus and container ownership stay native.

@export var frame: StyleBoxTexture
@export var surface: Texture2D
@export var base_color := Color("101414")
@export var surface_modulate := Color(1, 1, 1, 0.5)
@export var surface_inset: float = 9.0
@export var crop_surface: bool = false


func _draw(canvas_item: RID, rect: Rect2) -> void:
	var interior := rect.grow(-surface_inset)
	if interior.has_area():
		RenderingServer.canvas_item_add_rect(canvas_item, interior, base_color)
		if surface != null:
			if crop_surface:
				# Wide buttons sample a strip instead of flattening square grain.
				var source_size := surface.get_size()
				var scale_factor := minf(source_size.x / interior.size.x, source_size.y / interior.size.y)
				var sample_size := interior.size * scale_factor
				var source := Rect2((source_size - sample_size) * 0.5, sample_size)
				surface.draw_rect_region(canvas_item, interior, source, surface_modulate)
			else:
				surface.draw_rect(canvas_item, interior, false, surface_modulate)
	if frame != null:
		frame.draw(canvas_item, rect)
