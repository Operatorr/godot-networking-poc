#!/usr/bin/env python3
"""The CAX11 + Mac mini hill-climb harness (issue #79; contract in the #78 resolution).

One repeatable command runs alternating trials and prints median and range, error count and work
done. Identity is proven on every trial: binary and config hashes, a config diff against the
unmodified loadtest config, and the effective socket buffer from the server's own log.

  climb.py check                                     read-only preflight, nothing started
  climb.py build REF                                 build omega-server at a git ref on the CAX11
  climb.py session --name S --bots N --trials 5 --arm control=df42e73b \\
                   --arm buffer=df42e73b:udp_receive_buffer_bytes=2097152
  climb.py report S [--reference ARM]                median/range/comparability for a session
  climb.py freeze                                    pin harness hashes; later sessions refuse drift

Evidence: loadtest-runs/cax11-climb/ (gitignored). One row per load run goes to the hill-climb
ledger. A hard stop refuses to start load run 101.
"""
import argparse
import atexit
import csv
import datetime as dt
import hashlib
import json
import os
import re
import resource
import shlex
import signal
import statistics
import subprocess as sp
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import analyze as an  # noqa: E402

HOST = "deploy@2.31.70.128"
SERVER_ADDR = "2.31.70.128:8081"
KEY = ROOT / "deployment/hetzner/ssh/omega_loadtest_ed25519"
BASE = ROOT / "loadtest-runs/cax11-climb"
SESSIONS = BASE / "sessions"
BOT_SOURCE = Path("/Users/opera/.t3/worktrees/godot-networking-poc/t3-66766b61/rust/target/release/omega-load-test")
BOT_SHA = "a8ff3501931949d681626f772c7d73d91ea78de8ae25af8979b9eeaab4f2db50"
BOT = BASE / "bin/omega-load-test-a8ff3501"
BASE_CONFIG = ROOT / "deployment/server_config.loadtest.json"
BASE_CONFIG_SHA = "631e90552c786a8ca34357b8db6825d4a9fdd3b323db2020f1797f5ff28e98f6"
LEDGER = ROOT / "docs/netcode/perf-notes/hill-climb/ledger.md"
BINS = BASE / "bins.tsv"
BUDGET = BASE / "budget.tsv"
FROZEN = BASE / "frozen.json"
RUN_BUDGET = 100
R_HOME = "/home/deploy/omega-climb"
R_REPO = "/home/deploy/omega-realm"
HARNESS_FILES = [HERE / "climb.py", HERE / "analyze.py", ROOT / "scripts/quick_stress/report.py",
                 ROOT / "scripts/quick_stress/sample_host.py", BASE_CONFIG]
THREADS, STAGGER_MS, SEED, DURATION_S = 2, 100, 1, 70
SMOKE_BOTS, SMOKE_DURATION_S = 3, 20
JOIN_S = 0.5  # measured about 0.42 s per join per shard over the 207 ms path
DEFAULT_RECEIVE_BYTES = 524288
# [s] keeps this from matching the remote shell's own command line: procps pkill -f spares only
# itself, so a literal path would kill the shell running the stop script before its final check.
SAMPLER_PATTERN = f"{R_HOME}/scripts/[s]ample_host.py"


def ssh_cmd():
    BASE.mkdir(parents=True, exist_ok=True)
    return ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
            "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/omega-climb-%C", "-o", "ControlPersist=4h",
            "-o", "ServerAliveInterval=30", HOST]


