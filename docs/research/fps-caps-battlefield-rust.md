# Why Battlefield stays at 64, and how Rust runs 1000-pop servers

**Status:** Reference (research note) · **Ticket:** [#40](https://github.com/Operatorr/godot-networking-poc/issues/40) (parent map #23) · **Researched:** 2026-10-15

This note builds on two earlier ones and does not repeat them:
[`realtime-player-caps.md`](realtime-player-caps.md), the industry case-study table (it already has
rows for BF V, BF2042 and BF6), and [`replication-math.md`](replication-math.md), the formulas
(`E = N·D`, `k_AoI = min(N−1, ρπR², k_max)`). Terms follow [`../CONTEXT.md`](../CONTEXT.md):
**Tick** (one server sim step), **Snapshot** (one replicated state message to one client),
**AoI** (the region whose entities a client is sent), **Instance** (one running server copy of a map).

## Confidence legend

- **[P]** Primary. Read directly in a first-party source: an ea.com or rust.facepunch.com post,
  an EA-hosted PDF, a Battlelog post by DICE, a named developer's own tweet (read as raw tweet data
  through the api.fxtwitter.com mirror because x.com can't be fetched), a Facepunch commit message,
  or an official wiki.
- **[S]** Secondary. A first-party quote I could only read as reproduced by the press, or a
  value from community-decompiled code or plugin documentation.
- **[U]** Unverified. Community measurements, leaks, or arithmetic resting on an unsourced input.
- **[O]** Observed, third-party. Live server-list data (populations, caps). It is real
  measurement, but not a statement by the studio.
- **[D]** Derived. My arithmetic on cited numbers, with the working shown.

## TL;DR

1. **Battlefield's 64 is mostly a design choice made under a technical tax.** DICE's CEO said in
   2011: "Technically, we can go to 256, we've tried it… tested 128 and that it's not fun" [S].
   BF2042's 128 was removed from Breakthrough in Update 4.1 because "the value and impact of an
   individual player, and squad is reduced due to the increased intensity and chaos" [P]. BF6 went
   back to 64 because 128 "didn't catch on" [S]. **No** first-party DICE/EA source gives server CPU
   or bandwidth as the reason for 64.
2. **The tax is the Tick rate.** In every era the biggest Battlefield servers were the last to get
   higher rates, and got the smallest raise. DICE's 2015 BF4 guidance: 64 players → max 60 Hz on
   one Instance per machine. 32/48 players → 120 Hz. Under 20 → 144 Hz. The default was 30 Hz [P].
   In BF4 on consoles only servers of 32 players or fewer went to 45 Hz, because DICE "did not feel
   confident that 64 players will work flawlessly" [S]. BF6 REDSEC runs 100+ players at 30 Hz
   [P/S]. In Battlefield, more players means a lower Tick rate, not a different architecture.
3. **Battlefield is built so that nearly everyone is relevant to everyone.** Open combined-arms
   maps, vehicles, jets and long sightlines keep `k ≈ N − 1`, so `E ∝ N²`. The only first-party
   relevance mechanism found is BF4's "High Frequency Bubble": a radius that gets a *higher* update
   rate. It is not a cull [P].
4. **Rust's ~1000 is a wipe-day peak, not a steady state.** Facepunch's own servers cap at
   **250–400** [O]. The biggest community servers hit **1000–1600** on wipe day, then average
   **150–340** over the week [O]. The default `server.maxplayers` is 500 [S].
5. **Rust has no global Tick.** The server runs a variable Unity frame loop (`fps.limit` 240 [S],
   observed 25–98 server FPS [O]). Physics runs at 32 fps [P], player state goes out at a default
   16 Hz [S], and other entities send position at about 10 Hz, and only when they move [S].
6. **Rust's relevance model is a hard spatial cull.** Since 2014: "the world is divided into a grid
   for network reasons. A player is only sent the objects in adjacent cells" [P]. Cells are 32 m
   [P] and the default far radius is 8 cells [S]. That gives a 544 m square (a "blocky circle"
   since 2026 [P]) whose corners reach about 350 m, which Facepunch calls "the size of a default
   network grid" [P]. On top of that, players hidden behind terrain are culled by server occlusion
   [P]. Facepunch keeps the radius small on purpose: "We can't afford to do that on the mainland
   because of player and entity density" [P].
7. **Verdict on the hypothesis: confirmed, with qualifications.** At N = 1000 on a 4.5 km map,
   uniform density gives `k_players ≈ 10–19` against N − 1 = 999 [D]. That is a 50–100× cut, so for
   *players* `k ≪ N` holds even with heavy crowding. But (a) Rust's AoI is dominated by
   **entities** (bases, deployables; one Facepunch server had 362,299 [P]), not players. (b) The
   binding limit Facepunch reports is **server CPU per frame** (about 19 ms for 200 players [P]),
   not bandwidth. (c) The 1000 figure is a peak few servers sustain.

---

## 1. Battlefield

### 1.1 Player caps across the franchise

| Game (year) | Cap | Source |
|---|---|---|
| BF1942 (2002) | 64 | Retail/box copy only [U] |
| BF2 (2005) | Announced as "over 100", shipped at **64**: "competing online with up to 64 players" | EA ship press release, Jun 2005, via [reprint][bf2-ship] [S]. The "over 100" EA announcement (Apr 2004) I saw only in search snippets [U] |
| BF2142 (2006) | **64** Conquest, **48** Titan | EA press release via [reprint][bf2142] [S] |
| Bad Company 2 (2010) | 32 PC, 24 console. Bach: "Some think bigger is better. We want to make more and better use of the players we have." | [Game Informer preview][bc2-gi] [S] |
| BF3 (2011) | **64 PC / 24 console** | Patrick Bach via [GameWatcher][bf3-gw] [S] |
| BF4 (2013) | **64** PC/PS4/XB1; 24 PS3/360 | Bach on [Xbox Wire][bf4-xbw] [P]; last-gen 24 via press [U] |
| BF1 (2016) | 64 | No first-party page found [U] |
| BF V (2018) | **64**; Firestorm BR also 64: "it needs to feel like it's Battlefield" (Ryan McArthur) | [PlayStation Blog][bfv-psb] [P]; McArthur via Push Square/VG247 [S] |
| BF2042 (2021) | **128** current-gen, **64** last-gen | See [`realtime-player-caps.md`](realtime-player-caps.md) [S] |
| BF6 (2025) | **64** max; some Breakthrough layouts 48; 8v8 for small modes: "Rather than locking maps and modes to a fixed player count, our philosophy is to adapt to best fit the intended experience." | [Open Beta Debrief][bf6-debrief] [P] |

### 1.2 Server Tick and send rates (first-party where possible)

| Game | Rate | Source |
|---|---|---|
| BF3 | ~10 Hz server→client, ~30 Hz client→server | Forum claims only, no DICE figure [U] |
| BF4 launch | **30 Hz**; "we haven't got any immediate plans to increase the tickrate at this moment… we are exploring the possibilities of raising the tickrate on specific servers" | [Battlelog, "Addressing 'Netcode' in BF4"][bf4-netcode] [P] |
| BF4 PC high-tick (2015) | "Normally, servers in Battlefield 4 run at 30hz… All the way up to 144hz!" Per-size caps (below) | [EA-hosted PDF, signed David Sirland & the BF4 team][bf4-hitick] [P] |
| BF4 consoles (2016) | **45 Hz** for servers of 32 or fewer; 64-player stayed 30 Hz | Sirland via [MP1st][bf4-console] [S] |
| BF1 | 60 Hz PC / 30 Hz console. In alpha: "only on PC the tick rate is 60. On consoles it is 30." | [Julian Manolov tweet][bf1-jj] [P] |
| BF V | "30hz on console, 60hz on PC"; "120hz is of course supported for smaller modes" | Sirland tweets [1][bfv-x1], [2][bfv-x2] [P] (upgrades the [S] row in `realtime-player-caps.md`) |
| BF2042 | No first-party figure. Lead designer, asked about tick rate at 64 players: "We have no changes related to tickrate at this point". Community beta capture: 45 Hz both ways [U]. Leak-sourced claim of 25 Hz "to accommodate its 128-player lobbies" [U] | Le Bihan via [MP1st][bf2042-tick] [S] |
| BF6 | MP: "60hz is the base for now" [P]. REDSEC (100+): "Its 60hz for the final fight… our 30 beats most of the competition baselines" [P] | Sirland tweets [1][bf6-x60], [2][bf6-x30] |

**DICE's 2015 server guidance** ([PDF][bf4-hitick], [P]). Verbatim:

- "For 64 player servers we recommend a single instance per hardware, limiting max tickrate to 60hz"
- "For 48/32 player slots we recommend half the number of instances running per hardware
  (normally translates to 2 instances instead of 4 per server)"; "limiting the max tickrate to 120hz"
- "For <20 player slots we recommend limiting the max tickrate to 144hz"
- "higher tickrate requires both the server/client to do more work, and using more bandwidth to do it."

**[D]** The "normally 4" in the parenthesis is the 30 Hz Instance density. So a 64-player server
at 60 Hz costs **4× the hardware per match** of the 30 Hz default, for 2× the Tick rate. Per box
that is 4 × 64 × 30 = 7,680 player-Ticks/s at 30 Hz against 1 × 64 × 60 = 3,840 at 60 Hz. The
per-player cost rises with the Tick rate *and* with the player count. That is what you expect when
each player's Snapshot covers every other player (`N·k·f` with `k = N − 1`).

### 1.3 Why 64: what DICE/EA actually said

Design reasons, in DICE's own words:

- **2011, Patrick Söderlund (DICE CEO)** [S], via [GameRevolution][bf3-256] and [TheSixthAxis][bf3-256-tsa]:
  "Technically, we can go to 256, we've tried it. We play tested with 128." Also: "the most fun you
  can have is when it's between 32 and 40 players". And: "tested 128 and that it's not fun…
  Maybe we haven't done our design work good enough, but we just feel like there's no point in
  going higher than 64."
- **BF2042 Core Feedback: Maps** [P] ([ea.com][bf2042-maps]): "it can get too chaotic when fighting
  over Flags; either there are too many players, or vehicles… this issue is mainly related to 128
  player modes, and especially in Breakthrough." Also: "Breakthrough on 64 players provides the
  best experience". The post cites players calling it a "Walking Simulator". Future maps will be
  "smaller in scale". It says nothing about servers.
- **BF2042 Update 4.1, May 2022** [P] ([patch notes][bf2042-41]): "Our leading change is the
  removal of the 128 player version of Breakthrough." The reason given is that "the value and
  impact of an individual player, and squad is reduced due to the increased intensity and chaos of
  the combat", and 128 is "better suited for Conquest where gameplay spaces are larger".
- **Battlefield Briefing, May 2022** [P] ([ea.com][bf2042-brief]): "we have unshackled ourselves
  from 128 Player Game Modes when it comes to how we develop new modes", but "128 Players won't
  be going anywhere".
- **BF6 Open Beta Debrief, Aug 2025** [P] ([ea.com][bf6-debrief]), on Rush: "We've experimented
  with larger player counts over the years, such as 64- and even 128-player versions… Overwhelming
  defenses, stalled frontlines… when a player tries to arm the M-COM while more than 20 opponents
  are defending, the intended gameplay becomes less tangible."
- **BF6 back to 64**: 128 "didn't catch on" (design director, Edge, via PC Gamer) [S]. Already in
  `realtime-player-caps.md`.

Technical reasons, in DICE's own words (all about platform and Tick rate, never "64 is the server limit"):

- **BF3 consoles, Bach** [S] ([GameWatcher][bf3-gw]): "We would love to do 64 players on console
  but then we would have to cut away so much… there's a lot of data that has to go through the
  network and the CPUs… If you had more vehicles, that would mean less players and vice versa.
  Everything is a compromise."
- **BF4 on Xbox One, Bach** [P] ([Xbox Wire][bf4-xbw]): "64-players at 60 fps" had not been
  possible on consoles before without "taking away from the core 'Battlefield' experience".
- **BF4 console 45 Hz** [S] ([MP1st][bf4-console]): DICE "did see issues for both players, and
  sometimes the server… even at small tickrate increases" and "did not feel confident that 64
  players will work flawlessly on all maps for ALL players".
- **BF6 REDSEC** [S] (Sirland via Insider Gaming, already in `realtime-player-caps.md`): "They were
  not running 100 players. All that work makes 30 stable and 60 possible end game."

**Relevance in Frostbite** [P] ([Battlelog, June 2014][bf4-hfb]): "we are adding something we
nicknamed the 'High Frequency Bubble'. Within a certain radius of the player, we add the
possibility to update the clients at a higher rate from the server", for "player movement,
stance, rotation, damage and projectiles". It was rolled out "to all 48 player servers and on a
small set of 64 player servers… keep a close eye on the larger servers to make sure server
performance stays good". This is priority by distance, the update-rate half of an AoI. It is not a
cull. Nothing first-party says Battlefield ever stops sending distant players.

**Reading.** In the `k_AoI` formula, Battlefield is the case where `ρπR² ≥ N − 1`. The maps and
weapons are built so a player can see, spot, shell or be shot by most of the server, so
`k = N − 1` and egress and per-Tick work grow as `N²·f`. DICE's lever was never AoI. It is
N (design) and `f` (the Tick rate DICE will pay for). The published record says DICE picks N on
design grounds and `f` on cost grounds. This is my inference from the sources above, not a DICE
statement.

---

## 2. Rust (Facepunch)

### 2.1 Real populations

- **Default `server.maxplayers` = 500** [S], from decompiled `ConVar/Server.cs`
  ([RustChangelog mirror][rust-cl]). The official wiki's example uses `+server.maxplayers 10`
  with `+server.worldsize 4000`, and warns: "The more players, the faster your computer CPU needs
  to be" [P] ([wiki][rust-wiki]).
- A 500-player cap once existed in code. Devblog 171's changelog reads "Fixed 500 Player Limit" [P] ([devblog 171][rust-db171]).
- **Observed populations** [O], from [Rustalyzer][rustalyzer] on 2026-10-15
  (BattleMetrics returned HTTP 403 to the fetch tool):
  - Facepunch official servers are capped at **250–400** on 4500 m maps. Premium 1 hits 400 every
    wipe, with a 7-day average of 213.
  - Community wipe-day peaks: Rusty Moose 1000 (cap now 275, 7-day average 341), Magic Rust 1600
    (7-day average 221), MIRAGE "mp1350" peak 1387 (7-day average 154).
  - Server FPS ranges from 25 to 98.

So "1000-pop" is real but brief: a wipe-day peak on a handful of community servers. Sustained
load on the biggest servers is 150–400.

### 2.2 Tick and update rates

Rust has no single server Tick in the Battlefield sense:

- The simulation runs once per Unity frame, capped by `fps.limit` (default 240) [S]. Observed
  server FPS is 25–98 [O].
- `server.tickrate` (default 10) drives RCon, the companion app and Nexus, not the simulation [S].
- Physics: "the physics system only runs at 32 frames per second by default to avoid excessive
  CPU load" [P] ([The Performance Update][rust-perf]).
- Player network updates: `player.tickrate_sv`, default **16 Hz** [S]. Generic entities send
  position at about **10 Hz, only when moved** [S] (decompiled code via [RustChangelog][rust-cl]).
- Per-frame batching of position updates landed on 2026-10-14/15 [P] (commits [716764][c716764], [716963][c716963]).

### 2.3 The relevance model: network grid, occlusion, globals

- **Grid since 2014** [P] ([Friday Devblog 16][rust-fd16]): "the world is divided into a grid for
  network reasons. A player is only sent the objects in adjacent cells."
- **Cell size 32 m** [P]. Commit [549058][c549058] describes a 16,384 m area in 512 cells.
  The default far radius is **8 cells** and near is 4 [S] (plugin docs: [CustomNetworkRange][rust-cnr]).
- **[D]** Subscribed area: (2·8 + 1) × 32 m = **544 m square**, 0.296 km². The corner is
  256·√2 ≈ 362 m from the centre, which matches Facepunch's "around **350 meters** (the size of a
  default network grid)" [P] ([Maintenance][rust-maint]). Players outside it are "unable to see
  outside of that" [P].
