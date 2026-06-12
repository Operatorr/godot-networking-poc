# Rust Game Server Port — Migration Spec

**Status:** Draft (in active grilling) · **Started:** 2026-06-11

> Porting the **game server only** from Godot 4.6 headless to **Rust**. The **Godot client stays**
> (rewritten only as far as the new transport/protocol force) and the **Go API stays** (auth,
> accounts, characters, leaderboard, persistence). This spec is the system of record for the port;
> it is being written incrementally as each decision is grilled and resolved.
>
> Reads against: [`../ARCHITECTURE.md`](../ARCHITECTURE.md), [`../netcode/overview.md`](../netcode/overview.md),
> [`../CONTEXT.md`](../CONTEXT.md), and the ADRs (esp. [`../adr/0003-enet-udp-transport.md`](../adr/0003-enet-udp-transport.md)).

## Target topology (unchanged from today's intent)

```
Godot Client ──login/account/characters/purchases──▶ Go API ◀──▶ Postgres
     │                                                  ▲
     │  session token / match ticket                    │ validate token, load/save character
     ▼                                                   │
Godot Client ──realtime game traffic (UDP)──▶ Rust Game Server ──┘
```

- **Go API** — accounts, login, JWT/session tokens, character metadata, inventory persistence,
  matchmaking coordination, admin, billing, launcher APIs, DB access. *Unchanged by this port.*
- **Rust Game Server** — inputs, movement, combat, visibility/AoI, replication, snapshots, lag
  compensation, anti-cheat validation, the tick loop, packet prioritization, world simulation.
- **Godot Client** — rendering, prediction, interpolation, input, UI, talks to both Go API and
  the Rust server.

---

## Decision log

Each entry: the decision, the alternatives weighed, and the consequence it forces downstream.

### D1 — Cutover strategy: clean-slate rewrite with new transport from day one

**Decision.** Build the Rust server directly on its target transport (UDP-based; see D2) with a
purpose-built protocol. Update the Godot client in lockstep. Retire the Godot server at cutover —
**no protocol-compatible WebSocket intermediate, no side-by-side run.**

**Alternatives weighed.**
- *Drop-in, protocol-identical-first (WebSocket):* Rust speaks today's exact binary protocol over
  WebSocket so the unchanged client connects; Godot server stays up as an A/B **parity oracle**.
  Rejected — keeps a throwaway WebSocket layer and delays the target architecture.
- *New transport, same packet semantics:* UDP immediately but reuse existing packet byte-layouts.
  Rejected — couples the transport swap to the port without buying the parity oracle.

**Consequences this forces (tracked as open risks).**
1. **No parity oracle.** There is no running Godot server to diff Rust snapshots against. Behavioral
   equivalence must be proven another way → see open question **[Validation]**.
2. **Reimplemented sim must match the client.** Prediction reconciliation requires the Rust server's
   movement/collision math to agree with the GDScript client's *predicted* math (today they share
   GDScript: `game_constants.gd`, `movement_state_machine.gd`, `move_with_obstacle_collision`).
   Divergence = constant misprediction snaps. → see open question **[Shared-sim parity]**.
3. **Bigger-bang cutover.** Client, server, and transport all change together; there is no
   intermediate state where only one moving part is new.

### D2 — Transport: ENet protocol, wire-compatible both sides

**Decision.** UDP via the **ENet protocol**. The Godot client uses its **native** low-level ENet API
(`ENetConnection` + `ENetPacketPeer`) to send raw binary on channels; the Rust server uses a
**wire-compatible pure-Rust ENet implementation** (candidate: `rusty_enet`). Honors
[ADR 0003](../adr/0003-enet-udp-transport.md). Final crate choice is a sub-decision under **[Rust stack]**.

**Alternatives weighed.**
- *Raw UDP + custom reliability (renet/laminar/hand-rolled):* full control, mainstream pure-Rust
  crates — but the Godot client must reimplement acks/sequencing/fragmentation over `PacketPeerUDP`,
  the largest client-side lift and the easiest place to introduce desync. Rejected.
- *QUIC (quinn):* per-stream reliability avoids head-of-line blocking, TLS + modern congestion
  control built in — but **Godot has no native QUIC**, forcing a client GDExtension. Overkill for a
  same-region POC. Rejected (revisit only if HOL-within-ENet-reliable-channel becomes a measured
  problem).

**Channel plan (per-message reliability — the whole point of leaving TCP).**

| Channel | ENet mode | Carries | Why |
|---|---|---|---|
| 0 | unreliable **sequenced** | `STATE_UPDATE` snapshots | newest wins; a dropped snapshot is superseded, never retransmitted or blocking |
| 1 | **reliable** ordered | `GAME_EVENT` (damage/kill/respawn/PLAYER_INFO), `CONNECT_AUTH`, `DISCONNECT`, `BASELINE_ACK`, `REQUEST_FULL_STATE`, `RESPAWN_REQUEST` | discrete one-shots that must arrive exactly once, in order |
| 2 | unreliable sequenced | `PLAYER_INPUT` | client replays unacked inputs anyway, so loss self-heals; latest input matters most |

