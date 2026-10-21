# Bitmap stale-cache comparison — 2026-10-21

**One changed-build diagnostic; failed ramp; no demonstrated CAX11 improvement or new capacity.** Candidate game `1d15d84` replaced repeated active-ID slice scans with bitmap membership. It retained the instrumented control's bot executable, collectors, gameplay, transport and resource limits. Initial overflow and subsequent reliable-traffic amplification remained. The observation ended sooner than control on a connection timeout, with somewhat worse game-drop and Tick observations; differing World/entity trajectories and stop conditions prevent attributing those differences solely to the bitmap.

The workload ran **37.555493 s**, **12:47:05.992006–12:47:43.546607 UTC**, against control's **43.057510 s**. The remote watchdog recorded **`Bot 182 failed to connect: connect timeout`** at 12:47:43.248320 UTC. This join-failure guard ended the run, not the controller's population-collapse guard. Per-Tick peaks were **181 authenticated / 130 living**, separately, versus control's **182 / 125**. The last candidate active Tick had **52 authenticated**. Phase 2 was **never reached**. Control reached it only after 39.328152 s, after population had already collapsed; neither run sustained 200 players.

[The machine-readable summary](bitmap-comparison-summary.json) contains exact boundaries, counters, matched bins, hashes and nulls. [Control report](instrumented-control.md) and [candidate rationale](REPLICATION-CANDIDATE.md) remain unchanged. Private raw evidence is under `deployment/hetzner/results/udp-bitmap-20261021/`; remote originals remain under `/home/deploy/omega-results/udp-bitmap-20261021/` on each host. Exactly one workload was launched; no rerun, additional agent, profiler, commit or capacity tuning was performed. Historical validated Strategy capacity remains **100**, not either failed ramp's peak.

## Matched comparison and hypothesis outcome

Prediction: reducing stale-cache membership cost reduces World Tick/replication time, shortens read gaps, and reduces first socket overflow and later retransmission pressure at comparable offered load. **This single observation does not demonstrate that chain.** The World is entropy seeded; bot seed 30 does not fix entity layout or survival. World Tick includes simulation and replication, so it does not isolate the helper. No candidate CPU profile was taken.

For equal elapsed-time bins, **control → bitmap**:

- **10–15 s:** both cover 92–134 authenticated players. Median living population **80 → 84**, projectiles **159 → 160**, monsters **0 → 0**, effects **1 → 0**. World Tick mean per invocation **7.336 → 7.102 ms**; wider Tick-work median **11.110 → 11.652 ms**; game CPU **46.245% → 46.236%** of one CPU. Both inner host intervals have zero receive drops. Common-Running bot interval input totals **12,675 → 12,696** over **422.593 → 423.109 peer-seconds**; median per-bot rate **29.889 → 29.868 Hz**. Shoot/ability inputs **7,756/865 → 7,611/830**.
- **15–20 s:** authenticated ranges **135–167 → 134–169**, median living **104 → 109**, projectiles **183 → 197**. World Tick mean **11.149 → 11.517 ms**, wider Tick-work median **18.640 → 20.267 ms**, game CPU **69.216% → 70.986%**. Inner host receive drops **241 → 326**. Common-Running inputs **17,700 → 17,575** over **588.786 → 588.009 peer-seconds**, median rate **29.889 → 29.836 Hz**; shoot/ability inputs **10,814/1,120 → 10,667/1,223**. Server intervals contain **56 → 73** gaps in `(20,33.333] ms`; bitmap also has one in `(33.333,50] ms`, control none.
- **20–25 s:** authenticated ranges **168–182 → 169–181**, median living **115 → 121**, projectiles **178.5 → 198**. World Tick mean **14.884 → 15.017 ms**, wider Tick-work median **23.538 → 25.189 ms**, game CPU **88.915% → 92.477%**. Inner host receive drops **24,025 → 29,500**. Common-Running inputs **21,103 → 21,351** over **704.534 → 711.731 peer-seconds**, median rate **29.871 → 29.821 Hz**; shoot/ability inputs **11,879/1,302 → 12,294/1,414**. Observed Tick rates over the requested five seconds were **27.6 → 28.2 Hz**. Four complete UTC wire seconds contain inputs **20,446 → 20,415**, retries **7,451,161 → 5,619,819 command bytes**, and incoming ACKs **966,450 → 823,480**. That partial retry reduction did not prevent greater observed game drops.

Monsters remain median zero and effects **1 → 0** in the latter two bins too. All entity values above are per-Tick medians, not assumed equal gameplay load. Per-source boundaries are retained: server timings span **4.016/4.006**, **4.005/4.009**, and **4.139/4.469 s**, respectively, within the five-second requests; CPU uses separate inner host boundaries. Counters spanning sample boundaries are charged when observed. Wire totals use complete UTC seconds, whose positions within elapsed-time bins differ between runs. These are descriptive samples, not independent repetitions or confidence intervals.

