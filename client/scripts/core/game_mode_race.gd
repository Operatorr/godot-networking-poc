## GameModeRace - Cutthroat races (PoE-style fresh-start level race).
##
## Concrete GameModeBase for time-boxed competitive races: every entrant starts
## from scratch and races to progress (level/objectives) in a PvPvE setting.
##
## NOTE (per GDD): races run in INSTANCES OF THE NORMAL WORLD — there are NO
## race-track scenes. A race is a rule set + a fresh-start instance layered over
## the existing world, not bespoke geometry. Treat the world data as-is; the mode
## supplies the race rules, timer, and standings on top.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene -> configured
## entity. The race uses the normal world's biome/monster/loot data via the same
## factories; only the rule set (fresh start, timer, ranking) differs.
##
## Authority note: "the client requests, the server decides." Race standings,
## timer, and completion are server-authoritative; these hooks mirror and present
## them (ladder, countdown, finish screen).
##
## Governing docs: docs/gdd/game-modes.md, docs/gdd/progression/.
##
## TODO:
##  - Mirror race timer + standings from the server; present the ladder.
##  - Enforce fresh-start presentation (no carried gear/level) client-side.
##  - Handle race-end transition and final ranking display.
class_name GameModeRace
extends GameModeBase


func on_enter() -> void:
	pass


func on_exit() -> void:
	pass


func tick(_delta: float) -> void:
	pass


## Server-confirmed local death during the race (PvPvE rules apply).
func on_player_death() -> void:
	pass
