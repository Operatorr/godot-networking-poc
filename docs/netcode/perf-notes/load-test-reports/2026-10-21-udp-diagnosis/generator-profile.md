# Sustained generator profile — aborted after early recording

**Exactly one workload launched; diagnostic incomplete; no capacity claim.** The new
controller stopped this run after the early profile because it incorrectly treated perf's
SIGINT return code **−2** as a recording failure. Offline validation establishes that the
retained early recording is usable. No second workload or late recording was attempted.
Historical **Strategy 100** remains the highest validated population.

The [compact summary](generator-profile-summary.json) preserves exact aggregates, window
points, profile/cleanup provenance and hashes. Full timelines, per-bot rows, addresses,
commands and raw profiles remain private. Parent ledgers and issues were not edited.

## Execution and controller defect

The intended condition was exactly [GENERATOR-PROFILE-PLAN.md](GENERATOR-PROFILE-PLAN.md):
Strategy 150, seed 30, difficulty 1, Warrior/Rogue/Mage rotation, 30 Hz input/Tick/Snapshot,
100 ms stagger, original AoI/LOD/budgets, 60 s global warmup and 300 s measurement. The
frozen game/bot/config and effective buffers were unchanged. World entropy was not fixed.

The workload ran **2026-10-21T14:25:58.784220+00:00 to
2026-10-21T14:26:45.348129+00:00**, **46.564934 seconds**. Actual Phase 2 was
**2026-10-21T14:26:15.771137+00:00**. Both real measurement schedules were atomically published with
**53.020977 seconds** of lead time; no dummy
window existed. Abort was at Phase 2 +28.872441 s.
The planned measurement interval **2026-10-21T14:27:15.771137+00:00 to
2026-10-21T14:32:15.771137+00:00 never began**. Capacity/delivery/strict-assertion gates are
unscored. The historical analyzer's false gates fail closed on missing observations;
they must not be read as measured capacity failures.

Perf was deliberately stopped using SIGINT at the window end. Its retained status reports
`reason=nominal-window-end`, no recorder error, complete readable data, and `rc=-2`.
The new local guard nevertheless required `rc == 0`; it classified this as
`profile-failure:early-recording-failed` and stopped the swarm. The three-second disposable
sampler validation had also returned −2 while validating **234/234** known call chains.
I failed to reconcile these two success criteria before launch. This is a diagnostic
controller defect, not evidence of game or generator collapse. The bot watchdog records
`controller-stop`, exit −15. Executed controller bytes are preserved unchanged, so the
parent can review and correct the gate before deciding on any new experiment.

## Early profile and missing late evidence

Only the generator was sampled. The supervisor was armed before launch and attached to
the verified bot PID/start identity and frozen executable. Configuration was installed
perf **7.0.0-38.38** (`perf version 7.0.14`), software `cpu-clock` **99 Hz**, DWARF **8192**,
monotonic clock, **256** mmap pages, no build-id-cache update and empty debuginfod URLs.
There was no game profiler, package installation, kernel/policy change or game/bot rebuild.

- Early enable/disable anchors: Phase 2 **+0.839149 / +25.001264 s**; observed active
  span **24.162114 s**. First/last actual samples: **+0.855460 / +24.999583 s**.
  The **0.839149 s missing prefix was not backfilled**. Disable acknowledgement extends
  about 1.264 ms past the nominal boundary; the last sample remains before +25 s.
- Recorder/supervisor lifetime **25.646 s**, below 30 s; data **14,633,481 bytes**, below
  30 MiB soft / 32 MiB hard bounds. Total recording is the same single 24.162 s interval
  and 14,633,481 bytes, below 50 s / 64 MiB aggregate bounds.
- **1,699 raw samples = 1,699 decoded samples**; zero lost, lost-sample, throttle or
  unthrottle records. Within matched clock/CPU anchors, **1,695 samples / 17.15 target
  CPU-seconds = 98.833819 samples/CPU-second**, 70.299650 samples/wall-second.
  Sampled periods sum to **17.161615990 CPU-seconds**.
- Clock correlation uses local UTC−monotonic anchors, median offset
  **1791890037878160640 ns**, spread **46,360 ns**. Exact UTC/monotonic
  anchors are in the summary; raw `/proc` CPU anchors remain private.
- Stack depth median **6**; **1,697/1,699** samples have at least two frames;
  **1,695/1,699** reach application main. Named leaves **1,001/1,699**;
  **698/1,699 (41.083%)** have unresolved leaves. Of these, 604 are attributed only to
  kernel/module DSOs, 84 to libc, five each to unknown/vDSO. Named ancestors often reach
  UDP send/receive, but unresolved leaves are not assigned invented function names.
- Recorder CPU/RSS: **0.360287 s / 16,740 KiB**. Per-profile supervisor:
  **0.374120 s / 27,488 KiB**. Phase-watching supervisor:
  **0.400664 s / 26,948 KiB**. These are instrumentation resource costs, not causal
  slowdown estimates.

