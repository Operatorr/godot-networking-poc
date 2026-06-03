---
name: git-pr
description: Create a feature branch off master/develop/main when needed, stage and commit all changes, push, and immediately open a pull request via the gh CLI. Use when the user asks to open a PR, ship changes, or commit and create a pull request.
argument-hint: "Optional summary of the work to ship"
---

# Git PR

Commit all current repository changes and immediately open a pull request. If the current branch is a protected base branch (`master`, `main`, or `develop`), create a feature branch first. Do not ask the user for confirmation — "open a PR" means do it.

## Workflow

### 1. Inspect state

Run in parallel:

- `git status --short` — what will be staged
- `git diff` and `git diff --stat` — the actual changes
- `git branch --show-current` — the current branch
- `git log -5 --oneline` — to match the repo's existing commit style

If there is nothing to commit, report that and stop. Do not create an empty commit or an empty PR.

### 2. Resolve the working branch and PR base

- Let `CURRENT` be the output of `git branch --show-current`.
- **If `CURRENT` is `master`, `main`, or `develop`** (a protected base branch):
  - The PR **base** is `CURRENT`.
  - Create a feature branch and switch to it: `git switch -c feature/<slug>`.
- **Otherwise** (already on a feature branch):
  - Stay on `CURRENT`; do not create a new branch.
  - Determine the PR **base** integration branch:
    - Use `develop` if it exists: `git ls-remote --exit-code --heads origin develop`.
    - Otherwise use the repo default: `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`.

Build `<slug>` as a short kebab-case summary of the work, derived from the supplied
argument or the diff (e.g. `feature/fix-login-redirect`). If the supplied summary
contains a task/issue key such as `ABC-123`, include it: `feature/ABC-123-fix-login-redirect`.

### 3. Stage and commit

- Stage everything from the repository root: `git add -A`.
- Generate a commit message following the **same conventions as the `git-commit` skill**:
  - Subject line ≤ 72 characters summarizing the change.
  - Body of 2–5 sentences focused on the why more than the what.
  - If the branch name contains a task/issue number, start the subject with it.
  - Do not include `Co-Authored-By` lines.
- Commit using a HEREDOC so formatting is preserved:

  ```sh
  git commit -m "$(cat <<'EOF'
  <subject>

  <body>
  EOF
  )"
  ```

### 4. Push the branch

```sh
git push -u origin <branch>
```

### 5. Open the pull request

Use the commit subject as the title and a short summary as the body:

```sh
gh pr create --base <base> --head <branch> --title "<subject>" --body "$(cat <<'EOF'
## Summary
<2–4 sentence overview of the change and why it was made>

## Changes
- <key change>
- <key change>
EOF
)"
```

### 6. Report

Report the PR URL printed by `gh pr create`. Verify success with `git status`.

## Failure handling

- If `gh` is not installed or not authenticated (`gh auth status` fails), report that and stop after committing — do not lose the commit.
- If `git push` fails (e.g. no remote, rejected, auth), report the exact error rather than retrying blindly.
- If a pre-commit hook modifies files, fails, or leaves staged/unstaged changes, report that state rather than silently retrying.
- If a PR already exists for the branch, `gh pr create` will fail — report the existing PR (`gh pr view --json url`) instead of treating it as an error.
- If a summary of the work is already in context or supplied as arguments, use it for the branch name, commit message, and PR body.
