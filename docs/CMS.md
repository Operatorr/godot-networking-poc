# CMS / Web — Content Management & Player Website

**Status: split.** This doc covers two very different things that the original GDD lumped together
under "CMS Integration":

1. **The player website / dashboard — AS BUILT.** A real, deployed Astro app (`web/`) backed by
   the Go API (`api/`). Players register, log in, create / forge-sacrifice a character, and view
   the leaderboard + Glory. This is live.
2. **The content-CMS (Enemy / Item / Spell editors, Balance Dashboard, publish-to-JSON balance
   patches) — ASPIRATIONAL.** None of it is built. It is a design intent only. Everything in
   §3–§5 below is **NOT built** and is marked as such.

> The HTTP/JSON contract the website actually consumes is documented in full in
> [`api/web-api.md`](api/web-api.md). That file is the source of truth for endpoints, request /
> response shapes, and the Astro SSR integration pattern. **This doc does not restate it** — it
> frames what exists vs. what doesn't, and what the unbuilt content-CMS would have to touch.

---

## 1. Reality check (read this first)

The GDD described a single "web-based CMS" that does everything: a player portal **and** a
designer tool that hot-reloads enemy/item/spell stats to live clients via JSON-on-CDN with "no
game patch required." Only the player portal exists. Two facts from the current code constrain
the rest:

- **Gameplay tuning is not data-loaded at runtime by the authoritative server.** The only
  authoritative server is the Rust **`omega-server`** (`rust/server/`). Monster stats are
  **compiled-in Rust statics** (`rust/server/src/sim/monster.rs` — `TOXIC_SLIME`, `TARGET_DUMMY`),
  and per-class / ability tuning is likewise hardcoded (`rust/server/src/sim/ability.rs` —
  `ClassStats`). The `client/data/monsters/*.json` and `client/data/classes/*.json` files are a
  **parity mirror / human reference** that the retired GDScript code read; they are *not* the
  authoritative numbers and the Rust server does **not** read them at runtime. Changing a
  monster's HP today means editing Rust and **rebuilding + redeploying** the server
  (`scripts/deploy.sh`) — not publishing a JSON file. The GDD's "< 5 minutes, no patch" hot-update
  flow does **not** exist.
  - *Exception:* `client/data/config/server_config.json` (tick rate, arena bounds, spawn config)
    **is** loaded at startup by `rust/server/src/main.rs`. It is per-instance runtime config, not
    a content/balance database, and a change still requires a restart (`scripts/deploy.sh sync`).
- **There is no `data/*.json` content database that a CMS could publish to today.** The closest
  thing is `client/data/`. A future content-CMS managing balance would have to either (a) make
  the Rust server load these JSON files at runtime (it does not), or (b) emit Rust source /
  constants consumed at build time. Either path is real work; see §6.

So: the player website is **done**. The content-CMS is a **green-field feature** that would
**extend the Go API (`api/`) and the Astro app (`web/`)** and require deciding how the Rust
server ingests content data.

### Content kinds (web↔api identity mapping)

The CMS content store keys every definition by a **kind** slug. The Go API and the web CMS use the
**same** strings — an identity mapping, so the web `ApiBackend` needs **no kind translation**:

`monsters` · `classes` · `weapons` · `spells` · `projectiles` · `balance`

These are the canonical collection slugs (`content.Kind` in `api/internal/content/content.go`; the
web collection names match exactly). The CRUD surface is `GET/POST /api/content/{kind}`,
`GET/DELETE /api/content/{kind}/{id}`, and `POST /api/content/{kind}/publish` (all admin-gated).

---

## 2. AS BUILT — the player website / dashboard

A deployed marketing site + player dashboard. Not a designer tool — a player-facing portal.

- **App:** `web/` — Astro (SSR on Vercel) with React islands, shadcn/ui, Tailwind v4. See
  [`web/README.md`](../web/README.md).
- **Backend:** the Go API in `api/` (Postgres + Redis). Handlers in
  `api/internal/handlers/` (`auth.go`, `character.go`, `leaderboard.go`, `region.go`,
  `ticket.go`, `internal.go`).
- **Auth pattern (BFF):** the browser never calls the Go API directly. Astro endpoints under
  `web/src/pages/api/**` call the Go API and store its JWTs in **httpOnly cookies**
  (`or_access` 15 min, `or_refresh` 7 days, cached `or_user`). `web/src/middleware.ts` guards
  `/dashboard` + `/api/character/*`; `web/src/lib/auth-session.ts` forwards the access token and
  refreshes on 401. Full contract + the canonical SSR snippets are in
  [`api/web-api.md`](api/web-api.md) §6.

