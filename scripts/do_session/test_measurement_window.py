"""The window proof over deterministic files: one complete tree, one thing broken, the exact reason expected.

These timelines are mocked and nothing ran, so a 60 or 300 s here is arithmetic. ``test_measurement_integration`` runs real binaries in real time.
"""
import csv
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / 'quick_stress'))
import sample_host  # noqa: E402

import measurement_fixtures as fx  # noqa: E402
import measurement_window as mw  # noqa: E402

NS = mw.NS


class Base(unittest.TestCase):
    def tree(self, **options):
        root = tempfile.mkdtemp(prefix='omega-window-')
        self.addCleanup(shutil.rmtree, root, True)
        return fx.Tree(root, **options)

    def codes(self, proof):
        return sorted({item['code'] for item in proof['reasons']})

    def assert_complete(self, tree, **options):
        proof = tree.prove(**options)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        return proof

    def assert_reason(self, tree, code, status=None, **options):
        proof = tree.prove(**options)
        self.assertIn(code, self.codes(proof), proof['reasons'])
        if status is not None:
            self.assertEqual(proof['status'], status, proof['reasons'])
        self.assertNotEqual(proof['status'], mw.COMPLETE)
        return proof


class FreezeOrder(Base):
    """A counter snapshot proves only what came before it."""

    def test_a_normal_freeze_after_the_end_is_accepted(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=tree.timeline.end + 2_000_000))
        self.assert_complete(tree)

    def test_a_freeze_exactly_at_the_end_with_its_acknowledgment_is_accepted(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'ack_end', lambda row: row.update(mono_ns=tree.timeline.end, lateness_ns=0))
        tree.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=tree.timeline.end))
        self.assert_complete(tree)

    def test_counters_frozen_before_the_end_cannot_prove_it(self):
        for offset in (mw.NS, 1):
            with self.subTest(offset=offset):
                tree = self.tree()
                tree.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=tree.timeline.end - offset))
                self.assert_reason(tree, 'frozen_before_end', mw.INCONCLUSIVE)

    def test_a_freeze_with_no_real_time_cannot_prove_it(self):
        for change in (lambda row: row.pop('mono_ns'), lambda row: row.update(mono_ns=None), lambda row: row.update(mono_ns='late'), lambda row: row.update(mono_ns=True), lambda row: row.update(mono_ns=-1), lambda row: row.update(mono_ns=1.5)):
            tree = self.tree()
            tree.edit_shard_row(0, 'freeze', change)
            self.assert_reason(tree, 'freeze_time_missing', mw.INCONCLUSIVE)

    def test_a_freeze_timed_before_its_end_acknowledgment(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'ack_end', lambda row: row.update(mono_ns=tree.timeline.end + 5_000_000))
        tree.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=tree.timeline.end + 1_000_000))
        self.assert_reason(tree, 'frozen_before_end_acknowledgment', mw.INCONCLUSIVE)

    def test_a_freeze_written_before_its_end_acknowledgment(self):
        tree = self.tree()

        def swap(rows):
            ack = next(row for row in rows if row.get('k') == 'ack_end')
            freeze = next(row for row in rows if row.get('k') == 'freeze')
            ack['seq'], freeze['seq'] = freeze['seq'], ack['seq']
            rows.sort(key=lambda row: row['seq'])
        tree.edit_rows('bot/swarm/shard-1.ndjson', swap)
        self.assert_reason(tree, 'frozen_before_end_acknowledgment', mw.INCONCLUSIVE)

    def test_a_drain_timed_before_the_freeze(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=tree.timeline.drain + 2_000_000))
        self.assert_reason(tree, 'drained_before_freeze')

    def test_a_shard_that_stayed_must_show_its_drain(self):
        tree = self.tree()
        tree.drop_shard_rows(0, 'drain_start')
        self.assert_reason(tree, 'drain_missing', mw.INCONCLUSIVE)

    def test_a_drain_with_no_time(self):
        for change in (lambda row: row.pop('mono_ns'), lambda row: row.update(mono_ns='late')):
            tree = self.tree()
            tree.edit_shard_row(0, 'drain_start', change)
            self.assert_reason(tree, 'drain_time_missing', mw.INCONCLUSIVE)

    def test_a_second_boundary_row_is_a_contradiction(self):
        for kind in ('ack_start', 'ack_end', 'freeze', 'drain_start', 'window_observed'):
            with self.subTest(kind=kind):
                tree = self.tree()

                def double(rows):
                    index = next(position for position, row in enumerate(rows) if row.get('k') == kind)
                    rows.insert(index + 1, dict(rows[index]))
                    for position, row in enumerate(rows):
                        row['seq'] = position
                tree.edit_rows('bot/swarm/shard-1.ndjson', double)
                self.assert_reason(tree, 'boundary_contradiction', mw.INCONCLUSIVE)

    def test_acknowledgments_out_of_order_are_a_contradiction(self):
        tree = self.tree()

        def swap(rows):
            start = next(row for row in rows if row.get('k') == 'ack_start')
            end = next(row for row in rows if row.get('k') == 'ack_end')
            start['seq'], end['seq'] = end['seq'], start['seq']
            rows.sort(key=lambda row: row['seq'])
        tree.edit_rows('bot/swarm/shard-1.ndjson', swap)
        self.assert_reason(tree, 'boundary_contradiction', mw.INCONCLUSIVE)


class CompleteWindows(Base):
    def test_a_complete_60_s_tree(self):
        proof = self.assert_complete(self.tree(hold_s=60))
        self.assertTrue(proof['facts']['contract_hold'])
        self.assertEqual(proof['facts']['input']['scheduled_total'], 8 * 60 * 30)
        self.assertEqual(proof['facts']['input']['below_minimum'], [])
        self.assertFalse(proof['establishes_capacity'])

    def test_a_complete_300_s_tree(self):
        self.assert_complete(self.tree(hold_s=300))

    def test_a_short_hold_is_only_ever_allowed_when_asked_for_and_says_so(self):
        tree = self.tree(hold_s=5)
        self.assert_reason(tree, 'non_contract_hold', mw.INCONCLUSIVE)
        proof = tree.prove(allow_short_hold=True)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertFalse(proof['facts']['contract_hold'])

    def test_the_proof_holds_no_gate_verdicts(self):
        facts = self.tree().prove()['facts']
        self.assertNotIn('passed', json.dumps(facts))
        self.assertNotIn('p95', json.dumps(facts))


