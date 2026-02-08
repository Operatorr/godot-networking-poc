## LeaderboardCompact - Top-left leaderboard
## Shows top 3 by default, expands to top 10 when Tab held
extends Control


const COMPACT_COUNT := 3
const EXPANDED_COUNT := 10
const FLASH_DURATION := 1.5

var _entries: Array[Dictionary] = []  # {entity_id: int, pvp_kills: int}
var _labels: Array[Label] = []
var _title_label: Label = null
var _vbox: VBoxContainer = null
var _is_expanded: bool = false
var _flash_entity_id: int = -1
var _flash_tween: Tween = null


func _ready() -> void:
	_build_ui()
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _build_ui() -> void:
	# Position top-left
	anchor_left = 0.0
	anchor_right = 0.0
	anchor_top = 0.0
	anchor_bottom = 0.0
	offset_left = 20
	offset_right = 250
	offset_top = 20
	offset_bottom = 400

	var panel := PanelContainer.new()
	panel.set_anchors_and_offsets_preset(Control.PRESET_TOP_LEFT)
	panel.size = Vector2(230, 0)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.08, 0.08, 0.1, 0.8)
	style.corner_radius_top_left = 4
	style.corner_radius_top_right = 4
	style.corner_radius_bottom_left = 4
	style.corner_radius_bottom_right = 4
	style.content_margin_left = 10
	style.content_margin_right = 10
	style.content_margin_top = 8
	style.content_margin_bottom = 8
	panel.add_theme_stylebox_override("panel", style)
	add_child(panel)

	_vbox = VBoxContainer.new()
	_vbox.add_theme_constant_override("separation", 2)
	panel.add_child(_vbox)

	# Title
	_title_label = Label.new()
	_title_label.text = "LEADERBOARD"
	_title_label.add_theme_font_size_override("font_size", 12)
	_title_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7))
	_title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_vbox.add_child(_title_label)

	# Separator
	var sep := HSeparator.new()
	_vbox.add_child(sep)

	# Pre-create labels (10 max)
	for i in EXPANDED_COUNT:
		var label := Label.new()
		label.add_theme_font_size_override("font_size", 14)
		label.add_theme_color_override("font_color", Color(0.9, 0.9, 0.9))
		_vbox.add_child(label)
		_labels.append(label)

	_refresh_display()


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey:
		if event.physical_keycode == KEY_TAB:
			_is_expanded = event.pressed
			_refresh_display()


## Update leaderboard entries from server data
func update_entries(entries: Array) -> void:
	_entries.clear()
	for entry in entries:
		_entries.append(entry)
	_refresh_display()


func _refresh_display() -> void:
	var show_count := EXPANDED_COUNT if _is_expanded else COMPACT_COUNT
	_title_label.text = "LEADERBOARD" + (" (Tab)" if not _is_expanded else "")

	for i in _labels.size():
		if i < _entries.size() and i < show_count:
			var entry: Dictionary = _entries[i]
			var entity_id: int = entry.get("entity_id", 0)
			var kills: int = entry.get("pvp_kills", 0)
			var player_name := EntityNameCache.get_entity_name(entity_id)
			_labels[i].text = "%d. %s - %d kills" % [i + 1, player_name, kills]
			_labels[i].visible = true

			# Color priority: flash > local player > default
			if entity_id == _flash_entity_id:
				_labels[i].add_theme_color_override("font_color", Color(1.0, 0.85, 0.2))
			elif entity_id == GameManager.get_local_player_entity_id():
				_labels[i].add_theme_color_override("font_color", Color(0.3, 0.9, 0.3))
			else:
				_labels[i].add_theme_color_override("font_color", Color(0.9, 0.9, 0.9))
		else:
			_labels[i].visible = false


## Briefly flash/highlight a player's name in the leaderboard
func flash_player(entity_id: int) -> void:
	_flash_entity_id = entity_id
	_refresh_display()

	# Cancel any existing flash tween
	if _flash_tween and _flash_tween.is_valid():
		_flash_tween.kill()

	_flash_tween = create_tween()
	_flash_tween.tween_callback(func():
		_flash_entity_id = -1
		_refresh_display()
	).set_delay(FLASH_DURATION)
