"""B1 of PR 88: no start outlives its authority. A real registry, the real runner and the real agent; delivery delays are real.

The registry cannot reach a guest, so the order of a start against a revocation is defined, not assumed atomic: a takeover or cleanup takes
effect when no grant it found can still be used. These tests hold both sides of that line, with and without a controller.
"""
import concurrent.futures
import contextlib
import io
import json
import time
import types
import unittest
from unittest import mock

import cleanup_ledger
import guest_agent
import guest_runner
import registry
import registry_client
import registry_cli
import registry_fixtures as stacks
import run_executor
import run_fixtures as rf
import session_clock
import test_guest_access as access
import test_guest_runner as runner_tests

SESSION = 'do-cap-1v1g-20261030a'


class RegistrySide(unittest.TestCase):
    def setUp(self):
        self.stack = stacks.Stack(self, typed_runs=True)
        self.manifest, self.sha, self.token, self.ack, self.ids = self.stack.ready(SESSION, cap_s=14400)
        self.client = self.stack.client
        self.registry = self.stack.registry
        self.count = 0

    def grant(self, token=None, role='game', action='smoke'):
        self.count += 1
        grant_id = 'g%d' % self.count
        return self.client.mutate('authorize_guest_action', 'grant:%s' % grant_id, session_id=SESSION, fencing_token=token or self.token, action=action, role=role, grant_id=grant_id)

    def paused(self):
        """A smoke needs a paused session, as on a resume: control re-acquired with nothing outstanding."""
        return self.client.acquire(SESSION, takeover=True)['fencing_token']

    def rejected(self, code, method, **params):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.client.mutate(method, **params)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def status(self):
        return self.registry.status(SESSION)

    def kinds(self):
        return [e['kind'] for e in self.registry.journal(SESSION)]

    def test_an_abort_with_a_grant_outstanding_is_pending_and_says_until_when(self):
        token = self.paused()
        grant = self.grant(token)
        self.client.mutate('operator_abort', session_id=SESSION, reason='operator')
        status = self.status()
        self.assertEqual(status['state'], registry.REVOCATION_PENDING)
        self.assertEqual(status['revocation']['target_state'], registry.DELETING)
        self.assertEqual(status['revocation']['effective_at'], grant['conclusive_at'])
        self.assertEqual([g['grant_id'] for g in status['revocation']['grants']], [grant['grant_id']])
        self.assertIsNotNone(status['cleanup']['requested_at'], 'the intent is durable at once; only its effect waits')
        self.assertIn('revocation_pending', self.kinds())
        self.rejected('cleanup_in_progress', 'authorize_guest_action', session_id=SESSION, fencing_token=token, action='smoke', role='game', grant_id='after-abort')
        self.stack.clock.advance(session_clock.parse(grant['conclusive_at']) - self.registry.peek_now())
        self.assertEqual(self.status()['state'], registry.DELETING, 'the view needs no write to see conclusive expiry')
        self.client.mutate('record_measurement', session_id=SESSION, fencing_token=token, outcome='x')
        self.assertEqual(self.registry.guest_grants(SESSION)[0]['state'], 'expired')
        self.assertIn('revocation_effective', self.kinds())

    def test_a_grant_the_guest_answered_holds_nothing(self):
        token = self.paused()
        grant = self.grant(token)
        self.client.mutate('resolve_guest_grant', session_id=SESSION, grant_id=grant['grant_id'], resolution='started')
        self.client.mutate('operator_abort', session_id=SESSION, reason='operator')
        self.assertEqual(self.status()['state'], registry.DELETING)
        self.assertNotIn('revocation_pending', self.kinds())

    def test_cleanup_ack_rpc_and_cli_lists_share_pending_and_effective_state(self):
        for method in ('operator_abort', 'request_cleanup'):
            with self.subTest(method=method):
                self.setUp()
                token = self.paused()
                grants = [self.grant(token, role=role) for role in ('game', 'bot')]
                params = dict(session_id=SESSION, reason='done')
                if method == 'request_cleanup':
                    params['fencing_token'] = token
                for count in (2, 1, 0):
                    response = self.registry.rpc(dict(method=method, params=params))
                    self.assertTrue(response['ok'], response)
                    status = self.status()
                    self.assertEqual(status['state'], registry.REVOCATION_PENDING if count else registry.DELETING)
                    self.assertEqual(len(status['revocation']['grants']), count)
                    output = io.StringIO()
                    with mock.patch.object(registry_cli.registry_mod, 'Registry', return_value=self.registry), mock.patch.object(self.registry, 'close'), contextlib.redirect_stdout(output):
                        registry_cli.read_command(types.SimpleNamespace(command='sessions', state_dir='unused'))
                    views = [response['result'], self.registry.rpc(dict(method='list_sessions'))['result'][0],
                             json.loads(output.getvalue())[0]]
                    for view in views:
                        self.assertEqual(view['state'], status['state'])
                        self.assertEqual(view['revocation'], status['revocation'])
                    if count:
                        self.client.mutate('resolve_guest_grant', session_id=SESSION,
                                           grant_id=grants[2 - count]['grant_id'], resolution='started')

    def test_a_takeover_is_pending_until_a_fence_acknowledgement_and_only_the_current_token_can_give_it(self):
        old = self.paused()
        grant = self.grant(old, role='bot')
        new = self.paused()
        status = self.status()
        self.assertEqual((status['state'], status['revocation']['target_state']), (registry.REVOCATION_PENDING, registry.PAUSED))
        refused = self.rejected('revocation_pending', 'authorize_guest_action', session_id=SESSION, fencing_token=new, action='smoke', role='game', grant_id='next')
        self.assertEqual(refused.details['roles'], ['bot'])
        self.assertLessEqual(refused.details['retry_after_s'], registry.GUEST_ACTION_TTL_S + registry.GUEST_COMMIT_SLACK_S)
        self.rejected('revocation_pending', 'record_resume', session_id=SESSION, fencing_token=new, operator_request_ref='r', checks=dict(x=True))
        self.rejected('stale_fencing_token', 'report_guest_fence', session_id=SESSION, fencing_token=old, role='bot')
        self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=new, role='game')
        self.assertEqual(self.status()['state'], registry.REVOCATION_PENDING, 'the other host says nothing about this one')
        settled = self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=new, role='bot', consumed=[])
        self.assertEqual(settled['settled'], [grant['grant_id']])
        self.assertEqual(self.status()['state'], registry.PAUSED)
        self.assertIn('revocation_effective', self.kinds())
        self.grant(new)

    def test_the_acknowledgement_keeps_what_the_guest_said_it_used(self):
        old = self.paused()
        grant = self.grant(old)
        new = self.paused()
        self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=new, role='game', consumed=[grant['grant_id']])
        self.assertEqual(self.registry.guest_grants(SESSION)[0]['state'], 'started')

    def test_a_lost_answer_resolves_nothing_until_expiry(self):
        token = self.paused()
        grant = self.grant(token)
        self.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        self.assertTrue(self.status()['revocation']['pending'])
        self.assertEqual(self.registry.guest_grants(SESSION)[0]['state'], 'outstanding')
        self.stack.clock.advance(session_clock.parse(grant['conclusive_at']) - self.registry.peek_now() + 0.001)
        self.assertFalse(self.status()['revocation']['pending'])

    def test_a_replayed_answer_never_outlives_its_gate(self):
        token = self.paused()
        params = dict(session_id=SESSION, fencing_token=token, action='smoke', role='game', grant_id='lost-ack')
        first = self.client.mutate('authorize_guest_action', 'same-request', **params)
        self.assertEqual(self.client.mutate('authorize_guest_action', 'same-request', **params)['conclusive_at'], first['conclusive_at'], 'a lost ack replays the same commit')
        self.client.mutate('operator_abort', session_id=SESSION, reason='operator')
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.client.mutate('authorize_guest_action', 'same-request', **params)
        self.assertEqual(caught.exception.code, 'cleanup_in_progress')

    def test_either_commit_order_is_serialized(self):
        token = self.paused()
        self.client.mutate('operator_abort', session_id=SESSION, reason='first')
        self.rejected('cleanup_in_progress', 'authorize_guest_action', session_id=SESSION, fencing_token=token, action='smoke', role='game', grant_id='late')
        self.assertEqual(self.registry.guest_grants(SESSION), [], 'revocation first: no intent exists to wait for')

    def test_no_grant_is_conclusive_past_the_lease_or_the_delete_cutoff(self):
        token = self.paused()
        status = self.status()
        cutoff = session_clock.parse(status['cleanup_c_utc']) - registry.DELETE_MARGIN_S
        while self.registry.peek_now() < cutoff - registry.GUEST_COMMIT_SLACK_S - 5:
            self.stack.clock.advance(min(60.0, cutoff - registry.GUEST_COMMIT_SLACK_S - 5 - self.registry.peek_now()))
            self.client.call('renew_control', session_id=SESSION, fencing_token=token)
        grant = self.grant(token)
        self.assertLessEqual(session_clock.parse(grant['conclusive_at']), cutoff)
        self.assertLessEqual(grant['ttl_s'], 5.0 + 1e-6)
        lease = session_clock.parse(self.status()['lease_expires_at'])
        self.assertLessEqual(session_clock.parse(grant['conclusive_at']), lease)

    def test_the_watchdog_holds_destructive_requests_for_the_pending_seconds_only(self):
        token = self.paused()
        grant = self.grant(token)
        self.client.mutate('operator_abort', session_id=SESSION, reason='operator')
        started = self.registry.peek_now()
        self.stack.run_until(lambda: any(a['op'] in cleanup_ledger.DELETE_OPS.values() for a in self.registry.attempts(SESSION)), limit_s=60.0)
        first_delete = min(session_clock.parse(a['started_at']) for a in self.registry.attempts(SESSION) if a['op'] in cleanup_ledger.DELETE_OPS.values())
        self.assertGreaterEqual(first_delete, session_clock.parse(grant['conclusive_at']))
        self.assertLess(first_delete - started, 60.0, 'the hold ends with the grant, whether or not any controller exists')

    def test_time_gone_unverifiable_releases_the_hold_at_once(self):
        token = self.paused()
        self.grant(token)
        self.client.mutate('operator_abort', session_id=SESSION, reason='operator')
        self.assertTrue(self.status()['revocation']['pending'])
        with mock.patch.object(self.registry, 'time_uncertain', return_value=True):
            self.assertEqual(self.registry.pending_revocation(self.registry.session_row(SESSION), self.registry.peek_now()), [], 'a frozen effective clock must not hold a delete')

    def test_the_hold_cannot_reach_past_c(self):
        token = self.paused()
        status = self.status()
        c = session_clock.parse(status['cleanup_c_utc'])
        while self.registry.peek_now() < c - registry.DELETE_MARGIN_S - registry.GUEST_COMMIT_SLACK_S - 0.5:
            self.stack.clock.advance(min(60.0, c - registry.DELETE_MARGIN_S - registry.GUEST_COMMIT_SLACK_S - 0.5 - self.registry.peek_now()))
            self.client.call('renew_control', session_id=SESSION, fencing_token=token)
        grant = self.grant(token)
        self.stack.run_until(lambda: self.registry.session_row(SESSION)['cleanup_requested_at'] is not None, limit_s=30.0)
        self.assertEqual(self.registry.pending_revocation(self.registry.session_row(SESSION), c - registry.DELETE_MARGIN_S), [])
        self.assertLessEqual(session_clock.parse(grant['conclusive_at']), c - registry.DELETE_MARGIN_S)


