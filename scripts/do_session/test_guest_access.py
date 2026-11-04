"""Exact firewall rules, secret-free bootstrap, pinned SSH, readiness rules and the guest agent's parsers."""
import base64
import copy
import json
import os
import pathlib
import shlex
import socket
import subprocess
import tempfile
import threading
import types
import unittest
import unittest.mock

import fake_do_http
import fake_guest
import fixture_support as fx
import guest_agent
import guest_bootstrap
import manifest as manifest_mod
import provider_preflight
import readiness
import session_access
import ssh_access

MANIFEST, SHA = fx.session_manifest(cap_s=14400)
PUBLIC_KEY = fake_do_http.PUBLIC_KEY_PATH.read_text().strip()
NONCE = 'fixture-nonce-0123456789abcdef'


class FirewallRules(unittest.TestCase):
    def desired(self, ssh=('203.0.113.10/32',), udp=('203.0.113.10/32',), bot='198.51.100.7'):
        return session_access.firewall_request(MANIFEST, list(ssh), list(udp), bot)

    def test_ingress_is_exactly_ssh_and_game_udp_from_exact_hosts(self):
        rules = {r['ports']: r for r in self.desired()['inbound_rules']}
        self.assertEqual(sorted(rules), ['22', '8081'])
        self.assertEqual(rules['22']['protocol'], 'tcp')
        self.assertEqual(rules['22']['sources']['addresses'], ['203.0.113.10/32'])
        self.assertEqual(rules['8081']['protocol'], 'udp')
        self.assertEqual(rules['8081']['sources']['addresses'], ['198.51.100.7/32', '203.0.113.10/32'])

    def test_metrics_has_no_rule_at_all(self):
        text = json.dumps(self.desired())
        self.assertNotIn(session_access.METRICS_PORT, text)

    def test_no_broad_ingress_can_be_rendered(self):
        for bad in ('0.0.0.0/0', '::/0', '203.0.113.0/24', '2001:db8::/32', '10.0.0.1/32', '192.168.1.2/32', '172.16.0.9/32', '100.64.0.1/32',
                    '127.0.0.1/32', '169.254.169.254/32', '224.0.0.1/32', '240.0.0.1/32', 'fd00::1/128', '203.0.113.1/24', 'operator', ''):
            with self.assertRaises(session_access.AccessRefused, msg=bad):
                self.desired(ssh=(bad,))
            with self.assertRaises(session_access.AccessRefused, msg=bad):
                self.desired(udp=(bad,))

    def test_egress_is_open_because_the_provider_denies_what_has_no_rule(self):
        protocols = {r['protocol'] for r in self.desired()['outbound_rules']}
        self.assertEqual(protocols, {'tcp', 'udp', 'icmp'})

    def test_an_empty_ssh_list_is_refused_and_empty_udp_omits_the_rule(self):
        with self.assertRaises(session_access.AccessRefused):
            session_access.firewall_request(MANIFEST, [], [], None)
        request = session_access.firewall_request(MANIFEST, ['203.0.113.10/32'], [], None)
        self.assertEqual([r['ports'] for r in request['inbound_rules']], ['22'])

    def test_read_back_comparison_catches_any_difference(self):
        desired = self.desired()
        self.assertEqual(session_access.firewall_problems(copy.deepcopy(desired), desired), [])
        changes = dict(name='other-fw', tags=['prod'], droplet_ids=[9],
                       inbound_rules=desired['inbound_rules'] + [dict(protocol='tcp', ports='9100', sources=dict(addresses=['0.0.0.0/0']))],
                       outbound_rules=[])
        for field, value in changes.items():
            self.assertTrue(session_access.firewall_problems(dict(desired, **{field: value}), desired), field)
        wider = copy.deepcopy(desired)
        wider['inbound_rules'][0]['sources']['addresses'] = ['0.0.0.0/0']
        self.assertTrue(session_access.firewall_problems(wider, desired))
        denied = copy.deepcopy(desired)
        denied['inbound_rules'][0]['action'] = 'deny'
        self.assertTrue(session_access.firewall_problems(denied, desired))
        source_tag = copy.deepcopy(desired)
        source_tag['inbound_rules'][0]['sources']['tags'] = ['prod']
        self.assertTrue(session_access.firewall_problems(source_tag, desired))

    def test_read_back_tolerates_only_provider_spelling_differences(self):
        desired = self.desired()
        spelled = copy.deepcopy(desired)
        spelled['inbound_rules'][0]['sources']['addresses'] = ['203.0.113.10']
        for rule in spelled['outbound_rules']:
            if rule['protocol'] == 'icmp':
                rule['ports'] = '0'
            else:
                rule['ports'] = '0'
        self.assertEqual(session_access.firewall_problems(spelled, desired), [])

    def test_only_a_completed_status_counts_as_applied(self):
        self.assertEqual(session_access.applied_problems(dict(status='succeeded', pending_changes=[])), [])
        self.assertTrue(session_access.applied_problems(dict(status='waiting', pending_changes=[])))
        self.assertTrue(session_access.applied_problems(dict(status='succeeded', pending_changes=[dict(droplet_id=1)])))
        self.assertTrue(session_access.applied_problems({}))


