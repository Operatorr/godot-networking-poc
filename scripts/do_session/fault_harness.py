#!/usr/bin/env python3
"""Offline process-level crash fixture: die for real at a named side-effect boundary.

The fixtures run this as a child process, which calls ``os._exit`` at the Nth hit of a registry
failpoint with no cleanup, as ``kill -9`` would. The parent then reopens the same state directory
and asserts what survived. It uses a scripted clock and a file-backed fake provider, so it never
touches a network or an account.

    fault_harness.py watchdog   --state-dir D --account F --failpoint P [--hit N] --wall W --mono M --boot B --steps K
    fault_harness.py controller --state-dir D --account F --failpoint P [--hit N] --wall W --mono M --boot B --session S
"""
import argparse
import os
import sys

import fake_provider
import fixture_support as fx
import registry
import registry_client
import watchdog

CRASH_EXIT = 137


def crash_at(point, hit):
    remaining = [hit]

    def failpoint(name):
        if name == point:
            remaining[0] -= 1
            if remaining[0] == 0:
                os._exit(CRASH_EXIT)
    return failpoint


def find_existing(provider, session_id):
    """The reconcile step: look an intent up by its unique name and session tag."""
    tag = 'omega-session:' + session_id

    def find(grant):
        kind, name = grant['kind'], grant['expected_name']
        if kind == 'droplet':
            matches = [d['id'] for d in provider.list_droplets_by_tag(tag) if d['name'] == name]
        elif kind == 'firewall':
            matches = [f['id'] for f in provider.list_firewalls_by_name(name)]
        else:
            matches = [name] if provider.get_tag(name) else []
        return matches[0] if matches else None
    return find


def create_for(provider):
    def create(grant):
        kind, name, tags = grant['kind'], grant['expected_name'], grant['expected_tags']
        if kind == 'droplet':
            return provider.add_droplet(name, tags)
        if kind == 'firewall':
            return provider.add_firewall(name, tags=tags)
        provider.add_tag(name)
        return name
    return create


def controller_flow(reg, wd_tick, provider, session_id):
    """One whole session, with request ids a restarted controller would reuse, then cleanup."""
    manifest, sha = fx.session_manifest(session_id)
    client = registry_client.RegistryClient(registry_client.LocalTransport(reg), 'controller-a', attempts=1)
    client.register(manifest, sha, request_id='r-register')
    token = client.acquire(session_id, request_id='r-acquire')['fencing_token']
    wd_tick()
    client.arm(session_id, manifest, sha, token, request_id='r-arm')
    wd_tick()
    find, create = find_existing(provider, session_id), create_for(provider)
    # A restarted controller reads durable state and continues; it does not replay finished stages.
    status = reg.status(session_id)
    if status['state'] == registry.PROVISIONING:
        created = {i['intent_id'] for i in status['intents'] if i['state'] == 'created'}
        for suffix in ('tag:session', 'tag:game', 'tag:bot', 'firewall', 'droplet:game', 'droplet:bot'):
            intent = session_id + ':' + suffix
            if intent not in created:
                client.guarded_create(session_id, intent, token, create, find, request_id='r-create-' + intent)
        client.mutate('mark_ready', 'r-ready', session_id=session_id, fencing_token=token, evidence_ref='readiness/fake.json')
    if not reg.runs(session_id) or reg.status(session_id)['state'] == registry.RUNNING:
        client.mutate('dispatch_run', 'r-dispatch', session_id=session_id, run_id='run-1', fencing_token=token,
                      manifest_sha256=sha, estimated_duration_s=60)
    if reg.runs(session_id)[0]['outcome'] is None:
        client.mutate('record_run_outcome', 'r-outcome', session_id=session_id, run_id='run-1', outcome='PASS',
                      fencing_token=token, evidence_ref='runs/run-1')
    client.mutate('request_cleanup', 'r-cleanup', session_id=session_id, fencing_token=token, reason='batch finished')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('watchdog', 'controller'))
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--failpoint', required=True)
    parser.add_argument('--hit', type=int, default=1)
    parser.add_argument('--wall', type=float, required=True)
    parser.add_argument('--mono', type=float, required=True)
    parser.add_argument('--boot', required=True)
    parser.add_argument('--steps', type=int, default=200)
    parser.add_argument('--session', default=None)
    args = parser.parse_args(argv)

    clock = fx.ScriptedClock(args.wall, args.mono, args.boot)
    provider = fake_provider.FakeProvider(args.account, clock=clock)
    failpoint = crash_at(args.failpoint, args.hit)
    if args.mode == 'watchdog':
        service = watchdog.Watchdog(registry.Registry(args.state_dir, clock=clock, failpoint=failpoint), provider,
                                    executor=watchdog.InlineExecutor())
        service.start()
        for _ in range(args.steps):
            clock.advance(1)
            service.tick()
    else:
        # The watchdog is a separate service, so the controller's failpoints never fire inside it.
        service = watchdog.Watchdog(registry.Registry(args.state_dir, clock=clock), provider, executor=watchdog.InlineExecutor())
        service.start()
        controller_flow(registry.Registry(args.state_dir, clock=clock, failpoint=failpoint), service.tick, provider, args.session)
    return 0


if __name__ == '__main__':
    sys.exit(main())
