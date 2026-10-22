# Bounded collector comparison — 2026-10-21

**Exactly one remote experiment; failed ramp; no capacity claim.** The repaired collector
`30ec792` avoided history exhaustion, finalized both readers, and retained late flow/port
observations with lower measured capture CPU and RSS. **Identity mapping still failed:** both
`port-bot.csv` files contain only their header. This condition validates bounded collection,
not every required collector feature or per-bot wire validity.

The unchanged bitmap game and control bots ran Strategy 200 for **40.062320 s**, from
**13:01:53.602261 to 13:02:33.663675 UTC**. The watchdog observed
`Bot 186 failed to connect: connect timeout` at **13:02:33.533881 UTC** and stopped the swarm.
Phase 2 was never reached. Separate per-Tick peaks were **185 authenticated / 124 living**;
the last active Tick had **68 authenticated**. This is a diagnostic failure, not sustained
capacity. No retry, second workload, agent, game/bot rebuild, profiler, settings change or
commit was performed.

[Machine-readable summary](bounded-collector-summary.json) retains exact counters, source-specific
boundaries, comparisons, hashes and nulls. Compare with the completed
[bitmap diagnostic](bitmap-comparison.md), whose workload lasted 37.555493 s and peaked at
181 authenticated / 130 living. The sole experimental intervention is the collector repair;
any apparent game-performance difference belongs to this instrumentation condition. The
entropy-seeded World trajectories and entity loads are unequal despite identical bot seed 30.

## Collector prediction and validity

Prediction: bounded per-stream reliable sequence history avoids the two-million-entry guard,
preserves late input/parser/mapping evidence, and lowers collector CPU/RSS. The history,
parser, late-port and resource portions are supported; the mapping portion is not.

- Both readers ended **`eof`, exit code 0, zero malformed packets**. Game parsed **716,976**
  packets, bots **716,978**. On each host this exactly equals both tcpdump's captured and
  filter-received counts; **kernel capture drops were zero**. Capture supervisors stopped
  normally on controller request, without a duration, size, memory or forced-stop result.
  These capture-loss counters are independent of the substantial game/bot socket drops.
- Both observed **4,279,862 outgoing + 4,609 incoming reliable commands**, with **416**
  direction/port/channel streams and **1,703,936 bytes** of sequence bitmaps. Neither reader
  exhausted history. This is a real failed-ramp validation, not a 300-second sustained test
  or a maximum-stream memory test.
- First observed packet timestamps were **+0.004449140 s game / +0.004222140 s bots** after
  process launch. Last timestamps were **+43.299767140 / +43.300893140 s**, extending
  **3.238353 / 3.239479 s beyond watchdog termination** into cleanup. Parser and flow-summary
  last timestamps agree. Both captures contain all **42 complete UTC seconds** in
  `[13:01:54, 13:02:36)`, including **39 complete seconds inside the workload**. This is
  timestamp coverage, not a claim of traffic before the first observed packet.
- The final-ten-second workload request has **nine complete wire seconds on both hosts**,
  versus only one in the bitmap diagnostic. Its absent historical tail remains absent.
  Timestamp backsteps reached **47 µs game / 272 µs bots**; analysis merges equal 10 ms bins
  and equal port-seconds. Empty 10 ms bins are absent from raw output: distributions condition
  on observed bins, while reported peaks are observed maxima. Clock offsets were below
  0.1 ms with about 1.6–1.8 ms root dispersion; submillisecond cross-host causality is not claimed.
- **Unclassified reliable counts are `[0,0]` on each host**, both whole-capture and scheduled
  counters. V2 counts repeats within a **32,768-sequence window per direction/port/channel,
  with no 60-second TTL**. It extends from observed data commands using the nearest half-range;
  ACKs do not advance history. Exactly-half-range observations are unclassified. Zero such
  observations does not prove no unseen advance ≥32,768 or no port reuse. A first observation
  is not proof of an original transmission. **V2 retry totals are not interchangeable with
  historical v1 totals.** Outstanding reliable queue length remains null.

