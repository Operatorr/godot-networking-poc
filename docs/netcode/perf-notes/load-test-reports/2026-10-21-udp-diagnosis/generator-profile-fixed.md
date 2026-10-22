# Corrected sustained generator profile — 2026-10-21

**Exactly one workload completed; both profiles validated; generator-invalid; no new
validated capacity.** All 150 players stayed authenticated for the 300-second window
at 30 TickHz, but every bot offered **18.212983 Hz**, with **397,650 missed schedules**.
The strongest late sampled cost is Strategy processing: **19.37% → 51.21% inclusive**,
with hash-map iteration prominent. The qualified owner-iterator subset increased
**6.26% → 10.62%** of total samples. This narrows the generator investigation; it does
not measure owner-map growth or establish a causal fix. Historical **Strategy 100**
remains the highest validated population.

The [compact summary](generator-profile-fixed-summary.json) contains exact profiles,
clock/CPU anchors, on/off comparisons, cadence trajectories, counters, provenance and
cleanup. Repeated per-bot rows, full per-second timelines, raw IPs/stacks, commands and
connection details remain private. The parent owns the next intervention and ledgers.

The condition followed the final amendment in [GENERATOR-PROFILE-PLAN.md](GENERATOR-PROFILE-PLAN.md).
Fresh namespace: `udp-generator-profile-fixed-20261021`. Workload ran from
**14:50:31.916630 to 14:56:49.138269 UTC**, about **377.222 s**. Actual Phase 2 was
**14:50:49.058221 UTC**. The measurement window was **14:51:49.058221–14:56:49.058221 UTC**,
exactly 300 s after 60 s global warmup. Real schedules were atomically published with
**53.006812 s** lead; no dummy schedule or restart occurred. All **118** runtime polls
matched the fresh game identity. The swarm finished naturally with **exit 2**, caused
by the strict AoI assertion, without controller abort or watchdog failure.

The new controller imports the parent's corrected `profile_failure` function from
`udp_generator_profile.py`. Disposable preflight and live control use that same function
object. Before any workload, the actual disposable recorder returned **−2**, nominal
window end, no error, and passed the shared predicate. Its **234 raw = 234 decoded**
samples all contained the known leaf/middle/outer/main chain; loss/throttle counts were
zero and the disposable process exited. The existing disposable binary was hash-checked,
not rebuilt. The live early and late statuses likewise returned −2 nominally and passed.
Local tests exercise the real call sites, abnormal/early/forced exits, dispatch and
missing-status failure, expired dispatch, frozen swarm/collection, byte journals, sample
counts, and qualified disassembly. **17 unit tests**, compilation, actual disposable-status
replay and historical retained-profile replay passed. Lifecycle success was separately
followed by data validation.

