# Hit authority — two netcodes in one arena (PvE client-authoritative, PvP server-authoritative)

**Status:** Partial — the split is built and live; the monster→player path is under play-test
verification (debug tracing on, see "Known mismatches"). This doc is the **canonical statement of
intent** for *who decides a projectile hit*. When the code disagrees with the intent below, the code
wins — fix the code or fix this doc, and say which.

> Terms: [Tick](../CONTEXT.md) · [Snapshot](../CONTEXT.md) · [Render delay](../CONTEXT.md) ·
> [Lag compensation](../CONTEXT.md) · [Local player](../CONTEXT.md) · [Remote entity](../CONTEXT.md).
> The mechanics of each path live in [`../systems/combat-hits.md`](../systems/combat-hits.md); this doc
> is about **authority and why it differs by projectile owner**.

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

**The load-bearing rule:** *authority is chosen per projectile, by its owner.* A monster-owned bullet
and a player-owned bullet hitting the same player are resolved by **different netcodes in the same
frame.** This is intentional, not an inconsistency.

### Why monster hits felt wrong before the split (the bug that motivated this)

Server-authoritative detection compares the bullet's **true** position to the player's **true**
position. But the client renders the [Local player](../CONTEXT.md) **predicted-ahead** of its
authoritative position and renders bullets **interpolated ~66.7 ms behind** theirs
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

## The decision table (what the code must implement)

| Projectile owner | Target | Authority | Where decided | Lag comp |
|---|---|---|---|---|
| **Monster** (id ≥ 30000) | Player | **Client-authoritative + server-validated** | victim's client → `LOCAL_HIT_REPORT` → server validates | n/a (judged in client's render frame) |
| **Player** (id < 1000) | Player | **Server-authoritative** | server | rewind target to shooter's Tick, swept, **cap 4 ticks** |
| **Player** (id < 1000) | Monster | **Server-authoritative** | server | rewind target to shooter's Tick, swept, **cap 6 ticks** |

Owner id ranges are the project invariant: players 1–999, projectiles 10000–29999, monsters
30000–39999 (`game_constants.gd`). "Monster-owned" is the test `owner_id >= MONSTER_ENTITY_ID_START`.

## PvE / monster → player: client-authoritative + server-validated

**Intent:** the bullet hits you **iff your client saw it hit your rendered self** — the position
actually drawn on screen, which is *not* always `predicted_position` (see step 2). The server's only
job is to reject implausible reports (anti-grief / anti-spam) and apply the damage; it must **not**
re-decide the hit on authoritative positions (that would reintroduce the phantom/pass-through feel).

**Flow:**

1. **Ownership reaches the client.** Monster fire now broadcasts the **real projectile id** in
   `PROJECTILE_FIRED` — `monster_ai._spawn_monster_projectile` records `last_fired_projectile_id`,
   `monster_ai.update_all` returns `{source_id, projectile_id}` pairs, and
   `server_main._broadcast_projectile_fired` sends them. The client's
   `arena_base._handle_projectile_fired_event` → `client_entity_manager.register_projectile_source`
   records `projectile_id → monster_id`. *(Before the split, monster fire broadcast id 0, so the
   client never learned ownership — that gap is fixed and is load-bearing for this whole path.)*
2. **Client detects.** `LocalHitDetector` (`local_hit_detector.gd`), driven each render frame from
   `arena_base._process` **after** `update_entity_visuals()`. For every visible **monster-owned**
   projectile (`client_entity_manager.get_monster_projectile_snapshots`) it swept-tests the bullet's
   render-frame travel against `prediction.get_rendered_position()` — the position the player is
   **actually drawn at** — with hit window `PROJECTILE_RADIUS + PLAYER_HITBOX_RADIUS = 24`, using the
   shared `GameConstants.closest_point_on_segment`. It uses the *rendered* position, **not**
   `predicted_position`, because during a smooth reconciliation `PredictionController` lerps
   `player_node.position` toward `predicted_position` (the correction target) over several frames — so
   `predicted_position` is ahead of what the player sees. Testing against it would report hits the
   player never saw (or miss bullets overlapping the visibly-smoothed player) under correction spikes,
   reintroducing the "not what I saw" problem this whole path exists to prevent.
3. **Client reports.** On a hit it marks the bullet reported (once per bullet), hides it locally for
   instant feel (`client_entity_manager.hide_projectile_locally`), and sends `LOCAL_HIT_REPORT`
   (`[u16 projectile_id]`). HP is **not** touched locally — it stays authoritative.
