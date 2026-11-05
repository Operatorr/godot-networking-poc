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
        found_after_the_commit = {'corrupt_bytes_found_after_the_commit_stop_the_session_and_keep_the_outcome', 'corrupt_bytes_found_by_recovery_at_wrap_up_withhold_the_claim', 'corrupt_seal_after_the_commit_refuses_resume', 'corrupt_seal_with_a_crash_after_the_fact_and_a_restored_transfer_refuses_resume'}
        refused_with_nothing_final_said = {'stop_request_failing_refuses_resume_and_dispatch', 'foreign_terminal_fact_refuses_resume_with_nothing_final_said'} | self.NOTHING_FORGOTTEN | self.NOTHING_FINAL     # the registry never heard, or must not: test_the_new_stop_paths_are_retained_with_no_successor
        self.assertEqual({name for name, row in searches.items() if not row['evidence']['verified']}, disputed | stopped_by_a_fact | found_after_the_commit | refused_with_nothing_final_said | set(self.LIFECYCLE_SCENARIOS) - set(self.IN_FLIGHT_FAILURES) | {'malformed_terminal_fact_stops_a_running_dispatch_with_nothing_final_said'})
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
        for name, _ in sf.OOM_STILL_THE_GAMES:
            self.assertEqual((scores['game_oom_' + name]['classification'], scores['game_oom_' + name]['game_exit']['kind']), (cs.CAPACITY_FAILURE, 'out_of_memory'), name)

    HELD_IN_FLIGHT = 'corrupt_file_in_flight_with_a_crash_before_its_bytes_refuses_as_unverified'
    NOTHING_FORGOTTEN = {'corrupt_seal_with_a_failed_sync_and_its_new_names_lost_starts_no_sibling', 'corrupt_file_with_a_failed_sync_and_its_new_names_lost_starts_no_sibling', 'a_crash_inside_a_comparison_decides_nothing_from_a_later_look'}
    NOTHING_FINAL = {'unsupported_terminal_fact_refuses_with_nothing_final_said', 'unsupported_execution_generation_refuses_with_nothing_final_said', 'a_number_too_large_for_a_float_in_a_retained_score_refuses_and_renders'}
    IN_FLIGHT_FAILURES = ('corrupt_seal_in_flight_with_a_crash_before_any_outcome_takes_the_failure', 'corrupt_file_in_flight_with_a_crash_before_any_outcome_takes_the_failure')
    LIFECYCLE_SCENARIOS = {'corrupt_seal_with_a_crash_before_its_bytes_refuses_as_unverified': ('stop_record_unverified', None),
                           'corrupt_file_with_a_crash_before_its_bytes_refuses_as_unverified': ('stop_record_unverified', None),
                           'corrupt_seal_with_a_crash_before_its_fact_stops_the_session': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_file_with_a_crash_before_its_fact_stops_the_session': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_seal_whose_fact_failed_its_fsync_stops_the_session_on_the_next_return': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_file_whose_fact_failed_its_fsync_stops_the_session_on_the_next_return': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_seal_in_flight_with_a_crash_before_any_outcome_takes_the_failure': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_file_in_flight_with_a_crash_before_any_outcome_takes_the_failure': ('terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                           'corrupt_file_in_flight_with_a_crash_before_its_bytes_refuses_as_unverified': ('stop_record_unverified', None),
                           'malformed_terminal_fact_refuses_resume_with_nothing_final_said': ('stop_record_unverified', None),
                           'malformed_execution_record_refuses_resume_with_nothing_final_said': ('stop_record_unverified', None)}

    def test_corrupt_bytes_are_retained_at_every_step_of_being_written_down(self):
        searches = json.loads((RETAINED / 'synthetic-searches.json').read_text())['scenarios']
        for name, (code, terminal) in self.LIFECYCLE_SCENARIOS.items():
            row = searches[name]
            self.assertEqual((row['resumed'], row['resume_code'], row['terminal_failure'], row['game_starts']), (False, code, terminal, 1), name)
            if name in self.IN_FLIGHT_FAILURES:
                self.assertEqual(([item['outcome'] for item in row['trials']], row['status']), (['INFRASTRUCTURE_FAILURE'], 'stopped_infrastructure_failure'), name)
                continue
            self.assertEqual(row['dispatch_code'], code, name)
            self.assertEqual(row['claim']['kind'], 'evidence_disagreement', name)
            self.assertEqual([item['outcome'] for item in row['trials']], [None if name == self.HELD_IN_FLIGHT else 'PASS'], 'the outcome stays, and nothing follows it. One not yet committed waits on the comparison that never ended')
            self.assertEqual(bool(row['trials'][0]['hard_facts']), terminal is not None, name)
            if terminal is None:
                self.assertTrue(row['trials'][0]['unverified_stop_records'], name)
        for name in ('corrupt_seal_whose_fact_failed_its_fsync_stops_the_session_on_the_next_return', 'corrupt_file_whose_fact_failed_its_fsync_stops_the_session_on_the_next_return'):
            self.assertEqual(searches[name]['first_refusal'], 'terminal_fact_unacknowledged')
        running = searches['malformed_terminal_fact_stops_a_running_dispatch_with_nothing_final_said']
        self.assertEqual((running['dispatch_code'], running['terminal_failure'], running['game_starts'], running['batch']), ('stop_record_unverified', None, 1, 'stopped'))
        self.assertEqual(running['claim']['kind'], 'evidence_disagreement')

    def test_a_comparison_cannot_be_forgotten_and_a_contradicted_account_is_no_fact(self):
        searches = json.loads((RETAINED / 'synthetic-searches.json').read_text())['scenarios']
        for name in sorted(self.NOTHING_FORGOTTEN):
            row = searches[name]
            self.assertEqual((row['resumed'], row['resume_code'], row['dispatch_code'], row['terminal_failure']), (False, 'stop_record_unverified', 'stop_record_unverified', None), name)
            self.assertEqual(row['claim']['kind'], 'evidence_disagreement', name)
            self.assertIsNone(row['trials'][-1]['outcome'], name)
            self.assertTrue(any(item['record'].startswith(cs.VALIDATION_GUARD_DIR) for item in row['trials'][-1]['unverified_stop_records']), name)
        for name in ('corrupt_seal_with_a_failed_sync_and_its_new_names_lost_starts_no_sibling', 'corrupt_file_with_a_failed_sync_and_its_new_names_lost_starts_no_sibling'):
            self.assertEqual((searches[name]['game_starts'], len(searches[name]['trials'])), (4, 4), 'the siblings never start')
        unguarded = searches['no_guard_means_nothing_is_compared_and_cleanup_still_goes_out']
        self.assertEqual((unguarded['dispatch_code'], unguarded['terminal_failure'], unguarded['game_starts'], unguarded['cleanup_requested']), ('directory_not_durable', None, 1, True))
        self.assertEqual(unguarded['trials'][0]['hard_facts'], [])
        for name in ('a_status_reply_naming_another_seal_says_nothing_and_stops_nothing', 'a_status_reply_of_another_session_says_nothing_and_stops_nothing'):
            row = searches[name]
            self.assertEqual((row['resumed'], row['terminal_failure'], row['trials'][0]['hard_facts'], row['trials'][0]['unverified_stop_records']), (True, None, [], []), name)
        for name in ('unsupported_terminal_fact_refuses_with_nothing_final_said', 'unsupported_execution_generation_refuses_with_nothing_final_said'):
            row = searches[name]
            self.assertEqual((row['resumed'], row['resume_code'], row['dispatch_code'], row['terminal_failure'], row['trials'][0]['hard_facts'], row['game_starts']), (False, 'stop_record_unverified', 'stop_record_unverified', None, [], 1), name)
            self.assertEqual(row['trials'][0]['outcome'], 'PASS', 'the outcome stays')
        enormous = searches['a_number_too_large_for_a_float_in_a_retained_score_refuses_and_renders']
        self.assertEqual(([item['outcome'] for item in enormous['trials']], enormous['resumed'], enormous['game_starts']), (['INCONCLUSIVE'], False, 1))
        self.assertNotEqual(enormous['terminal_failure'], 'INFRASTRUCTURE_FAILURE')
        self.assertEqual(enormous['claim']['kind'], 'evidence_disagreement')

    def test_the_new_stop_paths_are_retained_with_no_successor(self):
        searches = json.loads((RETAINED / 'synthetic-searches.json').read_text())['scenarios']
        for name, code, terminal in (('corrupt_seal_after_the_commit_refuses_resume', 'terminal_failure', 'INFRASTRUCTURE_FAILURE'), ('corrupt_seal_with_a_crash_after_the_fact_and_a_restored_transfer_refuses_resume', 'terminal_failure', 'INFRASTRUCTURE_FAILURE'),
                                     ('stop_request_failing_refuses_resume_and_dispatch', 'terminal_fact_unacknowledged', None), ('foreign_terminal_fact_refuses_resume_with_nothing_final_said', 'stop_record_unverified', None)):
            row = searches[name]
            self.assertEqual((row['resumed'], row['resume_code'], row['terminal_failure'], row['game_starts']), (False, code, terminal, 1), name)
            self.assertEqual(row['claim']['kind'], 'evidence_disagreement', name)
        self.assertEqual(searches['stop_request_failing_refuses_resume_and_dispatch']['dispatch_code'], 'terminal_fact_unacknowledged')
        self.assertEqual(searches['foreign_terminal_fact_refuses_resume_with_nothing_final_said']['trials'][0]['hard_facts'], [])
        self.assertTrue(searches['foreign_terminal_fact_refuses_resume_with_nothing_final_said']['trials'][0]['unverified_stop_records'])
        self.assertTrue(searches['corrupt_seal_after_the_commit_refuses_resume']['trials'][0]['hard_facts'][-1]['receipts'])
        self.assertEqual([row['outcome'] for row in searches['oom_kill_counted_only_elsewhere_in_the_unit_stops_with_no_refinement']['trials']], ['INCONCLUSIVE'])
        self.assertEqual(searches['oom_kill_of_the_game_beside_the_samplers_opens_the_bracket']['status'], 'no_passing_target')

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
