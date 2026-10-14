#!/usr/bin/env python3
"""Offline report of the operator-authorized Strategy overload attempts."""
import csv
import gzip
import json
import pathlib

import cpu_report

REPORT = cpu_report.DEFAULT_REPORT
POPULATIONS = (200, 250, 500, 750, 999)


def records(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def receive_drop_onset(samples, ticks):
    """First host UDP receive-buffer increment, aligned with retained Tick points."""
    def count(sample):
        lines = sample['net/snmp'].splitlines()
        for names, values in zip(lines[::2], lines[1::2]):
            if names.startswith('Udp:'):
                return dict(zip(names.split()[1:], map(int, values.split()[1:])))['RcvbufErrors']
        raise ValueError('Missing UDP receive-buffer counter')

    for first, last in zip(samples, samples[1:]):
        delta = count(last) - count(first)
        if delta < 0:
            raise ValueError('UDP receive-buffer counter reset during retained run')
        if delta == 0:
            continue
        population = [int(tick['authenticated']) for tick in ticks
                      if first['utc_ns'] <= int(tick['utc_ns']) < last['utc_ns']]
        cpu = cpu_report.interval(first, last)
        return {'utc_start_ns': first['utc_ns'], 'utc_end_ns': last['utc_ns'],
                'seconds_from_first_host_sample': (first['utc_ns'] - samples[0]['utc_ns']) / 1e9,
                'receive_buffer_error_delta': delta,
                'game_cpu_percent_one_core': cpu['process_cpu_percent_one_core'],
                'authenticated_min': min(population) if population else None,
                'authenticated_max': max(population) if population else None,
                'scope': 'First positive host-wide UDP receive-buffer delta; one sample interval, not an exact drop instant or socket-specific attribution.'}
    return None


def update(report=REPORT, charts=True):
    rows, timelines, onsets = [], [], []
    for population in POPULATIONS:
        directory = report / f'core-strategy-{population}-r1'
        result_path = directory / 'agent-result.json'
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text())
        actual = result.get('actual_population') or {}
        with gzip.open(directory / 'game/ticks.csv.gz', 'rt') as stream:
            ticks = list(csv.DictReader(stream))
        row = {'requested_players': population, 'classification': result['classification'],
               'window_s': result.get('window_s'),
               'ramp_peak_authenticated': actual.get('ramp_peak_authenticated'),
               'steady_min': actual.get('steady_min'), 'steady_max': actual.get('steady_max'),
               'collector_valid': result.get('collector_valid'),
               'generator_valid': result.get('generator_valid'),
               'report': f'{directory.name}/agent-result.json'}
        timeline = {'directory': directory, 'population': population, 'result': result, 'hosts': {}}
        for role in ('game', 'bots'):
            samples = records(directory / role / 'host.ndjson.gz')
            if role == 'game':
                onsets.append({'run_id': directory.name, 'requested_players': population,
                               'first_receive_buffer_errors': receive_drop_onset(samples, ticks)})
            # Failed ramps have no scheduled common window. Derive only the retained
            # host interval; exclude long gaps from 1 Hz peaks exactly as CPU reports do.
            if result.get('window_s') is None:
                summary, points = cpu_report.summarize_host(samples, samples[0], samples[-1])
                scope = 'unscored startup/ramp through abort; varying population'
            else:
                start = json.loads((directory / role / 'start.json').read_text())
                end = json.loads((directory / role / 'end.json').read_text())
                summary, points = cpu_report.summarize_host(samples, start, end)
                scope = 'common scheduled measurement window'
            metric = 'swarm_cpu_percent_one_core' if role == 'bots' else 'process_cpu_percent_one_core'
            if not summary['one_second_statistics'][metric].get('sample_count'):
                metric = 'process_cpu_percent_one_core'
            stats = summary['one_second_statistics'][metric]
            row[role + '_cpu_scope'] = scope
            row[role + '_logical_cpus'] = summary['matched_boundary']['logical_cpus']
            row[role + '_host_mean_percent_capacity'] = summary['matched_boundary']['host_execution_percent_capacity']
            for key in ('p99', 'max'):
                row[role + '_host_' + key + '_percent_capacity'] = summary['one_second_statistics']['host_execution_percent_capacity'].get(key)
            row[role + '_host_mean_steal_percent_capacity'] = summary['matched_boundary']['steal_percent_capacity']
            for key in ('time_weighted_mean', 'p99', 'max', 'seconds_at_or_above_95_percent', 'covered_seconds'):
                row[role + '_cpu_' + key] = stats.get(key)
            for key in ('RcvbufErrors', 'SndbufErrors'):
                row[role + '_' + key] = (result.get(role.rstrip('s') + '_kernel_errors') or {}).get(key)
            # Bot result uses singular bot_kernel_errors; game stays game.
            timeline['hosts'][role] = {'points': points, 'metric': metric}
        near = next((point for point in timeline['hosts']['game']['points']
                     if point.get('usable_for_1hz_peaks') and
                     (point.get('process_cpu_percent_one_core') or 0) >= 95), None)
        near_population = [int(tick['authenticated']) for tick in ticks
                           if near and near['utc_start_ns'] <= int(tick['utc_ns']) < near['utc_end_ns']]
        row['first_game_cpu_ge95_authenticated_min'] = min(near_population) if near_population else None
        row['first_game_cpu_ge95_authenticated_max'] = max(near_population) if near_population else None
        row['bundle_bytes'] = sum((result.get('bundle_bytes') or {}).values())
        rows.append(row)
        timeline['players'] = records(directory / 'game/server.ndjson.gz')
        timelines.append(timeline)
    if not rows:
        return []
    (report / 'strategy-failure-onset.json').write_text(json.dumps(onsets, indent=2) + '\n')
    with (report / 'strategy-extension-summary.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    lines = ['# Strategy overload continuation', '',
             'The [lower-ladder checkpoint](PRE-STRATEGY-EXTENSION.md) was documented before these attempts. '
             'Each requested rung ran once in a separate subagent, sequentially on the same isolated hosts. '
             'The pinned binaries and original conditions were retained.', '',
             '| Requested | Outcome | Ramp peak authenticated | Measured seconds | Game CPU peak | Bot CPU peak | Game / bot receive-buffer errors |',
             '| ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        peak = lambda role: f"{row[role + '_cpu_max']:.2f}%" if row[role + '_cpu_max'] is not None else 'unavailable'
        lines.append(f"| {row['requested_players']} | [{row['classification']}]({row['report']}) | "
                     f"{row['ramp_peak_authenticated']} | {row['window_s'] if row['window_s'] is not None else 'unscored ramp'} | "
                     f"{peak('game')} | {peak('bots')} | {row['game_RcvbufErrors']} / {row['bots_RcvbufErrors']} |")
    lines += ['', 'CPU percentages use **100% = one logical CPU**. A two-vCPU host can reach 200% on this scale. '
              'Peaks are approximately one-second interval values, not instantaneous or tick-thread CPU. '
              'Near-95% duration is descriptive, not a pass gate. Failed-ramp CPU and kernel deltas cover differing startup/abort intervals '
              'and must not be compared as fixed-population steady measurements.', '',
              'A requested population is not an achieved load. A ramp failure has no five-minute result or steady input-cadence conclusion. '
              'CPU near one core together with UDP errors and lost players identifies an overload episode; it does not locate an exact sustainable ceiling. '
              'Strategy 100 remains the highest passing native rung in the preserved campaign state; the earlier offered-load failures remain unchanged.', '',
              '[Numeric comparison](strategy-extension-summary.csv) includes CPU coverage, means, p99, peaks and seconds ≥95%. '
              '[Dispatch ledger](strategy-extension-ledger.json) and each agent result retain outcome, errors, archive checksums and cleanup proof.', '']
    near_min = [row['first_game_cpu_ge95_authenticated_min'] for row in rows
                if row['first_game_cpu_ge95_authenticated_min'] is not None]
    near_max = [row['first_game_cpu_ge95_authenticated_max'] for row in rows
                if row['first_game_cpu_ge95_authenticated_max'] is not None]
    if near_min and near_max:
        lines += [f'Across these attempts, the first retained game CPU interval ≥95% coincided with '
                  f'**{min(near_min)}–{max(near_max)} authenticated players**, using the per-Tick population within that CPU interval. '
                  'This locates observed startup overload episodes; it is not a validated steady-player ceiling.', '']
    lines += [f'Retained endpoint bundles total **{sum(row["bundle_bytes"] for row in rows) / 2**20:.2f} MiB** '
              f'for {len(rows)} attempts, using the compact logging policy. '
              'The [extension audit](strategy-extension-audit.json) verifies bundle hashes, pinned provenance, '
              'redaction, actual per-Tick peaks and preservation of the original campaign state.', '',
              'The broader matrix’s network/transfer phases, external accounting and complete coverage audit remain pending. '
              'See the [operator closure and failure hypotheses](CAX11-CONCLUSION.md) for the accepted checkpoint scope and future comparison.', '']
    if (report / 'strategy-extension-final-cleanup.json').exists():
        lines += ['[Final cleanup](strategy-extension-final-cleanup.json) independently verified native idle endpoints, '
                  'restored update timers and stopped the temporary restoration watchdog timers.', '']
    if charts:
        plot(report, timelines)
        lines += ['![CPU and actual population during each attempt](strategy-extension-timelines.png)', '']
    (report / 'STRATEGY-EXTENSION.md').write_text('\n'.join(lines))
    return rows


def plot(report, timelines):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['svg.hashsalt'] = 'omega-strategy-extension-v1'
    fig, axes = plt.subplots(len(timelines), 2, figsize=(12, 2.7 * len(timelines) + .9), squeeze=False)
    for (cpu_ax, players_ax), timeline in zip(axes, timelines):
        population = timeline['population']
        player_rows = timeline['players']
        origin = min(point['utc_start_ns'] for host in timeline['hosts'].values() for point in host['points'])
        for role, host in timeline['hosts'].items():
            points = [p for p in host['points'] if p.get('usable_for_1hz_peaks') and p.get(host['metric']) is not None]
            cpu_ax.plot([(p['utc_end_ns'] - origin) / 1e9 for p in points], [p[host['metric']] for p in points], label=role)
        cpu_ax.axhline(100, color='black', linestyle='--', linewidth=.8)
        cpu_ax.set_ylabel(f'Requested {population}\nCPU (100% = one CPU)')
        cpu_ax.set_ylim(bottom=0, top=max(110, cpu_ax.get_ylim()[1])); cpu_ax.legend(fontsize=8); cpu_ax.grid(alpha=.2)
        players_ax.step([(p['utc_ns'] - origin) / 1e9 for p in player_rows], [len(p['players']) for p in player_rows], where='post')
        players_ax.set_ylabel('Authenticated players'); players_ax.set_ylim(bottom=0); players_ax.grid(alpha=.2)
        players_ax.set_title(timeline['result']['classification'], fontsize=10)
        for ax in (cpu_ax, players_ax):
            ax.set_xlabel('Seconds from first retained game-host CPU interval')
    fig.suptitle('Strategy continuation: CPU and achieved population')
    fig.text(.5, .006, 'Unscored ramp attempts include startup and abort. Requested populations are not steady achieved loads.\n'
             '1 Hz process/unit CPU sums threads; actual population comes from authoritative server samples.', ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .6 / fig.get_figheight(), 1, .96))
    fig.savefig(report / 'strategy-extension-timelines.png', dpi=160)
    svg = report / 'strategy-extension-timelines.svg'
    fig.savefig(svg, metadata={'Date': None})
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    plt.close(fig)


if __name__ == '__main__':
    print(f'Strategy extension results updated: {len(update())}')
