"""Whether the names a stop record lives under are on disk before anything depends on them, through the real executor's own directory operations.

A process crash and a power cut are different things here. A process crash leaves every name visible, and is what ``test_stop_record_lifecycle`` tests. A power cut can also take any name whose directory was never fsynced (fsync(2)), and that is modelled by
``NamespaceLoss``, which removes exactly those names. It is a model of what is permitted, not an experiment: no kernel crash, power cut or filesystem fault ran, and the contents of a file nobody fsynced are not modelled at all.
"""
import contextlib
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import capacity_report
import capacity_scorer as cs
import do_session
import run_cli
import run_executor
import run_fixtures as rf
import test_cli
import test_stop_record_lifecycle as life
from search import INFRASTRUCTURE_FAILURE

DURABLE = run_executor.DIRECTORY_NOT_DURABLE
BOUNDARIES = ('session', 'runs', 'run', 'corrupt-evidence', 'role')


class NamespaceLoss:
    """Every directory fsync the code really makes, in order, and the most a power cut may take afterwards: any name under ``runs`` that was not in its directory the last time that directory was synced.

    ``fails`` names directories whose sync raises while ``armed``, and the directory's sync is then not counted.
    """

    def __init__(self, session_dir, fails=()):
        self.session_dir = pathlib.Path(session_dir)
        self.fails = {os.path.realpath(str(path)) for path in fails}
        self.armed = True
        self.calls = []
        self.kept = {}
        self.lost = []
        self.real = do_session._fsync_directory

    @contextlib.contextmanager
    def watching(self):
        with mock.patch.object(do_session, '_fsync_directory', self.sync):
            yield self

    def sync(self, directory):
        key = os.path.realpath(str(directory))
        if self.armed and key in self.fails:
            raise OSError('injected: this directory fsync failed')
        self.real(directory)
        self.calls.append(key)
        self.kept.setdefault(key, set()).update(os.listdir(key))

    def held(self, path):
        """Whether ``path`` and every name above it, up to the session directory, are on disk."""
        path = pathlib.Path(os.path.realpath(str(path)))
        top = pathlib.Path(os.path.realpath(str(self.session_dir)))
        while path != top:
            if path.name not in self.kept.get(str(path.parent), ()):
                return False
            path = path.parent
        return True

    def power_cut(self):
        rf.make_writable(self.session_dir)
        self._prune(self.session_dir / 'runs') if self.held(self.session_dir / 'runs') else self._take(self.session_dir / 'runs')
        return self.lost

    def _prune(self, directory):
        for name in sorted(os.listdir(str(directory))):
            path = directory / name
            if name not in self.kept.get(os.path.realpath(str(directory)), ()):
                self._take(path)
            elif path.is_dir():
                self._prune(path)

    def _take(self, path):
        self.lost.append(str(path.relative_to(self.session_dir)))
        shutil.rmtree(str(path)) if path.is_dir() else path.unlink()


class Confirmation(life.Fixture):
    def boundaries_of(self, sim, run_id, role):
        run_dir = sim.run_dir(run_id)
        return dict(session=sim.stack.root, runs=run_dir.parent, run=run_dir, **{'corrupt-evidence': run_dir / cs.CORRUPT_EVIDENCE_DIR, 'role': run_dir / cs.CORRUPT_EVIDENCE_DIR / role})

    def corrupt_confirmation(self, sim, corrupt, crash=None, watch=None, boundary=None):
        """25 PASS, 50 FAIL, 30 FAIL, then the first of three confirmations meets corrupt bytes of ``corrupt``, and two untouched siblings could still run. Dies at ``crash``. ``boundary`` is the directory whose sync fails while those bytes are being written down."""
        def at(point):
            if point == 'after_outcome_commit' and len(sim.records()) == 3:
                sim.guests.corrupt_export.add(corrupt)
            if point == crash and sim.guests.corrupt_export:
                raise rf.SimulatedCrash()
        executor = sim.executor(failpoint=at)
        if boundary is not None:
            real = executor._corrupt_receipt

            def during(run_id, role, *arguments):
                watch.fails = {os.path.realpath(str(self.boundaries_of(sim, run_id, role)[boundary]))}
                try:
                    return real(run_id, role, *arguments)
                finally:
                    watch.fails = set()
            executor._corrupt_receipt = during
        notes = []
        real_note = executor._note
        executor._note = lambda kind, **data: (notes.append(kind), real_note(kind, **data))
        with contextlib.ExitStack() as stack:
            if watch is not None:
                stack.enter_context(watch.watching())
            if crash is None:
                result = executor.execute()
            else:
                with self.assertRaises(rf.SimulatedCrash):
                    executor.execute()
                result = None
        return result, notes

    def come_back(self, sim):
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-later')
        return executor.resume('operator', control), executor.execute()


