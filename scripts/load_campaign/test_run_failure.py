"""Exercise aborted-ramp cleanup with local fixtures; never contact the hosts."""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock
import run


class FailedRampTests(unittest.TestCase):
    def exercise(self, log, phase=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        remote = root / 'remote'
        bot_dir = remote / 'failed-ramp' / 'bots'
        bot_dir.mkdir(parents=True)
        (bot_dir / 'bot.log').write_text(log)
        if phase:
            (bot_dir / 'phase.json').write_text(json.dumps(phase))
        calls, copies = [], []
        polls = 0

        def ssh(role, command, check=True):
            nonlocal polls
            calls.append((role, command))
            if command.startswith('df '):
                return str(32 * 1024 ** 3)
            if command.startswith('tail -5 '):
                polls += 1
                if polls > 1:
                    raise AssertionError('Controller continued after failed join')
                return subprocess.run(['bash', '-c', command], capture_output=True, text=True).stdout
            if '--property=InvocationID' in command:
                return 'fixture-invocation'
            return ''

        def copy(role, source, destination, download=False):
            copies.append((role, download))
            if download:
                pathlib.Path(destination).write_bytes(b'retained endpoint archive fixture')

        raw = root / 'raw'
        raw.mkdir()
        with mock.patch.multiple(run, RAW=raw, REMOTE=str(remote)), \
             mock.patch.object(run, 'ssh', side_effect=ssh), \
             mock.patch.object(run, 'copy', side_effect=copy), \
             mock.patch.object(run.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Ramp failed'):
                run.run('failed-ramp', 999, 'movement', collection=False,
                        build='instrumented' if phase else 'original', configure_service=False)
        directory = raw / 'failed-ramp'
        failure = json.loads((directory / 'ramp-failure.json').read_text())
        self.assertEqual(failure['classification'], 'ramp-failed-unscored')
        self.assertEqual(failure['requested_bots'], 999)
        self.assertFalse((directory / 'window.json').exists())
        self.assertIn('Ramp failed', (directory / 'controller-error.txt').read_text())
        manifest = json.loads((directory / 'manifest.json').read_text())
        self.assertIn('ended_utc', manifest)
        self.assertEqual(set(manifest['cleanup_stages']), {'game', 'bots'})
        self.assertEqual({role for role, download in copies if download}, {'game', 'bots'})
        for role in ('game', 'bots'):
            self.assertTrue(any(r == role and 'systemctl stop' in command for r, command in calls))
            self.assertTrue((directory / (role + '.tar.gz')).exists())
        launch = next(command for role, command in calls if '--unit=omega-campaign-failed-ramp-swarm' in command)
        self.assertIn('--property=RuntimeMaxSec=', launch)
        return failure

    def test_failure_before_last_five_lines_stops_and_preserves_both_endpoints(self):
        log = 'WARN Bot 1 failed to connect: connect timeout\n'
        log += ''.join(f'INFO Connected {number}/999 bots...\n' for number in range(2, 22))
        result = self.exercise(log)
        self.assertIn('Bot 1 failed to connect', result['line'])

    def test_failed_start_cannot_be_promoted_by_phase_two_marker(self):
        self.exercise('WARN Bot 1 failed to start: socket unavailable\n',
                      {'phase2_utc_ns': 1_000_000_000})

    def test_successful_ramp_keeps_phase_and_finished_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            (path / 'bot.log').write_text('INFO Connected 50/50 bots...\n')
            (path / 'phase.json').write_text('{"phase2_utc_ns": 1000000000}')
            (path / 'exit-code').write_text('0')
            output = subprocess.run(['bash', '-c', run.swarm_status_command(directory, True)],
                                    capture_output=True, text=True).stdout
            self.assertNotIn('OMEGA_RAMP_FAILURE', output)
            self.assertIn('{"phase2_utc_ns": 1000000000}', output)
            self.assertIn('FINISHED', output)


if __name__ == '__main__':
    unittest.main()
