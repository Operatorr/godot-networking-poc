"""Pre-create acknowledgement, fencing, durable transitions and independent outcome fields."""
import contextlib
import io
import json
import os
import pathlib
import sqlite3
import stat
import tempfile
import unittest

import admission
import do_session
import fixture_support as fx
import cleanup_provider
import create_evidence
import registry
import registry_client
import registry_fixtures as rf
import search
import session_clock

SESSION = 'do-cap-1v1g-20261030a'


class DropResponse:
    """The write applies, but the acknowledgement is lost on the way back."""

    def __init__(self, inner, method, times=1):
        self.inner, self.method, self.remaining = inner, method, times

    def __call__(self, request):
        response = self.inner(request)
        if request['method'] == self.method and self.remaining > 0:
            self.remaining -= 1
            raise registry_client.TransportError('connection lost after the write')
        return response


class Unreachable:
    def __call__(self, request):
        raise registry_client.TransportError('no route to management host')


def storage_failure(point):
    def failpoint(name):
        if name == point:
            raise sqlite3.OperationalError('disk I/O error')
    return failpoint


class RegistryStateTests(unittest.TestCase):
    def test_init_is_create_only_and_restricted(self):
        with tempfile.TemporaryDirectory() as root:
            state = pathlib.Path(root) / 'state'
            registry.Registry.init(state, 'r', 'w')
            self.assertEqual(stat.S_IMODE(os.stat(state).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(state / registry.DB_NAME).st_mode), 0o600)
            with self.assertRaises(registry.RegistryUnavailable):
                registry.Registry.init(state, 'other', 'other')

    def test_missing_state_fails_instead_of_recreating_an_empty_registry(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(registry.RegistryUnavailable):
                registry.Registry(pathlib.Path(root) / 'gone')
            self.assertEqual(list(pathlib.Path(root).iterdir()), [])

    def test_incomplete_initialization_is_unusable(self):
        with tempfile.TemporaryDirectory() as root:
            state = pathlib.Path(root)
            (state / registry.DB_NAME).write_bytes(b'')
            with self.assertRaises(registry.RegistryUnavailable):
                registry.Registry(state)


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        self.manifest, self.sha = fx.session_manifest(SESSION)

    def rejected(self, code, method, **params):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.mutate(method, **params)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_registration_persists_manifest_ownership_and_intents(self):
        ack = self.stack.client.register(self.manifest, self.sha)
        self.assertEqual(ack['manifest_sha256'], self.sha)
        kinds = sorted(i['kind'] for i in ack['intents'])
        self.assertEqual(kinds, ['droplet', 'droplet', 'firewall', 'tag', 'tag', 'tag'])
        reopened = self.stack.open_registry()
        self.assertEqual(reopened.manifest(SESSION), self.manifest)
        self.assertEqual(reopened.status(SESSION)['state'], registry.REGISTERED)

    def test_changed_or_foreign_manifests_are_refused(self):
        changed = json.loads(json.dumps(self.manifest))
        changed['limits']['max_session_duration_s'] += 1
        self.rejected('manifest_rejected', 'register_session', manifest=changed, manifest_sha256=self.sha)
        for section, field in (('registry_id', 'wrong_registry'), ('identity', 'wrong_watchdog')):
            manifest, sha = fx.session_manifest('do-cap-foreign-' + section.replace('_', ''))
            manifest['watchdog'][section] = 'somewhere-else'
            import manifest as manifest_mod
            self.rejected(field, 'register_session', manifest=manifest, manifest_sha256=manifest_mod.manifest_sha256(manifest))

    def test_second_manifest_for_a_session_is_a_conflict_not_a_replacement(self):
        self.stack.client.register(self.manifest, self.sha)
        other, other_sha = fx.session_manifest(SESSION, cap_s=7200)
        self.rejected('manifest_conflict', 'register_session', manifest=other, manifest_sha256=other_sha)
        self.assertEqual(self.stack.registry.manifest(SESSION), self.manifest)

    def test_credential_values_are_refused_and_never_stored(self):
        token = 'dop_v1_' + 'a' * 64
        self.stack.client.register(self.manifest, self.sha)
        control = self.stack.client.acquire(SESSION)
        self.rejected('secret_value_rejected', 'record_evidence', session_id=SESSION,
                      fencing_token=control['fencing_token'], status='partial', ref=token)
        self.assertNotIn(token.encode(), self.stack.state_bytes())


class PreCreateAcknowledgementTests(unittest.TestCase):
    """Criterion 1: no provider create without a durable, acknowledged deadline."""

    def setUp(self):
        self.stack = rf.Stack(self)
        self.creates = []

    def create_fn(self, grant):
        self.creates.append(grant['intent_id'])
        return 'id-' + str(len(self.creates))

    def try_create(self, token, client=None, session_id=SESSION):
        (client or self.stack.client).guarded_create(session_id, session_id + ':droplet:game', token, self.create_fn, lambda g: None)

    def assert_refused(self, code, token, client=None):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.try_create(token, client=client)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.creates, [])

    def test_create_without_arming_is_refused(self):
        _, _, token = self.stack.registered(SESSION)
        self.assert_refused('not_armed', token)

    def test_arming_needs_a_healthy_watchdog_that_acknowledged_the_manifest(self):
        manifest, sha, token = self.stack.registered(SESSION)
        # The fixture's start() wrote a fresh heartbeat, but no tick has acknowledged this manifest.
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.arm(SESSION, manifest, sha, token)
        self.assertEqual(caught.exception.code, 'watchdog_unacknowledged')
        self.stack.watchdog.tick()
        self.stack.clock.advance(self.stack.registry.watchdog_stale_s + 1)
        self.stack.client.call('renew_control', session_id=SESSION, fencing_token=token)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.arm(SESSION, manifest, sha, token)
        self.assertEqual(caught.exception.code, 'watchdog_unhealthy')
        self.assertIsNone(self.stack.registry.status(SESSION)['t0_utc'])

    def test_create_needs_the_watchdog_to_have_seen_the_armed_deadline(self):
        manifest, sha, token = self.stack.registered(SESSION)
        self.stack.watchdog.tick()
        self.stack.client.arm(SESSION, manifest, sha, token)
        self.assert_refused('watchdog_unacknowledged', token)
        self.stack.watchdog.tick()
        self.try_create(token)
        self.assertEqual(len(self.creates), 1)

    def test_create_is_refused_when_the_watchdog_heartbeat_goes_stale(self):
        _, _, token, _ = self.stack.armed(SESSION)
        self.stack.clock.advance(self.stack.registry.watchdog_stale_s + 1)
        self.assert_refused('watchdog_unhealthy', token)

    def test_registry_write_failure_at_each_step_yields_no_create(self):
        manifest, sha = fx.session_manifest(SESSION)
        for point in ('register_session:before_commit', 'acquire_control:before_commit',
                      'arm_session:before_commit', 'begin_create:before_commit'):
            with self.subTest(point=point):
                stack = rf.Stack(self)
                creates = []
                client = stack.client

                def flow():
                    client.register(manifest, sha)
                    token = client.acquire(SESSION)['fencing_token']
                    stack.watchdog.tick()
                    client.arm(SESSION, manifest, sha, token)
                    stack.watchdog.tick()
                    client.guarded_create(SESSION, SESSION + ':droplet:game', token,
                                          lambda g: creates.append(g) or 'x', lambda g: None)

                stack.failpoint = storage_failure(point)
                with self.assertRaises(registry_client.RegistryUnavailable):
                    flow()
                self.assertEqual(creates, [])

    def test_unreachable_registry_yields_no_create(self):
        _, _, token, _ = self.stack.armed(SESSION)
        client = self.stack.new_client('controller-a', transport=Unreachable())
        with self.assertRaises(registry_client.RegistryUnavailable):
            self.try_create(token, client=client)
        self.assertEqual(self.creates, [])

    def test_ack_failing_validation_is_treated_as_no_ack(self):
        manifest, sha, token, ack = self.stack.armed(SESSION)
        for tamper in (dict(durable=False), dict(manifest_sha256='0' * 64),
                       dict(deadline_d_utc=session_clock.iso(session_clock.parse(ack['deadline_d_utc']) + 60)),
                       dict(cleanup_c_utc=session_clock.iso(session_clock.parse(ack['cleanup_c_utc']) + 60))):
            with self.subTest(tamper=sorted(tamper)):
                with self.assertRaises(ValueError):
                    admission.validate_arm_ack(dict(ack, **tamper), manifest, sha)


class ImmutableDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)

    def test_lost_arm_ack_replays_the_original_t0_even_much_later(self):
        manifest, sha, token = self.stack.registered(SESSION)
        self.stack.watchdog.tick()
        client = self.stack.new_client('controller-a', transport=DropResponse(self.stack.transport, 'arm_session'))
        first = client.arm(SESSION, manifest, sha, token, request_id='arm-1')
        self.assertTrue(first['replayed'])
        self.stack.clock.advance(50)
        again = client.arm(SESSION, manifest, sha, token, request_id='arm-1')
        self.assertEqual((first['t0_utc'], first['deadline_d_utc'], first['cleanup_c_utc']),
                         (again['t0_utc'], again['deadline_d_utc'], again['cleanup_c_utc']))
        self.assertEqual(self.stack.registry.status(SESSION)['t0_utc'], first['t0_utc'])

    def test_a_second_arm_is_refused_and_reports_the_original_deadline(self):
        manifest, sha, token, ack = self.stack.armed(SESSION)
        self.stack.clock.advance(30)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.arm(SESSION, manifest, sha, token)
        self.assertEqual(caught.exception.code, 'already_armed')
        self.assertEqual(caught.exception.details['deadline_d_utc'], ack['deadline_d_utc'])

    def test_d_and_c_follow_the_contract(self):
        _, _, _, ack = self.stack.armed(SESSION, cap_s=1800, reserve_s=120)
        self.assertEqual(session_clock.parse(ack['deadline_d_utc']) - session_clock.parse(ack['t0_utc']), 1800)
        self.assertEqual(session_clock.parse(ack['deadline_d_utc']) - session_clock.parse(ack['cleanup_c_utc']), 120)

    def test_storage_refuses_to_change_a_deadline_or_rewrite_history(self):
        self.stack.armed(SESSION)
        db = self.stack.registry.db
        for statement in ("UPDATE sessions SET deadline_d_utc='2099-01-01T00:00:00+00:00'",
                          "UPDATE sessions SET cleanup_c_utc='2099-01-01T00:00:00+00:00'",
                          "UPDATE sessions SET t0_utc='2099-01-01T00:00:00+00:00'",
                          "UPDATE sessions SET cap_s=999999",
                          "UPDATE sessions SET manifest_sha256='x'",
                          "DELETE FROM sessions",
                          "DELETE FROM resources",
                          "UPDATE events SET kind='edited'",
                          "DELETE FROM events"):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)

    def test_journal_chain_detects_tampering(self):
        self.stack.armed(SESSION)
        self.assertTrue(self.stack.registry.verify_journal()['valid'])
        db = self.stack.registry.db
        db.execute('DROP TRIGGER events_no_update')
        db.execute("UPDATE events SET data_json='{}' WHERE seq=2")
        result = self.stack.registry.verify_journal()
        self.assertFalse(result['valid'])
        self.assertEqual(result['broken_at_seq'], 2)

    def test_registry_clock_is_used_not_the_callers(self):
        # No RPC accepts a timestamp, so a skewed laptop has no way to influence t0/D/C.
        for method in registry.Registry.RPC_METHODS:
            parameters = getattr(registry.Registry, method).__code__.co_varnames
            for forbidden in ('now', 't0', 'deadline', 'wall'):
                self.assertNotIn(forbidden, parameters, method)

    def test_planner_takes_t0_from_the_durable_ack(self):
        manifest, sha, _, ack = self.stack.armed(SESSION)
        session_dir = self.stack.root / 'session'
        session_dir.mkdir()
        (session_dir / 'manifest.json').write_text(json.dumps(manifest))
        (session_dir / 'manifest.sha256').write_text(sha + '  manifest.json\n')
        ack_path = self.stack.root / 'ack.json'
        ack_path.write_text(json.dumps(ack))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(do_session.main(['mark-t0', '--session-dir', str(session_dir), '--arm-ack', str(ack_path)]), 0)
        _, _, _, meta = do_session.load_session(session_dir)
        self.assertEqual(meta['t0'], ack['t0_utc'])

    def test_planner_refuses_a_forged_ack(self):
        manifest, sha, _, ack = self.stack.armed(SESSION)
        session_dir = self.stack.root / 'session'
        session_dir.mkdir()
        (session_dir / 'manifest.json').write_text(json.dumps(manifest))
        (session_dir / 'manifest.sha256').write_text(sha + '  manifest.json\n')
        ack_path = self.stack.root / 'ack.json'
        ack_path.write_text(json.dumps(dict(ack, durable=False)))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(do_session.main(['mark-t0', '--session-dir', str(session_dir), '--arm-ack', str(ack_path)]), 2)

    def test_registry_health_drives_planner_admission(self):
        manifest, sha, _, _ = self.stack.armed(SESSION, cap_s=14400)
        state = search.SearchState(SESSION)
        health = self.stack.registry.health(SESSION)
        result = admission.admit(manifest, sha, state, session_clock.iso(self.stack.clock.wall()), health)
        self.assertTrue(result.admitted, result.reasons)
        self.stack.clock.advance(self.stack.registry.watchdog_stale_s + 1)
        stale = self.stack.registry.health(SESSION)
        result = admission.admit(manifest, sha, state, session_clock.iso(self.stack.clock.wall()), stale)
        self.assertFalse(result.admitted)
        self.assertTrue(any('watchdog' in r for r in result.reasons))


