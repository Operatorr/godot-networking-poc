"""What a retained file can make the session do, when that file is not what it says: an observation with an expected hash nothing older supports, and retained decisions and proofs of any shape.

Everything goes through the real executor, registry, scorer and report over a fake guest. A file edited here is an edited temporary simulator file, and these are negative metadata tests in the sense of the wrong-session ones: nothing here says a normal writer produces them.
"""
import copy
import hashlib
import json
import os
import subprocess
import unittest
import unittest.mock

import capacity_report
import capacity_scorer as cs
import guest_runner
import run_fixtures as rf
import test_stop_record_lifecycle as life
from search import INCONCLUSIVE, INFRASTRUCTURE_FAILURE, PASS
from test_stop_record_lifecycle import BAD_BYTES, BAD_DIGEST, RULES

SEAL = guest_runner.SEAL
UNSUPPORTED = 'e' * 64
RAW = 'bot.stdout.log'


class Fixture(life.Fixture):
    def committed(self):
        """A real simulator-produced committed PASS, with its score and classification on record."""
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        row = sim.records()[0]
        run_dir = sim.run_dir(row['run_id'])
        return sim, row['run_id'], run_dir, {name: (run_dir / name).read_bytes() for name in ('score.json', 'classification.json')}

    def stray(self, sim, run_id, relative=RAW, expected=None, payload=BAD_BYTES, token=2):
        """A correctly identified observation of ``relative``, named by the true hash of ``payload``, with those bytes where it says they are."""
        run_dir = sim.run_dir(run_id)
        actual = hashlib.sha256(payload).hexdigest()
        document = cs.corrupt_observation(sim.session_id, sim.sha, run_id, 'bot', relative, expected, actual, token, '2026-10-30T00:00:00Z')
        target = run_dir / document['retained_as']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        path = run_dir / cs.corrupt_observation_name(token, 'bot', relative, actual)
        path.write_text(json.dumps(document))
        return path, target

    def read(self, sim, run_id, **expected):
        return cs.stop_records(sim.run_dir(run_id), dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, **expected))

    def true_digest(self, run_dir, relative=RAW):
        return life.sealed_digest(run_dir, relative) if relative != SEAL else cs.file_sha256(run_dir / 'bot' / SEAL)

    def receipts(self, run_dir, role='bot'):
        return [path for path in run_dir.glob(cs.SEAL_RECEIPT_GLOB) if json.loads(path.read_text()).get('role') == role]

    def receipt_file(self, sim, run_id, token=1, role='bot', digest=None, files=None, **changes):
        document = cs.seal_receipt(sim.session_id, sim.sha, run_id, role, digest or 'a' * 64, files, token, '2026-10-30T00:00:00Z')
        document.update(changes)
        path = sim.run_dir(run_id) / cs.seal_receipt_name(token, role, document['seal_sha256'], files)
        path.write_text(json.dumps(document))
        return path

    def replaced(self, path, change):
        """``change`` over one file's bytes, and how to put them back."""
        original = path.read_bytes()
        path.chmod(0o644)
        path.write_bytes(change(original))

        def restore():
            path.chmod(0o644)
            path.write_bytes(original)
        return restore

    def assertUnverifiedAndRecoverable(self, sim, run_dir, history, *strays, restore=None):
        before = len(sim.guests.runner_steps('game', 'start'))
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedUnverified(sim, resumed, dispatched)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), before, 'no successor')
        self.assertEqual(sim.outcomes()[1:], [])
        self.assertHistoryKept(run_dir, history)
        for path in strays:
            path.unlink()
        if restore is not None:
            restore()
        executor, control = sim.controller(name='after-operator-removal')
        recovered = executor.resume('operator', control)
        self.assertTrue(recovered.get('resumed'), recovered)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'nothing irreversible stood in the way')


