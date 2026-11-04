"""Offline stand-in for the provider seam. It makes no network call and needs no credential.

``FakeProvider`` keeps fake resources in memory, or in a JSON file so a crashed process and its
restarted successor see one account. Faults are scripted per operation, and every request is logged
so fixtures can assert exactly what the watchdog did, and did not, attempt.
"""
import json
import os
import pathlib
import threading

import cleanup_provider
import create_evidence


class FakeProvider(cleanup_provider.CleanupProvider):
    offline_fixture = True      # the service CLI refuses this unless explicitly allowed

    def __init__(self, path=None, clock=None):
        self.path = pathlib.Path(path) if path else None
        self.clock = clock
        self.lock = threading.RLock()
        self.data = dict(droplets={}, firewalls={}, tags={}, next_id=5000000, ops=[])
        self.ops = []
        self.faults = []
        self.linger_reads = 0
        self.blockers = {}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text())

    # ---- fixture controls --------------------------------------------------------------------

    def _save(self):
        if self.path:
            temporary = self.path.with_name(self.path.name + '.tmp')
            temporary.write_text(json.dumps(self.data, sort_keys=True))
            os.replace(temporary, self.path)

    def add_droplet(self, name, tags, project='omega.realm', droplet_id=None):
        with self.lock:
            if droplet_id is None:
                droplet_id = str(self.data['next_id'])
                self.data['next_id'] += 1
            self.data['droplets'][str(droplet_id)] = dict(id=str(droplet_id), name=name, tags=list(tags), project=project,
                                                          status='active', linger=0)
            for tag in tags:
                self.data['tags'].setdefault(tag, dict(name=tag))
            self._save()
            return str(droplet_id)

    def add_firewall(self, name, tags=(), droplet_ids=(), firewall_id=None):
        with self.lock:
            if firewall_id is None:
                firewall_id = 'fw-' + str(self.data['next_id'])
                self.data['next_id'] += 1
            self.data['firewalls'][firewall_id] = dict(id=firewall_id, name=name, tags=list(tags), droplet_ids=list(droplet_ids))
            self._save()
            return firewall_id

    def add_tag(self, name):
        with self.lock:
            self.data['tags'].setdefault(name, dict(name=name))
            self._save()

    def fail(self, error_factory, op=None, target=None, times=None):
        """Script ``error_factory()`` for matching requests, ``times`` times or until cleared."""
        rule = dict(factory=error_factory, op=op, target=target, remaining=times)
        self.faults.append(rule)
        return rule

    def clear_faults(self):
        self.faults = []

    def issue_receipt(self, ref, terminal=create_evidence.NOT_CREATED, resource_id=None):
        """The fixture decides when a request is finished. Until then there is no receipt to read."""
        with self.lock:
            self.data.setdefault('receipts', {})[ref] = self.offline_receipt(ref, terminal, resource_id)
            self._save()

    def answer_all_requests(self):
        """Crash fixtures: every request has finished, so a receipt reports what the account really holds."""
        with self.lock:
            self.data['answer_all_requests'] = True
            self._save()

    def note_create(self, ref, resource_id):
        with self.lock:
            self.data.setdefault('landed', {})[ref] = str(resource_id)
            self._save()

    @staticmethod
    def offline_receipt(ref, terminal, resource_id=None):
        return create_evidence.receipt(ref, terminal, create_evidence.OFFLINE_FIXTURE_RECEIPT, 'fake-operation:' + ref, resource_id)

    def block(self, op, target):
        """Make a matching request hang until the returned event is set."""
        event = threading.Event()
        self.blockers[(op, str(target))] = event
        return event

    def ops_named(self, *names):
        return [entry for entry in self.ops if entry['op'] in names]

    def live_ids(self):
        return dict(droplets=sorted(self.data['droplets']), firewalls=sorted(self.data['firewalls']), tags=sorted(self.data['tags']))

    # ---- request plumbing --------------------------------------------------------------------

    def _request(self, op, target):
        with self.lock:
            if self.path and self.path.exists():
                self.data = json.loads(self.path.read_text())   # another process may share this account
            self.ops.append(dict(op=op, target=str(target), at=self.clock.wall() if self.clock else None))
            if self.path:
                self.data.setdefault('ops', []).append(self.ops[-1])
                self._save()
            for rule in self.faults:
                if (rule['op'] in (None, op)) and (rule['target'] in (None, str(target))) and rule['remaining'] != 0:
                    if rule['remaining'] is not None:
                        rule['remaining'] -= 1
                    raise rule['factory']()
        blocker = self.blockers.get((op, str(target)))
        if blocker is not None:
            blocker.wait(30)

    def _tag_count(self, name):
        return sum(1 for d in self.data['droplets'].values() if name in d['tags'])

    # ---- CleanupProvider ---------------------------------------------------------------------

    def get_droplet(self, droplet_id):
        self._request('get_droplet', droplet_id)
        with self.lock:
            droplet = self.data['droplets'].get(str(droplet_id))
            if droplet is None:
                return None
            if droplet.get('deleting'):
                if droplet['linger'] <= 0:
                    del self.data['droplets'][str(droplet_id)]
                    self._save()
                    return None
                droplet['linger'] -= 1
                self._save()
            return {k: droplet[k] for k in ('id', 'name', 'tags', 'status')}

    def delete_droplet(self, droplet_id):
        self._request('delete_droplet', droplet_id)
        with self.lock:
            droplet = self.data['droplets'].get(str(droplet_id))
            if droplet is not None and not droplet.get('deleting'):
                droplet['deleting'] = True
                droplet['linger'] = self.linger_reads
                self._save()

    def list_droplets_by_tag(self, tag):
        self._request('list_droplets_by_tag', tag)
        with self.lock:
            return [{k: d[k] for k in ('id', 'name', 'tags', 'status')} for d in self.data['droplets'].values() if tag in d['tags']]

    def get_firewall(self, firewall_id):
        self._request('get_firewall', firewall_id)
        with self.lock:
            firewall = self.data['firewalls'].get(str(firewall_id))
            return dict(firewall) if firewall else None

    def delete_firewall(self, firewall_id):
        self._request('delete_firewall', firewall_id)
        with self.lock:
            self.data['firewalls'].pop(str(firewall_id), None)
            self._save()

    def list_firewalls_by_name(self, name):
        self._request('list_firewalls_by_name', name)
        with self.lock:
            return [dict(f) for f in self.data['firewalls'].values() if f['name'] == name]

    def get_tag(self, name):
        self._request('get_tag', name)
        with self.lock:
            if name not in self.data['tags']:
                return None
            return dict(name=name, resource_count=self._tag_count(name))

    def delete_tag(self, name):
        self._request('delete_tag', name)
        with self.lock:
            self.data['tags'].pop(name, None)
            self._save()

    def get_request_settlement(self, request_ref):
        self._request('get_request_settlement', request_ref)
        with self.lock:
            issued = self.data.get('receipts', {}).get(request_ref)
            if issued is not None or not self.data.get('answer_all_requests'):
                return issued
            landed = self.data.get('landed', {}).get(request_ref)
            if landed is not None:
                return self.offline_receipt(request_ref, create_evidence.CREATED, landed)
            return self.offline_receipt(request_ref, create_evidence.NOT_CREATED)


def from_file(path):
    """``--provider fake_provider:from_file`` for offline process-level fixtures only."""
    return FakeProvider(path)
