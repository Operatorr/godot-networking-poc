"""From an admitted session to a verified ready pair, or to ownership-safe cleanup (handoff slice 3, issue #66).

    run
      authorization, fresh facts, register, watchdog ack, fresh facts again, admission, arm (t0/D/C frozen here)
      tags -> firewall -> game -> bot, each behind one durable intent
      converge, assign to the project, final firewall with the bot's exact address, exact inventory (ownership read each time)
      first contact pins host keys -> cloud-init -> clean locked build -> release on both roles
      observations, sampler, cross-host ENet smoke, reset, exact inventory, firewall unchanged
      mark_ready, or request_cleanup with the reason

Failing stops the batch: nothing is repaired in place and no pair is replaced, so every failure path ends in
``request_cleanup`` and the watchdog deletes what the session owns. The deadline never moves. If cleanup cannot be
requested, C still arrives on the management host.

A create with an unknown outcome gets no retry. The controller watches for the resource for a bounded time, and if it
appears it is adopted; otherwise the session stops with the request still unresolved, which keeps protection in place
and refuses a clean closure. Time spent watching settles nothing (see README "Create settlement").

A restarted controller never resumes a half-bootstrapped pair. Its host-binding nonces lived only in the earlier
process, so it cannot verify first contact, and arming again is refused. It requests cleanup. Cold bootstrap has no
partial credit to preserve.
"""
import dataclasses
import hashlib
import json
import pathlib
import secrets
import tempfile

import admission
import cleanup_provider
import create_evidence
import guest_bootstrap
import manifest as manifest_mod
import provider_preflight
import readiness
import registry
import registry_client
import remote_authorization
import resource_ownership
import search
import session_access
import session_clock
import ssh_access

ROLES = ('game', 'bot')
AGENT_SOURCE = pathlib.Path(__file__).with_name('guest_agent.py')
AGENT_REMOTE = '/home/deploy/omega-agent/guest_agent.py'
AGENT_INCOMING = '/home/deploy/omega-agent/incoming'
READY, REJECTED, ABORTED, ABORT_UNACKNOWLEDGED = 'ready', 'rejected', 'aborted', 'abort_unacknowledged'
RENEW_EVERY_S = 30.0


@dataclasses.dataclass(frozen=True)
class Policy:
    """Local waits. None of these is a claim about the provider: when one runs out the session stops, nothing is settled."""
    watchdog_ack_wait_s: float = 30.0
    reconcile_observe_s: float = 120.0
    reconcile_poll_s: float = 10.0
    provider_poll_s: float = 5.0
    firewall_apply_wait_s: float = 120.0
    host_contact_wait_s: float = 600.0
    host_contact_poll_s: float = 5.0
    assign_attempts: int = 3
    firewall_update_attempts: int = 4
    cloud_init_timeout_s: int = 600
    fetch_timeout_s: int = 300
    build_timeout_s: int = 1800
    relay_timeout_s: int = 300
    step_timeout_s: int = 90
    smoke_timeout_s: int = 60


@dataclasses.dataclass
class Result:
    status: str
    session_id: str
    code: str = None
    detail: str = None
    droplets: dict = dataclasses.field(default_factory=dict)
    firewall_id: str = None
    fencing_token: int = None
    evidence_ref: str = None


class Stop(Exception):
    """The session cannot become ready. ``code`` is stable and machine-readable; ``detail`` is for people."""

    def __init__(self, code, detail=''):
        super().__init__(code + ': ' + str(detail))
        self.code = code
        self.detail = str(detail)


class Refused(Stop):
    """Refused before t0. Nothing exists at the provider for this session, so it normally closes with no resources."""

    def __init__(self, code, detail='', keep_registered=False):
        super().__init__(code, detail)
        self.keep_registered = keep_registered


class ControlLost(Stop):
    """This controller no longer holds the session: stop touching anything, and leave cleanup to its holder."""


class OwnershipConflict(Stop):
    """A recorded resource is no longer what this session alone could have left it as. Report it and leave it alone."""

    def __init__(self, resource_key, problems, observed_name=None):
        super().__init__('ownership_conflict', resource_key + ': ' + '; '.join(problems))
        self.resource_key = resource_key
        self.problems = list(problems)
        self.observed_name = observed_name


