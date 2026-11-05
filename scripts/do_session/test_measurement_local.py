"""What ``measurement_local`` does when something goes wrong around a run. Nothing real runs here: the runners are stand-ins, so this is cleanup and nothing else."""
import json
import pathlib
import shutil
import tempfile
import time
import unittest

import measurement_local as ml


class FakeRunner:
    """Answers just enough of the runner CLI. ``failures`` maps a (role, command) to the exception to raise, or to a falsey-ok answer."""

    def __init__(self, calls, failures, root, role, runner_path):
        self.calls, self.failures, self.role = calls, failures, role

    def __call__(self, command, *arguments, check=True):
        self.calls.append((self.role, command))
        failure = self.failures.get((self.role, command))
        if failure is not None:
            raise failure
        if command == 'clock':
            return dict(wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns(), boot_id='boot')
        if command == 'grant_prepare':
            return dict(grant_id='grant-%s' % self.role)
        if command == 'start':
            return dict(processes={self.role: dict(pid=1)}, supervisor=dict(pid=2))
        if command == 'status':
            return dict(socket=True, result=dict(ok=True))
        return dict(ok=True)


class FakeRelay:
    port = 9

    def __init__(self, failure=None):
        self.stops, self.failure = 0, failure

    def stop(self):
        self.stops += 1
        if self.failure is not None:
            raise self.failure


