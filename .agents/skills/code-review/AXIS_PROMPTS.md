# Independent axis briefs

Use the shared brief plus exactly one axis brief for each child. Substitute concrete snapshot identifiers and source paths. Do not delegate by sending only "review this PR".

## Shared brief

Review the assigned axis of this change directly. Do not invoke `code-review`, `deep-review`, or another review skill, and do not spawn additional agents. Do not edit files, post comments, approve, or merge.

You receive:
- Exact comparison/snapshot and commands or captured artifacts for reading it.
- Changed-file manifest and diff, including deletions and exclusions.
- Locations of applicable repo instructions, standards, and available requirements.
- Relevant tooling and changed contracts to inspect.

Read the relevant source and consumers yourself. Do not infer that a check passed or an author assertion is correct. Findings must concern this change, with exact code locations and source citations. Check plausible upstream guards and counterevidence before returning a claim.

Include verified Low candidates as well as Critical, High, and Medium; use the severity definitions in `SKILL.md`. Low requires the same evidence and a concrete consequence, not just a plausible concern. Omit cosmetic Nit feedback.

Return: confirmed candidates with severity, location, evidence, consequence, fix direction, and verification scenario; coverage with source locations inspected; unresolved questions and omissions. Zero findings is acceptable. Do not force an issue count, invent requirements, or classify missing evidence as a pass. Stop after one pass and targeted verification; no iterative clean-review loop.

## Standards reviewer

Question: does the change obey this repository's documented engineering rules and invariants?

Read applicable instructions, `REVIEW.md`, `CODING_STANDARDS.md`, `CONTRIBUTING.md`, and relevant ADRs. For each actionable breach, quote the rule with its path/line and cite the changed code. Distinguish mandatory rules from recommendations. Skip rules enforced by configured linters; the parent reports check failures once.

Where docs are silent, use nearby code only as evidence of a convention, not a binding requirement. Use these named smell heuristics only when they expose a concrete maintenance risk in the change: Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Repeated Switches, Shotgun Surgery, Divergent Change, Speculative Generality, Message Chains, Middle Man, Refused Bequest. Label such a finding `possible <smell> (judgement call)`, cite the hunk and related code, explain the specific likely fault, and suggest a local remedy. A smell name alone is not a finding at any severity. Repo rules override the baseline.

Do not turn this into a general redesign or cosmetic review. If a behavioral bug emerges, return it as a Bugs lead for the parent to verify. End with the worst Standards candidate or none confirmed, and any coverage limits.

## Spec reviewer

Question: does the change implement the documented requirements?

Read the supplied requirement sources, including acceptance criteria and relevant linked context. Build a compact requirement map: `source:line or anchored quote → implementation → test/evidence → satisfied / partial / missing / contradicted / unclear`. Check negative requirements and edge cases as well as the happy path. A test name or PR claim alone does not prove compliance.

Trace missing, partial, or incorrect requirements to code and observable behavior. Report scope creep only when it violates an explicit boundary or has a concrete adverse effect; extra code alone is not a defect. Quote the requirement for each finding. Do not invent requirements from the implementation or treat speculative discussion as approved scope. Report conflicting or unavailable requirements as questions, not confirmed failures.

Return the requirement map alongside findings. End with the worst Spec candidate or none confirmed, and any coverage limits. If the sources contain no actual requirements, return `no spec available` rather than manufacturing a spec.
