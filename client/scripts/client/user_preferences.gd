## UserPreferences - Local user preferences stored in user://
## Persists region selection and other client preferences across sessions
class_name UserPreferences
extends RefCounted

const SAVE_PATH: String = "user://preferences.json"
const DEFAULT_PLAYER_COLOR: Color = Color(0.27, 0.53, 1.0)

var selected_region: String = "local"  ## Default to local development server
var player_color: Color = DEFAULT_PLAYER_COLOR

## Custom keyboard rebinds: action_name -> physical_keycode (int). Empty = project
## defaults. Applied to the InputMap at startup via apply_keybinds(); edited from the
## Settings → Keyboard Controls page.
var keybinds: Dictionary = {}


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
		prefs.keybinds = _keybinds_from_data(json.data.get("keybinds", {}))
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
		],
		"keybinds": keybinds.duplicate()
	}

	file.store_string(JSON.stringify(data, "\t"))
	file.close()
	print("[UserPreferences] Saved preferences: region=%s color=%s" % [selected_region, player_color])


## JSON stores keybind keycodes as floats; coerce back to {action: int}.
static func _keybinds_from_data(value: Variant) -> Dictionary:
	var result: Dictionary = {}
	if value is Dictionary:
		for action: Variant in value.keys():
			result[String(action)] = int(value[action])
	return result


## Apply the saved keyboard rebinds onto the live InputMap, replacing only the
## InputEventKey events of each overridden action (mouse buttons are preserved).
## Call once at startup after the InputMap has loaded project defaults.
func apply_keybinds() -> void:
	for action: Variant in keybinds.keys():
		var action_name := String(action)
		if not InputMap.has_action(action_name):
			continue
		rebind_action_key(action_name, int(keybinds[action_name]))


## Rebind a single action to a physical key, persisting the change. Removes the
## action's existing keyboard events (leaving mouse/other events intact) and adds
## a physical-key event so the binding follows the key's physical location.
func rebind_action_key(action_name: String, physical_keycode: int) -> void:
	if not InputMap.has_action(action_name):
		return
	for event in InputMap.action_get_events(action_name):
		if event is InputEventKey:
			InputMap.action_erase_event(action_name, event)
	var key_event := InputEventKey.new()
	key_event.physical_keycode = physical_keycode
	InputMap.action_add_event(action_name, key_event)
	keybinds[action_name] = physical_keycode


## Restore all input actions to the project defaults and clear saved rebinds.
func reset_keybinds_to_defaults() -> void:
	InputMap.load_from_project_settings()
	keybinds.clear()


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
