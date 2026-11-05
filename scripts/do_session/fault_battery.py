#!/usr/bin/env python3
"""The integrated offline fault battery for handoff slice 8 (issue #71): whole sessions with faults at several boundaries at once.

    fault_battery.py --out DIR

Every scenario drives one session through the real planner admission, registry, watchdog, provisioner and DigitalOcean adapter, the
real run executor and guest runner contract, the real window prover and scorer, and the real exporter and report, and keeps going until
the registry closes the session or a stated boundary leaves it open. What is fake: the DigitalOcean account (``fake_do_http``, at the HTTP
boundary), the guests (``fake_run_guest``, behind the SSH seam), the recorder files a run leaves (``measurement_fixtures``), and one
scripted clock. Faults are injected where the real code meets those fakes: HTTP answers, guest commands and transfers, crash points
the production code already names, the management host's clock and restarts, and the local file system.

Each row keeps what was observed, not what was hoped for: the registry's journal as a timeline, every provider mutation and a count of
reads, the session's resources at named moments, guest starts and transfers, run records, and the three independent results. ``checks``
are assertions on those observations, and ``invariants`` are the same eight assertions for every session. ``test_fault_battery``
regenerates the file, compares its hash, and asserts every check and invariant. No raw recorder byte is kept, and nothing here measured
any host: every number is fixture arithmetic on a scripted clock.
"""
import argparse
import collections
import contextlib
import errno
import hashlib
import json
import pathlib
import re
import sys
import types
import unittest
import urllib.parse
from unittest import mock

import do_api
import evidence_publication as ep
import export_fixtures as ef
import fake_do_http
import fixture_support as fx
import provision_fixtures as pf
import provisioner
import registry
import remote_authorization
import run_executor
import run_fixtures as rf
import scoring_fixtures as sf
import search
import session_clock
import session_export as se

SCHEMA = 'omega.do-session.fault-battery/1'
NOTE = ('Synthetic. Nothing ran on any host: a fake DigitalOcean account at the HTTP boundary, fake guests behind the SSH seam and '
        'fixture recorder files, on one scripted clock, through the real planner admission, registry, watchdog, provisioner, adapter, '
        'executor, prover, scorer and exporter. Every number is fixture arithmetic and says nothing about any host, capacity or cost.')
ORIGIN = fx.T0_WALL
NOISY_EVENTS = frozenset(('run_progress', 'guest_grant_issued', 'guest_grant_started'))
EVENT_FIELDS = ('run_id', 'outcome', 'status', 'reason', 'code', 'first_failure', 'deadline', 'resource_key', 'intent_id', 'state', 'takeover', 'token', 'target_state', 'decision')

# Issue #71's acceptance criteria, and the points of the accepted contracts the parent asked to be shown together. Each scenario names the ones it covers.
REQUIREMENTS = collections.OrderedDict((
    ('composed_real_transitions', 'Fake API, SSH, clock, process and storage backends composed through the real controller transitions, with timelines, calls, inventories and final states retained'),
    ('partial_create', 'A partial pair stops the batch and cleans every owned resource'),
    ('ambiguous_create', 'A lost or garbled create response is reconciled by unique intent/tag before anything is retried'),
    ('late_create', 'A create that lands after its timeout is discovered and deleted before closure'),
    ('wrong_ownership', 'Ownership disagreement opens an incident and deletes nothing it cannot prove is the session\'s'),
    ('controller_laptop_disappearance', 'The runner and laptop vanish; cleanup still happens by C'),
    ('watchdog_restart', 'A watchdog process restart loses no pending state'),
    ('watchdog_reboot', 'A management-host reboot keeps deadlines, or fails closed when its clock cannot be trusted'),
    ('stale_fencing', 'A stale controller cannot dispatch after takeover'),
    ('retry_fairness', 'One failing session\'s retries never starve another session\'s deletion'),
    ('rate_limits', 'Provider rate-limit guidance is honoured without abandoning cleanup'),
    ('deletion_outage', 'A deletion outage produces retries, not a false clean'),
    ('deadline_exhaustion', 'Insufficient remaining time stops the search as partial with no extension'),
    ('persistent_overdue_cleanup', 'Past D, surviving resources keep a durable overdue incident with exact ids, attempts and errors'),
    ('interrupted_resume', 'An interrupted active run is kept incomplete and never replayed'),
    ('eligible_resume', 'An explicit resume runs only untouched, independently eligible work after revalidation'),
    ('ineligible_resume', 'Resume is refused after a terminal failure, cleanup, C or exhausted headroom'),
    ('dependent_path_uncertainty', 'An incomplete trial whose successor depends on it stops that path'),
    ('genuine_server_failure', 'A demonstrated game-host failure advances only the frozen search'),
    ('invalid_generator_load', 'Invalid offered load stops the batch and establishes nothing'),
    ('clock_gap', 'A clock gap or reboot cannot prove a pass'),
    ('socket_gap', 'Missing socket counters cannot prove a pass'),
    ('failed_confirmation', 'A failed confirmation leaves the candidate unconfirmed with no replacement trial'),
    ('corrupt_evidence', 'Corrupt bytes are never promoted to verified evidence'),
    ('incomplete_evidence', 'Missing evidence keeps every result honest and still reaches cleanup'),
    ('rejected_admission_creates_nothing', 'A rejected admission or unacknowledged watchdog creates no provider resource'),
    ('no_unrelated_deletion', 'No unrelated, retained or management resource is ever mutated'),
    ('no_duplicate_run', 'No run is started twice, overwritten or replayed'),
    ('independent_cleanup_without_runner', 'Cleanup needs no runner, laptop or SSH key'),
    ('no_hidden_retry', 'No create, trial or confirmation is silently repeated'),
    ('no_deadline_extension', 't0, C and D never move, through restarts, clock steps and recovery'),
    ('clean_only_after_owned_absence', 'Clean closure only after authenticated absence of every owned resource and settlement of every create'),
    ('orphan_operator_disposition', 'An unsettled create is closed only by an explicit operator disposition, which never reads clean'),
    ('accepted_delete_not_absence', 'An accepted DELETE is not proof of destruction'),
    ('revocation_pending_handoff', 'A takeover is pending until the guests acknowledge the new fence'),
    ('terminal_fact_through_recovery', 'A demonstrated terminal failure survives crashes and recovery and blocks resume'),
    ('source_frozen', 'Code other than the frozen revision dispatches nothing and the deadline still arrives'),
    ('publication_truth', 'Raw evidence is never published; local preparation is not publication'),
    ('independent_results', 'Measurement, evidence completeness and cleanup stay independent results'),
    ('no_claim_on_unknown', 'Nothing unknown, partial or unverified becomes a capacity claim'),
))


class _Case(unittest.TestCase):
    """The fixtures take a TestCase, for its cleanups and its one assertion on scripted time."""

    def runTest(self):
        pass


# ---- observation ------------------------------------------------------------------------------------

@contextlib.contextmanager
def named_requests():
    """Remember which resource name each provider request carried, without changing what the fake logs (retained slice 3 files depend on that)."""
    original = fake_do_http.FakeDoAccount.__call__

    def call(self, method, target, body=None, **options):
        names = self.__dict__.setdefault('_battery_names', {})
        index = len(self.requests)
        try:
            names[index] = json.loads(body).get('name') if body is not None else None
        except (ValueError, AttributeError):
            names[index] = None
        return original(self, method, target, body, **options)
    with mock.patch.object(fake_do_http.FakeDoAccount, '__call__', call):
        yield


def t_of(wall):
    return round(wall - ORIGIN, 3)


def t_of_text(text):
    return None if text is None else t_of(session_clock.parse(text))


class Names:
    """Provider ids as the names the session gave them, so a row reads the same on any run and says what was touched."""

    def __init__(self, account):
        self.account = account
        self.droplets, self.firewalls = {}, {}
        self.note()
        original_droplet, original_firewall = account._new_droplet, account._new_firewall

        def new_droplet(payload):
            droplet = original_droplet(payload)
            self.droplets[str(droplet['id'])] = droplet['name']
            return droplet

        def new_firewall(payload):
            firewall = original_firewall(payload)
            self.firewalls[firewall['id']] = firewall['name']
            return firewall
        account._new_droplet, account._new_firewall = new_droplet, new_firewall

    def note(self):
        for identifier, droplet in self.account.droplets.items():
            self.droplets.setdefault(str(identifier), droplet['name'])
        for identifier, firewall in self.account.firewalls.items():
            self.firewalls.setdefault(identifier, firewall['name'])

    def path(self, path):
        parts = [urllib.parse.unquote(p) for p in path.split('/')]
        if len(parts) > 3 and parts[2] == 'droplets':
            parts[3] = '{%s}' % self.droplets.get(parts[3], 'droplet?')
        elif len(parts) > 3 and parts[2] == 'firewalls':
            parts[3] = '{%s}' % self.firewalls.get(parts[3], 'firewall?')
        elif len(parts) > 3 and parts[2] == 'projects':
            parts[3] = '{project}'
        return '/'.join(parts)


