"""Retained decisions and generator evidence through the real executor, registry, prover and scorer: what must stop a search, and what must still be recovered.

Each case starts from a run the production path scored, then changes what a returning controller or report finds on disk. Nothing ran, so none of it says anything about any host.
"""
import json
import pathlib
import unittest
from unittest import mock

import capacity_report
import capacity_scorer as cs
import do_session
import measurement_window as mw
import registry_client
import run_cli
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import search
from search import FAIL, INCOMPLETE, INCONCLUSIVE, INFRASTRUCTURE_FAILURE, INVALID_LOAD, PASS


class Base(unittest.TestCase):
    def sim_of(self, rules=None, **options):
        sim = sf.ScoredSim(self, sf.by_target(rules or {}), **options)
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        return sim

    def crash(self, sim, point):
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=rf.crash_at(point)).execute()

    def collect(self, sim, **options):
        executor, _ = sim.controller(**options)
        executor.collecting = True
        executor.prepare()
        executor.reconcile('fixture')
        return executor

    def score_path(self, sim, index=0):
        return sim.run_dir(sim.records()[index]['run_id']) / 'score.json'

    def overwrite(self, path, text):
        path.chmod(0o644)
        path.write_text(text)

    def stops_at_the_first_run(self, sim, result, outcome=INCONCLUSIVE):
        self.assertEqual(len(sim.records()), 1, sim.outcomes())
        self.assertEqual(sim.records()[0]['outcome'], outcome)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1, 'no successor, and no retry')
        if result is not None:
            self.assertEqual(result.search_status, search.STOPPING[outcome])


class GeneratorEvidence(Base):
    expected_code = staticmethod(lambda name, code: 'schema_mismatch' if name == 'no_bot_collector' else code)     # a fake guest always leaves a placeholder collector file, of no schema

    def test_missing_generator_proof_beside_a_failed_tick_gate_stops_with_no_successor(self):
        for name, code, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                sim = self.sim_of({25: lambda tree: (sf.slow(tree), change(tree)), 5: sf.slow})
                self.stops_at_the_first_run(sim, sim.executor().execute())
                self.assertIn(self.expected_code(name, code), sim.score_of(sim.records()[0]['run_id'])['inputs']['proof_reasons'])

    def test_missing_generator_proof_beside_a_demonstrated_crash_stops_with_no_successor(self):
        for name, code, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                sim = self.sim_of({25: lambda tree: (sf.game_died(tree, 30), sf.bots_time_out_after_game_died(tree, [1], 35), change(tree)), 5: sf.slow})
                sim.guests.game_crash_after_s = 20
                sim.guests.game_exit = (101, None)
                self.stops_at_the_first_run(sim, sim.executor().execute())

    def test_an_early_server_failure_with_independently_proven_generator_still_advances(self):
        sim = self.sim_of({25: lambda tree: (sf.game_died(tree, 30), sf.bots_time_out_after_game_died(tree, [1], 35)), 5: sf.slow})
        sim.guests.game_crash_after_s = 20
        sim.guests.game_exit = (101, None)
        result = sim.executor().execute()
        first = sim.score_of(sim.records()[0]['run_id'])
        self.assertEqual(sim.outcomes()[:2], [('coarse', 25, FAIL), ('refine', 5, FAIL)])
        self.assertEqual(first['validity']['verdict'], cs.VALID)
        self.assertNotEqual(first['inputs']['proof_status'], mw.COMPLETE, 'no whole window was demanded of it')
        self.assertEqual(result.search_status, 'no_passing_target')


class ProcessOomThroughTheExecutor(Base):
    """A SIGKILLed game through the real executor, registry, prover and scorer, in the mode a real session runs in: each run a unit of its own. No kernel ran."""

    def killed_sim(self, change=None, wrong_mode=False):
        def rule(tree):
            sf.game_died(tree, 30)
            sf.bots_time_out_after_game_died(tree, [1], 35)
            sf.supervisor_saw_an_oom_kill(tree, change)
        sim = self.sim_of({25: rule, 5: rule})
        sim.guests.game_crash_after_s = 20
        sim.guests.game_exit = (None, 9)
        sim.guests.UNIT_MODE = 'process_group' if wrong_mode else 'systemd'
        return sim

    def test_a_victim_matched_kill_advances_the_search(self):
        sim = self.killed_sim()
        result = sim.executor().execute()
        self.assertEqual(sim.outcomes()[:2], [('coarse', 25, FAIL), ('refine', 5, FAIL)])
        score = sim.score_of(sim.records()[0]['run_id'])
        self.assertEqual(score['attribution']['game_exit']['kind'], 'out_of_memory', score['attribution'])
        self.assertEqual(result.search_status, 'no_passing_target')

    def test_anything_less_stops_with_no_successor(self):
        for name, status, change in sf.OOM_NOT_ATTRIBUTED:
            with self.subTest(name):
                sim = self.killed_sim(change)
                self.stops_at_the_first_run(sim, sim.executor().execute())
                self.assertEqual(sim.score_of(sim.records()[0]['run_id'])['attribution']['game_exit']['kind'], 'killed_with_no_cause_on_record')

    def test_a_run_without_a_unit_of_its_own_has_nothing_to_show(self):
        sim = self.killed_sim(wrong_mode=True)
        self.stops_at_the_first_run(sim, sim.executor().execute())

    def test_a_kill_with_no_evidence_at_all_stays_as_conservative_as_ever(self):
        def rule(tree):
            sf.game_died(tree, 30)
            sf.bots_time_out_after_game_died(tree, [1], 35)
        sim = self.sim_of({25: rule})
        sim.guests.game_crash_after_s = 20
        sim.guests.game_exit = (None, 9)
        self.stops_at_the_first_run(sim, sim.executor().execute())


class RampEvidence(Base):
    def failing_ramp(self, tree):
        sf.ramp_failure(tree, 'readiness_timeout', tree.timeline.target - 1)
        sf.ramp_slow_ticks(tree, 2)

    def kick_in_the_ramp(self, tree):
        sf.ramp_failure(tree, 'bot_failed_before_window', 5)
        sf.add_bot_end(tree, 3, 'server disconnected (reason 2)', dict(at_ns=2 * mw.NS, reason=cs.REASON_KICKED, expected=False))

    def test_valid_ramp_failures_advance_only_with_attribution_and_generator_proof(self):
        for name, ramp in (('overrun', self.failing_ramp), ('kick', self.kick_in_the_ramp)):
            with self.subTest(name):
                sim = self.sim_of({25: ramp, 5: sf.slow})
                result = sim.executor().execute()
                self.assertEqual(sim.outcomes()[:2], [('coarse', 25, FAIL), ('refine', 5, FAIL)])
                self.assertEqual(sim.score_of(sim.records()[0]['run_id'])['validity']['verdict'], cs.VALID)
                self.assertEqual(result.search_status, 'no_passing_target')

    def test_ramp_evidence_that_is_not_the_supervised_processes_stops_with_no_refinement(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            with self.subTest(name):
                sim = self.sim_of({25: lambda tree: (self.failing_ramp(tree), change(tree)), 5: sf.slow})
                self.stops_at_the_first_run(sim, sim.executor().execute())
                self.assertIn('schema_mismatch' if name == 'no_bot_collector' else code, sim.score_of(sim.records()[0]['run_id'])['inputs']['proof_reasons'])

    def test_a_server_crash_over_an_unobserved_tail_stops_with_no_refinement(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            if 'read' not in name:
                continue
            with self.subTest(name):
                sim = self.sim_of({25: lambda tree: (self.failing_ramp(tree), change(tree)), 5: sf.slow})
                sim.guests.game_crash_after_s = 20
                sim.guests.game_exit = (101, None)
                self.stops_at_the_first_run(sim, sim.executor().execute())

    def test_a_fully_bracketed_ramp_with_an_overflow_stops_beside_server_distress(self):
        def overflow(tree):
            self.failing_ramp(tree)
            sf._bot_socket(tree, lambda item: item.update(drops=1 if item['local_port'] == 40003 else 0))
        sim = self.sim_of({25: overflow, 5: sf.slow})
        self.stops_at_the_first_run(sim, sim.executor().execute())
        self.assertEqual(sim.score_of(sim.records()[0]['run_id'])['validity']['verdict'], cs.INVALID)

    def test_a_kick_over_a_broken_generator_proof_stops_with_no_refinement(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            with self.subTest(name):
                sim = self.sim_of({25: lambda tree: (self.kick_in_the_ramp(tree), change(tree)), 5: sf.slow})
                sim.executor().execute()
                self.assertEqual(len(sim.records()), 1, sim.outcomes())
                self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)

    def test_a_collector_on_another_boot_stops_as_infrastructure(self):
        sim = self.sim_of({25: lambda tree: (self.failing_ramp(tree), tree.edit_sampler('bot', lambda index, row: row.update(boot_id='another-boot')))})
        self.stops_at_the_first_run(sim, sim.executor().execute(), INFRASTRUCTURE_FAILURE)

    def test_an_identity_an_earlier_run_on_that_host_used(self):
        sim = self.sim_of({25: self.failing_ramp, 5: sf.slow})
        sim.guests.hosts['bot'].ledger.append(dict(run_id='an-earlier-run', role='bot', sealed=True, socket_inodes=['bot-socket-40003']))
        self.stops_at_the_first_run(sim, sim.executor().execute())
        self.assertIn('socket_identity_reused', sim.score_of(sim.records()[0]['run_id'])['inputs']['proof_reasons'])

    def test_a_process_identity_an_earlier_run_used_is_refused_wherever_it_is_caught_first(self):
        sim = self.sim_of({25: self.failing_ramp, 5: sf.slow})
        used = dict(pid=4242, start_id='ticks:424242', boot_id=sim.guests.hosts['bot'].boot_id)
        sim.guests.hosts['bot'].ledger.append(dict(run_id='an-earlier-run', role='bot', processes=dict(bot=used)))
        sim.guests.hosts['bot'].scripted_identity = used
        sim.executor().execute()
        self.assertEqual(len(sim.records()), 1, sim.outcomes())
        self.assertNotIn(sim.records()[0]['outcome'], (PASS, FAIL))

    def test_a_ramp_that_broke_a_run_cannot_blame_the_server_on_return_either(self):
        for point in ('after_execution_record', 'after_score_retained'):
            with self.subTest(point):
                sim = self.sim_of({25: lambda tree: (self.failing_ramp(tree), tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(pid=123456)))})
                self.crash(sim, point)
                self.collect(sim)
                self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)


