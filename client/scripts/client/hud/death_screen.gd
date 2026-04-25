## DeathScreen - Death overlay with killer info and respawn button
## Shown when local player dies, hidden on respawn
extends Control


var _killer_label: Label = null
var _countdown_label: Label = null
var _respawn_button: Button = null
var _countdown_timer: float = 0.0
var _countdown_active: bool = false
const RESPAWN_COUNTDOWN := 3.0


func _ready() -> void:
	_build_ui()
	visible = false
	# Consume mouse events when visible
	mouse_filter = Control.MOUSE_FILTER_STOP


func _build_ui() -> void:
	# Full-screen semi-transparent background
	var bg := ColorRect.new()
	bg.color = Color(0.08, 0.0, 0.0, 0.85)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(bg)

	# Center container
	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 20)
	center.add_child(vbox)

	# "YOU DIED" title
	var title := Label.new()
	title.text = "YOU DIED"
	title.add_theme_font_size_override("font_size", 64)
	title.add_theme_color_override("font_color", Color(1.0, 0.0, 0.0))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	# Killer info
	_killer_label = Label.new()
	_killer_label.text = ""
	_killer_label.add_theme_font_size_override("font_size", 20)
	_killer_label.add_theme_color_override("font_color", Color(0.8, 0.8, 0.8))
	_killer_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(_killer_label)

	# Countdown label
	_countdown_label = Label.new()
	_countdown_label.text = ""
	_countdown_label.add_theme_font_size_override("font_size", 28)
	_countdown_label.add_theme_color_override("font_color", Color(0.9, 0.5, 0.5))
	_countdown_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(_countdown_label)

	# Spacer
	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(0, 10)
	vbox.add_child(spacer)

	# Respawn button
	_respawn_button = Button.new()
	_respawn_button.text = "RESPAWN"
	_respawn_button.custom_minimum_size = Vector2(200, 50)
	_respawn_button.add_theme_font_size_override("font_size", 24)
	_respawn_button.pressed.connect(_on_respawn_pressed)
	vbox.add_child(_respawn_button)


func _process(delta: float) -> void:
	if not _countdown_active:
		return
	_countdown_timer -= delta
	if _countdown_timer <= 0.0:
		_countdown_active = false
		_countdown_label.text = ""
		_respawn_button.disabled = false
		_respawn_button.text = "RESPAWN"
	else:
		var secs := ceili(_countdown_timer)
		_countdown_label.text = "Respawn in %d..." % secs
		# Pulse effect
		var pulse: float = 0.7 + 0.3 * absf(sin(Time.get_ticks_msec() / 200.0))
		_countdown_label.modulate.a = pulse


## Show death screen with killer information
func show_death(killer_entity_id: int) -> void:
	if killer_entity_id >= 100000:
		_killer_label.text = "Killed by Monster"
	elif killer_entity_id > 0:
		var killer_name := EntityNameCache.get_entity_name(killer_entity_id)
		_killer_label.text = "Killed by %s" % killer_name
	else:
		_killer_label.text = ""

	# Start countdown
	_countdown_timer = RESPAWN_COUNTDOWN
	_countdown_active = true
	_respawn_button.disabled = true
	_respawn_button.text = "WAIT..."
	visible = true


## Hide death screen
func hide_death() -> void:
	visible = false


func _on_respawn_pressed() -> void:
	_respawn_button.disabled = true
	NetworkManager.send_message(
		NetworkManager.MessageType.RESPAWN_REQUEST, {}
	)
	# Re-enable after short delay in case of failure
	await get_tree().create_timer(2.0).timeout
	if visible:
		_respawn_button.disabled = false
