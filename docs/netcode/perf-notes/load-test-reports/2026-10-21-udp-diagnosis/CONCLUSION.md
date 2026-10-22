# CAX11 UDP investigation — correctness plateau

[Diagnose UDP receive-buffer errors and increase validated CAX11 capacity](https://github.com/Operatorr/godot-networking-poc/issues/38)
concludes with demonstrated generator and transport improvements, but **no new
validated capacity**. Historical Strategy **100** remains the highest passing
population. The final Strategy 150 observation passed offered/wire load,
population, delivery, Tick, backlog and UDP-error gates; strict AoI failed for
24 peers. That is a valid failure, not a 150-player capacity certificate.

This is the issue's permitted plateau resolution: a different limiting gate now
needs focused correctness work. It does not complete the original capacity goal,
the unfinished test matrix, or the article's bug-free-results requirement.

## What the evidence establishes

1. **The reproduced receive errors were socket queue drops.** The original
   Strategy 200 reproduction stopped after 38.05 seconds at 189 authenticated
   players. All 172,927 game receive-buffer errors matched the game's socket drop
   counter. Interface/qdisc/checksum deltas were zero. Generator drops also
   occurred, with most attributable to bot sockets. Original ramp cadence was
   unavailable; no generator-valid baseline capacity follows.
   [Baseline evidence](baseline-reproduction.md).
2. **Read delays and reliable work grew during the failure.** The instrumented
   control observed initial read gaps around 26 ms and a later maximum of 443 ms.
   Retry-command bytes grew from 132,337 to 13,688,810 across equal nine-second
   windows; reliable-command removal became the dominant sampled game self cost.
   This supports amplification after overflow. It does not prove the initiating
   processing cause or the causal cost of collection.
   [Timing control](instrumented-control.md), [CPU profile](profile-reproduction.md).
3. **A larger receive allowance delayed loss but did not sustain 200.** A 2 MiB
   request produced an effective 4 MiB receive buffer, reached all 200 players,
   then collapsed with 159,266 game socket drops. A pre-swarm measurement panic
   and restart qualify runtime identity proof for that cell. The controller's
   atomic-publication repair was validated in later cells. This observation is
   burst-absorption evidence, not a throughput or capacity fix.
   [Receive comparison](receive-buffer.md).
4. **The generator had a separate sustained CPU limit that was improved.** At
   150, the original Strategy bot offered about 18.34 Hz at 97.71% of one logical
   CPU. Profiling identified substantial Strategy work. Searching the smaller
   visible-entity map when appropriate, with the original owner-order fallback
   for ties, restored every bot to 29.993–30.000 Hz offered and 29.843–29.997 Hz
   wire input. Generator CPU was 78.30%. Gameplay, nearest-choice semantics and
   requested cadence were preserved. Remote map occupancy remains unmeasured.
   [Generator comparison](dodge150.md), [candidate and regressions](DODGE-CANDIDATE.md).
5. **A larger send allowance removed observed backpressure at valid load.** With
   the optimized bot and receive request frozen, a 2 MiB game send request
   produced an effective 4 MiB send buffer. Game SndbufErrors/nonempty zero-byte
   sends changed from 2,290 steady / 2,295 full workload to zero. Both hosts had
   zero UDP error deltas. All 150 stayed authenticated for 300 seconds after
   60-second warmup; Tick rate was 30.0 Hz, p99 work 27.182 ms, every peer passed
   delivery, and backlog guards passed. This supports the predeclared burst
   allowance intervention. Sampled memory did not catch saturation, so the exact
   kernel queue/cause and queue residence remain unknown. World entropy was not
   fixed and one observation does not establish behavior over longer durations.
   [Final matched comparison](send150.md), [exact summary](send150-summary.json).

The replication bitmap candidate improved a bounded local helper but showed no
consistent remote timing or capacity improvement. It is not presented as the
cause or fix of overflow. [Rejected remote hypothesis](bitmap-comparison.md).

## Final condition and remaining limit

The final game was built from `e27db2d3c50b3b1dd550a32ed40f7a64526a4513`, identically
on both CAX11 hosts; SHA-256
`a4e5460cd6558a9f5cafec93206e64780e8c30bb1f6e20313c6394d7e22466a5`.
The unchanged optimized bot was built from
`2c25af7d5ab4cba81de1777437e2df2cfe735ebc`; SHA-256
`73b957c7cb090ac8c433aa66dfba983ec8ad62305f527cab83be596dce524b1e`.
Private config SHA-256 is
`0abd2a9041dc33023ff924cae334ce25683838a0c0726cfd8fcb5a0000332370`.
The final report records compiler, kernel, source/collector identities and exact
windows. Ordinary defaults were not changed or permanently deployed.

The strict AoI result was 126/150 peers within 1,150 units, below the unchanged
95% requirement. Baseline-reference misses and unknown delta entities were zero
in this final cell, but their absence does not resolve earlier findings. There
were still 348,964 steady oversized-unreliable warnings. No bug-free result is
claimed. Exact application-delivered input, send/receive queue residence,
outstanding reliable queue and causal instrumentation slowdown remain unknown.

[Diagnose strict AoI failures in the valid-load CAX11 Strategy 150 condition](https://github.com/Operatorr/godot-networking-poc/issues/41)
will distinguish server visibility from Snapshot/respawn ordering and measurement
time mismatch, using the real application seam and bounded anomaly evidence.
Current lifetime maxima lack the offending packet and matching authoritative
observer position. No gate is relaxed and no historical result is upgraded.
The [bug ledger](BUG-LEDGER.md) hands the full findings to
[Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39).
That ticket retains the final clean rerun. The
[broader results task](https://github.com/Operatorr/godot-networking-poc/issues/31)
retains unfinished matrix/economics/audit work. No CCX13 host was provisioned.

## Validation, provenance and restoration

Eleven workloads ran sequentially, each in a separate delegated task; one earlier
profiling preflight launched none. The [iteration ledger](ITERATIONS.md) retains
failed and invalid observations alongside improvements. Reports are in UTC under
the October 21 namespace; completion falls on October 22 in the operator's time
zone. Original one-pass results and all prior artifacts are preserved.

Required Rust workspace tests, Clippy and formatting checks passed on the final
source candidate, as did the client extension release build. Clippy retains two
pre-existing `collapsible_match` warnings in bot code. The final parent validation
also passed 18 targeted controller, analysis and atomic-publication tests.
Real ENet startup regressions cover independent optional receive/send requests;
the Strategy regression compares the real search against the original semantics.
Measurement defects and their regression coverage are detailed in the bug ledger.

Final private evidence is in
`deployment/hetzner/results/udp-send150-20261021/`, with separate `-build/` evidence.
The parent rechecked both archive hashes against retained remote checksum records:

```text
game.tar.gz  d88bc751089931da38cadd2211ca5fa50c62fed629619ffca979a75c91c35f71
bots.tar.gz  500e41cc6d2735397d2b857f758f4f4441c606683aaeedcce34d4b395293a715
```

Independent cleanup and post-analysis audits verified the original service,
configuration, executable, measurement destination, network/maintenance settings
and ordinary 524,288-byte game buffers in both directions. Zero players and no
owned workloads, collectors, profilers or timers remained. Candidate builds and
remote originals are retained separately. Previously provisioned `linux-perf`
and two debuginfod dependencies remain installed; kernel and perf policy are
unchanged. Private connection addresses and credentials are excluded from reports.
