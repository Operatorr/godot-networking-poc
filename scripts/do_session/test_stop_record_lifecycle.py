"""What corrupt bytes leave behind at every step of being written down, and what any file in a run directory can do to the reader that has to judge it.

Everything here goes through the real executor, registry, prover, scorer and report over a fake guest, with crashes that nothing catches and failures of the real durable writer's own system calls. Nothing ran on a host, so none of it says anything about one.
A real power cut is not among these. What is tested is that each step finishes, by the writer's own definition, before the next one starts.
"""
import contextlib
import hashlib
import json
import os
import pathlib
import stat
import tempfile
import unittest
from unittest import mock

import capacity_report
import capacity_scorer as cs
import do_session
import registry_client
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import test_capacity_integrity as integrity
from search import INFRASTRUCTURE_FAILURE, PASS

CORRUPT = ('seal.json', 'bot.stdout.log')
RULES = {50: sf.slow, 30: sf.slow}
TERMINAL = 'terminal_failure'
UNVERIFIED = run_executor.STOP_RECORD_UNVERIFIED
UNACKNOWLEDGED = run_executor.TERMINAL_FACT_UNACKNOWLEDGED
BAD_BYTES = b'not what the seal says\n'
BAD_DIGEST = hashlib.sha256(BAD_BYTES).hexdigest()


def is_observation(path):
    return path.name.startswith('corrupt-observation-')


def is_kept_bytes(path):
    return cs.CORRUPT_EVIDENCE_DIR in path.parts


def is_fact(path):
    return path.name.startswith('terminal-fact-')



@contextlib.contextmanager
def fails_at(stage):
    """One system call of the real durable writer fails, as a full or dying disk would make it."""
    real_fsync, real_link = os.fsync, os.link
    linked = []

    def fsync(handle):
        directory = stat.S_ISDIR(os.fstat(handle).st_mode)
        if (stage == 'file_fsync' and not directory) or (stage == 'directory_fsync' and directory and linked):
            raise OSError('injected: fsync failed')
        return real_fsync(handle)

    def link(source, target):
        if stage == 'link':
            raise OSError('injected: link failed')
        real_link(source, target)
        linked.append(target)

    def unlink(self, *_):
        raise OSError('injected: unlink failed')

    def refuse_open(self, *_, **__):
        raise OSError('injected: no space left')

    patches = [mock.patch.object(os, 'fsync', fsync), mock.patch.object(os, 'link', link)]
    if stage == 'unlink':
        patches.append(mock.patch.object(pathlib.Path, 'unlink', unlink))
    if stage == 'open':
        patches.append(mock.patch.object(pathlib.Path, 'open', refuse_open))
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


@contextlib.contextmanager
def writes_fail(stage, *wanted):
    """Only writes whose target matches one of ``wanted`` meet the failure, so a run's other files stay as they would be."""
    real = do_session.write_new_durable_bytes

    def write(path, data):
        if not any(item(pathlib.Path(path)) for item in wanted):
            return real(path, data)
        with fails_at(stage):
            return real(path, data)
    with mock.patch.object(do_session, 'write_new_durable_bytes', write):
        yield


def sealed_digest(run_dir, relative='bot.stdout.log', role='bot'):
    seal = json.loads((run_dir / role / 'seal.json').read_text())
    return next(item['sha256'] for item in seal['files'] if item['path'] == relative)


def observation_file(sim, own_run, token=2, relative='bot.stdout.log', keep_bytes=True, name=None, **changes):
    """The file the executor writes, with one thing changed, and the bytes it names unless told otherwise."""
    run_dir = sim.run_dir(own_run)
    document = cs.corrupt_observation(sim.session_id, sim.sha, own_run, 'bot', relative, sealed_digest(run_dir, relative), BAD_DIGEST, token, '2026-10-30T00:00:00Z')
    if keep_bytes:
        target = run_dir / document['retained_as']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(BAD_BYTES)
    path = run_dir / (name or cs.corrupt_observation_name(token, 'bot', relative, BAD_DIGEST))
    document.update(changes)
    path.write_text(json.dumps(document))
    return path


def remove_kept_bytes(run_dir):
    for path in sorted((run_dir / cs.CORRUPT_EVIDENCE_DIR).rglob('*'), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    with contextlib.suppress(OSError):
        (run_dir / cs.CORRUPT_EVIDENCE_DIR).rmdir()


class Fixture(integrity.Base):
    def returning(self, corrupt):
        """A committed PASS, a controller gone, one required raw file lost. The next transfer brings corrupt bytes of ``corrupt``."""
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        history = {name: (run_dir / name).read_bytes() for name in ('score.json', 'classification.json')}
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        sim.guests.corrupt_export.add(corrupt)
        return sim, run_dir, history

    def later_controller(self, sim):
        """Transport and registry back to health, a new controller, and both things it could try: a resume and an actual dispatch."""
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-later')
        return executor, executor.resume('operator', control), executor.execute()

    def assertNoSuccessor(self, sim, starts=1):
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts, 'no second workload')
        self.assertEqual(sim.outcomes()[1:], [], 'and nothing dispatched')

    def assertHistoryKept(self, run_dir, history):
        for name, data in history.items():
            self.assertEqual((run_dir / name).read_bytes(), data, name + ' stays as it was')

    def assertRefusedTerminal(self, sim, resumed, dispatched):
        self.assertFalse(resumed['resumed'], resumed)
        self.assertEqual(resumed['code'], TERMINAL, resumed)
        self.assertEqual(dispatched.code, TERMINAL)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertFalse(report['evidence']['verified'])
        self.assertTrue(report['evidence']['trials_with_stop_facts'], 'and the report names the fact')

    def assertRefusedUnverified(self, sim, resumed, dispatched):
        self.assertFalse(resumed['resumed'], resumed)
        self.assertEqual(resumed['code'], UNVERIFIED, resumed)
        self.assertEqual(dispatched.code, UNVERIFIED)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'no irreversible word on what cannot be held to this run')
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertFalse(report['evidence']['verified'])
        self.assertTrue(report['evidence']['trials_with_unverified_stop_records'])
        self.assertIn('Unverified stop record', capacity_report.render_search(report))

    def assertRefused(self, code, sim, resumed, dispatched):
        (self.assertRefusedTerminal if code == TERMINAL else self.assertRefusedUnverified)(sim, resumed, dispatched)


