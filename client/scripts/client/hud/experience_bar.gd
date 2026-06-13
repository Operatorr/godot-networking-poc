## ExperienceBar - top-center HUD element showing the player's level and XP progress.
##
## Driven by GameManager.experience_updated. XP is granted server-side (EXP_GAIN events,
## one per nearby player when a monster dies) and accounted client-side by GameManager,
## which owns the level curve and account persistence. See docs/systems/PROGRESSION.md.
class_name ExperienceBar
extends Control

const LEVEL_UP_FLASH_DURATION := 1.0
const FILL_COLOR := Color("5b3a8e")  # Void Violet
const LEVEL_UP_COLOR := Color(1.0, 0.92, 0.4)

var _level_label: Label = null
var _progress: ProgressBar = null
var _flash_timer: float = 0.0


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_build_ui()

	if GameManager.has_signal("experience_updated"):
		GameManager.experience_updated.connect(_on_experience_updated)

	# Seed from current state so the bar is correct on entry (no event needed).
	var level := GameManager.get_player_level()
	_refresh(level, GameManager.get_player_experience(), GameManager.xp_to_next_level(level), false)


func _build_ui() -> void:
	# Top-center, just below the screen edge.
	set_anchors_preset(Control.PRESET_CENTER_TOP)
	custom_minimum_size = Vector2(340, 40)
	offset_left = -170.0
	offset_right = 170.0
	offset_top = 14.0
	offset_bottom = 54.0

	var vbox := VBoxContainer.new()
	vbox.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	vbox.add_theme_constant_override("separation", 2)
	vbox.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(vbox)

	_level_label = Label.new()
	_level_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_level_label.add_theme_font_size_override("font_size", 16)
	_level_label.add_theme_color_override("font_color", Color.WHITE)
	_level_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.8))
	_level_label.add_theme_constant_override("outline_size", 4)
	_level_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	vbox.add_child(_level_label)

	_progress = ProgressBar.new()
	_progress.custom_minimum_size = Vector2(340, 12)
	_progress.show_percentage = false
	_progress.min_value = 0.0
	_progress.max_value = 100.0
	_progress.value = 0.0
	_progress.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var fill := StyleBoxFlat.new()
	fill.bg_color = FILL_COLOR
	fill.corner_radius_top_left = 3
	fill.corner_radius_top_right = 3
	fill.corner_radius_bottom_left = 3
	fill.corner_radius_bottom_right = 3
	_progress.add_theme_stylebox_override("fill", fill)
	vbox.add_child(_progress)


func _process(delta: float) -> void:
	if _flash_timer <= 0.0:
		return
	_flash_timer = maxf(0.0, _flash_timer - delta)
	if _level_label:
		var t := _flash_timer / LEVEL_UP_FLASH_DURATION
		_level_label.add_theme_color_override("font_color", Color.WHITE.lerp(LEVEL_UP_COLOR, t))


func _on_experience_updated(level: int, experience: int, xp_to_next: int, leveled_up: bool) -> void:
	_refresh(level, experience, xp_to_next, leveled_up)


func _refresh(level: int, experience: int, xp_to_next: int, leveled_up: bool) -> void:
	if _progress:
		if xp_to_next > 0:
			_progress.max_value = float(xp_to_next)
			_progress.value = clampf(float(experience), 0.0, float(xp_to_next))
		else:
			# Max level: full bar.
			_progress.max_value = 1.0
			_progress.value = 1.0
	if _level_label:
		if xp_to_next > 0:
			_level_label.text = "Lv %d   %d / %d XP" % [level, experience, xp_to_next]
		else:
			_level_label.text = "Lv %d   MAX" % level
	if leveled_up:
		_flash_timer = LEVEL_UP_FLASH_DURATION
		_play_level_up_effect(level)


## Big centered "LEVEL UP!" banner + golden flash + the ding — a ROTMG/WoW-style moment.
## Built as a transient overlay on the HUD layer so it spans the screen, then auto-freed.
func _play_level_up_effect(level: int) -> void:
	var audio := get_node_or_null("/root/AudioManager")
	if audio and audio.has_method("play_level_up"):
		audio.play_level_up()

	var hud := get_parent()
	if hud == null:
		return

	var overlay := Control.new()
	overlay.name = "LevelUpEffect"
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay.mouse_filter = Control.MOUSE_FILTER_IGNORE
	hud.add_child(overlay)

	var flash := ColorRect.new()
	flash.color = Color(1.0, 0.85, 0.35, 0.0)
	flash.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	flash.mouse_filter = Control.MOUSE_FILTER_IGNORE
	overlay.add_child(flash)

	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	center.modulate = Color(1, 1, 1, 0)
	overlay.add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 4)
	center.add_child(vbox)

	var title := Label.new()
	title.text = "LEVEL UP!"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 64)
	title.add_theme_color_override("font_color", Color(1.0, 0.9, 0.45))
	title.add_theme_color_override("font_outline_color", Color(0.28, 0.16, 0.0, 1.0))
	title.add_theme_constant_override("outline_size", 8)
	vbox.add_child(title)

	var sub := Label.new()
	sub.text = "Level %d" % level
	sub.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sub.add_theme_font_size_override("font_size", 28)
	sub.add_theme_color_override("font_color", Color(1.0, 0.96, 0.82))
	sub.add_theme_color_override("font_outline_color", Color(0.28, 0.16, 0.0, 1.0))
	sub.add_theme_constant_override("outline_size", 5)
	vbox.add_child(sub)

	# Fade the banner in with the flash, hold, then fade out. (Position isn't animated —
	# the container is anchored full-rect, so a position tween would fight the layout.)
	var tw := create_tween()
	tw.tween_property(flash, "color:a", 0.32, 0.10)
	tw.parallel().tween_property(center, "modulate:a", 1.0, 0.18)
	tw.tween_interval(0.7)
	tw.tween_property(flash, "color:a", 0.0, 0.6)
	tw.parallel().tween_property(center, "modulate:a", 0.0, 0.6)
	tw.tween_callback(overlay.queue_free)
