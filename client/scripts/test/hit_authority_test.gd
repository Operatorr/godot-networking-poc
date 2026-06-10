## Regression coverage for the PvPvE hit-authority model (docs/netcode/hit-authority-model.md).
##
## Exercises the real production predicates in HitAuthority — the same functions the
## client detector (LocalHitDetector), server validator (ServerMain._handle_local_hit_report)
## and server-authoritative skip checks call — so a regression in any authority path is
## caught here. Run headless:
##   godot --headless --path client --script scripts/test/hit_authority_test.gd
extends SceneTree

var _failures := 0


func _init() -> void:
	_test_authority_split()
	_test_swept_direct_hit()
	_test_swept_through_between_frames()
	_test_swept_near_miss()
	_test_swept_degenerate_point_segment()
	_test_flight_origin_reconstruction()
	_test_plausible_on_path()
	_test_plausible_rejects_across_map()
	_test_plausible_accepts_past_position()
	_test_plausible_empty_history()
	_test_plausible_margin_boundary()
	_test_plausible_full_flight_reconstructed()

	if _failures > 0:
		push_error("[HitAuthorityTest] %d assertion(s) failed" % _failures)
		quit(1)
	else:
		print("[HitAuthorityTest] All hit-authority tests passed")
		quit(0)


# --- Authority split: monster bullets are client-auth, player bullets server-auth ---

func _test_authority_split() -> void:
	# Monster ids (>= 30000) are client-authoritative for the victim's dodge.
	_assert(HitAuthority.is_client_authoritative(GameConstants.MONSTER_ENTITY_ID_START), "monster start is client-auth")
	_assert(HitAuthority.is_client_authoritative(35000), "mid monster id is client-auth")
	# Player ids (1-999) and projectile-range owners stay server-authoritative.
	_assert(not HitAuthority.is_client_authoritative(1), "player id is server-auth")
	_assert(not HitAuthority.is_client_authoritative(500), "player id is server-auth")
	_assert(not HitAuthority.is_client_authoritative(GameConstants.MONSTER_ENTITY_ID_START - 1), "just below monster start is server-auth")
	# Unknown source (-1 from ClientEntityManager) must not be treated as a monster.
	_assert(not HitAuthority.is_client_authoritative(-1), "unknown source is not client-auth")


# --- Client swept detection (radius = PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS = 24) ---

func _test_swept_direct_hit() -> void:
	var r := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS
	# Bullet ends exactly on the player.
	_assert(HitAuthority.swept_hit(Vector2.ZERO, Vector2(0, 100), Vector2.ZERO, r), "bullet landing on player is a hit")


func _test_swept_through_between_frames() -> void:
	var r := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS
	# Fast bullet crosses the player between two frames: NEITHER endpoint is within
	# the radius (~100u away), but the swept segment passes 5u from the player. A
	# point-vs-endpoint test would miss this; the swept test must catch it.
	var hit := HitAuthority.swept_hit(Vector2.ZERO, Vector2(-100, 5), Vector2(100, 5), r)
	_assert(hit, "fast bullet swept across the player is a hit")


func _test_swept_near_miss() -> void:
	var r := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS
	# Path stays 30u away (> 24u radius): a clean dodge, not a hit.
	var hit := HitAuthority.swept_hit(Vector2.ZERO, Vector2(-100, 30), Vector2(100, 30), r)
	_assert(not hit, "bullet passing 30u away is a clean dodge")


func _test_swept_degenerate_point_segment() -> void:
	var r := GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS
	# First sighting (prev == cur): a degenerate point segment must still test distance.
	_assert(HitAuthority.swept_hit(Vector2.ZERO, Vector2(10, 0), Vector2(10, 0), r), "point segment within radius is a hit")
	_assert(not HitAuthority.swept_hit(Vector2.ZERO, Vector2(50, 0), Vector2(50, 0), r), "point segment outside radius is not a hit")


# --- Server flight reconstruction + plausibility (threshold = 8 + 16 + 64 = 88) ---

func _test_flight_origin_reconstruction() -> void:
	# A bullet now at (200,0), travelling +x, 400u downrange originated at (-200,0).
	var origin := HitAuthority.flight_origin(Vector2(200, 0), Vector2.RIGHT, 400.0)
	_assert(origin.is_equal_approx(Vector2(-200, 0)), "flight origin reconstructs spawn point")


func _test_plausible_on_path() -> void:
	var threshold := _plausibility_threshold()
	# Player sat 50u off the bullet's straight line: within the 88u anti-grief bound.
	var ok := HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), [Vector2(0, 50)], threshold)
	_assert(ok, "hit near the bullet's flight line is plausible")


func _test_plausible_rejects_across_map() -> void:
	var threshold := _plausibility_threshold()
	# Fabricated "a bullet across the map hit me": 200u off-path > 88u → rejected.
	var ok := HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), [Vector2(0, 200)], threshold)
	_assert(not ok, "hit far from the flight line is rejected")


func _test_plausible_accepts_past_position() -> void:
	var threshold := _plausibility_threshold()
	# The bullet passed the player earlier; by report time the live player has moved
	# far away. History must still vindicate the hit (test ANY recorded position).
	var positions := [Vector2(0, 40), Vector2(900, 900)]
	var ok := HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), positions, threshold)
	_assert(ok, "hit against a past position in history is plausible")


func _test_plausible_empty_history() -> void:
	var threshold := _plausibility_threshold()
	_assert(not HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), [], threshold), "no history rejects the report")


func _test_plausible_margin_boundary() -> void:
	var threshold := _plausibility_threshold()  # 88.0
	# Boundary is exclusive (< threshold): exactly 88u off is rejected, 87u accepted.
	_assert(not HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), [Vector2(0, threshold)], threshold), "exactly at threshold is rejected")
	_assert(HitAuthority.is_hit_plausible(Vector2(-200, 0), Vector2(200, 0), [Vector2(0, threshold - 1.0)], threshold), "just inside threshold is accepted")


func _test_plausible_full_flight_reconstructed() -> void:
	var threshold := _plausibility_threshold()
	# End-to-end: reconstruct the flight from a live bullet, then validate it. The
	# contact point is well behind the bullet's current position, so testing only
	# the last tick would miss it — the FULL reconstructed flight must be used.
	var current := Vector2(800, 0)
	var origin := HitAuthority.flight_origin(current, Vector2.RIGHT, 1000.0)  # (-200, 0)
	var ok := HitAuthority.is_hit_plausible(origin, current, [Vector2(0, 30)], threshold)
	_assert(ok, "contact point behind the live bullet is still plausible via full flight")


# --- helpers ---

func _plausibility_threshold() -> float:
	# Mirrors ServerMain._local_hit_is_plausible: radii + LOCAL_HIT_VALIDATION_MARGIN (64).
	return GameConstants.PROJECTILE_RADIUS + GameConstants.PLAYER_HITBOX_RADIUS + 64.0


func _assert(condition: bool, label: String) -> void:
	if condition:
		return
	_failures += 1
	push_error("[HitAuthorityTest] FAILED: %s" % label)
