"""Fresh-process test runs on a ready pair, and the explicit resume of untouched work (handoff slice 4, issue #67).

    one trial
      admit legal remaining paths -> publish the selection -> preflight both hosts (a dirty host stops here, untouched)
      dispatch_run (durable intent) -> launching (last fenced check) -> game, wait for its new socket -> bot -> running
      watch, keeping the lease -> stop -> seal both hosts -> export through .partial -> execution.json -> sealed
      classification.json -> record_run_outcome -> planner journal mirror

The registry is the record of what was dispatched. A crash anywhere after ``dispatch_run`` leaves that run touched for
good: it cannot be dispatched again, and on return it is stopped, sealed and classified from what it actually left.

Workload processes stop by themselves, through the guest's supervisor, by ``launch_by + estimate`` less the time export
needs. This controller only ends them sooner. Nothing here scores a measurement: ``scorer`` is the boundary described in
``run_checks``, and no scorer ships yet, so no run can currently establish PASS or FAIL.
"""
import dataclasses
import hashlib
import json
import os
import pathlib
import tempfile

import admission
import cleanup_provider
import do_session
import guest_runner
import manifest as manifest_mod
import provisioner
import readiness
import registry
import registry_client
import run_checks
import run_plan
import search
import session_access
import session_clock
import ssh_access

ROLES = ('game', 'bot')
RUNNER_SOURCE = pathlib.Path(guest_runner.__file__)
FINISHED, STOPPED, PARTIAL, CONTROL_LOST, CLEANUP_STARTED, REFUSED = ('search_finished', 'stopped', 'partial_search', 'control_lost', 'cleanup_started', 'refused')
NOT_LAUNCHED = 'not_launched'
STALE_CODES = ('stale_fencing_token', 'lease_expired', 'control_held')
CLEANUP_CODES = ('cleanup_in_progress', 'deadline_reached', 'clock_unverifiable')
SEARCH_ENDINGS = ('confirmed', 'confirmed_search_cap_reached', 'no_passing_target', 'unconfirmed_variable', 'unconfirmed_partial')


@dataclasses.dataclass(frozen=True)
class Policy:
    """Local waits. Each one ends in a stop, and none of them moves a deadline."""
    poll_s: float = 10.0                # slow on purpose: every poll is an SSH login on the host being measured
    guest_step_timeout_s: float = 30.0
    stop_wait_s: float = 20.0
    stop_grace_s: float = 5.0
    game_start_wait_s: float = 15.0
    game_start_poll_s: float = 1.0
    guest_loss_tolerance_s: float = 45.0
    renew_every_s: float = 30.0
    transfer_timeout_s: float = 60.0
    recovery_poll_s: float = 15.0


@dataclasses.dataclass
class BatchResult:
    status: str
    search_status: str = None
    code: str = None
    detail: str = None
    runs: list = dataclasses.field(default_factory=list)


class ControlLost(Exception):
    """A newer controller, a lapsed lease or a fence refusal. This controller must stop acting, and it records nothing further."""

    def __init__(self, code, detail=''):
        super().__init__('%s: %s' % (code, detail))
        self.code = code
        self.detail = str(detail)


class CleanupStarted(Exception):
    """Cleanup or C took over. The token is still ours, so measurement facts can still be recorded."""

    def __init__(self, detail=''):
        super().__init__(str(detail))
        self.detail = str(detail)


class GuestLost(Exception):
    """A command's result is unknown. It may have happened, which is exactly why nothing is retried blindly."""


class RunAborted(Exception):
    def __init__(self, kind, reason):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


class BatchStop(Exception):
    def __init__(self, status, code, detail, search_status=None):
        super().__init__('%s: %s' % (code, detail))
        self.status = status
        self.code = code
        self.detail = str(detail)
        self.search_status = search_status


class ResumeRefused(Exception):
    def __init__(self, code, detail=''):
        super().__init__('%s: %s' % (code, detail))
        self.code = code
        self.detail = str(detail)


@dataclasses.dataclass
class RunContext:
    trial: search.Trial
    grant: dict
    launch_deadline: float
    stop_by: float
    workload_ends: float
    plans: dict = dataclasses.field(default_factory=dict)
    summaries: dict = dataclasses.field(default_factory=dict)
    sealed: dict = dataclasses.field(default_factory=dict)
    ledgers: dict = dataclasses.field(default_factory=dict)
    problems: dict = dataclasses.field(default_factory=lambda: {run_checks.INFRASTRUCTURE: [], run_checks.GENERATOR: [], run_checks.GAME: []})
    interrupted: str = None
    launched: bool = False
    exported: dict = dataclasses.field(default_factory=dict)


def publish_new(source, target):
    """Promote a verified file, refusing to overwrite anything already there. ``os.rename`` would overwrite."""
    os.link(str(source), str(target))
    os.unlink(str(source))