class RealRunnerSide(runner_tests.GuestFixture):
    """The registry's clock is scripted, and the guest's delay is real, so the elapsed window is what actually refuses."""

    def setUp(self):
        super().setUp()
        self.stack = stacks.Stack(self, typed_runs=True)
        self.manifest_r, self.sha_r, self.token_r, _, _ = self.stack.ready(SESSION, cap_s=14400)
        self.client = self.stack.client
        self.registry = self.stack.registry
        self.token = self.client.acquire(SESSION, takeover=True)['fencing_token']

    def issue(self, plan, ttl_s=None):
        """Prepare on the real guest, then commit in the real registry. A wall limit an hour off cannot help: the elapsed clock must refuse."""
        minted = self.do(plan['role'], 'grant_prepare', '--session', plan['session_id'], '--token', str(plan['fencing_token']))
        self.assertTrue(minted['ok'], minted)
        with mock.patch.object(registry, 'GUEST_ACTION_TTL_S', ttl_s or registry.GUEST_ACTION_TTL_S):
            grant = self.client.mutate('authorize_guest_action', session_id=SESSION, fencing_token=self.token, action='smoke', role=plan['role'], grant_id=minted['grant_id'])
        return dict(plan, launch_not_after_wall=time.time() + 3600, grant=dict(id=grant['grant_id'], ttl_s=grant['ttl_s'])), grant

    def plan_for(self, role='game', trial=None):
        return self.plan(role=role, trial=trial, token=self.token, bound_s=5.0, stop_grace_s=0.2)

    def workload_started(self, plan):
        summaries = [r for r in guest_runner.inventory(guest_runner.Host(self.guests.runner_root(plan['role']))) if r['run_id'] == plan['run_id']]
        return [s for s in summaries if s['processes']]

    def finish(self, plan, token=None):
        self.stop(plan, token=token or self.token)
        self.seal(plan, token or self.token)

    def test_a_delayed_workload_after_abort_with_no_controller_is_refused_once_the_revocation_is_effective(self):
        self.fence(token=self.token)
        plan, grant = self.issue(self.plan_for(), ttl_s=0.3)
        self.client.mutate('operator_abort', session_id=SESSION, reason='abort, then the controller is gone')
        self.assertEqual(self.registry.status(SESSION)['state'], registry.REVOCATION_PENDING)
        time.sleep(0.4)
        self.stack.clock.advance(session_clock.parse(grant['conclusive_at']) - self.registry.peek_now())
        self.assertEqual(self.registry.status(SESSION)['state'], registry.DELETING)
        answer = self.start(plan)
        self.assertEqual((answer['ok'], answer['code']), (False, 'launch_window_closed'))
        self.assertEqual(self.workload_started(plan), [])

    def test_a_delayed_workload_after_takeover_is_refused_by_the_acknowledged_fence(self):
        self.fence(token=self.token)
        old_token = self.token
        plan, grant = self.issue(self.plan_for())
        self.token = self.client.acquire(SESSION, takeover=True)['fencing_token']
        self.assertEqual(self.registry.status(SESSION)['state'], registry.REVOCATION_PENDING)
        fenced = self.fence(token=self.token)
        self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=self.token, role='game', consumed=fenced['grants_consumed'])
        self.assertEqual(self.registry.status(SESSION)['state'], registry.PAUSED, 'effective at the guest\'s own acknowledgement')
        answer = self.start(plan)
        self.assertEqual((answer['ok'], answer['code']), (False, 'stale_fence'))
        self.assertEqual(self.workload_started(plan), [])
        self.assertEqual(plan['fencing_token'], old_token)

    def test_a_delivery_inside_the_pending_window_is_ordered_before_the_revocation_and_accounted_for(self):
        self.fence(token=self.token)
        plan, grant = self.issue(self.plan_for())
        self.client.mutate('operator_abort', session_id=SESSION, reason='abort while the grant is on its way')
        answer = self.start(plan)
        self.assertTrue(answer['ok'], 'the grant predates the commit and can still be used: this is the one case no check can refuse')
        status = self.registry.status(SESSION)
        self.assertEqual(status['state'], registry.REVOCATION_PENDING, 'the record says so: the session is not yet deleting')
        self.assertEqual([g['grant_id'] for g in status['revocation']['grants']], [grant['grant_id']])
        self.assertEqual(self.registry.attempts(SESSION), [], 'nothing destructive has been issued')
        fenced = self.do('game', 'fence', '--session', runner_tests.SESSION, '--token', str(self.token), '--close', 'abort')
        self.assertIn(grant['grant_id'], fenced['grants_consumed'], 'a returning controller can see the use whose answer was lost')
        self.assertEqual([r['run_id'] for r in fenced['runs']], [plan['run_id']], 'and it knows what to stop')
        self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=self.token, role='game', closed=True, consumed=fenced['grants_consumed'])
        self.assertEqual(self.registry.guest_grants(SESSION)[-1]['state'], 'started')
        self.finish(plan)

    def test_the_wall_clock_is_not_what_ends_a_grant(self):
        self.fence(token=self.token)
        plan, _ = self.issue(self.plan_for(), ttl_s=0.2)
        self.assertGreater(plan['launch_not_after_wall'], time.time() + 3000, 'a guest whose clock is an hour behind')
        time.sleep(0.3)
        answer = self.start(plan)
        self.assertEqual((answer['ok'], answer['code']), (False, 'launch_window_closed'))

    def test_a_replayed_grant_starts_nothing_even_after_the_first_use_finished(self):
        self.fence(token=self.token)
        plan, _ = self.issue(self.plan_for())
        self.assertTrue(self.start(plan)['ok'])
        self.finish(plan)
        another = dict(self.plan_for(trial=self.trial(2, 50)), grant=plan['grant'], launch_not_after_wall=plan['launch_not_after_wall'])
        answer = self.start(another)
        self.assertEqual((answer['ok'], answer['code']), (False, 'grant_replayed'))
        self.assertEqual(self.workload_started(another), [])

    def test_a_grant_this_host_never_minted_or_from_another_token_starts_nothing(self):
        self.fence(token=self.token)
        plan = dict(self.plan_for(), grant=dict(id='0' * 32, ttl_s=10.0))
        self.assertEqual(self.start(plan)['code'], 'grant_unknown')
        self.assertEqual(self.start(dict(self.plan_for(), grant=dict(id='not a grant', ttl_s=10.0)))['code'], 'grant_unknown')
        self.assertEqual(self.start(dict(self.plan_for(), grant=None))['code'], 'grant_unknown')

    def test_a_grant_minted_before_a_reboot_starts_nothing(self):
        self.fence(token=self.token)
        plan, _ = self.issue(self.plan_for())
        path = guest_runner.Host(self.guests.runner_root('game')).grant_path(plan['grant']['id'])
        record = guest_runner.read_json(path)
        path.write_text(json.dumps(dict(record, boot_id='an earlier boot')))
        answer = self.start(plan)
        self.assertEqual((answer['ok'], answer['code']), (False, 'launch_window_closed'))

    def test_concurrent_start_and_fence_have_one_order_and_the_fence_always_knows_it(self):
        for attempt in range(4):
            with self.subTest(attempt=attempt):
                self.fence(token=self.token)
                plan, _ = self.issue(self.plan_for(trial=self.trial(attempt + 1, 25 * (attempt + 1))))
                new_token = self.client.acquire(SESSION, takeover=True)['fencing_token']
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    started = pool.submit(self.start, plan)
                    fenced = pool.submit(self.fence, 'game', new_token)
                    answer, fence = started.result(), fenced.result()
                listed = [r for r in fence['runs'] if r['run_id'] == plan['run_id']]
                if answer['ok']:
                    self.assertEqual(len(listed), 1, 'the fence was raised after the start and names it, under the host lock')
                    self.assertIn(plan['grant']['id'], fence['grants_consumed'])
                    self.stop(plan, token=new_token)
                    self.seal(plan, new_token)
                else:
                    self.assertEqual(answer['code'], 'stale_fence')
                    self.assertEqual(self.workload_started(plan), [])
                self.token = new_token
                self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=new_token, role='game', consumed=fence['grants_consumed'])

    def test_a_fence_that_rises_between_the_last_look_and_the_fork_ends_the_workload_at_once(self):
        self.fence(token=self.token)
        plan, _ = self.issue(self.plan_for())
        tree = self.tree(plan)
        tree.mkdir(parents=True)
        (tree / 'plan.json').write_text(json.dumps(plan))
        host = guest_runner.Host(self.guests.runner_root('game'))
        real = guest_runner._spawn

        def raised_during(spec, run_dir, placeholder):
            guest_runner.cmd_fence(types.SimpleNamespace(session=runner_tests.SESSION, token=self.token + 1), host)
            return real(spec, run_dir, placeholder)
        with mock.patch.object(guest_runner, '_spawn', side_effect=raised_during):
            guest_runner.cmd_supervise(types.SimpleNamespace(run_dir=str(tree)), host)
        result = guest_runner.read_json(tree / 'result.json')
        self.assertEqual(result['stop_reason'], 'launch_refused:stale_fence_after_spawn')
        self.assertLess(result['elapsed_s'], 2.0)
        identity = guest_runner.read_json(tree / 'identity.json')
        self.assertFalse(any(guest_runner.same_process(item) for item in identity['processes'].values()))

    def test_a_pause_past_the_slack_between_the_last_look_and_the_fork_ends_the_workload_at_once(self):
        self.fence(token=self.token)
        plan, _ = self.issue(self.plan_for())
        plan = dict(plan, grant=dict(plan['grant'], ttl_s=0.1))
        tree = self.tree(plan)
        tree.mkdir(parents=True)
        (tree / 'plan.json').write_text(json.dumps(plan))
        host = guest_runner.Host(self.guests.runner_root('game'))
        real = guest_runner._spawn
        with mock.patch.object(guest_runner, 'GRANT_COMMIT_SLACK_S', 0.2), mock.patch.object(guest_runner, '_spawn', side_effect=lambda *a: (time.sleep(0.4), real(*a))[1]):
            guest_runner.cmd_supervise(types.SimpleNamespace(run_dir=str(tree)), host)
        self.assertEqual(guest_runner.read_json(tree / 'result.json')['stop_reason'], 'launch_refused:grant_outlived_after_spawn')


