## Matched PR screenshot fixture, compatible with the pre-redesign UI.
## godot --path client res://scenes/test/ui_review_capture.tscn -- --capture=/tmp/omega-ui
extends Node

var _capture_dir: String = ""
var _failed: bool = false


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--capture="):
			_capture_dir = arg.trim_prefix("--capture=")
	if not _capture_dir.is_empty():
		DirAccess.make_dir_recursive_absolute(_capture_dir)
	# Keep the real MainMenu lifecycle, but make any read requests strictly local.
	AuthManager.api_base_url = "http://127.0.0.1:1"
	AuthManager.jwt_token = ""
	await get_tree().process_frame
	get_window().mode = Window.MODE_WINDOWED
	get_window().size = Vector2i(1280, 720)
	var background := ColorRect.new()
	background.color = Color("171c20")
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var hud: GameHud = load("res://scenes/ui/hud/game_hud.tscn").instantiate()
	add_child(hud)
	hud.health_bar.update_hp(120, 120)
	hud.mana_bar.update_value(100, 100)
	hud.stamina_bar.update_value(100, 100)
	var entries: Array = []
	for i in 5:
		EntityNameCache.set_entity_name(i + 1, ["Kurogane", "Elysia", "Drax", "Mira", "LongCharacterName"][i])
		EntityNameCache.entity_classes[i + 1] = i
		EntityNameCache.entity_levels[i + 1] = 30 - i
		entries.append({"entity_id": i + 1, "pvp_kills": 42 - i * 6, "deaths": i})
	hud.leaderboard.update_entries(entries)
	var player := Node2D.new()
	add_child(player)
	player.add_to_group("minimap_player_local")
	hud.set_minimap_player(player)
	# A deliberately oversized terrain texture catches clipping through frame edges.
	var terrain := GradientTexture2D.new()
	terrain.gradient = Gradient.new()
	terrain.gradient.colors = PackedColorArray([Color("273d3a"), Color("172625")])
	hud.minimap.set_world_map(terrain, Rect2(-2000, -2000, 4000, 4000))
	hud.get_node("KillFeed").add_kill("Kurogane", "Drax")
	hud.get_node("KillFeed").set_process(false)
	await _capture("hud-1280")
	hud.pause_menu.toggle()
	await _capture("pause-1280")
	hud.pause_menu._on_settings_pressed()
	await _capture("settings-ingame-1280")
	var settings: Control = hud.pause_menu.get_node("SettingsMenu")
	settings._show_controls()
	await _capture("keybinds-1280")
	settings._hide_controls()
	settings._on_back_pressed()
	hud.pause_menu._on_resume_pressed()
	hud.health_bar.update_hp(37, 120)
	hud.mana_bar.update_value(24, 100)
	hud.stamina_bar.update_value(0, 100)
	var movement := MovementStateMachine.new()
	movement.ability_cooldown_max = 5.0
	movement.set_predicted_cooldowns(0.8, 3.2)
	hud.bind_movement_state_machine(movement)
	await _capture("hud-partial-1280")
	get_window().size = Vector2i(1920, 1080)
	await _capture("hud-1920")
	get_window().size = Vector2i(390, 844)
	await _capture("hud-390")
	get_window().size = Vector2i(1280, 720)
	hud.get_node("DeathScreen").show_death(1)
	hud.get_node("DeathScreen").set_process(false)
	await _capture("death-softcore-1280")
	hud.get_node("DeathScreen").hide_death()
	hud.get_node("DeathScreen").show_death_hardcore(1, 1250)
	await _capture("death-hardcore-1280")
	hud.get_node("DeathScreen").hide_death()
	hud.get_node("ConnectionLostOverlay").show_overlay()
	hud.get_node("ConnectionLostOverlay").set_process(false)
	await _capture("connection-lost-1280")
	hud.get_node("ConnectionLostOverlay").hide_overlay()
	hud.get_node("MapOverlay").set_world_map(terrain, Rect2(-2000, -2000, 4000, 4000))
	hud.get_node("MapOverlay").set_open(true)
	await _capture("world-map-1280")
	hud.queue_free()
	await get_tree().process_frame
	get_window().size = Vector2i(1280, 720)
	var main: Control = load("res://scenes/ui/menus/main_menu.tscn").instantiate()
	GameManager.player_data["character_name"] = "AshenWarden"
	add_child(main)
	await _settle()
	var dropdown: OptionButton = main.find_child("RegionDropdown", true, false)
	dropdown.clear()
	dropdown.add_item("Southeast Asia — The Hollow Gate — Very long realm name")
	dropdown.select(0)
	await _capture("main-1280")
	get_window().size = Vector2i(390, 844)
	await _capture("main-390")
	main.queue_free()
	await get_tree().process_frame
	get_window().size = Vector2i(1280, 720)
	var standalone: Control = load("res://scenes/ui/menus/settings_screen.tscn").instantiate()
	add_child(standalone)
	await _capture("settings-1280")
	var tabs: TabContainer = standalone.find_children("*", "TabContainer", true, false)[0]
	tabs.current_tab = 1
	await _capture("settings-video-1280")
	tabs.current_tab = 2
	await _capture("settings-controls-1280")
	get_window().size = Vector2i(390, 844)
	await _capture("settings-controls-390")
	standalone.queue_free()
	await get_tree().process_frame
	for scene_name in ["login_screen", "character_creation", "loading_screen"]:
		var menu: Control = load("res://scenes/ui/menus/" + scene_name + ".tscn").instantiate()
		if scene_name == "login_screen":
			menu.prefill_test_credentials_from_env = false
		add_child(menu)
		await _capture(scene_name + "-1280")
		menu.queue_free()
		await get_tree().process_frame
	for scene_name in ["error_dialog", "confirm_dialog"]:
		var dialog: Node = load("res://scenes/ui/dialogs/" + scene_name + ".tscn").instantiate()
		add_child(dialog)
		if scene_name == "error_dialog":
			dialog.show_error("Connection failed", "Unable to connect to the realm. Please try again.", true)
		else:
			dialog.show_confirm("Return to menu", "Leave the current realm and return to the main menu?", "Leave realm", "Stay")
		await _capture(scene_name + "-1280")
		dialog.queue_free()
		await get_tree().process_frame
	print("[UIReviewCapture] %s" % ("FAIL" if _failed else "PASS"))
	get_tree().quit(1 if _failed else 0)