- **Square → blocky circle, plus per-entity ranges (2026)** [P] ([Spring Clean][rust-spring]):
  "Before this change, the server networked everything in a large square around the player… now
  networks everything in a large, blocky circle around the player". Smaller entities (decor,
  dropped items) are networked only up close; vehicles further out. The commits describe layered
  grids at 128/256/512 m, with players on the medium layer [P] (commits [586937][c586937], [587940][c587940]).
- **Range kept small because of density** [P] ([Shipshape][rust-ship]): "We've also increased
  the network range from 300 to 620 metres in the Deep Sea… We can't afford to do that on the
  mainland because of player and entity density" (commit [579925][c579925]: 20 cells = 640 m).
  This is the clearest first-party statement that Rust's player capacity depends on keeping `R` small.
- **Server occlusion** [P]: players hidden behind terrain are not networked (introduced in
  [Road Renegades][rust-road], rocks added in Mar 2025, on by default since the
  [Jungle Update][rust-jungle]). It cuts `k` further but costs CPU: "up to 8ms… 10k occlusion
  queries for 350 players" ([Maintenance][rust-maint]).
- **What is global (all-relevant)?** The cargo ship, supply drops, patrol helicopter, planes and
  balloons, plus some building data through a `GlobalNetworkHandler` [P/S]. Team member positions
  go out by RPC roughly every 4 s [S]. **Remote players are never global.** Two players more than
  one AoI apart are never sent to each other, except as teammates at low rate.

