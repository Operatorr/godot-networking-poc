# Omega Game Server — design & rationale

How the authoritative game server (`rust/server`, the `omega-server` binary) is built, and the
reasoning behind each load-bearing choice. The wire format, crate APIs, and numerics live in
[`contract.md`](contract.md); this doc is the *why*. Governing rule throughout:
**the client requests, the server decides.**

## Topology

```
Godot Client ──login / account / characters / purchases──▶ Go API ◀──▶ Postgres
     │                                                        ▲
     │  session ticket (short-lived, Ed25519-signed)          │ verify ticket-issued state,
     ▼                                                         │ hydrate / persist character
Godot Client ──realtime game traffic (ENet / UDP)──▶ Rust Game Server ──┘
```

- **Go API** — accounts, login, JWT/session tokens, character metadata, inventory persistence,
  leaderboard, region coordination. Owns all durable state (Postgres + Redis).
- **Rust Game Server** — inputs, movement, combat, monster AI, visibility/AoI, replication,
  snapshots, lag compensation, validation, the tick loop. All gameplay state is in-memory and
  server-authoritative.
- **Godot Client** — rendering, prediction, interpolation, input, UI. Talks to both the Go API
  (HTTPS) and the game server (ENet/UDP).

One `omega-server` process **is a single instance** (one tick loop). The live deployment runs two
— **Arena** (`8081`, monsters + PvP) and **Sanctuary** (`8082`, the safe hub) — as separate
systemd units ([ADR 0007](../adr/0007-native-systemd-deployment.md)). `N=1` is a single arena;
production scales the pool. One crash never touches the others.

## Transport: ENet over UDP, three channels

UDP via the **ENet protocol** ([ADR 0003](../adr/0003-enet-udp-transport.md)). The Godot client
uses its native low-level ENet API (`ENetConnection` + `ENetPacketPeer`); the server uses the
pure-Rust **`rusty_enet`** (pinned `=0.4.0`), wire-compatible with Godot's ENet. Per-message
reliability is the whole point of leaving TCP — three channels, each matched to its traffic:

| Channel | ENet mode | Carries | Why |
|---|---|---|---|
| 0 | unreliable **sequenced** | snapshots, action confirms | newest wins; a dropped snapshot is superseded, never retransmitted or head-of-line-blocking |
| 1 | **reliable** ordered | auth result, game events, baselines, metrics; client one-shots | discrete messages that must arrive exactly once, in order |
| 2 | unreliable sequenced | player input | the client replays unacked inputs anyway, so loss self-heals |

ENet's native keepalive/RTT/timeout replaces an application heartbeat; the clock-sync payload that
interpolation needs (`server_ms`) rides every snapshot instead. Snapshot deltas stay under the
1200 B unreliable budget; baselines are budget-exempt and ride ch1 reliable (fragmentation is fine
there). Full channel/packet detail: [`contract.md`](contract.md).

## One shared simulation, run on both sides

Movement, collision, dash, knockback, and stamina are written **once** in the `sim_core` crate.
The server links it directly; the Godot client loads the **same compiled crate as a GDExtension**
(`client_ext`) and calls it for **prediction**. Client and server therefore run *literally the
same code*, so movement prediction can never diverge from authority on the math — the only
corrections left are real ones (server-only events the client hadn't seen, e.g. an unacked
knockback), surfaced as prediction-snap spikes.

