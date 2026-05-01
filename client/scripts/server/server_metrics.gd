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
	"total_bytes_sent": 0,
	"total_bytes_received": 0,
	"avg_bandwidth_per_client": 0.0,
	"last_metrics_time": 0.0,
	## Per-channel byte breakdown sampled from NetworkManager.bytes_sent_by_type
	## (§8.1). Map of MessageType -> bytes since server start; consumers diff
	## against a previous snapshot to derive bytes/sec per channel.
	"bytes_sent_by_type": {}
}

var _tick_times: Array[float] = []
const METRICS_SAMPLE_SIZE := 30  # Track last 30 ticks for averaging

# Bandwidth rate tracking (bytes/sec)
var _prev_total_peer_bytes: int = 0
var _prev_metrics_time: float = 0.0


func _init() -> void:
	var now := Time.get_ticks_msec() / 1000.0
	metrics.last_metrics_time = now
	_prev_metrics_time = now
	_prev_total_peer_bytes = 0


## Record tick processing time
func record_tick_time(time_ms: float) -> void:
	_tick_times.append(time_ms)
	if _tick_times.size() > METRICS_SAMPLE_SIZE:
		_tick_times.pop_front()


## Update performance metrics
func update_metrics(player_count: int, entity_count: int, tick_count: int, network_stats: Dictionary = {}) -> void:
	var now := Time.get_ticks_msec() / 1000.0
	var elapsed := now - _prev_metrics_time

	metrics.tick_count = tick_count
	metrics.player_count = player_count
	metrics.entity_count = entity_count
	metrics.total_bytes_sent = network_stats.get("bytes_sent", 0)
	metrics.total_bytes_received = network_stats.get("bytes_received", 0)
	# Per-channel byte breakdown (§8.1). Stored cumulatively; rate work is
	# left to consumers so we don't lose the absolute counter on a sample miss.
	if network_stats.has("bytes_sent_by_type"):
		metrics.bytes_sent_by_type = network_stats.bytes_sent_by_type

	# Calculate average bandwidth per client as a rate (bytes/sec)
	var peer_bytes: Dictionary = network_stats.get("peer_bytes_sent", {})
	var peer_count := peer_bytes.size()
	if peer_count > 0 and elapsed > 0.0:
		var total_peer_bytes := 0
		for pid in peer_bytes:
			total_peer_bytes += peer_bytes[pid]
		var delta_bytes := total_peer_bytes - _prev_total_peer_bytes
		if delta_bytes >= 0:
			metrics.avg_bandwidth_per_client = float(delta_bytes) / elapsed / float(peer_count)
		else:
			metrics.avg_bandwidth_per_client = 0.0
		_prev_total_peer_bytes = total_peer_bytes
	else:
		metrics.avg_bandwidth_per_client = 0.0
		_prev_total_peer_bytes = 0

	if _tick_times.size() > 0:
		var total := 0.0
		var max_time := 0.0
		for t in _tick_times:
			total += t
			if t > max_time:
				max_time = t
		metrics.avg_tick_time_ms = total / _tick_times.size()
		metrics.max_tick_time_ms = max_time

	metrics.last_metrics_time = now
	_prev_metrics_time = now

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
	_prev_total_peer_bytes = 0
	_prev_metrics_time = Time.get_ticks_msec() / 1000.0
	metrics = {
		"tick_count": 0,
		"avg_tick_time_ms": 0.0,
		"max_tick_time_ms": 0.0,
		"player_count": 0,
		"entity_count": 0,
		"total_bytes_sent": 0,
		"total_bytes_received": 0,
		"avg_bandwidth_per_client": 0.0,
		"last_metrics_time": _prev_metrics_time,
		"bytes_sent_by_type": {}
	}
