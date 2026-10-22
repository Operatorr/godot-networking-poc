"""Idle keeps input/confirm delivery gates without requiring combat activity."""
import copy
import unittest

import clean_run as live
import clean_run_analysis as analysis
import clean_run_scoring as scoring


class IdleScoringTests(unittest.TestCase):
    def test_idle_dispatch_is_bound_to_exact_population_and_revision(self):
        prior = copy.deepcopy(live.CELL)
        live.configure_cell(dict(namespace='clean-idle100-r1-20261022', population=100,
            behavior='idle', revision='f'*40, game_sha256='a'*64, bot_sha256='b'*64))
        self.assertEqual((live.POPULATION, live.BEHAVIOR), (100, 'idle'))
        self.assertEqual(live.CELL['revision'], 'f'*40)
        if prior: live.configure_cell(prior)

    def test_zero_actions_still_requires_snapshot_and_confirm_delivery(self):
        first = dict(snapshots=100, confirms=200, shoot_inputs=0, ability_inputs=0)
        last = first | dict(snapshots=3100, confirms=9200)
        observations = [dict(phase='Running', snapshot_age_s=.04, confirm_age_s=.08,
                             shoot_inputs=0, ability_inputs=0)]*300
        evidence = scoring.delivery_evidence(first, last, observations)
        self.assertTrue(evidence['delivery_gate'])
        self.assertFalse(scoring.delivery_evidence(first, last | dict(confirms=200), observations)['delivery_gate'])
        for field, value in [('snapshot_age_s', None), ('confirm_age_s', None),
                             ('snapshot_age_s', .250), ('confirm_age_s', .500),
                             ('snapshot_age_s', 1.0), ('phase', 'Disconnected')]:
            bad = observations.copy(); bad[0] = bad[0] | {field: value}
            if value in (.250, .500): bad = [bad[0]]*300
            self.assertFalse(scoring.delivery_evidence(first, last, bad)['delivery_gate'])

    def test_empty_remote_observations_are_distinct_from_unknown_positions(self):
        report = dict(per_bot=[dict(bot_id=1, aoi_matched_positions=0, aoi_unknown_positions=0),
                              dict(bot_id=2, aoi_matched_positions=10, aoi_unknown_positions=1)],
            regression_assertions=[dict(name='aoi_cull', passed=False, skipped=False,
                details=dict(threshold=1150, eligible_bots=2, violators=[], unknown_bots=[1, 2]))])
        result = analysis.received_aoi(report, 2)
        self.assertEqual(result['unknown_peer_ids'], [2])
        self.assertEqual(result['no_remote_entity_observation_peer_ids'], [1])
        self.assertFalse(result['all_peer_zero_unknown'])
        self.assertFalse(result['strict_default_pass'])


if __name__ == '__main__': unittest.main()
