# Wire protocol — retired (redirect)

**Status: Retired.** Superseded by the shared Rust `protocol` crate
([ADR 0004 — schema-driven wire protocol](../adr/0004-schema-driven-wire-protocol.md)).

The hand-written GDScript `PacketWriter` / `PacketReader` byte format this page
once documented no longer exists. The **as-built, bit-packed wire format** —
packet type table, the 3-channel plan, quantization rules, typed entity ids,
delta/baseline masks, and `PROTOCOL_VERSION` — is documented in:

→ **[`../server/contract.md`](../server/contract.md)** (the system of record).

This stub is kept only so historical links from the ADRs and exec-plans resolve.
