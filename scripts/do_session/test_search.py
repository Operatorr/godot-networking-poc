"""Every finite search branch, count ceiling and result label, with no provider or network."""
import unittest

import search
from search import (PASS, FAIL, INVALID_LOAD, INFRASTRUCTURE_FAILURE, INCONCLUSIVE, INCOMPLETE,
                    SearchState, TrialRecord, derive, dispatch, legal_paths, next_trial, record_outcome)


def play(outcomes, condition='c'):
    """Dispatch the legal next trial and record each outcome in order; return the state."""
    state = SearchState(condition)
    for outcome in outcomes:
        trial = next_trial(state)
        assert trial is not None, 'no legal next trial before outcome ' + outcome
        state = record_outcome(dispatch(state, trial), trial.run_id, outcome)
    return state


class CoarseAscentTests(unittest.TestCase):
    def test_first_trial_is_25_for_60_seconds(self):
        trial = next_trial(SearchState('c'))
        self.assertEqual((trial.phase, trial.target, trial.hold_s, trial.ordinal), ('coarse', 25, 60, 1))
        self.assertEqual(trial.run_id, 'c-t01-coarse-n025-r1')
        self.assertEqual(trial.predecessors, ())

    def test_pass_advances_by_25_with_predecessor(self):
        state = play([PASS])
        trial = next_trial(state)
        self.assertEqual((trial.target, trial.ordinal), (50, 2))
        self.assertEqual(trial.predecessors, ('c-t01-coarse-n025-r1',))

    def test_all_coarse_pass_goes_straight_to_confirmation_at_500(self):
        state = play([PASS] * 20)
        trial = next_trial(state)
        self.assertEqual((trial.phase, trial.target, trial.hold_s, trial.ordinal), ('confirm', 500, 300, 21))
        full = play([PASS] * 23)
        derived = derive(full)
        self.assertEqual(derived['status'], 'confirmed_search_cap_reached')
        self.assertEqual(derived['result'], dict(kind='at_least', candidate=500, search_cap_reached=True))
        self.assertIsNone(derived['next'])
        self.assertEqual(derived['counts']['total'], 23)

    def test_cannot_dispatch_a_trial_that_is_not_the_legal_next(self):
        state = play([PASS])
        rogue = search.Trial('c-t02-coarse-n100-r1', 2, 'coarse', 100, 1, 60, ())
        with self.assertRaises(search.SearchError):
            dispatch(state, rogue)


class RefinementTests(unittest.TestCase):
    def test_first_rung_failure_refines_from_5(self):
        state = play([FAIL])
        trial = next_trial(state)
        self.assertEqual((trial.phase, trial.target, trial.ordinal), ('refine', 5, 2))
        self.assertEqual(derive(state)['bracket'], dict(last_pass=0, first_fail=25))

    def test_even_5_failing_reports_no_passing_target(self):
        derived = derive(play([FAIL, FAIL]))
        self.assertEqual(derived['status'], 'no_passing_target')
        self.assertIn('not proof that no smaller population', derived['detail'])
        self.assertIsNone(derived['next'])

    def test_refinement_stops_at_first_failure_and_confirms_last_pass(self):
        # 25 pass, 50 fail -> 30 pass, 35 fail -> confirm 30
        state = play([PASS, FAIL, PASS, FAIL])
        trial = next_trial(state)
        self.assertEqual((trial.phase, trial.target, trial.repetition), ('confirm', 30, 1))
        self.assertIn('c-t02-coarse-n050-r1', trial.predecessors)
        self.assertIn('c-t03-refine-n030-r1', trial.predecessors)
        self.assertIn('c-t04-refine-n035-r1', trial.predecessors)

    def test_refinement_failing_immediately_confirms_the_coarse_pass(self):
        state = play([PASS, FAIL, FAIL])
        self.assertEqual(next_trial(state).target, 25)

    def test_four_refinement_passes_confirm_p_plus_20(self):
        state = play([PASS] * 19 + [FAIL] + [PASS] * 4)
        trial = next_trial(state)
        self.assertEqual((trial.phase, trial.target, trial.ordinal), ('confirm', 495, 25))
        self.assertEqual([t.target for t in (r.trial for r in state.records) if t.phase == 'refine'],
                         [480, 485, 490, 495])