class UserData(unittest.TestCase):
    def rendered(self, role='game'):
        text = guest_bootstrap.render_user_data(MANIFEST, role, PUBLIC_KEY, NONCE)
        self.assertTrue(text.startswith('#cloud-config\n'))
        return text, json.loads(text.split('\n', 1)[1])

    def test_key_only_access_and_nothing_private(self):
        text, config = self.rendered()
        self.assertIs(config['ssh_pwauth'], False)
        self.assertIs(config['disable_root'], True)
        self.assertEqual(config['users'][0]['ssh_authorized_keys'], [PUBLIC_KEY])
        self.assertIs(config['users'][0]['lock_passwd'], True)
        self.assertNotIn('PRIVATE KEY', text)
        self.assertEqual(manifest_mod.scan_for_secrets(text), [])
        policy = next(f for f in config['write_files'] if 'sshd_config.d' in f['path'])['content']
        self.assertIn('PasswordAuthentication no', policy)
        self.assertIn('PermitRootLogin no', policy)

    def test_only_the_builder_gets_compilers(self):
        _, game = self.rendered('game')
        _, bot = self.rendered('bot')
        self.assertNotIn('build-essential', game['packages'])
        self.assertNotIn('git', game['packages'])
        self.assertIn('build-essential', bot['packages'])

    def test_no_operator_address_token_reference_or_config_path(self):
        for role in ('game', 'bot'):
            text, _ = self.rendered(role)
            self.assertNotIn('203.0.113.10', text)
            self.assertNotIn('controller.token', text)
            self.assertNotIn('omega_loadtest_ed25519', text.replace('omega-loadtest-2026-10', ''))
            self.assertLess(len(text.encode()), guest_bootstrap.MAX_USER_DATA_BYTES)

    def test_refusals(self):
        for key, reason in (('ssh-rsa AAAA x', 'Ed25519'), ('not a key', 'Ed25519')):
            with self.assertRaisesRegex(guest_bootstrap.BootstrapRefused, reason):
                guest_bootstrap.render_user_data(MANIFEST, 'game', key, NONCE)
        other = 'ssh-ed25519 ' + base64.b64encode(b'other').decode() + ' x'
        with self.assertRaisesRegex(guest_bootstrap.BootstrapRefused, 'fingerprint'):
            guest_bootstrap.render_user_data(MANIFEST, 'game', other, NONCE)
        for secret in ('dop_v1_' + 'a' * 64, '-----BEGIN OPENSSH PRIVATE KEY-----'):
            with self.assertRaisesRegex(guest_bootstrap.BootstrapRefused, 'credential'):
                guest_bootstrap.render_user_data(MANIFEST, 'game', PUBLIC_KEY, secret)
        with self.assertRaisesRegex(guest_bootstrap.BootstrapRefused, '64 KiB'):
            guest_bootstrap.render_user_data(MANIFEST, 'game', PUBLIC_KEY, 'x' * (guest_bootstrap.MAX_USER_DATA_BYTES + 1))
        with self.assertRaisesRegex(guest_bootstrap.BootstrapRefused, 'operator address'):
            guest_bootstrap.render_user_data(MANIFEST, 'game', PUBLIC_KEY, '203.0.113.10')

    def test_the_tracked_public_key_has_the_registered_fingerprint(self):
        self.assertEqual(provider_preflight.ssh_fingerprint(PUBLIC_KEY), MANIFEST['ssh_key']['fingerprint_sha256'])

    def test_binding_script_deletes_the_nonce_and_publishes_only_the_hmac(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            key = root / 'host.pub'
            key.write_text('ssh-ed25519 ' + fake_guest.HOST_KEY_BLOBS['game'] + ' root@x\n')
            nonce, published = root / 'nonce', root / 'binding.json'
            nonce.write_text(NONCE + '\n')
            script = guest_bootstrap.BINDING_SCRIPT.replace(guest_bootstrap.HOST_KEY_PATH, str(key)).replace(guest_bootstrap.NONCE_PATH, str(nonce)).replace(guest_bootstrap.BINDING_PATH, str(published))
            subprocess.run(['python3', '-I', '-c', script], check=True)
            self.assertFalse(nonce.exists())
            document = published.read_text()
            self.assertNotIn(NONCE, document)
            self.assertTrue(ssh_access.binding_matches(NONCE, fake_guest.HOST_KEY_BLOBS['game'], document))


class HostPinning(unittest.TestCase):
    class Guests(ssh_access.GuestAccess):
        def __init__(self, offered, document):
            super().__init__()
            self.offered, self.document, self.pinned = offered, document, []

        def _scan_host_key(self, address):
            return self.offered

        def _read_binding(self, role, address, host_key):
            return self.document

        def _pin(self, role, address, host_key):
            self.pinned.append((role, address, host_key))

    BLOB = base64.b64encode(b'a-host-key').decode()

    def binding(self, nonce=NONCE, blob=BLOB, algorithm='hmac-sha256'):
        return json.dumps(dict(algorithm=algorithm, hmac=ssh_access.expected_binding(nonce, blob)))

    def test_matching_binding_pins_exactly_that_key(self):
        guests = self.Guests(('ssh-ed25519', self.BLOB), self.binding())
        pin = guests.pin_host('game', '198.51.100.7', NONCE)
        self.assertEqual(guests.pinned, [('game', '198.51.100.7', ('ssh-ed25519', self.BLOB))])
        self.assertTrue(pin['host_key_sha256'].startswith('SHA256:'))
        self.assertNotIn(NONCE, json.dumps(pin))

    def test_a_proof_for_another_nonce_or_key_is_refused(self):
        for document in (self.binding(nonce='another'), self.binding(blob='other-key'), self.binding(algorithm='md5'), 'not json', '[]', '{"hmac": 1}', '{}'):
            guests = self.Guests(('ssh-ed25519', self.BLOB), document)
            with self.assertRaises(ssh_access.HostVerificationFailed, msg=document):
                guests.pin_host('game', '198.51.100.7', NONCE)
            self.assertEqual(guests.pinned, [])

    def test_a_weaker_key_type_is_refused_and_silence_is_only_not_ready(self):
        with self.assertRaises(ssh_access.HostVerificationFailed):
            self.Guests(('ssh-rsa', self.BLOB), self.binding()).pin_host('game', 'a', NONCE)
        with self.assertRaises(ssh_access.HostNotReady):
            self.Guests(None, None).pin_host('game', 'a', NONCE)
        with self.assertRaises(ssh_access.HostNotReady):
            self.Guests(('ssh-ed25519', self.BLOB), None).pin_host('game', 'a', NONCE)


class FakeProcess:
    def __init__(self, stdout=b'', stderr=b'', returncode=0, polls=0):
        self.stdout_bytes, self.stderr_bytes, self.final = stdout, stderr, returncode
        self.remaining = polls
        self.returncode = None
        self.killed = False

    def poll(self):
        if self.killed or self.remaining <= 0:
            self.returncode = -9 if self.killed else self.final
            return self.returncode
        self.remaining -= 1
        return None

    def kill(self):
        self.killed = True

    def communicate(self):
        return self.stdout_bytes, self.stderr_bytes


class SshCommands(unittest.TestCase):
    def access(self, processes):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        key = pathlib.Path(directory.name) / 'key'
        key.write_text('fixture, never read')
        os.chmod(str(key), 0o600)
        self.calls = []

        def popen(argv, **kwargs):
            self.calls.append(argv)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertNotIn('shell', kwargs)
            return processes.pop(0)
        self.clock = [0.0]

        def sleep(seconds):
            self.clock[0] += seconds
        return ssh_access.SshAccess(key, pathlib.Path(directory.name) / 'ssh', popen=popen, sleep=sleep, monotonic=lambda: self.clock[0])

    def test_options_forbid_every_weaker_path(self):
        options = ' '.join(self.access([]).options())
        for required in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no', 'IdentitiesOnly=yes',
                         'IdentityAgent=none', 'ForwardAgent=no', 'UpdateHostKeys=no', 'GlobalKnownHostsFile=/dev/null', 'HostKeyAlgorithms=ssh-ed25519', 'ClearAllForwardings=yes'):
            self.assertIn(required, options)
        for forbidden in ('accept-new', 'StrictHostKeyChecking=no', 'UserKnownHostsFile=/dev/null', 'ForwardAgent=yes'):
            self.assertNotIn(forbidden, options)

    def test_the_module_never_spells_a_weaker_host_policy(self):
        source = pathlib.Path(ssh_access.__file__).read_text()
        self.assertNotIn('=accept-new', source)
        self.assertNotIn('StrictHostKeyChecking=no', source)

    def test_first_contact_requires_the_candidate_key_then_pins_it(self):
        blob = base64.b64encode(b'key').decode()
        address = '198.51.100.7'
        scan = FakeProcess(stdout=('%s ssh-ed25519 %s\n' % (address, blob)).encode())
        read = FakeProcess(stdout=json.dumps(dict(algorithm='hmac-sha256', hmac=ssh_access.expected_binding(NONCE, blob))).encode())
        access = self.access([scan, read])
        pin = access.pin_host('game', address, NONCE)
        self.assertEqual(self.calls[0][:6], ['ssh-keyscan', '-T', '10', '-t', 'ed25519', address])
        read_argv = ' '.join(self.calls[1])
        self.assertIn('known_hosts.game.candidate', read_argv)
        self.assertIn('StrictHostKeyChecking=yes', read_argv)
        self.assertEqual(access.known_hosts.read_text(), '%s ssh-ed25519 %s\n' % (address, blob))
        self.assertEqual(os.stat(str(access.known_hosts)).st_mode & 0o077, 0)
        self.assertFalse((access.session_dir / 'known_hosts.game.candidate').exists())
        self.assertEqual(pin['address'], address)

    def test_failed_binding_pins_nothing(self):
        blob = base64.b64encode(b'key').decode()
        scan = FakeProcess(stdout=('1.2.3.4 ssh-ed25519 %s\n' % blob).encode())
        read = FakeProcess(stdout=b'{"algorithm": "hmac-sha256", "hmac": "00"}')
        access = self.access([scan, read])
        with self.assertRaises(ssh_access.HostVerificationFailed):
            access.pin_host('game', '1.2.3.4', NONCE)
        self.assertFalse(access.known_hosts.exists())

    def test_a_command_before_pinning_is_refused(self):
        with self.assertRaises(ssh_access.GuestCommandFailed):
            self.access([]).run('game', ['true'], 5)

    def test_remote_arguments_are_quoted_and_output_is_bounded_by_the_timeout(self):
        access = self.access([FakeProcess(stdout=b'{}')])
        access.pins['game'] = '1.2.3.4'
        access.run('game', ['echo', 'a b; rm -rf /'], 5)
        self.assertEqual(shlex.split(self.calls[0][-1]), ['echo', 'a b; rm -rf /'])
        access = self.access([FakeProcess(polls=100)])
        access.pins['game'] = '1.2.3.4'
        waits = []
        result = access.run('game', ['sleep', '100'], 3, on_wait=lambda: waits.append(1))
        self.assertIsNone(result.returncode)
        self.assertEqual(len(waits), 3)

    def test_private_key_contents_are_never_opened(self):
        access = self.access([])
        with unittest.mock.patch('builtins.open', side_effect=AssertionError('opened')):
            ssh_access.require_restricted_key(access.private_key_path)

    def test_a_loose_private_key_is_refused(self):
        access = self.access([])
        os.chmod(access.private_key_path, 0o644)
        with self.assertRaises(ValueError):
            ssh_access.require_restricted_key(access.private_key_path)

    def test_a_raising_wait_kills_the_local_process(self):
        process = FakeProcess(polls=100)
        access = self.access([process])
        access.pins['game'] = '1.2.3.4'

        def lease_lost():
            raise KeyError('lease')
        with self.assertRaises(KeyError):
            access.run('game', ['sleep', '100'], 30, on_wait=lease_lost)
        self.assertTrue(process.killed)

    def test_stderr_is_redacted(self):
        access = self.access([FakeProcess(stderr=b'Authorization: Bearer ' + b'a' * 40, returncode=1)])
        access.pins['game'] = '1.2.3.4'
        self.assertNotIn('a' * 40, access.run('game', ['x'], 5).stderr)


