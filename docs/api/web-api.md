# Omega Realm — CMS / Web API Reference

**Audience:** the Astro CMS website (hosted on Vercel) where players **register accounts** and
**create characters**. This document is self-contained: it can be pasted into the Astro repo as
LLM/agent context. It describes the Go HTTP API as built (`api/`), the endpoints the website
needs, and the recommended integration pattern.

> **Source of truth:** the Go handlers under `api/internal/handlers/` and models under
> `api/internal/models/`. If this doc and the code disagree, the code wins — update this doc.

---

## 1. Can the Astro app connect? — Yes.

The Go API is a standard JSON-over-HTTP service with JWT auth, so any frontend can call it.
**Recommended pattern: call the API only from Astro's server side** (SSR pages, API routes /
endpoints, or middleware running on Vercel), not from browser JavaScript. Why:

- **No mixed-content problem.** A browser on `https://your-site.vercel.app` is blocked from
  `fetch()`-ing a plain-`http://` API. Server-to-server calls have no such rule.
- **Tokens stay off the client.** Store the JWT in an **httpOnly cookie** set by the Astro
  server; browser JS never sees it (mitigates XSS token theft).
- **CORS is irrelevant** server-side. (The API does send `Access-Control-Allow-Origin: *`, so
  browser calls would also work CORS-wise — but SSR is preferred for the reasons above.)

