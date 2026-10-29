#!/usr/bin/env python3
"""1 Hz host sampler for quick_stress.sh: process CPU/RSS, system CPU, UDP error counters.

Writes one JSON line per second with CUMULATIVE counters (the report takes deltas), so a
sampler that dies mid-run still leaves a usable prefix. Linux reads procfs directly; macOS falls
back to `ps`/`netstat -s`. Processes to watch come from a pid file (`name=pid` per line) that is
re-read every tick, so the bot swarm can be added after the server has started.

Usage: sample_host.py --out host.ndjson --pids pids.txt [--udp-port 8081] [--interval 1.0]
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time

IS_LINUX = platform.system() == "Linux"
IS_DARWIN = platform.system() == "Darwin"


def read_pids(path):
    pids = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    name, pid = line.split("=", 1)
                    try:
                        pids[name.strip()] = int(pid)
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return pids


def proc_linux(pid):
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
        rest = stat[stat.rfind(")") + 2:].split()
        clk = os.sysconf("SC_CLK_TCK")
        return {
            "cpu_s": (int(rest[11]) + int(rest[12])) / clk,
            "user_s": int(rest[11]) / clk,
            "sys_s": int(rest[12]) / clk,
            "threads": int(rest[17]),
            "rss_bytes": int(rest[21]) * os.sysconf("SC_PAGE_SIZE"),
            "alive": True,
        }
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return {"alive": False}


def proc_ps(pid):
    # macOS / generic: cumulative CPU time as [[dd-]hh:]mm:ss.cc and RSS in KiB.
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "time=,rss="], capture_output=True, text=True, timeout=2).stdout.split()
        if len(out) < 2:
            return {"alive": False}
        t, rss = out[0], out[1]
        days = 0
        if "-" in t:
            d, t = t.split("-", 1)
            days = int(d)
        parts = [float(p) for p in t.split(":")]
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        secs += days * 86400
        return {"cpu_s": secs, "rss_bytes": int(rss) * 1024, "alive": True}
    except Exception:
        return {"alive": False}


def system_cpu():
    if IS_LINUX:
        try:
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
            vals = [int(p) for p in parts]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            steal = vals[7] if len(vals) > 7 else 0
            clk = os.sysconf("SC_CLK_TCK")
            return {"total_s": sum(vals) / clk, "idle_s": idle / clk, "steal_s": steal / clk}
        except Exception:
            return {}
    return {}


def udp_linux(port):
    out = {}
    try:
        with open("/proc/net/snmp") as f:
            lines = f.read().splitlines()
        for i in range(0, len(lines) - 1, 2):
            if lines[i].startswith("Udp:"):
                names = lines[i].split()[1:]
                vals = [int(v) for v in lines[i + 1].split()[1:]]
                out["snmp"] = dict(zip(names, vals))
                break
    except Exception:
        pass
    if port:
        try:
            with open("/proc/net/udp") as f:
                lines = f.read().splitlines()[1:]
            hexport = f":{port:04X}"
            for line in lines:
                cols = line.split()
                if cols[1].endswith(hexport):
                    rx, tx = cols[4].split(":")
                    out["socket"] = {
                        "rx_queue": int(rx, 16),
                        "tx_queue": int(tx, 16),
                        "drops": int(cols[-1]),
                    }
                    break
        except Exception:
            pass
    return out


def udp_darwin():
    try:
        txt = subprocess.run(["netstat", "-s", "-p", "udp"], capture_output=True, text=True, timeout=2).stdout
        out = {}
        for line in txt.splitlines():
            line = line.strip()
            if "dropped due to full socket buffers" in line:
                out["RcvbufErrors"] = int(line.split()[0])
            elif line.endswith("datagrams received"):
                out["InDatagrams"] = int(line.split()[0])
            elif line.endswith("datagrams output"):
                out["OutDatagrams"] = int(line.split()[0])
        return {"snmp": out}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pids", required=True)
    ap.add_argument("--udp-port", type=int, default=0)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()
    start = time.monotonic()
    with open(args.out, "a") as out:
        out.write(json.dumps({"kind": "meta", "platform": platform.platform(), "cpus": os.cpu_count(), "ts": time.time()}) + "\n")
        out.flush()
        n = 0
        while True:
            row = {"ts": time.time(), "mono_s": round(time.monotonic() - start, 3), "procs": {}, "system": system_cpu()}
            for name, pid in read_pids(args.pids).items():
                row["procs"][name] = proc_linux(pid) if IS_LINUX else proc_ps(pid)
            try:
                row["load1"] = os.getloadavg()[0]
            except (AttributeError, OSError):
                pass
            row["udp"] = udp_linux(args.udp_port) if IS_LINUX else (udp_darwin() if IS_DARWIN else {})
            out.write(json.dumps(row) + "\n")
            out.flush()
            n += 1
            time.sleep(max(0.0, start + n * args.interval - time.monotonic()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
