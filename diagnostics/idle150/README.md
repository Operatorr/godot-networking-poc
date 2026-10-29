# Idle150 diagnostic observer — stopped at local overhead gate

This is an isolated, diagnostic-only copy of `rusty_enet =0.4.0` and an in-memory
replay harness for [Diagnose Idle150 offered-to-wire delivery deficit](https://github.com/Operatorr/godot-networking-poc/issues/45).
The production Cargo workspace and dependencies are unchanged. There is no
network client or remote runner in this package.

The [approved bounded plan](https://github.com/Operatorr/godot-networking-poc/issues/45#issuecomment-6491312527)
required <=2% added elapsed replay time across five paired measurements before
any remote access. The measured aggregate overhead was **5.549604164%**. The
preparation stop rule was applied with no retry, optimization after failure,
remote commands or workloads. This observer is **not admitted for remote use**.

See the [result and original measurements](../../docs/netcode/perf-notes/load-test-reports/2026-10-29-idle150-delivery/REPORT.md).
Do not infer remote overhead or the ordinary historical deficit's cause from
this local result.

## What is here

- `vendor/rusty_enet`: upstream 0.4.0 source with its MIT license retained. Five
  existing files receive additive observation changes; `input_diagnostic.rs`
  contains the new fixed-size counters and hooks. All unrelated upstream source
  remains byte-identical.
- `upstream-sha256.json`: hashes before modification. `observer.patch` shows
  changes to existing upstream files; the added module is separately included
  in the complete experiment source manifest.
- `src/replay.rs`: the same virtual-clock input for upstream, observer disabled
  and observer enabled. Compares exact datagrams, native send results, received
  events and their virtual timestamps. It never opens a UDP socket.
- `src/main.rs`: seven parity/accounting cases and the fixed five-pair timing
  assessment. There are 25 virtual 361-second replays per arm, alternating pair
  order. Original u8 input sequences wrap repeatedly in every case.
- `Cargo.lock`: the exact dependency resolution used for the recorded binary.

The local validation command is:

```sh
cargo run --release --locked --manifest-path diagnostics/idle150/Cargo.toml -- validate
```

The recorded timing command was the release executable with `benchmark`.
It exits 1 for an overhead failure and prints every pair. The approved assessment
has already run; a future measurement is a new experiment, not a replacement for
the retained result.

## Counter boundaries and limitations

Each enabled single-peer Host owns fixed-size counters, separate from peer
reset. The observer never changes packet allocation, data, reliability, sequence
numbers, transport return values or native removal order. It counts only
channel-2 packets of length 22 whose first byte is PlayerInput's type 2. Other
accepted modes enter an explicit unknown-disposition counter. It does not infer
identities from the wrapping u8 sequence.

Successful admission adds pending work. The actual throttle branch, reset of
queued work, and removal after the actual Socket result each consume one pending
unfragmented unreliable input. Full, zero, partial and error results are separate.
Three inputs in one datagram produce three dispositions, not one. Reset removal
is never labelled throttling. There is no per-input allocation, Debug parsing,
locking, trace file, transport tuning or retry in the observer.

One Host adds 112 bytes of counter state including its enable flag/alignment;
150 Hosts would add 16,800 bytes, below the approved 2 MiB cap. This is not a
measurement of a complete deployed bot recorder: none was prepared after the
failed local gate. The production bot and game binaries were never modified.

`completed_hook_ns` measures completed hook wall-time sections. It excludes the
entry clock read, the final elapsed bookkeeping, disabled branches, added Host
layout/cache effects, snapshot/serialization and any complete bot observer.
It is not total causal overhead or CPU time. The five-pair whole-replay elapsed
comparison is the local admission gate and captures those runtime effects for
the replay condition. No remote 1.5 CPU-second guard was evaluated.

The replay proves supported mechanisms and parity for its tested inputs only.
It does not prove ordinary Idle150 delivery, a bug in game code, the absence of
observer perturbation, or server capacity. This standalone package is a retained
investigation artifact and is not intended for production adoption.
