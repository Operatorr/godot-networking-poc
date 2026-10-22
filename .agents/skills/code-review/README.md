# code-review

Bounded review of GitHub PRs, branch diffs, uncommitted work, and named files across three separate axes: **Bugs**, **Standards**, and **Spec**.

The main reviewer traces changed behavior, failure paths, and affected callers. Up to two independent reviewers check repository standards and documented requirements. The main reviewer verifies their claims before reporting. Missing specs are explicit; green tests alone cannot justify a clean report. Side-effecting changes receive explicit partial-initialization and cleanup-failure traces, followed by a targeted search for sibling defects.

Normal review uses one round, focused checks, and concrete Critical/High/Medium findings. It has no finding quota or guaranteed runtime. Use [`deep-review`](../deep-review/SKILL.md) for per-file delegation, broad scanners, and Low/Nit coverage.

## Files

- [`SKILL.md`](./SKILL.md) — workflow, scope, and severity
- [`AXIS_PROMPTS.md`](./AXIS_PROMPTS.md) — independent Standards and Spec briefs
- [`REFERENCE.md`](./REFERENCE.md) — report and posting template
- [`PROJECT_REVIEW_TEMPLATE.md`](./PROJECT_REVIEW_TEMPLATE.md) — optional starter `REVIEW.md`

## Examples

```text
/code-review https://github.com/OWNER/REPO/pull/123
Review PR #123 using specs/invitations.md.
Review the current branch against main.
Review my staged and unstaged changes, including untracked files.
Review https://github.com/OWNER/REPO/pull/123 but do not post.
```

A branch review requires a fixed point; a PR supplies its own base. Branch comparisons use the merge base and exclude uncommitted changes unless requested. A direct PR URL permits one summary comment unless posting is disabled; other targets remain local unless posting is requested.

## Installation completeness

Install or copy the whole `code-review/` directory, not only `SKILL.md`. The workflow uses `AXIS_PROMPTS.md` and `REFERENCE.md`; omitting them degrades reviewer briefs and reporting.
