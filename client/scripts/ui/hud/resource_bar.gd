## ResourceBar - generic bottom-anchored resource bar (TextureProgressBar-backed scene).
##
## Shared script for the Stamina and Mana HUD bars. The visual layout (textures, trough
## inset, height, optional label) is authored per-scene in mana_bar.tscn / stamina_bar.tscn;
## this script only drives the fill value, the optional numeric label, and the stamina
## sprint-exhaustion frame flash. Modelled on health_bar.gd without the HP colour gradient.
## Update it via update_value().
class_name ResourceBar
extends Control

## Fill tint. Leave white to use the authored sprite colour.
@export var fill_color: Color = Color.WHITE
## Whether to draw the centered numeric label (the $Label node, if present).
@export var show_label: bool = false

var _current: float = 0.0
var _maximum: float = 100.0
## Sprint-exhaustion blink (stamina bar). While true, the frame flashes red.
var _exhausted: bool = false

@onready var _fill: TextureProgressBar = $Fill
@onready var _frame: TextureRect = $Frame
@onready var _label: Label = get_node_or_null("Label")


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	set_process(false)
	if _fill != null:
		_fill.tint_progress = fill_color
	if _label != null:
		_label.visible = show_label
	_update_display()


## Update the bar from an external resource value.
func update_value(current: float, maximum: float) -> void:
	_current = maxf(current, 0.0)
	_maximum = maxf(maximum, 1.0)
	_update_display()


## Toggle the sprint-exhaustion blink (wired from the movement SM's exhausted_changed).
func set_exhausted(active: bool) -> void:
	if _exhausted == active:
		return
	_exhausted = active
	set_process(active)
	if not active and _frame != null:
		_frame.modulate = Color.WHITE


func _process(_delta: float) -> void:
	if _frame == null:
		return
	# Flash the frame red↔white so the empty bar still reads as "exhausted".
	var t := 0.5 + 0.5 * sin(Time.get_ticks_msec() / 80.0)
	_frame.modulate = Color(1.0, 0.32, 0.32).lerp(Color.WHITE, t)


func _update_display() -> void:
	if _fill == null:
		return
	_fill.value = clampf(_current / _maximum, 0.0, 1.0)
	if _label != null and show_label:
		_label.text = "%d / %d" % [roundi(_current), roundi(_maximum)]
