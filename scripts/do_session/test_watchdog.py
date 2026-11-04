"""Independent deadline-driven cleanup: lost controllers, outages, ownership, clocks and fairness."""
import json
import logging
import shutil
import sqlite3
import time
import unittest

import cleanup_ledger
import cleanup_provider
import fake_provider
import fixture_support as fx
import registry
import registry_client
import registry_fixtures as rf
import session_clock
import watchdog

SESSION = 'do-cap-1v1g-20261030a'


def run_to(stack, epoch):
    """Tick in real scheduling order up to an absolute effective time."""
    while stack.clock.wall_value < epoch:
        stack.step(min(1.0, epoch - stack.clock.wall_value), min(1.0, epoch - stack.clock.wall_value))


def deadlines(stack, session_id=SESSION):
    status = stack.registry.status(session_id)
    return status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc']


class IndependentCleanupTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)

    def provider_mutations(self):
        return self.stack.provider.ops_named('delete_droplet', 'delete_firewall', 'delete_tag')

    def test_lost_controller_still_deletes_starting_by_c(self):
        _, _, _, ack, ids = self.stack.ready(SESSION)
        c = session_clock.parse(ack['cleanup_c_utc'])
        # The controller is never heard from again: no renewal, no cleanup request, no SSH.
        self.stack.client = None
        run_to(self.stack, c - registry.CLEANUP_LEAD_S - 1)
        self.assertEqual(self.stack.provider.ops, [], 'no provider call before cleanup starts')
        self.assertNotEqual(self.stack.registry.status(SESSION)['state'], registry.DELETING)
        run_to(self.stack, c)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['reason'], 'deadline_C')
        self.assertLessEqual(session_clock.parse(status['cleanup']['requested_at']), c)
        first_delete = self.provider_mutations()[0]
        self.assertEqual(first_delete['op'], 'delete_droplet')
        self.assertLessEqual(first_delete['at'], c, 'the first delete was issued by C')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual(status['evidence']['status'], 'unknown', 'lost evidence stays visibly unknown')
        self.assertEqual(status['overall'], 'resources_verified_evidence_incomplete')
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]))
        self.assertLess(self.stack.clock.wall_value, session_clock.parse(ack['deadline_d_utc']), 'verified before D')
        self.assertEqual(status['incidents'], [])

    def test_cleanup_intent_is_durable_before_any_delete(self):
        _, _, token, _, _ = self.stack.ready(SESSION)
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        journal = self.stack.registry.journal(SESSION)
        intent = next(e['seq'] for e in journal if e['kind'] == 'cleanup_intent')
        accepted = next(e['seq'] for e in journal if e['kind'] == 'delete_accepted')
        self.assertLess(intent, accepted)

    def test_successful_session_is_deleted_promptly_not_held_to_the_cap(self):
        _, _, token, ack, _ = self.stack.ready(SESSION)
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='batch finished')
        elapsed = self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertLessEqual(elapsed, 120, 'a healthy cleanup fits inside the default teardown reserve')
        self.assertLess(self.stack.clock.wall_value, session_clock.parse(ack['cleanup_c_utc']))
        receipt = json.loads((self.stack.state_dir / registry.RECEIPT_DIR / (SESSION + '.closure-1.json')).read_text())
        self.assertEqual(receipt['cleanup_outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual({d['status'] for d in receipt['dispositions']}, {'absent'})
        self.assertEqual(len(receipt['dispositions']), 6, 'three tags, one firewall, two Droplets')

    def test_ordering_is_droplets_then_firewall_then_tags(self):
        _, _, token, _, _ = self.stack.ready(SESSION)
        self.stack.provider.linger_reads = 2
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        ops = [o['op'] for o in self.stack.provider.ops]
        self.assertLess(max(i for i, o in enumerate(ops) if o == 'delete_droplet'), ops.index('delete_firewall'))
        self.assertLess(ops.index('delete_firewall'), ops.index('delete_tag'))
        journal = self.stack.registry.journal(SESSION)
        verified = [e['seq'] for e in journal if e['kind'] == 'verified_absent' and e['data']['resource_key'].startswith('droplet:')]
        accepted_fw = next(e['seq'] for e in journal if e['kind'] == 'delete_accepted' and e['data']['resource_key'].startswith('firewall:'))
        self.assertLess(max(verified), accepted_fw, 'firewall stays until Droplets are verified absent')

    def test_accepted_delete_is_not_proof_of_destruction(self):
        _, _, token, _, ids = self.stack.ready(SESSION)
        self.stack.provider.linger_reads = 8
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        self.stack.step(20)
        status = self.stack.registry.status(SESSION)
        game = next(r for r in status['resources'] if r['resource_key'] == ids['game'])
        self.assertEqual(game['status'], 'delete_accepted')
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['outcome'], 'in_progress')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        accepted = [e for e in self.stack.registry.journal(SESSION) if e['kind'] == 'delete_accepted'
                    and e['data']['resource_key'] == ids['game']]
        self.assertGreaterEqual(len(accepted), 2, 'a Droplet that lingers past the window is deleted again')

    def test_failed_read_is_not_proof_of_absence(self):
        _, _, token, _, ids = self.stack.ready(SESSION)
        self.stack.provider.fail(rf.outage, op='get_droplet')
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        self.stack.step(180)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual({r['status'] for r in status['resources'] if r['kind'] == 'droplet'}, {'unverified'})

    def test_watchdog_interface_cannot_reach_shared_resources(self):
        forbidden = [name for name in dir(cleanup_provider.CleanupProvider)
                     if not name.startswith('_') and ('create' in name or 'key' in name or 'project' in name or 'image' in name)]
        self.assertEqual(forbidden, [])

    def test_unarmed_sessions_are_not_touched(self):
        self.stack.registered(SESSION)
        self.stack.step(60)
        self.assertEqual(self.stack.provider.ops, [])
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.REGISTERED)


