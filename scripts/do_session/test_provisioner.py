"""Admitted intent to a verified pair, or ownership-safe cleanup, through the real adapter against a fake account."""
import json
import unittest

import cleanup_provider
import create_evidence
import do_api
import manifest as manifest_mod
import provision_fixtures as pf
import provisioner
import registry
import registry_client
import remote_authorization
import session_access
import session_clock

OTHER_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA other'
FAST_OBSERVE = provisioner.Policy(reconcile_observe_s=30.0, host_contact_wait_s=30.0, firewall_apply_wait_s=30.0, firewall_update_attempts=2, assign_attempts=2)


class ReadyPair(unittest.TestCase):
    def test_admitted_intent_reaches_a_verified_ready_pair(self):
        sim = pf.Sim(self)
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY, result)
        status = sim.status()
        self.assertEqual(status['state'], registry.READY)
        self.assertEqual(len(sim.creates('/v2/droplets')), 2)
        self.assertEqual(len(sim.creates('/v2/firewalls')), 1)
        self.assertEqual(len(sim.creates('/v2/tags')), 3)
        self.assertTrue(result.evidence_ref.startswith('provisioning/readiness.json#sha256:'))
        self.assertEqual(sim.ready_acks[0][1], result.evidence_ref)

    def test_every_create_precedes_nothing_it_needs_and_follows_the_durable_arm(self):
        sim = pf.Sim(self)
        sim.run()
        paths = [m['path'] for m in sim.account.mutations()]
        self.assertEqual(paths[:6], ['/v2/tags', '/v2/tags', '/v2/tags', '/v2/firewalls', '/v2/droplets', '/v2/droplets'])
        t0 = session_clock.parse(sim.armed_acks[0]['t0_utc'])
        self.assertGreaterEqual(sim.account.mutations()[0]['at'], t0)
        journal = [e['kind'] for e in sim.stack.registry.journal(sim.session_id)]
        self.assertLess(journal.index('watchdog_armed_acknowledged'), journal.index('create_intent_requested'))

    def test_creates_obey_the_grant_bound_and_send_window(self):
        sim = pf.Sim(self)
        sim.run()
        for path in ('/v2/tags', '/v2/firewalls', '/v2/droplets'):
            for request in sim.creates(path):
                self.assertEqual(request['bound'], session_clock.PROVIDER_REQUEST_BOUND_S)
                self.assertTrue(request['send_by'])

    def test_firewall_ends_exact_with_the_bot_address_and_no_metrics_rule(self):
        sim = pf.Sim(self)
        result = sim.run()
        firewall = sim.provider.get_firewall(result.firewall_id)
        bot = sim.provider.get_droplet(result.droplets['bot'])
        self.assertEqual(firewall['status'], 'succeeded')
        rules = {r['ports']: r['sources']['addresses'] for r in firewall['inbound_rules']}
        self.assertEqual(rules, {'22': ['203.0.113.10/32'], '8081': sorted(['203.0.113.10/32', bot['public_ipv4'][0] + '/32'])})
        self.assertEqual(sorted(firewall['tags']), sorted((sim.manifest['session']['ownership_tags']['game'], sim.manifest['session']['ownership_tags']['bot'])))

    def test_droplet_requests_are_frozen_and_hold_only_public_key_material(self):
        sim = pf.Sim(self)
        sim.run()
        self.assertEqual(len(sim.account.droplet_requests), 2)
        for request in sim.account.droplet_requests:
            self.assertEqual(request['ssh_keys'], [sim.manifest['ssh_key']['id']])
            self.assertFalse(request['backups'] or request['ipv6'] or request['monitoring'] or request['with_droplet_agent'])
            self.assertEqual(manifest_mod.scan_for_secrets(request), [])
            self.assertNotIn('PRIVATE KEY', request['user_data'])
            self.assertNotIn('203.0.113.10', request['user_data'])
            self.assertIn(sim.public_key, request['user_data'])

    def test_retained_readiness_records_each_role_and_contains_no_nonce(self):
        sim = pf.Sim(self)
        sim.run()
        path = sim.evidence.root / 'readiness.json'
        report = json.loads(path.read_text())
        for role in ('game', 'bot'):
            entry = report['roles'][role]
            self.assertEqual(entry['observation']['kernel'], '6.8.0-fixture')
            self.assertIn('host_key_sha256', entry['host_key'])
            self.assertIn('offset_s', entry['clock_offset'])
            self.assertIn('agent_sha256', entry)
        self.assertEqual(report['build']['source']['head'], sim.manifest['source']['benchmark_sha'])
        text = path.read_text() + (sim.evidence.root / 'journal.ndjson').read_text()
        self.assertNotIn('fixture-nonce', text)
        self.assertEqual(manifest_mod.scan_for_secrets(text), [])

    def test_commands_never_run_before_first_contact_pins_the_host(self):
        sim = pf.Sim(self)
        sim.run()
        for role in ('game', 'bot'):
            self.assertEqual(sim.guests.steps(role)[0], 'pin')

    def test_game_host_receives_a_release_but_no_compiler_or_build(self):
        sim = pf.Sim(self)
        sim.run()
        self.assertNotIn('build', sim.guests.steps('game'))
        self.assertNotIn('fetch_source', sim.guests.steps('game'))
        self.assertIn('install_release', sim.guests.steps('game'))
        self.assertIn('build', sim.guests.steps('bot'))

    def test_lease_stays_alive_through_a_long_build(self):
        sim = pf.Sim(self)
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY)
        lease = session_clock.parse(sim.status()['lease_expires_at'])
        self.assertGreater(lease, sim.clock.wall())

    def test_ready_pair_then_closes_clean_only_with_evidence_and_verified_absence(self):
        sim = pf.Sim(self)
        result = sim.run()
        sim.client.mutate('record_evidence', session_id=sim.session_id, fencing_token=result.fencing_token, status='complete', ref='x')
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='batch finished')
        status = sim.drive_cleanup()
        self.assertEqual(status['overall'], 'clean')
        self.assertEqual(sim.session_droplets(), [])
        self.assertTrue(sim.unrelated_intact())
        self.assertTrue(sim.session_mutation_targets_only())