def _reseal(document, **top):
    return cs.canonical(cs.seal(dict(document, **top)))


def _with_inputs(**inputs):
    return lambda document: _reseal(document, inputs=dict(document['inputs'], **inputs))


# The score a returning controller finds, however it came to be like this. Each of these must be refused, whatever outcome it claims. A real scorer sealed the ones that are resealed here.
REFUSED_SCORES = (
    ('another_run', lambda document: _reseal(document, run_id='another-session-another-run')),
    ('another_trial', lambda document: _reseal(document, trial=dict(document['trial'], target=50))),
    ('another_session', _with_inputs(session_id='another-session')),
    ('another_manifest', _with_inputs(manifest_sha256='a' * 64)),
    ('another_controller', _with_inputs(controller_sha='b' * 40)),
    ('another_policy_hash', lambda document: _reseal(document, policy_sha256='c' * 64)),
    ('another_policy', lambda document: _reseal(document, policy=dict(document['policy'], rtt_limit_ms_strictly_below=10_000))),
    ('another_scorer', lambda document: _reseal(document, scorer='someone-elses-scorer/1')),
    ('another_measurement_schema', _with_inputs(measurement_schema='omega.measurement/2')),
    ('another_proof_hash', _with_inputs(window_proof_sha256='d' * 64)),
    ('another_execution_hash', _with_inputs(execution_sha256='e' * 64)),
    ('other_process_identities', _with_inputs(identities=dict(bot=dict(bot=dict(pid=1, start_id='ticks:1', boot_id='b'))))),
    ('proof_status_it_never_saw', _with_inputs(proof_status='complete', proof_reasons=['something'])),
    ('outcome_changed_in_place', lambda document: cs.canonical(dict(document, outcome=PASS))),
    ('classification_and_outcome_changed_in_place', lambda document: cs.canonical(dict(document, outcome=PASS, classification=cs.VALID_PASS))),
    ('outcome_changed_and_resealed', lambda document: _reseal(document, outcome=PASS)),
    ('a_pass_over_a_failed_gate', lambda document: _reseal(document, outcome=PASS, classification=cs.VALID_PASS)),
    ('a_failure_with_no_failed_gate', lambda document: _reseal(document, gates={name: dict(gate, verdict=cs.PASS) for name, gate in document['gates'].items()})),
    ('a_gate_removed', lambda document: _reseal(document, gates={name: gate for name, gate in document['gates'].items() if name != 'tick_budget'})),
    ('rewritten_with_other_formatting', lambda document: json.dumps(document)),
    ('cut_short', lambda document: cs.canonical(document)[:200]),
    ('empty', lambda document: ''),
)


class RetainedScores(Base):
    """Starts from a run the real path scored FAIL, with the controller gone before it committed."""

    def retained(self):
        sim = self.sim_of({25: sf.slow, 5: sf.slow})
        self.crash(sim, 'after_score_retained')
        return sim, self.score_path(sim)

    def test_an_unchanged_score_is_recovered_without_being_recomputed(self):
        sim, path = self.retained()
        written = path.read_bytes()
        calls = []
        executor, _ = sim.controller()
        executor.scorer = lambda evidence: calls.append(evidence)
        executor.collecting = True
        executor.prepare()
        executor.reconcile('fixture')
        self.assertEqual(sim.records()[0]['outcome'], FAIL)
        self.assertEqual(calls, [])
        self.assertEqual(path.read_bytes(), written)

    def test_an_unchanged_score_survives_both_hosts_being_unreachable(self):
        sim, path = self.retained()
        sim.guests.unreachable.update({(role, step) for role in ('game', 'bot') for step in ('inspect', 'stop', 'clock', 'seal')})
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], FAIL, 'nothing the hosts could say would change it')

    def test_every_refused_score_stops_the_search_and_stays_as_it_was(self):
        for name, change in REFUSED_SCORES:
            with self.subTest(name):
                sim, path = self.retained()
                bad = change(cs.load_retained(path))
                self.overwrite(path, bad)
                self.collect(sim)
                self.stops_at_the_first_run(sim, None)
                self.assertEqual(path.read_text(), bad, 'never replaced')
                classification = json.loads((sim.run_dir(sim.records()[0]['run_id']) / 'classification.json').read_text())
                self.assertIn('refused', ' '.join(classification['verdict']['reasons']))
                self.assertTrue(capacity_report.build(sim.stack.root)['trials'][0]['evidence_problems'], 'and a report says so')

    def test_a_genuine_healthy_score_of_another_session_cannot_turn_a_failure_into_a_pass(self):
        other = self.sim_of()
        self.crash(other, 'after_score_retained')
        foreign = self.score_path(other).read_text()
        self.assertEqual(json.loads(foreign)['outcome'], PASS)
        sim, path = self.retained()
        self.overwrite(path, foreign)
        self.collect(sim)
        self.stops_at_the_first_run(sim, None)

    def test_a_genuine_failing_score_cannot_turn_a_pass_into_a_failure_that_advances(self):
        other, foreign_path = self.retained()
        foreign = foreign_path.read_text()
        sim = self.sim_of()
        self.crash(sim, 'after_score_retained')
        self.overwrite(self.score_path(sim), foreign)
        self.collect(sim)
        self.stops_at_the_first_run(sim, None)

    def test_a_score_of_an_earlier_run_of_this_session_is_refused(self):
        sim = self.sim_of({50: sf.slow})
        points = []

        def second_run(name):
            if name == 'after_score_retained':
                points.append(name)
                if len(points) == 2:
                    raise rf.SimulatedCrash(name)
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=second_run).execute()
        self.overwrite(self.score_path(sim, 1), self.score_path(sim, 0).read_text())
        self.collect(sim)
        self.assertEqual(sim.outcomes()[1], ('coarse', 50, INCONCLUSIVE))

    def test_a_proof_or_execution_record_changed_under_a_score(self):
        for name in ('window-proof.json', 'execution.json'):
            with self.subTest(name):
                sim, path = self.retained()
                other = sim.run_dir(sim.records()[0]['run_id']) / name
                self.overwrite(other, json.dumps(dict(json.loads(other.read_text()), edited=True), indent=2, sort_keys=True) + '\n')
                self.collect(sim)
                self.stops_at_the_first_run(sim, None)

    def test_a_proof_of_another_run_is_never_reused_or_scored(self):
        sim = self.sim_of()
        self.crash(sim, 'after_execution_record')
        proof = sim.run_dir(sim.records()[0]['run_id']) / 'window-proof.json'
        self.assertFalse(proof.exists())
        document = sim.guests.trees[sim.records()[0]['run_id']].prove(telemetry_schema=sf.FROZEN_SCHEMA)
        proof.write_text(json.dumps(dict(document, run_id='another-run')))
        self.collect(sim)
        self.assertNotIn(sim.records()[0]['outcome'], (PASS, FAIL))

    def test_a_missing_proof_under_a_score_is_refused(self):
        sim, path = self.retained()
        proof = sim.run_dir(sim.records()[0]['run_id']) / 'window-proof.json'
        proof.chmod(0o644)
        proof.unlink()
        self.collect(sim)
        self.stops_at_the_first_run(sim, None)

    def test_a_refused_score_does_not_mask_a_demonstrated_infrastructure_failure(self):
        sim, path = self.retained()
        self.overwrite(path, '{"schema": "foreign"}')
        _carry_a_demonstrated_infrastructure_failure(sim, path.parent)
        self.collect(sim)
        self.stops_at_the_first_run(sim, None, INFRASTRUCTURE_FAILURE)

    def test_a_refused_score_does_not_mask_a_terminal_fact(self):
        sim = self.sim_of({25: sf.slow})
        sim.guests.bot_exit = (4, None)
        self.crash(sim, 'after_execution_record')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        (run_dir / 'score.json').write_text('{"schema": "foreign"}')
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)


def _carry_a_demonstrated_infrastructure_failure(sim, run_dir):
    """What a returning controller that saw corrupt bytes and then died leaves behind: a fact, kept apart from anything it could not reach."""
    record = json.loads((run_dir / 'execution.json').read_text())
    (run_dir / 'execution-reconciled-0099-1.json').write_text(json.dumps(dict(record, writer='reconcile', demonstrated_problems=dict(infrastructure=['bot evidence failed its hash']), demonstrated_outcome=None, uncertain=[], problems=dict(infrastructure=['bot evidence failed its hash'], generator=[], game=[]))))


def _nth_crash(point, nth):
    """Dies the nth time ``point`` is reached, which is how a test picks out one run of a search."""
    seen = []

    def failpoint(name):
        if name == point:
            seen.append(name)
            if len(seen) == nth:
                raise rf.SimulatedCrash(name)
    return failpoint