class AnExpectedHashHasToBeSupported(Fixture):
    """A good file labelled corrupt, and everything else short of something older that says what was expected."""

    def test_a_good_seal_labelled_corrupt_is_no_fact(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, SEAL, UNSUPPORTED, (run_dir / 'bot' / SEAL).read_bytes())
        facts, unverified = self.read(sim, run_id)
        self.assertEqual(facts, [])
        self.assertIn('the retained seal receipts say', ' '.join(unverified[0]['problems']))
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target)

    def test_a_path_the_seal_does_not_list_is_no_fact(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, 'not-in-seal.log', UNSUPPORTED, (run_dir / 'bot' / RAW).read_bytes())
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target)

    def test_a_listed_path_with_an_unsupported_expected_hash_is_no_fact(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, RAW, UNSUPPORTED)
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target)

    def test_a_seal_gone_or_changed_cannot_support_anything(self):
        def gone(seal):
            original = seal.read_bytes()
            seal.chmod(0o644)
            seal.unlink()
            return lambda: seal.write_bytes(original)
        for name, damage in (('gone', gone), ('changed', lambda seal: self.replaced(seal, lambda data: data.replace(b'"sha256"', b'"sha256" ')))):
            with self.subTest(name):
                sim, run_id, run_dir, history = self.committed()
                path, target = self.stray(sim, run_id, RAW, UNSUPPORTED)
                restore = damage(run_dir / 'bot' / SEAL)
                self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=restore)

    def test_a_seal_gone_or_changed_says_nothing_for_an_otherwise_supported_hash(self):
        sim, run_id, run_dir, _ = self.committed()
        self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        seal = run_dir / 'bot' / SEAL
        original = seal.read_bytes()
        restore = self.replaced(seal, lambda data: data.replace(b'"sha256"', b'"sha256" '))
        facts, unverified = self.read(sim, run_id)
        self.assertEqual(facts, [])
        self.assertIn('not the one its receipts name', ' '.join(unverified[0]['problems']))
        restore()
        seal.chmod(0o644)
        seal.unlink()
        facts, unverified = self.read(sim, run_id)
        self.assertEqual(facts, [], 'a sealed execution record says it arrived, so its absence is no crash')
        self.assertIn('it is gone', ' '.join(unverified[0]['problems']))
        seal.write_bytes(original)
        self.assertEqual(len(self.read(sim, run_id)[0]), 1, 'and with it back, the hash is supported again')

    def test_a_seal_fetched_back_from_the_guest_supports_what_it_lists(self):
        """A role's seal lost from this disk is asked for again on the way back, before anything is admitted, and it is the same seal the receipts name."""
        sim, run_id, run_dir, history = self.committed()
        self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        seal = run_dir / 'bot' / SEAL
        seal.chmod(0o644)
        seal.unlink()
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedTerminal(sim, resumed, dispatched)
        self.assertEqual(cs.file_sha256(seal), json.loads(self.receipts(run_dir)[0].read_text())['seal_sha256'])
        self.assertHistoryKept(run_dir, history)

    def test_an_unreadable_seal_cannot_support_anything(self):
        sim, run_id, run_dir, history = self.committed()
        seal = run_dir / 'bot' / SEAL
        path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        seal.chmod(0)
        self.assertEqual(self.read(sim, run_id)[0], [], 'whatever else is on record')
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=lambda: seal.chmod(0o440))

    def test_the_other_roles_seal_cannot_support_anything(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        restore = self.replaced(run_dir / 'bot' / SEAL, lambda _: (run_dir / 'game' / SEAL).read_bytes())
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=restore)

    def test_with_no_receipt_it_is_only_its_own_word(self):
        for relative in (RAW, SEAL):
            with self.subTest(relative):
                sim, run_id, run_dir, history = self.committed()
                path, target = self.stray(sim, run_id, relative, self.true_digest(run_dir, relative))
                kept = {item: item.read_bytes() for item in self.receipts(run_dir)}
                for item in kept:
                    item.unlink()
                self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=lambda: [item.write_bytes(data) for item, data in kept.items()])

    def test_a_receipt_of_the_other_role_says_nothing_of_this_one(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        kept = {item: item.read_bytes() for item in self.receipts(run_dir, 'bot')}
        for item in kept:
            item.unlink()
        self.assertTrue(self.receipts(run_dir, 'game'), 'the game\'s is still here')
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=lambda: [item.write_bytes(data) for item, data in kept.items()])

    def test_a_receipt_that_came_after_the_observation_says_nothing_of_it(self):
        sim, run_id, run_dir, history = self.committed()
        digest = self.true_digest(run_dir)
        path, target = self.stray(sim, run_id, RAW, digest, token=1)
        kept = {item: item.read_bytes() for item in self.receipts(run_dir)}
        document = json.loads(next(iter(kept.values())))
        for item in kept:
            item.unlink()
        later = self.receipt_file(sim, run_id, token=2, digest=document['seal_sha256'], files=document['files'])
        self.assertEqual(self.read(sim, run_id)[0], [])

        def restore():
            later.unlink()
            for item, data in kept.items():
                item.write_bytes(data)
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=restore)

    def test_a_receipt_that_cannot_be_held_to_this_run_taints_them_all(self):
        def foreign(sim, run_id):
            return self.receipt_file(sim, run_id, session_id='another-session')

        def wrong_role_in_its_name(sim, run_id):
            path = self.receipt_file(sim, run_id, role='bot')
            document = json.loads(path.read_text())
            path.write_text(json.dumps(dict(document, role='game')))
            return path

        def of_no_shape(sim, run_id):
            path = sim.run_dir(run_id) / 'seal-receipt-0001-bot-x.json'
            path.write_text(json.dumps(dict(schema=cs.SEAL_RECEIPT_SCHEMA, files=[5])))
            return path

        def half(sim, run_id):
            path = sim.run_dir(run_id) / 'seal-receipt-0001-bot-y.json'
            path.write_text('{"half')
            return path

        def deep(sim, run_id):
            path = sim.run_dir(run_id) / 'seal-receipt-0001-bot-z.json'
            path.write_text('[' * 200000)
            return path

        for make in (foreign, wrong_role_in_its_name, of_no_shape, half, deep):
            with self.subTest(make.__name__):
                sim, run_id, run_dir, history = self.committed()
                path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))
                bad = make(sim, run_id)
                self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, bad)

    def test_a_receipt_from_a_controller_that_does_not_exist_is_no_receipt(self):
        sim, run_id, run_dir, _ = self.committed()
        self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        self.receipt_file(sim, run_id, token=99)
        facts, unverified = self.read(sim, run_id, current_token=2)
        self.assertEqual(facts, [])
        self.assertIn('newer than this session', ' '.join(' '.join(item['problems']) for item in unverified))

    def test_the_receipts_decide_on_their_own_when_no_seal_has_arrived(self):
        """Before any execution record, nothing says the seal arrived, so there is nothing else to ask."""
        for relative, expected, fragment in (('not-in-seal.log', UNSUPPORTED, 'do not list'), (RAW, UNSUPPORTED, 'do not list')):
            with self.subTest(relative):
                sim, run_id, run_dir, _ = self.committed()
                seal = run_dir / 'bot' / SEAL
                seal.chmod(0o644)
                seal.unlink()
                for path in run_dir.glob('execution*.json'):
                    path.chmod(0o644)
                    path.unlink()
                self.stray(sim, run_id, relative, expected)
                facts, unverified = self.read(sim, run_id)
                self.assertEqual(facts, [])
                self.assertIn(fragment, ' '.join(unverified[0]['problems']))

    def test_receipts_that_disagree_support_nothing(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))
        other = self.receipt_file(sim, run_id, digest='c' * 64)
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, other)

    def test_a_sealed_execution_record_that_names_another_seal_supports_nothing(self):
        sim, run_id, run_dir, history = self.committed()
        path, target = self.stray(sim, run_id, RAW, self.true_digest(run_dir))

        def change(data):
            document = json.loads(data)
            document['roles']['bot']['seal_sha256'] = 'c' * 64
            return json.dumps(document).encode('utf-8')
        restore = self.replaced(run_dir / 'execution.json', change)
        self.assertEqual(self.read(sim, run_id)[0], [])
        self.assertUnverifiedAndRecoverable(sim, run_dir, history, path, target, restore=restore)

    def test_a_genuine_fact_still_outranks_an_observation_that_cannot_be_supported(self):
        sim, run_id, run_dir, history = self.committed()
        self.stray(sim, run_id, RAW, UNSUPPORTED)
        (run_dir / 'terminal-fact-0001-0.json').write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['failed'], fencing_token=1, found_at='2026-10-30T00:00:00Z')))
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedTerminal(sim, resumed, dispatched)
        self.assertHistoryKept(run_dir, history)
        row = capacity_report.build(sim.stack.root)['trials'][0]
        self.assertEqual([item['record'] for item in row['hard_facts']], ['terminal-fact-0001-0.json'])
        self.assertTrue(row['unverified_stop_records'], 'and the one beside it is still named')

    def test_the_shapes_a_reader_is_handed_are_all_refused_quietly(self):
        for seal in (None, [], 5, {}, dict(run_id='x', role='bot', files=[]), dict(run_id='r', role='game', files=[]), dict(run_id='r', role='bot', files=5), dict(run_id='r', role='bot', files=[5]), dict(run_id='r', role='bot', files=[dict(path='../x', sha256='a' * 64)]), dict(run_id='r', role='bot', files=[dict(path='x', sha256='nope')])):
            self.assertIsNone(cs.seal_inventory(seal, 'r', 'bot'), seal)
        self.assertEqual(cs.seal_inventory(dict(run_id='r', role='bot', files=[dict(path='x', sha256='a' * 64, size=1)]), 'r', 'bot'), [dict(path='x', sha256='a' * 64)])


