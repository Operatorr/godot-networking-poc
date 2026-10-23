"""One authorized diagnostic dispatch and native environment fail closed."""
import copy
import pathlib
import tempfile
import unittest
from unittest import mock
import clean_run as live

class NativeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.cell=dict(namespace='clean-idle150-audit-r1-20261022',population=150,behavior='idle',
            revision='5'*40,game_sha256='a'*64,bot_sha256='b'*64,native_diagnostic='v1')
        live.configure_cell(self.cell)
    def test_matched_condition_and_explicit_version_required(self):
        self.assertEqual(live.diagnostic_environment({'diagnostic_environment':{'OMEGA_NATIVE_DIAG':'v1'}}),{'OMEGA_NATIVE_DIAG':'v1'})
        self.assertEqual(live.measurement_limit_bytes(),96*1024**2)
        for change in [dict(namespace='clean-idle150-r1-20261022'),dict(population=100),dict(behavior='movement'),dict(native_diagnostic=True),dict(native_diagnostic='v2')]:
            with self.assertRaises(ValueError):live.configure_cell(self.cell|change)
        for env in [{},{'OMEGA_NATIVE_DIAG':'v2'},{'OMEGA_NATIVE_DIAG':'v1','OTHER':'x'}]:
            with self.assertRaises(RuntimeError):live.diagnostic_environment({'diagnostic_environment':env})
    def test_off_path_is_off_and_inherited_flag_is_rejected(self):
        live.configure_cell({k:v for k,v in self.cell.items() if k!='native_diagnostic'})
        self.assertEqual(live.diagnostic_environment({}),{})
        self.assertEqual(live.measurement_limit_bytes(),1024**3)
        with mock.patch.object(pathlib.Path,'read_bytes',return_value=b'OMEGA_NATIVE_DIAG=v1\0'):
            with self.assertRaises(RuntimeError):live.validate_diagnostic_runtime(42)
    def test_runtime_required_and_versioned(self):
        for raw in [b'',b'OMEGA_NATIVE_DIAG=v2\0',b'OMEGA_NATIVE_DIAG=v1\0OMEGA_NATIVE_DIAG=v1\0']:
            with mock.patch.object(pathlib.Path,'read_bytes',return_value=raw):
                with self.assertRaises(RuntimeError):live.validate_diagnostic_runtime(42)
        with mock.patch.object(pathlib.Path,'read_bytes',return_value=b'OTHER=private\0OMEGA_NATIVE_DIAG=v1\0'):
            self.assertEqual(live.validate_diagnostic_runtime(42),{'OMEGA_NATIVE_DIAG':'v1'})

class NativeReplayTests(unittest.TestCase):
    def test_binary_caps_truncation_and_independent_compact_fingerprints(self):
        import native_diagnostic_analysis as replay
        import collections
        with tempfile.TemporaryDirectory() as temp:
            p=pathlib.Path(temp)/'trace';p.write_bytes(replay.RECORD.pack(1,2,2,1,64,32,0,32,7,1,1))
            self.assertEqual(replay.read_records(p)[0][9],1)
            p.write_bytes(p.read_bytes()+b'x')
            with self.assertRaises(ValueError):replay.read_records(p)
            p.write_bytes(b'ORF1'+replay.DATAGRAM.pack(99,1234,8081,80,60,64,0))
            known=collections.Counter({(1234,64):1})
            self.assertEqual(replay.capture_inputs(p,known),known)
            p.write_bytes(p.read_bytes()+b'x')
            with self.assertRaises(ValueError):replay.capture_inputs(p,known)
    def test_resource_reclaimer_cannot_target_original_or_evidence(self):
        import clean_run_resources as resources
        for path in ['/home/deploy/omega-measured','/home/deploy/omega-results/clean-x',
                     '/home/deploy/omega-clean-x/../omega-measured','/tmp/omega-clean-x']:
            with mock.patch.object(resources.shutil,'rmtree') as delete:
                with self.assertRaises(ValueError):resources.reclaim({'path':path})
                delete.assert_not_called()

class BlockedPreflightAuditTests(unittest.TestCase):
    def test_exclusive_labels_and_launched_state_fail_before_any_host_call(self):
        import native_diagnostic_preflight_audit as blocked
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);base=root/'deployment/hetzner/results';pre=base/(blocked.NS+'-preflight');pre.mkdir(parents=True)
            current=base/blocked.NS;current.mkdir()
            with mock.patch.object(blocked.run,'ROOT',root),mock.patch.object(blocked.audit,'bounded_ssh') as ssh:
                with self.assertRaises(ValueError):blocked.main('../bad')
                out=pre/'old-idle-audit.json';out.write_text('preserved')
                with self.assertRaises(FileExistsError):blocked.main('old')
                self.assertEqual(out.read_text(),'preserved')
                (current/'manifest.json').write_text('{}')
                with self.assertRaises(ValueError):blocked.main('fresh')
                self.assertFalse((pre/'fresh-idle-audit-commands.ndjson').exists())
                ssh.assert_not_called()
