# Omega Realm — Infrastructure & Deployment

**Status:** As-built reality (Phase 1) + scaling **Vision** (Phases 2–3, *not built*).
**Originally:** `docs/INFRASTRUCTURE.md` (Nov 2024, pre-Rust-port).

> **⚠️ Read this banner first.** This document predates the Rust server port and was
> rewritten to match it. The authoritative server is the Rust **`omega-server`** binary over
> **ENet/UDP** — the Godot headless server is retired. **What runs today is a single
> droplet** (the "Phase 1" section below), deployed as **native systemd** services with no
> Docker ([ADR 0007](../adr/0007-native-systemd-deployment.md)). The full operational runbook
> — provision, deploy, TLS, rollback — lives in
> [`deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md); this doc is the *shape and
> rationale*, not the step-by-step.
>
> Everything under **Vision** (multi-region, CloudFlare, HAProxy, managed/replicated
> Postgres, Redis cluster, per-zone shards) is a **future design, not provisioned**. Treat
> those diagrams as a target, not a description. When this file and the code/deploy scripts
> disagree, **the code wins** — re-ground against `deployment/` and
> [`server/design.md`](../server/design.md).

---

## Table of Contents

1. [Phase 1 — what runs today (single droplet)](#phase-1--what-runs-today-single-droplet)
2. [The five services + TLS front](#the-five-services--tls-front)
3. [Networking & firewall](#networking--firewall)
4. [Deploy: git-pull-and-rebuild](#deploy-git-pull-and-rebuild)
5. [Data: PostgreSQL + Redis](#data-postgresql--redis)
6. [Monitoring](#monitoring)
7. [Vision (Phase 2–3) — not built](#vision-phase-23--not-built)

---

## Phase 1 — what runs today (single droplet)

One Ubuntu 24.04 LTS DigitalOcean droplet runs the **entire** stack as native systemd
services — no Docker, no orchestrator, no load balancer ([ADR 0007](../adr/0007-native-systemd-deployment.md)).
This is deliberate: the POC exists to measure honest UDP latency/throughput at MMO scale, and
a network shim on game traffic would pollute the very metric under test (ADR 0007 §Context).

**Why one box is enough right now.** One `omega-server` process **is one Instance** (one 30 Hz
tick loop). The binding constraint for the target is **bandwidth, not CPU**
([`server/design.md`](../server/design.md) §tick), so a single host comfortably carries both
game Instances plus the API and data tier for Alpha-scale player counts.

**Specs.**
- **Minimum useful:** 2 vCPU / 4 GB (≈100 concurrent players).
- **Smoke-test floor:** the $6 1 vCPU / 1 GB box runs everything, but is tight for two game
  Instances + API + Postgres + Redis. `provision_server.sh` adds a **2 GB swapfile** so the
  on-server Rust release build doesn't OOM.
- **Image:** Ubuntu 24.04 LTS.

```
┌─────────────────────────────────────────────────────────────┐
│            Single Droplet (Ubuntu 24.04, systemd)           │
│                                                             │
│  Internet ──:443/tcp──▶ caddy (TLS, auto Let's Encrypt)     │
│                            └──▶ omega-api @ 127.0.0.1:8080  │
│  Internet ──:8081/udp─▶ omega-arena     (ENet/UDP)          │
│  Internet ──:8082/udp─▶ omega-sanctuary (ENet/UDP)          │
│                                                             │
│  localhost only:                                            │
│    omega-api  :8080/tcp   Go API (auth, chars, leaderboard) │
│    PostgreSQL :5432       durable account/character state   │
│    Redis      :6379       session/leaderboard cache, regions│
│    Prometheus :9100/:9101 arena / sanctuary metrics         │
└─────────────────────────────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
          [Game Client]           [CMS / web]
        (ENet/UDP + HTTPS)            (HTTPS)
```

`:80/tcp` exists only for the ACME HTTP-01 challenge and the HTTP→HTTPS redirect. Before
`setup_tls.sh` runs, the API is reachable directly on `:8080/tcp`; once Caddy fronts it, that
direct port is closed at the firewall.

---

## The five services + TLS front

systemd units live in [`deployment/systemd/`](../../deployment/systemd/); per-Instance configs
in `deployment/server_config.{arena,sanctuary}.json`. All carry `Restart=always` + boot-enable,
so systemd handles supervision and crash recovery (the job Docker's `restart:` policy used to do).

| Service | Unit | Listens | Source | Persists? |
|---|---|---|---|---|
| Go API | `omega-api` | `127.0.0.1:8080/tcp` (public via Caddy `:443`) | `api/bin/server` | **all durable state** |
| Game — **Arena** | `omega-arena` | `:8081/udp` · metrics `:9100` (localhost) | `omega-server --config server_config.arena.json` | no (in-memory) |
| Game — **Sanctuary** | `omega-sanctuary` | `:8082/udp` · metrics `:9101` (localhost) | same binary `--config server_config.sanctuary.json` | no (in-memory) |
| PostgreSQL | `postgresql` (apt) | `127.0.0.1:5432` | apt | yes — system of record |
| Redis | `redis-server` (apt) | `127.0.0.1:6379` | apt | cache + region heartbeat TTL |

Plus the **TLS front**, not one of the five but always present in a public deploy:

| Service | Unit | Listens | Role |
|---|---|---|---|
| Caddy | `caddy` (apt) | `:443/tcp` (+ `:80` redirect/ACME) | terminates TLS, reverse-proxies → `omega-api` on localhost (auto Let's Encrypt). Installed by `setup_tls.sh`; config in [`deployment/Caddyfile`](../../deployment/Caddyfile). |

**Two game Instances, always.** The client (`network_manager.gd`) connects to the **Sanctuary**
hub (`8082`) first and the **Arena** (`8081`) on entry, so a playable deployment runs **both** —
one process per Instance, one crash never touches the other. The metrics port is config-only (no
env override), so the two JSON configs assign `9100`/`9101` to avoid a bind clash; `server.env`
must **not** set `GAME_SERVER_PORT` (env wins over config and would force both onto one port —
ADR 0007 §Consequences).

Entity id ranges are uniform across both Instances: **players 1–999, projectiles 10000–29999,
monsters 30000–39999, world-effect entities 40000–49999** ([`server/contract.md`](../server/contract.md)).

---

## Networking & firewall

`deployment/harden_vps.sh` sets ufw to **default-deny inbound** and opens only:

| Port | Proto | For |
|---|---|---|
| `22` (or your SSH port) | tcp | SSH, rate-limited (`ufw limit`) |
| `80` | tcp | ACME HTTP-01 challenge + HTTP→HTTPS redirect |
| `443` | tcp | HTTPS (Caddy → Go API) |
| `8080` | tcp | Go API direct — **closed by `setup_tls.sh`** once Caddy fronts it |
| `8081` | udp | Arena game traffic (ENet/UDP) |
| `8082` | udp | Sanctuary game traffic (ENet/UDP) |

**Intentionally NOT opened:** Prometheus `9100`/`9101`, PostgreSQL `5432`, Redis `6379`. The Rust
server binds metrics to `127.0.0.1`; Postgres/Redis bind localhost. With native services the
firewall is **authoritative** (unlike Docker's published-port path, which sidestepped ufw — ADR
0007 §Context). To scrape metrics remotely, use an SSH tunnel or a **source-restricted** rule
(`ufw allow from <scraper-ip> to any port 9100`), never `ufw allow 9100/tcp` to the world.

`harden_vps.sh` also installs **fail2ban** and locks down SSH (key-only, no root password login).

---

## Deploy: git-pull-and-rebuild

**Git is the deploy channel.** There is no artifact store: a laptop-side `scripts/deploy.sh`
SSHes in and the server `git reset --hard origin/<branch>`, rebuilds the Go + Rust binaries in
place, restarts the units, and health-checks. The systemd units don't care *how* the binary
arrives, so build-on-CI + `rsync` is an easy later swap if on-box builds get painful (ADR 0007
§Costs).

```bash
# from your laptop, repo root:
./scripts/deploy.sh provision   # one-time: clone repo + install Go/Rust/Postgres/Redis,
                                #            units, swapfile, narrow systemctl sudoers
./scripts/deploy.sh             # (default) pull master → rebuild api+arena+sanctuary → restart → health
./scripts/deploy.sh all         # one-shot: OS update → deploy → health
./scripts/deploy.sh sync        # BUILD-FREE: pull + restart + health (runtime-only, e.g. server_config.*.json)
./scripts/deploy.sh pull        # JUST sync the checkout — no rebuild, no restart (docs, deploy scripts)
./scripts/deploy.sh status|logs|health|restart
```

TLS is a separate one-time step (`deployment/setup_tls.sh`): point an A/AAAA record at the droplet,
then it installs Caddy, copies the Caddyfile, pins `OMEGA_API_DOMAIN`, and closes the direct `:8080`
firewall rule. Full runbook (provision → harden → deploy → TLS → rollback) is
[`deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md).

---

## Data: PostgreSQL + Redis

Both run **locally on the droplet** as apt-supervised systemd services, bound to localhost.

- **PostgreSQL** is the **system of record** for *all* durable state: accounts, characters,
  leaderboard, regions, Glory. The game servers hold **no** durable state — gameplay state is
  server-authoritative and **in-memory**, and **death is a transactional API save**, not
  save-on-leave ([`server/design.md`](../server/design.md) §persistence,
  [ADR 0005](../adr/0005-permadeath-persistence-model.md)).
- **Redis** backs session/leaderboard caching and the **region heartbeat**: each Instance posts
  `POST /api/regions/heartbeat` every 2 s into a Redis key with a 5 s TTL — the **sole** signal
  behind `GET /api/regions` (no TCP probe; the server is UDP-only).

**Auth boundary.** The Go API mints a short-lived **Ed25519 session ticket** (private key
API-side); the game server **verifies it locally** against the public key — no per-join API
round-trip. The player-facing deploy currently runs `--allow-unsigned-tickets` until the client
fetch flow lands ([`server/design.md`](../server/design.md) §auth). The Go API also enforces a
**single active session per account** and owns atomic bank↔character item transfers — the
durable-state invariants that keep the two languages from racing into dupes.

> **Self-hosted on the box** (not DO Managed) is the Phase-1 choice: lowest cost, lowest latency
> to the API, and the firewall stays authoritative. Managed/replicated Postgres is a **Vision**
> item below — see the trade in [ADR 0007](../adr/0007-native-systemd-deployment.md).

---

## Monitoring

Each game Instance exposes a Prometheus `/metrics` endpoint on localhost (arena `:9100`,
sanctuary `:9101`) — tick time, players, bandwidth, snapshot bytes, and the **correction-snap
rate** (the live prediction-divergence signal). The Go API exposes `GET /health`.

```bash
# [server] quick manual checks
systemctl status omega-api omega-arena omega-sanctuary postgresql redis-server caddy
curl -s http://localhost:8080/health
curl -s http://localhost:9100/metrics | grep tick      # arena (sanctuary = :9101)
journalctl -fu omega-api -u omega-arena -u omega-sanctuary
redis-cli ping
sudo -u postgres psql -c "SELECT version();"
```

Scrape the metrics ports over an SSH tunnel or a source-restricted ufw rule — they are **not**
open to the internet (see [Firewall](#networking--firewall)).

---

## Vision (Phase 2–3) — not built

> **None of this is provisioned.** It is the scale-out target *if and when* player counts
> demand it. The single-box model above governs the POC; a future multi-region build may
> reintroduce an orchestrator (Kubernetes / Nomad) and containers **on its own merits** — that
> does not change today's reality ([ADR 0007](../adr/0007-native-systemd-deployment.md)
> §Consequences). Treat every diagram in this section as aspirational.

### Scaling path (target decision tree)

```
Player Count → Infrastructure Decision (VISION)

  0–100      → single droplet, all services      ← WHAT WE RUN TODAY (Phase 1)
  100–500    → 2× game hosts + separate API + managed DB
  500–2000   → game hosts by zone, 2× API, Postgres HA
  2000–10000 → 12+ game hosts (zone shards), 3–5 API, PG HA + replicas, Redis cluster, LBs
  10000+     → multi-region: 20+ game hosts/region, full HA, global CDN
```

### Phase 2 (Vision) — Beta scale-out, single region

Split the single box into dedicated hosts: 2× game-server droplets (by zone), a separate API
droplet, **DO Managed PostgreSQL** (automated backups, optional HA), and **DO Managed Redis**.
Still one region (Singapore primary). No code change — just more `omega-server` Instances and a
remote DB endpoint in `api.env`.

### Phase 3 (Vision) — Production, multi-region

```
                  ┌─────────────────────────────────────┐
                  │   CloudFlare Global CDN  (VISION)   │
                  │   static assets + DDoS protection   │
                  └─────────────────────────────────────┘
                       ▲              ▲              ▲
        ┌──────────────┘              │              └──────────────┐
        ▼                             ▼                             ▼
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│ FRANKFURT (EU)   │        │ SINGAPORE (prim) │        │ US-WEST (Americas)│
│  HAProxy LB      │        │  HAProxy LB      │        │  HAProxy LB       │
│  API cluster ×3  │        │  API cluster ×3  │        │  API cluster ×3   │
│  Game shards     │        │  Game shards     │        │  Game shards      │
│  PG read-replica │        │  PG primary (HA) │        │  PG read-replica  │
└──────────────────┘        └────────┬─────────┘        └──────────────────┘
                                      │
                            ┌─────────┴──────────┐
                            │  Global Redis      │
                            │  cluster (boards)  │
                            └────────────────────┘
```

**Why these pieces (Vision):**
- **CloudFlare** — static-asset CDN, DDoS protection, Geo-IP routing (Europe→FRA, APAC→SGP,
  Americas→US-West).
- **HAProxy per region** — load-balances the API cluster (the game servers are connected to
  **directly** by IP after the API hands one out; LBs front the API, not the UDP game traffic).
- **PostgreSQL primary + read-replicas** — writes through the Singapore primary, region-local
  reads. Character saves tolerate 100–200 ms cross-region latency.
- **Redis cluster** — globally-replicated leaderboards (read-local, write-primary).
- **Game state stays local & ephemeral** — no cross-region replication; matchmaking/PvP happen
  within a region for low latency, cross-region coordination goes through the API.

Cross-region data strategy, player-routing flow, and per-region cost estimates from the original
Nov-2024 design are preserved in git history — pull them forward only when a real multi-region
build is on the table.

---

## See also

- [ADR 0007 — Native systemd deployment](../adr/0007-native-systemd-deployment.md) — *why no Docker*; the canonical service table.
- [`deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md) — the step-by-step runbook (provision, harden, deploy, TLS, rollback).
- [`deployment/`](../../deployment/) — units, configs, `provision_server.sh`, `server_update.sh`, `server_sync.sh`, `harden_vps.sh`, `setup_tls.sh`, `Caddyfile`.
- [`server/design.md`](../server/design.md) — server architecture, transport, auth, persistence.
- [`server/contract.md`](../server/contract.md) — wire format, channels, numerics, entity id ranges (as built).
- [`ops/architecture.md`](architecture.md) — top-level system architecture + POC success criteria.
- [ADR 0003 — ENet/UDP transport](../adr/0003-enet-udp-transport.md) · [ADR 0005 — permadeath persistence](../adr/0005-permadeath-persistence-model.md).