**Mapping defect:** all **185 ports with input traffic** remain unmapped on each host; all
**185 observed Running/offering bot IDs** lack a correspondence. Empty maps are not a successful
cross-host mapping comparison. `cc86869:rust/protocol/src/client.rs` encodes unsigned
ConnectAuth as type/version/ticket-length, then a **u32 `character_id` at offsets 4–7**, then
name length at **8** and name at **9**. The frozen collector reads name length at **4** and
name at **5**. Unsigned bots set character_id to zero, so that path cannot identify `LoadBotNNN`.
The existing synthetic mapping fixture omits character_id and therefore misses this mismatch.
This is established by the pinned encoder/parser source plus empty live mapping output;
no collector semantic fix or additional replay/workload was made here. The contract's prose
layout also differs from the encoder at this point; the implemented encoder determines the wire.
Retained fingerprints contain no payload from which to recover the names. Identity-aligned wire
cadence, server-delivered per-bot inputs and generator-valid classification remain **null**.

Capture-child CPU was **2.037398 s over 52.904007 s game**, **2.681053 s over 52.146698 s bots**,
versus bitmap **3.067919 / 36.335012 s**, **3.440802 / 32.820586 s**. These correspond to
**3.851% / 5.141%** of one CPU for this capture lifetime, with unequal workload/cleanup windows.
Supervisor CPU was **0.139749 / 0.128677 s**. Child maximum RSS fell from
**204,896 / 205,220 KiB** to **38,820 / 38,808 KiB**. This is the maximum for waited-for capture
children, not isolated reader RSS or summed cgroup RSS. Sampled guarded retained size peaked
at **525,579 / 525,733 bytes**; final parser status files add 129 bytes each. Host/socket
collector self+child CPU averaged **3.913% game / 4.219% bots** over their full windows.
These support lower collection resource use, but do not quantify causal slowdown of the game.

## Overflow, read gaps and late traffic

First game-host receive-buffer errors were bracketed at **+15.126376–16.126495 s**,
**135–142 authenticated players**, **40 drops**, and **60.993%** game-process CPU. Bitmap's
first interval was **+16.327203–17.327435 s**, 145–152 authenticated. There is no demonstrated
onset improvement. Nearby cumulative maximum read gaps were **20.045555 ms at +14.845204 s**,
**23.817847 ms at +15.847835 s**, and **27.579259 ms at +16.851798 s**. The latter two
one-second observations add three and six gaps in `(20,33.333] ms`, none above a Tick.
Initial overflow still precedes the much longer late read gaps.

Game-host `Udp:RcvbufErrors` rose **162,406**, exactly matching the single fresh game socket;
bitmap recorded 161,782. Bot-host errors rose **5,466**; maximum observed drop counters across
186 bot sockets total **5,252**, with 32 dropping sockets. **214 remain unattributed** because
sockets disappeared before final capture. Bot-host onset ended at **+30.721273 s**, with
272 errors and 180–185 game players. Sampled receive-memory maxima were **523,904 game /
212,976 bot bytes**. Effective receive/send limits stayed **524,288/524,288 game** and
**212,992/212,992 bots**.

Final adapter counters were **275,966 receive attempts, 237,330 datagrams, 38,636 empty reads,
zero receive errors; 317,163 send calls, 445 zero-byte sends, zero send errors**. Zero-byte
sends match the **445** game-host `SndbufErrors`; application send/decode counters were zero.
Kernel socket drops need not surface as adapter decode or receive errors. Interface drops,
fq_codel drops/overlimits, checksum errors and UDP memory errors were zero. The bot-host
**6,579 NoPorts** include post-exit traffic. Whole host counter windows span **59.007894 s game /
61.009882 s bots**, including setup/cleanup, and are not matched gameplay windows.

For requests before onset / after onset / final ten seconds, inner server timing spans
**9.007544 / 8.587175 / 8.994726 s**. Service/routing consumed **9.828% / 21.315% / 64.026%**
of elapsed time; World Tick including replication **17.205% / 39.529% / 21.075%**;
outbox **5.138% / 13.902% / 5.826%**; ENet flush **4.527% / 14.208% / 5.636%**.
Maximum service phase was **439.533 ms**, World Tick **17.836 ms**, and read gap **455.286 ms**.
Inner workload counter differences include **30 gaps >100 ms** and **57 >33.333 ms**.
Phase measurements are wall time, not sampled CPU attribution. Read gaps measure intervals
between receive attempts, including normal sleep, not packet residence in the receive queue.
Histogram counts/sums are differenced; cumulative maxima are never subtracted. A gap crossing
a sample boundary is charged when observed.

