---
name: code-review
description: "Perform a fast, light, conservative code review for GitHub pull requests or local branch changes. Use for /code-review, quick PR reviews, current-branch reviews, and default review requests when the user has not asked for a deep, exhaustive, CodeRabbit-style, nitpick-level, or find-everything review. Aim for the top 1-3 material issues; use deep-review for exhaustive coverage."
---

# Code Review

Run a fast, light review like a pragmatic senior engineer: understand the intent, inspect the diff in enough context to catch real risks, and report only the highest-signal findings.

This is the default review skill for `/code-review`. It optimizes for **precision and speed**, usually producing 0-3 issues. For exhaustive, CodeRabbit-style coverage with per-file sub-agents, full scanner batteries, inline comments, and nitpicks, use `deep-review` instead.

## Use Cases

```bash
/code-review https://github.com/OWNER/REPO/pull/123
/skill:code-review https://github.com/OWNER/REPO/pull/123
Review PR #123 quickly
Review the current branch against main
Do a security-focused light review of this PR
Review these local changes but do not post to GitHub
```

## Principles

- Prioritize bugs, security issues, data loss, regressions, broken edge cases, API compatibility issues, and missing tests with clear risk.
- Aim for the top 1-3 material findings. Cap the report at 3 findings unless additional clear Critical or High issues are present.
- Prefer false negatives over noisy findings. Do not report speculative issues without concrete evidence from the diff or surrounding code.
- Do not nitpick. Skip naming, formatting, import order, wording, docs, and micro-refactors unless an explicit project rule makes them merge-blocking.
- Do not fan out sub-agents or run the `deep-review` workflow from this skill.
- Be specific and actionable. Every finding should include the exact file/location, impact, and a concrete fix.
- Review only by default. Do not edit code unless the user explicitly asks you to fix the issues.
- Treat a direct GitHub PR URL as permission to post the completed review back to that PR, unless the user says not to post.
- Keep local branch reviews, file-only reviews, and non-URL PR references terminal-only unless the user explicitly asks to post.
- User wording such as "do not post", "review only", "don't comment", or "terminal only" overrides any posting permission.

## Workflow

Follow this process for every review.

### Phase 1: Establish the Review Target

Determine both the review target and the output destination. Review targets can be:

1. A GitHub PR, e.g. `PR #123`
2. The current branch against a base branch, usually `main` or `master`
3. Uncommitted local changes
4. A specific set of files

Output destination rules:

1. Direct GitHub PR URL, e.g. `https://github.com/OWNER/REPO/pull/123` — post one PR comment by default.
2. GitHub PR number or shorthand, e.g. `PR #123` — print to terminal unless the user explicitly asks to post.
3. Local branch, uncommitted, or file-only review — print to terminal unless the user explicitly asks to post and provides a PR target.
4. Any explicit "do not post" wording — print to terminal only.

For direct GitHub PR URLs with posting enabled, run `gh auth status` before resolving PR metadata. If `gh` is unavailable or auth fails, mark posting unavailable, continue terminal-only when the PR diff can still be gathered, and include the failure reason with the terminal review.

For GitHub PRs, gather PR metadata and diff with `gh` when available. Use the PR URL when one was provided:

```bash
gh auth status
gh pr view <url-or-number> --json title,body,author,baseRefName,headRefName,files,commits,url
gh pr diff <url-or-number>
```

For local branch reviews, inspect the merge base and diff:

```bash
git status --short
git branch --show-current
git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main
git diff <merge-base>...HEAD
```

Adjust the base branch if the repository uses a different default branch.

### Phase 2: Gather Focused Project Context

Read the changed files and only enough surrounding code to validate likely impact. Check project standards in this priority order:

