"""The real-process part of the integrated fault battery (issue #71): real controller, registry and watchdog processes die and come back around one session.

Every process here is real and runs on this machine on real clocks: the registry CLI per request, the supervised watchdog service, each
controller, both role runners and their workloads. What is not real: the provider is a JSON file behind ``fake_provider`` and the pair's view
of it another (``LocalPairProvider``), the workloads are stand-ins on loopback, ``tc`` is a stub, and run outcomes come from the scripted
scorer, because stand-ins leave nothing a real scorer could read. No SSH, systemd, Linux, Droplet or account is involved.

The facts that do not depend on timing are kept in ``real-process.json`` beside the synthetic battery. With ``OMEGA_FAULT_BATTERY_RECORD=DIR``
the test writes its own copy there instead of comparing, for a deliberate refresh.
"""
import json
import os
import pathlib
import signal
import subprocess
import time
import unittest

import guest_runner
import registry
import run_fault_harness
import search
import session_export
from test_run_local_integration import ENV, LocalFixture

RETAINED = pathlib.Path(__file__).parents[2] / 'docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice8' / 'real-process.json'
SCORES = json.dumps(dict(targets={'25': 'PASS', '50': 'FAIL', '30': 'FAIL'}))
SCHEMA = 'omega.do-session.fault-battery-process/1'
NOTE = ('Real local processes on one machine, on real clocks: registry CLI, watchdog service, controllers, role runners and stand-in workloads on loopback. '
        'The provider and the pair view are JSON files, tc is a stub and outcomes come from a scripted scorer. Only facts that do not depend on timing are kept. '
        'Nothing here ran on a Droplet, over SSH, under systemd or on Linux, and nothing here is a measurement.')


