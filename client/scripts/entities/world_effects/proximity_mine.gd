## ProximityMine - client view of the Engineer's Mine (world-effect subtype 1).
##
## Responsibility: render the Engineer's deployed mine — protocol kind 3, subtype
## **1**, id band **42500–44999**. Server-side it arms (~0.5 s), proximity-
## triggers, deals an AOE blast, and expires at 30 s; the client renders the
## arm-state telegraph and the blast VFX. The mine is a DEFERRED class effect
## (the Engineer class is deferred per the GDD); this stub exists so the entity
## taxonomy is complete. Governing rule:
## **the client requests, the server decides** — arming, the proximity trigger,
## and the blast/damage are all server-authoritative; this is display only.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The WorldEffectFactory instances this subclass for ids in
## the 42500–44999 sub-band and configures arm/blast visuals from the snapshot +
## effect definition (arm time, blast radius).
##
## Governing docs: docs/systems/abilities.md (Engineer — Mine row),
## docs/server/contract.md (world-effect band), docs/gdd/classes/engineer.md.
##
## TODO (DEFERRED — Engineer class):
## - override configure() to set the mine sprite + armed/unarmed state.
## - show_armed(): switch to the armed telegraph when the server arms it.
## - on_detonate(): play the AOE blast VFX on the server's trigger event.
class_name ProximityMine
extends WorldEffect

## Whether the mine has armed (server-reported; display state only).
var is_armed: bool = false


## React to the server arming this mine: switch to the armed telegraph.
# TODO: set is_armed, swap visual.
func show_armed() -> void:
	pass


## React to the server-authoritative detonation: play the AOE blast VFX + free.
# TODO: spawn blast FX at radius, then free.
func on_detonate() -> void:
	pass
