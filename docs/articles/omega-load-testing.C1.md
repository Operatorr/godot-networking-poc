# [PENDING title] Part 1: Why realtime games cap at ~64–150 players

> **First draft, Article C1 (part 1 of the two-part split, ~4k words of body).** Written for
> [Write the full first draft of the article](https://github.com/Operatorr/godot-networking-poc/issues/33).
> Part 2 is [`omega-load-testing.C2.md`](omega-load-testing.C2.md); the single-article version is
> [`omega-load-testing.A.md`](omega-load-testing.A.md). Sections 1–3 here are Article A §2–§4 with
> cross-references adjusted, so the author can compare like with like. Appendices are shared:
> [`omega-load-testing.appendices.md`](omega-load-testing.appendices.md). Evidence rules and markers:
> [`README.md`](README.md).
>
> **Title candidates** (`[PENDING]`):
> 1. *Why realtime games cap at ~64–150 players*
> 2. *The N² wall: why Battlefield stays at 64 and Rust doesn't*
> 3. *Hundreds on screen: what WoW does that a shooter can't*

---

## 0. Introduction: the same few numbers

Battlefield 2042 shipped 128-player modes. Within a year DICE had removed the 128-player version
of Breakthrough, and Battlefield 6 went back to 64. Warzone launched at 150, tested 200, and later
dropped to 100 on a new map. Apex runs 60. Fortnite runs 100. Quake III hard-coded 64 in 1999 with
the comment `// absolute limit`.

Meanwhile World of Warcraft put about 1,500 players in one zone for the Ahn'Qiraj event in 2020,
EVE Online has held 6,739 pilots in one solar system, and community Rust servers touch 1,000 on
wipe day.

So why do realtime shooters keep landing between 64 and 150? This part answers that from the
outside: published numbers from studios, the arithmetic of sending a world to N players, and the
tricks MMOs use to get past it. [Part 2](omega-load-testing.C2.md) answers it from the inside, with
a Rust game server we built to find out how far one Instance could go, and the load test that broke
it.

The short version: **a player cap is a fixed CPU budget per Tick set against work that grows faster
than the number of players.** Bit-packing and delta compression shrink that work by constant
factors. Only limiting what each player is sent changes how fast it grows. The games that break
past ~150 do it by changing the rules of the game, not by out-engineering the arithmetic.

A few terms, used exactly:

| Term | Meaning here |
|---|---|
| **Tick** | One step of the server's authoritative simulation. At 30 Hz, 33.3 ms. |
| **Frame** | One client render. Not a Tick. |
| **Snapshot** | One replicated world-state message from the server to one client. |
| **Baseline** | A full-state Snapshot that later delta Snapshots are encoded against. |
| **AoI** | Area of Interest: the region around a player whose entities that player is sent. |
| **Instance** | One running copy of a map, with its own player cap. |
| **Lag compensation** | The server rewinding positions to the Tick a shooter saw, so aimed shots register. |

---

## 1. The ceiling everyone hits

Look at enough realtime games and the same picture comes up. Player caps aren't usually set by one
hard limit. They come from a **fixed CPU budget per Tick** (1/tick-rate seconds, shared by
however many matches you pack onto a core) set against **per-Tick work that grows faster than N**.
Studios trade tick rate against player count against matches per core, then pick a design number
somewhere below the technical ceiling.

| Game | Players | Tick / update rate | What the studio said | Tag |
|---|---|---|---|---|
| Quake III Arena (1999) | `MAX_CLIENTS 64 // absolute limit` | `sv_fps` 20 | Hard-coded in [`q_shared.h`][q3-shared] | [P] |
| Source engine (2004–) | 32 by design, 255 absolute | 66.67 | "really designed for 32 or less players" ([SDK `shareddefs.h`][sdk-shareddefs]) | [P] |
| Apex Legends (2019) | 60 | 20 Hz | ~60 kB/s per client; 60 Hz "would consume 180kB/s" ([Respawn][apex]) | [P] |
| Valorant (2020) | 10 | 128 | ≥3 games per core, 2.34 ms per frame ([Riot][val-128]) | [P] |
| Fortnite (2017) | 100 | 20 → 30 Hz | Per-actor-per-client relevancy "will bottleneck the server's CPU" ([Epic][ue-repgraph]) | [P] |
| Warzone (2020) | 150 → 100 → 120 | ~20 Hz (community) | 150 "works best for the mode" ([Charlie INTEL][wz-150]) | [S] |
| Battlefield 4 (2013) | 64 | 30 default, ≤60 at 64 players | 64 players: one Instance per box, 60 Hz max ([DICE PDF][bf4-hitick]) | [P] |
| Battlefield 6 REDSEC (2025) | 100+ | 30 Hz, "60hz for the final fight" | "They were not running 100 players" ([Insider Gaming][bf6-ig]) | [S] |
| Star Citizen 4.0 (2024) | ~100 per server, 500 per shard | n/p | Server meshing splits authority across processes ([RSI][sc-eptu]) | [S] |

Tags: [P] primary source read directly, [S] first-party statement read through the press, [D]
our arithmetic. The full 20-row table, with every source, is in
[`realtime-player-caps.md`](../research/realtime-player-caps.md).

### The cleanest number in the set: Valorant

Riot published the arithmetic. At 128 Hz a Tick lasts 7.8125 ms. Riot needed better than three
games per core to make hosting affordable ("a single game per core would be prohibitively
expensive"), and reserved 10% for the OS, which left **2.34 ms per game per Tick** for 10 players.
A 36-core host runs 108 games, or 1,080 players. ([Riot, 128-tick servers][val-128].)

**D1, the yardstick [D].** 1,080 players ÷ 36 cores = **30 players per core at 128 Hz**, or
30 × 128 = **3,840 player-Ticks per core-second**. Rescaled naively to 30 Hz, that is
3,840 / 30 = **128 players per core**. Part 2 holds our own numbers up against it. The
rescale is naive on purpose: it assumes per-player cost is constant in N, and the rest of this
article is about why it isn't.

### Why the work grows faster than N

The recurring reasons, in rough order of how often studios name them:

1. **Relevance fan-out is O(N²) per Tick.** Every player is both an observer and something
   observed. If everyone is relevant to everyone, the server must decide, serialise and send about
   N × (N − 1) entity records per Tick. Epic's Replication Graph exists because stock Unreal
   replication checks every actor against every connection, which at Fortnite's 100 players and
   ~50,000 actors "will bottleneck the server's CPU" ([Epic][ue-repgraph]).
2. **The CPU budget per Tick is fixed.** Overrun it and the tick rate drops, or the clock dilates.
3. **Lag-compensated hits multiply with N.** Source keeps "a history of all recent player positions
   for one second" and rewinds "all other players" for every shot ([Valve wiki][vw-smn]). The work
   per shot grows with N, and so does the number of shots.
4. **Downstream bandwidth per client grows with visible entities × rate.** Apex measured about
   60 kB/s per client at 20 Hz and said 60 Hz would mean 180 kB/s: "for triple the bandwidth and
   CPU costs, you can save two frames worth of latency" ([Respawn][apex]).
5. **A Snapshot wants to fit in one datagram.** Lose one fragment of an unreliable Snapshot and the
   whole Snapshot is gone. Quake III caps packets at 1,400 B; Valve's GameNetworkingSockets at 1,300 B.

Two pressures sit on top. Players now expect 60–128 Hz, and every doubling of tick rate halves the
per-Tick budget. And the weakest *client* still has to render, animate and simulate every visible
character: EA kept last-gen consoles at 64 players in Battlefield 2042 to keep "performance stable
for older systems" ([EA FAQ][bf2042-faq]).

### Battlefield: 64 as a design choice, paid for in tick rate

Battlefield is the useful counterexample, because DICE has said in public that the engine could go
higher.

- 2011, DICE CEO Patrick Söderlund: "Technically, we can go to 256, we've tried it. We play tested
  with 128." And: "tested 128 and that it's not fun… there's no point in going higher than 64."
  ([GameRevolution][bf3-256], [S])
- Battlefield 2042 shipped 128-player modes, then removed 128-player Breakthrough in Update 4.1
  because "the value and impact of an individual player, and squad is reduced due to the increased
  intensity and chaos of the combat" ([EA patch notes][bf2042-41], [P]). Battlefield 6 went back to
  64 because 128 "didn't catch on" ([PC Gamer via inkl][bf6-64], [S]).

No first-party DICE or EA source gives CPU or bandwidth as the reason for 64. But the tax is
visible in the tick rate. DICE's 2015 guidance for Battlefield 4 high-tickrate servers, verbatim
([EA-hosted PDF][bf4-hitick], [P]):

- "For 64 player servers we recommend a single instance per hardware, limiting max tickrate to 60hz"
- "For 48/32 player slots we recommend half the number of instances running per hardware (normally
  translates to 2 instances instead of 4 per server)"; "limiting the max tickrate to 120hz"
- "Normally, servers in Battlefield 4 run at 30hz"

**[D]** The "normally 4" is the density at the 30 Hz default. So per box, 4 × 64 × 30 =
**7,680 player-Ticks per second at 30 Hz**, against 1 × 64 × 60 = **3,840 at 60 Hz**. Doubling the
tick rate of a 64-player server costs **four times the hardware per match**, not two. That is
what you expect when each player's Snapshot covers every other player: cost goes as N · k · f, and
k ≈ N − 1.

Why is k ≈ N − 1 in Battlefield? Because the game is built that way. Open combined-arms maps, jets,
artillery and long sightlines mean a player can see, spot, shell or be shot by most of the server.
The only first-party relevance mechanism we found is Battlefield 4's 2014 "High Frequency Bubble",
which sends *more often* to players inside a radius ([Battlelog][bf4-hfb], [P]). It changes the
rate. It isn't a cull. Nothing first-party says Battlefield ever stops sending distant players.

So DICE's levers are N (picked on design grounds) and f (picked on cost grounds). REDSEC, the
Battlefield 6 battle royale, shows both at once: 100+ players at 30 Hz, stepping up to 60 Hz "for
the final fight" once most players are dead ([Sirland][bf6-x30]).

> [AUTHOR] The reading "DICE picks N on design and f on cost" is our inference from the sources,
> not a DICE statement. Say so in the rewrite. Details: [Battlefield/Rust research note][fps-caps].

### The tech sets the ceiling, design picks the point

The public reason for a cap is very often design, even where the tech could go higher. MAG picked
256 "for game design reasons" and said its architecture "could increase the number players well
beyond" ([PlayStation Blog][mag-psblog]). Raven moved Warzone to 100 for "time-to-action, the map
size… circle timings… total match time" ([TechRadar][wz-100], [S]). The networking ceiling decides
whether a number is possible. Design decides where under it to land.

The few games that get well past ~150 do it by **changing the rules**. Star Citizen splits a world
across server processes (500 players across 8–10 servers is about 50–60 per process [D]). EVE
slows its game clock to 10% speed. Tab-target MMOs change what combat needs from the network.
Section 3 takes those apart. First, the arithmetic.

---

## 2. The math of sending a world to N players

This section derives the formulas. The point it builds to: **bit-packing and delta compression
are constant factors. Only AoI changes the exponent.** The full derivations, with every RFC and
source-file reference, are in [`replication-math.md`](../research/replication-math.md); the formula
sheet is [Appendix A](omega-load-testing.appendices.md#appendix-a-formula-sheet).

| Symbol | Meaning |
|---|---|
| N | connected players on one Instance |
| k | entities in one client's Snapshot (its visible set) |
| b_e | bits per entity record |
| H_s | Snapshot header bytes (per datagram) |
| H_d | per-datagram overhead below the game (IP + UDP + ENet) |
| f | Snapshot rate, Hz |
| L | max game payload per datagram |
| d | datagrams per Snapshot |

### D2: what each datagram costs before your first byte

An unreliable ENet message alone in an IPv4 datagram carries:

```
H_d = IPv4 20 + UDP 8 + ENet header 2 + SEND_UNRELIABLE command 8 = 38 B
```

The 20 and 8 come from RFC 791 and RFC 768. The ENet sizes come from the `#[repr(C, packed)]`
structs in `rusty_enet` 0.4.0, which match upstream `protocol.h`. ENet's header grows to 4 B when
the datagram carries a reliable command, so the worst case on IPv6 (40 B header, RFC 8200) is
40 + 8 + 4 + 8 = **60 B**.

That overhead is fixed per send, so it dominates small packets. Omega Realm's 22-byte input packet
(Part 2) is 38 / (22 + 38) = **63% header** on IPv4. A 1,200-byte Snapshot is 3.1% header.

### D3: where "1200 bytes" comes from

IPv6 requires every link to carry at least 1,280 octets (RFC 8200 §5). Subtract the worst-case
headers:

```
L_max = 1280 − 40 (IPv6) − 8 (UDP) − 4 (ENet header) − 8 (SEND_UNRELIABLE) = 1220 B
```

So **L = 1200 B** leaves 20 B spare on the strictest legal path. QUIC derives the same rule from the
same numbers (RFC 9000 §14), and Glenn Fiedler gives the same game-side advice: 1,000–1,200 bytes of
payload ([Gaffer On Games][gaffer-frag]). ENet's own fragmentation threshold is higher, at
1392 − 4 − 24 = 1,364 B, and an unreliable packet above it becomes *reliable* fragments by default.
That's the head-of-line-blocking trap a 1,200-byte cap protects against.

### D4: bits per number

A value in a range of width `range`, sent with step `q`, needs

```
bits(range, q) = ceil( log2( range / q + 1 ) )
```

Omega Realm's Arena is 2,000 units wide, quantized to 0.1 u: ceil(log2(20,001)) = **15 bits**. It
sends 16 (an i16), one bit over the minimum. Each 10× gain in precision costs about log2(10) ≈ 3.3 bits per
component.

### D5: downstream per client, and egress for the server

```
records per datagram   r = floor( (L − H_s) · 8 / b_e )
datagrams per Snapshot d = ceil( k / r )
down per client        D = f · ( ceil(k · b_e / 8) + d · (H_s + H_d) )
server egress          E = N · D
```

Drop the per-datagram terms and the headline is **bytes/s ≈ k × bytes per entity × f**, per client.
Then:

- **Naive broadcast**, everyone sees everyone: k = N − 1, so E = Θ(N²). Going from 64 to 1000
  players multiplies N(N − 1) by 999,000 / 4,032 = **248×**.
- **AoI**, each client only gets entities within radius R. With uniform density ρ = N / A,
  k ≈ min(N − 1, ρπR², k_max), and E = Θ(N · k). Once k saturates, egress is *linear* in N.

**One case, step by step [D].** N = 1000 at 30 Hz, naive broadcast, Omega Realm's full 63-bit player record,
IPv4, H_s = 12 B:

```
k = 999
r = floor((1200 − 12) × 8 / 63)      = 150 records per datagram
d = ceil(999 / 150)                   = 7 datagrams per Snapshot
payload P = 6 × (12 + 1182) + (12 + 780) = 7,956 B
wire W = P + 7 × 38                    = 8,222 B per Snapshot
D = 30 × 8,222                         = 246.7 kB/s ≈ 1.97 Mbit/s per client
E = 1000 × D                           ≈ 1,973 Mbit/s ≈ 2.0 Gbit/s
datagrams/s = 1000 × 7 × 30            = 210,000
```

With AoI capped at 64 entities, the same Instance needs d = 1, W = 554 B, D = 16.6 kB/s, and
E ≈ **133 Mbit/s**: 14.8× less, close to the asymptotic 999 / 64 = 15.6×.

**F2 data: server egress vs N, 63-bit player records [D].** Players only; projectiles and monsters add
on top with the same formula.

| N | 30 Hz naive | 30 Hz AoI-64 | 60 Hz naive | 60 Hz AoI-64 | Datagrams/s, 30 Hz naive |
|---:|---:|---:|---:|---:|---:|
| 16 | 0.6 Mbit/s | 0.6 | 1.3 | 1.3 | 480 |
| 32 | 2.3 | 2.3 | 4.5 | 4.5 | 960 |
| 64 | 8.4 | 8.4 | 16.8 | 16.8 | 1,920 |
| 100 | 19.9 | 13.3 | 39.8 | 26.6 | 3,000 |
| 150 | 44.1 | 19.9 | 88.1 | 39.9 | 4,500 |
| 200 | 80.1 | 26.6 | 160.1 | 53.2 | 12,000 |
| 500 | 495.8 | 66.5 | 991.7 | 133.0 | 60,000 |
| 1000 | 1,973.3 | 133.0 | 3,946.6 | 265.9 | 210,000 |

> [FIGURE F2 — new] Plot the four egress columns against N on log–log axes. The naive lines have
> slope 2, the AoI-64 lines bend to slope 1 at N = 65. Mark 1 Gbit/s as a horizontal line.

How to read it:

- **Tick rate is linear.** 30 → 60 Hz doubles everything.
- **Bit-packing is a constant factor.** Going from a naive 16-byte record (u16 id, three f32, u16
  state) to Omega Realm's 63 bits saves about 2×. Delta compression adds about 1.25× more when everything
  moves (see the caveats below).
- **AoI is the only lever that changes the exponent.** At 1000 players, naive broadcast needs 2–4
  Gbit/s of egress at 30–60 Hz, more than one 1 Gbit/s port. AoI-64 needs 0.13–0.27 Gbit/s.
- **Packets per second matter too.** ENet sends at least one datagram per peer per flush, so the
  floor is N × f datagrams per second, and every one is a syscall and kernel work. Naive 1000 at
  60 Hz is 420,000 datagrams per second.

### D6: the transfer bill

1 Gbit/s sustained is 125 MB/s × 2,592,000 s ≈ **324 TB per 30-day month**. So even the AoI-64
case at 133 Mbit/s is about **43 TB a month**. Many VPS plans meter transfer in single-digit TB, so
the egress bill can bind before the link speed does.

### The CPU side of the same formula

Bandwidth is only half of it. The work per Tick is roughly

```
C_tick ≈ C_sim(N, projectiles)       movement, collision, hit checks
       + N · C_aoi                   each client's visible-set query
       + Σ_i k_i · c_rec              serialise k records per recipient   → O(N · k)
       + N · d · c_send               ENet framing and one sendto() per datagram
```

against a budget of 1000 / f_tick ms: **33.3 ms at 30 Hz**. Record writes per Tick are N · k:
999,000 for naive 1000 players, 64,000 with AoI-64. The per-record cost `c_rec` isn't a citable
constant (it depends on your encoder), but as an **illustration only**, at 50 ns per record naive
1000 players costs about 50 ms per Tick in serialisation alone. That blows the 30 Hz budget on one
thread before the simulation has run. AoI-64 costs about 3.2 ms.

### Two caveats

**Delta compression buys less than you'd hope in a shooter.** Delta encoding sends only what
changed since a Baseline. In a bullet hell almost everything moves every Tick, so you still send
almost every position. Omega Realm's position-only delta record is 49 bits against a 63-bit full record: a
22% saving when everyone moves. It pays off on slow fields (flags, animation, HP) and idle
entities, not on positions.

**AoI isn't magic.** If everyone crowds into one radius (a boss fight, a town square), ρπR² → N
and you're back at Θ(N²). Only a hard cap on k (a byte budget plus priorities) bounds that case.
Plan capacity for the crowd, not the average.

### The real-world AoI example: Rust's 1000-player servers

Rust (Facepunch) is the game people point to when they say a realtime game *can* hold 1000 on one
server. It does, and the math says why. The details are in the
[Battlefield/Rust research note][fps-caps].

- **The relevance model is a hard spatial cull.** Facepunch, 2014: "the world is divided into a grid
  for network reasons. A player is only sent the objects in adjacent cells" ([Devblog 16][rust-fd16],
  [P]). Cells are 32 m and the default far radius is 8 cells, so the subscribed area is a
  544 m square whose corners reach about 360 m. Facepunch calls about 350 m "the size of a default
  network grid" ([Maintenance][rust-maint], [P]). Terrain occlusion culls further.
- **Facepunch keeps R small on purpose.** On extending the network range at sea: "We can't afford
  to do that on the mainland because of player and entity density" ([Shipshape][rust-ship], [P]).

**[D] k for players.** A 4,500 m map is 20.25 km² (including ocean). At N = 1000, ρ ≈ 49 players per
km². With R = 256–350 m, k = ρπR² ≈ **10–19** players. Assume only half the map is land and it
doubles to 20–38. Against N − 1 = 999, that is a 26–98× cut. Even a 100-player crowd at one
monument only raises k for those 100 clients; total replication work stays about 40× below naive
broadcast.

Three qualifications keep this honest:

1. **Rust's "1000" is a wipe-day peak.** Facepunch's own servers cap at 250–400. Community servers
   that touch 1,000–1,600 on wipe day average 150–340 over the week ([O], Rustalyzer, 2026-10-15).
2. **Rust's k is dominated by entities, not players.** Servers hold 150,000–362,299 entities
   (bases, deployables, drops) ([P]). The 2026 per-entity network ranges exist to shrink *entity* k.
3. **The limit Facepunch reports is server CPU per frame, not bandwidth.** "We spend about 19ms to
   process all 200 connected players in a server tick" ([Crafting Update][rust-craft], [P]). And
   bandwidth is small: one commit saved ~105 KB/s, described as 6%, on a 122-player server, which
   implies about **14.3 kB/s per player** [D]. At 1000 players that is roughly 115 Mbit/s, far
   inside one port.

So AoI is what moves Rust from Θ(N²) to Θ(N · k). It gets 1000 players past the bandwidth wall.
It doesn't get them past the CPU wall, which in Facepunch's own numbers sits at a few hundred.
Rust also escapes the fixed-Tick budget: there is no global Tick, and server FPS is allowed to sag
(25–98 observed). Battlefield, at the other end, sets k = N − 1 by design and pays in f.

---

## 3. How tab-target MMOs put hundreds on screen

If the math is that harsh, how does World of Warcraft put 1,500 players in one zone? The short
answer: **it doesn't beat N². It pays it less often, per entity, and it designs combat that
tolerates the server being late.** Full sources: [`mmo-scaling-tab-target.md`](../research/mmo-scaling-tab-target.md).

### D7: Blizzard did the arithmetic in public

In 2020 Blizzard rebuilt the Ahn'Qiraj gate event for WoW Classic and explained why it was hard
([Blizzard, Engineer's Workshop][blz-aq]):

> "In this group of 20, the server processes 380 packets (20 total players * 19 recipients = 380
> packets)." … "1,500 players then 2,248,500 packets"
>
> "What we faced is a polynomial problem, which means we can't solve it by throwing faster hardware
> at it because hardware's not exponentially better. Instead, we have to handcraft the optimization
> by deliberately choosing which data should be communicated to players and how often."

Check: 1,500 × 1,499 = 2,248,500. That is the same N(N − 1) fan-out from section 2.

### The lever is the latency budget

Each genre has a budget: how late the authoritative result can arrive before combat feels broken.
Claypool & Claypool's measurements put it at about **100 ms** for first-person shooters, **500 ms**
for third-person RPGs, and **1000 ms** for omnipresent games ([CACM 2006][claypool]). Every MMO
scaling trick spends that budget.

- **WoW batched on purpose for ten years.** Blizzard's Celestalon, 2014: "Any action that one unit
  takes on another different unit used to be processed in batches every 400ms" ([Blizzard
  forums][celestalon]). Players treated mutual Polymorphs and posthumous heals as quirks.
