## LivingEntity - a BaseEntity that can take damage and die (client view).
##
## Responsibility: adds the health/damage/death DISPLAY layer on top of
## BaseEntity — current/max HP mirrored from the server, hit-flash + floating
## numbers, and the death visual/cleanup. It owns no authority: HP is
## server-authoritative state we are shown. Governing rule:
## **the client requests, the server decides** — we never locally subtract HP
## to "decide" a kill; we render the HP/death the server replicated.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The Factory stamps max_hp (and any resist/armor display
## hints) from the definition; HP itself arrives via snapshots. Health tracking
## composes via the existing [HPComponent] child rather than being inlined here
## (composition over inheritance). Live [Player]/[Monster] already use
## HPComponent and predate this base — they are the parity reference.
##
## Governing docs: docs/systems/combat-hits.md, docs/server/contract.md
## (HP fields in snapshots / death events).
##
## TODO:
## - Hold a reference to the child HPComponent; relay its hp_changed/died.
## - apply_health(current, max) from snapshot; trigger hit-flash on decrease.
## - on_death(): play death visual then free/return-to-pool (no local kill
##   decision — only react to the server's death signal).
class_name LivingEntity
extends BaseEntity

## Emitted for audio/FX when replicated HP drops. Display only.
signal took_damage(amount: int)

## Emitted when the server reports this entity dead.
signal died()

## Server-mirrored health (display copy; authority lives on the server).
var current_hp: int = 0
var max_hp: int = 0


## Apply a server HP update (from a snapshot/event). Fires took_damage on a
## decrease so FX can play; does NOT itself decide death.
# TODO: diff against current_hp, flash on damage, store new values.
func apply_health(_current: int, _max: int) -> void:
	pass


## React to the server-authoritative death of this entity (play visual, clean
## up). Never invoked by local HP reaching zero — only by a server death event.
# TODO: play death anim, emit died(), free or pool the node.
func on_death() -> void:
	pass
