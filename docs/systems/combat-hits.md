# Combat — projectiles, hits, shooting

**Status:** Implemented in the Rust **`omega-server`** (the only authoritative server; the GDScript
headless server is retired). The combat loop works end-to-end. **Player → monster (PvE)** and
**PvP** hits are server-authoritative, **lag-compensated** (rewind the target roster to the Tick the
shooter saw) and **swept** (test the projectile's travel segment, not just its end-of-tick point).
**Monster → player** hits use a different netcode: **client-detected + server-validated** (RotMG
dodge-feel) with a **lenient blatant-overlap-only backstop** (true 24 u overlap, grace ≥ 15 ticks)
that catches egregious never-reporters. The geometry predicates that decide every hit live in one
shared, unit-tested crate ([`rust/sim_core/src/hit.rs`](../../rust/sim_core/src/hit.rs)) compiled
into BOTH the server and the client (via the `SimHit` GDExtension), so client detection and server
validation cannot drift. Governing rule everywhere: **the client requests, the server decides.**

> One shooting ability, HP only, one monster type — gameplay is deliberately minimal so the
> netcode is the thing under test. The wire/transport spec is [`docs/server/contract.md`](../server/contract.md).

## Numbers

All combat constants live in [`rust/sim_core/src/constants.rs`](../../rust/sim_core/src/constants.rs)
— a single source shared by server, client prediction, and the load-test bots.

| Constant | Value | Symbol |
| --- | --- | --- |
| Shoot cooldown | 0.3 s | `SHOOT_COOLDOWN` |
| Player projectile speed | 400 u/s | `PROJECTILE_SPEED` |
| Monster projectile speed | 300 u/s | `MONSTER_PROJECTILE_SPEED` |
| Projectile radius | 8 u | `PROJECTILE_RADIUS` |
| Player hitbox radius | 16 u | `PLAYER_HITBOX_RADIUS` |
| Monster hitbox radius | 16 u | `MONSTER_HITBOX_RADIUS` |
| Hit window (PvP & PvE) | 24 u | `PROJECTILE_RADIUS + PLAYER/MONSTER_HITBOX_RADIUS` |
| Max projectile distance | 800 u | `PROJECTILE_MAX_DISTANCE` |
| Player projectile damage (flat fallback) | 25 | `PLAYER_PROJECTILE_DAMAGE` |
| Monster projectile damage | 10 | `MONSTER_PROJECTILE_DAMAGE` |
| Max PvE rewind | 6 ticks (200 ms @30 Hz) | `MAX_PVE_PROJECTILE_COMPENSATION_TICKS` |
| Max **PvP** rewind | **4 ticks (~133 ms @30 Hz)** | `MAX_PVP_PROJECTILE_COMPENSATION_TICKS` |
| PvP defender-favor lerp | 0.25 | `PVP_DEFENDER_FAVOR` |
| Knockback force (player & monster bullets) | 450 u/s | `PLAYER/MONSTER_PROJECTILE_KNOCKBACK_FORCE` |
| Daze on hit while sprinting | 1.5 s | `PLAYER_DAZE_DURATION` |
| Backstop overlap window | 24 u (true, no looser) | `HIT_BACKSTOP_OVERLAP_UNITS` |
| Backstop grace floor | 15 ticks | `HIT_BACKSTOP_GRACE_TICKS` |
| Local-hit-report rate cap | 20 / s / peer | `LOCAL_HIT_REPORT_MAX_PER_SECOND` (`combat.rs`) |
| Local-hit plausibility slack | +64 u (⇒ 88 u bound) | `LOCAL_HIT_VALIDATION_MARGIN` (`combat.rs`) |
| Projectile entity ids | 10000–29999 | `PROJECTILE_ENTITY_ID_START/_END` |
| XP share radius (kill credit) | 500 u | `XP_SHARE_RADIUS` |
| Projectile per-tick advance | ~13.3 u (400 ÷ 30) | derived |

> Player primary shots carry a **per-projectile** class+level-scaled damage value
> (`PlayerState::primary_damage`, [`rust/server/src/sim/player.rs`](../../rust/server/src/sim/player.rs));
> the flat `PLAYER_PROJECTILE_DAMAGE` is only the `damage == 0` fallback in the PvE pass
> (`combat::process_collisions`). Ability projectiles set their own value. See
> [`abilities.md`](abilities.md).

## The shoot path (client → server → client)

The Rust [Authoritative server](../CONTEXT.md) owns every projectile. The [Local player](../CONTEXT.md)
never spawns an authoritative one; it only sends intent over ENet channel 2 (input). There is no
separate "fire" message — the held SHOOT flag and the aim angle ride the input stream.

1. **Client captures intent.** `PredictionController` reads the SHOOT action and ships it inside the
   normal input packet at the server-tick cadence (~33 ms, 30 Hz)
   (`client/scripts/network/prediction.gd`, `INPUT_FLAG_SHOOT`). On the SHOOT **rising edge** it also
   emits a cosmetic-only `shoot_predicted` signal — see "Client shoot feedback" below.
2. **Server ingests + edge-detects.** Each tick `PlayerManager::process_all_inputs` drains the input
   queue into the persistent input model. `PlayerState::ingest_input`
   ([`rust/server/src/sim/player.rs`](../../rust/server/src/sim/player.rs)) detects a rising-edge SHOOT
   (`is_shooting && !was_shooting`) and queues a `PendingShot` (aim angle + claimed origin) onto
   `pending_shots`.
3. **Server fires (single-path, fire-once-per-Tick).** `World::process_shoot_inputs`
   ([`rust/server/src/sim/world.rs`](../../rust/server/src/sim/world.rs)) drains `pending_shots` first; a
   `fired_this_tick` latch makes it spawn **at most one** projectile per Tick (surplus same-Tick edges
   are dropped). Held auto-fire runs **only if** no rising-edge press already fired this Tick
   (`!fired_this_tick && state.is_shoot_held() && state.can_shoot()`). `try_spawn_projectile` then
   checks `can_shoot()` (cooldown + alive + authenticated), validates the fire origin
   (`validated_fire_origin`, RTT-bounded muzzle clamp), computes the per-shot rewind ticks
   (`pve_compensation`), spawns via `ProjectileManager::spawn_projectile_ex`
   ([`rust/server/src/sim/projectile.rs`](../../rust/server/src/sim/projectile.rs)), starts the 0.3 s
   cooldown (`start_shoot_cooldown`), and broadcasts a `PROJECTILE_FIRED`
   [Game event](../CONTEXT.md) (event type 12) carrying the muzzle position and the projectile id.
4. **Projectile integrates.** Each tick `ProjectileState::update` records `previous_position`,
   advances `position` by `direction * speed * delta`, accumulates `distance_traveled`, and retires
   on **max distance → out-of-bounds → obstacle** (exact check order; an obstacle hit clamps
   `position` to the wall-contact point). See `projectile.rs`.
5. **Client draws it.** The authoritative projectile reaches the client in the next
   [Snapshot](../CONTEXT.md) (`ServerPacket::Snapshot` on ENet channel 0, unreliable-sequenced):
   the client spawns the pooled visual and interpolates it at the [Render delay](../CONTEXT.md) —
   it is a [Remote entity](../CONTEXT.md), never predicted. The shooter already saw a **cosmetic
   muzzle flash** the instant they pressed fire (step 1), so click-to-feedback no longer waits a full
   round-trip even though the real bullet does.

## Hit detection — three passes per Tick

The world tick (`World::tick`, `world.rs`) runs collisions in a fixed order **after** movement and
projectile integration, and **after** recording the lag-comp position history for that Tick:

1. **PvE** (`combat::process_collisions` → `ProjectileManager::check_collisions_with_monsters`).
2. **PvP** (same call → `check_collisions_with_players`; skipped entirely when `pvp_enabled` is
   false, e.g. the safe Sanctuary).
3. **D11 backstop** (`Backstop::update`) — the monster→player safety net.

Monster→player live hits are NOT in this server loop — they arrive as client `LOCAL_HIT_REPORT`
messages handled out-of-band (`combat::handle_local_hit_report`).

### Why authority is split (the two-netcode model)

The owner-id range decides the netcode (`hit::is_client_authoritative`, `sim_core/src/hit.rs`):
a projectile is **client-authoritative iff it is monster-owned** (`owner_id >= MONSTER_ENTITY_ID_START`,
i.e. 30000+). Everything player-fired (PvP and player→monster) stays server-authoritative.

Pure server-authoritative detection of monster bullets tested the bullet's *true* position against
the player's *true* position. But the client renders itself **predicted-ahead** of its authoritative
position and renders bullets **interpolated-behind** theirs, so the felt result was
direction-dependent: **phantom hits while fleeing** and **pass-throughs while chasing**, zero error
at rest. To make dodging match what the player sees, the victim's **own client** decides incoming
monster-bullet hits, and the server validates rather than re-simulates.

> The GDD's blanket "PvE is client-authoritative" line is imprecise. Only **monster → player** is
> client-detected; **player → monster** PvE is fully server-authoritative + lag-compensated.

### Player → monster (PvE): server-authoritative, swept + rewound

`ProjectileManager::check_collisions_with_monsters` (`projectile.rs`):

- **Monster-owned bullets are skipped** (`owner_id >= MONSTER_ENTITY_ID_START`).
- **Rewind.** Each projectile computes `lag_compensated_monster_tick()` from its
  `collision_rewind_ticks` (derived per-shot in `pve_compensation`, capped at
  `MAX_PVE_PROJECTILE_COMPENSATION_TICKS` = 6) and tests against the **historical** monster roster
  for that Tick (`MonsterManager::get_alive_snapshot`, recorded each Tick by
  `record_position_snapshot`). True [Lag compensation](../CONTEXT.md): the server rewinds the monster
  to the Tick the shooter actually saw.
- **Swept path.** It tests `arena::closest_point_on_segment(monster, prev_pos, cur_pos)` against the
  monster centre, so a fast projectile that *stepped over* a monster between ticks still registers.
  Hit when distance < `PROJECTILE_RADIUS + MONSTER_HITBOX_RADIUS = 24`.
- **Pierce.** `pierce <= 1` ⇒ single-hit; `pierce N > 1` ⇒ passes through up to N monsters (Void
  Hunter multishot), tracked in `hit_targets` so each monster is hit at most once.
- Damage routes through `combat::apply_monster_damage`, which broadcasts the applied `DAMAGE` event,
  and on a kill the `KILL` event plus server-authoritative XP to every alive player within
  `XP_SHARE_RADIUS` (`grant_kill_experience` — full reward, no split; level-ups recompute
  class+level stats and emit a `PROGRESS` event + cosmetic `EXP_GAIN` floater).

### PvP (player → player): server-authoritative, swept + rewound, stricter cap, defender-favor

`ProjectileManager::check_collisions_with_players` (`projectile.rs`) handles **player-fired
projectiles only** (monster-owned are skipped — D11 invariant #1):

- **Rewind.** Computes `lag_compensated_player_tick()` from a **separate**
  `pvp_collision_rewind_ticks`, and rewinds the roster via `PlayerManager::get_alive_snapshot`. The
  PvP rewind is **capped stricter than PvE** at `MAX_PVP_PROJECTILE_COMPENSATION_TICKS` = 4 (~133 ms,
  `min`-clamped in `pve_compensation`) so a peeker who has already broken line of sight cannot be
  retro-hit ("shoot around corners").
- **Defender-favor.** Before the test, the rewound position is lerped 25% (`PVP_DEFENDER_FAVOR`)
  toward the victim's **live** position — a small bias to the dodger when rewind and present disagree.
- **Swept path.** `arena::closest_point_on_segment`; hit when distance < 24. The shooter is never hit
  by their own bullet, and PvP is single-hit even for piercing projectiles.
- On a hit, `combat::apply_player_hit` applies damage, broadcasts `DAMAGE`, and on a lethal hit a
  `KILL_PVP` event (event type 10) + a leaderboard `record_pvp_kill` + `LEADERBOARD_UPDATE`
  broadcast.

### Monster → player: client-detected + server-validated

- **Client detects** (`client/scripts/systems/combat/local_hit_detector.gd`). Each frame it swept-tests every
  live **monster-owned** projectile's rendered travel segment against its **rendered** self position
  (where the player is actually drawn, not the prediction lead), via the shared
  `SimHit.swept_hit` / `SimHit.is_client_authoritative` GDExtension predicates
  (`rust/client_ext/src/lib.rs`, backed by `sim_core/src/hit.rs`). On a hit it hides the bullet
  locally and sends a `LOCAL_HIT_REPORT` (`SimHit`/`ProtocolCodec.encode_local_hit_report`, ENet
  channel 1 reliable, `[u16 projectile_id]`). It learns ownership from `PROJECTILE_FIRED`, which
  carries the projectile id for monster shots (`world.rs` fire-event broadcast). The local hide is
  provisional and self-heals if the server never despawns the bullet.
- **Server validates + applies** (`combat::handle_local_hit_report`, `combat.rs`). The exact gate
  order: projectile id non-zero → reporter authenticated + alive → per-peer rate limit
  (`HitReportLimiter`, 20/s) → projectile exists + alive → `hit::is_client_authoritative` (no PvP via
  client report — invariant #2) → `hit::is_hit_plausible`: the bullet's reconstructed straight-line
  flight (`hit::flight_origin`) must pass within `LOCAL_HIT_PLAUSIBILITY_THRESHOLD` (8 + 16 + 64 =
  88 u) of the reporter's **authoritative** recent position history
  (`PlayerManager::get_recent_positions`). Any failure silently drops the report. On success it
  applies the hit to the **reporting peer's own entity only** through the shared `apply_player_hit`
  path and despawns the bullet (idempotent). This bound is deliberately **larger** than the 24 u hit
  window: it is an anti-grief plausibility check, NOT a hit re-check.
- **D11 lenient backstop** (`combat::Backstop`, `combat.rs`) — NEW code (it was **off** in GDScript,
  **ON** in the Rust port). Each tick it records the first **blatant** overlap of a live
  monster-owned bullet's authoritative swept path with a player — within the **true 24 u** window
  only (`hit::is_backstop_overlap` → `HIT_BACKSTOP_OVERLAP_UNITS`, no looser). If no
  `LOCAL_HIT_REPORT` despawns that bullet within the grace period
  (`hit::backstop_grace_elapsed`, floor `HIT_BACKSTOP_GRACE_TICKS` = 15 ticks, configurable up via
  `backstop_grace_ticks`), it applies the hit through the same shared path and increments
  `backstop_hits_total`. It must stay blatant-overlap-only; a tighter backstop would reintroduce the
  phantom-hit feel the client-authoritative path exists to prevent. `purge_dead` runs right after
  projectile integration so an id recycled by a same-tick monster spawn cannot inherit a dead
  bullet's pending overlap.
- **Trust trade-off (accepted):** a hacked client that never reports is effectively immune to monster
  bullets *between backstop firings* — the backstop bounds the abuse to blatant overlaps. PvP and
  player→monster PvE stay fully server-authoritative.

### On a hit (shared path) — damage, knockback, daze, kills

Every player hit (PvP collision, validated client report, and the backstop) resolves through the one
shared `combat::apply_player_hit` (`combat.rs`):

- **Damage** is selected by owner-id range (monster-owned ⇒ `MONSTER_PROJECTILE_DAMAGE`, else
  `PLAYER_PROJECTILE_DAMAGE`). `DAMAGE` broadcasts the **applied** delta; **zero applied**
  (dead/invulnerable target) ⇒ **no event at all**.
- **Knockback** (survival only) pushes along the projectile's **travel direction** (fallback:
  away-from-impact when no direction is known) with the projectile's per-spawn `knockback_force`
  (450 u/s today; the `apply_knockback` multiplier is the buff/debuff hook). Travel direction beats
  away-from-impact because the discrete-tick overlap test can place the impact point past the
  target's centre, which made away-from-impact feel random.
- **Daze** (survival only): a target hit **while SPRINTING** is dazed for `PLAYER_DAZE_DURATION`
  (1.5 s) — sprint and dash locked out, walking allowed (replicated via `ENTITY_FLAG_DAZED`; the
  client shows circling stars). See
  [`players-movement-state-machine.md`](players-movement-state-machine.md).
- **Kill** (lethal): `broadcast_player_kill` emits `KILL_PVP` (PvP) and credits the killer +
  leaderboard, or `KILL` (monster killer). A PvP self-hit and an unauthenticated killer are guarded.

Damage/kill events fire every Tick, not gated by the snapshot rate.

## Client shoot feedback — cosmetic muzzle flash on input

The client draws **immediate cosmetic feedback** when the player presses fire, decoupled from the
server round-trip. `PredictionController` fires the `shoot_predicted` signal on the SHOOT **rising
edge** (`client/scripts/network/prediction.gd`); the arena plays the shoot sound and spawns a muzzle
flash particle. This is **cosmetic only** — the client cannot spawn a local *authoritative*
projectile, so the real bullet still spawns server-side and damage stays server-confirmed. The
shooter no longer stares at nothing for a full round-trip; the real bullet arrives in a later
Snapshot. See [`../netcode/latency-budget.md`](../netcode/latency-budget.md).

## What's missing vs. a finished combat system

- Lag-compensated swept PvE and PvP. — ✅ *Done*
- Two-netcode monster→player (client-detect + server-validate + D11 backstop). — ✅ *Done (port)*
- Client-side cosmetic shoot feedback (muzzle flash). — ✅ *Done*
- Single-path, fire-once-per-Tick firing (paired-shots fix). — ✅ *Done*
- Only one primary ability, with one RMB class ability per class (Warrior/Rogue/Mage in pre-alpha
  scope) and one monster type — intentional for the POC, **not** a gap.

## The eight questions

- **Client:** captures SHOOT + aim, sends in the input stream (30 Hz, ENet ch2), draws a cosmetic
  muzzle flash on the rising edge, draws server projectiles as interpolated Remote entities (no local
  *authoritative* spawn), and **detects incoming monster bullets vs. its rendered self and reports
  them** (`LOCAL_HIT_REPORT`) using the shared `SimHit` predicates.
- **Server:** owns all projectiles — spawn, cooldown, integration, lag-compensated swept PvE/PvP hit
  detection, validation of client monster-hit reports, the D11 backstop, damage/knockback/daze, and
  damage/kill/XP Game events.
- **Predicted:** projectile spawn/damage are never predicted (muzzle flash is cosmetic). The one
  thing the client decides is **whether an incoming monster bullet hit *it*** — server-validated, not
  blindly trusted.
- **Replicated:** projectiles via `Snapshot` packets (ch0); `PROJECTILE_FIRED` / `DAMAGE` / `KILL` /
  `KILL_PVP` / `EXP_GAIN` / `PROGRESS` / `LEADERBOARD_UPDATE` via Game events; `LOCAL_HIT_REPORT`
  client→server (ch1).
- **Persisted:** nothing gameplay-side — kills increment in-memory counters; only the Go API persists
  leaderboard/character totals (progression write-back marks `progression_dirty`).
- **Validated:** fire origin is RTT-bounded (`validated_fire_origin`); cooldown gates rate; PvE rewind
  capped at 6 ticks, PvP rewind capped stricter at 4 ticks (`pve_compensation`); **monster-hit
  reports are plausibility-checked against authoritative position history + per-peer rate-limited**
  (`handle_local_hit_report`); the D11 backstop catches blatant unreported overlaps; damage is
  server-confirmed.
- **Can fail:** PvP rewind without a cap would let you "shoot around corners" — the 4-Tick cap is the
  guard; **a client that never sends `LOCAL_HIT_REPORT` is immune to monster bullets between backstop
  firings** (accepted trust trade-off, bounded by the backstop + validation + rate-limit); a cosmetic
  muzzle flash can draw even if the server later rejects the shot (cooldown) — by design, it carries
  no damage.
- **Tested:** the shared hit predicates have unit tests in
  [`rust/sim_core/src/hit.rs`](../../rust/sim_core/src/hit.rs) (authority split, swept-hit strictness,
  flight reconstruction, plausibility, backstop overlap + grace floor); the server damage/report/
  backstop paths have integration tests in
  [`rust/server/src/sim/combat.rs`](../../rust/server/src/sim/combat.rs) (reporter-only application,
  no-PvP-via-report, implausible-flight rejection, rate limiter, backstop apply/yield/recycle,
  knockback direction, sprint-daze, invulnerable no-event, PvP-disabled skip, kill broadcast); and the
  projectile passes are tested in
  [`rust/server/src/sim/projectile.rs`](../../rust/server/src/sim/projectile.rs). The client mirror keeps
  `client/scripts/test/hit_authority_test.gd`. Run with `cd rust && cargo test --workspace`.

## See also

- [`../netcode/hit-authority-model.md`](../netcode/hit-authority-model.md) — **who decides a hit**:
  the canonical statement of intent for the two-netcode (PvE client-authoritative monster bullets vs
  server-authoritative PvP) split, its anti-cheat reasoning, and the D11 invariants.
- [`../server/contract.md`](../server/contract.md) — the as-built wire format, channel plan, packet
  types, and numerics policy.
- [`../netcode/latency-budget.md`](../netcode/latency-budget.md) — the click-to-bullet round-trip and
  why shots feel late.
- [`monsters-ai.md`](monsters-ai.md) — monster firing and AI (the source of monster-owned bullets).
- [`abilities.md`](abilities.md) — RMB class abilities that spawn projectiles / damage monsters.
- [`../netcode/interpolation.md`](../netcode/interpolation.md) — how projectiles are drawn at the
  render delay.
