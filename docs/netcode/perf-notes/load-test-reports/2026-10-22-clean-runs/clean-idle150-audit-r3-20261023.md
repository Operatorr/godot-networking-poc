# Idle150 native diagnostic — round 3

**Exactly one attempt; `aborted-collector-invalid`; 14/36 original gates pass fail-closed scoring.** The controller aborted **38.759393134 s before the planned measurement window**, during warmup. No 300-second cadence, capacity, final AoI or closed native-lifetime result exists. The [machine summary](clean-idle150-audit-r3-20261023-summary.json) retains every gate, observed prefix, unknown, ambiguity and proof. [Issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39) remains open under the parent; no other cell was advanced.

## Exact source and build

Rust source `a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf`; frozen controller `37ea0eccb74a32c2ffdc7ebab9d743fc91439311` (base terminal/rename correction `4db3cf2`); executed controller SHA-256 `af5a5a2c6794bc04d470ad3a6b87e83766aabb8b212ca83bd36bd49d5bdac306`. Final offline analyzer `c4517a41f60735da6d996121232ebc3e36abe488`. Ordinary campaign candidate `fea24dd` is unchanged.

```text
game  de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot   56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67
```

Both locked packages were compiled natively **once on bots only** (`native_build_origin=bots`). The game host received independent real executable copies with matching SHA-256 (`game_artifact_mode=verifiednativebot-hostcopy`); no game-native package compilation is claimed. Both fresh Rust-only cone checkouts verify every materialized blob and all Cargo files: 62 Rust files plus 14 root files. Cone selection preceded checkout. Compiler/libc/aarch64 GNU/Linux, ELF, dependency, bundle/source and native object provenance are retained. Cargo's executable/object links remain on bots; transported game copies have one link. Missing `file` utility and native-link provenance checks were resolved without package changes, repeat compilation or repeat transfer; first failed proof logs remain sealed. Native intermediates remain retained.

The attempted condition was exactly Idle150, requested 30 Hz, 100 ms stagger, seed 30, difficulty 1, 60 s warmup + scheduled 300 s measurement; config SHA `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`. Game buffers 2 MiB requested / 4 MiB effective receive/send; bot buffers native 212,992 B. `OMEGA_NATIVE_DIAG=v1` explicit; native unimpaired network; no emission audit/perf, channel/reliability/budget/throttle/scheduler change or redundant input.

## Why the controller stopped

The last status query completed with a **0.565104653 s** old game sample. Synchronous atomic schedule publication then took **17.950328 s** before the controller reused that same sample. Its freshness check now saw **18.517215653 s**, exceeding 10 s, and set `game-observation-stale-over-10s`.

Retained game evidence independently contains **18 fresh samples during that publication**; its newest sample at the decision was only **0.513047795 s** old. Maximum game sample gap is **1.002603845 s**. This establishes a cached-observation/controller sequencing defect; the game recorder did not stop progressing. Atomic publication succeeded, with unchanged window clocks. The phase had run only **21.240606866 s** when aborted. The watchdog subsequently recorded `controller-stop`, exit **-15**, elapsed **41.06102079595439 s** including ramp. No retry occurred.

SIGTERM prevented `end`, `drained` and the final bot report. The new remote final-drain and bounded terminal-guard fixes were therefore **not validated by this attempt**. Application lifetime counters, final AoI, full native suffix and legacy results remain unknown. Parent follow-up should refresh both acquired observations after publication or evaluate freshness before blocking publication: the subsequent cached bot timestamp check needs the same treatment. This task makes no post-attempt controller or Rust fix.

## Retained observations and limits

All 150 peers authenticated. The last periodic native prefix has **147,243 created/admitted = 147,231 retired + 12 pending**. Retirements contain **147,148 full Socket input handoffs + 83 no-attempt retirements**; observed zero/partial/error returns and all native observer error/limit/parser counters are zero. Prefix all-datagram attempts/handoffs are **208,429** each. All peer ordinal, timestamp, counter and trace-byte identities independently pass. Final pending, final Socket/error counters and queue lengths remain **unknown**, rather than zero.

All **83** observed no-attempt events retain an unchanged pre/post throttle, single +7 counter step and skip predicate; **zero observed transitions are ambiguous**. Minimum observed throttle is **26/32**. This supports specified native shedding in this retained prefix only; it does not attribute the killed suffix or historical run.

Complete capture input commands are **148,060 on bots and 148,060 on game**. They outlast the retained native prefix by **912 commands**; that difference is not a loss or application-delivery count. In a separately labelled **24-second descriptive prefix**, chosen from complete integer UTC seconds and proven ordinal/admission bounds, **108,001 admissions − 107,928 handoffs = 75 no-attempt admissions + 10 carried-out − 12 carried-in**. Each capture counts **107,929**, one above native handoffs in that timestamp interval. The discrepancy remains unresolved; no game-specific capture asymmetry is observed here. This prefix is not the requested steady window and does not replace any cadence gate.

