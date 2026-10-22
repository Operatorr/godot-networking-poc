# Bounded wire collector history

The [instrumented control](instrumented-control.md) exposed a measurement defect:
its wire readers stopped after accumulating two million reliable-command history
entries. Complete port-second evidence ended at 27.57 seconds. Those historical
results and their null tails are unchanged. The bitmap comparison freezes the
same old collector at `04faa97` to preserve its matched condition.

## Reproduction and repair

A regression sends 2,000,010 wire-shaped reliable commands, with repeated u16
sequence wraps, through the actual `ArticleFlow::observe` path over 20 synthetic
seconds. The original reader failed with `diagnostic reliable-state limit`.
The repaired reader passes without retaining a growing entry per command.

Each direction/port/channel now holds a 32,768-sequence rolling bitmap (4 KiB).
The reader admits at most 8,192 streams: at most 32 MiB of bitmap storage plus
bounded map, aggregate, and output-buffer overhead. Advancing a sequence clears
reused slots in word-sized chunks; ordinary sequential traffic takes constant
work. It no longer scans millions of timestamps each second.

**New counting semantics:** `udp-diagnostic-points-v2` counts a repeated reliable
sequence while it remains in this sequence window, with no 60-second TTL. Sequence
extension uses the nearest half-range of observed data commands; ACKs do not
advance this history. This assumes no unseen advance of at least 32,768 sequences
and no port reuse. An exactly-half-range observation is explicitly unclassified,
not charged as first transmission or retry. A first observation is not proof of an
original transmission. The JSON records these semantics and unclassified counts.
These retry totals are not interchangeable with the old 60-second counters.

This repair retains the existing sampled UDP fingerprint, input counts, ACK
counts, packet/byte counts, second and 10 ms aggregates. Collector-version changes
remain a separate experimental condition; no server-capacity improvement is
inferred from this local repair.

## Failure visibility

- `port-bot.csv` is created at startup and flushed on each new observed mapping.
- Completed flow seconds and per-port rows are flushed as collection advances.
- `parser-status.json` is atomically checkpointed approximately once per second
  while packets arrive, then finalized as `eof` or `error`. A killed process can
  leave only a prefix checkpoint marked `running`.
- EOF means the supplied pipe ended. It does **not** prove complete workload
  coverage: controller exit/guard state, capture loss, packet timestamps, mappings,
  and the requested window must still agree.
- A truncated pcap record header now fails instead of looking like clean EOF.
  Finalization retains readable prefix flow evidence on ordinary reader errors.
  An output/filesystem failure can still prevent a final checkpoint; missing or
  unfinished evidence remains unknown.

## Local validation

Five standalone Rust tests pass: parser shape/truncation, sustained history,
wrap/reordering/half-range ambiguity, and differential comparison against a
bounded reference across 100,000 jumps/reordered observations. Six Python replay
tests pass, including exact window/input/retry counts, mapping, partial-pcap
failure with retained evidence, and malformed counts on normal EOF.

Commands:

```sh
rustc --edition=2021 -O --test scripts/load_campaign/udp_control_record.rs -o /tmp/omega-udp38-flow-regression
/tmp/omega-udp38-flow-regression
python3 -m unittest discover -s scripts/load_campaign -p test_udp_control_flow.py
```

The combined local Rust test process used 2,457,600 bytes maximum RSS and 0.35 s
wall time on the development Mac. This is a small-stream synthetic check, not a
remote collector-overhead measurement or a maximum-stream memory measurement.
Remote coverage and perturbation must be measured in the next collector condition.

## Remote validation and actual-encoder correction

The [bounded-collector run](bounded-collector.md) completed both readers without
history exhaustion, malformed packets or capture loss. It retained late wire
points and reduced measured capture-child RSS to about 39 MiB. It still failed
bot identity mapping: the original synthetic handshake omitted `character_id`.
The actual encoder places that u32 before the name, so unsigned name length is at
byte 8 and the name starts at byte 9 (including the application type byte).

`rust/protocol/tests/diagnostic_handshake.rs` now feeds **the actual
`ClientPacket::ConnectAuth::encode()` output** through the diagnostic command
parser. It failed before the offset correction and passes afterward, including
zero/nonzero character IDs, multiple bot IDs, non-bot names and truncated names.
The earlier synthetic fixtures and the wire-layout documentation are corrected.
Only name extraction changes: the reliable sequence history, packet/input/ACK
counting, fingerprint selection and cadence remain identical to `30ec792`.
New mapping output and its small I/O cost must still be verified remotely.

All seven integration tests (including the five imported reader tests) and six
Python replay tests pass. Workspace tests, Clippy (existing warnings), formatting
and the client extension build pass. Historical empty maps remain unknown; the
retained fingerprints contain no names from which to reconstruct identities.
