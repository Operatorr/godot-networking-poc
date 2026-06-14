## DatabaseLoader - Boot-time loader for every JSON definition catalogue.
##
## Responsibility: walk res://data/** at boot, parse each catalogue (monsters,
## classes, spells, projectiles, items, loot, balance), validate it, and hand
## the parsed definitions to a [DefinitionCache]. This is the entry point of the
## data-driven pipeline:
##     JSON definition -> DatabaseLoader (this) -> DefinitionCache -> Factory
##                     -> base scene -> configured entity.
## New content is added by dropping JSON in res://data/<kind>/, NOT by code.
##
## Loading is export-safe: each kind carries an index.json manifest (FileAccess
## by known path works inside an exported .pck); a best-effort DirAccess scan
## additionally auto-discovers files during editor development. Mirrors the
## MonsterDatabase / ServerConfig JSON-loading pattern.
##
## Authority note: "the client requests, the server decides." This loader only
## populates the client's display/prediction view of content; the Rust server is
## the numeric authority and re-validates everything it acts on.
##
## Governing docs: gdd/index.md (Data-Driven Content System),
## gdd/folder-structure.md, docs/CMS.md (hot-reload).
##
## TODO:
## - Enumerate the catalogue roots under res://data/ (monsters, classes, spells,
##   projectiles, items, loot, balance) and their index.json manifests.
## - Parse each JSON via FileAccess + JSON.parse; route by kind to the matching
##   <Kind>Definition.from_dict() builder.
## - Run SchemaValidator (raw JSON) then DefinitionValidator (parsed) per entry;
##   collect errors instead of aborting so one bad file never blocks boot.
## - Insert valid definitions into the supplied DefinitionCache keyed by id.
## - Expose load results/error report for the CMS + a startup health check.
class_name DatabaseLoader
extends RefCounted

const DATA_ROOT := "res://data/"


## Load every catalogue under res://data/** into the given cache.
## Returns true if all catalogues loaded without fatal errors.
func load_all(cache: DefinitionCache) -> bool:
	# TODO: iterate catalogue kinds, parse + validate, populate cache.
	return false


## Load (or reload) a single catalogue kind (e.g. "classes", "spells", "items")
## into the cache. Used for targeted CMS hot-reload.
func load_kind(kind: String, cache: DefinitionCache) -> bool:
	# TODO: resolve dir/manifest for kind, parse + validate, populate cache.
	return false


## Accumulated human-readable errors from the last load pass (empty == clean).
func get_errors() -> Array:
	# TODO: return collected validation/parse errors.
	return []