`ACTION_CONFIRM` rides channel 0 or its own unreliable-sequenced channel — a newer confirm supersedes
a lost one, so reliability is wasteful.

**Protocol simplifications ENet subsumes (delete from the port):**
- **`HEARTBEAT` (4):** ENet provides keepalive, ping, RTT, and timeout natively. The *clock-sync*
  payload (`server_ms`) that interpolation needs survives — relocated, not deleted.
- **`BATCH` (11):** ENet does its own fragmentation/coalescing; the TCP-framing-overhead wrapper
  (TASK-066) is no longer needed.

**Risks to watch.** ENet reliable-ordered channels can still head-of-line block *within that channel*
(mitigated by keeping snapshots on the unreliable channel); pure-Rust ENet crates are less mainstream
than tokio/quinn (pin the version, golden-test the handshake against Godot early).

### D3 — Wire protocol: redesign via a single schema, codegen both sides

**Decision.** Don't carry the hand-tuned-but-hand-written protocol forward. Define the wire format
**once in a schema** and **generate both** the Rust codec and the GDScript codec from it. Use the
clean-slate opening to bitpack tighter (sub-byte flags, varints, quantization and delta-mask layout
declared in the schema). Toolchain is a sub-decision → **[Codec toolchain]**, D4.

**Alternatives weighed.**
- *Preserve current semantics, adapt to ENet:* smallest client rewrite, bandwidth profile already
  proven — but keeps two hand-written codecs (now in *different languages*), exactly the drift risk
  D1 introduced. Rejected.
- *Simple format v1, optimize later:* fastest to first-playable but blows the <2 KB/s/player budget
  and re-does the protocol twice; can't load-test at scale until v2. Rejected.

**What this buys / costs.**
- ✅ **Single source of truth for the wire format** — serialization drift between client and server
  becomes impossible by construction (the codecs are generated from one file).
- ✅ Headroom to beat the current bandwidth via real bitpacking.
- ⚠️ **Does NOT solve sim-math parity** (movement/collision determinism) — that stays open under
  [Shared-sim parity].
- ⚠️ Every bandwidth budget in `performance-budgets.md` must be **re-measured**; old numbers are
  invalidated by the new layout.
- ⚠️ A codegen toolchain becomes a build dependency for both the Rust server and the Godot client.

**Carried forward from the old protocol (semantics, not bytes):** entity-type tags, 0.1-unit position
quantization (or tighter), delta encoding against a periodic full-state **baseline**, baseline acks,
and the AoI per-peer byte-budget scheduler. **Dropped:** `HEARTBEAT`, `BATCH` (ENet subsumes — see D2).

