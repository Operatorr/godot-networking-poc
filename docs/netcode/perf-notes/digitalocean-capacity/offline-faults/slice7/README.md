# Slice 7 export evidence

Offline evidence for [issue #70](https://github.com/Operatorr/godot-networking-poc/issues/70). **Not live-host validation and not a capacity finding.** Nothing ran: no account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and nothing was published. The exporter is in `scripts/do_session/`: see [its README section](../../../../../../scripts/do_session/README.md#checksum-verified-evidence-export-and-reports-slice-7).

| File | What it is | Reproducible |
| --- | --- | --- |
| [`synthetic-exports.json`](synthetic-exports.json) | 39 whole sessions through the real controller, registry, watchdog, prover, scorer and exporter, over a fake account and fake guests on a scripted clock. Each has its timeline, transfers, resources, incidents and how its three results ended | Yes: `test_export_evidence` regenerates it and compares the hash |
| [`synthetic-sample/`](synthetic-sample/) | One session's published text as an export writes it, under a banner saying it is a fixture. Its player count, prices and hashes are all fixture values | Yes, likewise |
| [`SHA256SUMS`](SHA256SUMS) | Hashes of the above | |

No raw recorder file is retained. Each scenario's raw tree is deleted with its temporary directory, and so the hash lines in the sample point at nothing.

## What the sessions show

| Scenario | Evidence | Overall | Establishes |
| --- | --- | --- | --- |
| Confirmed search, then verified absence | `complete` | `clean` | The fixture's candidate |
| No passing target; failed confirmation with no replacement; invalid offered load; infrastructure failure; inconclusive evidence | `complete` | `clean` | Nothing |
| Confirmed search with a required file absent | `partial` | `resources_verified_evidence_incomplete` | Nothing: the search's sentence stays as history |
| Corrupt bytes; a file changing between attempts; another role's bytes for a seal; a stale recorder schema | `corrupt` | `resources_verified_evidence_incomplete` | Nothing, with no bad byte promoted |
| A transfer that keeps failing; no space promoting a file; a first failure older than the grace; a reconnect | `missing` | `resources_verified_evidence_incomplete` | Nothing, with both roles' available files kept |
| A truncated transfer that recovers | `complete` | `clean` | Nothing: the run keeps its recorded failure, and the truncated attempt stays under its own name |
| No space for the generation; the rename refused; an exporter defect | `partial`, no generation | `resources_verified_evidence_incomplete` | Nothing, with cleanup requested anyway |
| A report defect | `partial`, inventory only | `resources_verified_evidence_incomplete` | Nothing |
| A controller crash, then collect | `partial` | `resources_verified_evidence_incomplete` | Nothing: the run stays incomplete |
| The watchdog alone, with no controller | `unknown`, no export | `resources_verified_evidence_incomplete` | Nothing |
| A deletion outage past D | `complete` | `resources_verified_after_overdue` | The fixture's candidate, with the incident kept on record |
| New socket fields, one opaque, carried by the raw files | `complete` | `clean` | None of them reached anything derived |
| The manifest changed afterward | `corrupt`, inventory only | Registry's earlier word kept apart | No report is written |
| A confirmed search with a plan, a clock bracket or a recorded provisioning artifact lost before wrap-up | `missing` | `resources_verified_evidence_incomplete` | Nothing, though every score still verifies: the search's sentence stays as history |
| A confirmed search with a clock bracket cut to one byte before wrap-up | `corrupt` | `resources_verified_evidence_incomplete` | Nothing, though every score still verifies: the bracket's bytes stay inventoried and what each run decided stays |
| A directory that cannot be listed, with a readable one beside it | `partial` | `resources_verified_evidence_incomplete` | Nothing: the sibling stays inventoried and the published text says how many paths it cannot cover |
| A first failure followed by a slow file, by a crash, or by a crash with the report lost | `corrupt` | `resources_verified_evidence_incomplete` | Nothing, and the recovery deadline stays the first failure plus the grace. `corrupt` is the fixture's cut bytes kept under `.partial` |
| A lost report, a crash, and a failure record the next controller cannot read | `missing` | `resources_verified_evidence_incomplete` | Nothing: the episode is taken as over, no transfer starts after the return, and the deadline is no later than the first failure plus the grace |
| A lost report, a crash, and a returning controller whose wall clock is 120 s behind | `corrupt` | `resources_verified_evidence_incomplete` | Nothing, and the recovery deadline stays the first failure plus the grace, from the monotonic age |
| A failure a new controller recovers inside the episode, and a resumed batch that goes on | `complete` | `clean` | The fixture's candidate: dispatching the next run ended that failure |
| Text placed in the canonical directory, then an operator's record, then a fake publication adapter | `complete` | `clean` | Publication reads `verified_local`, `operator_recorded`, then `published`, one step each |
| One bot at a 20% loss estimate beside a passing mean | `complete` | `clean` | The fixture's candidate: the peer peak reaches published text and decides nothing |

The scenario once named `published_to_the_canonical_directory_only` is now `prepared_in_the_canonical_directory_only`, because a local copy is not published. Its evidence and overall results did not change, and its publication status now reads `verified_local`.

The three sessions added for the unreadable record, the wall-clock step and the truncated bracket change no earlier row: all 36 keep every field they had.

A failed session's `overall` is about evidence and resources, not about what was measured. `clean` beside a failed search means every file arrived and every resource is gone.

## Limits

Every number is fixture arithmetic, and none says anything about any host, capacity or cost. Real SSH, a real provider's lifetime and bills, Linux counters, independent hosts and real publication remain unverified. Combined fault validation is [issue #71](https://github.com/Operatorr/godot-networking-poc/issues/71). The historical CAX11 gate is unchanged.
