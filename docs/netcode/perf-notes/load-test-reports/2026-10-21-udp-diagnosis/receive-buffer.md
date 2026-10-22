# Receive-buffer diagnostic — 2026-10-21

**Exactly one workload; population-collapse failure; no new validated capacity.** Requesting
2,097,152 receive bytes produced **4,194,304 effective bytes**, with game send unchanged at
524,288 and bot receive/send unchanged at 212,992. The larger receive queue delayed observed
loss and allowed all 200 bots to authenticate, but did not sustain them. The game still incurred
**159,266 socket-attributed receive-buffer errors**, accumulated larger queues, and developed
long read stalls and message ages. This supports burst absorption followed by throughput
failure, rather than a useful capacity increase. The historical Strategy 100 result is unchanged.

[Machine-readable evidence](receive-buffer-summary.json) contains exact counters, source-specific
windows, per-identity cadence, joint population/entity comparisons, hashes and unknowns.
This comparison is additionally qualified by a **pre-swarm instrumentation panic/restart**,
the explicitly changed identity parser, and live mapping polling. It is not perfect single-factor
equivalence. No second workload, rerun, subagent, commit, profiler, kernel/policy change or
parent-source edit occurred.

## Outcome and experimental bounds

The swarm ran **13:25:09.287673–13:26:01.867622 UTC**, watchdog elapsed **52.580846 s**.
Phase 2 began at 13:25:35.787610 UTC; neither the 120-second postjoin diagnostic nor the
ordinary capacity window completed. The controller observed 111 authenticated players at
+43.163 s and 44 at +48.133 s, both below 65% of the peak 200. It then stopped the run.
Peak counts were **200 authenticated / 154 living**. Bot-local `Running` remained 200 in the
last observation: that state is not authoritative authentication or proof of useful delivery.

The first finally action sampled game sockets, then stopped the game, stopped its collectors,
and stopped the swarm. Consequently the watchdog endpoint includes cleanup. The summary
retains those original endpoints and separately supplies **`pre_abort_last_10s`** and
**`active_until_controller_abort`**, ending at the +48.133 s decision observation. Comparisons
through 40 seconds precede cleanup. Controller polls actually occurred about every five seconds,
including SSH work and the specified two-second sleep; two live-map reads contributed about
one second per poll. Guard thresholds were unchanged, but this polling overhead is a difference.

Settings were the specified Strategy 200, seed 30, difficulty 1, normal Warrior/Rogue/Mage
rotation, 30 Hz inputs, 100 ms stagger. Game configuration retained 30 Hz Tick/Snapshot,
AoI 1000/exit 1100, LOD 400/1000, budgets 120000/200000, monster difficulty 0.85, isolated
unsigned Arena, no API/persistence. World randomness remains entropy-seeded; bot seed 30 does
not make entity trajectories identical.

Bounds: ramp 180 s, postjoin 120 s, swarm 305 s, restoration 420 s; existing join-failure,
population, stale-game and 8 MiB log guards. Capture 300 s, 48 MiB retained guard, 64 MiB per
file, 512 MiB cgroup, 1/64 fingerprints, 1 s host/socket and flow/port observations, 10 ms
burst bins. No full pcap or additional workload was used for validation.

## Pre-swarm instrumentation failure and runtime identity

The initial candidate PID **583034** passed direct executable-hash and startup/socket gates.
At **13:25:00.072349 UTC**, before the swarm existed, its measurement reader panicked:
`valid measurement window: Error("EOF while parsing a value", line: 1, column: 0)`.
The inherited controller publishes `window.json` through a direct, non-atomic scp while the
server's `measurement.rs` reads it and calls `expect` on JSON parsing. The empty/partial-file
race explains this observed failure; it was not a gameplay load failure.

Systemd restarted the same candidate as **PID 583102**, invocation
`823e82081b7e43f286a556df4f13fe18`. Its startup at **13:25:03.245245 UTC** independently logged
request/effective receive **2097152/4194304**, send **262144/524288**. A host/socket sample
**0.984 s before swarm start** identified this PID with receive memory 0, drop count 0 and
limits 4194304/524288. Only PID 583102 appears in workload socket samples. Thus the actual
buffer condition is verified before bot traffic, despite the controller not noticing the restart.

The controller's captured invocation remained the initial one, so its original `game.log`
contains nine startup/panic lines and is **not the workload log**. Post-run read-only journal
retrieval recovered the actual invocation's bounded 4,000-line tail, startup records and a
bounded 8,000-record unit window in a separate checksummed supplement; the original bundle
was left intact. No workload was relaunched to repair the evidence.

`/proc/PID/exe` was hashed only for the initial PID. The replacement's journal identifies the
candidate executable path; that file's hash is unchanged before and after, and its startup
records and socket samples agree. The replacement hash is therefore **inferred from the unchanged
path**, not directly measured through its `/proc` entry. The summary keeps that direct hash
null and preserves the initial proof separately. This and the restart qualify the comparison.

