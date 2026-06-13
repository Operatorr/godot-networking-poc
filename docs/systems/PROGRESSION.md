# Progression — experience & levels

**Status:** Implemented (2026-06-13). Defeating monsters grants **experience**; accumulated XP
raises the player's **level**, which now **scales gameplay stats** (HP, move speed, and primary
damage all grow per level — see [`../classes/index.md`](../classes/index.md)). Progression is now
**server/API-authoritative**: the server owns each player's level and XP in the live sim, hydrates
them from the Go API on join, and writes them back. The client is **display-only**.

> Design split (changed). The **server** decides *who* earns XP, *how much*, and **owns the level
> curve and the per-level stat application** in the authoritative tick. It **hydrates** level/XP
> from the Go API on join and **persists** back to it (via the side-I/O thread, ADR 0005). The
> **client** only renders the HUD from a server `PROGRESS` event — it no longer owns the level math
> or the write-back. This follows "**the client requests, the server decides**" and is the
> cheat-safe model permadeath + the Glory economy require (see
> [`../adr/0006-softcore-hardcore-glory-economy.md`](../adr/0006-softcore-hardcore-glory-economy.md)).

## Numbers

| Constant | Value | Where |
| --- | --- | --- |
| XP share radius | 500 u | `sim_core/src/constants.rs` (`XP_SHARE_RADIUS`) |
| Toxic Slime reward | 20 XP | `server/src/monster.rs` (`TOXIC_SLIME.xp_reward`) |
| Target Dummy reward | 0 XP | `server/src/monster.rs` (`TARGET_DUMMY.xp_reward`) |
| Level 1 → 2 cost | 100 XP (= 5 slimes) | `sim_core/src/constants.rs` (`XP_FIRST_LEVEL`) |
| Level L → L+1 cost (L ≥ 2) | 200 × L XP | `sim_core/src/constants.rs` (`XP_LEVEL_SLOPE`) |
| Max level | **50** | `sim_core/src/constants.rs` (`MAX_PLAYER_LEVEL`) |
| Mana regen | 8 /s (was 10) | `sim_core/src/constants.rs` (`MANA_REGEN_PER_SEC`) |
| Health regen (level 1) | 0.2 hp/s (= 1 hp / 5 s) | `sim_core` (`HEALTH_REGEN_MIN`) |
| Health regen (level 50) | 5.0 hp/s | `sim_core` (`HEALTH_REGEN_MAX`) |
| Glory conversion | `floor(total_lifetime_XP / 100)` | server death/Sacrifice → Go API |
| XP-gain wire event | `EXP_GAIN = 13`, tail `[u16 amount]` | `protocol/src/types.rs`, `protocol/src/server.rs` |
| Progress wire event | `PROGRESS = 15`, tail `[level, experience, move_speed_q]` | `protocol/src/server.rs` (protocol v4) |

## The XP curve

```
xp_to_next(level) = 100            if level == 1     # a quick first level
                  = 200 * level    if level >= 2     # ~10 same-level kills per level
                  = 0              if level == 50    # MAX — bar sits full
```

`experience` is **progress within the current level** (it carries the remainder over on level-up).
The server *also* tracks **total lifetime XP** for the Glory conversion (see below) — the two are
distinct. A Tier 1 Toxic Slime grants 20 XP, so:

- **Level 1 → 2:** 100 / 20 = **5 slimes**.
- **Level L → L+1 (L ≥ 2):** a *same-level* monster sets `xp_reward ≈ 20 × L`, so `200·L / 20·L` = **~10 kills**.
- **Over/under-level is never penalised:** you always get the monster's full `xp_reward`. Farming a
  low-tier slime (20 XP) at level 5 needs `200·5 / 20` = 50 kills/level — intentionally slow.

## Radius sharing (friend boost)

When a monster dies, **every alive, authenticated player within `XP_SHARE_RADIUS` of the corpse
gets the full reward** — there is no split, so standing near a stronger friend's kills boosts you.
The server emits one `EXP_GAIN` event per eligible player (`source_id` = that player); each client
keeps only the event whose `source_id` is its own.

## Per-level stat scaling (new — level now matters)

Level is no longer cosmetic. A stat at level `L` is `base + per_lvl * (L - 1)`, applied **on the
server** when XP crosses a level boundary (and on hydrate at join). Three stats scale, per Class
(full table in [`../classes/index.md`](../classes/index.md)):

