# Strategy 150 correctness candidate, round 2

**Classification: `clean-cell-pass`. Exactly one workload; all 36 matrix gates pass.** The unchanged legacy product criteria still fail bandwidth and exact estimated Tick rate. This is one matched cell of [issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), not a campaign certificate or historical capacity upgrade. The parent owns the remaining ladder/overload runs and issue state.

The [machine summary](clean-strategy150-r2-20261022-summary.json) retains every scored gate, count, unknown, identity and proof hash. Private evidence is in ignored `deployment/hetzner/results/clean-strategy150-r2-20261022/`, its `-build` directory and separate evidence/build archives. Originals remain in the corresponding `/home/deploy/omega-results/` namespace on each host. No R1 analyzer was rerun; historical derived files stayed untouched.

## Pinned build and unchanged condition

Candidate **`fea24dd1ec75eb3a5e832e408489943ced88814f`** was independently built on both hosts in separate clean checkouts using Rust/Cargo 1.95.0, native aarch64, locked dependencies and `cargo build --release --locked -j 2 -p omega-server -p omega-load-test`. Both hosts prove identical hashes:

```text
game  de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bots  a4e6e7a60f3890ec63724aae0a4841ad31879a0fcfbc8643e261b11421b76147
```

The game executable matches R1; the bot executable includes the report-precision correction. The byte-identical send150 config retains SHA-256 `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`. Game receive/send buffers remain 2 MiB requested / 4 MiB effective each; bots retain native 212,992-byte buffers. Strategy 150, 30 Hz input, 100 ms stagger, seed 30, difficulty 1, class rotation, strict assertions, AoI/LOD/budgets and all collector settings are unchanged. No emission audit or profiler ran; World entropy is not fixed.

Workload UTC **13:43:55.410065–13:50:12.665212**, 377.255147 s. The exact measurement was **13:45:12.485319–13:50:12.485319**, 300 s after 60 s warmup; the schedule was atomically published with 50.85 s lead. Fresh runtime proof and all **118** retained polls preserve candidate source revision, clean status, binary hashes, config, process and effective buffers. One launch reservation, one workload, no controller abort/error or watchdog reason.

## Complete workload evidence

All 150 peers passed offered **29.989483–29.999483 Hz** and both mapped wire views **29.810000–29.993333 Hz**, retaining the per-identity 29.7 Hz gate. Missed schedules were **180 lifetime / 180 steady**. Each capture has 150 unique agreeing identities, EOF, zero parser errors and zero capture drops: **7,593,739 game / 7,593,738 bot packets**. Capture endpoint differences are preserved.

All 150 peers show offered-to-wire cadence differences, with none below the wire gate. Largest: **bot 52**, port **43467**, offered counters **2148→11145** at **29.989483215127372 Hz**, versus **8,943 exact-window commands / 29.81 Hz** on each capture; difference **0.17948321512737309 Hz**. Offered observation endpoints and the exact UTC wire window differ. These are not exact loss or application-delivery counts; cause remains unknown. Every peer's counters and windows are retained.

There were **9,000 measured Ticks / 30.0 Hz**, with all 150 authenticated throughout. Tick work p99/max was **26.248400 / 58.006116 ms**; **10** Ticks reached 33.333 ms. Accumulator lag max/end was **30.519891 / 1.032657 ms**, and elapsed Tick lag ended at **0.719955 ms**. Deferred-wait first/last 30 s means were **6.766667 / 6.637070 Ticks**, maximum 10; pending replication means **3177.024444 / 2748.045505**. Tick, ending-lag and unchanged backlog gates pass. Worst peer Snapshot age p99/max was **52.687368 / 59.392465 ms**; ActionConfirm **83.613711 / 98.330356 ms**. Every peer passed delivery.

The following counts are **zero full-workload / zero steady**:

- Baseline-reference misses, unknown delta entities, stale Snapshots ignored, bot decode/send failures and panics; unexpected bot disconnects are zero in the final report.
- Server decode/send errors; transport receive/send errors and nonempty zero-byte sends.
- Both hosts' UDP receive/send buffer errors, input/memory/checksum errors and observed socket drops.
- Journal oversized warnings, panics and suppression notices.
- Received-AoI unknown positions and actual distances above 1150.

