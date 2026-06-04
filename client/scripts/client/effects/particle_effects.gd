## ParticleEffects - Factory for creating combat particle effects
## Uses CPUParticles2D for compatibility (no shader compilation required)
class_name ParticleEffects
extends RefCounted


## Create muzzle flash particles at position
static func create_muzzle_flash(pos: Vector2, direction: Vector2) -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = true
	particles.amount = 6
	particles.lifetime = 0.1
	particles.explosiveness = 1.0
	particles.global_position = pos

	# Direction-based emission
	particles.direction = Vector2(direction.x, direction.y)
	particles.spread = 25.0
	particles.initial_velocity_min = 100.0
	particles.initial_velocity_max = 200.0
	particles.gravity = Vector2.ZERO

	# Scale
	particles.scale_amount_min = 2.0
	particles.scale_amount_max = 4.0
	particles.scale_amount_curve = _create_fade_curve()

	# Color: white → electric blue
	var gradient := Gradient.new()
	gradient.set_color(0, Color(1.0, 1.0, 1.0))
	gradient.set_color(1, Color(0.27, 0.53, 1.0, 0.0))
	particles.color_ramp = gradient

	# Auto-free
	_auto_free(particles, 0.3)
	return particles


## Create hit spark particles at impact point
static func create_hit_sparks(pos: Vector2, color: Color = Color(1.0, 0.5, 0.1)) -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = true
	particles.amount = 12
	particles.lifetime = 0.3
	particles.explosiveness = 1.0
	particles.global_position = pos

	# Radial burst
	particles.direction = Vector2.ZERO
	particles.spread = 180.0
	particles.initial_velocity_min = 80.0
	particles.initial_velocity_max = 180.0
	particles.gravity = Vector2(0, 200)  # Slight gravity

	# Scale
	particles.scale_amount_min = 1.5
	particles.scale_amount_max = 3.0

	# Color: bright → fade
	var gradient := Gradient.new()
	gradient.set_color(0, color)
	var fade_color := color
	fade_color.a = 0.0
	gradient.set_color(1, fade_color)
	particles.color_ramp = gradient

	_auto_free(particles, 0.6)
	return particles


## Create death explosion particles
static func create_death_explosion(pos: Vector2, entity_color: Color = Color(0.8, 0.13, 0.13)) -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = true
	particles.amount = 25
	particles.lifetime = 0.6
	particles.explosiveness = 1.0
	particles.global_position = pos

	# Radial burst - violent
	particles.direction = Vector2.ZERO
	particles.spread = 180.0
	particles.initial_velocity_min = 60.0
	particles.initial_velocity_max = 250.0
	particles.gravity = Vector2(0, 100)

	# Scale
	particles.scale_amount_min = 2.0
	particles.scale_amount_max = 5.0

	# Color: entity color + gore red → dark fade
	var gradient := Gradient.new()
	gradient.set_color(0, entity_color)
	gradient.add_point(0.4, Color(0.6, 0.05, 0.05, 0.8))
	gradient.set_color(gradient.get_point_count() - 1, Color(0.1, 0.02, 0.02, 0.0))
	particles.color_ramp = gradient

	_auto_free(particles, 1.0)
	return particles


## Create gore splatter (lingers on ground)
static func create_gore_splatter(pos: Vector2) -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = true
	particles.amount = 8
	particles.lifetime = 0.8
	particles.explosiveness = 0.8
	particles.global_position = pos

	particles.direction = Vector2.ZERO
	particles.spread = 180.0
	particles.initial_velocity_min = 20.0
	particles.initial_velocity_max = 60.0
	particles.damping_min = 80.0
	particles.damping_max = 120.0
	particles.gravity = Vector2.ZERO

	particles.scale_amount_min = 1.0
	particles.scale_amount_max = 3.0

	# Dark red blood
	var gradient := Gradient.new()
	gradient.set_color(0, Color(0.5, 0.02, 0.02, 0.7))
	gradient.set_color(1, Color(0.2, 0.01, 0.01, 0.0))
	particles.color_ramp = gradient

	_auto_free(particles, 1.5)
	return particles


## Create spawn effect (dimensional tear ring)
static func create_spawn_effect(pos: Vector2, color: Color = Color(0.6, 0.27, 0.8)) -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = true
	particles.amount = 16
	particles.lifetime = 0.5
	particles.explosiveness = 0.9
	particles.global_position = pos

	# Expanding ring
	particles.emission_shape = CPUParticles2D.EMISSION_SHAPE_RING
	particles.emission_ring_radius = 5.0
	particles.emission_ring_inner_radius = 3.0
	particles.direction = Vector2.ZERO
	particles.spread = 180.0
	particles.initial_velocity_min = 40.0
	particles.initial_velocity_max = 100.0
	particles.gravity = Vector2.ZERO

	particles.scale_amount_min = 2.0
	particles.scale_amount_max = 4.0

	# Color: bright → purple → fade
	var gradient := Gradient.new()
	gradient.set_color(0, Color.WHITE)
	gradient.add_point(0.3, color)
	gradient.set_color(gradient.get_point_count() - 1, Color(color.r, color.g, color.b, 0.0))
	particles.color_ramp = gradient

	_auto_free(particles, 0.8)
	return particles


## Create projectile trail (continuous - caller must manage lifecycle)
static func create_projectile_trail() -> CPUParticles2D:
	var particles := CPUParticles2D.new()
	particles.emitting = true
	particles.one_shot = false
	particles.amount = 4
	particles.lifetime = 0.2
	particles.explosiveness = 0.0

	particles.direction = Vector2(-1, 0)  # Trail behind
	particles.spread = 15.0
	particles.initial_velocity_min = 10.0
	particles.initial_velocity_max = 30.0
	particles.gravity = Vector2.ZERO

	particles.scale_amount_min = 1.0
	particles.scale_amount_max = 2.0

	# Color: blue → transparent
	var gradient := Gradient.new()
	gradient.set_color(0, Color(0.27, 0.53, 1.0, 0.5))
	gradient.set_color(1, Color(0.27, 0.53, 1.0, 0.0))
	particles.color_ramp = gradient

	return particles


## Create a short-lived shot tracer line from -> to. One Line2D node, auto-freed
## quickly so held fire stays cheap. Points are in the world space of the entity
## container (the line draws in local space; we leave global_position at origin).
static func create_tracer(from: Vector2, to: Vector2, color: Color = Color(0.27, 0.53, 1.0)) -> Line2D:
	var line := Line2D.new()
	line.points = PackedVector2Array([from, to])
	line.width = 2.0
	line.default_color = color
	line.begin_cap_mode = Line2D.LINE_CAP_ROUND
	line.end_cap_mode = Line2D.LINE_CAP_ROUND
	_auto_free(line, 0.08)
	return line


## Create fade curve for scale
static func _create_fade_curve() -> Curve:
	var curve := Curve.new()
	curve.add_point(Vector2(0, 1))
	curve.add_point(Vector2(1, 0))
	return curve


## Auto-free node after delay
static func _auto_free(node: Node, delay: float) -> void:
	# Can't use get_tree in static, so we use a callback approach
	node.ready.connect(func():
		node.get_tree().create_timer(delay).timeout.connect(node.queue_free)
	)
