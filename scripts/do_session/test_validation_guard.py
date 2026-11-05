"""Whether a comparison of transferred bytes can be forgotten. A guard is on disk and acknowledged before any byte is judged, outside the run directory whose sync may fail, and it ends only when what was found is retained or the registry has acknowledged a stop.

Everything goes through the real executor, registry and report over a fake guest. ``test_durable_namespace`` says what the name-loss model is and is not: nothing here is a real power cut, and failing an ``os.fsync`` in a test is not a failing disk.
"""
import contextlib
import json
import os
import pathlib
import shutil
import stat
import unittest
from unittest import mock

import capacity_report
import capacity_scorer as cs
import do_session
import registry_client
import run_executor
import run_fixtures as rf
import test_capacity_integrity as integrity
import test_durable_namespace as dn
import test_stop_record_lifecycle as life
from search import INCOMPLETE, INFRASTRUCTURE_FAILURE, PASS

DURABLE = run_executor.DIRECTORY_NOT_DURABLE
UNVERIFIED = life.UNVERIFIED
FIRST_CONFIRMATION = 3     # 25 PASS, 50 FAIL and 30 FAIL come first


def is_guard(path):
    return pathlib.Path(path).parent.name == cs.VALIDATION_GUARD_DIR


class SyscallLoss(dn.NamespaceLoss):
    """The name-loss tracker, with the failure injected where a disk would give it: the actual ``os.fsync`` of the chosen directory, through the real helper."""

    def __init__(self, session_dir, fails=()):
        super().__init__(session_dir, fails)
        self.failed = []

    def sync(self, directory):
        key = os.path.realpath(str(directory))
        if self.armed and key in self.fails:
            def refuse(handle):
                self.assert_directory(handle)
                self.failed.append(key)
                raise OSError('injected: fsync of this directory failed')
            with mock.patch.object(do_session.os, 'fsync', refuse):
                self.real(directory)
            return
        super().sync(directory)

    @staticmethod
    def assert_directory(handle):
        if not stat.S_ISDIR(os.fstat(handle).st_mode):
            raise AssertionError('only a directory sync should fail here')


class Fixture(dn.Confirmation):
    def guards(self, sim):
        return sorted((sim.stack.root / cs.VALIDATION_GUARD_DIR).glob('*.json'))

    def assertNoClaim(self, sim):
        report = capacity_report.build(sim.stack.root)
        self.assertFalse(report['claim']['confirmed'], report['claim'])
        self.assertFalse(report['evidence']['verified'])
        self.assertTrue(report['evidence']['trials_with_unverified_stop_records'])
        capacity_report.render_search(report)

    def assertHeldBack(self, sim, resumed, dispatched, starts=4):
        self.assertFalse(resumed['resumed'], resumed)
        self.assertEqual(resumed['code'], UNVERIFIED, resumed)
        self.assertEqual(dispatched.code, UNVERIFIED)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts, 'no sibling starts')
        self.assertIsNone(sim.status_now()['terminal_failure'], 'and nothing irreversible is said without a fact')
        self.assertIsNone(sim.records()[-1]['outcome'], 'nor is the run decided from a later look')
        self.assertNoClaim(sim)

    def operator_lets_it_go(self, sim):
        """After looking. Removing the guard is the only way past it, and the run is then decided from what is there."""
        rf.make_writable(sim.stack.root)
        for path in self.guards(sim):
            path.unlink()
        executor, control = sim.controller(name='after-operator-removal')
        resumed = executor.resume('operator', control)
        self.assertTrue(resumed.get('resumed'), resumed)
        return executor

    def confirmation_with(self, sim, point):
        """Dies at ``point`` in the first confirmation."""
        def at(name):
            if name == point and len(sim.records()) == FIRST_CONFIRMATION + 1:
                raise rf.SimulatedCrash()
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=at).execute()


