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
- There is **one client-side authority** — `GameConstants.SERVER_TICK_RATE` — and **one server
  authority** — `server_config.json tick_rate`. For an honest test you must move **both** together.
- The harness (bot swarm) measures **server CPU + downstream bandwidth** only. Bots send input at a
  **fixed 10 Hz**, so the real-client **upstream** packet doubling and **client-side** CPU doubling
  must be captured in a **separate manual single-client run.**

## The two clocks (why "one knob" was a lie)

There are two independent tick clocks reading two different authorities:

1. **Server sim clock** — `config.tick_rate` from `server_config.json`, consumed by a **manual
   accumulator in `server_main.gd::_process`** (`tick_interval := 1.0 / config.tick_rate`,
   server_main.gd:188; the snapshot accumulator uses the same), **not** `_physics_process`. So the
   engine's `physics_ticks_per_second` does **not** gate the server.
2. **Client input/prediction/interp clock** — `Engine.physics_ticks_per_second`, which governs how
   often `_physics_process` runs in `prediction.gd` and `interpolation_controller.gd`. The *send*
   cadence within that is gated by `INPUT_SEND_INTERVAL = GameConstants.SERVER_TICK_INTERVAL`
   (prediction.gd:73), and `SERVER_TICK_INTERVAL = 1.0 / SERVER_TICK_RATE` (game_constants.gd).

These were independent: flipping `server_config.json tick_rate` alone moved the server but left the
client sampling/sending at 30; flipping `physics_ticks_per_second` alone changed how often the
client `_physics_process` ran but the *send* still gated at 33.3 ms unless `SERVER_TICK_RATE` also
changed.

### What the toggle unified

`GameConstants.SERVER_TICK_RATE` is now the single client-side authority:

- `game_manager.gd::_ready()` applies it once at startup:
  `Engine.physics_ticks_per_second = int(GameConstants.SERVER_TICK_RATE)`. So `project.godot`
  `physics_ticks_per_second=30` is only a fallback; the constant is the live client clock.
- `INPUT_SEND_INTERVAL` already derives from `SERVER_TICK_INTERVAL`, so the upstream send cadence
  follows the same constant.
- `server_config.gd DEFAULTS.tick_rate = int(GameConstants.SERVER_TICK_RATE)` — the code default
  tracks the constant. **But `server_config.json tick_rate` STILL OVERRIDES at runtime** (JSON wins
  for the server sim). So the JSON value and the constant must be kept in sync by hand for an honest
  test.

## How to run the 60 Hz trial (and revert)

Set **all three** of these to 60, then revert all to 30 when done:

1. `client/scripts/shared/game_constants.gd` → `const SERVER_TICK_RATE := 60.0`
   (drives the client `_physics_process` clock + `INPUT_SEND_INTERVAL`).
2. `client/data/config/server_config.json` → `"tick_rate": 60` (drives the server sim).
3. `client/data/config/server_config.json` → `"snapshot_rate_hz"`:
   - `60` (or `0` = follow tick) to test the **full** 60 Hz pipeline (input *and* snapshot), **or**
   - `30` to **isolate** the input-latency benefit from the snapshot-bandwidth cost.

   Run **both** variants so server CPU and downstream bandwidth are attributed separately.

Container override (no rebuild): `GAME_SERVER_TICK_RATE=60` in the environment overrides
`server_config.json tick_rate` at runtime (highest precedence; see `server_config.gd::_apply_env_overrides`
and `deployment/.env.example`). NOTE this moves only the **server** clock — a real client still
follows `GameConstants.SERVER_TICK_RATE`, so for an honest end-to-end test set the constant too.

**Revert = set 1, 2, 3 back to 30 / 30 / 30.** Confirm parity with the 30 Hz baseline run afterward.

### Sanity checks at each rate

- Server log prints `Server running at <N> Hz tick rate` and `Snapshot rate: <N> Hz`
  (server_main.gd:174-175).
- Bot report's `estimated_server_tick_rate` ≈ N (bot_swarm.py tick-range / duration estimate).
- A real client: `Engine.physics_ticks_per_second == N` and `INPUT_SEND_INTERVAL == 1.0 / N`.