### 2.4 What actually limits Rust: CPU and entities

- [P] [Devblog 58][rust-db58] (2015): "They can support 100 players without breaking a sweat. When
  you start getting into 200+ players things start to get a bit sweatier, and the biggest
  perspiration is the AI."
- [P] [Devblog 42][rust-db42]: "once a server hit around 50,000 entities its framerate would drop
  to around 5fps… now… a solid 60fps with 200 players and over 150,000 entities." A later post
  reports 362,299 entities on Facepunch EU2 ([Bags to Riches][rust-bags]).
- [P] [Crafting Update][rust-craft] (Mar 2025): "We spend about 19ms to process all 200 connected
  players in a server tick."
- [P] [Spring Clean][rust-spring] (2026), at 360 players, in a ~20 ms frame: serial antihack
  2.3 ms and "updating player's network streaming" 3.8 ms. The fix was parallelising the player
  update loop (`UsePlayerUpdateJobs`).
- [P] Bandwidth is not the headline cost. Commit [715823][c715823] saves ~105 KB/s on a
  122-player server, described as a 6% reduction.
  - **[D]** Total egress ≈ 105 / 0.06 ≈ **1.75 MB/s ≈ 14 Mbit/s**.
  - That is ≈ **14.3 kB/s ≈ 115 kbit/s per player**, the same order as the AoI-64 row in
    `replication-math.md` §9.2 (16.6 kB/s at 30 Hz).
  - **[D]** If D per player stays flat once the AoI saturates, 1000 players need about
    1000 × 14.3 kB/s ≈ **115 Mbit/s**. That is well inside one 1 Gbit/s port, so bandwidth is
    not what limits Rust.