class AKnownSyncFailureThenALoss(Fixture):
    """The actual system call fails while what was found is written down, and then only the two new names it failed to cover are taken. Everything older stays, including the seal receipt, the run directory and the registry."""

    def fails_then_loses(self, corrupt):
        sim = self.sim_of(life.RULES)
        watch = SyscallLoss(sim.stack.root)
        _, notes = self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=watch, boundary='run')
        self.assertTrue(watch.failed, 'the real syscall was reached')
        self.assertLessEqual({'corrupt_observation_not_retained', 'corrupt_bytes_not_retained'}, set(notes))
        run_id = sim.records()[-1]['run_id']
        run_dir = sim.run_dir(run_id)
        self.assertTrue(watch.held(run_dir) and watch.held(run_dir / 'grant.json') and all(watch.held(path) for path in run_dir.glob(cs.SEAL_RECEIPT_GLOB)), 'what is older is still durable')
        self.assertTrue(self.guards(sim) and all(watch.held(path) for path in self.guards(sim)), 'and so is the guard, which no failed sync of this directory covers')
        rf.make_writable(run_dir)
        lost = list(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB))
        self.assertTrue(lost)
        for path in lost:
            self.assertFalse(watch.held(path))
            path.unlink()
        self.assertFalse(watch.held(run_dir / cs.CORRUPT_EVIDENCE_DIR))
        shutil.rmtree(str(run_dir / cs.CORRUPT_EVIDENCE_DIR))
        return sim, run_dir

    def test_the_restored_transfer_cannot_make_it_forget(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim, _ = self.fails_then_loses(corrupt)
                resumed, dispatched = self.come_back(sim)
                self.assertHeldBack(sim, resumed, dispatched)

    def test_every_later_return_refuses_the_same_way_and_decides_nothing(self):
        sim, _ = self.fails_then_loses('seal.json')
        for _ in range(2):
            resumed, dispatched = self.come_back(sim)
            self.assertHeldBack(sim, resumed, dispatched)
        self.assertEqual(sim.outcomes()[:3], [('coarse', 25, PASS), ('coarse', 50, 'FAIL'), ('refine', 30, 'FAIL')], 'decisions already made stay what they were')

    def test_only_an_operator_who_has_looked_lets_the_search_go_on(self):
        sim, _ = self.fails_then_loses('bot.stdout.log')
        self.come_back(sim)
        executor = self.operator_lets_it_go(sim)
        self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], PASS, 'decided from the good bytes')
        executor.execute()
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 6)

    def test_with_nothing_lost_it_is_still_the_fact_it_was(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(life.RULES)
                self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=SyscallLoss(sim.stack.root), boundary='run')
                resumed, _ = self.come_back(sim)
                self.assertEqual(resumed['code'], life.TERMINAL, 'a process crash takes no names')
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)
                self.assertEqual(self.guards(sim), [], 'the stop was heard, which says more than the guard could')

    def test_the_most_the_model_may_take_refuses_the_same_way(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(life.RULES)
                watch = SyscallLoss(sim.stack.root)
                self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=watch, boundary='run')
                lost = watch.power_cut()
                self.assertFalse([name for name in lost if name.startswith(cs.VALIDATION_GUARD_DIR)], 'an acknowledged guard is not among what may go')
                resumed, dispatched = self.come_back(sim)
                self.assertFalse(resumed['resumed'])
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4, dispatched)
                self.assertFalse(capacity_report.build(sim.stack.root)['claim']['confirmed'])

    def test_a_recovery_of_a_committed_run_is_held_to_the_same(self):
        """The same two failures, found going back over a run whose PASS is already immutable."""
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = life.Fixture.returning(self, corrupt)
                watch = SyscallLoss(sim.stack.root)
                executor, control = sim.controller()
                executor.failpoint = rf.crash_at('after_corrupt_bytes')
                real = executor._corrupt_receipt

                def during(*arguments):
                    watch.fails = {os.path.realpath(str(run_dir))}
                    try:
                        return real(*arguments)
                    finally:
                        watch.fails = set()
                executor._corrupt_receipt = during
                with watch.watching(), self.assertRaises(rf.SimulatedCrash):
                    executor.resume('operator', control)
                rf.make_writable(run_dir)
                for path in run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB):
                    path.unlink()
                shutil.rmtree(str(run_dir / cs.CORRUPT_EVIDENCE_DIR))
                sim.guests.corrupt_export.clear()
                later, control = sim.controller(name='controller-later')
                resumed, dispatched = later.resume('operator', control), later.execute()
                self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                self.assertEqual(dispatched.code, UNVERIFIED)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)])
                self.assertIsNone(sim.status_now()['terminal_failure'])
                for name, data in history.items():
                    self.assertEqual((run_dir / name).read_bytes(), data)


