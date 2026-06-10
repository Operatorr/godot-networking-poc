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

---

## Open questions (resolved as grilling proceeds)

- **[Transport]** — D2, in progress.
- **[Wire protocol]** — keep quantization/delta/baseline semantics or redesign?
- **[Shared-sim parity]** — how do client (GDScript) and server (Rust) stay byte-identical on movement?
- **[Rust stack]** — async runtime, ECS vs hand-rolled, netcode crate, serialization.
- **[Concurrency]** — single-threaded tick vs parallel simulation at 500–1000 players.
- **[Go API boundary]** — token validation (shared key vs call-out) and character load/save path.
- **[Hit authority]** — port the two-netcode model (client-auth PvE / server-auth PvP) as-is?
- **[Validation]** — proving behavioral equivalence without a parity oracle.
- **[Deployment]** — process/sharding model, docker-compose fit, observability.
- **[Sequencing]** — milestone order and the cutover gate.
```
