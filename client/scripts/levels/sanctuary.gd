## Sanctuary — the safe-hub city the player enters when entering the world.
##
## NETWORKED shared instance (ArenaBase subclass): the Sanctuary is a real server instance
## (omega-server --mode sanctuary --port 8082) with no monsters and PvP off (projectiles never hit
## players). Movement is server-authoritative and predicted exactly like the Arena — abilities run
## server-side here too. The Arena portal in the Lower Sanctum disconnects and dials the Arena
## instance (8081) on the same host.
##
## ============================================================================
## REDESIGN — the grim, dense gothic pilgrim city (code-generated placeholders)
## ============================================================================
## This level is now a THIN NETWORKED SHELL. The whole town — ground, crooked roads, ramparts,
## enterable buildings, interiors, ~90 placeholder prop kinds, landmarks, the cursed fountain, the
## decorative World Gate, plus wind-sway / glow shaders and drifting ash + leaf particles — is built
## by `SanctuaryTownWorld` (scripts/levels/town/sanctuary_town_world.gd), which is decoupled from
## the network so it can also render in an offline preview. Props are drawn by `SanctuaryProps`.
##
## The town spans ±3328 × ±3072 (redesign spec). The server widens the Sanctuary bounds to match
## (rust/sim_core/src/constants.rs SANCTUARY_MAP_MIN/MAX) so the whole city is walkable; players
## spawn through the damaged West Gate into the refugee yard.
##
## Layout + tone are documented in docs/design/sanctuary-layout.md and
## docs/design/sanctuary-redesign-spec.md (system of record).
extends ArenaBase

const SanctuaryTownWorldScript := preload("res://scripts/levels/town/sanctuary_town_world.gd")
const NPC_SCENE: PackedScene = preload("res://scenes/entities/npc/npc.tscn")
const PORTAL_SCENE: PackedScene = preload("res://scenes/entities/portal/portal.tscn")
## Reused confirm modal for the priest's church sacrifice prompt.
const ConfirmDialogScene: PackedScene = preload("res://scenes/ui/dialogs/confirm_dialog.tscn")

const NPC_TEXTURE_DIR := "res://assets/sprites/npcs/"
const TOWN_TEXTURE_DIR := "res://assets/sprites/environment/town/"

var _town = null   # SanctuaryTownWorld (untyped so path-first builder calls stay duck-typed)

## Church sacrifice flow (priest interaction). Created on demand.
var _sacrifice_confirm = null               # ConfirmDialog instance (untyped — no class_name)
var _sacrifice_request: HTTPRequest = null
var _sacrifice_in_flight := false


## ArenaBase calls this on scene entry (before _setup_client). Build the town: the EntityContainer +
## HUDLayer the networked base needs, then the whole placeholder city via SanctuaryTownWorld. NPCs +
## the Arena portal are deferred to _after_client_setup (they need the HUD/scene present). Wall
## colliders are intentionally NOT used for movement — the Sanctuary is server-authoritative
## walk-through — so the town's tagged colliders never block the networked player.
func _build_level_environment() -> void:
	# Suppress the inherited dark arena floor; the town paints its own ground layer.
	_draws_arena_floor = false

	# ArenaBase needs the EntityContainer by name and the bare sanctuary.tscn lacks it.
	# The HUDLayer is the shared GameHud, instanced later in _setup_hud — not created here.
	if get_node_or_null("EntityContainer") == null:
		var entities := Node2D.new()
		entities.name = "EntityContainer"
		add_child(entities)

	_town = SanctuaryTownWorldScript.new()
	_town.name = "TownWorld"
	# The minimap viewport culls a whole subtree if an ANCESTOR's visibility_layer misses its
	# cull mask, so the town root must carry the minimap bit for its ground/wall layers to show.
	_town.visibility_layer = GameConstants.MINIMAP_TERRAIN_VISIBILITY
	add_child(_town)
	_town.build()


## Sanctuary world geometry: the full town is walkable (±3328 × ±3072), NO obstacles. Pushed into
## the prediction sim by ArenaBase._setup_client BEFORE the first predicted step so prediction
## matches the --mode sanctuary server (which uses the same SANCTUARY_MAP_MIN/MAX constants).
func _world_geometry() -> Array:
	var r: Rect2 = SanctuaryTownWorldScript.TOWN_RECT
	return [r.position, r.position + r.size, false]


## The minimap/map frame the WHOLE walkable town, not the ±1000 arena default.
func get_map_bounds() -> Rect2:
	return SanctuaryTownWorldScript.TOWN_RECT


## Runs at the end of _setup_client (client only): HUD, camera, prediction and entity container now
## exist. Build the kept-art NPCs (the priest opens the sacrifice flow) and the functional Arena
## portal here, and retarget the pause menu's "leave" to the main menu.
func _after_client_setup() -> void:
	if _town:
		_town.build_npcs(_town, NPC_SCENE, NPC_TEXTURE_DIR, _on_npc_interacted)
		_town.build_arena_portal(_town, PORTAL_SCENE, TOWN_TEXTURE_DIR)
	# The HUD now exists (instanced in _setup_hud); add the Sanctuary overlay labels onto it.
	_build_safe_zone_badge()
	if pause_menu:
		pause_menu.set_leave_button_text("EXIT TO MENU")


## All visuals live in the TownWorld child and the inherited arena floor is suppressed, so the
## Sanctuary node itself draws nothing.
func _draw() -> void:
	pass


