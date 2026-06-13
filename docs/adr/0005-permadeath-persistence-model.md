# ADR 0005 — Permadeath persistence: death is the server-authoritative transactional save

**Status:** Accepted (design) — 2026-06-11. Records [Rust port](../rust-port/migration-spec.md)
decision **D10**. Builds on [ADR 0003](0003-enet-udp-transport.md) (session ticket) and the migration
spec's D8 (single-threaded authoritative tick) and D9 (Ed25519 ticket). Reinforces the AGENTS.md
invariant *"all gameplay state is server-authoritative and in-memory; the Go API owns only
account/character/leaderboard persistence."*

> **Extended by [ADR 0006](0006-softcore-hardcore-glory-economy.md) (2026-06-13, D15).** This ADR's
> "death deletes the character and credits Glory" is now the **Hardcore** rule specifically:
> ADR 0006 adds a forgiving **Softcore** mode (death respawns; the character ends only by voluntary
> **Sacrifice** at the Church), defines the **XP→Glory** exchange (`floor(total_lifetime_XP / 100)`,
> run as one atomic transaction on the same death/sacrifice path), and moves **progression itself to
> server/API authority** (the client used to own the level curve; it no longer does). Read both
> together — the persistence *mechanism* here is unchanged; ADR 0006 layers modes and the economy
> onto it.

## Context

The Rust port is the netcode foundation for a **Realm-of-the-Mad-God-like instance-based MMO**:
permadeath characters and a forever account bank. Permadeath **inverts the usual persistence failure
mode.** A save-on-leave design fears *losing* progress on a crash; under permadeath the dangerous vector
is the opposite — a player **dodging a fatal hit by disconnecting** so the death never persists and they
keep the character and its loot. That inversion, plus a tradeable item economy (where **duplication** is
the cardinal sin), dictates the whole persistence design — so it is decided now, before the boundary is
built, even though POC gameplay is HP-only.

## Decision

**1. Three state lifetimes** (canonical terms in [`../CONTEXT.md`](../CONTEXT.md)):

| Lifetime | Examples | Storage | In the sim? | Survives death? |
|---|---|---|---|---|
| Account-scoped durable | bank, glory, classes, currency | Go API / Postgres | No | Yes |
| Character-scoped durable | level, stats, carried inventory | Go API / Postgres; hydrated on join | Yes (this subset) | **No** |
| Session-ephemeral | HP/MP, position, cooldowns | in-memory in the sim | born there | reset on entry |

The sim hydrates **only the Character-scoped subset** on join; **Account-scoped state never enters the
combat sim** (touched only at a bank chest in the Sanctuary, via the API). This is what keeps the service
boundary thin despite a rich item economy.

**2. Death is the first-class save, and it is disconnect-immune.** When HP reaches 0 **in the
authoritative tick** (D8's collision/damage stage), the server **synchronously and transactionally**:
deletes the character + everything it carried, credits account glory, and leaves the bank untouched —
**before any client action can intervene.** Alive/dead is server-authoritative at the tick it happens.
This is **not** save-on-leave; a disconnect handler a cheater never lets you reach cannot be the
mechanism.

**3. Item integrity is enforced by exactly one service (the Go API).**
- **Single active session per account** — prevents two sessions hydrating the same inventory and both
  saving (a dupe). Enforced at ticket issuance / session registration.
- **Atomic bank↔character transfers** — every item move is a single Postgres transaction behind the
  Go API; never "remove then add." Rust never races these in a second language.

**4. Instance transitions double as checkpoints.** Persist Character-scoped state through the API on
each portal transition; re-hydrate in the destination; spawn fresh Session-ephemeral state. Instances
are stateless-on-entry. Death-resolution authority must sit clearly on one side of a transition (no
portal-dodge).

**5. Writes are idempotent absolute-state** ("character is now level 12, these stats, this inventory"),
never deltas — so transition saves, periodic checkpoints, and the death-persist are all safe to retry.
A periodic checkpoint bounds loss on accumulating XP/glory between transitions.

## Considered options

| Option | Verdict |
|---|---|
| **Hydrate-on-join + death-as-save via Go API, three-tier state** (chosen) | **Accepted** — only model that closes the disconnect-to-dodge-death and dupe vectors while keeping the sim thin |
| Save-on-leave only (clean-exit) | Rejected — a disconnecting cheater never triggers it; permadeath unsaved |
| Ephemeral sim + results-only to API | Rejected for the target game — no durable progression; cannot host a bank economy (fine only as a throwaway POC stage) |
| Rust → Postgres direct | Rejected **hard** — item-transfer transactions racing across two languages is the surest dupe factory; violates the single-owner invariant |

## Consequences

- **The "Go API owns persistence" invariant becomes load-bearing**, not precautionary — it is the thing
  protecting the item economy from dupes.
- **Death persistence is on the tick hot path** — it must be transactional and fast; a failed
  death-write must retry (idempotent absolute-state makes this safe) and must not let the character
  resurrect. Open: whether the tick blocks on the death-write or hands it to a guaranteed-delivery
  outbox while marking the character dead in-memory immediately (the latter is preferred; the in-memory
  dead flag is the authority, the write is durability).
- **The Go API grows** a session registry (single-active-session), character hydrate/save endpoints, an
  atomic item-transfer endpoint, and a glory-credit/character-delete death endpoint.
- **Build the seam now, grow the payload later** — stand up hydrate-on-join, death-persist, atomic item
  move, and the session lock early; durable fields start minimal (identity + HP) and widen as classes,
  skill trees, and item types land. The seam is the expensive-to-retrofit part.
- **Scaling escape hatch (post-POC):** a per-player session actor that outlives instances (instances
  borrow live state) — a server-internal change behind the same API contract.

## The eight questions

- **Client:** requests a ticket from the Go API (HTTPS), connects; renders death; never authoritative
  over alive/dead or inventory.
- **Server (Rust):** hydrates Character-scoped state on join, runs the sim, and on in-tick HP→0 fires
  the transactional death-persist; persists on instance transitions + periodic checkpoints.
- **Predicted:** nothing about persistence is predicted; death is shown only when the server says so.
- **Replicated:** death as a `GAME_EVENT`; the durable consequence is a server↔API concern, off-wire.
- **Persisted:** Account- and Character-scoped state in Postgres behind the Go API; Session-ephemeral
  never persisted.
- **Validated:** single-active-session and atomic item transfers enforced by the Go API; the Rust
  server's in-tick dead flag is authoritative and disconnect-immune.
- **Can fail:** death-write failure (retried via idempotent absolute-state / outbox; in-memory dead flag
  holds); API outage during a transition (block the transition rather than risk an unsaved death).
- **Tested:** a disconnect-at-fatal-hit test must show the character stays dead; a concurrent-session
  test must show no dupe; an item-transfer crash-injection test must show no item in both/neither place.

## See also

- [ADR 0006](0006-softcore-hardcore-glory-economy.md) — Softcore/Hardcore modes, the XP→Glory exchange,
  and server-authoritative progression that **extend** this ADR (D15).
- [`../rust-port/migration-spec.md`](../rust-port/migration-spec.md) — decision D10 (and D15) and the D8/D9 it builds on.
- [ADR 0003](0003-enet-udp-transport.md) — the session-ticket auth this persistence boundary rides behind.
- [`../CONTEXT.md`](../CONTEXT.md) — the state-lifetime and progression terms this ADR makes canonical.
