## ClientEntityManager - Manages client-side visual entity lifecycle
## Bridges InterpolationController signals to visual scene nodes
## Creates/destroys Player, Monster, and Projectile visuals in the arena
class_name ClientEntityManager
extends Node

## Scene references for entity instantiation
const REMOTE_PLAYER_SCENE := "res://scenes/shared/player/remote_player.tscn"
const MONSTER_SCENE := "res://scenes/shared/monster/monster.tscn"
const PROJECTILE_SCENE := "res://scenes/shared/projectile/projectile.tscn"

## Preloaded scenes
var _remote_player_packed: PackedScene = null
var _monster_packed: PackedScene = null
var _projectile_packed: PackedScene = null

## Active entity nodes: entity_id -> Node2D
var player_entities: Dictionary = {}
var monster_entities: Dictionary = {}

## Projectile pool for network projectiles (separate from local player pool)
var _projectile_pool: Array[Projectile] = []
var _active_projectiles: Dictionary = {}  # entity_id -> Projectile
const NETWORK_PROJECTILE_POOL_SIZE := 64

## Reference to the entity container in the arena scene
var entity_container: Node2D = null

## Reference to InterpolationController
var interpolation_controller: InterpolationController = null

## Track previous animation states for remote player audio triggers
var _player_prev_anim: Dictionary = {}  # entity_id -> int (AnimationState)

## Debug logging
var debug_logging: bool = false


func _ready() -> void:
	_preload_scenes()


## Initialize with arena references
func setup(container: Node2D, interp_controller: InterpolationController) -> void:
	entity_container = container
	interpolation_controller = interp_controller

	if interpolation_controller:
		interpolation_controller.entity_spawned.connect(_on_entity_spawned)
		interpolation_controller.entity_despawned.connect(_on_entity_despawned)

	# Pre-allocate projectile pool
	_initialize_projectile_pool()

	if debug_logging:
		print("[ClientEntityManager] Setup complete")


## Preload entity scenes
func _preload_scenes() -> void:
	_remote_player_packed = load(REMOTE_PLAYER_SCENE)
	_monster_packed = load(MONSTER_SCENE)
	_projectile_packed = load(PROJECTILE_SCENE)

	if _remote_player_packed == null:
		push_error("[ClientEntityManager] Failed to load remote player scene")
	if _monster_packed == null:
		push_error("[ClientEntityManager] Failed to load monster scene")
	if _projectile_packed == null:
		push_error("[ClientEntityManager] Failed to load projectile scene")


## Initialize projectile pool for network-spawned projectiles
func _initialize_projectile_pool() -> void:
	if _projectile_packed == null or entity_container == null:
		return

	for i in range(NETWORK_PROJECTILE_POOL_SIZE):
		var projectile: Projectile = _projectile_packed.instantiate()
		projectile.process_mode = Node.PROCESS_MODE_DISABLED
		projectile.visible = false
		projectile.monitoring = false
		projectile.monitorable = false
		entity_container.add_child(projectile)
		_projectile_pool.append(projectile)


## Handle entity spawn from InterpolationController
func _on_entity_spawned(entity_id: int, entity_type: int, initial_position: Vector2) -> void:
	match entity_type:
		PacketTypes.EntityType.PLAYER:
			_spawn_remote_player(entity_id, initial_position)
		PacketTypes.EntityType.MONSTER:
			_spawn_monster(entity_id, initial_position)
		PacketTypes.EntityType.PROJECTILE:
			_spawn_projectile(entity_id, initial_position)
		_:
			if debug_logging:
				print("[ClientEntityManager] Unknown entity type: %d" % entity_type)


## Handle entity despawn from InterpolationController
func _on_entity_despawned(entity_id: int) -> void:
	if player_entities.has(entity_id):
		_despawn_remote_player(entity_id)
	elif monster_entities.has(entity_id):
		_despawn_monster(entity_id)
	elif _active_projectiles.has(entity_id):
		_despawn_projectile(entity_id)


