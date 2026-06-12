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
var _dead_monster_effects_played: Dictionary = {}

## Projectile pool for network projectiles (separate from local player pool)
var _projectile_pool: Array[Projectile] = []
var _active_projectiles: Dictionary = {}  # entity_id -> Projectile
## Ordered queue of active projectile entity IDs by spawn time (oldest first)
var _active_projectile_order: Array[int] = []
var _projectile_sources: Dictionary = {}  # projectile_id -> source_entity_id
const NETWORK_PROJECTILE_POOL_SIZE := 64

## Reference to the entity container in the arena scene
var entity_container: Node2D = null

## Reference to InterpolationController
var interpolation_controller: InterpolationController = null

## Track previous animation states for remote player audio triggers
var _player_prev_anim: Dictionary = {}  # entity_id -> int (AnimationState)

## Cached AudioManager reference (lazy-initialized)
var _audio_manager: Node = null

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
	if EntityNameCache and not EntityNameCache.entity_color_updated.is_connected(_on_entity_color_updated):
		EntityNameCache.entity_color_updated.connect(_on_entity_color_updated)
	if EntityNameCache and not EntityNameCache.entity_class_updated.is_connected(_on_entity_class_updated):
		EntityNameCache.entity_class_updated.connect(_on_entity_class_updated)

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


## Get cached AudioManager reference (lazy init)
func _get_audio_manager() -> Node:
	if _audio_manager == null or not is_instance_valid(_audio_manager):
		_audio_manager = get_tree().root.get_node_or_null("AudioManager")
	return _audio_manager


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
		projectile.is_active = false
		projectile.owner_pool = null
		entity_container.add_child(projectile)
		_return_projectile_to_pool(projectile)


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
	if entity_id == GameManager.get_local_player_entity_id():
		if interpolation_controller:
			interpolation_controller.forget_entity(entity_id)
		return

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
	remote_player.set_player_color(EntityNameCache.get_entity_color(entity_id))

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
	monster.died.connect(_on_monster_died.bind(entity_id))

	entity_container.add_child(monster)

	# Play monster spawn sound + effects
	var audio := _get_audio_manager()
	if audio:
		audio.play_monster_spawn()
	_spawn_monster_spawn_effects(position)
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

	_dead_monster_effects_played.erase(entity_id)

	if debug_logging:
		print("[ClientEntityManager] Despawned monster: id=%d" % entity_id)


## Apply server-authoritative monster damage for local visual feedback.
func apply_monster_damage(entity_id: int, amount: int) -> void:
	if amount <= 0 or not monster_entities.has(entity_id):
		return

	var monster: Monster = monster_entities[entity_id]
	if not is_instance_valid(monster):
		return

	monster.set_hp(maxi(monster.current_hp - amount, 0))


## Apply server-authoritative monster death feedback immediately from kill events.
func apply_monster_death(entity_id: int) -> void:
	if not monster_entities.has(entity_id):
		return

	var monster: Monster = monster_entities[entity_id]
	if not is_instance_valid(monster):
		return

	monster.current_hp = 0
	monster.queue_redraw()
	monster.visible = false
	_play_monster_death_once(entity_id, monster.global_position)


## Spawn a projectile from pool
func _spawn_projectile(entity_id: int, position: Vector2) -> void:
	if _active_projectiles.has(entity_id):
		return

	var projectile := _get_pooled_projectile()
	if projectile == null:
		return

	projectile.global_position = position
	projectile.reset_projectile_color()
	projectile.process_mode = Node.PROCESS_MODE_DISABLED  # Server controls movement
	projectile.visible = true
	projectile.monitoring = false  # Client doesn't detect collisions
	projectile.monitorable = false

	_active_projectiles[entity_id] = projectile
	_active_projectile_order.append(entity_id)
	_apply_projectile_color(entity_id)

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
	_active_projectile_order.erase(entity_id)
	_projectile_sources.erase(entity_id)

	if interpolation_controller:
		interpolation_controller.unregister_entity_node(entity_id)

	if is_instance_valid(projectile):
		projectile.process_mode = Node.PROCESS_MODE_DISABLED
		projectile.visible = false
		projectile.monitoring = false
		projectile.monitorable = false
		projectile.is_active = false
		projectile.owner_pool = null
		projectile.reset_projectile_color()
		_return_projectile_to_pool(projectile)

	if debug_logging:
		print("[ClientEntityManager] Despawned projectile: id=%d" % entity_id)


