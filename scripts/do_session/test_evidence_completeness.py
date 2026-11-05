"""What a session export may call complete, when a failed transfer's clock starts, what a local copy may be called, and which loss figures reach a reader. The real controller, registry, watchdog, prover and scorer over a fake account and fake guests, so no number here says anything about any host."""
import errno
import json
import math
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import capacity_scorer as cs
import evidence_publication as ep
import export_fixtures as ef
import guest_runner
import registry_client
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import session_clock
import session_export as se
import session_report as sr


def confirmed(case):
    sim = ef.ExportSim(case, ef.enriched(ef.CONFIRMING))
    sim.batch()
    return sim, sim.records()[0]['run_id']


class RequiredInputs(unittest.TestCase):
    """Removing what a current producer wrote, after a confirmed search whose scores all still verify."""

    def assert_withheld(self, sim, exported, word):
        self.assertEqual(exported.status, word)
        self.assertTrue(exported.problems)
        report = sim.document(exported.generation, se.REPORT_JSON)
        self.assertFalse(report['establishes'])
        self.assertIn(report['results']['measurement']['claim']['kind'], ('evidence_incomplete', 'evidence_disagreement'))
        self.assertFalse(report['results']['measurement']['claim']['confirmed'])
        self.assertIsNone(report['economics']['nominal_game_tier']['players_per_monthly_game_usd'])
        published = sim.document(exported.generation, 'published/summary.json')
        self.assertFalse(published['establishes'])
        self.assertEqual(published['results']['evidence']['status'], word)
        self.assertEqual([row['outcome'] for row in report['runs']], [row['outcome'] for row in sim.records()], 'what each run decided stays what it was')

    def test_each_required_controller_and_provenance_input_keeps_a_session_from_complete(self):
        sim, run = confirmed(self)
        run_dir = sim.run_dir(run)
        readiness = json.loads((sim.root / 'provisioning' / 'readiness.json').read_text())
        receipts = sorted(path.name for path in run_dir.glob(cs.SEAL_RECEIPT_GLOB))
        self.assertEqual(len(receipts), 2)
        named = ['runs/%s/%s' % (run, name) for name in ['plan-game.json', 'plan-bot.json', 'clock-before.json', 'clock-after.json', 'grant.json', 'selected.json', 'window-proof.json'] + receipts] + [item['path'] for item in readiness['required_artifacts']]
        self.assertEqual(sorted(item['role'] for item in readiness['required_artifacts']), ['bot', 'game'])
        first_admission = sorted(path.relative_to(sim.root) for path in (sim.root / 'admissions').glob('*.json'))[0]
        for relative in named + [str(first_admission)]:
            with self.subTest(relative):
                path = sim.root / relative
                data = path.read_bytes()
                path.chmod(0o640)
                path.unlink()
                try:
                    exported = se.export_session(sim.root, client=sim.client)
                    self.assert_withheld(sim, exported, 'missing')
                    inventory = sim.document(exported.generation)
                    self.assertEqual(len([entry for entry in inventory['roles'] if entry['run_id'] == run]), 2, 'both roles stay on the list')
                    self.assertNotIn(relative, [item['path'] for item in inventory['files']])
                    self.assertIn('runs/%s/game/seal.json' % run, [item['path'] for item in inventory['files']], 'everything still here stays inventoried')
                finally:
                    path.write_bytes(data)
        restored = se.export_session(sim.root, client=sim.client)
        self.assertEqual((restored.status, restored.problems), ('complete', []))

    def test_a_missing_plan_shows_on_the_role_the_run_and_every_report(self):
        sim, run = confirmed(self)
        path = sim.run_dir(run) / 'plan-bot.json'
        path.chmod(0o640)
        path.unlink()
        exported = se.export_session(sim.root, client=sim.client)
        entry = next(item for item in sim.document(exported.generation)['roles'] if (item['run_id'], item['role']) == (run, 'bot'))
        self.assertEqual(entry['status'], 'verified', 'the seal and its bytes hold up, and a further transfer could not help')
        self.assertEqual(entry['required_absent'], ['plan-bot.json'])
        report = sim.document(exported.generation, se.REPORT_JSON)
        row = next(item for item in report['runs'] if item['run_id'] == run)
        self.assertFalse(row['verified'])
        self.assertEqual(row['evidence_roles']['bot']['required_absent'], ['plan-bot.json'])
        self.assertIn('runs/%s/plan-bot.json' % run, report['results']['evidence']['controller_inputs_missing'])
        self.assertIn('plan-bot.json', (sim.generation(exported.generation) / se.REPORT_MD).read_text())
        published = sim.document(exported.generation, 'published/summary.json')
        self.assertEqual(published['results']['evidence']['controller_inputs_missing'], 1)
        self.assertIn('input(s) missing', (sim.generation(exported.generation) / 'published' / 'summary.md').read_text())

    def test_a_plan_lost_before_wrap_up_never_reaches_clean_and_cleanup_goes_on(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        executor = sim.executor()
        result = executor.execute()
        path = sim.run_dir(sim.records()[0]['run_id']) / 'plan-game.json'
        path.chmod(0o640)
        path.unlink()
        executor.wrap_up(result)
        status = sim.status_now()
        self.assertEqual(status['evidence']['status'], 'missing')
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete')

    def test_bytes_that_are_not_what_was_pinned_are_corrupt_and_not_merely_present(self):
        sim, run = confirmed(self)
        for relative in ('provisioning/packages-game.json', 'provisioning/readiness.json', 'runs/%s/plan-game.json' % run):
            with self.subTest(relative):
                path = sim.root / relative
                data = path.read_bytes()
                path.chmod(0o640)
                document = json.loads(data)
                document['fixture_edit'] = True
                path.write_text(json.dumps(document))
                try:
                    exported = se.export_session(sim.root, client=sim.client)
                    self.assert_withheld(sim, exported, 'corrupt')
                    self.assertIn(relative, sim.document(exported.generation)['controller_inputs']['corrupt'])
                finally:
                    path.write_bytes(data)

    def test_a_readiness_report_that_names_no_provenance_is_no_proof_of_it(self):
        sim, _ = confirmed(self)
        path = sim.root / 'provisioning' / 'readiness.json'
        path.chmod(0o640)
        document = json.loads(path.read_text())
        del document['required_artifacts']
        path.write_text(json.dumps(document))
        exported = se.export_session(sim.root)     # with no registry to hold the report to its hash, it still has to say what it requires
        self.assertNotEqual(exported.status, 'complete')
        self.assertTrue(any('required provisioning artifacts' in item for item in exported.problems))

    def test_a_derived_report_is_not_a_required_input(self):
        sim, run = confirmed(self)
        for relative in ('runs/%s/REPORT.md' % run, 'execution/capacity-report-token1-0.md'):
            with self.subTest(relative):
                path = sim.root / relative
                path.chmod(0o640)
                path.unlink()
                self.assertEqual(se.export_session(sim.root, client=sim.client).status, 'complete')

    def test_a_run_with_no_plans_left_is_still_a_dispatched_run_without_any_registry(self):
        sim, run = confirmed(self)
        for role in ('game', 'bot'):
            path = sim.run_dir(run) / ('plan-%s.json' % role)
            path.chmod(0o640)
            path.unlink()
        self.assertIn(run, se._dispatched_runs(sim.root, []))
        exported = se.export_session(sim.root)
        self.assertEqual(exported.status, 'missing')
        self.assertEqual(sorted(item['role'] for item in sim.document(exported.generation)['roles'] if item['run_id'] == run), ['bot', 'game'])


class WhichRolesWent(unittest.TestCase):
    """Nothing on record is the only thing that can say a role never went."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        self.run_dir = self.root / 'runs' / 'r1'
        self.run_dir.mkdir(parents=True)

    def entries(self, never_created=(), snapshot=None):
        return se.role_entries(self.root, ['r1'], None, None, never_created=never_created, snapshot=snapshot)[0]

    def test_a_role_nothing_says_went_is_not_invented(self):
        (self.run_dir / 'plan-game.json').write_text('{}')
        self.assertEqual([item['role'] for item in self.entries()], ['game'])

    def test_a_start_grant_with_no_plan_is_uncertainty(self):
        journal = [dict(kind='guest_grant_issued', data=dict(grant_id='g', run_id='r1', role='bot', action='launch_run'))]
        entry, = self.entries(snapshot=dict(journal=journal))
        self.assertEqual((entry['role'], entry['status'], entry['required_absent']), ('bot', 'missing', sorted(set(entry['required_absent']) | {'plan-bot.json'})))
        self.assertIn('plan-bot.json', entry['required_absent'])
        self.assertTrue(any('its start grant' in item for item in entry['problems']))

    def test_the_hosts_no_such_run_stands_when_nothing_on_record_disagrees(self):
        (self.run_dir / 'plan-game.json').write_text('{}')
        entry, = self.entries(never_created={('r1', 'game')})
        self.assertEqual(entry['status'], 'never_created')

    def test_the_hosts_no_such_run_does_not_outrank_a_start_on_record(self):
        (self.run_dir / 'plan-game.json').write_text('{}')
        journal = [dict(kind='guest_grant_issued', data=dict(grant_id='g', run_id='r1', role='game')), dict(kind='guest_grant_started', data=dict(grant_id='g', role='game'))]
        entry, = self.entries(never_created={('r1', 'game')}, snapshot=dict(journal=journal))
        self.assertEqual(entry['status'], 'missing')
        self.assertTrue(any('never existed' in item for item in entry['problems']))

    def test_a_retained_execution_record_shows_a_role_went_with_its_plan_gone(self):
        (self.run_dir / 'execution.json').write_text(json.dumps(dict(plan_digests=dict(game='0' * 64), roles={}, exported={})))
        self.assertEqual(self.entries()[0]['role'], 'game')


class Traversal(unittest.TestCase):
    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root reads through chmod 0')
    def test_an_unreadable_directory_is_not_an_empty_one(self):
        sim, _ = confirmed(self)
        hidden = sim.root / 'provider-diagnostics'
        hidden.mkdir()
        (hidden / 'quote-response.json').write_text('{"raw": "retained"}')
        beside = sim.root / 'provider-notes'
        beside.mkdir()
        (beside / 'readable.json').write_text('{"raw": "readable"}')
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)
        with self.assertRaises(PermissionError):
            list(hidden.iterdir())
        exported = se.export_session(sim.root, client=sim.client)
        self.assertEqual(exported.status, 'partial')
        inventory = sim.document(exported.generation)
        self.assertEqual(inventory['not_inventoried'], [dict(path='provider-diagnostics', kind='directory', reason='PermissionError')])
        paths = [item['path'] for item in inventory['files']]
        self.assertIn('provider-notes/readable.json', paths, 'a readable sibling is kept')
        self.assertNotIn('provider-diagnostics/quote-response.json', paths)
        report = sim.document(exported.generation, se.REPORT_JSON)
        self.assertFalse(report['establishes'])
        self.assertIn('provider-diagnostics', (sim.generation(exported.generation) / se.REPORT_MD).read_text())
        published = sim.document(exported.generation, 'published/summary.json')
        self.assertEqual(published['results']['evidence']['paths_not_inventoried'], 1)
        self.assertFalse(published['establishes'])
        self.assertIn('cannot be said to cover every raw file', (sim.generation(exported.generation) / 'published' / 'summary.md').read_text())

    def test_a_listing_that_fails_part_way_keeps_what_it_gave_and_says_the_rest_is_unknown(self):
        sim, _ = confirmed(self)
        directory = sim.root / 'provider-diagnostics'
        directory.mkdir()
        for name in ('a.json', 'b.json', 'c.json'):
            (directory / name).write_text('{}')
        real = os.scandir

        class Partial:
            def __init__(self, path):
                self.scan = real(path)
                self.given = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.scan.close()

            def __iter__(self):
                return self

            def __next__(self):
                if self.given == 1:
                    raise OSError(errno.EIO, 'injected')
                self.given += 1
                return next(self.scan)

        def scandir(path):
            return Partial(path) if str(path).endswith('provider-diagnostics') else real(path)
        with mock.patch.object(se.os, 'scandir', side_effect=scandir):
            files, problems, odd, absent = se._walk(sim.root)
        found = [item['path'] for item in files if item['path'].startswith('provider-diagnostics/')]
        self.assertEqual(len(found), 1, 'what it gave before failing is kept')
        self.assertEqual(absent, [dict(path='provider-diagnostics', kind='directory', reason='OSError')])
        self.assertTrue(any('could not be listed' in item for item in problems))
        with mock.patch.object(se.os, 'scandir', side_effect=scandir):
            exported = se.export_session(sim.root, client=sim.client)
        self.assertEqual(exported.status, 'partial')
        self.assertFalse(sim.document(exported.generation, se.REPORT_JSON)['establishes'])

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root reads through chmod 0')
    def test_an_unreadable_part_of_any_tree_costs_that_part_and_nothing_raises(self):
        sim, run = confirmed(self)
        for relative in ('runs/%s/game/telemetry' % run, 'runs/%s/game' % run, 'runs/%s' % run, 'runs', 'provisioning', 'execution', 'admissions'):
            with self.subTest(relative):
                path = sim.root / relative
                path.chmod(0)
                try:
                    exported = se.export_session(sim.root, client=sim.client)
                finally:
                    path.chmod(0o755)
                self.assertNotEqual(exported.status, 'complete')
                self.assertTrue(exported.problems)
                self.assertIn(relative, [item['path'] for item in sim.document(exported.generation)['not_inventoried']])
                report = sim.generation(exported.generation) / se.REPORT_JSON
                if report.exists():     # a tree this broken may cost the report too, and the inventory says so
                    self.assertFalse(json.loads(report.read_text())['establishes'])
        self.assertEqual(se.export_session(sim.root, client=sim.client).status, 'complete')

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root reads through chmod 0')
    def test_a_hostile_directory_name_stays_out_of_every_published_byte(self):
        sim, _ = confirmed(self)
        hostile = sim.root / ('198.51.100.' + '88')
        hostile.mkdir()
        hostile.chmod(0)
        self.addCleanup(hostile.chmod, 0o755)
        exported = se.export_session(sim.root, client=sim.client)
        top = sim.generation(exported.generation) / se.PUBLISHED
        self.assertTrue(top.is_dir(), sim.document(exported.generation).get('publication_refused'))
        data = {path.name: path.read_bytes() for path in top.iterdir()}
        self.assertEqual(ep.guard_problems(data), [])
        self.assertFalse(any(hostile.name.encode() in item for item in data.values()))


class FirstFailure(unittest.TestCase):
    """The actual copies and their timing, not just the registry's first-wins."""

    def setUp(self):
        self.sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        self.sim.ready()
        self.grace = self.sim.manifest['limits']['evidence_recovery_grace_s']
        self.first = []
        self.starts = []
        self.bounds = []
        self.faulty = None
        real = self.sim.guests.get

        def get(role, remote, local, timeout, on_wait=None):
            if '/do-runs/runs/' in str(remote):
                self.starts.append(self.sim.clock.wall())
                self.bounds.append((self.sim.clock.wall(), timeout))
            return real(role, remote, local, timeout, on_wait)
        self.sim.guests.get = get

    def registry_first(self):
        return [event for event in self.sim.stack.registry.journal(self.sim.session_id) if event['kind'] == 'evidence_failure']

    def fail_first_copy(self, then):
        """The first game copy of the session fails, and stays failing. ``then`` is what the next copy does."""
        def hook(role, run, relative, data, attempt):
            if role == 'game' and not self.first:
                self.first.append((self.sim.clock.wall(), relative))
                self.faulty = (role, relative)
                return 1, b'cut'
            if (role, relative) == self.faulty:
                return 1, b'cut'
            return then(role, relative, data)
        self.sim.guests.get_hook = hook

    def cutoff(self):
        return self.first[0][0] + self.grace

    def assert_original_episode(self):
        status = self.sim.status_now()
        event, = self.registry_first()
        self.assertEqual(session_clock.parse(event['data']['first_failure']), self.first[0][0])
        self.assertEqual(session_clock.parse(status['recovery_deadline_utc']), self.cutoff())
        self.assertLessEqual(max(self.starts), self.cutoff())
        for started, timeout in self.bounds:
            self.assertLessEqual(started + timeout, min(self.cutoff(), session_clock.parse(status['cleanup_c_utc'])) if started >= self.first[0][0] else float('inf'), 'nothing is allowed to outlast it')
        self.assertLessEqual(session_clock.parse(status['cleanup']['requested_at']), self.cutoff() + 1)

    def test_a_slow_later_file_does_not_move_the_episode(self):
        delayed = []

        def then(role, relative, data):
            if not delayed:
                delayed.append(True)
                self.sim.sleep(20)
            return 0, data
        self.fail_first_copy(then)
        self.sim.executor().run_batch()
        self.assert_original_episode()
        self.assertTrue(self.sim.status_now()['cleanup']['requested_at'])
        self.assertNotEqual(self.sim.status_now()['evidence']['status'], 'complete')

    def test_both_roles_are_still_collected_after_the_first_failure_and_within_the_episode(self):
        self.fail_first_copy(lambda role, relative, data: (0, data))
        self.sim.executor().run_batch()
        run = self.sim.records()[0]['run_id']
        self.assertTrue((self.sim.run_dir(run) / 'bot' / guest_runner.SEAL).exists(), 'the other role comes back all the same')
        self.assertTrue((self.sim.run_dir(run) / 'game' / guest_runner.SEAL).exists())
        self.assert_original_episode()
        retained = json.loads((self.sim.root / 'execution' / 'evidence-failure-0000.json').read_text())
        self.assertEqual((retained['role'], retained['path'], retained['kind']), ('game', self.first[0][1], 'transfer'))
        self.assertEqual(session_clock.parse(retained['observed_at']), self.first[0][0])

    def test_a_crash_between_files_leaves_the_failure_on_record_for_the_next_controller(self):
        def then(role, relative, data):
            raise rf.SimulatedCrash('between transfers')
        self.fail_first_copy(then)
        with self.assertRaises(rf.SimulatedCrash):
            self.sim.executor().execute()
        self.assertEqual(len(self.registry_first()), 1, 'the registry heard before another transfer started')
        self.sim.guests.get_hook = lambda role, run, relative, data, attempt: (1, b'cut') if (role, relative) == self.faulty else (0, data)
        self.sim.sleep(40)
        controller, _ = self.sim.controller()
        controller.collecting = True
        controller.prepare()
        controller.reconcile('operator_collect')
        controller.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='collect', detail='test'))
        self.assert_original_episode()

    def collect_after_crash(self, wait_s):
        self.sim.guests.get_hook = lambda role, run, relative, data, attempt: (1, b'cut') if (role, relative) == self.faulty else (0, data)
        self.sim.sleep(wait_s)
        controller, _ = self.sim.controller()
        controller.collecting = True
        controller.prepare()
        controller.reconcile('operator_collect')
        controller.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='collect', detail='test'))
        return controller

    def crash_on_next_copy(self):
        def then(role, relative, data):
            raise rf.SimulatedCrash('between transfers')
        self.fail_first_copy(then)

    def test_a_report_that_never_arrived_is_told_by_the_next_controller_as_old_as_it_was(self):
        self.crash_on_next_copy()
        executor = self.sim.executor()
        real = executor.client.call

        def lost(method, *arguments, **options):
            if method == 'record_evidence_failure':
                raise registry_client.RegistryUnavailable('lost')
            return real(method, *arguments, **options)
        with mock.patch.object(executor.client, 'call', side_effect=lost), self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.assertEqual(self.registry_first(), [], 'the registry never heard')
        self.assertTrue((self.sim.root / 'execution' / 'evidence-failure-0000.json').exists(), 'and this disk did')
        self.collect_after_crash(40)
        self.assert_original_episode()

    def test_an_acknowledgement_lost_after_the_write_cannot_move_it_either(self):
        self.crash_on_next_copy()
        executor = self.sim.executor()
        real = executor.client.call

        def ack_lost(method, *arguments, **options):
            answer = real(method, *arguments, **options)
            if method == 'record_evidence_failure':
                raise registry_client.RegistryUnavailable('the answer was lost')
            return answer
        with mock.patch.object(executor.client, 'call', side_effect=ack_lost), self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.assertEqual(len(self.registry_first()), 1)
        self.collect_after_crash(40)
        self.assert_original_episode()

    def test_a_failure_whose_record_this_disk_refused_still_reaches_the_registry(self):
        self.crash_on_next_copy()
        executor = self.sim.executor()
        with mock.patch.object(executor, '_write_durable', wraps=executor._write_durable) as wrapped, self.assertRaises(rf.SimulatedCrash):
            def refuse(path, text):
                if 'evidence-failure' in path.name:
                    raise OSError(errno.ENOSPC, 'full')
                return mock.DEFAULT
            wrapped.side_effect = refuse
            executor.execute()
        self.assertEqual(len(self.registry_first()), 1)

    def test_no_copy_starts_past_the_original_cutoff_when_a_controller_returns_after_it(self):
        self.crash_on_next_copy()
        with self.assertRaises(rf.SimulatedCrash):
            self.sim.executor().execute()
        before = len(self.starts)
        self.collect_after_crash(self.grace + 30)
        self.assertEqual(len(self.starts), before, 'nothing starts past the end of the episode')
        status = self.sim.status_now()
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertNotEqual(status['evidence']['status'], 'complete')
        self.assertEqual(session_clock.parse(status['recovery_deadline_utc']), self.cutoff())

    def test_stopping_and_sealing_are_not_transfers_and_keep_going_past_the_episode(self):
        self.crash_on_next_copy()
        with self.assertRaises(rf.SimulatedCrash):
            self.sim.executor().execute()
        before = len(self.sim.guests.commands)
        self.collect_after_crash(self.grace + 30)
        steps = [command.get('step') for command in self.sim.guests.commands[before:]]
        self.assertNotIn('get', steps)
        reconciled = list(self.sim.run_dir(self.sim.records()[0]['run_id']).glob('execution-reconciled-*.json'))
        self.assertTrue(reconciled or (self.sim.run_dir(self.sim.records()[0]['run_id']) / 'execution.json').exists(), 'the run was still stopped, sealed and written down')

    def test_a_batch_that_goes_on_past_a_recovered_failure_is_not_held_to_it_again(self):
        """A crash cost one file, the next controller fetched it inside the episode, and the operator's resume went on to dispatch more. That work has its own recovery allowance, and later transfers are not retries of the old failure."""
        self.crash_on_next_copy()
        with self.assertRaises(rf.SimulatedCrash):
            self.sim.executor().execute()
        self.sim.guests.get_hook = None
        self.sim.sleep(30)
        controller, control = self.sim.controller()
        self.assertTrue(controller.resume('operator', control)['resumed'])
        self.assertIsNotNone(controller.evidence_episode, 'until something else is dispatched this is still the episode')
        crashes = []

        def crash_once(point):
            if point == 'after_running_commit' and len(self.sim.records()) == 3 and not crashes:
                crashes.append(point)
                raise rf.SimulatedCrash(point)
        controller.failpoint = crash_once
        with self.assertRaises(rf.SimulatedCrash):
            controller.execute()
        self.assertIsNone(controller.evidence_episode)
        kinds = [event['kind'] for event in self.sim.stack.registry.journal(self.sim.session_id)]
        self.assertIn('evidence_failure_passed', kinds)
        self.assertIsNone(self.sim.stack.registry.session_row(self.sim.session_id)['recovery_first_failure_at'])
        self.assertGreater(self.sim.clock.wall(), self.cutoff() - self.grace + 60)
        while self.sim.clock.wall() <= self.cutoff():
            self.sim.sleep(30)
        returning, again = self.sim.controller(name='controller-c')
        self.assertTrue(returning.resume('operator-again', again)['resumed'], 'an old record a run was dispatched past binds nothing')
        self.assertIsNone(returning.evidence_episode)
        self.assertIsNone(self.sim.stack.registry.session_row(self.sim.session_id)['recovery_first_failure_at'])
        self.assertEqual(returning.run_batch().search_status, 'confirmed')
        self.assertGreater(max(self.starts), self.cutoff(), 'later runs still transfer')
        self.assertEqual(self.sim.status_now()['evidence']['status'], 'complete')
        self.assertIsNone(self.sim.status_now()['recovery_deadline_utc'])

    def test_a_later_failure_after_going_on_has_a_clock_of_its_own(self):
        self.crash_on_next_copy()
        with self.assertRaises(rf.SimulatedCrash):
            self.sim.executor().execute()
        self.sim.guests.get_hook = None
        self.sim.sleep(30)
        controller, control = self.sim.controller()
        self.assertTrue(controller.resume('operator', control)['resumed'])
        later = []

        def hook(role, run, relative, data, attempt):
            if role == 'bot' and not later and run.endswith('t03-refine-n030-r1'):
                later.append(self.sim.clock.wall())
            return (1, b'cut') if later and role == 'bot' else (0, data)
        self.sim.guests.get_hook = hook
        controller.run_batch()
        self.assertTrue(later)
        status = self.sim.status_now()
        self.assertEqual(session_clock.parse(status['recovery_deadline_utc']), later[0] + self.grace)
        self.assertGreater(later[0], self.cutoff() - self.grace)
        self.assertNotEqual(status['evidence']['status'], 'complete')

    def test_a_look_at_committed_runs_on_the_way_back_starts_no_episode(self):
        """A file that cannot be fetched now says nothing about a committed decision. It stays a note, and a batch that goes on is not on any clock for it."""
        sim = self.sim
        crash = []

        def crash_once(point):
            if point == 'after_running_commit' and len(sim.records()) == 2 and not crash:
                crash.append(point)
                raise rf.SimulatedCrash(point)
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=crash_once).execute()
        first = sim.records()[0]['run_id']
        path = sim.run_dir(first) / 'game' / 'sockets.ndjson'
        path.chmod(0o640)
        path.unlink()
        sim.guests.get_hook = lambda role, run, relative, data, attempt: (1, b'cut') if run == first else (0, data)
        controller, _ = sim.controller()
        controller.prepare()
        controller.reconcile('resume')
        self.assertEqual(self.registry_first(), [])
        self.assertIsNone(controller.evidence_episode)
        self.assertFalse(list((sim.root / 'execution').glob('evidence-failure-*.json')))


