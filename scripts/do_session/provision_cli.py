#!/usr/bin/env python3
"""Operator CLI for provider-backed provisioning (handoff slice 3, issue #66).

    provision_cli.py source-digests --repo DIR --sha SHA
    provision_cli.py preflight      --session-dir D --token-file F --registry-command CMD
    provision_cli.py provision      --session-dir D --token-file F --registry-command CMD --authorization A.json
                                    --ssh-key PATH [--public-key PATH]
    provision_cli.py refresh-access --session-dir D --token-file F --registry-command CMD --authorization A.json
                                    [--fencing-token N] --ssh-source CIDR... [--udp-source CIDR...]

``source-digests`` is local. ``preflight`` only reads the provider. ``provision`` and ``refresh-access`` change remote
resources, and they refuse before reading a token unless they get an authorization packet that validates for this
exact manifest right now. No such packet exists yet. Gates A, B and C each issue their own, and this slice issues none.

``refresh-access`` without ``--fencing-token`` acquires control first, because a changed address usually means this
controller was away. Taking control pauses a ready session, and nothing resumes until an explicit resume (slice 4).

Exit codes: 0 ready/done, 2 refused or stopped (the printed code says which), 1 configuration or local failure.
A stopped session is cleaned up by the watchdog. This command never waits for that, and never reports it as finished.
"""
import argparse
import hashlib
import json
import pathlib
import shlex
import subprocess
import sys
import time

import cleanup_provider
import create_evidence
import do_api
import do_session
import guest_agent
import guest_bootstrap
import manifest as manifest_mod
import provider_preflight
import provisioner
import registry_client
import remote_authorization
import session_access
import session_clock
import ssh_access


def source_digests(repo, sha):
    """The frozen digests of an exact commit, read from git objects. A dirty or moving checkout cannot affect them."""
    def git(*arguments):
        return subprocess.run(['git', '-C', str(repo)] + list(arguments), stdout=subprocess.PIPE, check=True).stdout

    tree = git('ls-tree', '-r', '--full-tree', sha, *guest_agent.CONTENT_PATHS).decode('utf-8')
    return dict(benchmark_sha=git('rev-parse', sha + '^{commit}').decode('utf-8').strip(),
                cargo_lock_sha256=hashlib.sha256(git('show', sha + ':rust/Cargo.lock')).hexdigest(),
                server_config_sha256=hashlib.sha256(git('show', sha + ':' + guest_agent.SERVER_CONFIG)).hexdigest(),
                content_sha256=guest_agent.content_digest(tree))


def load_session(session_dir):
    manifest = json.loads((pathlib.Path(session_dir) / 'manifest.json').read_text())
    sha = (pathlib.Path(session_dir) / 'manifest.sha256').read_text().split()[0]
    manifest_mod.verify_manifest(manifest, sha)
    return manifest, sha


def registry_client_for(command):
    """The registry lives on the management host. Without an acknowledgement nothing is created."""
    return registry_client.RegistryClient(registry_client.SubprocessTransport(shlex.split(command)), 'provision-cli')


class Environment:
    """Everything with a side effect outside this process, replaceable as a whole by offline fixtures."""

    def __init__(self, transport_factory=None, registry_factory=None, guests_factory=None, sleep=time.sleep, monotonic=session_clock.suspend_aware_monotonic, wall=time.time):
        self.transport_factory = transport_factory or do_api.HttpsTransport
        self.registry_factory = registry_factory or registry_client_for
        self.guests_factory = guests_factory or (lambda key_path, session_dir: ssh_access.SshAccess(key_path, pathlib.Path(session_dir) / 'provisioning' / 'ssh'))
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall = wall


def cmd_source_digests(args, environment):
    print(json.dumps(source_digests(args.repo, args.sha), indent=2, sort_keys=True))
    return 0


def cmd_preflight(args, environment):
    manifest, _ = load_session(args.session_dir)
    provider = do_api.DigitalOceanProvisioningProvider(environment.transport_factory(args.token_file), wall=environment.wall)
    client = environment.registry_factory(args.registry_command)
    try:
        facts = provider_preflight.collect(provider, manifest, environment.wall)
    except provider_preflight.PreflightUnavailable as error:
        print(json.dumps(dict(ok=False, code='provider_facts_unavailable', detail=str(error))))
        return 2
    reasons = provider_preflight.problems(manifest, facts, client.call('health', session_id=manifest['session']['id']), environment.wall())
    print(json.dumps(dict(ok=not reasons, reasons=reasons, observed_at=facts['observed_at'], account=facts['account'], collisions=facts['collisions']),
                     indent=2, sort_keys=True))
    return 0 if not reasons else 2


