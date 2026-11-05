"""``capacity_scorer`` over deterministic recorder files: one complete tree, one thing changed, the exact decision expected.

Nothing ran to make these, so a 60 s window here is arithmetic and says nothing about any host. The real binaries' bytes are ``test_capacity_real``. Whole searches through the executor are ``test_capacity_search``.
"""
import copy
import fractions
import json
import shutil
import tempfile
import unittest

import capacity_report
import capacity_scorer as cs
import measurement_fixtures as fx
import measurement_window as mw
import run_checks
import scoring_fixtures as sf
import search

NS = mw.NS


class Base(unittest.TestCase):
    def scenario(self, **options):
        root = tempfile.mkdtemp(prefix='omega-score-')
        self.addCleanup(shutil.rmtree, root, True)
        return sf.Scenario(root, **options)

    def assertClassified(self, document, classification, code=None):
        self.assertEqual(document['classification'], classification, document['reasons'])
        self.assertEqual(document['outcome'], cs.OUTCOME_OF[classification])
        if code:
            self.assertIn(code, ' '.join(document['reasons']))
        return document


class TheCompleteCase(Base):
    def test_a_complete_healthy_window_is_a_valid_pass(self):
        document = self.assertClassified(self.scenario().score(), cs.VALID_PASS)
        self.assertEqual({gate['verdict'] for gate in document['gates'].values()}, {cs.PASS})
        self.assertEqual(document['validity']['verdict'], cs.VALID)
        self.assertFalse(document['establishes_capacity'], 'one run is never a capacity')

    def test_a_300_s_confirmation_window_scores_the_same_way(self):
        document = self.assertClassified(self.scenario(hold_s=300).score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['rtt_p95']['samples'], 8 * 300)
        self.assertEqual(document['gates']['enet_loss']['seconds'], 300)

    def test_the_answer_is_a_pure_function_of_the_bytes(self):
        scenario = self.scenario()
        self.assertEqual(cs.canonical(scenario.score()), cs.canonical(scenario.score()))

    def test_the_policy_is_pinned_in_every_score(self):
        document = self.scenario().score()
        self.assertEqual(document['policy']['tick_budget_ns'], 33_300_000)
        self.assertIn('nearest rank', document['policy']['rtt_quantile']['definition'])
        self.assertIn('never an average of per-bot quantiles', document['policy']['rtt_quantile']['definition'])
        self.assertIn('Not a measured fraction of datagrams', document['policy']['enet_loss']['estimator'])
        self.assertEqual(document['policy_sha256'], cs.POLICY_SHA256)

    def test_the_legacy_whole_run_report_decides_nothing(self):
        healthy, failed = self.scenario(), self.scenario()
        for scenario, status in ((healthy, 'perfect'), (failed, 'window_incomplete')):
            scenario.tree.path('bot/report.json').write_text(json.dumps(dict(legacy_whole_run_diagnostic=True, measured_window_status=status, total_errors=99, enet_packet_loss=0.9)))
        one, other = healthy.score(), failed.score()
        self.assertClassified(one, cs.VALID_PASS)
        self.assertClassified(other, cs.VALID_PASS)
        self.assertTrue(one['legacy_report']['decides_nothing'])
        self.assertEqual(one['legacy_report']['measured_window_status'], 'perfect')


