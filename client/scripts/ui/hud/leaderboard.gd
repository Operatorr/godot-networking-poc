## Leaderboard - top-left compact leaderboard (top 5, expands to top 10 while Tab held).
##
## Authored as scenes/ui/hud/leaderboard.tscn (Panel + VBox with a Title and a separator); the
## ten entry rows are built in code (_build_rows). Each row is
##   [class icon] Name - Class {level} ........... {kills:deaths, right-aligned}
## with the "Name - Class {level}" text tinted by the class's identity color (PacketTypes.CLASS_COLORS,
## WoW-inspired). The local player and a recent killer/victim are cued by a row-background tint so the
## class color on the text is preserved. Ranking is by kills (the server's top_n order); the right
## column shows the Kills:Deaths ratio (deaths ride the LEADERBOARD_UPDATE entries, protocol v7+).
## update_entries() refreshes from server leaderboard data; class, level and icon are joined per entity
## from EntityNameCache (populated by PLAYER_INFO, protocol v6+).
extends Control

const COMPACT_COUNT := 5
const EXPANDED_COUNT := 10
const FLASH_DURATION := 1.5
const ICON_SIZE := 18

## Row-background tints (the row's StyleBoxFlat bg_color). Default is fully transparent so only the
## class-colored text shows; local/flash get a translucent wash that leaves the text legible.
const BG_TRANSPARENT := Color(0, 0, 0, 0)
const BG_LOCAL := Color(0.30, 0.90, 0.30, 0.14)
const BG_FLASH := Color(1.0, 0.85, 0.2, 0.30)
## Kill-count column color (gold), constant across rows.
const KILLS_COLOR := Color(1.0, 0.86, 0.45)

var _entries: Array[Dictionary] = []  # {entity_id: int, pvp_kills: int, deaths: int}
var _rows: Array[Dictionary] = []  # {panel, style, icon, info, kills}
var _is_expanded: bool = false
var _flash_entity_id: int = -1
var _flash_tween: Tween = null
var _last_signature: String = ""
var _icon_cache: Dictionary = {}  # class_id (int) -> Texture2D (null when the class has no icon)

@onready var _title_label: Label = $Panel/VBox/Title
@onready var _vbox: VBoxContainer = $Panel/VBox


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_build_rows()
	_refresh_display()


## Build the EXPANDED_COUNT entry rows once and cache their node handles. Each row owns its own
## StyleBoxFlat instance so its background tint can be toggled independently.
func _build_rows() -> void:
	for _i in EXPANDED_COUNT:
		var style := StyleBoxFlat.new()
		style.bg_color = BG_TRANSPARENT
		style.content_margin_left = 4.0
		style.content_margin_right = 4.0
		style.content_margin_top = 1.0
		style.content_margin_bottom = 1.0
		style.corner_radius_top_left = 3
		style.corner_radius_top_right = 3
		style.corner_radius_bottom_left = 3
		style.corner_radius_bottom_right = 3

		var panel := PanelContainer.new()
		panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
		panel.add_theme_stylebox_override("panel", style)

		var row := HBoxContainer.new()
		row.mouse_filter = Control.MOUSE_FILTER_IGNORE
		row.add_theme_constant_override("separation", 6)
		panel.add_child(row)

		var icon := TextureRect.new()
		icon.custom_minimum_size = Vector2(ICON_SIZE, ICON_SIZE)
		icon.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		icon.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		icon.mouse_filter = Control.MOUSE_FILTER_IGNORE
		row.add_child(icon)

		var info := Label.new()
		info.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		info.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		info.clip_text = true
		info.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		info.add_theme_font_size_override("font_size", 14)
		row.add_child(info)

		var kills := Label.new()
		# Min width for the "K:D" pair; typical counts fit, and the label trim-ellipsis-clips the
		# pathological max ("65535:65535") rather than overflowing the row.
		kills.custom_minimum_size = Vector2(50, 0)
		kills.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
		kills.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		kills.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		kills.add_theme_font_size_override("font_size", 14)
		kills.add_theme_color_override("font_color", KILLS_COLOR)
		row.add_child(kills)

		_vbox.add_child(panel)
		_rows.append({"panel": panel, "style": style, "icon": icon, "info": info, "kills": kills})


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey:
		if event.physical_keycode == KEY_TAB and not event.echo:
			_is_expanded = event.pressed
			_refresh_display()