class Observed:
    """One session's row: what the registry, the account, the guests and the exporter say happened."""

    def __init__(self, sim, names, label):
        self.sim, self.names, self.label = sim, names, label
        self.marks = []
        self.extra = {}

    @property
    def armed(self):
        """What the registry acknowledged to the provisioner when it armed the session, before the first create."""
        if not self.sim.armed_acks:
            return None
        ack = self.sim.armed_acks[0]
        return dict(t0=ack['t0_utc'], c=ack['cleanup_c_utc'], d=ack['deadline_d_utc'])

    @property
    def session_id(self):
        return self.sim.session_id

    def owned_live(self):
        """What the account holds that carries this session's name or tag, whatever the registry thinks of it."""
        sid = self.session_id
        tags = set(self.sim.manifest['session']['ownership_tags'].values())
        droplets = sorted('%s:%s' % (d['name'], 'deleting' if d.get('_deleting') else d['status']) for d in self.sim.account.droplets.values() if d['name'].startswith(sid) or tags & set(d['tags']))
        firewalls = sorted(f['name'] for f in self.sim.account.firewalls.values() if (f['name'] or '').startswith(sid))
        return dict(droplets=droplets, firewalls=firewalls, tags=sorted(t for t in self.sim.account.tags if t in tags))

    def mark(self, label):
        self.marks.append(dict(t_s=t_of(self.sim.clock.wall()), label=label, owned=self.owned_live(), state=self._state(), unrelated_intact=self.sim.unrelated_intact()))

    def _state(self):
        try:
            return self.sim.stack.registry.status(self.session_id)['state']
        except Exception:     # not registered: the honest answer is that the registry has never heard of it
            return None

    def timeline(self):
        rows = []
        try:
            journal = self.sim.stack.registry.journal(self.session_id)
        except Exception:
            return rows
        for event in journal:
            if event['kind'] in NOISY_EVENTS:
                continue
            data = event.get('data') or {}
            row = dict(t_s=t_of_text(event['at']), kind=event['kind'])
            row.update({key: data[key] for key in EVENT_FIELDS if key in data and isinstance(data[key], (str, int, float, bool, type(None)))})
            if isinstance(data.get('kind'), str):
                row['subject'] = data['kind']     # an incident's or a resource's own kind, kept apart from the event's
            rows.append(row)
        return rows

    def attempts(self):
        rows = self.sim.stack.registry.attempts(self.session_id)
        bursts = collections.Counter((row['resource_key'], row['sweep_seq']) for row in rows)
        errors = collections.Counter('%s %s' % (row['op'], row['http_status'] or row['error_class']) for row in rows if row['result'] == 'error')
        return dict(total=len(rows), max_burst_attempt=max((row['burst_attempt'] for row in rows), default=0), max_per_resource_sweep=max(bursts.values(), default=0), errors=dict(sorted(errors.items())))

    def deletes(self):
        """Every DELETE that named one of this session's resources, whatever it answered."""
        return [r for r in self.sim.account.requests if r['method'] == 'DELETE' and self.session_id in self.names.path(r['path'])]

    def row(self):
        sim = self.sim
        self.names.note()
        try:
            status = sim.stack.registry.status(self.session_id)
        except Exception:
            status = None
        records = sim.stack.registry.run_records(self.session_id) if status else []
        latest, report = self._export()
        results = report.get('results') or {}
        measurement = results.get('measurement') or {}
        claim = measurement.get('claim') or {}
        row = dict(registered=status is not None)
        if status is not None:
            row.update(state=status['state'], overall=status['overall'], terminal_failure=status['terminal_failure'],
                       t0_s=t_of_text(status['t0_utc']), c_s=t_of_text(status['cleanup_c_utc']), d_s=t_of_text(status['deadline_d_utc']),
                       measurement=status['measurement']['outcome'], evidence=status['evidence']['status'],
                       cleanup=dict(outcome=status['cleanup']['outcome'], requested_s=t_of_text(status['cleanup']['requested_at']), reason=status['cleanup']['reason'],
                                    verified_s=t_of_text(status['cleanup']['verified_at']), overdue=status['cleanup']['overdue'], overrun_s=status['cleanup']['overrun_s'],
                                    unresolved_creates=len(status['cleanup']['unresolved_creates'])),
                       resources=[dict(kind=r['kind'], name=r['name'], source=r['source'], status=r['status'], attempts=r['attempts'], last_error=r['last_error']) for r in status['resources']],
                       incidents=[dict(kind=i['kind'], status=i['status']) for i in status['incidents']],
                       runs=[dict(run=r['run_id'].split('-', 4)[-1], outcome=r['outcome'], phase=r['phase'], interrupted=r.get('interrupted_reason')) for r in records],
                       attempts=self.attempts(), timeline=self.timeline())
        row.update(search_status=measurement.get('search_status'), claim=dict(kind=claim.get('kind'), players=claim.get('players'), confirmed=claim.get('confirmed')) if claim else None,
                   establishes=report.get('establishes'), export_status=latest.get('status'), generations=self._generations(),
                   start_requests=dict(collections.Counter(c['role'] for c in starts_of(sim))), processes_started=dict(collections.Counter(role for role, _ in ledger_starts(sim))),
                   transfers=sum(1 for c in getattr(sim.guests, 'commands', ()) if c.get('step') == 'get'),
                   marks=self.marks, owned_at_end=self.owned_live(), armed=dict((k, t_of_text(v)) for k, v in self.armed.items()) if self.armed else None)
        if self._generations():
            row['publication'] = ep.publication_status(self.root)['status']
        row['invariants'] = invariants(self, row, status, records)
        row.update(self.extra)
        return row

    @property
    def root(self):
        return getattr(self.sim, 'session_root', self.sim.stack.root)

    def _generations(self):
        root = self.root / se.EXPORT_DIR
        return sorted(p.name for p in root.glob('gen-*') if p.is_dir() and '.writing-' not in p.name) if root.exists() else []

    def _export(self):
        generations = self._generations()
        if not generations:
            return {}, {}
        generation = self.root / se.EXPORT_DIR / generations[-1]
        latest = json.loads((generation / 'inventory.json').read_text())
        report = json.loads((generation / se.REPORT_JSON).read_text()) if (generation / se.REPORT_JSON).exists() else {}
        return latest, report


INVARIANTS = ('unrelated_untouched', 'one_request_per_create', 'runs_unique_and_started_once', 'trial_ceiling', 'deadlines_unchanged', 'clean_only_when_complete_and_absent',
              'closed_only_when_owned_absent', 'claims_only_on_complete_confirmed')


def starts_of(sim):
    return sim.guests.starts() if hasattr(sim.guests, 'starts') else []


def ledger_starts(sim):
    """(role, run id) for every process a fake guest really started. A provisioning-only session's guests start none."""
    hosts = getattr(sim.guests, 'hosts', None)
    return [] if hosts is None else [(e['role'], e['run_id']) for role in ('game', 'bot') for e in hosts[role].ledger if 'processes' in e]


def invariants(observed, row, status, records):
    """The same eight promises for every session, judged on what was observed."""
    sim = observed.sim
    account = sim.account
    created = collections.Counter(account._battery_names.get(i) for i, r in enumerate(account.requests) if r['method'] == 'POST' and r['path'] in ('/v2/droplets', '/v2/firewalls', '/v2/tags'))
    own_created = {name: count for name, count in created.items() if name and observed.session_id in name}
    run_ids = [r['run_id'] for r in records]
    starts = collections.Counter(ledger_starts(sim))
    found = dict(
        unrelated_untouched=sim.unrelated_intact() and sim.session_mutation_targets_only(),
        one_request_per_create=all(count == 1 for count in own_created.values()),
        runs_unique_and_started_once=len(run_ids) == len(set(run_ids)) and all(count == 1 for count in starts.values()),
        trial_ceiling=len(records) <= search.MAX_TRIALS_PER_CONDITION and sum(1 for r in records if r['phase'] == search.CONFIRM) <= 3,
        deadlines_unchanged=observed.armed is None or status is None or (observed.armed == dict(t0=status['t0_utc'], c=status['cleanup_c_utc'], d=status['deadline_d_utc'])),
        clean_only_when_complete_and_absent=row.get('overall') != 'clean' or (row.get('evidence') == 'complete' and observed.owned_live() == dict(droplets=[], firewalls=[], tags=[]) and row['cleanup']['unresolved_creates'] == 0),
        closed_only_when_owned_absent=row.get('state') != registry.CLOSED or observed.owned_live() == dict(droplets=[], firewalls=[], tags=[]),
        claims_only_on_complete_confirmed=not row.get('establishes') or (row.get('export_status') == 'complete' and row.get('search_status') in ('confirmed', 'confirmed_search_cap_reached') and (row.get('claim') or {}).get('confirmed') is True),
    )
    assert tuple(found) == INVARIANTS
    return found


