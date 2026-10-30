"""Exact time/spend accumulation, boundaries, re-admission and zero-mutation rejections."""
import unittest

import admission as adm
import fixture_support as fx
import manifest as m
import search
from search import PASS, FAIL, SearchState, dispatch, next_trial, record_outcome

NOW = '2026-10-30T12:00:00+00:00'


def frozen(mutate=None):
    conditions = fx.conditions()
    if mutate:
        mutate(conditions)
    manifest, sha = m.freeze_manifest(conditions, fx.preflight(), fx.FROZEN_AT)
    return manifest, sha


def play(outcomes, condition='do-cap-1v1g-20261030a'):
    state = SearchState(condition)
    for outcome in outcomes:
        trial = next_trial(state)
        state = record_outcome(dispatch(state, trial), trial.run_id, outcome)
    return state


def admit(manifest, sha, state=None, now=NOW, health=None, **kw):
    state = state or SearchState(manifest['session']['id'])
    return adm.admit(manifest, sha, state, now, fx.health(sha) if health is None else health, **kw)


class TimeAccumulationTests(unittest.TestCase):
    def test_per_trial_terms_are_itemized_and_ramp_not_double_counted(self):
        manifest, _ = frozen()
        trial = search.Trial('x', 1, 'coarse', 500, 1, 60, ())
        cost = adm.trial_duration(manifest, trial)
        self.assertEqual(cost['terms'], dict(readiness_bound_s=80, post_auth_warmup_s=2, hold_s=60,
                                             process_reset_s=30, recorder_finalization_s=20, per_trial_export_s=40))
        self.assertEqual(cost['total_s'], 232)
        self.assertEqual(cost['nominal_ramp_s'], 50)
        self.assertNotIn('ramp_s', cost['terms'])

    def test_maximal_path_total_is_exact_sum(self):
        manifest, sha = frozen()
        result = admit(manifest, sha)
        maximal = result.time['maximal_path']
        self.assertEqual(maximal['count'], 27)
        self.assertEqual(maximal['scored_hold_s'], 2340)
        # readiness: 12 rungs <=300 at 60 s, then 62.5,65,67.5,70,72.5,75,77.5,80 for 325..500,
        # refinements 480..495 at 78,78.5,79,79.5, confirmations at 495 -> 79.5 each.
        readiness = 12 * 60 + sum([62.5, 65, 67.5, 70, 72.5, 75, 77.5, 80]) + sum([78, 78.5, 79, 79.5]) + 3 * 79.5
        fixed_per_trial = 27 * (2 + 30 + 20 + 40)
        self.assertEqual(maximal['total_s'], readiness + fixed_per_trial + 2340)
        self.assertEqual(result.time['pre_workload_terms'], dict(create_bootstrap_s=900, readiness_access_s=180))
        self.assertEqual(result.time['tail_terms'], dict(collection_export_s=300, evidence_recovery_grace_s=300))
        self.assertEqual(result.time['workload_deadline_c_s'], 14400 - 120)
        self.assertEqual(result.time['required_before_c_s'],
                         900 + 180 + maximal['total_s'] + 600)
        self.assertEqual(result.time['legal_remaining_paths'], 401)
        self.assertTrue(result.admitted)

    def test_exact_cap_boundary(self):
        base, _ = frozen()
        required = admit(base, m.manifest_sha256(base)).time['required_before_c_s']
        exact_cap = required + 120

        def tight(conditions):
            conditions['limits']['max_session_duration_s'] = exact_cap
        manifest, sha = frozen(tight)
        result = admit(manifest, sha)
        self.assertEqual(result.time['slack_s'], 0)
        self.assertTrue(result.admitted, result.reasons)

        def short(conditions):
            conditions['limits']['max_session_duration_s'] = exact_cap - 1
        manifest, sha = frozen(short)
        result = admit(manifest, sha)
        self.assertFalse(result.admitted)
        self.assertEqual(result.time['slack_s'], -1)
        self.assertTrue(any('No deadline extension' in r for r in result.reasons))
        self.assertIsNone(result.next_run)

    def test_thirty_minute_cap_is_rejected_even_though_count_ceiling_is_27(self):
        def thirty(conditions):
            conditions['limits']['max_session_duration_s'] = 1800
        manifest, sha = frozen(thirty)
        result = admit(manifest, sha)
        self.assertFalse(result.admitted)
        self.assertEqual(result.time['maximal_path']['count'], 27)
        self.assertGreater(result.time['maximal_path']['scored_hold_s'], 1800)

    def test_re_admission_after_t0_uses_elapsed_and_shrinking_paths(self):
        manifest, sha = frozen()
        state = play([PASS] * 19 + [FAIL] + [PASS] * 4)
        t0 = '2026-10-30T12:00:00+00:00'
        result = admit(manifest, sha, state, now='2026-10-30T14:00:00+00:00', phase='pair_ready', t0=t0)
        self.assertTrue(result.admitted, result.reasons)
        self.assertEqual(result.time['elapsed_s'], 7200)
        self.assertEqual(result.time['pre_workload_terms'], {})
        self.assertEqual(result.time['maximal_path']['count'], 3)
        self.assertEqual(result.next_run['phase'], 'confirm')
        self.assertEqual(result.next_run['target'], 495)
        late = admit(manifest, sha, state, now='2026-10-30T15:50:00+00:00', phase='pair_ready', t0=t0)
        self.assertFalse(late.admitted)
        self.assertTrue(late.time['next_trial_only_fits'] is False or late.time['slack_s'] < 0)

    def test_pair_ready_needs_t0_and_consistent_clock(self):
        manifest, sha = frozen()
        self.assertFalse(admit(manifest, sha, phase='pair_ready').admitted)
        result = admit(manifest, sha, now='2026-10-30T11:00:00+00:00', phase='pair_ready', t0=NOW)
        self.assertFalse(result.admitted)
        self.assertTrue(any('before t0' in r for r in result.reasons))

    def test_no_remaining_work_when_search_is_terminal(self):
        manifest, sha = frozen()
        result = admit(manifest, sha, play([PASS, FAIL, FAIL, PASS, PASS, PASS]))
        self.assertEqual(result.decision, adm.NO_REMAINING_WORK)
        self.assertEqual(result.search['status'], 'confirmed')
        self.assertIsNone(result.next_run)
        result = admit(manifest, sha, play([PASS, FAIL, FAIL, PASS, FAIL]))
        self.assertEqual(result.decision, adm.NO_REMAINING_WORK)
        self.assertEqual(result.search['status'], 'unconfirmed_variable')
        result = admit(manifest, sha, play([FAIL, FAIL]))
        self.assertEqual(result.search['status'], 'no_passing_target')
        result = admit(manifest, sha, play([PASS] * 23))
        self.assertEqual(result.search['status'], 'confirmed_search_cap_reached')
        result = admit(manifest, sha, play([PASS, search.INFRASTRUCTURE_FAILURE]))
        self.assertEqual(result.search['status'], 'stopped_infrastructure_failure')

    def test_incomplete_predecessor_blocks_dependent_dispatch_and_resume(self):
        manifest, sha = frozen()
        state = play([PASS])
        trial = next_trial(state)
        pending = dispatch(state, trial)
        result = admit(manifest, sha, pending, resume_requested=True)
        self.assertEqual(result.decision, adm.NO_REMAINING_WORK)
        self.assertEqual(result.search['status'], 'undecidable_incomplete_predecessor')
        incomplete = record_outcome(pending, trial.run_id, search.INCOMPLETE)
        result = admit(manifest, sha, incomplete, resume_requested=True)
        self.assertIsNone(result.next_run)

    def test_time_exhaustion_is_a_labelled_partial(self):
        manifest, sha = frozen()
        state = play([PASS, PASS])
        state.stop_reason = 'time_exhausted'
        result = admit(manifest, sha, state)
        self.assertEqual(result.decision, adm.NO_REMAINING_WORK)
        self.assertEqual(result.search['status'], 'partial_time_exhausted')
        self.assertIsNone(result.search['result'])


