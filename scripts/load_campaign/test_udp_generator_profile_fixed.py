"""No workloads: verify the corrected attempt's real preflight/live gate binding."""
import ast
import inspect
import pathlib
import signal
import tempfile
import unittest
from unittest import mock

import udp_generator_profile as shared
import udp_generator_profile_fixed as fixed
import udp_generator_profile_fixed_preflight as preflight
import udp_capacity150 as capacity
from udp_generator_profile_fixed_details import disassembly, sockets


class FixedAttemptTests(unittest.TestCase):
    def test_preflight_and_live_import_identical_gate(self):
        self.assertIs(fixed.profile_failure, shared.profile_failure)
        self.assertIs(preflight.profile_failure, fixed.profile_failure)
        tree = ast.parse(inspect.getsource(fixed.controller))
        calls = [n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn('profile_failure', calls)
        self.assertIn('validate_status', calls)
        self.assertEqual(calls.count('profile_failure'), 1)

    def test_actual_preflight_call_uses_shared_gate(self):
        observation = {'profiles': {'disposable': {
            'rc': -signal.SIGINT, 'reason': 'nominal-window-end'}}}
        with mock.patch.object(preflight, 'profile_failure', wraps=shared.profile_failure) as gate:
            preflight.validate_status(observation, 42)
            gate.assert_called_once_with(observation, 42)
        self.assertIsNone(fixed.profile_failure(observation, 42))
        for change in ({'rc': 1}, {'reason': 'perf-exited'}, {'reason': 'forced-kill'},
                       {'error': 'ack missing'}, {'reason': 'controller-stop'}):
            observation['profiles']['disposable'] = {
                'rc': -signal.SIGINT, 'reason': 'nominal-window-end', **change}
            with self.assertRaises(RuntimeError):
                preflight.validate_status(observation, 42)
            self.assertIsNotNone(fixed.profile_failure(observation, 42))

    def test_workload_collectors_and_bounds_unchanged(self):
        for name in ('swarm', 'collect'):
            self.assertEqual(inspect.getsource(getattr(fixed, name)),
                             inspect.getsource(getattr(capacity, name)))
        self.assertEqual(fixed.COLLECTOR_REVISION, shared.COLLECTOR_REVISION)
        self.assertEqual((fixed.RAMP_SECONDS, fixed.STEADY_SECONDS), (180, 360))
        self.assertEqual(fixed.NAMESPACE, 'udp-generator-profile-fixed-20261021')
        self.assertNotEqual(fixed.REMOTE, shared.REMOTE)
        self.assertNotEqual(fixed.OVERRIDE, shared.OVERRIDE)
        source = inspect.getsource(fixed.controller)
        self.assertLess(source.index('validate_status(sampler'), source.index("manifest['workload_launch_attempted']"))
        self.assertIn("open('x')", source)
        self.assertNotIn("REMOTE + '/udp_generator_profile.py'", source)

    def test_disassembly_counts_only_qualified_iterator_subset(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d)
            text = ('(100 samples, percent: local period)\n'
                    '1000 <omega_load_test::bot::Bot::poll>:\n'
                    '50.00 : 1000: unrelated\n'
                    '2.00 : 26c0: ldurh w8, [x8, #-2]\n'
                    '3.00 : 26c4: lsr w8, w8, #4\n'
                    '5.00 : 26c8: cmp w8, #0x753\n'
                    '40.00 : 271c: downstream\n')
            (p/'poll-annotate.txt').write_text(text)
            result = disassembly(p, 1000)
            self.assertEqual(result['samples_reconstructed_from_rounded_local_period_percent'], 10)
            self.assertEqual(result['percent_of_all_samples'], 1)
            (p/'poll-annotate.txt').write_text(text.replace('#0x753', '#0x100'))
            with self.assertRaises(ValueError):
                disassembly(p, 1000)

    def test_transient_socket_retains_unknown_pid_and_real_counters(self):
        row = ('UNCONN uid:1000 ino:42 sk:1 '
               'cgroup:/system.slice/omega-example-swarm.service <->\n'
               ' skmem:(r0,rb212992,t0,tb212992,f0,w0,o0,bl0,d0)\n')
        parsed = sockets(row)[0]
        self.assertIsNone(parsed['pid'])
        self.assertIsNone(parsed['comm'])
        self.assertEqual((parsed['inode'], parsed['d'], parsed['rb']), (42, 0, 212992))
        owned = row.replace('uid:1000', 'users:(("omega-load-test",pid=7,fd=8)) uid:1000')
        self.assertEqual(sockets(owned)[0]['pid'], 7)
        with self.assertRaises(ValueError):
            sockets(row.replace('ino:42', 'missing'))


if __name__ == '__main__':
    unittest.main()
