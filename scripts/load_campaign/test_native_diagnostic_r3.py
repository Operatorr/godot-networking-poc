"""R3-only resource boundary; ordinary and historical caps remain intact."""
import copy
import json
import pathlib
import shlex
import subprocess
import tempfile
import unittest
import native_diagnostic_r3 as r3
import native_diagnostic_storage as old
import clean_run_build as build

class R3Tests(unittest.TestCase):
    @unittest.skipUnless((pathlib.Path(__file__).resolve().parents[2]/'deployment/hetzner/results'/
                         (r3.NAMESPACE+'-build')/'native-transit/omega-load-test').is_file(),
                         'Manual real-artifact regression requires retained private R3 transit')
    def test_direct_elf_proof_uses_actual_new_native_binaries_without_file_utility(self):
        root=pathlib.Path(__file__).resolve().parents[2]
        transit=root/'deployment/hetzner/results'/ (r3.NAMESPACE+'-build')/'native-transit'
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

    def test_exact_r3_dispatch_preserves_historical_caps_and_rejects_old_bot(self):
        import clean_run as live
        cell=dict(namespace=r3.NAMESPACE,revision=r3.REVISION,population=150,behavior='idle',
                  game_sha256=r3.GAME_SHA,bot_sha256='56c2139ebf042680febccca48c2b5b3d036bce2eadc4ea385f6f52ae5812ed67',
                  native_diagnostic='v1',measurement_preservation='rename-v1')
        live.configure_cell(cell);self.assertEqual(live.measurement_limit_bytes(),32*1024**2)
        for change in (dict(revision=build.NATIVE_REVISION),dict(bot_sha256=build.NATIVE_HASHES[1]),
                       dict(game_sha256='0'*64),dict(measurement_preservation='copy'),
                       dict(namespace=r3.NAMESPACE+'-retry'),dict(population=100),dict(behavior='strategy')):
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
        self.assertEqual(value['combined_bytes'],186*1024**2)
        self.assertEqual(value['allowances']['live_game_payload'],32*1024**2)
        self.assertEqual(value['allowances']['role_only_archive'],58*1024**2)
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


class RealRecorderBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(all((pathlib.Path(__file__).resolve().parents[2]/'rust/target/debug'/name).is_file()
                             for name in ('omega-server','omega-load-test')),
                         'Real recorder regression requires built local CLI executables')
    def test_actual_cli_drained_row_does_not_replace_measurement_endpoints(self):
        import os,socket,time
        import clean_run_scoring as scoring
        root=pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            d=pathlib.Path(tmp);measure=d/'measure';measure.mkdir()
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            config=d/'config.json';config.write_text(json.dumps(dict(port=port,metrics_port=0,max_players=1,monster_spawn_rate=0)))
            env=dict(os.environ);env.pop('OMEGA_MEASURE_DIR',None);env.pop('OMEGA_NATIVE_DIAG',None)
            with (d/'server.log').open('wb') as log:
                server=subprocess.Popen([str(root/'rust/target/debug/omega-server'),'--config',str(config),'--allow-unsigned-tickets'],stdout=log,stderr=log,env=env)
                try:
                    time.sleep(.4)
                    env.update(OMEGA_MEASURE_DIR=str(measure),OMEGA_NATIVE_DIAG='v1')
                    env.pop('OMEGA_TICKET_API',None);env.pop('OMEGA_LOAD_TEST_SECRET',None)
                    result=subprocess.run([str(root/'rust/target/debug/omega-load-test'),'--server',f'127.0.0.1:{port}','--bots','1','--duration','1','--stagger','0','--behavior','idle','--no-report'],env=env,capture_output=True,timeout=12)
                    rows=[json.loads(line) for line in (measure/'bots.ndjson').read_text().splitlines()]
                    self.assertEqual(rows[-1]['boundary'],'drained')
                    self.assertEqual(rows[-1]['bots'][0]['phase'],'Closed')
                    self.assertGreater(rows[-1]['bots'][0]['inputs'],0)
                    self.assertEqual(set(scoring.measurement_boundaries(rows)),{'end'})
                    self.assertEqual(scoring.measurement_boundaries(rows)['end']['boundary'],'end')
                finally:
                    server.terminate();server.wait(timeout=5)

if __name__=='__main__':unittest.main()
