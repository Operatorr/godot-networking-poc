# Combat — projectiles, hits, shooting

**Status:** Implemented — the combat loop works end-to-end. **PvP** hit detection is
lag-compensated + swept (rewind, cap 4 ticks, mirroring PvE), and the client draws **cosmetic
muzzle flash feedback** on shoot input (damage stays server-confirmed). **Monster → player** hits are
now **client-detected + server-validated** (since 2026-06-10): the victim's own client tests incoming
monster bullets against its *predicted* position and reports them, fixing the direction-dependent
phantom-hit / pass-through feel that pure server-authoritative detection produced under prediction.
The former PvP gaps and the **paired-shots** firing hazard are resolved (see below).

> One shooting ability, HP only, one monster type — gameplay is deliberately minimal so the
> netcode is the thing under test. This doc is the canonical home for the shoot/hit bugs.

## Numbers

| Constant | Value | Where |
| --- | --- | --- |
| Shoot cooldown | 0.3 s | `game_constants.gd:258` (`SHOOT_COOLDOWN`) |
| Projectile speed | 400 u/s | `game_constants.gd:236` (`PROJECTILE_SPEED`) |
| Projectile radius | 8 u | `game_constants.gd:242` (`PROJECTILE_RADIUS`) |
| Player hitbox radius | 16 u | `game_constants.gd:250` (`PLAYER_HITBOX_RADIUS`) |
| Monster hitbox radius | 16 u | `game_constants.gd:312` (`MONSTER_HITBOX_RADIUS`) |
| PvP hit window | 24 u | `8 + 16` (`projectile_manager.gd:304`) |
| PvE hit window | 24 u | `8 + 16` (`projectile_manager.gd:371`) |
| Max projectile distance | 800 u | `game_constants.gd:239` (`PROJECTILE_MAX_DISTANCE`) |
| Player projectile damage | 25 | `game_constants.gd:333` (`PLAYER_PROJECTILE_DAMAGE`) |
| Monster projectile damage | 10 | `game_constants.gd:330` (`MONSTER_PROJECTILE_DAMAGE`) |
| Max PvE rewind | 6 ticks (200 ms @30 Hz) | `game_constants.gd:40` (`MAX_PVE_PROJECTILE_COMPENSATION_TICKS`) |
| Max **PvP** rewind | **4 ticks (~133 ms @30 Hz)** | `game_constants.gd:45` (`MAX_PVP_PROJECTILE_COMPENSATION_TICKS`) |
| Projectile entity ids | 10000–29999 | `game_constants.gd:246-247` |
| Projectile per-tick advance | ~13.3 px (400 ÷ 30) | derived |

## The shoot path (client → server → client)

The [Authoritative server](../CONTEXT.md) owns every projectile. The [Local player](../CONTEXT.md)
never spawns one; it only sends intent.

1. **Client captures intent.** `PredictionController` reads the SHOOT action in `_physics_process`
   (`prediction.gd:213`, `INPUT_FLAG_SHOOT`) and ships it inside the normal input packet at the
   server-tick cadence — `INPUT_SEND_INTERVAL = SERVER_TICK_INTERVAL` ≈ 33 ms, 30 Hz
   (`prediction.gd:78,189`). There is no separate "fire" message; the held SHOOT flag and the
   aim angle ride the input stream. On the **SHOOT rising edge** it also emits the cosmetic-only
   `shoot_predicted` signal (`prediction.gd:178`) — see "Client shoot feedback" below.
2. **Server ingests + edge-detects.** `PlayerManager.process_all_inputs` drains the *whole* input
   queue for each player into the persistent input model (`player_manager.gd:128-129`).
   `PlayerState.ingest_input` detects a rising-edge SHOOT (held last packet? vs held this packet?)
   and queues an immediate fire onto `pending_shots` (`player_state.gd:139-158`).
3. **Server fires.** `ServerMain._process_shoot_inputs` (`server_main.gd:304`) drains `pending_shots`
   first and only falls through to held auto-fire if it did not already fire this tick
   (`fired_this_tick` guard, `server_main.gd:321`), calling `_try_spawn_projectile`
   (`server_main.gd:365`). That checks `can_shoot()` (cooldown gate), validates the fire origin,
   spawns via `ProjectileManager.spawn_projectile` (`server_main.gd:393`), starts the 0.3 s
   cooldown (`server_main.gd:410`), and broadcasts a `PROJECTILE_FIRED` [Game event](../CONTEXT.md).
