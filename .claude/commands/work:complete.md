---
description: Mark a task as completed by moving it from todolist.json to donelist.json
model: haiku
---

# Mark Task as Complete

Update task $ARGUMENTS in `todolist.json` to `"status": "completed"`.

## Instructions

1. Search in `todolist.json` for the task with ID "TASK-$ARGUMENTS"
2. Update the task:
   - Set status to "completed"

## Expected Formats

### todolist.json structure:

```json
{
	"project": "Omega Realm - Multiplayer Networking Proof of Concept",
	"version": "1.0",
	"date": "YYYY-MM-DD",
	"tasks": [...]
}
```

## Files to Modify

- `todolist.json` (search and modify - update task status to completed)

## Usage Examples

- Command: `001` → Marks TASK-001 as complete
- Command: `045` → Marks TASK-045 as complete