# ---- scenario helpers -------------------------------------------------------------------------------

def checker(checks):
    def check(label, condition):
        checks[label] = bool(condition)
    return check


def session(case, names_holder, label='main', script=None, **options):
    sim = ef.ExportSim(case, script if script is not None else ef.enriched(ef.CONFIRMING), **options)
    names = names_holder.setdefault('names', Names(sim.account))
    observed = Observed(sim, names, label)
    return sim, observed


def to_wall(text):
    return session_clock.parse(text)


def until(sim, wall):
    """Scripted time to ``wall``, with the watchdog ticking at its normal interval."""
    remaining = wall - sim.clock.wall()
    if remaining > 0:
        sim.stack.step(remaining)


def record_calls(account, names):
    """Every distinct mutation in the order it first happened: [first t_s, last t_s, count, method, path, status, fault]. Repeats, such as retries during an outage, fold into their first line."""
    mutations, index = [], {}
    for r in account.requests:
        if r['method'] == 'GET':
            continue
        key = (r['method'], names.path(r['path']), r.get('status'), r.get('fault'))
        if key in index:
            line = mutations[index[key]]
            line[1], line[2] = t_of(r['at']), line[2] + 1
        else:
            index[key] = len(mutations)
            mutations.append([t_of(r['at']), t_of(r['at']), 1] + list(key))
    reads = collections.Counter(re.sub(r'\{[^}]+\}', '{id}', names.path(r['path'])) for r in account.requests if r['method'] == 'GET')
    return dict(mutations=mutations, reads=sum(reads.values()), reads_by_route=dict(sorted(reads.items())))


def late_export(sim):
    return se.export_session(sim.root, client=sim.client)


def owned_absent(observed):
    return observed.owned_live() == dict(droplets=[], firewalls=[], tags=[])


class LostAck:
    """A registry transport whose answer to ``method`` is lost once after the registry acted, while ``lost_s`` of scripted time passes."""

    def __init__(self, sim, method, lost_s=5.0):
        self.sim, self.method, self.lost_s = sim, method, lost_s
        self.inner = sim.client.transport
        self.lost = []

    def __call__(self, request):
        response = self.inner(request)
        if request.get('method') == self.method and not self.lost:
            self.lost.append(dict(t_s=t_of(self.sim.clock.wall()), request_id=bool(request['params'].get('request_id'))))
            self.sim.clock.advance(self.lost_s)
            import registry_client
            raise registry_client.TransportError('scripted: the acknowledgement was lost')
        return response


def crash(executor):
    try:
        executor.execute()
    except rf.SimulatedCrash:
        return True
    return False


def crash_on_hit(point, hit):
    seen = [0]

    def failpoint(name):
        if name == point:
            seen[0] += 1
            if seen[0] == hit:
                raise rf.SimulatedCrash(name)
    return failpoint


# ---- scenarios --------------------------------------------------------------------------------------
# Each takes (case, holder, check) and returns the observed sessions. ``holder`` shares one name table per account.

def baseline_confirmed_then_verified_absence(case, holder, check):
    """The control every fault scenario is read against: no fault anywhere."""
    sim, obs = session(case, holder)
    result = sim.batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('the search confirmed its candidate', result.search_status == 'confirmed')
    check('one request per created resource', (len(sim.creates('/v2/droplets')), len(sim.creates('/v2/firewalls')), len(sim.creates('/v2/tags'))) == (2, 1, 3))
    check('closed clean only after every owned resource was absent', final['overall'] == 'clean' and owned_absent(obs))
    check('the export establishes the candidate', obs.row()['establishes'] is True)
    publication = publish_locally(case, sim)
    check('preparing the canonical text is verified_local, not published', (publication['receipts'], publication['status']) == (['verified_local'], 'verified_local'))
    check('only the text summary and its hashes leave the private tree', publication['files'] == sorted(ep.PUBLISHED_FILES) and publication['guard_problems'] == [])
    check('the raw run trees stay private and are not in the published text', publication['raw_files_private'] > 0 and not publication['raw_names_published'])
    obs.extra = dict(publication=publication)
    return [obs]


def publish_locally(case, sim):
    """The canonical repository text prepared in a temporary checkout: what an export would hand to the repository, and nothing more. No real publication happens."""
    import shutil
    import tempfile
    exported = late_export(sim)
    directory = pathlib.Path(tempfile.mkdtemp(prefix='omega-battery-publish-'))
    case.addCleanup(shutil.rmtree, str(directory), True)
    (directory / ep.CANONICAL_ROOT).mkdir(parents=True)
    receipts = ep.publish(sim.root, exported.generation, [ep.RepositoryDocs(directory / ep.CANONICAL_ROOT)], '2026-11-06T00:00:00+00:00', ep.sensitive_values(sim.root, sim.manifest))
    published = directory / ep.CANONICAL_ROOT / ep.SESSIONS_DIR / sim.session_id / exported.generation
    files = sorted(path.name for path in published.iterdir())
    text = ''.join((published / name).read_text() for name in files)
    raw = sorted({path.name for path in (sim.root / 'runs').rglob('*') if path.is_file() and path.suffix in ('.ndjson', '.csv', '.log')})
    return dict(receipts=[item['status'] for item in receipts], status=ep.publication_status(sim.root)['status'], files=files,
                guard_problems=ep.guard_problems({name: (published / name).read_bytes() for name in files}), raw_files_private=len(raw),
                raw_names_published=[name for name in raw if name in files], bytes_published=sum((published / name).stat().st_size for name in files), text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())


def admission_rejected_creates_nothing(case, holder, check):
    """A batch whose legal paths cannot fit the cap. The planner refuses it inside the provisioner, before t0."""
    sim, obs = session(case, holder, cap_s=1800)
    result = sim.run()
    obs.mark('refused')
    check('refused by admission before t0', (result.status, result.code) == (provisioner.REJECTED, 'admission_refused'))
    check('not one provider mutation', sim.account.mutations() == [])
    check('never armed, so no deadline exists', sim.status()['t0_utc'] is None and sim.armed_acks == [])
    check('no guest was contacted', sim.guests.commands == [])
    return [obs]


def unacknowledged_watchdog_creates_nothing(case, holder, check):
    """The watchdog stops ticking before the manifest is acknowledged: no create may follow, whatever the controller wants."""
    sim, obs = session(case, holder)
    sim.stack.watchdog.tick = lambda: None
    result = sim.run()
    obs.mark('refused')
    check('refused for want of an acknowledgement', (result.status, result.code) == (provisioner.REJECTED, 'watchdog_unacknowledged'))
    check('not one provider mutation', sim.account.mutations() == [])
    check('never armed', sim.status()['t0_utc'] is None)
    return [obs]


def lost_acknowledgement_and_lost_create_then_confirmed(case, holder, check):
    """The arm acknowledgement is lost after the registry acted, and the game Droplet's create answer is lost after the provider acted. Neither repeats anything, and the search still confirms."""
    sim, obs = session(case, holder)
    lost = LostAck(sim, 'arm_session')
    sim.client.transport = lost
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=40.0)
    result = sim.batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    armed = [e for e in sim.stack.registry.journal(sim.session_id) if e['kind'] == 'armed']
    check('the lost acknowledgement was retried under the same request and armed once', len(lost.lost) == 1 and lost.lost[0]['request_id'] and len(armed) == 1)
    check('t0 is when the registry acted, not when the retry arrived', t_of_text(final['t0_utc']) == lost.lost[0]['t_s'])
    check('the lost create was adopted, never repeated', len(sim.creates('/v2/droplets')) == 2 and any(e['kind'] == 'resource_recorded' for e in sim.stack.registry.journal(sim.session_id)))
    check('the search confirmed and closed clean', (result.search_status, final['overall']) == ('confirmed', 'clean'))
    return [obs]


