"""Exercise the real status/identity reads while a bot's proc files disappear."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import clean_run as live


class StatusProcessExitTests(unittest.TestCase):
    def observe(self, missing=None, problem=None):
        cell = dict(namespace='clean-status-exit-test', population=2, behavior='idle',
                    revision='a'*40, game_sha256='b'*64, bot_sha256='c'*64)
        live.configure_cell(cell)
        original_text = pathlib.Path.read_text
        original_bytes = pathlib.Path.read_bytes
        original_exists = pathlib.Path.exists
        proc = '/proc/881605'

        def maybe_fail(path):
            if str(path) == missing:
                raise (problem or FileNotFoundError(2, 'No such file or directory', str(path)))

        def read_text(path, *args, **kwargs):
            maybe_fail(path)
            if str(path) == proc+'/stat':
                return '881605 (omega-load-test) '+' '.join(['S']+['0']*18+['12345'])
            return original_text(path, *args, **kwargs)

        def read_bytes(path, *args, **kwargs):
            maybe_fail(path)
            if str(path) == proc+'/exe':
                return b'frozen bot executable'
            if str(path) == proc+'/environ':
                return b'OMEGA_NATIVE_DIAG=v1\0' if missing == 'bad-environment' else b''
            return original_bytes(path, *args, **kwargs)

        def readlink(path):
            maybe_fail('readlink' if missing == 'readlink' else path)
            return live.EXPERIMENT_BINARIES['bots']

        def exists(path):
            return True if str(path) == proc else original_exists(path)

        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)/'bots'
            directory.mkdir()
            (directory/'workload-start.json').write_text(json.dumps(dict(pid=881605)))
            (directory/'phase.json').write_text(json.dumps(dict(phase2_utc_ns=1)))
            output = io.StringIO()
            with (patch.object(live, 'REMOTE', tmp),
                  patch.object(live, 'source_identity', return_value={}),
                  patch.object(live, 'command', return_value=''),
                  patch.object(pathlib.Path, 'exists', exists),
                  patch.object(pathlib.Path, 'read_text', read_text),
                  patch.object(pathlib.Path, 'read_bytes', read_bytes),
                  patch.object(live.os, 'readlink', readlink),
                  contextlib.redirect_stdout(output)):
                live.status('bots')
            return json.loads(output.getvalue())

    def test_disappearance_at_each_real_proc_read_is_missing_identity(self):
        for missing in ('/proc/881605/stat', '/proc/881605/exe', 'readlink', '/proc/881605/environ'):
            with self.subTest(missing=missing):
                observed = self.observe(missing)
                self.assertIsNone(observed.get('bot_identity'))
                window = dict(end=360_000_000_001)
                self.assertEqual(live.bot_runtime_problem(observed, window, window['end']-1),
                                 'bot-runtime-identity-missing')
                self.assertIsNone(live.bot_runtime_problem(observed, window, window['end']+1))
                self.assertEqual(live.bot_runtime_problem(observed, window, window['end']+10_000_000_000),
                                 'bot-terminal-result-timeout')

    def test_live_process_keeps_actual_identity_and_environment(self):
        observed = self.observe()
        self.assertEqual(observed['bot_identity']['pid'], 881605)
        self.assertEqual(observed['bot_identity']['start_ticks'], 12345)
        self.assertEqual(observed['native_diagnostic_environment'], {})
        with self.assertRaisesRegex(RuntimeError, 'Bot runtime identity changed'):
            live.validate_bot_identity(observed['bot_identity'])

    def test_permission_errors_are_not_normal_teardown(self):
        with self.assertRaises(PermissionError):
            self.observe('/proc/881605/exe', PermissionError(13, 'Permission denied'))

    def test_unexpected_environment_still_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'Native diagnostic runtime environment mismatch'):
            self.observe('bad-environment')
