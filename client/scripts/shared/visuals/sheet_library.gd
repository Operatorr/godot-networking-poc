## SheetLibrary - builds SpriteFrames from PixelLab grid spritesheets.
##
## A sheet asset is a directory containing one PNG per animation plus a
## meta.json sidecar written by scripts/art/assemble_pixellab_sheets.py:
##   { "canvas": [w, h], "directional": true, "dir_order": [8 names],
##     "anims": { "idle": {"frames": 8, "fps": 8, "loop": true, "png": "idle.png"}, ... } }
##
## Directional sheets hold one row per direction (DIR_ORDER below, matching
## the assembler) and become SpriteFrames animations named "<anim>_<row>"
## (row 0-7). Non-directional sheets (slime, projectiles) hold a single row
## and become plain "<anim>" animations.
##
## Player-class sheets are cached per PacketTypes.PlayerClass id and resolve
## missing animations by aliasing (e.g. a bot class without "attack" falls
## back to its "idle" frames) so callers can always play any base name.
class_name SheetLibrary
extends RefCounted

## Row order in every directional sheet; index = row. Matches the assembler.
const DIR_ORDER := [
	"south", "south-east", "east", "north-east",
	"north", "north-west", "west", "south-west",
]

## Octant (round(angle / 45deg), angle 0 = +X/east, CW with +Y down) -> row.
const OCTANT_TO_ROW := [2, 1, 0, 7, 6, 5, 4, 3]

## PacketTypes.PlayerClass id -> sheet directory key.
const CLASS_KEYS := [
	"zealot", "void_hunter", "engineer", "plague_seer",
	"warrior", "rogue", "mage",
]

const PLAYERS_DIR := "res://assets/sprites/players"
const MONSTERS_DIR := "res://assets/sprites/monsters"
const PROJECTILES_DIR := "res://assets/sprites/projectiles"

## Animations every class SpriteFrames must answer to; missing ones alias
## to the first available fallback in their list.
const CLASS_ANIM_FALLBACKS := {
	"idle": [],
	"run": ["idle"],
	"sprint": ["run", "idle"],
	"dash": ["sprint", "run", "idle"],
	"attack": ["idle"],
	"hit": ["idle"],
	"death": ["hit", "idle"],
}

static var _class_cache: Dictionary = {}
static var _sheet_cache: Dictionary = {}


## SpriteFrames for a player class id (clamped); never returns null for
## a class whose sheet directory exists. Returns null if assets are absent
## so callers can keep their procedural fallback.
static func class_frames(class_id: int) -> SpriteFrames:
	var idx := clampi(class_id, 0, CLASS_KEYS.size() - 1)
	if _class_cache.has(idx):
		return _class_cache[idx]
	var frames := load_sheet("%s/%s" % [PLAYERS_DIR, CLASS_KEYS[idx]], CLASS_ANIM_FALLBACKS)
	_class_cache[idx] = frames
	return frames


## Animations monster.gd plays that the generated slime sheet may lack;
## aliased so the server-driven state machine can always play them.
const MONSTER_ANIM_FALLBACKS := {
	"idle": [],
	"walk": ["idle"],
	"attack": ["idle"],
	"hit": ["idle"],
	"death": ["idle"],
	"spawn": ["idle"],
}


static func monster_frames(monster_key: String) -> SpriteFrames:
	return load_sheet("%s/%s" % [MONSTERS_DIR, monster_key], MONSTER_ANIM_FALLBACKS)


static func projectile_frames(class_id: int) -> SpriteFrames:
	var idx := clampi(class_id, 0, CLASS_KEYS.size() - 1)
	return load_sheet("%s/%s" % [PROJECTILES_DIR, CLASS_KEYS[idx]], {})


static func monster_projectile_frames(monster_key: String) -> SpriteFrames:
	return load_sheet("%s/%s" % [PROJECTILES_DIR, monster_key], {})


## Some generated projectile art points 45 degrees up-right instead of right
## (+X). The projectile rotates its root by direction.angle(), so this is the
## extra sprite-local rotation (radians) that trues up each class's art.
const _PROJECTILE_ROT_OFFSET_DEG := {
	"zealot": 45.0,
	"warrior": 45.0,
	"rogue": 45.0,
	"mage": 45.0,
}


