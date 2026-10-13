# Why do realtime games cap at ~64–150 players? Industry case studies

**Status:** Reference (research note) · **Ticket:** [#24](https://github.com/Operatorr/godot-networking-poc/issues/24) (parent map #23) · **Researched:** 2026-10-13

Feeds the technical article on load testing and on why realtime games cap their player counts.
It collects published numbers (player cap, tick rate, snapshot rate, per-client bandwidth) and
the reason each studio gave for its cap. Every number has a citation.

## Confidence legend

Each claim carries a tag:

- **[P]** Primary. Read directly in a first-party source: source code, an official engineering
  blog, official docs or FAQ, a GDC Vault abstract, or a first-party developer post.
- **[S]** Secondary. A first-party statement (tweet, forum post, interview) that I could only
  read as reproduced by the press or a mirror. The wording is probably accurate, but I did not
  read the original.
- **[U]** Unverified. Community measurements, press estimates, or summaries of talks I could not
  watch. Treat these as unconfirmed.
- **[D]** Derived. My own arithmetic on cited numbers, shown so it can be checked.

The quotes from web pages were pulled with a fetch tool. The quotes from source code (Quake III,
Source SDK, GameNetworkingSockets) and from the Valve Developer Wiki were read in full.

## TL;DR

1. Per-match player caps are rarely set by one hard limit. The server CPU budget per tick is
   fixed (1/tick-rate seconds per match, times the matches packed onto a core), and the per-tick
   work grows faster than linearly with N: relevance fan-out, replication and lag-compensated
   hit tests. Studios trade **tick rate against player count against matches per core**. Riot's
   Valorant math (128 Hz, at least 3 games per core, 2.34 ms per frame) is the cleanest published
   example.
2. Studios openly trade tick rate against N. BF V offered 120 Hz "for smaller modes". BF6
   REDSEC runs 30 Hz with 100+ players and steps up to 60 Hz "for the final fight". Asked why
   older Battlefields had higher tick rates, DICE's producer said: "They were not running 100
   players." Fortnite throttles movement uploads to 20 Hz until 24 players remain.
3. Bandwidth per client scales with (visible entities × update rate). Apex measured about
   60 kB/s per client at 20 Hz and said 60 Hz would mean 180 kB/s, "triple the bandwidth and CPU
   costs" for two frames of latency. Peer-hosted console games (Halo: Reach, 16 players) were
   capped by the host's upstream.
4. Engines encode the ceiling in code. Valve's Source SDK comment says: "The Source engine is
   really designed for 32 or less players… have a good answer for a bunch of perf question
   related to player simulation, thinking logic, tracelines, networking overhead". Quake III
   hard-codes `MAX_CLIENTS 64 // absolute limit`.
5. The public reason is often game design, even where the tech could go higher: MAG's 256,
   Warzone's 150 and later 100, BF6's return to 64. The tech sets the ceiling and design picks a
   point below it.
6. The 500+ player examples get there by changing the rules: split the world across processes
   (Star Citizen server meshing, about 500 per shard across several servers), slow the clock
   (EVE's time dilation), or accept lower fidelity (PlanetSide 2; its exact model is
   unverified). Even PlanetSide 2 cut its continent cap from 300 to 250 per faction for server
   performance.

## Per-game table

Rows run roughly chronologically. "Tick" means server simulation rate. "Snapshot/update" means
the rate of server→client state. Per-client bandwidth is downstream unless noted. "n/p" means
not published in any source I found.

| Game (year) | Player cap | Tick / sim rate | Snapshot / update rate | Per-client bandwidth | Stated reason for the cap | Sources |
|---|---|---|---|---|---|---|
| **Starsiege: Tribes** (1998) / **Tribes 2** (2001) | Tribes: up to 32. Tribes 2: "up to 100 in a single gaming area served by a 1GHz Pentium III" [P] | n/p | n/p (prioritised, non-retransmitting "Notify" protocol) [P] | **~2 KB/s** per client: designed for a 28.8 kbps modem [P] | Modem bandwidth. The whole model (prioritised, unreliable-by-default state) exists to fit 2 KB/s [P] | [OpenTNL history][tnl] |
| **Quake III Arena** (1999) | `MAX_CLIENTS 64 // absolute limit`; default `sv_maxclients 8` [P] | `sv_fps` default **20** [P] | Client `snaps` default **20**; client upload `cl_maxpackets` **30** [P] | Client `rate` default **3000 B/s** [P]; packets max `MAX_PACKETLEN 1400` B, larger messages fragment [P] | Hard-coded limit. The model suits "fewer clients, much higher bandwidth per client" than an MMO (Hook relaying Carmack) [S] | [sv_init.c][q3-svinit], [cl_main.c][q3-clmain], [q_shared.h][q3-shared], [net_chan.c][q3-netchan], [Q3 networking model][q3-hook] |
| **Half-Life / GoldSrc** (1998–) | 32 typical (n/p as a hard cap) | **60** tick (CS 1.6, HL1); 30 (TFC) [P] | **20** updates/s, 100 ms interpolation [P] | n/p | n/p. The latency-compensation design assumes modem/early-broadband clients [P] | [Valve wiki: Source MP Networking][vw-smn], [Bernier, GDC 2001][bernier] |
| **Source engine**: CS:S, DoD:S, TF2 (2004–) | Engine `ABSOLUTE_PLAYER_LIMIT 255`; game `MAX_PLAYERS` **33** default, **65** CS, **101** TF/HL2MP (current public SDK) [P] | **66.67** (15 ms default tick); 66 fixed in CS:S/DoD:S/TF2; 30 in L4D/L4D2 [P] | `cl_updaterate` default **20**, `cl_cmdrate` ~30, `cl_interp` 0.1 s [P] | Client-set `rate`; "players with a modem connection can't receive more than 5 to 7 KB/sec" [P] | Code comment: "The Source engine is really designed for 32 or less players" because of player sim, thinking, tracelines and networking overhead [P]. Higher tickrate "requires more CPU power and available bandwidth" [P] | [shareddefs.h][sdk-shareddefs], [const.h][sdk-const], [Valve wiki][vw-smn] |
| **CS:GO / CS2** (2012 / 2023) | n/p (competitive 5v5 by design) | CS:GO default **64** (community 128 via `-tickrate`); CS2 hard-coded **64** "with sub-tick" [P] | n/p | n/p | n/p | [Valve wiki][vw-smn] |
| **Halo: Reach** (2010) | **16**, one player hosts ("hosted client") [S] | n/p | Minimum **10 Hz** packet rate for solid play [S] | Host upstream ≥ **250 kbit/s** for a solid 16-player game; max **45 kbit/s** host→one client; ~**1 kbit/s** per biped per client in combat; max single-peer upstream 675 kbit/s [S] | Host upstream (peer-hosted). Latency targets 100/200 ms close-quarters, 133/300 ms ranged [S] | [UCL Networked Graphics summary of GDC 2011 talk][halo-ucl]; talk: Aldridge, "I Shot You First" (GDC Vault, free) |
| **MAG** (PS3, 2010) | **256** (8-player squads up to 256) [P] | n/p | n/p | n/p | "We picked 256 players as our target for game design reasons (how we divide up squads, platoons, etc)"; the architecture "could increase the number players well beyond" [P]. "There are trade-offs that would have to be made" [S] | [PlayStation Blog][mag-psblog], [TheSixthAxis quoting MAG dev blog][mag-tsa] |
| **PlanetSide 2** (2012) | Launch marketing ~2,000 per server/continent [S]; Guinness record **1,158** in one battle (24 Jan 2015) [P]; continent cap **300 → 250 per faction** (2022) [P*] | n/p [U] | n/p | n/p | 2022 cap cut: "the reintroduction of the Spawn Priority System is likely the cause of the performance issues when populations are high" (Wrel) [P*] | [Guinness][ps2-guinness], [Wrel dev post (mirror)][ps2-wrel], [GameWatcher (SOE quote)][ps2-forgelight] |
| **Overwatch** (2016) | 12 (6v6) | 60 Hz / 16 ms command frame (7 ms tournament) [U] | Client update rate **21 → 63/s** ("High Bandwidth", Aug 2016, PC), with "adaptive" scale-down for weak connections [S] | n/p | n/p (fixed by game design) | [Tentonhammer reproducing Blizzard CM post][ow-hb]; [GDC 2017 abstract][ow-gdc] |
| **Fortnite Battle Royale** (2017) | **100** players, "about 50,000 replicated Actors" per match [P] | **20 → 30 Hz** in standard modes; goal: 50v50 "hitting 30Hz for the entire match" [P] | n/p. Client→server movement throttled to **20 Hz**, raised to **33 Hz** once ≤24 players remain [P] | n/p | Default UE replication makes "each replicated Actor… determine whether or not it should send an update to each connected client… will bottleneck the server's CPU" [P]. The movement throttle is there "to reduce strain on the server's physics system, allowing it to maintain frame rate" [P] | [UE Replication Graph docs][ue-repgraph], [Fortnite State of Development v5][fn-sod] ([mirror][fn-sod-mirror]) |
| **PUBG** (2017) | 100 | Tick drops when players cluster; a figure of 4–8 Hz early-match is reported [U] | Distance-based: near objects every tick, far objects every **2–4 ticks** ("replication interleaving") [S] | n/p | "When many players are in close proximity… the network replication server processes slow down the server tick rate" [S] | Fix PUBG roadmap (2018) as reproduced by [GodIsAGeek][pubg-gaig]; [Shacknews][pubg-shack] [U] |
| **Apex Legends** (2019) | **60** (Battle Royale) [P] | **20 Hz** [P] | 20 Hz snapshot [P] | ~**60 kB/s** at game start; 60 Hz "would consume 180kB/s" [P] | "For triple the bandwidth and CPU costs, you can save two frames worth of latency"; "Keeping bandwidth costs low for games is much more critical than… video streaming" [P] | [Respawn netcode deep dive][apex], [EA BR mode page][apex-60] |
| **Valorant** (2020) | **10** (5v5) [P] | **128** tick → 7.8125 ms frame [P] | 128 Hz movement, fixed timestep [P] | n/p | Hosting economics: "a single game per core would be prohibitively expensive"; target better than **3 games per core** → **2.34 ms** per frame after 10% OS reserve. 36-core hosts → 108 games / 1,080 players per host. Server frame went from 50 ms to sub-2 ms [P] | [Riot: 128-tick servers][val-128], [Riot: Peeking into netcode][val-peek] |
| **Battlefield V** (2018) | 64 | **60 Hz PC / 30 Hz console**; "120Hz is of course supported for smaller modes" [S] | n/p | n/p | n/p. Tick rate traded against mode size [S] | Sirland tweet via [TheSixthAxis][bfv-tsa] |
| **Battlefield 2042** (2021) | **128** on PC/PS5/Xbox Series; **64** on PS4/Xbox One [P] | 45 Hz send/receive measured by community in beta [U] | — | n/p | Last-gen cap: EA says scale was reduced to keep "performance stable for older systems" [S] | [EA BF2042 FAQ][bf2042-faq], [EA forum thread (45 Hz)][bf2042-45] [U] |
| **Battlefield 6** (2025) / **REDSEC** BR | MP: **64** (128 dropped). REDSEC: 100+ [S] | MP: "60hz is the base for now" [S]. REDSEC: **30 Hz**, "60hz for the final fight" [P/S] | — | n/p | 64 MP: 128 "didn't catch on" in 2042 (design director, Edge) [S]. REDSEC 30 Hz: "They were not running 100 players. All that work makes 30 stable and 60 possible end game" [S] | [Sirland on X][bf6-x], [Insider Gaming][bf6-ig], [MP1st (60 Hz)][bf6-mp1st], [PC Gamer via inkl (Edge)][bf6-64] |
| **Call of Duty: Warzone** (2020) | **150** at launch; 200 tested; **100** on Urzikstan (2023), later 120 [S] | ~20 Hz reported by community [U] | n/p | n/p | 150 "works best for the mode overall" (Infinity Ward, paraphrased) [S]. 100: "time-to-action, the map size… circle timings… total match time (20 minutes)" (Raven) [S] | [Charlie INTEL][wz-150], [TechRadar][wz-100], [VGC][wz-100-vgc] |
| **Star Citizen** (Alpha 4.0, Dec 2024) | ~100 per server before meshing [S]; **500 per shard** with static server meshing (EPTU config "4:4:500" = 4 servers Stanton + 4 Pyro) [S]; tests at 350 (1 shard, 2 servers) [P], 1,000 and 2,000 (Test E) [P] | n/p | n/p | n/p | Single-server limits; meshing splits authority across processes. The 2,000-player test run was "especially rough" [P] | [Letter from the Chairman][sc-chairman] ([mirror][sc-chairman-mirror]), [Test E AAR][sc-teste], [4.0 EPTU notes][sc-eptu], [Digital Trends][sc-dt] |
| *Contrast:* **EVE Online** time dilation (2011) | Fights of "1600 or so" | Game clock slowed to "5%"–"10%" of real time when a node overloads [P] | — | — | "When a server is overloaded, there is no explicit mechanism for dealing with the situation" [P] | [CCP Veritas: Introducing TiDi][eve-tidi] |

\*[P*] PlanetSide 2's 2022 post is a first-party developer post (signed "-Wrel"), read through a
devtracker mirror of the original Reddit post.

**[D] Normalising Valorant:** 1,080 players ÷ 36 cores = **30 players per core at 128 Hz**, or
about **3,840 player-ticks per core-second**. This is the most useful single benchmark in the
set, because it states the CPU density that a commercial 128 Hz shooter needed to be
economical.

## The recurring reasons, synthesised

### 1. Relevance fan-out grows as O(N²) per tick

Every player is both an observer and a thing being observed. If everyone is relevant to
everyone, the server must decide, serialise and send about N×(N−1) entity updates per tick.

- Epic's docs say this directly. In stock UE replication, each actor checks each connection,
  which "will bottleneck the server's CPU" at Fortnite's 100 players and 50k actors. The
  Replication Graph was built to remove that per-actor, per-client check. [P][ue-repgraph]
- Riot found UE4 property replication slow because it "requires scanning through every variable
  marked as replicated every frame". Moving state changes to RPCs gave "100x to 10000x"
  improvements. [P][val-128]
- PUBG's fix was distance-tiered replication: near objects every tick, far objects every 2–4
  ticks. The problem it fixed was tick collapse "when many players are in close proximity".
  [S][pubg-gaig]
- **[D] Illustration.** With 100 mutually-visible players, 20 bytes per entity update and 30 Hz:
  100 × 99 × 20 B × 30 = 5.94 MB/s ≈ 47.5 Mbit/s egress per match, or about 59 kB/s per client.
  That is the same order as Apex's measured 60 kB/s. Doubling N roughly quadruples the egress
  and the relevance work.

### 2. The CPU budget per tick is fixed, so tick rate and N are traded against each other

The tick period is a hard deadline. Overrun it and the tick rate drops (PUBG's early-match
collapse) or the clock dilates (EVE).

- Valorant: 7.8125 ms per tick ÷ 3 games per core, minus 10% → 2.34 ms per game-frame for 10
  players. [P][val-128]
- DICE says it outright. BF V: 60 Hz, but "120Hz… for smaller modes". BF6 REDSEC: 30 Hz with
  100+ players, 60 Hz once the field thins, because "They were not running 100 players". [S][bfv-tsa] [S][bf6-ig]
- Fortnite: movement uploads at 20 Hz until 24 players remain, then 33 Hz, "to reduce strain on
  the server's physics system". [P][fn-sod]
- Battle royales therefore tend to run the tick rate as a function of how many players are
  alive.

### 3. Lag-compensated hit registration multiplies with N

Source-style lag compensation keeps "a history of all recent player positions for one second".
For every shot it rewinds "all other players" to the shooter's view time, traces, then restores
them. [P][vw-smn] The work per shot scales with N, and the number of shots also scales with N.
Valve's SDK comment names "tracelines" as one of the costs past 32 players. [P][sdk-shareddefs]

### 4. Downstream bandwidth per client, and egress cost for the operator

- Per-client bytes ≈ visible entities × bytes per entity × snapshot rate. Apex: 60 kB/s at
  20 Hz, 180 kB/s at 60 Hz. [P][apex]
- Historical floors forced low caps: Tribes 2 KB/s [P][tnl], Quake III `rate 3000` [P][q3-clmain],
  Source 5–7 KB/s modems [P][vw-smn].
- Peer hosting multiplies this by N on one home uplink. Halo: Reach needed at least 250 kbit/s of
  host upstream for 16 players, at up to 45 kbit/s per client. [S][halo-ucl]
- **[D]** Apex egress per match ≈ 60 clients × 60 kB/s ≈ 3.6 MB/s (~29 Mbit/s) at 20 Hz, and
  ~86 Mbit/s at 60 Hz. Respawn: "Keeping bandwidth costs low for games is much more critical
  than, say, for video streaming." [P][apex]

### 5. MTU: a snapshot wants to fit in one datagram

- Quake III caps packets at `MAX_PACKETLEN 1400` and fragments anything larger. [P][q3-netchan]
- Valve's GameNetworkingSockets caps the UDP payload at `k_cbSteamNetworkingSocketsMaxUDPMsgLen =
  1300`. [P][gns]
- Losing any fragment of an unreliable snapshot loses the whole snapshot. So a per-tick snapshot
  budget of about 1.2–1.4 KB caps how many entities each client can be sent per tick before
  you must prioritise, interleave or fragment. **[D]** At 20 B per entity that is about 60
  entities per snapshot. (Omega Realm's own invariant is "unreliable payloads < 1200 B".)

### 6. Tick-rate expectations keep rising

Competitive players now expect 60–128 Hz. Riot chose 128 Hz so that defenders get time to
react to peekers. A 10 ms swing in peeker's advantage moved playtest win rates. [P][val-peek]
Every doubling of tick rate halves the per-tick budget, so at fixed hardware cost N must shrink.
Respawn argues the opposite for BR scale: 20→60 Hz saves only about 2 frames of latency.
[P][apex]

### 7. Client-side limits

The cap is also bounded by the weakest client that has to render, animate and simulate N
characters. EA kept PS4 and Xbox One at 64 players to keep "performance stable for older
systems". [S][bf2042-faq] Riot's netcode targets 60 FPS "on most machines from this decade".
[P][val-peek]

### 8. The stated public reason is often game design

MAG said 256 was chosen "for game design reasons" even though the architecture could go
"well beyond". [P][mag-psblog] Warzone said 150 "works best". [S][wz-150] Raven's 100 was about
time-to-action and match length. [S][wz-100] BF6 dropped 128 because it "didn't catch on".
[S][bf6-64] A reasonable reading: the networking ceiling decides whether a number is possible,
and design decides where under it to land.

### 9. How the outliers exceed ~150

| Technique | Example | Cost |
|---|---|---|
| Split authority spatially across processes | Star Citizen static server meshing: ~500 per shard across about 8–10 servers [S][sc-eptu] → **[D]** about 50–60 players per server process | Hand-off at boundaries; the replication layer becomes the new bottleneck (2,000-player test "especially rough") [P][sc-teste] |
| Slow the simulation clock | EVE time dilation, down to 5–10% speed in fights of 1,600 [P][eve-tidi] | Unacceptable for twitch shooters |
| Relax fidelity or authority | PlanetSide 2 (1,158 in one battle) [P][ps2-guinness]; tick rate and hit model **not confirmed** from a primary source [U] | Still had to cut caps for server performance in 2022 [P*][ps2-wrel] |
| Purpose-built server tech | MAG (custom server-first architecture, 256) [S][mag-tsa] | "There are trade-offs that would have to be made" [S][mag-tsa] |

## Notable quotes

- Valve, Source SDK `shareddefs.h` (Yahn Bernier, 2003) [P][sdk-shareddefs]:
  > "The Source engine is really designed for 32 or less players. If you raise this number above
  > 32, you better know what you are doing and have a good answer for a bunch of perf question
  > related to player simulation, thinking logic, tracelines, networking overhead, etc."
- Valve Developer Wiki [P][vw-smn]:
  > "A higher tickrate increases the simulation precision, but also requires more CPU power and
  > available bandwidth on both server and client."
- Epic, Replication Graph docs [P][ue-repgraph]: Fortnite "starts each game with 100 connected
  players and about 50,000 replicated Actors"; per-actor-per-client relevancy "performs poorly in
  cases like this and will bottleneck the server's CPU."
- Riot, Brent Randall, 2020 [P][val-128]: running one game per core would be "prohibitively
  expensive"; "we knew we needed to do better than 3 games per core"; "a server frame took 50ms,
  and by the end we reached sub-2ms per frame."
- Respawn, Samy Duc, 2021 [P][apex]: "So for triple the bandwidth and CPU costs, you can save two
  frames worth of latency in the best-case scenario."
- Epic, Fortnite State of Development, 2018 [P][fn-sod]: movement updates are throttled to 20 Hz
  "to reduce strain on the server's physics system, allowing it to maintain frame rate… As the
  number of players… reduces to 24, we increase the frequency of updates to 33Hz."
- DICE, David Sirland, 2025 [S][bf6-ig]: "They were not running 100 players. All that work makes
  30 stable and 60 possible end game."
- Zipper Interactive, 2011 [P][mag-psblog]: "We picked 256 players as our target for game design
  reasons… with our architecture, we could increase the number players well beyond the
  256-person limit if we wanted to."
- Dynamix / TNL history [P][tnl]: TRIBES "must run well even over a 28.8 kbps modem, imposing a
  meager 2 Kbytes per second of bandwidth limitation on each client."
- CCP Veritas, 2011 [P][eve-tidi]: "Currently when a server is overloaded, there is no explicit
  mechanism for dealing with the situation."

## Not confirmed / did not check out

- **Overwatch 60 Hz sim / 7 ms tournament command frame.** Widely repeated from Tim Ford's GDC
  2017 talk. The Vault video is members-only and I did not watch it. [U]
- **Battlefield 2042 tick rate.** No DICE figure found. 45 Hz is a community capture and 25 Hz
  is a press claim. KitGuru's "128-tick servers" line reads like a mix-up with "128-player". [U]
- **Warzone tick rate (~20 Hz)** and **PUBG's tick numbers (4–8 Hz → ~60 Hz)** come only from
  community or press measurements. [U]
- **PlanetSide 2 tick rate and client-side hit detection.** Commonly asserted. I found no
  first-party statement. [U]
- **Halo: Reach bandwidth figures** come from a university blog summary of the GDC 2011 talk,
  not from the talk itself. [S]
- **Star Citizen 4.0 server count per shard** ("4:4:500", "10 servers") comes from search
  excerpts of RSI patch notes and press. The RSI pages are JS-rendered and I could not read them
  in full. [S]
- **Per-client bandwidth for Valorant, Fortnite, Overwatch, Battlefield.** Not published by the
  studios.

## Takeaways for Omega Realm (inference, not sourced)

- The binding constraints in these case studies are relevance fan-out, per-client egress and
  datagram size. Sim cost comes later. A 2D top-down sim with no skeletal animation or 3D
  traces removes much of what Riot spent its budget on (animation, physics), which leaves AoI
  fan-out and egress as the axes the load test should stress. See
  [`../netcode/interest-mgmt-aoi.md`](../netcode/interest-mgmt-aoi.md) and
  [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md).
- Valorant's ~3,840 player-ticks per core-second at 128 Hz is a citable yardstick. Scaling it
  naively to 30 Hz gives about 128 players per core. The omega-server tick is single-threaded,
  so a 500–1000 player Instance needs roughly 4–8× Valorant's per-core density. That has to come
  from a cheaper sim (2D, no animation) and from a strict AoI cap on visible entities per client.
  Linear scaling is optimistic, because fan-out is superlinear.
- Load tests should report players × tick rate × visible-entity count together. Every case
  study shows these three trading against each other.

## Sources

Primary [P] and secondary [S] sources, grouped by game.

- **Valve.** [Source Multiplayer Networking (Valve Developer Wiki)][vw-smn] ([archived copy][vw-smn-arch]) ·
  [Latency Compensating Methods… (Bernier, GDC 2001)][bernier] ·
  [Source SDK 2013 `shareddefs.h` L245–257][sdk-shareddefs] · [Source SDK 2013 `const.h` L30–37][sdk-const] ·
  [GameNetworkingSockets `steamnetworkingsockets_internal.h` L263–273][gns]
- **id Software.** [Quake III `sv_init.c`][q3-svinit] · [`cl_main.c`][q3-clmain] · [`q_shared.h`][q3-shared] ·
  [`net_chan.c`][q3-netchan] · [The Quake3 Networking Model (bookofhook, relaying Carmack)][q3-hook]
- **Dynamix / GarageGames.** [OpenTNL history][tnl]
- **Riot.** [VALORANT's 128-Tick Servers (Randall, 2020)][val-128] · [Peeking into VALORANT's Netcode (deWet & Straily, 2020)][val-peek]
- **Epic.** [Replication Graph (UE docs)][ue-repgraph] · [Fortnite State of Development v5 (2018)][fn-sod] ([mirror][fn-sod-mirror])
- **Respawn / EA.** [Servers & Netcode Developer Deep Dive (2021)][apex] · [Apex BR mode page][apex-60]
- **Blizzard.** [Overwatch GDC 2017 abstract][ow-gdc] · [High Bandwidth CM post (reproduced)][ow-hb]
- **DICE / EA.** [BF2042 FAQ][bf2042-faq] · [Sirland on X (REDSEC)][bf6-x] · [Insider Gaming (Sirland quotes)][bf6-ig] ·
  [MP1st (BF6 60 Hz)][bf6-mp1st] · [TheSixthAxis (BF V 60/30/120 Hz)][bfv-tsa] · [PC Gamer via inkl (Edge, 64 players)][bf6-64] ·
  [EA forum (BF2042 45 Hz, community)][bf2042-45]
- **Bungie.** [UCL Networked Graphics summary of "I Shot You First" (GDC 2011)][halo-ucl] · [Destiny GDC 2015 abstract][destiny-gdc]
  (architecture only, no player-count numbers)
- **Zipper / Sony.** [Five Things You Didn't Know About MAG (PlayStation Blog, 2011)][mag-psblog] · [TheSixthAxis (MAG dev blog quotes, 2009)][mag-tsa]
- **SOE / Daybreak.** [Guinness World Records (2015)][ps2-guinness] · [Wrel continent-cap post (mirror)][ps2-wrel] · [GameWatcher (Forgelight)][ps2-forgelight]
- **PUBG Corp.** [GodIsAGeek (Fix PUBG roadmap text)][pubg-gaig] · [Shacknews][pubg-shack]
- **Activision.** [Charlie INTEL (150)][wz-150] · [TechRadar (100)][wz-100] · [VGC (100)][wz-100-vgc]
- **CIG.** [Letter from the Chairman][sc-chairman] ([mirror][sc-chairman-mirror]) · [Server Meshing Test E AAR][sc-teste] ·
  [Alpha 4.0 EPTU patch notes][sc-eptu] · [Digital Trends (500 per server)][sc-dt]
- **CCP.** [Introducing Time Dilation (2011)][eve-tidi]

[vw-smn]: https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
[vw-smn-arch]: https://web.archive.org/web/2024/https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
[bernier]: https://developer.valvesoftware.com/wiki/Latency_Compensating_Methods_in_Client/Server_In-game_Protocol_Design_and_Optimization
[sdk-shareddefs]: https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/game/shared/shareddefs.h#L245-L257
[sdk-const]: https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/public/const.h#L30-L37
[gns]: https://github.com/ValveSoftware/GameNetworkingSockets/blob/d534c19aa760df3fb75fd20db13ba1932b8a5463/src/steamnetworkingsockets/steamnetworkingsockets_internal.h#L263-L273
[q3-svinit]: https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/server/sv_init.c#L573-L596
[q3-clmain]: https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/client/cl_main.c#L2304-L2349
[q3-shared]: https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/game/q_shared.h#L1092
[q3-netchan]: https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/qcommon/net_chan.c#L50-L52
[q3-hook]: https://fabiensanglard.net/quake3/The%20Quake3%20Networking%20Mode.html
[tnl]: https://opentnl.sourceforge.net/doxydocs/history.html
[val-128]: https://technology.riotgames.com/news/valorants-128-tick-servers
[val-peek]: https://technology.riotgames.com/news/peeking-valorants-netcode
[ue-repgraph]: https://dev.epicgames.com/documentation/en-us/unreal-engine/replication-graph-in-unreal-engine
[fn-sod]: https://www.fortnite.com/news/state-of-development-v5
[fn-sod-mirror]: https://devtrackers.gg/fortnite/p/bc794407-state-of-development-v5
[apex]: https://www.ea.com/games/apex-legends/news/servers-netcode-developer-deep-dive
[apex-60]: https://www.ea.com/en/games/apex-legends/apex-legends/game-objects/apex-legends-modes-hub/game-object/battle-royale
[ow-gdc]: https://gdcvault.com/play/1024001/-Overwatch-Gameplay-Architecture-and
[ow-hb]: https://www.tentonhammer.com/news/overwatch-high-bandwidth-servers-rolling-out.amp
[bf2042-faq]: https://www.ea.com/en/games/battlefield/battlefield-2042/faq
[bf2042-45]: https://forums.ea.com/discussions/battlefield-2042-general-discussion-en/battlefield-2042-tick-rate/6836617
[bf6-x]: https://x.com/tiggr_/status/1983276616928383071
[bf6-ig]: https://insider-gaming.com/battlefield-redsec-30hz-servers-beats-most-of-the-competition-says-lead-producer/
[bf6-mp1st]: https://mp1st.com/news/battlefield-6-server-tick-rate-60hz-enemy-visibility-improved-per-map
[bf6-64]: https://www.inkl.com/news/we-are-subservient-to-the-players-battlefield-6-ditched-128-player-matches-in-favour-of-classic-64-players-after-it-didn-t-catch-on-in-battlefield-2042
[bfv-tsa]: https://www.thesixthaxis.com/2018/10/24/dice-talk-server-tick-rates-for-battlefield-v-after-black-ops-4-controversy/
[halo-ucl]: https://ng.cs.ucl.ac.uk/?p=115
[destiny-gdc]: https://gdcvault.com/play/1022247/Shared-World-Shooter-Destiny
[mag-psblog]: https://blog.playstation.com/?p=44305
[mag-tsa]: https://www.thesixthaxis.com/?p=30881
[ps2-guinness]: https://www.guinnessworldrecords.com/news/2015/1/planetside-2-gamers-aiming-for-fps-battle-world-record-this-weekend-370414
[ps2-wrel]: https://devtrackers.gg/planetside/p/bdc3ac24-server-latency-issues
[ps2-forgelight]: https://www.gamewatcher.com/2013-09-04-sony-online-to-use-planetside-2-s-forgelight-engine-in-all-future-mmos
[pubg-gaig]: https://godisageek.com/2018/08/pubg-corp-launches-fix-pubg-campaign-improve-game-bug-fixes-performance-improvements/
[pubg-shack]: https://shacknews.com/article/105209/please-take-a-look-high-tick-rate-hot-drops
[wz-150]: https://www.charlieintel.com/call-of-duty-warzone/call-of-duty-warzone-features-150-players-59526/
[wz-100]: https://www.techradar.com/gaming/warzone-developers-explain-decision-to-move-from-150-player-to-100-player-matches-for-an-optimal-and-fun-experience
[wz-100-vgc]: https://www.videogameschronicle.com/news/activision-shows-off-warzones-new-map-and-confirms-it-only-supports-100-players
[sc-chairman]: https://robertsspaceindustries.com/en/comm-link/transmission/19848-Letter-From-The-Chairman
[sc-chairman-mirror]: https://api.star-citizen.wiki/comm-links/19848
[sc-teste]: https://robertsspaceindustries.com/spectrum/community/SC/forum/3/thread/server-meshing-test-e-after-action-report
[sc-eptu]: https://robertsspaceindustries.com/spectrum/community/SC/forum/190048/thread/star-citizen-alpha-4-0-eptu-patch-notes
[sc-dt]: https://www.digitaltrends.com/gaming/star-citizen-500-player-server-update/
[eve-tidi]: https://www.eveonline.com/news/view/introducing-time-dilation-tidi
