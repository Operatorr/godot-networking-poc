"""Run-slice fixtures: a whole offline session driven to a ready pair, then the real executor over fake or real guests."""
import dataclasses
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import threading

import fake_run_guest
import guest_runner
import provision_fixtures as pf
import provisioner
import registry
import run_executor
import run_plan
import search
import ssh_access

HERE = pathlib.Path(__file__).parent
STANDINS = HERE / 'fixtures' / 'local_standins'
FAST_POLICY = run_executor.Policy(poll_s=10.0)


class ScriptedAdapter(run_plan.ReleaseAdapter):
    """The real adapter's processes over a fake guest, which only ever writes the sampler file and the swarm's report."""

    def required_on_clean_exit(self, role):
        return ('sampler.ndjson', 'report.json') if role == 'bot' else ('sampler.ndjson',)


class SimulatedCrash(BaseException):
    """Nothing catches this but the fixture, like a process that simply stopped existing at that line."""


def crash_at(point):
    def failpoint(name):
        if name == point:
            raise SimulatedCrash(name)
    return failpoint


def scripted_scorer(outcomes=None, default=search.PASS):
    """A stand-in for slices 5 and 6, with no opinion of its own: a test says what each target scores. Only fixtures may do this."""
    outcomes = outcomes or {}
    seen = []

    def score(evidence):
        seen.append(evidence)
        outcome = outcomes.get((evidence['trial']['phase'], evidence['trial']['target']), outcomes.get(evidence['trial']['target'], default))
        if outcome is None:
            return None
        return dict(outcome=outcome, evidence_ref=evidence['execution_ref'], scorer='scripted-fixture', reasons=['scripted'])
    score.seen = seen
    return score


class RunSim(pf.Sim):
    """A provisioned session with typed runs on, exactly as ``registry_cli.py`` serves it."""

    def __init__(self, case, **options):
        options.setdefault('typed_runs', True)
        super().__init__(case, **options)
        self.guests = fake_run_guest.FakeRunGuests(self)
        self.result = None

    def ready(self):
        self.result = self.run()
        if self.result.status != provisioner.READY:
            raise AssertionError('the fixture pair did not reach ready: %s %s' % (self.result.code, self.result.detail))
        return self.result

    def executor(self, client=None, token=None, scorer=None, failpoint=None, policy=None, source_problems=None, guests=None, readiness_problems=None, adapter=None, window_prover=None):
        return run_executor.RunExecutor(client or self.client, guests or self.guests, self.provider, self.manifest, self.sha, self.stack.root, token if token is not None else self.result.fencing_token,
                                        self.sleep, self.monotonic, self.clock.wall, scorer=scorer, adapter=adapter or ScriptedAdapter(), policy=policy or FAST_POLICY, failpoint=failpoint,
                                        source_problems=source_problems or (lambda: []), readiness_problems=readiness_problems, window_prover=window_prover)

    def controller(self, name='controller-b', takeover=True, **options):
        """Returning after a crash: a new client, a new token, a paused session."""
        client = pf.client_for(self, name)
        control = client.acquire(self.session_id, takeover=takeover)
        return self.executor(client=client, token=control['fencing_token'], **options), control

    def records(self):
        return self.stack.registry.run_records(self.session_id)

    def status_now(self):
        return self.stack.registry.status(self.session_id)

    def run_dir(self, run_id):
        return self.stack.root / 'runs' / run_id


def make_writable(root):
    """Sealed trees are read-only by design, and a temporary directory still has to be removed."""
    for directory, names, _ in os.walk(str(root)):
        os.chmod(directory, 0o755)
        for name in names:
            os.chmod(os.path.join(directory, name), 0o755)


# ---- real local processes -------------------------------------------------------------------------

