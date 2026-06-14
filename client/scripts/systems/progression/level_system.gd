## LevelSystem - Pure level-curve helpers (display only).
##
## Stateless math mirroring sim_core/progression: converts between XP totals and
## levels for the UI (XP bar, "next level" preview, level-up thresholds). The Rust
## server + Go API are authoritative for the player's actual level — the client
## requests, the server decides; these helpers exist so the client can render and
## predict, never to assign a level.
##
## Curve (must match sim_core exactly):
##   MonsterEXP(L) = round(100 * 1.15^(L-1));  cap = 50
##   to advance:  L1->2 = 5 * MonsterEXP(1);  L(2..49)->next = 10 * MonsterEXP(L)
##
## Data-driven pattern (GDD: JSON definition -> Factory -> base scene -> configured
## entity): curve constants come from the progression definitions; consumed by
## ExperienceSystem (display) and StatSystem (stat scaling). Keep parity with the
## server's truncate/round policy — see docs/server/contract.md numerics.
##
## Governing docs: docs/gdd/progression/, docs/systems/PROGRESSION.md.
##
## # TODO:
##   - Implement xp->level and level->xp-threshold mapping from the shared curve.
##   - Match server rounding (round() for MonsterEXP) to avoid boundary drift.
class_name LevelSystem
extends RefCounted

const EXP_BASE: float = 100.0
const EXP_GROWTH: float = 1.15
const LEVEL_CAP: int = 50


## Level reached for a given cumulative XP total (display preview).
static func level_for_xp(total_xp: int) -> int:
	# TODO: accumulate thresholds until total_xp is exhausted; clamp to LEVEL_CAP.
	return 1


## Cumulative XP needed to first reach the given level (display preview).
static func xp_for_level(level: int) -> int:
	# TODO: sum per-level requirements 1..level-1.
	return 0
