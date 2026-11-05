"""The retained run timelines reproduce byte for byte, stay compact and claim no measurement."""
import json
import pathlib
import tempfile
import unittest

import manifest
import run_fault_evidence as evidence

COMMITTED = pathlib.Path(__file__).parent.parent.parent / 'docs' / 'netcode' / 'perf-notes' / 'digitalocean-capacity' / 'offline-faults' / 'slice4'


class RunFaultEvidence(unittest.TestCase):
    def test_regenerated_timelines_match_the_committed_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            evidence.generate(root)
            self.assertEqual((pathlib.Path(root) / 'SHA256SUMS').read_text(), (COMMITTED / 'SHA256SUMS').read_text())

    def test_retained_files_hold_no_credential_or_local_path(self):
        for path in COMMITTED.iterdir():
            text = path.read_text(encoding='utf-8')
            for pattern in manifest.SECRET_PATTERNS:
                self.assertIsNone(pattern.search(text), path.name)
            self.assertNotIn('/private/', text, path.name)
            self.assertNotIn('/tmp/', text, path.name)

    def test_each_accepted_fault_family_has_a_timeline(self):
        names = {s.__name__ for s in evidence.SCENARIOS}
        for family in ('fresh_runs', 'crash_before_dispatch', 'crash_after_dispatch', 'crash_during_active', 'crash_before_outcome', 'crash_after_outcome', 'reused_process_identity', 'old_socket_counters',
                       'leftover_socket_and_netem', 'deadline_exhaustion', 'eligible_resume', 'resume_refused_after_terminal', 'resume_refused_after_operator_abort', 'resume_refused_after_c',
                       'resume_refused_on_changed_host', 'resume_refused_on_changed_source', 'capacity_failure', 'generator_crash', 'lost_host', 'stale_controller', 'incomplete_confirmation',
                       'abort_before_authorization', 'abort_in_flight', 'start_delayed_past_its_window', 'start_delayed_past_a_takeover', 'smoke_delayed_past_a_takeover', 'smoke_delayed_past_its_window',
                       'lost_smoke_reply', 'corrupt_export_then_crash', 'failed_file_is_recovered', 'local_collection_failure', 'wrong_controller',
                       'abort_with_no_controller', 'takeover_takes_effect', 'replayed_grant', 'two_crashes_keep_the_terminal_fact_with_a_scorer', 'two_crashes_keep_the_terminal_fact_without_a_scorer', 'fence_fault_at_wrap_up'):
            self.assertTrue(any(family in name for name in names), family)

    def test_every_timeline_says_its_outcomes_are_scripted(self):
        for path in COMMITTED.glob('*.json'):
            self.assertIn('never a measurement', json.loads(path.read_text(encoding='utf-8'))['scorer'], path.name)

    def test_the_evidence_stays_compact(self):
        total = sum(path.stat().st_size for path in COMMITTED.iterdir())
        self.assertLess(total, 400 * 1024)


if __name__ == '__main__':
    unittest.main()
