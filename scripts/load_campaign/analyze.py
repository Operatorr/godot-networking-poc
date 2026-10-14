#!/usr/bin/env python3
"""Derive steady-window observations; keep harness criteria separate from campaign gates."""
import collections
import contextlib
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
import packet_store

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "deployment/hetzner/results/campaign-20261013"
SOURCE_BYTES = pathlib.Path(__file__).read_bytes()
ANALYZER_SOURCE_SHA256 = hashlib.sha256(SOURCE_BYTES).hexdigest()


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
            swap = re.search(r"VmSwap:\s+(\d+)", process["status"])
            result[pid] = {"cpu_ticks": int(stat[11]) + int(stat[12]), "rss_bytes": int(stat[21]) * observation.get("page_size", 4096),
                           "swap_kib": int(swap[1]) if swap else None, "state": stat[0]}
    return result


def cpu_delta(start, end):
    first, last = ticks_cpu(start), ticks_cpu(end)
    duration = (end["monotonic_ns"] - start["monotonic_ns"]) / 1e9
    result = {"duration_s": duration, "process_cpu_percent_one_core": None}
    common = first.keys() & last.keys()
    if common:
        result["process_cpu_percent_one_core"] = sum(last[pid]["cpu_ticks"] - first[pid]["cpu_ticks"] for pid in common) / duration * 100 / start.get("clock_ticks_s", 100)
        result["process_end_states"] = {pid: last[pid]["state"] for pid in common}
        result["rss_end_bytes"] = sum(last[pid]["rss_bytes"] for pid in common) if all(last[pid]["state"] != "Z" for pid in common) else None
        result["swap_end_kib"] = sum(last[pid]["swap_kib"] for pid in common) if all(last[pid]["swap_kib"] is not None for pid in common) else None
        if any(last[pid]["state"] == "Z" for pid in common):
            result["endpoint_process_note"] = "Process exited during endpoint observation; zombie CPU totals retained, endpoint resident/swap memory unavailable. Swarm cgroup CPU supplies the matched generator total."
    def cgroup_cpu(observation):
        if observation.get("swarm_cgroup_cpu"):
            return int(dict(line.split() for line in observation["swarm_cgroup_cpu"].splitlines())["usage_usec"]) * 1000
        text = observation.get("swarm_systemd_cpu_ns", {}).get("stdout", "").strip()
        return int(text) if text.isdigit() else None
    first_cgroup, last_cgroup = cgroup_cpu(start), cgroup_cpu(end)
    if first_cgroup is not None and last_cgroup is not None:
        result["swarm_cgroup_cpu_percent_one_core"] = (last_cgroup - first_cgroup) / duration / 1e7
        result["swarm_cgroup_cpu_semantics"] = "Swarm unit (bot process plus tiny shell wrapper), matched boundaries; final systemd value if process exited during boundary observation"
    a = [int(value) for value in start["stat"].splitlines()[0].split()[1:]]
    b = [int(value) for value in end["stat"].splitlines()[0].split()[1:]]
    delta = [y - x for x, y in zip(a, b)]
    result["steal_percent"] = 100 * delta[7] / max(1, sum(delta[:8]))
    result["busy_percent_all_cores"] = 100 * (sum(delta[:8]) - delta[3] - delta[4]) / max(1, sum(delta[:8]))
    result["per_core"] = {}
    first_cores = {line.split()[0]: [int(value) for value in line.split()[1:]] for line in start["stat"].splitlines() if re.match(r"cpu\d", line)}
    last_cores = {line.split()[0]: [int(value) for value in line.split()[1:]] for line in end["stat"].splitlines() if re.match(r"cpu\d", line)}
    for name, values in first_cores.items():
        changed = [last_value - value for value, last_value in zip(values, last_cores[name])]
        total = max(1, sum(changed[:8]))
        result["per_core"][name] = {"busy_percent": 100 * (sum(changed[:8]) - changed[3] - changed[4]) / total,
                                    "steal_percent": 100 * changed[7] / total}
    def snmp(observation):
        lines = observation["net/snmp"].splitlines()
        return {names.split()[0].rstrip(":"): dict(zip(names.split()[1:], map(int, values.split()[1:]))) for names, values in zip(lines[::2], lines[1::2])}
    first_snmp, last_snmp = snmp(start), snmp(end)
    result["kernel_udp_delta"] = {name: last_snmp["Udp"][name] - value for name, value in first_snmp["Udp"].items() if name != "InCsumErrors" or name in last_snmp["Udp"]}
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


