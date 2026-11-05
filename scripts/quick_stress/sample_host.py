#!/usr/bin/env python3
"""1 Hz host sampler for quick_stress.sh: process CPU/RSS, system CPU, UDP error counters.

Writes one JSON line per second with CUMULATIVE counters (the report takes deltas), so a
sampler that dies mid-run still leaves a usable prefix. Linux reads procfs directly; macOS falls
back to `ps`/`netstat -s`. Processes to watch come from a pid file (`name=pid` per line) that is
re-read every tick, so the bot swarm can be added after the server has started.

With --identity (the DigitalOcean common-window recorder, omega.measurement/2) each row also keeps
this sampler's own wall/monotonic pair, the boot id, each watched process's kernel start identity and
per-thread CPU, every UDP socket that exact process owns (inode, local endpoint, drops, queues), raw
memory/OOM counters, raw interface counters and what the sample itself cost. Host-wide kernel counters
stay in `udp.snmp`, never merged with a socket's. Missing values are absent, never zero.

Usage: sample_host.py --out host.ndjson --pids pids.txt [--udp-port 8081] [--interval 1.0] [--identity]
"""
import argparse
import contextlib
import ctypes
import json
import os
import platform
import struct
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
                    tx, rx = cols[4].split(":")  # procfs column is tx_queue:rx_queue
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


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except OSError:
        pass
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=2).stdout
        return out.split(",")[0].strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def start_id(pid):
    """guest_runner.process_start_id: the kernel's start time for this pid, or None. A zombie counts as gone."""
    if IS_LINUX:
        try:
            with open(f"/proc/{pid}/stat", errors="replace") as f:
                fields = f.read().rsplit(")", 1)[1].split()
            return None if fields[0] in ("Z", "X") else "ticks:" + fields[19]
        except (OSError, IndexError):
            return None
    info = ctypes.create_string_buffer(136)
    try:
        size = ctypes.CDLL("/usr/lib/libproc.dylib").proc_pidinfo(pid, 3, ctypes.c_uint64(0), info, 136)
    except OSError:
        return None
    if size != 136 or struct.unpack_from("<I", info.raw, 4)[0] == 5:
        return None
    return "bsd:%d.%06d" % struct.unpack_from("<QQ", info.raw, 120)


def parse_proc_net_udp(text):
    """Rows of /proc/net/udp or udp6, by inode. Drops and queues belong to that one socket."""
    rows = {}
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 13 or ":" not in cols[1]:
            continue
        with contextlib.suppress(ValueError):
            tx, rx = cols[4].split(":")
            rows[cols[9]] = {"inode": cols[9], "local": cols[1], "local_port": int(cols[1].rsplit(":", 1)[1], 16), "drops": int(cols[12]),
                             "rx_queue": int(rx, 16), "tx_queue": int(tx, 16)}
    return rows


def udp_table(proc_root="/proc"):
    rows = {}
    for table in ("net/udp", "net/udp6"):
        with contextlib.suppress(OSError):
            with open(f"{proc_root}/{table}") as f:
                rows.update(parse_proc_net_udp(f.read()))
    return rows


def owned_sockets(pid, table, proc_root="/proc"):
    """Only sockets this exact pid holds open, joined on inode. A row for anyone else's socket is never attributed to it."""
    found = []
    try:
        names = os.listdir(f"{proc_root}/{pid}/fd")
    except OSError:
        return None
    for name in names:
        with contextlib.suppress(OSError):
            target = os.readlink(f"{proc_root}/{pid}/fd/{name}")
            if target.startswith("socket:[") and target[8:-1] in table:
                found.append(table[target[8:-1]])
    return sorted(found, key=lambda row: row["local_port"])


