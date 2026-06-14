# Tick rate: 30 Hz vs 60 Hz — gated toggle + measurement protocol

**Status:** Protocol defined; **RESULTS PENDING MEASUREMENT.** Default is **30 Hz** and stays 30
until a load run proves 60 Hz fits the budgets below.

> The roadmap asked: would raising the sim/input tick rate from 30→60 Hz fix the "input feels
> sluggish / floaty" complaint without breaking the bandwidth budget at target load? This note
> documents the **gated, reversible toggle** that makes an honest A/B possible, the **measurement
> protocol** to run it, and a **clearly-marked empty results section** to fill once measured. No
> numbers here are measured yet — do not fabricate them.

## TL;DR

- 60 Hz is a **toggle, not the default.** Default stays 30 Hz.
- The authoritative server is the Rust **`omega-server`** binary (`rust/server/`); one process = one
  Instance. Its sim clock authority is `tick_rate` in `rust/server/src/config.rs`. The Godot client's
  clock authority is `GameConstants.SERVER_TICK_RATE` (`client/scripts/shared/game_constants.gd`). For
  an honest end-to-end test you must move **both** together — see below.
- The load-test swarm (`omega-load-test`, `rust/load_test/`) measures **server CPU + downstream
  bandwidth** and, unlike the retired Python harness, **also drives real-client-rate input** via
  `--input-hz` (default 30). Client-side **prediction/interpolation CPU** doubling still needs a
  **separate manual single-client run** on a real Godot client.

## The two clocks (why "one knob" was a lie)

There are two independent tick clocks reading two different authorities:

1. **Server sim clock** — `config.tick_rate` (`rust/server/src/config.rs`), consumed by the **fixed
   accumulator loop in `rust/server/src/main.rs`** (`tick_interval = config.tick_interval()`, then
   `while tick_timer >= tick_interval { world.tick(...) }`). The main thread IS the tick thread (D8);
   the ENet host is serviced in ~1 ms slices between ticks. There is no engine `physics_ticks_per_second`
   on the server — it's a plain Rust loop.
2. **Client input/prediction/interp clock** — `Engine.physics_ticks_per_second`, which governs how
   often `_physics_process` runs in `prediction.gd` and the interpolation controller. The *send*
   cadence within that is gated by `INPUT_SEND_INTERVAL = GameConstants.SERVER_TICK_INTERVAL`
   (`prediction.gd`), and `SERVER_TICK_INTERVAL = 1.0 / SERVER_TICK_RATE` (`game_constants.gd`).

These are independent: flipping the server's `tick_rate` alone moves the server but leaves the client
sampling/sending at 30; flipping `physics_ticks_per_second` alone changes how often the client
`_physics_process` runs but the *send* still gates at 33.3 ms unless `SERVER_TICK_RATE` also changes.

### The client-side authority

`GameConstants.SERVER_TICK_RATE` is the single client-side authority:

- `game_manager.gd::_ready()` applies it once at startup:
  `Engine.physics_ticks_per_second = int(GameConstants.SERVER_TICK_RATE)`. So `project.godot`
  `physics_ticks_per_second=30` is only a fallback; the constant is the live client clock.
- `INPUT_SEND_INTERVAL` derives from `SERVER_TICK_INTERVAL`, so the upstream send cadence follows the
  same constant.
- The shared sim crate `sim_core` carries its own `SERVER_TICK_RATE = 30.0`
  (`rust/sim_core/src/constants.rs`), mirrored from `game_constants.gd`. The client runs the SAME
  compiled crate via the `client_ext` GDExtension, so prediction cannot diverge — but the constant
  is **not** read from a config file, so a 60 Hz test must edit it in source and rebuild the
  GDExtension. The Rust server's `tick_rate` is independent of `sim_core::SERVER_TICK_RATE` (the
  server reads its rate from config, not the constant).

## How to run the 60 Hz trial (and revert)

The server rate is **config/env-driven** (no source edit, no rebuild). The client rate is
**source/constant-driven** (edit + rebuild). For an honest A/B move both:

**Server (pick one — env wins over JSON):**

