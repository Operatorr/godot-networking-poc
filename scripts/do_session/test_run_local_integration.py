"""One controller as a real process, real runner processes, a real registry CLI and watchdog, stand-in workloads on loopback.

Everything is on this machine and real clocks. It proves the execution paths are real, not that they work on a Droplet:
there is no SSH, systemd, /proc, netem or DigitalOcean account here, and the pair's provider view is a JSON file.
``OMEGA_LOCAL_RELEASE_DIR`` adds one run of the real omega-server and omega-load-test binaries when a build is supplied.
"""
import concurrent.futures
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import do_session
import guest_runner
import registry
import run_executor
import run_fault_harness
import run_fixtures as rf
import run_plan
import search

HERE = pathlib.Path(__file__).parent
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
PASS_ALL = json.dumps(dict(default='PASS'))
FAIL_LOW = json.dumps(dict(targets={'25': 'FAIL', '5': 'FAIL'}))


class LocalFixture(unittest.TestCase):
    def session(self, **options):
        temporary = tempfile.mkdtemp(prefix='omega-local-')
        self.addCleanup(shutil.rmtree, temporary, True)
        session = rf.LocalSession(self, temporary, **options)
        session.description = pathlib.Path(temporary) / 'description.json'
        session.description.write_text(json.dumps(session.describe()))
        return session

    def harness_argv(self, session, mode, controller, *arguments):
        return [sys.executable, str(HERE / 'run_fault_harness.py'), mode, str(session.description), '--controller', controller] + list(arguments)

    def harness(self, session, mode, controller, *arguments, timeout=240):
        return subprocess.run(self.harness_argv(session, mode, controller, *arguments), env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)

    def execute(self, session, *arguments, **options):
        return self.harness(session, 'execute', 'controller-a', '--fencing-token', str(session.token), *arguments, **options)

    def document(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stderr.decode()[-2000:])
        return json.loads(completed.stdout)

    def records(self, session):
        return session.client.call('run_records', session_id=session.SESSION)

    def status(self, session):
        return session.client.call('status', session_id=session.SESSION)

    def assert_nothing_runs(self, session):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and session.live_workloads():
            time.sleep(0.05)
        self.assertEqual(session.live_workloads(), [])
        self.assertTrue(guest_runner.port_free('udp', session.game_port))

    def inventory(self, session):
        """Every byte under both hosts' run trees, to prove nothing was overwritten or removed later."""
        found = {}
        for role in ('game', 'bot'):
            runs = session.hosts.guests.runner_root(role) / 'runs'
            for path in runs.rglob('*') if runs.exists() else ():
                if path.is_file():
                    found[str(path)] = path.read_bytes()
        return found

    def wait_for_phase(self, session, phase, limit_s=30.0):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            records = self.records(session)
            if records and records[-1]['phase'] == phase:
                return records[-1]
            time.sleep(0.1)
        details = [p.read_text()[-1200:] for p in session.session_dir.glob('runs/*/classification.json')]
        journal = session.session_dir / 'execution' / 'journal.ndjson'
        raise AssertionError('no run reached %s: %s %s %s' % (phase, self.records(session), details, journal.read_text()[-1200:] if journal.exists() else ''))