First-ascent **actual population bands** corroborate the lack of a consistent World Tick reduction: mean World Tick duration at **100–124**, **125–149**, **150–174**, and **175–199** authenticated players is **7.359 → 7.146**, **9.289 → 9.155**, **12.669 → 13.101**, and **12.622 → 13.469 ms**. Actual upper peaks in the last band are only 182/181. The last two bands do not have equal residence times or entity loads; for 150–174, median living is **111/111** but projectiles **181/200**, and first-ascent duration **4.565/3.868 s**. For 175–199, median living is **108/112** and projectiles **172/174**. Summary data retain each band's offered inputs, CPU, read-gap histogram, delivery, entity distribution and timestamp boundaries; unequal wire coverage is not normalized into a false equal-duration comparison.

## Socket overflow, phases, and reliable amplification

The candidate's first game receive-buffer error interval was **16.327203–17.327435 s** after launch, **145–152 authenticated**, with **127 drops** and **70.9834%** game CPU. Control's **16.478601–17.478707 s**, **146–153 authenticated**, 33-drop interval overlaps it: there is **no demonstrated onset delay**. Candidate cumulative read-gap maximum was **20.602842 ms** at 16.101 s and **29.084639 ms** at 17.104 and 18.104 s. The 16.101–17.104 s server interval adds 16 gaps in `(20,33.333] ms`, none larger. Control's nearby maxima were about 26 ms. Initial overflow still precedes the much larger late stalls.

Candidate game `Udp:RcvbufErrors` rose **161,782**, exactly matching its single fresh socket, versus **149,140** control. Bot host rose **2,861**, versus **4,031** control; maximum observed drops across **182 bot sockets** sum to only **2,675**, on **18 sockets**. The remaining **186 are unattributed**, not silently assigned to bots. The bot process had already exited before final socket capture; its disappearing sockets limit attribution. Bot-host onset ended at **29.836853 s**, 174 errors and 181 authenticated players, versus control's 29.968513 s. Sampled maximum receive memory was **524,288 bytes game / 212,896 bots**. Effective receive/send limits remained **524,288/524,288 game**, **212,992/212,992 bots**.

Final candidate adapter counters were **254,693 receive calls**, **217,958 datagrams**, **36,735 empty reads**, **0 receive errors**, **296,201 send calls**, **4 zero-byte sends**, **0 send errors**. Four zero-byte sends match game-host `SndbufErrors`; control had **969**. Application decode/send counters were zero in both. Lower whole-run zero-sends and bot drops are not a matched improvement claim: run lengths, traffic, death/disconnection trajectories and cleanup order differ.

For candidate's before-onset / after-onset / last-ten-second requests, retained inner server intervals span **9.012 / 7.984 / 8.973 s**. Phase elapsed-time fractions are:

- Service/routing: **10.993% / 23.108% / 59.305%**; control **10.703% / 24.512% / 64.999%**, with different inner durations and late populations.
- World Tick, including replication: **20.228% / 41.871% / 26.805%**; control **20.762% / 40.789% / 16.229%**.
- Outbox: **6.403% / 14.808% / 7.389%**; control **6.148% / 13.470% / 4.969%**.
- ENet flush: **5.485% / 13.354% / 5.115%**; control **5.227% / 12.132% / 3.777%**.

The candidate's maximum service/routing phase was **365.725 ms**, World Tick **23.160 ms**, and cumulative read gap **435.561 ms**. Whole-workload inner counter differences include **35 gaps >100 ms** and **63 >33.333 ms**, versus control **36 / 51**. Read gaps measure opportunities to read, including normal sleep; they are not queue residence or packet arrival delay. Phase percentages are elapsed wall time, not sampled CPU attribution; maxima are cumulative, never subtracted.

Equal **nine-complete-UTC-second** windows before and after candidate onset show game-side inputs **28,102 → 45,407**, incoming datagrams **73,982 → 139,704**, incoming ACKs **463,212 → 1,909,498**, and reliable retry command bytes **166,124 → 15,103,419**. Control retries were **132,337 → 13,688,810** in its corresponding nine-second windows. Candidate incoming 10 ms peaks grew **274 → 621 datagrams**, **106 → 265 inputs**, **6,166 → 19,200 ACK commands**. Bot-side observations broadly agree; after-onset retry bytes were **15,101,817**, inputs **45,404**, ACKs **1,909,841**, and input burst peak **273**. Cross-host bin differences are not packet-loss estimates. Equal 10 ms timestamps are merged before taking maxima.