**Parent follow-up:** publish measurement files atomically or before starting the service;
recheck PID/invocation, runtime hash and buffers immediately before swarm launch; collect logs
for every experiment invocation. These defects are reported here only—no parent Rust, prior
report or ledger was edited, and the new controller is retained as executed.

## Drops, queues, processing and delivery

First game-host loss was bracketed at **+25.019750–26.019890 s**, **197–199 authenticated**,
2,605 errors, approximately **98.99%** game-process CPU. The socket observation ended at
+26.074964 s and found the same 2,605 drops on PID 583102/inode 2108895. The bounded-collector
control first lost packets at +15.126376–16.126495 s, 135–142 authenticated, with 40 errors.
These one-second windows do not determine the exact first-drop instant.

At +14.981–17.984 s the candidate's cumulative maximum read gap was **26.990 ms**, with no
receive drops. It reached **64.234 ms** by +24.037 s, **237.794 ms** at +26.218 s and ultimately
**703.726 ms**, versus control's 455.286 ms. This is consistent with absorbing the earlier
short bursts, then encountering a much larger processing backlog. Read gaps are time between
receive attempts, including sleep; **packet residence in the queue remains unknown**.

Across the host collector windows (63.009648 s game, 66.010185 s bots, including setup/cleanup):

- Game `RcvbufErrors` **159,266**, exactly matching the fresh dropping game socket; send-buffer
  errors 0. Bot receive errors **11**, all 11 observed on one bot socket. No unattributed bot
  receive-error remainder. Control had 162,406 game errors and 5,466 bot-host errors over
  different windows/populations, so full-run totals are not a matched improvement estimate.
- Sampled receive memory peaked at **4,193,984 bytes game**, versus control 523,904; bots peaked
  at 13,744. Increased queued memory counts against useful capacity. Queue residence and
  outstanding reliable-queue length remain unknown.
- Interface drops, qdisc drops/overlimits, UDP checksum/memory errors and CPU steal were zero.
  Game `NoPorts` increased 6,146 after the server stopped while bots were still running;
  this is not equivalent to gameplay socket overflow. Bot `NoPorts` was zero.
- Final game adapter totals: 396,961 receive attempts, 368,712 datagrams, 28,249 empty reads,
  zero receive errors; 388,384 sends, zero send errors/zero-byte sends. Application send/decode
  errors were zero. These counters do not report kernel-dropped datagrams as decode failures.

For candidate windows before onset / after onset / final ten seconds **before the abort decision**,
inner server timing spans 8.057337 / 8.908007 / 8.303088 s. Service/routing consumed
**15.28% / 45.48% / 54.42%** of wall time, World Tick including replication
**39.21% / 32.97% / 14.08%**. Final cumulative maximum service phase was **1,358.221 ms**;
World Tick maximum was 21.066 ms. Phase wall time is not CPU hot-path attribution.

Those windows each contain nine complete UTC wire seconds. Game-side reliable retry-command
bytes rose **1,697,320 → 17,197,948**, then fell to 2,385,284 as population collapsed;
incoming ACK commands were **1,429,297 / 1,871,463 / 337,849**. Incoming 10 ms datagram peaks
were **317 / 696 / 426** and ACK-command peaks **7,615 / 21,027 / 10,342**. Reliable traffic
and service amplification persisted after overflow. Retry semantics are the same v2 rolling
32,768-sequence window as the bounded control, without a TTL; unseen half-range advances or
port reuse cannot be disproved by these compact artifacts.

Pre-abort Snapshot-age median/p99 was **0.279 / 9.812 s**; ActionConfirm-age median/p99
**0.842 / 17.658 s**. These are message ages observed by bots, not one-way latency or queue
residence. The last-ten-seconds window ending at actual swarm termination is worse and includes
cleanup, so it is retained separately rather than used as the primary late gameplay window.

Active Tick work averaged **13.225 ms**, maximum **64.629 ms**, with **30** durations above
33.333 ms; maximum accumulator lag **1.509742 s**. Peak pending replication **9,379**, maximum
deferred wait **10 Ticks**, versus control 5,974 / 8 and 0.726444 s lag. Game CPU averaged
69.635% of one logical CPU over available process intervals, with 20.004 s at ≥95%; bot
process CPU averaged 57.761%. The late high queues, ages and deadlines reject a useful
capacity conclusion even though first loss occurred later.

## Matched comparisons and identity/wire validity

The summary compares both observations in elapsed bins, first-ascent population bands, and
contiguous segments sharing elapsed time, 25-player authenticated/living bands, 50-projectile
bands and exact monster/effect counts. Each host/server/bot/wire source retains its own inner
boundaries; short segments without sufficient observations remain null. There are no common
joint strata after 25 s; the treatment then has materially higher populations. No equal-World
or instrumentation-adjusted causal estimate is claimed.

