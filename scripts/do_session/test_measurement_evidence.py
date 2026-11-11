"""The retained slice 5 evidence: synthetic proofs regenerate byte for byte, and real summaries are the bytes the inventory names."""
import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

import measurement_evidence as evidence
import measurement_window as mw

RETAINED = pathlib.Path(__file__).parents[2] / 'docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice5'


class RetainedEvidence(unittest.TestCase):
    def sums(self):
        return {line.split()[1]: line.split()[0] for line in (RETAINED / 'SHA256SUMS').read_text().splitlines()}

    def test_the_synthetic_table_regenerates_exactly(self):
        root = tempfile.mkdtemp(prefix='omega-window-evidence-')
        self.addCleanup(shutil.rmtree, root, True)
        evidence.synthetic(root)
        data = (pathlib.Path(root) / 'synthetic-proofs.json').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.sums()['synthetic-proofs.json'])

    def test_every_retained_file_matches_the_inventory(self):
        for name, digest in self.sums().items():
            self.assertEqual(hashlib.sha256((RETAINED / name).read_bytes()).hexdigest(), digest, name)

    def test_the_synthetic_table_says_what_it_is(self):
        document = json.loads((RETAINED / 'synthetic-proofs.json').read_text())
        self.assertEqual(document['kind'], 'synthetic')
        self.assertIn('Nothing ran', document['note'])
        self.assertEqual(document['measurement_schema_sha256'], mw.schema_sha256())
        for name, row in document['scenarios'].items():
            self.assertFalse(row['establishes_capacity'], name)
            self.assertEqual(row['status'] == 'complete', not row['reasons'], name)

    def test_the_real_summaries_say_what_they_are_and_where_they_came_from(self):
        for path in RETAINED.glob('real-*.json'):
            document = json.loads(path.read_text())
            self.assertEqual(document['kind'], 'real_local')
            self.assertIn('not a capacity observation', document['note'])
            provenance = document['provenance']
            self.assertRegex(provenance['source_revision'], '^[0-9a-f]{40}$')
            self.assertTrue(provenance['source_clean'], 'built and run from an exact clean revision')
            self.assertEqual(provenance['measurement_schema_sha256'], mw.schema_sha256())
            for name, row in document['scenarios'].items():
                self.assertFalse(row['establishes_capacity'], name)
                self.assertEqual(row['contract_hold'], row['hold_s'] in (60, 300), name)
                if row['status'] == 'complete':
                    self.assertFalse(row['socket_counters_required'], 'nothing on this path could read a kernel drop counter')


if __name__ == '__main__':
    unittest.main()
