## EventBus - Global signal hub (Observer).
##
## A single autoload that decouples emitters from listeners: systems fire signals
## here, and any scene/UI subscribes without holding direct references to the
## source. Registered as the autoload named `EventBus`; access it as `EventBus`
## from anywhere.
##
## Keep this hub for genuinely cross-cutting, app-wide events (run/mode changes,
## death, loot, HUD-relevant notifications). Local, parent-child signalling should
## stay on the nodes themselves — don't funnel everything through here.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The bus is the glue *around* that pipeline: factories/modes announce
## results here so display/UI systems react without coupling to the producers.
##
## Authority note: "the client requests, the server decides." Signals here carry
## already-decided, server-confirmed (or purely client-side display) events. The
## bus is not an authority and must not be used to bypass the server.
##
## Governing docs: docs/gdd/index.md, docs/gdd/game-modes.md.
##
## TODO:
##  - Settle the canonical signal set + payloads (the ones below are examples).
##  - Document who emits / who listens for each.
##  - Consider grouping signals by domain if this grows large.
extends Node

# --- Example signals (illustrative — finalise names/payloads before use) -----

## Example: the active run/mode changed (e.g. entered a PvE run).
# signal run_started(run_id: String, mode: int)

## Example: the local player died (server-confirmed).
# signal player_died(player_id: int)

## Example: loot was granted to the local player (server-authoritative).
# signal loot_received(item_spec: Dictionary)

## Example: a HUD-relevant notification to surface to the player.
# signal notification(text: String)


func _ready() -> void:
	pass
