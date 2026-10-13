#!/usr/bin/env python3
"""Derive steady-window observations; keep harness criteria separate from campaign gates."""
import collections
import csv
import gzip
import hashlib
import io
import json
import math
import pathlib
import re
import statistics
import struct
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "deployment/hetzner/results/campaign-20261013"


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(len(values) * fraction) - 1)] if values else None


def nft(observation):
    result = {}
    text = observation.get("nft", {}).get("stdout", "")
    if text:
        for entry in json.loads(text).get("nftables", []):
            rule = entry.get("rule", {})
            if "comment" in rule:
                for expression in rule.get("expr", []):
                    if "counter" in expression:
                        result[rule["comment"]] = expression["counter"]
    return result


def exposition(text):
    result = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            key, value = line.rsplit(" ", 1)
            result[key] = float(value)
    return result


def ticks_cpu(observation):
    result = {}
    for pid, process in observation.get("processes", {}).items():
        if process["comm"] and process["comm"].startswith("omega-"):
            stat = process["stat"].split(")", 1)[1].split()
            result[pid] = {"cpu_ticks": int(stat[11]) + int(stat[12]), "rss_bytes": int(stat[21]) * 4096,
                           "swap_kib": int(re.search(r"VmSwap:\s+(\d+)", process["status"])[1])}
    return result


def cpu_delta(start, end):
    first, last = ticks_cpu(start), ticks_cpu(end)
    duration = (end["monotonic_ns"] - start["monotonic_ns"]) / 1e9
    result = {"duration_s": duration, "process_cpu_percent_one_core": None}
    common = first.keys() & last.keys()
    if common:
        result["process_cpu_percent_one_core"] = sum(last[pid]["cpu_ticks"] - first[pid]["cpu_ticks"] for pid in common) / duration
        result["rss_end_bytes"] = sum(last[pid]["rss_bytes"] for pid in common)
        result["swap_end_kib"] = sum(last[pid]["swap_kib"] for pid in common)
    a = [int(value) for value in start["stat"].splitlines()[0].split()[1:]]
    b = [int(value) for value in end["stat"].splitlines()[0].split()[1:]]
    delta = [y - x for x, y in zip(a, b)]
    result["steal_percent"] = 100 * delta[7] / max(1, sum(delta[:8]))
    result["busy_percent_all_cores"] = 100 * (sum(delta[:8]) - delta[3] - delta[4]) / max(1, sum(delta[:8]))
    result["interface"] = {name: int(end["interface"][name]) - int(start["interface"][name]) for name in start["interface"]}
    result["flow"] = {name: {kind: counter[kind] - nft(start)[name][kind] for kind in ("bytes", "packets")}
                      for name, counter in nft(end).items() if name in nft(start)}
    result["boundary_start_lateness_ms"] = (start["utc_ns"] - start["target_utc_ns"]) / 1e6
    result["boundary_end_lateness_ms"] = (end["utc_ns"] - end["target_utc_ns"]) / 1e6
    result["boundary_sample_duration_ms"] = [start["sample_duration_ns"] / 1e6, end["sample_duration_ns"] / 1e6]
    return result


def records(stream):
    if stream.read(4) != b"ORF1":
        raise ValueError("flow observation version")
    while True:
        header = stream.read(26)
        if not header:
            break
        if len(header) != 26:
            raise ValueError("partial flow header")
        stamp = struct.unpack_from("<Q", header)[0]
        source, target = struct.unpack_from(">HH", header, 8)
        ip_len, udp_len, fingerprint, count = struct.unpack_from("<HHQH", header, 12)
        commands = stream.read(count * 16)
        if len(commands) != count * 16:
            raise ValueError("partial command observations")
        yield stamp, source, target, ip_len, udp_len, fingerprint, [commands[i:i + 16] for i in range(0, len(commands), 16)]


