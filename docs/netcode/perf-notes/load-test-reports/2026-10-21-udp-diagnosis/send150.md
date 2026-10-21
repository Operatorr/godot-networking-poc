# Send-buffer allowance, unprofiled Strategy 150 — 2026-10-21 UTC

**Exactly one workload completed. Generator valid; capacity `valid-failure`.**
Game `SndbufErrors` and nonempty zero-byte sends fell from **2,290 steady / 2,295
total to zero**. All offered/wire, population, per-peer delivery, Tick, backlog,
application-error and collector gates passed. **Strict AoI still failed: 24/150
violators. Strategy 100 remains the highest validated capacity.**

The binding plan is [SEND-BUFFER-CANDIDATE.md](SEND-BUFFER-CANDIDATE.md), with
unchanged [capacity gates](CAPACITY-150-PLAN.md) and direct unprofiled comparator
[dodge150](dodge150.md). [The compact summary](send150-summary.json) contains exact
window points, gates, failing identities, counters, trajectories, hashes and cleanup.
Full peer rows, timelines, commands and connection details remain private.

## Condition and build identity

The intended workload factor was game send allowance: request **262,144 → 2,097,152**
bytes, effective **524,288 → 4,194,304**. Receive stayed requested **2,097,152** and
effective **4,194,304**; bot receive/send stayed **212,992 / 212,992**. Startup
requested/effective fields, owned sockets and runtime identities were verified
before traffic and throughout. No sysctl, kernel, network policy or default
configuration was changed.

The game binary changed to expose the optional send setting; this is not a
same-executable config comparison. Both hosts separately built **only omega-server**
from clean exact revision `e27db2d3c50b3b1dd550a32ed40f7a64526a4513`, in the same path:

```text
/home/deploy/omega-udp-send-e27db2d/rust/target/release/omega-server
a4e5460cd6558a9f5cafec93206e64780e8c30bb1f6e20313c6394d7e22466a5
```

Build argv: `cargo build --release --locked -p omega-server`. Rust **1.95.0**
(`59807616e1fa2540724bfbac14d7976d7e4a3860`), Cargo **1.95.0**, LLVM **22.1.2**,
native **aarch64-unknown-linux-gnu**, existing **thin LTO**, both kernels
**7.0.0-30-generic**. No custom target flags or user Cargo configuration were present.
The game production diff against `f1cc5d6` is configuration, bind wiring and native
send-buffer initialization; the protocol test difference does not enter the binary.
Exact compiler/kernel/environment, build output, source proof and bundle checksum
are retained separately.

The optimized bot was neither rebuilt nor redeployed:

```text
revision  2c25af7d5ab4cba81de1777437e2df2cfe735ebc
path      /home/deploy/omega-udp-dodge-2c25af7/rust/target/release/omega-load-test
sha256    73b957c7cb090ac8c433aa66dfba983ec8ad62305f527cab83be596dce524b1e
```