class WholeRuns(LocalFixture):
    def test_each_run_has_fresh_processes_and_its_own_sealed_verified_directory(self):
        session = self.session(workload_seconds=1.0)
        result = self.document(self.execute(session, '--score', FAIL_LOW, '--no-wrap-up'))['batch']
        self.assertEqual((result['status'], result['search_status']), (run_executor.FINISHED, 'no_passing_target'))
        records = self.records(session)
        self.assertEqual([r['outcome'] for r in records], [search.FAIL, search.FAIL])
        identities = []
        for row in records:
            self.assertEqual(row['phase'], 'sealed')
            for role in ('game', 'bot'):
                tree = session.run_tree(role, row['run_id'])
                seal = json.loads((tree / guest_runner.SEAL).read_text())
                identities.append((seal['identity']['processes'][role]['pid'], seal['identity']['processes'][role]['start_id']))
                identities.append((seal['identity']['processes']['sampler']['pid'], seal['identity']['processes']['sampler']['start_id']))
                self.assertEqual(os.stat(str(tree / 'plan.json')).st_mode & 0o777, 0o440)
                self.assertEqual(os.stat(str(tree)).st_mode & 0o777, 0o550)
                for item in seal['files']:
                    self.assertEqual(run_executor.sha256_path(tree / item['path']), item['sha256'])
                    local = session.session_dir / 'runs' / row['run_id'] / role / item['path']
                    self.assertEqual(run_executor.sha256_path(local), item['sha256'], 'the exported copy is the sealed copy')
                self.assertGreater(len((tree / 'sampler.ndjson').read_text().splitlines()), 1, 'each run has its own working sampler')
            self.assertTrue(json.loads((session.run_tree('bot', row['run_id']) / 'report.json').read_text())['sent'] > 0, 'real traffic was sent')
            sockets = (session.run_tree('game', row['run_id']) / 'sockets.ndjson').read_text().splitlines()
            self.assertGreater(len(sockets), 0, 'the real socket of this process was observed')
        self.assertEqual(len(identities), len(set(identities)), 'no process identity repeats')
        self.assert_nothing_runs(session)
        self.assertTrue(session.client.call('verify_journal')['valid'])

    def test_the_planner_journal_replays_to_the_registrys_result(self):
        session = self.session(workload_seconds=1.0)
        self.document(self.execute(session, '--score', FAIL_LOW, '--no-wrap-up'))
        _, _, state, _ = do_session.load_session(session.session_dir)
        self.assertEqual(search.derive(state)['status'], 'no_passing_target')

    def test_an_abort_before_the_authorization_starts_no_real_process(self):
        session = self.session(workload_seconds=1.0)
        result = self.document(self.execute(session, '--score', PASS_ALL, '--no-wrap-up', '--abort-at', 'after_launching_commit'))['batch']
        self.assertEqual(result['status'], run_executor.CLEANUP_STARTED)
        run_id = self.records(session)[0]['run_id']
        self.assertFalse(session.run_tree('game', run_id).exists(), 'no process and no directory')
        self.assertEqual(self.records(session)[0]['outcome'], search.INCOMPLETE)
        for role in ('game', 'bot'):
            fence = json.loads((session.hosts.guests.runner_root(role) / 'control' / 'fence.json').read_text())
            self.assertTrue(fence['closed'], 'the revocation reached the real fence file')
        self.assert_nothing_runs(session)

    def test_an_abort_in_flight_is_stopped_by_the_recheck_and_no_bot_starts(self):
        session = self.session(workload_seconds=30.0)
        started = time.monotonic()
        result = self.document(self.execute(session, '--score', PASS_ALL, '--no-wrap-up', '--abort-at', 'after_game_authorized'))['batch']
        self.assertEqual(result['status'], run_executor.CLEANUP_STARTED)
        run_id = self.records(session)[0]['run_id']
        tree = session.run_tree('game', run_id)
        reason = json.loads((tree / 'result.json').read_text())['stop_reason']
        self.assertTrue(reason.startswith('stop_requested'), reason)
        self.assertFalse(session.run_tree('bot', run_id).exists())
        self.assertLess(time.monotonic() - started, 25.0, 'a real server was stopped long before its workload bound')
        self.assert_nothing_runs(session)

    def test_a_start_delayed_past_its_real_authorization_is_refused_by_the_real_guest(self):
        session = self.session(workload_seconds=1.0)
        self.document(self.execute(session, '--score', PASS_ALL, '--no-wrap-up', '--delay-at', 'after_game_authorized', '--delay-s', str(registry.GUEST_ACTION_TTL_S + guest_runner.LAUNCH_CLOCK_TOLERANCE_S + 1)))
        row = self.records(session)[0]
        self.assertFalse(session.run_tree('game', row['run_id']).exists(), 'no process and no directory')
        self.assertEqual(row['outcome'], search.INCOMPLETE)
        self.assert_nothing_runs(session)

    def test_a_crash_between_authorization_and_start_leaves_nothing_to_stop(self):
        session = self.session(workload_seconds=1.0)
        self.assertEqual(self.execute(session, '--failpoint', 'after_game_authorized').returncode, run_fault_harness.CRASH_EXIT)
        self.assert_nothing_runs(session)
        self.assertEqual(self.records(session)[0]['phase'], 'launching')
        document = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))
        self.assertEqual(self.records(session)[0]['outcome'], search.INCOMPLETE)
        self.assertEqual(document['resume']['code'], 'no_eligible_untouched_work')

    def test_a_real_permission_failure_while_collecting_reaches_the_real_cleanup_request(self):
        session = self.session(workload_seconds=1.0, recovery_grace_s=3)
        guests, adapter = session.hosts.guests, session.hosts.adapter
        executor = run_executor.RunExecutor(session.client, guests, rf.LocalPairProvider(session.pair_file), session.manifest, session.sha, session.session_dir, session.token, time.sleep,
                                            time.monotonic, time.time, adapter=adapter, policy=run_fault_harness.FAST, source_problems=lambda: [], readiness_problems=lambda report: [], require_counters=False)
        result = executor.execute()
        role_dir = session.session_dir / 'runs' / self.records(session)[0]['run_id'] / 'game'
        os.chmod(str(role_dir), 0)
        self.addCleanup(os.chmod, str(role_dir), 0o755)
        executor.wrap_up(result)
        self.assertIsNotNone(self.status(session)['cleanup']['requested_at'], 'not left collecting until C')
        self.assertEqual(self.status(session)['evidence']['status'], 'corrupt', 'unreadable is never called verified')

    def test_wrap_up_requests_deletion_and_the_real_watchdog_closes_the_session(self):
        session = self.session(workload_seconds=1.0)
        self.document(self.execute(session, '--score', FAIL_LOW))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and self.status(session)['state'] != registry.CLOSED:
            time.sleep(0.2)
        final = self.status(session)
        self.assertEqual(final['state'], registry.CLOSED)
        self.assertEqual(final['measurement']['outcome'], 'no_passing_target')
        self.assertEqual(final['overall'], 'resources_verified_evidence_incomplete')

    def test_no_scorer_means_inconclusive_and_the_batch_stops(self):
        session = self.session(workload_seconds=1.0)
        result = self.document(self.execute(session, '--no-wrap-up'))['batch']
        self.assertEqual(result['search_status'], 'stopped_inconclusive_evidence')
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.INCONCLUSIVE])

    def test_a_real_generator_crash_is_invalid_load_not_capacity(self):
        session = self.session(workload_seconds=5.0, bot_extra=['--crash-after', '0.3'])
        result = self.document(self.execute(session, '--score', json.dumps(dict(default='FAIL')), '--no-wrap-up'))['batch']
        self.assertEqual(result['search_status'], 'stopped_invalid_load')
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.INVALID_LOAD])
        self.assert_nothing_runs(session)

    def test_a_real_game_crash_can_only_be_capacity_through_a_scorer(self):
        session = self.session(workload_seconds=1.5, game_extra=['--crash-after-first-datagram', '0.3'])
        result = self.document(self.execute(session, '--score', FAIL_LOW, '--no-wrap-up'))['batch']
        self.assertEqual(result['search_status'], 'no_passing_target', result)
        self.assertIsNone(self.status(session)['terminal_failure'])
        unscored = self.session(workload_seconds=1.5, game_extra=['--crash-after-first-datagram', '0.3'])
        self.document(self.execute(unscored, '--no-wrap-up'))
        self.assertEqual([r['outcome'] for r in self.records(unscored)], [search.INCONCLUSIVE])

    def test_a_swarm_that_reports_nothing_fails_the_required_evidence(self):
        session = self.session(workload_seconds=1.0, bot_extra=['--no-report'])
        result = self.document(self.execute(session, '--score', PASS_ALL, '--no-wrap-up'))['batch']
        self.assertEqual(result['search_status'], 'stopped_infrastructure_failure')
        self.assertTrue(any('report.json' in reason for reason in result['runs'][0]['reasons']))

    @unittest.skipUnless(os.environ.get('OMEGA_LOCAL_RELEASE_DIR'), 'needs a real release build; see the module docstring')
    def test_real_binaries_run_through_the_same_path(self):
        release = pathlib.Path(os.environ['OMEGA_LOCAL_RELEASE_DIR'])
        session = self.session(release_dir=release, workload_seconds=3.0)
        result = self.document(self.harness(session, 'execute', 'controller-real', '--fencing-token', str(session.token), '--no-wrap-up', timeout=240))['batch']
        # Whether the swarm's own criteria passed on a loaded laptop varies. Either way it completed, and nothing is scored.
        self.assertEqual(result['search_status'], 'stopped_inconclusive_evidence', result)
        row = self.records(session)[0]
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        report = json.loads((session.run_tree('bot', row['run_id']) / 'report.json').read_text())
        self.assertGreater(report['aggregated']['connected_bots'], 0)
        self.assert_nothing_runs(session)


