"""Admission and persistence boundaries exercised through the public planner/CLI seams."""
import json
import unittest
from unittest import mock

import admission
import do_session
import fixture_support as fx
import manifest
import search
import test_cli
from test_search import play


class SearchSafetyTests(unittest.TestCase):
    def test_each_pending_confirmation_blocks_ordinary_and_resume_admission(self):
        frozen, sha = manifest.freeze_manifest(fx.conditions(), fx.preflight(), fx.FROZEN_AT)
        for completed in range(3):
            state = play([search.PASS, search.FAIL, search.FAIL] + [search.PASS] * completed,
                         condition=frozen['session']['id'])
            trial = search.next_trial(state)
            pending = search.dispatch(state, trial)
            for resume in (False, True):
                with self.subTest(repetition=trial.repetition, resume=resume):
                    result = admission.admit(frozen, sha, pending, fx.FROZEN_AT, fx.health(sha),
                                             resume_requested=resume)
                    self.assertFalse(result.admitted)
                    self.assertIsNone(result.next_run)
                    self.assertEqual(result.search['status'], 'awaiting_confirmation_outcome')

    def test_advancing_outcomes_require_nonempty_evidence_references(self):
        state = search.SearchState('c')
        trial = search.next_trial(state)
        pending = search.dispatch(state, trial)
        for outcome in search.ADVANCING:
            for ref in (None, '', '  ', 42, {}):
                with self.subTest(outcome=outcome, ref=ref):
                    with self.assertRaisesRegex(search.SearchError, 'evidence'):
                        search.record_outcome(pending, trial.run_id, outcome, ref)

    def test_legacy_evidenceless_pass_cannot_advance_or_confirm(self):
        for outcomes in ([search.PASS], [search.PASS, search.FAIL, search.FAIL, search.PASS]):
            state = play(outcomes)
            last = state.records[-1]
            state.records[-1] = search.TrialRecord(last.trial, last.outcome, None)
            with self.subTest(outcomes=outcomes):
                with self.assertRaisesRegex(search.SearchError, 'evidence'):
                    search.derive(state)


class AdmissionSafetyTests(unittest.TestCase):
    def test_hashed_legacy_manifests_with_unsupported_sections_are_rejected(self):
        for section in ('source', 'workload', 'limits', 'timing_basis', 'pricing'):
            for value in (None, [], 'invalid'):
                with self.subTest(section=section, value=value):
                    frozen, _ = manifest.freeze_manifest(fx.conditions(), fx.preflight(), fx.FROZEN_AT)
                    frozen[section] = value
                    sha = manifest.manifest_sha256(frozen)
                    result = admission.admit(frozen, sha, search.SearchState(frozen['session']['id']),
                                             fx.FROZEN_AT, fx.health(sha))
                    self.assertEqual(result.decision, admission.REJECTED)
                    self.assertIsNone(result.next_run)
                    self.assertEqual(result.time, {})

    def test_provisioning_requires_t0_and_preserves_elapsed_and_setup(self):
        frozen, sha = manifest.freeze_manifest(fx.conditions(), fx.preflight(), fx.FROZEN_AT)
        state = search.SearchState(frozen['session']['id'])
        result = admission.admit(frozen, sha, state, fx.FROZEN_AT, fx.health(sha), phase='provisioning')
        self.assertEqual(result.decision, admission.REJECTED)
        result = admission.admit(frozen, sha, state, '2026-10-30T12:01:00Z', fx.health(sha),
                                 phase='provisioning', t0=fx.FROZEN_AT)
        self.assertTrue(result.admitted)
        self.assertEqual(result.time['elapsed_s'], 60)
        self.assertEqual(sum(result.time['pre_workload_terms'].values()), 1080)

    def test_pre_create_cannot_reset_an_existing_t0(self):
        frozen, sha = manifest.freeze_manifest(fx.conditions(), fx.preflight(), fx.FROZEN_AT)
        result = admission.admit(frozen, sha, search.SearchState(frozen['session']['id']),
                                 fx.FROZEN_AT, fx.health(sha), t0=fx.FROZEN_AT)
        self.assertEqual(result.decision, admission.REJECTED)
        self.assertIsNone(result.next_run)