def remote(cmd, check=True, timeout=120):
    # One persistent connection: a fresh login runs the host's motd scripts, and
    # check-new-release takes most of a core for seconds. Never log in during a measurement.
    r = sp.run(ssh_cmd() + [cmd], text=True, capture_output=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"remote failed ({r.returncode}): {cmd[:200]}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def harness_hashes():
    return {str(p.relative_to(ROOT)): sha256(p) for p in HARNESS_FILES}


def ensure_bot():
    BOT.parent.mkdir(parents=True, exist_ok=True)
    if not BOT.exists():
        BOT.write_bytes(BOT_SOURCE.read_bytes())
        BOT.chmod(0o755)
    if sha256(BOT) != BOT_SHA:
        raise SystemExit(f"bot binary hash mismatch: {BOT}")


def bins():
    if not BINS.exists():
        return {}
    with open(BINS) as f:
        return {r[0][:8]: {"sha256": r[0], "commit": r[1], "ref": r[2]} for r in csv.reader(f, delimiter="\t")}


def resolve_bin(short):
    known = bins()
    if short not in known:
        raise SystemExit(f"unknown binary {short}; known: {sorted(known)}")
    return known[short]


def r_bin(info):
    return f"{R_HOME}/bin/{info['sha256'][:8]}/omega-server"


def add_bin(digest, commit, ref):
    if digest[:8] not in bins():
        with open(BINS, "a") as f:
            f.write(f"{digest}\t{commit}\t{ref}\n")


def setup_remote():
    remote(f"mkdir -p {R_HOME}/bin {R_HOME}/config {R_HOME}/scripts {R_HOME}/runs")
    sampler = ROOT / "scripts/quick_stress/sample_host.py"
    sp.run(ssh_cmd() + [f"cat > {R_HOME}/scripts/sample_host.py"], stdin=open(sampler, "rb"), check=True)
    frozen = "df42e73b8da7a59cd5fc513abfa97ab5e8795c9fb1100d36dfd67a07c040ea33"
    add_bin(frozen, "0c9ecafa70adf4fbf2fee101f55a41b8c2ff19b6", "frozen-control")
    remote(f"mkdir -p {R_HOME}/bin/{frozen[:8]}; test -x {R_HOME}/bin/{frozen[:8]}/omega-server || "
           f"cp {R_REPO}/rust/target/release/omega-server {R_HOME}/bin/{frozen[:8]}/omega-server")
    got = remote(f"sha256sum {R_HOME}/bin/{frozen[:8]}/omega-server").split()[0]
    if got != frozen:
        raise SystemExit(f"frozen server binary hash mismatch: {got}")


def build_script(repo=R_REPO, cargo="~/.cargo/bin/cargo", log=f"{R_HOME}/build.log"):
    """One release build that exits with cargo's status. Piped straight into tail it would exit with
    tail's, and a failed build would then hash and register the older binary still in target/."""
    return (f"cd {repo} || exit; {cargo} build --manifest-path rust/Cargo.toml --locked --release "
            f"-p omega-server > {log} 2>&1; status=$?; tail -3 {log}; exit $status")


def cmd_build(args):
    setup_remote()
    commit = sp.check_output(["git", "rev-parse", args.ref], cwd=ROOT, text=True).strip()
    print(f"build {args.ref} = {commit}", flush=True)
    # Buffered whole: a failed archive stops here, before anything reaches the CAX11.
    archive = sp.check_output(["git", "archive", commit, "rust", "deployment", "scripts"], cwd=ROOT)
    # -m: fresh mtimes. git archive stamps the commit time, and an older stamp would let cargo
    # keep a stale binary when moving back to an earlier commit.
    sp.run(ssh_cmd() + [f"tar -xm -C {R_REPO}"], input=archive, check=True)
    print(remote(build_script(), timeout=1500), flush=True)
    digest = remote(f"sha256sum {R_REPO}/rust/target/release/omega-server").split()[0]
    remote(f"mkdir -p {R_HOME}/bin/{digest[:8]} && cp {R_REPO}/rust/target/release/omega-server "
           f"{R_HOME}/bin/{digest[:8]}/omega-server")
    add_bin(digest, commit, args.ref)
    print(f"binary {digest[:8]} {digest} from {commit}")


def preflight(info, config_remote, config_sha, wait_quiet=True):
    """Read-only. Returns the evidence dict or exits."""
    ensure_bot()
    deadline = time.time() + 180
    while True:
        out = remote(rf"""sha256sum {r_bin(info)} {config_remote} | cut -d' ' -f1
sysctl -n net.core.rmem_max
pgrep -x omega-server | wc -l
ss -H -lun 'sport = :8081' | wc -l
a=$(head -1 /proc/stat); sleep 2; b=$(head -1 /proc/stat)
python3 -c "
a=[int(x) for x in '$a'.split()[1:]];b=[int(x) for x in '$b'.split()[1:]]
d=[y-x for x,y in zip(a,b)];print(round(100*(1-(d[3]+d[4])/sum(d)),1))"
ps -eo pcpu,comm --sort=-pcpu | sed -n 2,4p | tr '\n' ';'
""")
        lines = out.splitlines()
        busy = float(lines[5])
        if not wait_quiet or busy < 15.0:
            break
        if time.time() > deadline:
            raise SystemExit(f"host not quiet after 180 s: busy {busy}%, top {lines[6]}")
        time.sleep(5)
    evidence = {"server_sha256": lines[0], "config_sha256": lines[1], "rmem_max": int(lines[2]),
                "omega_server_processes": int(lines[3]), "udp_8081_listeners": int(lines[4]),
                "host_busy_pct": busy, "host_top": lines[6], "bot_sha256": sha256(BOT)}
    if lines[0] != info["sha256"]:
        raise SystemExit(f"server hash mismatch: {lines[0]} != {info['sha256']}")
    if lines[1] != config_sha:
        raise SystemExit(f"config hash mismatch: {lines[1]} != {config_sha}")
    if int(lines[3]) or int(lines[4]):
        raise SystemExit(f"competing server present: {evidence}")
    ping = sp.run(["ping", "-c", "5", "-i", "0.2", SERVER_ADDR.split(":")[0]], text=True, capture_output=True).stdout
    m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", ping)
    evidence["idle_ping_ms"] = {"min": float(m[1]), "mean": float(m[2]), "max": float(m[3])} if m else None
    received = re.search(r"(\d+) packets received", ping)
    evidence["idle_ping_replies"] = int(received[1]) if received else 0
    return evidence


def arm_config(levers):
    """The unmodified loadtest config plus only the lever under test."""
    if sha256(BASE_CONFIG) != BASE_CONFIG_SHA:
        raise SystemExit("deployment/server_config.loadtest.json changed; it is frozen")
    if not levers:
        return BASE_CONFIG.read_bytes()
    data = json.loads(BASE_CONFIG.read_text())
    data.update(levers)
    return (json.dumps(data, indent=2) + "\n").encode()


def push_config(blob):
    digest = hashlib.sha256(blob).hexdigest()
    path = f"{R_HOME}/config/{digest[:12]}.json"
    sp.run(ssh_cmd() + [f"cat > {path}"], input=blob, check=True)
    return path, digest


def config_diff(blob):
    base, arm = json.loads(BASE_CONFIG.read_text()), json.loads(blob)
    return {k: {"base": base.get(k), "arm": arm.get(k)} for k in sorted(set(base) | set(arm)) if base.get(k) != arm.get(k)}


def refuse_used_trial(trial):
    if trial.exists():
        raise SystemExit(f"{trial} holds an earlier attempt with no result; move it aside to retry")


def sample_threads(pid):
    """One `ps -M` sample, or None. Optional evidence: the process can exit between the caller's
    poll and this call, and ps then exits 1, which is a normal end of the run."""
    try:
        r = sp.run(["ps", "-M", "-p", str(pid), "-o", "pid,time,pcpu"], text=True, capture_output=True)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def stop_remote():
    """Stop the server, then the host sampler. Raises if either cannot be confirmed."""
    left = remote(f"pkill -INT -x omega-server || true; sleep 2; "
                  f"for i in $(seq 1 40); do pgrep -x omega-server > /dev/null || break; sleep 0.2; done; "
                  f"pkill -f {shlex.quote(SAMPLER_PATTERN)} || true; pgrep -x omega-server || true").strip()
    if left:
        raise SystemExit(f"omega-server still running after stop: {left}")


def collect_remote(trial, rdir):
    with open(trial / "remote.tar", "wb") as f:
        sp.run(ssh_cmd() + [f"tar -C {shlex.quote(rdir)} -cf - ."], stdout=f, check=True)
    sp.run(["tar", "-xf", str(trial / "remote.tar"), "-C", str(trial)], check=True)
    (trial / "remote.tar").unlink()


def run_cleanup(steps):
    """Run every step even if an earlier one fails, and return the failures: a cleanup problem may
    neither skip the steps after it nor replace the error that started the cleanup."""
    errors = []
    for label, step in steps:
        try:
            step()
        except (Exception, SystemExit) as exc:
            errors.append(f"{label}: {exc}")
    return errors


def run_trial(trial, name, info, levers, bots, duration, count=True):
    """One bounded run. Once the first remote launch is attempted, always stops the remote server
    and collects evidence, and any startup or run error stays the error the caller sees."""
    blob = arm_config(levers)
    cfg_remote, cfg_sha = push_config(blob)
    pre = preflight(info, cfg_remote, cfg_sha)
    trial.mkdir(parents=True, exist_ok=False)
    (trial / "bots").mkdir()
    expected = 2 * levers["udp_receive_buffer_bytes"] if "udp_receive_buffer_bytes" in levers else DEFAULT_RECEIVE_BYTES
    (trial / "preflight.json").write_text(json.dumps(pre, indent=2))
    (trial / "config.json").write_bytes(blob)
    (trial / "config-diff.json").write_text(json.dumps(config_diff(blob), indent=2))
    bot_guard = int(bots / THREADS * JOIN_S) + duration + 60
    server_guard = bot_guard + 30
    rdir = f"{R_HOME}/runs/{trial.parent.name}/{trial.name}"
    q = shlex.quote
    cmd = [str(BOT), "--scenario", "quick", "--bots", str(bots), "--threads", str(THREADS), "--stagger",
           str(STAGGER_MS), "--seed", str(SEED), "--duration", str(duration), "--server", SERVER_ADDR,
           "-o", str(trial / "bots/report.json")]
    swarm = failure = None
    start = time.time()

    def stop_swarm():
        if swarm is not None and swarm.poll() is None:
            swarm.kill()
            swarm.wait()

    def write_manifest(errors):
        manifest = {"name": name, "command": cmd, "start": start, "end": time.time(),
                    "exit": swarm.returncode if swarm is not None else None,
                    "server_sha256": info["sha256"], "commit": info["commit"], "levers": levers,
                    "harness": harness_hashes()}
        if failure is not None:
            manifest["error"] = str(failure) or repr(failure)
        if errors:
            manifest["cleanup_errors"] = errors
        (trial / "run.json").write_text(json.dumps(manifest, indent=2))

    try:
        print(remote(f"""set -e; mkdir -p {q(rdir)}/server; cd {R_REPO}
nohup timeout -s INT -k 5 {server_guard} env OMEGA_MEASURE_DIR={q(rdir)}/server RUST_LOG=info {r_bin(info)} --config {cfg_remote} --allow-unsigned-tickets > {q(rdir)}/server.log 2>&1 < /dev/null &
for i in $(seq 1 50); do grep -q 'listening on udp' {q(rdir)}/server.log 2>/dev/null && break; sleep 0.2; done
pgrep -x omega-server > {q(rdir)}/server.pid; sed 's/^/server=/' {q(rdir)}/server.pid > {q(rdir)}/pids.txt
nohup timeout {server_guard + 3} python3 {R_HOME}/scripts/sample_host.py --out {q(rdir)}/host.ndjson --pids {q(rdir)}/pids.txt --udp-port 8081 > {q(rdir)}/sampler.log 2>&1 < /dev/null &
echo $! > {q(rdir)}/sampler.pid
sleep 1; grep -a -o 'effective_receive_bytes[^ ]*' {q(rdir)}/server.log | head -1
"""), end="", flush=True)
        start = time.time()  # the bot guard runs from a live server, not from the launch attempt
        log_text = re.sub(r"\x1b\[[0-9;]*m", "", remote(f"cat {q(rdir)}/server.log"))
        m = re.search(r"effective_receive_bytes=(\d+)", log_text)
        if not m or int(m[1]) != expected:
            raise SystemExit(f"effective receive buffer {m and m[1]} != expected {expected}")
        (trial / "udp-before.txt").write_text(sp.check_output(["netstat", "-s", "-p", "udp"], text=True))
        (trial / "interfaces-before.txt").write_text(sp.check_output(["netstat", "-ibn"], text=True))
        fds = max(bots + 512, 4096)

        def raise_fds():
            hard = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(fds, hard), hard))
        swarm = sp.Popen(cmd, stdout=open(trial / "bots.log", "w"), stderr=sp.STDOUT, preexec_fn=raise_fds)
        (trial / "pids.txt").write_text(f"bots={swarm.pid}\n")
        sampler = sp.Popen([sys.executable, str(ROOT / "scripts/quick_stress/sample_host.py"), "--out",
                            str(trial / "mac-host.ndjson"), "--pids", str(trial / "pids.txt")])
        try:
            with open(trial / "mac-threads.ndjson", "w") as f:
                while swarm.poll() is None:
                    ps = sample_threads(swarm.pid)
                    if ps is not None:
                        f.write(json.dumps({"ts": time.time(), "ps": ps}) + "\n")
                        f.flush()
                    if time.time() - start > bot_guard:
                        swarm.send_signal(signal.SIGINT)
                        try:
                            swarm.wait(timeout=10)
                        except sp.TimeoutExpired:
                            swarm.kill()
                        break
                    time.sleep(1)
        finally:
            sampler.terminate()
            sampler.wait()
        (trial / "udp-after.txt").write_text(sp.check_output(["netstat", "-s", "-p", "udp"], text=True))
        (trial / "interfaces-after.txt").write_text(sp.check_output(["netstat", "-ibn"], text=True))
    except BaseException as exc:
        failure = exc
        raise
    finally:
        errors = run_cleanup([("stop bots", stop_swarm), ("stop server", stop_remote),
                              ("collect evidence", lambda: collect_remote(trial, rdir))])
        errors += run_cleanup([("write run.json", lambda: write_manifest(list(errors)))])
        for error in errors:
            print(f"trial cleanup failed: {error}", file=sys.stderr, flush=True)
    if errors:
        raise SystemExit(f"trial cleanup failed, evidence in {trial} may be incomplete: " + "; ".join(errors))
    if swarm.returncode not in (0, 1, 2):
        raise SystemExit(f"bot process exit {swarm.returncode}; see {trial}")
    return swarm.returncode