class NoGuardMeansNoComparison(Fixture):
    """Failing to establish the guard at each thing it takes. Corrupt bytes are on the way each time, and nothing may be found, kept, published or advanced past."""

    def at_the_comparison(self, sim, failing):
        """``failing`` is entered for the rest of the first confirmation, from just before its export."""
        entered = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)

        def at(point):
            if point == 'after_outcome_commit' and len(sim.records()) == FIRST_CONFIRMATION:
                sim.guests.corrupt_export.add('bot.stdout.log')
            if point == 'after_seal' and len(sim.records()) == FIRST_CONFIRMATION + 1 and not entered:
                entered.append(True)
                stack.enter_context(failing())
        return sim.executor(failpoint=at), stack

    def failures(self, sim):
        guards = sim.stack.root / cs.VALIDATION_GUARD_DIR
        return dict(file_fsync=lambda: life.writes_fail('file_fsync', is_guard), link=lambda: life.writes_fail('link', is_guard), open=lambda: life.writes_fail('open', is_guard),
                    guard_directory=lambda: SyscallLoss(sim.stack.root, fails=[guards]).watching(), session_directory=lambda: SyscallLoss(sim.stack.root, fails=[sim.stack.root]).watching())

    def assertUnjudged(self, sim):
        run_id = sim.records()[FIRST_CONFIRMATION]['run_id']
        run_dir = sim.run_dir(run_id)
        self.assertEqual(list(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB)), [], 'nothing was found')
        self.assertFalse((run_dir / cs.CORRUPT_EVIDENCE_DIR).exists())
        self.assertEqual(list(run_dir.glob('*/seal.json')), [], 'and nothing was promoted')
        self.assertTrue(list(run_dir.glob('*/*.partial')), 'what came back stays unjudged')
        self.assertIsNone(sim.records()[FIRST_CONFIRMATION]['outcome'])
        self.assertIsNone(sim.status_now()['terminal_failure'], 'this disk says nothing about any host')
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4, 'and no sibling starts')
        self.assertFalse(capacity_report.build(sim.stack.root)['claim']['confirmed'])

    def test_each_failure_stops_it_short_of_the_comparison(self):
        for name in self.failures(self.sim_of(life.RULES)):
            with self.subTest(name):
                sim = self.sim_of(life.RULES)
                executor, stack = self.at_the_comparison(sim, self.failures(sim)[name])
                result = executor.execute()
                stack.close()
                self.assertEqual(result.code, DURABLE, result)
                self.assertUnjudged(sim)

    def test_it_says_nothing_afterwards_and_a_disk_that_recovers_finishes_the_job(self):
        for name in self.failures(self.sim_of(life.RULES)):
            with self.subTest(name):
                sim = self.sim_of(life.RULES)
                executor, stack = self.at_the_comparison(sim, self.failures(sim)[name])
                executor.execute()
                stack.close()
                self.assertEqual(self.guards(sim), [], 'no comparison followed it, so it says none may have')
                sim.guests.corrupt_export.clear()
                later, control = sim.controller(name='controller-later')
                resumed = later.resume('operator', control)
                self.assertTrue(resumed.get('resumed'), resumed)
                self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], PASS)

    def test_it_ends_the_batch_with_cleanup_requested(self):
        sim = self.sim_of(life.RULES)
        executor, stack = self.at_the_comparison(sim, self.failures(sim)['guard_directory'])
        result = executor.run_batch()
        stack.close()
        self.assertEqual(result.code, DURABLE)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_a_guard_that_could_not_be_removed_still_refuses_and_that_is_all_it_costs(self):
        sim = self.sim_of(life.RULES)

        @contextlib.contextmanager
        def nothing_works():
            with SyscallLoss(sim.stack.root, fails=[sim.stack.root / cs.VALIDATION_GUARD_DIR]).watching(), life.fails_at('unlink'):
                yield
        executor, stack = self.at_the_comparison(sim, nothing_works)
        self.assertEqual(executor.execute().code, DURABLE)
        stack.close()
        self.assertTrue(self.guards(sim), 'a final name this controller could neither commit nor take back')
        resumed, dispatched = self.come_back(sim)
        self.assertHeldBack(sim, resumed, dispatched)

    def test_while_collecting_it_keeps_going_to_cleanup_and_still_judges_nothing(self):
        sim = self.sim_of(life.RULES)
        sim.guests.corrupt_export.add('bot.stdout.log')
        self.crash(sim, 'after_seal')
        with SyscallLoss(sim.stack.root, fails=[sim.stack.root / cs.VALIDATION_GUARD_DIR]).watching():
            executor = self.collect(sim)
            executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture', runs=executor.outcomes))
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        self.assertEqual(list(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB)), [])
        self.assertEqual(sim.records()[0]['outcome'], INCOMPLETE, 'unjudged bytes decide nothing')
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
        self.assertIsNone(sim.status_now()['terminal_failure'])