class FirstFailureAtTheRegistry(unittest.TestCase):
    def setUp(self):
        self.sim = ef.ExportSim(self)
        self.sim.ready()
        self.token = self.sim.result.fencing_token

    def report(self, **options):
        return self.sim.client.mutate('record_evidence_failure', session_id=self.sim.session_id, fencing_token=self.token, detail='test', **options)

    def test_an_age_can_only_make_an_episode_earlier_and_is_held_to_being_one(self):
        now = self.sim.clock.wall()
        answer = self.report(observed_age_s=40)
        self.assertEqual(session_clock.parse(answer['first_failure_at']), now - 40)
        self.assertEqual(session_clock.parse(answer['recovery_deadline_utc']), now - 40 + self.sim.manifest['limits']['evidence_recovery_grace_s'])
        for bad in (-1, True, math.inf, math.nan, '40'):
            with self.subTest(bad), self.assertRaises(registry_client.RegistryRejected):
                self.report(observed_age_s=bad)

    def test_a_later_report_changes_nothing_and_a_fixed_deadline_stays_fixed(self):
        first = self.report(observed_age_s=5)
        self.sim.clock.advance(10)
        self.assertEqual(self.report(observed_age_s=60)['first_failure_at'], first['first_failure_at'])
        self.sim.client.mutate('begin_collection', session_id=self.sim.session_id, fencing_token=self.token)
        episode = self.sim.client.mutate('begin_evidence_recovery', session_id=self.sim.session_id, fencing_token=self.token)
        self.assertEqual(self.report()['recovery_deadline_utc'], episode['recovery_deadline_utc'])

    def test_c_bounds_the_answer(self):
        c = session_clock.parse(self.sim.status_now()['cleanup_c_utc'])
        while c - self.sim.clock.wall() > 60:
            self.sim.sleep(30)
            self.sim.client.call('renew_control', session_id=self.sim.session_id, fencing_token=self.token)
        self.assertEqual(session_clock.parse(self.report()['recovery_deadline_utc']), c)


