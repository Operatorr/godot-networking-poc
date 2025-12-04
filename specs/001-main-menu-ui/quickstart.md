# Quickstart: Main Menu UI Development

**Feature Branch**: `001-main-menu-ui`

## Prerequisites

- Godot 4.5 installed
- Go 1.21+ installed
- Docker & Docker Compose (for database services)
- Git

## Setup Steps

### 1. Clone and Switch to Feature Branch

```bash
cd /path/to/workspace
git clone <repo-url> omega-networking
cd omega-networking
git checkout 001-main-menu-ui
```

### 2. Start Backend Services

```bash
# Start PostgreSQL and Redis
cd deployment
docker-compose up -d postgres redis

# Verify services are running
docker-compose ps
```

### 3. Run Go API Server

```bash
cd api

# Install dependencies
go mod download

# Copy environment template (if needed)
cp ../.env.example .env

# Run the API server
go run cmd/server/main.go
```

Expected output:
```
[API] Initializing database connection...
[API] Database connected successfully
[API] Initializing Redis connection...
[API] Redis connected successfully
[API] Starting server on port 8080...
```

### 4. Open Godot Project

```bash
cd client

# Open in Godot editor
godot project.godot
```

Or double-click `client/project.godot` to open in Godot.

### 5. Run the Client

In Godot editor:
- Press **F5** to run the project
- Client will detect it's NOT running headless and initialize as client
- Initial scene will depend on auth state

## Development Workflow

### Creating New Scenes

New scenes for this feature go in:
```
client/scenes/client/menus/
├── login_screen.tscn
├── main_menu.tscn (modify existing)
└── character_creation.tscn
```

### Creating New Scripts

New scripts go in:
```
client/scripts/client/
├── login_screen.gd
├── main_menu.gd (modify existing)
├── character_creation.gd
└── ui/
    └── error_dialog.gd
```

### Testing Auth Flow

1. **Register a test user** (via API or external website):
   ```bash
   curl -X POST http://localhost:8080/api/auth/register \
     -H "Content-Type: application/json" \
     -d '{"username":"testuser","email":"test@example.com","password":"testpass123"}'
   ```

2. **Test login in client**:
   - Enter username/password
   - Click Login
   - Should redirect to Character Creation (new user) or Main Menu (returning user)

### Testing Character Creation

1. **Login as user without character**
2. **Enter character name** (3-16 chars, alphanumeric + underscore)
3. **Click Create**
4. **Verify redirect to Main Menu** with character displayed

### Testing Region Selection

1. **Login as user with character**
2. **Click region dropdown**
3. **Verify regions load** from API with player counts
4. **Select a region**
5. **Verify selection persists** after restart

## API Endpoints Used

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/auth/login` | POST | No | User login |
| `/api/auth/refresh` | POST | Yes | Token refresh |
| `/api/character/me` | GET | Yes | Get user's character |
| `/api/character/create` | POST | Yes | Create character |
| `/api/regions` | GET | No | List game regions |
| `/api/regions/select` | POST | Yes | Select region |

## Common Issues

### "Failed to connect to database"

Ensure PostgreSQL is running:
```bash
docker-compose ps
docker-compose up -d postgres
```

### "AuthManager state stuck on LOGGING_IN"

Check API server is running on port 8080:
```bash
curl http://localhost:8080/health
```

### "Scene not found" errors

Ensure SceneManager constants match actual file paths:
```gdscript
# In client/autoload/scene_manager.gd
const SCENE_LOGIN = "res://scenes/client/menus/login_screen.tscn"
```

### Audio not playing

Check AudioManager audio_library is populated:
```gdscript
# Assets must be preloaded in AudioManager
"sfx_ui": {
    "button_hover": preload("res://assets/audio/sfx/button_hover.ogg"),
    "button_click": preload("res://assets/audio/sfx/button_click.ogg")
}
```

## File Locations Reference

| Purpose | Location |
|---------|----------|
| Feature spec | `specs/001-main-menu-ui/spec.md` |
| Implementation plan | `specs/001-main-menu-ui/plan.md` |
| API contracts | `specs/001-main-menu-ui/contracts/api.yaml` |
| Godot scenes | `client/scenes/client/menus/` |
| GDScript files | `client/scripts/client/` |
| Autoloads | `client/autoload/` |
| Go handlers | `api/internal/handlers/` |

## Testing Checklist

Before marking tasks complete:

- [ ] Login with valid credentials → redirects correctly
- [ ] Login with invalid credentials → shows error modal
- [ ] Token auto-refresh works (test with short expiry)
- [ ] Character creation validates name client-side
- [ ] Character creation handles server errors
- [ ] Region dropdown populates from API
- [ ] Region selection persists across restarts
- [ ] Enter World connects to game server
- [ ] Exit button closes application
- [ ] Audio plays on button hover/click
- [ ] Tab navigation works between inputs
- [ ] All buttons disable during operations
