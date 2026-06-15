## KillFeed - displays recent kill messages (last 3, fading after 3 seconds).
##
## Authored as scenes/ui/hud/kill_feed.tscn (top-right Control + VBox). Rows are created
## dynamically per kill (they're data-driven), appended to the authored $VBox.
extends Control

const MAX_MESSAGES := 3
const FADE_DURATION := 3.0

var _messages: Array[Dictionary] = []  # {text: String, timestamp: float, label: Label}

@onready var _vbox: VBoxContainer = $VBox


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _process(_delta: float) -> void:
	var current_time := Time.get_ticks_msec() / 1000.0
	var i := 0
	while i < _messages.size():
		var msg: Dictionary = _messages[i]
		var age: float = current_time - msg.timestamp
		if age >= FADE_DURATION:
			msg.label.queue_free()
			_messages.remove_at(i)
		else:
			# Fade out in last second
			if age > FADE_DURATION - 1.0:
				msg.label.modulate.a = (FADE_DURATION - age)
			i += 1


## Add a kill message to the feed.
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