class AProcessCrashInTheComparison(Fixture):
    def test_at_either_end_of_it_nothing_can_say_how_it_came_out(self):
        for point in ('after_validation_guard', 'before_validation_end'):
            with self.subTest(point):
                sim = self.sim_of(life.RULES)
                self.confirmation_with(sim, point)
                self.assertTrue(self.guards(sim))
                resumed, dispatched = self.come_back(sim)
                self.assertHeldBack(sim, resumed, dispatched)
                self.operator_lets_it_go(sim)
                self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], PASS)

    def test_a_crash_in_the_transfer_before_it_leaves_nothing_to_answer_for(self):
        sim = self.sim_of(life.RULES)
        guests = sim.guests
        real, calls = guests.get, []

        def get(role, remote, local, timeout_s, on_wait=None):
            if len(sim.records()) == FIRST_CONFIRMATION + 1 and not calls:
                calls.append(remote)
                raise rf.SimulatedCrash()
            return real(role, remote, local, timeout_s, on_wait)
        with mock.patch.object(guests, 'get', get), self.assertRaises(rf.SimulatedCrash):
            sim.executor().execute()
        self.assertEqual(self.guards(sim), [])
        executor, control = sim.controller(name='controller-later')
        resumed = executor.resume('operator', control)
        self.assertTrue(resumed.get('resumed'), resumed)
        self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], PASS)

    def test_crashes_on_either_side_of_the_comparison_replay_as_they_always_did(self):
        for point in ('after_stop', 'after_seal', 'after_execution_record', 'after_score_retained', 'before_outcome_commit', 'after_outcome_commit'):
            with self.subTest(point):
                sim = self.sim_of(life.RULES)
                self.confirmation_with(sim, point)
                self.assertEqual(self.guards(sim), [], 'nothing is left open')
                executor, control = sim.controller(name='controller-later')
                resumed = executor.resume('operator', control)
                self.assertTrue(resumed.get('resumed'), resumed)
                self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], PASS)

    def test_a_genuine_stop_of_the_same_return_is_not_held_up_by_it(self):
        sim = self.sim_of(life.RULES)
        self.confirmation_with(sim, 'after_validation_guard')
        run_dir = sim.run_dir(sim.records()[FIRST_CONFIRMATION]['run_id'])
        role = json.loads(self.guards(sim)[0].read_text())['role']
        (run_dir / 'terminal-fact-0002-0.json').write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_dir.name, role=role, outcome=INFRASTRUCTURE_FAILURE, details=['a stop of its own'], fencing_token=2, found_at='2026-10-30T00:00:00Z')))
        executor, control = sim.controller(name='controller-later')
        resumed = executor.resume('operator', control)
        self.assertFalse(resumed['resumed'])
        self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], INFRASTRUCTURE_FAILURE, 'it becomes the outcome')
        self.assertEqual(self.guards(sim), [])
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)

    def test_a_genuine_stop_the_guard_does_not_answer_for_is_not_held_up_either(self):
        """A fact of the other role, or a receipt-free reason in an execution generation, says nothing of the comparison, so the guard stays unresolved. The stop still decides the run, and once the registry has it the guard has nothing left to hold back."""
        def other_role(sim, run_dir, role):
            (run_dir / 'terminal-fact-0002-0.json').write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_dir.name, role='bot' if role == 'game' else 'game', outcome=INFRASTRUCTURE_FAILURE, details=['a stop of its own'], fencing_token=2, found_at='2026-10-30T00:00:00Z')))

        def execution_generation(sim, run_dir, role):
            record = json.loads((run_dir / 'execution.json').read_text()) if (run_dir / 'execution.json').exists() else dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_dir.name, problems={}, interrupted=None)
            record.update(writer='reconcile', fencing_token=2, demonstrated_outcome=dict(outcome=INFRASTRUCTURE_FAILURE, reasons=['bot host rebooted']), demonstrated_problems={}, uncertain=[], exported={})
            (run_dir / 'execution-reconciled-0002-1.json').write_text(json.dumps(record))
        for arrange in (other_role, execution_generation):
            with self.subTest(arrange.__name__):
                sim = self.sim_of(life.RULES)
                self.confirmation_with(sim, 'after_validation_guard')
                run_dir = sim.run_dir(sim.records()[FIRST_CONFIRMATION]['run_id'])
                arrange(sim, run_dir, json.loads(self.guards(sim)[0].read_text())['role'])
                self.assertTrue(cs.stop_records(run_dir, dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_dir.name))[1], 'still unresolved')
                executor, control = sim.controller(name='controller-later')
                self.assertFalse(executor.resume('operator', control)['resumed'])
                self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], INFRASTRUCTURE_FAILURE, 'it becomes the outcome')
                self.assertEqual(self.guards(sim), [])
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)

    def test_collecting_past_it_decides_nothing_from_a_later_look_and_reaches_cleanup(self):
        sim = self.sim_of(life.RULES)
        self.confirmation_with(sim, 'before_validation_end')
        executor = self.collect(sim)
        executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture', runs=executor.outcomes))
        self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], INCOMPLETE)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertFalse(capacity_report.build(sim.stack.root)['claim']['confirmed'])

    def test_a_retained_pass_does_not_get_past_it_while_collecting(self):
        """The score and the classification are already written when a later comparison of the same run leaves a guard behind."""
        sim = self.sim_of(life.RULES)
        self.confirmation_with(sim, 'before_outcome_commit')
        guard = sim.stack.root / cs.VALIDATION_GUARD_DIR / cs.validation_guard_name(sim.records()[FIRST_CONFIRMATION]['run_id'], 'bot', 1, 9)
        guard.write_text(json.dumps(cs.validation_guard(sim.session_id, sim.sha, sim.records()[FIRST_CONFIRMATION]['run_id'], 'bot', 1, '2026-10-30T00:00:00Z')))
        self.collect(sim)
        self.assertEqual(sim.records()[FIRST_CONFIRMATION]['outcome'], INCOMPLETE)
        verdict = json.loads(next(path for path in sim.run_dir(sim.records()[FIRST_CONFIRMATION]['run_id']).glob('classification-reconciled-*.json')).read_text())['verdict']
        self.assertEqual([item['file'] for item in verdict['supersedes']], ['classification.json', 'score.json'])


