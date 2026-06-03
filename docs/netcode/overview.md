# Netcode overview — authority model, loops, packet map

**Status:** Implemented (verified 2026-06-03 against code)

> The map of the netcode subtree. It fixes the **authority model**, the **three loops**, and the
> **packet map** once, so the deep docs don't each re-derive them. When you need a mechanism in
> detail, jump from the [where to go next](#where-to-go-next) index — don't expand it here.

## Authority model — "the client requests, the server decides"

This is an [Authoritative server](../CONTEXT.md): one Godot 4.6 headless process is the single
source of truth for all gameplay. The client sends *intent* (`PLAYER_INPUT`); the server runs the
simulation, decides outcomes, and streams back authoritative state (`STATE_UPDATE`) and one-shot
[Game events](../CONTEXT.md) (`GAME_EVENT`). Nothing a client claims about position, hits, or kills
is trusted.

Two client-side techniques hide the round-trip without surrendering authority:

- The [Local player](../CONTEXT.md) is **predicted** — the client simulates its own input
  immediately (`prediction.gd:142,162`) and later [reconciles](../CONTEXT.md) to the server
  (`prediction.gd:171` acks; replay of unacked inputs). Drift past the 4-unit epsilon
  (`prediction.gd:30`) snaps `predicted_position`; bigger jumps past the 150-unit teleport
  threshold (`prediction.gd:28`) hard-warp.
- Every [Remote entity](../CONTEXT.md) is **interpolated**, never predicted — drawn from buffered
  Snapshots at a fixed [Render delay](../CONTEXT.md) of `REMOTE_ENTITY_RENDER_DELAY_TICKS = 2`
  (`game_constants.gd:20`, applied at `interpolation_controller.gd:186`) = 66.7 ms behind the
  server tick.

Persistence is split: all gameplay state is **in-memory and server-authoritative**; the Go API
owns only account / character / leaderboard / region data.

## The three loops

Three independent clocks drive the netcode. Confusing them is the most common source of error, so
they are named with the [glossary](../CONTEXT.md) terms ([Tick](../CONTEXT.md) ≠
[Frame](../CONTEXT.md) ≠ [Snapshot](../CONTEXT.md)).

| Loop | Where | Driver | Rate | What it does |
|---|---|---|---|---|
| **Server Tick** | `server_main.gd:170-182` | manual accumulator in `_process` | **30 Hz** (33.3 ms) | advance the authoritative simulation one Tick |
| **Server Snapshot** | `server_main.gd:207-218,249-253` | second accumulator gated on the Tick | **20 Hz live** (50 ms) | broadcast `STATE_UPDATE` per player |
| **Client predict + interpolate** | `prediction.gd:142`, `interpolation_controller.gd` | `_physics_process` | **30 Hz** (33.3 ms) | predict Local player, interpolate Remote entities, send `PLAYER_INPUT` |

### 1. Server Tick — 30 Hz, in `_process` (not `_physics_process`)

The simulation steps on a **manual accumulator inside `Node._process`** (`server_main.gd:177-182`):
`tick_timer += delta`, then `while tick_timer >= 1/tick_rate: _process_server_tick()`. There is
**no** `Engine.max_fps` cap and it does **not** use `_physics_process`. Each Tick (in order,
`server_main.gd:230-256`): drain client inputs → update state → monster AI → record monster
position snapshot (for PvE rewind) → collisions → *conditionally* broadcast → cleanup. `tick_rate`
is 30 (`data/config/server_config.json:9`).

### 2. Server Snapshot — 20 Hz live, decoupled from the Tick

Snapshot bandwidth is **decoupled** from the Tick by a second accumulator
(`server_main.gd:207-218`): a Tick only sets `snapshot_due` when enough wall time has elapsed at
`snapshot_rate_hz`, and `broadcast_state_updates` runs only on those Ticks (`server_main.gd:249`).
Events (`GAME_EVENT`) still fire every Tick — only continuous state is rate-limited.

> **Config discrepancy — flag this.** `ServerConfig` *defaults* `snapshot_rate_hz = 0`, which falls
> back to the Tick rate (30 Hz) (`server_config.gd:88-93`). But the loaded
> `data/config/server_config.json:10` sets `snapshot_rate_hz = 20`, and **the JSON wins at
> runtime** → the **live Snapshot rate is 20 Hz (50 ms)**, not 30. Several client-side constants
> still assume 20 Hz from before the Tick rate moved to 30 (see
> [`smoothness-render.md`](smoothness-render.md) and the interpolation doc); the stale comments
> (`interpolation_controller.gd:9,75`) say "20Hz/100ms" and should be read as historical.

### 3. Client predict + interpolate — 30 Hz, in `_physics_process`

The client's gameplay loop runs in `_physics_process` (`prediction.gd:142`): capture input flags,
apply local prediction, smooth any active correction, and send `PLAYER_INPUT` on the server-tick
cadence (`INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL`, `prediction.gd:71`; sent at
`prediction.gd:170-172`). 8-bit wrapping sequence numbers and a 256-entry replay buffer
(`prediction.gd:21,57`) bound reconciliation. `InterpolationController._physics_process` advances
every Remote entity toward `render_tick = server_tick − 2` (`interpolation_controller.gd:186`).

> **Frame ≠ Tick.** Both gameplay loops above write node positions only in `_physics_process` at
> 30 Hz, while the GPU draws Frames far more often. Built-in physics interpolation is off, so motion
> *steps* at 30 Hz regardless of FPS — the "looks like 30 fps at 100 fps" bug, owned by
> [`smoothness-render.md`](smoothness-render.md).

### Transport note

All three loops ride **WebSocket over TCP** both directions (`network_manager.gd:49,144,182`
server via `TCPServer` + `WebSocketPeer.accept_stream`; `network_manager.gd:295-298` client via
`connect_to_url` + TLS). Sockets are **polled once per render Frame** in `_process`
(`network_manager.gd:167-171,190,235`), *not* on the Tick. The server coalesces a Tick's per-peer
packets into one `BATCH` frame flushed at end-of-Tick (`server_main.gd:227-228,258-259`); the
client sends one `ws.send` per message. Deep dive: the transport doc (Planned).

## The packet map

One byte of header type selects the message. The wire header is `[u8 type][u16 length]`
(`packet_types.gd:7`); `MAX_PACKET_SIZE = 65535` (`packet_types.gd:10`). The `MessageType` enum is
defined identically in `packet_types.gd:13-25` (`Type`) and mirrored in `network_manager.gd:16-28`
(`MessageType`) — keep them in lockstep.

| # | Name | Direction | Carries | Notes |
|---|---|---|---|---|
| 1 | `PLAYER_INPUT` | client → server | input flags + aim + 8-bit sequence | intent only; sampled & sent at 30 Hz (`prediction.gd:170`) |
| 2 | `STATE_UPDATE` | server → client | [Snapshot](../CONTEXT.md): entity positions / anim / flags | delta-encoded vs a [Baseline](../CONTEXT.md); forced full state every 100 ticks (`packet_types.gd:78`); 20 Hz live |
| 3 | `GAME_EVENT` | server → client | one-shot [Game event](../CONTEXT.md) (damage, kill, respawn, `PLAYER_INFO`, projectile fired…) | sub-types in `GameEventType` (`packet_types.gd:81-94`); fires every Tick, not rate-limited |
| 4 | `HEARTBEAT` | bidirectional | keep-alive + `server_ms` for clock sync | 1 Hz; 5 s timeout; client echoes (`network_manager.gd:494-501`) |
| 5 | `ACTION_CONFIRM` | server → client | authoritative move confirm / correction (sequence + position + tick) | drives [Reconciliation](../CONTEXT.md) (`server_main.gd:310-320`) |
| 6 | `CONNECT_AUTH` | client → server | auth handshake (JWT from the Go API) | the "AUTH/CONNECT" message; sent on connect (`network_manager.gd:398`) |
| 7 | `DISCONNECT` | client → server | clean disconnect + reason code | `DisconnectReason` enum (`packet_types.gd:97-104`) |
| 8 | `REQUEST_FULL_STATE` | client → server | ask for a fresh full-state [Baseline](../CONTEXT.md) | recovery when delta reconstruction fails (TASK-021) |
| 9 | `RESPAWN_REQUEST` | client → server | request respawn after death | server validates life-state |
| 10 | `SERVER_METRICS` | server → client | tick time / bandwidth / player count | 1 Hz diagnostics (`server_main.gd:194`) |
| 11 | `BATCH` | server → client | N inner packets in one WS frame | per-peer coalescing wrapper (TASK-066, `network_manager.gd:617`) |

The four message types the spec calls out — `AUTH/CONNECT` (= `CONNECT_AUTH`, 6), `PLAYER_INPUT`
(1), `STATE_UPDATE` (2), `GAME_EVENT` (3), `ACTION_CONFIRM` (5), `HEARTBEAT` (4), `DISCONNECT` (7),
`REQUEST_FULL_STATE` (8) — are all present above; there is **no** standalone `AUTH` or `CONNECT`
message, only the combined `CONNECT_AUTH`.

## Where to go next

The deep docs own the mechanisms; this overview only points at them.

- [`latency-budget.md`](latency-budget.md) — **start here.** Every millisecond of perceived delay, accounted with `file:line`. *(live)*
- [`smoothness-render.md`](smoothness-render.md) — the "30 fps at 100 fps" stepping bug and its fix. *(live)*
- `client-prediction.md` — Local player prediction + reconciliation internals (sequence/replay/correction lerp). *(Planned)*
- `interpolation.md` — Remote entity interpolation, the 2-tick Render delay, state buffer, extrapolation/freeze. *(Planned)*
- `server-tick-broadcast.md` — the Tick loop, the decoupled Snapshot cadence, per-player broadcast. *(Planned)*
- `interest-mgmt-aoi.md` — [AoI](../CONTEXT.md) filtering, LOD, the per-peer snapshot byte budget / scheduler. *(Planned)*
- `wire-protocol.md` — header, quantization, delta masks, the u8 entity-count cap. *(Planned)*
- `transport-websocket.md` — WebSocket/TCP, polling cadence, batching, head-of-line blocking. *(Planned)*
- `performance-budgets.md` — POC targets vs measured numbers. *(Planned)*
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — top-level system architecture + POC success criteria.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary; the canonical terms used throughout this doc.

## The eight questions

- **Client:** samples input, predicts the Local player, interpolates Remote entities, renders, and talks WebSocket — all in `_physics_process`/`_process`.
- **Server:** the authority — runs the 30 Hz Tick, resolves movement/collisions/combat, and emits `STATE_UPDATE` (20 Hz) + `GAME_EVENT`.
- **Predicted:** only the Local player (`prediction.gd`); Remote entities are never predicted.
- **Replicated:** all entity state via delta `STATE_UPDATE` Snapshots against a 100-tick Baseline; discrete outcomes via `GAME_EVENT`.
- **Persisted:** nothing in the sim — gameplay state is in-memory; the Go API persists account/character/leaderboard/region only.
- **Validated:** server re-simulates every input and corrects via `ACTION_CONFIRM`; positions, hits, and kills are server-decided, never client-claimed.
- **Can fail:** the 20 Hz JSON Snapshot rate diverging from the 30 Hz default; stale 20 Hz client constants; TCP head-of-line blocking stalling all state on one lost segment.
- **Tested:** offline `sandbox.tscn` and full-stack `auto_join_arena.tscn` scenes plus the Python bot swarm; no automated test asserts the loop rates today.

## See also

- [`latency-budget.md`](latency-budget.md) · [`smoothness-render.md`](smoothness-render.md)
- [`../CONTEXT.md`](../CONTEXT.md) · [`../ARCHITECTURE.md`](../ARCHITECTURE.md) · [`../../AGENTS.md`](../../AGENTS.md)
