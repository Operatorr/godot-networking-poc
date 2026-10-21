# Instrumented Strategy 200 control — 2026-10-21

**One diagnostic run; population collapse; no capacity or performance improvement claim.** This control for [issue #38](https://github.com/Operatorr/godot-networking-poc/issues/38) used exact commit `cc86869f1cc0f3d5d219e880d08b2cfda312f4eb`, including server observation `466e62c` and bot ramp recording `3b910cd`. The frozen baseline and profile remain separate conditions. Strategy 100 remains the historical validated rung.

The swarm ran **43.057510 s**, from **12:28:33.430109 to 12:29:16.486766 UTC**. The controller stopped it after two polls below 65% of its observed authenticated peak. Per-Tick maxima were **182 authenticated / 125 living**, separately; the last retained Tick had 69 authenticated. All 200 bot identities eventually reached Running, and Phase 2 began at **39.328152 s**, after earlier peers had already disappeared from the server. This is neither 200 simultaneous players nor a useful steady window. The controller stopped the game before terminating the bots; the final bot observations and host counters include that short cleanup tail.

[Machine-readable evidence and exact interval boundaries](instrumented-control-summary.json) accompany this report. Raw evidence stays in ignored `deployment/hetzner/results/udp-control-20261021/`. No second workload, profiler, capacity tuning, commit, or sub-agent was used.

## Overflow, read opportunities, and actual send outcomes

The first game-host receive-buffer error interval was **12:28:49.908710–12:28:50.908816 UTC**, **16.478601–17.478707 s after launch**, with **33 drops**, **146–153 authenticated players**, and **64.9931%** game-process CPU (100% = one logical CPU). The first bot-host interval ended at **29.968513 s**, with 78 errors and 178–181 authenticated players on game.

Game `Udp:RcvbufErrors` increased **149,140**, exactly matching the fresh game socket's observed drop total. Bot host increased **4,031**, matching the sum of maximum observed drop counters across its 200 sockets; 22 sockets dropped. Effective receive/send limits stayed **524,288 / 524,288 bytes game**, **212,992 / 212,992 bots**. Maximum sampled receive memory / Recv-Q was **524,256 game / 212,944 bots**. These are sampled maxima, not subsecond peaks.

Final transport counters: **294,007 receive calls**, **257,472 datagrams**, **36,535 empty reads**, **0 receive errors**; **315,960 send calls**, **969 zero-byte sends**, **0 send errors**. The **969** zero-byte sends match the game-host `SndbufErrors` delta, exposing the adapter's nonblocking `WouldBlock` outcome despite **zero application enqueue/send errors**. Kernel receive drops need not produce adapter receive errors.

The initial overflow happened while read gaps were still below a Tick: cumulative maximum was **25.879035 ms** at the server sample 17.324 s after launch, then **26.908249 ms** at 18.324 s. In the 16.324–17.324 s server interval there were ten gaps in `(20, 33.333] ms`, none above 33.333 ms. A long late stall therefore does **not** explain the first drop by itself. Later the cumulative maximum reached **443.413725 ms**. The full observed workload counter difference contains **36 gaps >100 ms** and **51 >33.333 ms**.

Read gaps measure time between receive attempts, including idle sleep; they do not measure packet arrival or residence in the receive queue. Cumulative maxima are reported as maxima, never subtracted. Histogram counts and sums are differenced between timestamped samples. A gap or phase spanning a sample boundary is charged when its observation completes.

## Before/after onset and late behavior

The requested windows are ten seconds before the lower onset bound, ten seconds after its upper bound, and the last ten seconds before bot termination. Each source uses its retained inner boundaries: server intervals span **9.019735 / 8.787744 / 6.126751 s**. Wire comparisons use equal **nine complete UTC seconds** before and after onset; there is no usable late wire window.

- **Server loop wall-time fractions, before → after → late:** service/routing **10.703% → 24.512% → 64.999%**; World Tick including replication **20.762% → 40.789% → 16.229%**; outbox **6.148% → 13.470% → 4.969%**; ENet flush **5.227% → 12.132% → 3.777%**. These are elapsed phase measurements, not CPU profiles. Whole-run cumulative maximum service/routing duration was **356.987298 ms**. World Tick maximum was **20.256998 ms**; the wider Tick-work timer reached **41.976576 ms** because it includes outbox and transport flush.
- **Read-gap counts before → after:** `(20,33.333] ms` **6 → 120**, `(33.333,50]` **0 → 5**, `(50,100]` **0 → 6**, `>100 ms` **0 → 10**. The late retained interval adds six >100 ms gaps.
- **Wire evidence at game, before → after:** input commands **27,193 → 45,040**; incoming UDP datagrams **70,647 → 142,491**; incoming ACK commands **443,299 → 1,877,283**; reliable retry command bytes **132,337 → 13,688,810**. Retries are repeated ENet reliable sequence/channel/port keys within 60 seconds, including command headers. This measures retransmitted traffic, not outstanding queue length or duplicate-ACK identity.
- **Generator-side confirmation:** inputs **27,193 → 45,057**, incoming-to-game ACK commands **443,299 → 1,877,283**, and retry bytes **132,337 → 13,688,810**. Small cross-host bin differences are not a packet-loss estimate: clocks and bin boundaries differ. Directions in the collector are semantic (`out` = game→bots) on both hosts.
- **10 ms burst bins at game, before → after:** peak incoming datagrams **268 → 590**, peak input commands **117 → 200**, and peak incoming ACK commands **5,713 → 15,508**. Bot-host input peaks were **117 → 208**. Timestamp backsteps can split a bin in the raw file; analysis merges equal bin timestamps before taking maxima.

These observations support **reliable retry/ACK traffic as an amplifier after overflow**, consistent with the prior frozen CPU profile. Initial read delays, growing replication work, and arrival bursts remain candidates for onset. This run does not establish the causal intervention or attribute late service time exclusively to ACK removal. No current CPU profile was taken.

## Ramp cadence and application delivery

The repaired recorder retained **44 bot samples**, **40 during ramp**, all ramp `phase_s=null`. For identities Running at both ends of each adjacent sample interval, median input rate was **29.8946 Hz before**, **29.8483 after**, **29.8052 late**. Corresponding minima were **29.5640 / 28.7861 / 20.5775 Hz**. These distributions include per-bot intervals, not independent run repetitions. Dead bots also send zero-input frames.

The full retained cumulative bot totals were **164,373 inputs**, **46 missed schedules**, and maximum observed input gap **87.501173 ms**; none of the recorded input-gap histogram observations exceeded 100 ms. The selected before/after windows had zero missed-schedule increments. Before onset, 286 gaps were in `(40,50] ms` and none in `(50,100]`; after onset these became **4,980 / 1,202**. Scheduling jitter increased even while average offered cadence stayed near 30 Hz.

Each endpoint's complete port-second records have median **30 input commands** before and after onset, maximum **31**. These distributions contain nonzero port-seconds and partial joins; they exclude silent port-seconds and are not a per-peer validity pass. **Bot-ID↔port correspondence is null:** the collector's final mapping file was not flushed before its guard exit. Per-bot scheduler and per-port wire observations are retained, but their individual correspondence cannot be established from this capture.

For Running bot samples, median time since last Snapshot was **16.51 ms → 22.69 ms → 1.061 s**; since last ActionConfirm **16.38 ms → 95.23 ms → 1.251 s**. Late p99 values reached **10.688 s Snapshot / 15.712 s confirm**. These are application-observed ages, not one-way network latency or server input age; late samples include the cleanup tail. Actual per-command queue residence and server-received per-bot input cadence remain **null**.

Bots recorded **0 decode failures, 0 send failures, 0 panics**, plus **1,520 baseline-reference misses / 1,395 unknown delta-entity observations**. These are correctness/convergence evidence for the parent and issue #39, not a newly proven root cause. Server application decode/send counters were zero. The bounded 4,000-line game-log tail contains **3,837 oversized-unreliable warnings**; this is not a full-run warning count. No join-failure line was retained.

## Collection coverage and perturbation limits

The [controller](../../../../../scripts/load_campaign/udp_control.py) reused the baseline guards: ramp ≤180 s, postjoin ≤120 s, 305 s swarm service bound, 0.5 s join-failure checks, two-poll population-collapse guard, stale observation/log guards, and 420 s service restoration timer. Host/socket observations ran at 1 Hz. No nft counters, mirror interface, qdisc change, or perf sampler was added.

The [capture supervisor](../../../../../scripts/load_campaign/udp_control_capture.py) invokes existing `capture.py --article` and a separately compiled diagnostic flow recorder. It retains fingerprints at 1/64 sampling, one-second flow/port counts, and 10 ms traffic bins; **no full pcap or packet-payload archive**. Bounds: **300 s**, **48 MiB retained-size polling guard**, **64 MiB per-file hard limit**, **512 MiB cgroup memory**, and **2,000,000 reliable-command state entries**. The base `flow_record.rs` parser and `article_flow.rs` were copied into new diagnostic sources with their original SHA-256 identities embedded. Existing collectors were not edited. Two parser unit tests and four wire replay tests passed, covering truncation, ACK/retry/sequence wrap, ramp port counts, burst bins, and unsigned test-handshake mapping.

**Both readers exited at the explicit reliable-state limit.** Complete one-second flow/port evidence ends at **27.569891 s after launch**; flushed 10 ms bins reach about **28.05 s**. Reader shutdown and capture draining finish later. Consequently the before/after onset windows above are usable, but late wire retries/cadence, final flow summary, final mappings, total parsed packets, and malformed-packet count are **unknown**. Capture loss accounting cannot repair that parser-tail omission. No second experiment was launched to fill it.

Tcpdump reported **500,238 captured / 500,786 filter-received / 0 kernel-dropped packets game**, and **500,278 / 500,596 / 0 bots**. These are tcpdump counts, not validated parsed-packet counts. Capture subprocess CPU was **3.048829 s over 35.326359 s game**, **3.271116 s over 31.568897 s bots**; supervisor CPU **0.100677 / 0.091061 s**. Child maximum RSS was **205,252 / 205,208 KiB**. Host/socket collector self+child CPU was **3.980483% / 4.038734%** of one CPU over its full windows. No memory, retained-size, or wall-time cap was reached; the command-state guard ended collection first.

Game active-process CPU averaged **66.163807%**, peak **99.989061%**; bot CPU **52.016870%**, peak **78.992210%**. Game spent **13.004697 s** at ≥95% of one CPU. Steal was zero. These are resource observations. **Causal collector/instrumentation slowdown remains unknown**; no matched observer-off workload was run. Earlier onset than the frozen baseline/profile cannot be attributed to instrumentation or treated as a capacity regression/improvement. The game world is entropy seeded; bot seed 30 does not fix it.

Host counter windows differ: **53.014269 s game / 56.007945 s bots**. Final game `NoPorts=4,730` includes the interval after game shutdown while bots were still running. Interface drops, checksum errors, and memory errors were zero; all raw host counters and clock checks remain private. Both clocks reported synchronized with sub-0.2 ms offsets and roughly 2 ms dispersion; no finer causal ordering is inferred.

## Exact identities and restoration

Both hosts fetched `perf/cax11-udp-capacity-20261021` and created a **new detached checkout** at `/home/deploy/omega-udp-control-cc86869`, pinned to the full commit above regardless of later branch advances. Both packages were built independently on **both hosts**, using their new `rust/target` directories:

```sh
CARGO_TARGET_DIR=/home/deploy/omega-udp-control-cc86869/rust/target \
  cargo build --release --locked -p omega-server -p omega-load-test
```

The resulting hashes matched across hosts:

```text
/home/deploy/omega-udp-control-cc86869/rust/target/release/omega-server
5a36a7aaf3bed4db46efd2a4200c4e02825ef3598d0c4990a672d279c051a202
/home/deploy/omega-udp-control-cc86869/rust/target/release/omega-load-test
831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3
```

Compiler: **rustc 1.95.0 (`59807616e`, LLVM 22.1.2)**, `aarch64-unknown-linux-gnu`; Cargo **1.95.0 (`f2d3ce0bd`)**. Compiler executable SHA-256 `db0c9200524653ed0ff20a2950b49402879887ad4932c4de18606df9de5cf3d9`; Cargo executable `959e627e4d7b8d8b618d32ae7af795ce9f1544656822eb9d407b4fd76a4f53b0`. Cargo.lock `904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b`. Release profile uses thin LTO; no additional Rust flags, Cargo build/profile environment overrides, or local/global Cargo config files were present; package fingerprints report empty Rust flags. Kernel remained `7.0.0-30-generic`.

Workload stayed **Strategy 200, seed 30, difficulty 1, 100 ms stagger, 30 Hz input**, default Warrior/Rogue/Mage rotation; native config hash `bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`, 30 Hz Tick/Snapshot, AoI 1000/exit 1100, default/max budgets 120000/200000. The only service override selected the instrumented executable and private measurement path. Running `/proc/PID/exe` hash matched the control artifact.

Preflight verified idle ownership, zero population, original binary hashes, native network/config, and free disk above 8 GiB. Current pre-run measurement files were copied and hash-verified before restart. **Original binary directories were neither reused nor overwritten.** Frozen game remained `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`; frozen bots remained `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`.

Independent final verification at approximately **12:30:32 UTC** found the ordinary game service active with **zero players**, no runtime control override, no swarm/capture/profiler/compiler/package-job leftovers, restored original unit/config, unchanged qdisc/filters/firewall and closed campaign state. Both maintenance timers remain active/enabled; update services inactive. The preserved pre-run measurement copy passed a second complete checksum verification. All collectors stopped before archiving. Local bundles were SHA-256 verified against remote bundles; **no remote evidence or originals were deleted**. New detached builds and private evidence remain available for the next comparison.

```text
game.tar.gz  f24962009331110abc48559bc7b8bfc438cb48fe51067095f5faebcbeb1db2be
bots.tar.gz  4f4a1be12791944de2fa8385b742ef194e7be4305f7b00bb74532f80c7307578
```

The summary records executed controller/collector/source hashes, compiler/build-setting evidence hashes, archive hashes, exact counter windows, nulls, and cleanup proofs. The next experiment should retain mapping/parser accounting incrementally and bound reliable-state tracking without losing finalization; this run's missing tail must remain missing. Parent server/bot source changes and existing baseline/profile files were not edited.