class TickBudget(Base):
    def tight(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree)
        return scenario

    def test_a_tick_of_exactly_33_3_ms_is_not_above_it(self):
        scenario = self.tight()
        rows = sf.tick_rows(scenario.tree)
        for row in rows[1:]:
            row[3] = str(33_300_000)
        sf.write_ticks(scenario.tree, rows)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['tick_budget']['over_wide'], 0)

    def test_one_nanosecond_above_it_counts(self):
        scenario = self.tight()
        sf.set_slow_ticks(scenario.tree, 1, 33_300_001)
        self.assertEqual(scenario.score()['gates']['tick_budget']['over_wide'], 1)

    def test_exactly_one_percent_fails_and_one_tick_fewer_passes(self):
        probe = self.tight()
        total = sf.count_ticks(probe.tree)
        self.assertEqual(total % 100, 0, 'this fixture needs a whole 1 percent')
        exactly = self.tight()
        sf.set_slow_ticks(exactly.tree, total // 100, 40_000_000)
        document = self.assertClassified(exactly.score(), cs.CAPACITY_FAILURE, '33.3 ms')
        gate = document['gates']['tick_budget']
        self.assertEqual(gate['verdict'], cs.FAIL)
        self.assertEqual((gate['over_wide'], gate['ticks_wide']), (total // 100, total))
        self.assertEqual(gate['worst_possible_ratio']['exact'], '1/100', 'kept unrounded')
        fewer = self.tight()
        sf.set_slow_ticks(fewer.tree, total // 100 - 1, 40_000_000)
        document = self.assertClassified(fewer.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['tick_budget']['worst_possible_ratio']['exact'], str(fractions.Fraction(total // 100 - 1, total)))

    def test_a_ratio_that_depends_on_where_the_clocks_put_the_window_stays_unknown(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree, half_ns=900_000_000)
        total = sf.count_ticks(self.scenario().tree)
        sf.set_slow_ticks(scenario.tree, total // 100, 40_000_000)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        gate = document['gates']['tick_budget']
        self.assertEqual(gate['verdict'], cs.UNKNOWN)
        self.assertLess(gate['ticks_narrow'], gate['ticks_wide'])

    def test_a_clear_failure_survives_wide_clocks(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree, half_ns=900_000_000)
        sf.set_slow_ticks(scenario.tree, 180, 40_000_000)
        self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE)

    def test_a_clear_pass_survives_wide_clocks(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree, half_ns=900_000_000)
        sf.set_slow_ticks(scenario.tree, 2, 40_000_000)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.PASS)

    def test_ticks_outside_the_interval_are_not_counted(self):
        scenario = self.tight()
        rows = sf.tick_rows(scenario.tree)
        start = fx.to_game_mono(scenario.tree.timeline.start) - 2 * NS
        for row in rows[1:]:
            if int(row[1]) < start:
                row[3] = str(500_000_000)
        sf.write_ticks(scenario.tree, rows)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['tick_budget']['over_wide'], 0)

    def test_a_stepped_wall_clock_makes_server_side_gates_unknown(self):
        scenario = self.scenario()

        def step(rows):
            for row in rows:
                clock = row.get('clock')
                if clock and clock['mono_ns'] >= scenario.tree.timeline.start + 10 * NS:
                    clock['wall_before_ns'] += NS
                    clock['wall_after_ns'] += NS
        scenario.tree.edit_rows('bot/swarm/coordinator.ndjson', step)
        sf.set_slow_ticks(scenario.tree, 180, 40_000_000)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.UNKNOWN)


class PooledRtt(Base):
    def test_exactly_150_ms_fails_and_anything_below_passes(self):
        at_limit = self.scenario()
        sf.set_rtt(at_limit.tree, lambda bot, second: 150)
        document = self.assertClassified(at_limit.score(), cs.CAPACITY_FAILURE, 'RTT p95')
        self.assertEqual(document['gates']['rtt_p95']['p95_ms'], 150)
        below = self.scenario()
        sf.set_rtt(below.tree, lambda bot, second: 149.999)
        self.assertClassified(below.score(), cs.VALID_PASS)

    def test_the_producer_turns_whole_milliseconds_into_exactly_this_float(self):
        # rusty_enet gives Duration::from_millis(n), and bot.rs does as_secs_f64() * 1000.0.
        self.assertEqual(150_000_000 / 1e9 * 1000.0, 150.0)
        self.assertLess(149_000_000 / 1e9 * 1000.0, 150)

    def test_the_rank_is_nearest_rank_over_the_exact_pool(self):
        # 8 bots x 60 s = 480 samples, so rank ceil(0.95 x 480) = 456, and 24 samples may sit above it.
        def high(count):
            scenario = self.scenario()
            seen = []

            def value(bot, second):
                seen.append(1)
                return 500 if len(seen) <= count else 12.5
            sf.set_rtt(scenario.tree, value)
            return scenario.score()
        allowed = self.assertClassified(high(24), cs.VALID_PASS)
        self.assertEqual((allowed['gates']['rtt_p95']['rank'], allowed['gates']['rtt_p95']['samples']), (456, 480))
        self.assertEqual(allowed['gates']['rtt_p95']['p95_ms'], 12.5)
        self.assertEqual(high(25)['gates']['rtt_p95']['p95_ms'], 500)

    def test_small_pools_use_the_same_rank(self):
        self.assertEqual(cs.nearest_rank([1], 95), 1)
        self.assertEqual(cs.nearest_rank(list(range(1, 101)), 95), 95)
        self.assertEqual(cs.nearest_rank(list(range(1, 102)), 95), 96)
        self.assertEqual(cs.nearest_rank(list(range(1, 21)), 95), 19)

    def test_it_pools_samples_and_never_averages_per_bot_quantiles(self):
        # Three bots always slow: an average of per-bot p95s is (3 x 200 + 5 x 12.5) / 8, about 83, yet the pool's p95 is 200.
        slow_bots = self.scenario()
        sf.set_rtt(slow_bots.tree, lambda bot, second: 200 if bot <= 3 else 12.5)
        self.assertEqual(self.assertClassified(slow_bots.score(), cs.CAPACITY_FAILURE)['gates']['rtt_p95']['p95_ms'], 200)
        # Two bots each slow for 4 seconds: each of those bots has a p95 of 1000, so the average is about 259, yet only 8 of 480 pooled samples are slow.
        brief = self.scenario()
        sf.set_rtt(brief.tree, lambda bot, second: 1000 if bot <= 2 and second < 4 else 12.5)
        self.assertEqual(self.assertClassified(brief.score(), cs.VALID_PASS)['gates']['rtt_p95']['p95_ms'], 12.5)

    def test_ramp_and_drain_samples_are_not_in_the_pool(self):
        scenario = self.scenario()
        start, end = scenario.tree.timeline.start, scenario.tree.timeline.end

        def change(rows):
            for row in rows:
                if row.get('k') == 'sample':
                    for item in row['bots']:
                        item[-1] = [[sample[0], 5000 if not start <= sample[0] < end else sample[1], sample[2]] for sample in item[-1]]
        for shard in range(4):
            scenario.tree.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['rtt_p95']['max_ms'], 12.5)

    def test_a_sample_exactly_at_the_end_is_out_and_at_the_start_is_in(self):
        scenario = self.scenario()
        start, end = scenario.tree.timeline.start, scenario.tree.timeline.end

        def change(rows):
            row = next(row for row in rows if row.get('k') == 'sample')
            row['bots'][0][-1] = [[end, 5000, 0]]
            row['bots'][1][-1] = [[start, 77, 0]]
        scenario.tree.edit_rows('bot/swarm/shard-0.ndjson', change)
        self.assertEqual(scenario.score()['gates']['rtt_p95']['max_ms'], 77)

    def test_a_missing_sample_is_not_a_fast_one(self):
        scenario = self.scenario()
        sf.edit_peer_samples(scenario.tree, lambda bot, second, sample: None if bot == 3 else sample)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'too few in-window ENet samples')
        self.assertEqual(document['gates']['rtt_p95']['verdict'], cs.UNKNOWN)
        self.assertEqual(document['validity']['verdict'], cs.NOT_PROVEN, 'missing samples are missing evidence, and do not show a failed generator')

    def test_a_non_finite_or_negative_sample_refuses_the_gate(self):
        for bad in (float('inf'), -1):
            scenario = self.scenario()
            sf.set_rtt(scenario.tree, lambda bot, second: bad if bot == 1 and second == 3 else 12.5)
            document = scenario.score()
            self.assertEqual(document['gates']['rtt_p95']['verdict'], cs.UNKNOWN, bad)
            self.assertClassified(document, cs.INCONCLUSIVE)


class EnetLoss(Base):
    def test_exactly_two_percent_in_one_second_fails_exactly(self):
        # 25 bots: 32768 / (25 x 65536) is exactly 2/100. One bot, one second.
        at_limit = self.scenario(target=25)
        sf.set_loss(at_limit.tree, lambda bot, second: 32768 if bot == 1 and second == 7 else 0)
        document = self.assertClassified(at_limit.score(), cs.CAPACITY_FAILURE, 'ENet loss')
        gate = document['gates']['enet_loss']
        self.assertEqual(gate['per_second_mean_peak']['ratio']['exact'], '1/50')
        self.assertEqual(gate['seconds_at_or_above_limit'], [7])
        below = self.scenario(target=25)
        sf.set_loss(below.tree, lambda bot, second: 32767 if bot == 1 and second == 7 else 0)
        document = self.assertClassified(below.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['enet_loss']['per_second_mean_peak']['ratio']['exact'], '32767/1638400', 'no rounding moved this across the line')

    def test_one_second_excursion_fails_a_window_whose_average_is_fine(self):
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 3000 if second == 30 else 0)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE)
        gate = document['gates']['enet_loss']
        self.assertEqual(gate['seconds_at_or_above_limit'], [30])
        self.assertLess(gate['window_mean_of_seconds']['approximate'], 0.002, 'the whole-window mean hides what the per-second gate catches')

    def test_each_bot_weighs_the_same_whatever_its_peak(self):
        # One bot at 10 percent among 8 is a mean of 1.25 percent: its peer peak is reported, and it is no gate.
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 6554 if bot == 1 else 0)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        gate = document['gates']['enet_loss']
        self.assertEqual(gate['peer_peak']['bot'], 1)
        self.assertGreater(gate['peer_peak']['ratio']['approximate'], 0.09)
        self.assertLess(gate['per_second_mean_peak']['ratio']['approximate'], 0.02)

    def test_a_bot_with_two_readings_in_a_second_counts_once(self):
        readings = {1: [(0, 0, 6554), (1, 0, 6554)], 2: [(0, 0, 0)], 3: [(0, 0, 0)], 4: [(0, 0, 0)], 5: [(0, 0, 0)], 6: [(0, 0, 0)], 7: [(0, 0, 0)], 8: [(0, 0, 0)]}
        bins = cs.loss_bins({bot: [(at, rtt, loss) for at, rtt, loss in rows] for bot, rows in readings.items()}, {bot: 1 for bot in readings}, 0, 1)
        self.assertEqual(bins[0]['value'], fractions.Fraction(6554, 8 * 65536))

    def test_a_missing_reading_borrows_a_neighbour_and_is_never_zero(self):
        # Bot 1 sits at 20 percent, and with 8 bots that alone is a mean of 2.5 percent. Its sample in second 10 is missing.
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 13108 if bot == 1 else 0)
        sf.edit_peer_samples(scenario.tree, lambda bot, second, sample: None if bot == 1 and second == 10 else sample)
        gate = scenario.score()['gates']['enet_loss']
        self.assertEqual(gate['verdict'], cs.FAIL)
        self.assertEqual(gate['seconds_at_or_above_limit'][:12], list(range(12)), 'second 10 is still failing: a zero there would have hidden it')
        self.assertEqual(gate['borrowed_readings'], 1)

    def test_a_gap_too_long_to_borrow_across_stays_unknown(self):
        scenario = self.scenario()
        sf.edit_peer_samples(scenario.tree, lambda bot, second, sample: None if bot == 1 and 10 <= second < 16 else sample)
        document = scenario.score()
        self.assertEqual(document['gates']['enet_loss']['verdict'], cs.UNKNOWN)
        self.assertEqual(document['gates']['enet_loss']['seconds_without_coverage'], [12, 13])
        self.assertNotEqual(document['classification'], cs.VALID_PASS)

    def test_a_short_gap_is_tolerated_but_counted(self):
        scenario = self.scenario()
        sf.edit_peer_samples(scenario.tree, lambda bot, second, sample: None if bot == 1 and second == 10 else sample)
        gate = self.assertClassified(scenario.score(), cs.VALID_PASS)['gates']['enet_loss']
        self.assertEqual((gate['borrowed_readings'], gate['seconds_evaluated']), (1, 60))

    def test_a_failure_elsewhere_stands_even_if_another_second_is_unknown(self):
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 3000 if second == 40 else 0)
        sf.edit_peer_samples(scenario.tree, lambda bot, second, sample: None if bot == 1 and 10 <= second < 16 else sample)
        self.assertEqual(scenario.score()['gates']['enet_loss']['verdict'], cs.FAIL)

    def test_a_reading_above_the_estimators_scale_is_refused(self):
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 70000 if bot == 1 and second == 2 else 0)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE)

    def test_the_estimator_is_labelled_wherever_it_appears(self):
        document = self.scenario().score()
        self.assertIn('smoothed', document['gates']['enet_loss']['estimator'])
        self.assertIn('estimate', capacity_report.render_run(document))
        self.assertNotIn('packet loss', capacity_report.render_run(document).lower())

    def test_ticks_between_ten_second_epochs_hold_a_value_the_gate_can_read(self):
        # ENet moves this value at most every 10 s, so a whole hold of one reading is an ordinary series.
        scenario = self.scenario()
        sf.set_loss(scenario.tree, lambda bot, second: 1000)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['gates']['enet_loss']['per_second_mean_peak']['ratio']['exact'], '125/8192')


class GameSocket(Base):
    def test_zero_drops_passes_on_an_exact_count(self):
        document = self.scenario().score()
        self.assertEqual(document['gates']['game_socket_drops']['drops_in_widest_interval'], 0)

    def test_a_drop_proven_inside_is_a_capacity_failure(self):
        scenario = self.scenario()
        sf.game_drop(scenario.tree, 30, count=3)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, 'drops on the game socket')
        self.assertEqual(document['gates']['game_socket_drops']['drops_proven_inside'], 3)

    def test_a_drop_that_may_be_just_outside_proves_neither(self):
        scenario = self.scenario()
        sf.game_drop_before_any_window_read(scenario.tree)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        gate = document['gates']['game_socket_drops']
        self.assertEqual(gate['verdict'], cs.UNKNOWN)
        self.assertEqual((gate['drops_proven_inside'], gate['drops_at_the_uncertain_edge']), (0, 1))

    def test_a_missing_counter_is_not_zero(self):
        scenario = self.scenario()
        sf.foggy(scenario.tree)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['gates']['game_socket_drops']['verdict'], cs.UNKNOWN)

    def test_a_counter_moving_backward_refuses_everything(self):
        scenario = self.scenario()

        def rewind(index, row):
            for item in row['procs']['game']['sockets']:
                item['drops'] = 9 if index < 30 else 2
        scenario.tree.edit_sampler('game', rewind)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'socket_counter_reset')

    def test_host_wide_kernel_counters_never_decide(self):
        scenario = self.scenario()

        def noisy(index, row):
            row['udp']['snmp']['RcvbufErrors'] = index * 1000
        scenario.tree.edit_sampler('game', noisy)
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertGreater(document['diagnostics']['game_host_kernel_counters']['RcvbufErrors'], 0)


