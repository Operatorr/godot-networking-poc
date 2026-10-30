## Real scene rendering and focus smoke. No server or account required.
## godot --windowed --path client res://scenes/test/ui_theme_regression.tscn -- --capture=/tmp/omega-ui
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
	_check_material_apertures()
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
	_check_hud_spacing(hud)
	_check(hud.minimap.get_node("MapContent").clip_contents, "Minimap aperture must clip terrain")
	await _check_kill_feed(hud.get_node("KillFeed"))
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
	_check_hud_spacing(hud)
	get_window().size = Vector2i(390, 844)
	await _capture("hud-390")
	_check_hud_spacing(hud)
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
	_check_training_layout(main)
	get_window().size = Vector2i(390, 844)
	await _capture("main-390")
	_check_in_view(main.get_node("CenterContainer/Panel"))
	_check_training_layout(main)
	# Keep this fixture offline while exercising the moved buttons' real hit areas.
	var training_requests: Array[int] = [0, 0]
	main.practice_button.pressed.disconnect(main._on_practice_pressed)
	main.offline_sandbox_button.pressed.disconnect(main._on_offline_sandbox_pressed)
	main.practice_button.pressed.connect(func() -> void: training_requests[0] += 1)
	main.offline_sandbox_button.pressed.connect(func() -> void: training_requests[1] += 1)
	await _click(main.practice_button)
	await _click(main.offline_sandbox_button)
	_check(training_requests == [1, 1], "Both detached training actions must receive clicks: %s" % [training_requests])
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
	await _check_account_menus()
	await _check_death_panel()
	print("[UIThemeRegression] %s" % ("FAIL" if _failed else "PASS"))
	get_tree().quit(1 if _failed else 0)


func _check_material_apertures() -> void:
	var skin: Theme = load("res://themes/grimdark.tres")
	for control_type in ["Button", "OptionButton", "PrimaryButton", "DeathButton"]:
		var button: Button = OptionButton.new() if control_type == "OptionButton" else Button.new()
		button.theme = skin
		button.theme_type_variation = control_type
		add_child(button)
		for state in ["normal", "hover", "pressed", "disabled"]:
			# Resolve inherited states through a real Control, as the game does.
			var style := button.get_theme_stylebox(state) as LayeredUIStyle
			_check(style != null, "%s/%s must retain its material layer" % [control_type, state])
			if style == null:
				continue
			var pixels := style.frame.texture.get_image()
			_check(pixels.get_pixelv(pixels.get_size() / 2).a < 0.01, "Vector center must not obscure the material")
			_check(style.surface != null, "Every button state needs a material")
		button.free()


func _check_death_panel() -> void:
	var death: Control = load("res://scenes/ui/hud/death_screen.tscn").instantiate()
	add_child(death)
	_check(death.get_node("Center/Panel") is MarginContainer, "Death content must have padding without a panel background or frame")
	var requests: Array[int] = [0]
	death.main_menu_requested.connect(func() -> void: requests[0] += 1)
	for width in [1280, 390]:
		get_window().size = Vector2i(width, 720 if width == 1280 else 844)
		death.show_death_hardcore(0, 1250)
		await _settle()
		_check_in_view(death.get_node("Center/Panel"))
		var button: Button = death.get_node("Center/Panel/VBox/ButtonHolder/MenuButton")
		_check(button.has_focus(), "Hardcore death must focus its menu action")
		await _click(button)
		_check(button.disabled, "Death action must accept transformed pointer input once")
		death.hide_death()
	_check(requests[0] == 2, "Each death action must emit one menu request")
	death.queue_free()
	await get_tree().process_frame


