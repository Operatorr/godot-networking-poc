## SpatialGrid - Reusable uniform spatial-hash broad-phase (#9).
##
## Stores opaque items keyed by an externally-supplied position, so it works for
## both the AoI scan (which holds `Array[Dictionary]` entity-data) and the
## projectile collision path (which holds state objects). The grid only narrows
## the candidate set; the exact distance/hysteresis test stays in the caller.
class_name SpatialGrid
extends RefCounted

var cell_size: float = 64.0
var _grid: Dictionary = {}  # Vector2i -> Array (items)


func _init(p_cell_size: float = 64.0) -> void:
	cell_size = maxf(p_cell_size, 1.0)


func clear() -> void:
	_grid.clear()


func _cell_of(pos: Vector2) -> Vector2i:
	return Vector2i(floori(pos.x / cell_size), floori(pos.y / cell_size))


## Insert an opaque item at a world position. An item lands in exactly one cell,
## so neighbourhood/radius queries never produce duplicates.
func insert(item: Variant, pos: Vector2) -> void:
	var cell := _cell_of(pos)
	if not _grid.has(cell):
		_grid[cell] = []
	_grid[cell].append(item)


## 3x3 (ring=1) neighbourhood broad-phase — the equivalent of
## projectile_manager._query_nearby. NO distance filter; the caller does the
## precise hit test.
func query_cell_neighbourhood(pos: Vector2, ring: int = 1) -> Array:
	var result: Array = []
	var c := _cell_of(pos)
	for dx in range(-ring, ring + 1):
		for dy in range(-ring, ring + 1):
			var cell := Vector2i(c.x + dx, c.y + dy)
			if _grid.has(cell):
				result.append_array(_grid[cell])
	return result


## Radius query for AoI: collect every item in the cell band covering `radius`.
## Returns the candidate superset bounded by the cell ring — the AoI caller keeps
## its existing distance_squared + hysteresis check, so visibility semantics are
## unchanged.
func query_radius(center: Vector2, radius: float) -> Array:
	var result: Array = []
	var r_cells := ceili(radius / cell_size)
	var c := _cell_of(center)
	for dx in range(-r_cells, r_cells + 1):
		for dy in range(-r_cells, r_cells + 1):
			var cell := Vector2i(c.x + dx, c.y + dy)
			if _grid.has(cell):
				result.append_array(_grid[cell])
	return result
