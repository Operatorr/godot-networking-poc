"""The real adapter's request and status semantics, and its one-attempt transport over a loopback socket."""
import http.client
import json
import os
import pathlib
import socket
import ssl
import tempfile
import threading
import time
import unittest
import unittest.mock

import cleanup_provider
import create_evidence
import do_api
import fake_do_http
import fixture_support as fx
import manifest as manifest_mod
import registry_cli
import remote_authorization
import session_access
import session_clock

UUID = '00000001-0000-4000-8000-000000000000'


def answer(status, document=None, headers=None):
    return do_api.HttpResponse(status, headers or {}, b'' if document is None else json.dumps(document).encode())


class Script:
    """Answer every request with the next scripted response; list what was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, target, body=None, request_bound_s=None, send_by=None, send_guard=None):
        self.calls.append(dict(method=method, target=target, body=body, bound=request_bound_s, send_by=send_by))
        if send_guard is not None:
            send_guard.confirm()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def provider(*responses):
    return do_api.DigitalOceanProvider(Script(*responses), wall=lambda: 1000.0)


def controller(*responses, gate=None):
    transport = Script(*responses)
    return do_api.DigitalOceanProvisioningProvider(transport, gate=gate or OpenGate(), wall=lambda: 1000.0), transport


class OpenGate:
    def check(self, *_):
        pass

    def send_guard(self, action):
        return None


class Routes(unittest.TestCase):
    def test_watchdog_adapter_has_no_create_update_or_assign(self):
        adapter = do_api.DigitalOceanProvider(Script())
        for name in ('create_tag', 'create_firewall', 'create_droplet', 'update_firewall', 'assign_droplet'):
            self.assertFalse(hasattr(adapter, name), name)
        self.assertFalse([route for route in do_api.WATCHDOG_ROUTES if route[0] in ('POST', 'PUT', 'PATCH')])

    def test_watchdog_routes_refuse_everything_outside_exact_reads_and_deletes(self):
        adapter = do_api.DigitalOceanProvider(Script())
        for method, path in (('POST', '/v2/droplets'), ('DELETE', '/v2/droplets'), ('DELETE', '/v2/account/keys/1'), ('DELETE', '/v2/projects/' + UUID),
                             ('DELETE', '/v2/images/1'), ('PUT', '/v2/firewalls/' + UUID), ('GET', '/v2/account')):
            with self.assertRaises(do_api.RouteRefused, msg=method + path):
                adapter._send(method, path)

    def test_no_route_can_delete_by_tag_or_touch_keys_projects_or_images(self):
        for method, pattern in do_api.CONTROLLER_ROUTES:
            if method == 'DELETE':
                self.assertRegex(pattern.pattern, r'/v2/(droplets|firewalls|tags)/')
            if method in ('POST', 'PUT', 'DELETE'):
                self.assertNotIn('keys', pattern.pattern)
                self.assertNotIn('images', pattern.pattern)
        projects = [(m, p.pattern) for m, p in do_api.CONTROLLER_ROUTES if 'projects' in p.pattern and m != 'GET']
        self.assertEqual(len(projects), 1)
        self.assertTrue(projects[0][1].endswith('/resources$'))

    def test_identifiers_cannot_escape_their_route(self):
        adapter = do_api.DigitalOceanProvider(Script())
        for call in (lambda: adapter.get_droplet('1/../../account'), lambda: adapter.delete_droplet('1?tag_name=prod'), lambda: adapter.delete_droplet(''),
                     lambda: adapter.delete_firewall('../account'), lambda: adapter.get_firewall('not-a-uuid'), lambda: adapter.list_droplets_by_tag('')):
            with self.assertRaises(do_api.RouteRefused):
                call()
        self.assertEqual(adapter.transport.calls, [])

    def test_tag_names_are_encoded_into_their_one_path_segment(self):
        adapter = provider(answer(204))
        adapter.delete_tag('omega-session:abc/x')
        self.assertEqual(adapter.transport.calls[0]['target'], '/v2/tags/omega-session%3Aabc%2Fx')
        with self.assertRaises(do_api.RouteRefused):
            adapter.delete_tag('../account')


class StatusMapping(unittest.TestCase):
    def test_reads(self):
        self.assertIsNone(provider(answer(404)).get_droplet('1'))
        self.assertIsNone(provider(answer(404)).get_firewall(UUID))
        self.assertIsNone(provider(answer(404)).get_tag('t'))
        with self.assertRaises(cleanup_provider.ProviderAuthError):
            provider(answer(401)).get_droplet('1')
        with self.assertRaises(cleanup_provider.ProviderAuthError):
            provider(answer(403)).get_droplet('1')
        for status in (500, 502, 503, 408, 422, 301):
            with self.assertRaises(cleanup_provider.ProviderTransient):
                provider(answer(status)).get_droplet('1')

    def test_rate_limit_carries_the_provider_guidance(self):
        with self.assertRaises(cleanup_provider.ProviderRateLimited) as raised:
            provider(answer(429, headers={'retry-after': '17'})).get_droplet('1')
        self.assertEqual(raised.exception.retry_after_s, 17.0)
        with self.assertRaises(cleanup_provider.ProviderRateLimited) as raised:
            provider(answer(429, headers={'ratelimit-reset': '1090'})).get_droplet('1')
        self.assertEqual(raised.exception.retry_after_s, 90.0)
        with self.assertRaises(cleanup_provider.ProviderRateLimited) as raised:
            provider(answer(429)).get_droplet('1')
        self.assertIsNone(raised.exception.retry_after_s)

    def test_a_response_for_another_resource_is_not_that_resource(self):
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(droplet=dict(id=2, name='x', tags=[], status='active')))).get_droplet('1')
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(firewall=dict(id='other', name='x')))).get_firewall(UUID)
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(tag=dict(name='other', resources=dict(count=0))))).get_tag('t')

    def test_malformed_success_is_a_failure_and_never_absence(self):
        for body in (dict(unexpected=1), dict(droplet=dict(id=1))):
            with self.assertRaises(cleanup_provider.ProviderTransient):
                provider(answer(200, body)).get_droplet('1')
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(do_api.HttpResponse(200, {}, b'<html>')).get_droplet('1')
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(tag=dict(name='t')))).get_tag('t')

    def test_a_200_without_a_record_is_never_absence_for_any_getter(self):
        def adapter(body):
            return controller(answer(200, body))[0]

        getters = (('droplet', lambda a: a.get_droplet('1')), ('firewall', lambda a: a.get_firewall(UUID)), ('tag', lambda a: a.get_tag('t')),
                   ('account', lambda a: a.account()), ('image', lambda a: a.image('1')), ('ssh_key', lambda a: a.ssh_key('1')), ('project', lambda a: a.project(UUID)))
        for key, read in getters:
            for value in (None, 0, False, '', 'text', 1, [], [dict(id=1)]):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(cleanup_provider.ProviderTransient):
                        read(adapter({key: value}))
            with self.subTest(key=key, value='404'):
                self.assertIsNone(read(controller(answer(404))[0]))

    def test_a_listing_that_holds_a_non_record_is_a_failure(self):
        for item in (None, 1, 'x', []):
            with self.subTest(item), self.assertRaises(cleanup_provider.ProviderTransient):
                provider(answer(200, dict(firewalls=[item], links={}, meta=dict(total=1)))).list_firewalls_by_name('fw')

    def test_deletes_accept_only_what_the_seam_allows(self):
        for status in (200, 202, 204, 404):
            provider(answer(status)).delete_droplet('1')
        for status, error in ((401, cleanup_provider.ProviderAuthError), (429, cleanup_provider.ProviderRateLimited),
                              (500, cleanup_provider.ProviderTransient), (409, cleanup_provider.ProviderTransient)):
            with self.assertRaises(error):
                provider(answer(status)).delete_droplet('1')

    def test_transport_failures_are_transient_everywhere_but_create(self):
        for failure in (do_api.RequestNotSent('x'), do_api.RequestOutcomeUnknown('y')):
            with self.assertRaises(cleanup_provider.ProviderTransient):
                provider(failure).get_droplet('1')
            with self.assertRaises(cleanup_provider.ProviderTransient):
                provider(failure).delete_droplet('1')

    def test_no_settlement_basis_exists_for_this_provider(self):
        self.assertIsNone(provider().get_request_settlement('intent#1'))
        self.assertFalse(hasattr(do_api, 'SETTLEMENT_BASIS'))
        self.assertEqual(create_evidence.DEFAULT_TRUSTED_BASES, ())

    def test_error_text_never_includes_credentials(self):
        leaky = dict(id='Authorization: Bearer ' + 'a' * 40)
        with self.assertRaises(cleanup_provider.ProviderTransient) as raised:
            provider(answer(500, leaky)).get_droplet('1')
        self.assertNotIn('a' * 40, str(raised.exception))


class Listings(unittest.TestCase):
    def page(self, ids, total, more):
        links = dict(pages=dict(next='https://evil.example/v2/droplets?page=2')) if more else {}
        return answer(200, dict(droplets=[dict(id=i, name='d', tags=[], status='active') for i in ids], links=links, meta=dict(total=total)))

    def test_follows_every_page_with_targets_it_built_itself(self):
        adapter = provider(self.page([1, 2], 3, True), self.page([3], 3, False))
        self.assertEqual([d['id'] for d in adapter.list_droplets_by_tag('t')], ['1', '2', '3'])
        targets = [c['target'] for c in adapter.transport.calls]
        self.assertEqual(targets[1], '/v2/droplets?tag_name=t&per_page=200&page=2')
        self.assertFalse(any('evil' in t for t in targets))

    def test_a_short_walk_or_missing_total_is_a_failure_not_an_empty_result(self):
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(self.page([1], 2, False)).list_droplets_by_tag('t')
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(droplets=[]))).list_droplets_by_tag('t')
        with self.assertRaises(cleanup_provider.ProviderTransient):
            provider(answer(200, dict(droplets='none', meta=dict(total=0)))).list_droplets_by_tag('t')

    def test_a_listing_error_is_not_empty(self):
        for status in (404, 500, 401):
            with self.assertRaises(cleanup_provider.ProviderError):
                provider(answer(status)).list_droplets_by_tag('t')

    def test_firewalls_have_no_name_filter_so_only_exact_names_return(self):
        walls = [dict(id=UUID, name='s-fw'), dict(id='x', name='s-fw-2')]
        adapter = provider(answer(200, dict(firewalls=walls, links={}, meta=dict(total=2))))
        self.assertEqual([f['id'] for f in adapter.list_firewalls_by_name('s-fw')], [UUID])


class CreateEvidence(unittest.TestCase):
    PAYLOAD = dict(name='x')

    def create(self, *responses):
        adapter, transport = controller(*responses)
        return adapter.create_droplet(self.PAYLOAD, request_bound_s=35.0, send_by=5.0), transport

    def test_2xx_with_an_exact_id_lands(self):
        identifier, transport = self.create(answer(202, dict(droplet=dict(id=77))))
        self.assertEqual(identifier, '77')
        self.assertEqual(transport.calls[0]['bound'], 35.0)
        self.assertEqual(transport.calls[0]['send_by'], 5.0)
        self.assertEqual(len(transport.calls), 1)

    def test_only_listed_refusals_are_rejections(self):
        for status in do_api.DEFINITIVE_CREATE_REFUSALS:
            with self.assertRaises(create_evidence.CreateRejected, msg=status):
                self.create(answer(status, dict(id='refused')))

    def test_everything_else_stays_unknown(self):
        for response in (answer(500), answer(502), answer(503), answer(504), answer(408), answer(409), answer(425), answer(301), answer(202, {}),
                         answer(202, dict(droplet={})), answer(202, dict(droplet=dict(id='nope'))), answer(202, dict(droplet=dict(id=0))),
                         answer(202, dict(droplet=dict(id=True))), do_api.HttpResponse(202, {}, b'<html>'), do_api.RequestOutcomeUnknown('timeout')):
            with self.assertRaises(cleanup_provider.ProviderTransient, msg=str(response)):
                self.create(response)

    def test_only_a_failed_connection_is_not_sent(self):
        with self.assertRaises(create_evidence.CreateNotSent):
            self.create(do_api.RequestNotSent('refused'))

    def test_exact_ids_are_required_for_firewalls_and_tags(self):
        adapter, _ = controller(answer(202, dict(firewall=dict(id='not-a-uuid'))))
        with self.assertRaises(cleanup_provider.ProviderTransient):
            adapter.create_firewall(dict())
        adapter, _ = controller(answer(201, dict(tag=dict(name='different'))))
        with self.assertRaises(cleanup_provider.ProviderTransient):
            adapter.create_tag('wanted')

    def test_no_create_retries_anywhere_in_the_adapter(self):
        adapter, transport = controller(do_api.RequestOutcomeUnknown('x'))
        with self.assertRaises(cleanup_provider.ProviderTransient):
            adapter.create_tag('t')
        self.assertEqual(len(transport.calls), 1)

    def test_assignment_needs_a_confirmed_status_for_this_droplet(self):
        project = 'eb8ab36b-8d7a-4af4-b28b-a66d1b9fe940'
        good, transport = controller(answer(200, dict(resources=[dict(urn='do:droplet:5', status='assigned')])))
        good.assign_droplet(project, '5')
        self.assertEqual(json.loads(transport.calls[0]['body']), dict(resources=['do:droplet:5']))
        for body in (dict(resources=[dict(urn='do:droplet:5', status='service_down')]), dict(resources=[dict(urn='do:droplet:6', status='assigned')]), dict(resources=[])):
            bad, _ = controller(answer(200, body))
            with self.assertRaises(cleanup_provider.ProviderTransient):
                bad.assign_droplet(project, '5')


class Gate(unittest.TestCase):
    def gate(self, wall=None, **packet_changes):
        import provision_fixtures as pf
        manifest, sha = fx.session_manifest(cap_s=14400)
        now = fx.T0_WALL
        packet = pf.authorization(manifest, sha, now, **packet_changes)
        return remote_authorization.MutationGate(packet, manifest, sha, wall or (lambda: now)), manifest

    def droplet(self, manifest, role='game', **changes):
        spec = manifest['roles'][role]
        tags = manifest['session']['ownership_tags']
        payload = dict(name=manifest['session']['id'] + '-' + role, region=spec['region'], size=spec['size_slug'], image=spec['image_id'], ssh_keys=[manifest['ssh_key']['id']],
                       tags=[tags['session'], tags[role]], backups=False, ipv6=False, monitoring=False, with_droplet_agent=False, user_data='#cloud-config\n{}')
        payload.update(changes)
        return payload

    def test_exact_frozen_droplet_passes_and_any_difference_refuses(self):
        gate, manifest = self.gate()
        gate.check('create_droplet', self.droplet(manifest))
        for changes in (dict(size='s-8vcpu-16gb'), dict(region='nyc1'), dict(image=1), dict(ssh_keys=[1]), dict(tags=['x']), dict(backups=True), dict(ipv6=True), dict(monitoring=True),
                        dict(with_droplet_agent=True), dict(name='prod-api'), dict(volumes=['v']), dict(vpc_uuid='x')):
            with self.subTest(changes):
                gate, manifest = self.gate()
                with self.assertRaises(remote_authorization.MutationRefused):
                    gate.check('create_droplet', self.droplet(manifest, **changes))

    def test_counts_are_bounded(self):
        gate, manifest = self.gate()
        gate.check('create_droplet', self.droplet(manifest, 'game'))
        gate.check('create_droplet', self.droplet(manifest, 'bot'))
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('create_droplet', self.droplet(manifest, 'game'))
        tags = manifest['session']['ownership_tags']
        for tag in tags.values():
            gate.check('create_tag', tag)
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('create_tag', tags['game'])

    def test_foreign_targets_are_refused(self):
        gate, manifest = self.gate()
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('create_tag', 'prod')
        for firewall in (dict(name='prod-fw'), dict(name=manifest['session']['id'] + '-fw', tags=['prod']),
                         dict(name=manifest['session']['id'] + '-fw', tags=[], droplet_ids=[1])):
            with self.assertRaises(remote_authorization.MutationRefused):
                gate.check('create_firewall', firewall)
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('assign_droplet', 'another-project', '1')

    def test_the_window_is_checked_at_every_mutation_not_once(self):
        now = [fx.T0_WALL]
        gate, manifest = self.gate(wall=lambda: now[0])
        tag = manifest['session']['ownership_tags']['game']
        gate.check('create_tag', tag)
        now[0] += 7201
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('create_tag', tag)

    def test_updates_and_assignments_need_an_id_the_registry_records(self):
        gate, manifest = self.gate()
        firewall = session_access.firewall_request(manifest, ['198.51.100.7/32'], [])
        project = manifest['session']['project_id']
        for action, details in (('update_firewall', (UUID, firewall)), ('assign_droplet', (project, '5'))):
            with self.subTest(action), self.assertRaises(remote_authorization.MutationRefused):
                gate.check(action, *details)
        recorded = [dict(kind='firewall', provider_id=UUID, resource_key='firewall:' + UUID), dict(kind='droplet', provider_id='5', resource_key='droplet:5')]
        gate.bind_owned(recorded)
        gate.check('update_firewall', UUID, firewall)
        gate.check('assign_droplet', project, '5')
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('update_firewall', '00000009-0000-4000-8000-000000000000', firewall)
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('assign_droplet', project, '6')
        # The latest record is the whole authority: what it no longer names can no longer be changed.
        gate.bind_owned(recorded[1:])
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('update_firewall', UUID, firewall)

    def test_a_retained_id_gets_no_authority_even_when_recorded(self):
        import provision_fixtures as pf
        manifest, sha = fx.session_manifest(cap_s=14400, retained=['droplet:5'])
        gate = remote_authorization.MutationGate(pf.authorization(manifest, sha, fx.T0_WALL), manifest, sha, lambda: fx.T0_WALL)
        gate.bind_owned([dict(kind='droplet', provider_id='5', resource_key='droplet:5')])
        with self.assertRaises(remote_authorization.MutationRefused):
            gate.check('assign_droplet', manifest['session']['project_id'], '5')

    def test_the_send_guard_reports_the_window_and_refuses_after_it_without_spending(self):
        now = [fx.T0_WALL]
        gate, manifest = self.gate(wall=lambda: now[0], not_after_utc=session_clock.iso(fx.T0_WALL + 10))
        guard = gate.send_guard('create_tag')
        self.assertAlmostEqual(guard.seconds_left(), 10.0)
        guard.confirm()
        self.assertEqual(gate.counts, {})
        now[0] += 10
        self.assertLessEqual(guard.seconds_left(), 0)
        with self.assertRaises(remote_authorization.MutationRefused):
            guard.confirm()

    def test_a_refusal_counts_as_not_sent(self):
        self.assertTrue(issubclass(remote_authorization.MutationRefused, create_evidence.CreateNotSent))

    def test_validation_rejects_unknown_fields_and_credential_values(self):
        import provision_fixtures as pf
        manifest, sha = fx.session_manifest(cap_s=14400)
        packet = pf.authorization(manifest, sha, fx.T0_WALL)
        self.assertEqual(remote_authorization.validate(packet, manifest, sha, fx.T0_WALL), [])
        self.assertTrue(remote_authorization.validate(dict(packet, extra=1), manifest, sha, fx.T0_WALL))
        leaked = dict(packet, operator_request_ref='dop_v1_' + 'a' * 64)
        reasons = remote_authorization.validate(leaked, manifest, sha, fx.T0_WALL)
        self.assertIn('credential value', reasons[0])
        self.assertNotIn('dop_v1_', ''.join(reasons))
        self.assertTrue(remote_authorization.validate(dict(packet, schema='x'), manifest, sha, fx.T0_WALL))
        self.assertTrue(remote_authorization.validate(None, manifest, sha, fx.T0_WALL))


class TokenFile(unittest.TestCase):
    def path(self, text, mode=0o600):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = pathlib.Path(directory.name) / 'token'
        path.write_text(text)
        os.chmod(str(path), mode)
        return path

    def test_restricted_single_value_is_accepted(self):
        self.assertEqual(do_api.load_token(self.path('offline-fixture-value\n')), 'offline-fixture-value')

    def test_loose_mode_empty_or_multiple_values_refuse_without_echo(self):
        for text, mode in (('secret-value', 0o640), ('secret-value', 0o644), ('', 0o600), ('secret-value extra', 0o600)):
            with self.assertRaises(ValueError) as raised:
                do_api.load_token(self.path(text, mode))
            self.assertNotIn('secret-value', str(raised.exception))

    def test_directory_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, 0o700)
            with self.assertRaises(ValueError):
                do_api.load_token(directory)

    def test_watchdog_factory_builds_the_read_delete_adapter_without_any_network(self):
        adapter = do_api.from_token_file(self.path('offline-fixture-value'))
        self.assertIs(type(adapter), do_api.DigitalOceanProvider)
        self.assertFalse(adapter.offline_fixture)
        loaded = registry_cli.load_provider('do_api:from_token_file', str(self.path('offline-fixture-value')))
        self.assertFalse(getattr(loaded, 'offline_fixture'))

    def test_the_fake_account_is_refused_as_a_real_watchdog_provider(self):
        import unittest.mock
        module = type('M', (), dict(factory=staticmethod(lambda: do_api.DigitalOceanProvider(fake_do_http.FakeDoAccount(fx.ScriptedClock())))))
        with unittest.mock.patch('importlib.import_module', return_value=module):
            with self.assertRaises(ValueError):
                registry_cli.load_provider('m:factory', None)


class LoopbackServer:
    """A one-shot TCP endpoint: lets the transport's real socket path run with no network and no TLS."""

    def __init__(self, handler):
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.socket.listen(8)
        self.port = self.socket.getsockname()[1]
        self.accepted = 0
        self.requests = []
        self.handler = handler
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            self.accepted += 1
            connection.settimeout(2)
            try:
                self.requests.append(connection.recv(65536))
                self.handler(connection)
            except OSError:
                pass
            finally:
                connection.close()

    def close(self):
        self.socket.close()


