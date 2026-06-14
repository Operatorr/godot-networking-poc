# Omega game server — docs

The authoritative game server is the Rust **`omega-server`** binary (`rust/`). The Godot client
connects over ENet/UDP and runs its prediction through the same compiled `sim_core` the server
uses, so movement prediction and authority cannot diverge on the math.

## Read in this order

1. [`design.md`](design.md) — architecture & rationale: topology, transport, the shared sim, the
   tick loop, auth, persistence, hit authority, progression, deployment. The **why**.
2. [`contract.md`](contract.md) — workspace, crate APIs, ENet channel plan, the bit-packed wire
   format, and the numerics policy, **as built**. The **what** an implementer codes against.

## The crates (`rust/`)

| Crate | Role |
|---|---|
| `protocol` | Bit-packed wire format: `[u8 type][payload]`, typed entity ids, delta masks, strict decode (hostile bytes ⇒ `Err`, never panic). |
| `sim_core` | Movement state machine, the mover, arena geometry, hit predicates. No Godot or network deps. Shared by the server **and** client prediction. |
| `server` | The `omega-server` binary: single-threaded 30 Hz tick over `rusty_enet` (`=0.4.0`), AoI/LOD/budget broadcast, Ed25519 session tickets (dev mode: unsigned), Prometheus on `:9100`. |
| `client_ext` | GDExtension (`gdext`) exposing `ProtocolCodec`, `PredictionSim`, `SimHit` to GDScript; copied into `client/bin/`. |
| `load_test` | The `omega-load-test` ENet bot swarm — links `protocol` + `sim_core` directly. See its README. |

## See also

- [`../ops/architecture.md`](../ops/architecture.md) — top-level system architecture + POC success criteria.
- [`../CONTEXT.md`](../CONTEXT.md) — glossary (Tick ≠ Frame ≠ Snapshot; the three state lifetimes).
- [`../adr/`](../adr/) — load-bearing decisions (0003 ENet/UDP, 0004 wire protocol, 0005
  permadeath, 0006 Softcore/Hardcore + Glory, 0007 native systemd deploy).
