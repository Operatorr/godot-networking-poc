## DazeIndicator - Procedural "circling stars" status visual floating above a
## player's head while the daze status effect is active (ENTITY_FLAG_DAZED on
## remote players; the MovementStateMachine daze timer on the local player).
## Pure _draw, no assets. top_level so it neither rotates with an aiming body
## nor orbits it. To track the parent's RENDERED position without judder it
## anchors two ways (Node2D has no get_global_transform_interpolated()):
## - parent physics-interpolated (local player): sample the parent position at
##   physics ticks and lerp by Engine.get_physics_interpolation_fraction() —
##   the same blend the engine renders the body with.
## - parent interpolation OFF (remote entities, written per render frame by the
##   InterpolationController): follow parent.global_position directly.
class_name DazeIndicator
extends Node2D

const STAR_COUNT := 3
const ORBIT_RADIUS_X := 13.0
const ORBIT_RADIUS_Y := 4.0
const ORBIT_SPEED := 5.0  ## radians per second
const STAR_SIZE := 4.0
const STAR_COLOR := Color(1.0, 0.9, 0.25)
const STAR_OUTLINE_COLOR := Color(0.45, 0.33, 0.05)
const HEAD_OFFSET := Vector2(0.0, -28.0)

var _phase := 0.0
var _prev_parent_pos := Vector2.ZERO
var _curr_parent_pos := Vector2.ZERO
var _has_samples := false


func _ready() -> void:
	top_level = true
	visible = false
	z_index = 10
	# This node positions itself in _process; keep the engine's physics
	# interpolation from re-blending those writes.
	physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	set_process(false)
	set_physics_process(false)


func set_active(active: bool) -> void:
	if visible == active:
		return
	visible = active
	set_process(active)
	set_physics_process(active)
	if active:
		_phase = 0.0
		_has_samples = false
		_follow_parent()
	queue_redraw()


func _physics_process(_delta: float) -> void:
	var parent := get_parent() as Node2D
	if parent == null:
		return
	_prev_parent_pos = _curr_parent_pos if _has_samples else parent.global_position
	_curr_parent_pos = parent.global_position
	_has_samples = true


func _process(delta: float) -> void:
	_phase += delta * ORBIT_SPEED
	_follow_parent()
	queue_redraw()


func _follow_parent() -> void:
	var parent := get_parent() as Node2D
	if parent == null:
		return
	var anchor: Vector2
	if not _has_samples \
			or parent.physics_interpolation_mode == Node.PHYSICS_INTERPOLATION_MODE_OFF:
		anchor = parent.global_position
	else:
		anchor = _prev_parent_pos.lerp(
			_curr_parent_pos, Engine.get_physics_interpolation_fraction())
	global_position = anchor + HEAD_OFFSET


func _draw() -> void:
	# Draw back-half stars first so front stars overlap them (pseudo-3D orbit).
	var order := range(STAR_COUNT)
	order.sort_custom(func(a: int, b: int) -> bool:
		return sin(_phase + TAU * float(a) / STAR_COUNT) < sin(_phase + TAU * float(b) / STAR_COUNT))
	for i: int in order:
		var angle := _phase + TAU * float(i) / STAR_COUNT
		var pos := Vector2(cos(angle) * ORBIT_RADIUS_X, sin(angle) * ORBIT_RADIUS_Y)
		var depth := 0.7 + 0.3 * sin(angle)  # back of the ellipse draws smaller
		_draw_star(pos, STAR_SIZE * depth)


func _draw_star(center: Vector2, size: float) -> void:
	var points := PackedVector2Array()
	for i in 10:
		var r := size if i % 2 == 0 else size * 0.45
		var a := -PI / 2.0 + TAU * float(i) / 10.0
		points.append(center + Vector2(cos(a), sin(a)) * r)
	draw_colored_polygon(points, STAR_COLOR)
	points.append(points[0])
	draw_polyline(points, STAR_OUTLINE_COLOR, 1.0)
