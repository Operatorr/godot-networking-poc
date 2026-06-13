# ADR 0006 — Softcore/Hardcore modes, the Glory economy, and server-authoritative progression

**Status:** Accepted (design) — 2026-06-13. Extends [ADR 0005](0005-permadeath-persistence-model.md)
(permadeath as the server-authoritative transactional save). Builds on the Ed25519
ticket (now carries `character_id`) and hydrate-on-join / death-as-save. Reinforces the AGENTS.md
invariant *"all gameplay state is server-authoritative and in-memory; the Go API owns only
account/character/leaderboard persistence."*

## Context

ADR 0005 designed permadeath as *the* first-class save: an in-tick HP→0 deletes the character and
credits account Glory, disconnect-immune. Two things changed once Classes, per-level stats, and an
ability system landed:

1. **Not every player wants permadeath.** A RotMG-like wants the brutal Hardcore loop, but a
   forgiving on-ramp (respawn, keep your character) widens the audience and is the safer default for
   the POC. We need **two permanence modes** without forking the persistence design.
2. **Progression became gameplay.** Level now scales HP, move speed, and primary damage, and abilities
   spend Mana. Under ADR 0005's predecessor, the **client** owned the level curve and `PATCH`ed it
   back — "trusted client identity," explicitly *not* anti-cheat-hardened. That was acceptable when
   level was cosmetic. The moment level drives stats **and** converts to a tradeable account currency
   (Glory), a client-owned number is a dupe/inflation vector. Progression must move server-side.

This ADR records both decisions together because they share one mechanism: the **XP→Glory
conversion**, which is the hinge between Character-scoped XP and Account-scoped Glory.

## Decision

**1. Two permanence modes, chosen per character.**

| Mode | On death | On voluntary Sacrifice (Church) | Keeps XP? |
|---|---|---|---|
| **Softcore** | respawn; character survives | delete character, convert XP→Glory | yes (until Sacrifice) |
| **Hardcore** | **Permadeath** — delete character, convert XP→Glory | (death already deletes) | no |

**Permadeath is now Hardcore-only.** A Softcore death is not permanent; a Softcore character ends
**only** by Sacrifice. The CONTEXT.md `Permadeath` entry is reconciled to say exactly this.

**2. The Glory exchange.** When a character ends — Hardcore death or Sacrifice (either mode) — the
server converts its **total lifetime XP** to account Glory:

```
Glory = floor(total_lifetime_XP / 100)
```

This is one **atomic Go API transaction** (credit account Glory + delete the character), run on the
server's death/sacrifice path — the same disconnect-immune, idempotent-absolute-state save ADR 0005
mandates. It cannot half-apply (Glory credited but character alive, or vice versa).

**3. Sacrifice is the deliberate counterpart to dying.** A player visits the **Church** in the
Sanctuary and Sacrifices the active character. This is the *only* way to end a Softcore character and
realize its XP as Glory — it is the Softcore "cash-out." Hardcore players may also Sacrifice (e.g. to
bank progress before a risky run) rather than wait to die.

