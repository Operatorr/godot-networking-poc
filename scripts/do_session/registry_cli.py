#!/usr/bin/env python3
"""Management-host CLI for the session registry and cleanup watchdog. No token passes through here.

    registry_cli.py init     --state-dir D --registry-id R --watchdog-identity W
    registry_cli.py rpc      --state-dir D                  # one JSON request on stdin, one response on stdout
    registry_cli.py watchdog --state-dir D --provider MODULE:FACTORY [--provider-arg ARG]
                             # --allow-offline-fake is required to run against fake_provider
    registry_cli.py status   --state-dir D --session S
    registry_cli.py health   --state-dir D [--session S]
    registry_cli.py sessions|incidents|journal|verify-journal --state-dir D [--session S]
    registry_cli.py abort    --state-dir D --session S --reason TEXT
    registry_cli.py disown   --state-dir D --session S --resource KEY --note TEXT
    registry_cli.py dispose-create --state-dir D --session S --intent ID --note TEXT

``watchdog`` refuses to start without an explicit provider factory; there is no silent no-op mode.
Exit codes: 0 done, 2 refused, 1 storage or configuration failure.
"""
import argparse
import importlib
import json
import logging
import os
import signal
import sqlite3
import sys
import threading

import cleanup_ledger
import create_evidence
import registry as registry_mod
import watchdog as watchdog_mod

SYSLOG_PREFIX = {logging.ERROR: '<3>', logging.CRITICAL: '<2>', logging.WARNING: '<4>', logging.INFO: '<6>'}


class SyslogPrefixFormatter(logging.Formatter):
    """systemd reads a leading <n> as the journal priority, so ERROR records are journal errors."""

    def format(self, record):
        return SYSLOG_PREFIX.get(record.levelno, '<7>') + super().format(record)


def configure_logging():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(SyslogPrefixFormatter('%(name)s %(message)s'))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def load_provider(spec, argument, allow_offline_fake=False):
    module_name, _, factory_name = spec.partition(':')
    if not module_name or not factory_name:
        raise ValueError('--provider must be MODULE:FACTORY')
    factory = getattr(importlib.import_module(module_name), factory_name)
    provider = factory(argument) if argument is not None else factory()
    if getattr(provider, 'offline_fixture', False) and not allow_offline_fake:
        # A fake account would report real Droplets as absent and close their sessions.
        raise ValueError('refusing an offline fake provider without --allow-offline-fake')
    return provider


def emit(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_init(args):
    registry_mod.Registry.init(args.state_dir, args.registry_id, args.watchdog_identity)
    emit(dict(initialized=True, state_dir=args.state_dir, registry_id=args.registry_id))
    return 0


def cmd_rpc(args):
    # A nonzero exit carries no acknowledgement, so the client treats it as a lost response.
    registry = registry_mod.Registry(args.state_dir)
    try:
        response = registry.rpc(json.loads(sys.stdin.read()))
    finally:
        registry.close()
    print(json.dumps(response, sort_keys=True))
    return 0


def cmd_watchdog(args):
    configure_logging()
    provider = load_provider(args.provider, args.provider_arg, args.allow_offline_fake)
    # Only the offline fake's own receipts are ever trusted here; a real provider has no trusted basis yet.
    trusted = create_evidence.OFFLINE_FIXTURE_BASES if getattr(provider, 'offline_fixture', False) else create_evidence.DEFAULT_TRUSTED_BASES
    registry = registry_mod.Registry(args.state_dir, trusted_settlement_bases=trusted)
    service = watchdog_mod.Watchdog(registry, provider, sweep_interval_s=args.sweep_interval_s)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    service.run_forever(stop, tick_interval_s=args.tick_interval_s)
    return 0


def read_command(args):
    registry = registry_mod.Registry(args.state_dir)
    try:
        if args.command == 'status':
            emit(registry.status(args.session))
        elif args.command == 'health':
            emit(registry.health(args.session))
        elif args.command == 'sessions':
            emit(registry.list_sessions())
        elif args.command == 'incidents':
            emit([registry.incident_report(i['incident_id']) for i in registry.incidents(args.session)])
        elif args.command == 'journal':
            for entry in registry.journal(args.session):
                print(json.dumps(entry, sort_keys=True))
        elif args.command == 'verify-journal':
            result = registry.verify_journal()
            emit(result)
            return 0 if result['valid'] else 1
        elif args.command == 'abort':
            emit(registry.operator_abort(args.session, args.reason))
        elif args.command == 'disown':
            emit(registry.disown_resource(args.session, args.resource, args.note))
        elif args.command == 'dispose-create':
            emit(registry.dispose_create(args.session, args.intent, args.note))
    finally:
        registry.close()
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    def command(name, func, session=None):
        item = sub.add_parser(name)
        item.add_argument('--state-dir', required=True)
        if session is not None:
            item.add_argument('--session', required=session)
        item.set_defaults(func=func)
        return item

    init = command('init', cmd_init)
    init.add_argument('--registry-id', required=True)
    init.add_argument('--watchdog-identity', required=True)
    command('rpc', cmd_rpc)
    service = command('watchdog', cmd_watchdog)
    service.add_argument('--provider', required=True, help='MODULE:FACTORY returning a CleanupProvider')
    service.add_argument('--provider-arg')
    service.add_argument('--allow-offline-fake', action='store_true', help='offline process fixtures only')
    service.add_argument('--tick-interval-s', type=float, default=watchdog_mod.DEFAULT_TICK_INTERVAL_S)
    service.add_argument('--sweep-interval-s', type=float, default=cleanup_ledger.SWEEP_INTERVAL_S,
                         help='the contract is 15 s; only offline process fixtures shorten it')
    command('status', read_command, session=True)
    command('health', read_command, session=False)
    command('sessions', read_command)
    command('incidents', read_command, session=False)
    command('journal', read_command, session=False)
    command('verify-journal', read_command)
    abort = command('abort', read_command, session=True)
    abort.add_argument('--reason', required=True)
    disown = command('disown', read_command, session=True)
    disown.add_argument('--resource', required=True)
    disown.add_argument('--note', required=True)
    dispose = command('dispose-create', read_command, session=True)
    dispose.add_argument('--intent', required=True)
    dispose.add_argument('--note', required=True)
    return parser


def main(argv=None):
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except registry_mod.Rejection as rejection:
        print(json.dumps(rejection.to_response(), sort_keys=True), file=sys.stderr)
        return 2
    except (registry_mod.RegistryUnavailable, watchdog_mod.WatchdogAlreadyRunning, sqlite3.Error,
            ImportError, AttributeError, ValueError, OSError) as error:
        print(json.dumps(dict(error=type(error).__name__ + ': ' + str(error))), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
