## UserPreferences - Local user preferences stored in user://
## Persists region selection and other client preferences across sessions
class_name UserPreferences
extends RefCounted

const SAVE_PATH: String = "user://preferences.json"
const DEFAULT_PLAYER_COLOR: Color = Color(0.27, 0.53, 1.0)

var selected_region: String = "local"  ## Default to local development server
var player_color: Color = DEFAULT_PLAYER_COLOR


## Load preferences from disk
static func load_preferences() -> UserPreferences:
	var prefs := UserPreferences.new()
	if not FileAccess.file_exists(SAVE_PATH):
		return prefs

	var file := FileAccess.open(SAVE_PATH, FileAccess.READ)
	if file == null:
		push_error("[UserPreferences] Failed to open preferences file")
		return prefs

	var json := JSON.new()
	var parse_result := json.parse(file.get_as_text())
	file.close()

	if parse_result == OK and json.data is Dictionary:
		prefs.selected_region = json.data.get("selected_region", "local")
		prefs.player_color = _color_from_data(json.data.get("player_color", DEFAULT_PLAYER_COLOR))
		print("[UserPreferences] Loaded preferences: region=%s color=%s" % [prefs.selected_region, prefs.player_color])
	else:
		push_warning("[UserPreferences] Failed to parse preferences file")

	return prefs


## Save preferences to disk
func save() -> void:
	var file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
	if file == null:
		push_error("[UserPreferences] Failed to save preferences")
		return

	var data := {
		"selected_region": selected_region,
		"player_color": [
			clampi(roundi(player_color.r * 255.0), 0, 255),
			clampi(roundi(player_color.g * 255.0), 0, 255),
			clampi(roundi(player_color.b * 255.0), 0, 255)
		]
	}

	file.store_string(JSON.stringify(data, "\t"))
	file.close()
	print("[UserPreferences] Saved preferences: region=%s color=%s" % [selected_region, player_color])


static func _color_from_data(value: Variant) -> Color:
	if value is Color:
		return value

	if value is Array and value.size() >= 3:
		return Color(
			float(clampi(int(value[0]), 0, 255)) / 255.0,
			float(clampi(int(value[1]), 0, 255)) / 255.0,
			float(clampi(int(value[2]), 0, 255)) / 255.0,
			1.0
		)

	if value is Dictionary:
		return Color(
			float(value.get("r", DEFAULT_PLAYER_COLOR.r)),
			float(value.get("g", DEFAULT_PLAYER_COLOR.g)),
			float(value.get("b", DEFAULT_PLAYER_COLOR.b)),
			1.0
		)

	if value is String:
		var color := Color(value)
		if color != Color.BLACK or String(value).to_lower() in ["black", "#000", "#000000", "000000"]:
			color.a = 1.0
			return color

	return DEFAULT_PLAYER_COLOR
