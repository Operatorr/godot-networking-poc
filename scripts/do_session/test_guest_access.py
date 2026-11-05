"""Exact firewall rules, secret-free bootstrap, pinned SSH, readiness rules and the guest agent's parsers."""
import base64
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import shlex
import signal
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import unittest.mock

import fake_do_http
import fake_guest
import fixture_support as fx
import guest_agent
import guest_bootstrap
import guest_runner
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

    def communicate(self, timeout=None):
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
            process = processes.pop(0)
            kwargs['stdout'].write(process.stdout_bytes)
            kwargs['stderr'].write(process.stderr_bytes)
            kwargs['stdout'].flush()
            kwargs['stderr'].flush()
            return process
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
        self.assertGreaterEqual(len(waits), 3)
        self.assertLessEqual(len(waits), 12, "halved near the cutoff, not spinning")

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

    def test_real_child_output_larger_than_a_pipe_completes(self):
        access = self.access([])
        access.popen = subprocess.Popen
        access.monotonic = __import__('time').monotonic
        access.sleep = lambda _: __import__('time').sleep(0.01)
        script = "import json,sys; print(json.dumps({'packages': ['package-1.0'] * 10000})); sys.stderr.write('x' * 100000)"
        result = access._execute([sys.executable, '-c', script], 5, None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['packages']), 10000)
        self.assertEqual(result.stderr, ssh_access.cleanup_provider.redact('x' * 100000))

    def test_oversized_output_is_failure_not_successful_truncation(self):
        access = self.access([FakeProcess(stdout=b'x' * (ssh_access.MAX_OUTPUT_CHARS + 1))])
        result = access._execute(['fixture'], 5, None)
        self.assertIsNone(result.returncode)
        self.assertEqual(result.stdout, '')
        self.assertIn('limit', result.stderr)


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


def mint_grant(session, token, control=None):
    """What ``grant_prepare`` leaves on the host, without its fence check, so these tests reach the check they are about."""
    grant_id = secrets.token_hex(16)
    path = guest_agent.grant_path(grant_id, control=control)
    path.parent.mkdir(parents=True, exist_ok=True)
    guest_agent.atomic_json(path, dict(grant_id=grant_id, session_id=session, token=token, boot_id=guest_agent.boot_id(), clock_ns=guest_agent.grant_clock_ns()))
    return grant_id


def authority(**fields):
    fields.setdefault('session', 'do-test')
    fields.setdefault('token', 1)
    fields.setdefault('not_after_wall', time.time() + 10)
    fields.setdefault('grant_ttl_s', 60.0)
    if 'grant_id' not in fields:
        with contextlib.suppress(OSError):      # a stop or a probe has no grant, and may run with no host directory at all
            fields['grant_id'] = mint_grant(fields['session'], fields['token'])
    return types.SimpleNamespace(**fields)