static func projectile_rotation_offset(class_id: int) -> float:
	var idx := clampi(class_id, 0, CLASS_KEYS.size() - 1)
	return deg_to_rad(_PROJECTILE_ROT_OFFSET_DEG.get(CLASS_KEYS[idx], 0.0))


## Build (cached) SpriteFrames from a sheet directory. `fallbacks` maps
## required animation base names to alias candidates used when the sheet
## lacks them. Returns null when the directory/meta.json is missing.
static func load_sheet(dir_path: String, fallbacks: Dictionary) -> SpriteFrames:
	if _sheet_cache.has(dir_path):
		return _sheet_cache[dir_path]
	var meta_path := dir_path + "/meta.json"
	if not ResourceLoader.exists(dir_path.path_join("meta.json"), "JSON") \
			and not FileAccess.file_exists(meta_path):
		push_warning("SheetLibrary: no sheet at %s" % dir_path)
		_sheet_cache[dir_path] = null
		return null
	var meta_text := FileAccess.get_file_as_string(meta_path)
	var meta: Dictionary = JSON.parse_string(meta_text)
	if meta == null:
		push_error("SheetLibrary: bad meta.json at %s" % dir_path)
		_sheet_cache[dir_path] = null
		return null

	var canvas: Array = meta["canvas"]
	var directional: bool = meta.get("directional", false)
	var rows := DIR_ORDER.size() if directional else 1
	var frames := SpriteFrames.new()
	frames.remove_animation("default")

	var anims: Dictionary = meta["anims"]
	for anim_name: String in anims.keys():
		var info: Dictionary = anims[anim_name]
		var texture: Texture2D = load(dir_path + "/" + String(info["png"]))
		if texture == null:
			push_error("SheetLibrary: missing %s/%s" % [dir_path, info["png"]])
			continue
		var n_frames := int(info["frames"])
		var fps := float(info.get("fps", 10.0))
		var loop := bool(info.get("loop", true))
		for row in rows:
			var sf_name := _sf_name(anim_name, row, directional)
			frames.add_animation(sf_name)
			frames.set_animation_speed(sf_name, fps)
			frames.set_animation_loop(sf_name, loop)
			for col in n_frames:
				var atlas := AtlasTexture.new()
				atlas.atlas = texture
				atlas.region = Rect2(
					col * int(canvas[0]), row * int(canvas[1]),
					int(canvas[0]), int(canvas[1])
				)
				frames.add_frame(sf_name, atlas)

	_apply_fallbacks(frames, anims, fallbacks, rows, directional)
	_sheet_cache[dir_path] = frames
	return frames


## Row index (0-7) for a facing angle in radians (0 = east, CW, +Y down).
static func row_from_angle(angle: float) -> int:
	var octant := wrapi(roundi(angle / (PI / 4.0)), 0, 8)
	return OCTANT_TO_ROW[octant]


## SpriteFrames animation name for a base + facing row.
static func anim_for(base: String, row: int, directional: bool = true) -> String:
	return _sf_name(base, row, directional)


static func _sf_name(base: String, row: int, directional: bool) -> String:
	return "%s_%d" % [base, row] if directional else base


static func _apply_fallbacks(
	frames: SpriteFrames, present: Dictionary, fallbacks: Dictionary,
	rows: int, directional: bool
) -> void:
	for base: String in fallbacks.keys():
		if present.has(base):
			continue
		var target := ""
		for candidate: String in fallbacks[base]:
			if present.has(candidate):
				target = candidate
				break
		if target.is_empty():
			continue
		for row in rows:
			var src := _sf_name(target, row, directional)
			var dst := _sf_name(base, row, directional)
			if frames.has_animation(dst) or not frames.has_animation(src):
				continue
			frames.add_animation(dst)
			frames.set_animation_speed(dst, frames.get_animation_speed(src))
			frames.set_animation_loop(dst, frames.get_animation_loop(src))
			for i in frames.get_frame_count(src):
				frames.add_frame(dst, frames.get_frame_texture(src, i))
