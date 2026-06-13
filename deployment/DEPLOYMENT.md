# Omega Realm — Deployment Guide (native, Docker-free)

Deploy the Omega Realm stack to a single Ubuntu 24.04 droplet. Everything runs as
**native systemd services** — no Docker (see [ADR 0007](../docs/adr/0007-native-systemd-deployment.md)
for why). Git is the deploy channel: the server pulls `master` and rebuilds in place.

## Architecture

```
Internet
  ├── :8080/tcp  → omega-api      (Go: auth, characters, leaderboard, regions)
  ├── :8081/udp  → omega-arena    (Rust omega-server, ENet/UDP; metrics :9100, localhost)
  └── :8082/udp  → omega-sanctuary(Rust omega-server, ENet/UDP; metrics :9101, localhost)

localhost only: PostgreSQL :5432 · Redis :6379 · Prometheus :9100/:9101
```

One process = one Instance. The **Arena** has monsters + PvP
(±1000 + pillars); the **Sanctuary** is the safe hub (±1856 walk-through). The client
connects to the Sanctuary first, then the Arena on entry — so both must run.

Services (systemd units in [`systemd/`](systemd/)):

| Unit | What | Restart on boot | Restart on crash |
|------|------|:---:|:---:|
| `postgresql` / `redis-server` | data + cache (apt) | ✅ | ✅ |
| `omega-api` | Go API (`api/bin/server`) | ✅ | ✅ (`Restart=always`) |
| `omega-arena` | Rust server, `--config server_config.arena.json` | ✅ | ✅ |
| `omega-sanctuary` | Rust server, `--config server_config.sanctuary.json` | ✅ | ✅ |

## 1. Provision the droplet

### Specs
- **Minimum useful:** 2 vCPU / 4 GB (100 players). The $6 1 vCPU/1 GB box works for a
  functional smoke test but is tight for both game instances + API + Postgres + Redis;
  `provision_server.sh` adds a 2 GB swapfile so Rust release builds don't OOM.
- **Image:** Ubuntu 24.04 LTS.

> **Order matters on a fresh box.** Nothing is on the server yet — not even this repo.
> `provision` is what clones it. So **provision first**, then harden from the cloned repo.
> Do **not** `mkdir ~/omega-realm` by hand; `provision` creates and clones it.

> **Where each command runs.** Blocks are tagged **`[laptop]`** (your own machine, from the repo
> root) or **`[server]`** (an SSH shell on the droplet). The deploy is laptop-driven —
> `scripts/deploy.sh` SSHes in for you — so you only open an SSH shell by hand for Steps 2 and 3.
> A `# → now on the server` marker shows where an `ssh` line inside a block hands you over.

### Step 1 — One-time bootstrap (clones the repo + installs everything)

