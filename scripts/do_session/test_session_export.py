"""The session export through the real controller, registry, watchdog, prover and scorer, over a fake account and fake guests. Nothing ran, so no number here says anything about any host."""
import errno
import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import capacity_scorer as cs
import cleanup_provider
import evidence_publication as ep
import export_fixtures as ef
import guest_runner
import registry
import registry_client
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import search
import session_clock
import session_export as se
import session_report as sr


def sha(data):
    return hashlib.sha256(data).hexdigest()


def confirmed_session(case, **options):
    sim = ef.ExportSim(case, ef.enriched(ef.CONFIRMING), **options)
    return sim, sim.batch()


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(pathlib.Path(root).rglob('*')) if path.is_file()}


class WholeSession(unittest.TestCase):
    def test_a_confirmed_search_exports_complete_evidence_and_closes_clean_only_after_absence(self):
        sim, result = confirmed_session(self)
        self.assertEqual(result.status, run_executor.FINISHED)
        self.assertEqual(result.wrap_up_errors, [])
        status = sim.status_now()
        self.assertEqual(status['evidence']['status'], 'complete')
        self.assertTrue(status['evidence']['ref'].startswith('export/gen-0001/inventory.json#sha256:'))
        self.assertEqual(status['overall'], 'cleanup_not_verified', 'the evidence is complete and nothing here says the resources are gone')
        first = sim.document('gen-0001', 'session-report.json')
        self.assertEqual(first['results']['evidence']['status'], 'complete')
        self.assertTrue(first['results']['measurement']['claim']['confirmed'])
        self.assertFalse(first['results']['cleanup']['verified_absent'])
        self.assertEqual(first['economics']['session_estimate']['total_estimated_usd'], None, 'no lifetime is known until deletion is verified')
        kept = tree_bytes(sim.generation('gen-0001'))

        self.assertEqual(sim.drive_cleanup()['overall'], 'clean')
        self.assertEqual(sim.session_droplets(), [])
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual((later.generation, later.status), ('gen-0002', 'complete'))
        self.assertEqual(tree_bytes(sim.generation('gen-0001')), kept, 'nothing is ever replaced')
        report = sim.document('gen-0002', 'session-report.json')
        cleanup = report['results']['cleanup']
        self.assertTrue(cleanup['verified_absent'])
        self.assertEqual(cleanup['overall'], 'clean')
        self.assertTrue(all(item['verified_absent_at'] for item in cleanup['resources']))
        self.assertEqual(cleanup['unresolved_creates'], 0)
        self.assertIsNotNone(report['economics']['session_estimate']['lifetime_s'])

    def test_a_requested_cleanup_and_an_accepted_delete_are_not_verified_absence(self):
        sim, _ = confirmed_session(self)
        self.assertTrue(sim.status_now()['cleanup']['requested_at'])
        sim.stack.watchdog.tick()     # deletes are accepted, and the droplets are not yet shown absent
        self.assertNotEqual(sim.status_now()['state'], registry.CLOSED)
        later = se.export_session(sim.root, client=sim.client)
        cleanup = sim.document(later.generation, se.REPORT_JSON)['results']['cleanup']
        self.assertFalse(cleanup['verified_absent'])
        self.assertIsNone(cleanup['verified_at'])
        self.assertIn('not proof of destruction', cleanup['statement'])
        self.assertIsNone(sim.document(later.generation, se.REPORT_JSON)['economics']['session_estimate']['total_estimated_usd'])
        self.assertFalse(sim.document(later.generation, 'published/summary.json')['results']['cleanup']['verified_absent'])

    def test_every_recovery_free_trial_keeps_its_own_summary_and_report(self):
        sim, _ = confirmed_session(self)
        rows = sim.records()
        self.assertEqual(len(rows), 7)
        for row in rows:
            summary = json.loads((sim.run_dir(row['run_id']) / 'summary.json').read_text())
            self.assertEqual(summary['provider'], 'DigitalOcean')
            self.assertEqual(summary['outcome'], row['outcome'])
            self.assertIn('Outcome **%s**' % row['outcome'], (sim.run_dir(row['run_id']) / 'REPORT.md').read_text())
            self.assertEqual(sorted(summary['evidence_roles']), ['bot', 'game'])

    def test_game_and_bot_evidence_and_the_sessions_own_records_are_all_inventoried(self):
        sim, _ = confirmed_session(self)
        inventory = sim.document('gen-0001')
        paths = {item['path']: item for item in inventory['files']}
        for required in ('manifest.json', 'manifest.sha256', 'search_journal.ndjson', 'provisioning/journal.ndjson', 'provisioning/readiness.json', 'execution/journal.ndjson'):
            self.assertIn(required, paths)
        self.assertGreater(inventory['admissions'], 0)
        run_id = sim.records()[0]['run_id']
        for name in ('game/telemetry/ticks.csv', 'game/sampler.ndjson', 'game/sockets.ndjson', 'bot/swarm/shard-0.ndjson', 'bot/swarm/window.json', 'bot/sampler.ndjson', 'window-proof.json', 'score.json', 'classification.json', 'grant.json', 'clock-before.json', 'summary.json', 'REPORT.md'):
            self.assertIn('runs/%s/%s' % (run_id, name), paths)
        self.assertEqual(paths['execution/journal.ndjson']['kind'], 'append_only')
        sums = (sim.generation('gen-0001') / se.SUMS_FILE).read_text().splitlines()
        self.assertEqual(len(sums), inventory['file_count'])
        for line in sums:
            digest, path = line.split('  ', 1)
            self.assertEqual(paths[path]['sha256'], digest)

    def test_verify_holds_every_hash_to_the_disk_and_a_journal_may_only_grow(self):
        sim, _ = confirmed_session(self)
        self.assertEqual(se.verify(sim.root, 'gen-0001'), [])
        journal = sim.root / 'execution' / 'journal.ndjson'
        with journal.open('a') as handle:
            handle.write('{"grown": true}\n')
        self.assertEqual(se.verify(sim.root, 'gen-0001'), [], 'an append-only journal may have grown')
        journal.write_text('{"rewritten": true}\n')
        self.assertTrue(any('execution/journal.ndjson' in item for item in se.verify(sim.root, 'gen-0001')))
        run_id = sim.records()[0]['run_id']
        path = sim.run_dir(run_id) / 'game' / 'telemetry' / 'ticks.csv'
        path.chmod(0o640)
        path.write_text('rewritten')
        self.assertTrue(any('ticks.csv' in item for item in se.verify(sim.root, 'gen-0001')))

    def test_a_capacity_failure_keeps_measurement_evidence_and_cleanup_apart(self):
        sim = ef.ExportSim(self, ef.enriched(default=sf.slow))
        result = sim.batch()
        self.assertEqual(result.search_status, 'no_passing_target')
        self.assertEqual(sim.status_now()['evidence']['status'], 'complete', 'a valid failure is complete evidence of a failure')
        sim.drive_cleanup()
        se.export_session(sim.root, client=sim.client)
        report = sim.document('gen-0002', 'session-report.json')
        self.assertEqual(report['results']['measurement']['claim']['kind'], 'no_passing_target_at_resolution')
        self.assertFalse(report['establishes'])
        self.assertEqual(report['results']['evidence']['status'], 'complete')
        self.assertEqual(report['results']['cleanup']['overall'], 'clean')
        self.assertIsNone(report['economics']['nominal_game_tier']['players_per_monthly_game_usd'])

    def test_invalid_offered_load_stops_and_reports_no_capacity(self):
        sim = ef.ExportSim(self, ef.enriched(default=sf.starved))
        result = sim.batch()
        self.assertEqual(sim.outcomes()[0][2], search.INVALID_LOAD)
        self.assertEqual(len(sim.outcomes()), 1, 'no successor past invalid load')
        report = sim.document('gen-0001', 'session-report.json')
        self.assertFalse(report['results']['measurement']['claim']['confirmed'])
        self.assertEqual(report['runs'][0]['offered_load'], 'invalid')
        self.assertTrue(sim.status_now()['cleanup']['requested_at'], result)

    def test_a_failed_confirmation_keeps_every_individual_outcome_with_no_replacement(self):
        sim = ef.ExportSim(self, ef.enriched({50: sf.slow, 35: sf.slow, ('confirm', 30): lambda tree: sf.slow(tree) if tree.trial['run_id'].endswith('r2') else None}))
        sim.batch()
        report = sim.document('gen-0001', 'session-report.json')
        confirmations = report['confirmations']['runs']
        self.assertEqual([item['outcome'] for item in confirmations][:2], [search.PASS, search.FAIL])
        self.assertEqual(report['results']['measurement']['claim']['kind'], 'unconfirmed_variable')
        self.assertEqual(report['economics']['nominal_game_tier']['confirmed_players'], None)
        self.assertLess(report['confirmations']['spread']['tick_p95_work_ns']['low'], report['confirmations']['spread']['tick_p95_work_ns']['high'])

    def test_a_run_interrupted_by_a_crash_reads_as_incomplete_in_every_report(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=rf.crash_at('after_running_commit')).execute()
        controller, _ = sim.controller()
        controller.collecting = True
        controller.prepare()
        controller.reconcile('operator_collect')
        result = run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='test', runs=controller.outcomes)
        controller.wrap_up(result)
        report = sim.document('gen-0001', 'session-report.json')
        self.assertEqual(report['runs'][0]['outcome'], search.INCOMPLETE)
        self.assertFalse(report['establishes'])
        self.assertNotEqual(report['results']['evidence']['status'], 'complete')


