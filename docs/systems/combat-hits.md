# Combat — projectiles, hits, shooting

**Status:** Partial (verified 2026-06-03 against code) — the combat loop works end-to-end, but
it has three known correctness gaps: a **paired-shots** server bug (one trigger fires twice),
**PvP hit detection** that uses no [Lag compensation](../CONTEXT.md) and a point check (tunneling
+ must-lead), and **no client shoot feedback** (full round-trip before anything is drawn).

> One shooting ability, HP only, one monster type — gameplay is deliberately minimal so the
> netcode is the thing under test. This doc is the canonical home for the shoot/hit bugs.

## Numbers

| Constant | Value | Where |
| --- | --- | --- |
| Shoot cooldown | 0.3 s | `game_constants.gd:237` (`SHOOT_COOLDOWN`) |
| Projectile speed | 400 u/s | `game_constants.gd:215` (`PROJECTILE_SPEED`) |
| Projectile radius | 8 u | `game_constants.gd:221` (`PROJECTILE_RADIUS`) |
| Player hitbox radius | 16 u | `game_constants.gd:229` (`PLAYER_HITBOX_RADIUS`) |
| Monster hitbox radius | 16 u | `game_constants.gd:291` (`MONSTER_HITBOX_RADIUS`) |
| PvP hit window | 24 u | `8 + 16` (`projectile_manager.gd:270`) |
| PvE hit window | 24 u | `8 + 16` (`projectile_manager.gd:337`) |
| Max projectile distance | 800 u | `game_constants.gd:218` (`PROJECTILE_MAX_DISTANCE`) |
| Player projectile damage | 25 | `game_constants.gd:312` |
| Monster projectile damage | 10 | `game_constants.gd:309` |
| Max PvE rewind | 6 ticks (200 ms @30 Hz) | `game_constants.gd:24` (`MAX_PVE_PROJECTILE_COMPENSATION_TICKS`) |
| Projectile entity ids | 10000–29999 | `game_constants.gd:225-226` |
| Projectile per-tick advance | ~13.3 px (400 ÷ 30) | derived |

## The shoot path (client → server → client)

The [Authoritative server](../CONTEXT.md) owns every projectile. The [Local player](../CONTEXT.md)
never spawns one; it only sends intent.

1. **Client captures intent.** `PredictionController` reads the SHOOT action in `_physics_process`
   (`prediction.gd:191`, `INPUT_FLAG_SHOOT`) and ships it inside the normal input packet at the
   server-tick cadence — `INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL` ≈ 33 ms, 30 Hz
   (`prediction.gd:71,170`). There is no separate "fire" message; the held SHOOT flag and the
   aim angle ride the input stream.
2. **Server ingests + edge-detects.** `PlayerManager.process_all_inputs` drains the *whole* input
   queue for each player into the persistent input model (`player_manager.gd:111-112`).
   `PlayerState.ingest_input` detects a rising-edge SHOOT (held last packet? vs held this packet?)
   and queues an immediate fire onto `pending_shots` (`player_state.gd:147-158`).
3. **Server fires.** `ServerMain._process_shoot_inputs` drains `pending_shots` and also continues
   held auto-fire (`server_main.gd:284-293`), calling `_try_spawn_projectile`
   (`server_main.gd:336`). That checks `can_shoot()` (cooldown gate), validates the fire origin,
   spawns via `ProjectileManager.spawn_projectile` (`projectile_manager.gd:25`), starts the 0.3 s
   cooldown (`server_main.gd:373`), and broadcasts a `PROJECTILE_FIRED` [Game event](../CONTEXT.md)
   (`server_main.gd:374`).
4. **Projectile integrates.** Each tick `ProjectileState.update` advances `position` by
   `direction * 400 * delta`, records `previous_position`, and retires on max distance /
   out-of-bounds / obstacle (`projectile_state.gd:94-128`).
5. **Client draws it.** The projectile reaches the client only via the next `STATE_UPDATE`
   [Snapshot](../CONTEXT.md): `InterpolationController` emits `entity_spawned`, and
   `ClientEntityManager._spawn_projectile` instantiates the pooled visual
   (`client_entity_manager.gd:113-114`). It is a [Remote entity](../CONTEXT.md) — interpolated
   at the fixed 66.7 ms [Render delay](../CONTEXT.md), never predicted.

