"""Offline trajectories and qualified static disassembly correlation; no remote calls."""
import collections
import json
import math
import pathlib
import re

import udp_capacity150_analysis as base

NS = 10**9


def sockets(text):
    """Keep transient cgroup-owned rows without inventing a process identity."""
    result = []
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        if 'omega-' not in line:
            continue
        owner = re.search(r'users:\(\("([^"]+)",pid=(\d+),fd=(\d+)\)\)', line)
        inode = re.search(r'ino:(\d+)', line)
        memory = re.search(r'skmem:\(([^)]+)\)', lines[index+1])
        if not inode or not memory:
            raise ValueError('Socket memory or inode absent')
        if not owner and not re.search(r'cgroup:/system.slice/omega-[^ ]+-swarm.service', line):
            raise ValueError('Socket lacks process or owned swarm cgroup')
        result.append(dict({k:int(v) for k,v in re.findall(r'([a-z]+)(\d+)',memory[1])},
                           pid=int(owner[2]) if owner else None, inode=int(inode[1]),
                           comm=owner[1] if owner else None))
    return result


def disassembly(directory, sample_count):
    text = (directory/'poll-annotate.txt').read_text()
    match = re.search(r'\((\d+) samples, percent: local period\)', text)
    start = re.search(r'([0-9a-f]+) <omega_load_test::bot::Bot::poll>:', text)
    if not match or not start:
        raise ValueError('Missing poll annotation count or symbol start')
    count, address = int(match[1]), int(start[1], 16)
    rows = []
    for line in text.splitlines():
        m = re.match(r'\s*([\d.]+)\s*:\s*([0-9a-f]+):\s*(.*)', line)
        if m:
            rows.append((int(m[2], 16)-address, float(m[1]), m[3]))
    selected = [r for r in rows if 0x16c0 <= r[0] < 0x171c]
    instructions = '\n'.join(r[2] for r in selected)
    if not all(s in instructions for s in ('ldurh', '#0x753', 'lsr', '#4')):
        raise ValueError('Owner iterator instruction signature changed')
    hits = sum(round(percent*count/100) for _, percent, _ in selected)
    return {'kind': 'static disassembly/source correlation, no DWARF source-line attribution',
            'relative_range': ['+0x16c0', '+0x171c exclusive'],
            'poll_symbol_samples': count, 'all_profile_samples': sample_count,
            'samples_reconstructed_from_rounded_local_period_percent': hits,
            'percent_of_all_samples': 100*hits/sample_count,
            'evidence': 'Four-byte map entries, two u16 loads, owner shifted right four and compared with 0x753; subsequent path checks reported-projectile membership and entities. Frozen scan_for_monster_hits owner filter matches.',
            'limitations': ['Only iterator/filter subset, not complete scan or all Bot::poll',
                            'Sample reconstruction uses rounded local-period annotation',
                            'Owner-map occupancy and serial poll-cycle duration uninstrumented',
                            'No debug_info; no invented inline source samples']}


def trajectories(directory, phase, private):
    bots = base.rows(directory/'bots/bots.ndjson')
    ticks = base.csvrows(directory/'game/ticks.csv')
    host = {r: base.rows(directory/r/'host.ndjson.gz') for r in ('game', 'bots')}
    mapping = {r: base.csvrows(directory/r/'port-bot.csv') for r in host}
    wire = {r: collections.Counter() for r in host}
    flows = {}
    for role in host:
        for row in base.csvrows(directory/role/'input-ports.csv'):
            wire[role][row['utc_second'], row['port']] += row['input_commands']
        flows[role] = {r['utc_second']: r for r in base.csvrows(directory/role/'flow-points.csv')}
    result = []
    for a, b in zip(bots, bots[1:]):
        before = {v['id']: v for v in a['bots']}
        dt = (b['mono_ns']-a['mono_ns'])/NS
        values = [(before[v['id']], v) for v in b['bots'] if v['id'] in before]
        sec = b['utc_ns']//NS-1
        row = {'start_ns': a['utc_ns'], 'end_ns': b['utc_ns'],
               'phase_end_s': (b['utc_ns']-phase)/NS, 'interval_s': dt,
               'offered_hz': base.dist([(v['inputs']-u['inputs'])/dt for u, v in values]),
               'missed_schedules': sum(v['missed_schedules']-u['missed_schedules'] for u, v in values),
               'input_gap_histogram': [sum(v['input_gaps'][i]-u['input_gaps'][i] for u, v in values) for i in range(8)],
               'wire_utc_second': sec, 'hosts': {}}
        ts = [t for t in ticks if a['utc_ns'] <= t['utc_ns'] < b['utc_ns']]
        row['authenticated'] = base.dist([t['authenticated'] for t in ts])
        row['tick_hz'] = len(ts)/((b['utc_ns']-a['utc_ns'])/NS)
        for role in host:
            pair = base.bracket(host[role], a['utc_ns'], b['utc_ns'])
            cpu = base.cpu_report.interval(*pair) if pair else None
            complete = base.bracket(bots, sec*NS, (sec+1)*NS)
            counts = [wire[role][sec, m['port']] for m in mapping[role]] if complete else []
            row['hosts'][role] = {'cpu_outer_bracket': cpu, 'wire_inputs_per_second': base.dist(counts),
                                 'flow': flows[role].get(sec)}
        result.append(row)
    private.write_text(json.dumps(result)+'\n')
    groups = []
    for lo, hi in [(math.floor((bots[0]['utc_ns']-phase)/NS),0),(0,25),(25,50),(50,60),(60,90),(90,120),(120,150),(150,180),
                   (180,205),(205,230),(230,270),(270,300),(300,330),(330,360)]:
        rows = [r for r in result if lo < r['phase_end_s'] <= hi]
        groups.append({'phase_interval_s': [lo,hi], 'observations': len(rows),
                       'offered_hz_interval_medians': base.dist([r['offered_hz']['median'] for r in rows]),
                       'missed_schedules': sum(r['missed_schedules'] for r in rows) if rows else None,
                       'input_gap_histogram': [sum(r['input_gap_histogram'][i] for r in rows) for i in range(8)] if rows else None,
                       'bot_cpu_percent_one_core': base.dist([(r['hosts']['bots']['cpu_outer_bracket'] or {}).get('process_cpu_percent_one_core') for r in rows]),
                       'wire_input_interval_medians': {role: base.dist([r['hosts'][role]['wire_inputs_per_second']['median'] for r in rows]) for role in host}})
    return {'semantics': 'Adjacent approximately one-second cumulative bot observations; groups use end timestamps, not exact window counters. Wire uses the preceding complete UTC second. Full rows private; profile on/off exact window aggregates remain separate.',
            'groups': groups}
