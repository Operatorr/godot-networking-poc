# Multi-region deployment

**Status:** As-built mechanism (the region registry + heartbeat + client select flow exist and
work today); this doc is the **operator guide** for actually running game servers in more than
one DigitalOcean region. The broader scaling vision lives in
[`infrastructure.md`](infrastructure.md); the step-by-step runbook is
[`../../deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md).

> **The one idea to hold onto:** there are **two planes**. The **control plane** (Go API +
> Postgres + Redis) is **global — exactly one**, and is what `api_base_url` points at. The
> **game plane** (the Rust `omega-server`) is **regional — one per location**. The client talks
> to the single API for everything *except the game itself*, and the API tells it which regional
> game server to open a UDP connection to. So a single `api_base_url` is correct by design — it
> is not a bottleneck for gameplay, because gameplay traffic never goes through it.

## Why one API is fine

| | Control plane (Go API) | Game plane (`omega-server`) |
|---|---|---|
| Count | **One, global** | **One per region** (Frankfurt, Singapore, …) |
| Transport | HTTPS — `api_base_url` | ENet/**UDP**, bare `host:port` (ADR 0003) |
| Owns | accounts, characters, leaderboard, region registry, progression | the live in-memory sim (movement, combat, hits) |
| Latency-sensitive? | No — login, region list, XP/Glory saves | **Yes** — must be near the player |
| State | PostgreSQL (durable) + Redis (sessions, region heartbeats) | in-memory, authoritative, ephemeral |

Only **control-plane** calls cross regions (a Singapore game server calling the Frankfurt API
for heartbeats, ticket validation, and progression saves). Those tolerate ~150 ms round-trips
fine — they are not on the per-tick path. **Real-time game packets stay regional:** a Singapore
player ↔ the Singapore droplet, never via Frankfurt.

## Topology (Frankfurt + Singapore)

```
                       ┌────────────────────────────────────────────────┐
   Client ─── HTTPS ──▶│  Droplet A — Frankfurt  (CONTROL PLANE, global)  │
  (api_base_url =      │   • Go API   api.omega.marrowtech.app:443        │
   one address)        │   • PostgreSQL + Redis                           │◀──┐
                       │   • omega-server (region=europe) :8081 / :8082   │   │  heartbeat (2s)
                       └────────────────────────────────────────────────┘   │  + ticket verify
                                  ▲                                           │  + progression
            GET /api/regions ─────┘  region list w/ host:port                 │  (HTTP, control
            POST /api/regions/select                                          │   plane only)
                                                                              │
                       ┌────────────────────────────────────────────────┐   │
   Client ─── UDP ────▶│  Droplet B — Singapore  (GAME PLANE only)        │───┘
  (after selecting     │   • omega-server (region=asia) :8081 / :8082     │
   "Asia" in the menu) │     api_server_url → Frankfurt API (public)      │
                       │     advertise_url  → sgp.omega.marrowtech.app    │
                       └────────────────────────────────────────────────┘
```

- **Droplet A** runs the whole control plane **plus** a game server for its own region
  (`europe`). Postgres/Redis stay here; characters and leaderboard are global and consistent.
- **Droplet B** runs **only** game servers. Its `api_server_url` points at the **public**
  Frankfurt API; its `advertise_url` is its **own** public address.
- Each droplet runs **both instances** — Arena (`:8081`) and the Sanctuary hub (`:8082`). The
  Sanctuary is **per-region** (see below).

## How a player reaches the right server

This flow is already implemented end to end:

1. Client logs in against the single `api_base_url`
   ([`auth_manager.gd`](../../client/autoload/auth_manager.gd)).
2. The main menu calls `GET /api/regions`
   ([`main_menu.gd`](../../client/scripts/ui/menus/main_menu.gd)) and shows a dropdown. The API
   returns **only regions with a live heartbeat** ([`onlineRegions`](../../api/internal/handlers/region.go)),
   each carrying a connect `host:port`.
3. Each game server pushes a heartbeat every ~2 s
   ([`api_client.rs`](../../rust/server/src/net/api_client.rs)) advertising its `region`,
   `active_players`, and **`advertise_url`** (its own public `host:port`). The API stores it in
   Redis with a 5 s TTL — a dead server **drops out of the list automatically**.
4. The player picks a region (`POST /api/regions/select`); the client splits the returned URL
   into host/port ([`_split_host_port`](../../client/autoload/network_manager.gd)) and opens an
   **ENet/UDP** connection straight to that regional droplet. The Sanctuary address is derived
   from the same host on port `8082`.

The live `advertise_url` from the heartbeat **overrides** the static `REGION_<ID>_URL` fallback
([`applyRuntimeStatuses`](../../api/internal/handlers/region.go)) — the game server tells the API
where to reach it, not the reverse.

## The Sanctuary is per-region

The social hub runs **once per region**, alongside that region's Arena (`:8082` next to `:8081`),
and the client derives its address from the **selected** region's host
([`network_manager.gd`](../../client/autoload/network_manager.gd)). So a player who selects "Asia"
lands in the Singapore Sanctuary and the Singapore Arena — never a cross-region hop for
gameplay. There is intentionally **no single global hub** (that would force every player onto one
region's UDP server and defeat the point). A global town is a future design question, not a
requirement for the POC.

## What each droplet needs configured

### Game droplets — `deployment/server_config.<instance>.json` (per instance)
- `"region"` — `"europe"` on Frankfurt, `"asia"` on Singapore (valid ids: `local`, `asia`,
  `europe`, `us-west`; the heartbeat lower-cases it).
- `"advertise_url"` — that droplet's **public** `host:port`, e.g.
  `fra.omega.marrowtech.app:8081` / `sgp.omega.marrowtech.app:8081`. This is the authoritative
  source of the connect address.
- `"api_server_url"` — the **public** Frankfurt API URL (the default `http://localhost:8080` is
  only correct on the droplet co-located with the API).