1. Env override, no rebuild: `GAME_SERVER_TICK_RATE=60` (read by `apply_env` in
   `rust/server/src/config.rs`; highest precedence). The systemd units inject this via
   `deployment/env/`. There is **no** `--tick-rate` CLI flag — only `--config`, `--mode`, `--port`,
   `--allow-unsigned-tickets`, `--require-tickets` (`rust/server/src/main.rs`).
2. Or per-instance JSON: `deployment/server_config.{arena,sanctuary}.json` →
   `"tick_rate": 60` (the local dev file is `client/data/config/server_config.json`, the fallback
   search path in `main.rs`).

**Snapshot rate (downstream cost knob):** `"snapshot_rate_hz"` in the same config:

- `60` (or `0` = follow tick) to test the **full** 60 Hz pipeline (input *and* snapshot), **or**
- `30` to **isolate** the input-latency benefit from the snapshot-bandwidth cost.

  Effective rate = `0 → tick_rate`, else `min(raw, tick_rate)` (`ServerConfig::snapshot_rate_hz`,
  `config.rs`; the accumulator that consumes it lives in `World::tick`,
  `rust/server/src/world.rs` — `snapshot_interval = 1.0 / snapshot_rate_hz`). Run **both** variants
  so server CPU and downstream bandwidth are attributed separately.

**Client:** edit `client/scripts/shared/game_constants.gd` → `const SERVER_TICK_RATE := 60.0`
(drives the client `_physics_process` clock + `INPUT_SEND_INTERVAL`) **and**
`rust/sim_core/src/constants.rs` → `pub const SERVER_TICK_RATE: f64 = 60.0;` (keep the two mirrored),
then rebuild the GDExtension (`./scripts/build_client_ext.sh`).

**Load-test bots** follow the real-client cadence via `--input-hz` — set `--input-hz 60` to match a
60 Hz client (`rust/load_test/src/main.rs`, default 30).

**Revert = set the server rate, the client constants (both), and `snapshot_rate_hz` back to 30 / 30 /
30**, rebuild the GDExtension, and confirm parity with the 30 Hz baseline run afterward.

### Sanity checks at each rate

- Server log prints `config: ServerConfig { ... tick_rate: N, ... }` at boot (`info!("config: {config:?}")`
  in `main.rs`); the Prometheus `tick_duration_ms` histogram on `127.0.0.1:9100` reflects the loop rate.
- Load-test report: bots ran at the requested `--input-hz`; per-peer bandwidth and tick-time fields
  come straight from the server's `ServerMetrics` packet.
- A real client: `Engine.physics_ticks_per_second == N` and `INPUT_SEND_INTERVAL == 1.0 / N`.

## Tick-derived constants whose wall-clock meaning HALVES at 60 Hz

These are expressed in **ticks**, so their real-time meaning halves at 60 Hz. They live in the shared
sim crate `rust/sim_core/src/constants.rs` (mirrored in `game_constants.gd`); enumerated here so
nothing silently changes meaning:

| Constant | @30 Hz | @60 Hz | Effect | Where |
| --- | --- | --- | --- | --- |
| `REMOTE_ENTITY_RENDER_DELAY_TICKS = 2` | 66.7 ms | 33.3 ms | Remote-smoothness margin shrinks. Interp seeds from `SERVER_TICK_INTERVAL`, so it adapts. | `sim_core/src/constants.rs` |
| `MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6` | 200 ms | 100 ms | Lag-comp rewind window auto-scales (`pve_compensation` uses `tick_rate`, `rust/server/src/world.rs`) — PvE hits get slightly harder to land. | `sim_core/src/constants.rs` |
| `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4` | ~133 ms | ~66.7 ms | Same auto-scale, tighter PvP rewind. | `sim_core/src/constants.rs` |
| `POSITION_HISTORY_TICKS = 8` | ~267 ms | ~133 ms | The lag-comp position ring (`rust/server/src/player.rs`) holds 8 ticks — at 60 Hz it covers half the wall-clock, so deep rewinds run out of history sooner. | `rust/server/src/player.rs` |
| `HIT_BACKSTOP_GRACE_TICKS = 15` (floor) | 500 ms | 250 ms | The D11 lenient backstop grace floor (`config.rs` clamps `backstop_grace_ticks` up to this). Halving the wall-clock grace risks the backstop firing on lag — re-check leniency if 60 Hz ships. | `sim_core/src/constants.rs` |
| `DELTA_FULL_STATE_INTERVAL = 100` | ~3.3 s | ~1.7 s | Forced full baselines twice as often = more downstream bandwidth. | `rust/server/src/broadcast.rs` |

