## MonsterState - Server-side monster state container
## Holds authoritative state for a single monster entity
## Created by MonsterManager when spawning monsters
class_name MonsterState
extends RefCounted

## Unique entity ID for network sync (starts at 100000)
var entity_id: int = 0

## Current position in world space
var position: Vector2 = Vector2.ZERO

## Current health
var health: int = GameConstants.MONSTER_HEALTH

## Maximum health
var max_health: int = GameConstants.MONSTER_HEALTH

## Whether the monster is alive
var is_alive: bool = true

## Time when monster was spawned (server_time)
var spawn_time: float = 0.0

## Current animation state
var animation_state: int = PacketTypes.AnimationState.IDLE

## Entity flags bitfield
var entity_flags: int = PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE


# =============================================================================
# AI STATE FIELDS
# =============================================================================

## Current AI state (0=IDLE, 1=CHASE, 2=ATTACK, 3=FLEE)
var ai_state: int = 0

## Entity ID of current target (0 = no target)
var target_id: int = 0

## Time remaining on shoot cooldown
var shoot_cooldown: float = 0.0

## Time spent in current attack state
var attack_timer: float = 0.0

## Time since last target evaluation
var retarget_timer: float = 0.0

## Current movement direction (normalized)
var move_direction: Vector2 = Vector2.ZERO

## Random steering offset for natural movement
var steering_offset: Vector2 = Vector2.ZERO

## Time until next steering offset update
var steering_timer: float = 0.0


## Create a new MonsterState
static func create(p_entity_id: int, p_position: Vector2, p_health: int = GameConstants.MONSTER_HEALTH) -> MonsterState:
	var state = MonsterState.new()
	state.entity_id = p_entity_id
	state.position = p_position
	state.health = p_health
	state.max_health = p_health
	state.is_alive = true
	state.spawn_time = 0.0
	state.animation_state = PacketTypes.AnimationState.IDLE
	state.entity_flags = PacketTypes.ENTITY_FLAG_ALIVE | PacketTypes.ENTITY_FLAG_VISIBLE
	return state


## Apply damage to the monster
## Returns true if the monster was killed
func take_damage(amount: int) -> bool:
	if not is_alive:
		return false

	health -= amount

	if health <= 0:
		health = 0
		is_alive = false
		entity_flags &= ~PacketTypes.ENTITY_FLAG_ALIVE
		animation_state = PacketTypes.AnimationState.DEATH
		return true

	# Show hit animation briefly
	animation_state = PacketTypes.AnimationState.HIT
	return false


# =============================================================================
# AI HELPER METHODS
# =============================================================================

## Check if monster can shoot (cooldown expired)
func can_shoot() -> bool:
	return is_alive and shoot_cooldown <= 0.0


## Start shoot cooldown after firing
func start_shoot_cooldown() -> void:
	shoot_cooldown = GameConstants.MONSTER_SHOOT_COOLDOWN


## Update all AI timers (called each tick)
func update_timers(delta: float) -> void:
	if shoot_cooldown > 0.0:
		shoot_cooldown = maxf(0.0, shoot_cooldown - delta)
	if attack_timer > 0.0:
		attack_timer = maxf(0.0, attack_timer - delta)
	retarget_timer += delta
	steering_timer -= delta


## Convert to entity data dictionary for StateUpdatePacket
func to_entity_data() -> Dictionary:
	return {
		"id": entity_id,
		"type": PacketTypes.EntityType.MONSTER,
		"position": position,
		"animation": animation_state,
		"flags": entity_flags
	}


## Convert to dictionary for debugging
func to_dict() -> Dictionary:
	return {
		"entity_id": entity_id,
		"position": position,
		"health": health,
		"max_health": max_health,
		"is_alive": is_alive,
		"spawn_time": spawn_time,
		"animation_state": animation_state,
		"entity_flags": entity_flags,
		"ai_state": ai_state,
		"target_id": target_id,
		"shoot_cooldown": shoot_cooldown
	}