def packet_observations(stream, start, end):
    result = {direction: {"packets": 0, "ip_bytes": 0, "reliable_retry_command_bytes": 0,
                          "reliable_retry_payload_bytes": 0, "reliable_commands": 0, "acks": 0,
                          "outstanding_commands_end": 0} for direction in ("out", "in")}
    fingerprints = {direction: collections.Counter() for direction in result}
    reliable = {direction: {} for direction in result}
    outstanding = {direction: set() for direction in result}
    for stamp, source, target, ip_len, udp_len, fingerprint, commands in records(stream):
        direction = "out" if source == 8081 else "in"
        port = target if source == 8081 else source
        included = start <= stamp < end
        if included:
            result[direction]["packets"] += 1
            result[direction]["ip_bytes"] += ip_len
            fingerprints[direction][(source, target, udp_len, fingerprint)] += 1
        for command in commands:
            kind, channel = command[0] & 15, command[1]
            sequence, related, payload_length = struct.unpack_from(">HHH", command, 2)
            fragment = struct.unpack_from(">I", command, 8)[0]
            key = port, channel, sequence, fragment if kind == 8 else 0
            if kind == 1:
                reverse = "in" if direction == "out" else "out"
                outstanding[reverse].discard((port, channel, related, 0))
                if included:
                    result[direction]["acks"] += 1
            elif command[0] & 0x80:
                # Sequence wraps are distinguished from retries by a bounded age. ENet's
                # maximum timeout is far below this; fragment keys use per-fragment seq.
                previous = reliable[direction].get(key)
                if included:
                    result[direction]["reliable_commands"] += 1
                    if previous is not None and stamp - previous < 60_000_000_000:
                        result[direction]["reliable_retry_command_bytes"] += {6: 6, 8: 24}.get(kind, 4) + payload_length
                        result[direction]["reliable_retry_payload_bytes"] += payload_length
                reliable[direction][key] = stamp
                outstanding[direction].add((port, channel, sequence, 0))
        if stamp >= end:
            break
    for direction in result:
        result[direction]["outstanding_commands_end"] = len(outstanding[direction])
    return result, fingerprints


