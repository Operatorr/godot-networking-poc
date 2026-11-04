"""The separately bounded remote authorization that every provider mutation needs (issue #61 §8, gates A/B/C).

The packet is an operator decision recorded in a JSON file: one exact session and manifest, one pair, a time
window, spend/transfer/duration ceilings and an attestation of the token scopes. Nothing in this repository
creates one, and no such packet exists for this slice. Without it the adapter refuses before any byte leaves.

The packet does not gate cleanup. Deleting owned resources needs only exact ids and ownership, because a
deadline must work when no controller or authorization is left. See ``MutationGate``.

Scopes are attested rather than discovered: DigitalOcean exposes no endpoint for reading a token's own scopes,
successful reads say nothing about write scopes, and testing a write scope would itself be a mutation.
"""
import json
import pathlib

import create_evidence
import manifest as manifest_mod
import session_clock

SCHEMA = 'omega.do-session.remote-authorization/1'
GATE_BY_KIND = dict(calibration='A', lifecycle_smoke='B', capacity='C')
# From the operator-confirmed controller set in #62. Only what this lifecycle uses is required.
REQUIRED_CONTROLLER_SCOPES = (
    'account:read', 'actions:read', 'droplet:create', 'droplet:delete', 'droplet:read', 'firewall:create', 'firewall:delete',
    'firewall:read', 'firewall:update', 'image:read', 'project:assign_resource', 'project:read', 'regions:read',
    'sizes:read', 'snapshot:read', 'ssh_key:read', 'tag:create', 'tag:delete', 'tag:read', 'vpc:read')
FIELDS = {'schema', 'gate', 'session_id', 'manifest_sha256', 'operator_request_ref', 'max_pairs', 'not_before_utc', 'not_after_utc',
          'max_session_duration_s', 'max_estimated_session_usd', 'max_estimated_transfer_gib', 'scope_attestation'}
ATTESTATION_FIELDS = {'scopes', 'attested_at', 'controller_token_expires_at', 'watchdog_token_expires_at'}
TAG_CREATES, FIREWALL_CREATES, DROPLET_CREATES = 3, 1, 2
MAX_FIREWALL_UPDATES = 32
MAX_ASSIGNMENTS = 8


class MutationRefused(create_evidence.CreateNotSent):
    """The gate stopped this request, so it certainly never left the process."""


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _epoch(text):
    return session_clock.parse(text)


def validate(packet, manifest, manifest_sha256, now):
    """Return every reason this packet does not authorize mutations for this manifest now."""
    if not isinstance(packet, dict):
        return ['authorization must be a JSON object']
    reasons = []
    for field in sorted(FIELDS - set(packet)):
        reasons.append('authorization is missing ' + field)
    for field in sorted(set(packet) - FIELDS):
        reasons.append('authorization has an unknown field ' + field)
    hits = manifest_mod.scan_for_secrets(packet)
    if hits:
        return ['authorization contains a credential value at ' + ', '.join(hits)]
    if reasons:
        return reasons
    if packet['schema'] != SCHEMA:
        reasons.append('authorization schema is not ' + SCHEMA)
    kind = manifest['session'].get('kind')
    if packet['gate'] != GATE_BY_KIND.get(kind):
        reasons.append('gate %r does not cover a %s session' % (packet['gate'], kind))
    if packet['session_id'] != manifest['session']['id']:
        reasons.append('authorization names a different session')
    if packet['manifest_sha256'] != manifest_sha256:
        reasons.append('authorization names a different manifest')
    if not isinstance(packet['operator_request_ref'], str) or not packet['operator_request_ref'].strip():
        reasons.append('authorization needs an operator request reference')
    if packet['max_pairs'] != 1:
        reasons.append('one authorization covers exactly one pair')
    try:
        if not _epoch(packet['not_before_utc']) <= now < _epoch(packet['not_after_utc']):
            reasons.append('authorization is outside its time window')
    except (TypeError, ValueError):
        reasons.append('authorization window is not a pair of UTC timestamps')
    limits = manifest['limits']
    for field in ('max_session_duration_s', 'max_estimated_session_usd', 'max_estimated_transfer_gib'):
        allowed = packet[field]
        if not isinstance(allowed, (int, float)) or isinstance(allowed, bool) or limits[field] > allowed:
            reasons.append('manifest %s exceeds what was authorized' % field)
    reasons.extend(_attestation_problems(packet['scope_attestation'], limits['max_session_duration_s'], now))
    return reasons


