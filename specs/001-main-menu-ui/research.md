# Research: Main Menu UI

**Feature Branch**: `001-main-menu-ui`
**Date**: 2025-12-04

## Research Questions Resolved

### 1. How does the existing AuthManager integrate with UI?

**Decision**: Use AuthManager signals for reactive UI updates

**Rationale**: AuthManager already provides comprehensive signals:
- `login_successful(user_data: Dictionary)` - Triggers navigation to main menu or character creation
- `login_failed(error: String)` - Displays error modal
- `auth_state_changed(new_state: AuthState)` - Updates UI state

**Implementation**:
```gdscript
# Connect to AuthManager signals in _ready()
AuthManager.login_successful.connect(_on_login_successful)
AuthManager.login_failed.connect(_on_login_failed)
AuthManager.auth_state_changed.connect(_on_auth_state_changed)

func _on_login_successful(user_data: Dictionary) -> void:
    # Check if character exists
    if user_data.get("character_id", "").is_empty():
        SceneManager.goto_character_creation()
    else:
        SceneManager.goto_main_menu()
```

**Alternatives Considered**:
- Polling AuthManager state (rejected: unnecessary CPU usage, reactive is cleaner)
- Direct HTTP calls from UI (rejected: duplicates AuthManager functionality)

---

### 2. How should scene navigation work between Login → MainMenu → CharacterCreation?

**Decision**: Use existing SceneManager with defined scene paths

**Rationale**: SceneManager already defines all required paths:
```gdscript
const SCENE_MAIN_MENU = "res://scenes/client/menus/main_menu.tscn"
const SCENE_CHARACTER_CREATION = "res://scenes/client/menus/character_creation.tscn"
```

And provides convenience methods:
- `SceneManager.goto_main_menu()`
- `SceneManager.goto_character_creation()`

**Flow**:
1. Game launches → Check AuthManager.current_state
2. If LOGGED_OUT → Login screen
3. If LOGGED_IN with character → Main menu
4. If LOGGED_IN without character → Character creation

**Alternatives Considered**:
- Single scene with multiple containers (rejected: harder to maintain, breaks SceneManager pattern)
- Custom navigation system (rejected: SceneManager already handles cleanup and transitions)

---

### 3. How should the Login screen be added as the initial scene?

**Decision**: Add new Login screen scene, update SceneManager to check auth state on init

**Rationale**: SceneManager._ready() should route to appropriate scene:
```gdscript
# In SceneManager._ready() for CLIENT mode
if not is_server:
    await get_tree().process_frame
    if AuthManager.is_logged_in():
        if GameManager.has_character():
            change_scene(SceneName.MAIN_MENU, false)
        else:
            change_scene(SceneName.CHARACTER_CREATION, false)
    else:
        change_scene(SceneName.LOGIN, false)
```

**Required Changes**:
1. Add `SCENE_LOGIN` constant to SceneManager
2. Add `SceneName.LOGIN` enum value
3. Add `goto_login()` convenience method
4. Update `_ready()` to include auth state check

**Alternatives Considered**:
- Main scene handles routing (rejected: SceneManager is the appropriate place for scene decisions)
- Login as overlay (rejected: needs to be a full scene for proper state management)

---

### 4. What is the character name validation pattern?

**Decision**: 3-16 alphanumeric characters plus underscore, validated both client-side and server-side

**Rationale**:
- Spec states: "3-16 alphanumeric characters"
- Go API validates: `a-z, A-Z, 0-9, space, underscore, hyphen` with 3-50 char limit
- Need to align client validation with server

**Client-side validation**:
```gdscript
const NAME_MIN_LENGTH: int = 3
const NAME_MAX_LENGTH: int = 16
const NAME_PATTERN: String = "^[a-zA-Z0-9_]+$"

func validate_character_name(name: String) -> String:
    name = name.strip_edges()
    if name.length() < NAME_MIN_LENGTH:
        return "Name must be at least %d characters" % NAME_MIN_LENGTH
    if name.length() > NAME_MAX_LENGTH:
        return "Name must not exceed %d characters" % NAME_MAX_LENGTH
    var regex = RegEx.new()
    regex.compile(NAME_PATTERN)
    if not regex.search(name):
        return "Name can only contain letters, numbers, and underscores"
    return ""  # Valid
```

**Note**: Server uses max 50 chars but spec requires 16. Client enforces stricter 16-char limit.

**Alternatives Considered**:
- Server-only validation (rejected: bad UX, wastes API calls)
- Unicode support (rejected: spec explicitly states alphanumeric only)

---

### 5. How should error dialogs be implemented?

**Decision**: Create reusable ErrorDialog scene with popup functionality

**Rationale**: Multiple screens need error handling (login failures, API errors, connection issues). A reusable component ensures consistent UX.

**ErrorDialog Features**:
- Title and message text
- Optional retry button
- Close/OK button
- Modal behavior (blocks input to parent)
- Audio feedback on show

**Implementation**:
```gdscript
## ErrorDialog - Reusable error modal component
class_name ErrorDialog
extends PopupPanel

signal retry_pressed
signal closed

@onready var title_label: Label = $VBoxContainer/TitleLabel
@onready var message_label: Label = $VBoxContainer/MessageLabel
@onready var retry_button: Button = $VBoxContainer/ButtonContainer/RetryButton
@onready var close_button: Button = $VBoxContainer/ButtonContainer/CloseButton

func show_error(title: String, message: String, show_retry: bool = false) -> void:
    title_label.text = title
    message_label.text = message
    retry_button.visible = show_retry
    popup_centered()
```

