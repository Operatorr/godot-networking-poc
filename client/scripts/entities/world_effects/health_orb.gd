## HealthOrb - client view of a monster-death heal pickup (world-effect subtype 0).
##
## Responsibility: render the heal orb that drops on monster death — protocol
## kind 3, subtype **0**, id band **40000–42499**. Walking over it heals the
## player (+5 HP per docs/server/contract.md). The orb is NOT an ability; it is a
## monster-death drop that shares the world-effect entity kind. The pickup is
## **server-authoritative** and reported via the `PICKUP {kind, amount}` event —
## the client only shows the orb and plays the pickup FX on that event.
## Governing rule:
## **the client requests, the server decides** — we never locally grant the heal
## or remove the orb; we react to the server's PICKUP.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The WorldEffectFactory instances this subclass for ids in
## the 40000–42499 sub-band and configures its visuals from the snapshot.
##
## Governing docs: docs/server/contract.md (PICKUP=6 payload, id bands),
## docs/systems/abilities.md (Healthorb row), docs/gdd/loot.md.
##
## TODO:
## - override configure() to set the orb sprite + bob/pulse VFX.
## - on_picked_up(amount): play pickup FX + free, driven by the server PICKUP
##   event (NOT by local overlap detection).
class_name HealthOrb
extends WorldEffect

## Heal magnitude shown on pickup (authoritative value arrives in PICKUP.amount).
const HEAL_AMOUNT := 5


## React to the server's PICKUP event for this orb: play FX and despawn.
## `amount` is the server-reported heal. We do not decide the heal ourselves.
# TODO: spawn heal FX, then free the orb.
func on_picked_up(_amount: int) -> void:
	pass