def partial_pair_stops_before_any_run(case, holder, check):
    """The bot Droplet is refused outright. The game Droplet exists, so cleanup owns it; no run, no guest, no claim."""
    sim, obs = session(case, holder)
    original = sim.account._route_droplets

    def refuse_bot(method, parts, query, payload):
        if method == 'POST' and payload['name'].endswith('-bot'):
            return sim.account._reply(422, dict(id='unprocessable_entity', message='fixture: no capacity'))
        return original(method, parts, query, payload)
    sim.account._route_droplets = refuse_bot
    result = sim.run()
    obs.mark('stopped')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('stopped on the definitive refusal, with no retry', (result.code, len(sim.creates('/v2/droplets'))) == ('create_rejected', 2))
    check('no run was dispatched and no guest command ran', sim.records() == [] and sim.guests.commands == [])
    check('the owned half is gone and closure is verified', owned_absent(obs) and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    check('measurement and evidence stay unestablished beside a verified cleanup', (final['measurement']['outcome'], final['overall']) == (None, 'resources_verified_evidence_incomplete'))
    return [obs]


def late_create_found_after_the_stop(case, holder, check):
    """The game Droplet's create is lost and lands five minutes later, after provisioning gave up on it. Cleanup waits for it, finds it by tag and deletes it."""
    sim, obs = session(case, holder, policy=pf_fast())
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=300.0)
    result = sim.run()
    obs.mark('stopped_unknown')
    sim.stack.step(120)
    obs.mark('still_unknown')
    open_before = sim.status()['state']
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('stopped with the outcome unknown', result.code == 'create_outcome_unknown')
    check('the session stayed open while the create was unresolved', open_before == registry.DELETING)
    check('discovered by its unique tag and deleted, then closed', any(r['source'] == 'discovered' for r in final['resources']) and owned_absent(obs) and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    check('never created twice', len(sim.creates('/v2/droplets')) == 1)
    return [obs]


def pf_fast():
    import provision_fault_evidence
    return provision_fault_evidence.FAST


def unknown_create_overdue_then_operator_disposition(case, holder, check):
    """A create whose answer is lost and which never lands. An empty listing, elapsed time and D settle nothing; only an explicit operator disposition closes it, and that never reads clean."""
    sim, obs = session(case, holder, policy=pf_fast())
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
    result = sim.run()
    d = to_wall(sim.status()['deadline_d_utc'])
    until(sim, d + 600)
    obs.mark('ten_minutes_past_d')
    overdue = sim.status()
    check('stopped with the outcome unknown and never retried', (result.code, len(sim.creates('/v2/droplets'))) == ('create_outcome_unknown', 1))
    check('past D it is overdue, not settled', overdue['overall'] == 'cleanup_overdue' and len(overdue['cleanup']['unresolved_creates']) == 1)
    check('the session firewall still protects a possible landing', any(name.endswith('-fw') for name in obs.owned_live()['firewalls']))
    incident = next(i for i in overdue['incidents'] if i['kind'] == 'cleanup-overdue')
    report = sim.stack.registry.incident_report(incident['incident_id'])
    check('the overdue incident is durable and names what is unresolved', incident['status'] == 'open' and 'droplet' in json.dumps(report))
    for item in sim.stack.registry.intents(sim.session_id):
        if item['state'] in registry.PENDING_CREATE_STATES:
            sim.stack.registry.dispose_create(sim.session_id, item['intent_id'], 'offline fixture: the operator checked the account by unique tag')
    final = sim.drive_cleanup()
    obs.mark('closed_by_disposition')
    check('closure names the disposition and never reads clean', (final['cleanup']['outcome'], final['overall']) == (registry.VERIFIED_WITH_DISPOSITION, 'resources_verified_with_operator_disposition'))
    check('the overdue incident stays on record', any(i['kind'] == 'cleanup-overdue' for i in final['incidents']))
    return [obs]


class ManagementClock:
    """The management host's own view of the shared scripted time: after a reboot it has its own boot id and monotonic origin, and possibly a wrong RTC, while the laptop's clock carries on."""

    def __init__(self, base, boot='mgmt-boot-b', rtc_error_s=0.0, synced=True):
        self.base, self.boot, self.rtc_error_s, self.synced = base, boot, rtc_error_s, synced
        self.mono_origin = base.mono() - 5.0

    def wall(self):
        return self.base.wall() + self.rtc_error_s

    def mono(self):
        return self.base.mono() - self.mono_origin

    def boot_id(self):
        return self.boot

    def utc_verified(self):
        return self.synced

    def advance(self, seconds):
        self.base.advance(seconds)

    def time_sync(self):
        self.rtc_error_s, self.synced = 0.0, True


def reboot_management_host(sim, **options):
    """The registry and watchdog come back on a rebooted host. Everything they held in memory is gone; the state directory remains."""
    sim.stack.clock = ManagementClock(sim.clock, **options)
    sim.stack.restart_watchdog()
    return sim.stack.clock


def create_landing_with_a_foreign_tag_is_not_adopted(case, holder, check):
    """The game Droplet's create answer is lost, and what lands carries the session tag beside a foreign one. Its ownership is ambiguous: it is neither adopted nor deleted, an incident opens, and the session never reads clean."""
    sim, obs = session(case, holder, policy=pf_fast())
    tags = sim.manifest['session']['ownership_tags']
    original = sim.account._route_droplets

    def land_wrong(method, parts, query, payload):
        if method == 'POST':
            return original(method, parts, query, dict(payload, tags=[tags['session'], 'foreign']))
        return original(method, parts, query, payload)
    sim.account._route_droplets = land_wrong
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1)
    result = sim.run()
    sim.stack.step(600)
    obs.mark('ten_minutes_later')
    final = sim.status()
    check('not adopted', (result.status, result.code) == (provisioner.ABORTED, 'ownership_ambiguous'))
    check('an ownership incident is open', any(i['kind'] == 'ownership-mismatch' and i['status'] == 'open' for i in final['incidents']))
    check('the ambiguous Droplet was not deleted', sim.account.ops('DELETE', '^/v2/droplets/') == [] and len(obs.owned_live()['droplets']) == 1)
    check('no run was dispatched and the session is not clean', sim.records() == [] and final['overall'] != 'clean' and final['state'] != registry.CLOSED)
    return [obs]


