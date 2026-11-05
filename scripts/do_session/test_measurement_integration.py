"""Real omega-server and omega-load-test processes, the real runner and supervisor, two host roots on loopback, real time.

    OMEGA_LOCAL_RELEASE_DIR   a release build of the revision under test (cargo build --release -p omega-server -p omega-load-test)
    OMEGA_FAULT_RELEASE_DIR   the same source built with --features omega-load-test/fault-injection, for what no outside signal can do
    OMEGA_MEASURE_LONG=1      also run the full 60 s and 300 s windows

Without those it skips, because the deterministic version of every proof rule is in ``test_measurement_window``. Short holds here are clearly short: they
prove the machinery in real time, each carries ``contract_hold`` false, and the prover refuses them without ``allow_short_hold``.
Endpoints share this host, so counters and clock offsets are limited as ``measurement_local`` says. Nothing here is a capacity observation.

Under the offline sandbox, ``sandbox-exec -f measurement_offline.sb python3 -m unittest test_measurement_integration``: every non-loopback send is refused and the
collector's ``ps`` still runs. A sandbox without that allowance makes the collector report every process as gone, and the proofs are then rightly inconclusive.
"""
import json
import os
import pathlib
import shutil
import tempfile
import unittest

import measurement_local as ml
import measurement_window as mw

RELEASE = os.environ.get('OMEGA_LOCAL_RELEASE_DIR')
FAULT_RELEASE = os.environ.get('OMEGA_FAULT_RELEASE_DIR')
TARGET, HOLD = 8, 6


def codes(proof):
    return {item['code'] for item in proof['reasons']}


class Real(unittest.TestCase):
    @staticmethod
    def proof_status(proof):
        return proof['status']

    def run_local(self, target=TARGET, hold_s=HOLD, **options):
        root = tempfile.mkdtemp(prefix='omega-real-')
        self.addCleanup(shutil.rmtree, root, True)
        return ml.LocalRun(RELEASE, pathlib.Path(root) / 'run', target, hold_s, **options).execute()

    def fault(self, *specs, **options):
        extra = [item for spec in specs for item in ('--fault', spec)]
        return self.run_local(bot_release=FAULT_RELEASE, bot_extra=extra, **options)