class ConfirmationTests(unittest.TestCase):
    def test_three_passes_confirm_candidate(self):
        derived = derive(play([PASS, FAIL, FAIL, PASS, PASS, PASS]))
        self.assertEqual(derived['status'], 'confirmed')
        self.assertEqual(derived['result'], dict(kind='confirmed', candidate=25, search_cap_reached=False))
        self.assertEqual(derived['counts'], dict(coarse=2, refine=1, confirm=3, total=6))

    def test_confirmation_failure_is_unconfirmed_variable_without_replacement(self):
        for reps in ([FAIL], [PASS, FAIL], [PASS, PASS, FAIL]):
            derived = derive(play([PASS, FAIL, FAIL] + reps))
            self.assertEqual(derived['status'], 'unconfirmed_variable', reps)
            self.assertIsNone(derived['next'], 'no replacement or descending sweep after ' + str(reps))
            self.assertEqual(derived['result']['candidate'], 25)
            self.assertEqual(derived['bracket'], dict(last_pass=25, first_fail=50))

    def test_incomplete_confirmation_leaves_independent_reps_eligible_but_set_partial(self):
        state = play([PASS, FAIL, FAIL])
        first = next_trial(state)
        state = record_outcome(dispatch(state, first), first.run_id, INCOMPLETE)
        second = next_trial(state)
        self.assertEqual((second.phase, second.repetition), ('confirm', 2))
        state = record_outcome(dispatch(state, second), second.run_id, PASS)
        third = next_trial(state)
        state = record_outcome(dispatch(state, third), third.run_id, PASS)
        derived = derive(state)
        self.assertEqual(derived['status'], 'unconfirmed_partial')
        self.assertEqual(derived['result'], dict(kind='unconfirmed_partial', candidate=25, passes=2))


class StoppingOutcomeTests(unittest.TestCase):
    def test_stopping_outcomes_end_the_batch_without_capacity(self):
        expected = {INVALID_LOAD: 'stopped_invalid_load',
                    INFRASTRUCTURE_FAILURE: 'stopped_infrastructure_failure',
                    INCONCLUSIVE: 'stopped_inconclusive_evidence'}
        for outcome, status in expected.items():
            derived = derive(play([PASS, PASS, outcome]))
            self.assertEqual(derived['status'], status)
            self.assertIsNone(derived['next'])
            self.assertIsNone(derived['result'])
            self.assertEqual(legal_paths(play([PASS, PASS, outcome])), [[]])

    def test_incomplete_coarse_trial_makes_next_branch_undecidable(self):
        state = play([PASS])
        trial = next_trial(state)
        state = record_outcome(dispatch(state, trial), trial.run_id, INCOMPLETE)
        derived = derive(state)
        self.assertEqual(derived['status'], 'undecidable_incomplete_predecessor')
        self.assertIsNone(derived['next'])
        self.assertIn(trial.run_id, derived['detail'])

    def test_dispatched_without_outcome_is_not_advanced(self):
        state = play([PASS, FAIL])
        trial = next_trial(state)
        state = dispatch(state, trial)
        self.assertEqual(derive(state)['status'], 'undecidable_incomplete_predecessor')

    def test_external_stop_is_labelled_partial(self):
        state = play([PASS, PASS])
        state.stop_reason = 'time_exhausted'
        derived = derive(state)
        self.assertEqual(derived['status'], 'partial_time_exhausted')
        self.assertIsNone(derived['next'])

    def test_outcomes_are_final_and_unknown_trials_rejected(self):
        state = play([PASS])
        with self.assertRaises(search.SearchError):
            record_outcome(state, 'c-t01-coarse-n025-r1', FAIL)
        with self.assertRaises(search.SearchError):
            record_outcome(state, 'c-t09-coarse-n225-r1', PASS)
        with self.assertRaises(search.SearchError):
            record_outcome(dispatch(state, next_trial(state)), 'c-t02-coarse-n050-r1', 'RETRY')


