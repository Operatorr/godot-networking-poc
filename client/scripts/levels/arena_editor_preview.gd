@tool
extends Node2D
## Editor-only backdrop for arena_base.tscn so the map can be decorated WYSIWYG.
##
## arena_base.gd is NOT a @tool script (it is the big networked client controller), so in the
## editor none of its _ready()/_process()/_draw() run and the scene looks black. This small
## node fills that gap: in the editor it draws the real stone floor plus the obstacle and
## boundary walls, giving a faithful backdrop to place props against. It draws the SAME
## geometry the runtime uses by reading GameConstants.ARENA_OBSTACLES / MAP_MIN / MAP_MAX —
## which are themselves kept in lockstep with the Rust authority (rust/sim_core/src/arena.rs).
##
## It exists ONLY in the editor: at runtime _ready() frees it immediately, so the real
## builders in arena_base.gd (_setup_arena_tilemap / _build_arena_floor_decor / _draw) own the
## live look and this never double-draws or costs anything in-game.
##
## The walls drawn here are Rust-authoritative collision and must NOT be moved in Godot alone —
## changing them means editing BOTH GameConstants.ARENA_OBSTACLES and rust/sim_core/src/arena.rs.

## The seamless stone base, tiled across the arena to mirror the runtime sprite floor
## (_GroundDecorLayer in arena_base.gd). Detail decals are intentionally omitted — the base
## alone is enough context for decorating.
const GROUND_BASE_PATH := "res://assets/sprites/environment/arena/ground_stone1.png"
const GROUND_TILE_SIZE := 250.0

## Mirrors arena_base.gd's _draw() palette so the editor backdrop matches the runtime look.
const BORDER_COLOR := Color(0.6, 0.1, 0.1, 1.0)
const OBSTACLE_BODY := Color(0.15, 0.05, 0.08, 1.0)
const OBSTACLE_EDGE := Color(0.3, 0.08, 0.12, 0.6)
const BORDER_WIDTH := 4.0

var _ground_tex: Texture2D = null


func _ready() -> void:
	if not Engine.is_editor_hint():
		# Never present at runtime — the real arena builders own the live look.
		queue_free()
		return
	if ResourceLoader.exists(GROUND_BASE_PATH, "Texture2D"):
		_ground_tex = load(GROUND_BASE_PATH)
	# Sit under the authored props (z 0) so they render on top of the backdrop.
	z_index = -100
	z_as_relative = false
	queue_redraw()


func _draw() -> void:
	if not Engine.is_editor_hint():
		return

	var arena_min := GameConstants.MAP_MIN
	var arena_max := GameConstants.MAP_MAX
	var arena_rect := Rect2(arena_min, arena_max - arena_min)

	# Stone floor — tiled, the actual runtime ground look.
	if _ground_tex != null:
		var y := arena_min.y
		while y < arena_max.y:
			var x := arena_min.x
			while x < arena_max.x:
				draw_texture_rect(
					_ground_tex,
					Rect2(Vector2(x, y), Vector2(GROUND_TILE_SIZE, GROUND_TILE_SIZE)),
					false
				)
				x += GROUND_TILE_SIZE
			y += GROUND_TILE_SIZE
	else:
		# No art on this checkout — at least show the dark floor fill so the bounds read.
		draw_rect(arena_rect, Color(0.06, 0.04, 0.04, 1.0), true)

	# Rust-authoritative obstacle walls — filled blocks + edge glow (mirrors _draw_obstacles).
	for obs: Rect2 in GameConstants.ARENA_OBSTACLES:
		draw_rect(obs, OBSTACLE_BODY, true)
		draw_rect(obs, OBSTACLE_EDGE, false, 2.0)

	# Red perimeter border marking the ±1000 play bounds.
	draw_rect(arena_rect, BORDER_COLOR, false, BORDER_WIDTH)
