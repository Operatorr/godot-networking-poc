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

if __name__=='__main__':unittest.main()
