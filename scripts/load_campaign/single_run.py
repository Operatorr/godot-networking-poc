#!/usr/bin/env python3
"""One isolated clustered diagnostic; never advances the agreed matrix."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import shlex
import time
import traceback
import run
import analyze
import publish


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--duration', type=int, default=360)
    parser.add_argument('--game-measured-directory', default=run.MEASURED)
    parser.add_argument('--game-checkout', default='/home/deploy/omega-measured')
    args = parser.parse_args()
    if not re.fullmatch('[a-z0-9-]+', args.run_id):
        raise ValueError('Use a simple, unique diagnostic run id')
    if args.duration <= 60:
        raise ValueError('The global warmup is 60 seconds')
    run.RAW = run.ROOT / 'deployment/hetzner/results/single-run-20261014'
    run.REMOTE = '/home/deploy/omega-results/single-run-20261014'
    run.MEASURED_BY_ROLE['game'] = args.game_measured_directory
    run.MEASURED_CHECKOUTS['game'] = args.game_checkout
    publish.OUTPUT = run.ROOT / 'docs/netcode/perf-notes/load-test-reports/2026-10-14-single-run'
    run.RAW.mkdir(parents=True, exist_ok=True)
    directory = run.RAW / args.run_id
    if directory.exists():
        raise RuntimeError('Refusing to overwrite diagnostic evidence')
    if run.ssh('bots', 'pgrep -x omega-load-test >/dev/null && echo BUSY || echo IDLE').strip() != 'IDLE':
        raise RuntimeError('A swarm is already active; do not overlap workloads')

    def stage(role):
        run.ssh(role, 'mkdir -p ' + shlex.quote(run.REMOTE))
        for name in ('host_collect.py', 'capture.py', 'flow_record.rs'):
            run.copy(role, run.ROOT / 'scripts/load_campaign' / name, run.REMOTE + '/' + name)
        run.ssh(role, 'cp /home/deploy/omega-results/campaign-20261013/flow-record ' + run.REMOTE + '/flow-record')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(stage, run.HOSTS))

    instance = '/sys/kernel/tracing/instances/omega-' + args.run_id
    setup = """import pathlib
p=pathlib.Path(INSTANCE)
p.mkdir()
(p/'trace_clock').write_text('mono')
(p/'buffer_size_kb').write_text('1024')
(p/'events/udp/udp_fail_queue_rcv_skb/enable').write_text('1')
(p/'events/skb/kfree_skb/filter').write_text('reason == 6')
(p/'events/skb/kfree_skb/enable').write_text('1')
(p/'tracing_on').write_text('1')
""".replace('INSTANCE', repr(instance))
    run.ssh('game', 'sudo -n python3 -c ' + shlex.quote(setup))
    cleanup = """import pathlib
p=pathlib.Path(INSTANCE)
(p/'tracing_on').write_text('0')
(p/'events/enable').write_text('0')
p.rmdir()
""".replace('INSTANCE', repr(instance))
    started = time.monotonic()
    try:
        run.run(args.run_id, 50, 'clustered', duration=args.duration, build='instrumented')
    finally:
        directory.mkdir(parents=True, exist_ok=True)
        trace = run.ssh('game', 'sudo -n cat ' + shlex.quote(instance + '/trace'), check=False)
        (directory / 'kernel-drop-trace.txt').write_text(trace)
        stats = run.ssh('game', 'sudo -n sh -c ' + shlex.quote('cat ' + instance + '/per_cpu/cpu*/stats'), check=False)
        (directory / 'kernel-drop-trace-stats.txt').write_text(stats)
        run.ssh('game', 'sudo -n python3 -c ' + shlex.quote(cleanup), check=False)
    proof = {'purpose': 'Single-run diagnosis; outside the scored matrix',
             'binary_and_buffers': 'Unchanged unless the selected executable provenance explicitly records a later revision',
             'trace_scope': 'Dedicated tracefs instance: UDP queue failures and SOCKET_RCVBUFF drops only; no global tracing changes',
             'trace_clock': 'mono', 'trace_sha256': hashlib.sha256(trace.encode()).hexdigest(),
             'trace_stats_sha256': hashlib.sha256(stats.encode()).hexdigest(),
             'udp_queue_failure_events_all_ports': trace.count('udp_fail_queue_rcv_skb:'),
             'socket_receive_buffer_drop_events': trace.count('kfree_skb:'),
             'run_and_evidence_seconds': time.monotonic() - started}
    (directory / 'diagnostic-proof.json').write_text(json.dumps(proof, indent=2))
    analysis_started = time.monotonic()
    try:
        result = analyze.summarize(directory)
        result['diagnostic_only'] = True
        (directory / 'steady.json').write_text(json.dumps(result, indent=2))
    except Exception:
        (directory / 'analysis-error.txt').write_text(traceback.format_exc())
        raise
    proof['analysis_seconds'] = time.monotonic() - analysis_started
    publish.publish(args.run_id)
    target = publish.OUTPUT / args.run_id
    (target / 'diagnostic-proof.json').write_text(json.dumps(proof, indent=2))
    print(json.dumps({'run': args.run_id, 'classification': result['classification'],
                      'window_s': result['window_s'], 'kernel_errors': result['game_kernel_udp_errors'],
                      'generator_valid': result['generator_valid'], 'collector_valid': result['collector_valid'],
                      'tick_hz': result['tick_hz'], 'tick_p99_ms': result['tick_work_ms']['p99'],
                      'analysis_seconds': proof['analysis_seconds']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