class CrashesAlongTheLifecycle(Fixture):
    """Interrupted between each two steps, for a seal and for a raw file. A later working transfer must not be able to erase any of it."""

    def crash_returning(self, sim, point):
        executor, control = sim.controller(failpoint=rf.crash_at(point))
        with self.assertRaises(rf.SimulatedCrash):
            executor.resume('operator', control)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'nothing reached the registry yet')

    def test_after_the_observation_and_before_the_bytes_it_refuses_as_unverified(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = self.returning(corrupt)
                self.crash_returning(sim, 'after_corrupt_observation')
                self.assertEqual(len(list(run_dir.glob('corrupt-observation-*.json'))), 1)
                self.assertFalse((run_dir / cs.CORRUPT_EVIDENCE_DIR).exists())
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedUnverified(sim, resumed, dispatched)
                self.assertIn('are not here', resumed['detail'])
                self.assertNoSuccessor(sim)
                self.assertHistoryKept(run_dir, history)

    def test_after_the_bytes_and_before_the_fact_it_replays_as_a_fact(self):
        """This is the crash that used to let five successors run. Both hashes are on disk now, so the stop can still be told."""
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = self.returning(corrupt)
                self.crash_returning(sim, 'after_corrupt_bytes')
                self.assertEqual(list(run_dir.glob('terminal-fact-*')), [])
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminal(sim, resumed, dispatched)
                self.assertNoSuccessor(sim)
                self.assertHistoryKept(run_dir, history)
                report = capacity_report.build(sim.stack.root)
                fact = report['trials'][0]['hard_facts'][0]
                self.assertEqual((fact['outcome'], fact['role']), (INFRASTRUCTURE_FAILURE, 'bot'))
                receipt = fact['receipts'][0]
                self.assertEqual(receipt['path'], corrupt)
                self.assertNotEqual(receipt['expected_sha256'], receipt['actual_sha256'])
                self.assertEqual(run_executor.sha256_path(run_dir / receipt['retained_as']), receipt['actual_sha256'])
                self.assertEqual(report['trials'][0]['unverified_stop_records'], [])

    def test_after_the_fact_and_before_the_registry_it_is_one_stop_and_not_two(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = self.returning(corrupt)
                self.crash_returning(sim, 'after_terminal_fact')
                self.assertEqual(len(list(run_dir.glob('terminal-fact-*.json'))), 1)
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminal(sim, resumed, dispatched)
                self.assertNoSuccessor(sim)
                self.assertHistoryKept(run_dir, history)
                row = capacity_report.build(sim.stack.root)['trials'][0]
                self.assertEqual([item['record'][:13] for item in row['hard_facts']], ['terminal-fact'], 'the observation it covers does not count again')
                self.assertEqual(row['unverified_stop_records'], [])

    def test_a_registry_down_at_the_replay_still_refuses_and_a_later_one_hears(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, _ = self.returning(corrupt)
                self.crash_returning(sim, 'after_corrupt_bytes')
                sim.guests.corrupt_export.clear()
                executor, control = sim.controller(name='controller-c')
                integrity.UnacknowledgedStops.stop_fails(executor, registry_client.RegistryUnavailable('down'))
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], UNACKNOWLEDGED, resumed)
                self.assertEqual(executor.execute().code, UNACKNOWLEDGED)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminal(sim, resumed, dispatched)
                self.assertNoSuccessor(sim)

    def test_a_crash_with_nothing_yet_written_leaves_nothing_to_replay(self):
        """The limit of all this, stated: only memory knew, for as long as it took to write the first file. A later controller over good bytes has no way to know."""
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, _ = self.returning(corrupt)
                executor, control = sim.controller()
                with mock.patch.object(cs, 'corrupt_observation', side_effect=rf.SimulatedCrash('before anything was written')), self.assertRaises(rf.SimulatedCrash):
                    executor.resume('operator', control)
                self.assertEqual(list(run_dir.glob('corrupt-observation-*')), [])
                sim.guests.corrupt_export.clear()
                executor, control = sim.controller(name='controller-later')
                self.assertTrue(executor.resume('operator', control)['resumed'])


class AnUncommittedRun(Fixture):
    """The same bytes failing before any outcome is committed. A healthy transfer later must not let the run be scored as if they never had."""

    def corrupted_in_flight(self, corrupt, point):
        sim = self.sim_of(RULES)
        sim.guests.corrupt_export.add(corrupt)
        self.crash(sim, point)
        self.assertIsNone(sim.records()[0]['outcome'], 'the first controller died before any outcome')
        return sim

    def test_a_report_read_before_anyone_comes_back_does_not_vouch_for_the_run(self):
        for corrupt in CORRUPT:
            for point, record in (('after_corrupt_observation', 'unverified_stop_records'), ('after_corrupt_bytes', 'hard_facts')):
                with self.subTest(corrupt=corrupt, point=point):
                    sim = self.corrupted_in_flight(corrupt, point)
                    report = capacity_report.build(sim.stack.root)
                    self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
                    self.assertFalse(report['evidence']['verified'])
                    self.assertTrue(report['trials'][0][record], report['trials'][0])

    def test_observed_with_its_bytes_it_takes_the_failure_as_its_outcome(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim = self.corrupted_in_flight(corrupt, 'after_corrupt_bytes')
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminalOutcome(sim, resumed, dispatched)

    def assertRefusedTerminalOutcome(self, sim, resumed, dispatched):
        self.assertFalse(resumed['resumed'], resumed)
        self.assertEqual(resumed['code'], TERMINAL, resumed)
        self.assertEqual(dispatched.search_status, 'stopped_infrastructure_failure', 'the search itself has nothing left to run')
        self.assertEqual(sim.outcomes(), [('coarse', 25, INFRASTRUCTURE_FAILURE)])
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertNoSuccessor(sim)

    def test_observed_without_its_bytes_nothing_follows_it(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim = self.corrupted_in_flight(corrupt, 'after_corrupt_observation')
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedUnverified(sim, resumed, dispatched)
                self.assertNoSuccessor(sim)


class FailuresInsideTheWriter(Fixture):
    """Every system call of the durable writer, for each of the three things it writes, for a seal and for a raw file, with a registry that does not answer either. This controller refuses from memory. The next one must not need that memory."""
    OPEN, FILE_FSYNC, LINK, UNLINK, DIRECTORY_FSYNC = STAGES = ('open', 'file_fsync', 'link', 'unlink', 'directory_fsync')
    WRITERS = (('observation', is_observation), ('kept bytes', is_kept_bytes), ('fact', is_fact))
    PUBLISHED = (UNLINK, DIRECTORY_FSYNC)     # the final name exists by then

    def first_controller_refuses(self, sim, stage, wanted):
        executor, control = sim.controller()
        integrity.UnacknowledgedStops.stop_fails(executor, registry_client.RegistryUnavailable('down'))
        with writes_fail(stage, wanted):
            first = executor.resume('operator', control)
        self.assertEqual(first['code'], UNACKNOWLEDGED, first)
        self.assertEqual(executor.execute().code, UNACKNOWLEDGED, 'kept in this controller\'s memory')
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_any_failure_with_the_rest_of_the_lifecycle_intact_replays_as_a_stop(self):
        for corrupt in CORRUPT:
            for label, wanted in self.WRITERS:
                for stage in self.STAGES:
                    with self.subTest(corrupt=corrupt, writer=label, stage=stage):
                        sim, run_dir, history = self.returning(corrupt)
                        self.first_controller_refuses(sim, stage, wanted)
                        _, resumed, dispatched = self.later_controller(sim)
                        self.assertRefusedTerminal(sim, resumed, dispatched)
                        self.assertNoSuccessor(sim)
                        self.assertHistoryKept(run_dir, history)

    def test_the_observation_or_the_bytes_failing_and_a_crash_before_any_fact_leaves_no_clean_path(self):
        """Here the fact never gets written. What is left is the observation short of its bytes, or bytes no observation accounts for, and each refuses."""
        for corrupt in CORRUPT:
            for label, wanted in self.WRITERS[:2]:
                for stage in self.STAGES:
                    with self.subTest(corrupt=corrupt, writer=label, stage=stage):
                        sim, run_dir, history = self.returning(corrupt)
                        executor, control = sim.controller(failpoint=rf.crash_at('after_corrupt_bytes'))
                        with writes_fail(stage, wanted), self.assertRaises(rf.SimulatedCrash):
                            executor.resume('operator', control)
                        _, resumed, dispatched = self.later_controller(sim)
                        self.assertRefused(TERMINAL if stage in self.PUBLISHED else UNVERIFIED, sim, resumed, dispatched)
                        self.assertNoSuccessor(sim)
                        self.assertHistoryKept(run_dir, history)

    def test_every_write_failing_at_its_fsync_leaves_interrupted_writes_that_refuse(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, _ = self.returning(corrupt)
                self.first_controller_refuses(sim, self.FILE_FSYNC, lambda path: is_observation(path) or is_kept_bytes(path) or is_fact(path))
                self.assertEqual(list(run_dir.glob('corrupt-observation-*.json')) + list(run_dir.glob('terminal-fact-*.json')), [])
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedUnverified(sim, resumed, dispatched)
                self.assertIn('interrupted write', resumed['detail'])
                self.assertNoSuccessor(sim)

    def test_a_disk_that_refused_every_file_is_only_as_good_as_memory_and_the_registry(self):
        """The other limit. No file reached the disk at all, so this controller's refusal and the registry's answer are all there ever was."""
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, _ = self.returning(corrupt)
                self.first_controller_refuses(sim, self.OPEN, lambda path: is_observation(path) or is_kept_bytes(path) or is_fact(path))
                self.assertEqual([path.name for path in run_dir.glob('*') if is_observation(path) or is_fact(path)], [])
                self.assertFalse(any(path.is_file() for path in (run_dir / cs.CORRUPT_EVIDENCE_DIR).rglob('*')))
                sim.guests.corrupt_export.clear()
                executor, control = sim.controller(name='controller-later')
                self.assertTrue(executor.resume('operator', control)['resumed'], 'nothing durable says otherwise')

    def test_cleanup_goes_ahead_whatever_the_writer_and_the_registry_do(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(RULES)
                executor = sim.executor()
                result = executor.execute()
                self.assertEqual(result.search_status, 'confirmed')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                path = run_dir / 'bot' / 'bot.stdout.log'
                path.chmod(0o644)
                path.unlink()
                sim.guests.corrupt_export.add(corrupt)
                integrity.UnacknowledgedStops.stop_fails(executor, registry_client.RegistryUnavailable('down'))
                with writes_fail(self.FILE_FSYNC, lambda item: is_observation(item) or is_kept_bytes(item) or is_fact(item)):
                    executor.wrap_up(result)
                self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertTrue(any('has not acknowledged the stop fact' in item for item in result.wrap_up_errors), result.wrap_up_errors)
                self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'evidence_disagreement')


class TheOrderOfTheSteps(Fixture):
    def test_each_step_has_finished_before_the_next_begins(self):
        for corrupt in CORRUPT:
            with self.subTest(corrupt):
                sim, _, _ = self.returning(corrupt)
                events = []
                real = do_session.write_new_durable_bytes

                def write(path, data):
                    path = pathlib.Path(path)
                    kind = 'observation' if is_observation(path) else 'bytes' if is_kept_bytes(path) else 'fact' if is_fact(path) else None
                    if kind:
                        events.append(kind + ' begins')
                    real(path, data)
                    if kind:
                        events.append(kind + ' done')
                executor, control = sim.controller()
                real_mutate = executor.client.mutate

                def mutate(method, *arguments, **parameters):
                    if method == 'record_batch_stop':
                        events.append('registry')
                    return real_mutate(method, *arguments, **parameters)
                executor.client.mutate = mutate
                with mock.patch.object(do_session, 'write_new_durable_bytes', write):
                    executor.resume('operator', control)
                self.assertEqual(events[:7], ['observation begins', 'observation done', 'bytes begins', 'bytes done', 'fact begins', 'fact done', 'registry'])

    def test_the_writer_commits_with_the_directory_fsync_and_the_directories_it_made_come_first(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            target = root / 'made' / 'for' / 'this' / 'file'
            events = []
            real_fsync, real_link = os.fsync, os.link

            def fsync(handle):
                kind = stat.S_IFMT(os.fstat(handle).st_mode)
                events.append('directory' if kind == stat.S_IFDIR else 'file')
                return real_fsync(handle)

            def link(source, destination):
                events.append('link')
                return real_link(source, destination)
            with mock.patch.object(os, 'fsync', fsync), mock.patch.object(os, 'link', link):
                do_session.write_new_durable_bytes(target, b'whole')
            self.assertEqual(events, ['directory', 'directory', 'directory', 'file', 'link', 'directory'], 'three new directories, the bytes, the name, and the name is committed')
            self.assertEqual(target.read_bytes(), b'whole')
            self.assertEqual([path.name for path in target.parent.iterdir()], ['file'], 'nothing else left behind')

    def test_the_writer_keeps_what_it_could_not_finish_and_never_names_it(self):
        with tempfile.TemporaryDirectory() as root:
            target = pathlib.Path(root) / 'record.json'
            with fails_at('file_fsync'), self.assertRaises(OSError):
                do_session.write_new_durable_bytes(target, b'half')
            self.assertFalse(target.exists())
            self.assertEqual(len(list(pathlib.Path(root).glob('record.json' + do_session.WRITING + '*'))), 1)


class ContactOnlyStaysRecoverable(Fixture):
    """None of this may turn a failure of contact into a demonstrated failure. A valid retained decision outlives an unreachable host."""

    def test_a_transfer_that_cannot_run_writes_nothing_and_stops_nothing(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        sim.guests.copy_failures.add(('bot', 'get'))
        executor, control = sim.controller()
        resumed = executor.resume('operator', control)
        self.assertNotEqual(resumed.get('code'), UNVERIFIED, resumed)
        self.assertNotEqual(resumed.get('code'), TERMINAL, resumed)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(list(run_dir.glob('corrupt-observation-*')), [])
        self.assertFalse((run_dir / cs.CORRUPT_EVIDENCE_DIR).exists())

    def test_a_partial_transfer_a_crash_cut_short_is_no_observation(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        path.with_name(path.name + '.partial').write_bytes(b'cut sho')
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'], 'nobody compared a hash, and what a cut transfer leaves proves nothing')
        self.assertEqual(run_executor.sha256_path(path), sealed_digest(run_dir))

    def test_an_interrupted_write_of_anything_else_is_not_a_stop_record(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        (run_dir / ('window-proof.json' + do_session.WRITING + '1-0')).write_text('{"half')
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'])


class WholeWritesAreNotInterruptedWrites(Fixture):
    def facts_of(self, sim, run_id):
        return cs.stop_records(sim.run_dir(run_id), dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id))

    def committed(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        return sim, sim.records()[0]['run_id']

    def test_a_crash_between_the_link_and_the_unlink_leaves_a_true_copy_that_refuses_nothing(self):
        sim, run_id = self.committed()
        path = observation_file(sim, run_id)
        (path.parent / (path.name + do_session.WRITING + '9-0')).write_bytes(path.read_bytes())
        bytes_name = json.loads(path.read_text())['retained_as']
        (path.parent / (bytes_name + do_session.WRITING + '9-0')).write_bytes(BAD_BYTES)
        facts, unverified = self.facts_of(sim, run_id)
        self.assertEqual(len(facts), 1)
        self.assertEqual(unverified, [])

    def test_an_interrupted_write_that_differs_from_its_final_name_still_refuses(self):
        sim, run_id = self.committed()
        path = observation_file(sim, run_id)
        (path.parent / (path.name + do_session.WRITING + '9-0')).write_text('{"half')
        facts, unverified = self.facts_of(sim, run_id)
        self.assertEqual(len(facts), 1, 'the whole record still counts')
        self.assertEqual([item['record'] for item in unverified], [path.name + do_session.WRITING + '9-0'])

    def test_bytes_a_genuine_earlier_fact_or_execution_record_names_need_no_observation(self):
        sim, run_id = self.committed()
        run_dir = sim.run_dir(run_id)
        name = cs.corrupt_evidence_name('bot', 'bot.stdout.log', BAD_DIGEST)
        (run_dir / name).parent.mkdir(parents=True)
        (run_dir / name).write_bytes(BAD_BYTES)
        receipt = dict(path='bot.stdout.log', kind='corrupt', reason='hash mismatch', expected_sha256='a' * 64, actual_sha256=BAD_DIGEST, retained_as=name)
        fact = integrity._terminal_fact_file(sim, run_id, 2, receipts=[receipt])
        facts, unverified = self.facts_of(sim, run_id)
        self.assertEqual(([item['record'] for item in facts], unverified), ([fact.name], []))
        fact.unlink()
        record = json.loads((run_dir / 'execution.json').read_text())
        record.update(writer='reconcile', exported=dict(bot=dict(complete=False, failed=[receipt])))
        (run_dir / 'execution-reconciled-0002-1.json').write_text(json.dumps(record))
        self.assertEqual(self.facts_of(sim, run_id)[1], [], 'an own execution record accounts for them')


class ObservationsAreHeldToThisRun(Fixture):
    """Finding a file by its name proves nothing. Each of these keeps a resume from standing, and none of them says anything to the registry."""

    def table(self, run_id):
        bad = 'e' * 64
        return (('another_session', dict(session_id='foreign-session')),
                ('another_manifest', dict(manifest_sha256='f' * 64)),
                ('another_run', dict(run_id='foreign-run')),
                ('no_session', dict(session_id=None)),
                ('another_role', dict(role='watchdog')),
                ('a_role_of_no_shape', dict(role=['bot'])),
                ('a_path_outside', dict(path='../../manifest.json')),
                ('an_absolute_path', dict(path='/etc/passwd')),
                ('a_path_of_no_shape', dict(path=[])),
                ('equal_hashes', dict(expected_sha256=BAD_DIGEST)),
                ('a_hash_of_no_shape', dict(actual_sha256={})),
                ('an_expected_hash_of_no_shape', dict(expected_sha256=5)),
                ('an_expected_hash_the_seal_does_not_say', dict(expected_sha256=bad)),
                ('no_time', dict(found_at=None)),
                ('a_token_of_true', dict(fencing_token=True)),
                ('a_token_of_no_shape', dict(fencing_token='two')),
                ('a_token_newer_than_the_session', dict(fencing_token=99)),
                ('a_token_of_zero', dict(fencing_token=0)),
                ('another_schema', dict(schema='omega.other/1')),
                ('bytes_named_elsewhere', dict(retained_as='../../manifest.json')),
                ('bytes_named_of_no_shape', dict(retained_as=[])))

    def test_each_wrong_observation_refuses_as_unverified_and_removing_it_restores_the_session(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_id = sim.records()[0]['run_id']
        run_dir = sim.run_dir(run_id)
        for name, change in self.table(run_id):
            with self.subTest(name):
                path = observation_file(sim, run_id, **change)
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                row = capacity_report.build(sim.stack.root)['trials'][0]
                self.assertEqual(row['hard_facts'], [])
                self.assertIn(path.name, [item['record'] for item in row['unverified_stop_records']])
                path.unlink()
                remove_kept_bytes(run_dir)
        self.assertNoSuccessor(sim)
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'])
        executor.execute()
        self.assertGreater(len(sim.guests.runner_steps('game', 'start')), 1, 'nothing about them stayed')

    def test_a_copied_name_a_changed_byte_and_a_stray_file_are_not_facts(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_id = sim.records()[0]['run_id']
        run_dir = sim.run_dir(run_id)
        cases = {}
        cases['a_copy_under_another_name'] = observation_file(sim, run_id, name='corrupt-observation-0002-0000000000000000.json')
        cases['a_name_another_token_should_carry'] = observation_file(sim, run_id, name=cs.corrupt_observation_name(3, 'bot', 'bot.stdout.log', BAD_DIGEST))
        for name, path in cases.items():
            for other in cases.values():
                if other != path:
                    other.rename(other.with_name(other.name + '.aside'))
            with self.subTest(name):
                executor, control = sim.controller()
                self.assertEqual(executor.resume('operator', control)['code'], UNVERIFIED)
            for other in cases.values():
                if other != path:
                    other.with_name(other.name + '.aside').rename(other)
        for path in cases.values():
            path.unlink()
        path = observation_file(sim, run_id)
        kept = run_dir / json.loads(path.read_text())['retained_as']
        kept.write_bytes(BAD_BYTES + b'changed')
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], UNVERIFIED, 'bytes that are not the ones it hashed')
        self.assertIsNone(sim.status_now()['terminal_failure'])
        path.unlink()
        kept.unlink()
        (run_dir / cs.CORRUPT_EVIDENCE_DIR / 'bot' / 'seal.json.deadbeef').write_bytes(b'a name is not evidence')
        executor, control = sim.controller()
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], UNVERIFIED, resumed)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        row = capacity_report.build(sim.stack.root)['trials'][0]
        self.assertEqual(row['hard_facts'], [], 'bytes nothing accounts for make nobody\'s fact')
        remove_kept_bytes(run_dir)
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'])

    def test_a_genuine_observation_beside_a_foreign_one_still_stops_the_session(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_id = sim.records()[0]['run_id']
        observation_file(sim, run_id)
        foreign = observation_file(sim, run_id, name='corrupt-observation-0002-aaaaaaaaaaaaaaaa.json', session_id='foreign-session')
        executor, control = sim.controller()
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], TERMINAL, resumed)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        row = capacity_report.build(sim.stack.root)['trials'][0]
        self.assertEqual(len(row['hard_facts']), 1)
        self.assertEqual([item['record'] for item in row['unverified_stop_records']], [foreign.name])


class EveryPathReadsTheSameLifecycle(Fixture):
    """The dispatch gate, the collect path and the wrap-up, each meeting what a crash left without a resume ever having asked."""

    def between_runs(self, leave):
        """Nothing resumed: the same controller finishes a run and, about to dispatch the next, finds this."""
        sim = self.sim_of(RULES)

        def failpoint(point):
            if point == 'after_outcome_commit' and not failpoint.done:
                failpoint.done = True
                row = sim.records()[0]
                leave(sim, row['run_id'], row['fencing_token'])
        failpoint.done = False
        executor = sim.executor(failpoint=failpoint)
        return sim, executor, executor.execute()

    def test_a_running_dispatch_stops_short_at_each_pending_state(self):
        def no_bytes(sim, run_id, token):
            observation_file(sim, run_id, token, keep_bytes=False)

        def orphan_bytes(sim, run_id, token):
            target = sim.run_dir(run_id) / cs.corrupt_evidence_name('bot', 'bot.stdout.log', BAD_DIGEST)
            target.parent.mkdir(parents=True)
            target.write_bytes(BAD_BYTES)

        def half_observation(sim, run_id, token):
            (sim.run_dir(run_id) / ('corrupt-observation-0001-aaaaaaaaaaaaaaaa.json' + do_session.WRITING + '1-0')).write_text('{"half')

        def half_fact(sim, run_id, token):
            (sim.run_dir(run_id) / ('terminal-fact-0001-0.json' + do_session.WRITING + '1-0')).write_text('{"half')

        for leave in (no_bytes, orphan_bytes, half_observation, half_fact):
            with self.subTest(leave.__name__):
                sim, _, result = self.between_runs(leave)
                self.assertEqual(result.code, UNVERIFIED, result)
                self.assertEqual(result.status, run_executor.STOPPED)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)])
                self.assertNoSuccessor(sim)

    def test_a_running_dispatch_tells_the_registry_of_a_whole_observation(self):
        def whole(sim, run_id, token):
            observation_file(sim, run_id, token)
        sim, _, result = self.between_runs(whole)
        self.assertEqual(result.code, TERMINAL, result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertNoSuccessor(sim)

    def test_a_wrap_up_with_no_dispatch_before_it_still_tells_the_registry_and_still_asks_for_cleanup(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_id = sim.records()[0]['run_id']
        observation_file(sim, run_id)
        executor, _ = sim.controller()
        executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture'))
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_a_wrap_up_loses_nothing_to_a_pending_record_or_a_registry_that_does_not_answer(self):
        for down in (False, True):
            with self.subTest(down=down):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_outcome_commit')
                run_id = sim.records()[0]['run_id']
                observation_file(sim, run_id, keep_bytes=False)
                executor, _ = sim.controller()
                if down:
                    integrity.UnacknowledgedStops.stop_fails(executor, registry_client.RegistryUnavailable('down'))
                result = run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture')
                executor.wrap_up(result)
                self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
                self.assertIsNone(sim.status_now()['terminal_failure'], 'an observation short of its bytes is nobody\'s fact')
                report = capacity_report.build(sim.stack.root)
                self.assertEqual(report['claim']['kind'], 'evidence_disagreement')

    def test_collect_finishes_a_whole_observation_and_still_hands_over_to_cleanup(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_id = sim.records()[0]['run_id']
        observation_file(sim, run_id)
        executor = self.collect(sim)
        executor.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='fixture'))
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)], 'the outcome stays what it was committed as')