class LocalPlacementIsNotPublication(unittest.TestCase):
    def setUp(self):
        self.sim, _ = confirmed(self)
        directory = tempfile.mkdtemp(prefix='omega-publication-')
        self.addCleanup(shutil.rmtree, directory, True)
        self.base = pathlib.Path(directory)
        self.root = self.base / ep.CANONICAL_ROOT
        self.root.mkdir(parents=True)
        self.summary = (self.sim.generation('gen-0001') / 'published' / 'summary.md').read_bytes()

    def reference(self, commit='a' * 40):
        return 'https://github.com/example/repository/tree/%s/%s/sessions/%s/gen-0001' % (commit, ep.CANONICAL_ROOT, self.sim.session_id)

    def test_a_directory_with_the_canonical_suffix_and_no_repository_is_only_local(self):
        self.assertFalse((self.base / '.git').exists())
        receipt, = ep.publish(self.sim.root, 'gen-0001', [ep.RepositoryDocs(self.root)], '2026-11-06T00:00:00+00:00')
        self.assertEqual((receipt['status'], receipt['publication'], receipt['reference']), (ep.VERIFIED_LOCAL, ep.UNVERIFIED, None))
        self.assertEqual(receipt['local_reference'], '%s/sessions/%s/gen-0001' % (ep.CANONICAL_ROOT, self.sim.session_id))
        status = ep.publication_status(self.sim.root)
        self.assertEqual(status['status'], ep.VERIFIED_LOCAL)
        self.assertEqual(status['publication']['status'], ep.UNVERIFIED)
        self.assertIsNone(status['publication']['reference'])
        self.assertIn('this machine only', status['statement'])
        later = se.export_session(self.sim.root, client=self.sim.client)
        report = self.sim.document(later.generation, se.REPORT_JSON)['publication']
        self.assertEqual(report['status'], ep.VERIFIED_LOCAL)
        self.assertIn('Publication: `verified_local`. Written under the canonical path', (self.sim.generation(later.generation) / se.REPORT_MD).read_text())

    def test_a_receipt_of_the_local_destination_can_say_no_more_than_local_whatever_it_says(self):
        ep._write_receipt(self.sim.root, dict(schema=ep.RECEIPT_SCHEMA, destination=ep.RepositoryDocs.name, generation='gen-0001', status=ep.PUBLISHED, reference='https://example.com/x'))
        status = ep.publication_status(self.sim.root)
        self.assertNotEqual(status['status'], ep.PUBLISHED)
        self.assertEqual(status['publication']['status'], ep.UNVERIFIED)

    def adapter(self, reference='https://docs.example/session/gen-0001', tamper=False):
        class Publisher:
            name = ep.PUBLICATION_NAME
            publishes = True

            def __init__(self):
                self.files = {}

            def reference(self, session_id, generation):
                return reference

            def put(self, session_id, generation, files):
                self.files.update(files)

            def read_back(self, session_id, generation, name):
                return b'other bytes' if tamper else self.files[name]
        return Publisher()

    def test_only_an_adapter_reading_back_from_an_accessible_reference_can_say_published(self):
        adapter = self.adapter()
        receipt, = ep.publish(self.sim.root, 'gen-0001', [ep.RepositoryDocs(self.root), adapter], '2026-11-06T00:00:00+00:00')[1:]
        self.assertEqual((receipt['status'], receipt['reference'], receipt['checked_by_this_tool']), (ep.PUBLISHED, 'https://docs.example/session/gen-0001', True))
        self.assertEqual(sorted(adapter.files), sorted(ep.PUBLISHED_FILES), 'the three text files, and nothing raw')
        status = ep.publication_status(self.sim.root)
        self.assertEqual(status['status'], ep.PUBLISHED)
        self.assertTrue(status['publication']['checked_by_this_tool'])
        self.assertEqual(status['repository']['status'], ep.VERIFIED_LOCAL, 'the local copy stays what it is')

    def test_an_adapter_with_no_accessible_reference_or_other_bytes_publishes_nothing(self):
        for adapter, code in ((self.adapter(reference=str(self.root)), 'reference_not_accessible'), (self.adapter(reference='docs/relative/path'), 'reference_not_accessible'), (self.adapter(tamper=True), 'read_back_mismatch')):
            with self.subTest(code):
                receipt, = ep.publish(self.sim.root, 'gen-0001', [adapter], 'now')
                self.assertEqual((receipt['status'], receipt['code'], receipt['reference']), (ep.FAILED, code, None))
                self.assertEqual(ep.publication_status(self.sim.root)['status'], ep.FAILED)

    def test_text_the_guard_refuses_reaches_no_adapter(self):
        directory = self.sim.generation('gen-0001') / 'published'
        (directory / 'summary.md').chmod(0o640)
        (directory / 'summary.md').write_text('held at 198.51.100.' + '77')
        adapter = self.adapter()
        with self.assertRaises(ep.PublicationRefused) as refused:
            ep.publish(self.sim.root, 'gen-0001', [adapter], 'now')
        self.assertEqual(refused.exception.code, 'guard_refused')
        self.assertEqual(adapter.files, {})

    def test_the_operators_record_names_who_where_and_which_bytes_and_never_reads_as_checked(self):
        good = dict(reference=self.reference(), now='now', summary_sha256=ep.sha256_bytes(self.summary), operator='the operator')
        for change, code in ((dict(summary_sha256='0' * 64), 'publication_of_other_text'), (dict(reference='https://github.com/example/repository/tree/main/x'), 'reference_not_accessible'), (dict(reference=str(self.root)), 'reference_not_accessible'), (dict(operator=' '), 'publication_not_attributed')):
            with self.subTest(code), self.assertRaises(ep.PublicationRefused) as refused:
                ep.record_publication(self.sim.root, 'gen-0001', **dict(good, **change))
            self.assertEqual(refused.exception.code, code)
        self.assertEqual(ep.publication_status(self.sim.root)['status'], ep.NOT_PUBLISHED)
        record = ep.record_publication(self.sim.root, 'gen-0001', **good)
        self.assertEqual((record['status'], record['recorded_by'], record['checked_by_this_tool']), (ep.OPERATOR_RECORDED, 'the operator', False))
        self.assertEqual(sorted(record['files']), sorted(ep.PUBLISHED_FILES))
        status = ep.publication_status(self.sim.root)
        self.assertEqual(status['status'], ep.OPERATOR_RECORDED)
        self.assertEqual((status['publication']['reference'], status['publication']['checked_by_this_tool']), (self.reference(), False))
        later = se.export_session(self.sim.root, client=self.sim.client)
        self.assertEqual(self.sim.document(later.generation, se.REPORT_JSON)['publication']['status'], ep.OPERATOR_RECORDED)
        self.assertEqual(se.reproduce(self.sim.root, later.generation), [])

    def test_the_journal_seam_stays_not_published_until_someone_does_it(self):
        ep.publish(self.sim.root, 'gen-0001', [ep.RepositoryDocs(self.root)], 'now')
        self.assertEqual(ep.publication_status(self.sim.root)['journal_mirror']['status'], ep.NOT_PUBLISHED)


