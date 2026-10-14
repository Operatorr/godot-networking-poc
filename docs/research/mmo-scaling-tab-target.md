# How tab-target and non-twitch MMOs put hundreds on screen

> Research note for wayfinder ticket **#25** (map **#23**: the load-testing / "why realtime games cap
> at ~64" article). Researched 2026-10-13.
>
> **Question.** How do WoW, EVE Online, Guild Wars 2 WvW and Albion Online put hundreds or
> thousands of players in one place, and what do they give up that a realtime shooter like Omega
> Realm can't?
>
> **Sourcing rule.** First-party sources (Blizzard, CCP, ArenaNet, Sandbox Interactive dev posts,
> patch notes, open-source code) or peer-reviewed measurement come first. Anything else is labelled
> **[secondary]** or **[community]**. Where a number could not be confirmed from a primary source,
> the note says so and gives the best-sourced figure it could find. No numbers are invented.
>
> **Vocabulary.** Omega terms (Tick, Snapshot, AoI, Lag compensation, Instance) are used as in
> `docs/CONTEXT.md`. **Watch out:** WoW's "shard" (a copy of one zone) is *not* an Omega **Shard**
> (a server node hosting Instances). In this note, "WoW shard" always means Blizzard's zone copy.

---

## TL;DR

1. **They don't beat the O(N²) fan-out. They pay it less often, per entity.** Blizzard says this
   about the 2020 AQ gate rebuild: every action by each of N players goes to the other N-1, so
   1,500 players doing one action means **2,248,500 packets**, and *"we can't solve it by throwing
   faster hardware at it."* What they do is choose *"which data should be communicated to players
   and how often"* ([Blizzard, 2020](#src-blz-aq)).
