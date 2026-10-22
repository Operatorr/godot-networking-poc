# Idle 150 admission-to-wire diagnosis

This is work inside [Fix load-test-exposed bugs and rerun until a run is clean](https://github.com/Operatorr/godot-networking-poc/issues/39), not another resolved map ticket.
The passing ladder is held at the generator-invalid Idle 150 observation.

The existing controls show complete offered input, matching capture counts below
the wire gate, no capture/kernel/socket errors, and no correctness findings. They
cannot identify whether inputs disappeared before the socket or were miscounted.
The new deterministic `enet_throttle_semantics` integration test uses the actual
pinned engine, virtual clocks and a lossless in-memory Socket. All 10,700 queue
submissions reach the wire with stable delay. With varying delay and unchanged
throttle defaults, 10,699 reach the socket and receiver; throttle falls to 28/32.
This is a transport-semantic witness, not the remote magnitude or causal attribution.

Ranked hypotheses and discriminating predictions:

1. ENet's documented adaptive throttle sheds queued unreliable inputs. Socket
   sends will be below admissions, without send errors, and the native throttle
   state/counter should account for the skipped commands.
2. Queue flushing is delayed. Pending command ages/service gaps and subsequent
   drain should explain admissions absent from the same-window socket count.
3. The wire collector misses commands. Independent native socket input-command
   counts/fingerprints will exceed both capture counts after boundary matching.

One separate child owns one matched Idle 150 diagnostic: 30 Hz input, 100 ms
stagger, seed 30, difficulty 1, 60 s warmup, 300 s measurement, unchanged send150
config and native bot buffers/network. Game behavior/binary, packet modes,
channels, throttle settings, AoI/budgets and all existing gates remain unchanged.
The instrumented bot receives its own committed source identity and both-host
binary proofs. Historical files and the fixed-build campaign candidate remain
preserved. Passive instrumentation is opt-in and its overhead is a limitation;
this is not a pure performance comparison or retrospective historical attribution.

Observe admission, native socket handoff and captures as distinct boundaries.
Use actual ENet-generated datagrams to test any input-command observer. Record
native send failures/zero-byte returns, service gaps and incomplete audit evidence.
Whitelist numeric peer diagnostics; do not publish raw Debug strings or auth data.
Keep evidence compact and explicitly bounded. A bounded per-input command identity
or datagram fingerprint trace can reconcile socket/capture boundaries; unknown
clock alignment, remaining queued work, truncation or parse errors stay unknown.
Do not infer application delivery from any of these transmission observations.

If Debug is used for otherwise-private peer counters, validate its exact pinned
0.4.0 field format with actual peers and fail diagnostics closed if it changes.
Do not patch dependency internals or disable throttling to manufacture valid load.
If native adaptive shedding explains a gap, classify specified transport behavior
separately from a code defect and retain any failed generator gate. A genuine
measurement/code defect needs its own failing regression and matched validation.

Before another workload, verify the previous hosts are released. Retain the proven
restoration path, unique audit labels, bounded collectors and complete byte-aware
journal counts. Finish with automatic restoration, two independent bounded audits,
prior binary/archive/closed-state preservation and matching evidence hashes. Do
not advance another ladder cell or close the parent ticket in this diagnostic.