Installs Go (official tarball — apt's is too old for `go 1.24`), Rust (rustup),
PostgreSQL, Redis, swap, the systemd units, and a narrow passwordless `systemctl`
rule for the three Omega services — and **clones the repo** into `~/omega-realm`. From
your **laptop** (asks for the `deploy` user's sudo password; idempotent):

```bash
# [laptop]
./scripts/deploy.sh provision
```

### Step 2 — Harden the box

The repo is on the server now (Step 1 cloned it), so run the hardening script from there —
firewall (opens 22, 8080/tcp, 8081+8082/udp), fail2ban, SSH lockdown, unattended-upgrades.

Run it from an **interactive** SSH session and keep that session open until you've confirmed a
second login still works. The script disables root login and password auth, so a separate,
already-verified session is your safety net:

```bash
# [laptop]
ssh deploy@<droplet-ip>                                    # → now on the server
# [server]
cd ~/omega-realm && sudo bash deployment/harden_vps.sh     # harden (keep this shell OPEN)
# From a SECOND laptop terminal, confirm you can still reconnect:
#        ssh deploy@<droplet-ip>
# Only close the first session once the second one logs in.
```

> Don't run it as a one-shot `ssh -t deploy@<ip> '… harden_vps.sh'`: that session closes the
> instant the script finishes, so the script's "this session is still open to fix it" safety net
> is gone before you can use it. (The SSH config is validated with `sshd -t` before any reload, so
> a lockout is unlikely — but the rescue session is there for the unexpected.)

### Step 3 — Set real secrets

Provisioning installs `/etc/omega-realm/{api,server}.env` from the templates with
placeholder values. You must replace the placeholders before the stack works — several
endpoints **fail closed** when their secret is unset, and in production the **API refuses
to start at all** until `JWT_SECRET_KEY` is a real (non-placeholder) value: with a missing
or placeholder secret anyone could forge auth tokens, so the process exits instead.

Do this **all on the server, in one SSH session**: generating the Ed25519 seed there means the
private key is created where it lives and never leaves the box.

```bash
# [laptop]
ssh deploy@<droplet-ip>                  # → now on the server for the rest of Step 3
# [server] — generate the secrets (run each line separately; use a DIFFERENT value for each):
openssl rand -hex 32                                    # JWT_SECRET_KEY      (signs auth tokens; api.env only)
openssl rand -hex 32                                    # SERVER_API_TOKEN
openssl rand -hex 32                                    # REGION_HEARTBEAT_TOKEN
cd ~/omega-realm/api && go run ./cmd/gen_ticket_key     # OMEGA_TICKET_PRIVKEY + OMEGA_TICKET_PUBKEY
# [server] — set the DB password, then paste the values into the env files:
sudo -u postgres psql -c "ALTER ROLE omega PASSWORD 'YOUR_DB_PASSWORD';"
sudo nano /etc/omega-realm/api.env      # DB_PASSWORD, JWT_SECRET_KEY, SERVER_API_TOKEN,
                                        # REGION_HEARTBEAT_TOKEN, OMEGA_TICKET_PRIVKEY
sudo nano /etc/omega-realm/server.env   # SERVER_API_TOKEN + REGION_HEARTBEAT_TOKEN (MATCH
                                        # api.env), OMEGA_TICKET_PUBKEY, ticket policy
exit                                    # → back on your laptop
```

`gen_ticket_key` prints a matched Ed25519 pair: the **private** seed goes in `api.env` (the API
signs tickets), the **public** key goes in `server.env` (the game server verifies) — both from the
same run. What must line up across the two files:

| Secret | api.env | server.env | Must match? |
|---|---|---|---|
| `JWT_SECRET_KEY` | ✅ | — | api.env only (not shared) |
| `SERVER_API_TOKEN` | ✅ | ✅ | **identical** |
| `REGION_HEARTBEAT_TOKEN` | ✅ | ✅ | **identical** |
| Ed25519 ticket key | `OMEGA_TICKET_PRIVKEY` (private) | `OMEGA_TICKET_PUBKEY` (public) | same keypair |

> **Ticket policy — heads up.** The shipped default is `OMEGA_ALLOW_UNSIGNED_TICKETS=false`
> (fail closed, require signed tickets). The **game client does not yet fetch/present
> tickets** (the M3 client flow is unbuilt), so with `false` a real player is refused. Until
> the client is wired, set `OMEGA_ALLOW_UNSIGNED_TICKETS=true` on a player-facing box. The
> signing side (API mint endpoint + keys above) is ready now, so once the client presents
> tickets you flip it back to `false` with `OMEGA_TICKET_PUBKEY` set — no server rebuild.

> `/etc/omega-realm/*.env` are `root:deploy 0640` and are **not** in the repo. The
> templates are `deployment/env/*.example`.

## 2. Deploy

From your laptop, anytime you want the server on the latest `master`:

```bash
# [laptop]
./scripts/deploy.sh                # pull master → build api + both game servers → restart → health-check
```

Under the hood this SSHes in and runs [`server_update.sh`](server_update.sh):
`git reset --hard origin/master`, `go build`, `cargo build --release`, restart all three
units, then verify `/health` (API) and `/metrics` (each instance). Deploy a different
branch with `OMEGA_BRANCH=my-branch ./scripts/deploy.sh`.

### Operate

```bash
# [laptop]
./scripts/deploy.sh sync       # pull master + restart + health-check, NO rebuild (fast)
./scripts/deploy.sh pull       # JUST sync the server's checkout — no rebuild, no restart
./scripts/deploy.sh status     # systemctl status for all three services
./scripts/deploy.sh logs       # follow journald for api + arena + sanctuary
./scripts/deploy.sh health     # curl API /health + both metrics endpoints
./scripts/deploy.sh restart    # restart without rebuilding (no pull either)
./scripts/deploy.sh ssh        # interactive shell on the box
```

**`deploy` vs `sync` vs `pull`** — three tiers, cheapest last; pick by what your change needs:

| command | recompiles? | restarts services? | use when the change is… |
| ------- | ----------- | ------------------ | ----------------------- |
| `deploy` | yes (`go build` + `cargo build --release`, minutes) | yes | compiled code under `api/` or `rust/` |
| `sync`   | no | yes | read at **runtime** — `server_config.{arena,sanctuary}.json`, other non-compiled assets a restart picks up |
| `pull`   | no | no | takes effect **without a restart** — server-side deploy scripts (`update_os.sh`, `server_update.sh`, …), docs |

All three keep the server a pristine mirror of origin (`git reset --hard origin/master`) — that
reset is instant; the cost is in the rebuild and the restart, which the lighter tiers skip.

- `sync` ([`server_sync.sh`](server_sync.sh)) leaves the existing binaries untouched and
  **guards** against misuse: if the pulled range touched `api/` or `rust/` it aborts *before*
  restarting (the binaries would be stale against the new source) and tells you to run `deploy`.
- `pull` touches nothing running — no `go`/`cargo`, no `systemctl`. The running services keep
  their current binaries and config; the new files just sit in the checkout for next time a
  script runs. Note that a change to `scripts/deploy.sh` **itself** needs no server step at all —
  that script runs on your laptop, not the box.

The API auto-applies its schema on startup (`db.Exec(schema)`), so there is no separate
migration step.

### OS maintenance

`harden_vps.sh` enables `unattended-upgrades`, so **security** patches land daily on their
own. For the periodic **full** upgrade (all packages + kernel) and Ubuntu version jumps, use
[`update_os.sh`](update_os.sh) via:

```bash
# [laptop]
./scripts/deploy.sh os-update                  # apt full-upgrade + autoremove + cleanup
./scripts/deploy.sh os-update --reboot         # ...and reboot if one is required
./scripts/deploy.sh os-update --release-upgrade # Ubuntu version bump (snapshot first!)
```

A full upgrade often wants a reboot; systemd restarts Postgres, Redis, the API, and both
game instances automatically on boot (`enable` + `Restart=always`). Verify after a reboot:
`./scripts/deploy.sh status`.

## 3. Auto-restart

`Restart=always` (units) means a crashed service comes back in 3 s; `WantedBy=multi-user.target`
+ `systemctl enable` means everything (Postgres, Redis, API, both game servers) starts on
boot. Verify:

```bash
ssh deploy@<droplet-ip> 'sudo systemctl kill -s SIGKILL omega-arena; sleep 5; systemctl is-active omega-arena'
# → active
```

## 4. Load test against the live server

From your dev machine — bots hit the **Arena** (`8081`), never the Sanctuary:

```bash
export OMEGA_SERVER=<droplet-ip>:8081           # set the live target once
./scripts/run_load_test.sh --scenario baseline  # 50 bots
./scripts/run_load_test.sh --scenario target     # 100 bots (POC success metric)
# or per-invocation: ./scripts/run_load_test.sh --scenario stress --server <droplet-ip>:8081
```

> Bots authenticate ticket-less, so `OMEGA_ALLOW_UNSIGNED_TICKETS=true` (the default in
> `server.env`). The `stress` scenario (200 bots) needs `max_players >= 200` in
> `server_config.arena.json` — raise it and redeploy.

## Runtime config reference

| File | Purpose |
|------|---------|
| `/etc/omega-realm/api.env` | API secrets + DB/Redis endpoints (`EnvironmentFile`) |
| `/etc/omega-realm/server.env` | shared game-server env (ticket policy). **No `GAME_SERVER_PORT`** — env wins over config and would clobber both instances onto one port |
| `deployment/server_config.arena.json` | Arena: mode/port 8081/metrics 9100 + sim tuning |
| `deployment/server_config.sanctuary.json` | Sanctuary: mode/port 8082/metrics 9101 |

Env precedence (game server): CLI flag > env var > JSON config > built-in default
(`rust/server/src/config.rs`).

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Service won't start | `./scripts/deploy.sh logs` → `journalctl -u omega-arena -n 80` |
| API exits on startup with "JWT config error" | `JWT_SECRET_KEY` in `/etc/omega-realm/api.env` is empty or still a placeholder — set a real one (`openssl rand -hex 32`), then `sudo systemctl restart omega-api` |
| API can't reach DB | password in `/etc/omega-realm/api.env` matches the `omega` role; `sudo -u postgres pg_isready` |
| Bots can't connect | `sudo ufw status` shows `8081/udp`; ticket policy in `server.env`; `curl localhost:9100/metrics` |
| Sanctuary metrics missing | Arena=9100, Sanctuary=9101 — they must differ (set in each JSON config) |
| Build OOM | confirm swap is on: `swapon --show` (provisioning adds 2 GB) |
| High latency | `journalctl -u omega-arena` tick warnings; consider a larger droplet |

## Rollback

```bash
ssh deploy@<droplet-ip> 'cd ~/omega-realm && git reset --hard <previous-commit>'
./scripts/deploy.sh        # rebuilds + restarts at that commit
```