class CostTests(unittest.TestCase):
    def test_cost_terms_are_exact(self):
        manifest, _ = frozen()
        cost = adm.estimate_cost(manifest)
        game, bot = cost['roles']['game'], cost['roles']['bot']
        self.assertEqual(game['billable_units'], 4)
        self.assertAlmostEqual(game['compute_usd'], 4 * 0.01042, places=6)
        self.assertAlmostEqual(bot['compute_usd'], 4 * 0.08333, places=6)
        self.assertAlmostEqual(game['prorated_allowance_gib'], 1.0 * 1024 * 4 / 730, places=5)
        self.assertAlmostEqual(game['transfer_usd'], (20 - 1024 * 4 / 730) * 0.01, places=5)
        self.assertEqual(bot['transfer_usd'], 0.0)
        self.assertAlmostEqual(cost['session_estimate_usd'],
                               game['compute_usd'] + bot['compute_usd'] + game['transfer_usd'], places=6)
        self.assertEqual(cost['management_host_monthly_usd_separate'], 6.0)
        self.assertEqual(cost['estimated_outbound_gib'], 24.0)
        self.assertTrue(any('never an invoice' in a for a in cost['assumptions']))

    def test_billing_minimum_applies_to_short_caps(self):
        def short(conditions):
            conditions['limits'].update(max_session_duration_s=1800, evidence_recovery_grace_s=300,
                                        teardown_reserve_s=120)
        manifest, _ = frozen(short)
        cost = adm.estimate_cost(manifest)
        self.assertEqual(cost['roles']['game']['billable_units'], 1)

    def test_no_proration_is_more_conservative(self):
        def strict(conditions):
            conditions['pricing']['prorate_transfer_allowance'] = False
        manifest, _ = frozen(strict)
        cost = adm.estimate_cost(manifest)
        self.assertAlmostEqual(cost['transfer_usd'], 24 * 0.01, places=6)

    def test_exact_spend_boundary(self):
        base, _ = frozen()
        estimate = adm.estimate_cost(base)['session_estimate_usd']

        def exact(conditions):
            conditions['limits']['max_estimated_session_usd'] = estimate
        manifest, sha = frozen(exact)
        self.assertTrue(admit(manifest, sha).admitted)

        def below(conditions):
            conditions['limits']['max_estimated_session_usd'] = estimate - 0.000001
        manifest, sha = frozen(below)
        result = admit(manifest, sha)
        self.assertFalse(result.admitted)
        self.assertTrue(any('exceeds max_estimated_session_usd' in r for r in result.reasons))

    def test_transfer_limit_boundary(self):
        def exact(conditions):
            conditions['limits']['max_estimated_transfer_gib'] = 24
        manifest, sha = frozen(exact)
        self.assertTrue(admit(manifest, sha).admitted)

        def below(conditions):
            conditions['limits']['max_estimated_transfer_gib'] = 23.999
        manifest, sha = frozen(below)
        self.assertTrue(any('exceeds max_estimated_transfer_gib' in r for r in admit(manifest, sha).reasons))

    def test_over_budget_still_reported_when_search_terminal(self):
        def below(conditions):
            conditions['limits']['max_estimated_session_usd'] = 0.01
        manifest, sha = frozen(below)
        result = admit(manifest, sha, play([FAIL, FAIL]))
        self.assertEqual(result.decision, adm.REJECTED)