class GuardDirectoryFailures(Fixture):
    def pending(self):
        sim = self.sim_of(life.RULES)
        real = pathlib.Path.unlink

        def unlink(path, *args, **kwargs):
            if is_guard(path) and path.suffix == '.json' and '--game-' in path.name and len(sim.records()) == 4:
                raise OSError('guard removal failed')
            return real(path, *args, **kwargs)
        with mock.patch.object(pathlib.Path, 'unlink', unlink):
            self.confirmation_with(sim, 'before_outcome_commit')
        return sim, sim.stack.root / cs.VALIDATION_GUARD_DIR

    @contextlib.contextmanager
    def unreadable(self, directory):
        directory.chmod(0)
        try:
            with self.assertRaises(PermissionError):
                os.listdir(directory)
            yield
        finally:
            directory.chmod(0o700)

    def test_unreadable_directory_preserves_pending_run_and_guard(self):
        sim, directory = self.pending()
        guards = self.guards(sim)
        with self.unreadable(directory):
            self.assertHeldBack(sim, *self.come_back(sim))
        self.assertEqual(self.guards(sim), guards)
        self.assertHeldBack(sim, *self.come_back(sim))

    def test_enumeration_error_preserves_pending_outcome_not_just_dispatch(self):
        sim, _ = self.pending()
        with mock.patch.object(cs, 'validation_guards', side_effect=OSError('scan failed')):
            self.assertHeldBack(sim, *self.come_back(sim))

    def test_non_directory_is_uncertainty_and_absent_legacy_directory_is_empty(self):
        sim, directory = self.pending()
        held = directory.with_name('held-guards')
        directory.rename(held)
        run_dir = sim.run_dir(sim.records()[-1]['run_id'])
        self.assertEqual(cs.validation_guards(run_dir), [])
        directory.write_text('not a directory')
        try:
            self.assertHeldBack(sim, *self.come_back(sim))
        finally:
            directory.unlink()
            held.rename(directory)

    def test_independent_stop_wins_and_cleanup_runs_with_unreadable_guards(self):
        sim, directory = self.pending()
        run_dir = sim.run_dir(sim.records()[-1]['run_id'])
        (run_dir / 'terminal-fact-0002-0.json').write_text(json.dumps(dict(
            schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id,
            manifest_sha256=sim.sha, run_id=run_dir.name, role='bot',
            outcome=INFRASTRUCTURE_FAILURE, details=['bot host rebooted'],
            fencing_token=2, found_at='2026-10-30T00:00:00Z')))
        with self.unreadable(directory):
            executor, control = sim.controller(name='returning')
            self.assertFalse(executor.resume('operator', control)['resumed'])
            self.assertEqual(sim.records()[-1]['outcome'], INFRASTRUCTURE_FAILURE)
            executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture', runs=executor.outcomes))
            self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
            self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)

    def test_collect_reaches_cleanup_without_deciding_pass(self):
        sim, directory = self.pending()
        with self.unreadable(directory):
            executor = self.collect(sim)
            executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture', runs=executor.outcomes))
            self.assertEqual(sim.records()[-1]['outcome'], INCOMPLETE)
            self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
            self.assertNoClaim(sim)


