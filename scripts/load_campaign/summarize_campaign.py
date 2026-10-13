#!/usr/bin/env python3
"""Incremental public summary; each row keeps validity next to transfer and cost."""
import csv
import json
import pathlib
import economics
import publish
import run


def main():
    rows = []
    for path in sorted(run.RAW.glob("*/steady.json")):
        result = json.loads(path.read_text())
        if result.get("window_s") != 300:
            continue
        rate = result.get("outbound_ip_bytes_player_s")
        forecasts = {}
        if rate is not None:
            for ccu in (result["requested_bots"],):
                forecasts[str(ccu)] = {"decimal": economics.forecast(rate, ccu), "binary_sensitivity": economics.forecast(rate, ccu, binary=True)}
            if result["requested_bots"] == 999 and result.get("generator_valid") and result.get("server_sustainability_gate"):
                forecasts["1000"] = {"decimal": economics.forecast(rate, 1000), "binary_sensitivity": economics.forecast(rate, 1000, binary=True),
                                     "status": "Marginal extrapolation from this 999-player cell, not 1000-player admission evidence"}
        forecast_path = publish.OUTPUT / path.parent.name / "conditional-forecast.json"
        forecast_path.parent.mkdir(parents=True, exist_ok=True)
        forecast_path.write_text(json.dumps({"source_run": path.parent.name, "source_classification": result["classification"],
                                             "rate_bytes_authenticated_player_second": rate, "forecasts": forecasts,
                                             "status": "Continuous-use conditional economics. Invalid/failing source rows cannot establish sustainable CCU costs."}, indent=2))
        economic = forecasts.get(str(result["requested_bots"]), {}).get("decimal", {})
        rows.append({
            "run_id": path.parent.name, "classification": result["classification"],
            "requested_population": result["requested_bots"], "actual_min": result.get("population_min"), "actual_max": result.get("population_max"),
            "workload": result["behavior"], "profile": result.get("profile", "native"), "variant": result.get("variant", "native"),
            "repeat": result.get("repeat"), "authenticated_player_seconds": result.get("authenticated_player_seconds"),
            "alive_player_seconds": result.get("alive_player_seconds"), "alive_fraction": result.get("alive_fraction"),
            "outbound_ip_bytes_s": result.get("outbound_ip_bytes_s"), "outbound_ip_bytes_player_s": rate,
            "tested_ccu_30day_outbound_bytes": economic.get("illustrative_30_days", {}).get("outbound_bytes"),
            "tested_ccu_365day_outbound_bytes": economic.get("annual_outbound_bytes"),
            "tested_ccu_30day_game_host_USD_conditional": economic.get("illustrative_30_days", {}).get("total_game_host_USD"),
            "tested_ccu_year_game_host_USD_conditional": economic.get("annual_game_host_USD"),
            "tick_hz": result.get("tick_hz"), "tick_work_p99_ms": result.get("tick_work_ms", {}).get("p99"),
            "tick_work_max_ms": result.get("tick_work_ms", {}).get("max"), "tick_deadline_exceedances": result.get("tick_work_ms", {}).get("exceed_33_333ms"),
            "server_cpu_percent_one_core": result.get("game_host", {}).get("process_cpu_percent_one_core"),
            "server_steal_percent": result.get("game_host", {}).get("steal_percent"),
            "generator_cpu_percent_one_core": result.get("bots_host", {}).get("swarm_cgroup_cpu_percent_one_core", result.get("bots_host", {}).get("process_cpu_percent_one_core")),
            "generator_offered_hz": 30, "generator_achieved_hz": result.get("generator", {}).get("overall_hz"),
            "minimum_bot_input_hz": result.get("generator", {}).get("minimum_bot_hz"),
            "rtt_mean_ms": result.get("rtt_ms", {}).get("mean"), "rtt_p95_ms": result.get("rtt_ms", {}).get("p95"),
            "outbound_loss_percent": result.get("directional_loss", {}).get("out", {}).get("loss_pct"),
            "inbound_loss_percent": result.get("directional_loss", {}).get("in", {}).get("loss_pct"),
            "deaths": result.get("source_events_by_type", {}).get("2", 0) + result.get("source_events_by_type", {}).get("10", 0),
            "disconnects_legacy": result.get("legacy_aggregated", {}).get("disconnected_bots"),
            "pending_replication_max": result.get("pending_replication", {}).get("max"),
            "deferred_wait_max_ticks": result.get("max_deferred_wait_ticks", {}).get("max"),
            "delta_age_p99_s": result.get("delivery", {}).get("delta_age_s", {}).get("p99"),
            "baseline_reference_misses": result.get("baseline_reference_misses"),
        })
    if rows:
        with (publish.OUTPUT / "summary.csv").open("w") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    (publish.OUTPUT / "scored-runs.json").write_text(json.dumps(rows, indent=2))
    sensitivity = {str(ccu): {str(kib): economics.forecast(kib * 1024, ccu) for kib in (5, 15, 30)} for ccu in (100, 1000)}
    (publish.OUTPUT / "unmeasured-cost-sensitivity.json").write_text(json.dumps({"status": "[MEASURE] hypothetical rates; unmeasured fan-out and capacity; not a forecast from 50-player preflight", "rows": sensitivity}, indent=2))
    print("Scored summary rows:", len(rows))


if __name__ == "__main__":
    main()