class RefusedBeforeAnyCreate(unittest.TestCase):
    def assert_nothing_created(self, sim, result, code):
        self.assertEqual(result.status, provisioner.REJECTED, result)
        self.assertEqual(result.code, code, result)
        self.assertEqual(sim.account.mutations(), [])

    def test_wrong_or_unavailable_facts_create_nothing(self):
        def wrong_project(sim):
            sim.account.project['name'] = 'someone-else'

        def inactive_account(sim):
            sim.account.account['status'] = 'locked'

        def no_quota(sim):
            sim.account.account['droplet_limit'] = 3

        def size_gone(sim):
            sim.account.sizes = [s for s in sim.account.sizes if s['slug'] != 's-1vcpu-1gb-amd']

        def size_unavailable(sim):
            next(s for s in sim.account.sizes if s['slug'] == 's-1vcpu-1gb-amd')['available'] = False

        def size_changed(sim):
            next(s for s in sim.account.sizes if s['slug'] == 's-1vcpu-1gb-amd')['memory'] = 512

        def price_changed(sim):
            next(s for s in sim.account.sizes if s['slug'] == 's-4vcpu-8gb-amd')['price_hourly'] = 0.09

        def region_down(sim):
            sim.account.regions[0]['available'] = False

        def image_gone(sim):
            sim.account.images.clear()

        def image_not_official(sim):
            sim.account.images[247516813]['public'] = False

        def image_is_a_snapshot(sim):
            sim.account.images[247516813]['type'] = 'snapshot'

        def image_needs_more_disk(sim):
            sim.account.images[247516813]['min_disk_size'] = 500

        def key_gone(sim):
            sim.account.ssh_keys.clear()

        def key_replaced(sim):
            key = next(iter(sim.account.ssh_keys.values()))
            key['public_key'] = OTHER_KEY

        def key_unreadable(sim):
            next(iter(sim.account.ssh_keys.values()))['public_key'] = 'ssh-ed25519 not*base64 x'

        for change in (wrong_project, inactive_account, no_quota, size_gone, size_unavailable, size_changed, price_changed, region_down,
                       image_gone, image_not_official, image_is_a_snapshot, image_needs_more_disk, key_gone, key_replaced, key_unreadable):
            with self.subTest(change.__name__):
                sim = pf.Sim(self)
                change(sim)
                self.assert_nothing_created(sim, sim.run(), 'preflight_refused')

    def test_failed_reads_refuse_rather_than_assume(self):
        for status, path in ((401, '/v2/account$'), (403, '/v2/sizes'), (503, '/v2/regions'), (429, '/v2/images'), (500, '/v2/projects')):
            with self.subTest(path):
                sim = pf.Sim(self)
                sim.account.fault('GET', path, 'status', status=status)
                self.assert_nothing_created(sim, sim.run(), 'provider_facts_unavailable')

    def test_a_pre_existing_session_resource_is_a_collision(self):
        def droplet(sim):
            sim.account._new_droplet(dict(name='anything', size='s-1vcpu-1gb-amd', region='sgp1', image=247516813, tags=[sim.manifest['session']['ownership_tags']['session']]))

        def firewall(sim):
            sim.account._new_firewall(dict(name=sim.session_id + '-fw', tags=[], inbound_rules=[], outbound_rules=[]))

        def tag(sim):
            sim.account.tags[sim.manifest['session']['ownership_tags']['bot']] = dict(name='x')

        for change in (droplet, firewall, tag):
            with self.subTest(change.__name__):
                sim = pf.Sim(self)
                change(sim)
                before = sim.account.live()
                self.assert_nothing_created(sim, sim.run(), 'preflight_refused')
                self.assertEqual(sim.account.live(), before)

    def test_missing_expired_or_mismatched_authorization_sends_nothing(self):
        def changes(sim):
            wall = sim.clock.wall()
            attestation = dict(sim.packet['scope_attestation'])
            return dict(wrong_session=dict(session_id='do-cap-other'), wrong_manifest=dict(manifest_sha256='0' * 64), wrong_gate=dict(gate='A'),
                        two_pairs=dict(max_pairs=2), expired=dict(not_after_utc=session_clock.iso(wall - 1)), not_yet=dict(not_before_utc=session_clock.iso(wall + 1)),
                        no_operator=dict(operator_request_ref=' '), small_spend=dict(max_estimated_session_usd=0.01), short_time=dict(max_session_duration_s=60),
                        small_transfer=dict(max_estimated_transfer_gib=1),
                        missing_scope=dict(scope_attestation=dict(attestation, scopes=['droplet:read'])),
                        token_expires=dict(scope_attestation=dict(attestation, controller_token_expires_at=session_clock.iso(wall + 60))),
                        watchdog_expires=dict(scope_attestation=dict(attestation, watchdog_token_expires_at=session_clock.iso(wall + 60))))
        names = sorted(changes(pf.Sim(self)))
        for name in names:
            with self.subTest(name):
                sim = pf.Sim(self)
                sim.packet = dict(sim.packet, **changes(sim)[name])
                result = sim.run()
                self.assert_nothing_created(sim, result, 'authorization_refused')
                self.assertEqual(sim.account.requests, [])

    def test_absent_authorization_refuses(self):
        sim = pf.Sim(self)
        sim.packet = {}
        self.assert_nothing_created(sim, sim.run(packet={}), 'authorization_refused')

    def test_adapter_without_a_gate_cannot_create(self):
        sim = pf.Sim(self)
        bare = do_api.DigitalOceanProvisioningProvider(sim.account)
        for call in (lambda: bare.create_tag('x'), lambda: bare.create_firewall({}), lambda: bare.create_droplet({}),
                     lambda: bare.update_firewall('00000001-0000-4000-8000-000000000000', {}), lambda: bare.assign_droplet('p', '1')):
            with self.assertRaises(create_evidence.CreateNotSent):
                call()
        self.assertEqual(sim.account.requests, [])

    def test_unhealthy_watchdog_creates_nothing(self):
        sim = pf.Sim(self)
        sim.clock.advance(120)      # no tick: the heartbeat is stale
        self.assert_nothing_created(sim, sim.run(), 'preflight_refused')

    def test_operator_address_in_a_broad_allowlist_is_refused_before_t0(self):
        sim = pf.Sim(self)
        sim.manifest['access_allowlists']['ssh_sources'] = ['203.0.113.0/24']
        sim.sha = manifest_mod.manifest_sha256(sim.manifest)
        sim.packet = pf.authorization(sim.manifest, sim.sha, sim.clock.wall())
        sim.gate.manifest_sha256 = sim.sha
        sim.gate.packet = sim.packet
        self.assert_nothing_created(sim, sim.run(), 'bootstrap_refused')

    def test_wrong_public_key_is_refused_before_t0(self):
        sim = pf.Sim(self)
        sim.public_key = OTHER_KEY
        self.assert_nothing_created(sim, sim.run(), 'bootstrap_refused')

    def test_rejected_after_registration_closes_without_a_deadline(self):
        sim = pf.Sim(self)
        original = sim.provider.account
        calls = []

        def failing_second_read():
            calls.append(1)
            if len(calls) > 1:
                raise cleanup_provider.ProviderTransient('503')
            return original()

        sim.provider.account = failing_second_read
        result = sim.run()
        self.assertEqual(result.status, provisioner.REJECTED)
        status = sim.status()
        self.assertEqual(status['state'], registry.CLOSED)
        self.assertEqual(status['overall'], 'closed_never_armed')
        self.assertIsNone(status['t0_utc'])