4. **Server validates + applies.** `server_main._handle_local_hit_report`: honour the report only if
   the player is alive/authenticated, the per-peer **rate limit** holds
   (`LOCAL_HIT_REPORT_MAX_PER_SECOND = 20`), the projectile exists/alive, it is **monster-owned**, and
   the bullet's **full straight-line flight** (reconstructed `position − direction·distance_traveled`
   → `position`) passes within `24 + LOCAL_HIT_VALIDATION_MARGIN` (64 u slack) of the player's
   **authoritative** position history (`player_manager.get_recent_positions`, 8-tick window). Then it
   applies damage via the shared `server_collision_handler.apply_player_hit` and despawns the bullet
   for everyone (`remove_projectile`) — idempotent, since a removed bullet can't be re-reported.
5. **Server does NOT run its own monster→player collision.**
   `projectile_manager.check_collisions_with_players` **skips** `owner_id >= MONSTER_ENTITY_ID_START`.
   This is the other half of the contract — without the skip you'd get the old phantom hit *and* the
   client report (double damage / conflicting result).

**Validation is a coarse plausibility gate, not a re-decision.** The 64 u slack deliberately absorbs
the legitimate prediction+interpolation offset. It exists to reject "a bullet across the map hit me",
not to second-guess where the client drew the contact. Tightening it toward the true 24 u window would
re-break dodge-feel — do not.

## PvP / player → player: server-authoritative, lag-compensated

**Intent:** the **server** decides, and a client **cannot** avoid damage by withholding or faking a
report. The model favours the **shooter's** view (standard competitive lag comp): rewind the target
to the Tick the shooter saw, so a well-aimed shot on the shooter's screen connects.

- `projectile_manager.check_collisions_with_players` handles **player-owned** projectiles only. Each
  rewinds the player roster to `get_lag_compensated_player_tick()` (from `pvp_collision_rewind_ticks`,
  **capped at `MAX_PVP_PROJECTILE_COMPENSATION_TICKS = 4`** ≈ 133 ms) and runs the swept-segment test
  against that rewound position. The cap bounds "shoot around corners."
- The defender experiences the *same* predicted-self vs. delayed-bullet offset described above and
  **cannot** opt out of it — that asymmetry is the price of cheat-proof PvP. Mitigations are
  shooter-favouring lag comp + a tight rewind cap, **not** client authority.
- Movement is independently server-authoritative: the server re-simulates each player from input
  flags (`player_state._calculate_movement_*`, `move_with_obstacle_collision`) and never adopts a
  client-sent position as truth, so PvP hit resolution runs on positions the client cannot forge.

## Tuning the PvP/feel offset — dynamic and per-ping (Options 2 & 3)

PvP keeps the predicted-self vs. delayed-bullet offset (the defender can't opt out without enabling
cheating). We shrink and rebalance it with three server-authoritative levers, **all already
per-player / per-ping** — there is no single global ping knob, and that's correct:

1. **Lag-comp rewind is per-SHOOTER, per-shot (live).** Each shot's rewind is derived from *that
   shooter's* latency: `server_main._get_pve_projectile_compensation` reads the
   `client_render_tick` / `client_rtt_ms` the client stamps on every input (`prediction.gd:460-461`)
   and rewinds the target roster that many Ticks (PvP capped at 4). So your 10 ms ↔ 90 ms example is
   already handled **directionally**: when the 90 ms player shoots, the server rewinds *you* ~3–4
   Ticks (honours their delayed view); when the 10 ms player shoots, it rewinds ~1 Tick. Each
   direction uses the shooter's ping; the defender's ping does not change how a given shot resolves.
2. **Render delay is per-CLIENT, jitter-driven (live, Option 3).** Each client sizes its own
   interpolation buffer to its own measured *jitter* (`interpolation_controller.gd:206-226`, clamp
   1–3 Ticks, asymmetric fast-grow/slow-shrink). A clean 10 ms link draws bullets ~33 ms behind; a
   jittery link buffers more. Note it tracks **jitter, not raw ping** — a *stable* 90 ms link needs no
   more buffer than a stable 10 ms one, because the buffer only has to hide arrival-time variance.
3. **Defender compensation `PVP_DEFENDER_FAVOR` (new, Option 2).** A server-side dial
   (`game_constants.gd`, default `0.25`) that pulls the *tested* defender position from the
   shooter-rewound position back toward the defender's **current authoritative** position
   (`projectile_manager.check_collisions_with_players`). `0.0` = pure favour-shooter (original);
   `1.0` = test at the defender's live position. It softens "hit after I dodged" for the defender at
   a small cost to shooter precision, with **no client trust**. It is implicitly ping-scaled: a
   high-ping defender was rewound further, so the same factor pulls them a larger distance.

**Why no single "combined-ping" formula.** You can't put both players on one timeline (the offset
exists precisely because their predicted/interpolated frames differ). The honest model is: favour the
shooter (lever 1), shrink everyone's offset to the jitter floor (lever 2), and optionally hand a tunable
slice of fairness back to the defender (lever 3). Levers 1–2 are the safe, always-on wins; lever 3 is a
deliberate shooter-vs-defender trade dialled with 2-client, mixed-ping play-tests. **None of these is
client-authoritative** — that line is reserved for PvE only.

