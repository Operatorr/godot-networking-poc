# CAX11 single-run diagnosis and stabilization

Current execution task: [Execute the revised one-pass CAX11 load-test matrix](https://github.com/Operatorr/godot-networking-poc/issues/35).
[Run the new load tests and record results](https://github.com/Operatorr/godot-networking-poc/issues/31)
retains the preparation/diagnosis history and final audit. The new task has a fresh handoff;
creating it does not mean the remaining tests have run.

**Status: corrected 50-bot clustered pilot passed operational checks, including warmup. The full matrix is held for checklist/time-estimate review.**

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
baseline-reference misses. The subsequent transport diagnostic is recorded below.

The game socket's effective receive/send limits were both 212,992 bytes. The pinned
`rusty_enet` 0.4 standard `UdpSocket` adapter sets nonblocking/broadcast options but
ignores ENet's requested 256 KiB buffers. A candidate server transport adapter applies
those requested sizes with `socket2`, logs the effective sizes and preserves the
existing nonblocking I/O behavior. Linux's returned buffer sizes include its bookkeeping
allowance; record the actual values rather than assuming requested equals effective.

The two transport regression tests failed with the original initialization delegation
and passed after applying the options. Workspace tests (203 tests), Clippy and formatting
passed; Clippy retains two existing `collapsible_match` warnings in the unchanged bot.
The remote five-minute workload validated the requested buffers and recorded zero kernel errors, including warmup.
Its game build is revision `77a8af53d947a41106b0cc3b44a9c340145bd9f1`, ordinary locked
Arm release with Rust 1.95.0. SHA-256:
`ae7f7afc130ad647dbd3bd917f91e60d5b16e650f123bdd5d35e0d4d9b36b021`.
The unchanged bot remains at measurement revision `642c147` and its previously recorded
hash. Both source checkouts are recorded separately in each pilot's provenance.


The [transport diagnostic](pilot-clustered-50-after/steady.json) held all 50 bots at
30 Ticks/s, with Tick work p99 7.852 ms and zero application send/decode or kernel UDP
errors. Effective receive/send buffers were 524,288 bytes each. Endpoint packet matching
found no unmatched packets. Local analysis peaked at 583,270,400 bytes RSS and the whole
pilot took 676.45 seconds. Seven unknown-entity partial deltas and five enqueued Snapshots
absent from observed first transmission remain; this is not yet a clean delivery pilot.
The legacy aspirational bandwidth assertion also fails; this diagnosis does not optimize
bandwidth to satisfy it.

Two regression tests reproduced a baseline-cache inconsistency: receiving a Baseline
replaces the receiver's entity model, but the server retained cached entities omitted
by visibility or the Baseline cap. Their re-entry could emit a partial delta without a
known entity. Clearing the cache when creating the replacement Baseline makes both tests
pass. This is a separately recorded correctness fix; a new remote pilot must establish
whether it removes the observed anomalies. All 205 workspace tests, Clippy and formatting
pass (the same two existing bot warnings remain).

A third regression test reproduces loss of the first unreliable FULL record for a new
entity. The next Snapshot previously contained position only, although the receiver had
never learned animation/flags. New entities now retain FULL records until a reliable
Baseline includes them; existing Baseline entities retain their normal partial masks.
The test fails before this correction and passes after it, including the return to partial
updates after a Baseline. This is a correctness/transfer trade-off, not an optimization;
record its bandwidth separately. All 206 workspace tests, Clippy and formatting pass.
The follow-up remote diagnostic passed; details follow below.

The [cache-fix pilot](pilot-clustered-50-baseline-cache/steady.json), game revision
`a8fb109`, completed with zero unknown-entity partial deltas and zero baseline-reference
misses during measurement, Tick cadence 30 Hz and p99 work 7.975 ms. The generator and
collection remained valid with no kernel errors. Whole-run cumulative delivery checks
still recorded 1,915 unknown-entity observations before the scored window. The
[separate whole-run replay](pilot-clustered-50-baseline-cache/whole-run-checks-replay.json)
makes that warmup fault explicit. No run is overwritten; keep the diagnostic revisions separate when selecting current matrix evidence. Follow-up revision `b1266c1` applies first-record recovery;
its remote five-minute diagnostic passed; details follow below.

## Completed corrected pilot

[The recovery pilot](pilot-clustered-50-recovery/steady.json), game `b1266c1` and unchanged
bot `642c147`, held all 50 bots for 300 measured seconds with valid generation/collection,
30 Ticks/s, p99 work 7.951 ms, max 14.370 ms and no work-deadline exceedances. Whole-run
checks include warmup: zero kernel UDP, application send/decode, panic, unknown-entity
and baseline-reference errors. Dedicated tracing saw zero socket queue/drop events.
This passes [the single-run operational checks](single-run-validation.json), not a
complete-matrix claim. The user amended the matrix to one run per test on 2026-10-14. The legacy bandwidth target still fails.

Game outbound IP traffic averaged 1,239,239.707 bytes/s (371,771,912 bytes in the window).
Twenty-three enqueued Snapshots were absent from first observed wire transmissions;
retain this source/ENet observation separately from network loss. No unknown-entity
errors or reference misses resulted. Endpoint matching observed zero unmatched outbound
packets and two unmatched inbound packets out of 1,000,547 (0.00020%); this is not a
perfect-delivery claim. The conservative new-entity FULL recovery changes
transfer, so this build is a separate baseline; do not mix its repeats with earlier builds.

The controller took 637.81 s (10 min 38 s), including 58.48 s of analysis, with peak local
RSS 580,648,960 bytes. All raw archives are checksummed and copied off the temporary
hosts. [Pilot comparison CSV](pilot-comparison.csv), [fixes and open checks](fixes-and-open-checks.md)
and [full run checklist and estimate](run-checklist.md) preserve the scope and next gates.
The user amended the matrix on 2026-10-14 to one run per test. The 50/100 checkpoint is
now eight cases (40 measured minutes). The revised ladder has all four workloads at
50/100/150 and Strategy alone at 200/250/500/750/999: 17 core cases (85 measured minutes).
The complete all-ladders-pass plan has up to 88
scored windows including explicit control positions. The previous three-repeat estimates
are superseded by the linked checklist. Higher-population costs remain unmeasured;
update estimates and storage at checkpoints. The full controller has not restarted;
historical reports and CCX13 remain deferred.

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

The controller now detects the first failed join from the complete ramp log, even when
later success lines push the warning outside the five-line tail. It stops further joins,
labels the attempt unscored, preserves both endpoint archives, and gives the swarm a
finite service lifetime. Eight Python tests pass, including full abort/cleanup fixtures
and a successful-ramp status check. The completed remote pilot's logs also pass the
read-only probe. [Controller failure validation](controller-failure-validation.json).

These changes do not shorten the five-minute scored window or discard failed evidence.
The completed pilot took 713.85 seconds overall, including 52.34 seconds of analysis.
The slower endpoint spent 24.27 seconds archiving and 219.11 seconds downloading and
checking SHA-256. Peak local analysis RSS was 2,918,858,752 bytes. Full-campaign planning
must address the analyzer's unbounded packet-context storage before scaling populations.
The revised analyzer stores packet matching and exact delay quantiles in a temporary
disk database, limits retry history to its actual classification window and stops
accumulating an unsupported outstanding queue on egress-only mirrors. A replay of the
unaltered pilot archives used 542,998,528 bytes peak RSS and 56.79 seconds. Every prior
metric matched within 1e-12 floating tolerance except the intentional correction of
four mirror outstanding fields to unavailable. Bidirectional endpoint ACK accounting,
traffic, retries, loss, classifications and original evidence were unchanged.
[Replay validation](packet-analysis-validation.json) and five focused regression tests
cover duplicates, clock margins, late arrivals, unsigned fingerprints, ACK scope and
temporary-file cleanup. Larger-population resource demand is still unmeasured.
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

The independent [provider network screenshot](provider-network-20261014.png), supplied
at 10:56 Taipei, shows yellow outbound around 1.1 MBps (roughly 1.0–1.2) during the 10:29–10:34 scored
window. Guest game IP traffic averaged 1.132 decimal MB/s (1.080 MiB/s, 9.056 Mbit/s);
whole-interface TX averaged 1.158 decimal MB/s. Packet rates broadly agree too. These are
approximate chart readings, without verified chart smoothing or unit base. Hetzner's
network graph is fetched from the physical host and independently sees this same-zone
load; its billable allowance meter is a separate measurement. Outbound continuing after
the workload includes evidence downloads. [Comparison data](provider-network-comparison.json)
and [provider graph documentation](https://docs.hetzner.com/cloud/servers/faq/).
