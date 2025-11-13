---
description: Search for a task in todolist.json and display it to begin work
model: claude-sonnet-4-5
---

# Start Working on Task

Let's work on task $ARGUMENTS.

## Instructions

1. Search in `todolist.json` for the task with ID "TASK-$ARGUMENTS"
2. Display the complete task details in a clear, readable format
3. Check if there are any dependencies and note their status
4. Display a quick summary of what the purpose of this task is and describe what you intend to implement in pseudo language
5. Ask if I should proceed with implementing this task or if any clarification is needed

## Task Display Format

Show the task like this:

```
## Working on TASK-$ARGUMENTS

**Category**: [category]
**Title**: [title]

**Description**: [description]

**Dependencies**: [list dependencies or "None"]

**Files to Create**:
- [file paths]

**Purpose**: [notes]

**Intent**: [notes]

**Current Status**: [status]
```

Then ask: "Ready to work on this task?"

## Files to Read

- `todolist.json` (search only - find the specific task)

## Usage Examples

- Command: `038` → Fetches and displays TASK-038
- Command: `045` → Fetches and displays TASK-045
