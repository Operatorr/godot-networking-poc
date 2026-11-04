"""The independent cleanup watchdog: the loop half of handoff slice 2 (issue #61 §2).

It needs only the state directory and a provider seam. It never consults a controller, a lease, a
laptop or an SSH key. Each tick (1 s by default, on a monotonic wait) evaluates every session's
deadlines before any provider work, so an API outage cannot delay an overdue incident. A reconcile
sweep starts every 15 s and immediately on service start.

Provider requests run off the main thread through an executor seam, and only the main thread
touches SQLite. Round-robin dispatch with per-session and global in-flight limits means a session
whose provider calls hang or fail cannot starve another session's checks.
"""
import collections
import contextlib
import fcntl
import json
import logging
import os
import pathlib
import sqlite3
import threading

import cleanup_ledger
import registry as registry_mod
import session_clock

LOG = logging.getLogger('omega.do_watchdog')
LOCK_NAME = 'watchdog.lock'
DEFAULT_MAX_IN_FLIGHT = 8
DEFAULT_MAX_IN_FLIGHT_PER_SESSION = 2
DEFAULT_REQUEST_DEADLINE_S = 35.0
DEFAULT_TICK_INTERVAL_S = 1.0


class WatchdogAlreadyRunning(RuntimeError):
    pass


class InlineExecutor:
    """Run each provider call during dispatch; deterministic for fixtures."""

    def submit(self, call, done, session_id=None):
        done(*_invoke(call))


class ThreadExecutor:
    """One daemon thread per bounded request. A hung call costs its own thread and nothing else."""

    def submit(self, call, done, session_id=None):
        threading.Thread(target=lambda: done(*_invoke(call)), daemon=True,
                         name='omega-provider-request-' + str(session_id)).start()


def _invoke(call):
    try:
        return call(), None
    except Exception as error:  # every provider failure, including adapter bugs, is a failed attempt
        return None, error


