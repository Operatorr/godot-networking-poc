# deep-review

Maximally thorough, CodeRabbit-style code review for GitHub PRs and local branch changes. The thorough counterpart to `code-review`: it fans out one focused sub-agent per changed file, runs every available linter/SAST/secret scanner, and reports every issue down to nitpicks. Optimizes for recall — some noise is acceptable.

## Files

- [`SKILL.md`](./SKILL.md) — main skill instructions (principles, phased workflow, severity tiers, output)
- [`REFERENCE.md`](./REFERENCE.md) — finding shape, terminal + GitHub templates, the `gh api .../reviews` inline payload recipe, fallback commands, pitfalls
- [`SUBAGENT_PROMPT.md`](./SUBAGENT_PROMPT.md) — the exact per-file review sub-agent prompt (the anti-salience-collapse core)
- [`TOOL_BATTERY.md`](./TOOL_BATTERY.md) — language/file detection and the linter/SAST/secret-scanner matrix with the npx/uvx install policy

## Example prompts

```text
/deep-review https://github.com/OWNER/REPO/pull/123
/skill:deep-review https://github.com/OWNER/REPO/pull/123
Exhaustively review PR #123 — find everything.
CodeRabbit-style deep review of the current branch.
Thorough review of this PR with inline comments.
Nitpick-level review of these local changes, terminal only.
```

## When to use which

- **deep-review** — maximum coverage; you want every issue including nitpicks, accept some noise.
- **[code-review](../code-review/SKILL.md)** — fast, conservative, senior-engineer review that flags only what matters.
