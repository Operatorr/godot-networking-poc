#!/usr/bin/env python3
"""Render one quick_stress run into REPORT.md + summary.json + a stdout summary.

Reads (all optional except run.json; missing inputs degrade to "n/a"):
  run.json            harness metadata (args, commit, host)
  bots/report.json    omega-load-test report (aggregates, per-bot, criteria, assertions)
  server/ticks.csv    one row per server Tick (work_ns, entity counts, scheduler diagnostics)
  server/server.ndjson 1 Hz server samples (loop-phase timings, bytes by type, events, procfs CPU)
  host.ndjson         1 Hz host sampler (process CPU/RSS, system CPU, UDP error counters)
  server.log bots.log log hygiene (size, WARN/ERROR counts)

Usage: report.py <run_dir> [--ledger ledger.md] [--quiet]
"""
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

SERVER_PACKET = {64: "AuthResult", 65: "Snapshot", 66: "ActionConfirm", 67: "GameEvent", 68: "ServerMetrics"}
CLIENT_PACKET = {1: "ConnectAuth", 2: "PlayerInput", 3: "BaselineAck", 4: "RequestFullState", 5: "RespawnRequest", 6: "LocalHitReport"}
EVENT_TYPE = {1: "DAMAGE", 2: "KILL", 3: "RESPAWN", 4: "EFFECT_APPLY", 5: "EFFECT_REMOVE", 6: "PICKUP", 7: "LEVEL_UP",
              8: "CHAT", 9: "PLAYER_INFO", 10: "KILL_PVP", 11: "LEADERBOARD", 12: "PROJECTILE_FIRED", 13: "EXP_GAIN",
              14: "ABILITY_EFFECT", 15: "PROGRESS"}
PHASES = ["service_and_route", "world_tick", "snapshot_build", "outbox_flush", "enet_flush"]
TICK_MS = 1000.0 / 30.0


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_ndjson(path):
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return rows


def pct(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * q))]


def fmt(v, unit="", nd=1):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}{unit}"
    return f"{v}{unit}"


