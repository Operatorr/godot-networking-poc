# Candidate: isolate game receive-queue burst capacity

This is prepared code and a proposed discriminating condition, **not an observed
improvement**. The native-buffer observation with the repaired collector must
finish and verify cleanup before the next remote run is selected.

## Prediction and competing outcomes

Initial game-socket overflow occurs while observed maximum read gaps are around
26–29 ms, before the much larger late service/read stalls. The
[reliable-event analysis](RELIABLE-PRESSURE.md) also shows high reliable command
fan-out before overflow. The working hypothesis is that finite receive capacity
loses ACK/input bursts during serial processing, then reliable retries amplify
transport work and extend read gaps.

A later one-factor condition can request **2,097,152 game receive bytes**, versus
ENet's ordinary 262,144-byte request, while retaining the exact bot executable,
collector version, send buffer, workload and other configuration. Effective size
must be observed, not assumed from the request; record kernel limits and any
clamping. No persistent kernel tuning is proposed. The only config difference
must be this receive request and must be restored and hash-verified afterward.

- Later/fewer initial drops **and** healthy sustained delivery/Tick cadence support
  burst capacity as a useful intervention.
- Fewer drops with growing queues/application ages or missed Tick deadlines means
  the larger queue is masking a throughput problem, not increasing valid capacity.
- Similar onset/read gaps despite a verified larger effective queue weakens this
  burst-capacity explanation; inspect packet bursts/ACK processing next.
- Bot-side overflow or invalid per-bot offered/delivered cadence remains a separate
  limiting factor. A successful ramp is not the 60 s + 300 s capacity gate.

## Implementation and validation

Optional JSON `udp_receive_buffer_bytes` feeds only the game socket's receive
request during ENet initialization. Omission preserves the existing ENet request;
invalid/out-of-range values warn and retain the prior value. Numeric JSON uses the
repository's truncate-toward-zero convention within 1–16,777,216 bytes. Send-buffer
initialization and nonblocking datagram I/O remain the same. Startup logs expose
both requested and effective sizes.

The implementation uses the existing socket2 0.6.4
[`set_recv_buffer_size`](https://docs.rs/socket2/0.6.4/socket2/struct.Socket.html#method.set_recv_buffer_size)
API. Context7 is unavailable in this session; pinned crate source and official
crate documentation were used instead. No dependency update is involved.

A real `Host::new` socket test verifies that an override survives ENet startup,
changes only the receive size, and leaves an empty receive nonblocking. Config
coverage exercises omission, numeric input, invalid types/ranges and retaining a
previous valid setting. Existing socket/datagram tests still pass.

`cargo test --workspace`, `cargo clippy --workspace --all-targets`, and
`cargo fmt --check` pass; existing Clippy warnings remain. The client extension
rebuild also passes with the existing macOS 26.2 SDK selected for that command.
No deployed config or remote executable has been changed by this preparation.