class ReadinessAndAcknowledgments(Base):
    def test_a_window_that_starts_inside_the_warmup_is_invalid(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/window.json', lambda d: d.update(final_auth_ns=tree.timeline.start - NS))
        self.assert_reason(tree, 'warmup_violated', mw.INVALID)

    def test_a_readiness_timeout_never_has_a_window(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/window.json', lambda d: d.update(status='not_established', reason='readiness_timeout', start_ns=None, end_ns=None))
        proof = self.assert_reason(tree, 'window_not_established', mw.INVALID)
        self.assertIn('readiness_timeout', proof['reasons'][0]['detail'])

    def test_a_late_join_slot_is_a_stagger_violation(self):
        tree = self.tree()
        tree.edit_shard_row(2, 'join', lambda row: row.update(actual_ns=row['scheduled_ns'] + 101_000_000))
        self.assert_reason(tree, 'global_stagger_violated', mw.INVALID)

    def test_exactly_the_stagger_tolerance_is_allowed(self):
        tree = self.tree()
        tree.edit_shard_row(2, 'join', lambda row: row.update(actual_ns=row['scheduled_ns'] + 100_000_000))
        self.assert_complete(tree)

    def test_poll_starvation_anywhere_in_the_shards_life_is_invalid(self):
        tree = self.tree()
        tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=501_000_000))
        self.assert_reason(tree, 'poll_starvation', mw.INVALID)

    def test_a_shard_that_never_reported_polling_is_not_assumed_live(self):
        tree = self.tree()
        tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=None))
        self.assert_reason(tree, 'poll_liveness_missing')

    def test_a_late_start_acknowledgment_is_starvation(self):
        tree = self.tree()
        tree.edit_shard_row(3, 'ack_start', lambda row: row.update(mono_ns=tree.timeline.start + 501_000_000))
        self.assert_reason(tree, 'poll_starvation', mw.INVALID)

    def test_a_missing_end_acknowledgment_is_invalid(self):
        tree = self.tree()
        tree.drop_shard_rows(0, 'ack_end')
        self.assert_reason(tree, 'missing_acknowledgment', mw.INVALID)

    def test_a_shard_that_saw_the_window_after_it_began_is_invalid(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'window_observed', lambda row: row.update(mono_ns=tree.timeline.start + 1))
        self.assert_reason(tree, 'window_observed_late', mw.INVALID)

    def test_a_window_published_after_its_start_is_not_future(self):
        tree = self.tree()

        def change(rows):
            for row in rows:
                if row.get('k') == 'window_published':
                    row['mono_ns'] = tree.timeline.start
        tree.edit_rows('bot/swarm/coordinator.ndjson', change)
        self.assert_reason(tree, 'window_not_future', mw.INVALID)

    def test_an_early_shard_exit_is_invalid(self):
        tree = self.tree()
        tree.edit_shard_row(2, 'footer', lambda row: row.update(left_early=True))
        tree.edit_json('bot/swarm/window.json', lambda d: d.update(status='window_incomplete'))
        proof = self.assert_reason(tree, 'early_shard_exit', mw.INVALID)
        self.assertIn('window_incomplete', self.codes(proof))

    def test_counters_frozen_after_the_drain_started_are_invalid(self):
        tree = self.tree()

        def swap(rows):
            freeze = next(row for row in rows if row.get('k') == 'freeze')
            drain = next(row for row in rows if row.get('k') == 'drain_start')
            freeze['seq'], drain['seq'] = drain['seq'], freeze['seq']
            rows.sort(key=lambda row: row['seq'])
        tree.edit_rows('bot/swarm/shard-1.ndjson', swap)
        self.assert_reason(tree, 'drained_before_freeze', mw.INVALID)

    def test_a_drain_inside_the_window_is_invalid(self):
        tree = self.tree()
        tree.edit_shard_row(1, 'drain_start', lambda row: row.update(mono_ns=tree.timeline.end - 1))
        self.assert_reason(tree, 'drained_before_end', mw.INVALID)

    def test_a_shard_with_no_freeze_is_invalid(self):
        tree = self.tree()
        tree.drop_shard_rows(0, 'freeze')
        self.assert_reason(tree, 'counters_not_frozen', mw.INVALID)

    def test_round_robin_ownership_is_checked(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'header', lambda row: row.update(bots=[1, 2]))
        self.assert_reason(tree, 'ownership_mismatch')

    def test_a_thread_without_sim_geometry_is_invalid(self):
        tree = self.tree()
        tree.edit_shard_row(1, 'header', lambda row: row['geometry'].update(initialized_on_thread=False))
        self.assert_reason(tree, 'geometry_not_initialized', mw.INVALID)

    def test_workload_controls_are_held_to_the_trial_and_manifest(self):
        for key, value in (('seed', 2), ('threads', 2), ('behavior', 'combat'), ('input_hz', 20), ('join_stagger_ms', 50), ('hold_s', 61), ('bots', 9)):
            with self.subTest(key=key):
                tree = self.tree()
                tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update({key: value}))
                self.assert_reason(tree, 'workload_mismatch')

    def test_the_swarm_timing_must_be_the_frozen_schema(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update(end_guard_ns=0))
        self.assert_reason(tree, 'workload_mismatch')

    def test_a_deliberately_broken_build_can_never_prove_a_window(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update(faults=['Starve']))
        self.assert_reason(tree, 'fault_injection_build')

    def test_a_fault_build_can_never_prove_a_window_with_nothing_injected(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(build=dict(fault_injection=True)))
        self.assert_reason(tree, 'fault_injection_build', mw.INCONCLUSIVE)

    def test_a_build_that_does_not_state_itself_cannot_prove_a_window(self):
        for change in (lambda d: d.pop('build'), lambda d: d.update(build=None), lambda d: d.update(build=dict()), lambda d: d.update(build=dict(fault_injection='no')), lambda d: d.update(build=dict(fault_injection=0))):
            tree = self.tree()
            tree.edit_json('bot/swarm/swarm.json', change)
            self.assert_reason(tree, 'build_unstated', mw.INCONCLUSIVE)

    def test_faults_that_are_not_stated_are_not_assumed_absent(self):
        for change in (lambda d: d['controls'].pop('faults'), lambda d: d['controls'].update(faults=None), lambda d: d['controls'].update(faults='none')):
            tree = self.tree()
            tree.edit_json('bot/swarm/swarm.json', change)
            self.assert_reason(tree, 'workload_mismatch', mw.INCONCLUSIVE)

    def test_a_final_authentication_past_the_bound_cannot_stand(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update(readiness_timeout_s=0.1))
        self.assert_reason(tree, 'readiness_bound_exceeded', mw.INVALID)
        tree = self.tree()
        bound = tree.timeline.final_auth / NS
        tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update(readiness_timeout_s=bound))
        self.assert_complete(tree)
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].pop('readiness_timeout_s'))
        self.assert_reason(tree, 'window_boundaries_missing', mw.INCONCLUSIVE)