def report_conflict(client, session_id, conflict, record):
    """Durable before anything else happens to the session. If the registry cannot take it, the watchdog's read still will."""
    try:
        client.mutate('report_ownership_conflict', session_id=session_id, resource_key=conflict.resource_key, problems=conflict.problems,
                      observed_name=conflict.observed_name)
    except (registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
        record('ownership_conflict_unreported', resource_key=conflict.resource_key, detail=cleanup_provider.redact(error))
    record('ownership_conflict', resource_key=conflict.resource_key, problems=conflict.problems)


def require_control(client, provider, session_id, fencing_token, wall):
    """Fresh proof that this controller may still change anything: fence, lease, cleanup, C. Never throttled.

    Renewing raises when the token is stale or the lease has lapsed. The registry's current record of owned resources
    then becomes the adapter's only authority to name an exact id. This answers for the moment it was asked, so callers
    ask again after any wait or slow read and immediately before each mutation.
    """
    client.call('renew_control', session_id=session_id, fencing_token=fencing_token)
    status = client.call('status', session_id=session_id)
    if status['state'] in (registry.DELETING, registry.CLOSED) or status['cleanup']['requested_at'] is not None:
        raise ControlLost('cleanup_in_progress', 'the session entered ' + status['state'])
    if status['cleanup_c_utc'] is not None and wall() >= session_clock.parse(status['cleanup_c_utc']):
        raise ControlLost('deadline_reached', 'the session reached C at ' + status['cleanup_c_utc'])
    provider.bind_owned(status['resources'])
    return status


def droplet_conflict(manifest, droplet_id, droplet):
    """Exactly the policy that decides whether the watchdog could ever delete this Droplet."""
    key = resource_ownership.resource_key('droplet', droplet_id)
    problems = resource_ownership.droplet_problems(manifest, key, droplet)
    return OwnershipConflict(key, problems, droplet.get('name')) if problems else None


class Evidence:
    """Create-only artifacts and one append-only journal under the session's ``provisioning/`` directory.

    Everything is scanned first, and registered sensitive values are checked as well, so a bootstrap nonce or a
    credential cannot reach retained evidence even by accident.
    """

    def __init__(self, root, wall):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.wall = wall
        self.sensitive = []

    def _text(self, value):
        text = manifest_mod.canonical_json(value)
        if manifest_mod.scan_for_secrets(value) or any(item in text for item in self.sensitive):
            raise Stop('evidence_secret_refused', 'an evidence record contained a sensitive value and was not written')
        return text

    def event(self, kind, **data):
        line = self._text(dict(at=session_clock.iso(self.wall()), kind=kind, **data))
        with (self.root / 'journal.ndjson').open('a', encoding='utf-8') as handle:
            handle.write(line)

    def artifact(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self._text(value)
        with path.open('x', encoding='utf-8') as handle:
            handle.write(text)
        return path


class Provisioner:
    def __init__(self, client, provider, guests, manifest, manifest_sha256, authorization, evidence, public_key, sleep, monotonic,
                 wall, policy=None, new_nonce=None, on_armed=None, on_ready=None):
        self.client = client
        self.provider = provider
        self.guests = guests
        self.manifest = manifest
        self.sha = manifest_sha256
        self.authorization = authorization
        self.evidence = evidence
        self.public_key = public_key
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall = wall
        self.policy = policy or Policy()
        self.new_nonce = new_nonce or (lambda role: secrets.token_hex(32))
        self.on_armed = on_armed
        self.on_ready = on_ready
        session = manifest['session']
        self.session_id = session['id']
        self.tags = session['ownership_tags']
        self.token = None
        self.armed = False
        self.budget_ends = None
        self.next_renew = None
        self.nonces = {}
        self.droplets = {}
        self.firewall_id = None
        self.facts = None
        self.report = dict(schema='omega.do-session.readiness/1', session_id=self.session_id, manifest_sha256=manifest_sha256, roles={})

    # ---- the whole path ----------------------------------------------------------------------

    def run(self):
        try:
            self._pre_create()
            self._arm()
            self._create_resources()
            self._converge_droplets()
            self._assign_project()
            self._apply_final_firewall()
            self._check_inventory()
            self._bootstrap()
            self._verify_ready()
            return self._mark_ready()
        except Stop as stop:
            return self._stop(stop)
        except registry_client.RegistryRejected as rejection:
            return self._stop(self._rejection_stop(rejection))
        except registry_client.RegistryUnavailable as error:
            return self._stop(Stop('registry_unavailable', error))
        except cleanup_provider.ProviderError as error:
            return self._stop(Stop('provider_error', type(error).__name__ + ': ' + cleanup_provider.redact(error)))
        except create_evidence.CreateNotSent as error:
            return self._stop(Stop('mutation_refused', cleanup_provider.redact(error)))
        except (session_access.AccessRefused, guest_bootstrap.BootstrapRefused) as error:
            return self._stop(Stop('bootstrap_refused', error))
        except OSError as error:
            return self._stop(Stop('local_failure', type(error).__name__))
        except Exception as error:     # resources may exist and bill by the hour, so even a defect asks for cleanup now
            return self._stop(Stop('internal_error', type(error).__name__))

    def _record(self, kind, **data):
        """While stopping, a failed evidence write must not prevent the cleanup request."""
        try:
            self.evidence.event(kind, **data)
        except (OSError, Stop):
            pass

    def _rejection_stop(self, rejection):
        if rejection.code in ('stale_fencing_token', 'lease_expired', 'control_held'):
            if not self.armed:
                return Refused('control_unavailable', rejection)
            return ControlLost('control_lost', rejection)
        if rejection.code == 'deadline_capacity_exceeded':
            # Other sessions hold the watchdog's slots for now, so the same session id may arm later.
            return Refused('deadline_capacity_exceeded', 'arming again fits after %s s' % rejection.details.get('retry_after_s'), keep_registered=True)
        if not self.armed:
            return Refused('registry_refused_' + rejection.code, rejection)
        return Stop('registry_refused_' + rejection.code, rejection)

    def _result(self, status, stop=None, evidence_ref=None):
        droplets = {role: item['id'] for role, item in self.droplets.items()}
        return Result(status, self.session_id, stop.code if stop else None, stop.detail if stop else None, droplets,
                      self.firewall_id, self.token, evidence_ref)

    def _stop(self, stop):
        """Stop the batch. Refused before t0 closes a registered session with no resources; later, cleanup takes over."""
        if isinstance(stop, ControlLost):
            self._record('control_lost', code=stop.code, detail=stop.detail)
            return self._result(ABORTED, stop)
        self._record('stopping', code=stop.code, detail=stop.detail, armed=self.armed)
        if isinstance(stop, OwnershipConflict):
            report_conflict(self.client, self.session_id, stop, self._record)
        if self.token is None or getattr(stop, 'keep_registered', False):
            return self._result(REJECTED, stop)
        try:
            self.client.mutate('request_cleanup', session_id=self.session_id, fencing_token=self.token, reason='provisioning: ' + stop.code)
        except (registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
            # The watchdog still deletes by C. This outcome only says that nobody acknowledged the early start.
            self._record('cleanup_request_unacknowledged', detail=str(error))
            return self._result(ABORT_UNACKNOWLEDGED, stop)
        self._record('cleanup_requested', code=stop.code)
        return self._result(ABORTED if self.armed else REJECTED, stop)

    # ---- before t0: nothing can exist yet -----------------------------------------------------

    def _refresh_facts(self, require_watchdog_ack):
        try:
            self.facts = provider_preflight.collect(self.provider, self.manifest, self.wall)
        except provider_preflight.PreflightUnavailable as error:
            raise Refused('provider_facts_unavailable', error)
        health = self.client.call('health', session_id=self.session_id)
        reasons = provider_preflight.problems(self.manifest, self.facts, health, self.wall(), require_watchdog_ack=require_watchdog_ack)
        self.evidence.event('provider_facts', observed_at=self.facts['observed_at'], collisions=self.facts['collisions'],
                            account=self.facts['account'], problems=reasons)
        if reasons:
            raise Refused('preflight_refused', '; '.join(reasons))
        return health

    def _require_authorized(self):
        reasons = remote_authorization.validate(self.authorization, self.manifest, self.sha, self.wall())
        if reasons:
            raise Refused('authorization_refused', '; '.join(reasons))
        self.evidence.event('remote_authorization', gate=self.authorization['gate'], operator_request_ref=self.authorization['operator_request_ref'])

    def _require_renderable(self):
        """Bad allowlists or a wrong key are refused now, while nothing exists and no deadline is running."""
        allowlists = self.manifest['access_allowlists']
        try:
            session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'])
            for role in ROLES:
                guest_bootstrap.render_user_data(self.manifest, role, self.public_key, 'validation-only')
        except (session_access.AccessRefused, guest_bootstrap.BootstrapRefused, ValueError) as error:
            raise Refused('bootstrap_refused', error)

    def _refuse_earlier_session(self):
        """Session ids are single-use. An armed one was this session's earlier controller, and it may own resources."""
        try:
            status = self.client.call('status', session_id=self.session_id)
        except registry_client.RegistryRejected as rejection:
            if rejection.code == 'unknown_session':
                return
            raise
        if status['state'] == registry.CLOSED:
            raise Refused('session_already_closed', 'a closed session is never provisioned again')
        if status['t0_utc'] is not None:
            self.token = self.client.acquire(self.session_id)['fencing_token']
            self.armed = True
            raise Stop('restart_fails_closed', 'a restarted controller never resumes a half-bootstrapped pair')

    def _pre_create(self):
        self._require_authorized()
        self._require_renderable()
        self._refuse_earlier_session()
        self._refresh_facts(require_watchdog_ack=False)
        self.client.register(self.manifest, self.sha)
        self.token = self.client.acquire(self.session_id)['fencing_token']
        self.next_renew = self.monotonic() + RENEW_EVERY_S
        self._await_manifest_ack()
        health = self._refresh_facts(require_watchdog_ack=True)
        self._require_admitted(health)

    def _require_admitted(self, health):
        """A capacity session must fit its whole search. Others carry no search yet, so setup and teardown must fit."""
        if self.manifest['session']['kind'] == 'capacity':
            verdict = admission.admit(self.manifest, self.sha, search.SearchState(self.session_id), session_clock.iso(self.wall()), health)
            reasons, decision = verdict.reasons, verdict.decision
            admitted = verdict.admitted
        else:
            reasons = bounded_setup_problems(self.manifest)
            admitted, decision = not reasons, 'bounded_setup'
        self.evidence.event('admission', decision=decision, reasons=reasons)
        if not admitted:
            raise Refused('admission_refused', '; '.join(reasons))

    def _await_manifest_ack(self):
        deadline = self.monotonic() + self.policy.watchdog_ack_wait_s
        while True:
            watchdog = self.client.call('health', session_id=self.session_id)['watchdog']
            if watchdog.get('acknowledged_manifest_sha256') == self.sha:
                return
            if self.monotonic() >= deadline:
                raise Refused('watchdog_unacknowledged', 'no watchdog acknowledged this manifest')
            self.sleep(1.0)

    def _arm(self):
        ack = self.client.arm(self.session_id, self.manifest, self.sha, self.token)
        self.armed = True
        timing = self.manifest['timing_basis']
        self.budget_ends = self.monotonic() + timing['create_bootstrap_s']['seconds'] + timing['readiness_access_s']['seconds']
        self.evidence.event('armed', t0_utc=ack['t0_utc'], cleanup_c_utc=ack['cleanup_c_utc'], deadline_d_utc=ack['deadline_d_utc'])
        if self.on_armed is not None:
            self.on_armed(ack)

    # ---- staying in charge --------------------------------------------------------------------

    def _keepalive(self):
        """Renew the lease and notice cleanup. Called from every wait, including SSH commands that run for minutes."""
        now = self.monotonic()
        if self.budget_ends is not None and now >= self.budget_ends:
            raise Stop('provisioning_budget_exhausted', 'the declared create/bootstrap/readiness bound ran out')
        if self.next_renew is None or now < self.next_renew:
            return
        self.next_renew = now + RENEW_EVERY_S
        self.client.call('renew_control', session_id=self.session_id, fencing_token=self.token)
        state = self.client.call('status', session_id=self.session_id)['state']
        if state in (registry.DELETING, registry.CLOSED):
            raise ControlLost('cleanup_started_elsewhere', 'the session entered ' + state)

    def _authorize_mutation(self):
        """The unthrottled form of ``_keepalive``, for just before a change and after anything slow."""
        if self.budget_ends is not None and self.monotonic() >= self.budget_ends:
            raise Stop('provisioning_budget_exhausted', 'the declared create/bootstrap/readiness bound ran out')
        require_control(self.client, self.provider, self.session_id, self.token, self.wall)
        self.next_renew = self.monotonic() + RENEW_EVERY_S

    def _wait(self, seconds):
        self.sleep(seconds)
        self._keepalive()

    # ---- creates ------------------------------------------------------------------------------

    def _intent_rows(self):
        return registry.session_intents(self.manifest)

    def _find_for(self, intent):
        """Look up by unique tag or exact name. A hit that fails an ownership check is refused, never adopted."""
        def find(grant):
            if intent['kind'] == 'tag':
                return intent['expected_name'] if self.provider.get_tag(intent['expected_name']) is not None else None
            if intent['kind'] == 'firewall':
                matches = self.provider.list_firewalls_by_name(intent['expected_name'])
                for firewall in matches:
                    if sorted(firewall['tags']) != sorted(intent['expected_tags']) or firewall['droplet_ids']:
                        raise Stop('ownership_ambiguous', 'a firewall has the session name but other targets')
                return matches[0]['id'] if matches else None
            matches = [d for d in self.provider.list_droplets_by_tag(self.tags['session']) if d['name'] == intent['expected_name']]
            for droplet in matches:
                problems = resource_ownership.droplet_problems(self.manifest, resource_ownership.resource_key('droplet', droplet['id']), droplet)
                if problems:
                    raise Stop('ownership_ambiguous', 'a droplet has the session tag and name but: ' + '; '.join(problems))
            return matches[0]['id'] if matches else None
        return find

    def _settlement(self, grant):
        return self.provider.get_request_settlement(grant['create_request_ref'])

    def _request_for(self, intent):
        """Built before the grant: a local refusal here must never be mistaken for a request of unknown outcome."""
        if intent['kind'] == 'tag':
            return None
        if intent['kind'] == 'firewall':
            allowlists = self.manifest['access_allowlists']
            return session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'])
        return self._droplet_request(intent['role'])

    def _create_for(self, intent, payload):
        def create(grant):
            limits = dict(request_bound_s=grant['create_request_timeout_s'], send_by=grant['send_by_monotonic'])
            if intent['kind'] == 'tag':
                return self.provider.create_tag(intent['expected_name'], **limits)
            if intent['kind'] == 'firewall':
                return self.provider.create_firewall(payload, **limits)
            return self.provider.create_droplet(payload, **limits)
        return create

    def _droplet_request(self, role):
        spec = self.manifest['roles'][role]
        nonce = self.new_nonce(role)
        self.nonces[role] = nonce
        self.evidence.sensitive.append(nonce)
        user_data = guest_bootstrap.render_user_data(self.manifest, role, self.public_key, nonce)
        self.evidence.event('user_data', role=role, sha256=hashlib.sha256(user_data.encode('utf-8')).hexdigest(),
                            bytes=len(user_data.encode('utf-8')))
        return dict(name=self.session_id + '-' + role, region=spec['region'], size=spec['size_slug'], image=spec['image_id'],
                    ssh_keys=[self.manifest['ssh_key']['id']], tags=[self.tags['session'], self.tags[role]], backups=False, ipv6=False,
                    monitoring=False, with_droplet_agent=False, user_data=user_data)

    def _guarded(self, intent, create):
        """Tolerates only the short wait for the watchdog to acknowledge the armed deadline."""
        deadline = self.monotonic() + self.policy.watchdog_ack_wait_s
        while True:
            try:
                return self.client.guarded_create(self.session_id, intent['intent_id'], self.token, create, self._find_for(intent),
                                                  settlement_fn=self._settlement)
            except registry_client.RegistryRejected as rejection:
                if rejection.code not in ('watchdog_unacknowledged', 'watchdog_unhealthy') or self.monotonic() >= deadline:
                    raise
            self._wait(1.0)

    def _create_resources(self):
        for intent in self._intent_rows():
            key = self._create_one(intent)
            self.evidence.event('resource_created', intent_id=intent['intent_id'], resource_key=key)
            provider_id = key.split(':', 1)[1]
            if intent['kind'] == 'firewall':
                self.firewall_id = provider_id
                self._verify_initial_firewall()
            elif intent['kind'] == 'droplet':
                self.droplets[intent['role']] = dict(id=provider_id)

    def _create_one(self, intent):
        self._keepalive()
        try:
            return self._guarded(intent, self._create_for(intent, self._request_for(intent)))
        except create_evidence.CreateRejected as rejected:
            raise Stop('create_rejected', intent['intent_id'] + ': ' + cleanup_provider.redact(rejected))
        except remote_authorization.MutationRefused as refused:
            raise Stop('mutation_refused', cleanup_provider.redact(refused))
        except create_evidence.CreateNotSent as not_sent:
            raise Stop('create_not_sent', intent['intent_id'] + ': ' + cleanup_provider.redact(not_sent))
        except registry_client.CreateGrantExpired as expired:
            raise Stop('create_not_sent', str(expired))
        except (cleanup_provider.ProviderError, registry_client.CreateUnresolved) as error:
            self.evidence.event('create_outcome_unknown', intent_id=intent['intent_id'], detail=cleanup_provider.redact(error))
            return self._observe_unknown_create(intent)

    def _observe_unknown_create(self, intent):
        """Watch for a landing. Nothing here can send a request, and running out of time settles nothing."""
        def never_send(grant):
            raise create_evidence.CreateNotSent('observation never sends')

        deadline = self.monotonic() + self.policy.reconcile_observe_s
        while True:
            try:
                key = self._guarded(intent, never_send)
                self.evidence.event('create_landed', intent_id=intent['intent_id'], resource_key=key)
                return key
            except registry_client.CreateUnresolved:
                pass
            except create_evidence.CreateNotSent:
                raise Stop('create_outcome_unknown', intent['intent_id'] + ' was reported settled with no resource')
            except cleanup_provider.ProviderError as error:
                self.evidence.event('reconcile_read_failed', intent_id=intent['intent_id'], detail=cleanup_provider.redact(error))
            if self.monotonic() >= deadline:
                raise Stop('create_outcome_unknown', intent['intent_id'] + ' has no evidence either way')
            self._wait(self.policy.reconcile_poll_s)

    def _verify_initial_firewall(self):
        allowlists = self.manifest['access_allowlists']
        desired = session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'])
        actual = self.provider.get_firewall(self.firewall_id)
        problems = ['firewall is not readable'] if actual is None else session_access.firewall_problems(actual, desired)
        problems += resource_ownership.retained_problems(self.manifest, resource_ownership.resource_key('firewall', self.firewall_id))
        if actual is not None and actual.get('status') == 'failed':
            problems.append('firewall status is failed')
        if problems:
            raise Stop('firewall_verification_failed', '; '.join(problems))

    # ---- from created to correct --------------------------------------------------------------

    def _converge_droplets(self):
        for role in ROLES:
            droplet = self._await_active(role)
            conflict = droplet_conflict(self.manifest, droplet['id'], droplet)
            if conflict is not None:
                self.evidence.event('droplet_ownership_refused', role=role, droplet=droplet, problems=conflict.problems)
                raise conflict
            problems = readiness.droplet_problems(self.manifest, role, droplet)
            self.evidence.event('droplet_verified', role=role, droplet=droplet, problems=problems)
            if problems:
                raise Stop('wrong_plan', '; '.join(problems))
            self.droplets[role] = droplet
            self.report['roles'].setdefault(role, {})['droplet'] = droplet

    def _await_active(self, role):
        identifier = self.droplets[role]['id']
        while True:
            self._keepalive()
            try:
                droplet = self.provider.get_droplet(identifier)
            except cleanup_provider.ProviderAuthError:
                raise
            except cleanup_provider.ProviderError as error:
                self.evidence.event('droplet_read_failed', role=role, detail=cleanup_provider.redact(error))
            else:
                if droplet is None:
                    raise Stop('droplet_vanished', role + ' droplet ' + identifier + ' is gone')
                if droplet['status'] == 'active' and droplet['public_ipv4']:
                    return droplet
            self._wait(self.policy.provider_poll_s)

    def _assign_project(self):
        project = self.manifest['session']['project_id']
        for role in ROLES:
            identifier = self.droplets[role]['id']
            for attempt in range(self.policy.assign_attempts):
                try:
                    self._authorize_mutation()
                    droplet = self.provider.get_droplet(identifier)
                    if droplet is None:
                        raise Stop('droplet_vanished', role + ' droplet ' + identifier + ' is gone')
                    conflict = droplet_conflict(self.manifest, identifier, droplet)
                    if conflict is not None:
                        raise conflict
                    self._authorize_mutation()      # that read may have been slow
                    self.provider.assign_droplet(project, identifier)
                    if 'do:droplet:' + identifier in self.provider.project_resource_urns(project):
                        self.evidence.event('project_assigned', role=role, attempts=attempt + 1)
                        break
                    last = 'the project does not list the droplet'
                except remote_authorization.MutationRefused:
                    raise
                except cleanup_provider.ProviderError as error:
                    last = cleanup_provider.redact(error)
                self._wait(self.policy.provider_poll_s)
            else:
                raise Stop('project_assignment_failed', role + ': ' + last)

    def desired_firewall(self):
        allowlists = self.manifest['access_allowlists']
        return session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'],
                                               self.droplets['bot']['public_ipv4'][0])

    def _apply_final_firewall(self):
        self._require_owned_droplets()
        desired = self.desired_firewall()
        outcome = apply_firewall(self.provider, self.manifest, self.firewall_id, desired, self.sleep, self.monotonic, self.policy, self._authorize_mutation)
        if outcome['problems']:
            raise Stop('firewall_verification_failed', '; '.join(outcome['problems']))
        for role in ROLES:
            applied = self.provider.droplet_firewall_ids(self.droplets[role]['id'])
            if applied != [self.firewall_id]:
                raise Stop('firewall_verification_failed', '%s droplet is under firewalls %s' % (role, applied))
        self.report['firewall'] = dict(id=self.firewall_id, inbound_rules=outcome['firewall']['inbound_rules'],
                                       tags=outcome['firewall']['tags'], status=outcome['firewall']['status'])
        self.evidence.event('firewall_applied', firewall_id=self.firewall_id, attempts=outcome['attempts'])

    def _require_owned_droplets(self):
        """Both Droplets, as they are now, by the watchdog's policy. Returns everything the session tag lists."""
        listed = self.provider.list_droplets_by_tag(self.tags['session'])
        for role in ROLES:
            identifier = self.droplets[role]['id']
            droplet = next((d for d in listed if d['id'] == identifier), None)
            if droplet is None:
                raise OwnershipConflict(resource_ownership.resource_key('droplet', identifier), ['droplet no longer carries the unique session tag'])
            conflict = droplet_conflict(self.manifest, identifier, droplet)
            if conflict is not None:
                raise conflict
        return listed

    def _check_inventory(self):
        """Exactly what this session asked for. Anything else is recorded, so it is owned and cleaned, then we stop."""
        expected = {self.droplets[role]['id'] for role in ROLES}
        extras = [d for d in self._require_owned_droplets() if d['id'] not in expected]
        for droplet in extras:
            intent = next((i['intent_id'] for i in self._intent_rows() if i['kind'] == 'droplet' and i['expected_name'] == droplet['name']), None)
            self.client.mutate('record_resource', session_id=self.session_id, kind='droplet', provider_id=droplet['id'],
                               intent_id=intent, name=droplet['name'])
        firewalls = [f['id'] for f in self.provider.list_firewalls_by_name(self.session_id + '-fw')]
        for extra in [f for f in firewalls if f != self.firewall_id]:
            self.client.mutate('record_resource', session_id=self.session_id, kind='firewall', provider_id=extra, name=self.session_id + '-fw')
        if extras or firewalls != [self.firewall_id]:
            raise Stop('unexpected_resource', 'droplets %s, firewalls %s' % ([d['id'] for d in extras], firewalls))
        self.evidence.event('inventory_exact', droplets=sorted(expected), firewall=self.firewall_id)

    # ---- guests -------------------------------------------------------------------------------

    def _bounded(self, seconds):
        return max(1, int(min(seconds, self.budget_ends - self.monotonic())))

    def _agent(self, role, step, *arguments, timeout_s=None):
        """One agent subcommand. A nonzero exit, a timeout or unreadable output means the step failed."""
        timeout = self._bounded(timeout_s or self.policy.step_timeout_s)
        argv = ['python3', AGENT_REMOTE, step] + [str(a) for a in arguments]
        result = self.guests.run(role, argv, timeout, self._keepalive)
        if result.returncode != 0:
            raise Stop('bootstrap_failed', '%s %s exited %s: %s' % (role, step, result.returncode, cleanup_provider.redact(result.stderr)))
        try:
            document = json.loads(result.stdout)
        except ValueError:
            raise Stop('bootstrap_failed', '%s %s printed no JSON document' % (role, step))
        if manifest_mod.scan_for_secrets(document):
            raise Stop('bootstrap_failed', '%s %s reported a credential value' % (role, step))
        return document

    def _transfer(self, method, role, source, target):
        result = method(role, source, target, self._bounded(self.policy.relay_timeout_s), self._keepalive)
        if result.returncode != 0:
            raise Stop('bootstrap_failed', '%s copy to %s failed: %s' % (role, target, cleanup_provider.redact(result.stderr)))

    def _first_contact(self, role):
        address = self.droplets[role]['public_ipv4'][0]
        deadline = self.monotonic() + self.policy.host_contact_wait_s
        while True:
            try:
                pin = self.guests.pin_host(role, address, self.nonces[role])
            except ssh_access.HostVerificationFailed as failure:
                raise Stop('host_verification_failed', failure)
            except ssh_access.HostNotReady as waiting:
                if self.monotonic() >= deadline:
                    raise Stop('bootstrap_failed', waiting)
                self._wait(self.policy.host_contact_poll_s)
                continue
            self.evidence.event('host_pinned', role=role, **pin)
            self.report['roles'].setdefault(role, {})['host_key'] = pin
            return

    def _bootstrap(self):
        for role in ROLES:
            self._first_contact(role)
            if self.guests.run(role, ['mkdir', '-p', AGENT_INCOMING], self._bounded(self.policy.step_timeout_s), self._keepalive).returncode != 0:
                raise Stop('bootstrap_failed', role + ' could not create its agent directory')
            self._transfer(self.guests.put, role, str(AGENT_SOURCE), AGENT_REMOTE)
            self.report['roles'][role]['agent_sha256'] = hashlib.sha256(AGENT_SOURCE.read_bytes()).hexdigest()
            status = self._agent(role, 'wait_cloud_init', '--timeout-s', self.policy.cloud_init_timeout_s, timeout_s=self.policy.cloud_init_timeout_s + 30)
            self.report['roles'][role]['cloud_init'] = status
            if status.get('rc') != 0 or status.get('status') != 'done':
                raise Stop('bootstrap_failed', '%s cloud-init ended %s' % (role, status.get('status')))
        self._build_on_bot()
        self._relay_to_game()

    def _build_on_bot(self):
        """The fixed generator builds both binaries. A 1 GiB game host stays untouched by a compiler and its memory use."""
        source = self.manifest['source']
        fetched = self._agent('bot', 'fetch_source', '--sha', source['benchmark_sha'], '--timeout-s', self.policy.fetch_timeout_s,
                              timeout_s=self.policy.fetch_timeout_s + 30)
        flags = ['--flag=' + flag for flag in source['build_flags']]
        built = self._agent('bot', 'build', '--toolchain', source['rust_toolchain'], '--target', source['target_triple'],
                            '--timeout-s', self.policy.build_timeout_s, *flags, timeout_s=self.policy.build_timeout_s + 30)
        self.report['build'] = dict(source=fetched, build=built)
        problems = readiness.build_problems(self.manifest, fetched, built)
        self.evidence.event('source_and_build', problems=problems, head=fetched.get('head'), rustc=built.get('rustc'))
        if problems:
            raise Stop('build_verification_failed', '; '.join(problems))
        self.built_release = built['release']
        self.report['binary_hash_basis'] = 'frozen' if readiness.binaries_frozen(self.manifest) else 'observed_for_calibration'

    def _relay_to_game(self):
        """Through the controller: the builder holds no key for the game host. Hashes are compared after the move."""
        with tempfile.TemporaryDirectory() as temporary:
            for name in ('omega-server', 'server_config.json', 'sample_host.py'):
                local = str(pathlib.Path(temporary) / name)
                self._transfer(self.guests.get, 'bot', '/home/deploy/omega-release/' + name, local)
                self._transfer(self.guests.put, 'game', local, AGENT_INCOMING + '/' + name)
        installed = self._agent('game', 'install_release', '--role', 'game', '--incoming', AGENT_INCOMING)
        for name in ('omega-server', 'server_config.json', 'sample_host.py'):
            if (installed.get('release') or {}).get(name) != self.built_release.get(name):
                raise Stop('build_verification_failed', name + ' changed in transit')
        self.evidence.event('release_relayed', files=sorted(installed['release']))

    def _measure_clock(self, role):
        """Bracket one trivial call. The bracket is the uncertainty, and the probe's own timing is not used."""
        before = self.wall()
        reading = self._agent(role, 'clock')
        after = self.wall()
        wall_ns = reading.get('wall_ns')
        if not isinstance(wall_ns, int):
            return None
        return dict(offset_s=wall_ns / 1e9 - (before + after) / 2, uncertainty_s=(after - before) / 2,
                    guest_monotonic_ns=reading.get('monotonic_ns'))

    def _verify_ready(self):
        problems = []
        images = {i['id']: i['name'] for i in self.facts['images']}
        for role in ROLES:
            observation = self._agent(role, 'probe', '--role', role)
            measured = self._measure_clock(role)
            sampler = self._agent(role, 'sampler')
            entry = self.report['roles'][role]
            entry.update(observation=self._retain_packages(role, observation), clock_offset=measured, sampler=sampler)
            # Judged as the guest reported it, whole list included, not as the report now summarizes it.
            problems += readiness.observation_problems(self.manifest, role, observation, images.get(self.manifest['roles'][role]['image_id']),
                                                       built_release=self.built_release)
            problems += readiness.clock_problems(role, measured)
            problems += readiness.sampler_problems(role, sampler)
        if problems:
            raise Stop('readiness_failed', '; '.join(problems))
        probe = self._agent('bot', 'tcp_probe', '--host', self.droplets['game']['public_ipv4'][0], '--port', session_access.SSH_PORT)
        self.report['firewall_enforcement'] = probe
        problems = readiness.enforcement_problems(probe)
        if problems:
            raise Stop('readiness_failed', '; '.join(problems))
        problems = self._enet_smoke()
        self.report['problems'] = problems
        if problems:
            raise Stop('readiness_failed', '; '.join(problems))
        self._check_inventory()
        self._verify_firewall_unchanged()

    def _retain_packages(self, role, observation):
        """Keep the guest's whole package list in its own file: teardown destroys the only other copy.

        The report keeps the command status, the hashes and where the file is, which binds it to ``mark_ready`` through
        the report's own hash. A list readiness will refuse is still retained, because it explains the refusal.
        """
        packages = observation.get('packages') if isinstance(observation, dict) else None
        if not isinstance(packages, dict) or not isinstance(packages.get('inventory'), list):
            return observation
        name = 'packages-%s.json' % role
        path = self.evidence.artifact(name, dict(schema='omega.do-session.package-inventory/1', session_id=self.session_id, role=role,
                                                 command=packages.get('command'), rc=packages.get('rc'), count=packages.get('count'),
                                                 sha256=packages.get('sha256'), inventory=packages['inventory']))
        problems = readiness.package_problems(packages)
        summary = {k: v for k, v in packages.items() if k != 'inventory'}
        summary.update(artifact='provisioning/' + name, artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), problems=problems)
        self.report.setdefault('required_artifacts', []).append(dict(kind='package_inventory', role=role, path=summary['artifact'], sha256=summary['artifact_sha256']))
        return dict(observation, packages=summary)

    def _verify_firewall_unchanged(self):
        """Readiness is about the firewall as it is now, not as it was before the minutes spent on bootstrap."""
        desired = self.desired_firewall()
        actual = self.provider.get_firewall(self.firewall_id)
        key = resource_ownership.resource_key('firewall', self.firewall_id)
        if actual is None:
            raise Stop('firewall_verification_failed', 'firewall is gone')
        problems = session_access.firewall_problems(actual, desired)
        if problems:
            raise OwnershipConflict(key, problems, actual.get('name'))
        problems = session_access.applied_problems(actual)
        if problems:
            raise Stop('firewall_verification_failed', '; '.join(problems))
        self.evidence.event('firewall_unchanged', firewall_id=self.firewall_id)

    def _enet_smoke(self):
        """Over the public route and the session firewall. Its processes and ports are gone again before ready."""
        started = self._agent('game', 'smoke_game_start')
        target = self.droplets['game']['public_ipv4'][0] + ':' + session_access.GAME_PORT
        try:
            bot = self._agent('bot', 'smoke_bot', '--server', target, '--timeout-s', self.policy.smoke_timeout_s,
                              timeout_s=self.policy.smoke_timeout_s + 30)
        finally:
            stopped = self._agent('game', 'smoke_game_stop')
        self.report['enet_smoke'] = dict(game_started=started, bot=bot, game_stopped=stopped)
        return readiness.smoke_problems(started, bot, stopped)

    def _mark_ready(self):
        path = self.evidence.artifact('readiness.json', self.report)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        evidence_ref = 'provisioning/readiness.json#sha256:' + digest
        ack = self.client.mutate('mark_ready', session_id=self.session_id, fencing_token=self.token, evidence_ref=evidence_ref)
        self.evidence.event('pair_ready', ready_at=ack['ready_at'], evidence_ref=evidence_ref)
        if self.on_ready is not None:
            self.on_ready(ack, evidence_ref)
        return self._result(READY, evidence_ref=evidence_ref)


def bounded_setup_problems(manifest):
    """The planner's rules for a session whose workload belongs to a later, separately bounded plan."""
    reasons = []
    limits, timing = manifest['limits'], manifest['timing_basis']
    needed = sum(timing[term]['seconds'] for term in ('create_bootstrap_s', 'readiness_access_s', 'collection_export_s'))
    needed += limits['evidence_recovery_grace_s'] + limits['teardown_reserve_s'] + session_clock.DELETE_ISSUE_MARGIN_S
    if needed > limits['max_session_duration_s']:
        reasons.append('setup, collection, recovery and teardown need %.1f s of a %s s cap' % (needed, limits['max_session_duration_s']))
    cost = admission.estimate_cost(manifest)
    if cost['session_estimate_usd'] > limits['max_estimated_session_usd']:
        reasons.append('session estimate %.6f USD exceeds its limit' % cost['session_estimate_usd'])
    if cost['estimated_outbound_gib'] > limits['max_estimated_transfer_gib']:
        reasons.append('estimated outbound %.6f GiB exceeds its limit' % cost['estimated_outbound_gib'])
    return reasons


def current_firewall_conflict(manifest, firewall_id, actual, desired):
    """Exact id, name, targets and only this session's own rules, against a fresh read. See ``replacement_problems``."""
    key = resource_ownership.resource_key('firewall', firewall_id)
    problems = resource_ownership.retained_problems(manifest, key) + session_access.replacement_problems(actual, desired, firewall_id)
    return OwnershipConflict(key, problems, actual.get('name')) if problems else None


def apply_firewall(provider, manifest, firewall_id, desired, sleep, monotonic, policy, authority):
    """Replace a recorded firewall, then trust only the read-back.

    Every attempt reads the firewall and refuses if it has drifted (``OwnershipConflict``), then proves control again, and
    only then sends. ``authority`` also runs after every wait. It raises to stop, and this function lets it, so nothing
    that follows it can send. An unreadable firewall is not replaced. A firewall already exactly as desired, as when a
    previous response was lost, is not replaced again.

    DigitalOcean documents no conditional update: a change landing between the read and the PUT is overwritten, and the
    read-back then sees our own replacement. The read narrows that race to one request and cannot close it.

    A failed attempt is simply repeated within a bound. The rules are exact in every attempt, so no failure path can
    widen ingress, and an unreachable provider leaves the previous exact rules in force.
    """
    problems = ['the firewall could not be updated']
    actual = None
    for attempt in range(1, policy.firewall_update_attempts + 1):
        authority()
        try:
            current = provider.get_firewall(firewall_id)
            if current is None:
                return dict(problems=['firewall is gone'], attempts=attempt, firewall=None)
            conflict = current_firewall_conflict(manifest, firewall_id, current, desired)
            if conflict is not None:
                raise conflict
            if session_access.firewall_problems(current, desired):
                authority()     # that read may have been slow
                provider.update_firewall(firewall_id, desired)
                current = provider.get_firewall(firewall_id)
            actual = current
        except remote_authorization.MutationRefused:
            raise
        except cleanup_provider.ProviderError as error:
            problems = [cleanup_provider.redact(error)]
            actual = None
        if actual is not None:
            problems = session_access.firewall_problems(actual, desired)
            if not problems:
                break
        sleep(policy.provider_poll_s)
    else:
        return dict(problems=problems, attempts=attempt, firewall=actual)
    deadline = monotonic() + policy.firewall_apply_wait_s
    while True:
        try:
            actual = provider.get_firewall(firewall_id)
        except cleanup_provider.ProviderError as error:
            problems = [cleanup_provider.redact(error)]
            actual = None
        else:
            problems = ['firewall is gone'] if actual is None else (session_access.firewall_problems(actual, desired)
                                                                    + session_access.applied_problems(actual))
        authority()     # Read-back can finish after cleanup, takeover or lease expiry.
        if not problems or (actual is not None and actual.get('status') == 'failed') or monotonic() >= deadline:
            return dict(problems=problems, attempts=attempt, firewall=actual)
        sleep(policy.provider_poll_s)
        authority()


def refresh_access(client, provider, manifest, fencing_token, ssh_sources, operator_udp_sources, sleep, monotonic, policy=None, evidence=None):
    """Replace the exact source allowlists through the API. It needs no SSH and works while SSH is locked out.

    Invalid sources are refused before any request. The target comes from the registry's exact id, and a recorded
    resource that fails its ownership check raises ``OwnershipConflict`` with an incident on record and nothing sent.

    Cleanup, a lost lease, a takeover and C all stop a refresh, because a firewall under cleanup is protection and a stale
    controller's rules must not overwrite a newer one's. Control is checked immediately before each PUT and after each
    wait. A stop found once work began comes back as ``stopped`` with ``applied=False``, and the rules stay as they stand.
    """
    policy = policy or Policy()
    session_id = manifest['session']['id']

    def record(kind, **data):
        """A failed evidence write must not hide what happened from the caller."""
        if evidence is not None:
            try:
                evidence.event(kind, **data)
            except (OSError, Stop):
                pass

    def authority():
        require_control(client, provider, session_id, fencing_token, provider.wall)

    def refuse(conflict):
        report_conflict(client, session_id, conflict, record)
        raise conflict

    status = require_control(client, provider, session_id, fencing_token, provider.wall)
    firewalls = [r for r in status['resources'] if r['kind'] == 'firewall']
    droplets = [r for r in status['resources'] if r['kind'] == 'droplet']
    bots = [r for r in droplets if r['name'] == session_id + '-bot']
    if len(firewalls) != 1 or len(bots) != 1:
        raise Stop('ownership_ambiguous', 'the registry does not hold exactly one firewall and one bot droplet')
    bot = None
    for recorded in droplets:
        droplet = provider.get_droplet(recorded['provider_id'])
        if droplet is None:
            raise Stop('ownership_ambiguous', 'recorded droplet %s is gone' % recorded['provider_id'])
        conflict = droplet_conflict(manifest, recorded['provider_id'], droplet)
        if conflict is not None:
            refuse(conflict)
        if recorded is bots[0]:
            bot = droplet
    if len(bot['public_ipv4']) != 1:
        raise Stop('ownership_ambiguous', 'the bot droplet does not have exactly one public route')
    desired = session_access.firewall_request(manifest, ssh_sources, operator_udp_sources, bot['public_ipv4'][0])
    firewall_id = firewalls[0]['provider_id']
    try:
        outcome = apply_firewall(provider, manifest, firewall_id, desired, sleep, monotonic, policy, authority)
    except OwnershipConflict as conflict:
        refuse(conflict)
    except (ControlLost, registry_client.RegistryRejected, registry_client.RegistryUnavailable) as stop:
        code = getattr(stop, 'code', 'registry_unavailable')
        detail = cleanup_provider.redact(stop)
        record('access_refresh_stopped', firewall_id=firewall_id, code=code, detail=detail)
        return dict(firewall_id=firewall_id, applied=False, stopped=code, problems=[detail], attempts=None)
    record('access_refreshed', firewall_id=firewall_id, ssh_sources=desired['inbound_rules'][0]['sources']['addresses'],
           problems=outcome['problems'], attempts=outcome['attempts'])
    return dict(firewall_id=firewall_id, applied=not outcome['problems'], stopped=None, problems=outcome['problems'], attempts=outcome['attempts'])