### What players can do (as built)

| Feature | How | Endpoint (via Go API) |
|---|---|---|
| Register an account | `web/src/pages/register.astro` → `src/pages/api/auth/register.ts` | `POST /api/auth/register` |
| Log in / out | `login.astro` → `api/auth/{login,logout}.ts` | `POST /api/auth/login`, `POST /api/auth/refresh` |
| View dashboard / character | `dashboard.astro` + `components/dashboard/CharacterCard.astro` | `GET /api/character/me` |
| Create a character | `api/character/create.ts` | `POST /api/character/create` |
| **Forge-sacrifice** a character for Glory | `api/character/sacrifice.ts` | `POST /api/character/sacrifice` → `{ glory_awarded }` |
| Delete a character | `api/character/index.ts` | `DELETE /api/character` |
| View the leaderboard | `leaderboard.astro` | `GET /api/leaderboard?metric=…&limit=…` |
| See Glory balance | from `user.glory` on login | (returned in `AuthResponse.user`) |
| Marketing / legal pages | `index.astro`, `news`, `faq`, `support`, `legal/*` | none (static) |

**Glory** is the account-wide currency awarded by the sacrifice flow
(`floor(total lifetime XP / 100)`); it is server-authoritative and stored on the `users` row in
Postgres. Progression (`level`/`experience`) is **read-only** to the website — it is owned by the
game server, settled into the API over the server-only internal endpoints. The website cannot
raise it. See [`api/web-api.md`](api/web-api.md) §3–§5.

> The data the website shows (accounts, characters, Glory, leaderboard) is the **only durable
> state in the system** and the API owns all of it. In-match gameplay state is server-authoritative
> and in-memory in the Rust server.

---

## 3. ASPIRATIONAL — content-CMS (NOT BUILT)

> **None of §3, §4, §5 is implemented.** This is the GDD's design intent, retained for direction.
> A content-CMS would be a **new** designer-facing surface on top of the existing `api/` + `web/`,
> plus a decision on how the Rust server ingests the data (see §6). Treat every field list below
> as a wishlist, not a contract.

**Goal (aspirational):** let designers / balance teams edit game content without Godot access or a
hand-written rebuild.

### 3.1 Enemy Editor — NOT BUILT
```
Fields: Name · Health · Damage · Speed · AI Type (melee_aggressive | ranged_kiting | …) ·
        Abilities (from spell list) · Loot Table · Experience Reward · Resistances (k/v)
Actions: Create · Clone · Visual Preview · Stat-compare Preview · Publish · Archive (soft delete)
```
Today the equivalent values live as Rust statics in `rust/server/src/sim/monster.rs` (and as a parity
mirror in `client/data/monsters/*.json`). An editor would need to write those, then trigger §4.

### 3.2 Item Editor — NOT BUILT
```
Fields: Item Type (weapon | armor | consumable) · Name · Base Stats (by type) ·
        Rarity Multipliers · Affix Pool · Icon (upload) · Value
Features: Generated-item preview · Stat comparison · Bulk edit (all swords at once)
```
There is **no item / inventory system in the as-built game** at all — this editor would precede or
accompany building one.

### 3.3 Spell / Ability Editor — NOT BUILT
```
Fields: Name · Damage · Mana Cost · Cooldown · Cast Time · Range · Projectile · Effects[] ·
        Class Assignment (which classes can cast)
Features: Visual preview · DPS calculator
```
Today the per-class RMB ability and its tuning are hardcoded in `rust/server/src/sim/ability.rs`
(`ClassStats`, `AbilityKind`), and that same config feeds the shared `sim_core` so prediction
matches the server. **Any editor here is constrained by the shared-sim invariant:** the
prediction sim and the server run the *same compiled crate*, so edited ability numbers must reach
both — i.e. a rebuild of `sim_core` + the client GDExtension, not a JSON drop. This is the
single biggest reason the "hot-publish balance" flow is hard for abilities specifically.

### 3.4 Balance Dashboard — NOT BUILT
```
Analytics: most-used items · most-killed-by enemies · avg time-to-kill · spell usage · win rate by class
Tools:     global damage-multiplier slider · batch HP update · export balance patch
```
This would require the Go API to **collect and store gameplay analytics** in Postgres (a new
ingestion path from the Rust server, plus new tables and aggregation endpoints). None of that
exists; the API currently stores only accounts / characters / leaderboard / Glory.

