## MonsterFactory - Builds server-authoritative MonsterState instances from data.
##
## The single seam for turning a monster archetype id + spawn position into a
## fully configured MonsterState (stats, AI tuning, appearance reference). All
## monster spawning flows through here so new archetypes need no spawn-path code.
##
## The factory only assembles state; entity-id allocation and tracking remain in
## MonsterManager, which owns the id range.
class_name MonsterFactory
extends RefCounted

var _database: MonsterDatabase = null


func _init(database: MonsterDatabase = null) -> void:
	_database = database if database != null else MonsterDatabase.get_shared()


## Create a MonsterState for the given archetype id at a position. The caller
## (MonsterManager) supplies the already-allocated entity id.
func create(type_id: String, entity_id: int, position: Vector2) -> MonsterState:
	var definition := _database.get_definition(type_id)
	return MonsterState.create_from_definition(entity_id, position, definition)


func get_database() -> MonsterDatabase:
	return _database