**Tick-rate INVARIANT (no change):** cooldowns/respawn/invulnerability are in seconds and the server
applies them via tick-interval accumulation, so they are unaffected by the tick rate.

## Measurement protocol

Run `omega-load-test` (`./scripts/run_load_test.sh`) against a server at **30 Hz**, then at **60 Hz**
(both the 60-tick/60-snap and 60-tick/30-snap variants), matching `--input-hz` to the rate under
test. Per run, capture from the JSON report (sourced from the server `ServerMetrics` packet, see
`docs/server/contract.md`):

- per-peer downstream bandwidth (server `MetricsCollector` per-peer bytes, `rust/server/src/metrics.rs`).
- `avg_tick_time_ms` / `max_tick_time_ms` — avg/max over the last 30 ticks (`METRICS_SAMPLE_SIZE`,
  `metrics.rs`); also exported as the Prometheus `tick_duration_ms` histogram + `avg_tick_time_ms` gauge.
- player/entity counts, packet-loss, crash/disconnect rate for context.

### Scenarios

Use the predefined scenarios in `rust/load_test/src/main.rs` (`SCENARIOS`):

| Scenario | Bots | Duration | Purpose |
| --- | --- | --- | --- |
| `baseline` | 50 | 2 min | Basic validation |
| `target` | 100 | 5 min | The release-gate load |
| `combat` | 100 | 2 min | Constant-shooting stress (worst-case event traffic) |
| `clustered` | 100 | 2 min | AoI worst case (bots clustered → max in-radius neighbours) |
| `stress` | 200 | 5 min | Find the breaking point (needs `max_players >= 200`) |

(`idle`, `movement`, and `strategy` also exist; see `rust/load_test/README.md`. Unlike the retired
Python harness, the Rust swarm **does** have a `clustered` AoI-worst-case scenario — measure it here too.)

### Budgets to compare against

- **Per-player bandwidth:** `< 5 KB/s` working budget, `< 2 KB/s` aspirational
  (`../performance-budgets.md`).
- **Server tick time:** avg `< 8 ms`, max `< 25 ms` (eng budget). The gate for adopting 60 Hz:
  per-player KB/s under 5 **and** server max tick time under ~16–25 ms at `target` (100 bots).

### Critical caveat — what the bot harness CANNOT measure

The Rust swarm links `protocol` + `sim_core` directly and sends `PlayerInput` at `--input-hz`
(default 30, settable to 60), so it **does** exercise real-client upstream packet rate — a strict
improvement over the old Python bots' fixed 10 Hz. The swarm measures:

- ✅ **Server CPU** (tick time) at the higher tick rate.
- ✅ **Downstream** bandwidth doubling when `snapshot_rate_hz` follows a 60 Hz tick.
- ✅ **Upstream** packet rate, when `--input-hz 60` is set to match a 60 Hz client.

…but does **NOT** exercise:

- ❌ Client-side **prediction/interpolation CPU** doubling (governed by `physics_ticks_per_second` on
  a real Godot client running the `client_ext` `PredictionSim`/interpolation — the bots use a
  simplified headless AI, not the rendering/prediction stack).

**Capture client CPU with a separate MANUAL single-client run:** launch one real client at 30, then
60 (rebuild the GDExtension between rates), and watch the engine profiler frame time plus the HUD
metrics channel (`bytes_received`). Record the client frame-time delta and subjective feel here.

## RESULTS — PENDING MEASUREMENT

> No load runs have been captured yet. Do **not** fill these with estimates. Run the protocol above
> and paste the real numbers, then write the recommendation.

### Load-swarm runs (server CPU + downstream/upstream)