class LocalGuests(ssh_access.GuestAccess):
    """Two host roots on this machine, real subprocesses, real file copies. No SSH, no remote host and no systemd.

    Paths a real guest would see are mapped under each role's root, so the uploaded runner is what actually executes.
    """
    UNIT_MODE = guest_runner.PROCESS_GROUP

    def __init__(self, root, environment=None):
        super().__init__()
        self.root = pathlib.Path(root)
        self.environment = dict(os.environ, **(environment or {}))
        self.environment['PYTHONDONTWRITEBYTECODE'] = '1'
        self.pins = dict(game='local-game', bot='local-bot')

    def host_path(self, role, path):
        return self.root / role / str(path).lstrip('/')

    def runner_root(self, role):
        return self.host_path(role, guest_runner.DEFAULT_ROOT)

    def _pinned_addresses(self):
        return {'198.51.100.10', '198.51.100.11', 'local-game', 'local-bot'}

    def run(self, role, argv, timeout_s, on_wait=None):
        if argv[0] == 'python3' and argv[1] == provisioner.AGENT_REMOTE:
            # Not installed here, because its paths and tools are Linux ones, and no smoke is ever started on this path. ``test_guest_access`` runs the real agent.
            return ssh_access.CommandResult(0, json.dumps(dict(exited_on_signal=True, processes=0, listeners=[])), '')
        if argv[0] == 'python3':
            argv = [sys.executable, str(self.host_path(role, argv[1])), '--root', str(self.runner_root(role))] + [str(a) for a in argv[2:]]

        def popen(command, **options):
            return subprocess.Popen(command, env=self.environment, **options)
        import time
        return ssh_access.bounded_command(popen, argv, timeout_s, on_wait, time.sleep, time.monotonic, 0.02)

    def put(self, role, local_path, remote_path, timeout_s, on_wait=None):
        target = self.host_path(role, remote_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(local_path), str(target))
        return ssh_access.CommandResult(0, '', '')

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        try:
            shutil.copyfile(str(self.host_path(role, remote_path)), str(local_path))
        except OSError as error:
            return ssh_access.CommandResult(1, '', type(error).__name__)
        return ssh_access.CommandResult(0, '', '')


class LocalAdapter(run_plan.ReleaseAdapter):
    """Stand-in programs under a role root and loopback ports. The swarm's duration is scaled, because only the bound matters here."""

    sampler_interval_s = 0.1

    def __init__(self, guests, game_port, metrics_port, workload_seconds=1.0, game_extra=(), bot_extra=()):
        self.guests = guests
        self.game_port = game_port
        self.metrics_port = metrics_port
        self.workload_seconds = workload_seconds
        self.game_extra = list(game_extra)
        self.bot_extra = list(bot_extra)
        self.interface = 'lo0'

    def game_address(self, addresses):
        return '127.0.0.1'

    def _release(self, role):
        return str(self.guests.host_path(role, run_plan.RELEASE_DIR))

    @property
    def source_dir(self):
        return str(self.guests.host_path('bot', run_plan.SOURCE_DIR))

    def program_paths(self):
        return dict(game=self._release('game') + '/omega-server', bot=self._release('bot') + '/omega-load-test')

    def config_path(self):
        return self._release('game') + '/server_config.json'

    def sampler_path(self, role):
        return self._release(role) + '/sample_host.py'

    def game_process(self, manifest, trial, addresses):
        return dict(name='game', primary=True, argv=[self.program_paths()['game'], '--config', self.config_path(), '--mode', 'arena', '--port', str(self.game_port)] + self.game_extra)

    def bot_process(self, manifest, trial, addresses):
        return dict(name='bot', primary=True, argv=[self.program_paths()['bot'], '--server', '127.0.0.1:%d' % self.game_port, '--bots', str(trial.target),
                                                    '--duration', str(self.workload_seconds), '--output', '{run_dir}/report.json'] + self.bot_extra)

    def sampler_process(self, role):
        return dict(name='sampler', argv=[sys.executable, self.sampler_path(role), '--out', '{run_dir}/sampler.ndjson', '--pids', '{run_dir}/sampler.pids', '--interval', '0.1'])

    def required_on_clean_exit(self, role):
        return ScriptedAdapter.required_on_clean_exit(self, role)


class RealReleaseAdapter(LocalAdapter):
    """The same layout with a real build in it, running the production adapter's measured processes. Loopback and macOS, so no measurement is claimed."""
    sampler_interval_s = run_plan.SAMPLER_INTERVAL_S
    game_process = run_plan.ReleaseAdapter.game_process
    bot_process = run_plan.ReleaseAdapter.bot_process
    required_on_clean_exit = run_plan.ReleaseAdapter.required_on_clean_exit

    def sampler_process(self, role):
        return dict(run_plan.ReleaseAdapter.sampler_process(self, role), argv=[sys.executable] + run_plan.ReleaseAdapter.sampler_process(self, role)['argv'][1:])