class OfferedLoad(Base):
    def test_exactly_99_percent_is_valid_and_one_frame_fewer_is_not(self):
        exact = self.scenario()
        exact.tree.edit_frozen_bot(3, lambda row: row.update(scheduled=1800, sent=1782))
        document = self.assertClassified(exact.score(), cs.VALID_PASS)
        self.assertEqual(document['offered_load']['worst_ratio']['exact'], '99/100')
        below = self.scenario()
        below.tree.edit_frozen_bot(3, lambda row: row.update(scheduled=1800, sent=1781))
        document = self.assertClassified(below.score(), cs.INVALID_LOAD, 'offered_input_below_minimum')
        self.assertEqual(document['validity']['offered_input'], cs.INVALID)
        self.assertEqual(document['offered_load']['bots_below_floor'], [3])

    def test_one_bot_is_held_to_it_however_good_the_total_is(self):
        scenario = self.scenario(target=25)
        scenario.tree.edit_frozen_bot(9, lambda row: row.update(sent=1000))
        document = self.assertClassified(scenario.score(), cs.INVALID_LOAD)
        self.assertGreater(document['offered_load']['sent_total'] / document['offered_load']['scheduled_total'], 0.98)

    def test_a_generator_socket_drop_is_invalid_load(self):
        scenario = self.scenario()
        sf.bot_drop(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INVALID_LOAD, 'generator_socket_drops')

    def test_a_missing_generator_counter_is_not_zero(self):
        scenario = self.scenario()

        def missing(index, row):
            for item in row['procs']['bot']['sockets']:
                item['drops'] = None
        scenario.tree.edit_sampler('bot', missing)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['validity']['generator_sockets'], cs.NOT_PROVEN)

    def test_a_dead_in_game_bot_still_sending_is_valid_load(self):
        scenario = self.scenario()
        scenario.tree.edit_frozen_bot(2, lambda row: row.update(alive=False, dead_frames=900))
        document = self.assertClassified(scenario.score(), cs.VALID_PASS)
        self.assertEqual(document['offered_load']['dead_frames_total'], 900)

    def test_bot_errors_of_every_kind(self):
        for change, classification in ((dict(panics=1), cs.INVALID_LOAD), (dict(errors=1), cs.INVALID_LOAD), (dict(send_errors=2), cs.INVALID_LOAD), (dict(socket_send_errors=1), cs.INVALID_LOAD),
                                       (dict(socket_receive_errors=1), cs.INVALID_LOAD), (dict(decode_failures=1), cs.INCONCLUSIVE)):
            scenario = self.scenario()
            scenario.tree.edit_frozen_bot(1, lambda row: row.update(change))
            document = self.assertClassified(scenario.score(), classification)
            self.assertEqual(document['gates']['bot_errors']['verdict'], cs.FAIL, change)

    def test_a_frozen_counter_that_is_missing_is_not_zero(self):
        for field in ('errors', 'panics', 'decode_failures', 'sent', 'scheduled', 'socket_send_errors'):
            scenario = self.scenario()
            scenario.tree.edit_frozen_bot(2, lambda row: row.pop(field))
            document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
            self.assertEqual(document['validity']['offered_input'], cs.NOT_PROVEN, field)

    def test_a_missing_shard_file_is_not_a_healthy_one(self):
        scenario = self.scenario()
        scenario.tree.path('bot/swarm/shard-2.ndjson').unlink()
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE)

    def test_cpu_and_gaps_are_no_gate(self):
        scenario = self.scenario()
        for shard in range(4):
            scenario.tree.edit_shard_row(shard, 'footer', lambda row: row.update(max_poll_gap_ns=499_000_000))
        scenario.tree.edit_frozen_bot(1, lambda row: row.update(gap_max_ns=400_000_000))
        self.assertClassified(scenario.score(), cs.VALID_PASS)


class Attribution(Base):
    def test_a_kick_with_a_healthy_generator_is_a_capacity_failure_and_not_generator_failure(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 30, reason=cs.REASON_KICKED, server_reason=0)
        proof = scenario.proof()
        self.assertIn('bot_errors', [item['code'] for item in proof['reasons'] if item['category'] == mw.GENERATOR], 'the prover cannot tell this error from any other')
        document = self.assertClassified(scenario.score(proof=proof), cs.CAPACITY_FAILURE, 'disconnected bots [2]')
        self.assertEqual(document['validity']['verdict'], cs.VALID)
        self.assertEqual(document['gates']['bot_errors']['errors_that_are_the_disconnect_itself'], 1)
        self.assertEqual(document['gates']['bot_errors']['independent'], 0)
        self.assertEqual(document['gates']['continuity']['verdict'], cs.FAIL)

    def test_frames_a_kicked_bot_never_sent_afterward_are_not_held_against_it(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 1, reason=cs.REASON_KICKED)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE)
        self.assertEqual(document['offered_load']['bots_below_floor'], [])
        worst = document['offered_load']['worst_ratio']
        self.assertLess(worst['approximate'], 0.1, 'the raw ratio is kept, and it is not what the floor judges')

    def test_starvation_before_the_disconnect_stays_visible(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 30, reason=cs.REASON_KICKED, sent=0)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'both the generator and the server failed')
        self.assertEqual(document['offered_load']['bots_below_floor'], [2])
        self.assertIn('offered_input_below_minimum', [item['code'] for item in document['validity']['independent_failures']])

    def test_one_slot_can_be_interrupted_and_two_cannot(self):
        ok = self.scenario()
        sf.lose_bot(ok.tree, 2, 30, reason=cs.REASON_KICKED, sent=890)   # 900 owed: (890 + 1) x 100 >= 900 x 99
        self.assertClassified(ok.score(), cs.CAPACITY_FAILURE)
        short = self.scenario()
        sf.lose_bot(short.tree, 2, 30, reason=cs.REASON_KICKED, sent=889)
        self.assertClassified(short.score(), cs.INCONCLUSIVE, 'both the generator and the server failed')

    def test_lag_in_seeing_a_disconnect_is_kept_apart_from_the_servers_event(self):
        scenario = self.scenario()
        # The server kicks it 1 s in. The bot sees that 400 ms later: 12 more frames fell due, and none were sent, because the poll was busy elsewhere.
        sf.lose_bot(scenario.tree, 2, 1.4, reason=cs.REASON_KICKED, server_at_s=1.0, sent=30)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE)
        row = next(item for item in document['offered_load']['per_bot'] if item['bot'] == 2)
        self.assertTrue(row['input_missing_only_after_the_server_event'])
        self.assertEqual(document['attribution']['input_missing_only_after_a_server_event'], [2])
        lost = row['disconnect']
        self.assertEqual(lost['scheduled_before_observation'], 42)
        self.assertLess(lost['scheduled_before_server_event'], 42)
        self.assertEqual(lost['order'], 'server_first')
        self.assertGreater(lost['observation_lag_ns'][0], 300 * 1_000_000)
        self.assertEqual(document['offered_load']['bots_below_floor'], [])
        self.assertIn('offered_input_below_minimum', document['inputs']['proof_reasons'], 'the proof still says what it saw')

    def test_starvation_before_the_servers_event_is_not_excused_by_the_lag(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 1.4, reason=cs.REASON_KICKED, server_at_s=1.0, sent=10)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'both the generator and the server failed')

    def test_clocks_that_cannot_place_the_server_event_do_not_excuse_it_either(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 1.4, reason=cs.REASON_KICKED, server_at_s=1.0, sent=30)
        scenario.tree.brackets = dict(scenario.tree.brackets, after=None)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'offered_input_below_minimum')

    def test_a_transport_timeout_alone_proves_no_cause(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 30, reason=0)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'cause is unknown')
        self.assertEqual(document['attribution']['departures'][0]['cause'], 'transport_timeout_unattributed')
        self.assertEqual(document['gates']['continuity']['verdict'], cs.FAIL, 'N/N is broken either way')
        self.assertEqual(document['validity']['verdict'], cs.VALID, 'and it is not generator failure either')

    def test_a_transport_timeout_beside_real_server_distress_is_attributed(self):
        for distress, label in ((lambda tree: sf.set_slow_ticks(tree, 180, 40_000_000), '33.3 ms'), (lambda tree: sf.game_drop(tree, 20), 'drops on the game socket')):
            scenario = self.scenario()
            sf.lose_bot(scenario.tree, 2, 30, reason=0)
            distress(scenario.tree)
            document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, label)
            self.assertEqual(document['attribution']['departures'][0]['cause'], 'transport_timeout_with_server_distress')

    def test_a_kick_stands_beside_a_timeout_with_no_cause(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 30, reason=cs.REASON_KICKED)
        sf.lose_bot(scenario.tree, 3, 31, reason=0)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, 'no cause on record')
        self.assertEqual({item['bot']: item['cause'] for item in document['attribution']['departures']}, {2: 'server_kick', 3: 'transport_timeout_unattributed'})

    def test_reasons_that_are_no_capacity_signal(self):
        for reason in (cs.REASON_SERVER_SHUTDOWN, 4, 5, 1, 77):
            scenario = self.scenario()
            sf.lose_bot(scenario.tree, 2, 30, reason=reason)
            self.assertClassified(scenario.score(), cs.INCONCLUSIVE)

    def test_a_server_row_the_bot_never_saw_is_still_lost_population(self):
        scenario = self.scenario()
        sf.server_row_only(scenario.tree, 2, 30)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'cause is unknown')
        self.assertEqual(document['attribution']['departures'][0]['source'], 'server_only')

    def test_a_bot_that_asked_to_leave_is_the_generators_doing(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 2, 30, reason=0)
        scenario.tree.edit_frozen_bot(2, lambda row: row.update(errors=0, disconnected=dict(row['disconnected'], expected=True)))
        document = scenario.score()
        self.assertIn('bot_quit_inside_the_window', [item['code'] for item in document['validity']['independent_failures']])
        self.assertNotEqual(document['classification'], cs.CAPACITY_FAILURE)

    def test_a_disconnect_that_the_bot_saw_after_the_end_cannot_be_placed(self):
        scenario = self.scenario()
        end = scenario.tree.timeline.end
        scenario.tree.edit_frozen_bot(2, lambda row: row.update(errors=1, disconnected=dict(at_ns=end + 500_000, reason=0, expected=False), scheduled_before_disconnect=row['scheduled']))
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['gates']['continuity']['verdict'], cs.UNKNOWN)

    def test_population_below_n_with_no_account_of_who(self):
        scenario = self.scenario()
        rows = sf.tick_rows(scenario.tree)
        rows[sf.ticks_in_window(scenario.tree, rows)[100]][4] = str(scenario.tree.timeline.target - 1)
        sf.write_ticks(scenario.tree, rows)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['gates']['continuity']['verdict'], cs.FAIL)

    def test_a_loss_only_in_the_clock_uncertainty_cannot_pass(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree, half_ns=900_000_000)

        def edit(rows):
            row = next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot002')
            row['mono_ns'] = fx.to_game_mono(scenario.tree.timeline.end) + 100_000_000
        scenario.tree.edit_rows('game/telemetry/population.ndjson', edit)
        document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE)
        self.assertEqual(document['gates']['continuity']['verdict'], cs.UNKNOWN)

    def test_generator_failure_alone_never_blames_the_server(self):
        for change in (lambda tree: tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=501_000_000)),
                       lambda tree: tree.drop_shard_rows(0, 'ack_end')):
            scenario = self.scenario()
            change(scenario.tree)
            document = self.assertClassified(scenario.score(), cs.INVALID_LOAD)
            self.assertEqual({gate['verdict'] for name, gate in document['gates'].items() if name == 'tick_budget'}, {cs.PASS})

    def test_a_generator_failure_beside_a_server_failure_cannot_be_separated(self):
        for server in (lambda tree: sf.set_slow_ticks(tree, 180, 40_000_000), lambda tree: sf.game_drop(tree, 20), lambda tree: sf.lose_bot(tree, 3, 30, cs.REASON_KICKED)):
            for generator in (lambda tree: tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=501_000_000)), lambda tree: sf.bot_drop(tree, 2), lambda tree: tree.edit_frozen_bot(4, lambda row: row.update(sent=1, last_input_ns=row['last_input_ns']))):
                scenario = self.scenario()
                server(scenario.tree)
                generator(scenario.tree)
                document = self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'nothing separates them')
                self.assertTrue(document['validity']['independent_failures'], 'the generator failure stays visible')


