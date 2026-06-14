## MonsterDatabase - Registry of all monster definitions (the data-driven catalogue).
##
## Loads every monster archetype from res://data/monsters/ and exposes them by id.
## Shared by the server (to spawn/drive monsters) and the client (display name +
## appearance for rendering). Mirrors ServerConfig's JSON loading pattern.
##
## Loading is export-safe: an explicit index.json manifest is the source of truth
## (FileAccess by known path works inside an exported .pck), while a best-effort
## DirAccess scan additionally auto-discovers files during editor development.
##
## To add a monster: drop res://data/monsters/<id>.json and list <id> in index.json.
class_name MonsterDatabase
extends RefCounted

const MONSTER_DATA_DIR := "res://data/monsters/"
const MANIFEST_PATH := "res://data/monsters/index.json"
const DEFAULT_MONSTER_ID := "toxic_slime"

## Process-wide shared instance (lazy). Both client and server use this.
static var _shared: MonsterDatabase = null

## id -> MonsterDefinition
var _definitions: Dictionary = {}

var debug_logging: bool = false


## Get (or lazily build) the shared database.
static func get_shared() -> MonsterDatabase:
	if _shared == null:
		_shared = MonsterDatabase.new()
		_shared.load_all()
	return _shared


## (Re)load all monster definitions from disk.
func load_all() -> void:
	_definitions.clear()

	for id in _discover_ids():
		_load_definition_file(MONSTER_DATA_DIR + id + ".json", id)

	_ensure_default()

	if debug_logging:
		print("[MonsterDatabase] Loaded %d monster definition(s): %s" % [
			_definitions.size(), ", ".join(PackedStringArray(_definitions.keys()))
		])


## Resolve the set of monster ids to load: manifest first (export-safe),
## then any extra *.json discovered on disk (editor convenience).
func _discover_ids() -> Array[String]:
	var ids: Array[String] = []

	var manifest: Variant = _load_json(MANIFEST_PATH)
	if manifest is Dictionary and manifest.has("monsters") and manifest["monsters"] is Array:
		for entry in manifest["monsters"]:
			var entry_id := str(entry)
			if not entry_id.is_empty() and not ids.has(entry_id):
				ids.append(entry_id)

	var dir := DirAccess.open(MONSTER_DATA_DIR)
	if dir != null:
		dir.list_dir_begin()
		var file_name := dir.get_next()
		while file_name != "":
			if not dir.current_is_dir() and file_name.ends_with(".json") and file_name != "index.json":
				var discovered_id := file_name.get_basename()
				if not ids.has(discovered_id):
					ids.append(discovered_id)
			file_name = dir.get_next()
		dir.list_dir_end()

	return ids


func _load_definition_file(path: String, fallback_id: String) -> void:
	var data: Variant = _load_json(path)
	if not (data is Dictionary):
		push_warning("[MonsterDatabase] Skipping invalid monster file: %s" % path)
		return

	var def := MonsterDefinition.from_dict(fallback_id, data)
	_definitions[def.id] = def


func _ensure_default() -> void:
	if not _definitions.has(DEFAULT_MONSTER_ID):
		var def := MonsterDefinition.default()
		_definitions[def.id] = def


## Look up a definition by id. Falls back to the default rather than returning null.
func get_definition(id: String) -> MonsterDefinition:
	if _definitions.has(id):
		return _definitions[id]
	push_warning("[MonsterDatabase] Unknown monster id '%s', using default" % id)
	return get_default_definition()


func get_default_definition() -> MonsterDefinition:
	return _definitions.get(DEFAULT_MONSTER_ID, MonsterDefinition.default())


func has(id: String) -> bool:
	return _definitions.has(id)


func get_all_ids() -> Array:
	return _definitions.keys()


# --- JSON loading (mirrors ServerConfig) ------------------------------------

func _load_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		return null

	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		push_error("[MonsterDatabase] Failed to open: %s (Error: %d)" % [path, FileAccess.get_open_error()])
		return null

	var content := file.get_as_text()
	file.close()

	var json := JSON.new()
	if json.parse(content) != OK:
		push_error("[MonsterDatabase] JSON parse error in %s at line %d: %s" % [
			path, json.get_error_line(), json.get_error_message()
		])
		return null

	return json.data