def install_real_release(hosts, release_dir, metrics_port):
    """Swap the stand-ins for a local release build, before the manifest freezes their hashes."""
    release_dir = pathlib.Path(release_dir)
    for role, name in (('game', 'omega-server'), ('bot', 'omega-load-test')):
        target = hosts.guests.host_path(role, run_plan.RELEASE_DIR) / name
        target.unlink()
        shutil.copyfile(str(release_dir / name), str(target))
        target.chmod(0o755)
    config = json.loads((HERE.parents[1] / 'deployment' / 'server_config.loadtest.json').read_text())
    config['metrics_port'] = metrics_port
    pathlib.Path(hosts.adapter.config_path()).write_text(json.dumps(config))


@dataclasses.dataclass
class LocalHosts:
    guests: LocalGuests
    adapter: LocalAdapter
    state_file: pathlib.Path
    bin_dir: pathlib.Path


def write_tc_stub(bin_dir, state_file):
    """``tc`` cannot exist on macOS, so this one program is scripted. The runner still reads it as a real subprocess."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / 'tc'
    stub.write_text('#!/bin/sh\nif [ "$3" = "show" ] && [ "$2" = "filter" ]; then echo "[]"; else cat "%s"; fi\n' % state_file)
    stub.chmod(0o755)
    state_file.write_text(json.dumps([dict(kind='noqueue', dev='lo0')]))


def install_local_hosts(root, game_port, metrics_port, **adapter_options):
    """Copy stand-ins into both role roots, as a build relay would, and put a real git checkout where the source belongs."""
    root = pathlib.Path(root)
    bin_dir, state_file = root / 'shim-bin', root / 'qdisc-state.json'
    write_tc_stub(bin_dir, state_file)
    guests = LocalGuests(root, environment=dict(PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', '')))
    sampler = HERE.parent / 'quick_stress' / 'sample_host.py'
    for role in ('game', 'bot'):
        release = guests.host_path(role, run_plan.RELEASE_DIR)
        release.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(sampler), str(release / 'sample_host.py'))
    for role, name in (('game', 'omega-server'), ('bot', 'omega-load-test')):
        target = guests.host_path(role, run_plan.RELEASE_DIR) / name
        shutil.copyfile(str(STANDINS / name), str(target))
        target.chmod(0o755)
    (guests.host_path('game', run_plan.RELEASE_DIR) / 'server_config.json').write_text('{"synthetic": true}\n')
    source = guests.host_path('bot', run_plan.SOURCE_DIR)
    source.mkdir(parents=True, exist_ok=True)
    (source / 'README').write_text('synthetic source checkout\n')
    git = ['git', '-C', str(source), '-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false']
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(git + ['add', '.'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'synthetic'], check=True)
    return LocalHosts(guests, LocalAdapter(guests, game_port, metrics_port, **adapter_options), state_file, bin_dir)


_PORT_LOCK = threading.Lock()
_PORTS_GIVEN = set()


def free_ports(count=2):
    """Below every ephemeral range, because any process's outgoing socket could take a port that only looked free up there."""
    found = []
    with _PORT_LOCK:
        while len(found) < count:
            port = random.randint(21000, 31000)
            if port not in _PORTS_GIVEN and guest_runner.port_free('udp', port) and guest_runner.port_free('tcp', port):
                _PORTS_GIVEN.add(port)
                found.append(port)
    return found


class LocalPairProvider:
    """The provider's view of a pair, from one JSON file a test can change. Read-only, like everything the executor may do."""

    def __init__(self, path):
        self.path = pathlib.Path(path)

    def _state(self):
        return json.loads(self.path.read_text())

    def list_droplets_by_tag(self, tag):
        return [d for d in self._state()['droplets'].values() if tag in d['tags']]

    def get_droplet(self, droplet_id):
        return self._state()['droplets'].get(str(droplet_id))

    def get_firewall(self, firewall_id):
        return self._state()['firewalls'].get(str(firewall_id))

    def droplet_firewall_ids(self, droplet_id):
        return self._state()['attachments'].get(str(droplet_id), [])

    def image(self, image_id):
        return dict(id=image_id, name='24.04 (LTS) x64')


