"""The integrated offline fault battery (issue #71): it regenerates byte for byte, every check and invariant holds on what was observed, every requirement is covered, and the checks fail when the code under them is broken."""
import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

import do_api
import evidence_publication as ep
import export_fixtures as ef
import fault_battery as fb
import registry
import run_executor

RETAINED = pathlib.Path(__file__).parents[2] / 'docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice8'
GENERATED = ('synthetic-battery.json',)


def document():
    return json.loads((RETAINED / 'synthetic-battery.json').read_text())


def scenarios():
    return document()['scenarios']


def sessions(name):
    return scenarios()[name]['sessions']


def main_session(name):
    return sessions(name)[0]


class RetainedBattery(unittest.TestCase):
    def sums(self):
        return {line.split('  ', 1)[1]: line.split()[0] for line in (RETAINED / 'SHA256SUMS').read_text().splitlines()}

    def test_it_regenerates_exactly(self):
        root = tempfile.mkdtemp(prefix='omega-fault-battery-')
        self.addCleanup(shutil.rmtree, root, True)
        real = RETAINED / 'real-process.json'
        fb.generate(root, real if real.exists() else None)
        self.assertEqual((pathlib.Path(root) / 'SHA256SUMS').read_text(), (RETAINED / 'SHA256SUMS').read_text())

    def test_every_retained_file_is_inventoried_and_matches(self):
        kept = {str(path.relative_to(RETAINED)) for path in RETAINED.rglob('*') if path.is_file()}
        self.assertEqual(kept - {'SHA256SUMS', 'README.md', 'real-process.json'}, set(GENERATED))
        self.assertEqual(set(self.sums()), set(GENERATED) | ({'real-process.json'} & kept))
        for name, digest in self.sums().items():
            self.assertEqual(hashlib.sha256((RETAINED / name).read_bytes()).hexdigest(), digest, name)

    def test_it_says_what_it_is_and_keeps_no_raw_evidence(self):
        data = document()
        self.assertEqual((data['schema'], data['kind']), (fb.SCHEMA, 'synthetic'))
        self.assertIn('Nothing ran on any host', data['note'])
        readme = (RETAINED / 'README.md').read_text()
        self.assertIn('Not live-host validation and not a capacity finding', readme)
        for path in RETAINED.rglob('*'):
            if path.is_file():
                self.assertLess(path.stat().st_size, ep.MAX_PUBLISHED_BYTES, path.name)
                self.assertFalse(path.name.endswith(('.csv', '.ndjson', '.log', '.partial')), path.name)
                text = path.read_text()
                for marker in (ef.SOCKET_MARKER, ef.ENDPOINT_MARKER, ef.KERNEL_ENDPOINT_MARKER, '/var/folders/', '/private/tmp/', 'BEGIN OPENSSH'):
                    self.assertNotIn(marker, text, path.name)

    def test_the_retained_scenarios_are_the_battery(self):
        self.assertEqual(sorted(scenarios()), sorted(play.__name__ for play, _ in fb.SCENARIOS))


