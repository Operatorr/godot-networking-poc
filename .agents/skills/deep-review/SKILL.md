---
name: deep-review
description: Perform a maximally thorough, CodeRabbit-style code review that fans out one focused sub-agent per changed file, runs every available linter/SAST/secret scanner, and reports every issue down to nitpicks. Use for /deep-review or when the user asks for a deep, exhaustive, thorough, or nitpick-level review, a CodeRabbit-style review, to "find everything", to "leave no stone unturned", or wants maximum coverage on a PR or branch. Optimizes for recall; some noise is acceptable. For a fast, conservative, senior-engineer review that flags only what matters, use code-review instead.
---

# Deep Review

Review code like a relentless automated reviewer. Fan out a fresh, focused sub-agent for every changed file so no file inherits the leftover attention of a single pass, run every deterministic check available, resolve cross-file impact, and surface every finding from Critical down to Nitpick.

This skill optimizes for **recall, not precision**. Some noise is expected and acceptable. For a fast, low-noise review, use the `code-review` skill instead — `deep-review` is its thorough counterpart.

## Use Cases

```bash
/deep-review https://github.com/OWNER/REPO/pull/123
Exhaustively review PR #123 — find everything
/skill:deep-review https://github.com/OWNER/REPO/pull/123
CodeRabbit-style deep review of the current branch
Thorough review of this PR with inline comments
Nitpick-level review of these local changes, terminal only
```

## Principles

- **Recall over precision.** 10–15+ findings on a non-trivial PR is normal and healthy. Under-reporting is the failure mode to avoid. Let severity tiers — not omission — communicate importance.
- **Do nitpick.** Naming, formatting not covered by a formatter, import order, magic values, doc/comment quality, and grammar are all in scope and belong in the Nitpick tier.
- **Report low-severity findings individually.** Never collapse, summarize, or count-away Low/Nitpick issues. Every finding gets its own entry.
- **Fresh attention per file.** Never rely on one holistic pass. Each changed file (or small batch) gets a dedicated sub-agent with the full checklist, so no file inherits "salience collapse" from earlier files.
- **Run every available deterministic check.** Linters, type-checkers, SAST, secret scanners, and prose linters are first-class inputs, not optional. Prefer one-shot runners (`npx --yes`, `uvx`) so "not installed" rarely means "skipped".
- **Be specific and actionable.** Thoroughness must not mean vagueness. Every finding includes the exact file/location, impact, and a concrete fix.
- **Review only by default.** Do not edit code unless the user explicitly asks you to fix the issues.
- **Posting rules (same as `code-review`):** A direct GitHub PR URL grants permission to post. PR numbers, branch reviews, file-only reviews, and local reviews are terminal-only unless the user explicitly asks to post. Any "do not post", "review only", or "terminal only" wording overrides everything.

> **Explicitly do NOT apply `code-review`'s suppression rules here.** Do not "summarize lower-severity patterns" and do not apply "if you would not block a real merge for it, do not mark it Medium or higher." Report everything; tier it honestly.

## Workflow

Follow every phase for each review.

### Phase 0: Establish Target & Output Destination

Determine the review target (a GitHub PR, the current branch vs a base, uncommitted changes, or a specific set of files) and the output destination.

Output destination rules (identical to `code-review`):

1. Direct GitHub PR URL (`https://github.com/OWNER/REPO/pull/123`) — post by default.
2. PR number or shorthand (`PR #123`) — terminal only unless the user asks to post.
3. Local branch, uncommitted, or file-only review — terminal only unless the user asks to post and provides a PR target.
4. Any "do not post" / "terminal only" wording — terminal only.

For a direct PR URL with posting enabled, the **default posting style is CodeRabbit-style: inline review comments anchored to lines plus one summary comment.** Resolve an `inline` flag: on by default for PR-URL posting; the user can request "summary only" (no inline) or "terminal only".

### Phase 1: Gather the Diff & Build the Changed-File Manifest

For GitHub PRs, run `gh auth status` first, then gather metadata and diff:

```bash
gh pr view <url-or-number> --json title,body,author,baseRefName,headRefName,files,commits,url
gh pr diff <url-or-number>
```

For local branches:

```bash
git status --short
git branch --show-current
git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main
git diff <merge-base>...HEAD --name-status
git diff <merge-base>...HEAD
```

Adjust the base branch if the repo's default is not `main`/`master`.

Build a **changed-file manifest**. For each changed file, record:

- `path`
- `change_type` (added / modified / deleted / renamed)
- `language` (from extension)
- `hunk_ranges` — the changed line ranges parsed from each `@@ -a,b +c,d @@` header

Keep the `hunk_ranges` — Phase 7 reuses them to validate that inline comments land inside a diff hunk (GitHub rejects out-of-hunk inline lines).

### Phase 2: Build the Repo-Context Packet

Read project standards in this priority order (highest first):

1. `REVIEW.md` in the target repo root
2. `CLAUDE.md`, `.claude.md`, or equivalent agent instructions
3. `CONTRIBUTING.md`, coding standards, architecture docs, ADRs
4. Package/tooling manifests (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, …)
5. Nearby tests and similar implementations

Treat the target repo's `REVIEW.md` as the highest-priority rules.

Assemble one compact **context packet** to hand to every sub-agent (a cheap stand-in for whole-repo indexing):

- **Standards digest** — key rules extracted from `REVIEW.md` / `CLAUDE.md` / `CONTRIBUTING.md`.
- **Stack summary** — languages, frameworks, test runner, lint configs present.
- **Conventions digest** — naming, error-handling, and test patterns observed in nearby files.
- **Symbol/caller index** — for each exported or imported symbol touched by the diff, the grep-derived list of other files referencing it, so each per-file agent knows its blast radius. Build with read-only `git grep` scoped to symbols appearing in the diff.

### Phase 3: Run the Tool Battery

Detect languages/file types from the manifest and run every matching available linter, type-checker, SAST scanner, secret scanner, and prose linter. See `TOOL_BATTERY.md` for the full detection-and-runner matrix and the install policy.

Policy summary:

- Prefer one-shot runners (`npx --yes …`, `uvx …`, `docker run …`). These are ephemeral and run without asking.
- Never run a global install (`npm i -g`, `pip install`, `brew install`, `go install`) without explicit permission. If declined, mark the tool `skipped (not installed)` in statistics and continue.
- Check mode only — never `--fix` / `--write`. This skill reviews; it does not edit.
- Scope runs to changed paths where the tool supports it.

Normalize every tool result into the shared finding shape (see `REFERENCE.md`): `path`, `line`, `category`, `rule_id`, `message`, `source: <tool>`.

### Phase 4: Fan Out Per-File Review Sub-Agents

This is the structural core of the skill. Partition the manifest into review tasks and dispatch them.

**Task split:**

- One file = one task by default.
- **Batch** tiny files (each under ~40 changed lines) so one sub-agent handles up to ~5 files or ~400 total changed lines.
- **Split** any file with more than ~600 changed lines into multiple hunk-range tasks so no agent reviews more than it can hold with fresh attention. (Large means *more* agents, not fewer findings.)
- **Skip** lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `poetry.lock`, `go.sum`), pure deletions, and generated/vendored paths — no LLM agent (tools may still scan them).

**Dispatch:** run sub-agents (the Agent tool, read-only) in **parallel waves of up to 5**. Dispatch a wave, wait for it to return, dispatch the next, until the task list is exhausted.

**Each sub-agent receives** (assemble the prompt from `SUBAGENT_PROMPT.md`):

1. Its assigned file path(s) and changed line ranges.
2. The file's diff hunks.
3. The Phase 2 context packet.
4. Any Phase 3 tool findings already scoped to its file(s) — to confirm/expand, not miss.
5. The full category checklist (see below).
6. Anti-collapse instructions and the fixed output schema (both in `SUBAGENT_PROMPT.md`).

### Phase 5: Aggregate, Ground & Dedupe

Collect all sub-agent findings plus all normalized tool findings into one list keyed by `(path, line-range, category)`. Then:

1. **Dedupe** in three layers:
   - Exact/near-exact location + same category → keep the richer entry.
   - Tool-vs-LLM overlap (same defect, same place) → merge into one entry tagged `confirmed-by-tool` (raises confidence).
   - Same root cause reported from multiple call sites → merge with an "also affects" list.
2. **Resolve cross-file context** — for each finding carrying `cross_file_refs`, read/grep the referenced call sites to confirm impact. A changed signature that breaks an unseen caller becomes its own High finding.
3. **Normalize severity** — sub-agent severities are advisory; assign final tiers consistently across the whole report.
4. **Order** findings Critical → High → Medium → Low → Nitpick, then by file and line.
5. **Count** per-tier totals. Do **not** drop or summarize the Low/Nitpick tiers.

### Phase 6: Self-Critique Re-Scan

Before producing output, run a structured re-scan (read-only):