class CreateFailures(unittest.TestCase):
    def assert_owned_cleanup(self, sim, expect_overall=None):
        status = sim.drive_cleanup()
        if expect_overall:
            self.assertEqual(status['overall'], expect_overall)
        self.assertEqual(sim.session_droplets(), [])
        self.assertTrue(sim.unrelated_intact())
        self.assertTrue(sim.session_mutation_targets_only())
        return status

    def test_partial_pair_stops_and_cleans_only_owned(self):
        sim = pf.Sim(self)
        # The second droplet is refused, so the game droplet alone is created.
        original = sim.account._route_droplets

        def refuse_bot(method, parts, query, payload):
            if method == 'POST' and payload['name'].endswith('-bot'):
                return sim.account._reply(422, dict(id='unprocessable_entity', message='no capacity'))
            return original(method, parts, query, payload)
        sim.account._route_droplets = refuse_bot
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'create_rejected'))
        self.assertEqual(len(sim.session_droplets()), 1)
        self.assertEqual(sim.guests.commands, [])
        self.assert_owned_cleanup(sim, 'resources_verified_evidence_incomplete')

    def test_definitive_refusals_stop_without_a_retry(self):
        for status in (400, 401, 403, 422, 429):
            with self.subTest(status):
                sim = pf.Sim(self)
                sim.account.fault('POST', '^/v2/droplets$', 'status', status=status)
                result = sim.run()
                self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'create_rejected'), result)
                self.assertEqual(len(sim.creates('/v2/droplets')), 1)
                intent = next(i for i in sim.status()['intents'] if i['intent_id'].endswith(':droplet:game'))
                self.assertEqual(intent['state'], 'rejected')

    def test_connect_failure_is_not_sent_and_stays_settled(self):
        sim = pf.Sim(self)
        sim.account.fault('POST', '^/v2/firewalls$', 'not_sent', times=1)
        result = sim.run()
        self.assertEqual(result.code, 'create_not_sent', result)
        self.assertEqual(sim.status()['cleanup']['unresolved_creates'], [])
        self.assert_owned_cleanup(sim, 'resources_verified_evidence_incomplete')

    def test_a_grant_that_outlives_its_send_window_is_not_sent(self):
        sim = pf.Sim(self)
        sent = []
        original = sim.client.mutate

        def slow_grant(method, request_id=None, **params):
            answer = original(method, request_id, **params)
            if method == 'begin_create' and params['intent_id'].endswith(':droplet:game') and not sent:
                sent.append(1)
                sim.clock.advance(11)
            return answer
        sim.client.mutate = slow_grant
        result = sim.run()
        self.assertEqual(result.code, 'create_not_sent', result)
        self.assertEqual(sim.creates('/v2/droplets'), [])
        self.assertEqual(sim.status()['cleanup']['unresolved_creates'], [])

    def test_lost_response_that_landed_is_adopted_without_a_second_create(self):
        for action, options in (('lost', {}), ('garbled', {}), ('acted_status', dict(status=500))):
            with self.subTest(action):
                sim = pf.Sim(self)
                sim.account.fault('POST', '^/v2/droplets$', action, times=1, **options)
                result = sim.run()
                self.assertEqual(result.status, provisioner.READY, result)
                self.assertEqual(len(sim.creates('/v2/droplets')), 2)
                self.assertEqual(len(sim.session_droplets()), 2)

    def test_lost_firewall_and_tag_responses_are_adopted_too(self):
        for path in ('^/v2/firewalls$', '^/v2/tags$'):
            with self.subTest(path):
                sim = pf.Sim(self)
                sim.account.fault('POST', path, 'lost', times=1)
                result = sim.run()
                self.assertEqual(result.status, provisioner.READY, result)
                self.assertEqual(len(sim.creates('/v2/firewalls')), 1)
                self.assertEqual(len(sim.creates('/v2/tags')), 3)

    def test_landing_during_observation_is_adopted(self):
        sim = pf.Sim(self)
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=40.0)
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY, result)
        self.assertEqual(len(sim.creates('/v2/droplets')), 2)

    def test_unknown_create_never_settles_on_time_or_an_empty_listing(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'create_outcome_unknown'))
        self.assertEqual(len(sim.creates('/v2/droplets')), 1)
        status = sim.status()
        self.assertEqual(len(status['cleanup']['unresolved_creates']), 1)
        # Far past the observation window, past C and past D: still unresolved, never clean, firewall still protecting.
        session = sim.stack.registry.session_row(sim.session_id)
        sim.stack.step(1200)
        d = session_clock.parse(session['deadline_d_utc'])
        sim.clock.advance(d - sim.clock.wall() + 60)
        sim.stack.step(30)
        status = sim.status()
        self.assertNotEqual(status['state'], registry.CLOSED)
        self.assertEqual(status['overall'], 'cleanup_overdue')
        self.assertTrue(sim.account.firewalls.keys() - {sim.unrelated['firewall']})
        self.assertEqual(sim.provider.get_request_settlement(status['cleanup']['unresolved_creates'][0]['create_request_ref']), None)

    def test_operator_disposition_closes_but_is_not_clean(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
        result = sim.run()
        sim.client.mutate('record_evidence', session_id=sim.session_id, fencing_token=result.fencing_token, status='complete', ref='x')
        sim.stack.step(60)
        intent = sim.status()['cleanup']['unresolved_creates'][0]['intent_id']
        sim.stack.registry.dispose_create(sim.session_id, intent, 'checked the account by unique tag')
        status = sim.drive_cleanup()
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_WITH_DISPOSITION)
        self.assertEqual(status['overall'], 'resources_verified_with_operator_disposition')

    def test_late_landing_after_the_batch_stopped_is_found_deleted_and_blocks_false_closure(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=300.0)
        result = sim.run()
        self.assertEqual(result.code, 'create_outcome_unknown')
        sim.stack.step(120)
        self.assertNotEqual(sim.status()['state'], registry.CLOSED)
        status = sim.drive_cleanup()
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)
        self.assertEqual(sim.session_droplets(), [])
        self.assertEqual(len(sim.creates('/v2/droplets')), 1)
        self.assertTrue(any(r['source'] == 'discovered' for r in status['resources']))

    def test_duplicate_landing_is_recorded_and_both_are_deleted(self):
        sim = pf.Sim(self)
        tags = sim.manifest['session']['ownership_tags']
        # A second copy of the game droplet appears before the inventory check, as a replayed provider request would.
        original_assign = sim.provider.assign_droplet

        def assign_then_duplicate(project, droplet):
            original_assign(project, droplet)
            if len(sim.session_droplets()) == 2:
                duplicate = sim.account._new_droplet(dict(name=sim.session_id + '-game', size='s-1vcpu-1gb-amd', region='sgp1', image=247516813,
                                                          tags=[tags['session'], tags['game']]))
                duplicate['status'] = 'active'
        sim.provider.assign_droplet = assign_then_duplicate
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'unexpected_resource'))
        self.assertEqual(len(sim.status()['resources']) - 3 - 1, 3)      # three droplets besides tags and the firewall
        journal = [e['kind'] for e in sim.stack.registry.journal(sim.session_id)]
        self.assertIn('duplicate_create', journal)
        self.assert_owned_cleanup(sim)

    def test_registry_loss_after_a_create_is_not_a_lost_droplet(self):
        sim = pf.Sim(self)
        original = sim.client.mutate
        lost = []

        def lose_record(method, request_id=None, **params):
            if method == 'record_resource' and params.get('kind') == 'droplet' or lost:
                lost.append(method)
                raise registry_client.RegistryUnavailable('management host unreachable')
            return original(method, request_id, **params)
        sim.client.mutate = lose_record
        result = sim.run()
        self.assertEqual(result.status, provisioner.ABORT_UNACKNOWLEDGED, result)
        self.assertEqual(len(sim.session_droplets()), 1)
        sim.client.mutate = original
        # The controller is gone. The watchdog finds it by tag once C arrives.
        session = sim.stack.registry.session_row(sim.session_id)
        sim.clock.advance(session_clock.parse(session['cleanup_c_utc']) - sim.clock.wall())
        status = sim.drive_cleanup()
        self.assertEqual(sim.session_droplets(), [])
        self.assertEqual(status['cleanup']['reason'], 'deadline_C')

    def test_restarted_controller_fails_closed_rather_than_resuming(self):
        sim = pf.Sim(self)
        original = sim.guests.pin_host

        def crash(*_):
            raise KeyboardInterrupt
        sim.guests.pin_host = crash
        with self.assertRaises(KeyboardInterrupt):
            sim.run()
        self.assertEqual(len(sim.session_droplets()), 2)
        sim.guests.pin_host = original
        session = sim.stack.registry.session_row(sim.session_id)
        sim.clock.advance(session_clock.parse(session['lease_expires_at']) - sim.clock.wall() + 1)
        sim.stack.watchdog.tick()
        result = sim.run(client=pf.client_for(sim, 'controller-b'))
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'restart_fails_closed'), result)
        self.assertEqual(len(sim.creates('/v2/droplets')), 2)
        self.assert_owned_cleanup(sim)

    def test_live_lease_refuses_a_second_controller_outright(self):
        sim = pf.Sim(self)
        original = sim.guests.pin_host

        def second_controller(*args):
            sim.guests.pin_host = original
            intruder = sim.run(client=pf.client_for(sim, 'controller-b'))
            self.assertEqual((intruder.status, intruder.code), (provisioner.REJECTED, 'control_unavailable'))
            return original(*args)
        sim.guests.pin_host = second_controller
        self.assertEqual(sim.run().status, provisioner.READY)
        self.assertEqual(len(sim.creates('/v2/droplets')), 2)


