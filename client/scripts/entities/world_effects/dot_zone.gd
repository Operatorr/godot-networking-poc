## DotZone - client view of the Plague Seer's Plague Zone (world-effect subtype 2).
##
## Responsibility: render the Plague Seer's damage-over-time zone — protocol kind
## 3, subtype **2**, id band **45000–47499**. Server-side it applies DoT (12/s)
## to anything within its radius for 5 s; the client renders the zone circle and
## its lingering VFX. This is a DEFERRED class effect (the Plague Seer class is
## deferred per the GDD); the stub keeps the entity taxonomy complete. Governing
## rule:
## **the client requests, the server decides** — the per-tick DoT and the zone
## lifetime are server-authoritative; this node only draws the zone.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The WorldEffectFactory instances this subclass for ids in
## the 45000–47499 sub-band and configures the zone visual from the snapshot +
## effect definition (radius, duration, tick VFX).
##
## Governing docs: docs/systems/abilities.md (Plague Seer — Plague Zone row),
## docs/server/contract.md (world-effect band), docs/gdd/classes/plague_seer.md.
##
## TODO (DEFERRED — Plague Seer class):
## - override configure() to draw the zone circle at radius + ground VFX.
## - tick_vfx(): optional periodic visual pulse synced to the server DoT cadence
##   (display only; the server applies the actual damage).
class_name DotZone
extends WorldEffect

## DoT magnitude per second shown for telegraphing (server owns real damage).
const DOT_PER_SECOND := 12


## Optional periodic visual pulse synced to the server's DoT cadence. Display
## only — the server applies the damage.
# TODO: pulse the zone VFX.
func tick_vfx() -> void:
	pass
