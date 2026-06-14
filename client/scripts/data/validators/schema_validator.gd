## SchemaValidator - Structural validation of raw JSON against a schema.
##
## Runs in the data-driven pipeline FIRST, on the raw parsed dictionary, before
## any <Kind>Definition is built:
##     JSON definition -> DatabaseLoader -> SchemaValidator (this)
##                     -> <Kind>Definition.from_dict() -> DefinitionValidator
##                     -> DefinitionCache -> Factory -> base scene -> entity.
## Checks SHAPE against the JSON schemas in res://data/schemas/*.json: required
## keys present, value types correct, no unknown top-level keys. Semantic/range
## checks belong to DefinitionValidator, not here.
##
## Authority note: "the client requests, the server decides." This is purely a
## client-side load-time guard so malformed content fails fast and visibly.
##
## Governing docs: gdd/index.md (Data-Driven Content System),
## gdd/folder-structure.md, docs/CMS.md (hot-reload re-validates on push).
##
## TODO:
## - Load + cache the schema JSON for each kind from res://data/schemas/<kind>.json.
## - Walk required keys + type tags ("string"/"number"/"int"/"array"/"object"/
##   "color") and report mismatches with the offending key path.
## - Flag unknown top-level keys (typo guard) without failing forward-compat data.
## - Return a structured result: ok flag + list of human-readable errors.
class_name SchemaValidator
extends RefCounted

const SCHEMA_DIR := "res://data/schemas/"

## Errors collected by the most recent validate() call (empty == valid).
var errors: Array = []


## Validate a raw parsed JSON dictionary for the given kind against its schema.
## Returns true if the shape conforms; populates errors otherwise.
func validate(kind: String, raw: Dictionary) -> bool:
	# TODO: load schema for kind, check required keys + value types.
	return false


## Preload (and cache) the schema for a kind so repeated validates are cheap.
func load_schema(kind: String) -> bool:
	# TODO: read res://data/schemas/<kind>.json into the schema cache.
	return false
