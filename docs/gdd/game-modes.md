# Game Modes

Omega Realm ships one set of shared mechanics (one shooting verb, HP/Mana/Energy, the shared
`sim_core` simulation) reused across several **modes**. A mode is a wrapper of rules — who can hurt
whom, what resets, what is at stake — around the same core loop. This doc is the design intent;
where a mode is unbuilt it says so.

> **Source of truth, not this doc:** the wire/authority mechanics live in
> [`../server/contract.md`](../server/contract.md) and [`../server/design.md`](../server/design.md).
> Glory/persistence is owned by the Go API (`api/`). The only authoritative server is the Rust
> **omega-server** (`rust/server/`); one process = one running **instance** (e.g. Arena udp/8081,
> Sanctuary udp/8082). The retired GDScript headless server is not live and is being deleted — do
> not treat `client/scripts/server/*.gd` as runtime behaviour.

---

## Authority model (applies to every mode)

The GDD's old one-liner ("PvE and monster damage is client authoritative, PvP is server
authoritative") is **misleading and must be read as the nuanced two-netcode model below**, which is
what the Rust server actually implements. Governing rule everywhere: **the client requests, the
server decides.**

| Interaction | Authority | Why |
| --- | --- | --- |
| **Monster → player** damage | Client-authoritative, **server-validated** | Preserves RotMG dodge-feel (you dodge what *you* render). Client sends a `LocalHitReport`; the server checks plausibility and applies it. |
| **Player → monster** damage | **Server-authoritative**, lag-compensated | Server rewinds monster positions (≥ 6-tick history ring) and resolves the hit. |
| **Player → player (PvP)** damage | **Server-authoritative**, lag-compensated | No client gets to declare it hurt another player. |

A **lenient backstop** guards the client-authoritative path against grief: the server only
overrides a missing self-report on a *blatant* overlap (true 24 u overlap, grace ≥ 15 ticks). It is
deliberately forgiving so legitimate dodges are never punished. See the hit-authority invariants in
[`../server/contract.md`](../server/contract.md) and `rust/server/src/combat.rs`
(`apply_local_hit_report` / `apply_monster_damage`, owner-id range selects the path:
`owner_id >= 30000` is monster-owned and skipped in the server's player-collision pass).

All gameplay state is **server-authoritative and in-memory**. Only durable account/character state
(accounts, characters, **mode**, level/XP, **Glory**, leaderboard, regions) is persisted, by the Go
API into Postgres + Redis. Auth is an Ed25519 session ticket minted by the Go API and verified by
the server (dev default: `--allow-unsigned-tickets`).

---

## 1. PvE — the primary mode (bullet-hell roguelite)

The core experience. Venture from the Sanctuary into the open world / dungeons, fight monsters,
level toward the cap (50), collect loot, and either die (Hardcore) or retire your character on your
own terms (Softcore) to bank **Glory** for account-wide meta-progression.

### The loop

1. Spawn in **The Sanctuary** (also "The Sanctum" in the CMS) — a shared, **PvP-off** hub
   instance. Bank, vendors/NPCs, buy/sell, trade, spend Glory, then take a portal out.
2. Three portals lead to the open-world shards: **Mainland** (Tier 1–4), **Underworld** (Tier 3–7),
   **The Creators Realm** (Tier 4–7). One open-world boss per biome; one procedurally-generated
   dungeon-with-boss per biome. (Biome/tier table: [`BIOMES.md`](BIOMES.md).)
3. Kill monsters → earn encounter-based EXP ([`progression/EXP_contribution.md`](progression/EXP_contribution.md))
   and roll loot ([`loot.md`](loot.md)) → grow level/power → push into higher-tier biomes.
4. Death (Hardcore) or voluntary sacrifice (Softcore) converts the character's lifetime into Glory.

### Permadeath: Softcore vs Hardcore

A character's mode is fixed at creation and stored on the character row (`characters.mode`,
constrained to `'softcore' | 'hardcore'`, default `'softcore'`; see
`api/internal/database/database.go` and `api/internal/handlers/character.go`).

| | **Softcore** | **Hardcore** |
| --- | --- | --- |
| On death | Character survives (designed: respawn / non-permanent loss) | **Permadeath** — character is gone |
| Banking Glory | **Voluntary sacrifice** in the Sanctuary/Sanctum | Automatic on death |
| Stakes | Lower; you choose when to cash out | Higher; one death ends the run |

### Glory (the meta-progression currency)

Glory is **account-wide**, server-authoritative, and never negative
(`users.glory`, `CHECK (glory >= 0)`; `api/internal/models/models.go`). It is spent in the
Sanctuary on permanent account upgrades — boost max health, unlock weapons, buy passive buffs,
unlock skill-tree points — making subsequent runs more forgiving.

**Award math (single source: `api/internal/progression/progression.go`, ported from the shared
curve in `rust/sim_core/src/progression.rs`):**

```
Glory awarded = floor( TotalLifetimeXP(level, experience) / GloryXPDivisor )
GloryXPDivisor = 100
```

Both the **death** path (Hardcore) and the **sacrifice** path (Softcore) call the same
`GloryFor(level, experience)`. The softcore sacrifice is an atomic, JWT-protected transaction:
`POST /api/character/sacrifice` reads the character's level/XP, awards Glory to the account, and
retires the character (`SacrificeCharacter` in `api/internal/handlers/character.go`). At the level
cap, `GloryFor(50, 0) = floor(244900 / 100) = 2449` (see `progression_test.go`).

