## DebugOverlay - Toggleable debug HUD for player information
## Shows HP, position, state, and velocity
class_name DebugOverlay
extends CanvasLayer

## Reference to the player being debugged
var target_player: Node2D = null

## Label for displaying debug info
@onready var label: Label = $Label


func _ready() -> void:
	# Start hidden
	visible = false

	# Try to find parent player if not set
	if target_player == null:
		var parent := get_parent()
		if parent is CharacterBody2D:
			target_player = parent


func _input(event: InputEvent) -> void:
	if event.is_action_pressed("toggle_debug"):
		visible = not visible


func _process(_delta: float) -> void:
	if not visible or target_player == null or label == null:
		return

	_update_label()


func _update_label() -> void:
	var hp_text := "N/A"
	var state_text := "N/A"

	# Get HP info if available
	if target_player.has_method("get_state"):
		var state: Dictionary = target_player.get_state()
		hp_text = "%d/%d" % [state.get("hp", 0), state.get("max_hp", 100)]

	# Get state name if available
	if target_player.has_method("get_state_name"):
		state_text = target_player.get_state_name()

	label.text = """[DEBUG - F3 to toggle]
HP: %s
Position: %s
State: %s
Velocity: %s
Rotation: %.2f rad""" % [
		hp_text,
		str(target_player.global_position.round()),
		state_text,
		str(target_player.velocity.round()) if target_player is CharacterBody2D else "N/A",
		target_player.rotation
	]
