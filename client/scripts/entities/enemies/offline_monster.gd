## OfflineMonster - a self-contained, client-side AI enemy for the offline modes
## (Offline Sandbox). It is NOT the networked Monster: there is no server here, so
## this node runs its own compact chase / kite / shoot state machine locally.
##
## Behaviour and tuning are data-driven from the same MonsterDefinition JSON the
## server AI reads (move_speed, ranges, cooldown, projectile speed/damage), so a
## "toxic_slime" here fights like the real one without re-tuning. It mirrors the
## INTENT of MonsterAi (idle/chase/attack/flee) in a much simpler form; it does not
## try to reproduce the server's steering/threat-scoring math.
##
## It does NOT respawn when killed - it frees itself.
class_name OfflineMonster
extends CharacterBody2D

signal took_damage(amount: int)
signal killed(monster: OfflineMonster)

enum State { IDLE, CHASE, ATTACK, FLEE }

const DEFAULT_DEFINITION_ID := "toxic_slime"

@export var definition_id: String = DEFAULT_DEFINITION_ID

## The node this monster fights (the local player). Set by the spawner.
var target: Node2D = null

@onready var animated_sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var projectile_pool: ProjectilePool = $ProjectilePool

var definition: MonsterDefinition = null
var max_hp: int = GameConstants.MONSTER_HEALTH
var current_hp: int = GameConstants.MONSTER_HEALTH

var _is_dead: bool = false
var _state: State = State.IDLE
var _shoot_timer: float = 0.0
var _strafe_sign: float = 1.0
var _cached_audio_manager: Node = null


func _ready() -> void:
	motion_mode = CharacterBody2D.MOTION_MODE_FLOATING
	add_to_group("enemies")
	add_to_group("minimap_monster")  # red dot on the minimap

	definition = MonsterDatabase.get_shared().get_definition(definition_id)
	max_hp = definition.max_health
	current_hp = max_hp
	_strafe_sign = 1.0 if randf() < 0.5 else -1.0

	_apply_definition()

	# Monster bullets hit the player + walls, never other monsters.
	if projectile_pool:
		projectile_pool.projectile_collision_mask = ProjectilePool.MONSTER_PROJECTILE_COLLISION_MASK
		for projectile: Projectile in projectile_pool.pool:
			var hit_callable := Callable(self, "_on_bullet_hit").bind(projectile)
			if not projectile.hit.is_connected(hit_callable):
				projectile.hit.connect(hit_callable)

	queue_redraw()


func _physics_process(delta: float) -> void:
	if _is_dead:
		velocity = Vector2.ZERO
		return

	if _shoot_timer > 0.0:
		_shoot_timer -= delta

	if target == null or not is_instance_valid(target):
		_state = State.IDLE
		velocity = Vector2.ZERO
		move_and_slide()
		_play_movement_animation()
		return

	var to_target := target.global_position - global_position
	var distance := to_target.length()
	var dir := to_target.normalized() if distance > 0.001 else Vector2.RIGHT
	var perp := Vector2(-dir.y, dir.x) * _strafe_sign

	var desired := Vector2.ZERO
	var shooting := false

	if distance < definition.flee_distance:
		# Too close — back away while strafing (kite).
		_state = State.FLEE
		desired = (-dir + perp * 0.5).normalized()
	elif distance <= definition.attack_range:
		# In weapon range — orbit at the preferred distance and fire.
		_state = State.ATTACK
		var radial := Vector2.ZERO
		if distance < definition.preferred_distance * 0.85:
			radial = -dir
		elif distance > definition.preferred_distance * 1.15:
			radial = dir
		desired = (perp + radial * 0.6).normalized()
		shooting = true
	elif distance <= definition.detection_range:
		# Seen but out of range — close the gap.
		_state = State.CHASE
		desired = dir
	else:
		_state = State.IDLE
		desired = Vector2.ZERO

	velocity = desired * definition.move_speed
	move_and_slide()

	if shooting and _shoot_timer <= 0.0:
		_shoot_at(target)
		_shoot_timer = definition.shoot_cooldown
		_play_animation("attack")
	else:
		_play_movement_animation()