## PvE / player → monster: server-authoritative, lag-compensated

Same shape as PvP but against the monster roster: `check_collisions_with_monsters`,
`get_lag_compensated_monster_tick()`, **cap `MAX_PVE_PROJECTILE_COMPENSATION_TICKS = 6`** (≈ 200 ms).
Monsters never need cheat-proofing the way players do, so the cap is looser. This path is unchanged by
the split.

## PvPvE coexistence — what must stay true

In one tick a player can be grazed by a monster bullet **and** an enemy player's bullet. They take
**two different code paths** and that is correct:

- The monster bullet: not in `check_collisions_with_players` (skipped), resolved only by the victim's
  `LOCAL_HIT_REPORT`.
- The enemy player's bullet: resolved by `check_collisions_with_players` server-side, lag-compensated.

`apply_player_hit` is shared by both so damage/DAMAGE/KILL broadcasting is identical regardless of
which path confirmed the hit.

## Anti-cheat properties (and the one accepted hole)

| Vector | PvE (client-auth) | PvP (server-auth) |
|---|---|---|
| Refuse damage (never report) | **possible** → immune to *monster* bullets only (accepted) | impossible — server decides |
| Fake a hit on someone else | impossible — a client only reports hits on *itself*; server applies to the reporting peer | n/a |
| Claim an impossible hit on self | rejected by plausibility (path + history) + rate limit | n/a |
| Forge position to dodge | n/a (your own render frame is the point) | impossible — server re-simulates movement from inputs |
| "Shoot around corners" | n/a | bounded by the rewind cap (4 ticks) |

The **accepted hole:** a hacked client that never sends `LOCAL_HIT_REPORT` is immune to **monster**
damage. This is inherent to RotMG-style PvE and was chosen knowingly for dodge-feel. It does **not**
touch PvP. An optional, deliberately-lenient server backstop (apply a monster hit if its authoritative
path blatantly overlaps the player and no report arrives within N ticks) is noted in the exec plan and
**left off** — a tight backstop would reintroduce phantom hits.

## Intended invariants (check the code against these)

A future agent should be able to grep these and confirm the implementation still matches:

1. `check_collisions_with_players` **must** early-`continue` on `owner_id >= MONSTER_ENTITY_ID_START`.
   If that skip is removed, monster hits double-apply.
2. `_handle_local_hit_report` **must** reject `owner_id < MONSTER_ENTITY_ID_START` (no PvP via client
   report) and **must** apply to the *reporting* peer's own entity only (never a target id from the
   client).
