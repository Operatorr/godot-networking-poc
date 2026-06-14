## Sandbox - offline test playground. A thin OfflineArena subclass.
## The base owns player/camera/HUD/audio/pause/leave and projectile->enemy hits;
## this adds the debug key panel (1-7), the death overlay, and spawning a real
## client-AI Toxic Slime (OfflineMonster) that chases, kites and shoots you.
## Fully client-authoritative — no NetworkManager or server.
extends OfflineArena

const KILL_FEED_PATH := "res://scripts/ui/hud/kill_feed.gd"
const MINIMAP_PATH := "res://scripts/ui/hud/minimap.gd"
const LEADERBOARD_PATH := "res://scripts/ui/hud/leaderboard.gd"
const OFFLINE_MONSTER_SCENE := "res://scenes/shared/monster/offline_monster.tscn"

const TOXIC_SLIME_SPAWN_DISTANCE := 280.0

var kill_feed: Control = null
var minimap: Control = null
var leaderboard: Control = null
var death_overlay: Control = null
var controls_label: Label = null
var spawn_slime_button: Button = null

var enemies: Array[OfflineMonster] = []
var _invulnerable: bool = false

var _fake_names: Array[String] = [
	"Zephyr", "NovaBlade", "IronFist", "ShadowKing", "PixelWolf",
	"StormRider", "CrystalMage", "DarkPhoenix", "ThunderBolt", "FrostByte"
]


func _configure() -> void:
	arena_rect = Rect2(GameConstants.MAP_MIN, GameConstants.MAP_MAX - GameConstants.MAP_MIN)
	wall_thickness = 10.0
	grid_cell_size = 64.0
	floor_color = Color(0.12, 0.12, 0.15, 1.0)
	grid_color = Color(0.18, 0.18, 0.22, 1.0)
	border_color = Color(0.4, 0.15, 0.15, 1.0)
	border_width = 4.0


func _populate() -> void:
	_setup_extra_hud()
	_setup_test_overlay()
	_seed_leaderboard()

	# Show the death overlay no matter how the player dies (slime, instant-kill...).
	if local_player and local_player.hp_component:
		local_player.hp_component.died.connect(_show_death)

	print("[Sandbox] Ready - press 1-7 for test actions, Esc for pause")


func _process_extra(_delta: float) -> void:
	if _invulnerable and local_player and is_instance_valid(local_player) and local_player.animated_sprite:
		local_player.animated_sprite.modulate.a = 0.5 + 0.5 * sin(Time.get_ticks_msec() / 100.0)
	_update_controls_label()


func _unhandled_input(event: InputEvent) -> void:
	# Base handles exit_to_menu (T); the pause menu handles Esc.
	super._unhandled_input(event)

	if not event is InputEventKey or not event.pressed or event.echo:
		return

	match event.physical_keycode:
		KEY_1:
			_test_damage()
		KEY_2:
			_test_heal()
		KEY_3:
			_respawn_player()
		KEY_4:
			_test_teleport()
		KEY_5:
			_test_toggle_invulnerability()
		KEY_6:
			_test_kill_feed()
		KEY_7:
			_test_instant_kill()


# =============================================================================
# EXTRA HUD
# =============================================================================

func _setup_extra_hud() -> void:
	kill_feed = _create_hud_component(KILL_FEED_PATH, "KillFeed")
	hud_layer.add_child(kill_feed)

	minimap = _create_hud_component(MINIMAP_PATH, "Minimap")
	hud_layer.add_child(minimap)
	minimap.interpolation_controller = null
	minimap.local_player = local_player

	leaderboard = _create_hud_component(LEADERBOARD_PATH, "Leaderboard")
	hud_layer.add_child(leaderboard)

	_build_death_overlay()


