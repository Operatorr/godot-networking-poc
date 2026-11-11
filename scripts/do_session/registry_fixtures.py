"""A complete offline registry + watchdog + fake provider stack for the fault fixtures."""
import itertools
import logging
import pathlib
import shutil
import tempfile

import cleanup_provider
import create_evidence
import fake_provider
import fixture_support as fx
import registry
import registry_client
import watchdog


logging.getLogger('omega.do_watchdog').addHandler(logging.NullHandler())   # fixtures assert on logs explicitly


def outage():
    return cleanup_provider.ProviderTransient('503 service unavailable', status=503)


def auth_failure():
    return cleanup_provider.ProviderAuthError('401 unauthorized', status=401)


class Stack:
    def __init__(self, case, executor=None, provider_path=None, typed_runs=False, **watchdog_options):
        temporary = tempfile.TemporaryDirectory()
        case.addCleanup(temporary.cleanup)
        self.case = case
        self.root = pathlib.Path(temporary.name)
        self.state_dir = self.root / 'state'
        self.clock = fx.ScriptedClock()
        registry.Registry.init(self.state_dir, fx.REGISTRY_ID, fx.WATCHDOG_IDENTITY)
        self.failpoint = None
        self.typed_runs = typed_runs
        self.registry = self.open_registry()
        self.provider = fake_provider.FakeProvider(provider_path, clock=self.clock)
        self.executor = executor or watchdog.InlineExecutor()
        self.watchdog_options = watchdog_options
        self.watchdog = self.new_watchdog()
        self.watchdog.start(pid=1)
        self._ids = itertools.count(1)
        self.transport = registry_client.LocalTransport(self.registry)
        self.client = self.new_client('controller-a')

    def open_registry(self):
        reg = registry.Registry(self.state_dir, clock=self.clock, failpoint=lambda name: self.failpoint and self.failpoint(name),
                                trusted_settlement_bases=create_evidence.OFFLINE_FIXTURE_BASES, typed_runs=self.typed_runs)
        self.case.addCleanup(reg.close)
        return reg

    def new_watchdog(self, registry_=None, provider=None, executor=None):
        return watchdog.Watchdog(registry_ or self.registry, provider or self.provider, executor=executor or self.executor,
                                 **self.watchdog_options)

    def new_client(self, controller_id, transport=None):
        return registry_client.RegistryClient(transport or registry_client.LocalTransport(self.registry), controller_id,
                                              attempts=2, retry_delay_s=0, sleep=lambda _: None,
                                              new_request_id=lambda: controller_id + '-r' + str(next(self._ids)))

    def restart_watchdog(self, reboot=False, **reboot_options):
        """A crash or restart: all in-memory scheduling is lost, only the state directory remains."""
        if reboot:
            self.clock.reboot(**reboot_options)
        self.registry = self.open_registry()
        self.executor = self.executor if not isinstance(self.executor, fx.DeferredExecutor) else fx.DeferredExecutor()
        self.watchdog = self.new_watchdog()
        self.watchdog.start(pid=2)
        self.client.transport = registry_client.LocalTransport(self.registry)
        return self.watchdog

    def step(self, seconds=1.0, tick_interval=1.0):
        """Advance scripted time, ticking the watchdog at its normal interval."""
        elapsed = 0.0
        while elapsed < seconds:
            self.clock.advance(tick_interval)
            elapsed += tick_interval
            self.watchdog.tick()

    def run_until(self, predicate, limit_s=1200.0, tick_interval=1.0):
        elapsed = 0.0
        while not predicate():
            self.case.assertLess(elapsed, limit_s, 'condition was not reached in scripted time')
            self.step(tick_interval, tick_interval)
            elapsed += tick_interval
        return elapsed

    # ---- session construction ----------------------------------------------------------------

    def registered(self, session_id='do-cap-1v1g-20261030a', client=None, **limits):
        manifest, sha = fx.session_manifest(session_id, **limits)
        client = client or self.client
        client.register(manifest, sha)
        control = client.acquire(session_id)
        return manifest, sha, control['fencing_token']

    def armed(self, session_id='do-cap-1v1g-20261030a', client=None, **limits):
        client = client or self.client
        manifest, sha, token = self.registered(session_id, client=client, **limits)
        self.watchdog.tick()
        ack = client.arm(session_id, manifest, sha, token)
        self.watchdog.tick()
        return manifest, sha, token, ack

    def create_pair(self, session_id, token, client=None):
        """Every intent of the session, through the guarded create path. Returns resource ids."""
        client = client or self.client
        tags = fx_tags(session_id)
        ids = {}
        for role in ('session', 'game', 'bot'):
            client.guarded_create(session_id, session_id + ':tag:' + role, token,
                                  lambda grant, r=role: (self.provider.add_tag(tags[r]), tags[r])[1], lambda grant: None)
        ids['firewall'] = client.guarded_create(session_id, session_id + ':firewall', token,
                                                lambda grant: self.provider.add_firewall(grant['expected_name'], tags=grant['expected_tags']),
                                                lambda grant: None)
        for role in ('game', 'bot'):
            ids[role] = client.guarded_create(session_id, session_id + ':droplet:' + role, token,
                                              lambda grant: self.provider.add_droplet(grant['expected_name'], grant['expected_tags']),
                                              lambda grant: None)
        return ids

    def ready(self, session_id='do-cap-1v1g-20261030a', client=None, **limits):
        client = client or self.client
        manifest, sha, token, ack = self.armed(session_id, client=client, **limits)
        ids = self.create_pair(session_id, token, client=client)
        client.mutate('mark_ready', session_id=session_id, fencing_token=token, evidence_ref='readiness/fake.json')
        return manifest, sha, token, ack, ids

    def closed(self, session_id):
        return self.registry.status(session_id)['state'] == registry.CLOSED

    def state_bytes(self):
        """Every persisted byte under the state directory, for secret scans."""
        return b''.join(path.read_bytes() for path in sorted(self.state_dir.rglob('*')) if path.is_file())

    def copy_state_to(self, target):
        shutil.copytree(self.state_dir, target)
        return target


def fx_tags(session_id):
    return dict(session='omega-session:' + session_id, game='omega-role:game:' + session_id,
                bot='omega-role:bot:' + session_id)
