## ServerMain - Main server scene node
## Coordinates server-side game logic and manages game state
extends Node

## Server state
var server_running: bool = false
var connected_clients: Dictionary = {}
var tick_rate: int = 30  # 30 ticks per second
var tick_timer: float = 0.0

## Called when the node enters the scene tree
func _ready() -> void:
	print("[ServerMain] Server scene loaded")
	print("[ServerMain] Tick rate: %d Hz" % tick_rate)

	# Verify we're running as server
	if not (OS.has_feature("dedicated_server") or DisplayServer.get_name() == "headless"):
		push_warning("[ServerMain] Not running as dedicated server!")

	server_running = true
	set_process(true)

## Process loop - server tick
func _process(delta: float) -> void:
	if not server_running:
		return

	# Fixed tick rate processing
	tick_timer += delta
	var tick_interval = 1.0 / tick_rate

	while tick_timer >= tick_interval:
		tick_timer -= tick_interval
		_process_server_tick()

## Process a single server tick
func _process_server_tick() -> void:
	# Server game logic will be implemented here:
	# - Update player positions
	# - Process attacks and collisions
	# - Update monster AI
	# - Broadcast state to clients
	pass

## Called when scene is exited
func _exit_tree() -> void:
	server_running = false
	print("[ServerMain] Server scene unloaded")