def atomic_write(path, text):
    path = pathlib.Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Watchdog:
    def __init__(self, registry, provider, executor=None, max_in_flight=DEFAULT_MAX_IN_FLIGHT,
                 max_in_flight_per_session=DEFAULT_MAX_IN_FLIGHT_PER_SESSION,
                 request_deadline_s=DEFAULT_REQUEST_DEADLINE_S, sweep_interval_s=cleanup_ledger.SWEEP_INTERVAL_S,
                 ledger_options=None):
        self.registry = registry
        self.provider = provider
        self.identity = registry.watchdog_identity
        self.executor = executor or ThreadExecutor()
        self.ledger = cleanup_ledger.CleanupLedger(registry, self.identity, sweep_interval_s=sweep_interval_s,
                                                   **(ledger_options or {}))
        self.max_in_flight = max_in_flight
        self.max_in_flight_per_session = max_in_flight_per_session
        self.request_deadline_s = request_deadline_s
        self.sweep_interval_s = sweep_interval_s
        self._results = collections.deque()
        self._next_sweep = None
        self._rr_last = None
        self._written_incidents = {}
        self._written_receipts = set()
        self._logged_open = set()
        self._lock_fd = None
        self.storage_healthy = True

    # ---- lifecycle ---------------------------------------------------------------------------

    def acquire_lock(self):
        """One watchdog per state directory; the kernel drops the lock when the process dies."""
        fd = os.open(str(self.registry.state_dir / LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise WatchdogAlreadyRunning('another watchdog holds ' + LOCK_NAME)
        self._lock_fd = fd

    def release_lock(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def start(self, pid=None):
        """Reconcile from the persisted registry at start. Deadlines are read, never recomputed."""
        self.ledger.recover(os.getpid() if pid is None else pid)
        self._next_sweep = None

    # ---- one iteration -----------------------------------------------------------------------

    def tick(self):
        """Evaluate deadlines first. Storage faults leave work queued and hold back side effects."""
        try:
            self._drain_results()
            effective = self.registry.peek_now()
            new_sweep = self._next_sweep is None or effective >= self._next_sweep
            effective = self.ledger.tick(new_sweep=new_sweep)
            if new_sweep:
                # Keep the 15-second cadence unless the loop fell a whole interval behind.
                scheduled = (self._next_sweep or effective) + self.sweep_interval_s
                self._next_sweep = scheduled if scheduled > effective else effective + self.sweep_interval_s
            self.ledger.expire_overdue_requests(self.request_deadline_s)
            self._dispatch(effective)
            self._drain_results()
            self.storage_healthy = True
        except sqlite3.Error as error:
            # Without durable intent nothing is deleted. Stay alive and retry on the next tick.
            self.storage_healthy = False
            LOG.error('registry storage failure; holding provider side effects: %s', error)
        self._publish_artifacts()

    def run_forever(self, stop_event, tick_interval_s=DEFAULT_TICK_INTERVAL_S):
        self.acquire_lock()
        try:
            self.start()
            while not stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    # Stay supervised and visible: a stale heartbeat turns the health check unhealthy.
                    LOG.exception('watchdog tick failed; retrying')
                stop_event.wait(tick_interval_s)    # monotonic: clock changes cannot stretch this wait
        finally:
            self.release_lock()

    # ---- dispatch ----------------------------------------------------------------------------

    def _dispatch(self, effective):
        hold = self.ledger.rate_limit_hold()
        if hold is not None and effective < session_clock.parse(hold):
            return
        due = self.ledger.due_work(effective)
        if not due:
            return
        counts = self.ledger.in_flight_counts()
        capacity = self.max_in_flight - sum(counts.values())
        order = sorted(due)
        if self._rr_last is not None:
            later = [s for s in order if s > self._rr_last]
            order = later + [s for s in order if s <= self._rr_last]
        queues = {s: collections.deque(due[s]) for s in order}
        while capacity > 0 and any(queues.values()):
            progressed = False
            for session_id in order:
                if capacity <= 0 or not queues[session_id]:
                    continue
                if counts.get(session_id, 0) >= self.max_in_flight_per_session:
                    queues[session_id].clear()
                    continue
                row = queues[session_id].popleft()
                if self._start_request(session_id, row['resource_key']):
                    counts[session_id] = counts.get(session_id, 0) + 1
                    capacity -= 1
                    self._rr_last = session_id
                    progressed = True
            if not progressed:
                break

    def _start_request(self, session_id, resource_key):
        started = self.ledger.start_attempt(session_id, resource_key)
        if started is None:
            return False
        attempt_id, op, target = started
        self.registry.failpoint('wd_request:before')
        call = getattr(self.provider, op)
        self.executor.submit(lambda: call(target), lambda value, error: self._results.append((attempt_id, value, error)),
                             session_id=session_id)
        return True

    def _drain_results(self):
        while self._results:
            attempt_id, value, error = self._results[0]
            self.registry.failpoint('wd_request:after')
            self.ledger.finish_attempt(attempt_id, value=value, error=error)
            self._results.popleft()     # dropped only once the result is durable

    # ---- operator-visible artifacts ----------------------------------------------------------

    def _publish_artifacts(self):
        """Incident files are a rendering of the registry. A write failure is retried next tick."""
        try:
            rows = self.registry.db.execute('SELECT * FROM incidents').fetchall()
        except sqlite3.Error as error:
            LOG.error('cannot read incidents: %s', error)
            return
        for row in rows:
            incident_id = row['incident_id']
            if row['status'] == 'open' and incident_id not in self._logged_open:
                self._logged_open.add(incident_id)
                # systemd maps this ERROR to the management-host journal through the <3> prefix.
                LOG.error('incident %s %s session=%s: %s', incident_id, row['kind'], row['session_id'], row['last_error'])
            needs_refresh = row['status'] == 'open' and row['kind'] == 'cleanup-overdue'
            if self._written_incidents.get(incident_id) == row['version'] and not needs_refresh:
                continue
            with self._artifact_guard('incident ' + str(incident_id)):
                rendered = registry_mod.canonical(self.registry.incident_report(incident_id))
                path = self.registry.state_dir / registry_mod.INCIDENT_DIR / ('incident-%06d-%s.json' % (incident_id, row['kind']))
                if not path.exists() or path.read_text(encoding='utf-8') != rendered:
                    atomic_write(path, rendered)
                self._written_incidents[incident_id] = row['version']
        with self._artifact_guard('receipts'):
            for row in self.ledger.closed_sessions():
                key = (row['session_id'], row['closure_count'])
                if key in self._written_receipts:
                    continue
                path = self.registry.state_dir / registry_mod.RECEIPT_DIR / ('%s.closure-%d.json' % key)
                if not path.exists():
                    atomic_write(path, json.dumps(self.ledger.render_receipt(row['session_id']), indent=2, sort_keys=True) + '\n')
                self._written_receipts.add(key)

    @contextlib.contextmanager
    def _artifact_guard(self, label):
        try:
            yield
        except (OSError, sqlite3.Error) as error:
            LOG.error('cannot publish %s; the registry remains authoritative: %s', label, error)
