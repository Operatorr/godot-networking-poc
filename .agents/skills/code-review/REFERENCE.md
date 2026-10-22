# Code Review Report

Use this structure for local output and the single GitHub summary comment. Findings belong to separate axes; severity definitions live in [SKILL.md](SKILL.md). List verified Low findings individually after higher-severity findings within each axis, marked non-blocking by default. Preserve their evidence, consequence, fix direction, and verification scenario; do not suppress them under a Medium cutoff. Nit findings are excluded.

Keep coverage concise but substantive: name the scenarios examined, not just how many tests passed.

```markdown
# Code Review

Scope: <base/merge-base SHA> → <head SHA>, or captured local snapshot.
Comparison: <merge-base/direct/uncommitted/file-only>; <included/excluded changes>.
Review mode: independent Standards/Spec reviewers plus main Bugs reviewer, or disclosed fallback.

## Bugs
<Findings ordered by severity, or no confirmed findings within reviewed scope.>

## Standards
<Findings, or none confirmed; name rule sources and any heuristic fallback.>

## Spec
<Findings, or none confirmed, or no spec available; name requirement sources.>
<Compact requirement map, including partial/unclear coverage.>

## Coverage and limits
- Files: <reviewed count>/<total>; <excluded/unreviewed paths and reasons>.
- Behavior traces: <entry point, ordinary/adverse inputs, result, evidence locations; partial setup and cleanup failure where applicable>.
- Final adversarial check: <distinct scenario, result/evidence, or why none remains>.
- Contracts/callers: <symbols and actual consumer paths inspected>.
- Checks: <commands, pass/fail/not run and reasons; baseline vs new failures>.
- Open questions / coverage gaps: <unreviewed paths/behavior families, reason, and highest-risk next trace, or none>.

## Worst issue per axis
- Bugs: <finding ID/severity, none confirmed, or incomplete>.
- Standards: <finding ID/severity, none confirmed, or incomplete>.
- Spec: <finding ID/severity, none confirmed, no spec available, or incomplete>.
```

## Finding shape

```markdown
### B1 — [High] Retried request applies the credit twice

**Location:** `src/credits.ts:80-86` (reviewed head).
**Evidence and trigger:** <request/event sequence; code trace and base/head causal link>.
**Expected / actual:** <invariant or requirement versus observable behavior>.
**Impact:** <who is affected and how>.
**Fix direction:** <specific local remedy consistent with surrounding code>.
**Verify:** <regression scenario and expected assertion; distinguish executed from proposed>.
```

Use `B`, `S`, and `P` identifiers for Bugs, Standards, and Spec. Standards findings also quote a rule with `path:line` or identify a smell as a judgement call with concrete evidence. Spec findings quote a requirement with `path:line` or a source URL and anchored quote. Cross-reference duplicate root causes rather than counting them twice. Use the shortest location range that identifies the cause; cite other files in the evidence.

For GitHub, keep the scope, coverage, and per-axis conclusions visible; wrap individual findings in `<details>` under their respective axis:

```markdown
<details>
<summary>B1 — [High] src/credits.ts:80 — Retried request applies the credit twice</summary>

<Full finding body.>

</details>
```

No findings is an outcome, not a reason to omit the three axes or coverage. For example, `cancel while save is pending → late response ignored by request-id guard at editor.ts:144` is useful negative evidence. `All categories checked; 353 tests pass` does not show what behavior was reviewed.

## Delivery

When posting is authorized by the skill/user, check authentication, write the complete body to a unique temporary Markdown file, and post once:

```bash
gh auth status
gh pr comment <pr-url> --body-file <temporary-markdown-path>
```

Use a file-writing tool or properly quoted heredoc for the body; do not interpolate Markdown into shell arguments. Return the comment URL on success. On failure, preserve the review locally and show the actual error. Never substitute an approval or multiple inline threads for the one-comment output.
