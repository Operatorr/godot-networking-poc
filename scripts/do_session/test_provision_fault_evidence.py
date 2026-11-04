"""The retained provisioning timelines reproduce byte for byte and hold no credential or bootstrap nonce."""
import json
import pathlib
import tempfile
import unittest

import manifest
import provision_fault_evidence as evidence

COMMITTED = (pathlib.Path(__file__).parent.parent.parent / 'docs' / 'netcode' / 'perf-notes' / 'digitalocean-capacity' / 'offline-faults' / 'slice3')


class ProvisionFaultEvidence(unittest.TestCase):
    def test_regenerated_timelines_match_the_committed_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            evidence.generate(root)
            self.assertEqual((pathlib.Path(root) / 'SHA256SUMS').read_text(), (COMMITTED / 'SHA256SUMS').read_text())

    def test_retained_files_hold_no_credential_nonce_or_user_data(self):
        for path in COMMITTED.iterdir():
            text = path.read_text(encoding='utf-8')
            for pattern in manifest.SECRET_PATTERNS:
                self.assertIsNone(pattern.search(text), path.name)
            self.assertNotIn('fixture-nonce', text, path.name)
            self.assertNotIn('#cloud-config', text, path.name)

    def test_each_accepted_fault_family_has_a_timeline(self):
        names = {s.__name__ for s in evidence.SCENARIOS}
        for family in ('ready_pair', 'partial_pair', 'lost_create', 'unknown_create', 'late_create', 'duplicate_create', 'wrong_plan', 'wrong_facts', 'project_assignment',
                       'firewall_wrong', 'cloud_init', 'ownership', 'changed_operator_address', 'broad_source', 'outage', 'accepted_delete', 'impostor', 'restarted_controller',
                       'authorization', 'disposition', 'firewall_retargeted', 'protected_droplet', 'package_versions'):
            self.assertTrue(any(family in name for name in names), family)

    def test_retained_package_inventories_are_only_the_synthetic_fixture(self):
        import fake_guest
        allowed = set(fake_guest.FIXTURE_PACKAGES)
        found = 0
        for path in COMMITTED.glob('*.json'):
            for inventory in json.loads(path.read_text(encoding='utf-8'))['retained_package_inventories'].values():
                found += 1
                self.assertEqual({e['name'] for e in inventory['inventory']}, allowed, path.name)
                self.assertTrue(all('fixture' in e['version'] for e in inventory['inventory']), path.name)
        self.assertGreater(found, 0)

    def test_only_documentation_addresses_appear_in_the_retained_rules(self):
        for path in COMMITTED.glob('*.json'):
            text = path.read_text(encoding='utf-8')
            for prefix in ('10.', '192.168.'):
                self.assertNotIn('"' + prefix, text, path.name)


if __name__ == '__main__':
    unittest.main()