class WhatWasObserved(unittest.TestCase):
    def test_every_check_and_every_invariant_held(self):
        for name, row in scenarios().items():
            self.assertTrue(row['checks'], name + ' asserts nothing')
            self.assertEqual([label for label, ok in row['checks'].items() if not ok], [], name)
            for item in row['sessions']:
                self.assertEqual(sorted(item['invariants']), sorted(fb.INVARIANTS), name)
                self.assertEqual([key for key, ok in item['invariants'].items() if not ok], [], name + '/' + item['label'])

    def test_every_requirement_is_covered_by_a_scenario_that_names_it(self):
        listed = {item['key']: item for item in document()['requirements']}
        self.assertEqual(list(listed), list(fb.REQUIREMENTS))
        for key, item in listed.items():
            self.assertTrue(item['scenarios'], key)
            for name in item['scenarios']:
                self.assertIn(key, scenarios()[name]['requirements'])

    def test_rejected_admission_and_an_unacknowledged_watchdog_touch_no_provider_state(self):
        for name in ('admission_rejected_creates_nothing', 'unacknowledged_watchdog_creates_nothing'):
            row = scenarios()[name]
            self.assertEqual(row['provider']['mutations'], [], name)
            self.assertIsNone(main_session(name)['armed'], name)
            self.assertEqual(main_session(name)['overall'], 'closed_never_armed', name)
        self.assertGreater(len(scenarios()['baseline_confirmed_then_verified_absence']['provider']['mutations']), 0, 'the positive control did mutate')

    def test_faults_change_what_the_control_shows_only_where_they_should(self):
        control = main_session('baseline_confirmed_then_verified_absence')
        lost = scenarios()['lost_acknowledgement_and_lost_create_then_confirmed']
        self.assertTrue(any(item[-1] == 'lost' for item in lost['provider']['mutations']))
        self.assertFalse(any(item[-1] for item in scenarios()['baseline_confirmed_then_verified_absence']['provider']['mutations']))
        creates = lambda row: sum(item[2] for item in row['provider']['mutations'] if item[3:5] == ['POST', '/v2/droplets'])   # noqa: E731
        self.assertEqual(creates(lost), creates(scenarios()['baseline_confirmed_then_verified_absence']), 'a lost answer adds no request')
        self.assertEqual([r['outcome'] for r in lost['sessions'][0]['runs']], [r['outcome'] for r in control['runs']])
        self.assertEqual(lost['sessions'][0]['overall'], control['overall'])

    def test_the_watchdog_alone_deletes_by_c(self):
        for name in ('controller_and_laptop_vanish_mid_run', 'changed_checkout_returns_and_c_still_arrives'):
            row = main_session(name)
            self.assertEqual(row['cleanup']['reason'], 'deadline_C', name)
            first_delete = min(item[0] for item in scenarios()[name]['provider']['mutations'] if item[3] == 'DELETE')
            self.assertLessEqual(first_delete, row['c_s'], name)
            self.assertLessEqual(row['cleanup']['verified_s'], row['d_s'], name)
        self.assertNotEqual(main_session('baseline_confirmed_then_verified_absence')['cleanup']['reason'], 'deadline_C')

    def test_one_session_failing_does_not_slow_another(self):
        control = main_session('baseline_confirmed_then_verified_absence')['cleanup']
        main, sibling = sessions('fairness_rate_limits_and_a_deletion_outage')
        self.assertEqual(main['cleanup']['verified_s'] - main['cleanup']['requested_s'], control['verified_s'] - control['requested_s'])
        self.assertEqual(main['overall'], 'clean')
        self.assertTrue(sibling['cleanup']['overdue'])
        self.assertLessEqual(sibling['attempts']['max_burst_attempt'], 6)
        self.assertLessEqual(sibling['attempts']['max_per_resource_sweep'], 6)
        self.assertIn('get_droplet 429', sibling['attempts']['errors'])
        self.assertIn('delete_droplet 503', sibling['attempts']['errors'])
        self.assertIn('cleanup-overdue', [item['kind'] for item in sibling['incidents']])

    def test_only_complete_evidence_of_a_confirmed_search_establishes_anything(self):
        for name, row in scenarios().items():
            for item in row['sessions']:
                if item.get('establishes'):
                    self.assertEqual((item['export_status'], item['search_status']), ('complete', 'confirmed'), name)
                if item.get('overall') == 'clean':
                    self.assertEqual(item['evidence'], 'complete', name)
                    self.assertEqual(item['owned_at_end'], dict(droplets=[], firewalls=[], tags=[]), name)

    def test_measurement_evidence_and_cleanup_stay_independent(self):
        """The same three fields take every combination the faults produce; none is derived from another."""
        seen = {(item.get('measurement'), item.get('evidence'), item.get('overall')) for row in scenarios().values() for item in row['sessions']}
        self.assertIn(('confirmed', 'complete', 'cleanup_not_verified'), seen, 'a confirmed, complete session can still be open')
        self.assertIn(('stopped_inconclusive_evidence', 'complete', 'clean'), seen, 'clean says nothing about what was measured')
        self.assertTrue(any(m == 'operator_collect' and e != 'complete' for m, e, _ in seen))
        self.assertIn((None, 'unknown', 'resources_verified_with_operator_disposition'), seen)

    def test_deadlines_never_moved_through_restarts_reboots_and_clock_steps(self):
        for name in ('watchdog_restart_and_reboot_keep_the_deadline', 'reboot_with_untrusted_clock_fails_closed', 'failed_transfer_crash_and_late_return_end_the_episode', 'lost_acknowledgement_and_lost_create_then_confirmed'):
            row = main_session(name)
            self.assertEqual(row['armed'], dict(t0=row['t0_s'], c=row['c_s'], d=row['d_s']), name)
            self.assertEqual(row['d_s'] - row['t0_s'], fb.pf.CAP_S, name)