def _authorized(args, environment):
    """Refused here, before any token is read or provider contacted."""
    manifest, sha = load_session(args.session_dir)
    packet = remote_authorization.load(args.authorization)
    reasons = remote_authorization.validate(packet, manifest, sha, environment.wall())
    if reasons:
        print(json.dumps(dict(ok=False, code='authorization_refused', reasons=reasons), indent=2))
        return None
    gate = remote_authorization.MutationGate(packet, manifest, sha, environment.wall)
    provider = do_api.DigitalOceanProvisioningProvider(environment.transport_factory(args.token_file), gate=gate, wall=environment.wall)
    return manifest, sha, packet, provider


def cmd_provision(args, environment):
    authorized = _authorized(args, environment)
    if authorized is None:
        return 2
    manifest, sha, packet, provider = authorized
    session_dir = pathlib.Path(args.session_dir)

    def on_armed(ack):
        path = session_dir / 'arm-ack.json'
        do_session.write_new(path, json.dumps(ack, indent=2, sort_keys=True) + '\n')
        do_session.append_journal(session_dir, dict(kind='t0', manifest_sha256=sha, t0_utc=ack['t0_utc']))

    def on_ready(ack, evidence_ref):
        do_session.append_journal(session_dir, dict(kind='pair_ready', manifest_sha256=sha, ready_at=ack['ready_at'], evidence_ref=evidence_ref))

    guests = environment.guests_factory(args.ssh_key, session_dir)
    run = provisioner.Provisioner(environment.registry_factory(args.registry_command), provider, guests, manifest, sha, packet,
                                  provisioner.Evidence(session_dir / 'provisioning', environment.wall), pathlib.Path(args.public_key).read_text().strip(),
                                  environment.sleep, environment.monotonic, environment.wall, on_armed=on_armed, on_ready=on_ready)
    result = run.run()
    print(json.dumps(dict(status=result.status, code=result.code, detail=result.detail, droplets=result.droplets, firewall_id=result.firewall_id,
                          fencing_token=result.fencing_token, evidence_ref=result.evidence_ref), indent=2, sort_keys=True))
    return 0 if result.status == provisioner.READY else 2


def cmd_refresh_access(args, environment):
    authorized = _authorized(args, environment)
    if authorized is None:
        return 2
    manifest, _, _, provider = authorized
    client = environment.registry_factory(args.registry_command)
    evidence = provisioner.Evidence(pathlib.Path(args.session_dir) / 'provisioning', environment.wall)
    try:
        token = args.fencing_token
        if token is None:
            token = client.acquire(manifest['session']['id'])['fencing_token']
        outcome = provisioner.refresh_access(client, provider, manifest, token, args.ssh_source, args.udp_source, environment.sleep,
                                             environment.monotonic, evidence=evidence)
    except session_access.AccessRefused as refused:
        print(json.dumps(dict(applied=False, code='access_refused', detail=str(refused))))
        return 2
    except provisioner.Stop as stop:
        print(json.dumps(dict(applied=False, code=stop.code, detail=stop.detail)))
        return 2
    except create_evidence.CreateNotSent as refused:
        print(json.dumps(dict(applied=False, code='mutation_refused', detail=cleanup_provider.redact(refused))))
        return 2
    except (cleanup_provider.ProviderError, registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
        print(json.dumps(dict(applied=False, code='refresh_failed', detail=cleanup_provider.redact(error))))
        return 2
    print(json.dumps(dict(outcome, fencing_token=token), indent=2, sort_keys=True))
    return 0 if outcome['applied'] else 2


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    digests = sub.add_parser('source-digests')
    digests.add_argument('--repo', required=True)
    digests.add_argument('--sha', required=True)
    digests.set_defaults(func=cmd_source_digests)

    def session_command(name, func):
        item = sub.add_parser(name)
        item.add_argument('--session-dir', required=True)
        item.add_argument('--token-file', required=True)
        item.add_argument('--registry-command', required=True, help='e.g. "ssh ... mgmt omega-do-registry rpc"; see registry_client.ssh_argv')
        item.set_defaults(func=func)
        return item

    session_command('preflight', cmd_preflight)
    provision = session_command('provision', cmd_provision)
    provision.add_argument('--authorization', required=True)
    provision.add_argument('--ssh-key', required=True, help='path only: the private key is passed to ssh and never read here')
    provision.add_argument('--public-key', default=str(guest_bootstrap.PUBLIC_KEY_PATH))
    refresh = session_command('refresh-access', cmd_refresh_access)
    refresh.add_argument('--authorization', required=True)
    refresh.add_argument('--fencing-token', type=int)
    refresh.add_argument('--ssh-source', action='append', required=True)
    refresh.add_argument('--udp-source', action='append', default=[])
    return parser


def main(argv=None, environment=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, environment or Environment())
    except (OSError, ValueError, subprocess.CalledProcessError, manifest_mod.ManifestError) as error:
        print(json.dumps(dict(error=type(error).__name__ + ': ' + cleanup_provider.redact(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
