"""Offline guests behind the real first-contact decision. Nothing here runs a command or opens a connection.

The nonce check uses the bytes the account actually received in user data, so these fixtures prove the whole path from
rendering to pinning. Every observation starts healthy for the frozen manifest, and a fixture breaks one fact at a time.
"""
import base64
import copy
import hashlib
import json

import guest_bootstrap
import ssh_access

HOST_KEY_BLOBS = dict(game=base64.b64encode(b'fixture-game-host-key').decode(), bot=base64.b64encode(b'fixture-bot-host-key').decode())
SAMPLER_SHA256 = 'a' * 64
AGENT_SECONDS = dict(wait_cloud_init=60, fetch_source=30, build=240, install_release=2, probe=2, sampler=4, smoke_game_start=3, smoke_bot=7,
                     smoke_game_stop=2, tcp_probe=5)
FIXTURE_PACKAGES = {'base-files': '13fixture1', 'dpkg': '1.22.fixture1', 'libc6': '2.39-fixture1', 'openssh-server': '9.6fixture1', 'python3': '3.12.fixture1'}


class FakeGuests(ssh_access.GuestAccess):
    def __init__(self, sim):
        super().__init__()
        self.sim = sim
        self.manifest = sim.manifest
        self.account = sim.account
        self.commands = []
        self.overrides = {}
        self.impostor = set()
        self.silent_until = {}
        self.copy_failures = set()
        self.exit_codes = {}
        self.package_versions = {}

    # ---- first contact -----------------------------------------------------------------------

    def _role_at(self, address):
        for droplet in self.account.droplets.values():
            if droplet['networks']['v4'][0]['ip_address'] == address:
                return droplet['name'].rsplit('-', 1)[1], droplet
        return None, None

    def _scan_host_key(self, address):
        role, _ = self._role_at(address)
        if role is None or self.sim.clock.wall() < self.silent_until.get(role, 0):
            return None
        if role in self.impostor:
            return 'ssh-ed25519', base64.b64encode(b'impostor-host-key').decode()
        return 'ssh-ed25519', HOST_KEY_BLOBS[role]

    def _read_binding(self, role, address, host_key):
        name = self.manifest['session']['id'] + '-' + role
        request = next((r for r in self.account.droplet_requests if r['name'] == name), None)
        if request is None:
            return None
        document = json.loads(request['user_data'].split('\n', 1)[1])
        nonce_file = next(f for f in document['write_files'] if f['path'] == guest_bootstrap.NONCE_PATH)
        nonce = 'wrong-nonce' if role in self.impostor else nonce_file['content'].strip()
        return json.dumps(dict(algorithm='hmac-sha256', hmac=ssh_access.expected_binding(nonce, host_key[1])))

    def _pin(self, role, address, host_key):
        self.commands.append(dict(role=role, step='pin', address=address))

    # ---- commands ----------------------------------------------------------------------------

    def _spend(self, seconds, on_wait):
        remaining = seconds
        while remaining > 0:
            step = min(remaining, 5)
            self.sim.sleep(step)
            remaining -= step
            if on_wait is not None:
                on_wait()

    def run(self, role, argv, timeout_s, on_wait=None):
        if role not in self.pins:
            raise AssertionError('a command ran before the host key was pinned')
        step = argv[2] if len(argv) > 2 and argv[0] == 'python3' else argv[0]
        self.commands.append(dict(role=role, step=step, argv=[str(a) for a in argv], timeout_s=timeout_s))
        seconds = AGENT_SECONDS.get(step, 0)
        if seconds > timeout_s:
            self._spend(timeout_s, on_wait)
            return ssh_access.CommandResult(None, '', 'timed out')
        self._spend(seconds, on_wait)
        if (role, step) in self.exit_codes:
            return ssh_access.CommandResult(self.exit_codes[(role, step)], '', 'scripted failure')
        document = self._document(role, step)
        override = self.overrides.get((role, step))
        if override is not None:
            document = override(copy.deepcopy(document))
        return ssh_access.CommandResult(0, json.dumps(document), '')

    def put(self, role, local_path, remote_path, timeout_s, on_wait=None):
        self.commands.append(dict(role=role, step='put', remote=str(remote_path)))
        code = 1 if (role, 'put') in self.copy_failures else 0
        return ssh_access.CommandResult(code, '', 'scripted copy failure' if code else '')

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        self.commands.append(dict(role=role, step='get', remote=str(remote_path)))
        code = 1 if (role, 'get') in self.copy_failures else 0
        return ssh_access.CommandResult(code, '', 'scripted copy failure' if code else '')

    def steps(self, role=None):
        return [c['step'] for c in self.commands if role is None or c['role'] == role]

    def break_step(self, role, step, **fields):
        def change(document):
            document.update(fields)
            return document
        self.overrides[(role, step)] = change

    # ---- healthy answers ---------------------------------------------------------------------

    def _release(self, role):
        source = self.manifest['source']
        if role == 'bot':
            return {'omega-load-test': source['binary_sha256']['bot'], 'omega-server': source['binary_sha256']['game'],
                    'server_config.json': source['server_config_sha256'], 'sample_host.py': SAMPLER_SHA256}
        return {'omega-server': source['binary_sha256']['game'], 'server_config.json': source['server_config_sha256'], 'sample_host.py': SAMPLER_SHA256}

    def _document(self, role, step):
        return getattr(self, '_answer_' + step, self._answer_nothing)(role)

    def _answer_nothing(self, role):
        return {}

    def _answer_wait_cloud_init(self, role):
        return dict(rc=0, status='done', extended_status='done', errors=[], recoverable_errors={}, boot_finished=True)

    def _answer_fetch_source(self, role):
        source = self.manifest['source']
        return dict(ok=True, head=source['benchmark_sha'], clean=True, cargo_lock_sha256=source['cargo_lock_sha256'],
                    server_config_sha256=source['server_config_sha256'], content_sha256=source['content_sha256'])

    def _answer_build(self, role):
        source = self.manifest['source']
        return dict(ok=True, rc=0, clean_after_build=True, toolchain=source['rust_toolchain'], target=source['target_triple'], flags=list(source['build_flags']),
                    rustc='rustc %s (fixture)\nhost: %s\n' % (source['rust_toolchain'], source['target_triple']), cargo='cargo ' + source['rust_toolchain'],
                    rustup_init_sha256='b' * 64, log_sha256='c' * 64, release=self._release('bot'))

    def _answer_install_release(self, role):
        return dict(ok=True, release=self._release(role))

    def _answer_probe(self, role):
        spec = self.manifest['roles'][role]
        return dict(schema='omega.do-session.guest-observation/1', role=role, os=dict(id='ubuntu', version_id='24.04'), kernel='6.8.0-fixture', architecture='x86_64',
                    cpu=dict(count=spec['vcpus'], vendor='AuthenticAMD', model='AMD EPYC fixture'), memory=dict(total_mib=int(spec['memory_mib'] * 0.93), swap_total_mib=0),
                    disk=dict(root_total_gib=spec['disk_gib'] - 1, results_free_gib=spec['disk_gib'] - 5, results_writable=True),
                    nofile=dict(soft=guest_bootstrap.NOFILE_LIMIT, hard=guest_bootstrap.NOFILE_LIMIT),
                    cloud_init=self._answer_wait_cloud_init(role),
                    sshd=dict(rc=0, passwordauthentication='no', kbdinteractiveauthentication='no', pubkeyauthentication='yes', authenticationmethods='publickey', permitrootlogin='no'),
                    authorized_keys=[self.manifest['ssh_key']['fingerprint_sha256']],
                    listeners=[dict(protocol='tcp', address='0.0.0.0', port=22)],
                    clock=dict(ntp_synchronized=True, service='active', wall_ns=int(self.sim.clock.wall() * 1e9), monotonic_ns=int(self.sim.clock.mono() * 1e9), boot_id='fixture-boot-' + role),
                    packages=self.packages(role),
                    network=dict(default_route='[]', addresses='[]'), secrets=dict(findings=[]), release=self._release(role))

    def packages(self, role):
        """Synthetic names and versions, never read from any real machine. ``package_versions`` changes one for a role."""
        versions = dict(FIXTURE_PACKAGES, **self.package_versions.get(role, {}))
        inventory = [dict(name=name, version=version) for name, version in sorted(versions.items())]
        text = ''.join('%s %s\n' % (e['name'], e['version']) for e in inventory)
        return dict(command='dpkg-query -W -f ${Package} ${Version}\\n', rc=0, complete=True, incomplete=None, count=len(inventory),
                    sha256=hashlib.sha256(text.encode()).hexdigest(), inventory=inventory)

    def _answer_tcp_probe(self, role):
        return dict(outcome='timeout')

    def _answer_clock(self, role):
        return dict(wall_ns=int(self.sim.clock.wall() * 1e9), monotonic_ns=int(self.sim.clock.mono() * 1e9))

    def _answer_sampler(self, role):
        return dict(samples=4, alive_until_stopped=True, monotonic_advancing=True, sha256='d' * 64)

    def _answer_grant_prepare(self, role):
        self.grant_count = getattr(self, 'grant_count', 0) + 1
        return dict(ok=True, grant_id='%032x' % self.grant_count, raised=True)

    def _answer_smoke_game_start(self, role):
        return dict(pid=4242, running=True, metrics_loopback_ok=True,
                    listeners=[dict(protocol='udp', address='0.0.0.0', port=8081), dict(protocol='tcp', address='127.0.0.1', port=9100),
                               dict(protocol='tcp', address='0.0.0.0', port=22)])

    def _answer_smoke_bot(self, role):
        return dict(rc=0, report=True, requested_bots=2, report_sha256='e' * 64, connected_bots=2, disconnected_bots=0, total_errors=0, total_decode_failures=0,
                    total_send_failures=0, total_panics=0, total_packets_sent=300, total_packets_received=450)

    def _answer_smoke_game_stop(self, role):
        return dict(exited_on_signal=True, processes=0, listeners=[dict(protocol='tcp', address='0.0.0.0', port=22)])