class Readiness(unittest.TestCase):
    def healthy(self, role='game'):
        sim = types.SimpleNamespace(manifest=MANIFEST, account=types.SimpleNamespace(), clock=fx.ScriptedClock())
        return fake_guest.FakeGuests(sim)._answer_probe(role), fake_guest.FakeGuests(sim)

    def test_healthy_observations_pass(self):
        for role in ('game', 'bot'):
            observation, _ = self.healthy(role)
            self.assertEqual(readiness.observation_problems(MANIFEST, role, observation, '24.04 (LTS) x64'), [])

    def test_every_missing_prerequisite_is_rejected(self):
        expected = dict(role='role', cloud_init='cloud_init_done', architecture='architecture', os='os_image', kernel='kernel', packages='packages', cpu='cpu_count',
                        memory='memory', disk='disk', nofile='nofile_soft', sshd='sshd_readable', authorized_keys='authorized_key', listeners='listeners_read',
                        clock='clock_synchronized', secrets='guest_secret_scan', release='binary_hash')
        healthy, _ = self.healthy()
        for field in healthy:
            if field in ('schema', 'network'):
                continue
            self.assertIn(field, expected, 'a new observation field needs a rejection check')
            damaged = copy.deepcopy(healthy)
            del damaged[field]
            problems = readiness.observation_problems(MANIFEST, 'game', damaged, '24.04 (LTS) x64')
            self.assertTrue(any(expected[field] in p for p in problems), field)

    def test_empty_or_non_object_observation_rejects(self):
        self.assertTrue(readiness.observation_problems(MANIFEST, 'game', {}, 'x'))
        self.assertTrue(readiness.observation_problems(MANIFEST, 'game', None, 'x'))

    def test_each_wrong_fact_is_rejected(self):
        spec = MANIFEST['roles']['game']
        cases = dict(
            cloud_init_done=lambda o: o['cloud_init'].update(status='running'), cloud_init_rc=lambda o: o['cloud_init'].update(rc=2),
            cloud_init_errors=lambda o: o['cloud_init'].update(errors=['x']), recoverable=lambda o: o['cloud_init'].update(recoverable_errors=dict(WARNING=['x'])),
            cloud_init_boot_finished=lambda o: o['cloud_init'].update(boot_finished=False), architecture=lambda o: o.update(architecture='aarch64'),
            os_image=lambda o: o['os'].update(version_id='22.04'), cpu_count=lambda o: o['cpu'].update(count=spec['vcpus'] + 1), cpu_vendor=lambda o: o['cpu'].update(vendor='GenuineIntel'),
            memory_low=lambda o: o['memory'].update(total_mib=int(spec['memory_mib'] * 0.5)), memory_high=lambda o: o['memory'].update(total_mib=spec['memory_mib'] * 2),
            no_swap=lambda o: o['memory'].update(swap_total_mib=1024), disk=lambda o: o['disk'].update(root_total_gib=spec['disk_gib'] * 2),
            storage_free=lambda o: o['disk'].update(results_free_gib=1), storage_writable=lambda o: o['disk'].update(results_writable=False),
            nofile_soft=lambda o: o['nofile'].update(soft=1024), nofile_hard=lambda o: o['nofile'].update(hard=1024), sshd_password_off=lambda o: o['sshd'].update(passwordauthentication='yes'),
            sshd_keyboard_off=lambda o: o['sshd'].update(kbdinteractiveauthentication='yes'), sshd_pubkey_on=lambda o: o['sshd'].update(pubkeyauthentication='no'), sshd_methods=lambda o: o['sshd'].update(authenticationmethods='any'),
            sshd_root_refused=lambda o: o['sshd'].update(permitrootlogin='yes'), authorized_key=lambda o: o.update(authorized_keys=['SHA256:other']),
            extra_key=lambda o: o['authorized_keys'].append('SHA256:other'), port_game_free=lambda o: o['listeners'].append(dict(protocol='udp', address='0.0.0.0', port=8081)),
            port_metrics_free=lambda o: o['listeners'].append(dict(protocol='tcp', address='127.0.0.1', port=9100)), listeners_read=lambda o: o.update(listeners=[]),
            clock_synchronized=lambda o: o['clock'].update(ntp_synchronized=False), clock_service=lambda o: o['clock'].update(service='inactive'),
            clock_monotonic=lambda o: o['clock'].update(monotonic_ns=None), clock_boot_id=lambda o: o['clock'].update(boot_id=''), guest_secret_scan=lambda o: o['secrets'].update(findings=['/home/deploy/.env']),
            binary_hash=lambda o: o['release'].update({'omega-server': 'f' * 64}), config_hash=lambda o: o['release'].update({'server_config.json': 'f' * 64}),
            sampler_present=lambda o: o['release'].pop('sample_host.py'))
        for name, change in cases.items():
            with self.subTest(name):
                observation, _ = self.healthy()
                change(observation)
                self.assertTrue(readiness.observation_problems(MANIFEST, 'game', observation, '24.04 (LTS) x64'))

    def test_only_a_silent_drop_proves_the_firewall_is_in_force(self):
        self.assertEqual(readiness.enforcement_problems(dict(outcome='timeout')), [])
        for probe in (dict(outcome='connected'), dict(outcome='refused'), dict(outcome='error'), {}, None):
            self.assertTrue(readiness.enforcement_problems(probe), probe)

    def test_clock_bracket_rules(self):
        self.assertEqual(readiness.clock_problems('game', dict(offset_s=0.1, uncertainty_s=0.3)), [])
        self.assertEqual(readiness.clock_problems('game', dict(offset_s=1.2, uncertainty_s=0.3)), [])
        self.assertTrue(readiness.clock_problems('game', dict(offset_s=2.0, uncertainty_s=0.3)))
        self.assertTrue(readiness.clock_problems('game', dict(offset_s=0.0, uncertainty_s=30.0)))
        self.assertTrue(readiness.clock_problems('game', None))
        self.assertTrue(readiness.clock_problems('game', dict(offset_s='x', uncertainty_s=0)))

    def test_sampler_rules(self):
        good = dict(samples=4, alive_until_stopped=True, monotonic_advancing=True)
        self.assertEqual(readiness.sampler_problems('game', good), [])
        for change in (dict(samples=1), dict(samples=None), dict(alive_until_stopped=False), dict(monotonic_advancing=False)):
            self.assertTrue(readiness.sampler_problems('game', dict(good, **change)), change)
        self.assertTrue(readiness.sampler_problems('game', None))

    def test_smoke_rules(self):
        _, guests = self.healthy()
        started, bot, stopped = guests._answer_smoke_game_start('game'), guests._answer_smoke_bot('bot'), guests._answer_smoke_game_stop('game')
        self.assertEqual(readiness.smoke_problems(started, bot, stopped), [])
        public_metrics = copy.deepcopy(started)
        public_metrics['listeners'][1]['address'] = '0.0.0.0'
        self.assertTrue(any('metrics_loopback_only' in p for p in readiness.smoke_problems(public_metrics, bot, stopped)))
        for change in (dict(running=False), dict(metrics_loopback_ok=False), dict(listeners=[])):
            self.assertTrue(readiness.smoke_problems(dict(started, **change), bot, stopped), change)
        for change in (dict(report=False), dict(connected_bots=1), dict(requested_bots=None), dict(disconnected_bots=1), dict(total_errors=1), dict(total_decode_failures=1),
                       dict(total_send_failures=1), dict(total_panics=1), dict(total_packets_received=0), dict(total_packets_sent=None)):
            self.assertTrue(readiness.smoke_problems(started, dict(bot, **change), stopped), change)
        for change in (dict(exited_on_signal=False), dict(processes=1), dict(processes=None), dict(listeners=None),
                       dict(listeners=[dict(protocol='udp', address='0.0.0.0', port=8081)])):
            self.assertTrue(readiness.smoke_problems(started, bot, dict(stopped, **change)), change)
        self.assertTrue(readiness.smoke_problems(None, None, None))

    def test_droplet_plan_rules(self):
        tags = MANIFEST['session']['ownership_tags']
        spec = MANIFEST['roles']['game']
        good = dict(name=MANIFEST['session']['id'] + '-game', tags=[tags['session'], tags['game']], size_slug=spec['size_slug'], region=spec['region'], image_id=spec['image_id'],
                    vcpus=spec['vcpus'], memory_mib=spec['memory_mib'], disk_gib=spec['disk_gib'], public_ipv4=['198.51.100.7'])
        self.assertEqual(readiness.droplet_problems(MANIFEST, 'game', good), [])
        for change in (dict(name='x'), dict(tags=[tags['session']]), dict(tags=[tags['game']]), dict(size_slug='s'), dict(region='nyc1'), dict(image_id=1), dict(vcpus=9), dict(memory_mib=9),
                       dict(disk_gib=9), dict(public_ipv4=[]), dict(public_ipv4=['a', 'b'])):
            self.assertTrue(readiness.droplet_problems(MANIFEST, 'game', dict(good, **change)), change)


