"""The retained offline timelines reproduce byte for byte and contain no credential."""
import pathlib
import tempfile
import unittest

import fault_evidence
import manifest

COMMITTED = (pathlib.Path(__file__).parent.parent.parent / 'docs' / 'netcode' / 'perf-notes'
             / 'digitalocean-capacity' / 'offline-faults' / 'slice2')


class FaultEvidenceTests(unittest.TestCase):
    def test_regenerated_timelines_match_the_committed_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            fault_evidence.generate(root)
            fresh = pathlib.Path(root)
            self.assertEqual((fresh / 'SHA256SUMS').read_text(), (COMMITTED / 'SHA256SUMS').read_text())

    def test_retained_files_hold_no_credential_value(self):
        for path in COMMITTED.iterdir():
            text = path.read_text(encoding='utf-8')
            for pattern in manifest.SECRET_PATTERNS:
                self.assertIsNone(pattern.search(text), path.name)

    def test_evidence_covers_each_accepted_fault_family(self):
        names = {s.__name__ for s in fault_evidence.SCENARIOS}
        for family in ('lost_controller', 'api_outage', 'stale_controller', 'rate_limit', 'ownership', 'clock', 'late_create', 'fairness', 'restart'):
            self.assertTrue(any(family in name for name in names), family)


if __name__ == '__main__':
    unittest.main()
