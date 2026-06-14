## Projectile - Individual projectile behavior
## Managed by ProjectilePool, uses object pooling
class_name Projectile
extends Area2D

## Emitted when projectile hits something
signal hit(body: Node2D)

## Movement speed in pixels/second
var speed: float = GameConstants.PROJECTILE_SPEED

## Maximum travel distance before deactivation
var max_distance: float = GameConstants.PROJECTILE_MAX_DISTANCE

## Damage dealt on hit
var damage: int = 25

## Normalized travel direction
var direction: Vector2 = Vector2.ZERO

## Tracks distance for range limit
var distance_traveled: float = 0.0

## Reference to managing pool for return
var owner_pool: Node = null

## Whether this projectile is active and should return to its pool
var is_active: bool = false


## Cached sprite reference
var _sprite: AnimatedSprite2D = null
var projectile_color: Color = ProceduralSprites.PROJ_MID

## -1 = monster/default visual; otherwise a PacketTypes.PlayerClass id whose
## generated projectile sheet is shown (when the art exists on disk).
var _visual_class: int = -1


func _ready() -> void:
	_sprite = get_node_or_null("AnimatedSprite2D")
	_apply_visual()

	# Connect body_entered signal for collision detection
	body_entered.connect(_on_body_entered)


## Resolve the current visual: class sheet > monster sheet > procedural dot.
func _apply_visual() -> void:
	if _sprite == null:
		return
	var frames: SpriteFrames = null
	if _visual_class >= 0:
		frames = SheetLibrary.projectile_frames(_visual_class)
	else:
		frames = SheetLibrary.monster_projectile_frames("slime")
	if frames != null and frames.has_animation("fly"):
		_sprite.sprite_frames = frames
		_sprite.modulate = Color.WHITE
		_sprite.rotation = (
			SheetLibrary.projectile_rotation_offset(_visual_class) if _visual_class >= 0 else 0.0
		)
		_sprite.play("fly")
		return
	_sprite.rotation = 0.0
	# Procedural fallback: single-frame radial gradient, color-tintable.
	var fallback := SpriteFrames.new()
	fallback.remove_animation("default")
	fallback.add_animation("fly")
	fallback.add_frame("fly", ProceduralSprites.create_projectile_texture(16, projectile_color))
	_sprite.sprite_frames = fallback
	_sprite.modulate = Color.WHITE
	_sprite.play("fly")


func _physics_process(delta: float) -> void:
	# Move projectile
	var movement := direction * speed * delta
	global_position += movement
	distance_traveled += movement.length()

	# Check if max distance reached
	if distance_traveled >= max_distance:
		deactivate()


## Activate projectile (called by pool)
## @param pos: Starting position
## @param dir: Normalized direction
## @param max_dist: Maximum travel distance
## @param pool: Owning pool reference
func activate(pos: Vector2, dir: Vector2, max_dist: float, pool: Node) -> void:
	direction = dir.normalized()
	max_distance = max_dist
	distance_traveled = 0.0
	owner_pool = pool
	is_active = true

	# Re-enable processing/collision FIRST. A projectile recycled from far away (it
	# travelled to max range before reuse, common in the large Sandbox arena) was
	# process-disabled; resetting interpolation while still disabled left a one-frame
	# streak from the old spot. Enabling, then positioning, then resetting last makes
	# the reset apply to a live node — no ghost.
	process_mode = Node.PROCESS_MODE_INHERIT
	visible = true
	monitoring = true
	monitorable = true

	rotation = direction.angle()
	global_position = pos
	# Teleport to the new spawn without interpolating from the recycled position.
	reset_physics_interpolation()


## Show the class-specific projectile art for the firing player's class.
func set_projectile_class(class_id: int) -> void:
	if _visual_class == class_id:
		return
	_visual_class = class_id
	_apply_visual()


## Tint projectile visuals to match a player. Only affects the procedural
## fallback — generated class/monster art is already class-styled.
func set_projectile_color(color: Color) -> void:
	color.a = 1.0
	projectile_color = color
	_apply_visual()


## Monster/default visual (the toxic slime glob when art is present).
func reset_projectile_color() -> void:
	projectile_color = ProceduralSprites.PROJ_MID
	_visual_class = -1
	_apply_visual()


## Deactivate and return to pool
func deactivate() -> void:
	if not is_active:
		return

	# is_active flips immediately so a second body_entered this frame is ignored,
	# and visible hides it now so the pool can find it for reuse. The physics-server
	# toggles (monitoring/monitorable/process_mode) are deferred: deactivate() is
	# normally called from inside a body_entered callback, where Godot forbids
	# changing them directly.
	is_active = false
	var pool := owner_pool
	owner_pool = null

	visible = false
	direction = Vector2.ZERO
	distance_traveled = 0.0

	call_deferred("_apply_deactivation")

	# Return to pool
	if pool and pool.has_method("return_projectile"):
		pool.return_projectile(self)


## Disable collision/processing at idle time. Guarded so that if the projectile
## was recycled (re-activated) before this deferred call runs, we don't clobber
## the freshly-enabled monitoring/process_mode of the now-live projectile.
func _apply_deactivation() -> void:
	if is_active:
		return
	process_mode = Node.PROCESS_MODE_DISABLED
	monitoring = false
	monitorable = false


func _on_body_entered(body: Node2D) -> void:
	if not is_active:
		return

	hit.emit(body)
	deactivate()
