#!/usr/bin/env python3
"""Incremental public summary; each row keeps validity next to transfer and cost."""
import csv
import collections
import statistics
import json
import pathlib
import economics
import publish
import run


def main():
    rows = []
    replacements_path = run.RAW / "matrix-replacements.json"
    replacements = json.loads(replacements_path.read_text()) if replacements_path.exists() else {}
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
        binary_economic = forecasts.get(str(result["requested_bots"]), {}).get("binary_sensitivity", {})
        thousand = forecasts.get("1000", {}).get("decimal", {})
        rows.append({
            "run_id": path.parent.name, "classification": result["classification"],
            "selected_for_matrix_cell": path.parent.name not in replacements,

            "requested_population": result["requested_bots"], "actual_min": result.get("population_min"), "actual_max": result.get("population_max"),
            "workload": result["behavior"], "profile": result.get("profile", "native"), "variant": result.get("variant", "native"),
            "repeat": result.get("repeat"), "collector_valid": result.get("collector_valid"), "generator_valid": result.get("generator_valid"),
            "server_sustainability_gate": result.get("server_sustainability_gate"),
            "authenticated_player_seconds": result.get("authenticated_player_seconds"),
            "alive_player_seconds": result.get("alive_player_seconds"), "alive_fraction": result.get("alive_fraction"),
            "outbound_ip_bytes_s": result.get("outbound_ip_bytes_s"), "outbound_ip_bytes_player_s": rate,
            "tested_ccu_30day_outbound_bytes": economic.get("illustrative_30_days", {}).get("outbound_bytes"),
            "tested_ccu_365day_outbound_bytes": economic.get("annual_outbound_bytes"),
            "tested_ccu_30day_game_host_USD_conditional": economic.get("illustrative_30_days", {}).get("total_game_host_USD"),
            "tested_ccu_year_game_host_USD_conditional": economic.get("annual_game_host_USD"),
            "tested_ccu_30day_decimal_TB": economic.get("illustrative_30_days", {}).get("decimal_TB"),
            "tested_ccu_30day_binary_TiB": economic.get("illustrative_30_days", {}).get("binary_TiB"),
            "tested_ccu_30day_game_host_USD_binary_sensitivity": binary_economic.get("illustrative_30_days", {}).get("total_game_host_USD"),
            "tested_ccu_year_game_host_USD_binary_sensitivity": binary_economic.get("annual_game_host_USD"),
            "modeled_1000ccu_30day_outbound_bytes_from_valid_999": thousand.get("illustrative_30_days", {}).get("outbound_bytes"),
            "modeled_1000ccu_365day_outbound_bytes_from_valid_999": thousand.get("annual_outbound_bytes"),
            "modeled_1000ccu_30day_USD_conditional_from_valid_999": thousand.get("illustrative_30_days", {}).get("total_game_host_USD"),
            "modeled_1000ccu_year_USD_conditional_from_valid_999": thousand.get("annual_game_host_USD"),
            "tick_hz": result.get("tick_hz"), "tick_work_p99_ms": result.get("tick_work_ms", {}).get("p99"),
            "tick_work_max_ms": result.get("tick_work_ms", {}).get("max"), "tick_deadline_exceedances": result.get("tick_work_ms", {}).get("exceed_33_333ms"),
            "server_cpu_percent_one_core": result.get("game_host", {}).get("process_cpu_percent_one_core"),
            "server_steal_percent": result.get("game_host", {}).get("steal_percent"),
            "server_sampled_peak_rss_bytes": result.get("game_host", {}).get("sampled_process_peak_rss_bytes"),
            "generator_sampled_peak_rss_bytes": result.get("bots_host", {}).get("sampled_process_peak_rss_bytes"),
            "generator_cpu_percent_one_core": result.get("bots_host", {}).get("swarm_cgroup_cpu_percent_one_core", result.get("bots_host", {}).get("process_cpu_percent_one_core")),
            "generator_offered_hz": 30, "generator_achieved_hz": result.get("generator", {}).get("overall_hz"),
            "minimum_bot_input_hz": result.get("generator", {}).get("minimum_bot_hz"),
            "rtt_mean_ms": result.get("rtt_ms", {}).get("mean"), "rtt_p95_ms": result.get("rtt_ms", {}).get("p95"),
            "outbound_loss_percent": result.get("directional_loss", {}).get("out", {}).get("loss_pct"),
            "inbound_loss_percent": result.get("directional_loss", {}).get("in", {}).get("loss_pct"),
            "authoritative_player_deaths_observed": result.get("authoritative_life_transitions", {}).get("player_deaths_observed"),
            "authoritative_player_respawns_observed": result.get("authoritative_life_transitions", {}).get("player_respawns_observed"),
            "disconnects_legacy": result.get("legacy_aggregated", {}).get("disconnected_bots"),
            "pending_replication_max": result.get("pending_replication", {}).get("max"),
            "deferred_wait_max_ticks": result.get("max_deferred_wait_ticks", {}).get("max"),
            "delta_age_p99_s": result.get("delivery", {}).get("delta_age_s", {}).get("p99"),
            "baseline_reference_misses": result.get("baseline_reference_misses"),
        })
    if rows:
        with (publish.OUTPUT / "summary.csv").open("w") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
    (publish.OUTPUT / "scored-runs.json").write_text(json.dumps(rows, indent=2))
    grouped = collections.defaultdict(list)
    for row in rows:
        family = row["run_id"].split("-", 1)[0]
        grouped[family, row["workload"], row["requested_population"], row["profile"], row["variant"]].append(row)
    spreads = []
    metrics = ("outbound_ip_bytes_s", "outbound_ip_bytes_player_s", "alive_fraction", "tick_hz", "tick_work_p99_ms",
               "server_cpu_percent_one_core", "generator_cpu_percent_one_core", "generator_achieved_hz", "rtt_p95_ms",
               "tested_ccu_30day_game_host_USD_conditional", "tested_ccu_year_game_host_USD_conditional")
    for key, group in sorted(grouped.items()):
        selected = [row for row in group if row["selected_for_matrix_cell"]]
        complete = len({row["repeat"] for row in selected}) >= 3
        spreads.append({"family": key[0], "workload": key[1], "requested_population": key[2], "profile": key[3], "variant": key[4],
                        "runs": [row["run_id"] for row in group], "classes": [row["classification"] for row in group],
                        "three_repeats_present": complete,
                        "all_collector_valid": all(row["collector_valid"] for row in group),
                        "all_generator_valid": all(row["generator_valid"] for row in group),
                        "selected_matrix_runs": [row["run_id"] for row in selected],
                        "native_sustainability_demonstrated_all_repeats": complete and key[3] == "native" and all(row["classification"] == "native-stable-candidate" for row in selected),
                        "spread_includes_all_source_rows_even_invalid": True,
                        "metrics": {metric: {"min": min(values), "mean": statistics.mean(values), "median": statistics.median(values), "max": max(values)}
                                    for metric in metrics if (values := [row[metric] for row in group if row.get(metric) is not None])}})
    (publish.OUTPUT / "repeat-spread.json").write_text(json.dumps(spreads, indent=2))
    attempts = []
    for manifest_path in sorted(run.RAW.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        result_path = manifest_path.parent / "steady.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        errors = [publish.redact(path.read_text()) for name in ("controller-error.txt", "analysis-error.txt") if (path := manifest_path.parent / name).exists()]
        attempts.append({"run_id": manifest_path.parent.name, "requested_population": manifest.get("requested_bots"),
                         "workload": manifest.get("behavior"), "requested_duration_s": manifest.get("duration"),
                         "started_utc": manifest.get("started_utc"), "ended_utc": manifest.get("ended_utc"),
                         "classification": result.get("classification", "not_yet_classified"), "scored_300s_window_present": result.get("window_s") == 300,
                         "retained_errors": errors, "raw_asset_relative_location": str(manifest_path.parent.relative_to(run.ROOT))})
    (publish.OUTPUT / "attempt-inventory.json").write_text(json.dumps(attempts, indent=2))
    sensitivity = {str(ccu): {str(kib): {"decimal": economics.forecast(kib * 1024, ccu), "binary_sensitivity": economics.forecast(kib * 1024, ccu, binary=True)} for kib in (5, 15, 30)} for ccu in (100, 1000)}
    (publish.OUTPUT / "unmeasured-cost-sensitivity.json").write_text(json.dumps({"status": "[MEASURE] hypothetical rates; unmeasured fan-out and capacity; not a forecast from 50-player preflight", "rows": sensitivity}, indent=2))
    print("Scored summary rows:", len(rows))


if __name__ == "__main__":
    main()
