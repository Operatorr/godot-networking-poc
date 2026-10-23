"""Verify actual archived bytes and the real bounded audit command, without extraction."""
import copy
import io
import json
import pathlib
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import clean_run_audit as audit
import closed_measurement_archive as archive


class ClosedMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.original = self.root/'clean-fixture'/'original'
        self.loose = self.original/'measurement-current'
        self.loose.mkdir(parents=True)
        (self.loose/'server.ndjson').write_bytes(b'original evidence\n')
        (self.original/'measurement-verified').touch()
        (self.original/'measurement-sha256.txt').write_text(
            archive.digest(self.loose/'server.ndjson')+'  ./server.ndjson\n')

    def compact(self):
        inventory = archive.inventory(self.loose)
        target = self.original/archive.ARCHIVE
        with tarfile.open(target, 'w:gz') as stream:
            stream.add(self.loose, arcname='measurement-current')
        proof = dict(schema=archive.SCHEMA, namespace='clean-fixture', inventory=inventory,
                     archive_sha256=archive.digest(target), archive_bytes=target.stat().st_size,
                     manifest_sha256=archive.digest(self.original/'measurement-sha256.txt'))
        archive.verify_archive(self.original, proof)
        shutil.rmtree(self.loose)
        self.write_proof(proof)
        return proof

    def write_proof(self, proof):
        (self.original/archive.PROOF).write_text(json.dumps(proof))

    def test_actual_audit_command_verifies_loose_and_archived_modes(self):
        self.assertTrue(archive.verify(self.original)['original_inodes_live'])
        proof = self.compact()
        row = archive.verify(self.original)
        self.assertFalse(row['original_inodes_live'])
        self.assertEqual(row['mode'], archive.SCHEMA)
        self.assertGreater(proof['inventory']['files']['server.ndjson']['inode'], 0)
        parts = shlex.split(audit.measurement_backups_command(self.root))
        self.assertEqual(parts[:3], ['sudo', '-n', 'python3'])
        result = subprocess.run([sys.executable, *parts[3:]], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {'clean-fixture': row})

    def test_changed_loose_bytes_fail_frozen_manifest(self):
        (self.loose/'server.ndjson').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'frozen manifest'):
            archive.verify(self.original)

    def test_corrupt_archive_and_changed_manifest_fail(self):
        proof = self.compact()
        target = self.original/archive.ARCHIVE
        original = target.read_bytes()
        target.write_bytes(original+b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Archive identity'):
            archive.verify(self.original)
        target.write_bytes(original)
        (self.original/'measurement-sha256.txt').write_text('0'*64+'  ./server.ndjson\n')
        with self.assertRaisesRegex(ValueError, 'Frozen manifest'):
            archive.verify(self.original)
        proof['manifest_sha256'] = archive.digest(self.original/'measurement-sha256.txt')
        self.write_proof(proof)
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            archive.verify(self.original)

    def test_links_traversal_duplicate_missing_extra_and_changed_members_fail(self):
        proof = self.compact()
        root_info = tarfile.TarInfo('measurement-current')
        root_info.type = tarfile.DIRTYPE
        directory = proof['inventory']['directories']['.']
        root_info.uid, root_info.gid, root_info.mode = directory['uid'], directory['gid'], directory['mode']
        file_info = tarfile.TarInfo('measurement-current/server.ndjson')
        row = proof['inventory']['files']['server.ndjson']
        file_info.uid, file_info.gid, file_info.mode = row['uid'], row['gid'], row['mode']
        data = b'original evidence\n'
        file_info.size = len(data)
        for case in ('symlink', 'hardlink', 'traversal', 'duplicate', 'missing', 'extra', 'bytes', 'mode'):
            with self.subTest(case=case):
                member = copy.copy(file_info)
                if case == 'symlink':
                    member.type, member.linkname, member.size = tarfile.SYMTYPE, '/tmp/outside', 0
                elif case == 'hardlink':
                    member.type, member.linkname, member.size = tarfile.LNKTYPE, 'measurement-current/server.ndjson', 0
                elif case == 'traversal':
                    member.name = 'measurement-current/../outside'
                elif case == 'mode':
                    member.mode ^= 0o100
                target = self.original/archive.ARCHIVE
                with tarfile.open(target, 'w:gz') as stream:
                    stream.addfile(root_info)
                    if case != 'missing':
                        payload = b'x'*len(data) if case == 'bytes' else data
                        stream.addfile(member, io.BytesIO(payload) if member.isfile() else None)
                    if case == 'duplicate':
                        stream.addfile(file_info, io.BytesIO(data))
                    if case == 'extra':
                        extra = copy.copy(file_info)
                        extra.name = 'measurement-current/extra'
                        stream.addfile(extra, io.BytesIO(data))
                changed = proof | dict(archive_sha256=archive.digest(target), archive_bytes=target.stat().st_size)
                self.write_proof(changed)
                with self.assertRaises(ValueError):
                    archive.verify(self.original)

    def test_missing_proof_or_ambiguous_representation_fails(self):
        self.compact()
        self.loose.mkdir()
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            archive.verify(self.original)
        self.loose.rmdir()
        (self.original/archive.PROOF).unlink()
        with self.assertRaisesRegex(ValueError, 'lacks explicit proof'):
            archive.verify(self.original)

    def test_missing_marked_backup_is_not_skipped(self):
        shutil.rmtree(self.loose)
        with self.assertRaises(ValueError):
            archive.verify_all(self.root)

    def test_loose_symlink_is_rejected(self):
        target = self.loose/'server.ndjson'
        target.unlink()
        target.symlink_to(self.original/'measurement-sha256.txt')
        with self.assertRaisesRegex(ValueError, 'Linked'):
            archive.verify(self.original)