func _check_hud_spacing(hud: GameHud) -> void:
	var slots := hud.ability_bar.get_global_rect()
	# Exclude the key badges below the square action slots from the centerline.
	slots.size.y = AbilityBar.SLOT_SIZE
	var health := hud.health_bar.get_global_rect()
	var mana := hud.mana_bar.get_global_rect()
	var energy := hud.stamina_bar.get_global_rect()
	var gap := AbilityBar.SLOT_GAP
	_check(is_equal_approx(slots.position.x - health.end.x, gap), "HP/action gap must match slot spacing")
	_check(is_equal_approx(mana.position.x - slots.end.x, gap), "Mana/action gap must match slot spacing")
	_check(is_equal_approx(slots.position.y - energy.end.y, gap), "Energy/action gap must match slot spacing")
	_check(is_equal_approx(health.get_center().y, slots.get_center().y), "HP must share the action-slot centerline")
	_check(is_equal_approx(mana.get_center().y, slots.get_center().y), "Mana must share the action-slot centerline")


func _check_kill_feed(feed: Control) -> void:
	feed.set_process(false)
	for i in 4:
		feed.add_kill("LongCombatantName", "[b]LiteralName[/b]")
	await _settle()
	_check(feed._messages.size() == 3, "Kill feed must remain bounded to three notifications")
	_check(feed.get_node("VBox").get_child_count() == 3, "Replaced notification must leave the layout")
	for message: Dictionary in feed._messages:
		var row: Control = message.row
		_check(row.size.x <= feed.size.x, "Long kill names must wrap within the minimap width")
		var label: RichTextLabel = row.find_children("*", "RichTextLabel", true, false)[0]
		_check(label.get_parsed_text() == "LongCombatantName eliminated [b]LiteralName[/b]", "Kill names must remain literal text")
		message.timestamp = -10.0
	feed._process(0.0)
	await _settle()
	_check(feed._messages.is_empty() and feed.get_node("VBox").get_child_count() == 0, "Expired notifications must remove the complete framed row")


func _check_account_menus() -> void:
	for scene_name in ["login_screen", "character_creation"]:
		var menu: Control = load("res://scenes/ui/menus/" + scene_name + ".tscn").instantiate()
		if scene_name == "login_screen":
			menu.prefill_test_credentials_from_env = false
		add_child(menu)
		await _capture(scene_name + "-1280")
		var panel: Control = menu.get_node("CenterContainer/Panel")
		_check_in_view(panel)
		if scene_name == "login_screen":
			_check(menu.username_input.has_focus(), "Login must initially focus username")
			_check(menu.password_input.secret, "Login must mask the password")
			await _press_tab()
			_check(menu.password_input.has_focus(), "Tab must move username to password")
		else:
			_check(menu.name_input.has_focus(), "Character creation must initially focus name")
			_check_input_border(menu.name_input)
			_check(menu.create_button.disabled, "An empty character name must disable creation")
			await _press_tab()
			_check(menu._class_buttons[menu._selected_class].has_focus(), "Tab must reach class choices before Create")
			menu.name_input.text = "AshenWarden"
			menu._on_name_text_changed("AshenWarden")
			_check(not menu.create_button.disabled, "A valid name must enable creation")
			menu._on_name_text_changed("invalid name!")
			_check(menu.create_button.disabled, "Invalid characters must disable creation")
			await _click(menu._class_buttons[PacketTypes.PlayerClass.ROGUE])
			_check(menu._selected_class == PacketTypes.PlayerClass.ROGUE, "Scaled class choices must receive clicks")
			await _click(menu._mode_buttons[1])
			_check(menu._selected_mode == "hardcore", "Scaled mode choices must receive clicks")
		if scene_name == "character_creation":
			menu.name_input.grab_focus()
		await _capture(scene_name + "-390")
		if scene_name == "character_creation":
			_check_input_border(menu.name_input)
		_check_in_view(panel)
		if scene_name == "character_creation":
			await _click(menu._mode_buttons[0])
			_check(menu._selected_mode == "softcore", "Narrow mode choices must receive clicks")
		menu.queue_free()
		await get_tree().process_frame


