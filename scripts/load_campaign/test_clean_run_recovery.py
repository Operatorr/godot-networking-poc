"""Run the actual recovery shell with temporary evidence and mocked host commands."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import clean_run as live


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.measurement = self.root / 'current'
        self.measurement.mkdir()
        self.original = {'ticks.csv': b'old tick evidence\n', 'server.ndjson': b'old server evidence\n'}
        for name, data in self.original.items():
            (self.measurement / name).write_bytes(data)
        self.remote = self.root / 'experiment'
        (self.remote / 'original').mkdir(parents=True)
        self.override = self.root / 'diagnostic.conf'
        self.config = self.root / 'arena.json'
        self.config.write_text('{}')
        self.native_override = self.root / 'measurement.conf'
        self.native_override.write_text('original environment')
        self.state = self.root / 'state.json'
        self.state.write_text(json.dumps({'cached': 'original', 'calls': [], 'starts': []}))
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        # The command shim performs real local copies and startup truncation. Only
        # systemd/proc identity and injected copy/reload failures are simulated.
        shim = '''import hashlib, json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ['RECOVERY_TEST_ROOT'])
state_path = root/'state.json'
s = json.loads(state_path.read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
def save(): state_path.write_text(json.dumps(s))
if name == 'systemctl':
    s['calls'].append(args); save()
    if args[0] == 'daemon-reload':
        fail = root/'fail-reload'
        if fail.exists(): fail.unlink(); sys.exit(1)
        s['cached'] = 'diagnostic' if (root/'diagnostic.conf').exists() else 'original'
    elif args[0] == 'start':
        s['starts'].append(s['cached'])
        for f in (root/'current').iterdir():
            if f.is_file(): f.write_bytes(b'new startup evidence')
    elif args[0] == 'show':
        if 'MainPID' in args:
            s['pid_queries'] = s.get('pid_queries', 0) + 1
            print('0' if (root/'delayed-pid').exists() and s['pid_queries']==1 else
                  '43' if (root/'changed-pid').exists() and s['pid_queries']>1 else '42')
        elif 'ActiveState' in args: print('active')
        elif 'NRestarts' in args:
            s['restart_queries'] = s.get('restart_queries', 0) + 1
            print('1' if (root/'restarted').exists() and s['restart_queries']>1 else '0')
        elif 'Environment' in args:
            print('OMEGA_MEASURE_DIR='+str(root/'current') if s['cached']=='original' else 'OMEGA_AOI_AUDIT=1')
            if (root/'audit-env').exists(): print('OMEGA_AOI_AUDIT=1')
    save()
elif name == 'cp':
    source, dest = map(pathlib.Path, args[-2:])
    if source.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(sorted(source.iterdir())):
            shutil.copy2(f, dest/f.name)
            if (root/'fail-copy').exists(): sys.exit(1)
    else: shutil.copy2(source, dest)
elif name == 'sha256sum':
    if args[0].startswith('/proc/'):
        s['hash_queries'] = s.get('hash_queries', 0) + 1; save()
        digest = 'pre-exec-image' if (root/'delayed-exec').exists() and s['hash_queries']==1 else os.environ['RECOVERY_TEST_GAME_HASH']
        print(digest+'  '+args[0])
    elif args[0] == '-c':
        for line in pathlib.Path(args[1]).read_text().splitlines():
            digest, path = line.split('  ', 1)
            if hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()!=digest: sys.exit(1)
    else:
        for path in args: print(hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()+'  '+path)
elif name == 'python3':
    if (root/'fail-rename').exists() and 'os.rename(' in args[-1]: sys.exit(1)
    os.execv(sys.executable,[sys.executable,*args])
'''
        for name in ('systemctl', 'cp', 'sha256sum', 'python3'):
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\n' + shim)
            path.chmod(0o755)
        patches = dict(REMOTE=str(self.remote), OVERRIDE=str(self.override),
                       MEASUREMENT_DIRECTORY=str(self.measurement),
                       NATIVE_CONFIG=str(self.config), MEASUREMENT_OVERRIDE=str(self.native_override),
                       RESTORE_READY_ATTEMPTS=4)
        self.patches = patches
        with mock.patch.multiple(live, create=True, **patches):
            script = live.recovery_script()
        self.script = self.root / 'restore.sh'
        self.script.write_text(script)
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                        RECOVERY_TEST_ROOT=str(self.root), RECOVERY_TEST_GAME_HASH=live.PINNED['game'])

    def run_recovery(self, mode='restore'):
        return subprocess.run(['/bin/sh', str(self.script), mode], env=self.env,
                              capture_output=True, text=True)

    def current_state(self):
        return json.loads(self.state.read_text())

    def assert_original_recoverable(self):
        backup = self.remote / 'original/measurement-current'
        for name, data in self.original.items():
            self.assertTrue(((self.measurement/name).exists() and (self.measurement/name).read_bytes() == data)
                            or ((backup/name).exists() and (backup/name).read_bytes() == data), name)

    def use_atomic_preservation(self):
        with mock.patch.multiple(live, create=True, **self.patches), mock.patch.object(live,'CELL',
                {'native_diagnostic':'v1','measurement_preservation':'rename-v1'}):
            self.script.write_text(live.recovery_script())

    def test_atomic_preservation_moves_original_inodes_without_copying_payload(self):
        self.use_atomic_preservation()
        original_inodes={name:(self.measurement/name).stat().st_ino for name in self.original}
        result=self.run_recovery('preserve')
        self.assertEqual(result.returncode,0,result.stderr)
        backup=self.remote/'original/measurement-current'
        self.assertEqual({name:(backup/name).stat().st_ino for name in self.original},original_inodes)
        self.assertFalse(self.measurement.exists())
        self.assertEqual(self.current_state()['starts'],[])
        result=self.run_recovery()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(self.measurement.is_dir())
        self.assert_original_recoverable()

    def test_atomic_preservation_can_resume_after_rename_before_verified_marker(self):
        self.use_atomic_preservation()
        backup=self.remote/'original/measurement-current'
        import hashlib
        manifest=self.remote/'original/measurement-sha256.txt'
        manifest.write_text(''.join(hashlib.sha256(data).hexdigest()+'  ./'+name+'\n' for name,data in self.original.items()))
        self.measurement.rename(backup)
        result=self.run_recovery()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assert_original_recoverable()

    def test_atomic_preservation_rejects_conflicting_or_corrupted_partial_backup(self):
        self.use_atomic_preservation()
        backup=self.remote/'original/measurement-current';backup.mkdir()
        (backup/'ticks.csv').write_text('unverified conflict')
        self.assertNotEqual(self.run_recovery().returncode,0)
        self.assertEqual(self.current_state()['starts'],[])
        for name,data in self.original.items():self.assertEqual((self.measurement/name).read_bytes(),data)

    def test_failed_atomic_rename_never_falls_back_to_copy_or_starts_service(self):
        self.use_atomic_preservation()
        (self.root/'fail-rename').touch()
        self.assertNotEqual(self.run_recovery().returncode,0)
        self.assertEqual(self.current_state()['starts'],[])
        self.assertFalse((self.remote/'original/measurement-current').exists())
        for name,data in self.original.items():self.assertEqual((self.measurement/name).read_bytes(),data)
        (self.root/'fail-rename').unlink()
        result=self.run_recovery()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assert_original_recoverable()

    def test_persistent_partial_copy_failure_never_restarts_or_loses_evidence(self):
        (self.root/'fail-copy').touch()
        for mode in ('preserve', 'restore', 'restore'):
            self.assertNotEqual(self.run_recovery(mode).returncode, 0)
            self.assert_original_recoverable()
        self.assertEqual(self.current_state()['starts'], [])

    def test_recovery_retries_interrupted_preservation_before_restart(self):
        (self.root/'fail-copy').touch()
        self.assertNotEqual(self.run_recovery('preserve').returncode, 0)
        (self.root/'fail-copy').unlink()
        result = self.run_recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_original_recoverable()
        self.assertEqual(self.current_state()['starts'], ['original'])

    def test_reload_failure_is_retried_after_override_retirement(self):
        self.override.write_text('diagnostic')
        state = self.current_state() | {'cached': 'diagnostic'}
        self.state.write_text(json.dumps(state))
        (self.root/'fail-reload').touch()
        self.assertNotEqual(self.run_recovery().returncode, 0)
        self.assertFalse(self.override.exists())
        result = self.run_recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_state()['starts'], ['original'])
        self.assert_original_recoverable()

    def test_preserve_mode_verifies_backup_without_starting(self):
        result = self.run_recovery('preserve')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_state()['starts'], [])
        backup = self.remote/'original/measurement-current'
        for name, data in self.original.items():
            self.assertEqual((backup/name).read_bytes(), data)

    def test_runtime_identity_failure_cannot_report_restoration_success(self):
        self.env['RECOVERY_TEST_GAME_HASH'] = 'wrong-build'
        result = self.run_recovery()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('result=1 step=await-pinned-executable', result.stderr)
        self.assert_original_recoverable()

    def test_damaged_verified_backup_prevents_restart(self):
        self.assertEqual(self.run_recovery('preserve').returncode, 0)
        (self.remote/'original/measurement-current/ticks.csv').write_text('corrupt')
        self.assertNotEqual(self.run_recovery().returncode, 0)
        self.assertEqual(self.current_state()['starts'], [])
        self.assert_original_recoverable()

    def test_leftover_audit_environment_cannot_report_success(self):
        (self.root/'audit-env').touch()
        self.assertNotEqual(self.run_recovery().returncode, 0)
        self.assert_original_recoverable()

    def test_simple_service_can_publish_pid_after_start_returns(self):
        (self.root/'delayed-pid').touch()
        result = self.run_recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_state()['starts'], ['original'])
        self.assert_original_recoverable()

    def test_simple_service_pre_exec_image_is_not_final_identity(self):
        (self.root/'delayed-exec').touch()
        result = self.run_recovery()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_state()['starts'], ['original'])
        self.assert_original_recoverable()

    def test_service_restart_or_pid_change_cannot_be_hidden_by_readiness_retry(self):
        for marker in ('restarted', 'changed-pid'):
            with self.subTest(marker=marker):
                (self.root/marker).touch()
                self.state.write_text(json.dumps({'cached':'original','calls':[],'starts':[]}))
                result = self.run_recovery()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('result=1 step=await-pinned-executable', result.stderr)
                self.assertEqual(self.current_state()['starts'], ['original'])
                (self.root/marker).unlink()


if __name__ == '__main__':
    unittest.main()