The same loss/retry amplification remains. The next measured bottleneck is service/routing under reliable-traffic pressure, with substantial replication/outbox/flush work already present at onset. The prior control profile implicated reliable ACK removal; this candidate run does not exclusively attribute its service timer to that function. The **4,000-line retained game-log tail contains 4,000 oversized-unreliable warnings** (e.g. 1,214-byte channel-0 packets); control retained 3,837 in its capped tail. The full-run warning count is unknown. Investigating excessive reliable traffic and the oversized-unreliable fallback remains justified; this experiment neither changed that behavior nor proves its exclusive causal contribution.

## Offered load, delivery, Tick work, and errors

All **38 bot samples** were ramp observations, with `phase_s=null`. They contain 182 distinct identities and **181 observed Running identities**. The last sample, 0.333 s before watchdog end, has **133 Running / 48 Failed / 1 Connecting**. This differs from authoritative game population; bot phases are not authentication counts. Final cumulative recorded inputs total **141,359**, missed schedules **39**, maximum observed input gap **90.359440 ms**; no retained input-gap histogram observation exceeded 100 ms. Control recorded **164,373 / 46 / 87.501173 ms** over its longer run.

Before/after/late candidate median per-Running-bot interval rates are **29.8678 / 29.8211 / 29.8271 Hz**, minima **29.7575 / 28.2800 / 28.8670 Hz**, missed increments **0 / 5 / 34**. Dead bots also send zero-input frames. Near-30 Hz average offered scheduling does not establish per-peer delivered-input validity. Bot-ID↔port mapping and server-received per-bot input cadence remain **null** because collector finalization was missing. Nonzero port-second wire counts and per-bot scheduling evidence are retained separately; no generator-valid pass is claimed.

Candidate median Snapshot ages before/after/late are **16.079 / 15.946 / 151.682 ms**, ActionConfirm ages **16.913 / 63.455 / 239.216 ms**. Late p99 reaches **4.949 s Snapshot / 12.781 s confirm**. Control late medians were **1.061 / 1.251 s**, p99 **10.688 / 15.712 s**, but its window occurred later and included a different cleanup tail; those are not a latency improvement result. Application-observed ages are not one-way latency, input age or queue residence.

Bots recorded **0 decode failures / 0 send failures / 0 panics**, **574 baseline-reference misses / 1,866 unknown delta-entity observations**, versus control **1,520 / 1,395**. The complete candidate bot log has one connection-timeout failure, no ticket/start failure, and no panic or ERROR lines. These are failure/convergence findings for the parent and issue #39; the interrupted workload has no completed strict-assertion pass.

Candidate active Tick work averaged **13.527 ms**, maximum **37.393 ms**, with **11** work durations exceeding 33.333 ms; control **12.674 / 41.977 ms / 12**. Maximum accumulator lag **0.596 s** versus **0.617 s**; maximum pending replication **7,050** versus **7,911**, maximum deferred wait **9 versus 10 Ticks**. Whole-run averages compare different population trajectories. Tick observer overhead mean/max **29.318 / 2,122.589 µs**, control **26.411 / 305.564 µs**, is retained rather than ignored.

Game active-process CPU averaged **66.932%**, maximum **100.976%** of one logical CPU, with **15.003 s ≥95%**; control **66.164% / 99.989% / 13.005 s**. Bot process **52.659% average / 77.994% maximum**, control **52.017% / 78.992%**. Process CPU sums threads. Both hosts had zero measured steal. Interface drops, checksum errors and UDP memory errors were zero. Host windows span **55.010 s game / 57.009 s bots**, including setup/cleanup. Candidate bot-host `NoPorts=4,777` includes post-exit traffic; game `NoPorts=0`. Cleanup tails are not gameplay loss.

## Collector coverage and bounds

Both unchanged parsers stopped at **2,000,000 reliable-command state entries**. Complete one-second evidence ends **29.007994 s after candidate launch**, versus **27.569891 s** control. Candidate's last-ten-second request contains only **one complete wire second**; control contains none. **There is no complete late wire comparison.** Final flow summaries, mapping, total parsed packets and malformed counts remain null. Tcpdump's loss accounting cannot fill the missing parser tail.

Tcpdump reports **515,397 captured / 516,495 filter-received / 0 kernel drops game**, and **515,383 / 515,983 / 0 bots**. These are capture-process counts, not validated parser totals. Capture children consumed **3.067919 s over 36.335012 s game**, **3.440802 s over 32.820586 s bots**; supervisor CPU **0.106693 / 0.090969 s**; child maximum RSS **204,896 / 205,220 KiB**. Host/socket collector self+children CPU averaged **4.063% / 4.072%** of one CPU over their full collection windows. Causal instrumentation/collector slowdown remains unknown.