## Tick-derived constants whose wall-clock meaning HALVES at 60 Hz

These are expressed in **ticks**, so their real-time meaning halves at 60 Hz. Each is flagged in code
with a `TICK-DERIVED:` comment; enumerated here so nothing silently changes meaning:

| Constant | @30 Hz | @60 Hz | Effect | Where |
| --- | --- | --- | --- | --- |
| `REMOTE_ENTITY_RENDER_DELAY_TICKS = 2` | 66.7 ms | 33.3 ms | Remote-smoothness margin shrinks. Adaptive (interp seeds from `SERVER_TICK_INTERVAL`), so mostly fine. | game_constants.gd |
| `MIN/MAX_RENDER_DELAY_TICKS = 1/3` | 33/100 ms | 17/50 ms | Same adaptive band, half the wall-clock. | interpolation_controller.gd |
| `MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6` | 200 ms | 100 ms | Lag-comp rewind window auto-scales (`max_compensation_seconds = TICKS / tick_rate`, server_main.gd) — PvE hits get slightly harder to land. | game_constants.gd |
| `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4` | ~133 ms | ~66.7 ms | Same auto-scale, tighter PvP rewind. | game_constants.gd |
| `DELTA_FULL_STATE_INTERVAL = 100` | ~3.3 s | ~1.7 s | Forced full baselines twice as often = more downstream bandwidth. | packet_types.gd |

**Tick-rate INVARIANT (no change):** `SHOOT_COOLDOWN = 0.3 s`, `RESPAWN_DELAY = 3.0 s`,
`INVULNERABILITY_DURATION = 3.0 s` are in seconds and the server applies them via tick-interval
accumulation, so they are unaffected by the tick rate.

## Measurement protocol

Run `load_testing/bot_swarm.py` against a server at **30 Hz**, then at **60 Hz** (both the
60-tick/60-snap and 60-tick/30-snap variants). Per run, capture from the JSON report +
`SERVER_METRICS`:

- `avg_bandwidth_per_player_kbps` — per-player downstream+upstream KB/s (bot_swarm.py bandwidth calc).
- `server_avg_tick_time_ms` / `server_max_tick_time_ms` — latest `SERVER_METRICS` snapshot
  (server_metrics.gd avg/max over the last 30 ticks).
- `estimated_server_tick_rate` — tick-range ÷ duration (bot_swarm.py).
- `server_entity_count`, `packet_loss_pct`, `crash_rate_pct` for context.

### Scenarios

Use the predefined scenarios in `bot_swarm.py` (`SCENARIOS`):

| Scenario | Bots | Duration | Purpose |
| --- | --- | --- | --- |
| `baseline` | 50 | 2 min | Basic validation |
| `target` | 100 | 5 min | The release-gate load |
| `combat` | 100 | 2 min | Constant-shooting stress (worst-case event traffic) |
| `stress` | 200 | 5 min | Find the breaking point |

(There is **no** `clustered` AoI-worst-case scenario in the harness today; `stress` at 200 is the
closest density proxy. If an AoI-clustering scenario is added, measure it here too.)

### Budgets to compare against

- **Per-player bandwidth:** `< 5 KB/s` working budget, `< 2 KB/s` aspirational
  (performance-budgets.md; ARCHITECTURE contradicts itself 2-vs-5, eng aligns on 5).
- **Server tick time:** avg `< 8 ms`, max `< 25 ms` (eng budget). The user's gate for adopting 60 Hz:
  per-player KB/s under 5 **and** server max tick time under ~16-25 ms at `target` (100 bots).

### Critical caveat — what the bot harness CANNOT measure

Bots send `PLAYER_INPUT` at a **fixed 10 Hz** (`BOT_INPUT_INTERVAL = 0.1`, bot_client.py:129),
independent of the server tick rate. So the swarm measures:

- ✅ **Server CPU** (tick time) at the higher tick rate.
- ✅ **Downstream** bandwidth doubling when `snapshot_rate_hz` follows a 60 Hz tick.

…but does **NOT** exercise:

- ❌ Real-client **upstream** packet doubling (a real client sends at `INPUT_SEND_INTERVAL`, which is
  60 Hz when `SERVER_TICK_RATE = 60`; bots stay at 10 Hz).
- ❌ Client-side **prediction/interpolation CPU** doubling (governed by `physics_ticks_per_second` on
  a real Godot client only).

**Capture those with a separate MANUAL single-client run:** launch one real client at 30, then 60,
and watch the HUD `SERVER_METRICS` channel (`bytes_received`, per-`MessageType` breakdown) plus the
engine profiler frame time and the outbound `PLAYER_INPUT` rate. Record upstream KB/s and client
frame-time delta here.

## RESULTS — PENDING MEASUREMENT

> No load runs have been captured yet. Do **not** fill these with estimates. Run the protocol above
> and paste the real numbers, then write the recommendation.

### Bot-swarm runs (server CPU + downstream)

| Scenario | Tick/Snap | est. tick rate (Hz) | per-player KB/s | avg tick ms | max tick ms | crash % | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (50) | 30 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| baseline (50) | 60 / 60 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| baseline (50) | 60 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 30 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 60 / 60 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| target (100) | 60 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| combat (100) | 30 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| combat (100) | 60 / 60 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| stress (200) | 30 / 30 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |
| stress (200) | 60 / 60 | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ | |

### Manual single-client run (upstream + client CPU)

| Tick rate | upstream PLAYER_INPUT KB/s | client frame time (ms) | subjective feel | notes |
| --- | --- | --- | --- | --- |
| 30 Hz | _pending_ | _pending_ | _pending_ | |
| 60 Hz | _pending_ | _pending_ | _pending_ | |

### Recommendation

_PENDING._ Default gate: keep **30 Hz** unless 60 Hz keeps per-player KB/s under **5** **and** server
max tick time under **~16-25 ms** at `target` (100) load. If 60 Hz only fits at `60-tick/30-snap`
(input fast, snapshot held at 30), record that as the recommended compromise.

## The eight questions

- **Client:** the client clock (`_physics_process` rate driving prediction/interpolation, and the
  `PLAYER_INPUT` send cadence) follows `GameConstants.SERVER_TICK_RATE` via
  `Engine.physics_ticks_per_second` + `INPUT_SEND_INTERVAL`.
- **Server:** the sim/snapshot loop follows `server_config.json tick_rate` / `snapshot_rate_hz` via
  the manual accumulator in `server_main.gd::_process` (`GAME_SERVER_TICK_RATE` env overrides at
  runtime).
- **Predicted:** nothing new — tick rate is a cadence, not gameplay state.
- **Replicated:** the *effect* is observable (faster snapshot stream at 60-tick/60-snap); the rate
  itself is not on the wire (clients measure inter-snapshot arrival; STATE_UPDATE carries an absolute
  `server_tick`, so no protocol change is needed for the client to adapt).
- **Persisted:** nothing; the deploy-time authority is `server_config.json` (+ optional env).
- **Validated:** `server_config.gd` clamps `snapshot_rate_hz` to `(0, tick_rate]`; the constant and
  the JSON must be kept in sync manually for an honest A/B (this doc is the checklist).
- **Can fail:** flipping only one of the three knobs → client/server cadence mismatch (server starves
  of inputs half its ticks, or client predicts at the wrong rate). At 60-tick/60-snap, downstream
  bandwidth likely breaches the 5 KB/s per-player budget at target load — the expected reason the
  default stays 30.
- **Tested:** `load_testing/bot_swarm.py` (`baseline`/`target`/`combat`/`stress`) for server CPU +
  downstream; a manual single-client run for upstream + client CPU. **Run pending.**

## See also

- [`../performance-budgets.md`](../performance-budgets.md) — the budget table this measurement updates
- [`../latency-budget.md`](../latency-budget.md) — input-sample (stage 1) + tick-wait (stage 2) that 60 Hz halves
- [`../smoothness-render.md`](../smoothness-render.md) — why interpolation, not 60 Hz, is the primary smoothness fix
- [`../server-tick-broadcast.md`](../server-tick-broadcast.md) — the tick + snapshot loop the rate governs