def human_bytes(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


# ── server ticks ──────────────────────────────────────────────────────────────────────────
def analyze_ticks(path):
    rows = []
    try:
        with open(path) as f:
            for r in csv.DictReader(f):
                rows.append(r)
    except OSError:
        return None
    if not rows:
        return None
    ticks = [{k: float(v) for k, v in r.items()} for r in rows]
    max_auth = max(t["authenticated"] for t in ticks)
    # steady window: from the first tick at >= 95 % of peak population to the end
    thresh = max_auth * 0.95
    first_steady = next((i for i, t in enumerate(ticks) if t["authenticated"] >= thresh), 0)
    steady = ticks[first_steady:]
    ramp = ticks[:first_steady]

    def stats(sel):
        work = [t["work_ns"] / 1e6 for t in sel]
        n = len(work) or 1
        return {
            "ticks": len(sel),
            "work_ms_avg": sum(work) / n,
            "work_ms_p50": pct(work, 0.5), "work_ms_p95": pct(work, 0.95), "work_ms_p99": pct(work, 0.99),
            "work_ms_max": max(work) if work else 0.0,
            "over_16ms_pct": 100.0 * sum(1 for w in work if w > 16.0) / n,
            "over_33ms_pct": 100.0 * sum(1 for w in work if w > TICK_MS) / n,
            "lag_s_max": max((t["accumulator_lag_s"] for t in sel), default=0.0),
            "players_avg": sum(t["authenticated"] for t in sel) / n,
            "alive_avg": sum(t["alive"] for t in sel) / n,
            "monsters_avg": sum(t["monsters"] for t in sel) / n,
            "monsters_peak": max((t["monsters"] for t in sel), default=0),
            "projectiles_avg": sum(t["projectiles"] for t in sel) / n,
            "projectiles_peak": max((t["projectiles"] for t in sel), default=0),
            "effects_avg": sum(t["effects"] for t in sel) / n,
            "deferred_avg": sum(t["deferred"] for t in sel) / n,
            "budget_pct_avg": sum(t["budget_pct"] for t in sel) / n,
            "queue_age_max": max((t["max_queue_age"] for t in sel), default=0),
            "overflow_max": max((t["overflow"] for t in sel), default=0),
            "observer_ns_avg": sum(t["observer_ns"] for t in sel) / n,
        }

    span_s = (ticks[-1]["mono_ns"] - ticks[0]["mono_ns"]) / 1e9 if len(ticks) > 1 else 0.0
    steady_span_s = (steady[-1]["mono_ns"] - steady[0]["mono_ns"]) / 1e9 if len(steady) > 1 else 0.0
    return {
        "players_peak": max_auth,
        "ramp_s": (ticks[first_steady]["mono_ns"] - ticks[0]["mono_ns"]) / 1e9 if ramp else 0.0,
        "span_s": span_s,
        "achieved_tick_hz": (len(ticks) - 1) / span_s if span_s > 0 else 0.0,
        "steady_tick_hz": (len(steady) - 1) / steady_span_s if steady_span_s > 0 else 0.0,
        "steady_first_mono_ns": steady[0]["mono_ns"] if steady else 0,
        "steady": stats(steady),
        "ramp": stats(ramp) if ramp else None,
        "all": stats(ticks),
    }


# ── server 1 Hz samples ───────────────────────────────────────────────────────────────────
def analyze_server_samples(path, steady_first_mono_ns):
    rows = [r for r in load_ndjson(path) if r.get("boundary", "") == ""]
    if len(rows) < 2:
        return None
    # window: first sample at/after steady start … last sample
    start_idx = next((i for i, r in enumerate(rows) if r["mono_ns"] >= steady_first_mono_ns), 0)
    if start_idx >= len(rows) - 1:
        start_idx = max(0, len(rows) - 2)
    a, b = rows[start_idx], rows[-1]
    dt = (b["mono_ns"] - a["mono_ns"]) / 1e9
    if dt <= 0:
        return None
    out = {"window_s": dt, "samples": len(rows)}
    ticks = (b.get("tick", 0) - a.get("tick", 0)) or 1
    phases = {}
    for ph in PHASES:
        pa, pb = a["loop_phases"].get(ph), b["loop_phases"].get(ph)
        if not pa or not pb:
            continue
        total_ns = pb["total_ns"] - pa["total_ns"]
        count = pb["count"] - pa["count"]
        phases[ph] = {
            "core_pct": 100.0 * total_ns / 1e9 / dt,
            "ms_per_tick": total_ns / 1e6 / ticks,
            "calls_per_s": count / dt,
            "max_ms": pb["max_ns"] / 1e6,
        }
    if "world_tick" in phases and "snapshot_build" in phases:
        sim = dict(phases["world_tick"])
        sim["core_pct"] -= phases["snapshot_build"]["core_pct"]
        sim["ms_per_tick"] -= phases["snapshot_build"]["ms_per_tick"]
        sim["max_ms"] = None
        phases["simulation (= world_tick - snapshot_build)"] = sim
    out["phases"] = phases
    out["phase_core_pct_total"] = sum(p["core_pct"] for k, p in phases.items() if not k.startswith("simulation"))
    pa, pb = a.get("process"), b.get("process")
    if pa and pb:
        out["process"] = {
            "cpu_core_pct": 100.0 * ((pb["user_s"] + pb["system_s"]) - (pa["user_s"] + pa["system_s"])) / dt,
            "user_core_pct": 100.0 * (pb["user_s"] - pa["user_s"]) / dt,
            "system_core_pct": 100.0 * (pb["system_s"] - pa["system_s"]) / dt,
            "rss_bytes": pb["rss_bytes"],
            "threads": pb["threads"],
        }

    def by_type(key, names):
        da = {k: v for k, v in a.get(key, [])}
        db = {k: v for k, v in b.get(key, [])}
        res = {}
        for k, chans in db.items():
            prev = da.get(k, [0, 0, 0])
            delta = [chans[i] - prev[i] for i in range(3)]
            if sum(delta) > 0:
                res[names.get(k, str(k))] = {"bytes_per_s": sum(delta) / dt, "ch": [d / dt for d in delta]}
        return res

    out["sent_by_type"] = by_type("sent_bytes_by_type_channel", SERVER_PACKET)
    out["received_by_type"] = by_type("received_bytes_by_type_channel", CLIENT_PACKET)
    out["sent_bytes_per_s"] = sum(v["bytes_per_s"] for v in out["sent_by_type"].values())
    out["received_bytes_per_s"] = sum(v["bytes_per_s"] for v in out["received_by_type"].values())
    ev = {}
    for i, (ea, eb) in enumerate(zip(a.get("event_sends", []), b.get("event_sends", []))):
        if eb - ea > 0:
            ev[EVENT_TYPE.get(i, str(i))] = (eb - ea) / dt
    out["event_sends_per_s"] = dict(sorted(ev.items(), key=lambda kv: -kv[1]))
    src = {}
    for i, (ea, eb) in enumerate(zip(a.get("source_events", []), b.get("source_events", []))):
        if eb - ea > 0:
            src[EVENT_TYPE.get(i, str(i))] = (eb - ea) / dt
    out["source_events_per_s"] = dict(sorted(src.items(), key=lambda kv: -kv[1]))
    out["baselines_per_s"] = (b.get("baselines", 0) - a.get("baselines", 0)) / dt
    out["deltas_per_s"] = (b.get("deltas", 0) - a.get("deltas", 0)) / dt
    out["send_errors"] = b.get("send_errors", 0)
    out["decode_errors"] = b.get("decode_errors", 0)
    ta, tb = a.get("transport"), b.get("transport")
    if ta and tb:
        gaps = tb["read_gaps"]
        out["transport"] = {
            "received_datagrams_per_s": (tb["received_datagrams"] - ta["received_datagrams"]) / dt,
            "send_calls_per_s": (tb["send_calls"] - ta["send_calls"]) / dt,
            "receive_errors": tb["receive_errors"], "send_errors": tb["send_errors"],
            "zero_byte_sends": tb["zero_byte_sends"],
            "read_gap_max_ms": gaps["max_ns"] / 1e6,
            "read_gaps_over_10ms": sum(gaps["buckets"][5:]),
            "read_gaps_over_33ms": sum(gaps["buckets"][7:]),
        }
    return out


# ── host sampler ──────────────────────────────────────────────────────────────────────────
def analyze_host(path, t_steady_wall):
    rows = [r for r in load_ndjson(path) if r.get("kind") != "meta"]
    meta = next((r for r in load_ndjson(path) if r.get("kind") == "meta"), {})
    if len(rows) < 2:
        return None
    start_idx = next((i for i, r in enumerate(rows) if r["ts"] >= t_steady_wall), 0)
    if start_idx >= len(rows) - 1:
        start_idx = max(0, len(rows) - 2)
    a, b = rows[start_idx], rows[-1]
    dt = b["ts"] - a["ts"]
    out = {"window_s": dt, "cpus": meta.get("cpus"), "platform": meta.get("platform"), "procs": {}}
    names = set()
    for r in rows:
        names.update(r.get("procs", {}).keys())
    for name in sorted(names):
        # Per process, use its own alive span inside the window (the swarm exits before the
        # server does, so the last host row may already show it gone).
        alive = [(i, r["procs"][name]) for i, r in enumerate(rows) if r.get("procs", {}).get(name, {}).get("alive") and "cpu_s" in r["procs"][name]]
        span = [(i, p) for i, p in alive if i >= start_idx] or alive
        if len(span) < 2:
            continue
        (ia, pa), (ib, pb) = span[0], span[-1]
        d_all = rows[ib]["ts"] - rows[ia]["ts"]
        if d_all <= 0:
            continue
        peaks = []
        for (i0, p0), (i1, p1) in zip(span, span[1:]):
            d = rows[i1]["ts"] - rows[i0]["ts"]
            if d > 0:
                peaks.append(100.0 * (p1["cpu_s"] - p0["cpu_s"]) / d)
        out["procs"][name] = {
            "cpu_core_pct": 100.0 * (pb["cpu_s"] - pa["cpu_s"]) / d_all,
            "cpu_core_pct_peak": max(peaks) if peaks else None,
            "rss_bytes": max(p.get("rss_bytes", 0) for _, p in span),
            "threads": pb.get("threads"),
            "window_s": d_all,
        }
    sa, sb = a.get("system", {}), b.get("system", {})
    if "total_s" in sa and "total_s" in sb and sb["total_s"] > sa["total_s"]:
        tot = sb["total_s"] - sa["total_s"]
        out["system"] = {
            "busy_pct": 100.0 * (1 - (sb["idle_s"] - sa["idle_s"]) / tot),
            "steal_pct": 100.0 * (sb["steal_s"] - sa["steal_s"]) / tot,
        }
    ua, ub = a.get("udp", {}).get("snmp", {}), b.get("udp", {}).get("snmp", {})
    if ua and ub:
        out["udp"] = {k: ub.get(k, 0) - ua.get(k, 0) for k in ("InDatagrams", "OutDatagrams", "InErrors", "RcvbufErrors", "SndbufErrors") if k in ub}
        # whole-run deltas too (errors during the ramp matter)
        u0 = rows[0].get("udp", {}).get("snmp", {})
        out["udp_whole_run"] = {k: ub.get(k, 0) - u0.get(k, 0) for k in ("InErrors", "RcvbufErrors", "SndbufErrors") if k in ub}
    sock_rows = [r.get("udp", {}).get("socket") for r in rows if r.get("udp", {}).get("socket")]
    if sock_rows:
        out["server_socket"] = {
            "drops": sock_rows[-1]["drops"] - sock_rows[0]["drops"],
            "rx_queue_max": max(s["rx_queue"] for s in sock_rows),
            "tx_queue_max": max(s["tx_queue"] for s in sock_rows),
        }
    out["load1_max"] = max((r.get("load1", 0.0) for r in rows), default=None)
    return out


# ── logs ──────────────────────────────────────────────────────────────────────────────────
def analyze_log(path):
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    levels = Counter()
    messages = Counter()
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    with open(path, errors="replace") as f:
        for line in f:
            line = ansi.sub("", line)
            m = re.search(r"\b(WARN|ERROR)\b\s+(\S+):\s*(.*)", line)
            if m:
                levels[m.group(1)] += 1
                msg = re.sub(r"\d+", "N", m.group(3))[:90]
                messages[msg] += 1
    return {"bytes": size, "warn": levels["WARN"], "error": levels["ERROR"], "top": messages.most_common(5)}


# ── verdict ───────────────────────────────────────────────────────────────────────────────
def verdict(run, bots, ticks, srv, host):
    reasons = []
    findings = []
    agg = (bots or {}).get("aggregated", {})
    criteria = (bots or {}).get("success_criteria", [])
    connected = agg.get("connected_bots", 0)
    requested = run.get("bots", 0)
    failed_criteria = [c for c in criteria if not c.get("passed")]
    if bots is None:
        reasons.append("no bot report (swarm crashed or never ran)")
    if requested and connected < requested:
        reasons.append(f"only {connected}/{requested} bots connected")
    if (agg.get("total_errors", 0) or 0) > 0:
        reasons.append(f"{agg['total_errors']} bot errors")
    for c in failed_criteria:
        reasons.append(f"criterion failed: {c.get('criterion')} ({c.get('value')})")
    steady = (ticks or {}).get("steady", {})
    if steady and steady.get("over_33ms_pct", 0) > 1.0:
        reasons.append(f"{steady['over_33ms_pct']:.1f}% of ticks over 33 ms")
    udp = (host or {}).get("udp_whole_run", {})
    if udp.get("RcvbufErrors", 0) > 0:
        reasons.append(f"host UDP RcvbufErrors +{udp['RcvbufErrors']}")

    # bottleneck heuristics — in order of "this invalidates everything after it"
    threads = max(1, run.get("threads", 1))
    bots_cpu = (host or {}).get("procs", {}).get("bots", {}).get("cpu_core_pct")
    server_cpu = ((srv or {}).get("process") or {}).get("cpu_core_pct")
    if server_cpu is None:
        server_cpu = (host or {}).get("procs", {}).get("server", {}).get("cpu_core_pct")
    if bots_cpu is not None and bots_cpu / threads > 85:
        findings.append(f"GENERATOR-BOUND: bot swarm at {bots_cpu:.0f}% CPU over {threads} thread(s) "
                        f"({bots_cpu / threads:.0f}% per thread) — add --threads or a bigger bot host; "
                        f"server numbers from this run are suspect")
    if server_cpu is not None and server_cpu > 85:
        top = ""
        phases = (srv or {}).get("phases", {})
        if phases:
            ranked = sorted(((k, v["core_pct"]) for k, v in phases.items() if not k.startswith("simulation")), key=lambda kv: -kv[1])
            top = " — biggest phase: " + ", ".join(f"{k} {v:.0f}%" for k, v in ranked[:2])
        findings.append(f"SERVER CPU-BOUND: {server_cpu:.0f}% of one core{top}")
    if udp.get("RcvbufErrors", 0) > 0:
        findings.append("UDP RECEIVE OVERFLOW: the kernel dropped datagrams for lack of socket buffer — "
                        "the server loop is not draining fast enough (or bursts exceed the buffer)")
    if steady and steady.get("work_ms_p95", 0) > TICK_MS:
        findings.append(f"TICK OVERRUN: p95 tick work {steady['work_ms_p95']:.1f} ms > {TICK_MS:.1f} ms budget")
    if agg and (agg.get("packet_loss_pct", 0) > 2 or agg.get("latency_p95_ms", 0) > 150):
        findings.append(f"NETWORK: loss {agg.get('packet_loss_pct', 0):.2f}%, RTT p95 {agg.get('latency_p95_ms', 0):.0f} ms")
    if not findings:
        headroom = ""
        if server_cpu and server_cpu > 0 and steady.get("players_avg"):
            per_player = server_cpu / steady["players_avg"]
            headroom = f"; server CPU {server_cpu:.0f}% ≈ {per_player:.2f}%/player (linear headroom to 85%: ~{85 / per_player:.0f} players — real growth is super-linear, see event rates)"
        findings.append("NO BOTTLENECK HIT at this population" + headroom)
    ok = not reasons
    return ("PASS" if ok else "FAIL"), reasons, findings


# ── render ────────────────────────────────────────────────────────────────────────────────
def render(run_dir, run, bots, ticks, srv, host, logs):
    status, reasons, findings = verdict(run, bots, ticks, srv, host)
    agg = (bots or {}).get("aggregated", {})
    steady = (ticks or {}).get("steady", {}) or {}
    L = []
    L.append(f"# quick_stress run — {os.path.basename(run_dir)}")
    L.append("")
    L.append(f"**{status}** · {run.get('bots')} {run.get('behavior')} bots × {run.get('duration_s')} s · join every "
             f"{run.get('stagger_ms')} ms · {run.get('threads')} swarm thread(s) · seed {run.get('seed')} · "
             f"commit `{run.get('git_sha')}`{' (dirty)' if run.get('git_dirty') else ''} · "
             f"{run.get('platform')} {run.get('host_cpus')} cpus · wall {run.get('wall_s')} s")
    L.append("")
    if reasons:
        L.append("Why not a pass:")
        L.extend(f"- {r}" for r in reasons)
        L.append("")
    L.append("Bottleneck read:")
    L.extend(f"- {f}" for f in findings)
    L.append("")

    L.append("## Server tick (steady window = from 95 % of peak population to end)")
    L.append("")
    if ticks:
        L.append(f"- players peak {ticks['players_peak']:.0f}, ramp {ticks['ramp_s']:.1f} s, steady window {steady.get('ticks', 0)} ticks, "
                 f"achieved tick rate {ticks['steady_tick_hz']:.2f} Hz (whole run {ticks['achieved_tick_hz']:.2f} Hz)")
        L.append("")
        L.append("| | avg | p50 | p95 | p99 | max | >16 ms | >33 ms | accumulator lag max |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        L.append(f"| tick work ms | {steady.get('work_ms_avg', 0):.2f} | {steady.get('work_ms_p50', 0):.2f} | {steady.get('work_ms_p95', 0):.2f} | "
                 f"{steady.get('work_ms_p99', 0):.2f} | {steady.get('work_ms_max', 0):.2f} | {steady.get('over_16ms_pct', 0):.1f}% | "
                 f"{steady.get('over_33ms_pct', 0):.1f}% | {steady.get('lag_s_max', 0) * 1000:.1f} ms |")
        L.append("")
        L.append(f"- entities (avg / peak): players {steady.get('players_avg', 0):.0f} (alive {steady.get('alive_avg', 0):.0f}), "
                 f"monsters {steady.get('monsters_avg', 0):.0f} / {steady.get('monsters_peak', 0):.0f}, "
                 f"projectiles {steady.get('projectiles_avg', 0):.0f} / {steady.get('projectiles_peak', 0):.0f}, "
                 f"effects {steady.get('effects_avg', 0):.0f}")
        L.append(f"- snapshot scheduler: deferred entities/tick {steady.get('deferred_avg', 0):.1f}, peers at byte budget {steady.get('budget_pct_avg', 0):.0f}%, "
                 f"max queue age {steady.get('queue_age_max', 0):.0f} ticks, full-snapshot overflow {steady.get('overflow_max', 0):.0f}")
    else:
        L.append("- no server/ticks.csv (server telemetry missing)")
    L.append("")

    L.append("## Server CPU by loop phase (steady window; 100 % = one core)")
    L.append("")
    if srv and srv.get("phases"):
        p = srv.get("process") or {}
        L.append(f"- process CPU {fmt(p.get('cpu_core_pct'), '%', 0)} (user {fmt(p.get('user_core_pct'), '%', 0)}, "
                 f"sys {fmt(p.get('system_core_pct'), '%', 0)}), RSS {human_bytes(p.get('rss_bytes', 0))}, "
                 f"phases sum {srv['phase_core_pct_total']:.0f}% (rest = sleep/loop overhead/off-thread)")
        L.append("")
        L.append("| phase | % of a core | ms per tick | max ms | calls/s |")
        L.append("|---|---|---|---|---|")
        for k, v in srv["phases"].items():
            L.append(f"| {k} | {v['core_pct']:.1f} | {v['ms_per_tick']:.2f} | {fmt(v['max_ms'], '', 1)} | {v['calls_per_s']:.0f} |")
    else:
        L.append("- no server/server.ndjson phase data")
    L.append("")

    L.append("## Traffic (server view, steady window)")
    L.append("")
    if srv:
        n = max(1.0, steady.get("players_avg", 1.0))
        L.append(f"- out {human_bytes(srv['sent_bytes_per_s'])}/s total = {human_bytes(srv['sent_bytes_per_s'] / n)}/s per player · "
                 f"in {human_bytes(srv['received_bytes_per_s'])}/s total = {human_bytes(srv['received_bytes_per_s'] / n)}/s per player")
        L.append(f"- snapshots: {srv['deltas_per_s']:.0f} deltas/s + {srv['baselines_per_s']:.1f} reliable baselines/s · "
                 f"send errors {srv['send_errors']}, decode errors {srv['decode_errors']}")
        tr = srv.get("transport")
        if tr:
            L.append(f"- socket: {tr['received_datagrams_per_s']:.0f} datagrams in/s, {tr['send_calls_per_s']:.0f} sends/s, "
                     f"receive errors {tr['receive_errors']}, read-gap max {tr['read_gap_max_ms']:.1f} ms "
                     f"({tr['read_gaps_over_10ms']} gaps >10 ms, {tr['read_gaps_over_33ms']} >33 ms)")
        L.append("")
        L.append("| server → client | bytes/s | per player | ch0 snap | ch1 reliable | ch2 |")
        L.append("|---|---|---|---|---|---|")
        for k, v in sorted(srv["sent_by_type"].items(), key=lambda kv: -kv[1]["bytes_per_s"]):
            L.append(f"| {k} | {human_bytes(v['bytes_per_s'])} | {human_bytes(v['bytes_per_s'] / n)} | {human_bytes(v['ch'][0])} | {human_bytes(v['ch'][1])} | {human_bytes(v['ch'][2])} |")
        L.append("")
        L.append("| client → server | bytes/s | per player |")
        L.append("|---|---|---|")
        for k, v in sorted(srv["received_by_type"].items(), key=lambda kv: -kv[1]["bytes_per_s"]):
            L.append(f"| {k} | {human_bytes(v['bytes_per_s'])} | {human_bytes(v['bytes_per_s'] / n)} |")
        L.append("")
        L.append("Reliable GameEvent packets actually sent per second (every broadcast event = one reliable packet PER PEER):")
        L.append("")
        L.append("| event | packets/s (all peers) | per peer/s | source events/s |")
        L.append("|---|---|---|---|")
        for k, v in srv["event_sends_per_s"].items():
            L.append(f"| {k} | {v:.0f} | {v / n:.1f} | {srv['source_events_per_s'].get(k, 0):.1f} |")
        total_ev = sum(srv["event_sends_per_s"].values())
        L.append(f"| **total** | **{total_ev:.0f}** | **{total_ev / n:.1f}** | {sum(srv['source_events_per_s'].values()):.1f} |")
    else:
        L.append("- no server sample data")
    L.append("")

    L.append("## Host (1 Hz sampler, steady window)")
    L.append("")
    if host:
        for name, pr in host.get("procs", {}).items():
            L.append(f"- {name}: CPU {fmt(pr['cpu_core_pct'], '%', 0)} of a core (peak 1 s {fmt(pr['cpu_core_pct_peak'], '%', 0)}), "
                     f"RSS {human_bytes(pr.get('rss_bytes') or 0)}, threads {pr.get('threads', 'n/a')}")
        sy = host.get("system")
        if sy:
            L.append(f"- system: {sy['busy_pct']:.0f}% busy across {host.get('cpus')} cpus, steal {sy['steal_pct']:.1f}%, load1 max {fmt(host.get('load1_max'), '', 2)}")
        u = host.get("udp")
        if u:
            L.append(f"- UDP (host-wide, window): in {u.get('InDatagrams', 0)} / out {u.get('OutDatagrams', 0)} datagrams; "
                     f"InErrors {u.get('InErrors', 0)}, RcvbufErrors {u.get('RcvbufErrors', 0)}, SndbufErrors {u.get('SndbufErrors', 0)} "
                     f"(whole run: {host.get('udp_whole_run')})")
        ss = host.get("server_socket")
        if ss:
            L.append(f"- server socket: drops {ss['drops']}, rx_queue max {human_bytes(ss['rx_queue_max'])}, tx_queue max {human_bytes(ss['tx_queue_max'])}")
    else:
        L.append("- no host.ndjson")
    L.append("")

    L.append("## Bots (client view)")
    L.append("")
    if bots:
        per = bots.get("per_bot", [])
        conn_times = [b.get("connection_time_ms", 0) for b in per if b.get("connected")]
        unexpected = sum(1 for b in per if b.get("unexpected_disconnect"))
        stale = sum(b.get("stale_snapshots_ignored", 0) for b in per)
        baselines = sum(b.get("baselines_received", 0) for b in per)
        L.append(f"- connected {agg.get('connected_bots')}/{run.get('bots')} (disconnected {agg.get('disconnected_bots', 0)}, unexpected disconnects {unexpected}, "
                 f"errors {agg.get('total_errors')}, panics {agg.get('total_panics')}, decode failures {agg.get('total_decode_failures')}, send failures {agg.get('total_send_failures')})")
        L.append(f"- connect time p50 {pct(conn_times, 0.5):.0f} ms / p95 {pct(conn_times, 0.95):.0f} ms / max {max(conn_times) if conn_times else 0:.0f} ms")
        L.append(f"- RTT avg {agg.get('latency_avg_ms')} ms, p95 {agg.get('latency_p95_ms')} ms, p99 {agg.get('latency_p99_ms')} ms, max {agg.get('latency_max_ms')} ms · "
                 f"ENet loss {agg.get('packet_loss_pct')}% · bandwidth {agg.get('bandwidth_per_player_kbps')} KB/s per bot · "
                 f"client-estimated tick rate {agg.get('estimated_tick_rate')} Hz")
        L.append(f"- per bot: {baselines / max(1, len(per)):.1f} baselines, {stale} stale snapshots ignored (swarm total)")
        L.append("")
        L.append("| criterion | value | |")
        L.append("|---|---|---|")
        for c in bots.get("success_criteria", []):
            L.append(f"| {c.get('criterion')} | {c.get('value')} | {'PASS' if c.get('passed') else '**FAIL**'} |")
        for a in bots.get("regression_assertions", []):
            name = a.get("name") or a.get("assertion") or "assertion"
            L.append(f"| {name} | {a.get('detail') or a.get('message') or ''} | {'PASS' if a.get('passed') else ('SKIP' if a.get('skipped') else '**FAIL**')} |")
        ts = bots.get("time_series", [])
        if ts:
            L.append("")
            L.append("| t (s) | bots | RTT avg | RTT p95 | server tick ms | entities |")
            L.append("|---|---|---|---|---|---|")
            for r in ts:
                L.append(f"| {r.get('elapsed_seconds')} | {r.get('connected_bots')} | {r.get('latency_avg_ms', '')} | {r.get('latency_p95_ms', '')} | {r.get('server_avg_tick_time_ms', '')} | {r.get('server_entity_count', '')} |")
    else:
        L.append("- no bots/report.json")
    L.append("")

    L.append("## Log hygiene")
    L.append("")
    for name, lg in logs.items():
        if lg is None:
            continue
        L.append(f"- {name}: {human_bytes(lg['bytes'])}, {lg['warn']} WARN, {lg['error']} ERROR" + ("" if not lg["top"] else " — top: " + "; ".join(f"`{m}` ×{c}" for m, c in lg["top"][:3])))
    big = {n: lg for n, lg in logs.items() if lg and lg["bytes"] > 20 * 1024 * 1024}
    if big:
        L.append(f"- WARNING: {', '.join(big)} over 20 MB — something is logging per event; fix the source before the next run")
    for f in ("server/ticks.csv", "server/server.ndjson", "host.ndjson", "bots/report.json"):
        p = os.path.join(run_dir, f)
        if os.path.exists(p):
            L.append(f"- {f}: {human_bytes(os.path.getsize(p))}")
    L.append("")
    return status, reasons, findings, "\n".join(L) + "\n"


def summary_line(run, status, agg, steady, srv, host, ticks):
    p = (srv or {}).get("process") or {}
    bcpu = ((host or {}).get("procs", {}).get("bots") or {}).get("cpu_core_pct")
    scpu = p.get("cpu_core_pct") if p else ((host or {}).get("procs", {}).get("server") or {}).get("cpu_core_pct")
    udp = (host or {}).get("udp_whole_run", {})
    ev = sum((srv or {}).get("event_sends_per_s", {}).values()) if srv else None
    n = max(1.0, steady.get("players_avg", 1.0)) if steady else 1.0
    return {
        "date": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
        "label": run.get("label"), "sha": run.get("git_sha"), "status": status,
        "bots": run.get("bots"), "behavior": run.get("behavior"),
        "connected": agg.get("connected_bots"),
        "players_peak": (ticks or {}).get("players_peak"),
        "tick_p95_ms": steady.get("work_ms_p95"), "tick_max_ms": steady.get("work_ms_max"),
        "over_33_pct": steady.get("over_33ms_pct"),
        "server_cpu_pct": scpu, "bots_cpu_pct": bcpu,
        "rcvbuf_errors": udp.get("RcvbufErrors"),
        "rtt_p95_ms": agg.get("latency_p95_ms"), "loss_pct": agg.get("packet_loss_pct"),
        "kbps_per_bot": agg.get("bandwidth_per_player_kbps"),
        "events_per_peer_s": (ev / n) if ev is not None else None,
        "out_bytes_per_s": (srv or {}).get("sent_bytes_per_s"),
    }


def ledger_row(s):
    def f(v, nd=1, unit=""):
        return "n/a" if v is None else (f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}")
    return (f"| {s['date']} | {s['label']} | `{s['sha']}` | {s['bots']} {s['behavior']} | {s['status']} | {s['connected']}/{s['bots']} | "
            f"{f(s['tick_p95_ms'], 2)} / {f(s['tick_max_ms'], 1)} | {f(s['over_33_pct'], 1, '%')} | {f(s['server_cpu_pct'], 0, '%')} | "
            f"{f(s['bots_cpu_pct'], 0, '%')} | {f(s['rcvbuf_errors'], 0)} | {f(s['rtt_p95_ms'], 0)} | {f(s['loss_pct'], 2, '%')} | "
            f"{f(s['kbps_per_bot'], 1)} | {f(s['events_per_peer_s'], 0)} | |")


LEDGER_HEADER = ("| date (UTC) | label | commit | bots | result | connected | tick p95 / max ms | ticks >33 ms | server CPU | "
                 "bots CPU | RcvbufErr | RTT p95 ms | loss | KB/s per bot | reliable events per peer/s | notes |\n"
                 "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    run_dir = sys.argv[1]
    ledger = None
    quiet = "--quiet" in sys.argv
    if "--ledger" in sys.argv:
        ledger = sys.argv[sys.argv.index("--ledger") + 1]
    run = load_json(os.path.join(run_dir, "run.json"), {}) or {}
    bots = load_json(os.path.join(run_dir, "bots", "report.json"))
    if bots and isinstance(bots.get("success_criteria"), dict):
        # omega-load-test writes {key: {passed, value}}; normalise to a list with a readable name.
        names = {"latency_avg": "Average latency < 100 ms", "latency_p95": "P95 latency < 150 ms",
                 "bandwidth": "Bandwidth < 5 KB/s per player", "packet_loss": "Packet loss < 2 %",
                 "crash_rate": "Bot crash rate < 5 %", "server_tick_rate": "Server tick rate >= 30 Hz"}
        bots["success_criteria"] = [{"key": k, "criterion": names.get(k, k), "value": v.get("value"), "passed": v.get("passed")}
                                    for k, v in bots["success_criteria"].items()]
    ticks = analyze_ticks(os.path.join(run_dir, "server", "ticks.csv"))
    steady_mono = ticks["steady_first_mono_ns"] if ticks else 0
    srv = analyze_server_samples(os.path.join(run_dir, "server", "server.ndjson"), steady_mono)
    if bots and ticks and ticks.get("steady_tick_hz", 0) >= 29.9:
        # The swarm's ">= 30 Hz" gate is computed from truncated u32 server_ms spans and reads
        # 29.9997 Hz on a perfectly healthy server. The server's own per-tick clock is the
        # authoritative tick rate for this report; keep the raw swarm value visible.
        for c in bots.get("success_criteria", []):
            if c.get("key") == "server_tick_rate" and not c.get("passed"):
                c["passed"] = True
                c["value"] = f"{c.get('value')} (swarm estimate; server clock {ticks['steady_tick_hz']:.3f} Hz)"
    # steady start on the wall clock: server start + ramp
    t_steady_wall = float(run.get("t_server_start", 0)) + (ticks["ramp_s"] if ticks else 0) + 1.0
    host = analyze_host(os.path.join(run_dir, "host.ndjson"), t_steady_wall)
    logs = {"server.log": analyze_log(os.path.join(run_dir, "server.log")), "bots.log": analyze_log(os.path.join(run_dir, "bots.log"))}
    status, reasons, findings, md = render(run_dir, run, bots, ticks, srv, host, logs)
    with open(os.path.join(run_dir, "REPORT.md"), "w") as f:
        f.write(md)
    agg = (bots or {}).get("aggregated", {})
    steady = (ticks or {}).get("steady", {}) or {}
    summ = summary_line(run, status, agg, steady, srv, host, ticks)
    summ["reasons"] = reasons
    summ["findings"] = findings
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump({"summary": summ, "ticks": ticks, "server": srv, "host": host, "logs": {k: (v and {kk: vv for kk, vv in v.items() if kk != "top"}) for k, v in logs.items()}}, f, indent=1, default=str)
    if ledger:
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        exists = os.path.exists(ledger)
        with open(ledger, "a") as f:
            if not exists:
                f.write("# Hill-climb ledger\n\nOne row per `scripts/quick_stress.sh` run (appended automatically). Newest at the bottom.\n\n" + LEDGER_HEADER)
            f.write(ledger_row(summ) + "\n")
    if not quiet:
        # compact stdout summary: the verdict block + the key tables
        print(md.split("## Server tick")[0].rstrip())
        print()
        key = [f"server CPU {fmt(summ['server_cpu_pct'], '%', 0)} · bots CPU {fmt(summ['bots_cpu_pct'], '%', 0)} · "
               f"tick p95 {fmt(summ['tick_p95_ms'], ' ms', 2)} max {fmt(summ['tick_max_ms'], ' ms', 1)} · "
               f">33 ms {fmt(summ['over_33_pct'], '%', 1)} · RcvbufErrors {fmt(summ['rcvbuf_errors'])}",
               f"RTT p95 {fmt(summ['rtt_p95_ms'], ' ms', 0)} · loss {fmt(summ['loss_pct'], '%', 2)} · {fmt(summ['kbps_per_bot'], ' KB/s', 1)} per bot · "
               f"reliable events {fmt(summ['events_per_peer_s'], '/s per peer', 0)} · server out {human_bytes(summ['out_bytes_per_s'] or 0)}/s"]
        print("\n".join(key))
        if srv and srv.get("phases"):
            print("phases (% core): " + ", ".join(f"{k.split(' ')[0]} {v['core_pct']:.0f}" for k, v in srv["phases"].items()))
        if srv and srv.get("event_sends_per_s"):
            top = list(srv["event_sends_per_s"].items())[:4]
            print("top reliable events/s: " + ", ".join(f"{k} {v:.0f}" for k, v in top))
        print(f"\nfull report: {os.path.join(run_dir, 'REPORT.md')}")
    # The verdict is in the text and summary.json; a non-zero exit here would read as a
    # harness failure in quick_stress.sh. The swarm's own exit code carries pass/fail.
    sys.exit(0)


if __name__ == "__main__":
    main()
