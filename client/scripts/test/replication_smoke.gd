extends Node


func _ready() -> void:
	var controller := InterpolationController.new()
	add_child(controller)
	controller._process_state_update({
		"server_tick": 100,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [{"entity_id": 30001, "position": Vector2(10, 0)}],
	})
	controller._process_state_update({
		"server_tick": 200,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [],
	})
	controller._handle_explicit_despawn(30001)
	controller._process_state_update({
		"server_tick": 199,
		"baseline_tick": 100,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"entities": [{"entity_id": 30001, "position": Vector2(11, 0)}],
	})
	if controller.entity_buffers.has(30001) or controller.needs_full_state_sync:
		push_error("[ReplicationSmoke] Retired delta recreated an entity or requested recovery")
		get_tree().quit(1)
		return
	controller._process_state_update({
		"server_tick": 201,
		"baseline_tick": 200,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"entities": [{"entity_id": 30002, "position": Vector2(12, 0)}],
	})
	if not controller.entity_buffers.has(30002):
		push_error("[ReplicationSmoke] Current delta was rejected")
		get_tree().quit(1)
		return
	print("[ReplicationSmoke] PASS")
	get_tree().quit(0)