class RealAgentSide(access.SmokeAuthority):
    """The same line for a smoke, through the real agent and its real helper, with a real registry on the far side."""

    def setUp(self):
        super().setUp()
        self.stack = stacks.Stack(self, typed_runs=True)
        _, _, token, _, _ = self.stack.ready(SESSION, cap_s=14400)
        self.client = self.stack.client
        self.registry = self.stack.registry
        self.reg_token = self.client.acquire(SESSION, takeover=True)['fencing_token']

    def smoke_args(self, ttl_s=None, token=1, smoke_id='1'):
        """The prepare ran on the real agent, the commit in the real registry. The wall limit is far off, so only the elapsed clock can refuse."""
        minted = guest_agent.cmd_grant_prepare(types.SimpleNamespace(session=self.SESSION, token=token))
        with mock.patch.object(registry, 'GUEST_ACTION_TTL_S', ttl_s or registry.GUEST_ACTION_TTL_S):
            grant = self.client.mutate('authorize_guest_action', session_id=SESSION, fencing_token=self.reg_token, action='smoke', role='game', grant_id=minted['grant_id'])
        return grant, types.SimpleNamespace(session=self.SESSION, token=token, not_after_wall=time.time() + 3600, grant_id=grant['grant_id'], grant_ttl_s=grant['ttl_s'],
                                            smoke_id=smoke_id, wait_s=1, lifetime_s=30.0)

    def test_a_delayed_smoke_after_abort_with_no_controller_is_refused_once_effective(self):
        grant, args = self.smoke_args(ttl_s=0.2)
        self.client.mutate('operator_abort', session_id=SESSION, reason='abort, then the controller is gone')
        self.assertEqual(self.registry.status(SESSION)['state'], registry.REVOCATION_PENDING)
        time.sleep(0.3)
        self.stack.clock.advance(session_clock.parse(grant['conclusive_at']) - self.registry.peek_now())
        self.assertEqual(self.registry.status(SESSION)['state'], registry.DELETING)
        with self.assertRaises(guest_agent.Refused) as caught:
            guest_agent.cmd_smoke_game_start(args)
        self.assertEqual(caught.exception.code, 'authorization_expired')
        self.assertIsNone(guest_agent.read_json(guest_agent.bounded_paths('readiness-game')[0]))

    def test_a_delayed_smoke_after_takeover_is_refused_by_the_acknowledged_fence(self):
        _, args = self.smoke_args()
        new = self.client.acquire(SESSION, takeover=True)['fencing_token']
        minted = guest_agent.cmd_grant_prepare(types.SimpleNamespace(session=self.SESSION, token=2))
        self.assertTrue(minted['raised'], 'preparing under the new token is itself the fence')
        self.client.mutate('report_guest_fence', session_id=SESSION, fencing_token=new, role='game')
        self.assertEqual(self.registry.status(SESSION)['state'], registry.PAUSED)
        with self.assertRaises(guest_agent.Refused) as caught:
            guest_agent.cmd_smoke_game_start(args)
        self.assertEqual(caught.exception.code, 'stale_fence')

    def test_a_replayed_smoke_grant_starts_nothing(self):
        _, args = self.smoke_args()
        self.addCleanup(self.kill_everything)
        guest_agent.cmd_smoke_game_start(args)
        guest_agent.cmd_smoke_game_stop(types.SimpleNamespace(session=self.SESSION, token=1, smoke_id='1'))
        with self.assertRaises(guest_agent.Refused) as caught:
            guest_agent.cmd_smoke_game_start(types.SimpleNamespace(**dict(vars(args), smoke_id='2')))
        self.assertEqual(caught.exception.code, 'grant_replayed')

    def test_the_smoke_wall_clock_is_not_what_ends_a_grant(self):
        _, args = self.smoke_args(ttl_s=0.1)
        time.sleep(0.2)
        with self.assertRaises(guest_agent.Refused) as caught:
            guest_agent.cmd_smoke_game_start(args)
        self.assertEqual(caught.exception.code, 'authorization_expired')

    def test_a_grant_from_another_token_starts_nothing(self):
        _, args = self.smoke_args()
        minted = guest_agent.cmd_grant_prepare(types.SimpleNamespace(session=self.SESSION, token=1))
        path = guest_agent.grant_path(minted['grant_id'])
        guest_agent.atomic_json(path, dict(guest_agent.read_json(path), token=9))
        with self.assertRaises(guest_agent.Refused) as caught:
            guest_agent.cmd_smoke_game_start(types.SimpleNamespace(**dict(vars(args), grant_id=minted['grant_id'])))
        self.assertEqual(caught.exception.code, 'grant_mismatch')


