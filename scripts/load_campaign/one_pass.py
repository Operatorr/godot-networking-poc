#!/usr/bin/env python3
"""Issue execution entry point; never inherit historical campaign/build defaults."""
import concurrent.futures
import datetime
import hashlib
import json
import pathlib
import shlex
import shutil
import sys
import time

import run
import analyze
import campaign
import publish
import single_run

NAMESPACE = 'one-pass-20261014'
run.RAW = run.ROOT / 'deployment/hetzner/results' / NAMESPACE
run.REMOTE = '/home/deploy/omega-results/' + NAMESPACE
run.UNIT_PREFIX = 'omega-' + NAMESPACE + '-'
run.MEASURED_BY_ROLE = {
    'game': '/home/deploy/omega-stabilized-b1266c1/rust/target/release',
    'bots': '/home/deploy/omega-measured/rust/target/release',
}
run.MEASURED_CHECKOUTS = {
    'game': '/home/deploy/omega-stabilized-b1266c1',
    'bots': '/home/deploy/omega-measured',
}
campaign.STATE = run.RAW / 'campaign-state.json'
analyze.RAW = run.RAW
publish.OUTPUT = run.ROOT / 'docs/netcode/perf-notes/load-test-reports/2026-10-14-one-pass'
PINNED = {
    'game': 'f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2',
    'bots': '8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf',
}


def save(name, value):
    text = json.dumps(value, indent=2) + '\n'
    (run.RAW / name).write_text(text)
    (publish.OUTPUT / name).write_text(publish.redact(text))


def check_hosts():
    def check(role):
        binary = run.MEASURED_BY_ROLE[role] + ('/omega-server' if role == 'game' else '/omega-load-test')
        digest = run.ssh(role, 'sha256sum ' + shlex.quote(binary)).split()[0]
        if digest != PINNED[role]:
            raise RuntimeError('Pinned binary changed: ' + role)
        return digest
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(check, run.HOSTS))
    if run.ssh('bots', 'pgrep -x omega-load-test >/dev/null && echo BUSY || echo IDLE').strip() != 'IDLE':
        raise RuntimeError('Existing swarm; refusing overlap')


def initialize():
    if run.RAW.exists():
        raise RuntimeError('Fresh namespace already exists; inspect before resuming')
    run.RAW.mkdir(parents=True)
    publish.OUTPUT.mkdir(parents=True)
    check_hosts()
    save('execution-binding.json', {
        'task': 'https://github.com/Operatorr/godot-networking-poc/issues/35',
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'controller_revision': run.subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'namespace': NAMESPACE, 'binary_sha256_by_role': PINNED,
        'checkouts_by_role': run.MEASURED_CHECKOUTS,
        'authorization': 'User: $wayfinder work on Execute the revised one-pass CAX11 load-test matrix',
        'historical_hold': 'Preserved unchanged; administrative hold applies to the old namespace, with no active swarm found.',
        'one_run_per_condition': True,
    })
    def stage(role):
        run.ssh(role, 'mkdir -p ' + shlex.quote(run.REMOTE))
        for name in ('host_collect.py', 'capture.py', 'flow_record.rs'):
            run.copy(role, run.ROOT / 'scripts/load_campaign' / name, run.REMOTE + '/' + name)
        run.ssh(role, 'cp /home/deploy/omega-results/campaign-20261013/flow-record ' + run.REMOTE + '/flow-record')
        command = 'date -u --iso-8601=ns; uname -a; lscpu; df -B1 /home/deploy; chronyc tracking; tc -s -j qdisc show dev eth0; tc -j filter show dev eth0 egress; source /home/deploy/.cargo/env; rustc -Vv; sha256sum ' + run.REMOTE + '/flow-record'
        (run.RAW / (role + '-initial-state.txt')).write_text(run.ssh(role, command))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(stage, run.HOSTS))


def observe(name, population, behavior, duration=120, collection=True, build='instrumented', profile='native'):
    directory = run.RAW / name
    if not (directory / 'steady.json').exists():
        check_hosts()
        started = time.monotonic()
        run.run(name, population, behavior, duration=duration, collection=collection, build=build, profile=profile)
        result = analyze.summarize(directory)
        result['pipeline_elapsed_s'] = time.monotonic() - started
        (directory / 'steady.json').write_text(json.dumps(result, indent=2))
        publish.publish(name)
    result = json.loads((directory / 'steady.json').read_text())
    print(json.dumps({'run': name, 'classification': result['classification'], 'tick_hz': result.get('tick_hz'), 'mean_tick_ms': result.get('exporter_tick_mean_ms')}), flush=True)
    return result


