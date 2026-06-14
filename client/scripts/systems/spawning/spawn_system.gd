## SpawnSystem - Client visual spawn coordinator.
##
## Instantiates and recycles the VISUAL representations of entities (monsters,
## pickups, effects) the server tells the client about. The server owns the
## authoritative spawn set — the client requests, the server decides; this node
## only mirrors that set onto pooled, factory-configured base scenes for display.
## It does NOT invent entities (offline practice goes through WaveSpawner instead).
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): given an entity-type id from a snapshot, resolve its JSON definition,
## ask the matching Factory to configure a pooled base scene, and place it. Reuses
## the live pools/detectors — see ProjectilePool (scripts/systems/spawning/),
## LocalHitDetector & HitAuthority (scripts/systems/combat/) — do not duplicate them.
##
## Governing docs: docs/gdd/folder-structure.md, docs/gdd/MONSTERS.md,
## docs/server/contract.md (entity id ranges & snapshot format).
##
## # TODO:
##   - Wire per-type object pools (reuse ProjectilePool pattern) keyed by entity type.
##   - On snapshot add: factory-configure a base scene from the JSON def, activate.
##   - On snapshot remove: recycle back to its pool (despawn VFX optional).
##   - Map server entity-id ranges (players/projectiles/monsters) to the right pool.
class_name SpawnSystem
extends Node


## Spawn (or reuse) the visual for a server-reported entity. Returns the instance.
func spawn_entity(entity_type: String, entity_id: int, position: Vector2) -> Node:
	# TODO: resolve JSON def -> Factory -> pooled base scene; place at position.
	return null


## Recycle the visual for an entity the server removed.
func despawn_entity(entity_id: int) -> void:
	# TODO: return instance to its pool; optionally play despawn VFX.
	pass


## Drop all spawned visuals (scene teardown / arena change).
func clear_all() -> void:
	# TODO: recycle every active instance to its pool.
	pass