### PvE authority

PvE is **not** a free-for-all "client authoritative" mode. It uses the two-netcode model above:
your dodges of monster bullets are client-authoritative + server-validated; your damage to monsters
is server-authoritative and lag-compensated. EXP grants are server-authoritative
(`grant_kill_experience` in `rust/server/src/combat.rs`).

---

## 2. PvP arenas (competitive instances)

Player-vs-player combat in arena instances (small/medium/large arena layouts in the GDD's scene
plan). The current shipped arena runs as the **Arena instance** (udp/8081).

- **Authority:** PvP damage is **fully server-authoritative and lag-compensated** (8-tick monster
  history ring is reused for lag-comp; PvP resolution never trusts a client's hit claim). The
  Sanctuary instance keeps **PvP off**; arenas turn it on.
- **PvP bots:** a strong PvP bot AI exists and is to be preserved and refactored into a reusable
  pattern that also feeds tunable Monster AI (see [`index.md`](index.md) → Bots / Difficulty).
- **Status:** the Arena instance and the underlying server-authoritative PvP path exist; structured
  PvP *matchmaking/scoring* as a packaged mode is **design-directional / partially unbuilt**.

---

## 3. Tournaments (scheduled competitive events)

Scheduled, time-boxed competitive events surfaced through the CMS and a tournament UI
(tournament list / lobby / leaderboard in the GDD scene plan). Results feed the competitive
leaderboard (Redis-backed; `api/internal/redis/leaderboard.go`,
`api/internal/handlers/leaderboard.go`).

- Tournaments are a **scheduling + ruleset + leaderboard** wrapper around PvP and/or race rules,
  not a new combat model — they reuse the authority model above.
- **Status:** **unbuilt / design-directional.** No tournament scheduler, bracket, or lobby exists
  in `rust/` or `api/` today. The GDScript scene/script names in the legacy GDD
  (`tournament_manager.gd`, `tournament_system.gd`, etc.) describe the retired client-server design
  and are **not** live; if rebuilt, scheduling/state belongs in the Go API and ruleset enforcement
  in the omega-server.

---

## 4. Cutthroat Races (PoE-style fresh-start level races, PvPvE)

A competitive **leveling race**: every participant starts a **fresh reset** at level 1 at the same
moment (Path of Exile league / Rust-wipe style) and simultaneously ventures into the world to level
up — **while also able to fight each other**. This is **PvPvE**: monsters *and* rival players are
threats at once.

- **Win condition:** fastest progression (first to a target level / furthest within the time box —
  exact scoring TBD), tracked live and posted to the leaderboard.
- **Instancing:** the GDD's earlier "race track" scene names are a **misinterpretation** — there is
  no dedicated race-track level. A Cutthroat Race runs in an **instance of the normal game world**
  with PvP enabled, a fresh-start ruleset, and a shared clock.
- **Authority:** combat uses the same two-netcode model. The fresh-start reset (everyone level 1,
  no inherited gear/level for the race instance) and the race clock would be enforced
  server-/API-side; the client merely requests.
- **Status:** **unbuilt / design-directional.** No fresh-start/race ruleset, race tracker, or
  simultaneous-start orchestration exists in code today. Reuses PvP authority + the EXP curve when
  built.

---

## Mode comparison

| Mode | PvP | Resets | At stake | Authority highlight | Status |
| --- | --- | --- | --- | --- | --- |
| **PvE** (primary) | Off (Sanctuary) | Per character (perma/sacrifice) | Character + Glory | Two-netcode (dodge client-side, damage server-side) | Core loop building |
| **PvP arena** | On | None | Match standing | Fully server-authoritative + lag-comp | Arena instance live; mode wrapper partial |
| **Tournament** | On (and/or race) | Per event | Leaderboard rank | Inherits underlying mode | Unbuilt |
| **Cutthroat Race** | On (PvPvE) | **Fresh start, level 1, all players** | Race rank | Two-netcode + server-enforced fresh start | Unbuilt |

---

## How this is documented (the eight questions)

- **Client:** input, prediction (via the shared `sim_core` through the `client_ext` GDExtension),
  rendering, self-reported monster-hit dodges, mode/UI selection.
- **Server (omega-server):** all damage resolution (server-auth for PvP and player→monster,
  validation for monster→player), EXP grants, deaths/respawns, AoI snapshots, PvP toggle per
  instance.
- **Predicted:** local movement and (only) Warrior Charge / Rogue Shadowstep blink; nothing else.
- **Replicated:** entity snapshots over ch0 (unreliable-sequenced); events/auth/baselines over ch1.
- **Persisted:** account, character (incl. **mode**), level/XP, **Glory**, leaderboard, regions —
  all in the Go API (Postgres + Redis). No gameplay state is persisted.
- **Validated:** monster→player hit reports (plausibility + lenient blatant-overlap backstop);
  movement thresholds; Glory awards floored server-side; mode constrained in DB.
- **Fails:** Tournaments and Cutthroat Races are unbuilt; PvP *mode packaging* is partial.
- **Tested:** Glory math has Go unit tests (`api/internal/progression/progression_test.go`); the
  shared sim has Rust workspace tests. Mode-orchestration tests do not exist yet (nothing to test).
