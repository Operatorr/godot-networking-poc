"""The window proof over deterministic files: one complete tree, one thing broken, the exact reason expected.

These timelines are mocked and nothing ran, so a 60 or 300 s here is arithmetic. ``test_measurement_integration`` runs real binaries in real time.
"""
import csv
import json
import shutil
import tempfile
import unittest

import measurement_fixtures as fx
import measurement_window as mw

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
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Running', sent=0))
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
        tree.edit_frozen_bot(2, lambda b: b.update(phase='Failed', sent=900, disconnected=dict(at_ns=tree.timeline.start + 30 * NS, reason=7, expected=False)))
        proof = self.assert_reason(tree, 'population_lost_in_window', mw.INVALID)
        self.assertNotIn('offered_input_below_minimum', self.codes(proof), 'its missing frames follow from the server disconnect')

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
        def change(rows):
            for index, row in enumerate(rows):
                edit(index, row)
        tree.edit_rows('game/sampler.ndjson', change)

    def edit_bot_sampler(self, tree, edit):
        def change(rows):
            for index, row in enumerate(rows):
                edit(index, row)
        tree.edit_rows('bot/sampler.ndjson', change)

    def test_a_reused_pid_has_another_start_time(self):
        tree = self.tree()

        def change(index, row):
            if index >= 25:
                row['procs']['game']['start_id'] = 'ticks:424242'
        self.edit_game_sampler(tree, change)
        self.assert_reason(tree, 'pid_reused', mw.INCONCLUSIVE)

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


class Schema(Base):
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
