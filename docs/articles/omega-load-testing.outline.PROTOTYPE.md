# PROTOTYPE: article outline and narrative arc

> **Throwaway.** This is the prototype for [Article outline and narrative arc](https://github.com/Operatorr/godot-networking-poc/issues/32),
> part of the map [Article: load testing Omega Realm & why realtime games cap at ~64 players](https://github.com/Operatorr/godot-networking-poc/issues/23).
> It exists for the author to react to before [Write the full first draft of the article](https://github.com/Operatorr/godot-networking-poc/issues/33).
> It lives on branch `prototype/article-outline` and is never merged. The validated outline goes into the
> ticket's resolution comment.
>
> **Format note:** the prototype skill offers a logic demo or UI variants, and neither fits an article.
> The cheapest concrete artifact for an article is a section-by-section outline with word budgets,
> numbers and source placement. That is what this file is.

Markers: `[MEASURE]` = not yet measured. `[PENDING #31]` / `[PENDING #38]` = waits on an open ticket.
`[CHECK]` = a number I derived here that the draft must re-verify before printing it.
`[DECIDE]` = a question for the author (collected at the end).

---

## Working title (pick one, or none)

1. *We wanted 1000 players on one server. We broke at 190. Here's why everyone stops near 64.*
2. *Why realtime games cap at ~64–150 players, measured on a $7.59 server*
3. *The N² wall: load-testing a bit-packed Rust game server*

## The arc in one paragraph

We built a deliberately simple 2D bullet-hell game to find out if one server Instance can hold
500–1000 realtime players. On a 2-vCPU ARM box it holds 100 cleanly, and every ramp past that
breaks between 176 and 191 players. That's the same band where almost every realtime game sets its
player cap. The article explains why the band exists (per-Tick work that grows faster than N
against a fixed Tick budget), shows how tab-target MMOs escape it by changing the game instead of
the network, then opens up our own wire format bit by bit and our load test, so the reader sees the
N² term in our real bytes and our real CPU graph.

**Shape: open with our wall, explain it with the industry and the math, prove it with our bits and
our measurements, then say which wall it actually was.** ("Arc A" below. Alternatives are at the end.)

## Budget

~7,500 words of body, plus appendices that don't count. Per-section targets are in brackets.

---

## 0. Cold open: five ramps, one wall [~350]

**Point:** we asked for 200, 250, 500, 750 and 999 players. All five runs collapsed at nearly the
same population.

- Ramp peaks: **191 / 185 / 176 / 180 / 190** authenticated players, for requested 200/250/500/750/999.
- Hardware: one Hetzner CAX11 (2 vCPU Neoverse-N1, 4 GB, Falkenstein). Quoted at $6.99 compute +
  $0.60 IPv4 = **$7.59/month** (conditional quote).
- What happened: UDP receive-buffer errors first, then game CPU near one core, then mass disconnects.
- Hook: 190 sits right next to Warzone's 150, PlanetSide 2's 250 per faction, Star Citizen's ~100
  per server before meshing. Is that coincidence?
- **Figure F1:** `strategy-extension-timelines.png` (CPU and population per attempt). It already exists.

Sources: `docs/netcode/perf-notes/load-test-reports/2026-10-14-one-pass/STRATEGY-EXTENSION.md`, `CAX11-CONCLUSION.md`.

Guardrail to keep in the prose: these are **failed ramps, not a sustained capacity**. "CAX11 holds 190"
is not established. The sustained number is 100.

## 1. What Omega is and what we set out to prove [~450]

**Point:** the game is deliberately minimal, so the network is the thing under test.

- POC goal: 500–1000 concurrent players on one Instance. One ability, HP only, one monster type.
- Architecture in one diagram's worth: Rust `omega-server`, single-threaded **30 Hz** Tick,
  ENet over UDP (`rusty_enet` 0.4.0), 3 channels, `sim_core` shared by the server and client
  prediction. Rule: *the client requests, the server decides.*
- Define the glossary terms the rest of the article uses: **Tick**, **Snapshot**, **Instance**,
  **AoI**, **Baseline**. (Tick ≠ Frame ≠ Snapshot.)
- What we're *not* covering: prediction/interpolation feel, client rendering. Link out.

Sources: `docs/server/design.md`, `docs/CONTEXT.md`, `AGENTS.md`.

## 2. The ceiling everyone hits [~1,000]

**Point:** player caps come from a fixed CPU budget per Tick against work that grows faster than N.
Studios trade tick rate against player count against matches per core, then pick a design number
below the tech ceiling.

- **Trimmed case-study table** (~8 rows, not the full 20): Quake III (`MAX_CLIENTS 64 // absolute limit`,
  20 Hz), Source (designed for "32 or less"), Apex (60 players, 20 Hz, ~60 kB/s; 60 Hz = 180 kB/s),
  Valorant (10 players, 128 Hz, 2.34 ms/frame), Fortnite (100, 20→30 Hz, input throttled), Warzone
  (150 → 100 → 120), BF6 / REDSEC (30 Hz with 100+, 60 Hz "for the final fight"), Star Citizen
  (~100 per server, 500 per shard with meshing).
- **Derivation D1, the Valorant yardstick:** 1,080 players ÷ 36 cores = 30 players/core at 128 Hz
  = **3,840 player-Ticks per core-second**. Naive rescale to 30 Hz gives about **128 players/core**.
- The recurring reasons, in order: (1) relevance fan-out O(N²) per Tick, (2) fixed CPU per Tick,
  (3) lag-compensated hits multiply with N, (4) bandwidth per client and egress cost,
  (5) a Snapshot wants to fit one datagram. Briefly: rising tick-rate expectations, client limits.
- "The tech sets the ceiling, design picks a point below it" (MAG 256, Warzone, BF6 back to 64).
- The outliers (Star Citizen, EVE, PlanetSide 2) get past ~150 by changing the rules. Set up §4.
- Quotes to use: DICE "They were not running 100 players"; Valve's Source SDK comment; Riot's
  "a single game per core would be prohibitively expensive".

Source: `docs/research/realtime-player-caps.md` (TL;DR, per-game table, §1–9, notable quotes).
Cut: the "not confirmed" rows. The draft may footnote them.

## 3. The math of sending a world to N players [~1,200]

**Point:** bit-packing and delta compression are constant factors. Only AoI changes the exponent.

- Symbols table (N, k, b_e, H_s, H_d, f, L, d). Keep it short.
- **D2, per-datagram overhead:** IPv4 20 + UDP 8 + ENet 2 + 8 = **38 B** (IPv6: 60 B).
- **D3, the 1200 B rule:** IPv6 minimum MTU 1280 − 60 = 1220 → use L = 1200 B. Contrast ENet's
  default fragmentation threshold of 1364 B.
- **D4, quantization:** `bits(range, step) = ceil(log2(range/step + 1))`. Worked for our 0.1 u
  positions → 16 bits.
- **D5, downstream per client:** `D = f · (ceil(k·b_e/8) + d·(H_s + H_d))`. **Server egress:** `E = N·D`.
  Naive k = N−1 → Θ(N²). AoI k = min(N−1, ρπR², k_max) → Θ(N·k).
- **Worked grid (trimmed §9.2/9.3):** 64 / 100 / 1000 players at 30 Hz, naive vs AoI-64, 63-bit
  records. Headline cells: 1000 @ 30 Hz naive = **1,973 Mbit/s**, AoI-64 = **133 Mbit/s**.
- Packets per second matter too: the floor is N × f datagrams/s (1000 @ 60 Hz naive = 420k/s).
- **D6, transfer economics:** 1 Gbit/s sustained ≈ 324 TB/month, so 133 Mbit/s ≈ 43 TB/month.
  Egress billing can bind before link speed does.
- CPU per Tick: `C_sim + N·C_aoi + N·k·c_rec + N·d·c_send` against 1000/f ms. This connects the
  bandwidth math back to §2's CPU argument.
- **Figure F2 (new):** server egress vs N, naive vs AoI-64, at 30 and 60 Hz. Log y-axis.

Source: `docs/research/replication-math.md` §0–11. The formula sheet goes in Appendix A.
Cut or footnote: lockstep vs snapshot interpolation (§8). Mention in one sentence as the RTS escape hatch.

## 4. How tab-target MMOs put hundreds on screen [~800]

**Point:** they don't beat N². They send less, send it less often, and design combat that tolerates
the server being late. A twitch shooter can't copy any of these without becoming a different game.

- **D7, WoW AQ 2020:** 1,500 players × 1,499 recipients = **2,248,500 packets** per round of
  actions. "We can't solve it by throwing faster hardware at it."
- Latency budgets: 1.5 s global cooldown; 400 ms unit-on-unit batching until 2014; Claypool & Claypool:
  ~100 ms FPS / ~500 ms third-person RPG / ~1000 ms omnipresent.
- No lag compensation needed: target-by-unit-ID removes the per-Tick rewind cost.
- Sparse, event-driven movement: 2007 traces show TCP inter-arrival peaks at ~200/300 ms; under
  load, move updates only on start/stop. "Blizzard never published 'WoW sends movement at X Hz'."
- Degrade on purpose: EVE 1 Hz sim + TiDi down to 10%; layering, sharding, zone caps and queues
  (Wintergrasp 120/faction).
- They still break: AQ 2006 12-hour loop, B-R5RB = 21 h real time for ~2 h game time.
- Close: "what they give up that a realtime shooter can't" (§7 of the research doc). This hands off
  to our own bytes: which of those levers *could* a bullet hell use?

Source: `docs/research/mmo-scaling-tab-target.md` TL;DR, §1–3, §7. GW2 and Albion get at most one
line each. `[DECIDE]` placement (see question 2).

## 5. Omega's wire format, bit by bit [~1,300]

**Point:** here is the formula from §3 with our real constants plugged in, and where every byte goes.

- Framing: `[u8 type][payload]` over ENet, no length field (datagram boundaries). LSB-first bit packing.
  3 channels: ch0 Snapshots/confirms (unreliable sequenced), ch1 reliable + Baselines, ch2 input.
- **Input:** `PlayerInput`, 22 B, byte-aligned, 30 Hz → **660 B/s up**, constant even when idle.
- **Snapshot:** 16 B delta header, typed entity id, then records: moving player **49 b**, projectile
  **54 b**, monster **53 b**. Positions are absolute i16 at 0.1 u, truncated toward zero.
- "Delta" here = a 5-bit change mask over absolute values, against the last state *sent*. A Baseline
  every 100 Ticks. (The doc says acked. Mention it in a footnote at most; the drift fix is out of scope.)
- AoI: 1000 u enter / 1100 u exit. That's half the Arena's width, so a client sees ~42% of everything.
  *This is the punchline:* our AoI barely reduces k in a 2000 u Arena.
- **Where the bytes go (50 bots, measured):** average delta Snapshot **384 B**. **65% projectiles**,
  30% players. Downstream 13.7 KB/s per bot: Snapshots 83%, Game events 12% (mostly the 12 B
  `PROJECTILE_FIRED`), ActionConfirm 3.5%.
- Projectiles are re-sent every Tick even though their flight is deterministic. That's the single
  biggest waste, and it's design, not a bug.
- **D8, cost model:** `R(N) ≈ 1.3 KB/s + ~245 B/s · N` downstream payload. E = N·R → quadratic.
  Snapshots hit the 1200 B budget at **~165 players**. Past that, broadcast Game events (not
  AoI-filtered) keep growing without bound.
- **Figure F3 (new):** bit-layout diagram of one Snapshot (header + one record of each kind).
- **Figure F4 (new):** stacked bar of where the bytes go at 50 bots.
- Sidebar `[DECIDE]`: "Two numbers that lied to us": the 14.85 KB/s vs 5 KB/s gate (the gate sums both
  directions, has no derivation, and fixed costs alone are ~1.8 KiB/s), and the 32.9 Hz tick rate
  (an estimator dividing a span that includes the spawn phase by a fixed 120 s; 30 × 131.6 / 120 = 32.9).

Source: `docs/research/omega-wire-format-and-cost.md` §1–8. Full layouts go in Appendix B.
Cut: §10 doc drift (out of scope for the map).

## 6. How we load-tested it [~900]

**Point:** a load test is only as honest as its generator and its pass gates. Ours found bugs before
it found a ceiling.

- Topology: separate CAX11 game and bot hosts in the same zone, pinned release ARM builds, isolated
  unsigned dev mode, no API or persistence, source-restricted UDP.
- The bots: `omega-load-test` links `protocol` + `sim_core`, so every bot is a real client running
  real prediction, not a packet replayer.
- Workloads: movement / combat / clustered / strategy. 30 Hz input, 100 ms join stagger, 60 s warmup,
  **300 s measured window**, one observation per cell.
- Pass gates: 30 Tick Hz held, per-peer wire input ≥ 29.7 Hz, population held, UDP and delivery error
  counters clean. "A requested population is not an achieved load."
- **The load test found real bugs first.** This is the beat engineers will remember:
  - The UDP adapter **ignored ENet's requested socket buffers**. Effective limit was 212,992 B;
    after the fix, 524,288 B.
  - A cache/Baseline mismatch re-introduced entities with partial records.
  - New entities couldn't recover when their first unreliable FULL record was lost.
  - Host maintenance silently restarted captures and invalidated a Strategy 100 run.
- The generator can be the bottleneck: Strategy 150's bot host sat at 97.8% CPU and delivered 18 Hz
  input instead of 30. That result says nothing about the server.
- Collection cost: compact collector ~99% smaller than full packet capture (1.12 vs 110.5 MiB per
  preflight). One paragraph at most.

Sources: `docs/netcode/perf-notes/load-test-reports/2026-10-14-single-run/fixes-and-open-checks.md`,
`2026-10-14-one-pass/README.md`, `CPU.md`, `rust/load_test/README.md`, and the matrix decision on
[Define the new load-test matrix](https://github.com/Operatorr/godot-networking-poc/issues/30#issuecomment-6145030523).

## 7. Results [~1,100]

**Point:** 100 players clean on one core of a $7.59 box. The N² is visible in the bytes. Overload
starts in the receive path before CPU saturates.

- **Ladder table:** Movement passed 50/100/150. Combat passed 50/100 (150 failed). Clustered passed 50
  (75/100 had kernel UDP errors). Strategy passed 50/100 (125/150 failed offered load).
- **Strategy 100 (the headline pass):** 30.000 Tick Hz, 29.98 wire input Hz, Tick work p99
  **15.96 ms** of a 33.33 ms budget, game CPU mean 39.7% of one core, outbound **3.67 MB/s**.
- **D9, the N² in our bytes:** outbound per authenticated player-second is 21,867 B at Strategy 50 and
  36,704 B at Strategy 100. Doubling N grew per-player bytes **×1.68**, so total egress grew ~×3.4.
  `[CHECK]` the ratio against the §5 model before printing.
- **D10, model vs measured:** §5 predicts ~26 KB/s payload per client at N=100; with ~16% wire overhead
  that's ~30 KB/s, against 36.7 KB/s measured. `[CHECK]` the gap: the Strategy workload isn't the
  default bots, the recovery fixes add FULL records, and outbound IP bytes include reliable traffic.
- **Overload:** first game-host receive-buffer errors appear at **131–164 players**, while game CPU
  averages only 57–76% of one core. Later CPU hits ~100%, players drop, and joins time out.
  Peaks 176–191.
- **D11, Valorant yardstick (inference, flag it):** 128 players/core at 30 Hz (D1) vs our 100 passing
  and ~180 breaking. Same order of magnitude, from a 2D sim with no animation or 3D traces.
- **D12, transfer:** 3.67 MB/s × 2,592,000 s ≈ **9.5 TB per 30-day month** at 100 players
  `[CHECK]`. Billing/allowance → `[PENDING #31]`.
- **Figures:** F5 = `cpu-vs-population.png` (exists). F1 is reused or zoomed.
- `[PENDING #38]`: the UDP-error diagnosis may raise the validated ceiling and name the cause. If it
  does, this section gains a before/after table and §8 changes.
- `[PENDING #31]`: delay/jitter/loss results and Snapshot15/AoI600 transfer comparisons. If they land
  before the draft, add one subsection, "what the network does to it". If not, cut it.

## 8. Which wall did we hit? [~650]

**Point:** we land in the industry band. The reason is partly the same (fan-out on one serial Tick)
and partly our own (bursts overflowing a socket buffer before the CPU is full).

- What the data supports now: failure begins in the receive path, CPU saturation follows.
- Ranked hypotheses (from `CAX11-CONCLUSION.md`): serial loop runs out of time; packet bursts between
  socket reads; reliable retries amplify backlog; generator I/O. Say plainly which are unproven.
- The ~165-player Snapshot-budget prediction (D8) sits inside the 131–164 error onset. **Note it, don't
  claim it.** No causal link has been shown.
- What 1000 would take, mapped to the levers from §2–§4:
  1. Make AoI actually shrink k (a 1000 u AoI in a 2000 u Arena doesn't).
  2. Stop re-sending deterministic projectiles (65% of Snapshot bytes).
  3. AoI-filter broadcast Game events (the unbounded term).
  4. Get the Tick off one core: split the Instance (meshing/sharding) or parallelize replication.
- `[DECIDE]` the headline claim (question 3).

## 9. Conclusion [~250]

The cap isn't folklore. It's arithmetic plus a CPU budget. Tab-target games escape by changing the
game. A realtime game has to change *what* it sends and *to whom*. On a $7.59 box we got 100 players
for free and hit the wall at ~190, right where the industry stops.

## Appendices (outside the word budget)

- **A.** Formula sheet (replication-math §11, verbatim).
- **B.** Full bit layouts: `PlayerInput`, Snapshot header, typed id, each record kind.
- **C.** Reproduce it: build, run a load test, commands from `rust/load_test/README.md` and `scripts/load_campaign/`.
- **D.** Sources (primary only, grouped by section).

---

## Where each research finding lands

| Finding | Source | Section |
|---|---|---|
| Cap = fixed CPU per Tick vs superlinear work | realtime-player-caps TL;DR 1 | §2 |
| Valorant 3,840 player-Ticks/core-s | realtime-player-caps per-game table [D] | §2 (D1), §7 (D11) |
| Tick rate traded for N (BF V, BF6, Fortnite) | realtime-player-caps TL;DR 2 | §2 |
| Apex 60 → 180 kB/s at 3× tick | realtime-player-caps TL;DR 3 | §2 |
| Engine hard caps (Quake III, Source) | realtime-player-caps TL;DR 4 | §2 |
| Design picks below tech ceiling | realtime-player-caps TL;DR 5 | §2 |
| Outliers change the rules | realtime-player-caps TL;DR 6 | §2 → §4 |
| WoW AQ 2,248,500 packets | mmo-scaling TL;DR 1 | §4 (D7) |
| Latency tolerance 100/500/1000 ms | mmo-scaling TL;DR 2 | §4 |
| No lag compensation | mmo-scaling TL;DR 3 | §4 |
| Sparse movement updates | mmo-scaling TL;DR 4 | §4 |
| TiDi / layering / queues | mmo-scaling TL;DR 5 | §4 |
| They still break | mmo-scaling TL;DR 6 | §4 |
| 38 B per datagram | replication-math §1 | §3 (D2) |
| 1200 B from IPv6 MTU | replication-math §2 | §3 (D3) |
| bits(range, step) | replication-math §6 | §3 (D4), §5 |
| Θ(N²) vs Θ(N·k) | replication-math §5 | §3 (D5) |
| 64/100/1000 grid | replication-math §9 | §3 |
| CPU-per-Tick formula | replication-math §10 | §3 |
| 22 B input, 660 B/s | omega-wire-format §2 | §5 |
| 49/54/53-bit records | omega-wire-format §3 | §5, App. B |
| 65% projectiles | omega-wire-format §6 | §5, §8 |
| R(N) model, 1200 B at ~165 | omega-wire-format §7.3 | §5 (D8), §8 |
| 14.85 KB/s & 32.9 Hz | omega-wire-format §8 | §5 sidebar `[DECIDE]` |
| Loader bugs found | single-run fixes-and-open-checks | §6 |
| Ladder / Strategy 100 / overload | one-pass README, STRATEGY-EXTENSION, CAX11-CONCLUSION | §0, §7, §8 |

**Not placed (cut or footnote):** GW2/Albion detail, Halo: Reach host upstream, lockstep (§8 of
replication-math), the doc-drift list and the Sanctuary i16 bounds bug (both out of scope on the map).

## Figures

| # | Figure | Status |
|---|---|---|
| F1 | CPU + population per Strategy ramp | exists: `strategy-extension-timelines.png` |
| F2 | Server egress vs N, naive vs AoI-64, 30/60 Hz | new |
| F3 | Snapshot bit layout | new |
| F4 | Where the bytes go at 50 bots | new |
| F5 | CPU vs requested population | exists: `cpu-vs-population.png` |
| F6? | Fan-out diagram (N peers × k records) | optional |

---

## Alternative arcs (for comparison)

- **Arc B, textbook order:** industry (§2) → math (§3) → MMOs (§4) → our bits (§5) → test (§6) →
  results (§7). Safer and easier to write. The hook is weaker, because our 190 shows up at word 5,000.
- **Arc C, two articles:** Part 1 "Why realtime games cap at ~64–150" (§2–4, general, ~4k words).
  Part 2 "Load-testing Omega" (§0–1, §5–8, ~4k words). Each is easier to publish. Part 2 leans on Part 1.

## Questions for the author `[DECIDE]`

1. **Arc:** A (cold open with our wall), B (textbook), or C (split in two)? I recommend A.
2. **Where tab-target MMOs go:** before our bits (as "the levers", my recommendation) or after our
   results (as "how we might escape")?
3. **Headline claim:** "we hit the same wall the industry does" vs "how far a 2D top-down game can
   push it". Today's data supports the first, with a twist (receive path before CPU). Do we commit
   now, or leave a `[PENDING #38]` slot and decide after diagnosis?
4. **"The load test found bugs first" (§6):** its own beat (my recommendation), or trimmed to a sidebar?
5. **The 14.85 KB/s / 32.9 Hz sidebar:** keep it (good "numbers that lied" material), or cut it,
   since both come from the old historical runs?
6. **Length:** is ~7,500 words right, or should the draft aim for the 5k end and push detail into appendices?
