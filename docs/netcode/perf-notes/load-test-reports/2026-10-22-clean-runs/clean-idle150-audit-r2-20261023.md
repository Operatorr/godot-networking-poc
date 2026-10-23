# Idle 150 native admission-to-wire diagnostic — round 2

**One workload; `aborted-generator-invalid`; native diagnosis incomplete.** All 36 original gates were scored unchanged: **34 pass**, while offered and mapped wire cadence fail for **all 150 peers**. This is not a clean-load pass or capacity result. The [machine summary](clean-idle150-audit-r2-20261023-summary.json) retains full/steady observations, all gates, per-peer evidence, ambiguities and hashes. [Issue 39](https://github.com/Operatorr/godot-networking-poc/issues/39), the held ladder and parent candidate `fea24dd1ec75eb3a5e832e408489943ced88814f` remain unchanged by this task.

## Exact source and execution

Instrumented source: `ab535731b21860fcfdc3654288dd8821eaa63450`. Frozen controller: `69334ee8b1c1a0701df22bd9eef426e350bbbd8b`; executed SHA-256 `3bc59a825734cc2672e0bed8c850354d002633752edd94cb30406613a0647221`. Corrected offline analyzer: `ee3d1143533d1dd10ceaf55f2f00bfd10fa36ca0`. No Rust/game/protocol/simulation change or remote native package rebuild occurred.

```text
game  de92e120bb863948fc4c55fe525d200ac6ebc0d0d214d453ed3efeab159208db
bot   a9325ad1bd90a24e3d1bdb08ce049fb5734d67471010af6f5425b104bda2f042
```

Both hosts use new, real binary copies from the proven R1 build. Both new Rust-only cone checkouts are pinned, clean, and verify every materialized blob: **61 Rust files, including all Cargo files, plus 14 root files**. Sparse specification is `/*`, `!/*/`, `/rust/`; it was set before checkout. Rust tree `94e03de6be62482b9f12aa1d6d95b1383a1307a9`; specification SHA `2d189224b3c941b40b7ba2682e53aacf4a059bce1dcf8c03bfb49ceebae10166`. Shared-object provenance and bundle reachability are retained. Existing checkouts are untouched. The ordinary default-off bot hash is not this diagnostic bot.

Condition: Idle150, 30 Hz requested input, 100 ms stagger, seed 30, difficulty 1, 60 s warmup + exact 300 s measurement. Config SHA `0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`. Game buffers: 2 MiB requested / 4 MiB effective receive and send; bot buffers: native 212,992 B each. `OMEGA_NATIVE_DIAG=v1` is explicitly enabled; no AoI emission audit or profiler. Channels, reliability, scheduling, throttle defaults and the 29.7 Hz gates were not changed.

## Preflight, reservation and storage

Bounded connectivity succeeded before the new exclusive reservation. There is exactly one R2 reservation and one workload launch; no retry. R1 remains sealed with zero workloads, its failed reservation and all historical evidence intact.

Before any remote staging, free game storage was **9,128,042,496 B**. The additive allowance was **525,470,790 B**, including measured preservation copy **197,632,000 B**, complete sparse source/bundle/binary staging **40,528,966 B**, 96 MiB live payload, 24 MiB journal, 122 MiB role-only archive and 32 MiB margin. That left **12,637,114 B after all allowances above the unchanged 8 GiB guard**.

The controller repeated the check before workload staging: preservation **198,311,936 B**, staging **24,887,296 B**, total **510,509,056 B**, remaining above guard after allowances **10,375,168 B**. The ordinary 1 GiB resource stop and all gates remain intact; diagnostic live evidence has the stricter 96 MiB stop. No additional cleanup, package change, journal/evidence/source/build/archive/binary deletion, purchase or resize occurred. The game archive contains `game/` only, excluding the original backup.

## Load validity and retained correctness

Offered rates are **29.562921561253216–29.57958799577867 Hz**; both captures' per-peer wire rates are **27.33–29.52 Hz**. All peers fail both 29.7 Hz gates. The diagnostic has observer overhead and fails offered cadence; it cannot certify the intended valid 30 Hz load or serve as a pure performance comparison.

The common 300 s coverage gate passes. Authenticated population is exactly 150 through all **9,000 Ticks**: actual 30 Hz; work p99 **11.022872 ms**, maximum **17.277358 ms**. Ending accumulator lag is **0.3123443333382381 ms**; deferred wait remains zero, without growing replication backlog. Every peer passes Snapshot/ActionConfirm delivery: worst per-peer p99 ages **43.050684 / 137.253403 ms**, observed maxima **259.996282 / 302.286480 ms**.

Full-workload and steady baseline-reference misses, unknown entities, decode/send failures, panics and server decode/send errors are all zero. Both hosts' full/steady/all-observed UDP error and socket-drop counters are zero; capture parser errors and capture drops are zero. These measurements do not prove application input delivery. All **1,650,814 accepted Snapshots** reconcile with the final application counters; stale received count is zero. The received-AoI checker covers every received Snapshot, including the stale-discard path, and all peers: **36,444,919 matched positions, zero unknowns or actual violations**, unchanged 1150 threshold, no empty peer observers. Journal scanning retains all **456 records / 748,054 B**, with zero oversized, panic or suppression findings. Complete delivery, population, cadence, Tick, backlog, UDP, AoI and full/steady counter details remain in the summary.

Legacy criteria also remain failed: displayed **7.45 KB/s** versus the original strict **<5 KiB/s** predicate. Raw arithmetic is **411,921,604 bytes / 150 / 360 / 1024 = 7.449392433449074 KiB/s**. Estimated Tick rate is **1,657,908 × 1000 / 55,263,603 = 29.999998371441688 Hz**, which fails unchanged **>=30**, with **1 ms** timestamp resolution. The independent 9,000/300 Tick measurement is separately scored and does not replace that failed legacy criterion.

## Native boundary evidence and its open suffix

The last native snapshot is **before disconnect/drain**. It reports **1,639,091 admissions = 1,638,941 retained retirements + 150 pending inputs**, exactly one pending input per peer. All peer prefix balances, ordinals and Socket counters independently reconcile. Retained retirements comprise **1,616,728 full Socket input handoffs + 22,213 retirements without a native attempt**; observed native zero/partial/error returns are zero. All-datagram attempts and full handoffs in that snapshot are **3,138,063**. These are distinct from admissions, capture records and application delivery.

There is **no post-drain native snapshot**. The pinned source samples `end` before `begin_disconnect`/`force_close`, then exits without another native observation. Final native pending count, native retirement fate and native Socket/error counters therefore remain **unknown**, not zero. Trace record writes observe retirement after service, rather than the exact Drop instant; inferred boundary pending brackets are not native queue lengths. Full native lifetime/drain cannot be certified. The raw closed-lifetime diagnostic check fails for this reason; the separate retained-prefix accounting checks pass.

For the **retired trace subset** in the exact UTC measurement window: **1,330,725 admission timestamps**, **1,308,679 full handoffs**, **22,043 no-attempt admissions**, **6 carried-in** and **9 carried-out** handoffs. Its difference balances: **22,046 = 22,043 + 9 − 6**. Late observation-endpoint input deltas total **1,330,869**; they are not relabelled exact-window admissions. Boundary lateness is retained, and the missing pending-input timestamps prevent closing the complete exact UTC admission window.

Complete capture command counts are **1,616,728 bot-side / 1,616,717 game-side** over capture lifetime, and **1,308,679 / 1,308,672** in the same exact measurement window. Bot-side counts equal traced Socket handoffs for every peer. Game capture is **11 commands lower full / 7 lower steady**; this asymmetry remains unresolved. It is not evidence of application delivery or a proved capture/network cause.

The v2 collector retains deterministic **1-in-64 full-UDP fingerprints**, alongside complete command counters. After correcting the offline port reader, **all 25,262 sampled input datagrams match at both captures**, with zero missing/extra records, complete per-peer comparison and no sampled exact-window membership crossings. Native-to-capture timestamp offsets are **2,966..605,438 ns** on bots and **−123,674..3,522,090 ns** on game; independent clocks and microsecond capture precision remain limitations. The sample is not an all-datagram identity census.

## Ranked diagnosis

1. **Native adaptive shedding — strong retained-prefix support.** All 22,213 no-attempt retirements match the native classifier's single +7 counter step, pre-throttle skip predicate, one pending input and unchanged defaults. Independent traces show unchanged pre/post throttle for **21,991**; **222 have changed throttle and remain explicitly ambiguous**. Minimum observed throttle is **12/32**. Do not extend this classification to the ambiguous events, unobserved suffix or historical run.
2. **Delayed flushing — measured boundary carry, incomplete final drain.** Maximum observed service gap **67.780014 ms**, service bracket **5.850850 ms**, tracked retirement age **67.695133 ms**. The retired subset's carry is accounted for; the final 150 pending inputs cannot be classified.
3. **Capture miscount — offline parser defect fixed, residual asymmetry unresolved.** The native analyzer incorrectly read network-order UDP ports as little-endian and initially matched no fingerprints. A new regression compiles the **actual frozen recorder**, replays PCAP, fails before correction and passes afterward. First output/source are retained; corrected analysis is separate. Matching samples and complete bot-side counts argue against a large bot collector deficit in this run, while the 11/7 game-side difference remains unknown. No remote workload or collector behavior was changed.

Native whitelist/parser/trace-limit/pending-limit/write/unmatched/error counters are zero **in the observed prefix**; the unobserved post-drain counters remain null. Public peer queue pointers are never interpreted as lengths; native outgoing/reliable queue lengths stay null. Actual receive truncation is **unavailable in the unchanged std UDP implementation**, not zero. Native measured observer sections total **84,693,931,835 ns**, in addition to ordinary sampling cost; this is not total causal observer cost. Offered cadence failure prevents an unqualified workload comparison. Historical Idle150 cause and exact application delivery remain **UNKNOWN**.

## Terminal controller observation

The last poll starts **471,781,180 ns before** the window end and finishes **253,992,820 ns after** it. It has a bot identity, no guard result yet, and zero sockets after teardown; the controller decides at **end +254,454,820 ns**. The watchdog subsequently records natural completion, reason null, exit 1 (legacy criteria). The final application report, end boundary and 300 s coverage are retained. This demonstrates a terminal status/read race and remains `bot-socket-observations-incomplete` in the manifest and aborted classification. No gate or result is rewritten to turn it into a pass; no second workload was attempted.

## Restoration, preservation and validation

Automatic restoration passed without manual intervention; the diagnostic restore timer is disarmed. Two fresh independent audits, **`r2-release-a` and `r2-release-b`**, each pass **72/72 bounded commands (90 s command timeout)**. They verify original service/config/unit/binary, ordinary **524,288 B receive/send buffers**, measurement destination and every original backup, maintenance states, native qdisc/empty filters/firewall, zero players and quiet queues, no active workload processes/units, all earlier binary/archive/closed-state hashes, all six clean source/binary proofs on both hosts, and actual R2 sparse blob contents. Final free storage: game **8,820,174,848 B**, bots **18,975,293,440 B**. Both hosts are released.

The independent **5,380-file R2-start census has zero changed/missing files**. It includes all 5,206 historical paths. Against the older R1 census, 5,204 hashes already match at R2 start; the two parent-owned ledger updates exactly match parent commit `efbf4ec335430191db5d4124075f87bc64cbd97c` and were captured in the new baseline. This task changed neither ledger. All R1 reservation/report/private evidence and historical archives remain intact.

**47 Python checks pass: 36 clean-run + 11 native diagnostic**, including actual sparse checkout/source boundary, wrong revision/hash rejection, fresh namespace dispatch, byte budget, throttle ambiguity, timestamp boundary and actual frozen-recorder interoperability regressions. Rust source is byte-identical to `ab53573`; its retained validation is 239 passing tests, 2 ignored, Clippy with 2 old bot warnings, formatting and extension green. No expensive Rust rerun was needed.

Workload archive SHA-256 values (independently verified remote/local and during safe real extraction):

```text
game.tar.gz  297e566eb956dd3efe939c786b7828a73dffa0cb0d60e9a09829ea86a70e4e3e
bots.tar.gz  bed06f43d54a06efba9a43e791d0e25a93338a9ff6aea0b4fecd8397e529c70a
```

Private build/preflight/evidence bundles are retained and every file member is checksum-verified; their hashes and all audit/raw-output/analysis/controller proofs are in the machine summary. Exact commands and endpoints stay private. No PR, push, issue/map update, ladder advancement, threshold weakening or load-manufacturing change occurred. Remaining work belongs to the parent: resolve observer cadence and native final-drain evidence, retain the ambiguous throttle transitions and capture asymmetry, address the terminal controller race, then decide on a separately authorized continuation. **This single-attempt task is stopped.**
