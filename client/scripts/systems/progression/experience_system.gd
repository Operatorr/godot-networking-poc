## ExperienceSystem - Client display of XP / level progression.
##
## Renders the player's XP bar and level-up feedback from server/API-authoritative
## PROGRESS events. The Rust server + Go API own XP and level — the client requests,
## the server decides; this node never grants levels, it only animates the values it
## is told and predicts the bar fill between events for smooth UI.
##
## Curve (mirrors sim_core/progression, for display/preview only):
##   MonsterEXP   = round(100 * 1.15^(L-1))            # XP a monster of level L grants
##   EXPRequired: L1 = 5  * MonsterEXP(1)              # to go 1 -> 2
##                L2..49 = 10 * MonsterEXP(L)          # to go L -> L+1
##   Level cap    = 50
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): pulls curve constants from the progression definitions; defers final
## authority to the API. See LevelSystem/StatSystem for the shared curve helpers.
##
## Governing docs: docs/gdd/progression/, docs/systems/PROGRESSION.md.
##
## # TODO:
##   - Subscribe to PROGRESS events; update current_xp / level and emit signals.
##   - Drive the XP bar fill (display prediction); reconcile to server values.
##   - Trigger level-up VFX/SFX on an authoritative level change only.
class_name ExperienceSystem
extends Node

## XP awarded by killing a monster of the given level: round(100 * 1.15^(L-1)).
const EXP_BASE: float = 100.0
const EXP_GROWTH: float = 1.15
## Multipliers for XP required to advance: 5x for L1->2, 10x for L2..49.
const REQUIRED_MULT_FIRST: int = 5
const REQUIRED_MULT_REST: int = 10
const LEVEL_CAP: int = 50


## Apply an authoritative XP grant from a PROGRESS event (display only).
func add_experience(amount: int) -> void:
	# TODO: accumulate, roll over levels via LevelSystem, emit signals.
	pass


## XP required to advance FROM the given level (display preview).
func xp_required_for_level(level: int) -> int:
	# TODO: REQUIRED_MULT_* * round(EXP_BASE * EXP_GROWTH^(level-1)); clamp at cap.
	return 0


## Reconcile local display to the server/API authoritative state.
func sync_from_server(level: int, current_xp: int) -> void:
	# TODO: set level/current_xp to authoritative values; re-fill bar.
	pass