class RealCrashes(LocalFixture):
    """``os._exit`` at each boundary, then a separate process comes back. No test may depend on the crashed process's memory."""
    # (failpoint, whether the first trial survives as untouched)
    WINDOWS = (('after_selection', 'untouched'), ('before_dispatch_commit', 'untouched'), ('after_dispatch_commit', 'lost'), ('after_launching_commit', 'lost'),
               ('after_game_start', 'lost'), ('after_bot_start', 'lost'), ('after_running_commit', 'lost'),
               ('before_outcome_commit', 'committed'), ('after_outcome_commit', 'committed'), ('after_journal_mirror', 'committed'))

    def one_window(self, window):
        point, expected = window
        # A swarm that finishes by itself before anyone returns has proved its own end, which ``test_a_workload_...`` covers.
        session = self.session(workload_seconds=30.0 if expected == 'lost' else 1.2)
        crashed = self.execute(session, '--score', FAIL_LOW, '--failpoint', point, '--no-wrap-up')
        self.assertEqual(crashed.returncode, run_fault_harness.CRASH_EXIT, point + ': ' + crashed.stderr.decode()[-2000:])
        before_records = self.records(session)
        before_files = self.inventory(session)
        comeback = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', FAIL_LOW))
        resume = comeback['resume']
        records = self.records(session)
        self.assert_nothing_runs(session)
        for path, content in before_files.items():
            # A workload that outlived its controller may have written more, but it can never have rewritten anything.
            self.assertTrue(pathlib.Path(path).read_bytes().startswith(content), path + ' was overwritten after the crash')
        first = search.run_id(session.SESSION, 1, search.COARSE, 25, 1)
        if expected == 'untouched':
            self.assertEqual(before_records, [])
            self.assertTrue(resume['resumed'], resume)
            self.assertEqual(resume['next_run_id'], first)
            self.assertEqual(records[0]['outcome'], search.FAIL)
        elif expected == 'lost':
            self.assertEqual(before_records[0]['outcome'], None)
            self.assertFalse(resume['resumed'], resume)
            self.assertEqual(resume['code'], 'no_eligible_untouched_work')
            self.assertEqual([r['outcome'] for r in records], [search.INCOMPLETE], 'never replayed, never advanced')
            for role in ('game', 'bot'):
                tree = session.run_tree(role, first)
                if tree.exists():
                    self.assertEqual(json.loads((tree / guest_runner.SEAL).read_text())['interrupted'], 'controller_replaced')
        else:
            self.assertTrue(resume['resumed'], resume)
            self.assertEqual(records[0]['outcome'], search.FAIL, 'the verdict from before the crash stands')
        self.assertTrue(session.client.call('verify_journal')['valid'])
        lines = (session.session_dir / do_session.JOURNAL).read_text().splitlines() if (session.session_dir / do_session.JOURNAL).exists() else []
        outcomes = [json.loads(line)['run_id'] for line in lines if json.loads(line)['kind'] == 'outcome']
        self.assertEqual(len(outcomes), len(set(outcomes)), 'no outcome was mirrored twice')

    def test_every_crash_window_keeps_its_promise(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {window[0]: pool.submit(self.one_window, window) for window in self.WINDOWS}
        failures = {name: future.exception() for name, future in futures.items() if future.exception() is not None}
        self.assertEqual(failures, {})

    def test_a_workload_that_finished_by_itself_after_the_crash_is_scored_from_what_it_left(self):
        session = self.session(workload_seconds=1.2)
        crashed = self.execute(session, '--score', FAIL_LOW, '--failpoint', 'after_running_commit', '--no-wrap-up')
        self.assertEqual(crashed.returncode, run_fault_harness.CRASH_EXIT)
        first = self.records(session)[0]['run_id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not (session.run_tree('bot', first) / 'result.json').exists():
            time.sleep(0.05)
        comeback = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', FAIL_LOW))['resume']
        self.assertTrue(comeback['resumed'], comeback)
        self.assertEqual(self.records(session)[0]['outcome'], search.FAIL, 'proved by the retained evidence, with nothing rerun')
        self.assertEqual(json.loads((session.run_tree('bot', first) / 'result.json').read_text())['stop_reason'], 'primary_exited')
        unscored = self.session(workload_seconds=1.2)
        self.assertEqual(self.execute(unscored, '--failpoint', 'after_running_commit', '--no-wrap-up').returncode, run_fault_harness.CRASH_EXIT)
        first = self.records(unscored)[0]['run_id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not (unscored.run_tree('bot', first) / 'result.json').exists():
            time.sleep(0.05)
        self.assertEqual(self.document(self.harness(unscored, 'resume', 'controller-b', '--takeover'))['resume']['code'], 'no_eligible_untouched_work')
        self.assertEqual(self.records(unscored)[0]['outcome'], search.INCOMPLETE, 'with nothing to score it, nothing is claimed')

    def test_kill_nine_mid_run_leaves_a_bounded_run_that_the_next_controller_stops_and_preserves(self):
        session = self.session(workload_seconds=60.0)
        process = subprocess.Popen(self.harness_argv(session, 'execute', 'controller-a', '--fencing-token', str(session.token), '--score', PASS_ALL, '--no-wrap-up'),
                                   env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        row = self.wait_for_phase(session, 'running')
        process.send_signal(signal.SIGKILL)
        process.wait()
        time.sleep(0.5)
        self.assertEqual(len(session.live_workloads()), 2, 'the workload does not depend on the controller, and its bound stands')
        game = session.run_tree('game', row['run_id'])
        started = json.loads((game / 'identity.json').read_text())['processes']['game']
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))['resume']
        self.assertEqual(resume['code'], 'no_eligible_untouched_work')
        self.assert_nothing_runs(session)
        seal = json.loads((game / guest_runner.SEAL).read_text())
        self.assertEqual(seal['identity']['processes']['game']['pid'], started['pid'], 'the same process was stopped, not a replacement')
        self.assertEqual(seal['interrupted'], 'controller_replaced')
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.INCOMPLETE])
        self.assertEqual(json.loads((game / 'result.json').read_text())['stop_reason'], 'stop_requested:controller_replaced')

    def test_explicit_takeover_stops_a_live_controller_and_refuses_its_later_work(self):
        session = self.session(workload_seconds=60.0)
        process = subprocess.Popen(self.harness_argv(session, 'execute', 'controller-a', '--fencing-token', str(session.token), '--score', PASS_ALL, '--no-wrap-up'),
                                   env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        self.wait_for_phase(session, 'running')
        refused = self.document(self.harness(session, 'resume', 'controller-b', '--score', PASS_ALL))['resume']
        self.assertEqual(refused['code'], 'control_held', 'without takeover nothing changes')
        self.assertEqual(len(session.live_workloads()), 2)
        self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))
        output, _ = process.communicate(timeout=60)
        self.assertEqual(json.loads(output)['batch']['status'], run_executor.CONTROL_LOST)
        self.assert_nothing_runs(session)
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.INCOMPLETE])