## Leave the Sanctuary (pause menu "Exit to Menu" or the T/tilde return key): disconnect from the
## Sanctuary server instance and return to the main menu. Overrides ArenaBase._leave_arena (which
## would route back to the Sanctuary — meaningless from inside it).
func _leave_arena() -> void:
	if _is_leaving_arena:
		return
	_is_leaving_arena = true

	var audio := _get_audio_manager()
	if audio:
		audio.stop_music()
	GameManager.persist_progression()
	NetworkManager.disconnect_from_server("Leave Sanctuary")
	GameManager.change_state(GameManager.GameState.MAIN_MENU)
	SceneManager.goto_main_menu()


# =============================================================================
# CHURCH SACRIFICE  (priest interaction)
# =============================================================================

## The priest was interacted with: open the sacrifice confirm prompt.
func _on_npc_interacted(npc) -> void:
	if npc == null or npc.role != TownNpc.Role.PRIEST:
		return
	if _sacrifice_in_flight:
		return
	if _sacrifice_confirm == null:
		_sacrifice_confirm = ConfirmDialogScene.instantiate()
		add_child(_sacrifice_confirm)
		_sacrifice_confirm.confirmed.connect(_on_sacrifice_confirmed)
	_sacrifice_confirm.show_confirm(
		"Sacrifice Character",
		"Sacrifice your character to the silent gods? This deletes it and converts your XP to Glory.",
		"Sacrifice",
		"Cancel"
	)


## Confirmed sacrifice: POST /api/character/sacrifice with the JWT auth header.
func _on_sacrifice_confirmed() -> void:
	if _sacrifice_in_flight:
		return
	var header := AuthManager.get_auth_header()
	if header.is_empty():
		push_warning("[Sanctuary] Cannot sacrifice: not authenticated")
		return

	_sacrifice_in_flight = true
	if _sacrifice_request == null:
		_sacrifice_request = HTTPRequest.new()
		add_child(_sacrifice_request)
	if _sacrifice_request.request_completed.is_connected(_on_sacrifice_completed):
		_sacrifice_request.request_completed.disconnect(_on_sacrifice_completed)
	_sacrifice_request.request_completed.connect(_on_sacrifice_completed)

	var url := AuthManager.api_base_url + "/api/character/sacrifice"
	var headers := ["Content-Type: application/json", header]
	var error := _sacrifice_request.request(url, headers, HTTPClient.METHOD_POST, "{}")
	if error != OK:
		_sacrifice_in_flight = false
		push_warning("[Sanctuary] Sacrifice request failed to start: %d" % error)


## Handle the sacrifice API response: on success clear the local character and route to character
## creation. The DB is authoritative; the local reset keeps the display clean.
func _on_sacrifice_completed(result: int, response_code: int, _headers: PackedStringArray, _body: PackedByteArray) -> void:
	_sacrifice_in_flight = false
	if _sacrifice_request and _sacrifice_request.request_completed.is_connected(_on_sacrifice_completed):
		_sacrifice_request.request_completed.disconnect(_on_sacrifice_completed)

	if result != HTTPRequest.RESULT_SUCCESS:
		push_warning("[Sanctuary] Sacrifice request failed: %d" % result)
		return

	if response_code == 200 or response_code == 204:
		# Character sacrificed: drop local character state and route to creation.
		GameManager.clear_local_player_entity_id()
		GameManager.player_data["character_name"] = ""
		GameManager.player_data["character_id"] = ""
		GameManager.player_data["player_class"] = PacketTypes.PlayerClass.ZEALOT
		GameManager.reset_progression()
		GameManager.player_data_updated.emit()
		# Tear down the live Sanctuary ENet session before leaving (matches _leave_arena);
		# the sacrificed character must not linger as a connected entity.
		NetworkManager.disconnect_from_server("Character sacrificed")
		print("[Sanctuary] Character sacrificed; routing to character creation")
		SceneManager.goto_character_creation()
	else:
		push_warning("[Sanctuary] Sacrifice returned status %d" % response_code)


# =============================================================================
# HUD
# =============================================================================

func _build_safe_zone_badge() -> void:
	# HUDLayer is created in _build_level_environment before this runs (networked base owns it).
	var hud := get_hud_layer()
	if hud == null:
		return

	var badge := Label.new()
	badge.name = "SafeZoneBadge"
	badge.text = "SANCTUARY  •  SAFE ZONE"
	badge.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	badge.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	badge.offset_left = -220.0
	badge.offset_right = 220.0
	badge.offset_top = 62.0
	badge.offset_bottom = 94.0
	badge.add_theme_font_size_override("font_size", 22)
	badge.add_theme_color_override("font_color", Color("c69a2e"))
	badge.add_theme_color_override("font_outline_color", Color("050706"))
	badge.add_theme_constant_override("outline_size", 6)
	hud.add_child(badge)

	var hint := Label.new()
	hint.name = "TravelHint"
	hint.text = "You made it inside the walls. The Arena Portal waits in the Lower Sanctum, south-east."
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP)
	hint.offset_left = -340.0
	hint.offset_right = 340.0
	hint.offset_top = 98.0
	hint.offset_bottom = 120.0
	hint.add_theme_font_size_override("font_size", 13)
	hint.add_theme_color_override("font_color", Color(0.82, 0.78, 0.7, 0.85))
	hud.add_child(hint)
