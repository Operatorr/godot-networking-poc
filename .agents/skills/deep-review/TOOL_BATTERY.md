# Tool Battery

Phase 3 of `deep-review` runs every available deterministic check and folds the output into the review. This file defines detection, the tool matrix, the install policy, and how output is normalized. Tool-only findings (no LLM counterpart) are a major source of deep-review's extra finding count, so do not skip this phase when runners are available.

## Detection

From the Phase 1 changed-file manifest, map each file to tool sets:

- **By extension:** `.js/.jsx/.ts/.tsx` → JS/TS; `.py` → Python; `.go` → Go; `.rb`/`.rs`/`.java`; `.sh` → Shell; `Dockerfile`/`*.dockerfile` → Docker; `.tf` → Terraform; `.yaml`/`.yml` → YAML; `.md` → Markdown; `.json` → JSON.
- **By config presence (raises priority):** if `.eslintrc*`, `biome.json`, `ruff.toml`/`pyproject.toml`, `.golangci.yml`, `.markdownlint*`, `.yamllint*`, `tsconfig.json`, `mypy.ini`, etc. exist, prefer the project's configured invocation over a default one-shot run.
- Always run secret and multi-language SAST scanners regardless of language mix.

## Tool matrix

Run tools in preference order. When a tool is not installed, use the one-shot runner.

| Domain | Tools (preference order) | One-shot runner when not installed |
| --- | --- | --- |
| JS/TS lint | project ESLint, Biome | `npx --yes eslint <paths>`, `npx --yes @biomejs/biome check <paths>` |
| JS/TS types | project `tsc` | `npx --yes typescript tsc --noEmit` |
| Python lint | Ruff | `uvx ruff check <paths>` |
| Python types | mypy, pyright | `uvx mypy <paths>`, `npx --yes pyright <paths>` |
| Go | `go vet`, golangci-lint | `go vet ./...` (no global install without permission) |
| Shell | ShellCheck | system `shellcheck` (ask before install) |
| Dockerfile | Hadolint | `docker run --rm -i hadolint/hadolint < Dockerfile` if docker present, else ask |
| Terraform/IaC | Checkov | `uvx checkov -f <file>` |
| YAML | yamllint | `uvx yamllint <paths>` |
| Markdown | markdownlint | `npx --yes markdownlint-cli <paths>` |
| Multi-language SAST | Semgrep | `uvx semgrep --config auto <paths>` |
| Secrets | Gitleaks | system `gitleaks detect`; else `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks detect --source=/repo`; else ask |
| Prose/grammar | LanguageTool, Vale | `npx --yes` where a runner exists; else rely on the sub-agent grammar pass |

## Install policy

- **One-shot runners run without asking.** `npx --yes …`, `uvx …`, and `docker run …` are ephemeral and non-destructive — they do not pollute the system. Use them freely so "not installed" rarely means "skipped".
- **Never run a global/system install without explicit permission.** That includes `npm install -g`, `pip install`, `brew install`, `go install`, and package-manager mutations. When only a global install would unlock a tool, list the tool, the exact install command, and ask. If declined, mark the tool `skipped (not installed)` in the statistics block and continue — coverage degrades gracefully, it does not block.
- **Check mode only.** Never pass `--fix`, `--write`, or any mutating flag. This skill reviews; it does not edit.
- **Scope to changed paths** where the tool supports per-path runs, to keep runs fast and findings on-diff. Secret scanners and Semgrep may scan the diff or full changed files.
- **Time-box** slow tools; if a run is too expensive, note it as `skipped (timed out)` rather than blocking the review.

## Normalization

Parse each tool's output into the shared finding record so it flows through the same Phase 5 dedupe as LLM findings:

```text
path: <file>
line: <line or range>
category: <mapped — see below>
rule_id: <tool rule id, e.g. eslint:no-unused-vars>
message: <tool message>
source: <tool name>
severity: <advisory; orchestrator normalizes in Phase 5>
```

Category mapping:

- lint style/format → **Style/Nitpicks** or **Maintainability**
- type error → **Correctness**
- SAST finding → **Security**
- secret detected → **Critical / Security**
- prose/grammar → **Grammar & prose** (usually Nitpick)

In Phase 5, a tool finding and an LLM finding at the same location describing the same defect merge into one entry tagged `confirmed-by-tool` (higher confidence). A tool finding with no LLM counterpart is kept as its own finding.