func _check_training_layout(menu: Control) -> void:
	var footer: Control = menu.get_node("TrainingActions")
	var panel: Control = menu.get_node("CenterContainer/Panel")
	_check(footer.get_parent() == menu, "Training actions belong to the screen, outside the card")
	_check_in_view(footer)
	var footer_rect := footer.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, footer.size)
	var panel_rect := panel.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, panel.size)
	_check(not footer_rect.intersects(panel_rect), "Training actions must not overlap the main card")
	var left_gap := footer_rect.position.x
	var bottom_gap := get_viewport().get_visible_rect().size.y - footer_rect.end.y
	_check(is_equal_approx(left_gap, bottom_gap), "Training actions must share equal bottom-left insets")


func _check_input_border(field: LineEdit) -> void:
	if DisplayServer.get_name() == "headless":
		return
	# Check rendered pixels, not just style widths: a fractional transform used to
	# drop the entire one-unit top edge even though its StyleBox width was correct.
	RenderingServer.force_draw()
	var pixels := get_viewport().get_texture().get_image()
	var ratio := Vector2(pixels.get_size()) / get_viewport().get_visible_rect().size
	var bounds := field.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, field.size)
	bounds = Rect2(bounds.position * ratio, bounds.size * ratio)
	for side in [SIDE_LEFT, SIDE_TOP, SIDE_RIGHT, SIDE_BOTTOM]:
		var found := false
		var point := bounds.get_center()
		if side == SIDE_LEFT:
			point.x = bounds.position.x
		elif side == SIDE_RIGHT:
			point.x = bounds.end.x - 1.0
		elif side == SIDE_TOP:
			point.y = bounds.position.y
		else:
			point.y = bounds.end.y - 1.0
		for offset in range(-3, 4):
			var sample := Vector2i(point) + (Vector2i(offset, 0) if side in [SIDE_LEFT, SIDE_RIGHT] else Vector2i(0, offset))
			if Rect2i(Vector2i.ZERO, pixels.get_size()).has_point(sample):
				var color := pixels.get_pixelv(sample)
				found = found or (color.r > 0.65 and color.g > 0.5 and color.b < 0.6)
		_check(found, "Focused character-name border must render on side %d at %s" % [side, pixels.get_size()])


func _press_tab() -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = KEY_TAB
		event.pressed = pressed
		get_viewport().push_input(event, true)
		await get_tree().process_frame


func _settle() -> void:
	for i in 4:
		await get_tree().process_frame


func _capture(name: String) -> void:
	# Pin the physical size for each capture; GameManager keeps tests windowed.
	var expected := Vector2i(1280, 720)
	if name.ends_with("390"):
		expected = Vector2i(390, 844)
	elif name.ends_with("1920"):
		expected = Vector2i(1920, 1080)
	get_window().mode = Window.MODE_WINDOWED
	get_window().size = expected
	await _settle()
	if _capture_dir.is_empty() or DisplayServer.get_name() == "headless":
		return
	# Rendering can lag a native resize. Require both dimensions to agree.
	# Do not pin the window on top or repeatedly steal desktop focus.
	for attempt in 100:
		get_window().mode = Window.MODE_WINDOWED
		get_window().size = expected
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


func _click(button: Button) -> void:
	# Validation text can queue container layout; click its settled hit area.
	await _settle()
	var point := button.get_global_transform_with_canvas() * (button.size * 0.5)
	var motion := InputEventMouseMotion.new()
	motion.position = point
	get_viewport().push_input(motion, true)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		get_viewport().push_input(event, true)
	# Dispatch a complete click before native pointer motion can interrupt it.
	await _settle()


func _check_in_view(control: Control) -> void:
	var bounds := control.get_global_transform_with_canvas() * Rect2(Vector2.ZERO, control.size)
	_check(get_viewport().get_visible_rect().encloses(bounds), "%s extends outside the window: %s" % [control.name, bounds])


func _check(ok: bool, message: String) -> void:
	if not ok:
		_failed = true
		push_error(message)
