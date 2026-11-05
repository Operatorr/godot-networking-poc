#!/usr/bin/env python3
"""Operator CLI for fresh test runs on a ready pair. No provider mutation is possible here: its adapter holds no gate.

    run_cli.py execute --session-dir D --token-file T --registry-command C --ssh-key K --fencing-token N
    run_cli.py resume  --session-dir D --token-file T --registry-command C --ssh-key K --operator-request REF [--takeover] [--repository R]
    run_cli.py collect --session-dir D --token-file T --registry-command C --ssh-key K --reason WHY [--takeover]

``execute`` continues under the token ``provision_cli`` printed. There is deliberately no way to pick up a session without
``resume``: returning under a new token pauses it, and only an explicit operator request with every revalidation passed
un-pauses it. ``collect`` is the other exit, and it stops whatever was left, seals it and requests cleanup.

``execute`` and ``resume`` refuse before touching any guest unless this checkout is the frozen controller and adapter revision.

None of this has ever been run against a live account. Trials are scored by ``capacity_scorer``, the executor's default, and no argument here
can replace it or relax the prover. Exit codes: 0 finished or resumed and finished, 2 refused, stopped, or a wrap-up that failed locally
(its cleanup request still went out).
"""
import argparse
import dataclasses
import json
import pathlib
import shlex
import sys
import time

import cleanup_provider
import do_api
import guest_runner
import manifest as manifest_mod
import registry_client
import run_executor
import search
import session_clock
import ssh_access


def load_session(session_dir):
    manifest = json.loads((pathlib.Path(session_dir) / 'manifest.json').read_text())
    sha = (pathlib.Path(session_dir) / 'manifest.sha256').read_text().split()[0]
    manifest_mod.verify_manifest(manifest, sha)
    return manifest, sha


def resume_and_run(client, session_id, build_executor, operator_request_ref, takeover=False):
    """The one path back in. Control first, then every check, and only then more work. Any refusal leaves the session paused."""
    try:
        control = client.acquire(session_id, takeover=takeover)
    except registry_client.RegistryRejected as rejection:
        return dict(resumed=False, code=rejection.code, detail=str(rejection.message), checks={}), None
    executor = build_executor(control['fencing_token'])
    outcome = executor.resume(operator_request_ref, control)
    if not outcome['resumed']:
        return outcome, None
    return outcome, executor.run_batch()


def collect_and_stop(client, session_id, build_executor, reason, takeover=False):
    """Refusing to resume is not the end: stop and preserve anything left, then collect and hand over to deletion."""
    control = client.acquire(session_id, takeover=takeover)
    executor = build_executor(control['fencing_token'])
    executor.collecting = True
    problems = []
    try:
        executor.prepare()
        problems = executor.reconcile('operator_collect')
    except (run_executor.BatchStop, run_executor.GuestLost, run_executor.ControlLost, run_executor.ResumeRefused, run_executor.RunAborted, run_executor.CleanupStarted,
            ssh_access.HostVerificationFailed, cleanup_provider.ProviderError, registry_client.RegistryRejected, registry_client.RegistryUnavailable) + run_executor.LOCAL_FAILURES as error:
        problems = [type(error).__name__ + ': ' + cleanup_provider.redact(error)]    # whatever went wrong, the request below must still go out
    result = run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail=reason, runs=executor.outcomes)
    executor.wrap_up(result)
    return result, problems


def _executor_factory(args, environment):
    manifest, sha = load_session(args.session_dir)
    provider = do_api.DigitalOceanProvisioningProvider(environment['transport'](args.token_file), wall=time.time)
    guests = environment['guests'](args.ssh_key, args.session_dir)
    client = environment['registry'](args.registry_command)

    def build(token):
        return run_executor.RunExecutor(client, guests, provider, manifest, sha, args.session_dir, token, time.sleep, session_clock.suspend_aware_monotonic, time.time,
                                        source_problems=lambda: run_executor.source_identity_problems(manifest, args.repository))
    return client, manifest['session']['id'], build


def _print(document):
    print(json.dumps(document, indent=2, sort_keys=True, default=str))


def cmd_execute(args, environment):
    _, _, build = _executor_factory(args, environment)
    result = build(args.fencing_token).run_batch()
    _print(dataclasses.asdict(result))
    return 0 if result.status == run_executor.FINISHED and result.wrap_up_error is None else 2


def cmd_resume(args, environment):
    client, session_id, build = _executor_factory(args, environment)
    outcome, result = resume_and_run(client, session_id, build, args.operator_request, takeover=args.takeover)
    _print(dict(resume=outcome, batch=dataclasses.asdict(result) if result is not None else None))
    return 0 if result is not None and result.status == run_executor.FINISHED and result.wrap_up_error is None else 2


def cmd_collect(args, environment):
    client, session_id, build = _executor_factory(args, environment)
    result, problems = collect_and_stop(client, session_id, build, args.reason, takeover=args.takeover)
    _print(dict(batch=dataclasses.asdict(result), problems=problems))
    return 2 if problems or result.wrap_up_error else 0


def default_environment():
    return dict(transport=do_api.HttpsTransport,
                guests=lambda key_path, session_dir: ssh_access.SshAccess(key_path, pathlib.Path(session_dir) / 'provisioning' / 'ssh'),
                registry=lambda command: registry_client.RegistryClient(registry_client.SubprocessTransport(shlex.split(command)), 'run-cli-%d' % int(time.time())))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    def command(name, func):
        item = sub.add_parser(name)
        item.add_argument('--session-dir', required=True)
        item.add_argument('--token-file', required=True)
        item.add_argument('--registry-command', required=True)
        item.add_argument('--ssh-key', required=True, help='path only: the private key is passed to ssh and never read here')
        item.add_argument('--repository', default=str(pathlib.Path(__file__).parents[2]))
        item.set_defaults(func=func)
        return item

    command('execute', cmd_execute).add_argument('--fencing-token', type=int, required=True)
    resume = command('resume', cmd_resume)
    resume.add_argument('--operator-request', required=True, help='the operator\'s explicit request, as a reference')
    resume.add_argument('--takeover', action='store_true', help='also take a live lease; the other controller becomes stale')
    collect = command('collect', cmd_collect)
    collect.add_argument('--reason', required=True)
    collect.add_argument('--takeover', action='store_true')
    return parser


def main(argv=None, environment=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, environment or default_environment())
    except (OSError, ValueError, manifest_mod.ManifestError) as error:
        print(json.dumps(dict(error=type(error).__name__ + ': ' + cleanup_provider.redact(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
