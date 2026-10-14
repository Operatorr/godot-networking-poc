# CAX11 single-run diagnosis and stabilization

**Status: failure reproduced; candidate transport fix awaiting remote validation. The full matrix is held.**

On 2026-10-14 the user requested one smooth run and reproducible bug fixes before the
full rundown, followed by a run checklist and time estimate. The earlier
[baseline campaign](../2026-10-13/README.md), including failed and invalid observations,
remains preserved. This work uses the same separate CAX11 hosts, unsigned no-API dev
mode, native network and 50-bot clustered workload. Any transport fix is a separate
build; it must not be presented as the untouched baseline.

## Reproduction and candidate fix

The original clustered repeats recorded game UDP receive-buffer drops during their
five-minute windows. A fresh diagnostic with the same measurement binary and OS
buffer defaults caught 17 UDP 8081 queue failures during warmup. Matching trace events
report `SOCKET_RCVBUFF` at `__udp_queue_rcv_skb`, with return code -12. The trace uses
its own tracefs instance and monotonic clock; raw addresses stay in the private evidence.
The [completed diagnostic](pilot-clustered-50-before/steady.json) was a valid failing
observation: the scored window recorded 86 game-host send-buffer errors and no
receive-buffer errors; the receive failures occurred earlier during warmup. All
450,000 scheduled Snapshots were enqueued, with 87 absent from observed first
transmissions. The run retained 72 unknown-entity delta observations and zero
baseline-reference misses. No transport fix has yet been validated remotely.

The game socket's effective receive/send limits were both 212,992 bytes. The pinned
`rusty_enet` 0.4 standard `UdpSocket` adapter sets nonblocking/broadcast options but
ignores ENet's requested 256 KiB buffers. A candidate server transport adapter applies
those requested sizes with `socket2`, logs the effective sizes and preserves the
existing nonblocking I/O behavior. Linux's returned buffer sizes include its bookkeeping
allowance; record the actual values rather than assuming requested equals effective.

The two transport regression tests failed with the original initialization delegation
and passed after applying the options. Workspace tests (203 tests), Clippy and formatting
passed; Clippy retains two existing `collapsible_match` warnings in the unchanged bot.
The candidate is not yet validated by the remote five-minute workload.

## Collection and execution fixes

- Reuse authenticated SSH connections instead of establishing a new connection for
  each status poll and command. The fresh pilot's setup, ramp and global warmup took
  88.1 seconds, versus approximately 150–186 seconds in the prior completed cells.
- Archive/download independent endpoints concurrently after the workload ends.
  Preserve per-endpoint stage timings and errors, and attempt cleanup on both endpoints
  even when one archive fails. The injected archive-failure check verified both endpoint
  cleanups, the surviving download and error-manifest retention.
- Hash archives incrementally; avoid allocating an entire archive for each SHA-256 pass.
- Prevent the full matrix controller from restarting while the user's hold is active.

These changes do not shorten the five-minute scored window or discard failed evidence.
The completed pilot took 713.85 seconds overall, including 52.34 seconds of analysis.
The slower endpoint spent 24.27 seconds archiving and 219.11 seconds downloading and
checking SHA-256. Peak local analysis RSS was 2,918,858,752 bytes. Full-campaign planning
must address the analyzer's unbounded packet-context storage before scaling populations.
Before announcing a successful pilot, verify joins/connections, actual per-bot input rate,
clean collection, transport/codec errors across warmup and measurement, Tick cadence/work,
lag/backlog and delivery recovery. The final run checklist and estimate follow that gate.

## Provider meter and measured traffic

Falkenstein and Helsinki both belong to `eu-central`. Hetzner exempts Cloud-to-Cloud
traffic in the same network zone even over public IPs; moving the bot to Helsinki would
not make it consume the billable outgoing allowance. A non-Hetzner client or a Cloud host
in another network zone is needed for that meter check. Evidence downloads to the operator
are external egress too. [Locations](https://docs.hetzner.com/cloud/general/locations/),
[billing rules](https://docs.hetzner.com/cloud/billing/faq/).

At 2026-10-14 01:42:49 UTC the user reported game `0.00177221 TB` and bot `0.00178569 TB`.
Under the conditional decimal interpretation those are 1.77221 and 1.78569 GB.
The nine selected completed same-zone measurement windows then totaled 2.36945 GB
game outbound and 0.52280 GB bot outbound. The separate external-client check measured
4.845 MB game outbound. Retained downloaded archive payloads totaled 1.88768/1.90806 GB
from game/bot hosts. These differently scoped totals are consistent with external archive
downloads contributing to the provider reading and same-zone game traffic being exempt;
they are not exact invoice reconciliation. Reporting delay, exact account units and
transport overhead remain unresolved. [Timestamped snapshot](provider-reconciliation-snapshot.json).