## Hit detection — PvE is lag-compensated, PvP is not

This asymmetry is deliberate-by-accident: the monster path got the careful treatment, the player
path did not.

### PvE (projectile → monster): swept + rewound

`check_collisions_with_monsters` (`projectile_manager.gd:303`):

- **Rewind.** Each projectile computes `get_lag_compensated_monster_tick()` from its
  `collision_rewind_ticks` (derived from the firing client's RTT / render tick, capped at 6 ticks
  = 200 ms) and tests against a **historical** monster snapshot for that tick
  (`projectile_state.gd:143-146`, `monster_manager.record_position_snapshot`,
  `server_main.gd:241`). This is true [Lag compensation](../CONTEXT.md): the server rewinds the
  monster to the Tick the shooter actually saw.
- **Swept path.** It tests the closest point on the segment `previous_position → position`
  against the monster centre (`projectile_manager.gd:335`), so a fast projectile that *stepped
  over* a monster between ticks still registers. Hit when distance < `8 + 16 = 24`.

### PvP (projectile → player): current-tick point check, no rewind

`check_collisions_with_players` (`projectile_manager.gd:246`):

- **No rewind.** The player grid is built from `get_alive_players()` at the **current** Tick
  (`projectile_manager.gd:251`) — there is no historical player snapshot, no
  `get_lag_compensated_*` call. A well-aimed shot at a moving target can miss purely because of
  latency.
- **No sweep.** Hit is a single **point distance** check: `proj.position.distance_to(player.position)`
  (`projectile_manager.gd:269`) — only the projectile's *end-of-tick* position, not its swept
  path. Hit when distance < `8 + 16 = 24`.

**Consequences:**

- **Tunneling.** At 400 u/s ÷ 30 Hz the projectile jumps ~13.3 px/tick. With a 24 u window a
  player can be passed through in a single tick if alignment is unlucky — the point check on both
  endpoints misses the body in between.
- **Must-lead.** Because there is no rewind, the shooter has to lead targets by their own ping;
  the server checks against where the victim *is now*, not where the shooter *saw* them.

On a hit, `ServerCollisionHandler` applies damage and broadcasts a `DAMAGE` (and, if lethal,
`KILL` / PvP-`KILL`) [Game event](../CONTEXT.md) — `server_collision_handler.gd:32-59` (player),
`:76-112` (monster). Damage/kill events fire every Tick, not gated by the snapshot rate.

## No client shoot prediction / feedback

The client has **zero** local shoot feedback. `Player.gd`'s local projectile spawning is disabled
at spawn (`arena_base.gd:220`, `set_local_projectile_spawning_enabled(false)`) and never
re-enabled, and there is no predicted muzzle flash / tracer. The first thing the shooter sees is
the server's projectile arriving in a `STATE_UPDATE` (`client_entity_manager.gd:114`). So the
delay from click to any visible bullet is a **full round-trip** plus the 66.7 ms render delay —
on top of any input-send and snapshot-cadence jitter. (This is the latency half of the felt
problem; see [`../netcode/latency-budget.md`](../netcode/latency-budget.md).)

> The historical "client doubling" theory is **refuted**: the client cannot spawn a local
> projectile at all (`arena_base.gd:220`). All doubling is server-side — see below.

## Bug: paired shots (one trigger → two projectiles)

A single SHOOT press can spawn **two** projectiles on the server in one Tick. Two independent
causes, both live:

1. **Two firing paths in one tick.** `_process_shoot_inputs` fires from the drained `pending_shots`
   queue *and then* immediately fires the held-auto-fire path if `is_shoot_held() and can_shoot()`
   (`server_main.gd:286-293`). On the rising-edge Tick both can pass: the rising edge queues a
   pending shot, and `is_shoot_held()` is also already true from the same packet. The cooldown
   (`start_shoot_cooldown`, `server_main.gd:373`) is the only thing that stops the second — but it
   is only set *after* the first spawn, and both calls happen in the same `_process_shoot_inputs`
   pass, so the second `_try_spawn_projectile` re-checks `can_shoot()` against the now-started
   cooldown. (Whether the second is suppressed depends on call ordering and cooldown bookkeeping
   — the two-path structure is the latent hazard.)