def load_runs_used():
    if not BUDGET.exists():
        return 0
    return sum(1 for _ in open(BUDGET))


def count_load_run(session, trial, arm, bots, info):
    with open(BUDGET, "a") as f:
        f.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()}\t{session}\t{trial}\t{arm}\t{bots}\t{info['sha256'][:8]}\n")


def ledger_row(session, trial_name, arm, info, s):
    b = s["bots_report"]
    srv = s.get("server", {})
    enet = srv.get("enet") or {}
    tick = s.get("tick_ms") or {}
    passed = all(s["gates"].values())
    drops = s.get("drops") or {}
    workers = (s.get("mac", {}).get("workers") or {})
    snap = srv.get("phase_ms_per_tick", {}).get("snapshot_build")
    fmt = lambda v, nd=2: "n/a" if v is None else f"{v:.{nd}f}"  # noqa: E731
    note = (f"CAX11 climb `{session}` {arm}; {s['gates_passed']}/6 gates; ramp/min/tail drops "
            f"{drops.get('ramp')}/{drops.get('minute')}/{drops.get('tail')}; offered {fmt(s.get('offered_datagrams_per_s'), 0)} dg/s; "
            f"snapshot {fmt(snap)} ms; deferred p95 {(s.get('deferred') or {}).get('p95')}; wait max "
            f"{(s.get('deferred_wait_ticks') or {}).get('max')}; excess RTT {fmt(s.get('excess_rtt_ms'), 1)}")
    return (f"| {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} | {session}/{trial_name} | `{info['commit'][:7]}` | {s['bots']} strategy | "
            f"{'PASS' if passed else 'FAIL'} | {b.get('connected_bots')}/{s['bots']}, {s['window_ticks']} Ticks | "
            f"{fmt(tick.get('p95'))} / {fmt(tick.get('max'))} | {fmt(s.get('ticks_over_pct'), 3)}% | {fmt(srv.get('cpu_core_pct'), 1)}% | "
            f"top-2 mean {fmt(workers.get('mean_top2_pct'), 1)}% | {drops.get('whole')} whole run | {fmt(b.get('latency_p95_ms'), 0)} | "
            f"{fmt(b.get('packet_loss_pct'))}% | {fmt(b.get('bandwidth_per_player_kbps'))} | unavailable | "
            f"{fmt(enet.get('loss_mean_pct_max'), 3)}% / {fmt(enet.get('rtt_max_ms_max'), 0)} | {note} |\n")


