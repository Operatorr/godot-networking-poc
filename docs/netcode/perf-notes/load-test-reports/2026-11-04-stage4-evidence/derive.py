#!/usr/bin/env python3
"""Stage 4 evidence-only derivation. Reads retained evidence, never rewrites it.

Sources: clean-run summaries from git commit fcf4f62 (not on master), plus the
committed 2026-10-13 and 2026-10-14-one-pass bundles. Writes only beside itself.
Run from anywhere inside the repository: python3 derive.py

python3 derive.py --check-archives is read-only: it hashes any original archives
found under the repo's deployment/hetzner/results/ and prints counts, writing nothing.
Run it on the machine that holds them.
"""
import calendar, csv, glob, hashlib, json, math, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True).strip()
REPORTS = os.path.join(ROOT, "docs/netcode/perf-notes/load-test-reports")
PIN = "fcf4f62c3d625a24caf8c462e186c8887fa98ce9"
CLEAN = "docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs"
YEAR = 2027  # non-leap forecast year agreed in the matrix

# Retained, conditional price model from the agreed matrix. NOT a verified 2026-11 quote.
COMPUTE, IPV4, ALLOW = 6.99, 0.60, 20_000_000_000_000
INCR, INCR_USD = 100_000_000, 0.00012


def show(path):
    return subprocess.check_output(["git", "show", f"{PIN}:{path}"], cwd=ROOT, text=True)


def month_cost(bytes_, allowance=ALLOW):
    return COMPUTE + IPV4 + math.ceil(max(0, bytes_ - allowance) / INCR) * INCR_USD


def forecast(ccu, rate):
    months = [ccu * rate * 86400 * calendar.monthrange(YEAR, m)[1] for m in range(1, 13)]
    b30 = ccu * rate * 86400 * 30
    return {
        "bytes_30d": b30,
        "overage_USD_30d": round(month_cost(b30) - COMPUTE - IPV4, 6) + 0.0,
        "overage_USD_year": round(sum(month_cost(b) - COMPUTE - IPV4 for b in months), 6) + 0.0,
        "TB_30d": b30 / 1e12,
        "TiB_30d": b30 / 2**40,
        "USD_30d": month_cost(b30),
        "USD_30d_binary_allowance": month_cost(b30, 20 * 2**40),
        "bytes_year": sum(months),
        "USD_year": sum(month_cost(b) for b in months),
        "USD_year_binary_allowance": sum(month_cost(b, 20 * 2**40) for b in months),
        "peak_month_TB": max(months) / 1e12,
        "mean_Mbit_s": ccu * rate * 8 / 1e6,
    }


def clean_rows():
    names = subprocess.check_output(
        ["git", "ls-tree", "--name-only", PIN, CLEAN + "/"], cwd=ROOT, text=True
    ).split()
    rows = []
    for path in names:
        base = os.path.basename(path)
        if not (base.startswith("clean-") and base.endswith("-summary.json")):
            continue
        s = json.loads(show(path))
        m = s.get("measurement") or {}
        w = m.get("wire") or {}
        secs = w.get("complete_common_utc_seconds")
        row = {"namespace": base[6:-13], "classification": s.get("classification")}
        if not secs or secs < 299:
            row["excluded_reason"] = f"no complete steady wire window ({secs} s)"
            rows.append(row)
            continue
        t = w["hosts"]["game"]["totals"]
        ticks = m["ticks"]
        auth, alive = ticks["authenticated"], ticks["alive"]
        abs_ = w["active_bot_seconds"]
        iface = s["hosts"]["game"]["periods"]["steady_window"]["interface_delta"]
        win = s["hosts"]["game"]["periods"]["steady_window"]
        iface_s = (win["end_ns"] - win["start_ns"]) / 1e9
        flow = ((s.get("collectors") or {}).get("game") or {}).get("flow_counters") or {}
        out = flow.get("out") or {}
        build = ((s.get("settings") or {}).get("candidate_revision"), s["settings"].get("experiment_binary_sha256"))
        row.update(
            excluded_reason="",
            population=auth["max"],
            auth_min=auth["min"],
            wire_seconds=secs,
            tick_count=ticks["count"] if isinstance(ticks["count"], int) else None,
            authenticated_player_seconds_wire=abs_,
            alive_median=alive["median"],
            alive_median_fraction=alive["median"] / auth["max"],
            out_ip_bytes=t["out_ip_bytes"],
            out_packets=t["out_packets"],
            out_ip_bytes_s=t["out_ip_bytes"] / secs,
            r_out=t["out_ip_bytes"] / abs_,
            r_out_per_median_alive=t["out_ip_bytes"] / (alive["median"] * secs),
            mean_datagram_bytes=t["out_ip_bytes"] / t["out_packets"],
            ip_udp_header_share=28 * t["out_packets"] / t["out_ip_bytes"],
            reliable_retry_share=t["reliable_retry_command_bytes"] / t["out_ip_bytes"],
            interface_tx_bytes_s=iface["tx_bytes"] / iface_s,
            capture_span_ip_bytes=out.get("ip_bytes"),
            capture_span_first_tx_payload_bytes=out.get("first_transmission_payload_bytes"),
            revision=build[0],
            game_sha256=(build[1] or {}).get("game"),
            bots_sha256=(build[1] or {}).get("bots"),
            rx_buffer=s["settings"]["game_config"].get("udp_receive_buffer_bytes"),
            snapshot_hz=s["settings"]["game_config"].get("snapshot_rate_hz"),
            aoi=s["settings"]["game_config"].get("aoi_radius"),
        )
        rows.append(row)
    return rows


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def claimed_archives():
    """Yield (group, relative path, sha256) for every archive the retained evidence names."""
    for f in sorted(glob.glob(os.path.join(REPORTS, "*/*/retained-evidence.json"))):
        r = json.load(open(f))
        loc = r.get("original_archives_relative_location")
        for name, sha in (r.get("sha256") or {}).items():
            yield "report-bundles", os.path.join(loc, name) if loc else None, sha
    names = subprocess.check_output(["git", "ls-tree", "--name-only", PIN, CLEAN + "/"], cwd=ROOT, text=True).split()
    for path in names:
        base = os.path.basename(path)
        if base.startswith("clean-") and base.endswith("-summary.json"):
            s = json.loads(show(path))
            loc = s.get("private_evidence")
            for name, sha in (s.get("evidence_sha256") or {}).items():
                if isinstance(sha, str):
                    yield "clean-runs", os.path.join(loc, name) if loc else None, sha


