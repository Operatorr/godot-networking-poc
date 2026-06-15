## ConnectionLostOverlay - shown when the connection to the server is lost.
##
## Authored as scenes/ui/hud/connection_lost_overlay.tscn (full-rect dark overlay with a
## title + status Label). Displays reconnection status and emits reconnect_failed on timeout.
extends Control

signal reconnect_failed

const RECONNECT_TIMEOUT := 15.0

var _timer: float = 0.0
var _is_active: bool = false

@onready var _status_label: Label = $Center/VBox/StatusLabel


func _ready() -> void:
	visible = false
	mouse_filter = Control.MOUSE_FILTER_STOP
	set_process(false)


func _process(delta: float) -> void:
	if not _is_active:
		return
	_timer += delta
	if _timer >= RECONNECT_TIMEOUT:
		_is_active = false
		set_process(false)
		_status_label.text = "Connection failed. Returning to main menu..."
		reconnect_failed.emit()


## Show the overlay (called when a disconnect is detected).
func show_overlay() -> void:
	_is_active = true
	_timer = 0.0
	_status_label.text = "Attempting to reconnect..."
	visible = true
	set_process(true)


## Hide the overlay (called when reconnected).
func hide_overlay() -> void:
	_is_active = false
	set_process(false)
	visible = false