class StopFacts(Base):
    """A failure demonstrated on a return outranks an intact retained decision that was never committed, and stops the session if the decision already was."""
    POINTS = ('after_score_retained', 'before_outcome_commit')
    RULES = {50: sf.slow, 30: sf.slow}

    def lose_a_file(self, sim, index=0, corrupt=True):
        run_dir = sim.run_dir(sim.records()[index]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        if corrupt:
            sim.guests.corrupt_export.add('bot.stdout.log')
        return run_dir

    def decision_bytes(self, run_dir):
        return {name: (run_dir / name).read_bytes() for name in ('score.json', 'classification.json', 'window-proof.json', 'score-report.md', 'execution.json') if (run_dir / name).exists()}

    def assertStoppedInfrastructure(self, sim, run_dir, before, starts, result):
        self.assertFalse(result['resumed'], result)
        self.assertEqual(result['code'], 'terminal_failure')
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts, 'no successor')
        now = self.decision_bytes(run_dir)
        self.assertEqual({name: now.get(name) for name in before}, before, 'an earlier decision stays as it was written')

    def assertReported(self, sim, run_id, claim_kind='stopped_infrastructure_failure', superseded=True):
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], claim_kind, report['claim'])
        self.assertFalse(report['establishes'])
        self.assertFalse(report['evidence']['verified'], 'the whole cannot be called verified with a stop fact standing against part of it')
        self.assertIn(run_id, report['evidence']['trials_with_stop_facts'])
        row = next(item for item in report['trials'] if item['run_id'] == run_id)
        self.assertTrue(any('hash mismatch' in str(fact['details']) or 'failed its hash' in str(fact['details']) for fact in row['hard_facts']), row['hard_facts'])
        if superseded:
            self.assertTrue(row['superseded_decisions'], row)
            self.assertIn(run_id, report['evidence']['superseded_trials'])
            self.assertTrue(any(item['outcome'] == PASS for item in row['superseded_decisions']))
            self.assertIsNone(row['classification'], 'what the old score classified is not the run\'s classification any more')
        rendered = capacity_report.render_search(report)
        self.assertIn('Stop fact', rendered)
        self.assertNotIn('confirmed', report['claim']['kind'])
        return report, rendered

    def test_corrupt_bytes_on_return_outrank_a_valid_retained_decision(self):
        for point in self.POINTS:
            with self.subTest(point):
                sim = self.sim_of(self.RULES)
                self.crash(sim, point)
                run_dir = self.lose_a_file(sim)
                before = self.decision_bytes(run_dir)
                self.assertEqual(json.loads((run_dir / 'score.json').read_text())['outcome'], PASS, 'the score really was a healthy one')
                executor, control = sim.controller()
                starts = len(sim.guests.runner_steps('game', 'start'))
                result = executor.resume('operator: remaining', control)
                self.assertStoppedInfrastructure(sim, run_dir, before, starts, result)
                self.assertEqual(sim.outcomes(), [('coarse', 25, INFRASTRUCTURE_FAILURE)])
                self.assertReported(sim, sim.records()[0]['run_id'])

    def test_the_fact_survives_a_second_crash_and_a_transfer_that_works_again(self):
        for point in self.POINTS:
            with self.subTest(point):
                sim = self.sim_of(self.RULES)
                self.crash(sim, point)
                run_dir = self.lose_a_file(sim)
                before = self.decision_bytes(run_dir)
                starts = len(sim.guests.runner_steps('game', 'start'))
                executor, control = sim.controller(failpoint=rf.crash_at('after_reconcile_record'))
                with self.assertRaises(rf.SimulatedCrash):
                    executor.resume('operator', control)
                sim.guests.corrupt_export.clear()
                executor, control = sim.controller(name='controller-c')
                result = executor.resume('operator', control)
                self.assertStoppedInfrastructure(sim, run_dir, before, starts, result)
                self.assertEqual(sim.outcomes(), [('coarse', 25, INFRASTRUCTURE_FAILURE)])
                records = [json.loads(path.read_text()) for path in sorted(run_dir.glob('execution-reconciled-*.json'))]
                self.assertTrue(any(item['problems'].get('infrastructure') for record in records for item in record['carried_from']), 'the source of the fact is named')
                self.assertReported(sim, sim.records()[0]['run_id'])

    def test_a_report_made_between_the_crashes_withholds_the_claim(self):
        """Nobody has committed anything yet. The classification on disk says PASS, and a record beside it says otherwise."""
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'before_outcome_commit')
        self.lose_a_file(sim)
        executor, control = sim.controller(failpoint=rf.crash_at('after_reconcile_record'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.resume('operator', control)
        report = capacity_report.build(sim.stack.root)
        self.assertFalse(report['evidence']['verified'])
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertIn('stop fact', str(report['trials'][0]['evidence_problems']))

    def test_confirmation_siblings_stay_untouched(self):
        for point in self.POINTS:
            for name, crashes_twice in (('one_crash', False), ('second_crash', True)):
                with self.subTest(point=point, name=name):
                    sim = self.sim_of(self.RULES)
                    with self.assertRaises(rf.SimulatedCrash):
                        sim.executor(failpoint=_nth_crash(point, 4)).execute()
                    self.assertEqual(sim.outcomes()[:3], [('coarse', 25, PASS), ('coarse', 50, FAIL), ('refine', 30, FAIL)])
                    self.assertEqual(sim.outcomes()[3][:2], ('confirm', 25))
                    run_dir = self.lose_a_file(sim, 3)
                    before = self.decision_bytes(run_dir)
                    starts = len(sim.guests.runner_steps('game', 'start'))
                    if crashes_twice:
                        executor, control = sim.controller(failpoint=rf.crash_at('after_reconcile_record'))
                        with self.assertRaises(rf.SimulatedCrash):
                            executor.resume('operator', control)
                        sim.guests.corrupt_export.clear()
                    executor, control = sim.controller(name='controller-c')
                    result = executor.resume('operator', control)
                    self.assertStoppedInfrastructure(sim, run_dir, before, starts, result)
                    self.assertEqual(sim.outcomes()[3], ('confirm', 25, INFRASTRUCTURE_FAILURE))
                    self.assertEqual(len(sim.records()), 4, 'repetitions 2 and 3 were never dispatched')
                    self.assertReported(sim, sim.records()[3]['run_id'])

    def test_collect_from_any_controller_records_the_stop_too(self):
        for point in self.POINTS:
            with self.subTest(point):
                sim = self.sim_of(self.RULES)
                self.crash(sim, point)
                self.lose_a_file(sim)
                self.collect(sim, source_problems=lambda: ['controller revision is not frozen'])
                self.assertEqual(sim.records()[0]['outcome'], INFRASTRUCTURE_FAILURE)
                self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)

    def test_an_earlier_generations_invalid_load_fact_outranks_a_retained_decision(self):
        for point in self.POINTS:
            with self.subTest(point):
                sim = self.sim_of(self.RULES)
                self.crash(sim, point)
                run_dir = sim.run_dir(sim.records()[0]['run_id'])
                record = json.loads((run_dir / 'execution.json').read_text())
                (run_dir / 'execution-reconciled-0099-1.json').write_text(json.dumps(dict(record, writer='reconcile', fencing_token=99, demonstrated_problems={}, demonstrated_outcome=dict(outcome=INVALID_LOAD, reasons=['the swarm crashed by itself: exit 3 signal None']), uncertain=[])))
                executor, control = sim.controller()
                result = executor.resume('operator', control)
                self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'))
                self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)
                self.assertEqual(sim.status_now()['terminal_failure'], INVALID_LOAD)

    def test_a_retained_terminal_verdict_stays_what_it_is_with_the_fact_beside_it(self):
        sim = self.sim_of({25: sf.starved})
        self.crash(sim, 'before_outcome_commit')
        self.lose_a_file(sim)
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], 'terminal_failure')
        self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)
        report = capacity_report.build(sim.stack.root)
        self.assertTrue(report['trials'][0]['hard_facts'], 'the fact stays visible beside the verdict that stands')

    def test_an_unreachable_host_alone_costs_a_healthy_retained_decision_nothing(self):
        for point in self.POINTS:
            with self.subTest(point):
                sim = self.sim_of(self.RULES)
                self.crash(sim, point)
                run_dir = self.lose_a_file(sim, corrupt=False)
                sim.guests.copy_failures.update({('bot', 'get')})
                self.collect(sim)
                self.assertEqual(sim.records()[0]['outcome'], PASS, 'a transfer that could not run says nothing')
                self.assertIsNone(sim.status_now()['terminal_failure'])
                executions = [json.loads(path.read_text()) for path in run_dir.glob('execution-reconciled-*.json')]
                self.assertTrue(all(not (record.get('demonstrated_problems') or {}).get('infrastructure') for record in executions))
                self.assertTrue(any(record['uncertain'] for record in executions))

    def test_an_unknown_recorded_host_identity_is_no_stop_fact_either(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_score_retained')
        sim.guests.unreachable.update({(role, step) for role in ('game', 'bot') for step in ('inspect', 'stop', 'clock', 'seal')})
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], PASS)
        self.assertIsNone(sim.status_now()['terminal_failure'])

    # ---- the outcome was already committed ------------------------------------------------------------

    def test_corrupt_bytes_found_after_the_commit_stop_the_session_and_leave_the_outcome(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        self.assertEqual(sim.records()[0]['outcome'], PASS)
        run_dir = self.lose_a_file(sim)
        before = self.decision_bytes(run_dir)
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertStoppedInfrastructure(sim, run_dir, before, starts, result)
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)], 'a committed outcome is immutable')
        self.assertEqual(len(sorted(run_dir.glob('terminal-fact-*.json'))), 1)
        report, rendered = self.assertReported(sim, sim.records()[0]['run_id'], claim_kind='evidence_disagreement', superseded=False)
        self.assertEqual(report['trials'][0]['outcome'], PASS, 'what the journal recorded stays in the row')
        self.assertIn('History only', rendered)

    def test_a_crash_between_writing_that_fact_and_the_registry_hearing_of_it_is_finished_by_the_next_controller(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = self.lose_a_file(sim)
        executor, control = sim.controller(failpoint=rf.crash_at('after_terminal_fact'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.resume('operator', control)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'it was only written down')
        self.assertEqual(len(sorted(run_dir.glob('terminal-fact-*.json'))), 1)
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-c')
        self.assertEqual(executor.resume('operator', control)['code'], 'terminal_failure')
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)

    def test_a_committed_run_whose_transfer_cannot_run_keeps_its_successor(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        self.lose_a_file(sim, corrupt=False)
        sim.guests.copy_failures.update({('bot', 'get')})
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertTrue(result['resumed'], result)
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_a_stop_fact_beside_a_committed_outcome_refuses_the_resume(self):
        """A record a generation left beside an outcome already in the registry, however it got there."""
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        _carry_a_demonstrated_infrastructure_failure(sim, run_dir)
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], 'terminal_failure')
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)])

    def test_recovery_at_wrap_up_records_corrupt_bytes_for_a_committed_run(self):
        sim = self.sim_of(self.RULES)
        executor = sim.executor()
        result = executor.execute()
        self.assertEqual(result.search_status, 'confirmed')
        run_dir = self.lose_a_file(sim)
        before = self.decision_bytes(run_dir)
        self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'confirmed_observation')
        executor.wrap_up(result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(self.decision_bytes(run_dir), before)
        self.assertEqual(sim.status_now()['cleanup']['requested_at'] is not None, True, 'it never stands between a finished batch and its cleanup')
        self.assertEqual(len(sorted(run_dir.glob('terminal-fact-*.json'))), 1, 'one fact, however many sweeps saw it')
        report, _ = self.assertReported(sim, sim.records()[0]['run_id'], claim_kind='evidence_disagreement', superseded=False)
        self.assertEqual(report['journal_claim']['kind'], 'confirmed_observation', 'the journal\'s history stays')

    def test_bytes_that_fail_on_one_sweep_and_recover_on_the_next_are_not_unsaid(self):
        sim = self.sim_of(self.RULES)
        executor = sim.executor()
        result = executor.execute()
        run_dir = self.lose_a_file(sim)
        real_get = sim.guests.get
        calls = []

        def get(role, remote, local, timeout_s, on_wait=None):
            answer = real_get(role, remote, local, timeout_s, on_wait)
            if remote.endswith('bot.stdout.log'):
                calls.append(remote)
                sim.guests.corrupt_export.clear()
            return answer
        sim.guests.get = get
        executor.wrap_up(result)
        self.assertEqual((run_dir / 'bot' / 'bot.stdout.log').exists(), True, 'recovered')
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)