**Alternatives Considered**:
- OS.alert() (rejected: doesn't support retry, not styleable)
- Inline error labels (rejected: inconsistent for different error types)

---

### 6. How should audio feedback be integrated?

**Decision**: Use existing AudioManager with button_hover and button_click sounds

**Rationale**: AudioManager already has:
- `play_button_hover()` method
- `play_button_click()` method
- UI SFX player pool

**Implementation on buttons**:
```gdscript
func _ready() -> void:
    for button in get_tree().get_nodes_in_group("menu_buttons"):
        button.mouse_entered.connect(_on_button_hover)
        button.pressed.connect(_on_button_click)

func _on_button_hover() -> void:
    AudioManager.play_button_hover()

func _on_button_click() -> void:
    AudioManager.play_button_click()
```

**Required**: Add audio assets to library in AudioManager:
```gdscript
"sfx_ui": {
    "button_hover": preload("res://assets/audio/sfx/button_hover.ogg"),
    "button_click": preload("res://assets/audio/sfx/button_click.ogg")
}
```

**Alternatives Considered**:
- Per-button AudioStreamPlayer nodes (rejected: wasteful, AudioManager pools exist)
- No audio (rejected: spec requires audio feedback)

---

### 7. How should region selection persist?

**Decision**: Store in GameManager.player_data, save to user:// on change

**Rationale**: GameManager already stores `selected_region` in player_data dictionary and has settings persistence. Region preference should be saved separately from auth token.

**Implementation**:
```gdscript
# In region dropdown change handler
func _on_region_selected(region_id: String) -> void:
    GameManager.player_data.selected_region = region_id
    _save_region_preference(region_id)

func _save_region_preference(region_id: String) -> void:
    var save_path = "user://preferences.json"
    var prefs = {}
    if FileAccess.file_exists(save_path):
        var file = FileAccess.open(save_path, FileAccess.READ)
        var json = JSON.new()
        if json.parse(file.get_as_text()) == OK:
            prefs = json.data
        file.close()
    prefs["selected_region"] = region_id
    var file = FileAccess.open(save_path, FileAccess.WRITE)
    file.store_string(JSON.stringify(prefs))
    file.close()
```

**Alternatives Considered**:
- Store in auth token (rejected: region is client preference, not auth data)
- Only in-memory (rejected: spec requires persistence across restarts)

---

### 8. How should the regions dropdown be populated?

**Decision**: Fetch from `/api/regions` API endpoint on main menu load

**Rationale**: API already provides regions with active player counts. Dynamic fetching allows server-side region management.

**API Response Format** (from region handler):
```json
{
  "regions": [
    {
      "id": "asia",
      "name": "Asia",
      "websocket_url": "wss://asia.example.com:8081",
      "status": "online",
      "active_players": 42,
      "max_players": 1000
    }
  ]
}
```

**Client Implementation**:
```gdscript
func _fetch_regions() -> void:
    var http = HTTPRequest.new()
    add_child(http)
    http.request_completed.connect(_on_regions_received)
    http.request(AuthManager.api_base_url + "/api/regions")

func _on_regions_received(result: int, code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
    if code != 200:
        return
    var json = JSON.new()
    if json.parse(body.get_string_from_utf8()) == OK:
        var regions = json.data.get("regions", [])
        _populate_region_dropdown(regions)
```

**Alternatives Considered**:
- Hardcoded regions (rejected: less flexible, API already exists)
- Store regions in local config (rejected: API provides live player counts)

---

### 9. What URLs should external links use?

**Decision**: Configurable via export variables or project settings

**Rationale**: Spec states URLs must be configurable (FR-004a). Export variables allow per-deployment configuration.

**Implementation**:
```gdscript
## Configurable external URLs
@export var registration_url: String = "https://example.com/register"
@export var forgot_password_url: String = "https://example.com/forgot-password"

func _on_create_account_pressed() -> void:
    OS.shell_open(registration_url)

func _on_forgot_password_pressed() -> void:
    OS.shell_open(forgot_password_url)
```

**Note**: These can be overridden in the scene inspector or via a configuration file.

**Alternatives Considered**:
- Hardcoded URLs (rejected: spec requires configurability)
- API endpoint for URLs (rejected: over-engineering for simple links)

---

### 10. How should the character sprite/portrait be displayed?

**Decision**: Use TextureRect with placeholder, load actual sprite when character data available

**Rationale**: Spec requires 2D sprite/portrait display. Character sprite asset is assumed to be provided (per assumptions in spec).

**Implementation**:
```gdscript
@onready var character_portrait: TextureRect = $CharacterPanel/Portrait

func _update_character_display() -> void:
    var char_name = GameManager.player_data.get("character_name", "")
    if char_name.is_empty():
        character_portrait.visible = false
        return

    character_portrait.visible = true
    # Load character portrait (placeholder for now)
    character_portrait.texture = preload("res://assets/sprites/player/portrait_default.png")
    character_name_label.text = char_name
```

**Alternatives Considered**:
- 3D preview (rejected: spec says 2D sprite)
- No visual (rejected: spec explicitly requires character display)

---

## Technology Best Practices Applied

### Godot 4.5 UI Best Practices

1. **Use Control node anchors** for responsive layouts
2. **Theme resources** for consistent styling across screens
3. **Focus neighbors** set for keyboard navigation (Tab support)
4. **Signal-based communication** rather than direct references
5. **Typed signals** where possible for compile-time checking

### GDScript Style (per Constitution)

1. **Static typing** on all function parameters and return values
2. **Documentation comments** on exported variables
3. **Client-only code** in `scripts/client/` directory
4. **No cross-imports** from server code

### Error Handling

1. **User-friendly messages** - never expose technical errors
2. **Retry options** for recoverable errors (network, API)
3. **Graceful degradation** - missing audio assets don't crash
4. **Logging** for debugging without user-facing impact
