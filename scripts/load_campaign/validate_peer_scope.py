#!/usr/bin/env python3
"""Validate corrected peer scope, retain the invalid attempt, then resume the matrix."""
import hashlib
import json
import run
import analyze
import publish
import summarize_campaign
import campaign


def collect(name, count, duration, profile="native", behavior="movement"):
    directory = run.run(name, count, behavior, duration, build="instrumented", profile=profile)
    result = analyze.summarize(directory)
    (directory / "steady.json").write_text(json.dumps(result, indent=2))
    publish.publish(name)
    if not result.get("collector_valid") or not result.get("generator_valid"):
        raise RuntimeError("Validation invalid: " + name)
    return result


def main():
    validations = [collect("scope-3-native-validation", 3, 90),
                   collect("scope-3-combined-validation", 3, 90, "combined"),
                   collect("scope-50-native-validation", 50, 120)]
    if not all(row.get("server_sustainability_gate") for row in validations):
        raise RuntimeError("Peer-scope preflight server gate failed")
    gate_path = run.RAW / "measurement-preflight-resolution.json"
    gate = json.loads(gate_path.read_text())
    gate["peer_scope_validation"] = {"capture_source_sha256": hashlib.sha256((run.ROOT / "scripts/load_campaign/capture.py").read_bytes()).hexdigest(),
        "runs": [row["run_id"] for row in validations], "passed": True,
        "reason": "Port-only capture included one unrelated Internet probe; raw capture/counters now require the test peer IP and game port."}
    gate_path.write_text(json.dumps(gate, indent=2))
    (publish.OUTPUT / gate_path.name).write_text(publish.redact(gate_path.read_text()))
    old_name, new_name = "core-strategy-50-r1", "core-strategy-50-r1-attempt2"
    old = json.loads((run.RAW / old_name / "steady.json").read_text())
    if old["classification"] != "collector-invalid":
        raise RuntimeError("Only collector-invalid attempts may be replaced")
    directory = run.run(new_name, 50, "strategy", build="instrumented", repeat=1)
    result = analyze.summarize(directory)
    (directory / "steady.json").write_text(json.dumps(result, indent=2))
    publish.publish(new_name)
    if not result.get("collector_valid"):
        raise RuntimeError("Replacement collector invalid; retain attempt and stop")
    # A valid generator/server failure is selected as failure, never retried for a pass.
    mapping = {old_name: {"selected_run_id": new_name, "original_invalid_attempt_retained": True,
                         "reason": "Corrected collection scope after independently identified non-test-peer traffic",
                         "replacement_classification": result["classification"]}}
    (run.RAW / "matrix-replacements.json").write_text(json.dumps(mapping, indent=2))
    (publish.OUTPUT / "matrix-replacements.json").write_text(json.dumps(mapping, indent=2))
    summarize_campaign.main()
    campaign.all_phases()


if __name__ == "__main__":
    main()
