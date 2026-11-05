"""The retained slice 6 evidence: synthetic results regenerate byte for byte, the inventory matches, and each file says what it is."""
import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

import capacity_scorer as cs
import measurement_window as mw
import scoring_evidence as evidence

RETAINED = pathlib.Path(__file__).parents[2] / 'docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice6'


class RetainedEvidence(unittest.TestCase):
    def sums(self):
        return {line.split()[1]: line.split()[0] for line in (RETAINED / 'SHA256SUMS').read_text().splitlines()}

    def test_the_synthetic_files_regenerate_exactly(self):
        root = tempfile.mkdtemp(prefix='omega-score-evidence-')
        self.addCleanup(shutil.rmtree, root, True)
        evidence.synthetic(root)
        for name in ('synthetic-scores.json', 'synthetic-searches.json'):
            data = (pathlib.Path(root) / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), self.sums()[name], name)

    def test_every_retained_file_matches_the_inventory(self):
        self.assertGreaterEqual(set(self.sums()), {'synthetic-scores.json', 'synthetic-searches.json'})
        for name, digest in self.sums().items():
            self.assertEqual(hashlib.sha256((RETAINED / name).read_bytes()).hexdigest(), digest, name)

    def test_the_synthetic_files_say_what_they_are(self):
        for name in ('synthetic-scores.json', 'synthetic-searches.json'):
            document = json.loads((RETAINED / name).read_text())
            self.assertEqual(document['kind'], 'synthetic')
            self.assertIn('Nothing ran', document['note'])
            self.assertIn('Not a capacity observation', document['note'])
            self.assertEqual(document['measurement_schema_sha256'], mw.schema_sha256())

    def test_no_single_score_establishes_capacity_and_every_search_branch_is_retained(self):
        scores = json.loads((RETAINED / 'synthetic-scores.json').read_text())['scenarios']
        self.assertTrue(all(row['establishes_capacity'] is False for row in scores.values()))
        self.assertEqual({row['classification'] for row in scores.values()}, {cs.VALID_PASS, cs.CAPACITY_FAILURE, cs.INVALID_LOAD, cs.INFRASTRUCTURE_FAILURE, cs.INCONCLUSIVE})
        searches = json.loads((RETAINED / 'synthetic-searches.json').read_text())['scenarios']
        self.assertEqual({row['status'] for row in searches.values()} & {'confirmed', 'confirmed_search_cap_reached', 'no_passing_target', 'unconfirmed_variable', 'unconfirmed_partial', 'stopped_invalid_load', 'stopped_inconclusive_evidence', 'stopped_infrastructure_failure', 'undecidable_incomplete_predecessor', 'partial_time_exhausted'},
                         {'confirmed', 'confirmed_search_cap_reached', 'no_passing_target', 'unconfirmed_variable', 'unconfirmed_partial', 'stopped_invalid_load', 'stopped_inconclusive_evidence', 'stopped_infrastructure_failure', 'undecidable_incomplete_predecessor', 'partial_time_exhausted'})
        for name, row in searches.items():
            self.assertTrue(row['no_hidden_retry'], name)

    def test_real_summaries_are_labelled_and_never_pass(self):
        for path in RETAINED.glob('real-*.json'):
            document = json.loads(path.read_text())
            self.assertEqual(document['kind'], 'real_local')
            self.assertIn('not a capacity observation', document['note'])
            self.assertTrue(document['provenance']['source_clean'])
            self.assertRegex(document['provenance']['source_revision'], '^[0-9a-f]{40}$')
            for name, row in document['scenarios'].items():
                self.assertNotEqual(row['classification'], cs.VALID_PASS, name)
                self.assertFalse(row['establishes_capacity'], name)


if __name__ == '__main__':
    unittest.main()