def parse_arm(text):
    name, _, spec = text.partition("=")
    short, _, lever_text = spec.partition(":")
    levers = {}
    for item in filter(None, lever_text.split(",")):
        key, _, value = item.partition("=")
        levers[key] = json.loads(value)
    return name, short, levers


def cmd_session(args):
    if FROZEN.exists():
        frozen = json.loads(FROZEN.read_text())["harness"]
        if frozen != harness_hashes():
            raise SystemExit("harness changed since `freeze`: refusing to measure")
    setup_remote()
    session = SESSIONS / args.name
    session.mkdir(parents=True, exist_ok=True)
    arms = [parse_arm(a) for a in args.arm]
    infos = {name: resolve_bin(short) for name, short, _ in arms}
    meta = {"name": args.name, "bots": args.bots, "duration": args.duration, "trials": args.trials,
            "arms": {n: {"bin": s, "levers": l, "commit": infos[n]["commit"]} for n, s, l in arms}, "note": args.note}
    (session / "session.json").write_text(json.dumps(meta, indent=2))
    caffeine = sp.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    atexit.register(caffeine.terminate)
    smoke = {}
    if args.smoke:
        for name, short, levers in arms:
            sdir = session / f"smoke-{name}"
            if not (sdir / "bots/report.json").exists():
                refuse_used_trial(sdir)
                run_trial(sdir, f"{args.name}-smoke-{name}", infos[name], levers, SMOKE_BOTS, SMOKE_DURATION_S)
            r = json.loads((sdir / "bots/report.json").read_text())["aggregated"]
            ok = r.get("connected_bots") == SMOKE_BOTS and not r.get("total_errors")
            if not ok:
                raise SystemExit(f"smoke failed for arm {name}: {r}")
            smoke[name] = r["latency_p95_ms"]
            print(f"smoke {name}: 3/3 connected, ENet RTT p95 {smoke[name]} ms", flush=True)
            time.sleep(args.cooldown)
    for index in range(1, args.trials + 1):
        for name, short, levers in arms:
            trial = session / f"{index:02d}-{name}"
            if (trial / "summary.json").exists():
                continue
            refuse_used_trial(trial)  # before the count: a refused retry starts no load run
            if load_runs_used() >= RUN_BUDGET:
                raise SystemExit(f"run budget of {RUN_BUDGET} exhausted")
            count_load_run(args.name, trial.name, name, args.bots, infos[name])
            print(f"== {args.name} {trial.name}: {args.bots} bots, binary {short}, levers {levers or 'none'}"
                  f" (load run {load_runs_used()}/{RUN_BUDGET})", flush=True)
            code = run_trial(trial, args.name, infos[name], levers, args.bots, args.duration)
            s = an.analyze(trial, args.bots, smoke.get(name))
            s["bot_exit"] = code
            (trial / "summary.json").write_text(json.dumps(s, indent=2))
            with open(LEDGER, "a") as f:
                f.write(ledger_row(args.name, trial.name, name, infos[name], s))
            tick = s.get("tick_ms") or {}
            print(f"   p95 {tick.get('p95')} over {s.get('ticks_over')} drops {s.get('drops')} gates {s['gates_passed']}/6"
                  f" errors {s['error_count']} window {s['window_ticks']} excess {s.get('excess_rtt_ms')}", flush=True)
            time.sleep(args.cooldown)
    report_session(args.name, None)