class GenuineMismatchesStillReplay(Fixture):
    def test_a_genuine_one_with_everything_on_record_is_a_fact(self):
        for relative in (RAW, SEAL):
            with self.subTest(relative):
                sim, run_id, run_dir, history = self.committed()
                self.stray(sim, run_id, relative, self.true_digest(run_dir, relative))
                facts, unverified = self.read(sim, run_id)
                self.assertEqual([fact['outcome'] for fact in facts], [INFRASTRUCTURE_FAILURE])
                self.assertEqual(unverified, [])

    def test_the_receipt_is_on_disk_before_the_first_byte_is_asked_for(self):
        sim = self.sim_of(RULES)
        executor = sim.executor(failpoint=rf.crash_at('after_outcome_commit'))
        real = sim.guests.get
        seen = []

        def get(role, remote_path, *arguments, **options):
            run_dir = sim.run_dir(remote_path.split('/runs/')[1].split('/')[0])
            seen.append(bool(self.receipts(run_dir, role)))
            return real(role, remote_path, *arguments, **options)
        sim.guests.get = get
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.assertTrue(seen)
        self.assertTrue(all(seen), 'for every transfer')

    def test_a_crash_before_any_execution_record_replays_with_the_seal_not_yet_arrived(self):
        """The file a raw mismatch is held to arrives last, so here the receipt is all there is, and the seal's absence means nothing: no record says it arrived."""
        sim = self.sim_of(RULES)
        sim.guests.corrupt_export.add('bot.stdout.log')
        self.crash(sim, 'after_corrupt_bytes')
        row = sim.records()[0]
        run_dir = sim.run_dir(row['run_id'])
        self.assertEqual(list(run_dir.glob('execution*.json')), [], 'it died before that')
        observation = next(run_dir.glob('corrupt-observation-*.json'))
        role = json.loads(observation.read_text())['role']
        self.assertFalse((run_dir / role / SEAL).exists(), 'and its seal never arrived')
        self.assertEqual(len(self.read(sim, row['run_id'])[0]), 1, 'a fact on what was retained first')
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-later')
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], life.TERMINAL, resumed)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)

    def test_a_seal_that_failed_its_hash_replays_on_what_the_guest_said_of_it(self):
        sim, run_dir, history = self.returning(SEAL)
        executor, control = sim.controller(failpoint=rf.crash_at('after_corrupt_bytes'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.resume('operator', control)
        self.assertIn(None, [json.loads(path.read_text())['files'] for path in self.receipts(run_dir)], 'a status reply names only the digest, and that is on record before the bytes are compared')
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedTerminal(sim, resumed, dispatched)
        self.assertHistoryKept(run_dir, history)

    def test_the_controller_that_saw_it_holds_to_it_and_so_does_the_next(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim = self.sim_of(RULES)
                sim.guests.corrupt_export.add(corrupt)
                sim.executor().execute()
                self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                self.assertEqual(sim.records()[0]['outcome'], INFRASTRUCTURE_FAILURE)
                row = capacity_report.build(sim.stack.root)['trials'][0]
                self.assertTrue(row['hard_facts'])
                self.assertEqual([item['record'] for item in row['unverified_stop_records']], [], 'and it is all one coherent account')

    def test_a_receipt_a_full_disk_refused_leaves_an_observation_that_refuses_and_says_nothing_irreversible(self):
        sim = self.sim_of(RULES)
        sim.guests.corrupt_export.add(RAW)
        executor = sim.executor(failpoint=rf.crash_at('after_corrupt_bytes'))
        with life.writes_fail('open', lambda path: path.name.startswith('seal-receipt-')), self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        sim.guests.corrupt_export.clear()
        run_id = sim.records()[0]['run_id']
        facts, unverified = self.read(sim, run_id)
        self.assertEqual(facts, [])
        self.assertIn('only its own word', ' '.join(' '.join(item['problems']) for item in unverified))
        executor, control = sim.controller(name='controller-later')
        resumed = executor.resume('operator', control)
        self.assertEqual(resumed['code'], life.UNVERIFIED, resumed)
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_a_controller_alive_when_a_receipt_was_refused_still_holds_to_what_it_saw(self):
        sim = self.sim_of(RULES)
        sim.guests.corrupt_export.add(RAW)
        with life.writes_fail('open', lambda path: path.name.startswith('seal-receipt-')):
            sim.executor().execute()
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)


def _digested(path, change):
    """A score edited in place with its own digest redone, as a shape test has to: the digest only says a file was not changed afterwards."""
    document = json.loads(path.read_text())
    change(document)
    path.chmod(0o644)
    path.write_text(cs.canonical(cs.seal(document)))


def _deep(path):
    path.chmod(0o644)
    path.write_text('[' * 2000 + '0' + ']' * 2000)


def _score(field, value):
    return lambda run_dir: _digested(run_dir / 'score.json', lambda document: document.update({field: value}))


def _attribution(**changes):
    return lambda run_dir: _digested(run_dir / 'score.json', lambda document: document['attribution'].update(changes))


def _gate(name, **changes):
    return lambda run_dir: _digested(run_dir / 'score.json', lambda document: document['gates'][name].update(changes))


def _proof(**changes):
    def change(run_dir):
        path = run_dir / 'window-proof.json'
        document = json.loads(path.read_text())
        document.update(changes)
        path.chmod(0o644)
        path.write_text(json.dumps(document))
        _digested(run_dir / 'score.json', lambda score: score['inputs'].update(window_proof_sha256=cs.file_sha256(path)))
    return change


def _verdict(**changes):
    def change(run_dir):
        path = run_dir / 'classification.json'
        document = json.loads(path.read_text())
        document['verdict'].update(changes)
        path.chmod(0o644)
        path.write_text(json.dumps(document))
    return change


def _unreadable(name):
    return lambda run_dir: (run_dir / name).chmod(0)


def _a_directory(name):
    def change(run_dir):
        path = run_dir / name
        path.chmod(0o644)
        path.unlink()
        path.mkdir()
    return change


class RetainedDecisionsOfNoShape(Fixture):
    """Every one of these used to reach a nested lookup. The supplied witnesses first, then their nearest siblings."""

    SCORES = (('deep_score', lambda run_dir: _deep(run_dir / 'score.json'), 'does not read as a whole score'),
              ('departures_scalar', _attribution(departures=5), 'departures'),
              ('departures_of_scalars', _attribution(departures=[5]), 'departures'),
              ('departures_short_of_fields', _attribution(departures=[dict(bot=1)]), 'departures'),
              ('attribution_scalar', _score('attribution', 5), 'attribution'),
              ('game_exit_scalar', _attribution(game_exit=5), 'game process'),
              ('inputs_scalar', _score('inputs', 5), 'inputs'),
              ('ratio_scalar', _gate('tick_budget', ticks_wide=1, worst_possible_ratio=5, least_possible_ratio=None), 'tick_budget'),
              ('rank_text', _gate('rtt_p95', p95_ms=1, rank='x', samples=1, max_ms=1), 'rtt_p95'),
              ('peak_scalar', _gate('enet_loss', per_second_mean_peak=5), 'enet_loss'),
              ('drops_list', _gate('game_socket_drops', drops_in_widest_interval=[]), 'game_socket_drops'),
              ('errors_nan', _gate('bot_errors', errors=float('nan'), errors_that_are_the_disconnect_itself=0, independent=0), 'bot_errors'),
              ('why_list', _gate('continuity', why=[]), 'continuity'),
              ('unproven_scalar', lambda run_dir: _digested(run_dir / 'score.json', lambda document: document['validity'].update(unproven=5)), 'offered-load'),
              ('failures_of_scalars', lambda run_dir: _digested(run_dir / 'score.json', lambda document: document['validity'].update(independent_failures=[5])), 'offered-load'),
              ('offered_scalar', _score('offered_load', 5), 'offered load'),
              ('proof_code_list', _proof(reasons=[dict(code=[])]), 'window proof'),
              ('proof_reasons_scalar', _proof(reasons=5), 'window proof'),
              ('proof_reasons_of_scalars', _proof(reasons=[5]), 'window proof'),
              ('proof_category_list', _proof(reasons=[dict(code='x', category=[])]), 'window proof'),
              ('proof_facts_scalar', _proof(facts=5), 'window proof'),
              ('proof_status_list', _proof(status=[]), 'window proof'),
              ('score_a_directory', _a_directory('score.json'), 'does not read as a whole score'),
              ('score_unreadable', _unreadable('score.json'), 'does not read as a whole score'),
              ('proof_deep', lambda run_dir: _deep(run_dir / 'window-proof.json'), 'not the retained one'),
              ('proof_a_directory', _a_directory('window-proof.json'), 'not the retained one'))

    VERDICTS = (('reasons_nested', _verdict(reasons=[dict(x=[])]), 'reasons of no known shape'),
                ('reasons_scalar', _verdict(reasons=5), 'reasons of no known shape'),
                ('supersedes_scalar', _verdict(supersedes=5), 'supersedes'),
                ('supersedes_of_scalars', _verdict(supersedes=[5]), 'supersedes'),
                ('supersedes_outcome_list', _verdict(supersedes=[dict(file='x', sha256='a', outcome=[])]), 'supersedes'),
                ('evidence_ref_list', _verdict(evidence_ref=[]), 'evidence of no known shape'),
                ('classification_deep', lambda run_dir: _deep(run_dir / 'classification.json'), 'classification'),
                ('classification_a_directory', _a_directory('classification.json'), 'classification'),
                ('classification_unreadable', _unreadable('classification.json'), 'classification'))

    def assertRefusedAndRendered(self, sim, name, fragment):
        report = capacity_report.build(sim.stack.root)
        rendered = capacity_report.render_search(report)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement', name)
        self.assertFalse(report['evidence']['verified'])
        self.assertIn(fragment, rendered, name)
        self.assertNotIn('could not be read to the end', rendered, 'a strict check said so, and not only the last resort')
        self.assertFalse(report['establishes'])

    def through_everything(self, sim, name, fragment, after):
        """Report before anyone returns, then a resume and an actual dispatch, then the report again. Whatever it holds, nothing raises, nothing advances, no infrastructure failure is named and no later run starts."""
        self.assertRefusedAndRendered(sim, name, fragment)
        executor, control = sim.controller(name='controller-later')
        resumed = executor.resume('operator', control)
        self.assertFalse(resumed['resumed'], resumed)
        self.assertNotEqual(resumed.get('code'), 'controller_failure', resumed)
        dispatched = executor.execute()
        self.assertNotEqual(dispatched.code, 'controller_failure', dispatched)
        self.assertNotEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE, 'no infrastructure failure on the word of a damaged file')
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1, 'no successor')
        self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE, 'and nothing advanced')
        after()
        self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'evidence_disagreement')

    def test_a_score_or_proof_left_before_the_outcome_refuses_through_every_reader(self):
        for name, change, fragment in self.SCORES:
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_score_retained')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                keep = {item: (item.read_bytes() if item.is_file() else None) for item in (run_dir / 'score.json', run_dir / 'window-proof.json')}
                change(run_dir)
                changed = {item: (item.read_bytes() if item.is_file() and os.access(str(item), os.R_OK) else None) for item in keep}

                def after():
                    for item, data in changed.items():
                        if data is not None:
                            self.assertEqual(item.read_bytes(), data, 'a refused file stays exactly as it was')
                self.through_everything(sim, name, fragment, after)

    def test_a_classification_left_before_the_commit_refuses_through_every_reader(self):
        for name, change, fragment in self.VERDICTS:
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'before_outcome_commit')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                path = run_dir / 'classification.json'
                change(run_dir)
                changed = path.read_bytes() if path.is_file() and os.access(str(path), os.R_OK) else None

                def after(changed=changed, path=path):
                    if changed is not None:
                        self.assertEqual(path.read_bytes(), changed, 'a refused file stays exactly as it was')
                self.through_everything(sim, name, fragment, after)

    def test_a_classification_of_no_shape_is_never_committed_as_it_stands(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'before_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        _verdict(outcome=INCONCLUSIVE, reasons=[dict(x=[])])(run_dir)
        executor, control = sim.controller(name='controller-later')
        executor.resume('operator', control)
        reference = sim.records()[0]['evidence_ref']
        self.assertNotIn('runs/%s/classification.json#' % sim.records()[0]['run_id'], reference, 'the outcome rests on what replaced it')
        self.assertTrue(all(isinstance(reason, str) for reason in capacity_report.build(sim.stack.root)['trials'][0]['reasons']))

    def test_the_same_files_after_a_commit_only_withhold_the_claim(self):
        for name, change, fragment in self.SCORES[:6] + self.SCORES[16:18]:
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_outcome_commit')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                change(run_dir)
                self.assertRefusedAndRendered(sim, name, fragment)
                self.assertEqual(sim.records()[0]['outcome'], PASS, 'an outcome is immutable once committed')
                self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_a_genuine_stop_outranks_a_damaged_decision_beside_it(self):
        for name, change, _ in (self.SCORES[0], self.SCORES[1], self.SCORES[16]) + (self.VERDICTS[0],):
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_outcome_commit')
                row = sim.records()[0]
                run_dir = sim.run_dir(row['run_id'])
                (run_dir / 'terminal-fact-0001-0.json').write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=row['run_id'], role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['failed'], fencing_token=1, found_at='2026-10-30T00:00:00Z')))
                change(run_dir)
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminal(sim, resumed, dispatched)
                self.assertNoSuccessor(sim)

    def test_cleanup_is_reached_past_any_of_them(self):
        for name, change, _ in (self.SCORES[0], self.SCORES[16], self.VERDICTS[0]):
            with self.subTest(name):
                sim = self.sim_of(RULES)
                self.crash(sim, 'before_outcome_commit')
                change(sim.run_dir(sim.records()[0]['run_id']))
                executor, control = sim.controller(name='controller-later')
                executor.resume('operator', control)
                executor.wrap_up(executor.execute())
                self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_an_execution_record_a_score_rests_on_has_to_have_a_shape_too(self):
        for problems in ([1], 5, dict(infrastructure=5)):
            with self.subTest(problems):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_score_retained')
                row = sim.records()[0]
                run_dir = sim.run_dir(row['run_id'])
                path = run_dir / 'execution.json'
                document = json.loads(path.read_text())
                document['problems'] = problems
                path.chmod(0o644)
                path.write_text(json.dumps(document))
                _digested(run_dir / 'score.json', lambda score: score['inputs'].update(execution_sha256=cs.file_sha256(path)))
                found = cs.bound_score(run_dir / 'score.json', cs.retained_expectation(run_dir, row['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha']))[1]
                self.assertIn('its execution record:', ' '.join(found))
                self.assertNotIn('could not be read to the end', ' '.join(found))
                self.assertIn('score.json', capacity_report.render_search(capacity_report.build(sim.stack.root)))

    def test_a_proof_of_no_shape_with_nothing_scored_yet_decides_nothing(self):
        """A complete status and whole facts, with reasons nobody can read: it must not reach the scorer as if it were a proof, and a pass must not come of it."""
        for reasons in (5, [5], [dict(code=[])]):
            with self.subTest(reasons=reasons):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_score_retained')
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                score = run_dir / 'score.json'
                score.chmod(0o644)
                score.unlink()
                proof = run_dir / 'window-proof.json'
                document = json.loads(proof.read_text())
                self.assertEqual(document['status'], 'complete')
                document['reasons'] = reasons
                proof.chmod(0o644)
                proof.write_text(json.dumps(document))
                data = proof.read_bytes()
                executor, control = sim.controller(name='controller-later')
                resumed = executor.resume('operator', control)
                self.assertNotEqual(resumed.get('code'), 'controller_failure', resumed)
                self.assertNotEqual(sim.records()[0]['outcome'], PASS, 'no pass on it')
                self.assertNotEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
                self.assertEqual(proof.read_bytes(), data)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                capacity_report.render_search(capacity_report.build(sim.stack.root))

    def test_anything_a_strict_check_missed_is_still_a_refusal_and_never_a_validation(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'before_outcome_commit')
        row = sim.records()[0]
        run_dir = sim.run_dir(row['run_id'])
        expected = cs.retained_expectation(run_dir, row['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        document = json.loads((run_dir / 'classification.json').read_text())
        self.assertEqual(cs.bound_score(run_dir / 'score.json', expected)[1], [])
        self.assertEqual(cs.classification_problems(document, expected), [])
        for error in (TypeError, AttributeError, KeyError, RecursionError):
            with self.subTest(error=error.__name__), unittest.mock.patch.object(cs, '_result_problems', side_effect=error('a defect')):
                self.assertEqual(cs.bound_score(run_dir / 'score.json', expected)[1], ['it could not be read to the end: ' + error.__name__])
            with self.subTest(error=error.__name__), unittest.mock.patch.object(cs, '_verdict_shape_problems', side_effect=error('a defect')):
                self.assertEqual(cs.classification_problems(document, expected), ['it could not be read to the end: ' + error.__name__])

    def test_a_retained_proof_of_no_shape_is_not_handed_to_anyone(self):
        for reasons in (5, [5], [dict(code=[])], [dict()]):
            self.assertTrue(cs.proof_shape_problems(dict(reasons=reasons)), reasons)
            self.assertEqual(cs._codes(dict(reasons=reasons)), [])
        self.assertEqual(cs.proof_shape_problems(dict(reasons=[dict(code='x', category='generator', detail='y')], facts={}, status='complete')), [])
        for proof in (None, [], 5):
            self.assertTrue(cs.proof_shape_problems(proof))


class EveryPlaceAScoreCanBeWrong(Fixture):
    """A real score with each field in turn replaced by each shape. Whatever comes back, nothing raises, and what a reader is allowed to act on can always be rendered."""

    SHAPES = ([], 5, {}, 'x', None, [[]], [{}], {'x': []}, 1.5, True, float('inf'), 10 ** 400, -(10 ** 400), -1, 2 ** 63)

    def paths(self, value, prefix=()):
        for key, item in (value.items() if isinstance(value, dict) else ()):
            yield prefix + (key,)
            if len(prefix) < 3:
                yield from self.paths(item, prefix + (key,))

    def test_no_shape_of_any_field_breaks_a_reader_or_gets_past_the_renderers(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'score.json'
        original = json.loads(path.read_text())
        expected = cs.retained_expectation(run_dir, sim.records()[0]['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        path.chmod(0o644)
        tried = 0
        for where in self.paths({key: value for key, value in original.items() if key != 'diagnostics'}):
            for shape in self.SHAPES:
                document = copy.deepcopy(original)
                target = document
                for key in where[:-1]:
                    target = target[key]
                target[where[-1]] = shape
                path.write_text(cs.canonical(cs.seal(document)))
                score, problems = cs.bound_score(path, expected)
                self.assertNotIn('could not be read to the end', ' '.join(problems), (where, shape))
                if not problems:
                    capacity_report.render_run(score)
                    for name, gate in score['gates'].items():
                        capacity_report.gate_value(name, gate)
                capacity_report.render_search(capacity_report.build(sim.stack.root))
                tried += 1
        self.assertGreater(tried, 500, 'this walked the document')


class NumbersOfAnySize(Fixture):
    """A JSON integer has no size of its own. ``math.isfinite`` would turn one into a float on the way to looking at it, and one too large for that raises through every reader."""

    NUMERIC = (('gates', 'rtt_p95', 'rank'), ('gates', 'rtt_p95', 'samples'), ('gates', 'rtt_p95', 'p95_ms'), ('gates', 'rtt_p95', 'max_ms'),
               ('gates', 'enet_loss', 'per_second_mean_peak', 'second'), ('gates', 'enet_loss', 'per_second_mean_peak', 'ratio', 'approximate'), ('gates', 'enet_loss', 'window_mean_of_seconds', 'approximate'),
               ('gates', 'enet_loss', 'seconds'), ('gates', 'enet_loss', 'seconds_evaluated'), ('gates', 'enet_loss', 'borrowed_readings'),
               ('gates', 'tick_budget', 'worst_possible_ratio', 'approximate'), ('gates', 'tick_budget', 'least_possible_ratio', 'approximate'), ('gates', 'tick_budget', 'ticks_wide'), ('gates', 'tick_budget', 'over_narrow'),
               ('gates', 'bot_errors', 'errors'), ('gates', 'bot_errors', 'errors_that_are_the_disconnect_itself'), ('gates', 'bot_errors', 'independent'),
               ('offered_load', 'sent_total'), ('offered_load', 'scheduled_total'), ('offered_load', 'worst_ratio', 'approximate'))
    VALUES = (10 ** 400, -(10 ** 400), 2 ** 63, -1, float('inf'), float('nan'), True, 'x')
    REPRESENTATIVE = (('gates', 'rtt_p95', 'rank'), ('gates', 'enet_loss', 'per_second_mean_peak', 'ratio', 'approximate'), ('gates', 'bot_errors', 'errors'), ('offered_load', 'sent_total'))

    def with_value(self, path, where, value):
        document = json.loads(path.read_text())
        target = document
        for key in where[:-1]:
            target = target[key]
        self.assertIn(where[-1], target, where)
        target[where[-1]] = value
        path.chmod(0o644)
        path.write_text(cs.canonical(cs.seal(document)))
        return path.read_bytes()

    def test_each_is_a_refusal_at_the_reader(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_score_retained')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'score.json'
        original = path.read_bytes()
        expected = cs.retained_expectation(run_dir, sim.records()[0]['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        for where in self.NUMERIC:
            for value in self.VALUES:
                with self.subTest(where=where, value=str(value)[:12]):
                    path.chmod(0o644)
                    path.write_bytes(original)
                    self.with_value(path, where, value)
                    score, problems = cs.bound_score(path, expected)
                    self.assertTrue(problems, 'held to its range')
                    self.assertNotIn('could not be read to the end', ' '.join(problems), 'by a check, and not by what happened to fall over')
                    capacity_report.render_search(capacity_report.build(sim.stack.root))

    def test_the_values_a_real_score_holds_are_all_still_accepted(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_score_retained')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        expected = cs.retained_expectation(run_dir, sim.records()[0]['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        self.assertEqual(cs.bound_score(run_dir / 'score.json', expected)[1], [])
        path = run_dir / 'score.json'
        self.with_value(path, ('gates', 'rtt_p95', 'rank'), 2 ** 63 - 1)
        self.with_value(path, ('gates', 'rtt_p95', 'samples'), 2 ** 63 - 1)
        self.with_value(path, ('gates', 'rtt_p95', 'p95_ms'), 0)
        self.assertEqual(cs.bound_score(path, expected)[1], [], 'an integer is compared as the integer it is, up to the limit')

    def test_a_rank_outside_its_samples_is_no_rank(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_score_retained')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'score.json'
        expected = cs.retained_expectation(run_dir, sim.records()[0]['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        samples = json.loads(path.read_text())['gates']['rtt_p95']['samples']
        for rank in (0, samples + 1):
            self.with_value(path, ('gates', 'rtt_p95', 'rank'), rank)
            self.assertIn('rank', ' '.join(cs.bound_score(path, expected)[1]))

    def test_through_the_report_the_resume_and_a_running_dispatch(self):
        for where in self.REPRESENTATIVE:
            with self.subTest(where):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_score_retained')
                path = sim.run_dir(sim.records()[0]['run_id']) / 'score.json'
                bytes_of_it = self.with_value(path, where, 10 ** 400)
                report = capacity_report.build(sim.stack.root)
                self.assertFalse(report['evidence']['verified'])
                self.assertFalse(report['claim']['confirmed'])
                capacity_report.render_search(report)
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                dispatched = executor.execute()
                self.assertFalse(resumed['resumed'], resumed)
                self.assertEqual(sim.outcomes(), [('coarse', 25, INCONCLUSIVE)], 'refused, as any score that cannot be held to its run is')
                self.assertNotEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE, 'a number in a file is no failure of any host')
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1, 'no successor')
                self.assertEqual(path.read_bytes(), bytes_of_it, 'and the file stays as it was found')
                self.assertIsNotNone(dispatched)
                capacity_report.render_search(capacity_report.build(sim.stack.root))

    def test_a_genuine_stop_outranks_it(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_score_retained')
        row = sim.records()[0]
        run_dir = sim.run_dir(row['run_id'])
        self.with_value(run_dir / 'score.json', ('gates', 'rtt_p95', 'rank'), 10 ** 400)
        (run_dir / 'terminal-fact-0002-0.json').write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=row['run_id'], role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['a genuine stop of its own'], fencing_token=2, found_at='2026-10-30T00:00:00Z')))
        executor, control = sim.controller()
        self.assertFalse(executor.resume('operator', control)['resumed'])
        self.assertEqual(sim.outcomes(), [('coarse', 25, INFRASTRUCTURE_FAILURE)])
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)

    def test_on_a_committed_run_it_only_withholds_the_claim(self):
        sim, run_id, run_dir, _ = self.committed()
        path = run_dir / 'score.json'
        self.with_value(path, ('gates', 'rtt_p95', 'rank'), 10 ** 400)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        capacity_report.render_search(report)
        executor, control = sim.controller()
        executor.resume('operator', control)
        self.assertEqual(sim.outcomes()[0], ('coarse', 25, PASS), 'an immutable outcome stays')

    def test_a_conversion_nobody_foresaw_is_still_a_refusal(self):
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_score_retained')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        expected = cs.retained_expectation(run_dir, sim.records()[0]['trial'], sim.session_id, sim.sha, sim.manifest['source']['controller_sha'])
        for error in (OverflowError('too large'), ZeroDivisionError('nothing')):
            with self.subTest(type(error).__name__), unittest.mock.patch.object(cs, '_score_shape_problems', side_effect=error):
                _, problems = cs.bound_score(run_dir / 'score.json', expected)
                self.assertIn('could not be read to the end: ' + type(error).__name__, ' '.join(problems))
                self.assertTrue(capacity_report.build(sim.stack.root)['trials'][0]['evidence_problems'])

    def test_a_sampler_row_too_large_for_a_float_is_a_malformed_reading_and_not_a_broken_scorer(self):
        rows = [dict(k='header', bot_fields=['id', 'peer']), dict(k='sample', bots=[[1, [[10, 10 ** 400, 0], [11, 149.5, 0], [12, 150, 0], [13, float('nan'), 0], [14, True, 0]]]])]
        with unittest.mock.patch.object(cs, '_load_shards', return_value=[rows]):
            found, malformed = cs.peer_samples('unused', 0, 100)
        self.assertEqual(found[1], [(11, 149.5, 0), (12, 150, 0)])
        self.assertEqual(len(malformed), 3, malformed)


FORMS = ('observation', 'terminal_fact', 'execution_generation', 'execution_words_only')


class EveryFormOfTheAccount(Fixture):
    """The same account of corrupt bytes, told as an observation, a terminal fact, a reconciled execution generation with its own export, and a generation that only carries the words. It has to be held to the same older records whichever it is, or the weakest of them decides."""

    def tell(self, sim, run_id, form, relative, expected, payload=BAD_BYTES, token=2):
        """What the record of ``form`` would be, with the bytes where it says they are. Returns the files added."""
        run_dir = sim.run_dir(run_id)
        actual = hashlib.sha256(payload).hexdigest()
        retained = cs.corrupt_evidence_name('bot', relative, actual)
        target = run_dir / retained
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        receipt = dict(path=relative, kind='corrupt', reason='hash mismatch', expected_sha256=expected, actual_sha256=actual, retained_as=retained)
        words = 'bot evidence was not fully exported: %s' % [receipt]
        if form == 'observation':
            record = cs.corrupt_observation(sim.session_id, sim.sha, run_id, 'bot', relative, expected, actual, token, '2026-10-30T00:00:00Z')
            path = run_dir / cs.corrupt_observation_name(token, 'bot', relative, actual)
        elif form == 'terminal_fact':
            record = dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, role='bot', outcome=INFRASTRUCTURE_FAILURE, details=[words], fencing_token=token, found_at='2026-10-30T00:00:00Z', receipts=[receipt])
            path = run_dir / ('terminal-fact-%04d-0.json' % token)
        else:
            record = json.loads((run_dir / 'execution.json').read_text())
            record.update(writer='reconcile', fencing_token=token, demonstrated_problems=dict(infrastructure=[words]), demonstrated_outcome=dict(outcome=INFRASTRUCTURE_FAILURE, reasons=[words]), problems=dict(infrastructure=[words]), uncertain=[])
            if form == 'execution_generation':
                record['exported'] = dict(bot=dict(complete=False, failed=[receipt], files=1, copied=0))
            else:
                record['exported'] = {}
            path = run_dir / ('execution-reconciled-%04d-1.json' % token)
        path.write_text(json.dumps(record))
        return [path, target]

    def gone(self, path):
        original = path.read_bytes()
        path.chmod(0o644)
        path.unlink()
        return lambda: path.write_bytes(original)

    def without_receipts(self, run_dir, add=()):
        """Takes this role's seal receipts away, with anything ``add`` puts in their place. Returns how to put them back."""
        kept = {item: item.read_bytes() for item in self.receipts(run_dir)}
        for item in kept:
            item.unlink()
        added = [make() for make in add]

        def restore():
            for item in added:
                item.unlink()
            for item, data in kept.items():
                item.write_bytes(data)
        return restore

    def cases(self):
        """(name, relative, expected, how to arrange what is on record), each of them short of what it takes. ``expected`` is told the true digest."""
        def nothing(sim, run_id, run_dir):
            return None

        def missing_receipt(sim, run_id, run_dir):
            return self.without_receipts(run_dir)

        def foreign_receipt(sim, run_id, run_dir):
            other = self.receipt_file(sim, run_id, token=1, digest='c' * 64, session_id='another-session')
            return other.unlink

        def later_receipt(sim, run_id, run_dir):
            document = json.loads(self.receipts(run_dir)[0].read_text())
            return self.without_receipts(run_dir, [lambda: self.receipt_file(sim, run_id, token=3, digest=document['seal_sha256'], files=document['files'])])

        def disagreeing_receipt(sim, run_id, run_dir):
            return self.receipt_file(sim, run_id, digest='c' * 64).unlink

        def changed_seal(sim, run_id, run_dir):
            return self.replaced(run_dir / 'bot' / SEAL, lambda data: data.replace(b'"sha256"', b'"sha256" '))

        def wrong_role_seal(sim, run_id, run_dir):
            seal = json.loads((run_dir / 'bot' / SEAL).read_bytes())
            document = json.dumps(dict(seal, role='game')).encode('utf-8')
            restore = self.replaced(run_dir / 'bot' / SEAL, lambda _: document)
            digest = hashlib.sha256(document).hexdigest()
            restore_receipts = self.without_receipts(run_dir, [lambda: self.receipt_file(sim, run_id, token=1, digest=digest, files=[dict(path=item['path'], sha256=item['sha256']) for item in seal['files']])])

            def both():
                restore()
                restore_receipts()
            return both
        true = 'true'
        return (('unsupported_expected', RAW, UNSUPPORTED, nothing), ('good_seal_under_a_made_up_digest', SEAL, UNSUPPORTED, nothing), ('unlisted_path', 'not-in-seal.log', UNSUPPORTED, nothing),
                ('missing_receipt', RAW, true, missing_receipt), ('foreign_receipt', RAW, true, foreign_receipt), ('later_receipt', RAW, true, later_receipt), ('disagreeing_receipt', RAW, true, disagreeing_receipt),
                ('changed_seal', RAW, true, changed_seal), ('wrong_role_seal', RAW, true, wrong_role_seal))

    def test_a_supported_account_is_a_fact_and_stops_the_session_in_every_form(self):
        for form in FORMS:
            for relative in (RAW, SEAL):
                with self.subTest(form=form, relative=relative):
                    sim, run_id, run_dir, history = self.committed()
                    self.tell(sim, run_id, form, relative, self.true_digest(run_dir, relative))
                    facts, unverified = self.read(sim, run_id)
                    self.assertEqual(unverified, [])
                    self.assertTrue(facts, 'held to everything older, and it holds')
                    _, resumed, dispatched = self.later_controller(sim)
                    self.assertRefusedTerminal(sim, resumed, dispatched)
                    self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                    self.assertHistoryKept(run_dir, history)

    def test_each_unsupported_account_refuses_in_every_form_and_removing_it_restores_the_session(self):
        for form in FORMS:
            for name, relative, expected, arrange in self.cases():
                with self.subTest(form=form, case=name):
                    sim, run_id, run_dir, history = self.committed()
                    digest = self.true_digest(run_dir, RAW) if expected == 'true' else expected
                    payload = (run_dir / 'bot' / SEAL).read_bytes() if name == 'good_seal_under_a_made_up_digest' else BAD_BYTES
                    strays = self.tell(sim, run_id, form, relative, digest, payload)
                    restore = arrange(sim, run_id, run_dir)
                    facts, unverified = self.read(sim, run_id)
                    self.assertEqual(facts, [], 'no fact')
                    self.assertEqual({item['record'] for item in unverified} & {strays[0].name}, {strays[0].name}, unverified)
                    self.assertUnverifiedAndRecoverable(sim, run_dir, history, *strays, restore=restore)

    def test_a_seal_gone_from_here_supports_nothing_until_it_is_fetched_back(self):
        """Nothing says what the file was listed at while it is gone and the host cannot be asked. Once the same seal the receipts name is back, the account is held to it and stands."""
        for form in FORMS:
            with self.subTest(form):
                sim, run_id, run_dir, history = self.committed()
                self.tell(sim, run_id, form, RAW, self.true_digest(run_dir, RAW))
                self.gone(run_dir / 'bot' / SEAL)
                self.assertEqual(self.read(sim, run_id)[0], [], 'no fact')
                real = sim.guests.get

                def get(role, remote, local, timeout_s, on_wait=None):
                    if role == 'bot':
                        return rf.ssh_access.CommandResult(1, '', 'no route')
                    return real(role, remote, local, timeout_s, on_wait)
                with unittest.mock.patch.object(sim.guests, 'get', get):
                    executor, control = sim.controller()
                    resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], life.UNVERIFIED, resumed)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertHistoryKept(run_dir, history)
                _, resumed, dispatched = self.later_controller(sim)
                self.assertRefusedTerminal(sim, resumed, dispatched)

    def test_a_new_generation_does_not_lose_the_distinction_by_carrying_it(self):
        """An unfinished run, where whatever is carried becomes this return's own hard fact unless it is held to the same records first."""
        for form in ('execution_generation', 'execution_words_only'):
            with self.subTest(form):
                sim = self.sim_of(RULES)
                self.crash(sim, 'after_score_retained')
                row = sim.records()[0]
                run_dir = sim.run_dir(row['run_id'])
                strays = self.tell(sim, row['run_id'], form, RAW, UNSUPPORTED)
                executor, control = sim.controller()
                resumed, dispatched = executor.resume('operator', control), executor.execute()
                self.assertRefusedUnverified(sim, resumed, dispatched)
                self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)], 'the retained decision stands')
                newer = [path for path in run_dir.glob('execution-reconciled-*.json') if path not in strays]
                self.assertTrue(newer)
                for path in newer:
                    record = json.loads(path.read_text())
                    self.assertIsNone(record['demonstrated_outcome'])
                    self.assertEqual(record['demonstrated_problems'].get('infrastructure', []), [])
                    self.assertEqual(record['problems'].get('infrastructure', []), [], 'nothing of it was carried')
                for path in strays:
                    path.unlink()
                later, control = sim.controller(name='after-operator-removal')
                self.assertTrue(later.resume('operator', control).get('resumed'))
                self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_a_reason_of_its_own_stands_beside_an_account_that_does_not(self):
        """Neither says anything for the other. The reboot is a fact, and the account stays unverified."""
        sim, run_id, run_dir, history = self.committed()
        strays = self.tell(sim, run_id, 'execution_generation', RAW, UNSUPPORTED)
        record = json.loads(strays[0].read_text())
        record['demonstrated_outcome']['reasons'].append('bot host rebooted: [\'other\']')
        record['demonstrated_problems']['infrastructure'].append('the sampler died during the run')
        strays[0].write_text(json.dumps(record))
        facts, unverified = self.read(sim, run_id)
        self.assertEqual([fact['details'] for fact in facts], [['bot host rebooted: [\'other\']'], ['the sampler died during the run']])
        self.assertIn(strays[0].name, {item['record'] for item in unverified}, 'and the contradiction is still on record')
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedTerminal(sim, resumed, dispatched)
        self.assertHistoryKept(run_dir, history)

    def test_a_stop_that_presents_no_receipt_has_nothing_to_be_held_to(self):
        sim, run_id, run_dir, history = self.committed()
        for path in self.receipts(run_dir):
            path.unlink()
        fact = run_dir / 'terminal-fact-0002-0.json'
        fact.write_text(json.dumps(dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['a stop of its own'], fencing_token=2, found_at='2026-10-30T00:00:00Z')))
        self.assertEqual([item['record'] for item in self.read(sim, run_id)[0]], [fact.name])
        _, resumed, dispatched = self.later_controller(sim)
        self.assertRefusedTerminal(sim, resumed, dispatched)

    def test_the_shapes_a_receipt_can_take_are_refused_quietly(self):
        for shape in ([], [{}], [[]], ['x'], [dict(path=[], expected_sha256='a' * 64, actual_sha256='b' * 64)], [dict(path='x', expected_sha256='a' * 64, actual_sha256='b' * 64, retained_as=[])]):
            with self.subTest(shape=str(shape)[:40]):
                sim, run_id, run_dir, _ = self.committed()
                record = json.loads((run_dir / 'execution.json').read_text())
                record.update(writer='reconcile', fencing_token=2, exported=dict(bot=dict(failed=shape), other=5), demonstrated_outcome=dict(outcome=INFRASTRUCTURE_FAILURE, reasons=['bot.log failed its hash: bot evidence was not fully exported: [not python']))
                (run_dir / 'execution-reconciled-0002-1.json').write_text(json.dumps(record))
                facts, unverified = self.read(sim, run_id)
                self.assertIsInstance(facts, list)
                self.assertIsInstance(unverified, list)
                capacity_report.render_search(capacity_report.build(sim.stack.root))
                executor, control = sim.controller()
                self.assertFalse(executor.resume('operator', control).get('resumed') and shape not in ([], ['x'], [[]]))