The **late profile is null**: no dispatch, samples, CPU anchors, loss observations,
clock correlation or hot paths exist for +180..205 s. The full raw perf data is retained.
Offline commands were bounded; the 74,262,248-byte textual record stream was fully scanned
for counts while retaining only its 67,108,815-byte prefix. The decoded sample listing is
complete. This textual-prefix limit does not truncate `perf.data` or invalidate counts.

## CPU attribution and hypotheses

Percentages below are weighted by recorded CPU period; inclusive costs overlap.
Early self CPU: unknown **41.08%**, `Bot::poll` **15.01%**, hash-map iterator
`RawIterRange::fold_impl` **14.77%**, Snapshot `read_full_fields` **7.47%**,
`BuildHasher::hash_one` **4.12%**, and Snapshot `decode_body` **3.41%**.
Inclusive: ENet `enet_host_service` **39.85%**, outgoing commands **26.07%**,
Strategy `BehaviorState::decide` **21.19%**, and Snapshot decoding **14.54%**.
`Bot::poll` inclusive **98.88%** largely reflects its role as the caller.

The release has `.symtab` and unwind sections but **no `.debug_info`**. Bounded
`perf annotate` succeeded. Within `Bot::poll`, the relative range **+0x16c0..+0x171c**
(exclusive end) iterates four-byte entries, loads two u16 fields, and tests the second
field by shifting right four and comparing to `0x753`—equivalent to the frozen
`owner >= 30000` test. The following path checks reported-projectile membership and
looks up the entity. This matches the inlined owner iterator/filter in frozen
`scan_for_monster_hits`; it is **static disassembly/source correlation, not DWARF
source-line attribution**. Reconstructing counts from the 255-sample local-period
annotation gives **88 samples (5.1795% of all early samples)** in that iterator/filter
range. This is a subset of the scan, not its entire cost, and not all `Bot::poll`.

Consequently: hypothesis 1 has qualified evidence for an early owner-iteration cost,
but **owner-map occupancy, growth and late cost remain unknown**. Hypothesis 2 has
observed early transport/decode/Strategy costs, but their late shares are unknown.
Hypothesis 3 is not tested at the sustained failure: the observed early input cadence
is near 30 Hz with zero missed schedules. **Exact serial poll-cycle duration remains
null.** None of these observations identifies the cause of the prior sustained limit.

## Traffic, Tick, delivery and collector evidence

The nominal early +0..25 s interval had all **150 authenticated**, living **91–115**,
750 Ticks (**30 Hz**), Tick-work p99 **25.503070 ms**, maximum **49.769362 ms**.
Per-bot offered cadence from inner observations was **29.966925–30.008259 Hz**, with
**zero missed schedules**. Twenty-four complete UTC wire seconds yielded mapped
**27.291667–30.041667 Hz** per bot at both hosts. Mapped input totals were 107,499 game
and 107,489 bots, with 934,752 reliable retry-command bytes at each observer. Capture
placement/counts are not application delivery; the small endpoint differences remain
visible rather than being forced equal.

The adjacent profile-off interval was only **+25..+29.235336 s** of retained bot
observations, not the planned +25..50 s comparison. Offered cadence was
**29.780546–30.028717 Hz**, zero missed schedules. Four complete wire seconds gave
**28.75–30.25 Hz game / 29.00–30.25 Hz bots**, totals 18,003/18,007, and 125,522 reliable
retry-command bytes. Authentication remained 150. Early bot CPU was **70.99% of one
core** over the outer host bracket; the shorter off interval's inner three-second
bracket was **78.31%**. These unequal, evolving intervals do not measure causal profiler
overhead. Outer off-window bot CPU is null because its final host sample follows exit;
its 2,085 NoPorts increment likewise includes shutdown and is not attributed to the
profile-off workload. All late comparisons are unavailable, not zero.

Early sampled Snapshot age p99/max: **182.949 / 1,426.876 ms**; ActionConfirm:
**168.680 / 2,415.287 ms**. Eight early confirm-age observations were absent, not filled
with zero. Short off-interval p99/max: Snapshot **36.632 / 48.911 ms**, confirm
**56.438 / 66.147 ms**. These warmup message ages are not one-way latency or a scored
steady delivery gate. No final bot/strict-assertion report was produced after termination.

Across retained capture, **zero game/bot RcvbufErrors, SndbufErrors, InErrors or checksum
errors**, and zero observed receive-socket drops. Effective game receive/send buffers
were **4,194,304 / 524,288**, bots **212,992 / 212,992**. Early sampled receive memory
maxima were 275,520 / 7,872 bytes; both hosts had zero observed steal. Final bot counters
show zero baseline-reference misses, unknown delta entities, decode/send failures,
panics or missed schedules; these apply only to this short interval.