class ReconcileCadenceTests(unittest.TestCase):
    def test_sweeps_every_15_seconds_while_a_session_is_being_deleted(self):
        stack = rf.Stack(self)
        stack.ready(SESSION)
        stack.registry.operator_abort(SESSION, 'test')
        stack.provider.fail(rf.outage, op='list_droplets_by_tag')
        before = stack.registry.watchdog_view()['sweep_seq']
        sweep_times = []
        for _ in range(61):
            stack.step(1)
            view = stack.registry.watchdog_view()
            if view['sweep_seq'] != before:
                before = view['sweep_seq']
                sweep_times.append(session_clock.parse(view['last_sweep_at']))
        gaps = {round(b - a, 3) for a, b in zip(sweep_times, sweep_times[1:])}
        self.assertEqual(gaps, {15.0})
        self.assertGreaterEqual(len(sweep_times), 4)

    def test_restart_reconciles_immediately_and_reads_the_persisted_deadline(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION)
        original = deadlines(stack)
        stack.clock.advance(session_clock.parse(ack['cleanup_c_utc']) - stack.clock.wall_value + 5)
        watchdog_after = stack.restart_watchdog()
        watchdog_after.tick()
        status = stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertTrue(stack.provider.ops, 'the first tick after restart already reached the provider')
        self.assertEqual(deadlines(stack), original)

    def test_reboot_recovers_pending_cleanup_and_overdue_state(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION)
        original = deadlines(stack)
        d = session_clock.parse(ack['deadline_d_utc'])
        stack.restart_watchdog(reboot=True, downtime_s=d - stack.clock.wall_value + 30)
        stack.watchdog.tick()
        status = stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertTrue(status['cleanup']['overdue'], 'host was down across D: immediately overdue on boot')
        self.assertEqual(deadlines(stack), original)
        stack.run_until(lambda: stack.closed(SESSION))
        self.assertGreater(stack.registry.status(SESSION)['cleanup']['overrun_s'], 30)

    def test_state_directory_can_move_to_another_host_unchanged(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION)
        original = deadlines(stack)
        moved = stack.copy_state_to(stack.root / 'other-host-state')
        clock = fx.ScriptedClock(wall=stack.clock.wall_value + 40, mono=3.0, boot='other-host-boot')
        reg = registry.Registry(moved, clock=clock)
        self.addCleanup(reg.close)
        service = watchdog.Watchdog(reg, stack.provider, executor=watchdog.InlineExecutor())
        service.start(pid=9)
        self.assertEqual(deadlines(type('S', (), dict(registry=reg))), original)
        c = session_clock.parse(ack['cleanup_c_utc'])
        clock.wall_value, clock.mono_value = c + 1, 3.0 + c + 1 - (stack.clock.wall_value + 40)
        for _ in range(120):
            clock.advance(1)
            service.tick()
        self.assertEqual(reg.status(SESSION)['state'], registry.CLOSED)
        self.assertEqual(reg.status(SESSION)['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_second_watchdog_on_one_state_directory_refuses(self):
        stack = rf.Stack(self)
        stack.watchdog.acquire_lock()
        self.addCleanup(stack.watchdog.release_lock)
        second = stack.new_watchdog()
        with self.assertRaises(watchdog.WatchdogAlreadyRunning):
            second.acquire_lock()


class RetryBurstTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        _, _, self.token, self.ack, self.ids = self.stack.ready(SESSION)

    def abort(self):
        self.stack.registry.operator_abort(SESSION, 'test')

    def attempts_by_burst(self, key):
        bursts = {}
        for attempt in self.stack.registry.attempts(SESSION, key):
            bursts.setdefault(attempt['sweep_seq'], []).append(attempt)
        return bursts

    def test_six_attempts_with_exponential_backoff_capped_at_30_seconds(self):
        self.stack.provider.fail(rf.outage, op='get_droplet')
        self.abort()
        self.stack.step(70)
        bursts = self.attempts_by_burst(self.ids['game'])
        first = bursts[min(bursts)]
        self.assertEqual(len(first), 6)
        self.assertEqual([a['burst_attempt'] for a in first], [1, 2, 3, 4, 5, 6])
        started = [session_clock.parse(a['started_at']) for a in first]
        self.assertEqual([b - a for a, b in zip(started, started[1:])], [2.0, 4.0, 8.0, 16.0, 30.0])

    def test_no_burst_ever_exceeds_six_and_sweeps_continue_without_a_cutoff(self):
        self.stack.provider.fail(rf.outage)
        self.abort()
        self.stack.step(1800)
        for key in (self.ids['game'], self.ids['bot']):
            bursts = self.attempts_by_burst(key)
            self.assertGreater(len(bursts), 20, 'retries continue indefinitely across sweeps')
            self.assertLessEqual(max(len(a) for a in bursts.values()), 6)
            self.assertEqual({a['result'] for b in bursts.values() for a in b}, {'error'})

    def test_bursts_never_overlap_across_sweeps(self):
        self.stack.provider.fail(rf.outage, op='get_droplet')
        self.abort()
        self.stack.step(300)
        windows = []
        for attempts in self.attempts_by_burst(self.ids['game']).values():
            windows.append((session_clock.parse(attempts[0]['started_at']), session_clock.parse(attempts[-1]['finished_at'])))
        for (_, end), (next_start, _) in zip(windows, windows[1:]):
            self.assertGreaterEqual(next_start, end)

    def test_restart_mid_burst_continues_it_without_more_attempts(self):
        self.stack.provider.fail(rf.outage, op='get_droplet')
        self.abort()
        self.stack.step(10)
        before = self.stack.registry.resources(SESSION)
        game = next(r for r in before if r['resource_key'] == self.ids['game'])
        self.assertEqual(game['burst_state'], 'active')
        self.stack.restart_watchdog()
        self.stack.step(60)
        first = self.attempts_by_burst(self.ids['game'])[game['burst_sweep']]
        self.assertEqual(len(first), 6, 'the restart resumed the same burst and did not stack another')

    def test_a_crash_loop_cannot_buy_extra_attempts(self):
        self.stack.provider.fail(rf.outage, op='get_droplet')
        self.abort()
        started = self.stack.clock.wall_value
        for _ in range(40):
            self.stack.step(1.5, 1.5)
            self.stack.restart_watchdog()
        elapsed = self.stack.clock.wall_value - started
        attempts = self.stack.registry.attempts(SESSION, self.ids['game'])
        allowed = 6 * (elapsed / cleanup_ledger.SWEEP_INTERVAL_S + 1)
        self.assertLessEqual(len(attempts), allowed)
        # Backoff is persisted too: the requests inside a burst still respect their spacing.
        for attempts_in_burst in self.attempts_by_burst(self.ids['game']).values():
            self.assertLessEqual(len(attempts_in_burst), 6)

    def test_request_outstanding_at_restart_is_recorded_interrupted_and_counted(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        _, _, _, _, ids = stack.ready(SESSION)
        stack.registry.operator_abort(SESSION, 'test')
        stack.watchdog.tick()
        self.assertTrue(executor.pending)
        stack.restart_watchdog()
        attempts = stack.registry.attempts(SESSION)
        self.assertTrue(any(a['result'] == 'interrupted' for a in attempts))
        self.assertTrue(all(a['finished_at'] for a in attempts))
        self.assertEqual(stack.registry.resources(SESSION)[0]['in_flight_attempt'], None)

    def test_hung_request_is_bounded_and_its_late_result_ignored(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor, request_deadline_s=35.0)
        stack.ready(SESSION)
        stack.registry.operator_abort(SESSION, 'test')
        stack.watchdog.tick()
        first_batch = list(executor.pending)
        stack.step(36)
        attempts = stack.registry.attempts(SESSION)
        expired = [a for a in attempts if a['message'] == 'request exceeded its deadline']
        self.assertEqual(len(expired), len(first_batch))
        self.assertTrue(all(a['error_class'] == 'ProviderTransient' for a in expired))
        executor.release()
        stack.watchdog.tick()
        for attempt in stack.registry.attempts(SESSION):
            if attempt['attempt_id'] in {a['attempt_id'] for a in expired}:
                self.assertEqual(attempt['result'], 'error', 'a late success cannot rewrite the expired attempt')

    def test_rate_limit_guidance_holds_every_request_and_survives_restart(self):
        self.stack.provider.fail(lambda: cleanup_provider.ProviderRateLimited('429', status=429, retry_after_s=120), times=1)
        self.abort()
        self.stack.watchdog.tick()
        requests_before_hold = len(self.stack.provider.ops)
        hold = self.stack.registry.watchdog_view()['rate_limit_hold_until']
        self.assertEqual(session_clock.parse(hold) - self.stack.registry.peek_now(), 120)
        self.stack.step(60)
        self.stack.restart_watchdog()
        self.stack.step(58)
        self.assertEqual(len(self.stack.provider.ops), requests_before_hold,
                         'no request of any session during the hold, even after a restart')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.registry.status(SESSION)['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_rate_limit_without_guidance_uses_a_bounded_default_hold(self):
        self.stack.provider.fail(lambda: cleanup_provider.ProviderRateLimited('429', status=429), times=1)
        self.abort()
        self.stack.watchdog.tick()
        hold = self.stack.registry.watchdog_view()['rate_limit_hold_until']
        self.assertEqual(session_clock.parse(hold) - self.stack.registry.peek_now(), cleanup_ledger.DEFAULT_RATE_LIMIT_HOLD_S)

    def test_absurd_retry_after_is_capped_so_deletion_cannot_stall_forever(self):
        self.stack.provider.fail(lambda: cleanup_provider.ProviderRateLimited('429', status=429, retry_after_s=10**9), times=1)
        self.abort()
        self.stack.watchdog.tick()
        hold = self.stack.registry.watchdog_view()['rate_limit_hold_until']
        self.assertEqual(session_clock.parse(hold) - self.stack.registry.peek_now(), cleanup_ledger.MAX_RATE_LIMIT_HOLD_S)

    def test_auth_failure_is_an_incident_that_needs_repair_never_a_success(self):
        rule = self.stack.provider.fail(rf.auth_failure)
        self.abort()
        self.stack.step(45)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['outcome'], 'in_progress')
        auth = [i for i in status['incidents'] if i['kind'] == 'provider-auth']
        self.assertEqual(len(auth), 1)
        self.assertEqual(auth[0]['status'], 'open')
        for bursts in self.attempts_by_burst(self.ids['game']).values():
            self.assertEqual(len(bursts), 1, 'no pointless in-burst retry against a rejected credential')
        self.assertTrue(len(self.attempts_by_burst(self.ids['game'])) >= 3, 'later sweeps keep trying after repair')
        self.stack.provider.faults.remove(rule)
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        final = self.stack.registry.status(SESSION)
        self.assertEqual([i['status'] for i in final['incidents'] if i['kind'] == 'provider-auth'], ['resolved'])
        self.assertEqual(final['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_unexpected_adapter_exception_is_a_failed_attempt_not_a_dead_watchdog(self):
        self.stack.provider.fail(lambda: KeyError('malformed provider response'), times=3)
        self.abort()
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertTrue(any(a['error_class'] == 'KeyError' for a in self.stack.registry.attempts(SESSION)))


class OverdueTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        _, _, _, self.ack, self.ids = self.stack.ready(SESSION)
        self.c = session_clock.parse(self.ack['cleanup_c_utc'])
        self.d = session_clock.parse(self.ack['deadline_d_utc'])

    def overdue(self):
        return [i for i in self.stack.registry.incidents(SESSION) if i['kind'] == 'cleanup-overdue']

    def test_api_outage_creates_a_persistent_incident_exactly_at_d(self):
        self.stack.provider.fail(lambda: cleanup_provider.ProviderTransient(
            '503 from gateway Authorization: Bearer ' + 'a' * 40 + ' token=' + 'dop_v1_' + 'b' * 64, status=503))
        with self.assertLogs('omega.do_watchdog', level=logging.ERROR) as logs:
            run_to(self.stack, self.d - 1)
            self.assertEqual(self.overdue(), [])
            run_to(self.stack, self.d)
            self.assertEqual(len(self.overdue()), 1)
        self.assertTrue(any('cleanup-overdue' in line for line in logs.output))
        path = next((self.stack.state_dir / registry.INCIDENT_DIR).glob('*cleanup-overdue.json'))
        incident = json.loads(path.read_text())
        self.assertEqual(incident['session_id'], SESSION)
        self.assertEqual(incident['deadline_d_utc'], self.ack['deadline_d_utc'])
        self.assertEqual(sorted(r['resource_key'] for r in incident['resources'] if r['kind'] == 'droplet'),
                         sorted([self.ids['game'], self.ids['bot']]))
        self.assertIn(self.ids['game'], incident['unverified_resource_keys'])
        self.assertGreater(incident['attempt_total'], 0)
        self.assertTrue(incident['recent_attempts'])
        self.assertIn('503', incident['last_error'])
        self.assertTrue(any(self.ids['game'].split(':')[1] in c for c in incident['remediation']))
        raw = self.stack.state_bytes()
        self.assertNotIn(b'dop_v1_', raw, 'provider error text is redacted before anything is stored')
        self.assertNotIn(b'Bearer ' + b'a' * 40, raw)

    def test_incident_survives_restart_and_recovery_records_actual_overrun(self):
        rule = self.stack.provider.fail(rf.outage)
        run_to(self.stack, self.d + 30)
        self.stack.restart_watchdog()
        self.stack.step(30)
        self.assertEqual(len(self.overdue()), 1, 'a restart neither loses nor duplicates the incident')
        self.assertEqual(self.overdue()[0]['status'], 'open')
        self.assertEqual(self.stack.registry.status(SESSION)['overall'], 'cleanup_overdue')
        self.stack.provider.faults.remove(rule)
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        final = self.stack.registry.status(SESSION)
        self.assertEqual(final['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertGreaterEqual(final['cleanup']['overrun_s'], 60)
        incident = self.overdue()[0]
        self.assertEqual(incident['status'], 'resolved')
        self.assertEqual(incident['overrun_s'], final['cleanup']['overrun_s'])
        self.assertEqual(final['overall'], 'resources_verified_evidence_incomplete')
        self.assertTrue(final['cleanup']['overdue'], 'the breach stays visible after eventual cleanup')
        path = next((self.stack.state_dir / registry.INCIDENT_DIR).glob('*cleanup-overdue.json'))
        self.assertEqual(json.loads(path.read_text())['status'], 'resolved')

    def test_overdue_fires_even_while_every_provider_call_hangs(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        _, _, _, ack, _ = stack.ready(SESSION)
        run_to(stack, session_clock.parse(ack['deadline_d_utc']))
        kinds = [i['kind'] for i in stack.registry.incidents(SESSION)]
        self.assertIn('cleanup-overdue', kinds)

    def test_overdue_fires_during_a_rate_limit_hold(self):
        self.stack.provider.fail(lambda: cleanup_provider.ProviderRateLimited('429', status=429, retry_after_s=3600))
        run_to(self.stack, self.d)
        self.assertEqual(len(self.overdue()), 1)

    def test_incident_file_write_failure_is_retried_and_registry_stays_authoritative(self):
        self.stack.provider.fail(rf.outage)
        directory = self.stack.state_dir / registry.INCIDENT_DIR
        shutil.rmtree(directory)
        with self.assertLogs('omega.do_watchdog', level=logging.ERROR):
            run_to(self.stack, self.d)
        self.assertEqual(len(self.overdue()), 1)
        directory.mkdir()
        self.stack.step(1)
        self.assertTrue(list(directory.glob('*cleanup-overdue.json')))


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)

    def ready_and_abort(self):
        result = self.stack.ready(SESSION)
        return result

    def test_wrong_owner_is_refused_with_an_incident_and_blocks_a_clean_closure(self):
        _, _, token, _, ids = self.ready_and_abort()
        droplet_id = ids['game'].split(':')[1]
        self.stack.provider.data['droplets'][droplet_id]['tags'] = ['someone-elses-tag']
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(200)
        self.assertIn(droplet_id, self.stack.provider.live_ids()['droplets'])
        self.assertFalse([o for o in self.stack.provider.ops_named('delete_droplet') if o['target'] == droplet_id])
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        mismatch = [i for i in status['incidents'] if i['kind'] == 'ownership-mismatch']
        self.assertEqual(len(mismatch), 1)
        self.assertIn('unique session tag', mismatch[0]['last_error'])
        self.assertEqual(mismatch[0]['detail']['resource_key'], ids['game'])

    def test_operator_disposition_allows_closure_labelled_as_not_clean(self):
        _, _, _, _, ids = self.ready_and_abort()
        droplet_id = ids['game'].split(':')[1]
        self.stack.provider.data['droplets'][droplet_id]['tags'] = ['someone-elses-tag']
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(60)
        self.stack.registry.disown_resource(SESSION, ids['game'], 'verified in console: belongs to another project')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_WITH_DISPOSITION)
        self.assertEqual(status['overall'], 'resources_verified_with_operator_disposition')
        self.assertIn(droplet_id, self.stack.provider.live_ids()['droplets'], 'the unrelated Droplet survives')

    def test_operator_can_also_repair_ownership_so_cleanup_proceeds(self):
        _, _, _, _, ids = self.ready_and_abort()
        droplet_id = ids['game'].split(':')[1]
        original = list(self.stack.provider.data['droplets'][droplet_id]['tags'])
        self.stack.provider.data['droplets'][droplet_id]['tags'] = ['someone-elses-tag']
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(30)
        self.stack.provider.data['droplets'][droplet_id]['tags'] = original
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual([i['status'] for i in status['incidents'] if i['kind'] == 'ownership-mismatch'], ['resolved'])

    def test_unrelated_resources_and_project_membership_grant_nothing(self):
        unrelated = self.stack.provider.add_droplet('production-arena', ['production'], project='omega.realm')
        other_fw = self.stack.provider.add_firewall('production-fw', tags=['production'])
        management = self.stack.provider.add_droplet('mgmt-1', ['omega-management'], project='omega.realm')
        self.stack.provider.add_tag('production')
        self.ready_and_abort()
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        live = self.stack.provider.live_ids()
        self.assertEqual(sorted(live['droplets']), sorted([unrelated, management]))
        self.assertEqual(live['firewalls'], [other_fw])
        self.assertIn('production', live['tags'])
        touched = {o['target'] for o in self.stack.provider.ops}
        self.assertFalse(touched & {unrelated, management, other_fw, 'production'})

    def test_management_tag_is_never_deletable_even_with_a_session_tag(self):
        tags = rf.fx_tags(SESSION)
        _, _, _, _, _ = self.ready_and_abort()
        management = self.stack.provider.add_droplet(SESSION + '-game', [tags['session'], tags['game'], 'omega-management'])
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(60)
        self.assertIn(management, self.stack.provider.live_ids()['droplets'])
        incident = [i for i in self.stack.registry.incidents(SESSION) if i['kind'] == 'ownership-mismatch']
        self.assertTrue(any('protected management tag' in i['last_error'] for i in incident))

    def test_retained_resource_listed_in_the_manifest_is_refused(self):
        manifest, sha = fx.session_manifest(SESSION)
        tags = rf.fx_tags(SESSION)
        import copy
        import manifest as manifest_mod
        changed = copy.deepcopy(manifest)
        changed['session']['retained_resources'] = list(changed['session']['retained_resources']) + ['droplet:424242']
        sha = manifest_mod.manifest_sha256(changed)
        client = self.stack.client
        client.register(changed, sha)
        token = client.acquire(SESSION)['fencing_token']
        self.stack.watchdog.tick()
        client.arm(SESSION, changed, sha, token)
        self.stack.watchdog.tick()
        self.stack.provider.add_droplet(SESSION + '-game', [tags['session'], tags['game']], droplet_id='424242')
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(60)
        self.assertIn('424242', self.stack.provider.live_ids()['droplets'])

    def test_firewall_identity_and_targets_are_checked(self):
        for tamper, expected in ((dict(name='production-fw'), 'expected session name'),
                                 (dict(tags=['production']), 'tags outside this session'),
                                 (dict(droplet_ids=['999']), 'does not own')):
            with self.subTest(tamper=sorted(tamper)):
                stack = rf.Stack(self)
                _, _, _, _, ids = stack.ready(SESSION)
                firewall_id = ids['firewall'].split(':', 1)[1]
                stack.provider.data['firewalls'][firewall_id].update(tamper)
                stack.registry.operator_abort(SESSION, 'test')
                stack.step(120)
                self.assertIn(firewall_id, stack.provider.live_ids()['firewalls'])
                incident = [i for i in stack.registry.incidents(SESSION) if i['kind'] == 'ownership-mismatch']
                self.assertTrue(any(expected in i['last_error'] for i in incident), incident)
                self.assertFalse(stack.provider.ops_named('delete_firewall'))

    def test_tag_still_labelling_something_else_is_not_deleted(self):
        self.ready_and_abort()
        tags = rf.fx_tags(SESSION)
        self.stack.provider._tag_count = lambda name: 1 if name == tags['bot'] else 0
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(150)
        self.assertIn(tags['bot'], self.stack.provider.live_ids()['tags'])
        self.assertFalse([o for o in self.stack.provider.ops_named('delete_tag') if o['target'] == tags['bot']])
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.DELETING)

    def test_a_listing_alone_never_deletes_an_id_it_could_not_verify_by_read(self):
        tags = rf.fx_tags(SESSION)
        self.stack.armed(SESSION)
        foreign = self.stack.provider.add_droplet('not-a-session-name', [tags['session']])
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(60)
        self.assertIn(foreign, self.stack.provider.live_ids()['droplets'])
        kinds = [i['kind'] for i in self.stack.registry.incidents(SESSION)]
        self.assertIn('ownership-mismatch', kinds)


class AmbiguousAndLateCreateTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        _, _, self.token, self.ack = self.stack.armed(SESSION)
        self.tags = rf.fx_tags(SESSION)
        self.intent = SESSION + ':droplet:game'
        self.name = SESSION + '-game'

    def begin(self):
        return self.stack.client.mutate('begin_create', session_id=SESSION, intent_id=self.intent, fencing_token=self.token)

    def test_created_but_never_reported_resource_is_discovered_and_deleted(self):
        self.begin()
        droplet = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        # The controller dies between the provider's 201 and record_resource.
        self.stack.registry.operator_abort(SESSION, 'controller lost')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [])
        status = self.stack.registry.status(SESSION)
        resource = next(r for r in status['resources'] if r['resource_key'] == 'droplet:' + droplet)
        self.assertEqual((resource['source'], resource['status']), ('discovered', 'absent'))
        intent = next(i for i in status['intents'] if i['intent_id'] == self.intent)
        self.assertEqual(intent['state'], 'created')

    def test_missing_id_after_timeout_is_not_proof_nothing_was_created(self):
        self.begin()
        self.stack.client.mutate('record_create_result', session_id=SESSION, intent_id=self.intent, outcome='ambiguous', note='timeout')
        self.stack.registry.operator_abort(SESSION, 'test')
        start = self.stack.clock.wall_value
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertGreaterEqual(self.stack.clock.wall_value - start, cleanup_ledger.CREATE_SETTLE_S,
                                'closure waits out the settle window')
        intent = next(i for i in self.stack.registry.status(SESSION)['intents'] if i['intent_id'] == self.intent)
        self.assertEqual(intent['state'], 'resolved_absent')

    def test_late_create_landing_during_the_settle_window_is_caught(self):
        self.begin()
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(40)
        late = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [])
        self.assertTrue(self.stack.provider.ops_named('delete_droplet'))
        self.assertEqual(self.stack.registry.status(SESSION)['resources'][0]['provider_id'], late)

    def test_duplicate_creates_for_one_intent_are_both_owned_and_deleted(self):
        ids = [self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']]) for _ in range(2)]
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [])
        self.assertEqual({o['target'] for o in self.stack.provider.ops_named('delete_droplet')}, set(ids))
        self.assertIn('duplicate_create', [e['kind'] for e in self.stack.registry.journal(SESSION)])

    def test_inventory_outranks_an_earlier_absent_read(self):
        droplet = self.stack.client.guarded_create(SESSION, self.intent, self.token,
                                                   lambda g: self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']]),
                                                   lambda g: None)
        droplet_id = droplet.split(':')[1]
        self.stack.provider.fail(rf.outage, op='list_droplets_by_tag', times=1)
        real_get = self.stack.provider.get_droplet
        self.stack.provider.get_droplet = lambda i: None    # eventually consistent 404 while still listed
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.step(20)
        journal = [e['kind'] for e in self.stack.registry.journal(SESSION)]
        self.assertIn('absence_reversed', journal)
        self.assertFalse(self.stack.closed(SESSION))
        self.stack.provider.get_droplet = real_get
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertNotIn(droplet_id, self.stack.provider.live_ids()['droplets'])

    def live_firewall(self):
        return self.stack.client.guarded_create(SESSION, SESSION + ':firewall', self.token,
                                                lambda g: self.stack.provider.add_firewall(g['expected_name'], tags=g['expected_tags']),
                                                lambda g: None)

    def live_tags(self):
        for role in ('session', 'game', 'bot'):
            self.stack.client.guarded_create(SESSION, SESSION + ':tag:' + role, self.token,
                                             lambda g, r=role: (self.stack.provider.add_tag(self.tags[r]), self.tags[r])[1], lambda g: None)

    def protection_requests(self):
        return self.stack.provider.ops_named('delete_firewall', 'delete_tag', 'get_firewall', 'get_tag')

    def intent_state(self, intent_id):
        return next(i for i in self.stack.registry.status(SESSION)['intents'] if i['intent_id'] == intent_id)['state']

    def test_outstanding_droplet_create_keeps_firewall_and_tags_until_it_resolves(self):
        self.live_firewall()
        self.live_tags()
        self.begin()
        self.stack.registry.operator_abort(SESSION, 'droplet request outstanding')
        self.stack.step(35)
        self.assertEqual(self.protection_requests(), [], 'nothing protective is even read yet')
        self.assertEqual(len(self.stack.provider.live_ids()['firewalls']), 1)
        self.assertEqual(len(self.stack.provider.live_ids()['tags']), 3)
        late = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.stack.step(15)
        self.assertEqual(len(self.stack.provider.live_ids()['firewalls']), 1, 'the late Droplet landed behind its firewall')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]), 'clean receipt, clean account')
        self.assertEqual(self.intent_state(self.intent), 'created')
        ops = [o['op'] for o in self.stack.provider.ops]
        self.assertLess(ops.index('delete_droplet'), ops.index('delete_firewall'))
        self.assertLess(ops.index('delete_firewall'), ops.index('delete_tag'))
        journal = self.stack.registry.journal(SESSION)
        verified = next(e['seq'] for e in journal if e['kind'] == 'verified_absent' and e['data']['resource_key'] == 'droplet:' + late)
        accepted = next(e['seq'] for e in journal if e['kind'] == 'delete_accepted' and e['data']['resource_key'].startswith('firewall:'))
        self.assertLess(verified, accepted)

    def test_create_that_never_lands_releases_protection_after_its_bound(self):
        self.live_firewall()
        self.live_tags()
        self.begin()
        start = self.stack.clock.wall_value
        self.stack.registry.operator_abort(SESSION, 'never lands')
        self.stack.run_until(lambda: self.stack.provider.ops_named('delete_firewall'), limit_s=200)
        self.assertGreaterEqual(self.stack.clock.wall_value - start, cleanup_ledger.CREATE_SETTLE_S)
        self.assertEqual(self.intent_state(self.intent), 'resolved_absent')
        self.stack.run_until(lambda: self.stack.closed(SESSION), limit_s=200)
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]))

    def test_settling_needs_fresh_listings_so_an_outage_is_never_a_success(self):
        self.live_firewall()
        self.begin()
        self.stack.registry.operator_abort(SESSION, 'listing outage')
        rule = self.stack.provider.fail(rf.outage, op='list_droplets_by_tag')
        self.stack.step(cleanup_ledger.CREATE_SETTLE_S + 120)
        self.assertEqual(self.intent_state(self.intent), 'requested')
        self.assertEqual(self.protection_requests(), [])
        self.assertFalse(self.stack.closed(SESSION))
        self.stack.provider.faults.remove(rule)
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.intent_state(self.intent), 'resolved_absent')

    def test_settling_counts_only_listings_started_after_the_bound(self):
        self.begin()
        self.stack.registry.operator_abort(SESSION, 'race the bound')
        start = self.stack.clock.wall_value
        while self.stack.clock.wall_value - start < cleanup_ledger.CREATE_SETTLE_S:
            self.assertEqual(self.intent_state(self.intent), 'requested', 'early empty listings prove nothing')
            self.stack.step(1)
        landing = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.intent_state(self.intent), 'created')
        self.assertNotIn(landing, self.stack.provider.live_ids()['droplets'])

    def test_outstanding_tag_create_blocks_closure_until_its_bound(self):
        tag_intent = SESSION + ':tag:session'
        self.stack.client.mutate('begin_create', session_id=SESSION, intent_id=tag_intent, fencing_token=self.token)
        self.stack.registry.operator_abort(SESSION, 'tag request outstanding')
        start = self.stack.clock.wall_value
        self.stack.step(40)
        self.assertFalse(self.stack.closed(SESSION))
        self.stack.provider.add_tag(self.tags['session'])
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertGreaterEqual(self.stack.clock.wall_value - start, cleanup_ledger.CREATE_SETTLE_S)
        self.assertEqual(self.stack.provider.live_ids()['tags'], [], 'the late tag did not survive closure')
        self.assertEqual(self.intent_state(tag_intent), 'created')

    def test_outstanding_tag_create_that_never_lands_is_resolved_by_its_read(self):
        tag_intent = SESSION + ':tag:bot'
        self.stack.client.mutate('begin_create', session_id=SESSION, intent_id=tag_intent, fencing_token=self.token)
        self.stack.registry.operator_abort(SESSION, 'tag never lands')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.intent_state(tag_intent), 'resolved_absent')

    def test_every_pending_kind_at_once_cannot_deadlock(self):
        for intent in (self.intent, SESSION + ':droplet:bot', SESSION + ':firewall', SESSION + ':tag:session',
                       SESSION + ':tag:game', SESSION + ':tag:bot'):
            self.stack.client.mutate('begin_create', session_id=SESSION, intent_id=intent, fencing_token=self.token)
        self.stack.registry.operator_abort(SESSION, 'everything outstanding')
        self.stack.run_until(lambda: self.stack.closed(SESSION), limit_s=240)
        self.assertEqual({i['state'] for i in self.stack.registry.status(SESSION)['intents']}, {'resolved_absent'})

    def test_id_reported_without_its_intent_still_settles_it(self):
        firewall_intent = SESSION + ':firewall'
        self.stack.client.mutate('begin_create', session_id=SESSION, intent_id=firewall_intent, fencing_token=self.token)
        firewall = self.stack.provider.add_firewall(SESSION + '-fw', tags=[self.tags['game'], self.tags['bot']])
        self.stack.client.mutate('record_resource', session_id=SESSION, kind='firewall', provider_id=firewall, name=SESSION + '-fw')
        self.stack.registry.operator_abort(SESSION, 'unlinked report')
        self.stack.run_until(lambda: self.stack.closed(SESSION), limit_s=240)
        self.assertEqual(self.intent_state(firewall_intent), 'created')
        self.assertEqual(self.stack.provider.live_ids()['firewalls'], [])

    def test_droplet_found_after_tags_were_verified_makes_them_reverify(self):
        self.live_tags()
        self.stack.registry.operator_abort(SESSION, 'late beyond the bound')
        self.stack.run_until(lambda: all(r['status'] == 'absent' for r in self.stack.registry.resources(SESSION) if r['kind'] == 'tag'))
        self.assertFalse(self.stack.closed(SESSION), 'closure still needs a listing that started after this read')
        self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])    # recreates its tags
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]))
        self.assertIn('tags_revalidating', [e['kind'] for e in self.stack.registry.journal(SESSION)])

    def test_tag_read_older_than_the_late_resource_cannot_prove_absence(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        stack.armed(SESSION)
        stack.registry.operator_abort(SESSION, 'race a tag read')
        while not any(r['kind'] == 'tag' and r['in_flight_attempt'] for r in stack.registry.resources(SESSION)):
            stack.step(1)
            executor.release()
            stack.watchdog.tick()
        stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        with stack.registry.txn('fixture') as effective:
            stack.registry.revalidate_tags(SESSION, session_clock.iso(effective), 'droplet:late')
        stack.step(1)
        executor.release()
        stack.watchdog.tick()
        statuses = {r['resource_key']: r['status'] for r in stack.registry.resources(SESSION) if r['kind'] == 'tag'}
        self.assertNotEqual(statuses['tag:' + self.tags['session']], 'absent')

    def test_failed_listing_is_not_the_fresh_inventory_closure_needs(self):
        self.stack.registry.operator_abort(SESSION, 'listing fails after verification')
        real_done = lambda: all(r['status'] == 'absent' for r in self.stack.registry.resources(SESSION)
                                if r['kind'] not in registry.LISTING_KINDS)
        self.stack.run_until(real_done)
        self.assertFalse(self.stack.closed(SESSION))
        self.stack.provider.fail(rf.outage, op='list_droplets_by_tag')
        self.stack.step(60)
        self.assertFalse(self.stack.closed(SESSION), 'a failed listing proves nothing')
        self.stack.provider.clear_faults()
        self.stack.run_until(lambda: self.stack.closed(SESSION))

    def test_report_after_closure_reverifies_tags_the_late_resource_recreated(self):
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        late = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.assertTrue(self.stack.provider.live_ids()['tags'], 'the provider recreated them')
        self.stack.client.mutate('record_resource', session_id=SESSION, kind='droplet', provider_id=late, intent_id=self.intent, name=self.name)
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]))

    def test_no_new_create_is_authorized_once_cleanup_began(self):
        self.stack.registry.operator_abort(SESSION, 'test')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.begin()
        self.assertEqual(caught.exception.code, 'cleanup_in_progress')

    def test_create_authorized_before_c_and_reported_after_cleanup_is_still_recorded(self):
        self.begin()
        self.stack.registry.operator_abort(SESSION, 'test')
        droplet = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.stack.client.mutate('record_resource', session_id=SESSION, kind='droplet', provider_id=droplet, intent_id=self.intent, name=self.name)
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [])

    def test_report_after_closure_reopens_cleanup_and_keeps_the_first_receipt(self):
        self.stack.registry.operator_abort(SESSION, 'test')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        first_verified = self.stack.registry.status(SESSION)['cleanup']['verified_at']
        late = self.stack.provider.add_droplet(self.name, [self.tags['session'], self.tags['game']])
        self.stack.client.mutate('record_resource', session_id=SESSION, kind='droplet', provider_id=late, intent_id=self.intent, name=self.name)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['overall'], 'cleanup_not_verified')
        self.assertEqual(deadlines(self.stack)[0], self.ack['t0_utc'], 'reopening never revives or re-arms')
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [])
        receipts = sorted(p.name for p in (self.stack.state_dir / registry.RECEIPT_DIR).iterdir())
        self.assertEqual(receipts, [SESSION + '.closure-1.json', SESSION + '.closure-2.json'])
        self.assertGreater(self.stack.registry.status(SESSION)['cleanup']['verified_at'], first_verified)
        self.assertIn('late-resource-after-close', [i['kind'] for i in self.stack.registry.incidents(SESSION)])


class ClockJumpTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        _, _, self.token, self.ack, _ = self.stack.ready(SESSION)
        self.c = session_clock.parse(self.ack['cleanup_c_utc'])
        self.d = session_clock.parse(self.ack['deadline_d_utc'])
        self.original = deadlines(self.stack)

    def test_backward_wall_jump_cannot_delay_c(self):
        self.stack.step(10)
        self.stack.clock.jump_wall(-7200)
        elapsed_to_c = self.c - self.stack.registry.peek_now()
        self.assertGreater(elapsed_to_c, 0)
        self.stack.step(elapsed_to_c)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING, 'monotonic time reached C despite the wall clock')
        self.assertEqual(deadlines(self.stack), self.original)
        kinds = [i['kind'] for i in self.stack.registry.incidents()]
        self.assertIn('clock-anomaly', kinds)

    def test_backward_jump_cannot_delay_d_or_the_overdue_incident(self):
        self.stack.provider.fail(rf.outage)
        self.stack.clock.jump_wall(-7200)
        self.stack.step(self.d - self.stack.registry.peek_now())
        kinds = [i['kind'] for i in self.stack.registry.incidents(SESSION)]
        self.assertIn('cleanup-overdue', kinds)

    def test_backward_jump_across_a_restart_on_the_same_boot_keeps_time(self):
        self.stack.step(10)
        before = self.stack.registry.peek_now()
        self.stack.clock.jump_wall(-3600)
        self.stack.restart_watchdog()
        self.assertGreaterEqual(self.stack.registry.peek_now(), before)
        self.stack.step(self.c - self.stack.registry.peek_now())
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.DELETING)

    def test_forward_jump_may_start_cleanup_early_and_correction_cannot_revive(self):
        self.stack.clock.jump_wall(self.c - self.stack.clock.wall_value + 10)
        self.stack.watchdog.tick()
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.stack.clock.jump_wall(-(self.c - fx.T0_WALL))
        self.stack.step(5)
        status = self.stack.registry.status(SESSION)
        self.assertIn(status['state'], (registry.DELETING, registry.CLOSED), 'an expired session stays expired')
        self.assertEqual(deadlines(self.stack), self.original)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.mutate('dispatch_run', session_id=SESSION, run_id='r', fencing_token=self.token,
                                     manifest_sha256=status['manifest_sha256'], estimated_duration_s=1)
        self.assertIn(caught.exception.code, ('lease_expired', 'cleanup_in_progress'))

    def test_reboot_with_a_behind_rtc_cannot_rewind_or_lose_the_deadline(self):
        self.stack.step(100)
        high_water = self.stack.registry.peek_now()
        self.stack.restart_watchdog(reboot=True, rtc_error_s=-86400)
        self.assertGreaterEqual(self.stack.registry.peek_now(), high_water)
        self.assertFalse(self.stack.registry.clock_healthy())
        self.stack.watchdog.tick()
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.DELETING)
        self.assertEqual(deadlines(self.stack), self.original)

    def test_clock_anomaly_refuses_new_sessions_until_it_clears(self):
        manifest, sha, token = self.stack.registered('do-cap-second-session')
        self.stack.watchdog.tick()
        self.stack.clock.jump_wall(-3600)
        self.stack.watchdog.tick()
        self.assertFalse(self.stack.registry.health()['registry']['healthy'])
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.arm('do-cap-second-session', manifest, sha, token)
        self.assertEqual(caught.exception.code, 'clock_unhealthy')
        self.stack.clock.jump_wall(3600)
        self.stack.watchdog.tick()
        self.stack.client.arm('do-cap-second-session', manifest, sha, token)
        incident = [i for i in self.stack.registry.incidents() if i['kind'] == 'clock-anomaly']
        self.assertEqual([i['status'] for i in incident], ['resolved'], 'the record survives the recovery')

    def test_small_slews_are_not_anomalies(self):
        self.stack.clock.jump_wall(-3)
        self.stack.step(3)
        self.stack.clock.jump_wall(3)
        self.stack.step(3)
        self.assertEqual([i for i in self.stack.registry.incidents() if i['kind'] == 'clock-anomaly'], [])

    def test_lease_cannot_be_prolonged_by_a_backward_jump(self):
        self.stack.clock.jump_wall(-3600)
        self.stack.step(self.stack.registry.lease_ttl_s + 1)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.call('renew_control', session_id=SESSION, fencing_token=self.token)
        self.assertEqual(caught.exception.code, 'lease_expired')


