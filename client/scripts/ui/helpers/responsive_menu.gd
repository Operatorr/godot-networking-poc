## Scale menu content independently of the world/camera stretch policy.
## Native Controls retain their transformed mouse and keyboard hit areas.
class_name ResponsiveMenu
extends CenterContainer

var _fit_queued: bool = false


func _ready() -> void:
	get_viewport().size_changed.connect(_queue_fit)
	minimum_size_changed.connect(_queue_fit)
	_queue_fit()


func _queue_fit() -> void:
	if not _fit_queued:
		_fit_queued = true
		_fit.call_deferred()


func _fit() -> void:
	_fit_queued = false
	var area := get_viewport_rect().size
	var factor := menu_scale(self, get_combined_minimum_size())
	set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	scale = Vector2.ONE * factor
	size = area / factor
	position = (area - size * factor) * 0.5


static func menu_scale(control: Control, minimum: Vector2) -> float:
	var area := control.get_viewport_rect().size
	var window_width := maxf(control.get_window().size.x, 1.0)
	var native_scale := clampf(area.x / window_width, 1.0, 3.0)
	return minf(native_scale, minf(area.x / (minimum.x + 48.0), area.y / (minimum.y + 48.0)))


static func fit_panel(panel: Control) -> void:
	var factor := menu_scale(panel, panel.size)
	panel.pivot_offset = panel.size * 0.5
	panel.scale = Vector2.ONE * factor