- **HP** — `max_hp` grows; the live HP cap rises on level-up (current HP is not topped up).
- **Move speed** — feeds the `sim_core` ground speed; the new value rides the wire so the client
  predicts at the right speed (see the `PROGRESS` event's `move_speed_q` below).
- **Primary damage** — applied server-side when the player's projectile resolves a hit.

Class abilities do **not** scale with level (their parameters are fixed per Class — see
[`abilities.md`](abilities.md)).

## Health & mana regen

- **Health regen** (server-only, all Classes): hp/s scales smoothly with level —
  `regen = lerp(0.2, 5.0, (level - 1) / 49)`, so **level 1 = 0.2 hp/s (1 hp / 5 s)** and
  **level 50 = 5.0 hp/s**. Applied in the authoritative tick, clamped to `max_hp`.
- **Mana regen**: **8/s** for every Class — nerfed 20% from the old 10/s now that Class abilities
  are the Mana sink (see [`abilities.md`](abilities.md)).

## XP → Glory (Hardcore death / Sacrifice)

When a character **ends** — a **Hardcore** death (Permadeath) or a voluntary **Sacrifice** at the
Church (either mode) — the server converts the character's **total lifetime XP** to account **Glory**:

```
Glory = floor(total_lifetime_XP / 100)
```

This is an **atomic Go API transaction** (credit Glory, delete the character) owned by the server's
death/sacrifice path — the same disconnect-immune save permadeath requires (ADR 0005). A
**Softcore** death does **not** convert: the character respawns and keeps its XP; only a Sacrifice
ends it. See [`../adr/0006-softcore-hardcore-glory-economy.md`](../adr/0006-softcore-hardcore-glory-economy.md).

## Flow (API → server → client)

1. **Hydrate on join.** The server fetches the character's `level` + `experience` from the Go API
   (the hydrate-on-join step, ADR 0005) and applies the per-level stats before the player enters the
   sim. `ConnectAuth` now carries `character_id` (protocol v4) so the server knows *which* character.
2. **Server grant.** `combat.rs::process_collisions` PvE branch: when a player projectile kills a
   monster, `grant_kill_experience(monster_pos, xp_reward, players, outbox)` distance-checks all
   players against the corpse and grants the full reward to each eligible player. The server adds it
   to that player's `experience` **and** `total_lifetime_XP`, resolving level-ups via the curve and
   re-applying per-level stats.
3. **Replicate.** On a change the server emits a `PROGRESS { level, experience, move_speed_q }` event
   (protocol v4) to that player; an `EXP_GAIN { amount }` event still fires for the floating "+XP" HUD
   feedback.
4. **Client display.** The client routes `PROGRESS` to the HUD: `ExperienceBar` renders
   `Lv N — exp / next` and flashes on a level-up; the client applies `move_speed_q` to its prediction
   so it predicts at the server's speed. The client computes **nothing** authoritative.
5. **Persist.** The server writes `{ level, experience }` back through the Go API on a periodic
   checkpoint, on instance transition, and on death/sacrifice (idempotent absolute-state, ADR 0005).
   The game server — not the client — owns the write now.

## The eight questions

- **Client:** display-only — renders the XP bar + level from the `PROGRESS` event and the floating
  "+XP" from `EXP_GAIN`; applies the replicated `move_speed_q` to its own prediction. Owns no level
  math and no write-back.
- **Server:** authoritative for *who* earns XP, *how much*, the level curve, per-level stat
  application, regen, and the XP→Glory conversion. Hydrates level/XP from the Go API on join and
  persists back to it.
- **Predicted:** nothing about XP/level. The only knock-on to prediction is move speed, which the
  client takes from the replicated `move_speed_q` rather than predicting.
- **Replicated:** `EXP_GAIN { amount }` (HUD pop) and `PROGRESS { level, experience, move_speed_q }`
  (authoritative state) — both server→client; level is now a real wire field, not a client number.
- **Persisted:** `characters.level` and `characters.experience` in PostgreSQL behind the Go API,
  written **by the server** (via the side-I/O thread); account `glory` credited on Hardcore
  death / Sacrifice. The client no longer `PATCH`es character progression.
- **Validated:** the server grants only a monster's fixed `xp_reward` to alive, authenticated,
  in-radius players, owns the curve, and clamps level to `1..=50`. Because the server (not the
  client) owns and writes level/XP, progression is now **cheat-safe**, not trusted-client — the shift
  that the Glory economy and atomic permadeath conversion required.
- **Can fail:** a dropped `EXP_GAIN` only loses an HUD pop (the authoritative `PROGRESS` corrects it);
  a failed API write retries on the next checkpoint (idempotent absolute-state); a crash loses XP back
  to the last checkpoint, but the Glory conversion is part of the atomic death transaction and cannot
  half-apply.
- **Tested:** protocol round-trip for `EXP_GAIN` and `PROGRESS` (`protocol/src/server.rs` tests);
  Rust workspace build/clippy/fmt green. Curve, per-level scaling, regen, and the Glory conversion are
  exercised by play-test (no automated gameplay harness for them yet — a gap to close).

## Known gaps / future work

- **No per-kill persistence:** the server checkpoints XP on a timer / transition / death, so a crash
  can lose a few seconds of progress (the Glory conversion itself is atomic and safe).
- **Monster roster:** only the Toxic Slime grants XP today (20). Higher tiers should set
  proportionally larger `xp_reward` as they are implemented — see [`MONSTERS.md`](MONSTERS.md).
- **Ability scaling:** Class abilities are fixed per Class today; per-level or skill-tree ability
  scaling is future work (Class Trainer spells, ADR 0005's "widen the payload later").

## See also

- [`../classes/index.md`](../classes/index.md) — per-Class base stats and the per-level scaling table.
- [`abilities.md`](abilities.md) — Class abilities, Mana, the 8/s regen sink.
- [`../adr/0006-softcore-hardcore-glory-economy.md`](../adr/0006-softcore-hardcore-glory-economy.md) — Softcore/Hardcore + Glory.
- [`../adr/0005-permadeath-persistence-model.md`](../adr/0005-permadeath-persistence-model.md) — hydrate-on-join + death-as-save.
- [`../server/contract.md`](../server/contract.md) — the protocol v4 wire deltas (`PROGRESS`, `character_id`).
