#!/usr/bin/env python3
"""Disposable native stack + two rendered clients; see docs/testing/local-smoke.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "builds/local-smoke"
SCENE = "res://scenes/test/local_stack_smoke.tscn"
ROLES = ("client", "bot")
ERROR_LINE = re.compile(
    r"SCRIPT ERROR:|(?:^|\s)(?:ERROR|FATAL|PANIC)(?:\s|:)|"
    r"thread .* panicked|\[LocalStackSmoke\] FAIL|ObjectDB instances were leaked at exit|"
    r"\bWARN\b.*(?:failed|rejected)|\bFailed to (?:load|initialize|connect|decode)|"
    r"handle_crash:|Program crashed|Segmentation fault",
    re.IGNORECASE,
)
# go-redis probes an optional newer Redis feature and explicitly falls back on Redis 7.0.
# Preserve/report this exact notice, rather than hiding general Redis or handshake failures.
REDIS_OPTIONAL_NOTICE = "auto mode fallback: maintnotifications disabled due to handshake error: ERR unknown subcommand 'maint_notifications'. Try CLIENT HELP."


class SmokeFailure(Exception):
    pass


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def source_fingerprint() -> str:
    # Include uncommitted sources: a stale executable must not test yesterday's code.
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
         "--", "rust", "api", "client"], cwd=ROOT
    ).decode().split("\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        path = ROOT / name
        if not path.is_file() or path.suffix not in {
            ".rs", ".toml", ".lock", ".go", ".mod", ".sum", ".gd", ".tscn",
            ".godot", ".gdextension",
        }:
            continue
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def executable(name: str, override: str | None = None) -> Path:
    found = shutil.which(override or name)
    if found:
        return Path(found).resolve()
    if override:
        raise SmokeFailure(f"Executable not found: {override}")
    # DBngin installs native binaries outside PATH on macOS.
    candidates = sorted(Path("/Users/Shared/DBngin").glob(f"*/[0-9]*/bin/{name}"))
    if candidates:
        return candidates[-1]
    raise SmokeFailure(f"{name} is missing; install it or use the corresponding CLI option")


def prepare(godot: Path) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "prepared.json").unlink(missing_ok=True)
    sources = source_fingerprint()
    build_env = {**os.environ, "CARGO_TARGET_DIR": str(ROOT / "rust/target")}
    commands = [
        (["cargo", "build", "--release", "-p", "omega-server"], ROOT / "rust"),
        ([str(ROOT / "scripts/build_client_ext.sh")], ROOT),
        (["go", "build", "-o", str(BUILD / "api"), "./cmd/server"], ROOT / "api"),
        (["go", "build", "-o", str(BUILD / "keygen"), "./cmd/gen_ticket_key"], ROOT / "api"),
        ([str(godot), "--headless", "--path", str(ROOT / "client"), "--editor", "--import", "--quit"], ROOT),
    ]
    for args, cwd in commands:
        print("[prepare] " + " ".join(args), flush=True)
        if args[0] == str(godot):
            result = subprocess.run(args, cwd=cwd, env=build_env, check=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            print(result.stdout, end="")
            if any(ERROR_LINE.search(line) for line in result.stdout.splitlines()):
                raise SmokeFailure("Godot import reported errors")
        else:
            subprocess.run(args, cwd=cwd, env=build_env, check=True)
    shutil.copy2(ROOT / "rust/target/release/omega-server", BUILD / "omega-server")
    version = subprocess.check_output([str(godot), "--version"]).decode().strip()
    if source_fingerprint() != sources:
        raise SmokeFailure("Sources changed during preparation; run --prepare again after edits finish")
    write_json(BUILD / "prepared.json", {"sources": sources, "godot_version": version})
    print("[prepare] Ready. Run ./scripts/smoke_local.py (20-second maximum).", flush=True)


def free_tcp_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def isolated_environment() -> dict[str, str]:
    # Never source deployment/deploy.env, api/.env, .env.test, or inherited service targets.
    prefixes = ("OMEGA_", "DB_", "REDIS_", "JWT_", "GAME_SERVER_", "PG")
    exact = {"PORT", "SERVER_API_TOKEN", "REGION_HEARTBEAT_TOKEN", "ALLOW_INSECURE_INTERNAL",
             "ALLOW_INSECURE_CMS", "LOAD_TEST_TICKET_SECRET", "GAME_CONTENT_DIR", "ENVIRONMENT"}
    return {key: value for key, value in os.environ.items()
            if not key.startswith(prefixes) and key not in exact}


class SmokeRun:
    def __init__(self, args: argparse.Namespace, godot: Path, postgres: Path, redis: Path, started: float):
        self.args, self.godot, self.postgres, self.redis = args, godot, postgres, redis
        logs = ROOT / "logs/local-smoke"
        logs.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=logs))
        self.processes: dict[str, subprocess.Popen] = {}
        self.log_handles = []
        self.user_dirs: list[Path] = []
        self.started = started
        # Reserve cleanup time inside the user's total budget.
        self.deadline = self.started + args.timeout - 1.5
        self.env = isolated_environment()
        self.command = self.directory / "command.txt"
        self.command.write_text("sanctuary")
        self.results: dict = {"result": "FAIL", "stages": {}}
        self.api_url = ""
        self.stage = "startup"

    def say(self, message: str) -> None:
        print(f"[{time.monotonic() - self.started:4.1f}s] {message}", flush=True)

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeFailure(f"Timed out during {self.stage} (total budget {self.args.timeout:g}s, including cleanup)")
        return remaining

    def launch(self, name: str, args: list[str], env: dict | None = None, cwd: Path | None = None) -> None:
        self.remaining()
        log = (self.directory / f"{name}.log").open("wb")
        self.log_handles.append(log)
        self.processes[name] = subprocess.Popen(
            [str(arg) for arg in args], cwd=cwd or self.directory, env=env or self.env,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )

    def errors(self) -> list[str]:
        errors, notices = [], []
        for path in self.directory.glob("*.log"):
            for line in path.read_text(errors="replace").splitlines():
                if path.name == "api.log" and line.endswith(REDIS_OPTIONAL_NOTICE):
                    notices.append("Redis optional maintenance notifications unavailable; go-redis used its supported fallback")
                elif ERROR_LINE.search(line):
                    errors.append(f"{path.name}: {line}")
        self.results["notices"] = sorted(set(notices))
        return errors

    def check_processes(self, clients_finished: bool = False) -> None:
        for name, process in self.processes.items():
            if clients_finished and name in ROLES:
                continue
            returncode = process.poll()
            if name == "initdb" and returncode == 0:
                continue  # Retain its group for cleanup even after setup completes.
            if returncode is not None:
                raise SmokeFailure(f"{name} exited unexpectedly ({process.returncode}); see {name}.log")

    def check(self) -> None:
        self.remaining()
        self.check_processes()
        errors = self.errors()
        if errors:
            raise SmokeFailure("\n".join(errors[:8]))

    def wait_for(self, predicate, label: str) -> object:
        self.stage = label
        while True:
            self.check()
            value = predicate()
            if value:
                return value
            time.sleep(min(0.05, self.remaining()))

    def request(self, route: str, data: dict | None = None, token: str = "") -> dict:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            self.api_url + route, headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
        )
        # Loopback traffic must not use a developer's HTTP proxy.
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                request, timeout=min(1.0, self.remaining())
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise SmokeFailure(f"{route} returned HTTP {exc.code}: {exc.read(1024).decode(errors='replace')}") from exc

    def health(self) -> bool:
        try:
            return self.request("/health").get("status") == "healthy"
        except (OSError, urllib.error.URLError):
            return False

    def status(self, role: str) -> dict:
        path = self.directory / f"{role}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def ready(self, phase: str) -> bool:
        return all((state := self.status(role)).get("phase") == phase and state.get("ready")
                   for role in ROLES)

    def create_project(self, role: str) -> Path:
        project = self.directory / f"project-{role}"
        project.mkdir()
        for source in (ROOT / "client").iterdir():
            if source.name not in {"project.godot", "override.cfg"}:
                (project / source.name).symlink_to(source, target_is_directory=source.is_dir())
        name = f"OmegaSmoke-{self.directory.name}-{role}"
        settings = (ROOT / "client/project.godot").read_text()
        settings = re.sub(r'^config/name=.*$', 'config/name=' + json.dumps(name), settings, flags=re.M)
        settings = re.sub(r'^config/(?:use_custom_user_dir|custom_user_dir_name)=.*\n', '', settings, flags=re.M)
        settings = settings.replace("[application]", "[application]\n\nconfig/use_custom_user_dir=false", 1)
        (project / "project.godot").write_text(settings)
        # A private user:// prevents reading/writing the player's saved tokens and preferences.
        data_root = (Path.home() / "Library/Application Support" if sys.platform == "darwin"
                     else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
        user_dir = data_root / ("Godot" if sys.platform == "darwin" else "godot") / "app_userdata" / name
        user_dir.mkdir(parents=True)
        self.user_dirs.append(user_dir)
        write_json(user_dir / "settings.json", {"window_mode": "windowed", "master_volume": 0.0})
        write_json(user_dir / "preferences.json", {"use_local_api": True})
        return project

    def run(self) -> None:
        # Reserve the actual portal ports. Refuse a running dev stack; never stop/reuse it.
        reservations = []
        try:
            for port in (8081, 8082):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                reservations.append(sock)
                sock.bind(("0.0.0.0", port))
        except OSError as exc:
            for sock in reservations:
                sock.close()
            raise SmokeFailure("UDP 8081/8082 is occupied; stop that stack before running the smoke") from exc
        try:
            self.start_services()
            for sock in reservations:
                sock.close()
            self.start_servers()
            accounts = self.create_accounts()
            for role in ROLES:
                config = {**accounts[role], "role": role, "api_url": self.api_url,
                          "peer_name": accounts["bot" if role == "client" else "client"]["character_name"],
                          "command_path": str(self.command), "status_path": str(self.directory / f"{role}.json")}
                config_path = self.directory / f"{role}-credentials.json"
                write_json(config_path, config)
                env = {**self.env, "OMEGA_SMOKE_CONFIG": str(config_path)}
                self.launch(role, [str(self.godot), "--path", str(self.create_project(role)),
                                   "--verbose", "--max-fps", "60", "--audio-driver", "Dummy", SCENE], env)
            self.say("Client + bot launched; waiting for signed auth, hydration and mutual replication")
            self.wait_for(lambda: self.ready("sanctuary"), "Sanctuary readiness")
            self.say("Both in Sanctuary; observing 3 seconds")
            until = time.monotonic() + 3.0
            self.wait_for(lambda: time.monotonic() >= until, "Sanctuary observation")
            if not self.ready("sanctuary"):
                raise SmokeFailure("Sanctuary lost replication during its observation window")
            self.results["stages"]["sanctuary"] = {role: self.status(role) for role in ROLES}
            self.command.write_text("arena")
            self.say("Activating both Arena portals")
            self.wait_for(lambda: self.ready("arena"), "Arena readiness")
            self.say("Both in Arena; observing up to 3 seconds for a monster interaction")
            until = time.monotonic() + 3.0
            self.wait_for(lambda: time.monotonic() >= until or any(
                self.status(role).get("monster_interactions", 0) > 0 for role in ROLES
            ), "Arena observation")
            if not self.ready("arena"):
                raise SmokeFailure("Arena lost replication during its observation window")
            states = {role: self.status(role) for role in ROLES}
            if not all(state["monsters"] > 0 and state["shots"] > 0 for state in states.values()):
                raise SmokeFailure("Arena must replicate monsters and server-confirmed shots for both players")
            self.results["stages"]["arena"] = states
            # Region liveness traverses Rust -> Go -> Redis -> HTTP readback.
            regions = self.request("/api/regions")["regions"]
            if not any(region["id"] == "local" for region in regions):
                raise SmokeFailure("Local region heartbeat is missing from Redis-backed /api/regions")
            self.results["region_heartbeat"] = True
            self.command.write_text("quit")
            for role in ROLES:
                self.processes[role].wait(timeout=self.remaining())
                if self.processes[role].returncode != 0:
                    raise SmokeFailure(f"{role} did not exit successfully")
            errors = self.errors()
            if errors:
                raise SmokeFailure("\n".join(errors[:8]))
            self.remaining()
            self.check_processes(clients_finished=True)
            self.results["result"] = "PASS"
        finally:
            for sock in reservations:
                sock.close()

    def start_services(self) -> None:
        self.say("Starting disposable PostgreSQL, Redis and API")
        pg_port, redis_port, api_port = (free_tcp_port() for _ in range(3))
        self.api_url = f"http://127.0.0.1:{api_port}"
        data = self.directory / "pgdata"
        self.launch("initdb", [str(self.postgres.parent / "initdb"), "-D", str(data), "-U", "omega_smoke",
                               "--auth=trust", "--no-locale", "--encoding=UTF8", "--no-sync"])
        if self.processes["initdb"].wait(timeout=self.remaining()) != 0:
            raise SmokeFailure("initdb failed; see initdb.log")
        self.launch("postgres", [str(self.postgres), "-D", str(data), "-h", "127.0.0.1",
                                 "-p", str(pg_port), "-k", "",
                                 "-c", "fsync=off", "-c", "log_min_messages=warning"])
        self.launch("redis", [str(self.redis), "--bind", "127.0.0.1", "--port", str(redis_port),
                              "--save", "", "--appendonly", "no", "--dir", str(self.directory)])
        def database_ready():
            if "database system is ready to accept connections" not in (self.directory / "postgres.log").read_text(errors="replace"):
                return False
            probe = subprocess.run([str(self.postgres.parent / "pg_isready"), "-h", "127.0.0.1",
                                    "-p", str(pg_port), "-U", "omega_smoke", "-d", "postgres"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=self.env, timeout=min(1.0, self.remaining()))
            try:
                with socket.create_connection(("127.0.0.1", redis_port), timeout=0.2) as conn:
                    conn.sendall(b"*1\r\n$4\r\nPING\r\n")
                    return probe.returncode == 0 and conn.recv(64).startswith(b"+PONG")
            except OSError:
                return False
        self.wait_for(database_ready, "Database startup")
        key_output = subprocess.check_output([str(BUILD / "keygen")], timeout=self.remaining()).decode()
        keys = dict(line.split("=", 1) for line in key_output.splitlines() if line.startswith("OMEGA_"))
        self.env.update(keys)
        self.env.update({
            "DB_HOST": "127.0.0.1", "DB_PORT": str(pg_port), "DB_USER": "omega_smoke",
            "DB_PASSWORD": "unused", "DB_NAME": "postgres", "DB_SSLMODE": "disable",
            "REDIS_HOST": "127.0.0.1", "REDIS_PORT": str(redis_port), "PORT": str(api_port),
            "JWT_SECRET_KEY": secrets.token_hex(32), "SERVER_API_TOKEN": secrets.token_hex(32),
            "REGION_HEARTBEAT_TOKEN": secrets.token_hex(32), "ENVIRONMENT": "test",
            "GAME_CONTENT_DIR": str(ROOT / "client/data"), "RUST_LOG": "info", "NO_COLOR": "1",
        })
        (self.directory / ".env").write_text("# Service configuration is passed through the environment.\n")
        self.launch("api", [str(BUILD / "api")])
        self.wait_for(self.health, "API startup")

    def start_servers(self) -> None:
        for mode, port in (("sanctuary", 8082), ("arena", 8081)):
            config = {
                "mode": mode, "port": port, "region": "local", "max_players": 4,
                "api_server_url": self.api_url, "advertise_url": f"127.0.0.1:{port}",
                "metrics_port": 0, "allow_unsigned_tickets": False,
                # A short smoke needs encounters promptly, without modifying game content.
                "monster_spawn_rate": 8.0, "aoi_radius": 8000.0, "aoi_exit_radius": 8100.0,
            }
            path = self.directory / f"{mode}.json"
            write_json(path, config)
            self.launch(mode, [str(BUILD / "omega-server"), "--config", str(path), "--require-tickets"])

    def create_accounts(self) -> dict:
        accounts = {}
        for role in ROLES:
            username = "smoke_" + role
            password = secrets.token_urlsafe(24)
            self.request("/api/auth/register", {"username": username, "email": username + "@example.test",
                                                "password": password, "region": "Asia"})
            auth = self.request("/api/auth/login", {"username": username, "password": password})
            token = auth["access_token"]
            character = self.request("/api/character/create", {
                "name": "SmokeClient" if role == "client" else "SmokeBot",
                "class": "Mage", "race": "Human", "realm": "Local", "mode": "softcore",
            }, token)["character"]
            accounts[role] = {"token": token, "user_id": auth["user"]["id"],
                              "character_id": character["id"], "character_name": character["name"]}
        return accounts

    def cleanup(self) -> None:
        # A filesystem/reporting failure must not prevent independent releases.
        errors: list[str] = []

        def attempt(label, release):
            try:
                release()
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        def signal_groups(group, signum):
            for name, process in group:
                try:
                    os.killpg(process.pid, signum)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    errors.append(f"signal {name}: {exc}")

        def alive_groups(group):
            alive = []
            for name, process in group:
                try:
                    process.poll()  # Reap leaders so their zombies don't keep a group alive.
                    os.killpg(process.pid, 0)
                    alive.append(name)
                except ProcessLookupError:
                    pass
                except OSError:
                    # macOS can transiently deny inspection during group teardown.
                    # Keep waiting; a group still present at the final check fails cleanup.
                    alive.append(name)
            return alive

        def wait_groups(group, limit):
            while alive_groups(group) and time.monotonic() < limit:
                time.sleep(0.01)

        def remove_directory(path):
            try:
                shutil.rmtree(path)
            except FileNotFoundError:
                pass

        attempt("quit command", lambda: self.command.write_text("quit"))
        # All children own their own group. Descendants remain owned after a leader exits.
        # Close consumers first so PostgreSQL can shut down without active API connections.
        for database_group in (False, True):
            group = [(name, process) for name, process in self.processes.items()
                     if (name in {"postgres", "redis"}) == database_group]
            for item in group:
                signal_groups([item], signal.SIGINT if item[0] == "postgres" else signal.SIGTERM)
            wait_groups(group, time.monotonic() + 0.25)
        all_groups = list(self.processes.items())
        signal_groups(all_groups, signal.SIGKILL)
        wait_groups(all_groups, time.monotonic() + 0.25)
        alive = alive_groups(all_groups)
        self.results["processes_stopped"] = not alive
        if alive:
            errors.append("process groups still present: " + ", ".join(alive))
        for handle in self.log_handles:
            attempt("close log", handle.close)
        for path in self.user_dirs + [self.directory / "pgdata"]:
            attempt(f"remove {path.name}", lambda path=path: remove_directory(path))
        # Include an interrupted atomic credential write's .tmp file too.
        for role in ROLES:
            for suffix in ("json", "tmp"):
                path = self.directory / f"{role}-credentials.{suffix}"
                attempt(f"remove {path.name}", lambda path=path: path.unlink(missing_ok=True))
        self.results["elapsed_seconds"] = round(time.monotonic() - self.started, 3)
        self.results["logs"] = str(self.directory)
        self.results["cleanup_errors"] = errors
        if errors:
            self.results["result"] = "FAIL"
        attempt("write result", lambda: write_json(self.directory / "result.json", self.results))
        if errors:
            self.results["result"] = "FAIL"
            for error in errors:
                print("[cleanup] " + error, file=sys.stderr, flush=True)


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="Build binaries/import assets; outside the smoke time budget")
    parser.add_argument("--timeout", type=float, default=20.0, help="Total runtime cap including cleanup, 3–20 seconds")
    parser.add_argument("--godot", help="Godot executable (default: godot on PATH)")
    parser.add_argument("--postgres", help="postgres executable; sibling initdb/pg_isready are used")
    parser.add_argument("--redis", help="redis-server executable (also discovers DBngin on macOS)")
    args = parser.parse_args()
    if not 3.0 <= args.timeout <= 20.0:
        parser.error("--timeout must be between 3 and 20 seconds")
    run = None
    try:
        godot = executable("godot", args.godot)
        if args.prepare:
            prepare(godot)
            return 0
        marker = BUILD / "prepared.json"
        if not marker.exists() or any(not (BUILD / name).is_file() for name in ("api", "keygen", "omega-server")):
            raise SmokeFailure("Run ./scripts/smoke_local.py --prepare first")
        prepared = json.loads(marker.read_text())
        if prepared.get("sources") != source_fingerprint():
            raise SmokeFailure("Sources changed since preparation; run ./scripts/smoke_local.py --prepare")
        version = subprocess.check_output([str(godot), "--version"], timeout=2).decode().strip()
        if prepared.get("godot_version") != version:
            raise SmokeFailure("Godot changed since preparation; run ./scripts/smoke_local.py --prepare")
        postgres = executable("postgres", args.postgres)
        redis = executable("redis-server", args.redis)
        run = SmokeRun(args, godot, postgres, redis, started)
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        run.run()
    except (SmokeFailure, OSError, subprocess.SubprocessError, ValueError, KeyboardInterrupt) as exc:
        reason = str(exc) or "Interrupted"
        print("[FAIL] " + reason, file=sys.stderr, flush=True)
        if run:
            run.results["error"] = reason
            run.results["last_status"] = {role: run.status(role) for role in ROLES}
        return 1
    finally:
        if run:
            # A second interrupt must not abort cleanup halfway through owned services.
            handlers = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                run.cleanup()
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
            run.say(f"{run.results['result']} — logs: {run.directory}")
    return 0 if run and run.results["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
