# Transport — WebSocket over TCP

**Status:** Superseded (historical — describes the retired WebSocket-era transport, last
verified 2026-06-04). The live transport is **ENet-over-UDP**, shipped with the Rust port:
see [ADR 0003](../adr/0003-enet-udp-transport.md) and
[`../rust-port/contract.md`](../rust-port/contract.md) for the channel plan as built. The
transport-abstraction seam (`Transport`, #12) survives on the client; `WebSocketTransport`
was replaced by `ENetTransport`. The analysis below (especially TCP head-of-line blocking)
is the *why* behind that swap.

> The wire *format* (header, quantization, delta masks, BATCH framing) lives in
> [`wire-protocol.md`](wire-protocol.md). This doc is the *transport* underneath it: how bytes
> actually move, when they move, and the one property that dominates behaviour under packet
> loss — **TCP head-of-line blocking**. The chosen transport is a known liability for a
> real-time shooter; see [ADR 0001](../adr/0001-websocket-tcp-transport.md) (the original WebSocket/TCP
> decision) and [ADR 0003](../adr/0003-enet-udp-transport.md) (which supersedes its substrate).

## What the transport is

A single **WebSocket connection per client, carried over TCP, used in both directions** —
client→server input and server→client Snapshots/Game events all share the same socket.
The same `NetworkManager` autoload runs both sides, mode-detected at startup
(`network_manager.gd:126`).

**Transport seam (#12).** `NetworkManager` no longer touches the socket directly — every raw socket
verb is delegated through a `Transport` interface (`client/autoload/transport/transport.gd`,
`class_name Transport`), whose default implementation is `WebSocketTransport`
(`websocket_transport.gd`, `class_name WebSocketTransport`). This is a pure refactor: **behaviour and
bytes on the wire are identical to before.** The seam exists so the eventual ENet-over-UDP transport
([ADR 0003](../adr/0003-enet-udp-transport.md)) is a `Transport` *subclass swap*, not a `NetworkManager`
rewrite — the entire layer above (`PacketWriter`/`PacketReader`, prediction, interpolation, the tick
loop) is transport-agnostic. The ENet implementation itself is **not built** (a deferred,
human-approved follow-up).

| Side | Setup | Evidence |
|------|-------|----------|
| Server | `TCPServer.listen(port)`, then per accepted stream `WebSocketPeer.new().accept_stream(peer)` | `network_manager.gd:144-145`, `:181-182` |
| Client | `WebSocketPeer.new().connect_to_url(url, TLSOptions.client())` | `network_manager.gd:295-298` |

There is exactly one socket per client. No second channel (no UDP side-channel, no datagram
fallback). Port defaults to `8080` from `ServerConfig` (`network_manager.gd:76`, `:141`).

## When bytes move — polled once per Frame, not per Tick

Both directions are pumped from `NetworkManager._process`, i.e. **once per render Frame**, not
on the server Tick (`network_manager.gd:167-171`). This is the load-bearing timing fact.

**Server poll** (`_process_server`, `network_manager.gd:174-219`), every Frame:
1. Accept one pending connection if available (`:179-185`).
2. For each peer: `ws_peer.poll()`, then **full-drain inbound** —
   `while get_available_packet_count() > 0: _handle_server_incoming_packet(...)` (`:200-202`).
   Every queued client packet is consumed in this Frame; nothing is left for next Frame.
3. Heartbeat-timeout sweep (`:213-219`).

**Client poll** (`_process_connected`, `network_manager.gd:230-264`), every Frame:
1. `ws_client.poll()` (`:235`).
2. **Full-drain inbound** — `while get_available_packet_count() > 0: _handle_incoming_packet()`
   (`:241-242`). BATCH frames are transparently unwrapped here (`:441`, `_dispatch_batch_buffer`).
3. Heartbeat send (1 Hz) and timeout check (`:245-255`).

The Tick loop (`server_main.gd:178-188`, 30 Hz) and the Snapshot cadence (30 Hz live, see
[`server-tick-broadcast.md`](server-tick-broadcast.md)) drive *when state is produced*; the
socket is only *serviced* on render Frames. On a headless server `_process` Frame rate is
uncapped, so polling is effectively continuous — but it is structurally Frame-driven, not
Tick-driven. **Planned:** poll on the Tick (or right before/after it) so inbound input is
drained at a known cadence relative to the simulation rather than at whatever Frame rate the
process happens to run.

## Egress shape — server BATCH coalescing vs client one-send-per-message

The two directions emit bytes very differently.

**Server → client: per-Tick coalescing into BATCH frames (TASK-066).** The Tick opens a
batching window (`server_main.gd:228`, `nm.begin_batch()`). Every `send_to_client` during the
Tick is *queued per-peer* instead of written (`network_manager.gd:527-531`). At end-of-Tick the
server flushes (`server_main.gd:259`, `flush_batches()`): each peer's queue is concatenated into
`[u8 BATCH][u16 len][u8 count][inner packets…]` envelopes (`network_manager.gd:614-628`) and sent
as few WebSocket frames as possible. A one-packet chunk is sent raw with no envelope
(`:607-610`). Chunks are capped by the `u8 count` field (≤255 inner packets,
`BATCH_MAX_PACKETS`) and the `u16` payload length (`BATCH_MAX_INNER_BYTES`,
`network_manager.gd:67-70`, `:570-573`).

Consequence: a Tick's Snapshot + Game events for a peer leave as **one (or few) WebSocket
frames at end-of-Tick**. This cuts per-message framing overhead, but adds up to a full Tick of
**server-side queuing latency** (~33 ms at 30 Hz) before anything in that Tick is written —
accounted as a stage in [`latency-budget.md`](latency-budget.md).

**Client → server: one `ws.send` per message, immediately.** No batching window exists on the
client. `send_message` encodes and writes straight away (`network_manager.gd:688-705`); input is
sent at 30 Hz from prediction (one `PLAYER_INPUT` per call). Heartbeats, auth, respawn, etc. are
likewise one-send-each.

## What is *not* tuned

Godot/OS defaults are used throughout. None of the usual real-time socket knobs are set:

| Knob | State | Note |
|------|-------|------|
| `inbound_buffer_size` / `outbound_buffer_size` | default | not set on `WebSocketPeer` either side |
| `max_queued_packets` | default | not set |
| TCP `NODELAY` (disable Nagle) | not set | small frames may be Nagle-delayed under TCP defaults |
| Send backpressure | none | client `send()` and server `_send_raw_to_peer` log on `error != OK` but **do not** treat a non-`OK` return as backpressure / queue-full and retry or shed (`network_manager.gd:642-652`, `:697-705`) |

**Planned:** buffer sizing (`inbound/outbound_buffer_size`, `max_queued_packets`) tuned for the
target peer count, and treating `send() != OK` as backpressure (drop/coalesce or apply
per-client rate budget) instead of a logged no-op.

## The key limitation — TCP head-of-line blocking

This is why the transport choice matters and why it is flagged for replacement.

TCP guarantees **in-order, reliable** delivery of a single byte stream. The WebSocket carries
Snapshots, Game events, and heartbeats interleaved on that one stream. When a single TCP segment
is lost, the kernel **holds back every later segment** — already-arrived bytes included — until
the lost one is retransmitted (one RTT minimum). For this game that means:

- A dropped segment **freezes all incoming state** — every Remote entity stops updating, not
  just the entity in the lost packet — until retransmit completes.
- Because Snapshots are *continuous state* (the next one fully supersedes the last), reliable
  in-order delivery of stale Snapshots is exactly the wrong trade: a real-time transport would
  rather **drop the stale one and deliver the newest**. TCP cannot.
- Under loss, latency spikes by ≥1 RTT and the [Render delay](../CONTEXT.md) buffer (5 slots,
  ~166 ms) can drain, exposing extrapolation freeze (see [`interpolation.md`](interpolation.md)).

There is no application-level mitigation in code today — no out-of-band heartbeat channel, no
selective drop. The fix is a transport change, deliberately deferred (below).

## Deferred: ENet over UDP

An unreliable/unordered datagram transport would let Snapshots be sent **unreliable + unsequenced**
(drop the stale, keep the newest) while reliable Game events / auth ride a separate reliable,
ordered channel — eliminating head-of-line blocking for state. The chosen target is **ENet-over-UDP**
via Godot's built-in `ENetConnection` with raw channels (ch0 unreliable for `STATE_UPDATE` +
`PLAYER_INPUT`, ch1 reliable for everything else), keeping the existing `PacketWriter`/`PacketReader`
binary protocol on top.

This **supersedes** the earlier WebRTC/WebTransport plan: the game is **native-only** (no browser
client), so browser reach — the sole reason ADR 0001 rejected ENet and preferred WebRTC — no longer
applies, and the server's planned Rust port can reuse the **wire-compatible** `rusty_enet`. ENet is
also built into Godot 4.6 with no extra plugin or signalling/ICE/DTLS dance. The transport **seam** is
built (above); the ENet `Transport` subclass is **deferred** (human-approved follow-up). Full
rationale and trade-offs in [ADR 0003](../adr/0003-enet-udp-transport.md).

## Planned work (summary)

| Item | Why | Status |
|------|-----|--------|
| Transport-abstraction seam | make the datagram swap a subclass, not a rewrite | ✅ done (#12) |
| Poll on the Tick (not every Frame) | drain input at a known cadence vs the 30 Hz sim | planned |
| Buffer sizing — `inbound/outbound_buffer_size`, `max_queued_packets` | survive 500–1000 peers without silent default limits | planned |
| `send() != OK` as backpressure | drop/coalesce or rate-budget instead of logged no-op | planned |
| ENet-over-UDP `Transport` impl behind the seam | kill TCP head-of-line blocking for Snapshots | deferred ([ADR 0003](../adr/0003-enet-udp-transport.md)) |

## The eight questions

- **Client:** opens one WS-over-TCP socket; polls + full-drains inbound every Frame; sends one
  `ws.send` per message.
- **Server:** `TCPServer` + per-peer `WebSocketPeer`; polls + full-drains every Frame; coalesces a
  Tick's egress into BATCH frames flushed at end-of-Tick.
- **Predicted:** nothing — transport moves bytes, prediction lives in
  [`client-prediction.md`](client-prediction.md).
- **Replicated:** all Snapshots and Game events travel this single ordered stream.
- **Persisted:** nothing — transport is in-memory sockets; persistence is the Go API's job.
- **Validated:** packet size ≥ `HEADER_SIZE` before decode (`network_manager.gd:436`, `:917`);
  invalid `type` rejected; BATCH envelopes bounds-checked (`:458-474`). No auth at transport
  layer (that's the `CONNECT_AUTH` message).
- **Can fail:** one lost TCP segment freezes **all** state (head-of-line blocking) — the motivation for
  the deferred ENet swap behind the seam; `send() != OK` is logged but not handled as backpressure; no
  buffer caps tuned for scale.
- **Tested:** load-test bots open real WS connections (`load_testing/`); no automated test today
  injects packet loss to exercise head-of-line behaviour.

## See also

- [`../adr/0001-websocket-tcp-transport.md`](../adr/0001-websocket-tcp-transport.md) — why TCP now, datagram later
- [`../adr/0003-enet-udp-transport.md`](../adr/0003-enet-udp-transport.md) — the ENet-over-UDP target + the transport seam that lands first
- [`wire-protocol.md`](wire-protocol.md) — header, quantization, delta masks, BATCH format
- [`server-tick-broadcast.md`](server-tick-broadcast.md) — what produces the bytes this carries
- [`latency-budget.md`](latency-budget.md) — where end-of-Tick queuing and RTT land in the budget
- [`interpolation.md`](interpolation.md) — what a loss-induced freeze does to Remote entities