class UnverifiableRebootTests(unittest.TestCase):
    """Local timestamps cannot bound downtime: an unverified reboot stops work and starts cleanup."""

    def setUp(self):
        self.stack = rf.Stack(self)
        self.manifest, self.sha, self.token, self.ack, _ = self.stack.ready(SESSION, cap_s=600, reserve_s=120, grace_s=100)
        self.stack.step(50)
        self.stack.registry.renew_control(SESSION, self.token)
        self.stack.step(50)

    def assert_failed_closed(self):
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['reason'], registry.CLOCK_UNVERIFIABLE_REASON)
        self.assertTrue(status['cleanup']['overdue'], 'D may already have passed, so report the possible breach')
        self.assertTrue(status['cleanup']['deadline_uncertain'])
        overdue = [i for i in status['incidents'] if i['kind'] == 'cleanup-overdue']
        self.assertTrue(overdue[0]['detail']['deadline_uncertain'])
        for name, call in (('renew', lambda: self.stack.registry.renew_control(SESSION, self.token)),
                           ('dispatch', lambda: self.stack.registry.dispatch_run(SESSION, 'after-reboot', self.token, self.sha, 60))):
            with self.subTest(call=name), self.assertRaises(registry.Rejection) as caught:
                call()
            self.assertEqual(caught.exception.code, 'clock_unverifiable')
        self.assertEqual(self.stack.registry.runs(SESSION), [])

    def test_rtc_a_day_behind_after_downtime_past_d_stops_work_and_reports_overdue(self):
        self.stack.restart_watchdog(reboot=True, downtime_s=600, rtc_error_s=-86400)    # really 700 s: past D
        self.stack.watchdog.tick()
        self.assert_failed_closed()
        self.stack.run_until(lambda: self.stack.closed(SESSION))
        status = self.stack.registry.status(SESSION)
        self.assertEqual(self.stack.provider.live_ids(), dict(droplets=[], firewalls=[], tags=[]))
        self.assertEqual(status['overall'], 'resources_verified_evidence_incomplete')
        self.assertTrue(status['cleanup']['overdue'], 'the possible breach stays visible after cleanup')
        self.assertTrue(status['cleanup']['overrun_is_lower_bound'], 'measured on a clock that lost the downtime')
        receipt = json.loads(next((self.stack.state_dir / registry.RECEIPT_DIR).glob('*.json')).read_text())
        self.assertTrue(receipt['deadline_uncertain'])
        self.assertTrue(receipt['overrun_is_lower_bound'])

    def test_rtc_partly_behind_is_not_saved_by_timestamps_moving_forward(self):
        # Downtime 600 s, RTC 300 s slow: the wall looks like a plausible 300 s reboot, before C and D.
        self.stack.restart_watchdog(reboot=True, downtime_s=600, rtc_error_s=-300)
        self.assertGreater(self.stack.clock.wall_value, self.stack.registry.db.execute('SELECT effective FROM clock_state').fetchone()['effective'] - 1)
        self.stack.watchdog.tick()
        self.assert_failed_closed()

    def test_wall_ahead_of_the_floor_without_a_verified_clock_fails_closed(self):
        self.stack.restart_watchdog(reboot=True, downtime_s=10, rtc_error_s=0.0, synced=False)
        self.stack.watchdog.tick()
        self.assert_failed_closed()

    def test_first_request_after_a_reboot_fails_closed_before_any_watchdog_runs(self):
        self.stack.clock.reboot(downtime_s=600, rtc_error_s=-86400)
        registry_ = self.stack.registry
        self.assertFalse(registry_.health(SESSION)['registry']['healthy'], 'a read alone already reports it')
        with self.assertRaises(registry.Rejection) as caught:
            registry_.renew_control(SESSION, self.token)
        self.assertEqual(caught.exception.code, 'clock_unverifiable')
        self.assert_failed_closed()

    def test_takeover_after_the_reboot_gets_no_work(self):
        self.stack.restart_watchdog(reboot=True, downtime_s=600, rtc_error_s=-86400)
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('dispatch_run', session_id=SESSION, run_id='r', fencing_token=token,
                         manifest_sha256=self.sha, estimated_duration_s=1)
        self.assertEqual(caught.exception.code, 'clock_unverifiable')

    def test_new_sessions_wait_for_verified_time_and_old_ones_stay_in_cleanup(self):
        manifest, sha, token = self.stack.registered('do-cap-second-session')
        self.stack.restart_watchdog(reboot=True, downtime_s=600, rtc_error_s=-86400)
        self.stack.step(1)
        self.assertNotIn('do-cap-second-session', [i['session_id'] for i in self.stack.registry.incidents(status='open')],
                         'an unarmed session has no deadline to lose')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.arm('do-cap-second-session', manifest, sha, token)
        self.assertEqual(caught.exception.code, 'clock_unhealthy')
        self.stack.clock.time_sync(86400)
        self.stack.step(1)
        kinds = {i['kind']: i['status'] for i in self.stack.registry.incidents()}
        self.assertEqual(kinds['clock-unverifiable'], 'resolved', 'the record survives the recovery')
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.DELETING, 'verified time cannot revive it')
        self.stack.client.acquire('do-cap-second-session', takeover=True)
        token = self.stack.registry.status('do-cap-second-session')['fencing_token']
        self.stack.client.arm('do-cap-second-session', manifest, sha, token)

    def test_verified_time_after_a_reboot_keeps_the_session_running(self):
        self.stack.restart_watchdog(reboot=True, downtime_s=30, rtc_error_s=0.0)
        self.stack.watchdog.tick()
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.READY)
        self.assertFalse(status['cleanup']['deadline_uncertain'])
        self.assertEqual(self.stack.registry.incidents(), [])

    def test_repeated_unverified_reboots_stay_one_incident_per_session(self):
        for boot in ('boot-b', 'boot-c'):
            self.stack.restart_watchdog(reboot=True, boot=boot, downtime_s=5, rtc_error_s=-1000)
            self.stack.watchdog.tick()
        kinds = [i['kind'] for i in self.stack.registry.incidents()]
        self.assertEqual(sorted(kinds), ['cleanup-overdue', 'clock-unverifiable'])
        intents = [e for e in self.stack.registry.journal(SESSION) if e['kind'] == 'cleanup_intent']
        self.assertEqual(len(intents), 1)


