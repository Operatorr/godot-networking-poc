"""Scheduling follows the user's one-run matrix, without contacting hosts."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import campaign
import run
import verify_matrix
import publish


class SinglePassMatrixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.state = self.root / 'campaign-state.json'
        (self.root / 'measurement-preflight-resolution.json').write_text(
            json.dumps({'scored_runs_authorized_by_preflight': True}))
        self.calls = []

    def cell(self, name, population, behavior, repeat=1, profile='native', variant='native'):
        self.calls.append((name, population, behavior, repeat, profile, variant))
        return {'classification': 'native-stable-candidate'}

    def patches(self):
        return mock.patch.multiple(campaign, STATE=self.state, cell=self.cell)

    def test_core_schedules_each_workload_population_once(self):
        with self.patches(), mock.patch.object(run, 'RAW', self.root):
            campaign.core()
        core = [row for row in self.calls if row[0].startswith('core-')]
        expected = {(population, behavior) for population in (50, 100, 150)
                    for behavior in ('movement', 'combat', 'clustered', 'strategy')}
        expected |= {(population, 'strategy') for population in (200, 250, 500, 750, 999)}
        self.assertEqual(len(core), 17)
        self.assertEqual({(row[1], row[2]) for row in core}, expected)
        self.assertTrue(all(row[3] == 1 for row in self.calls))
        idle = [row for row in self.calls if row[0].startswith('idle-')]
        self.assertEqual([row[1] for row in idle], [100, 150])
        state = json.loads(self.state.read_text())
        for behavior in ('movement', 'combat', 'clustered'):
            self.assertEqual(state['ladder_stop_reason'][behavior], 'planned-population-limit')
            self.assertNotIn(behavior, state['first_failed'])

    def test_network_runs_one_pass_of_profiles_and_required_control_positions(self):
        self.state.write_text(json.dumps({'highest_stable': {'combat': 150, 'strategy': 999}}))
        with self.patches():
            campaign.network()
        self.assertEqual(len(self.calls), 44)
        profiles = [row for row in self.calls if not row[0].startswith('network-control-')]
        self.assertEqual(len(profiles), 36)
        self.assertEqual(len({(row[1], row[2], row[4]) for row in profiles}), 36)
        self.assertTrue(all(row[3] == 1 for row in self.calls))

    def test_failed_workload_stops_its_ladder_and_refines_once(self):
        def observed(name, population, behavior, repeat=1, profile='native', variant='native'):
            result = self.cell(name, population, behavior, repeat, profile, variant)
            if population == 50 and behavior == 'clustered':
                result['classification'] = 'valid-failure'
            return result

        with mock.patch.multiple(campaign, STATE=self.state, cell=observed), \
             mock.patch.object(run, 'RAW', self.root):
            campaign.core()
        clustered = [row for row in self.calls if row[2] == 'clustered']
        self.assertEqual([(row[1], row[3]) for row in clustered], [(50, 1), (25, 1)])

    def test_high_population_combat_state_is_rejected(self):
        self.state.write_text(json.dumps({'highest_stable': {'combat': 250, 'strategy': 999}}))
        with self.patches(), self.assertRaisesRegex(RuntimeError, 'planned workload scope'):
            campaign.network()
        self.assertEqual(self.calls, [])

    def test_direct_high_population_non_strategy_cell_is_rejected_before_running(self):
        with mock.patch.object(run, 'run') as execute, \
             self.assertRaisesRegex(ValueError, 'only Strategy'):
            campaign.cell('core-combat-200-r1', 200, 'combat')
        execute.assert_not_called()

    def test_unfinished_coverage_requires_four_initial_cells_and_external_once(self):
        with mock.patch.object(campaign, 'STATE', self.state), \
             mock.patch.object(run, 'RAW', self.root), \
             mock.patch.object(publish, 'OUTPUT', self.root):
            result = verify_matrix.verify()
        self.assertFalse(result['complete'])
        self.assertEqual(result['expected_cell_count'], 5)
        self.assertTrue(all(name.endswith('-r1') for name in result['missing_cells']))

    def test_transfer_runs_one_pass_of_variants_and_required_control_positions(self):
        self.state.write_text(json.dumps({'highest_stable': {
            'combat': 150, 'clustered': 150, 'strategy': 999}}))
        with self.patches():
            campaign.transfer()
        self.assertEqual(len(self.calls), 24)
        variants = [row for row in self.calls if row[5] != 'native']
        self.assertEqual(len(variants), 12)
        self.assertEqual(len({(row[1], row[2], row[5]) for row in variants}), 12)
        self.assertTrue(all(row[3] == 1 for row in self.calls))


if __name__ == '__main__':
    unittest.main()
