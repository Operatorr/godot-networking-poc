## Test launches must suppress fullscreen before their scene becomes ready.
## Run headless first; --windowed provides an additional guard for native checks.
extends Node

var _failed: bool = false


func _ready() -> void:
	_check(GameManager._force_windowed_for_run, "Window override must be set during autoload startup")
	if _failed:
		get_tree().quit(1)
		return
	_check_windowed()
	var saved_settings := GameManager.settings.duplicate(true)
	var settings_path := "user://settings.json"
	var had_file := FileAccess.file_exists(settings_path)
	var saved_bytes := FileAccess.get_file_as_bytes(settings_path) if had_file else PackedByteArray()
	# Reapplying the loaded preference must not initiate a native fullscreen Space.
	GameManager._apply_window_mode("windowed_fullscreen")
	for frame in 12:
		_check_windowed()
		await get_tree().process_frame
	_check(GameManager.settings == saved_settings, "Launch override must not change game preferences")
	_check(FileAccess.file_exists(settings_path) == had_file, "Launch override must not create settings")
	if had_file:
		_check(FileAccess.get_file_as_bytes(settings_path) == saved_bytes, "Launch override must not write settings")
	_check(GameManager._is_test_scene_path("res://scenes/test/window_mode_regression.tscn"), "Resource test path")
	_check(GameManager._is_test_scene_path("scenes/test/window_mode_regression.tscn"), "Relative test path")
	_check(GameManager._is_test_scene_path(ProjectSettings.globalize_path("res://scenes/test/window_mode_regression.tscn")), "Absolute test path")
	_check(not GameManager._is_test_scene_path("res://scenes/boot_scene.tscn"), "Normal game launch must keep its preference")
	print("[WindowModeRegression] %s" % ("FAIL" if _failed else "PASS"))
	get_tree().quit(1 if _failed else 0)


func _check_windowed() -> void:
	if DisplayServer.get_name() != "headless":
		_check(DisplayServer.window_get_mode() == DisplayServer.WINDOW_MODE_WINDOWED, "Test must remain windowed")


func _check(ok: bool, message: String) -> void:
	if not ok:
		_failed = true
		push_error(message)
