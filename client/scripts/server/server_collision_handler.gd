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


## Check projectile-vs-player collisions, apply damage, broadcast events
func _check_player_collisions(
	projectile_manager: ProjectileManager,
	player_manager: PlayerManager,
	network_manager: Node,
	broadcast_service: ServerBroadcastService
) -> void:
	var player_hits = projectile_manager.check_collisions_with_players(player_manager)

	for hit in player_hits:
		var target := player_manager.get_player_by_entity_id(hit.target_id)
		if target == null:
			continue

		# Determine damage based on projectile owner
		var damage: int = GameConstants.PLAYER_PROJECTILE_DAMAGE
		if hit.owner_id >= 100000:
			damage = GameConstants.MONSTER_PROJECTILE_DAMAGE

		# Record killer before damage (take_damage may set DEAD state)
		target.last_killer_id = hit.owner_id
		var killed := target.take_damage(damage)

		# Broadcast DAMAGE event to all clients
		if network_manager:
			var damage_packet = GameEventPacket.create_damage(
				hit.owner_id, hit.target_id, damage
			)
			network_manager.broadcast_to_clients(
				NetworkManager.MessageType.GAME_EVENT,
				damage_packet.to_dict()
			)

		if killed and network_manager:
			if hit.owner_id < 100000:
				# PvP kill: attribute to killer player
				var killer := player_manager.get_player_by_entity_id(hit.owner_id)
				if killer != null:
					killer.pvp_kills += 1
				var kill_packet = GameEventPacket.create_kill_pvp(
					hit.owner_id, hit.target_id
				)
				network_manager.broadcast_to_clients(
					NetworkManager.MessageType.GAME_EVENT,
					kill_packet.to_dict()
				)

				# Record kill in leaderboard and broadcast immediately
				if broadcast_service and broadcast_service.leaderboard_manager:
					broadcast_service.leaderboard_manager.record_pvp_kill(hit.owner_id, hit.target_id)
					broadcast_service.broadcast_leaderboard(player_manager, network_manager)
			else:
				# PvE kill: monster killed player
				var kill_packet = GameEventPacket.create_kill(
					hit.owner_id, hit.target_id
				)
				network_manager.broadcast_to_clients(
					NetworkManager.MessageType.GAME_EVENT,
					kill_packet.to_dict()
				)

		if debug_logging:
			print("[CollisionHandler] Player %d took %d damage from entity %d (killed=%s)" % [
				hit.target_id, damage, hit.owner_id, killed
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

		var killed := monster.take_damage(GameConstants.PLAYER_PROJECTILE_DAMAGE)

		# Broadcast DAMAGE event to all clients
		if network_manager:
			var damage_packet = GameEventPacket.create_damage(
				hit.owner_id, hit.target_id, GameConstants.PLAYER_PROJECTILE_DAMAGE
			)
			network_manager.broadcast_to_clients(
				NetworkManager.MessageType.GAME_EVENT,
				damage_packet.to_dict()
			)

		# Attribute monster kill to player
		if killed:
			var killer := player_manager.get_player_by_entity_id(hit.owner_id)
			if killer != null:
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
				hit.target_id, GameConstants.PLAYER_PROJECTILE_DAMAGE, hit.owner_id, killed
			])