## Spawn a remote player visual
func _spawn_remote_player(entity_id: int, position: Vector2) -> void:
	if player_entities.has(entity_id):
		return

	if _remote_player_packed == null or entity_container == null:
		return

	var remote_player: RemotePlayer = _remote_player_packed.instantiate()
	remote_player.entity_id = entity_id
	remote_player.position = position

	# Try to get character name from EntityNameCache
	var cached_name := EntityNameCache.get_entity_name(entity_id)
	remote_player.set_character_name(cached_name)

	entity_container.add_child(remote_player)
	player_entities[entity_id] = remote_player

	# Register with InterpolationController for position updates
	if interpolation_controller:
		interpolation_controller.register_entity_node(entity_id, remote_player)

	if debug_logging:
		print("[ClientEntityManager] Spawned remote player: id=%d, name=%s, pos=%s" % [
			entity_id, cached_name, position
		])


## Despawn a remote player visual
func _despawn_remote_player(entity_id: int) -> void:
	if not player_entities.has(entity_id):
		return

	var remote_player: RemotePlayer = player_entities[entity_id]
	player_entities.erase(entity_id)
	_player_prev_anim.erase(entity_id)

	if interpolation_controller:
		interpolation_controller.unregister_entity_node(entity_id)

	if is_instance_valid(remote_player):
		remote_player.queue_free()

	if debug_logging:
		print("[ClientEntityManager] Despawned remote player: id=%d" % entity_id)


## Spawn a monster visual
func _spawn_monster(entity_id: int, position: Vector2) -> void:
	if monster_entities.has(entity_id):
		return

	if _monster_packed == null or entity_container == null:
		return

	var monster: Monster = _monster_packed.instantiate()
	monster.entity_id = entity_id
	monster.position = position

	# Connect monster signals for audio feedback
	monster.took_damage.connect(_on_monster_took_damage)
	monster.died.connect(_on_monster_died)

	entity_container.add_child(monster)

	# Play monster spawn sound
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.play_monster_spawn()
	monster_entities[entity_id] = monster

	# Register with InterpolationController for position updates
	if interpolation_controller:
		interpolation_controller.register_entity_node(entity_id, monster)

	if debug_logging:
		print("[ClientEntityManager] Spawned monster: id=%d, pos=%s" % [entity_id, position])


## Despawn a monster visual
func _despawn_monster(entity_id: int) -> void:
	if not monster_entities.has(entity_id):
		return

	var monster: Monster = monster_entities[entity_id]
	monster_entities.erase(entity_id)

	if interpolation_controller:
		interpolation_controller.unregister_entity_node(entity_id)

	if is_instance_valid(monster):
		monster.queue_free()

	if debug_logging:
		print("[ClientEntityManager] Despawned monster: id=%d" % entity_id)


## Spawn a projectile from pool
func _spawn_projectile(entity_id: int, position: Vector2) -> void:
	if _active_projectiles.has(entity_id):
		return

	var projectile := _get_pooled_projectile()
	if projectile == null:
		return

	projectile.global_position = position
	projectile.process_mode = Node.PROCESS_MODE_DISABLED  # Server controls movement
	projectile.visible = true
	projectile.monitoring = false  # Client doesn't detect collisions
	projectile.monitorable = false

	_active_projectiles[entity_id] = projectile

	# Connect projectile hit signal for impact audio
	if projectile.hit.is_connected(_on_projectile_hit) == false:
		projectile.hit.connect(_on_projectile_hit)

	# Register with InterpolationController for position updates
	if interpolation_controller:
		interpolation_controller.register_entity_node(entity_id, projectile)

	if debug_logging:
		print("[ClientEntityManager] Spawned projectile: id=%d, pos=%s" % [entity_id, position])


## Despawn a projectile (return to pool)
func _despawn_projectile(entity_id: int) -> void:
	if not _active_projectiles.has(entity_id):
		return

	var projectile: Projectile = _active_projectiles[entity_id]
	_active_projectiles.erase(entity_id)

	if interpolation_controller:
		interpolation_controller.unregister_entity_node(entity_id)

	if is_instance_valid(projectile):
		projectile.process_mode = Node.PROCESS_MODE_DISABLED
		projectile.visible = false
		projectile.monitoring = false
		projectile.monitorable = false
		_projectile_pool.append(projectile)

	if debug_logging:
		print("[ClientEntityManager] Despawned projectile: id=%d" % entity_id)


