## VfxSmoke — visual smoke for the ability VFX added 2026-06-17: the charge_blast
## and mageblast BlastEffect sprite detonations and the shader-driven ChargeTrail.
##
## Run with the movie writer to capture frames (real renderer, so the particle
## shader actually compiles + runs):
##   godot --path . res://scenes/test/vfx_smoke.tscn \
##     --write-movie /tmp/shots/vfx.png --fixed-fps 12 --quit-after 6
##
## Lives under scenes/test/ so SceneManager doesn't reroute it to login.
extends Node2D

const LOOP_PERIOD := 1.6  # respawn the one-shot blasts + reset the trail each cycle

var _respawn_t := 0.0
var _trail_t := 0.0
var _trail: ChargeTrail = null


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.07, 0.07, 0.09))
	var cam := Camera2D.new()
	cam.position = Vector2(320, 240)
	cam.zoom = Vector2(2.4, 2.4)  # fill the frame with the effects
	add_child(cam)
	cam.make_current()
	_spawn_blasts()
	_restart_trail()


func _spawn_blasts() -> void:
	add_child(BlastEffect.create(
		"charge_blast", Vector2(170, 170), 120.0,
		Color(1.0, 0.6, 0.2), Color(1.0, 0.8, 0.4)
	))
	add_child(BlastEffect.create(
		"mageblast", Vector2(470, 170), 144.0,
		Color(0.5, 0.7, 1.0), Color(0.85, 0.95, 1.0)
	))


func _restart_trail() -> void:
	if _trail != null and is_instance_valid(_trail):
		_trail.finish()
	_trail = ChargeTrail.create()
	add_child(_trail)
	_trail.global_position = Vector2(80, 360)
	_trail_t = 0.0


func _process(delta: float) -> void:
	_respawn_t += delta
	_trail_t += delta
	# Sweep the trail left -> right so embers are left behind in world space
	# (stands in for the warrior's charge motion).
	if _trail != null and is_instance_valid(_trail):
		_trail.global_position = Vector2(80.0 + _trail_t * 260.0, 360.0 + sin(_trail_t * 4.0) * 26.0)
	if _respawn_t >= LOOP_PERIOD:
		_respawn_t = 0.0
		_spawn_blasts()
		_restart_trail()
