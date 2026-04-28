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
var _sprite: Sprite2D = null
var projectile_color: Color = ProceduralSprites.PROJ_MID

func _ready() -> void:
	# Apply procedural projectile texture
	_sprite = get_node_or_null("Sprite2D")
	if _sprite:
		_sprite.texture = ProceduralSprites.create_projectile_texture(16, projectile_color)
		_sprite.modulate = Color.WHITE  # Override placeholder yellow tint

	# Connect body_entered signal for collision detection
	body_entered.connect(_on_body_entered)


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
	global_position = pos
	direction = dir.normalized()
	max_distance = max_dist
	distance_traveled = 0.0
	owner_pool = pool
	is_active = true

	# Set rotation to match direction
	rotation = direction.angle()

	# Enable processing and visibility
	process_mode = Node.PROCESS_MODE_INHERIT
	visible = true

	# Enable collision detection
	monitoring = true
	monitorable = true


## Tint projectile visuals to match a player. Monster projectiles use reset color.
func set_projectile_color(color: Color) -> void:
	color.a = 1.0
	projectile_color = color
	if _sprite == null:
		_sprite = get_node_or_null("Sprite2D")
	if _sprite:
		_sprite.texture = ProceduralSprites.create_projectile_texture(16, projectile_color)
		_sprite.modulate = Color.WHITE


func reset_projectile_color() -> void:
	set_projectile_color(ProceduralSprites.PROJ_MID)


## Deactivate and return to pool
func deactivate() -> void:
	if not is_active:
		return

	is_active = false
	var pool := owner_pool
	owner_pool = null

	# Disable processing and visibility
	process_mode = Node.PROCESS_MODE_DISABLED
	visible = false

	# Disable collision detection
	monitoring = false
	monitorable = false

	# Reset state
	direction = Vector2.ZERO
	distance_traveled = 0.0

	# Return to pool
	if pool and pool.has_method("return_projectile"):
		pool.return_projectile(self)


func _on_body_entered(body: Node2D) -> void:
	if not is_active:
		return

	hit.emit(body)
	deactivate()
