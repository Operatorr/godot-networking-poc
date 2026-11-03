## Regression coverage for the Sanctuary priest: the production level must build a priest inside
## the Temple whose interaction opens the sacrifice confirm prompt. Cancels only; never confirms,
## so no sacrifice request is sent. Run headless:
##   godot --headless --path client --script scripts/test/sanctuary_priest_test.gd
extends SceneTree

## How long a run may take before a script error that never reaches _finish fails the test.
const WATCHDOG_SECONDS := 120.0

var _failures := 0
var _role: Dictionary


func _initialize() -> void:
	create_timer(WATCHDOG_SECONDS).timeout.connect(_on_watchdog)
	_run.call_deferred()


func _on_watchdog() -> void:
	push_error("[SanctuaryPriestTest] timed out")
	quit(1)


func _run() -> void:
	# Headless ArenaBase runs in server mode: it builds the production town and skips client setup,
	# so the NPCs are built here with the same arguments as Sanctuary._after_client_setup.
	# Loaded here, not preloaded: under --script this file compiles before autoloads register.
	_role = load("res://scripts/entities/npc.gd").Role
	var level = load("res://scripts/levels/sanctuary.gd").new()
	root.add_child(level)
	level._town.build_npcs(level._town, level.NPC_SCENE, level.NPC_TEXTURE_DIR, level._on_npc_interacted)

	var priest = _only_priest(level._town)
	if priest == null:
		_finish()
		return
	_check(priest.npc_name == "Father Aldric", "priest keeps his name")
	_check(level._town.interior_at(priest.global_position) == "temple", "priest stands in the Temple")
	_check(priest.suppress_default_dialog, "priest suppresses the default dialog")
	_check(priest.interacted.is_connected(level._on_npc_interacted), "priest is connected to the listener")

	_press_interact(priest)
	_check(level._sacrifice_confirm != null and level._sacrifice_confirm.visible, "interacting opens the confirm")
	_check(priest._dialog_layer == null, "priest opens no info dialog")

	level._sacrifice_confirm._on_cancel()
	_check(not level._sacrifice_confirm.visible, "cancel closes the confirm")
	_check(not level._sacrifice_in_flight and level._sacrifice_request == null, "cancel sends no sacrifice request")

	_press_interact(priest)
	_check(level._sacrifice_confirm.visible, "the confirm can be reopened after cancelling")
	level._sacrifice_confirm._on_cancel()

	var banker = _first_with_role(level._town, _role.BANKER)
	_check(banker != null and not banker.suppress_default_dialog, "banker keeps the default dialog")

	# The offline preview passes no listener: the priest falls back to his own dialog.
	var preview_town = level.SanctuaryTownWorld.new()
	root.add_child(preview_town)
	preview_town.build()
	preview_town.build_npcs(preview_town, level.NPC_SCENE, level.NPC_TEXTURE_DIR, Callable())
	var preview_priest = _only_priest(preview_town)
	if preview_priest != null:
		_check(not preview_priest.suppress_default_dialog, "priest without a listener keeps his dialog")
		_press_interact(preview_priest)
		_check(preview_priest._dialog_layer != null, "priest without a listener opens his dialog")

	_finish()


func _only_priest(town: Node):
	var priests := _with_role(town, _role.PRIEST)
	_check(priests.size() == 1, "town has exactly one priest (found %d)" % priests.size())
	return priests[0] if priests.size() == 1 else null


func _first_with_role(town: Node, role: int):
	var matches := _with_role(town, role)
	return matches[0] if not matches.is_empty() else null


func _with_role(town: Node, role: int) -> Array:
	return town.get_children().filter(func(child: Node) -> bool:
		return child.get("npc_name") != null and child.role == role)


## Drive the NPC's real input path with the player inside its interact area.
func _press_interact(npc: Node) -> void:
	npc._player_inside = true
	var event := InputEventAction.new()
	event.action = "interact"
	event.pressed = true
	npc._unhandled_input(event)


func _check(condition: bool, label: String) -> void:
	if not condition:
		_failures += 1
		push_error("[SanctuaryPriestTest] FAILED: " + label)


func _finish() -> void:
	if _failures > 0:
		push_error("[SanctuaryPriestTest] %d assertion(s) failed" % _failures)
		quit(1)
	else:
		print("All sanctuary priest tests passed")
		quit(0)
