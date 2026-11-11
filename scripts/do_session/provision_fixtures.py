"""A whole offline session: registry, watchdog, real adapters over a fake account, fake guests, one scripted clock."""
import pathlib

import do_api
import fake_do_http
import fake_guest
import fixture_support as fx
import manifest as manifest_mod
import provisioner
import registry
import registry_client
import registry_fixtures as rf
import remote_authorization
import session_clock

SESSION = 'do-cap-1v1g-20261030a'
CAP_S = 14400


def authorization(manifest, sha, wall, **changes):
    packet = dict(
        schema=remote_authorization.SCHEMA, gate=remote_authorization.GATE_BY_KIND[manifest['session']['kind']], session_id=manifest['session']['id'],
        manifest_sha256=sha, operator_request_ref='offline-fixture: not a real authorization', max_pairs=1,
        not_before_utc=session_clock.iso(wall - 60), not_after_utc=session_clock.iso(wall + 7200),
        max_session_duration_s=manifest['limits']['max_session_duration_s'], max_estimated_session_usd=manifest['limits']['max_estimated_session_usd'],
        max_estimated_transfer_gib=manifest['limits']['max_estimated_transfer_gib'],
        scope_attestation=dict(scopes=list(remote_authorization.REQUIRED_CONTROLLER_SCOPES), attested_at=session_clock.iso(wall - 60),
                               controller_token_expires_at=session_clock.iso(wall + 86400 * 30), watchdog_token_expires_at=session_clock.iso(wall + 86400 * 30)))
    packet.update(changes)
    return packet


def session_of_kind(session_id, cap_s, kind, retained=(), telemetry_schema=None):
    if kind == 'capacity':
        return fx.session_manifest(session_id, cap_s=cap_s, retained=retained, telemetry_schema=telemetry_schema)
    conditions = fx.conditions()
    session = conditions['session']
    session.update(id=session_id, kind=kind, ownership_tags=dict(session='omega-session:' + session_id, game='omega-role:game:' + session_id,
                                                                 bot='omega-role:bot:' + session_id))
    conditions['evidence']['local_root'] = 'loadtest-runs/digitalocean/' + session_id
    conditions['limits'].update(max_session_duration_s=cap_s)
    return manifest_mod.freeze_manifest(conditions, fx.preflight(), fx.FROZEN_AT)


class Sim:
    TICK_S = 5.0

    def __init__(self, case, session_id=SESSION, cap_s=CAP_S, account_options=None, policy=None, kind='capacity', retained=(), typed_runs=False, telemetry_schema=None):
        self.stack = rf.Stack(case, typed_runs=typed_runs)
        self.clock = self.stack.clock
        self.case = case
        self.account = fake_do_http.FakeDoAccount(self.clock, **(account_options or {}))
        self.unrelated = self.account.seed_unrelated()
        self.watchdog_provider = do_api.DigitalOceanProvider(self.account, wall=self.clock.wall)
        self.stack.provider = self.watchdog_provider
        self.stack.watchdog = self.stack.new_watchdog()
        self.stack.watchdog.start(pid=1)
        self.stack.watchdog.tick()
        self.manifest, self.sha = session_of_kind(session_id, cap_s, kind, retained, telemetry_schema)
        self.session_id = session_id
        self.packet = authorization(self.manifest, self.sha, self.clock.wall())
        self.gate = remote_authorization.MutationGate(self.packet, self.manifest, self.sha, self.clock.wall)
        self.provider = do_api.DigitalOceanProvisioningProvider(self.account, gate=self.gate, wall=self.clock.wall)
        self.guests = fake_guest.FakeGuests(self)
        self.client = self.stack.client
        self.client.monotonic = self.monotonic
        self.evidence = provisioner.Evidence(self.stack.root / 'provisioning', self.clock.wall)
        self.public_key = fake_do_http.PUBLIC_KEY_PATH.read_text().strip()
        self.policy = policy
        self.armed_acks = []
        self.ready_acks = []

    def sleep(self, seconds):
        remaining = seconds
        while remaining > 0:
            step = min(remaining, self.TICK_S)
            self.clock.advance(step)
            self.account.advance_landings()
            self.stack.watchdog.tick()
            remaining -= step

    def monotonic(self):
        return self.clock.mono()

    def provisioner(self, client=None, provider=None, guests=None, packet=None):
        return provisioner.Provisioner(client or self.client, provider or self.provider, guests or self.guests, self.manifest, self.sha,
                                       self.packet if packet is None else packet, self.evidence, self.public_key, self.sleep, self.monotonic,
                                       self.clock.wall, policy=self.policy, new_nonce=lambda role: 'fixture-nonce-' + role + '-0123456789abcdef',
                                       on_armed=self.armed_acks.append, on_ready=lambda ack, ref: self.ready_acks.append((ack, ref)))

    def run(self, **options):
        return self.provisioner(**options).run()

    def status(self):
        return self.stack.registry.status(self.session_id)

    def closed(self):
        return self.status()['state'] == registry.CLOSED

    def drive_cleanup(self, limit_s=1200.0):
        self.stack.run_until(self.closed, limit_s=limit_s)
        return self.status()

    def step_cleanup(self, seconds):
        self.stack.step(seconds)

    def session_droplets(self):
        tag = self.manifest['session']['ownership_tags']['session']
        return sorted(str(i) for i, d in self.account.droplets.items() if tag in d['tags'])

    def unrelated_intact(self):
        live = self.account.live()
        return (all(str(i) in live['droplets'] for i in self.unrelated['droplets']) and self.unrelated['firewall'] in live['firewalls']
                and all(t in live['tags'] for t in self.unrelated['tags']))

    def session_mutation_targets_only(self):
        """Every delete named this session's exact resources, and nothing touched an unrelated id."""
        foreign = {'/v2/droplets/%d' % i for i in self.unrelated['droplets']} | {'/v2/firewalls/' + self.unrelated['firewall']}
        foreign |= {'/v2/tags/' + t for t in self.unrelated['tags']}
        return not [m for m in self.account.mutations() if m['path'] in foreign]

    def puts(self):
        return self.account.ops('PUT', '^/v2/firewalls/')

    def open_incidents(self, kind='ownership-mismatch'):
        return [i for i in self.stack.registry.incidents(self.session_id) if i['kind'] == kind and i['status'] == 'open']

    def creates(self, path):
        return self.account.ops('POST', '^' + path + '$')

    def evidence_lines(self):
        path = pathlib.Path(self.evidence.root) / 'journal.ndjson'
        return path.read_text().splitlines() if path.exists() else []


def client_for(sim, name):
    return registry_client.RegistryClient(registry_client.LocalTransport(sim.stack.registry), name, attempts=1, retry_delay_s=0, sleep=lambda _: None,
                                          monotonic=sim.monotonic)
