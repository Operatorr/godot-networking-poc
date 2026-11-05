"""Whole searches through the real executor, registry, prover and scorer, over a fake guest whose runs leave real-format recorder files.

No verdict here is scripted: each trial's outcome comes from the bytes the fixture wrote, through the production path. Nothing ran, so none of it says anything about any host.
"""
import inspect
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import capacity_report
import capacity_scorer as cs
import measurement_window as mw
import registry
import run_cli
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import search
from search import FAIL, INCOMPLETE, INCONCLUSIVE, INFRASTRUCTURE_FAILURE, INVALID_LOAD, PASS, SearchState


def run_search(case, rules, **options):
    sim = sf.ScoredSim(case, sf.by_target(rules), **options)
    case.addCleanup(rf.make_writable, sim.stack.root)
    sim.ready()
    return sim, sim.executor().execute()


def only_one_start_per_run(case, sim):
    starts = [call for call in sim.guests.calls if call['command'] == 'start' and call['role'] == 'game']
    case.assertEqual(len(starts), len(sim.records()), 'no hidden retry')
    ids = [row['run_id'] for row in sim.records()]
    case.assertEqual(len(ids), len(set(ids)))


class ProductionDefaults(unittest.TestCase):
    def test_the_executors_defaults_are_the_real_scorer_and_the_strict_prover(self):
        parameters = inspect.signature(run_executor.RunExecutor.__init__).parameters
        self.assertIs(parameters['scorer'].default, cs.score)
        self.assertIs(parameters['window_prover'].default, mw.prove)
        self.assertIs(parameters['require_counters'].default, True)

    def test_the_operator_cli_uses_those_defaults_and_cannot_change_them(self):
        environment = dict(transport=lambda path: mock.Mock(), guests=lambda key, directory: mock.Mock(), registry=lambda command: mock.Mock())
        args = mock.Mock(token_file='t', ssh_key='k', session_dir='d', registry_command='c', repository='r')
        manifest = dict(session=dict(id='s'), timing_basis={name: dict(seconds=1) for name in ('process_reset_s', 'recorder_finalization_s', 'per_trial_export_s')})
        with mock.patch.object(run_cli, 'load_session', return_value=(manifest, 'sha')), mock.patch.object(run_executor.provisioner, 'Evidence'), mock.patch.object(run_executor, 'sha256_path', return_value='0' * 64):
            _, _, build = run_cli._executor_factory(args, environment)
            executor = build(1)
        self.assertIs(executor.scorer, cs.score)
        self.assertIs(executor.window_prover, mw.prove)
        self.assertIs(executor.require_counters, True)
        source = inspect.getsource(run_cli)
        for bypass in ('require_counters', 'allow_short_hold', 'scorer=', 'window_prover'):
            self.assertNotIn(bypass, source)

    def test_the_placeholder_manifest_used_by_other_fixtures_cannot_produce_a_pass(self):
        sim = rf.RunSim(self)
        self.addCleanup(rf.make_writable, sim.stack.root)
        self.assertNotEqual(sim.manifest['telemetry_schema']['id'], mw.schema()['id'])