class GameProcess(Base):
    def crashed(self, code, signal, at_s=30, **options):
        scenario = self.scenario(**options)
        sf.game_died(scenario.tree, at_s)
        sf.bots_time_out_after_game_died(scenario.tree, [1, 2], at_s + 5)
        return scenario, sf.execution(game_exit=(code, signal))

    def test_a_panic_or_a_crash_signal_is_demonstrated_even_with_its_evidence_cut(self):
        for code, signal, kind in ((101, None, 'server_panic'), (None, 11, 'server_crash_signal'), (None, 6, 'server_crash_signal')):
            scenario, record = self.crashed(code, signal)
            document = self.assertClassified(scenario.score(execution_record=record), cs.CAPACITY_FAILURE, kind)
            self.assertEqual(document['validity']['verdict'], cs.VALID)
            self.assertEqual(document['gates']['tick_budget']['verdict'], cs.UNKNOWN, 'its Ticks are lost, and that is not zero')
            self.assertEqual({item['cause'] for item in document['attribution']['departures']}, {'transport_timeout_with_server_distress'})

    def test_a_kill_with_no_cause_on_record_proves_nothing(self):
        scenario, record = self.crashed(None, 9)
        document = self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')
        self.assertFalse(document['attribution']['game_exit']['demonstrated'])

    def test_the_hosts_oom_count_never_explains_a_kill(self):
        """Host-wide, so it cannot say who was killed or when, whichever way it moves. No producer here names a victim, so nothing can support the attribution."""
        cases = dict(increment_long_before_the_kill=lambda index: dict(oom_kill=0 if index < 2 else 1), increment_just_before_the_kill=lambda index: dict(oom_kill=0 if index < 40 else 1), increment_right_at_the_end=lambda index: dict(oom_kill=0 if index < 49 else 7),
                     counter_reset=lambda index: dict(oom_kill=5 if index < 10 else 1), no_change=lambda index: dict(oom_kill=3), missing=lambda index: dict(),
                     a_row_naming_some_other_victim=lambda index: dict(oom_kill=0 if index < 10 else 1, victim=dict(pid=999, start_id='ticks:1')))
        for name, memory in cases.items():
            with self.subTest(name):
                scenario, record = self.crashed(None, 9)
                scenario.tree.edit_sampler('game', lambda index, row: row.update(memory=memory(index)))
                document = self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')
                exit_facts = document['attribution']['game_exit']
                self.assertEqual(exit_facts['kind'], 'killed_with_no_cause_on_record')
                self.assertIs(exit_facts['demonstrated'], False)

    def test_the_hosts_oom_count_stays_on_record_as_a_diagnostic(self):
        scenario, record = self.crashed(None, 9)

        def memory(index, row):
            row['memory'] = dict(oom_kill=0 if index < 10 else 1, MemAvailable=100_000 - index, pgmajfault=index, pswpout=0)
        scenario.tree.edit_sampler('game', memory)
        document = scenario.score(execution_record=record)
        self.assertEqual(document['attribution']['game_exit']['host_oom_kill_delta'], 1)
        self.assertEqual(document['diagnostics']['game_memory']['host_oom_kill_delta'], 1)

    def test_a_counter_that_was_reset_has_no_delta(self):
        scenario, record = self.crashed(None, 9)
        scenario.tree.edit_sampler('game', lambda index, row: row.update(memory=dict(oom_kill=5 if index < 10 else 1)))
        self.assertIsNone(scenario.score(execution_record=record)['attribution']['game_exit']['host_oom_kill_delta'])

    def test_a_gate_proven_failed_beside_an_unexplained_kill_stays_on_record_and_decides_nothing(self):
        scenario, record = self.crashed(None, 9)
        sf.set_rtt(scenario.tree, lambda bot, second: 500)
        document = self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')
        self.assertEqual(document['gates']['rtt_p95']['verdict'], cs.FAIL)
        self.assertIn('RTT p95', ' '.join(document['reasons']))

    def test_a_gate_proven_failed_with_no_kill_still_fails_whatever_the_oom_count_says(self):
        scenario = self.scenario()
        sf.slow(scenario.tree)
        scenario.tree.edit_sampler('game', lambda index, row: row.update(memory=dict(oom_kill=0 if index < 10 else 1)))
        self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, '33.3 ms')

    def test_a_ramp_kill_beside_the_oom_count_is_no_failure_either(self):
        scenario = self.scenario()
        sf.ramp_failure(scenario.tree, 'readiness_timeout', 5)
        scenario.tree.path('game/telemetry/final.json').unlink()
        scenario.tree.edit_sampler('game', lambda index, row: row.update(memory=dict(oom_kill=0 if index < 10 else 1)))
        self.assertClassified(scenario.score(execution_record=sf.execution(game_exit=(None, 9))), cs.INCONCLUSIVE, 'nothing on record says why')

    def test_an_exit_that_looks_tidy_mid_run_is_not_capacity(self):
        for code, signal in ((0, None), (1, None), (None, 15)):
            scenario, record = self.crashed(code, signal)
            self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')

    def test_a_swarm_that_also_failed_cannot_blame_the_server(self):
        scenario, record = self.crashed(101, None)
        record['problems']['generator'] = ['the swarm exited 4 signal None']
        self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing separates them')

    def test_a_swarm_that_failed_beside_a_game_that_ended_for_no_known_reason(self):
        scenario, record = self.crashed(0, None)
        record['problems']['generator'] = ['the swarm exited 4 signal None']
        self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing separates them')

    def test_a_host_reboot_is_infrastructure(self):
        scenario = self.scenario()
        sf.rebooted(scenario.tree)
        self.assertClassified(scenario.score(), cs.INFRASTRUCTURE_FAILURE, 'rebooted')

    def test_a_demonstrated_execution_problem_is_infrastructure(self):
        scenario = self.scenario()
        document = self.assertClassified(scenario.score(execution_record=sf.execution(infrastructure=['game still has processes after the run'])), cs.INFRASTRUCTURE_FAILURE, 'still has processes')
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.PASS, 'the numbers stay on record')


