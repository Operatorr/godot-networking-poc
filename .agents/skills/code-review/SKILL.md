---
name: code-review
description: "Review PRs, branch diffs, and uncommitted changes for concrete bugs, repository standards, and spec compliance using bounded independent review axes. Use for /code-review and normal review requests. Use deep-review for exhaustive per-file delegation, scanner batteries, and nitpick coverage."
---

# Code Review

Find actionable faults without the cost of an exhaustive audit. Review three separate axes: **Bugs**, **Standards**, and **Spec**. The main reviewer owns Bugs and validates findings; at most two independent sub-agents own Standards and Spec. Passing tests are supporting evidence, never a substitute for tracing behavior.

## Boundaries

- Review only unless the user asks for fixes. Do not merge as part of review unless separately requested.
- Report all supported Critical, High, and Medium findings, without a count target. Zero findings is valid after completing coverage. Skip cosmetic preferences and linter-enforced style.
- One review round, at most two children, no recursive delegation, no per-file fan-out. Do not automatically invoke `deep-review` or repeat until clean.
- Use configured, focused checks. No tool installations, broad scanner batteries, or expensive full suites by default. Spend effort on reachable failure scenarios and cross-file contracts.
- A direct GitHub PR URL permits one summary comment unless the user says "do not post", "review only", "don't comment", or "terminal only". PR numbers, branches, and local files remain terminal-only unless posting is explicitly requested. Children never post.

## 1. Pin the target and scope

Determine whether the user wants a PR, a branch comparison, uncommitted work, or named files. Never silently substitute one for another.

For a PR, resolve its URL, body, linked issues, base/head refs and SHAs, changed files, and commits using the host tools or `gh pr view`. Fetch/read the exact reviewed revisions; the current checkout may belong to another branch. Register the PR with thread-linking tools when available. Read the diff and surrounding source from the same snapshot.

For a branch comparison, use the user's fixed point. If neither the user nor PR metadata supplies a base, ask for it rather than guessing `main`. Resolve refs before delegation:

```bash
git rev-parse --verify '<fixed-point>^{commit}'
git rev-parse --verify 'HEAD^{commit}'
git merge-base <resolved-base-sha> <resolved-head-sha>
git diff --name-status <merge-base-sha> <head-sha>
git diff <merge-base-sha> <head-sha>
```

State that this compares from the merge base, equivalent to `<fixed-point>...HEAD`, and excludes staged and unstaged changes. Honor an explicitly requested direct/two-dot comparison instead.

For uncommitted work, inspect staged and unstaged diffs and untracked files (`git status --short`, `git diff HEAD`, and reads of relevant untracked files). Record HEAD and the captured patch/file contents so reviewers examine the same version. For file-only review, record paths and note when no baseline exists, so pre-existing issues cannot be distinguished.

Stop on an invalid ref or empty requested diff before spawning reviewers. Do not discard local edits or switch a dirty checkout to gather a PR. If the target changes during review, disclose the reviewed snapshot and remaining delta; do not claim the latest revision was reviewed.

Build a file manifest including modifications, additions, deletions, and renames. Record exclusions explicitly. Generated/vendor/lockfile churn may be excluded from line-by-line reading, but inspect dependency/version changes, generated contracts, and removed consumers when behavior depends on them.

**Complete when:** the exact scope, snapshot, comparison mode, and output destination are known.

## 2. Gather evidence and dispatch independent axes

Read applicable agent instructions and repo review rules (`REVIEW.md`), standards (`CODING_STANDARDS.md`, `CONTRIBUTING.md`), architecture/ADRs, and package/test configuration. Repo-specific rules override generic heuristics, subject to higher-priority instructions. Cite source paths and lines rather than handing reviewers only a paraphrased digest.

Find the spec from an explicit user path/link first, then the PR body and linked issues, commit issue references via the configured tracker, and matching documents under `docs/`, `specs/`, or `.scratch/`. Use actual requirement text, not requirements inferred from the implementation. Distinguish binding requirements from discussion or proposals. If sources conflict, report the ambiguity instead of choosing silently. If none is available, mark Spec **no spec available** and skip that child; do not block the bug review.

Build a compact context packet: pinned snapshot and how to read it, diff/manifest, source locations for rules and requirements, relevant tooling, and changed public/shared contracts. Do not include the author's reasoning, your suspected findings, or the other reviewer's conclusions.

Read [AXIS_PROMPTS.md](AXIS_PROMPTS.md) and launch one Standards reviewer and, when a spec exists, one Spec reviewer using those briefs. Prefer fresh contexts without inherited authoring history. Each reads source and returns findings plus coverage. Run them concurrently with the main bug review, within tool concurrency limits. If delegation is unavailable, perform separate passes yourself and disclose that they were not independent.

**Complete when:** each available axis has its own evidence-based brief; a missing spec is explicit.

## 3. Hunt behavioral faults

Read every changed first-party file, including deleted code and its surviving consumers. Read small files fully; for large files, read complete changed functions, relevant callers/callees, and enclosing state/cleanup logic. Prioritize risky paths but do not silently sample the rest.

Organize the review around **changed behaviors**, not a checklist tick per file. For each behavior:

1. Identify the entry point, valid inputs, intended invariant, and observable result.
2. Trace at least one ordinary path and a plausible failure/boundary path through the actual implementation. Record the input or event sequence and file/line evidence. For a non-behavioral change, record why no execution trace applies.
3. Follow changed signatures, return shapes, schemas, defaults, and semantics to callers and producers outside the diff. Search usages, then read them; a search hit is not caller verification. Check old data/clients and rolling deployment compatibility where relevant.
4. Compare base and head to establish whether the patch introduces or exposes the defect. Do not label unrelated pre-existing debt as a regression.
5. Read tests for those paths: inspect assertions, mocks, fixtures, and omitted branches. Ask what realistic input would fail despite the current tests passing.

Use the applicable fault probes below to choose counterexamples, not to manufacture findings:

- **Boundaries and logic:** absent versus empty versus zero/false, first/last item, inclusive/exclusive bounds, duplicate identifiers, ordering, units/timezones, parser/serializer round trips.
- **State and concurrency:** stale responses, duplicate events/retries, concurrent writers, interrupted transitions, cache invalidation, reset/unmount cleanup, transaction boundaries and partial writes. Trace a concrete interleaving when relevant.
- **Trust boundaries:** follow untrusted data to sensitive operations; verify object/tenant ownership, server-side authorization, injection protection, and data returned/logged. Confirm upstream guards before claiming they are missing.
- **Failures and resources:** rejected dependencies, timeout/cancellation, rollback, leaked listeners/connections, swallowed errors, and whether retry repeats a side effect.
- **Compatibility and scale:** old records/payloads, migrations/defaults, removed exports/routes/configuration, pagination, bounded memory, and query/work growth on a reachable hot path.
- **User-visible behavior:** loading/empty/error states, navigation, input and accessibility behavior when touched; inspect the rendered UI when needed to substantiate a visual claim.

Keep a compact internal coverage ledger: `behavior → files/callers → normal case → adverse case → evidence/result → gaps`. Checklists and test counts alone do not satisfy it. If scale or missing infrastructure prevents full coverage, record the actual unreviewed areas and deliver a partial review; recommend deep review for those areas without launching it.

Run targeted configured checks after identifying the important scenarios, or concurrently if they do not interfere. Prefer a focused reproduction when a candidate is uncertain; use a temporary location or isolated checkout for probes, without modifying the user's working tree. Do not require an executable test when a complete source trace proves the fault. Distinguish baseline/environment failures from failures caused by the patch.

**Complete when:** every in-scope changed behavior has a trace or an explicit gap, and affected contracts have been checked at their consumers.

## 4. Verify candidates and close coverage

Treat all findings, including child output and check failures, as hypotheses until verified:

- Re-read the exact reviewed lines and relevant guard/caller. Try to disprove the claim: can the input reach this path, does another layer handle it, is the behavior deliberate, or does the spec permit it?
- Require a concrete trigger, expected versus actual behavior (or cited rule/requirement breach), observable consequence, and a local fix direction. Do not invent precise patches against unread code.
- For Bugs, establish the changed-code causal link. For Standards, verify the quoted rule applies; label smell-based observations as judgement calls. For Spec, verify the requirement citation and implementation trace.
- Separate unresolved potentially material concerns into **Open questions / coverage gaps**, with the missing evidence. Do not present them as confirmed bugs or silently turn uncertainty into a clean verdict.
- Deduplicate the same root cause. If it affects multiple axes, put the full finding in its primary axis and cross-reference it in the others; preserve each axis's conclusion.

Before a zero-finding conclusion, challenge the highest-risk changed behavior with one additional counterexample not covered by its existing tests. Record the scenario and result. This is one bounded adversarial check, not a loop driven by finding count.

**Complete when:** candidates are confirmed, rejected with evidence, or explicitly unresolved; every manifest entry is accounted for. A partial or blocked axis cannot be reported as clean.

## 5. Report and deliver

Read [REFERENCE.md](REFERENCE.md) for the compact report and posting template. Keep **Bugs**, **Standards**, and **Spec** as separate sections, ordered by severity within each. Close with the worst confirmed issue **per axis**, or `none confirmed`, `no spec available`, or `incomplete` as applicable. Do not blend the axes into an overall score or let one passing axis cancel another's failure.

Each finding includes severity, exact path/lines, evidence, trigger/consequence, fix direction, and how to verify. Quote the rule or requirement for Standards/Spec. A suggested patch or implementation handoff is optional when useful or requested, not mandatory boilerplate.

Severity reflects actual impact and reachability:

- **Critical:** reachable severe compromise, widespread outage, or irreversible data loss.
- **High:** broken core flow, serious authorization/data-integrity fault, or material compatibility/performance regression.
- **Medium:** concrete limited-impact malfunction or actionable rule/requirement breach. Missing tests qualify only for a named material regression scenario or explicit repo requirement; prefer reporting the underlying bug with its regression test.
- **Low/Nit:** cosmetic preference or speculative cleanup; omit. Do not inflate severity to retain it.

Include snapshot/scope, reviewed versus excluded/unreviewed files, representative behavior traces and callers checked, check results, and unresolved limits. Say **no confirmed findings within the reviewed scope**, not "safe to merge" based on green CI. Never claim guaranteed bug detection.

When posting is permitted, post one summary comment with a temporary Markdown body file (`gh pr comment <url> --body-file <path>`). Recheck the PR head before posting and disclose if it moved. Do not post inline comments or submit an approval unless explicitly asked. If authentication or posting fails, return the full review locally with the error; do not claim it was posted.
