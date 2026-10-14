"""A coverage audit must reject corrupt archives and mislabeled conditions."""
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import campaign
import publish
import run
import summarize_campaign
import verify_matrix


class MatrixEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.state = self.root / 'campaign-state.json'
        self.source = json.loads((run.ROOT / 'docs/netcode/perf-notes/load-test-reports/'
                                  '2026-10-14-single-run/pilot-clustered-50-recovery/'
                                  'steady.json').read_text())

    def write_row(self, name, **condition):
        directory = self.root / name
        directory.mkdir()
        row = dict(self.source, run_id=name, **condition)
        row['game_config'] = dict(row['game_config'])
        if row['variant'] == 'snapshot15':
            row['game_config']['snapshot_rate_hz'] = 15
        elif row['variant'] == 'aoi600':
            row['game_config'].update(aoi_radius=600, aoi_exit_radius=660, lod_mid_radius=600)
        row['archive_sha256'] = {}
        for role in ('game', 'bots'):
            archive = role + '.tar.gz'
            payload = (name + ':' + role).encode()
            (directory / archive).write_bytes(payload)
            row['archive_sha256'][archive] = hashlib.sha256(payload).hexdigest()
        (directory / 'steady.json').write_text(json.dumps(row))

    def verify(self):
        with mock.patch.object(campaign, 'STATE', self.state), \
             mock.patch.object(run, 'RAW', self.root), \
             mock.patch.object(publish, 'OUTPUT', self.root):
            return verify_matrix.verify()

    def test_matching_cell_and_archive_bytes_have_no_inconsistencies(self):
        self.write_row('core-movement-50-r1', requested_bots=50, behavior='movement')
        self.assertEqual(self.verify()['inconsistent_evidence'], [])

    def test_requested_condition_is_checked_independently_of_run_name(self):
        self.write_row('core-movement-50-r1', requested_bots=3, behavior='strategy',
                       profile='loss3', variant='snapshot15')
        evidence = self.verify()['inconsistent_evidence']
        for field in ('requested_bots', 'behavior', 'profile', 'variant'):
            self.assertTrue(any('condition mismatch: ' + field in item for item in evidence), field)

    def test_each_retained_archive_digest_is_recomputed(self):
        self.write_row('core-movement-50-r1', requested_bots=50, behavior='movement')
        for role in ('game', 'bots'):
            (self.root / 'core-movement-50-r1' / (role + '.tar.gz')).write_bytes(b'corrupted')
        evidence = self.verify()['inconsistent_evidence']
        for role in ('game', 'bots'):
            self.assertTrue(any('checksum mismatch: ' + role + '.tar.gz' in item for item in evidence))

    def test_replacement_must_match_original_condition(self):
        (self.root / 'matrix-replacements.json').write_text(json.dumps({
            'core-movement-50-r1': {'selected_run_id': 'replacement-attempt'}}))
        self.write_row('replacement-attempt', requested_bots=50, behavior='combat')
        self.assertTrue(any('condition mismatch: behavior' in item
                            for item in self.verify()['inconsistent_evidence']))

    def test_wrong_conditions_and_corrupt_archives_cannot_complete_matrix(self):
        self.state.write_text(json.dumps({
            'core_complete': True, 'network_complete': True, 'transfer_complete': True,
            'highest_stable': {'movement': 150, 'combat': 150, 'clustered': 150, 'strategy': 999}}))
        (self.root / 'admission-resolution.json').write_text(json.dumps({'passed': True}))
        for name in self.verify()['missing_cells']:
            condition = dict(requested_bots=3, behavior='strategy', profile='loss3', variant='native')
            if name.startswith('external-'):
                condition['classification'] = 'external-accounting-check-valid'
            self.write_row(name, **condition)
            for role in ('game', 'bots'):
                (self.root / name / (role + '.tar.gz')).write_bytes(b'corrupted')
        result = self.verify()
        self.assertFalse(result['complete'])
        self.assertEqual(result['expected_cell_count'], 88)
        self.assertEqual(result['missing_cells'], [])
        self.assertTrue(result['inconsistent_evidence'])

    def test_actual_scheduler_conditions_can_complete_coverage(self):
        (self.root / 'measurement-preflight-resolution.json').write_text(json.dumps({
            'scored_runs_authorized_by_preflight': True}))

        def cell(name, population, behavior, repeat=1, profile='native', variant='native'):
            self.write_row(name, requested_bots=population, behavior=behavior,
                           profile=profile, variant=variant, repeat=repeat)
            return {'classification': 'native-stable-candidate'}

        with mock.patch.multiple(campaign, STATE=self.state, cell=cell), \
             mock.patch.object(run, 'RAW', self.root):
            campaign.core()
            campaign.network()
            campaign.transfer()
        self.write_row('external-combat-3-r1', requested_bots=3, behavior='combat',
                       classification='external-accounting-check-valid')
        (self.root / 'admission-resolution.json').write_text(json.dumps({'passed': True}))
        result = self.verify()
        self.assertTrue(result['complete'], result['inconsistent_evidence'])
        self.assertEqual(result['expected_cell_count'], 88)

    def test_1000_forecast_requires_valid_strategy_999_source(self):
        for name, condition, expected in (
                ('valid-strategy', {}, True),
                ('collector-invalid', {'collector_valid': False, 'classification': 'collector-invalid'}, False),
                ('wrong-workload', {'behavior': 'combat'}, False)):
            row = dict(requested_bots=999, behavior='strategy')
            row.update(condition)
            self.write_row(name, **row)
            with mock.patch.object(run, 'RAW', self.root), \
                 mock.patch.object(publish, 'OUTPUT', self.root), mock.patch('builtins.print'):
                summarize_campaign.main()
            forecasts = json.loads((self.root / name / 'conditional-forecast.json').read_text())['forecasts']
            self.assertEqual('1000' in forecasts, expected, name)


if __name__ == '__main__':
    unittest.main()
