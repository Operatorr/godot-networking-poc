"""Controller-side client for the registry: retries, acknowledgement checks and the create gate.

The registry lives on the trusted management host, so the controller reaches it through a transport
(one JSON request in, one JSON response out). Retries reuse the request id: if a write applied but
its acknowledgement was lost, the replay returns the original answer rather than a second t0 or a
second dispatch. Exhausted retries raise ``RegistryUnavailable``, and the create path treats that
as refusal: no acknowledgement, no provider create.
"""
import contextlib
import copy
import json
import shlex
import subprocess
import time
import uuid

import admission
import create_evidence
import session_clock

STORAGE_ERROR = 'registry_storage_error'
MAX_REVOCATION_WAITS = 8
REVOCATION_WAIT_STEP_S = 2.0


class TransportError(Exception):
    """The request or its response was lost; it may or may not have been applied."""


class RegistryUnavailable(Exception):
    """No durable acknowledgement could be obtained. Provider creation and dispatch must not proceed."""


class RegistryRejected(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(code + ': ' + str(message))
        self.code = code
        self.message = message
        self.details = details or {}


class CreateUnresolved(Exception):
    """An earlier create's outcome is unknown and nothing proves otherwise, so nothing was sent.

    Waiting does not clear this: a client timeout says nothing about when the provider finishes. It
    clears when the resource is found or typed evidence arrives. Otherwise the batch stops and cleans up.
    """

    def __init__(self, intent_id, create_request_ref):
        super().__init__('%s has no settlement evidence for %s' % (intent_id, create_request_ref))
        self.intent_id = intent_id
        self.create_request_ref = create_request_ref


class CreateGrantExpired(Exception):
    """The grant sat unused past its start window, so the create was not sent."""


class LocalTransport:
    """In-process transport over the same ``rpc`` entry point the CLI serves."""

    def __init__(self, registry):
        self.registry = registry

    def __call__(self, request):
        return self.registry.rpc(request)


class SubprocessTransport:
    """One process per request, so a command like ``ssh mgmt omega-do-registry rpc`` fits as is."""

    def __init__(self, argv, timeout_s=30.0):
        self.argv = list(argv)
        self.timeout_s = timeout_s

    def within(self, seconds):
        return SubprocessTransport(self.argv, min(self.timeout_s, seconds))

    def __call__(self, request):
        try:
            completed = subprocess.run(self.argv, input=json.dumps(request).encode('utf-8'), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, timeout=self.timeout_s, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise TransportError(type(error).__name__)
        if completed.returncode != 0:
            raise TransportError('registry command exited ' + str(completed.returncode))
        try:
            return json.loads(completed.stdout.decode('utf-8'))
        except ValueError:
            raise TransportError('registry response was not JSON')


def ssh_argv(host, remote_command='omega-do-registry rpc', connect_timeout_s=10):
    """Key-only and host-verified. The request travels on stdin, so nothing reaches a remote shell."""
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'PasswordAuthentication=no',
            '-o', 'ConnectTimeout=' + str(connect_timeout_s), host] + shlex.split(remote_command)


class RegistryClient:
    def __init__(self, transport, controller_id, attempts=4, retry_delay_s=1.0, sleep=time.sleep, new_request_id=None,
                 monotonic=session_clock.suspend_aware_monotonic):
        self.transport = transport
        self.controller_id = controller_id
        self.attempts = attempts
        self.retry_delay_s = retry_delay_s
        self.sleep = sleep
        self.monotonic = monotonic
        self.new_request_id = new_request_id or (lambda: uuid.uuid4().hex)

    def call(self, method, request_id=None, **params):
        """Return the acknowledged result, raise RegistryRejected, or raise RegistryUnavailable."""
        if request_id is not None:
            params['request_id'] = request_id
        request = dict(method=method, params=params)
        failure = 'no attempt was made'
        for attempt in range(self.attempts):
            if attempt:
                self.sleep(self.retry_delay_s)
            try:
                response = self.transport(request)
            except TransportError as error:
                failure = str(error)
                continue
            if not isinstance(response, dict) or 'ok' not in response:
                failure = 'malformed registry response'
                continue
            if response['ok']:
                return response['result']
            if response.get('code') == STORAGE_ERROR:
                failure = response.get('message') or STORAGE_ERROR
                continue
            raise RegistryRejected(response.get('code', 'rejected'), response.get('message'), response.get('details'))
        raise RegistryUnavailable('no durable acknowledgement for ' + method + ': ' + failure)

    def mutate(self, method, request_id=None, **params):
        return self.call(method, request_id=request_id or self.new_request_id(), **params)

    def guest_grant(self, session_id, fencing_token, action, role, prepare, sleep, run_id=None):
        """One grant for one start: the guest mints its identity first, then the registry commits the intent.

        ``prepare()`` returns the id. A pending revocation is waited out here, at most for the life of the grants it names, which
        takes a fresh identity each time because a guest times a grant from the moment it minted it.
        """
        for _ in range(MAX_REVOCATION_WAITS):
            grant_id = prepare()
            try:
                return self.mutate('authorize_guest_action', 'grant:%s:%s' % (session_id, grant_id), session_id=session_id, fencing_token=fencing_token, action=action,
                                   grant_id=grant_id, role=role, run_id=run_id)
            except RegistryRejected as rejection:
                if rejection.code != 'revocation_pending':
                    raise
                sleep(min(REVOCATION_WAIT_STEP_S, max(0.01, rejection.details.get('retry_after_s') or 0.0)))
        raise RegistryUnavailable('a revocation stayed pending past the life of any grant')

    def within(self, seconds):
        """A copy that answers or gives up inside ``seconds``: one attempt, no retry delay. For a caller with its own hard deadline."""
        limited = copy.copy(self)
        limited.attempts = 1
        if hasattr(self.transport, 'within'):
            limited.transport = self.transport.within(seconds)
        return limited

    # ---- the pre-create contract -------------------------------------------------------------

    def register(self, manifest, manifest_sha256, request_id=None):
        ack = self.mutate('register_session', request_id, manifest=manifest, manifest_sha256=manifest_sha256)
        if ack.get('manifest_sha256') != manifest_sha256:
            raise RegistryUnavailable('registry acknowledged a different manifest hash')
        return ack

    def acquire(self, session_id, takeover=False, request_id=None):
        return self.mutate('acquire_control', request_id, session_id=session_id, controller_id=self.controller_id,
                           takeover=takeover)

    def arm(self, session_id, manifest, manifest_sha256, fencing_token, request_id=None):
        """t0/D/C must come back durable and exactly as the frozen limits require."""
        ack = self.mutate('arm_session', request_id, session_id=session_id, manifest_sha256=manifest_sha256,
                          fencing_token=fencing_token)
        try:
            admission.validate_arm_ack(ack, manifest, manifest_sha256)
        except ValueError as error:
            raise RegistryUnavailable(str(error))
        return ack

    def guarded_create(self, session_id, intent_id, fencing_token, create_fn, find_fn, request_id=None, settlement_fn=None):
        """Run one provider create behind the durable intent, reconciling any uncertainty first.

        ``create_fn(grant)`` returns the exact id or raises, and must finish within the grant's
        ``create_request_timeout_s`` without retrying. It raises ``create_evidence.CreateRejected`` or
        ``CreateNotSent`` only when that is certain; anything else leaves the outcome unknown.
        ``find_fn(grant)`` looks the intent up by unique tag and name and returns an id or None. It is
        called whenever an earlier request may have reached the provider, so a lost response can never
        become a blind duplicate. ``settlement_fn(grant)`` returns a ``create_evidence`` receipt for
        ``grant['create_request_ref']`` or None. Without a found resource or a receipt this raises
        ``CreateUnresolved`` and sends nothing.
        """
        started = self.monotonic()
        try:
            grant = self.mutate('begin_create', request_id, session_id=session_id, intent_id=intent_id,
                                fencing_token=fencing_token)
        except RegistryRejected as rejection:
            if rejection.code != 'create_outcome_unknown':
                raise
            grant = dict(rejection.details, must_reconcile=True, authorized=False)
        if grant.get('must_reconcile'):
            if grant.get('replayed') and request_id is None:
                # This call's own id came back as a replay: the first answer was lost in transit, and
                # that id was never given to anyone else, so nobody ever held this grant.
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='not_sent',
                            fencing_token=fencing_token, request_number=grant['request_count'],
                            note='the acknowledgement of this grant was lost, so no request was sent')
            else:
                resource_key = self._reconcile(session_id, intent_id, fencing_token, grant, find_fn, settlement_fn)
                if resource_key is not None:
                    return resource_key
            started = self.monotonic()
            grant = self.mutate('begin_create', session_id=session_id, intent_id=intent_id, fencing_token=fencing_token)
        if not grant.get('authorized'):
            raise RegistryUnavailable('create was not authorized for ' + intent_id)
        if self.monotonic() - started > grant['create_start_window_s']:
            # Never sent, and only this holder knows that. If the report is lost the request stays unresolved.
            with contextlib.suppress(RegistryUnavailable, RegistryRejected):
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='not_sent',
                            fencing_token=fencing_token, request_number=grant['request_count'], note='grant expired unused')
            raise CreateGrantExpired(intent_id)
        # The adapter enforces the same window on its connection, so a slow connect cannot stretch it.
        grant = dict(grant, send_by_monotonic=started + grant['create_start_window_s'])
        try:
            provider_id = create_fn(grant)
        except create_evidence.CreateNotSent:
            with contextlib.suppress(RegistryUnavailable, RegistryRejected):
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='not_sent',
                            fencing_token=fencing_token, request_number=grant['request_count'], note='the adapter sent nothing')
            raise
        except create_evidence.CreateRejected as rejected:
            with contextlib.suppress(RegistryUnavailable, RegistryRejected):
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='rejected',
                            request_number=grant['request_count'], note=type(rejected).__name__)
            raise
        except Exception as error:
            # Unrecorded, the intent simply stays 'requested', which the watchdog treats the same way.
            with contextlib.suppress(RegistryUnavailable):
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='ambiguous',
                            note=type(error).__name__)
            raise
        kind = grant['kind']
        recorded = self.mutate('record_resource', session_id=session_id, kind=kind, provider_id=str(provider_id),
                               intent_id=intent_id, name=grant.get('expected_name'))
        return recorded['resource_key']

    def _reconcile(self, session_id, intent_id, fencing_token, grant, find_fn, settlement_fn):
        """Return the resource key if the earlier create landed, or None once evidence says it did not.

        A visible resource is proof at any time. Nothing visible proves nothing, however long ago the
        request was sent, so absence needs a receipt for this exact request.
        """
        def record_if_found():
            found = find_fn(grant)
            if found is None:
                return None
            return self.mutate('record_resource', session_id=session_id, kind=grant['kind'], provider_id=str(found),
                               intent_id=intent_id, name=grant.get('expected_name'))['resource_key']

        resource_key = record_if_found()
        if resource_key is not None:
            return resource_key
        settlement = settlement_fn(grant) if settlement_fn is not None else None
        if settlement is None:
            raise CreateUnresolved(intent_id, grant['create_request_ref'])
        # A resource that landed before the request finished must be adopted, not duplicated.
        resource_key = record_if_found()
        if resource_key is not None:
            return resource_key
        settled = self.mutate('record_create_settlement', session_id=session_id, intent_id=intent_id, settlement=settlement,
                              fencing_token=fencing_token)
        return settled['resource_key']
