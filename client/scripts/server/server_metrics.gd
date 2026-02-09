## ServerMetrics - Tracks server performance metrics
## Extracted from ServerMain to isolate metrics/diagnostics concerns
class_name ServerMetrics
extends RefCounted

var debug_logging: bool = false

## Performance metrics
var metrics: Dictionary = {
	"tick_count": 0,
	"avg_tick_time_ms": 0.0,
	"max_tick_time_ms": 0.0,
	"player_count": 0,
	"entity_count": 0,
	"last_metrics_time": 0.0
}

var _tick_times: Array[float] = []
const METRICS_SAMPLE_SIZE := 30  # Track last 30 ticks for averaging


func _init() -> void:
	metrics.last_metrics_time = Time.get_ticks_msec() / 1000.0


## Record tick processing time
func record_tick_time(time_ms: float) -> void:
	_tick_times.append(time_ms)
	if _tick_times.size() > METRICS_SAMPLE_SIZE:
		_tick_times.pop_front()


## Update performance metrics
func update_metrics(player_count: int, entity_count: int, tick_count: int) -> void:
	metrics.tick_count = tick_count
	metrics.player_count = player_count
	metrics.entity_count = entity_count

	if _tick_times.size() > 0:
		var total := 0.0
		var max_time := 0.0
		for t in _tick_times:
			total += t
			if t > max_time:
				max_time = t
		metrics.avg_tick_time_ms = total / _tick_times.size()
		metrics.max_tick_time_ms = max_time

	metrics.last_metrics_time = Time.get_ticks_msec() / 1000.0

	if debug_logging:
		print_metrics(tick_count)


## Print current server metrics
func print_metrics(tick_count: int) -> void:
	print("[ServerMetrics] Tick: %d | Players: %d | Entities: %d | Avg: %.2fms | Max: %.2fms" % [
		tick_count,
		metrics.player_count,
		metrics.entity_count,
		metrics.avg_tick_time_ms,
		metrics.max_tick_time_ms
	])


## Get current metrics
func get_metrics() -> Dictionary:
	return metrics.duplicate()


## Clear all tracking data
func clear() -> void:
	_tick_times.clear()
	metrics = {
		"tick_count": 0,
		"avg_tick_time_ms": 0.0,
		"max_tick_time_ms": 0.0,
		"player_count": 0,
		"entity_count": 0,
		"last_metrics_time": 0.0
	}