# Far longer than any client timeout: the point is that no amount of waiting settles a request.
LONG_AFTER_THE_REQUEST_S = 600


class CreateAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)
        _, _, self.token, _ = self.stack.armed(SESSION)
        self.intent = SESSION + ':droplet:game'
        self.creates = []

    def create(self, grant):
        self.creates.append(grant['intent_id'])
        return self.stack.provider.add_droplet(grant['expected_name'], grant['expected_tags'])

    def find(self, grant):
        for droplet in self.stack.provider.list_droplets_by_tag(rf.fx_tags(SESSION)['session']):
            if droplet['name'] == grant['expected_name']:
                return droplet['id']
        return None

    def settlement(self, grant):
        return self.stack.provider.get_request_settlement(grant['create_request_ref'])

    def guarded(self, create=None, **options):
        return self.stack.client.guarded_create(SESSION, self.intent, self.token, create or self.create, self.find, **options)

    def wait(self, seconds):
        """Pass time as a live controller would, keeping its lease."""
        for _ in range(int(seconds // 60)):
            self.stack.step(60)
            self.stack.registry.renew_control(SESSION, self.token)
        self.stack.step(seconds % 60 or 0)

    def intent_view(self):
        return [i for i in self.stack.registry.status(SESSION)['intents'] if i['intent_id'] == self.intent][0]

    def timed_out_request(self):
        """The provider may still be processing it: the caller only knows it stopped waiting."""
        grants = []

        def still_processing(grant):
            grants.append(grant)
            raise TimeoutError('request timed out, remote outcome unknown')

        with self.assertRaises(TimeoutError):
            self.guarded(still_processing)
        return grants[0]

    def land(self, grant):
        return self.stack.provider.add_droplet(grant['expected_name'], grant['expected_tags'])

    def test_lost_ack_of_a_fresh_grant_is_known_unsent_so_the_create_proceeds(self):
        client = self.stack.new_client('controller-a', transport=DropResponse(self.stack.transport, 'begin_create'))
        client.guarded_create(SESSION, self.intent, self.token, self.create, self.find)
        self.assertEqual(self.creates, [self.intent], 'one create, and only after the unsent grant was recorded')
        self.assertEqual((self.intent_view()['request_count'], self.intent_view()['state']), (2, 'created'))
        self.assertIn('not_sent', [e['data'].get('outcome') for e in self.stack.registry.journal(SESSION)])

    def test_replay_of_a_request_id_someone_else_may_have_held_is_unresolved(self):
        self.stack.client.mutate('begin_create', 'restart-id', session_id=SESSION, intent_id=self.intent, fencing_token=self.token)
        with self.assertRaises(registry_client.CreateUnresolved):
            self.guarded(request_id='restart-id')
        self.assertEqual(self.creates, [], 'a restarted controller cannot know whether its predecessor sent it')

    def test_create_timeout_then_retry_finds_the_landed_resource(self):
        def landed_but_timed_out(grant):
            self.create(grant)
            raise TimeoutError('response lost')

        with self.assertRaises(TimeoutError):
            self.guarded(landed_but_timed_out)
        key = self.guarded()
        self.assertEqual(len(self.creates), 1, 'no blind duplicate')
        self.assertTrue(key.startswith('droplet:'))

    def test_no_amount_of_waiting_permits_a_retry(self):
        self.timed_out_request()
        retries = []
        for _ in range(5):
            with self.assertRaises(registry_client.CreateUnresolved) as caught:
                self.guarded(retries.append)
            self.assertEqual(caught.exception.create_request_ref, self.intent + '#1')
            self.wait(LONG_AFTER_THE_REQUEST_S / 5)
        self.assertEqual(retries, [], 'an empty listing never granted a retry')
        self.assertEqual((self.intent_view()['request_count'], self.intent_view()['state']), (1, 'ambiguous'))

    def test_original_landing_after_every_former_bound_is_adopted_not_duplicated(self):
        grant = self.timed_out_request()
        retries = []
        self.wait(60)   # the review counterexample: an empty listing at +60 used to grant a retry
        with self.assertRaises(registry_client.CreateUnresolved):
            self.guarded(retries.append)
        self.stack.step(5)
        original = self.land(grant)
        self.wait(LONG_AFTER_THE_REQUEST_S)
        key = self.guarded(retries.append)
        self.assertEqual(retries, [])
        self.assertEqual(key, 'droplet:' + original)
        self.assertEqual(self.stack.provider.live_ids()['droplets'], [original], 'no duplicate Droplet')
        self.assertEqual((self.intent_view()['request_count'], self.intent_view()['state']), (1, 'created'))

    def test_receipt_for_this_request_permits_exactly_one_retry(self):
        grant = self.timed_out_request()
        self.stack.provider.issue_receipt(grant['create_request_ref'])
        self.guarded(settlement_fn=self.settlement)
        self.assertEqual(self.creates, [self.intent])
        self.assertEqual((self.intent_view()['request_count'], self.intent_view()['state']), (2, 'created'))
        journal = self.stack.registry.journal(SESSION)
        settled = next(e for e in journal if e['kind'] == 'create_settled')
        self.assertEqual((settled['data']['request_ref'], settled['data']['terminal']), (self.intent + '#1', 'not_created'))

    def test_no_receipt_from_the_adapter_stays_unresolved(self):
        self.timed_out_request()
        with self.assertRaises(registry_client.CreateUnresolved):
            self.guarded(settlement_fn=self.settlement)
        self.assertEqual(self.creates, [])

    def test_created_receipt_adopts_the_exact_id_without_a_retry(self):
        grant = self.timed_out_request()
        original = self.land(grant)
        self.stack.provider.issue_receipt(grant['create_request_ref'], create_evidence.CREATED, original)
        key = self.stack.client.guarded_create(SESSION, self.intent, self.token, self.create, lambda g: None, settlement_fn=self.settlement)
        self.assertEqual(key, 'droplet:' + original)
        self.assertEqual(self.creates, [])

    def test_resource_visible_with_a_not_created_receipt_is_adopted_not_duplicated(self):
        grant = self.timed_out_request()
        self.stack.provider.issue_receipt(grant['create_request_ref'])
        original = self.land(grant)
        self.assertEqual(self.guarded(settlement_fn=self.settlement), 'droplet:' + original)
        self.assertEqual(self.creates, [])

    def test_shipped_registry_trusts_no_receipt_and_the_provider_default_offers_none(self):
        grant = self.timed_out_request()
        production = registry.Registry(self.stack.state_dir, clock=self.stack.clock)
        self.addCleanup(production.close)
        self.assertEqual(production.trusted_settlement_bases, ())
        receipt = self.stack.provider.offline_receipt(grant['create_request_ref'], create_evidence.NOT_CREATED)
        with self.assertRaises(registry.Rejection) as caught:
            production.record_create_settlement(SESSION, self.intent, receipt, self.token)
        self.assertEqual(caught.exception.code, 'untrusted_settlement_basis')
        self.assertEqual(self.intent_view()['state'], 'ambiguous')
        self.assertIsNone(cleanup_provider.CleanupProvider().get_request_settlement(grant['create_request_ref']))

    def test_receipts_are_typed_and_every_malformed_or_wrong_one_is_refused(self):
        grant = self.timed_out_request()
        ref = grant['create_request_ref']
        good = self.stack.provider.offline_receipt(ref, create_evidence.NOT_CREATED)
        cases = {
            'stale_settlement': dict(good, request_ref=self.intent + '#2'),
            'untrusted_settlement_basis': dict(good, basis='elapsed_time'),
            'malformed_settlement': dict(good, terminal='pending'),
            'secret_value_rejected': dict(good, provider_reference='dop_v1_' + 'a' * 64),
        }
        for code, receipt in cases.items():
            with self.subTest(code=code), self.assertRaises(registry.Rejection) as caught:
                self.stack.registry.record_create_settlement(SESSION, self.intent, receipt, self.token)
            self.assertIn(caught.exception.code, (code, 'secret_value_rejected'))
        for broken in ({}, 'empty', dict(good, kind='other'), dict(good, resource_id='5'), dict(good, terminal='created'),
                       {k: v for k, v in good.items() if k != 'basis'}, dict(good, provider_reference=' ')):
            with self.subTest(broken=broken), self.assertRaises(registry.Rejection) as caught:
                self.stack.registry.record_create_settlement(SESSION, self.intent, broken, self.token)
            self.assertEqual(caught.exception.code, 'malformed_settlement')
        self.assertEqual(self.intent_view()['state'], 'ambiguous')

    def test_stale_controller_cannot_present_a_receipt(self):
        grant = self.timed_out_request()
        self.stack.new_client('controller-b').acquire(SESSION, takeover=True)
        receipt = self.stack.provider.offline_receipt(grant['create_request_ref'], create_evidence.NOT_CREATED)
        with self.assertRaises(registry.Rejection) as caught:
            self.stack.registry.record_create_settlement(SESSION, self.intent, receipt, self.token)
        self.assertEqual(caught.exception.code, 'stale_fencing_token')

    def test_registry_enforces_eligibility_without_trusting_the_client(self):
        self.timed_out_request()
        registry_ = self.stack.registry
        self.wait(LONG_AFTER_THE_REQUEST_S)
        with self.assertRaises(registry.Rejection) as caught:
            registry_.begin_create(SESSION, self.intent, self.token)
        self.assertEqual(caught.exception.code, 'create_outcome_unknown', 'time alone proves nothing')
        self.assertNotIn('begin_reconcile', registry.Registry.RPC_METHODS)
        with self.assertRaises(registry.Rejection) as caught:
            registry_.record_create_result(SESSION, self.intent, 'reconciled_absent', self.token, note='empty listing')
        self.assertEqual(caught.exception.code, 'bad_request', 'an empty listing is not a kind of result')

    def test_forward_wall_step_changes_nothing_about_an_unresolved_request(self):
        self.timed_out_request()
        self.stack.step(1)
        self.stack.clock.jump_wall(LONG_AFTER_THE_REQUEST_S)
        self.stack.step(1)
        self.assertEqual(self.intent_view()['state'], 'ambiguous')
        self.assertEqual(self.intent_view()['request_count'], 1)

    def test_takeover_cannot_skip_the_evidence(self):
        self.timed_out_request()
        other = self.stack.new_client('controller-b')
        token = other.acquire(SESSION, takeover=True)['fencing_token']
        with self.assertRaises(registry_client.CreateUnresolved):
            other.guarded_create(SESSION, self.intent, token, self.create, self.find)
        self.assertEqual(self.creates, [])

    def test_a_receipt_for_an_earlier_request_cannot_answer_a_newer_one(self):
        registry_ = self.stack.registry
        first = self.timed_out_request()['create_request_ref']
        receipt = self.stack.provider.offline_receipt(first, create_evidence.NOT_CREATED)
        registry_.record_create_settlement(SESSION, self.intent, receipt, self.token)
        registry_.begin_create(SESSION, self.intent, self.token)
        with self.assertRaises(registry.Rejection) as caught:
            registry_.record_create_settlement(SESSION, self.intent, receipt, self.token)
        self.assertEqual(caught.exception.code, 'stale_settlement')
        self.assertEqual(self.intent_view()['state'], 'requested')

    def test_a_late_rejection_of_an_earlier_request_cannot_clear_a_newer_one(self):
        registry_ = self.stack.registry
        registry_.begin_create(SESSION, self.intent, self.token)
        registry_.record_create_result(SESSION, self.intent, 'rejected', request_number=1)
        self.assertEqual(self.intent_view()['state'], 'rejected')
        registry_.begin_create(SESSION, self.intent, self.token)
        with self.assertRaises(registry.Rejection) as caught:
            registry_.record_create_result(SESSION, self.intent, 'rejected', request_number=1)
        self.assertEqual(caught.exception.code, 'stale_create_report')
        self.assertEqual(self.intent_view()['state'], 'requested')

    def test_a_not_sent_report_needs_the_current_request_and_controller(self):
        registry_ = self.stack.registry
        registry_.begin_create(SESSION, self.intent, self.token)
        with self.assertRaises(registry.Rejection) as caught:
            registry_.record_create_result(SESSION, self.intent, 'not_sent', self.token, request_number=2)
        self.assertEqual(caught.exception.code, 'stale_create_report')
        with self.assertRaises(registry.Rejection) as caught:
            registry_.record_create_result(SESSION, self.intent, 'not_sent', self.token + 1, request_number=1)
        self.assertEqual(caught.exception.code, 'stale_fencing_token')
        self.assertEqual(self.intent_view()['state'], 'requested')

    def test_grant_left_unused_past_its_start_window_is_not_sent_and_can_be_retried(self):
        client = self.stack.new_client('controller-a')
        moments = iter([0.0, session_clock.CREATE_START_WINDOW_S + 0.1])
        client.monotonic = lambda: next(moments)
        with self.assertRaises(registry_client.CreateGrantExpired):
            client.guarded_create(SESSION, self.intent, self.token, self.create, self.find)
        self.assertEqual(self.creates, [])
        self.assertEqual((self.intent_view()['request_count'], self.intent_view()['state']), (1, 'declared'),
                         'its holder knows it was never sent')
        self.guarded()
        self.assertEqual(self.creates, [self.intent])

    def test_certain_outcomes_from_the_adapter_are_typed_and_anything_else_is_unknown(self):
        cases = ((create_evidence.CreateRejected('422'), 'rejected'), (create_evidence.CreateNotSent('dns failed before connect'), 'declared'),
                 (TimeoutError('read timed out'), 'ambiguous'), (ConnectionResetError('reset'), 'ambiguous'))
        for error, state in cases:
            with self.subTest(error=type(error).__name__):
                stack = rf.Stack(self)
                _, _, token, _ = stack.armed(SESSION)

                def fails(grant, failure=error):
                    raise failure

                with self.assertRaises(type(error)):
                    stack.client.guarded_create(SESSION, self.intent, token, fails, lambda g: None)
                view = next(i for i in stack.registry.status(SESSION)['intents'] if i['intent_id'] == self.intent)
                self.assertEqual(view['state'], state)

    def test_grant_states_what_the_provider_adapter_must_honor_and_promises_no_settling(self):
        grant = self.stack.registry.begin_create(SESSION, self.intent, self.token)
        self.assertEqual(grant['create_start_window_s'], session_clock.CREATE_START_WINDOW_S)
        self.assertEqual(grant['create_request_timeout_s'], session_clock.PROVIDER_REQUEST_BOUND_S)
        self.assertEqual(grant['create_request_ref'], self.intent + '#1')
        self.assertNotIn('create_settle_s', grant)

    def test_a_created_intent_cannot_be_created_again(self):
        self.guarded()
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.guarded()
        self.assertEqual(caught.exception.code, 'already_created')
        self.assertEqual(len(self.creates), 1)

    def test_a_pair_cannot_become_ready_over_an_unresolved_create(self):
        for role in ('game', 'bot'):
            self.stack.client.guarded_create(SESSION, SESSION + ':droplet:' + role, self.token,
                                             lambda g: self.stack.provider.add_droplet(g['expected_name'], g['expected_tags']), lambda g: None)
        self.stack.registry.begin_create(SESSION, SESSION + ':tag:bot', self.token)
        with self.assertRaises(registry.Rejection) as caught:
            self.stack.registry.mark_ready(SESSION, self.token, 'readiness/fake.json')
        self.assertEqual(caught.exception.code, 'create_outcome_unknown')


class FencingTests(unittest.TestCase):
    """Criterion 2: one live controller; stale tokens and expired work are refused at dispatch."""

    def setUp(self):
        self.stack = rf.Stack(self)
        self.manifest, self.sha, self.token, self.ack, self.ids = self.stack.ready(SESSION)
        self.other = self.stack.new_client('controller-b')

    def dispatch(self, client=None, token=None, run_id='run-1', duration=60, request_id=None):
        return (client or self.stack.client).mutate(
            'dispatch_run', request_id, session_id=SESSION, run_id=run_id, fencing_token=self.token if token is None else token,
            manifest_sha256=self.sha, estimated_duration_s=duration)

    def assert_rejected(self, code, func, *args, **kwargs):
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_second_controller_cannot_take_a_live_session_without_explicit_takeover(self):
        error = self.assert_rejected('control_held', self.other.acquire, SESSION)
        self.assertEqual(error.details['controller_id'], 'controller-a')
        self.assertEqual(self.dispatch()['authorized'], True)

    def test_takeover_makes_every_authority_of_the_old_controller_stale(self):
        new = self.other.acquire(SESSION, takeover=True)
        self.assertGreater(new['fencing_token'], self.token)
        calls = [
            lambda: self.dispatch(),
            lambda: self.stack.client.call('renew_control', session_id=SESSION, fencing_token=self.token),
            lambda: self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=self.token, reason='stale'),
            lambda: self.stack.client.mutate('begin_collection', session_id=SESSION, fencing_token=self.token),
            lambda: self.stack.client.mutate('record_evidence', session_id=SESSION, fencing_token=self.token, status='complete'),
            lambda: self.stack.client.mutate('record_measurement', session_id=SESSION, fencing_token=self.token, outcome='x'),
        ]
        for call in calls:
            self.assert_rejected('stale_fencing_token', call)
        self.assertEqual(self.stack.registry.runs(SESSION), [])
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.PAUSED)

    def test_stale_replay_of_an_applied_dispatch_cannot_launch(self):
        self.dispatch(request_id='dispatch-1')
        self.other.acquire(SESSION, takeover=True)
        self.assert_rejected('stale_fencing_token', self.dispatch, request_id='dispatch-1')

    def test_lost_dispatch_ack_replays_one_grant_without_a_second_run(self):
        client = self.stack.new_client('controller-a', transport=DropResponse(self.stack.transport, 'dispatch_run'))
        grant = self.dispatch(client=client, request_id='dispatch-1')
        self.assertTrue(grant['authorized'])
        self.assertEqual(len(self.stack.registry.runs(SESSION)), 1)

    def test_replay_of_a_finished_or_unlaunchable_dispatch_grants_nothing(self):
        grant = self.dispatch(request_id='dispatch-1')
        self.stack.step(self.stack.registry.launch_window_s + 1)
        self.stack.client.call('renew_control', session_id=SESSION, fencing_token=self.token)
        self.assertFalse(self.dispatch(request_id='dispatch-1')['authorized'], 'launch window closed')
        self.stack.client.mutate('record_run_outcome', session_id=SESSION, run_id='run-1', outcome=search.PASS,
                                 fencing_token=self.token, evidence_ref='runs/run-1')
        self.assertFalse(self.dispatch(request_id='dispatch-1')['authorized'], 'finished run')
        self.assertTrue(grant['authorized'])

    def test_lease_lapse_refuses_dispatch_and_renewal_and_resume_is_explicit(self):
        self.stack.clock.advance(self.stack.registry.lease_ttl_s + 1)
        self.stack.watchdog.tick()
        self.assert_rejected('lease_expired', self.dispatch)
        self.assert_rejected('lease_expired', self.stack.client.call, 'renew_control', session_id=SESSION, fencing_token=self.token)
        new = self.stack.client.acquire(SESSION)
        self.assertEqual(new['state'], registry.PAUSED)
        self.assertFalse(new['dispatch_allowed'])
        self.assert_rejected('bad_state', self.dispatch, token=new['fencing_token'])
        self.stack.client.mutate('record_resume', session_id=SESSION, fencing_token=new['fencing_token'],
                                 operator_request_ref='operator: resume 2026-10-30', checks=dict(readiness='passed'))
        self.assertTrue(self.dispatch(token=new['fencing_token'])['authorized'])
        journal = [e['kind'] for e in self.stack.registry.journal(SESSION)]
        self.assertIn('resumed', journal)

    def test_interrupted_run_is_retained_and_blocks_resume_until_classified(self):
        self.dispatch()
        new = self.other.acquire(SESSION, takeover=True)
        token = new['fencing_token']
        run = self.stack.registry.runs(SESSION)[0]
        self.assertEqual(run['state'], 'interrupted')
        self.assertEqual(run['interrupted_reason'], 'controller_replaced')
        self.assert_rejected('interrupted_run_unclassified', self.other.mutate, 'record_resume', session_id=SESSION,
                             fencing_token=token, operator_request_ref='op', checks=dict(readiness='passed'))
        self.other.mutate('record_run_outcome', session_id=SESSION, run_id='run-1', outcome=search.INCOMPLETE, fencing_token=token)
        self.other.mutate('record_resume', session_id=SESSION, fencing_token=token, operator_request_ref='op',
                          checks=dict(readiness='passed'))
        self.assert_rejected('duplicate_run', self.dispatch, client=self.other, token=token)
        self.assertTrue(self.dispatch(client=self.other, token=token, run_id='run-2')['authorized'])

    def test_terminal_failure_cannot_be_resumed_or_dispatched_past(self):
        for outcome in search.STOPPING:
            with self.subTest(outcome=outcome):
                stack = rf.Stack(self)
                _, sha, token, _, _ = stack.ready(SESSION)
                stack.client.mutate('dispatch_run', session_id=SESSION, run_id='r', fencing_token=token, manifest_sha256=sha, estimated_duration_s=10)
                stack.client.mutate('record_run_outcome', session_id=SESSION, run_id='r', outcome=outcome, fencing_token=token)
                with self.assertRaises(registry_client.RegistryRejected) as caught:
                    stack.client.mutate('dispatch_run', session_id=SESSION, run_id='r2', fencing_token=token, manifest_sha256=sha, estimated_duration_s=10)
                self.assertEqual(caught.exception.code, 'terminal_failure')
                other = stack.new_client('controller-b')
                new = other.acquire(SESSION, takeover=True)['fencing_token']
                with self.assertRaises(registry_client.RegistryRejected) as caught:
                    other.mutate('record_resume', session_id=SESSION, fencing_token=new, operator_request_ref='op', checks=dict(x=1))
                self.assertEqual(caught.exception.code, 'terminal_failure')

    def test_dispatch_refuses_overlap_duplicates_and_wrong_manifest(self):
        self.dispatch()
        self.assert_rejected('bad_state', self.dispatch, run_id='run-2')
        self.stack.client.mutate('record_run_outcome', session_id=SESSION, run_id='run-1', outcome=search.PASS,
                                 fencing_token=self.token, evidence_ref='e')
        self.assert_rejected('duplicate_run', self.dispatch)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.mutate('dispatch_run', session_id=SESSION, run_id='run-3', fencing_token=self.token,
                                     manifest_sha256='0' * 64, estimated_duration_s=10)
        self.assertEqual(caught.exception.code, 'manifest_conflict')

    def test_dispatch_refused_when_run_cannot_finish_before_c(self):
        cutoff = session_clock.parse(self.ack['cleanup_c_utc']) - registry.DELETE_MARGIN_S
        remaining = cutoff - self.stack.registry.peek_now() - self.stack.registry.launch_window_s
        self.assert_rejected('does_not_fit', self.dispatch, duration=remaining + 1)
        grant = self.dispatch(duration=remaining)
        self.assertTrue(grant['authorized'], 'an exact fit is admitted')
        self.assertEqual(session_clock.parse(grant['launch_by']) + remaining, cutoff,
                         'a run launched at the very end of its grant still ends before deletion starts')

    def test_dispatch_is_not_cut_off_by_read_only_preparation(self):
        c = session_clock.parse(self.ack['cleanup_c_utc'])
        self.stack.step(c - self.stack.clock.wall_value - registry.PREPARE_LEAD_S + 1)
        token = self.stack.client.acquire(SESSION, takeover=True)['fencing_token']
        self.stack.client.mutate('record_resume', session_id=SESSION, fencing_token=token,
                                 operator_request_ref='fixture', checks=dict(readiness='ok'))
        self.assertTrue(self.stack.provider.ops_named('get_droplet'), 'preparation has begun')
        grant = self.stack.client.mutate('dispatch_run', session_id=SESSION, run_id='late-run', fencing_token=token,
                                         manifest_sha256=self.sha, estimated_duration_s=5)
        self.assertTrue(grant['authorized'])
        self.assertLess(session_clock.parse(grant['launch_by']) + 5, c)
        self.assertEqual(self.stack.provider.ops_named('delete_droplet'), [])

    def test_dispatch_fit_uses_the_real_grant_when_the_lease_ends_first(self):
        cleanup_start = session_clock.parse(self.ack['cleanup_c_utc']) - registry.DELETE_MARGIN_S
        self.stack.step(self.stack.registry.lease_ttl_s - 10)
        grant = self.dispatch(duration=1)
        self.assertEqual(session_clock.parse(grant['launch_by']), session_clock.parse(self.stack.registry.status(SESSION)['lease_expires_at']))
        self.assertLess(session_clock.parse(grant['launch_by']), cleanup_start)

    def test_dispatch_refused_while_the_watchdog_heartbeat_is_stale(self):
        self.stack.clock.advance(self.stack.registry.watchdog_stale_s + 1)
        self.assert_rejected('watchdog_unhealthy', self.dispatch)
        self.assertEqual(self.stack.registry.runs(SESSION), [])

    def test_dispatch_refused_after_cleanup_or_at_c_even_with_a_current_token(self):
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=self.token, reason='batch finished')
        self.assert_rejected('cleanup_in_progress', self.dispatch)
        stack = rf.Stack(self)
        _, sha, token, ack, _ = stack.ready(SESSION)
        c = session_clock.parse(ack['cleanup_c_utc'])
        stack.clock.wall_value = c
        stack.clock.mono_value += c - fx.T0_WALL
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            stack.client.mutate('dispatch_run', session_id=SESSION, run_id='late', fencing_token=token, manifest_sha256=sha, estimated_duration_s=1)
        self.assertIn(caught.exception.code, ('lease_expired', 'deadline_reached', 'cleanup_in_progress'))
        self.assertEqual(stack.registry.runs(SESSION), [])

    def test_dispatch_at_c_is_refused_with_a_live_lease_before_the_watchdog_acts(self):
        stack = rf.Stack(self)
        stack.registry.lease_ttl_s = 100000.0
        stack.registry.watchdog_stale_s = 100000.0
        _, sha, token, ack, _ = stack.ready(SESSION, cap_s=400, reserve_s=120, grace_s=100)
        c = session_clock.parse(ack['cleanup_c_utc'])
        stack.clock.advance(c - stack.clock.wall_value)
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            stack.client.mutate('dispatch_run', session_id=SESSION, run_id='late', fencing_token=token, manifest_sha256=sha, estimated_duration_s=1)
        self.assertEqual(caught.exception.code, 'deadline_reached')

    def test_outcome_after_cleanup_is_retained_for_the_current_controller(self):
        self.dispatch()
        self.stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=self.token, reason='abort')
        run = self.stack.registry.runs(SESSION)[0]
        self.assertEqual(run['interrupted_reason'], 'cleanup_started')
        self.stack.client.mutate('record_run_outcome', session_id=SESSION, run_id='run-1', outcome=search.INCOMPLETE, fencing_token=self.token)
        self.assertEqual(self.stack.registry.runs(SESSION)[0]['outcome'], search.INCOMPLETE)
        self.assert_rejected('outcome_recorded', self.stack.client.mutate, 'record_run_outcome', session_id=SESSION, run_id='run-1',
                             outcome=search.PASS, fencing_token=self.token, evidence_ref='forged')

    def test_rejections_are_journaled_with_no_token_echo_in_storage(self):
        self.other.acquire(SESSION, takeover=True)
        self.assert_rejected('stale_fencing_token', self.dispatch)
        kinds = [(e['kind'], e['data'].get('code')) for e in self.stack.registry.journal(SESSION)]
        self.assertIn(('rejected', 'stale_fencing_token'), kinds)

    def test_request_id_reuse_for_another_request_conflicts(self):
        self.dispatch(request_id='shared')
        self.stack.client.mutate('record_run_outcome', session_id=SESSION, run_id='run-1', outcome=search.INCOMPLETE, fencing_token=self.token)
        self.assert_rejected('request_id_conflict', self.dispatch, run_id='run-2', request_id='shared')

    def test_concurrent_controllers_through_separate_connections_get_one_winner(self):
        stack = rf.Stack(self)
        manifest, sha = fx.session_manifest(SESSION)
        stack.client.register(manifest, sha)
        second = stack.open_registry()
        results = []
        for name, reg in (('a', stack.registry), ('b', second)):
            response = reg.rpc(dict(method='acquire_control', params=dict(session_id=SESSION, controller_id=name, request_id='req-' + name)))
            results.append(response)
        self.assertTrue(results[0]['ok'])
        self.assertEqual(results[1]['code'], 'control_held')


class EvidenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = rf.Stack(self)

    def recovering(self, **limits):
        _, _, token, ack, _ = self.stack.ready(SESSION, **limits)
        self.stack.client.mutate('begin_collection', session_id=SESSION, fencing_token=token)
        return token, ack

    def test_episode_is_bounded_by_grace_and_never_resets(self):
        token, _ = self.recovering()
        first = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        self.assertEqual(session_clock.parse(first['recovery_deadline_utc']) - self.stack.registry.peek_now(), 300)
        self.stack.step(60)
        self.stack.client.call('renew_control', session_id=SESSION, fencing_token=token)
        self.stack.step(40)
        again = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        self.assertEqual(again['recovery_deadline_utc'], first['recovery_deadline_utc'])
        self.stack.client.mutate('begin_collection', session_id=SESSION, fencing_token=token)
        third = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        self.assertEqual(third['recovery_deadline_utc'], first['recovery_deadline_utc'], 'reconnecting does not reopen the window')

    def fail_at(self, ack, before_c):
        """A controller holding a live lease has its first failed download this long before C."""
        c = session_clock.parse(ack['cleanup_c_utc'])
        self.stack.step(c - self.stack.clock.wall_value - before_c)
        token = self.stack.client.acquire(SESSION, takeover=True)['fencing_token']
        return c, token, self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)

    def test_episode_is_exactly_the_accepted_formula_near_c(self):
        for before_c, grace, expected_from_failure in ((60, 100, 60), (100, 100, 100), (40, 100, 40), (150, 100, 100), (1, 100, 1)):
            with self.subTest(before_c=before_c, grace=grace):
                self.stack = rf.Stack(self)
                _, ack = self.recovering(cap_s=600, reserve_s=120, grace_s=grace)
                c, _, first = self.fail_at(ack, before_c)
                self.assertEqual(session_clock.parse(first['first_failure_at']), c - before_c)
                self.assertEqual(session_clock.parse(first['recovery_deadline_utc']), c - before_c + expected_from_failure,
                                 'min(first_failure + grace, C)')

    def test_active_recovery_lasts_until_c_while_ownership_is_prepared_and_nothing_is_deleted(self):
        _, ack = self.recovering(cap_s=600, reserve_s=120, grace_s=100)
        c, token, first = self.fail_at(ack, 60)
        self.assertEqual(session_clock.parse(first['recovery_deadline_utc']), c)
        self.stack.step(59)
        self.assertEqual(self.stack.clock.wall_value, c - 1)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.EVIDENCE_RECOVERY, 'preparing cleanup does not end recovery')
        self.assertIsNone(status['cleanup']['requested_at'])
        self.assertEqual(self.stack.provider.ops_named('delete_droplet', 'delete_firewall', 'delete_tag'), [])
        self.assertTrue(self.stack.provider.ops_named('get_droplet'), 'ownership is already known')
        self.assertEqual(len(self.stack.provider.live_ids()['droplets']), 2, 'the evidence hosts are intact')
        self.stack.client.call('renew_control', session_id=SESSION, fencing_token=token)
        again = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        self.assertEqual(again['recovery_deadline_utc'], first['recovery_deadline_utc'], 'still open, never reset')
        self.stack.step(0.75, tick_interval=0.25)
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.EVIDENCE_RECOVERY)
        self.assertEqual(self.stack.provider.ops_named('delete_droplet', 'delete_firewall', 'delete_tag'), [])
        self.stack.step(0.25, tick_interval=0.25)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['reason'], 'deadline_C')
        first_delete = self.stack.provider.ops_named('delete_droplet')[0]
        self.assertLessEqual(first_delete['at'], c, 'and deletion still begins by C')
        self.assertGreaterEqual(first_delete['at'], c, 'but not before recovery was over')

    def test_recovery_ending_before_c_deletes_at_once_using_the_prepared_ownership(self):
        _, ack = self.recovering(cap_s=600, reserve_s=120, grace_s=10)
        c, _, first = self.fail_at(ack, 30)
        deadline = session_clock.parse(first['recovery_deadline_utc'])
        self.assertEqual(deadline, c - 20)
        self.stack.step(10)
        self.assertEqual(self.stack.registry.status(SESSION)['cleanup']['reason'], 'evidence_recovery_expired')
        self.assertEqual(self.stack.provider.ops_named('delete_droplet')[0]['at'], deadline)

    def test_watchdog_ends_an_expired_episode_without_the_controller(self):
        token, _ = self.recovering()
        first = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        deadline = session_clock.parse(first['recovery_deadline_utc'])
        # The controller is gone from here on; only the watchdog acts.
        self.stack.run_until(lambda: self.stack.registry.status(SESSION)['state'] != registry.EVIDENCE_RECOVERY)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['cleanup']['reason'], 'evidence_recovery_expired')
        self.assertLessEqual(session_clock.parse(status['cleanup']['requested_at']) - deadline, 1.0)


    def test_reconnecting_cannot_outlive_the_episode(self):
        token, ack = self.recovering()
        first = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        deadline = session_clock.parse(first['recovery_deadline_utc'])
        self.stack.step(50)
        self.stack.client.mutate('begin_collection', session_id=SESSION, fencing_token=token)
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.COLLECTING)
        # The controller reconnected, then vanished. No later call may be needed to end the episode.
        self.stack.step(deadline - self.stack.clock.wall_value - 1)
        self.assertEqual(self.stack.registry.status(SESSION)['state'], registry.COLLECTING, 'not early')
        self.stack.step(1)
        status = self.stack.registry.status(SESSION)
        self.assertEqual(status['state'], registry.DELETING)
        self.assertEqual(status['cleanup']['reason'], 'evidence_recovery_expired')
        self.assertLessEqual(session_clock.parse(status['cleanup']['requested_at']), deadline)
        self.assertLess(deadline, session_clock.parse(ack['cleanup_c_utc']), 'this was the recovery bound, not C')

    def test_expired_episode_refuses_collection_before_the_watchdog_notices(self):
        token, _ = self.recovering()
        first = self.stack.client.mutate('begin_evidence_recovery', session_id=SESSION, fencing_token=token)
        self.stack.clock.advance(session_clock.parse(first['recovery_deadline_utc']) - self.stack.clock.wall_value)
        # No watchdog tick has run, so only the registry's own gate stands here.
        self.stack.registry.db.execute("UPDATE sessions SET lease_expires_at='2099-01-01T00:00:00+00:00'")
        with self.assertRaises(registry_client.RegistryRejected) as caught:
            self.stack.client.mutate('begin_collection', session_id=SESSION, fencing_token=token)
        self.assertEqual(caught.exception.code, 'recovery_expired')


