## LocalHitDetector - Client-side detection of incoming monster projectiles.
##
## Server-authoritative hit detection compares the player's TRUE (authoritative)
## position against the bullet's TRUE position. But the client renders itself
## PREDICTED-ahead and renders bullets INTERPOLATED-behind, so server-side hits
## felt direction-dependent: phantom hits while fleeing (true-you is behind the
## rendered you, closer to the bullet) and pass-throughs while chasing (true-you
## hasn't caught the bullet the screen shows you touching).
##
## To make "what you see is what you get" true for dodging, the victim's own
## client tests incoming MONSTER bullets against the position it actually renders
## the player at — exactly what is on screen, which trails predicted_position while
## a correction smooths — and reports a hit. The server validates plausibility
## before applying damage (see ServerMain._handle_local_hit_report).
##
## Scope: monster-owned projectiles vs. the LOCAL player only. Player-vs-player and
## player-vs-monster hits stay server-authoritative. See docs/systems/combat-hits.md.
class_name LocalHitDetector
extends RefCounted

## Feature toggle for A/B testing against the legacy server-side behaviour.
var enabled: bool = true

var _prediction: PredictionController = null
var _entity_manager: ClientEntityManager = null
var _local_player: Player = null

## projectile_id -> last rendered position, for swept-segment tests between frames.
var _last_positions: Dictionary = {}
## projectile_id -> true; bullets already reported this life (report each at most once).
var _reported_ids: Dictionary = {}


func setup(prediction: PredictionController, entity_manager: ClientEntityManager, local_player: Player) -> void:
	_prediction = prediction
	_entity_manager = entity_manager
	_local_player = local_player


## Reset per-life tracking (call on respawn) so a fresh life can be hit again.
func reset() -> void:
	_last_positions.clear()
	_reported_ids.clear()


## Run one detection pass against the currently rendered projectiles. Call every
## render frame, after entity visuals have been updated for this frame.
func update() -> void:
	if not enabled:
		return
	if _prediction == null or not _prediction.is_active():
		return
	if _local_player == null or not is_instance_valid(_local_player):
		return
	if _local_player.hp_component != null and _local_player.hp_component.is_dead:
		return
	if _entity_manager == null:
		return

	# Test against where the player is actually rendered, not predicted_position:
	# during a smooth correction the rendered position trails the prediction, so a
	# hit must use what the player saw on screen to stay "what you see is what you get".
	var self_pos: Vector2 = _prediction.get_rendered_position()
	var hit_radius := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS
	var snapshots: Array = _entity_manager.get_monster_projectile_snapshots()

	var seen_ids := {}
	for snap: Dictionary in snapshots:
		var projectile_id: int = snap["id"]
		var cur_pos: Vector2 = snap["position"]
		seen_ids[projectile_id] = true

		if _reported_ids.has(projectile_id):
			continue

		# First sighting has no prior frame; use a degenerate (point) segment.
		var prev_pos: Vector2 = _last_positions.get(projectile_id, cur_pos)
		_last_positions[projectile_id] = cur_pos

		# Swept test of the bullet's render-frame travel against the rendered self.
		var closest := GameConstants.closest_point_on_segment(self_pos, prev_pos, cur_pos)
		if self_pos.distance_to(closest) < hit_radius:
			_report_hit(projectile_id)

	_prune_stale(seen_ids)


func _report_hit(projectile_id: int) -> void:
	_reported_ids[projectile_id] = true
	# Cosmetic: hide the bullet immediately so the impact feels instant. The
	# authoritative despawn + HP change follow the server's validated response.
	_entity_manager.hide_projectile_locally(projectile_id)
	NetworkManager.send_to_server(
		NetworkManager.MessageType.LOCAL_HIT_REPORT,
		{ "projectile_id": projectile_id }
	)


## Drop tracking for projectiles that are no longer rendered (despawned/hidden).
func _prune_stale(seen_ids: Dictionary) -> void:
	for projectile_id: int in _last_positions.keys():
		if not seen_ids.has(projectile_id):
			_last_positions.erase(projectile_id)
	for projectile_id: int in _reported_ids.keys():
		if not seen_ids.has(projectile_id):
			_reported_ids.erase(projectile_id)