Equal nine-complete-second wire windows before / after / late now show:

- **Game-side input commands:** **24,336 / 44,740 / 38,472**; bot-side **24,337 / 44,748 / 38,453**.
- **Game-side incoming datagrams:** **63,200 / 138,252 / 82,470**; incoming ACK commands
  **364,692 / 1,809,629 / 677,715**.
- **V2 reliable retry command bytes, both directions:** game **112,797 / 10,504,775 / 8,200,090**;
  bots **112,797 / 10,504,775 / 8,225,245**.
- **Game incoming 10 ms peaks:** datagrams **302 / 541 / 515**, inputs **99 / 198 / 152**,
  ACKs **5,600 / 15,022 / 14,427**. Bot-side input peaks **99 / 202 / 152**.

Thus reliable traffic pressure persists into the previously missing late ramp. The comparison
supports amplification after overflow; it does not isolate a server hot path or prove the first
loss's cause. Cross-host bin differences are not packet-loss or latency estimates. Game wire
capture is at the interface, before socket overflow; it is not application-delivered input.
Both complete captures contain **148,554 input commands**, agreeing between summary and port
rows, but lacking bot identities. Nonzero port-second medians are 30 inputs in all three windows;
these exclude silent port-seconds and include partial joins, so they are not per-peer validity.

## Offered load, Tick work, delivery and correctness

All **40 bot observations** are ramp rows with `phase_s=null`: 186 observed identities,
185 ever Running. Last sample, **0.819451 s before termination**, has **113 Running /
72 Failed / 1 Connecting**. Bot phase is not authoritative game authentication. Final retained
cumulative bot observations contain **148,492 offered inputs, 91 missed schedules**, maximum
input gap **107.393423 ms**, and **12 gaps >100 ms**. Wire/application totals have different
boundaries; their difference is not a loss estimate.

For bots Running at both ends of each adjacent sample, median offered rates before / after /
late were **29.8700 / 29.8435 / 29.8171 Hz**, minima **29.7026 / 29.5417 / 29.7153 Hz**.
The 91 misses occur outside these selected inner intervals; the whole-workload minimum is
28.7626 Hz. Dead bots also offer zero-input frames. Near-30 Hz scheduling does not establish
identity-aligned wire delivery. The raw per-bot interval analysis remains private and retains
individual IDs/counts/timestamps.

Snapshot-age medians before / after / late were **18.338 / 19.699 / 97.825 ms**; ActionConfirm
ages **17.525 / 53.071 / 189.083 ms**. Late p99 reaches **5.684 s Snapshot / 11.184 s confirm**.
These are application-observed message ages, not one-way network latency, input age or queue
residence. Late survival/disconnection and differing observation windows prevent an improvement
claim against the bitmap run.

Bots recorded **0 decode failures / 0 send failures / 0 panics**, but **8,245 baseline-reference
misses / 1,538 unknown delta-entity observations**, versus bitmap **574 / 1,866**. These remain
correctness/convergence findings, including the substantially larger reference-miss count; they
are not zeroed by diagnostic classification. The bounded 4,000-line game log contains
**3,845 oversized-unreliable warnings**, payloads **1,201–1,444 bytes**, versus bitmap's capped
4,000 warnings. Full-run warning count is unknown. The complete bot log contains one join timeout;
no strict-assertion completion occurred.

Active Tick work averaged **12.841 ms**, maximum **49.714 ms**, with **16** work durations above
33.333 ms; maximum accumulator lag **0.726444 s**. Peak pending replication was **5,974**,
maximum deferred wait **8 Ticks**. Tick-observer mean/max was **25.086 / 1,702.424 µs**; bot
observation accounting reports **147.241403 ms over 39 completed samples**, excluding the
current row. Game process CPU averaged **67.991%**, maximum **99.991%** of one logical CPU,
with **17.002206 s ≥95%**. Bots averaged **52.530%**, maximum **80.992%**. Both hosts recorded
zero steal. These are measured resources with different entity trajectories, not causal gains.

