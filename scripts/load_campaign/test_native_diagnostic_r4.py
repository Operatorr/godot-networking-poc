"""R4-only resource boundary; ordinary and historical caps remain intact."""
import copy
import json
import pathlib
import shlex
import subprocess
import tempfile
import unittest
import native_diagnostic_r4 as r3
import native_diagnostic_storage as old
import clean_run_build as build

class R4Tests(unittest.TestCase):
    @unittest.skipUnless((pathlib.Path(__file__).resolve().parents[2]/'deployment/hetzner/results'/
                         (r3.REUSE_NAMESPACE+'-build')/'native-transit/omega-load-test').is_file(),
                         'Manual real-artifact regression requires retained private R3 transit')
    def test_direct_elf_proof_uses_actual_new_native_binaries_without_file_utility(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        transit=root/'deployment/hetzner/results'/ (r3.REUSE_NAMESPACE+'-build')/'native-transit'
        paths=[str(transit/name) for name in ('omega-server','omega-load-test')]
        result=subprocess.run(shlex.split(r3.elf_identity_command(paths)),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        proof=json.loads(result.stdout)
        self.assertEqual(len(proof),2)
        self.assertTrue(all(v['machine']=='AArch64' and v['links']==1 for v in proof.values()))
        with tempfile.TemporaryDirectory() as tmp:
            import os
            linked=pathlib.Path(tmp)/'native';linked.write_bytes(pathlib.Path(paths[0]).read_bytes())
            os.link(linked,pathlib.Path(tmp)/'cargo-object')
            self.assertNotEqual(subprocess.run(shlex.split(r3.elf_identity_command([str(linked)])),capture_output=True).returncode,0)
            native=subprocess.run(shlex.split(r3.elf_identity_command([str(linked)],native_cargo_artifact=True)),capture_output=True,text=True)
            self.assertEqual(native.returncode,0,native.stderr)
            self.assertEqual(json.loads(native.stdout)[str(linked)]['links'],2)
            bad=pathlib.Path(tmp)/'bad';bad.write_bytes(b'not-elf')
            self.assertNotEqual(subprocess.run(shlex.split(r3.elf_identity_command([str(bad)])),capture_output=True).returncode,0)

    def test_exact_r4_dispatch_preserves_historical_caps_and_rejects_old_bot(self):
        import clean_run as live
        cell=dict(namespace=r3.NAMESPACE,revision=r3.REVISION,population=150,behavior='idle',
                  game_sha256=r3.GAME_SHA,bot_sha256='56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67',
                  native_diagnostic='v1',measurement_preservation='rename-v1',native_build_origin='bots',game_artifact_mode='verified-existing-build-copy')
        live.configure_cell(cell);self.assertEqual(live.measurement_limit_bytes(),16*1024**2)
        for change in (dict(revision=build.NATIVE_REVISION),dict(bot_sha256=build.NATIVE_HASHES[1]),
                       dict(game_sha256='0'*64),dict(measurement_preservation='copy'),
                       dict(native_build_origin='game'),dict(game_artifact_mode='native-build'),dict(namespace=r3.NAMESPACE+'-retry'),dict(population=100),dict(behavior='strategy')):
            with self.assertRaises(ValueError):live.configure_cell(cell|change)
        oldcell=cell|dict(namespace=build.NATIVE_R2,revision=build.NATIVE_REVISION,
                         bot_sha256=build.NATIVE_HASHES[1],measurement_preservation='copy')
        live.configure_cell(oldcell);self.assertEqual(live.measurement_limit_bytes(),96*1024**2)
        live.configure_cell({k:v for k,v in oldcell.items() if k!='native_diagnostic'})
        self.assertEqual(live.measurement_limit_bytes(),1024**3)

    def test_additive_budget_requires_real_same_device_before_zero_copy(self):
        measurement=dict(free_bytes=old.GUARD+240*1024**2,staging_bytes=40*1024**2,same_device=True,real_directories=True)
        value=r3.budget(measurement)
        self.assertEqual(value['allowances']['original_measurement_additional_payload'],0)
        self.assertEqual(value['combined_bytes'],154*1024**2)
        self.assertEqual(value['allowances']['live_game_payload'],16*1024**2)
        self.assertEqual(value['allowances']['role_only_archive'],42*1024**2)
        self.assertTrue(value['passed'])
        self.assertFalse(r3.budget(measurement|dict(free_bytes=old.GUARD+value['combined_bytes']-1))['passed'])
        for key in ('same_device','real_directories'):
            with self.assertRaises(ValueError):r3.budget(measurement|{key:False})
        for val in (0,-1,True,1.2):
            with self.assertRaises(ValueError):r3.budget(measurement|dict(staging_bytes=val))
        self.assertEqual(old.LIVE,96*1024**2);self.assertEqual(old.ARCHIVE,122*1024**2)

    def test_actual_probe_hashes_inodes_and_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp).resolve();current=root/'measure/current';current.mkdir(parents=True)
            (current/'data').write_text('preserve')
            dst=root/'results';dst.mkdir();binary=root/'binary';binary.write_bytes(b'123')
            cmd=r3.rename_probe_command(12345).replace('/var/lib/omega-measure/current',str(current)).replace('/home/deploy/omega-results',str(dst)).replace('/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server',str(binary))
            p=subprocess.run(shlex.split(cmd),capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);row=json.loads(p.stdout)
            self.assertEqual(row['measurement']['inode'],current.stat().st_ino)
            self.assertEqual(row['measurement']['files']['data']['inode'],(current/'data').stat().st_ino)
            self.assertEqual(row['staging_bytes'],12345+4096)
            (current/'link').symlink_to(current/'data')
            self.assertNotEqual(subprocess.run(shlex.split(cmd),capture_output=True).returncode,0)


    def test_exact_reuse_rejects_wrong_source_hash_path_and_origin(self):
        import copy
        row=dict(revision=r3.REVISION,path='/home/deploy/omega-'+r3.REUSE_NAMESPACE,
                 sha256=r3.GAME_SHA,bot_sha256=r3.BOT_SHA,native_build_origin='bots')
        proof={role:copy.deepcopy(row) for role in ('game','bots')}
        r3.validate_reuse(r3.NAMESPACE,r3.REVISION,r3.REUSE_NAMESPACE,proof)
        for role in proof:
            for key,value in dict(revision='0'*40,path='/tmp/other',sha256='0'*64,
                                  bot_sha256=build.NATIVE_HASHES[1],native_build_origin='game').items():
                bad=copy.deepcopy(proof);bad[role][key]=value
                with self.assertRaises(ValueError):r3.validate_reuse(r3.NAMESPACE,r3.REVISION,r3.REUSE_NAMESPACE,bad)
        for args in [(r3.NAMESPACE+'-retry',r3.REVISION,r3.REUSE_NAMESPACE),
                     (r3.NAMESPACE,build.NATIVE_REVISION,r3.REUSE_NAMESPACE),
                     (r3.NAMESPACE,r3.REVISION,'clean-idle150-audit-r2-20261023')]:
            with self.assertRaises(ValueError):r3.validate_reuse(*args,proof)


    def test_exact_r5_dispatch_and_reuse_preserve_r4(self):
        import clean_run as live
        ns='clean-idle150-audit-r5-20261023'
        cell=dict(namespace=ns,revision=r3.REVISION,population=150,behavior='idle',
                  game_sha256=r3.GAME_SHA,bot_sha256=r3.BOT_SHA,native_diagnostic='v1',
                  measurement_preservation='rename-v1',native_build_origin='bots',
                  game_artifact_mode='verified-existing-build-copy')
        live.configure_cell(cell)
        self.assertEqual(live.measurement_limit_bytes(),16*1024**2)
        row=dict(revision=r3.REVISION,path='/home/deploy/omega-'+r3.REUSE_NAMESPACE,
                 sha256=r3.GAME_SHA,bot_sha256=r3.BOT_SHA,native_build_origin='bots')
        proof={role:copy.deepcopy(row) for role in ('game','bots')}
        r3.validate_reuse(ns,r3.REVISION,r3.REUSE_NAMESPACE,proof)
        for change in (dict(namespace=ns+'-retry'),dict(revision='0'*40),
                       dict(bot_sha256=build.NATIVE_HASHES[1]),dict(game_sha256='0'*64),
                       dict(population=100),dict(behavior='strategy'),
                       dict(measurement_preservation='copy'),dict(native_build_origin='game'),
                       dict(game_artifact_mode='native-build')):
            with self.assertRaises(ValueError):live.configure_cell(cell|change)
        with self.assertRaises(ValueError):r3.validate_reuse(ns+'-retry',r3.REVISION,r3.REUSE_NAMESPACE,proof)
        for role in proof:
            for key,value in dict(revision='0'*40,path='/tmp/wrong',sha256='0'*64,
                                  bot_sha256=build.NATIVE_HASHES[1],native_build_origin='game').items():
                bad=copy.deepcopy(proof);bad[role][key]=value
                with self.assertRaises(ValueError):r3.validate_reuse(ns,r3.REVISION,r3.REUSE_NAMESPACE,bad)
        live.configure_cell(cell|dict(namespace=r3.NAMESPACE))
        self.assertEqual(live.measurement_limit_bytes(),16*1024**2)


    def test_idle_current_directory_probe_executes_and_checks_inode_and_prefix(self):
        import hashlib
        import native_diagnostic_r4_audit as release
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp).resolve();data=root/'data';data.write_bytes(b'preserved')
            st=root.stat();fs=data.stat()
            import stat
            proof=dict(device=st.st_dev,inode=st.st_ino,uid=st.st_uid,gid=st.st_gid,
                       mode=stat.S_IMODE(st.st_mode),files=dict(data=dict(bytes=9,
                       sha256=hashlib.sha256(b'preserved').hexdigest(),inode=fs.st_ino,device=fs.st_dev)))
            command=release.current_measurement_command(proof).removeprefix('sudo -n ').replace('/var/lib/omega-measure/current',str(root))
            result=subprocess.run(shlex.split(command),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(json.loads(result.stdout)['original_current_directory_untouched'])
            data.write_bytes(b'changed')
            self.assertNotEqual(subprocess.run(shlex.split(command),capture_output=True).returncode,0)


if __name__=='__main__':unittest.main()
