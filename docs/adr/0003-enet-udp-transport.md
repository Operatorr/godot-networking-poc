# ADR 0003 — ENet-over-UDP datagram transport (supersedes 0001's substrate)

**Status:** Accepted (design) — 2026-06-04. The **transport seam** is implemented
(`client/autoload/transport/`); the ENet implementation behind it is a **deferred, human-approved
follow-up**. Supersedes [ADR 0001](0001-websocket-tcp-transport.md) on the transport substrate
**only** — the wire protocol (`PacketWriter`/`PacketReader`, the `[u8 type][u16 length]` header,
quantization, delta masks, BATCH coalescing) and the authoritative fixed-tick model
([ADR 0002](0002-authoritative-server-fixed-tick.md)) stand unchanged.

## Decision

Move the continuous-state channel off WebSocket/TCP onto **ENet-over-UDP**, using Godot's built-in
**`ENetConnection` with raw channels** (NOT `ENetMultiplayerPeer`), keeping the existing
`PacketWriter`/`PacketReader` binary protocol **on top** of it. Two channels:

| Channel | Delivery | Carries |
|---|---|---|
| **ch0** | unreliable, **unsequenced** (`FLAG_UNRELIABLE` / `FLAG_UNSEQUENCED`) | `STATE_UPDATE` (Snapshots) + `PLAYER_INPUT` — superseding state where a lost datagram should be **dropped**, not redelivered |
| **ch1** | reliable, ordered (`FLAG_RELIABLE`) | `GAME_EVENT`, `CONNECT_AUTH`, `BASELINE_ACK`, `ACTION_CONFIRM`, `RESPAWN_REQUEST`, `REQUEST_FULL_STATE`, `DISCONNECT`, `SERVER_METRICS`, `HEARTBEAT` (carries clock-sync → wants ordered-reliable) |

This run ships only the **transport seam** (`Transport` abstract base + `WebSocketTransport` default
impl) so `NetworkManager` calls socket verbs through an interface; behaviour and bytes-on-the-wire are
**identical to today**. The ENet impl is a `Transport` subclass added later.

## Context — why the 0001 premise is now void

ADR 0001 chose WebSocket/TCP and **explicitly rejected ENet** for one reason: *browser reach* (raw
UDP/ENet is unavailable to browsers). Two facts retire that reasoning:

- **The game is native-only, permanently.** There will be no web client. Browser reach — the *sole*
  basis for 0001's ENet rejection and for preferring WebRTC/WebTransport as the eventual datagram
  target — no longer applies. With it gone, ENet is the lowest-friction datagram transport, not the
  rejected one.
- **The server will be ported to Rust.** [`rusty_enet`](https://github.com/jabuwu/rusty_enet) is ENet
  transpiled to Rust and **wire-compatible** with Godot's ENet. Choosing ENet means **one protocol
  spans both languages**: the eventual Rust server speaks the same datagrams the Godot client sends,
  and the Rust port reimplements **only the transport seam**, never the wire format.

ENet is also **built into Godot 4.6** (the `enet` module ships in the standard export templates) —
unlike WebRTC, which needs the `webrtc-native` GDExtension, and WebTransport, which has no native
Godot support. So ENet is the only datagram option that needs **no extra plugin** and **no signalling/
ICE/DTLS dance**.

## Considered options

| Option | Native fit | Datagram (no HOL) | Cross-lang (Rust) | Extra deps | Verdict |
|---|---|---|---|---|---|
| **ENet / UDP via `ENetConnection`** (chosen) | Yes | Yes (per-channel reliability) | `rusty_enet` wire-compatible | None (built in) | **Accepted** |
| WebSocket / TCP (0001, current) | Yes | **No** — one ordered stream, head-of-line blocking | n/a | None | Kept as fallback / reliable-only |
| WebRTC DataChannel | Yes | Yes | No clean Rust path | `webrtc-native` GDExtension + signalling/ICE/DTLS | Rejected — cost without the browser payoff |
| WebTransport (HTTP/3) | **No native Godot support** | Yes | No | Not available | Rejected — unavailable |
| `ENetMultiplayerPeer` | Yes | Yes | Couples to Godot RPC framing | None | Rejected — its framing fights our `PacketWriter` protocol and the Rust port |

## Consequences

- **Fixes TCP head-of-line blocking** (the central risk 0001 documented): a lost Snapshot datagram on
  ch0 is simply dropped; the next Snapshot supersedes it. Remote entities no longer freeze on a single
  loss. This is what makes [`#14` baseline acks](../exec-plans/active/netcode-perf-fixes.md) and the
  adaptive [Render delay](../CONTEXT.md) buffer actually earn their keep — both are inert on TCP today.
- **No transport-layer encryption.** ENet has no built-in TLS. **Auth must not send the JWT over plain
  ENet.** The client obtains a **short-lived session ticket** from the Go API (over HTTPS) and presents
  *that* in `CONNECT_AUTH` on ch1. Wire/API design for the ticket is part of the deferred ENet
  follow-up, not this seam.
- **BATCH coalescing becomes partly redundant** on a datagram transport (ENet fragments large reliable
  packets itself; unreliable ch0 wants whole-Snapshot datagrams, not cross-Tick batches). The seam
  leaves BATCH above it untouched for now; the ENet follow-up revisits whether ch0 should bypass BATCH.
- **NAT traversal / firewalling.** UDP needs the game port reachable (the Docker/DigitalOcean
  deployment must open the UDP port); there is no proxy-friendly HTTPS framing as with WebSocket.
  Acceptable for a native game server with a known endpoint.
- **The seam is the only thing the Rust port reimplements.** Everything above it
  (`PacketWriter`/`PacketReader`, encode/decode, prediction, interpolation, the tick loop) is
  transport-agnostic and language-portable.

## The eight questions

- **Client:** opens one `ENetConnection`, services it per Frame, sends Snapshots/input on ch0
  (unreliable) and events/auth on ch1 (reliable). Today: the `WebSocketTransport` impl behind the seam,
  behaviour unchanged.
- **Server:** binds an `ENetConnection` host, services per Frame, fans Snapshots to peers on ch0. The
  `PacketWriter` buffers it sends are byte-identical to today's.
- **Predicted:** nothing — the transport only moves bytes; Prediction stays client-side.
- **Replicated:** every Snapshot rides ch0 (drop-old-on-loss); every Game event rides ch1 (reliable).
- **Persisted:** nothing — sockets are in-memory; the Go API still owns account/character/leaderboard.
- **Validated:** packet size ≥ `HEADER_SIZE` and `type` validity before decode (unchanged); auth is a
  short-lived **session ticket** (issued by the Go API over HTTPS), never a raw JWT over plain ENet.
- **Can fail:** datagram negotiation/port-unreachable → fall back to the `WebSocketTransport` reliable
  path (the seam makes this a swap, not a rewrite). A lost ch0 Snapshot is dropped by design (next
  Snapshot supersedes). A lost ch1 event is retransmitted by ENet.
- **Tested:** the seam refactor is gated by behavioural-equivalence (the existing E2E + bot-swarm paths
  must be byte-for-byte identical with `WebSocketTransport`); the ENet impl will need a loss-injection
  test that does not exist yet.

## See also

- [ADR 0001](0001-websocket-tcp-transport.md) — the WebSocket/TCP decision this supersedes on substrate; its head-of-line-blocking analysis is the motivation here.
- [`../netcode/transport-websocket.md`](../netcode/transport-websocket.md) — the current transport mechanism and BATCH coalescing the seam preserves.
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — the byte format that rides unchanged above the seam.
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — roadmap item #12 (the transport change).
