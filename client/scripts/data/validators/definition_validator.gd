## DefinitionValidator - Semantic validation of a parsed definition object.
##
## Runs in the data-driven pipeline AFTER parsing, BEFORE the definition enters
## the cache:
##     JSON definition -> DatabaseLoader -> SchemaValidator (raw shape)
##                     -> <Kind>Definition.from_dict() -> DefinitionValidator (this)
##                     -> DefinitionCache -> Factory -> base scene -> entity.
## Where SchemaValidator checks JSON SHAPE, this checks SEMANTICS: required
## fields present, numeric ranges sane, cross-references resolvable (e.g. a
## class's ability id exists, an item's biome_requirement names a real biome).
##
## Authority note: "the client requests, the server decides." This is a client
## sanity gate so bad content fails loudly at boot; the Rust server is the
## numeric authority and re-validates whatever it acts on (server/contract.md).
##
## Governing docs: gdd/index.md, server/contract.md (numerics policy).
##
## TODO:
## - Per-kind required-field + range rules (health > 0, cooldown >= 0, etc.).
## - Cross-reference checks against a DefinitionCache (ability/projectile/biome
##   ids resolve).
## - Return a structured result: ok flag + list of human-readable errors;
##   never throw, never abort the whole load for one bad entry.
class_name DefinitionValidator
extends RefCounted

## Errors collected by the most recent validate() call (empty == valid).
var errors: Array = []


## Validate a parsed definition object of the given kind. Returns true if valid;
## populates errors with human-readable messages otherwise.
func validate(kind: String, definition: Object) -> bool:
	# TODO: dispatch by kind; check required fields, ranges, references.
	return false


## Validate a whole already-parsed bucket (kind -> { id -> definition }),
## including cross-references. Returns true if every entry is valid.
func validate_kind(kind: String, definitions: Dictionary) -> bool:
	# TODO: validate each entry + resolve cross-references.
	return false