class TheActualExecutorsDirectories(Confirmation):
    def test_every_name_above_a_stop_record_is_on_disk_before_the_writer_returns(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(life.RULES)
                watch = NamespaceLoss(sim.stack.root)
                self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=watch)
                row = sim.records()[-1]
                run_dir = sim.run_dir(row['run_id'])
                written = list(run_dir.glob('corrupt-observation-*.json')) + list(run_dir.glob(cs.SEAL_RECEIPT_GLOB)) + [path for path in (run_dir / cs.CORRUPT_EVIDENCE_DIR).rglob('*') if path.is_file()]
                self.assertEqual(len(list(run_dir.glob('corrupt-observation-*.json'))), 1)
                self.assertGreaterEqual(len(written), 3, 'the observation, its bytes, and the receipt that came before them')
                for path in written:
                    self.assertTrue(watch.held(path), path)
                self.assertTrue(watch.held(run_dir / 'grant.json'), 'and the file that says it was dispatched')
                self.assertIn(os.path.realpath(str(run_dir.parent)), watch.calls, 'runs/ itself, which is what a fsync of the run directory does not do')

    def test_the_run_directory_is_on_disk_before_anything_is_dispatched(self):
        sim = self.sim_of(life.RULES)
        watch = NamespaceLoss(sim.stack.root)
        seen = []

        def at(point):
            if point == 'before_dispatch_commit':
                seen.append([watch.held(path) for path in sim.stack.root.glob('runs/*')])
                raise rf.SimulatedCrash()
        with watch.watching(), self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=at).execute()
        self.assertEqual(seen, [[True]], 'the next run\'s directory, before dispatch and before any guest starts')
        self.assertEqual(sim.guests.runner_steps('game', 'start'), [])

    def test_the_grant_goes_through_the_durable_writer(self):
        """Not only a name a later sync happened to cover: the report reads it to tell a dispatched run from a selection, and the fence is read from it."""
        sim = self.sim_of(life.RULES)
        written = []
        real = do_session.write_new_durable_bytes

        def write(path, data):
            written.append(pathlib.Path(path).name)
            return real(path, data)
        with mock.patch.object(do_session, 'write_new_durable_bytes', write):
            self.crash(sim, 'after_outcome_commit')
        self.assertIn('grant.json', written)

    def test_the_order_is_session_runs_run_and_only_then_the_commit_of_what_is_in_it(self):
        sim = self.sim_of(life.RULES)
        watch = NamespaceLoss(sim.stack.root)
        self.corrupt_confirmation(sim, 'bot.stdout.log', crash='after_corrupt_observation', watch=watch)
        run_dir = sim.run_dir(sim.records()[-1]['run_id'])
        session, runs, own = (os.path.realpath(str(path)) for path in (sim.stack.root, run_dir.parent, run_dir))
        self.assertEqual(watch.calls[-3:], [session, runs, own], 'the observation\'s own directories, then its commit')