class OfferedInput(Base):
    def test_exactly_99_percent_is_valid_for_each_bot(self):
        tree = self.tree()
        tree.edit_frozen_bot(3, lambda b: b.update(scheduled=1800, sent=1782))
        proof = self.assert_complete(tree)
        self.assertEqual(proof['facts']['input']['worst_ratio'], 0.99)

    def test_one_frame_below_99_percent_is_invalid_offered_load(self):
        tree = self.tree()
        tree.edit_frozen_bot(3, lambda b: b.update(scheduled=1800, sent=1781))
        self.assert_reason(tree, 'offered_input_below_minimum', mw.INVALID)

    def test_a_pooled_average_cannot_hide_one_starved_bot(self):
        tree = self.tree(target=100)
        tree.edit_frozen_bot(100, lambda b: b.update(sent=1))     # 99.01% across the swarm
        proof = self.assert_reason(tree, 'offered_input_below_minimum', mw.INVALID)
        self.assertEqual(proof['facts']['input']['below_minimum'], [100])

    def test_a_dead_but_connected_bot_that_keeps_sending_idle_frames_is_valid(self):
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.update(alive=False, dead_frames=900))
        proof = self.assert_complete(tree)
        self.assertEqual(proof['facts']['input']['dead_frames_total'], 900)

    def test_a_connected_bot_that_stopped_sending_is_invalid_offered_load(self):
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Running', sent=0, last_input_ns=None))
        self.assert_reason(tree, 'offered_input_below_minimum', mw.INVALID)

    def test_a_missing_counter_is_missing_not_zero(self):
        for field in ('sent', 'scheduled', 'send_errors'):
            with self.subTest(field=field):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update({field: None}))
                self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)
        tree = self.tree()
        tree.edit_shard_row(1, 'freeze', lambda row: row.update(bots=[]))
        self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)

    def test_no_required_frozen_field_can_read_as_clean_unless_it_is_a_real_count(self):
        """Removed, null, text, boolean, float and negative, one field at a time, on one otherwise perfect record."""
        for field in mw.FROZEN_COUNTS:
            for value in (mw.__name__, None, 'zero', True, False, 1.5, -1):    # the module name stands for removal
                with self.subTest(field=field, value=value):
                    tree = self.tree()
                    if value == mw.__name__:
                        tree.edit_frozen_bot(2, lambda b: b.pop(field))
                    else:
                        tree.edit_frozen_bot(2, lambda b: b.update({field: value}))
                    proof = tree.prove()
                    self.assertEqual(proof['status'], mw.INCONCLUSIVE, proof['reasons'])
                    self.assertIn('input_record_missing', self.codes(proof))

    def test_the_other_frozen_fields_are_checked_the_same_way(self):
        for field, value in (('phase', None), ('phase', 3), ('alive', None), ('alive', 'yes'), ('gap_buckets', None), ('gap_buckets', [0] * 7), ('gap_buckets', [-1] + [0] * 7), ('last_input_ns', 'late'), ('last_input_ns', -5),
                             ('disconnected', 'gone'), ('disconnected', dict(at_ns='soon', reason=1, expected=False)), ('disconnected', dict(at_ns=1, reason=None, expected=False)), ('disconnected', dict(at_ns=1, reason=1))):
            with self.subTest(field=field, value=value):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update({field: value}, scheduled_before_disconnect=0))
                proof = tree.prove()
                self.assertEqual(proof['status'], mw.INCONCLUSIVE, proof['reasons'])
                self.assertIn('input_record_missing', self.codes(proof))
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.pop('disconnected'))
        self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)

    def test_contradictory_frozen_values_are_not_believed(self):
        for change in (dict(dead_frames=1801), dict(last_input_ns=None), dict(scheduled=0)):
            with self.subTest(change=change):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update(change))
                self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)
        for offset in (0, NS, -1 - 60 * NS):
            with self.subTest(offset=offset):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update(last_input_ns=tree.timeline.end + offset))
                self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.update(last_input_ns=tree.timeline.end - 1))
        self.assert_complete(tree)

    def test_a_peer_sample_with_no_rtt_or_loss_is_no_sample(self):
        for bad in ([None, 0], ['fast', 0], [True, 0], [-1, 0], [12.5, None], [12.5, -1], [12.5, 1.5]):
            with self.subTest(bad=bad):
                tree = self.tree()

                def change(rows):
                    for row in rows:
                        if row.get('k') == 'sample':
                            for bot in row['bots']:
                                if bot[0] == 2:
                                    bot[-1] = [[bot[-1][0][0]] + bad]
                tree.edit_rows('bot/swarm/shard-1.ndjson', change)
                self.assert_reason(tree, 'peer_sample_coverage', mw.INVALID)

    def test_a_bot_error_is_invalid(self):
        for field in ('send_errors', 'errors', 'panics', 'decode_failures'):
            with self.subTest(field=field):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update({field: 1}))
                self.assert_reason(tree, 'bot_errors', mw.INVALID)

    def test_a_generator_socket_failure_is_invalid_offered_load(self):
        for field in ('socket_send_errors', 'socket_zero_sends', 'socket_receive_errors'):
            with self.subTest(field=field):
                tree = self.tree()
                tree.edit_frozen_bot(2, lambda b: b.update({field: 1}))
                self.assert_reason(tree, 'generator_socket_errors', mw.INVALID)
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.pop('socket_send_errors'))
        self.assert_reason(tree, 'input_record_missing', mw.INCONCLUSIVE)

    def test_an_impossible_schedule_is_refused(self):
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.update(scheduled=1000, sent=1000))
        self.assert_reason(tree, 'schedule_mismatch')
        tree = self.tree()
        tree.edit_frozen_bot(2, lambda b: b.update(sent=1801))
        self.assert_reason(tree, 'schedule_mismatch')

    def test_missing_peer_samples_are_missing_coverage(self):
        tree = self.tree()

        def strip(rows):
            for row in rows:
                if row.get('k') == 'sample':
                    for bot in row['bots']:
                        if bot[0] == 2:
                            bot[-1] = []
        tree.edit_rows('bot/swarm/shard-1.ndjson', strip)
        self.assert_reason(tree, 'peer_sample_coverage', mw.INVALID)


class Truncation(Base):
    def test_a_recorder_cut_inside_a_line(self):
        tree = self.tree()
        data = tree.path('bot/swarm/shard-1.ndjson').read_bytes()
        tree.path('bot/swarm/shard-1.ndjson').write_bytes(data[:len(data) // 2])
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_a_recorder_cut_at_a_line_boundary_has_no_footer(self):
        tree = self.tree()
        tree.edit_rows('bot/swarm/shard-1.ndjson', lambda rows: rows.pop())
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_a_row_lost_from_the_middle_breaks_the_numbering(self):
        tree = self.tree()
        tree.edit_rows('bot/swarm/shard-2.ndjson', lambda rows: rows.pop(10))
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_an_overwritten_recorder_carries_another_process_nonce(self):
        tree = self.tree()

        def replace(rows):
            for row in rows:
                row['nonce'] = 'another-process'
        tree.edit_rows('bot/swarm/shard-0.ndjson', replace)
        self.assert_reason(tree, 'recorder_overwritten', mw.INCONCLUSIVE)

    def test_a_recorder_failure_is_reported(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'footer', lambda row: row.update(recorder_failure='No space left on device'))
        self.assert_reason(tree, 'recorder_failed', mw.INCONCLUSIVE)

    def test_a_missing_shard_file(self):
        tree = self.tree()
        tree.path('bot/swarm/shard-3.ndjson').unlink()
        self.assert_reason(tree, 'shard_evidence_missing', mw.INCONCLUSIVE)

    def test_a_missing_window_file(self):
        tree = self.tree()
        tree.path('bot/swarm/window.json').unlink()
        self.assert_reason(tree, 'swarm_evidence_missing', mw.INCONCLUSIVE)

    def test_ticks_shorter_than_the_servers_own_count(self):
        tree = self.tree()
        lines = tree.path('game/telemetry/ticks.csv').read_text().splitlines()
        tree.path('game/telemetry/ticks.csv').write_text('\n'.join(lines[:-1]) + '\n')
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_a_server_that_never_finished_its_recorders(self):
        tree = self.tree()
        tree.path('game/telemetry/final.json').unlink()
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_population_rows_shorter_than_the_servers_own_count(self):
        tree = self.tree()
        tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] + 1))
        self.assert_reason(tree, 'recorder_truncated', mw.INCONCLUSIVE)

    def test_a_collector_cut_by_its_stop_signal_is_fine_if_it_bracketed_the_window(self):
        tree = self.tree()
        data = tree.path('bot/sampler.ndjson').read_bytes()
        tree.path('bot/sampler.ndjson').write_bytes(data[:-3])
        self.assert_complete(tree)

    def test_a_collector_that_never_reached_the_end_of_the_window(self):
        tree = self.tree()
        tree.edit_rows('bot/sampler.ndjson', lambda rows: rows.__delitem__(slice(20, None)))
        self.assert_reason(tree, 'collector_boundary_missing', mw.INCONCLUSIVE)

    def test_a_shard_that_does_not_say_whether_it_left_early_is_not_assumed_to_have_stayed(self):
        for change in (lambda row: row.pop('left_early'), lambda row: row.update(left_early=None), lambda row: row.update(left_early='no')):
            tree = self.tree()
            tree.edit_shard_row(1, 'footer', change)
            self.assert_reason(tree, 'poll_liveness_missing', mw.INCONCLUSIVE)

    def test_a_footer_that_does_not_mention_recorder_failure_does_not_mean_none(self):
        tree = self.tree()
        tree.edit_shard_row(1, 'footer', lambda row: row.pop('recorder_failure'))
        self.assert_reason(tree, 'recorder_failed', mw.INCONCLUSIVE)

    def test_a_window_that_does_not_say_which_shards_ended_is_not_assumed_clean(self):
        for field in ('panicked_shards', 'unjoined_shards'):
            for change in (lambda d: d.pop(field), lambda d: d.update({field: None})):
                with self.subTest(field=field):
                    tree = self.tree()
                    tree.edit_json('bot/swarm/window.json', change)
                    self.assert_reason(tree, 'swarm_evidence_missing', mw.INCONCLUSIVE)

    def test_a_bad_poll_gap_sample_is_not_liveness(self):
        for value in (None, 'quick', -1, True):
            tree = self.tree()
            tree.edit_shard_row(1, 'sample', lambda row: row.update(max_poll_gap_ns=value))
            self.assert_reason(tree, 'poll_liveness_missing', mw.INCONCLUSIVE)

    def test_a_silent_collector_inside_the_window(self):
        tree = self.tree()
        tree.edit_rows('bot/sampler.ndjson', lambda rows: rows.__delitem__(slice(10, 20)))
        self.assert_reason(tree, 'collector_gap', mw.INCONCLUSIVE)