class RealResume(LocalFixture):
    def crash_between_runs(self, session):
        crashed = self.execute(session, '--score', json.dumps(dict(targets={'25': 'PASS', '50': 'FAIL', '30': 'FAIL'})), '--failpoint', 'after_selection', '--failpoint-hit', '2', '--no-wrap-up')
        self.assertEqual(crashed.returncode, run_fault_harness.CRASH_EXIT, crashed.stdout.decode()[-2000:] + crashed.stderr.decode()[-2000:])
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.PASS])

    def test_resume_runs_only_untouched_work_with_established_predecessors(self):
        session = self.session(workload_seconds=1.0)
        self.crash_between_runs(session)
        comeback = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', json.dumps(dict(targets={'25': 'PASS', '50': 'FAIL', '30': 'FAIL'}))))
        self.assertTrue(comeback['resume']['resumed'], comeback)
        self.assertEqual(comeback['resume']['next_run_id'], search.run_id(session.SESSION, 2, search.COARSE, 50, 1))
        self.assertEqual(comeback['batch']['search_status'], 'confirmed')
        records = self.records(session)
        self.assertEqual([r['outcome'] for r in records], [search.PASS, search.FAIL, search.FAIL] + [search.PASS] * 3)
        self.assertEqual(len({r['run_id'] for r in records}), 6)

    def test_a_changed_host_refuses_even_with_everything_else_clean(self):
        session = self.session(workload_seconds=1.0)
        self.crash_between_runs(session)
        pair = json.loads(session.pair_file.read_text())
        next(iter(pair['droplets'].values()))['public_ipv4'] = ['198.51.100.250']
        session.pair_file.write_text(json.dumps(pair))
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))['resume']
        self.assertEqual(resume['code'], 'pair_changed')
        self.assertEqual(len(self.records(session)), 1)

    def test_a_changed_program_refuses(self):
        session = self.session(workload_seconds=1.0)
        self.crash_between_runs(session)
        path = pathlib.Path(session.hosts.adapter.program_paths()['bot'])
        path.write_text(path.read_text() + '\n# changed\n')
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))['resume']
        self.assertEqual(resume['code'], 'host_not_reset')
        self.assertIn('frozen hash', resume['detail'])

    def test_a_leftover_socket_refuses_and_clearing_it_allows_a_new_request(self):
        session = self.session(workload_seconds=1.0)
        self.crash_between_runs(session)
        held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        held.bind(('127.0.0.1', session.game_port))
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))['resume']
        self.assertEqual(resume['code'], 'host_not_reset')
        self.assertIn('still holds a socket', resume['detail'])
        held.close()
        again = self.document(self.harness(session, 'resume', 'controller-c', '--takeover', '--score', json.dumps(dict(targets={'25': 'PASS', '50': 'FAIL', '30': 'FAIL'}))))
        self.assertTrue(again['resume']['resumed'], again)

    def test_uncleared_impairment_stops_the_batch_before_dispatch(self):
        session = self.session(workload_seconds=1.0)
        session.hosts.state_file.write_text(json.dumps([dict(kind='netem', dev='lo0')]))
        result = self.document(self.execute(session, '--score', PASS_ALL, '--no-wrap-up'))['batch']
        self.assertEqual(result['code'], 'host_not_reset')
        self.assertIn('qdisc netem', result['detail'])
        self.assertEqual(self.records(session), [])
        self.assertEqual(self.status(session)['terminal_failure'], search.INFRASTRUCTURE_FAILURE)

    def test_an_operator_abort_refuses_resume_and_collect_still_preserves(self):
        session = self.session(workload_seconds=60.0)
        process = subprocess.Popen(self.harness_argv(session, 'execute', 'controller-a', '--fencing-token', str(session.token), '--score', PASS_ALL, '--no-wrap-up'),
                                   env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        row = self.wait_for_phase(session, 'running')
        process.send_signal(signal.SIGKILL)
        process.wait()
        session.client.mutate('operator_abort', session_id=session.SESSION, reason='operator abort')
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', PASS_ALL))['resume']
        self.assertEqual(resume['code'], 'cleanup_in_progress')
        self.assertEqual(len(self.records(session)), 1)
        collected = self.document(self.harness(session, 'collect', 'controller-c', '--takeover'))
        self.assertEqual(collected['batch']['code'], 'operator_collect')
        self.assert_nothing_runs(session)
        self.assertTrue((session.run_tree('game', row['run_id']) / guest_runner.SEAL).exists(), 'its evidence survived the abort')


if __name__ == '__main__':
    unittest.main()