### Game droplets — `deployment/env/server.env`
- `SERVER_API_TOKEN` and `REGION_HEARTBEAT_TOKEN` — **must match** the API's values, or
  progression and heartbeats fail closed (`503`/`401`). Same secrets on every droplet.
- `OMEGA_TICKET_PUBKEY` — the public half of the API's Ed25519 session-ticket key (same on all).

### API droplet — `deployment/env/api.env`
- `REGION_ASIA_URL` / `REGION_EUROPE_URL` / … — optional static fallbacks (bare `host:port`).
  Leave blank to rely purely on the heartbeat `advertise_url`; set them if you want a region to
  show a sane address even in the brief window before its first heartbeat.

### DNS
- One `A` record per game region → that droplet's IP (`fra…`, `sgp…`), each on UDP `8081`/`8082`.
- The API behind its own name with TLS (Caddy already does this — `deployment/Caddyfile`).
- Game servers need **no TLS** — raw UDP.

## The eight questions

- **Client:** picks a region from the API-provided list; connects over UDP to that region only.
- **Server:** each regional `omega-server` runs an independent authoritative sim and heartbeats
  the global API.
- **Predicted / replicated:** unchanged from single-region — all within one regional server.
- **Persisted:** **globally**, in the one Postgres via the API. A character's XP/Glory is the
  same wherever it plays; only transient combat/HP state is per-region and in-memory.
- **Validated:** region id against `ValidRegions`; heartbeat + internal calls gated by shared
  tokens; region must be `online` and not full at select time.
- **Fails:** if a region's game server dies, its heartbeat lapses (5 s TTL) and it disappears
  from the menu; the control plane (and other regions) are unaffected. If the **API** region
  (Frankfurt) goes down, login and saves stop globally — that is the single point of failure of
  the one-API design, accepted for the POC.
- **Tested:** API region logic in `api/internal/handlers/region_test.go` and
  `api/internal/models/region_test.go`.

## Known limitations / follow-ups

- **One character, two regions:** a global character could in principle connect to two regional
  servers at once (each keeps its own in-memory copy; only progression reconciles via the API).
  Session/ticket handling should enforce single-presence before this matters at scale.
- **Single-API SPOF:** acceptable for the POC. The scaling path (replicated Postgres, Redis
  cluster, multiple API replicas behind anycast) is the **Vision** in
  [`infrastructure.md`](infrastructure.md).