---

## 3. The hypothesis: does 1000-pop work because k ≪ N?

**Hypothesis (author):** Rust's ~1000-pop servers work because players are spread out, so k (the
entities in one client's relevant set) is far below N, even at busy monuments like Outpost.

### 3.1 The math, with Rust's numbers

From `replication-math.md`: `E = N·D`, `D ≈ f·k·b_e/8 + per-datagram terms`, and
`k_AoI = min(N−1, ρπR², k_max)`.

**[D]** Inputs: worldsize 4500 m (official servers [O]) gives A = 20.25 km². This counts ocean;
land is smaller, which raises ρ (land fraction unsourced, so treat it as up to 2×). Take R from
256 m (cell edge) to 350 m (Facepunch's stated grid size).

| N | ρ = N/A (per km²) | k = ρπR², R = 256 m (0.206 km²) | R = 350 m (0.385 km²) | (N−1)/k |
|---|---|---|---|---|
| 200 (typical) | 9.9 | 2.0 | 3.8 | 52–98× |
| 400 (official cap) | 19.8 | 4.1 | 7.6 | 52–98× |
| 1000 (wipe peak) | 49.4 | **10.2** | **19.0** | **53–98×** |
| 1000, land only (assume 50% land) | 98.8 | 20.4 | 38.0 | 26–49× |

The AoI fraction πR²/A is 1.0–1.9% of the map, so a uniform k is about 1–2% of N.

**Crowding.** No first-party or observed counts of players at Outpost or Bandit Camp exist
(gap). Sensitivity check instead: put 100 players inside one AoI at Outpost on a 1000-pop server,
which is 10% of the server in about 1.5% of the map. Then k ≈ 100 + background 10–19 ≈ 110–120.
That is still **8–9× below N − 1**, and the cost is local: only the ~100 clients in that AoI pay
it. **[D]** Egress is the sum over clients:

```
E = f · Σ_i k_i · b_e/8
  = f · b_e/8 · (100·~115  +  900·~15)
  ≈ f · b_e/8 · 25 000       vs. naive  f · b_e/8 · 1000·999 ≈ 999 000   →  ~40× less
```

Even a heavy monument crowd leaves total player-replication work about 40× below naive broadcast.
`ρπR² → N` (the `replication-math.md` §5 caveat) needs most of the server inside one 350 m
radius. Rust's map size, spawn spread and base-building make that very rare.

### 3.2 Verdict: confirmed, with three qualifications

**Confirmed for players.** Rust is the real-world case of `k_AoI = ρπR²` far below `N − 1`.
A hard grid cull with R ≈ 256–350 m, plus occlusion, on a ~20 km² map gives
`k_players ≈ 10–40` at N = 1000. Facepunch keeps R small on purpose because of density ("can't
afford to do that on the mainland") [P]. Remote players are never globally relevant [P/S].
Battlefield sits at the other end: `k = N − 1` by design (§1.3).

**Qualifications:**

1. **k is dominated by entities, not players.** Rust's AoI carries every building block,
   deployable, dropped item and NPC in range. Servers hold 150k–362k entities [P], against
   N ≤ 1000. The per-entity network ranges and layered grids from 2026 [P] exist to shrink
   *entity* `k`. "k ≪ N" is true but beside the point: Rust's real `k` is set by build density.
2. **The binding cost is server CPU per frame, not replication bandwidth.** Facepunch's own
   profiles: about 19 ms for 200 players [P], and a ~20 ms frame at 360 players with 3.8 ms in
   network streaming [P]. Bandwidth comes to roughly 115 Mbit/s even at 1000 [D]. Low `k` is what
   makes the per-player network cost affordable. The per-player simulation (antihack, occlusion
   queries, AI, physics) is what actually bounds N. Rust also escapes a fixed Tick budget: it
   lets server FPS sag (25–98 observed [O]) where Battlefield would have to cut `f`.
3. **"1000-pop" is a wipe-day peak.** Facepunch caps its own servers at 250–400 [O]. The
   community servers that touch 1000–1600 average 150–340 over the week [O]. The architecture
   survives 1000 briefly, with degraded server FPS. Facepunch does not run it as a target.

For the article: AoI is what moves Rust from Θ(N²) to Θ(N·k) replication. That gets a 1000-player
Instance past the bandwidth wall, but not past the CPU wall. In Facepunch's own numbers, the CPU
wall sits at a few hundred players.

---

## 4. Survival comparison (one line each)

- **DayZ** [P] ([Bohemia wiki, server config][dayz-cfg], archived 2025-04-19): example
  `maxPlayers = 60`. Its network bubble is `networkRangeClose` 20 m, `networkRangeNear` 150 m,
  `networkRangeFar` 1000 m, and `networkRangeDistantEffect` 4000 m (sound only). Server limits:
  `-limitFPS` max 200, `simulatedPlayersBatch` 20 and `multithreadedReplication`. It runs a
  variable frame loop with no published Tick. Bohemia states no reason for 60. The common 127 cap
  comes from hosting companies [U]. In 2013 Dean Hall described the bubble as sending only nearby
  updates, targeting ≥15 FPS with 50 players, 2000 zombies and 25,000 loot items [S].
  DayZ's design is like Rust's: AoI first, with N bounded by simulated world state.
- **Escape from Tarkov**: about 8–14 PMCs per raid [U, third-party only]. Battlestate has stated
  no Tick rate and no reason for the cap. Patch 0.13.1.0 "Increased the number of network
  entities in the raid on Streets" [S]. Its small N goes with a dense, AI-heavy raid, so the
  cap is plausibly a server-CPU limit, not a bandwidth one [U, inference].

---

## 5. Gaps (searched, not found)

- **No first-party DICE/EA statement that 64 is a server, CPU or bandwidth limit.** Every
  128 → 64 rollback EA explained was framed as design.
- No first-party BF3 or BF2042 Tick/send rate. BF2042's 45 Hz (community capture) and 25 Hz
  (leak) conflict and are both [U].
- No first-party reason why BF2 went from "over 100" announced to 64 shipped.
- No DICE/Frostbite GDC networking or replication talk.
- I couldn't fetch the original Battlelog thread for Sirland's Feb 2016 console post, the
  VG247 Firestorm interview, the Edge BF6 interview, or the source tweet for "They were not
  running 100 players". All are [S].
- **No first-party or observed counts of concurrent players at Outpost/Bandit Camp, or inside one
  Rust AoI.** §3.1 uses a sensitivity bound instead.
- Rust's `player.tickrate_sv` 16 Hz, the 10 Hz entity rate, `fps.limit` 240, `maxplayers` 500 and
  the 8/4-cell radii come from decompiled code or plugin docs [S]. Facepunch has no published
  networking source. Its GitHub (e.g. Rust.Community, Facepunch.Steamworks) does not include
  the network visibility code.
- BattleMetrics blocked the fetch tool (HTTP 403). Observed populations come from Rustalyzer
  only, a single day's snapshot.
- Rust's land-to-ocean fraction, which would tighten ρ in §3.1, is unsourced.

---

## Sources

**DICE / EA (Battlefield)**
- [Battlelog: Addressing "Netcode" in BF4 (2014)][bf4-netcode] · [Battlelog: New netcode update / High Frequency Bubble (2014)][bf4-hfb]
- [BF4 High Tickrate BETA PDF (Sirland, 2015)][bf4-hitick] · [MP1st: BF4 console 45 Hz (Sirland, 2016)][bf4-console]
- [Xbox Wire: BF4 Q&A (Bach, 2013)][bf4-xbw] · [GameWatcher: BF3 console players (Bach, 2011)][bf3-gw]
- [GameRevolution (Söderlund, 256/128)][bf3-256] · [TheSixthAxis (Söderlund)][bf3-256-tsa]
- [Game Informer: BC2 preview (Bach)][bc2-gi] · [BF2 ship release reprint][bf2-ship] · [BF2142 release reprint][bf2142]
- [Manolov: BF1 alpha tick rate][bf1-jj] · [Sirland: BF V 30/60 Hz][bfv-x1] · [Sirland: BF V 120 Hz][bfv-x2] · [PlayStation Blog: BF V][bfv-psb]
- [BF2042 Core Feedback: Maps][bf2042-maps] · [BF2042 Update 4.1][bf2042-41] · [Battlefield Briefing May 2022][bf2042-brief] · [MP1st: Le Bihan on tick rate][bf2042-tick]
- [BF6 Open Beta Debrief][bf6-debrief] · [Sirland: BF6 60 Hz base][bf6-x60] · [Sirland: REDSEC 30/60 Hz][bf6-x30]

**Facepunch (Rust)**
- Devblogs: [Friday Devblog 16][rust-fd16] · [Devblog 42][rust-db42] · [Devblog 58][rust-db58] · [Devblog 171][rust-db171] · [The Performance Update][rust-perf]
- News: [Road Renegades][rust-road] · [Bags to Riches][rust-bags] · [Crafting Update][rust-craft] · [Jungle Update][rust-jungle] · [Maintenance][rust-maint] · [Shipshape][rust-ship] · [Spring Clean][rust-spring]
- Commits: [549058][c549058] · [579925][c579925] · [586937][c586937] · [587940][c587940] · [715823][c715823] · [716764][c716764] · [716963][c716963]
- [Rust wiki: Creating a server][rust-wiki]
- Secondary: [RustChangelog (decompiled convars)][rust-cl] · [CustomNetworkRange plugin][rust-cnr]
- Observed: [Rustalyzer][rustalyzer] (2026-10-15)

**Bohemia (DayZ)**
- [DayZ:Server_Configuration (archived 2025-04-19)][dayz-cfg]

[bf4-netcode]: https://battlelog.battlefield.com/bf4/news/view/addressing-netcode-in-bf4/
[bf4-hfb]: https://battlelog.battlefield.com/bf4/news/view/new-netcode-update-rolling-out/
[bf4-hitick]: https://eaassets-a.akamaihd.net/dice-commerce/battlefield4/assets/patch_notes/HighTickrat_BETA_R1_R4_DS.pdf
[bf4-console]: https://mp1st.com/news/battlefield-4-high-tickrate-servers-coming-to-xbox-one-playstation-4-this-week
[bf4-xbw]: https://news.xbox.com/en-us/2013/09/17/games-battlefield-4-qa/
[bf3-gw]: https://www.gamewatcher.com/2011-26-07-less-players-on-console-battlefield-3-no-evil-or-stupid-decision
[bf3-256]: https://www.gamerevolution.com/news/137-battlefield-3-can-handle-256-players-goes-intimate-instead
[bf3-256-tsa]: https://www.thesixthaxis.com/?p=74427
[bc2-gi]: https://gameinformer.com/games/battlefield_bad_company_2/b/pc/archive/2009/09/30/preview.aspx
[bf2-ship]: https://www.gamingnexus.com/FullNews/Battlefield-2-ships-to-stores2c-John-and-I-catch-mysterious-flu/Item522.aspx
[bf2142]: https://www.gamingnexus.com/News/2788/Battlefield-2142-dropped-onto-retail-shelves
[bf1-jj]: https://x.com/_jjju_/status/751472231352373249
[bfv-x1]: https://x.com/tiggr_/status/1054623169666056193
[bfv-x2]: https://x.com/tiggr_/status/1054801566186790913
[bfv-psb]: https://blog.playstation.com/?p=205762
[bf2042-maps]: https://www.ea.com/en-au/games/battlefield/battlefield-2042/community/battlefield-core-feedback-maps-kick-off
[bf2042-41]: https://www.ea.com/en-gb/games/battlefield/battlefield-2042/news/battlefield-2042-update-notes-4-1
[bf2042-brief]: https://www.ea.com/en-gb/games/battlefield/battlefield-2042/news/battlefield-briefing-development-update-may-2022
[bf2042-tick]: https://mp1st.com/news/battlefield-2042-tick-rate-changes-and-ping-value-in-scoreboard-not-in-the-cards-for-now
[bf6-debrief]: https://www.ea.com/games/battlefield/battlefield-6/news/community-update-open-beta-debrief
[bf6-x60]: https://x.com/tiggr_/status/1974185817800384794
[bf6-x30]: https://x.com/tiggr_/status/1983276616928383071
[rust-fd16]: https://rust.facepunch.com/blog/friday-devblog-16
[rust-db42]: https://rust.facepunch.com/blog/devblog-42
[rust-db58]: https://rust.facepunch.com/blog/devblog-58
[rust-db171]: https://rust.facepunch.com/blog/devblog-171
[rust-perf]: https://rust.facepunch.com/news/the-performance-update
[rust-road]: https://rust.facepunch.com/news/road-renegades
[rust-bags]: https://rust.facepunch.com/news/bags-to-riches
[rust-craft]: https://rust.facepunch.com/news/crafting-update
[rust-jungle]: https://rust.facepunch.com/news/jungle-update
[rust-maint]: https://rust.facepunch.com/news/maintenance
[rust-ship]: https://rust.facepunch.com/news/shipshape
[rust-spring]: https://rust.facepunch.com/news/spring-clean
[c549058]: https://commits.facepunch.com/549058
[c579925]: https://commits.facepunch.com/579925
[c586937]: https://commits.facepunch.com/586937
[c587940]: https://commits.facepunch.com/587940
[c715823]: https://commits.facepunch.com/715823
[c716764]: https://commits.facepunch.com/716764
[c716963]: https://commits.facepunch.com/716963
[rust-wiki]: https://wiki.facepunch.com/rust/Creating-a-server
[rust-cl]: https://github.com/MillionthOdin16/RustChangelog
[rust-cnr]: https://github.com/WheteThunger/CustomNetworkRange
[rustalyzer]: https://rustalyzer.com/
[dayz-cfg]: https://web.archive.org/web/20250419091101/https://community.bistudio.com/wiki/DayZ:Server_Configuration