All **2,377 known-prefix 1-in-64 sampled input fingerprints** match both captures, with no sampled common-prefix boundary crossing. Native-to-capture offsets: bots **3,200..126,127 ns**, game **67,631..1,491,749 ns**. Matching samples cannot prove all-datagram identity, no drops or suffix completeness. Retirement timestamps are post-service record-write observations, not actual Drop instants. Native outgoing/reliable queue lengths and receive truncation remain unavailable in unchanged std UDP. Application delivery and historical cause remain **UNKNOWN**.

Last periodic bot baseline-reference/unknown-entity/decode/send/panic counts are all zero; retained game decode/send counts are zero. These are observed prefixes, not full-lifetime certification. Observed full-workload UDP/socket counters and collector checks are retained separately in the summary. Final received-AoI report/counts and all scheduled steady errors/cadence/delivery/Tick/backlog/AoI results are unobserved. The journal scans all **456 records / 748,060 B**, with no oversized/panic/suppression findings in observed periods; the empty scheduled period is not a zero-error observation.

The first offline output mistakenly passed the unobserved steady journal zero-error gate. Its original outputs are retained in `first-derived/` and `campaign-summary.original.json`. A regression using this real aborted recorder archive failed before the safe offline correction and passes after the existing complete-coverage gate is required. All 36 gate names and thresholds remain; none was weakened. Final scoring has 14 passing flags, with missing intervals failing closed. The unchanged strict <5 KiB/s and raw-float >=30 Hz legacy predicates, raw operands and 1 ms clock semantics remain declared, but no final report exists: their observed operands and results are **null**.

Native measured observer sections total **7,603,989,440 ns**, trace **9,422,784 B**. This is not total causal overhead. No controlled remote observer comparison or cadence-fix claim follows from the local parser timing improvement or this truncated run.

## Storage, restoration and preservation

Before any remote staging, free game storage was **8,810,237,952 B**; additive allowance **201,954,720 B**, leaving **18,348,640 B** above the unchanged 8 GiB guard. Before workload staging: **8,789,372,928 B** free, **177,979,392 B** allowance, **21,458,944 B** remaining. Allowances include sparse source/bundle/objects, binaries/directories/configs/manifests, original executable, 32 MiB live game payload, 24 MiB journal, 58 MiB role archive and 32 MiB margin. Bot native build has a 2 GiB bounded allowance. Ordinary 1 GiB and R1/R2 abort caps remain unchanged.

`rename-v1` was remotely exercised: same-filesystem real-directory and pre-staging hash proofs preceded any source/binary staging. The stopped original directory was hashed and atomically renamed into the exact backup layout; no copy fallback. Both audits verify original directory/file inodes and hash prefixes, frozen manifests/markers/recovery script and all prior original files. The native destination was absent during the candidate and recreated with original owner/group/mode before startup. No cleanup, package change, purchase/resize or evidence/journal/source/build/binary/archive deletion occurred.

**Automatic restoration passed without manual intervention.** Two independent labelled audits, **`r3-release-a` and `r3-release-b`**, each pass **81 bounded commands**, 90 s maximum per command. They verify prior artifacts/archives/closed states, candidate source/binaries, actual sparse blobs, frozen original backups, native owner/mode/paths, ordinary **524,288 B receive/send buffers**, maintenance, native qdisc/empty filters/firewall, zero players, quiet queues, no active owned workload processes/units, and remote/local archive equality. Final free storage: game **8,760,897,536 B**, bots **18,586,284,032 B**. **Hosts released.**

The local before/after census covers **5,696 pre-existing files**, with zero changed/missing files. R1/R2 reservations, reports, evidence and archives remain sealed. Fresh real extraction contains no symlinks/hardlinks. All **59 applicable Python tests** pass; real CLI/ENet terminal and actual-recorder regressions pass locally. Retained root validation is 240 Rust passes, three intentionally ignored probes, green Clippy with two old warnings, formatting and extension. No Rust source changed in this task.

Workload archive SHA-256 values, matched independently remote/local and at extraction:

```text
game.tar.gz  adb1213628af579dc064c5c0e5c3c0e2ca698b6dca184b4e851dcc8e2a602874
bots.tar.gz  94b2e6f5c9719c33f1b97b83d7842f09062a9e32645017e954dbf203d33095f2
```

Private build/preflight/evidence bundles retain checked file-member hashes. No PR, push, issue/map/parent-ledger edit, retry or other cell. The cached-freshness controller defect, unobserved final lifecycle/steady results, prefix boundary discrepancy, unknown causal overhead and campaign closure return to the parent. **One attempt; stopped.**