class Cleanup(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix='omega-local-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.release = self.root / 'release'
        self.release.mkdir()
        for name in ('omega-server', 'omega-load-test'):
            (self.release / name).write_bytes(b'stand-in')

    def run_local(self, failures=None, relay=None, release=None):
        calls = []
        failures = failures or {}
        run = ml.LocalRun(release or self.release, self.root / 'run', 8, 6, runner_factory=lambda root, role, path: FakeRunner(calls, failures, root, role, path))
        run.relay = relay
        self.addCleanup(lambda: None)
        return run, calls

    def stops(self, calls):
        return [role for role, command in calls if command == 'stop']

    def test_a_clean_run_stops_both_roles_once_in_reverse_order(self):
        relay = FakeRelay()
        run, calls = self.run_local(relay=relay)
        with self.assertRaises(FileNotFoundError):      # past every stop, into evidence a stand-in never wrote
            run.execute()
        self.assertEqual(self.stops(calls), ['bot', 'game'])
        self.assertEqual(relay.stops, 1)
        self.assertEqual([command for _, command in calls].count('seal'), 2)

    def test_a_failed_bot_stop_with_a_clean_run_still_stops_the_rest_and_says_so(self):
        relay = FakeRelay()
        run, calls = self.run_local({('bot', 'stop'): RuntimeError('stop refused')}, relay)
        with self.assertRaises(ml.CleanupFailed) as caught:
            run.execute()
        self.assertEqual(self.stops(calls), ['bot', 'game'], 'the game was still stopped')
        self.assertEqual(relay.stops, 1, 'and the relay')
        self.assertEqual(len(caught.exception.failures), 1)
        self.assertIn('stop bot', caught.exception.failures[0])
        self.assertIn('stop refused', caught.exception.failures[0])
        self.assertNotIn('seal', [command for _, command in calls], 'nothing is sealed over a process that may still run')

    def test_every_cleanup_failure_is_reported_not_only_the_first(self):
        relay = FakeRelay(OSError('relay stuck'))
        run, calls = self.run_local({('bot', 'stop'): RuntimeError('bot refused'), ('game', 'stop'): TimeoutError('game hung')}, relay)
        with self.assertRaises(ml.CleanupFailed) as caught:
            run.execute()
        self.assertEqual(self.stops(calls), ['bot', 'game'])
        self.assertEqual(relay.stops, 1)
        text = ' | '.join(caught.exception.failures)
        for expected in ('bot refused', 'game hung', 'relay stuck'):
            self.assertIn(expected, text)

    def test_an_execution_failure_stays_the_primary_error_and_cleanup_still_runs(self):
        relay = FakeRelay()
        primary = RuntimeError('the swarm outlived its bound')
        run, calls = self.run_local({('bot', 'status'): primary, ('bot', 'stop'): RuntimeError('stop refused')}, relay)
        with self.assertRaises(RuntimeError) as caught:
            run.execute()
        self.assertIs(caught.exception, primary, 'the cleanup failure does not mask it')
        self.assertEqual(self.stops(calls), ['bot', 'game'])
        self.assertEqual(relay.stops, 1)
        self.assertEqual(len(primary.cleanup_failures), 1)
        self.assertIn('stop refused', primary.cleanup_failures[0])

    def test_an_execution_failure_with_clean_stops_has_no_cleanup_failures(self):
        primary = RuntimeError('the swarm outlived its bound')
        run, calls = self.run_local({('bot', 'status'): primary})
        with self.assertRaises(RuntimeError) as caught:
            run.execute()
        self.assertIs(caught.exception, primary)
        self.assertFalse(hasattr(primary, 'cleanup_failures'))
        self.assertEqual(self.stops(calls), ['bot', 'game'])

    def test_a_setup_failure_after_the_relay_exists_still_stops_the_relay(self):
        for key in (('game', 'fence'), ('bot', 'fence'), ('game', 'clock'), ('game', 'grant_prepare')):
            with self.subTest(key=key):
                shutil.rmtree(self.root / 'run', True)
                relay = FakeRelay()
                primary = RuntimeError('setup failed')
                run, calls = self.run_local({key: primary}, relay)
                with self.assertRaises(RuntimeError) as caught:
                    run.execute()
                self.assertIs(caught.exception, primary)
                self.assertEqual(relay.stops, 1)
                self.assertEqual(self.stops(calls), [], 'nothing was started')

    def test_a_failure_before_any_runner_exists_still_stops_the_relay(self):
        relay = FakeRelay()
        run, calls = self.run_local(relay=relay, release=self.root / 'no-such-release')
        with self.assertRaises(OSError):
            run.execute()
        self.assertEqual(relay.stops, 1)
        self.assertEqual(calls, [])

    def test_a_start_that_raised_is_still_stopped_because_it_may_have_left_a_process(self):
        relay = FakeRelay()
        primary = RuntimeError('no reply to start')
        run, calls = self.run_local({('bot', 'start'): primary}, relay)
        with self.assertRaises(RuntimeError) as caught:
            run.execute()
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.stops(calls), ['bot', 'game'])
        self.assertEqual(relay.stops, 1)

    def test_a_real_relay_is_really_stopped_after_a_setup_failure(self):
        primary = RuntimeError('fence refused')
        calls = []
        run = ml.LocalRun(self.release, self.root / 'run', 8, 6, use_relay=True, runner_factory=lambda root, role, path: FakeRunner(calls, {('game', 'fence'): primary}, root, role, path))
        with self.assertRaises(RuntimeError) as caught:
            run.execute()
        self.assertIs(caught.exception, primary)
        self.assertFalse(run.relay.is_alive(), 'its thread has ended')
        self.assertEqual(run.relay.front.fileno(), -1, 'and its socket is closed')


class RealRunnerRefusal(unittest.TestCase):
    def test_the_real_runner_wrapper_raises_on_refusal_and_on_a_bad_answer(self):
        """The stop in cleanup goes through this. A refusal raises unless the caller asked not to check, which is what an unconfirmed start uses."""
        root = pathlib.Path(tempfile.mkdtemp(prefix='omega-local-'))
        self.addCleanup(shutil.rmtree, root, True)
        script = root / 'refuses.py'
        script.write_text('import json; print(json.dumps(dict(ok=False, code="nope", detail="refused")))\n')
        runner = ml.Runner(root, 'bot', script)
        with self.assertRaises(RuntimeError):
            runner('stop')
        self.assertEqual(json.loads(json.dumps(runner('stop', check=False)))['code'], 'nope')


if __name__ == '__main__':
    unittest.main()
