"""Preservation audits refuse overwrites and retain exact bounded-command failures."""
import json
import pathlib
import subprocess
import tempfile
import types
import unittest
from unittest import mock

import clean_run_audit as audit


class AuditTests(unittest.TestCase):
    def test_unique_audits_and_existing_partial_output_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            first=audit.audit_paths(root,'independent')
            self.assertEqual(first['summary'].name,'independent-prebuild-preservation-audit.json')
            first['commands'].write_bytes(b'first partial audit')
            with self.assertRaises(FileExistsError):audit.audit_paths(root,'independent')
            self.assertTrue(set(first.values()).isdisjoint(audit.audit_paths(root,'recheck').values()))
            self.assertEqual(first['commands'].read_bytes(),b'first partial audit')
            with self.assertRaises(ValueError):audit.audit_paths(root,'../escape')

    def test_failed_step_and_timeout_keep_exact_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=pathlib.Path(tmp)/'commands.ndjson'
            result=types.SimpleNamespace(returncode=7,stdout='partial stdout',stderr='exact failure')
            with mock.patch.object(audit.subprocess,'run',return_value=result) as call:
                with self.assertRaises(RuntimeError):audit.bounded_ssh('game','read-only check',journal)
                self.assertEqual(call.call_args.kwargs['timeout'],90)
            timeout=subprocess.TimeoutExpired('ssh',90,output=b'timeout stdout',stderr=b'timeout stderr')
            with mock.patch.object(audit.subprocess,'run',side_effect=timeout):
                with self.assertRaises(RuntimeError):audit.bounded_ssh('bots','bounded check',journal)
            rows=[json.loads(row) for row in journal.read_text().splitlines()]
            self.assertEqual(rows[0]['command'],'read-only check')
            self.assertEqual(rows[0]['returncode'],7)
            self.assertEqual(rows[0]['stderr'],'exact failure')
            self.assertEqual(rows[1]['timeout_s'],90)
            self.assertEqual(rows[1]['stdout'],'timeout stdout')
            self.assertEqual(rows[1]['stderr'],'timeout stderr')


if __name__=='__main__':unittest.main()