## Comparison at matched time and population

The summary supplies per-source inner boundaries, actual living/entity counts, offered inputs,
CPU, read gaps, delivery and wire availability. In equal elapsed bins, **bitmap → bounded collector**:

- **10–15 s:** both 92–134 authenticated; median living **84 → 76**, projectiles **160 → 158**.
  World Tick mean **7.102 → 7.217 ms**, wider Tick-work median **11.652 → 10.766 ms**, game CPU
  **46.236% → 42.994%**, inner receive drops **0 → 0**. Common-Running offered inputs
  **12,696 → 12,637** over **423.109 → 422.470 peer-seconds**.
- **15–20 s:** authenticated **134–169 → 134–170**, living **109 → 104**, projectiles **197 → 193**.
  World Tick mean **11.517 → 11.466 ms**, Tick-work median **20.267 → 18.703 ms**, CPU
  **70.986% → 68.993%**, inner drops **326 → 697**. Offered inputs **17,575 → 17,588** over
  **588.009 → 584.769 peer-seconds**.
- **20–25 s:** authenticated **169–181 → 170–185**, living **121 → 118**, projectiles **198 → 192**.
  World Tick mean **15.017 → 14.709 ms**, Tick-work median **25.189 → 24.450 ms**, CPU
  **92.477% → 93.239%**, inner drops **29,500 → 25,345**. Offered inputs **21,351 → 21,586** over
  **711.731 → 720.004 peer-seconds**. Inner server timing spans differ materially:
  **4.468950 → 3.266986 s** within the five-second request.

Monsters and effects have median zero in these bins. Each has four complete UTC wire seconds,
with different positions within its elapsed interval. Retry values are retained with their
collector versions, never treated as an equal counting definition. First-ascent actual
population bands **100–124 / 125–149 / 150–174 / 175–199** yield World Tick means
**7.146→7.135 / 9.155→9.699 / 13.101→12.375 / 13.469→12.447 ms**. The last band peaks at only
181/185 and has median projectiles **174→140** with unequal residence times; it does not
control for entity load. At **30–35 s**, bitmap wire totals are null while the repaired collector
retains four complete seconds. The **35–40 s** bitmap comparison is null because that workload
had already ended. These descriptive comparisons establish neither a server optimization nor
an instrumentation-adjusted capacity increase.

## Identity, commands, preservation and cleanup

Existing executables, unchanged before/after and checked through `/proc/PID/exe` during the run:

```text
game /home/deploy/omega-udp-bitmap-1d15d84/rust/target/release/omega-server
29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421
bots /home/deploy/omega-udp-control-cc86869/rust/target/release/omega-load-test
831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3
original game /home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server
f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2
original bots /home/deploy/omega-measured/rust/target/release/omega-load-test
8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf
/etc/omega-loadtest/arena.json
bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c
```

The new [controller](../../../../../scripts/load_campaign/udp_bounded.py) adapts `udp_bitmap.py`
without editing it. It freezes `host_collect.py`, `capture.py`, `udp_control_capture.py`,
`udp_control_record.rs`, and `udp_control_flow.rs` using
`git show 30ec7925008ffd882bd5d46d32810d4ec39f754f:scripts/load_campaign/<source>`.
Host collection/dependencies are unchanged from the bitmap condition. No frozen collector
source or Rust application file was edited. Only the standalone collector was compiled on
each host:

```sh
source /home/deploy/.cargo/env
rustc --edition=2021 -O \
  /home/deploy/omega-results/udp-bounded-20261021/udp_control_record.rs \
  -o /home/deploy/omega-results/udp-bounded-20261021/flow-record
```

Both collector executables hash to
`647c9173d72c8214897f3d8d48788914722264da1f3a71bcc032cef6050e5fd8`.
Toolchain remains Rust 1.95.0 (`59807616e`), Cargo 1.95.0 (`f2d3ce0bd`), LLVM 22.1.2,
`aarch64-unknown-linux-gnu`; kernel `7.0.0-30-generic`. No packages or system settings changed.
Historical application build flags are referenced from the bitmap/control reports, not
independently reconstructed from a rebuild. All source hashes are in the summary.

Executed locally:

```sh
python3 scripts/load_campaign/udp_bounded.py run
python3 scripts/load_campaign/udp_bounded_analysis.py
```

