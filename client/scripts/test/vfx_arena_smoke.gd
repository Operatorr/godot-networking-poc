## VfxArenaSmoke — verifies the ability VFX draw order against the REAL arena
## floor (the plain vfx_smoke uses a black background, which hides z-order bugs).
## Sweeps a Warrior across the arena with a ChargeTrail attached and fires the
## charge blast at its feet, so we can confirm: (1) the trail is visible above the
## floor and behind the warrior, (2) the blast renders below the warrior.
##
##   godot --path . res://scenes/test/vfx_arena_smoke.tscn \
##     --write-movie /tmp/shots/arena.png --fixed-fps 12 --quit-after 40
extends Node2D

const ArenaScene := preload("res://scenes/levels/arena/arena_base.tscn")
const RemotePlayerScene := preload("res://scenes/entities/player/remote_player.tscn")

var _container: Node = null
var _warrior: Node2D = null
var _trail: ChargeTrail = null
var _t := 0.0
var _blast_t := 0.0


func _ready() -> void:
	var arena := ArenaScene.instantiate()
	add_child(arena)
	arena._is_leaving_arena = true  # latch teardown off (no server in this smoke)
	await get_tree().process_frame
	_container = arena.get_entity_container()

	var cam := Camera2D.new()
	cam.position = Vector2(0, 0)
	cam.zoom = Vector2(1.3, 1.3)
	add_child(cam)
	cam.make_current()

	_warrior = RemotePlayerScene.instantiate()
	_container.add_child(_warrior)
	_warrior.global_position = Vector2(-360, 0)
	_warrior.set_character_name("warrior")
	_warrior.set_player_class(PacketTypes.PlayerClass.WARRIOR)
	_warrior.update_from_network(
		PacketTypes.AnimationState.RUN,
		PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE
	)

	_trail = ChargeTrail.create()
	_warrior.add_child(_trail)
	await get_tree().process_frame
	print("[vfx_arena] trail z=", _trail.z_index, " child_index=",
		_warrior.get_children().find(_trail), " emitting=", _trail.emitting)

	_validate()


## Assert the VFX preconditions so this doubles as a CI smoke test (not just a capture harness):
## on any failure it push_errors and exits non-zero, instead of silently exiting 0 under --quit-after.
## On success it prints PASS and lets the capture continue. Kept assertion-only (no eyeballing needed).
func _validate() -> void:
	var failures: Array[String] = []
	if not is_instance_valid(_warrior):
		failures.append("warrior node missing")
	if not is_instance_valid(_trail):
		failures.append("charge trail missing")
	if _container == null:
		failures.append("entity container missing")
	# The sprite-sheet path must resolve — else BlastEffect silently falls back to the procedural
	# ring forever and a broken sheet import would never surface.
	var frames := SheetLibrary.effect_frames("charge_blast")
	if frames == null:
		failures.append("SheetLibrary.effect_frames('charge_blast') returned null")
	elif not frames.has_animation("blast"):
		failures.append("charge_blast sheet has no 'blast' animation")
	# A blast node must instantiate and self-attach without error.
	var blast := BlastEffect.create(
		"charge_blast", Vector2.ZERO, 120.0, Color.WHITE, Color.WHITE)
	if not is_instance_valid(blast):
		failures.append("BlastEffect.create returned an invalid node")
	else:
		blast.queue_free()
	if failures.is_empty():
		print("[vfx_arena] PASS — all VFX preconditions met")
		return
	for f in failures:
		push_error("[vfx_arena] FAIL: " + f)
	get_tree().quit(1)


func _process(delta: float) -> void:
	_t += delta
	_blast_t += delta
	if is_instance_valid(_warrior):
		_warrior.global_position = Vector2(-360.0 + _t * 230.0, 0.0)
	if _blast_t >= 1.3 and _container != null and is_instance_valid(_warrior):
		_blast_t = 0.0
		_container.add_child(BlastEffect.create(
			"charge_blast", _warrior.global_position, 120.0,
			Color(1.0, 0.6, 0.2), Color(1.0, 0.8, 0.4)
		))
