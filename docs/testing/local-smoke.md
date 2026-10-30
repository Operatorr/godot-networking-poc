# Local stack smoke test

Run a disposable native stack and a rendered Godot client with one automated companion
client. Both authenticate, enter the real Sanctuary scene, receive each other's replicated
entities, then activate the existing Arena portal and enter the real Arena scene.

```bash
# Once, and again after source changes or a Godot upgrade; builds and imports may take minutes.
./scripts/smoke_local.py --prepare

# The actual smoke run: maximum 20 seconds, including service startup and cleanup.
./scripts/smoke_local.py
```

Requires Python 3.9+, Godot, Rust/Cargo, Go, native PostgreSQL and Redis. Preparation builds
the Go API, ticket key generator, Rust server and GDExtension, then imports the Godot project.
The smoke run rejects stale builds instead of silently testing old code. No Docker is used.
Preparation also rejects source edits made during the build/import steps instead of marking
older binaries as current.

PostgreSQL and Redis are found on PATH, with a DBngin fallback on macOS. Explicit paths:

```bash
./scripts/smoke_local.py \
  --postgres /path/to/postgresql/bin/postgres \
  --redis /path/to/redis-server \
  --godot /path/to/godot
```

PostgreSQL's `initdb` and `pg_isready` must be beside `postgres`. A desktop session is required:
both clients run the normal rendering, HUD, prediction and scene lifecycle. The companion is
a second Godot client driven by test inputs, rather than the Rust load-test swarm. Its separate
ENet connection, account, character and process exercise remote-player replication too.

## What passes

1. Start a new PostgreSQL cluster, Redis, Go API and two Rust Instances (Sanctuary and Arena).
2. Register/login two temporary accounts and create Softcore Mage characters through the API.
3. Each client obtains a signed session ticket through `AuthManager`, connects to Sanctuary,
   and receives server-authoritative character progression, Snapshots and ActionConfirms.
4. Both render the other player and produce server-confirmed movement. Observe Sanctuary
   for three seconds after both are ready.
5. Activate both actual Arena portals without walking across town. This runs the usual
   disconnect, ticket refresh, reconnect and scene change.
6. Repeat the replication/movement checks in Arena. Move towards monsters and shoot for
   up to three seconds, ending early if the server reports a player/monster damage event.
   Both clients must receive monsters and their own authoritative projectile-fired events.
   A run can pass without damage; `monster_interactions` in the report distinguishes that case.
7. Verify region heartbeats through the Redis-backed API, inspect every process log for runtime
   errors, and require successful client exits.

Exit code `0` means PASS; nonzero means failure, interruption or timeout. Missing readiness,
authentication failures, unexpected process exits and Godot/Rust/PostgreSQL errors fail the run.
Godot's exit-time ObjectDB leak warning also fails the run, even if gameplay checks succeeded.
This is a short integration check, not a load test or validation of the live server.

On Redis 7.0, go-redis logs an optional maintenance-notification handshake fallback. The runner
recognizes only that exact message and records it in `result.json` under `notices`; Redis health
and region-heartbeat checks must still pass. Other Redis errors remain failures.

## Isolation and evidence

The runner does **not** source `api/.env`, `.env.test` or deployment env files. Database/API
ports, temporary account credentials, signing keys and internal service tokens are generated
for each run. Database/Redis traffic stays on loopback. The game servers use UDP 8081 and 8082
because the existing portal routing uses those ports; the runner fails if they are occupied.

Two temporary project manifests reuse the repository's assets and import cache while giving
each client its own `user://` directory. Existing saved tokens, settings, databases and running
services are not used. The runner stops only process groups it created and removes the temporary
database, client user directories and credential files on success, failure or Ctrl+C.
Each cleanup step is attempted independently; failures are recorded under `cleanup_errors`
and turn an otherwise successful run into a failure. Owned process groups are checked and
terminated even when their original process has already exited.

Logs and `result.json` remain in `logs/local-smoke/<run>/` (gitignored). The report includes both
clients' Snapshot/ActionConfirm counts, remote-player visibility, progression hydration,
movement, shot counts and monster interactions for each phase, plus elapsed time and cleanup
status. Service shutdown messages may follow the runtime log check.

The 20-second budget includes `initdb`, service startup, authentication, both scenes and cleanup;
1.5 seconds is reserved for cleanup. A cold or overloaded machine may fail with a timeout.
Compilation and Godot resource import are explicitly outside this budget in `--prepare`.
For checking the timeout path itself, use `./scripts/smoke_local.py --timeout 3`.

## Verification (2026-10-30)

On Godot 4.7.2/macOS, the final full run **passed in 9.7 seconds**, including signed-ticket joins,
three seconds in Sanctuary, both Arena portals, confirmed movement and shots, a monster damage
event, region heartbeats and cleanup. Both actors exited successfully without object-leak
warnings. The recognized Redis 7.0 optional-feature fallback remains recorded as a notice.

The initial run exposed five leaked `RefCounted` objects per actor during cold background
scene loading. A smaller scene-transition reproduction also leaked; initializing the scene's
entry script on the main thread removed the leak. `SceneManager` now loads entry scripts before
background-loading the remaining scene assets and holds them through instantiation. The smoke
continues to fail on exit leaks. Explicit audio shutdown in the driver also releases active
playback before the short test exits.

The forced three-second timeout returned failure and finished cleanup within its cap (the
runner reserves cleanup time). The occupied-UDP-port check failed immediately and left the
existing socket working. Temporary databases, credentials and client user directories were
removed, and both game ports were available after the final run.

Run the focused orchestration recovery regressions without any game services:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p test_smoke_local.py -v
```

The nine tests cover cleanup I/O failures, interrupted credential writes, an exited process-group
leader with a SIGTERM-resistant descendant, edits during preparation, service crashes during
client shutdown, and successful exits. The full rendered smoke is the regression check for the
cold scene-loading leak.

## Existing direct-connect tests

`client/scenes/test/net_smoke.tscn` targets `127.0.0.1:8081` and checks ENet/auth/Snapshot/
ActionConfirm traffic, without rendering the actual levels. `scripts/dev_local.sh` starts
the API and both game servers but expects PostgreSQL and Redis to already be running.

`TestConfig` can read `.env.test` (`API_SERVER_URL`, `GAME_SERVER_HOST`, `GAME_SERVER_PORT`
and test account fields). The basic `net_smoke.tscn` does not use it. The load-test wrapper's
live default is `gsapi.marrowtech.app:8081`, overridable with `OMEGA_LIVE_SERVER`; the local
stack smoke never uses that endpoint or the live load-test secret.