Exact bot argv/environment, with only the private connection address replaced:

```sh
env -u OMEGA_TICKET_API -u OMEGA_LOAD_TEST_SECRET \
  OMEGA_MEASURE_DIR=/home/deploy/omega-results/udp-bounded-20261021/bots \
  /home/deploy/omega-udp-control-cc86869/rust/target/release/omega-load-test \
  --server <game-host>:8081 --bots 200 --behavior strategy --duration 120 \
  --input-hz 30 --seed 30 --stagger 100 --difficulty 1.0 \
  --bandwidth-budget 0 --assertions strict --aoi-exit-radius 1100 \
  --output /home/deploy/omega-results/udp-bounded-20261021/bots/bot.json
```

The existing game ran under `omega-loadtest-arena.service` with
`--config /etc/omega-loadtest/arena.json --allow-unsigned-tickets` and measurement output
redirected to this namespace. Original JSON is reproduced in the summary: 30 Hz Tick/Snapshot,
AoI 1000/exit 1100, LOD 400/1000, default/max budgets 120000/200000, max_players 999,
monster difficulty 0.85, isolated unsigned Arena without API/persistence. Bots retain normal
Warrior/Rogue/Mage rotation. Bot difficulty 1 does not replace the game config's difficulty.

Bounds remain: ramp **180 s**, postjoin **120 s**, swarm unit **305 s**, restoration **420 s**;
0.5 s join-failure checks; two-poll population guard below 65% of peak ≥100; 10 s stale-game
and 8 MiB bot-log guards. Capture **300 s**, retained-size guard **48 MiB**, per-file limit
**64 MiB**, cgroup **512 MiB**; fingerprints **1/64**, host/socket and flow/port cadence **1 s**,
burst bins **10 ms**. No full pcap. Controller additionally checks frozen parser/capture status
while polling; this does not change collector semantics. Restoration is armed before stopping
the original service, and each finally-block stop is attempted independently. Unit details,
exact private SSH commands, and the executed controller copy are retained.

Fresh preflight found the original game active with zero players, no competing swarm,
collector/profiler/build/package processes, native network/config, and **15,740,448,768 bytes
game / 24,167,325,696 bytes bots** free. It hashed prior archives, retained prior namespace and
closed-state inventories, and checked original/candidate/control binaries. Current game
measurement files were copied and checksum-verified **before restart**; config, original
measurement drop-in and executables were preserved. All prior report namespaces and remote
originals remain intact. No remote evidence was deleted.

Independent final verification at **13:04:57 UTC** found the original service active with
**zero players**, original executable/config/unit restored, runtime override absent, no owned
swarm/collector/profiler/build leftovers, and restoration timer inactive. Buffers, qdisc,
filters, firewall rules, maintenance states, prior archive hashes and closed campaign state
matched preflight. Update timers remain active/enabled, update services inactive. Preserved
measurement copies passed a second full checksum check. Collectors stopped before archiving.
Both download-time and independent final remote/local checksum checks passed:

```text
game.tar.gz  8e06fcd153c89c569fb13fb7c9d64739151a26a922eb89946b083351f3ef9900
bots.tar.gz  883920e932c695827a842929c95fe8bfae1172266c989faa710c3c992eb94ede
```

Private evidence: `deployment/hetzner/results/udp-bounded-20261021/`, with remote originals
under `/home/deploy/omega-results/udp-bounded-20261021/` on both hosts. Archives include raw
host/socket points, Tick/server and bot observations, flow/port/burst points, parser status,
resource accounting, fingerprints and bounded logs. The summary hashes the controller,
analysis, manifests, archives and verification evidence. Local verification consisted of
Python syntax checks, analysis against these retained artifacts, count/coverage/hash consistency
checks, and public-artifact address scans; no additional workload was used for verification.

**Next fact for the parent:** bounded history now permits late investigation, but the collector's
ConnectAuth name offset must be repaired and tested against the actual protocol encoder before
identity-aligned offered/wire validation can pass. The new late evidence still shows reliable
traffic, service/read stalls, socket overflow and severe reference misses. This agent leaves
that mapping repair and any subsequent experiment to the parent; no further experiment is launched.