`sim_core` depends on nothing network- or Godot-related, so it stays unit-testable and reusable.
The cost is that the client ships a native module per platform (win/mac/linux), folded into the
existing export pipeline. The offline modes (practice/sandbox) reuse the same crate rather than
forking a second movement path. Numerics (f32 vectors, f64 scalars, truncate-toward-zero
quantization) are specified in [`contract.md` §numerics](contract.md#numerics-policy-sim_core--protocol).

## The tick: single-threaded, 30 Hz

A single synchronous **30 Hz** tick loop on a dedicated thread owns the ENet host and the entire
world. Entities live in plain typed collections keyed by id range (players 1–999, projectiles
10000–29999, monsters 30000–39999). No ECS, no parallelism — Rust single-threaded is ample for the
target, and the binding constraint is **bandwidth, not CPU**; parallelism stays a measured
optimization, not a starting assumption.

Per tick: drain `host.service()` → decode and route → apply inputs → step players through
`sim_core` → monster AI → record monster position history (lag-comp ring) → projectile + collision
pass → deaths/respawns/leaderboard → build per-peer snapshots (AoI grid + hysteresis, delta cache,
byte budget) → send confirms and events → `host.flush()` → sleep the remainder in short slices that
keep ENet acks timely. Infrequent side I/O (Go API heartbeat, persistence) runs on a separate
thread over `std::sync::mpsc`, never blocking the tick.

## Auth: locally-verified session ticket

The client fetches a **short-lived session ticket** from the Go API over HTTPS, then presents it in
`ConnectAuth` over ENet. The server **verifies the ticket signature locally** — no per-join API
round-trip, so an API hiccup can't block a spawn surge.

- **Ed25519, asymmetric.** The Go API holds the private key and signs tickets; the server holds
  only the public key (`OMEGA_TICKET_PUBKEY`). A compromised game server can verify but **cannot
  forge**.
- Ticket payload: `{ character_id, region, issued_at, expires_at }`, short TTL — expiry *is* the
  revocation story. Rejected on bad signature, expiry, or wrong region.
- **Dev mode** (`--allow-unsigned-tickets`, the load-test/POC default) accepts an empty ticket and
  assigns a placeholder `character_id`. A non-empty but malformed ticket is always refused — no
  silent unsigned downgrade.

**Minting side (implemented).** The Go API signs tickets at `POST /api/character/ticket`
(JWT-protected): it looks up the caller's own character, encodes the 22-byte payload, signs with
its Ed25519 seed (`OMEGA_TICKET_PRIVKEY`), and returns the 86-byte blob base64-encoded. Key code:
`api/internal/auth/ticket.go` (signer + region map), `api/internal/handlers/ticket.go` (endpoint),
`api/cmd/gen_ticket_key` (keypair generator). The exact byte layout is locked to the verifier by a
shared cross-language test vector (`api/internal/auth/ticket_test.go` ⇄
`rust/server/src/net/auth.rs::go_cross_language_ticket_vector`).

**Client fetch side (implemented, M3).** `AuthManager.fetch_session_ticket()` POSTs to
`/api/character/ticket` with the JWT, base64-decodes the blob, and validates the 86-byte length.
`NetworkManager.connect_to_server()` calls it (via `_refresh_session_ticket()`) **before every
dial** — so initial joins, portal travel, AND auto-reconnects all present a *fresh* ticket (TTL is
short). On a 503 (API signing disabled) or no JWT, the client falls back to an empty ticket
(unsigned join); a fetch failure is non-fatal and the server's `AuthResult` reports the precise
reason. Player-facing deploys therefore run **fail-closed** (`OMEGA_ALLOW_UNSIGNED_TICKETS=false`
+ `OMEGA_TICKET_PUBKEY` set). **Boot guardrail:** the server refuses to start if tickets are
required but no pubkey is configured (or the pubkey is malformed) — see `rust/server/src/main.rs`
— so a re-provision can't silently strand every player behind a reconnect loop.

**Load-test side (implemented).** The bot swarm (`rust/load_test`) has no user account, so it can't
use `/api/character/ticket`. Against a fail-closed server it instead fetches tickets from
`POST /api/loadtest/ticket` — guarded by a shared secret (`LOAD_TEST_TICKET_SECRET`; dormant/503
when unset) and capped to **synthetic** `character_id`s (≥ 1,000,000). The server already excludes
ids ≥ 1,000,000 from all progression I/O (no hydrate / write-back / permadeath — see
`crate::world` and ADR 0005), so a load-test ticket authenticates a real ENet join **without
touching any character row**, and the live server never has to allow unsigned tickets. Endpoint:
`api/internal/handlers/ticket.go::IssueLoadTestTicket` (reuses the same signer); client side:
`rust/load_test/src/ticket.rs`. See `deployment/DEPLOYMENT.md` §4.

## Persistence: permadeath, death-as-save

Durable state lives behind the Go API (Postgres); the sim hydrates only the living character's
combat-relevant subset on join and treats **death — not logout — as the first-class save**
([ADR 0005](../adr/0005-permadeath-persistence-model.md)). Three state lifetimes, canonical in
[`../CONTEXT.md`](../CONTEXT.md):

| Lifetime | Examples | Lives in | Enters the sim? | Survives death? |
|---|---|---|---|---|
| **Account-scoped durable** | bank, glory, unlocked classes | Go API / Postgres | No (bank chest only, via API) | Yes |
| **Character-scoped durable** | level, raised stats, carried inventory | Go API / Postgres; hydrated on join | Yes (this subset) | No — destroyed on death |
| **Session-ephemeral** | HP/MP, position, cooldowns | in-memory in the sim | n/a (born in the sim) | n/a — reset on entry |

The exploit permadeath must defeat is **disconnect-to-dodge-death**. Defense: when HP reaches 0 in
the authoritative tick, the server **synchronously and transactionally** deletes the character +
its inventory, credits account glory, and leaves the bank untouched — *before any client action can
intervene*. This is not save-on-leave; a disconnect handler a cheater never lets you reach cannot
be the mechanism. Writes are idempotent absolute-state (safe to retry); the Go API enforces a
**single active session per account** and owns **atomic** bank↔character item transfers, because
letting two languages race those transactions is the surest way to manufacture dupes.

## Hit authority: two-netcode model

Kept intact from the [hit-authority model](../netcode/hit-authority-model.md): **client-
authoritative + server-validated** for monster→player hits (RotMG dodge-feel), and
**server-authoritative, lag-compensated** for PvP and player→monster. The pure hit predicates live
in `sim_core`, so client and server share them exactly (the same anti-drift guarantee movement
gets).

Under permadeath the old *accepted hole* — a client that never reports being hit is effectively
invulnerable — becomes risk-free farming of real loot, so it is **mitigated**:

- The **lenient server backstop is ON**: if a monster bullet's authoritative path *blatantly*
  overlaps a player and no `LocalHitReport` arrives within the grace window, the server applies the
  hit. The backstop must stay **lenient / blatant-overlap-only** (true 24 u overlap, grace ≥ 15
  ticks) — a tight backstop re-decides hits on authoritative positions and reintroduces the
  phantom-hit feel the split exists to prevent.
- Subtle invulnerability is a **statistical anti-cheat** concern (flag accounts taking ≈zero
  monster damage), separate from the authority model.

Carried-forward invariants the implementation preserves: the server skips `owner_id >= 30000`
(monster-owned) in its player-collision pass; `LocalHitReport` applies only to the reporter's own
entity and rejects player-owned projectiles; monster shots carry a non-zero projectile id; the
client tests against the **rendered** position, not the predicted one.

## Progression & economy

Progression is **server/API-authoritative** ([ADR 0006](../adr/0006-softcore-hardcore-glory-economy.md)).
The server owns each player's `level`, `experience`, and `total_lifetime_XP`: it hydrates them on
join, applies the level curve and per-level stats (HP / move speed / damage scale; **max level
50**) in the authoritative tick, and pushes a `PROGRESS` event to the display-only client. Two
permanence modes share one save path:

- **Softcore** — death respawns and keeps XP; the character ends only by voluntary **Sacrifice**.
- **Hardcore** — death is permadeath (the character is deleted).

When a character ends (Hardcore death or Sacrifice), the server converts lifetime XP to account
**Glory** as `floor(total_lifetime_XP / 100)` in one atomic Go API transaction, on the same
disconnect-immune path death uses. A client-owned number would be a dupe/inflation vector — which
is exactly why progression is server-decided. The seven Class abilities all resolve damage/spawns
server-side; only Warrior Charge and Rogue Shadowstep's blink are predicted movement (shared
`sim_core`). See [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md) and
[`../systems/abilities.md`](../systems/abilities.md).

