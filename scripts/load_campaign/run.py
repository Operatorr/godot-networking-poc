#!/usr/bin/env python3
"""Operator-side campaign controller. Access stays in the ignored handoff file."""
import argparse
import datetime
import json
import pathlib
import shlex
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
ACCESS = json.loads((ROOT / "deployment/hetzner/access.local.json").read_text())
HOSTS = {host["role"]: host for host in ACCESS["servers"]}
KEY = ROOT / "deployment/hetzner/ssh/omega_loadtest_ed25519"
RAW = ROOT / "deployment/hetzner/results/campaign-20261013"
REMOTE = "/home/deploy/omega-results/campaign-20261013"


def ssh(role, command, check=True):
    host = HOSTS[role]
    result = subprocess.run(["ssh", "-i", str(KEY), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                             host["ssh_user"] + "@" + host["ipv4"], command], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(role + ": " + result.stderr)
    return result.stdout


def copy(role, source, destination, download=False):
    host = HOSTS[role]
    address = host["ssh_user"] + "@" + host["ipv4"] + ":"
    subprocess.run(["scp", "-q", "-i", str(KEY), "-o", "BatchMode=yes",
                    address + source if download else str(source),
                    str(destination) if download else address + destination], check=True)


def install():
    RAW.mkdir(parents=True, exist_ok=True)
    for role in HOSTS:
        ssh(role, f"mkdir -p {REMOTE}/original; cp -n /home/deploy/omega-realm/rust/target/release/omega-{'server' if role == 'game' else 'load-test'} {REMOTE}/original/; "
                  f"uname -a; lscpu; cat /etc/os-release; uptime; timedatectl; chronyc tracking; "
                  "cd /home/deploy/omega-realm && git rev-parse HEAD && git status --short; "
                  "source /home/deploy/.cargo/env && rustc -Vv && cargo -V; "
                  "sudo -n ufw status verbose; tc -s -j qdisc show; ethtool -k eth0; "
                  "cat /proc/sys/net/core/rmem_max; ulimit -n", check=False)
        provenance = ssh(role, f"sha256sum {REMOTE}/original/*; uname -a; lscpu; timedatectl; chronyc tracking; "
                         "cd /home/deploy/omega-realm && git rev-parse HEAD && git status --short; "
                         "source /home/deploy/.cargo/env && rustc -Vv; tc -s -j qdisc show; ethtool -k eth0", check=False)
        (RAW / (role + "-original-provenance.txt")).write_text(provenance)
        copy(role, ROOT / "scripts/load_campaign/host_collect.py", REMOTE + "/host_collect.py")
        copy(role, ROOT / "scripts/load_campaign/capture.py", REMOTE + "/capture.py")
        copy(role, ROOT / "scripts/load_campaign/flow_record.rs", REMOTE + "/flow_record.rs")
        ssh(role, f"source /home/deploy/.cargo/env && rustc --edition=2021 -O {REMOTE}/flow_record.rs -o {REMOTE}/flow-record")
    config = ssh("game", "cat /etc/omega-loadtest/arena.json; systemctl cat omega-loadtest-arena.service")
    (RAW / "original-config-service.txt").write_text(config)
    ssh("game", f"cp -n /etc/omega-loadtest/arena.json {REMOTE}/original/arena.json")


def run(run_id, bots, behavior, duration=360, collection=True, build="original", variant="native"):
    local = RAW / run_id
    if local.exists():
        raise RuntimeError("Refusing to overwrite evidence: " + run_id)
    local.mkdir(parents=True)
    manifest = {"run_id": run_id, "requested_bots": bots, "behavior": behavior, "duration": duration,
                "excluded_warmup": 60, "collection": collection, "build": build, "variant": variant,
                "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "stagger_ms": 100,
                "input_hz": 30, "seed": 30, "difficulty": 1.0, "bandwidth_budget": 0}
    unit = "omega-campaign-" + run_id
    roles = []
    try:
        if build != "original":
            ssh("game", "sudo -n rm -f /var/lib/omega-measure/current/window.json")
        ssh("game", "sudo -n systemctl restart omega-loadtest-arena.service")
        time.sleep(2)
        for role in HOSTS:
            directory = REMOTE + "/" + run_id + "/" + role
            ssh(role, f"mkdir -p {directory}; date -u --iso-8601=ns; tc -s -j qdisc show dev eth0 > {directory}/qdisc-before.json")
            if collection:
                nft = 'table inet omega_measure { chain input { type filter hook input priority -150; policy accept; udp sport 8081 counter comment "game_in"; udp dport 8081 counter comment "bot_in"; }; chain output { type filter hook output priority -150; policy accept; udp sport 8081 counter comment "game_out"; udp dport 8081 counter comment "bot_out"; }; }'
                ssh(role, "sudo -n nft delete table inet omega_measure 2>/dev/null || true")
                ssh(role, "printf '%s' " + shlex.quote(nft) + " | sudo -n nft -f -")
                capture = f"exec python3 {REMOTE}/capture.py {directory}"
                ssh(role, f"sudo -n systemd-run --quiet --property=KillMode=mixed --unit={unit}-{role}-capture /bin/bash -c " + shlex.quote(capture))
            collector = f"python3 {REMOTE}/host_collect.py --role {role} --directory {directory} --seconds {duration + bots * 16 + 120}" + (" --light" if not collection else "")
            ssh(role, f"sudo -n systemd-run --quiet --unit={unit}-{role}-collect --uid=deploy /bin/bash -c " + shlex.quote(collector))
            roles.append(role)
        game_directory = REMOTE + "/" + run_id + "/game"
        (local / "boot.log").write_text(ssh("game", "journalctl -u omega-loadtest-arena.service -n 20 --no-pager -o short-iso-precise"))
        directory = REMOTE + "/" + run_id + "/bots"
        binary = REMOTE + "/original/omega-load-test" if build == "original" else "/home/deploy/omega-realm/rust/target/release/omega-load-test"
        args = [binary, "--server", HOSTS["game"]["ipv4"] + ":8081", "--bots", str(bots), "--behavior", behavior,
                "--duration", str(duration), "--input-hz", "30", "--seed", "30", "--stagger", "100", "--difficulty", "1.0",
                "--bandwidth-budget", "0", "--assertions", "strict", "--aoi-exit-radius", "660" if variant == "aoi600" else "1100",
                "--output", directory + "/bot.json"]
        command = "env -u OMEGA_TICKET_API -u OMEGA_LOAD_TEST_SECRET "
        if build != "original":
            command += f"OMEGA_MEASURE_DIR={directory} "
        command += shlex.join(args)
        manifest["command"] = command
        (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
        shell = f"ulimit -n 8192; {command} >{directory}/bot.log 2>&1; result=$?; echo $result >{directory}/exit-code; exit $result"
        ssh("bots", f"sudo -n systemd-run --quiet --unit={unit}-swarm --uid=deploy /bin/bash -c " + shlex.quote(shell))
        print(run_id + ": ramp started", flush=True)
        started = time.monotonic()
        phase = None
        while time.monotonic() - started < duration + bots * 16 + 120:
            status = ssh("bots", f"tail -5 {directory}/bot.log; cat {directory}/phase.json 2>/dev/null; test -f {directory}/exit-code && echo FINISHED", check=False)
            if phase is None:
                if build != "original":
                    for line in status.splitlines():
                        if line.startswith('{"phase2_utc_ns"'):
                            phase = json.loads(line)["phase2_utc_ns"]
                elif "Phase 2:" in status:
                    import re
                    stamp = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+Z).*Phase 2:", status)
                    if stamp:
                        phase = int(datetime.datetime.fromisoformat(stamp[1]).timestamp() * 1e9)
                if phase is not None:
                    window = {"start": phase + 60_000_000_000, "end": phase + duration * 1_000_000_000}
                    (local / "window.json").write_text(json.dumps(window))
                    for role in HOSTS:
                        copy(role, local / "window.json", REMOTE + "/" + run_id + "/" + role + "/window.json")
                    if build != "original":
                        ssh("game", f"cp {game_directory}/window.json /var/lib/omega-measure/current/window.json")
                    print(run_id + ": Phase 2; window scheduled", flush=True)
            if "FINISHED" in status:
                print(run_id + ": finished", flush=True)
                break
            time.sleep(2)
        else:
            raise RuntimeError("swarm timeout")
    except Exception as error:
        (local / "controller-error.txt").write_text(repr(error))
        raise
    finally:
        if build != "original":
            ssh("game", f"cp /var/lib/omega-measure/current/ticks.csv /var/lib/omega-measure/current/server.ndjson {game_directory}/", check=False)
        for role in HOSTS:
            ssh(role, f"sudo -n systemctl stop {unit}-swarm {unit}-{role}-collect {unit}-{role}-capture 2>/dev/null || true", check=False)
            directory = REMOTE + "/" + run_id + "/" + role
            if role in roles:
                ssh(role, f"sudo -n chown -R deploy:deploy {directory}; tc -s -j qdisc show dev eth0 > {directory}/qdisc-after.json; "
                    f"tar -czf {REMOTE}/{run_id}-{role}.tar.gz -C {REMOTE}/{run_id} {role}")
                copy(role, REMOTE + "/" + run_id + "-" + role + ".tar.gz", local / (role + ".tar.gz"), download=True)
            if collection:
                ssh(role, "sudo -n nft delete table inet omega_measure 2>/dev/null || true", check=False)
        manifest["ended_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return local


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("install", "original-preflight", "run"))
    parser.add_argument("--id")
    parser.add_argument("--bots", type=int, default=3)
    parser.add_argument("--behavior", default="movement")
    parser.add_argument("--duration", type=int, default=360)
    parser.add_argument("--build", default="instrumented")
    args = parser.parse_args()
    if args.mode == "install":
        install()
    elif args.mode == "original-preflight":
        run("original-3-full-attempt2", 3, "movement", 90)
        for index, collection in enumerate((False, True, True, False), 1):
            run(f"original-50-control-{index}", 50, "movement", 120, collection=collection)
    else:
        run(args.id, args.bots, args.behavior, args.duration, build=args.build)


if __name__ == "__main__":
    main()
