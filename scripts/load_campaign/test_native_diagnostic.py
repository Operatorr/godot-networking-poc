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
    def test_fresh_r2_dispatch_requires_exact_source_binaries_and_own_build_proof(self):
        import clean_run_build as build
        cell=self.cell|dict(namespace=build.NATIVE_R2,revision=build.NATIVE_REVISION,
                           game_sha256=build.NATIVE_HASHES[0],bot_sha256=build.NATIVE_HASHES[1])
        live.configure_cell(cell)
        self.assertEqual(live.REMOTE,'/home/deploy/omega-results/'+build.NATIVE_R2)
        self.assertIn(build.NATIVE_R2,live.EXPERIMENT_BINARIES['bots'])
        for key in ('revision','game_sha256','bot_sha256'):
            with self.assertRaises(ValueError):live.configure_cell(cell|{key:'0'*len(cell[key])})
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp);script=root/'scripts/load_campaign/clean_run.py'
            script.parent.mkdir(parents=True)
            directory=root/'deployment/hetzner/results'/(build.NATIVE_R2+'-build');directory.mkdir(parents=True)
            import json
            row=dict(revision=build.NATIVE_REVISION,sha256=build.NATIVE_HASHES[0],bot_sha256=build.NATIVE_HASHES[1],
                     path='/home/deploy/omega-clean-idle150-audit-r1-20261022')
            f=directory/'build-proof.json';f.write_text(json.dumps(dict(game=row,bots=row)))
            with mock.patch.object(live,'__file__',str(script)):
                with self.assertRaises(RuntimeError):live.load_cell(build.NATIVE_R2,150,'idle')
                row['path']='/home/deploy/omega-'+build.NATIVE_R2
                f.write_text(json.dumps(dict(game=row,bots=row)))
                live.load_cell(build.NATIVE_R2,150,'idle')
                live.configure_cell(live.CELL|dict(native_diagnostic='v1'))
                self.assertEqual(live.CELL,cell)
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
    def test_sampled_fingerprint_timestamps_keep_exact_boundary_crossings(self):
        import native_diagnostic_analysis as replay
        rows=[(1,3,99,1,64,32,0,32,7,1,1),
              (1,3,99,2,64,32,0,32,7,1,2), # two inputs in one datagram
              (1,3,101,3,128,32,0,32,7,1,3)]
        captured={(1234,64):[100],(1234,128):[102]}
        r=replay.fingerprint_timing(rows,captured,1234,(100,200))
        self.assertEqual(r['paired_sampled_datagrams'],2)
        self.assertEqual(r['unpaired_sampled_datagrams'],0)
        self.assertEqual(r['capture_minus_native_ns']['min'],1)
        self.assertEqual(len(r['exact_window_membership_differences']),1)
        self.assertFalse(r['exact_window_membership_differences'][0]['native_in_window'])
    def test_counter_witness_with_changed_throttle_remains_ambiguous(self):
        import native_diagnostic_analysis as replay
        def record(pre,post,counter=21,after=28):
            return (1,2,0,1,0,pre,counter,post,after,5,0)
        rows=[record(27,27),record(27,28),record(27,27,21,29)]
        result=replay.throttle_trace_classification(rows)
        self.assertEqual(result['single_step_pre_predicate'],2)
        self.assertEqual(result['stable_throttle_single_step'],1)
        self.assertEqual(result['throttle_changed'],1)
        self.assertEqual(len(result['ambiguous']),2)
        self.assertEqual(result['ambiguous'][0]['reason'],'throttle-changed')
    def test_combined_storage_includes_original_copy_archive_and_unchanged_guard(self):
        import native_diagnostic_storage as storage
        # The old free>8GiB check passes, but the additive allowance must fail.
        r=storage.budget(storage.GUARD+500_000_000,196_087_808,40_000_000)
        self.assertFalse(r['passed'])
        self.assertEqual(r['unchanged_guard_bytes'],8*1024**3)
        self.assertEqual(r['allowances']['original_measurement_copy'],196_087_808)
        self.assertEqual(r['allowances']['live_game_payload'],96*1024**2)
        self.assertEqual(r['allowances']['journal'],24*1024**2)
        exact=storage.GUARD+r['combined_bytes']
        self.assertTrue(storage.budget(exact,196_087_808,40_000_000)['passed'])
        self.assertFalse(storage.budget(exact-1,196_087_808,40_000_000)['passed'])
        for args in ((-1,0,0),(1,True,0),(1,0,0.0)):
            with self.assertRaises(ValueError):storage.budget(*args)
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
            self.assertEqual(replay.capture_inputs(p,known,(99,100)),known)
            self.assertEqual(replay.capture_inputs(p,known,(0,99)),{})
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
