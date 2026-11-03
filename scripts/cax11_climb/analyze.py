#!/usr/bin/env python3
"""Evaluate one CAX11 climb trial from its raw evidence. Pure: reads files, returns a dict.

Window: the first 1800 consecutive Ticks at full population (issue #78 resolution). Drops count
across the whole run and are also split into ramp / minute / tail. All six gates are evaluated
together on every run. Usage: analyze.py <trial-dir> [--bots N] [--smoke-rtt-p95 MS]
"""
import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # quick_stress/__pycache__ is tracked on this branch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "quick_stress"))
import report as qs  # noqa: E402  (shared phase analysis from the one-minute stress loop)

WINDOW_TICKS = 1800
TICK_BUDGET_MS = 33.3
RTT_P95_GATE_MS = 150.0
LOSS_GATE_PCT = 2.0
ONE_TICK_MS = 33.3
INT_COLS = ("tick", "authenticated", "alive", "projectiles", "deferred", "pending_replication",
            "max_deferred_wait_ticks", "max_queue_age", "peers_evaluated")


def read_ticks(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "utc_ns": int(r["utc_ns"]), "mono_ns": int(r["mono_ns"]), "work_ns": int(r["work_ns"]),
                "budget_pct": float(r["budget_pct"]), **{k: int(float(r[k])) for k in INT_COLS},
            })
    return rows


def full_population_runs(rows, bots):
    """[start, end) index ranges of consecutive Ticks at exactly `bots` authenticated."""
    runs, start = [], None
    for i, r in enumerate(rows):
        if r["authenticated"] != bots:
            if start is not None:
                runs.append((start, i))
                start = None
            continue
        if start is not None and r["tick"] != rows[i - 1]["tick"] + 1:
            runs.append((start, i))
            start = None
        if start is None:
            start = i
    if start is not None:
        runs.append((start, len(rows)))
    return runs


def select_window(rows, bots, want=WINDOW_TICKS):
    """First `want` consecutive full-population Ticks, plus the longest run's length.

    If no run qualifies the window is the longest run, shorter than `want`: a broken run is still
    reported, and the full-population gate fails rather than certifying it.
    """
    runs = full_population_runs(rows, bots)
    if not runs:
        return [], 0
    longest = max(end - start for start, end in runs)
    for start, end in runs:
        if end - start >= want:
            return rows[start:start + want], longest
    start, end = max(runs, key=lambda run: run[1] - run[0])
    return rows[start:end], longest


def pct(sorted_values, q):
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def stat(values):
    v = sorted(values)
    if not v:
        return None
    return {"mean": statistics.mean(v), "p50": pct(v, .5), "p95": pct(v, .95), "p99": pct(v, .99), "max": v[-1]}


def host_rows(path):
    rows = [r for r in qs.load_ndjson(str(path)) if r.get("kind") != "meta"]
    return [r for r in rows if r.get("udp", {}).get("snmp")]


def split_counter(rows, key, lo_s=None, hi_s=None):
    """Delta of a cumulative SNMP counter per run phase. 1 Hz: boundaries are good to about 1 s.

    With no window (lo_s None) the phases do not exist, but the whole-run delta still does.
    """
    if len(rows) < 2:
        return None
    value = lambda r: r["udp"]["snmp"].get(key, 0)  # noqa: E731
    first, last = value(rows[0]), value(rows[-1])
    if lo_s is None:
        return {"whole": last - first, "ramp": None, "minute": None, "tail": None}
    at_or_before = lambda t: next((value(r) for r in reversed(rows) if r["ts"] <= t), first)  # noqa: E731
    at_lo, at_hi = at_or_before(lo_s), at_or_before(hi_s)
    return {"whole": last - first, "ramp": at_lo - first, "minute": at_hi - at_lo, "tail": last - at_hi}


