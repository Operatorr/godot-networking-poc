# Hit authority — two netcodes in one arena (PvE client-authoritative, PvP server-authoritative)

**Status:** Active (as built, Rust port). The split is implemented in the authoritative Rust
`omega-server` and runs every tick; the D11 lenient backstop — which was *off* in the retired
GDScript server — is **on** in the port. This doc is the **canonical statement of intent** for
*who decides a projectile hit*. When the code disagrees with the intent below, the code wins —
fix the code or fix this doc, and say which. The mechanism here is grounded in
[`rust/sim_core/src/hit.rs`](../../rust/sim_core/src/hit.rs) (the pure predicates, shared with the
client via the GDExtension) and [`rust/server/src/sim/combat.rs`](../../rust/server/src/sim/combat.rs)
(report validation, the shared damage path, the backstop).

> Terms: [Tick](../CONTEXT.md) · [Snapshot](../CONTEXT.md) · [Render delay](../CONTEXT.md) ·
> [Lag compensation](../CONTEXT.md) · [Local player](../CONTEXT.md) · [Remote entity](../CONTEXT.md).
> The mechanics of each path live in [`../systems/combat-hits.md`](../systems/combat-hits.md); this doc
> is about **authority and why it differs by projectile owner**. The wire format for the packets named
> below is the system of record in [`../server/contract.md`](../server/contract.md).

## The intent (read this first)

This arena is **PvPvE**: you fight monsters *and* other players at the same time. A single
hit-detection model cannot serve both, because the two have opposite priorities:

- **vs. monsters (PvE): make dodging feel honest.** Dodging is the entire skill of a bullet-hell.
  The player must be able to trust their own screen — "if I see the bullet miss, it missed." The
  monster is just the server; there is no human opponent whose fairness we must also protect. So the
  **victim's own client is authoritative for whether a monster bullet hit it** (Realm-of-the-Mad-God
  model), with the server validating plausibility. This is *client-authoritative, server-validated.*
- **vs. players (PvP): make cheating impossible.** If a client could decide whether an enemy bullet
  hit it, a hacked client would simply never report being hit = god mode. Unacceptable in PvP. So
  **the server is authoritative for player-vs-player hits**, using lag compensation that favours the
  shooter. This is *server-authoritative.* The defender trades a little dodge-feel for cheat-proofing
  — an accepted, deliberate cost.

> **The GDD's blanket "PvE is client-authoritative" line is wrong / over-simplified.** Only one PvE
> direction — **monster → player** — is client-authoritative. The other PvE direction,
> **player → monster**, is fully **server-authoritative and lag-compensated**, exactly like PvP.
> Client authority is reserved for *the victim deciding their own dodge against a monster bullet*,
> nothing else. The governing rule everywhere remains: **the client requests, the server decides.**

**The load-bearing rule:** *authority is chosen per projectile, by its owner.* A monster-owned bullet
and a player-owned bullet hitting the same player are resolved by **different netcodes in the same
tick.** This is intentional, not an inconsistency. The single owner test is
`hit::is_client_authoritative(owner_id)` (`owner_id >= MONSTER_ENTITY_ID_START`, i.e. ≥ 30000) in
[`rust/sim_core/src/hit.rs`](../../rust/sim_core/src/hit.rs).

### Why monster hits felt wrong before the split (the bug that motivated this)

