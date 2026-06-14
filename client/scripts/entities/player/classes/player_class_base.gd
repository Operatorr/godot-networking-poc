## PlayerClassBase - client-side "feel" strategy for one player class.
##
## Responsibility: the Strategy + Template-Method base that encapsulates how a
## class FEELS on the client — primary-attack (LMB) cadence/animation, and the
## RMB ability PREVIEW + locally-predicted motion (charge dash, blink) where the
## ability moves the player. It owns NONE of the outcome: damage, cooldown
## arbitration, and ability success are server-decided. Governing rule:
## **the client requests, the server decides** — these strategies build the
## request and the predicted feel; the server confirms or corrects it.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. A ClassFactory reads a class definition (loaded from
## docs/gdd/classes/<class>.md's data form, e.g. res://data/classes/<id>.json),
## instances the matching PlayerClass* strategy, and attaches it to the local
## [Player]. Differences between classes are STRATEGY + DATA, not Player
## subclasses (composition over inheritance). Concrete subclasses
## (Warrior/Rogue/Mage) override only the hooks they need.
##
## Governing docs: docs/gdd/classes/index.md, docs/systems/abilities.md,
## docs/server/contract.md (input/ability channel).
##
## TODO:
## - load_definition(def): parse primary cadence, ability id, predicted-motion
##   flag, preview shape from the class JSON.
## - get_primary_cooldown(): seconds between LMB attacks (display/feel only).
## - build_primary_request(aim) / build_ability_request(cursor): produce the
##   input payload the client SENDS (server validates + resolves).
## - draw_ability_preview(target): RMB telegraph (cursor AOE, dash line...).
## - predict_ability_motion(delta): default no-op; movement classes override.
class_name PlayerClassBase
extends RefCounted

## Stable class id (e.g. "warrior", "rogue", "mage"). Set from the definition.
var class_id: String = ""

## Display name for HUD. Set from the definition.
var display_name: String = ""

## Seconds between primary (LMB) attacks — feel/telegraph only, not authority.
var primary_cooldown: float = 0.3

## Whether the RMB ability locally predicts player motion (override per class).
var ability_predicts_motion: bool = false


## Template entry: parse a class definition Dictionary (from JSON) into the
## fields above. Subclasses extend for their ability-specific data.
# TODO: read primary cadence, ability id, preview/prediction config.
func load_definition(_def: Dictionary) -> void:
	pass


## Build the input payload the client SENDS for a primary attack. Aim is the
## world-space direction. Server validates and resolves the actual shot.
# TODO: pack aim/seq into the request dictionary.
func build_primary_request(_aim: Vector2) -> Dictionary:
	return {}


## Build the input payload the client SENDS to request the RMB ability.
## `cursor` is the world-space cursor/target. Server decides success.
# TODO: pack ability id + cursor/target.
func build_ability_request(_cursor: Vector2) -> Dictionary:
	return {}


## Draw/refresh the RMB ability preview (telegraph) at the given target. Pure
## display. Default: nothing to preview.
# TODO: subclasses draw their shape (line, circle, cone...).
func draw_ability_preview(_target: Vector2) -> void:
	pass


## Locally predict ability-driven player motion this frame (dash/blink).
## Default: ability does not move the player. Movement classes override and
## must reconcile against the server's confirmed position.
# TODO: integrate predicted motion; expect server correction.
func predict_ability_motion(_delta: float) -> void:
	pass