class WhatAGuestSaysIsHeldToWhatIsOnRecord(Fixture):
    """The real writer with a reply that is stale or wrong, a good seal still on the guest, and the older receipt still true. A reply is not a hash a byte can be judged against until what is on record agrees."""

    def lost_raw_with_a_reply(self, command, change):
        sim, run_id, run_dir, history = self.committed()
        path = run_dir / 'bot' / RAW
        path.chmod(0o644)
        path.unlink()
        real, changed = sim.guests.run, []

        def run(role, argv, *arguments, **options):
            answer = real(role, argv, *arguments, **options)
            if role == 'bot' and len(argv) > 2 and argv[2] == command and '--run-id' in argv:
                document = json.loads(answer.stdout)
                if document.get('sealed') or document.get('seal_sha256'):
                    change(document)
                    changed.append(document)
                    return subprocess.CompletedProcess(argv, answer.returncode, json.dumps(document), answer.stderr)
            return answer
        sim.guests.run = run
        return sim, run_id, run_dir, history, changed

    def test_a_reply_that_names_another_seal_or_another_session_says_nothing(self):
        def stale(document):
            document['seal_sha256'] = UNSUPPORTED

        def foreign(document):
            document.update(seal_sha256=UNSUPPORTED, session_id='another-session')

        def foreign_only(document):
            document['session_id'] = 'another-session'

        def other_run(document):
            document['run_id'] = 'another-run'

        def other_role(document):
            document['role'] = 'game'
        for change in (stale, foreign, foreign_only, other_run, other_role):
            with self.subTest(change.__name__):
                sim, run_id, run_dir, history, changed = self.lost_raw_with_a_reply('status', change)
                receipts = sorted(path.name for path in run_dir.glob(cs.SEAL_RECEIPT_GLOB))
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertTrue(changed, 'the wrong reply was given')
                self.assertTrue(resumed.get('resumed'), resumed)
                self.assertIsNone(sim.status_now()['terminal_failure'], 'and nothing permanent came of it')
                self.assertEqual(self.read(sim, run_id), ([], []))
                self.assertEqual(sorted(path.name for path in run_dir.glob(cs.SEAL_RECEIPT_GLOB)), receipts, 'nor does it get to be on record')
                self.assertEqual(list(run_dir.glob('terminal-fact-*')), [])
                self.assertHistoryKept(run_dir, history)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)

    def test_a_reply_that_agrees_still_finds_real_corruption(self):
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = self.returning(corrupt)
                _, control = None, None
                executor, control = sim.controller()
                resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], life.TERMINAL, resumed)
                self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
                self.assertHistoryKept(run_dir, history)

    def test_an_export_is_held_to_it_too_and_a_contradiction_stays_contact_trouble(self):
        """A return to an unfinished run, sealed earlier, whose seal command now names another digest."""
        sim = self.sim_of(RULES)
        self.crash(sim, 'after_execution_record')
        row = sim.records()[0]
        run_dir = sim.run_dir(row['run_id'])
        path = run_dir / 'bot' / RAW
        path.chmod(0o644)
        path.unlink()
        real = sim.guests.run

        def run(role, argv, *arguments, **options):
            answer = real(role, argv, *arguments, **options)
            if role == 'bot' and len(argv) > 2 and argv[2] == 'seal':
                document = json.loads(answer.stdout)
                document['seal_sha256'] = UNSUPPORTED
                return subprocess.CompletedProcess(argv, answer.returncode, json.dumps(document), answer.stderr)
            return answer
        sim.guests.run = run
        executor, control = sim.controller()
        executor.resume('operator', control)
        self.assertEqual(list(run_dir.glob(cs.CORRUPT_OBSERVATION_GLOB)), [], 'nothing was judged against it')
        self.assertNotEqual(sim.records()[0]['outcome'], INFRASTRUCTURE_FAILURE)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(len({json.loads(item.read_text())['seal_sha256'] for item in self.receipts(run_dir)}), 1)

    def test_a_seal_lost_here_and_fetched_back_wrong_is_real_corruption(self):
        sim, run_id, run_dir, history = self.committed()
        for name in (SEAL, RAW):
            (run_dir / 'bot' / name).chmod(0o644)
            (run_dir / 'bot' / name).unlink()
        sim.guests.corrupt_export.add(SEAL)
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], life.TERMINAL)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)

    def test_each_older_record_is_enough_to_refuse_a_reply_on_its_own(self):
        sim, run_id, run_dir, _ = self.committed()
        expected = dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, current_token=2)
        seal, execution = run_dir / 'bot' / SEAL, run_dir / 'execution.json'
        digest = cs.file_sha256(seal)
        receipts = {path: path.read_bytes() for path in self.receipts(run_dir)}

        def without_seal_digest(data):
            document = json.loads(data)
            document['roles']['bot']['seal_sha256'] = None
            return json.dumps(document).encode('utf-8')
        restore_execution = self.replaced(execution, without_seal_digest)
        restore_seal = self.gone(seal)
        self.assertIn('the retained seal receipts say', ' '.join(cs.seal_reply_problems(run_dir, 'bot', UNSUPPORTED, None, 2, expected)), 'the receipts alone')
        for path in receipts:
            path.unlink()
        self.assertEqual(cs.seal_reply_problems(run_dir, 'bot', UNSUPPORTED, None, 2, expected), [], 'with none of them, it is the first word')
        restore_seal()
        self.assertIn('the seal retained here', ' '.join(cs.seal_reply_problems(run_dir, 'bot', UNSUPPORTED, None, 2, expected)), 'the retained seal alone')
        self.gone(seal)
        restore_execution()
        self.assertIn('execution record', ' '.join(cs.seal_reply_problems(run_dir, 'bot', UNSUPPORTED, None, 2, expected)), 'an execution record alone')

    def gone(self, path):
        original = path.read_bytes()
        path.chmod(0o644)
        path.unlink()
        return lambda: path.write_bytes(original)

    def test_no_fact_is_written_or_sent_over_a_hash_a_full_disk_kept_unsupported(self):
        """A status reply is the first word with nothing on record, and its receipt cannot be kept. Bytes then fail their hash, and all this controller has is its own memory of the reply: enough to refuse, not enough for anything permanent."""
        for corrupt in life.CORRUPT:
            with self.subTest(corrupt):
                sim, run_dir, history = self.returning(corrupt)
                for path in self.receipts(run_dir):
                    path.unlink()
                executor, control = sim.controller()
                with life.writes_fail('file_fsync', lambda path: path.name.startswith('seal-receipt-')):
                    resumed = executor.resume('operator', control)
                self.assertEqual(resumed['code'], life.UNVERIFIED, resumed)
                self.assertEqual(list(run_dir.glob('terminal-fact-*')), [])
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                self.assertHistoryKept(run_dir, history)

    def test_nothing_on_record_to_contradict_it_leaves_the_reply_the_first_word(self):
        sim, run_id, run_dir, _ = self.committed()
        expected = dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id, current_token=2)
        digest = cs.file_sha256(run_dir / 'bot' / SEAL)
        self.assertEqual(cs.seal_reply_problems(run_dir, 'bot', digest, None, 2, expected), [])
        self.assertTrue(cs.seal_reply_problems(run_dir, 'bot', UNSUPPORTED, None, 2, expected))
        self.assertTrue(cs.seal_reply_problems(run_dir, 'bot', 'not a digest', None, 2, expected))
        self.assertTrue(cs.seal_reply_problems(run_dir, 'bot', digest, dict(run_id='another', role='bot', files=[]), 2, expected))
        self.assertTrue(cs.seal_reply_problems(run_dir, 'bot', digest, dict(run_id=run_id, role='bot', files=[]), 2, expected), 'its list is not the one on record')


if __name__ == '__main__':
    unittest.main()
