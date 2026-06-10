# ADR 0004 — Schema-driven wire protocol with codegen for client + server

**Status:** Accepted (design) — 2026-06-11. Part of the [Rust server port](../rust-port/migration-spec.md)
(decisions D3 + D4). **Amends [ADR 0003](0003-enet-udp-transport.md):** ADR 0003 assumed the Rust port
would reimplement *only the transport seam* and keep the existing `PacketWriter`/`PacketReader` wire
format **unchanged** ("never the wire format"). The port is now a **clean-slate rewrite** (migration
spec D1) that redesigns transport **and** wire format together, so that consequence of ADR 0003 no
longer holds. ADR 0003's transport choice (ENet-over-UDP via `ENetConnection` raw channels) **stands**;
only its "wire format rides unchanged" consequence is superseded here.

## Decision

Define the wire protocol **once in a custom schema** and **generate both codecs** from it:

- A **custom IDL** (a small `.toml`-style / DSL file under `protocol/`) declares every packet, its
  fields, field widths, quantization (e.g. `pos: vec2 @quantize(0.1)`), and delta-mask layout.
- A **generator written in Rust** (`protogen` binary in the `protocol/` cargo workspace member) emits:
  - `gen/protocol.rs` — the Rust server codec.
  - `client/scripts/shared/networking/gen/protocol.gd` — the GDScript client codec.
- Generated files are **committed** (Godot client builds without a Rust toolchain). The server crate
  regenerates via `build.rs`; CI runs `cargo run -p protogen` and fails on a non-empty `git diff`.
- The schema carries a **protocol version**; client and server reject mismatched versions at handshake.

This replaces the hand-written `PacketWriter`/`PacketReader` pair with a single source of truth.

## Context

The clean-slate Rust port (migration spec D1) means the authoritative simulation is **reimplemented in
Rust** while the client stays **GDScript**. The serialization layer therefore spans **two languages**.
Two hand-written codecs in two languages is the classic drift hazard: any field added on one side and
forgotten on the other is a silent desync. ADR 0003 avoided this by *freezing* the wire format; once we
choose to *evolve* the format (to bitpack tighter and reclaim bandwidth), freezing is off the table, so
we need a different guarantee. A schema with codegen makes serialization drift **impossible by
construction** — both codecs descend from one file.

GDScript is the binding constraint on tooling: mainstream IDLs (Protobuf, FlatBuffers, Cap'n Proto)
have weak or absent GDScript codegen and cannot sub-byte bitpack, so they cannot hit the project's
<2 KB/s/player budget without a fight. A custom generator is the only option that emits true GDScript
**and** the bit-level layout a tuned game protocol wants.

## Considered options

| Option | GDScript codegen | Sub-byte bitpack | Single source of truth | Tooling cost | Verdict |
|---|---|---|---|---|---|
| **Custom IDL + own generator** (chosen) | Yes (we emit it) | Yes | Yes | Build + own the generator | **Accepted** |
| Preserve current format, hand-port to Rust | n/a | as today | **No** — two hand codecs, two languages | None | Rejected — the drift hazard D1 created |
| Off-the-shelf IDL (Protobuf / FlatBuffers / Cap'n Proto) | Weak / third-party | No (varints at best) | Yes | Low (mature) | Rejected — weak GDScript, misses bandwidth budget |
| Rust-authoritative (bitcode/postcard) + hand GDScript mirror | n/a | Yes (Rust side) | **Partial** — GDScript hand-written | Low | Rejected — reintroduces GDScript drift |

## Consequences

- **Serialization drift between client and server is eliminated** — the one guarantee D1's two-language
  split most needs. Note this covers the **wire format only**; **simulation-math parity** (movement/
  collision determinism for prediction) is a *separate* problem tracked in the migration spec under
  [Shared-sim parity] — codegen does not solve it.
- **All bandwidth budgets are invalidated** and must be re-measured against the new layout; the numbers
  in [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md) no longer describe the
  shipped protocol.
- **A codegen step joins the build** for both the Rust server (`build.rs`) and the Godot client
  (committed artifact + CI sync check). New build dependency, new failure mode (schema/codec skew),
  bounded by the CI `git diff` gate.
- **`HEARTBEAT` and `BATCH` leave the protocol** (ENet subsumes them — see ADR 0003 / migration spec
  D2); the clock-sync payload that `HEARTBEAT` carried is relocated, not deleted.
- **Versioning and back-compat are now our problem.** Off-the-shelf IDLs hand you field-level
  back-compat; the custom generator does not. Mitigation: a protocol-version handshake and, because the
  native client and server ship together (no browser, no staged rollout of mixed versions), lockstep
  deploys are acceptable for the POC.

## The eight questions

- **Client:** loads the generated `protocol.gd`; encodes `PLAYER_INPUT`, decodes `STATE_UPDATE` /
  `GAME_EVENT` using generated functions. No hand-written codec.
- **Server:** the Rust crate compiles the generated `protocol.rs`; same field definitions, opposite
  direction.
- **Predicted:** nothing — serialization is pure data transform; prediction is unaffected by this ADR.
- **Replicated:** the schema *is* the replication format — entity deltas vs. a periodic full-state
  baseline, quantized positions, packed flags.
- **Persisted:** nothing — the Go API still owns all persistence; the schema describes only in-flight
  packets.
- **Validated:** decode validates field bounds and the protocol-version byte; mismatched versions are
  rejected at handshake.
- **Can fail:** schema/generated-code skew (caught by the CI `git diff` gate); a malformed packet fails
  generated bounds checks and drops the packet/peer rather than panicking.
- **Tested:** generator has golden-output tests (schema → expected `.rs`/`.gd`); round-trip property
  tests (encode→decode == identity) run on both sides against shared byte vectors.

## See also

- [ADR 0003](0003-enet-udp-transport.md) — the ENet transport this rides on; this ADR amends its
  "wire format rides unchanged" consequence.
- [`../rust-port/migration-spec.md`](../rust-port/migration-spec.md) — decisions D3 (redesign) and
  D4 (toolchain) that this ADR records.
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — the hand-written format this replaces.
- [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md) — bandwidth numbers this
  invalidates and must be re-measured.