class WhenItEnds(Fixture):
    def test_a_healthy_search_leaves_none(self):
        sim = self.sim_of(life.RULES)
        result = sim.executor().execute()
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual(self.guards(sim), [])
        self.assertTrue(capacity_report.build(sim.stack.root)['claim']['confirmed'])

    def test_what_was_found_and_retained_ends_it(self):
        sim = self.sim_of(life.RULES)
        self.corrupt_confirmation(sim, 'seal.json', crash='after_execution_record')
        self.assertEqual(self.guards(sim), [], 'observation and bytes are durable')

    def test_a_failed_write_keeps_it_until_the_registry_has_heard(self):
        sim = self.sim_of(life.RULES)
        watch = SyscallLoss(sim.stack.root)
        self.corrupt_confirmation(sim, 'seal.json', crash='after_execution_record', watch=watch, boundary='run')
        self.assertTrue(self.guards(sim), 'nothing durable says what it found yet')

    def test_the_stop_being_acknowledged_ends_it(self):
        sim = self.sim_of(life.RULES)
        watch = SyscallLoss(sim.stack.root)
        self.corrupt_confirmation(sim, 'seal.json', watch=watch, boundary='run')
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(self.guards(sim), [])

    def test_the_registry_hearing_of_a_committed_runs_failure_ends_it(self):
        """Nothing durable says what was found, since the run directory would not sync, so only the acknowledged stop can end this one."""
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, _ = life.Fixture.returning(self, corrupt)
                watch = SyscallLoss(sim.stack.root)
                executor, control = sim.controller()
                real, held = executor._corrupt_receipt, []

                def during(*arguments):
                    watch.fails = {os.path.realpath(str(run_dir))}
                    try:
                        answer = real(*arguments)
                    finally:
                        watch.fails = set()
                    held.append(arguments[-1].retained)
                    return answer
                executor._corrupt_receipt = during
                with watch.watching():
                    resumed = executor.resume('operator', control)
                self.assertEqual(held, [False], 'it could not be kept')
                self.assertEqual(resumed['code'], life.TERMINAL, resumed)
                self.assertEqual(self.guards(sim), [])

    def test_a_guard_stays_while_the_registry_has_not_heard(self):
        sim, run_dir, _ = life.Fixture.returning(self, 'seal.json')
        watch = SyscallLoss(sim.stack.root)
        executor, control = sim.controller()
        integrity.UnacknowledgedStops.stop_fails(executor, registry_client.RegistryUnavailable('down'))
        real = executor._corrupt_receipt

        def during(*arguments):
            watch.fails = {os.path.realpath(str(run_dir))}
            try:
                return real(*arguments)
            finally:
                watch.fails = set()
        executor._corrupt_receipt = during
        with watch.watching():
            executor.resume('operator', control)
        self.assertTrue(self.guards(sim))

    def test_a_guard_that_cannot_be_removed_keeps_refusing_and_breaks_nothing(self):
        sim = self.sim_of(life.RULES)
        real = pathlib.Path.unlink

        def unlink(path, *arguments, **options):
            if is_guard(path) and path.suffix == '.json':
                raise OSError('injected: unlink failed')
            return real(path, *arguments, **options)
        with mock.patch.object(pathlib.Path, 'unlink', unlink):
            result = sim.executor().execute()
        self.assertEqual(result.code, UNVERIFIED, 'the next look finds one still there')
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)

    def test_a_name_an_earlier_failed_sync_left_is_committed_before_it_counts_as_kept(self):
        for boundary in ('run', 'role'):
            with self.subTest(boundary):
                sim = self.sim_of(life.RULES)
                watch = SyscallLoss(sim.stack.root)
                self.corrupt_confirmation(sim, 'seal.json', crash='after_corrupt_bytes', watch=watch, boundary=boundary)
                run_dir = sim.run_dir(sim.records()[-1]['run_id'])
                observation = next(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB))
                document = json.loads(observation.read_text())
                source = run_dir / document['retained_as']
                self.assertFalse(watch.held(source))
                executor = sim.executor(token=document['fencing_token'])
                validation = run_executor.Validation(self.guards(sim)[0])
                with watch.watching():
                    executor._corrupt_receipt(document['run_id'], document['role'], document['path'], source, document['expected_sha256'], validation)
                self.assertTrue(validation.retained)
                self.assertTrue(watch.held(observation) and watch.held(source))

    def test_an_observation_found_there_is_committed_before_the_next_step_begins(self):
        """The next step's own sync would happen to cover it, and a crash between the two is what this is for."""
        sim = self.sim_of(life.RULES)
        watch = SyscallLoss(sim.stack.root)
        self.corrupt_confirmation(sim, 'seal.json', crash='after_corrupt_bytes', watch=watch, boundary='run')
        run_dir = sim.run_dir(sim.records()[-1]['run_id'])
        observation = next(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB))
        document = json.loads(observation.read_text())
        executor = sim.executor(token=document['fencing_token'], failpoint=rf.crash_at('after_corrupt_observation'))
        with watch.watching(), self.assertRaises(rf.SimulatedCrash):
            executor._corrupt_receipt(document['run_id'], document['role'], document['path'], run_dir / document['retained_as'], document['expected_sha256'], run_executor.Validation(self.guards(sim)[0]))
        self.assertTrue(watch.held(observation))

    def test_a_guard_of_no_shape_or_of_another_session_refuses_and_says_so(self):
        for name, text in (('not json', 'x'), ('not an object', '[]'), ('another schema', json.dumps(dict(schema='other'))), ('another session', json.dumps(dict(schema=cs.VALIDATION_GUARD_SCHEMA, session_id='other', manifest_sha256='0', run_id='r', role='bot', fencing_token=1)))):
            with self.subTest(name):
                sim = self.sim_of(life.RULES)
                self.crash(sim, 'after_outcome_commit')
                directory = sim.stack.root / cs.VALIDATION_GUARD_DIR
                directory.mkdir(exist_ok=True)
                path = directory / cs.validation_guard_name(sim.records()[0]['run_id'], 'bot', 1, 0)
                path.write_text(text)
                executor, control = sim.controller(name='controller-later')
                resumed, dispatched = executor.resume('operator', control), executor.execute()
                self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                self.assertEqual(dispatched.code, UNVERIFIED)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                capacity_report.render_search(capacity_report.build(sim.stack.root))
                path.unlink()
                executor, control = sim.controller(name='after-removal')
                self.assertTrue(executor.resume('operator', control).get('resumed'))


if __name__ == '__main__':
    unittest.main()