func _build_death_overlay() -> void:
	death_overlay = Control.new()
	death_overlay.name = "SandboxDeathScreen"
	death_overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	death_overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	death_overlay.visible = false

	var bg := ColorRect.new()
	bg.color = Color(0.08, 0.0, 0.0, 0.85)
	bg.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	death_overlay.add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	death_overlay.add_child(center)

	var vbox := VBoxContainer.new()
	vbox.alignment = BoxContainer.ALIGNMENT_CENTER
	vbox.add_theme_constant_override("separation", 20)
	center.add_child(vbox)

	var title := Label.new()
	title.text = "YOU DIED"
	title.add_theme_font_size_override("font_size", 64)
	title.add_theme_color_override("font_color", Color(1.0, 0.0, 0.0))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "(Sandbox Mode)"
	subtitle.add_theme_font_size_override("font_size", 20)
	subtitle.add_theme_color_override("font_color", Color(0.6, 0.6, 0.6))
	subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(subtitle)

	var spacer := Control.new()
	spacer.custom_minimum_size = Vector2(0, 20)
	vbox.add_child(spacer)

	var respawn_btn := Button.new()
	respawn_btn.text = "RESPAWN"
	respawn_btn.custom_minimum_size = Vector2(200, 50)
	respawn_btn.add_theme_font_size_override("font_size", 24)
	respawn_btn.pressed.connect(_respawn_player)
	vbox.add_child(respawn_btn)

	var hint := Label.new()
	hint.text = "or press 3"
	hint.add_theme_font_size_override("font_size", 14)
	hint.add_theme_color_override("font_color", Color(0.5, 0.5, 0.5))
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	vbox.add_child(hint)

	hud_layer.add_child(death_overlay)


func _setup_test_overlay() -> void:
	var overlay := CanvasLayer.new()
	overlay.name = "TestOverlay"
	overlay.layer = 10
	add_child(overlay)

	controls_label = Label.new()
	controls_label.name = "ControlsLabel"
	controls_label.add_theme_font_size_override("font_size", 13)
	controls_label.add_theme_color_override("font_color", Color(0.7, 0.7, 0.7, 0.8))
	controls_label.anchor_left = 0.0
	controls_label.anchor_top = 1.0
	controls_label.anchor_right = 0.0
	controls_label.anchor_bottom = 1.0
	controls_label.offset_left = 10
	controls_label.offset_top = -220
	controls_label.offset_right = 380
	controls_label.offset_bottom = -10
	controls_label.vertical_alignment = VERTICAL_ALIGNMENT_BOTTOM
	overlay.add_child(controls_label)

	spawn_slime_button = Button.new()
	spawn_slime_button.name = "SpawnToxicSlimeButton"
	spawn_slime_button.text = "Spawn Toxic Slime"
	spawn_slime_button.custom_minimum_size = Vector2(220, 44)
	spawn_slime_button.anchor_left = 1.0
	spawn_slime_button.anchor_top = 1.0
	spawn_slime_button.anchor_right = 1.0
	spawn_slime_button.anchor_bottom = 1.0
	spawn_slime_button.offset_left = -244
	spawn_slime_button.offset_top = -64
	spawn_slime_button.offset_right = -24
	spawn_slime_button.offset_bottom = -20
	spawn_slime_button.pressed.connect(_spawn_toxic_slime)
	overlay.add_child(spawn_slime_button)

	_update_controls_label()


func _seed_leaderboard() -> void:
	if leaderboard == null:
		return

	var entries: Array = []
	for i in range(5):
		entries.append({
			"entity_id": i + 1,
			"pvp_kills": (5 - i) * 3 + randi() % 5
		})
		EntityNameCache.set_entity_name(i + 1, _fake_names[i])

	leaderboard.update_entries(entries)


# =============================================================================
# DEBUG ACTIONS
# =============================================================================

func _test_damage() -> void:
	if local_player and is_instance_valid(local_player) and not local_player.is_dead:
		local_player.take_damage(25)
		print("[Sandbox] Took 25 damage -> HP: %d" % local_player.hp_component.current_hp)


func _test_heal() -> void:
	if local_player and is_instance_valid(local_player) and not local_player.is_dead:
		local_player.heal(25)
		print("[Sandbox] Healed 25 -> HP: %d" % local_player.hp_component.current_hp)


func _respawn_player() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return

	local_player.reset()
	local_player.position = arena_rect.get_center()
	_invulnerable = false
	local_player.invulnerable = false
	if local_player.animated_sprite:
		local_player.animated_sprite.modulate.a = 1.0
	if camera:
		camera.position = local_player.position
		camera.reset_physics_interpolation()

	if death_overlay:
		death_overlay.visible = false

	print("[Sandbox] Respawned at %s" % local_player.position)


