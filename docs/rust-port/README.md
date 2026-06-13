# Rust server port — status

**Status: Implemented** (2026-06-11). The authoritative game server is the Rust `omega-server`
binary; the GDScript server is retired (`NetworkManager` refuses server mode and points at the
binary). The Godot client connects over ENet/UDP and runs its prediction through the same
compiled `sim_core` the server uses — zero sim divergence by construction (D5).

Reading order: [`migration-spec.md`](migration-spec.md) (the D1–D14 decision log) →
[`contract.md`](contract.md) (crate APIs, channel plan, wire format, numerics policy — as
built) → [`extraction/`](extraction/) (the GDScript behavioral ground truth, `file:line` cited).

## What exists

| Piece | Where | Notes |
|---|---|---|
| `protocol` crate | `rust/protocol` | Bit-packed wire format (ADR 0004): `[u8 type][payload]`, typed entity ids, 5-bit delta masks, strict decode (hostile bytes ⇒ `Err`, never panic). |
| `sim_core` crate | `rust/sim_core` | Movement SM, the analytic mover, arena geometry, hit predicates. Preserves every documented parity hazard (13-tick dash, 166-decrement cooldown, sprint-gate flapping, X-axis slide tie-break, Chebyshev expansion, no depenetration, strict comparisons). |
| `omega-server` | `rust/server` | Single-threaded 30 Hz tick (D8) over `rusty_enet` (pinned `=0.4.0` — wire-compatible with Godot's `ENetConnection`); AoI/LOD/budget broadcast with delta caches; D11 lenient hit backstop (ON); Ed25519 session tickets with dev-mode unsigned fallback (D9); Prometheus `:9100` + tracing; graceful SIGINT/SIGTERM shutdown with reasoned disconnects. |
| `client_ext` GDExtension | `rust/client_ext` → `client/bin/` | `ProtocolCodec` (encode/decode, returns legacy GDScript dict shapes), `PredictionSim` (the shared sim for prediction/replay), `SimHit` (the shared hit predicate). |
| Client rewiring | `client/autoload/network_manager.gd`, `client/autoload/transport/enet_transport.gd`, `client/scripts/client/prediction.gd` | ENet client over 3 channels; clock sync rides every snapshot (HEARTBEAT retired); AUTH_RESULT carries the entity id (instant Authority sync, PLAYER_INFO name-match kept as gated fallback). |

## How it was verified

- **106 Rust tests** across the workspace (`cargo test --workspace`); clippy `--all-targets`
  clean; `cargo fmt` clean. (Count at port completion — keep green, not frozen.)
- **End-to-end smoke test**: `client/scenes/test/net_smoke.tscn` against a live server —
  ENet connect → auth → snapshots decoded → input acked → clock synced. Exits 0 on PASS.
- **Adversarial parity review**: five independent review passes (movement sim, combat/monsters,
  tick/broadcast/lifecycle, wire protocol, client rewiring) against the GDScript source and the
  extraction notes. **Zero critical findings**; all six moderate findings were fixed the same
  day (backstop id-recycling hole, graceful shutdown, baseline channel routing, malformed-ticket
  refusal, client disconnect flush, AUTH_RESULT → PredictionController wiring), plus the minor
  numerics/diagnostics items.

## Deliberate deviations from the GDScript (documented, reviewed)

- Player entity ids recycle within 1–999 (GDScript never recycled); freed ids are quarantined
  until the next snapshot broadcast so remote delta caches always see REMOVED before reuse.
- Baselines and full-state replies ride **ch1 reliable** (budget-exempt, may exceed the 1200 B
  unreliable MTU); deltas stay on ch0 unreliable-sequenced. Safe because deltas only ever
  reference an acked baseline.
- Bit-level (not byte-level) budget accounting; saturating ×100 metrics tick-times; configurable
  `advertise_url`; single monotonic clock; seedable PCG32 RNG (call-site parity, not
  stream parity); full-state packets cache only what ships (GDScript stranded truncated
  entities as "sent").
- Dev-mode (ticketless) joins get a server-assigned placeholder `character_id`.

## Not done / follow-ups

- **Load-testing bot swarm** still speaks the retired WebSocket protocol — port it to ENet,
  ideally as a Rust binary reusing the `protocol` crate.
- **M3 ticket issuance**: the Go API does not yet mint Ed25519 session tickets; servers run
  dev-mode (`allow_unsigned_tickets`). The verification path is implemented and tested.
- **Cutover cleanup**: once the port has soaked, delete `client/scripts/server/` (kept now as
  parity ground truth) and re-verify `docs/netcode/` file:line cites against `rust/`.