> **ADR candidate:** "Schema-driven wire protocol with codegen for client + server." Draft once D4
> pins the toolchain (it's hard to reverse, non-obvious, and a real trade-off vs. hand-written codecs).

### D4 — Codec toolchain: custom IDL + own generator

**Decision.** A **custom schema** (small DSL/`.toml`-style file) describes every packet, its fields,
quantization, and delta-mask layout. A **generator written in Rust** emits two artifacts: the server's
Rust codec module and the client's GDScript codec script. No runtime serialization dependency on
either side; full control over sub-byte bitpacking and quantization.

**Alternatives weighed.**
- *Off-the-shelf IDL (Protobuf / FlatBuffers / Cap'n Proto):* mature tooling and free versioning, but
  **GDScript codegen is weak or absent** and none sub-byte bitpack — we'd fight the tool to hit the
  bandwidth budget. Rejected.
- *Rust-authoritative + hand-written GDScript mirror (bitcode/postcard):* no generator to build, but
  reintroduces a hand-written GDScript codec — the drift risk D3 set out to kill. Rejected.

**Conventions (defaults, not separately grilled — reversible/standard):**
- Schema + generator live in a top-level **`protocol/`** cargo workspace member (`protogen` binary).
- Generated artifacts are **committed**: `gen/protocol.rs` (server) and
  `client/scripts/shared/networking/gen/protocol.gd` (client) — so the Godot client builds with no
  Rust toolchain.
- Server crate regenerates via `build.rs`; CI runs `cargo run -p protogen` then fails on a non-empty
  `git diff` (generated code must be in sync with the schema).
- The schema file carries a **protocol version** byte sent in the handshake; client and server refuse
  mismatched versions.

This resolves the **[Wire protocol]** and **[Codec toolchain]** open questions. ADR drafted:
[`../adr/0004-schema-driven-wire-protocol.md`](../adr/0004-schema-driven-wire-protocol.md).

### D5 — Sim parity: one shared Rust `sim_core`, loaded on the client as a GDExtension

**Decision.** Write movement/collision/dash/knockback/stamina **once** in a Rust crate (`sim_core`).
The server links it directly. The Godot client loads the **same compiled crate as a GDExtension** and
calls it for **prediction**. Client and server therefore run **literally the same code**, so movement
divergence is zero by construction; the only corrections left are *real* ones (server-only events the
client hadn't seen, e.g. an unacked knockback). This eliminates D1's largest risk outright.

**Alternatives weighed.**
- *Tolerance-based (independent Rust port + lean on correction smoothing):* keeps the client pure
  GDScript and is how most shipped games cope — but maintains movement in **two languages** and risks
  visible snaps on dash/knockback/slide where divergence is largest. Rejected (the project's whole
  point is netcode quality; writing the sim twice is the worst of both worlds after a clean-slate).
- *Fixed-point deterministic rewrite mirrored in both languages:* bit-deterministic by construction
  and a foundation for future lockstep/replays — but the largest rewrite, and float-free GDScript is
  painful. Rejected as overkill for a casual bullet-hell POC (revisit if lockstep/replays become a goal).

**Consequences.**
- ✅ Movement authored **once**; prediction and authority cannot diverge on math.
- ✅ The offline modes (practice/sandbox, client-authoritative) reuse the **same** `sim_core` — they
  stop being a separate code path that can drift.
- ⚠️ The client is **no longer pure GDScript** — it ships a native module per platform (win/mac/linux).
  The export pipeline already produces per-platform client builds, so this is incremental, but it adds
  native build/signing steps and slows editor iteration on sim code.
- ⚠️ The Python load-test bots don't predict, so they're unaffected (they send inputs, never call
  `sim_core`).
- 🔁 **Reaches back to D4** — see the [D4 reconsideration] open question below.

> **ADR candidate:** "Shared Rust `sim_core` loaded on the client as a GDExtension." Hard to reverse
> (client gains a native dependency), non-obvious, and a real trade-off vs. a pure-GDScript client.

### D6 — Client extension scope: sim + codec native; transport stays Godot-native ENet

**Decision.** The client GDExtension exposes **both** `sim_core` **and** the wire **codec** to GDScript.
The client encodes/decodes packets by calling the **Rust codec** through the extension; there is **no
GDScript codec**. Transport stays on Godot's **native `ENetConnection`** (honoring ADR 0003): GDScript
owns the socket, UI, and interpolation glue, handing raw bytes across the boundary to the Rust codec.

**Alternatives weighed.**
- *Extension = sim only, keep a generated GDScript codec:* smallest native surface and fully
  GDScript-debuggable networking — but keeps two languages on the wire format and a slower GDScript
  decode path. Rejected.
- *Thick core (transport + codec + sim all native), GDScript = render/UI only:* maximal code sharing,
  thinnest client — but **overrides ADR 0003's native-`ENetConnection` client choice** and pushes the
  most logic out of Godot. Rejected for now (revisit if the GDScript↔native call boundary for codec
  becomes a measured cost).

**Consequence — reopens D4.** With **no GDScript target**, the custom-IDL-+-generator rationale (D4)
collapses: see **[D4 collapse]**. ADR 0004 must be revised to match the outcome.

### D7 — Protocol implementation: shared Rust `protocol` crate, hand-rolled bit codec (supersedes D4's toolchain)

**Decision.** **No custom IDL, no generator.** Packets are Rust structs in a shared **`protocol`**
crate that **both** the server binary **and** the client GDExtension depend on. Encode/decode is
hand-written **once** in Rust with full bit-level control: position quantized to `i16` at 0.1 units,
sub-byte delta masks and flags, varints where they pay. D3's *redesign* still holds; only D4's
*implementation choice* (IDL + codegen) is dropped — the grilling showed the generator existed solely
to emit GDScript, which D6 removed.

**Alternatives weighed.**
- *Derive-based codec (bitcode/postcard) in the shared crate:* almost no hand-written codec and easy
  versioning, but looser control over exact bit layout (quantization/delta still need custom impls
  anyway). Rejected — the bandwidth budget wants explicit bit control.
- *Keep the custom IDL + generator (Rust-only output):* a neutral, readable schema in one place — but
  it's machinery for a **single** Rust consumer, and ADR 0003 fixed "native-only, no web client," so
  no second language will ever consume it. Rejected as unjustified complexity.

**Consequences.**
- ✅ One Rust crate is the single source of truth for the wire format; server and client extension
  link the same `Encode`/`Decode`.
- ✅ No codegen step, no schema/generated-code skew to police in CI.
- ⚠️ Versioning is DIY — a `PROTOCOL_VERSION` const in the crate, checked at handshake; lockstep
  client/server deploys (acceptable per ADR 0003's native-only model).
- 🔧 ADR 0004 is **revised** from "custom IDL + codegen" to "redesigned protocol as a shared Rust crate."

This resolves **[D4 collapse]**. The wire-protocol arc settled at: **D3** redesign → **D7** shared Rust
`protocol` crate.

### D8 — Simulation architecture: hand-rolled, single-threaded tick

**Decision.** Plain typed collections (a slotmap/`Vec` per id-range — players 1–999, monsters
30000–39999, projectiles 10000–29999, matching today's invariants) inside one `World`. A **single
synchronous 30 Hz tick loop** on a dedicated thread advances the sim: drain inputs → `sim_core`
movement → monster AI → record monster position history (lag-comp) → collisions → build snapshots →
cleanup. No ECS, no parallelism for the POC.

**Rationale.** Rust single-threaded is ~10–50× the current GDScript loop, and the POC's likely binding
constraint is **bandwidth, not CPU**. Keep the sim simple and deterministic; reserve parallelism as a
*measured* optimization, not a starting assumption.

**Alternatives weighed.**
- *ECS, single-threaded systems (bevy_ecs/hecs):* cleaner separation and an easy on-ramp to parallel
  systems later — but paradigm overhead now, and lag-comp rewind + AoI need careful component design.
  Rejected for the POC; the typed-arena layout below leaves the door open if profiling demands it.
- *ECS + parallel systems from day one:* highest throughput and future-proofs 1000+/shard — but
  cross-thread determinism, ordering, and parallel lag-comp/AoI are real cost, and it optimizes CPU
  when bandwidth is the cap. Rejected as premature.

**Determined Rust stack (defaults, not separately grilled — standard/forced by earlier decisions):**

| Concern | Choice | Why |
|---|---|---|
| Workspace | `protocol` + `sim_core` + `server` (bin) + `client-ext` (cdylib) crates | clean dependency edges; client + server share `protocol` and `sim_core` |
| Godot binding | **`gdext`** (official godot-rust) | the Godot 4 GDExtension binding for the client `sim_core`+codec |
| Transport | **`rusty_enet`** | wire-compatible with Godot's native ENet (D2 / ADR 0003) |
| Concurrency | one synchronous tick thread; Go API I/O offloaded | see [Go API boundary] for the I/O mechanism |
| Async runtime | **none in the hot loop**; a small runtime/thread only for outbound Go API calls | the tick is synchronous; only infrequent character load/save needs async/off-thread |

This resolves **[Rust stack]** and **[Concurrency]**.

### D9 — Go API boundary, part 1: auth via locally-verified Ed25519 session ticket

**Reality check (this boundary is greenfield, not a port).** Today's Godot server **does not validate
auth** (`server_main.gd:702`: `# TODO: Validate character_id with API server` — it trusts the client's
self-reported identity), persists **no** gameplay state (in-memory leaderboard,
`leaderboard_manager.gd:3`), and makes exactly **one** API call: a region-status heartbeat
(`server_main.gd:872`). The architecture diagram's "validate token" / "load-save character" arrows
describe an **intended** boundary that this port will actually build.

**Decision.** Per [ADR 0003](../adr/0003-enet-udp-transport.md): the client fetches a **short-lived
session ticket** from the Go API over **HTTPS**, then presents it in `CONNECT_AUTH` over ENet. The Rust
server **verifies the ticket signature locally** — no per-join API round-trip.

- Signature: **Ed25519 (asymmetric)**. The Go API holds the **private** key and signs tickets; the Rust
  server holds only the **public** key — a compromised game server can verify but **cannot forge**.
- Ticket payload: `{ character_id, region/shard, issued_at, expiry }`, TTL ≈ 30–60 s (long enough to
  connect, short enough that expiry *is* the revocation story).
- Reject on bad signature, expiry, or wrong region; no Redis/DB lookup on the join hot path.

**Alternatives weighed.**
- *Call Go API `/validate` (or Redis) per join:* instant revocation and central session control, but a
  round-trip + Go-API dependency on **every** join — an API outage blocks all joins and slows
  spawn-surges. Rejected for the hot path.
- *Hybrid (local verify + async revocation check):* fast join *and* revocation, but the most moving
  parts and a brief admit window for revoked tickets. Rejected for the POC; revisit if a ban/kick
  feature needs sub-TTL revocation.

**Key management (default).** Keys distributed via env/secret; rotation by publishing a new key id and
accepting both old+new during overlap. Part 2 (character persistence) follows.

### D10 — Go API boundary, part 2: RotMG-style permadeath persistence (hydrate-on-join, death-as-save)

**Decision.** Durable state lives behind the Go API (Postgres); the Rust sim hydrates only the living
character's combat-relevant subset on join and treats **death — not logout — as the first-class save.**
The target is a Realm-of-the-Mad-God-like instance-based MMO (permadeath characters, a forever account
bank), so the persistence model is built around **permadeath and item integrity** from the start, even
though POC gameplay stays HP-only. **The boundary stays thin because only the *living character* state
crosses; account/bank state never enters the combat sim.** Reinforces the AGENTS.md invariant rather
than bending it; **Option 3 (Rust → Postgres direct) is rejected harder** — see item integrity below.

**Three state lifetimes (canonical — added to [`../CONTEXT.md`](../CONTEXT.md)).**

| Lifetime | Examples | Where it lives | Crosses into the Rust sim? | Survives character death? |
|---|---|---|---|---|
| **Account-scoped durable** | bank contents, glory, unlocked classes, currency | Go API / Postgres | **No** — touched only at a bank chest in the Sanctuary, via the API | **Yes** |
| **Character-scoped durable** | level, the 8 potion-raised stats, carried inventory | Go API / Postgres; **hydrated** into the sim on join | **Yes** (this subset only) | **No** — destroyed on death |
| **Session-ephemeral** | current HP/MP, position, active cooldowns | in-memory in the sim only | n/a (born in the sim) | n/a — reset on every entry |

**Death is the load-bearing save (disconnect-immune).** The dangerous exploit under permadeath is
**disconnect-to-dodge-death** ("pull the cable the frame before a fatal hit so the death never saves").
Defense: when HP reaches 0 **in the authoritative tick** (D8's collision/damage stage), the server
**synchronously and transactionally**: (1) deletes the character + everything it carried, (2) credits
account-level glory, (3) leaves the bank untouched — *before any client action can intervene*. Alive/
dead is server-authoritative at the tick it happens; nothing the client does next can undo it. This is
**not** save-on-leave (clean-exit only); a disconnect handler a cheater never lets you reach cannot be
the mechanism.

**Item integrity — the cardinal sin is duplication.** Two vectors, both owned by the Go API:
- **Concurrent sessions:** two sessions on one account both hydrate the same inventory and both save →
  dupe. The Go API **MUST enforce a single active session per account** (now load-bearing, not
  precautionary — ties to D9's ticket issuance).
- **Bank↔character transfers:** every item move is a **single atomic swap owned by Postgres behind the
  Go API** — never "remove from bank, then add to character" (which can half-complete → item in both
  or neither). Letting Rust race these transactions against the API in a second language is the surest
  way to manufacture dupes → **this is the strongest reason Option 3 stays rejected.**

**Instance transitions double as checkpoints.** The world is realms + dungeon instances players portal
between. Each transition is a natural checkpoint + handoff: persist the character-scoped durable state
through the API on transition, re-hydrate in the destination, spawn **fresh** session-ephemeral state
(full HP, portal/Sanctuary spawn). Instances are **stateless-on-entry**; the API is the handoff medium.
Caution: **death-resolution authority must sit clearly on one side of a transition** — a player
mid-portal who would have died must not use the transition as another dodge.

**Write discipline (defaults).**
- Writes are **idempotent absolute-state** ("character is now level 12, these 8 stats, this exact
  inventory"), not deltas → every save (transition, periodic, death) is **safe to retry**.
- A **periodic checkpoint** bounds loss on accumulating state (XP / glory-in-progress) between transitions.
- **Build the seam now, grow the payload later:** stand up hydrate-on-join, the death-persist, the
  atomic item move, and the session lock **early**; let durable fields start small (POC: identity +
  HP-only) and widen as classes / skill trees / item types land. The seam is the expensive-to-retrofit
  part; the payload rides it for free.

**Scaling escape hatch (post-POC, server-only, same API contract).** If per-transition API round-trips
bottleneck on high portal frequency, introduce a **per-player session actor** that outlives individual
instances and owns the live character state, with instances borrowing it. Behind the same API contract,
so it's a server-internal change, not a boundary change.

This resolves **[Go API boundary]**. ADR drafted:
[`../adr/0005-permadeath-persistence-model.md`](../adr/0005-permadeath-persistence-model.md).

### D11 — Hit authority: port the two-netcode model as-is; escalate the PvE hole under permadeath

**Decision.** Keep the [two-netcode model](../netcode/hit-authority-model.md) intact — **client-
authoritative + server-validated PvE** (RotMG dodge-feel) and **server-authoritative, lag-compensated
PvP / player→monster**. The `HitAuthority` pure predicates (`hit_authority.gd`: authority split, client
swept test, flight reconstruction, server plausibility) move into the **shared Rust `sim_core`**, so the
client (via the GDExtension) and the server share them exactly — the same anti-drift guarantee D5 gives
movement. The authority *model* is unchanged.

**What changes because of D10 (permadeath).** The doc's *"accepted hole"* — never-report ⇒ immune to
monster damage — was accepted under POC stakes (respawn, no economy). Under permadeath + a bank
economy it becomes **risk-free farming of real loot** (the actual RotMG invuln-hack problem). So the
port **escalates** it from accepted to mitigated:
- **Enable the lenient server backstop** (today "left off"): if a monster bullet's **authoritative path
  blatantly overlaps** the player and **no `LOCAL_HIT_REPORT` arrives within N ticks**, the server
  applies the hit. Catches egregious never-reporters.
- **Open a statistical anti-cheat workstream:** flag accounts taking ≈zero monster damage over time.
  This catches *subtle* invuln the backstop can't; it's a detection/ban concern, **separate from the
  authority model.**

**Hard constraint (carried from the doc's invariants).** The backstop must stay **lenient / blatant-
overlap-only**. A *tight* backstop re-decides hits on authoritative positions and reintroduces the
phantom-hit / pass-through feel the whole split exists to prevent — invariant #4 in
[`hit-authority-model.md`](../netcode/hit-authority-model.md). Tune with mixed-ping play-tests.

**Alternatives weighed.**
- *PvE server-authoritative under permadeath:* closes the hole fully but **reintroduces phantom/pass-
  through** and throws away the dodge-feel that is the core skill. Rejected.
- *Port as-is, accept the hole:* simplest and matches shipped RotMG, but leaves the economy exposed
  until out-of-band detection exists. Rejected — D10 made integrity load-bearing.

**Carried-forward invariants the Rust port must preserve** (from the hit-authority doc): server skips
`owner_id >= MONSTER_ENTITY_ID_START` in its PvP/PvE-player collision pass; `LOCAL_HIT_REPORT` applies
only to the **reporting peer's own** entity and rejects player-owned projectiles; monster
`PROJECTILE_FIRED` carries a **non-zero** projectile id; the client tests against the **rendered**
position, not the predicted one. These become Rust-side tests.

This resolves **[Hit authority]**.

### D12 — Validation: play-test + load-test primary (no golden-trace/dual-run harness)

**Decision.** Validate the Rust server with **manual play-testing** (correctness/feel) and the existing
**Python bot swarm** (scale/perf at 500–1000). **No** recorded golden-trace oracle and **no** live
shadow dual-run harness will be built.

**Two things that come essentially free (use them regardless).**
- **Prediction-snap rate is a live divergence alarm — for free.** D5's shared `sim_core` means client
  prediction runs the *same* code as the server, so any sim divergence shows up as a spike in
  correction snaps, visible to players *and* metrics with zero extra harness. This is the one piece of
  automated equivalence signal that survives this decision.
- **A `sim_core` property-test floor is cheap insurance** (movement determinism, hit predicates, codec
  round-trip). Recommended even though full validation tooling is out of scope — these catch the bugs
  that are worst to diagnose live under load.

**Alternatives weighed.**
- *Layered (property + recorded golden traces + bots + snap monitor):* the rigorous option; recovers a
  *recorded* oracle compatible with clean-slate. Not chosen (harness cost).
- *Live shadow dual-run vs. a kept Godot server:* strongest oracle but contradicts D1's clean-slate.
  Not chosen.

**Accepted residual risk.** Behavioral regressions surface in play/load rather than in CI; there is no
automated correctness gate beyond the free snap-monitor. **Irreversible-timing caveat:** a recorded
golden-trace oracle can only be minted **while the Godot server still exists** — see [Sequencing]; if
that option is wanted later it must be exercised *before* the Godot server is retired, or it's gone.

This resolves **[Validation]** (as a deliberate, narrower scope than offered).

### D13 — Deployment: one process per instance, orchestrated by the Go API/matchmaker

**Decision.** The Rust binary **is a single instance** (one D8 tick loop). Run **N** of them; the Go API
(matchmaker role) **spawns and assigns** players using the **region/shard the session ticket already
carries** (D9). POC runs a small fixed pool via **docker-compose** (the `rust-server` container replaces
today's Godot `server` container; `N=1` reproduces the current single arena); production scales the pool
under an orchestrator (k8s/Nomad) later. **Crash-isolated** — one instance dying never touches others.

**Why this unifies POC and vision.** Because the binary is one instance, the single-arena POC and the
instance-based MMO are the *same artifact* at different N — no rearchitecting between them.

**Portal handoff ties to D10.** An instance transition (D10's checkpoint) is matchmaker-mediated:
client requests a portal → Go API persists the character (D10) and issues a **new ticket** for the
destination instance → client connects there. Cross-instance comms go **through the Go API only**,
consistent with the persistence boundary (no instance-to-instance direct links).

**Alternatives weighed.**
- *One process multiplexing many instances:* fewer processes and cheap cross-instance memory, but one
  crash risks many instances and it reintroduces the threading D8 avoided. Rejected.
- *Single shared-arena process (as today):* simplest, but ignores the D10 vision and is just this option
  at `N=1` anyway. Rejected as the *model* (kept as the POC's starting N).

**Observability (defaults).** Structured logging (`tracing` crate); a Prometheus `/metrics` endpoint per
instance (tick time, players, bandwidth, snapshot bytes, correction-snap rate — the D12 divergence
signal); keep the client-facing `SERVER_METRICS` packet. Each instance registers liveness with the Go
API (generalizing today's region-status heartbeat, `server_main.gd:872`).

**Networking/infra notes (carried from ADR 0003).** UDP game port must be reachable per instance
(open the UDP port in compose/orchestrator); no HTTPS proxy-friendliness as with WebSocket; the Go API
stays HTTPS for ticket issuance.

This resolves **[Deployment]**.

### D14 — Sequencing: tracer-bullet spine first, then layer features onto it

**Decision.** Prove the **novel cross-language spine end-to-end** before building gameplay. The port has
*integration* risk (gdext driving client prediction, `rusty_enet`↔Godot-native ENet wire-compat,
cross-language reconciliation) that a layer-by-layer build would surface only after most code is written.
A vertical tracer bullet pays that risk down on day one and keeps an always-runnable system to play-test.

**Milestone plan.**

| Milestone | Slice | Proves / delivers | Key decisions exercised |
|---|---|---|---|
| **M0 — Spine** | "one moving square": minimal `protocol` crate (input + position snapshot) → `rusty_enet` server with a trivial tick → Godot client on **native ENet** → `sim_core` extension does prediction → reconcile | the entire spine works end-to-end: transport, codec, shared sim, prediction/reconciliation | D2, D5, D6, D7, D8 |
| **M1 — Movement** | full `sim_core` (obstacle collision, dash, knockback, stamina), AoI + delta snapshots + baselines, multi-player interpolation | movement parity + replication at fidelity | D3, D7, D8, [interest-mgmt] |
| **M2 — Combat** | shooting, projectiles, the two-netcode hit authority + `HitAuthority` in `sim_core`, monsters + AI, lag comp | gameplay parity with today | D11 |
| **M3 — Service boundary** | Go API: Ed25519 ticket issuance + local verify; permadeath persistence — hydrate-on-join, **death-as-save**, single-session lock, atomic item transfer (payload minimal first) | the durable boundary + economy integrity | D9, D10 |
| **M4 — Deploy** | one-process-per-instance, matchmaker spawn/assign, portals/transitions, `tracing` + Prometheus | instances + the MMO-shaped deployment | D13 |
| **M5 — Scale & cutover** | Python bot swarm to 500–1000, perf tune, run the **cutover gate**, retire the Godot server | the POC success criteria + the big-bang cutover | D1, D12 |

**Cutover gate (the D1 big-bang criteria — all must hold before deleting the Godot server).**
1. **Feature parity** — movement, combat, monsters, and the two-netcode hits behave equivalently in
   play-test.
2. **Persistence safety (D10)** — the three integrity tests pass: disconnect-at-fatal-hit keeps the
   character dead; concurrent-session shows no dupe; item-transfer crash-injection leaves no item in
   both/neither place.
3. **Scale** — 500–1000 bots hold the tick-rate and per-player bandwidth targets
   ([performance-budgets.md], to be re-measured per D3/ADR 0004).
4. **Feel** — prediction-snap rate (the free D12 divergence monitor) stays within bound under
   mixed-ping play-test.
5. **Record-before-delete (D12 caveat)** — M5 is the **last** point to capture golden-trace fixtures if
   that oracle is ever wanted; the Godot server is retired only after this step is consciously skipped
   or done.

This resolves **[Sequencing]**. **All open questions are now resolved.**

## Open questions (live status)

| Tag | Status |
|---|---|
| **[Transport]** | ✅ Resolved — D2 (ENet, wire-compatible). |
| **[Wire protocol]** | ✅ Resolved — D3 (schema redesign). |
| **[Codec toolchain]** | ✅ Resolved — D4 proposed (custom IDL), **superseded by D7** (shared Rust `protocol` crate). |
| **[Shared-sim parity]** | ✅ Resolved — D5 (shared `sim_core` via GDExtension). |
| **[D4 reconsideration]** | ✅ Resolved — D6: extension exposes sim + codec; **no GDScript codec**; transport stays Godot-native ENet (ADR 0003). |
| **[D4 collapse]** | ✅ Resolved — D7: collapse to a shared Rust `protocol` crate, hand-rolled bit codec. |
| **[Rust stack]** | ✅ Resolved — D8 (gdext, rusty_enet, `protocol`/`sim_core`/`server`/`client-ext` workspace). |
| **[Concurrency]** | ✅ Resolved — D8 (single synchronous tick thread; parallelism deferred). |
| **[Go API boundary]** | ✅ Resolved — D9 (Ed25519 local-verify ticket) + D10 (permadeath persistence, death-as-save). |
| **[Hit authority]** | ✅ Resolved — D11 (port two-netcode model; escalate the PvE hole under permadeath). |
| **[Validation]** | ✅ Resolved — D12 (play-test + load-test; free snap-monitor; property-test floor). |
| **[Deployment]** | ✅ Resolved — D13 (one process per instance, Go API/matchmaker orchestrated). |
| **[Sequencing]** | ✅ Resolved — D14 (tracer-bullet spine first; cutover gate defined). |

**All branches resolved (2026-06-11).** The full decision log D1–D14 (D1–D5 above this status table,
D6–D14 below it) is complete; ADRs 0004 and 0005 are drafted. What remains is execution per the D14
milestone plan. A one-line summary of every decision is in [Migration at a glance](#migration-at-a-glance).

---

## Migration at a glance

Every decision, one line. Full reasoning is in the decision log above.

| # | Decision | Choice |
|---|---|---|
| **D1** | Cutover strategy | Clean-slate rewrite, new transport from day one (no WebSocket intermediate, no live parity oracle) |
| **D2** | Transport | ENet protocol, wire-compatible — Godot native `ENetConnection` ↔ Rust `rusty_enet`; 3 channels |
| **D3** | Wire protocol | Redesign (tighter bitpacking), not a carry-forward |
| **D4** | Codec toolchain (proposed) | Custom IDL + generator — **superseded by D7** |
| **D5** | Sim parity | One shared Rust `sim_core`; client loads it as a GDExtension for prediction |
| **D6** | Client extension scope | Extension = sim + codec; **no GDScript codec**; transport stays Godot-native ENet |
| **D7** | Protocol implementation | Shared Rust `protocol` crate, hand-rolled bit codec (no IDL, no codegen) |
| **D8** | Sim architecture | Hand-rolled typed arenas, single synchronous 30 Hz tick thread; `gdext` + `rusty_enet` |
| **D9** | Auth | Locally-verified **Ed25519** session ticket (Go API signs private, server holds public) |
| **D10** | Persistence | RotMG **permadeath**: hydrate-on-join, **death-as-save** (disconnect-immune), atomic item transfer, single session |
| **D11** | Hit authority | Port the two-netcode model as-is; **escalate** the PvE hole under permadeath (backstop + anti-cheat) |
| **D12** | Validation | Play-test + load-test; free prediction-snap divergence monitor; property-test floor |
| **D13** | Deployment | One process per instance; Go API/matchmaker spawns + assigns via ticket region/shard |
| **D14** | Sequencing | Tracer-bullet spine (M0) first, then layer features; defined cutover gate |

**ADRs spawned:** [0004 — redesigned wire protocol as a shared Rust crate](../adr/0004-schema-driven-wire-protocol.md)
(amends 0003) · [0005 — permadeath persistence](../adr/0005-permadeath-persistence-model.md).
**Amended:** [ADR 0003](../adr/0003-enet-udp-transport.md) — its "wire format rides unchanged / port reimplements only the seam" consequence is superseded by D1+D3+D7.

## The eight questions

- **Client (Godot):** native `ENetConnection` transport + UI + interpolation glue; loads a Rust
  GDExtension that runs `sim_core` for **prediction** and the `protocol` **codec** for encode/decode.
- **Server (Rust):** single-threaded 30 Hz authoritative tick over hand-rolled typed arenas; links the
  same `sim_core` + `protocol`; one process = one instance.
- **Predicted:** the Local player only, via the shared `sim_core` (so prediction == authority by
  construction); the client's monster-hit decision stays authoritative-pending-validation (D11).
- **Replicated:** entity deltas vs. a periodic baseline over ENet ch0 (unreliable-sequenced); discrete
  `GAME_EVENT`s over ch1 (reliable) — all via the shared `protocol` crate.
- **Persisted:** nothing in the sim; the Go API owns Account- and Character-scoped durable state
  (Postgres). Session-ephemeral state never leaves memory. Death is a transactional API save (D10).
- **Validated:** Ed25519 ticket verified locally (D9); movement re-simulated server-side; PvP/PvE-on-
  monster hits lag-compensated and server-decided; monster→player reports plausibility-gated; item
  integrity (single session, atomic transfer) enforced by the Go API.
- **Can fail:** divergence between `sim_core` builds (caught by the snap-monitor); a lost ch0 snapshot
  (superseded, by design); death-write failure (idempotent retry / in-memory dead flag holds); UDP port
  unreachable (deployment must open it); the accepted-but-now-mitigated PvE never-report hole (D11).
- **Tested:** `sim_core` + `protocol` property tests; the Python bot swarm at 500–1000; the permadeath
  integrity tests (disconnect-at-death, no-dupe, atomic-transfer) gate cutover; play-test for feel.

## See also

- [`../adr/0003-enet-udp-transport.md`](../adr/0003-enet-udp-transport.md) · [`0004`](../adr/0004-schema-driven-wire-protocol.md) · [`0005`](../adr/0005-permadeath-persistence-model.md)
- [`../netcode/overview.md`](../netcode/overview.md) · [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) · [`../CONTEXT.md`](../CONTEXT.md)
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — top-level system architecture this port re-shapes.