def _attestation_problems(attestation, cap_s, now):
    if not isinstance(attestation, dict) or set(attestation) != ATTESTATION_FIELDS:
        return ['scope attestation must carry exactly its fields']
    problems = []
    scopes = attestation['scopes']
    if not isinstance(scopes, list):
        return ['scope attestation must list the token scopes']
    missing = sorted(set(REQUIRED_CONTROLLER_SCOPES) - set(scopes))
    if missing:
        problems.append('attested scopes lack ' + ', '.join(missing))
    try:
        if _epoch(attestation['attested_at']) > now:
            problems.append('scope attestation is dated in the future')
        for name in ('controller_token_expires_at', 'watchdog_token_expires_at'):
            if _epoch(attestation[name]) <= now + cap_s:
                problems.append(name + ' does not outlast the session deadline')
    except (TypeError, ValueError):
        problems.append('scope attestation timestamps are not UTC timestamps')
    return problems


class MutationGate:
    """Every create, update and assignment passes here, just before the adapter would send it.

    The budget is per process and belongs to one packet, and the payload must be exactly what the manifest
    froze. The registry's intents remain the durable limit: a request with an unknown outcome never gets a retry.
    """

    def __init__(self, packet, manifest, manifest_sha256, wall):
        self.packet = packet
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self.wall = wall
        self.counts = {}
        session = manifest['session']
        self.session_id = session['id']
        self.tags = session['ownership_tags']

    def _refuse(self, reason):
        raise MutationRefused('mutation refused: ' + reason)

    def _spend(self, action, limit):
        self.counts[action] = self.counts.get(action, 0) + 1
        if self.counts[action] > limit:
            self._refuse(action + ' exceeds its authorized count')

    def check(self, action, *details):
        reasons = validate(self.packet, self.manifest, self.manifest_sha256, self.wall())
        if reasons:
            self._refuse('; '.join(reasons))
        getattr(self, '_check_' + action)(*details)

    def _check_create_tag(self, name):
        if name not in self.tags.values():
            self._refuse('tag is not an ownership tag of this session')
        self._spend('create_tag', TAG_CREATES)

    def _check_firewall_targets(self, payload):
        if payload.get('name') != self.session_id + '-fw':
            self._refuse('firewall name is not this session firewall')
        if sorted(payload.get('tags') or []) != sorted((self.tags['game'], self.tags['bot'])):
            self._refuse('firewall must target exactly the two role tags')
        if payload.get('droplet_ids'):
            self._refuse('firewall targets are tags only')

    def _check_create_firewall(self, payload):
        self._check_firewall_targets(payload)
        self._spend('create_firewall', FIREWALL_CREATES)

    def _check_create_droplet(self, payload):
        role = next((r for r in ('game', 'bot') if payload.get('name') == self.session_id + '-' + r), None)
        if role is None:
            self._refuse('droplet name is not a role of this session')
        spec = self.manifest['roles'][role]
        expected = dict(region=spec['region'], size=spec['size_slug'], image=spec['image_id'],
                        ssh_keys=[self.manifest['ssh_key']['id']], tags=[self.tags['session'], self.tags[role]],
                        backups=False, ipv6=False, monitoring=False, with_droplet_agent=False)
        for field, value in expected.items():
            if payload.get(field) != value:
                self._refuse('droplet %s differs from the frozen manifest' % field)
        unknown = set(payload) - set(expected) - {'name', 'user_data'}
        if unknown:
            self._refuse('droplet request has fields outside the frozen shape: ' + ', '.join(sorted(unknown)))
        self._spend('create_droplet', DROPLET_CREATES)

    def _check_update_firewall(self, firewall_id, payload):
        self._check_firewall_targets(payload)
        self._spend('update_firewall', MAX_FIREWALL_UPDATES)

    def _check_assign_droplet(self, project_id, droplet_id):
        if project_id != self.manifest['session']['project_id']:
            self._refuse('project is not the session project')
        self._spend('assign_droplet', MAX_ASSIGNMENTS)
