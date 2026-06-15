## DeathScreen - death overlay with killer info.
## Softcore: manual respawn countdown ("Press Space to respawn").
## Hardcore (permadeath): the server has already converted XP→Glory and deleted the
## character, so instead of a countdown we show "Your Glory will be remembered" and a
## "Back to Main Menu" button (no respawn).
##
## Authored as scenes/ui/hud/death_screen.tscn (full-rect overlay; title/killer/countdown/
## glory labels + a centered menu button).
extends Control

signal respawn_requested
signal main_menu_requested

var _countdown_timer: float = 0.0
var _countdown_active: bool = false
var _respawn_ready: bool = false

@onready var _killer_label: Label = $Center/VBox/KillerLabel
@onready var _countdown_label: Label = $Center/VBox/CountdownLabel
@onready var _glory_label: Label = $Center/VBox/GloryLabel
@onready var _menu_button: Button = $Center/VBox/ButtonHolder/MenuButton


func _ready() -> void:
	visible = false
	# Consume mouse events when visible
	mouse_filter = Control.MOUSE_FILTER_STOP
	set_process(false)
	_menu_button.pressed.connect(_on_menu_button_pressed)


func _process(delta: float) -> void:
	if not _countdown_active:
		return
	_countdown_timer -= delta
	if _countdown_timer <= 0.0:
		_countdown_active = false
		_respawn_ready = true
		_countdown_label.text = "Press Space to respawn"
		_countdown_label.modulate.a = 1.0
		set_process(false)
	else:
		var secs := ceili(_countdown_timer)
		_countdown_label.text = "Respawn in %d..." % secs
		# Pulse effect
		var pulse: float = 0.7 + 0.3 * absf(sin(Time.get_ticks_msec() / 200.0))
		_countdown_label.modulate.a = pulse


func _unhandled_input(event: InputEvent) -> void:
	if not visible or not _respawn_ready:
		return

	if event is InputEventKey \
			and event.pressed \
			and not event.echo \
			and event.physical_keycode == KEY_SPACE:
		_respawn_ready = false
		_countdown_label.text = "Respawning..."
		get_viewport().set_input_as_handled()
		respawn_requested.emit()


## Show death screen with killer information (softcore: respawn countdown).
func show_death(killer_entity_id: int) -> void:
	_set_killer_text(killer_entity_id)

	# Softcore widgets only.
	_glory_label.visible = false
	_menu_button.visible = false
	_countdown_label.visible = true

	# Start countdown
	_countdown_timer = GameConstants.RESPAWN_DELAY
	_countdown_active = true
	_respawn_ready = false
	_countdown_label.text = "Respawn in %d..." % ceili(_countdown_timer)
	_countdown_label.modulate.a = 1.0
	visible = true
	set_process(true)


## Show the hardcore permadeath screen: no respawn — the character is gone and its XP
## has already been converted to Glory server-side. Offers a single route back to the menu.
func show_death_hardcore(killer_entity_id: int) -> void:
	_set_killer_text(killer_entity_id)

	# No countdown / respawn for permadeath.
	_countdown_active = false
	_respawn_ready = false
	set_process(false)
	_countdown_label.visible = false

	_glory_label.visible = true
	_menu_button.visible = true
	_menu_button.grab_focus()
	visible = true


## Resolve the "Killed by ..." line from the killer entity id.
func _set_killer_text(killer_entity_id: int) -> void:
	if killer_entity_id >= GameConstants.MONSTER_ENTITY_ID_START:
		_killer_label.text = "Killed by Monster"
	elif killer_entity_id > 0:
		var killer_name := EntityNameCache.get_entity_name(killer_entity_id)
		_killer_label.text = "Killed by %s" % killer_name
	else:
		_killer_label.text = ""


func _on_menu_button_pressed() -> void:
	_menu_button.disabled = true
	main_menu_requested.emit()


## Hide death screen.
func hide_death() -> void:
	_countdown_active = false
	_respawn_ready = false
	_countdown_timer = 0.0
	set_process(false)
	if _countdown_label:
		_countdown_label.text = ""
		_countdown_label.modulate.a = 1.0
		_countdown_label.visible = true
	if _glory_label:
		_glory_label.visible = false
	if _menu_button:
		_menu_button.visible = false
		_menu_button.disabled = false
	visible = false
