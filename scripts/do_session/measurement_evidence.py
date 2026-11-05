#!/usr/bin/env python3
"""Regenerate the compact measurement evidence for handoff slice 5 (issue #68).

Two very different things, kept apart on purpose:

  synthetic   the real prover over mocked recorder files. Byte-reproducible, and ``test_measurement_evidence`` regenerates it.
              A "60 s window" here is arithmetic, and nothing ran.
  real        real omega-server and omega-load-test processes on this machine in real time, from one exact build, summarized.
              Not reproducible byte for byte, because process ids and timings are real. Its SHA256SUMS only says these are the bytes retained.

Neither is a live-host validation or a capacity observation: two endpoints on one loopback, macOS with no socket drop counters, one wall clock.

    python3 measurement_evidence.py synthetic --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice5
    python3 measurement_evidence.py real --out ... --release DIR --fault-release DIR [--long]
"""
import argparse
import hashlib
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile

import measurement_fixtures as fx
import measurement_local as ml
import measurement_window as mw

NS = mw.NS
HERE = pathlib.Path(__file__).parent
REPO = HERE.parents[1]


def _drop_auth(tree):
    def change(rows):
        kept = [row for row in rows if not (row.get('k') == 'auth' and row.get('name') == 'LoadBot008')]
        for index, row in enumerate(kept):
            row['seq'] = index
        rows[:] = kept
    tree.edit_rows('game/telemetry/population.ndjson', change)
    tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] - 1))


def _tick_below_n(tree, offset_s):
    import csv
    path = tree.path('game/telemetry/ticks.csv')
    with path.open(newline='') as handle:
        rows = list(csv.reader(handle))
    target = fx.to_game_mono(tree.timeline.start) + int(offset_s * NS)
    for row in rows[1:]:
        if int(row[1]) >= target:
            row[4] = str(tree.timeline.target - 1)
            break
    with path.open('w', newline='') as handle:
        csv.writer(handle).writerows(rows)


def _step_clock(tree):
    def step(rows):
        for row in rows:
            clock = row.get('clock')
            if clock and clock['mono_ns'] >= tree.timeline.start + 10 * NS:
                clock['wall_before_ns'] += NS
                clock['wall_after_ns'] += NS
    tree.edit_rows('bot/swarm/coordinator.ndjson', step)


def _sampler(tree, role, edit):
    def change(rows):
        for index, row in enumerate(rows):
            edit(index, row)
    tree.edit_rows(role + '/sampler.ndjson', change)


