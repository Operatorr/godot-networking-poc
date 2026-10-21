# Strategy 150 sustained observation — 2026-10-21

**Exactly one workload; generator-invalid; no new validated capacity.** All 150 players
remained authenticated for the full 300-second window, but every bot offered only
**18.34025 Hz**, below the predeclared 29.7 Hz gate. Mapped wire input was
**15.38–18.22 Hz** per bot at both endpoints. Bot process CPU averaged **97.71% of one
logical CPU**. These conditions cannot establish game-server capacity at the required
input load. Historical validated **Strategy 100** remains the highest defensible pass.
No second workload, tuning, rebuild of game/bots, agent, commit, or ladder advancement occurred.

The [summary](capacity150-summary.json) contains all gates, per-bot endpoints and delivery
tails, exact counters and hashes. Conditions follow [the frozen plan](CAPACITY-150-PLAN.md)
without relaxing its thresholds. The run also failed game UDP-error, delivery, and strict
assertion gates; it is not a bug-free or article-ready result.

The scored UTC window was **13:53:03.180598–13:58:03.180598**, exactly 300 seconds.
Workload endpoints were **13:51:46.116052–13:58:03.313550**; Phase 2 began 17.0645 seconds
after launch. It completed its 360-second postjoin duration naturally, with exit code **2**
(strict assertion failure), not a controller abort. The controller decision, process exit,
and cleanup endpoints are recorded separately.

- **Population and Tick gates passed:** 150 authenticated throughout 9,000 measured Ticks;
  **30.0 TickHz**, calculated from actual measured Ticks / 300 seconds. Tick-work p99
  **26.651 ms**, maximum 37.938 ms, 12 Ticks at or above 33.333 ms. Ending elapsed-Tick lag
  **1.430 ms**, ending accumulator lag 1.597 ms. Deferred wait first/last 30-second means
  **6.116 / 6.100 Ticks**, maximum 10; pending replication means **3,892.59 / 2,905.30**,
  maximum 6,773. The existing campaign backlog rule passes.
- **Offered/wire gates failed:** each bot offered 18.34025 Hz. There were **397,350 missed
  input schedules** during measurement, 404,596 over the full workload. Complete active
  port-seconds total **44,850** (150 × 299 whole UTC seconds); absent mapped rows were
  zero-filled only within complete, bracketed coverage. Both endpoints have five zero-input
  bot-seconds, median 18 inputs/s, range 0–22. Exact 300-second wire counters, including
  partial seconds, supply the scored rates. All 150 one-to-one mappings agree across hosts.
- **Delivery failed:** every bot increased Snapshot and ActionConfirm counts. Aggregate
  Snapshot-age p99/max was **57.195 / 70.126 ms**; confirm-age p99/max **145.651 / 1,716.931 ms**.
  Bot **97** had confirm-age p99/max **901.816 / 1,696.198 ms**; bot **129** had
  **922.753 / 1,716.931 ms**. Both violate the 500 ms p99 and observed-one-second guards.
  The other 148 pass the per-bot delivery checks. These are sampled message ages, not
  one-way latency; missing intervals are not manufactured as zero-age samples.
- **UDP errors failed:** game and bot receive-buffer errors and observed receive-socket
  drops were **zero**. Game **SndbufErrors = 637**, during both the whole workload and the
  measured interval; bot UDP errors were zero. The game adapter independently recorded
  **637 zero-byte sends**, with zero reported send errors. First send-buffer error bracket:
  +118.489 to +119.489 seconds after workload start, delta 19. The matching totals support
  game-send attribution; there was no additional kernel send tracing.
- **Application counters passed, correctness did not:** zero bot/game decode failures,
  reported application send failures, panics, or unexpected bot disconnects. Full-workload
  and steady bot observations both contain **7 baseline-reference misses / 15 unknown
  delta-entity observations**. Complete journal scans counted **426,969 oversized-unreliable
  warnings full-workload / 350,000 steady**, payloads **1,201–1,606 bytes**. Strict
  `aoi_cull` failed: **107/150** bots within 1,150 units, versus 95% required;
  `decode_clean` passed. `per_peer_budget` was skipped because no rate budget was configured,
  as in the frozen command. These findings remain part of the correctness investigation.

Game CPU averaged **70.38% of one logical CPU**, bot CPU 97.71%; measured steal was zero.
Maximum sampled receive memory was **516,416 bytes game / 19,456 bytes bots**.
Interface drops and qdisc drop/overlimit deltas were zero. The cumulative maximum game read
gap was **41.601 ms**. Over 299.501 seconds of inner transport observations, service/routing,
World Tick, outbox flush and ENet flush consumed respectively **13.983%, 35.156%, 11.564%,
10.911%** of wall time. These phase measurements are not CPU hot-path attribution.

Across 299 complete UTC wire seconds, game-side reliable retry-command bytes were
**109,484,645**, incoming ACK commands **36,811,073**; peak incoming datagrams/ACK commands
per 10 ms were **198 / 5,134**. Version-2 rolling-history semantics remain unchanged.
Exact outstanding reliable queues, application-delivered inputs and receive-queue residence
remain unknown. Interface capture precedes socket overflow. Equal observed input counts
across endpoints do not prove application delivery.