class IndependentOutcomeTests(unittest.TestCase):
    """Criterion 4: measurement, evidence and cleanup never overwrite one another."""

    def test_every_combination_is_representable_and_overall_never_overclaims(self):
        cases = [
            ('PASS', 'complete', 'clean'),
            ('FAIL', 'complete', 'clean'),
            ('PASS', 'partial', 'resources_verified_evidence_incomplete'),
            ('PASS', 'missing', 'resources_verified_evidence_incomplete'),
            ('PASS', 'unknown', 'resources_verified_evidence_incomplete'),
        ]
        for measurement, evidence, overall in cases:
            with self.subTest(measurement=measurement, evidence=evidence):
                stack = rf.Stack(self)
                _, _, token, _, _ = stack.ready(SESSION)
                stack.client.mutate('record_measurement', session_id=SESSION, fencing_token=token, outcome=measurement, ref='m.json')
                if evidence != 'unknown':
                    stack.client.mutate('record_evidence', session_id=SESSION, fencing_token=token, status=evidence, ref='e.json')
                before = stack.registry.status(SESSION)
                self.assertEqual(before['cleanup']['outcome'], 'not_started')
                self.assertEqual(before['overall'], 'cleanup_not_verified', 'a passing run is not a clean session')
                stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
                stack.run_until(lambda: stack.closed(SESSION))
                status = stack.registry.status(SESSION)
                self.assertEqual(status['measurement']['outcome'], measurement)
                self.assertEqual(status['evidence']['status'], evidence)
                self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
                self.assertEqual(status['overall'], overall)

    def test_evidence_can_be_recorded_after_closure_without_touching_cleanup(self):
        stack = rf.Stack(self)
        _, _, token, _, _ = stack.ready(SESSION)
        stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        stack.run_until(lambda: stack.closed(SESSION))
        verified = stack.registry.status(SESSION)['cleanup']['verified_at']
        fresh = stack.client.acquire(SESSION, takeover=True)['fencing_token']
        stack.client.mutate('record_evidence', session_id=SESSION, fencing_token=fresh, status='complete', ref='inventory.sha256')
        status = stack.registry.status(SESSION)
        self.assertEqual(status['overall'], 'clean')
        self.assertEqual(status['cleanup']['verified_at'], verified)

    def test_cleanup_failure_cannot_change_measurement_or_evidence(self):
        stack = rf.Stack(self)
        _, _, token, _, _ = stack.ready(SESSION)
        stack.client.mutate('record_measurement', session_id=SESSION, fencing_token=token, outcome='PASS')
        stack.client.mutate('record_evidence', session_id=SESSION, fencing_token=token, status='complete')
        stack.provider.fail(rf.outage)
        stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='done')
        stack.step(120)
        status = stack.registry.status(SESSION)
        self.assertEqual(status['measurement']['outcome'], 'PASS')
        self.assertEqual(status['evidence']['status'], 'complete')
        self.assertEqual(status['cleanup']['outcome'], 'in_progress')
        self.assertEqual(status['overall'], 'cleanup_not_verified')

    def test_operator_abort_needs_no_controller_and_closes_an_unarmed_session(self):
        stack = rf.Stack(self)
        stack.registered(SESSION)
        result = stack.registry.operator_abort(SESSION, 'operator stopped before arming')
        self.assertEqual(result['state'], registry.CLOSED)
        self.assertEqual(stack.registry.status(SESSION)['overall'], 'closed_never_armed')

    def test_a_resource_report_for_a_never_armed_session_is_refused(self):
        stack = rf.Stack(self)
        stack.registered(SESSION)
        with self.assertRaises(registry.Rejection) as caught:
            stack.registry.record_resource(SESSION, 'droplet', '1')
        self.assertEqual(caught.exception.code, 'not_armed')


if __name__ == '__main__':
    unittest.main()