def summarize(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    result = dict(manifest)
    result.pop("command", None)
    result["archive_sha256"] = {name.name: hashlib.sha256(name.read_bytes()).hexdigest() for name in directory.glob("*.tar.gz")}
    if not (directory / "window.json").exists():
        result["classification"] = "collector-invalid"
        return result
    window = json.loads((directory / "window.json").read_text())
    duration = (window["end"] - window["start"]) / 1e9
    result["window_s"] = duration
    archives = {role: tarfile.open(directory / (role + ".tar.gz")) for role in ("game", "bots")}

    def load(role, name):
        return json.load(archives[role].extractfile(role + "/" + name))

    collector_valid = True
    flow_sets = {}
    for role, archive in archives.items():
        names = archive.getnames()
        try:
            result[role + "_host"] = cpu_delta(load(role, "start.json"), load(role, "end.json"))
        except (KeyError, ValueError) as error:
            result[role + "_boundary_error"] = str(error)
            collector_valid = False
        if role + "/capture.log" in names:
            text = archive.extractfile(role + "/capture.log").read().decode()
            drops = re.search(r"(\d+) packets dropped by kernel", text)
            parse_errors = re.search(r"parse_errors=(\d+)", text)
            result[role + "_capture_kernel_drops"] = int(drops[1]) if drops else None
            result[role + "_flow_parse_errors"] = int(parse_errors[1]) if parse_errors else None
            collector_valid &= bool(drops and int(drops[1]) == 0)
        if role + "/datagrams.bin" in names:
            packets, fingerprints = packet_observations(archive.extractfile(role + "/datagrams.bin"), window["start"], window["end"])
            result[role + "_packets"] = packets
            flow_sets[role] = fingerprints
            collector_valid &= result.get(role + "_flow_parse_errors") == 0
        if role == "game":
            start_prom = exposition(load(role, "start.json").get("prometheus", ""))
            end_prom = exposition(load(role, "end.json").get("prometheus", ""))
            count = end_prom.get("tick_duration_ms_count", 0) - start_prom.get("tick_duration_ms_count", 0)
            result["exporter_tick_count"] = count
            result["exporter_tick_mean_ms"] = (end_prom.get("tick_duration_ms_sum", 0) - start_prom.get("tick_duration_ms_sum", 0)) / count if count else None
            result["exporter_tick_hz"] = count / duration
    if len(flow_sets) == 2:
        result["directional_loss"] = {}
        for direction in ("out", "in"):
            sender = flow_sets["game" if direction == "out" else "bots"][direction]
            receiver = flow_sets["bots" if direction == "out" else "game"][direction]
            unmatched = sum((sender - receiver).values())
            extra = sum((receiver - sender).values())
            total = sum(sender.values())
            result["directional_loss"][direction] = {"sent": total, "matched": total - unmatched,
                                                      "unmatched": unmatched, "received_unmatched": extra,
                                                      "loss_upper_bound_pct": 100 * unmatched / total if total else None,
                                                      "semantics": "UTC-window multiset; boundary crossing is included in upper bound"}
    report = load("bots", "bot.json")
    result["legacy_harness"] = report["success_criteria"]
    result["legacy_aggregated"] = report["aggregated"]
    result["collector_valid"] = collector_valid
    game = archives["game"]
    if "game/ticks.csv" not in game.getnames():
        result["classification"] = "original-build-control-unscored"
        return result
    all_ticks = list(csv.DictReader(io.TextIOWrapper(game.extractfile("game/ticks.csv"))))
    ticks = [row for row in all_ticks if window["start"] <= int(row["utc_ns"]) < window["end"]]
    work = [int(row["work_ns"]) / 1e6 for row in ticks]
    result["tick_count"] = len(ticks)
    result["tick_hz"] = len(ticks) / duration
    result["tick_work_ms"] = {"mean": statistics.mean(work), "p50": percentile(work, .5), "p95": percentile(work, .95),
                              "p99": percentile(work, .99), "max": max(work), "exceed_33_333ms": sum(value >= 1000 / 30 for value in work)}
    result["observer_mean_ms"] = statistics.mean(int(row["observer_ns"]) / 1e6 for row in ticks)
    # Piecewise-constant authoritative post-Tick population. Boundary values come from
    # the last preceding Tick; startup/teardown never share the denominator.
    population = living = 0.0
    preceding = [row for row in all_ticks if int(row["utc_ns"]) < window["start"]]
    state = preceding[-1] if preceding else ticks[0]
    stamp = window["start"]
    for row in ticks:
        delta = (int(row["utc_ns"]) - stamp) / 1e9
        population += delta * int(state["authenticated"])
        living += delta * int(state["alive"])
        state, stamp = row, int(row["utc_ns"])
    population += (window["end"] - stamp) / 1e9 * int(state["authenticated"])
    living += (window["end"] - stamp) / 1e9 * int(state["alive"])
    result["authenticated_player_seconds"] = population
    result["alive_player_seconds"] = living
    result["alive_fraction"] = living / population if population else None
    result["population_min"] = min(int(row["authenticated"]) for row in ticks)
    result["population_max"] = max(int(row["authenticated"]) for row in ticks)
    for name in ("deferred", "max_queue_age", "budget_pct", "peers_evaluated", "overflow", "monsters", "projectiles", "effects", "mean_radius_sq"):
        values = [float(row[name]) for row in ticks]
        result[name] = {"mean": statistics.mean(values), "max": max(values), "first_30s_mean": statistics.mean(values[:900]),
                        "last_30s_mean": statistics.mean(values[-900:])}
    lag = [(int(row["utc_ns"]) - int(ticks[0]["utc_ns"])) / 1e9 - (int(row["tick"]) - int(ticks[0]["tick"])) / 30 for row in ticks]
    result["tick_lag_ms"] = {"end": lag[-1] * 1000, "max": max(lag) * 1000}
    server_samples = [json.loads(line) for line in game.extractfile("game/server.ndjson")]
    server_boundaries = {row.get("boundary"): row for row in server_samples if row.get("boundary")}
    result["server_boundary_lateness_ms"] = {name: (row["utc_ns"] - window[name]) / 1e6 for name, row in server_boundaries.items()}
    if set(server_boundaries) != {"start", "end"}:
        collector_valid = False
    else:
        result["application_sent_bytes_by_type_channel"] = {}
        for field in ("sent_bytes_by_type_channel", "received_bytes_by_type_channel"):
            first = dict(server_boundaries["start"][field]); last = dict(server_boundaries["end"][field])
            result["application_" + field] = {kind: [value - first.get(kind, [0, 0, 0])[index] for index, value in enumerate(values)] for kind, values in last.items()}
        result["server_send_errors"] = server_boundaries["end"]["send_errors"] - server_boundaries["start"]["send_errors"]
    bot_samples = [json.loads(line) for line in archives["bots"].extractfile("bots/bots.ndjson")]
    bot_boundaries = {row.get("boundary"): row for row in bot_samples if row.get("boundary")}
    generator_valid = False
    if set(bot_boundaries) == {"start", "end"}:
        first, last = bot_boundaries["start"], bot_boundaries["end"]
        bot_duration = (last["mono_ns"] - first["mono_ns"]) / 1e9
        before = {bot["id"]: bot for bot in first["bots"]}
        rates = [(bot["inputs"] - before[bot["id"]]["inputs"]) / bot_duration for bot in last["bots"]]
        result["generator"] = {"overall_hz": statistics.mean(rates), "minimum_bot_hz": min(rates),
                               "maximum_bot_hz": max(rates), "window_s": bot_duration,
                               "missed_schedules": sum(bot["missed_schedules"] - before[bot["id"]]["missed_schedules"] for bot in last["bots"])}
        for field in ("baseline_reference_misses", "unknown_delta_entities", "shoot_inputs", "ability_inputs", "snapshots", "baselines", "confirms"):
            result[field] = sum(bot[field] - before[bot["id"]][field] for bot in last["bots"])
        valid_samples = [sample for sample in bot_samples if first["mono_ns"] <= sample["mono_ns"] <= last["mono_ns"]]
        rtts = [bot["rtt_ms"] for sample in valid_samples for bot in sample["bots"] if bot["phase"] == "Running"]
        result["rtt_ms"] = {"mean": statistics.mean(rtts), "p95": percentile(rtts, .95), "p99": percentile(rtts, .99), "max": max(rtts)} if rtts else {}
        result["delivery"] = {field: {"mean": statistics.mean(values), "p99": percentile(values, .99), "max": max(values)}
                              for field in ("visible_entities", "snapshot_age_s", "delta_age_s", "confirm_age_s")
                              if (values := [bot[field] for sample in valid_samples for bot in sample["bots"] if bot[field] is not None])}
        result["per_bot_input_hz"] = rates
        generator_valid = result["generator"]["overall_hz"] >= 29.7 and min(rates) >= 29.7
    else:
        collector_valid = False
    result["collector_valid"] = collector_valid
    result["generator_valid"] = generator_valid
    flow = result.get("game_host", {}).get("flow", {}).get("game_out", {})
    result["outbound_ip_bytes"] = flow.get("bytes")
    result["outbound_ip_bytes_s"] = flow.get("bytes", 0) / result["game_host"]["duration_s"]
    result["outbound_ip_bytes_player_s"] = flow.get("bytes", 0) / population if population else None
    result["outbound_ip_packets_s"] = flow.get("packets", 0) / duration
    agg = report["aggregated"]
    sustainability = (result["population_min"] == manifest["requested_bots"] and agg["disconnected_bots"] == 0
                      and agg["total_decode_failures"] == 0 and agg["total_send_failures"] == 0 and agg["total_panics"] == 0
                      and result["tick_hz"] >= 29.7 and result["tick_work_ms"]["p99"] < 1000 / 30
                      and result["tick_lag_ms"]["end"] < 100)
    result["server_sustainability_gate"] = sustainability
    result["classification"] = "collector-invalid" if not collector_valid else "generator-invalid" if not generator_valid else "native-stable-candidate" if sustainability else "valid-failure"
    for archive in archives.values():
        archive.close()
    return result


def main():
    import sys
    for run_id in sys.argv[1:]:
        directory = RAW / run_id
        result = summarize(directory)
        (directory / "steady.json").write_text(json.dumps(result, indent=2))
        print(run_id, result["classification"], result.get("tick_hz"), result.get("generator"), result.get("outbound_ip_bytes_s"), flush=True)


if __name__ == "__main__":
    main()