def local_conditions(session_id, hosts, source_sha, cap_s, recovery_grace_s=None):
    conditions = fx_conditions()
    session = conditions['session']
    session.update(id=session_id, ownership_tags=dict(session='omega-session:' + session_id, game='omega-role:game:' + session_id, bot='omega-role:bot:' + session_id))
    conditions['evidence']['local_root'] = 'loadtest-runs/digitalocean/' + session_id
    conditions['limits'].update(max_session_duration_s=cap_s)
    if recovery_grace_s is not None:
        conditions['limits'].update(evidence_recovery_grace_s=recovery_grace_s)
    source = conditions['source']
    programs = hosts.adapter.program_paths()
    source.update(benchmark_sha=source_sha, server_config_sha256=run_executor.sha256_path(hosts.adapter.config_path()),
                  binary_sha256=dict(game=run_executor.sha256_path(programs['game']), bot=run_executor.sha256_path(programs['bot'])))
    return conditions


def fx_conditions():
    import fixture_support
    return fixture_support.conditions()


class LocalSession:
    """A real registry CLI, a real watchdog process, real runner processes and stand-in workloads, on this machine, on real clocks."""
    SESSION = 'do-local-20261105a'

    def __init__(self, case, root, cap_s=14400, release_dir=None, recovery_grace_s=None, **adapter_options):
        import fake_provider
        import fixture_support as fx
        import manifest as manifest_mod
        import fault_harness
        self.case = case
        self.root = pathlib.Path(root)
        self.state = self.root / 'state'
        self.session_dir = self.root / 'session'
        self.session_dir.mkdir(parents=True)
        (self.session_dir / 'provisioning').mkdir()
        self.game_port, self.metrics_port = free_ports()
        self.hosts = install_local_hosts(self.root / 'hosts', self.game_port, self.metrics_port, **adapter_options)
        self.real_release = release_dir is not None
        if self.real_release:
            install_real_release(self.hosts, release_dir, self.metrics_port)
            self.hosts.adapter = RealReleaseAdapter(self.hosts.guests, self.game_port, self.metrics_port, **adapter_options)
        head = subprocess.run(['git', '-C', str(self.hosts.adapter.source_dir), 'rev-parse', 'HEAD'], stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        conditions = local_conditions(self.SESSION, self.hosts, head, cap_s, recovery_grace_s)
        if self.real_release:
            import measurement_window
            conditions['telemetry_schema'] = dict(id=measurement_window.schema()['id'], sha256=measurement_window.schema_sha256())
        self.manifest, self.sha = manifest_mod.freeze_manifest(conditions, fx.preflight(), fx.FROZEN_AT)
        (self.session_dir / 'manifest.json').write_text(manifest_mod.canonical_json(self.manifest))
        (self.session_dir / 'manifest.sha256').write_text(self.sha + '  manifest.json\n')
        registry.Registry.init(self.state, fx.REGISTRY_ID, fx.WATCHDOG_IDENTITY)
        self.account = self.root / 'account.json'
        fake_provider.FakeProvider(self.account).answer_all_requests()
        self.environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        self.watchdog = subprocess.Popen([sys.executable, str(HERE / 'registry_cli.py'), 'watchdog', '--state-dir', str(self.state), '--provider', 'fake_provider:from_file',
                                          '--provider-arg', str(self.account), '--allow-offline-fake', '--tick-interval-s', '0.05', '--sweep-interval-s', '0.3'],
                                         env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HERE))
        case.addCleanup(self._stop_watchdog)
        case.addCleanup(self.kill_every_process)
        case.addCleanup(make_writable, self.root)
        self.client = self.client_for('controller-a')
        self._arrange(fault_harness, fake_provider)

    def _stop_watchdog(self):
        if self.watchdog.poll() is None:
            self.watchdog.kill()
        self.watchdog.wait()

    def rpc_argv(self):
        return [sys.executable, str(HERE / 'registry_cli.py'), 'rpc', '--state-dir', str(self.state)]

    def client_for(self, name):
        import registry_client
        return registry_client.RegistryClient(registry_client.SubprocessTransport(self.rpc_argv()), name, attempts=2, retry_delay_s=0.05)

    def _await(self, predicate, limit_s=20.0):
        import time
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError('the local stack did not reach the expected state')

    def _arrange(self, fault_harness, fake_provider):
        client, sid = self.client, self.SESSION
        self._await(lambda: client.call('health')['watchdog']['healthy'])
        client.register(self.manifest, self.sha)
        self.token = client.acquire(sid)['fencing_token']
        self._await(lambda: client.call('health', session_id=sid)['watchdog']['acknowledged_manifest_sha256'] == self.sha)
        client.arm(sid, self.manifest, self.sha, self.token)
        provider = fake_provider.FakeProvider(self.account)
        create, find = fault_harness.create_for(provider), fault_harness.find_existing(provider, sid)
        ids = {}
        for intent in client.call('status', session_id=sid)['intents']:
            key = client.guarded_create(sid, intent['intent_id'], self.token, create, find)
            ids[intent['intent_id'].split(':', 1)[1]] = key.split(':', 1)[1]
        self._write_pair(ids)
        self._write_readiness()
        digest = run_executor.sha256_path(self.session_dir / 'provisioning' / 'readiness.json')
        client.mutate('mark_ready', session_id=sid, fencing_token=self.token, evidence_ref='provisioning/readiness.json#sha256:' + digest)

    def _write_pair(self, ids):
        import session_access
        spec, tags = self.manifest['roles'], self.manifest['session']['ownership_tags']
        self.addresses = dict(game='198.51.100.10', bot='198.51.100.11')
        droplets = {}
        for role in ('game', 'bot'):
            droplets[ids['droplet:' + role]] = dict(id=ids['droplet:' + role], name=self.SESSION + '-' + role, tags=[tags['session'], tags[role]], size_slug=spec[role]['size_slug'],
                                                    region=spec[role]['region'], image_id=spec[role]['image_id'], vcpus=spec[role]['vcpus'], memory_mib=spec[role]['memory_mib'],
                                                    disk_gib=spec[role]['disk_gib'], public_ipv4=[self.addresses[role]], status='active')
        allowlists = self.manifest['access_allowlists']
        firewall = session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'], self.addresses['bot'])
        firewall.update(id=ids['firewall'], status='succeeded', pending_changes=[])
        self.pair_file = self.root / 'pair.json'
        self.pair_file.write_text(json.dumps(dict(droplets=droplets, firewalls={ids['firewall']: firewall}, attachments={i: [ids['firewall']] for i in droplets})))

    def _write_readiness(self):
        roles = {}
        sampler = run_executor.sha256_path(self.hosts.adapter.sampler_path('game'))
        for role in ('game', 'bot'):
            roles[role] = dict(host_key=dict(address=self.addresses[role]),
                               observation=dict(clock=dict(boot_id=guest_runner.boot_id()), kernel='local', packages=dict(sha256='synthetic'), release={'sample_host.py': sampler}))
        (self.session_dir / 'provisioning' / 'readiness.json').write_text(json.dumps(dict(session_id=self.SESSION, roles=roles), sort_keys=True))

    def describe(self):
        """Everything a separate controller process needs. Holds no secret."""
        return dict(session=self.SESSION, session_dir=str(self.session_dir), rpc_argv=self.rpc_argv(), pair_file=str(self.pair_file), hosts_root=str(self.hosts.guests.root),
                    bin_dir=str(self.hosts.bin_dir), game_port=self.game_port, metrics_port=self.metrics_port, workload_seconds=self.hosts.adapter.workload_seconds,
                    game_extra=self.hosts.adapter.game_extra, bot_extra=self.hosts.adapter.bot_extra, real_release=self.real_release)

    def kill_every_process(self):
        """Nothing a fixture started may outlive it, whatever state a test left it in."""
        root = str(self.root)
        for line in guest_runner.process_table() or ():
            fields = line.split()
            if len(fields) > 1 and root in line and fields[0].isdigit() and int(fields[0]) != os.getpid():
                try:
                    os.kill(int(fields[0]), 9)
                except OSError:
                    pass

    def live_workloads(self):
        programs = list(self.hosts.adapter.program_paths().values())
        return [line for line in guest_runner.process_table() if any(program in line.split()[1:3] for program in programs)]

    def run_tree(self, role, run_id):
        return self.hosts.guests.runner_root(role) / 'runs' / run_id / role
