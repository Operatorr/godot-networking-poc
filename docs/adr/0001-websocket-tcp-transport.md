# ADR 0001 — WebSocket-over-TCP transport

**Status:** Implemented (verified 2026-06-03 against code) — accepted for the POC; a transport change is **Planned** but deferred.

> **Superseded-in-part by [ADR 0003](0003-enet-udp-transport.md)** (2026-06-04): the datagram-transport
> target is now **ENet-over-UDP**, not WebRTC/WebTransport — the *browser-reach* premise below is void
> (the game is native-only). This ADR's substrate decision is superseded; its head-of-line-blocking
> analysis remains the motivation. The wire protocol and the authoritative fixed-tick model stand.

## Decision

Carry **all** client↔server traffic — Snapshots, Game events, input, heartbeats — over a single
**WebSocket connection per client, on TCP, in both directions**. Server: `TCPServer.listen` +
per-stream `WebSocketPeer.accept_stream` (`network_manager.gd:144-145`, `:181-182`). Client:
`WebSocketPeer.connect_to_url(url, TLSOptions.client())` (`network_manager.gd:295-298`). One
socket, one ordered byte stream, no datagram side-channel.

## Context

This is a netcode POC that must run easily and be reachable from anywhere:

- **Browser reach.** A future web client can only open WebSocket/WebRTC/WebTransport — raw
  UDP/ENet is off the table for browsers. WebSocket is the lowest-friction of those.
- **Godot simplicity.** `WebSocketPeer` is built in and needs no signalling server, ICE, or
  certificate dance; the same `NetworkManager` autoload runs both sides, mode-detected at startup
  (`network_manager.gd:126`). Fastest path to a working authoritative loop.
- **Proxies / TLS.** WebSocket over TLS traverses corporate proxies, load balancers, and the
  Docker/DigitalOcean deployment (`deployment/`) as ordinary HTTPS — no special UDP firewalling.

The cost is paid under packet loss (Consequences).

## Considered options

| Option | Browser reach | Setup cost | Head-of-line blocking | Verdict |
|--------|---------------|------------|-----------------------|---------|
| **WebSocket / TCP** (chosen) | Yes | Lowest (built in) | **Yes — all state on one ordered stream** | Accepted for POC |
| ENet (UDP, Godot built-in) | No (not in browsers) | Low | No (unreliable channels) | Rejected — kills browser reach |
| WebRTC DataChannel (unreliable) | Yes | High (signalling, ICE, DTLS) | No | Deferred — best end-state, too costly to build first |
| WebTransport (HTTP/3 / QUIC datagrams) | Yes (modern) | Medium-high | No | Deferred — drop-in modern equivalent |

## Consequences

- **TCP head-of-line blocking is the main latency risk.** TCP delivers one reliable, in-order
  byte stream, so a single lost segment makes the kernel hold back **every** later segment —
  already-arrived bytes included — until retransmit (≥1 RTT). One dropped segment therefore
  freezes **all** incoming state: every Remote entity stops, not just the one in the lost packet.
- **Wrong trade for continuous state.** Snapshots supersede each other; a real-time transport
  would drop the stale Snapshot and deliver the newest. TCP cannot — it redelivers the stale one
  in order. Under loss the [Render delay](../CONTEXT.md) buffer can drain into extrapolation
  freeze ([`../netcode/interpolation.md`](../netcode/interpolation.md)).
- **No mitigation in code today.** No out-of-band heartbeat channel, no selective drop; the fix
  is a transport change, not a tuning knob.
- **Accepted anyway for the POC.** Loss on a same-region LAN/cloud path is low, and the dominant
  near-term wins are in the Snapshot/wire layers (AoI, scheduler, delta, BATCH coalescing), not
  the transport. We quantify those first.

A datagram transport (WebRTC unreliable, or WebTransport over QUIC) — Snapshots **unreliable +
unordered** with Game events on a separate reliable channel — is the intended end-state and is
**Planned** as the last and largest item, deliberately deferred until the snapshot/wire wins are
measured (Phase 6, `plans/NETWORK_PERFORMANCE_UPGRADES.md:267-284`, `:358`: *"Largest engineering
surface; do last when wins are quantified."*). See
[`../netcode/transport-websocket.md`](../netcode/transport-websocket.md) for the mechanism and the
deferred plan.

## The eight questions

- **Client:** opens one WS-over-TCP socket; full-drains inbound every Frame; one `ws.send` per message.
- **Server:** `TCPServer` + per-peer `WebSocketPeer`; full-drains every Frame; coalesces a Tick's egress into BATCH frames.
- **Predicted:** nothing — the transport only moves bytes; Prediction lives client-side.
- **Replicated:** every Snapshot and Game event rides this single ordered TCP stream.
- **Persisted:** nothing — sockets are in-memory; account/character persistence is the Go API's job.
- **Validated:** packet size ≥ `HEADER_SIZE` and `type` validity before decode (`network_manager.gd:436`, `:917`, `:925`); no auth at the transport layer (that is the `CONNECT_AUTH` message).
- **Can fail:** one lost TCP segment freezes **all** state until retransmit (head-of-line blocking) — the accepted risk this ADR records.
- **Tested:** load-test bots open real WS connections (`load_testing/`); no automated test injects packet loss to exercise head-of-line behaviour yet.

## See also

- [`../netcode/transport-websocket.md`](../netcode/transport-websocket.md) — the transport mechanism, BATCH coalescing, and the deferred datagram plan
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — the byte format this stream carries
- [`../netcode/latency-budget.md`](../netcode/latency-budget.md) — where queuing and RTT land in the budget
- [`../exec-plans/active/netcode-perf-fixes.md`](../exec-plans/active/netcode-perf-fixes.md) — the prioritized fix roadmap (transport change is the last item)