class IntegrityTests(unittest.TestCase):
    def test_changed_manifest_rejected(self):
        manifest, sha = frozen()
        manifest['limits']['max_session_duration_s'] = 99999
        result = admit(manifest, sha)
        self.assertFalse(result.admitted)
        self.assertTrue(any('does not match recorded' in r for r in result.reasons))
        self.assertEqual(result.time, {}, 'no plan is produced for a changed manifest')

    def test_changed_limits_in_force_rejected(self):
        manifest, sha = frozen()
        limits = dict(manifest['limits'], max_session_duration_s=28800)
        result = admit(manifest, sha, current_limits=limits)
        self.assertTrue(any('no deadline or budget change is admitted' in r for r in result.reasons))
        self.assertTrue(admit(manifest, sha, current_limits=dict(manifest['limits'])).admitted)

    def test_unhealthy_or_unacknowledged_cleanup_infrastructure_rejected(self):
        manifest, sha = frozen()
        health = fx.health(sha)
        health['watchdog']['healthy'] = False
        result = admit(manifest, sha, health=health)
        self.assertTrue(any('watchdog is not reported healthy' in r for r in result.reasons))
        health = fx.health('0' * 64)
        result = admit(manifest, sha, health=health)
        self.assertTrue(any('not acknowledged this exact manifest hash' in r for r in result.reasons))
        result = admit(manifest, sha, health={})
        self.assertFalse(result.admitted)

    def test_rejection_reasons_are_complete_and_explanation_reproducible(self):
        def broken(conditions):
            conditions['limits']['max_session_duration_s'] = 1800
            conditions['limits']['max_estimated_session_usd'] = 0.01
        manifest, sha = frozen(broken)
        first = admit(manifest, sha)
        second = admit(manifest, sha)
        self.assertEqual(first.to_dict(), second.to_dict(), 'frozen clock makes the explanation reproducible')
        self.assertTrue(any('exceeds max_estimated_session_usd' in r for r in first.reasons))
        self.assertTrue(any('short by' in r for r in first.reasons))

    def test_planner_modules_have_no_provider_or_network_capability(self):
        import pathlib
        forbidden = ('socket', 'urllib', 'http', 'subprocess', 'requests', 'ssl', 'paramiko', 'asyncio')
        for name in ('manifest.py', 'search.py', 'admission.py', 'do_session.py'):
            source = pathlib.Path(__file__).with_name(name).read_text()
            for module in forbidden:
                self.assertNotRegex(source, r'(?m)^\s*(import|from)\s+' + module + r'\b',
                                    name + ' must not import ' + module)


if __name__ == '__main__':
    unittest.main()
