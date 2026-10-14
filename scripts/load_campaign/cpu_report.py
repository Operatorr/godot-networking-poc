#!/usr/bin/env python3
"""Derive CPU graph points from existing 1 Hz observations; no new host collection.

100% is one logical CPU for process/host-core-equivalent metrics. Host capacity
percent is normalized across all CPUs. Linux counters: docs.kernel.org/filesystems/proc.html.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import pathlib
import os
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / 'docs/netcode/perf-notes/load-test-reports/2026-10-14-one-pass'
SOURCE_SHA256 = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()


def cpu_counters(row):
    return {line.split()[0]: list(map(int, line.split()[1:9]))
            for line in row['stat'].splitlines() if line.split()[0].startswith('cpu')}


def process_counters(row):
    result = {}
    for pid, process in row.get('processes', {}).items():
        if not (process.get('comm') or '').startswith('omega-') or not process.get('stat'):
            continue
        fields = process['stat'].rsplit(')', 1)[1].split()
        # starttime prevents a reused PID from turning a new process into CPU delta.
        result[pid] = (int(fields[19]), int(fields[11]) + int(fields[12]))
    return result


def swarm_cpu_ns(row):
    if row.get('swarm_cgroup_cpu'):
        fields = dict(line.split() for line in row['swarm_cgroup_cpu'].splitlines())
        return int(fields['usage_usec']) * 1000
    value = row.get('swarm_systemd_cpu_ns', {}).get('stdout', '').strip()
    return int(value) if value.isdigit() else None


def interval(first, last):
    seconds = (last['monotonic_ns'] - first['monotonic_ns']) / 1e9
    if seconds <= 0:
        raise ValueError('Non-increasing monotonic CPU sample clock')
    a, b = cpu_counters(first), cpu_counters(last)
    cores = sorted(key for key in a if key != 'cpu')
    if a.keys() != b.keys() or not cores:
        raise ValueError('CPU topology changed or is absent')
    execution = {}
    for name in a:
        delta = [y - x for x, y in zip(a[name], b[name])]
        if len(delta) != 8 or any(value < 0 for value in delta) or sum(delta) <= 0:
            raise ValueError('CPU counters decreased or did not advance')
        # guest/guest_nice are already included in user/nice and are not added again.
        execution[name] = 100 * sum(delta[i] for i in (0, 1, 2, 5, 6)) / sum(delta)
    first_process, last_process = process_counters(first), process_counters(last)
    process_percent = None
    if first_process and first_process.keys() == last_process.keys() and all(
        first_process[pid][0] == last_process[pid][0] and last_process[pid][1] >= first_process[pid][1]
        for pid in first_process
    ):
        process_percent = sum(last_process[pid][1] - value[1] for pid, value in first_process.items()) / seconds / first['clock_ticks_s'] * 100
    start_swarm, end_swarm = swarm_cpu_ns(first), swarm_cpu_ns(last)
    swarm_percent = (end_swarm - start_swarm) / seconds / 1e7 if start_swarm is not None and end_swarm is not None and end_swarm >= start_swarm else None
    delta = [y - x for x, y in zip(a['cpu'], b['cpu'])]
    return {'utc_start_ns': first['utc_ns'], 'utc_end_ns': last['utc_ns'], 'interval_s': seconds,
            'logical_cpus': len(cores), 'process_cpu_percent_one_core': process_percent,
            'swarm_cpu_percent_one_core': swarm_percent,
            'host_execution_percent_capacity': execution['cpu'],
            'host_execution_percent_one_core': execution['cpu'] * len(cores),
            'busiest_core_execution_percent': max(execution[name] for name in cores),
            'steal_percent_capacity': 100 * delta[7] / sum(delta),
            **{name + '_execution_percent': execution[name] for name in cores}}


def percentiles(points, field):
    samples = [point for point in points if point.get(field) is not None and point.get('usable_for_1hz_peaks', True)]
    if not samples:
        return {'sample_count': 0}
    values = sorted(point[field] for point in samples)
    duration = sum(point['interval_s'] for point in samples)
    longest = current = 0.0
    previous_end = None
    for point in points:
        if previous_end is not None and point['utc_start_ns'] != previous_end:
            current = 0.0
        previous_end = point['utc_end_ns']
        if point.get(field) is not None and point.get('usable_for_1hz_peaks', True) and point[field] >= 95:
            current += point['interval_s']
            longest = max(longest, current)
        else:
            current = 0.0
    return {'sample_count': len(samples), 'covered_seconds': duration,
            'time_weighted_mean': sum(point[field] * point['interval_s'] for point in samples) / duration,
            'p95': values[math.ceil(.95 * len(values)) - 1],
            'p99': values[math.ceil(.99 * len(values)) - 1], 'max': values[-1],
            'seconds_at_or_above_95_percent': sum(point['interval_s'] for point in samples if point[field] >= 95),
            'longest_contiguous_seconds_at_or_above_95_percent': longest}


def summarize_host(samples, start, end):
    sequence = [start] + sorted((row for row in samples if start['utc_ns'] < row['utc_ns'] < end['utc_ns']), key=lambda row: row['utc_ns']) + [end]
    points, errors = [], []
    for first, last in zip(sequence, sequence[1:]):
        try:
            point = interval(first, last)
            point['usable_for_1hz_peaks'] = .5 <= point['interval_s'] <= 2.5
            points.append(point)
        except (ValueError, KeyError, IndexError) as error:
            errors.append({'utc_start_ns': first['utc_ns'], 'utc_end_ns': last['utc_ns'], 'reason': str(error)})
    metrics = ('process_cpu_percent_one_core', 'swarm_cpu_percent_one_core', 'host_execution_percent_capacity',
               'host_execution_percent_one_core', 'busiest_core_execution_percent', 'steal_percent_capacity')
    summary = {'matched_boundary': interval(start, end), 'interval_errors': errors,
               'one_second_statistics': {field: percentiles(points, field) for field in metrics},
               'semantics': '1 Hz interval statistics, not instantaneous peaks or repeat confidence intervals. Intervals outside 0.5–2.5 s are excluded from peaks/near-95% durations. 95% is a descriptive warning threshold, not proof of CPU saturation. Process CPU sums all threads; tick-thread CPU was not collected separately. Per-core CPU includes all processes on that core; the tick thread may migrate. Executing CPU excludes idle/iowait/steal; steal is reported separately.'}
    return summary, points


def report_case(directory):
    result = json.loads((directory / 'steady.json').read_text())
    output = {'run_id': result['run_id'], 'classification': result['classification'],
              'collector_valid': result.get('collector_valid'), 'generator_valid': result.get('generator_valid'),
              'requested_bots': result['requested_bots'], 'behavior': result['behavior'],
              'profile': result.get('profile', 'native'), 'variant': result.get('variant', 'native'),
              'cpu_report_source_sha256': SOURCE_SHA256, 'hosts': {}}
    for role in ('game', 'bots'):
        host = directory / role
        if not all((host / name).exists() for name in ('host.ndjson.gz', 'start.json', 'end.json')):
            continue
        with gzip.open(host / 'host.ndjson.gz', 'rt') as stream:
            samples = [json.loads(line) for line in stream]
        start, end = (json.loads((host / (name + '.json')).read_text()) for name in ('start', 'end'))
        summary, points = summarize_host(samples, start, end)
        output['hosts'][role] = summary
        if points:
            text = io.StringIO()
            writer = csv.DictWriter(text, fieldnames=list(points[0]), lineterminator='\n')
            writer.writeheader(); writer.writerows(points)
            with (host / 'cpu-timeseries.csv.gz').open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as stream:
                stream.write(text.getvalue().encode())
    error_path = directory / 'cpu-report-error.json'
    error_path.unlink(missing_ok=True)
    (directory / 'cpu-summary.json').write_text(json.dumps(output, indent=2) + '\n')
    return output


def update(report=DEFAULT_REPORT, charts=True):
    replacement_path = report / 'matrix-replacements.json'
    replacements = json.loads(replacement_path.read_text()) if replacement_path.exists() else {}
    rows = []
    for directory in sorted(report.iterdir()):
        if not directory.is_dir() or not (directory / 'steady.json').exists():
            continue
        try:
            metadata = json.loads((directory / 'steady.json').read_text())
            if metadata.get('window_s') != 300:
                continue
            result = report_case(directory)
        except (ValueError, KeyError, OSError, EOFError) as error:
            (directory / 'cpu-report-error.json').write_text(json.dumps({'error': str(error)}, indent=2))
            continue
        row = {key: result[key] for key in ('run_id', 'classification', 'requested_bots', 'behavior', 'profile', 'variant', 'collector_valid', 'generator_valid')}
        row['selected_for_matrix'] = directory.name not in replacements
        for role, summary in result['hosts'].items():
            boundary = summary['matched_boundary']
            metric = 'swarm_cpu_percent_one_core' if role == 'bots' and boundary['swarm_cpu_percent_one_core'] is not None else 'process_cpu_percent_one_core'
            row[role + '_process_mean_percent_one_core'] = boundary[metric]
            row[role + '_host_mean_percent_capacity'] = boundary['host_execution_percent_capacity']
            row[role + '_host_mean_percent_one_core'] = boundary['host_execution_percent_one_core']
            row[role + '_logical_cpus'] = boundary['logical_cpus']
            for name in ('p95', 'p99', 'max', 'seconds_at_or_above_95_percent', 'longest_contiguous_seconds_at_or_above_95_percent'):
                row[role + '_process_' + name] = summary['one_second_statistics'][metric].get(name)
            for target, metric_name in (('host_capacity', 'host_execution_percent_capacity'), ('host_one_core', 'host_execution_percent_one_core'), ('busiest_core', 'busiest_core_execution_percent')):
                for name in ('p99', 'max', 'seconds_at_or_above_95_percent'):
                    row[role + '_' + target + '_' + name] = summary['one_second_statistics'][metric_name].get(name)
        rows.append(row)
    if rows:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with (report / 'cpu-summary.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    if charts and rows:
        plot(report, rows)
        for name in ('core-combat-150-r1', 'core-strategy-150-r1'):
            directory = report / name
            if (directory / 'cpu-summary.json').exists():
                plot_timeline(directory)
    return rows


def plot(report, rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for ax, role, label in zip(axes, ('game', 'bots'), ('Game server process', 'Bot generator unit')):
        for behavior in ('movement', 'combat', 'clustered', 'strategy'):
            data = sorted((row for row in rows if row['selected_for_matrix'] and row['profile'] == 'native' and row['variant'] == 'native'
                           and (row['run_id'].startswith(('core-', 'boundary-')) or row['run_id'] == 'pilot-clustered-50-recovery') and row['behavior'] == behavior
                           and row.get(role + '_process_mean_percent_one_core') is not None and row['collector_valid']), key=lambda row: row['requested_bots'])
            if not data:
                continue
            valid = [row for row in data if row['classification'] == 'native-stable-candidate']
            invalid = [row for row in data if row['classification'] != 'native-stable-candidate']
            line, = ax.plot([row['requested_bots'] for row in valid], [row[role + '_process_mean_percent_one_core'] for row in valid], '-o', label=behavior)
            ax.scatter([row['requested_bots'] for row in invalid], [row[role + '_process_mean_percent_one_core'] for row in invalid], marker='x', s=65, color=line.get_color())
        ax.axhline(100, color='black', linestyle='--', linewidth=1, label='One logical CPU')
        ax.set_ylabel(f'{label}\nmean CPU (100% = one CPU)')
        ax.set_ylim(bottom=0)
        ax.grid(alpha=.2); ax.legend(ncol=3, fontsize=8)
    axes[-1].set_xlabel('Requested players')
    fig.suptitle('CAX11 measured CPU vs population — one observation per case')
    fig.text(.5, .01, '× = failed/invalid observation, not sustainable capacity. Averages after load collapses hide earlier CPU peaks.\nCPU includes all process threads; 1 Hz peaks/durations and host CPU are in cpu-summary.csv.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .07, 1, .96))
    fig.savefig(report / 'cpu-vs-population.png', dpi=160)
    fig.savefig(report / 'cpu-vs-population.svg')
    plt.close(fig)


def plot_timeline(directory):
    import matplotlib.pyplot as plt
    import datetime
    metadata = json.loads((directory / 'steady.json').read_text())
    window = json.loads((directory / 'window.json').read_text())
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for ax, role, label in zip(axes[:2], ('game', 'bots'), ('Game', 'Bot')):
        with gzip.open(directory / role / 'cpu-timeseries.csv.gz', 'rt') as stream:
            rows = list(csv.DictReader(stream))
        field = 'swarm_cpu_percent_one_core' if role == 'bots' else 'process_cpu_percent_one_core'
        rows = [row for row in rows if row[field] and row['usable_for_1hz_peaks'] == 'True']
        seconds = [(int(row['utc_end_ns']) - window['start']) / 1e9 for row in rows]
        ax.plot(seconds, [float(row[field]) for row in rows], label=label + ' process/unit')
        ax.plot(seconds, [float(row['host_execution_percent_one_core']) for row in rows], alpha=.65, label=label + ' entire host')
        ax.axhline(100, color='black', linestyle='--', linewidth=1, label='One logical CPU')
        ax.set_ylabel('CPU (100% = one CPU)'); ax.set_ylim(bottom=0); ax.legend(fontsize=8, loc='upper right'); ax.grid(alpha=.2)
    with gzip.open(directory / 'game/ticks.csv.gz', 'rt') as stream:
        ticks = [row for row in csv.DictReader(stream) if window['start'] <= int(row['utc_ns']) < window['end']]
    axes[2].plot([(int(row['utc_ns']) - window['start']) / 1e9 for row in ticks], [int(row['authenticated']) for row in ticks], label='Authenticated players', color='black')
    axes[2].axhline(metadata['requested_bots'], color='gray', linestyle=':', label='Requested players')
    axes[2].set_ylabel('Players'); axes[2].set_xlabel('Seconds into 300-second measurement'); axes[2].legend(fontsize=8); axes[2].grid(alpha=.2)
    begin = datetime.datetime.fromtimestamp(window['start'] / 1e9, datetime.timezone.utc).isoformat()
    fig.suptitle(f"{metadata['behavior'].title()} {metadata['requested_bots']} — {metadata['classification']}\nMeasurement start: {begin}")
    fig.text(.5, .01, 'Entire-host CPU includes OS and observation work. Failed offered-load validation prevents a sustainable capacity claim.\n1 Hz CPU averages cannot resolve sub-second CPU spikes; Tick work and UDP errors are separate evidence.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, .94))
    fig.savefig(directory / 'cpu-timeline.png', dpi=160); fig.savefig(directory / 'cpu-timeline.svg')
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=pathlib.Path, default=DEFAULT_REPORT)
    parser.add_argument('--no-charts', action='store_true')
    parser.add_argument('--watch-pid', type=int, help='Refresh completed reports until this local controller exits')
    args = parser.parse_args()
    signature = None
    while True:
        current = sorted((str(path), path.stat().st_mtime_ns) for name in ('steady.json', 'retained-evidence.json') for path in args.report.glob('*/' + name))
        if current != signature:
            rows = update(args.report, not args.no_charts)
            signature = current
            print(f'CPU reports updated: {len(rows)} completed observations', flush=True)
        if args.watch_pid is None:
            break
        try:
            os.kill(args.watch_pid, 0)
        except ProcessLookupError:
            update(args.report, not args.no_charts)
            break
        time.sleep(15)
