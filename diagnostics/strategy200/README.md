# Strategy200 polling prerequisite — rejected diagnostic

This is an isolated, **unqualified** experiment for
[Establish valid Strategy overload measurement without bot-host loss](https://github.com/Operatorr/godot-networking-poc/issues/46).
The author approved the [bounded plan](https://github.com/Operatorr/godot-networking-poc/issues/46#issuecomment-6493273227).
Its local event-preservation prerequisite failed, so preparation stopped before
observer timings or remote access. Do not deploy this scheduler.

The source materializer reads revision
`a1abdf8c9ada3efc164d4225de8c0ecf3f5c75bf` through `git show`. It builds a separate
three-crate workspace inside ignored `.prepared/`; production Rust files and
historical evidence are untouched. The only scheduler intervention limits each
bot to 32 delivered ENet events per poll. Socket buffers, protocol, per-bot seed,
AI, input schedule and native ENet implementation are unchanged.

Both reference and candidate receive the same constructor seam for public ENet
Socket/time injection. The replay uses actual pinned Bot decoding/handling,
Strategy AI, movement, input encoding and unmodified rusty_enet 0.4.0 over
in-memory sockets and a virtual clock. Harness-only traces are compiled out of
the ordinary executable. The candidate's sweep observer is separate from the
rejected Idle150 observer; neither was qualified for remote use here.

In a fresh checkout containing the pinned revision:

```sh
python3 diagnostics/strategy200/prepare.py
cargo build --manifest-path diagnostics/strategy200/.prepared/rust/Cargo.toml \
  --release --features synthetic-replay --bin poll-replay
diagnostics/strategy200/.prepared/rust/target/release/poll-replay parity
```

The last command intentionally **exits 101** on `LateBurst`. The reference handles
all 512 reliable events arriving at virtual 10,999 ms; the candidate handles 32.
At 11,000 ms, the existing disconnect call resets ENet's pending dispatch queues,
losing the candidate's remaining 480 events. This is a defect in the proposed
diagnostic condition, not attribution of the historical production failure.

`prepare.py` refuses to overwrite a prepared directory. It includes frozen
protocol integration-test collector sources and narrows only workspace members;
its generated code is formatted before compilation. Exact final generated source
changes, original blob hashes, executable identity, raw outputs, independent
codec/count checks and post-stop immutability proof live in the
[report directory](../../docs/netcode/perf-notes/load-test-reports/2026-10-29-strategy200-overload/REPORT.md).

The unexecuted `timing FRESH_DIRECTORY` command implements the proposed five
alternating observer pairs with 200 virtual bots and actual ordinary recorder
serialization. **It was not run.** No overhead, remote observer cost, memory/output
qualification, new workload gate, capacity or host-release result is claimed.
The standalone suite also exposed a native-mode CLI regression: the new guard
rejects the native observer that the retained historical terminal test requests.
That failed test is retained as a limitation; it was not skipped or called passing.

This batch ended at its stop rule. A new scheduler design or experiment requires
a new reviewed plan; these reproduction instructions do not authorize one.
