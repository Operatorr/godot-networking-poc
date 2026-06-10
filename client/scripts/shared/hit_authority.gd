## HitAuthority - Pure, dependency-free predicates for the PvPvE hit-authority model.
##
## Centralizes the rules that decide WHO judges a projectile hit and WHETHER a
## client-reported hit is geometrically plausible, so identical math is used by:
##   - the client incoming-hit detector (LocalHitDetector swept test),
##   - the server report validator (ServerMain._local_hit_is_plausible),
##   - the server-authoritative skip checks (ProjectileManager, ClientEntityManager).
## Keeping the rules here (instead of copied per call site) means they can be
## unit-tested in isolation — see scripts/test/hit_authority_test.gd — and can only
## drift in one place. See docs/netcode/hit-authority-model.md.
class_name HitAuthority
extends RefCounted


## A projectile is client-authoritative for the victim's dodge iff it is
## monster-owned. Player-fired (PvP) projectiles stay server-authoritative.
static func is_client_authoritative(owner_id: int) -> bool:
	return owner_id >= GameConstants.MONSTER_ENTITY_ID_START


## Client swept hit test: does the bullet's render-frame travel (prev_pos -> cur_pos)
## pass within `hit_radius` of the rendered self position? Uses the shared
## closest-point math so client detection and server collision agree byte-for-byte.
static func swept_hit(self_pos: Vector2, prev_pos: Vector2, cur_pos: Vector2, hit_radius: float) -> bool:
	var closest := GameConstants.closest_point_on_segment(self_pos, prev_pos, cur_pos)
	return self_pos.distance_to(closest) < hit_radius


## Reconstruct a still-alive straight-flying bullet's spawn point from its current
## position, unit direction, and distance traveled. Exact while the bullet has not
## been clamped by an obstacle. Lets the server validate the bullet's FULL flight
## (not just the last tick), since a client reports a hit after the contact point
## is already downrange.
static func flight_origin(current_position: Vector2, direction: Vector2, distance_traveled: float) -> Vector2:
	return current_position - direction * distance_traveled


## Server plausibility test: does the bullet's straight-line flight
## (flight_start -> flight_end) pass within `threshold` of ANY of the player's
## recent authoritative positions? Generous anti-grief bound that absorbs the
## legitimate prediction + interpolation offset — NOT a pixel-accurate re-check.
static func is_hit_plausible(flight_start: Vector2, flight_end: Vector2, recent_positions: Array, threshold: float) -> bool:
	for pos: Vector2 in recent_positions:
		var closest := GameConstants.closest_point_on_segment(pos, flight_start, flight_end)
		if pos.distance_to(closest) < threshold:
			return true
	return false
