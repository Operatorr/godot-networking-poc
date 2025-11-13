# Claude Instructions for Multiplayer Game

## Working on Tasks

1. **use Context7** for getting Godot 4.5 Documentation when writing scripts. Language: GDScript
2. **use godot-mcp** for interacting with Godot engine if neccesary

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