## Get a projectile from the pool, evicting the oldest active if exhausted
func _get_pooled_projectile() -> Projectile:
	if _projectile_pool.is_empty():
		# Pool exhausted - recycle oldest active by spawn time
		if _active_projectile_order.is_empty():
			push_warning("[ClientEntityManager] No projectiles available")
			return null

		var oldest_id: int = _active_projectile_order[0]
		_despawn_projectile(oldest_id)

		if _projectile_pool.is_empty():
			return null

	return _projectile_pool.pop_back()


## Return a network projectile to the inactive pool without duplicating it
func _return_projectile_to_pool(projectile: Projectile) -> void:
	if projectile == null or _projectile_pool.has(projectile):
		return

	_projectile_pool.append(projectile)


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

		# Detect animation state transitions for audio + effects
		var prev_anim: int = _player_prev_anim.get(entity_id, PacketTypes.AnimationState.IDLE)
		if anim_state != prev_anim:
			_play_remote_player_audio(anim_state)
			if anim_state == PacketTypes.AnimationState.HIT:
				_spawn_remote_hit_sparks(entity_id)
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
	_dead_monster_effects_played.clear()

	# Return all projectiles to pool
	for entity_id: int in _active_projectiles.keys():
		var projectile: Projectile = _active_projectiles[entity_id]
		if is_instance_valid(projectile):
			projectile.visible = false
			projectile.process_mode = Node.PROCESS_MODE_DISABLED
			projectile.monitoring = false
			projectile.monitorable = false
			projectile.is_active = false
			projectile.owner_pool = null
			projectile.reset_projectile_color()
			_return_projectile_to_pool(projectile)
	_active_projectiles.clear()
	_active_projectile_order.clear()
	_projectile_sources.clear()

	if debug_logging:
		print("[ClientEntityManager] All entities cleared")


## Handle monster taking damage (play audio)
func _on_monster_took_damage(_amount: int) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_monster_hit()


## Handle monster death (play audio + effects)
func _on_monster_died(entity_id: int) -> void:
	if not monster_entities.has(entity_id):
		return

	var monster: Monster = monster_entities[entity_id]
	if not is_instance_valid(monster):
		return

	_play_monster_death_once(entity_id, monster.global_position)


## Play monster death effects once for a network entity.
func _play_monster_death_once(entity_id: int, pos: Vector2) -> void:
	if _dead_monster_effects_played.has(entity_id):
		return

	_dead_monster_effects_played[entity_id] = true
	var audio := _get_audio_manager()
	if audio:
		audio.play_monster_death()
	_spawn_monster_death_effects(pos)


## Spawn death particles for a monster at position
func _spawn_monster_death_effects(pos: Vector2) -> void:
	if entity_container == null:
		return
	var death_fx := ParticleEffects.create_death_explosion(pos, Color(0.8, 0.13, 0.13))
	entity_container.add_child(death_fx)
	var gore := ParticleEffects.create_gore_splatter(pos)
	entity_container.add_child(gore)


## Spawn spawn particles for a monster at position
func _spawn_monster_spawn_effects(pos: Vector2) -> void:
	if entity_container == null:
		return
	var spawn_fx := ParticleEffects.create_spawn_effect(pos, Color(0.8, 0.13, 0.13))
	entity_container.add_child(spawn_fx)


## Play audio for remote player hit/death animation state transitions.
## Shoot sounds are driven by authoritative PROJECTILE_FIRED events so held
## attack animations do not miss repeated shots or double-play with events.
func _play_remote_player_audio(anim_state: int) -> void:
	var audio := _get_audio_manager()
	if audio == null:
		return

	match anim_state:
		PacketTypes.AnimationState.HIT:
			audio.play_player_hit()
		PacketTypes.AnimationState.DEATH:
			audio.play_player_death()


## Spawn hit sparks for a remote player
func _spawn_remote_hit_sparks(entity_id: int) -> void:
	if not player_entities.has(entity_id) or entity_container == null:
		return
	var player: RemotePlayer = player_entities[entity_id]
	if is_instance_valid(player):
		var sparks := ParticleEffects.create_hit_sparks(player.global_position, Color(0.6, 0.27, 0.8))
		entity_container.add_child(sparks)


## Handle projectile hit (play impact audio)
func _on_projectile_hit(_body: Node2D) -> void:
	var audio := _get_audio_manager()
	if audio:
		audio.play_projectile_impact()