Private config SHA **`0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`**
differs from comparator SHA
`642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`
by exactly one dictionary entry: absent `udp_send_buffer_bytes` → **2097152**.
Every other key/value is unchanged. Previous game
`/home/deploy/omega-udp-buffer-f1cc5d6/rust/target/release/omega-server`, SHA
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`, is preserved
on the game host; it was not present on the bot host before this task.

Strategy 150, seed 30, difficulty 1, Warrior/Rogue/Mage rotation, 30 Hz requested
input/Tick/Snapshot, 100 ms stagger, AoI/LOD/budgets and strict assertions stayed
unchanged. World entropy was not fixed. No profiler/tracer, logging suppression,
pacing change, extra smoke/workload, retuning, gameplay fix, agent, commit/push,
parent-ledger edit or provisioning occurred. The unrelated worktree was untouched.

## Window and validation

Workload **15:55:51.622246–16:02:08.903280 UTC**, approximately **377.281034 s**.
Phase 2 **15:56:08.788056**, after a **17.165810 s** ramp. Measurement
**15:57:08.788056–16:02:08.788056 UTC**, exactly **300 s** after 60 s warmup.
The once-only namespace is `udp-send150-20261021`. Natural exit **2** reflects the
strict assertion failure; no controller abort, runtime error or rerun.

Actual Phase-2 schedules were atomically published with **53.254995 s** lead; no
dummy window. Game PID **601753**, start ticks **70820413**, invocation
`c2cd79695613444a8964f885a6df3263`, path/hash and buffers matched all **121** polls.
Bot PID **639136**, start ticks **70811374**, path/hash matched **120** polls while
present; no missing live identity or restart. Fresh zero-player/socket checks
preceded the single launch. Regression tests reject the old game path/hash,
wrong config, clamped buffers and changed PID/start/invocation. **15 local checks
passed**, including unchanged atomic-publication and analysis checks. Independent
offline recomputation verifies every offered/wire rate, Tick p99, transport bracket,
archive checksum and preservation of historical local reports/scripts.

## Load, delivery and compute

Every peer passed **29.7 Hz** offered and exact mapped wire requirements:
**29.993186–29.999853 Hz offered**, **29.770000–30.000000 Hz game-side wire**,
**29.766667–30.000000 Hz bot-side wire**. Offered count **1,349,879** over the
observed **300.001473903 s** boundary span; exact 300 s wire totals
**1,347,717 game / 1,347,715 bots**. The two-command endpoint difference remains
visible. Missed schedules **72**, versus 53 in dodge150. All 150 unique mappings
agree. Across **44,850 active bot-seconds** (299 complete UTC seconds), input counts
range **24–32**, median **30**, with no zero-input seconds. Exact partial seconds
enter the scored rates; complete seconds describe trajectories.

Ramp offered rates are **29.740609–30.731963 Hz** for **142** peers over their own
staggered first/last Running observations. IDs **143–150** lack two such pre-Phase-2
samples: their ramp rates remain unknown. The **1,101** bracketed active ramp
bot-seconds range **24–31** inputs, median 30, with no zero-input seconds. Unjoined
or unbracketed peers are not counted as zero.

All **150** remained authenticated throughout **9,000 Ticks**. Living population
**100–143**, median 120; projectiles **156–251**, monsters 0, effects 0–1. Every
peer received increasing Snapshot and ActionConfirm counts, with complete measured
delivery observations and no failed age gate. Aggregate Snapshot age p99/max
**43.296 / 53.465 ms**; ActionConfirm **55.436 / 124.252 ms**. Confirm maximum was
**84.054 ms** in dodge150, so delivery is not uniformly better; both runs pass the
predeclared per-peer p99 **250/500 ms** and observed maximum **<1 s** guards.
These sampled ages do not measure one-way latency or exact queue residence.

Generator CPU **78.521519% of one logical CPU**, versus **78.302151%** in dodge150;
game CPU **68.125696%**, versus **71.038213%**. These use strict inner host brackets
**299.051778 / 299.050156 s** (bots/game), with exact endpoints in the summary.
Outer matched brackets are separately retained; no interval is silently replaced.
Steal was **zero**. Generator CPU rose from a roughly **63.5%** early-warmup median
to roughly **79.5%** late, with wire medians around 30 inputs/s. Adjacent observation
rates and grouped medians describe trajectories; exact boundary counters score load.

Actual Tick rate **30.0 Hz**; work p99 **27.181973 ms**, maximum **41.016322 ms**,
**5** Ticks at/above 33.333 ms, versus comparator p99 29.667207 ms and 35 late Ticks.
Ending elapsed-Tick lag **0.431344 ms**, accumulator lag **0.719464 ms**. Deferred
wait first/last 30 s means **6.373333 / 6.252222 Ticks**, maximum 10; pending
replication means **3,998.399 / 3,812.039**, maximum 8,567. The unchanged backlog
rule passes; no hidden delivery/backlog failure offsets the observed error reduction.

## Transport and correctness

**Both hosts have zero full-workload and steady UDP send-buffer, receive-buffer,
input, checksum and memory error deltas; observed socket drops are zero.** Game
nonempty zero-byte sends are zero, independently agreeing with kernel SndbufErrors.
Game/bot application decode/send errors, panics and unexpected bot disconnects are
zero. There is no observed first send/receive-error bracket in this cell. The
comparator's first send error occurred at workload **+75.461411..+76.461524 s**.

Exact boundary transport records are **null**, not zero. The measured transport
counters use the inner bracket **1792598229048217991..1792598528350308997 ns UTC**,
approximately **299.302091 s**. It records **3,420,572 receive calls**, **3,270,912
received datagrams**, **3,000,482 send calls**, zero receive/send errors and zero
zero-byte sends. Cumulative maximum read gap at its end is **42.223139 ms**, versus
53.631855 ms in dodge150. Final/full-workload transport evidence is also retained.

Maximum sampled game `skmem.t` was **223,488 bytes**, with `tb=4,194,304`; `w=0`.
The prior cell sampled at most 258,304 with `tb=524,288`. Neither sampling series
caught saturation or establishes subsecond queue occupancy/residence. Game receive
memory reached **718,624 bytes** (full and steady); bots reached **11,824 full /
9,536 steady**, with transmit memory at most **2,880**. All retained socket rows
have PID attribution; missing-PID analysis still preserves null when absent.
Interface drops and qdisc drop/overlimit deltas are zero. Qdisc requeues were
**1,086 game / 658 bots** over the captured interval, not zero; full stats are kept.

Across the **299 complete measurement seconds**, game-side retry-command bytes
were **21,828,942**, versus **23,875,200**; incoming ACK commands **30,781,843**,
versus **30,740,384**. Peak incoming datagrams/ACK commands per retained 10 ms bin
were **325 / 8,448**. Exact-window retry-command bytes were **21,959,493** game-side.
The unchanged bounded v2 history counts observed repeated reliable commands, not
an exact outstanding reliable queue or application delivery. Endpoint differences
and timestamp backsteps remain in the summary.

**Strict `aoi_cull` fails: 126/150 within 1,150 units, below 95% required.**
Violating IDs: **43, 55, 58, 78, 85, 88, 102, 106, 108, 110, 112, 114, 115, 118,
122, 123, 125, 129, 131, 133, 140, 144, 147, 148**. The comparator had 19 violators.
`decode_clean` passes; `per_peer_budget` remains skipped under the original zero
rate-budget command. Baseline-reference misses and unknown delta entities are
**zero full/steady**, versus comparator **6 / 8**. Their absence in one observation
does not establish a correctness fix.

The byte-aware journal completely scanned **430,010 records** over the bounded
experiment. Oversized-unreliable warnings: **429,554 full / 348,964 steady**, versus
**429,342 / 349,181**. No panic or suppression notices. Raw retention is only a
**25,164,417-byte prefix**, below 24 MiB, while compact counts cover the full
interval. Full payload-size extrema remain unknown. The two `send` substring hits
are startup configuration/buffer messages, not send failures; 150 disconnect
records belong to normal shutdown. AoI and oversized findings remain unresolved.

## Interpretation and retained evidence

This observation supports the predeclared **burst-allowance explanation**: the
larger game send allowance removed observed send backpressure at valid offered
load without failing delivery or backlog gates. It did not merely defer the same
error until later within this full window. The sustained-drain explanation's
predicted delay/backlog deterioration was not observed. This does not identify
the precise kernel queue or rule out transient host/network stalls, entropy-driven
workload variation, or failure over longer durations. The pinned adapter's
WouldBlock→Ok(0) mapping remains relevant; no send tracing was performed. Exact
application-delivered input, send/receive queue residence, outstanding reliable
queue, and causal instrumentation cost remain unknown. No capacity increase is
claimed because strict correctness still fails.

Collector/counting source stayed **994cce8c7cb2f689cd59f4d09e93e270057aba7e**.
All five frozen source files, capture wrapper and atomic helper match dodge150.
The recorder was rebuilt in the new namespace, identically on both hosts, SHA
`825528ac5be6f2c4740a3450e13995d2d310f9991fcdffc672007c5b6b6f8c3c`;
its source is unchanged, not its path-dependent executable hash. Both readers
ended at EOF, with **7,756,677 game / 7,756,673 bot packets**, zero parse errors
and zero capture drops. Coverage, maps and boundaries pass. Boundary lateness
start/end: **0.129187 / 1.603090 ms bots**, **20.820304 / 25.572592 ms game**.

The existing 180/550/600/720 s ramp/workload/capture/restoration bounds, 48 MiB
capture guard, 64 MiB file limit and 512 MiB capture cgroup remained. Capture child
CPU **18.777180 / 30.410223 s**, max RSS **38,816 / 38,912 KiB**, retained sizes
**5,442,927 / 5,443,921 bytes** (game/bots). Host collector self/child CPU
**1.027%/2.609% game**, **1.305%/2.726% bots** of one core. Bot observation work
**1.418206195 s** over 377 completed samples is elapsed work, not causal overhead.

Restoration was armed before stopping the original service. Original measurement
files were copied and hash-verified before restart. Bot exit was verified, the
five-second quiet tail retained, then game/captures stopped. The original service,
config/drop-ins/measurement destination and ordinary **524,288 / 524,288** buffers
were restored. Independent read-only audits verify zero players, no owned
bots/collectors/timers/profilers, unchanged network/maintenance, all prior archives,
closed campaign state and **10 game-host / 5 bot-host** prebuild executable
artifacts. New builds, old artifacts and remote evidence remain separate and
retained. A final post-analysis read-only state/archive audit also passed on both
hosts. Audit results and timestamps are included in the summary.

Original game SHA `f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2`;
original bot SHA `8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf`;
original config SHA
`bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c`.
Control bot SHA `831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`
and the prior f1 game hash are independently preserved.

Private evidence: `deployment/hetzner/results/udp-send150-20261021/`.
Separate build evidence: `deployment/hetzner/results/udp-send150-20261021-build/`.
Remote originals: `/home/deploy/omega-results/udp-send150-20261021/` on both hosts.
Archives match retained remote originals:

```text
game.tar.gz  d88bc751089931da38cadd2211ca5fa50c62fed629619ffca979a75c91c35f71
bots.tar.gz  500e41cc6d2735397d2b857f758f4f4441c606683aaeedcce34d4b395293a715
```