4. **Projectile integrates.** Each tick `ProjectileState.update` advances `position` by
   `direction * 400 * delta`, records `previous_position`, and retires on max distance /
   out-of-bounds / obstacle (`projectile_state.gd:94-128`).
5. **Client draws it.** The authoritative projectile reaches the client via the next `STATE_UPDATE`
   [Snapshot](../CONTEXT.md): `InterpolationController` emits `entity_spawned`, and
   `ClientEntityManager._spawn_projectile` instantiates the pooled visual
   (`client_entity_manager.gd:107-113`, `:265`). It is a [Remote entity](../CONTEXT.md) — interpolated
   at the [Render delay](../CONTEXT.md), never predicted. The shooter, however, already saw a
   **cosmetic muzzle flash** the instant they pressed fire (step 1) — so click-to-feedback no
   longer waits a full round-trip, even though the real bullet still does.

> **Projectile facing (Arena).** A networked projectile is process-disabled (the server owns its
> motion), so it never runs the offline pool's `activate()` rotation set. `ClientEntityManager`
> now faces it along its **interpolated travel direction** each frame (`_update_projectile_rotations`),
> seeded on spawn from the replicated direction octant (`projectile_animation_octant` decode).
> Previously Arena bullets stuck at rotation 0 (facing right) while Sanctuary bullets — spawned
> locally with `rotation = direction.angle()` — looked correct; both now match.

## Hit detection — both PvE and PvP are now lag-compensated + swept

The two paths now mirror each other: both rewind the target roster to the Tick the shooter saw and
test the projectile's swept travel segment, differing only in the rewind **cap**.

### PvE (projectile → monster): swept + rewound

`check_collisions_with_monsters` (`projectile_manager.gd:337`):

- **Rewind.** Each projectile computes `get_lag_compensated_monster_tick()` from its
  `collision_rewind_ticks` (derived from the firing client's RTT / render tick, capped at 6 ticks
  = 200 ms) and tests against a **historical** monster snapshot for that tick
  (`projectile_state.gd:149-152`, `monster_manager.record_position_snapshot`,
  `server_main.gd:253`). True [Lag compensation](../CONTEXT.md): the server rewinds the
  monster to the Tick the shooter actually saw.
- **Swept path.** It tests the closest point on the segment `previous_position → position`
  against the monster centre (`projectile_manager.gd:369`), so a fast projectile that *stepped
  over* a monster between ticks still registers. Hit when distance < `8 + 16 = 24`.

### PvP (projectile → player): swept + rewound, stricter cap (#7)

`check_collisions_with_players` (`projectile_manager.gd:273`) handles **player-fired projectiles
only** — monster-owned projectiles are skipped here (`proj.owner_id >= MONSTER_ENTITY_ID_START`) and
resolved client-side instead (next subsection). For player-fired bullets it mirrors the PvE path:

- **Rewind.** Each projectile computes `get_lag_compensated_player_tick()`
  (`projectile_state.gd:158-161`) from a **separate** `pvp_collision_rewind_ticks`, and the player
  roster is rewound to that Tick from `PlayerManager`'s position history
  (`record_position_snapshot` / `get_alive_player_snapshot`, `player_manager.gd:256-285`, recorded
  each Tick at `server_main.gd:254`). The PvP rewind is **capped stricter than PvE** at
  `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4` (~133 ms, re-clamped at `server_main.gd:382-386`) so a
  peeker who has already broken line of sight cannot be retro-hit ("shoot around corners").
- **Swept path.** Hit is the swept-segment test `_closest_point_on_segment(player.position,
  previous_position, position)` (`projectile_manager.gd:302`), not the old end-of-tick point check.
  Hit when distance < `8 + 16 = 24`. The rewound roster is queried through a spatial grid built per
  collision tick, so only nearby players are tested.

**Consequences (resolved):** tunneling and must-lead are gone — the swept path catches a projectile
that stepped over a player in one Tick, and the rewind means the server checks where the shooter
*saw* the victim, not where they are *now* (within the 4-Tick cap).

### Monster → player: client-detected + server-validated (2026-06-10)