class SessionKinds(unittest.TestCase):
    CALIBRATION_SESSION = 'do-cal-1v1g-20261105a'

    def test_calibration_learns_the_binary_hash_instead_of_freezing_one(self):
        sim = pf.Sim(self, session_id=self.CALIBRATION_SESSION, kind='calibration')
        observed = 'f' * 64

        def fresh_release(role, step):
            def change(document):
                document['release']['omega-server'] = observed
                return document
            sim.guests.overrides[(role, step)] = change
        fresh_release('bot', 'build')
        fresh_release('game', 'install_release')
        fresh_release('game', 'probe')
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY, result)
        report = json.loads((sim.evidence.root / 'readiness.json').read_text())
        self.assertEqual(report['binary_hash_basis'], 'observed_for_calibration')

    def test_calibration_still_proves_the_relayed_copy_is_what_was_built(self):
        sim = pf.Sim(self, session_id=self.CALIBRATION_SESSION, kind='calibration')
        sim.guests.break_step('game', 'install_release', release={'omega-server': 'f' * 64})
        self.assertEqual(sim.run().code, 'build_verification_failed')

    def test_capacity_refuses_a_binary_that_differs_from_the_frozen_hash(self):
        sim = pf.Sim(self)

        def change(document):
            document['release']['omega-server'] = 'f' * 64
            return document
        sim.guests.overrides[('bot', 'build')] = change
        result = sim.run()
        self.assertEqual(result.code, 'build_verification_failed', result)
        self.assertIn('binary_game', result.detail)

    def test_a_calibration_gate_cannot_cover_a_capacity_session(self):
        sim = pf.Sim(self)
        sim.packet['gate'] = 'A'
        self.assertEqual(sim.run().code, 'authorization_refused')

    def test_non_capacity_sessions_must_still_fit_setup_and_limits(self):
        sim = pf.Sim(self, session_id=self.CALIBRATION_SESSION, kind='calibration', cap_s=1200)
        sim.packet = pf.authorization(sim.manifest, sim.sha, sim.clock.wall())
        sim.gate.packet = sim.packet
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.REJECTED, 'admission_refused'), result)
        self.assertEqual(sim.account.mutations(), [])


