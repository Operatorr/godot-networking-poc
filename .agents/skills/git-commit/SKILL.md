---
name: git-commit
description: Create a git commit for the current worktree when the user asks Codex to commit the current changes, make a commit with an auto-generated message, or stage and commit finished work. Use this skill for commit-message generation and commit execution. Do not use it for reviewing history, rebasing, pushing, or other general git tasks.
---

Create a git commit that summarizes the work.

Use the current session context when available. Otherwise base the message on the staged diff.

If this repo contains `app/data/changelog.json`, treat changelog maintenance as part of the commit workflow for shipped user-facing changes.

## Workflow

1. Stage all intended changes with `git add .`
2. Review the staged changes with `git diff --cached`
3. If there is nothing staged, stop and report that clearly
4. If `app/data/changelog.json` exists, decide whether the staged changes are user-facing enough to warrant a changelog entry
5. Generate a concise commit message that:
   - accurately describes the change set
   - explains the why, not just the file-level what
   - is 2-5 sentences
   - starts with the task number when one is clearly available from the branch name or current context
   - never includes `Co-Authored-By` lines
6. Create the main commit using a HEREDOC so multi-sentence formatting is preserved
7. If a changelog entry is needed and `app/data/changelog.json` exists:
   - read the current file format before editing
   - add a new top entry summarizing the shipped behavior in `added` and `fixed`
   - use the short hash of the main commit as the `version`
   - stage the changelog update and create a second focused commit for it
8. Run `git status` after committing to verify success

## Behavior

- Do not ask the user for confirmation before committing unless they explicitly asked for a review-only or draft-only step
- Never rewrite, amend, or squash existing commits unless the user explicitly asks
- Do not include unrelated observations or tool output in the commit message
- Do not skip the changelog just because the version depends on the commit hash; make the main commit first, then add the changelog entry in a follow-up commit when needed