class GeneratorEvidenceBesideAServerFailure(Base):
    """Missing proof of the generator is not excused by what the server did. Missing data from the server can be, when its crash is demonstrated."""

    def assertNotProven(self, document, code):
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertEqual(document['outcome'], search.INCONCLUSIVE)
        self.assertNotEqual(document['validity']['verdict'], cs.VALID)
        self.assertIn(code, document['inputs']['proof_reasons'])

    def test_beside_a_failed_tick_gate(self):
        for name, code, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                scenario = self.scenario()
                sf.slow(scenario.tree)
                change(scenario.tree)
                self.assertNotProven(scenario.score(), code)

    def test_beside_a_demonstrated_crash(self):
        for name, code, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                scenario = self.scenario()
                sf.game_died(scenario.tree, 30)
                sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
                change(scenario.tree)
                self.assertNotProven(scenario.score(execution_record=sf.execution(game_exit=(101, None))), code)

    def test_beside_a_kick(self):
        for name, code, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                scenario = self.scenario()
                sf.lose_bot(scenario.tree, 5, 30, cs.REASON_KICKED)
                change(scenario.tree)
                self.assertNotProven(scenario.score(), code)

    def test_a_crash_leaving_only_the_servers_data_missing_still_stands_on_its_own_generator_proof(self):
        scenario = self.scenario()
        sf.game_died(scenario.tree, 30)
        sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
        document = self.assertClassified(scenario.score(execution_record=sf.execution(game_exit=(101, None))), cs.CAPACITY_FAILURE, 'server_panic')
        self.assertEqual(document['validity']['verdict'], cs.VALID)
        self.assertEqual(document['validity']['unproven'], [])
        self.assertNotEqual(document['inputs']['proof_status'], mw.COMPLETE, 'a full window was never required of a failure that came first')
        self.assertIn('recorder_truncated', document['inputs']['proof_reasons'], 'the server\'s own truncation, explained by its crash')

    def test_a_truncation_is_judged_by_whose_file_it_is(self):
        server = self.scenario()
        sf.slow(server.tree)
        server.tree.edit_json('game/telemetry/final.json', lambda d: d.update(tick_rows=1))
        scored = server.score()
        self.assertIn('recorder_truncated', scored['inputs']['proof_reasons'])
        self.assertEqual(scored['validity']['unproven'], [], 'the server\'s file says nothing about the generator')
        generator = self.scenario()
        sf.slow(generator.tree)
        generator.tree.path('bot/swarm/coordinator.ndjson').write_text('{"cut')
        self.assertIn('recorder_truncated', generator.score()['inputs']['proof_reasons'])
        self.assertNotEqual(generator.score()['validity']['verdict'], cs.VALID)

    def test_a_bot_host_wall_clock_step_leaves_its_counter_reads_unplaced(self):
        scenario = self.scenario()
        sf.lose_bot(scenario.tree, 5, 30, cs.REASON_KICKED)
        sf._swarm_wall_step(scenario.tree)
        document = scenario.score()
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertIn('wall clock stepped', ' '.join(document['validity']['unproven']))

    def test_a_proof_silent_on_the_swarm_proves_nothing(self):
        scenario = self.scenario()
        sf.slow(scenario.tree)
        proof = scenario.proof()
        proof['facts'].pop('swarm_problems')
        self.assertNotEqual(scenario.score(proof=proof)['validity']['verdict'], cs.VALID)

    def test_another_runs_proof_is_refused(self):
        scenario = self.scenario()
        proof = dict(scenario.proof(), run_id='another-run')
        self.assertClassified(scenario.score(proof=proof), cs.INCONCLUSIVE, 'proof_is_of_another_trial')


class Ramp(Base):
    def ramp(self, reason='readiness_timeout', authenticated=None, **options):
        scenario = self.scenario(**options)
        sf.ramp_failure(scenario.tree, reason, authenticated)
        return scenario

    def test_the_prover_calls_every_ramp_failure_a_generator_reason(self):
        proof = self.ramp().proof()
        self.assertEqual([(item['code'], item['category']) for item in proof['reasons']], [('window_not_established', mw.GENERATOR)])

    def test_a_timeout_alone_is_never_a_capacity_limit(self):
        document = self.assertClassified(self.ramp(authenticated=5).score(), cs.INCONCLUSIVE, 'a timeout alone is not a capacity limit')
        self.assertFalse(document['established'])
        self.assertEqual(document['validity']['verdict'], cs.VALID)
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.PASS)

    def test_a_timeout_beside_a_proven_overrun_with_a_valid_generator_is_a_failing_bracket(self):
        scenario = self.ramp(authenticated=5)
        sf.ramp_slow_ticks(scenario.tree, 2)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, '33.3 ms')
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.FAIL)
        self.assertIn('ramp', capacity_report.gate_value('tick_budget', document['gates']['tick_budget']))

    def test_exactly_one_percent_of_ramp_ticks_fails_and_fewer_does_not(self):
        scenario = self.ramp(authenticated=5)
        rows = sf.tick_rows(scenario.tree)
        held = [index for index, row in enumerate(rows) if index and int(row[4]) >= 1]
        for index in held[:len(held) % 100]:     # so that 1 percent of them is a whole number of Ticks
            rows[index][4] = '0'
        held = held[len(held) % 100:]
        for index in held[:len(held) // 100]:
            rows[index][3] = str(40_000_000)
        sf.write_ticks(scenario.tree, rows)
        self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE)
        rows[held[0]][3] = str(33_300_000)
        sf.write_ticks(scenario.tree, rows)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'a timeout alone')

    def test_a_kick_in_the_ramp_is_demonstrated(self):
        scenario = self.ramp('bot_failed_before_window', authenticated=5)
        sf.add_bot_end(scenario.tree, 3, 'server disconnected (reason 2)', dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False))
        self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, 'disconnected authenticated bots [3]')

    def test_a_transport_timeout_in_the_ramp_alone_is_not(self):
        scenario = self.ramp('bot_failed_before_window', authenticated=5)
        sf.add_bot_end(scenario.tree, 3, 'server disconnected (reason 0)', dict(at_ns=2 * NS, reason=0, expected=False))
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'a timeout alone')

    def test_a_crash_in_the_ramp_is_demonstrated(self):
        scenario = self.ramp(authenticated=5)
        scenario.tree.path('game/telemetry/final.json').unlink()
        document = self.assertClassified(scenario.score(execution_record=sf.execution(game_exit=(101, None))), cs.CAPACITY_FAILURE, 'server_panic')
        self.assertEqual(document['gates']['continuity']['verdict'], cs.FAIL)

    def test_a_refused_join_is_a_limit_or_a_ticket_and_not_capacity(self):
        scenario = self.ramp('bot_failed_before_window', authenticated=5)

        def refused(rows):
            rows.insert(-1, dict(k='connect_rejected', peer=9, mono_ns=rows[-1]['mono_ns'] - 1, tick=1, entity_id=None, name=None, reason=cs.REASON_KICKED, authenticated_after=5))
            for index, row in enumerate(rows):
                row['seq'] = index
        scenario.tree.edit_rows('game/telemetry/population.ndjson', refused)
        scenario.tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] + 1))
        sf.ramp_slow_ticks(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'no capacity signal')

    def test_a_starved_generator_cannot_establish_a_bracket(self):
        scenario = self.ramp(authenticated=5)
        scenario.tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=600_000_000))
        self.assertClassified(scenario.score(), cs.INVALID_LOAD, 'did not poll')

    def test_a_join_outside_the_global_stagger_is_the_generators(self):
        scenario = self.ramp(authenticated=5)
        scenario.tree.edit_shard_row(2, 'join', lambda row: row.update(actual_ns=row['scheduled_ns'] + 101_000_000))
        self.assertClassified(scenario.score(), cs.INVALID_LOAD, 'after its slot')

    def test_both_failing_in_the_ramp_cannot_be_separated(self):
        scenario = self.ramp(authenticated=5)
        scenario.tree.edit_shard_row(1, 'footer', lambda row: row.update(max_poll_gap_ns=600_000_000))
        sf.ramp_slow_ticks(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'nothing separates them')

    def test_unproven_generator_counters_establish_nothing(self):
        scenario = self.ramp(authenticated=5)

        def missing(index, row):
            for item in row['procs']['bot']['sockets']:
                item['drops'] = None
        scenario.tree.edit_sampler('bot', missing)
        sf.ramp_slow_ticks(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'not proven valid')

    def test_a_generator_socket_drop_in_the_ramp(self):
        scenario = self.ramp(authenticated=5)
        sf.bot_drop(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INVALID_LOAD, 'dropped')

    def test_interrupted_or_a_shard_gone_says_nothing_about_the_server(self):
        self.assertClassified(self.ramp('interrupted').score(), cs.INCONCLUSIVE, 'stopped before a window')
        self.assertClassified(self.ramp('shard_exited_before_window').score(), cs.INVALID_LOAD)

    def test_a_ramp_can_never_pass(self):
        document = self.ramp().score()
        self.assertNotEqual(document['classification'], cs.VALID_PASS)
        self.assertEqual(document['gates']['rtt_p95']['verdict'], cs.UNKNOWN)

    def test_foreign_or_fault_build_ramp_evidence_refused(self):
        foreign = self.ramp()
        foreign.tree.edit_json('bot/swarm/swarm.json', lambda d: d.update(build=dict(fault_injection=True)))
        sf.ramp_slow_ticks(foreign.tree, 2)
        self.assertClassified(foreign.score(), cs.INCONCLUSIVE, 'fault_injection_build')

    def test_apply_scorer_lets_a_proven_ramp_failure_past_the_generator_reason(self):
        scenario = self.ramp(authenticated=5)
        sf.ramp_slow_ticks(scenario.tree, 2)
        evidence = scenario.evidence()
        verdict = run_checks.apply_scorer(run_checks.disposition(evidence['execution']['problems']), cs.score(evidence), evidence['window_proof'])
        self.assertEqual(verdict['outcome'], search.FAIL)


