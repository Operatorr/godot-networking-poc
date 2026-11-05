# Slice 7 export evidence

Offline evidence for [issue #70](https://github.com/Operatorr/godot-networking-poc/issues/70). **Not live-host validation and not a capacity finding.** Nothing ran: no account, Droplet, SSH session, paid workload or CAX11 evidence was involved, and nothing was published. The exporter is in `scripts/do_session/`: see [its README section](../../../../../../scripts/do_session/README.md#checksum-verified-evidence-export-and-reports-slice-7).

| File | What it is | Reproducible |
| --- | --- | --- |
| [`synthetic-exports.json`](synthetic-exports.json) | 26 whole sessions through the real controller, registry, watchdog, prover, scorer and exporter, over a fake account and fake guests on a scripted clock. Each has its timeline, transfers, resources, incidents and how its three results ended | Yes: `test_export_evidence` regenerates it and compares the hash |
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

A failed session's `overall` is about evidence and resources, not about what was measured. `clean` beside a failed search means every file arrived and every resource is gone.

## Limits

Every number is fixture arithmetic, and none says anything about any host, capacity or cost. Real SSH, a real provider's lifetime and bills, Linux counters, independent hosts and real publication remain unverified. Combined fault validation is [issue #71](https://github.com/Operatorr/godot-networking-poc/issues/71). The historical CAX11 gate is unchanged.