3. Monster `PROJECTILE_FIRED` **must** carry a non-zero projectile id, or the client never tags the
   bullet monster-owned and the whole PvE path silently no-ops (you'd take *no* monster damage).
4. The plausibility slack (`LOCAL_HIT_VALIDATION_MARGIN`) is a coarse anti-grief bound; it must stay
   comfortably larger than the prediction+interpolation offset at target ping. It is **not** a hit
   re-check.
5. PvP/PvE-on-monster hit detection **must** remain entirely server-side and lag-compensated; never
   route them through `LOCAL_HIT_REPORT`.
6. The client hit test **must** use the **rendered** local-player position
   (`prediction.get_rendered_position()`), not `predicted_position`. The two diverge during a smooth
   correction; testing against the prediction would judge the hit in a frame the player never saw.
7. A reported bullet that the server does **not** despawn within `REPORT_RESOLVE_TIMEOUT_MS` **must**
   be un-hidden and made detectable again (`LocalHitDetector._resolve_pending_reports`). A locally
   hidden bullet that is never restored is both an invisible projectile and a free dodge of a hit the
   server rejected.

## Known mismatches / open items (2026-06-10)

- **Monster→player damage not registering — root-caused + fixed (2026-06-10).** Symptom: bullet
  despawned on contact (client hid it + sent the report) but no damage and no server log. Cause:
  `PacketTypes.is_valid_type` capped valid types at `BASELINE_ACK` (12), so the new `LOCAL_HIT_REPORT`
  (13) failed validation in `_decode_packet`, which returned `{}` and was then silently handled as a
  HEARTBEAT — the report never reached `_handle_local_hit_report`. **Lesson / invariant:** adding a
  wire type means updating *three* things in lockstep — `MessageType`, `PacketTypes.Type`, **and**
  `is_valid_type`'s range — plus encode/decode. Plausibility was also hardened to test the bullet's
  **full** flight (not just the last Tick), since by report-processing time the live bullet is
  downrange of the contact point. **Confirmed working in play-test (2026-06-10); debug flags removed.**
- **Load-test bots report hits (done, 2026-06-10).** The Python swarm (`load_testing/bot_client.py`)
  now mirrors `LocalHitDetector`: each tick it tests visible projectiles against its position and
  sends `LOCAL_HIT_REPORT` (deduped per projectile, rate-limited to 20/s like the server), so bots
  take monster damage like real players.
- **Bots filter to monster-owned bullets before spending quota (done, 2026-06-10).** Bots now track
  projectile ownership exactly like the real client: a `projectile_id → owner` map populated from
  `PROJECTILE_FIRED` (`source_id` = owner, `target_id` = projectile id), pruned on entity removal.
  `_detect_and_report_hits` skips any projectile whose owner is unknown or `< MONSTER_ENTITY_ID_START`
  **before** the distance check and the rate-limit call. *Why it mattered:* the earlier "report any
  nearby projectile, let the server filter" approach spent both the bot's local quota and the server's
  per-peer quota on player-fired bullets the server can only reject — in combat/clustered runs enough
  player bullets near a bot starved its legitimate monster hits in the same second, so bots stopped
  taking PvE damage and the load-test stopped matching real-client behaviour.
- **Rejected/lost reports no longer strand the bullet (fixed, 2026-06-11).** On report the client
  hides the bullet immediately so the impact feels instant. Previously, if the server then *rejected*
  the report (implausible) or it was lost, the bullet stayed alive server-side but invisible and
  excluded from detection on that client for the rest of its life — a one-bullet free pass plus a
  vanished projectile. `LocalHitDetector` now tracks each report as *pending* with a timestamp; after
  `REPORT_RESOLVE_TIMEOUT_MS` (500 ms, comfortably > render-delay + RTT) it checks whether the bullet
  is still live: if so the server did not honour the report, so the bullet is un-hidden and its
  per-bullet tracking cleared so it can be detected again; if it is already gone, the hit was confirmed
  and nothing is restored.
- **Authority predicates centralized (2026-06-11).** The monster-vs-player split, client swept test,
  flight reconstruction, and server plausibility math were duplicated across `LocalHitDetector`,
  `ServerMain`, `ProjectileManager`, and `ClientEntityManager`. They now live in one pure helper,
  `HitAuthority` (`client/scripts/shared/hit_authority.gd`), so the rules can only drift in one place
  and are unit-testable in isolation. Invariants 1–4 below are checks against that helper's callers.
- **PvP defender dodge-feel.** Inherent to server authority; tracked here so nobody "fixes" it by
  making PvP client-authoritative.

## The eight questions

- **Client:** detects incoming **monster** bullets vs. its **rendered** self (`get_rendered_position()`,
  what's actually on screen) and reports them (`LOCAL_HIT_REPORT`); draws all projectiles as
  interpolated Remote entities; never decides PvP hits.
- **Server:** owns all projectiles; decides **PvP** and **player→monster** hits (lag-compensated,
  swept); **validates** monster→player reports and applies damage; broadcasts DAMAGE/KILL.
- **Predicted:** only the local player's movement and the cosmetic muzzle flash. The client's monster-hit
  decision is *authoritative-pending-validation*, not prediction, and is judged at the **rendered**
  position (which trails the prediction during a correction), not the predicted one.
- **Replicated:** projectiles via Snapshots; `PROJECTILE_FIRED` (now with projectile id) / DAMAGE /
  KILL via Game events; `LOCAL_HIT_REPORT` client→server.
- **Persisted:** nothing — gameplay state is in-memory; only the Go API persists leaderboard totals.
- **Validated:** monster→player reports gated by alive/owner/rate-limit/plausibility; PvP/PvE hits by
  rewind caps + server-authoritative movement; all damage is server-applied.
- **Can fail:** a non-reporting client is immune to monster bullets (accepted); a missing monster
  projectile id silently disables PvE-on-player; PvP defender dodge-feel is offset by design.
- **Tested:** the load-bearing predicates (authority split, client swept detection, flight
  reconstruction, server plausibility) are factored into the pure `HitAuthority` helper
  (`client/scripts/shared/hit_authority.gd`) and covered by an automated headless regression,
  `client/scripts/test/hit_authority_test.gd` (run via `./scripts/run_tests.sh`). End-to-end
  client↔server behaviour is still verified by play-test + debug tracing.

## See also

- [`../systems/combat-hits.md`](../systems/combat-hits.md) — the shoot/hit mechanics for every path.
- [`latency-budget.md`](latency-budget.md) — why the predicted/interpolated offset exists.
- [`interpolation.md`](interpolation.md) · [`client-prediction.md`](client-prediction.md) — the two
  timelines that make the offset.
- [`overview.md`](overview.md) — authority model & packet map.