class RegistryAndLocalFailures(unittest.TestCase):
    def test_capacity_refusal_creates_nothing_and_leaves_the_session_able_to_arm_later(self):
        sim = pf.Sim(self)
        original = sim.client.mutate

        def refused(method, request_id=None, **params):
            if method == 'arm_session':
                raise registry_client.RegistryRejected('deadline_capacity_exceeded', 'full', dict(retry_after_s=77.0))
            return original(method, request_id, **params)
        sim.client.mutate = refused
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.REJECTED, 'deadline_capacity_exceeded'), result)
        self.assertIn('77', result.detail)
        self.assertEqual(sim.account.mutations(), [])
        self.assertEqual(sim.status()['state'], registry.REGISTERED)

    def test_unverifiable_time_after_a_reboot_fails_closed_mid_bootstrap(self):
        sim = pf.Sim(self)
        original = sim.guests.pin_host
        rebooted = []

        def reboot(*args):
            if not rebooted:
                rebooted.append(1)
                sim.stack.restart_watchdog(reboot=True, downtime_s=60.0, rtc_error_s=-30.0)
                sim.client.transport = sim.stack.client.transport
            return original(*args)
        sim.guests.pin_host = reboot
        result = sim.run()
        self.assertNotEqual(result.status, provisioner.READY, result)
        status = sim.status()
        self.assertEqual(status['cleanup']['reason'], registry.CLOCK_UNVERIFIABLE_REASON)
        self.assertTrue(status['cleanup']['deadline_uncertain'])
        self.assertTrue(status['cleanup']['overdue'])
        self.assertIsNone(sim.stack.registry.session_row(sim.session_id)['ready_at'])

    def test_local_evidence_failure_asks_for_cleanup(self):
        sim = pf.Sim(self)
        original = sim.evidence.event

        def full_disk(kind, **data):
            if kind == 'droplet_verified':
                raise OSError('no space left')
            return original(kind, **data)
        sim.evidence.event = full_disk
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'local_failure'), result)
        self.assertEqual(sim.status()['state'], registry.DELETING)

    def test_a_defect_still_asks_for_cleanup_while_resources_bill(self):
        sim = pf.Sim(self)
        sim.provider.project_resource_urns = lambda project: 1 / 0
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'internal_error'), result)
        self.assertEqual(sim.status()['state'], registry.DELETING)

    def test_a_503_on_a_create_stays_unknown_and_never_retries(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        sim.account.fault('POST', '^/v2/droplets$', 'status', status=503)
        result = sim.run()
        self.assertEqual(result.code, 'create_outcome_unknown', result)
        self.assertEqual(len(sim.creates('/v2/droplets')), 1)

    def test_persistent_outage_during_observation_settles_nothing(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        original = sim.provider.create_droplet

        def outage_after_send(payload, **limits):
            sim.account.outage()
            return original(payload, **limits)
        sim.provider.create_droplet = outage_after_send
        result = sim.run()
        self.assertEqual(result.code, 'create_outcome_unknown', result)
        self.assertEqual(len(sim.status()['cleanup']['unresolved_creates']), 1)
        journal = (sim.evidence.root / 'journal.ndjson').read_text()
        self.assertIn('reconcile_read_failed', journal)

    def test_a_closed_session_id_is_never_provisioned_again(self):
        sim = pf.Sim(self)
        first = sim.run()
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=first.fencing_token, reason='done')
        sim.drive_cleanup()
        creates = len(sim.creates('/v2/droplets'))
        second = sim.run(client=pf.client_for(sim, 'controller-b'))
        self.assertEqual((second.status, second.code), (provisioner.REJECTED, 'session_already_closed'))
        self.assertEqual(len(sim.creates('/v2/droplets')), creates)


class WrongConditions(unittest.TestCase):
    def test_wrong_plan_stops_and_is_deleted_as_owned(self):
        sim = pf.Sim(self)
        sim.account.wrong_size[sim.session_id + '-game'] = 's-2vcpu-4gb-amd'
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'wrong_plan'))
        self.assertIn('game:size', result.detail)
        self.assertEqual(sim.guests.commands, [])
        sim.drive_cleanup()
        self.assertEqual(sim.session_droplets(), [])
        self.assertTrue(sim.unrelated_intact())

    def test_droplet_vanishing_while_converging_stops(self):
        sim = pf.Sim(self)
        original = sim.account._route_droplets

        def vanish(method, parts, query, payload):
            if method == 'GET' and len(parts) == 1:
                return sim.account._not_found()
            return original(method, parts, query, payload)
        sim.account._route_droplets = vanish
        result = sim.run()
        self.assertEqual(result.code, 'droplet_vanished')

    def test_project_assignment_failure_stops_and_cleans(self):
        def refuse(sim):
            sim.account.fault('POST', '/v2/projects/.*/resources', 'status', status=500)

        def unconfirmed(sim):
            sim.account.assignment_status = 'service_down'

        def not_listed(sim):
            original = sim.provider.project_resource_urns
            sim.provider.project_resource_urns = lambda project: original(project) - {u for u in original(project) if 'do:droplet:5000' in u and u[-1] != '0' and u[-1] != '1'}

        for change in (refuse, unconfirmed, not_listed):
            with self.subTest(change.__name__):
                sim = pf.Sim(self)
                sim.policy = FAST_OBSERVE
                change(sim)
                result = sim.run()
                self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'project_assignment_failed'), result)
                sim.account.clear_faults()
                sim.drive_cleanup()
                self.assertEqual(sim.session_droplets(), [])
                self.assertTrue(sim.unrelated_intact())

    def test_project_membership_never_authorizes_a_delete(self):
        sim = pf.Sim(self)
        sim.run()
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=sim.status()['fencing_token'], reason='stop')
        status = sim.drive_cleanup()
        self.assertIn('do:droplet:%d' % sim.unrelated['droplets'][0], sim.account.project_urns)
        self.assertTrue(sim.unrelated_intact())
        self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_firewall_that_comes_back_wrong_stops_before_any_droplet(self):
        def mangle(sim, change):
            original = sim.account._new_firewall

            def create(payload):
                return original(change(dict(payload)))
            sim.account._new_firewall = create

        cases = dict(extra_world_rule=lambda p: dict(p, inbound_rules=p['inbound_rules'] + [dict(protocol='tcp', ports='9100', sources=dict(addresses=['0.0.0.0/0']))]),
                     wrong_targets=lambda p: dict(p, tags=['prod']), direct_droplets=lambda p: dict(p, droplet_ids=[1]))
        for name, change in cases.items():
            with self.subTest(name):
                sim = pf.Sim(self)
                mangle(sim, change)
                result = sim.run()
                self.assertIn(result.code, ('firewall_verification_failed',), result)
                self.assertEqual(sim.creates('/v2/droplets'), [])

    def test_firewall_failures_after_droplets_exist_clean_up_owned_only(self):
        def failed_status(sim):
            original = sim.account._firewall_view

            def view(firewall):
                result = original(firewall)
                if firewall['name'] == sim.session_id + '-fw' and sim.account.ops('PUT'):
                    result['status'] = 'failed'
                return result
            sim.account._firewall_view = view

        def never_applies(sim):
            original = sim.account._firewall_view

            def view(firewall):
                result = original(firewall)
                result['pending_changes'] = [dict(droplet_id=1, removing=False, status='waiting')] if sim.account.ops('PUT') else []
                return result
            sim.account._firewall_view = view

        def put_refused(sim):
            sim.account.fault('PUT', '/v2/firewalls/.*', 'status', status=500)

        def rules_reset(sim):
            original = sim.account._apply_firewall

            def reset(firewall, payload):
                original(firewall, dict(payload, tags=[]))
            sim.account._apply_firewall = reset

        for change in (failed_status, never_applies, put_refused, rules_reset):
            with self.subTest(change.__name__):
                sim = pf.Sim(self)
                sim.policy = FAST_OBSERVE
                change(sim)
                result = sim.run()
                self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'firewall_verification_failed'), result)
                self.assertEqual(sim.guests.commands, [])

    def test_ownership_ambiguity_at_lookup_refuses_adoption_and_never_deletes(self):
        sim = pf.Sim(self)
        tags = sim.manifest['session']['ownership_tags']
        sim.policy = FAST_OBSERVE
        # The create response is lost. What shows up has the unique session tag and name but not the role tag.
        original = sim.account._route_droplets

        def land_wrong(method, parts, query, payload):
            if method == 'POST':
                return original(method, parts, query, dict(payload, tags=[tags['session'], 'foreign']))
            return original(method, parts, query, payload)
        sim.account._route_droplets = land_wrong
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1)
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'ownership_ambiguous'), result)
        sim.stack.step(60)
        status = sim.status()
        self.assertTrue(any(i['kind'] == 'ownership-mismatch' for i in status['incidents']))
        self.assertEqual(sim.account.ops('DELETE', '^/v2/droplets/'), [])
        self.assertEqual(len(sim.session_droplets()), 1)

    def test_same_name_without_the_session_tag_is_never_adopted_or_deleted(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        imposter = sim.account._new_droplet(dict(name=sim.session_id + '-game', size='s-1vcpu-1gb-amd', region='sgp1', image=247516813, tags=['prod']))
        sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
        result = sim.run()
        self.assertEqual(result.code, 'create_outcome_unknown', result)
        sim.stack.step(60)
        self.assertIn(imposter['id'], sim.account.droplets)
        self.assertEqual(sim.account.ops('DELETE', '/v2/droplets/%d$' % imposter['id']), [])


class BootstrapFailures(unittest.TestCase):
    def stops(self, sim, code='bootstrap_failed'):
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, code), result)
        return result

    def test_cloud_init_failure_stops_and_cleans(self):
        sim = pf.Sim(self)
        sim.guests.break_step('game', 'wait_cloud_init', rc=1, status='error', errors=['boom'])
        self.stops(sim)
        sim.drive_cleanup()
        self.assertEqual(sim.session_droplets(), [])
        self.assertTrue(sim.unrelated_intact())

    def test_host_that_never_answers_stops_within_the_contact_wait(self):
        sim = pf.Sim(self)
        sim.policy = FAST_OBSERVE
        sim.guests.silent_until['bot'] = sim.clock.wall() + 100000
        self.stops(sim)
        self.assertEqual(sim.guests.steps('bot'), [])

    def test_impostor_host_key_is_never_pinned_and_stops(self):
        sim = pf.Sim(self)
        sim.guests.impostor.add('game')
        self.stops(sim, 'host_verification_failed')
        self.assertNotIn('game', sim.guests.pins)
        self.assertEqual(sim.guests.steps('game'), [])

    def test_nonzero_exit_timeout_and_bad_output_each_stop(self):
        for step, role in (('fetch_source', 'bot'), ('build', 'bot'), ('install_release', 'game'), ('probe', 'game'), ('sampler', 'bot')):
            with self.subTest(step):
                sim = pf.Sim(self)
                sim.guests.exit_codes[(role, step)] = 2
                self.stops(sim)
        sim = pf.Sim(self)
        sim.guests.exit_codes[('bot', 'build')] = None
        self.stops(sim)
        sim = pf.Sim(self)
        original = sim.guests.run

        def broken_output(role, argv, timeout_s, on_wait=None):
            result = original(role, argv, timeout_s, on_wait)
            if 'fetch_source' in argv:
                return type(result)(0, 'not a json document', '')
            return result
        sim.guests.run = broken_output
        self.stops(sim)

    def test_copy_failures_stop(self):
        for failure in (('bot', 'get'), ('game', 'put')):
            with self.subTest(failure):
                sim = pf.Sim(self)
                sim.guests.copy_failures.add(failure)
                self.stops(sim)

    def test_source_and_build_mismatches_stop(self):
        cases = dict(head=('fetch_source', dict(head='f' * 40)), dirty=('fetch_source', dict(clean=False)), lock=('fetch_source', dict(cargo_lock_sha256='f' * 64)),
                     config=('fetch_source', dict(server_config_sha256='f' * 64)), content=('fetch_source', dict(content_sha256='f' * 64)),
                     failed=('build', dict(ok=False, rc=101)), dirtied=('build', dict(clean_after_build=False)), rustc=('build', dict(rustc='rustc 1.0.0 (x)\nhost: x86_64-unknown-linux-gnu')),
                     host=('build', dict(rustc='rustc 1.91.0 (x)\nhost: aarch64-unknown-linux-gnu')), flags=('build', dict(flags=['--features=x'])))
        for name, (step, fields) in cases.items():
            with self.subTest(name):
                sim = pf.Sim(self)
                sim.guests.break_step('bot', step, **fields)
                result = sim.run()
                self.assertEqual(result.code, 'build_verification_failed', result)

    def test_binary_changed_in_transit_stops(self):
        sim = pf.Sim(self)
        sim.guests.break_step('game', 'install_release', release={'omega-server': 'f' * 64})
        result = sim.run()
        self.assertEqual(result.code, 'build_verification_failed', result)

    def test_a_firewall_that_lets_the_bot_reach_ssh_stops_before_ready(self):
        for outcome in ('connected', 'refused'):
            with self.subTest(outcome):
                sim = pf.Sim(self)
                sim.guests.break_step('bot', 'tcp_probe', outcome=outcome)
                result = sim.run()
                self.assertEqual(result.code, 'readiness_failed', result)
                self.assertIn('ssh_from_bot_blocked', result.detail)

    def test_failed_enet_smoke_stops_and_still_stops_the_game_process(self):
        sim = pf.Sim(self)
        sim.guests.break_step('bot', 'smoke_bot', connected_bots=0)
        result = sim.run()
        self.assertEqual(result.code, 'readiness_failed')
        self.assertIn('bots_connected', result.detail)
        self.assertIn('smoke_game_stop', sim.guests.steps('game'))

    def test_a_smoke_that_exits_nonzero_still_stops_the_game_process(self):
        sim = pf.Sim(self)
        sim.guests.exit_codes[('bot', 'smoke_bot')] = 1
        self.stops(sim)
        self.assertIn('smoke_game_stop', sim.guests.steps('game'))

    def test_budget_exhaustion_stops_rather_than_extending(self):
        sim = pf.Sim(self)
        import fake_guest
        original = dict(fake_guest.AGENT_SECONDS)
        fake_guest.AGENT_SECONDS['build'] = 5000
        self.addCleanup(lambda: fake_guest.AGENT_SECONDS.update(original))
        result = sim.run()
        self.assertEqual(result.status, provisioner.ABORTED)
        self.assertEqual(result.code, 'provisioning_budget_exhausted', result)
        self.assertEqual(sim.armed_acks[0]['deadline_d_utc'], sim.status()['deadline_d_utc'])

    def test_cleanup_started_elsewhere_stops_this_controller(self):
        sim = pf.Sim(self)
        original = sim.guests.pin_host

        def operator_aborts(*args):
            sim.stack.registry.operator_abort(sim.session_id, 'operator stop')
            return original(*args)
        sim.guests.pin_host = operator_aborts
        result = sim.run()
        self.assertEqual((result.status, result.code), (provisioner.ABORTED, 'cleanup_started_elsewhere'), result)
        self.assertNotIn('build', sim.guests.steps())

    def test_deadline_reached_during_bootstrap_loses_to_the_watchdog(self):
        sim = pf.Sim(self, cap_s=14400)
        original = sim.guests.pin_host

        def clock_runs_out(*args):
            session = sim.stack.registry.session_row(sim.session_id)
            sim.clock.advance(session_clock.parse(session['cleanup_c_utc']) - sim.clock.wall())
            sim.stack.watchdog.tick()
            return original(*args)
        sim.guests.pin_host = clock_runs_out
        result = sim.run()
        self.assertEqual(result.status, provisioner.ABORTED)
        self.assertEqual(sim.status()['cleanup']['reason'], 'deadline_C')
        self.assertIsNone(sim.stack.registry.session_row(sim.session_id)['ready_at'])