Living population ranged **99–144** (median 115), projectiles 148–234, monsters 0–1 and
effects 0–1. World randomness is entropy-seeded; seed 30 governs bots, not identical World
trajectories. Zero receive drops at this substantially reduced offered load do not establish
that the larger buffer fixed 150-player throughput. The generator limit must be resolved
before attributing a server limit. Logging and collector perturbation remain possible
contributors, with no causal isolation in this observation.

The existing game was exact `f1cc5d645217ddc14a4069c3fe40992d496270ae`, executable SHA
`dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56`; bots SHA
`831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3`.
Only the new private configuration added `udp_receive_buffer_bytes: 2097152`, hash
`642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`.
Verified effective game receive/send **4,194,304 / 524,288**, bots **212,992 / 212,992**.
Strategy 150, seed 30, difficulty 1, Warrior/Rogue/Mage rotation, 30 Hz requested input,
100 ms stagger, original 30 Hz Tick/Snapshot, AoI/LOD/budgets and monster difficulty remain.
The isolated unsigned Arena had no API/persistence. Exact commands and bytes are private.

The [new controller](../../../../../scripts/load_campaign/udp_capacity150.py) stages the
`d2dfe73` atomic publication helper. No dummy window exists: the frozen bot's actual
`phase.json` marker supplies Phase 2, and both schedules are published by sibling-partial
transfer and rename **52.421 seconds before start**. PID **584244**, invocation
`d0187f626fea4162a35c83c5ba6b2db8`, and `/proc/PID/exe` hash passed the fresh pre-swarm gate
and all **125** subsequent polls. No experiment restart or measurement panic occurred.
Maps share existing status queries; no separate map SSH reads. Median query duration was
949 ms, median poll cadence 2.961 seconds, maximum cadence 9.186 seconds including publication.

Reader/counting sources, `capture.py` and `host_collect.py` were frozen from `994cce8`.
Only the standalone recorder was compiled; its executable SHA on both hosts is
`6e27c962d03af1d96081c16d6d20a2c0140148863874ee178895b808ce30f8cf`.
The new capacity wrapper explicitly extends 300→600 seconds. Ramp/workload/restoration
bounds were 180/550/720 seconds; 48 MiB capture, 64 MiB files, 512 MiB cgroup, 1/64
fingerprints, one-second host/socket/flow/port samples and 10 ms bins were retained.
Both readers ended cleanly with zero malformed packets and zero capture drops; exact schedules
and timestamps cover the full window. Captures continued through the bot exit and quiet tail.

Capture children used **18.415 / 27.018 CPU seconds** (game/bots), maximum child RSS
**38,760 / 41,084 KiB**, and approximately 5.18 MB retained per endpoint over about 394 seconds.
Host collector self/child CPU costs were **1.066%/2.765% game**, **1.333%/2.666% bots** of one
core. Bot observation work totaled **1.318 seconds of elapsed observer work** over
369 completed observations; this is measured elapsed instrumentation time, not causal slowdown.
No profiler or full pcap was retained.

One post-run controller defect remains in the executed source: journald returned `MESSAGE`
as bytes, and the initial string-only exporter failed. Both primary bundles remain unchanged.
A separate byte-aware supplement retained a bounded 24 MiB prefix; the entire **427,425-record**
experiment journal was then scanned remotely into checksummed per-window/per-second counters.
There was one invocation and no observed suppression notice or panic. The full raw JSON journal
was **not** copied locally: its 681 MB byte-array representation exceeded the predeclared bound.
The retained prefix is incomplete; complete compact counts and first findings supplement it.
No workload was rerun to recover logs. New recovery helpers and analysis preserve this limitation.

Restoration was armed before stopping the original service, whose current measurement files
were copied and hash-verified before restart. Cleanup stopped bots, verified exit, allowed a
five-second drain, stopped the game, then stopped collectors before archiving. Independent
verification and a second audit after journal recovery confirm original executable/config/
drop-ins/measurement destination, zero players, inactive restoration timer, no owned processes,
and unchanged network, buffers, maintenance, prior archives and closed campaign state.
No evidence was deleted; parent ledgers, prior scripts/reports and Rust sources were not edited.

Private evidence is `deployment/hetzner/results/udp-capacity150-20261021/`, with retained
remote originals in the same namespace under `/home/deploy/omega-results/` on both hosts.
Both primary bundles, the journal supplement and compact journal counters were independently
checked against retained remote SHA-256 values:

```text
game.tar.gz  503004f933e80c44e829ae69857f5514ea39bffc7ef0b2e81e95814c2ddb1a57
bots.tar.gz  d44da4359e117610284b5ceec7004185a295d505bad3145d41dd833d14ac6535
game-journal-supplement.tar.gz  34ff3724481ca432f8644582214b949577c918f388161e862cf97e8f9ab44f50
journal-counts.json  bbdfe7541f643be9e28ac3ab10fad638e381a937f76416820e6f346a0aa2d071
```

Local validation: two existing atomic-publication tests and seven new controller/analysis tests
pass, including direct-copy partial JSON visibility and journald byte-array messages. Python syntax checks pass.
No game/bot rebuild or new remote test was used for validation. Cleanup is complete; the parent
can resume from this failed, fully bounded observation.