1. **Coverage matrix** — build a `(changed file) × (category)` grid. Re-examine any empty cell for a substantial file ("file X produced zero findings — re-read it for tests, docs, nitpicks"; "no Security findings anywhere — re-scan auth/input/secret surfaces").
2. **Tool reconciliation** — confirm every tool that ran was folded in and listed in statistics; none silently dropped.
3. **Cross-file completeness** — confirm every `cross_file_refs` was resolved and every signature/contract change has a finding.
4. **Count sanity check** — on a non-trivial PR, a low total with a near-empty Nitpick tier signals under-reporting; re-run a targeted nitpick/docs/grammar pass over the largest changed files.

Merge any new findings through Phase 5's dedupe.

### Phase 7: Output

Produce the terminal report (always) and, when posting is permitted, the GitHub output. See the Output Format and GitHub Posting sections below, with full templates in `REFERENCE.md`.

## Category Checklist

Every sub-agent applies all of these. Categories 8–10 are exactly what `code-review` suppresses — here they are required.

1. **Correctness** — logic errors, wrong assumptions, off-by-one, broken edge cases, race conditions, bad state transitions, incorrect error propagation.
2. **Security** — auth/authz, injection, unsafe input, secrets, SSRF, XSS, unsafe deserialization, sensitive logging, insecure defaults.
3. **Reliability** — error handling, retries, idempotency, null/undefined handling, resource cleanup, timeouts, partial-failure behavior.
4. **Data & API compatibility** — migrations, schema changes, response-shape changes, backward compatibility, contract drift.
5. **Tests** — missing coverage for new logic, missing regression/edge-case tests, weak assertions, untested error paths, flaky patterns.
6. **Performance** — N+1 queries, hot-path regressions, unnecessary allocations/work, missing pagination/batching, sync work in async paths.
7. **Maintainability** — complexity, duplication, poor naming, inconsistency with project patterns, dead code, leaky abstractions.
8. **Style / Nitpicks** — naming conventions, formatting not auto-fixed, import ordering, magic values, redundant code, micro-clarity. Report individually.
9. **Docs & comments** — missing/stale doc comments on new public APIs, misleading comments, missing README/changelog updates when the project expects them.
10. **Grammar & prose** — typos and grammar in comments, log/error/UI strings, and markdown.

## Severity Scale

- **Critical** — security vulnerability, data loss, production crash, auth bypass, major regression, leaked secret.
- **High** — logic bug, missing critical error handling, broken feature, serious performance issue, breaking API/contract change.
- **Medium** — missing test, maintainability risk, code smell likely to cause future bugs, minor behavior issue.
- **Low** — small clarity issue, local style/consistency problem, doc gap.
- **Nitpick** — purely cosmetic: naming preference, formatting, grammar/typo, micro-refactor suggestion.

Emit one entry per Low and per Nitpick finding. The statistics block must show the Nitpick count, and the report must list every Low/Nitpick item (collapsed for GitHub, never dropped).

## Output Format

Start with a short overall assessment, then list findings highest to lowest severity (all tiers present). Use the per-finding format and closing blocks (PR Summary, Recommendations, Statistics) defined in `REFERENCE.md`. The statistics block must report files changed, sub-agents/waves run, issues per tier (incl. Nitpick), tools run with pass/fail/skipped, and the tool-confirmed count.

If no issues are found at any tier, say so clearly — but on a non-trivial PR treat that as a signal to re-run Phase 6 before concluding.

## GitHub PR Posting

When posting is permitted, default to **inline comments + a summary comment** (see `REFERENCE.md` for exact commands and the JSON payload recipe).

1. Run `gh auth status`. On failure or `gh` missing, print the full review to terminal with the reason.
2. **Summary comment** — one comment with the overall assessment and statistics, each blocking/notable finding (Critical/High/Medium) in its own `<details>`, and a single outer collapsed `🪶 Nitpicks & minor issues` `<details>` wrapping each Low/Nitpick finding individually.
3. **Inline review** — one review via `gh api repos/OWNER/REPO/pulls/<n>/reviews` with `event=COMMENT` and a `comments` array, each comment anchored to a line. Build the payload as JSON and post with `gh api … --input <payload>`. Validate each finding's line against the Phase 1 hunk ranges; demote any out-of-hunk finding into the summary comment. The review `body` repeats the summary + statistics so nothing is lost if a reader sees only the summary.
4. If the user asked for "summary only", post the summary comment alone. If posting fails, print the full review to terminal with the error.