Both readers ended at EOF with **847,580 packets each**, zero parse errors/capture
loss and complete agreeing 150-identity mappings. Capture child CPU/RSS was
**2.255514 s / 38,836 KiB game**, **3.343580 s / 38,812 KiB bots**; retained capture
maxima **610,964 / 612,580 bytes**. Full host/collector costs, read-gap histograms,
transport counters and retry counts are in the summary/private evidence. Counting
sources were frozen at `994cce8c7cb2f689cd59f4d09e93e270057aba7e`; the existing
600-second capture wrapper was reused byte-for-byte. No parser, map or gate semantics
were relaxed.

The corrected byte-aware journal exporter scanned **42,509 records / 68,020,558 bytes**,
all MESSAGE byte arrays, with complete compact counts. It retained a **25,165,415-byte
raw prefix**, omitting 26,789 raw rows. Experiment oversized warnings: **42,105**;
full-workload warnings: **41,201**. There were no observed panic/suppression notices.
Steady-window warning/error counts are null because measurement never began.

## Provenance, restoration and handoff

Game revision `f1cc5d645217ddc14a4069c3fe40992d496270ae`, SHA
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`;
bot SHA `831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`;
private candidate config SHA
`642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`.
Fresh game PID/invocation/executable/buffers passed before launch and every runtime
poll; bot PID/start/executable was verified too. Exact argv, sources, compiler/kernel,
configs and runtime observations remain in private evidence. No Rust/gameplay edits.

The restoration timer was armed before stopping the original service. Its old measured
files were copied and hash-verified before restart; originals and prior candidate
artifacts were preserved. Cleanup stopped bots, verified exit, kept the five-second
quiet tail, stopped game then collectors, stopped profiler/supervisor units, restored
the ordinary service and canceled the restoration timer. Independent verification was
performed after the controller and **again after offline decoding**; the final audit
at **2026-10-21T14:32:56.594374+00:00** confirms original service/config/drop-in/measurement destination,
ordinary **524,288/524,288** game buffers, zero players, no owned bots/collectors/perf/
supervisors/timers, unchanged network/maintenance, prior archives and campaign state.
Both primary archives and the offline supplement match retained remote SHA-256 values.
No remote evidence was deleted.

Private local evidence: `deployment/hetzner/results/udp-generator-profile-20261021/`.
Remote originals: `/home/deploy/omega-results/udp-generator-profile-20261021/`.
Disposable sampler evidence is retained under the separate
`udp-generator-profile-tools-20261021` remote namespace and local
`udp-generator-profile-preflight-20261021/`. The unrelated untracked worktree was not touched.

```text
bots.tar.gz  8d215914fa5d896f3b4857fbd19a258d9f9721bf7ed808f0d673e818d3dd0f2b
cleanup.json  28260937d585c45d5c1bdfd7abb592eea9125044bed0ab2f2c1abb530b8378e2
final-verification-summary.json  8547d59b9b5e80077e9870d00978a47cee54413fd4d119ff2dbc071998b364ee
game.tar.gz  985a4501343bfbd79baaf7142dc8eb9f2264ba3ca5e5c3faac5e69f9ddd27a3c
manifest.json  8dfd58bbbd8f78174f41f7a5f46dcbc1305be7f58a664a75e9af8a298bee4b2a
offline.tar.gz  536a8ebcaf75fc44af3f07e97d79a944a8aee04fb3b6a5b5e8472d13bbacd086
preserved-measurement-sha256.txt  debaaf2a83f390e0bfc4d3080a424a376419bb0d287e5bae32b119bd3f53c155
udp_generator_profile.executed.py  faa67ca531f381d7b5885f4df7f22bed146148102667115b7d06655b956b3ed2
udp_generator_profile_analysis.py  90b2440a0db94b27a403e88c0c4e495235c09756ce686f25c4d916d46e18e1dc
udp_generator_profile_journal.py.executed  3cea54137acee768d020046b2d4e25c12557f39815cf584ce131c010831766f6
udp_generator_profile_record.py.executed  50866340cd3cd668c7042ef1129d0e46ddee6d59f87e6320a1313978e9682f1f
```

Nine local controller/analysis/atomic-publication tests pass, including string/byte-array
journals, bounded-prefix/full counts, unchanged swarm/collector behavior, expired-profile
refusal, raw/decoded sample count checks and CPU/clock weighting. Python compilation
passes. These tests did not catch the SIGINT-success mismatch; the executed controller
still contains it and is retained as evidence. No commit, push, tuning, extra workload,
CCX13 provisioning, sub-agent or parent-ledger change occurred.

The parent must decide whether to repair that diagnostic guard and authorize a fresh
experiment. Application-delivered input, owner-map occupancy, serial poll-cycle duration,
exact queue residence and causal instrumentation slowdown remain **null**. **Workloads
consumed: exactly 1. Late profiles: 0. New validated capacity: none.**