class ByteIdenticalReports(unittest.TestCase):
    def test_every_report_regenerates_exactly_even_from_another_directory(self):
        sim, _ = confirmed_session(self)
        self.assertEqual(se.reproduce(sim.root, 'gen-0001'), [])
        moved = pathlib.Path(tempfile.mkdtemp(prefix='omega-export-moved-'))
        self.addCleanup(shutil.rmtree, moved, True)
        target = moved / 'session'
        shutil.copytree(sim.root, target)
        self.addCleanup(rf.make_writable, moved)
        self.assertEqual(se.reproduce(target, 'gen-0001'), [])

    def test_a_changed_raw_file_is_seen_and_a_derived_file_is_never_taken_on_trust(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        path = sim.run_dir(run_id) / 'game' / 'telemetry' / 'ticks.csv'
        path.chmod(0o640)
        path.write_text(path.read_text().replace(',2000000,', ',2000001,'))
        self.assertIn(se.REPORT_JSON, se.reproduce(sim.root, 'gen-0001'))
        sim2, _ = confirmed_session(self)
        report = sim2.generation('gen-0001') / se.REPORT_MD
        report.write_text(report.read_text().replace('Confirmed 30', 'Confirmed 300'))
        self.assertEqual(se.reproduce(sim2.root, 'gen-0001'), [se.REPORT_MD])

    def test_a_changed_manifest_cannot_be_reported_on(self):
        sim, _ = confirmed_session(self)
        (sim.root / 'manifest.json').write_text('[]')
        self.assertEqual(se.reproduce(sim.root, 'gen-0001'), ['manifest.json'])
        (sim.root / 'manifest.json').write_text('{}')
        self.assertTrue(se.reproduce(sim.root, 'gen-0001')[0].startswith('the reports cannot be rebuilt'))

    def test_the_report_comes_from_retained_inputs_with_no_registry_and_no_clock(self):
        sim, _ = confirmed_session(self)
        sim.stack.registry.close()
        sim.client = None
        with mock.patch('time.time', side_effect=AssertionError('no clock')):
            self.assertEqual(se.reproduce(sim.root, 'gen-0001'), [])
        sim.stack.registry = sim.stack.open_registry()


class IncompleteEvidenceNeverPasses(unittest.TestCase):
    def assertNoClaim(self, sim, name='gen-0001'):
        report = sim.document(name, 'session-report.json')
        self.assertFalse(report['establishes'])
        self.assertFalse(report['results']['measurement']['claim']['confirmed'])
        self.assertIsNone(report['economics']['nominal_game_tier']['confirmed_players'])
        self.assertIsNone(report['economics']['nominal_game_tier']['players_per_monthly_game_usd'])
        return report

    def test_a_missing_required_file_withholds_the_claim_and_keeps_the_journals_word_apart(self):
        def drop(tree, trial):
            if trial['phase'] == 'confirm':
                tree.path('game/sockets.ndjson').unlink()
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=drop))
        sim.batch()
        self.assertEqual(sim.status_now()['evidence']['status'], 'partial')
        report = self.assertNoClaim(sim)
        self.assertEqual(report['results']['measurement']['search_status'], 'confirmed', 'what was recorded is not rewritten')
        self.assertIn('Confirmed 30', report['results']['measurement']['journal_claim_withheld']['statement'])
        rendered = (sim.generation('gen-0001') / se.REPORT_MD).read_text()
        self.assertIn('No claim stands while the evidence inventory is partial', rendered)
        self.assertIn('History, not vouched for', rendered)
        self.assertIn('required files absent: sockets.ndjson', rendered)
        self.assertNotIn('**Confirmed 30', rendered)
        published = (sim.generation('gen-0001') / 'published' / 'summary.md').read_text()
        self.assertIn('No claim stands', published)
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete')

    def test_rendering_a_report_is_not_evidence(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        (sim.run_dir(run_id) / 'game' / 'sampler.ndjson').unlink()
        later = se.export_session(sim.root, client=sim.client)
        self.assertNotEqual(later.status, 'complete')
        self.assertNoClaim(sim, later.generation)

    def test_a_disputed_verdict_is_not_vouched_for(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        classification = sim.run_dir(run_id) / 'classification.json'
        classification.chmod(0o640)
        classification.write_text(classification.read_text().replace('PASS', 'FAIL'))
        later = se.export_session(sim.root, client=sim.client)
        self.assertNotEqual(later.status, 'complete')
        self.assertNoClaim(sim, later.generation)

    def test_an_open_comparison_is_not_complete(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.batch()
        run_id = sim.records()[0]['run_id']
        guard = sim.root / cs.VALIDATION_GUARD_DIR / cs.validation_guard_name(run_id, 'game', 1, 0)
        guard.parent.mkdir(exist_ok=True)
        guard.write_text(json.dumps(cs.validation_guard(sim.session_id, sim.sha, run_id, 'game', 1, 'x')))
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'partial')
        self.assertTrue(any('comparison' in item for item in later.problems))

    def test_no_dispatched_run_is_not_complete_evidence(self):
        sim = ef.ExportSim(self)
        sim.ready()
        exported = se.export_session(sim.root, client=sim.client)
        self.assertEqual(exported.status, 'partial')
        self.assertTrue(any('no run was dispatched' in item for item in exported.problems))


class TransferFaults(unittest.TestCase):
    def roles(self, sim, generation='gen-0001'):
        return {(item['run_id'], item['role']): item for item in sim.document(generation)['roles']}

    def assertNothingPromotedBadly(self, sim):
        """Every promoted file is the one its seal names. A bad byte must never sit under a final name."""
        for row in sim.records():
            for role in ('game', 'bot'):
                seal = sim.run_dir(row['run_id']) / role / guest_runner.SEAL
                if not seal.exists():
                    continue
                for item in json.loads(seal.read_text())['files']:
                    path = sim.run_dir(row['run_id']) / role / item['path']
                    if path.exists():
                        self.assertEqual(sha(path.read_bytes()), item['sha256'], item['path'])

    def test_a_truncated_transfer_stays_partial_and_a_later_attempt_keeps_the_earlier_one(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))

        def hook(role, run_id, relative, data, attempt):
            if relative == 'telemetry/ticks.csv' and attempt == 1:
                return 1, data[:len(data) // 2]
            return 0, data
        sim.guests.get_hook = hook
        result = sim.batch()
        self.assertEqual(len(sim.records()), 1, 'an export failure stops the batch')
        run_id = sim.records()[0]['run_id']
        telemetry = sim.run_dir(run_id) / 'game' / 'telemetry'
        final = telemetry / 'ticks.csv'
        self.assertTrue(final.exists(), 'recovery brought the whole file')
        attempts = sorted(path.name for path in telemetry.glob('ticks.csv.partial*'))
        self.assertEqual(attempts, ['ticks.csv.partial.1'], 'the truncated attempt is kept under its own name')
        self.assertLess((telemetry / attempts[0]).stat().st_size, final.stat().st_size)
        self.assertNothingPromotedBadly(sim)
        self.assertEqual(sim.status_now()['evidence']['status'], 'complete', result)
        inventory = sim.document('gen-0001')
        self.assertEqual(inventory['attempts_retained'], 1)
        self.assertEqual(sim.document('gen-0001', 'session-report.json')['runs'][0]['outcome'], search.INFRASTRUCTURE_FAILURE)

    def test_a_transfer_failing_the_same_way_again_does_not_fill_the_disk_and_distinct_bytes_all_stay(self):
        same = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        same.guests.get_hook = lambda role, run_id, relative, data, attempt: (1, b'the same prefix') if relative == 'telemetry/ticks.csv' else (0, data)
        same.batch()
        self.assertGreater(same.guests.attempts[(same.records()[0]['run_id'], 'game', 'telemetry/ticks.csv')], 2)
        telemetry = same.run_dir(same.records()[0]['run_id']) / 'game' / 'telemetry'
        self.assertEqual(sorted(path.name for path in telemetry.glob('ticks.csv.partial*')), ['ticks.csv.partial', 'ticks.csv.partial.1'][:len(list(telemetry.glob('ticks.csv.partial*')))])
        self.assertLessEqual(len(list(telemetry.glob('ticks.csv.partial*'))), 2, 'identical bytes are kept once, and one more under the current name')
        differing = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        differing.guests.get_hook = lambda role, run_id, relative, data, attempt: (1, b'prefix %d' % attempt) if relative == 'telemetry/ticks.csv' else (0, data)
        differing.batch()
        attempts = differing.guests.attempts[(differing.records()[0]['run_id'], 'game', 'telemetry/ticks.csv')]
        telemetry = differing.run_dir(differing.records()[0]['run_id']) / 'game' / 'telemetry'
        self.assertEqual(len(list(telemetry.glob('ticks.csv.partial*'))), attempts, 'never overwrite an earlier attempt')

    def test_corrupt_bytes_are_never_promoted_and_stay_visible(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.guests.corrupt_export.add('telemetry/ticks.csv')
        sim.batch()
        self.assertEqual(len(sim.records()), 1)
        run_id = sim.records()[0]['run_id']
        self.assertFalse((sim.run_dir(run_id) / 'game' / 'telemetry' / 'ticks.csv').exists())
        self.assertTrue(list((sim.run_dir(run_id) / cs.CORRUPT_EVIDENCE_DIR).rglob('*ticks.csv.*')))
        self.assertEqual(sim.status_now()['evidence']['status'], 'corrupt')
        inventory = sim.document('gen-0001')
        self.assertEqual(inventory['status'], 'corrupt')
        self.assertTrue(inventory['corrupt_files'])
        self.assertEqual(self.roles(sim)[(run_id, 'bot')]['status'], 'verified', 'one role\'s damage costs the other nothing')
        report = sim.document('gen-0001', 'session-report.json')
        self.assertEqual(report['runs'][0]['outcome'], search.INFRASTRUCTURE_FAILURE)
        self.assertFalse(report['establishes'])

    def test_a_remote_file_that_changes_between_attempts_is_never_promoted(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.guests.get_hook = lambda role, run_id, relative, data, attempt: (0, data + (b'changed %d\n' % attempt)) if relative == 'sampler.ndjson' and role == 'bot' else (0, data)
        sim.batch()
        run_id = sim.records()[0]['run_id']
        self.assertFalse((sim.run_dir(run_id) / 'bot' / 'sampler.ndjson').exists())
        self.assertGreaterEqual(len(list((sim.run_dir(run_id) / cs.CORRUPT_EVIDENCE_DIR).rglob('*sampler.ndjson.*'))), 1)
        self.assertEqual(sim.status_now()['evidence']['status'], 'corrupt')
        self.assertEqual(self.roles(sim)[(run_id, 'bot')]['status'], 'corrupt')

    def test_bytes_of_the_wrong_role_fail_their_hash_and_are_not_filed(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))

        def hook(role, run_id, relative, data, attempt):
            if role == 'bot' and relative == guest_runner.SEAL:
                return 0, sim.guests.hosts['game'].runs[run_id].files[guest_runner.SEAL]
            return 0, data
        sim.guests.get_hook = hook
        sim.batch()
        run_id = sim.records()[0]['run_id']
        self.assertFalse((sim.run_dir(run_id) / 'bot' / guest_runner.SEAL).exists())
        self.assertEqual(self.roles(sim)[(run_id, 'bot')]['status'], 'corrupt')
        self.assertEqual(self.roles(sim)[(run_id, 'game')]['status'], 'verified')

    def test_a_seal_of_another_role_or_run_on_this_disk_is_corrupt_evidence(self):
        for change, label in ((lambda seal: seal.update(role='game'), 'wrong role'), (lambda seal: seal.update(run_id='another-run'), 'wrong run')):
            with self.subTest(label):
                sim, _ = confirmed_session(self)
                run_id = sim.records()[0]['run_id']
                path = sim.run_dir(run_id) / 'bot' / guest_runner.SEAL
                seal = json.loads(path.read_text())
                change(seal)
                path.chmod(0o640)
                path.write_text(json.dumps(seal))
                later = se.export_session(sim.root, client=sim.client)
                self.assertEqual(later.status, 'corrupt')
                self.assertEqual(self.roles(sim, later.generation)[(run_id, 'bot')]['status'], 'corrupt')
                self.assertFalse(sim.document(later.generation, 'session-report.json')['establishes'])

    def test_a_replaced_seal_of_the_right_shape_disagrees_with_the_retained_receipts(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        path = sim.run_dir(run_id) / 'game' / guest_runner.SEAL
        seal = json.loads(path.read_text())
        seal['files'] = seal['files'][1:]
        path.chmod(0o640)
        path.write_text(json.dumps(seal))
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'corrupt')
        self.assertTrue(any('seal' in item for item in later.problems))

    def test_a_file_that_is_not_in_the_seal_is_not_vouched_for(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        directory = sim.run_dir(run_id) / 'game'
        directory.chmod(0o750)
        (directory / 'from-another-role.ndjson').write_text('{}\n')
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'partial')
        self.assertEqual(self.roles(sim, later.generation)[(run_id, 'game')]['unlisted'], ['from-another-role.ndjson'])

    def test_a_recorder_of_a_stale_schema_is_corrupt_evidence_whatever_its_hash(self):
        def stale(tree, trial):
            path = tree.path('bot/swarm/swarm.json')
            document = json.loads(path.read_text())
            document['schema'] = 'omega.measurement/2'
            path.write_text(json.dumps(document) + '\n')
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=stale))
        sim.batch()
        self.assertEqual(sim.status_now()['evidence']['status'], 'corrupt')
        self.assertTrue(any('omega.measurement/2' in item for item in sim.document('gen-0001')['problems']))

    def test_a_changed_manifest_is_not_a_session_any_report_can_speak_for(self):
        sim, _ = confirmed_session(self)
        manifest = json.loads((sim.root / 'manifest.json').read_text())
        manifest['limits']['max_estimated_session_usd'] = 999
        (sim.root / 'manifest.json').write_text(json.dumps(manifest))
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'corrupt')
        self.assertFalse((sim.generation(later.generation) / se.REPORT_JSON).exists())
        self.assertFalse((sim.generation(later.generation) / se.PUBLISHED).exists())
        self.assertTrue((sim.generation(later.generation) / se.INVENTORY_FILE).exists(), 'the inventory is still what happened')

    def test_a_registry_holding_another_manifest_is_said_out_loud(self):
        sim, _ = confirmed_session(self)
        client = mock.Mock()
        client.call.side_effect = lambda method, **_: dict(evaluated_at='2026-10-30T12:00:00+00:00') if method == 'health' else (dict(manifest_sha256='0' * 64, runs=[]) if method == 'status' else [])
        later = se.export_session(sim.root, client=client)
        self.assertTrue(any('another manifest' in item for item in later.problems))
        self.assertNotEqual(later.status, 'complete')

    def test_no_space_during_promotion_keeps_the_partial_and_never_says_verified(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        real = run_executor.publish_new

        def fail(source, target):
            if pathlib.Path(target).name == 'ticks.csv':
                raise OSError(errno.ENOSPC, 'No space left on device')
            real(source, target)
        with mock.patch.object(run_executor, 'publish_new', side_effect=fail):
            result = sim.batch()
        run_id = sim.records()[0]['run_id']
        telemetry = sim.run_dir(run_id) / 'game' / 'telemetry'
        self.assertFalse((telemetry / 'ticks.csv').exists())
        self.assertTrue(list(telemetry.glob('ticks.csv.partial*')), 'the good bytes stay where they arrived')
        self.assertEqual(self.roles(sim)[(run_id, 'game')]['status'], 'missing')
        self.assertEqual(sim.status_now()['evidence']['status'], 'missing')
        self.assertTrue(sim.status_now()['cleanup']['requested_at'], 'evidence trouble holds up nothing: %s' % result)

    def test_a_failed_rename_of_one_file_costs_only_that_file(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        real = os.link

        def fail(source, target, **options):
            if pathlib.Path(target).name == 'window.json' and 'swarm' in str(target):
                raise OSError(errno.EIO, 'I/O error')
            return real(source, target, **options)
        with mock.patch.object(run_executor.os, 'link', side_effect=fail):
            sim.batch()
        run_id = sim.records()[0]['run_id']
        roles = self.roles(sim)
        self.assertEqual(roles[(run_id, 'bot')]['status'], 'missing')
        self.assertEqual(roles[(run_id, 'game')]['status'], 'verified')
        self.assertTrue((sim.run_dir(run_id) / 'bot' / 'swarm' / 'shard-0.ndjson').exists())

    def test_a_transfer_that_keeps_failing_keeps_both_roles_available_files(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))

        def hook(role, run_id, relative, data, attempt):
            return (1, None) if role == 'game' and relative == 'telemetry/ticks.csv' else (0, data)
        sim.guests.get_hook = hook
        sim.batch()
        run_id = sim.records()[0]['run_id']
        self.assertEqual(self.roles(sim)[(run_id, 'game')]['status'], 'missing')
        self.assertEqual(self.roles(sim)[(run_id, 'bot')]['status'], 'verified')
        for name in ('game/sampler.ndjson', 'game/telemetry/final.json', 'bot/swarm/window.json'):
            self.assertTrue((sim.run_dir(run_id) / name).exists(), name)
        self.assertEqual(sim.status_now()['evidence']['status'], 'missing')
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete')

    def test_a_hung_copy_that_claims_success_without_a_file_is_only_a_local_failure(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.guests.get_hook = lambda role, run_id, relative, data, attempt: (0, None) if relative == 'sampler.ndjson' and role == 'game' else (0, data)
        sim.batch()
        run_id = sim.records()[0]['run_id']
        self.assertEqual(self.roles(sim)[(run_id, 'game')]['status'], 'missing')
        self.assertEqual(sim.status_now()['evidence']['status'], 'missing')


class ExportFailureIsNotCleanupFailure(unittest.TestCase):
    def test_no_space_for_the_generation_leaves_no_generation_and_still_asks_for_cleanup(self):
        def fail(name):
            if name == 'before_generation_rename':
                raise OSError(errno.ENOSPC, 'No space left on device')
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        result = sim.batch(failpoint=fail)
        self.assertEqual(result.status, run_executor.FINISHED)
        status = sim.status_now()
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertIn(status['evidence']['status'], ('partial', 'missing'), 'only a whole, written generation can say complete')
        self.assertFalse(list((sim.root / 'export').glob('gen-0001')))
        self.assertTrue(list((sim.root / 'export').glob('gen-0001.writing-*')), 'what got written stays, and nothing promotes it')
        self.assertTrue(result.wrap_up_errors)
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete')

    def test_the_directory_rename_failing_is_the_same(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        real = os.rename

        def fail(source, target, **options):
            if '.writing-' in str(source):
                raise OSError(errno.EXDEV, 'Cross-device link')
            return real(source, target, **options)
        with mock.patch.object(se.os, 'rename', side_effect=fail):
            sim.batch()
        self.assertNotEqual(sim.status_now()['evidence']['status'], 'complete')
        self.assertTrue(sim.status_now()['cleanup']['requested_at'])

    def test_a_defect_in_the_exporter_still_reaches_the_cleanup_request(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        with mock.patch.object(se, 'export_session', side_effect=RuntimeError('a defect')):
            result = sim.batch()
        self.assertTrue(sim.status_now()['cleanup']['requested_at'])
        self.assertNotEqual(sim.status_now()['evidence']['status'], 'complete')
        self.assertTrue(any('RuntimeError' in item for item in result.wrap_up_errors))

    def test_a_defect_in_a_report_costs_that_report_and_the_inventory_stays(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        with mock.patch.object(sr, 'build', side_effect=KeyError('a defect')):
            sim.batch()
        self.assertEqual(se.reproduce(sim.root, 'gen-0001'), [], 'nothing was written to compare, and its inventory says why')
        status = sim.status_now()
        self.assertEqual(status['evidence']['status'], 'partial', 'a session whose report could not be written is not complete')
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertTrue((sim.generation('gen-0001') / se.INVENTORY_FILE).exists())
        self.assertFalse((sim.generation('gen-0001') / se.REPORT_JSON).exists())

    def test_a_registry_that_stops_answering_costs_the_cleanup_statement_and_nothing_else(self):
        sim, _ = confirmed_session(self)
        client = mock.Mock()
        client.call.side_effect = registry_client.RegistryUnavailable('gone')
        later = se.export_session(sim.root, client=client)
        self.assertIsNotNone(later.generation)
        cleanup = sim.document(later.generation, 'session-report.json')['results']['cleanup']
        self.assertFalse(cleanup['known'])
        self.assertFalse(cleanup['verified_absent'])
        self.assertIn('nothing is said about the resources', cleanup['statement'])

    def test_a_registry_down_through_the_whole_wrap_up_still_leaves_a_generation_and_the_watchdog_still_deletes(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        executor = sim.executor()
        result = executor.execute()
        self.assertEqual(result.status, run_executor.FINISHED)
        real = executor.client.call

        def down(method, *arguments, **options):
            raise registry_client.RegistryUnavailable('gone')
        with mock.patch.object(executor.client, 'call', side_effect=down):
            executor.wrap_up(result)
        self.assertEqual(executor.client.call, real)
        inventory = sim.document('gen-0001')
        self.assertEqual(len([item for item in inventory['roles'] if item['status'] == 'verified']), 14, 'the search journal says what ran when the registry cannot')
        self.assertFalse(sim.document('gen-0001', se.REPORT_JSON)['results']['cleanup']['known'])
        self.assertIsNone(sim.status_now()['cleanup']['requested_at'], 'the request could not reach it')
        c = session_clock.parse(sim.status_now()['cleanup_c_utc'])
        while sim.clock.wall() < c + 5:
            sim.sleep(30)
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete', 'the watchdog deletes by C, and the evidence was never acknowledged as complete')

    def test_cleanup_is_requested_with_or_without_any_of_this_and_the_watchdog_needs_none_of_it(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        c = session_clock.parse(sim.status_now()['cleanup_c_utc'])
        while sim.clock.wall() < c + 5:     # no controller ever came, and no export ever ran
            sim.sleep(30)
        self.assertEqual(sim.drive_cleanup()['overall'], 'resources_verified_evidence_incomplete')
        self.assertFalse((sim.root / 'export').exists())


class RecoveryEpisode(unittest.TestCase):
    def seconds_to(self, sim, moment):
        return moment - sim.clock.wall()

    def episode(self, sim):
        return [event for event in sim.stack.registry.journal(sim.session_id) if event['kind'] == 'evidence_recovery']

    def failed_session(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        sim.guests.copy_failures.update({('game', 'get'), ('bot', 'get')})
        executor = sim.executor()
        executor.execute()
        return sim, executor

    def test_the_episode_is_fixed_by_the_first_failure_and_not_by_when_recovery_began(self):
        sim, executor = self.failed_session()
        failed = [event for event in sim.stack.registry.journal(sim.session_id) if event['kind'] == 'evidence_failure']
        self.assertEqual(len(failed), 1)
        first = session_clock.parse(failed[0]['at'])
        sim.sleep(20)
        sim.client.mutate('begin_collection', session_id=sim.session_id, fencing_token=executor.token)
        episode = executor.client.mutate('begin_evidence_recovery', session_id=sim.session_id, fencing_token=executor.token)
        self.assertEqual(session_clock.parse(episode['first_failure_at']), first)
        self.assertEqual(session_clock.parse(episode['recovery_deadline_utc']), first + sim.manifest['limits']['evidence_recovery_grace_s'], 'twenty seconds later it still ends where the first failure put it')

    def test_a_reconnect_or_a_new_controller_never_resets_it(self):
        sim, executor = self.failed_session()
        sim.client.mutate('begin_collection', session_id=sim.session_id, fencing_token=executor.token)
        episode = sim.client.mutate('begin_evidence_recovery', session_id=sim.session_id, fencing_token=executor.token)
        sim.sleep(60)
        controller, control = sim.controller()
        again = controller.client.mutate('begin_evidence_recovery', session_id=sim.session_id, fencing_token=control['fencing_token'])
        self.assertEqual(again['recovery_deadline_utc'], episode['recovery_deadline_utc'])
        self.assertEqual(again['first_failure_at'], episode['first_failure_at'])
        controller.client.mutate('record_evidence_failure', session_id=sim.session_id, fencing_token=control['fencing_token'], detail='later')
        self.assertEqual(controller.client.mutate('begin_evidence_recovery', session_id=sim.session_id, fencing_token=control['fencing_token'])['recovery_deadline_utc'], episode['recovery_deadline_utc'])

    def test_c_bounds_it_when_c_comes_first(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        executor = sim.executor()
        c = session_clock.parse(sim.status_now()['cleanup_c_utc'])
        while c - sim.clock.wall() > 60:
            sim.sleep(30)
            sim.client.call('renew_control', session_id=sim.session_id, fencing_token=executor.token)
        sim.client.mutate('record_evidence_failure', session_id=sim.session_id, fencing_token=executor.token, detail='scripted')
        sim.client.mutate('begin_collection', session_id=sim.session_id, fencing_token=executor.token)
        episode = sim.client.mutate('begin_evidence_recovery', session_id=sim.session_id, fencing_token=executor.token)
        self.assertEqual(session_clock.parse(episode['recovery_deadline_utc']), c)

    def test_a_failure_older_than_the_grace_fetches_nothing_and_the_batch_still_reaches_cleanup(self):
        sim, executor = self.failed_session()
        sim.guests.copy_failures.clear()
        sim.sleep(sim.manifest['limits']['evidence_recovery_grace_s'] + 10)
        before = len([command for command in sim.guests.commands if command.get('step') == 'get'])
        result = run_executor.BatchResult(run_executor.STOPPED, code='late', detail='test')
        executor.wrap_up(result)
        self.assertEqual(len([command for command in sim.guests.commands if command.get('step') == 'get']), before, 'nothing starts past the end of the episode')
        self.assertTrue(sim.status_now()['cleanup']['requested_at'])
        self.assertNotEqual(sim.status_now()['evidence']['status'], 'complete')

    def test_a_retry_keeps_within_the_episode_and_evidence_loss_extends_nothing(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        sim.guests.copy_failures.update({('game', 'get')})
        executor = sim.executor()
        executor.run_batch()
        status = sim.status_now()
        self.assertTrue(status['cleanup']['requested_at'])
        failure = session_clock.parse(next(event['at'] for event in sim.stack.registry.journal(sim.session_id) if event['kind'] == 'evidence_failure'))
        self.assertLessEqual(session_clock.parse(status['recovery_deadline_utc']), failure + sim.manifest['limits']['evidence_recovery_grace_s'])
        self.assertLessEqual(session_clock.parse(status['cleanup']['requested_at']), session_clock.parse(status['recovery_deadline_utc']) + 1)
        self.assertEqual(status['deadline_d_utc'], sim.stack.registry.status(sim.session_id)['deadline_d_utc'], 'the deadline is what it always was')
        final = sim.drive_cleanup()
        self.assertEqual(final['overall'], 'resources_verified_evidence_incomplete')
        self.assertLessEqual(session_clock.parse(final['cleanup']['verified_at']), session_clock.parse(final['deadline_d_utc']))

    def test_verified_success_deletes_promptly_long_before_any_deadline(self):
        sim, _ = confirmed_session(self)
        status = sim.status_now()
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertLess(session_clock.parse(status['cleanup']['requested_at']), session_clock.parse(status['cleanup_c_utc']) - 3600, 'a finished session never waits for its cap')
        self.assertEqual(sim.drive_cleanup(limit_s=300)['overall'], 'clean')

    def test_the_first_failure_is_first_wins_and_only_for_the_current_controller(self):
        sim = ef.ExportSim(self)
        sim.ready()
        token = sim.result.fencing_token
        first = sim.client.mutate('record_evidence_failure', session_id=sim.session_id, fencing_token=token, detail='one')
        sim.clock.advance(10)
        second = sim.client.mutate('record_evidence_failure', session_id=sim.session_id, fencing_token=token, detail='two')
        self.assertEqual(first['first_failure_at'], second['first_failure_at'])
        with self.assertRaises(registry_client.RegistryRejected):
            sim.client.mutate('record_evidence_failure', session_id=sim.session_id, fencing_token=token + 1, detail='stale')

    def test_a_lost_failure_report_only_costs_the_difference(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        sim.guests.copy_failures.update({('game', 'get')})
        executor = sim.executor()
        real = executor.client.mutate

        def lost(method, *arguments, **options):
            if method == 'record_evidence_failure':
                raise registry_client.RegistryUnavailable('lost')
            return real(method, *arguments, **options)
        with mock.patch.object(executor.client, 'mutate', side_effect=lost):
            executor.run_batch()
        status = sim.status_now()
        self.assertTrue(status['cleanup']['requested_at'])
        self.assertIsNotNone(status['recovery_deadline_utc'])
        self.assertLessEqual(session_clock.parse(status['recovery_deadline_utc']), session_clock.parse(status['cleanup_c_utc']))


class Reports(unittest.TestCase):
    def report(self):
        sim, _ = confirmed_session(self)
        sim.drive_cleanup()
        exported = se.export_session(sim.root, client=sim.client)
        return sim, sim.document(exported.generation, 'session-report.json'), (sim.generation(exported.generation) / se.REPORT_MD).read_text()

    def test_the_report_is_labelled_digitalocean_and_keeps_cax11_apart(self):
        sim, report, text = self.report()
        self.assertEqual(report['provider'], 'DigitalOcean')
        self.assertTrue(report['label'].startswith('do-sgp-premium-amd-1vcpu-1g-public-'))
        self.assertIn('not a CAX11 result', text)
        self.assertIn('historical CAX11 gate', report['separate_from_cax11'])

    def test_every_required_diagnostic_is_there_from_the_recorders(self):
        _, report, text = self.report()
        run = report['runs'][0]['diagnostics']
        self.assertEqual(run['ticks']['p95_work_ns'], 2_000_000)
        self.assertEqual(run['ticks']['max_work_ns'], 2_000_000)
        self.assertEqual((run['ticks']['over_budget_at_least'], run['ticks']['over_budget_at_most']), (0, 0))
        self.assertAlmostEqual(run['ticks']['achieved_ticks_per_s'], 30.0, delta=0.5)
        self.assertEqual(run['ticks']['authenticated_min'], 25)
        self.assertEqual(run['server']['snapshot_build']['mean_ns'], 400_000.0)
        self.assertEqual(run['server']['average_recipients'], 9.0)
        self.assertGreater(run['server']['reliable_event_sends'], 0)
        self.assertEqual(run['server']['unreliable_event_sends'], 2 * run['server']['reliable_event_sends'])
        self.assertEqual(run['peers']['rtt_p95_ms'], 12.5)
        self.assertEqual(run['peers']['loss_estimate_peak_per_second_mean'], 0.0)
        self.assertIn('smoothed', run['peers']['loss_estimator'])
        game = run['window']['game']
        self.assertEqual(game['process']['percent_of_one_core'], 20.0)
        self.assertEqual(game['host']['utilization_percent'], 25.0)
        self.assertEqual(game['host']['steal_percent'], 1.0)
        self.assertLess(game['memory']['available_min_bytes'], 500_000_000)
        self.assertEqual(game['memory']['swap_used_max_bytes'], 0)
        self.assertEqual(game['memory']['host_oom_kill_delta'], 0)
        self.assertEqual(game['kernel_receive_errors'], 0)
        threads = run['window']['bot']['process']['threads']
        self.assertEqual(len(threads), 4)
        self.assertEqual({item['percent_of_one_core'] for item in threads}, {10.0})
        self.assertEqual(run['sockets']['game_socket_drops'], 0)
        for heading in ('Snapshot build mean', 'Avg recipients', 'Steal', 'Host RcvbufErrors', 'Gen sock drops'):
            self.assertIn(heading, text)

    def test_window_and_lifetime_traffic_are_separate_and_labelled(self):
        _, report, text = self.report()
        run = report['runs'][0]['diagnostics']
        window = run['window']['game']['traffic']
        self.assertEqual(window['tx_bytes_per_s'], ef.INTERFACE_TX_PER_S)
        self.assertEqual(window['tx_bits_per_s'], ef.INTERFACE_TX_PER_S * 8, 'bits are named as bits')
        self.assertEqual(window['tx_bytes_per_s_per_player'], ef.INTERFACE_TX_PER_S / 25)
        span = run['run_span_traffic']['game']
        self.assertGreater(span['tx_bytes'], window['tx_bytes'], 'ramp and drain are not in the window')
        self.assertEqual(run['server']['application_sent_bytes_per_s_per_player'], (ef.APP_BYTES_PER_S + 100) / 25)
        self.assertEqual(window['interfaces']['lo']['tx_bytes'] is not None, True)
        self.assertNotEqual(window['tx_bytes'], window['interfaces']['lo']['tx_bytes'], 'loopback is not transfer')
        self.assertIn('Run-span figures include ramp and drain', text)

    def test_missing_values_read_as_unknown_and_never_as_zero(self):
        sim = ef.ExportSim(self, sf.by_target(ef.CONFIRMING))     # the slice 5 trees, with no interface, memory or server rows
        sim.batch()
        report = sim.document('gen-0001', 'session-report.json')
        run = report['runs'][0]['diagnostics']
        self.assertIsNone(run['window']['game']['traffic']['tx_bytes'])
        self.assertIsNone(run['window']['game']['memory']['available_min_bytes'])
        self.assertFalse(run['server']['covered'])
        self.assertIsNone(report['economics']['session_estimate']['hosts']['game']['measured_outbound_bytes_lower_bound'])
        self.assertIn('unknown', (sim.generation('gen-0001') / se.REPORT_MD).read_text())

    def test_a_surprising_recorder_costs_one_diagnostic_and_no_report(self):
        def odd(tree, trial):
            tree.path('game/telemetry/server.ndjson').write_text('{"mono_ns": "not a number"}\n[1,2]\nnot json\n')
            tree.edit_sampler('game', lambda index, row: row.update(interfaces='nope', memory=['x'], system=7))
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=odd))
        sim.batch()
        report = sim.document('gen-0001', 'session-report.json')
        self.assertFalse(report['runs'][0]['diagnostics']['server']['covered'])

    def test_money_has_four_lines_and_they_are_never_added_together(self):
        sim, report, text = self.report()
        economy = report['economics']
        nominal = economy['nominal_game_tier']
        self.assertEqual(nominal['monthly_usd'], 7.0)
        self.assertEqual(nominal['confirmed_players'], 30)
        self.assertEqual(nominal['players_per_monthly_game_usd'], round(30 / 7.0, 3))
        session = economy['session_estimate']
        self.assertIn('not an invoice', session['label'])
        hosts = session['hosts']
        self.assertEqual(sorted(hosts), ['bot', 'game'], 'the bot host is never omitted')
        quote = sim.manifest['quote']['roles']
        self.assertEqual(hosts['game']['compute_usd'], round(hosts['game']['billable_units'] * quote['game']['price_hourly_usd'], 6))
        self.assertEqual(session['total_estimated_usd'], round(hosts['game']['compute_usd'] + hosts['bot']['compute_usd'] + hosts['game']['transfer_overage_usd'] + hosts['bot']['transfer_overage_usd'], 6))
        self.assertGreater(hosts['game']['measured_outbound_bytes_lower_bound'], 0)
        self.assertLess(hosts['game']['prorated_allowance_gib'], quote['game']['transfer_tib_month'] * 1024, 'a short-lived host never gets a whole month')
        self.assertIn('not what was spent', economy['admission_estimate']['label'])
        self.assertEqual(economy['management_host']['monthly_usd'], sim.manifest['pricing']['management_host_monthly_usd'])
        self.assertIn('in none of the above', economy['management_host']['label'])
        self.assertEqual(economy['invoices']['recorded'], [])
        self.assertIn('Nothing in this report is an invoice', text)

    def test_an_invoice_is_recorded_later_kept_apart_and_changes_no_earlier_generation(self):
        sim, _, _ = self.report()
        before = tree_bytes(sim.generation('gen-0002'))
        estimate = sim.document('gen-0002', 'session-report.json')['economics']['session_estimate']['total_estimated_usd']
        se.record_invoice(sim.root, '2026-11', '1.23', 'provider invoice, by hand', '2026-12-01T00:00:00+00:00')
        later = se.export_session(sim.root, client=sim.client)
        report = sim.document(later.generation, 'session-report.json')
        self.assertEqual(report['economics']['invoices']['recorded'][0]['amount_usd'], 1.23)
        self.assertEqual(report['economics']['session_estimate']['total_estimated_usd'], estimate, 'an invoice is not folded into any estimate')
        self.assertEqual(tree_bytes(sim.generation('gen-0002')), before)
        self.assertEqual(se.reproduce(sim.root, later.generation), [])

    def test_a_search_cap_pass_is_a_lower_bound_and_is_labelled_so(self):
        economy = sr.economics(ef.ExportSim(self).manifest, dict(confirmed=True, players=None, lower_bound=500, search_cap_reached=True), dict(seconds=None, basis='x'), dict(game=None, bot=None), ())
        self.assertTrue(economy['nominal_game_tier']['is_lower_bound'])
        self.assertEqual(economy['nominal_game_tier']['confirmed_players'], 500)

    def test_overdue_cleanup_stays_on_record_after_it_resolves(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING), account_options=dict())
        sim.batch()
        deadline = session_clock.parse(sim.status_now()['deadline_d_utc'])
        real = sim.stack.watchdog.provider.delete_droplet

        def fail(droplet_id):
            if sim.clock.wall() < deadline + 120:
                raise cleanup_provider.ProviderError('scripted outage')
            return real(droplet_id)
        with mock.patch.object(sim.stack.watchdog.provider, 'delete_droplet', side_effect=fail):
            final = sim.drive_cleanup(limit_s=16000)
        self.assertEqual(final['overall'], 'resources_verified_after_overdue')
        later = se.export_session(sim.root, client=sim.client)
        cleanup = sim.document(later.generation, 'session-report.json')['results']['cleanup']
        self.assertTrue(cleanup['overdue'])
        self.assertTrue(cleanup['verified_absent'])
        self.assertTrue(any(item['kind'] == 'cleanup-overdue' for item in cleanup['incidents']))
        self.assertGreater(cleanup['overrun_s'], 0)
        self.assertIn('stays on record', cleanup['statement'])
        rendered = (sim.generation(later.generation) / se.REPORT_MD).read_text()
        self.assertIn('Incident on record: cleanup-overdue', rendered)
        published = sim.document(later.generation, 'published/summary.json')
        self.assertTrue(any(item['kind'] == 'cleanup-overdue' for item in published['results']['cleanup']['incidents']))

    def test_resume_history_and_the_episode_are_in_the_report(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        sim.guests.copy_failures.add(('game', 'get'))
        sim.executor().run_batch()
        report = sim.document('gen-0001', 'session-report.json')
        self.assertIsNotNone(report['records']['recovery_episode'])
        self.assertEqual(report['records']['registry_journal']['valid'], True)
        self.assertEqual(report['records']['resume_history'], [])


    def test_a_refused_resume_is_in_the_report_with_its_code(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING))
        sim.ready()
        with self.assertRaises(rf.SimulatedCrash):
            sim.executor(failpoint=rf.crash_at('after_running_commit')).execute()
        controller, control = sim.controller()
        refused = controller.resume('operator-request-one', control)
        self.assertFalse(refused['resumed'])
        controller.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='after_refusal', detail='test', runs=controller.outcomes))
        history = sim.document(se.latest_generation(sim.root), se.REPORT_JSON)['records']['resume_history']
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]['decision'], history[0]['operator_request_ref']), ('refused', 'operator-request-one'))
        self.assertEqual(history[0]['code'], refused['code'])
        self.assertTrue(sim.document(se.latest_generation(sim.root), se.REPORT_JSON)['records']['fencing_tokens'])

    def test_the_batch_result_names_the_generation_and_says_nothing_of_cleanup(self):
        sim, result = confirmed_session(self)
        self.assertEqual(result.evidence_export['generation'], 'gen-0001')
        self.assertEqual(result.evidence_export['status'], 'complete')
        self.assertTrue(result.evidence_export['ref'].startswith('export/gen-0001/'))
        self.assertNotIn('cleanup', result.evidence_export)

    def test_an_unreadable_role_costs_that_role(self):
        sim, _ = confirmed_session(self)
        run_id = sim.records()[0]['run_id']
        with mock.patch.object(se, 'role_inventory', side_effect=[PermissionError('x')] + [se.role_inventory] * 0 + [dict(run_id=run_id, role='bot', status='verified', files=[], required_absent=[], partial_retained=[], problems=[])] * 200):
            later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'corrupt')
        self.assertIsNotNone(later.generation)

    def test_an_invoice_amount_must_be_a_real_amount(self):
        sim = ef.ExportSim(self)
        for amount in ('nan', 'inf', '-1', 'free'):
            with self.subTest(amount), self.assertRaises(ValueError):
                se.record_invoice(sim.root, 'p', amount, 's', 'now')
        with self.assertRaises(ValueError):
            se.record_invoice(sim.root, 'p', '1', 'dop_v1_' + 'c' * 64, 'now')


class Redaction(unittest.TestCase):
    def exposed(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=lambda tree, trial: ef.expose_socket_fields(tree)))
        sim.batch()
        return sim

    def test_a_new_socket_field_cannot_reach_anything_derived_and_stays_in_the_private_raw(self):
        sim = self.exposed()
        self.assertEqual(sim.status_now()['evidence']['status'], 'complete')
        run_id = sim.records()[0]['run_id']
        self.assertIn(ef.SOCKET_MARKER, (sim.run_dir(run_id) / 'game' / 'sampler.ndjson').read_text(), 'the fixture must really have carried it')
        top = sim.generation('gen-0001')
        for name in ('published/summary.md', 'published/summary.json', 'published/SHA256SUMS', se.REPORT_MD, se.REPORT_JSON):
            text = (top / name).read_text()
            for marker in (ef.SOCKET_MARKER, ef.ENDPOINT_MARKER, ef.KERNEL_ENDPOINT_MARKER):
                self.assertNotIn(marker, text, name)
        for name in ('summary.json', 'REPORT.md'):
            self.assertNotIn(ef.SOCKET_MARKER, (sim.run_dir(run_id) / name).read_text(), name)

    def test_the_summary_only_has_the_fields_someone_named(self):
        sim = self.exposed()
        summary = sim.document('gen-0001', 'published/summary.json')
        run = summary['runs'][0]
        allowed = {'run_id', 'ordinal', 'phase', 'target', 'repetition', 'hold_s', 'outcome', 'classification', 'offered_load', 'gates', 'verified', 'evidence', 'required_files_absent', 'not_verified_reasons', 'proof_reason_codes', 'ticks', 'snapshot_build_mean_ns', 'reliable_event_sends', 'unreliable_event_sends', 'source_events', 'average_recipients', 'peers',
                   'game_cpu_percent_of_one_core', 'generator_thread_cpu_percent_of_one_core', 'host_utilization_percent', 'host_steal_percent', 'memory_available_min_bytes', 'swap_used_max_bytes', 'oom_kill_delta', 'game_socket_drops', 'generator_socket_drops', 'kernel_receive_errors', 'window_traffic', 'run_span_traffic', 'gate_values', 'trajectory'}
        self.assertEqual(set(run), allowed)
        self.assertNotIn('reasons', run, 'free text from a host stays private')
        self.assertNotIn('evidence_problems', run)
        text = json.dumps(summary)
        for private in ('access_allowlists', 'ssh_key', 'credentials', 'private_key', 'omega-watchdog@', 'fingerprint'):
            self.assertNotIn(private, text)

    def test_the_summary_names_the_limit_each_gate_was_held_to(self):
        sim, _ = confirmed_session(self)
        summary = sim.document('gen-0001', 'published/summary.json')
        self.assertEqual(summary['gate_policy'], dict(policy_sha256=cs.POLICY_SHA256, tick_budget=dict(budget_ns=33_300_000, over_percent_strictly_below=1), rtt_p95=dict(limit_ms_strictly_below=150, quantile_percent=95), enet_loss=dict(limit_strictly_below='2/100'),
                                                      game_socket_drops=dict(allowed=0), continuity=dict(unexpected_disconnects_allowed=0), bot_errors=dict(total_allowed=0)))
        self.assertEqual(set(summary['gate_policy']) - {'policy_sha256'}, set(cs.GATE_NAMES), 'every gate has its limit')
        self.assertIn('33300000', sim.generation('gen-0001').joinpath('published/summary.md').read_text())

    def test_each_run_publishes_what_its_gates_measured(self):
        sim, _ = confirmed_session(self)
        passing, failing = [next(row for row in sim.document('gen-0001', 'published/summary.json')['runs'] if row['outcome'] == outcome) for outcome in ('PASS', 'FAIL')]
        self.assertEqual(passing['gate_values']['continuity_unexpected_disconnects'], 0)
        self.assertEqual(passing['gate_values']['bot_errors_total'], 0)
        self.assertEqual(passing['gate_values']['tick_over_budget_worst_ratio']['approximate'], 0.0)
        self.assertGreaterEqual(failing['gate_values']['tick_over_budget_worst_ratio']['approximate'], 0.01)
        self.assertRegex(failing['gate_values']['tick_over_budget_worst_ratio']['exact'], r'^\d+/\d+$')

    def test_each_run_publishes_its_tick_distribution(self):
        sim, _ = confirmed_session(self)
        for row in sim.document('gen-0001', 'published/summary.json')['runs']:
            ticks = row['ticks']
            self.assertLessEqual(ticks['p50_work_ns'], ticks['p90_work_ns'])
            self.assertLessEqual(ticks['p90_work_ns'], ticks['p95_work_ns'])
            self.assertLessEqual(ticks['p95_work_ns'], ticks['p99_work_ns'])
            self.assertLessEqual(ticks['p99_work_ns'], ticks['max_work_ns'])

    def test_each_run_publishes_one_trajectory_entry_per_held_second_that_agrees_with_its_gates(self):
        sim, _ = confirmed_session(self)
        for row in sim.document('gen-0001', 'published/summary.json')['runs']:
            trajectory = row['trajectory']
            self.assertTrue(trajectory['covered'], row['run_id'])
            self.assertEqual(trajectory['seconds'], row['hold_s'])
            self.assertIn('decide nothing', trajectory['scope'])
            for name in sr.TRAJECTORY_SERIES:
                self.assertEqual(len(trajectory[name]), row['hold_s'], name)
            self.assertEqual(max(item for item in trajectory['tick_max_work_ns'] if item is not None), row['ticks']['max_work_ns'])
            self.assertEqual(sum(item for item in trajectory['tick_over_budget'] if item is not None), row['ticks']['over_budget_at_least'])
            self.assertEqual(max(trajectory['loss_estimate_mean']), row['peers']['loss_estimate_peak_per_second_mean'])
            self.assertLessEqual(max(trajectory['rtt_p95_ms']), row['peers']['rtt_max_ms'])

    def test_the_trajectory_of_a_run_with_no_proof_reads_as_not_covered(self):
        self.assertEqual(sr._trajectory('/nonexistent', None, dict(hold_s=60, target=1), {}), dict(covered=False))

    def test_a_stepped_wall_clock_leaves_no_tick_trajectory(self):
        proof = dict(reasons=[dict(code='clock_step')], facts=dict(population=dict(core_game_mono_ns=[0, 10 * sr.NS])))
        self.assertIsNone(sr._tick_series('/nonexistent', proof, 10))

    # 35 bots at 1311 and 15 at 1310 on the 65536 scale: a mean of 13107/655360, which passes the strict 2/100 limit.
    JUST_BELOW_THE_LOSS_LIMIT = 13107 / 655360

    def test_a_loss_just_below_the_limit_is_published_unrounded_in_the_trajectory(self):
        proof = dict(facts=dict(population=dict(core_game_mono_ns=[0, 2 * sr.NS])))
        with mock.patch.object(cs, 'per_second_series', return_value=dict(rtt_p95_ms=[12, None], loss_estimate_mean=[self.JUST_BELOW_THE_LOSS_LIMIT, None])):
            trajectory = sr._trajectory('/nonexistent', proof, dict(hold_s=2, target=50), {})
        self.assertEqual(trajectory['loss_estimate_mean'], [self.JUST_BELOW_THE_LOSS_LIMIT, None])
        self.assertLess(trajectory['loss_estimate_mean'][0], 0.02)

    def test_a_loss_just_below_the_limit_is_published_unrounded_beside_its_gate(self):
        near = cs.exact(cs.fractions.Fraction(13107, 655360))
        peers = sr._peer_diagnostics(dict(enet_loss=dict(per_second_mean_peak=dict(ratio=near), window_mean_of_seconds=near, peer_peak=dict(ratio=near))))
        for name in ('loss_estimate_peak_per_second_mean', 'loss_estimate_window_mean', 'loss_estimate_peer_peak'):
            self.assertEqual(peers[name], self.JUST_BELOW_THE_LOSS_LIMIT, name)
            self.assertLess(peers[name], 0.02, name)

    def test_free_text_holding_a_host_address_or_a_credential_never_reaches_a_report(self):
        secret = 'dop_v1_' + 'a' * 64
        scrubbed = sr.scrub(dict(reason='token %s and host 203.0.113.10' % secret, nested=[secret]), ('203.0.113.10',))
        self.assertNotIn(secret, json.dumps(scrubbed))
        self.assertNotIn('203.0.113.10', json.dumps(scrubbed))

    def test_the_guard_refuses_every_shape_of_leak_and_names_no_value(self):
        for label, data in (('ipv4', b'host 198.51.100.77 port'), ('ipv6', b'at 2001:db8::77 now'), ('kernel', b'local 0100007F:1F91'), ('path', b'in /home/deploy/omega'), ('fingerprint', b'SHA256:UtC5Y6VWbIrptSdUyOFCyoWWhMPgwO8BeJVVC3nVkMg'), ('assignment', b'api_key=whatever'), ('token', ('dop_v1_' + 'a' * 64).encode()), ('binary', b'\xff\xfe\x00'), ('nul', b'a\x00b')):
            with self.subTest(label):
                problems = ep.guard_problems({'summary.md': data})
                self.assertTrue(problems)
                self.assertNotIn(data.decode('latin-1'), ' '.join(problems))
        self.assertTrue(ep.guard_problems({'summary.md': b'the session value'}, ('session value',)))
        self.assertTrue(ep.guard_problems({'summary.md': b'x' * (ep.MAX_PUBLISHED_BYTES + 1)}))
        self.assertEqual(ep.guard_problems({'summary.md': b'at 2026-10-30T12:33:49+00:00, | ---: | sha256 ' + b'a' * 64 + b' version 1.91.0'}), [])

    def test_a_refused_guard_leaves_no_published_text_and_the_export_says_why(self):
        sim, _ = confirmed_session(self)
        with mock.patch.object(ep, 'guard_problems', return_value=['summary.md holds an IPv4 address']):
            later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.publication_refused, ['summary.md holds an IPv4 address'])
        self.assertFalse((sim.generation(later.generation) / se.PUBLISHED).exists())
        self.assertEqual(sim.document(later.generation)['publication_refused'], later.publication_refused)
        with self.assertRaises(ep.PublicationRefused) as refused:
            ep.publish(sim.root, later.generation, [], '2026-11-05T00:00:00+00:00')
        self.assertEqual(refused.exception.code, 'nothing_to_publish')

    def test_a_raw_path_that_is_not_plainly_a_file_name_is_published_as_a_hash(self):
        secret_path = 'runs/x/game/token=' + ef.SOCKET_MARKER + ' weird.log'
        published = ep.published_path(secret_path)
        self.assertNotIn(ef.SOCKET_MARKER, published)
        self.assertTrue(published.startswith('opaque-path-sha256-'))
        self.assertEqual(ep.published_path('runs/x/game/ticks.csv'), 'runs/x/game/ticks.csv')

    def test_a_guest_file_with_a_hostile_name_is_inventoried_and_not_published_by_name(self):
        def hostile(tree, trial):
            tree.path('game/telemetry/' + ef.ENDPOINT_MARKER + '.log').write_text('x\n')
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=hostile))
        sim.batch()
        top = sim.generation('gen-0001')
        self.assertIn(ef.ENDPOINT_MARKER, (top / se.SUMS_FILE).read_text(), 'the private inventory keeps the real name')
        published = (top / se.PUBLISHED / 'SHA256SUMS').read_text()
        self.assertNotIn(ef.ENDPOINT_MARKER, published, 'it leaves as a hash of its own name, and the rest still goes')
        self.assertIn('opaque-path-sha256-', published)

    def test_a_credential_in_the_registrys_reply_is_not_kept(self):
        client = mock.Mock()
        client.call.side_effect = lambda method, **_: dict(evaluated_at='x', detail='dop_v1_' + 'a' * 64)
        snapshot = se.registry_snapshot(client, 's')
        self.assertIn('unavailable', snapshot)
        self.assertNotIn('dop_v1_', json.dumps(snapshot))

    def test_a_credential_in_a_generated_report_refuses_to_write_it(self):
        sim, _ = confirmed_session(self)
        secret = 'dop_v1_' + 'b' * 64
        with mock.patch.object(sr, 'scrub', side_effect=lambda value, sensitive=(): dict(value, leaked=secret) if isinstance(value, dict) and value.get('schema') == sr.REPORT_SCHEMA else value):
            later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(later.status, 'partial')
        self.assertFalse((sim.generation(later.generation) / se.REPORT_JSON).exists())
        for path in sim.generation(later.generation).rglob('*'):
            if path.is_file():
                self.assertNotIn(secret, path.read_text())


