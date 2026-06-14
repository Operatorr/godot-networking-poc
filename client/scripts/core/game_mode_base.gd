## GameModeBase - Abstract base for game modes (Template Method).
##
## One subclass per mode (PvE / PvP / Race). The base defines the lifecycle
## skeleton — on_enter / tick / on_player_death / on_exit — and concrete modes
## fill in the rule-specific hooks. Scenes drive a single active GameModeBase;
## they never branch on mode by hand.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The mode selects *which* data the factories use (monster tables, loot
## tables, win/lose rules) and reacts to gameplay events; it does not itself spawn
## the low-level entities.
##
## Authority note: "the client requests, the server decides." Mode hooks here run
## client-side for prediction, presentation, and local state — never as the rule
## authority. The server enforces win/lose, death, and rewards; these hooks mirror
## those outcomes for the player.
##
## Governing docs: docs/gdd/game-modes.md.
##
## TODO:
##  - Define the hook contract (what each hook may/may not do client-side).
##  - Give subclasses access to the shared run context (see GameSession).
##  - Decide how the active mode is constructed/swapped on scene change.
class_name GameModeBase
extends RefCounted


## Called when the mode becomes active (scene loaded, run started).
func on_enter() -> void:
	pass


## Called when the mode is torn down (run over, leaving to sanctuary).
func on_exit() -> void:
	pass


## Per-tick hook for client-side mode bookkeeping (display/prediction only).
func tick(_delta: float) -> void:
	pass


## Reaction hook when the local player dies (server-confirmed).
func on_player_death() -> void:
	pass