---

## 4. ASPIRATIONAL — content update / balance-patch flow (NOT BUILT)

> The GDD imagined: edit in CMS → "Publish" → generate `enemy_database.json` → upload to CDN →
> clients download a few KB on next launch → balance applies in < 5 minutes, no game patch.

**This flow does not exist and does not match the as-built architecture.** Why it can't work as
written today:

- The **authoritative numbers are in the Rust server binary**, not a JSON file the client
  downloads. A client-side JSON download cannot change what the server simulates.
- **Prediction parity** is by construction (client and server run the same `sim_core` crate). A
  unilateral client JSON change would *diverge* prediction from the server — the exact failure
  mode the shared-sim design exists to prevent.
- Deployment is **native systemd, git-pull-and-rebuild** ([ADR 0007](adr/0007-native-systemd-deployment.md)),
  via `scripts/deploy.sh`. There is no CDN / version-check / hot-reload machinery.

If a content-CMS is ever built, the realistic update flow would be **build-time, not hot**:
`edit content → CMS persists it → regenerate the server's content source → rebuild + redeploy the
Rust server (and the client GDExtension if `sim_core` numbers changed) via deploy.sh`. Server
config (non-`sim_core`) that is already runtime-loaded (`server_config.json`) could use the
lighter `deploy.sh sync` (restart, no rebuild). The "no rebuild, instant" promise is unattainable
for anything `sim_core` touches.

---

## 5. ASPIRATIONAL — CMS API endpoints & schema (NOT BUILT)

The GDD pointed at a `docs/api/cms-api.md` and a SQL schema that were never written; **neither
exists**. (`docs/index.md` still lists a stale `api/cms-api.md` link — the real, as-built API doc
is [`api/web-api.md`](api/web-api.md).) When designing the content-CMS:

- New designer endpoints would live in the **Go API** (`api/internal/handlers/`), guarded by an
  **admin / designer role** (the API today only has player JWT auth + server-secret headers — no
  admin role exists yet).
- New tables (enemies, items, spells, balance patches, analytics) would live in the same
  **Postgres** the API already owns.
- The designer UI would be **new pages in `web/`** (Astro), reusing the existing BFF /
  httpOnly-cookie auth pattern.

---

## 6. If you build the content-CMS — the open decision

The load-bearing question is **how authoritative content data reaches the Rust server**, given
that monster/class/ability stats are currently compiled-in and that `sim_core` is shared with the
client for prediction parity:

1. **Build-time codegen (most aligned with today).** CMS persists content in Postgres → a build
   step regenerates Rust constants (the `monster.rs` / `ability.rs` statics, and any `sim_core`
   tuning) → normal `deploy.sh` rebuild. Keeps the shared-sim guarantee intact. Cost: a deploy per
   balance change.
2. **Runtime data-loading in the server.** Make `omega-server` load monster/class JSON at startup
   (like it already does for `server_config.json`). Non-`sim_core` numbers (e.g. monster HP / AI
   tuning) could change with a `deploy.sh sync` restart. Anything `sim_core` evaluates (movement,
   ability mechanics used for prediction) **still** needs the client GDExtension rebuilt in
   lockstep, or prediction diverges — so this only helps server-only stats.
3. **Hot-reload (the GDD dream).** Not feasible without breaking prediction parity for any
   `sim_core` value; at best viable for purely server-side, non-predicted stats, and even then
   needs a reload hook the server doesn't have.

Recommended default: option 1 for `sim_core`-touching values, option 2 for purely server-side
content (monster HP, AI ranges, XP rewards) that prediction never reads.

---

## Cross-references

- **As-built HTTP/JSON contract + Astro SSR integration:** [`api/web-api.md`](api/web-api.md)
- **As-built website app:** [`web/README.md`](../web/README.md), `web/src/`
- **Authoritative server (where content actually lives today):** [`server/design.md`](server/design.md),
  [`server/contract.md`](server/contract.md); statics in `rust/server/src/sim/monster.rs`,
  `rust/server/src/sim/ability.rs`; runtime config in `rust/server/src/main.rs` ↔
  `client/data/config/server_config.json`
- **Deployment (no CDN; git-pull rebuild):** [ADR 0007](adr/0007-native-systemd-deployment.md),
  `scripts/deploy.sh`
- **Glory / sacrifice / progression authority:** [`api/web-api.md`](api/web-api.md) §3