2. **Their combat models have a latency budget of hundreds of milliseconds to seconds, so the
   server can be late.** WoW abilities run on a 1.5 s global cooldown, target by unit ID (there's
   no aim to get wrong), and until 2014 the server resolved unit-on-unit actions in **400 ms
   batches** that players accepted for a decade ([Celestalon, 2014](#src-celestalon)). EVE's
   simulation Ticks at **1 Hz** ([CCP Masterplan, 2010](#src-drakes1)). Peer-reviewed tests put
   the tolerance threshold at about **500 ms** for third-person RPGs and about **1000 ms** for
   omnipresent games, against about **100 ms** for first-person shooters
   ([Claypool & Claypool, 2006](#src-claypool)).
3. **None of these games needs Lag compensation.** A heal or a target-locked missile is resolved
   against a unit ID on the server, not against a ray through a position the shooter saw 80 ms ago.
   No rewind buffer is needed and no hit is disputed, so most of a shooter's per-Tick hit cost
   disappears.
4. **Movement updates are event-driven and sparse, not streamed every Tick.** Packet traces from
   2007 show WoW clients sending over **TCP** with packet inter-arrival peaks at about **200 ms and
   300 ms** ([Molnár & Szabó, 2008](#src-molnar)). Under extreme load Blizzard goes further: it
   drops facing updates and sends player movement *"only whenever a player starts, stops, or uses
   keyboard movement"* ([Blizzard, 2020](#src-blz-aq)). **Blizzard has never published "WoW sends
   movement at X Hz."**
5. **They degrade on purpose.** EVE slows game time to as little as **10 %** (TiDi). WoW splits
   crowds into layers and WoW shards, caps zones, and queues (Wintergrasp **120 per faction**,
   Classic Silithus **~1,500**). GW2 used to cull distant characters and now caps maps. Albion
   queues players per zone with a proportional cluster queue. A twitch shooter can't use any of
   these without becoming a different game.
6. **They still break.** The AQ gate opening in 2006 caused a 12-hour login/disconnect loop.
   Wintergrasp crashed realms in 2009. EVE's B-R5RB (2014) ran 21 hours of real time to compute
   about 2 hours of game time. Albion's single-threaded zones freeze in big ZvZ fights. GW2 WvW has
   chronic "skill lag".

---

## 1. Genre comparison: the latency-tolerance budget

"Latency-tolerance budget" here means **how late the authoritative result can arrive before the
outcome or the feel of combat breaks.** The bigger the budget, the more the server can batch,
throttle, slow down or drop low-priority state.

| Genre / game | Combat model | Server cadence (best source) | Latency the model tolerates | Lag compensation? | Scaling mechanisms | Documented peak in one place |
|---|---|---|---|---|---|---|
| **Twitch shooter** (Omega Realm, CS, Valorant) | Aimed projectiles and hitscan; dodging is the skill | Omega: 30 Hz Tick (`docs/server/design.md`) | **~100 ms** threshold for first-person/precision play ([Claypool](#src-claypool)) | **Yes**, needed so aimed shots register | AoI, delta Snapshots, bit-packing; hard player cap per Instance | Usually 64–128 per server (covered by other #23 tickets) |
| **Tab-target MMO**: WoW | Target by unit ID; 1.5 s GCD (0.75 s haste floor); cast bars; server-side resolution | Unpublished. Historic **400 ms** batch for unit-on-unit actions, now "1–10 ms" ([Celestalon](#src-celestalon)). Client packets peak at ~200/300 ms IAT over TCP ([Molnár & Szabó](#src-molnar)) | **~500 ms** threshold for third-person RPG ([Claypool](#src-claypool)); 400 ms batching was live 2004–2014 | **No**: unit-targeted; client is effectively authoritative over its own movement ([TrinityCore, community](#src-tc-move)) | Layering, WoW sharding, cross-realm zones, zone caps and queues, throttled low-priority data, dropped facing updates, separate Home/World servers | Classic Silithus "**around 1,500** … stacked on top of each other" ([Blizzard](#src-blz-aq)); Wintergrasp capped at **240** ([3.2.0 notes](#src-320)) |
| **Spaceship MMO**: EVE Online | Lock target, activate modules on cycles; positioning by commands ("orbit", "approach") | **1 Tick/s** per ballpark ([CCP Masterplan](#src-drakes1)) | ~**1 s** granularity built in; CCP's TiDi goal was module response **< 1 s** ([CCP Veritas 2012](#src-tidi-2012)). Closest Claypool class: omnipresent, **~1000 ms** | **No**: lock-based | **Time Dilation** (to 10 %), node reinforcement on request, one system per node | **6,739** in M2-XFE (Jan 2021); **6,557** FWST-8 Guinness record (Oct 2020) ([CCP](#src-m2xfe-2), [CCP](#src-fwst)) |
| **Action-hybrid MMO**: GW2 WvW | Tab-target plus dodge rolls and ground-target AoE; AoE capped at **5 targets** ([GW2 wiki, community](#src-gw2-aoe)) | Unpublished | Between WoW and a shooter: dodge timing matters, so "skill lag" is felt | No public statement; none known | Culling (removed from WvW in 2013) → client-side model limits; per-map population caps | Map caps never officially published |
| **Click-to-move sandbox**: Albion Online | Click-to-move, targeted and ground skills, server-authoritative with client prediction ([Unity/Sandbox, 2026](#src-albion-unity)) | Unpublished; **one CPU thread per zone ("cluster")** for core logic ([Sandbox dev post, via search index](#src-albion-zvz)) | RPG-class (~500 ms); freezes appear when the per-zone spell queue backs up | No public statement; none known | Hard per-zone caps, proportional **cluster queue** by alliance ([Korn, 2021](#src-korn)), spell and VFX optimisation | "Hundreds of players" ([Unity/Sandbox](#src-albion-unity)); cap is "hard tech", number unpublished |
| **Turn-based / async** (Civ IV PitBoss, correspondence chess) | Discrete turns; server stores state between turns | Event-driven: one request per move | **Seconds to days.** Civ IV PitBoss used a **24 h** turn timer ([Johnson, 2009](#src-johnson)); Lichess correspondence offers **1–14 days per move** ([lila source](#src-lila)) | Not applicable | Stateless request/response, horizontal scaling, push notifications | Effectively unbounded per *game*; limited by storage, not Tick budget |

**Reading the table.** Moving down the rows, the budget grows by about an order of magnitude at
each step: ~100 ms, then ~500 ms, then ~1 s, then hours or days. Every mechanism in the "scaling"
column spends that budget: batching, throttling, dilating time, queuing, splitting crowds.

---

## 2. World of Warcraft (Blizzard)

### 2.1 Combat model and latency budget

- **Global cooldown.** *"Most abilities have 1.5 seconds"*, with a 1.0 s GCD for rogues, Cat Form
  druids and monks. Haste can bring the 1.5 s GCD down to 0.75 s (1.0 s before Legion)
  ([Warcraft Wiki, community](#src-gcd)). Nobody can act more than about once per 0.75–1.5 s, which
  caps the per-player action rate the server must resolve and fan out.
- **Server-side batching was the live behaviour for ten years.** Celestalon (Blizzard), June 2014:
  > "Any action that one unit takes on another different unit used to be processed in batches
  > every 400ms." … "healing another unit would incur a delay of between 0ms and 400ms (again, on
  > top of client/server latency)." … "We no longer batch them up like that. We just do it as fast
  > as we can, which usually amounts to between 1ms and 10ms later."
  > ([Celestalon, quoted on the Blizzard forums](#src-celestalon))

  For WoW Classic, Blizzard *reintroduced* the slow cadence on purpose. Kaivax, 28 March 2019:
  > "While we never really eliminated spell batching in WoW" … "For WoW Classic, we're moving spell
  > casts to a low-priority loop" ([Kaivax, Blizzard forums](#src-kaivax-batch))

  **Takeaway for the article:** a mass-market MMO ran up to 400 ms of *deliberate* server-side
  delay on top of network latency, and players treated the side effects (mutual Polymorphs, "the
  heal landed but I died") as quirks, not bugs. A shooter that added 400 ms on top of RTT would be
  unplayable.
- **Client-side spell queue (best-sourced figure, not confirmed by Blizzard).** The `SpellQueueWindow`
  CVar, which lets you press the next ability before the current cast/GCD ends, is widely documented
  as defaulting to **400 ms**. No Blizzard blue post confirming that default was found
  ([community: Maxroll, Blizzard forums](#src-sqw)). The design intent is clear: the client hides
  RTT by sending the next action early.
- **No Lag compensation.** Abilities target a unit ID and the server checks range, line of sight
  and resources. There's no aim to rewind. Blizzard has not published a WoW hit-validation design.
  TrinityCore's reverse-engineering notes that clients *"seem to run the entire physic simulation
  for the character that they own … This makes the client authoritative about the player's
  movement"* ([TrinityCore wiki, community](#src-tc-move)). This is emulator inference, not a
  Blizzard statement.
- **Peer-reviewed tolerance data.** Claypool & Claypool classify third-person avatar games
  ("Sports, RPG") as **medium** sensitivity with a **500 ms** threshold. In the EverQuest 2 field
  study they cite, going from 0 to 500 ms of added latency added *"only an additional 5 seconds to
  about 2 minutes of combat"* ([Claypool & Claypool, 2006](#src-claypool)).

### 2.2 How often WoW sends movement

**Not confirmed by any Blizzard primary source.** This is the best evidence available:

| Evidence | What it says | Strength |
|---|---|---|
| Molnár & Szabó, *Híradástechnika* 2008 (Wireshark traces, Jan 2007) | WoW runs over **TCP**. Client packet inter-arrival PDFs from all four MMOs studied peak at **~200 ms**, and WoW and Guild Wars also peak at **~300 ms**. The authors note MMOGs are *"designed to run smoothly even with 1250 msec latency"*, and that at 200 ms *"even a retransmission fits into this interval"* ([src](#src-molnar)). The 1250 ms figure is the authors' claim, not a measurement | **Peer-reviewed measurement**, but of whole client traffic, not movement only |
| TrinityCore wiki, "Movement" (2019) | *"The client only sends a packet on player's direction or speed change (or on heatbeat)."* Interval not given. Server anti-jitter buffer *"assumed to be 500ms. However, no definite proof"* ([src](#src-tc-move)) | **[community]** reverse-engineering |
| Bot-developer forum reports | Heartbeat "every 500 ms or so" while moving | **[community]**, anecdotal. Not used as a figure |
| Blizzard, AQ rebuild (2020) | Under load: *"dropping facing updates … and only send out player updates whenever a player starts, stops, or uses keyboard movement"* ([src](#src-blz-aq)) | **Primary**, but describes the *throttled* mode |

**Best-sourced statement:** WoW movement is **event-driven** (start, stop, turn or speed change)
plus a periodic heartbeat, carried over TCP. Measured client traffic clusters at roughly 3–5
packets/s (200–300 ms inter-arrival), compared with Omega's 30 Hz Tick. **[MEASURE-style caveat:
this is derived from inter-arrival peaks, not a per-message movement rate.]**

### 2.3 Scaling mechanisms

- **Event-driven, prioritised replication.** The AQ engineering post is the key primary source:
  > "What we faced is a polynomial problem, which means we can't solve it by throwing faster
  > hardware at it because hardware's not exponentially better. Instead, we have to handcraft the
  > optimization by deliberately choosing which data should be communicated to players and how
  > often." … "In this group of 20, the server processes 380 packets (20 total players * 19
  > recipients = 380 packets)." … "1,500 players then 2,248,500 packets"
  >
  > "Since latency with an excessive amount of players is already compromised, spending CPU time
  > sending minor facing updates made the fidelity worse." … "it's better to miss some movement
  > updates than to not be able to login to your character at all." … "optimized the code to only
  > send you less important information in batches and less frequently." … "we now batch the buffs
  > and debuffs to avoid sending multiple packets in succession to players."
  > ([Blizzard, "Engineer's Workshop: Recreating the Ahn'Qiraj War Effort", 2020-08-20](#src-blz-aq))

  Check: 20×19 = 380, 500×499 = 249,500, 1,500×1,499 = 2,248,500. This is the same N(N-1) fan-out
  Omega faces.
- **WoW sharding (retail).** *"making a copy of a zone (e.g. Zuldazar) once the player count
  reaches a certain threshold … player interactions are among the most CPU intensive due to the
  amount of packets that they constantly send to the server for pinpoint accuracy on their
  movements and spells casts."* ([Blizzard 2020](#src-blz-aq))
- **Layering (Classic).** *"layers—copies of entire regions (e.g. Eastern Kingdoms)"*
  ([Blizzard 2020](#src-blz-aq)). Brian Birmingham (Lead Software Engineer), Aug 2019: *"everybody
  will be clustered in the starting zones, and having players so close together causes an
  exponential drain on server resources"*, and *"every layer is a copy of the entire world"*
  ([Blizzard forums relay of r/classicwow AMA](#src-birmingham)). Layers were cut back as players
  spread out: *"This allowed them to accommodate more players per layer"*
  ([Kaivax, Oct 2019, via wowisclassic.com](#src-layer-update)).
- **Cross-realm zones (MoP, patch 5.0.4, 2012-08-28).** These pool under-populated zones across
  realms and can also split overcrowded ones ([Warcraft Wiki](#src-crz), [Engadget, secondary](#src-crz-eng)).
- **Hard zone caps and queues.** Wintergrasp in patch 3.2.0 (2009-08-04): *"The queue will accept
  up to 120 players from each faction, resulting in a maximum battle of 240 players at a time."*
  ([patch notes](#src-320)). Classic AQ: level-60-only access to Silithus and a cap of *"around
  1,500 players if they were stacked on top of each other"* ([Blizzard 2020](#src-blz-aq)).
- **Split servers.** Since patch 4.0.6 the client shows separate **Home** latency (chat, auction
  house, guild) and **World** latency (combat, nearby units, casting). These run on different
  server connections, so crowded zones don't lag social traffic ([Warcraft Wiki](#src-latency)).
- **Bots for capacity tests.** Blizzard load-tested AQ with *"headless clients—automated
  players—"* that cast spells, fought NPCs and moved around, then compared the results with
  volunteer stress tests. *"Server frame time measurements were heavily scrutinized to see how
  close they were to causing a server to become unresponsive, also known as deadlocking."*
  ([Blizzard 2020](#src-blz-aq)). This maps directly onto Omega's `omega-load-test` swarm.

### 2.4 Documented breakdowns

- **AQ gate opening, 2006 (patch 1.9).** Blizzard's own account: *"The turnout was beyond the
  development team's wildest imaginings and, simply put, we were not prepared. Servers quickly
  become overloaded, and many players were caught in a loop of logging in, disconnecting, and trying
  to get back online over a 12-hour period"* ([Blizzard 2020](#src-blz-aq)). Community accounts say
  the Medivh-US world server crashed the moment the gong was rung **[community]**
  ([Warcraft Wiki: Medivh US](#src-medivh)).
- **AQ rebuild, 2020.** The first stress test crashed at *"nearly at 150% the capacity of an entire
  1.12 realm"*, because zone-transfer code *"was a queue that didn't process many players at
  once"*. After the fixes, a few realms crashed at the live event but recovered *"within minutes"*
  ([Blizzard 2020](#src-blz-aq)).
- **Wintergrasp, 2009.** In patch 3.0.8 the zone changing hands crashed realms, and Blizzard
  temporarily disabled the battle on all realms ([Engadget, secondary](#src-wg-308)). After 3.1,
  Blizzard's Zarhym called the lag *"simply population based"* and at first rejected caps: putting a
  limit on the number of people *"is not the way to go"* (paraphrased by
  [Engadget, secondary](#src-wg-31)). Three months later, 3.2.0 shipped the **120-per-faction queue**
  ([patch notes](#src-320)). The original non-instanced design lost to the fan-out.
- **Capital-city crowding (Ironforge/Orgrimmar).** **No primary Blizzard post specifically about
  Ironforge or Orgrimmar lag was found.** The closest first-party statement is Birmingham's point
  that clustering *"causes an exponential drain on server resources"* ([src](#src-birmingham)),
  and the Home/World split exists partly because crowded areas inflate World latency
  ([Warcraft Wiki](#src-gns)). Treat specific "Ironforge lag" anecdotes as folklore unless sourced.

---

## 3. EVE Online (CCP Games)

### 3.1 Combat model and latency budget

- **1 Hz simulation.** CCP Masterplan, 2010-12-10: *"Each ballpark runs at a rate of one tick per
  second."* Each Tick has a pre-tick step (apply client actions and server events), an evolve step
  (physics) and a post-tick step (build and send client updates, handle new clients). *"The
  majority of the time is spent in the Pre-tick step"*, and *"less than 10% of the overall time in
  Destiny is spent in Evolve."* ([Drakes of Destiny pt 1](#src-drakes1))
- **Physics runs on both client and server.** *"It runs both on the server and on each client"*
  ([CCP GingerDude, "Facing Destiny", 2009](#src-facing)). The client extrapolates between 1 Hz
  Ticks, and commands are high-level intents ("orbit at 10 km"), not stick inputs.
- **Combat is lock-and-activate.** Weapons are target-locked modules with cycle times, so hits are
  computed server-side against the locked target. No Lag compensation is needed.
- **What load actually is.** CCP Veritas, 2011: physics *"only accounts for 5-10% of the load"*,
  and *"A large majority of the load in large engagements is tied to the clock."* The scheduler
  runs one tasklet at a time: *"only one tasklet can be running at any given time."*
  ([Introducing TiDi](#src-tidi-2011)). In the 2010 Drake mass-test (200 Drakes with missile
  launchers plus 100 other thin clients), the cost was **missiles being added to and removed from
  every observer's view**, an AoI problem. Fixing an O(n·m) per-observer list build removed a
  function that had taken *"over 15% of the entire CPU load"* ([Drakes pt 2](#src-drakes2)).

### 3.2 Time Dilation (TiDi)

- **Mechanism.** *"slow down the game clock enough to maintain a very small queue of waiting
  tasklets"*. It was planned with *"a hard limit on how far we're willing to dilate"*
  ([CCP Veritas, 2011-04-22](#src-tidi-2011)). The floor is **10 %**. B-R5RB: *"it hit our limit
  of running the simulation at 10% of normal time"* ([CCP, 2014](#src-br5rb)).
- **It's per node, not per system.** *"it's a node-level thing, which causes solar systems
  potentially far away from the fight to be effected."* The goal: *"the module response time was
  kept under one second for the vast majority of the action"*, against earlier delays of
  *"20, 40, 600 seconds."* It was live by default from January 2012
  ([CCP Veritas, 2012-02-10](#src-tidi-2012)).
- **Why it fits EVE and not a shooter.** TiDi trades *wall-clock time* for *simulation
  correctness*. Everyone in the system slows down together, so relative timing stays fair. A
  shooter where your crosshair moves at 10 % speed is not a shooter.

### 3.3 Node reinforcement

- One solar system can be moved onto a reserve node at downtime when players file a Fleet Fight
  Notification: *"we keep a few nodes in reserve for occasions when large player engagements
  occur."* CCP is explicit: *"there is no way for us to guarantee flawless performance during large
  fleet fights."* ([CCP Convict, 2020-07-10](#src-ffn))
- Early record (pre-TiDi): about **3,242** players in one fully reinforced system, *"without the
  node crashing"* but *"not an ideal gameplay experience"* ([CCP Veritas, 2010](#src-few)).

### 3.4 Record battles (all first-party figures)

| Battle | Date | Peak in system | Notes | Source |
|---|---|---|---|---|
| Unnamed 3k fight | 2010-10-30 | ~3,242 | single reinforced node, pre-TiDi | [CCP Veritas](#src-few) |
| **B-R5RB** | 2014-01-27/28 | **2,670** max in system; 6,058 took part in system; 7,548 across the battle | ~21 h real time at 10 % TiDi → *"just over 2 hours worth of simulation"*; 75 Titans; 11 T ISK ≈ US$300–330k | [CCP Dolan](#src-br5rb) |
| **FWST-8** | 2020-10-06/07 | **6,557** concurrent (Guinness) | 8,825 total participants (Guinness), 14+ h | [CCP](#src-fwst) |
| M2-XFE (first) | 2020-12-30/31 | >5,000 participants | Guinness: most costly battle (US$378,012), 257 Titans lost | [CCP / Guinness PR](#src-m2xfe-1) |
| **M2-XFE (second timer)** | 2021-01-02 | **6,739** in M2-XFE | 13,770 combined across three reinforced systems (~35 % of all online pilots). *"Neither side of the war, or CCP, can, could or will be able to predict the server performance in these kinds of situations."* | [CCP](#src-m2xfe-2) |

Check: B-R5RB at 10 % TiDi for ~21 h of wall clock gives ≈ 2.1 h of simulation, consistent with
CCP's "just over 2 hours".

**Tranquility hardware.** CCP's "Tranquility Tech III" series (2015–16) covers the cluster rebuild
([CCP Gun Show](#src-tq3)), but no CCP post found gives per-node specs tied to a specific record
battle, so this note doesn't cite hardware numbers.

---

## 4. Guild Wars 2 WvW (ArenaNet)

- **Culling (2012 to 2013).** Habib Loew (ArenaNet), *"World vs. World: The End of Culling"*,
  2013-03-13: normally every character in a fairly large radius is reported to the client. Culling
  capped that count so only the *closest* characters were reported, to cut network resources and
  client requirements. The side effect was invisible enemies in big fights and stealth lasting up
  to two seconds past its end ([ArenaNet](#src-gw2-culling)).
- **Replacement (2013-03-26).** The server now reports all nearby characters. The client decides
  how many to draw as full models, low-res fallback models or nameplates only, via *WvW Character
  Limit* and *WvW Character Quality* ([ArenaNet](#src-gw2-culling), [GW2 Wiki](#src-gw2-wiki-culling)).
  This moved the cost from server/network AoI to the client renderer.
- **Design caps that also bound compute.** AoE skills hit *"a maximum of 5 targets, determined by
  proximity"* ([GW2 Wiki, community](#src-gw2-aoe)). ArenaNet gives no performance reason, so
  treat it as a balance rule that happens to bound per-cast work.
- **Skill lag and map caps.** ArenaNet acknowledged WvW was suffering from skill lag and **tested
  reduced map populations** as a short-term fix. It also warned that *"any reduction to player
  counts will have a negative impact on the overall gameplay experience"*
  (**[secondary]**, [Massively OP](#src-gw2-mop); the forum original sits behind a bot wall and
  could not be fetched). Later (2020) staff forum posts reported server-side lag improvements;
  also **[secondary via search index]**. **ArenaNet has never published official WvW map caps**,
  and none are given here.
- **Latency budget.** GW2 sits between WoW and a shooter: dodge rolls and ground-target AoE make
  timing matter, which is why "skill lag" (delayed activations under load) is the community's main
  complaint, not rubber-banding.

---

## 5. Albion Online (Sandbox Interactive)

- **Architecture.** The core simulation is independent of Unity: *"Our core simulation layer is
  completely independent of Unity"* (David Eibensteiner, principal game engineer). The client is
  split into input, simulation and visualisation layers, with client-side prediction against an
  authoritative server. Large battles are tested locally with in-house bots
  ([Unity case study, 2026-05-12](#src-albion-unity)).
- **One thread per zone.** Sandbox's developer post *"How Albion Online Tackles ZvZ Performance"*
  says each **cluster** (zone) runs its core logic on a **single CPU thread** that processes a queue
  of in-zone actions (spells, movement). Database, I/O and pathfinding are already off-thread. The
  team keeps the single thread on purpose for simulation consistency and to avoid race conditions.
  The post gives a non-linear example: an AoE that hits 5 targets may cost about 10 interaction
  checks, but one that hits 50 can cost over a thousand per cast
  (**[primary, but read via search index only]**: the page sits behind a Cloudflare challenge,
  so this is paraphrased and not quoted; [forum](#src-albion-zvz), [news](#src-albion-news)).
- **Hard per-zone caps and a proportional queue.** Korn (Sandbox), 2021: *"There are hard tech
  limits to how many players can fight in a single zone. These tech limits are not subject to
  hardware, meaning that no matter how many servers we use, they can't be exceeded."* The cluster
  queue exists *"to prevent zone capping"*. Slots are shared in proportion to each alliance's queued
  players, weighted by item power, and re-evaluated every 90 s. **The real cap isn't published.**
  Korn's worked example uses a *hypothetical* 500 ([Korn, devtrackers mirror](#src-korn)).
- **Latency budget.** Click-to-move with targeted skills sits in the RPG band (~500 ms). The
  failure mode under load is whole-zone **freezes** while the single thread works through the
  spell queue, not missed shots.

---

## 6. The far end: turn-based and asynchronous games

- **Budget: seconds to days.** Soren Johnson (Civ IV designer), *Game Developer*, 2009: with
  asynchronous play *"the time pressure of a standard turn-based game is eliminated"*. Civ IV's
  PitBoss let *"players could log-on at any time to execute their turns"*, with simultaneous moves
  and a **24-hour** turn timer, for games of up to 32 players ([Johnson](#src-johnson)).
  Lichess's correspondence mode offers `List(1, 2, 3, 5, 7, 10, 14)` **days per move**
  ([lila `Mappings.scala`](#src-lila)).
- **What that buys.** There's no Tick, no AoI streaming and no fan-out per Tick. The server is a
  request/response store with notifications, so "players in one place" is limited by storage and
  matchmaking, not by a frame-time deadline. This is the end of the spectrum where the latency
  budget no longer constrains scale at all.

---

## 7. What they give up that a realtime shooter can't

| Lever the MMO pulls | What it costs | Why Omega can't pull it |
|---|---|---|
| **Low, event-driven movement rate** (start/stop/heartbeat over TCP; drop facing under load) | Remote positions are coarse. Fine positioning doesn't matter because nothing aims at a position | Omega's projectiles hit *positions*. Coarse remote motion means shots miss what the shooter saw |
| **Server-side batching / slow resolution loop** (WoW 400 ms; Classic low-priority loop) | Odd simultaneous outcomes (mutual sheep, posthumous heals) | Bullet-hell dodging is decided within one or two Ticks. 400 ms is longer than a whole dodge |
| **Unit-ID targeting, no Lag compensation** | No skill expression in aim | Aim *is* the skill. Omega needs a rewind/backstop (D11), which costs history buffers and per-hit work |
| **Time Dilation** | Everyone slows down; a 21 h fight to compute 2 h of game time | Twitch feel collapses at any dilation. Input-to-response must stay at real time |
| **Culling / client-side model limits** | You may not see everyone | You can't dodge bullets from enemies you can't see |
| **Layering / WoW sharding / zone caps and queues** | "The world is full", you're in a copy, or you're queued | Usable, and Omega already caps per Instance. This lever does transfer to shooters |
| **Huge GCDs / cast bars** | Low APM; actions telegraphed | Omega's fire rate is the gameplay |

**One-line thesis for the article:** tab-target MMOs reach hundreds on screen not by beating the
N² fan-out (Blizzard says plainly they can't) but by having a combat model that tolerates
hundreds of milliseconds to seconds of lateness. That budget pays for low update rates,
batching, throttling, TCP, time dilation and queues. A twitch shooter's ~100 ms budget leaves
little room for any of them.

---

## Sources

Primary unless marked. All accessed 2026-10-13.

**Blizzard / World of Warcraft**
- <a id="src-blz-aq"></a>Blizzard Entertainment, "Engineer's Workshop: Recreating the Ahn'Qiraj War Effort", news.blizzard.com, `datePublished` 2020-08-20. https://news.blizzard.com/en-gb/world-of-warcraft/23504702/engineer-s-workshop-recreating-the-ahn-qiraj-war-effort
- <a id="src-celestalon"></a>Celestalon (Blizzard), 2014-06-18 (patch 5.4.7) post on 400 ms batching, quoted in Blizzard forums thread "Please fix spell batching". https://us.forums.blizzard.com/en/wow/t/please-fix-spell-batching/437862/4
- <a id="src-kaivax-batch"></a>Kaivax (Blizzard), "Spell Batching in Classic", Blizzard forums, 2019-03-28. https://us.forums.blizzard.com/en/wow/t/137118/1
- <a id="src-birmingham"></a>Brian Birmingham (Lead Software Engineer), r/classicwow AMA, relayed on Blizzard forums "Layering in Classic – Blizzard Responds on Reddit", 2019-08-20. https://us.forums.blizzard.com/en/wow/t/layering-in-classic-blizzard-responds-on-reddit/260714
- <a id="src-layer-update"></a>Kaivax, "Realm Layering Update" (blue post as reproduced by wowisclassic.com, 2019-10-04) **[secondary reproduction]**. https://www.wowisclassic.com/en/news/realm-layering-update/
- <a id="src-320"></a>Patch 3.2.0 notes (2009-08-04), as archived on Warcraft Wiki. https://warcraft.wiki.gg/wiki/Patch_3.2.0
- <a id="src-crz"></a>Warcraft Wiki, "Cross-realm zone" (patch 5.0.4, 2012-08-28) **[community]**. https://warcraft.wiki.gg/wiki/Cross-realm_zone
- <a id="src-crz-eng"></a>Engadget, "World of Warcraft unveils cross-realm zones", 2012-05-10 **[secondary]**. https://www.engadget.com/2012-05-10-world-of-warcraft-unveils-cross-realm-zones.html
- <a id="src-latency"></a>Warcraft Wiki, "Latency" (Home/World split, patch 4.0.6) **[community]**. https://warcraft.wiki.gg/wiki/Latency
- <a id="src-gns"></a>Warcraft Wiki, "API GetNetStats" **[community]**. https://warcraft.wiki.gg/wiki/API:GetNetStats
- <a id="src-gcd"></a>Warcraft Wiki, "Global cooldown" **[community]**. https://warcraft.wiki.gg/wiki/Global_cooldown
- <a id="src-sqw"></a>SpellQueueWindow default 400 ms: Maxroll guide and Blizzard forum threads **[community]**. https://maxroll.gg/wow/resources/spell-queue-window ; https://us.forums.blizzard.com/en/wow/t/input-lag-spellqueuewindow-and-spell-batching/1210379
- <a id="src-tc-move"></a>TrinityCore wiki, "Movement" (2019-01-20) **[community reverse-engineering]**. https://trinitycore.atlassian.net/wiki/spaces/tc/pages/721256449/Movement
- <a id="src-wg-308"></a>Engadget, "Patch 3.0.8 bug roundup", 2009-01-21 (quotes Bornakk on the zone-flip crash) **[secondary]**. https://www.engadget.com/2009-01-21-patch-3-0-8-bug-roundup.html ; Blizzplanet, "Wintergrasp fix and other patch 3.0.8 issues" (battle temporarily disabled on all realms) **[secondary]**. https://www.blizzplanet.com/blog/comments/wintergrasp_fix_and_other_patch_3_0_8_issues
- <a id="src-wg-31"></a>Engadget, "Wintergrasp lag a big issue after patch 3.1", 2009-05-06 **[secondary; paraphrases Zarhym]**. https://www.engadget.com/2009-05-06-wintergrasp-lag-a-big-issue-after-patch-3-1.html
- <a id="src-medivh"></a>Warcraft Wiki, "Server:Medivh US" **[community]**. https://warcraft.wiki.gg/wiki/Server:Medivh_US

**CCP Games / EVE Online**
- <a id="src-drakes1"></a>CCP Masterplan, "Fixing Lag: Drakes of Destiny (Part 1)", 2010-12-10. https://www.eveonline.com/article/fixing-lag-drakes-of-destiny-part-1-1
- <a id="src-drakes2"></a>CCP Masterplan, "Fixing Lag: Drakes of Destiny (Part 2)", 2010-12-11. https://www.eveonline.com/news/view/fixing-lag-drakes-of-destiny-part-2-1
- <a id="src-facing"></a>CCP GingerDude, "Facing Destiny", 2009-09-11. https://eveonline.com/article/facing-destiny
- <a id="src-tidi-2011"></a>CCP Veritas, "Introducing Time Dilation (TiDi)", 2011-04-22. https://www.eveonline.com/news/view/introducing-time-dilation-tidi
- <a id="src-tidi-2012"></a>CCP Veritas, "Time Dilation – How's That Going?", 2012-02-10. https://www.eveonline.com/news/view/time-dilation-hows-that-going
- <a id="src-few"></a>CCP Veritas, "Well, that was a few people", 2010-11-09. https://www.eveonline.com/article/well-that-was-a-few-people
- <a id="src-br5rb"></a>CCP Dolan, "The Bloodbath of B-R5RB, Gaming's Most Destructive Battle Ever", 2014-01-29. https://www.eveonline.com/news/view/the-bloodbath-of-b-r5rb
- <a id="src-fwst"></a>CCP, "Two Guinness World Records Titles Broken!" (Fury at FWST-8), 2020-10-29. https://eveonline.com/article/qivbsp
- <a id="src-m2xfe-1"></a>CCP press release, "The Most Expensive Video Game Battle Ever Earns Two GUINNESS WORLD RECORDS Titles", 2021-02-04. https://pressreleases.triplepointpr.com/2021/02/04/the-most-expensive-video-game-battle-ever-earns-two-guinness-world-records-titles-for-eve-online/
- <a id="src-m2xfe-2"></a>CCP, "The Second Timer in M2-XFE", 2021-01-05. https://www.eveonline.com/news/view/the-second-timer-in-m2-xfe
- <a id="src-ffn"></a>CCP Convict, "Fleet Fight Notification Tool", 2020-07-10. https://www.eveonline.com/news/view/fleet-fight-notification-tool
- <a id="src-tq3"></a>CCP Gun Show, "Tranquility Tech III – An Update", Dec 2015. https://www.eveonline.com/news/view/tranquility-tech-iii-an-update

**ArenaNet / Guild Wars 2**
- <a id="src-gw2-culling"></a>Habib Loew (ArenaNet), "World vs. World: The End of Culling", 2013-03-13. https://www.guildwars2.com/en/news/world-vs-worldthe-end-of-culling/
- <a id="src-gw2-wiki-culling"></a>Guild Wars 2 Wiki, "Culling" **[community]**. https://wiki.guildwars2.com/wiki/Culling
- <a id="src-gw2-aoe"></a>Guild Wars 2 Wiki, "Area of effect" **[community]**. https://wiki.guildwars2.com/wiki/Area_of_effect
- <a id="src-gw2-mop"></a>Massively OP, "Guild Wars 2 looks for short-term WvW performance improvements" **[secondary; page not fetchable, content via search index]**. https://massivelyop.com/?p=291272

**Sandbox Interactive / Albion Online**
- <a id="src-albion-unity"></a>Unity Technologies (F. Baird) with Sandbox engineers J. Kosanetzky and D. Eibensteiner, Albion architecture case study, 2026-05-12. https://unity.com/blog/albion-online-cross-platform-pvp-mmo-architecture
- <a id="src-albion-zvz"></a>Sandbox Interactive, "How Albion Online Tackles ZvZ Performance", Developers' Statements forum **[primary; Cloudflare-blocked, read via search index]**. https://forum.albiononline.com/index.php/Thread/218858-How-Albion-Online-Tackles-ZvZ-Performance/
- <a id="src-albion-news"></a>Albion Online news, "ZvZ performance" **[primary; Cloudflare-blocked, read via search index]**. https://albiononline.com/news/zvz-performance
- <a id="src-korn"></a>Korn (Sandbox Interactive), "Cluster Queue" (2021), mirrored on devtrackers.gg. https://devtrackers.gg/albion/p/af3dbae9-cluster-queue

**Measurement / academic**
- <a id="src-claypool"></a>M. Claypool & K. Claypool, "Latency and Player Actions in Online Games", *Communications of the ACM* 49(11):40–45, Nov 2006 (WPI tech report WPI-CS-TR-06-13). https://ftp.cs.wpi.edu/pub/techreports/pdf/06-13.pdf
- <a id="src-molnar"></a>S. Molnár & G. Szabó, "On the scaling characteristics of MMORPG traffic", *Híradástechnika* LXIII (2008/1) (traces captured Jan 2007). https://regi.hiradastechnika.hu/data/upload/file/2008/2008_1/HT_0801a-8.pdf

**Turn-based / async**
- <a id="src-johnson"></a>Soren Johnson, "Analysis: Asynchronicity In Game Design", *Game Developer*, March 2009 (web 2009-07-07). https://www.gamedeveloper.com/pc/analysis-asynchronicity-in-game-design
- <a id="src-lila"></a>lichess-org/lila, `modules/setup/src/main/Mappings.scala`: `daysChoices = Days.from(List(1, 2, 3, 5, 7, 10, 14))`. https://github.com/lichess-org/lila/blob/master/modules/setup/src/main/Mappings.scala

---

## Open gaps (not resolvable from primary sources in this pass)

- **WoW movement Hz.** Blizzard has never published it. The best figure is measured client traffic
  inter-arrival (~200/300 ms, TCP, 2007). A fresh packet capture of retail and Classic would settle
  it. **[MEASURE]** candidate if the article needs a hard number.
- **GW2 WvW map caps, and Albion's per-zone cap number.** Both studios call them technical limits
  but don't publish values.
- **Tranquility per-node hardware at record battles.** Not published alongside battle reports.
- **WoW Classic final batch window.** The 1.13.7 PTR tested 400 → 10 ms per secondary reports. The
  live outcome was not confirmed from a Blizzard source.