- **The global cooldown caps the action rate.** Most abilities share a 1.5 s cooldown (0.75 s at the
  haste floor), so nobody acts more than about once a second.
- **No Lag compensation.** A heal or a target-locked missile resolves against a unit ID on the
  server. Nothing aims at a position the shooter saw 80 ms ago, so there is no rewind buffer and
  no per-shot rewind cost.
- **Movement is sparse and event-driven.** 2007 packet traces show WoW clients on TCP with
  inter-arrival peaks around 200 and 300 ms ([Molnár & Szabó][molnar]). Under the AQ load Blizzard
  went further: dropping facing updates and sending player movement "only whenever a player starts,
  stops, or uses keyboard movement". Blizzard has never published a movement rate in Hz.
- **EVE simulates at 1 Hz.** "Each ballpark runs at a rate of one tick per second" ([CCP
  Masterplan][drakes1]). When a node overloads, **Time Dilation** slows the game clock, down to
  10% ([CCP Veritas][eve-tidi]).
- **Split the crowd.** WoW layers regions and shards zones (a WoW "shard" is a copy of one zone, not
  an Omega Shard); Wintergrasp queued at 120 per faction;
  Albion runs each zone on one thread and queues players proportionally per alliance.

### They still break

The 2006 AQ gate opening put players in "a loop of logging in, disconnecting, and trying to get
back online over a 12-hour period" ([Blizzard][blz-aq]). EVE's B-R5RB battle in 2014 ran at the 10%
dilation floor for about 21 hours of real time to compute "just over 2 hours" of game time
([CCP][br5rb]). Check: 21 h × 10% ≈ 2.1 h.

