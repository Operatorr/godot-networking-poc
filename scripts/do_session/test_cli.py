"""End-to-end offline CLI: freeze, admit, select, record and resume with create-only files."""
import contextlib
import io
import json
import os
import pathlib
import tempfile
import unittest

import do_session
import fixture_support as fx

NOW = '2026-10-30T12:00:00+00:00'


class CliFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.conditions = self.root / 'conditions.json'
        self.conditions.write_text(json.dumps(fx.conditions()))
        self.preflight = self.root / 'preflight.json'
        self.preflight.write_text(json.dumps(fx.preflight()))
        self.session_root = self.root / 'sessions'

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = do_session.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def freeze(self):
        code, out, err = self.run_cli('freeze', '--conditions', str(self.conditions), '--preflight',
                                      str(self.preflight), '--session-root', str(self.session_root), '--now', NOW)
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.session_dir = pathlib.Path(result['session_dir'])
        self.sha = result['manifest_sha256']
        self.health = self.root / 'health.json'
        self.health.write_text(json.dumps(fx.health(self.sha)))
        return result

    def snapshot(self):
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file())


class FreezeCliTests(CliFixture):
    def test_freeze_writes_manifest_and_hash_once(self):
        self.freeze()
        self.assertTrue((self.session_dir / 'manifest.json').exists())
        self.assertEqual((self.session_dir / 'manifest.sha256').read_text().split()[0], self.sha)
        code, _, err = self.run_cli('freeze', '--conditions', str(self.conditions), '--preflight',
                                    str(self.preflight), '--session-root', str(self.session_root), '--now', NOW)
        self.assertEqual(code, 2, 'an existing manifest is immutable')
        self.assertIn('error', err)

    def test_rejected_freeze_creates_nothing(self):
        conditions = fx.conditions()
        del conditions['limits']['max_estimated_session_usd']
        self.conditions.write_text(json.dumps(conditions))
        before = self.snapshot()
        code, out, _ = self.run_cli('freeze', '--conditions', str(self.conditions), '--preflight',
                                    str(self.preflight), '--session-root', str(self.session_root), '--now', NOW)
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)['frozen'])
        self.assertEqual(self.snapshot(), before)


class AdmitAndSelectTests(CliFixture):
    def test_admit_next_run_record_cycle(self):
        self.freeze()
        code, out, _ = self.run_cli('admit', '--session-dir', str(self.session_dir), '--now', NOW,
                                    '--infra-health', str(self.health))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['decision'], 'admitted')
        self.assertEqual(len(list((self.session_dir / 'admissions').iterdir())), 1)

        code, out, _ = self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now', NOW,
                                    '--infra-health', str(self.health))
        self.assertEqual(code, 0)
        selected = json.loads(out)['selected']
        run_id = selected['trial']['run_id']
        self.assertTrue(run_id.endswith('-t01-coarse-n025-r1'))
        self.assertTrue((self.session_dir / 'runs' / run_id / 'selected.json').exists())
        journal = (self.session_dir / 'search_journal.ndjson').read_text().splitlines()
        self.assertEqual(json.loads(journal[-1])['kind'], 'selected')

        # Selecting again without an outcome is refused: the predecessor is incomplete.
        code, out, _ = self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now', NOW,
                                    '--infra-health', str(self.health))
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)['search']['status'], 'undecidable_incomplete_predecessor')

        code, out, _ = self.run_cli('record', '--session-dir', str(self.session_dir), '--run-id', run_id,
                                    '--outcome', 'PASS', '--evidence-ref', 'runs/' + run_id + '/summary.json',
                                    '--now', NOW)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['status'], 'in_progress')
        code, _, err = self.run_cli('record', '--session-dir', str(self.session_dir), '--run-id', run_id,
                                    '--outcome', 'FAIL', '--now', NOW)
        self.assertEqual(code, 2, 'outcomes are final: ' + err)

        code, out, _ = self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now', NOW,
                                    '--infra-health', str(self.health))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['selected']['trial']['run_id'].endswith('-t02-coarse-n050-r1'))
        self.assertEqual(json.loads(out)['selected']['predecessor_evidence'][0]['outcome'], 'PASS')

    def test_rejected_admission_writes_only_the_explanation(self):
        conditions = fx.conditions()
        conditions['limits']['max_session_duration_s'] = 1800
        self.conditions.write_text(json.dumps(conditions))
        self.freeze()
        before = self.snapshot()
        code, out, _ = self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now', NOW,
                                    '--infra-health', str(self.health))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)['decision'], 'rejected')
        added = sorted(set(self.snapshot()) - set(before))
        self.assertEqual(len(added), 1)
        self.assertIn('admissions/', added[0])
        self.assertFalse((self.session_dir / 'runs').exists(), 'no run is materialized on rejection')

    def test_t0_resume_and_stop(self):
        self.freeze()
        code, out, _ = self.run_cli('mark-t0', '--session-dir', str(self.session_dir), '--now', NOW)
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli('mark-t0', '--session-dir', str(self.session_dir), '--now', '2026-10-30T12:30:00Z')
        self.assertEqual(code, 2, 't0 is immutable')
        code, out, _ = self.run_cli('admit', '--session-dir', str(self.session_dir), '--now',
                                    '2026-10-30T12:20:00Z', '--infra-health', str(self.health), '--resume')
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result['time']['phase'], 'pair_ready')
        self.assertEqual(result['time']['elapsed_s'], 1200)
        code, out, _ = self.run_cli('admit', '--session-dir', str(self.session_dir), '--now',
                                    '2026-10-30T15:30:00Z', '--infra-health', str(self.health), '--resume')
        self.assertEqual(code, 2, 'the original deadline admits no full remaining path this late')
        code, _, _ = self.run_cli('stop', '--session-dir', str(self.session_dir), '--reason', 'time_exhausted',
                                  '--now', '2026-10-30T15:31:00Z')
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now',
                                    '2026-10-30T15:32:00Z', '--infra-health', str(self.health))
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)['search']['status'], 'partial_time_exhausted')

    def test_tampered_manifest_blocks_every_command(self):
        self.freeze()
        manifest_path = self.session_dir / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['limits']['max_session_duration_s'] = 99999
        manifest_path.write_text(json.dumps(manifest))
        for argv in (('admit', '--session-dir', str(self.session_dir), '--now', NOW, '--infra-health', str(self.health)),
                     ('paths', '--session-dir', str(self.session_dir))):
            code, _, err = self.run_cli(*argv)
            self.assertEqual(code, 2, argv[0])
            self.assertIn('does not match recorded', err)

    def test_paths_reports_the_27_trial_39_minute_ceiling(self):
        self.freeze()
        code, out, _ = self.run_cli('paths', '--session-dir', str(self.session_dir))
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report['max_trials'], 27)
        self.assertEqual(report['max_scored_hold_min'], 39.0)
        self.assertEqual(report['legal_remaining_paths'], 401)

    def test_no_secret_values_in_any_written_file(self):
        self.freeze()
        self.run_cli('next-run', '--session-dir', str(self.session_dir), '--now', NOW, '--infra-health', str(self.health))
        import manifest as m
        for path in self.session_dir.rglob('*'):
            if path.is_file():
                self.assertEqual(m.scan_for_secrets(path.read_text()), [], str(path))


if __name__ == '__main__':
    unittest.main()
