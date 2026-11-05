"""Slice 4's registry gates: only the legal next trial, durable phases, terminal stops and explicit resume. Typed runs on."""
import unittest

import admission
import fixture_support as fx
import registry
import registry_client
import registry_fixtures as rf
import search
import session_clock

SESSION = 'do-cap-1v1g-20261030a'


class TypedRuns(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self, typed_runs=True)
        self.manifest, self.sha, self.token, self.ack, self.ids = self.stack.ready(SESSION, cap_s=14400)
        self.client = self.stack.client

    def rejected(self, code, method, **params):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.client.mutate(method, **params)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def authorize(self, token=None, **params):
        self.minted = getattr(self, 'minted', 0) + 1
        params.setdefault('role', 'game')
        params.setdefault('grant_id', 'g%d' % self.minted)
        return self.client.mutate('authorize_guest_action', session_id=SESSION, fencing_token=token or self.token, **params)

    def launching(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        self.client.mutate('record_run_progress', session_id=SESSION, run_id=trial.run_id, phase='launching', fencing_token=self.token)
        return trial

    def now(self):
        return self.stack.registry.peek_now()

    def test_a_launch_authorization_is_short_and_ends_with_the_grant(self):
        trial = self.launching()
        run = self.stack.registry.run_records(SESSION)[0]
        answer = self.authorize(action='launch_run', run_id=trial.run_id, role='game')
        until = session_clock.parse(answer['authorized_until'])
        self.assertLessEqual(until - self.now(), registry.GUEST_ACTION_TTL_S)
        self.assertGreater(until, self.now())
        self.assertLessEqual(until, session_clock.parse(run['launch_by']))

    def test_an_authorization_never_outlives_the_lease(self):
        trial = self.launching()
        lease = session_clock.parse(self.stack.registry.status(SESSION)['lease_expires_at'])
        self.stack.clock.advance(lease - registry.GUEST_ACTION_TTL_S / 2 - self.now())
        answer = self.authorize(action='launch_run', run_id=trial.run_id, role='bot')
        self.assertEqual(session_clock.parse(answer['conclusive_at']), lease, 'a lapsed lease leaves nothing that can still be used')
        self.assertEqual(session_clock.parse(answer['authorized_until']), lease - registry.GUEST_COMMIT_SLACK_S)

    def test_a_grant_is_a_durable_intent_with_its_own_identity(self):
        trial = self.launching()
        answer = self.authorize(action='launch_run', run_id=trial.run_id, role='game', grant_id='minted-by-the-guest')
        self.assertEqual(answer['grant_id'], 'minted-by-the-guest')
        row = next(g for g in self.stack.registry.guest_grants(SESSION) if g['grant_id'] == 'minted-by-the-guest')
        self.assertEqual((row['state'], row['action'], row['role'], row['run_id'], row['fencing_token']), ('outstanding', 'launch_run', 'game', trial.run_id, self.token))
        self.assertIn('guest_grant_issued', [e['kind'] for e in self.stack.registry.journal(SESSION)])
        self.rejected('grant_replayed', 'authorize_guest_action', session_id=SESSION, fencing_token=self.token, action='launch_run', run_id=trial.run_id, role='game', grant_id='minted-by-the-guest')

    def test_only_a_run_in_its_launch_can_be_authorized(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(action='launch_run', run_id=trial.run_id, role='game')
        self.assertEqual(caught.exception.code, 'bad_state')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(action='launch_run', run_id='not-dispatched', role='game')
        self.assertEqual(caught.exception.code, 'unknown_run')

    def test_every_loss_of_authority_refuses_an_authorization(self):
        trial = self.launching()
        arguments = dict(action='launch_run', run_id=trial.run_id, role='game')
        self.stack.clock.advance(registry.DEFAULT_LAUNCH_WINDOW_S + 1)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(**arguments)
        self.assertEqual(caught.exception.code, 'launch_window_closed')
        self.client.call('renew_control', session_id=SESSION, fencing_token=self.token)
        self.authorize(action='launch_run', run_id=trial.run_id, role='bot')    # the swarm starts after the game, by design
        self.stack.registry.operator_abort(SESSION, 'operator abort')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(action='launch_run', run_id=trial.run_id, role='bot')
        self.assertEqual(caught.exception.code, 'cleanup_in_progress')

    def test_a_stale_token_and_an_expired_lease_are_refused(self):
        trial = self.launching()
        control = self.client.acquire(SESSION, takeover=True)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(action='launch_run', run_id=trial.run_id, role='game')
        self.assertEqual(caught.exception.code, 'stale_fencing_token')
        self.stack.clock.advance(registry.DEFAULT_LEASE_TTL_S + 1)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(token=control['fencing_token'], action='smoke')
        self.assertEqual(caught.exception.code, 'lease_expired')

    def test_a_smoke_belongs_to_a_paused_session_and_stops_short_of_the_cutoff(self):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(action='smoke')
        self.assertEqual(caught.exception.code, 'bad_state')
        token = self.client.acquire(SESSION, takeover=True)['fencing_token']
        until = session_clock.parse(self.authorize(token=token, action='smoke')['authorized_until'])
        self.assertLessEqual(until - self.now(), registry.GUEST_ACTION_TTL_S)
        c = session_clock.parse(self.stack.registry.status(SESSION)['cleanup_c_utc'])
        target = c - registry.DELETE_MARGIN_S - registry.GUEST_ACTION_TTL_S / 2
        while self.now() < target:
            self.stack.clock.advance(min(60.0, target - self.now()))
            self.client.call('renew_control', session_id=SESSION, fencing_token=token)
        until = session_clock.parse(self.authorize(token=token, action='smoke')['authorized_until'])
        self.assertLessEqual(until, c - registry.DELETE_MARGIN_S, 'an authorization never reaches past the delete cutoff')
        self.stack.clock.advance(registry.GUEST_ACTION_TTL_S)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(token=token, action='smoke')
        self.assertEqual(caught.exception.code, 'deadline_reached')

    def test_a_terminal_failure_refuses_a_smoke(self):
        token = self.client.acquire(SESSION, takeover=True)['fencing_token']
        self.client.mutate('record_batch_stop', session_id=SESSION, outcome=search.INFRASTRUCTURE_FAILURE, fencing_token=token, detail='host failed')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.authorize(token=token, action='smoke')
        self.assertEqual(caught.exception.code, 'terminal_failure')

    def test_an_unknown_action_or_missing_role_is_a_bad_request(self):
        for params in (dict(action='anything'), dict(action='launch_run', run_id='x', role=None), dict(action='smoke', role=None)):
            with self.assertRaises(registry_client.RegistryRejected) as caught:
                self.authorize(**params)
            self.assertEqual(caught.exception.code, 'bad_request')

    def test_a_limited_client_gives_up_inside_its_time(self):
        limited = registry_client.RegistryClient(registry_client.SubprocessTransport(['true'], timeout_s=30.0), 'x').within(4.0)
        self.assertEqual((limited.attempts, limited.transport.timeout_s), (1, 4.0))
        self.assertEqual(self.client.within(1.0).attempts, 1, 'an in-process transport has nothing to shorten')

    def state(self):
        return self.stack.registry.search_state(self.stack.registry.session_row(SESSION))

    def next(self):
        return search.next_trial(self.state())

    def dispatch(self, trial=None, token=None, estimate=None, **changes):
        trial = trial or self.next()
        params = dict(session_id=SESSION, run_id=trial.run_id, fencing_token=token or self.token, manifest_sha256=self.sha,
                      estimated_duration_s=admission.trial_duration(self.manifest, trial)['total_s'] if estimate is None else estimate, trial=trial.to_dict())
        params.update(changes)
        return params

    def seal(self, run_id, token=None):
        self.client.mutate('record_run_progress', session_id=SESSION, run_id=run_id, phase='sealed', fencing_token=token or self.token)

    def finish(self, trial, outcome, token=None):
        self.client.mutate('dispatch_run', **self.dispatch(trial, token=token))
        self.seal(trial.run_id, token)
        self.client.mutate('record_run_outcome', session_id=SESSION, run_id=trial.run_id, outcome=outcome, fencing_token=token or self.token, evidence_ref='runs/x')

    def good_checks(self, token_next=None):
        checks = {name: True for name in registry.RESUME_REQUIRED_CHECKS}
        return dict(checks, manifest_sha256=self.sha, next_run_id=token_next or self.next().run_id)

    def test_only_the_legal_next_trial_can_be_dispatched(self):
        legal = self.next()
        other = search.Trial(search.run_id(SESSION, 1, search.COARSE, 500, 1), 1, search.COARSE, 500, 1, 60, ())
        self.rejected('illegal_trial', 'dispatch_run', **self.dispatch(other))
        self.rejected('illegal_trial', 'dispatch_run', **dict(self.dispatch(legal), run_id='some-other-id'))
        self.rejected('illegal_trial', 'dispatch_run', **dict(self.dispatch(legal), trial=None))
        grant = self.client.mutate('dispatch_run', **self.dispatch(legal))
        self.assertTrue(grant['authorized'])
        self.assertEqual(session_clock.parse(grant['must_stop_by']), session_clock.parse(grant['launch_by']) + grant['estimated_duration_s'])

    def test_an_estimate_shorter_than_the_whole_trial_is_refused(self):
        trial = self.next()
        needed = admission.trial_duration(self.manifest, trial)['total_s']
        error = self.rejected('estimate_too_short', 'dispatch_run', **self.dispatch(trial, estimate=needed - 1))
        self.assertEqual(error.details['needed_s'], needed)

    def test_grant_bound_stays_inside_the_cutoff(self):
        grant = self.client.mutate('dispatch_run', **self.dispatch())
        cutoff = session_clock.parse(self.ack['cleanup_c_utc']) - registry.DELETE_MARGIN_S
        self.assertLessEqual(session_clock.parse(grant['must_stop_by']), cutoff)

    def test_a_run_cannot_be_dispatched_twice_even_by_a_new_controller(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        other.mutate('record_run_outcome', session_id=SESSION, run_id=trial.run_id, outcome=search.INCOMPLETE, fencing_token=token)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('dispatch_run', **self.dispatch(trial, token=token))
        self.assertIn(caught.exception.code, ('bad_state', 'duplicate_run'))

    def test_an_incomplete_predecessor_refuses_its_dependent_successor(self):
        first = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(first))
        self.client.mutate('record_run_outcome', session_id=SESSION, run_id=first.run_id, outcome=search.INCOMPLETE, fencing_token=self.token)
        successor = search.Trial(search.run_id(SESSION, 2, search.COARSE, 50, 1), 2, search.COARSE, 50, 1, 60, (first.run_id,))
        error = self.rejected('illegal_trial', 'dispatch_run', **self.dispatch(successor))
        self.assertEqual(error.details['status'], 'undecidable_incomplete_predecessor')

    def test_advancing_outcomes_need_sealed_evidence(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        for outcome in search.ADVANCING:
            self.rejected('evidence_not_sealed', 'record_run_outcome', session_id=SESSION, run_id=trial.run_id, outcome=outcome, fencing_token=self.token, evidence_ref='runs/x')
        self.client.mutate('record_run_progress', session_id=SESSION, run_id=trial.run_id, phase='sealed', fencing_token=self.token)
        self.client.mutate('record_run_outcome', session_id=SESSION, run_id=trial.run_id, outcome=search.PASS, fencing_token=self.token, evidence_ref='runs/x')

    def test_phases_only_move_forward_and_launching_is_fenced(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        progress = dict(session_id=SESSION, run_id=trial.run_id, fencing_token=self.token)
        self.client.mutate('record_run_progress', phase='launching', **progress)
        self.rejected('phase_regressed', 'record_run_progress', phase='launching', **progress)
        self.client.mutate('record_run_progress', phase='running', **progress)
        self.rejected('phase_regressed', 'record_run_progress', phase='launching', **progress)
        self.rejected('bad_request', 'record_run_progress', phase='dispatched', **progress)

    def test_launching_refuses_a_closed_window_a_stale_token_and_cleanup(self):
        trial = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(trial))
        progress = dict(session_id=SESSION, run_id=trial.run_id, phase='launching')
        self.stack.step(self.stack.registry.launch_window_s + 1)
        self.client.call('renew_control', session_id=SESSION, fencing_token=self.token)
        self.rejected('launch_window_closed', 'record_run_progress', fencing_token=self.token, **progress)
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        self.rejected('stale_fencing_token', 'record_run_progress', fencing_token=self.token, **progress)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_run_progress', fencing_token=token, **progress)
        self.assertEqual(caught.exception.code, 'bad_state', 'an interrupted run is not launchable under any token')

    def test_a_replayed_grant_after_launching_began_authorizes_nothing(self):
        trial = self.next()
        params = self.dispatch(trial)
        self.client.mutate('dispatch_run', 'd1', **params)
        self.client.mutate('record_run_progress', session_id=SESSION, run_id=trial.run_id, phase='launching', fencing_token=self.token)
        self.assertFalse(self.client.mutate('dispatch_run', 'd1', **params)['authorized'])

    def test_a_batch_stop_is_terminal_and_cannot_be_resumed_past(self):
        self.client.mutate('record_batch_stop', session_id=SESSION, outcome=search.INFRASTRUCTURE_FAILURE, fencing_token=self.token, detail='leftover netem on the game host')
        self.rejected('terminal_failure', 'dispatch_run', **self.dispatch())
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=self.good_checks())
        self.assertEqual(caught.exception.code, 'terminal_failure')
        self.rejected('bad_request', 'record_batch_stop', session_id=SESSION, outcome=search.PASS, fencing_token=self.token, detail='x')

    def test_resume_needs_every_revalidation_and_the_exact_next_run(self):
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        for name in registry.RESUME_REQUIRED_CHECKS:
            checks = dict(self.good_checks(), **{name: False})
            with self.assertRaises(registry_client.RegistryRejected) as caught:
                other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=checks)
            self.assertEqual(caught.exception.code, 'resume_unverified', name)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=dict(self.good_checks(), manifest_sha256='0' * 64))
        self.assertEqual(caught.exception.code, 'manifest_conflict')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=dict(self.good_checks(), next_run_id='other'))
        self.assertEqual(caught.exception.code, 'illegal_trial')
        self.assertEqual(other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=self.good_checks())['state'], registry.READY)

    def test_resume_is_refused_when_only_a_dependent_path_remains(self):
        first = self.next()
        self.client.mutate('dispatch_run', **self.dispatch(first))
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        other.mutate('record_run_outcome', session_id=SESSION, run_id=first.run_id, outcome=search.INCOMPLETE, fencing_token=token)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=dict(self.good_checks('x'), next_run_id='x'))
        self.assertEqual(caught.exception.code, 'no_untouched_work')
        self.assertEqual(caught.exception.details['status'], 'undecidable_incomplete_predecessor')

    def test_resume_needs_a_live_watchdog(self):
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        self.stack.clock.advance(self.stack.registry.watchdog_stale_s + 1)
        other.call('renew_control', session_id=SESSION, fencing_token=token)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op', checks=self.good_checks())
        self.assertEqual(caught.exception.code, 'watchdog_unhealthy')

    def test_run_records_hold_what_a_controller_needs_to_start_again(self):
        trial = self.next()
        grant = self.client.mutate('dispatch_run', **self.dispatch(trial))
        row = self.client.call('run_records', session_id=SESSION)[0]
        self.assertEqual((row['run_id'], row['phase'], row['state']), (trial.run_id, 'dispatched', 'dispatched'))
        self.assertEqual(row['trial'], trial.to_dict())
        self.assertEqual(row['must_stop_by'], grant['must_stop_by'])

    def test_a_non_capacity_session_has_no_search_to_dispatch(self):
        stack = rf.Stack(self, typed_runs=True)
        import provision_fixtures as pf
        manifest, sha = pf.session_of_kind('do-cal-a', 7200, 'calibration')
        stack.client.register(manifest, sha)
        token = stack.client.acquire('do-cal-a')['fencing_token']
        stack.watchdog.tick()
        stack.client.arm('do-cal-a', manifest, sha, token)
        stack.watchdog.tick()
        stack.create_pair('do-cal-a', token)
        stack.client.mutate('mark_ready', session_id='do-cal-a', fencing_token=token, evidence_ref='readiness/fake.json')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            stack.client.mutate('dispatch_run', session_id='do-cal-a', run_id='r', fencing_token=token, manifest_sha256=sha, estimated_duration_s=10)
        self.assertEqual(caught.exception.code, 'no_workload_plan')


if __name__ == '__main__':
    unittest.main()