class ChecksFailOnBrokenCode(unittest.TestCase):
    """Negative controls: break one production behaviour at its real seam and the battery's own checks must notice. Nothing here is retained."""

    def play(self, play):
        """Failed checks and invariants. A scenario that cannot even reach its end, for example a session that never closes in scripted time, is reported as such."""
        case = fb._Case()
        holder, checks = {}, {}
        broken = []
        try:
            with fb.named_requests():
                observed = play(case, holder, fb.checker(checks))
                broken = [key for obs in observed for key, ok in obs.row()['invariants'].items() if not ok]
        except AssertionError as error:
            broken.append('stopped: ' + str(error).split(':')[0])
        finally:
            case.doCleanups()
        return [label for label, ok in checks.items() if not ok], broken

    def assert_noticed(self, play, *expected):
        failed, broken = self.play(play)
        self.assertTrue(failed or broken, 'the broken behaviour went unnoticed')
        for label in expected:
            self.assertIn(label, failed + broken)

    def test_an_accepted_delete_read_as_absence_is_caught(self):
        """An adapter that hides a Droplet once its delete was accepted, from both the exact read and the tag listing."""
        get, listing = do_api.DigitalOceanProvider.get_droplet, do_api.DigitalOceanProvider.list_droplets_by_tag

        def deleting(provider):
            return {str(i) for i, d in provider.transport.droplets.items() if d.get('_deleting')}

        def lying_get(provider, droplet_id):
            return None if str(droplet_id) in deleting(provider) else get(provider, droplet_id)

        def lying_list(provider, tag):
            return [d for d in listing(provider, tag) if str(d['id']) not in deleting(provider)]
        with mock.patch.object(do_api.DigitalOceanProvider, 'get_droplet', lying_get), mock.patch.object(do_api.DigitalOceanProvider, 'list_droplets_by_tag', lying_list):
            self.assert_noticed(fb.accepted_delete_lingers_beside_corrupt_evidence, 'no Droplet the account still listed was recorded absent')

    def test_an_unresolved_create_settled_by_elapsed_time_is_caught(self):
        with mock.patch.object(registry.Registry, 'unresolved_creates', lambda self, session_id: []):
            self.assert_noticed(fb.unknown_create_overdue_then_operator_disposition)

    def test_a_controller_that_skips_its_source_check_is_caught(self):
        with mock.patch.object(run_executor.RunExecutor, '_require_frozen_source', lambda self: None):
            self.assert_noticed(fb.changed_checkout_returns_and_c_still_arrives, 'resume refused on the source, with no batch run')

    def test_a_verdict_that_passes_a_gap_is_caught(self):
        """The prover, the scorer's socket gate and the executor's check of the scorer each refuse the missing counter on their own: breaking only the gate or only the scorer changes nothing. So this replaces the run's verdict as a whole."""
        def passing(executor, context, execution):
            return dict(outcome=fb.search.PASS, reasons=['sabotage: a gap read as zero'], scored=True, evidence_ref=execution['ref'], scorer='capacity_scorer')
        with mock.patch.object(run_executor.RunExecutor, '_classify', passing):
            self.assert_noticed(fb.socket_gap_is_inconclusive, 'inconclusive, not a pass or a capacity failure')


if __name__ == '__main__':
    unittest.main()