Only generator CPU profiling was added to the frozen workload. Existing game revision
`f1cc5d645217ddc14a4069c3fe40992d496270ae`, SHA
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`;
control bot SHA `831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`;
private configuration SHA `642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`.
Strategy 150, seed 30, difficulty 1, Warrior/Rogue/Mage rotation, requested 30 Hz
input/Tick/Snapshot, 100 ms stagger, original AoI/LOD/budgets were preserved. Game effective
receive/send buffers stayed **4,194,304 / 524,288 bytes**; bot buffers **212,992 / 212,992**.
World entropy is not fixed. No game/bot rebuild, Rust change, logging suppression, network
or kernel-policy tuning, package installation, CCX13 provisioning, or additional agent.

Profiling used installed perf **7.0.14** (linux-perf package 7.0.0-38.38), `cpu-clock`
**99 Hz**, DWARF **8192**, monotonic clock, **256** mmap pages, no build-id-cache update,
and empty debuginfod URLs. The remote Phase-2 supervisor was armed before the swarm and
verified the bot PID/start/executable. No game profiling or kernel tracing occurred.

- **Early:** enable/disable at Phase 2 **+0.404256 / +25.003501 s**; active span
  **24.599245 s**. First/last samples **+0.423733 / +25.002237 s**. Missing prefix
  **0.404256 s** remains missing. Disable scheduling/acknowledgement crossed the nominal
  end by 3.501 ms; the last sample was 2.237 ms beyond +25, explicitly retained.
  Recorder lifetime **25.207859 s**, perf data **14,860,417 bytes**.
- **Late:** enable/disable **+180.499112 / +205.001047 s**; active span **24.501934 s**.
  First/last samples **+180.510182 / +204.992529 s**. Missing prefix **0.499112 s**.
  Recorder lifetime **25.220284 s**, data **20,276,545 bytes**.
- Aggregate active recording **49.101179 s**, data **35,136,962 bytes**, within
  50 s / 64 MiB. Each active interval was below 25 s, each lifetime below 30 s, and each
  data file below 30 MiB soft / 32 MiB hard bounds. Finalization used lifetime margin.
- **1,724 early / 2,363 late raw samples equal decoded samples**, total **4,087**.
  Lost, lost-sample, throttle and unthrottle records are all zero. Matched CPU-anchor
  windows contain **1,721 / 17.44 CPU-seconds** and **2,363 / 23.89 CPU-seconds**:
  **98.681193 / 98.911679 samples per CPU-second**. Sampled periods total
  **17.414141 / 23.868687 CPU-seconds**.
- UTC−monotonic median offsets are **1791890037878160480 / 1791890037878160680 ns**,
  anchor spreads **44,361 / 63,761 ns**. Exact clock/CPU endpoints are in the summary.
- Stack depth median **6 / 5**; at least two frames **1,723/1,724 / 2,363/2,363**;
  reaching application main **1,715/1,724 / 2,361/2,363**. Unknown leaves are
  **763 (44.26%) / 435 (18.41%)**: **677 / 359** are kernel/module DSOs, **71 / 72**
  libc, with the remainder vDSO/unknown. Named ancestors do not invent unknown leaf names.
- Perf child CPU **0.304289 / 0.300212 s**, max RSS **16,304 KiB** each. Per-recording
  supervisor CPU **0.377975 / 0.396593 s**, RSS **26,476 / 27,528 KiB**. Phase-watching
  supervisor CPU **1.066326 s**, RSS **27,424 KiB**. These are instrumentation costs,
  not estimates of causal slowdown.

The full perf data and decoded sample listings are retained. Raw textual record streams
were fully scanned for counts: **75,546,548 / 102,173,367 bytes**, retaining bounded
prefixes **67,108,799 / 67,108,805 bytes** and omitting **8,437,749 / 35,064,562 bytes**
from text retention. This does not truncate `perf.data` or substitute prefix counts for
complete counts. Both offline decoders exited zero. Primary and offline archive hashes
match their retained remote originals.

CPU shares use sampled CPU periods. Self samples are leaf instructions; inclusive shares
overlap and must not be added. Early → late self costs: hash-map `RawIterRange::fold_impl`
**13.28% → 35.29%**, `Bot::poll` **15.37% → 16.12%**, `BuildHasher::hash_one`
**4.23% → 11.00%**, Snapshot `read_full_fields` **7.37% → 6.14%**, Snapshot
`decode_body` **2.84% → 2.20%**. Inclusive Strategy `BehaviorState::decide` grows
**19.37% → 51.21%**, ENet `enet_host_service` falls **41.88% → 16.17%**, and Snapshot
`decode_body` falls **14.73% → 10.16%**. Absolute sampled Strategy CPU rises
**3.374 → 12.222 s** across almost equal recording spans; Snapshot decoding remains
**2.566 → 2.424 s**. `Bot::poll` is **98.67% / 99.37% inclusive**, as a broad caller,
and cannot be assigned wholesale to a single scan.

The unchanged release contains symbols/unwind data but no `.debug_info`. Bounded annotation
succeeded in both windows. Relative `Bot::poll` range **+0x16c0..+0x171c (exclusive)**
iterates four-byte entries, loads two u16 fields, and checks the owner threshold using
right-shift four / compare 0x753, followed by reported-projectile membership/entity lookup.
This matches the frozen `scan_for_monster_hits` iterator/filter. Reconstructed from rounded
local-period annotation: **108/1,724 early (6.2645%)** and **251/2,363 late (10.6221%)**.
This is qualified static disassembly/source correlation for a subset of the scan, not
DWARF source-line attribution or its complete cost. Actual owner-map occupancy is unknown.
Frozen Strategy source also scans entity/owner maps; these profiles alone do not assign
all Strategy iteration to one source loop or prove which collection grew.

The ranked hypotheses therefore resolve only partly. Owner-iteration cost is larger late,
supporting further investigation of history/scan work, while occupancy/growth remains
unmeasured. Strategy/map work is the largest resolved late inclusive cost; transport and
decode remain material but do not dominate that late sample. Missed schedules align with
the generator's near-one-core CPU use, consistent with serial work exceeding its cadence
budget; exact polling-cycle duration and causal scheduling mechanism remain null.

Cadence and profile-on/off comparisons retain actual boundaries and one-second trajectories:

- Nominal **+0..25 s on:** offered **29.989846–30.031211 Hz**, zero missed schedules,
  bot CPU **70.97%** of one CPU; mapped wire **28.291667–30.0 Hz**, retry-command bytes
  **904,913** across complete UTC seconds.
- **+25..50 s off:** offered **29.897129–30.021012 Hz**, **34** missed schedules,
  CPU **86.53%**; wire **29.208333–30.0 Hz**, retries **2,944,453 bytes**.
- **+155..180 s off:** offered **18.812704 Hz**, **31,800** missed schedules,
  CPU **97.68%**; wire **18.625–18.833333 Hz**, retries **9,296,856 bytes**.
- Nominal **+180..205 s on:** offered **18.902584 Hz**, **29,700** missed schedules,
  CPU **97.44%**; wire **18.541667–18.916667 Hz**, retries **7,743,701 bytes**.
- **+205..230 s off:** offered **18.266553 Hz**, **32,850** missed schedules,
  CPU **97.64%**; wire **17.291667–18.291667 Hz**, retries **8,031,544 bytes**.

These are inner bot-counter observations, outer host CPU brackets, and complete UTC wire
seconds, not identical endpoint estimators. The summary preserves every bracket, input-gap
histogram, delivery tail, socket/error delta and Tick statistic. The per-second trajectory
shows the cadence loss near **+50..60 s**, while profiling was off; after +60 s most input
gaps move to the longer histogram buckets. The pre/on/post late rates do not demonstrate
causal profiler slowdown. Population is 150 and Tick rate 30 in all five nominal windows.
No receive errors occurred. The +25..50 outer host bracket had **316** game send-buffer
errors; +205..230 had **150**; other listed brackets had zero. Warmup age spikes and these
evolving workloads are retained rather than treated as a controlled overhead experiment.

For the full measurement, offered input was **18.212983 Hz** for every identity; exact
mapped wire input was **14.546667–18.133333 Hz** at both endpoints. Full-workload missed
schedules: **400,479**. The 9,000 Ticks give **30.0 Hz**; Tick-work p99 **26.270360 ms**,
maximum **50.617254 ms**, 11 Ticks at/above 33.333 ms. Ending accumulator lag **0.133073 ms**;
elapsed-Tick lag **−2.363969 ms**. Deferred-wait first/last-30-second means
**6.207778 / 6.185556 Ticks**; pending replication **4,244.08 / 3,184.48**. The unchanged
backlog rule passes. Living population **95–144**, projectiles **144–255**, monsters **0–1**.

Generator CPU is **97.680953%** over the strict inner **299.044994 s** host bracket;
game CPU **69.788293%** over **299.047291 s**. Steal is zero. The outer matched bot CPU
endpoint is **null**, because its final host sample follows bot exit; it was not filled
from another interval. Per-second CPU statistics and exact inner endpoints are retained.
Maximum sampled receive memory: **592,560 bytes game / 22,576 bots**. Receive-buffer
errors and observed receive-socket drops are zero. Game send-buffer errors are **580
full-workload / 264 steady**, matching **580 / 264** measured zero-byte sends; reported
application send failures remain zero. The steady transport read-gap cumulative maximum
is **54.225424 ms**. These observations do not measure exact queue residence or application
input delivery.

All bots increased Snapshot and ActionConfirm counts. Aggregate steady age p99/max:
Snapshot **58.197 / 106.741 ms**, ActionConfirm **198.875 / 1,859.321 ms**. Nine identities
(**2, 5, 6, 10, 15, 19, 22, 74, 101**) fail the predeclared per-bot delivery gate; their
individual age tails are private. Missing samples remain missing. Strict `aoi_cull` fails
at **81/150** within 1,150 units versus 95% required; `decode_clean` passes; budget assertion
is skipped under the unchanged zero rate-budget configuration. Full workload has **3
baseline-reference misses / 109 unknown delta-entity observations**, zero decode failures,
reported send failures or panics. Steady-window totals are **2 / 4** respectively, also with zero decode/send/panic errors. No claim of a clean correctness run is made.

Across 299 complete UTC measurement seconds, game-side retry-command bytes total
**108,361,853**, incoming ACK commands **36,518,536**. These retain v2 bounded-history
counting semantics; retries are observed repeated sequences, not complete ACK queue state.
Endpoint captures precede socket delivery. Equal measured input counts do not prove
application delivery. Exact outstanding reliable queues remain unknown.

Collectors used revision `994cce8c7cb2f689cd59f4d09e93e270057aba7e` and the existing 600 s
wrapper. Both readers ended at EOF: **6,992,118 / 6,992,127 packets**, zero parse/capture
loss, agreeing unique 150-identity mappings and complete window coverage. The nine-packet
endpoint difference remains visible. Capture children used **18.217812 / 26.769369 CPU s**,
max RSS **40,880 / 38,812 KiB**, retained maxima **5,165,288 / 5,165,837 bytes**.
Host collector self/child costs were **1.047% / 2.706% game**, **1.303% / 2.675% bots**.
All original ramp/workload/capture/restoration bounds remained **180/550/600/720 s**, with
48 MiB capture, 64 MiB files and 512 MiB capture cgroups.

One offline compatibility issue was explicit and regression-tested: at Phase 2
**−12.452234 s**, `ss` reported a swarm-cgroup socket inode but no process owner. The
historical parser rejected it. The new analyzer retains **PID=null**, actual counters
(receive memory/drop zero, buffers 212,992), and the missing-attribution record. No PID
was invented; no collector, mapping, counting, or live gate changed. That row precedes
the steady and both profile windows. The historical analyzer/source remains untouched.

The byte-aware journal exporter fully scanned **430,424 MESSAGE-array records /
691,238,235 bytes**, retaining only **25,164,965 bytes**; **414,763** raw records were
omitted from retention. Complete compact counts show **429,968 oversized warnings
full-workload / 349,506 steady**, no panic or suppression notices. Payload-size extrema
are **null** because the bounded exporter does not count them. No unbounded raw journal
or online full log was retained. Full-count completeness and raw-prefix completeness
are separate fields.

Restoration was armed before stopping the original service. Original measurement files
were copied and hash-verified before restart; all original/candidate binaries were
preserved. Cleanup verified bot exit, kept the five-second quiet tail, stopped game,
then captures, and stopped all profile/supervisor units before restoring the ordinary
service and canceling the timer. Independent audits passed before offline decoding and
again afterward, finishing **15:04:25.270489 UTC**. Both confirm original service/config/
drop-ins/measurement destination, ordinary **524,288/524,288** game buffers, zero players,
no owned bots/collectors/perf/supervisors/timers, unchanged network/maintenance, prior
archives and closed campaign state. Remote evidence remains intact.

Private evidence: `deployment/hetzner/results/udp-generator-profile-fixed-20261021/`.
Retained remote originals: `/home/deploy/omega-results/udp-generator-profile-fixed-20261021/`
on both hosts. The compact summary hashes all executed/new helpers, preflight proof,
archives and final audit. Primary archive/manifest hashes:

```text
game.tar.gz  3b3945533380427f42b943ac454ee8f99e32800675729b0bb4a00869877c7cab
bots.tar.gz  c6abe451b962d6e169436642e862105278a88758c08da9fa0cab299aa5a46b2b
offline.tar.gz  c2eb1e796c4d9a76c79073e61e3df993de742f54d3137fe1a46b8c6a58dc04ba
manifest.json  1d46a680fad8a13121d4c9e3c9edd78c732e74b861596ea730e1eff553931850
final-verification-summary.json  37925d949a0c966e267ba4858cb6bfb241dc2d4019f119edfb545cb45129556d
udp_generator_profile_fixed.executed.py  d48c661e3935b1712ff15fd8fa3850d0038f221bad98a4732b86d467a85a0b9d
```

No historical report/controller/executed evidence, parent ledger/plan, unrelated worktree,
Rust source, commit, or push was changed. No second workload was launched. Application-delivered
inputs, actual owner occupancy, serial poll-cycle duration, exact queue residence and causal
instrumentation slowdown remain **null**. The result is ready for the parent's next decision.