class UnacknowledgedStops(Base):
    """A stop fact the registry did not take is still a stop fact, and failing to record it must not turn into permission. Every case here has a real controller, a real resume and a real dispatch to walk into."""
    RULES = {50: sf.slow, 30: sf.slow}

    def fixture(self, retained=False, point='after_outcome_commit'):
        """A committed PASS, then corrupt bytes on the way back. ``retained``: an earlier controller already wrote the fact, and died before the registry heard."""
        sim = self.sim_of(self.RULES)
        self.crash(sim, point)
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        sim.guests.corrupt_export.add('bot.stdout.log')
        if retained:
            executor, control = sim.controller(name='controller-a', failpoint=rf.crash_at('after_terminal_fact'))
            with self.assertRaises(rf.SimulatedCrash):
                executor.resume('operator', control)
            self.assertEqual(len(list(run_dir.glob('terminal-fact-*.json'))), 1)
            sim.guests.corrupt_export.clear()
        self.assertIsNone(sim.status_now()['terminal_failure'])
        return sim, run_dir

    @staticmethod
    def stop_fails(executor, error, times=None, commit=False):
        """``record_batch_stop`` fails, ``times`` over or for ever, either before the registry commits it or after, with only its answer lost."""
        real, seen = executor.client.mutate, []

        def mutate(method, *arguments, **parameters):
            if method != 'record_batch_stop' or (times is not None and len(seen) >= times):
                return real(method, *arguments, **parameters)
            seen.append(arguments)
            if commit:
                real(method, *arguments, **parameters)
            raise error
        executor.client.mutate = mutate
        return seen

    def assertNoSuccessor(self, sim, starts):
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts, 'no second workload')
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)], 'nothing dispatched, and the committed outcome stays')

    def assertReplayedBeforeWork(self, sim, starts):
        """A later controller, with a healthy registry and a healthy transfer, finishes what was left."""
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-later')
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertNoSuccessor(sim, starts)

    def test_an_unavailable_registry_refuses_the_resume_and_the_dispatch_for_a_new_and_for_a_retained_fact(self):
        for retained in (False, True):
            with self.subTest(retained=retained):
                sim, run_dir = self.fixture(retained)
                starts = len(sim.guests.runner_steps('game', 'start'))
                executor, control = sim.controller()
                self.stop_fails(executor, registry_client.RegistryUnavailable('down for this one request'))
                result = executor.resume('operator', control)
                self.assertFalse(result['resumed'], result)
                self.assertEqual(result['code'], run_executor.TERMINAL_FACT_UNACKNOWLEDGED)
                self.assertIsNone(sim.status_now()['terminal_failure'], 'the registry never heard')
                self.assertIsNone(result['checks']['next_run_id'])
                self.assertEqual(len(list(run_dir.glob('terminal-fact-*.json'))), 1, 'written down whatever the registry did')
                done = executor.execute()
                self.assertEqual((done.status, done.code), (run_executor.STOPPED, run_executor.TERMINAL_FACT_UNACKNOWLEDGED), done)
                self.assertEqual(done.search_status, 'stopped_infrastructure_failure')
                self.assertNoSuccessor(sim, starts)
                self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'evidence_disagreement')
                self.assertReplayedBeforeWork(sim, starts)

    def test_a_rejected_stop_refuses_the_same_way(self):
        for retained in (False, True):
            with self.subTest(retained=retained):
                sim, _ = self.fixture(retained)
                starts = len(sim.guests.runner_steps('game', 'start'))
                executor, control = sim.controller()
                self.stop_fails(executor, registry_client.RegistryRejected('lock_timeout', 'the registry would not take it'))
                result = executor.resume('operator', control)
                self.assertEqual((result['resumed'], result['code']), (False, run_executor.TERMINAL_FACT_UNACKNOWLEDGED), result)
                self.assertNoSuccessor(sim, starts)
                self.assertReplayedBeforeWork(sim, starts)

    def test_a_stale_controller_is_told_it_lost_control_and_runs_nothing(self):
        sim, _ = self.fixture()
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        self.stop_fails(executor, registry_client.RegistryRejected('stale_fencing_token', 'another controller holds this'))
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'stale_fencing_token'), result)
        self.assertEqual(executor.execute().status, run_executor.CONTROL_LOST)
        self.assertNoSuccessor(sim, starts)

    def test_one_failed_request_is_retried_before_any_decision_and_the_session_stops(self):
        """The reproduced case: one failure, then a healthy registry for every later request."""
        for retained in (False, True):
            with self.subTest(retained=retained):
                sim, _ = self.fixture(retained)
                starts = len(sim.guests.runner_steps('game', 'start'))
                executor, control = sim.controller()
                seen = self.stop_fails(executor, registry_client.RegistryUnavailable('down for this one request'), times=1)
                result = executor.resume('operator', control)
                self.assertEqual(len(seen), 1)
                self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
                self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
                self.assertNoSuccessor(sim, starts)

    def test_an_answer_lost_after_the_commit_is_not_taken_for_a_stop_that_was_not_made(self):
        sim, _ = self.fixture()
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        seen = self.stop_fails(executor, registry_client.RegistryUnavailable('the answer was lost'), commit=True)
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE, 'it did commit')
        self.assertEqual(len(seen), 2, 'asked again, and refused all the same')
        self.assertEqual(len(set(seen)), 1, 'the same request id, so the registry replays and does not apply it twice')
        self.assertEqual(executor.execute().code, run_executor.TERMINAL_FACT_UNACKNOWLEDGED)
        self.assertNoSuccessor(sim, starts)

    def test_a_stop_not_committed_stays_refused_and_is_replayed_by_the_same_request(self):
        sim, _ = self.fixture()
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        seen = self.stop_fails(executor, registry_client.RegistryUnavailable('never arrived'), times=3)
        self.assertEqual(executor.resume('operator', control)['code'], run_executor.TERMINAL_FACT_UNACKNOWLEDGED)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(len(seen), 2)
        self.assertEqual(executor.execute().code, run_executor.TERMINAL_FACT_UNACKNOWLEDGED, 'the third attempt fails too')
        self.assertEqual(len(set(seen)), 1)
        result = executor.resume('operator again', control)     # the fourth reaches it
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertNoSuccessor(sim, starts)

    def test_a_fact_no_disk_kept_still_refuses_this_controller(self):
        sim, run_dir = self.fixture()
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        self.stop_fails(executor, registry_client.RegistryUnavailable('down'))
        real = do_session.write_new_durable

        def refuse_facts(path, text):
            if 'terminal-fact' in str(path):
                raise OSError('no space left')
            return real(path, text)
        with mock.patch.object(do_session, 'write_new_durable', refuse_facts):
            result = executor.resume('operator', control)
        self.assertEqual(result['code'], run_executor.TERMINAL_FACT_UNACKNOWLEDGED)
        self.assertEqual(list(run_dir.glob('terminal-fact-*.json')), [])
        self.assertEqual(executor.execute().code, run_executor.TERMINAL_FACT_UNACKNOWLEDGED, 'kept in this controller\'s memory')
        self.assertNoSuccessor(sim, starts)

    def test_a_failed_stop_mutation_costs_the_batch_neither_its_wrap_up_nor_its_cleanup(self):
        sim = self.sim_of(self.RULES)
        executor = sim.executor()
        result = executor.execute()
        self.assertEqual(result.search_status, 'confirmed')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        sim.guests.corrupt_export.add('bot.stdout.log')
        self.stop_fails(executor, registry_client.RegistryUnavailable('down'))
        executor.wrap_up(result)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'it never stands between a batch and its cleanup')
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertTrue(any('has not acknowledged the stop fact' in item for item in result.wrap_up_errors), result.wrap_up_errors)
        self.assertEqual(len(list(run_dir.glob('terminal-fact-*.json'))), 1, 'kept for whoever comes next')
        self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'evidence_disagreement')

    def test_a_fact_that_appears_between_runs_stops_the_next_dispatch(self):
        """Nothing returned and nothing resumed: the same controller, about to dispatch, finds a fact beside the run it just committed."""
        sim = self.sim_of(self.RULES)

        def leave_a_fact(point):
            if point == 'after_outcome_commit' and not leave_a_fact.done:
                leave_a_fact.done = True
                row = sim.records()[0]
                _terminal_fact_file(sim, row['run_id'], row['fencing_token'])
        leave_a_fact.done = False
        result = sim.executor(failpoint=leave_a_fact).execute()
        self.assertEqual((result.status, result.code), (run_executor.STOPPED, 'terminal_failure'), result)
        self.assertEqual(result.search_status, 'stopped_infrastructure_failure')
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)