class EverySearchEndpoint(unittest.TestCase):
    def outcomes(self, sim):
        return [item[2] for item in sim.outcomes()]

    def test_a_confirmed_candidate(self):
        sim, result = run_search(self, {50: sf.slow, 30: sf.slow})
        self.assertEqual((result.status, result.search_status), (run_executor.FINISHED, 'confirmed'))
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS), ('coarse', 50, FAIL), ('refine', 30, FAIL), ('confirm', 25, PASS), ('confirm', 25, PASS), ('confirm', 25, PASS)])
        only_one_start_per_run(self, sim)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['claim']['kind'], 'confirmed_observation')
        self.assertEqual(report['claim']['players'], 25)
        self.assertIn('not provider-wide', report['claim']['statement'])
        for row in sim.records():
            self.assertEqual(sim.score_of(row['run_id'])['outcome'], row['outcome'])
            self.assertIn('score.json#sha256:', json.loads((sim.run_dir(row['run_id']) / 'classification.json').read_text())['verdict']['evidence_ref'])

    def test_first_rung_failure_then_five_failing_is_no_passing_target_and_never_zero(self):
        sim, result = run_search(self, {25: sf.slow, 5: sf.slow})
        self.assertEqual(result.search_status, 'no_passing_target')
        self.assertEqual(sim.outcomes(), [('coarse', 25, FAIL), ('refine', 5, FAIL)])
        claim = capacity_report.build(sim.stack.root)['claim']
        self.assertEqual(claim['kind'], 'no_passing_target_at_resolution')
        self.assertIsNone(claim['players'])
        self.assertIsNone(claim['lower_bound'], 'not a capacity of zero')
        self.assertIn('not proof that no smaller population', claim['statement'].lower())

    def test_first_rung_failure_can_still_find_a_candidate_under_it(self):
        sim, result = run_search(self, {25: sf.slow, 10: sf.slow})
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual(sim.outcomes(), [('coarse', 25, FAIL), ('refine', 5, PASS), ('refine', 10, FAIL), ('confirm', 5, PASS), ('confirm', 5, PASS), ('confirm', 5, PASS)])

    def test_every_refinement_passing_confirms_the_top_of_the_bracket(self):
        sim, result = run_search(self, {50: sf.slow})
        self.assertEqual(result.search_status, 'confirmed')
        self.assertEqual([item[1] for item in sim.outcomes() if item[0] == 'refine'], [30, 35, 40, 45])
        self.assertEqual({item[1] for item in sim.outcomes() if item[0] == 'confirm'}, {45})

    def test_a_failed_confirmation_stays_unconfirmed_with_no_replacement(self):
        for failing in (1, 2, 3):
            with self.subTest(repetition=failing):
                seen = []

                def confirmation(tree):
                    seen.append(1)
                    if len(seen) == failing:
                        sf.slow(tree)
                sim, result = run_search(self, {50: sf.slow, 30: sf.slow, ('confirm', 25): confirmation})
                self.assertEqual((result.status, result.search_status), (run_executor.FINISHED, 'unconfirmed_variable'))
                confirmations = [item[2] for item in sim.outcomes() if item[0] == 'confirm']
                self.assertEqual(confirmations, [PASS] * (failing - 1) + [FAIL], 'stops there, with nothing after it')
                only_one_start_per_run(self, sim)
                claim = capacity_report.build(sim.stack.root)['claim']
                self.assertEqual((claim['kind'], claim['candidate'], claim['confirmed']), ('unconfirmed_variable', 25, False))

    def test_stopping_outcomes_end_the_batch_in_every_phase(self):
        stops = ((sf.starved, INVALID_LOAD, 'stopped_invalid_load'), (sf.foggy, INCONCLUSIVE, 'stopped_inconclusive_evidence'), (sf.rebooted, INFRASTRUCTURE_FAILURE, 'stopped_infrastructure_failure'))
        phases = (({50: None}, 'coarse'), ({50: sf.slow, 30: None}, 'refine'), ({50: sf.slow, 30: sf.slow, ('confirm', 25): None}, 'confirm'))
        for change, outcome, status in stops:
            for template, phase in phases:
                with self.subTest(outcome=outcome, phase=phase):
                    rules = {key: (change if value is None else value) for key, value in template.items()}
                    sim, result = run_search(self, rules)
                    self.assertEqual((result.status, result.search_status), (run_executor.STOPPED, status))
                    rows = sim.outcomes()
                    self.assertEqual(rows[-1][2], outcome)
                    self.assertEqual(rows[-1][0], phase)
                    only_one_start_per_run(self, sim)
                    report = capacity_report.build(sim.stack.root)
                    self.assertFalse(report['claim']['confirmed'])
                    self.assertIn('No capacity established', report['claim']['statement'])
                    self.assertIn('highest one-minute pass was 25', report['claim']['statement'], 'a stop does not erase what was already recorded')

    def test_a_stop_at_the_first_rung_says_only_that(self):
        sim, result = run_search(self, {25: sf.starved})
        self.assertEqual(result.search_status, 'stopped_invalid_load')
        self.assertEqual(sim.outcomes(), [('coarse', 25, INVALID_LOAD)])
        self.assertNotIn('highest', capacity_report.build(sim.stack.root)['claim']['statement'])

    def test_a_ramp_failure_with_a_valid_generator_and_a_proven_overrun_opens_the_bracket(self):
        def ramp(tree):
            sf.ramp_failure(tree, 'readiness_timeout', tree.timeline.target - 1)
            sf.ramp_slow_ticks(tree, 2)
        sim, result = run_search(self, {50: ramp, 30: sf.slow})
        self.assertEqual(sim.outcomes()[1], ('coarse', 50, FAIL))
        self.assertEqual(result.search_status, 'confirmed')

    def test_a_ramp_timeout_with_no_failure_on_record_stops_and_establishes_nothing(self):
        sim, result = run_search(self, {50: lambda tree: sf.ramp_failure(tree, 'readiness_timeout', tree.timeline.target - 1)})
        self.assertEqual(sim.outcomes()[-1], ('coarse', 50, INCONCLUSIVE))
        self.assertEqual(result.search_status, 'stopped_inconclusive_evidence')

    def test_a_server_disconnect_in_the_window_advances_the_search_as_a_capacity_failure(self):
        sim, result = run_search(self, {50: lambda tree: sf.lose_bot(tree, 2, 30, cs.REASON_KICKED), 30: sf.slow})
        self.assertEqual(sim.outcomes()[1], ('coarse', 50, FAIL))
        score = sim.score_of(sim.records()[1]['run_id'])
        self.assertIn('bot_errors', score['inputs']['proof_reasons'], 'the prover\'s generator-labelled reason did not decide this')
        self.assertEqual(score['validity']['verdict'], cs.VALID)
        self.assertEqual(result.search_status, 'confirmed')

    def test_a_game_process_that_crashed_is_a_capacity_failure_through_the_real_path(self):
        sim = sf.ScoredSim(self, sf.by_target({25: lambda tree: (sf.game_died(tree, 30), sf.bots_time_out_after_game_died(tree, [1], 35))}))
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        sim.guests.game_crash_after_s = 20
        sim.guests.game_exit = (101, None)
        executor = sim.executor()
        result = executor.execute()
        first = sim.records()[0]
        self.assertEqual(first['outcome'], FAIL, sim.score_of(first['run_id'])['reasons'])
        self.assertEqual(sim.score_of(first['run_id'])['attribution']['game_exit']['kind'], 'server_panic')
        self.assertEqual(sim.outcomes()[1][:2], ('refine', 5))
        self.assertIsNotNone(result.search_status)

    def test_a_swarm_that_crashed_is_invalid_load_with_no_score_consulted(self):
        sim = sf.ScoredSim(self)
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        sim.guests.bot_exit = (4, None)
        result = sim.executor().execute()
        self.assertEqual(result.search_status, 'stopped_invalid_load')
        self.assertFalse((sim.run_dir(sim.records()[0]['run_id']) / 'score.json').exists())

    def test_the_whole_ladder_passing_reports_at_least_500_at_the_cap(self):
        sim, result = run_search(self, {}, cap_s=7 * 3600)
        self.assertEqual((result.status, result.search_status), (run_executor.FINISHED, 'confirmed_search_cap_reached'))
        rows = sim.outcomes()
        self.assertEqual(len(rows), 23)
        self.assertEqual([item[1] for item in rows[:20]], list(range(25, 501, 25)))
        self.assertEqual(rows[20:], [('confirm', 500, PASS)] * 3)
        only_one_start_per_run(self, sim)
        claim = capacity_report.build(sim.stack.root)['claim']
        self.assertEqual((claim['kind'], claim['lower_bound'], claim['search_cap_reached']), ('at_least_search_cap', 500, True))
        self.assertIsNone(claim['players'], 'no ceiling was discovered')
        self.assertIn('not a discovered ceiling', claim['statement'])


