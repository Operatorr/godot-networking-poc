## EnemyFactory - Build enemies from a MonsterDefinition.
##
## Concrete EntityFactory for monsters. Takes a monster definition (from the
## data/monsters catalogue, via MonsterDatabase) plus the base enemy scene, then
## instantiates and configures stats, appearance, and AI hooks.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The "definition" here is a MonsterDefinition (built from a monster JSON
## file); the base scene is the shared enemy prefab; the result is a configured
## monster Node ready for display/prediction.
##
## Authority note: "the client requests, the server decides." Spawned monsters are
## server-authoritative; this factory builds the *client-side representation* the
## interpolation/render layer drives. It does not decide spawns, HP, or AI truth.
##
## Governing docs: docs/gdd/MONSTERS.md, docs/systems/monster-architecture.md,
## docs/gdd/loot.md (drop tables referenced by enemies).
##
## TODO:
##  - Look up the MonsterDefinition by id (see MonsterDatabase) and build from it.
##  - Configure HP/speed/appearance/collision from the definition.
##  - Attach the client-side AI/animation hooks (display-only).
##  - Resolve the base enemy scene path.
class_name EnemyFactory
extends EntityFactory


## Build a configured enemy from a monster definition id.
func create_enemy(_monster_id: String) -> Node:
	return null


func _get_base_scene() -> PackedScene:
	return null


func _configure(_entity: Node, _definition: Dictionary) -> void:
	pass
