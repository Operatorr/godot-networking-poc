## HPComponent - Health tracking component for entities
## Attached as child node to Player
class_name HPComponent
extends Node

## Emitted when HP changes
signal hp_changed(new_hp: int, max_hp: int)

## Emitted when HP reaches zero
signal died()

## Maximum health points
@export var max_hp: int = 100

## Current health points
var current_hp: int = 100

## Whether entity is dead (prevents further damage)
var is_dead: bool = false


func _ready() -> void:
	current_hp = max_hp


## Apply damage to the entity
## @param amount: Damage to apply (positive integer)
func take_damage(amount: int) -> void:
	if is_dead:
		return

	current_hp = maxi(0, current_hp - amount)
	hp_changed.emit(current_hp, max_hp)

	if current_hp <= 0:
		is_dead = true
		died.emit()


## Restore HP, clamped to max_hp
## @param amount: HP to restore (positive integer)
func heal(amount: int) -> void:
	if is_dead:
		return

	current_hp = mini(max_hp, current_hp + amount)
	hp_changed.emit(current_hp, max_hp)


## Set the HP cap (class+level scaling). Clamps current HP to the new cap, or tops it to full when
## `fill` is set (spawn / level-up). Display mirror — the server owns the authoritative HP.
func set_max_hp(new_max: int, fill: bool = false) -> void:
	max_hp = maxi(1, new_max)
	current_hp = max_hp if fill else mini(current_hp, max_hp)
	if current_hp > 0:
		is_dead = false
	hp_changed.emit(current_hp, max_hp)


## Reset to full HP and clear is_dead flag
func reset() -> void:
	is_dead = false
	current_hp = max_hp
	hp_changed.emit(current_hp, max_hp)


## Set HP directly (for server reconciliation)
## Auto-corrects invalid values per NFR-005
## @param hp: New HP value
func set_hp(hp: int) -> void:
	var clamped_hp := clampi(hp, 0, max_hp)

	if clamped_hp != hp:
		push_warning("HPComponent: Invalid HP value %d auto-corrected to %d" % [hp, clamped_hp])

	current_hp = clamped_hp

	if current_hp <= 0 and not is_dead:
		is_dead = true
		died.emit()
	elif current_hp > 0 and is_dead:
		is_dead = false

	hp_changed.emit(current_hp, max_hp)
