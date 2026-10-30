## Real scene rendering and focus smoke. No server or account required.
## godot --path client res://scenes/test/ui_theme_regression.tscn -- --capture=/tmp/omega-ui
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
	await _capture("hud-1280")
	_check(hud.minimap.get_node("MapContent").clip_contents, "Minimap aperture must clip terrain")
	hud.pause_menu.toggle()
	await _capture("pause-1280")
	_check(get_viewport().gui_get_focus_owner() == hud.pause_menu.get_node("Center/Panel/VBox/ResumeButton"), "Pause must focus Resume")
	await _click(hud.pause_menu.get_node("Center/Panel/VBox/SettingsButton"))
	_check(hud.pause_menu.get_node("SettingsMenu").visible, "Scaled Settings button must receive clicks")
	await _capture("settings-ingame-1280")
	var settings: Control = hud.pause_menu.get_node("SettingsMenu")
	settings._show_controls()
	await _capture("keybinds-1280")
	settings.go_back()
	_check(settings.get_node("Panel").visible, "Back must return from keybinds to settings")
	settings.go_back()
	_check(get_viewport().gui_get_focus_owner() == hud.pause_menu.get_node("Center/Panel/VBox/SettingsButton"), "Settings must restore pause focus")
	hud.pause_menu._on_resume_pressed()
	_check(not get_tree().paused, "Online UI must never pause the SceneTree")
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
	hud.queue_free()
	await get_tree().process_frame
	get_window().size = Vector2i(1280, 720)
	var main: Control = load("res://scenes/ui/menus/main_menu.tscn").instantiate()
	GameManager.player_data["character_name"] = "AshenWarden"
	add_child(main)
	await _settle()
	var dropdown: OptionButton = main.get_node("CenterContainer/Panel/VBoxContainer/RegionDropdown")
	dropdown.clear()
	dropdown.add_item("Southeast Asia — The Hollow Gate — Very long realm name")
	dropdown.select(0)
	_check(dropdown.get_theme_constant("arrow_margin") >= 12, "Dropdown caret must be inset")
	_check(dropdown.get_theme_stylebox("normal").content_margin_right >= 36, "Dropdown value must reserve space")
	_check(not dropdown.fit_to_longest_item, "Long region labels must not widen the menu")
	await _capture("main-1280")
	get_window().size = Vector2i(390, 844)
	await _capture("main-390")
	_check_in_view(main.get_node("CenterContainer/Panel"))
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
	print("[UIThemeRegression] %s" % ("FAIL" if _failed else "PASS"))
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
	# Require several stable frames after the OS completes the mode transition.
	# A fullscreen completion event can arrive after our first resize request.
	var stable := 0
	for attempt in 40:
		if get_window().mode != Window.MODE_WINDOWED or get_window().size != expected:
			get_window().mode = Window.MODE_WINDOWED
			get_window().size = expected
			stable = 0
		await get_tree().create_timer(0.1).timeout
		if get_window().mode == Window.MODE_WINDOWED and get_window().size == expected:
			stable += 1
			if stable >= 4:
				break
	await _settle()
	if _capture_dir.is_empty() or DisplayServer.get_name() == "headless":
		return
	await RenderingServer.frame_post_draw
	var pixels := get_viewport().get_texture().get_image()
	_check(pixels.get_size() == expected, "%s capture has unexpected physical size: %s" % [name, pixels.get_size()])
	var result := pixels.save_png(_capture_dir.path_join(name + ".png"))
	_check(result == OK, "Failed to capture " + name)


func _click(button: Button) -> void:
	var point := button.get_global_transform_with_canvas() * (button.size * 0.5)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		get_viewport().push_input(event, true)
		await get_tree().process_frame


func _check_in_view(control: Control) -> void:
	var bounds := control.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, control.size)
	_check(get_viewport().get_visible_rect().encloses(bounds), "%s extends outside the window: %s" % [control.name, bounds])


func _check(ok: bool, message: String) -> void:
	if not ok:
		_failed = true
		push_error(message)
