extends Node


func _ready() -> void:
	var controller := InterpolationController.new()
	add_child(controller)
	var container := Node2D.new()
	add_child(container)
	var entity_manager := ClientEntityManager.new()
	add_child(entity_manager)
	entity_manager.setup(container, controller)
	var despawned: Array[int] = []
	controller.entity_despawned.connect(func(entity_id: int) -> void: despawned.append(entity_id))
	controller._process_state_update({
		"server_tick": 100,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [_monster(30001, Vector2(10, 0)), _monster(30003, Vector2(20, 0))],
	})
	if not entity_manager.monster_entities.has(30001) or not entity_manager.monster_entities.has(30003):
		_fail("Initial Baseline did not spawn monster visuals")
		return
	var removed_visual: Monster = entity_manager.monster_entities[30001]
	var retained_visual: Monster = entity_manager.monster_entities[30003]
	var retained_buffer: EntityStateBuffer = controller.entity_buffers[30003]
	controller._process_state_update({
		"server_tick": 200,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [_monster(30003, Vector2(21, 0))],
	})
	if controller.entity_buffers.has(30001) or controller.entity_last_states.has(30001) \
		or controller.missing_update_count.has(30001) or controller.entity_nodes.has(30001) \
		or entity_manager.monster_entities.has(30001) or not removed_visual.is_queued_for_deletion() \
		or despawned != [30001]:
		_fail("Replacement Baseline did not immediately retire the omitted entity and visual")
		return
	if controller.entity_buffers.get(30003) != retained_buffer \
		or entity_manager.monster_entities.get(30003) != retained_visual:
		_fail("Replacement Baseline recreated an entity that was still present")
		return
	controller._process_state_update({
		"server_tick": 199,
		"baseline_tick": 100,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"entities": [_monster(30001, Vector2(11, 0))],
	})
	if controller.entity_buffers.has(30001) or controller.needs_full_state_sync:
		_fail("Retired delta recreated an entity or requested recovery")
		return
	controller._process_state_update({
		"server_tick": 150,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [_monster(30001, Vector2(11, 0))],
	})
	if controller.entity_buffers.has(30001) or not controller.entity_buffers.has(30003) \
		or controller.last_baseline_tick != 200 or despawned != [30001]:
		_fail("Retired Baseline changed the current entity set")
		return
	controller._process_state_update({
		"server_tick": 201,
		"baseline_tick": 200,
		"state_flags": PacketTypes.STATE_FLAG_IS_DELTA,
		"entities": [_monster(30002, Vector2(12, 0))],
	})
	if not controller.entity_buffers.has(30002) or not controller.entity_buffers.has(30003):
		_fail("Current delta was rejected or removed an unchanged entity")
		return
	controller._process_state_update({
		"server_tick": 300,
		"state_flags": PacketTypes.STATE_FLAG_BASELINE,
		"entities": [],
	})
	if not controller.entity_buffers.is_empty() or not controller.entity_last_states.is_empty() \
		or not controller.entity_nodes.is_empty() or not controller.missing_update_count.is_empty() \
		or not entity_manager.monster_entities.is_empty() or despawned.size() != 3:
		_fail("Empty Baseline did not retire every remaining entity")
		return
	print("[ReplicationSmoke] PASS")
	get_tree().quit(0)


func _monster(entity_id: int, position: Vector2) -> Dictionary:
	return {"entity_id": entity_id, "entity_type": PacketTypes.EntityType.MONSTER, "position": position}


func _fail(message: String) -> void:
	push_error("[ReplicationSmoke] " + message)
	get_tree().quit(1)
