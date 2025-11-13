---
description: Stage all changes and create a commit for a specific task
model: haiku
---

# Work Commit Command

Commit changes for task TASK-$ARGUMENTS with an auto-generated commit message.

Execute the following steps:

1. Stage all changes using `git add .`
2. Review the staged changes using `git diff --cached`
3. Generate a concise, descriptive commit message that:
    - **MUST start with "TASK-$ARGUMENTS: "** (e.g., "TASK-041: Description here")
    - Accurately describes the changes being committed
    - Focuses on the "why" rather than the "what"
    - Is 1-10 sentences maximum after the task prefix
4. DO NOT commit with Co-Author or Claude as co-author.

5. Use a HEREDOC format for the commit message to ensure proper formatting
6. Do not run `git status` after the commit to verify success

## Usage Examples

-   Command: `041` → Creates commit starting with "TASK-041: "
-   Command: `123` → Creates commit starting with "TASK-123: "

IMPORTANT: Use the Haiku model for efficiency. Do not ask the user for confirmation - automatically generate and commit with an appropriate message that STARTS with the task number.