def mac_workers(path, lo_s, hi_s):
    """The two busiest `ps -M` rows per sample. Rows carry no stable thread id, so this is the
    sampled %CPU of the two most active threads, not a per-thread accounting."""
    top, mean = [], []
    if not Path(path).exists():
        return None
    for line in Path(path).read_text().splitlines():
        s = json.loads(line)
        if not lo_s <= s["ts"] <= hi_s:
            continue
        cpu = []
        for row in s["ps"].splitlines()[1:]:
            parts = row.split()
            if parts:
                cpu.append(float(parts[-1]))
        cpu = sorted(cpu[1:] or [0.0])[-2:]
        top.append(max(cpu))
        mean.append(statistics.mean(cpu))
    if not top:
        return None
    return {"peak_sampled_pct": max(top), "mean_top2_pct": statistics.mean(mean), "samples": len(top)}


def mac_counter_delta(before, after, needle):
    def read(p):
        if not Path(p).exists():
            return None
        for line in Path(p).read_text().splitlines():
            if needle in line:
                return int(line.split()[0])
        return None
    a, b = read(before), read(after)
    return None if a is None or b is None else b - a


def effective_buffers(log_path):
    text = re.sub(r"\x1b\[[0-9;]*m", "", Path(log_path).read_text(errors="replace")) if Path(log_path).exists() else ""
    m = re.search(r"effective_receive_bytes=(\d+).*?effective_send_bytes=(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def bot_samples(report):
    """Time series of 5 s merged samples: recent RTT p95 range, kept next to the ramp-inclusive p95."""
    series = report.get("time_series") or []
    p95 = [s.get("latency_p95_ms") or s.get("rtt_p95_ms") for s in series]
    p95 = [v for v in p95 if v]
    return {"samples": len(series), "rtt_p95_min": min(p95), "rtt_p95_max": max(p95)} if p95 else {"samples": len(series)}


def analyze(trial, bots, smoke_rtt_p95=None):
    trial = Path(trial)
    ticks = read_ticks(trial / "server/ticks.csv")
    window, longest = select_window(ticks, bots)
    out = {"bots": bots, "ticks_total": len(ticks), "longest_full_population_ticks": longest,
           "window_ticks": len(window)}
    lo_s, hi_s = (window[0]["utc_ns"] / 1e9, window[-1]["utc_ns"] / 1e9) if window else (None, None)
    # Whole-run evidence, so it does not depend on the run ever reaching full population.
    hrows = host_rows(trial / "host.ndjson")
    out["drops"] = split_counter(hrows, "RcvbufErrors", lo_s, hi_s)
    out["sndbuf_errors"] = split_counter(hrows, "SndbufErrors", lo_s, hi_s)
    sock = [r["udp"]["socket"] for r in qs.load_ndjson(str(trial / "host.ndjson")) if r.get("udp", {}).get("socket")]
    if sock:
        out["socket"] = {"drops": sock[-1]["drops"] - sock[0]["drops"],
                         "rx_queue_max": max(s["rx_queue"] for s in sock),
                         "tx_queue_max": max(s["tx_queue"] for s in sock)}
    if window:
        work = [r["work_ns"] / 1e6 for r in window]
        over = sum(w > TICK_BUDGET_MS for w in work)
        out.update({
            "window_first_tick": window[0]["tick"], "window_last_tick": window[-1]["tick"],
            "window_utc_start_s": lo_s, "window_utc_end_s": hi_s,
            "minimum_population": min(r["authenticated"] for r in window),
            "tick_ms": stat(work), "ticks_over": over, "ticks_over_pct": 100.0 * over / len(work),
            "deferred": stat([r["deferred"] for r in window]),
            "deferred_wait_ticks": stat([r["max_deferred_wait_ticks"] for r in window]),
            "peers_at_budget_pct": stat([r["budget_pct"] for r in window]),
            "projectiles": stat([r["projectiles"] for r in window]),
        })
        selected = trial / "selected-server.ndjson"
        rows = [r for r in qs.load_ndjson(str(trial / "server/server.ndjson"))
                if r.get("boundary", "") == "" and window[0]["mono_ns"] <= r["mono_ns"] <= window[-1]["mono_ns"]]
        selected.write_text("".join(json.dumps(r) + "\n" for r in rows))
        sa = qs.analyze_server_samples(str(selected), window[0]["mono_ns"]) or {}
        phases = sa.get("phases", {})
        out["server"] = {
            "sample_window_s": sa.get("window_s"),
            "phase_ms_per_tick": {k: v["ms_per_tick"] for k, v in phases.items()},
            "cpu_core_pct": sa.get("process", {}).get("cpu_core_pct"),
            "rss_bytes": sa.get("process", {}).get("rss_bytes"),
            "transport": sa.get("transport"), "enet": sa.get("enet"),
            "sent_bytes_per_s": sa.get("sent_bytes_per_s"),
            "event_sends_per_s": sum(sa.get("event_sends_per_s", {}).values()),
        }
        inside = [r for r in hrows if lo_s <= r["ts"] <= hi_s and "total_s" in r.get("system", {})]
        if len(inside) >= 2:
            a_sys, b_sys = inside[0]["system"], inside[-1]["system"]
            total = b_sys["total_s"] - a_sys["total_s"]
            if total > 0:
                out["host"] = {"steal_pct": 100.0 * (b_sys["steal_s"] - a_sys["steal_s"]) / total,
                               "busy_pct": 100.0 * (1 - (b_sys["idle_s"] - a_sys["idle_s"]) / total)}
        # Offered = what reached the socket in the minute: delivered plus dropped.
        rx = (sa.get("transport") or {}).get("received_datagrams_per_s")
        dur = sa.get("window_s") or 0
        if rx is not None and dur:
            out["offered_datagrams_per_s"] = rx + (out["drops"]["minute"] if out["drops"] else 0) / dur
            out["datagrams_in_minute"] = rx * dur
        out["mac"] = {"workers": mac_workers(trial / "mac-threads.ndjson", lo_s - 5, hi_s + 5),
                      "udp_full_buffer_delta": mac_counter_delta(trial / "udp-before.txt", trial / "udp-after.txt",
                                                                 "dropped due to full socket buffers")}
    rep = json.loads((trial / "bots/report.json").read_text()) if (trial / "bots/report.json").exists() else {}
    agg = rep.get("aggregated", {})
    out["bots_report"] = {k: agg.get(k) for k in (
        "connected_bots", "disconnected_bots", "total_errors", "total_decode_failures", "total_send_failures",
        "total_panics", "latency_avg_ms", "latency_p95_ms", "latency_max_ms", "packet_loss_pct",
        "bandwidth_per_player_kbps")}
    out["bot_samples"] = bot_samples(rep)
    out["effective_receive_bytes"], out["effective_send_bytes"] = effective_buffers(trial / "server.log")
    errors = sum(agg.get(k) or 0 for k in ("total_errors", "total_decode_failures", "total_send_failures", "total_panics"))
    rtt = agg.get("latency_p95_ms")
    loss = agg.get("packet_loss_pct")
    drops = (out.get("drops") or {}).get("whole")
    out["error_count"] = errors
    out["gates"] = {
        "full_population": len(window) == WINDOW_TICKS,
        "bot_errors": bool(agg) and errors == 0,
        "tick_overruns": bool(window) and out.get("ticks_over_pct", 100) < 1.0,
        "socket_drops": drops == 0,
        "rtt_p95": rtt is not None and rtt < RTT_P95_GATE_MS,
        "loss": loss is not None and loss < LOSS_GATE_PCT,
    }
    out["gates_passed"] = sum(out["gates"].values())
    out["all_but_rtt"] = all(v for k, v in out["gates"].items() if k != "rtt_p95")
    if smoke_rtt_p95 is not None and rtt is not None:
        out["smoke_rtt_p95_ms"] = smoke_rtt_p95
        out["excess_rtt_ms"] = rtt - smoke_rtt_p95
        out["excess_rtt_over_one_tick"] = out["excess_rtt_ms"] > ONE_TICK_MS
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trial")
    ap.add_argument("--bots", type=int, required=True)
    ap.add_argument("--smoke-rtt-p95", type=float)
    a = ap.parse_args()
    print(json.dumps(analyze(a.trial, a.bots, a.smoke_rtt_p95), indent=2))
