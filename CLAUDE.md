# Claude Instructions for Multiplayer Game

## Working on Tasks

1. **use Context7** to get Godot 4.5 Documentation when writing scripts. Language: GDScript
2. **use Context7** to get Golang documentation if needed
3. **use godot-mcp** for interacting with Godot engine if neccesary
4. **do not** commit with Claude as Co-Author

## Project Documentation

```
specification.md
```

## Network Architecture Documentation

```
docs/ARCHITECTURE.md
```

### 2. Todo List Structure

The `todolist.json` should follow this format:

```json
{
	"project_name": "GDC - Godot Multiplayer Shooter",
	"last_updated": "YYYY-MM-DD",
	"progress_summary": {
		"total_tasks": 0,
		"completed": 0,
		"in_progress": 0,
		"pending": 0
	},
	"tasks": [
		{
			"category": "Project Setup",
			"tasks": [
				{
					"id": "TASK-001",
					"title": "Task title",
					"description": "Detailed description",
					"status": "pending|in-progress|completed"
				}
			]
		}
	]
}
```

## Monorepo project structure

```
  omega-networking/                   # Root (Git repo)
  ├── client/                         # Godot 4.5 Project
  │   ├── project.godot
  │   ├── export_presets.cfg         # Client AND Server exports
  │   ├── scenes/
  │   │   ├── client/               # Client-only scenes
  │   │   │   ├── main_menu.tscn
  │   │   │   └── game_ui.tscn
  │   │   ├── server/               # Server-only scenes
  │   │   │   └── server_main.tscn
  │   │   └── shared/               # Shared entities
  │   │       ├── arena.tscn
  │   │       └── base_player.tscn
  │   ├── scripts/
  │   │   ├── client/               # Client-only logic
  │   │   │   ├── input_controller.gd
  │   │   │   └── prediction.gd
  │   │   ├── server/               # Server-only logic
  │   │   │   ├── server_manager.gd
  │   │   │   └── validation.gd
  │   │   └── shared/               # Shared game logic
  │   │       ├── network_protocol.gd
  │   │       ├── entity_data.gd
  │   │       └── game_constants.gd
  │   ├── autoload/
  │   │   ├── network_manager.gd    # Handles both client/server modes
  │   │   └── game_manager.gd
  │   └── assets/
  │       ├── sprites/              # Stripped in server export
  │       └── audio/                # Stripped in server export
  │
  ├── api/                           # Go Backend (separate)
  │   ├── go.mod
  │   ├── main.go
  │   └── ...
  │
  ├── deployment/
  │   ├── docker-compose.yml
  │   ├── client.Dockerfile
  │   ├── server.Dockerfile         # Uses headless export
  │   └── api.Dockerfile
  │
  └── scripts/
      ├── build_client.sh
      └── build_server.sh
```