def free_udp_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def port_free(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(('127.0.0.1', port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def wait_for(predicate, limit_s):
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('the condition was not reached')


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
        fence = ['--session', 's', '--token', '1']
        start = fence + ['--not-after-wall', '1', '--grant-id', 'g', '--grant-ttl-s', '1']
        for arguments in (['clock'], ['probe', '--role', 'game'], ['wait_cloud_init', '--timeout-s', '5'], ['tcp_probe', '--host', 'a', '--port', '22'],
                          ['fetch_source', '--sha', 'a', '--timeout-s', '5'] + fence, ['build', '--toolchain', '1.91.0', '--target', 'x', '--timeout-s', '5', '--flag=--features=x'] + fence,
                          ['install_release', '--role', 'game', '--incoming', 'x'] + fence, ['sampler'] + start, ['smoke_game_start', '--smoke-id', 'x'] + start, ['smoke_bot', '--server', 'a:1', '--timeout-s', '5'] + start, ['smoke_game_stop', '--smoke-id', 'x'] + fence):
            parser.parse_args(arguments)

    def test_every_step_that_changes_the_host_needs_authority(self):
        parser = guest_agent.build_parser()
        for arguments in (['fetch_source', '--sha', 'a', '--timeout-s', '5'], ['build', '--toolchain', '1', '--target', 'x', '--timeout-s', '5'], ['install_release', '--role', 'game', '--incoming', 'x'],
                          ['sampler'], ['smoke_game_start', '--smoke-id', 'x'], ['smoke_bot', '--server', 'a:1'], ['smoke_game_stop', '--smoke-id', 'x']):
            with self.subTest(arguments[0]), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
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

    def probe_with_dpkg(self, code, out, error=None):
        self.agent_dirs()

        def tool(argv, *args, **kwargs):
            if argv[0] == 'dpkg-query':
                if error is not None:
                    raise error
                return subprocess.CompletedProcess(argv, code, out.encode(), b'')
            raise FileNotFoundError(argv[0])
        with unittest.mock.patch.object(guest_agent.subprocess, 'run', side_effect=tool), \
                unittest.mock.patch.object(guest_agent, 'secret_findings', return_value=[]):
            return guest_agent.cmd_probe(types.SimpleNamespace(role='game'))['packages']

    GOOD_LIST = 'base-files 13fixture1\ndpkg 1.22.fixture1\nlibc6 2.39-fixture1\nopenssh-server 9.6fixture1\npython3 3.12.fixture1\n'

    def test_the_agent_returns_each_package_and_version_with_its_status_and_hash(self):
        packages = self.probe_with_dpkg(0, self.GOOD_LIST)
        self.assertEqual((packages['rc'], packages['complete'], packages['count']), (0, True, 5))
        self.assertIn(dict(name='libc6', version='2.39-fixture1'), packages['inventory'])
        self.assertEqual(packages['sha256'], hashlib.sha256(self.GOOD_LIST.encode()).hexdigest())
        self.assertIn('dpkg-query', packages['command'])
        self.assertEqual(readiness.package_problems(packages), [])
        json.dumps(packages)

    def test_two_lists_with_one_changed_version_are_told_apart_by_entry_and_by_hash(self):
        first = self.probe_with_dpkg(0, self.GOOD_LIST)
        second = self.probe_with_dpkg(0, self.GOOD_LIST.replace('libc6 2.39-fixture1', 'libc6 2.39-fixture2'))
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertEqual([e for e in second['inventory'] if e not in first['inventory']], [dict(name='libc6', version='2.39-fixture2')])

    def test_failed_truncated_or_unreadable_package_output_fails_readiness(self):
        cases = dict(nonzero=(1, self.GOOD_LIST, None), missing_tool=(0, '', FileNotFoundError('dpkg-query')), timeout=(0, '', subprocess.TimeoutExpired('dpkg-query', 60)),
                     empty=(0, '', None), truncated_mid_line=(0, self.GOOD_LIST[:-8], None), extra_field=(0, self.GOOD_LIST + 'a b c\n', None),
                     no_version=(0, self.GOOD_LIST + 'orphan\n', None), cut_at_a_line=(0, 'base-files 13fixture1\n', None))
        for name, (code, out, error) in cases.items():
            with self.subTest(name):
                packages = self.probe_with_dpkg(code, out, error)
                json.dumps(packages)
                self.assertTrue(readiness.package_problems(packages), packages)
                self.assertTrue(any('packages' in p for p in readiness.observation_problems(MANIFEST, 'game', dict(packages=packages), '24.04 (LTS) x64')))

    def test_the_real_sampler_satisfies_the_readiness_rule(self):
        root = self.agent_dirs()
        sampler = pathlib.Path(guest_agent.__file__).parents[1] / 'quick_stress' / 'sample_host.py'
        (root / 'release' / 'sample_host.py').write_text(sampler.read_text())
        report = guest_agent.cmd_sampler(authority(seconds=3))
        self.assertEqual(readiness.sampler_problems('game', report), [], report)
        again = guest_agent.cmd_sampler(authority(seconds=3))
        self.assertEqual(readiness.sampler_problems('game', again), [], 'a second pass, as a resume makes, does not read as the clock going backward')

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
            report = guest_agent.cmd_fetch_source(authority(sha=head, timeout_s=30))
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['clean'])
        frozen = provision_cli.source_digests(repo, head)
        self.assertEqual(report['head'], frozen['benchmark_sha'])
        for digest in ('cargo_lock_sha256', 'server_config_sha256', 'content_sha256'):
            self.assertEqual(report[digest], frozen[digest], digest)

    def test_a_fetch_failure_is_reported(self):
        self.agent_dirs()
        with unittest.mock.patch.object(guest_agent, 'REPOSITORY', '/nonexistent/repository'):
            report = guest_agent.cmd_fetch_source(authority(sha='a' * 40, timeout_s=30))
        self.assertFalse(report['ok'])

    def test_smoke_commands_report_the_bot_result_and_really_stop_the_server(self):
        root = self.agent_dirs()
        release = root / 'release'
        self.stub(release / 'omega-server', 'exec sleep 60')
        self.stub(release / 'omega-load-test', 'while [ $# -gt 0 ]; do [ "$1" = "--output" ] && out=$2; shift; done\n'
                  'printf \'{"aggregated": {"connected_bots": 2, "disconnected_bots": 0, "total_errors": 0, "total_decode_failures": 0, '
                  '"total_send_failures": 0, "total_panics": 0, "total_packets_sent": 5, "total_packets_received": 7}}\' > "$out"')
        started = guest_agent.cmd_smoke_game_start(authority(smoke_id='1', wait_s=1, lifetime_s=60.0))
        self.assertTrue(started['running'])
        bot = guest_agent.cmd_smoke_bot(authority(server='198.51.100.7:8081', timeout_s=10))
        self.assertEqual((bot['report'], bot['connected_bots'], bot['requested_bots']), (True, 2, 2))
        stopped = guest_agent.cmd_smoke_game_stop(authority(smoke_id='1'))
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
        report = guest_agent.cmd_smoke_bot(authority(server='a:1', timeout_s=10))
        self.assertFalse(report['report'])
        self.assertTrue(readiness.smoke_problems(None, report, None))

    def test_install_release_moves_exactly_the_role_files(self):
        root = self.agent_dirs()
        incoming = root / 'incoming'
        incoming.mkdir()
        for name in guest_agent.ROLE_FILES['game']:
            (incoming / name).write_text(name)
        report = guest_agent.cmd_install_release(authority(role='game', incoming=str(incoming)))
        self.assertEqual(sorted(report['release']), sorted(guest_agent.ROLE_FILES['game']))
        self.assertTrue(os.access(str(root / 'release' / 'omega-server'), os.X_OK))

    def test_agent_is_python_with_no_third_party_import(self):
        import ast
        tree = ast.parse(pathlib.Path(guest_agent.__file__).read_text())
        imported = {n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        allowed = {'argparse', 'contextlib', 'ctypes', 'fcntl', 'functools', 'hashlib', 'json', 'os', 'pathlib', 're', 'secrets', 'shutil', 'signal', 'socket', 'struct', 'subprocess', 'sys', 'tempfile', 'time', 'urllib'}
        self.assertEqual(imported - allowed, set())


class RealCommandBounds(unittest.TestCase):
    """The real poller, a real child, the real clock and the real one second poll. Not a real-time promise: an overrun is bounded by these margins, not by a poll."""
    MARGIN_S = 0.2

    def test_expensive_temporary_file_preparation_cannot_spawn_after_cutoff(self):
        real_temporary_file = tempfile.TemporaryFile
        clock = [0.0]
        files = []
        def delayed():
            clock[0] += 0.2
            stream = real_temporary_file()
            files.append(stream)
            return stream
        popen = unittest.mock.Mock(side_effect=AssertionError('spawned after cutoff'))
        with unittest.mock.patch.object(ssh_access.tempfile, 'TemporaryFile', side_effect=delayed):
            result = ssh_access.bounded_command(popen, ['unused'], 0.25, None, lambda _: None,
                                                lambda: clock[0], ssh_access.POLL_S)
        popen.assert_not_called()
        self.assertIsNone(result.returncode)
        self.assertIn('timed out', result.stderr)
        self.assertTrue(all(stream.closed for stream in files))

    def run_child(self, seconds, cutoff, on_wait=None, sleep=time.sleep):
        started = time.monotonic()
        result = ssh_access.bounded_command(subprocess.Popen, [sys.executable, '-c', 'import time; time.sleep(%s)' % seconds], cutoff, on_wait, sleep, time.monotonic, ssh_access.POLL_S)
        return result, time.monotonic() - started

    def test_a_child_outlasting_a_quarter_second_cutoff_is_killed_at_it(self):
        result, elapsed = self.run_child(2.0, 0.25)
        self.assertIsNone(result.returncode)
        self.assertIn('timed out', result.stderr)
        self.assertLess(elapsed, 0.25 + self.MARGIN_S)

    def test_a_child_ending_after_the_cutoff_is_not_a_success(self):
        result, elapsed = self.run_child(0.5, 0.25)
        self.assertIsNone(result.returncode, 'the review probe got success here at 1.012 s')
        self.assertLess(elapsed, 0.25 + self.MARGIN_S)

    def test_a_child_ending_inside_a_fractional_cutoff_is_a_success_inside_it(self):
        result, elapsed = self.run_child(0.05, 2.0)
        self.assertEqual(result.returncode, 0)
        self.assertLess(elapsed, 2.0)

    def test_a_callback_that_uses_up_the_budget_ends_the_command(self):
        result, elapsed = self.run_child(5.0, 0.2, on_wait=lambda: time.sleep(0.4))
        self.assertIsNone(result.returncode)
        self.assertLess(elapsed, 0.4 + self.MARGIN_S, 'one callback, then no sleep at all')

    def test_a_child_already_gone_when_seen_late_is_not_accepted(self):
        result, elapsed = self.run_child(0.0, 0.2, on_wait=lambda: time.sleep(0.5))
        self.assertIsNone(result.returncode, 'nobody can show it ended in time, and a caller with a deadline may not act on it')
        self.assertIn('timed out', result.stderr)

    def test_a_sleep_is_never_longer_than_what_is_left(self):
        sleeps = []
        started = time.monotonic()

        def recording(seconds):
            sleeps.append((seconds, 0.3 - (time.monotonic() - started)))
            time.sleep(seconds)
        self.run_child(1.0, 0.3, sleep=recording)
        self.assertTrue(sleeps)
        for asked, left in sleeps:
            self.assertLessEqual(asked, left + 0.01)

    def test_a_killed_child_is_reaped_and_leaves_no_process(self):
        popped = []

        def popen(*a, **k):
            popped.append(subprocess.Popen(*a, **k))
            return popped[-1]
        ssh_access.bounded_command(popen, [sys.executable, '-c', 'import time; time.sleep(30)'], 0.1, None, time.sleep, time.monotonic, ssh_access.POLL_S)
        self.assertIsNotNone(popped[0].poll())


class SmokeAuthority(unittest.TestCase):
    """The real agent and its real helper: a real server stand-in, a real UDP socket and real signals. Files as on a guest, under a temporary root."""

    SESSION = 'do-test'

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(directory.name)
        for name, attribute in (('release', 'RELEASE_DIR'), ('results', 'RESULTS_DIR')):
            (self.root / name).mkdir()
            patcher = unittest.mock.patch.object(guest_agent, attribute, self.root / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.port = free_udp_port()
        patcher = unittest.mock.patch.object(guest_agent, 'GAME_PORT', self.port)
        patcher.start()
        self.addCleanup(patcher.stop)
        standins = pathlib.Path(guest_agent.__file__).parent / 'fixtures' / 'local_standins'
        target = self.root / 'release' / 'omega-server'
        target.write_bytes((standins / 'omega-server').read_bytes())
        target.chmod(0o755)
        (self.root / 'release' / 'server_config.json').write_text('{}')
        self.addCleanup(self.kill_everything)

    def kill_everything(self):
        record = guest_agent.read_json(guest_agent.bounded_paths('readiness-game')[0]) or {}
        guest_agent.signal_identity(record.get('process'), signal.SIGKILL)
        guest_agent.signal_identity(record.get('supervisor'), signal.SIGKILL)

    def start(self, token=1, smoke_id='1', lifetime_s=30.0, not_after=None):
        return guest_agent.cmd_smoke_game_start(authority(token=token, smoke_id=smoke_id, wait_s=1, lifetime_s=lifetime_s, session=self.SESSION,
                                                          not_after_wall=time.time() + 10 if not_after is None else not_after))

    def stop(self, token=1, smoke_id='1'):
        return guest_agent.cmd_smoke_game_stop(authority(token=token, smoke_id=smoke_id, session=self.SESSION))

    def fence(self):
        return guest_agent.read_json(guest_agent.control_dir() / 'fence.json')

    def assert_refused(self, code, call, *arguments, **options):
        with self.assertRaises(guest_agent.Refused) as caught:
            call(*arguments, **options)
        self.assertEqual(caught.exception.code, code)

    def assert_no_server(self):
        self.assertIsNone(guest_agent.read_json(guest_agent.bounded_paths('readiness-game')[0]))
        self.assertTrue(port_free(self.port))

    def test_a_delayed_smoke_from_a_replaced_controller_starts_nothing(self):
        guest_runner.cmd_fence(types.SimpleNamespace(session=self.SESSION, token=2), guest_runner.Host(self.root / 'results' / 'do-runs'))
        self.assert_refused('stale_fence', self.start, token=1)
        self.assert_no_server()

    def test_another_sessions_controller_starts_nothing(self):
        guest_runner.cmd_fence(types.SimpleNamespace(session='do-other', token=9), guest_runner.Host(self.root / 'results' / 'do-runs'))
        self.assert_refused('foreign_session', self.start)
        self.assert_no_server()

    def test_a_smoke_past_its_authorization_starts_nothing(self):
        self.assert_refused('authorization_expired', self.start, not_after=time.time() - guest_agent.CLOCK_TOLERANCE_S - 0.5)
        self.assert_no_server()

    def test_a_closed_session_starts_nothing_and_the_close_survives_a_higher_token(self):
        host = guest_runner.Host(self.root / 'results' / 'do-runs')
        guest_runner.cmd_fence(types.SimpleNamespace(session=self.SESSION, token=1, close='operator abort'), host)
        self.assert_refused('session_closed', self.start, token=1)
        self.assert_refused('session_closed', self.start, token=2)
        self.assertEqual(self.fence(), dict(session_id=self.SESSION, token=2, closed='operator abort'))
        self.assert_no_server()

    def test_the_helper_itself_refuses_when_authority_changed_after_the_agent_looked(self):
        """The helper is a separate process and can be scheduled late. It looks again, right before anything exists."""
        state, stop, log = guest_agent.bounded_paths('readiness-game')
        control = guest_agent.control_dir()
        cases = dict(stale_fence=dict(token=2), session_closed=dict(closed='operator abort'), authorization_expired=dict(not_after=time.time() - 5), stop_requested=dict(stop=True))
        for code, case in cases.items():
            with self.subTest(code):
                guest_agent.atomic_json(control / 'fence.json', dict(session_id=self.SESSION, token=case.get('token', 1), closed=case.get('closed')))
                if case.get('stop'):
                    stop.write_text('{}')
                with unittest.mock.patch.object(guest_agent.subprocess, 'Popen', side_effect=AssertionError('nothing may be started')):
                    guest_agent.cmd_bounded(types.SimpleNamespace(state=str(state), stop=str(stop), log=str(log), control=str(control), session=self.SESSION, token=1,
                                                                  not_after_wall=case.get('not_after', time.time() + 10), grant_id=mint_grant(self.SESSION, 1, control), grant_ttl_s=60.0,
                                                                  lifetime_s=5.0, cwd=str(self.root), argv=['--', 'true']))
                self.assertEqual(guest_agent.read_json(state)['refused'], code)
                self.assertIsNone(guest_agent.read_json(state)['process'])
                state.unlink()
                if case.get('stop'):
                    stop.unlink()

    def test_a_lost_reply_cannot_outlive_the_helper_with_no_controller_left(self):
        started = self.start(lifetime_s=1.5)
        self.assertTrue(started['running'])
        self.assertFalse(port_free(self.port), 'a real socket is held')
        identity = started['process']
        # Nothing more is sent: the reply was lost and the controller is gone.
        state = guest_agent.bounded_paths('readiness-game')[0]
        wait_for(lambda: guest_agent.read_json(state).get('ended'), 10.0)
        self.assertFalse(guest_agent.same_process(identity))
        self.assertTrue(port_free(self.port))
        self.assertEqual(guest_agent.read_json(state)['reason'], 'lifetime_exhausted')

    def test_the_stop_settles_a_lost_reply_and_a_start_that_arrives_after_it_is_refused(self):
        started = self.start()
        stopped = self.stop()
        self.assertTrue(stopped['exited_on_signal'])
        self.assertFalse(guest_agent.same_process(started['process']))
        self.assertTrue(port_free(self.port))
        self.assert_refused('smoke_stopped', self.start, smoke_id='1')
        self.assertTrue(port_free(self.port))

    def test_a_stop_before_any_start_blocks_that_start(self):
        self.assertTrue(self.stop()['exited_on_signal'], 'nothing to stop is not a failure')
        self.assert_refused('smoke_stopped', self.start, smoke_id='1')

    def test_a_replaced_controller_cannot_stop_the_new_one(self):
        started = self.start(token=2)
        self.assert_refused('stale_fence', self.stop, token=1)
        self.assertTrue(guest_agent.same_process(started['process']))
        self.assertTrue(self.stop(token=2)['exited_on_signal'])

    def test_the_stop_still_works_through_cleanup(self):
        started = self.start()
        guest_runner.cmd_fence(types.SimpleNamespace(session=self.SESSION, token=1, close='cleanup'), guest_runner.Host(self.root / 'results' / 'do-runs'))
        self.assertTrue(self.stop()['exited_on_signal'])
        self.assertFalse(guest_agent.same_process(started['process']))

    def test_a_new_controller_retires_a_smoke_it_never_started(self):
        started = self.start(token=1)
        self.stop(token=2, smoke_id='retire-2')
        self.assertFalse(guest_agent.same_process(started['process']))
        self.assertEqual(self.fence()['token'], 2, 'and the old controller is fenced out')

    def test_a_second_smoke_cannot_overlap_the_first_or_a_run(self):
        self.start()
        self.assert_refused('overlap', self.start, smoke_id='2')
        self.stop()
        (guest_agent.control_dir() / 'active.json').write_text(json.dumps(dict(run_id='run')))
        self.assert_refused('overlap', self.start, smoke_id='3')

    def test_a_killed_helper_leaves_the_server_to_be_stopped_only_by_its_exact_identity(self):
        started = self.start()
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_for(lambda: not guest_agent.same_process(started['supervisor']), 5.0)
        if sys.platform == 'darwin':
            self.assertTrue(guest_agent.same_process(started['process']), 'macOS has no parent-death signal, so this path really runs here')
            self.assertFalse(self.stop()['exited_on_signal'], 'it had to be killed')
        else:
            self.stop()
        self.assertFalse(guest_agent.same_process(started['process']))

    def test_a_recorded_identity_from_another_boot_is_never_signalled(self):
        victim = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        self.addCleanup(lambda: (victim.kill(), victim.wait()))
        wait_for(lambda: guest_agent.process_start_id(victim.pid), 5.0)
        other_boot = dict(guest_agent.identity_of(victim.pid), boot_id='a-previous-boot')
        self.assertFalse(guest_agent.same_process(other_boot))
        state = guest_agent.bounded_paths('readiness-game')[0]
        state.write_text(json.dumps(dict(supervisor=dict(other_boot), process=other_boot, ended=False)))
        self.stop()
        self.assertIsNone(victim.poll())

    def test_the_agent_and_the_runner_see_the_same_identity(self):
        self.assertEqual(guest_agent.identity_of(os.getpid()), guest_runner.identity_of(os.getpid()))
        self.assertEqual(guest_agent.CLOCK_TOLERANCE_S, guest_runner.LAUNCH_CLOCK_TOLERANCE_S)

    def test_a_real_refusal_is_a_document_not_a_crash(self):
        guest_runner.cmd_fence(types.SimpleNamespace(session=self.SESSION, token=2), guest_runner.Host(self.root / 'results' / 'do-runs'))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = guest_agent.main(['smoke_game_start', '--session', self.SESSION, '--token', '1', '--not-after-wall', str(time.time() + 10), '--grant-id', '0' * 32, '--grant-ttl-s', '10', '--smoke-id', '1'])
        document = json.loads(output.getvalue())
        self.assertEqual((code, document['ok'], document['code']), (0, False, 'stale_fence'))


if __name__ == '__main__':
    unittest.main()