class Population(Base):
    def edit_ticks(self, tree, edit):
        path = tree.path('game/telemetry/ticks.csv')
        with path.open(newline='') as handle:
            rows = list(csv.reader(handle))
        edit(rows)
        with path.open('w', newline='') as handle:
            csv.writer(handle).writerows(rows)

    def game_mono(self, tree, offset_s):
        return fx.to_game_mono(tree.timeline.start) + int(offset_s * NS)

    def test_one_tick_below_n_in_the_window_is_invalid_with_server_evidence(self):
        tree = self.tree()

        def change(rows):
            target = self.game_mono(tree, 30)
            for row in rows[1:]:
                if int(row[1]) >= target:
                    row[4] = str(tree.timeline.target - 1)
                    return
        self.edit_ticks(tree, change)
        proof = self.assert_reason(tree, 'population_lost_in_window', mw.INVALID)
        self.assertEqual(next(item for item in proof['reasons'] if item['code'] == 'population_lost_in_window')['category'], mw.SERVER)

    def test_a_peak_cannot_stand_in_for_continuity(self):
        tree = self.tree()

        def change(rows):
            target = self.game_mono(tree, 59)
            for row in rows[1:]:
                if int(row[1]) >= target:
                    row[4] = '0'
        self.edit_ticks(tree, change)
        self.assert_reason(tree, 'population_lost_in_window', mw.INVALID)

    def test_a_tick_number_gap_is_not_continuity(self):
        tree = self.tree()

        def change(rows):
            target = self.game_mono(tree, 30)
            index = next(i for i, row in enumerate(rows[1:], 1) if int(row[1]) >= target)
            for row in rows[index:]:
                row[2] = str(int(row[2]) + 5)
        self.edit_ticks(tree, change)
        self.assert_reason(tree, 'server_tick_gap', mw.INCONCLUSIVE)

    def test_a_disconnect_inside_the_window_is_recorded_and_excuses_only_that_bot(self):
        tree = self.tree()
        at = self.game_mono(tree, 30)

        def change(rows):
            target = next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot002')
            target['mono_ns'] = at
            target['reason'] = 7
        tree.edit_rows('game/telemetry/population.ndjson', change)
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=900, scheduled_before_disconnect=900, disconnected=dict(at_ns=tree.timeline.start + 30 * NS, reason=7, expected=False)))
        proof = self.assert_reason(tree, 'population_lost_in_window', mw.INVALID)
        self.assertNotIn('offered_input_below_minimum', self.codes(proof), 'its missing frames follow from the server disconnect')

    def disconnect_at(self, tree, bot, at):
        """The server's own record of this bot leaving at ``at``, on the swarm's clock."""
        def change(rows):
            target = next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot%03d' % bot)
            target['mono_ns'] = fx.to_game_mono(at)
            target['reason'] = 7
        tree.edit_rows('game/telemetry/population.ndjson', change)

    def test_a_disconnect_does_not_excuse_starvation_before_it(self):
        """Zero frames in the 30 s it was connected: its schedule was broken before any disconnect, and the raw counters stay for the scorer. Nothing here names who caused what."""
        tree = self.tree()
        at = tree.timeline.start + 30 * NS
        self.disconnect_at(tree, 2, at)
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=0, last_input_ns=None, scheduled_before_disconnect=900, disconnected=dict(at_ns=at, reason=7, expected=False)))
        proof = self.assert_reason(tree, 'offered_input_below_minimum', mw.INVALID)
        self.assertIn('population_lost_in_window', self.codes(proof), 'the server evidence stays too')
        row = next(item for item in proof['facts']['per_bot_input'] if item['bot'] == 2)
        self.assertEqual((row['sent'], row['scheduled'], row['scheduled_before_disconnect']), (0, 1800, 900))

    def test_a_disconnect_floor_is_exact_in_integers_with_one_interrupted_slot(self):
        for sent, starved in ((890, False), (889, True)):       # (890 + 1) / 900 is exactly 99%; (889 + 1) / 900 is below it
            with self.subTest(sent=sent):
                tree = self.tree()
                at = tree.timeline.start + 30 * NS
                self.disconnect_at(tree, 2, at)
                tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=sent, last_input_ns=at - 1000, scheduled_before_disconnect=900, disconnected=dict(at_ns=at, reason=7, expected=False)))
                self.assertEqual('offered_input_below_minimum' in self.codes(tree.prove()), starved)

    def test_a_disconnect_in_the_first_moments_owes_only_the_slot_it_interrupted(self):
        tree = self.tree()
        at = tree.timeline.start + 30_000_000
        self.disconnect_at(tree, 2, at)
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=0, last_input_ns=None, scheduled_before_disconnect=1, disconnected=dict(at_ns=at, reason=7, expected=False)))
        self.assertNotIn('offered_input_below_minimum', self.codes(tree.prove()))

    def test_peer_coverage_is_held_only_over_the_connected_part(self):
        tree = self.tree()
        at = tree.timeline.start + 30 * NS
        self.disconnect_at(tree, 2, at)
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=900, scheduled_before_disconnect=900, disconnected=dict(at_ns=at, reason=7, expected=False)))

        def strip(rows):
            for row in rows:
                if row.get('k') == 'sample':
                    for bot in row['bots']:
                        if bot[0] == 2:
                            bot[-1] = []
        tree.edit_rows('bot/swarm/shard-1.ndjson', strip)
        self.assert_reason(tree, 'peer_sample_coverage', mw.INVALID)

    def test_a_disconnect_needs_what_it_was_owed(self):
        for value in (None, 'many', -1, True, 1801):
            with self.subTest(value=value):
                tree = self.tree()
                at = tree.timeline.start + 30 * NS
                self.disconnect_at(tree, 2, at)
                tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=900, scheduled_before_disconnect=value, disconnected=dict(at_ns=at, reason=7, expected=False)))
                proof = tree.prove()
                self.assertIn('input_record_missing', self.codes(proof))
                self.assertNotEqual(proof['status'], mw.COMPLETE)

    def test_a_late_auth_inside_the_window_is_not_full_population(self):
        tree = self.tree()
        at = self.game_mono(tree, 1)

        def change(rows):
            next(row for row in rows if row.get('k') == 'auth' and row.get('name') == 'LoadBot001')['mono_ns'] = at
        tree.edit_rows('game/telemetry/population.ndjson', change)
        self.assert_reason(tree, 'population_lost_in_window', mw.INVALID)

    def test_a_missing_transition_is_missing_not_assumed(self):
        tree = self.tree()

        def change(rows):
            kept = [row for row in rows if not (row.get('k') == 'auth' and row.get('name') == 'LoadBot008')]
            for index, row in enumerate(kept):
                row['seq'] = index
            rows[:] = kept
        tree.edit_rows('game/telemetry/population.ndjson', change)
        tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] - 1))
        self.assert_reason(tree, 'server_auth_evidence_missing', mw.INCONCLUSIVE)

    def test_a_server_refused_join_is_named(self):
        tree = self.tree()

        def change(rows):
            footer = rows.pop()
            rows.append(dict(k='connect_rejected', peer=99, mono_ns=1, reason=4, seq=len(rows)))
            footer['seq'] = len(rows)
            rows.append(footer)
        tree.edit_rows('game/telemetry/population.ndjson', change)
        tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] + 1))
        self.assert_reason(tree, 'server_refused_a_join', mw.INVALID)

    def test_entity_identity_must_agree(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'auth', lambda row: row.update(entity_id=99))
        self.assert_reason(tree, 'entity_identity_mismatch')