class Transport(unittest.TestCase):
    def transport(self, server=None, port=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = pathlib.Path(directory.name) / 'token'
        path.write_text('offline-fixture-token')
        os.chmod(str(path), 0o600)
        target = port if port is not None else server.port
        return do_api.HttpsTransport(path, host='127.0.0.1', connection_factory=lambda host, timeout: http.client.HTTPConnection(host, target, timeout=timeout))

    def serve(self, handler):
        server = LoopbackServer(handler)
        self.addCleanup(server.close)
        return server

    def test_one_request_one_answer_and_the_token_travels_only_in_its_header(self):
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nRatelimit-Reset: 5\r\n\r\n{}'))
        response = self.transport(server)('GET', '/v2/droplets/1')
        self.assertEqual((response.status, response.body, response.headers['ratelimit-reset']), (200, b'{}', '5'))
        request = server.requests[0].decode()
        self.assertEqual(server.accepted, 1)
        self.assertIn('Authorization: Bearer offline-fixture-token', request)

    def test_server_error_is_returned_and_never_retried(self):
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 503 Busy\r\nContent-Length: 0\r\n\r\n'))
        response = self.transport(server)('POST', '/v2/droplets', body=b'{}')
        self.assertEqual(response.status, 503)
        time.sleep(0.05)
        self.assertEqual(server.accepted, 1)

    def test_redirects_are_not_followed(self):
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 302 Found\r\nLocation: http://evil.example/\r\nContent-Length: 0\r\n\r\n'))
        response = self.transport(server)('POST', '/v2/droplets', body=b'{}')
        self.assertEqual(response.status, 302)
        self.assertEqual(server.accepted, 1)

    def test_a_connection_that_never_opens_is_not_sent(self):
        unused = socket.socket()
        unused.bind(('127.0.0.1', 0))
        port = unused.getsockname()[1]
        unused.close()
        with self.assertRaises(do_api.RequestNotSent):
            self.transport(port=port)('POST', '/v2/droplets', body=b'{}')

    def test_a_closed_send_window_sends_nothing(self):
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n'))
        transport = self.transport(server)
        with self.assertRaises(do_api.RequestNotSent):
            transport('POST', '/v2/droplets', body=b'{}', send_by=session_clock.suspend_aware_monotonic() - 1)
        self.assertEqual(server.accepted, 0)

    def test_connection_dropped_after_the_request_is_unknown(self):
        server = self.serve(lambda c: None)
        with self.assertRaises(do_api.RequestOutcomeUnknown):
            self.transport(server)('POST', '/v2/droplets', body=b'{}')
        self.assertEqual(server.accepted, 1)

    def test_the_bound_is_absolute_even_for_a_trickling_response(self):
        def trickle(connection):
            connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n')
            for _ in range(40):
                try:
                    connection.sendall(b'x')
                except OSError:
                    return
                time.sleep(0.05)

        server = self.serve(trickle)
        started = time.monotonic()
        with self.assertRaises(do_api.RequestOutcomeUnknown):
            self.transport(server)('POST', '/v2/droplets', body=b'{}', request_bound_s=0.4)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_the_default_connection_verifies_tls_and_connects_only_on_request(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = pathlib.Path(directory.name) / 'token'
        path.write_text('offline-fixture-token')
        os.chmod(str(path), 0o600)
        connection = do_api.HttpsTransport(path).connection_factory(do_api.API_HOST, 1.0)
        self.assertIsInstance(connection, http.client.HTTPSConnection)
        self.assertIsNone(connection.sock)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(connection._context.check_hostname)

    def test_the_transport_uses_no_library_that_retries_or_follows_redirects(self):
        source = pathlib.Path(do_api.__file__).read_text()
        for helper in ('import requests', 'import urllib.request', 'import urllib3', 'HTTPAdapter'):
            self.assertNotIn(helper, source)


class StalledConnect:
    """A connection whose connect blocks until released, as a stuck system resolver would. Offline by construction."""

    def __init__(self, release=None):
        self.release = release or threading.Event()
        self.closed = threading.Event()
        self.sock = None

    def connect(self):
        self.release.wait(20)

    def close(self):
        self.closed.set()


class CountingGuard:
    def __init__(self, seconds_left=100.0, confirm_raises=None):
        self.left = seconds_left
        self.confirm_raises = confirm_raises
        self.confirmed = 0

    def seconds_left(self):
        return self.left

    def confirm(self):
        self.confirmed += 1
        if self.confirm_raises is not None:
            raise self.confirm_raises


class TransportBounds(unittest.TestCase):
    """The whole request, from the resolver on, stays inside one bound. Loopback sockets and stubs only."""

    SLACK_S = 0.5

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.token = pathlib.Path(directory.name) / 'token'
        self.token.write_text('offline-fixture-token')
        os.chmod(str(self.token), 0o600)

    def serve(self, handler):
        server = LoopbackServer(handler)
        self.addCleanup(server.close)
        return server

    def stall_resolver(self):
        """Every name lookup blocks until the returned event is set, then answers with loopback."""
        release = threading.Event()
        real = socket.getaddrinfo

        def stalled(host, port, *rest, **options):
            release.wait(20)
            return real('127.0.0.1', port, *rest, **options)
        patcher = unittest.mock.patch('socket.getaddrinfo', side_effect=stalled)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(release.set)
        return release

    def assert_bounded(self, call, bound_s, error=do_api.RequestNotSent):
        started = time.monotonic()
        with self.assertRaises(error):
            call()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, bound_s + self.SLACK_S)
        return elapsed

    def connect_workers(self):
        return [t for t in threading.enumerate() if t.name == 'omega-do-connect']

    def await_no_workers(self, baseline=0):
        deadline = time.monotonic() + 5
        while len(self.connect_workers()) > baseline and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertLessEqual(len(self.connect_workers()), baseline)

    def test_a_stalled_resolver_cannot_outlast_the_bound_on_the_default_connection(self):
        self.stall_resolver()
        transport = do_api.HttpsTransport(self.token)
        elapsed = self.assert_bounded(lambda: transport('GET', '/v2/account', request_bound_s=0.05), 0.05)
        self.assertGreaterEqual(elapsed, 0.04)

    def test_a_grant_send_deadline_bounds_connecting_tighter_than_the_request_bound(self):
        self.stall_resolver()
        transport = do_api.HttpsTransport(self.token)
        send_by = session_clock.suspend_aware_monotonic() + 0.05
        self.assert_bounded(lambda: transport('POST', '/v2/droplets', body=b'{}', request_bound_s=5.0, send_by=send_by), 0.05)

    def test_addresses_that_never_answer_share_one_bound(self):
        attempts = []
        real_socket = socket.socket

        class Unanswered(real_socket):
            def connect(self, address):
                attempts.append(address)
                time.sleep(0.2)
                raise socket.timeout('stub: no answer')

        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.%d' % i, 443)) for i in (1, 2, 3)]
        with unittest.mock.patch('socket.getaddrinfo', return_value=addresses), unittest.mock.patch('socket.socket', Unanswered):
            transport = do_api.HttpsTransport(self.token)
            self.assert_bounded(lambda: transport('GET', '/v2/account', request_bound_s=0.05), 0.05)
            # Past the caller's return the worker walks the remaining addresses, finds nothing, and frees its slot.
            self.await_no_workers()
        self.assertEqual(len(attempts), 3)

    def test_a_tls_handshake_that_stalls_or_trickles_is_bounded_and_sends_no_request(self):
        def silent(connection):
            time.sleep(0.5)

        def trickle(connection):
            connection.sendall(b'\x16\x03\x03\x10\x00')     # a TLS record header promising more than ever comes
            for _ in range(40):
                try:
                    connection.sendall(b'\x00')
                except OSError:
                    return
                time.sleep(0.05)

        for handler in (silent, trickle):
            with self.subTest(handler.__name__):
                server = self.serve(handler)
                transport = do_api.HttpsTransport(
                    self.token, host='127.0.0.1',
                    connection_factory=lambda host, timeout: http.client.HTTPSConnection(host, server.port, timeout=timeout, context=ssl.create_default_context()))
                self.assert_bounded(lambda: transport('POST', '/v2/droplets', body=b'{}', request_bound_s=0.2), 0.2)
                self.assertEqual(server.accepted, 1)
                self.assertFalse(any(b'POST' in r or b'offline-fixture-token' in r for r in server.requests))

    def test_a_response_trickling_its_headers_is_bounded_and_stays_unknown(self):
        def trickle(connection):
            connection.sendall(b'HTTP/1.1 200 OK\r\n')
            for index in range(40):
                try:
                    connection.sendall(b'X-Slow-%d: y\r\n' % index)
                except OSError:
                    return
                time.sleep(0.05)

        server = self.serve(trickle)
        transport = do_api.HttpsTransport(self.token, host='127.0.0.1', connection_factory=lambda host, timeout: http.client.HTTPConnection(host, server.port, timeout=timeout))
        self.assert_bounded(lambda: transport('POST', '/v2/droplets', body=b'{}', request_bound_s=0.2), 0.2, do_api.RequestOutcomeUnknown)

    def test_repeated_stalls_hold_a_bounded_number_of_workers_and_recover_without_a_late_request(self):
        release = self.stall_resolver()
        baseline = len(self.connect_workers())
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}'))
        transport = do_api.HttpsTransport(self.token, host='127.0.0.1', max_connect_workers=3,
                                          connection_factory=lambda host, timeout: http.client.HTTPConnection(host, server.port, timeout=timeout))
        most = 0
        for _ in range(12):
            self.assert_bounded(lambda: transport('POST', '/v2/droplets', body=b'{}', request_bound_s=0.02), 0.02)
            most = max(most, len(self.connect_workers()) - baseline)
        self.assertLessEqual(most, 3)
        self.assertEqual(most, 3)
        # Full: this one is refused at once, without waiting out its bound.
        started = time.monotonic()
        with self.assertRaises(do_api.RequestNotSent):
            transport('GET', '/v2/account', request_bound_s=5.0)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(server.accepted, 0)
        release.set()
        self.await_no_workers(baseline)
        # Each abandoned worker did connect once released. Each closed without a request byte.
        deadline = time.monotonic() + 2
        while server.accepted < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(server.accepted, 3)
        self.assertEqual([r for r in server.requests if r], [])
        # And the slots came back: the transport works again.
        self.assertEqual(transport('GET', '/v2/account', request_bound_s=2.0).status, 200)
        self.assertEqual(len([r for r in server.requests if b'offline-fixture-token' in r]), 1)

    def test_a_worker_that_finishes_after_the_caller_left_closes_what_it_opened(self):
        stalled = StalledConnect()
        transport = do_api.HttpsTransport(self.token, connection_factory=lambda host, timeout: stalled)
        self.assert_bounded(lambda: transport('GET', '/v2/account', request_bound_s=0.02), 0.02)
        self.assertFalse(stalled.closed.is_set())
        stalled.release.set()
        self.assertTrue(stalled.closed.wait(2))

    def test_authorization_expiring_while_connecting_bounds_the_wait_and_sends_nothing(self):
        stalled = StalledConnect()
        self.addCleanup(stalled.release.set)
        transport = do_api.HttpsTransport(self.token, connection_factory=lambda host, timeout: stalled)
        guard = CountingGuard(seconds_left=0.05)
        self.assert_bounded(lambda: transport('POST', '/v2/droplets', body=b'{}', request_bound_s=5.0, send_guard=guard), 0.05)
        self.assertEqual(guard.confirmed, 0)

    def test_an_authorization_already_over_opens_no_connection(self):
        opened = []
        transport = do_api.HttpsTransport(self.token, connection_factory=lambda host, timeout: opened.append(host))
        with self.assertRaises(do_api.RequestNotSent):
            transport('POST', '/v2/droplets', body=b'{}', send_guard=CountingGuard(seconds_left=0))
        self.assertEqual(opened, [])

    def test_the_last_check_runs_after_connecting_and_its_refusal_sends_no_byte(self):
        server = self.serve(lambda c: c.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n'))
        transport = do_api.HttpsTransport(self.token, host='127.0.0.1', connection_factory=lambda host, timeout: http.client.HTTPConnection(host, server.port, timeout=timeout))
        refusal = remote_authorization.MutationRefused('authorization ended while connecting')
        guard = CountingGuard(confirm_raises=refusal)
        with self.assertRaises(remote_authorization.MutationRefused):
            transport('POST', '/v2/droplets', body=b'{}', send_guard=guard)
        self.assertEqual(guard.confirmed, 1)
        deadline = time.monotonic() + 2
        while server.accepted < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual([r for r in server.requests if r], [])

    def test_a_connection_failure_is_closed_reported_and_not_sent(self):
        unused = socket.socket()
        unused.bind(('127.0.0.1', 0))
        port = unused.getsockname()[1]
        unused.close()
        transport = do_api.HttpsTransport(self.token, host='127.0.0.1', connection_factory=lambda host, timeout: http.client.HTTPConnection(host, port, timeout=timeout))
        with self.assertRaises(do_api.RequestNotSent) as raised:
            transport('POST', '/v2/droplets', body=b'{}')
        self.assertIn('Refused', str(raised.exception))


class NoLiveAccess(unittest.TestCase):
    def test_the_fake_account_is_marked_offline_and_needs_no_credential(self):
        account = fake_do_http.FakeDoAccount(fx.ScriptedClock())
        self.assertTrue(account.offline_fixture)
        self.assertTrue(do_api.DigitalOceanProvider(account).offline_fixture)

    def test_fake_account_keeps_bodies_out_of_its_request_log(self):
        account = fake_do_http.FakeDoAccount(fx.ScriptedClock())
        account('POST', '/v2/tags', body=json.dumps(dict(name='x')).encode())
        self.assertNotIn('body', account.requests[0])
        self.assertEqual(manifest_mod.scan_for_secrets(account.requests), [])


if __name__ == '__main__':
    unittest.main()
