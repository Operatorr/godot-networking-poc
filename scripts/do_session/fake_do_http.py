"""An offline DigitalOcean account at the HTTP boundary. It makes no network call and holds no credential.

Fixtures drive the real adapter against this, so status mapping, pagination, ownership reads and create semantics are
all exercised by production code. Faults are scripted per route:

  * ``status``: answer that code, with no effect;
  * ``not_sent``: the request never left;
  * ``lost``: the provider acts, possibly later, and the response never arrives;
  * ``garbled``: the provider acts and answers 2xx with no usable record;
  * ``acted_status``: the provider acts and still answers a 5xx.

The account also models accepted deletes that linger, ``new`` Droplets, firewalls that apply later and rules that DO
would reset on a PUT. Requests are logged with their target, never their body. Droplet bodies go to ``droplet_requests``
so tests can scan what a guest would have received.
"""
import json
import re
import urllib.parse

import do_api
import fixture_support as fx
import guest_bootstrap

PUBLIC_KEY_PATH = guest_bootstrap.PUBLIC_KEY_PATH


class FakeDoAccount:
    offline_fixture = True

    def __init__(self, clock, max_per_page=200, active_after_s=30.0, firewall_settle_s=5.0):
        self.clock = clock
        self.max_per_page = max_per_page
        self.active_after_s = active_after_s
        self.firewall_settle_s = firewall_settle_s
        facts = fx.preflight()
        self.project = dict(id=facts['project']['id'], name=facts['project']['name'])
        self.account = dict(droplet_limit=facts['account']['droplet_limit'], status='active')
        self.regions = [dict(r) for r in facts['regions']]
        self.sizes = [dict(slug=s['slug'], vcpus=s['vcpus'], memory=s['memory_mib'], disk=s['disk_gib'], price_hourly=s['price_hourly_usd'],
                           price_monthly=s['price_monthly_usd'], transfer=s['transfer_tib_month'], regions=s['regions'],
                           available=s['available'], description='fixture') for s in facts['sizes']]
        self.images = {i['id']: dict(id=i['id'], name=i['name'], distribution=i['distribution'], public=True, type='base', status='available',
                                     min_disk_size=i['min_disk_gib'], regions=i['regions']) for i in facts['images']}
        key = facts['ssh_keys'][0]
        self.ssh_keys = {key['id']: dict(id=key['id'], name=key['name'], fingerprint='00:00', public_key=PUBLIC_KEY_PATH.read_text().strip())}
        self.droplets, self.firewalls, self.tags = {}, {}, {}
        self.project_urns = set()
        self.next_droplet = 500000
        self.next_firewall = 1
        self.requests = []
        self.droplet_requests = []
        self.rules = []
        self.scheduled = []
        self.wrong_size = {}
        self.linger_reads = 0
        self.assignment_status = 'assigned'
        self.next_address = 10

    # ---- fixture controls --------------------------------------------------------------------

    def seed_unrelated(self):
        """Things that a session must never touch, some of them in the same project."""
        self.tags['omega-management'] = dict(name='omega-management')
        self.tags['prod'] = dict(name='prod')
        management = self._new_droplet(dict(name='omega-management-1', size='s-1vcpu-512mb-10gb', region='sgp1', image=247516813, tags=['omega-management']))
        unrelated = self._new_droplet(dict(name='prod-api', size='s-2vcpu-2gb-amd', region='sgp1', image=247516813, tags=['prod']))
        for droplet in (management, unrelated):
            droplet['status'] = 'active'
            self.project_urns.add('do:droplet:%d' % droplet['id'])
        wall = self._new_firewall(dict(name='prod-fw', tags=['prod'], droplet_ids=[], inbound_rules=[], outbound_rules=[]))
        return dict(droplets=[management['id'], unrelated['id']], firewall=wall['id'], tags=['omega-management', 'prod'])

    def fault(self, method, pattern, action, times=None, status=None, land=True, delay_s=0.0, headers=None):
        """``headers`` go out with a ``status`` answer, so a scripted 429 can carry the provider's own retry guidance."""
        rule = dict(method=method, pattern=re.compile(pattern), action=action, times=times, status=status, land=land, delay_s=delay_s, headers=headers)
        self.rules.append(rule)
        return rule

    def clear_faults(self):
        self.rules = []

    def outage(self, status=503):
        return self.fault(None, '.*', 'status', status=status)

    def ops(self, method=None, pattern='.*'):
        return [r for r in self.requests if (method is None or r['method'] == method) and re.search(pattern, r['path'])]

    def mutations(self):
        return [r for r in self.requests if r['method'] != 'GET']

    def live(self):
        return dict(droplets=sorted(str(i) for i in self.droplets), firewalls=sorted(self.firewalls), tags=sorted(self.tags))

    def advance_landings(self):
        now = self.clock.wall()
        due = [item for item in self.scheduled if item[0] <= now]
        self.scheduled = [item for item in self.scheduled if item[0] > now]
        for _, effect in due:
            effect()

    # ---- the wire ----------------------------------------------------------------------------

    def __call__(self, method, target, body=None, request_bound_s=None, send_by=None, send_guard=None):
        if send_guard is not None:
            send_guard.confirm()        # what the transport does immediately before the first request byte
        self.advance_landings()
        parsed = urllib.parse.urlsplit(target)
        path = parsed.path
        query = dict(urllib.parse.parse_qsl(parsed.query))
        payload = json.loads(body) if body is not None else None
        entry = dict(method=method, path=path, tag=query.get('tag_name'), at=self.clock.wall(), bound=request_bound_s, send_by=send_by is not None)
        self.requests.append(entry)
        if method == 'POST' and path == '/v2/droplets':
            self.droplet_requests.append(payload)
        rule = next((r for r in self.rules if r['times'] != 0 and r['method'] in (None, method) and r['pattern'].search(path)), None)
        if rule is not None and rule['times'] is not None:
            rule['times'] -= 1
        effect = lambda: self._route(method, path, query, payload)   # noqa: E731
        if rule is None:
            response = effect()
            entry['status'] = response.status
            return response
        entry['fault'] = rule['action']
        if rule['action'] == 'status':
            entry['status'] = rule['status']
            return self._reply(rule['status'], dict(id='fixture_fault', message='scripted fault'), rule.get('headers'))
        if rule['action'] == 'not_sent':
            raise do_api.RequestNotSent('scripted: connect failed')
        if rule['action'] == 'lost':
            if rule['land']:
                if rule['delay_s']:
                    self.scheduled.append((self.clock.wall() + rule['delay_s'], effect))
                else:
                    effect()
            raise do_api.RequestOutcomeUnknown('scripted: response lost')
        response = effect()
        if rule['action'] == 'garbled':
            entry['status'] = 202
            return do_api.HttpResponse(202, {}, b'{}')
        entry['status'] = rule['status']
        return self._reply(rule['status'], dict(id='fixture_fault', message='scripted fault after acting'))

    @staticmethod
    def _reply(status, document=None, headers=None):
        return do_api.HttpResponse(status, headers or {}, b'' if document is None else json.dumps(document).encode('utf-8'))

    def _not_found(self):
        return self._reply(404, dict(id='not_found', message='The resource you requested could not be found.'))

    def _page(self, key, items, query):
        per_page = min(int(query.get('per_page', 20)), self.max_per_page)
        page = int(query.get('page', 1))
        chunk = items[(page - 1) * per_page: page * per_page]
        pages = {'next': 'https://api.digitalocean.com/ignored?page=%d' % (page + 1)} if page * per_page < len(items) else {}
        return self._reply(200, {key: chunk, 'links': dict(pages=pages), 'meta': dict(total=len(items))})

    def _route(self, method, path, query, payload):
        parts = [urllib.parse.unquote(p) for p in path.strip('/').split('/')[1:]]
        handler = getattr(self, '_route_' + parts[0], None)
        if handler is None:
            raise AssertionError('the adapter sent an unmodelled route: ' + path)
        return handler(method, parts[1:], query, payload)

    # ---- account facts -----------------------------------------------------------------------

    def _route_account(self, method, parts, query, payload):
        if not parts:
            return self._reply(200, dict(account=self.account))
        key = self.ssh_keys.get(int(parts[1]))
        return self._reply(200, dict(ssh_key=key)) if key else self._not_found()

    def _route_regions(self, method, parts, query, payload):
        return self._page('regions', self.regions, query)

    def _route_sizes(self, method, parts, query, payload):
        return self._page('sizes', self.sizes, query)

    def _route_images(self, method, parts, query, payload):
        image = self.images.get(int(parts[0]))
        return self._reply(200, dict(image=image)) if image else self._not_found()

    def _route_projects(self, method, parts, query, payload):
        if parts[0] != self.project['id']:
            return self._not_found()
        if len(parts) == 1:
            return self._reply(200, dict(project=self.project))
        if method == 'GET':
            return self._page('resources', [dict(urn=u, status='ok') for u in sorted(self.project_urns)], query)
        for urn in payload['resources']:
            if self.assignment_status in do_api.ASSIGNED_STATES:
                self.project_urns.add(urn)
        return self._reply(200, dict(resources=[dict(urn=u, status=self.assignment_status) for u in payload['resources']]))

    # ---- droplets ----------------------------------------------------------------------------

    def _view(self, droplet):
        return {k: v for k, v in droplet.items() if not k.startswith('_')}

    def _new_droplet(self, payload):
        identifier = self.next_droplet
        self.next_droplet += 1
        self.next_address += 1
        slug = self.wrong_size.get(payload['name'], payload['size'])
        size = next((s for s in self.sizes if s['slug'] == slug), dict(vcpus=1, memory=512, disk=10))
        droplet = dict(id=identifier, name=payload['name'], tags=list(payload['tags']), status='new', size_slug=slug, region=dict(slug=payload['region']),
                       image=dict(id=payload['image']), vcpus=size['vcpus'], memory=size['memory'], disk=size['disk'],
                       networks=dict(v4=[dict(type='public', ip_address='198.51.100.%d' % self.next_address)]),
                       _active_at=self.clock.wall() + self.active_after_s, _deleting=False, _linger=0)
        self.droplets[identifier] = droplet
        for tag in payload['tags']:
            self.tags.setdefault(tag, dict(name=tag))
        return droplet

    def _refresh(self, droplet):
        if droplet['status'] == 'new' and self.clock.wall() >= droplet['_active_at']:
            droplet['status'] = 'active'

    def _route_droplets(self, method, parts, query, payload):
        if not parts:
            if method == 'POST':
                return self._reply(202, dict(droplet=self._view(self._new_droplet(payload))))
            items = [d for d in self.droplets.values() if 'tag_name' not in query or query['tag_name'] in d['tags']]
            for droplet in items:
                self._refresh(droplet)
            return self._page('droplets', [self._view(d) for d in items], query)
        droplet = self.droplets.get(int(parts[0]))
        if droplet is None:
            return self._not_found()
        if len(parts) == 2:
            applied = [f for f in self.firewalls.values() if set(f['tags']) & set(droplet['tags']) or droplet['id'] in f['droplet_ids']]
            return self._page('firewalls', [self._firewall_view(f) for f in applied], query)
        if method == 'DELETE':
            if not droplet['_deleting']:
                droplet['_deleting'], droplet['_linger'] = True, self.linger_reads
            return self._reply(204)
        if droplet['_deleting']:
            if droplet['_linger'] <= 0:
                del self.droplets[int(parts[0])]
                return self._not_found()
            droplet['_linger'] -= 1
        self._refresh(droplet)
        return self._reply(200, dict(droplet=self._view(droplet)))

    # ---- firewalls ---------------------------------------------------------------------------

    def _new_firewall(self, payload):
        identifier = '%08x-0000-4000-8000-000000000000' % self.next_firewall
        self.next_firewall += 1
        firewall = dict(id=identifier, status='waiting', pending_changes=[], _settles_at=self.clock.wall() + self.firewall_settle_s)
        self._apply_firewall(firewall, payload)
        self.firewalls[identifier] = firewall
        return firewall

    def _apply_firewall(self, firewall, payload):
        """A PUT is a full replacement: whatever is left out goes back to its default."""
        firewall.update(name=payload.get('name'), tags=list(payload.get('tags') or []), droplet_ids=list(payload.get('droplet_ids') or []),
                        inbound_rules=list(payload.get('inbound_rules') or []), outbound_rules=list(payload.get('outbound_rules') or []),
                        status='waiting', _settles_at=self.clock.wall() + self.firewall_settle_s)

    def _firewall_view(self, firewall):
        if firewall['status'] == 'waiting' and self.clock.wall() >= firewall['_settles_at']:
            firewall['status'] = 'succeeded'
        return {k: v for k, v in firewall.items() if not k.startswith('_')}

    def _route_firewalls(self, method, parts, query, payload):
        if not parts:
            if method == 'POST':
                return self._reply(202, dict(firewall=self._firewall_view(self._new_firewall(payload))))
            return self._page('firewalls', [self._firewall_view(f) for f in self.firewalls.values()], query)
        firewall = self.firewalls.get(parts[0])
        if firewall is None:
            return self._not_found()
        if method == 'DELETE':
            del self.firewalls[parts[0]]
            return self._reply(204)
        if method == 'PUT':
            self._apply_firewall(firewall, payload)
        return self._reply(200, dict(firewall=self._firewall_view(firewall)))

    # ---- tags --------------------------------------------------------------------------------

    def _route_tags(self, method, parts, query, payload):
        if not parts:
            self.tags.setdefault(payload['name'], dict(name=payload['name']))
            return self._reply(201, dict(tag=dict(name=payload['name'], resources=dict(count=0))))
        name = parts[0]
        if name not in self.tags:
            return self._not_found()
        if method == 'DELETE':
            del self.tags[name]
            for droplet in self.droplets.values():
                if name in droplet['tags']:
                    droplet['tags'].remove(name)
            return self._reply(204)
        count = sum(1 for d in self.droplets.values() if name in d['tags']) + sum(1 for f in self.firewalls.values() if name in f['tags'])
        return self._reply(200, dict(tag=dict(name=name, resources=dict(count=count))))
