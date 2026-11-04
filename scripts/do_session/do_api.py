"""The real DigitalOcean adapter behind the provider seams (handoff slice 3, issue #66).

Two classes, split by privilege. ``DigitalOceanProvider`` is what the watchdog runs: authenticated reads
and deletes of exact resources, nothing else. ``DigitalOceanProvisioningProvider`` adds what a controller
needs and refuses every create, update or assignment without a ``remote_authorization.MutationGate``.

Every request passes one route allowlist before a byte can leave, so bulk deletes, key or project changes
and image operations cannot be expressed. A transport makes exactly one attempt with an absolute bound and
never follows a redirect. Retrying belongs to the callers that own the retry budget.

What a response proves (see README "Create settlement"):

  * create answered 2xx with an exact id: it landed;
  * create answered with a listed refusal: ``CreateRejected``;
  * connecting failed, so no request byte left: ``CreateNotSent``;
  * anything else, including a 5xx, a timeout and a 2xx without an id: unknown, and it stays unknown.

DigitalOcean documents no idempotency key and no way to ask about a lost create, and its 202 "does not
indicate the success or failure of the operation". So ``get_request_settlement`` stays the inherited None,
and this adapter names no receipt basis. A resource found by tag and name is the only way back.
"""
import dataclasses
import http.client
import json
import os
import re
import socket
import ssl
import stat
import threading
import time
import urllib.parse

import cleanup_provider
import create_evidence
import session_clock

API_HOST = 'api.digitalocean.com'
PAGE_SIZE = 200
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
CONNECT_BOUND_S = 10.0
# Status codes that can only mean this request was refused. 408, 409, 425 and every 5xx are not here.
DEFINITIVE_CREATE_REFUSALS = (400, 401, 403, 404, 422, 429)
ACCEPTED_DELETE = (200, 202, 204, 404)   # the seam's contract: only a later authenticated read proves absence
ASSIGNED_STATES = ('ok', 'assigned', 'already_assigned')

NUMERIC_ID = r'[0-9]{1,20}'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
TAG = r'[A-Za-z0-9_:%-]{1,512}'     # percent-encoded by the caller
WATCHDOG_ROUTES = tuple((method, re.compile('^' + pattern + '$')) for method, pattern in (
    ('GET', '/v2/droplets'),        # only with tag_name: see list_droplets_by_tag
    ('GET', '/v2/droplets/' + NUMERIC_ID),
    ('DELETE', '/v2/droplets/' + NUMERIC_ID),
    ('GET', '/v2/firewalls'),
    ('GET', '/v2/firewalls/' + UUID),
    ('DELETE', '/v2/firewalls/' + UUID),
    ('GET', '/v2/tags/' + TAG),
    ('DELETE', '/v2/tags/' + TAG),
))
CONTROLLER_ROUTES = WATCHDOG_ROUTES + tuple((method, re.compile('^' + pattern + '$')) for method, pattern in (
    ('GET', '/v2/account'),
    ('GET', '/v2/account/keys/' + NUMERIC_ID),
    ('GET', '/v2/regions'),
    ('GET', '/v2/sizes'),
    ('GET', '/v2/images/' + NUMERIC_ID),
    ('GET', '/v2/projects/' + UUID),
    ('GET', '/v2/projects/' + UUID + '/resources'),
    ('GET', '/v2/droplets/' + NUMERIC_ID + '/firewalls'),
    ('POST', '/v2/droplets'),
    ('POST', '/v2/firewalls'),
    ('PUT', '/v2/firewalls/' + UUID),
    ('POST', '/v2/tags'),
    ('POST', '/v2/projects/' + UUID + '/resources'),
))


class RequestNotSent(Exception):
    """No byte of the HTTP request left this process."""


class RequestOutcomeUnknown(Exception):
    """The request may have reached the provider and no complete response came back."""


class RouteRefused(Exception):
    """This adapter cannot express that request. It is a defect, never a provider answer."""


@dataclasses.dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict
    body: bytes


