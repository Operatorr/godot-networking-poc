# Deep Review Reference

Supporting templates and commands for the `deep-review` skill. See also `SUBAGENT_PROMPT.md` (per-file fan-out prompt) and `TOOL_BATTERY.md` (linter/SAST/secret matrix).

## Shared finding record

Both sub-agent findings and normalized tool findings use this shape so Phase 5 can merge them mechanically:

```text
path: <file>
line: <line or range>
severity: Critical | High | Medium | Low | Nitpick
category: Correctness | Security | Reliability | Data/API | Tests | Performance | Maintainability | Style | Docs | Grammar
title: <short>
problem: <1–2 sentences>
impact: <concrete consequence>
fix: <unified diff or before/after>
confidence: high | medium | low
source: llm | <tool name>
confirmed_by_tool: true | false
cross_file_refs: <symbols/callers, or none>
```

## Terminal per-finding format

````markdown
## [Severity] Issue: [Short descriptive title]

**File:** `path/to/file.ext:line-range`
**Category:** Correctness | Security | Reliability | Data/API | Tests | Performance | Maintainability | Style | Docs | Grammar
**Source:** LLM | <tool> (confirmed-by-tool when both)

**Problem:**
[1-2 sentences: what is wrong and why it matters.]

**Impact:**
[Specific consequence if unfixed.]

**Suggested Fix:**
```diff
[Exact unified diff, or precise before/after.]
```

**Handoff Prompt:**
```
In the file `path/to/file.ext`, around lines X-Y:

[Self-contained instruction: the exact change, why it is required, edge cases, and how to verify it.]

Only modify the necessary lines. Keep unrelated code unchanged.
```
````

Order findings Critical → High → Medium → Low → Nitpick, then by file and line. Every Low and Nitpick gets its own entry — never summarized away.

## Terminal closing blocks

```markdown
### PR Summary
[2-4 sentence overview and overall assessment.]

### Recommendations
- [ ] Blocking fixes (Critical/High)
- [ ] Tests to add or run
- [ ] Nitpick cleanup (optional)

### Statistics
- Files changed: X
- Sub-agents run: N (waves: W)
- Issues found: Y (Critical: a, High: b, Medium: c, Low: d, Nitpick: e)
- Tools run: [tool: passed | failed | skipped (reason), ...]
- Tool-confirmed findings: Z
```

## GitHub summary comment template

One comment. Blocking/notable findings expanded individually; Low/Nitpick wrapped in a single outer collapsed section (CodeRabbit-style).

````markdown
# Deep Review

[Overall assessment: mergeable / blocking issues / needs follow-up.]

### Statistics
- Files changed: X | Sub-agents: N (waves W) | Tools: [list]
- Issues: Y (Critical a, High b, Medium c, Low d, Nitpick e) | Tool-confirmed: Z

### Blocking & Notable Findings

<details>
<summary>[Severity] path/to/file.ext:line - short title</summary>

**Category:** ...
**Source:** ...

**Problem:** ...

**Impact:** ...

**Suggested Fix:**
```diff
...
```

**Handoff Prompt:**
```text
...
```
</details>

### 🪶 Nitpicks & minor issues (d + e)

<details>
<summary>Click to expand low-severity findings</summary>

<details>
<summary>[Low] path:line - title</summary>

**Problem:** ...
**Suggested Fix:**
```diff
...
```
</details>

<details>
<summary>[Nitpick] path:line - title</summary>

**Problem:** ...
</details>

</details>
````

If a tier is empty, omit its section. Never omit a finding to shorten the comment — collapse it instead.

## GitHub inline review (default for PR-URL posting)

Post one review carrying a `comments` array so each finding lands on its line. Build the payload as JSON and pipe it to `gh api --input -`.

```bash
gh auth status  # bail to terminal output on failure

cat > /tmp/deep-review-payload.json <<'JSON'
{
  "event": "COMMENT",
  "body": "# Deep Review\n\n<summary + statistics — same content as the summary comment>",
  "comments": [
    { "path": "src/file.ts", "line": 42, "side": "RIGHT", "body": "[High] Missing null check — ..." },
    { "path": "src/file.ts", "start_line": 88, "line": 91, "side": "RIGHT", "body": "[Medium] ..." }
  ]
}
JSON

gh api repos/OWNER/REPO/pulls/<number>/reviews \
  -X POST --input /tmp/deep-review-payload.json
```

Rules:

- Each comment's `line` (and `start_line` for ranges) must fall inside a diff hunk for that file, or GitHub rejects the whole review. Validate every finding's line against the Phase 1 `hunk_ranges`; **demote out-of-hunk findings into the summary comment** instead of inlining them.
- `side: RIGHT` targets the new version of the file (use `LEFT` only for deleted lines).
- The review `body` repeats the summary + statistics so nothing is lost if a reader sees only the summary.
- "Summary only" requested → skip the inline review, post only the summary comment with `gh pr comment <url-or-number> --body-file <tmp.md>`.

## Auth & fallback commands

```bash
command -v gh
gh auth status
```

Terminal fallback when `gh` is missing or unauthenticated, or when posting fails — print the full review with the reason:

```bash
tmp_review="$(mktemp -t deep-review.XXXXXX.md)"
# Write the full review markdown to "$tmp_review" first.
if ! command -v gh >/dev/null 2>&1; then
  printf 'GitHub posting skipped: gh is not installed.\n\n'; cat "$tmp_review"
elif ! gh auth status 2>/tmp/deep-review-gh.err; then
  printf 'GitHub posting skipped: gh auth failed.\n'; cat /tmp/deep-review-gh.err; printf '\n\n'; cat "$tmp_review"
fi
```

## Pitfalls to avoid

- Do not let thoroughness become vagueness — every finding still needs an exact location and a concrete fix.
- Do not collapse the Nitpick tier into a count; collapse it into a `<details>`, but list each item.
- Do not run any tool with `--fix`/`--write`, and do not run global installs without asking.
- Do not inline a comment on a line outside a diff hunk — it rejects the entire review payload.
- Do not skip Phase 6 on a non-trivial PR; a suspiciously low count is usually under-reporting, not a clean PR.
- Do still say what is good. Even an exhaustive review benefits from noting solid patterns.