**4. Progression is now server/API-authoritative (was client-owned).** The server owns each player's
`level`, `experience`, and `total_lifetime_XP` in the live sim:
- **Hydrate on join** from the Go API (ADR 0005's hydrate step); `ConnectAuth` now carries
  `character_id` so the server knows which character to load.
- **Grant + curve + per-level stats** are applied in the authoritative tick.
- **Persist** back through the Go API on checkpoint / transition / end (server-written, not client).
- The client is **display-only**, fed a `PROGRESS { level, experience, move_speed_q }` event.

This is the cheat-safety the Glory economy needs: a client cannot inflate level (and thus Glory) or
desync stats from the server. It follows the governing rule, **"the client requests, the server
decides."**

## Considered options

| Option | Verdict |
|---|---|
| **Two modes + atomic XP→Glory + server-authoritative progression** (chosen) | **Accepted** — one mechanism serves both modes; closes the client-owned-progression cheat/dupe vector |
| Hardcore-only (drop Softcore) | Rejected — no forgiving on-ramp; narrows the POC audience for no design saving |
| Keep client-owned progression (ADR-0005-era) | Rejected — level now drives stats *and* converts to a tradeable currency; a client number is a dupe/inflation vector |
| Convert XP→Glory on every level-up (continuous) | Rejected — makes mid-life characters partially "cashed out," muddying the Character/Account-scoped split; end-of-life conversion keeps the boundary clean |

## Consequences

- **The CONTEXT.md `Permadeath` entry narrows to Hardcore.** New canonical terms: Softcore, Hardcore,
  Sacrifice, plus Class ability / Mana / the named abilities and AOE / Stealth / Healthorb / Health
  regen for the survival systems.
- **The Go API gains a Glory-credit-on-end endpoint** (atomic credit + character-delete) and a
  `mode` (Softcore/Hardcore) field on the character; it already owns single-active-session and atomic
  transfers from ADR 0005.
- **The server gains progression ownership:** the level curve, per-level stat application, regen, and
  the XP→Glory conversion move into the sim/side-I/O thread; the client's old `PATCH /api/character`
  write-back is removed.
- **The wire grows (protocol v4):** `character_id` in `ConnectAuth`, a `PROGRESS` event, plus the
  ability-system additions (cursor in `PlayerInput`, world-effect entity kind, `STEALTH` flag,
  `ABILITY_EFFECT`, `PICKUP {kind, amount}` for Healthorbs). Full layout in
  [`../server/contract.md`](../server/contract.md).
- **Total lifetime XP must be tracked separately** from within-level `experience` — the conversion
  reads the lifetime total, not the level-progress remainder.

## The eight questions

- **Client:** picks Softcore/Hardcore at character creation; requests Sacrifice at the Church; renders
  level/XP/Glory from server events. Never authoritative over level, XP, Glory, or alive/dead.
- **Server (Rust):** owns level/XP/lifetime-XP in the sim; applies the curve, per-level stats, and
  regen; on Hardcore death or Sacrifice runs the atomic XP→Glory + character-delete via the Go API.
- **Predicted:** nothing about progression or Glory; move speed is taken from the replicated
  `move_speed_q`, not predicted.
- **Replicated:** `EXP_GAIN` (HUD pop) and `PROGRESS { level, experience, move_speed_q }`; Glory is an
  Account-scoped server↔API concern, off the game wire.
- **Persisted:** `level`, `experience` (Character-scoped) and `glory`, `mode` (Account/Character) in
  Postgres behind the Go API; the conversion is one atomic transaction.
- **Validated:** server owns the curve and clamps level to `1..=50`; the Glory credit + character
  delete are atomic and idempotent; Softcore deaths never convert (only respawn).
- **Can fail:** a failed conversion retries on idempotent absolute-state; a Softcore respawn that
  races a Sacrifice resolves on the server (one ends the character, the other no-ops).
- **Tested:** the conversion is part of the ADR 0005 death-path tests (disconnect-at-fatal-hit keeps
  the Hardcore character dead *and* credits Glory exactly once); Softcore respawn-keeps-character and
  Sacrifice-converts paths by play-test; `PROGRESS` protocol round-trip.

## See also

- [ADR 0005](0005-permadeath-persistence-model.md) — permadeath as the transactional save this extends.
- [`../server/design.md`](../server/design.md) — progression & economy in the context of the whole server.
- [`../server/contract.md`](../server/contract.md) — the protocol v4 wire layout.
- [`../systems/PROGRESSION.md`](../systems/PROGRESSION.md) · [`../systems/abilities.md`](../systems/abilities.md) · [`../classes/index.md`](../classes/index.md)
- [`../CONTEXT.md`](../CONTEXT.md) — the Softcore/Hardcore/Sacrifice/Glory terms this ADR makes canonical.