class Clocks(Base):
    def test_different_monotonic_origins_and_a_large_wall_offset_still_map(self):
        # The tree's monotonic origins already differ by 20 s; a 37 s wall offset, known to the brackets, is just a mapping.
        proof = self.assert_complete(self.tree(game_wall_offset=37 * NS))
        self.assertLess(proof['facts']['clock']['boundary_half_width_ms'], 50)

    def test_an_offset_the_brackets_do_not_know_moves_the_interval_off_the_population(self):
        tree = self.tree()
        tree.brackets = dict(before=fx.bracket('before', fx.BOT_MONO_ORIGIN_WALL, 90 * NS), after=fx.bracket('after', fx.BOT_MONO_ORIGIN_WALL, 90 * NS))
        self.assertNotEqual(tree.prove()['status'], mw.COMPLETE)

    def test_a_missing_bracket(self):
        for name in ('before', 'after'):
            with self.subTest(name=name):
                tree = self.tree()
                tree.brackets = dict(tree.brackets)
                tree.brackets[name] = None
                self.assert_reason(tree, 'clock_mapping_missing', mw.INCONCLUSIVE)

    def test_a_bracket_with_no_readings_for_one_role(self):
        tree = self.tree()
        tree.brackets = json.loads(json.dumps(tree.brackets))
        tree.brackets['after']['roles']['game'] = []
        self.assert_reason(tree, 'clock_mapping_missing', mw.INCONCLUSIVE)

    def test_offset_drift_between_the_brackets_is_ambiguous(self):
        tree = self.tree()
        tree.brackets = dict(tree.brackets, after=fx.bracket('after', fx.BOT_MONO_ORIGIN_WALL + 200 * NS, 6 * NS))
        self.assert_reason(tree, 'clock_ambiguous', mw.INCONCLUSIVE)

    def test_a_wide_bracket_is_ambiguous(self):
        tree = self.tree()
        tree.brackets = dict(before=fx.bracket('before', fx.BOT_MONO_ORIGIN_WALL, 0, half_ns=3 * NS), after=tree.brackets['after'])
        self.assert_reason(tree, 'clock_ambiguous', mw.INCONCLUSIVE)

    def test_an_uncertainty_wider_than_the_margins_cannot_prove_population_at_the_boundary(self):
        tree = self.tree()
        # 1.5 s either way is inside the ambiguity cap but reaches past the swarm's last 1 s of margin once the disconnects move closer.
        tree.brackets = dict(before=fx.bracket('before', fx.BOT_MONO_ORIGIN_WALL, 0, half_ns=800_000_000), after=tree.brackets['after'])
        at = fx.to_game_mono(tree.timeline.end) + 500_000_000

        def change(rows):
            next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot001')['mono_ns'] = at
        tree.edit_rows('game/telemetry/population.ndjson', change)
        proof = self.assert_reason(tree, 'population_boundary_ambiguous', mw.INCONCLUSIVE)
        self.assertGreater(proof['facts']['clock']['boundary_half_width_ms'], 500)

    def test_a_stepped_wall_clock_is_refused(self):
        tree = self.tree()

        def step(rows):
            for row in rows:
                clock = row.get('clock')
                if clock and clock['mono_ns'] >= tree.timeline.start + 10 * NS:
                    clock['wall_before_ns'] += NS
                    clock['wall_after_ns'] += NS
        tree.edit_rows('bot/swarm/coordinator.ndjson', step)
        self.assert_reason(tree, 'clock_step', mw.INCONCLUSIVE)

    def test_no_wall_pair_near_a_boundary_is_missing_not_interpolated(self):
        tree = self.tree()

        def strip(rows):
            for row in rows:
                clock = row.get('clock')
                if clock and clock['mono_ns'] > tree.timeline.start + 10 * NS:
                    row.pop('clock')
        tree.edit_rows('bot/swarm/coordinator.ndjson', strip)
        self.assert_reason(tree, 'clock_mapping_missing', mw.INCONCLUSIVE)

    def test_a_reboot_between_the_brackets(self):
        tree = self.tree()
        tree.brackets = json.loads(json.dumps(tree.brackets))
        tree.brackets['after']['roles']['bot'][0]['boot_id'] = 'another-boot'
        self.assert_reason(tree, 'host_rebooted', mw.INCONCLUSIVE)

    def test_a_malformed_bracket_attempt_is_no_reading(self):
        tree = self.tree()
        tree.brackets = json.loads(json.dumps(tree.brackets))
        tree.brackets['after']['roles']['bot'][0]['after_ns'] = tree.brackets['after']['roles']['bot'][0]['before_ns'] - 1
        self.assert_reason(tree, 'clock_mapping_missing', mw.INCONCLUSIVE)


