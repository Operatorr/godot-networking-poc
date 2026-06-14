## PlayerClassRogue - Rogue client feel: fast primary + Shadowstep.
##
## Responsibility: concrete [PlayerClassBase] strategy for the Rogue. Its RMB
## ability is **Shadowstep** (a blink + brief stealth): an instant teleport
## toward the cursor that the client PREDICTS as a blink (snap to the predicted
## landing) and then reconciles against the server's confirmed position; the
## stealth state and its duration are server-decided. Governing rule:
## **the client requests, the server decides** — we predict the blink landing
## and telegraph it; the server owns the actual teleport result and stealth.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The ClassFactory instances this strategy for class id
## "rogue" and feeds it that JSON (blink range, stealth duration, primary
## cadence). Behaviour is STRATEGY + DATA, not a Player subclass.
## `ability_predicts_motion = true` for this class.
##
## Governing docs: docs/gdd/classes/rogue.md, docs/systems/abilities.md.
##
## TODO:
## - override load_definition() to read blink range + stealth duration.
## - override predict_ability_motion() to snap to the predicted blink landing
##   and flag a reconcile on server confirm.
## - override draw_ability_preview() to draw the blink target marker (clamped
##   to range).
class_name PlayerClassRogue
extends PlayerClassBase

## Predicted blink reach in world units (loaded from the class definition).
var blink_range: float = 0.0

## Stealth duration in seconds — display hint; the server owns the real state.
var stealth_duration: float = 0.0


## Predict the Shadowstep blink: snap toward the clamped landing this frame,
## then reconcile. The server decides the real teleport + stealth outcome.
# TODO: compute clamped landing, snap, mark reconcile on confirm.
func predict_ability_motion(_delta: float) -> void:
	pass


## Draw the Shadowstep telegraph (blink target marker) at the cursor.
# TODO: render the landing marker clamped to blink_range.
func draw_ability_preview(_target: Vector2) -> void:
	pass