class APowerCut(Confirmation):
    """Between each step of writing a failure down, for a seal and for a raw file, with two siblings still eligible. Everything the writer said it finished survives, because the model only takes what no fsync covered."""

    def test_no_step_of_a_reported_failure_lets_a_sibling_start(self):
        for corrupt in life.CORRUPT:
            for point, code, terminal in (('after_corrupt_observation', life.UNVERIFIED, None), ('after_corrupt_bytes', life.TERMINAL, INFRASTRUCTURE_FAILURE), ('after_execution_record', life.TERMINAL, INFRASTRUCTURE_FAILURE)):
                with self.subTest(corrupt=corrupt, point=point):
                    sim = self.sim_of(life.RULES)
                    watch = NamespaceLoss(sim.stack.root)
                    self.corrupt_confirmation(sim, corrupt, crash=point, watch=watch)
                    starts = len(sim.guests.runner_steps('game', 'start'))
                    self.assertEqual(starts, 4)
                    lost = watch.power_cut()
                    self.assertTrue(lost, 'the model took what nothing synced, so this is not a test of nothing')
                    self.assertFalse([name for name in lost if 'corrupt-observation' in name or name.endswith(('execution.json', 'grant.json'))], lost)
                    resumed, dispatched = self.come_back(sim)
                    self.assertFalse(resumed['resumed'], resumed)
                    self.assertEqual(resumed['code'], code, resumed)
                    self.assertNotEqual(dispatched.code, 'controller_failure', dispatched)
                    self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts, 'neither sibling starts')
                    self.assertEqual(sim.status_now()['terminal_failure'], terminal)
                    self.assertIn(sim.records()[-1]['run_id'], capacity_report.render_search(capacity_report.build(sim.stack.root)))

    def test_a_process_crash_at_the_same_step_takes_nothing_and_says_the_same(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(life.RULES)
                self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes')
                resumed, _ = self.come_back(sim)
                self.assertEqual(resumed['code'], life.TERMINAL)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)

    def test_the_model_takes_the_run_away_when_nothing_syncs_its_name(self):
        """What the model does to the old behaviour, where a run directory was made with a plain mkdir. Its name is gone, and the refusal below is all that is left, which is why it is there."""
        sim = self.sim_of(life.RULES)
        watch = NamespaceLoss(sim.stack.root)

        def plain(directory, root):
            pathlib.Path(directory).mkdir(parents=True, exist_ok=True)
        with mock.patch.object(do_session, 'make_directory_durable', plain):
            self.corrupt_confirmation(sim, 'bot.stdout.log', crash='after_corrupt_bytes', watch=watch)
        run_dir = sim.run_dir(sim.records()[-1]['run_id'])
        watch.power_cut()
        self.assertFalse(run_dir.exists(), 'the observation was whole, and its name went with its directory')
        resumed, dispatched = self.come_back(sim)
        self.assertEqual(resumed['code'], run_executor.RUN_DIRECTORY_LOST)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'and nothing irreversible is said on what is simply gone')


class ALostRunDirectory(Confirmation):
    def test_a_dispatched_run_with_no_directory_refuses_and_says_nothing_irreversible(self):
        for point, count in (('after_outcome_commit', 1), ('after_dispatch_commit', 0)):
            with self.subTest(point):
                sim = self.sim_of(life.RULES)
                self.crash(sim, point)
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                rf.make_writable(run_dir)
                shutil.rmtree(str(run_dir))
                report = capacity_report.build(sim.stack.root)
                self.assertEqual(report['claim']['kind'], 'evidence_disagreement', 'its selection is on record, and its absence is not read as a selection never dispatched')
                self.assertTrue(report['evidence']['trials_with_unverified_stop_records'])
                self.assertIn('its directory is gone', capacity_report.render_search(report))
                executor, control = sim.controller(name='controller-later')
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], run_executor.RUN_DIRECTORY_LOST, resumed)
                self.assertFalse(run_dir.exists(), 'and it is not quietly made again, which would hide that it went')
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), count)
                self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_the_directory_lost_at_a_confirmation_starts_no_sibling(self):
        """The supplied counterexample, unchanged: the whole run directory removed after the failure was written down. Its name is now durable, so this is no longer what a crash can do, and it refuses all the same."""
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(life.RULES)
                self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes')
                run_dir = sim.run_dir(sim.records()[-1]['run_id'])
                rf.make_writable(run_dir)
                shutil.rmtree(str(run_dir))
                resumed, dispatched = self.come_back(sim)
                self.assertEqual(resumed['code'], run_executor.RUN_DIRECTORY_LOST, resumed)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4, dispatched)


    def test_collecting_carries_on_past_it_to_the_rest_and_to_cleanup(self):
        sim = self.sim_of(life.RULES)
        self.crash(sim, 'after_dispatch_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        rf.make_writable(run_dir)
        shutil.rmtree(str(run_dir))
        executor = self.collect(sim)
        executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture', runs=executor.outcomes))
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'cleanup is not lost')
        self.assertIn('run_directories_lost', self.events(sim))

    def events(self, sim):
        return [line for path in sim.stack.root.glob('execution/*') if path.is_file() for line in path.read_text().splitlines()].__str__()