def preflight():
    observe('preflight-clustered-50-off', 50, 'clustered', collection=False, build='instrumented-off')
    observe('preflight-clustered-50-on', 50, 'clustered')
    observe('preflight-combat-3-combined', 3, 'combat', profile='combined')
    observe('preflight-combat-3-cleanup', 3, 'combat')


def resolve_preflight():
    rows = {name: json.loads((run.RAW / name / 'steady.json').read_text()) for name in (
        'preflight-clustered-50-off', 'preflight-clustered-50-on',
        'preflight-combat-3-combined', 'preflight-combat-3-cleanup')}
    off = rows['preflight-clustered-50-off']
    on = audit_whole_run(rows['preflight-clustered-50-on'])
    impaired = audit_whole_run(rows['preflight-combat-3-combined'])
    cleanup = audit_whole_run(rows['preflight-combat-3-cleanup'])
    if off['classification'] != 'instrumented-build-recording-off-control-unscored':
        raise RuntimeError('Unexpected off-control result')
    for row in (on, cleanup):
        if row['classification'] != 'native-stable-candidate' or not row['whole_run_error_gate']:
            raise RuntimeError('Native preflight failed: ' + row['run_id'])
    if not impaired['collector_valid'] or not impaired['generator_valid']:
        raise RuntimeError('Impaired preflight collection/generation failed')
    cleanup_state = {}
    for role in run.HOSTS:
        qdiscs = json.loads(run.ssh(role, 'tc -j qdisc show dev eth0'))
        filters = json.loads(run.ssh(role, 'tc -j filter show dev eth0 egress'))
        if len(qdiscs) != 1 or qdiscs[0]['kind'] != 'fq_codel' or filters:
            raise RuntimeError('Impairment/mirror cleanup incomplete: ' + role)
        cleanup_state[role] = {'qdiscs': qdiscs, 'egress_filters': filters}
    def cpu(row, role):
        host = row[role + '_host']
        return host.get('swarm_cgroup_cpu_percent_one_core', host.get('process_cpu_percent_one_core'))
    save('measurement-preflight-resolution.json', {
        'scored_runs_authorized_by_preflight': True,
        'validated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'binary_sha256_by_role': PINNED,
        'observations': list(rows), 'measurement_seconds_per_preflight': 60,
        'overhead': {
            'mean_tick_work_on_ms': on['exporter_tick_mean_ms'],
            'mean_tick_work_off_ms': off['exporter_tick_mean_ms'],
            'tick_difference_ms': on['exporter_tick_mean_ms'] - off['exporter_tick_mean_ms'],
            'server_cpu_on_percent_one_core': cpu(on, 'game'),
            'server_cpu_off_percent_one_core': cpu(off, 'game'),
            'generator_cpu_on_percent_one_core': cpu(on, 'bots'),
            'generator_cpu_off_percent_one_core': cpu(off, 'bots'),
            'observer_mean_ms': on['observer_mean_ms'],
        },
        'impairment_directional_observations': impaired['directional_loss'],
        'impairment_rtt_ms': impaired['rtt_ms'],
        'cleanup_state': cleanup_state,
        'caveats': ['One on/off comparison, different entropy-seeded worlds and shared-host conditions; no causal precision or repeat variance claimed.',
                    'Configured loss/delay is delivery degradation, not a native capacity failure.',
                    'All preflights are unscored; the matched exporter sum/count and host boundaries supply the off-control comparison.'],
    })


def audit_whole_run(result):
    """Keep warmup errors visible and enforce the native zero-error gate."""
    directory = run.RAW / result['run_id']
    checks = single_run.whole_run_checks(directory)
    result['whole_run_checks'] = checks
    errors = {scope: values for scope, values in checks.items()
              if isinstance(values, dict) and any(values.values())}
    result['whole_run_error_gate'] = not errors
    if errors and result['profile'] == 'native':
        result['server_sustainability_gate'] = False
        if result['classification'] == 'native-stable-candidate':
            result['classification'] = 'valid-failure'
    (directory / 'steady.json').write_text(json.dumps(result, indent=2))
    publish.publish(result['run_id'])
    return result


