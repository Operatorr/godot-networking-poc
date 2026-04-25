## UserPreferences - Local user preferences stored in user://
## Persists region selection and other client preferences across sessions
class_name UserPreferences
extends RefCounted

const SAVE_PATH: String = "user://preferences.json"

var selected_region: String = "local"  ## Default to local development server


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
		print("[UserPreferences] Loaded preferences: region=%s" % prefs.selected_region)
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
		"selected_region": selected_region
	}

	file.store_string(JSON.stringify(data, "\t"))
	file.close()
	print("[UserPreferences] Saved preferences: region=%s" % selected_region)