No profiler, buffer, network or collector-state fix was introduced. Original limits remain: one-second host/socket samples; compact fingerprints at 1/64 sampling; 1 s port/flow and 10 ms burst bins; no full pcap archive; 300 s capture duration; 48 MiB retained-size guard; 64 MiB per-file hard limit; 512 MiB cgroup memory. Ramp ≤180 s, postjoin ≤120 s, 305 s swarm bound, join-failure checks every 0.5 s, original population/stale/log guards and 420 s restoration timer were unchanged. Even a 200-player, 120-second completion would be diagnostic only: capacity requires the ordinary 60-second warmup and 300-second measurement window.

## Build identity, provenance, and verified cleanup

Only `omega-server` was built, on the game host, in a **new clean detached checkout and target** at `/home/deploy/omega-udp-bitmap-1d15d84`, exact `1d15d84a86164af4e2d34db633bcd3828836b3d6`. No original/control build directory was overwritten or reused, no evidence was deleted, and the bot host did not rebuild either game package or bot package. Its existing control bot was used. Command:

```sh
CARGO_TARGET_DIR=/home/deploy/omega-udp-bitmap-1d15d84/rust/target \
  cargo build --release --locked -p omega-server
```

Build took 3m08s. Compiler **Rust 1.95.0 (`59807616e`, LLVM 22.1.2)**, Cargo **1.95.0 (`f2d3ce0bd`)**, `aarch64-unknown-linux-gnu`, thin LTO, empty additional Rust flags across **136** final package fingerprints. No build/profile environment overrides or Cargo configs were present. Compiler/Cargo/lock hashes match control and are in the summary; kernel remained `7.0.0-30-generic`. The only Rust diff from `cc86869` is bitmap membership plus tests. Parent-reported local workspace/Clippy/format/extension validation is not CAX11 performance evidence.

Exact executed hashes, including `/proc/PID/exe` runtime verification:

```text
game /home/deploy/omega-udp-bitmap-1d15d84/rust/target/release/omega-server
29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421
bots /home/deploy/omega-udp-control-cc86869/rust/target/release/omega-load-test
831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3
preserved control game
5a36a7aaf3bed4db46efd2a4200c4e02825ef3598d0c4990a672d279c051a202
```

[Controller](../../../../../scripts/load_campaign/udp_bitmap.py) stages all five collector files using `git show 04faa9770dd78c34398a0361eebcb949c037e55a:...`; their bytes match both control hosts' executed-source hashes. Parent's concurrent collector changes are excluded. The host/socket collection function is unchanged. Runtime bot hashing and candidate provenance checks are outside the game loop. [Analysis](../../../../../scripts/load_campaign/udp_bitmap_analysis.py) retains source-specific boundaries and matched actual-load facts.

Workload stayed **Strategy 200, seed 30, difficulty 1, 100 ms stagger, 30 Hz input**, normal Warrior/Rogue/Mage rotation, 30 Hz Tick/Snapshot, AoI 1000/exit 1100 and normal 120000/200000 default/max budgets. Config SHA-256 remained **`bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`**. The sole temporary service override selected the game executable and private measurement path.

Preflight found zero players, one ordinary game service, no swarm/collector/profiler/compiler/package-job ownership conflict, normal network/settings and maintenance state, **16.403 GB game / 24.182 GB bots** free. The fresh game build left **15.793 GB**. Frozen binaries and pre-run measurement files were copied and checksum-verified before restart. Final verification confirms the original service/config and frozen game executable restored, **zero players**, override removed, unchanged qdisc/filters/firewall/buffer sysctls/closed campaign state, and **no swarm, capture, trace, profiler, compiler or package-job leftovers**. Both maintenance timers remain active/enabled, update services inactive. The preserved measurement copy passed a second checksum check. Original hashes remain `f2bf76c6…dada3a2` game and `8af49183…3e8bdf` bots; full hashes and proofs are in the summary.

Collectors stopped before archiving; local private bundles were independently SHA-256 checked against retained remote originals:

```text
game.tar.gz ae50817b9fb01f605378e17497998af81aeefc5aa4d1cc12fe8689c10ca2282c
bots.tar.gz d060ef2d481999c6c8e80f91546f89229875157f2787b9fd36731ae5d704602b
```

Build/source/compiler evidence is in private `game-build.json`, `game-build-settings.json`, `game-final-build-settings.json`, `staged/`, and `udp_bitmap.executed.py`; configuration/runtime identities in `manifest.json` and host before/after snapshots; cleanup in `cleanup.json`, `final-verification-summary.json` and endpoint final-verification files. The sanitized summary records their hashes. Raw addresses and access material remain private. Existing control/profile/baseline sources and reports, parent Rust changes and the iteration ledger were not edited.