func _settle() -> void:
	for i in 4:
		await get_tree().process_frame


func _capture(name: String) -> void:
	# macOS can finish the launch fullscreen transition asynchronously. Pin each
	# capture's physical size rather than trusting a prior window resize request.
	var expected := Vector2i(1280, 720)
	if name.ends_with("390"):
		expected = Vector2i(390, 844)
	elif name.ends_with("1920"):
		expected = Vector2i(1920, 1080)
	if _capture_dir.is_empty() or DisplayServer.get_name() == "headless":
		return
	# A macOS fullscreen transition can leave the rendered texture one resize
	# behind the native window. Require both dimensions to agree before saving.
	get_window().always_on_top = true
	for attempt in 100:
		get_window().mode = Window.MODE_WINDOWED
		get_window().size = expected
		get_window().grab_focus()
		await get_tree().create_timer(0.1).timeout
		await _settle()
		RenderingServer.force_draw()
		var pixels := get_viewport().get_texture().get_image()
		if get_window().size != expected or pixels.get_size() != expected:
			continue
		var result := pixels.save_png(_capture_dir.path_join(name + ".png"))
		_check(result == OK, "Failed capture: " + name)
		return
	_check(false, "Could not stabilize capture dimensions: " + name)


func _check(ok: bool, message: String) -> void:
	if not ok:
		_failed = true
		push_error(message)