class PeerPeak(unittest.TestCase):
    def test_one_bad_peer_beside_a_passing_mean_reaches_every_report_and_decides_nothing(self):
        def high_peer(tree, trial):
            sf.set_loss(tree, lambda bot, second: cs.LOSS_SCALE // 5 if bot == 1 else 0)
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=high_peer))
        sim.batch()
        run = sim.records()[0]['run_id']
        score = json.loads((sim.run_dir(run) / 'score.json').read_text())['gates']['enet_loss']
        self.assertEqual(sim.records()[0]['outcome'], 'PASS')
        expected = round(score['peer_peak']['ratio']['approximate'], 6)
        self.assertGreater(expected, 0.19)
        report = sim.document('gen-0001', se.REPORT_JSON)['runs'][0]['diagnostics']['peers']
        published = sim.document('gen-0001', 'published/summary.json')['runs'][0]['peers']
        per_run = json.loads((sim.run_dir(run) / 'summary.json').read_text())['diagnostics']['peers']
        for peers in (report, published, per_run):
            self.assertEqual(peers['loss_estimate_peer_peak'], expected)
            self.assertEqual(peers['loss_estimate_peer_peak_bot'], score['peer_peak']['bot'])
            self.assertEqual(peers['loss_estimate_peer_peak_at_bot_mono_ns'], score['peer_peak']['at_bot_mono_ns'])
            self.assertEqual(peers['loss_estimator'], 'ENet smoothed estimate of reliable commands lost')
            self.assertIn('decides nothing', peers['loss_estimate_peer_peak_scope'])
            self.assertLess(peers['loss_estimate_peak_per_second_mean'], 0.01, 'the mean the gate reads stays beside it')
        for text in ((sim.generation('gen-0001') / se.REPORT_MD).read_text(), (sim.generation('gen-0001') / 'published' / 'summary.md').read_text(), (sim.run_dir(run) / 'REPORT.md').read_text()):
            self.assertIn('Loss est. peer peak (bot)', text)
            self.assertIn('%s (bot %s)' % (expected, score['peer_peak']['bot']), text)
        self.assertEqual(sim.document('gen-0001').get('publication_refused'), None)

    def test_a_score_with_no_peer_reading_reads_as_unknown(self):
        self.assertIsNone(sr._peer_diagnostics({})['loss_estimate_peer_peak'])
        self.assertEqual(sr._peer_peak_cell(sr._peer_diagnostics({})), 'unknown')


if __name__ == '__main__':
    unittest.main()