class FailureAtEachBoundary(Confirmation):
    """The real writer's directory syncs fail while the failure is being written down, at each level from the session directory to the kept bytes."""

    def test_the_controller_that_saw_it_starts_nothing_more(self):
        for corrupt in life.CORRUPT:
            for boundary in BOUNDARIES:
                with self.subTest(corrupt=corrupt, boundary=boundary):
                    sim = self.sim_of(life.RULES)
                    watch = NamespaceLoss(sim.stack.root)
                    result, _ = self.corrupt_confirmation(sim, corrupt, watch=watch, boundary=boundary)
                    self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4, result)
                    self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)

    def test_a_process_crash_right_after_it_replays_what_is_on_disk(self):
        for corrupt in life.CORRUPT:
            for boundary in BOUNDARIES:
                with self.subTest(corrupt=corrupt, boundary=boundary):
                    sim = self.sim_of(life.RULES)
                    watch = NamespaceLoss(sim.stack.root)
                    self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=watch, boundary=boundary)
                    resumed, _ = self.come_back(sim)
                    self.assertEqual(resumed['code'], life.TERMINAL, 'a process crash takes no names, and these are whole')
                    self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 4)

    def test_a_power_cut_right_after_it_forgets_only_what_was_reported_unfinished(self):
        """Above the run directory the names were already durable from before the dispatch, so a sync that fails now costs nothing. Below it, the observation is durable and the bytes are not, which refuses. A failed sync of the run directory itself is the one case
        that leaves nothing: its writer said so at the time, nothing was reported durable, and this is where durability stops being up to this code."""
        for corrupt in life.CORRUPT:
            for boundary, code, starts in (('session', life.TERMINAL, 4), ('runs', life.TERMINAL, 4), ('corrupt-evidence', life.UNVERIFIED, 4), ('role', life.UNVERIFIED, 4), ('run', None, 6)):
                with self.subTest(corrupt=corrupt, boundary=boundary):
                    sim = self.sim_of(life.RULES)
                    watch = NamespaceLoss(sim.stack.root)
                    _, notes = self.corrupt_confirmation(sim, corrupt, crash='after_corrupt_bytes', watch=watch, boundary=boundary)
                    self.assertTrue({'corrupt_observation_not_retained', 'corrupt_bytes_not_retained'} & set(notes), 'the writer reported what it could not finish')
                    if boundary == 'run':
                        self.assertIn('corrupt_observation_not_retained', notes, 'and this is the report that makes the loss below permitted')
                    watch.power_cut()
                    resumed, _ = self.come_back(sim)
                    self.assertEqual(resumed.get('code'), code, resumed)
                    self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts)

    def test_before_a_dispatch_it_stops_the_batch_and_leaves_the_session_recoverable(self):
        for name in ('session', 'runs'):
            with self.subTest(name):
                sim = self.sim_of(life.RULES)
                watch = NamespaceLoss(sim.stack.root, fails=[dict(session=sim.stack.root, runs=sim.stack.root / 'runs')[name]])
                with watch.watching():
                    result = sim.executor().run_batch()
                self.assertEqual(result.code, DURABLE, result)
                self.assertEqual(sim.records(), [], 'nothing was dispatched')
                self.assertEqual(sim.guests.runner_steps('game', 'start'), [])
                self.assertIsNone(sim.status_now()['terminal_failure'], 'this disk\'s trouble says nothing about any host')
                self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'and cleanup is not lost')

    def test_a_directory_left_by_a_failed_sync_is_synced_again_and_never_trusted_for_being_there(self):
        sim = self.sim_of(life.RULES)
        runs = sim.stack.root / 'runs'
        watch = NamespaceLoss(sim.stack.root, fails=[runs])
        with watch.watching():
            result = sim.executor().execute()
        self.assertEqual(result.code, DURABLE)
        self.assertTrue(runs.exists(), 'the mkdir before it worked, so it is there')
        run_dir = next(runs.iterdir())
        self.assertFalse(watch.held(run_dir), 'and its run directory is there too, and is not durable')
        retry = NamespaceLoss(sim.stack.root)
        with retry.watching():
            executor, control = sim.controller(name='controller-later')
            resumed = executor.resume('operator', control)
            self.assertTrue(resumed['resumed'], resumed)
            result = executor.execute()
        self.assertTrue(retry.held(run_dir), 'the retry syncs what it found already there')
        self.assertIn(os.path.realpath(str(sim.stack.root)), retry.calls)
        self.assertTrue(sim.guests.runner_steps('game', 'start'))

    def test_the_operators_collect_still_stops_what_was_left_and_reaches_cleanup_when_nothing_can_be_made_durable(self):
        sim = self.sim_of(life.RULES)
        self.crash(sim, 'after_dispatch_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        watch = NamespaceLoss(sim.stack.root, fails=[sim.stack.root, run_dir.parent])
        fences = len(sim.guests.runner_steps('game', 'fence'))
        with watch.watching():
            result, _ = run_cli.collect_and_stop(sim.client, sim.session_id, lambda token: sim.executor(token=token), 'fixture', takeover=True)
        self.assertEqual(result.code, 'operator_collect')
        self.assertGreater(len(sim.guests.runner_steps('game', 'fence')), fences, 'it still got as far as the hosts, to stop what is there')
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'cleanup is not lost')

    def role_directory_is_refused(self, run_dir_is_role, also_mkdir=False):
        real, real_mkdir = do_session.make_directory_durable, pathlib.Path.mkdir

        def durable(directory, root):
            if run_dir_is_role(pathlib.Path(directory)):
                raise OSError('injected: this role directory cannot be made durable')
            return real(directory, root)

        def mkdir(path, *arguments, **options):
            if also_mkdir and run_dir_is_role(path):
                raise OSError('injected: no directory here')
            return real_mkdir(path, *arguments, **options)
        return mock.patch.object(do_session, 'make_directory_durable', durable), mock.patch.object(pathlib.Path, 'mkdir', mkdir)

    def test_a_role_directory_that_cannot_be_made_durable_does_not_keep_its_bytes_from_being_compared(self):
        sim = self.sim_of(life.RULES)
        sim.guests.corrupt_export.add('bot.stdout.log')
        first, second = self.role_directory_is_refused(lambda path: path.name in ('game', 'bot') and path.parent.parent == sim.stack.root / 'runs')
        with first, second:
            sim.executor().execute()
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE, 'the mismatch was still seen')
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
        self.assertTrue(list(sim.run_dir(sim.records()[0]['run_id']).glob('corrupt-observation-*.json')))

    def test_a_role_directory_that_cannot_be_made_at_all_costs_that_export_and_nothing_else(self):
        sim = self.sim_of(life.RULES)
        first, second = self.role_directory_is_refused(lambda path: path.name in ('game', 'bot') and path.parent.parent == sim.stack.root / 'runs', also_mkdir=True)
        with first, second:
            result = sim.executor().run_batch()
        self.assertNotEqual(result.code, 'controller_failure', result)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1, 'nothing runs past it')
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_resume_refuses_while_the_session_directory_cannot_be_made_durable(self):
        sim = self.sim_of(life.RULES)
        self.crash(sim, 'after_outcome_commit')
        watch = NamespaceLoss(sim.stack.root, fails=[sim.stack.root])
        with watch.watching():
            executor, control = sim.controller(name='controller-later')
            resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], DURABLE, resumed)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)


