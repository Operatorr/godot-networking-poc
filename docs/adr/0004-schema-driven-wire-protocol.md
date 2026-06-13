# ADR 0004 — Redesigned wire protocol as a shared Rust crate (no codegen)

**Status:** Implemented — 2026-06-11 (`rust/protocol`, exposed to GDScript through the
`client_ext` GDExtension; [rust-port/contract.md](../rust-port/contract.md) is the wire spec
as built). Records [Rust port](../rust-port/migration-spec.md)
decisions **D3** (redesign the wire format) and **D7** (implement it as a shared Rust `protocol`
crate). **Amends [ADR 0003](0003-enet-udp-transport.md):** ADR 0003 assumed the Rust port would
reimplement *only the transport seam* and keep the existing `PacketWriter`/`PacketReader` wire format
**unchanged**. The port is a **clean-slate rewrite** (migration spec D1) that redesigns transport
**and** wire format together, so that consequence of ADR 0003 is superseded. ADR 0003's transport
choice (ENet-over-UDP via `ENetConnection` raw channels) **stands**.

> **History (kept on purpose).** This ADR first proposed a *custom IDL + generator emitting both a
> Rust and a GDScript codec*. Grilling collapsed that: migration-spec **D5** put a shared Rust
> `sim_core` on the client as a GDExtension, and **D6** let the client call the **Rust** codec through
> that same extension — removing the GDScript target. With no second language to emit, the generator's
> sole justification vanished, so **D7** collapsed it to a plain shared Rust crate. The custom-IDL idea
> is recorded as a *rejected option* below.

## Decision

Redesign the wire format (tighter bitpacking, sub-byte flags, quantization, delta masks) and implement
it as a single shared Rust crate, **`protocol`**:

- Packets are Rust structs in `protocol`; encode/decode is **hand-written once** with explicit bit
  control — position quantized to `i16` at 0.1 units, sub-byte delta masks and entity flags, varints
  where they pay.
- **Both** consumers depend on the same crate: the **server** binary, and the **client GDExtension**
  (which exposes `protocol`'s codec to GDScript — migration spec D6).
- A `PROTOCOL_VERSION` const lives in the crate and is checked at handshake; mismatched versions are
  refused. Client and server deploy in lockstep (native-only model, ADR 0003 — no mixed-version
  rollout to support).
- **No IDL, no generator, no GDScript codec.**

## Context

The clean-slate Rust port reimplements the simulation in Rust while the client stays Godot. Naively
that splits serialization across two languages (GDScript + Rust) — the classic drift hazard ADR 0003
sidestepped by *freezing* the format. Once we choose to *evolve* the format to reclaim bandwidth,
freezing is off the table, so we need a different guarantee that the two sides agree.

Migration-spec D5/D6 supply it from an unexpected direction: the client already links a Rust
GDExtension (for `sim_core`, to guarantee prediction matches the server). Since the client runs Rust,
it can call the **Rust** codec directly — so **both** sides are Rust, and a single shared crate is the
single source of truth. No codegen is needed because there is no second language. ADR 0003 fixed
"native-only, permanently — no web client," so no future non-Rust consumer will ever need a
language-neutral schema either.

## Considered options

| Option | Single source of truth | Bit-level control | Machinery | Verdict |
|---|---|---|---|---|
| **Shared Rust `protocol` crate, hand-rolled bit codec** (chosen) | Yes | Full | None (one crate) | **Accepted** |
| Shared Rust crate, derive-based codec (bitcode/postcard) | Yes | Partial (quant/delta still custom) | Low | Rejected — wants explicit bit control for the budget |
| Custom IDL + generator emitting Rust **and** GDScript | Yes | Full | Generator + schema/codec skew in CI | Rejected — its only point was GDScript output, removed by D6 |
| Preserve current format, hand-port to Rust + keep GDScript codec | **No** — two hand codecs, two languages | as today | None | Rejected — the drift hazard D1 created |
| Off-the-shelf IDL (Protobuf/FlatBuffers/Cap'n Proto) | Yes | No (varints at best) | Low | Rejected — weak GDScript (moot now) and misses bandwidth budget |

## Consequences

- **Serialization drift between client and server is impossible by construction** — there is one codec,
  in one crate, linked by both. This covers the **wire format only**; **simulation-math parity** is
  handled separately and more fundamentally by the shared `sim_core` crate (migration-spec D5).
- **All bandwidth budgets are invalidated** and must be re-measured; the numbers in
  [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md) no longer describe the
  shipped protocol.
- **`HEARTBEAT` and `BATCH` leave the protocol** (ENet subsumes them — ADR 0003 / migration-spec D2);
  the clock-sync payload `HEARTBEAT` carried is relocated, not deleted.
- **No codegen step and no schema/generated-code skew** to police — the trade is **DIY versioning**
  (a version const + handshake check) instead of an IDL's free field-level back-compat. Acceptable
  under lockstep native deploys.
- **The client gains a native code path for (de)serialization** across the GDScript↔native boundary;
  revisit if that boundary cost shows up in client profiling.

## The eight questions

- **Client:** the GDExtension exposes `protocol`'s codec; GDScript hands raw ENet bytes in and gets
  typed packets out. No GDScript codec.
- **Server:** the Rust binary links the same `protocol` crate; identical structs, opposite direction.
- **Predicted:** nothing — serialization is a pure data transform.
- **Replicated:** the `protocol` structs *are* the replication format — entity deltas vs. a periodic
  full-state baseline, quantized positions, packed flags.
- **Persisted:** nothing — the Go API owns persistence; `protocol` describes only in-flight packets.
- **Validated:** decode checks field bounds and the `PROTOCOL_VERSION` byte; mismatches are rejected
  at handshake; malformed packets drop the packet/peer, never panic.
- **Can fail:** a version skew between a stale client and server (caught at handshake); a malformed
  datagram fails bounds checks in the codec.
- **Tested:** round-trip property tests (`encode → decode == identity`) in the `protocol` crate; shared
  byte-vector fixtures asserted by both the server and the client-extension test suites.

## See also

- [ADR 0003](0003-enet-udp-transport.md) — the ENet transport this rides on; this ADR amends its
  "wire format rides unchanged" consequence.
- [`../rust-port/migration-spec.md`](../rust-port/migration-spec.md) — decisions D3, D4, D6, D7 behind
  this ADR, and D5 (the shared `sim_core` that makes a single-language codec possible).
- [`../netcode/wire-protocol.md`](../netcode/wire-protocol.md) — the hand-written format this replaces.
- [`../netcode/performance-budgets.md`](../netcode/performance-budgets.md) — bandwidth numbers this
  invalidates and must be re-measured.