class ClockUnitTests(unittest.TestCase):
    def test_advance_table(self):
        anchor = session_clock.Anchor('b', 100.0, 5000.0)
        unverifiable = session_clock.REBOOT_TIME_UNVERIFIABLE
        cases = [
            ('normal', 5010.0, 110.0, 'b', False, 5010.0, None),
            ('wall behind', 4000.0, 110.0, 'b', False, 5010.0, 'wall_behind_effective'),
            ('wall ahead', 9000.0, 110.0, 'b', False, 9000.0, 'wall_jumped_forward'),
            ('reboot with verified time is just downtime', 9000.0, 1.0, 'c', True, 9000.0, None),
            ('reboot without verified time proves nothing', 9000.0, 1.0, 'c', False, 9000.0, unverifiable),
            ('reboot rtc behind', 100.0, 1.0, 'c', False, 5000.0, unverifiable),
            ('reboot behind the floor is wrong even if synced', 100.0, 1.0, 'c', True, 5000.0, unverifiable),
            ('boot id lost', 5001.0, 110.0, session_clock.UNKNOWN_BOOT, False, 5001.0, unverifiable),
            ('mono regressed on same boot id', 5000.0, 50.0, 'b', False, 5000.0, None),
            ('mono regressed and wall behind', 100.0, 50.0, 'b', False, 5000.0, unverifiable),
        ]
        for label, wall, mono, boot, verified, expected, anomaly in cases:
            with self.subTest(label):
                effective, new_anchor, seen = session_clock.advance(anchor, wall, mono, boot, utc_verified=verified)
                self.assertEqual(effective, expected)
                self.assertEqual(seen['kind'] if seen else None, anomaly)
                self.assertEqual(new_anchor.effective, expected)

    def test_a_host_with_no_boot_identity_trusts_only_the_floor(self):
        unknown = session_clock.UNKNOWN_BOOT
        anchor = session_clock.Anchor(unknown, 100.0, 5000.0)
        self.assertIsNone(session_clock.advance(anchor, 5001.0, 110.0, unknown)[2], 'a development fallback, not a reboot')
        self.assertEqual(session_clock.advance(anchor, 100.0, 110.0, unknown)[2]['kind'], session_clock.REBOOT_TIME_UNVERIFIABLE)

    def test_kernel_time_sync_reading(self):
        class Libc:
            def __init__(self, state):
                self.state = state

            def adjtimex(self, _):
                return self.state

        for state, expected in ((0, True), (1, True), (4, True), (session_clock.ADJTIMEX_TIME_ERROR, False), (-1, False)):
            with self.subTest(state=state):
                self.assertIs(session_clock.kernel_time_synced(Libc(state)), expected)
        self.assertIs(session_clock.kernel_time_synced(object()), False, 'no such call means nothing is verified')

    def test_timing_constants_keep_their_ordering(self):
        self.assertGreaterEqual(session_clock.CLEANUP_START_LEAD_S, session_clock.PROVIDER_REQUEST_BOUND_S + 2)
        self.assertGreater(session_clock.CREATE_SETTLE_S, session_clock.CREATE_START_WINDOW_S + session_clock.PROVIDER_REQUEST_BOUND_S)

    def test_effective_time_never_moves_backward_on_any_sequence(self):
        import random
        rng = random.Random(65)
        anchor, previous = None, 0.0
        wall, mono, boot = 1000.0, 10.0, 'b0'
        for step in range(5000):
            wall += rng.choice((1, 1, 1, -500, 500, 0))
            mono += 1
            if rng.random() < 0.01:
                mono, boot = 1.0, 'b' + str(step)
            effective, anchor, _ = session_clock.advance(anchor, wall, mono, boot)
            self.assertGreaterEqual(effective, previous)
            previous = effective


