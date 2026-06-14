# Transport: WebSocket / TCP — retired (redirect)

**Status: Retired.** Superseded by ENet/UDP with three channels
([ADR 0003 — ENet/UDP transport](../adr/0003-enet-udp-transport.md)).

The WebSocket-over-TCP transport and its BATCH coalescing / polling-cadence
machinery described here were removed during the Rust port. The
head-of-line-blocking analysis that *motivated* the switch is preserved in
[ADR 0001 — WebSocket/TCP transport](../adr/0001-websocket-tcp-transport.md).

The **live transport** (ENet channels: ch0 snapshots/confirms, ch1 reliable,
ch2 input; native keepalive/RTT) is documented in:

→ **[`../server/contract.md`](../server/contract.md)** (channel plan).

This stub is kept only so historical links from the ADRs and exec-plans resolve.
