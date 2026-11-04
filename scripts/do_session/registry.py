"""Durable session registry: the control-plane half of handoff slice 2 (issue #61 §2).

One SQLite file in one state directory holds the manifest, ownership, creation intents, immutable
t0/D/C, fencing state, run/cleanup transitions, an append-only hash-chained journal and incidents.
A state directory can be stopped, copied to another Linux host and started there unchanged.

Every mutation is one ``BEGIN IMMEDIATE`` transaction with ``synchronous=EXTRA``. Its response is
stored in the same transaction under the caller's request id, so an applied write whose
acknowledgement was lost replays the same answer. Replays of operations that authorize a side
effect (workload dispatch, provider create) re-run their gate first: a stored answer never lets a
stale controller launch anything after takeover, cleanup or expiry.

Time always comes from the registry's own effective clock (``session_clock``), never the caller.
"""
import contextlib
import hashlib
import json
import os
import pathlib
import sqlite3

import manifest as manifest_mod
import search
import session_clock

SCHEMA_VERSION = 1
DB_NAME = 'registry.sqlite3'
INCIDENT_DIR = 'incidents'
RECEIPT_DIR = 'receipts'

REGISTERED, PROVISIONING, READY, RUNNING, PAUSED = 'registered', 'provisioning', 'ready', 'running', 'paused'
COLLECTING, EVIDENCE_RECOVERY, DELETING, CLOSED = 'collecting', 'evidence-recovery', 'deleting', 'closed'

DEFAULT_LEASE_TTL_S = 90.0
DEFAULT_WATCHDOG_STALE_S = 30.0
DEFAULT_LAUNCH_WINDOW_S = 30.0
CLEANUP_LEAD_S = 5.0        # the watchdog starts this early so its first delete is issued by C
PROTECTED_TAGS = ('omega-management',)

EVIDENCE_STATUSES = ('unknown', 'collecting', 'complete', 'partial', 'missing', 'corrupt')
VERIFIED_ABSENT = 'verified_absent'
VERIFIED_WITH_DISPOSITION = 'verified_absent_with_operator_disposition'
NEVER_ARMED = 'no_resources_never_armed'

TERMINAL_RESOURCE_STATES = ('absent', 'disowned')
LISTING_KINDS = ('inventory_droplet', 'inventory_firewall')
INCIDENT_ATTEMPT_TAIL = 30

GENESIS_HASH = '0' * 64

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE clock_state(id INTEGER PRIMARY KEY CHECK(id = 1), boot_id TEXT NOT NULL, mono REAL NOT NULL,
    effective REAL NOT NULL, wall REAL NOT NULL, anomaly_incident INTEGER);
CREATE TABLE watchdog_status(id INTEGER PRIMARY KEY CHECK(id = 1), identity TEXT, pid INTEGER, boot_id TEXT,
    started_at TEXT, last_tick_at TEXT, last_sweep_at TEXT, sweep_seq INTEGER NOT NULL DEFAULT 0,
    rate_limit_hold_until TEXT, rate_limit_detail TEXT);