def storage_faults_on_both_sides_hold_every_result(case, holder, check):
    """The registry's disk refuses one outcome commit, and the controller's disk is full when it promotes the first confirmation's ticks file. The outcome is retried under its own request and recorded once. The run whose file could not be kept stops the batch as infrastructure; wrap-up later verifies the bytes, and that changes no decision."""
    import sqlite3
    sim, obs = session(case, holder)
    refused = []

    def registry_disk(name):
        if name == 'record_run_outcome:before_commit' and len(refused) == 0 and len(sim.stack.registry.runs(sim.session_id)) == 3:
            refused.append(t_of(sim.clock.wall()))
            raise sqlite3.OperationalError('disk I/O error')
    sim.stack.failpoint = registry_disk
    real = run_executor.publish_new
    full = []

    def local_disk(source, target):
        if pathlib.Path(target).name == 'ticks.csv' and '-confirm-' in str(target) and not full:
            full.append(next(part for part in pathlib.Path(target).parts if part.startswith(sim.session_id + '-t')))
            raise OSError(errno.ENOSPC, 'No space left on device')
        real(source, target)
    with mock.patch.object(run_executor, 'publish_new', side_effect=local_disk):
        result = sim.batch()
    sim.stack.failpoint = None
    final = sim.drive_cleanup()
    obs.mark('closed')
    outcomes = [e for e in sim.stack.registry.journal(sim.session_id) if e['kind'] == 'run_outcome']
    row = obs.row()
    check('the registry refused one commit and the retry recorded it once', len(refused) == 1 and len(outcomes) == len(sim.records()) == len({e['data']['run_id'] for e in outcomes}))
    check('the controller ran out of space promoting a confirmation file', len(full) == 1)
    check('the run whose file could not be kept is an infrastructure failure, never a pass', sim.outcomes()[-1] == (search.CONFIRM, 30, search.INFRASTRUCTURE_FAILURE) and result.search_status == 'stopped_infrastructure_failure')
    check('the bytes verified at wrap-up are complete, and the decision made without them stands', row['export_status'] == 'complete' and full[0] == sim.records()[-1]['run_id'] and row['establishes'] is not True)
    check('cleanup verified', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def ownership_conflict_after_the_batch_is_not_deleted(case, holder, check):
    """After a confirmed batch, someone outside the session points the session firewall at a production Droplet and puts the session tag on it. Cleanup deletes the session's own Droplets, refuses both foreign claims and stays open."""
    sim, obs = session(case, holder)
    result = sim.batch()
    fw = next(f for f in sim.account.firewalls.values() if f['name'] == sim.session_id + '-fw')
    foreign = sim.unrelated['droplets'][1]
    fw.update(tags=['prod'], droplet_ids=[foreign])
    sim.account.droplets[foreign]['tags'].append(sim.manifest['session']['ownership_tags']['session'])
    obs.mark('foreign_claims_made')
    sim.stack.step(600)
    obs.mark('ten_minutes_later')
    final = sim.status()
    check('the batch itself confirmed', result.search_status == 'confirmed')
    check('an ownership incident is open', any(i['kind'] == 'ownership-mismatch' and i['status'] == 'open' for i in final['incidents']))
    check('the session\'s own Droplets were deleted', not [d for d in obs.owned_live()['droplets'] if not d.startswith('prod-api')])
    check('the retargeted firewall and the production Droplet were not deleted', sim.account.ops('DELETE', '/v2/firewalls/') == [] and foreign in sim.account.droplets)
    check('the session stays open and never reads clean', final['state'] != registry.CLOSED and final['overall'] != 'clean')
    check('measurement and evidence keep their own results', (final['measurement']['outcome'], final['evidence']['status']) == ('confirmed', 'complete'))
    return [obs]


def controller_and_laptop_vanish_mid_run(case, holder, check):
    """The controller dies while the third trial runs, and nobody ever comes back. The workload stops at its own bound, and the watchdog alone deletes by C."""
    sim, obs = session(case, holder)
    sim.ready()
    crashed = crash(sim.executor(failpoint=crash_on_hit('after_running_commit', 3)))
    obs.mark('controller_gone')
    c = to_wall(sim.status()['cleanup_c_utc'])
    until(sim, c - 60)
    obs.mark('one_minute_before_c')
    before_c = sim.status()
    final = sim.drive_cleanup(limit_s=7200)
    obs.mark('closed')
    first_delete = min(r['at'] for r in obs.deletes())
    check('the controller really stopped mid-run', crashed and sim.records()[-1]['outcome'] is None)
    check('the orphaned run\'s own grant ended before C', to_wall(sim.records()[-1]['must_stop_by']) <= c)
    check('nothing was deleted or requested before C', before_c['cleanup']['requested_at'] is None and before_c['state'] != registry.DELETING)
    check('the watchdog issued deletion by C with no controller, laptop or SSH key', first_delete <= c and to_wall(final['cleanup']['requested_at']) <= c)
    check('closed only after verified absence', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT and owned_absent(obs))
    check('no evidence was exported and nothing is claimed', obs._generations() == [] and final['overall'] == 'resources_verified_evidence_incomplete')
    return [obs]


def watchdog_restart_and_reboot_keep_the_deadline(case, holder, check):
    """The watchdog process restarts while the second trial's outcome is being written, and the management host reboots (clock synchronized) during the fourth. The batch confirms, cleanup closes clean, and t0/C/D never move."""
    sim, obs = session(case, holder)
    sim.ready()
    events = []

    watchdogs = [sim.stack.watchdog]

    def failpoint(name):
        if name == 'after_outcome_commit':
            events.append(name)
            if len(events) == 2:
                watchdogs.append(sim.stack.restart_watchdog())
                obs.mark('watchdog_restarted')
            if len(events) == 4:
                reboot_management_host(sim)
                watchdogs.append(sim.stack.watchdog)
                obs.mark('management_host_rebooted')
    executor = sim.executor(failpoint=failpoint)
    result = executor.run_batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('two fresh watchdog services replaced the first, one on a new boot', len({id(w) for w in watchdogs}) == 3 and sim.stack.clock.boot_id() == 'mgmt-boot-b')
    check('the batch confirmed across both restarts', result.search_status == 'confirmed')
    check('cleanup closed clean after the reboot', final['overall'] == 'clean' and owned_absent(obs))
    check('the deadlines are the ones armed before the first create', obs.armed == dict(t0=final['t0_utc'], c=final['cleanup_c_utc'], d=final['deadline_d_utc']))
    return [obs]


def reboot_with_untrusted_clock_fails_closed(case, holder, check):
    """The management host reboots mid-batch with its RTC an hour behind and no time sync. The registry cannot date anything, so no further run dispatches. When the clock is synchronized, cleanup proceeds against the original deadlines."""
    sim, obs = session(case, holder)
    sim.ready()
    hits = []
    clock = []

    def failpoint(name):
        if name == 'after_outcome_commit':
            hits.append(name)
            if len(hits) == 2:
                clock.append(reboot_management_host(sim, rtc_error_s=-3600.0, synced=False))
    result = sim.executor(failpoint=failpoint).run_batch()
    obs.mark('batch_returned')
    stuck = sim.status()
    sim.stack.step(120)
    obs.mark('two_minutes_unsynchronized')
    clock[0].time_sync()
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('no run dispatched after the reboot', len(sim.records()) == 2)
    check('the batch stopped rather than guessing the time', result.search_status != 'confirmed')
    check('closed after the clock was trusted, with the original deadlines', final['state'] == registry.CLOSED and obs.armed == dict(t0=final['t0_utc'], c=final['cleanup_c_utc'], d=final['deadline_d_utc']))
    check('nothing is claimed', final['overall'] != 'clean' or final['measurement']['outcome'] != 'confirmed')
    return [obs]


def collect(sim, name):
    """The operator's ``collect`` command: stop and preserve anything left, then collect and hand over to deletion."""
    import run_cli
    client = pf.client_for(sim, name)
    return run_cli.collect_and_stop(client, sim.session_id, lambda token: sim.executor(client=client, token=token), 'operator: collect what is there', takeover=True)


def stale_controller_after_takeover_then_eligible_resume(case, holder, check):
    """Controller A dies between trials holding no run. B takes over and resumes; A's executor then wakes up with its old token and tries to go on. Only B's work happens, once each."""
    sim, obs = session(case, holder)
    sim.ready()
    stale = sim.executor(failpoint=crash_on_hit('after_selection', 2))
    crashed = crash(stale)
    obs.mark('a_crashed_between_trials')
    resumed, control = sim.controller(name='controller-b')
    outcome = resumed.resume('operator: resume remaining runs', control)
    stale.failpoint = None
    late = stale.execute()
    obs.mark('stale_a_woke_up')
    result = resumed.run_batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('A really crashed after one trial', crashed and len(sim.records()) >= 1)
    check('every resume check passed and it named the untouched second trial', outcome['resumed'] and outcome['next_run_id'].endswith('t02-coarse-n050-r1') and all(outcome['checks'][k] is True for k in registry.RESUME_REQUIRED_CHECKS))
    check('stale A was refused before any dispatch', late.status == run_executor.CONTROL_LOST and late.code in run_executor.STALE_CODES)
    check('the search confirmed with each trial started once', result.search_status == 'confirmed' and len(sim.guests.starts()) == 2 * len(sim.records()))
    check('closed clean', final['overall'] == 'clean')
    return [obs]


def interrupted_coarse_run_stops_the_dependent_path(case, holder, check):
    """The controller dies while the second coarse trial runs. Its successor depends on it, so resume is refused, nothing is replayed, and collect keeps the interrupted run as incomplete."""
    sim, obs = session(case, holder)
    sim.ready()
    crash(sim.executor(failpoint=crash_on_hit('after_running_commit', 2)))
    obs.mark('crashed_mid_run')
    executor, control = sim.controller(name='controller-b')
    outcome = executor.resume('operator: resume remaining runs', control)
    collect(sim, 'controller-c')
    obs.mark('collected')
    final = sim.drive_cleanup()
    late_export(sim)
    obs.mark('closed')
    row = sim.records()[1]
    check('resume refused because the next branch is undecidable', (outcome['resumed'], outcome['code']) == (False, 'no_eligible_untouched_work'))
    check('the interrupted trial is incomplete and was not rerun', row['outcome'] == search.INCOMPLETE and len(sim.records()) == 2 and len(sim.guests.starts()) == 4)
    check('both roles sealed it as interrupted', all(sim.guests.hosts[r].runs[row['run_id']].sealed['interrupted'] for r in ('game', 'bot')))
    check('cleanup still requested and verified', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    check('nothing is claimed', obs.row()['establishes'] is not True)
    return [obs]


def interrupted_confirmation_leaves_siblings_eligible(case, holder, check):
    """The controller dies during the first confirmation. Its siblings do not depend on it, so an explicit resume runs them; the set is then partial and never a confirmed capacity."""
    sim, obs = session(case, holder)
    sim.ready()
    crash(sim.executor(failpoint=crash_on_hit('after_running_commit', 5)))
    executor, control = sim.controller(name='controller-b')
    outcome = executor.resume('operator: resume remaining runs', control)
    result = executor.run_batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    late_export(sim)
    obs.mark('closed')
    phases = [(r['trial']['phase'], r['outcome']) for r in sim.records()]
    check('the next sibling was eligible', outcome['resumed'] and outcome['next_run_id'].endswith('t06-confirm-n030-r2'))
    check('three confirmations exist, one incomplete, none replaced', [o for p, o in phases if p == search.CONFIRM] == [search.INCOMPLETE, search.PASS, search.PASS])
    check('an incomplete set is never a confirmed capacity', result.search_status == 'unconfirmed_partial' and obs.row()['establishes'] is not True)
    check('resources verified absent', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def terminal_invalid_load_survives_two_crashes(case, holder, check):
    """The generator starves at 50 players. The controller dies before recording that, a returner dies after reconciling, and a third controller still finds the invalid load on record and cannot resume past it."""
    sim, obs = session(case, holder, script=ef.enriched({50: sf.starved}))
    sim.ready()
    crash(sim.executor(failpoint=crash_on_hit('before_outcome_commit', 2)))
    obs.mark('first_crash')
    second, control = sim.controller(name='returner', failpoint=rf.crash_at('after_reconcile_record'))
    try:
        second.resume('operator: resume', control)
        second_crashed = False
    except rf.SimulatedCrash:
        second_crashed = True
    obs.mark('second_crash')
    third, control = sim.controller(name='third')
    resumed = third.resume('operator: resume', control)
    collect(sim, 'collector')
    final = sim.drive_cleanup()
    late_export(sim)
    obs.mark('closed')
    check('both crashes happened', second_crashed)
    check('the invalid load is the recorded outcome and the session\'s terminal failure', sim.records()[1]['outcome'] == search.INVALID_LOAD and final['terminal_failure'] == search.INVALID_LOAD)
    check('resume refused on the terminal failure and nothing more started', resumed['code'] == 'terminal_failure' and len(sim.records()) == 2)
    check('the cleanup closed with nothing claimed', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT and obs.row()['establishes'] is not True)
    return [obs]


def server_failure_advances_generator_failure_stops(case, holder, check):
    """At 50 the server kicks a bot mid-window: a game-host failure that advances the search, not a generator fault. At 35 the generator starves: invalid offered load, which stops the batch and establishes nothing."""
    import capacity_scorer as cs
    sim, obs = session(case, holder, script=ef.enriched({50: lambda tree: sf.lose_bot(tree, 2, 30, cs.REASON_KICKED), 35: sf.starved}))
    result = sim.batch()
    obs.mark('batch_returned')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('the server-caused disconnect advanced the search as a capacity failure', sim.outcomes()[1] == ('coarse', 50, search.FAIL))
    check('the starved generator stopped it as invalid load', sim.outcomes()[-1] == ('refine', 35, search.INVALID_LOAD) and result.search_status == 'stopped_invalid_load')
    check('no confirmation was attempted and nothing is claimed', not [o for o in sim.outcomes() if o[0] == search.CONFIRM] and obs.row()['establishes'] is not True)
    check('cleanup verified while evidence stays complete for what ran', (final['cleanup']['outcome'], final['evidence']['status']) == (registry.VERIFIED_ABSENT, 'complete'))
    return [obs]


def socket_gap_is_inconclusive(case, holder, check):
    """The game socket's drop counter goes missing at 50 players. A gap cannot be read as zero drops, so the batch stops inconclusive."""
    sim, obs = session(case, holder, script=ef.enriched({50: sf.foggy}))
    result = sim.batch()
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('inconclusive, not a pass or a capacity failure', sim.outcomes()[-1] == ('coarse', 50, search.INCONCLUSIVE) and result.search_status == 'stopped_inconclusive_evidence')
    check('nothing claimed, cleanup verified', obs.row()['establishes'] is not True and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def guest_reboot_clock_gap_is_infrastructure(case, holder, check):
    """The game host's sampler sees a new boot ten seconds into the 25-player window: the clock domain broke, so the run is an infrastructure failure, not a pass."""
    sim, obs = session(case, holder, script=ef.enriched({25: sf.rebooted}))
    result = sim.batch()
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('not a pass', sim.outcomes()[0][2] != search.PASS)
    check('the batch stopped and nothing is claimed', result.search_status not in run_executor.SEARCH_ENDINGS and obs.row()['establishes'] is not True)
    check('cleanup verified', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def failed_confirmation_has_no_replacement(case, holder, check):
    """The second confirmation fails. The candidate is unconfirmed and variable, and no fourth confirmation is tried."""
    def second(tree):
        if tree.trial['run_id'].endswith('r2'):
            sf.slow(tree)
    rules = dict(ef.CONFIRMING)
    rules[(search.CONFIRM, 30)] = second
    sim, obs = session(case, holder, script=ef.enriched(rules))
    result = sim.batch()
    final = sim.drive_cleanup()
    obs.mark('closed')
    confirms = [o for o in sim.outcomes() if o[0] == search.CONFIRM]
    check('the failed second confirmation ended the set: no third and no replacement', [o[2] for o in confirms] == [search.PASS, search.FAIL] and sim.outcomes()[-1] == (search.CONFIRM, 30, search.FAIL))
    check('unconfirmed and variable, with nothing claimed', result.search_status == 'unconfirmed_variable' and obs.row()['establishes'] is not True)
    check('closed clean: complete evidence, verified absence', final['overall'] == 'clean')
    return [obs]


def deadline_exhaustion_is_a_partial_search(case, holder, check):
    """The controller dies after one trial and the operator returns 25 minutes before C. The remaining legal paths no longer fit, so resume is refused on the original headroom; collect hands over to deletion before C."""
    sim, obs = session(case, holder)
    sim.ready()
    crash(sim.executor(failpoint=crash_on_hit('after_selection', 2)))
    c = to_wall(sim.status()['cleanup_c_utc'])
    sim.sleep(c - sim.clock.wall() - 1500)
    obs.mark('operator_returns')
    executor, control = sim.controller(name='controller-b')
    outcome = executor.resume('operator: resume remaining runs', control)
    collect(sim, 'controller-c')
    final = sim.drive_cleanup()
    late_export(sim)
    obs.mark('closed')
    check('resume refused on the original headroom', (outcome['resumed'], outcome['code']) == (False, 'headroom_exhausted'))
    check('nothing more ran', len(sim.records()) == 1)
    check('deletion started before C and C was not moved', to_wall(final['cleanup']['requested_at']) < c and obs.armed['c'] == final['cleanup_c_utc'])
    check('a partial search claims nothing', obs.row()['establishes'] is not True)
    return [obs]


class SiblingSim:
    """A second session on the same management host and the same account, provisioned by the real provisioner with its own controller."""

    def __init__(self, main, session_id):
        import fake_guest
        self.main = main
        self.session_id = session_id
        self.manifest, self.sha = pf.session_of_kind(session_id, pf.CAP_S, 'capacity')
        self.stack, self.clock, self.account, self.unrelated = main.stack, main.clock, main.account, main.unrelated
        self.packet = pf.authorization(self.manifest, self.sha, main.clock.wall())
        gate = remote_authorization.MutationGate(self.packet, self.manifest, self.sha, main.clock.wall)
        self.provider = do_api.DigitalOceanProvisioningProvider(main.account, gate=gate, wall=main.clock.wall)
        self.guests = fake_guest.FakeGuests(types.SimpleNamespace(manifest=self.manifest, account=main.account, clock=main.clock, sleep=main.sleep))
        self.client = pf.client_for(main, 'controller-' + session_id)
        self.armed_acks = []
        self.session_root = main.stack.root / 'sibling-not-exported'
        self.evidence = provisioner.Evidence(main.stack.root / ('provisioning-' + session_id), main.clock.wall)

    def run(self):
        return provisioner.Provisioner(self.client, self.provider, self.guests, self.manifest, self.sha, self.packet, self.evidence, self.main.public_key, self.main.sleep,
                                       self.main.monotonic, self.main.clock.wall, new_nonce=lambda role: 'fixture-nonce-sibling-' + role + '-0123456789ab',
                                       on_armed=self.armed_acks.append).run()

    def status(self):
        return self.stack.registry.status(self.session_id)

    def unrelated_intact(self):
        return self.main.unrelated_intact()

    def session_mutation_targets_only(self):
        return self.main.session_mutation_targets_only()

    def records(self):
        return self.stack.registry.run_records(self.session_id)


def fairness_rate_limits_and_a_deletion_outage(case, holder, check):
    """Two sessions share one watchdog and one account. The sibling's Droplet deletes fail with 503 for hours and its reads are rate limited with 45 s guidance; the main session's batch, export and deletion go ahead unhindered. Past its D the sibling is overdue with a durable incident naming exact ids, and it closes, still marked overdue, once the provider recovers."""
    sim, obs = session(case, holder)
    sibling = SiblingSim(sim, 'do-cap-1v1g-20261030b')
    sibling_obs = Observed(sibling, holder['names'], 'sibling')
    ready = sibling.run()
    ids = '|'.join(str(i) for i in sorted(ready.droplets.values()))
    outage = sim.account.fault('DELETE', '^/v2/droplets/(%s)$' % ids, 'status', status=503)
    limited = sim.account.fault('GET', '^/v2/droplets/(%s)$' % ids, 'status', status=429, times=6, headers={'retry-after': '45'})
    sibling.client.mutate('request_cleanup', session_id=sibling.session_id, fencing_token=ready.fencing_token, reason='batch finished')
    sibling_obs.mark('sibling_cleanup_requested')
    sim.ready()
    result = sim.executor().run_batch()
    obs.mark('main_batch_returned')
    if sim.status()['cleanup']['requested_at'] is None:
        raise AssertionError('main batch did not wrap up: %r' % (result,))
    requested = to_wall(sim.status()['cleanup']['requested_at'])
    main_final = sim.drive_cleanup()
    obs.mark('main_closed')
    main_first_delete = min(r['at'] for r in obs.deletes())
    d = to_wall(sibling.status()['deadline_d_utc'])
    until(sim, d + 60)
    sibling_obs.mark('one_minute_past_d')
    owned_past_d = sibling_obs.owned_live()
    overdue = sibling.status()
    incident = next(i for i in overdue['incidents'] if i['kind'] == 'cleanup-overdue')
    report = json.dumps(sim.stack.registry.incident_report(incident['incident_id']))
    attempts = sim.stack.registry.attempts(sibling.session_id)
    per_sweep = collections.Counter((a['resource_key'], a['sweep_seq']) for a in attempts)
    sim.account.rules.remove(outage)
    sim.stack.run_until(lambda: sibling.status()['state'] == registry.CLOSED, limit_s=1200)
    sibling_obs.mark('sibling_closed')
    final = sibling.status()
    check('the sibling reached ready and asked for cleanup first', ready.status == provisioner.READY)
    check('the main batch confirmed and closed clean while the sibling failed', result.search_status == 'confirmed' and main_final['overall'] == 'clean')
    check('the main session\'s first delete went out within one sweep of its request', main_first_delete - requested <= 15.0)
    check('the rate-limit guidance was received and honoured', limited['times'] == 0 and any(a['retry_after_s'] == 45.0 for a in attempts))
    check('no burst exceeded six attempts per resource', max(per_sweep.values()) <= 6 and max(a['burst_attempt'] for a in attempts) <= 6)
    every = sorted(sim.stack.registry.attempts(sim.session_id) + attempts, key=lambda a: a['started_at'])
    held = [a for a in every if a['http_status'] == 429]
    check('after each 429 the next provider request waited out the guidance', bool(held) and all(min((session_clock.parse(b['started_at']) for b in every if b['started_at'] > a['finished_at']), default=float('inf')) >= session_clock.parse(a['finished_at']) + 45.0 for a in held))
    check('the main session needed no longer than an unfaulted one to close', to_wall(main_final['cleanup']['verified_at']) - requested <= 90.0)
    check('past D the sibling is overdue, not clean, with the Droplets still there', overdue['overall'] == 'cleanup_overdue' and len(owned_past_d['droplets']) == 2)
    check('the overdue incident names the exact Droplet ids and the last error', all(str(i) in report for i in ready.droplets.values()) and '503' in report)
    check('retries continued past D rather than stopping', any(session_clock.parse(a['started_at']) > d for a in attempts if a['op'].startswith('delete_')))
    check('once the provider recovered it closed, still marked overdue, never clean', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT and final['cleanup']['overdue'] and final['cleanup']['overrun_s'] > 0 and final['overall'] != 'clean')
    check('the incident stays on record', any(i['kind'] == 'cleanup-overdue' for i in final['incidents']))
    return [obs, sibling_obs]


def accepted_delete_lingers_beside_corrupt_evidence(case, holder, check):
    """A transferred ticks file arrives corrupt, and after cleanup the provider accepts every delete but keeps listing the Droplets for a dozen reads. Neither the corrupt bytes nor the accepted deletes become verified."""
    sim, obs = session(case, holder)
    sim.guests.corrupt_export.add('telemetry/ticks.csv')
    sim.account.linger_reads = 12
    result = sim.batch()
    sim.stack.step(45)
    obs.mark('deletes_accepted')
    midway = sim.status()
    accepted = [r for r in obs.deletes() if '/v2/droplets/' in r['path'] and r.get('status') == 204]
    check('the deletes were accepted', len(accepted) >= 2)
    check('accepted deletes are not absence: still deleting, not closed', midway['state'] == registry.DELETING and len(obs.marks[0]['owned']['droplets']) == 2)
    check('no Droplet the account still listed was recorded absent', not [r for r in midway['resources'] if r['kind'] == 'droplet' and r['status'] == 'absent'])
    row = obs.row()
    check('the corrupt file was never promoted, and nothing is claimed', row['export_status'] == 'corrupt' and row['establishes'] is not True)
    check('a run whose bytes cannot be verified stops the batch as infrastructure, never a pass', sim.outcomes()[0][2] == search.INFRASTRUCTURE_FAILURE and result.search_status == 'stopped_infrastructure_failure')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('closed only after the provider stopped listing them', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT and owned_absent(obs))
    check('resources verified, evidence still incomplete', final['overall'] == 'resources_verified_evidence_incomplete')
    return [obs]


def failed_transfer_crash_and_late_return_end_the_episode(case, holder, check):
    """The first game transfer fails and keeps failing, and the controller dies on the next file. The watchdog restarts, and a controller whose wall clock is two minutes behind returns after the grace. No transfer starts after the episode's end, and that end is the first failure plus the grace."""
    sim, obs = session(case, holder)
    sim.ready()
    first = []

    def hook(role, run_id, relative, data, attempt):
        if role == 'game' and not first:
            first.append((sim.clock.wall(), relative))
            return 1, b'cut'
        if first and (role, relative) == ('game', first[0][1]):
            return 1, b'cut'
        if first:
            raise rf.SimulatedCrash('between transfers')
        return 0, data
    sim.guests.get_hook = hook
    crashed = crash(sim.executor())
    obs.mark('crashed_after_first_failure')
    sim.stack.restart_watchdog()
    grace = sim.manifest['limits']['evidence_recovery_grace_s']
    sim.sleep(grace + 60)
    before = sum(1 for c in sim.guests.commands if c.get('step') == 'get')
    sim.guests.get_hook = lambda role, run_id, relative, data, attempt: (1, b'cut') if (role, relative) == ('game', first[0][1]) else (0, data)
    controller, _ = sim.controller(name='controller-b')
    controller.wall = lambda: sim.clock.wall() - 120
    controller.collecting = True
    controller.prepare()
    controller.reconcile('operator_collect')
    controller.wrap_up(run_executor.BatchResult(run_executor.STOPPED, code='operator_collect', detail='returned after the grace', runs=controller.outcomes))
    after = sum(1 for c in sim.guests.commands if c.get('step') == 'get')
    status = sim.status()
    obs.mark('collected')
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('the controller died between transfers', crashed and first)
    check('no transfer started after the episode had ended', after == before)
    check('the episode ends at the first failure plus the grace, not later', to_wall(status['recovery_deadline_utc']) <= first[0][0] + grace)
    check('cleanup was requested and verified anyway', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    check('the evidence is not complete and nothing is claimed', final['evidence']['status'] != 'complete' and obs.row()['establishes'] is not True)
    return [obs]


def source_change_mid_run_scores_nothing(case, holder, check):
    """While the second trial runs, the controller's checkout stops matching the frozen revision. The unfrozen code may finish collecting but decides nothing: the run is inconclusive and the batch stops, with cleanup."""
    sim, obs = session(case, holder)
    sim.ready()

    def source_problems():
        return ['the working tree is not the frozen controller revision'] if len(sim.records()) >= 2 else []
    result = sim.executor(source_problems=source_problems).run_batch()
    final = sim.drive_cleanup()
    obs.mark('closed')
    check('the second trial was not scored by unfrozen code', [o[2] for o in sim.outcomes()] == [search.PASS, search.INCONCLUSIVE] and sim.score_of(sim.records()[1]['run_id']) is None)
    check('the batch stopped there and nothing is claimed', result.search_status == 'stopped_inconclusive_evidence' and obs.row()['establishes'] is not True)
    check('cleanup verified', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def changed_checkout_returns_and_c_still_arrives(case, holder, check):
    """The controller dies between trials, and the operator comes back from a checkout that is not the frozen revision. Resume is refused before anything is dispatched, the wrong code wraps nothing up, nobody else returns, and the watchdog deletes by C."""
    import run_cli
    sim, obs = session(case, holder)
    sim.ready()
    crash(sim.executor(failpoint=crash_on_hit('after_selection', 3)))
    obs.mark('controller_crashed')
    client = pf.client_for(sim, 'controller-changed')
    changed = lambda: ['the working tree is not the frozen controller revision']   # noqa: E731
    outcome, batch = run_cli.resume_and_run(client, sim.session_id, lambda token: sim.executor(client=client, token=token, source_problems=changed), 'operator: resume', takeover=True)
    obs.mark('changed_checkout_refused')
    c = to_wall(sim.status()['cleanup_c_utc'])
    final = sim.drive_cleanup(limit_s=16000)
    obs.mark('closed')
    first_delete = min(r['at'] for r in obs.deletes())
    check('resume refused on the source, with no batch run', (outcome['resumed'], outcome.get('code'), batch) == (False, run_executor.SOURCE_CHANGED, None))
    check('nothing was dispatched after the crash', len(sim.records()) == 2 and len(sim.guests.starts()) == 4)
    check('nobody asked for cleanup, and the watchdog deleted by C', final['cleanup']['reason'] == 'deadline_C' and first_delete <= c and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    return [obs]


def takeover_with_an_outstanding_grant_is_pending(case, holder, check):
    """The controller dies holding a launch grant for its second trial. A takeover is pending until both guests acknowledge the new fence; the delayed start is then refused and collect keeps the run incomplete."""
    import run_fault_evidence as rfe
    sim, obs = session(case, holder)
    sim.ready()
    stale = sim.executor(failpoint=crash_on_hit('after_game_authorized', 2))
    crash(stale)
    grant = next(g for g in sim.stack.registry.guest_grants(sim.session_id) if g['state'] == 'outstanding')
    new, control = sim.controller(name='controller-b')
    pending = sim.status()
    obs.mark('takeover_pending')
    new.prepare()
    paused = sim.status()
    obs.mark('fenced')
    try:
        rfe._delayed_start(stale, grant)
        refused = None
    except run_executor.ControlLost as lost:
        refused = lost.code
    collect(sim, 'controller-c')
    final = sim.drive_cleanup()
    late_export(sim)
    obs.mark('closed')
    check('the takeover read as pending until the fence landed', control['revocation']['pending'] and pending['state'] == registry.REVOCATION_PENDING)
    check('both guests acknowledged and the session paused', paused['state'] == registry.PAUSED)
    check('the stale controller\'s delayed start was refused by the fence', refused == 'stale_fence')
    check('the second trial is incomplete and started nowhere', sim.records()[-1]['outcome'] == search.INCOMPLETE and sim.records()[-1]['run_id'] not in sim.guests.hosts['bot'].runs)
    check('cleanup verified, nothing claimed', final['cleanup']['outcome'] == registry.VERIFIED_ABSENT and obs.row()['establishes'] is not True)
    return [obs]


# ---- the battery ------------------------------------------------------------------------------------

ALWAYS = ('composed_real_transitions', 'no_unrelated_deletion', 'no_duplicate_run', 'no_hidden_retry', 'no_deadline_extension', 'clean_only_after_owned_absence', 'independent_results', 'no_claim_on_unknown')

SCENARIOS = (
    (baseline_confirmed_then_verified_absence, ('publication_truth',)),
    (admission_rejected_creates_nothing, ('rejected_admission_creates_nothing',)),
    (unacknowledged_watchdog_creates_nothing, ('rejected_admission_creates_nothing',)),
    (lost_acknowledgement_and_lost_create_then_confirmed, ('ambiguous_create',)),
    (partial_pair_stops_before_any_run, ('partial_create',)),
    (late_create_found_after_the_stop, ('late_create', 'ambiguous_create')),
    (unknown_create_overdue_then_operator_disposition, ('ambiguous_create', 'orphan_operator_disposition', 'persistent_overdue_cleanup')),
    (create_landing_with_a_foreign_tag_is_not_adopted, ('wrong_ownership', 'ambiguous_create')),
    (ownership_conflict_after_the_batch_is_not_deleted, ('wrong_ownership',)),
    (controller_and_laptop_vanish_mid_run, ('controller_laptop_disappearance', 'independent_cleanup_without_runner', 'interrupted_resume')),
    (watchdog_restart_and_reboot_keep_the_deadline, ('watchdog_restart', 'watchdog_reboot')),
    (reboot_with_untrusted_clock_fails_closed, ('watchdog_reboot', 'clock_gap')),
    (stale_controller_after_takeover_then_eligible_resume, ('stale_fencing', 'eligible_resume')),
    (takeover_with_an_outstanding_grant_is_pending, ('stale_fencing', 'revocation_pending_handoff', 'interrupted_resume')),
    (interrupted_coarse_run_stops_the_dependent_path, ('interrupted_resume', 'ineligible_resume', 'dependent_path_uncertainty', 'incomplete_evidence')),
    (interrupted_confirmation_leaves_siblings_eligible, ('interrupted_resume', 'eligible_resume', 'incomplete_evidence')),
    (terminal_invalid_load_survives_two_crashes, ('invalid_generator_load', 'terminal_fact_through_recovery', 'ineligible_resume')),
    (server_failure_advances_generator_failure_stops, ('genuine_server_failure', 'invalid_generator_load')),
    (socket_gap_is_inconclusive, ('socket_gap',)),
    (guest_reboot_clock_gap_is_infrastructure, ('clock_gap',)),
    (failed_confirmation_has_no_replacement, ('failed_confirmation', 'genuine_server_failure')),
    (deadline_exhaustion_is_a_partial_search, ('deadline_exhaustion', 'ineligible_resume')),
    (fairness_rate_limits_and_a_deletion_outage, ('retry_fairness', 'rate_limits', 'deletion_outage', 'persistent_overdue_cleanup')),
    (accepted_delete_lingers_beside_corrupt_evidence, ('accepted_delete_not_absence', 'corrupt_evidence')),
    (storage_faults_on_both_sides_hold_every_result, ('incomplete_evidence', 'composed_real_transitions')),
    (failed_transfer_crash_and_late_return_end_the_episode, ('incomplete_evidence', 'watchdog_restart', 'clock_gap', 'controller_laptop_disappearance')),
    (source_change_mid_run_scores_nothing, ('source_frozen',)),
    (changed_checkout_returns_and_c_still_arrives, ('source_frozen', 'ineligible_resume', 'independent_cleanup_without_runner')),
)


def run_scenario(play, requirements):
    """One scenario in its own temporary directories, with its own account and clock. Returns its row; a scenario that raises is recorded as having raised."""
    case = _Case()
    holder, checks = {}, {}
    try:
        with named_requests():
            observed = play(case, holder, checker(checks))
            sessions = [dict(label=obs.label, session_id=obs.session_id, **obs.row()) for obs in observed]
            calls = record_calls(observed[0].sim.account, holder['names'])
        return dict(about=' '.join(play.__doc__.split()), requirements=sorted(set(requirements) | set(ALWAYS)), checks=checks, sessions=sessions, provider=calls)
    finally:
        case.doCleanups()


def build():
    scenarios = collections.OrderedDict()
    for play, requirements in SCENARIOS:
        scenarios[play.__name__] = run_scenario(play, requirements)
    covered = {key: sorted(name for name, row in scenarios.items() if key in row['requirements']) for key in REQUIREMENTS}
    return dict(schema=SCHEMA, kind='synthetic', note=NOTE, requirements=[dict(key=key, text=text, scenarios=covered[key]) for key, text in REQUIREMENTS.items()], scenarios=scenarios)


def canonical(document):
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=True) + '\n'


def generate(out, real_process=None):
    """Write the synthetic battery and the inventory. ``real_process`` is the normalized summary ``test_fault_battery_process`` records from real processes; it is carried into the inventory as it is, never regenerated here."""
    import shutil
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = canonical(build()).encode('utf-8')
    (out / 'synthetic-battery.json').write_bytes(data)
    names = ['synthetic-battery.json']
    if real_process is not None:
        if pathlib.Path(real_process).resolve() != (out / 'real-process.json').resolve():
            shutil.copyfile(str(real_process), str(out / 'real-process.json'))
        names.append('real-process.json')
    (out / 'SHA256SUMS').write_text(''.join('%s  %s\n' % (hashlib.sha256((out / name).read_bytes()).hexdigest(), name) for name in sorted(names)))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True)
    parser.add_argument('--real-process', help='the normalized real-process summary to carry into the inventory')
    args = parser.parse_args(argv)
    generate(args.out, args.real_process)
    print((pathlib.Path(args.out) / 'SHA256SUMS').read_text(), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
