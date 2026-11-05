"""The retained slice 7 evidence: every session regenerates byte for byte, says what it is, and holds what the issue asked for."""
import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

import evidence_publication as ep
import export_evidence as evidence
import export_fixtures as ef

RETAINED = pathlib.Path(__file__).parents[2] / 'docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice7'


def scenarios():
    return json.loads((RETAINED / 'synthetic-exports.json').read_text())['scenarios']


class RetainedEvidence(unittest.TestCase):
    def sums(self):
        return {line.split('  ', 1)[1]: line.split()[0] for line in (RETAINED / 'SHA256SUMS').read_text().splitlines()}

    def test_it_regenerates_exactly(self):
        root = tempfile.mkdtemp(prefix='omega-export-evidence-')
        self.addCleanup(shutil.rmtree, root, True)
        evidence.generate(root)
        self.assertEqual((pathlib.Path(root) / 'SHA256SUMS').read_text(), (RETAINED / 'SHA256SUMS').read_text())

    def test_every_retained_file_matches_the_inventory_and_nothing_else_is_there(self):
        kept = {str(path.relative_to(RETAINED)) for path in RETAINED.rglob('*') if path.is_file()}
        self.assertEqual(kept - {'SHA256SUMS', 'README.md'}, set(self.sums()))
        for name, digest in self.sums().items():
            self.assertEqual(hashlib.sha256((RETAINED / name).read_bytes()).hexdigest(), digest, name)

    def test_it_says_what_it_is_and_claims_nothing(self):
        document = json.loads((RETAINED / 'synthetic-exports.json').read_text())
        self.assertEqual(document['kind'], 'synthetic')
        self.assertIn('Nothing ran', document['note'])
        self.assertIn('SYNTHETIC FIXTURE', (RETAINED / 'synthetic-sample' / 'summary.md').read_text().splitlines()[0])
        self.assertIn('Nothing ran', json.loads((RETAINED / 'synthetic-sample' / 'summary.json').read_text())['synthetic_fixture'])
        self.assertIn('Not live-host validation and not a capacity finding', (RETAINED / 'README.md').read_text())

    def test_no_raw_evidence_and_no_leak_is_retained(self):
        for path in RETAINED.rglob('*'):
            if path.is_file():
                self.assertLess(path.stat().st_size, ep.MAX_PUBLISHED_BYTES, path.name)
                self.assertFalse(path.name.endswith(('.csv', '.ndjson', '.log', '.partial')), path.name)
                text = path.read_text()
                for marker in (ef.SOCKET_MARKER, ef.ENDPOINT_MARKER, ef.KERNEL_ENDPOINT_MARKER):
                    self.assertNotIn(marker, text, path.name)
        files = {name: (RETAINED / 'synthetic-sample' / name).read_bytes() for name in ep.PUBLISHED_FILES}
        self.assertEqual(ep.guard_problems(files), [])


