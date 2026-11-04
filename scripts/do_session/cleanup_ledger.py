"""Durable cleanup state machine for the watchdog (lifecycle contract #59 §6, handoff #61 §2).

Everything here is one registry transaction, and everything the watchdog needs to survive a crash
is in those rows: cleanup intent, per-resource burst progress, each attempt (written *before* its
side effect) and each result. The watchdog loop only decides when to call these methods.

A *burst* is one resource's work for one 15-second sweep: at most six provider requests, with
exponential backoff capped at 30 s, spread across as many polling ticks as that takes. A resource
has at most one active burst, so a later sweep or a restart continues it and never stacks another.
A finished burst is followed by a new one on a later sweep, indefinitely: nothing billable is
abandoned. An accepted DELETE only moves a resource to ``delete_accepted``. Only an authenticated
read returning absent verifies it, and a session closes only after a fresh, empty inventory and
settled create requests.

Cleanup has a read-only half and a destructive half. Ownership preparation reads known Droplets from
``C - lead``, while a workload or evidence recovery may still be running; it changes no session state.
The destructive half needs durable cleanup intent, and at C that intent and the first delete happen
on one tick. A delete is therefore never issued during preparation, by construction.

Droplets go first and are never held back. Firewalls and tags wait until every outstanding create
has settled, because a late Droplet would land unprotected and recreate its tags. Elapsed time settles
nothing: an unresolved create keeps protection in place and blocks closure until the resource is seen
or typed evidence (``create_evidence``) arrives. Reconciliation keeps looking and overdue stays visible.

Deletion authority is the exact recorded id plus matching session ownership; project membership
is never consulted, and a mismatch becomes an incident instead of a delete.
"""
import json

import cleanup_provider
import create_evidence
import deadline_capacity
import registry as registry_mod
import session_clock

MAX_ATTEMPTS_PER_BURST = 6
BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 30.0
SWEEP_INTERVAL_S = 15.0
DEFAULT_RATE_LIMIT_HOLD_S = 30.0
MAX_RATE_LIMIT_HOLD_S = 3600.0
REDELETE_AFTER_S = 60.0
PREPARE_LEAD_S = registry_mod.PREPARE_LEAD_S
DELETE_MARGIN_S = registry_mod.DELETE_MARGIN_S
CHAIN_TAIL_TICKS = 2
DEFAULT_TICK_INTERVAL_S = 1.0

TERMINAL = registry_mod.TERMINAL_RESOURCE_STATES
PENDING_CREATE = registry_mod.PENDING_CREATE_STATES
LISTING_KINDS = registry_mod.LISTING_KINDS
BOOKKEEPING_KINDS = registry_mod.BOOKKEEPING_KINDS
CREATE_REQUEST_KIND = registry_mod.CREATE_REQUEST_KIND
SETTLEMENT_OP = 'get_request_settlement'
READ_OPS = dict(droplet='get_droplet', firewall='get_firewall', tag='get_tag')
DELETE_OPS = dict(droplet='delete_droplet', firewall='delete_firewall', tag='delete_tag')
LIST_OPS = dict(inventory_droplet='list_droplets_by_tag', inventory_firewall='list_firewalls_by_name')
KIND_PRIORITY = dict(droplet=0, inventory_droplet=1, create_request=2, firewall=3, inventory_firewall=4, tag=5)


def backoff_s(attempts_done):
    return min(BACKOFF_CAP_S, BACKOFF_BASE_S ** attempts_done)


