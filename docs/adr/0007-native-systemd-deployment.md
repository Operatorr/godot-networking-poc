# ADR 0007 — Native systemd deployment (drop Docker)

**Status:** Implemented — 2026-06-13. The stack deploys as native systemd services on a
single Ubuntu 24.04 droplet; Docker is removed entirely. Operational guide:
[`deployment/DEPLOYMENT.md`](../../deployment/DEPLOYMENT.md). Units in
[`deployment/systemd/`](../../deployment/systemd/); provisioning + deploy scripts in
[`deployment/`](../../deployment/) and `scripts/deploy.sh`. This supersedes the Docker
Compose deployment described in earlier revisions of `DEPLOYMENT.md` and
[`docs/INFRASTRUCTURE.md`](../INFRASTRUCTURE.md) (§Deployment Procedures).

## Decision

Run every service **natively**, supervised by **systemd**, on one host:

| Service | Unit | Listens | Source |
|---|---|---|---|
| Go API | `omega-api` | `:8080/tcp` | `api/bin/server` |
| Game server — **Arena** | `omega-arena` | `:8081/udp` (metrics `:9100`) | `rust/.../omega-server --config server_config.arena.json` |
| Game server — **Sanctuary** | `omega-sanctuary` | `:8082/udp` (metrics `:9101`) | same binary `--config server_config.sanctuary.json` |
| PostgreSQL | `postgresql` (apt) | `:5432` localhost | apt |
| Redis | `redis-server` (apt) | `:6379` localhost | apt |

**Deploy channel is git.** A laptop-side `scripts/deploy.sh` SSHes in and runs
`deployment/server_update.sh`, which `git reset --hard origin/master`, rebuilds the Go
and Rust binaries in place, restarts the three units, and health-checks. A one-time
`deployment/provision_server.sh` installs the toolchains (Go from the official tarball —
apt's is too old for `go 1.24`; Rust via rustup), PostgreSQL, Redis, a 2 GB swapfile, the
units, and a narrow passwordless `systemctl` sudoers rule scoped to the three services.

**Two game instances, always.** The client (`network_manager.gd`) connects players to the
Sanctuary hub (`8082`) first and the Arena (`8081`) on entry, so a playable deployment
runs both — one process per Instance (migration-spec D13). Each carries its own JSON
config; the metrics port is config-only (no env override), so the two configs assign
`9100`/`9101` to avoid a bind clash.

## Context — why Docker was the wrong fit here

This is a netcode POC whose *entire purpose* is measuring UDP latency at MMO scale
(AGENTS.md: "the **network** is the thing under test"). Docker added cost in exactly the
dimensions that hurt this goal:

- **Network abstraction pollutes the measurement.** Docker's default published-port path
  is iptables NAT + a userland `docker-proxy` per port. For ENet/UDP at 30 Hz × hundreds
  of peers that adds per-packet latency and syscall/copy overhead — confounding the metric
  the POC exists to produce. `network_mode: host` removes it, but then containers buy
  almost nothing for these stateless binaries.
- **Daemon RAM tax on a small box.** `dockerd`+`containerd` idle at ~80–150 MB. On the
  1 vCPU / 1 GB starter droplet that is 10–15 % of available memory before the app starts.
- **Docker bypasses ufw.** Published ports get iptables rules in the `DOCKER` chain that
  sidestep the firewall — the Compose file published Postgres `5432` and Redis `6379` on
  all interfaces, which would have been internet-exposed regardless of `ufw`. Native
  services bind localhost and are governed by the firewall we actually configured.
- **Builds OOM in-container on 1 GB.** Multi-stage Rust release builds inside the image
  were impractical on the target box; native builds + a swapfile are simpler and faster.

The containers gave us little in return: the Rust server is a self-contained static-ish
binary, the Go API a single binary, and Postgres/Redis ship well-supported apt packages +
systemd units. systemd already provides supervision, boot-start, restart-on-crash,
resource limits, and journald logging — the features Compose's `restart: unless-stopped`
was standing in for.

## Consequences

**Good**
- Zero network shim on game traffic → honest latency/throughput numbers.
- Lower memory floor; the whole stack fits the starter droplet for smoke tests.
- Firewall is authoritative again (services bind localhost; only 22, 8080/tcp,
  8081+8082/udp are exposed — see `harden_vps.sh`).
- One-command deploy/rollback over git; `Restart=always` + `enable` give boot-start and
  crash recovery; `journalctl -u <unit>` for logs.

**Costs / risks**
- **Builds on the server.** `cargo build --release` on 1 vCPU is slow; the 2 GB swapfile
  is the OOM backstop. If this becomes painful, switch to build-on-CI/laptop + `rsync` the
  binaries (the units don't care how the binary arrives).
- **No image immutability / pinned base.** Reproducibility now rests on the apt packages
  and the toolchain versions provisioned. Acceptable for a single-box POC.
- **Single host.** No orchestration story for multi-region scale-out. The
  [INFRASTRUCTURE.md](../INFRASTRUCTURE.md) Phase 3 design still applies; that future may
  reintroduce containers/orchestration on its own merits — this ADR governs the POC, not
  forever.
- **Two units to keep in lockstep.** Arena/Sanctuary share `server.env`; `GAME_SERVER_PORT`
  must **not** be set there (env wins over config and would force both onto one port).

## Alternatives considered

- **Docker with `network_mode: host`** — fixes latency + the ufw bypass, but keeps the
  daemon RAM tax and build pain while removing most of containerization's benefit. Net
  negative on this box.
- **Build-and-ship binaries (no on-server build)** — viable and faster per-deploy; rejected
  as the default only because git-pull-and-rebuild keeps the deploy channel a single
  `git` remote with no artifact store. Easy to adopt later (see costs above).
- **Nix / single static musl builds** — more reproducible, more upfront complexity than a
  POC warrants.