class Publication(unittest.TestCase):
    def canonical(self):
        directory = pathlib.Path(tempfile.mkdtemp(prefix='omega-publication-'))
        self.addCleanup(shutil.rmtree, directory, True)
        root = directory / ep.CANONICAL_ROOT
        root.mkdir(parents=True)
        return root

    def session(self):
        sim, _ = confirmed_session(self)
        return sim

    def test_nothing_is_published_until_someone_publishes_and_a_local_path_never_reads_as_published(self):
        sim = self.session()
        status = ep.publication_status(sim.root)
        self.assertEqual(status['status'], 'not_published')
        self.assertEqual(status['journal_mirror']['status'], 'not_published')
        report = sim.document('gen-0001', 'session-report.json')
        self.assertEqual(report['publication']['status'], 'not_published')
        self.assertIn('Publication: `not_published`', (sim.generation('gen-0001') / se.REPORT_MD).read_text())

    def test_the_canonical_copy_is_text_only_and_is_read_back_before_a_receipt_exists(self):
        sim = self.session()
        root = self.canonical()
        receipts = ep.publish(sim.root, 'gen-0001', [ep.RepositoryDocs(root)], '2026-11-05T00:00:00+00:00', ep.sensitive_values(sim.root, sim.manifest))
        self.assertEqual([item['status'] for item in receipts], ['verified_local'], 'a working tree read back on this machine shows placement and nothing else')
        directory = root / ep.SESSIONS_DIR / sim.session_id / 'gen-0001'
        self.assertEqual(sorted(path.name for path in directory.iterdir()), sorted(ep.PUBLISHED_FILES))
        total = 0
        for path in directory.iterdir():
            total += len(path.read_bytes())
            path.read_bytes().decode('utf-8')
        self.assertLess(total, ep.MAX_PUBLISHED_BYTES)
        for path in directory.iterdir():
            self.assertEqual(sha(path.read_bytes()), receipts[0]['files'][path.name])
        status = ep.publication_status(sim.root)
        self.assertEqual(status['repository']['status'], 'verified_local')
        self.assertEqual(status['repository']['local_reference'], '%s/sessions/%s/gen-0001' % (ep.CANONICAL_ROOT, sim.session_id))
        self.assertEqual(status['publication']['status'], 'unverified')
        self.assertEqual(status['journal_mirror']['status'], 'not_published')
        self.assertIn('never published', status['raw_evidence'])

    def test_the_published_inventory_can_verify_the_raw_files(self):
        sim = self.session()
        summary = sim.document('gen-0001', 'published/summary.json')
        sums = (sim.generation('gen-0001') / 'published' / 'SHA256SUMS').read_bytes()
        self.assertEqual(summary['raw_evidence']['inventory_sha256'], sha(sums))
        self.assertEqual(summary['raw_evidence']['files'], len(sums.splitlines()))
        for line in sums.decode().splitlines():
            digest, path = line.split('  ', 1)
            self.assertEqual(sha((sim.root / path).read_bytes()), digest, path)
        self.assertIn('never published', summary['raw_evidence']['policy'])
        self.assertIn('available on request', summary['raw_evidence']['policy'])
        self.assertIn('single copy', summary['raw_evidence']['policy'])

    def test_published_text_is_never_replaced(self):
        sim = self.session()
        root = self.canonical()
        destination = ep.RepositoryDocs(root)
        ep.publish(sim.root, 'gen-0001', [destination], 'now')
        path = root / ep.SESSIONS_DIR / sim.session_id / 'gen-0001' / 'summary.md'
        path.write_text('someone edited this')
        receipts = ep.publish(sim.root, 'gen-0001', [destination], 'now')
        self.assertEqual(receipts[0]['status'], 'failed')
        self.assertEqual(receipts[0]['code'], 'published_file_differs')
        self.assertEqual(path.read_text(), 'someone edited this')

    def test_only_the_canonical_directory_can_receive_it_so_no_historical_series_can(self):
        for name in ('docs/netcode/perf-notes/hill-climb', 'docs/netcode/perf-notes/load-test-reports/2026-10-13', 'loadtest-runs/digitalocean'):
            with self.subTest(name):
                with self.assertRaises(ep.PublicationRefused) as refused:
                    ep.RepositoryDocs(pathlib.Path('/tmp') / name)
                self.assertEqual(refused.exception.code, 'destination_not_canonical')

    def test_a_manifest_naming_any_other_destination_cannot_be_published(self):
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING), durable_destination='ref:evidence-bucket:omega-do-capacity')
        sim.batch()
        with self.assertRaises(ep.PublicationRefused) as refused:
            ep.publish(sim.root, 'gen-0001', [ep.RepositoryDocs(self.canonical())], 'now')
        self.assertEqual(refused.exception.code, 'destination_not_accepted')

    def test_a_failing_journal_adapter_costs_only_itself_and_a_lying_one_gets_no_receipt(self):
        class Failing:
            name = ep.MIRROR_NAME

            def reference(self, session_id, generation):
                return 'https://marrowtech.app/journal/fake'

            def put(self, session_id, generation, files):
                raise OSError('no route')

            def read_back(self, session_id, generation, name):
                raise AssertionError('never reached')

        class Lying(Failing):
            name = ep.MIRROR_NAME

            def put(self, session_id, generation, files):
                pass

            def read_back(self, session_id, generation, name):
                return b'something else'

        class Honest(Lying):
            name = ep.MIRROR_NAME
            publishes = True

            def __init__(self):
                self.files = {}

            def put(self, session_id, generation, files):
                self.files.update(files)

            def read_back(self, session_id, generation, name):
                return self.files[name]
        sim = self.session()
        receipts = ep.publish(sim.root, 'gen-0001', [Failing(), ep.RepositoryDocs(self.canonical())], 'now')
        self.assertEqual([item['status'] for item in receipts], ['failed', 'verified_local'])
        self.assertEqual(ep.publication_status(sim.root)['journal_mirror']['status'], 'failed')
        receipts = ep.publish(sim.root, 'gen-0001', [Lying()], 'now')
        self.assertEqual((receipts[0]['status'], receipts[0]['code']), ('failed', 'read_back_mismatch'))
        receipts = ep.publish(sim.root, 'gen-0001', [Honest()], 'now')
        self.assertEqual(receipts[0]['status'], 'published')
        self.assertEqual(ep.publication_status(sim.root)['journal_mirror']['status'], 'published')

    def test_the_operators_mirror_record_is_held_to_this_text_and_never_reads_as_checked(self):
        sim = self.session()
        digest = sha((sim.generation('gen-0001') / 'published' / 'summary.md').read_bytes())
        with self.assertRaises(ep.PublicationRefused):
            ep.record_mirror(sim.root, 'gen-0001', 'https://marrowtech.app/journal/x', 'now', '0' * 64)
        with self.assertRaises(ep.PublicationRefused):
            ep.record_mirror(sim.root, 'gen-0001', 'https://example.com/journal/x', 'now', digest)
        record = ep.record_mirror(sim.root, 'gen-0001', 'https://marrowtech.app/journal/x', 'now', digest)
        self.assertEqual(record['status'], 'operator_recorded')
        self.assertFalse(record['checked_by_this_tool'])
        status = ep.publication_status(sim.root)['journal_mirror']
        self.assertEqual((status['status'], status['checked_by_this_tool']), ('operator_recorded', False))

    def test_publication_status_joins_the_next_generation_and_changes_no_earlier_one(self):
        sim = self.session()
        before = tree_bytes(sim.generation('gen-0001'))
        ep.publish(sim.root, 'gen-0001', [ep.RepositoryDocs(self.canonical())], '2026-11-05T00:00:00+00:00')
        later = se.export_session(sim.root, client=sim.client)
        self.assertEqual(sim.document(later.generation, 'session-report.json')['publication']['status'], 'verified_local')
        self.assertEqual(tree_bytes(sim.generation('gen-0001')), before)
        self.assertEqual(se.reproduce(sim.root, 'gen-0001'), [])
        self.assertEqual(se.reproduce(sim.root, later.generation), [])

    def test_publishing_an_incomplete_session_keeps_its_label(self):
        def drop(tree, trial):
            tree.path('game/sockets.ndjson').unlink()
        sim = ef.ExportSim(self, ef.enriched(ef.CONFIRMING, extra=drop))
        sim.batch()
        ep.publish(sim.root, 'gen-0001', [ep.RepositoryDocs(self.canonical())], 'now')
        summary = sim.document('gen-0001', 'published/summary.json')
        self.assertEqual(summary['results']['evidence']['status'], 'partial')
        self.assertFalse(summary['establishes'])
        self.assertFalse(summary['results']['measurement']['claim']['confirmed'])
        self.assertGreater(summary['runs'][0]['required_files_absent'], 0)

    def test_publication_opens_no_connection_and_names_no_historical_series(self):
        source = pathlib.Path(ep.__file__).read_text() + pathlib.Path(se.__file__).read_text()
        self.assertNotIn('hill-climb/', source)
        for forbidden in ('urllib', 'http.client', 'socket', 'requests', 'subprocess'):
            self.assertNotIn('import ' + forbidden, pathlib.Path(ep.__file__).read_text())


