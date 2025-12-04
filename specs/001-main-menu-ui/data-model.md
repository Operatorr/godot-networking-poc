# Data Model: Main Menu UI

**Feature Branch**: `001-main-menu-ui`
**Date**: 2025-12-04

## Client-Side Data Structures

### 1. AuthManager State (Existing)

```gdscript
## Already defined in client/autoload/auth_manager.gd
enum AuthState {
    LOGGED_OUT,     ## No authentication, show login screen
    LOGGING_IN,     ## Login request in progress
    LOGGED_IN,      ## Authenticated with valid token
    REGISTERING,    ## Registration in progress (unused - external registration)
    ERROR           ## Authentication error occurred
}

## Runtime state
var current_state: AuthState = AuthState.LOGGED_OUT
var jwt_token: String = ""
var refresh_token: String = ""
var token_expiry: int = 0
```

### 2. GameManager Player Data (Existing)

```gdscript
## Already defined in client/autoload/game_manager.gd
var player_data: Dictionary = {
    "character_name": "",      ## Display name (empty if no character)
    "character_id": "",        ## Backend ID (empty if no character)
    "user_id": "",             ## Account ID
    "selected_region": "Asia", ## Default region
    "session_id": ""           ## Current session ID
}
```

### 3. Region Data Structure (New - Client)

```gdscript
## Region information fetched from API
class_name RegionInfo
extends RefCounted

var id: String              ## e.g., "asia", "europe", "us-west"
var name: String            ## Display name, e.g., "Asia"
var websocket_url: String   ## Game server WebSocket URL
var status: String          ## "online", "offline", "maintenance"
var active_players: int     ## Current player count
var max_players: int        ## Maximum capacity

static func from_dict(data: Dictionary) -> RegionInfo:
    var region := RegionInfo.new()
    region.id = data.get("id", "")
    region.name = data.get("name", "")
    region.websocket_url = data.get("websocket_url", "")
    region.status = data.get("status", "offline")
    region.active_players = data.get("active_players", 0)
    region.max_players = data.get("max_players", 1000)
    return region

func is_available() -> bool:
    return status == "online" and active_players < max_players
```

### 4. User Preferences (New - Client)

```gdscript
## Local preferences stored in user://preferences.json
class_name UserPreferences
extends RefCounted

const SAVE_PATH: String = "user://preferences.json"

var selected_region: String = "us-west"  ## Default region (US-West per spec)
var remember_username: bool = true       ## Not used per spec (always persist)

static func load() -> UserPreferences:
    var prefs := UserPreferences.new()
    if not FileAccess.file_exists(SAVE_PATH):
        return prefs

    var file := FileAccess.open(SAVE_PATH, FileAccess.READ)
    if file == null:
        return prefs

    var json := JSON.new()
    if json.parse(file.get_as_text()) == OK and json.data is Dictionary:
        prefs.selected_region = json.data.get("selected_region", "us-west")
    file.close()
    return prefs

func save() -> void:
    var file := FileAccess.open(SAVE_PATH, FileAccess.WRITE)
    if file == null:
        push_error("[UserPreferences] Failed to save preferences")
        return

    file.store_string(JSON.stringify({
        "selected_region": selected_region
    }))
    file.close()
```

### 5. Login Credentials (Transient)

```gdscript
## Used only during login flow, never persisted (passwords)
## Already handled by AuthManager.login(username, password)
```

### 6. Character Creation Request

```gdscript
## Sent to POST /api/character/create
## Request body:
{
    "name": "PlayerName"  ## 3-16 alphanumeric + underscore
}

## Response on success (201):
{
    "message": "Character created successfully",
    "character": {
        "id": 1,
        "user_id": 1,
        "name": "PlayerName",
        "created_at": "2025-12-04T12:00:00Z"
    }
}

## Response on error:
{
    "error": "Character name already taken"  ## or validation error
}
```

## Server-Side Data Structures (Existing)

### User Model (Go)

```go
// Already defined in api/internal/models/models.go
type User struct {
    ID           int       `json:"id"`
    Username     string    `json:"username"`
    Email        string    `json:"email"`
    PasswordHash string    `json:"-"`          // Never sent to client
    Region       string    `json:"region"`
    CreatedAt    time.Time `json:"created_at"`
}
```

### Character Model (Go)

```go
// Already defined in api/internal/models/models.go
type Character struct {
    ID        int       `json:"id"`
    UserID    int       `json:"user_id"`
    Name      string    `json:"name"`
    CreatedAt time.Time `json:"created_at"`
}
```

### Region Model (Go)

```go
// Already defined in api/internal/models/region.go
type Region struct {
    ID            string `json:"id"`
    Name          string `json:"name"`
    WebSocketURL  string `json:"websocket_url"`
    Status        string `json:"status"`          // online, offline, maintenance
    ActivePlayers int64  `json:"active_players"`
    MaxPlayers    int    `json:"max_players"`
}
```

## State Transitions

### Authentication Flow

```
┌──────────────┐     login()     ┌──────────────┐
│  LOGGED_OUT  │ ───────────────>│  LOGGING_IN  │
└──────────────┘                 └──────┬───────┘
       ^                                │
       │                    success     │     failure
       │ logout()              ┌────────┴────────┐
       │                       v                 v
       │               ┌──────────────┐  ┌──────────────┐
       └───────────────│  LOGGED_IN   │  │    ERROR     │
                       └──────────────┘  └──────────────┘
```

### Scene Navigation Flow

```
┌─────────────────┐
│   Game Launch   │
└────────┬────────┘
         │
         v
  ┌──────────────────┐
  │ Check Auth State │
  └────────┬─────────┘
           │
     ┌─────┴─────┐
     │           │
   Logged Out  Logged In
     │           │
     v           v
┌─────────┐  ┌────────────────┐
│ Login   │  │ Has Character? │
│ Screen  │  └───────┬────────┘
└────┬────┘          │
     │         ┌─────┴─────┐
     │        Yes          No
     │         │           │
     │         v           v
     │    ┌─────────┐  ┌────────────────┐
     └───>│ Main    │<─│ Character      │
          │ Menu    │  │ Creation       │
          └────┬────┘  └────────────────┘
               │
               v
          ┌─────────┐
          │ Arena   │
          └─────────┘
```

## Validation Rules

### Character Name

| Rule | Constraint | Error Message |
|------|------------|---------------|
| Min Length | >= 3 | "Name must be at least 3 characters" |
| Max Length | <= 16 | "Name must not exceed 16 characters" |
| Characters | [a-zA-Z0-9_] | "Name can only contain letters, numbers, and underscores" |
| Uniqueness | Per region | "Character name already taken" (from server) |

### Region Selection

| Rule | Constraint | Error Message |
|------|------------|---------------|
| Valid ID | One of: asia, europe, us-west | "Invalid region" |
| Availability | status == "online" | "Region is currently unavailable" |
| Capacity | active_players < max_players | "Region is currently full" |

## Persistence Summary

| Data | Storage Location | Persistence |
|------|------------------|-------------|
| JWT Token | `user://auth_token.dat` | Across sessions |
| Refresh Token | `user://auth_token.dat` | Across sessions |
| Region Preference | `user://preferences.json` | Across sessions |
| Settings (volume, etc.) | `user://settings.json` | Across sessions (existing) |
| Character Data | PostgreSQL (server) | Permanent |
| Active Players | Redis (server) | Real-time |
