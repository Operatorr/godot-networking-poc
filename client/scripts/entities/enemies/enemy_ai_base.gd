## EnemyAiBase - client-side enemy AI strategy seam (OFFLINE modes only).
##
## Responsibility: the Strategy base for steering a client-controlled enemy when
## there is NO server — i.e. the offline/sandbox modes. In live networked play
## the authoritative monster AI runs in the Rust server
## (rust/server/src/monster.rs); this class never executes there. Today the live
## offline enemy ([OfflineMonster]) carries its own compact FSM; this seam is the
## intended home for that logic once profiles are factored out. Governing rule:
## **the client requests, the server decides** — but offline there IS no server,
## so this strategy is the sole decider for offline enemies and ONLY offline.
##
## Two-axis difficulty (GDD: docs/gdd/MONSTERS.md):
##   1. LEVEL — stat scaling (HP, damage, speed) from the monster level/tier.
##   2. AI TUNING — behavioural aggression: perception range, leash, attack
##      cadence, kite distance. The same archetype can be made harder by AI
##      tuning WITHOUT changing its level. These are orthogonal knobs.
##
## Data-driven pattern (GDD): JSON definition -> Factory -> base scene ->
## configured entity. The same [MonsterDefinition] JSON the server AI reads also
## feeds these offline profiles (move_speed, ranges, cooldown), so a monster
## fights the same offline as online. Profiles are STRATEGY + DATA (melee vs
## ranged), not enemy subclasses.
##
## Governing docs: docs/gdd/MONSTERS.md, docs/systems/monsters-ai.md.
##
## TODO:
## - configure(definition, level): apply level stat-scaling + AI-tuning knobs.
## - decide(self_pos, target_pos, delta): return the steering/intent for this
##   tick (move vector, whether to attack). Subclasses implement per profile.
class_name EnemyAiBase
extends RefCounted

## Level axis: stat-scaling tier (HP/damage/speed multipliers derive from this).
var level: int = 1

## AI-tuning axis: how far the enemy notices the target (world units).
var perception_range: float = 0.0

## AI-tuning axis: seconds between attacks.
var attack_cooldown: float = 0.0


## Apply both difficulty axes from a parsed MonsterDefinition Dictionary and a
## level. Subclasses extend for profile-specific tuning.
# TODO: read move_speed/ranges/cooldown; scale stats by level.
func configure(_definition: Dictionary, _level: int) -> void:
	pass


## Decide this tick's intent for an offline enemy. Returns a Dictionary like
## { "move": Vector2, "attack": bool }. Subclasses implement the profile.
# TODO: per-profile chase/kite/attack decision.
func decide(_self_pos: Vector2, _target_pos: Vector2, _delta: float) -> Dictionary:
	return {}
