## ProjectileFactory - Build projectiles with pooling.
##
## Concrete EntityFactory for projectiles. Rather than instantiating fresh nodes
## per shot, it leases recycled instances from the live object pool and configures
## them from a projectile definition (speed, lifetime, collision mask, visuals).
##
## NOTE: the live pool already exists at
## scripts/systems/spawning/projectile_pool.gd (class_name ProjectilePool). This
## factory is the data-driven front door to it — it owns/holds a ProjectilePool and
## delegates allocation/recycling there, adding only definition-based configuration.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The "definition" is the projectile/spell-projectile data; the base scene
## is projectile.tscn (already pre-instanced inside the pool); the result is a
## configured, active projectile leased from the pool.
##
## Authority note: "the client requests, the server decides." Predicted projectiles
## are client-side for responsiveness; the server owns the authoritative projectile
## (id range 10000–29999) and hit resolution. This factory builds display/prediction
## instances only.
##
## Governing docs: docs/gdd/index.md, docs/systems/abilities.md, docs/server/contract.md.
##
## TODO:
##  - Hold a ProjectilePool and route create/recycle through it.
##  - Configure speed/lifetime/collision mask/visuals from the definition.
##  - Distinguish predicted-local vs replicated-remote projectiles.
class_name ProjectileFactory
extends EntityFactory


## Lease + configure a projectile from a definition (delegates to ProjectilePool).
func create_projectile(_definition: Dictionary) -> Node:
	return null


func _get_base_scene() -> PackedScene:
	return null


func _configure(_entity: Node, _definition: Dictionary) -> void:
	pass
