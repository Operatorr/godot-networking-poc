"""Exercise the generated maintenance wrapper and shared real recovery shell."""
import os
import pathlib
import subprocess
import sys
import unittest

import idle_measurement_maintenance as maintenance
import test_clean_run_recovery as recovery_tests


class MaintenanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recovery_tests.RecoveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.use_atomic_preservation()
        self.remote = self.fixture.remote
        (self.remote/'restore.sh').write_bytes(self.fixture.script.read_bytes())
        self.wrapper = self.fixture.root/'guarded-restore.sh'
        self.wrapper.write_text(maintenance.guarded_script(str(self.remote)))
        # macOS lacks util-linux flock. This shim validates the actual generated
        # command/lock path and uses the kernel's advisory lock. Host commands and
        # proc identity use the existing shared recovery fixture's narrow shims.
        shim = self.fixture.bin/'flock'
        shim.write_text('#!'+sys.executable+'\n'+'''import fcntl,os,pathlib,sys
assert sys.argv[1:3]==['-w','20']
root=pathlib.Path(os.environ['RECOVERY_TEST_ROOT'])
assert pathlib.Path(sys.argv[3])==root/'experiment/recovery.lock'
with open(sys.argv[3],'a') as stream:
 try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:sys.exit(75)
 os.set_inheritable(stream.fileno(),True)
 os.execv(sys.argv[4],sys.argv[4:])
''')
        shim.chmod(0o755)

    def call(self, mode='restore'):
        return subprocess.run(['/bin/sh',str(self.wrapper),mode],env=self.fixture.env,
                              capture_output=True,text=True,timeout=10)

    def test_generated_wrapper_preserves_original_inodes_then_restores(self):
        old={p.name:(p.stat().st_dev,p.stat().st_ino) for p in self.fixture.measurement.iterdir()}
        result=self.call('preserve')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.fixture.measurement.exists())
        self.assertEqual(self.fixture.current_state()['starts'],[])
        backup=self.remote/'original/measurement-current'
        self.assertEqual({p.name:(p.stat().st_dev,p.stat().st_ino) for p in backup.iterdir()},old)
        result=self.call()
        self.assertEqual(result.returncode,0,result.stderr)
        self.fixture.assert_original_recoverable()
        self.assertEqual(self.fixture.current_state()['starts'],['original'])
        self.assertNotEqual(self.fixture.measurement.stat().st_ino,backup.stat().st_ino)

    def test_generated_wrapper_failed_rename_stays_stopped_and_keeps_originals(self):
        (self.fixture.root/'fail-rename').touch()
        result=self.call()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.fixture.current_state()['starts'],[])
        self.fixture.assert_original_recoverable()

    def test_generated_wrapper_cannot_stop_service_without_exclusive_lock(self):
        import fcntl
        with (self.remote/'recovery.lock').open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=self.call()
        self.assertEqual(result.returncode,75)
        self.assertEqual(self.fixture.current_state()['calls'],[])
        self.fixture.assert_original_recoverable()


if __name__=='__main__':
    unittest.main()