def verify_tree():
    """Read-only: do the archives named by retained evidence resolve and match on this machine?"""
    out = {}
    for group, rel, sha in claimed_archives():
        g = out.setdefault(group, {"claimed": 0, "present": 0, "match": 0, "mismatch": []})
        g["claimed"] += 1
        p = os.path.join(ROOT, rel) if rel else None
        if p and os.path.exists(p):
            g["present"] += 1
            if sha256_file(p) == sha:
                g["match"] += 1
            else:
                g["mismatch"].append(rel)
    return out


def inventories():
    res = {}
    for d in ("2026-10-13", "2026-10-14-one-pass"):
        inv = json.load(open(os.path.join(REPORTS, d, "attempt-inventory.json")))
        scored = json.load(open(os.path.join(REPORTS, d, "scored-runs.json")))
        repl = json.load(open(os.path.join(REPORTS, d, "matrix-replacements.json")))
        c = {}
        for e in inv:
            c[e.get("classification")] = c.get(e.get("classification"), 0) + 1
        res[d] = {
            "attempts": len(inv),
            "attempt_classes": c,
            "scored": len(scored),
            "selected": sum(1 for r in scored if r.get("selected_for_matrix_cell")),
            "replacements": len(repl),
            "scored_window_present": sum(1 for e in inv if e.get("scored_300s_window_present")),
        }
    led = json.loads(show(CLEAN + "/campaign-ledger.json"))
    res["2026-10-22-clean-runs"] = {
        "completed_entries": len(led["completed"]),
        "diagnostic_attempts": len(led.get("diagnostic_attempts") or []),
        "candidate_revision": led.get("candidate_revision"),
        "game_sha256": led.get("game_sha256"),
    }
    return res


def main():
    rows = clean_rows()
    keys = sorted({k for r in rows for k in r})
    first = ["namespace", "classification", "population", "wire_seconds", "r_out", "out_ip_bytes_s", "alive_median"]
    keys = first + [k for k in keys if k not in first]
    with open(os.path.join(HERE, "fixed-build-transfer.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["namespace"]))
    models = {}
    for r in rows:
        if r.get("classification") == "clean-cell-pass" and r.get("population") == 100:
            models[r["namespace"]] = {"status": "conditional forecast at a measured population", "ccu": 100, "r_out": r["r_out"], **forecast(100, r["r_out"])}
    for r in rows:
        if r.get("classification") == "clean-cell-pass" and r.get("population") == 150:
            models[r["namespace"]] = {"status": "conditional forecast at a measured population", "ccu": 150, "r_out": r["r_out"], **forecast(150, r["r_out"])}
    strat150 = next(r for r in rows if r["namespace"].startswith("strategy150-r2"))["r_out"]
    models["HYPOTHETICAL-1000-flat-strategy150-rate"] = {"status": "[MEASURE] hypothetical; no valid 999 cell; fan-out unmeasured; no host shown to carry it", "ccu": 1000, "r_out": strat150, **forecast(1000, strat150)}
    models["HYPOTHETICAL-1000-default-client-budget"] = {"status": "[MEASURE] hypothetical; configured default per-client budget treated as bytes/s, not a measured rate", "ccu": 1000, "r_out": 120000, **forecast(1000, 120000)}
    assumptions = {
        "price_status": "Retained historical conditional assumptions from the agreed matrix; not an account quote",
        "compute_USD_month": COMPUTE, "ipv4_USD_month": IPV4,
        "allowance_bytes_month": ALLOW, "excess_increment_bytes": INCR, "excess_increment_USD": INCR_USD,
        "game_host_USD_month": COMPUTE + IPV4, "game_host_USD_year": (COMPUTE + IPV4) * 12,
        "test_pair_USD_month": (COMPUTE + IPV4) * 2, "test_pair_USD_year": (COMPUTE + IPV4) * 24,
        "year": YEAR,
    }
    json.dump({"assumptions": assumptions, "models": models, "inventories": inventories(), "archive_check": verify_tree()},
              open(os.path.join(HERE, "economics-and-reconciliation.json"), "w"), indent=2, sort_keys=True)


if __name__ == "__main__":
    if "--check-archives" in sys.argv:
        print(json.dumps(verify_tree(), indent=2, sort_keys=True))
    else:
        main()