Examples, **bounded control → receive buffer**:

- **10–15 s:** both 92–134 authenticated; median living 76→80, projectiles 158→160;
  Tick-work median 10.766→11.357 ms, CPU 42.99→45.24%, inner receive errors 0→0.
- **15–20 s:** 134–170→135–171 authenticated; median living 104→104, projectiles 193→170;
  CPU 68.99→66.99%, inner receive errors **697→0**.
- **20–25 s:** 170–185→171–197 authenticated; median living 118→119, projectiles 192→187.5;
  CPU 93.24→91.74%, inner receive errors **25,345→0**. Sampled queue maxima
  **523,904→633,712 bytes**. A shared joint stratum has 175–199 authenticated,
  100–124 living, 150–199 projectiles and zero monsters/effects; its contiguous windows
  and sparse source coverage are retained explicitly in the JSON.
- **30–35 s:** populations differ, 135–184→200; Snapshot-age median 0.061→0.119 s and
  confirm-age median 0.262→0.495 s. These unequal-population values describe the tradeoff;
  they are not a matched throughput improvement.

The frozen `994cce8` collector includes the actual-encoder name-offset correction from
`227a9ec` and parser-equivalent Clippy cleanup. Only mapping semantics changed from `30ec792`;
sequence/retry/input/ACK/fingerprint counting did not. Both final maps contain **200 unique
port↔bot pairs**, agree across hosts, and cover every observed input port and Running/offering
identity. Ten live checkpoints also map every previously observed offering identity, are unique,
and have no disagreements on common ports. Historical empty maps remain unknown.

There are **7,424** aligned active bot-seconds within shared complete capture coverage. Both
hosts report median **30** input commands/s, range **8–32**, with **zero zero-input seconds**.
Missing port rows were explicitly filled with zero only for mapped bots with Running observations
bracketing the complete second; no missing coverage was zero-filled. Per-identity distributions
and per-bot offered intervals are retained. Offered median was 29.822 Hz, interval range
26.759–32.705 Hz. Last retained cumulative observations contain 241,842 inputs, **424 missed
schedules**, maximum input gap **115.508 ms**, 22 gaps above 100 ms. Identity attribution passes
for the covered prefix; **a whole-run generator/capacity pass is not assigned**.

Interface captures precede socket overflow: **application-delivered per-bot input is unknown**.
Different cross-host second boundaries and the cleanup tail make differences in total wire
counts unsuitable as loss estimates. Near-30 Hz offered traffic does not establish timely
application delivery. Bots recorded **83 baseline-reference misses / 1,119 unknown delta-entity
observations**, and zero decode/send failures/panics. The recovered workload log retains
**3,887 oversized-unreliable warnings**, payloads **1,201–1,554 bytes**; full-run warning count
is unknown because the tail is bounded. Zero malformed packets is not zero application loss.

## Collector coverage and observer cost

Both readers ended EOF, exit 0, zero malformed packets, with reader counts exactly equal to
tcpdump captured counts: **924,500 game / 939,336 bots**. Kernel capture-drop counters were
zero. However, game filter-received count was **924,640**, leaving **140 uncaptured records**
in shutdown accounting. Their exact timestamps are not retained; do not call total capture
loss zero. Bot filter-received equals captured. Both retain 451 reliable streams, 1,847,296
bitmap bytes and zero classified half-range ambiguities; this does not prove sequence assumptions.

Game packet coverage ends at **+50.133100 s**, **2.446849 s before swarm termination**; bot
coverage ends +52.575734 s. Game/bot complete UTC-second counts are **49 / 51**, and both
cover all complete seconds through the +48.133 s controller abort decision. The game cleanup
tail is unavailable, not zero. Capture status, mapping validity, prefix validity and full-swarm
coverage are separate fields; `all_requested_collector_requirements_met` is false for the
whole swarm window. Duplicate timestamp bins are merged; empty 10 ms bins are absent, so
burst distributions condition on observed traffic bins.

Capture children used **2.604622 / 3.326882 CPU seconds** over **57.913248 / 57.153105 seconds**
(game/bots), approximately **4.50% / 5.82%** of one CPU. Child maximum RSS was
**38,772 / 38,812 KiB**. These are waited-for child maxima, not isolated reader or summed
cgroup RSS. Guarded retained-size maxima were 684,536 / 703,877 bytes. Control capture
resources were 2.037398 / 2.681053 CPU seconds over 52.904007 / 52.146698 seconds; unequal
traffic and observation windows prevent assigning the difference to name extraction.

