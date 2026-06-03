# code-review

Fast, light code review for GitHub PRs and local branch changes.

This is the precision-biased `/code-review` workflow: it usually reports only the top 1-3 material issues and skips exhaustive nitpicks. Use [`deep-review`](../deep-review/SKILL.md) when you want CodeRabbit-style coverage.

## Files

- [`SKILL.md`](./SKILL.md) — main skill instructions
- [`REFERENCE.md`](./REFERENCE.md) — templates, examples, severity guidance
- [`PROJECT_REVIEW_TEMPLATE.md`](./PROJECT_REVIEW_TEMPLATE.md) — starter project-level `REVIEW.md` template

## Example prompts

```text
/code-review https://github.com/OWNER/REPO/pull/123
/skill:code-review https://github.com/OWNER/REPO/pull/123
Review PR #123 quickly.
Review https://github.com/OWNER/REPO/pull/123 but do not post to GitHub.
Review the current branch against main.
Do a security-focused light review of this PR, but do not post to GitHub.
```