def med_range(values, nd=2):
    v = [x for x in values if x is not None]
    if not v:
        return "n/a"
    return f"{statistics.median(v):.{nd}f} [{min(v):.{nd}f}..{max(v):.{nd}f}]"


def report_session(name, reference):
    session = SESSIONS / name
    meta = json.loads((session / "session.json").read_text())
    trials = {}
    for d in sorted(session.iterdir()):
        if (d / "summary.json").exists():
            arm = d.name.split("-", 1)[1]
            trials.setdefault(arm, []).append(json.loads((d / "summary.json").read_text()))
    lines = [f"# {name}: {meta['bots']} bots × {meta['duration']} s ({meta.get('note') or 'no note'})", ""]
    get = lambda s, *path: _dig(s, path)  # noqa: E731
    rows = [
        ("Tick work p95 ms (METRIC)", ("tick_ms", "p95"), 2), ("Tick work mean ms", ("tick_ms", "mean"), 2),
        ("Tick work max ms", ("tick_ms", "max"), 1), ("Ticks over 33.3 ms %", ("ticks_over_pct",), 3),
        ("Socket drops whole run", ("drops", "whole"), 0), ("  ramp", ("drops", "ramp"), 0),
        ("  minute", ("drops", "minute"), 0), ("  tail", ("drops", "tail"), 0),
        ("SndbufErrors whole run", ("sndbuf_errors", "whole"), 0), ("rx queue max B", ("socket", "rx_queue_max"), 0),
        ("Snapshot build ms/Tick", ("server", "phase_ms_per_tick", "snapshot_build"), 2),
        ("Service+route ms/Tick", ("server", "phase_ms_per_tick", "service_and_route"), 2),
        ("Outbox flush ms/Tick", ("server", "phase_ms_per_tick", "outbox_flush"), 2),
        ("ENet flush ms/Tick", ("server", "phase_ms_per_tick", "enet_flush"), 2),
        ("Server CPU % core", ("server", "cpu_core_pct"), 1), ("Offered datagrams/s", ("offered_datagrams_per_s",), 0),
        ("Host steal %", ("host", "steal_pct"), 2), ("Host busy %", ("host", "busy_pct"), 1),
        ("Read gaps >33 ms", ("server", "transport", "read_gaps_over_33ms"), 0),
        ("Read gap max ms", ("server", "transport", "read_gap_max_ms"), 1),
        ("Deferred records p95/Tick", ("deferred", "p95"), 0), ("Deferred records mean/Tick", ("deferred", "mean"), 0),
        ("Deferred wait max Ticks", ("deferred_wait_ticks", "max"), 0), ("Deferred wait p95 Ticks", ("deferred_wait_ticks", "p95"), 0),
        ("Bot RTT p95 ms (incl. ramp)", ("bots_report", "latency_p95_ms"), 0), ("Excess RTT ms", ("excess_rtt_ms",), 1),
        ("5 s bot RTT p95 max", ("bot_samples", "rtt_p95_max"), 0), ("Server worst-peer RTT max", ("server", "enet", "rtt_max_ms_max"), 0),
        ("Bot loss %", ("bots_report", "packet_loss_pct"), 2), ("Server peer loss max %", ("server", "enet", "loss_max_pct_max"), 2),
        ("Mac worker peak %", ("mac", "workers", "peak_sampled_pct"), 1), ("Mac worker mean %", ("mac", "workers", "mean_top2_pct"), 1),
        ("Mac UDP full-buffer delta", ("mac", "udp_full_buffer_delta"), 0),
        ("WORK: Ticks at full population", ("longest_full_population_ticks",), 0), ("WORK: datagrams in minute", ("datagrams_in_minute",), 0),
        ("ERRORS", ("error_count",), 0), ("Gates passed /6", ("gates_passed",), 0),
    ]
    arms = list(trials)
    lines.append("| measure (median [min..max]) | " + " | ".join(f"{a} (n={len(trials[a])})" for a in arms) + " |")
    lines.append("|---|" + "---|" * len(arms))
    for label, path, nd in rows:
        cells = [med_range([get(s, *path) for s in trials[a]], nd) for a in arms]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines.append("")
    for a in arms:
        ok = sum(1 for s in trials[a] if s["gates"]["socket_drops"])
        allbut = sum(1 for s in trials[a] if s["all_but_rtt"])
        lines.append(f"- **{a}**: zero-drop runs {ok}/{len(trials[a])}; all gates but absolute RTT {allbut}/{len(trials[a])}; "
                     f"p95 values {[round(get(s, 'tick_ms', 'p95') or 0, 2) for s in trials[a]]}")
    if reference and reference in trials:
        base = trials[reference]
        def med(ts, *path):
            v = [get(s, *path) for s in ts]
            v = [x for x in v if x is not None]
            return statistics.median(v) if v else None
        for a in arms:
            if a == reference:
                continue
            checks = []
            for label, path, levers_only in (("offered datagrams/s", ("offered_datagrams_per_s",), False),
                                             ("Snapshot build", ("server", "phase_ms_per_tick", "snapshot_build"), True)):
                x, y = med(trials[a], *path), med(base, *path)
                if x is None or not y:
                    continue
                d = 100 * (x - y) / y
                checks.append(f"{label} {d:+.1f}% ({'within' if abs(d) <= 10 else 'OUTSIDE'} 10%{', config levers only' if levers_only else ''})")
            peak = max((get(s, "mac", "workers", "peak_sampled_pct") or 0) for s in trials[a] + base)
            checks.append(f"Mac worker peak {peak:.1f}% ({'below' if peak < 85 else 'AT OR ABOVE'} 85%)")
            lines.append(f"- comparability {a} vs {reference}: " + "; ".join(checks))
    text = "\n".join(lines) + "\n"
    (session / "REPORT.md").write_text(text)
    print(text)