func _test_teleport() -> void:
	if local_player == null or not is_instance_valid(local_player):
		return

	# Blink to the mouse cursor, clamped inside the room.
	var radius := GameConstants.PLAYER_HITBOX_RADIUS
	var target := local_player.get_global_mouse_position()
	target.x = clampf(target.x, arena_rect.position.x + radius, arena_rect.position.x + arena_rect.size.x - radius)
	target.y = clampf(target.y, arena_rect.position.y + radius, arena_rect.position.y + arena_rect.size.y - radius)
	local_player.position = target

	if camera:
		camera.position = local_player.position
		camera.reset_physics_interpolation()
	print("[Sandbox] Teleported to cursor %s" % local_player.position)


func _test_toggle_invulnerability() -> void:
	_invulnerable = not _invulnerable
	if local_player and is_instance_valid(local_player):
		local_player.invulnerable = _invulnerable
		if not _invulnerable and local_player.animated_sprite:
			local_player.animated_sprite.modulate.a = 1.0
	print("[Sandbox] Invulnerability: %s" % ("ON" if _invulnerable else "OFF"))


func _test_kill_feed() -> void:
	if kill_feed:
		var killer := _fake_names[randi() % _fake_names.size()]
		var victim := _fake_names[randi() % _fake_names.size()]
		while victim == killer:
			victim = _fake_names[randi() % _fake_names.size()]
		kill_feed.add_kill(killer, victim)
		print("[Sandbox] Kill feed: %s eliminated %s" % [killer, victim])


func _test_instant_kill() -> void:
	if local_player and is_instance_valid(local_player) and not local_player.is_dead:
		# Bypass invulnerability for the explicit instant-kill tool.
		var was_invulnerable := local_player.invulnerable
		local_player.invulnerable = false
		local_player.take_damage(local_player.hp_component.current_hp)
		local_player.invulnerable = was_invulnerable
		print("[Sandbox] Instant kill")


# =============================================================================
# ENEMY SPAWNING
# =============================================================================

func _spawn_toxic_slime() -> void:
	var slime_scene := load(OFFLINE_MONSTER_SCENE)
	if slime_scene == null:
		push_error("[Sandbox] Failed to load OfflineMonster scene")
		return

	var slime := slime_scene.instantiate() as OfflineMonster
	if slime == null:
		push_error("[Sandbox] Failed to instantiate OfflineMonster")
		return

	slime.definition_id = "toxic_slime"
	slime.name = "ToxicSlime%d" % enemies.size()
	slime.position = _get_slime_spawn_position()
	slime.target = local_player
	slime.killed.connect(_on_slime_killed)
	add_child(slime)
	enemies.append(slime)
	print("[Sandbox] Toxic slime spawned at %s" % slime.position)


func _get_slime_spawn_position() -> Vector2:
	var base_position := Vector2.ZERO
	if local_player and is_instance_valid(local_player):
		base_position = local_player.position

	var angle := randf() * TAU
	var offset := Vector2(cos(angle), sin(angle)) * TOXIC_SLIME_SPAWN_DISTANCE
	var target := base_position + offset
	var margin := GameConstants.MONSTER_HITBOX_RADIUS + wall_thickness
	return Vector2(
		clampf(target.x, arena_rect.position.x + margin, arena_rect.position.x + arena_rect.size.x - margin),
		clampf(target.y, arena_rect.position.y + margin, arena_rect.position.y + arena_rect.size.y - margin)
	)


func _on_slime_killed(slime: OfflineMonster) -> void:
	enemies.erase(slime)
	if kill_feed:
		kill_feed.add_kill(GameManager.player_data.get("character_name", "You"), "Toxic Slime")


func _show_death() -> void:
	if death_overlay:
		death_overlay.visible = true


func _update_controls_label() -> void:
	if controls_label == null:
		return

	var hp_str := "--"
	var state_str := "--"
	if local_player and is_instance_valid(local_player):
		hp_str = "%d/%d" % [
			local_player.hp_component.current_hp if local_player.hp_component else 0,
			local_player.hp_component.max_hp if local_player.hp_component else 0
		]
		state_str = local_player.get_state_name()

	controls_label.text = "SANDBOX MODE\nHP: %s  State: %s  Invuln: %s\n---\n1 - Damage (25)        5 - Toggle Invuln\n2 - Heal (25)          6 - Kill Feed Test\n3 - Respawn            7 - Instant Kill\n4 - Teleport to cursor  Esc - Pause" % [hp_str, state_str, "ON" if _invulnerable else "OFF"]