class RealProcesses(LocalFixture):
    summary = {}

    @classmethod
    def tearDownClass(cls):
        if len(cls.summary) < 2:
            return
        document = dict(schema=SCHEMA, kind='real_process_normalized', note=NOTE, scenarios=dict(sorted(cls.summary.items())))
        text = json.dumps(document, indent=1, sort_keys=True) + '\n'
        target = os.environ.get('OMEGA_FAULT_BATTERY_RECORD')
        if target:
            pathlib.Path(target).mkdir(parents=True, exist_ok=True)
            (pathlib.Path(target) / 'real-process.json').write_text(text)

    def provider_holds(self, session):
        state = json.loads(session.account.read_text())
        tags = {'omega-session:' + session.SESSION, 'omega-role:game:' + session.SESSION, 'omega-role:bot:' + session.SESSION}
        found = []
        for kind in ('droplets', 'firewalls'):
            for item in (state.get(kind) or {}).values():
                if tags & set(item.get('tags') or ()) or str(item.get('name', '')).startswith(session.SESSION):
                    found.append(kind)
        return found + sorted(tags & set(state.get('tags') or ()))

    def await_closed(self, session, limit_s=60.0):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline and self.status(session)['state'] != registry.CLOSED:
            time.sleep(0.2)
        return self.status(session)

    def common(self, session, armed, watchdog_pids):
        final = self.status(session)
        records = self.records(session)
        return dict(state=final['state'], overall=final['overall'], measurement=final['measurement']['outcome'], evidence=final['evidence']['status'],
                    cleanup=final['cleanup']['outcome'], deadlines_unchanged=armed == (final['t0_utc'], final['cleanup_c_utc'], final['deadline_d_utc']),
                    runs=[[r['run_id'].split('-', 4)[-1], r['outcome']] for r in records], run_ids_unique=len({r['run_id'] for r in records}) == len(records),
                    journal_valid=session.client.call('verify_journal')['valid'], workloads_left=len(session.live_workloads()), provider_holds=self.provider_holds(session),
                    watchdog_replaced=watchdog_pids[0] != watchdog_pids[1])

    def test_kill_nine_controller_and_watchdog_mid_run_then_collect_and_real_cleanup(self):
        """A controller is killed while its first trial runs, and so is the watchdog service. The service restarts; a returning controller is refused, a third collects, and the restarted watchdog closes the session only after the provider file holds nothing of it."""
        session = self.session(workload_seconds=60.0)
        held_at_start = self.provider_holds(session)
        before = self.status(session)
        armed = (before['t0_utc'], before['cleanup_c_utc'], before['deadline_d_utc'])
        process = subprocess.Popen(self.harness_argv(session, 'execute', 'controller-a', '--fencing-token', str(session.token), '--score', SCORES, '--no-wrap-up'),
                                   env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        row = self.wait_for_phase(session, 'running')
        process.send_signal(signal.SIGKILL)
        controller_exit = process.wait()
        workloads_after_kill = len(session.live_workloads())
        pids = session.restart_watchdog()
        session._await(lambda: session.client.call('health')['watchdog']['healthy'])
        resume = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', SCORES))['resume']
        self.assert_nothing_runs(session)
        collected = self.document(self.harness(session, 'collect', 'controller-c', '--takeover'))
        final = self.await_closed(session)
        seal = json.loads((session.run_tree('game', row['run_id']) / guest_runner.SEAL).read_text())
        exported = sorted(p.name for p in (session.session_dir / 'export').glob('gen-*') if '.writing-' not in p.name)
        self.assertEqual(controller_exit, -signal.SIGKILL)
        self.assertEqual(workloads_after_kill, 2, 'the workload does not depend on its controller')
        self.assertEqual(resume['code'], 'no_eligible_untouched_work')
        self.assertEqual(collected['batch']['code'], 'operator_collect')
        self.assertEqual(final['state'], registry.CLOSED)
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.INCOMPLETE], 'never replayed, never advanced')
        self.assertEqual(seal['interrupted'], 'controller_replaced')
        self.assertEqual(session_export.verify(session.session_dir, exported[-1]), [])
        found = self.common(session, armed, pids)
        self.assertTrue(found['deadlines_unchanged'] and found['run_ids_unique'] and found['journal_valid'] and found['watchdog_replaced'])
        self.assertEqual((found['workloads_left'], found['provider_holds'], found['cleanup']), (0, [], registry.VERIFIED_ABSENT))
        self.assertNotEqual(found['overall'], 'clean')
        self.assertTrue(held_at_start, 'the provider file held the pair before cleanup')
        found.update(provider_held_at_start=held_at_start, controller_killed=True, workloads_survived_their_controller=True, resume_code=resume['code'], collect_code=collected['batch']['code'], seal_interrupted=seal['interrupted'],
                     export_generations=len(exported), export_verifies=True)
        self.check_retained('kill_nine_controller_and_watchdog_mid_run', found)

    def test_controller_exits_between_trials_watchdog_restarts_and_resume_finishes(self):
        """A controller process dies at a named boundary between trials, the watchdog service is killed and restarted, and an explicit resume runs only the untouched remaining trials to the end of the scripted search, after which the restarted watchdog closes the session."""
        session = self.session(workload_seconds=1.0)
        held_at_start = self.provider_holds(session)
        before = self.status(session)
        armed = (before['t0_utc'], before['cleanup_c_utc'], before['deadline_d_utc'])
        crashed = self.execute(session, '--score', SCORES, '--failpoint', 'after_selection', '--failpoint-hit', '2', '--no-wrap-up')
        self.assertEqual(crashed.returncode, run_fault_harness.CRASH_EXIT)
        self.assertEqual([r['outcome'] for r in self.records(session)], [search.PASS])
        pids = session.restart_watchdog()
        session._await(lambda: session.client.call('health')['watchdog']['healthy'])
        comeback = self.document(self.harness(session, 'resume', 'controller-b', '--takeover', '--score', SCORES))
        final = self.await_closed(session)
        self.assertTrue(comeback['resume']['resumed'], comeback)
        self.assertTrue(comeback['resume']['next_run_id'].endswith('t02-coarse-n050-r1'))
        self.assertEqual(comeback['batch']['search_status'], 'confirmed')
        self.assertEqual(final['state'], registry.CLOSED)
        found = self.common(session, armed, pids)
        self.assertEqual([r[1] for r in found['runs']], [search.PASS, search.FAIL, search.FAIL] + [search.PASS] * 3)
        self.assertTrue(found['deadlines_unchanged'] and found['run_ids_unique'] and found['journal_valid'] and found['watchdog_replaced'])
        self.assertEqual((found['workloads_left'], found['provider_holds'], found['cleanup']), (0, [], registry.VERIFIED_ABSENT))
        self.assertTrue(held_at_start, 'the provider file held the pair before cleanup')
        found.update(provider_held_at_start=held_at_start, controller_exit=crashed.returncode, resumed=True, next_run=comeback['resume']['next_run_id'].split('-', 4)[-1], search_status=comeback['batch']['search_status'])
        self.check_retained('controller_exit_between_trials_then_resume', found)

    def check_retained(self, name, found):
        type(self).summary[name] = found
        if os.environ.get('OMEGA_FAULT_BATTERY_RECORD') or not RETAINED.exists():
            return
        self.assertEqual(found, json.loads(RETAINED.read_text())['scenarios'][name], 'a timing-independent fact changed: refresh it deliberately with OMEGA_FAULT_BATTERY_RECORD')

    def test_the_retained_summary_says_what_it_is(self):
        if not RETAINED.exists():
            self.skipTest('no real-process summary is retained yet')
        document = json.loads(RETAINED.read_text())
        self.assertEqual((document['schema'], document['kind']), (SCHEMA, 'real_process_normalized'))
        self.assertIn('nothing here is a measurement', document['note'])
        self.assertEqual(sorted(document['scenarios']), ['controller_exit_between_trials_then_resume', 'kill_nine_controller_and_watchdog_mid_run'])


if __name__ == '__main__':
    unittest.main()