# Everything a JSON field can hold that its writer never put there.
SHAPES = ([], {}, None, True, 5, 1.5, 'x', [[]], [{}], [None], {'x': []})



class MalformedStopRecords(Fixture):
    """The shared reader over whatever a foreign or damaged file holds: never an exception, and never anything irreversible on its word."""

    def committed(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        row = sim.records()[0]
        return sim, row['run_id'], sim.run_dir(row['run_id'])

    def fact_document(self, sim, own_run, **changes):
        return dict(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=own_run, role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['failed'], fencing_token=2, found_at='2026-10-30T00:00:00Z'), **changes)

    def fact_table(self, sim, run_id):
        for field in ('schema', 'session_id', 'manifest_sha256', 'run_id', 'role', 'outcome', 'details', 'fencing_token', 'found_at', 'receipts'):
            for value in SHAPES:
                legitimate = (field == 'found_at' and value == 'x') or (field == 'receipts' and value in ([], None))
                if not legitimate:
                    yield '%s=%r' % (field, value), json.dumps(self.fact_document(sim, run_id, **{field: value}))
        receipt = dict(path='seal.json', expected_sha256='a' * 64, actual_sha256='b' * 64)
        for field in ('expected_sha256', 'actual_sha256', 'retained_as'):
            for value in SHAPES + ('a\0b', '', '.', '/etc/passwd', '../x'):
                if not (field == 'retained_as' and value is None):
                    yield 'receipt.%s=%r' % (field, value), json.dumps(self.fact_document(sim, run_id, receipts=[dict(receipt, **{field: value})]))
        for value in ('[]', '{}', 'null', 'true', '5', '"x"', '{"half', '', '[' * 200000):
            yield 'document=%s' % value[:10], value

    def execution_table(self, record):
        for field, values in (('demonstrated_outcome', ([], 5, True, 1.5, 'x', [[]], {}, dict(outcome=[]), dict(outcome={}), dict(outcome=None), dict(outcome=5), dict(outcome=True), dict(outcome='x'), dict(outcome=PASS), dict(outcome=INFRASTRUCTURE_FAILURE, reasons=5), dict(outcome=INFRASTRUCTURE_FAILURE, reasons={}), dict(outcome=INFRASTRUCTURE_FAILURE, reasons=True), dict(outcome=INFRASTRUCTURE_FAILURE, reasons=[1]))),
                              ('demonstrated_problems', ([], 5, True, 1.5, 'x', dict(infrastructure=5), dict(infrastructure={}), dict(infrastructure=True), dict(infrastructure='x'), dict(infrastructure=[1]), dict(game=5))),
                              ('problems', ([], None, 5, True, 'x', dict(infrastructure=5), dict(infrastructure=[1]))),
                              ('interrupted', ([], {}, 5, True))):
            for value in values:
                yield '%s=%r' % (field, value), json.dumps(dict(record, **{field: value}))
        for value in ('[]', 'null', 'true', '5', '"x"', '{"half', '[' * 200000):
            yield 'document=%s' % value[:10], value

    def assertTotal(self, sim, run_id, path, name):
        facts, unverified = cs.stop_records(sim.run_dir(run_id), dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id))
        self.assertEqual(facts, [], 'no fact from it')
        self.assertIn(path.name, [item['record'] for item in unverified], name)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement', 'and the report renders the disagreement')
        self.assertIn(path.name, capacity_report.render_search(report))

    def test_each_terminal_fact_shape_is_unverified_through_the_reader_the_resume_and_the_report(self):
        sim, run_id, run_dir = self.committed()
        path = run_dir / 'terminal-fact-0002-0.json'
        for name, text in self.fact_table(sim, run_id):
            with self.subTest(name):
                path.write_text(text)
                self.assertTotal(sim, run_id, path, name)
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                path.unlink()
        self.assertNoSuccessor(sim)
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'], 'removing the stray file restores the session')

    def test_each_execution_record_shape_is_unverified_whoever_it_names(self):
        sim, run_id, run_dir = self.committed()
        record = json.loads((run_dir / 'execution.json').read_text())
        record.update(writer='reconcile')
        path = run_dir / 'execution-reconciled-0002-9.json'
        for identity in (dict(), dict(session_id='foreign-session')):
            for name, text in self.execution_table(dict(record, **identity)):
                with self.subTest(name, identity=identity):
                    path.write_text(text)
                    self.assertTotal(sim, run_id, path, name)
                    executor, control = sim.controller()
                    resumed = executor.resume('operator', control)
                    self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                    self.assertIsNone(sim.status_now()['terminal_failure'])
                    path.unlink()
        self.assertNoSuccessor(sim)
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator', control)['resumed'])

    def running_dispatch(self, leave):
        sim = self.sim_of(RULES)

        def failpoint(point):
            if point == 'after_outcome_commit' and not failpoint.done:
                failpoint.done = True
                row = sim.records()[0]
                leave(sim, row)
        failpoint.done = False
        executor = sim.executor(failpoint=failpoint)
        return sim, executor, executor.execute()

    def test_an_already_running_dispatch_refuses_without_a_false_infrastructure_stop_and_recovers(self):
        def fact_with(field, value):
            def leave(sim, row):
                document = self.fact_document(sim, row['run_id'], fencing_token=row['fencing_token'], **{field: value})
                (sim.run_dir(row['run_id']) / ('terminal-fact-%04d-0.json' % row['fencing_token'])).write_text(json.dumps(document))
                leave.path = sim.run_dir(row['run_id']) / ('terminal-fact-%04d-0.json' % row['fencing_token'])
            return leave

        def execution_with(demonstrated=None, text=None):
            def leave(sim, row):
                record = json.loads((sim.run_dir(row['run_id']) / 'execution.json').read_text())
                record.update(writer='reconcile', demonstrated_outcome=demonstrated)
                leave.path = sim.run_dir(row['run_id']) / 'execution-reconciled-0001-9.json'
                leave.path.write_text(text if text is not None else json.dumps(record))
            return leave

        cases = [('outcome=%r' % (value,), fact_with('outcome', value)) for value in ([], {}, None, True, 5)]
        cases += [('details=%r' % (value,), fact_with('details', value)) for value in ({}, 5)]
        cases += [('execution=%r' % (value,), execution_with(dict(outcome=value, reasons=['foreign']))) for value in ([], {}, 5)]
        cases += [('execution_reasons', execution_with(dict(outcome=INFRASTRUCTURE_FAILURE, reasons=5))), ('execution_document', execution_with(text='[]'))]
        for name, leave in cases:
            with self.subTest(name):
                sim, executor, result = self.running_dispatch(leave)
                self.assertEqual((result.status, result.code), (run_executor.STOPPED, UNVERIFIED), result)
                self.assertIsNone(sim.status_now()['terminal_failure'], 'no false permanent stop')
                self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)])
                self.assertNoSuccessor(sim)
                self.assertIn(leave.path.name, capacity_report.render_search(capacity_report.build(sim.stack.root)))
                leave.path.unlink()
                next_executor, control = sim.controller()
                resumed = next_executor.resume('operator', control)
                self.assertTrue(resumed['resumed'], resumed)
                self.assertEqual(next_executor.execute().search_status, 'confirmed', 'the stray file cost the session nothing')

    def test_a_stopped_dispatch_still_reaches_its_cleanup(self):
        def leave(sim, row):
            document = self.fact_document(sim, row['run_id'], fencing_token=row['fencing_token'], outcome=[])
            (sim.run_dir(row['run_id']) / ('terminal-fact-%04d-0.json' % row['fencing_token'])).write_text(json.dumps(document))
        sim, executor, result = self.running_dispatch(leave)
        executor.wrap_up(result)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'cleanup is not lost')
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_an_unfinished_run_with_a_malformed_earlier_record_reconciles_instead_of_failing(self):
        for name, text in (('reasons', json.dumps(dict(demonstrated_outcome=dict(outcome=INFRASTRUCTURE_FAILURE, reasons=5), problems={}))), ('problems', json.dumps(dict(problems=dict(game=5)))), ('demonstrated', json.dumps(dict(problems={}, demonstrated_outcome=[]))), ('document', '[]')):
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_execution_record')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                (run_dir / 'execution-reconciled-0002-9.json').write_text(text)
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], UNVERIFIED, resumed)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertNoSuccessor(sim)

    def test_an_earlier_record_cannot_demonstrate_a_pass_into_an_unfinished_run(self):
        """Its writer only ever demonstrates a stop. A record saying otherwise is carried nowhere, so it cannot reach an outcome commit without a score."""
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_execution_record')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        record = json.loads((run_dir / 'execution.json').read_text())
        (run_dir / 'execution-reconciled-0002-9.json').write_text(json.dumps(dict(record, writer='reconcile', demonstrated_outcome=dict(outcome=PASS, reasons=['said so']))))
        executor, control = sim.controller()
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], UNVERIFIED, resumed)
        verdict = json.loads(next(path for path in sorted(run_dir.glob('classification*.json'))).read_text())['verdict']
        self.assertNotIn('said so', verdict.get('reasons') or [])
        self.assertNoSuccessor(sim)

    def test_the_refusal_says_what_is_wrong_and_not_only_that_something_was(self):
        """The reader's last resort must not be what catches these: an operator has to be able to see why, and every other problem in the file with it."""
        sim, run_id, run_dir = self.committed()
        path = run_dir / 'terminal-fact-0002-0.json'
        record = run_dir / 'execution-reconciled-0002-9.json'
        expected = dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id)
        for value in ([], {}):
            with self.subTest(value=value):
                path.write_text(json.dumps(self.fact_document(sim, run_id, session_id='foreign-session', outcome=value)))
                problems = next(item for item in cs.stop_records(run_dir, expected)[1] if item['record'] == path.name)['problems']
                self.assertTrue(any('session_id' in item for item in problems), problems)
                self.assertTrue(any('it names outcome' in item for item in problems), problems)
                path.unlink()
                document = json.loads((run_dir / 'execution.json').read_text())
                document.update(session_id='foreign-session', demonstrated_outcome=dict(outcome=value, reasons=['foreign']))
                record.write_text(json.dumps(document))
                problems = next(item for item in cs.stop_records(run_dir, expected)[1] if item['record'] == record.name)['problems']
                self.assertTrue(any('demonstrated outcome' in item for item in problems), problems)
                record.unlink()

    def test_a_decision_of_no_shape_beside_a_stop_is_named_and_does_not_stand_in_its_way(self):
        for value in (['x'], 5, True, 'x'):
            with self.subTest(value=value):
                sim = self.sim_of(RULES)
                self.crash(sim, 'before_outcome_commit')
                run_id = sim.records()[0]['run_id']
                run_dir = sim.run_dir(run_id)
                path = run_dir / 'classification.json'
                path.chmod(0o644)
                path.write_text(json.dumps(dict(json.loads(path.read_text()), verdict=value)))
                observation_file(sim, run_id)
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], TERMINAL, resumed)
                self.assertEqual(sim.outcomes(), [('coarse', 25, INFRASTRUCTURE_FAILURE)])
                self.assertNoSuccessor(sim)

    def test_a_genuine_old_fact_stands_and_outranks_anything_malformed_beside_it(self):
        sim, run_id, run_dir = self.committed()
        own = integrity._terminal_fact_file(sim, run_id, 1, name='terminal-fact-0001-0.json')
        (run_dir / 'terminal-fact-0002-0.json').write_text(json.dumps(self.fact_document(sim, run_id, outcome=[])))
        (run_dir / 'execution-reconciled-0002-9.json').write_text('[]')
        executor, control = sim.controller()
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], TERMINAL, resumed)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        row = capacity_report.build(sim.stack.root)['trials'][0]
        self.assertEqual([item['record'] for item in row['hard_facts']], [own.name])
        self.assertEqual(sorted(item['record'] for item in row['unverified_stop_records']), ['execution-reconciled-0002-9.json', 'terminal-fact-0002-0.json'])

    def test_what_is_read_beside_a_stop_record_is_total_too(self):
        """A retained decision read on the same paths, over the same kind of file. A wrong one is refused as ever, and a refusal never turns into an exception."""
        for name, change in (('outcome', lambda d: d['verdict'].update(outcome=[])), ('verdict', lambda d: d.update(verdict=[])), ('reasons', lambda d: d['verdict'].update(reasons=5)), ('supersedes', lambda d: d['verdict'].update(supersedes=[5])), ('a_supersedes_of_no_keys', lambda d: d['verdict'].update(supersedes=[{}])), ('nesting past any stack', None)):
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'before_outcome_commit')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                path = run_dir / 'classification.json'
                document = json.loads(path.read_text())
                if change:
                    change(document)
                path.chmod(0o644)
                path.write_text(json.dumps(document) if change else '[' * 200000)
                self.assertIn(capacity_report.build(sim.stack.root)['claim']['kind'], ('evidence_disagreement', 'in_progress'))
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertNotEqual(resumed.get('code'), 'controller_failure', resumed)
                self.assertNoSuccessor(sim) if not resumed['resumed'] else None
                self.assertIn(sim.records()[0]['run_id'], capacity_report.render_search(capacity_report.build(sim.stack.root)))
        for name, change in (('classification', dict(classification=[])), ('inputs', dict(inputs=dict(execution_sha256=[])))):
            with self.subTest(name):
                sim, run_id, run_dir = self.committed()
                path = run_dir / 'score.json'
                document = json.loads(path.read_text())
                document = cs.seal(dict(document, **change))
                path.chmod(0o644)
                path.write_text(cs.canonical(document))
                report = capacity_report.build(sim.stack.root)
                self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
                self.assertIn('score.json', capacity_report.render_search(report))

    def test_identities_of_no_shape_are_read_as_none_at_all(self):
        for execution in (None, [], 5, dict(roles=5), dict(roles=dict(bot=5)), dict(roles=dict(bot=dict(identity=5))), dict(roles=dict(bot=dict(identity=dict(processes=5)))), dict(roles=dict(bot=dict(identity=dict(processes=dict(game=5)))))):
            with self.subTest(execution=execution):
                self.assertIsInstance(cs.execution_identities(execution), dict)


if __name__ == '__main__':
    unittest.main()
