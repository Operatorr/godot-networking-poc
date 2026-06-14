## StatusEffectManager - Client display state for buffs/debuffs/DoTs/CC.
##
## Tracks the VISUAL state of status effects on entities (Daze, Stun, Stealth,
## DoT ticks, slows, shields) so the HUD and entity visuals can render icons,
## tints, and timers. The server is authoritative: flags like Daze/Stun/Stealth
## arrive in snapshots/PROGRESS events — the client requests, the server decides.
## This node never gates gameplay; a desynced effect here is purely cosmetic.
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): effect metadata (icon, color, default duration, stack rule) comes from
## a status-effect JSON definition; runtime application is driven by server flags.
##
## Governing docs: docs/systems/abilities.md (effect catalogue & CC rules),
## docs/server/contract.md (which flags ride the wire).
##
## # TODO:
##   - Define the effect record shape (id, source, expires_tick, stacks, magnitude).
##   - apply/refresh/remove from server flags; tick local timers for smooth UI only.
##   - Emit signals the HUD/visuals listen to (effect_added / effect_removed).
##   - Reconcile against the authoritative flag set each snapshot (server wins).
class_name StatusEffectManager
extends Node


## Apply or refresh an effect on an entity from a server-sourced flag/event.
func apply_effect(entity_id: int, effect_id: String, duration_ms: int) -> void:
	# TODO: insert/refresh record; emit effect_added; respect stack rules from JSON.
	pass


## Remove an effect (expired locally or cleared by the server).
func remove_effect(entity_id: int, effect_id: String) -> void:
	# TODO: drop record; emit effect_removed.
	pass


## True if the entity currently displays the given effect (UI queries only).
func has_effect(entity_id: int, effect_id: String) -> bool:
	# TODO: lookup in the per-entity effect table.
	return false


## All active effect ids on an entity, for HUD icon rendering.
func get_active_effects(entity_id: int) -> Array:
	# TODO: return the entity's current effect id list.
	return []


## Reconcile the local display set against the server's authoritative flags.
func reconcile_from_snapshot(entity_id: int, server_flags: Dictionary) -> void:
	# TODO: add/remove so local state matches server flags exactly.
	pass
