"""Real processes: the CLI transport, kill -9 at every side-effect boundary, the service unit."""
import json
import logging
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

import create_evidence
import fake_provider
import fault_harness
import fixture_support as fx
import registry
import registry_cli
import registry_client
import session_clock
import watchdog

HERE = pathlib.Path(__file__).parent
SESSION = 'do-cap-1v1g-20261030a'
UNIT = HERE.parent.parent / 'deployment' / 'do-watchdog' / 'omega-do-watchdog.service'
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
STRAY = 'stray-production-host'


def run_harness(*args):
    return subprocess.run([sys.executable, str(HERE / 'fault_harness.py')] + [str(a) for a in args], env=ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)


def cli(state_dir, *args, stdin=None):
    return subprocess.run([sys.executable, str(HERE / 'registry_cli.py')] + list(args[:1]) + ['--state-dir', str(state_dir)] + list(args[1:]),
                          env=ENV, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)


def cli_help():
    return b''.join(subprocess.run([sys.executable, str(HERE / 'registry_cli.py'), command, '--help'], env=ENV, capture_output=True, check=True).stdout
                    for command in ('rpc', 'watchdog', 'dispose-create'))


class ProcessFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.state = self.root / 'state'
        self.account = self.root / 'account.json'
        self.reset()

    def reset(self):
        """A fresh registry and fake account holding one unrelated host, for each matrix case."""
        if self.state.is_dir():
            shutil.rmtree(self.state)
        if self.account.exists():
            self.account.unlink()
        registry.Registry.init(self.state, fx.REGISTRY_ID, fx.WATCHDOG_IDENTITY)
        seed = fake_provider.FakeProvider(self.account)
        self.stray = seed.add_droplet(STRAY, ['production'])
        seed.add_tag('production')
        seed.answer_all_requests()      # a crash leaves requests unresolved until the fake's receipts settle them

    def reopen(self, wall, mono, boot):
        clock = fx.ScriptedClock(wall, mono, boot)
        reg = registry.Registry(self.state, clock=clock, trusted_settlement_bases=create_evidence.OFFLINE_FIXTURE_BASES)
        self.addCleanup(reg.close)
        provider = fake_provider.FakeProvider(self.account, clock=clock)
        service = watchdog.Watchdog(reg, provider, executor=watchdog.InlineExecutor())
        service.start(pid=77)
        return clock, reg, provider, service

    def drive_until_closed(self, clock, reg, service, limit=1200):
        for _ in range(limit):
            clock.advance(1)
            service.tick()
            if reg.status(SESSION)['state'] == registry.CLOSED:
                return
        self.fail('session never closed: ' + json.dumps(reg.status(SESSION)['resources']))

    def assert_cleanup_invariants(self, reg, provider, original_deadlines):
        status = reg.status(SESSION)
        self.assertEqual(status['state'], registry.CLOSED)
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual((status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc']), original_deadlines)
        live = provider.live_ids()
        self.assertEqual(live['droplets'], [self.stray], 'only the unrelated host survives')
        self.assertEqual(live['firewalls'], [])
        self.assertEqual(live['tags'], ['production'])
        bursts = {}
        for attempt in reg.attempts(SESSION):
            self.assertIsNotNone(attempt['finished_at'], 'no attempt is left unresolved after recovery')
            key = (attempt['resource_key'], attempt['sweep_seq'])
            bursts[key] = bursts.get(key, 0) + 1
        self.assertLessEqual(max(bursts.values()), 6, 'a crash never buys more than six attempts per burst')
        self.assertTrue(reg.verify_journal()['valid'])
        journal = reg.journal(SESSION)
        intents = [e['seq'] for e in journal if e['kind'] == 'cleanup_intent']
        accepted = [e['seq'] for e in journal if e['kind'] == 'delete_accepted']
        self.assertEqual(len(intents), 1, 'cleanup intent is recorded exactly once')
        if accepted:
            self.assertLess(intents[0], accepted[0])
        self.assertNotIn(self.stray, {o['target'] for o in json.loads(self.account.read_text()).get('ops', [])})


class WatchdogCrashMatrix(ProcessFixture):
    POINTS = ('wd_recover:before_commit', 'wd_recover:after_commit', 'wd_tick:before_commit', 'wd_tick:after_commit',
              'wd_start_attempt:before_commit', 'wd_start_attempt:after_commit', 'wd_request:before', 'wd_request:after',
              'wd_finish_attempt:before_commit', 'wd_finish_attempt:after_commit')

    def prepare(self, abort=True):
        """A ready session whose controller has already gone away."""
        clock = fx.ScriptedClock()
        reg = registry.Registry(self.state, clock=clock)
        provider = fake_provider.FakeProvider(self.account, clock=clock)
        service = watchdog.Watchdog(reg, provider, executor=watchdog.InlineExecutor())
        service.start(pid=1)
        manifest, sha = fx.session_manifest(SESSION)
        client = registry_client.RegistryClient(registry_client.LocalTransport(reg), 'controller-a', attempts=1)
        client.register(manifest, sha)
        token = client.acquire(SESSION)['fencing_token']
        service.tick()
        client.arm(SESSION, manifest, sha, token)
        service.tick()
        create, find = fault_harness.create_for(provider), fault_harness.find_existing(provider, SESSION)
        for suffix in ('tag:session', 'tag:game', 'tag:bot', 'firewall', 'droplet:game', 'droplet:bot'):
            client.guarded_create(SESSION, SESSION + ':' + suffix, token, create, find)
        client.mutate('mark_ready', session_id=SESSION, fencing_token=token, evidence_ref='readiness/fake.json')
        status = reg.status(SESSION)
        original = (status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc'])
        if abort:
            reg.operator_abort(SESSION, 'operator stopped the batch')
        wall, mono = clock.wall_value, clock.mono_value
        reg.close()
        return wall, mono, original

    def test_crash_at_every_boundary_then_restart_still_verifies_cleanup(self):
        reached = set()
        for point in self.POINTS:
            for hit in (1, 2, 3, 5, 8, 13):
                if point.startswith('wd_recover') and hit > 1:
                    continue
                for reboot in (False, True):
                    if reboot and hit not in (1, 5):
                        continue
                    with self.subTest(point=point, hit=hit, reboot=reboot):
                        self.reset()
                        wall, mono, original = self.prepare()
                        outcome = run_harness('watchdog', '--state-dir', self.state, '--account', self.account, '--failpoint', point,
                                              '--hit', hit, '--wall', wall + 1, '--mono', mono + 1, '--boot', 'boot-a', '--steps', 400)
                        self.assertIn(outcome.returncode, (0, fault_harness.CRASH_EXIT), outcome.stderr.decode())
                        if outcome.returncode == fault_harness.CRASH_EXIT:
                            reached.add(point)
                        if reboot:
                            clock, reg, provider, service = self.reopen(wall + 700, 5.0, 'boot-b')
                        else:
                            clock, reg, provider, service = self.reopen(wall + 700, mono + 700, 'boot-a')
                        if reg.status(SESSION)['state'] != registry.CLOSED:
                            self.drive_until_closed(clock, reg, service)
                        self.assert_cleanup_invariants(reg, provider, original)
                        reg.close()
        self.assertEqual(reached, set(self.POINTS), 'every boundary was actually crashed through')

    def test_crash_while_failing_closed_on_an_unverifiable_reboot_loses_nothing(self):
        for point in ('wd_recover:before_commit', 'wd_recover:after_commit', 'wd_tick:before_commit', 'wd_tick:after_commit'):
            with self.subTest(point=point):
                self.reset()
                wall, mono, original = self.prepare(abort=False)
                behind = wall - 86400       # the RTC is a day slow, so downtime is unknowable
                outcome = run_harness('watchdog', '--state-dir', self.state, '--account', self.account, '--failpoint', point,
                                      '--wall', behind, '--mono', 5.0, '--boot', 'boot-b', '--steps', 3)
                self.assertEqual(outcome.returncode, fault_harness.CRASH_EXIT, outcome.stderr.decode())
                clock, reg, provider, service = self.reopen(behind + 1, 6.0, 'boot-b')
                status = reg.status(SESSION)
                self.assertEqual(status['state'], registry.DELETING)
                self.assertEqual(status['cleanup']['reason'], registry.CLOCK_UNVERIFIABLE_REASON)
                self.assertTrue(status['cleanup']['deadline_uncertain'])
                self.assertEqual([i['kind'] for i in status['incidents']], ['cleanup-overdue'])
                self.drive_until_closed(clock, reg, service)
                self.assert_cleanup_invariants(reg, provider, original)
                reg.close()

    def test_watchdog_killed_mid_outage_keeps_one_overdue_incident(self):
        wall, mono, original = self.prepare(abort=False)
        d = session_clock.parse(original[2])
        data = json.loads(self.account.read_text())
        self.assertEqual(len([d_ for d_ in data['droplets'] if d_ != self.stray]), 2)
        clock, reg, provider, service = self.reopen(d - 3, mono + (d - 3 - wall), 'boot-a')
        provider.fail(lambda: fake_provider.cleanup_provider.ProviderTransient('503', status=503))
        for _ in range(10):
            clock.advance(1)
            service.tick()
        reg.close()
        clock, reg, provider, service = self.reopen(clock.wall_value, clock.mono_value, 'boot-a')
        for _ in range(60):
            clock.advance(1)
            service.tick()
        overdue = [i for i in reg.incidents(SESSION) if i['kind'] == 'cleanup-overdue']
        self.assertEqual(len(overdue), 1)
        self.drive_until_closed(clock, reg, service)
        self.assert_cleanup_invariants(reg, provider, original)
        self.assertEqual(reg.incidents(SESSION)[0]['status'], 'resolved')


class ControllerCrashMatrix(ProcessFixture):
    METHODS = ('register_session', 'acquire_control', 'arm_session', 'begin_create', 'record_resource', 'mark_ready',
               'dispatch_run', 'record_run_outcome', 'request_cleanup')

    def boundary_cases(self):
        for method in self.METHODS:
            for phase in ('before_commit', 'after_commit'):
                yield method + ':' + phase, 1
        # The Droplet creates are the riskiest: crash around the fifth and sixth intents as well.
        for hit in (5, 6):
            for point in ('begin_create:before_commit', 'begin_create:after_commit',
                          'record_resource:before_commit', 'record_resource:after_commit'):
                yield point, hit

    def crash(self, point, hit):
        outcome = run_harness('controller', '--state-dir', self.state, '--account', self.account, '--failpoint', point, '--hit', hit,
                              '--wall', fx.T0_WALL, '--mono', 1000.0, '--boot', 'boot-a', '--session', SESSION)
        self.assertEqual(outcome.returncode, fault_harness.CRASH_EXIT, point + ' was not reached: ' + outcome.stderr.decode())

    def deadlines_if_armed(self, reg):
        rows = [s for s in reg.list_sessions() if s['session_id'] == SESSION]
        if not rows:
            return None
        status = reg.status(SESSION)
        return (status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc']) if status['t0_utc'] else None

    def test_controller_lost_at_any_boundary_never_escapes_cleanup(self):
        for point, hit in self.boundary_cases():
            with self.subTest(point=point, hit=hit):
                self.reset()
                self.crash(point, hit)
                clock, reg, provider, service = self.reopen(fx.T0_WALL + 2, 1002.0, 'boot-a')
                original = self.deadlines_if_armed(reg)
                live_before = provider.live_ids()
                created = [d for d in live_before['droplets'] if d != self.stray]
                if original is None:
                    self.assertEqual(created, [], 'nothing can exist before the deadline was durable')
                    self.assertEqual(live_before['firewalls'], [])
                    reg.close()
                    continue
                # Nobody returns: only the persisted deadline stands between us and a billable orphan.
                c = session_clock.parse(original[1])
                clock.wall_value, clock.mono_value = c - 1, 1002.0 + (c - 1 - (fx.T0_WALL + 2))
                self.drive_until_closed(clock, reg, service)
                self.assert_cleanup_invariants(reg, provider, original)
                reg.close()

    def test_controller_retrying_the_same_requests_converges_without_duplicates(self):
        for point, hit in self.boundary_cases():
            with self.subTest(point=point, hit=hit):
                self.reset()
                self.crash(point, hit)
                clock = fx.ScriptedClock(fx.T0_WALL + 3, 1003.0, 'boot-a')
                provider = fake_provider.FakeProvider(self.account, clock=clock)
                reg_probe = fault_harness.open_registry(self.state, clock)
                self.addCleanup(reg_probe.close)
                before = self.deadlines_if_armed(reg_probe)
                service = watchdog.Watchdog(reg_probe, provider, executor=watchdog.InlineExecutor())
                service.start(pid=2)
                reg_client = fault_harness.open_registry(self.state, clock)
                self.addCleanup(reg_client.close)
                fault_harness.controller_flow(reg_client, service.tick, provider, SESSION)
                status = reg_probe.status(SESSION)
                if before is not None:
                    self.assertEqual((status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc']), before,
                                     'a retry can never move the deadline')
                data = json.loads(self.account.read_text())
                names = [d['name'] for k, d in data['droplets'].items() if k != self.stray]
                self.assertEqual(sorted(names), [SESSION + '-bot', SESSION + '-game'], 'no duplicate Droplets')
                self.assertEqual(len(data['firewalls']), 1, 'no duplicate firewall')
                self.assertEqual(len(reg_probe.runs(SESSION)), 1, 'no second run')
                self.assertEqual(status['state'], registry.DELETING)
                reg_probe.close()
                reg_client.close()


class CliTransportTests(ProcessFixture):
    def client(self):
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]
        return registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'controller-a', attempts=2, retry_delay_s=0)

    def test_rpc_over_a_real_process_acknowledges_durably(self):
        manifest, sha = fx.session_manifest(SESSION)
        ack = self.client().register(manifest, sha, request_id='cli-1')
        self.assertEqual(ack['manifest_sha256'], sha)
        replay = self.client().register(manifest, sha, request_id='cli-1')
        self.assertTrue(replay['replayed'])
        status = cli(self.state, 'status', '--session', SESSION)
        self.assertEqual(status.returncode, 0, status.stderr.decode())
        self.assertEqual(json.loads(status.stdout)['state'], registry.REGISTERED)

    def test_missing_state_gives_no_acknowledgement_and_no_create(self):
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.root / 'lost')]
        client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'c', attempts=2, retry_delay_s=0)
        creates = []
        with self.assertRaises(registry_client.RegistryUnavailable):
            client.guarded_create(SESSION, SESSION + ':droplet:game', 1, lambda g: creates.append(g), lambda g: None)
        self.assertEqual(creates, [])
        self.assertFalse((self.root / 'lost').exists(), 'the CLI must not recreate lost state')

    def test_transport_failures_count_as_no_ack(self):
        for argv in (['false'], [sys.executable, '-c', 'print("not json")'], ['/nonexistent/omega-do-registry']):
            with self.subTest(argv=argv[0]):
                client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'c', attempts=1)
                with self.assertRaises(registry_client.RegistryUnavailable):
                    client.call('status', session_id=SESSION)

    def test_slow_registry_times_out_as_no_ack(self):
        argv = [sys.executable, '-c', 'import time; time.sleep(5)']
        client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv, timeout_s=0.1), 'c', attempts=1)
        with self.assertRaises(registry_client.RegistryUnavailable):
            client.call('status', session_id=SESSION)

    def test_ssh_transport_is_key_only_and_host_verified(self):
        argv = registry_client.ssh_argv('omega@mgmt')
        joined = ' '.join(argv)
        for required in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'PasswordAuthentication=no'):
            self.assertIn(required, joined)
        self.assertNotIn('StrictHostKeyChecking=no', joined)

    def test_watchdog_refuses_without_a_real_provider(self):
        missing = cli(self.state, 'watchdog')
        self.assertEqual(missing.returncode, 2, 'the provider is a required argument')
        for bad in ('', 'no_such_module:factory', 'fake_provider:no_such_factory', 'fake_provider'):
            with self.subTest(provider=bad):
                result = cli(self.state, 'watchdog', '--provider', bad)
                self.assertEqual(result.returncode, 1, result.stderr.decode())

    def test_watchdog_refuses_the_fake_provider_unless_explicitly_allowed(self):
        result = cli(self.state, 'watchdog', '--provider', 'fake_provider:from_file', '--provider-arg', str(self.account))
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'--allow-offline-fake', result.stderr)

    def test_init_refuses_to_overwrite_and_verify_journal_passes(self):
        again = cli(self.state, 'init', '--registry-id', 'x', '--watchdog-identity', 'y')
        self.assertEqual(again.returncode, 1)
        self.assertEqual(json.loads(cli(self.state, 'verify-journal').stdout)['valid'], True)

    def test_operator_abort_and_listing_commands(self):
        manifest, sha = fx.session_manifest(SESSION)
        self.client().register(manifest, sha)
        self.assertEqual(cli(self.state, 'abort', '--session', SESSION, '--reason', 'operator').returncode, 0)
        self.assertEqual(json.loads(cli(self.state, 'sessions').stdout)[0]['state'], registry.CLOSED)
        self.assertEqual(cli(self.state, 'health', '--session', SESSION).returncode, 0)
        self.assertEqual(cli(self.state, 'incidents', '--session', SESSION).returncode, 0)
        self.assertIn(b'closed_never_armed', cli(self.state, 'journal', '--session', SESSION).stdout)
        self.assertEqual(cli(self.state, 'status', '--session', 'nope').returncode, 2)