def _cut(tree, relative):
    data = tree.path(relative).read_bytes()
    tree.path(relative).write_bytes(data[:len(data) // 2])


def _overwrite(tree, relative):
    def change(rows):
        for row in rows:
            row['nonce'] = 'another-process'
    tree.edit_rows(relative, change)


def _set_game_start(index, row):
    if index >= 25:
        row['procs']['game']['start_id'] = 'ticks:424242'


def _set_game_inode(index, row):
    if index >= 25:
        row['procs']['game']['sockets'][0]['inode'] = 'another'


def _rewind_game_drops(index, row):
    row['procs']['game']['sockets'][0]['drops'] = 5 if index < 25 else 1


def _drop_bot_counter(index, row):
    row['procs']['bot']['sockets'][0]['drops'] = None


def _bot_socket_drop(index, row):
    row['procs']['bot']['sockets'][2]['drops'] = 0 if index < 25 else 1


def _game_socket_drop(index, row):
    row['procs']['game']['sockets'][0]['drops'] = 0 if index < 25 else 7


# name, (options for Tree), how to break it, options for prove
SYNTHETIC = (
    ('complete_60s', dict(hold_s=60), None, {}),
    ('complete_300s', dict(hold_s=300), None, {}),
    ('short_hold_refused', dict(hold_s=5), None, {}),
    ('large_known_wall_offset_still_maps', dict(game_wall_offset=37 * NS), None, {}),
    ('warmup_violated', {}, lambda t: t.edit_json('bot/swarm/window.json', lambda d: d.update(final_auth_ns=t.timeline.start - NS)), {}),
    ('readiness_timeout_has_no_window', {}, lambda t: t.edit_json('bot/swarm/window.json', lambda d: d.update(status='not_established', reason='readiness_timeout', start_ns=None, end_ns=None)), {}),
    ('global_stagger_violated', {}, lambda t: t.edit_shard_row(2, 'join', lambda r: r.update(actual_ns=r['scheduled_ns'] + 101_000_000)), {}),
    ('poll_starvation', {}, lambda t: t.edit_shard_row(1, 'footer', lambda r: r.update(max_poll_gap_ns=501_000_000)), {}),
    ('early_shard_exit', {}, lambda t: (t.edit_shard_row(2, 'footer', lambda r: r.update(left_early=True)), t.edit_json('bot/swarm/window.json', lambda d: d.update(status='window_incomplete'))), {}),
    ('missing_end_acknowledgment', {}, lambda t: t.drop_shard_rows(0, 'ack_end'), {}),
    ('window_seen_after_it_began', {}, lambda t: t.edit_shard_row(0, 'window_observed', lambda r: r.update(mono_ns=t.timeline.start + 1)), {}),
    ('exactly_99_percent_input_valid', {}, lambda t: t.edit_frozen_bot(3, lambda b: b.update(scheduled=1800, sent=1782)), {}),
    ('below_99_percent_input_invalid', {}, lambda t: t.edit_frozen_bot(3, lambda b: b.update(scheduled=1800, sent=1781)), {}),
    ('dead_in_game_still_sending_idle_frames_valid', {}, lambda t: t.edit_frozen_bot(2, lambda b: b.update(alive=False, dead_frames=900)), {}),
    ('connected_but_not_sending_invalid', {}, lambda t: t.edit_frozen_bot(2, lambda b: b.update(sent=0)), {}),
    ('missing_input_counter_is_not_zero', {}, lambda t: t.edit_frozen_bot(2, lambda b: b.update(sent=None)), {}),
    ('recorder_cut_inside_a_line', {}, lambda t: _cut(t, 'bot/swarm/shard-1.ndjson'), {}),
    ('recorder_lost_its_footer', {}, lambda t: t.edit_rows('bot/swarm/shard-1.ndjson', lambda rows: rows.pop()), {}),
    ('recorder_overwritten', {}, lambda t: _overwrite(t, 'bot/swarm/shard-0.ndjson'), {}),
    ('server_never_finished_recorders', {}, lambda t: t.path('game/telemetry/final.json').unlink(), {}),
    ('population_tick_below_n', {}, lambda t: _tick_below_n(t, 30), {}),
    ('server_transition_missing', {}, _drop_auth, {}),
    ('clock_bracket_missing', {}, lambda t: setattr(t, 'brackets', dict(t.brackets, after=None)), {}),
    ('clock_drift_is_ambiguous', {}, lambda t: setattr(t, 'brackets', dict(t.brackets, after=fx.bracket('after', fx.BOT_MONO_ORIGIN_WALL + 200 * NS, 6 * NS))), {}),
    ('clock_bracket_too_wide', {}, lambda t: setattr(t, 'brackets', dict(t.brackets, before=fx.bracket('before', fx.BOT_MONO_ORIGIN_WALL, 0, half_ns=3 * NS))), {}),
    ('wall_clock_stepped', {}, _step_clock, {}),
    ('pid_reused', {}, lambda t: _sampler(t, 'game', _set_game_start), {}),
    ('socket_inode_changed', {}, lambda t: _sampler(t, 'game', _set_game_inode), {}),
    ('socket_inode_reused_from_earlier_run', {}, None, dict(prior=dict(game=dict(processes=set(), inodes={'game-socket-8081'})))),
    ('process_identity_reused_from_earlier_run', {}, None, dict(prior=dict(game=dict(processes={(3001, 'ticks:8001', 'boot-game')}, inodes=set())))),
    ('socket_counter_moved_backward', {}, lambda t: _sampler(t, 'game', _rewind_game_drops), {}),
    ('socket_counter_missing_is_not_zero', {}, lambda t: _sampler(t, 'bot', _drop_bot_counter), {}),
    ('generator_socket_drop_invalid', {}, lambda t: _sampler(t, 'bot', _bot_socket_drop), {}),
    ('game_socket_drop_is_a_fact_not_a_broken_window', {}, lambda t: _sampler(t, 'game', _game_socket_drop), {}),
    ('schema_not_the_frozen_one', {}, None, dict(telemetry_schema=dict(id='omega.measurement/2', sha256='6' * 64))),
)


def summary(proof):
    """What a reader needs and nothing machine-specific. Unrounded, and never a verdict on capacity."""
    facts = proof.get('facts') or {}
    return dict(status=proof['status'], reasons=sorted({'%s:%s' % (item['category'], item['code']) for item in proof['reasons']}), contract_hold=facts.get('contract_hold'), target=facts.get('target'), hold_s=facts.get('hold_s'),
                establishes_capacity=proof.get('establishes_capacity'), socket_counters_required=proof.get('socket_counters_required'), input=facts.get('input'))


def synthetic(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name, options, breaker, prove_options in SYNTHETIC:
        with tempfile.TemporaryDirectory(prefix='omega-window-') as root:
            tree = fx.Tree(root, **options)
            if breaker is not None:
                breaker(tree)
            rows[name] = summary(tree.prove(**prove_options))
    document = dict(schema='omega.do-session.window-evidence/1', kind='synthetic', note='The real prover over mocked recorder files. Nothing ran. Every window here is arithmetic.',
                    measurement_schema=mw.schema()['id'], measurement_schema_sha256=mw.schema_sha256(), scenarios=rows)
    (out / 'synthetic-proofs.json').write_text(json.dumps(document, indent=1, sort_keys=True) + '\n')
    return document


REAL_SHORT = (
    ('short_complete', dict(target=8, hold_s=6), {}),
    ('short_delayed_authentication', dict(target=8, hold_s=6, use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(4, 4.0)]), {}),
    ('short_authentication_never_arrives', dict(target=8, hold_s=6, use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(2, None)], readiness_timeout_s=4.0), {}),
    ('short_poll_starvation_in_window', dict(target=8, hold_s=6, schedule=[ml.FaultSchedule.pause_swarm_in_window(1.5)]), {}),
    ('short_poll_starvation_through_barrier', dict(target=8, hold_s=6, schedule=[ml.FaultSchedule.pause_swarm_in_barrier(1.0)]), {}),
    ('short_swarm_killed_in_window', dict(target=8, hold_s=6, schedule=[ml.FaultSchedule.kill_swarm_in_window()]), {}),
    ('short_game_killed_in_window', dict(target=8, hold_s=6, schedule=[ml.FaultSchedule.kill_game_in_window()]), {}),
)
REAL_INJECTED = (
    ('short_injected_early_shard_exit', dict(target=8, hold_s=6), ['exit:1:window:1']),
    ('short_injected_one_shard_starved', dict(target=8, hold_s=6), ['starve:2:window:1:1200']),
    ('short_injected_shard_starved_through_barrier', dict(target=8, hold_s=6), ['starve:3:barrier:0:900']),
    ('short_injected_dead_but_connected_input', dict(target=8, hold_s=6), ['mute:3:window:0']),
    ('short_injected_recorder_truncated', dict(target=8, hold_s=6), ['truncate:1:window:1']),
)
REAL_LONG = (
    ('contract_60s_25_bots', dict(target=25, hold_s=60)),
    ('contract_300s_25_bots', dict(target=25, hold_s=300)),
)


def provenance(release, fault_release):
    def run(*argv):
        return subprocess.run(argv, stdout=subprocess.PIPE, check=True, cwd=str(REPO)).stdout.decode().strip()
    return dict(source_revision=run('git', 'rev-parse', 'HEAD'), source_clean=not run('git', 'status', '--porcelain'), cargo_lock_sha256=hashlib.sha256((REPO / 'rust/Cargo.lock').read_bytes()).hexdigest(),
                rustc=run('rustc', '-Vv'), python=platform.python_version(), platform=platform.platform(), server_config_sha256=hashlib.sha256((REPO / 'deployment/server_config.loadtest.json').read_bytes()).hexdigest(),
                measurement_schema=mw.schema()['id'], measurement_schema_sha256=mw.schema_sha256(), release_build='cargo build --release --locked -p omega-server -p omega-load-test',
                fault_build='cargo build --release --locked -p omega-load-test --features omega-load-test/fault-injection --target-dir <scratch>',
                binaries=dict(omega_server=hashlib.sha256((pathlib.Path(release) / 'omega-server').read_bytes()).hexdigest(), omega_load_test=hashlib.sha256((pathlib.Path(release) / 'omega-load-test').read_bytes()).hexdigest(),
                              omega_load_test_fault_build=hashlib.sha256((pathlib.Path(fault_release) / 'omega-load-test').read_bytes()).hexdigest() if fault_release else None))


def real_summary(run, proof):
    row = summary(proof)
    facts = proof.get('facts') or {}
    row.update(events=run['events'], clock=facts.get('clock'), population={k: v for k, v in (facts.get('population') or {}).items() if k not in ('interval_game_mono_ns', 'core_game_mono_ns')},
               window_length_ns=(facts['window_bot_mono_ns'][1] - facts['window_bot_mono_ns'][0]) if facts.get('window_bot_mono_ns') else None,
               shard_max_poll_gap_ns=[shard['max_poll_gap_ns'] for shard in facts.get('shards') or []],
               bot_host={k: v for k, v in (facts.get('bot_host') or {}).items() if k != 'kernel_counters'}, game_host={k: v for k, v in (facts.get('game_host') or {}).items() if k not in ('kernel_counters', 'socket_inode', 'socket_port')},
               exits={role: (result.get('result') or {}).get('processes') for role, result in run['results'].items()})
    return row


def real(out, release, fault_release, long_windows):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    scenarios = {}
    root = pathlib.Path(tempfile.mkdtemp(prefix='omega-evidence-'))
    try:
        for name, options, _ in REAL_SHORT:
            run = ml.LocalRun(release, root / name, options.pop('target'), options.pop('hold_s'), **options).execute()
            scenarios[name] = real_summary(run, ml.prove(run))
            print(name, scenarios[name]['status'], scenarios[name]['reasons'], flush=True)
        if fault_release:
            for name, options, faults in REAL_INJECTED:
                extra = [item for fault in faults for item in ('--fault', fault)]
                run = ml.LocalRun(release, root / name, options['target'], options['hold_s'], bot_release=fault_release, bot_extra=extra).execute()
                scenarios[name] = real_summary(run, ml.prove(run))
                print(name, scenarios[name]['status'], scenarios[name]['reasons'], flush=True)
        if long_windows:
            for name, options in REAL_LONG:
                run = ml.LocalRun(release, root / name, options['target'], options['hold_s']).execute()
                proof = ml.prove(run, allow_short_hold=False)
                scenarios[name] = real_summary(run, proof)
                print(name, scenarios[name]['status'], scenarios[name]['reasons'], flush=True)
    finally:
        shutil.rmtree(str(root), True)
    document = dict(schema='omega.do-session.window-evidence/1', kind='real_local', note='Real processes on one machine in real time. Short holds are labelled short. Not a live-host validation and not a capacity observation.',
                    provenance=provenance(release, fault_release), scenarios=scenarios)
    name = 'real-windows.json' if long_windows else 'real-short-windows.json'
    (out / name).write_text(json.dumps(document, indent=1, sort_keys=True) + '\n')
    return document


def write_sums(out):
    out = pathlib.Path(out)
    lines = []
    for path in sorted(out.glob('*.json')):
        lines.append('%s  %s\n' % (hashlib.sha256(path.read_bytes()).hexdigest(), path.name))
    (out / 'SHA256SUMS').write_text(''.join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=('synthetic', 'real'))
    parser.add_argument('--out', required=True)
    parser.add_argument('--release')
    parser.add_argument('--fault-release')
    parser.add_argument('--long', action='store_true')
    args = parser.parse_args(argv)
    if args.kind == 'synthetic':
        document = synthetic(args.out)
        for name, row in document['scenarios'].items():
            print(name, row['status'], row['reasons'])
    else:
        if not args.release:
            parser.error('--release is required')
        real(args.out, args.release, args.fault_release, args.long)
    write_sums(args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