CREATE TABLE sessions(
    session_id TEXT PRIMARY KEY, manifest_sha256 TEXT NOT NULL, manifest_json TEXT NOT NULL,
    registered_at TEXT NOT NULL, state TEXT NOT NULL,
    cap_s REAL NOT NULL, reserve_s REAL NOT NULL, grace_s REAL NOT NULL,
    watchdog_identity TEXT NOT NULL, watchdog_ack_at TEXT, watchdog_armed_ack_at TEXT,
    t0_utc TEXT, deadline_d_utc TEXT, cleanup_c_utc TEXT,
    fencing_token INTEGER NOT NULL DEFAULT 0, controller_id TEXT, lease_expires_at TEXT,
    ready_at TEXT, ready_evidence_ref TEXT, terminal_failure TEXT,
    recovery_first_failure_at TEXT, recovery_deadline_utc TEXT,
    measurement_outcome TEXT, measurement_ref TEXT, measurement_updated_at TEXT,
    evidence_status TEXT NOT NULL DEFAULT 'unknown', evidence_ref TEXT, evidence_updated_at TEXT,
    cleanup_outcome TEXT NOT NULL DEFAULT 'not_started', cleanup_requested_at TEXT, cleanup_reason TEXT,
    cleanup_actor TEXT, cleanup_verified_at TEXT, overrun_s REAL, closure_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE intents(
    session_id TEXT NOT NULL, intent_id TEXT NOT NULL, kind TEXT NOT NULL, role TEXT NOT NULL,
    expected_name TEXT NOT NULL, expected_tags_json TEXT NOT NULL, state TEXT NOT NULL,
    requested_at TEXT, request_count INTEGER NOT NULL DEFAULT 0, resource_key TEXT, resolved_at TEXT, note TEXT,
    PRIMARY KEY(session_id, intent_id));
CREATE TABLE runs(
    session_id TEXT NOT NULL, run_id TEXT NOT NULL, state TEXT NOT NULL, dispatched_at TEXT NOT NULL,
    fencing_token INTEGER NOT NULL, controller_id TEXT, launch_by TEXT NOT NULL, trial_json TEXT,
    finished_at TEXT, outcome TEXT, evidence_ref TEXT, interrupted_at TEXT, interrupted_reason TEXT,
    PRIMARY KEY(session_id, run_id));
CREATE TABLE resources(
    session_id TEXT NOT NULL, resource_key TEXT NOT NULL, kind TEXT NOT NULL, provider_id TEXT NOT NULL,
    name TEXT, intent_id TEXT, source TEXT NOT NULL, status TEXT NOT NULL, first_seen_at TEXT NOT NULL,
    ownership_detail TEXT, verified_absent_at TEXT, delete_accepted_at TEXT,
    delete_accept_count INTEGER NOT NULL DEFAULT 0, last_error TEXT, last_attempt_at TEXT,
    attempt_total INTEGER NOT NULL DEFAULT 0,
    burst_state TEXT NOT NULL DEFAULT 'idle', burst_sweep INTEGER, burst_started_at TEXT,
    burst_attempts INTEGER NOT NULL DEFAULT 0, burst_next_at TEXT, burst_next_op TEXT, in_flight_attempt INTEGER,
    listing_started_at TEXT, listing_finished_at TEXT, consecutive_empty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(session_id, resource_key));
CREATE TABLE attempts(
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, resource_key TEXT NOT NULL,
    sweep_seq INTEGER, burst_attempt INTEGER NOT NULL, op TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, result TEXT, http_status INTEGER, error_class TEXT, message TEXT, retry_after_s REAL);
CREATE TABLE events(
    seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, session_id TEXT, kind TEXT NOT NULL,
    data_json TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE incidents(
    incident_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL,
    opened_at TEXT NOT NULL, resolved_at TEXT, overrun_s REAL, version INTEGER NOT NULL DEFAULT 1,
    last_error TEXT, detail_json TEXT NOT NULL);
CREATE TABLE requests(
    request_id TEXT PRIMARY KEY, method TEXT NOT NULL, params_sha256 TEXT NOT NULL, session_id TEXT,
    response_json TEXT NOT NULL, at TEXT NOT NULL);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER incidents_no_delete BEFORE DELETE ON incidents BEGIN SELECT RAISE(ABORT, 'incidents are retained'); END;
CREATE TRIGGER resources_no_delete BEFORE DELETE ON resources BEGIN SELECT RAISE(ABORT, 'owned ids are retained'); END;
CREATE TRIGGER sessions_no_delete BEFORE DELETE ON sessions BEGIN SELECT RAISE(ABORT, 'sessions are retained'); END;
CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT, 'attempts are retained'); END;
CREATE TRIGGER attempts_finish_once BEFORE UPDATE ON attempts WHEN OLD.finished_at IS NOT NULL
    BEGIN SELECT RAISE(ABORT, 'a finished attempt is immutable'); END;
CREATE TRIGGER deadlines_immutable BEFORE UPDATE OF t0_utc, deadline_d_utc, cleanup_c_utc, cap_s, reserve_s ON sessions
    WHEN OLD.t0_utc IS NOT NULL AND (NEW.t0_utc IS NOT OLD.t0_utc OR NEW.deadline_d_utc IS NOT OLD.deadline_d_utc
        OR NEW.cleanup_c_utc IS NOT OLD.cleanup_c_utc OR NEW.cap_s IS NOT OLD.cap_s OR NEW.reserve_s IS NOT OLD.reserve_s)
    BEGIN SELECT RAISE(ABORT, 'session deadlines are immutable'); END;
CREATE TRIGGER manifest_immutable BEFORE UPDATE OF manifest_json, manifest_sha256 ON sessions
    WHEN NEW.manifest_json IS NOT OLD.manifest_json OR NEW.manifest_sha256 IS NOT OLD.manifest_sha256
    BEGIN SELECT RAISE(ABORT, 'the registered manifest is immutable'); END;
"""


class Rejection(Exception):
    """A refused request. It is an answer, not a storage failure: retrying will not change it."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_response(self):
        return dict(ok=False, code=self.code, message=self.message, details=self.details)


class RegistryUnavailable(Exception):
    """The state directory is missing or unusable. No acknowledgement can be given."""


def canonical(value):
    return manifest_mod.canonical_json(value)


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def session_intents(manifest):
    """Creation intents derived only from the frozen manifest, so no caller can widen ownership."""
    session_id = manifest['session']['id']
    tags = manifest['session']['ownership_tags']
    intents = [dict(intent_id=session_id + ':tag:' + role, kind='tag', role=role,
                    expected_name=tags[role], expected_tags=[]) for role in ('session', 'game', 'bot')]
    intents.append(dict(intent_id=session_id + ':firewall', kind='firewall', role='session',
                        expected_name=session_id + '-fw', expected_tags=[tags['game'], tags['bot']]))
    for role in ('game', 'bot'):
        intents.append(dict(intent_id=session_id + ':droplet:' + role, kind='droplet', role=role,
                            expected_name=session_id + '-' + role, expected_tags=[tags['session'], tags[role]]))
    return intents


class Registry:
    def __init__(self, state_dir, clock=None, failpoint=None, lease_ttl_s=DEFAULT_LEASE_TTL_S,
                 watchdog_stale_s=DEFAULT_WATCHDOG_STALE_S, launch_window_s=DEFAULT_LAUNCH_WINDOW_S,
                 clock_tolerance_s=session_clock.DEFAULT_TOLERANCE_S, protected_tags=PROTECTED_TAGS):
        self.state_dir = pathlib.Path(state_dir)
        self.clock = clock or session_clock.SystemClock()
        self.failpoint = failpoint or (lambda name: None)
        self.lease_ttl_s = lease_ttl_s
        self.watchdog_stale_s = watchdog_stale_s
        self.launch_window_s = launch_window_s
        self.clock_tolerance_s = clock_tolerance_s
        self.protected_tags = tuple(protected_tags)
        path = self.state_dir / DB_NAME
        if not path.exists():
            # A vanished state directory must fail loudly: recreating it would forget armed sessions.
            raise RegistryUnavailable('registry state is missing: ' + str(path))
        self.db = self._connect(path)
        try:
            row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.Error as error:
            raise RegistryUnavailable('registry state is unusable: ' + str(error))
        if row is None or int(row['value']) != SCHEMA_VERSION:
            raise RegistryUnavailable('registry initialization is incomplete or its schema is unsupported')
        self.registry_id = self._meta('registry_id')
        self.watchdog_identity = self._meta('watchdog_identity')

    @staticmethod
    def _connect(path):
        db = sqlite3.connect(str(path), timeout=10.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=DELETE')
        db.execute('PRAGMA synchronous=EXTRA')
        return db

    @classmethod
    def init(cls, state_dir, registry_id, watchdog_identity):
        """Create-only. Refuses an existing registry, so setup can never reset armed sessions."""
        state_dir = pathlib.Path(state_dir)
        path = state_dir / DB_NAME
        if path.exists():
            raise RegistryUnavailable('registry already exists: ' + str(path))
        for directory in (state_dir, state_dir / INCIDENT_DIR, state_dir / RECEIPT_DIR):
            directory.mkdir(parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = cls._connect(path)
        db.executescript('BEGIN IMMEDIATE;' + SCHEMA + 'COMMIT;')
        db.execute('INSERT INTO meta VALUES (?, ?)', ('registry_id', registry_id))
        db.execute('INSERT INTO meta VALUES (?, ?)', ('watchdog_identity', watchdog_identity))
        db.execute('INSERT INTO watchdog_status(id) VALUES (1)')
        db.execute('INSERT INTO meta VALUES (?, ?)', ('schema_version', str(SCHEMA_VERSION)))   # last: marks init complete
        db.close()

    def close(self):
        self.db.close()

    def _meta(self, key):
        return self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()['value']

    # ---- clock ------------------------------------------------------------------------------

    def _read_anchor(self):
        row = self.db.execute('SELECT * FROM clock_state WHERE id=1').fetchone()
        if row is None:
            return None, None
        return session_clock.Anchor(row['boot_id'], row['mono'], row['effective']), row

    def _advance_clock(self):
        """Inside a write transaction: ratchet the effective clock and journal any anomaly."""
        wall, mono, boot = self.clock.wall(), self.clock.mono(), self.clock.boot_id()
        anchor, row = self._read_anchor()
        effective, new_anchor, anomaly = session_clock.advance(anchor, wall, mono, boot, self.clock_tolerance_s)
        if row is None:
            self.db.execute('INSERT INTO clock_state(id, boot_id, mono, effective, wall) VALUES (1, ?, ?, ?, ?)',
                            (boot, mono, effective, wall))
            return effective
        open_incident = row['anomaly_incident']
        if anomaly and open_incident is None:
            now_text = session_clock.iso(effective)
            open_incident = self.open_incident(None, 'clock-anomaly', now_text, anomaly, last_error=anomaly['kind'])
            self.event(now_text, None, 'clock_anomaly', anomaly)
        elif anomaly is None and open_incident is not None:
            self.resolve_incident(open_incident, session_clock.iso(effective))
            open_incident = None
        self.db.execute('UPDATE clock_state SET boot_id=?, mono=?, effective=?, wall=?, anomaly_incident=? WHERE id=1',
                        (boot, mono, effective, wall, open_incident))
        return effective

    def peek_now(self):
        """The effective time for read-only callers; nothing is persisted."""
        anchor, _ = self._read_anchor()
        effective, _, _ = session_clock.advance(anchor, self.clock.wall(), self.clock.mono(),
                                                self.clock.boot_id(), self.clock_tolerance_s)
        return effective

    def clock_healthy(self, effective=None):
        effective = self.peek_now() if effective is None else effective
        row = self.db.execute('SELECT anomaly_incident FROM clock_state WHERE id=1').fetchone()
        if row is not None and row['anomaly_incident'] is not None:
            return False
        return abs(self.clock.wall() - effective) <= self.clock_tolerance_s

    # ---- transactions, journal, incidents ----------------------------------------------------

    @contextlib.contextmanager
    def txn(self, label):
        """One durable write. Yields the effective epoch; storage errors roll back and propagate."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield self._advance_clock()
            self.failpoint(label + ':before_commit')
            self.db.execute('COMMIT')
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self.db.execute('ROLLBACK')
            raise
        self.failpoint(label + ':after_commit')

    def event(self, at, session_id, kind, data=None):
        data_json = canonical(data or {})
        last = self.db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        prev = last['hash'] if last else GENESIS_HASH
        digest = sha256_text(prev + canonical([at, session_id, kind]) + data_json)
        cursor = self.db.execute('INSERT INTO events(at, session_id, kind, data_json, prev_hash, hash) '
                                 'VALUES (?, ?, ?, ?, ?, ?)', (at, session_id, kind, data_json, prev, digest))
        return cursor.lastrowid

    def open_incident(self, session_id, kind, now_text, detail, last_error=None):
        cursor = self.db.execute('INSERT INTO incidents(session_id, kind, status, opened_at, last_error, detail_json) '
                                 "VALUES (?, ?, 'open', ?, ?, ?)", (session_id, kind, now_text, last_error, canonical(detail)))
        self.event(now_text, session_id, 'incident_opened', dict(incident_id=cursor.lastrowid, kind=kind))
        return cursor.lastrowid

    def resolve_incident(self, incident_id, now_text, overrun_s=None):
        self.db.execute("UPDATE incidents SET status='resolved', resolved_at=?, overrun_s=?, version=version+1 "
                        "WHERE incident_id=? AND status='open'", (now_text, overrun_s, incident_id))
        row = self.db.execute('SELECT session_id, kind FROM incidents WHERE incident_id=?', (incident_id,)).fetchone()
        self.event(now_text, row['session_id'], 'incident_resolved', dict(incident_id=incident_id, kind=row['kind']))

    def open_incident_of(self, session_id, kind):
        return self.db.execute("SELECT * FROM incidents WHERE session_id IS ? AND kind=? AND status='open' "
                               'ORDER BY incident_id DESC LIMIT 1', (session_id, kind)).fetchone()

    def verify_journal(self):
        """Recompute the chain; a removed or edited event breaks it from that point on."""
        prev = GENESIS_HASH
        expected_seq = 1
        for row in self.db.execute('SELECT * FROM events ORDER BY seq'):
            digest = sha256_text(prev + canonical([row['at'], row['session_id'], row['kind']]) + row['data_json'])
            if row['prev_hash'] != prev or row['hash'] != digest or row['seq'] != expected_seq:
                return dict(valid=False, broken_at_seq=row['seq'])
            prev = row['hash']
            expected_seq += 1
        return dict(valid=True, events=expected_seq - 1, head=prev)

    def journal(self, session_id=None):
        query = 'SELECT seq, at, session_id, kind, data_json, hash FROM events'
        args = ()
        if session_id is not None:
            query += ' WHERE session_id=?'
            args = (session_id,)
        return [dict(seq=r['seq'], at=r['at'], session_id=r['session_id'], kind=r['kind'],
                     data=json.loads(r['data_json']), hash=r['hash'])
                for r in self.db.execute(query + ' ORDER BY seq', args)]

    # ---- mutation envelope -------------------------------------------------------------------

    def session_row(self, session_id):
        row = self.db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if row is None:
            raise Rejection('unknown_session', 'session is not registered: ' + str(session_id))
        return row

    def _mutate(self, method, params, request_id, session_id, body, gate=None):
        hits = manifest_mod.scan_for_secrets(params)
        if hits:
            # The offending value is deliberately neither stored nor echoed.
            raise Rejection('secret_value_rejected', 'request contains a credential value at ' + ', '.join(hits))
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise Rejection('bad_request', 'request_id must be a nonempty string')
        params_sha = sha256_text(canonical(dict(method=method, params=params)))
        try:
            with self.txn(method) as effective:
                now_text = session_clock.iso(effective)
                session = self.session_row(session_id) if session_id is not None else None
                if gate is not None:
                    gate(effective, session)
                if request_id is not None:
                    prior = self.db.execute('SELECT * FROM requests WHERE request_id=?', (request_id,)).fetchone()
                    if prior is not None:
                        if prior['params_sha256'] != params_sha:
                            raise Rejection('request_id_conflict', 'request id was used for a different request')
                        return dict(json.loads(prior['response_json']), replayed=True)
                result = body(effective, now_text, session)
                if request_id is not None:
                    self.db.execute('INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?)',
                                    (request_id, method, params_sha, session_id, canonical(result), now_text))
                return result
        except Rejection as rejection:
            self._journal_rejection(method, session_id, rejection)
            raise

    def _journal_rejection(self, method, session_id, rejection):
        with contextlib.suppress(sqlite3.Error, Rejection):
            with self.txn('journal_rejection') as effective:
                known = session_id is not None and self.db.execute(
                    'SELECT 1 FROM sessions WHERE session_id=?', (session_id,)).fetchone() is not None
                self.event(session_clock.iso(effective), session_id if known else None, 'rejected',
                           dict(method=method, code=rejection.code))

    # ---- gates -------------------------------------------------------------------------------

    @staticmethod
    def _require_token(session, token):
        if not isinstance(token, int) or isinstance(token, bool) or token <= 0 or token != session['fencing_token']:
            raise Rejection('stale_fencing_token', 'fencing token is not the current controller',
                            current_token=session['fencing_token'], presented=token)

    def _require_lease(self, session, effective):
        expires = session['lease_expires_at']
        if expires is None or effective >= session_clock.parse(expires):
            raise Rejection('lease_expired', 'the controller lease lapsed; re-acquire control explicitly')

    @staticmethod
    def _require_no_cleanup(session):
        if session['state'] in (DELETING, CLOSED) or session['cleanup_requested_at'] is not None:
            raise Rejection('cleanup_in_progress', 'cleanup takes precedence; no further work is admitted',
                            state=session['state'])

    @staticmethod
    def _require_before_c(session, effective):
        if session['cleanup_c_utc'] is not None and effective >= session_clock.parse(session['cleanup_c_utc']):
            raise Rejection('deadline_reached', 'the session reached C; no further work is admitted',
                            cleanup_c_utc=session['cleanup_c_utc'])

    def _require_watchdog_fresh(self, effective):
        row = self.db.execute('SELECT last_tick_at, identity FROM watchdog_status WHERE id=1').fetchone()
        if row['last_tick_at'] is None or row['identity'] != self.watchdog_identity:
            raise Rejection('watchdog_unhealthy', 'no heartbeat from the configured watchdog')
        if effective - session_clock.parse(row['last_tick_at']) > self.watchdog_stale_s:
            raise Rejection('watchdog_unhealthy', 'the watchdog heartbeat is stale')

    def _authority_gate(self, token):
        def gate(effective, session):
            self._require_token(session, token)
            self._require_lease(session, effective)
            self._require_no_cleanup(session)
            self._require_before_c(session, effective)
        return gate

    # ---- registration, control and arming ----------------------------------------------------

    def register_session(self, manifest, manifest_sha256, request_id=None):
        """Durably acknowledge the manifest, ownership and creation intents. Nothing is armed yet."""
        try:
            sha = manifest_mod.verify_manifest(manifest, manifest_sha256)
        except manifest_mod.ManifestError as error:
            raise Rejection('manifest_rejected', 'manifest failed verification', reasons=error.reasons)
        hits = manifest_mod.scan_for_secrets(manifest)
        if hits:
            raise Rejection('secret_value_rejected', 'manifest contains a credential value at ' + ', '.join(hits))
        session_id = manifest['session']['id']
        watchdog = manifest['watchdog']
        if watchdog.get('registry_id') != self.registry_id:
            raise Rejection('wrong_registry', 'manifest names a different registry',
                            expected=self.registry_id, manifest=watchdog.get('registry_id'))
        if watchdog.get('identity') != self.watchdog_identity:
            raise Rejection('wrong_watchdog', 'manifest names a different watchdog',
                            expected=self.watchdog_identity, manifest=watchdog.get('identity'))
        limits = manifest['limits']

        def body(effective, now_text, _):
            existing = self.db.execute('SELECT manifest_sha256 FROM sessions WHERE session_id=?',
                                       (session_id,)).fetchone()
            if existing is not None:
                if existing['manifest_sha256'] != sha:
                    raise Rejection('manifest_conflict', 'a different manifest is already registered for this session')
                return self._registration_ack(session_id, sha, already_registered=True)
            self.db.execute(
                'INSERT INTO sessions(session_id, manifest_sha256, manifest_json, registered_at, state, cap_s, '
                'reserve_s, grace_s, watchdog_identity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (session_id, sha, canonical(manifest), now_text, REGISTERED, float(limits['max_session_duration_s']),
                 float(limits['teardown_reserve_s']), float(limits['evidence_recovery_grace_s']), watchdog['identity']))
            for intent in session_intents(manifest):
                self.db.execute(
                    'INSERT INTO intents(session_id, intent_id, kind, role, expected_name, expected_tags_json, state) '
                    "VALUES (?, ?, ?, ?, ?, ?, 'declared')",
                    (session_id, intent['intent_id'], intent['kind'], intent['role'], intent['expected_name'],
                     canonical(intent['expected_tags'])))
            for tag in manifest['session']['ownership_tags'].values():
                self._insert_resource(session_id, 'tag', tag, tag, None, 'manifest', now_text)
            for listing, target in (('droplets', manifest['session']['ownership_tags']['session']),
                                    ('firewalls', session_id + '-fw')):
                self._insert_resource(session_id, 'inventory_' + listing[:-1], listing, target, None, 'manifest', now_text)
            self.event(now_text, session_id, 'registered', dict(manifest_sha256=sha, ownership=manifest['session']['ownership_tags']))
            return self._registration_ack(session_id, sha)
        return self._mutate('register_session', dict(manifest_sha256=sha, session_id=session_id), request_id, None, body)

    def _registration_ack(self, session_id, sha, already_registered=False):
        return dict(session_id=session_id, manifest_sha256=sha, registry_id=self.registry_id,
                    watchdog_identity=self.watchdog_identity, already_registered=already_registered,
                    intents=[self.intent_view(i) for i in self.intents(session_id)])

    def _insert_resource(self, session_id, kind, provider_id, name, intent_id, source, now_text):
        key = kind + ':' + str(provider_id)
        self.db.execute('INSERT OR IGNORE INTO resources(session_id, resource_key, kind, provider_id, name, intent_id, '
                        "source, status, first_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'unverified', ?)",
                        (session_id, key, kind, str(provider_id), name, intent_id, source, now_text))
        return key

    def intents(self, session_id):
        return self.db.execute('SELECT * FROM intents WHERE session_id=? ORDER BY intent_id', (session_id,)).fetchall()

    @staticmethod
    def intent_view(row):
        return dict(intent_id=row['intent_id'], kind=row['kind'], role=row['role'], expected_name=row['expected_name'],
                    expected_tags=json.loads(row['expected_tags_json']), state=row['state'],
                    request_count=row['request_count'], resource_key=row['resource_key'])

    def acquire_control(self, session_id, controller_id, takeover=False, request_id=None):
        """Grant the next fencing token. Any earlier controller becomes stale at this commit.

        Returning after an interruption never resumes work by itself: a pair that was ready or
        running becomes paused, an active run is marked interrupted, and dispatch stays refused
        until an explicit ``record_resume``. Control may always be taken for status and evidence.
        """
        if not isinstance(controller_id, str) or not controller_id:
            raise Rejection('bad_request', 'controller_id must be a nonempty string')

        def body(effective, now_text, session):
            lease_live = (session['lease_expires_at'] is not None
                          and effective < session_clock.parse(session['lease_expires_at']))
            if lease_live and not takeover:
                raise Rejection('control_held', 'another controller holds a live lease; takeover must be explicit',
                                controller_id=session['controller_id'], lease_expires_at=session['lease_expires_at'])
            token = session['fencing_token'] + 1
            expires = session_clock.iso(effective + self.lease_ttl_s)
            state = session['state']
            if session['fencing_token'] > 0 and state in (READY, RUNNING):
                state = PAUSED
                self._interrupt_active_runs(session_id, now_text, 'controller_replaced')
            self.db.execute('UPDATE sessions SET fencing_token=?, controller_id=?, lease_expires_at=?, state=? '
                            'WHERE session_id=?', (token, controller_id, expires, state, session_id))
            self.event(now_text, session_id, 'control_acquired',
                       dict(controller_id=controller_id, token=token, takeover=bool(takeover),
                            prior_controller=session['controller_id'], prior_token=session['fencing_token'],
                            prior_lease_live=lease_live, state=state))
            return dict(session_id=session_id, fencing_token=token, lease_expires_at=expires, state=state,
                        dispatch_allowed=state == READY)
        return self._mutate('acquire_control', dict(session_id=session_id, controller_id=controller_id,
                                                    takeover=bool(takeover)), request_id, session_id, body)

    def renew_control(self, session_id, fencing_token):
        """A lapsed lease cannot be renewed: a lapse is an interruption, and resume is explicit."""
        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            self._require_lease(session, effective)
            expires = session_clock.iso(effective + self.lease_ttl_s)
            self.db.execute('UPDATE sessions SET lease_expires_at=? WHERE session_id=?', (expires, session_id))
            return dict(fencing_token=fencing_token, lease_expires_at=expires, state=session['state'])
        return self._mutate('renew_control', dict(session_id=session_id, fencing_token=fencing_token), None, session_id, body)

    def arm_session(self, session_id, manifest_sha256, fencing_token, request_id=None):
        """Set t0/D/C once, immediately before the first create. A lost ack replays the same t0."""
        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            self._require_lease(session, effective)
            if session['manifest_sha256'] != manifest_sha256:
                raise Rejection('manifest_conflict', 'arm request names a different manifest')
            if session['t0_utc'] is not None:
                raise Rejection('already_armed', 'the deadline is immutable', t0_utc=session['t0_utc'],
                                deadline_d_utc=session['deadline_d_utc'], cleanup_c_utc=session['cleanup_c_utc'])
            self._require_no_cleanup(session)
            if session['state'] != REGISTERED:
                raise Rejection('bad_state', 'only a registered session can be armed', state=session['state'])
            self._require_watchdog_fresh(effective)
            if session['watchdog_ack_at'] is None:
                raise Rejection('watchdog_unacknowledged', 'the watchdog has not acknowledged this manifest')
            if not self.clock_healthy(effective):
                raise Rejection('clock_unhealthy', 'wall and effective clocks disagree; deadlines would be unreliable')
            deadline = effective + session['cap_s']
            cleanup = deadline - session['reserve_s']
            t0_text, d_text, c_text = now_text, session_clock.iso(deadline), session_clock.iso(cleanup)
            self.db.execute('UPDATE sessions SET t0_utc=?, deadline_d_utc=?, cleanup_c_utc=?, state=? WHERE session_id=?',
                            (t0_text, d_text, c_text, PROVISIONING, session_id))
            self.event(now_text, session_id, 'armed', dict(t0_utc=t0_text, deadline_d_utc=d_text, cleanup_c_utc=c_text,
                                                           manifest_sha256=manifest_sha256, fencing_token=fencing_token))
            return dict(session_id=session_id, manifest_sha256=manifest_sha256, t0_utc=t0_text, deadline_d_utc=d_text,
                        cleanup_c_utc=c_text, max_session_duration_s=session['cap_s'],
                        teardown_reserve_s=session['reserve_s'], registry_id=self.registry_id,
                        watchdog_identity=session['watchdog_identity'], durable=True)
        return self._mutate('arm_session', dict(session_id=session_id, manifest_sha256=manifest_sha256,
                                                fencing_token=fencing_token), request_id, session_id, body)

    # ---- creation intents and owned resources ------------------------------------------------

    def begin_create(self, session_id, intent_id, fencing_token, request_id=None):
        """Persist the create intent, then authorize exactly one provider request for it."""
        authority = self._authority_gate(fencing_token)

        def gate(effective, session):
            authority(effective, session)
            if session['t0_utc'] is None:
                raise Rejection('not_armed', 'no acknowledged deadline exists; provider creation is refused')
            if session['state'] != PROVISIONING:
                raise Rejection('bad_state', 'creates are only admitted while provisioning', state=session['state'])
            if session['watchdog_armed_ack_at'] is None:
                raise Rejection('watchdog_unacknowledged', 'the watchdog has not acknowledged the armed deadline')
            self._require_watchdog_fresh(effective)

        def body(effective, now_text, session):
            intent = self.db.execute('SELECT * FROM intents WHERE session_id=? AND intent_id=?',
                                     (session_id, intent_id)).fetchone()
            if intent is None:
                raise Rejection('unknown_intent', 'intent is not part of this manifest: ' + str(intent_id))
            if intent['state'] in ('requested', 'ambiguous'):
                raise Rejection('create_outcome_unknown', 'reconcile the earlier request by tag before creating again',
                                must_reconcile=True, requested_at=intent['requested_at'], **self.intent_view(intent))
            if intent['state'] == 'created':
                raise Rejection('already_created', 'intent already has an exact resource id',
                                resource_key=intent['resource_key'])
            self.db.execute("UPDATE intents SET state='requested', requested_at=?, request_count=request_count+1 "
                            'WHERE session_id=? AND intent_id=?', (now_text, session_id, intent_id))
            self.event(now_text, session_id, 'create_intent_requested',
                       dict(intent_id=intent_id, request_count=intent['request_count'] + 1, fencing_token=fencing_token))
            return dict(self.intent_view(self.db.execute('SELECT * FROM intents WHERE session_id=? AND intent_id=?',
                                                          (session_id, intent_id)).fetchone()),
                        t0_utc=session['t0_utc'], cleanup_c_utc=session['cleanup_c_utc'],
                        deadline_d_utc=session['deadline_d_utc'], authorized=True, must_reconcile=False)
        result = self._mutate('begin_create', dict(session_id=session_id, intent_id=intent_id, fencing_token=fencing_token),
                              request_id, session_id, body, gate=gate)
        if result.get('replayed'):
            # The earlier grant may already have reached the provider.
            result = dict(result, authorized=False, must_reconcile=True)
        return result

    def record_create_result(self, session_id, intent_id, outcome, fencing_token=None, note=None, request_id=None):
        """``ambiguous``/``rejected`` are facts, accepted from anyone. Re-enabling a create is gated."""
        if outcome not in ('ambiguous', 'rejected', 'reconciled_absent'):
            raise Rejection('bad_request', 'unknown create result: ' + str(outcome))
        gate = None
        if outcome == 'reconciled_absent':
            if not isinstance(note, str) or not note.strip():
                raise Rejection('bad_request', 'reconciled_absent needs a reference to the authenticated listing')
            gate = self._authority_gate(fencing_token)

        def body(effective, now_text, session):
            intent = self.db.execute('SELECT * FROM intents WHERE session_id=? AND intent_id=?',
                                     (session_id, intent_id)).fetchone()
            if intent is None:
                raise Rejection('unknown_intent', 'intent is not part of this manifest: ' + str(intent_id))
            if intent['state'] == 'created':
                return self.intent_view(intent)
            if intent['state'] not in ('requested', 'ambiguous'):
                raise Rejection('bad_state', 'intent has no outstanding create', state=intent['state'])
            state = dict(ambiguous='ambiguous', rejected='rejected', reconciled_absent='declared')[outcome]
            resolved = now_text if state == 'rejected' else None
            self.db.execute('UPDATE intents SET state=?, note=?, resolved_at=? WHERE session_id=? AND intent_id=?',
                            (state, note, resolved, session_id, intent_id))
            self.event(now_text, session_id, 'create_result', dict(intent_id=intent_id, outcome=outcome, note=note))
            return self.intent_view(self.db.execute('SELECT * FROM intents WHERE session_id=? AND intent_id=?',
                                                     (session_id, intent_id)).fetchone())
        return self._mutate('record_create_result', dict(session_id=session_id, intent_id=intent_id, outcome=outcome,
                                                         fencing_token=fencing_token, note=note), request_id, session_id, body, gate=gate)

    def record_resource(self, session_id, kind, provider_id, intent_id=None, name=None, request_id=None):
        """Persist a returned exact id. Accepted from any controller: knowing an id is always safe.

        Recording does not grant deletion: the watchdog still verifies ownership on read. A report
        that arrives after closure means the receipt was wrong, so cleanup reopens.
        """
        if kind not in ('droplet', 'firewall', 'tag'):
            raise Rejection('bad_request', 'unknown resource kind: ' + str(kind))
        if provider_id in (None, ''):
            raise Rejection('bad_request', 'provider_id is required')

        def body(effective, now_text, session):
            if session['t0_utc'] is None:
                # begin_create refuses an unarmed session, so this report breaks the protocol.
                raise Rejection('not_armed', 'no resource can exist for a session that was never armed')
            if intent_id is not None:
                intent = self.db.execute('SELECT * FROM intents WHERE session_id=? AND intent_id=?',
                                         (session_id, intent_id)).fetchone()
                if intent is None:
                    raise Rejection('unknown_intent', 'intent is not part of this manifest: ' + str(intent_id))
                if intent['kind'] != kind:
                    raise Rejection('bad_request', 'intent kind does not match resource kind')
            key = self.record_resource_row(session_id, kind, provider_id, intent_id, name, 'controller', now_text)
            return dict(session_id=session_id, resource_key=key)
        return self._mutate('record_resource', dict(session_id=session_id, kind=kind, provider_id=str(provider_id),
                                                    intent_id=intent_id, name=name), request_id, session_id, body)

    def record_resource_row(self, session_id, kind, provider_id, intent_id, name, source, now_text):
        """Shared by controller reports and watchdog discovery, inside the caller's transaction."""
        key = self._insert_resource(session_id, kind, provider_id, name, intent_id, source, now_text)
        if intent_id is not None:
            prior = self.db.execute('SELECT resource_key, state FROM intents WHERE session_id=? AND intent_id=?',
                                    (session_id, intent_id)).fetchone()
            if prior['state'] == 'created' and prior['resource_key'] != key:
                self.event(now_text, session_id, 'duplicate_create',
                           dict(intent_id=intent_id, first=prior['resource_key'], second=key))
            else:
                self.db.execute("UPDATE intents SET state='created', resource_key=?, resolved_at=? "
                                'WHERE session_id=? AND intent_id=?', (key, now_text, session_id, intent_id))
        self.event(now_text, session_id, 'resource_recorded', dict(resource_key=key, intent_id=intent_id, source=source))
        session = self.session_row(session_id)
        if session['state'] == CLOSED:
            self.db.execute("UPDATE sessions SET state=?, cleanup_outcome='in_progress', cleanup_verified_at=NULL "
                            'WHERE session_id=?', (DELETING, session_id))
            self.open_incident(session_id, 'late-resource-after-close', now_text, dict(resource_key=key),
                               last_error='a resource was reported after a clean closure')
        return key

    def mark_ready(self, session_id, fencing_token, evidence_ref, request_id=None):
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise Rejection('bad_request', 'pair readiness requires an evidence reference')

        def body(effective, now_text, session):
            if session['state'] != PROVISIONING:
                raise Rejection('bad_state', 'only a provisioning session can become ready', state=session['state'])
            missing = [i['intent_id'] for i in self.intents(session_id) if i['kind'] == 'droplet' and i['state'] != 'created']
            if missing:
                raise Rejection('pair_incomplete', 'both roles need an exact recorded id', missing=missing)
            self.db.execute('UPDATE sessions SET state=?, ready_at=?, ready_evidence_ref=? WHERE session_id=?',
                            (READY, now_text, evidence_ref, session_id))
            self.event(now_text, session_id, 'pair_ready', dict(evidence_ref=evidence_ref))
            return dict(session_id=session_id, state=READY, ready_at=now_text, t0_utc=session['t0_utc'])
        return self._mutate('mark_ready', dict(session_id=session_id, fencing_token=fencing_token, evidence_ref=evidence_ref),
                            request_id, session_id, body, gate=self._authority_gate(fencing_token))

    # ---- workload dispatch -------------------------------------------------------------------

    def dispatch_run(self, session_id, run_id, fencing_token, manifest_sha256, estimated_duration_s,
                     trial=None, request_id=None):
        """Journal the dispatch intent, then authorize one launch before ``launch_by``."""
        if not isinstance(run_id, str) or not run_id:
            raise Rejection('bad_request', 'run_id must be a nonempty string')
        if (not isinstance(estimated_duration_s, (int, float)) or isinstance(estimated_duration_s, bool)
                or estimated_duration_s <= 0):
            raise Rejection('bad_request', 'estimated_duration_s must be positive')
        authority = self._authority_gate(fencing_token)

        def gate(effective, session):
            authority(effective, session)
            if session['manifest_sha256'] != manifest_sha256:
                raise Rejection('manifest_conflict', 'dispatch names a different manifest')
            if session['terminal_failure'] is not None:
                raise Rejection('terminal_failure', 'a terminal failure stopped this batch',
                                outcome=session['terminal_failure'])
            self._require_watchdog_fresh(effective)     # no workload without a live cleanup path

        def body(effective, now_text, session):
            if session['state'] != READY:
                raise Rejection('bad_state', 'dispatch needs a ready pair and no active run', state=session['state'])
            if effective + estimated_duration_s > session_clock.parse(session['cleanup_c_utc']) - CLEANUP_LEAD_S:
                raise Rejection('does_not_fit', 'the run cannot finish before cleanup starts for C',
                                cleanup_c_utc=session['cleanup_c_utc'], cleanup_lead_s=CLEANUP_LEAD_S)
            if self.db.execute('SELECT 1 FROM runs WHERE session_id=? AND run_id=?', (session_id, run_id)).fetchone():
                raise Rejection('duplicate_run', 'a run id is dispatched at most once: ' + run_id)
            launch_by = min(effective + self.launch_window_s, session_clock.parse(session['lease_expires_at']),
                            session_clock.parse(session['cleanup_c_utc']))
            launch_text = session_clock.iso(launch_by)
            self.db.execute('INSERT INTO runs(session_id, run_id, state, dispatched_at, fencing_token, controller_id, '
                            "launch_by, trial_json) VALUES (?, ?, 'dispatched', ?, ?, ?, ?, ?)",
                            (session_id, run_id, now_text, fencing_token, session['controller_id'], launch_text,
                             canonical(trial) if trial is not None else None))
            self.db.execute('UPDATE sessions SET state=? WHERE session_id=?', (RUNNING, session_id))
            self.event(now_text, session_id, 'run_dispatch_intent',
                       dict(run_id=run_id, fencing_token=fencing_token, launch_by=launch_text))
            return dict(session_id=session_id, run_id=run_id, authorized=True, launch_by=launch_text, fencing_token=fencing_token)
        result = self._mutate('dispatch_run', dict(session_id=session_id, run_id=run_id, fencing_token=fencing_token,
                                                   manifest_sha256=manifest_sha256, estimated_duration_s=estimated_duration_s,
                                                   trial=trial), request_id, session_id, body, gate=gate)
        if result.get('replayed'):
            # A lost ack may replay the grant, but a finished run or a closed launch window may not.
            run = self.db.execute('SELECT state FROM runs WHERE session_id=? AND run_id=?', (session_id, run_id)).fetchone()
            launchable = (run is not None and run['state'] == 'dispatched'
                          and self.peek_now() < session_clock.parse(result['launch_by']))
            result = dict(result, authorized=launchable)
        return result

    def _interrupt_active_runs(self, session_id, now_text, reason):
        active = self.db.execute("SELECT run_id FROM runs WHERE session_id=? AND state='dispatched'", (session_id,)).fetchall()
        for row in active:
            self.db.execute("UPDATE runs SET state='interrupted', interrupted_at=?, interrupted_reason=? "
                            'WHERE session_id=? AND run_id=?', (now_text, reason, session_id, row['run_id']))
            self.event(now_text, session_id, 'run_interrupted', dict(run_id=row['run_id'], reason=reason))

    def record_run_outcome(self, session_id, run_id, outcome, fencing_token, evidence_ref=None, request_id=None):
        """Measurement facts stay recordable during cleanup and after closure, by the current token."""
        if outcome not in search.OUTCOMES:
            raise Rejection('bad_request', 'unknown run outcome: ' + str(outcome))
        if outcome in search.ADVANCING and (not isinstance(evidence_ref, str) or not evidence_ref.strip()):
            raise Rejection('bad_request', outcome + ' requires an evidence reference')

        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            run = self.db.execute('SELECT * FROM runs WHERE session_id=? AND run_id=?', (session_id, run_id)).fetchone()
            if run is None:
                raise Rejection('unknown_run', 'no dispatch was journaled for ' + str(run_id))
            if run['outcome'] is not None:
                raise Rejection('outcome_recorded', 'a run outcome is immutable', outcome=run['outcome'])
            self.db.execute("UPDATE runs SET state='finished', finished_at=?, outcome=?, evidence_ref=? "
                            'WHERE session_id=? AND run_id=?', (now_text, outcome, evidence_ref, session_id, run_id))
            state = READY if session['state'] == RUNNING else session['state']
            terminal = session['terminal_failure']
            if outcome in search.STOPPING and terminal is None:
                terminal = outcome
            self.db.execute('UPDATE sessions SET state=?, terminal_failure=? WHERE session_id=?', (state, terminal, session_id))
            self.event(now_text, session_id, 'run_outcome', dict(run_id=run_id, outcome=outcome, evidence_ref=evidence_ref))
            return dict(session_id=session_id, run_id=run_id, outcome=outcome, state=state, terminal_failure=terminal)
        return self._mutate('record_run_outcome', dict(session_id=session_id, run_id=run_id, outcome=outcome,
                                                       fencing_token=fencing_token, evidence_ref=evidence_ref),
                            request_id, session_id, body)

    def record_resume(self, session_id, fencing_token, operator_request_ref, checks, request_id=None):
        """Record an explicit operator resume and its checks. Only untouched work can follow."""
        if not isinstance(operator_request_ref, str) or not operator_request_ref.strip():
            raise Rejection('bad_request', 'resume needs an explicit operator request reference')
        if not isinstance(checks, dict) or not checks:
            raise Rejection('bad_request', 'resume must record the revalidation checks')

        def body(effective, now_text, session):
            if session['state'] != PAUSED:
                raise Rejection('bad_state', 'only a paused session can resume', state=session['state'])
            if session['terminal_failure'] is not None:
                raise Rejection('terminal_failure', 'a terminal failure cannot be resumed past',
                                outcome=session['terminal_failure'])
            unclassified = self.db.execute("SELECT run_id FROM runs WHERE session_id=? AND outcome IS NULL", (session_id,)).fetchall()
            if unclassified:
                raise Rejection('interrupted_run_unclassified', 'record each interrupted run before resuming',
                                run_ids=[r['run_id'] for r in unclassified])
            self.db.execute('UPDATE sessions SET state=? WHERE session_id=?', (READY, session_id))
            self.event(now_text, session_id, 'resumed', dict(operator_request_ref=operator_request_ref, checks=checks,
                                                             fencing_token=fencing_token))
            return dict(session_id=session_id, state=READY, t0_utc=session['t0_utc'], cleanup_c_utc=session['cleanup_c_utc'])
        return self._mutate('record_resume', dict(session_id=session_id, fencing_token=fencing_token,
                                                  operator_request_ref=operator_request_ref, checks=checks),
                            request_id, session_id, body, gate=self._authority_gate(fencing_token))

    # ---- collection and independent outcome fields -------------------------------------------

    def begin_collection(self, session_id, fencing_token, request_id=None):
        def body(effective, now_text, session):
            if session['state'] not in (READY, PAUSED, EVIDENCE_RECOVERY):
                raise Rejection('bad_state', 'collection follows a finished batch', state=session['state'])
            self.db.execute('UPDATE sessions SET state=? WHERE session_id=?', (COLLECTING, session_id))
            self.event(now_text, session_id, 'collecting', {})
            return dict(session_id=session_id, state=COLLECTING)
        return self._mutate('begin_collection', dict(session_id=session_id, fencing_token=fencing_token), request_id,
                            session_id, body, gate=self._authority_gate(fencing_token))

    def begin_evidence_recovery(self, session_id, fencing_token, request_id=None):
        """One bounded episode: min(first_failure + grace, C). Retries never reset its clock."""
        def body(effective, now_text, session):
            if session['state'] not in (COLLECTING, EVIDENCE_RECOVERY):
                raise Rejection('bad_state', 'recovery follows a failed collection', state=session['state'])
            deadline_text = session['recovery_deadline_utc']
            first = session['recovery_first_failure_at']
            if deadline_text is None:
                first = now_text
                deadline = min(effective + session['grace_s'], session_clock.parse(session['cleanup_c_utc']))
                deadline_text = session_clock.iso(deadline)
            elif effective >= session_clock.parse(deadline_text):
                raise Rejection('recovery_expired', 'the recovery episode is over', recovery_deadline_utc=deadline_text)
            self.db.execute('UPDATE sessions SET state=?, recovery_first_failure_at=?, recovery_deadline_utc=? '
                            'WHERE session_id=?', (EVIDENCE_RECOVERY, first, deadline_text, session_id))
            self.event(now_text, session_id, 'evidence_recovery', dict(first_failure=first, deadline=deadline_text))
            return dict(session_id=session_id, state=EVIDENCE_RECOVERY, first_failure_at=first, recovery_deadline_utc=deadline_text)
        return self._mutate('begin_evidence_recovery', dict(session_id=session_id, fencing_token=fencing_token), request_id,
                            session_id, body, gate=self._authority_gate(fencing_token))

    def record_measurement(self, session_id, fencing_token, outcome, ref=None, request_id=None):
        if not isinstance(outcome, str) or not outcome:
            raise Rejection('bad_request', 'measurement outcome must be a nonempty label')

        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            self.db.execute('UPDATE sessions SET measurement_outcome=?, measurement_ref=?, measurement_updated_at=? '
                            'WHERE session_id=?', (outcome, ref, now_text, session_id))
            self.event(now_text, session_id, 'measurement_recorded', dict(outcome=outcome, ref=ref))
            return dict(session_id=session_id, measurement_outcome=outcome)
        return self._mutate('record_measurement', dict(session_id=session_id, fencing_token=fencing_token, outcome=outcome, ref=ref),
                            request_id, session_id, body)

    def record_evidence(self, session_id, fencing_token, status, ref=None, request_id=None):
        if status not in EVIDENCE_STATUSES:
            raise Rejection('bad_request', 'unknown evidence status: ' + str(status))

        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            self.db.execute('UPDATE sessions SET evidence_status=?, evidence_ref=?, evidence_updated_at=? WHERE session_id=?',
                            (status, ref, now_text, session_id))
            self.event(now_text, session_id, 'evidence_recorded', dict(status=status, ref=ref))
            return dict(session_id=session_id, evidence_status=status)
        return self._mutate('record_evidence', dict(session_id=session_id, fencing_token=fencing_token, status=status, ref=ref),
                            request_id, session_id, body)

    # ---- cleanup requests --------------------------------------------------------------------

    def begin_cleanup_row(self, session, now_text, reason, actor):
        """Persist cleanup intent, inside the caller's transaction, before any delete is issued."""
        session_id = session['session_id']
        self.db.execute("UPDATE sessions SET state=?, cleanup_requested_at=?, cleanup_reason=?, cleanup_actor=?, "
                        "cleanup_outcome='in_progress' WHERE session_id=?", (DELETING, now_text, reason, actor, session_id))
        self._interrupt_active_runs(session_id, now_text, 'cleanup_started')
        self.event(now_text, session_id, 'cleanup_intent', dict(reason=reason, actor=actor, prior_state=session['state']))

    def _cleanup_view(self, session_id):
        session = self.session_row(session_id)
        return dict(session_id=session_id, state=session['state'], cleanup_requested_at=session['cleanup_requested_at'],
                    cleanup_reason=session['cleanup_reason'], deadline_d_utc=session['deadline_d_utc'])

    def request_cleanup(self, session_id, fencing_token, reason, request_id=None):
        """The current controller asks for prompt deletion. A stale controller has no such power."""
        if not isinstance(reason, str) or not reason.strip():
            raise Rejection('bad_request', 'cleanup needs a reason')

        def body(effective, now_text, session):
            self._require_token(session, fencing_token)
            if session['cleanup_requested_at'] is None:
                if session['t0_utc'] is None:
                    self._close_never_armed(session, now_text, reason, session['controller_id'] or 'controller')
                else:
                    self.begin_cleanup_row(session, now_text, reason, 'controller:' + str(session['controller_id']))
            return self._cleanup_view(session_id)
        return self._mutate('request_cleanup', dict(session_id=session_id, fencing_token=fencing_token, reason=reason),
                            request_id, session_id, body)

    def operator_abort(self, session_id, reason, request_id=None):
        """The operator's abort needs no live controller token; cleanup always takes precedence."""
        if not isinstance(reason, str) or not reason.strip():
            raise Rejection('bad_request', 'abort needs a reason')

        def body(effective, now_text, session):
            if session['cleanup_requested_at'] is None:
                if session['t0_utc'] is None:
                    self._close_never_armed(session, now_text, reason, 'operator')
                else:
                    self.begin_cleanup_row(session, now_text, reason, 'operator')
            return self._cleanup_view(session_id)
        return self._mutate('operator_abort', dict(session_id=session_id, reason=reason), request_id, session_id, body)

    def _close_never_armed(self, session, now_text, reason, actor):
        # begin_create refuses an unarmed session, so nothing was ever created for it.
        self.db.execute('UPDATE sessions SET state=?, cleanup_requested_at=?, cleanup_reason=?, cleanup_actor=?, '
                        'cleanup_outcome=?, cleanup_verified_at=? WHERE session_id=?',
                        (CLOSED, now_text, reason, actor, NEVER_ARMED, now_text, session['session_id']))
        self.event(now_text, session['session_id'], 'closed_never_armed', dict(reason=reason, actor=actor))

    def disown_resource(self, session_id, resource_key, operator_note, request_id=None):
        """Operator disposition for a refused resource: it is not ours and will not be deleted."""
        if not isinstance(operator_note, str) or not operator_note.strip():
            raise Rejection('bad_request', 'a disposition needs an operator note')

        def body(effective, now_text, session):
            row = self.db.execute('SELECT * FROM resources WHERE session_id=? AND resource_key=?',
                                  (session_id, resource_key)).fetchone()
            if row is None or row['status'] != 'ownership_refused':
                raise Rejection('bad_state', 'only an ownership-refused resource can be disowned')
            self.db.execute("UPDATE resources SET status='disowned', burst_state='idle', burst_next_at=NULL "
                            'WHERE session_id=? AND resource_key=?', (session_id, resource_key))
            self.event(now_text, session_id, 'resource_disowned', dict(resource_key=resource_key, note=operator_note))
            incident = self.db.execute("SELECT incident_id, detail_json FROM incidents WHERE session_id=? "
                                       "AND kind='ownership-mismatch' AND status='open'", (session_id,)).fetchall()
            for row_incident in incident:
                if json.loads(row_incident['detail_json']).get('resource_key') == resource_key:
                    self.resolve_incident(row_incident['incident_id'], now_text)
            return dict(session_id=session_id, resource_key=resource_key, status='disowned')
        return self._mutate('disown_resource', dict(session_id=session_id, resource_key=resource_key,
                                                    operator_note=operator_note), request_id, session_id, body)

    # ---- read-only views ---------------------------------------------------------------------

    def watchdog_view(self):
        return dict(self.db.execute('SELECT * FROM watchdog_status WHERE id=1').fetchone())

    def health(self, session_id=None):
        """Exactly the ``infra_health`` shape that planner admission checks."""
        effective = self.peek_now()
        watchdog = self.watchdog_view()
        fresh = (watchdog['last_tick_at'] is not None and watchdog['identity'] == self.watchdog_identity
                 and effective - session_clock.parse(watchdog['last_tick_at']) <= self.watchdog_stale_s)
        clock_ok = self.clock_healthy(effective)
        sha = watchdog_sha = None
        if session_id is not None:
            row = self.db.execute('SELECT manifest_sha256, watchdog_ack_at FROM sessions WHERE session_id=?',
                                  (session_id,)).fetchone()
            if row is not None:
                sha = row['manifest_sha256']
                watchdog_sha = sha if row['watchdog_ack_at'] else None
        return dict(registry=dict(healthy=clock_ok, registry_id=self.registry_id, clock_healthy=clock_ok,
                                  acknowledged_manifest_sha256=sha),
                    watchdog=dict(healthy=bool(fresh), identity=self.watchdog_identity,
                                  last_tick_at=watchdog['last_tick_at'], acknowledged_manifest_sha256=watchdog_sha),
                    evaluated_at=session_clock.iso(effective))

    def incidents(self, session_id=None, status=None):
        query, args = 'SELECT * FROM incidents WHERE 1=1', []
        if session_id is not None:
            query += ' AND session_id=?'
            args.append(session_id)
        if status is not None:
            query += ' AND status=?'
            args.append(status)
        return [self.incident_view(row) for row in self.db.execute(query + ' ORDER BY incident_id', args).fetchall()]

    @staticmethod
    def incident_view(row):
        return dict(incident_id=row['incident_id'], session_id=row['session_id'], kind=row['kind'], status=row['status'],
                    opened_at=row['opened_at'], resolved_at=row['resolved_at'], overrun_s=row['overrun_s'],
                    last_error=row['last_error'], detail=json.loads(row['detail_json']), version=row['version'])

    def incident_report(self, incident_id):
        """Everything an operator needs on reconnect: ids, deadline, attempts, errors. Never a token."""
        row = self.db.execute('SELECT * FROM incidents WHERE incident_id=?', (incident_id,)).fetchone()
        if row is None:
            raise Rejection('unknown_incident', 'no such incident: ' + str(incident_id))
        view = self.incident_view(row)
        session_id = view['session_id']
        if session_id is None:
            return view
        session = self.session_row(session_id)
        resources = [r for r in self.resources(session_id) if r['kind'] not in LISTING_KINDS]
        unverified = [r for r in resources if r['status'] not in TERMINAL_RESOURCE_STATES]
        total = self.db.execute('SELECT COUNT(*) AS n FROM attempts WHERE session_id=?', (session_id,)).fetchone()['n']
        recent = self.db.execute('SELECT * FROM attempts WHERE session_id=? ORDER BY attempt_id DESC LIMIT ?',
                                 (session_id, INCIDENT_ATTEMPT_TAIL)).fetchall()
        view.update(
            t0_utc=session['t0_utc'], cleanup_c_utc=session['cleanup_c_utc'], deadline_d_utc=session['deadline_d_utc'],
            cleanup_outcome=session['cleanup_outcome'], cleanup_verified_at=session['cleanup_verified_at'],
            resources=[dict(resource_key=r['resource_key'], kind=r['kind'], provider_id=r['provider_id'], name=r['name'],
                            status=r['status'], attempts=r['attempt_total'], last_error=r['last_error'],
                            verified_absent_at=r['verified_absent_at']) for r in resources],
            unverified_resource_keys=[r['resource_key'] for r in unverified],
            attempt_total=total,
            recent_attempts=[dict(attempt_id=a['attempt_id'], resource_key=a['resource_key'], op=a['op'], started_at=a['started_at'],
                                  finished_at=a['finished_at'], result=a['result'], http_status=a['http_status'],
                                  error_class=a['error_class'], message=a['message']) for a in reversed(recent)],
            remediation=self._remediation(session_id, unverified))
        return view

    @staticmethod
    def _remediation(session_id, unverified):
        commands = ['registry_cli.py status --state-dir <state-dir> --session ' + session_id,
                    'registry_cli.py journal --state-dir <state-dir> --session ' + session_id]
        for row in unverified:
            if row['kind'] == 'droplet':
                commands.append('doctl compute droplet get ' + row['provider_id'] + '   # verify ownership before any manual delete')
            elif row['kind'] == 'firewall':
                commands.append('doctl compute firewall get ' + row['provider_id'])
            elif row['kind'] == 'tag':
                commands.append('doctl compute tag get ' + row['provider_id'])
        return commands

    def resources(self, session_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM resources WHERE session_id=? ORDER BY resource_key', (session_id,))]

    def attempts(self, session_id, resource_key=None):
        query, args = 'SELECT * FROM attempts WHERE session_id=?', [session_id]
        if resource_key is not None:
            query += ' AND resource_key=?'
            args.append(resource_key)
        return [dict(r) for r in self.db.execute(query + ' ORDER BY attempt_id', args)]

    def runs(self, session_id):
        return [dict(r) for r in self.db.execute('SELECT * FROM runs WHERE session_id=? ORDER BY dispatched_at, run_id', (session_id,))]

    def manifest(self, session_id):
        return json.loads(self.session_row(session_id)['manifest_json'])

    def status(self, session_id):
        """The three outcomes stay separate. ``overall`` only combines them, never overwrites them."""
        session = self.session_row(session_id)
        incidents = self.incidents(session_id)
        overdue = [i for i in incidents if i['kind'] == 'cleanup-overdue']
        return dict(
            session_id=session_id, manifest_sha256=session['manifest_sha256'], state=session['state'],
            t0_utc=session['t0_utc'], deadline_d_utc=session['deadline_d_utc'], cleanup_c_utc=session['cleanup_c_utc'],
            controller_id=session['controller_id'], fencing_token=session['fencing_token'],
            lease_expires_at=session['lease_expires_at'], terminal_failure=session['terminal_failure'],
            recovery_deadline_utc=session['recovery_deadline_utc'],
            measurement=dict(outcome=session['measurement_outcome'], ref=session['measurement_ref'],
                             updated_at=session['measurement_updated_at']),
            evidence=dict(status=session['evidence_status'], ref=session['evidence_ref'],
                          updated_at=session['evidence_updated_at']),
            cleanup=dict(outcome=session['cleanup_outcome'], requested_at=session['cleanup_requested_at'],
                         reason=session['cleanup_reason'], actor=session['cleanup_actor'],
                         verified_at=session['cleanup_verified_at'], overrun_s=session['overrun_s'],
                         overdue=bool(overdue)),
            overall=self._overall(session, overdue),
            resources=[dict(resource_key=r['resource_key'], kind=r['kind'], provider_id=r['provider_id'], name=r['name'],
                            status=r['status'], source=r['source'], attempts=r['attempt_total'],
                            last_error=r['last_error'], verified_absent_at=r['verified_absent_at'])
                       for r in self.resources(session_id) if not r['kind'].startswith('inventory_')],
            intents=[self.intent_view(i) for i in self.intents(session_id)],
            runs=[dict(run_id=r['run_id'], state=r['state'], outcome=r['outcome'], evidence_ref=r['evidence_ref'],
                       interrupted_reason=r['interrupted_reason']) for r in self.runs(session_id)],
            incidents=incidents)

    @staticmethod
    def _overall(session, overdue):
        if session['cleanup_outcome'] == NEVER_ARMED:
            return 'closed_never_armed'
        if session['cleanup_outcome'] not in (VERIFIED_ABSENT, VERIFIED_WITH_DISPOSITION):
            return 'cleanup_overdue' if overdue else 'cleanup_not_verified'
        if session['cleanup_outcome'] == VERIFIED_WITH_DISPOSITION:
            return 'resources_verified_with_operator_disposition'
        if session['evidence_status'] != 'complete':
            return 'resources_verified_evidence_incomplete'
        return 'resources_verified_after_overdue' if overdue else 'clean'

    def list_sessions(self):
        return [dict(session_id=r['session_id'], state=r['state'], deadline_d_utc=r['deadline_d_utc'],
                     cleanup_outcome=r['cleanup_outcome'])
                for r in self.db.execute('SELECT * FROM sessions ORDER BY session_id')]

    # ---- transport-neutral entry point -------------------------------------------------------

    RPC_METHODS = ('register_session', 'acquire_control', 'renew_control', 'arm_session', 'begin_create',
                   'record_create_result', 'record_resource', 'mark_ready', 'dispatch_run', 'record_run_outcome',
                   'record_resume', 'begin_collection', 'begin_evidence_recovery', 'record_measurement',
                   'record_evidence', 'request_cleanup', 'operator_abort', 'disown_resource', 'health', 'status',
                   'incidents', 'incident_report', 'journal', 'list_sessions', 'verify_journal')

    def rpc(self, request):
        """One JSON request to one JSON response. Only an ``ok`` response is an acknowledgement."""
        try:
            method = request.get('method') if isinstance(request, dict) else None
            params = request.get('params', {}) if isinstance(request, dict) else None
            if method not in self.RPC_METHODS or not isinstance(params, dict):
                raise Rejection('bad_request', 'unknown method or malformed params')
            try:
                result = getattr(self, method)(**params)
            except TypeError as error:
                raise Rejection('bad_request', 'bad parameters for ' + str(method) + ': ' + str(error))
            last = self.db.execute('SELECT MAX(seq) AS seq FROM events').fetchone()
            return dict(ok=True, result=result, ack=dict(registry_id=self.registry_id, journal_seq=last['seq']))
        except Rejection as rejection:
            return rejection.to_response()
        except sqlite3.Error as error:
            return dict(ok=False, code='registry_storage_error', message=type(error).__name__ + ': ' + str(error), details={})