## Get a projectile from the pool
func _get_pooled_projectile() -> Projectile:
	if _projectile_pool.is_empty():
		# Pool exhausted - recycle oldest active
		if _active_projectiles.is_empty():
			push_warning("[ClientEntityManager] No projectiles available")
			return null

		var oldest_id: int = _active_projectiles.keys()[0]
		_despawn_projectile(oldest_id)

		if _projectile_pool.is_empty():
			return null

	return _projectile_pool.pop_back()


## Update animation/flag state for entities from InterpolationController
## Called each frame to sync visual state
func update_entity_visuals() -> void:
	if interpolation_controller == null:
		return

	# Update remote player visuals
	for entity_id: int in player_entities.keys():
		var remote_player: RemotePlayer = player_entities[entity_id]
		if not is_instance_valid(remote_player):
			player_entities.erase(entity_id)
			_player_prev_anim.erase(entity_id)
			continue

		var anim_state := interpolation_controller.get_entity_animation_state(entity_id)
		var flags := interpolation_controller.get_entity_flags(entity_id)
		remote_player.update_from_network(anim_state, flags)

		# Detect animation state transitions for audio
		var prev_anim: int = _player_prev_anim.get(entity_id, PacketTypes.AnimationState.IDLE)
		if anim_state != prev_anim:
			_play_remote_player_audio(anim_state)
			_player_prev_anim[entity_id] = anim_state

	# Update monster visuals
	for entity_id: int in monster_entities.keys():
		var monster: Monster = monster_entities[entity_id]
		if not is_instance_valid(monster):
			monster_entities.erase(entity_id)
			continue

		var anim_state := interpolation_controller.get_entity_animation_state(entity_id)
		var flags := interpolation_controller.get_entity_flags(entity_id)
		monster.update_from_network(anim_state, flags)


## Clear all managed entities
func clear_all() -> void:
	# Free remote players
	for entity_id: int in player_entities.keys():
		var node = player_entities[entity_id]
		if is_instance_valid(node):
			node.queue_free()
	player_entities.clear()
	_player_prev_anim.clear()

	# Free monsters
	for entity_id: int in monster_entities.keys():
		var node = monster_entities[entity_id]
		if is_instance_valid(node):
			node.queue_free()
	monster_entities.clear()

	# Return all projectiles to pool
	for entity_id: int in _active_projectiles.keys():
		var projectile: Projectile = _active_projectiles[entity_id]
		if is_instance_valid(projectile):
			projectile.visible = false
			projectile.process_mode = Node.PROCESS_MODE_DISABLED
			_projectile_pool.append(projectile)
	_active_projectiles.clear()

	if debug_logging:
		print("[ClientEntityManager] All entities cleared")


## Handle monster taking damage (play audio)
func _on_monster_took_damage(_amount: int) -> void:
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.play_monster_hit()


## Handle monster death (play audio)
func _on_monster_died() -> void:
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.play_monster_death()


## Play audio for remote player animation state transitions
func _play_remote_player_audio(anim_state: int) -> void:
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio == null:
		return

	match anim_state:
		PacketTypes.AnimationState.ATTACK:
			audio.play_player_shoot()
		PacketTypes.AnimationState.HIT:
			audio.play_player_hit()
		PacketTypes.AnimationState.DEATH:
			audio.play_player_death()


## Handle projectile hit (play impact audio)
func _on_projectile_hit(_body: Node2D) -> void:
	var audio := get_tree().root.get_node_or_null("AudioManager")
	if audio:
		audio.play_projectile_impact()


## Get entity counts for debug
func get_debug_info() -> Dictionary:
	return {
		"remote_players": player_entities.size(),
		"monsters": monster_entities.size(),
		"active_projectiles": _active_projectiles.size(),
		"pooled_projectiles": _projectile_pool.size()
	}
