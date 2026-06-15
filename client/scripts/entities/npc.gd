## TownNpc - interactable service NPC for the Sanctuary (priest, class trainers,
## vendors, banker). Fully client-local: walking up shows an interact prompt,
## pressing `interact` opens a dialog panel. The actual services (Glory spend,
## class training, shops, bank) are stubs until their systems land - the dialog
## text says so in-fiction. When those systems arrive they go through the Go
## API / game server (the client requests, the server decides); this node will
## only ever be the UI entry point.
class_name TownNpc
extends StaticBody2D

signal interacted(npc: TownNpc)

enum Role { GENERIC, PRIEST, CLASS_TRAINER, VENDOR, BANKER }

@export var npc_name: String = "Villager"
@export var npc_title: String = ""
@export var role: Role = Role.GENERIC
@export_multiline var dialog_text: String = "..."
## Sprite texture; a colored placeholder figure is drawn while missing.
@export var texture_path: String = ""
@export var placeholder_color: Color = Color("b8793a")
## When true, interacting only emits `interacted` and skips the built-in info dialog, so a
## listener (e.g. the Sanctuary priest's sacrifice flow) can present its own UI instead.
@export var suppress_default_dialog: bool = false

var _player_inside := false
var _dialog_layer: CanvasLayer = null

@onready var _sprite: Sprite2D = $Sprite2D
@onready var _name_label: Label = $NameLabel
@onready var _prompt_label: Label = $PromptLabel
@onready var _interact_area: Area2D = $InteractArea


func _ready() -> void:
	add_to_group("minimap_npc")  # green dot on the minimap
	_name_label.text = npc_name
	_prompt_label.visible = false
	_interact_area.body_entered.connect(_on_body_entered)
	_interact_area.body_exited.connect(_on_body_exited)

	if not texture_path.is_empty() and ResourceLoader.exists(texture_path):
		_sprite.texture = load(texture_path)
		# Character canvases pad below the feet; lift so feet sit on position.
		_sprite.offset = Vector2(0.0, -8.0)
	else:
		queue_redraw()


func _draw() -> void:
	if _sprite and _sprite.texture:
		return
	# Placeholder figure: body + head, tinted per NPC.
	draw_circle(Vector2(0.0, 2.0), 12.0, placeholder_color)
	draw_circle(Vector2(0.0, -12.0), 7.0, placeholder_color.lightened(0.35))
	draw_arc(Vector2(0.0, 2.0), 12.0, 0.0, TAU, 24, Color(0.15, 0.12, 0.1, 0.8), 1.5)


func _unhandled_input(event: InputEvent) -> void:
	if not event.is_action_pressed("interact"):
		if _dialog_layer and event.is_action_pressed("ui_cancel"):
			get_viewport().set_input_as_handled()
			_close_dialog()
		return
	if _dialog_layer:
		get_viewport().set_input_as_handled()
		_close_dialog()
	elif _player_inside:
		get_viewport().set_input_as_handled()
		_open_dialog()


func _on_body_entered(body: Node2D) -> void:
	if body is Player:
		_player_inside = true
		_prompt_label.text = "Press %s to talk" % _interact_key_name()
		_prompt_label.visible = true


func _on_body_exited(body: Node2D) -> void:
	if body is Player:
		_player_inside = false
		_prompt_label.visible = false
		_close_dialog()


func _open_dialog() -> void:
	if _dialog_layer:
		return
	interacted.emit(self)

	# A listener may handle this interaction entirely (e.g. the priest's sacrifice
	# confirm); in that case skip the built-in info dialog.
	if suppress_default_dialog:
		return

	_dialog_layer = CanvasLayer.new()
	_dialog_layer.name = "NpcDialogLayer"
	_dialog_layer.layer = 64
	add_child(_dialog_layer)

	var panel := PanelContainer.new()
	panel.name = "DialogPanel"
	panel.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM)
	panel.offset_left = -320.0
	panel.offset_right = 320.0
	panel.offset_top = -190.0
	panel.offset_bottom = -50.0
	_dialog_layer.add_child(panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 8)
	panel.add_child(vbox)

	var header := Label.new()
	header.text = npc_name if npc_title.is_empty() else "%s — %s" % [npc_name, npc_title]
	header.add_theme_font_size_override("font_size", 20)
	header.add_theme_color_override("font_color", Color(1.0, 0.83, 0.42))
	vbox.add_child(header)

	var body_label := Label.new()
	body_label.text = dialog_text
	body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body_label.add_theme_font_size_override("font_size", 15)
	vbox.add_child(body_label)

	var hint := Label.new()
	hint.text = "Press %s to close" % _interact_key_name()
	hint.add_theme_font_size_override("font_size", 12)
	hint.add_theme_color_override("font_color", Color(0.7, 0.7, 0.75))
	vbox.add_child(hint)


func _close_dialog() -> void:
	if _dialog_layer:
		_dialog_layer.queue_free()
		_dialog_layer = null


func _interact_key_name() -> String:
	for event: InputEvent in InputMap.action_get_events("interact"):
		if event is InputEventKey:
			var key: Key = event.physical_keycode if event.physical_keycode != KEY_NONE else event.keycode
			return OS.get_keycode_string(key)
	return "E"