class ProcessOom(Base):
    """A kill proven to be the kernel's, of this process. Each file here is the shape ``guest_runner.OomWatch`` writes: ``test_guest_runner.OomEvidence`` drives that producer, and no kernel ran."""

    def killed(self, change=None, **options):
        scenario = self.scenario(**options)
        sf.game_died(scenario.tree, 30)
        sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
        return scenario, sf.oom_killed(scenario.tree, change)

    def test_a_victim_matched_kill_is_a_capacity_failure_with_its_cause_on_record(self):
        scenario, record = self.killed()
        document = self.assertClassified(scenario.score(execution_record=record), cs.CAPACITY_FAILURE, 'out_of_memory')
        exit_facts = document['attribution']['game_exit']
        self.assertEqual((exit_facts['kind'], exit_facts['demonstrated']), ('out_of_memory', True))
        self.assertEqual(exit_facts['process_oom']['status'], 'victim_matched')
        self.assertEqual(exit_facts['process_oom']['oom_kill_in_leaf'], 1)
        self.assertEqual(exit_facts['process_oom']['problems'], [])
        self.assertEqual(document['validity']['verdict'], cs.VALID)

    def test_the_same_kill_in_a_ramp_opens_a_bracket_only_over_a_proven_generator(self):
        scenario = self.scenario()
        sf.ramp_failure(scenario.tree, 'bot_failed_before_window', 5)
        record = sf.oom_killed(scenario.tree)
        self.assertClassified(scenario.score(execution_record=record), cs.CAPACITY_FAILURE, 'out_of_memory')
        sf._keep_bot_reads(scenario.tree, sf._last_read_before_abort(scenario.tree))
        self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'not proven valid')

    def test_anything_less_than_a_match_leaves_the_kill_unexplained(self):
        for name, status, change in sf.OOM_NOT_ATTRIBUTED:
            with self.subTest(name):
                scenario, record = self.killed(change)
                document = self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')
                exit_facts = document['attribution']['game_exit']
                self.assertEqual((exit_facts['kind'], exit_facts['demonstrated']), ('killed_with_no_cause_on_record', False))
                self.assertEqual(exit_facts['process_oom']['status'], status, exit_facts['process_oom'])
                self.assertTrue(exit_facts['process_oom']['problems'])

    def test_no_file_cut_file_or_no_plan_leaves_it_unexplained(self):
        for name, breaks in (('no_file', lambda s: s.tree.path('game/process-oom.json').unlink()), ('cut_file', lambda s: s.tree.path('game/process-oom.json').write_text('{"schema": ')), ('no_plan', lambda s: s.tree.path('plan-game.json').unlink()),
                             ('a_plan_with_no_unit', lambda s: s.tree.path('plan-game.json').write_text(json.dumps(dict(unit_mode='process_group', unit=sf.OOM_UNIT))))):
            with self.subTest(name):
                scenario, record = self.killed()
                breaks(scenario)
                self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')

    def test_a_record_that_seals_a_different_process_leaves_it_unexplained(self):
        for name, identity in (('other_game', dict(supervisor=dict(sf.OOM_SUPERVISOR), processes=dict(game=dict(pid=9, start_id='ticks:9', boot_id='boot-game'), sampler=dict(sf.OOM_SAMPLER)), invocation_id=sf.OOM_INVOCATION)),
                               ('no_identity', {})):
            with self.subTest(name):
                scenario = self.scenario()
                sf.game_died(scenario.tree, 30)
                sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
                record = sf.oom_killed(scenario.tree, identity=identity or dict())
                if not identity:
                    record['roles']['game']['identity'] = {}
                self.assertClassified(scenario.score(execution_record=record), cs.INCONCLUSIVE, 'nothing on record says why')

    def test_what_became_of_the_sampler_changes_nothing_about_a_count_local_to_the_games_leaf(self):
        """The sampler dying used to void this, when the only count was the unit's. Its own death is its own problem: it is in another leaf, and the kernel named the game."""
        scenario, record = self.killed()
        record['roles']['game']['result']['sampler_exited_early'] = True
        self.assertClassified(scenario.score(execution_record=record), cs.CAPACITY_FAILURE, 'out_of_memory')
        for name, change in sf.OOM_STILL_THE_GAMES:
            with self.subTest(name):
                scenario, record = self.killed(change)
                self.assertClassified(scenario.score(execution_record=record), cs.CAPACITY_FAILURE, 'out_of_memory')

    def test_a_kill_of_the_game_still_needs_a_proven_generator_however_well_it_is_named(self):
        """A true victim-bound kill advances only over a generator proven valid: naming the victim is not what makes an offered load valid."""
        for name, _, change in sf.GENERATOR_OMISSIONS:
            with self.subTest(name):
                scenario, record = self.killed()
                change(scenario.tree)
                document = scenario.score(execution_record=record)
                self.assertEqual(document['attribution']['game_exit']['kind'], 'out_of_memory', 'still the kernel\'s, and on record')
                self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['validity'])
                self.assertEqual(document['outcome'], 'INCONCLUSIVE')

    def test_the_host_wide_count_alone_never_explains_a_kill(self):
        scenario = self.scenario()
        sf.game_died(scenario.tree, 30)
        sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
        scenario.tree.edit_sampler('game', lambda index, row: row.update(memory=dict(oom_kill=0 if index < 29 else 1)))
        document = self.assertClassified(scenario.score(execution_record=sf.execution(game_exit=(None, 9))), cs.INCONCLUSIVE, 'nothing on record says why')
        exit_facts = document['attribution']['game_exit']
        self.assertEqual((exit_facts['kind'], exit_facts['host_oom_kill_delta'], exit_facts['process_oom']['status']), ('killed_with_no_cause_on_record', 1, 'missing'))

    def test_evidence_cannot_turn_any_other_exit_into_an_oom(self):
        for name, code, signal, kind in (('sigterm', None, 15, 'ended_with_no_cause_on_record'), ('panic', 101, None, 'server_panic'), ('clean', 0, None, 'ended_with_no_cause_on_record')):
            with self.subTest(name):
                scenario, record = self.killed()
                record['roles']['game']['result']['processes']['game'] = dict(returncode=code, signal=signal)
                self.assertEqual(scenario.score(execution_record=record)['attribution']['game_exit']['kind'], kind)

    def test_a_game_process_that_was_not_lost_ignores_the_file(self):
        scenario, record = self.killed()
        record['roles']['game']['result']['stop_reason'] = 'stop_requested:workload_finished'
        self.assertEqual(scenario.score(execution_record=record)['attribution']['game_exit'], dict(lost=False))

    def test_a_verdict_of_oom_stands_only_over_a_proven_generator(self):
        scenario, record = self.killed()
        scenario.tree.edit_shard_row(1, 'footer', lambda row: row.pop('max_poll_gap_ns'))
        self.assertNotEqual(scenario.score(execution_record=record)['outcome'], search.FAIL)