def packet_observations(stream, start, end, margin_ns=2_000_000_000, context=None, track_outstanding=True):
    result = {direction: {"packets": 0, "ip_bytes": 0, "reliable_retry_command_bytes": 0,
                          "reliable_retry_payload_bytes": 0, "reliable_commands": 0, "acks": 0,
                          "outstanding_commands_end": 0} for direction in ("out", "in")}
    reliable = {direction: {} for direction in result}
    reliable_order = {direction: collections.deque() for direction in result}
    outstanding = {direction: set() for direction in result}
    latest_sequences = {direction: {} for direction in result}
    context = context or {direction: packet_store.MemoryContext() for direction in result}
    input_counts = collections.Counter()
    first_message_counts = {direction: collections.Counter() for direction in result}
    first_payload_bytes = {direction: 0 for direction in result}
    end_outstanding = None
    last_stamp = maximum_backstep = 0
    first_stamp = None
    def extend(direction, port, channel, sequence):
        old = latest_sequences[direction].get((port, channel), sequence)
        difference = (sequence - old + 32768) % 65536 - 32768
        extended = old + difference
        latest_sequences[direction][port, channel] = max(old, extended)
        return extended
    for stamp, source, target, ip_len, udp_len, fingerprint, commands in records(stream):
        if first_stamp is None:
            first_stamp = stamp
        maximum_backstep = max(maximum_backstep, last_stamp - stamp)
        last_stamp = stamp
        if end_outstanding is None and stamp >= end:
            end_outstanding = {direction: len(values) for direction, values in outstanding.items()}
        direction = "out" if source == 8081 else "in"
        port = target if source == 8081 else source
        # Retry classification only consults the previous 60 seconds. Keep one
        # additional second for capture timestamp reordering; larger backsteps
        # invalidate chronology rather than consuming unbounded memory.
        order = reliable_order[direction]
        while order and order[0][0] < stamp - 61_000_000_000:
            old_stamp, old_key = order.popleft()
            if reliable[direction].get(old_key) == old_stamp:
                del reliable[direction][old_key]
        included = start <= stamp < end
        if start - margin_ns <= stamp < end + margin_ns:
            context[direction].add((source, target, udp_len, fingerprint), stamp)
        if included:
            result[direction]["packets"] += 1
            result[direction]["ip_bytes"] += ip_len
        for command in commands:
            kind, channel = command[0] & 15, command[1]
            sequence, related, payload_length = struct.unpack_from(">HHH", command, 2)
            fragment = struct.unpack_from(">I", command, 8)[0]
            if included and kind == 7:
                first_message_counts[direction][command[12]] += 1
                first_payload_bytes[direction] += payload_length
            if included and direction == "in" and command[12] == 2 and kind in (6, 7) and payload_length == 22:
                input_counts[port] += 1
            if kind == 1:
                reverse = "in" if direction == "out" else "out"
                if track_outstanding:
                    related = extend(reverse, port, channel, related)
                    outstanding[reverse].discard((port, channel, related))
                if included:
                    result[direction]["acks"] += 1
            elif command[0] & 0x80 and kind in (6, 8):
                sequence = extend(direction, port, channel, sequence)
                key = port, channel, sequence
                previous = reliable[direction].get(key)
                if included:
                    result[direction]["reliable_commands"] += 1
                    if previous is not None and stamp - previous < 60_000_000_000:
                        result[direction]["reliable_retry_command_bytes"] += {2: 48, 3: 44, 4: 8, 5: 4, 6: 6, 8: 24, 10: 12, 11: 16}.get(kind, 4) + payload_length
                        result[direction]["reliable_retry_payload_bytes"] += payload_length
                    else:
                        first_payload_bytes[direction] += payload_length
                        if kind == 6 or fragment == 0:
                            first_message_counts[direction][command[12]] += 1
                reliable[direction][key] = stamp
                order.append((stamp, key))
                if track_outstanding:
                    outstanding[direction].add(key)
        if stamp >= end + margin_ns:
            break
    for direction in result:
        result[direction]["outstanding_commands_end"] = (end_outstanding or {direction: len(outstanding[direction])})[direction] if track_outstanding else None
        result[direction]["first_message_counts_by_type"] = dict(first_message_counts[direction])
        result[direction]["first_transmission_payload_bytes"] = first_payload_bytes[direction]
    result["wire_input_counts_by_port"] = dict(input_counts)
    result['max_timestamp_backstep_ns'] = maximum_backstep
    result['capture_first_timestamp_ns'] = first_stamp
    result['capture_last_timestamp_ns'] = last_stamp if first_stamp is not None else None
    result['outstanding_semantics'] = 'Observed reliable data commands without returning ACK at the endpoint boundary; not unsent ENet queues' if track_outstanding else 'Unavailable: egress-only mirror does not observe the returning ACK path'
    return result, context