Host/socket collector self+child CPU averaged **3.792% / 4.115%** of one core. Tick observer
mean/max was **33.828 / 672.009 µs**; bot observation accounting recorded **223.648482 ms over
52 completed samples**. The 20 live mapping SSH reads had median 492 ms wall time each.
Remote CPU attributable to those reads and causal instrumentation slowdown remain unknown.

## Build, configuration, preservation and cleanup

Only `omega-server` was built, once, in the new clean detached checkout/target
`/home/deploy/omega-udp-buffer-f1cc5d6`, exact revision
`f1cc5d645217ddc14a4069c3fe40992d496270ae`, using:

```sh
source /home/deploy/.cargo/env
cd /home/deploy/omega-udp-buffer-f1cc5d6/rust
cargo build --release --locked -p omega-server
```

Rust 1.95.0 (`59807616e`), Cargo 1.95.0 (`f2d3ce0bd`), LLVM 22.1.2,
`aarch64-unknown-linux-gnu`, release thin LTO, no build-flag environment overrides. Cargo
config files in checkout/ancestors/user locations were absent; `.cargo/env`, Cargo.toml,
Cargo.lock, full build command/log and source diff were recorded. The remote Rust diff from
`1d15d84` is exactly configuration/plumbing/tests in `config.rs`, `main.rs`, `net/transport.rs`;
no later gameplay edits entered the build. No original/control/bitmap target directory was reused.

```text
candidate game  dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56
control bots   831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3
bitmap game    29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421
original game  f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2
original bots  8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf
Cargo.lock     904a78967ed19cb3403c3f498b16e90f4c171daa3ea0c2311dc9d793f90e148b
original JSON  bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c
private JSON   642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183
```

The private `arena-buffer.json` differs semantically **only** by adding
`udp_receive_buffer_bytes: 2097152`. The original `/etc/omega-loadtest/arena.json` was untouched.
The temporary runtime drop-in selected the candidate, private config and measurement namespace.
Kernel limits stayed rmem_max/wmem_max 4194304, defaults 212992; network and policy were unchanged.

Collector files were frozen with `git show 994cce8c7cb2f689cd59f4d09e93e270057aba7e` and compiled
on each host with `rustc --edition=2021 -O .../udp_control_record.rs -o .../flow-record`.
The mapping source `udp_control_flow.rs` hashes to
`5edc761d67ff3f3affdfd5bbd21e79729208a92627049c461e909e347e7b0e7c`;
all five source hashes and both executable hashes are in the summary. Parent collector files
and Rust sources were never edited. New files are
[controller](../../../../../scripts/load_campaign/udp_buffer.py),
[analysis](../../../../../scripts/load_campaign/udp_buffer_analysis.py), this report and its JSON.
Python syntax checks, retained-artifact analysis and consistency/address scans were local;
no live workload was used to test these scripts. Previously reported Rust regressions were
not rerun or represented as new remote validation.

Preflight proved idle ownership, original service with zero players, native network/config,
no competing workload/build/collector/profiler and sufficient disk. Prior archive hashes,
namespace inventories and closed campaign state were preserved. The restoration timer was armed
before stopping the original service. Current measurement files were copied and hash-verified
before restart; original config/drop-in/binaries were also preserved. Finally cleanup stopped
owned processes and collectors before archiving and restored the original service.

Independent verification, followed by a final read-only audit after journal recovery, confirms:
original game executable/config/drop-in/measurement destination restored, **zero players**, runtime
override absent, restoration timer inactive, no owned swarm/collector/profiler/build processes,
unchanged buffers/network/firewall/maintenance/prior archives/closed state, and preserved original
measurement copies still checksum-valid. Original current output resumes at its original path;
the pre-restart contents remain in the verified preservation copy, not overwritten evidence.

Private local evidence is `deployment/hetzner/results/udp-buffer-20261021/`; retained remote
originals are `/home/deploy/omega-results/udp-buffer-20261021/` on both hosts. Both primary
bundles and the separate journal supplement were verified against retained remote bytes.
Repeated JSON journal reads can reorder object keys; the supplemental downloaded bytes match
remote checksums, and decoded records match the original SSH reads. No evidence was deleted.

```text
game.tar.gz  ae88b319f426879176bb607b23f1d2bf440d7530da9be142850ca4affa8c996b
bots.tar.gz  60d3a90979a2b673d6e123b4daeaa0cdfac66961c5ad588f0c0066c62adcb967
game-journal-supplement.tar.gz  63c2957c4d4f3b6e1f4471472ddaf08124c3eb032309a6a54963df4cddcb4013
```

**Handoff:** burst capacity delayed initial loss, but the larger queue still overflowed and
service/delivery deteriorated. Mapping attribution is repaired for the covered interval;
application delivery and queue residence remain unknown. The parent also needs the preflight
window-publication/invocation defect above. Cleanup is complete; no next experiment was dispatched.