def lsof_sockets(pid):
    """Development only: endpoints and a reusable kernel address, with no drop counter on this platform."""
    try:
        out = subprocess.run(["lsof", "-nP", "-a", "-p", str(pid), "-iUDP", "-Fdn"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows, device = [], None
    for line in out.splitlines():
        if line.startswith("d"):
            device = line[1:]
        elif line.startswith("n") and ":" in line:
            port = line.rsplit(":", 1)[1].split("-")[0]
            if port.isdigit():
                rows.append({"inode": f"lsof:{pid}:{device}", "local": line[1:], "local_port": int(port), "drops": None, "rx_queue": None, "tx_queue": None,
                             "counter_source": "unavailable_on_platform"})
    return sorted(rows, key=lambda row: row["local_port"])


def thread_cpu(pid, proc_root="/proc"):
    """Per-thread cumulative CPU by thread name. Linux only: absent elsewhere rather than zero."""
    threads = {}
    try:
        tids = os.listdir(f"{proc_root}/{pid}/task")
    except OSError:
        return None
    clk = os.sysconf("SC_CLK_TCK")
    for tid in tids:
        with contextlib.suppress(OSError, IndexError, ValueError):
            with open(f"{proc_root}/{pid}/task/{tid}/stat", errors="replace") as f:
                text = f.read()
            name = text[text.index("(") + 1:text.rindex(")")]
            rest = text[text.rindex(")") + 2:].split()
            threads[f"{name}/{tid}"] = (int(rest[11]) + int(rest[12])) / clk
    return threads


def memory_facts(proc_root="/proc"):
    facts = {}
    with contextlib.suppress(OSError, ValueError, IndexError):
        with open(f"{proc_root}/meminfo") as f:
            values = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in f if len(line.split()) >= 2}
        for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
            if key in values:
                facts[key] = values[key]
    with contextlib.suppress(OSError, ValueError, IndexError):
        with open(f"{proc_root}/vmstat") as f:
            values = {line.split()[0]: int(line.split()[1]) for line in f if len(line.split()) == 2}
        for key in ("oom_kill", "pgmajfault", "pswpin", "pswpout"):
            if key in values:
                facts[key] = values[key]
    return facts


def interface_counters(proc_root="/proc"):
    facts = {}
    with contextlib.suppress(OSError, ValueError, IndexError):
        with open(f"{proc_root}/net/dev") as f:
            for line in f.readlines()[2:]:
                name, values = line.split(":", 1)
                cols = values.split()
                facts[name.strip()] = {"rx_bytes": int(cols[0]), "rx_packets": int(cols[1]), "rx_errs": int(cols[2]), "rx_drop": int(cols[3]),
                                       "tx_bytes": int(cols[8]), "tx_packets": int(cols[9]), "tx_errs": int(cols[10]), "tx_drop": int(cols[11])}
    return facts


def identity_row(row, seq, began_ns):
    """The extra fields of one --identity row. The wall/monotonic pair is the tightest thing here."""
    wall_before = time.time_ns()
    mono = time.monotonic_ns()
    wall_after = time.time_ns()
    row["clock"] = {"wall_before_ns": wall_before, "mono_ns": mono, "wall_after_ns": wall_after}
    row["seq"] = seq
    row["boot_id"] = boot_id()
    table = udp_table() if IS_LINUX else None
    for name, facts in row["procs"].items():
        pid = facts["pid"]
        facts["start_id"] = start_id(pid)
        facts["sockets"] = owned_sockets(pid, table) if IS_LINUX else lsof_sockets(pid)
        if IS_LINUX:
            facts["thread_cpu_s"] = thread_cpu(pid)
    if IS_LINUX:
        row["memory"] = memory_facts()
        row["interfaces"] = interface_counters()
    row["collector_ns"] = time.monotonic_ns() - began_ns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pids", required=True)
    ap.add_argument("--udp-port", type=int, default=0)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--identity", action="store_true")
    args = ap.parse_args()
    start = time.monotonic()
    with open(args.out, "a") as out:
        out.write(json.dumps({"kind": "meta", "platform": platform.platform(), "cpus": os.cpu_count(), "ts": time.time()}) + "\n")
        out.flush()
        n = 0
        while True:
            began_ns = time.monotonic_ns()
            row = {"ts": time.time(), "mono_s": round(time.monotonic() - start, 3), "procs": {}, "system": system_cpu()}
            for name, pid in read_pids(args.pids).items():
                row["procs"][name] = dict(proc_linux(pid) if IS_LINUX else proc_ps(pid), pid=pid) if args.identity else (proc_linux(pid) if IS_LINUX else proc_ps(pid))
            try:
                row["load1"] = os.getloadavg()[0]
            except (AttributeError, OSError):
                pass
            row["udp"] = udp_linux(args.udp_port) if IS_LINUX else (udp_darwin() if IS_DARWIN else {})
            if args.identity:
                identity_row(row, n, began_ns)
            out.write(json.dumps(row) + "\n")
            out.flush()
            n += 1
            time.sleep(max(0.0, start + n * args.interval - time.monotonic()))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