class CommandLine(unittest.TestCase):
    def out(self, *arguments):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = se.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_export_verify_reproduce_and_a_refused_publish(self):
        sim, _ = confirmed_session(self)
        root = str(sim.root)
        code, out, _ = self.out('export', '--session-dir', root)
        result = json.loads(out)
        self.assertEqual((code, result['generation'], result['status']), (0, 'gen-0002', 'complete'))
        self.assertFalse(sim.document('gen-0002', 'session-report.json')['results']['cleanup']['known'], 'with no registry, nothing is said about the resources')
        self.assertEqual(self.out('verify', '--session-dir', root)[0], 0)
        self.assertEqual(self.out('reproduce', '--session-dir', root)[0], 0)
        code, _, err = self.out('prepare-publication', '--session-dir', root, '--now', 'now', '--docs-root', '/tmp/not-canonical')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['code'], 'destination_not_canonical')

    def test_publish_and_record_through_the_command_line(self):
        sim, _ = confirmed_session(self)
        directory = pathlib.Path(tempfile.mkdtemp(prefix='omega-publication-'))
        self.addCleanup(shutil.rmtree, directory, True)
        code, out, _ = self.out('prepare-publication', '--session-dir', str(sim.root), '--now', 'now', '--repository', str(directory))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['status']['status'], 'verified_local', 'no commit and no remote: this is placement')
        self.assertTrue((directory / ep.CANONICAL_ROOT / 'sessions' / sim.session_id / 'gen-0001' / 'summary.md').exists())
        digest = sha((sim.generation('gen-0001') / 'published' / 'summary.md').read_bytes())
        reference = 'https://github.com/example/repository/tree/%s/%s/sessions/%s/gen-0001' % ('a' * 40, ep.CANONICAL_ROOT, sim.session_id)
        self.assertEqual(self.out('record-publication', '--session-dir', str(sim.root), '--generation', 'gen-0001', '--reference', reference, '--summary-sha256', digest, '--operator', 'the operator', '--now', 'now')[0], 0)
        self.assertEqual(ep.publication_status(sim.root)['status'], 'operator_recorded')
        self.assertEqual(self.out('record-journal', '--session-dir', str(sim.root), '--generation', 'gen-0001', '--url', 'https://marrowtech.app/journal/x', '--summary-sha256', digest, '--now', 'now')[0], 0)
        self.assertEqual(self.out('record-invoice', '--session-dir', str(sim.root), '--period', '2026-11', '--amount-usd', '1', '--source', 'hand', '--now', 'now')[0], 0)

    def test_an_export_with_no_session_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            code, out, _ = self.out('export', '--session-dir', directory)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)['status'], 'corrupt')
            self.assertEqual(self.out('verify', '--session-dir', str(pathlib.Path(directory) / 'nothing'))[0], 1)


if __name__ == '__main__':
    unittest.main()