class CorruptSeals(Base):
    """A seal that came back whole with the wrong hash is corrupt bytes, like any other file. A transfer that could not run is no such thing."""
    RULES = {50: sf.slow, 30: sf.slow}

    def fixture(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        path = run_dir / 'bot' / 'bot.stdout.log'
        path.chmod(0o644)
        path.unlink()
        return sim, run_dir

    def assertKept(self, run_dir, facts=1):
        found = sorted(run_dir.glob('terminal-fact-*.json'))
        self.assertEqual(len(found), facts, found)
        fact = json.loads(found[0].read_text())
        receipt = fact['receipts'][0]
        self.assertEqual((fact['role'], receipt['path'], receipt['kind']), ('bot', 'seal.json', 'corrupt'))
        self.assertNotEqual(receipt['expected_sha256'], receipt['actual_sha256'])
        kept = run_dir / receipt['retained_as']
        self.assertEqual(run_executor.sha256_path(kept), receipt['actual_sha256'], 'the bytes themselves are kept, under their own hash')
        self.assertTrue(kept.read_bytes().endswith(b'corrupted in transfer'))
        self.assertEqual(run_executor.sha256_path(run_dir / 'bot' / 'seal.json'), receipt['expected_sha256'], 'the good seal on this disk is what the expected hash names')
        return fact

    def test_a_committed_outcome_stops_the_session_keeps_its_files_and_has_the_report_disagree(self):
        sim, run_dir = self.fixture()
        before = {path.name: path.read_bytes() for path in (run_dir / 'classification.json', run_dir / 'score.json')}
        (run_dir / 'bot' / 'seal.json').chmod(0o644)
        sim.guests.corrupt_export.add('seal.json')
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts)
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS)], 'the outcome stays what was committed')
        self.assertEqual(before, {path.name: path.read_bytes() for path in (run_dir / 'classification.json', run_dir / 'score.json')})
        self.assertKept(run_dir)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertEqual(report['journal_claim']['kind'], 'in_progress')
        self.assertTrue(any('hash mismatch' in str(fact['details']) for fact in report['trials'][0]['hard_facts']))
        self.assertTrue(report['trials'][0]['hard_facts'][-1]['receipts'])
        self.assertIn('Stop fact', capacity_report.render_search(report))

    def test_a_crash_after_the_fact_and_a_restored_transport_do_not_unsay_it(self):
        sim, run_dir = self.fixture()
        sim.guests.corrupt_export.add('seal.json')
        starts = len(sim.guests.runner_steps('game', 'start'))
        executor, control = sim.controller(failpoint=rf.crash_at('after_terminal_fact'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.resume('operator', control)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'only written down so far')
        sim.guests.corrupt_export.clear()
        executor, control = sim.controller(name='controller-c')
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), starts)
        self.assertKept(run_dir)
        self.assertEqual(run_executor.sha256_path(run_dir / 'bot' / 'bot.stdout.log'), json.loads((run_dir / 'bot' / 'seal.json').read_text())['files'][[item['path'] for item in json.loads((run_dir / 'bot' / 'seal.json').read_text())['files']].index('bot.stdout.log')]['sha256'], 'what a working transfer can still bring back, it does')

    def test_at_wrap_up_it_stops_the_session_and_cleanup_still_happens(self):
        sim = self.sim_of(self.RULES)
        executor = sim.executor()
        result = executor.execute()
        self.assertEqual(result.search_status, 'confirmed')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        for name in ('bot/seal.json', 'bot/bot.stdout.log'):
            path = run_dir / name
            path.chmod(0o644)
            path.unlink()
        sim.guests.corrupt_export.add('seal.json')
        executor.wrap_up(result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])
        self.assertEqual(len(list(run_dir.glob('terminal-fact-*.json'))), 1, 'one fact, however many sweeps saw it')
        self.assertEqual(executor._role_inventory(sim.records()[0]['run_id'], 'bot')['status'], 'corrupt', 'not merely absent')
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertEqual(report['journal_claim']['kind'], 'confirmed_observation', 'the journal\'s history stays')

    def test_a_host_only_failing_to_answer_stays_no_fact(self):
        cases = dict(the_transfer_failed=lambda sim: sim.guests.copy_failures.update({('bot', 'get')}))
        for name, arrange in cases.items():
            with self.subTest(name):
                sim, run_dir = self.fixture()
                arrange(sim)
                executor, control = sim.controller()
                result = executor.resume('operator', control)
                self.assertTrue(result['resumed'], result)
                self.assertIsNone(sim.status_now()['terminal_failure'])
                self.assertEqual(list(run_dir.glob('terminal-fact-*.json')), [])

    def test_a_transfer_claiming_success_with_no_file_says_nothing_about_the_seal(self):
        sim, run_dir = self.fixture()
        executor, control = sim.controller()
        real = executor.guests.get

        def get(role, remote, local, timeout_s, on_wait=None):
            if remote.endswith('/seal.json') and role == 'bot':
                return rf.ssh_access.CommandResult(0, '', '')
            return real(role, remote, local, timeout_s, on_wait)
        with mock.patch.object(executor.guests, 'get', get):
            result = executor.resume('operator', control)
        self.assertTrue(result['resumed'], result)
        self.assertEqual(list(run_dir.glob('terminal-fact-*.json')), [])

    def test_a_status_naming_no_seal_hash_says_nothing_either(self):
        sim, run_dir = self.fixture()
        sim.guests.corrupt_export.add('seal.json')
        executor, control = sim.controller()
        real = executor._runner

        def runner(role, step, *arguments, **options):
            answer = real(role, step, *arguments, **options)
            return dict(answer, seal_sha256=None) if step == 'status' else answer
        with mock.patch.object(executor, '_runner', runner):
            result = executor.resume('operator', control)
        self.assertTrue(result['resumed'], result)
        self.assertEqual(list(run_dir.glob('terminal-fact-*.json')), [])

    def test_any_other_corrupt_file_keeps_its_bytes_even_after_a_later_good_transfer(self):
        sim, run_dir = self.fixture()
        sim.guests.corrupt_export.add('bot.stdout.log')
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], 'terminal_failure')
        fact = json.loads(next(run_dir.glob('terminal-fact-*.json')).read_text())
        receipt = fact['receipts'][0]
        self.assertEqual(receipt['path'], 'bot.stdout.log')
        sim.guests.corrupt_export.clear()
        self.assertTrue(executor._recover_role(sim.records()[0]['run_id'], 'bot', lambda: None), 'recovery at wrap-up, with the transfer working')
        self.assertEqual(run_executor.sha256_path(run_dir / 'bot' / 'bot.stdout.log'), receipt['expected_sha256'], 'the good copy arrived')
        self.assertEqual(run_executor.sha256_path(run_dir / receipt['retained_as']), receipt['actual_sha256'], 'and the corrupt one is still here')


def _terminal_fact_file(sim, directory, token, name=None, **changes):
    """The file the executor writes into run ``directory``, with one thing changed. A change to None removes that key."""
    document = dict(schema=cs.TERMINAL_FACT_SCHEMA, session_id=sim.session_id, manifest_sha256=sim.sha, run_id=directory, role='bot', outcome=INFRASTRUCTURE_FAILURE, details=['bot evidence was not fully exported'], fencing_token=token, found_at='2026-10-30T00:00:00Z')
    document.update(changes)
    document = {key: value for key, value in document.items() if value is not None}
    path = sim.run_dir(directory) / (name or 'terminal-fact-%04d-0.json' % token)
    path.write_text(json.dumps(document))
    return path