def capture_covers_window(packets, start, end):
    """Collector chronology gate shared by endpoint and prequeue observations."""
    first, last = packets.get('capture_first_timestamp_ns'), packets.get('capture_last_timestamp_ns')
    return (first is not None and last is not None and first <= start
            and last >= end - 100_000_000
            and packets['max_timestamp_backstep_ns'] <= 1_000_000_000)


def summarize(directory):
    with contextlib.ExitStack() as resources:
        store = resources.enter_context(packet_store.PacketStore())
        return _summarize(directory, store, resources)


def _summarize(directory, store, resources):
    manifest = json.loads((directory / "manifest.json").read_text())
    result = dict(manifest)
    result["derived_source_sha256"] = ANALYZER_SOURCE_SHA256
    result['derived_support_sources_sha256'] = {'packet_store.py': packet_store.SOURCE_SHA256}
    result.pop("command", None)
    result["archive_sha256"] = {}
    for name in directory.glob("*.tar.gz"):
        with name.open('rb') as evidence:
            result["archive_sha256"][name.name] = hashlib.file_digest(evidence, 'sha256').hexdigest()
    if not (directory / "window.json").exists():
        result["classification"] = "collector-invalid"
        return result
    window = json.loads((directory / "window.json").read_text())
    duration = (window["end"] - window["start"]) / 1e9
    result["window_s"] = duration
    archives = {role: resources.enter_context(tarfile.open(directory / (role + ".tar.gz"))) for role in ("game", "bots")}

    def load(role, name):
        return json.load(archives[role].extractfile(role + "/" + name))

    collector_valid = True
    flow_sets = {}
    prequeue_sets = {}
    for role, archive in archives.items():
        names = archive.getnames()
        external_bot = role == "bots" and "Operator Mac" in manifest.get("topology", "")
        try:
            if external_bot:
                result[role + "_host"] = {"duration_s": duration, "semantics": "Operator Mac process observations retained in operator-host.ndjson; socket capture has synthetic IPv4 headers and no NIC/kernel capture counters"}
            else:
                result[role + "_host"] = cpu_delta(load(role, "start.json"), load(role, "end.json"))
        except (KeyError, ValueError) as error:
            result[role + "_boundary_error"] = str(error)
            collector_valid = False
        if not external_bot and role + "/host.ndjson.gz" in names:
            host_samples = []
            with gzip.GzipFile(fileobj=archive.extractfile(role + "/host.ndjson.gz")) as observations:
                for line in observations:
                    sample = json.loads(line)
                    if window["start"] <= sample["utc_ns"] < window["end"]:
                        host_samples.append(sample)
            rss = [sum(process["rss_bytes"] for process in ticks_cpu(sample).values() if process["state"] != "Z") for sample in host_samples]
            result.setdefault(role + "_host", {})["sampled_process_peak_rss_bytes"] = max(rss) if rss else None
            result[role + "_host"]["steady_host_sample_count"] = len(host_samples)
        if role + "/capture.log" in names:
            text = archive.extractfile(role + "/capture.log").read().decode()
            drops = re.search(r"(\d+) packets dropped by kernel", text)
            parse_errors = re.search(r"parse_errors=(\d+)", text)
            result[role + "_capture_kernel_drops"] = int(drops[1]) if drops else None
            result[role + "_flow_parse_errors"] = int(parse_errors[1]) if parse_errors else None
            collector_valid &= external_bot or bool(drops and int(drops[1]) == 0)
        if role + "/datagrams.bin" in names:
            packets, fingerprints = packet_observations(archive.extractfile(role + "/datagrams.bin"), window["start"], window["end"], context=store.contexts())
            if role + "/flow-summary.json" in names:
                packets = load(role, 'flow-summary.json')
                collector_valid &= packets.get('window') == window and packets.get('schedule_observed_utc_ns', window['start'] + 1) <= window['start']
                packets['out']['first_message_counts_by_type'] = {int(k): v for k, v in packets['out']['first_message_counts_by_type'].items()}
                packets['in']['first_message_counts_by_type'] = {int(k): v for k, v in packets['in']['first_message_counts_by_type'].items()}
            elif manifest.get('collection_format') == 'article-points-v1':
                collector_valid = False
            result[role + "_packets"] = packets
            flow_sets[role] = fingerprints
            collector_valid &= result.get(role + "_flow_parse_errors") == 0
            collector_valid &= capture_covers_window(packets, window['start'], window['end'])
        if role + "/prequeue/datagrams.bin" in names:
            text = archive.extractfile(role + "/prequeue/capture.log").read().decode()
            drops = re.search(r"(\d+) packets dropped by kernel", text)
            parse_errors = re.search(r"parse_errors=(\d+)", text)
            result[role + "_prequeue_capture_drops"] = int(drops[1]) if drops else None
            result[role + "_prequeue_parse_errors"] = int(parse_errors[1]) if parse_errors else None
            collector_valid &= bool(drops and parse_errors and int(drops[1]) == 0 and int(parse_errors[1]) == 0)
            packets, fingerprints = packet_observations(archive.extractfile(role + "/prequeue/datagrams.bin"), window["start"], window["end"], context=store.contexts(), track_outstanding=False)
            if role + "/prequeue/flow-summary.json" in names:
                packets = load(role, 'prequeue/flow-summary.json')
                collector_valid &= packets.get('window') == window and packets.get('schedule_observed_utc_ns', window['start'] + 1) <= window['start']
                for direction in ('out', 'in'):
                    packets[direction]['first_message_counts_by_type'] = {int(k): v for k, v in packets[direction]['first_message_counts_by_type'].items()}
            elif manifest.get('collection_format') == 'article-points-v1':
                collector_valid = False
            result[role + "_prequeue_packets"] = packets
            prequeue_sets[role] = fingerprints
            collector_valid &= capture_covers_window(packets, window['start'], window['end'])
        if role == "game":
            start_prom = exposition(load(role, "start.json").get("prometheus", ""))
            end_prom = exposition(load(role, "end.json").get("prometheus", ""))
            count = end_prom.get("tick_duration_ms_count", 0) - start_prom.get("tick_duration_ms_count", 0)
            result["exporter_tick_count"] = count
            result["exporter_tick_mean_ms"] = (end_prom.get("tick_duration_ms_sum", 0) - start_prom.get("tick_duration_ms_sum", 0)) / count if count else None
            result["exporter_tick_hz"] = count / duration
    if len(flow_sets) == 2:
        store.prepare()
        result["directional_loss"] = {}
        for direction in ("out", "in"):
            sender_role = "game" if direction == "out" else "bots"
            sender = prequeue_sets.get(sender_role, flow_sets[sender_role])[direction]
            receiver = flow_sets["bots" if direction == "out" else "game"][direction]
            result["directional_loss"][direction] = store.match(sender, receiver, window['start'], window['end'])
            if manifest.get('collection_format') == 'article-points-v1':
                result['directional_loss'][direction].update(sample_modulus=64, estimate=True,
                    uncertainty='Deterministic fingerprint sample; identical retransmissions are correlated. No independent-packet confidence interval or exact zero-loss claim.')
            result['directional_loss'][direction]['semantics'] = "sender pre-qdisc mirror when available (otherwise post-qdisc capture); timestamped full-UDP fingerprints matched to receiver ±2 ms/+2 s context; host clocks; signed, uncorrected timestamp differences include clock offset (negative sub-ms values are not negative network latency)"
    if "Operator Mac" in manifest.get("topology", ""):
        for observation in result.get("directional_loss", {}).values():
            uncertainty = manifest.get('external_clock_uncertainty_ms', 35.746)
            observation["semantics"] += f"; external receiver/sender observations are socket timestamps, operator clock uncertainty ±{uncertainty} ms; unmatched rates cannot independently distinguish internet loss from operator NIC/kernel loss"
    if manifest.get("profile", "native") != "native" and len(prequeue_sets) != 2:
        collector_valid = False
        result["collector_missing"] = "Pre-qdisc directional observations; post-qdisc matching cannot measure injected drops/delay"
    report = load("bots", "bot.json")
    result["legacy_harness"] = report["success_criteria"]
    result["legacy_aggregated"] = report["aggregated"]
    result["collector_valid"] = collector_valid
    game = archives["game"]
    if "game/ticks.csv" not in game.getnames():
        result["classification"] = "original-build-control-unscored" if manifest["build"] == "original" else "instrumented-build-recording-off-control-unscored" if manifest["build"] == "instrumented-off" else "collector-invalid"
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
    state_stamp = lambda row: int(row["utc_ns"]) + int(row["work_ns"])
    preceding = [row for row in all_ticks if state_stamp(row) < window["start"]]
    state = preceding[-1] if preceding else ticks[0]
    stamp = window["start"]
    population_ticks = [row for row in all_ticks if window["start"] <= state_stamp(row) < window["end"]]
    for row in population_ticks:
        delta = (state_stamp(row) - stamp) / 1e9
        population += delta * int(state["authenticated"])
        living += delta * int(state["alive"])
        state, stamp = row, state_stamp(row)
    population += (window["end"] - stamp) / 1e9 * int(state["authenticated"])
    living += (window["end"] - stamp) / 1e9 * int(state["alive"])
    result["authenticated_player_seconds"] = population
    result["alive_player_seconds"] = living
    result["alive_fraction"] = living / population if population else None
    result["population_min"] = min(int(row["authenticated"]) for row in ticks)
    result["population_max"] = max(int(row["authenticated"]) for row in ticks)
    for name in ("deferred", "max_queue_age", "budget_pct", "peers_evaluated", "overflow", "monsters", "projectiles", "effects", "mean_radius_sq", "pending_replication", "max_deferred_wait_ticks"):
        if name not in ticks[0]:
            continue
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
        for field in ("sent_bytes_by_type_channel", "received_bytes_by_type_channel"):
            first = dict(server_boundaries["start"][field]); last = dict(server_boundaries["end"][field])
            result["application_" + field] = {kind: [value - first.get(kind, [0, 0, 0])[index] for index, value in enumerate(values)] for kind, values in last.items()}
        result["server_send_errors"] = server_boundaries["end"]["send_errors"] - server_boundaries["start"]["send_errors"]
        result["server_decode_errors"] = server_boundaries["end"]["decode_errors"] - server_boundaries["start"]["decode_errors"]
        result["source_events_by_type"] = {index: value - server_boundaries["start"]["source_events"][index] for index, value in enumerate(server_boundaries["end"]["source_events"]) if value - server_boundaries["start"]["source_events"][index]}
        result["server_enqueued_snapshots"] = sum(server_boundaries["end"][field] - server_boundaries["start"][field] for field in ("baselines", "deltas"))
        result["expected_scheduled_snapshots"] = population * manifest.get("game_config", {}).get("snapshot_rate_hz", 30)
        emitted = result.get("game_prequeue_packets", result.get("game_packets", {})).get("out", {}).get("first_message_counts_by_type", {}).get(65)
        if emitted is not None:
            result["first_transmitted_snapshots_prequeue"] = emitted
            result["enqueued_minus_first_transmitted_snapshots"] = result["server_enqueued_snapshots"] - emitted
        result["snapshot_schedule_semantics"] = "Scheduled count uses authoritative player-seconds × configured Snapshot Hz; source ENet enqueues and first wire transmissions separate scheduling/suppression from network drops. Boundary crossings can differ by one per-peer scheduled burst."
        life_samples = [server_boundaries["start"]] + [sample for sample in server_samples
                       if not sample.get("boundary") and server_boundaries["start"]["utc_ns"] < sample["utc_ns"] < server_boundaries["end"]["utc_ns"]] + [server_boundaries["end"]]
        life_samples.sort(key=lambda sample: sample["utc_ns"])
        previous = {player[0]: player[1] for player in life_samples[0]["players"]}
        deaths = respawns = disconnects = 0
        for sample in life_samples[1:]:
            current = {player[0]: player[1] for player in sample["players"]}
            for entity, alive in current.items():
                if entity in previous:
                    deaths += int(previous[entity] and not alive)
                    respawns += int(not previous[entity] and alive)
            disconnects += len(previous.keys() - current.keys())
            previous = current
        maximum_gap = max((later["utc_ns"] - earlier["utc_ns"]) / 1e9 for earlier, later in zip(life_samples, life_samples[1:]))
        result["authoritative_life_transitions"] = {"player_deaths_observed": deaths, "player_respawns_observed": respawns,
                                                   "disconnects_observed": disconnects, "maximum_sample_gap_s": maximum_gap,
                                                   "semantics": "Per-player authoritative alive-state transitions, not global KILL events (which include monsters). 1 Hz observations and matched boundaries; bot respawn wait is 3.2 s. Event times lie between observations; gaps >=3.2 s can miss whole life cycles.",
                                                   "whole_cycle_aliasing_possible": maximum_gap >= 3.2}
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
        result["input_gap_histogram"] = [sum(bot["input_gaps"][i] - before[bot["id"]]["input_gaps"][i] for bot in last["bots"]) for i in range(8)]
        result["snapshot_gap_histogram"] = [sum(bot["snapshot_gaps"][i] - before[bot["id"]]["snapshot_gaps"][i] for bot in last["bots"]) for i in range(8)]
        generator_valid = result["generator"]["overall_hz"] >= 29.7 and min(rates) >= 29.7
    else:
        collector_valid = False
    sender = result.get("bots_prequeue_packets", result.get("bots_packets", {}))
    input_ports = sender.get("wire_input_counts_by_port", {})
    wire_rates = [count / duration for count in input_ports.values()]
    wire_gate = len(wire_rates) == manifest["requested_bots"] and min(wire_rates, default=0) >= 29.7
    result.setdefault("generator", {}).update(wire_input_ports_observed=len(wire_rates),
        wire_overall_input_hz=sum(input_ports.values()) / duration / manifest["requested_bots"],
        minimum_wire_port_input_hz=min(wire_rates, default=None), wire_offered_load_gate=wire_gate)
    kernel_error_names = ("RcvbufErrors", "SndbufErrors", "MemErrors", "InErrors")
    for role in ("game", "bots"):
        errors = result.get(role + "_host", {}).get("kernel_udp_delta", {})
        result[role + "_kernel_udp_errors"] = {name: errors[name] for name in kernel_error_names if errors.get(name, 0) > 0}
    result["generator"]["kernel_udp_validation_semantics"] = "Whole-host UDP error deltas on the isolated bot endpoint; positive errors require raw socket-table diagnosis. External Mac NIC/kernel counters unavailable; external accounting is not capacity evidence."
    generator_valid = generator_valid and wire_gate and not result["bots_kernel_udp_errors"]
    result["collector_valid"] = collector_valid
    result["generator_valid"] = generator_valid
    flow = result.get("game_host", {}).get("flow", {}).get("game_out", {})
    wire = result.get("game_packets", {}).get("out", flow)
    wire_bytes = wire.get("ip_bytes", flow.get("bytes", 0))
    result["outbound_ip_bytes"] = wire_bytes
    result["outbound_ip_bytes_s"] = wire_bytes / duration
    result["outbound_ip_bytes_player_s"] = wire_bytes / population if population else None
    result["outbound_ip_packets_s"] = wire.get("packets", 0) / duration
    result["offered_outbound_ip_bytes_nft_prequeue"] = flow.get("bytes")
    result["outbound_counter_semantics"] = "Post-qdisc game-port capture IP lengths over the common UTC window; nftables output counters are pre-qdisc offered bytes. Native counter differences also reflect read-time brackets. Interface bytes are separate."
    agg = report["aggregated"]
    wait = result.get("max_deferred_wait_ticks")
    growing_backlog = bool(wait and wait["last_30s_mean"] > wait["first_30s_mean"] + 30 and wait["max"] > 60)
    result["growing_replication_backlog"] = growing_backlog
    sustainability = (result["population_min"] == manifest["requested_bots"] and agg["disconnected_bots"] == 0
                      and agg["total_decode_failures"] == 0 and agg["total_send_failures"] == 0 and agg["total_panics"] == 0
                      and result.get("server_send_errors") == 0 and result.get("server_decode_errors") == 0
                      and result["tick_hz"] >= 29.7 and result["tick_work_ms"]["p99"] < 1000 / 30
                      and result["tick_lag_ms"]["end"] < 100 and not growing_backlog and not result["game_kernel_udp_errors"])
    result["server_sustainability_gate"] = sustainability
    result["classification"] = "collector-invalid" if not collector_valid else "generator-invalid" if not generator_valid else "native-stable-candidate" if sustainability else "valid-failure"
    if manifest.get("profile", "native") != "native" and collector_valid and generator_valid:
        result["classification"] = "controlled-profile-valid" if sustainability else "controlled-profile-degradation"
    if "Operator Mac" in manifest.get("topology", "") and collector_valid and generator_valid:
        result["classification"] = "external-accounting-check-valid"
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