@unittest.skipUnless(RELEASE, 'needs a release build: OMEGA_LOCAL_RELEASE_DIR')
class CompleteWindow(Real):
    @classmethod
    def setUpClass(cls):
        cls.base = pathlib.Path(tempfile.mkdtemp(prefix='omega-real-base-'))
        cls.run_data = ml.LocalRun(RELEASE, cls.base / 'run', TARGET, HOLD).execute()
        cls.proof = ml.prove(cls.run_data)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, True)

    def copy(self):
        root = tempfile.mkdtemp(prefix='omega-real-copy-')
        self.addCleanup(shutil.rmtree, root, True)
        target = pathlib.Path(root) / 'evidence'
        shutil.copytree(self.run_data['evidence'], str(target))
        os.system('chmod -R u+w %s' % target)
        return target

    def reproved(self, root, **options):
        return ml.prove(self.run_data, root=str(root), **options)

    def test_every_recorder_agrees_on_one_window(self):
        self.assertEqual(self.proof['status'], mw.COMPLETE, self.proof['reasons'])
        self.assertFalse(self.proof['facts']['contract_hold'], 'a short real hold says what it is')
        self.assertEqual(self.proof['facts']['input']['below_minimum'], [])
        population = self.proof['facts']['population']
        self.assertTrue(population['tick_numbers_contiguous'])
        self.assertEqual(population['authenticated_transitions'], TARGET)
        self.assertGreater(population['ticks_in_interval'], HOLD * 25)

    def test_a_short_hold_is_refused_without_the_explicit_allowance(self):
        proof = ml.prove(self.run_data, allow_short_hold=False)
        self.assertIn('non_contract_hold', codes(proof))
        self.assertEqual(proof['status'], mw.INCONCLUSIVE)

    def test_macos_has_no_socket_counters_and_the_proof_will_not_call_that_zero(self):
        if pathlib.Path('/proc/net/udp').exists():
            self.skipTest('this host has real counters')
        proof = ml.prove(self.run_data, require_counters=True)
        self.assertIn('socket_counters_missing', codes(proof))
        self.assertEqual(proof['status'], mw.INCONCLUSIVE)
        self.assertIsNone(self.proof['facts']['bot_host']['socket_drops_total'])

    def test_four_shards_each_with_their_own_file_and_identity(self):
        evidence = pathlib.Path(self.run_data['evidence'])
        swarm = json.loads((evidence / 'bot/swarm/swarm.json').read_text())
        self.assertEqual(swarm['pid'], self.run_data['identities']['bot']['bot']['pid'])
        self.assertEqual(sorted(path.name for path in (evidence / 'bot/swarm').glob('shard-*.ndjson')), ['shard-%d.ndjson' % n for n in range(4)])
        for shard in range(4):
            rows = [json.loads(line) for line in (evidence / 'bot/swarm' / ('shard-%d.ndjson' % shard)).read_text().splitlines()]
            self.assertEqual(rows[0]['bots'], [bot for bot in range(1, TARGET + 1) if (bot - 1) % 4 == shard])
            self.assertEqual(rows[0]['thread'], 'swarm-%d' % shard)
            self.assertTrue(rows[0]['geometry']['initialized_on_thread'])
        process = json.loads((evidence / 'game/telemetry/process.json').read_text())
        self.assertEqual(process['pid'], self.run_data['identities']['game']['game']['pid'])

    def test_a_real_frozen_schema_and_build_are_stated_by_every_recorder(self):
        evidence = pathlib.Path(self.run_data['evidence'])
        frozen = mw.schema()['id']
        swarm = json.loads((evidence / 'bot/swarm/swarm.json').read_text())
        self.assertEqual((swarm['schema'], swarm['role']), (frozen, 'bot'))
        self.assertIs(swarm['build']['fault_injection'], False, 'this is a frozen release build')
        for relative, role in (('bot/swarm/window.json', 'bot'), ('game/telemetry/process.json', 'game'), ('game/telemetry/final.json', 'game')):
            document = json.loads((evidence / relative).read_text())
            self.assertEqual((document['schema'], document['role']), (frozen, role), relative)
        for relative in ['bot/swarm/coordinator.ndjson'] + ['bot/swarm/shard-%d.ndjson' % shard for shard in range(4)]:
            header = json.loads((evidence / relative).read_text().splitlines()[0])
            self.assertEqual((header['schema'], header['role']), (frozen, 'bot'), relative)
        for role in ('bot', 'game'):
            self.assertEqual(json.loads((evidence / role / 'sampler.ndjson').read_text().splitlines()[0])['schema'], frozen)

    def test_a_real_collector_brackets_every_counter_read(self):
        evidence = pathlib.Path(self.run_data['evidence'])
        limits = mw.schema()['limits']
        for role in ('bot', 'game'):
            rows = [json.loads(line) for line in (evidence / role / 'sampler.ndjson').read_text().splitlines()[1:]]
            for row in rows:
                self.assertIsNotNone(mw.counter_read_bounds(row, limits), row.get('seq'))
                self.assertLessEqual(row['clock']['mono_ns'], row['clock_after']['mono_ns'])

    def test_the_game_and_bot_monotonic_domains_really_differ(self):
        evidence = pathlib.Path(self.run_data['evidence'])
        swarm = json.loads((evidence / 'bot/swarm/swarm.json').read_text())['clock']
        game = json.loads((evidence / 'game/telemetry/process.json').read_text())['clock']
        self.assertGreater(abs(swarm['wall_before_ns'] - game['wall_before_ns']), mw.NS // 100, 'the game started first')
        self.assertLess(swarm['mono_ns'], mw.NS, 'each counts from its own process')
        self.assertLess(game['mono_ns'], mw.NS)

    # ---- truncation and overwrite, on real bytes ------------------------------------------------

    def test_real_recorders_truncated(self):
        for relative in ('bot/swarm/shard-1.ndjson', 'bot/swarm/coordinator.ndjson', 'game/telemetry/population.ndjson', 'game/telemetry/ticks.csv'):
            with self.subTest(relative=relative):
                root = self.copy()
                data = (root / relative).read_bytes()
                (root / relative).write_bytes(data[:len(data) * 2 // 3])
                proof = self.reproved(root)
                self.assertIn('recorder_truncated', codes(proof), proof['reasons'])
                self.assertNotEqual(proof['status'], mw.COMPLETE)

    def test_a_real_shard_overwritten_by_another_run(self):
        root = self.copy()
        rows = [json.loads(line) for line in (root / 'bot/swarm/shard-2.ndjson').read_text().splitlines()]
        (root / 'bot/swarm/shard-2.ndjson').write_text(''.join(json.dumps(dict(row, nonce='another')) + '\n' for row in rows))
        self.assertIn('recorder_overwritten', codes(self.reproved(root)))

    # ---- clocks, on real bytes ------------------------------------------------------------------

    def test_a_real_run_with_a_known_wall_offset_still_maps(self):
        """The game's wall fields all move by 37 s, and the brackets know. The window must still prove, through the mapping alone."""
        root = self.copy()
        offset = 37 * mw.NS

        def shift(value):
            if isinstance(value, dict):
                return {k: (v + offset if k in ('wall_before_ns', 'wall_after_ns') else shift(v)) for k, v in value.items()}
            if isinstance(value, list):
                return [shift(item) for item in value]
            return value
        population = [shift(json.loads(line)) for line in (root / 'game/telemetry/population.ndjson').read_text().splitlines()]
        (root / 'game/telemetry/population.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in population))
        (root / 'game/telemetry/process.json').write_text(json.dumps(shift(json.loads((root / 'game/telemetry/process.json').read_text()))))
        sampler = [shift(json.loads(line)) for line in (root / 'game/sampler.ndjson').read_text().splitlines()]
        (root / 'game/sampler.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in sampler))
        brackets = json.loads(json.dumps(self.run_data['brackets']))
        for bracket in brackets.values():
            for attempt in bracket['roles']['game']:
                attempt['guest_wall_ns'] += offset
        proof = self.reproved(root, brackets=brackets)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        # The same files with brackets that do not know about the offset cannot prove it.
        unaware = self.reproved(root)
        self.assertNotEqual(unaware['status'], mw.COMPLETE)

    def test_real_clock_ambiguity(self):
        brackets = json.loads(json.dumps(self.run_data['brackets']))
        for attempt in brackets['after']['roles']['game']:
            attempt['guest_wall_ns'] += 7 * mw.NS
        proof = ml.prove(self.run_data, brackets=brackets)
        self.assertIn('clock_ambiguous', codes(proof))
        self.assertEqual(proof['status'], mw.INCONCLUSIVE)
        proof = ml.prove(self.run_data, brackets=dict(before=self.run_data['brackets']['before'], after=None))
        self.assertIn('clock_mapping_missing', codes(proof))

    # ---- identity, on real bytes ----------------------------------------------------------------

    def test_a_reused_pid_and_inode_on_real_rows(self):
        root = self.copy()
        rows = [json.loads(line) for line in (root / 'game/sampler.ndjson').read_text().splitlines()]
        for row in rows[len(rows) // 2:]:
            if 'game' in (row.get('procs') or {}):
                row['procs']['game']['start_id'] = 'bsd:1.000001'
        (root / 'game/sampler.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertIn('pid_reused', codes(self.reproved(root)))
        root = self.copy()
        rows = [json.loads(line) for line in (root / 'bot/sampler.ndjson').read_text().splitlines()]
        for row in rows[len(rows) // 2:]:
            for item in ((row.get('procs') or {}).get('bot') or {}).get('sockets') or []:
                item['inode'] = 'another-socket'
        (root / 'bot/sampler.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertIn('socket_identity_changed', codes(self.reproved(root)))
        game = self.run_data['identities']['game']['game']
        proof = ml.prove(self.run_data, prior=dict(game=dict(processes={(game['pid'], game['start_id'], game['boot_id'])}, inodes=set())))
        self.assertIn('process_identity_reused', codes(proof))

    def test_a_second_real_run_has_no_identity_in_common_with_the_first(self):
        second = self.run_local()
        first, again = self.run_data['identities'], second['identities']
        for role in ('game', 'bot'):
            self.assertNotEqual(first[role][role]['start_id'], again[role][role]['start_id'])
        before = set()
        for row in pathlib.Path(self.run_data['evidence'], 'bot/sampler.ndjson').read_text().splitlines():
            for item in (json.loads(row).get('procs') or {}).get('bot', {}).get('sockets') or []:
                before.add(item['inode'])
        proof = ml.prove(second, prior=dict(bot=dict(processes=set(), inodes=before)))
        self.assertNotIn('socket_identity_reused', codes(proof))
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])


@unittest.skipUnless(RELEASE, 'needs a release build: OMEGA_LOCAL_RELEASE_DIR')
class OutsideFaults(Real):
    """Things done to the frozen binaries from outside: signals and a datagram relay. No hook, no feature."""

    def test_a_delayed_authentication_moves_the_window_and_every_shard_kept_polling(self):
        run = self.run_local(use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(4, 4.0)])
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertGreater(proof['facts']['final_auth_bot_mono_ns'], 3.5 * mw.NS, 'the held bot joined late, and the barrier waited')
        for shard in proof['facts']['shards']:
            self.assertLess(shard['max_poll_gap_ns'], 500_000_000)

    def test_a_warmup_runs_past_the_readiness_bound(self):
        """The review's reproduction: all eight were in by about 0.7 s against a 2 s bound, and the barrier used to give up at 2 s, inside the warmup."""
        run = self.run_local(readiness_timeout_s=2.0)
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertLess(proof['facts']['final_auth_bot_mono_ns'], 2 * mw.NS)
        self.assertGreater(proof['facts']['window_bot_mono_ns'][0], 2 * mw.NS, 'the window opened after the bound had passed')

    def test_a_final_authentication_near_the_readiness_bound_reaches_a_window(self):
        run = self.run_local(use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(4, 3.0)], readiness_timeout_s=4.0)
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        final_auth = proof['facts']['final_auth_bot_mono_ns']
        self.assertGreater(final_auth, 2.5 * mw.NS)
        self.assertLessEqual(final_auth, 4 * mw.NS)
        self.assertGreaterEqual(proof['facts']['window_bot_mono_ns'][0], final_auth + 3 * mw.NS, 'the whole warmup and the lead, past the bound')

    def test_an_authentication_that_never_arrives_establishes_nothing(self):
        run = self.run_local(use_relay=True, schedule=[ml.FaultSchedule.hold_one_bot(2, None)], readiness_timeout_s=4.0)
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertIn('window_not_established', codes(proof))
        window = json.loads(pathlib.Path(run['evidence'], 'bot/swarm/window.json').read_text())
        self.assertEqual(window['status'], 'not_established')
        self.assertIsNone(window['start_ns'])

    def test_poll_starvation_in_the_window(self):
        run = self.run_local(schedule=[ml.FaultSchedule.pause_swarm_in_window(1.5)])
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertIn('poll_starvation', codes(proof))
        self.assertIn('offered_input_below_minimum', codes(proof))

    def test_poll_starvation_through_the_barrier(self):
        run = self.run_local(schedule=[ml.FaultSchedule.pause_swarm_in_barrier(1.0)])
        proof = ml.prove(run)
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertIn('poll_starvation', codes(proof))

    def test_the_swarm_dying_in_the_window_leaves_no_proof(self):
        run = self.run_local(schedule=[ml.FaultSchedule.kill_swarm_in_window()])
        proof = ml.prove(run)
        self.assertNotEqual(proof['status'], mw.COMPLETE)
        self.assertIn('swarm_evidence_missing', codes(proof))
        self.assertEqual(run['results']['bot']['result']['processes']['bot']['signal'], 9)

    def test_the_game_dying_in_the_window_leaves_no_proof(self):
        run = self.run_local(schedule=[ml.FaultSchedule.kill_game_in_window()])
        proof = ml.prove(run)
        self.assertNotEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertIn('recorder_truncated', codes(proof), 'its recorders never finished')


@unittest.skipUnless(RELEASE and FAULT_RELEASE, 'needs a fault-injection build: OMEGA_FAULT_RELEASE_DIR')
class InjectedFaults(Real):
    """What no outside signal can reach: one thread, or one bot. A fault build always names itself in swarm.json, so it can never prove a window."""

    def test_an_early_shard_exit(self):
        proof = ml.prove(self.fault('exit:1:window:1'))
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertTrue({'early_shard_exit', 'missing_acknowledgment', 'window_incomplete', 'fault_injection_build'} <= codes(proof), proof['reasons'])

    def test_one_starved_shard_does_not_stall_the_others_and_is_named(self):
        proof = ml.prove(self.fault('starve:2:window:1:1200'))
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertIn('poll_starvation', codes(proof))
        gaps = [shard['max_poll_gap_ns'] for shard in proof['facts']['shards']]
        self.assertGreaterEqual(gaps[2], 1_200_000_000)
        for index, gap in enumerate(gaps):
            if index != 2:
                self.assertLess(gap, 500_000_000, 'shard %d' % index)

    def test_one_shard_starved_through_the_barrier(self):
        proof = ml.prove(self.fault('starve:3:barrier:0:900'))
        self.assertIn('poll_starvation', codes(proof))

    def test_a_dead_but_connected_input_source_is_invalid_offered_load(self):
        proof = ml.prove(self.fault('mute:3:window:0'))
        self.assertEqual(proof['status'], mw.INVALID)
        self.assertIn('offered_input_below_minimum', codes(proof))
        self.assertEqual(proof['facts']['input']['below_minimum'], [3])
        row = next(item for item in proof['facts']['per_bot_input'] if item['bot'] == 3)
        self.assertEqual(row['sent'], 0)
        self.assertIsNone(row['disconnected'], 'connected the whole time, on real sockets')

    def test_a_fault_build_with_nothing_injected_still_cannot_prove_a_window(self):
        run = self.fault()
        proof = ml.prove(run)
        self.assertEqual(self.proof_status(proof), mw.INCONCLUSIVE, proof['reasons'])
        self.assertEqual(codes(proof), {'fault_injection_build'}, 'it ran a clean window and is refused only for being that binary')
        swarm = json.loads(pathlib.Path(run['evidence'], 'bot/swarm/swarm.json').read_text())
        self.assertEqual(swarm['controls']['faults'], [])
        self.assertIs(swarm['build']['fault_injection'], True)

    def test_a_recorder_that_stops_writing_is_truncation(self):
        proof = ml.prove(self.fault('truncate:1:window:1'))
        self.assertIn('recorder_truncated', codes(proof))
        self.assertNotEqual(proof['status'], mw.COMPLETE)


@unittest.skipUnless(RELEASE and os.environ.get('OMEGA_MEASURE_LONG'), 'needs OMEGA_MEASURE_LONG=1: a real 60 s and a real 300 s window')
class ContractWindows(Real):
    def test_a_real_60_s_window(self):
        run = self.run_local(target=25, hold_s=60)
        proof = ml.prove(run, allow_short_hold=False)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertTrue(proof['facts']['contract_hold'])
        self.assertEqual(proof['facts']['input']['scheduled_total'], 25 * 60 * 30)

    def test_a_real_300_s_window(self):
        run = self.run_local(target=25, hold_s=300)
        proof = ml.prove(run, allow_short_hold=False)
        self.assertEqual(proof['status'], mw.COMPLETE, proof['reasons'])
        self.assertTrue(proof['facts']['contract_hold'])
        self.assertEqual(proof['facts']['input']['scheduled_total'], 25 * 300 * 30)


if __name__ == '__main__':
    unittest.main()