### What a shooter can't borrow

| Lever | Why a bullet hell can't pull it |
|---|---|
| Low, event-driven movement rate | Projectiles hit *positions*. Coarse remote motion means shots miss what the shooter saw. |
| 400 ms server batching | A dodge is decided in one or two Ticks. 400 ms is longer than a whole dodge. |
| Unit-ID targeting, no Lag compensation | Aim is the skill. A hit has to be checked against where things were. |
| Time Dilation | Twitch feel collapses at any dilation. |
| Culling distant characters | You can't dodge bullets from enemies you can't see. |
| Layering, zone caps, queues | **This one transfers.** Omega already caps per Instance. |

So which levers *can* a bullet hell use? Only the ones from section 2: shrink k (real AoI), send fewer
bits per record, send less often, or split the Instance.
---

## 4. Conclusion: arithmetic, then design

The cap isn't folklore. Every realtime server has a Tick deadline, 33.3 ms at 30 Hz and 7.8 ms at
128 Hz, and every player adds work that touches every other player they can see. With k ≈ N − 1,
that work is N², and doubling the tick rate doubles it again. Battlefield 4's own server guidance
shows the bill: twice the tick rate for a 64-player match cost four times the hardware.

The levers are few and well known:

- **Fewer players (N).** Usually justified as design, and often honestly so.
- **Lower rate (f).** Battle royales raise the tick rate as players die.
- **Smaller visible set (k).** AoI. It is the only lever that changes the growth order, and it only
  works if the game lets players be far apart. Rust's grid keeps k at 1–2% of N. Battlefield's maps
  keep k at N − 1 on purpose.
