# Strategy 150 correctness candidate, round 1

**Classification: `valid-failure`. Exactly one workload; no clean certificate or capacity advance.** All workload, collector, generator, transport and received-correctness gates passed. The sole failed final gate is `autonomous_recovery_succeeded`: the recovery shell returned 1 with empty stderr. The original service was independently verified restored, its remaining timer was disarmed without another restart, and missing archival was completed. Both independent final audits pass. The failed automatic recovery remains an unresolved controller finding, rather than being erased by manual completion.

This is one cell of [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39); the parent owns fixes and the remaining campaign. Historical Strategy 100 is unchanged. No other workload, production deploy, branch change or subagent was created.

The [compact machine report](clean-strategy150-r1-20261022-summary.json) records all gates, identities, counters, timing, collector resources, cadence witnesses and proof hashes. Full/private evidence is in ignored `deployment/hetzner/results/clean-strategy150-r1-20261022/`; separate build evidence is in its `-build` directory. Remote originals remain under the corresponding `/home/deploy/omega-results/` namespace on both hosts.

## Exact condition and identity

The pinned candidate is **`487b6d9ad21e6d2fd1b1a9cf2b146ef454e9329a`**, including the parent's final received-AoI-before-stale-discard correction. Both hosts independently built both packages from this revision in `/home/deploy/omega-clean-strategy150-r1-20261022`, using Rust/Cargo 1.95.0, native `aarch64-unknown-linux-gnu`, locked dependencies and `cargo build --release --locked -j 2 -p omega-server -p omega-load-test`. Their executable hashes agree:

```text
game  de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bots  fe1f16f00e3b669209a8fe27ec85d3a43feddbdeefe976188ba5e4ba2fd9d11d
```

The send150 config stayed byte-identical, SHA-256 `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`: game receive/send requested 2 MiB each, effective 4 MiB each; bot buffers stayed native 212,992/212,992 bytes. Strategy 150, 30 Hz input, 100 ms stagger, seed 30, difficulty 1, class rotation, AoI/LOD/budgets and strict assertions are unchanged. World entropy is not fixed. The expensive emission audit was explicitly disabled and no `aoi.csv` was created. Compact observations and the repaired bounded v2 wire collector were retained; no profiler was used.

Workload UTC: **13:02:58.350630–13:09:15.636509**, 377.286944 s. The atomically published measurement was **13:04:15.380156–13:09:15.380156**, exactly 300 s after 60 s warmup. The single-launch reservation remains. Fresh and 119 subsequent game polls check runtime identity; source revision, clean source state, both binary hashes and game config are rechecked, with bot identity checked while live. No identity/config/buffer change or controller abort occurred.

## Workload and correctness observations

All 150 peers passed offered input **29.996093–30.002759 Hz** and both mapped wire views **29.793333–30.000000 Hz**, preserving the per-identity 29.7 Hz gate. Missed schedules were **31 lifetime / 31 steady**. Both captures have 150 unique agreeing mappings, EOF, zero parser errors and zero capture drops: **7,578,012 game / 7,578,011 bot packets**. Captured endpoint differences remain visible.

There are observed offered-to-wire rate differences for **148 peers**, with none below the wire gate. Largest: **bot 52**, port **33918**, offered counters **2146→11146** (29.999426 Hz) versus **8,938 exact-window commands on each capture** (29.793333 Hz), a 0.206093 Hz rate difference. Offered endpoints are observed monotonic boundaries; wire uses the exact UTC schedule. This is not an exact lost-input or application-delivery count. Identity-specific counts, windows and EOF evidence are retained in `offered-to-wire-deficits.json`, with its hash and ten largest differences public. **Cause remains unknown.** No cause is inferred from passing host counters.

There were **9,000 measured Ticks / 30.0 Hz**, with all 150 authenticated throughout. Tick work p99 was **26.227199 ms**, maximum **50.618774 ms**, and **27** Ticks reached 33.333 ms. Maximum accumulator lag was **109.309083 ms**; ending lag was **0.058868 ms**, passing the declared ending-lag gate. Deferred-wait first/last 30 s means were **6.717778 / 6.588889 Ticks**, maximum 9; pending replication means **3061.763333 / 2694.672222**. The unchanged backlog rule passed. Worst per-peer Snapshot age p99/max was **53.680819 / 78.754713 ms**; ActionConfirm **70.010798 / 81.285814 ms**. Every peer passed delivery.

All following bug/error counts are **zero lifetime / zero steady**:

