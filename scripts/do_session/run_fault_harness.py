#!/usr/bin/env python3
"""Offline crash fixture: one real controller process over real runner processes, dying for real at a named boundary.

The fixtures start this as a child with one JSON description of a ``run_fixtures.LocalSession``. At the chosen failpoint it
calls ``os._exit`` with no cleanup, as ``kill -9`` would. Without one it finishes normally and prints what happened.

    run_fault_harness.py execute DESCRIPTION.json --fencing-token N --controller NAME [--failpoint P] [--score JSON]
    run_fault_harness.py resume  DESCRIPTION.json --controller NAME [--takeover] [--failpoint P] [--score JSON]
    run_fault_harness.py collect DESCRIPTION.json --controller NAME [--takeover]

``--abort-at P`` has the operator abort at that boundary, through the real registry. ``--delay-at P --delay-s N`` holds this
controller there, as a slow network would hold a request already authorized.
"""
import argparse
import dataclasses
import json
import os
import pathlib
import sys
import time

import registry_client
import run_cli
import run_executor
import run_fixtures
import session_clock

CRASH_EXIT = 137
FAST = run_executor.Policy(poll_s=0.1, game_start_poll_s=0.05, renew_every_s=2.0, stop_wait_s=8.0, guest_step_timeout_s=30.0, recovery_poll_s=0.2)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('execute', 'resume', 'collect'))
    parser.add_argument('description')
    parser.add_argument('--controller', required=True)
    parser.add_argument('--fencing-token', type=int)
    parser.add_argument('--takeover', action='store_true')
    parser.add_argument('--failpoint')
    parser.add_argument('--failpoint-hit', type=int, default=1)
    parser.add_argument('--abort-at')
    parser.add_argument('--delay-at')
    parser.add_argument('--delay-s', type=float, default=0.0)
    parser.add_argument('--score')
    parser.add_argument('--no-wrap-up', action='store_true')
    args = parser.parse_args(argv)
    description = json.loads(pathlib.Path(args.description).read_text())
    guests = run_fixtures.LocalGuests(description['hosts_root'], environment=dict(PATH=description['bin_dir'] + os.pathsep + os.environ.get('PATH', '')))
    adapter = (run_fixtures.RealReleaseAdapter if description.get('real_release') else run_fixtures.LocalAdapter)(guests, description['game_port'], description['metrics_port'], workload_seconds=description['workload_seconds'],
                                        game_extra=description['game_extra'], bot_extra=description['bot_extra'])
    client = registry_client.RegistryClient(registry_client.SubprocessTransport(description['rpc_argv']), args.controller, attempts=2, retry_delay_s=0.05)
    manifest, sha = run_cli.load_session(description['session_dir'])
    provider = run_fixtures.LocalPairProvider(description['pair_file'])
    scorer = None
    if args.score is not None:
        scripted = json.loads(args.score)
        scorer = run_fixtures.scripted_scorer({int(k): v for k, v in scripted.get('targets', {}).items()}, scripted.get('default', 'PASS'))

    hits = [0]

    def failpoint(name):
        if name == args.abort_at:
            client.mutate('operator_abort', session_id=description['session'], reason='local fixture: operator abort')
        if name == args.delay_at:
            time.sleep(args.delay_s)
        if name == args.failpoint:
            hits[0] += 1
            if hits[0] == args.failpoint_hit:
                os._exit(CRASH_EXIT)

    def build(token):
        return run_executor.RunExecutor(client, guests, provider, manifest, sha, description['session_dir'], token, time.sleep, session_clock.suspend_aware_monotonic, time.time,
                                        scorer=scorer, adapter=adapter, policy=FAST, failpoint=failpoint, source_problems=lambda: [], readiness_problems=lambda report: [],
                                        require_counters=False)

    if args.mode == 'execute':
        executor = build(args.fencing_token)
        result = executor.execute() if args.no_wrap_up else executor.run_batch()
        print(json.dumps(dict(batch=dataclasses.asdict(result)), sort_keys=True, default=str))
    elif args.mode == 'resume':
        outcome, result = run_cli.resume_and_run(client, description['session'], build, 'local-fixture: explicit operator request', takeover=args.takeover)
        print(json.dumps(dict(resume=outcome, batch=dataclasses.asdict(result) if result is not None else None), sort_keys=True, default=str))
    else:
        result, problems = run_cli.collect_and_stop(client, description['session'], build, 'local fixture', takeover=args.takeover)
        print(json.dumps(dict(batch=dataclasses.asdict(result), problems=problems), sort_keys=True, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
