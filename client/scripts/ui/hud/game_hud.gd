## GameHud - the shared in-game HUD, composed once and reused by every world.
##
## Authored as scenes/ui/hud/game_hud.tscn: a CanvasLayer holding instances of every HUD widget
## (bars, ability bar, XP, minimap, kill feed, leaderboard, server status, and the death / pause /
## connection-lost overlays). Levels instantiate this with a runtime load() inside their
## client-only _setup_hud(), rename the instance to "HUDLayer" (so get_hud_layer() keeps working),
## and talk to the typed widget refs + the four re-emitted signals below — instead of building the
## HUD inline. @export toggles let offline/practice hide the networked-only widgets.
class_name GameHud
extends CanvasLayer

## Renders the level's static terrain once into a texture for the minimap + map overlay (perf:
## no per-frame world render). Loaded at runtime with the rest of the client-only HUD.
const WorldMapViewScene := preload("res://scenes/ui/hud/world_map_view.tscn")

## Networked-only widgets — offline/practice turn these off; bars / XP / minimap / pause stay on.
@export var show_leaderboard: bool = true
@export var show_server_status: bool = true
@export var show_kill_feed: bool = true

## Re-emitted from the overlay widgets so a level connects to the HUD once.
signal respawn_requested
signal main_menu_requested
signal leave_arena_requested
signal reconnect_failed

@onready var health_bar: HealthBar = $HealthBar
@onready var mana_bar: ResourceBar = $ManaBar
@onready var stamina_bar: ResourceBar = $StaminaBar
@onready var ability_bar: AbilityBar = $AbilityBar
@onready var experience_bar: ExperienceBar = $ExperienceBar
@onready var minimap: Minimap = $Minimap
@onready var kill_feed: Control = $KillFeed
@onready var leaderboard: Control = $Leaderboard
@onready var server_status: Control = $ServerStatus
@onready var death_screen: Control = $DeathScreen
@onready var pause_menu: Control = $PauseMenu
@onready var connection_lost_overlay: Control = $ConnectionLostOverlay
@onready var map_overlay: MapOverlay = $MapOverlay

var _world_map: WorldMapView = null


func _ready() -> void:
	leaderboard.visible = show_leaderboard
	server_status.visible = show_server_status
	kill_feed.visible = show_kill_feed

	death_screen.respawn_requested.connect(func() -> void: respawn_requested.emit())
	death_screen.main_menu_requested.connect(func() -> void: main_menu_requested.emit())
	pause_menu.leave_arena_requested.connect(func() -> void: leave_arena_requested.emit())
	connection_lost_overlay.reconnect_failed.connect(func() -> void: reconnect_failed.emit())


## Set the pause menu's Leave button label (contextual per level).
func set_leave_button_text(text: String) -> void:
	if pause_menu:
		pause_menu.set_leave_button_text(text)


## Wire the ability bar to the local movement state machine (dash cooldown).
func bind_movement_state_machine(sm: MovementStateMachine) -> void:
	if ability_bar:
		ability_bar.bind_movement_state_machine(sm)


## Set the local player as the minimap's follow centre + the dot frame-of-reference. Safe with null.
## (The fullscreen MapOverlay frames the whole level by bounds, so it needs no follow target.)
func set_minimap_player(player: Node2D) -> void:
	if minimap != null:
		minimap.local_player = player


## Render the level's static terrain once (framing `bounds`) and hand the texture to the minimap +
## map overlay. Call once per level after the terrain has been built.
func setup_world_map(bounds: Rect2) -> void:
	if _world_map == null:
		_world_map = WorldMapViewScene.instantiate()
		add_child(_world_map)
	_world_map.configure(bounds)
	var tex := _world_map.get_texture()
	if minimap != null:
		minimap.set_world_map(tex, bounds)
	if map_overlay != null:
		map_overlay.set_world_map(tex, bounds)
