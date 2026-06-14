## EntityFactory - Abstract base factory: JSON definition -> configured entity.
##
## The shared contract for all gameplay factories. Each concrete factory takes a
## parsed *definition* (the data side) and a *base scene* (the prefab), then
## instantiates and configures one entity from them. Subclasses specialise the
## kind of entity (enemy, item, spell, projectile) but share this pipeline so the
## data-driven flow is uniform across the codebase.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. This class IS the "Factory" node in that chain. The "definition" is a
## Dictionary parsed from JSON (or a typed *Definition object built from one); the
## "base scene" is a PackedScene; the result is a configured Node.
##
## Authority note: "the client requests, the server decides." Factories build
## client-side instances for prediction/display from server-authoritative data;
## they never invent gameplay outcomes.
##
## Governing docs: docs/gdd/index.md, docs/gdd/folder-structure.md.
##
## TODO:
##  - Define how the base scene is resolved per concrete factory.
##  - Define create(definition) -> Node and the configuration step.
##  - Decide validation/fallback when a definition is malformed.
class_name EntityFactory
extends RefCounted


## Build and configure one entity from a parsed JSON definition.
## Subclasses override; base returns null (nothing to build abstractly).
func create_from_definition(_definition: Dictionary) -> Node:
	return null


## Resolve the base scene this factory instantiates from. Subclasses override.
func _get_base_scene() -> PackedScene:
	return null


## Apply a definition's fields onto an already-instantiated entity.
func _configure(_entity: Node, _definition: Dictionary) -> void:
	pass
