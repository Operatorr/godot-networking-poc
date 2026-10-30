## KillFeed - displays recent kill messages (last 3, fading after 3 seconds).
##
## Authored as scenes/ui/hud/kill_feed.tscn (top-right Control + VBox). Rows are created
## dynamically per kill (they're data-driven), appended to the authored $VBox.
extends Control

const MAX_MESSAGES := 3
const FADE_DURATION := 3.0
const FRAME := preload("res://assets/ui/grimdark/kill_feed_frame.svg")
const SKULL := preload("res://assets/ui/grimdark/kill_skull.svg")

var _messages: Array[Dictionary] = []  # {timestamp: float, row: PanelContainer}

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
			msg.row.queue_free()
			_messages.remove_at(i)
		else:
			# Fade out in last second
			if age > FADE_DURATION - 1.0:
				msg.row.modulate.a = (FADE_DURATION - age)
			i += 1


## Add a kill message to the feed.
func add_kill(killer_name: String, victim_name: String) -> void:
	# Remove oldest if at capacity
	if _messages.size() >= MAX_MESSAGES:
		_messages[0].row.queue_free()
		_messages.remove_at(0)

	var row := PanelContainer.new()
	row.custom_minimum_size.y = 64
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var style := StyleBoxTexture.new()
	style.texture = FRAME
	for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
		style.set_texture_margin(side, 18)
		style.set_content_margin(side, 14)
	row.add_theme_stylebox_override("panel", style)
	var content := HBoxContainer.new()
	content.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_theme_constant_override("separation", 10)
	row.add_child(content)
	var skull := TextureRect.new()
	skull.texture = SKULL
	skull.custom_minimum_size = Vector2(24, 28)
	skull.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	skull.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	skull.mouse_filter = Control.MOUSE_FILTER_IGNORE
	content.add_child(skull)
	var label := RichTextLabel.new()
	label.fit_content = true
	label.scroll_active = false
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	label.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.focus_mode = Control.FOCUS_NONE
	label.add_theme_font_size_override("normal_font_size", 16)
	# Push colors explicitly: player names are text, never interpreted as BBCode.
	label.push_color(Color("ee6464"))
	label.add_text(killer_name)
	label.pop()
	label.add_text(" eliminated ")
	label.push_color(Color("81b9df"))
	label.add_text(victim_name)
	label.pop()
	content.add_child(label)
	_vbox.add_child(row)

	_messages.append({
		"timestamp": Time.get_ticks_msec() / 1000.0,
		"row": row
	})
