## ServerCollisionHandler - Handles projectile collision detection and damage/kill events
## Extracted from ServerMain to isolate collision and combat concerns
class_name ServerCollisionHandler
extends RefCounted

const ServerBroadcastService := preload("res://scripts/server/server_broadcast_service.gd")

var debug_logging: bool = false


## Process all collision checks and broadcast resulting events
func process_collisions(
	projectile_manager: ProjectileManager,
	player_manager: PlayerManager,
	monster_manager: MonsterManager,
	network_manager: Node,
	broadcast_service: ServerBroadcastService
) -> void:
	_check_player_collisions(projectile_manager, player_manager, network_manager, broadcast_service)
	_check_monster_collisions(projectile_manager, player_manager, monster_manager, network_manager)


## Check projectile-vs-player collisions, apply damage, broadcast events.
## Only player-fired (PvP) projectiles reach here — monster-fired hits on players
## are client-detected and applied via apply_player_hit from
## ServerMain._handle_local_hit_report. See docs/systems/combat-hits.md.
func _check_player_collisions(
	projectile_manager: ProjectileManager,
	player_manager: PlayerManager,
	network_manager: Node,
	broadcast_service: ServerBroadcastService
) -> void:
	var player_hits = projectile_manager.check_collisions_with_players(player_manager)

	for hit in player_hits:
		apply_player_hit(hit.owner_id, hit.target_id, player_manager, network_manager, broadcast_service, hit.get("position", Vector2.INF))


## Apply a confirmed projectile hit on a player: damage, DAMAGE broadcast, and any
## kill broadcast. Shared by the server-authoritative PvP collision path and the
## client-reported monster-hit path (ServerMain._handle_local_hit_report).
func apply_player_hit(
	owner_id: int,
	target_id: int,
	player_manager: PlayerManager,
	network_manager: Node,
	broadcast_service: ServerBroadcastService,
	impact_position: Vector2 = Vector2.INF
) -> void:
	var target := player_manager.get_player_by_entity_id(target_id)
	if target == null or not target.authenticated:
		return

	# Determine damage based on projectile owner
	var damage: int = GameConstants.PLAYER_PROJECTILE_DAMAGE
	if owner_id >= GameConstants.MONSTER_ENTITY_ID_START:
		damage = GameConstants.MONSTER_PROJECTILE_DAMAGE

	var previous_health := target.health
	var killed := target.take_damage(damage, owner_id)
	var damage_applied := previous_health - target.health
	if damage_applied <= 0:
		return

	# Knock the survivor back away from the impact point (authoritative; the
	# client predicts an identical KNOCKED_BACK via its movement state machine).
	if not killed and impact_position.is_finite():
		var knock_dir := (target.position - impact_position)
		if knock_dir.length() > 0.01:
			target.movement_sm.apply_knockback(
				knock_dir, GameConstants.PLAYER_KNOCKBACK_BASE_FORCE
			)

	# Broadcast DAMAGE event to all clients
	if network_manager:
		var damage_packet = GameEventPacket.create_damage(
			owner_id, target_id, damage_applied
		)
		network_manager.broadcast_to_clients(
			NetworkManager.MessageType.GAME_EVENT,
			damage_packet.to_dict()
		)

	if killed and network_manager:
		_broadcast_player_kill(owner_id, target_id, player_manager, network_manager, broadcast_service)

	if debug_logging:
		print("[CollisionHandler] Player %d took %d damage from entity %d (killed=%s)" % [
			target_id, damage_applied, owner_id, killed
		])


## Check projectile-vs-monster collisions, apply damage, broadcast events
func _check_monster_collisions(
	projectile_manager: ProjectileManager,
	player_manager: PlayerManager,
	monster_manager: MonsterManager,
	network_manager: Node
) -> void:
	var monster_hits = projectile_manager.check_collisions_with_monsters(monster_manager)

	for hit in monster_hits:
		var monster := monster_manager.get_monster(hit.target_id)
		if monster == null:
			continue

		var killer := player_manager.get_player_by_entity_id(hit.owner_id)

		var previous_health := monster.health
		var killed := monster.take_damage(GameConstants.PLAYER_PROJECTILE_DAMAGE)
		var damage_applied := previous_health - monster.health
		if damage_applied <= 0:
			continue

		# Broadcast DAMAGE event to all clients
		if network_manager:
			var damage_packet = GameEventPacket.create_damage(
				hit.owner_id, hit.target_id, damage_applied
			)
			network_manager.broadcast_to_clients(
				NetworkManager.MessageType.GAME_EVENT,
				damage_packet.to_dict()
			)

		# Attribute the kill only when the shooter is still tracked, but keep
		# already-fired projectiles authoritative even after death/disconnect.
		if killed:
			if killer != null and killer.authenticated:
				killer.monster_kills += 1

			if network_manager:
				var kill_packet = GameEventPacket.create_kill(
					hit.owner_id, hit.target_id
				)
				network_manager.broadcast_to_clients(
					NetworkManager.MessageType.GAME_EVENT,
					kill_packet.to_dict()
				)

		if debug_logging:
			print("[CollisionHandler] Monster %d took %d damage from player %d (killed=%s)" % [
				hit.target_id, damage_applied, hit.owner_id, killed
			])


## Attribute a lethal hit on a player and broadcast the compatible kill event.
func _broadcast_player_kill(
	killer_id: int,
	victim_id: int,
	player_manager: PlayerManager,
	network_manager: Node,
	broadcast_service: ServerBroadcastService
) -> void:
	if killer_id < GameConstants.MONSTER_ENTITY_ID_START:
		if killer_id == victim_id:
			return

		var killer := player_manager.get_player_by_entity_id(killer_id)
		if killer != null and not killer.authenticated:
			return

		# The shooter may have disconnected after firing; clients still need the
		# kill event to drive feed and death-stat updates.
		var kill_packet = GameEventPacket.create_kill_pvp(killer_id, victim_id)
		network_manager.broadcast_to_clients(
			NetworkManager.MessageType.GAME_EVENT,
			kill_packet.to_dict()
		)

		if killer == null:
			return

		killer.pvp_kills += 1
		if broadcast_service and broadcast_service.leaderboard_manager:
			broadcast_service.leaderboard_manager.record_pvp_kill(killer_id, victim_id)
			broadcast_service.broadcast_leaderboard(player_manager, network_manager)
		return

	var kill_packet = GameEventPacket.create_kill(killer_id, victim_id)
	network_manager.broadcast_to_clients(
		NetworkManager.MessageType.GAME_EVENT,
		kill_packet.to_dict()
	)
