## ChargeTrail — the shader-driven GPU particle trail streamed behind the Warrior
## while charging. Cosmetic only.
##
## A GPUParticles2D parented to the player with `local_coords = false`, so the
## embers it emits are left behind in WORLD space as the warrior dashes (the fast
## charge motion does most of the trailing). The process pass is the custom
## particle shader `assets/shaders/effects/charge_trail.gdshader`; rendering is
## additive (blend_add) for glow. Each physics frame we push the live charge
## direction into the shader's `flow_dir` (derived from our own world-space
## motion, so this node stays decoupled from the prediction internals) to sweep
## the embers backward into a comet tail.
##
## Lifecycle: PredictionController.create()s one on the predicted charge rising
## edge (mirroring the charge-loop SFX) and calls finish() on the falling edge —
## finish() stops emission and frees the node once the last embers have faded.
class_name ChargeTrail
extends GPUParticles2D

const TRAIL_SHADER := preload("res://assets/shaders/effects/charge_trail.gdshader")

const PARTICLE_LIFETIME := 0.45
const PARTICLE_AMOUNT := 56

var _mat: ShaderMaterial
var _prev_pos: Vector2 = Vector2.ZERO
var _have_prev := false


## Build a configured, already-emitting trail. Parent it to the player.
static func create() -> ChargeTrail:
	var t := ChargeTrail.new()
	return t


func _ready() -> void:
	# World-space embers (trail behind a moving emitter), drawn additively.
	local_coords = false
	# Stay at entity z (0), NOT negative: a negative z_index would drop the trail
	# UNDER the arena's own _draw() floor (arena_base.gd warns about exactly this)
	# and it would vanish. Instead we sit at z 0 (above the floor) and draw BEHIND
	# the player's sprite via tree order — move to the front of the player's
	# children below. (EntityContainer is not Y-sorted, so order wins.)
	z_index = 0
	z_as_relative = true
	texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR  # soft glow dot despite the pixel-art default
	amount = PARTICLE_AMOUNT
	lifetime = PARTICLE_LIFETIME
	one_shot = false
	explosiveness = 0.0
	randomness = 0.4
	emitting = true

	_mat = ShaderMaterial.new()
	_mat.shader = TRAIL_SHADER
	process_material = _mat

	texture = _make_dot_texture()

	var glow := CanvasItemMaterial.new()
	glow.blend_mode = CanvasItemMaterial.BLEND_MODE_ADD
	material = glow

	# Draw behind the player's sprite (siblings share z 0; first child draws first).
	var parent := get_parent()
	if parent != null:
		parent.move_child(self, 0)

	set_physics_process(true)


## Stop emitting and free once the trailing embers have faded out.
func finish() -> void:
	emitting = false
	set_physics_process(false)
	var tree := get_tree()
	if tree == null:
		queue_free()
		return
	tree.create_timer(PARTICLE_LIFETIME + 0.1).timeout.connect(func() -> void:
		if is_instance_valid(self):
			queue_free()
	)


## Feed the live charge direction into the shader so embers sweep backward.
## Derived from our own world motion to avoid coupling to the prediction sim.
func _physics_process(_delta: float) -> void:
	var pos := global_position
	if _have_prev:
		var step := pos - _prev_pos
		if step.length() > 0.5 and _mat != null:
			_mat.set_shader_parameter("flow_dir", step.normalized())
	_prev_pos = pos
	_have_prev = true


## Small soft radial dot used as the ember sprite (white core -> transparent rim).
## Generated in code so no PNG asset is needed; tinted/faded by the shader COLOR.
func _make_dot_texture() -> GradientTexture2D:
	var grad := Gradient.new()
	grad.set_color(0, Color(1.0, 1.0, 1.0, 1.0))
	grad.add_point(0.55, Color(1.0, 1.0, 1.0, 0.55))
	grad.set_color(grad.get_point_count() - 1, Color(1.0, 1.0, 1.0, 0.0))
	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.width = 24
	tex.height = 24
	tex.fill = GradientTexture2D.FILL_RADIAL
	tex.fill_from = Vector2(0.5, 0.5)
	tex.fill_to = Vector2(1.0, 0.5)
	return tex