## Update leaderboard entries from server data.
func update_entries(entries: Array) -> void:
	var sanitized := _sanitize_entries(entries)
	var signature := _make_signature(sanitized)
	if signature == _last_signature:
		return

	_entries.clear()
	for entry in sanitized:
		_entries.append(entry)
	_last_signature = signature
	_refresh_display()


func _sanitize_entries(entries: Array) -> Array[Dictionary]:
	var by_entity_id: Dictionary = {}

	for raw_entry in entries:
		if not raw_entry is Dictionary:
			continue

		var entity_id := int(raw_entry.get("entity_id", 0))
		if entity_id <= 0:
			continue

		var kills := clampi(int(raw_entry.get("pvp_kills", 0)), 0, 65535)
		var deaths := clampi(int(raw_entry.get("deaths", 0)), 0, 65535)
		var existing: Dictionary = by_entity_id.get(entity_id, {})
		if existing.is_empty() or kills > int(existing.get("pvp_kills", 0)):
			by_entity_id[entity_id] = {
				"entity_id": entity_id,
				"pvp_kills": kills,
				"deaths": deaths
			}

	var sanitized: Array[Dictionary] = []
	for entry in by_entity_id.values():
		sanitized.append(entry)

	sanitized.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var a_kills := int(a.get("pvp_kills", 0))
		var b_kills := int(b.get("pvp_kills", 0))
		if a_kills == b_kills:
			return int(a.get("entity_id", 0)) < int(b.get("entity_id", 0))
		return a_kills > b_kills
	)

	if sanitized.size() > EXPANDED_COUNT:
		sanitized.resize(EXPANDED_COUNT)

	return sanitized


func _make_signature(entries: Array[Dictionary]) -> String:
	var parts: PackedStringArray = []
	for entry in entries:
		parts.append("%d:%d:%d" % [
			int(entry.get("entity_id", 0)),
			int(entry.get("pvp_kills", 0)),
			int(entry.get("deaths", 0))
		])
	return "|".join(parts)


func _refresh_display() -> void:
	var show_count := EXPANDED_COUNT if _is_expanded else COMPACT_COUNT
	_title_label.text = "LEADERBOARD" + (" (Tab)" if not _is_expanded else "")

	for i in _rows.size():
		var row: Dictionary = _rows[i]
		if i < _entries.size() and i < show_count:
			var entry: Dictionary = _entries[i]
			var entity_id: int = entry.get("entity_id", 0)
			var kills: int = entry.get("pvp_kills", 0)
			var deaths: int = entry.get("deaths", 0)
			var player_name := EntityNameCache.get_entity_name(entity_id)
			var cls_id := EntityNameCache.get_entity_class(entity_id)
			var level := EntityNameCache.get_entity_level(entity_id)

			var info: Label = row["info"]
			info.text = "%s - %s %d" % [player_name, PacketTypes.class_id_to_name(cls_id), level]
			info.add_theme_color_override("font_color", PacketTypes.class_color(cls_id))

			var kills_label: Label = row["kills"]
			kills_label.text = "%d:%d" % [kills, deaths]

			var icon: TextureRect = row["icon"]
			icon.texture = _icon_for_class(cls_id)

			# State cue via row background (keeps the class-colored text): flash > local > none.
			var style: StyleBoxFlat = row["style"]
			if entity_id == _flash_entity_id:
				style.bg_color = BG_FLASH
			elif entity_id == GameManager.get_local_player_entity_id():
				style.bg_color = BG_LOCAL
			else:
				style.bg_color = BG_TRANSPARENT

			row["panel"].visible = true
		else:
			row["panel"].visible = false


## Class icon texture for a class id (cached), or null when that class ships no icon yet.
func _icon_for_class(class_id: int) -> Texture2D:
	if _icon_cache.has(class_id):
		return _icon_cache[class_id]
	var path := PacketTypes.class_icon_path(class_id)
	var tex: Texture2D = null
	if not path.is_empty() and ResourceLoader.exists(path):
		tex = load(path)
	_icon_cache[class_id] = tex
	return tex


## Briefly flash/highlight a player's row in the leaderboard.
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