## Observability & deployment

Structured logging via `tracing`; a Prometheus `/metrics` endpoint per instance (tick time,
players, bandwidth, snapshot bytes, **correction-snap rate** — the live divergence signal); the
client-facing `ServerMetrics` packet is kept. Each instance registers liveness with the Go API via
a 2 s region heartbeat (`POST /api/regions/heartbeat`, Redis TTL 5 s) — the **sole** signal behind
`GET /api/regions`; there is no TCP probe (the server is UDP-only). Graceful SIGINT/SIGTERM
shutdown sends reasoned disconnects. Deployment, units, and config files:
[`../../deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md).

## The eight questions

- **Client (Godot):** native `ENetConnection` transport + UI + interpolation; loads a Rust
  GDExtension running `sim_core` for prediction and the `protocol` codec for encode/decode.
- **Server (Rust):** single-threaded 30 Hz authoritative tick over typed arenas; links the same
  `sim_core` + `protocol`; one process = one instance.
- **Predicted:** the Local player only, via the shared `sim_core`; the client's monster-hit
  decision is authoritative-pending-validation.
- **Replicated:** entity deltas vs. a periodic baseline over ch0; discrete game events over ch1 —
  all via the shared `protocol` crate.
- **Persisted:** nothing in the sim; the Go API owns Account- and Character-scoped durable state.
  Death is a transactional API save.
- **Validated:** Ed25519 ticket verified locally; movement re-simulated server-side; PvP/player→
  monster hits lag-compensated and server-decided; monster→player reports plausibility-gated; item
  integrity (single session, atomic transfer) enforced by the Go API.
- **Can fail:** a lost ch0 snapshot (superseded, by design); a death-write failure (idempotent
  retry / in-memory dead flag holds); an unreachable UDP port (deployment must open it); the
  mitigated monster-hit never-report hole.
- **Tested:** `sim_core` + `protocol` property tests; the ENet bot swarm at 500–1000
  ([`../../rust/load_test/README.md`](../../rust/load_test/README.md)); permadeath integrity tests
  (disconnect-at-death, no-dupe, atomic-transfer); play-test for feel.

## See also

- [`contract.md`](contract.md) — workspace, wire format, numerics, crate APIs (as built).
- [`../ops/architecture.md`](../ops/architecture.md) — top-level system architecture + POC success criteria.
- [`../adr/0003-enet-udp-transport.md`](../adr/0003-enet-udp-transport.md) ·
  [`0004`](../adr/0004-schema-driven-wire-protocol.md) ·
  [`0005`](../adr/0005-permadeath-persistence-model.md) ·
  [`0006`](../adr/0006-softcore-hardcore-glory-economy.md) ·
  [`0007`](../adr/0007-native-systemd-deployment.md)
- [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) · [`../CONTEXT.md`](../CONTEXT.md)
