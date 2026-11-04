"""Controller-side client for the registry: retries, acknowledgement checks and the create gate.

The registry lives on the trusted management host, so the controller reaches it through a transport
(one JSON request in, one JSON response out). Retries reuse the request id: if a write applied but
its acknowledgement was lost, the replay returns the original answer rather than a second t0 or a
second dispatch. Exhausted retries raise ``RegistryUnavailable``, and the create path treats that
as refusal: no acknowledgement, no provider create.
"""
import contextlib
import json
import shlex
import subprocess
import time
import uuid

import admission
import session_clock

STORAGE_ERROR = 'registry_storage_error'


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


class CreateStillSettling(Exception):
    """An earlier create can still land. Nothing was sent; call ``guarded_create`` again later."""

    def __init__(self, intent_id, retry_after_s):
        super().__init__('%s can still land; retry in %.1f s' % (intent_id, retry_after_s))
        self.intent_id = intent_id
        self.retry_after_s = retry_after_s


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

    def guarded_create(self, session_id, intent_id, fencing_token, create_fn, find_fn, request_id=None):
        """Run one provider create behind the durable intent, reconciling any uncertainty first.

        ``create_fn(grant)`` returns the exact id or raises, and must finish within the grant's
        ``create_request_timeout_s`` without retrying. ``find_fn(grant)`` looks the intent up by unique
        tag and name and returns an id or None. It is called whenever an earlier request may have
        reached the provider, so a lost response can never become a blind duplicate. Raises
        ``CreateStillSettling`` while that earlier request can still land.
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
            resource_key = self._reconcile(session_id, intent_id, fencing_token, grant, find_fn)
            if resource_key is not None:
                return resource_key
            started = self.monotonic()
            grant = self.mutate('begin_create', session_id=session_id, intent_id=intent_id, fencing_token=fencing_token)
        if not grant.get('authorized'):
            raise RegistryUnavailable('create was not authorized for ' + intent_id)
        if self.monotonic() - started > grant['create_start_window_s']:
            # The bound behind every later absence claim assumes the request started inside this window.
            with contextlib.suppress(RegistryUnavailable):
                self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='ambiguous',
                            note='grant expired unused')
            raise CreateGrantExpired(intent_id)
        try:
            provider_id = create_fn(grant)
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

    def _reconcile(self, session_id, intent_id, fencing_token, grant, find_fn):
        """Return the resource key if the earlier create landed, or None once it is proven absent.

        A visible resource is proof at any time. Absence counts only from a listing the registry opened
        after the settle bound, so an empty listing while the request can still land grants nothing.
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
        try:
            ticket = self.mutate('begin_reconcile', session_id=session_id, intent_id=intent_id, fencing_token=fencing_token)
        except RegistryRejected as rejection:
            if rejection.code != 'create_settling':
                raise
            raise CreateStillSettling(intent_id, rejection.details['retry_after_s'])
        if not ticket['outstanding']:
            return ticket['resource_key']
        resource_key = record_if_found()
        if resource_key is not None:
            return resource_key
        self.mutate('record_create_result', session_id=session_id, intent_id=intent_id, outcome='reconciled_absent',
                    fencing_token=fencing_token, reconcile_id=ticket['reconcile_id'],
                    note='authenticated listing by unique tag and name, started after the settle bound, found nothing')
        return None