class ForeignStopRecords(Base):
    """A file in this directory that says a run stopped is believed only as this run's own. Otherwise it stops this controller without an irreversible word to the registry, and no claim stands beside it."""
    RULES = {50: sf.slow, 30: sf.slow}
    OWN_TOKEN = 2      # the controller that returned

    def committed(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_outcome_commit')
        row = sim.records()[0]
        return sim, row['run_id'], row['fencing_token']

    def malformed(self):
        return (('another_session', dict(session_id='foreign-session')),
                ('another_manifest', dict(manifest_sha256='f' * 64)),
                ('another_run', dict(run_id='foreign-run')),
                ('no_session', dict(session_id=None)),
                ('no_manifest', dict(manifest_sha256=None)),
                ('no_run', dict(run_id=None)),
                ('no_role', dict(role=None)),
                ('another_role', dict(role='watchdog')),
                ('no_reason', dict(details=[])),
                ('a_reason_of_no_shape', dict(details='bytes failed')),
                ('no_time', dict(found_at=None)),
                ('no_token', dict(fencing_token=None)),
                ('a_token_of_no_shape', dict(fencing_token='two')),
                ('a_token_of_true', dict(fencing_token=True)),
                ('an_outcome_that_stops_nothing', dict(outcome=PASS)),
                ('another_schema', dict(schema='omega.other/1')),
                ('a_receipt_of_no_shape', dict(receipts='bad')),
                ('a_receipt_with_equal_hashes', dict(receipts=[dict(path='seal.json', expected_sha256='a' * 64, actual_sha256='a' * 64)])),
                ('a_receipt_naming_bytes_that_are_not_there', dict(receipts=[dict(path='seal.json', expected_sha256='a' * 64, actual_sha256='b' * 64, retained_as='corrupt-evidence/bot/seal.json.none')])),
                ('a_receipt_naming_a_path_outside', dict(receipts=[dict(path='seal.json', expected_sha256='a' * 64, actual_sha256='b' * 64, retained_as='../../manifest.json')])))

    def assertUnverifiedStop(self, sim, run_id, result, record):
        self.assertFalse(result['resumed'], result)
        self.assertEqual(result['code'], run_executor.STOP_RECORD_UNVERIFIED, result)
        self.assertIsNone(sim.status_now()['terminal_failure'], 'nothing irreversible on a word that is not this session\'s')
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement', 'and no claim stands beside it')
        row = next(item for item in report['trials'] if item['run_id'] == run_id)
        self.assertEqual(row['hard_facts'], [], 'it is not reported as this run\'s fact')
        self.assertEqual([item['record'] for item in row['unverified_stop_records']], [record])
        self.assertIn(run_id, report['evidence']['trials_with_unverified_stop_records'])
        self.assertIn('Unverified stop record', capacity_report.render_search(report))

    def test_each_wrong_file_stops_the_resume_as_unverified_and_is_no_fact(self):
        for name, change in self.malformed():
            with self.subTest(name):
                sim, run_id, token = self.committed()
                path = _terminal_fact_file(sim, run_id, 2, **change)
                executor, control = sim.controller()
                self.assertEqual(control['fencing_token'], self.OWN_TOKEN)
                self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), path.name)

    def test_unparseable_bytes_are_the_same(self):
        sim, run_id, _ = self.committed()
        path = sim.run_dir(run_id) / 'terminal-fact-0002-0.json'
        path.write_text('{ "schema": "half a')
        executor, control = sim.controller()
        self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), path.name)
        path.write_bytes(b'\xff\xfe not text')
        executor, control = sim.controller(name='controller-c')
        self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), path.name)

    def test_a_stale_fact_is_older_than_the_run_it_names(self):
        sim, run_id, token = self.committed()
        self.assertGreater(token, 0)
        path = _terminal_fact_file(sim, run_id, 0, name='terminal-fact-0000-0.json', fencing_token=0)
        executor, control = sim.controller()
        self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), path.name)

    def test_a_fact_older_than_the_dispatch_token_is_refused_by_what_the_grant_says(self):
        sim, run_id, _ = self.committed()
        grant = sim.run_dir(run_id) / 'grant.json'
        document = json.loads(grant.read_text())
        document['fencing_token'] = 2
        grant.chmod(0o644)
        grant.write_text(json.dumps(document))
        path = _terminal_fact_file(sim, run_id, 1)
        _, problems = cs.stop_records(sim.run_dir(run_id), dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id))
        self.assertEqual([item['record'] for item in problems], [path.name])
        self.assertIn('older than the token', str(problems))

    def test_a_token_newer_than_the_controller_reading_it_is_refused(self):
        """Only a controller knows the current token. A report, pure over files, cannot tell, and withholds its claim all the same."""
        sim, run_id, _ = self.committed()
        _terminal_fact_file(sim, run_id, 99)
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, run_executor.STOP_RECORD_UNVERIFIED), result)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertEqual(capacity_report.build(sim.stack.root)['claim']['kind'], 'evidence_disagreement')

    def test_a_copied_fact_whose_name_does_not_carry_its_token_is_refused(self):
        sim, run_id, _ = self.committed()
        path = _terminal_fact_file(sim, run_id, 2, name='terminal-fact-0001-0.json')
        executor, control = sim.controller()
        self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), path.name)

    def test_a_foreign_execution_record_carrying_a_stop_is_refused_too(self):
        sim, run_id, _ = self.committed()
        run_dir = sim.run_dir(run_id)
        record = json.loads((run_dir / 'execution.json').read_text())
        name = 'execution-reconciled-0002-9.json'
        (run_dir / name).write_text(json.dumps(dict(record, session_id='foreign-session', writer='reconcile', demonstrated_problems=dict(infrastructure=['foreign bytes']), demonstrated_outcome=None, uncertain=[])))
        executor, control = sim.controller()
        self.assertUnverifiedStop(sim, run_id, executor.resume('operator', control), name)

    def test_a_foreign_record_beside_an_uncommitted_run_decides_nothing_for_it(self):
        sim = self.sim_of(self.RULES)
        self.crash(sim, 'after_score_retained')
        run_id = sim.records()[0]['run_id']
        run_dir = sim.run_dir(run_id)
        record = json.loads((run_dir / 'execution.json').read_text())
        name = 'execution-reconciled-0002-9.json'
        (run_dir / name).write_text(json.dumps(dict(record, run_id='foreign-run', writer='reconcile', demonstrated_problems=dict(infrastructure=['foreign bytes']), demonstrated_outcome=dict(outcome=INFRASTRUCTURE_FAILURE, reasons=['foreign']), uncertain=[])))
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, run_executor.STOP_RECORD_UNVERIFIED), result)
        self.assertIsNone(sim.status_now()['terminal_failure'])
        self.assertNotEqual(sim.records()[0]['outcome'], INFRASTRUCTURE_FAILURE, 'its word is not carried')

    def test_a_real_fact_of_this_run_stands_beside_a_foreign_one_and_is_final(self):
        sim, run_id, token = self.committed()
        own = _terminal_fact_file(sim, run_id, token, name='terminal-fact-%04d-0.json' % token)
        foreign = _terminal_fact_file(sim, run_id, 2, name='terminal-fact-0002-7.json', run_id='foreign-run')
        executor, control = sim.controller()
        result = executor.resume('operator', control)
        self.assertEqual((result['resumed'], result['code']), (False, 'terminal_failure'), result)
        self.assertEqual(sim.status_now()['terminal_failure'], INFRASTRUCTURE_FAILURE, 'a known fact is still final')
        row = capacity_report.build(sim.stack.root)['trials'][0]
        self.assertEqual([item['record'] for item in row['hard_facts']], [own.name])
        self.assertEqual([item['record'] for item in row['unverified_stop_records']], [foreign.name])

    def test_removing_the_stray_file_is_all_it_takes_because_nothing_was_said_to_the_registry(self):
        sim, run_id, _ = self.committed()
        path = _terminal_fact_file(sim, run_id, 2, session_id='foreign-session')
        executor, control = sim.controller()
        self.assertEqual(executor.resume('operator', control)['code'], run_executor.STOP_RECORD_UNVERIFIED)
        path.unlink()
        executor, control = sim.controller(name='controller-c')
        self.assertTrue(executor.resume('operator', control)['resumed'])

    def test_a_dispatch_stops_on_a_foreign_file_beside_a_run_it_just_committed(self):
        sim = self.sim_of(self.RULES)

        def leave_a_file(point):
            if point == 'after_outcome_commit' and not leave_a_file.done:
                leave_a_file.done = True
                row = sim.records()[0]
                _terminal_fact_file(sim, row['run_id'], row['fencing_token'], session_id='foreign-session')
        leave_a_file.done = False
        result = sim.executor(failpoint=leave_a_file).execute()
        self.assertEqual((result.status, result.code, result.search_status), (run_executor.STOPPED, run_executor.STOP_RECORD_UNVERIFIED, 'stopped_inconclusive_evidence'), result)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
        self.assertIsNone(sim.status_now()['terminal_failure'])

    def test_every_generation_of_a_runs_own_facts_is_read_and_each_is_hashed(self):
        sim, run_id, token = self.committed()
        first = _terminal_fact_file(sim, run_id, token, name='terminal-fact-%04d-0.json' % token)
        executor, control = sim.controller()
        executor.resume('operator', control)
        second = _terminal_fact_file(sim, run_id, control['fencing_token'], name='terminal-fact-%04d-1.json' % control['fencing_token'])
        facts, unverified = cs.stop_records(sim.run_dir(run_id), dict(session_id=sim.session_id, manifest_sha256=sim.sha, run_id=run_id))
        self.assertEqual(unverified, [])
        self.assertEqual({fact['record']: fact['sha256'] for fact in facts}, {path.name: run_executor.sha256_path(path) for path in (first, second)})

    def test_the_registry_is_told_which_bytes_stopped_it(self):
        sim, run_id, token = self.committed()
        path = _terminal_fact_file(sim, run_id, token)
        executor, control = sim.controller()
        sent = []
        real = executor.client.mutate

        def mutate(method, *arguments, **parameters):
            if method == 'record_batch_stop':
                sent.append(parameters['evidence_ref'])
            return real(method, *arguments, **parameters)
        executor.client.mutate = mutate
        executor.resume('operator', control)
        self.assertEqual(sent, ['runs/%s/%s#sha256:%s' % (run_id, path.name, run_executor.sha256_path(path))])


