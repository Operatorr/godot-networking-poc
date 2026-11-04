"""A fake guest for the run slice: the same documents as ``guest_runner``, on the scripted clock, with faults on request.

It models processes as times, not as processes. ``test_guest_runner`` and the local integration prove the real runner produces
what this fake claims: both pass through the same ``run_checks`` rules, and ``CONTRACT_KEYS`` is checked against real output.
"""
import hashlib
import json

import fake_guest
import guest_runner
import ssh_access

CONTRACT_KEYS = dict(
    preflight=('active', 'boot_id', 'disk_free_bytes', 'fence', 'files', 'impairment', 'ledger', 'leftovers', 'monotonic_ns', 'ok', 'ports_free', 'run_dir_exists', 'runner_sha256', 'schema', 'source', 'units', 'wall_ns'),
    status=('fencing_token', 'has_plan', 'invocation_id', 'ok', 'processes', 'result', 'role', 'run_id', 'sampler', 'schema', 'seal_sha256', 'sealed', 'session_id', 'socket', 'stopping', 'supervisor'),
    inspect=('active', 'boot_id', 'fence', 'ledger', 'ok', 'runs', 'schema'),
)
QDISCS = ['fq_codel', 'mq', 'noqueue']


def option(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


class FakeRun:
    def __init__(self, plan, host, now, wall, ends_after_s):
        self.plan = plan
        self.host = host
        self.started = now
        self.started_wall = wall
        self.ends_at = None if ends_after_s is None else now + ends_after_s
        self.exit_code = 0
        self.exit_signal = None
        self.stop_reason = None
        self.stop_at = None
        self.killed = False
        self.sealed = None
        self.seal_sha256 = None
        self.sampler_dead_at = None
        self.supervisor_dead = False
        self.sampler_rows = 0
        self.socket_rows = None
        self.identity = None
        self.files = {}


class FakeHost:
    def __init__(self, role):
        self.role = role
        self.boot_id = 'fixture-boot-' + role
        self.fence = None
        self.active = None
        self.ledger = []
        self.runs = {}
        self.leftovers = []
        self.busy_ports = set()
        self.qdiscs = list(QDISCS)
        self.filters = 0
        self.units = []
        self.file_overrides = {}
        self.source_head = None
        self.source_clean = True
        self.next_pid = 5000
        self.next_inode = 70000
        self.runner_sha256 = None
        self.scripted_identity = None   # replays a chosen identity for the next process started
        self.scripted_inode = None


class FakeRunGuests(fake_guest.FakeGuests):
    """Faults are plain attributes, so each test states the one thing that is wrong."""

    def __init__(self, sim):
        super().__init__(sim)
        self.hosts = dict(game=FakeHost('game'), bot=FakeHost('bot'))
        self.hosts['bot'].source_head = self.manifest['source']['benchmark_sha']
        self.calls = []
        self.unreachable = set()        # (role, command): the command never ran
        self.lost_answer = set()        # (role, command): the command ran and its answer was lost
        self.bot_seconds = None         # how long the swarm runs; defaults to its whole workload
        self.bot_exit = (0, None)
        self.game_crash_after_s = None
        self.game_exit = (101, None)
        self.bot_hangs = False
        self.no_report = False
        self.sampler_dies_after_s = {}
        self.drop_counter_rewind = False
        self.corrupt_export = set()
        self.socket_never_opens = False
        self.fail_start = {}
        self.upload_ok = True

    # ---- transport ---------------------------------------------------------------------------

    def run(self, role, argv, timeout_s, on_wait=None):
        if len(argv) > 2 and argv[0] == 'python3' and 'guest_runner-' in argv[1]:
            return self._run_runner(role, argv, timeout_s, on_wait)
        return super().run(role, argv, timeout_s, on_wait)

    def _run_runner(self, role, argv, timeout_s, on_wait):
        if role not in self.pins:
            raise AssertionError('a runner command ran before the host key was restored')
        command = argv[2]
        self.calls.append(dict(role=role, command=command, at=self.sim.clock.wall(), token=option(argv, '--token')))
        self.commands.append(dict(role=role, step='runner:' + command, timeout_s=timeout_s))
        self._spend(1, on_wait)
        if (role, command) in self.unreachable:
            return ssh_access.CommandResult(255, '', 'connection timed out')
        try:
            document = getattr(self, '_do_' + command)(self.hosts[role], argv[3:])
        except guest_runner.Refused as refused:
            document = dict(ok=False, code=refused.code, detail=refused.detail)
        else:
            document = dict(document, ok=True)
        if (role, command) in self.lost_answer:
            return ssh_access.CommandResult(255, '', 'connection reset')
        return ssh_access.CommandResult(0, json.dumps(dict(document, schema=guest_runner.SCHEMA), sort_keys=True), '')

    def put(self, role, local_path, remote_path, timeout_s, on_wait=None):
        if 'guest_runner-' in str(remote_path):
            with open(str(local_path), 'rb') as handle:
                self.hosts[role].runner_sha256 = hashlib.sha256(handle.read()).hexdigest()
            self.commands.append(dict(role=role, step='upload_runner'))
            return ssh_access.CommandResult(0 if self.upload_ok else 1, '', '' if self.upload_ok else 'scripted copy failure')
        return super().put(role, local_path, remote_path, timeout_s, on_wait)

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        if '/do-runs/runs/' not in str(remote_path):
            return super().get(role, remote_path, local_path, timeout_s, on_wait)
        self.commands.append(dict(role=role, step='get', remote=str(remote_path)))
        if (role, 'get') in self.copy_failures:
            return ssh_access.CommandResult(1, '', 'scripted copy failure')
        parts = str(remote_path).split('/do-runs/runs/')[1].split('/', 2)
        run = self.hosts[role].runs[parts[0]]
        content = run.files[parts[2]]
        if parts[2] in self.corrupt_export:
            content = content + b'corrupted in transfer'
        with open(str(local_path), 'wb') as handle:
            handle.write(content)
        return ssh_access.CommandResult(0, '', '')

    # ---- a simulated run ---------------------------------------------------------------------

    def _now(self):
        return self.sim.clock.mono()

    def _settle(self, run):
        """Bring one run up to the scripted clock. Called before anything reads it, like a real host that kept running."""
        if run.stop_reason is not None or run.supervisor_dead:
            return
        now = self._now()
        bound_at = run.started + run.plan['bound_s']
        if self._now_wall() >= run.plan['stop_by_wall']:
            bound_at = min(bound_at, now)
        if run.ends_at is not None and run.ends_at <= min(now, bound_at):
            run.stop_reason, run.stop_at = 'primary_exited', run.ends_at
        elif now >= bound_at:
            run.stop_reason, run.stop_at, run.killed = 'bound_exhausted', bound_at, True

    def _now_wall(self):
        return self.sim.clock.wall()

    def _alive(self, run):
        self._settle(run)
        return run.stop_reason is None and not run.supervisor_dead

    def _summary(self, host, run):
        plan = run.plan
        alive = self._alive(run)
        primary = plan['processes'][0]['name']
        processes = {}
        for name, item in run.identity['processes'].items():
            sampler_dead = name == 'sampler' and run.sampler_dead_at is not None and self._now() >= run.sampler_dead_at
            processes[name] = dict(item, alive=alive and not sampler_dead)
        result = None
        if run.stop_reason is not None:
            exits = {primary: dict(returncode=None if self._killed(run) else self._exit_code(run), signal=9 if self._killed(run) else run.exit_signal, elapsed_s=run.stop_at - run.started),
                     'sampler': dict(returncode=0, signal=None, elapsed_s=run.stop_at - run.started)}
            result = dict(stop_reason=run.stop_reason, completed=True, processes=exits, elapsed_s=run.stop_at - run.started, bound_s=plan['bound_s'], ended_wall=self.sim.clock.wall(),
                          sampler_exited_early=run.sampler_dead_at is not None and run.sampler_dead_at < run.stop_at, killed=[primary] if self._killed(run) else [])
        rows = int(max(0, (run.stop_at if run.stop_at is not None else self._now()) - run.started)) + 2
        socket_view = None
        if plan.get('watch_socket_port') is not None and not self.socket_never_opens:
            pid, start_id = run.identity['processes']['game']['pid'], run.identity['processes']['game']['start_id']
            first = dict(inode=run.socket_rows, local='00000000:1F91', drops=3, rx_queue=0, counter_source='proc_net_udp', pid=pid, start_id=start_id, mono_ns=1, wall_ns=1)
            last = dict(first, drops=1 if self.drop_counter_rewind else 3 + rows)
            socket_view = dict(first=first, last=last, samples=rows)
        return dict(run_id=plan['run_id'], role=plan['role'], has_plan=True, session_id=plan['session_id'], fencing_token=plan['fencing_token'],
                    supervisor=dict(run.identity['supervisor'], alive=alive), invocation_id=run.identity['invocation_id'], processes=processes, result=result,
                    stopping=dict(reason=run.stop_reason) if run.stop_reason is not None else None,
                    sealed=run.sealed is not None, seal_sha256=run.seal_sha256, socket=socket_view, sampler=dict(rows=rows, last_mono_s=float(rows)))

    def _killed(self, run):
        return run.killed or (run.stop_reason or '').startswith('stop_requested') and run.plan['role'] == 'bot' and run.ends_at is None

    def _exit_code(self, run):
        return run.exit_code

    # ---- runner commands ---------------------------------------------------------------------

    def _do_fence(self, host, argv):
        session, token = option(argv, '--session'), int(option(argv, '--token'))
        if host.fence is not None and host.fence['session_id'] != session:
            raise guest_runner.Refused('foreign_session', '')
        if host.fence is not None and token < host.fence['token']:
            raise guest_runner.Refused('stale_fence', 'fence is at %s' % host.fence['token'])
        raised = host.fence is None or token > host.fence['token']
        host.fence = dict(session_id=session, token=token)
        return dict(token=token, raised=raised, active=host.active, runs=[self._summary(host, run) for run in host.runs.values()])

    def _do_inspect(self, host, argv):
        return dict(fence=host.fence, active=host.active, runs=[self._summary(host, run) for run in host.runs.values()], boot_id=host.boot_id, ledger=list(host.ledger))

    def _facts(self, host, plan):
        files = []
        for item in plan['verify_files']:
            files.append(dict(path=item['path'], present=True, sha256=host.file_overrides.get(item['path'], item['sha256']), size=1, executable=True))
        ports = {'%s/%d' % (p['protocol'], p['port']): p['port'] not in host.busy_ports for p in plan['ports']}
        impairment = dict(available=True, interface='eth0', qdisc_kinds=sorted(host.qdiscs), filter_count=host.filters)
        return dict(boot_id=host.boot_id, files=files, ports_free=ports, leftovers=list(host.leftovers), impairment=impairment, units=list(host.units), active=host.active,
                    fence=host.fence, ledger=list(host.ledger), run_dir_exists=plan['run_id'] in host.runs, runner_sha256=host.runner_sha256,
                    source=dict(head=host.source_head, clean=host.source_clean) if host.source_head is not None else None, disk_free_bytes=10 ** 10, wall_ns=1, monotonic_ns=1)

    def _do_preflight(self, host, argv):
        return self._facts(host, json.loads(option(argv, '--plan-json')))

    def _new_identity(self, host, name):
        if host.scripted_identity is not None and name not in ('sampler', 'supervisor'):
            scripted, host.scripted_identity = host.scripted_identity, None
            return dict(scripted, primary=True, path=name)
        host.next_pid += 1
        return dict(pid=host.next_pid, start_id='ticks:%d' % int(self._now() * 100 + host.next_pid), boot_id=host.boot_id, path=name, primary=name != 'sampler')

    def _do_start(self, host, argv):
        plan = json.loads(option(argv, '--plan-json'))
        if host.fence is None or host.fence['session_id'] != plan['session_id']:
            raise guest_runner.Refused('not_fenced', '')
        if plan['fencing_token'] != host.fence['token']:
            raise guest_runner.Refused('stale_fence', 'fence is at %s' % host.fence['token'])
        if self.sim.clock.wall() > plan['launch_not_after_wall'] + guest_runner.LAUNCH_CLOCK_TOLERANCE_S:
            raise guest_runner.Refused('launch_window_closed', '')
        if host.active is not None:
            raise guest_runner.Refused('overlap', host.active['run_id'])
        if plan['run_id'] in host.runs:
            raise guest_runner.Refused('duplicate_run_dir', plan['run_id'])
        facts = self._facts(host, plan)
        for item, expected in zip(facts['files'], plan['verify_files']):
            if item['sha256'] != expected['sha256']:
                raise guest_runner.Refused('hash_mismatch', item['path'])
        if facts['leftovers']:
            raise guest_runner.Refused('leftover_process', '')
        busy = [name for name, free in facts['ports_free'].items() if not free]
        if busy:
            raise guest_runner.Refused('port_busy', ', '.join(busy))
        if plan['role'] in self.fail_start:
            raise guest_runner.Refused(self.fail_start[plan['role']], 'scripted')
        ends = self._scripted_duration(plan)
        run = FakeRun(plan, host, self._now(), self.sim.clock.wall(), ends)
        primary = plan['processes'][0]['name']
        run.identity = dict(supervisor=self._new_identity(host, 'supervisor'), processes={primary: self._new_identity(host, primary), 'sampler': self._new_identity(host, 'sampler')},
                            invocation_id='fixture-invocation-%s-%d' % (plan['role'], host.next_pid), started_wall=self.sim.clock.wall())
        if plan['role'] == 'bot':
            run.exit_code, run.exit_signal = self.bot_exit
        else:
            run.exit_code, run.exit_signal = self.game_exit
        if plan.get('watch_socket_port') is not None:
            if host.scripted_inode is not None:
                run.socket_rows, host.scripted_inode = host.scripted_inode, None
            else:
                host.next_inode += 1
                run.socket_rows = str(host.next_inode)
        if plan['role'] in self.sampler_dies_after_s:
            run.sampler_dead_at = self._now() + self.sampler_dies_after_s[plan['role']]
        host.runs[plan['run_id']] = run
        host.active = dict(run_id=plan['run_id'], role=plan['role'], session_id=plan['session_id'], fencing_token=plan['fencing_token'])
        host.ledger.append(dict(run_id=plan['run_id'], role=plan['role'], supervisor=run.identity['supervisor'], invocation_id=run.identity['invocation_id'], processes=run.identity['processes']))
        return self._summary(host, run)

    def _scripted_duration(self, plan):
        if plan['role'] == 'bot':
            if self.bot_hangs:
                return None
            if self.bot_seconds is not None:
                return self.bot_seconds
            trial = next(t for t in [json.loads(json.dumps(plan))] if t)
            return float(trial['processes'][0]['argv'][trial['processes'][0]['argv'].index('--duration') + 1]) + 30.0
        return self.game_crash_after_s

    def _run_of(self, host, argv):
        run = host.runs.get(option(argv, '--run-id'))
        if run is None:
            raise guest_runner.Refused('unknown_run', '')
        return run

    def _do_status(self, host, argv):
        return self._summary(host, self._run_of(host, argv))

    def _do_stop(self, host, argv):
        run = self._run_of(host, argv)
        if int(option(argv, '--token')) != host.fence['token']:
            raise guest_runner.Refused('stale_fence', 'fence is at %s' % host.fence['token'])
        if self._alive(run):
            run.stop_reason, run.stop_at = 'stop_requested:' + option(argv, '--reason'), self._now()
            run.exit_code, run.exit_signal = (0, None) if run.plan['role'] == 'game' else (-15, 15)
            if run.plan['role'] == 'bot':
                run.exit_code = None
        if run.supervisor_dead:
            run.stop_reason, run.stop_at = run.stop_reason or 'supervisor_lost', self._now()
        return dict(self._summary(host, run), stopped=True, escalated=run.supervisor_dead)

    def _do_seal(self, host, argv):
        run = self._run_of(host, argv)
        if int(option(argv, '--token')) != host.fence['token']:
            raise guest_runner.Refused('stale_fence', 'fence is at %s' % host.fence['token'])
        if self._alive(run):
            raise guest_runner.Refused('still_running', '')
        if run.sealed is None:
            names = {'sampler.ndjson': b'{"mono_s": 1}\n{"mono_s": 2}\n', 'result.json': b'{}', 'bot.stdout.log': b'fixture log\n'}
            if run.plan['role'] == 'bot' and not self.no_report and run.stop_reason == 'primary_exited' and run.exit_code in run.plan['completed_exit_codes']:
                names['report.json'] = b'{"synthetic": true}\n'
            run.files = dict(names)
            ports = {'%s/%d' % (p['protocol'], p['port']): p['port'] not in host.busy_ports for p in run.plan['ports']}
            final = dict(sealed_by_token=int(option(argv, '--token')), interrupted=option(argv, '--interrupted'), boot_id=host.boot_id, wall_ns=1, ports_free=ports, leftovers=list(host.leftovers),
                         impairment=dict(available=True, interface='eth0', qdisc_kinds=sorted(host.qdiscs), filter_count=host.filters), units=list(host.units))
            summary = self._summary(host, run)
            run.sealed = dict(schema=guest_runner.SCHEMA, run_id=run.plan['run_id'], role=run.plan['role'], interrupted=option(argv, '--interrupted'), final=final, result=summary['result'],
                              files=[dict(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data)) for path, data in sorted(names.items())], identity=run.identity)
            text = json.dumps(run.sealed, sort_keys=True).encode('utf-8')
            run.files[guest_runner.SEAL] = text
            run.seal_sha256 = hashlib.sha256(text).hexdigest()
            if summary.get('socket'):
                host.ledger.append(dict(run_id=run.plan['run_id'], role=run.plan['role'], sealed=True, socket_inodes=[summary['socket']['first']['inode']]))
            if host.active is not None and host.active['run_id'] == run.plan['run_id']:
                host.active = None
        return dict(self._summary(host, run), seal=run.sealed)

    def runner_steps(self, role=None, command=None):
        return [c for c in self.calls if (role is None or c['role'] == role) and (command is None or c['command'] == command)]

    def starts(self):
        return [c for c in self.calls if c['command'] == 'start']
