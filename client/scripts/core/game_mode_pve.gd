## GameModePvE - The primary PvE roguelite mode.
##
## Concrete GameModeBase for the main game: dive the world, fight monsters,
## gain EXP/loot, and either die (hardcore = permadeath) or extract. Softcore
## and Hardcore are variants of this same mode; death and voluntary sacrifice
## both convert progress into Glory per the GDD.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. This mode points the EnemyFactory/ItemFactory at the active biome's
## monster + loot tables and applies the PvE rule set; it does not author entities.
##
## Authority note: "the client requests, the server decides." Death, Glory, and
## loot grants are server-authoritative; the hooks here only mirror and present
## those outcomes (e.g. show the death screen, animate the Glory payout).
##
## Governing docs: docs/gdd/game-modes.md, docs/gdd/progression/, docs/gdd/loot.md.
##
## TODO:
##  - Branch softcore vs hardcore behaviour on death (read from GameSession).
##  - On server-confirmed death: compute/display Glory; route to outcome screen.
##  - Wire voluntary sacrifice (extract-for-Glory) request -> server.
##  - Drive biome/loot table selection for the factories.
class_name GameModePvE
extends GameModeBase


## True when this run is hardcore (permadeath); mirrors GameSession.hardcore.
var hardcore: bool = false


func on_enter() -> void:
	pass


func on_exit() -> void:
	pass


func tick(_delta: float) -> void:
	pass


## Server-confirmed local death: softcore vs hardcore, then Glory payout.
func on_player_death() -> void:
	pass


## Request voluntary sacrifice/extraction (client requests, server decides).
func request_sacrifice() -> void:
	pass