func _shoot_at(victim: Node2D) -> void:
	if projectile_pool == null:
		return

	var aim := _predicted_aim_direction(victim)
	var spawn_offset := definition.hitbox_radius + GameConstants.PROJECTILE_RADIUS + 2.0
	var spawn_pos := global_position + aim * spawn_offset

	var projectile := projectile_pool.spawn(spawn_pos, aim, GameConstants.PROJECTILE_MAX_DISTANCE)
	if projectile == null:
		return

	projectile.speed = definition.projectile_speed
	projectile.damage = definition.projectile_damage
	projectile.set_projectile_color(definition.glow_color)

	var audio := _get_audio_manager()
	if audio and audio.has_method("play_monster_shoot"):
		audio.play_monster_shoot()


## Lead the target using its current velocity so shots aren't always behind.
func _predicted_aim_direction(victim: Node2D) -> Vector2:
	var to_target: Vector2 = victim.global_position - global_position
	var victim_velocity := Vector2.ZERO
	if victim is CharacterBody2D:
		victim_velocity = (victim as CharacterBody2D).velocity
	var lead_time: float = to_target.length() / maxf(1.0, definition.projectile_speed)
	var predicted: Vector2 = victim.global_position + victim_velocity * lead_time
	var aim := predicted - global_position
	if aim.is_zero_approx():
		aim = to_target
	if aim.is_zero_approx():
		aim = Vector2.RIGHT
	return aim.normalized()


func _on_bullet_hit(body: Node2D, _projectile: Projectile) -> void:
	# Bullets also collide with walls (environment) — only damage the player.
	if body is Player:
		(body as Player).take_damage(definition.projectile_damage)


func take_damage(amount: int) -> bool:
	if _is_dead or amount <= 0:
		return false

	current_hp = clampi(current_hp - amount, 0, max_hp)
	queue_redraw()
	took_damage.emit(amount)
	_play_animation("hit")

	if current_hp == 0:
		_die()
		return true
	return false


func is_dead() -> bool:
	return _is_dead


func _die() -> void:
	_is_dead = true
	velocity = Vector2.ZERO
	if collision_shape:
		collision_shape.set_deferred("disabled", true)
	_play_animation("death")
	killed.emit(self)
	# Let the death animation play, then remove. No respawn.
	var timer := get_tree().create_timer(0.5)
	timer.timeout.connect(queue_free, CONNECT_ONE_SHOT)


func _apply_definition() -> void:
	if collision_shape and collision_shape.shape is CircleShape2D:
		(collision_shape.shape as CircleShape2D).radius = definition.hitbox_radius

	if animated_sprite:
		animated_sprite.sprite_frames = ProceduralSprites.create_monster_frames_from_colors(
			definition.core_color,
			definition.glow_color,
			definition.shell_color
		)
		animated_sprite.modulate = Color.WHITE
		animated_sprite.play("idle")


func _play_movement_animation() -> void:
	if velocity.length() > 5.0:
		_play_animation("walk")
	else:
		_play_animation("idle")


func _play_animation(animation_name: StringName) -> void:
	if animated_sprite == null or animated_sprite.sprite_frames == null:
		return
	if not animated_sprite.sprite_frames.has_animation(animation_name):
		return
	if animated_sprite.animation != animation_name:
		animated_sprite.play(animation_name)


func _get_audio_manager() -> Node:
	if _cached_audio_manager == null or not is_instance_valid(_cached_audio_manager):
		_cached_audio_manager = get_tree().root.get_node_or_null("AudioManager")
	return _cached_audio_manager


func _draw() -> void:
	if _is_dead:
		return

	var bar_width := 42.0
	var bar_height := 5.0
	var bar_y := -30.0
	var hp_ratio := clampf(float(current_hp) / float(maxi(max_hp, 1)), 0.0, 1.0)
	var bg_rect := Rect2(Vector2(-bar_width * 0.5, bar_y), Vector2(bar_width, bar_height))
	var hp_rect := Rect2(bg_rect.position, Vector2(bar_width * hp_ratio, bar_height))

	draw_rect(bg_rect, Color(0.05, 0.09, 0.03, 0.88), true)
	draw_rect(hp_rect, Color(0.55, 0.92, 0.25, 0.95), true)
	draw_rect(bg_rect, Color(0.12, 0.2, 0.07, 0.9), false, 1.0)