for _name in dir(access.SmokeAuthority):      # this class is here for its setup: the parent's own tests already run in their own module
    if _name.startswith('test_'):
        setattr(RealAgentSide, _name, RealAgentSide.__dict__.get(_name))


class ThroughTheController(unittest.TestCase):
    """The controller's half, on the scripted fake guest that holds to the same rules."""

    def setUp(self):
        self.sim = rf.RunSim(self)
        self.addCleanup(rf.make_writable, self.sim.stack.root)
        self.sim.ready()
        self.guests = self.sim.guests

    def status(self):
        return self.sim.status_now()

    def test_every_start_leaves_a_grant_that_is_resolved_or_expired(self):
        executor = self.sim.executor()
        executor.execute()
        states = {g['state'] for g in self.sim.stack.registry.guest_grants(self.sim.session_id)}
        self.assertNotIn('outstanding', states)
        self.assertIn('started', states)

    def test_a_crash_right_after_authorizing_leaves_a_pending_takeover_that_the_next_prepare_settles(self):
        executor = self.sim.executor(failpoint=rf.crash_at('after_game_authorized'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        new, control = self.sim.controller()
        self.assertTrue(control['revocation']['pending'])
        self.assertEqual(self.status()['state'], registry.REVOCATION_PENDING)
        new.prepare()
        self.assertEqual(self.status()['state'], registry.PAUSED, 'both fences acknowledged')
        self.assertEqual([g['state'] for g in self.sim.stack.registry.guest_grants(self.sim.session_id) if g['action'] == 'launch_run'], ['fenced'])

    def test_a_crash_then_an_abort_with_no_controller_holds_deletion_until_expiry_and_no_later(self):
        executor = self.sim.executor(failpoint=rf.crash_at('after_game_authorized'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.sim.stack.registry.operator_abort(self.sim.session_id, 'operator')
        self.assertEqual(self.status()['state'], registry.REVOCATION_PENDING)
        grant = next(g for g in self.sim.stack.registry.guest_grants(self.sim.session_id) if g['state'] == 'outstanding')
        self.sim.sleep(session_clock.parse(grant['conclusive_at']) - self.sim.stack.registry.peek_now() + 0.001)
        self.assertEqual(self.status()['state'], registry.DELETING)

    def test_a_lease_check_failing_during_a_smoke_does_not_settle_its_grant(self):
        crashed = self.sim.executor(failpoint=rf.crash_at('before_dispatch_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            crashed.execute()
        executor, _ = self.sim.controller()
        executor.prepare()
        real = executor.guests.run

        def lease_gone_during_the_command(role, argv, timeout_s, on_wait=None):
            if 'smoke_game_start' in argv:
                raise run_executor.ControlLost('lease_expired', 'seen while waiting, so whether the start landed is unknown')
            return real(role, argv, timeout_s, on_wait)
        executor.guests.run = lease_gone_during_the_command
        with self.assertRaises(run_executor.ControlLost):
            executor._granted_agent('game', 'smoke_game_start', '--smoke-id', 'x')
        self.assertEqual(self.sim.stack.registry.guest_grants(self.sim.session_id)[-1]['state'], 'outstanding')

    def test_a_refusal_from_the_guest_does_settle_its_grant(self):
        crashed = self.sim.executor(failpoint=rf.crash_at('before_dispatch_commit'))
        with self.assertRaises(rf.SimulatedCrash):
            crashed.execute()
        old, _ = self.sim.controller()
        old.prepare()
        grant = old._authorize('smoke', 'game')
        real = old.guests.run

        def closed_on_arrival(role, argv, timeout_s, on_wait=None):
            if 'smoke_game_start' in argv:
                self.guests.hosts['game'].fence = dict(self.guests.hosts['game'].fence, closed='abort')
            return real(role, argv, timeout_s, on_wait)
        old.guests.run = closed_on_arrival
        old._authorize = lambda *a, **k: grant
        with self.assertRaises(run_executor.CleanupStarted):
            old._granted_agent('game', 'smoke_game_start', '--smoke-id', 'x')
        self.assertEqual(self.sim.stack.registry.guest_grants(self.sim.session_id)[-1]['state'], 'refused')

    def test_a_lost_start_reply_leaves_one_grant_and_never_a_second_start(self):
        self.guests.lost_answer.add(('game', 'start'))
        self.sim.executor().execute()
        self.assertEqual(len([s for s in self.guests.runner_steps('game', 'start')]), 1)
        launch = [g for g in self.sim.stack.registry.guest_grants(self.sim.session_id) if g['action'] == 'launch_run']
        self.assertEqual(len(launch), 1, 'one grant, used at most once')

    def test_a_revocation_pending_at_resume_is_waited_out_or_refused_by_the_registry(self):
        executor = self.sim.executor(failpoint=rf.crash_at('after_game_authorized'))
        with self.assertRaises(rf.SimulatedCrash):
            executor.execute()
        self.guests.unreachable.add(('bot', 'fence'))
        new, control = self.sim.controller()
        resumed = new.resume('operator', control)
        self.assertFalse(resumed['resumed'], 'a host that cannot acknowledge its fence does not pass a resume')


if __name__ == '__main__':
    unittest.main()