Received AoI includes **203,603,817 matched positional observations**, complete for every peer, zero unknowns and zero unrounded production-assertion violations above 1150. Both the default 95% policy and stricter all-peer gates pass. Lifetime zero bounds steady zero; a separate steady matched-position total is unknown. No stale Snapshot or manual recovery edge was provoked; those remain local regression coverage.

Final report accepted/stale Snapshot counts reconcile exactly with the final recorder row for every peer, proving full replication-counter coverage through drain. The byte-aware journal scanned and retained **456 records / 745,313 bytes**, all 456 byte-array messages decoded. The full-workload interval has **450 records / 150 textual disconnect matches**; the steady interval has no journal records. The experiment interval has two textual `send` matches, distinct from server send-error counters, which are zero. Independent offline checks agree with every journal-period count, rate arithmetic, Tick count/p99, final Snapshot reconciliation, AoI totals, runtime identity and archive hash.

Unknowns remain: application-delivered input counts, per-Snapshot payload extrema, exact receive/send queue residence, outstanding reliable queue occupancy, causal collector slowdown and equal World trajectories. Transport deltas use retained observation brackets rather than invented exact-boundary counts.

## Legacy product criteria retained exactly

The bot naturally exited **1**, with exactly two failed legacy criteria:

- **Bandwidth: 39.66 KB/s versus 5 KB/s**, the known out-of-scope optimization target.
- **Estimated Tick rate: 29.99998120034632 Hz versus unchanged `>= 30`**. Its recorded numerator is **1,659,604 summed paired Snapshot Tick spans**, denominator **55,320,168 summed server-clock milliseconds**, evaluated as `ticks * 1000.0 / ms`; clock resolution is **1 ms**. The raw value and the false criterion are retained and independently recomputed. The separate matrix Tick gate uses 9,000 Ticks in the exact 300 s window and passes.

No threshold changed, and neither legacy failure is relabelled as a pass. Other legacy criteria and the enabled AoI/decode assertions pass; the original per-peer budget assertion remains skipped because the command configures no rate budget.

## Automatic recovery and independent preservation

Automatic teardown invoked the preserved restore shell, which returned **0** at `OMEGA_RECOVERY result=0 step=restored`. Attempts **1 and 2** observed the same original PID **632368** and pinned executable hash `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`. Original measurement checksums passed before restart; the fallback timer was disarmed and both archives completed automatically. No manual recovery was needed. R1 remains its original failed automatic-recovery observation with unknown immediate cause.

Two independent complete audits passed on both hosts, under unique `final` / `recheck` restoration labels and `independent` / `recheck` preservation labels. Each used 90 s command timeouts and retained exact command/output journals, with zero failed steps. Each proves service/config/unit/executable/measurement restoration, ordinary effective **524,288/524,288** buffers, zero players, quiet queues, native qdisc, empty filters, unchanged firewall/maintenance, no owned processes or active units, clean candidate source and matching remote/local new archives. Both R1 and R2 original measurement backups verify against their preserved checksum lists; native config and measurement-unit backups also match.

All **15 game / 10 bot pre-existing executable artifacts** and **82 game / 83 bot prior archive/checksum files** retain their hashes. The local preservation census covers 204 historical/source files; only the two explicitly edited reusable helpers changed. R1 raw archives, reports, private derived files, controllers and executables were preserved. R1's previously documented raw-audit/scratch limitations remain unchanged.

Remote/local new workload archives agree:

```text
game.tar.gz  2a914e13185257a5630f4dd023574ff579d5f28f4d13f37f1b16c6f2fc718c4c
bots.tar.gz  1c7b5979792796ae02f7dd901fbdb8a701726f97f26d793059a5f1da28e514cd
```

Reusable helper changes are limited to bounded, uniquely labelled preservation audits with exact failed-step evidence, and optional verified same-revision real-file binary reuse for future cells. The build helper permits a fixed full candidate behind HEAD only after exact commit/reachability and verified bundle containment checks; remote clean-source/hash guards remain. **R2 used fresh native builds, not reuse.** All **31 clean-run tests and 42 existing relevant tests** pass, including actual Git/bundle reachability, real copy identity, dirty/symlink/hash/overwrite rejection, readiness and audit-failure evidence. The new helper sources are separately preserved; the actually executed R2 build/controller sources remain pinned.

Pending parent work: dispatch the remaining passing ladder cells and one overload cell sequentially, evaluate the complete campaign, and own issue 39 state. This agent has no further workload authorization and does not close the issue.
