# Legacy GDScript server — parity ground truth (removed)

**Status: Removed.** The original authoritative server was written in GDScript and
ran headless inside the Godot project at `client/scripts/server/` (+ the
`client/scenes/server/server_main.tscn` entry scene). It was retired when the
authoritative server was ported to Rust (`rust/server/`, the `omega-server`
binary) and **deleted** during the full-game restructure.

This file preserves the **file-by-file parity mapping** that was the GDScript
server's remaining value: when the Rust server's behavior is in question, this is
the index of which GDScript module each Rust module was ported from. The actual
GDScript source is recoverable from git history (it lived under
`client/scripts/server/` up to the commit that introduced this file).

> The Rust modules already carry top-of-file doc comments citing the GDScript
> file they port; this table is the consolidated reverse index.

## Module parity map

| Former GDScript file (`client/scripts/server/`) | Responsibility | Rust owner (`rust/`) |
| --- | --- | --- |
| `server_main.gd` | Top-level tick loop (`_process_server_tick`), input/shoot processing, move confirms, projectile spawn + lag-comp, respawn, `LOCAL_HIT_REPORT` validation, region heartbeat, metrics, shutdown | `server/src/sim/world.rs` (tick order) + `server/src/main.rs` (30 Hz accumulator + ENet service loop / dispatch); heartbeat → `server/src/net/api_client.rs` |
| `player_manager.gd` | Player registry: add/remove/auth, entity-id allocation, round-robin spawns, input queue, position-history for PvP lag comp, heartbeat timeouts | `server/src/sim/player.rs` (`PlayerManager`) |
| `player_state.gd` | Authoritative per-player state + one-tick `step()` (movement via shared SM, shoot rising-edge, position validation, damage/death/respawn/invuln, flags) | `server/src/sim/player.rs` (`PlayerState`); movement math in `sim_core` |
| `monster_manager.gd` | Monster registry: spawn (factory), id allocation (30000–39999), queries, position-history for player-projectile lag comp, cleanup, state collection | `server/src/sim/monster.rs` (`MonsterManager`) |
| `monster_ai.gd` | 4-state AI (IDLE/CHASE/ATTACK/FLEE): targeting, steering+avoidance, kiting/strafe, predictive aim, projectile spawn; difficulty-lerped from definition | `server/src/sim/monster.rs` (`MonsterAi`); RNG → `server/src/sim/rng.rs` (PCG32) |
| `monster_factory.gd` | Archetype id + pos → configured `MonsterState` via `MonsterDatabase` | folded into `server/src/sim/monster.rs` (no separate factory) |
| `monster_spawner.gd` | Three-layer spawn director (anchors + encounter pressure + regional grid) with visibility/overlap/bounds validation | `server/src/sim/monster.rs` (`MonsterSpawner`) |
| `monster_state.gd` | Per-monster state: archetype + definition, health, AI fields, `take_damage`, cooldowns, `to_entity_data` | `server/src/sim/monster.rs` (`MonsterState` + `MonsterDefinition`) |
| `projectile_manager.gd` | Projectile registry + integration; id range (10000–29999); two swept lag-compensated spatial-grid collision passes (vs monsters PvE, vs players PvP) | `server/src/sim/projectile.rs` (`ProjectileManager`); hit math in `sim_core::hit` |
| `projectile_state.gd` | Per-projectile state: pos/prev/dir/speed, distance/boundary/obstacle checks, spawn-tick + rewind-tick accessors, owner classification, `to_entity_data` | `server/src/sim/projectile.rs` (`ProjectileState`) |
| `server_collision_handler.gd` | Applies confirmed hits: player damage + knockback, DAMAGE/KILL/KILL_PVP broadcasts, monster damage + kill attribution + leaderboard | `server/src/sim/combat.rs` (incl. the D11 lenient backstop) |
| `server_broadcast_service.gd` | Snapshot/broadcast pipeline: per-tick spatial grid, AoI filter + hysteresis + LOD, per-peer delta caches, byte-budget scheduler, baselines, PLAYER_INFO/leaderboard | `server/src/net/broadcast.rs` (`BroadcastService`) |
| `delta_state_cache.gd` | Per-client last-sent-state cache; delta-mask calc, baseline interval/ack/resend, stale-entity despawn deltas | folded into `server/src/net/broadcast.rs` |
| `snapshot_scheduler.gd` | Per-peer priority queue for delta-entity selection under a byte budget; encoded-size estimator | folded into `server/src/net/broadcast.rs` |
| `spatial_grid.gd` | Uniform spatial-hash broad-phase (insert + 3×3 neighbourhood + radius queries) | folded into `server/src/net/broadcast.rs` (AoI) + inline in `projectile.rs` (collision) |
| `leaderboard_manager.gd` | In-memory PvP leaderboard (POC-only, no persistence) | `server/src/sim/leaderboard.rs` (persistence belongs to the Go API, ADR 0005) |
| `server_config.gd` | JSON config loader (user:// → res:// → defaults) + env overrides | `server/src/config.rs`; live configs are `deployment/server_config.{arena,sanctuary}.json` |
| `server_metrics.gd` | Tick-time/player/entity/byte metrics → `SERVER_METRICS` payload | `server/src/net/metrics.rs` (+ Prometheus gauges :9100/:9101) |
| `scenes/server/server_main.tscn` | Headless entry scene hosting `server_main.gd` | none — the Rust server is a plain binary, not a Godot scene |

## Why it was safe to delete

- The Godot client exports **client-only**; `NetworkManager` refuses server mode,
  so nothing under `client/scripts/server/` or `client/scenes/server/` loaded at
  runtime.
- The only non-server references were documentation comments naming the class
  names — prose, not code dependencies.

See [`design.md`](design.md) and [`contract.md`](contract.md) for the Rust
server's current architecture and as-built contract.