Server-authoritative detection compares the bullet's **true** position to the player's **true**
position. But the client renders the [Local player](../CONTEXT.md) **predicted-ahead** of its
authoritative position and renders bullets **interpolated behind** theirs
([`latency-budget.md`](latency-budget.md), [`interpolation.md`](interpolation.md)). The disagreement
is a vector along the player's movement of size ≈ `player_speed × (prediction_lead + render_delay +
transit)`:

| You are… | True-you vs. rendered-you | Server-authoritative result |
|---|---|---|
| Standing still | same place | hit lands exactly on visual contact ✓ |
| Fleeing | true-you is *behind* (nearer the bullet) | **phantom hit** while bullet looks 2–3 body-lengths back |
| Chasing into it | true-you is *behind* (hasn't caught it) | **pass-through** — you touch it on screen, no hit |

You cannot make all three views agree on the server with one timeline while the player is predicted
ahead and bullets are drawn behind. Client-authoritative PvE detection resolves it by judging the hit
in **the only frame that matters to the player — their own rendered frame.**

## The decision table (what the code implements)

| Projectile owner | Target | Authority | Where decided | Lag comp |
|---|---|---|---|---|
| **Monster** (id ≥ 30000) | Player | **Client-authoritative + server-validated**, with a **lenient backstop** | victim's client → `LocalHitReport` → `combat::handle_local_hit_report` validates; backstop applies egregious never-reports | n/a (judged in client's render frame); backstop uses authoritative swept path |
| **Player** (id 1–999) | Player | **Server-authoritative** | `ProjectileManager::check_collisions_with_players` | rewind target roster to shooter's tick, swept, **cap `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4`** |
| **Player** (id 1–999) | Monster | **Server-authoritative** | `ProjectileManager::check_collisions_with_monsters` | rewind monster roster to shooter's tick, swept, **cap `MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6`** |

Owner id ranges are the project invariant: players 1–999, projectiles 10000–29999, monsters
30000–39999, world-effect entities 40000–49999 (`sim_core::constants`,
[`../server/contract.md`](../server/contract.md)). "Monster-owned" is exactly
`hit::is_client_authoritative(owner_id)`.

## PvE / monster → player: client-authoritative + server-validated (+ backstop)

**Intent:** the bullet hits you **iff your client saw it hit your rendered self** — the position
actually drawn on screen, which is *not* always the predicted position (during a smooth
reconciliation the rendered position trails the prediction). The server's job is to (a) reject
implausible reports (anti-grief / anti-spam) and apply the damage, and (b) backstop egregious
*never-reporters* — but it must **not** re-decide a normal hit on authoritative positions (that
would reintroduce the phantom/pass-through feel).

**Flow:**

1. **Ownership reaches the client.** Monster fire broadcasts a **non-zero projectile id** in the
   `PROJECTILE_FIRED` game event (`target_id` = projectile id; see
   [`../server/contract.md`](../server/contract.md) GameEvent section — *"non-zero for monster shots
   — hit-authority invariant"*). The client records `projectile_id → monster_id` so it can tag the
   bullet monster-owned. If this id were 0 the client would never tag the bullet and the whole PvE
   path would silently no-op (you'd take *no* monster damage) — this is why the contract pins it.
2. **Client detects.** The Godot-side `LocalHitDetector` (`client/scripts/systems/combat/local_hit_detector.gd`),
   driven each render frame, swept-tests every visible **monster-owned** projectile's render-frame
   travel against the player's **rendered** position (what's drawn on screen — not the raw predicted
   position, which is ahead of the screen during a correction). The test is the shared
   `hit::swept_hit(self_pos, prev, cur, hit_radius)` predicate, exposed to GDScript through the
   `SimHit` GDExtension class so client and server run identical math. The hit window is
   `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS = 8 + 16 = 24` units.
3. **Client reports.** On a hit it hides the bullet locally for instant feel and sends `LocalHitReport`
   (`[u8 type=6][u16 projectile_id]` on ch1, reliable — see
   [`../server/contract.md`](../server/contract.md)). HP is **not** touched locally — it stays
   authoritative.
4. **Server validates + applies.** `combat::handle_local_hit_report` runs a fixed gate order
   ([`rust/server/src/sim/combat.rs`](../../rust/server/src/sim/combat.rs)): `projectile_id != 0`; reporter
   exists, is authenticated and alive; per-peer **rate limit** holds (`HitReportLimiter`,
   `LOCAL_HIT_REPORT_MAX_PER_SECOND = 20`); the projectile exists and is alive; it is **monster-owned**
   (`hit::is_client_authoritative` — *invariant #2: no PvP via client report*); and the bullet's
   reconstructed **full straight-line flight** (`hit::flight_origin(pos, dir, distance_traveled)` →
   `pos`) passes `hit::is_hit_plausible` within `LOCAL_HIT_PLAUSIBILITY_THRESHOLD` of the player's
   **authoritative** position history (`PlayerManager::get_recent_positions`,
   `POSITION_HISTORY_TICKS = 8`). On success it applies damage through the shared
   `combat::apply_player_hit` and despawns the bullet for everyone (`remove_projectile`) — idempotent,
   since a removed bullet can't be re-reported — and clears the backstop entry.
   `LOCAL_HIT_PLAUSIBILITY_THRESHOLD = PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS +
   LOCAL_HIT_VALIDATION_MARGIN = 8 + 16 + 64 = 88` units.
5. **Server does NOT run its own monster→player collision.**
   `ProjectileManager::check_collisions_with_players` early-`continue`s on
   `hit::is_client_authoritative(proj.owner_id)`. Without that skip you'd get the old phantom hit
   *and* the client report (double damage / conflicting result).

**Validation is a coarse plausibility gate, not a re-decision.** The 64 u margin deliberately absorbs
the legitimate prediction+interpolation offset. It exists to reject "a bullet across the map hit me",
not to second-guess where the client drew the contact. The Rust constant comment makes this binding:
*"strictly larger than the 24 u hit window by design (D11 invariant #4: it is NOT a hit re-check)."*
Tightening it toward the true 24 u window would re-break dodge-feel — do not.

### The D11 lenient backstop (new in the port, off in GDScript)

A hacked client that never sends `LocalHitReport` would be immune to monster bullets. The port adds a
**deliberately lenient** server backstop (`combat::Backstop` in
[`rust/server/src/sim/combat.rs`](../../rust/server/src/sim/combat.rs)) that catches only *egregious*
never-reporters, without re-introducing phantom hits:

- **Record (true 24 u overlap only).** Each tick, after projectile integration and before the
  snapshot broadcast, for every live monster-owned projectile and every alive player it records the
  *first* tick at which the bullet's **authoritative** swept path
  (`previous_position → position`) **blatantly overlaps** the player — `hit::is_backstop_overlap`,
  which tests the **TRUE 24 u window** (`HIT_BACKSTOP_OVERLAP_UNITS = PROJECTILE_RADIUS +
  PLAYER_HITBOX_RADIUS = 24`, *no looser*). This is the single predicate the backstop books on, tying
  the "blatant overlap only" rule to the owned sim_core constant.
- **Apply after grace.** A recorded overlap is only applied once it has aged past the grace window —
  `hit::backstop_grace_elapsed(overlap_tick, now, grace_ticks)`, saturating-sub so an out-of-order
  tick can't underflow. The configured `backstop_grace_ticks` (default **20**, see
  `rust/server/src/config.rs`) is **floored to `HIT_BACKSTOP_GRACE_TICKS = 15`** — the D11 minimum;
  the config validator clamps anything lower and `backstop_grace_elapsed` debug-asserts the floor.
  That grace is the window in which a legitimate client's `LocalHitReport` is expected to arrive.
- **Yield to the report.** A validated report (or any despawn — wall/range) cancels the pending
  overlap, so a normally-reported hit never double-applies. A dead victim cancels it too.
- **Id-recycle safety.** `Backstop::purge_dead` runs right after projectile integration (before
  monster AI can spawn into a freed id), and the apply path re-checks `alive` + authority, so a
  recycled id never inherits a dead bullet's pending overlap.
- Applies through the same `combat::apply_player_hit` and increments the `backstop_hits_total`
  Prometheus counter. **It must stay blatant-overlap-only**; a tight backstop would reintroduce the
  phantom-hit feel the client-authoritative path exists to prevent (invariant #4).

## PvP / player → player: server-authoritative, lag-compensated

**Intent:** the **server** decides, and a client **cannot** avoid damage by withholding or faking a
report. The model favours the **shooter's** view (standard competitive lag comp): rewind the target
to the tick the shooter saw, so a well-aimed shot on the shooter's screen connects.

- `ProjectileManager::check_collisions_with_players` handles **player-owned** projectiles only
  (it skips `hit::is_client_authoritative`). Each rewinds the player roster to
  `ProjectileState::lag_compensated_player_tick()` (derived from the shot's `pvp_collision_rewind_ticks`,
  **capped at `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4`** ≈ 133 ms) and runs the swept-segment test
  (`arena::closest_point_on_segment`, window `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS = 24`) against
  that rewound position. One target per projectile (PvP is single-hit even for piercing weapons). The
  cap bounds "shoot around corners."
- **PvP is gated by `pvp_enabled`.** In the safe **Sanctuary** instance PvP is off
  (`combat::process_collisions` skips the entire player pass): you can fire, but player bullets never
  damage players and no DAMAGE event is emitted. The **Arena** instance runs PvP on.
- The defender experiences the *same* predicted-self vs. delayed-bullet offset described above and
  **cannot** opt out of it — that asymmetry is the price of cheat-proof PvP. Mitigations are
  shooter-favouring lag comp + a tight rewind cap + the defender-favor lerp below, **not** client
  authority.
- Movement is independently server-authoritative: the server re-simulates each player from input
  flags via `sim_core::step_player` and never adopts a client-sent position as truth, so PvP hit
  resolution runs on positions the client cannot forge.

## Tuning the PvP/feel offset — dynamic and per-ping

PvP keeps the predicted-self vs. delayed-bullet offset (the defender can't opt out without enabling
cheating). It is shrunk and rebalanced with three server-authoritative levers, **all already
per-player / per-ping** — there is no single global ping knob, and that's correct:

1. **Lag-comp rewind is per-SHOOTER, per-shot (live).** Each shot's rewind is derived from *that
   shooter's* latency by `world::pve_compensation` (`rust/server/src/sim/world.rs`): it resolves the
   `client_render_tick` the client stamps on every `PlayerInput` against the server tick counter (16-bit
   wrap-corrected), falling back to an RTT estimate (`2 + ceil((rtt/2)/tick_ms)`). It returns both the
   PvE rewind (cap 6) and the PvP rewind (`min(rewind, 4)`). So a 90 ms shooter rewinds the target
   roster further than a 10 ms shooter; the *defender's* ping does not change how a given shot resolves.
2. **Render delay is per-CLIENT, jitter-driven (live).** Each client sizes its own interpolation buffer
   to its own measured *jitter* (see [`interpolation.md`](interpolation.md)). A clean link draws bullets
   ~1 tick behind; a jittery link buffers more. It tracks **jitter, not raw ping** — a *stable* 90 ms
   link needs no more buffer than a stable 10 ms one, because the buffer only hides arrival-time variance.
3. **Defender compensation `PVP_DEFENDER_FAVOR` (sim_core constant, default `0.25`).** In
   `check_collisions_with_players` the *tested* defender position is lerped from the shooter-rewound
   snapshot toward the defender's **current authoritative** position by `PVP_DEFENDER_FAVOR`
   (`lerp_vec(snap.position, live.position, PVP_DEFENDER_FAVOR)`). `0.0` = pure favour-shooter; `1.0` =
   test at the defender's live position. It softens "hit after I dodged" for the defender at a small
   cost to shooter precision, with **no client trust**. It is implicitly ping-scaled: a high-ping
   defender was rewound further, so the same factor pulls them a larger distance.

**Why no single "combined-ping" formula.** You can't put both players on one timeline (the offset
exists precisely because their predicted/interpolated frames differ). The honest model is: favour the
shooter (lever 1), shrink everyone's offset to the jitter floor (lever 2), and hand a tunable slice of
fairness back to the defender (lever 3). Levers 1–2 are the safe, always-on wins; lever 3 is a
deliberate shooter-vs-defender trade. **None of these is client-authoritative** — that line is
reserved for the monster→player path only.

## PvE / player → monster: server-authoritative, lag-compensated

Same shape as PvP but against the monster roster: `ProjectileManager::check_collisions_with_monsters`,
`ProjectileState::lag_compensated_monster_tick()`, **cap `MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6`**
(≈ 200 ms), window `PROJECTILE_RADIUS + MONSTER_HITBOX_RADIUS`. Monsters never need cheat-proofing the
way players do, so the cap is looser. Piercing weapons can hit up to `pierce` distinct monsters
(`hit_targets` dedup); non-piercing is single-hit. Damage is applied via `combat::apply_monster_damage`,
which also broadcasts `KILL` and grants server-authoritative XP on a kill. **This is the PvE direction
the GDD's "client-authoritative" line gets wrong — it is fully server-side.**

## PvPvE coexistence — what must stay true

In one tick a player can be grazed by a monster bullet **and** an enemy player's bullet. They take
**different code paths** and that is correct:

- The monster bullet: not in `check_collisions_with_players` (skipped), resolved only by the victim's
  `LocalHitReport` — or, for a never-reporter, by the backstop.
- The enemy player's bullet: resolved by `check_collisions_with_players` server-side, lag-compensated.

`combat::apply_player_hit` is the single shared damage path for **all** of them (PvP collision,
validated client report, and the backstop), so DAMAGE/KILL/KILL_PVP broadcasting, knockback (along the
projectile's *travel* direction), and the sprint→daze rule are identical regardless of which path
confirmed the hit. Damage is selected by owner-id range inside that function
(`MONSTER_PROJECTILE_DAMAGE = 10` for monster-owned, else `PLAYER_PROJECTILE_DAMAGE = 25` /
per-projectile scaled).

## Anti-cheat properties (and the one remaining hole, now narrowed)

| Vector | PvE monster→player (client-auth) | PvP & player→monster (server-auth) |
|---|---|---|
| Refuse damage (never report) | **narrowed** — the lenient backstop still lands *blatant* overlaps (true 24 u, after grace); only *grazes* go unpunished | impossible — server decides |
| Fake a hit on someone else | impossible — a report applies only to the *reporting* peer's own entity (invariant #2) | n/a |
| Claim an impossible hit on self | rejected by plausibility (full-flight vs. 8-tick history) + rate limit | n/a |
| Forge position to dodge | n/a (your own render frame is the point) | impossible — server re-simulates movement from inputs |
| "Shoot around corners" | n/a | bounded by the rewind cap (PvP 4 ticks / PvE 6 ticks) |

The **remaining (narrowed) hole:** a hacked client that never reports can still dodge *grazing*
monster hits (anything that doesn't blatantly overlap within 24 u). This is inherent to RotMG-style
PvE and is the deliberate cost of dodge-feel; the backstop bounds the abuse to grazes only. It does
**not** touch PvP.

## Intended invariants (check the code against these)

A future agent should be able to grep these against `rust/` and confirm the implementation matches:

1. `ProjectileManager::check_collisions_with_players` **must** early-`continue` on
   `hit::is_client_authoritative(proj.owner_id)`. Removing the skip double-applies monster hits.
2. `combat::handle_local_hit_report` **must** reject non-monster-owned projectiles
   (`hit::is_client_authoritative`) and **must** apply to the *reporting* peer's own entity only —
   never a target id from the client.
3. Monster `PROJECTILE_FIRED` **must** carry a non-zero projectile id, or the client never tags the
   bullet monster-owned and the whole PvE path silently no-ops (you'd take *no* monster damage).
4. The plausibility threshold (`LOCAL_HIT_PLAUSIBILITY_THRESHOLD`) and the backstop overlap window
   (`HIT_BACKSTOP_OVERLAP_UNITS`) are two distinct constants: the former (88 u) is a generous
   anti-grief bound and **must** stay strictly larger than the 24 u hit window; the latter (24 u) is
   the true window and **must not** be loosened — it keeps the backstop blatant-overlap-only.
5. The backstop grace **must not** drop below `HIT_BACKSTOP_GRACE_TICKS = 15` (config-clamped +
   debug-asserted), so a legitimate client always has time to report before the backstop fires.
6. PvP and player→monster hit detection **must** remain entirely server-side and lag-compensated;
   never route them through `LocalHitReport`.
7. The client hit test **must** use the **rendered** local-player position (what's on screen), not the
   raw predicted position. The two diverge during a smooth correction; testing against the prediction
   would judge the hit in a frame the player never saw.

## Where the rules live (single source per concern)

The load-bearing predicates are centralized so they can only drift in one place:

- **Pure predicates** — `is_client_authoritative`, `swept_hit`, `flight_origin`, `is_hit_plausible`,
  `is_backstop_overlap`, `backstop_grace_elapsed` — live in
  [`rust/sim_core/src/hit.rs`](../../rust/sim_core/src/hit.rs) and are unit-tested there. They are
  shared with the Godot client through the `SimHit` GDExtension class (compiled from the *same* crate),
  so client detection and server validation cannot diverge.
- **Server validation, shared damage path, and the backstop** live in
  [`rust/server/src/sim/combat.rs`](../../rust/server/src/sim/combat.rs), tested by the module's own suite
  (report-applies-to-reporter-only, rejects-player-owned, rejects-implausible, rate-limit window,
  backstop-after-grace, backstop-yields-to-report, id-recycle safety, knockback direction, sprint daze,
  invulnerable no-op, PvP-disabled skip, kill broadcast).
- **Lag-compensated collision passes** live in `rust/server/src/sim/projectile.rs`; the per-shot rewind
  derivation is `world::pve_compensation` in `rust/server/src/sim/world.rs`.

## The eight questions

- **Client:** detects incoming **monster** bullets vs. its **rendered** self (shared `SimHit` swept
  test) and reports them (`LocalHitReport`); draws all projectiles as interpolated Remote entities;
  never decides PvP or player→monster hits.
- **Server:** owns all projectiles; decides **PvP** and **player→monster** hits (lag-compensated,
  swept); **validates** monster→player reports and applies damage; runs the **lenient backstop** for
  never-reporters; broadcasts DAMAGE/KILL/KILL_PVP. The only authoritative server is the Rust
  `omega-server`.
- **Predicted:** the local player's movement (via the shared `PredictionSim`) and cosmetic VFX. The
  client's monster-hit decision is *authoritative-pending-validation*, not prediction, and is judged at
  the **rendered** position (which trails the prediction during a correction).
- **Replicated:** projectiles via Snapshots; `PROJECTILE_FIRED` (carrying the projectile id) / DAMAGE /
  KILL / KILL_PVP via GameEvents; `LocalHitReport` client→server.
- **Persisted:** nothing — gameplay state is server-authoritative and in-memory; only the Go API
  persists accounts/characters/leaderboard/progression.
- **Validated:** monster→player reports gated by alive/auth/owner/rate-limit/full-flight-plausibility;
  PvP and player→monster hits by rewind caps + server-authoritative movement; the backstop by
  true-24 u overlap + grace floor; all damage is server-applied through `apply_player_hit` /
  `apply_monster_damage`.
- **Can fail:** a non-reporting client still dodges *grazing* monster bullets (the backstop only lands
  blatant overlaps); a missing/zero monster projectile id silently disables PvE-on-player; PvP defender
  dodge-feel is offset by design.
- **Tested:** the predicates are unit-tested in `rust/sim_core/src/hit.rs`; the validation/backstop/
  damage paths in `rust/server/src/sim/combat.rs`; the collision passes in `rust/server/src/sim/projectile.rs`.
  Run `cd rust && cargo test --workspace`. End-to-end client↔server behaviour is verified by play-test
  and the net smoke scene.

## See also

- [`../systems/combat-hits.md`](../systems/combat-hits.md) — the shoot/hit mechanics for every path.
- [`../server/contract.md`](../server/contract.md) — the wire format for `PROJECTILE_FIRED`,
  `LocalHitReport`, `PlayerInput` (the stamped render tick / RTT), and DAMAGE/KILL events.
- [`latency-budget.md`](latency-budget.md) — why the predicted/interpolated offset exists.
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md) — the two
  timelines that make the offset.
- [`overview.md`](overview.md) — authority model & packet map.