Pure server-authoritative detection tested the bullet's *true* position against the player's *true*
position. But the client renders itself **predicted-ahead** of its authoritative position and renders
bullets **interpolated-behind** theirs, so the felt result was direction-dependent: **phantom hits
while fleeing** (true-you is behind the rendered you, nearer the bullet) and **pass-throughs while
chasing** (true-you hasn't caught the bullet the screen shows you touching). The offset is a vector
along the player's movement of size ≈ `player_speed × (prediction_lead + render_delay + transit)` —
zero at rest, which is why standing still always felt correct.

To make dodging match what the player sees, the victim's **own client** now decides these hits:

- **Client detects** (`local_hit_detector.gd`, driven from `arena_base._process` after visuals).
  Each frame it swept-tests every live **monster-owned** projectile's rendered travel segment against
  its **rendered** position (`prediction.get_rendered_position()` — where the player is actually drawn,
  **not** `predicted_position`), hit window `8 + 16 = 24`, using the shared
  `GameConstants.closest_point_on_segment`. The rendered position matters because a smooth
  reconciliation lerps the on-screen player toward `predicted_position` over several frames, so the
  prediction is briefly ahead of the screen; judging the hit there would report hits the player never
  saw. On a hit it hides the bullet locally (instant feel) and sends a `LOCAL_HIT_REPORT`
  [Game event](../CONTEXT.md) (`[u16 projectile_id]`). It learns ownership from the `PROJECTILE_FIRED`
  event, which now carries the real projectile id for monster shots (`monster_ai`/`server_main`
  propagate `last_fired_projectile_id`). The local hide is provisional: each report is tracked as
  *pending*, and if the server has not despawned the bullet within `REPORT_RESOLVE_TIMEOUT_MS` (500 ms)
  the detector un-hides it and re-arms detection — otherwise a rejected (or lost) report would leave the
  bullet permanently invisible and intangible on that client. The geometry/authority predicates live in
  the shared, unit-tested `HitAuthority` helper.
- **Server validates + applies** (`server_main._handle_local_hit_report`). The report is honoured
  only if: the projectile exists and is alive, it is monster-owned, the reporting player is alive, the
  per-peer rate limit holds (`LOCAL_HIT_REPORT_MAX_PER_SECOND = 20`), and the bullet's recent swept
  path passes within a generous radius (`24 + LOCAL_HIT_VALIDATION_MARGIN`, 64 u slack) of the
  player's **authoritative** position history (`player_manager.get_recent_positions`). It then applies
  damage through the shared `apply_player_hit` path and despawns the bullet for everyone (idempotent —
  a despawned bullet can't be re-reported). Governing rule preserved: the client *requests*, the
  server *decides*.
- **Trust trade-off (accepted):** a hacked client that never reports is effectively immune to monster
  bullets. Bounded by the validation + rate-limit; an optional lenient server backstop is noted in the
  exec plan but left off. PvP and PvE stay fully server-authoritative.

On a hit (any path), damage + a `DAMAGE` (and, if lethal, `KILL` / PvP-`KILL`)
[Game event](../CONTEXT.md) are applied via `ServerCollisionHandler.apply_player_hit`
(`server_collision_handler.gd`) for players and `_check_monster_collisions` for monsters. Damage/kill
events fire every Tick, not gated by the snapshot rate.

On a **surviving** player hit (Rust `combat::apply_player_hit`, 2026-06-12):

- **Knockback** pushes along the projectile's **travel direction** (fallback: away from the impact
  point when no direction is known) with the projectile's per-spawn `knockback_force`
  (`PLAYER/MONSTER_PROJECTILE_KNOCKBACK_FORCE`, both 450 u/s today — per-projectile so future
  weapons/items/abilities can vary it; the `apply_knockback` multiplier is the buff/debuff hook).
- A target hit **while SPRINTING** is **dazed** for `PLAYER_DAZE_DURATION` (1.5 s): sprint and dash
  locked out, walking allowed. Replicated via `ENTITY_FLAG_DAZED`; the client shows circling stars
  above the player. Applies to every player, including bots. See
  [`players-movement-state-machine.md`](players-movement-state-machine.md).

## Client shoot feedback — cosmetic muzzle flash on input (#7)

The client now draws **immediate cosmetic feedback** when the player presses fire, decoupled from the
server round-trip. `PredictionController._maybe_emit_shoot_predicted` fires the `shoot_predicted`
signal on the SHOOT **rising edge** (`prediction.gd:281-302`); `arena_base._on_local_shoot_predicted`
(`arena_base.gd:764`) plays the shoot sound and spawns a muzzle flash particle effect. This
is **cosmetic only** — `Player.gd`'s local projectile spawning stays disabled
(`arena_base.gd:244`, `set_local_projectile_spawning_enabled(false)`), so the **authoritative**
projectile still spawns only server-side and damage stays server-confirmed. The shooter no longer
stares at nothing for a full round-trip; the real bullet arrives in a later `STATE_UPDATE`
(`client_entity_manager.gd:107-113`). See [`../netcode/latency-budget.md`](../netcode/latency-budget.md).

> The historical "client doubling" theory is **refuted**: the client cannot spawn a local
> *authoritative* projectile at all (`arena_base.gd:244`) — the muzzle flash it now draws is a
> particle effect, not an entity. Any double-fire is server-side — see below.

## Resolved: paired shots (one trigger → two projectiles)

**Fixed.** `_process_shoot_inputs` (`server_main.gd:304-322`) is now **single-path and
fire-once-per-Tick.** A `fired_this_tick` latch (`:310`) makes the rising-edge drain spawn **at most
one** projectile even if multiple same-Tick edges queued onto `pending_shots`; surplus edges are
coalesced/dropped (`:315-318`). Held auto-fire only runs **if no rising-edge press already fired this
Tick** (`if not fired_this_tick and state.is_shoot_held() and state.can_shoot()`, `:321`). Since
`SHOOT_COOLDOWN` (0.3 s) makes more than one legitimate shot per 33 ms Tick impossible, collapsing
the two former firing surfaces (drained `pending_shots` **and** held auto-fire firing the same Tick)
removes the "shots come out as pairs" bug. The multi-packet rising-edge over-count is gone for the
same reason — the per-Tick latch caps it at one regardless of how many edges `ingest_input`
(`player_state.gd:139-158`) recorded from a jittery batch.

## What's missing vs. a finished combat system

- PvP [Lag compensation](../CONTEXT.md) + swept path. — ✅ *Done (#7)*
- Client-side cosmetic shoot feedback (muzzle flash). — ✅ *Done (#7)*
- Single-path, fire-once-per-Tick firing (paired-shots fix). — ✅ *Done*
- Only one ability, one projectile type, one monster type — intentional for the POC, **not** a gap.

## The eight questions

- **Client:** captures SHOOT + aim, sends in the input stream (30 Hz), draws a cosmetic muzzle flash on the shoot rising edge, draws server projectiles as interpolated Remote entities (no local *authoritative* spawn), and **detects incoming monster bullets vs. its rendered self and reports them** (`LOCAL_HIT_REPORT`).
- **Server:** owns all projectiles — spawn, cooldown, integration, lag-compensated swept PvP/PvE hit detection, validation of client monster-hit reports, damage/kill Game events.
- **Predicted:** projectile spawn/damage are never predicted (muzzle flash is cosmetic). The one thing the client now decides is **whether an incoming monster bullet hit *it*** — server-validated, not blindly trusted.
- **Replicated:** projectiles via `STATE_UPDATE` Snapshots; `PROJECTILE_FIRED` (now carrying the projectile id for monster shots) / `DAMAGE` / `KILL` via Game events; `LOCAL_HIT_REPORT` client→server.
- **Persisted:** nothing — kills increment in-memory counters; only the Go API persists leaderboard totals.
- **Validated:** fire origin is RTT-bounded; cooldown gates rate; PvE rewind capped at 6 ticks, PvP rewind capped stricter at 4 ticks (`server_main.gd:382-386`); **monster-hit reports are plausibility-checked against authoritative position history + per-peer rate-limited** (`_handle_local_hit_report`); damage is server-confirmed.
- **Can fail:** PvP rewind without a cap would let you "shoot around corners" — the 4-Tick cap is the guard; a missed lag-comp tick falls back to the nearest history snapshot (`player_manager.gd:272-285`); cosmetic muzzle can fire even if the server later rejects the shot (cooldown) — by design, it draws no damage; **a client that never sends `LOCAL_HIT_REPORT` is immune to monster bullets** (accepted trust trade-off, bounded by validation + rate-limit).
- **Tested:** the hit-authority predicates (split, client swept detection, flight reconstruction, server plausibility) have an automated headless regression — `client/scripts/test/hit_authority_test.gd` via `./scripts/run_tests.sh` — against the real `HitAuthority` helper. Server-side projectile/hit diagnostics logging remains; end-to-end PvP rewind under loss/lead still has no automated test.

## See also

- [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) — **who decides a hit**: the client-authoritative-PvE vs server-authoritative-PvP split and its anti-cheat intent
- [`../netcode/latency-budget.md`](../netcode/latency-budget.md) — the click-to-bullet round-trip and why shots feel late
- [`monsters-ai.md`](monsters-ai.md) — monster firing, AI, and the PvE side of hit detection
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how projectiles are drawn at the render delay
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — the smoothness problem felt alongside latency