1. `REVIEW.md` in the target repository root, if present
2. `CLAUDE.md`, `.claude.md`, or equivalent agent instructions
3. `CONTRIBUTING.md`, coding standards, architecture docs, ADRs
4. Package/tooling files such as `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, etc.
5. Existing nearby tests and similar implementations

Treat the target repo's `REVIEW.md` as the highest-priority review rules.

If this skill's bundled reference files are available, use them as support material:

- `REFERENCE.md` — examples, output templates, severity guidance
- `PROJECT_REVIEW_TEMPLATE.md` — starter `REVIEW.md` users can copy into a project

### Phase 3: Run Available Checks

Run only cheap, already-configured checks that are likely to finish quickly and directly cover the changed area:

- Type checks
- Unit tests for changed areas
- Linters/format checks

Do not install tools, invoke one-shot package downloads, run broad scanner batteries, or run expensive full-suite checks by default. If the right check is too expensive or unavailable, note that it was not run and continue with manual review.

### Phase 4: Analyze in Order

Analyze the change in this order, stopping once the highest-signal issues are identified:

1. **Intent** — What is the PR/change trying to accomplish?
2. **Correctness** — logic errors, invalid assumptions, broken edge cases, race conditions, bad state transitions
3. **Security** — auth/authz, injection, unsafe input handling, secrets, SSRF, XSS, unsafe deserialization, sensitive logging
4. **Reliability** — error handling, retries, idempotency, null/undefined handling, resource cleanup
5. **Data & API compatibility** — migrations, schema changes, response shapes, backwards compatibility
6. **Testing** — missing coverage for new logic, regression tests, edge cases, integration boundaries
7. **Performance** — N+1 queries, hot path regressions, unnecessary expensive work
8. **Maintainability** — only concrete complexity or inconsistency likely to cause bugs

For large PRs, inspect the highest-risk files first and sample enough of the rest to catch obvious blockers. If the change is too large for a meaningful light review, say so briefly and recommend `/deep-review` for exhaustive coverage.

Suppression rules:

- Omit Low/Nit findings by default.
- Report missing tests only when a specific new behavior or regression risk clearly needs coverage.
- Do not report issues that require assumptions about undocumented product requirements.
- Do not summarize long lists of minor issues; leave them for `deep-review`.

## Severity Scale

- **Critical** — security vulnerability, data loss, production crash, auth bypass, major regression
- **High** — logic bug, missing critical error handling, broken feature, serious performance issue
- **Medium** — missing test with concrete regression risk, maintainability risk likely to cause future bugs, minor behavior issue
- **Low/Nit** — normally out of scope for `code-review`; use only for explicit project-rule violations that should block merge

Rule of thumb: if you would not block a real merge for it, do not mark it Medium or higher.

## Output Format

Start with a short overall assessment. Then list findings from highest to lowest severity. Keep the report concise: 0-3 findings is the expected result for most reviews.

For every issue, use this format:

````markdown
## [Severity] Issue: [Short descriptive title]

**File:** `path/to/file.ext:line-range`
**Category:** Bug | Security | Logic | Reliability | Maintainability | Testing | Performance | Style

**Problem:**
[Clear 1-2 sentence explanation of what is wrong and why it matters.]

**Impact:**
[Specific consequence if this is not fixed.]

**Suggested Fix:**
```diff
[Exact unified diff, or a precise before/after code block if a diff is not practical.]
```

**Handoff Prompt:**
```
In the file `path/to/file.ext`, around lines X-Y:

[Detailed, self-contained instruction explaining the exact change needed, why it is required, edge cases to consider, and how to verify it. Reference relevant project patterns if applicable.]

Only modify the necessary lines. Keep unrelated code unchanged.
```
````

After all issues, include:

```markdown
### PR Summary
[2-4 sentence overview of the change and overall assessment.]

### Recommendations
- [ ] Highest-priority fixes before merge
- [ ] Tests to add or run
- [ ] Optional improvements

### Statistics
- Files changed: X
- Issues found: Y (Critical: A, High: B, Medium: C, Low: D)
- Checks run: [commands or "not run"]
```

If no issues are found, say so clearly and include a brief positive summary of what looked good.

## GitHub PR Posting

When posting is permitted, use one normal PR comment by default. Do not create inline comments unless the user explicitly asks for them.

Posting workflow:

1. Run `gh auth status`.
2. If auth fails or `gh` is unavailable, print the full review to the terminal and include the failure reason.
3. Resolve PR metadata with `gh pr view <url-or-number> --json title,body,author,baseRefName,headRefName,files,commits,url`.
4. Generate the same findings and overall assessment you would produce for a terminal review.
5. Write the GitHub comment body to a temporary Markdown file.
6. Post with `gh pr comment <url-or-number> --body-file <tmp-review.md>`.
7. If posting fails, print the full review to the terminal and include the posting error.

The posted comment must include the summary and statistics at the top, followed by one collapsible `<details>` section per finding. Each `<summary>` line must use:

```markdown
[Severity] File:line - issue title
```

Each details section must include the problem, impact, suggested fix, and handoff prompt. See `REFERENCE.md` for the exact GitHub comment template and fallback commands.

For terminal-only reviews, use the standard output format above.
