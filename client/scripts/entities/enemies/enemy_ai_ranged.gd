## EnemyAiRanged - offline ranged-kiter AI profile.
##
## Responsibility: concrete [EnemyAiBase] strategy for an offline ranged enemy —
## hold a preferred distance from the target, kite away when too close, and fire
## on cooldown. This mirrors the ONLY profile implemented server-side today (the
## ranged kiter in rust/server/src/monster.rs); the live [OfflineMonster] FSM
## already approximates it. OFFLINE modes ONLY. Governing rule:
## **the client requests, the server decides** — online the server runs this;
## offline this strategy is the sole decider because there is no server.
##
## Two-axis difficulty (GDD docs/gdd/MONSTERS.md): LEVEL scales stats; AI TUNING
## adjusts perception, kite distance, and fire cadence — orthogonally. A kiter is
## made harder by leveling (stats) OR by tightening AI tuning (kites sooner,
## fires faster), independently.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. Reads the shared [MonsterDefinition] JSON (move_speed,
## ranges, cooldown, projectile speed/damage); differs from the melee profile by
## STRATEGY, not subclass-of-enemy.
##
## Governing docs: docs/gdd/MONSTERS.md, docs/systems/monsters-ai.md,
## rust/server/src/monster.rs (parity reference).
##
## TODO:
## - override configure() to read preferred/kite distance + projectile params.
## - override decide() to maintain stand-off range, kite when too close, and
##   flag a ranged attack on cooldown.
class_name EnemyAiRanged
extends EnemyAiBase

## Preferred stand-off distance from the target (world units).
var preferred_distance: float = 0.0

## Distance at which the enemy begins kiting away (world units).
var kite_distance: float = 0.0


## Offline ranged decision: keep stand-off range, kite when inside kite_distance,
## attack on cooldown.
# TODO: compute approach/kite move; set attack when in range and off cooldown.
func decide(_self_pos: Vector2, _target_pos: Vector2, _delta: float) -> Dictionary:
	return {}