### Transport security (important)
The API process serves **plain HTTP** on `:8080`. In production it must sit behind **TLS** —
the game client and the website both send passwords/JWTs, which must not travel in cleartext.
The deployment puts **Caddy** in front (automatic Let's Encrypt) so the public URL is
`https://omega.marrowtech.app`, proxying to the API on localhost. See
[`deployment/DEPLOYMENT.md` → Step 4](../../deployment/DEPLOYMENT.md). Point the CMS at the
**HTTPS** URL, never `http://…:8080`.

### Base URLs
| Environment | Base URL |
|---|---|
| Local dev | `http://localhost:8080` |
| Production | `https://omega.marrowtech.app` (TLS via Caddy) |

Health check (unauthenticated): `GET /health` → `{ "status": "healthy", "time": "<RFC3339>" }`.

---

## 2. Auth model

- **Scheme:** JSON Web Tokens. Send the access token on protected endpoints as:
  `Authorization: Bearer <access_token>`.
- **Two tokens** are returned by register/login/refresh:
  - `access_token` — short-lived (**15 minutes** in the shipped prod config; 24h if unset).
    Used on every authenticated request.
  - `refresh_token` — long-lived (**7 days**). Used only to mint a new pair when the access
    token expires.
- **Refresh flow:** when a protected call returns `401`, `POST /api/auth/refresh` with the
  refresh token to get a fresh pair, then retry. (Refresh returns a new refresh token too —
  store it.)
- **Passwords** are bcrypt-hashed server-side and never returned.

### Error shape
Every error response is JSON: `{ "error": "human-readable message" }` with a matching HTTP
status. Success bodies are documented per endpoint. All bodies are `application/json`.

---

## 3. Endpoints the CMS uses

> Auth column: **public** = no token; **Bearer** = `Authorization: Bearer <access_token>`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET`  | `/health` | public | liveness |
| `POST` | `/api/auth/register` | public | create account |
| `POST` | `/api/auth/login` | public | log in |
| `POST` | `/api/auth/refresh` | public | refresh tokens |
| `GET`  | `/api/character/me` | Bearer | get the user's character |
| `POST` | `/api/character/create` | Bearer | create the user's character |
| `POST` | `/api/character/sacrifice` | Bearer | trade character for Glory |
| `DELETE` | `/api/character` | Bearer | delete the user's character |
| `GET`  | `/api/regions` | public | list online game regions |
| `POST` | `/api/regions/select` | Bearer | select a region (returns its connect address) |
| `GET`  | `/api/leaderboard` | public | ranked players |

### POST /api/auth/register
Create an account. One account = one character slot (created later).

**Request**
```json
{ "username": "alice", "email": "alice@example.com", "password": "hunter2x", "region": "Asia" }
```
- `username` — required, 3–50 chars, unique.
- `email` — required, must contain `@`, unique.
- `password` — required, **min 6 chars**.
- `region` — optional; one of `"Asia"`, `"Europe"`, `"US-West"`. Defaults to `"Asia"`.

**Response `201 Created`**
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "user": { "id": 1, "username": "alice", "email": "alice@example.com", "region": "Asia", "glory": 0, "created_at": "0001-01-01T00:00:00Z" }
}
```
> On register, `glory` is `0` and `created_at` is the zero time (it isn't read back from the
> DB here). `login` returns the real stored values. No `character` field yet.

**Errors:** `400` invalid body / failed validation (message names the field) · `409` username or
email already exists · `500`.

### POST /api/auth/login
**Request**
```json
{ "username": "alice", "password": "hunter2x" }
```
**Response `200 OK`** — same `AuthResponse` shape, plus the user's `character` **if they have
one** (the field is omitted when absent):
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "user": { "id": 1, "username": "alice", "email": "alice@example.com", "region": "Asia", "glory": 1280, "created_at": "2026-01-05T12:00:00Z" },
  "character": { "id": 7, "user_id": 1, "name": "Valkyrie", "class": "Warrior", "race": "Human", "realm": "Asia (Singapore)", "mode": "softcore", "level": 12, "experience": 540, "created_at": "2026-01-06T09:30:00Z" }
}
```
**Errors:** `400` missing username/password · `401` invalid username or password · `500`.

### POST /api/auth/refresh
**Request** `{ "refresh_token": "<jwt>" }` → **`200 OK`** with a new `access_token` +
`refresh_token` and `user` (no `character`). **Errors:** `400` invalid body · `401`
invalid/expired refresh token or unknown user · `500`.

### GET /api/character/me  *(Bearer)*
Returns the authenticated user's character **directly** (not wrapped):
```json
{ "id": 7, "user_id": 1, "name": "Valkyrie", "class": "Warrior", "race": "Human", "realm": "Asia (Singapore)", "mode": "softcore", "level": 12, "experience": 540, "created_at": "2026-01-06T09:30:00Z" }
```
**Errors:** `401` missing/invalid token · `404` no character for this user · `500`.

### POST /api/character/create  *(Bearer)*
One character per account. The leaderboard row is auto-created with the character.

**Request** (only `name` is required; the rest default):
```json
{ "name": "Valkyrie", "class": "Warrior", "race": "Human", "realm": "Asia (Singapore)", "mode": "softcore", "level": 1 }
```
- `name` — required, 3–50 chars, letters/numbers/spaces/`_`/`-` only, no leading/trailing
  space, **globally unique**.
- `class` — default `"Warrior"`, ≤20 chars.
- `race` — default `"Human"`, ≤20 chars.
- `realm` — default `"Asia (Singapore)"`, ≤50 chars.
- `mode` — default `"softcore"`; **must be `"softcore"` or `"hardcore"`** (DB-enforced; an out-of-set value surfaces as `500`).
- `level` — default `1`; integer `1..50` (the level cap is **50**).

> Progression (`level`/`experience`) is **server-authoritative** — it is owned by the game
> server, not the website. You may seed `level` at creation, but there is no client endpoint to
> raise it afterward (by design). The website should treat `level`/`experience` as read-only.

**Response `201 Created`**
```json
{ "message": "Character created successfully", "character": { "id": 7, "user_id": 1, "name": "Valkyrie", "class": "Warrior", "race": "Human", "realm": "Asia (Singapore)", "mode": "softcore", "level": 1, "experience": 0, "created_at": "2026-01-06T09:30:00Z" } }
```
**Errors:** `400` invalid body / validation · `401` · `409` user already has a character **or**
character name already taken · `500`.

### POST /api/character/sacrifice  *(Bearer)*
Player-initiated "church sacrifice": deletes the user's character and awards account-wide Glory
(`floor(total lifetime XP / 100)`). No request body.
**Response `200 OK`** `{ "glory_awarded": 1280 }` · **Errors:** `401` · `404` no character · `500`.
*(This is primarily a game action; expose it on the website only if you want a sacrifice button.)*

### DELETE /api/character  *(Bearer)*
Deletes the user's character (no Glory). Leaderboard/session rows cascade-delete.
**Response `200 OK`** `{ "message": "Character deleted" }` · **Errors:** `401` · `404` · `500`.

### GET /api/regions
Returns the regions that currently have a **live game server** (fresh heartbeat). May be an
empty list if none is running. `connect_url` is a bare `host:port` for the ENet/UDP game
server (no scheme/TLS; ADR 0003), sourced from the server's heartbeat `advertise_url` or the
`REGION_<ID>_URL` env fallback. See [`../ops/multi-region.md`](../ops/multi-region.md).
```json
{ "regions": [ { "id": "asia", "display_name": "Asia", "connect_url": "sgp.omega.marrowtech.app:8081", "status": "online", "active_players": 12, "max_players": 200, "latency_estimate": "< 80ms" } ] }
```

### POST /api/regions/select  *(Bearer)*
**Request** `{ "region_id": "asia" }` (valid ids: `local`, `asia`, `europe`, `us-west`).
**Response `200 OK`** `{ "message": "Region selected successfully", "region": { … }, "connect_url": "…" }`.
**Errors:** `400` invalid region · `401` · `503` region unavailable or full.

### GET /api/leaderboard
Public ranked list for a rankings page.

**Query params**
- `metric` — `pvp_kills` (default) | `monster_kills` | `deaths`. Unknown value → `400`.
- `limit` — `1..100` (default `100`; out-of-range/invalid falls back to `100`).

`GET /api/leaderboard?metric=pvp_kills&limit=10` → **`200 OK`**:
```json
{
  "metric": "pvp_kills",
  "entries": [
    { "rank": 1, "character_name": "Valkyrie", "username": "alice", "region": "Asia", "pvp_kills": 142, "monster_kills": 980, "deaths": 17, "updated_at": "2026-06-14T10:00:00Z" }
  ]
}
```

---

## 4. Data models

**User** (`api/internal/models/models.go`) — `password_hash` is never serialized.
| field | type | notes |
|---|---|---|
| `id` | int | |
| `username` | string | unique, 3–50 |
| `email` | string | unique |
| `region` | string | `Asia` \| `Europe` \| `US-West` |
| `glory` | int | account-wide currency, ≥0, server-authoritative |
| `created_at` | string (RFC3339) | |

**Character**
| field | type | notes |
|---|---|---|
| `id` | int | |
| `user_id` | int | one character per user (unique) |
| `name` | string | unique, 3–50 |
| `class` / `race` / `realm` / `mode` | string | `mode` ∈ {`softcore`,`hardcore`} |
| `level` | int | 1–50 (cap 50) |
| `experience` | int | in-level XP; server-authoritative |
| `created_at` | string (RFC3339) | |

**Region** — `id`, `display_name`, `connect_url`, `status`, `active_players`, `max_players`,
`latency_estimate`.

**Leaderboard entry** — `rank`, `character_name`, `username`, `region`, `pvp_kills`,
`monster_kills`, `deaths`, `updated_at`.

---

## 5. Server-only endpoints — DO NOT call from the website

These exist for the **game server**, are guarded by shared secret headers (not JWT), and have
nothing the CMS needs. Listed so they're not mistaken for website endpoints:

| Path | Guard | Owner |
|---|---|---|
| `POST /api/leaderboard/update` | `X-Server-Token` | game server reports kills/deaths |
| `POST /api/regions/heartbeat` | `X-Region-Heartbeat-Token` | game server liveness |
| `GET/POST /api/internal/characters/{id}…` | `X-Server-Token` | progression + Glory settlement |
| `POST /api/character/ticket` | Bearer | mints a **game-connect** ticket (needed by the game client, not the website) |

---

## 6. Astro integration guide (SSR + httpOnly cookies)

> Requires an SSR-capable setup (e.g. `@astrojs/vercel` adapter, `output: 'server'` or
> `'hybrid'`). The API base URL is a **server-only** secret-ish config — name it `API_BASE_URL`
> (NOT `PUBLIC_*`, which would ship to the browser).

`.env`
```
API_BASE_URL=https://omega.marrowtech.app   # local: http://localhost:8080
```

`src/lib/omega-api.ts` — a tiny typed server-side client:
```ts
const BASE = import.meta.env.API_BASE_URL ?? "http://localhost:8080";

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: { id: number; username: string; email: string; region: string; glory: number; created_at: string };
  character?: Character;
}
export interface Character {
  id: number; user_id: number; name: string; class: string; race: string;
  realm: string; mode: string; level: number; experience: number; created_at: string;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as any).error ?? `API ${res.status}`);
  return body as T;
}

