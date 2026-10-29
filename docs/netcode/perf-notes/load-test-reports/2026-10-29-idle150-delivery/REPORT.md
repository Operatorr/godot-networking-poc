# Idle150 delivery diagnosis — bounded inconclusive result

**Stopped before remote access.** The diagnostic observer passed seven local
parity/accounting cases but failed the approved five-pair overhead prerequisite:
**+5.549604164% elapsed time against a <=2% limit**. The approved plan says a
failure ends preparation without a remote launch. No retry or subsequent
observer optimization was performed.

This resolves [Diagnose Idle150 offered-to-wire delivery deficit](https://github.com/Operatorr/godot-networking-poc/issues/45)
as a **bounded inconclusive investigation**, not a causal attribution. Ordinary
Idle150's historical cause and actual application-delivered input counts remain
unknown. No clean-cell pass, server-capacity result or game-code defect follows.

## Approved scope and execution accounting

The author approved the [published plan](https://github.com/Operatorr/godot-networking-poc/issues/45#issuecomment-6491312527)
in the working session; its [approval record](https://github.com/Operatorr/godot-networking-poc/issues/45#issuecomment-6491479793)
starts the four-hour preparation allowance at 2026-10-29 08:11:14 UTC. The
preparation result was recorded at 08:19:54 UTC, within that allowance.

Remote commands: **0**. Remote attempt slots consumed: **0/2**. Workloads: **0**.
The 90-minute remote batch clock never started. No host access, build, staging,
service change, restoration, release audit, buffer tuning or provisioning was
performed remotely; no fresh host state is claimed. No runtime bot or remote
controller was prepared after the failed prerequisite.

All 36 original acceptance predicates remain unchanged. They were **not
evaluated for a new workload**; the new steady-window result is null, not 0/36
or a pass. Historical reports, classifications, captures and archives were not
rewritten. The user's pre-existing evidence-audit directory was left untouched.

## Original evidence retained

Offline inspection verified the four ordinary R2/native R5 workload-archive
hashes against their reports and recomputed offered/capture counters directly
from archive members without extracting over previous evidence.

| Ordinary R2 observation | Original counter |
|---|---:|
| Actual recorder interval | 300.012041993 monotonic seconds |
| Queue admissions between those recorder boundaries | 1,349,614 |
| Offered rate | 29.982129851341–29.995462649496 Hz; 0/150 below 29.7 |
| Input commands in scheduled 300 s, bot capture | 1,326,805 |
| Input commands in scheduled 300 s, game capture | 1,326,811 |
| Wire rate on either capture | 28.08–29.953333333333 Hz; 113/150 below 29.7 |
| Original gate flags | 35/36 true; wire cadence false |
| Ordinary recorder completed sections | 1,533,812,553 ns, 377 completed samples |

Recorder and wire windows differ. Their subtraction is not an exact packet-loss
count. Eight peers have a one-command capture difference, net six more game
commands; matching range and failure count do not mean identical per-peer data.
See [ordinary R2](https://github.com/Operatorr/godot-networking-poc/blob/fcf4f62/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs/clean-idle150-r2-20261023.md).

Native R5's archived drained counters balance 1,644,645 admissions/retirements as
1,619,035 full Socket handoffs plus 25,610 no-attempt retirements, with zero
pending work. Its offered gate fails for 48 peers and wire gate for all 150.
Measured native sections total 70,153,372,362 ns, not total causal overhead.
The raw pre-only witness counter is 25,460; the retained independent trace
assessment qualifies 25,187 stable throttle witnesses, leaving 273 changed-
throttle and 150 teardown cases ambiguous. These counts are distinct. See
[native R5](https://github.com/Operatorr/godot-networking-poc/blob/fcf4f62/docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs/clean-idle150-audit-r5-20261023.md).

The mechanisms remain distinguishable in principle: `Peer::send` admits queued
work; ENet can drop it at its adaptive throttle branch; the UDP adapter can return
zero for WouldBlock; reset can destroy queued work. None of those facts identifies
which inputs were missing in ordinary R2. ENet documents its adaptive unreliable
shedding in the [pinned Peer API](https://docs.rs/rusty_enet/0.4.0/rusty_enet/struct.Peer.html#method.set_throttle).

## Local parity and accounting

The isolated [observer and harness](../../../../../diagnostics/idle150/README.md)
retain upstream 0.4.0 and compare it to the diagnostic fork with counters off
and on. Every tested wire byte, native send result, received event and virtual
timestamp matched exactly across the three variants. Every supported input
balanced admission against pending work and dispositions, with no unknowns or
accounting errors. Input u8 sequences wrap repeatedly.

| In-memory condition | Admitted | Full handoff | Other observed disposition |
|---|---:|---:|---|
| Stable delay | 10,700 | 10,700 | None |
| Varying delay, default throttle | 10,700 | 10,699 | 1 throttle retirement |
| Three inputs per datagram | 32,100 | 32,100 | None |
| One zero-byte datagram send | 32,100 | 32,097 | 3 zero-byte dispositions |
| One partial datagram send | 32,100 | 32,097 | 3 partial dispositions |
| One error datagram send | 32,100 | 32,097 | 3 error dispositions |
| Reset with three queued inputs | 7,806 | 7,803 | 3 reset retirements |

All final pending counts are zero. This is a deterministic transport-semantic
feedback loop, not a reproduction of the ordinary remote deficit's magnitude.
Raw output: [parity.json](parity.json).

## Preregistered observer-cost result

Release build, one local macOS ARM64 environment. Five alternating-order pairs,
25 virtual 361-second replays per arm, exactly one assessment. The comparison
uses the same diagnostic executable with only the observer enabled/disabled.

| Pair | Order | Disabled ns | Enabled ns | Added elapsed time |
|---|---|---:|---:|---:|
| 1 | off/on | 551,984,375 | 577,200,250 | +4.5682% |
| 2 | on/off | 549,056,334 | 576,236,791 | +4.9504% |
| 3 | off/on | 546,519,542 | 597,047,375 | +9.2454% |
| 4 | on/off | 556,142,916 | 577,693,500 | +3.8750% |
| 5 | off/on | 546,266,209 | 574,403,875 | +5.1509% |
| Total | | **2,749,969,376** | **2,902,581,791** | **+5.5496%** |

Derivation: `(2,902,581,791 / 2,749,969,376 - 1) * 100`.
The aggregate exceeds 2%, and every individual pair exceeds 2%. The timing
executable exits 1, retained in [timing-execution.json](timing-execution.json).
No measurements were discarded or substituted. See [all pairs](timing.json)
and [environment/binary identity](environment.json).

This measures whole-replay elapsed time on this machine. It is not remote bot
CPU overhead, an estimate of causal slowdown in the previous campaign, or a
test of remote offered cadence. Fixed observer state would be 112 bytes per
single-peer Host (16,800 bytes for 150); memory success does not override timing
failure. No deployed recorder's complete cost or the remote 1.5 CPU-second guard
was measured. The hooks' own timer excludes entry clock reads, final timer
bookkeeping, disabled branches, layout/cache effects and snapshot/serialization;
its counters must not be labelled total causal overhead.

## Evidence identities and boundary of the result

[experiment-source-sha256.json](experiment-source-sha256.json) freezes all 37
pre-execution package files, including dependency lock and observer source. Every
listed file was verified unchanged after the timing failure. Later README/report
files are additive documentation, outside that frozen experiment manifest.
[outcome.json](outcome.json) records the unchanged limit, failed gate, zero remote
actions and null workload observations. The private evidence directory retains
both stdout/stderr files, exclusive reservation records and execution timestamps.

The standalone package's formatter check passes. Compilation retained four
warnings from unchanged upstream compression/signature code. The staged
whitespace audit flags the frozen Cargo manifest's final blank line, unified
patch context spaces and an upstream Markdown hard line break. Those bytes were
retained to preserve the measured source identity; the whitespace audit is not
reported as passing. Production workspace files were not changed or retested.

The local observer can distinguish the tested retirement mechanisms but does
not satisfy this plan's admission budget. Per the approved stop rule, the
investigation ends with the ordinary deficit unresolved. Further optimization,
a different cost observer, a revised budget or any remote attempt requires a
new reviewed plan; none is launched, scheduled or implied by this closure.