class Identity(Base):
    def edit_game_sampler(self, tree, edit):
        tree.edit_sampler('game', edit)

    def edit_bot_sampler(self, tree, edit):
        tree.edit_sampler('bot', edit)

    def test_a_reused_pid_has_another_start_time(self):
        tree = self.tree()

        def change(index, row):
            if index >= 25:
                row['procs']['game']['start_id'] = 'ticks:424242'
        self.edit_game_sampler(tree, change)
        self.assert_reason(tree, 'pid_reused', mw.INCONCLUSIVE)

    def test_a_collector_row_that_does_not_say_alive_is_not_alive(self):
        for change in (lambda facts: facts.pop('alive'), lambda facts: facts.update(alive=None)):
            tree = self.tree()
            self.edit_game_sampler(tree, lambda index, row: change(row['procs']['game']) if index == 25 else None)
            self.assert_reason(tree, 'process_lost_in_window', mw.INCONCLUSIVE)

    def test_a_process_that_vanished_mid_window(self):
        tree = self.tree()

        def change(index, row):
            if index == 25:
                row['procs'].pop('game')
        self.edit_game_sampler(tree, change)
        self.assert_reason(tree, 'process_lost_in_window', mw.INCONCLUSIVE)

    def test_a_recorder_written_by_another_process(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(pid=99))
        self.assert_reason(tree, 'recorder_overwritten', mw.INCONCLUSIVE)
        tree = self.tree()
        tree.edit_json('game/telemetry/process.json', lambda d: d.update(kernel_start_id='ticks:1'))
        self.assert_reason(tree, 'pid_reused', mw.INCONCLUSIVE)

    def test_an_identity_an_earlier_run_used(self):
        tree = self.tree()
        self.assert_reason(tree, 'process_identity_reused', mw.INCONCLUSIVE, prior=dict(game=dict(processes={(3001, 'ticks:8001', 'boot-game')}, inodes=set())))

    def test_a_socket_inode_an_earlier_run_used(self):
        tree = self.tree()
        self.assert_reason(tree, 'socket_identity_reused', mw.INCONCLUSIVE, prior=dict(game=dict(processes=set(), inodes={'game-socket-8081'})))
        self.assert_reason(tree, 'socket_identity_reused', mw.INCONCLUSIVE, prior=dict(bot=dict(processes=set(), inodes={'bot-socket-40001'})))

    def test_a_socket_that_changed_inode_mid_window(self):
        tree = self.tree()

        def change(index, row):
            if index >= 25:
                row['procs']['game']['sockets'][0]['inode'] = 'another'
        self.edit_game_sampler(tree, change)
        self.assert_reason(tree, 'socket_identity_changed', mw.INCONCLUSIVE)

    def test_a_counter_that_moved_backward(self):
        tree = self.tree()

        def change(index, row):
            row['procs']['game']['sockets'][0]['drops'] = 5 if index < 25 else 1
        self.edit_game_sampler(tree, change)
        self.assert_reason(tree, 'socket_counter_reset', mw.INCONCLUSIVE)

    def test_missing_socket_counters_fail_when_required_and_never_read_as_zero(self):
        tree = self.tree()

        def change(index, row):
            row['procs']['bot']['sockets'][0]['drops'] = None
        self.edit_bot_sampler(tree, change)
        self.assert_reason(tree, 'socket_counters_missing', mw.INCONCLUSIVE)
        proof = self.assert_complete(tree, require_counters=False)
        self.assertEqual(proof['facts']['bot_host']['sockets_without_counters'], 1)
        self.assertIsNone(proof['facts']['bot_host']['socket_drops_total'], 'unknown, not zero')
        self.assertFalse(proof['socket_counters_required'])

    def test_a_bot_with_no_socket_row(self):
        tree = self.tree()

        def change(index, row):
            row['procs']['bot']['sockets'].pop(0)
        self.edit_bot_sampler(tree, change)
        self.assert_reason(tree, 'socket_evidence_missing', mw.INCONCLUSIVE)

    def test_a_generator_socket_drop_is_invalid_offered_load(self):
        tree = self.tree()

        def change(index, row):
            row['procs']['bot']['sockets'][2]['drops'] = 0 if index < 25 else 1
        self.edit_bot_sampler(tree, change)
        self.assert_reason(tree, 'generator_socket_drops', mw.INVALID)

    def test_a_bad_drop_counter_is_never_a_counter(self):
        for role, edit in (('bot', self.edit_bot_sampler), ('game', self.edit_game_sampler)):
            for value in ('0', -1, True, 1.5):
                for where in ('every row', 'first row', 'one row'):
                    with self.subTest(role=role, value=value, where=where):
                        tree = self.tree()

                        def change(index, row):
                            if where == 'every row' or index == (3 if where == 'first row' else 10):    # the baseline, and one in the hold
                                row['procs'][role]['sockets'][0]['drops'] = value
                        edit(tree, change)
                        proof = tree.prove()
                        self.assertEqual(proof['status'], mw.INCONCLUSIVE, proof['reasons'])

    def test_a_counter_absent_from_only_part_of_the_interval_fails_even_when_counters_are_optional(self):
        tree = self.tree()

        def change(index, row):
            if index == 10:
                row['procs']['bot']['sockets'][0]['drops'] = None
        self.edit_bot_sampler(tree, change)
        proof = tree.prove(require_counters=False)
        self.assertEqual(proof['status'], mw.INCONCLUSIVE, proof['reasons'])

    def test_a_game_socket_drop_is_a_fact_for_the_scorer_not_a_broken_window(self):
        tree = self.tree()

        def change(index, row):
            row['procs']['game']['sockets'][0]['drops'] = 0 if index < 25 else 7
        self.edit_game_sampler(tree, change)
        proof = self.assert_complete(tree)
        self.assertEqual(proof['facts']['game_host']['socket_drops'], 7)

    def test_host_kernel_counters_stay_separate_and_attribute_nothing(self):
        tree = self.tree()

        def change(index, row):
            row['udp']['snmp']['RcvbufErrors'] = index * 10
        self.edit_bot_sampler(tree, change)
        proof = self.assert_complete(tree)
        self.assertGreater(proof['facts']['bot_host']['kernel_counters']['RcvbufErrors'], 0)
        self.assertEqual(proof['facts']['bot_host']['socket_drops_total'], 0)