def _dig(data, path):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def cmd_report(args):
    report_session(args.session, args.reference)


def cmd_check(_args):
    setup_remote()
    info = resolve_bin("df42e73b")
    path, digest = push_config(arm_config({}))
    print(json.dumps(preflight(info, path, digest), indent=2))
    print(f"load runs used {load_runs_used()}/{RUN_BUDGET}; harness {'frozen' if FROZEN.exists() else 'NOT frozen'}")


def cmd_freeze(_args):
    FROZEN.write_text(json.dumps({"at": dt.datetime.now(dt.timezone.utc).isoformat(), "harness": harness_hashes()}, indent=2))
    print(FROZEN.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("freeze").set_defaults(fn=cmd_freeze)
    p = sub.add_parser("build")
    p.add_argument("ref")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("session")
    p.add_argument("--name", required=True)
    p.add_argument("--bots", type=int, required=True)
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--duration", type=int, default=DURATION_S)
    p.add_argument("--arm", action="append", required=True)
    p.add_argument("--cooldown", type=int, default=15)
    p.add_argument("--note", default="")
    p.add_argument("--no-smoke", dest="smoke", action="store_false")
    p.set_defaults(fn=cmd_session)
    p = sub.add_parser("report")
    p.add_argument("session")
    p.add_argument("--reference")
    p.set_defaults(fn=cmd_report)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
