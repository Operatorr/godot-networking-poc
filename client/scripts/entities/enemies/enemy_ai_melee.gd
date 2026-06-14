## EnemyAiMelee - offline melee-chaser AI profile.
##
## Responsibility: concrete [EnemyAiBase] strategy for an offline melee enemy —
## close the gap to the target and attack in contact range. OFFLINE modes ONLY;
## the authoritative version lives in the Rust server. Note: a dedicated melee
## profile is NOT implemented server-side today (only the ranged kiter is) — this
## is the offline counterpart of a planned archetype. Governing rule:
## **the client requests, the server decides** — irrelevant online; offline this
## strategy decides for itself because there is no server.
##
## Two-axis difficulty (GDD docs/gdd/MONSTERS.md): LEVEL scales stats; AI TUNING
## adjusts perception/leash/attack cadence. A melee enemy is made harder either
## by raising level (more HP/damage) or by tuning AI (longer perception, faster
## swings) — independently.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. Reads the shared [MonsterDefinition] JSON; differs from the
## ranged profile by STRATEGY, not subclass-of-enemy.
##
## Governing docs: docs/gdd/MONSTERS.md, docs/systems/monsters-ai.md.
##
## TODO:
## - override configure() to read melee reach + chase speed.
## - override decide() to steer straight at the target and attack within reach.
class_name EnemyAiMelee
extends EnemyAiBase

## Contact range (world units) at which the melee attack lands.
var melee_reach: float = 0.0


## Offline melee decision: chase the target; attack when inside melee_reach.
# TODO: move toward target_pos; set attack true within reach.
func decide(_self_pos: Vector2, _target_pos: Vector2, _delta: float) -> Dictionary:
	return {}
