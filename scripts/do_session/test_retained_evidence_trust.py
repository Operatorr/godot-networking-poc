"""What a retained file can make the session do, when that file is not what it says: an observation with an expected hash nothing older supports, and retained decisions and proofs of any shape.

Everything goes through the real executor, registry, scorer and report over a fake guest. A file edited here is an edited temporary simulator file, and these are negative metadata tests in the sense of the wrong-session ones: nothing here says a normal writer produces them.
"""
import copy
import hashlib
import json
import os
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

    SHAPES = ([], 5, {}, 'x', None, [[]], [{}], {'x': []}, 1.5, True, float('inf'))

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


if __name__ == '__main__':
    unittest.main()