class ChangedOperatorAddress(unittest.TestCase):
    NEW = '198.51.100.200/32'

    def ready(self):
        sim = pf.Sim(self)
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY)
        return sim, result

    def refresh(self, sim, result, ssh=None, udp=None):
        return provisioner.refresh_access(sim.client, sim.provider, sim.manifest, result.fencing_token, ssh if ssh is not None else [self.NEW],
                                          udp if udp is not None else [self.NEW], sim.sleep, sim.monotonic, policy=FAST_OBSERVE, evidence=sim.evidence)

    def test_refresh_replaces_the_old_address_exactly_and_uses_no_ssh(self):
        sim, result = self.ready()
        before = len(sim.guests.commands)
        outcome = self.refresh(sim, result)
        self.assertTrue(outcome['applied'], outcome)
        firewall = sim.provider.get_firewall(result.firewall_id)
        bot = sim.provider.get_droplet(result.droplets['bot'])
        rules = {r['ports']: r['sources']['addresses'] for r in firewall['inbound_rules']}
        self.assertEqual(rules['22'], [self.NEW])
        self.assertEqual(rules['8081'], sorted([self.NEW, bot['public_ipv4'][0] + '/32']))
        self.assertEqual(len(sim.guests.commands), before)
        tags = sim.manifest['session']['ownership_tags']
        self.assertEqual(sorted(firewall['tags']), sorted((tags['game'], tags['bot'])))

    def test_broad_or_unroutable_sources_send_nothing(self):
        for bad in (['0.0.0.0/0'], ['::/0'], ['198.51.100.0/24'], ['10.1.2.3/32'], ['127.0.0.1/32'], ['not-an-address'], ['169.254.1.1/32'], []):
            with self.subTest(bad):
                sim, result = self.ready()
                puts = len(sim.account.ops('PUT'))
                with self.assertRaises(session_access.AccessRefused):
                    self.refresh(sim, result, ssh=bad, udp=[])
                self.assertEqual(len(sim.account.ops('PUT')), puts)

    def test_outage_during_refresh_leaves_the_previous_exact_rules(self):
        sim, result = self.ready()
        before = sim.provider.get_firewall(result.firewall_id)['inbound_rules']
        sim.account.fault('PUT', '/v2/firewalls/.*', 'status', status=503)
        outcome = self.refresh(sim, result)
        self.assertFalse(outcome['applied'])
        self.assertEqual(sim.provider.get_firewall(result.firewall_id)['inbound_rules'], before)
        self.assertEqual(sim.status()['state'], registry.READY)

    def test_lost_refresh_response_is_verified_by_reading_back(self):
        sim, result = self.ready()
        sim.account.fault('PUT', '/v2/firewalls/.*', 'lost', times=1)
        outcome = self.refresh(sim, result)
        self.assertTrue(outcome['applied'], outcome)

    def test_a_stale_controller_cannot_refresh(self):
        sim, result = self.ready()
        sim.clock.advance(100)
        sim.stack.watchdog.tick()
        with self.assertRaises(registry_client.RegistryRejected) as raised:
            self.refresh(sim, result)
        self.assertEqual(raised.exception.code, 'lease_expired')

    def test_refresh_is_refused_during_cleanup(self):
        sim, result = self.ready()
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='done')
        with self.assertRaises(provisioner.Stop) as raised:
            self.refresh(sim, result)
        self.assertEqual(raised.exception.code, 'cleanup_in_progress')

    def test_a_firewall_with_foreign_targets_is_not_updated(self):
        sim, result = self.ready()
        sim.account.firewalls[result.firewall_id]['tags'] = ['prod']
        puts = len(sim.account.ops('PUT'))
        with self.assertRaises(provisioner.Stop) as raised:
            self.refresh(sim, result)
        self.assertEqual(raised.exception.code, 'ownership_ambiguous')
        self.assertEqual(len(sim.account.ops('PUT')), puts)

    def test_expired_authorization_refuses_a_refresh(self):
        sim, result = self.ready()
        sim.packet['not_after_utc'] = session_clock.iso(sim.clock.wall() - 1)
        with self.assertRaises(remote_authorization.MutationRefused):
            self.refresh(sim, result)


