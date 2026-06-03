---
name: git-commit
description: Stage all repository changes and create a git commit with an auto-generated message after inspecting status, diff, and recent commit style. Use when the user asks to commit changes, save changes in git, stage and commit, or create a commit without needing confirmation.
argument-hint: "Optional summary of the work to commit"
---

# Git Commit

Commit all current repository changes with an auto-generated message. Do not ask the user for confirmation.

## Workflow

1. Inspect state in parallel:
   - `git status --short` — what will be staged
   - `git diff --stat` and `git diff` — the actual changes
   - `git log -5 --oneline` — to match the repo's existing commit style
2. If there is nothing to commit, report that and stop. Do not create an empty commit.
3. Stage everything from the repository root:
   - `git add -A`
4. Generate a commit message:
   - Subject line is ≤ 72 characters and summarizes the change.
   - Body is 2–5 sentences focused on the why more than the what.
   - If the current branch name contains a task/issue number such as `feature/ABC-123-name`, start the subject with that number. Otherwise omit it.
   - Do not include `Co-Authored-By` lines.
5. Commit using a HEREDOC so formatting is preserved:

   ```sh
   git commit -m "$(cat <<'EOF'
   <subject>

   <body>
   EOF
   )"
   ```

6. Run `git status` after the commit to verify success.

## Failure handling

- If a pre-commit hook modifies files, fails, or leaves staged/unstaged changes, report that state rather than silently retrying.
- If a summary of the work is already in context or supplied as arguments, use it when writing the commit message.
- Never include `Co-Authored-By` lines in commit messages.
