## KillFeedControl - Displays recent kill messages
## Shows last 3 kills, messages fade after 3 seconds
extends Control


const MAX_MESSAGES := 3
const FADE_DURATION := 3.0

var _messages: Array[Dictionary] = []  # {text: String, timestamp: float, label: Label}
var _vbox: VBoxContainer = null


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _build_ui() -> void:
	# Position top-right, below minimap (minimap is 180px + 20 margin)
	anchor_left = 1.0
	anchor_right = 1.0
	anchor_top = 0.0
	anchor_bottom = 0.0
	offset_left = -320
	offset_right = -20
	offset_top = 210
	offset_bottom = 310

	_vbox = VBoxContainer.new()
	_vbox.add_theme_constant_override("separation", 4)
	_vbox.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_vbox)


func _process(_delta: float) -> void:
	var current_time := Time.get_ticks_msec() / 1000.0
	var i := 0
	while i < _messages.size():
		var msg: Dictionary = _messages[i]
		var age := current_time - msg.timestamp
		if age >= FADE_DURATION:
			msg.label.queue_free()
			_messages.remove_at(i)
		else:
			# Fade out in last second
			if age > FADE_DURATION - 1.0:
				msg.label.modulate.a = (FADE_DURATION - age)
			i += 1


## Add a kill message to the feed
func add_kill(killer_name: String, victim_name: String) -> void:
	# Remove oldest if at capacity
	if _messages.size() >= MAX_MESSAGES:
		_messages[0].label.queue_free()
		_messages.remove_at(0)

	var label := Label.new()
	label.text = "%s eliminated %s" % [killer_name, victim_name]
	label.add_theme_font_size_override("font_size", 14)
	label.add_theme_color_override("font_color", Color(1.0, 0.85, 0.3))
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_vbox.add_child(label)

	_messages.append({
		"text": label.text,
		"timestamp": Time.get_ticks_msec() / 1000.0,
		"label": label
	})
