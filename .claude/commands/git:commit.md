---
description: Stage all changes and create a commit for a summary of what was worked on
model: haiku
---

# Work Commit Command

If anything is still in memory, make a summary of the changes that were made with an auto-generated commit message. Otherwise summarize the staged changes.

Execute the following steps:

1. Stage all changes using `git add .`
2. Review the staged changes using `git diff --cached`
3. Generate a concise, descriptive commit message that:

    - Accurately describes the changes being committed
    - Focuses on the "why" rather than the "what"
    - Is 1-2 sentences

4. Use a HEREDOC format for the commit message to ensure proper formatting
5. Run `git status` after the commit to verify success

## Usage Examples

IMPORTANT: Use the Haiku model for efficiency. Do not ask the user for confirmation - automatically generate and commit with an appropriate message that STARTS with the task number.