class TheDurableRoot(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(os.path.realpath(self.temporary.name))

    def test_each_level_is_synced_in_order_from_the_root_every_time(self):
        watch = NamespaceLoss(self.root)
        target = self.root / 'a' / 'b' / 'c'
        with watch.watching():
            do_session.make_directory_durable(target, self.root)
            first = list(watch.calls)
            do_session.make_directory_durable(target, self.root)
        expected = [str(self.root), str(self.root / 'a'), str(self.root / 'a' / 'b')]
        self.assertEqual(first, expected, 'a parent is synced after the name goes in it, and a child\'s sync would say nothing of its own name')
        self.assertEqual(watch.calls, expected + expected, 'and again for a tree already there')

    def test_a_failure_at_one_level_promises_nothing_below_it_and_a_retry_finishes_the_job(self):
        target = self.root / 'a' / 'b'
        watch = NamespaceLoss(self.root, fails=[self.root / 'a'])
        with watch.watching(), self.assertRaises(OSError):
            do_session.make_directory_durable(target, self.root)
        self.assertTrue(target.exists(), 'the name is there')
        self.assertFalse(watch.held(target), 'and it was not promised')
        retry = NamespaceLoss(self.root)
        with retry.watching():
            do_session.make_directory_durable(target, self.root)
        self.assertTrue(retry.held(target))

    def test_a_path_outside_the_root_is_a_defect_and_not_a_durable_write(self):
        with self.assertRaises(ValueError):
            do_session.make_directory_durable(self.root.parent, self.root)

    def test_a_file_where_a_directory_should_be_fails(self):
        (self.root / 'a').write_text('x')
        with self.assertRaises(OSError):
            do_session.make_directory_durable(self.root / 'a' / 'b', self.root)

    def test_the_top_of_the_filesystem_is_one_path_on_one_device(self):
        top = do_session._top_of_filesystem(self.root)
        device = self.root.stat().st_dev
        self.assertIn(top, [self.root] + list(self.root.parents))
        self.assertEqual(top.stat().st_dev, device)
        self.assertTrue(top == top.parent or top.parent.stat().st_dev != device or not os.access(str(top.parent), os.R_OK), 'it goes as far up as it can and no further')

    def test_a_level_above_that_this_account_cannot_open_ends_the_climb(self):
        real = os.access

        def access(path, mode, **kwargs):
            return str(path) != str(self.root.parent) and real(path, mode, **kwargs)
        with mock.patch.object(os, 'access', access):
            self.assertEqual(do_session._top_of_filesystem(self.root / 'a' / 'b'), self.root)

    def test_a_session_directory_is_durable_all_the_way_up_and_stops_at_the_filesystem(self):
        session = self.root / 'sessions' / 'one'
        watch = NamespaceLoss(self.root)
        with watch.watching():
            do_session.make_session_durable(session)
        self.assertTrue(watch.held(session))
        self.assertEqual(watch.calls[-1], str(session), 'and what is directly in it')
        top = do_session._top_of_filesystem(session)
        self.assertEqual(watch.calls[0], str(top), 'from the top of this one filesystem')
        self.assertFalse([path for path in watch.calls if not str(session).startswith(path)], 'only this one path')

    def test_the_writer_alone_still_answers_for_what_it_made(self):
        watch = NamespaceLoss(self.root)
        target = self.root / 'made' / 'for' / 'file'
        with watch.watching():
            do_session.write_new_durable_bytes(target, b'whole')
        self.assertTrue(watch.held(target))


class Freeze(test_cli.CliFixture):
    def test_a_frozen_session_is_on_disk_up_to_its_root_and_its_manifest_with_it(self):
        top = pathlib.Path(os.path.realpath(str(self.root)))
        watch = NamespaceLoss(top)
        with watch.watching():
            self.freeze()
        for name in ('manifest.json', 'manifest.sha256'):
            self.assertTrue(watch.held(pathlib.Path(os.path.realpath(str(self.session_dir))) / name), name)

    def test_an_interrupted_freeze_that_left_its_directories_is_finished_by_the_next(self):
        watch = NamespaceLoss(self.root, fails=[self.session_root])
        with watch.watching():
            code, out, _ = self.run_cli('freeze', '--conditions', str(self.conditions), '--preflight', str(self.preflight), '--session-root', str(self.session_root), '--now', test_cli.NOW)
        self.assertNotEqual(code, 0, out)
        self.assertTrue(self.session_root.exists())
        self.assertEqual(list(self.session_root.rglob('manifest.json')), [], 'and it claimed nothing')
        retry = NamespaceLoss(self.root)
        with retry.watching():
            self.freeze()
        self.assertTrue(retry.held(pathlib.Path(os.path.realpath(str(self.session_dir))) / 'manifest.json'), 'the retry does not trust the levels it found')
        self.assertIn(os.path.realpath(str(self.root)), retry.calls)


if __name__ == '__main__':
    unittest.main()