def release_unpacked(name):
    """Remove only remote unpacked duplicates after comparing both archive hashes."""
    ledger_path = run.RAW / 'duplicate-cleanup.json'
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    if name in ledger:
        return
    check_hosts()
    directory = run.RAW / name
    proof = {}
    for role in run.HOSTS:
        local = directory / (role + '.tar.gz')
        remote = run.REMOTE + '/' + name + '-' + role + '.tar.gz'
        with local.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if run.ssh(role, 'sha256sum ' + shlex.quote(remote)).split()[0] != digest:
            raise RuntimeError('Archive mismatch; retaining all duplicates')
        proof[role] = digest
    for role in run.HOSTS:
        target = run.REMOTE + '/' + name + '/' + role
        run.ssh(role, 'python3 -c ' + shlex.quote('import shutil; shutil.rmtree(' + repr(target) + ')'))
    ledger[name] = {'archive_sha256': proof, 'removed': 'Remote unpacked duplicates only; local and remote archives retained'}
    save('duplicate-cleanup.json', ledger)


ORIGINAL_CELL = campaign.cell


def checked_cell(*args, **kwargs):
    check_hosts()
    started = time.monotonic()
    result = audit_whole_run(ORIGINAL_CELL(*args, **kwargs))
    result['controller_cell_elapsed_s'] = time.monotonic() - started
    (run.RAW / result['run_id'] / 'steady.json').write_text(json.dumps(result, indent=2))
    # The imported diagnostic lives in its original remote namespace; preserve it there.
    if result['run_id'] != 'pilot-clustered-50-recovery':
        release_unpacked(result['run_id'])
    publish.publish(result['run_id'])
    import summarize_campaign
    summarize_campaign.main()
    return result


campaign.cell = checked_cell


def external_run():
    import external
    check_hosts()
    historical = run.ROOT / 'deployment/hetzner/results/campaign-20261013'
    previous = json.loads((historical / 'external-combat-3-r1/manifest.json').read_text())
    binary = run.ROOT / 'rust/target/release/omega-load-test'
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != previous['local_binary_sha256']:
        raise RuntimeError('External Mac binary differs from retained measurement build')
    difference = run.subprocess.check_output(['git', 'diff', '642c147', '--',
        'rust/load_test', 'rust/protocol', 'rust/sim_core'], text=True)
    if difference:
        raise RuntimeError('External generator sources differ from the measurement revision')
    for name in ('socket-capture.dylib', 'flow-record-macos'):
        shutil.copy2(historical / name, run.RAW / name)
    external.main()
    directory = run.RAW / 'external-combat-3-r1'
    result = analyze.summarize(directory)
    (directory / 'steady.json').write_text(json.dumps(result, indent=2))
    publish.publish(directory.name)
    (publish.OUTPUT / directory.name / 'operator-clock.txt').write_text(
        publish.redact((directory / 'operator-clock.txt').read_text()))
    import summarize_campaign
    summarize_campaign.main()
    print(result['classification'], flush=True)


def audit():
    import verify_matrix
    import summarize_campaign
    summarize_campaign.main()
    result = verify_matrix.verify()
    source_errors = []
    for path in run.RAW.glob('*/steady.json'):
        row = json.loads(path.read_text())
        for role, digest in PINNED.items():
            if role == 'bots' and row.get('topology', '').startswith('Operator Mac'):
                continue
            provenance = path.parent / (role + '-run-provenance.txt')
            if not provenance.exists() or digest not in provenance.read_text():
                source_errors.append(path.parent.name + ': ' + role + ' binary provenance mismatch')
    save('source-audit.json', {'pinned_sha256': PINNED, 'errors': source_errors,
        'complete': result['complete'] and not source_errors})
    print(json.dumps({'complete': result['complete'] and not source_errors,
        'expected': result['expected_cell_count'], 'missing': len(result['missing_cells']),
        'invalid': len(result['invalid_collection_cells']), 'source_errors': source_errors}), flush=True)


if __name__ == '__main__':
    {'init': initialize, 'preflight': preflight, 'resolve-preflight': resolve_preflight,
     'core': campaign.core, 'network': campaign.network, 'transfer': campaign.transfer,
     'all': campaign.all_phases, 'external': external_run, 'audit': audit}[sys.argv[1]]()