class WhatTheRowsSay(unittest.TestCase):
    def test_only_complete_evidence_of_a_confirmed_search_establishes_anything(self):
        for name, row in scenarios().items():
            if row['establishes']:
                self.assertEqual(row['evidence_latest_export'], 'complete', name)
                self.assertEqual(row['search_status'], 'confirmed', name)
                self.assertTrue(row['claim_confirmed'], name)

    def test_a_confirmed_search_over_incomplete_evidence_is_history(self):
        row = scenarios()['required_file_absent_withholds_the_claim']
        self.assertEqual(row['search_status'], 'confirmed')
        self.assertEqual(row['claim_kind'], 'evidence_incomplete')
        self.assertFalse(row['establishes'])
        self.assertTrue(row['history_withheld'])
        self.assertEqual(row['overall'], 'resources_verified_evidence_incomplete')

    def test_every_session_reached_cleanup_and_only_complete_evidence_reads_clean(self):
        for name, row in scenarios().items():
            self.assertTrue(row['cleanup_verified'] or name == 'new_socket_fields_stay_private', name)
            if row['overall'] == 'clean':
                self.assertEqual(row['evidence_registry'], 'complete', name)

    def test_every_written_report_reproduces(self):
        for name, row in scenarios().items():
            self.assertIn(row['reproduces'], (True, None), name)

    def test_the_faults_the_issue_names_each_end_as_they_must(self):
        rows = scenarios()
        for name in ('corrupt_bytes_in_transfer', 'wrong_role_bytes_for_a_seal', 'remote_file_changing', 'stale_recorder_schema'):
            self.assertEqual(rows[name]['evidence_latest_export'], 'corrupt', name)
            self.assertFalse(rows[name]['establishes'], name)
        for name in ('transfer_keeps_failing_other_files_kept', 'no_space_promoting_a_file', 'first_failure_older_than_the_grace'):
            self.assertEqual(rows[name]['evidence_latest_export'], 'missing', name)
        self.assertEqual(rows['truncated_transfer_then_recovered']['attempts_retained'], 1)
        self.assertEqual(rows['truncated_transfer_then_recovered']['evidence_latest_export'], 'complete')
        for name in ('no_space_writing_the_generation', 'generation_rename_refused', 'exporter_defect'):
            self.assertEqual(rows[name]['generations'], [], name)
            self.assertEqual(rows[name]['evidence_registry'], 'partial', name)
            self.assertTrue(rows[name]['cleanup_requested'], name)
        self.assertEqual(rows['first_failure_older_than_the_grace']['transfers_after_the_episode'], 0)
        self.assertTrue(rows['reconnect_keeps_the_original_episode']['deadline_unchanged'])
        self.assertTrue(rows['reconnect_keeps_the_original_episode']['first_failure_unchanged'])
        self.assertEqual(rows['deletion_outage_past_d_stays_on_record']['overall'], 'resources_verified_after_overdue')
        self.assertTrue(any(item['kind'] == 'cleanup-overdue' for item in rows['deletion_outage_past_d_stays_on_record']['incidents']))
        self.assertTrue(rows['new_socket_fields_stay_private']['fixture_carried_them'])
        self.assertFalse(rows['new_socket_fields_stay_private']['reached_anything_derived'])
        self.assertEqual(rows['manifest_changed_after_the_session']['export_status'], 'corrupt')
        self.assertFalse(rows['manifest_changed_after_the_session']['report_written'])
        prepared = rows['prepared_in_the_canonical_directory_only']
        self.assertEqual(prepared['published_files'], sorted(ep.PUBLISHED_FILES))
        self.assertEqual(prepared['receipt_status'], ['verified_local'])
        self.assertEqual((prepared['publication'], prepared['publication_detail']), ('verified_local', 'unverified'))
        self.assertEqual(prepared['journal_mirror'], 'not_published')

    def test_what_a_current_producer_wrote_cannot_be_missing_from_complete_evidence(self):
        rows = scenarios()
        for name in ('plan_lost_withholds_completeness', 'clock_bracket_lost_withholds_completeness', 'provisioning_provenance_lost_withholds_completeness'):
            row = rows[name]
            self.assertEqual((row['evidence_registry'], row['evidence_latest_export']), ('missing', 'missing'), name)
            self.assertFalse(row['establishes'], name)
            self.assertEqual(row['overall'], 'resources_verified_evidence_incomplete', name)
            self.assertEqual(row['search_status'], 'confirmed', 'what was measured stays what it was')
            self.assertTrue(row['controller_inputs_missing'], name)

    def test_an_unlistable_directory_is_unknown_and_not_empty(self):
        row = scenarios()['unlistable_directory_stays_unknown']
        self.assertEqual((row['evidence_registry'], row['evidence_latest_export'], row['overall']), ('partial', 'partial', 'resources_verified_evidence_incomplete'))
        self.assertFalse(row['establishes'])
        self.assertEqual(row['not_inventoried'], [dict(path='provider-diagnostics', kind='directory', reason='PermissionError')])
        self.assertTrue(row['readable_sibling_kept'])
        self.assertEqual(row['public_says_paths_not_inventoried'], 1)

    def test_the_first_failure_fixes_the_episode_through_a_delay_a_crash_and_a_lost_report(self):
        rows = scenarios()
        for name in ('first_failure_holds_past_a_slow_later_file', 'crash_between_files_keeps_the_first_failure', 'lost_report_then_crash_keeps_the_first_failure'):
            self.assertTrue(rows[name]['recovery_deadline_is_first_failure_plus_grace'], name)
            self.assertTrue(rows[name]['cleanup_requested'], name)
            self.assertNotEqual(rows[name]['evidence_latest_export'], 'complete', name)

    def test_a_failure_recovered_before_the_batch_went_on_ends_there(self):
        row = scenarios()['recovered_failure_then_the_batch_went_on']
        self.assertTrue(row['resumed'])
        self.assertEqual(row['evidence_latest_export'], 'complete')
        self.assertEqual(row['recovery_deadline_s'], None)
        self.assertIn('evidence_failure_passed', [item['kind'] for item in row['timeline']])

    def test_publication_says_only_what_was_shown(self):
        row = scenarios()['publication_needs_more_than_a_local_copy']
        self.assertEqual(row['status_after_each_step'], ['verified_local', 'operator_recorded', 'published'])
        self.assertEqual(row['adapter_received'], sorted(ep.PUBLISHED_FILES))

    def test_the_peer_peak_reaches_published_text_beside_the_mean_the_gate_reads(self):
        peers = scenarios()['one_bad_peer_beside_a_passing_mean']['published_first_run_peers']
        self.assertGreater(peers['loss_estimate_peer_peak'], 0.19)
        self.assertLess(peers['loss_estimate_peak_per_second_mean'], 0.01)
        self.assertEqual(peers['loss_estimate_peer_peak_bot'], 1)


if __name__ == '__main__':
    unittest.main()
