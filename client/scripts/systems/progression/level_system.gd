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
## TODO:
##   - Implement xp->level and level->xp-threshold mapping from the shared curve.
##   - Match server rounding (round() for MonsterEXP) to avoid boundary drift.
class_name LevelSystem
extends RefCounted

## Canonical XP curve for the whole client (ExperienceSystem/StatSystem read it here —
## single source of truth; do not duplicate these constants elsewhere).
const EXP_BASE: float = 100.0
const EXP_GROWTH: float = 1.15
## XP-required multipliers: 5x to go L1->2, 10x for L(2..49)->next.
const REQUIRED_MULT_FIRST: int = 5
const REQUIRED_MULT_REST: int = 10
const LEVEL_CAP: int = 50


## XP a monster of level L grants: round(100 * 1.15^(L-1)). Matches sim_core's round().
static func monster_exp(level: int) -> int:
	var l: int = clampi(level, 1, LEVEL_CAP)
	return int(round(EXP_BASE * pow(EXP_GROWTH, float(l - 1))))


## XP required to advance FROM `level` to `level + 1`; 0 at/above the cap (display preview).
static func advance_cost(level: int) -> int:
	if level < 1 or level >= LEVEL_CAP:
		return 0
	var mult: int = REQUIRED_MULT_FIRST if level == 1 else REQUIRED_MULT_REST
	return mult * monster_exp(level)


## Level reached for a given cumulative XP total (clamped to LEVEL_CAP).
static func level_for_xp(total_xp: int) -> int:
	var remaining: int = maxi(total_xp, 0)
	var level: int = 1
	while level < LEVEL_CAP:
		var cost: int = advance_cost(level)
		if remaining < cost:
			break
		remaining -= cost
		level += 1
	return level


## Cumulative XP needed to first reach the given level (sum of 1..level-1 advance costs).
static func xp_for_level(level: int) -> int:
	var total: int = 0
	for l in range(1, clampi(level, 1, LEVEL_CAP)):
		total += advance_cost(l)
	return total