2. **Multi-packet rising-edge over-count.** `process_all_inputs` drains the *entire* queued input
   list each Tick (`player_manager.gd:111`). If ≥2 input packets land in one Tick (common at
   30 Hz send into a 30 Hz tick under jitter), and the SHOOT bit toggled off→on→off→on across
   them, `ingest_input` records **multiple** rising edges into `pending_shots`
   (`player_state.gd:147-158`), and the `while` loop in `_process_shoot_inputs`
   (`server_main.gd:286-290`) spawns one projectile per queued edge — bypassing the cooldown,
   because each `pop_pending_shot` calls `_try_spawn_projectile` which only gates on `can_shoot()`
   *between* spawns within the loop.

**Fix sketch.** Make firing single-path and cooldown-authoritative:

- Coalesce to **at most one rising-edge per Tick** during ingest (collapse multiple edges from
  queued packets into one), OR gate the `pending_shots` drain by `can_shoot()` so the cooldown
  set by the first spawn suppresses the rest within the same Tick.
- Pick **one** trigger model: either edge-triggered (`pending_shots` only) or held-auto-fire
  (`is_shoot_held()` only) — not both feeding `_try_spawn_projectile` in the same pass.

## Bug: dropped first shot

The mirror failure of the over-count. Rising-edge detection compares the SHOOT bit of the *current*
packet against the *persisted* `input_flags` from the last ingested packet (`player_state.gd:148-150`).
If the very first packet that carries SHOOT also carries the *first ever* input for that player (so
`input_flags` was 0 and is now SHOOT), the edge is detected — good. But if a tap is short enough
to fall entirely *between* two server Ticks, or the off→on→off transition lands inside a single
drained batch where a *later* packet in the same batch has already cleared the bit, the persisted
`input_flags` can end the Tick with SHOOT=0 and **no** rising edge is recorded for the tap → the
first (or only) shot of a quick tap is silently dropped.

**Fix sketch.** Detect edges against a per-packet history rather than only the last-persisted flag,
so a complete press *contained within* one Tick still latches exactly one `pending_shots` entry —
the same coalescing logic that fixes the over-count, applied so a tap yields exactly one shot.

## What's missing vs. a finished combat system

- No PvP [Lag compensation](../CONTEXT.md) (no historical player snapshots). — *Planned*
- No swept PvP path (point check only). — *Planned*
- No client-side shoot prediction / muzzle feedback. — *Planned*
- Single-path, cooldown-authoritative firing (fix the paired-shots / dropped-shot pair). — *Planned*
- Only one ability, one projectile type, one monster type — intentional for the POC, **not** a gap.

## The eight questions

- **Client:** captures SHOOT + aim, sends in the input stream (30 Hz), and draws server projectiles as interpolated Remote entities — no local spawn.
- **Server:** owns all projectiles — spawn, cooldown, integration, hit detection, damage/kill Game events.
- **Predicted:** nothing in combat is predicted; the client shows no shot until the server's projectile arrives.
- **Replicated:** projectiles via `STATE_UPDATE` Snapshots; `PROJECTILE_FIRED` / `DAMAGE` / `KILL` via Game events.
- **Persisted:** nothing — kills increment in-memory counters; only the Go API persists leaderboard totals.
- **Validated:** fire origin is RTT-bounded (`server_main.gd:377-409`); cooldown gates rate; PvE rewind capped at 6 ticks; PvP uses current-tick truth.
- **Can fail:** paired shots (two firing paths + multi-packet edge over-count), dropped first shot (tap between ticks), PvP tunneling + must-lead (no sweep, no rewind), invisible-until-round-trip feedback.
- **Tested:** server-side projectile/hit diagnostics logging (`projectile_manager.gd:209-241,355`); no automated combat regression test today.

## See also

- [`../netcode/latency-budget.md`](../netcode/latency-budget.md) — the click-to-bullet round-trip and why shots feel late
- [`monsters-ai.md`](monsters-ai.md) — monster firing, AI, and the PvE side of hit detection
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how projectiles are drawn at the render delay
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — the smoothness problem felt alongside latency
