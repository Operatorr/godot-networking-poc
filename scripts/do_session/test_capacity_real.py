"""The production scorer over real ``omega-server`` and ``omega-load-test`` bytes: one machine, loopback, real time, short holds.

Needs ``OMEGA_LOCAL_RELEASE_DIR``. Run it under ``measurement_offline.sb``. The prover here is told counters are optional, because macOS has none, and the scorer must refuse exactly that. What these check is that the
producers' real units and real disconnect reasons are the ones ``capacity_scorer`` says they are. No result here is a capacity finding.
"""
import os
import pathlib
import shutil
import tempfile
import unittest

import capacity_scorer as cs
import measurement_local as ml
import measurement_window as mw
import scoring_evidence as evidence
import scoring_fixtures as sf

RELEASE = os.environ.get('OMEGA_LOCAL_RELEASE_DIR')


@unittest.skipUnless(RELEASE, 'needs a release build: OMEGA_LOCAL_RELEASE_DIR')
class RealBytes(unittest.TestCase):
    def scored(self, target, hold_s, **options):
        root = tempfile.mkdtemp(prefix='omega-score-real-')
        self.addCleanup(shutil.rmtree, root, True)
        run = ml.LocalRun(RELEASE, pathlib.Path(root) / 'run', target, hold_s, **options).execute()
        proof = ml.prove(run, telemetry_schema=sf.FROZEN_SCHEMA)
        return cs.evaluate(evidence.real_evidence(run, proof)), proof

    def test_a_healthy_short_window_measures_real_values_and_the_local_shortcut_is_refused(self):
        document, proof = self.scored(8, 6)
        self.assertEqual(proof['status'], mw.COMPLETE)
        self.assertEqual(document['classification'], cs.INCONCLUSIVE)
        self.assertIn('socket_counter_bypass', ' '.join(document['reasons']))
        self.assertIn('non_contract_hold', ' '.join(document['reasons']))
        self.assertNotIn('schema_check_bypassed', ' '.join(document['reasons']), 'the frozen schema was checked, and only the local allowances are what is refused')
        self.assertEqual(document['gates']['continuity']['verdict'], cs.PASS)
        self.assertEqual(document['gates']['bot_errors']['verdict'], cs.PASS)
        ticks = document['gates']['tick_budget']
        self.assertEqual(ticks['verdict'], cs.PASS)
        self.assertGreater(ticks['ticks_narrow'], 150)
        self.assertGreater(ticks['work_ns_max'], 0)
        rtt = document['gates']['rtt_p95']
        self.assertEqual(rtt['verdict'], cs.PASS)
        self.assertGreaterEqual(rtt['samples'], 8 * 4)
        self.assertEqual(rtt['p95_ms'], int(rtt['p95_ms']), 'rusty_enet reports whole milliseconds')
        self.assertEqual(document['gates']['enet_loss']['verdict'], cs.PASS)
        self.assertEqual(document['gates']['game_socket_drops']['verdict'], cs.UNKNOWN, 'no counter here, and that is not zero')
        self.assertEqual(document['validity']['generator_sockets'], cs.NOT_PROVEN)
        self.assertEqual(document['validity']['offered_input'], cs.VALID)

    def test_a_blocked_path_leaves_real_reason_zero_on_both_sides_and_no_blame(self):
        document, proof = self.scored(8, 20, use_relay=True, schedule=[evidence._block_one_bot_in_window(2, 2.0)])
        departures = document['attribution']['departures']
        self.assertEqual(len(departures), 1, departures)
        item = departures[0]
        self.assertEqual(item['reason'], 0, 'ENet giving up by itself carries no reason')
        self.assertEqual(item['cause'], 'transport_timeout_unattributed')
        self.assertEqual(document['gates']['continuity']['verdict'], cs.FAIL)
        self.assertEqual(document['gates']['bot_errors']['errors_that_are_the_disconnect_itself'], 1)
        self.assertEqual(document['classification'], cs.INCONCLUSIVE)
        self.assertNotIn('offered_input_below_minimum', [failure.get('code') for failure in document['validity']['independent_failures']], 'it kept sending until it saw the disconnect')

    def test_a_real_sigkill_proves_nothing(self):
        document, _ = self.scored(8, 20, schedule=[ml.FaultSchedule.kill_game_in_window(2.0)])
        self.assertEqual(document['attribution']['game_exit']['kind'], 'killed_with_no_cause_on_record')
        self.assertEqual(document['classification'], cs.INCONCLUSIVE)

    def test_a_real_paused_swarm_is_the_generators(self):
        document, _ = self.scored(8, 6, schedule=[ml.FaultSchedule.pause_swarm_in_window(1.5)])
        self.assertIn('poll_starvation', [failure.get('code') for failure in document['validity']['independent_failures']])
        self.assertEqual(document['validity']['verdict'], cs.INVALID)

    def test_a_real_readiness_timeout_is_no_capacity_limit(self):
        document, proof = self.scored(8, 6, use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(2, None)], readiness_timeout_s=4.0)
        self.assertIn('window_not_established', [item['code'] for item in proof['reasons']])
        self.assertFalse(document['established'])
        self.assertEqual(document['classification'], cs.INCONCLUSIVE)
        self.assertNotEqual(document['classification'], cs.CAPACITY_FAILURE)
        self.assertEqual(document['gates']['tick_budget']['scope'], 'every Tick with at least one authenticated player, the ramp and any drain')
        # The identities and coverage a ramp is now held to, on what the real producers actually write.
        self.assertEqual(sorted(set(document['inputs']['proof_reasons']) & cs.INTEGRITY_CODES), [], 'the supervised processes are recognized as themselves')
        ramp = proof['facts']['ramp']
        self.assertEqual(ramp['reason'], 'readiness_timeout')
        self.assertEqual(ramp['bots_started'], 8, 'every slot came before the abort')
        self.assertIsNotNone(ramp['abort_bot_mono_ns'], 'the real coordinator row is read')
        host = ramp['bot_host']
        self.assertEqual(host['sockets_with_counters'], 0, 'this platform has none')
        self.assertGreaterEqual(host['sockets_without_counters'], 1)
        self.assertGreaterEqual(host['reads_certainly_after_abort'], 1, 'the swarm held its sockets open for a read after it gave up')
        self.assertGreater(host['first_read_after_abort_ns'], 0)
        self.assertEqual(document['validity']['verdict'], cs.NOT_PROVEN, 'the missing counters leave it unproven, on this platform')


if __name__ == '__main__':
    unittest.main()