class RetainedClassifications(Base):
    """Starts from a verdict reached and written, with the controller gone just before the commit."""

    def retained(self, rules=None):
        sim = self.sim_of({25: sf.slow, 5: sf.slow} if rules is None else rules)
        self.crash(sim, 'before_outcome_commit')
        return sim, sim.run_dir(sim.records()[0]['run_id']) / 'classification.json'

    def test_an_unchanged_verdict_is_reused_and_needs_neither_host(self):
        sim, path = self.retained()
        written = path.read_bytes()
        sim.guests.unreachable.update({('bot', 'inspect'), ('bot', 'stop'), ('bot', 'clock')})
        executor, _ = sim.controller()
        executor.collecting = True
        try:
            executor.prepare()
            executor.reconcile('fixture')
        except run_executor.GuestLost:
            pass
        self.assertEqual(sim.records()[0]['outcome'], FAIL)
        self.assertEqual(path.read_bytes(), written)

    def test_every_refused_classification_is_kept_beside_a_refusal(self):
        cases = (('another_run', lambda d: dict(d, run_id='another-run')), ('no_verdict', lambda d: dict(d, verdict=None)), ('unknown_outcome', lambda d: dict(d, verdict=dict(d['verdict'], outcome='MAYBE'))),
                 ('foreign_schema', lambda d: dict(d, schema='omega.something/1')), ('says_pass_over_a_failing_score', lambda d: dict(d, verdict=dict(d['verdict'], outcome=PASS))),
                 ('rests_on_no_score', lambda d: dict(d, verdict=dict(d['verdict'], evidence_ref='runs/x/score.json'))), ('names_another_hash', lambda d: dict(d, verdict=dict(d['verdict'], evidence_ref=d['verdict']['evidence_ref'][:-64] + 'f' * 64))),
                 ('names_another_run', lambda d: dict(d, verdict=dict(d['verdict'], evidence_ref=d['verdict']['evidence_ref'].replace(d['run_id'], 'another-run')))), ('says_it_was_not_scored', lambda d: dict(d, verdict=dict(d['verdict'], scored=False))))
        for name, change in cases:
            with self.subTest(name):
                sim, path = self.retained()
                bad = json.dumps(change(json.loads(path.read_text())), indent=2, sort_keys=True)
                self.overwrite(path, bad)
                self.collect(sim)
                self.stops_at_the_first_run(sim, None)
                self.assertEqual(path.read_text(), bad)
                run_id = sim.records()[0]['run_id']
                self.assertRegex(sim.records()[0]['evidence_ref'], r'^runs/%s/classification-reconciled-\d+-1\.json#sha256:[0-9a-f]{64}$' % run_id)
                report = capacity_report.build(sim.stack.root)
                self.assertFalse(report['evidence']['verified'])

    def test_a_refused_classification_does_not_mask_a_demonstrated_infrastructure_failure(self):
        sim, path = self.retained()
        self.overwrite(path, json.dumps(dict(json.loads(path.read_text()), run_id='another-run')))
        _carry_a_demonstrated_infrastructure_failure(sim, path.parent)
        self.collect(sim)
        self.stops_at_the_first_run(sim, None, INFRASTRUCTURE_FAILURE)

    def test_a_controller_that_dies_after_refusing_leaves_the_next_one_to_refuse_again(self):
        sim, path = self.retained()
        bad = json.dumps(dict(json.loads(path.read_text()), run_id='another-run'))
        self.overwrite(path, bad)
        with self.assertRaises(rf.SimulatedCrash):
            self.collect(sim, failpoint=rf.crash_at('before_outcome_commit'))
        self.assertIsNone(sim.records()[0]['outcome'])
        self.collect(sim, name='controller-c')
        self.stops_at_the_first_run(sim, None)
        self.assertEqual(path.read_text(), bad)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['trials'][0]['outcome'], INCONCLUSIVE)
        self.assertFalse(report['evidence']['verified'])

    def test_a_classification_that_no_longer_parses(self):
        sim, path = self.retained()
        self.overwrite(path, '{"schema":')
        self.collect(sim)
        self.stops_at_the_first_run(sim, None)

    def test_a_score_changed_under_a_classification(self):
        sim, path = self.retained()
        self.overwrite(self.score_path(sim), self.score_path(sim).read_text().replace('"outcome": "FAIL"', '"outcome": "PASS"'))
        self.collect(sim)
        self.stops_at_the_first_run(sim, None)

    def test_a_refused_classification_does_not_mask_a_terminal_fact(self):
        sim = self.sim_of()
        sim.guests.bot_exit = (4, None)
        self.crash(sim, 'before_outcome_commit')
        path = sim.run_dir(sim.records()[0]['run_id']) / 'classification.json'
        self.overwrite(path, json.dumps(dict(json.loads(path.read_text()), run_id='another-run')))
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)


class InterruptedWrites(Base):
    def failing_link(self, name):
        real = do_session.os.link

        def link(source, target):
            if pathlib.Path(target).name == name:
                raise OSError('interrupted')
            return real(source, target)
        return mock.patch.object(do_session.os, 'link', side_effect=link)

    def test_a_score_interrupted_before_it_was_whole_is_never_read_and_cleanup_still_goes_out(self):
        sim = self.sim_of({25: sf.slow})
        with self.failing_link('score.json'):
            sim.executor().run_batch()
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        self.assertFalse((run_dir / 'score.json').exists())
        self.assertEqual(len(list(run_dir.glob('score.json.writing-*'))), 1, 'the refused bytes are kept, under a name nothing reads')
        self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)
        self.assertIn('cleanup_intent', [event['kind'] for event in sim.stack.registry.journal(sim.session_id)])

    def test_a_crash_between_writing_and_promoting_leaves_a_run_to_be_scored_on_return(self):
        sim = self.sim_of()

        def crash(source, target):
            if pathlib.Path(target).name == 'score.json':
                raise rf.SimulatedCrash('mid-write')
            return real(source, target)
        real = do_session.os.link
        with mock.patch.object(do_session.os, 'link', side_effect=crash), self.assertRaises(rf.SimulatedCrash):
            sim.executor().execute()
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], PASS)
        self.assertIsNotNone(sim.score_of(sim.records()[0]['run_id']))

    def test_a_score_cut_short_under_its_final_name_proves_nothing(self):
        sim = self.sim_of()
        self.crash(sim, 'after_execution_record')
        (sim.run_dir(sim.records()[0]['run_id']) / 'score.json').write_text('{"schema": "omega.do-session.run-sc')
        self.collect(sim)
        self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)

    def test_the_writer_never_overwrites(self):
        sim = self.sim_of()
        path = sim.stack.root / 'evidence.txt'
        do_session.write_new_durable(path, 'first')
        with self.assertRaises(FileExistsError):
            do_session.write_new_durable(path, 'second')
        self.assertEqual(path.read_text(), 'first')