- Baseline-reference misses; unknown delta entities; bot decode/send failures and panics; unexpected bot disconnects.
- Server decode/send errors; journal oversized warnings, panics and suppression notices.
- Both hosts' UDP `RcvbufErrors`, `SndbufErrors`, `InErrors`, `MemErrors`, `InCsumErrors`, and observed socket drops.
- Observed game transport receive errors, send errors and nonempty zero-byte sends.
- Received-AoI unknown positions and actual distances above 1150; stale Snapshots ignored were also 0/0.

The received-AoI census contains **202,963,596 matched positional observations**, zero unknowns for every peer, and no unrounded production-assertion maximum above 1150. Both the default 95% policy and stricter all-peer conditions pass. Lifetime zero bounds steady zero; a separate steady matched-position total is not retained. Ignored stale packets did not occur here; receiver ordering and full-state recovery edge cases remain local-regression coverage, not claimed remote provocations.

Lifetime replication-counter completeness is independently reconciled: final report accepted/stale Snapshot counts equal the last recorder row for every peer, so disconnect drain did not add an unrecorded Snapshot capable of changing those counters. The byte-aware journal completely scanned **456 records / 745,313 bytes**; all raw rows fit retention. Full/steady journal counts are complete. Transport period deltas use retained observation brackets, not invented exact-boundary transport values. Per-Snapshot payload-size extrema and application-delivered input counts remain unknown.

The bot's natural **exit 1** has two failed legacy product criteria: **39.56 KB/s** versus the unchanged 5 KB/s target, and a false `server_tick_rate` criterion whose displayed aggregate rounds to **30.0 Hz**. The unrounded comparison value is not retained. Independent Tick timestamps/counts pass the campaign's unchanged 29.7 Hz gate. These legacy failures are recorded, not relabelled as passes. `per_peer_budget` remains skipped because the original command configures no rate budget; `aoi_cull` and `decode_clean` pass.

## Recovery finding and preservation

The original recovery command at UTC ns `1792674575663119000` returned **1**, stdout `./server.ndjson: OK` and `./ticks.csv: OK`, stderr empty. Its exact command/output and executed shell are retained. Later evidence proves the original executable, config, unit and measurement destination were restored, with ordinary effective **524,288/524,288** buffers and zero players. **Which immediate post-start check failed is unknown**; there is no checkpoint proving a startup race or another cause.

The active owned recovery timer initially prevented the game archive, as intended by the archive guard. After fresh original-state and preserved-measurement verification, the timer was disarmed without restarting the service; the game archive was created and independently checksum-verified. `cleanup.json` retains the original failure. `recovery-completion.json` records manual completion separately. No automatic-success field was fabricated.

Independent final verification and a separate prebuild-preservation/queue audit passed on both hosts: service/config/unit/executable/measurement restoration, candidate source/binaries, default/socket buffers, quiet queues, native qdisc, empty filters, firewall rules, maintenance state, closed campaign states, zero owned processes/active units and preserved old evidence. All **13 game / 8 bot pre-existing executable artifacts** and **81 game / 82 bot prior archive/checksum files** retain their hashes. Remote/local new archives match:

```text
game.tar.gz  6b5dc5cfe7f64480f6f76da6649bad0f6e50dc664263a2419649bf08cc6aae2e
bots.tar.gz  d73313fd2590a9f85cbf82e72fe2c8bd4782143b3416fcefa8d27247eefea5b1
build-final  abb5975b4eac467721fbe798bc9db412084382be029ffa8132c3def2f7878b89
```

The initial build archive is also retained; `build-final` adds final analysis-validation provenance without replacing it. Source bundle/tree, compiler/environment/build output, executed controller, private command journals, recovery failure and audit hashes are retained. **22 new helper tests and 42 existing relevant tests pass**, including actual-shell recovery, teardown failure injection, atomic publication, wire replay, received-AoI unknown/violation gates and final Snapshot reconciliation. Population/behavior dispatch is bounded and tested for future cells; historical controller constants/sources are unchanged.

An offline replay isolation mistake briefly wrote two **private derived scratch JSON analyses** through symlinks. They were regenerated with their original scorer and original paths. No pre-replay checksum exists for those scratch outputs, so byte-for-byte pre-replay identity is not certified. Historical source archives, executables, controllers and committed reports were preserved; the remote archival preservation audit passes. This limitation is separate from the new run's checksum-verified evidence.

Pending parent work: diagnose/harden recovery's uncheckpointed failure, reconcile the legacy Tick criterion/report precision and product bandwidth finding, decide treatment of the passing workload with failed automation, then dispatch any authorized subsequent cell through another test subagent. Complete the remaining clean-build ladder/overload campaign. This agent has no further workload authorization and does not close issue 39.
