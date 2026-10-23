"""Versioned scoring at the real frozen observation/classifier seam; no replay writes."""
import copy
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import clean_run as controller
import clean_run_analysis as analysis

REPORTS=pathlib.Path(__file__).resolve().parents[2]/'docs/netcode/perf-notes/load-test-reports/2026-10-22-clean-runs'

class ClassificationVersionTests(unittest.TestCase):
    def report(self, name='clean-idle150-r2-20261023'):
        return json.loads((REPORTS/(name+'-summary.json')).read_text())

    def test_actual_idle_wire_failure_has_valid_generator_without_a_clean_or_capacity_pass(self):
        full=self.report();gates=copy.deepcopy(full['gates'])
        full['classification_version']='offered-load-v2'
        analysis.classify(full)
        self.assertTrue(full['generator_valid'])
        self.assertTrue(full['offered_load_valid'])
        self.assertFalse(full['wire_delivery_pass'])
        self.assertFalse(full['strict_generator_valid'])
        self.assertFalse(full['clean_cell_pass'])
        self.assertFalse(full['capacity_pass'])
        self.assertIsNone(full['highest_passing_population_this_observation'])
        self.assertEqual(full['classification'],'valid-offered-load-wire-deficit')
        self.assertEqual(full['failed_gates'],['mapped_wire_29_7hz'])
        self.assertEqual(full['gates'],gates)
        # Original committed report is read-only; re-reading yields the old outcome.
        self.assertEqual(self.report()['classification'],'generator-invalid')

    def test_default_and_explicit_strict_version_retain_historical_outcome(self):
        for version in (None,'strict-v1'):
            full=self.report()
            if version:full['classification_version']=version
            analysis.classify(full)
            self.assertEqual(full['classification'],'generator-invalid')
            self.assertFalse(full['generator_valid'])

    def test_v2_keeps_offered_udp_collector_and_correctness_failures_closed(self):
        for key in ('per_identity_offered_29_7hz','bots_udp_errors_zero','bots_full_workload_udp_errors_zero'):
            full=self.report();full['classification_version']='offered-load-v2';full['gates'][key]=False
            analysis.classify(full)
            self.assertFalse(full['generator_valid'],key)
            self.assertEqual(full['classification'],'generator-invalid')
        full=self.report();full['classification_version']='offered-load-v2';full['collector_valid']=False
        analysis.classify(full)
        self.assertEqual(full['classification'],'collector-invalid')
        full=self.report();full['classification_version']='offered-load-v2';full['gates']['received_aoi_all_peers_zero_unknown']=False
        analysis.classify(full)
        self.assertEqual(full['classification'],'valid-failure')
        self.assertFalse(full['clean_cell_pass'])

    def test_real_movement_pass_and_repeat_scoring_remain_consistent(self):
        full=self.report('clean-movement100-r1-20261023');full['classification_version']='offered-load-v2'
        analysis.classify(full);first=copy.deepcopy(full)
        analysis.classify(full)
        self.assertEqual(full,first)
        self.assertEqual(full['classification'],'clean-cell-pass')
        self.assertTrue(full['generator_valid'] and full['wire_delivery_pass'] and full['clean_cell_pass'] and full['capacity_pass'])

    def test_unknown_version_rejected_in_scoring_and_cell_dispatch(self):
        full=self.report();full['classification_version']='newest'
        with self.assertRaises(ValueError):analysis.classify(full)
        cell=dict(namespace='clean-version-test',population=50,behavior='movement',revision='a'*40,
                  game_sha256='b'*64,bot_sha256='c'*64,classification_version='newest')
        with self.assertRaises(ValueError):controller.configure_cell(cell)

    def test_invalid_manifest_version_creates_no_derived_output(self):
        with tempfile.TemporaryDirectory() as temp:
            p=pathlib.Path(temp);(p/'manifest.json').write_text(json.dumps({'classification_version':'newest'}))
            with mock.patch.object(analysis,'P',p):
                with self.assertRaises(ValueError):analysis.main()
            self.assertEqual({f.name for f in p.iterdir()},{'manifest.json'})

    def test_missing_wire_result_and_aborted_run_never_become_passes(self):
        full=self.report();full['classification_version']='offered-load-v2';full['gates']['mapped_wire_29_7hz']=None
        analysis.classify(full)
        self.assertIsNone(full['wire_delivery_pass'])
        self.assertEqual(full['classification'],'valid-failure')
        self.assertFalse(full['capacity_pass'])
        full=self.report();full['classification_version']='offered-load-v2';full['controller_abort']='test-abort'
        analysis.classify(full)
        self.assertTrue(full['classification'].startswith('aborted-'))
        self.assertFalse(full['clean_cell_pass'] or full['capacity_pass'])