def load_token(path):
    """Read a restricted token file. Its value is never logged, echoed or stored by this module."""
    path = os.path.expanduser(str(path))
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('token reference is not a regular file')
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('token file must not be readable by group or others')
    with open(path, encoding='utf-8') as handle:
        token = handle.read().strip()
    if not token or len(token.split()) != 1:
        raise ValueError('token file must hold exactly one token')
    return token


class HttpsTransport:
    """One attempt per call, over ``http.client``: no redirects, no proxy lookup, no hidden retries.

    ``request_bound_s`` is absolute. A timer shuts the socket at the bound, because a per-read timeout
    alone would let a slowly trickling response outlast it. ``send_by`` is a monotonic instant: a request
    still unsent by then is not sent at all, which is how a create grant's start window is enforced.
    """

    offline_fixture = False

    def __init__(self, token_path, host=API_HOST, connection_factory=None, monotonic=session_clock.suspend_aware_monotonic):
        self._token = load_token(token_path)
        self.host = host
        self.connection_factory = connection_factory or (
            lambda target, timeout: http.client.HTTPSConnection(target, timeout=timeout, context=ssl.create_default_context()))
        self.monotonic = monotonic

    def __call__(self, method, target, body=None, request_bound_s=session_clock.PROVIDER_REQUEST_BOUND_S, send_by=None):
        started = self.monotonic()
        connect_bound = CONNECT_BOUND_S if send_by is None else min(CONNECT_BOUND_S, send_by - started)
        if connect_bound <= 0:
            raise RequestNotSent('the send window closed before connecting')
        connection = self.connection_factory(self.host, min(connect_bound, request_bound_s))
        try:
            try:
                connection.connect()
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                raise RequestNotSent(type(error).__name__)
            remaining = request_bound_s - (self.monotonic() - started)
            if remaining <= 0 or (send_by is not None and self.monotonic() >= send_by):
                raise RequestNotSent('the send window closed while connecting')
            return self._exchange(connection, method, target, body, remaining)
        finally:
            connection.close()

    def _exchange(self, connection, method, target, body, remaining):
        headers = {'Authorization': 'Bearer ' + self._token, 'Accept': 'application/json', 'User-Agent': 'omega-do-session/1'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        expired = threading.Event()

        def expire():
            expired.set()
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        connection.sock.settimeout(remaining)
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            chunks, total = [], 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise RequestOutcomeUnknown('response exceeded the size bound')
                chunks.append(chunk)
            if expired.is_set():
                raise RequestOutcomeUnknown('the request bound elapsed')
            return HttpResponse(response.status, {k.lower(): v for k, v in response.getheaders()}, b''.join(chunks))
        except (OSError, http.client.HTTPException) as error:
            raise RequestOutcomeUnknown(type(error).__name__)
        finally:
            timer.cancel()


def _quoted(value):
    return urllib.parse.quote(str(value), safe='')


def _numeric(value):
    text = str(value)
    if not re.fullmatch(NUMERIC_ID, text):
        raise RouteRefused('not a numeric resource id')
    return text


def _uuid(value):
    text = str(value)
    if not re.fullmatch(UUID, text):
        raise RouteRefused('not a provider uuid')
    return text


class DigitalOceanProvider(cleanup_provider.CleanupProvider):
    """Reads and exact deletes: everything the watchdog's narrower token permits."""

    routes = WATCHDOG_ROUTES

    def __init__(self, transport, wall=time.time, request_bound_s=session_clock.PROVIDER_REQUEST_BOUND_S):
        self.transport = transport
        self.wall = wall
        self.request_bound_s = request_bound_s
        self.offline_fixture = getattr(transport, 'offline_fixture', False)

    # ---- one request -------------------------------------------------------------------------

    def _send(self, method, path, query=None, payload=None, request_bound_s=None, send_by=None):
        if not any(method == allowed and pattern.match(path) for allowed, pattern in self.routes):
            raise RouteRefused(method + ' ' + path + ' is not an adapter route')
        target = path + ('?' + urllib.parse.urlencode(query) if query else '')
        body = None if payload is None else json.dumps(payload, sort_keys=True).encode('utf-8')
        return self.transport(method, target, body=body, request_bound_s=request_bound_s or self.request_bound_s, send_by=send_by)

    def _exchange(self, method, path, query=None, payload=None):
        """For anything but a create, an undelivered or unanswered request is simply a failed one."""
        try:
            return self._send(method, path, query, payload)
        except (RequestNotSent, RequestOutcomeUnknown) as error:
            raise cleanup_provider.ProviderTransient(method + ' failed: ' + cleanup_provider.redact(error))

    def _retry_after(self, headers):
        try:
            return max(0.0, float(headers['retry-after']))
        except (KeyError, TypeError, ValueError):
            pass
        try:
            return max(0.0, float(headers['ratelimit-reset']) - self.wall())
        except (KeyError, TypeError, ValueError):
            return None

    def _describe(self, method, response):
        try:
            detail = json.loads(response.body.decode('utf-8'))
            code = detail.get('id') if isinstance(detail, dict) else None
        except (ValueError, UnicodeDecodeError):
            code = None
        return cleanup_provider.redact('%s answered %d%s' % (method, response.status, ' ' + str(code) if code else ''))

    def _raise_for(self, method, response):
        message = self._describe(method, response)
        if response.status in (401, 403):
            raise cleanup_provider.ProviderAuthError(message, status=response.status)
        if response.status == 429:
            raise cleanup_provider.ProviderRateLimited(message, status=429, retry_after_s=self._retry_after(response.headers))
        raise cleanup_provider.ProviderTransient(message, status=response.status)

    @staticmethod
    def _document(response, key=None):
        """A successful answer that lacks its expected shape proves nothing, least of all that a list is empty."""
        try:
            document = json.loads(response.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise cleanup_provider.ProviderTransient('provider answered %d with an unreadable body' % response.status, status=response.status)
        if not isinstance(document, dict) or (key is not None and key not in document):
            raise cleanup_provider.ProviderTransient('provider answered %d without %s' % (response.status, key), status=response.status)
        return document

    def _get(self, path, key, query=None):
        response = self._exchange('GET', path, query)
        if response.status == 404:
            return None
        if response.status != 200:
            self._raise_for('GET', response)
        return self._document(response, key)[key]

    def _paged(self, path, key, **query):
        """Follow page numbers we build ourselves, never a provider-supplied URL. A short walk is a failure."""
        items = []
        for page in range(1, MAX_PAGES + 1):
            response = self._exchange('GET', path, dict(query, per_page=PAGE_SIZE, page=page))
            if response.status != 200:
                self._raise_for('GET', response)
            document = self._document(response, key)
            batch = document[key]
            meta = document.get('meta')
            if not isinstance(batch, list) or not isinstance(meta, dict) or not isinstance(meta.get('total'), int):
                raise cleanup_provider.ProviderTransient('listing of ' + key + ' has no list or total')
            items.extend(batch)
            links = document.get('links')
            pages = links.get('pages') if isinstance(links, dict) else None
            if not isinstance(pages, dict) or not pages.get('next'):
                if len(items) != meta['total']:
                    raise cleanup_provider.ProviderTransient('listing of %s returned %d of %d' % (key, len(items), meta['total']))
                return items
        raise cleanup_provider.ProviderTransient('listing of ' + key + ' exceeded the page bound')

    def _delete(self, path):
        response = self._exchange('DELETE', path)
        if response.status not in ACCEPTED_DELETE:
            self._raise_for('DELETE', response)

    # ---- normal forms ------------------------------------------------------------------------

    @staticmethod
    def _droplet(item):
        try:
            networks = (item.get('networks') or {}).get('v4') or []
            public = [n.get('ip_address') for n in networks if n.get('type') == 'public']
            return dict(id=str(item['id']), name=item['name'], tags=list(item['tags'] or []), status=item['status'],
                        size_slug=item.get('size_slug') or (item.get('size') or {}).get('slug'),
                        region=(item.get('region') or {}).get('slug'), image_id=(item.get('image') or {}).get('id'),
                        vcpus=item.get('vcpus'), memory_mib=item.get('memory'), disk_gib=item.get('disk'),
                        public_ipv4=public, private_networks=[n.get('ip_address') for n in networks if n.get('type') != 'public'])
        except (KeyError, TypeError, AttributeError):
            raise cleanup_provider.ProviderTransient('droplet record is malformed')

    @staticmethod
    def _firewall(item):
        try:
            return dict(id=item['id'], name=item['name'], tags=list(item.get('tags') or []),
                        droplet_ids=list(item.get('droplet_ids') or []), status=item.get('status'),
                        pending_changes=list(item.get('pending_changes') or []),
                        inbound_rules=list(item.get('inbound_rules') or []), outbound_rules=list(item.get('outbound_rules') or []))
        except (KeyError, TypeError):
            raise cleanup_provider.ProviderTransient('firewall record is malformed')

    # ---- CleanupProvider ---------------------------------------------------------------------

    def get_droplet(self, droplet_id):
        item = self._get('/v2/droplets/' + _numeric(droplet_id), 'droplet')
        if item is None:
            return None
        droplet = self._droplet(item)
        if droplet['id'] != str(droplet_id):
            raise cleanup_provider.ProviderTransient('provider answered with a different droplet')
        return droplet

    def delete_droplet(self, droplet_id):
        self._delete('/v2/droplets/' + _numeric(droplet_id))

    def list_droplets_by_tag(self, tag):
        if not tag:
            raise RouteRefused('a droplet listing needs its exact tag')
        return [self._droplet(item) for item in self._paged('/v2/droplets', 'droplets', tag_name=tag)]

    def get_firewall(self, firewall_id):
        item = self._get('/v2/firewalls/' + _uuid(firewall_id), 'firewall')
        if item is None:
            return None
        firewall = self._firewall(item)
        if firewall['id'] != str(firewall_id):
            raise cleanup_provider.ProviderTransient('provider answered with a different firewall')
        return firewall

    def delete_firewall(self, firewall_id):
        self._delete('/v2/firewalls/' + _uuid(firewall_id))

    def list_firewalls_by_name(self, name):
        """The API has no name filter, so walk every page and keep exact matches only."""
        return [self._firewall(item) for item in self._paged('/v2/firewalls', 'firewalls') if item.get('name') == name]

    def get_tag(self, name):
        item = self._get('/v2/tags/' + _quoted(name), 'tag')
        if item is None:
            return None
        try:
            if item['name'] != name:
                raise cleanup_provider.ProviderTransient('provider answered with a different tag')
            return dict(name=item['name'], resource_count=int(item['resources']['count']))
        except (KeyError, TypeError, ValueError):
            raise cleanup_provider.ProviderTransient('tag record is malformed')

    def delete_tag(self, name):
        self._delete('/v2/tags/' + _quoted(name))


class DigitalOceanProvisioningProvider(DigitalOceanProvider):
    """The controller's adapter. Without a gate it can read and delete, but it cannot create or change anything."""

    routes = CONTROLLER_ROUTES

    def __init__(self, transport, gate=None, wall=time.time, request_bound_s=session_clock.PROVIDER_REQUEST_BOUND_S):
        super().__init__(transport, wall=wall, request_bound_s=request_bound_s)
        self.gate = gate

    def _require_gate(self, method_name, *details):
        if self.gate is None:
            raise create_evidence.CreateNotSent(method_name + ' needs a separately bounded remote authorization')
        self.gate.check(method_name, *details)

    # ---- facts -------------------------------------------------------------------------------

    def account(self):
        return self._get('/v2/account', 'account')

    def droplet_count(self):
        response = self._exchange('GET', '/v2/droplets', dict(per_page=1, page=1))
        if response.status != 200:
            self._raise_for('GET', response)
        meta = self._document(response, 'meta')['meta']
        if not isinstance(meta, dict) or not isinstance(meta.get('total'), int):
            raise cleanup_provider.ProviderTransient('droplet listing has no total')
        return meta['total']

    def regions(self):
        return self._paged('/v2/regions', 'regions')

    def sizes(self):
        return self._paged('/v2/sizes', 'sizes')

    def image(self, image_id):
        return self._get('/v2/images/' + _numeric(image_id), 'image')

    def ssh_key(self, key_id):
        return self._get('/v2/account/keys/' + _numeric(key_id), 'ssh_key')

    def project(self, project_id):
        return self._get('/v2/projects/' + _uuid(project_id), 'project')

    def project_resource_urns(self, project_id):
        return {item.get('urn') for item in self._paged('/v2/projects/' + _uuid(project_id) + '/resources', 'resources')}

    def droplet_firewall_ids(self, droplet_id):
        return [item.get('id') for item in self._paged('/v2/droplets/' + _numeric(droplet_id) + '/firewalls', 'firewalls')]

    # ---- creates: one attempt, and the status alone decides what is known ---------------------

    def _create(self, path, payload, key, request_bound_s, send_by):
        try:
            response = self._send('POST', path, payload=payload, request_bound_s=request_bound_s, send_by=send_by)
        except RequestNotSent as error:
            raise create_evidence.CreateNotSent(str(error))
        except RequestOutcomeUnknown as error:
            raise cleanup_provider.ProviderTransient('create outcome unknown: ' + cleanup_provider.redact(error))
        if 200 <= response.status < 300:
            return self._document(response, key)[key]     # a 2xx without its record stays unknown
        if response.status in DEFINITIVE_CREATE_REFUSALS:
            raise create_evidence.CreateRejected(self._describe('POST', response))
        raise cleanup_provider.ProviderTransient('create outcome unknown: ' + self._describe('POST', response), status=response.status)

    def create_tag(self, name, request_bound_s=None, send_by=None):
        self._require_gate('create_tag', name)
        item = self._create('/v2/tags', dict(name=name), 'tag', request_bound_s, send_by)
        if not isinstance(item, dict) or item.get('name') != name:
            raise cleanup_provider.ProviderTransient('create outcome unknown: tag response does not name the tag')
        return name

    def create_firewall(self, payload, request_bound_s=None, send_by=None):
        self._require_gate('create_firewall', payload)
        item = self._create('/v2/firewalls', payload, 'firewall', request_bound_s, send_by)
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch(UUID, item['id']):
            raise cleanup_provider.ProviderTransient('create outcome unknown: firewall response has no exact id')
        return item['id']

    def create_droplet(self, payload, request_bound_s=None, send_by=None):
        self._require_gate('create_droplet', payload)
        item = self._create('/v2/droplets', payload, 'droplet', request_bound_s, send_by)
        identifier = item.get('id') if isinstance(item, dict) else None
        if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0:
            raise cleanup_provider.ProviderTransient('create outcome unknown: droplet response has no exact id')
        return str(identifier)

    # ---- changes to resources this session already owns ---------------------------------------

    def update_firewall(self, firewall_id, payload):
        """A full replacement, so its effect is read back by the caller. A lost response is safe to send again."""
        self._require_gate('update_firewall', firewall_id, payload)
        response = self._exchange('PUT', '/v2/firewalls/' + _uuid(firewall_id), payload=payload)
        if response.status != 200:
            self._raise_for('PUT', response)

    def assign_droplet(self, project_id, droplet_id):
        self._require_gate('assign_droplet', project_id, droplet_id)
        urn = 'do:droplet:' + _numeric(droplet_id)
        response = self._exchange('POST', '/v2/projects/' + _uuid(project_id) + '/resources', payload=dict(resources=[urn]))
        if response.status != 200:
            self._raise_for('POST', response)
        resources = self._document(response, 'resources')['resources']
        entry = next((item for item in resources if isinstance(item, dict) and item.get('urn') == urn), None)
        if entry is None or entry.get('status') not in ASSIGNED_STATES:
            raise cleanup_provider.ProviderTransient('project assignment was not confirmed')


def from_token_file(path):
    """``registry_cli.py watchdog --provider do_api:from_token_file --provider-arg /path/to/token``."""
    return DigitalOceanProvider(HttpsTransport(path))
