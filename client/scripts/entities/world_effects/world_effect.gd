## WorldEffect - client view of a server "world-effect" entity (protocol kind 3).
##
## Responsibility: the base render node for the lingering, server-spawned effect
## entities that occupy protocol **kind 3**, id band **40000–49999** — health
## orbs and ability effects (mines, DoT zones, orbiting bibles). It renders the
## effect's position/lifetime/VFX from the snapshot stream; it owns no behaviour.
## Arming, proximity triggers, DoT ticks, sweep damage, expiry, and pickup are
## ALL server-decided. Governing rule:
## **the client requests, the server decides** — a WorldEffect is purely the
## client's picture of a server-authoritative entity.
##
## World-effect band (docs/server/contract.md, docs/systems/abilities.md):
## the 40000–49999 band is partitioned into 2500-id sub-bands BY SUBTYPE —
##   0 healthorb (40000–42499), 1 mine (42500–44999),
##   2 dot-zone (45000–47499), 3 bible (47500–49999).
## A snapshot carries the typed id; subtype is derivable from the id band.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. A WorldEffectFactory maps subtype -> the matching subclass
## scene and configures it from the snapshot + an effect definition (radius,
## lifetime, VFX). New effect types are added by DATA + a thin subclass, not by
## bloating one class. Composition over inheritance.
##
## Governing docs: docs/server/contract.md (kind 3 / id bands / PICKUP),
## docs/systems/abilities.md (world-effect table).
##
## TODO:
## - subtype()/from_id(): derive subtype 0..3 from the entity id band.
## - configure(snapshot, definition): set position, radius, lifetime, VFX.
## - apply_snapshot()/on_expire(): update from stream; despawn on server expiry.
## - NOTE: BaseEntity is not used as the base yet (BaseEntity extends Node2D too)
##   to keep this scaffold parse-safe and standalone; revisit once the entity
##   base is wired in.
class_name WorldEffect
extends Node2D

## Server-assigned typed id within 40000–49999. -1 until configured.
var entity_id: int = -1

## Subtype tag 0..3 (0 healthorb / 1 mine / 2 dot-zone / 3 bible).
var subtype: int = -1

## Effect radius in world units (display/telegraph; server owns the real shape).
var radius: float = 0.0


## Derive the subtype 0..3 from a world-effect entity id's 2500-id sub-band.
# TODO: map (id - 40000) / 2500 -> subtype.
func subtype_from_id(_id: int) -> int:
	return -1


## Configure from a snapshot + effect definition Dictionary (Factory entry).
# TODO: set id/subtype/position/radius/lifetime/VFX.
func configure(_snapshot: Dictionary, _definition: Dictionary) -> void:
	pass


## Apply one server snapshot for this effect (position/lifetime). Display only.
# TODO: update transform + remaining-lifetime visual.
func apply_snapshot(_snapshot: Dictionary) -> void:
	pass


## React to the server-authoritative expiry/removal of this effect.
# TODO: play fade-out then free the node.
func on_expire() -> void:
	pass
