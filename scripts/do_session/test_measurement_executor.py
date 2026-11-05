"""How the window proof sits in the controller: retained with the run, handed to a scorer, and able to refuse a PASS. Fake guests and scripted outcomes.

No PASS here means anything: the scorer belongs to issue #69. These tests only hold the boundary it will stand behind.
"""
import json
import unittest

import measurement_window as mw
import run_checks
import run_executor
import run_fixtures as rf
import search

COMPLETE = dict(schema=mw.PROOF_SCHEMA, status=mw.COMPLETE, reasons=[])
INCOMPLETE = dict(schema=mw.PROOF_SCHEMA, status=mw.INVALID, reasons=[dict(code='poll_starvation', category=mw.GENERATOR, detail='shard-1')])
AMBIGUOUS = dict(schema=mw.PROOF_SCHEMA, status=mw.INCONCLUSIVE, reasons=[dict(code='clock_ambiguous', category=mw.CLOCK, detail='')])


class ScorerBoundary(unittest.TestCase):
    SETTLED = dict(scorable=True, outcome=None, reasons=[], generator_failed=False, game_failed=False)

    def answer(self, outcome, **extra):
        return dict(outcome=outcome, evidence_ref='ref', scorer='fixture', reasons=['scripted'], **extra)

    def test_a_pass_needs_a_complete_window(self):
        verdict = run_checks.apply_scorer(self.SETTLED, self.answer(search.PASS), COMPLETE)
        self.assertEqual(verdict['outcome'], search.PASS)
        for proof in (INCOMPLETE, AMBIGUOUS, dict(status=None), {}):
            verdict = run_checks.apply_scorer(self.SETTLED, self.answer(search.PASS), proof)
            self.assertEqual(verdict['outcome'], search.INCONCLUSIVE, proof)
            self.assertIn('a PASS needs a proven common window', verdict['reasons'])

    def test_a_failure_can_precede_a_full_hold_but_not_stand_on_a_failed_generator(self):
        self.assertEqual(run_checks.apply_scorer(self.SETTLED, self.answer(search.FAIL), AMBIGUOUS)['outcome'], search.FAIL)
        verdict = run_checks.apply_scorer(self.SETTLED, self.answer(search.FAIL), INCOMPLETE)
        self.assertEqual(verdict['outcome'], search.INCONCLUSIVE)
        named = run_checks.apply_scorer(self.SETTLED, self.answer(search.FAIL, generator_failure_attributed_to_server=True), INCOMPLETE)
        self.assertEqual(named['outcome'], search.FAIL)

    def test_no_scorer_establishes_nothing_whatever_the_window_says(self):
        verdict = run_checks.apply_scorer(self.SETTLED, None, COMPLETE)
        self.assertEqual(verdict['outcome'], search.INCONCLUSIVE)
        self.assertIn('window proof: complete', verdict['reasons'])
        verdict = run_checks.apply_scorer(self.SETTLED, None, INCOMPLETE)
        self.assertIn('window proof: invalid (poll_starvation)', verdict['reasons'])

    def test_fixtures_with_no_prover_keep_their_old_meaning(self):
        self.assertEqual(run_checks.apply_scorer(self.SETTLED, self.answer(search.PASS), None)['outcome'], search.PASS)


class Base(unittest.TestCase):
    def setUp(self):
        self.sim = rf.RunSim(self)
        self.addCleanup(rf.make_writable, self.sim.stack.root)
        self.sim.ready()
        self.guests = self.sim.guests
        self.seen = []

    def prover(self, proof):
        def prove(root, trial, workload, identities, brackets, telemetry_schema=None, require_counters=True, prior=None):
            self.seen.append(dict(root=root, trial=trial, workload=workload, identities=identities, brackets=brackets, telemetry_schema=telemetry_schema, require_counters=require_counters, prior=prior))
            return proof
        return prove


