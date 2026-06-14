## GameSession - Central run/session state shared across scenes.
##
## Holds the cross-scene flags that describe *what* we're playing right now:
## the active game mode, the current world/biome, the run id, and softcore/
## hardcore choice. Scenes and systems read this instead of threading the same
## arguments through every load; it is the single source of truth for "where am I".
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. GameSession is the *context* the factories consult — e.g. which biome's
## monster table the EnemyFactory should pull from, which mode's rules apply.
##
## Authority note: "the client requests, the server decides." This object is a
## client-side mirror for prediction/display only. The server owns the real run
## state; GameSession reflects what the server has told us and what the player chose.
##
## Governing docs: docs/gdd/game-modes.md, docs/gdd/BIOMES.md, docs/server/contract.md.
##
## TODO:
##  - Define the mode enum (PvE / PvP / Race) and current-mode storage.
##  - Track world/biome id and run id (server-assigned); reset on new run.
##  - Track softcore vs hardcore for the active PvE run.
##  - Emit / route changes through EventBus so HUD + systems react.
##  - Provide a reset() for returning to the sanctuary / starting a fresh run.
class_name GameSession
extends RefCounted


## Active game mode (see game-modes.md). Mirror of server-assigned mode.
var mode: int = 0

## Current world / biome id (drives factory data tables). See BIOMES.md.
var biome_id: String = ""

## Server-assigned run id for the active run (empty when in sanctuary).
var run_id: String = ""

## Hardcore (permadeath) vs softcore for the active PvE run.
var hardcore: bool = false


## Reset to a clean slate (e.g. back in the sanctuary, before a new run).
func reset() -> void:
	pass


## Apply server-authoritative run info (the client requests, the server decides).
func apply_server_run_info(_info: Dictionary) -> void:
	pass


## Convenience query for the active mode.
func get_mode() -> int:
	return mode