class ManifestSafetyTests(test_cli.CliFixture):
    def assert_freeze_rejected_without_files(self, conditions):
        self.conditions.write_text(json.dumps(conditions))
        before = self.snapshot()
        code, out, err = self.run_cli('freeze', '--conditions', str(self.conditions), '--preflight',
                                      str(self.preflight), '--session-root', str(self.session_root),
                                      '--now', fx.FROZEN_AT)
        self.assertEqual(code, 2, (out, err))
        self.assertFalse(json.loads(out)['frozen'])
        self.assertEqual(self.snapshot(), before)
        return json.loads(out)['reasons']

    def test_required_sections_reject_non_objects(self):
        for section in ('source', 'workload', 'limits', 'timing_basis', 'pricing'):
            for value in (None, [], 'invalid', 42):
                with self.subTest(section=section, value=value):
                    conditions = fx.conditions()
                    conditions[section] = value
                    reasons = self.assert_freeze_rejected_without_files(conditions)
                    self.assertTrue(any(section in reason and 'object' in reason for reason in reasons))

    def test_development_profile_is_rejected(self):
        conditions = fx.conditions()
        conditions['source']['profile'] = 'dev'
        self.assert_freeze_rejected_without_files(conditions)

    def test_toolchain_aliases_are_rejected(self):
        for toolchain in ('stable', 'beta', 'nightly', '1.91'):
            with self.subTest(toolchain=toolchain):
                conditions = fx.conditions()
                conditions['source']['rust_toolchain'] = toolchain
                self.assert_freeze_rejected_without_files(conditions)

    def test_extra_literal_credential_rejects_without_echoing_value(self):
        conditions = fx.conditions()
        literal = 'synthetic-plain-password-for-review'
        conditions['credentials']['ssh_passphrase'] = literal
        reasons = self.assert_freeze_rejected_without_files(conditions)
        self.assertNotIn(literal, json.dumps(reasons))

    def test_versioned_toolchain_with_explicit_host_triple_is_accepted(self):
        conditions = fx.conditions()
        conditions['source']['rust_toolchain'] = '1.91.0-x86_64-unknown-linux-gnu'
        frozen, sha = manifest.freeze_manifest(conditions, fx.preflight(), fx.FROZEN_AT)
        self.assertEqual(manifest.verify_manifest(frozen, sha), sha)


