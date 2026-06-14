## PlayerClassWarrior - Warrior client feel: melee-range primary + Charge.
##
## Responsibility: concrete [PlayerClassBase] strategy for the Warrior. Its RMB
## ability is **Charge** (a movement_dash_blast): a forward dash toward the
## cursor that the client PREDICTS for snappy motion, then reconciles against the
## server's confirmed end position. Damage/knockback at the destination are
## server-decided. Governing rule:
## **the client requests, the server decides** — we predict the dash travel and
## telegraph the line; the server owns the hit and the final position.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The ClassFactory instances this strategy when the class
## definition's id is "warrior" and feeds it that JSON (dash distance/speed,
## primary cadence). Behaviour is STRATEGY + DATA, not a Player subclass.
## `ability_predicts_motion = true` for this class.
##
## Governing docs: docs/gdd/classes/warrior.md, docs/systems/abilities.md.
##
## TODO:
## - override load_definition() to read dash distance/speed/duration.
## - override predict_ability_motion() to integrate the Charge dash and flag a
##   reconcile when the server confirms.
## - override draw_ability_preview() to draw the dash line/destination marker.
class_name PlayerClassWarrior
extends PlayerClassBase

## Predicted dash reach in world units (loaded from the class definition).
var charge_distance: float = 0.0

## Predicted dash speed in units/sec (loaded from the class definition).
var charge_speed: float = 0.0


## Integrate the predicted Charge dash for this frame. Reconciles against the
## server's confirmed landing — the server, not us, decides where Charge ends.
# TODO: advance toward dash target; mark reconcile on server confirm.
func predict_ability_motion(_delta: float) -> void:
	pass


## Draw the Charge telegraph (dash line + destination marker) at the cursor.
# TODO: render the dash line clamped to charge_distance.
func draw_ability_preview(_target: Vector2) -> void:
	pass