def sha256_path(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def state_from_records(session_id, records):
    rows = []
    for row in records:
        if row.get('trial') is None:
            raise ValueError('run %s has no trial on record' % row['run_id'])
        rows.append(search.TrialRecord(search.trial_from_dict(row['trial']), row['outcome'], row['evidence_ref']))
    rows.sort(key=lambda record: record.trial.ordinal)
    return search.SearchState(session_id, rows)


class GuestReadiness:
    """Full readiness again, by the same pure rules as first provisioning, against the state recorded at ``mark_ready``."""

    def __init__(self, executor):
        self.executor = executor

    def problems(self, report):
        executor = self.executor
        found = []
        for role in ROLES:
            observation = executor._agent(role, 'probe', '--role', role)
            image = executor.provider.image(executor.manifest['roles'][role]['image_id'])
            found += readiness.observation_problems(executor.manifest, role, observation, (image or {}).get('name'))
            found += readiness.clock_problems(role, executor._measure_clock(role))
            found += readiness.sampler_problems(role, executor._agent(role, 'sampler'))
            recorded = report['roles'][role]['observation']
            if (observation.get('clock') or {}).get('boot_id') != (recorded.get('clock') or {}).get('boot_id'):
                found.append(role + ': the host rebooted since readiness')
            if observation.get('kernel') != recorded.get('kernel'):
                found.append(role + ': the kernel changed since readiness')
            if (observation.get('packages') or {}).get('sha256') != (recorded.get('packages') or {}).get('sha256'):
                found.append(role + ': the package inventory changed since readiness')
        addresses = executor.addresses
        probe = executor._agent('bot', 'tcp_probe', '--host', addresses['game'], '--port', session_access.SSH_PORT)
        found += readiness.enforcement_problems(probe)
        started = executor._agent('game', 'smoke_game_start')
        try:
            bot = executor._agent('bot', 'smoke_bot', '--server', addresses['game'] + ':' + session_access.GAME_PORT, '--timeout-s', 60, timeout_s=90)
        finally:
            stopped = executor._agent('game', 'smoke_game_stop')
        found += readiness.smoke_problems(started, bot, stopped)
        return found


class RunExecutor:
    def __init__(self, client, guests, provider, manifest, sha, session_dir, fencing_token, sleep, monotonic, wall, scorer=None, adapter=None, policy=None,
                 failpoint=None, source_problems=None, readiness_problems=None, require_counters=True):
        self.client = client
        self.guests = guests
        self.provider = provider
        self.manifest = manifest
        self.sha = sha
        self.session_dir = pathlib.Path(session_dir)
        self.token = fencing_token
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall = wall
        self.scorer = scorer
        self.adapter = adapter or run_plan.ReleaseAdapter()
        self.policy = policy or Policy()
        self.failpoint = failpoint or (lambda name: None)
        self.source_problems = source_problems
        self.readiness_problems = readiness_problems or GuestReadiness(self).problems
        self.require_counters = require_counters
        self.session_id = manifest['session']['id']
        self.timing = {name: manifest['timing_basis'][name]['seconds'] for name in ('process_reset_s', 'recorder_finalization_s', 'per_trial_export_s')}
        self.evidence = provisioner.Evidence(self.session_dir / 'execution', wall)
        self.runner_sha256 = sha256_path(RUNNER_SOURCE)
        self.runner_path = run_plan.runner_remote_path(self.runner_sha256)
        self.next_renew = None
        self.lease_good_until = None
        self.collecting = False     # stopping and sealing whatever was left must carry on through cleanup
        self.work_cutoff = None     # local monotonic form of C less the delete margin
        self.in_recovery = False    # an evidence recovery episode has its own deadline, up to C itself
        self.addresses = None
        self.report = None
        self.prepared = False
        self.outcomes = []

    # ---- control -----------------------------------------------------------------------------

    def _note(self, kind, **data):
        """Local trail only. A failed write here must not change what happens to a workload."""
        try:
            self.evidence.event(kind, **data)
        except (OSError, provisioner.Stop):
            pass

    def _keepalive(self, force=False):
        """Called from every wait, including SSH commands in flight. Raises when control or the session is gone."""
        now = self.monotonic()
        if not force and self.next_renew is not None and now < self.next_renew:
            return
        try:
            self.client.call('renew_control', session_id=self.session_id, fencing_token=self.token)
            status = self.client.call('status', session_id=self.session_id)
        except registry_client.RegistryRejected as rejection:
            if rejection.code in STALE_CODES:
                raise ControlLost(rejection.code, rejection.message)
            raise
        except registry_client.RegistryUnavailable as error:
            if self.lease_good_until is not None and now >= self.lease_good_until:
                raise ControlLost('lease_unverifiable', error)
            self.next_renew = now + min(5.0, self.policy.renew_every_s)
            return
        self.next_renew = now + self.policy.renew_every_s
        self.lease_good_until = now + registry.DEFAULT_LEASE_TTL_S
        if not self.collecting and (status['state'] in (registry.DELETING, registry.CLOSED) or status['cleanup']['requested_at'] is not None):
            raise CleanupStarted(status['cleanup']['reason'] or status['state'])

    def _quiet_keepalive(self):
        """For stopping and sealing, which must finish even after the session has moved on."""
        try:
            self._keepalive()
        except (ControlLost, CleanupStarted):
            pass

    def _status(self):
        return self.client.call('status', session_id=self.session_id)

    def _records(self):
        return self.client.call('run_records', session_id=self.session_id)

    # ---- guests ------------------------------------------------------------------------------

    def _guest_timeout(self, seconds):
        """No guest command starts at or past the cutoff, and none is allowed to outlast it."""
        if self.work_cutoff is None or self.in_recovery:
            return seconds
        remaining = self.work_cutoff - self.monotonic()
        if remaining <= 0:
            raise GuestLost('past the controller work cutoff')
        return max(1, min(seconds, remaining))

    def _set_work_cutoff(self, status):
        asked = self.monotonic()
        now = session_clock.parse(self.client.call('health', session_id=self.session_id)['evaluated_at'])
        self.work_cutoff = asked + session_clock.parse(status['cleanup_c_utc']) - registry.DELETE_MARGIN_S - now

    def _runner(self, role, command, *arguments, timeout_s=None, on_wait=None):
        argv = ['python3', self.runner_path, command] + [str(a) for a in arguments]
        result = self.guests.run(role, argv, self._guest_timeout(timeout_s or self.policy.guest_step_timeout_s), on_wait or self._keepalive)
        if result.returncode != 0:
            raise GuestLost('%s %s exited %s: %s' % (role, command, result.returncode, cleanup_provider.redact(result.stderr)))
        try:
            document = json.loads(result.stdout)
        except ValueError:
            raise GuestLost('%s %s printed no JSON document' % (role, command))
        if not isinstance(document, dict) or document.get('schema') != guest_runner.SCHEMA:
            raise GuestLost('%s %s printed an unknown document' % (role, command))
        if manifest_mod.scan_for_secrets(document):
            raise RunAborted(run_checks.INFRASTRUCTURE, '%s %s reported a credential value' % (role, command))
        if document.get('ok') is not True and document.get('code') == 'stale_fence':
            raise ControlLost('stale_fence', '%s: %s' % (role, document.get('detail')))
        return document

    def _agent(self, role, step, *arguments, timeout_s=None):
        argv = ['python3', provisioner.AGENT_REMOTE, step] + [str(a) for a in arguments]
        result = self.guests.run(role, argv, self._guest_timeout(timeout_s or self.policy.guest_step_timeout_s), self._keepalive)
        if result.returncode != 0:
            raise GuestLost('%s %s exited %s' % (role, step, result.returncode))
        try:
            document = json.loads(result.stdout)
        except ValueError:
            raise GuestLost('%s %s printed no JSON document' % (role, step))
        if manifest_mod.scan_for_secrets(document):
            raise RunAborted(run_checks.INFRASTRUCTURE, '%s %s reported a credential value' % (role, step))
        return document

    def _measure_clock(self, role):
        before = self.wall()
        reading = self._agent(role, 'clock')
        after = self.wall()
        wall_ns = reading.get('wall_ns')
        if not isinstance(wall_ns, int):
            return None
        return dict(offset_s=wall_ns / 1e9 - (before + after) / 2, uncertainty_s=(after - before) / 2)

    # ---- the pair ----------------------------------------------------------------------------

    def _load_readiness(self):
        """The record ``mark_ready`` bound by hash. Anything else is not the readiness this session was granted."""
        ready = self.client.call('ready_record', session_id=self.session_id)
        reference = ready.get('ready_evidence_ref') or ''
        path = self.session_dir / 'provisioning' / 'readiness.json'
        try:
            digest = sha256_path(path)
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            raise ResumeRefused('readiness_record_unavailable', str(path))
        if not reference.endswith('#sha256:' + digest):
            raise ResumeRefused('readiness_record_changed', 'the retained report does not match %s' % reference)
        self.report = report
        return report

    def _recorded_pair(self, status):
        droplets, firewalls = {}, [r for r in status['resources'] if r['kind'] == 'firewall']
        for role in ROLES:
            matches = [r for r in status['resources'] if r['kind'] == 'droplet' and r['name'] == self.session_id + '-' + role]
            if len(matches) != 1:
                raise ResumeRefused('pair_changed', 'the registry does not hold exactly one %s droplet' % role)
            droplets[role] = matches[0]['provider_id']
        if len(firewalls) != 1:
            raise ResumeRefused('pair_changed', 'the registry does not hold exactly one firewall')
        return droplets, firewalls[0]['provider_id']

    def _pair_problems(self, status):
        """The same pair, as the provider says it is now: exact ids, plan, ownership, routes and firewall. Read only."""
        droplets, firewall_id = self._recorded_pair(status)
        tag = self.manifest['session']['ownership_tags']['session']
        listed = self.provider.list_droplets_by_tag(tag)
        problems, addresses = [], {}
        extras = sorted({d['id'] for d in listed} - set(droplets.values()))
        if extras:
            problems.append('droplets carry the session tag that the registry does not hold: %s' % extras)
        for role in ROLES:
            droplet = next((d for d in listed if d['id'] == droplets[role]), None)
            if droplet is None:
                problems.append('%s droplet %s is gone or lost its session tag' % (role, droplets[role]))
                continue
            conflict = provisioner.droplet_conflict(self.manifest, droplets[role], droplet)
            if conflict is not None:
                provisioner.report_conflict(self.client, self.session_id, conflict, self._note)
                problems += conflict.problems
            problems += readiness.droplet_problems(self.manifest, role, droplet)
            addresses[role] = (droplet.get('public_ipv4') or [None])[0]
            recorded = ((self.report or {}).get('roles') or {}).get(role, {}).get('host_key', {}).get('address')
            if addresses[role] != recorded:
                problems.append('%s droplet moved from %s to %s' % (role, recorded, addresses[role]))
            if self.provider.droplet_firewall_ids(droplets[role]) != [firewall_id]:
                problems.append('%s droplet is not under exactly the session firewall' % role)
        if 'bot' in addresses and addresses['bot']:
            problems += self._firewall_problems(firewall_id, addresses['bot'])
        self.addresses = addresses
        return problems

    def _firewall_problems(self, firewall_id, bot_address):
        actual = self.provider.get_firewall(firewall_id)
        if actual is None:
            return ['the session firewall is gone']
        allowlists = self.manifest['access_allowlists']
        desired = session_access.firewall_request(self.manifest, allowlists['ssh_sources'], allowlists['operator_udp_sources'], bot_address)
        conflict = provisioner.current_firewall_conflict(self.manifest, firewall_id, actual, desired)
        if conflict is not None:
            provisioner.report_conflict(self.client, self.session_id, conflict, self._note)
            return list(conflict.problems)
        problems = session_access.applied_problems(actual)
        game_rules = [r for r in actual.get('inbound_rules') or [] if r.get('protocol') == 'udp']
        sources = {address.split('/')[0] for rule in game_rules for address in (rule.get('sources') or {}).get('addresses') or []}
        if bot_address not in sources:
            problems.append('the game port no longer admits the bot address')
        return problems

    def prepare(self, status=None):
        """Once per controller: the exact pair, pins from the first contact, this runner on both hosts, and the fence raised."""
        if self.prepared:
            return
        status = status or self._status()
        for name, seconds in self.timing.items():
            if not isinstance(seconds, (int, float)):
                raise BatchStop(REFUSED, 'timing_basis_invalid', name)
        needed = self.policy.game_start_wait_s + 2 * self.policy.stop_grace_s
        if self.timing['process_reset_s'] < needed:
            raise BatchStop(REFUSED, 'timing_basis_too_small', 'process_reset_s must cover the game start wait and two stop graces: %s s' % needed)
        self._set_work_cutoff(status)
        self._load_readiness()
        problems = self._pair_problems(status)
        if problems:
            raise BatchStop(STOPPED, 'pair_changed', '; '.join(problems))
        self.guests.restore_pins(self.addresses)
        for role in ROLES:
            copied = self.guests.put(role, str(RUNNER_SOURCE), self.runner_path, self._guest_timeout(self.policy.transfer_timeout_s), self._keepalive)
            if copied.returncode != 0:
                raise GuestLost('%s runner upload failed: %s' % (role, cleanup_provider.redact(copied.stderr)))
            fenced = self._runner(role, 'fence', '--session', self.session_id, '--token', self.token)
            if fenced.get('ok') is not True:
                raise BatchStop(STOPPED, 'fence_refused', '%s: %s %s' % (role, fenced.get('code'), fenced.get('detail')))
        self.prepared = True

    # ---- planning ----------------------------------------------------------------------------

    def _search_state(self, records=None):
        return state_from_records(self.session_id, self._records() if records is None else records)

    def _admit(self, state, resume=False):
        health = self.client.call('health', session_id=self.session_id)
        status = self._status()
        result = admission.admit(self.manifest, self.sha, state, health['evaluated_at'], health, phase='pair_ready', t0=status['t0_utc'], resume_requested=resume)
        do_session.persist_admission(self.session_dir, result, 'resume' if resume else 'dispatch')
        return result

    def _journal_kinds(self):
        path = self.session_dir / do_session.JOURNAL
        selected, outcomes = set(), set()
        if path.exists():
            for line in path.read_text().splitlines():
                entry = json.loads(line) if line.strip() else {}
                if entry.get('kind') == 'selected':
                    selected.add(entry['trial']['run_id'])
                elif entry.get('kind') == 'outcome':
                    outcomes.add(entry['run_id'])
        return selected, outcomes

    def _sync_planner_journal(self, records=None):
        """The registry decides; this file is its local mirror, repaired after any crash between the two writes."""
        records = self._records() if records is None else records
        selected, outcomes = self._journal_kinds()
        for row in sorted(records, key=lambda item: item['trial']['ordinal']):
            run_id = row['run_id']
            if run_id not in selected:
                do_session.append_journal(self.session_dir, dict(kind='selected', manifest_sha256=self.sha, selected_at=row['dispatched_at'], trial=row['trial'],
                                                                 predecessor_evidence=[], admission_decision='repaired_from_registry', resume=False))
            if row['outcome'] is not None and run_id not in outcomes:
                do_session.append_journal(self.session_dir, dict(kind='outcome', manifest_sha256=self.sha, run_id=run_id, outcome=row['outcome'],
                                                                 evidence_ref=row['evidence_ref'], recorded_at=row['finished_at']))

    def _publish_selection(self, state, result):
        selected, _ = self._journal_kinds()
        if search.next_trial(state).run_id in selected:
            return      # selected by a controller that crashed before dispatching it: still untouched
        do_session.publish_selection(self.session_dir, self.sha, state, result, False)

    def _run_dir(self, run_id):
        return self.session_dir / 'runs' / run_id

    def _plan(self, trial, role, launch_not_after_wall=0.0, bound_s=0.0, stop_by_wall=0.0):
        sampler_sha256 = self.report['roles'][role]['observation']['release']['sample_host.py']
        return run_plan.role_plan(self.adapter, self.manifest, self.sha, trial, role, self.addresses, sampler_sha256, self.token, self.guests.UNIT_MODE,
                                  launch_not_after_wall, bound_s, stop_by_wall, self.policy.stop_grace_s)

    def _expected_boot(self, role):
        return self.report['roles'][role]['observation']['clock']['boot_id']

    def _host_problems(self, trial, ledgers=None):
        """Both hosts, before anything is touched. A dirty host is a failure of the batch, not of a run."""
        problems = []
        for role in ROLES:
            plan = self._plan(trial, role)
            facts = self._runner(role, 'preflight', '--plan-json', json.dumps(plan, sort_keys=True))
            if facts.get('ok') is not True:
                problems.append('%s preflight refused: %s %s' % (role, facts.get('code'), facts.get('detail')))
                continue
            source_sha = self.manifest['source']['benchmark_sha'] if role == 'bot' else None
            problems += ['%s: %s' % (role, problem) for problem in run_checks.host_problems(plan, facts, self._expected_boot(role), self.runner_sha256, source_sha)]
            if ledgers is not None:
                ledgers[role] = facts.get('ledger') or []
        return problems

    # ---- one run -----------------------------------------------------------------------------

    def run_batch(self):
        """Run until the search or the session ends, then collect and hand over to cleanup. A stale controller does neither."""
        result = self.execute()
        if result.status == CONTROL_LOST:
            return result
        self.wrap_up(result)
        return result

    def execute(self):
        """Run the legal remaining trials. Assumes this controller holds the session in ``ready``."""
        try:
            self.prepare()
            while True:
                self._keepalive(force=True)
                records = self._records()
                self._sync_planner_journal(records)
                state = self._search_state(records)
                result = self._admit(state)
                if result.decision == admission.NO_REMAINING_WORK:
                    label = result.search['status']
                    return BatchResult(FINISHED if label in SEARCH_ENDINGS else STOPPED, search_status=label, detail=result.search['detail'], runs=self.outcomes)
                if not result.admitted:
                    return self._refused_admission(result)
                self._one_run(state, result)
        except ControlLost as lost:
            self._note('control_lost', code=lost.code, detail=lost.detail)
            return BatchResult(CONTROL_LOST, code=lost.code, detail=lost.detail, runs=self.outcomes)
        except CleanupStarted as cleanup:
            self._note('cleanup_started', detail=cleanup.detail)
            return BatchResult(CLEANUP_STARTED, detail=cleanup.detail, runs=self.outcomes)
        except BatchStop as stop:
            self._note('batch_stop', status=stop.status, code=stop.code, detail=stop.detail)
            return BatchResult(stop.status, search_status=stop.search_status, code=stop.code, detail=stop.detail, runs=self.outcomes)
        except (registry_client.RegistryUnavailable, registry_client.RegistryRejected) as error:
            return self._registry_failed(error)
        except GuestLost as lost:
            return self._batch_failed('guest_unreachable', cleanup_provider.redact(lost))
        except (cleanup_provider.ProviderError, ResumeRefused, ssh_access.HostVerificationFailed) as error:
            return self._batch_failed('pair_unverifiable', cleanup_provider.redact(error))
        except RunAborted as aborted:
            return self._batch_failed('guest_report_refused', aborted.reason)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # A defect or a full disk here must not hide behind a clean-looking return. C still arrives.
            return self._batch_failed('controller_failure', type(error).__name__)

    def _refused_admission(self, result):
        time_short = any('maximal legal remaining path' in reason for reason in result.reasons)
        if time_short:
            do_session.append_journal(self.session_dir, dict(kind='stop', manifest_sha256=self.sha, reason='time_exhausted',
                                                             stopped_at=result.evaluated_at))
            return BatchResult(PARTIAL, search_status='partial_time_exhausted', code='time_exhausted', detail='; '.join(result.reasons), runs=self.outcomes)
        return BatchResult(STOPPED, search_status=result.search.get('status'), code='admission_refused', detail='; '.join(result.reasons), runs=self.outcomes)

    def _registry_failed(self, error):
        code = getattr(error, 'code', 'registry_unavailable')
        detail = cleanup_provider.redact(error)
        self._note('registry_failed', code=code, detail=detail)
        if code in STALE_CODES:
            return BatchResult(CONTROL_LOST, code=code, detail=detail, runs=self.outcomes)
        if code in CLEANUP_CODES:
            return BatchResult(CLEANUP_STARTED, code=code, detail=detail, runs=self.outcomes)
        return BatchResult(STOPPED, code=code, detail=detail, runs=self.outcomes)

    def _batch_failed(self, code, detail):
        """An infrastructure failure with no run to carry it. It must survive this process, so resume cannot walk past it."""
        self._note('batch_failed', code=code, detail=detail)
        try:
            self.client.mutate('record_batch_stop', session_id=self.session_id, outcome=search.INFRASTRUCTURE_FAILURE, fencing_token=self.token, detail=code + ': ' + detail)
        except (registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
            self._note('batch_stop_unrecorded', detail=cleanup_provider.redact(error))
        return BatchResult(STOPPED, search_status=search.STOPPING[search.INFRASTRUCTURE_FAILURE], code=code, detail=detail, runs=self.outcomes)

    def _one_run(self, state, result):
        trial = search.next_trial(state)
        self._publish_selection(state, result)
        self.failpoint('after_selection')
        ledgers = {}
        problems = self._host_problems(trial, ledgers)
        if problems:
            stopped = self._batch_failed('host_not_reset', '; '.join(problems))
            raise BatchStop(STOPPED, stopped.code, stopped.detail, stopped.search_status)
        estimate = result.next_run['estimate']['total_s']
        asked = self.monotonic()
        self.failpoint('before_dispatch_commit')
        grant = self._dispatch(trial, estimate)
        self.failpoint('after_dispatch_commit')
        run_dir = self._run_dir(trial.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        do_session.write_new(run_dir / 'grant.json', json.dumps(grant, indent=2, sort_keys=True) + '\n')
        # ``asked`` is before the grant existed, so these local limits can only err early.
        launch_deadline = asked + session_clock.parse(grant['launch_by']) - session_clock.parse(grant['granted_at'])
        stop_by = launch_deadline + estimate
        context = RunContext(trial, grant, launch_deadline, stop_by, stop_by - self.timing['recorder_finalization_s'] - self.timing['per_trial_export_s'], ledgers=ledgers)
        self._drive(context)

    def _dispatch(self, trial, estimate):
        try:
            grant = self.client.mutate('dispatch_run', 'dispatch:%s:%s:%d' % (self.session_id, trial.run_id, self.token), session_id=self.session_id, run_id=trial.run_id,
                                       fencing_token=self.token, manifest_sha256=self.sha, estimated_duration_s=estimate, trial=trial.to_dict())
        except registry_client.RegistryRejected as rejection:
            if rejection.code in STALE_CODES:
                raise ControlLost(rejection.code, rejection.message)
            if rejection.code in CLEANUP_CODES:
                raise CleanupStarted(rejection.message)
            if rejection.code == 'does_not_fit':
                do_session.append_journal(self.session_dir, dict(kind='stop', manifest_sha256=self.sha, reason='time_exhausted', stopped_at=session_clock.iso(self.wall())))
                raise BatchStop(PARTIAL, 'time_exhausted', rejection.message, 'partial_time_exhausted')
            raise BatchStop(STOPPED, rejection.code, rejection.message)
        if grant.get('authorized') is not True:
            raise BatchStop(STOPPED, 'dispatch_not_authorized', trial.run_id)
        return grant

    def _drive(self, context):
        """Launch, watch and stop. Whatever happens here, every process is stopped and the evidence sealed before anything is claimed."""
        cleanup = None
        try:
            self._launch(context)
            self._watch(context)
        except RunAborted as aborted:
            context.problems.setdefault(aborted.kind, []).append(aborted.reason)
            context.interrupted = aborted.reason
        except GuestLost as lost:
            context.problems[run_checks.INFRASTRUCTURE].append(cleanup_provider.redact(lost))
            context.interrupted = 'guest_lost'
        except ControlLost as lost:
            self._stop_after_control_loss(context, lost)
            raise
        except CleanupStarted as started:
            cleanup = started
            context.interrupted = 'cleanup_started'
        except registry_client.RegistryRejected as rejection:
            if rejection.code in STALE_CODES:
                lost = ControlLost(rejection.code, rejection.message)
                self._stop_after_control_loss(context, lost)
                raise lost
            if rejection.code == 'launch_window_closed':
                context.problems.setdefault(NOT_LAUNCHED, []).append(rejection.code)
            elif rejection.code in CLEANUP_CODES:
                cleanup = CleanupStarted(rejection.message)
            context.interrupted = rejection.code
        except registry_client.RegistryUnavailable as error:
            # Stopping comes first. If the registry stays away the commits below raise, with the processes already stopped.
            context.interrupted = 'registry_unavailable'
            self._note('registry_unavailable_during_run', run_id=context.trial.run_id, detail=cleanup_provider.redact(error))
        except (OSError, ValueError, KeyError, TypeError) as error:
            context.problems[run_checks.INFRASTRUCTURE].append('the controller failed locally: ' + type(error).__name__)
            context.interrupted = 'controller_failure'
        self._finish_run(context)
        if cleanup is not None:
            raise cleanup

    def _stop_after_control_loss(self, context, lost):
        """Best effort, by this run's id only. A newer fence refuses it, and then the new controller already owns the run."""
        self._note('run_control_lost', run_id=context.trial.run_id, code=lost.code)
        for role in ('bot', 'game'):
            try:
                self._runner(role, 'stop', '--run-id', context.trial.run_id, '--role', role, '--token', self.token, '--reason', 'control_lost',
                             '--wait-s', 5, on_wait=lambda: None)
            except (ControlLost, GuestLost, RunAborted):
                pass

    def _launch(self, context):
        trial = context.trial
        if self.monotonic() >= context.launch_deadline:
            raise RunAborted(NOT_LAUNCHED, 'the grant expired before launch')
        self.client.mutate('record_run_progress', session_id=self.session_id, run_id=trial.run_id, phase='launching', fencing_token=self.token)
        self.failpoint('after_launching_commit')
        must_stop_by = session_clock.parse(context.grant['must_stop_by'])
        reserved = self.timing['recorder_finalization_s'] + self.timing['per_trial_export_s']
        grace = self.policy.stop_grace_s
        launch_by = session_clock.parse(context.grant['launch_by'])
        game = self._plan(trial, 'game', launch_by, max(1.0, context.stop_by - self.monotonic() - reserved - grace), must_stop_by - reserved - grace)
        self._start_role(context, game)
        self.failpoint('after_game_start')
        self._await_game_socket(context, game)
        bound = context.stop_by - self.monotonic() - reserved - 2 * grace
        if bound < run_plan.workload_s(trial):
            raise RunAborted(NOT_LAUNCHED, 'too little of the grant is left for the whole workload: %.1f s' % bound)
        bot = self._plan(trial, 'bot', launch_by + self.policy.game_start_wait_s, bound, must_stop_by - reserved - 2 * grace)
        self._start_role(context, bot)
        self.failpoint('after_bot_start')
        self.client.mutate('record_run_progress', session_id=self.session_id, run_id=trial.run_id, phase='running', fencing_token=self.token,
                           execution_ref='plans:' + run_plan.plan_digest(context.plans))
        self.failpoint('after_running_commit')

    def _start_role(self, context, plan):
        role = plan['role']
        run_dir = self._run_dir(plan['run_id'])
        do_session.write_new(run_dir / ('plan-%s.json' % role), json.dumps(plan, indent=2, sort_keys=True) + '\n')
        context.plans[role] = plan
        document = self._runner(role, 'start', '--plan-json', json.dumps(plan, sort_keys=True))
        if document.get('ok') is not True:
            code, detail = document.get('code'), document.get('detail')
            if code == 'launch_window_closed':
                raise RunAborted(NOT_LAUNCHED, '%s start arrived after its grant' % role)
            raise RunAborted(run_checks.INFRASTRUCTURE, '%s start refused: %s %s' % (role, code, detail))
        context.launched = True
        context.summaries[role] = document
        problems = run_checks.launch_problems(plan, document, self._ledger_without(context.ledgers.get(role), plan['run_id']))
        if problems:
            raise RunAborted(run_checks.INFRASTRUCTURE, '%s: %s' % (role, '; '.join(problems)))

    @staticmethod
    def _ledger_without(ledger, run_id):
        return [entry for entry in ledger or [] if entry.get('run_id') != run_id]

    def _await_game_socket(self, context, plan):
        deadline = self.monotonic() + self.policy.game_start_wait_s
        while True:
            summary = self._runner('game', 'status', '--run-id', plan['run_id'], '--role', 'game')
            if summary.get('ok') is True:
                context.summaries['game'] = summary
                if summary.get('result') is not None:
                    raise RunAborted(run_checks.INFRASTRUCTURE, 'the game ended during startup, before any load: %s' % json.dumps(summary['result'], sort_keys=True))
                if summary.get('socket') is not None:
                    problems = run_checks.socket_problems(plan, summary, self._ledger_without(context.ledgers.get('game'), plan['run_id']), self.require_counters)
                    if problems:
                        raise RunAborted(run_checks.INFRASTRUCTURE, '; '.join(problems))
                    return
            if self.monotonic() >= deadline:
                raise RunAborted(run_checks.INFRASTRUCTURE, 'the game never opened its socket')
            self.sleep(self.policy.game_start_poll_s)
            self._keepalive()

    def _watch(self, context):
        run_id = context.trial.run_id
        last_seen = {role: self.monotonic() for role in ROLES}
        while True:
            self._keepalive()
            finished = False
            for role in ROLES:
                try:
                    summary = self._runner(role, 'status', '--run-id', run_id, '--role', role)
                except GuestLost as lost:
                    if self.monotonic() - last_seen[role] > self.policy.guest_loss_tolerance_s:
                        raise RunAborted(run_checks.INFRASTRUCTURE, 'lost contact with the %s host: %s' % (role, cleanup_provider.redact(lost)))
                    continue
                if summary.get('ok') is not True:
                    raise RunAborted(run_checks.INFRASTRUCTURE, '%s status refused: %s' % (role, summary.get('code')))
                last_seen[role] = self.monotonic()
                context.summaries[role] = summary
                if summary.get('result') is not None:
                    finished = finished or role == 'bot'
                    continue
                if not (summary.get('supervisor') or {}).get('alive'):
                    raise RunAborted(run_checks.INFRASTRUCTURE, 'the %s supervisor is gone with no result' % role)
                if summary.get('stopping') is None and ((summary.get('processes') or {}).get('sampler') or {}).get('alive') is not True:
                    raise RunAborted(run_checks.INFRASTRUCTURE, 'the %s sampler is gone while the run continues' % role)
            if finished:
                return
            # Each supervisor has already stopped its own processes by now, so still running here means it failed.
            if self.monotonic() >= context.workload_ends:
                raise RunAborted(run_checks.INFRASTRUCTURE, 'the workload outlived every process bound')
            self.sleep(min(self.policy.poll_s, max(0.01, context.workload_ends - self.monotonic())))

    def _stop_role(self, context, role, reason):
        document = self._runner(role, 'stop', '--run-id', context.trial.run_id, '--role', role, '--token', self.token, '--reason', reason,
                                '--wait-s', self.policy.stop_wait_s, timeout_s=self.policy.stop_wait_s + self.policy.guest_step_timeout_s, on_wait=self._quiet_keepalive)
        if document.get('ok') is not True:
            return document.get('code')
        context.summaries[role] = document
        return None if document.get('stopped') is True else 'still_running'

    def _finish_run(self, context):
        """Stop, seal and export. Each host independently: a dead game host must not cost the swarm's evidence."""
        run_id = context.trial.run_id
        reason = context.interrupted or 'workload_finished'
        for role in ('bot', 'game'):
            try:
                failure = self._stop_role(context, role, reason)
            except GuestLost as lost:
                context.problems[run_checks.INFRASTRUCTURE].append('%s could not be stopped: %s' % (role, cleanup_provider.redact(lost)))
                continue
            if failure not in (None, 'unknown_run'):
                context.problems[run_checks.INFRASTRUCTURE].append('%s could not be stopped: %s' % (role, failure))
        self.failpoint('after_stop')
        self._safe_progress(run_id, 'stopped')
        for role in ROLES:
            self._seal_role(context, role)
        self.failpoint('after_seal')
        self._export(context)
        execution = self._write_execution(context, 'execution.json')
        self._safe_progress(run_id, 'sealed', execution['ref'])
        self.failpoint('after_execution_record')
        verdict = self._classify(context, execution)
        self._commit_outcome(context, verdict)

    def _safe_progress(self, run_id, phase, execution_ref=None):
        try:
            self.client.mutate('record_run_progress', session_id=self.session_id, run_id=run_id, phase=phase, fencing_token=self.token, execution_ref=execution_ref)
        except registry_client.RegistryRejected as rejection:
            if rejection.code in STALE_CODES:
                raise ControlLost(rejection.code, rejection.message)
            if rejection.code != 'phase_regressed':
                raise

    def _seal_role(self, context, role):
        run_id = context.trial.run_id
        arguments = ['--run-id', run_id, '--role', role, '--token', self.token]
        if context.interrupted:
            arguments += ['--interrupted', context.interrupted]
        try:
            sealed = self._runner(role, 'seal', *arguments, timeout_s=max(self.policy.guest_step_timeout_s, self.timing['recorder_finalization_s']), on_wait=self._quiet_keepalive)
        except GuestLost as lost:
            context.problems[run_checks.INFRASTRUCTURE].append('%s could not be sealed: %s' % (role, cleanup_provider.redact(lost)))
            return
        if sealed.get('ok') is not True:
            if sealed.get('code') != 'unknown_run':
                context.problems[run_checks.INFRASTRUCTURE].append('%s could not be sealed: %s' % (role, sealed.get('code')))
            return
        context.sealed[role] = sealed
        context.summaries[role] = sealed

    def _export(self, context):
        for role, sealed in context.sealed.items():
            context.exported[role] = self._export_role(context.trial.run_id, role, sealed)
            if not context.exported[role]['complete']:
                context.problems[run_checks.INFRASTRUCTURE].append('%s evidence was not fully exported: %s' % (role, context.exported[role]['failed']))

    def _export_role(self, run_id, role, sealed):
        """Through ``.partial`` and SHA256, as the lifecycle contract asks. A file that fails stays partial and is never promoted."""
        target = self._run_dir(run_id) / role
        target.mkdir(parents=True, exist_ok=True)
        remote = guest_runner.DEFAULT_ROOT + '/runs/' + run_id + '/' + role + '/'
        wanted = [(item['path'], item['sha256']) for item in sealed['seal']['files']] + [(guest_runner.SEAL, sealed['seal_sha256'])]
        failed, copied = [], 0
        for relative, digest in wanted:
            local = target / relative
            if local.exists() and sha256_path(local) == digest:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            partial = local.with_name(local.name + '.partial')
            try:
                result = self.guests.get(role, remote + relative, str(partial), self._guest_timeout(self.policy.transfer_timeout_s), self._quiet_keepalive)
            except GuestLost as lost:
                failed.append(dict(path=relative, reason=cleanup_provider.redact(lost)))
                continue
            if result.returncode != 0:
                failed.append(dict(path=relative, reason=cleanup_provider.redact(result.stderr)))
            elif sha256_path(partial) != digest:
                failed.append(dict(path=relative, reason='hash mismatch'))
            else:
                publish_new(partial, local)
                copied += 1
        return dict(complete=not failed, failed=failed, files=len(wanted), copied=copied)

    def _write_execution(self, context, name):
        """The boundary between running and scoring: what happened, bound by hash. Create-only, like every run file."""
        ledgers = {role: self._ledger_without(context.ledgers.get(role), context.trial.run_id) for role in ROLES}
        problems = dict(context.problems)
        if context.plans and set(context.plans) == set(ROLES):
            found = run_checks.execution_problems(context.plans, context.summaries, context.sealed, ledgers, self.require_counters)
            for kind, items in found.items():
                problems[kind] = list(problems.get(kind, [])) + items
        document = dict(schema='omega.do-session.run-execution/1', session_id=self.session_id, manifest_sha256=self.sha, run_id=context.trial.run_id, trial=context.trial.to_dict(),
                        fencing_token=self.token, grant=context.grant, plan_digests={role: run_plan.plan_digest(plan) for role, plan in context.plans.items()},
                        launched=context.launched, interrupted=context.interrupted, problems=problems, runner_sha256=self.runner_sha256,
                        roles={role: dict(identity=dict(supervisor=summary.get('supervisor'), processes=summary.get('processes'), invocation_id=summary.get('invocation_id')),
                                          result=summary.get('result'), socket=summary.get('socket'), sampler=summary.get('sampler'), seal_sha256=summary.get('seal_sha256'))
                               for role, summary in context.summaries.items()},
                        exported=context.exported)
        path = self._run_dir(context.trial.run_id) / name
        text = json.dumps(document, indent=2, sort_keys=True) + '\n'
        if manifest_mod.scan_for_secrets(document):
            raise RunAborted(run_checks.INFRASTRUCTURE, 'the execution record held a credential value and was not written')
        do_session.write_new(path, text)
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return dict(document=document, sha256=digest, ref='runs/%s/%s#sha256:%s' % (context.trial.run_id, name, digest), path=path)

    def _classify(self, context, execution):
        problems = execution['document']['problems']
        if problems.get(NOT_LAUNCHED):
            return dict(outcome=search.INCOMPLETE, reasons=problems[NOT_LAUNCHED], scored=False)
        if context.interrupted and not any(problems.get(kind) for kind in (run_checks.INFRASTRUCTURE,)):
            return dict(outcome=search.INCOMPLETE, reasons=[context.interrupted], scored=False)
        settled = run_checks.disposition(problems)
        answer = None
        if settled['scorable'] and self.scorer is not None:
            answer = self.scorer(self._evidence_for_scorer(context, execution))
        return run_checks.apply_scorer(settled, answer)

    def _evidence_for_scorer(self, context, execution):
        """Everything a scorer may read: verified local files and the sealed execution facts. Nothing live."""
        return dict(run_id=context.trial.run_id, trial=context.trial.to_dict(), root=str(self._run_dir(context.trial.run_id)), execution=execution['document'],
                    execution_sha256=execution['sha256'], execution_ref=execution['ref'])

    def _commit_outcome(self, context, verdict):
        run_id = context.trial.run_id
        document = dict(schema='omega.do-session.run-classification/1', run_id=run_id, verdict=verdict)
        if manifest_mod.scan_for_secrets(document):
            document = dict(document, verdict=dict(outcome=search.INCONCLUSIVE, reasons=['the classification held a credential value and was replaced'], scored=False))
            verdict = document['verdict']
        text = json.dumps(document, indent=2, sort_keys=True) + '\n'
        path = self._run_dir(run_id) / 'classification.json'
        do_session.write_new(path, text)
        reference = 'runs/%s/classification.json#sha256:%s' % (run_id, hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.failpoint('before_outcome_commit')
        self._record_outcome(run_id, verdict['outcome'], reference)
        self.failpoint('after_outcome_commit')
        self._sync_planner_journal()
        self.failpoint('after_journal_mirror')
        self.outcomes.append(dict(run_id=run_id, outcome=verdict['outcome'], reasons=verdict.get('reasons')))

    def _record_outcome(self, run_id, outcome, reference):
        try:
            self.client.mutate('record_run_outcome', 'outcome:%s:%s:%d' % (self.session_id, run_id, self.token), session_id=self.session_id, run_id=run_id, outcome=outcome,
                               fencing_token=self.token, evidence_ref=reference)
        except registry_client.RegistryRejected as rejection:
            if rejection.code in STALE_CODES:
                raise ControlLost(rejection.code, rejection.message)
            if rejection.code != 'outcome_recorded':
                raise

    # ---- coming back after an interruption ---------------------------------------------------

    def reconcile(self, reason='controller_replaced'):
        """Stop and preserve whatever the last controller left, and classify each unfinished run from what it left.

        No run is restarted or continued. A run with no proof of its result is INCOMPLETE, and its dependent path stays stopped.
        Returns the host problems found, for the caller to judge.
        """
        records = self._records()
        unfinished = [r for r in records if r['outcome'] is None]
        known = {r['run_id'] for r in records}
        problems = []
        inventories = {}
        for role in ROLES:
            try:
                inventories[role] = self._runner(role, 'inspect')
            except GuestLost as lost:
                problems.append('%s could not be inspected: %s' % (role, cleanup_provider.redact(lost)))
        for role, view in inventories.items():
            for entry in view.get('runs') or []:
                if entry.get('run_id') not in known:
                    # Selected and started by nobody we recorded: it still must not run on, and it is never ours to claim.
                    self._retire_unknown(role, entry, reason)
                    problems.append('%s holds run %s that the registry never dispatched' % (role, entry.get('run_id')))
        for row in unfinished:
            self._reconcile_run(row, reason, inventories)
        self._sync_planner_journal()
        return problems

    def _retire_unknown(self, role, entry, reason):
        run_id = entry['run_id']
        try:
            self._runner(role, 'stop', '--run-id', run_id, '--role', role, '--token', self.token, '--reason', reason, on_wait=self._quiet_keepalive)
            self._runner(role, 'seal', '--run-id', run_id, '--role', role, '--token', self.token, '--interrupted', reason, on_wait=self._quiet_keepalive)
        except GuestLost as lost:
            self._note('unknown_run_not_retired', role=role, run_id=run_id, detail=cleanup_provider.redact(lost))

    def _reconcile_run(self, row, reason, inventories):
        trial = search.trial_from_dict(row['trial'])
        run_dir = self._run_dir(trial.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        grant = dict(launch_by=row['launch_by'], must_stop_by=row['must_stop_by'], interrupted_reason=row['interrupted_reason'])
        now = self.monotonic()
        context = RunContext(trial, grant, now, now, now, interrupted=row['interrupted_reason'] or reason)
        reachable = True
        for role in ROLES:
            plan_path = run_dir / ('plan-%s.json' % role)
            if plan_path.exists():
                context.plans[role] = json.loads(plan_path.read_text())
            if role not in inventories:
                reachable = False
                continue
            context.ledgers[role] = inventories[role].get('ledger') or []
            if any(entry.get('run_id') == trial.run_id and entry.get('role') == role for entry in inventories[role].get('runs') or []):
                self._reconcile_role(context, role, reason)
        self._export(context)
        name = 'execution.json' if not (run_dir / 'execution.json').exists() else 'execution-reconciled.json'
        if (run_dir / name).exists():
            name = 'execution-reconciled-%d.json' % self.token
        execution = self._write_execution(context, name)
        if set(context.sealed) == set(ROLES):
            self._safe_progress(trial.run_id, 'sealed', execution['ref'])
        verdict = self._interrupted_verdict(context, execution, reachable)
        self._commit_interrupted(context, verdict, execution)

    def _reconcile_role(self, context, role, reason):
        run_id = context.trial.run_id
        try:
            stopped = self._runner(role, 'stop', '--run-id', run_id, '--role', role, '--token', self.token, '--reason', reason, '--wait-s', self.policy.stop_wait_s,
                                   timeout_s=self.policy.stop_wait_s + self.policy.guest_step_timeout_s, on_wait=self._quiet_keepalive)
            if stopped.get('ok') is True:
                context.summaries[role] = stopped
        except GuestLost as lost:
            context.problems[run_checks.INFRASTRUCTURE].append('%s could not be stopped: %s' % (role, cleanup_provider.redact(lost)))
            return
        self._seal_role(context, role)

    def _interrupted_verdict(self, context, execution, reachable):
        """A crash just before the commit keeps the verdict already reached. Otherwise only retained evidence can say more than INCOMPLETE."""
        path = self._run_dir(context.trial.run_id) / 'classification.json'
        if path.exists():
            document = json.loads(path.read_text())
            return dict(document['verdict'], reused=True)
        boots = {role: self._expected_boot(role) for role in ROLES} if self.report else {}
        demonstrated = run_checks.interrupted_outcome(context.plans, context.summaries, boots)
        if demonstrated is not None:
            return dict(demonstrated, scored=False)
        problems = execution['document']['problems']
        if not reachable or set(context.sealed) != set(ROLES) or not run_checks.finished_naturally(context.plans, context.summaries):
            return dict(outcome=search.INCOMPLETE, reasons=['interrupted: ' + str(context.interrupted)], scored=False)
        settled = run_checks.disposition(problems)
        if not settled['scorable'] or self.scorer is None:
            return dict(outcome=search.INCOMPLETE, reasons=['the run ended by itself, but nothing has scored it: ' + '; '.join(settled['reasons'])], scored=False)
        verdict = run_checks.apply_scorer(settled, self.scorer(self._evidence_for_scorer(context, execution)))
        if not verdict.get('scored'):
            return dict(outcome=search.INCOMPLETE, reasons=verdict['reasons'], scored=False)
        return verdict

    def _commit_interrupted(self, context, verdict, execution):
        run_id = context.trial.run_id
        path = self._run_dir(run_id) / 'classification.json'
        if verdict.get('reused'):
            text = path.read_text()
            reference = 'runs/%s/classification.json#sha256:%s' % (run_id, hashlib.sha256(text.encode('utf-8')).hexdigest())
            self._record_outcome(run_id, verdict['outcome'], reference)
            self.outcomes.append(dict(run_id=run_id, outcome=verdict['outcome'], reasons=verdict.get('reasons'), reused=True))
            return
        self._commit_outcome(context, verdict)

    # ---- explicit resume ---------------------------------------------------------------------

    def resume(self, operator_request_ref, control):
        """Revalidate everything, or refuse. ``control`` is the acquisition this controller just made. Returns the checks."""
        checks = dict(manifest_sha256=self.sha, control_exclusive=False, manifest_unchanged=False, pair_unchanged=False, source_unchanged=False,
                      readiness_revalidated=False, processes_reset=False, headroom_admitted=False, interrupted_preserved=False, next_run_id=None)
        history = dict(requested_at=session_clock.iso(self.wall()), operator_request_ref=operator_request_ref, fencing_token=self.token, checks=checks)
        try:
            self._resume_checks(control, checks)
            self.client.mutate('record_resume', session_id=self.session_id, fencing_token=self.token, operator_request_ref=operator_request_ref, checks=checks)
            history.update(decision='resumed')
            return dict(resumed=True, checks=checks, next_run_id=checks['next_run_id'])
        except ResumeRefused as refused:
            history.update(decision='refused', code=refused.code, detail=refused.detail)
            return dict(resumed=False, code=refused.code, detail=refused.detail, checks=checks)
        except registry_client.RegistryRejected as rejection:
            history.update(decision='refused', code=rejection.code, detail=str(rejection.message))
            return dict(resumed=False, code=rejection.code, detail=str(rejection.message), checks=checks)
        except (registry_client.RegistryUnavailable, GuestLost, cleanup_provider.ProviderError, BatchStop, RunAborted, ControlLost, CleanupStarted) as error:
            code = getattr(error, 'code', type(error).__name__)
            history.update(decision='refused', code=code, detail=cleanup_provider.redact(error))
            return dict(resumed=False, code=code, detail=cleanup_provider.redact(error), checks=checks)
        finally:
            self._note('resume_request', **history)

    def _require_resumable(self, status):
        """What an interruption can never excuse. All of it comes from the registry, none from local files."""
        if status['cleanup']['requested_at'] is not None or status['state'] in (registry.DELETING, registry.CLOSED):
            raise ResumeRefused('cleanup_in_progress', status['cleanup']['reason'] or status['state'])
        if status['terminal_failure'] is not None:
            raise ResumeRefused('terminal_failure', status['terminal_failure'])
        if status['state'] != registry.PAUSED:
            raise ResumeRefused('not_paused', status['state'])

    def _resume_checks(self, control, checks):
        status = self._status()
        if status['fencing_token'] != self.token or control.get('fencing_token') != self.token:
            raise ResumeRefused('control_not_exclusive', 'this controller does not hold the current fence')
        checks['control_exclusive'] = True
        self._require_resumable(status)
        if status['manifest_sha256'] != self.sha:
            raise ResumeRefused('manifest_changed', 'the registry holds a different manifest')
        manifest_mod.verify_manifest(self.manifest, self.sha)
        checks['manifest_unchanged'] = True
        now = session_clock.parse(self.client.call('health', session_id=self.session_id)['evaluated_at'])
        if now >= session_clock.parse(status['cleanup_c_utc']):     # the registry's clock, never this machine's
            raise ResumeRefused('deadline_reached', status['cleanup_c_utc'])
        source = self.source_problems() if self.source_problems is not None else ['no controller source check was supplied']
        if source:
            raise ResumeRefused('source_changed', '; '.join(source))
        self.prepared = False
        try:
            self.prepare(status)
        except BatchStop as stop:
            raise ResumeRefused(stop.code, stop.detail)
        checks['pair_unchanged'] = True
        unknown = self.reconcile()
        checks['interrupted_preserved'] = True
        if unknown:
            raise ResumeRefused('unknown_run_on_host', '; '.join(unknown))
        status = self._status()
        self._require_resumable(status)
        records = self._records()
        state = self._search_state(records)
        first = self._admit(state, resume=True)
        if first.decision == admission.NO_REMAINING_WORK:
            raise ResumeRefused('no_eligible_untouched_work', first.search['status'] + ': ' + first.search['detail'])
        if not first.admitted:
            raise ResumeRefused('headroom_exhausted', '; '.join(first.reasons))
        trial = search.next_trial(state)
        checks['next_run_id'] = trial.run_id
        problems = self.readiness_problems(self.report)
        if problems:
            raise ResumeRefused('readiness_failed', '; '.join(problems))
        checks['readiness_revalidated'] = True
        dirty = self._host_problems(trial)
        if dirty:
            raise ResumeRefused('host_not_reset', '; '.join(dirty))
        checks['source_unchanged'] = True
        checks['processes_reset'] = True
        # Revalidation took time, and only an admission after it can answer for what is left.
        final = self._admit(state, resume=True)
        if not final.admitted:
            raise ResumeRefused('headroom_exhausted', '; '.join(final.reasons))
        checks['headroom_admitted'] = True

    # ---- the end of a batch ------------------------------------------------------------------

    def wrap_up(self, result, request_cleanup=True):
        """Stop means collect and delete. Slice 7's exporter replaces the evidence status; a run's own export has already happened."""
        status = self._status()
        label = result.search_status or result.code or result.status
        try:
            if status['state'] in (registry.READY, registry.PAUSED, registry.EVIDENCE_RECOVERY):
                self.client.mutate('begin_collection', session_id=self.session_id, fencing_token=self.token)
            missing = self._collect_missing()
            if missing:
                self._recover_evidence(missing)
            self.client.mutate('record_measurement', session_id=self.session_id, fencing_token=self.token, outcome=label, ref='execution/journal.ndjson')
            self.client.mutate('record_evidence', session_id=self.session_id, fencing_token=self.token, status='partial', ref='run-level exports; session export belongs to slice 7')
        except registry_client.RegistryRejected as rejection:
            self._note('wrap_up_rejected', code=rejection.code, detail=str(rejection.message))
        except registry_client.RegistryUnavailable as error:
            self._note('wrap_up_unacknowledged', detail=cleanup_provider.redact(error))
        if request_cleanup:
            try:
                self.client.mutate('request_cleanup', session_id=self.session_id, fencing_token=self.token, reason='batch ended: ' + str(label))
            except (registry_client.RegistryRejected, registry_client.RegistryUnavailable) as error:
                # The watchdog still deletes by C.
                self._note('cleanup_request_unacknowledged', detail=cleanup_provider.redact(error))
        return result

    def _collect_missing(self):
        """Files named by a seal that never arrived. Reads only: a sealed tree cannot change, so this can retry safely."""
        missing = []
        for row in self._records():
            run_dir = self._run_dir(row['run_id'])
            for role in ROLES:
                local_seal = run_dir / role / guest_runner.SEAL
                if not local_seal.exists() and (run_dir / ('plan-%s.json' % role)).exists():
                    missing.append((row['run_id'], role))
        return missing

    def _recover_evidence(self, missing):
        """One bounded episode. It ends at the registry's own deadline, and a reconnect never reopens it."""
        try:
            episode = self.client.mutate('begin_evidence_recovery', session_id=self.session_id, fencing_token=self.token)
        except registry_client.RegistryRejected as rejection:
            self._note('recovery_refused', code=rejection.code)
            return missing
        asked = self.monotonic()
        now = session_clock.parse(self.client.call('health', session_id=self.session_id)['evaluated_at'])
        ends = asked + session_clock.parse(episode['recovery_deadline_utc']) - now
        self.in_recovery = True
        try:
            while missing and self.monotonic() < ends:
                remaining = []
                for run_id, role in missing:
                    if not self._recover_role(run_id, role):
                        remaining.append((run_id, role))
                missing = remaining
                if missing:
                    self.sleep(min(self.policy.recovery_poll_s, max(0.01, ends - self.monotonic())))
                    self._quiet_keepalive()
        finally:
            self.in_recovery = False
        for run_id, role in missing:
            self._note('evidence_unrecovered', run_id=run_id, role=role)
        try:
            self.client.mutate('begin_collection', session_id=self.session_id, fencing_token=self.token)
        except registry_client.RegistryRejected as rejection:
            self._note('collection_not_reopened', code=rejection.code)
        return missing

    def _recover_role(self, run_id, role):
        try:
            sealed = self._runner(role, 'status', '--run-id', run_id, '--role', role, on_wait=self._quiet_keepalive)
            if sealed.get('ok') is not True or sealed.get('sealed') is not True:
                return False
            remote_seal = guest_runner.DEFAULT_ROOT + '/runs/' + run_id + '/' + role + '/' + guest_runner.SEAL
            with tempfile.TemporaryDirectory() as temporary:
                local = pathlib.Path(temporary) / guest_runner.SEAL
                result = self.guests.get(role, remote_seal, str(local), self._guest_timeout(self.policy.transfer_timeout_s), self._quiet_keepalive)
                if result.returncode != 0 or sha256_path(local) != sealed.get('seal_sha256'):
                    return False
                seal = json.loads(local.read_text())
            return self._export_role(run_id, role, dict(seal=seal, seal_sha256=sealed['seal_sha256']))['complete']
        except (GuestLost, ControlLost, RunAborted, OSError, ValueError):
            return False


def source_identity_problems(manifest, repository, runner=None):
    """This controller's own code against the frozen revision. Each of these is a change the batch never reviewed."""
    import subprocess
    run = runner or (lambda argv: subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False))
    head = run(['git', '-C', str(repository), 'rev-parse', 'HEAD'])
    dirty = run(['git', '-C', str(repository), 'status', '--porcelain', '--', 'scripts/do_session'])
    problems = []
    if head.returncode != 0 or head.stdout.decode().strip() != manifest['source']['controller_sha']:
        problems.append('the controller checkout is not the frozen controller revision')
    if dirty.returncode != 0 or dirty.stdout.strip():
        problems.append('the controller code has uncommitted changes')
    return problems