class ConcurrentProcessTests(ProcessFixture):
    """Controllers racing through separate processes against one state directory."""

    def race(self, requests):
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]
        started = [subprocess.Popen(argv, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                   for _ in requests]
        for process, request in zip(started, requests):
            process.stdin.write(json.dumps(request).encode())
            process.stdin.close()
        responses = []
        for process in started:
            responses.append(json.loads(process.stdout.read()))
            process.stdout.close()
            process.stderr.close()
            process.wait()
        return responses

    def test_exactly_one_of_many_racing_controllers_gets_the_token(self):
        manifest, sha = fx.session_manifest(SESSION)
        reg = registry.Registry(self.state)
        self.addCleanup(reg.close)
        reg.register_session(manifest, sha, request_id='setup')
        responses = self.race([dict(method='acquire_control', params=dict(session_id=SESSION, controller_id='c' + str(i), request_id='race-' + str(i)))
                               for i in range(6)])
        winners = [r for r in responses if r['ok']]
        self.assertEqual(len(winners), 1, responses)
        self.assertEqual(winners[0]['result']['fencing_token'], 1)
        self.assertEqual({r['code'] for r in responses if not r['ok']}, {'control_held'})

    def test_production_rpc_refuses_every_receipt_and_offers_no_way_to_trust_one(self):
        clock = fx.ScriptedClock(wall=time.time(), mono=time.monotonic(), boot=session_clock.UNKNOWN_BOOT)
        clock.wall = time.time
        clock.mono = time.monotonic
        reg = fault_harness.open_registry(self.state, clock)
        self.addCleanup(reg.close)
        service = watchdog.Watchdog(reg, fake_provider.FakeProvider(self.account), executor=watchdog.InlineExecutor())
        service.start(pid=1)
        manifest, sha = fx.session_manifest(SESSION)
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]
        client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'controller-a', attempts=2, retry_delay_s=0)
        client.register(manifest, sha)
        token = client.acquire(SESSION)['fencing_token']
        service.tick()
        client.arm(SESSION, manifest, sha, token)
        service.tick()
        intent = SESSION + ':droplet:game'
        client.mutate('begin_create', session_id=SESSION, intent_id=intent, fencing_token=token)
        receipt = fake_provider.FakeProvider.offline_receipt(intent + '#1', create_evidence.NOT_CREATED)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            client.mutate('record_create_settlement', session_id=SESSION, intent_id=intent, settlement=receipt, fencing_token=token)
        self.assertEqual(caught.exception.code, 'untrusted_settlement_basis')
        self.assertNotIn(b'trust', cli_help(), 'no runtime switch can widen what counts as evidence')
        status = json.loads(cli(self.state, 'status', '--session', SESSION).stdout)
        self.assertEqual(next(i for i in status['intents'] if i['intent_id'] == intent)['state'], 'requested')

    def test_dispose_create_cli_needs_cleanup_and_labels_the_session(self):
        clock = fx.ScriptedClock(wall=time.time(), mono=time.monotonic(), boot=session_clock.UNKNOWN_BOOT)
        clock.wall = time.time
        clock.mono = time.monotonic
        reg = fault_harness.open_registry(self.state, clock)
        self.addCleanup(reg.close)
        service = watchdog.Watchdog(reg, fake_provider.FakeProvider(self.account), executor=watchdog.InlineExecutor())
        service.start(pid=1)
        manifest, sha = fx.session_manifest(SESSION)
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]
        client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'controller-a', attempts=2, retry_delay_s=0)
        client.register(manifest, sha)
        token = client.acquire(SESSION)['fencing_token']
        service.tick()
        client.arm(SESSION, manifest, sha, token)
        service.tick()
        intent = SESSION + ':droplet:game'
        client.mutate('begin_create', session_id=SESSION, intent_id=intent, fencing_token=token)
        early = cli(self.state, 'dispose-create', '--session', SESSION, '--intent', intent, '--note', 'too early')
        self.assertEqual(early.returncode, 2, early.stderr.decode())
        self.assertEqual(cli(self.state, 'abort', '--session', SESSION, '--reason', 'unknown create').returncode, 0)
        done = cli(self.state, 'dispose-create', '--session', SESSION, '--intent', intent, '--note', 'checked by hand')
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        self.assertEqual(json.loads(done.stdout)['state'], 'operator_disposed')

    def test_racing_dispatches_with_one_token_start_exactly_one_run(self):
        clock = fx.ScriptedClock(wall=time.time(), mono=time.monotonic(), boot=session_clock.UNKNOWN_BOOT)
        clock.wall = time.time
        clock.mono = time.monotonic
        reg = registry.Registry(self.state, clock=clock)
        self.addCleanup(reg.close)
        provider = fake_provider.FakeProvider(self.account)
        service = watchdog.Watchdog(reg, provider, executor=watchdog.InlineExecutor())
        service.start(pid=1)
        manifest, sha = fx.session_manifest(SESSION)
        client = registry_client.RegistryClient(registry_client.LocalTransport(reg), 'controller-a', attempts=1)
        client.register(manifest, sha)
        token = client.acquire(SESSION)['fencing_token']
        service.tick()
        client.arm(SESSION, manifest, sha, token)
        service.tick()
        create, find = fault_harness.create_for(provider), fault_harness.find_existing(provider, SESSION)
        for suffix in ('droplet:game', 'droplet:bot'):
            client.guarded_create(SESSION, SESSION + ':' + suffix, token, create, find)
        client.mutate('mark_ready', session_id=SESSION, fencing_token=token, evidence_ref='readiness/fake.json')
        responses = self.race([dict(method='dispatch_run', params=dict(session_id=SESSION, run_id='run-' + str(i), fencing_token=token,
                                                                       manifest_sha256=sha, estimated_duration_s=60, request_id='d-' + str(i)))
                               for i in range(5)])
        self.assertEqual(sum(1 for r in responses if r['ok']), 1, responses)
        self.assertEqual(len(reg.runs(SESSION)), 1)