- **Fewer bits per record.** Quantization and bit-packing: a constant factor of about 2×.
- **Tolerate lateness.** WoW, EVE and Albion spend a latency budget of 500 ms to seconds on
  batching, throttling, time dilation and queues. A shooter's ~100 ms budget doesn't stretch that far.
- **Split the world.** Layering, sharding, server meshing. This is the one MMO lever a shooter can
  borrow.

And even with all of them pulled, something else is waiting. Rust gets past the bandwidth wall at
1000 players and runs into a CPU wall at a few hundred, in Facepunch's own measurements.

What does this look like on a real server? In [Part 2](omega-load-testing.C2.md) we take a
deliberately minimal Rust bullet-hell server, open its wire format bit by bit, plug its real
constants into the formulas above, and load-test it on a $7.59-a-month ARM box. The first build's
join ramps broke near 190 players. Why they broke there, and what changed after we fixed our bugs,
including several in the test itself, is the rest of the story.

## Appendices

Shared: [`omega-load-testing.appendices.md`](omega-load-testing.appendices.md) (A formula sheet,
D sources). B and C belong to Part 2.

<!-- Reference links -->
[fps-caps]: https://github.com/Operatorr/godot-networking-poc/blob/research/fps-caps-battlefield-rust/docs/research/fps-caps-battlefield-rust.md
[q3-shared]: https://github.com/id-Software/Quake-III-Arena/blob/dbe4ddb10315479fc00086f08e25d968b4b43c49/code/game/q_shared.h#L1092
[sdk-shareddefs]: https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/game/shared/shareddefs.h#L245-L257
[vw-smn]: https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
[apex]: https://www.ea.com/games/apex-legends/news/servers-netcode-developer-deep-dive
[val-128]: https://technology.riotgames.com/news/valorants-128-tick-servers
[ue-repgraph]: https://dev.epicgames.com/documentation/en-us/unreal-engine/replication-graph-in-unreal-engine
[wz-150]: https://www.charlieintel.com/call-of-duty-warzone/call-of-duty-warzone-features-150-players-59526/
[wz-100]: https://www.techradar.com/gaming/warzone-developers-explain-decision-to-move-from-150-player-to-100-player-matches-for-an-optimal-and-fun-experience
[bf4-hitick]: https://eaassets-a.akamaihd.net/dice-commerce/battlefield4/assets/patch_notes/HighTickrat_BETA_R1_R4_DS.pdf
[bf4-hfb]: https://battlelog.battlefield.com/bf4/news/view/new-netcode-update-rolling-out/
[bf6-ig]: https://insider-gaming.com/battlefield-redsec-30hz-servers-beats-most-of-the-competition-says-lead-producer/
[bf6-x30]: https://x.com/tiggr_/status/1983276616928383071
[bf6-64]: https://www.inkl.com/news/we-are-subservient-to-the-players-battlefield-6-ditched-128-player-matches-in-favour-of-classic-64-players-after-it-didn-t-catch-on-in-battlefield-2042
[bf3-256]: https://www.gamerevolution.com/news/137-battlefield-3-can-handle-256-players-goes-intimate-instead
[bf2042-41]: https://www.ea.com/en-gb/games/battlefield/battlefield-2042/news/battlefield-2042-update-notes-4-1
[bf2042-faq]: https://www.ea.com/en/games/battlefield/battlefield-2042/faq
[sc-eptu]: https://robertsspaceindustries.com/spectrum/community/SC/forum/190048/thread/star-citizen-alpha-4-0-eptu-patch-notes
[mag-psblog]: https://blog.playstation.com/?p=44305
[gaffer-frag]: https://gafferongames.com/post/packet_fragmentation_and_reassembly/
[rust-fd16]: https://rust.facepunch.com/blog/friday-devblog-16
[rust-maint]: https://rust.facepunch.com/news/maintenance
[rust-ship]: https://rust.facepunch.com/news/shipshape
[rust-craft]: https://rust.facepunch.com/news/crafting-update
[blz-aq]: https://news.blizzard.com/en-gb/world-of-warcraft/23504702/engineer-s-workshop-recreating-the-ahn-qiraj-war-effort
[celestalon]: https://us.forums.blizzard.com/en/wow/t/please-fix-spell-batching/437862/4
[claypool]: https://ftp.cs.wpi.edu/pub/techreports/pdf/06-13.pdf
[molnar]: https://regi.hiradastechnika.hu/data/upload/file/2008/2008_1/HT_0801a-8.pdf
[drakes1]: https://www.eveonline.com/article/fixing-lag-drakes-of-destiny-part-1-1
[eve-tidi]: https://www.eveonline.com/news/view/introducing-time-dilation-tidi
[br5rb]: https://www.eveonline.com/news/view/the-bloodbath-of-b-r5rb