class InterruptionsAndReturns(unittest.TestCase):
    def sim_of(self, rules=None):
        sim = sf.ScoredSim(self, sf.by_target({50: sf.slow, 30: sf.slow} if rules is None else rules))
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        return sim

    def resume(self, sim, **options):
        executor, control = sim.controller(**options)
        return executor, executor.resume('operator: resume remaining runs', control)

    def crash(self, sim, point):
        executor = sim.executor(failpoint=rf.crash_at(point))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()

    def test_a_cut_measurement_is_incomplete_and_its_dependent_branch_stays_undecidable(self):
        sim = self.sim_of()
        self.crash(sim, 'after_running_commit')
        executor, outcome = self.resume(sim)
        self.assertEqual(sim.records()[0]['outcome'], INCOMPLETE)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(outcome['code'], 'no_eligible_untouched_work')
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1, 'never replayed')
        state = run_executor.state_from_records(sim.session_id, sim.records())
        self.assertEqual(search.derive(state)['status'], 'undecidable_incomplete_predecessor')
        claim = search.capacity_claim(state)
        self.assertEqual(claim['kind'], 'undecidable_incomplete_predecessor')
        self.assertIn('neither inferred nor replayed', claim['statement'])

    def test_a_natural_end_is_scored_on_return_from_what_it_left(self):
        for point in ('after_stop', 'after_seal', 'after_execution_record'):
            with self.subTest(point=point):
                sim = self.sim_of()
                self.crash(sim, point)
                _, outcome = self.resume(sim)
                self.assertEqual(sim.records()[0]['outcome'], PASS, point)
                self.assertTrue(outcome['resumed'], outcome)
                self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)
                self.assertEqual(sim.score_of(sim.records()[0]['run_id'])['classification'], cs.VALID_PASS)

    def test_a_retained_score_is_read_and_never_recomputed_or_replaced(self):
        sim = self.sim_of()
        self.crash(sim, 'after_score_retained')
        run_id = sim.records()[0]['run_id']
        path = sim.run_dir(run_id) / 'score.json'
        written = path.read_bytes()
        calls = []
        executor, control = sim.controller()
        executor.scorer = lambda evidence: calls.append(evidence) or dict(outcome=FAIL, evidence_ref='x', score=None)
        executor.resume('operator', control)
        self.assertEqual(sim.records()[0]['outcome'], PASS)
        self.assertEqual(calls, [], 'not scored twice')
        self.assertEqual(path.read_bytes(), written)

    def test_a_retained_score_survives_the_hosts_being_unreachable_on_return(self):
        sim = self.sim_of({25: sf.slow})
        self.crash(sim, 'after_score_retained')
        sim.guests.unreachable.update({('bot', 'inspect'), ('bot', 'stop'), ('bot', 'clock')})
        executor, control = sim.controller()
        executor.collecting = True
        try:
            executor.prepare()
            executor.reconcile('fixture')
        except run_executor.GuestLost:
            pass
        self.assertEqual(sim.records()[0]['outcome'], FAIL, 'the failure on file is not lost to a host going away')

    def test_a_verdict_committed_just_before_a_crash_is_kept(self):
        sim = self.sim_of({25: sf.slow})
        self.crash(sim, 'before_outcome_commit')
        self.assertIsNone(sim.records()[0]['outcome'])
        path = sim.run_dir(sim.records()[0]['run_id']) / 'classification.json'
        written = path.read_bytes()
        self.resume(sim)
        self.assertEqual(sim.records()[0]['outcome'], FAIL)
        self.assertEqual(path.read_bytes(), written)

    def test_a_crash_after_the_commit_keeps_the_terminal_fact_and_adds_no_run(self):
        sim = self.sim_of({25: sf.starved})
        self.crash(sim, 'after_outcome_commit')
        self.assertEqual(sim.records()[0]['outcome'], INVALID_LOAD)
        executor, outcome = self.resume(sim)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(len(sim.records()), 1)
        self.assertEqual(len(sim.guests.runner_steps('game', 'start')), 1)

    def test_an_interrupted_confirmation_leaves_only_its_untouched_siblings_and_never_confirms(self):
        sim = self.sim_of()
        count = dict(n=0)

        def in_confirmation(name):
            if name == 'after_running_commit':
                count['n'] += 1
                if count['n'] == 4:
                    raise rf.SimulatedCrash(name)
        executor = sim.executor(failpoint=in_confirmation)
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        resumed, outcome = self.resume(sim)
        self.assertTrue(outcome['resumed'], outcome)
        self.assertIn('-confirm-n025-r2', outcome['next_run_id'])
        result = resumed.execute()
        self.assertEqual(result.search_status, 'unconfirmed_partial')
        self.assertEqual([item[2] for item in sim.outcomes() if item[0] == 'confirm'], [INCOMPLETE, PASS, PASS])
        only_one_start_per_run(self, sim)
        claim = capacity_report.build(sim.stack.root)['claim']
        self.assertEqual((claim['kind'], claim['confirmed']), ('unconfirmed_partial', False))
        self.assertIn('2 of 3', claim['statement'])

    def test_a_terminal_failure_refuses_every_later_resume(self):
        sim = self.sim_of({25: sf.rebooted})
        sim.executor().execute()
        self.assertEqual(sim.records()[0]['outcome'], INFRASTRUCTURE_FAILURE)
        _, outcome = self.resume(sim)
        self.assertFalse(outcome['resumed'])
        self.assertEqual(len(sim.records()), 1)

    def test_time_running_out_is_a_partial_search_that_keeps_its_results(self):
        sim = self.sim_of({})
        ran = []

        def third_selection(name):
            if name == 'after_selection':
                ran.append(1)
                if len(ran) == 3:
                    raise rf.SimulatedCrash(name)
        executor = sim.executor(failpoint=third_selection)
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        c = run_executor.session_clock.parse(sim.status_now()['cleanup_c_utc'])
        sim.sleep(c - sim.clock.wall() - 1800)
        token = sim.client.acquire(sim.session_id, takeover=True)['fencing_token']
        state = run_executor.state_from_records(sim.session_id, sim.records())
        sim.client.mutate('record_resume', session_id=sim.session_id, fencing_token=token, operator_request_ref='fixture',
                          checks={**{name: True for name in registry.RESUME_REQUIRED_CHECKS}, 'manifest_sha256': sim.sha, 'next_run_id': search.next_trial(state).run_id})
        result = sim.executor(token=token).execute()
        self.assertEqual((result.status, result.search_status), (run_executor.PARTIAL, 'partial_time_exhausted'))
        self.assertEqual(sim.outcomes(), [('coarse', 25, PASS), ('coarse', 50, PASS)], 'nothing is dispatched that cannot fit')
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['status'], 'partial_time_exhausted')
        self.assertEqual(report['claim']['kind'], 'partial_time_exhausted')
        self.assertIn('highest one-minute pass was 50', report['claim']['statement'])
        self.assertEqual(report['observations']['highest_exploration_pass'], 50)
        self.assertEqual(len(report['trials']), 2, 'a selection never dispatched is no trial')

    def test_a_scorer_that_breaks_is_inconclusive_and_the_outcome_still_commits(self):
        sim = self.sim_of()
        executor = sim.executor()

        def broken(evidence):
            raise KeyError('a surprising file')
        executor.scorer = broken
        result = executor.execute()
        self.assertEqual(sim.records()[0]['outcome'], INCONCLUSIVE)
        self.assertEqual(result.search_status, 'stopped_inconclusive_evidence')

    def test_a_score_holding_a_credential_is_not_retained(self):
        sim = self.sim_of()
        executor = sim.executor()

        def leaking(evidence):
            answer = cs.score(evidence)
            answer['score']['diagnostics']['note'] = 'dop_v1_' + 'a' * 64
            return answer
        executor.scorer = leaking
        executor.execute()
        row = sim.records()[0]
        self.assertEqual(row['outcome'], INCONCLUSIVE)
        self.assertFalse((sim.run_dir(row['run_id']) / 'score.json').exists())

    def test_a_rendering_lost_to_a_crash_is_written_again_and_the_score_is_not(self):
        sim = self.sim_of()
        self.crash(sim, 'after_score_retained')
        run_dir = sim.run_dir(sim.records()[0]['run_id'])
        written = (run_dir / 'score.json').read_bytes()
        report = run_dir / capacity_report.RUN_REPORT_FILE
        report.chmod(0o644)
        report.unlink()
        self.resume(sim)
        self.assertTrue(report.exists())
        self.assertEqual((run_dir / 'score.json').read_bytes(), written)

    def test_a_retained_score_that_no_longer_reads_proves_nothing(self):
        sim = self.sim_of()
        self.crash(sim, 'after_score_retained')
        run_id = sim.records()[0]['run_id']
        path = sim.run_dir(run_id) / 'score.json'
        path.chmod(0o644)
        path.write_text('{"schema": "broken"}')
        self.resume(sim)
        self.assertNotEqual(sim.records()[0]['outcome'], PASS)