class RealServiceTests(ProcessFixture):
    """The actual service process on real clocks: lost controller, real SIGKILL, restart."""

    def start_service(self):
        process = subprocess.Popen([sys.executable, str(HERE / 'registry_cli.py'), 'watchdog', '--state-dir', str(self.state),
                                    '--provider', 'fake_provider:from_file', '--provider-arg', str(self.account), '--allow-offline-fake',
                                    '--tick-interval-s', '0.05', '--sweep-interval-s', '0.3'],
                                   env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HERE))
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        return process

    def poll(self, predicate, limit_s=30.0):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.05)
        self.fail('condition not reached in real time')

    def test_sigkill_during_cleanup_after_the_controller_vanished(self):
        # Deletion starts at C, about 9 s from now, and read-only preparation has already begun by then.
        manifest, sha = fx.session_manifest(SESSION, cap_s=10, reserve_s=1, grace_s=1)
        argv = [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]
        client = registry_client.RegistryClient(registry_client.SubprocessTransport(argv), 'controller-a', attempts=2, retry_delay_s=0)
        service = self.start_service()
        client.register(manifest, sha)
        token = client.acquire(SESSION)['fencing_token']

        def try_arm():
            try:
                return client.arm(SESSION, manifest, sha, token)
            except registry_client.RegistryRejected as rejection:
                self.assertIn(rejection.code, ('watchdog_unhealthy', 'watchdog_unacknowledged'))
                return None

        ack = self.poll(try_arm)
        provider = fake_provider.FakeProvider(self.account)
        create, find = fault_harness.create_for(provider), fault_harness.find_existing(provider, SESSION)

        def try_create():
            try:
                return client.guarded_create(SESSION, SESSION + ':droplet:game', token, create, find)
            except registry_client.RegistryRejected as rejection:
                self.assertEqual(rejection.code, 'watchdog_unacknowledged')
                return None

        self.poll(try_create)
        client.guarded_create(SESSION, SESSION + ':droplet:bot', token, create, find)
        del client      # the controller vanishes; nothing it holds is needed from here on

        def ops():
            return json.loads(self.account.read_text()).get('ops', [])

        self.poll(lambda: any(o['op'] == 'delete_droplet' for o in ops()))
        service.send_signal(signal.SIGKILL)
        service.wait()
        self.start_service()
        reader = registry.Registry(self.state)
        self.addCleanup(reader.close)
        self.poll(lambda: reader.status(SESSION)['state'] == registry.CLOSED, limit_s=60)
        status = reader.status(SESSION)
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual(status['cleanup']['reason'], 'deadline_C')
        self.assertEqual(status['t0_utc'], ack['t0_utc'])
        live = json.loads(self.account.read_text())['droplets']
        self.assertEqual(list(live), [self.stray])
        kinds = [e['kind'] for e in reader.journal()]
        self.assertGreaterEqual(kinds.count('watchdog_started'), 2)


class ServiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.unit = UNIT.read_text()

    def test_unit_is_supervised_boot_enabled_and_restart_forever(self):
        for required in ('Restart=always', 'WantedBy=multi-user.target', 'StartLimitIntervalSec=0', 'StateDirectory=omega-do-watchdog'):
            self.assertIn(required, self.unit)

    def test_unit_is_portable_and_holds_no_secret_or_host_identity(self):
        self.assertIsNone(re.search(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', self.unit), 'no fixed address')
        self.assertNotIn('dop_v1_', self.unit)
        self.assertNotRegex(self.unit, r'(?im)^Environment=.*TOKEN')
        self.assertNotIn('digitalocean.com', self.unit)
        self.assertNotIn('omega_loadtest_ed25519', self.unit, 'the watchdog never receives the SSH key')

    def test_errors_reach_the_journal_at_error_priority(self):
        record = logging.LogRecord('omega.do_watchdog', logging.ERROR, __file__, 1, 'overdue', None, None)
        self.assertTrue(registry_cli.SyslogPrefixFormatter('%(message)s').format(record).startswith('<3>'))

    def test_unit_cannot_start_without_a_configured_provider(self):
        self.assertIn('--provider ${OMEGA_DO_PROVIDER}', self.unit)
        self.assertIn('EnvironmentFile=/etc/omega-do-watchdog/watchdog.env', self.unit)


if __name__ == '__main__':
    unittest.main()
