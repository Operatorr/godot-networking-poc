# Netcode overview — authority model, loops, packet map

**Status:** Implemented (verified 2026-06-14 against `rust/`)

> The map of the netcode subtree, post Rust-port. It fixes the **authority model**, the **three
> loops**, and the **packet map** once, so the deep docs don't each re-derive them. The
> authoritative server is now the Rust **`omega-server`** binary (`rust/server/`) over ENet/UDP,
> running the shared **`sim_core`** crate; the legacy Godot headless server is retired. When you
> need a mechanism in detail, jump from the [where to go next](#where-to-go-next) index — and for
> the as-built wire format, go straight to [`../server/contract.md`](../server/contract.md).

## Authority model — "the client requests, the server decides"

This is an [Authoritative server](../CONTEXT.md): one **`omega-server` process is one instance**
([`../server/design.md`](../server/design.md)) and is the single source of truth for all gameplay.
The client sends *intent* (`PlayerInput`); the server runs the simulation, decides outcomes, and
streams back authoritative state (`Snapshot`) and one-shot [Game events](../CONTEXT.md)
(`GameEvent`). Nothing a client claims about position, hits, or kills is trusted. The retired
GDScript server (`client/scripts/server/*.gd`) is kept only as parity ground truth and is being
deleted — do not cite it as live code.

Two client-side techniques hide the round-trip without surrendering authority:

- The [Local player](../CONTEXT.md) is **predicted** — the client simulates its own input
  immediately through the **same compiled `sim_core` crate** the server runs, exposed to GDScript
  as `PredictionSim` (`client/scripts/network/prediction.gd`; the `client_ext` GDExtension). Because
  client and server execute literally the same movement code, prediction cannot diverge on the
  math; later it [reconciles](../CONTEXT.md) to the server's `ActionConfirm`. Drift past the 4-unit
  epsilon (`prediction.gd` `server_position_epsilon`) smooth-corrects; jumps past the 150-unit
  teleport threshold (`prediction.gd` `teleport_threshold`) hard-warp.
- Every [Remote entity](../CONTEXT.md) is **interpolated**, never predicted — drawn from buffered
  Snapshots at a fixed [Render delay](../CONTEXT.md) of `REMOTE_ENTITY_RENDER_DELAY_TICKS = 2`
  (`client/scripts/data/game_constants.gd`, applied in `interpolation_controller.gd`) ≈ 66.7 ms
  behind the server tick. The delay adapts within `[1, 3]` ticks under jitter.

Persistence is split: all gameplay state is **in-memory and server-authoritative**; the **Go API**
(`api/`, Postgres + Redis) owns all durable state — accounts, characters, leaderboard, regions, and
Glory. Auth is an **Ed25519 session ticket** minted by the Go API and **verified locally** by the
server (dev default `--allow-unsigned-tickets`); see [`../server/design.md`](../server/design.md).

## The three loops

Three independent clocks drive the netcode. Confusing them is the most common source of error, so
they are named with the [glossary](../CONTEXT.md) terms ([Tick](../CONTEXT.md) ≠
[Frame](../CONTEXT.md) ≠ [Snapshot](../CONTEXT.md)).

| Loop | Where | Driver | Rate | What it does |
|---|---|---|---|---|
| **Server Tick** | `rust/server/src/main.rs`, `world.rs::tick` | fixed 30 Hz accumulator over non-blocking ENet `host.service()` | **30 Hz** (33.3 ms) | advance the authoritative simulation one Tick |
| **Server Snapshot** | `rust/server/src/sim/world.rs` (`snapshot_accumulator`), `broadcast.rs` | second accumulator gated on the Tick | **30 Hz live** (matches tick; see note) | build + send per-peer `Snapshot` |
| **Client predict + interpolate** | `prediction.gd::_physics_process`, `interpolation_controller.gd` | `_physics_process` | **30 Hz** (33.3 ms) | predict Local player, interpolate Remote entities, send `PlayerInput` |

### 1. Server Tick — 30 Hz, single-threaded synchronous

The main thread **is** the tick thread (`rust/server/src/main.rs`): a fixed 30 Hz accumulator loop
over a non-blocking `host.service()` — there is no game-engine frame loop. Each Tick, in order
(`rust/server/src/sim/world.rs::tick`): drain `host.service()` → decode and route → apply inputs (per-
player latched flags, `_pending_dash`, stale-input timeout) → step players through
`sim_core::step_player` → monster AI (`monster.rs`) → record monster position history (lag-comp
ring) → projectile + collision pass (`projectile.rs`, `combat.rs`, two-netcode model) → deaths /
respawns / leaderboard → build per-peer Snapshots → send confirms + events → `host.flush()` → sleep
the remainder in short slices that keep ENet acks timely. `tick_rate` is **30**
(`rust/server/src/config.rs`; `deployment/server_config.{arena,sanctuary}.json`). Infrequent side
I/O (Go API region heartbeat, persistence) runs on a separate thread over `std::sync::mpsc`, never
blocking the tick.

### 2. Server Snapshot — decoupled from the Tick by an accumulator

Snapshot bandwidth is **decoupled** from the Tick by a second accumulator
(`rust/server/src/sim/world.rs`: `snapshot_accumulator += tick_dt`, fire when `>= snapshot_interval`).
A Tick only sets `snapshot_due` when enough wall time has elapsed at `snapshot_rate_hz`; events
(`GameEvent`) still fire every Tick — only continuous state is rate-limited.

> **Live rate is 30 Hz, not 20.** The config default `snapshot_rate_hz = 0` falls back to the tick
> rate (`config.rs::snapshot_rate_hz` → `tick_rate`), and the deployed
> `deployment/server_config.{arena,sanctuary}.json` set `snapshot_rate_hz = 30`. So the live
> Snapshot rate equals the Tick rate at **30 Hz (33.3 ms)**. Older client constants and comments
> that assume a 20 Hz / 50 ms snapshot interval are historical (WebSocket-era); read them as such
> and cross-check [`smoothness-render.md`](smoothness-render.md) and
> [`interpolation.md`](interpolation.md).

### 3. Client predict + interpolate — 30 Hz, in `_physics_process`

The client's gameplay loop runs in `_physics_process` (`prediction.gd`): capture input flags, run
local prediction through `PredictionSim` (the shared `sim_core`), smooth any active correction, and
send `PlayerInput` on the server-tick cadence (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`). An
8-bit wrapping sequence and a replay buffer bound reconciliation; the codec lives in `ProtocolCodec`
(`client_ext`). `InterpolationController._physics_process` advances every Remote entity toward
`render_tick = server_tick − render_delay` (`interpolation_controller.gd`).

> **Frame ≠ Tick.** Both client gameplay loops write node positions in `_physics_process` at 30 Hz,
> while the GPU draws Frames far more often. Render smoothness is decoupled from FPS via Godot's
> `physics_interpolation` plus discontinuity resets — owned by
> [`smoothness-render.md`](smoothness-render.md).

### Transport note

All three loops ride **ENet over UDP** ([ADR 0003](../adr/0003-enet-udp-transport.md)) — **not**
WebSocket/TCP, and **not** Godot High-Level Multiplayer (`MultiplayerSynchronizer` /
`ENetMultiplayerPeer`). The server uses pure-Rust `rusty_enet` (pinned `=0.4.0`); the client uses
Godot's native low-level `ENetConnection` + `ENetPacketPeer`
(`client/scripts/network/transport/enet_transport.gd`), wire-compatible with `rusty_enet`. Three channels,
each matched to its traffic — see [the packet map](#the-packet-map) below. ENet's native
keepalive / RTT / timeout **replaces the old application HEARTBEAT**; the clock-sync payload
interpolation needs (`server_ms`) rides **every** `Snapshot` instead. Deep dive:
[`../server/contract.md`](../server/contract.md) (the transport-websocket doc is a retired stub).

## The packet map

The wire format is a hand-rolled **bit-packed protocol crate** (`rust/protocol/`) — no codegen,
no length field. Every packet is `[u8 type][payload]`; ENet preserves datagram boundaries.
Multi-byte integers are little-endian; bit-level fields pack LSB-first. `PROTOCOL_VERSION = 4`
rides the ENet connect `data: u32` and is re-checked in `ConnectAuth`. The full as-built spec
(field layouts, quantization, the Snapshot delta/baseline bitstream) lives in
[`../server/contract.md`](../server/contract.md) — this is only the map.

**Three channels** (`rust/protocol/src/lib.rs`: `CH_SNAPSHOT`, `CH_RELIABLE`, `CH_INPUT`):

| Ch | ENet mode | Carries |
|---|---|---|
| 0 | unreliable **sequenced** | `Snapshot` deltas, `ActionConfirm` — newest wins; a dropped one is superseded, never retransmitted |
| 1 | **reliable** ordered | `AuthResult`, `GameEvent`, `ServerMetrics`, **baseline `Snapshot`s** (S→C); `ConnectAuth`, `BaselineAck`, `RequestFullState`, `RespawnRequest`, `LocalHitReport` (C→S) |
| 2 | unreliable **sequenced** | `PlayerInput` — the client replays unacked inputs anyway, so loss self-heals |

**Packet type ids** (`rust/protocol/src/types.rs`; direction enforced at decode):

| # | Name | Direction | Carries | Notes |
|---|---|---|---|---|
| 1 | `ConnectAuth` | client → server | version + ticket + name/color + class + character_id + bandwidth budget | the auth handshake; ch1 |
| 2 | `PlayerInput` | client → server | input flags + aim + predicted pos/vel + cursor + 8-bit seq | intent only; 22 B (protocol v4); 30 Hz on ch2 |
| 3 | `BaselineAck` | client → server | acked baseline tick | ch1; enables delta-vs-baseline |
| 4 | `RequestFullState` | client → server | (empty) | recovery when delta reconstruction fails |
| 5 | `RespawnRequest` | client → server | (empty) | server validates life-state |
| 6 | `LocalHitReport` | client → server | projectile id | client-authoritative monster→player hit report |
| 64 | `AuthResult` | server → client | result code + entity_id + server_tick + tick_rate | fast-paths Authority sync |
| 65 | `Snapshot` | server → client | [Snapshot](../CONTEXT.md): per-entity pos/anim/flags + `server_tick` + **`server_ms`** | delta vs an acked [Baseline](../CONTEXT.md), forced full state every 100 ticks; deltas ch0, baselines ch1 |
| 66 | `ActionConfirm` | server → client | move confirm/correction (seq + pos + tick + stamina + mana) | drives [Reconciliation](../CONTEXT.md) |
| 67 | `GameEvent` | server → client | one-shot [Game event](../CONTEXT.md) (DAMAGE, KILL, RESPAWN, PLAYER_INFO, PROJECTILE_FIRED, PICKUP, ABILITY_EFFECT, PROGRESS, EXP_GAIN, LEADERBOARD_UPDATE…) | ch1; fires every Tick, not rate-limited |
| 68 | `ServerMetrics` | server → client | tick time / bandwidth / player count | 1 Hz diagnostics, ch1 |

There is **no** standalone HEARTBEAT, BATCH, or length-prefixed header anymore: keepalive/RTT is
ENet-native, clock-sync (`server_ms`) rides every `Snapshot`, and disconnect uses **native ENet
disconnect** with the reason in `data: u32` (no packet).

**Typed entity id** (bit-packed inside `Snapshot`, `rust/protocol/src/snapshot.rs`):
`[2-bit kind][offset]` — kind 0 player (id 1–999), kind 1 projectile (10000–29999), kind 2 monster
(30000–39999), **kind 3 world effect** (protocol v4; 40000–49999, e.g. Healthorbs / lingering
ability effects).

## Where to go next

The deep docs own the mechanisms; this overview only points at them.

- [`latency-budget.md`](latency-budget.md) — **start here.** Every millisecond of perceived delay accounted. *(verified)*
- [`smoothness-render.md`](smoothness-render.md) — FPS-independent render smoothness (physics interpolation + resets). *(fix applied)*
- [`client-prediction.md`](client-prediction.md) — Local player prediction + reconciliation (the `PredictionSim`/`sim_core` path, sequence/replay/correction). *(partial)*
- [`interpolation.md`](interpolation.md) — Remote entity interpolation, the 2-tick Render delay, state buffer, extrapolation/freeze. *(partial)*
- [`server-tick-broadcast.md`](server-tick-broadcast.md) — the 30 Hz Tick loop, the decoupled Snapshot accumulator, per-player broadcast. *(implemented)*
- [`interest-mgmt-aoi.md`](interest-mgmt-aoi.md) — [AoI](../CONTEXT.md) filtering with hysteresis, the per-peer snapshot byte budget / scheduler. *(implemented)*
- [`hit-authority-model.md`](hit-authority-model.md) — the two-netcode hit model (monster→player client-auth + lenient backstop; PvP / player→monster server-auth + lag-comp). *(partial)*
- [`performance-budgets.md`](performance-budgets.md) — POC targets vs measured numbers. *(reference)*
- [`../server/design.md`](../server/design.md) — the game server: transport, shared sim, tick, auth, persistence, hits — the *why*.
- [`../server/contract.md`](../server/contract.md) — the as-built wire format, crate APIs, numerics, channels — the spec. *(supersedes the retired `wire-protocol.md` / `transport-websocket.md` stubs)*
- [`../ops/architecture.md`](../ops/architecture.md) — top-level system architecture + POC success criteria.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary; the canonical terms used throughout this doc.

## The eight questions

- **Client (Godot):** samples input, predicts the Local player via the shared `sim_core`
  (`PredictionSim`), interpolates Remote entities, renders, and talks native ENet — all in
  `_physics_process`/`_process`.
- **Server (Rust):** the authority — `omega-server` runs the single-threaded 30 Hz Tick over
  `rusty_enet`, resolves movement/collisions/combat with the same `sim_core`, and emits `Snapshot`
  + `GameEvent`. One process = one instance (Arena `:8081`, Sanctuary `:8082`).
- **Predicted:** only the Local player (`sim_core` via `PredictionSim`); Remote entities are never
  predicted. The only predicted *ability* movement is Warrior Charge and Rogue Shadowstep's blink.
- **Replicated:** all entity state via delta `Snapshot`s against a 100-tick Baseline; discrete
  outcomes via `GameEvent` — all through the shared `protocol` crate.
- **Persisted:** nothing in the sim — gameplay state is in-memory; the Go API persists
  account / character / leaderboard / region (and Glory) only. Death is a transactional API save.
- **Validated:** Ed25519 ticket verified locally; movement re-simulated and corrected via
  `ActionConfirm`; PvP / player→monster hits lag-compensated (8-tick history) and server-decided;
  monster→player reports plausibility-gated with a lenient blatant-overlap backstop.
- **Can fail:** a lost ch0 snapshot (superseded by design); a death-write failure (idempotent
  retry / in-memory dead flag holds); an unreachable UDP port; the mitigated monster-hit
  never-report hole.
- **Tested:** `sim_core` + `protocol` property tests; the full-stack `net_smoke.tscn` smoke scene;
  the Rust `omega-load-test` bot swarm at 500–1000 (`./scripts/run_load_test.sh`); permadeath
  integrity tests. No automated test asserts the loop rates today.

## See also

- [`../server/design.md`](../server/design.md) · [`../server/contract.md`](../server/contract.md)
- [`latency-budget.md`](latency-budget.md) · [`smoothness-render.md`](smoothness-render.md) · [`hit-authority-model.md`](hit-authority-model.md)
- [`../CONTEXT.md`](../CONTEXT.md) · [`../ops/architecture.md`](../ops/architecture.md) · [`../../AGENTS.md`](../../AGENTS.md)
