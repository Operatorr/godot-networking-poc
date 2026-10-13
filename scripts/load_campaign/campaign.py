#!/usr/bin/env python3
"""Execute scored cells only after a recorded and validated measurement preflight."""
import json
import pathlib
import sys
import run
import analyze
import publish
import netem

BEHAVIORS = ["movement", "combat", "clustered", "strategy"]
POPULATIONS = [50, 100, 250, 500, 750, 999]
STATE = run.RAW / "campaign-state.json"


def cell(name, population, behavior, repeat=1, profile="native", variant="native"):
    directory = run.RAW / name
    if not (directory / "steady.json").exists():
        if directory.exists():
            raise RuntimeError("Unfinished run requires review before resuming: " + name)
        run.run(name, population, behavior, build="instrumented", profile=profile, variant=variant, repeat=repeat)
        result = analyze.summarize(directory)
        (directory / "steady.json").write_text(json.dumps(result, indent=2))
        publish.publish(name)
        import summarize_campaign
        summarize_campaign.main()
    result = json.loads((directory / "steady.json").read_text())
    print(json.dumps({"run": name, "classification": result["classification"], "tick_hz": result.get("tick_hz"),
                      "tick_p99_ms": result.get("tick_work_ms", {}).get("p99"), "input_hz": result.get("generator", {}).get("overall_hz"),
                      "outbound_bytes_s": result.get("outbound_ip_bytes_s")}), flush=True)
    if result["classification"] == "collector-invalid":
        raise RuntimeError("Collector invalid: stop and repair measurement before scored cells")
    return result


def stable(result):
    return result["classification"] == "native-stable-candidate"


def repeats(prefix, population, behavior, profile="native", variant="native"):
    return [cell(f"{prefix}-r{repeat}", population, behavior, repeat, profile, variant) for repeat in range(1, 4)]


def core():
    gate = json.loads((run.RAW / "measurement-preflight-resolution.json").read_text())
    if not gate.get("scored_runs_authorized_by_preflight"):
        raise RuntimeError("Measurement preflight gate is not satisfied")
    results = {}
    active = list(BEHAVIORS)
    highest = {}
    failed = {}
    for population in POPULATIONS:
        for repeat in range(1, 4):
            order = active if repeat != 2 else list(reversed(active))
            for behavior in order:
                result = cell(f"core-{behavior}-{population}-r{repeat}", population, behavior, repeat)
                results.setdefault((behavior, population), []).append(result)
        for behavior in active[:]:
            group = results[behavior, population]
            if all(stable(result) for result in group):
                highest[behavior] = population
            else:
                failed[behavior] = {"population": population, "classes": [result["classification"] for result in group]}
                active.remove(behavior)
        STATE.write_text(json.dumps({"highest_stable": highest, "first_failed": failed}, indent=2))
        if not active:
            break
    # Refine a valid server failure or generator validity boundary without attributing
    # generator saturation to the server. Repeated sides remain explicitly classified.
    boundaries = {}
    for behavior, failure in failed.items():
        lower, upper = highest.get(behavior, 0), failure["population"]
        if lower == 0:
            boundaries[behavior] = {"lower": 0, "upper": upper, "note": "No stable initial rung; no server ceiling established"}
            continue
        while upper - lower > 25:
            middle = ((lower + upper) // 2 // 25) * 25
            if middle <= lower:
                middle = lower + 25
            group = repeats(f"boundary-{behavior}-{middle}", middle, behavior)
            if all(stable(result) for result in group):
                lower = middle
            else:
                upper = middle
        highest[behavior] = lower
        boundaries[behavior] = {"lower": lower, "upper": upper,
                                "note": "Classification of the failed side determines whether this is a server boundary or generator validity boundary"}
        STATE.write_text(json.dumps({"highest_stable": highest, "first_failed": failed, "boundaries": boundaries}, indent=2))
    for population in sorted({100, max(highest.values(), default=100)}):
        repeats(f"idle-{population}", population, "idle")
    STATE.write_text(json.dumps({"highest_stable": highest, "first_failed": failed, "boundaries": boundaries, "core_complete": True}, indent=2))


def network():
    state = json.loads(STATE.read_text())
    for repeat in range(1, 4):
        profiles = list(netem.PROFILES)
        if repeat == 2:
            profiles.reverse()
        for behavior in ("combat", "strategy"):
            highest = state["highest_stable"].get(behavior, 0)
            for population in sorted({100, highest} - {0}):
                if population == 100 and highest < 100:
                    continue
                control = cell(f"network-control-before-{behavior}-{population}-r{repeat}", population, behavior, repeat)
                if not stable(control):
                    raise RuntimeError("Native control no longer passes: review before impairment group")
                for profile in profiles:
                    cell(f"network-{behavior}-{population}-{profile}-r{repeat}", population, behavior, repeat, profile)
                control = cell(f"network-control-after-{behavior}-{population}-r{repeat}", population, behavior, repeat)
                if not stable(control):
                    raise RuntimeError("Native cleanup control no longer passes: preserve group and review")
    state["network_complete"] = True
    STATE.write_text(json.dumps(state, indent=2))


def transfer():
    state = json.loads(STATE.read_text())
    highest = min(state["highest_stable"].get(behavior, 0) for behavior in ("combat", "clustered", "strategy"))
    for repeat in range(1, 4):
        variants = ["native", "snapshot15", "aoi600", "native"]
        if repeat == 2:
            variants = ["native", "aoi600", "snapshot15", "native"]
        for behavior in ("combat", "clustered", "strategy"):
            for population in sorted({100, highest} - {0}):
                if population == 100 and highest < 100:
                    continue
                for index, variant in enumerate(variants):
                    cell(f"transfer-{behavior}-{population}-{variant}-{index}-r{repeat}", population, behavior, repeat, variant=variant)
    state["transfer_complete"] = True
    STATE.write_text(json.dumps(state, indent=2))


def all_phases():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not state.get("core_complete"):
        core()
    state = json.loads(STATE.read_text())
    if not state.get("network_complete"):
        network()
    state = json.loads(STATE.read_text())
    if not state.get("transfer_complete"):
        transfer()
    state = json.loads(STATE.read_text())
    state["admission_check_required"] = state["highest_stable"].get("movement") == 999
    state["matrix_measurement_phases_complete"] = True
    STATE.write_text(json.dumps(state, indent=2))
    print("Matrix measurement phases complete; inspect evidence, provider reconciliation and conditional admission requirement before resolving issue.", flush=True)


if __name__ == "__main__":
    {"core": core, "network": network, "transfer": transfer, "all": all_phases}[sys.argv[1]]()
