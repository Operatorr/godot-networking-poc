# Send burst allowance — predeclared Strategy 150 comparison

**Completed:** [the single matched observation](send150.md) recorded zero game
zero-byte sends and zero UDP errors on both hosts. Offered/wire, population,
delivery, Tick and backlog gates passed. Strict AoI failed for 24 peers, so no new
capacity is validated. The predeclared plan below is retained unchanged as history.

[The optimized-generator cell](dodge150.md) supplied valid 30 Hz offered/wire input
for every peer. Population, Tick and delivery gates passed, but the game recorded
2,290 steady / 2,295 full-workload SndbufErrors matching nonempty zero-byte sends.
The pinned `rusty_enet 0.4.0` std socket adapter maps `WouldBlock` to `Ok(0)`;
other I/O errors remain errors. This identifies temporary send backpressure, not
the precise kernel queue or reason draining stalled. Receive/interface/qdisc drops
were zero. AoI/baseline correctness findings remain separate and unresolved.

The existing 395 sampled game socket rows have maximum `skmem.t` 258,304 bytes,
`tb` 524,288 and `w` zero. One-second sampling did not catch saturation; those
samples neither establish nor exclude a shorter send burst. No queue residence
or exact application delivery was measured.

## Ranked explanations

1. **Tick-sized bursts exhaust the send allowance.** Increasing only that allowance
   should eliminate or materially reduce zero sends/errors while maintaining
   valid input, per-peer delivery and stable backlog.
2. **Sustained output cannot drain fast enough.** More allowance should mainly delay
   errors or increase delivery age/backlog rather than produce a healthy full window.
3. **Host/driver/network-stack stalls interrupt draining.** Errors may persist with
   more allowance; existing CPU/steal/interface observations can narrow this but
   cannot identify a kernel stall without a later targeted diagnostic.

These explanations can coexist. One changed-buffer observation does not prove the
initial queue occupancy or exclude environmental variability. Do not call a larger
buffer a fix if it merely hides delivery delay.

## Candidate and local validation

Optional JSON `udp_send_buffer_bytes` independently requests SO_SNDBUF. Omission
keeps the prior ENet request; no default deployment configuration changes. Numeric
requests from 1 through 16,777,216 truncate toward zero; invalid requests warn and
preserve the prior value. Existing receive-option behavior, nonblocking send/receive,
ENet handling, simulation, replication and budgets are unchanged. Startup logs
requested and effective values in both directions.

The real ENet Host startup regression failed while the newly wired option was
ignored, then passed after native initialization applied it. It verifies the send
request, unchanged receive size and nonblocking reads. Configuration tests cover
invalid/oversized/string/null requests, truncation and independent receive settings.
Workspace tests, Clippy (two pre-existing bot.rs warnings), formatting and the client
extension release build pass. Against `f1cc5d6`, server production changes are only
configuration, argument wiring and native send-buffer initialization.

The API is documented by [socket2 0.6.4](https://docs.rs/socket2/0.6.4/socket2/struct.Socket.html#method.set_send_buffer_size).
Linux doubles SO_SNDBUF for bookkeeping and limits ordinary requests with
`wmem_max`; verify actual socket sizes instead of assuming them.
[Linux socket documentation](https://man7.org/linux/man-pages/man7/socket.7.html).
Context7 was unavailable; primary documentation and the pinned crate's local source
were consulted. No sysctl/kernel/network policy change is part of this experiment.

## Exactly one matched observation

Namespace **`udp-send150-20261021`**. The comparator is [dodge150](dodge150.md).
Build the exact candidate commit's **omega-server only** in separate matching
paths on both hosts, verify clean source/compiler/settings and identical hashes.
Keep the existing optimized bot unchanged:

```text
/home/deploy/omega-udp-dodge-2c25af7/rust/target/release/omega-load-test
73b957c7cb090ac8c433aa66dfba983ec8ad62305f527cab83be596dce524b1e
```

The private game configuration differs from comparator hash
`642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183`
only by **`udp_send_buffer_bytes: 2097152`**. Record the new exact hash. Expected
effective game receive/send sizes are **4,194,304 / 4,194,304**; receive request stays
2,097,152. Bot buffers stay 212,992 each. Verify all before launch and throughout.
The candidate binary exists only to expose this transport option; larger SO_SNDBUF
is the one intended workload intervention.

Keep Strategy 150, seed 30, difficulty 1, Class mix, 30 Hz input/Tick/Snapshot,
100 ms stagger, original AoI/LOD/budgets and 60 s warmup + 300 s measurement. All
[predeclared capacity and per-peer delivery gates](CAPACITY-150-PLAN.md) remain.
Report exact offered/wire, population/living, CPU/steal, Tick/deadlines, replication
backlog, per-peer delivery, send/receive/interface/qdisc errors, retry pressure,
sampled socket send/receive memory and error onset. Retain the unchanged strict
AoI assertion, baseline-reference/unknown-entity and oversized warnings. Passing
transport gates alone is not a capacity or bug-free certificate.

Collector/counting revision remains `994cce8`, with the same 600-second wrapper,
atomic schedules, byte-aware bounded journal and missing-owner analysis handling.
No profiler/tracer, collector semantics change, logging suppression, input pacing
change or next rung. Preserve 180/550/600/720-second ramp/workload/capture/restoration
bounds and all size/cgroup/identity/staleness/collapse guards. Original artifacts,
measurement files, namespace archives and closed campaign state must be preserved.

A separate agent owns the single experiment. Stop bots, verify exit and retain the
quiet tail before stopping game/captures. Restore original service/config/network/
maintenance and ordinary buffers, independently audit zero players/no owned
processes or timers, and verify bundle hashes against retained remote originals.
No rerun after failure. Return the complete result to the parent before any next
decision. Historical Strategy 100 remains highest validated until all gates pass.