export const api = {
  register: (b: { username: string; email: string; password: string; region?: string }) =>
    call<AuthResponse>("/api/auth/register", { method: "POST", body: JSON.stringify(b) }),
  login: (b: { username: string; password: string }) =>
    call<AuthResponse>("/api/auth/login", { method: "POST", body: JSON.stringify(b) }),
  refresh: (refresh_token: string) =>
    call<AuthResponse>("/api/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token }) }),
  me: (token: string) =>
    call<Character>("/api/character/me", { headers: { Authorization: `Bearer ${token}` } }),
  createCharacter: (token: string, b: { name: string; class?: string; race?: string; realm?: string; mode?: string; level?: number }) =>
    call<{ message: string; character: Character }>("/api/character/create", {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(b),
    }),
  leaderboard: (metric = "pvp_kills", limit = 100) =>
    call<{ metric: string; entries: any[] }>(`/api/leaderboard?metric=${metric}&limit=${limit}`),
};
```

`src/pages/api/login.ts` — SSR endpoint that logs in and stores tokens in httpOnly cookies:
```ts
import type { APIRoute } from "astro";
import { api } from "../../lib/omega-api";

export const POST: APIRoute = async ({ request, cookies }) => {
  const { username, password } = await request.json();
  try {
    const auth = await api.login({ username, password });
    const secure = import.meta.env.PROD;
    cookies.set("omega_access", auth.access_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 15 });
    cookies.set("omega_refresh", auth.refresh_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 7 });
    return new Response(JSON.stringify({ user: auth.user, character: auth.character ?? null }), { status: 200 });
  } catch (e) {
    return new Response(JSON.stringify({ error: (e as Error).message }), { status: 401 });
  }
};
```

`src/pages/dashboard.astro` — read the cookie server-side, fetch the character, refresh on 401:
```astro
---
import { api } from "../lib/omega-api";
let access = Astro.cookies.get("omega_access")?.value;
let character = null;
try {
  if (access) character = await api.me(access);
} catch {
  const refresh = Astro.cookies.get("omega_refresh")?.value;
  if (refresh) {
    const fresh = await api.refresh(refresh);          // mint a new pair
    const secure = import.meta.env.PROD;
    Astro.cookies.set("omega_access", fresh.access_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 15 });
    Astro.cookies.set("omega_refresh", fresh.refresh_token, { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 7 });
    character = await api.me(fresh.access_token);
  } else {
    return Astro.redirect("/login");
  }
}
---
<h1>Welcome</h1>
{character ? <p>{character.name} — level {character.level} {character.mode}</p>
           : <a href="/create-character">Create your character</a>}
```

**Register + create-character** follow the same pattern: POST to an SSR endpoint that calls
`api.register(...)` then optionally `api.createCharacter(token, ...)`, setting the cookies on
success.

### CORS (only if you ever call from the browser directly)
The API currently allows all origins (`Access-Control-Allow-Origin: *`). That's fine for
header-based Bearer auth, but if you switch to browser-side calls **with cookies** you must
change the API to echo a specific origin and add `Access-Control-Allow-Credentials: true`
(`*` + credentials is rejected by browsers). Sticking to SSR avoids this entirely.

---

## 7. Quick smoke test (curl)
```bash
BASE=http://localhost:8080
curl -s $BASE/health
# register
curl -s -XPOST $BASE/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"hunter2x"}'
# login (capture .access_token)
TOKEN=$(curl -s -XPOST $BASE/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"hunter2x"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
# create + read character
curl -s -XPOST $BASE/api/character/create -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Valkyrie","mode":"softcore"}'
curl -s $BASE/api/character/me -H "Authorization: Bearer $TOKEN"
# leaderboard (public)
curl -s "$BASE/api/leaderboard?metric=pvp_kills&limit=10"
```
