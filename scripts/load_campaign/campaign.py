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
POPULATIONS = [50, 100, 150, 200, 250, 500, 750, 999]
REPETITIONS = (1,)  # User amendment 2026-10-14: one five-minute run per test.
PLANNED_POPULATION_LIMIT = {'movement': 150, 'combat': 150, 'clustered': 150, 'strategy': 999}
STATE = run.RAW / "campaign-state.json"


def populations_for_workload(behavior):
    return [population for population in POPULATIONS if population <= PLANNED_POPULATION_LIMIT[behavior]]


def idle_populations(highest):
    # The user allows only Strategy at 200+; idle controls stay in the lower range.
    return sorted({100, min(150, max(highest.values(), default=100))})


def validate_highest_scope(state):
    for behavior, population in state.get('highest_stable', {}).items():
        if behavior not in PLANNED_POPULATION_LIMIT or population > PLANNED_POPULATION_LIMIT[behavior]:
            raise RuntimeError('Recorded highest population exceeds the planned workload scope: ' + behavior)


def core_progress(highest, failed, boundaries=None):
    return {'highest_stable': highest, 'first_failed': failed, 'boundaries': boundaries or {},
            'planned_populations_by_workload': {behavior: populations_for_workload(behavior) for behavior in BEHAVIORS},
            'ladder_stop_reason': {behavior: 'failed-observation' if behavior in failed else
                'planned-population-limit' if highest.get(behavior) == PLANNED_POPULATION_LIMIT[behavior] else
                'not-yet-complete' for behavior in BEHAVIORS}}


def cell(name, population, behavior, repeat=1, profile="native", variant="native"):
    if population >= 200 and behavior != 'strategy':
        raise ValueError('The amended matrix permits only Strategy at 200 or more players')
    replacements_path = run.RAW / "matrix-replacements.json"
    replacements = json.loads(replacements_path.read_text()) if replacements_path.exists() else {}
    name = replacements.get(name, {}).get("selected_run_id", name)
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
    """Retain the r1 naming convention; schedule only one observation."""
    return [cell(f"{prefix}-r{repeat}", population, behavior, repeat, profile, variant) for repeat in REPETITIONS]


def core():
    gate = json.loads((run.RAW / "measurement-preflight-resolution.json").read_text())
    if not gate.get("scored_runs_authorized_by_preflight"):
        raise RuntimeError("Measurement preflight gate is not satisfied")
    results = {}
    active = list(BEHAVIORS)
    highest = {}
    failed = {}
    for population in POPULATIONS:
        active = [behavior for behavior in active if population in populations_for_workload(behavior)]
        if not active:
            break
        for repeat in REPETITIONS:
            order = active
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
        STATE.write_text(json.dumps(core_progress(highest, failed), indent=2))
        if not active:
            break
    # Refine a valid server failure or generator validity boundary without attributing
    # generator saturation to the server. Both boundary sides remain explicitly classified from their single observations.
    boundaries = {}
    for behavior, failure in failed.items():
        lower, upper = highest.get(behavior, 0), failure["population"]
        while upper - lower > 25:
            middle = ((lower + upper) // 2 // 25) * 25
            if middle <= lower:
                middle = lower + 25
            group = repeats(f"boundary-{behavior}-{middle}", middle, behavior)
            if all(stable(result) for result in group):
                lower = middle
            else:
                upper = middle
        if lower:
            highest[behavior] = lower
        boundaries[behavior] = {"lower": lower, "upper": upper,
                                "note": "No positive stable population established" if lower == 0 else "Classification of the failed side determines whether this is a server boundary or generator validity boundary"}
        STATE.write_text(json.dumps(core_progress(highest, failed, boundaries), indent=2))
    for population in idle_populations(highest):
        repeats(f"idle-{population}", population, "idle")
    STATE.write_text(json.dumps({**core_progress(highest, failed, boundaries), "core_complete": True}, indent=2))


def network():
    state = json.loads(STATE.read_text())
    validate_highest_scope(state)
    for repeat in REPETITIONS:
        profiles = list(netem.PROFILES)
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
    validate_highest_scope(state)
    highest = min(state["highest_stable"].get(behavior, 0) for behavior in ("combat", "clustered", "strategy"))
    for repeat in REPETITIONS:
        variants = ["native", "snapshot15", "aoi600", "native"]
        for behavior in ("combat", "clustered", "strategy"):
            for population in sorted({100, highest} - {0}):
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
    state["admission_check_required"] = state["highest_stable"].get("strategy") == 999
    state["matrix_measurement_phases_complete"] = True
    STATE.write_text(json.dumps(state, indent=2))
    print("Matrix measurement phases complete; inspect evidence, provider reconciliation and conditional admission requirement before resolving issue.", flush=True)


if __name__ == "__main__":
    hold_path = run.RAW / 'full-matrix-hold.json'
    if hold_path.exists() and not json.loads(hold_path.read_text()).get('full_matrix_restart_authorized'):
        raise RuntimeError('Full matrix held by user direction: validate one smooth run and present the checklist/time estimate before restarting')
    {"core": core, "network": network, "transfer": transfer, "all": all_phases}[sys.argv[1]]()