## Register authoritative projectile ownership from PROJECTILE_FIRED events.
func register_projectile_source(projectile_id: int, source_entity_id: int) -> void:
	if projectile_id <= 0 or source_entity_id <= 0:
		return
	_projectile_sources[projectile_id] = source_entity_id
	_apply_projectile_color(projectile_id)


## Snapshots of live monster-fired projectiles for client-side incoming-hit
## detection: [{ "id": int, "position": Vector2 }]. Only projectiles whose source
## is known to be a monster and that are currently visible are returned, so a
## locally-consumed (hidden) bullet is naturally excluded. Used by LocalHitDetector.
func get_monster_projectile_snapshots() -> Array:
	var result: Array = []
	for projectile_id: int in _active_projectiles.keys():
		var source_id: int = _projectile_sources.get(projectile_id, -1)
		# Shared Rust sim_core predicate (D11); unknown source (-1) is never client-auth.
		if not SimHit.is_client_authoritative(source_id):
			continue
		var projectile: Projectile = _active_projectiles[projectile_id]
		if not is_instance_valid(projectile) or not projectile.visible:
			continue
		result.append({ "id": projectile_id, "position": projectile.global_position })
	return result


## Hide a projectile immediately after the local player reports being hit by it,
## so the dodge/impact feels instant. The authoritative despawn follows when the
## server validates the report and removes the projectile for everyone.
func hide_projectile_locally(projectile_id: int) -> void:
	var projectile: Projectile = _active_projectiles.get(projectile_id, null)
	if is_instance_valid(projectile):
		projectile.visible = false


## Re-show a projectile that was hidden by a hit report the server did NOT honour
## (rejected as implausible, or the report was lost). Without this the bullet would
## stay invisible and undetectable for the rest of its life. See LocalHitDetector.
func show_projectile_locally(projectile_id: int) -> void:
	var projectile: Projectile = _active_projectiles.get(projectile_id, null)
	if is_instance_valid(projectile):
		projectile.visible = true


## Is a projectile still live on the client? After a hit report, a still-active
## projectile means the server did not despawn it (report rejected/lost); a gone
## projectile means the server confirmed the hit and removed it for everyone.
func is_projectile_active(projectile_id: int) -> bool:
	return is_instance_valid(_active_projectiles.get(projectile_id, null))


func _apply_projectile_color(projectile_id: int) -> void:
	if not _active_projectiles.has(projectile_id):
		return
	var source_id: int = _projectile_sources.get(projectile_id, -1)
	if source_id <= 0 or source_id >= GameConstants.MONSTER_ENTITY_ID_START:
		return
	var projectile: Projectile = _active_projectiles[projectile_id]
	if is_instance_valid(projectile):
		projectile.set_projectile_color(_get_player_color(source_id))
		projectile.set_projectile_class(_get_player_class(source_id))


func _get_player_color(entity_id: int) -> Color:
	if entity_id == GameManager.get_local_player_entity_id():
		return GameManager.player_data.get("player_color", Color(0.27, 0.53, 1.0))
	return EntityNameCache.get_entity_color(entity_id)


func _get_player_class(entity_id: int) -> int:
	if entity_id == GameManager.get_local_player_entity_id():
		return GameManager.player_data.get("player_class", PacketTypes.PlayerClass.ZEALOT)
	return EntityNameCache.get_entity_class(entity_id)


func _on_entity_color_updated(entity_id: int, player_color: Color) -> void:
	if player_entities.has(entity_id):
		var remote_player: RemotePlayer = player_entities[entity_id]
		if is_instance_valid(remote_player):
			remote_player.set_player_color(player_color)

	for projectile_id: int in _projectile_sources.keys():
		if int(_projectile_sources[projectile_id]) == entity_id:
			_apply_projectile_color(projectile_id)


## Late PLAYER_INFO class updates propagate like color updates. RemotePlayer does not expose
## set_player_class yet (sprite selection is wired separately), so the call is guarded — once
## the visual hook lands, this handler feeds it without further changes here.
func _on_entity_class_updated(entity_id: int, player_class: int) -> void:
	if player_entities.has(entity_id):
		var remote_player: RemotePlayer = player_entities[entity_id]
		if is_instance_valid(remote_player) and remote_player.has_method("set_player_class"):
			remote_player.call("set_player_class", player_class)


## Get entity counts for debug
func get_debug_info() -> Dictionary:
	return {
		"remote_players": player_entities.size(),
		"monsters": monster_entities.size(),
		"active_projectiles": _active_projectiles.size(),
		"pooled_projectiles": _projectile_pool.size()
	}