class CounterBoundaries(Base):
    """The counters that prove zero drops must have been read outside the interval, so a read that straddles a boundary can never be its baseline or its final."""
    ROLES = ('bot', 'game')

    def place(self, tree, role, row, read_start, read_end, extra_cost=1000):
        begin, finish = tree.role_mono(role, read_start), tree.role_mono(role, read_end)
        row.update(clock=tree.sampler_pair(role, begin), clock_after=tree.sampler_pair(role, finish), collector_ns=finish - begin + extra_cost)

    def measured(self, rows):
        return [row for row in rows if row.get('clock')]

    def straddle_start(self, tree, role, read_end_offset, drop=True):
        """The last read that began before the start finishes at start + offset, and sees a drop that later reads also see. Earlier reads saw none."""
        start = tree.timeline.start
        edge = tree.role_mono(role, start)

        def change(rows):
            measured = self.measured(rows)
            index = max(position for position, row in enumerate(measured) if row['clock']['mono_ns'] < edge)
            began = start - (edge - measured[index]['clock']['mono_ns'])
            self.place(tree, role, measured[index], began, start + read_end_offset)
            for position, row in enumerate(measured):
                row['procs'][role]['sockets'][0]['drops'] = 1 if drop and position >= index else 0
        tree.edit_rows(role + '/sampler.ndjson', change)

    def assert_counted(self, tree, role, count=1):
        proof = tree.prove()
        if role == 'bot':
            self.assertIn('generator_socket_drops', self.codes(proof), proof['reasons'])
            self.assertEqual(proof['status'], mw.INVALID)
            self.assertEqual(proof['facts']['bot_host']['socket_drops_total'], count)
        else:
            self.assertEqual(proof['facts']['game_host']['socket_drops'], count, proof['reasons'])
        return proof

    def test_a_drop_during_a_read_that_straddles_the_start_is_counted(self):
        """The review's executed reproduction: clock before the start, read finishing 100 ms after it, baseline and final both 1. It must not prove zero."""
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                self.straddle_start(tree, role, 100_000_000)
                self.assert_counted(tree, role)

    def test_a_read_ending_inside_the_uncertainty_before_the_start_is_not_a_baseline_either(self):
        """Finished 1 ms before the nominal start, but the earliest possible start is earlier than that on the game side, whose bracket is 5 ms wide."""
        tree = self.tree()
        self.straddle_start(tree, 'game', -1_000_000)
        self.assert_counted(tree, 'game')

    def test_a_read_finished_before_the_earliest_start_is_a_good_baseline(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                self.straddle_start(tree, role, -100_000_000, drop=False)
                proof = self.assert_complete(tree)
                drops = proof['facts']['bot_host']['socket_drops_total'] if role == 'bot' else proof['facts']['game_host']['socket_drops']
                self.assertEqual(drops, 0)

    def test_no_clean_read_before_the_start_is_inconclusive_never_zero(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                self.straddle_start(tree, role, 100_000_000)
                edge = tree.role_mono(role, tree.timeline.start)

                def change(rows):
                    index = max(position for position, row in enumerate(rows) if row.get('clock') and row['clock']['mono_ns'] < edge)
                    del rows[1:index]
                tree.edit_rows(role + '/sampler.ndjson', change)
                self.assert_reason(tree, 'collector_boundary_missing', mw.INCONCLUSIVE)

    def straddle_end(self, tree, role, keep_later, later_drop=1):
        """The first read after the end really began 100 ms before it, read a counter of 0, and a drop then landed before the end. The next read shows it, if there is one."""
        end = tree.timeline.end
        edge = tree.role_mono(role, end)

        def change(rows):
            measured = self.measured(rows)
            index = min(position for position, row in enumerate(measured) if row['clock']['mono_ns'] >= edge)
            self.place(tree, role, measured[index], end - 100_000_000, end + 100_000_000)
            for position, row in enumerate(measured):
                row['procs'][role]['sockets'][0]['drops'] = later_drop if position > index else 0
            if not keep_later:
                rows[:] = rows[:rows.index(measured[index]) + 1]
        tree.edit_rows(role + '/sampler.ndjson', change)

    def test_a_drop_after_a_read_that_straddles_the_end_is_counted_by_the_next_read(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                self.straddle_end(tree, role, keep_later=True)
                self.assert_counted(tree, role)

    def test_a_read_straddling_the_end_with_nothing_after_it_is_inconclusive_never_zero(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                self.straddle_end(tree, role, keep_later=False)
                self.assert_reason(tree, 'collector_boundary_missing', mw.INCONCLUSIVE)

    def test_a_row_that_cannot_bound_its_read_is_never_a_boundary(self):
        def no_after(row):
            row.pop('clock_after')

        def null_after(row):
            row['clock_after'] = None

        def no_cost(row):
            row.pop('collector_ns')

        def bad_cost(row):
            row['collector_ns'] = 'quick'

        def cost_below_span(row):
            row['clock_after'] = dict(row['clock_after'], mono_ns=row['clock']['mono_ns'] + 10 * mw.NS, wall_before_ns=row['clock']['wall_before_ns'] + 10 * mw.NS, wall_after_ns=row['clock']['wall_after_ns'] + 10 * mw.NS)

        def backward(row):
            row['clock_after'] = dict(row['clock_after'], mono_ns=row['clock']['mono_ns'] - 1)

        def stepped(row):
            row['clock_after'] = dict(row['clock_after'], wall_before_ns=row['clock']['wall_before_ns'] + mw.NS, wall_after_ns=row['clock']['wall_after_ns'] + mw.NS)

        for role, edit in (('bot', Identity.edit_bot_sampler), ('game', Identity.edit_game_sampler)):
            for breaker in (no_after, null_after, no_cost, bad_cost, cost_below_span, backward, stepped):
                with self.subTest(role=role, breaker=breaker.__name__):
                    tree = self.tree()
                    edit(self, tree, lambda index, row: breaker(row))
                    self.assert_reason(tree, 'collector_boundary_missing', mw.INCONCLUSIVE)

    def test_a_collector_that_was_descheduled_widens_its_own_read(self):
        """The pairs look tight, but the row says it cost 2 s around them, so its counters may be from up to 2 s either way."""
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                start = tree.timeline.start
                edge = tree.role_mono(role, start)

                def change(rows):
                    measured = self.measured(rows)
                    index = max(position for position, row in enumerate(measured) if row['clock']['mono_ns'] < edge)
                    began = start - (edge - measured[index]['clock']['mono_ns'])
                    self.place(tree, role, measured[index], began, began + 1000, extra_cost=2 * mw.NS)
                    for position, row in enumerate(measured):
                        row['procs'][role]['sockets'][0]['drops'] = 1 if position >= index else 0
                tree.edit_rows(role + '/sampler.ndjson', change)
                self.assert_counted(tree, role)

    def test_rows_out_of_order_cannot_supply_a_boundary(self):
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()

                def change(rows):
                    rows[10], rows[12] = rows[12], rows[10]
                tree.edit_rows(role + '/sampler.ndjson', change)
                self.assert_reason(tree, 'collector_boundary_missing', mw.INCONCLUSIVE)

    def test_rows_from_the_real_collector_function_cross_both_boundaries_on_both_roles(self):
        """The sampler's own row builder, over a /proc-shaped tree, with the read placed by the same clocks a descheduled collector would have."""
        for role in self.ROLES:
            with self.subTest(role=role):
                tree = self.tree()
                proc = pathlib.Path(tempfile.mkdtemp(prefix='omega-proc-'))
                self.addCleanup(shutil.rmtree, proc, True)
                (proc / 'net').mkdir()
                ports = [40000 + bot for bot in range(1, 9)] if role == 'bot' else [8081]
                pid = tree.identities[role][role]['pid']
                (proc / str(pid) / 'fd').mkdir(parents=True)
                for port in ports:
                    os.symlink('socket:[%s-socket-%d]' % (role, port), str(proc / str(pid) / 'fd' / str(port)))

                def table(drops):
                    lines = ['  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops']
                    lines += ['  %d: 00000000:%04X 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 %s-socket-%d 2 0000000000000000 %d' % (index, port, role, port, drops if index == 0 else 0) for index, port in enumerate(ports)]
                    (proc / 'net/udp').write_text('\n'.join(lines) + '\n')

                identity = tree.identities[role][role]
                start, end = tree.timeline.start, tree.timeline.end
                rows = [dict(kind='meta', schema=mw.schema()['id'])]
                reads = [(0, 0), (start - NS // 2, 0), (start - NS // 10, 1)]     # the third straddles the start and sees the drop
                reads += [(start + second * NS, 1) for second in range(1, tree.timeline.hold_s)]
                reads += [(end - NS // 10, 1), (end + NS // 2, 2)]                # the last but one straddles the end; a later drop is then seen
                for seq, (begin, drops) in enumerate(reads):
                    table(drops)
                    finish = begin + 200_000_000 if seq in (2, len(reads) - 2) else begin + 200_000
                    row = dict(procs={role: dict(pid=identity['pid'], alive=True)}, udp={})
                    with mock.patch.object(sample_host, 'start_id', lambda _pid: identity['start_id']), mock.patch.object(sample_host, 'clock_pair', lambda: tree.sampler_pair(role, tree.role_mono(role, finish))), \
                            mock.patch.object(sample_host, 'boot_id', lambda: identity['boot_id']):
                        sample_host.identity_row(row, seq, time.monotonic_ns(), tree.sampler_pair(role, tree.role_mono(role, begin)), proc_root=str(proc), linux=True)
                    row['collector_ns'] = finish - begin + 1000
                    rows.append(row)
                tree.put_rows(role + '/sampler.ndjson', rows)
                proof = tree.prove()
                self.assert_counted(tree, role, 2)
                if role == 'game':
                    self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])


class Schema(Base):
    MANIFEST = None

    def frozen(self):
        return dict(id=mw.schema()['id'], sha256=mw.schema_sha256())

    def recorder_edits(self, tree):
        """Every versioned document and header: what to call it, and how to apply one change to it."""
        edits = [('swarm.json', lambda change: tree.edit_json('bot/swarm/swarm.json', change)),
                 ('window.json', lambda change: tree.edit_json('bot/swarm/window.json', change)),
                 ('process.json', lambda change: tree.edit_json('game/telemetry/process.json', change)),
                 ('final.json', lambda change: tree.edit_json('game/telemetry/final.json', change))]
        for shard in range(tree.timeline.threads):
            edits.append(('shard-%d' % shard, lambda change, shard=shard: tree.edit_shard_row(shard, 'header', change)))

        def coordinator(change):
            def apply(rows):
                change(rows[0])
            tree.edit_rows('bot/swarm/coordinator.ndjson', apply)
        edits.append(('coordinator', coordinator))
        return edits

    def test_every_recorder_must_be_the_frozen_schema_even_when_the_manifest_hash_is_right(self):
        for index in range(7 + 1):
            for label, change in (('foreign', lambda doc: doc.update(schema='omega.measurement/999')), ('old', lambda doc: doc.update(schema='omega.measurement/2')), ('missing', lambda doc: doc.pop('schema')),
                                  ('null', lambda doc: doc.update(schema=None)), ('number', lambda doc: doc.update(schema=3))):
                tree = self.tree()
                name, edit = self.recorder_edits(tree)[index]
                with self.subTest(document=name, change=label):
                    edit(change)
                    proof = tree.prove(telemetry_schema=self.frozen())
                    self.assertIn('schema_mismatch', self.codes(proof), proof['reasons'])
                    self.assertNotEqual(proof['status'], mw.COMPLETE)

    def test_every_recorder_must_be_its_frozen_role(self):
        for index in range(7 + 1):
            for label, change in (('other', lambda doc: doc.update(role='controller')), ('missing', lambda doc: doc.pop('role'))):
                tree = self.tree()
                name, edit = self.recorder_edits(tree)[index]
                with self.subTest(document=name, change=label):
                    edit(change)
                    proof = tree.prove(telemetry_schema=self.frozen())
                    self.assertIn('schema_mismatch', self.codes(proof), proof['reasons'])
                    self.assertNotEqual(proof['status'], mw.COMPLETE)

    def test_a_game_recorder_cannot_stand_in_for_a_bot_recorder(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(role='game'))
        self.assert_reason(tree, 'schema_mismatch', mw.INCONCLUSIVE)
        tree = self.tree()
        tree.edit_json('game/telemetry/process.json', lambda d: d.update(role='bot'))
        self.assert_reason(tree, 'schema_mismatch', mw.INCONCLUSIVE)

    def test_a_collector_must_be_the_frozen_schema(self):
        for role in ('bot', 'game'):
            for label, change in (('foreign', lambda rows: rows[0].update(schema='omega.measurement/999')), ('missing', lambda rows: rows[0].pop('schema')), ('no header', lambda rows: rows.pop(0)),
                                  ('second header', lambda rows: rows.insert(5, dict(kind='meta', schema='omega.measurement/999')))):
                with self.subTest(role=role, change=label):
                    tree = self.tree()
                    tree.edit_rows(role + '/sampler.ndjson', change)
                    proof = tree.prove(telemetry_schema=self.frozen())
                    self.assertIn('schema_mismatch', self.codes(proof), proof['reasons'])
                    self.assertNotEqual(proof['status'], mw.COMPLETE)

    def test_a_clock_bracket_must_be_the_known_schema(self):
        for name in ('before', 'after'):
            for change in (lambda bracket: bracket.update(schema='another/9'), lambda bracket: bracket.pop('schema')):
                with self.subTest(name=name):
                    tree = self.tree()
                    tree.brackets = json.loads(json.dumps(tree.brackets))
                    change(tree.brackets[name])
                    self.assert_reason(tree, 'clock_mapping_missing', mw.INCONCLUSIVE)

    def test_a_shard_that_claims_another_shards_place(self):
        for change in (lambda row: row.update(shard=2), lambda row: row.update(shards=3), lambda row: row.pop('shard')):
            tree = self.tree()
            tree.edit_shard_row(1, 'header', change)
            self.assert_reason(tree, 'ownership_mismatch', mw.INCONCLUSIVE)

    def test_a_foreign_document_is_not_read_for_anything_else(self):
        tree = self.tree()
        tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(schema='omega.measurement/999', controls=dict(seed=99)))
        proof = tree.prove()
        self.assertEqual(self.codes(proof), ['schema_mismatch'], 'its controls mean nothing, so nothing is judged from them')

    def test_every_producer_in_this_repository_writes_the_frozen_id(self):
        repo = pathlib.Path(mw.__file__).resolve().parents[2]
        expected = mw.schema()['id']
        for relative, pattern in (('rust/load_test/src/measured.rs', r'pub const SCHEMA: &str = "([^"]+)"'), ('rust/server/src/measurement.rs', r'pub const WINDOW_EVIDENCE_SCHEMA: &str = "([^"]+)"'),
                                  ('scripts/quick_stress/sample_host.py', r'^MEASUREMENT_SCHEMA = "([^"]+)"')):
            with self.subTest(relative=relative):
                self.assertEqual(re.search(pattern, (repo / relative).read_text(), re.MULTILINE).group(1), expected)

    def test_the_manifest_must_freeze_this_schema(self):
        tree = self.tree()
        self.assert_complete(tree, telemetry_schema=dict(id=mw.schema()['id'], sha256=mw.schema_sha256()))
        self.assert_reason(tree, 'schema_mismatch', mw.INCONCLUSIVE, telemetry_schema=dict(id=mw.schema()['id'], sha256='6' * 64))
        self.assert_reason(tree, 'schema_mismatch', mw.INCONCLUSIVE, telemetry_schema=dict(id='omega.measurement/1', sha256=mw.schema_sha256()))

    def test_a_generator_failure_outranks_missing_evidence_in_the_status_and_keeps_both_reasons(self):
        tree = self.tree()
        tree.edit_shard_row(0, 'footer', lambda row: row.update(max_poll_gap_ns=NS))
        tree.path('game/telemetry/final.json').unlink()
        proof = tree.prove()
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertTrue({'poll_starvation', 'recorder_truncated'} <= set(self.codes(proof)))


if __name__ == '__main__':
    unittest.main()