class RampIdentity(Base):
    """A ramp cannot lean on the hold prover's identity checks, because no hold happened. Everything it claims must be the supervised processes' own."""

    def failing_ramp(self, **options):
        scenario = self.scenario(**options)
        sf.ramp_failure(scenario.tree, 'readiness_timeout', scenario.tree.timeline.target - 1)
        sf.ramp_slow_ticks(scenario.tree, 2)
        return scenario

    def test_the_valid_ramp_overrun_these_all_start_from_is_a_failure(self):
        document = self.assertClassified(self.failing_ramp().score(), cs.CAPACITY_FAILURE, '33.3 ms')
        self.assertEqual(document['validity']['verdict'], cs.VALID)
        self.assertEqual(document['validity']['generator_socket_drops'], 0)

    def test_evidence_that_is_not_the_supervised_processes_establishes_nothing(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            with self.subTest(name):
                scenario = self.failing_ramp()
                change(scenario.tree)
                document = scenario.score()
                self.assertNotEqual(document['outcome'], search.FAIL, document['reasons'])
                self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
                self.assertIn(code, document['inputs']['proof_reasons'])

    def test_a_collector_on_another_boot_is_a_reboot(self):
        scenario = self.failing_ramp()
        scenario.tree.edit_sampler('bot', lambda index, row: row.update(boot_id='another-boot'))
        self.assertClassified(scenario.score(), cs.INFRASTRUCTURE_FAILURE, 'rebooted')

    def test_identities_an_earlier_run_used(self):
        scenario = self.failing_ramp()
        swarm, game = scenario.tree.identities['bot']['bot'], scenario.tree.identities['game']['game']
        for name, prior, code in (('swarm', dict(bot=dict(processes={(swarm['pid'], swarm['start_id'], swarm['boot_id'])}, inodes=set())), 'process_identity_reused'),
                                  ('game', dict(game=dict(processes={(game['pid'], game['start_id'], game['boot_id'])}, inodes=set())), 'process_identity_reused'),
                                  ('socket', dict(bot=dict(processes=set(), inodes={'bot-socket-40003'})), 'socket_identity_reused')):
            with self.subTest(name):
                document = scenario.score(proof=scenario.proof(prior=prior))
                self.assertClassified(document, cs.INCONCLUSIVE, code)

    def test_a_record_the_supervisor_cannot_vouch_for(self):
        scenario = self.failing_ramp()
        for role in ('bot', 'game'):
            with self.subTest(role):
                identities = {key: dict(value) for key, value in scenario.tree.identities.items()}
                identities[role] = {}
                self.assertClassified(scenario.score(proof=scenario.proof(identities=identities)), cs.INCONCLUSIVE, 'identity_missing')

    def test_a_proof_with_no_account_of_the_ramp_proves_nothing(self):
        scenario = self.failing_ramp()
        proof = scenario.proof()
        proof['facts'].pop('ramp')
        self.assertClassified(scenario.score(proof=proof), cs.INCONCLUSIVE, 'no account of this ramp')

    def aborted_early(self, abort_s, reads):
        """A swarm that gave up ``abort_s`` into its joins, with the collector having read only ``reads`` times. Bot n's slot is (n - 1) / 10 s, and a read comes every second, starting at zero."""
        scenario = self.scenario(target=25)
        tree = scenario.tree
        sf.ramp_failure(tree, 'bot_failed_before_window', 5)
        sf.ramp_slow_ticks(tree, 2)
        abort = int(abort_s * NS)
        sf._set_abort(tree, lambda row: row.update(mono_ns=abort))
        unjoined = [bot for bot in range(1, 26) if tree.timeline.joins[bot] >= abort]
        for shard in range(tree.timeline.threads):
            def change(rows):
                rows[:] = [row for row in rows if not (row.get('k') in ('join', 'connected', 'auth') and row['bot'] in unjoined)]
                for row in rows:
                    if row.get('k') == 'sample':
                        row['bots'] = [item for item in row['bots'] if item[0] not in unjoined]
                for index, row in enumerate(rows):
                    row['seq'] = index
            tree.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)

        def sockets(index, row):
            opened = [40000 + bot for bot in range(1, 26) if bot not in unjoined and tree.timeline.joins[bot] + 500_000 < index * NS]
            row['procs']['bot']['sockets'] = [item for item in row['procs']['bot']['sockets'] if item['local_port'] in opened]
        tree.edit_sampler('bot', sockets)
        sf._keep_bot_reads(tree, reads)
        return scenario

    def assertGeneratorNotProven(self, document):
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertNotEqual(document['outcome'], search.FAIL)
        self.assertEqual(document['validity']['verdict'], cs.NOT_PROVEN)
        self.assertEqual(document['validity']['generator_sockets'], cs.NOT_PROVEN)
        self.assertIsNone(document['validity']['generator_socket_drops'], 'a counter that was not read is never zero')
        self.assertIn('collector_boundary_missing', document['inputs']['proof_reasons'])

    def test_sockets_no_read_ever_saw_are_not_proven_free_of_drops(self):
        """15 bots started, 10 sockets observed, 5 never, and the last read half a second before the abort."""
        scenario = self.aborted_early(1.5, 2)
        self.assertGeneratorNotProven(scenario.score())
        host = scenario.proof()['facts']['ramp']['bot_host']
        self.assertIsNone(host['socket_drops_total'])
        self.assertEqual((host['sockets_with_counters'], host['sockets_without_counters'], host['reads_certainly_after_abort']), (0, 15, 0))

    def test_a_drop_a_read_would_have_shown_cannot_become_a_capacity_failure_by_the_read_not_happening(self):
        scenario = self.aborted_early(1.5, 2)
        path = scenario.tree.path('bot/sampler.ndjson')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        read = copy.deepcopy(rows[-1])
        read.update(clock=fx.bot_pair(1_400_000_000), clock_after=fx.bot_pair(1_400_000_000 + fx.READ_NS), seq=2)
        model = rows[-1]['procs']['bot']['sockets'][0]
        read['procs']['bot']['sockets'] = [dict(model, local_port=40000 + bot, local='00000000:%04X' % (40000 + bot), inode='bot-socket-%d' % (40000 + bot), drops=1 if bot == 11 else 0) for bot in range(1, 15)]
        fx.write_ndjson(path, rows + [read])
        with_the_read = scenario.score()
        self.assertEqual(with_the_read['classification'], cs.INCONCLUSIVE, with_the_read['reasons'])
        self.assertEqual(with_the_read['validity']['verdict'], cs.INVALID, 'the drop is on record, beside slow Ticks')
        fx.write_ndjson(path, rows)
        without_it = scenario.score()
        self.assertGeneratorNotProven(without_it)

    def test_every_socket_observed_is_still_not_enough_if_the_last_read_came_before_the_abort(self):
        for name, change in (('overrun', lambda s: None), ('kick', lambda s: sf.add_bot_end(s.tree, 3, 'server disconnected (reason 2)', dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False)))):
            with self.subTest(name):
                scenario = self.failing_ramp(target=25)
                change(scenario)
                sf._keep_bot_reads(scenario.tree, int(scenario.tree.timeline.drain // NS) + 1)
                self.assertGeneratorNotProven(scenario.score())
                host = scenario.proof()['facts']['ramp']['bot_host']
                self.assertEqual((host['sockets_with_counters'], host['sockets_without_counters']), (0, 25))

    def test_a_server_crash_on_an_unobserved_tail_is_not_a_capacity_failure(self):
        scenario = self.failing_ramp(target=25)
        sf._keep_bot_reads(scenario.tree, int(scenario.tree.timeline.drain // NS) + 1)
        self.assertGeneratorNotProven(scenario.score(execution_record=sf.execution(game_exit=(101, None))))

    def boundary(self, offset_ns):
        """The final read begins at 67 s, and the abort falls ``offset_ns`` after that."""
        scenario = self.failing_ramp(target=25)
        tree = scenario.tree
        sf._set_abort(tree, lambda row: row.update(mono_ns=67 * NS + offset_ns))
        sf._keep_bot_reads(tree, 68)
        return scenario

    def test_only_a_read_certainly_after_the_abort_proves_the_tail(self):
        for name, offset_ns in (('the_clocks_allow_either_order', -40_000), ('same_instant', 0), ('read_began_before', 1_000_000), ('read_began_well_before', 500_000_000)):
            with self.subTest(name):
                self.assertGeneratorNotProven(self.boundary(offset_ns).score())
        document = self.assertClassified(self.boundary(-2_000_000).score(), cs.CAPACITY_FAILURE, '33.3 ms')
        self.assertEqual(document['validity']['generator_socket_drops'], 0)

    def test_a_read_after_the_abort_that_saw_every_socket_proves_a_short_ramp(self):
        scenario = self.aborted_early(1.5, 3)
        document = self.assertClassified(scenario.score(), cs.CAPACITY_FAILURE, '33.3 ms')
        self.assertEqual(document['validity']['generator_socket_drops'], 0)
        host = scenario.proof()['facts']['ramp']['bot_host']
        self.assertEqual((host['sockets_with_counters'], host['sockets_without_counters'], host['reads_certainly_after_abort']), (15, 0, 1))
        self.assertGreater(host['first_read_after_abort_ns'], 0)

    def test_a_socket_gone_by_the_read_after_the_abort_is_not_proven(self):
        scenario = self.aborted_early(1.5, 3)
        sf._drop_bot_socket(scenario.tree, 40012, only_index=2)
        document = scenario.score()
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertIn('socket_evidence_missing', document['inputs']['proof_reasons'])
        self.assertIsNone(document['validity']['generator_socket_drops'])

    def test_a_read_after_the_abort_that_shows_an_overflow_stays_inconclusive_beside_server_distress(self):
        scenario = self.aborted_early(1.5, 3)
        sf._bot_socket(scenario.tree, lambda item: item.update(drops=2 if item['local_port'] == 40011 else 0), only_index=2)
        document = scenario.score()
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertEqual(document['validity']['verdict'], cs.INVALID)
        self.assertIn('generator_socket_drops', document['inputs']['proof_reasons'])

    def test_an_overflow_with_nothing_wrong_on_the_server_is_invalid_load(self):
        scenario = self.scenario(target=25)
        sf.ramp_failure(scenario.tree, 'readiness_timeout', 24)
        sf._bot_socket(scenario.tree, lambda item: item.update(drops=1 if item['local_port'] == 40011 else 0))
        self.assertClassified(scenario.score(), cs.INVALID_LOAD)

    def test_a_socket_that_a_read_owed_and_did_not_see_is_not_excused(self):
        scenario = self.aborted_early(1.5, 3)
        sf._drop_bot_socket(scenario.tree, 40005, only_index=1)
        document = scenario.score()
        self.assertEqual(document['classification'], cs.INCONCLUSIVE, document['reasons'])
        self.assertIn('socket_evidence_missing', document['inputs']['proof_reasons'])

    def test_a_slot_after_the_abort_was_never_owed_and_one_long_before_it_was(self):
        scenario = self.aborted_early(1.5, 3)
        self.assertEqual(scenario.proof()['facts']['ramp']['bots_started'], 15)
        sf._forget_bot_join(scenario.tree, 2)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'not proven valid')

    def test_a_drop_before_the_first_read_still_counts(self):
        scenario = self.failing_ramp()
        sf._bot_socket(scenario.tree, lambda item: item.update(drops=1 if item['local_port'] == 40002 else 0))
        document = scenario.score()
        self.assertIn('generator_socket_drops', document['inputs']['proof_reasons'])
        self.assertEqual(document['validity']['verdict'], cs.INVALID)

    def test_a_kick_needs_a_bot_both_sides_recorded_as_authenticated(self):
        """The server sends the same reason to a join it refuses, so the reason alone is not a kick."""
        kicked = dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False)
        for name, bot, expected in (('authenticated', 3, cs.CAPACITY_FAILURE), ('never_authenticated', 7, cs.INCONCLUSIVE)):
            with self.subTest(name):
                scenario = self.scenario()
                sf.ramp_failure(scenario.tree, 'bot_failed_before_window', 5)
                sf.add_bot_end(scenario.tree, bot, 'server disconnected (reason 2)', kicked)
                document = self.assertClassified(scenario.score(), expected)
                self.assertEqual(document['attribution']['server_kicks'], [bot] if expected == cs.CAPACITY_FAILURE else [])

    def test_a_kick_the_server_never_authenticated_is_no_kick(self):
        scenario = self.scenario()
        sf.ramp_failure(scenario.tree, 'bot_failed_before_window', 5)

        def forget(rows):
            rows[:] = [row for row in rows if not (row.get('k') == 'auth' and row.get('name') == 'LoadBot003')]
            for index, row in enumerate(rows):
                row['seq'] = index
        scenario.tree.edit_rows('game/telemetry/population.ndjson', forget)
        scenario.tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=d['population_rows'] - 1))
        sf.add_bot_end(scenario.tree, 3, 'server disconnected (reason 2)', dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False))
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'a timeout alone')

    def test_a_kick_with_a_broken_generator_proof_establishes_nothing(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            with self.subTest(name):
                scenario = self.scenario()
                sf.ramp_failure(scenario.tree, 'bot_failed_before_window', 5)
                sf.add_bot_end(scenario.tree, 3, 'server disconnected (reason 2)', dict(at_ns=2 * NS, reason=cs.REASON_KICKED, expected=False))
                change(scenario.tree)
                self.assertNotEqual(scenario.score()['outcome'], search.FAIL, name)

    def test_a_crash_in_the_ramp_needs_the_generator_proof_too(self):
        for name, code, change in sf.RAMP_NOT_PROVEN:
            if name.startswith('foreign_game'):
                continue
            with self.subTest(name):
                scenario = self.scenario()
                sf.ramp_failure(scenario.tree, 'readiness_timeout', 5)
                scenario.tree.path('game/telemetry/final.json').unlink()
                change(scenario.tree)
                self.assertNotEqual(scenario.score(execution_record=sf.execution(game_exit=(101, None)))['outcome'], search.FAIL, name)


class WhatMayBeScoredAtAll(Base):
    def refused(self, code, **options):
        document = self.assertClassified(self.scenario().score(**options), cs.INCONCLUSIVE, code)
        return document

    def test_local_counter_bypass_can_never_pass(self):
        document = self.refused('socket_counter_bypass', require_counters=False)
        self.assertEqual(document['gates']['tick_budget']['verdict'], cs.PASS, 'the numbers it measured stay visible')

    def test_a_prover_never_given_the_schema(self):
        scenario = self.scenario()
        self.assertClassified(scenario.score(proof=scenario.proof(telemetry_schema=None)), cs.INCONCLUSIVE, 'schema_check_bypassed')

    def test_the_historical_placeholder_manifest_is_refused(self):
        placeholder = dict(id='omega.measurement/2', sha256='a' * 64)
        scenario = self.scenario()
        document = scenario.score(telemetry_schema=placeholder, proof=scenario.proof(telemetry_schema=placeholder))
        self.assertClassified(document, cs.INCONCLUSIVE, 'manifest_schema_mismatch')

    def test_a_short_hold_is_refused_even_when_the_prover_was_allowed_it(self):
        scenario = self.scenario(hold_s=5)
        self.assertClassified(scenario.score(allow_short_hold=True), cs.INCONCLUSIVE, 'non_contract_hold')

    def test_no_proof_or_a_foreign_one(self):
        scenario = self.scenario()
        for proof in ({}, dict(schema='omega.do-session.window-proof/0'), dict(schema=mw.PROOF_SCHEMA, status='complete', reasons=[], facts=dict(contract_hold=True))):
            self.assertClassified(cs.evaluate(dict(scenario.evidence(), window_proof=proof)), cs.INCONCLUSIVE)
        self.assertClassified(cs.evaluate(dict(scenario.evidence(), window_proof=None)), cs.INCONCLUSIVE, 'no_window_proof')

    def test_a_proof_of_another_trial(self):
        scenario = self.scenario()
        proof = scenario.proof()
        proof['facts']['target'] = 500
        self.assertClassified(scenario.score(proof=proof), cs.INCONCLUSIVE, 'proof_is_of_another_trial')

    def test_evidence_not_verified_locally(self):
        self.refused('export_incomplete', execution_record=sf.execution(exported=False))

    def test_a_proof_with_no_retained_copy(self):
        scenario = self.scenario()
        self.assertClassified(cs.evaluate(dict(scenario.evidence(), window_proof_sha256=None)), cs.INCONCLUSIVE, 'proof_not_retained')

    def test_a_swarm_told_to_stop_inside_the_window_says_nothing_about_either_side(self):
        scenario = self.scenario()
        scenario.tree.edit_json('bot/swarm/window.json', lambda d: d.update(status='window_incomplete', reason='interrupted'))
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE, 'told to stop')

    def test_no_execution_record(self):
        scenario = self.scenario()
        self.assertClassified(cs.evaluate(dict(scenario.evidence(), execution=None)), cs.INCONCLUSIVE, 'execution_record_missing')

    def test_foreign_or_tampered_evidence_says_nothing_even_about_a_failure(self):
        changes = (lambda t: t.edit_json('bot/swarm/swarm.json', lambda d: d.update(schema='omega.measurement/2')),
                   lambda t: t.edit_json('bot/swarm/swarm.json', lambda d: d.update(build=dict(fault_injection=True))),
                   lambda t: t.edit_json('game/telemetry/process.json', lambda d: d.update(schema='omega.measurement/999')),
                   lambda t: t.edit_shard_row(1, 'header', lambda r: r.update(schema='omega.measurement/999')),
                   lambda t: t.edit_rows('bot/swarm/shard-0.ndjson', lambda rows: rows[2].update(nonce='other')),)
        for change in changes:
            scenario = self.scenario()
            sf.set_slow_ticks(scenario.tree, 180, 40_000_000)
            change(scenario.tree)
            self.assertClassified(scenario.score(), cs.INCONCLUSIVE)

    def test_every_missing_recorder_is_not_a_quiet_one(self):
        for relative in ('bot/swarm/swarm.json', 'bot/swarm/window.json', 'bot/swarm/coordinator.ndjson', 'bot/swarm/shard-0.ndjson', 'game/telemetry/process.json', 'game/telemetry/final.json', 'game/telemetry/population.ndjson', 'game/telemetry/ticks.csv', 'game/sampler.ndjson', 'bot/sampler.ndjson'):
            scenario = self.scenario()
            scenario.tree.path(relative).unlink()
            document = scenario.score()
            self.assertEqual(document['classification'], cs.INCONCLUSIVE, relative)

    def test_missing_clock_brackets_cannot_pass(self):
        scenario = self.scenario()
        scenario.tree.brackets = dict(scenario.tree.brackets, after=None)
        self.assertClassified(scenario.score(), cs.INCONCLUSIVE)

    def test_a_retained_score_that_does_not_read_is_nothing(self):
        scenario = self.scenario()
        path = scenario.tree.root / 'score.json'
        path.write_text('{"schema": "something else"}')
        self.assertIsNone(cs.load_retained(path))
        path.write_text('not json')
        self.assertIsNone(cs.load_retained(path))


class Reports(Base):
    def test_a_run_report_renders_exact_counts_and_says_what_it_is(self):
        scenario = self.scenario()
        sf.tight_clocks(scenario.tree)
        sf.set_slow_ticks(scenario.tree, 18, 40_000_000)
        text = capacity_report.render_run(scenario.score())
        self.assertIn('**capacity_failure**', text)
        self.assertIn('1/100', text)
        self.assertIn('A single run establishes no capacity', text)
        self.assertIn('decides nothing', text)

    def test_rendering_is_deterministic_and_adds_no_judgement(self):
        document = self.scenario().score()
        self.assertEqual(capacity_report.render_run(document), capacity_report.render_run(json.loads(cs.canonical(document))))


if __name__ == '__main__':
    unittest.main()