class CleanupLedger:
    def __init__(self, registry, identity, redelete_after_s=REDELETE_AFTER_S, sweep_interval_s=SWEEP_INTERVAL_S,
                 prepare_lead_s=PREPARE_LEAD_S, delete_margin_s=DELETE_MARGIN_S, deadline_slots=0,
                 request_bound_s=session_clock.PROVIDER_REQUEST_BOUND_S, tick_interval_s=DEFAULT_TICK_INTERVAL_S):
        self.registry = registry
        self.db = registry.db
        self.identity = identity
        self.redelete_after_s = redelete_after_s
        self.sweep_interval_s = sweep_interval_s
        self.prepare_lead_s = prepare_lead_s
        self.delete_margin_s = delete_margin_s
        self.deadline_slots = deadline_slots
        self.request_bound_s = request_bound_s
        self.tick_interval_s = tick_interval_s
        self.ownership_fresh_s = prepare_lead_s + sweep_interval_s

    @property
    def chain_tail_s(self):
        """A delete issued by C holds its reserved slot until its bound, noticed within two ticks."""
        return self.request_bound_s + CHAIN_TAIL_TICKS * self.tick_interval_s

    def _publish_capacity(self):
        self.db.execute('UPDATE watchdog_status SET deadline_slots=?, prepare_lead_s=?, chain_tail_s=? WHERE id=1',
                        (self.deadline_slots, self.prepare_lead_s, self.chain_tail_s))

    def _check_admitted_capacity(self, effective, now_text):
        """A restart with fewer slots cannot unarm anyone, so the broken promise must at least be visible."""
        cleanups = [session_clock.parse(row['cleanup_c_utc']) for row in self.db.execute(
            'SELECT cleanup_c_utc FROM sessions WHERE t0_utc IS NOT NULL AND state != ?', (registry_mod.CLOSED,))]
        cleanups = [c for c in cleanups if c + self.chain_tail_s > effective]
        peak = deadline_capacity.overall_peak(cleanups, self.prepare_lead_s, self.chain_tail_s)
        incident = self.registry.open_incident_of(None, 'deadline-capacity-overcommitted')
        if peak > self.deadline_slots and incident is None:
            self.registry.open_incident(None, 'deadline-capacity-overcommitted', now_text,
                                        dict(deadline_slots=self.deadline_slots, reservations_at_peak=peak),
                                        last_error='this watchdog has fewer deadline slots than armed sessions were promised')
        elif peak <= self.deadline_slots and incident is not None:
            self.registry.resolve_incident(incident['incident_id'], now_text)

    # ---- startup -----------------------------------------------------------------------------

    def recover(self, pid):
        """Registry recovery at service start: finish orphaned attempts; keep every burst and deadline."""
        with self.registry.txn('wd_recover') as effective:
            now_text = session_clock.iso(effective)
            orphaned = self.db.execute('SELECT attempt_id, session_id, resource_key FROM attempts WHERE finished_at IS NULL').fetchall()
            for row in orphaned:
                self.db.execute("UPDATE attempts SET finished_at=?, result='interrupted', "
                                "message='watchdog restarted with this request outstanding' WHERE attempt_id=?",
                                (now_text, row['attempt_id']))
                self.db.execute('UPDATE resources SET in_flight_attempt=NULL, burst_next_at=? WHERE session_id=? AND resource_key=?',
                                (now_text, row['session_id'], row['resource_key']))
            self.db.execute("UPDATE resources SET burst_state='exhausted' WHERE burst_state='active' AND burst_attempts>=?",
                            (MAX_ATTEMPTS_PER_BURST,))
            self.db.execute('UPDATE watchdog_status SET identity=?, pid=?, boot_id=?, started_at=?, last_tick_at=? WHERE id=1',
                            (self.identity, pid, self.registry.clock.boot_id(), now_text, now_text))
            self._publish_capacity()
            self._check_admitted_capacity(effective, now_text)
            self.registry.event(now_text, None, 'watchdog_started', dict(identity=self.identity, pid=pid,
                                                                         orphaned_attempts=len(orphaned)))
            return effective

    # ---- deadline evaluation, on every tick and independent of the provider ------------------

    def tick(self, new_sweep=False):
        """Heartbeat, acknowledgements, C/D evaluation, burst scheduling and closure, atomically."""
        with self.registry.txn('wd_tick') as effective:
            now_text = session_clock.iso(effective)
            self.db.execute('UPDATE watchdog_status SET last_tick_at=? WHERE id=1', (now_text,))
            if new_sweep:
                self.db.execute('UPDATE watchdog_status SET sweep_seq=sweep_seq+1, last_sweep_at=? WHERE id=1', (now_text,))
            sweep = self.db.execute('SELECT sweep_seq FROM watchdog_status WHERE id=1').fetchone()['sweep_seq']
            sessions = self.db.execute("SELECT * FROM sessions WHERE state != ? ORDER BY session_id",
                                       (registry_mod.CLOSED,)).fetchall()
            for session in sessions:
                self._acknowledge(session, now_text)
                if session['t0_utc'] is None:
                    continue
                session = self._evaluate_deadlines(session, effective, now_text)
                if session['state'] == registry_mod.DELETING:
                    self._track_unresolved_creates(session, now_text)
                    self._start_bursts(session, effective, now_text, sweep)
                    self._try_close(session, effective, now_text)
                else:
                    self._start_preparation(session, effective, now_text, sweep)
            return effective

    def _acknowledge(self, session, now_text):
        if session['watchdog_identity'] != self.identity:
            return
        session_id = session['session_id']
        if session['watchdog_ack_at'] is None:
            self.db.execute('UPDATE sessions SET watchdog_ack_at=? WHERE session_id=?', (now_text, session_id))
            self.registry.event(now_text, session_id, 'watchdog_acknowledged', dict(manifest_sha256=session['manifest_sha256']))
        if session['t0_utc'] is not None and session['watchdog_armed_ack_at'] is None:
            self.db.execute('UPDATE sessions SET watchdog_armed_ack_at=? WHERE session_id=?', (now_text, session_id))
            self.registry.event(now_text, session_id, 'watchdog_armed_acknowledged',
                                dict(t0_utc=session['t0_utc'], cleanup_c_utc=session['cleanup_c_utc'],
                                     deadline_d_utc=session['deadline_d_utc']))

    def _evaluate_deadlines(self, session, effective, now_text):
        session_id = session['session_id']
        cleanup_at = session_clock.parse(session['cleanup_c_utc'])
        if session['cleanup_requested_at'] is None:
            reason = None
            delete_at = cleanup_at - self.delete_margin_s
            if session['recovery_deadline_utc'] is not None:
                # Scheduling margin must not shorten an accepted recovery episode.
                delete_at = max(delete_at, session_clock.parse(session['recovery_deadline_utc']))
            if effective >= delete_at:
                reason = 'deadline_C'
            elif (session['recovery_deadline_utc'] is not None
                  and effective >= session_clock.parse(session['recovery_deadline_utc'])):
                # A started episode ends on time in any substate: reconnecting cannot extend it.
                reason = 'evidence_recovery_expired'
            if reason is not None:
                self.registry.begin_cleanup_row(session, now_text, reason, 'watchdog:' + self.identity)
                session = self.registry.session_row(session_id)
        if effective >= session_clock.parse(session['deadline_d_utc']) and session['state'] != registry_mod.CLOSED:
            if self.registry.open_incident_of(session_id, 'cleanup-overdue') is None:
                last = self.db.execute("SELECT error_class, message FROM attempts WHERE session_id=? AND result='error' "
                                       'ORDER BY attempt_id DESC LIMIT 1', (session_id,)).fetchone()
                self.registry.open_incident(session_id, 'cleanup-overdue', now_text,
                                            dict(deadline_d_utc=session['deadline_d_utc'], t0_utc=session['t0_utc'],
                                                 cleanup_c_utc=session['cleanup_c_utc']),
                                            last_error=(last['error_class'] + ': ' + last['message'] if last
                                                        else 'owned resources are not verified absent at D'))
        return session

    # ---- burst scheduling --------------------------------------------------------------------

    def _rows(self, session_id):
        return self.db.execute('SELECT * FROM resources WHERE session_id=?', (session_id,)).fetchall()

    def _pending_creates(self, session_id):
        return [i for i in self.registry.intents(session_id) if i['state'] in PENDING_CREATE]

    def _track_unresolved_creates(self, session, now_text):
        """Keep asking about each unresolved request and keep it visible. Time never resolves one."""
        session_id = session['session_id']
        pending = self._pending_creates(session_id)
        current = {create_evidence.request_ref(i['intent_id'], i['request_count']): i for i in pending}
        known = set()
        for row in self._rows(session_id):
            if row['kind'] != CREATE_REQUEST_KIND:
                continue
            known.add(row['provider_id'])
            if row['provider_id'] not in current and row['status'] not in TERMINAL:
                self.db.execute("UPDATE resources SET status='settled', burst_state='done', burst_next_at=NULL "
                                'WHERE session_id=? AND resource_key=?', (session_id, row['resource_key']))
        for ref, intent in current.items():
            if ref not in known:
                self.registry.insert_bookkeeping_row(session_id, CREATE_REQUEST_KIND, ref, intent['intent_id'], now_text)
        incident = self.registry.open_incident_of(session_id, registry_mod.UNRESOLVED_CREATE_INCIDENT)
        if pending and incident is None:
            self.registry.open_incident(session_id, registry_mod.UNRESOLVED_CREATE_INCIDENT, now_text,
                                        dict(create_request_refs=sorted(current)),
                                        last_error='a create outcome is unknown: closure and protection removal wait for evidence')
        elif not pending and incident is not None:
            self.registry.resolve_incident(incident['incident_id'], now_text)

    def _resolve_tag_intent(self, session_id, row, now_text):
        """A tag seen by name answers its own outstanding request. A 404 answers nothing: it can still land."""
        intent = next((i for i in self._pending_creates(session_id)
                       if i['kind'] == 'tag' and i['expected_name'] == row['provider_id']), None)
        if intent is not None:
            self.db.execute("UPDATE intents SET state='created', resource_key=?, resolved_at=? WHERE session_id=? AND intent_id=?",
                            (row['resource_key'], now_text, session_id, intent['intent_id']))

    def _blocked(self, row, rows, pending):
        """Droplets first, then firewalls, then tags; each only once what they protect is gone."""
        if row['kind'] in ('droplet',) + BOOKKEEPING_KINDS:
            return False
        if pending:
            # Reading a tag with its own request outstanding can only settle it. Deleting waits (_apply_read).
            return not (row['kind'] == 'tag' and any(i['kind'] == 'tag' and i['expected_name'] == row['provider_id'] for i in pending))
        by_kind = {}
        for other in rows:
            by_kind.setdefault(other['kind'], []).append(other)

        def layer_clear(kind, listing):
            listing_row = by_kind[listing][0]
            return (all(r['status'] in TERMINAL for r in by_kind.get(kind, []))
                    and listing_row['consecutive_empty'] >= 1)

        if row['kind'] == 'firewall':
            return not layer_clear('droplet', 'inventory_droplet')
        return not (layer_clear('droplet', 'inventory_droplet') and layer_clear('firewall', 'inventory_firewall'))

    def _ownership_fresh(self, row, effective):
        verified = row['ownership_verified_at']
        return verified is not None and effective - session_clock.parse(verified) <= self.ownership_fresh_s

    def _first_delete_ready(self, row, effective):
        """A Droplet preparation already verified goes straight to its first delete, without waiting for a sweep."""
        return (row['kind'] == 'droplet' and row['status'] == 'unverified' and self._ownership_fresh(row, effective)
                and self.db.execute("SELECT 1 FROM attempts WHERE session_id=? AND resource_key=? AND op='delete_droplet' LIMIT 1",
                                    (row['session_id'], row['resource_key'])).fetchone() is None)

    def _start_preparation(self, session, effective, now_text, sweep):
        """Read known Droplets before C. This only records ownership; it deletes nothing and changes no state."""
        if effective < session_clock.parse(session['cleanup_c_utc']) - self.prepare_lead_s:
            return
        for row in self._rows(session['session_id']):
            if (row['kind'] != 'droplet' or row['status'] in TERMINAL or row['burst_state'] == 'active'
                    or row['burst_sweep'] == sweep or self._ownership_fresh(row, effective)):
                continue
            if (row['burst_started_at'] is not None
                    and effective - session_clock.parse(row['burst_started_at']) < self.sweep_interval_s):
                continue
            self.db.execute("UPDATE resources SET burst_state='active', burst_sweep=?, burst_started_at=?, burst_attempts=0, "
                            'burst_next_at=?, burst_next_op=? WHERE session_id=? AND resource_key=?',
                            (sweep, now_text, now_text, READ_OPS['droplet'], session['session_id'], row['resource_key']))

    def _start_bursts(self, session, effective, now_text, sweep):
        rows = self._rows(session['session_id'])
        pending = self._pending_creates(session['session_id'])
        all_gone = not pending and all(r['status'] in TERMINAL for r in rows if r['kind'] not in BOOKKEEPING_KINDS)
        floor = self._closure_floor(session, rows)
        for row in rows:
            if row['status'] in TERMINAL or row['burst_state'] == 'active':
                continue
            # A listing that already proves closure must not start again: with slow requests two listings could
            # otherwise overlap forever, and closure needs both idle at once.
            if all_gone and row['kind'] in LISTING_KINDS and self._listing_proves(row, floor):
                continue
            ready = self._first_delete_ready(row, effective)
            if row['burst_sweep'] == sweep and not ready:
                continue
            if self._blocked(row, rows, pending):
                continue
            # A restart begins a sweep immediately. This keeps a crash loop from buying extra bursts.
            if (not ready and row['burst_started_at'] is not None
                    and effective - session_clock.parse(row['burst_started_at']) < self.sweep_interval_s):
                continue
            # Preparation and its first delete can share one sweep, and share its six attempts.
            attempts = row['burst_attempts'] if row['burst_sweep'] == sweep else 0
            if attempts >= MAX_ATTEMPTS_PER_BURST:
                continue
            first_op = DELETE_OPS['droplet'] if ready else self._first_op(row)
            self.db.execute("UPDATE resources SET burst_state='active', burst_sweep=?, burst_started_at=?, burst_attempts=?, "
                            'burst_next_at=?, burst_next_op=? WHERE session_id=? AND resource_key=?',
                            (sweep, now_text, attempts, now_text, first_op, session['session_id'], row['resource_key']))

    @staticmethod
    def _first_op(row):
        if row['kind'] == CREATE_REQUEST_KIND:
            return SETTLEMENT_OP
        return LIST_OPS.get(row['kind']) or READ_OPS[row['kind']]

    def due_work(self, effective):
        """Requests that may start now, grouped by session, most billable first."""
        rows = self.db.execute("SELECT r.* FROM resources r JOIN sessions s ON s.session_id = r.session_id "
                               "WHERE s.state != ? AND r.burst_state = 'active' AND r.in_flight_attempt IS NULL",
                               (registry_mod.CLOSED,)).fetchall()
        # Schedules are stored as microsecond text, and rounding can put one just after the instant it was stamped from.
        effective = session_clock.parse(session_clock.iso(effective))
        grouped = {}
        for row in rows:
            if session_clock.parse(row['burst_next_at']) <= effective:
                grouped.setdefault(row['session_id'], []).append(row)
        for work in grouped.values():
            # A due Droplet delete first, then whatever waited longest: repeating listings cannot starve the rest.
            work.sort(key=lambda r: (r['burst_next_op'] != DELETE_OPS['droplet'], r['last_attempt_at'] or '',
                                     KIND_PRIORITY[r['kind']], r['resource_key']))
        return grouped

    def deadline_chains(self, due, effective):
        """The one Droplet request each session needs next for a first delete by C, earliest C first.

        A session gets one chain request at a time and only inside ``[C - lead, C]``, which is what its
        reserved slot covers, so a hung session can never hold more and a late one gets no permanent priority.
        """
        chains = []
        for session_id, work in due.items():
            droplets = [row for row in work if row['kind'] == 'droplet']
            if not droplets:
                continue
            session = self.registry.session_row(session_id)
            cleanup_at = session_clock.parse(session['cleanup_c_utc'])
            if not cleanup_at - self.prepare_lead_s <= effective <= cleanup_at:
                continue
            if self.db.execute("SELECT 1 FROM attempts WHERE session_id=? AND op='delete_droplet' LIMIT 1", (session_id,)).fetchone():
                continue
            if self.db.execute('SELECT 1 FROM attempts WHERE session_id=? AND deadline_chain=1 AND finished_at IS NULL LIMIT 1',
                               (session_id,)).fetchone():
                continue
            if session['cleanup_requested_at'] is None and any(self._ownership_fresh(r, effective) for r in self._rows(session_id)):
                continue    # prepared: its next chain request is the delete at C
            row = next((r for r in droplets if r['burst_next_op'] == DELETE_OPS['droplet']), droplets[0])
            chains.append((cleanup_at, session_id, row))
        return [(session_id, row) for _, session_id, row in sorted(chains, key=lambda chain: chain[:2])]

    def in_flight_counts(self):
        rows = self.db.execute('SELECT session_id, COUNT(*) AS n FROM resources WHERE in_flight_attempt IS NOT NULL GROUP BY session_id')
        return {row['session_id']: row['n'] for row in rows}

    def in_flight_classes(self):
        """(deadline chain requests, ordinary requests) now outstanding."""
        row = self.db.execute('SELECT COALESCE(SUM(a.deadline_chain), 0) AS chain, COUNT(*) AS total FROM resources r '
                              'JOIN attempts a ON a.attempt_id = r.in_flight_attempt').fetchone()
        return row['chain'], row['total'] - row['chain']

    def next_boundary_after(self, effective):
        """The next instant a session deadline needs a tick, so a tick lands on it rather than up to a tick after."""
        boundaries = []
        for row in self.db.execute('SELECT cleanup_c_utc, deadline_d_utc, recovery_deadline_utc FROM sessions '
                                   'WHERE t0_utc IS NOT NULL AND state != ?', (registry_mod.CLOSED,)):
            cleanup_at = session_clock.parse(row['cleanup_c_utc'])
            boundaries += [cleanup_at - self.prepare_lead_s, cleanup_at - self.delete_margin_s, session_clock.parse(row['deadline_d_utc'])]
            if row['recovery_deadline_utc'] is not None:
                boundaries.append(session_clock.parse(row['recovery_deadline_utc']))
        return min((b for b in boundaries if b > effective), default=None)

    def rate_limit_hold(self):
        return self.db.execute('SELECT rate_limit_hold_until FROM watchdog_status WHERE id=1').fetchone()['rate_limit_hold_until']

    def start_attempt(self, session_id, resource_key, deadline_chain=False):
        """Persist the attempt BEFORE its side effect. Returns (attempt_id, op, target) or None.

        A destructive request needs durable cleanup intent, so preparation can never issue one.
        """
        with self.registry.txn('wd_start_attempt') as effective:
            now_text = session_clock.iso(effective)
            row = self.db.execute('SELECT * FROM resources WHERE session_id=? AND resource_key=?',
                                  (session_id, resource_key)).fetchone()
            session = self.registry.session_row(session_id)
            if (row['burst_state'] != 'active' or row['in_flight_attempt'] is not None
                    or session['state'] == registry_mod.CLOSED):
                return None
            if row['burst_next_op'] in DELETE_OPS.values() and session['cleanup_requested_at'] is None:
                raise AssertionError('a delete was scheduled without durable cleanup intent: ' + resource_key)
            attempt_number = row['burst_attempts'] + 1
            if attempt_number > MAX_ATTEMPTS_PER_BURST:
                raise AssertionError('burst attempt ceiling violated for ' + resource_key)
            cursor = self.db.execute('INSERT INTO attempts(session_id, resource_key, sweep_seq, burst_attempt, op, started_at, deadline_chain) '
                                     'VALUES (?, ?, ?, ?, ?, ?, ?)',
                                     (session_id, resource_key, row['burst_sweep'], attempt_number, row['burst_next_op'], now_text,
                                      1 if deadline_chain else 0))
            self.db.execute('UPDATE resources SET burst_attempts=?, attempt_total=attempt_total+1, last_attempt_at=?, '
                            'in_flight_attempt=? WHERE session_id=? AND resource_key=?',
                            (attempt_number, now_text, cursor.lastrowid, session_id, resource_key))
            target = row['name'] if row['kind'] in LISTING_KINDS else row['provider_id']
            return cursor.lastrowid, row['burst_next_op'], target

    def expire_overdue_requests(self, request_deadline_s):
        """A request past its bound counts as failed, so a stuck call cannot hold a resource forever."""
        expired = []
        effective = self.registry.peek_now()
        for row in self.db.execute('SELECT attempt_id, started_at FROM attempts WHERE finished_at IS NULL').fetchall():
            if effective - session_clock.parse(row['started_at']) >= request_deadline_s:
                expired.append(row['attempt_id'])
        for attempt_id in expired:
            self.finish_attempt(attempt_id, error=cleanup_provider.ProviderTransient('request exceeded its deadline'))
        return expired

    # ---- applying results --------------------------------------------------------------------

    def finish_attempt(self, attempt_id, value=None, error=None):
        """Apply one provider result. A late result for a finished attempt is ignored."""
        with self.registry.txn('wd_finish_attempt') as effective:
            now_text = session_clock.iso(effective)
            attempt = self.db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if attempt is None or attempt['finished_at'] is not None:
                return False
            session_id, key = attempt['session_id'], attempt['resource_key']
            row = self.db.execute('SELECT * FROM resources WHERE session_id=? AND resource_key=?', (session_id, key)).fetchone()
            self.db.execute('UPDATE resources SET in_flight_attempt=NULL WHERE session_id=? AND resource_key=?', (session_id, key))
            if error is not None:
                self._apply_error(attempt, row, error, effective, now_text)
            else:
                self.db.execute("UPDATE attempts SET finished_at=?, result='ok' WHERE attempt_id=?", (now_text, attempt_id))
                self._resolve_auth_incident(session_id, now_text)
                self._apply_success(attempt, row, value, effective, now_text)
            return True

    def _apply_error(self, attempt, row, error, effective, now_text):
        session_id, key = attempt['session_id'], attempt['resource_key']
        message = cleanup_provider.redact(str(error))
        error_class = type(error).__name__
        status = getattr(error, 'status', None)
        retry_after = getattr(error, 'retry_after_s', None)
        self.db.execute('UPDATE attempts SET finished_at=?, result=?, http_status=?, error_class=?, message=?, retry_after_s=? '
                        'WHERE attempt_id=?', (now_text, 'error', status, error_class, message, retry_after, attempt['attempt_id']))
        self.db.execute('UPDATE resources SET last_error=? WHERE session_id=? AND resource_key=?',
                        (error_class + ': ' + message, session_id, key))
        self._bump_overdue(session_id, error_class + ': ' + message)
        if isinstance(error, cleanup_provider.ProviderAuthError):
            self.db.execute("UPDATE resources SET burst_state='fatal', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (session_id, key))
            incident = self.registry.open_incident_of(session_id, 'provider-auth')
            if incident is None:
                self.registry.open_incident(session_id, 'provider-auth', now_text, dict(first_resource=key), last_error=message)
            else:
                self.db.execute('UPDATE incidents SET last_error=?, version=version+1 WHERE incident_id=?', (message, incident['incident_id']))
            return
        delay = backoff_s(attempt['burst_attempt'])
        if isinstance(error, cleanup_provider.ProviderRateLimited):
            hold = min(retry_after if retry_after is not None else DEFAULT_RATE_LIMIT_HOLD_S, MAX_RATE_LIMIT_HOLD_S)
            delay = max(delay, hold)
            hold_until = effective + hold
            current = self.rate_limit_hold()
            if current is None or session_clock.parse(current) < hold_until:
                self.db.execute('UPDATE watchdog_status SET rate_limit_hold_until=?, rate_limit_detail=? WHERE id=1',
                                (session_clock.iso(hold_until), message))
                self.registry.event(now_text, session_id, 'rate_limit_hold', dict(until=session_clock.iso(hold_until), status=status))
        if attempt['burst_attempt'] >= MAX_ATTEMPTS_PER_BURST:
            self.db.execute("UPDATE resources SET burst_state='exhausted', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (session_id, key))
            return
        self.db.execute('UPDATE resources SET burst_next_at=? WHERE session_id=? AND resource_key=?',
                        (session_clock.iso(effective + delay), session_id, key))

    def _apply_success(self, attempt, row, value, effective, now_text):
        op = attempt['op']
        if op == SETTLEMENT_OP:
            self._apply_settlement(attempt, row, value, now_text)
        elif op in LIST_OPS.values():
            self._apply_listing(attempt, row, value or [], now_text)    # only a successful listing is ever fresh
        elif op in READ_OPS.values():
            self._apply_read(attempt, row, value, effective, now_text)
        else:
            self.db.execute("UPDATE resources SET status='delete_accepted', delete_accepted_at=?, delete_accept_count=delete_accept_count+1, "
                            "burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (now_text, attempt['session_id'], attempt['resource_key']))
            self.registry.event(now_text, attempt['session_id'], 'delete_accepted',
                                dict(resource_key=attempt['resource_key'], note='accepted is not proof of destruction'))

    def _apply_settlement(self, attempt, row, value, now_text):
        """Only a typed receipt for the current request counts. No receipt leaves the request unresolved."""
        session_id, key = attempt['session_id'], attempt['resource_key']
        self.db.execute("UPDATE resources SET burst_state='done', burst_next_at=NULL, last_error=NULL WHERE session_id=? AND resource_key=?",
                        (session_id, key))
        intent = next((i for i in self._pending_creates(session_id) if i['intent_id'] == row['intent_id']), None)
        if value is None or intent is None:
            return
        try:
            self.registry.apply_settlement(self.registry.session_row(session_id), intent, value, now_text, 'watchdog')
        except create_evidence.EvidenceRefused as refused:
            self.db.execute('UPDATE resources SET last_error=? WHERE session_id=? AND resource_key=?', (refused.code, session_id, key))
            if self.registry.open_incident_of(session_id, 'create-evidence-refused') is None:
                self.registry.open_incident(session_id, 'create-evidence-refused', now_text,
                                            dict(request=row['provider_id'], code=refused.code), last_error=refused.message)

    def _apply_listing(self, attempt, row, items, now_text):
        session_id = attempt['session_id']
        kind = 'droplet' if row['kind'] == 'inventory_droplet' else 'firewall'
        intents = {i['expected_name']: i for i in self.registry.intents(session_id) if i['kind'] == kind}
        for item in items:
            key = kind + ':' + str(item['id'])
            known = self.db.execute('SELECT * FROM resources WHERE session_id=? AND resource_key=?', (session_id, key)).fetchone()
            intent = intents.get(item.get('name'))
            if known is None:
                self.registry.record_resource_row(session_id, kind, item['id'], intent['intent_id'] if intent else None,
                                                  item.get('name'), 'discovered', now_text)
                continue
            if known['status'] == 'absent':
                # Inventory outranks an earlier 404: never call something gone while it is still listed.
                self.db.execute("UPDATE resources SET status='unverified', verified_absent_at=NULL WHERE session_id=? AND resource_key=?",
                                (session_id, key))
                self.registry.event(now_text, session_id, 'absence_reversed', dict(resource_key=key))
                self.registry.revalidate_tags(session_id, now_text, key)
            if intent is not None and intent['state'] in PENDING_CREATE:
                # An id reported without its intent still answers that intent, or it would never settle.
                self.db.execute("UPDATE intents SET state='created', resource_key=?, resolved_at=? WHERE session_id=? AND intent_id=?",
                                (key, now_text, session_id, intent['intent_id']))
        disowned = {r['provider_id'] for r in self._rows(session_id) if r['status'] == 'disowned'}
        remaining = [item for item in items if str(item['id']) not in disowned]
        empty = row['consecutive_empty'] + 1 if not remaining else 0
        self.db.execute("UPDATE resources SET listing_started_at=?, listing_finished_at=?, consecutive_empty=?, burst_state='done', "
                        'burst_next_at=NULL, last_error=NULL WHERE session_id=? AND resource_key=?',
                        (attempt['started_at'], now_text, empty, session_id, row['resource_key']))

    def _ownership_problems(self, session_id, row, value):
        manifest = self.registry.manifest(session_id)
        tags = manifest['session']['ownership_tags']
        problems = []
        if row['resource_key'] in (manifest['session'].get('retained_resources') or []):
            problems.append('resource is listed as retained by the manifest')
        if row['kind'] == 'droplet':
            names = {i['expected_name']: i for i in self.registry.intents(session_id) if i['kind'] == 'droplet'}
            actual_tags = set(value.get('tags') or [])
            if tags['session'] not in actual_tags:
                problems.append('droplet does not carry the unique session tag')
            protected = actual_tags.intersection(self.registry.protected_tags)
            if protected:
                problems.append('droplet carries a protected management tag: ' + ', '.join(sorted(protected)))
            intent = names.get(value.get('name'))
            if intent is None:
                problems.append('droplet name is not an expected session name')
            elif tags[intent['role']] not in actual_tags:
                problems.append('droplet does not carry its role tag')
        elif row['kind'] == 'firewall':
            if value.get('name') != session_id + '-fw':
                problems.append('firewall name is not the expected session name')
            if not set(value.get('tags') or []).issubset({tags['session'], tags['game'], tags['bot']}):
                problems.append('firewall targets tags outside this session')
            owned = {r['provider_id'] for r in self._rows(session_id) if r['kind'] == 'droplet'}
            if not {str(d) for d in (value.get('droplet_ids') or [])}.issubset(owned):
                problems.append('firewall targets Droplets this session does not own')
        elif row['kind'] == 'tag':
            if value.get('name') != row['provider_id'] or row['provider_id'] not in tags.values():
                problems.append('tag is not an ownership tag of this session')
            if value.get('resource_count'):
                problems.append('tag still labels %s resource(s) after owned Droplets are gone' % value.get('resource_count'))
        return problems

    def _apply_read(self, attempt, row, value, effective, now_text):
        session_id, key = attempt['session_id'], attempt['resource_key']
        pending = self._pending_creates(session_id)     # as of this read: settling its own request releases nothing yet
        if row['kind'] == 'tag' and value is not None:
            self._resolve_tag_intent(session_id, row, now_text)
        if value is None:
            if row['kind'] == 'tag' and any(i['kind'] == 'tag' and i['expected_name'] == row['provider_id'] for i in pending):
                # Its own create can still land, so this 404 is no verification. Later sweeps read it again.
                self.db.execute("UPDATE resources SET burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                                (session_id, key))
                return
            if (row['revalidate_after'] is not None
                    and session_clock.parse(attempt['started_at']) <= session_clock.parse(row['revalidate_after'])):
                # This read began before a late resource appeared, so its 404 is out of date.
                self.db.execute("UPDATE resources SET burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                                (session_id, key))
                return
            self.db.execute("UPDATE resources SET status='absent', verified_absent_at=?, burst_state='done', burst_next_at=NULL, "
                            'last_error=NULL WHERE session_id=? AND resource_key=?', (now_text, session_id, key))
            self.registry.event(now_text, session_id, 'verified_absent', dict(resource_key=key))
            self._resolve_ownership_incident(session_id, key, now_text)
            return
        if row['kind'] != 'droplet' and pending:
            # Protection stays while any create is unresolved, whatever this read found.
            self.db.execute("UPDATE resources SET burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (session_id, key))
            return
        problems = self._ownership_problems(session_id, row, value)
        if problems:
            self.db.execute("UPDATE resources SET status='ownership_refused', ownership_detail=?, ownership_verified_at=NULL, "
                            "burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (registry_mod.canonical(problems), session_id, key))
            if row['status'] != 'ownership_refused':
                self.registry.open_incident(session_id, 'ownership-mismatch', now_text,
                                            dict(resource_key=key, problems=problems, observed_name=value.get('name')),
                                            last_error='; '.join(problems))
            return
        self._resolve_ownership_incident(session_id, key, now_text)
        status = 'unverified' if row['status'] == 'ownership_refused' else row['status']
        self.db.execute('UPDATE resources SET ownership_verified_at=? WHERE session_id=? AND resource_key=?',
                        (attempt['started_at'], session_id, key))
        if self.registry.session_row(session_id)['cleanup_requested_at'] is None:
            # Preparation only records what it saw. The delete belongs to the deadline tick.
            self.db.execute("UPDATE resources SET status=?, burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (status, session_id, key))
            return
        recently_accepted = (row['delete_accepted_at'] is not None
                             and effective - session_clock.parse(row['delete_accepted_at']) < self.redelete_after_s)
        if recently_accepted:
            self.db.execute("UPDATE resources SET status=?, burst_state='done', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (status, session_id, key))
            return
        if row['burst_attempts'] >= MAX_ATTEMPTS_PER_BURST:
            self.db.execute("UPDATE resources SET status=?, burst_state='exhausted', burst_next_at=NULL WHERE session_id=? AND resource_key=?",
                            (status, session_id, key))
            return
        self.db.execute("UPDATE resources SET status=?, burst_next_op=?, burst_next_at=? WHERE session_id=? AND resource_key=?",
                        (status, DELETE_OPS[row['kind']], now_text, session_id, key))

    def _resolve_ownership_incident(self, session_id, key, now_text):
        rows = self.db.execute("SELECT incident_id, detail_json FROM incidents WHERE session_id=? AND kind='ownership-mismatch' AND status='open'",
                               (session_id,)).fetchall()
        for row in rows:
            if json.loads(row['detail_json']).get('resource_key') == key:
                self.registry.resolve_incident(row['incident_id'], now_text)

    def _resolve_auth_incident(self, session_id, now_text):
        incident = self.registry.open_incident_of(session_id, 'provider-auth')
        if incident is not None:
            self.registry.resolve_incident(incident['incident_id'], now_text)

    def _bump_overdue(self, session_id, message):
        self.db.execute("UPDATE incidents SET last_error=?, version=version+1 WHERE session_id=? AND kind='cleanup-overdue' AND status='open'",
                        (message, session_id))

    # ---- closure -----------------------------------------------------------------------------

    def _closure_floor(self, session, rows):
        """The empty listing closure needs must start after every verification and every settled request."""
        verified = [session_clock.parse(r['verified_absent_at']) for r in rows
                    if r['kind'] not in BOOKKEEPING_KINDS and r['verified_absent_at']]
        verified += [session_clock.parse(i['resolved_at']) for i in self.registry.intents(session['session_id']) if i['resolved_at']]
        return max(verified + [session_clock.parse(session['cleanup_requested_at'])])

    @staticmethod
    def _listing_proves(listing, floor):
        return (listing['listing_finished_at'] is not None and listing['consecutive_empty'] >= 1
                and session_clock.parse(listing['listing_started_at']) >= floor)

    def _try_close(self, session, effective, now_text):
        """Close only after verified absence, a fresh empty inventory and settled create requests."""
        session_id = session['session_id']
        rows = self._rows(session_id)
        real = [r for r in rows if r['kind'] not in BOOKKEEPING_KINDS]
        listings = [r for r in rows if r['kind'] in LISTING_KINDS]
        if any(r['status'] not in TERMINAL or r['in_flight_attempt'] is not None for r in real):
            return
        if self._pending_creates(session_id):
            return
        floor = self._closure_floor(session, rows)
        for listing in listings:
            if listing['in_flight_attempt'] is not None or not self._listing_proves(listing, floor):
                return
        disowned = [r['resource_key'] for r in real if r['status'] == 'disowned']
        disowned += [i['intent_id'] for i in self.registry.intents(session_id) if i['state'] == 'operator_disposed']
        outcome = registry_mod.VERIFIED_WITH_DISPOSITION if disowned else registry_mod.VERIFIED_ABSENT
        overrun = max(0.0, effective - session_clock.parse(session['deadline_d_utc']))
        self.db.execute('UPDATE sessions SET state=?, cleanup_outcome=?, cleanup_verified_at=?, overrun_s=?, closure_count=closure_count+1 '
                        'WHERE session_id=?', (registry_mod.CLOSED, outcome, now_text, overrun, session_id))
        overdue = self.registry.open_incident_of(session_id, 'cleanup-overdue')
        if overdue is not None:
            self.registry.resolve_incident(overdue['incident_id'], now_text, overrun_s=overrun)
        late = self.registry.open_incident_of(session_id, 'late-resource-after-close')
        if late is not None:
            self.registry.resolve_incident(late['incident_id'], now_text)
        self.registry.event(now_text, session_id, 'closed', dict(cleanup_outcome=outcome, overrun_s=overrun, disowned=disowned))

    # ---- rendered artifacts ------------------------------------------------------------------

    def render_receipt(self, session_id):
        session = self.registry.session_row(session_id)
        resources = [r for r in self.registry.resources(session_id) if r['kind'] not in BOOKKEEPING_KINDS]
        return dict(
            session_id=session_id, manifest_sha256=session['manifest_sha256'], closure=session['closure_count'],
            t0_utc=session['t0_utc'], cleanup_c_utc=session['cleanup_c_utc'], deadline_d_utc=session['deadline_d_utc'],
            cleanup_reason=session['cleanup_reason'], cleanup_actor=session['cleanup_actor'],
            cleanup_requested_at=session['cleanup_requested_at'], cleanup_outcome=session['cleanup_outcome'],
            verified_at=session['cleanup_verified_at'], overrun_s=session['overrun_s'],
            deadline_uncertain=session['clock_uncertain_at'] is not None,
            overrun_is_lower_bound=session['clock_uncertain_at'] is not None,
            dispositions=[dict(resource_key=r['resource_key'], provider_id=r['provider_id'], name=r['name'], source=r['source'],
                               status=r['status'], verified_absent_at=r['verified_absent_at'], attempts=r['attempt_total'],
                               delete_accept_count=r['delete_accept_count']) for r in resources],
            intents=[self.registry.intent_view(i) for i in self.registry.intents(session_id)],
            incidents=[dict(incident_id=i['incident_id'], kind=i['kind'], status=i['status'], overrun_s=i['overrun_s'])
                       for i in self.registry.incidents(session_id)])

    def closed_sessions(self):
        return self.db.execute('SELECT session_id, closure_count FROM sessions WHERE state=? AND closure_count>0',
                               (registry_mod.CLOSED,)).fetchall()
