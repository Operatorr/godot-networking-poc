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
import scoring_fixtures as sf

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

    def test_nothing_earlier_was_dropped_and_each_new_scenario_lands_where_it_must(self):
        scores = json.loads((RETAINED / 'synthetic-scores.json').read_text())['scenarios']
        for name, row in scores.items():
            if name.startswith('generator_') and ('_beside_a_tick_overrun' in name or '_beside_a_demonstrated_crash' in name):
                self.assertEqual(row['classification'], cs.INCONCLUSIVE, name)
            if name.startswith('ramp_') and name.endswith('_beside_a_proven_overrun') and name != 'ramp_timeout_beside_a_proven_overrun':
                self.assertEqual(row['classification'], cs.INCONCLUSIVE, name)
        self.assertEqual(sum(name.startswith('generator_') and name.endswith('_beside_a_tick_overrun') for name in scores), 21)
        self.assertEqual(sum(name.startswith('generator_') and name.endswith('_beside_a_demonstrated_crash') for name in scores), 21)
        self.assertEqual(sum(name.endswith('_beside_a_proven_overrun') and name != 'ramp_timeout_beside_a_proven_overrun' for name in scores), 31)
        for name in ('game_sigkill_beside_an_earlier_host_oom_increment', 'game_sigkill_beside_a_later_host_oom_increment', 'game_sigkill_beside_a_host_oom_counter_reset', 'game_sigkill_beside_a_failed_rtt_gate', 'ramp_kick_of_a_bot_never_authenticated'):
            self.assertEqual(scores[name]['classification'], cs.INCONCLUSIVE, name)
        self.assertEqual(scores['game_panic_mid_window']['classification'], cs.CAPACITY_FAILURE, 'an early failure over a proven generator still stands')
        self.assertEqual(scores['tick_overrun_beside_a_host_oom_increment']['classification'], cs.CAPACITY_FAILURE)
        searches = json.loads((RETAINED / 'synthetic-searches.json').read_text())['scenarios']
        for name in ('tick_overrun_with_no_poll_liveness_stops_with_no_successor', 'tick_overrun_with_no_freeze_time_stops_with_no_successor', 'server_crash_with_no_poll_liveness_stops_with_no_successor', 'ramp_overrun_over_a_foreign_swarm_stops_with_no_refinement', 'ramp_overrun_over_a_foreign_game_stops_with_no_refinement', 'ramp_overrun_over_a_foreign_collector_stops_with_no_refinement', 'ramp_overrun_with_a_socket_never_read_stops_with_no_refinement'):
            self.assertEqual([row['outcome'] for row in searches[name]['trials']], ['INCONCLUSIVE'], name)
        for name in ('foreign_retained_score_is_refused_on_return', 'edited_retained_score_is_refused_on_return', 'foreign_retained_classification_is_refused_on_return', 'unfrozen_controller_refuses_a_foreign_retained_score'):
            self.assertEqual([row['outcome'] for row in searches[name]['trials']], ['INCONCLUSIVE'], name)
            self.assertEqual(searches[name]['claim']['kind'], 'evidence_disagreement', name)
            self.assertTrue(searches[name]['cleanup_requested'], name)
        withheld = searches['report_withholds_the_claim_when_a_retained_score_changed']
        self.assertEqual((withheld['claim']['kind'], withheld['journal_claim']['kind'], withheld['status']), ('evidence_disagreement', 'confirmed_observation', 'confirmed'))
        self.assertEqual([row['outcome'] for row in searches['unfrozen_controller_collects_and_decides_nothing']['trials']], ['INCOMPLETE'])
        self.assertEqual([row['outcome'] for row in searches['unfrozen_controller_recovers_a_validated_retained_score']['trials']], ['FAIL'])
        self.assertEqual([row['outcome'] for row in searches['frozen_controller_collects_and_scores_a_natural_end']['trials']], ['PASS'])
        disputed = {'foreign_retained_score_is_refused_on_return', 'edited_retained_score_is_refused_on_return', 'foreign_retained_classification_is_refused_on_return', 'unfrozen_controller_refuses_a_foreign_retained_score', 'report_withholds_the_claim_when_a_retained_score_changed'}
        stopped_by_a_fact = {'corrupt_bytes_on_return_outrank_a_retained_score', 'corrupt_bytes_on_return_outrank_a_retained_classification', 'corrupt_bytes_survive_a_second_crash_and_a_restored_transfer_after_a_retained_score',
                             'corrupt_bytes_survive_a_second_crash_and_a_restored_transfer_after_a_retained_classification', 'corrupt_bytes_in_a_confirmation_keep_its_siblings_untouched'}
        found_after_the_commit = {'corrupt_bytes_found_after_the_commit_stop_the_session_and_keep_the_outcome', 'corrupt_bytes_found_by_recovery_at_wrap_up_withhold_the_claim'}
        self.assertEqual({name for name, row in searches.items() if not row['evidence']['verified']}, disputed | stopped_by_a_fact | found_after_the_commit)
        for name in stopped_by_a_fact:
            row = searches[name]
            self.assertEqual((row['status'], row['terminal_failure'], row['resumed'], row['resume_code']), ('stopped_infrastructure_failure', 'INFRASTRUCTURE_FAILURE', False, 'terminal_failure'), name)
            self.assertEqual(row['trials'][-1]['outcome'], 'INFRASTRUCTURE_FAILURE', name)
            self.assertTrue(row['trials'][-1]['hard_facts'] and row['trials'][-1]['superseded_decisions'], name)
            self.assertEqual(row['evidence']['superseded_trials'], [item for item in row['evidence']['trials_with_stop_facts']], name)
            self.assertEqual(row['claim']['kind'], 'stopped_infrastructure_failure', name)
        self.assertEqual(len(searches['corrupt_bytes_in_a_confirmation_keep_its_siblings_untouched']['trials']), 4, 'repetitions 2 and 3 never ran')
        for name in found_after_the_commit:
            row = searches[name]
            self.assertEqual((row['claim']['kind'], row['terminal_failure']), ('evidence_disagreement', 'INFRASTRUCTURE_FAILURE'), name)
            self.assertEqual(row['trials'][0]['outcome'], 'PASS', 'a committed outcome stays')
        self.assertEqual(searches['corrupt_bytes_found_by_recovery_at_wrap_up_withhold_the_claim']['journal_claim']['kind'], 'confirmed_observation')
        for name in ('a_transfer_that_cannot_run_costs_a_retained_score_nothing', 'a_transfer_that_cannot_run_costs_a_committed_outcome_nothing'):
            self.assertEqual((searches[name]['trials'][0]['outcome'], searches[name]['terminal_failure'], searches[name]['resumed']), ('PASS', None, True), name)
        for name in ('ramp_overrun_with_the_last_read_just_before_the_abort_stops_with_no_refinement', 'ramp_overrun_with_the_last_read_possibly_before_the_abort_stops_with_no_refinement', 'ramp_overrun_with_a_socket_gone_by_the_read_after_the_abort_stops_with_no_refinement',
                     'ramp_kick_with_the_last_read_just_before_the_abort_stops_with_no_refinement', 'ramp_server_crash_with_the_last_read_just_before_the_abort_stops_with_no_refinement',
                     'oom_kill_of_a_reused_pid_stops_with_no_refinement', 'oom_kill_in_a_shared_cgroup_stops_with_no_refinement'):
            self.assertEqual([row['outcome'] for row in searches[name]['trials']], ['INCONCLUSIVE'], name)
        self.assertEqual(searches['oom_kill_matched_to_the_game_opens_the_bracket']['status'], 'no_passing_target')
        self.assertEqual(scores['game_oom_kill_matched_to_the_game']['classification'], cs.CAPACITY_FAILURE)
        self.assertEqual(scores['game_oom_kill_matched_to_the_game']['game_exit']['kind'], 'out_of_memory')
        self.assertEqual(scores['ramp_oom_kill_matched_to_the_game']['classification'], cs.CAPACITY_FAILURE)
        self.assertEqual(scores['ramp_oom_kill_with_the_last_read_before_the_abort']['classification'], cs.INCONCLUSIVE)
        self.assertEqual(scores['ramp_overflow_on_a_read_after_the_abort_beside_an_overrun']['classification'], cs.INCONCLUSIVE)
        for name, _, _ in sf.OOM_NOT_ATTRIBUTED:
            self.assertEqual((scores['game_oom_' + name]['classification'], scores['game_oom_' + name]['game_exit']['kind']), (cs.INCONCLUSIVE, 'killed_with_no_cause_on_record'), name)

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