class GuestAgent(unittest.TestCase):
    def test_listener_parser(self):
        output = ('udp UNCONN 0 0 0.0.0.0:8081 0.0.0.0:*\n'
                  'tcp LISTEN 0 128 127.0.0.1:9100 0.0.0.0:*\n'
                  'tcp LISTEN 0 128 [::]:22 [::]:*\n'
                  'udp UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*\n'
                  'garbage\n')
        self.assertEqual(guest_agent.parse_listeners(output),
                         [dict(protocol='udp', address='0.0.0.0', port=8081), dict(protocol='tcp', address='127.0.0.1', port=9100),
                          dict(protocol='tcp', address='::', port=22), dict(protocol='udp', address='127.0.0.53', port=53)])

    def test_sshd_output_is_read_as_key_value(self):
        with unittest.mock.patch.object(guest_agent, 'run', return_value=(0, 'passwordauthentication no\npermitrootlogin no\npubkeyauthentication yes\nkbdinteractiveauthentication no\nauthenticationmethods publickey\n', '')):
            self.assertEqual(guest_agent.effective_sshd(), dict(rc=0, passwordauthentication='no', kbdinteractiveauthentication='no', pubkeyauthentication='yes', authenticationmethods='publickey', permitrootlogin='no'))

    def test_content_digest_ignores_line_order_and_covers_every_blob(self):
        a = '100644 blob aaa\trust/a\n100644 blob bbb\trust/b\n'
        self.assertEqual(guest_agent.content_digest(a), guest_agent.content_digest('100644 blob bbb\trust/b\n100644 blob aaa\trust/a\n'))
        self.assertNotEqual(guest_agent.content_digest(a), guest_agent.content_digest(a.replace('aaa', 'ccc')))

    def test_secret_scan_reports_paths_and_never_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / 'clean.txt').write_text('nothing')
            (root / 'token').write_text('value dop_v1_' + 'a' * 64)
            (root / 'key').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nxx')
            found = guest_agent.secret_findings((directory,))
            self.assertEqual(found, sorted([str(root / 'key'), str(root / 'token')]))
            self.assertNotIn('dop_v1_', json.dumps(found))

    def test_cloud_init_status_reads_json_and_reports_a_timeout_as_not_done(self):
        document = json.dumps(dict(status='done', extended_status='done', errors=[], recoverable_errors={}))
        with unittest.mock.patch.object(guest_agent, 'run', return_value=(0, document, '')):
            self.assertEqual(guest_agent.cloud_init_status()['status'], 'done')
        with unittest.mock.patch.object(guest_agent, 'run', side_effect=subprocess.TimeoutExpired('x', 1)):
            self.assertEqual(guest_agent.cloud_init_status(5)['status'], 'timeout')
        with unittest.mock.patch.object(guest_agent, 'run', return_value=(1, 'not json', '')):
            self.assertIsNone(guest_agent.cloud_init_status()['status'])

    def test_agent_holds_no_credential_and_only_public_endpoints(self):
        source = pathlib.Path(guest_agent.__file__).read_text()
        self.assertEqual(manifest_mod.scan_for_secrets(source.replace('rb\'-----BEGIN [A-Z ]*PRIVATE KEY-----\'', '')), [])
        self.assertNotIn('api.digitalocean.com', source)
        self.assertNotIn('Authorization', source)
        self.assertTrue(guest_agent.REPOSITORY.startswith('https://github.com/'))

    def test_every_subcommand_the_controller_uses_exists_in_the_agent(self):
        source = pathlib.Path(provider_preflight.__file__).with_name('provisioner.py').read_text()
        import re
        used = set(re.findall(r"_agent\((?:role|'game'|'bot'), '([a-z_]+)'", source))
        self.assertEqual(used - set(guest_agent.COMMANDS), set())
        self.assertGreaterEqual(len(used), 8)
        parser = guest_agent.build_parser()
        for arguments in (['clock'], ['probe', '--role', 'game'], ['wait_cloud_init', '--timeout-s', '5'], ['fetch_source', '--sha', 'a', '--timeout-s', '5'],
                          ['build', '--toolchain', '1.91.0', '--target', 'x', '--timeout-s', '5', '--flag=--features=x'], ['install_release', '--role', 'game', '--incoming', 'x'],
                          ['sampler'], ['tcp_probe', '--host', 'a', '--port', '22'], ['smoke_game_start'], ['smoke_bot', '--server', 'a:1', '--timeout-s', '5'], ['smoke_game_stop']):
            parser.parse_args(arguments)

    def test_clock_and_a_full_probe_run_as_a_real_process(self):
        self.assertIn('wall_ns', guest_agent.cmd_clock(None))
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(['python3', '-I', str(pathlib.Path(guest_agent.__file__)), 'clock'], stdout=subprocess.PIPE, env=environment, check=True)
        self.assertIn('monotonic_ns', json.loads(result.stdout))

    def agent_dirs(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        for name, attribute in (('source', 'SOURCE_DIR'), ('release', 'RELEASE_DIR'), ('agent', 'AGENT_DIR'), ('results', 'RESULTS_DIR')):
            path = root / name
            path.mkdir()
            patcher = unittest.mock.patch.object(guest_agent, attribute, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        return root

    def stub(self, path, body):
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def test_a_guest_missing_every_tool_reports_rather_than_crashes_and_is_rejected(self):
        self.agent_dirs()
        with unittest.mock.patch.object(guest_agent.subprocess, 'run', side_effect=FileNotFoundError('tool')), \
                unittest.mock.patch.object(guest_agent, 'secret_findings', return_value=[]):
            observation = guest_agent.cmd_probe(types.SimpleNamespace(role='game'))
        json.dumps(observation)
        problems = readiness.observation_problems(MANIFEST, 'game', observation, '24.04 (LTS) x64')
        for name in ('cloud_init_done', 'sshd_readable', 'listeners_read', 'clock_synchronized', 'authorized_key', 'binary_hash', 'nofile_soft'):
            self.assertTrue(any(name in p for p in problems), name)

    def test_the_real_sampler_satisfies_the_readiness_rule(self):
        root = self.agent_dirs()
        sampler = pathlib.Path(guest_agent.__file__).parents[1] / 'quick_stress' / 'sample_host.py'
        (root / 'release' / 'sample_host.py').write_text(sampler.read_text())
        report = guest_agent.cmd_sampler(types.SimpleNamespace(seconds=3))
        self.assertEqual(readiness.sampler_problems('game', report), [], report)

    def test_fetch_source_matches_what_the_controller_computes_from_git_objects(self):
        import provision_cli
        root = self.agent_dirs()
        repo = root / 'repo'
        for relative in ('rust/Cargo.lock', 'rust/server/src/main.rs', 'deployment/server_config.loadtest.json', 'scripts/quick_stress/sample_host.py', 'README.md'):
            path = repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture ' + relative)

        def git(*arguments):
            return subprocess.run(['git', '-C', str(repo)] + list(arguments), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.decode().strip()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        git('add', '.')
        git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'fixture')
        head = git('rev-parse', 'HEAD')
        with unittest.mock.patch.object(guest_agent, 'REPOSITORY', 'file://' + str(repo)):
            report = guest_agent.cmd_fetch_source(types.SimpleNamespace(sha=head, timeout_s=30))
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['clean'])
        frozen = provision_cli.source_digests(repo, head)
        self.assertEqual(report['head'], frozen['benchmark_sha'])
        for digest in ('cargo_lock_sha256', 'server_config_sha256', 'content_sha256'):
            self.assertEqual(report[digest], frozen[digest], digest)

    def test_a_fetch_failure_is_reported(self):
        self.agent_dirs()
        with unittest.mock.patch.object(guest_agent, 'REPOSITORY', '/nonexistent/repository'):
            report = guest_agent.cmd_fetch_source(types.SimpleNamespace(sha='a' * 40, timeout_s=30))
        self.assertFalse(report['ok'])

    def test_smoke_commands_report_the_bot_result_and_really_stop_the_server(self):
        root = self.agent_dirs()
        release = root / 'release'
        self.stub(release / 'omega-server', 'exec sleep 60')
        self.stub(release / 'omega-load-test', 'while [ $# -gt 0 ]; do [ "$1" = "--output" ] && out=$2; shift; done\n'
                  'printf \'{"aggregated": {"connected_bots": 2, "disconnected_bots": 0, "total_errors": 0, "total_decode_failures": 0, '
                  '"total_send_failures": 0, "total_panics": 0, "total_packets_sent": 5, "total_packets_received": 7}}\' > "$out"')
        started = guest_agent.cmd_smoke_game_start(types.SimpleNamespace(wait_s=1))
        self.assertTrue(started['running'])
        # In production the agent has exited and init reaps the server. Here the test process is its parent.
        threading.Thread(target=os.waitpid, args=(started['pid'], 0), daemon=True).start()
        bot = guest_agent.cmd_smoke_bot(types.SimpleNamespace(server='198.51.100.7:8081', timeout_s=10))
        self.assertEqual((bot['report'], bot['connected_bots'], bot['requested_bots']), (True, 2, 2))
        stopped = guest_agent.cmd_smoke_game_stop(None)
        self.assertTrue(stopped['exited_on_signal'])
        with self.assertRaises(ProcessLookupError):
            os.kill(started['pid'], 0)

    def test_tcp_probe_reports_what_happened(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        self.assertEqual(guest_agent.cmd_tcp_probe(types.SimpleNamespace(host='127.0.0.1', port=port, timeout_s=2))['outcome'], 'connected')
        listener.close()
        self.assertEqual(guest_agent.cmd_tcp_probe(types.SimpleNamespace(host='127.0.0.1', port=port, timeout_s=2))['outcome'], 'refused')
        with unittest.mock.patch.object(guest_agent.socket, 'create_connection', side_effect=socket.timeout()):
            self.assertEqual(guest_agent.cmd_tcp_probe(types.SimpleNamespace(host='x', port=1, timeout_s=1))['outcome'], 'timeout')

    def test_a_missing_bot_report_is_reported_not_guessed(self):
        root = self.agent_dirs()
        self.stub(root / 'release' / 'omega-load-test', 'exit 1')
        report = guest_agent.cmd_smoke_bot(types.SimpleNamespace(server='a:1', timeout_s=10))
        self.assertFalse(report['report'])
        self.assertTrue(readiness.smoke_problems(None, report, None))

    def test_install_release_moves_exactly_the_role_files(self):
        root = self.agent_dirs()
        incoming = root / 'incoming'
        incoming.mkdir()
        for name in guest_agent.ROLE_FILES['game']:
            (incoming / name).write_text(name)
        report = guest_agent.cmd_install_release(types.SimpleNamespace(role='game', incoming=str(incoming)))
        self.assertEqual(sorted(report['release']), sorted(guest_agent.ROLE_FILES['game']))
        self.assertTrue(os.access(str(root / 'release' / 'omega-server'), os.X_OK))

    def test_agent_is_python_with_no_third_party_import(self):
        import ast
        tree = ast.parse(pathlib.Path(guest_agent.__file__).read_text())
        imported = {n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        allowed = {'argparse', 'hashlib', 'json', 'os', 'pathlib', 're', 'shutil', 'signal', 'socket', 'subprocess', 'sys', 'tempfile', 'time', 'urllib'}
        self.assertEqual(imported - allowed, set())


if __name__ == '__main__':
    unittest.main()