class FrozenSource(Base):
    def collect_with(self, sim, source_problems=None):
        checks = []

        def check():
            checks.append(1)
            return source_problems() if source_problems else []

        def build(token):
            return sim.executor(token=token, source_problems=check)
        result, problems = run_cli.collect_and_stop(sim.client, sim.session_id, build, 'operator collect', takeover=True)
        return result, problems, checks

    def collected_without_a_decision(self, sim):
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        self.assertEqual(sim.records()[0]['outcome'], INCOMPLETE)
        self.assertFalse((run_dir / 'score.json').exists(), 'nothing was scored')
        self.assertFalse((run_dir / 'window-proof.json').exists(), 'nothing here for a frozen controller to reuse')
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'], 'it still stops, seals, exports and hands over')
        for role in ('game', 'bot'):
            self.assertTrue((run_dir / role).is_dir(), role)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)

    def test_collect_from_a_mismatched_or_unverifiable_controller_creates_no_decision(self):
        def raises():
            raise ValueError('git is on fire')
        for name, problems in (('other_revision', lambda: ['the controller checkout is not the frozen controller revision']), ('dirty', lambda: ['the controller code has uncommitted changes']), ('unverifiable', raises)):
            with self.subTest(name):
                sim = self.sim_of({25: sf.slow})
                self.crash(sim, 'after_execution_record')
                _, returned, checks = self.collect_with(sim, problems)
                self.assertTrue(checks, 'the check was actually asked')
                self.assertEqual(returned, [])
                self.collected_without_a_decision(sim)

    def test_collect_with_no_source_check_at_all_creates_no_decision(self):
        sim = self.sim_of()
        self.crash(sim, 'after_execution_record')

        def build(token):
            executor = sim.executor(token=token)
            executor.source_problems = None
            return executor
        run_cli.collect_and_stop(sim.client, sim.session_id, build, 'operator collect', takeover=True)
        self.collected_without_a_decision(sim)

    def test_collect_from_the_frozen_controller_classifies_a_natural_end(self):
        sim = self.sim_of()
        self.crash(sim, 'after_execution_record')
        _, returned, checks = self.collect_with(sim)
        self.assertTrue(checks)
        self.assertEqual(returned, [])
        self.assertEqual(sim.records()[0]['outcome'], PASS)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_collect_recovers_a_validated_retained_score_from_any_controller_without_recomputing(self):
        for rules, expected in (({25: sf.slow}, FAIL), ({}, PASS)):
            with self.subTest(expected):
                sim = self.sim_of(rules)
                self.crash(sim, 'after_score_retained')
                written = self.score_path(sim).read_bytes()
                self.collect_with(sim, lambda: ['the controller checkout is not the frozen controller revision'])
                self.assertEqual(sim.records()[0]['outcome'], expected)
                self.assertEqual(self.score_path(sim).read_bytes(), written)
                self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_collect_recovers_a_validated_retained_classification_from_any_controller(self):
        sim = self.sim_of({25: sf.slow})
        self.crash(sim, 'before_outcome_commit')
        self.collect_with(sim, lambda: ['the controller code has uncommitted changes'])
        self.assertEqual(sim.records()[0]['outcome'], FAIL)

    def test_collect_from_any_controller_still_refuses_a_foreign_retained_score(self):
        sim = self.sim_of({25: sf.slow})
        self.crash(sim, 'after_score_retained')
        path = self.score_path(sim)
        self.overwrite(path, _with_inputs(controller_sha='f' * 40)(cs.load_retained(path)))
        self.collect_with(sim, lambda: ['the controller checkout is not the frozen controller revision'])
        self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)

    def test_collect_keeps_terminal_facts_even_from_a_mismatched_controller(self):
        sim = self.sim_of()
        sim.guests.bot_exit = (4, None)
        self.crash(sim, 'after_execution_record')
        self.collect_with(sim, lambda: ['the controller checkout is not the frozen controller revision'])
        self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)
        self.assertIsNotNone(sim.status_now()['cleanup']['requested_at'])

    def test_resume_from_a_mismatched_controller_refuses_before_anything_is_scored(self):
        sim = self.sim_of()
        self.crash(sim, 'after_execution_record')
        executor, control = sim.controller(source_problems=lambda: ['the controller code has uncommitted changes'])
        outcome = executor.resume('operator: resume remaining runs', control)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(outcome['code'], run_executor.SOURCE_CHANGED)
        self.assertFalse((sim.run_dir(sim.records()[0]['run_id']) / 'score.json').exists())

    def test_resume_from_the_frozen_controller_scores_what_collect_never_saw(self):
        sim = self.sim_of({50: sf.slow, 30: sf.slow})
        self.crash(sim, 'after_execution_record')
        executor, control = sim.controller()
        self.assertTrue(executor.resume('operator: resume remaining runs', control)['resumed'])
        self.assertEqual(sim.records()[0]['outcome'], PASS)

    def test_a_checkout_that_changes_during_a_batch_decides_nothing_more(self):
        sim = self.sim_of({50: sf.slow, 30: sf.slow})
        answers = iter([[]] * 5)
        executor = sim.executor(source_problems=lambda: next(answers, ['the controller code has uncommitted changes']))
        result = executor.execute()
        self.assertTrue(any(row['outcome'] == INCONCLUSIVE for row in sim.records()), sim.outcomes())
        last = sim.records()[-1]
        self.assertEqual(last['outcome'], INCONCLUSIVE)
        self.assertEqual(result.search_status, 'stopped_inconclusive_evidence')
        self.assertFalse((sim.run_dir(last['run_id']) / 'score.json').exists())


class Reports(Base):
    def confirmed(self):
        sim = self.sim_of({50: sf.slow, 30: sf.slow})
        sim.executor().execute()
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'confirmed_observation')
        self.assertTrue(report['evidence']['verified'], report['evidence'])
        self.assertEqual(report['claim'], report['journal_claim'])
        self.assertTrue(report['establishes'])
        self.assertTrue(all(row['evidence_problems'] == [] for row in report['trials']))
        return sim

    def withheld(self, sim, index, fragment):
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertIs(report['establishes'], False)
        self.assertIs(report['claim']['confirmed'], False)
        self.assertIsNone(report['claim']['players'])
        self.assertFalse(report['evidence']['verified'])
        self.assertEqual(report['journal_claim']['kind'], 'confirmed_observation', 'history stays, and apart')
        self.assertIn(fragment, ' '.join(report['trials'][index]['evidence_problems']))
        self.assertEqual(report['trials'][index]['outcome'], sim.records()[index]['outcome'], 'the journal\'s own outcome is still there to see')
        text = capacity_report.render_search(report)
        self.assertIn('No evidence-backed claim', text)
        self.assertIn('History only', text)
        self.assertIn('Not verified: ', text)
        self.assertNotEqual(text.split('\n')[2], '**Confirmed 25 players on this rented pair: three valid five-minute passes. An observed candidate, not provider-wide capacity.**')
        self.assertEqual(capacity_report.canonical(report), capacity_report.canonical(capacity_report.build(sim.stack.root)), 'deterministic over contradictory bytes too')
        return report

    def run_dir(self, sim, index=0):
        return sim.run_dir(sim.records()[index]['run_id'])

    def test_a_foreign_score_withholds_the_claim_and_nothing_of_it_is_rendered_as_this_run(self):
        other = self.sim_of({25: sf.slow})
        self.crash(other, 'after_score_retained')
        self.assertEqual(cs.load_retained(self.score_path(other))['outcome'], FAIL, 'a genuine, intact score, and of another tree')
        sim = self.confirmed()
        path = self.score_path(sim)
        self.overwrite(path, self.score_path(other).read_text())
        report = self.withheld(sim, 0, 'score.json')
        row = report['trials'][0]
        self.assertIsNone(row['classification'], 'its classification is not this run\'s')
        self.assertEqual(row['gates'], {})

    def test_a_changed_score_withholds_it(self):
        sim = self.confirmed()
        path = self.score_path(sim, 1)
        self.overwrite(path, path.read_text().replace('"classification": "capacity_failure"', '"classification": "inconclusive_evidence"'))
        self.withheld(sim, 1, 'score.json')

    def test_a_missing_score_withholds_it(self):
        sim = self.confirmed()
        self.score_path(sim, 2).chmod(0o644)
        self.score_path(sim, 2).unlink()
        self.withheld(sim, 2, 'score.json')

    def test_a_changed_or_missing_classification_withholds_it(self):
        for name, change, fragment in (('changed', lambda path: self.overwrite(path, path.read_text() + ' '), 'no longer the file the journal recorded'), ('missing', lambda path: (path.chmod(0o644), path.unlink()), 'is missing')):
            with self.subTest(name):
                sim = self.confirmed()
                change(self.run_dir(sim) / 'classification.json')
                self.withheld(sim, 0, fragment)

    def test_a_changed_proof_or_execution_record_withholds_it(self):
        for name in ('window-proof.json', 'execution.json'):
            with self.subTest(name):
                sim = self.confirmed()
                path = self.run_dir(sim) / name
                self.overwrite(path, path.read_text() + ' ')
                self.withheld(sim, 0, 'score.json')

    def test_a_journal_that_says_otherwise_withholds_it(self):
        sim = self.confirmed()
        journal = sim.stack.root / do_session.JOURNAL
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        row = next(item for item in rows if item.get('kind') == 'outcome' and item.get('run_id', item.get('trial_id')) == sim.records()[1]['run_id'])
        self.assertEqual(row['outcome'], FAIL)
        row['outcome'] = PASS
        journal.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in rows))
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertIn('the journal says PASS', ' '.join(report['trials'][1]['evidence_problems']))

    def test_a_journal_ref_that_names_no_retained_file_withholds_it(self):
        sim = self.confirmed()
        journal = sim.stack.root / do_session.JOURNAL
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        row = next(item for item in rows if item.get('kind') == 'outcome' and item.get('run_id', item.get('trial_id')) == sim.records()[1]['run_id'])
        row['evidence_ref'] = 'somewhere-else'
        journal.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in rows))
        self.assertIn('no retained file', ' '.join(capacity_report.build(sim.stack.root)['trials'][1]['evidence_problems']))

    def test_a_report_of_a_stopped_search_refuses_a_score_the_controller_also_refused(self):
        sim = self.sim_of({25: sf.slow})
        self.crash(sim, 'after_score_retained')
        path = self.score_path(sim)
        self.overwrite(path, _with_inputs(controller_sha='f' * 40)(cs.load_retained(path)))
        self.collect(sim)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['trials'][0]['outcome'], INCONCLUSIVE)
        self.assertEqual(report['journal_claim']['kind'], 'stopped_inconclusive_evidence')
        self.assertEqual(report['claim']['kind'], 'evidence_disagreement')
        self.assertIn('refused', ' '.join(report['trials'][0]['reasons']))

    def test_a_foreign_classification_cannot_finish_a_pending_trial(self):
        sim = self.sim_of({25: sf.starved})
        self.crash(sim, 'before_outcome_commit')
        path = self.run_dir(sim) / 'classification.json'
        self.overwrite(path, json.dumps(dict(json.loads(path.read_text()), run_id='another-run')))
        report = capacity_report.build(sim.stack.root)
        self.assertIsNone(report['trials'][0]['outcome'])
        self.assertFalse(report['evidence']['verified'])

    def test_a_verified_report_with_a_stop_keeps_its_own_claim(self):
        sim = self.sim_of({25: sf.starved})
        sim.executor().execute()
        report = capacity_report.build(sim.stack.root)
        self.assertTrue(report['evidence']['verified'], report['evidence'])
        self.assertEqual(report['claim']['kind'], 'stopped_invalid_load')


if __name__ == '__main__':
    unittest.main()