class AcceptedDeleteVersusAbsence(unittest.TestCase):
    def stopped(self, **options):
        sim = pf.Sim(self, **options)
        result = sim.run()
        sim.client.mutate('record_evidence', session_id=sim.session_id, fencing_token=result.fencing_token, status='complete', ref='x')
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='done')
        return sim, result

    def test_accepted_delete_alone_does_not_close(self):
        sim, _ = self.stopped()
        sim.account.linger_reads = 20
        sim.stack.step(60)
        status = sim.status()
        self.assertNotEqual(status['state'], registry.CLOSED)
        self.assertTrue(any(r['status'] in ('delete_accepted', 'unverified') for r in status['resources'] if r['kind'] == 'droplet'))
        self.assertGreaterEqual(len(sim.account.ops('DELETE', '^/v2/droplets/')), 2)
        status = sim.drive_cleanup()
        self.assertEqual(status['overall'], 'clean')

    def test_failed_reads_are_never_absence(self):
        for status_code in (500, 401, 403):
            with self.subTest(status_code):
                sim, _ = self.stopped()
                sim.account.fault('GET', r'^/v2/droplets/\d+$', 'status', status=status_code)
                sim.stack.step(120)
                self.assertNotEqual(sim.status()['state'], registry.CLOSED)
                sim.account.clear_faults()
                status = sim.drive_cleanup()
                self.assertEqual(sim.session_droplets(), [])
                self.assertEqual(status['cleanup']['outcome'], registry.VERIFIED_ABSENT)

    def test_a_malformed_ok_is_not_an_empty_listing(self):
        sim, _ = self.stopped()
        original = sim.account._route_droplets

        def unlisted(method, parts, query, payload):
            if method == 'GET' and not parts:
                return sim.account._reply(200, dict(unexpected=True))
            return original(method, parts, query, payload)
        sim.account._route_droplets = unlisted
        sim.stack.step(200)
        self.assertNotEqual(sim.status()['state'], registry.CLOSED)
        sim.account._route_droplets = original
        sim.drive_cleanup()

    def test_stopped_guest_is_not_destruction(self):
        sim, _ = self.stopped()
        for droplet in sim.account.droplets.values():
            droplet['status'] = 'off'
        sim.account.linger_reads = 5
        sim.stack.step(30)
        self.assertNotEqual(sim.status()['state'], registry.CLOSED)
        sim.drive_cleanup()
        self.assertEqual(sim.session_droplets(), [])

    def test_persistent_outage_goes_overdue_and_recovers_with_the_breach_visible(self):
        sim = pf.Sim(self, cap_s=14400)
        result = sim.run()
        sim.client.mutate('record_evidence', session_id=sim.session_id, fencing_token=result.fencing_token, status='complete', ref='x')
        rule = sim.account.outage()
        session = sim.stack.registry.session_row(sim.session_id)
        sim.clock.advance(session_clock.parse(session['deadline_d_utc']) - sim.clock.wall() + 30)
        sim.stack.step(120)
        status = sim.status()
        self.assertEqual(status['overall'], 'cleanup_overdue')
        self.assertTrue(status['cleanup']['overdue'])
        self.assertEqual(len(sim.session_droplets()), 2)
        sim.account.rules.remove(rule)
        status = sim.drive_cleanup()
        self.assertEqual(status['overall'], 'resources_verified_after_overdue')
        self.assertGreater(status['cleanup']['overrun_s'], 0)

    def test_rate_limit_guidance_holds_the_watchdog(self):
        sim, _ = self.stopped()
        rule = sim.account.fault('DELETE', '^/v2/droplets/', 'status', status=429)
        sim.stack.step(30)
        hold = sim.stack.registry.watchdog_view()['rate_limit_hold_until']
        self.assertIsNotNone(hold)
        sim.account.rules.remove(rule)
        sim.drive_cleanup()

    def test_multi_page_inventory_finds_a_late_droplet_past_page_one(self):
        sim = pf.Sim(self, account_options=dict(max_per_page=1))
        result = sim.run()
        self.assertEqual(result.status, provisioner.READY, result)
        tags = sim.manifest['session']['ownership_tags']
        sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='done')
        late = sim.account._new_droplet(dict(name=sim.session_id + '-bot', size='s-4vcpu-8gb-amd', region='sgp1', image=247516813, tags=[tags['session'], tags['bot']]))
        sim.drive_cleanup()
        self.assertNotIn(late['id'], sim.account.droplets)
        self.assertEqual(sim.session_droplets(), [])
        self.assertTrue(sim.unrelated_intact())

    def test_shared_resources_survive_every_cleanup(self):
        sim, _ = self.stopped()
        sim.drive_cleanup()
        self.assertEqual(sim.account.ops('DELETE', '/v2/account'), [])
        self.assertEqual(sim.account.ops('DELETE', '/v2/projects'), [])
        self.assertEqual(sim.account.ops('DELETE', '/v2/images'), [])
        self.assertTrue(sim.account.ssh_keys)
        self.assertEqual(sim.account.ops('DELETE', r'^/v2/droplets$'), [])
        self.assertTrue(sim.unrelated_intact())


if __name__ == '__main__':
    unittest.main()