class FirstDeleteByCTests(unittest.TestCase):
    """An ownership read comes before every delete, so cleanup starts early enough to fit one."""

    def first_delete_at(self, stack, session_id):
        return next(session_clock.parse(a['started_at']) for a in stack.registry.attempts(session_id) if a['op'] == 'delete_droplet')

    def reach_cleanup(self, stack, ack):
        run_to(stack, session_clock.parse(ack['cleanup_c_utc']) - registry.CLEANUP_LEAD_S)

    def test_slowest_successful_read_still_issues_the_first_delete_by_c(self):
        for delay in (1, 10, 20, session_clock.PROVIDER_REQUEST_BOUND_S - 1):
            with self.subTest(read_delay_s=delay):
                executor = fx.DeferredExecutor()
                stack = rf.Stack(self, executor=executor)
                _, _, _, ack, _ = stack.ready(SESSION, cap_s=600, reserve_s=120, grace_s=100)
                c = session_clock.parse(ack['cleanup_c_utc'])
                self.reach_cleanup(stack, ack)
                self.assertTrue(executor.pending, 'the ownership reads are out')
                self.assertFalse(stack.provider.ops_named('delete_droplet'))
                stack.step(delay)
                executor.release()      # the reads come back only now, and only ownership authorizes a delete
                stack.step(1)
                self.assertLessEqual(self.first_delete_at(stack, SESSION), c)

    def test_read_past_its_bound_is_a_failure_not_a_delete_or_a_success(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        _, _, _, ack, _ = stack.ready(SESSION, cap_s=600, reserve_s=120, grace_s=100)
        self.reach_cleanup(stack, ack)
        stack.step(session_clock.PROVIDER_REQUEST_BOUND_S + 1)
        self.assertEqual([a for a in stack.registry.attempts(SESSION) if a['op'] == 'delete_droplet'], [])
        self.assertTrue(all(a['error_class'] == 'ProviderTransient' or a['finished_at'] is None
                            for a in stack.registry.attempts(SESSION)))
        self.assertFalse(stack.closed(SESSION))

    def test_outage_through_c_issues_no_delete_and_never_claims_success(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION, cap_s=600, reserve_s=120, grace_s=100)
        stack.provider.fail(rf.outage)
        run_to(stack, session_clock.parse(ack['deadline_d_utc']) + 1)
        self.assertEqual(stack.provider.ops_named('delete_droplet'), [], 'no ownership read, no delete')
        status = stack.registry.status(SESSION)
        self.assertEqual(status['overall'], 'cleanup_overdue')

    def test_delayed_reads_across_simultaneous_sessions_all_delete_by_c(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        names = ['do-cap-' + c + '-sim' for c in 'abcd']     # 4 x 2 reads fill the eight in-flight slots
        acks = [stack.ready(name, cap_s=600, reserve_s=120, grace_s=100)[3] for name in names]
        self.reach_cleanup(stack, acks[0])
        self.assertEqual(len(executor.pending), 8)
        stack.step(session_clock.PROVIDER_REQUEST_BOUND_S - 1)
        executor.release()
        stack.step(1)
        for name, ack in zip(names, acks):
            self.assertLessEqual(self.first_delete_at(stack, name), session_clock.parse(ack['cleanup_c_utc']), name)

    def test_hung_sessions_cannot_make_an_imminent_c_late(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        hung = ['do-cap-' + c + '-hung' for c in 'abc']
        for name in hung:
            stack.ready(name)
        _, _, _, ack, _ = stack.ready('do-cap-z-due', cap_s=600, reserve_s=120, grace_s=100)
        for name in hung:
            stack.registry.operator_abort(name, 'provider calls hang')
        run_to(stack, session_clock.parse(ack['cleanup_c_utc']) - registry.CLEANUP_LEAD_S)
        stack.step(1)
        counts = stack.watchdog.ledger.in_flight_counts()
        self.assertEqual(counts.get('do-cap-z-due'), 2, 'reserved capacity took its reads at once')
        self.assertLessEqual(sum(counts.values()), 8)
        stack.step(session_clock.PROVIDER_REQUEST_BOUND_S - 2)
        executor.release()
        stack.step(1)
        self.assertLessEqual(self.first_delete_at(stack, 'do-cap-z-due'), session_clock.parse(ack['cleanup_c_utc']))

    def test_ordinary_sessions_keep_being_served_around_urgent_ones(self):
        stack = rf.Stack(self, max_in_flight=8, max_in_flight_per_session=2)
        names = ['do-cap-' + c + '-many' for c in 'abcdef']
        for name in names:
            stack.ready(name)
        for name in names:
            stack.registry.operator_abort(name, 'test')
        stack.run_until(lambda: all(stack.closed(name) for name in names))

    def test_urgency_ends_at_c_and_after_the_first_delete(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor)
        _, _, _, ack, _ = stack.ready(SESSION, cap_s=600, reserve_s=120, grace_s=100)
        c = session_clock.parse(ack['cleanup_c_utc'])
        self.reach_cleanup(stack, ack)
        ledger = stack.watchdog.ledger
        row = [r for r in stack.registry.resources(SESSION) if r['kind'] == 'droplet'][0]
        due = {SESSION: [row]}
        self.assertEqual(ledger.awaiting_first_delete(due, c - 1), [SESSION])
        self.assertEqual(ledger.awaiting_first_delete(due, c + 1), [], 'a late session gets no permanent priority')
        self.assertEqual(ledger.awaiting_first_delete(due, c - registry.CLEANUP_LEAD_S - 1), [], 'an early abort is not urgent')

    def test_a_cleanup_lead_too_short_for_one_read_refuses_to_start(self):
        with self.assertRaises(ValueError):
            rf.Stack(self, ledger_options=dict(cleanup_lead_s=5.0))
        with self.assertRaises(ValueError):
            rf.Stack(self).watchdog.run_forever(None, tick_interval_s=5.0)


class FairnessTests(unittest.TestCase):
    def test_hung_session_cannot_block_another_sessions_cleanup(self):
        executor = fx.DeferredExecutor(hold_sessions={'do-cap-aaa-hung'})
        stack = rf.Stack(self, executor=executor, max_in_flight=8, max_in_flight_per_session=2)
        stack.ready('do-cap-aaa-hung')
        stack.ready('do-cap-bbb-healthy')
        stack.registry.operator_abort('do-cap-aaa-hung', 'test')
        stack.registry.operator_abort('do-cap-bbb-healthy', 'test')
        stack.run_until(lambda: stack.closed('do-cap-bbb-healthy'), limit_s=120)
        self.assertFalse(stack.closed('do-cap-aaa-hung'))
        self.assertLessEqual(stack.watchdog.ledger.in_flight_counts().get('do-cap-aaa-hung', 0), 2,
                             'a session cannot occupy more than its in-flight share')

    def test_failing_session_does_not_consume_the_other_sessions_turns(self):
        stack = rf.Stack(self, max_in_flight=1)
        stack.ready('do-cap-aaa-failing')
        stack.ready('do-cap-bbb-healthy')
        for resource in stack.registry.resources('do-cap-aaa-failing'):
            target = resource['name'] if resource['kind'].startswith('inventory') else resource['provider_id']
            stack.provider.fail(rf.outage, target=target)
        stack.registry.operator_abort('do-cap-aaa-failing', 'test')
        stack.registry.operator_abort('do-cap-bbb-healthy', 'test')
        stack.run_until(lambda: stack.closed('do-cap-bbb-healthy'), limit_s=300)
        self.assertFalse(stack.closed('do-cap-aaa-failing'))
        for resource in stack.registry.resources('do-cap-aaa-failing'):
            bursts = {}
            for attempt in stack.registry.attempts('do-cap-aaa-failing', resource['resource_key']):
                bursts.setdefault(attempt['sweep_seq'], []).append(attempt)
            self.assertTrue(all(len(b) <= 6 for b in bursts.values()))

    def test_round_robin_serves_every_due_session_under_a_tight_limit(self):
        stack = rf.Stack(self, max_in_flight=1)
        names = ['do-cap-rr-' + c for c in 'abcd']
        for name in names:
            stack.ready(name)
        for name in names:
            stack.registry.operator_abort(name, 'test')
        for _ in range(8):
            stack.step(1)
        ordered = sorted(((a['attempt_id'], name) for name in names for a in stack.registry.attempts(name)))
        first_turns = [name for _, name in ordered[:4]]
        self.assertEqual(sorted(first_turns), names, 'every session got a turn before any got a second')

    def test_per_session_limit_leaves_capacity_for_others(self):
        executor = fx.DeferredExecutor()
        stack = rf.Stack(self, executor=executor, max_in_flight=4, max_in_flight_per_session=2)
        for name in ('do-cap-x-one', 'do-cap-y-two'):
            stack.ready(name)
        for name in ('do-cap-x-one', 'do-cap-y-two'):
            stack.registry.operator_abort(name, 'test')
        stack.step(1)
        counts = stack.watchdog.ledger.in_flight_counts()
        self.assertEqual(counts, {'do-cap-x-one': 2, 'do-cap-y-two': 2})

    def test_real_threads_keep_ticking_while_a_request_is_stuck(self):
        stack = rf.Stack(self, executor=watchdog.ThreadExecutor())
        _, _, _, _, ids = stack.ready('do-cap-aaa-stuck')
        stack.ready('do-cap-bbb-fine')
        release = stack.provider.block('get_droplet', ids['game'].split(':')[1])
        self.addCleanup(release.set)
        stack.registry.operator_abort('do-cap-aaa-stuck', 'test')
        stack.registry.operator_abort('do-cap-bbb-fine', 'test')
        deadline = time.monotonic() + 30
        while not stack.closed('do-cap-bbb-fine') and time.monotonic() < deadline:
            stack.clock.advance(1)
            started = time.monotonic()
            stack.watchdog.tick()
            self.assertLess(time.monotonic() - started, 5, 'the tick never waits on a provider call')
            time.sleep(0.002)
        self.assertTrue(stack.closed('do-cap-bbb-fine'))
        self.assertFalse(stack.closed('do-cap-aaa-stuck'))


class StorageFaultTests(unittest.TestCase):
    def test_no_delete_is_issued_without_durable_intent(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION)
        c = session_clock.parse(ack['cleanup_c_utc'])

        def fail(name):
            if name.startswith('wd_'):
                raise sqlite3.OperationalError('disk full')

        stack.failpoint = fail
        with self.assertLogs('omega.do_watchdog', level=logging.ERROR):
            stack.clock.advance(c - stack.clock.wall_value + 5)
            stack.watchdog.tick()
        self.assertFalse(stack.watchdog.storage_healthy)
        self.assertEqual(stack.provider.ops, [], 'no provider mutation without a persisted attempt')
        stack.failpoint = None
        stack.step(1)
        self.assertTrue(stack.watchdog.storage_healthy)
        self.assertEqual(stack.registry.status(SESSION)['state'], registry.DELETING)
        stack.run_until(lambda: stack.closed(SESSION))

    def test_result_that_cannot_be_persisted_is_retried_not_lost(self):
        stack = rf.Stack(self)
        stack.ready(SESSION)
        stack.registry.operator_abort(SESSION, 'test')
        stack.step(1)

        def fail(name):
            if name == 'wd_finish_attempt:before_commit':
                raise sqlite3.OperationalError('disk full')

        stack.failpoint = fail
        with self.assertLogs('omega.do_watchdog', level=logging.ERROR):
            stack.step(1)
        self.assertTrue(stack.watchdog._results, 'the result stays queued in memory')
        stack.failpoint = None
        stack.run_until(lambda: stack.closed(SESSION))
        self.assertTrue(all(a['finished_at'] for a in stack.registry.attempts(SESSION)))

    def test_read_only_database_is_a_rejection_of_new_work(self):
        stack = rf.Stack(self)
        manifest, sha = fx.session_manifest(SESSION)
        stack.failpoint = lambda name: (_ for _ in ()).throw(sqlite3.OperationalError('attempt to write a readonly database'))
        with self.assertRaises(registry_client.RegistryUnavailable):
            stack.client.register(manifest, sha)

    def test_sixty_second_sqlite_outage_does_not_lose_the_deadline(self):
        stack = rf.Stack(self)
        _, _, _, ack, _ = stack.ready(SESSION)
        original = deadlines(stack)

        def fail(name):
            raise sqlite3.OperationalError('database is locked')

        stack.failpoint = fail
        with self.assertLogs('omega.do_watchdog', level=logging.ERROR):
            for _ in range(60):
                stack.clock.advance(1)
                stack.watchdog.tick()
        stack.failpoint = None
        stack.step(1)
        self.assertEqual(deadlines(stack), original)
        self.assertEqual(stack.watchdog.storage_healthy, True)


class SecretHygieneTests(unittest.TestCase):
    def test_nothing_resembling_a_credential_reaches_any_persisted_file(self):
        secret_token = 'dop_v1_' + 'c' * 64
        stack = rf.Stack(self)
        _, _, token, _, _ = stack.ready(SESSION)
        rule = stack.provider.fail(lambda: cleanup_provider.ProviderAuthError('401 token=' + secret_token, status=401))
        stack.registry.operator_abort(SESSION, 'test')
        stack.step(30)
        stack.provider.faults.remove(rule)
        stack.provider.fail(lambda: cleanup_provider.ProviderTransient('500 Authorization: Bearer ' + secret_token), times=2)
        stack.run_until(lambda: stack.closed(SESSION))
        raw = stack.state_bytes()
        self.assertNotIn(secret_token.encode(), raw)
        self.assertNotIn(b'Bearer dop_', raw)

    def test_redaction_table(self):
        for text in ('dop_v1_' + 'd' * 64, 'Authorization: Bearer ' + 'x' * 30, 'token=abc123', 'api_key: abc',
                     '-----BEGIN OPENSSH PRIVATE KEY-----', 'password=hunter2'):
            with self.subTest(text=text[:12]):
                redacted = cleanup_provider.redact('prefix ' + text)
                self.assertIn('[REDACTED]', redacted)
                self.assertNotIn(text, redacted)
        self.assertEqual(len(cleanup_provider.redact('x' * 5000)), cleanup_provider.MAX_MESSAGE_CHARS)

    def test_fake_provider_makes_no_network_import(self):
        import ast
        import pathlib
        for name in ('fake_provider.py', 'watchdog.py', 'cleanup_ledger.py', 'registry.py', 'session_clock.py'):
            tree = ast.parse(pathlib.Path(__file__).with_name(name).read_text())
            imported = {n.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for n in node.names}
            imported |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
            self.assertFalse(imported & {'socket', 'http', 'urllib', 'requests', 'ssl', 'subprocess'}, name)


class FileBackedProviderTests(unittest.TestCase):
    def test_account_state_survives_a_new_process_view(self):
        stack = rf.Stack(self)
        path = stack.root / 'account.json'
        provider = fake_provider.FakeProvider(path)
        droplet = provider.add_droplet('n', ['t'])
        self.assertEqual(fake_provider.from_file(str(path)).get_droplet(droplet)['name'], 'n')


if __name__ == '__main__':
    unittest.main()