class WrapUp(unittest.TestCase):
    def test_a_finished_batch_retains_a_report_that_regenerates_exactly_and_still_requests_cleanup(self):
        sim, result = run_search(self, {50: sf.slow, 30: sf.slow})
        sim.executor().wrap_up(result)
        directory = sim.stack.root / 'execution'
        retained = sorted(directory.glob('capacity-report-*.json'))
        self.assertEqual(len(retained), 1)
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(retained[0].read_text(), capacity_report.canonical(report))
        self.assertEqual(retained[0].with_suffix('.md').read_text(), capacity_report.render_search(report))
        kinds = [event['kind'] for event in sim.stack.registry.journal(sim.session_id)]
        self.assertIn('cleanup_intent', kinds)
        for row in sim.records():
            self.assertTrue((sim.run_dir(row['run_id']) / capacity_report.RUN_REPORT_FILE).exists())

    def test_a_report_that_cannot_be_written_does_not_stand_in_the_way_of_cleanup(self):
        sim, result = run_search(self, {25: sf.starved})
        executor = sim.executor()
        with mock.patch.object(capacity_report, 'build', side_effect=OSError('disk full')):
            executor.wrap_up(result)
        kinds = [event['kind'] for event in sim.stack.registry.journal(sim.session_id)]
        self.assertIn('cleanup_intent', kinds)
        self.assertIsNone(result.wrap_up_error)

    def test_the_cli_regenerates_the_same_bytes_from_a_session_directory(self):
        sim, result = run_search(self, {25: sf.slow, 5: sf.slow})
        out = pathlib.Path(tempfile.mkdtemp(prefix='omega-report-'))
        self.addCleanup(shutil.rmtree, out, True)
        self.assertEqual(capacity_report.main(['--session-dir', str(sim.stack.root), '--out', str(out / 'a')]), 0)
        self.assertEqual(capacity_report.main(['--session-dir', str(sim.stack.root), '--out', str(out / 'b')]), 0)
        for name in ('capacity-report.json', 'capacity-report.md'):
            self.assertEqual((out / 'a' / name).read_bytes(), (out / 'b' / name).read_bytes())
        text = (out / 'a' / 'capacity-report.md').read_text()
        self.assertIn('No passing target at the search resolution', text)
        self.assertIn('33.3 ms', text)

    def test_a_tampered_manifest_cannot_produce_a_report(self):
        sim, result = run_search(self, {25: sf.starved})
        path = sim.stack.root / 'manifest.json'
        document = json.loads(path.read_text())
        document['session']['owner'] = 'someone else'
        path.chmod(0o644)
        path.write_text(json.dumps(document))
        with self.assertRaises(Exception):
            capacity_report.build(sim.stack.root)

    def test_a_journal_a_crash_left_behind_does_not_make_a_terminal_fact_pending(self):
        sim = sf.ScoredSim(self, sf.by_target({25: sf.starved}))
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=rf.crash_at('after_outcome_commit')).execute()
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['status'], 'stopped_invalid_load')
        self.assertEqual(report['trials'][0]['outcome'], INVALID_LOAD)

    def test_a_selection_never_dispatched_is_not_a_trial(self):
        sim = sf.ScoredSim(self)
        self.addCleanup(rf.make_writable, sim.stack.root)
        sim.ready()
        executor = sim.executor(failpoint=rf.crash_at('after_selection'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        report = capacity_report.build(sim.stack.root)
        self.assertEqual(report['trials'], [])
        self.assertEqual(report['status'], 'in_progress')
        self.assertIn('not finished', report['claim']['statement'])


class EveryLegalPath(unittest.TestCase):
    """Each of the 401 leaves of the finite graph, with no process and no file: the claim each ending may make."""

    def leaves(self):
        found = []

        def walk(state):
            trial = search.next_trial(state)
            if trial is None:
                found.append(state)
                return
            for outcome in search.ADVANCING:
                walk(search.record_outcome(search.dispatch(state, trial), trial.run_id, outcome, 'fixture:' + trial.run_id))
        walk(SearchState('c'))
        return found

    def test_every_ending_claims_only_what_it_showed(self):
        leaves = self.leaves()
        self.assertEqual(len(leaves), 401)
        seen = set()
        for state in leaves:
            derived, claim, facts = search.derive(state), search.capacity_claim(state), search.observations(state)
            seen.add(claim['kind'])
            self.assertLessEqual(facts['trials'], search.MAX_TRIALS_PER_CONDITION)
            self.assertEqual(facts['retries'], 0)
            confirm = [record for record in state.records if record.trial.phase == search.CONFIRM]
            self.assertLessEqual(len(confirm), search.CONFIRMATIONS)
            if claim['confirmed']:
                self.assertEqual([record.outcome for record in confirm], [PASS] * 3)
                self.assertEqual(len({record.trial.target for record in confirm}), 1)
            if claim['kind'] == 'at_least_search_cap':
                self.assertEqual(claim['lower_bound'], search.COARSE_MAX)
                self.assertEqual(state.records[19].trial.target, 500)
            elif claim['kind'] == 'confirmed_observation':
                self.assertLess(claim['players'], search.COARSE_MAX)
                self.assertIsNotNone(facts['lowest_failure_above_it'], 'a confirmed value below the cap has a failure above it')
            elif claim['kind'] == 'no_passing_target_at_resolution':
                self.assertIsNone(facts['highest_exploration_pass'])
                self.assertEqual([record.trial.target for record in state.records], [25, 5])
            else:
                self.assertEqual(claim['kind'], 'unconfirmed_variable')
                self.assertEqual(confirm[-1].outcome, FAIL)
            self.assertNotEqual(claim.get('players'), 0)
            self.assertNotEqual(claim.get('lower_bound'), 0)
            self.assertIn(derived['status'], run_executor.SEARCH_ENDINGS)
        self.assertEqual(seen, {'at_least_search_cap', 'confirmed_observation', 'no_passing_target_at_resolution', 'unconfirmed_variable'})

    def test_a_failure_at_500_refines_inside_the_top_bracket(self):
        state = SearchState('c')
        for outcome in [PASS] * 19 + [FAIL]:
            trial = search.next_trial(state)
            state = search.record_outcome(search.dispatch(state, trial), trial.run_id, outcome, 'fixture')
        trial = search.next_trial(state)
        self.assertEqual((trial.phase, trial.target), ('refine', 480))

    def test_an_incomplete_at_every_position_ends_it_or_leaves_only_siblings(self):
        for prefix, expected in (([], 'undecidable_incomplete_predecessor'), ([PASS], 'undecidable_incomplete_predecessor'), ([PASS, FAIL], 'undecidable_incomplete_predecessor'), ([PASS, FAIL, PASS], 'undecidable_incomplete_predecessor')):
            state = SearchState('c')
            for outcome in prefix:
                trial = search.next_trial(state)
                state = search.record_outcome(search.dispatch(state, trial), trial.run_id, outcome, 'fixture')
            trial = search.next_trial(state)
            state = search.record_outcome(search.dispatch(state, trial), trial.run_id, INCOMPLETE)
            derived = search.derive(state)
            self.assertEqual(derived['status'], expected)
            self.assertIsNone(derived['next'], 'neither inferred nor replayed')
            self.assertFalse(search.capacity_claim(state)['confirmed'])

    def test_passes_recorded_before_a_stop_are_observations_and_never_a_capacity(self):
        state = SearchState('c')
        for outcome in [PASS, PASS, FAIL, FAIL, PASS, INVALID_LOAD]:
            trial = search.next_trial(state)
            state = search.record_outcome(search.dispatch(state, trial), trial.run_id, outcome, 'fixture')
        facts, claim = search.observations(state), search.capacity_claim(state)
        self.assertEqual((facts['highest_exploration_pass'], facts['lowest_failure_above_it']), (50, 55))
        self.assertEqual(facts['confirmations']['passed'], 1)
        self.assertEqual(facts['confirmations']['stopped'], 1)
        self.assertEqual(claim['kind'], 'stopped_invalid_load')
        self.assertIsNone(claim['players'])

    def test_a_pending_confirmation_claims_nothing(self):
        state = SearchState('c')
        for outcome in [PASS, FAIL, FAIL]:
            trial = search.next_trial(state)
            state = search.record_outcome(search.dispatch(state, trial), trial.run_id, outcome, 'fixture')
        state = search.dispatch(state, search.next_trial(state))
        claim = search.capacity_claim(state)
        self.assertEqual(claim['kind'], 'awaiting_confirmation_outcome')
        self.assertFalse(claim['confirmed'])
        self.assertEqual(search.observations(state)['confirmations']['pending'], 1)


if __name__ == '__main__':
    unittest.main()
