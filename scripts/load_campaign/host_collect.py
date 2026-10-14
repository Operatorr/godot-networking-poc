#!/usr/bin/env python3
"""Read-only host observations; run on each isolated benchmark endpoint.

Flow counters are installed by the controller. Raw output intentionally stays in the
ignored evidence archive: socket/host details must not enter the public report.
"""
import argparse
import gzip
import json
import os
import pathlib
import signal
import subprocess
import time
import urllib.request


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=5)
    return {"rc": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def read(path):
    try:
        return pathlib.Path(path).read_text()
    except OSError:
        return None


def sample(role, swarm_unit=None):
    before = time.time_ns()
    result = {"utc_ns": before, "monotonic_ns": time.monotonic_ns(),
              "clock_ticks_s": os.sysconf("SC_CLK_TCK"), "page_size": os.sysconf("SC_PAGE_SIZE")}
    for name in ("stat", "meminfo", "net/snmp", "net/softnet_stat", "net/dev", "net/udp", "net/udp6", "pressure/cpu"):
        result[name] = read("/proc/" + name)
    result["interface"] = {
        name: read("/sys/class/net/eth0/statistics/" + name)
        for name in ("tx_bytes", "rx_bytes", "tx_packets", "rx_packets", "rx_dropped", "tx_dropped")
    }
    result["processes"] = {}
    if swarm_unit:
        result["swarm_cgroup_cpu"] = read("/sys/fs/cgroup/system.slice/" + swarm_unit + ".service/cpu.stat")
        if result["swarm_cgroup_cpu"] is None:
            result["swarm_systemd_cpu_ns"] = command(["systemctl", "show", swarm_unit, "--property=CPUUsageNSec", "--value"])
    for directory in pathlib.Path("/proc").iterdir():
        if directory.name.isdigit() and read(directory / "comm") in ("omega-server\n", "omega-load-test\n", "tcpdump\n"):
            result["processes"][directory.name] = {
                name: read(directory / name) for name in ("comm", "stat", "status", "io")
            }
    result["nft_before_utc_ns"] = time.time_ns()
    result["nft"] = command(["sudo", "-n", "nft", "-j", "list", "table", "inet", "omega_measure"])
    result["nft_after_utc_ns"] = time.time_ns()
    result["tc"] = command(["tc", "-s", "-j", "qdisc", "show", "dev", "eth0"])
    if role == "game":
        try:
            with urllib.request.urlopen("http://127.0.0.1:9100/metrics", timeout=2) as response:
                result["prometheus"] = response.read().decode()
        except Exception as error:
            result["prometheus_error"] = str(error)
    result["sample_duration_ns"] = time.time_ns() - before
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("game", "bots"), required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--light", action="store_true")
    parser.add_argument("--swarm-unit")
    args = parser.parse_args()
    directory = pathlib.Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with gzip.open(directory / "host.ndjson.gz", "wt") as output:
        deadline = time.monotonic() + args.seconds
        next_sample = time.monotonic()
        boundaries = set()
        while not stopped and time.monotonic() < deadline:
            schedule = read(directory / "window.json")
            targets = json.loads(schedule) if schedule else {}
            for boundary, target in targets.items():
                if boundary not in boundaries and time.time_ns() >= target:
                    observation = sample(args.role, args.swarm_unit)
                    observation["boundary"] = boundary
                    observation["target_utc_ns"] = target
                    (directory / (boundary + ".json")).write_text(json.dumps(observation))
                    boundaries.add(boundary)
            if not args.light and time.monotonic() >= next_sample:
                output.write(json.dumps(sample(args.role, args.swarm_unit)) + "\n")
                output.flush()
                next_sample += 1
            nearest = min([v for k, v in targets.items() if k not in boundaries] or [time.time_ns() + 100_000_000])
            time.sleep(max(0.001, min(0.05, (nearest - time.time_ns()) / 1e9)))


if __name__ == "__main__":
    main()