class ExecutorPath(Base):
    def run_one(self, proof=INCOMPLETE, scorer=None, **options):
        executor = self.sim.executor(scorer=scorer, window_prover=self.prover(proof), **options)
        result = executor.execute()
        return result, self.sim.records()[0]

    def test_the_production_default_is_the_real_prover(self):
        executor = run_executor.RunExecutor.__init__.__defaults__
        self.assertIn(mw.prove, executor)

    def test_both_brackets_are_retained_around_the_run_with_raw_readings(self):
        _, row = self.run_one()
        run_dir = self.sim.run_dir(row['run_id'])
        for label in ('before', 'after'):
            document = json.loads((run_dir / ('clock-%s.json' % label)).read_text())
            self.assertEqual(document['label'], label)
            for role in ('game', 'bot'):
                attempts = document['roles'][role]
                self.assertEqual(len(attempts), run_executor.CLOCK_ATTEMPTS)
                self.assertLessEqual(attempts[0]['before_ns'], attempts[0]['after_ns'])
                self.assertIn('boot_id', attempts[0])
        calls = [call['command'] for call in self.guests.calls if call['role'] == 'bot']
        self.assertLess(calls.index('clock'), calls.index('start'), 'before anything starts')
        self.assertGreater(len(calls) - 1 - calls[::-1].index('clock'), calls.index('stop'), 'after the stop')

    def test_a_host_that_cannot_answer_leaves_no_reading_and_the_run_still_finishes(self):
        self.guests.unreachable.add(('game', 'clock'))
        _, row = self.run_one(proof=INCOMPLETE)
        document = json.loads((self.sim.run_dir(row['run_id']) / 'clock-before.json').read_text())
        self.assertEqual(document['roles']['game'], [])
        self.assertTrue(document['errors'])
        self.assertIsNotNone(row['outcome'])

    def test_the_proof_is_retained_and_named_in_the_verdict(self):
        _, row = self.run_one()
        run_dir = self.sim.run_dir(row['run_id'])
        self.assertEqual(json.loads((run_dir / 'window-proof.json').read_text())['status'], mw.INVALID)
        classification = json.loads((run_dir / 'classification.json').read_text())
        self.assertEqual(classification['verdict']['outcome'], search.INCONCLUSIVE, 'with no scorer a run still establishes nothing')
        self.assertIn('window proof: invalid (poll_starvation)', classification['verdict']['reasons'])

    def test_the_prover_gets_verified_local_facts_and_the_frozen_schema(self):
        self.run_one()
        call = self.seen[0]
        self.assertEqual(call['workload'], self.sim.manifest['workload'])
        self.assertEqual(call['telemetry_schema'], self.sim.manifest['telemetry_schema'])
        self.assertEqual(set(call['identities']), {'game', 'bot'})
        self.assertIn('bot', call['identities']['bot'])
        self.assertTrue(call['require_counters'])
        self.assertEqual(set(call['brackets']), {'before', 'after'})

    def test_a_scorer_receives_the_proof_and_cannot_pass_without_it(self):
        scorer = rf.scripted_scorer({25: search.PASS})
        _, row = self.run_one(proof=INCOMPLETE, scorer=scorer)
        self.assertEqual(scorer.seen[0]['window_proof']['status'], mw.INVALID)
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)

    def test_a_complete_window_lets_a_scorer_decide(self):
        scorer = rf.scripted_scorer({25: search.PASS, 50: search.FAIL})
        _, row = self.run_one(proof=COMPLETE, scorer=scorer)
        self.assertEqual(row['outcome'], search.PASS)

    def test_a_prover_that_breaks_proves_nothing_and_the_outcome_still_commits(self):
        def broken(*args, **kwargs):
            raise KeyError('surprising file')
        executor = self.sim.executor(scorer=rf.scripted_scorer({25: search.PASS}), window_prover=broken)
        executor.execute()
        row = self.sim.records()[0]
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)
        proof = json.loads((self.sim.run_dir(row['run_id']) / 'window-proof.json').read_text())
        self.assertEqual(proof['reasons'][0]['code'], 'prover_failed')

    def test_a_proof_holding_a_credential_is_not_retained(self):
        leaking = dict(COMPLETE, facts=dict(note='dop_v1_' + 'a' * 64))
        executor = self.sim.executor(scorer=rf.scripted_scorer({25: search.PASS}), window_prover=self.prover(leaking))
        executor.execute()
        row = self.sim.records()[0]
        text = (self.sim.run_dir(row['run_id']) / 'window-proof.json').read_text()
        self.assertNotIn('dop_v1_', text)
        self.assertEqual(row['outcome'], search.INCONCLUSIVE)

    def test_a_returning_controller_reuses_the_retained_proof(self):
        crashing = self.sim.executor(scorer=rf.scripted_scorer({25: search.PASS}), window_prover=self.prover(INCOMPLETE), failpoint=rf.crash_at('before_outcome_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            crashing.execute()
        run_id = self.sim.records()[0]['run_id']
        written = (self.sim.run_dir(run_id) / 'window-proof.json').read_bytes()
        self.seen.clear()
        returning, _ = self.sim.controller(scorer=rf.scripted_scorer({25: search.PASS}), window_prover=self.prover(COMPLETE))
        returning.prepare()
        returning.reconcile()
        self.assertEqual((self.sim.run_dir(run_id) / 'window-proof.json').read_bytes(), written, 'evidence is never replaced')
        self.assertNotEqual(self.sim.records()[0]['outcome'], search.PASS)

    def test_slice_four_fencing_still_governs_a_measured_run(self):
        self.run_one()
        tokens = {call['token'] for call in self.guests.calls if call['command'] in ('stop', 'seal')}
        self.assertEqual(tokens, {str(self.sim.result.fencing_token)})
        for role in ('game', 'bot'):
            plan = json.loads((self.sim.run_dir(self.sim.records()[0]['run_id']) / ('plan-%s.json' % role)).read_text())
            self.assertEqual(plan['fencing_token'], self.sim.result.fencing_token)
            self.assertIn('grant', plan)
        self.assertEqual(len([c for c in self.guests.calls if c['command'] == 'clock' and c['token'] is not None]), 0, 'reading a clock needs no authority and changes nothing')

    def test_process_reset_must_hold_the_swarm_tail(self):
        executor = self.sim.executor()
        executor.timing = dict(executor.timing, process_reset_s=29)
        with self.assertRaises(run_executor.BatchStop) as caught:
            executor.prepare()
        self.assertEqual(caught.exception.code, 'timing_basis_too_small')
        self.assertIn('end guard', caught.exception.detail)


if __name__ == '__main__':
    unittest.main()