class CeilingAndPathTests(unittest.TestCase):
    def test_every_legal_path_respects_the_27_trial_ceiling(self):
        paths = legal_paths(SearchState('c'))
        self.assertEqual(len(paths), 401)
        self.assertEqual(max(len(p) for p in paths), 27)
        for path in paths:
            coarse = sum(1 for t in path if t.phase == 'coarse')
            refine = sum(1 for t in path if t.phase == 'refine')
            confirm = sum(1 for t in path if t.phase == 'confirm')
            self.assertLessEqual(coarse, 20)
            self.assertLessEqual(refine, 4)
            self.assertLessEqual(confirm, 3)
            self.assertEqual([t.ordinal for t in path], list(range(1, len(path) + 1)))
            self.assertEqual(len({t.run_id for t in path}), len(path), 'no hidden retries or duplicate ids')

    def test_maximal_count_path_has_39_minutes_of_scored_holds(self):
        path = max(legal_paths(SearchState('c')), key=len)
        summary = search.path_summary(path)
        self.assertEqual(summary['trials'], 27)
        self.assertEqual((summary['exploration'], summary['confirmations']), (24, 3))
        self.assertEqual(summary['scored_hold_s'], 24 * 60 + 3 * 300)
        self.assertEqual(summary['scored_hold_min'], 39.0)
        self.assertEqual([t.target for t in path][19:], [500, 480, 485, 490, 495, 495, 495, 495])

    def test_all_coarse_pass_path_is_23_trials_and_35_minutes(self):
        state = play([PASS] * 20)
        no_refine = [p for p in legal_paths(SearchState('c')) if not any(t.phase == 'refine' for t in p)
                     and sum(1 for t in p if t.phase == 'coarse') == 20]
        path = max(no_refine, key=len)
        summary = search.path_summary(path)
        self.assertEqual(summary['trials'], 23)
        self.assertEqual(summary['scored_hold_s'], 20 * 60 + 3 * 300)
        self.assertEqual(summary['scored_hold_min'], 35.0)
        self.assertEqual(next_trial(state).target, 500)

    def test_thirty_minute_cap_cannot_hold_the_maximal_path(self):
        holds = max(search.path_summary(p)['scored_hold_s'] for p in legal_paths(SearchState('c')))
        self.assertGreater(holds, 30 * 60, 'a 30-minute cap or a raw 27-count cap is not proof of fit')

    def test_remaining_paths_shrink_as_outcomes_land(self):
        state = play([PASS] * 19 + [FAIL] + [PASS] * 4)
        paths = legal_paths(state)
        # confirmation fails at rep 1, rep 2, rep 3, or all three pass: four leaves, none longer than 3
        self.assertEqual(sorted(len(p) for p in paths), [1, 2, 3, 3])

    def test_readiness_bound_contains_the_ramp_once(self):
        self.assertEqual(search.readiness_bound_s(25), 60)
        self.assertEqual(search.readiness_bound_s(300), 60)
        self.assertEqual(search.readiness_bound_s(325), 62.5)
        self.assertEqual(search.readiness_bound_s(500), 80)
        self.assertEqual(search.nominal_ramp_s(500), 50)

    def test_campaign_ceilings(self):
        self.assertEqual(search.campaign_trial_ceiling(['s-1vcpu-1gb-amd', 's-2vcpu-2gb-amd']), 54)
        self.assertEqual(search.campaign_trial_ceiling(['s-1vcpu-1gb-amd', 's-2vcpu-2gb-amd', 's-1vcpu-2gb-amd'],
                                                       accepted_conditional=['s-1vcpu-2gb-amd']), 81)
        with self.assertRaises(search.SearchError):
            search.campaign_trial_ceiling(['s-1vcpu-1gb-amd', 's-1vcpu-2gb-amd'])

    def test_journal_replay_rejects_gaps_and_duplicates(self):
        trial = search.Trial('c-t02-coarse-n050-r1', 2, 'coarse', 50, 1, 60, ())
        with self.assertRaises(search.SearchError):
            derive(SearchState('c', [TrialRecord(trial)]))


if __name__ == '__main__':
    unittest.main()