| Scenario | Tick/Snap | input-hz | per-player KB/s | avg tick ms | max tick ms | crash % | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (50) | 30 / 30 | 30 | _pending_ | _pending_ | _pending_ | _pending_ | |
| baseline (50) | 60 / 60 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| baseline (50) | 60 / 30 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 30 / 30 | 30 | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 60 / 60 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 60 / 30 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| combat (100) | 30 / 30 | 30 | _pending_ | _pending_ | _pending_ | _pending_ | |
| combat (100) | 60 / 60 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| clustered (100) | 30 / 30 | 30 | _pending_ | _pending_ | _pending_ | _pending_ | |
| clustered (100) | 60 / 60 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |
| stress (200) | 30 / 30 | 30 | _pending_ | _pending_ | _pending_ | _pending_ | |
| stress (200) | 60 / 60 | 60 | _pending_ | _pending_ | _pending_ | _pending_ | |

### Manual single-client run (client CPU + feel)

| Tick rate | client frame time (ms) | upstream PlayerInput KB/s | subjective feel | notes |
| --- | --- | --- | --- | --- |
| 30 Hz | _pending_ | _pending_ | _pending_ | |
| 60 Hz | _pending_ | _pending_ | _pending_ | |

### Recommendation

_PENDING._ Default gate: keep **30 Hz** unless 60 Hz keeps per-player KB/s under **5** **and** server
max tick time under **~16–25 ms** at `target` (100) load. If 60 Hz only fits at `60-tick/30-snap`
(input fast, snapshot held at 30), record that as the recommended compromise.

## The eight questions

- **Client:** the client clock (`_physics_process` rate driving prediction/interpolation, and the
  `PlayerInput` send cadence) follows `GameConstants.SERVER_TICK_RATE` via
  `Engine.physics_ticks_per_second` + `INPUT_SEND_INTERVAL`; the shared `sim_core::SERVER_TICK_RATE`
  must be kept mirrored and the GDExtension rebuilt.
- **Server:** the sim/snapshot loop follows `config.tick_rate` / `snapshot_rate_hz`
  (`rust/server/src/config.rs`) via the fixed accumulator in `rust/server/src/main.rs` and the
  snapshot accumulator in `rust/server/src/world.rs`; `GAME_SERVER_TICK_RATE` env overrides at runtime.
- **Predicted:** nothing new — tick rate is a cadence, not gameplay state.
- **Replicated:** the *effect* is observable (faster snapshot stream at 60-tick/60-snap); the rate
  itself is not on the wire. Each snapshot carries an absolute `server_tick` and a `server_ms`
  timestamp (`rust/server/src/broadcast.rs`; see `docs/server/contract.md`), so clients adapt by
  measuring inter-snapshot arrival — no protocol change is needed.
- **Persisted:** nothing; the deploy-time authority is the per-instance config
  (`deployment/server_config.{arena,sanctuary}.json`) plus optional env. Durable state lives only in
  the Go API.
- **Validated:** `ServerConfig::validate` rejects `tick_rate = 0` (falls back to 30) and clamps the
  backstop grace to the `sim_core` leniency floor; `snapshot_rate_hz()` clamps the snapshot rate to
  `(0, tick_rate]`. The client constant and the `sim_core` constant must be kept in sync by hand for
  an honest A/B (this doc is the checklist).
- **Can fail:** moving only the server rate (or only the client constant) → client/server cadence
  mismatch (server starves of inputs half its ticks, or client predicts at the wrong rate). At
  60-tick/60-snap, downstream bandwidth likely breaches the 5 KB/s per-player budget at target load —
  the expected reason the default stays 30. At 60 Hz the tick-derived grace/history windows above
  halve in wall-clock and may need re-tuning.
- **Tested:** `omega-load-test` (`baseline`/`target`/`combat`/`clustered`/`stress`,
  `rust/load_test/`) for server CPU + downstream/upstream; a manual single-client run for client CPU.
  **Run pending.**

## See also

- [`../performance-budgets.md`](../performance-budgets.md) — the budget table this measurement updates
- [`../latency-budget.md`](../latency-budget.md) — input-sample (stage 1) + tick-wait (stage 2) that 60 Hz halves
- [`../smoothness-render.md`](../smoothness-render.md) — why interpolation, not 60 Hz, is the primary smoothness fix
- [`../server-tick-broadcast.md`](../server-tick-broadcast.md) — the tick + snapshot loop the rate governs
- [`../../server/contract.md`](../../server/contract.md) — as-built wire format, snapshot fields (`server_tick`/`server_ms`), and config keys