class CliSafetyTests(test_cli.CliFixture):
    def select(self, now=fx.FROZEN_AT, resume=False):
        args = ['next-run', '--session-dir', str(self.session_dir), '--now', now,
                '--infra-health', str(self.health)]
        if resume:
            args.append('--resume')
        return self.run_cli(*args)

    def test_mark_t0_keeps_setup_charged_until_verified_ready(self):
        conditions = fx.conditions()
        conditions['limits']['max_session_duration_s'] = 8000
        self.conditions.write_text(json.dumps(conditions))
        self.freeze()
        args = ('admit', '--session-dir', str(self.session_dir), '--infra-health', str(self.health),
                '--now', fx.FROZEN_AT)
        code, before, _ = self.run_cli(*args)
        self.assertEqual(code, 2)
        self.assertEqual(self.run_cli('mark-t0', '--session-dir', str(self.session_dir),
                                      '--now', fx.FROZEN_AT)[0], 0)
        code, after, _ = self.run_cli(*args)
        self.assertEqual(code, 2)
        before, after = json.loads(before), json.loads(after)
        self.assertEqual(after['time']['phase'], 'provisioning')
        self.assertEqual(after['time']['required_before_c_s'], before['time']['required_before_c_s'])
        self.assertEqual(after['time']['pre_workload_terms'], before['time']['pre_workload_terms'])

    def test_verified_ready_transition_preserves_original_clock(self):
        self.freeze()
        self.run_cli('mark-t0', '--session-dir', str(self.session_dir), '--now', fx.FROZEN_AT)
        code, _, err = self.run_cli('mark-ready', '--session-dir', str(self.session_dir),
                                     '--now', '2026-10-30T12:18:00Z', '--evidence-ref', 'ref:pair-readiness')
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli('admit', '--session-dir', str(self.session_dir),
                                    '--infra-health', str(self.health), '--now', '2026-10-30T12:20:00Z')
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result['time']['elapsed_s'], 1200)
        self.assertEqual(result['time']['pre_workload_terms'], {})
        self.assertEqual(result['time']['phase'], 'pair_ready')
        code, _, err = self.run_cli('admit', '--session-dir', str(self.session_dir),
                                     '--infra-health', str(self.health), '--now', '2026-10-30T12:17:59Z')
        self.assertEqual(code, 2)
        self.assertIn('readiness', err)
        self.assertEqual(self.run_cli('mark-ready', '--session-dir', str(self.session_dir),
                                      '--now', '2026-10-30T12:20:00Z', '--evidence-ref', 'ref:new-ready')[0], 2)

    def test_ready_requires_t0_chronology_and_nonempty_evidence(self):
        self.freeze()
        args = ('mark-ready', '--session-dir', str(self.session_dir))
        self.assertEqual(self.run_cli(*args, '--now', fx.FROZEN_AT, '--evidence-ref', 'ref:ready')[0], 2)
        self.run_cli('mark-t0', '--session-dir', str(self.session_dir), '--now', fx.FROZEN_AT)
        self.assertEqual(self.run_cli(*args, '--now', '2026-10-30T11:59:59Z',
                                      '--evidence-ref', 'ref:ready')[0], 2)
        self.assertEqual(self.run_cli(*args, '--now', fx.FROZEN_AT, '--evidence-ref', ' ')[0], 2)
        self.assertEqual(do_session.load_session(self.session_dir)[3]['phase'], 'provisioning')

    def test_pass_without_evidence_does_not_change_journal(self):
        self.freeze()
        _, out, _ = self.select()
        run_id = json.loads(out)['selected']['trial']['run_id']
        journal = self.session_dir / do_session.JOURNAL
        before = journal.read_bytes()
        code, _, err = self.run_cli('record', '--session-dir', str(self.session_dir), '--run-id', run_id,
                                     '--outcome', 'PASS', '--now', fx.FROZEN_AT)
        self.assertEqual(code, 2, err)
        self.assertEqual(journal.read_bytes(), before)

    def test_legacy_evidenceless_outcome_blocks_replayed_selection(self):
        self.freeze()
        _, out, _ = self.select()
        run_id = json.loads(out)['selected']['trial']['run_id']
        do_session.append_journal(self.session_dir, dict(kind='outcome', manifest_sha256=self.sha,
                                                       run_id=run_id, outcome='PASS', evidence_ref=None))
        code, _, err = self.select()
        self.assertEqual(code, 2)
        self.assertIn('evidence', err)
        self.assertEqual(len(list((self.session_dir / 'runs').iterdir())), 1)

    def orphan_selection(self):
        with mock.patch.object(do_session, 'append_journal', side_effect=OSError('synthetic journal failure')):
            code, _, err = self.select()
        self.assertEqual(code, 2, err)
        path, = (self.session_dir / 'runs').glob('*/selected.json')
        self.assertEqual(len(do_session.load_session(self.session_dir)[2].records), 0)
        return path

    def test_append_failure_recovers_exact_selection_once_without_overwriting(self):
        self.freeze()
        path = self.orphan_selection()
        original = path.read_bytes()
        code, out, err = self.select(now='2026-10-30T12:00:01Z', resume=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['selected'], json.loads(original))
        self.assertEqual(path.read_bytes(), original)
        journal = [json.loads(line) for line in (self.session_dir / do_session.JOURNAL).read_text().splitlines()]
        self.assertEqual(len([entry for entry in journal if entry['kind'] == 'selected']), 1)
        self.assertEqual(self.select()[0], 3, 'retry must not select the same run again')

    def test_orphan_recovery_does_not_bypass_current_admission(self):
        self.freeze()
        self.run_cli('mark-t0', '--session-dir', str(self.session_dir), '--now', fx.FROZEN_AT)
        path = self.orphan_selection()
        original = path.read_bytes()
        code, _, _ = self.select(now='2026-10-30T15:59:59Z')
        self.assertEqual(code, 2)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(do_session.load_session(self.session_dir)[2].records), 0)

    def test_mismatched_orphan_is_refused_and_preserved(self):
        self.freeze()
        path = self.orphan_selection()
        record = json.loads(path.read_text())
        record['trial']['target'] = 500
        path.write_text(json.dumps(record))
        original = path.read_bytes()
        code, _, _ = self.select()
        self.assertEqual(code, 2)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(do_session.load_session(self.session_dir)[2].records), 0)

    def test_calibration_and_smoke_cannot_select_capacity_trials(self):
        for kind in ('calibration', 'lifecycle_smoke'):
            with self.subTest(kind=kind):
                conditions = fx.conditions()
                conditions['session']['kind'] = kind
                # Keep separate namespaces so both cases exercise create-only freeze.
                self.session_root = self.root / kind
                self.conditions.write_text(json.dumps(conditions))
                self.freeze()
                code, out, _ = self.select()
                self.assertEqual(code, 2)
                self.assertIn('separate bounded workload plans', json.loads(out)['reasons'][0])
                self.assertFalse((self.session_dir / 'runs').exists())
                self.assertEqual(self.run_cli('paths', '--session-dir', str(self.session_dir))[0], 2)


if __name__ == '__main__':
    unittest.main()
