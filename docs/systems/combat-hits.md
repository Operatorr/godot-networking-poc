# Combat — projectiles, hits, shooting

**Status:** Implemented (verified 2026-06-04 against code) — the combat loop works end-to-end, and the
former PvP gaps are resolved: **PvP hit detection is now lag-compensated + swept** (rewind, cap 4
ticks, mirroring PvE), and the client draws **cosmetic muzzle/tracer feedback** on shoot input
(damage stays server-confirmed). One server-side gap remains under watch: the **paired-shots**
firing-path hazard (one trigger can fire twice) — see below.

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
   **cosmetic muzzle flash + tracer** the instant they pressed fire (step 1) — so click-to-feedback no
   longer waits a full round-trip, even though the real bullet still does.

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

`check_collisions_with_players` (`projectile_manager.gd:273`) now mirrors the PvE path:

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

On a hit, `ServerCollisionHandler` applies damage and broadcasts a `DAMAGE` (and, if lethal,
`KILL` / PvP-`KILL`) [Game event](../CONTEXT.md) — `server_collision_handler.gd:32-59` (player),
`:76-112` (monster). Damage/kill events fire every Tick, not gated by the snapshot rate.

## Client shoot feedback — cosmetic muzzle/tracer on input (#7)

The client now draws **immediate cosmetic feedback** when the player presses fire, decoupled from the
server round-trip. `PredictionController._maybe_emit_shoot_predicted` fires the `shoot_predicted`
signal on the SHOOT **rising edge** (`prediction.gd:281-302`); `arena_base._on_local_shoot_predicted`
(`arena_base.gd:764`) plays the shoot sound and spawns a muzzle flash + tracer particle effect. This
is **cosmetic only** — `Player.gd`'s local projectile spawning stays disabled
(`arena_base.gd:244`, `set_local_projectile_spawning_enabled(false)`), so the **authoritative**
projectile still spawns only server-side and damage stays server-confirmed. The shooter no longer
stares at nothing for a full round-trip; the real bullet arrives in a later `STATE_UPDATE`
(`client_entity_manager.gd:107-113`). See [`../netcode/latency-budget.md`](../netcode/latency-budget.md).

> The historical "client doubling" theory is **refuted**: the client cannot spawn a local
> *authoritative* projectile at all (`arena_base.gd:244`) — the muzzle/tracer it now draws is a
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
- Client-side cosmetic shoot feedback (muzzle/tracer). — ✅ *Done (#7)*
- Single-path, fire-once-per-Tick firing (paired-shots fix). — ✅ *Done*
- Only one ability, one projectile type, one monster type — intentional for the POC, **not** a gap.

## The eight questions

- **Client:** captures SHOOT + aim, sends in the input stream (30 Hz), draws a cosmetic muzzle/tracer on the shoot rising edge, and draws server projectiles as interpolated Remote entities — no local *authoritative* spawn.
- **Server:** owns all projectiles — spawn, cooldown, integration, lag-compensated swept hit detection, damage/kill Game events.
- **Predicted:** nothing in combat is *predicted* in the netcode sense — the client's muzzle/tracer is cosmetic only and the authoritative projectile + damage stay server-confirmed.
- **Replicated:** projectiles via `STATE_UPDATE` Snapshots; `PROJECTILE_FIRED` / `DAMAGE` / `KILL` via Game events.
- **Persisted:** nothing — kills increment in-memory counters; only the Go API persists leaderboard totals.
- **Validated:** fire origin is RTT-bounded; cooldown gates rate; PvE rewind capped at 6 ticks, PvP rewind capped stricter at 4 ticks (`server_main.gd:382-386`); damage is server-confirmed.
- **Can fail:** PvP rewind without a cap would let you "shoot around corners" — the 4-Tick cap is the guard; a missed lag-comp tick falls back to the nearest history snapshot (`player_manager.gd:272-285`); cosmetic muzzle can fire even if the server later rejects the shot (cooldown) — by design, it draws no damage.
- **Tested:** server-side projectile/hit diagnostics logging; no automated combat regression test today (the PvP rewind has no loss/lead test).

## See also

- [`../netcode/latency-budget.md`](../netcode/latency-budget.md) — the click-to-bullet round-trip and why shots feel late
- [`monsters-ai.md`](monsters-ai.md) — monster firing, AI, and the PvE side of hit detection
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how projectiles are drawn at the render delay
- [`../netcode/smoothness-render.md`](../netcode/smoothness-render.md) — the smoothness problem felt alongside latency
