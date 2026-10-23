"""Exact ordinary follow-up dispatch; no remote workload is run by these tests."""
import copy
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import clean_run as live
import native_diagnostic_r4 as reuse

NS = 'clean-movement150-r1-20261023'


def cell():
    return dict(namespace=NS, revision=reuse.REVISION, population=150, behavior='movement',
                game_sha256=reuse.GAME_SHA, bot_sha256=reuse.BOT_SHA,
                classification_version='offered-load-v2', native_diagnostic=False, evidence_profile='movement150-compact-v1',
                measurement_preservation='rename-v1', native_build_origin='bots',
                game_artifact_mode='verified-existing-build-copy')


class Movement150Tests(unittest.TestCase):
    def test_exact_profile_and_rejections(self):
        live.configure_cell(cell())
        self.assertEqual(live.measurement_limit_bytes(), 16*1024**2)
        for change in (dict(namespace=NS+'-retry'), dict(classification_version='strict-v1'), dict(classification_version=None), dict(classification_version='unknown'), dict(population=100), dict(behavior='idle'),
                       dict(revision='0'*40), dict(game_sha256='0'*64), dict(bot_sha256='0'*64),
                       dict(evidence_profile='other'), dict(native_diagnostic='v1'),
                       dict(native_diagnostic='v0'), dict(native_diagnostic=0),
                       dict(measurement_preservation='copy'), dict(native_build_origin='game'),
                       dict(game_artifact_mode='native-build')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live.configure_cell(cell() | change)
        missing=cell();missing.pop('classification_version')
        with self.assertRaises(ValueError):live.configure_cell(missing)
        absent=cell(); absent.pop('native_diagnostic'); live.configure_cell(absent)
        self.assertEqual(live.diagnostic_environment({}), {})

    def test_actual_proc_environment_requires_absence(self):
        live.configure_cell(cell())
        for suffix in (b'', b'OMEGA_NATIVE_DIAG=v1\0', b'OMEGA_NATIVE_DIAG=\0', b'OMEGA_NATIVE_DIAG=false\0'):
            with patch.object(pathlib.Path, 'read_bytes', return_value=b'OMEGA_MEASURE_DIR=/measure\0'+suffix):
                if suffix:
                    with self.assertRaises(RuntimeError): live.validate_diagnostic_runtime(123)
                else: self.assertEqual(live.validate_diagnostic_runtime(123), {})

    def test_ordinary_status_rejects_native_files_and_fields(self):
        live.configure_cell(cell())
        with tempfile.TemporaryDirectory() as tmp:
            d=pathlib.Path(tmp); p=d/'bots.ndjson'
            p.write_text(json.dumps(dict(utc_ns=1,bots=[dict(id=1,inputs=1)]))+'\n')
            self.assertTrue(live.validate_ordinary_measurement(d)['native_fields_absent'])
            p.write_text(json.dumps(dict(utc_ns=1,bots=[dict(id=1,native_diagnostic={})]))+'\n')
            with self.assertRaises(RuntimeError):live.validate_ordinary_measurement(d)
            p.write_text('{}\n');(d/'native-input-trace.bin').write_bytes(b'')
            with self.assertRaises(RuntimeError):live.validate_ordinary_measurement(d)

    def test_load_cell_uses_exact_ordinary_spec(self):
        proof={r:dict(path='/home/deploy/omega-'+NS, revision=reuse.REVISION,
                     sha256=reuse.GAME_SHA,bot_sha256=reuse.BOT_SHA,
                     native_build_origin='bots',game_artifact_mode='verified-existing-build-copy')
               for r in ('game','bots')}
        with patch.object(pathlib.Path,'exists',return_value=False), patch.object(pathlib.Path,'read_text',return_value=json.dumps(proof)):
            live.load_cell(NS,150,'movement')
            self.assertTrue(live.compact_ordinary())
            self.assertEqual(live.CELL,cell())
            with self.assertRaises(ValueError):live.load_cell(NS,150,'idle')

    def test_resource_check_is_additive_and_fails_without_staging(self):
        import native_diagnostic_storage as storage
        measurement=dict(free_bytes=storage.GUARD+100*1024**2,staging_bytes=16*1024**2,
                         same_device=True,real_directories=True)
        with tempfile.TemporaryDirectory() as tmp:
            output=pathlib.Path(tmp)/'budget.json'
            with self.assertRaises(RuntimeError):
                reuse.check(lambda role,command:json.dumps(measurement),16*1024**2,output)
            row=json.loads(output.read_text())
            self.assertFalse(row['passed'])
            self.assertEqual(row['combined_bytes'],sum(row['allowances'].values()))
            self.assertEqual(row['allowances']['margin'],32*1024**2)
            self.assertEqual(row['unchanged_guard_bytes'],8*1024**3)

    def test_reuse_identity_and_budget_dispatch(self):
        row=dict(revision=reuse.REVISION,path='/home/deploy/omega-'+reuse.REUSE_NAMESPACE,
                 sha256=reuse.GAME_SHA,bot_sha256=reuse.BOT_SHA,native_build_origin='bots')
        proof={r:copy.deepcopy(row) for r in ('game','bots')}
        reuse.validate_reuse(NS,reuse.REVISION,reuse.REUSE_NAMESPACE,proof)
        for k,v in dict(revision='0'*40,path='/tmp/wrong',sha256='0'*64,
                        bot_sha256='0'*64,native_build_origin='game').items():
            bad=copy.deepcopy(proof);bad['bots'][k]=v
            with self.assertRaises(ValueError):reuse.validate_reuse(NS,reuse.REVISION,reuse.REUSE_NAMESPACE,bad)
        live.configure_cell(cell()); self.assertTrue(live.compact_ordinary())
        # The controller's exact profile uses the same additive proof, before staging.
        import inspect
        source=inspect.getsource(live.controller)
        self.assertIn("or compact_ordinary():",source)
        self.assertIn("r4.check(ssh,16*1024**2,local/'storage-preflight.json')",source)
        self.assertIn('os.rename',live.recovery_script())
        ordinary=cell()|dict(namespace='clean-idle150-unrelated',evidence_profile=None,measurement_preservation='copy')
        live.configure_cell(ordinary);self.assertEqual(live.measurement_limit_bytes(),1024**3)


if __name__=='__main__':unittest.main()
