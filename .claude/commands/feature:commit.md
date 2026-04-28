---
description: Create a new feature branch and commit all changes to it
model: haiku
argument-hint: <branch-name>
---

# Feature Branch Commit Command

Create a new feature branch with the provided name and commit all current changes to that branch.

The branch name is provided as an argument: `$ARGUMENTS`

If anything is still in memory, make a summary of the changes that were made with an auto-generated commit message. Otherwise summarize the staged changes.

Execute the following steps:

1. Validate that a branch name was provided as an argument. If not, abort with an error message asking the user to provide a branch name.
2. Create and switch to a new feature branch using `git checkout -b <branch-name>` where `<branch-name>` is the argument passed to the command. If the branch name does not already start with a feature prefix (e.g. `feature/`, `feat/`, `fix/`, `chore/`), prepend `feature/` to it.
3. Stage all changes using `git add .`
4. Review the staged changes using `git diff --cached`
5. Generate a concise, descriptive commit message that:

    - Accurately describes the changes being committed
    - Focuses on the "why" rather than the "what"
    - Is 3-5 sentences
    - Do NOT include any `Co-Authored-By` lines in the commit message

6. Use a HEREDOC format for the commit message to ensure proper formatting
7. Run `git status` after the commit to verify success
8. Display the new branch name and a hint for pushing it upstream (e.g. `git push -u origin <branch-name>`)

## Usage Examples

- `/work-commit user-authentication` → creates branch `feature/user-authentication` and commits changes
- `/work-commit fix/login-bug` → creates branch `fix/login-bug` (prefix preserved) and commits changes
- `/work-commit feat/dark-mode` → creates branch `feat/dark-mode` (prefix preserved) and commits changes

IMPORTANT: Use the Haiku model for efficiency. Do not ask the user for confirmation - automatically create the branch, generate the commit message, and commit with an appropriate message that STARTS with the task number.

IMPORTANT: NEVER include "Co-Authored-By" lines in commit messages.

IMPORTANT: If the working tree is clean (no changes to commit) after creating the branch, inform the user and do not attempt an empty commit.