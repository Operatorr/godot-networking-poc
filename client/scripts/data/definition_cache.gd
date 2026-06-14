## DefinitionCache - In-memory registry of parsed definitions, keyed by id.
##
## Responsibility: hold the parsed output of the data-driven pipeline so the rest
## of the client can look content up by id without touching disk:
##     JSON definition -> DatabaseLoader -> DefinitionCache (this) -> Factory
##                     -> base scene -> configured entity.
## One bucket per kind (classes, spells, projectiles, items, biomes, races,
## loot, balance); each bucket maps id -> the matching <Kind>Definition object.
##
## Supports hot-reload: the CMS can push updated JSON at runtime, and this cache
## swaps the affected entries atomically so live lookups never see a half state.
##
## Authority note: "the client requests, the server decides." Cached values are
## the client's display/prediction copy; the Rust server holds the authoritative
## numbers and may override anything cached here.
##
## Governing docs: gdd/index.md (Data-Driven Content System), docs/CMS.md.
##
## TODO:
## - Maintain per-kind id->definition dictionaries with O(1) lookup.
## - put()/get() typed accessors per kind (return null on miss, never throw).
## - replace_kind() for atomic CMS hot-reload of a whole bucket.
## - Emit a "definitions_reloaded(kind)" signal so views can refresh.
## - clear()/stats() for diagnostics + the CMS panel.
class_name DefinitionCache
extends RefCounted

## kind (String) -> { id (String) -> <Kind>Definition }
var _buckets: Dictionary = {}


## Store a parsed definition under (kind, id).
func put(kind: String, id: String, definition: Object) -> void:
	# TODO: insert into the kind's bucket, creating it if absent.
	pass


## Fetch a parsed definition by (kind, id), or null if absent.
func get_definition(kind: String, id: String) -> Object:
	# TODO: return _buckets[kind][id] if present, else null.
	return null


## True if (kind, id) is present.
func has_definition(kind: String, id: String) -> bool:
	# TODO: bucket membership check.
	return false


## Return all ids registered for a kind.
func ids_of(kind: String) -> Array:
	# TODO: return the kind bucket's keys.
	return []


## Atomically replace an entire kind bucket (CMS hot-reload).
func replace_kind(kind: String, definitions: Dictionary) -> void:
	# TODO: swap bucket and signal reload.
	pass


## Drop everything (e.g. before a full reload).
func clear() -> void:
	# TODO: empty all buckets.
	pass
