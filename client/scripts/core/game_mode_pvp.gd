## GameModePvP - PvP arena mode.
##
## Concrete GameModeBase for player-versus-player combat in the arena. Players
## fight each other under the PvP rule set (scoring, rounds, respawn/elimination
## per the GDD) rather than the PvE dive loop.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. PvP selects the arena/loadout data the factories use and applies the
## PvP rules; it does not author the underlying entities or spells.
##
## Authority note: "the client requests, the server decides." Kills, scores, and
## round outcomes are server-authoritative; these hooks mirror and present them
## (scoreboard, kill feed, round transitions).
##
## Governing docs: docs/gdd/game-modes.md.
##
## TODO:
##  - Define PvP scoring/round state (mirror of server state).
##  - On server-confirmed death: respawn vs eliminate per rules; update scoreboard.
##  - Present round start/end and match results.
class_name GameModePvP
extends GameModeBase


func on_enter() -> void:
	pass


func on_exit() -> void:
	pass


func tick(_delta: float) -> void:
	pass


## Server-confirmed local death in the arena (respawn/eliminate per rules).
func on_player_death() -> void:
	pass
