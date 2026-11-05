#!/usr/bin/env python3
"""Runs on a test guest: starts, watches, stops and seals the fresh processes of one test run. Standard library only.

One subcommand, one JSON document on stdout, like ``guest_agent``. It reports facts and enforces only what cannot wait for
the controller. The rules live here because they must hold when the controller is gone or stale:

  * a fence file that only rises and can only ever close, checked under one lock with the launch, so a replaced controller
    or a session in cleanup cannot start anything;
  * a start carries a single-use grant, minted here and then journaled by the registry. It is timed on this host's elapsed clock from
    the mint, so a delivery cannot outlive the grant whatever this host's wall clock says, and it is burned under the host lock, so
    a replay does nothing. Both are checked on arrival, after the slow checks, before any process exists and again once it does;
  * one active run per host, and a run directory created exclusively, so nothing overlaps or overwrites;
  * a supervisor with an absolute bound, so a workload stops on time with no controller left;
  * process identity is boot id, pid and kernel start time, so a reused pid is never mistaken for ours or signalled;
  * sealing hashes every file and makes the tree read-only, including for an interrupted run;
  * the supervisor keeps what the kernel counted against its own unit, so an OOM kill can be told from any other SIGKILL.

Linux facts come from /proc, ``tc`` and systemd. The macOS branches exist only so local fixtures can run real processes on a
developer machine, and they do not provide socket drop counters. Neither path has run on a real Droplet yet.
"""
import argparse
import contextlib
import ctypes
import errno
import fcntl
import functools
import hashlib
import json
import os
import pathlib
import re
import resource
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time

SCHEMA = 'omega.do-session.run-observation/1'
PLAN_SCHEMA = 'omega.do-session.run-plan/1'
DEFAULT_ROOT = '/home/deploy/omega-results/do-runs'
SYSTEMD, PROCESS_GROUP = 'systemd', 'process_group'
LOCK_WAIT_S = 20.0
HANDSHAKE_WAIT_S = 15.0
SUPERVISOR_POLL_S = 0.2
SOCKET_SAMPLE_S = 1.0
MAX_FILE_BYTES = 8 * 1024 ** 3      # per process; a runaway log must not take the disk from the evidence next to it
LAUNCH_CLOCK_TOLERANCE_S = 1.0      # readiness proved the guest clock within this of true time
GRANT_COMMIT_SLACK_S = 1.0          # registry.GUEST_COMMIT_SLACK_S: a process seen alive later than this past its window is stopped at once
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$')
GRANT_ID = re.compile(r'^[0-9a-f]{32}$')
SEAL = 'seal.json'
OOM_EVIDENCE = 'process-oom.json'
OOM_SCHEMA = 'omega.do-session.process-oom/2'
WORKLOAD_LEAF, SUPERVISION_LEAF = 'workload', 'supervision'     # names cgroup-v2.rst promises no interface file will start or end with, or does not use
CGROUP_ROOT = '/sys/fs/cgroup'


class Refused(Exception):
    def __init__(self, code, detail=''):
        super().__init__(code)
        self.code = code
        self.detail = detail


# ---- small durable writes -------------------------------------------------------------------------

def _fsync_directory(path):
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, document):
    path = pathlib.Path(path)
    temporary = path.with_name(path.name + '.tmp%d' % os.getpid())
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(document, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))
    _fsync_directory(path.parent)


def create_json(path, document):
    """Create-only. An existing file is evidence and is never replaced."""
    descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(document, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(pathlib.Path(path).parent)


def read_json(path, default=None):
    try:
        with open(str(path), encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def read_ndjson(path):
    rows = []
    try:
        with open(str(path), encoding='utf-8') as handle:
            for line in handle:
                with contextlib.suppress(ValueError):
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def sha256_file(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(argv, timeout=15, env=None):
    """A missing tool is a reported fact: ``None`` for the exit status, and the controller rejects what it cannot see."""
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, ''
    return result.returncode, result.stdout.decode('utf-8', 'replace')


# ---- process and socket identity ------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def boot_id():
    """Cached, because a process cannot outlive the boot it started in, and this is read on every identity comparison."""
    try:
        return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        code, out = run_command(['sysctl', '-n', 'kern.boottime'])
        return out.split(',')[0].strip() if code == 0 and out else None


def process_start_id(pid, proc_root='/proc'):
    """The kernel's start time for this pid, or None. A zombie has exited, so it counts as gone."""
    try:
        with open('%s/%d/stat' % (proc_root, pid), encoding='utf-8', errors='replace') as handle:
            fields = handle.read().rsplit(')', 1)[1].split()
        return None if fields[0] in ('Z', 'X') else 'ticks:' + fields[19]
    except (OSError, IndexError):
        pass
    return None if os.path.isdir(proc_root) else _darwin_start_id(pid)


def _darwin_start_id(pid):
    """Development only: libproc's proc_bsdinfo, because ``ps`` is setuid and cannot run inside a sandboxed test."""
    info = ctypes.create_string_buffer(136)
    try:
        size = ctypes.CDLL('/usr/lib/libproc.dylib').proc_pidinfo(pid, 3, ctypes.c_uint64(0), info, 136)
    except OSError:
        return None
    if size != 136 or struct.unpack_from('<I', info.raw, 4)[0] == 5:     # 3 is PROC_PIDTBSDINFO, status 5 is SZOMB
        return None
    return 'bsd:%d.%06d' % struct.unpack_from('<QQ', info.raw, 120)


def identity_of(pid):
    return dict(pid=pid, start_id=process_start_id(pid), boot_id=boot_id())


def same_process(identity):
    """True only when this exact process still runs: same boot, pid and start time. Start ticks can repeat after a reboot."""
    if not identity or not identity.get('start_id') or not identity.get('boot_id') or identity['boot_id'] != boot_id():
        return False
    return process_start_id(identity['pid']) == identity['start_id']


def parse_proc_net_udp(text, port):
    """Rows of /proc/net/udp bound to ``port``: inode and the kernel's drop counter for that one socket."""
    rows = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 13 or ':' not in fields[1]:
            continue
        with contextlib.suppress(ValueError):
            if int(fields[1].rsplit(':', 1)[1], 16) == port:
                rows.append(dict(local=fields[1], inode=fields[9], drops=int(fields[12]), rx_queue=int(fields[4].split(':')[1], 16)))
    return rows


def socket_inodes_of(pid, proc_root='/proc'):
    found = set()
    try:
        names = os.listdir('%s/%d/fd' % (proc_root, pid))
    except OSError:
        return found
    for name in names:
        with contextlib.suppress(OSError):
            target = os.readlink('%s/%d/fd/%s' % (proc_root, pid, name))
            if target.startswith('socket:['):
                found.add(target[8:-1])
    return found


def observe_socket(pid, port, proc_root='/proc'):
    """The UDP socket this exact process owns on ``port``, or None. Host-wide counters are never substituted."""
    if os.path.isdir(proc_root):
        rows = []
        for table in ('net/udp', 'net/udp6'):
            with contextlib.suppress(OSError):
                rows += parse_proc_net_udp(pathlib.Path(proc_root, table).read_text(), port)
        owned = socket_inodes_of(pid, proc_root)
        mine = [row for row in rows if row['inode'] in owned]
        return dict(mine[0], counter_source='proc_net_udp') if mine else None
    code, out = run_command(['lsof', '-nP', '-a', '-p', str(pid), '-iUDP:%d' % port, '-Ffd'])
    device = next((line[1:] for line in out.splitlines() if line.startswith('d')), None) if code == 0 else None
    # lsof's device is a reusable kernel address, so on this development path only the owning process makes it unique.
    return dict(local='udp:%d' % port, inode='lsof:%d:%s' % (pid, device), drops=None, rx_queue=None, counter_source='unavailable_on_platform') if device else None


def port_free(protocol, port):
    kind = socket.SOCK_DGRAM if protocol == 'udp' else socket.SOCK_STREAM
    probe = socket.socket(socket.AF_INET, kind)
    try:
        if kind == socket.SOCK_STREAM:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # TIME_WAIT is not a leftover listener
        probe.bind(('0.0.0.0', port))
        return True
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, errno.EACCES):
            return False
        raise
    finally:
        probe.close()


def process_table():
    """Lines of ``pid args``, or None. ``pgrep`` is a development fallback for a sandbox that refuses the setuid ``ps``."""
    code, out = run_command(['ps', '-axww', '-o', 'pid=,args='])
    if code != 0 and not os.path.isdir('/proc'):
        code, out = run_command(['pgrep', '-lf', '.'])
    return out.splitlines() if code == 0 else None


def leftover_processes(paths):
    """Anything running from these exact paths, whoever started it. ``None`` means the process table could not be read.

    Only the program position counts (argv[0], or argv[1] under an interpreter), because this runner's own command line
    carries the plan, and with it every one of these paths.
    """
    table = process_table()
    if table is None:
        return None
    found = []
    for line in table:
        fields = line.split()
        if len(fields) >= 2 and fields[0].isdigit() and int(fields[0]) != os.getpid():
            for path in paths:
                if path in fields[1:3]:
                    found.append(dict(path=path, pid=int(fields[0])))
    return found


def impairment_facts(interface=None):
    """Every qdisc on the host and the filters on the routed interface. Without ``tc``, nothing is known."""
    if shutil.which('tc') is None:
        return dict(available=False)
    code, out = run_command(['tc', '-j', 'qdisc', 'show'])
    try:
        qdiscs = json.loads(out) if code == 0 else None
    except ValueError:
        qdiscs = None
    if not isinstance(qdiscs, list):
        return dict(available=False, rc=code)
    if interface is None:
        route_code, route = run_command(['ip', '-j', 'route', 'show', 'default'])
        with contextlib.suppress(ValueError, IndexError, KeyError, TypeError):
            interface = json.loads(route)[0]['dev'] if route_code == 0 else None
    filters = None
    if interface:
        filter_code, filter_out = run_command(['tc', '-j', 'filter', 'show', 'dev', interface])
        with contextlib.suppress(ValueError):
            filters = len(json.loads(filter_out or '[]')) if filter_code == 0 else None
    return dict(available=True, interface=interface, qdisc_kinds=sorted({q.get('kind') for q in qdiscs if isinstance(q, dict)}), filter_count=filters)


def unit_names():
    code, out = run_command(['systemctl', 'list-units', '--all', '--plain', '--no-legend', '--no-pager', 'omega-*'])
    if code is None:
        return None
    return [line.split()[0] for line in out.splitlines() if line.split()]


def unit_facts(unit):
    code, out = run_command(['systemctl', 'show', unit, '--property=InvocationID,MainPID,ActiveState,SubState,Result,NRestarts'])
    if code != 0:
        return None
    return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)


def source_facts(path):
    if not pathlib.Path(path, '.git').exists():
        return None
    code, head = run_command(['git', '-C', str(path), 'rev-parse', 'HEAD'])
    dirty_code, porcelain = run_command(['git', '-C', str(path), 'status', '--porcelain'])
    return dict(head=head.strip() if code == 0 else None, clean=dirty_code == 0 and not porcelain.strip())


# ---- the host's control directory -----------------------------------------------------------------

def grant_clock_ns():
    """Elapsed time that includes suspension where the kernel can say so, shared by every process of this boot."""
    return time.clock_gettime_ns(getattr(time, 'CLOCK_BOOTTIME', time.CLOCK_MONOTONIC))     # not time.monotonic: on macOS each process counts from its own start


class Host:
    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.control = self.root / 'control'
        self.runs = self.root / 'runs'
        self.control.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.runs.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.fence_path = self.control / 'fence.json'
        self.active_path = self.control / 'active.json'
        self.ledger_path = self.control / 'ledger.ndjson'

    @contextlib.contextmanager
    def locked(self):
        with (self.control / 'lock').open('a') as handle:
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise Refused('lock_timeout', 'another runner holds the host lock')
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def fence(self):
        return read_json(self.fence_path)

    def grant_path(self, grant_id, suffix='.json'):
        if not isinstance(grant_id, str) or not GRANT_ID.match(grant_id):
            raise Refused('grant_unknown', 'not a grant identity')
        return self.control / 'grants' / (grant_id + suffix)

    def consumed_grants(self):
        try:
            return sorted(path.stem for path in (self.control / 'grants').glob('*.consumed'))
        except OSError:
            return []

    def active(self):
        return read_json(self.active_path)

    def ledger(self):
        return read_ndjson(self.ledger_path)

    def append_ledger(self, entry):
        with self.ledger_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, sort_keys=True) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def run_dir(self, run_id, role):
        if not isinstance(run_id, str) or not SAFE_NAME.match(run_id):
            raise Refused('bad_request', 'unsafe run id')
        return self.runs / run_id / role

    def require_token(self, session_id, token):
        fence = self.fence()
        if fence is None or fence.get('session_id') != session_id:
            raise Refused('not_fenced', 'this host has no fence for the session')
        if token != fence.get('token'):
            raise Refused('stale_fence', 'fence is at %s, request carries %s' % (fence.get('token'), token))
        return fence

    def require_open(self, session_id, token):
        """Authority to start something. Stopping and sealing need only the token, because they must work through cleanup."""
        fence = self.require_token(session_id, token)
        if fence.get('closed'):
            raise Refused('session_closed', 'no process may start: %s' % fence['closed'])
        return fence

    def require_current_token(self, plan, token):
        """A run directory with no plan names no session, and the fence still decides."""
        if plan:
            return self.require_token(plan['session_id'], token)
        fence = self.fence()
        if fence is not None and token != fence.get('token'):
            raise Refused('stale_fence', 'fence is at %s, request carries %s' % (fence.get('token'), token))
        return fence


def sampler_tail(path):
    """Row count and last timestamp, without parsing every row: a status poll must stay cheap on the host being measured."""
    rows, last = 0, None
    try:
        with open(str(path), encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if line.endswith('\n') and line.startswith('{'):
                    rows += 1
                    last = line
    except OSError:
        pass
    if last is not None:
        with contextlib.suppress(ValueError):
            return rows, json.loads(last).get('mono_s')
    return rows, None


def run_summary(run_dir):
    plan = read_json(run_dir / 'plan.json') or {}
    identity = read_json(run_dir / 'identity.json')
    processes = {}
    for name, item in ((identity or {}).get('processes') or {}).items():
        processes[name] = dict(item, alive=same_process(item))
    supervisor = (identity or {}).get('supervisor')
    supervisor_alive = same_process(supervisor)
    # After the liveness reads: a supervisor seen gone had already written its result, so gone with no result really means lost.
    result = read_json(run_dir / 'result.json')
    stopping = read_json(run_dir / 'stopping.json')
    seal = read_json(run_dir / SEAL)
    socket_rows = read_ndjson(run_dir / 'sockets.ndjson')
    sampler_rows, sampler_last = sampler_tail(run_dir / 'sampler.ndjson')
    summary = dict(run_id=plan.get('run_id') or run_dir.parent.name, role=plan.get('role') or run_dir.name, has_plan=bool(plan), session_id=plan.get('session_id'),
                   fencing_token=plan.get('fencing_token'), supervisor=dict(supervisor, alive=supervisor_alive) if supervisor else None,
                   invocation_id=(identity or {}).get('invocation_id'), processes=processes, result=result, stopping=stopping, sealed=seal is not None,
                   seal_sha256=sha256_file(run_dir / SEAL) if seal is not None else None,
                   socket=dict(first=socket_rows[0], last=socket_rows[-1], samples=len(socket_rows)) if socket_rows else None,
                   sampler=dict(rows=sampler_rows, last_mono_s=sampler_last))
    unit = plan.get('unit')
    if unit and plan.get('unit_mode') == SYSTEMD:
        summary['unit'] = unit_facts(unit)
    return summary


def running_anything(summary):
    return bool((summary.get('supervisor') or {}).get('alive')) or any(p['alive'] for p in summary['processes'].values())


def inventory(host, session_id=None):
    runs = []
    if host.runs.is_dir():
        for run_dir in sorted(host.runs.iterdir()):
            for role_dir in sorted(run_dir.iterdir()) if run_dir.is_dir() else ():
                runs.append(run_summary(role_dir))
    return runs


# ---- commands -------------------------------------------------------------------------------------

def cmd_fence(args, host):
    """Raise the fence, and only ever raise it. Whatever started before this returns is in the inventory.

    ``--close`` is how a live controller carries a revocation here: the registry cannot reach a guest, so an abort committed
    while no controller is listening waits out the grants it found. Closing never reopens, under any token.
    """
    with host.locked():
        fence = host.fence()
        if fence is not None and fence.get('session_id') != args.session:
            raise Refused('foreign_session', 'this host is fenced by another session')
        if fence is not None and args.token < fence.get('token'):
            raise Refused('stale_fence', 'fence is at %s' % fence.get('token'))
        raised = fence is None or args.token > fence.get('token')
        closed = (fence or {}).get('closed') or getattr(args, 'close', None)
        if raised or closed != (fence or {}).get('closed'):
            atomic_json(host.fence_path, dict(session_id=args.session, token=args.token, closed=closed))
        return dict(token=args.token, raised=raised, closed=closed, active=host.active(), runs=inventory(host), grants_consumed=host.consumed_grants())


def cmd_grant_prepare(args, host):
    """Mint one start's identity and start its clock, before the registry has been asked. See ``registry.authorize_guest_action``."""
    with host.locked():
        host.require_open(args.session, args.token)
        grant_id = secrets.token_hex(16)
        (host.control / 'grants').mkdir(exist_ok=True, mode=0o750)
        create_json(host.grant_path(grant_id), dict(grant_id=grant_id, session_id=args.session, token=args.token, boot_id=boot_id(), clock_ns=grant_clock_ns()))
        return dict(grant_id=grant_id, token=args.token)


def _grant_elapsed_s(record):
    """Seconds since this host minted the grant. A record from another boot has no elapsed time that means anything, so it never fits."""
    if not record or record.get('boot_id') != boot_id():
        return float('inf')
    return (grant_clock_ns() - record['clock_ns']) / 1e9


def _claim_grant(host, plan):
    """Under the host lock. Burned before anything else is judged: this is the one moment this delivery becomes the only use of the grant."""
    grant = plan.get('grant') or {}
    record = read_json(host.grant_path(grant.get('id')))
    if record is None:
        raise Refused('grant_unknown', 'this host never minted that grant')
    if record.get('session_id') != plan['session_id'] or record.get('token') != plan['fencing_token']:
        raise Refused('grant_mismatch', 'that grant belongs to another session or token')
    try:
        create_json(host.grant_path(grant['id'], '.consumed'), dict(run_id=plan['run_id'], role=plan['role'], clock_ns=grant_clock_ns(), wall=time.time()))
    except FileExistsError:
        raise Refused('grant_replayed', 'that grant was already used')


def _file_facts(path):
    try:
        info = os.stat(str(path))
    except OSError:
        return dict(path=str(path), present=False)
    return dict(path=str(path), present=True, sha256=sha256_file(path), size=info.st_size, executable=bool(info.st_mode & 0o111))


def host_facts(host, plan):
    ports = {'%s/%d' % (item['protocol'], item['port']): port_free(item['protocol'], item['port']) for item in plan['ports']}
    return dict(boot_id=boot_id(), files=[_file_facts(item['path']) for item in plan['verify_files']], ports_free=ports,
                leftovers=leftover_processes([item['path'] for item in plan['verify_files'] if item.get('role') in ('program', 'support')]),
                impairment=impairment_facts(plan.get('interface')), units=unit_names(), active=host.active(), fence=host.fence(),
                ledger=host.ledger(), run_dir_exists=host.run_dir(plan['run_id'], plan['role']).parent.exists(),
                runner_sha256=sha256_file(__file__), source=source_facts(plan['source_dir']) if plan.get('source_dir') else None,
                disk_free_bytes=shutil.disk_usage(str(host.root)).free, wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())


def cmd_preflight(args, host):
    return host_facts(host, load_plan(args.plan_json))


def load_plan(text):
    try:
        plan = json.loads(text)
    except ValueError:
        raise Refused('bad_request', 'the plan is not JSON')
    if not isinstance(plan, dict) or plan.get('schema') != PLAN_SCHEMA:
        raise Refused('bad_request', 'unknown plan schema')
    if plan.get('role') not in ('game', 'bot'):
        raise Refused('bad_request', 'unknown role')
    return plan


def _require_launch_window(host, plan):
    """A grant is a few seconds, so a delayed request expires here. Either clock can refuse, and only the elapsed one is what expiry rests on."""
    grant = plan.get('grant') or {}
    if _grant_elapsed_s(read_json(host.grant_path(grant.get('id')))) > grant.get('ttl_s', 0):
        raise Refused('launch_window_closed', 'this start request is past its grant')
    if time.time() > plan['launch_not_after_wall'] + LAUNCH_CLOCK_TOLERANCE_S:
        raise Refused('launch_window_closed', 'this start request is past its authorization')


def _remaining_bound(plan):
    """How long a workload started right now may run: never past the absolute stop, and refused if the whole workload no longer fits."""
    remaining = min(plan['bound_s'], plan['stop_by_wall'] - time.time())
    if remaining <= 0 or remaining < plan.get('minimum_bound_s', 0):
        raise Refused('launch_window_closed', 'only %.1f s of the grant is left for this workload' % remaining)
    return remaining


def _require_launchable(host, plan):
    """The last look before a process exists. Each of these can have changed since the controller's preflight."""
    _require_launch_window(host, plan)
    if host.active() is not None:
        raise Refused('overlap', 'run %s is active on this host' % host.active().get('run_id'))
    facts = host_facts(host, plan)
    for item, expected in zip(facts['files'], plan['verify_files']):
        if item.get('sha256') != expected['sha256']:
            raise Refused('hash_mismatch', item['path'])
    if facts['leftovers'] is None:
        raise Refused('process_state_unknown', 'the process table could not be read')
    if facts['leftovers']:
        raise Refused('leftover_process', json.dumps(facts['leftovers']))
    busy = sorted(name for name, free in facts['ports_free'].items() if not free)
    if busy:
        raise Refused('port_busy', ', '.join(busy))
    # Hashing and the process table take real time, and the window has to hold when something actually starts.
    _require_launch_window(host, plan)
    _remaining_bound(plan)


def cmd_start(args, host):
    plan = load_plan(args.plan_json)
    run_dir = host.run_dir(plan['run_id'], plan['role'])
    with host.locked():
        host.require_open(plan['session_id'], plan['fencing_token'])
        _claim_grant(host, plan)
        _require_launchable(host, plan)
        run_dir.parent.mkdir(exist_ok=True, mode=0o750)
        try:
            run_dir.mkdir(mode=0o750)
        except FileExistsError:
            raise Refused('duplicate_run_dir', str(run_dir))
        create_json(run_dir / 'plan.json', plan)
        atomic_json(host.active_path, dict(run_id=plan['run_id'], role=plan['role'], session_id=plan['session_id'], fencing_token=plan['fencing_token']))
        launch_supervisor(host, run_dir, plan)
        identity = _await_handshake(run_dir)
        host.append_ledger(dict(run_id=plan['run_id'], role=plan['role'], supervisor=identity['supervisor'], invocation_id=identity.get('invocation_id'),
                                processes=identity['processes']))
        return run_summary(run_dir)


# ---- process-attributable OOM evidence ------------------------------------------------------------

def cgroup_of(pid, proc_root='/proc'):
    """This process's cgroup v2 path, from the ``0::$PATH`` line of /proc/<pid>/cgroup. None if it has none, or if that cgroup is gone."""
    try:
        with open('%s/%s/cgroup' % (proc_root, pid), encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('0::'):
                    path = line[3:].strip()
                    return path if path.startswith('/') and not path.endswith(' (deleted)') else None
    except OSError:
        pass
    return None


def cgroup_reading(cgroup):
    """The kernel's OOM counters for one cgroup's own processes, and who is in it now. Zombies are not listed in cgroup.procs. None if either file cannot be read: a missing value is never zero."""
    root = CGROUP_ROOT + cgroup
    try:
        with open(root + '/memory.events.local', encoding='utf-8') as handle:
            events = {key: int(value) for key, value in (line.split() for line in handle if line.strip())}
        with open(root + '/cgroup.procs', encoding='utf-8') as handle:
            procs = sorted(int(line) for line in handle if line.strip())
    except (OSError, ValueError):
        return None
    if 'oom_kill' not in events:
        return None
    return dict(mono_ns=time.monotonic_ns(), wall_ns=time.time_ns(), oom_kill=events['oom_kill'], oom_group_kill=events.get('oom_group_kill'), oom=events.get('oom'), procs=procs)


def _unit_oom_kill(cgroup):
    """The unit's whole count, for a report to say a kill happened elsewhere in it. It attributes nothing: it names no process, and that is what the leaf is for."""
    try:
        with open(CGROUP_ROOT + cgroup + '/memory.events', encoding='utf-8') as handle:
            events = {key: int(value) for key, value in (line.split() for line in handle if line.strip())}
    except (OSError, ValueError):
        return None
    return events.get('oom_kill')


def _cgroup_mkdir(cgroup):
    """Create-only: a leaf this supervisor did not just make has a count nobody here can vouch for."""
    os.mkdir(CGROUP_ROOT + cgroup)


def _cgroup_write(cgroup, name, text):
    descriptor = os.open(CGROUP_ROOT + cgroup + '/' + name, os.O_WRONLY)
    try:
        os.write(descriptor, text.encode('ascii'))
    finally:
        os.close(descriptor)


def isolate_workload(unit_cgroup):
    """Inside the run's own delegated unit: the supervisor moves to a leaf of its own, the memory controller opens for the subtree, and a new empty leaf waits for the workload. Returns (workload, supervision). Raises OSError.

    The order is the kernel's: a cgroup with processes of its own cannot enable a domain controller for its children (cgroup-v2.rst, 'No Internal Process Constraint'). The supervisor is the only process in the unit at this point,
    nothing has been spawned, and the unit runs no ExecStartPost and the like, so systemd puts no ``.control`` here (CGROUP_DELEGATION.md).
    """
    workload, supervision = unit_cgroup + '/' + WORKLOAD_LEAF, unit_cgroup + '/' + SUPERVISION_LEAF
    _cgroup_mkdir(supervision)
    _cgroup_write(supervision, 'cgroup.procs', str(os.getpid()))
    _cgroup_write(unit_cgroup, 'cgroup.subtree_control', '+memory')
    _cgroup_mkdir(workload)
    return workload, supervision


def _enter_cgroup(cgroup):
    """In the forked child, before exec, so the workload has never been anywhere else. A failure leaves it where it was, and ``OomWatch.bind`` writes down where that was: a run does not stand or fall on its evidence."""
    with contextlib.suppress(OSError):
        _cgroup_write(cgroup, 'cgroup.procs', str(os.getpid()))


class OomWatch:
    """What the kernel counted against the workload's own cgroup, and nobody else's. Read by the supervisor, which owns that cgroup, while the unit still exists.

    ``__oom_kill_process`` raises ``MEMCG_OOM_KILL`` on the memory cgroup of the victim's mm owner and only then sends SIGKILL ('task reaper must see this'), so a read after reaping cannot miss the workload's own kill. The same ordering means a
    kill counted for the whole unit says nothing about who was chosen: the sampler can be counted and not yet dead at any read, and no membership sample or later signal can undo that. So the unit's count names nobody, and this does not use it.

    ``memory.events.local`` of a leaf holding one process does name it. ``isolate_workload`` makes that leaf, through the ``Delegate=memory`` on the unit, under the uid the unit already runs as. No write to cgroupfs happens outside the unit's own subtree, and no new
    privilege is involved. Where any of it is refused, the workload runs anyway, in the supervisor's leaf or the unit, and the record says unavailable. Outside a unit of the run's own there is no boundary to delegate, and it says that too. ``capacity_scorer`` decides what the record proves.
    Collecting this can never stop a run from stopping: it records what went wrong and carries on.
    """

    def __init__(self, plan):
        self.unit_cgroup = None
        self.workload = None
        self.document = dict(schema=OOM_SCHEMA, source='cgroup v2 memory.events.local of a leaf holding only the primary process', run_id=plan.get('run_id'), role=plan.get('role'), unit=plan.get('unit'), unit_mode=plan.get('unit_mode'), available=False, unavailable=None)
        self._guarded(self._begin, plan)

    def _guarded(self, step, *arguments):
        try:
            step(*arguments)
        except Exception as error:     # evidence must not stand between a run and its stop
            self.workload = None
            self.document.update(available=False, unavailable='%s failed: %s' % (step.__name__.strip('_'), type(error).__name__))

    def _unavailable(self, why):
        self.workload = None
        self.document.update(available=False, unavailable=why)

    def _begin(self, plan):
        if plan.get('unit_mode') != SYSTEMD or not plan.get('unit'):
            return self._unavailable('this run has no unit of its own, so no cgroup boundary is its alone')
        cgroup = cgroup_of(os.getpid())
        if cgroup is None:
            return self._unavailable('no cgroup v2 membership')
        if pathlib.PurePosixPath(cgroup).name != plan['unit']:
            return self._unavailable('the supervisor is in %s, not in the run unit' % cgroup)
        try:
            workload, supervision = isolate_workload(cgroup)
        except OSError as error:
            return self._unavailable('the unit gave no leaf of the workload\'s own under %s: %s errno %s' % (cgroup, type(error).__name__, error.errno))
        baseline = cgroup_reading(workload)
        if baseline is None:
            return self._unavailable('memory.events.local or cgroup.procs cannot be read for %s' % workload)
        self.unit_cgroup, self.workload = cgroup, workload
        self.document.update(available=True, cgroup=cgroup, leaf=workload, supervision=supervision, baseline=self._reading(workload, baseline))
        return None

    def _reading(self, workload, reading=None):
        reading = reading if reading is not None else cgroup_reading(workload)
        return None if reading is None else dict(reading, unit_oom_kill=_unit_oom_kill(self.unit_cgroup))

    def bind(self, supervisor, processes, invocation_id):
        """Who is where, once they all exist. Named by the kernel's own /proc, after the fact, so a workload that did not reach its leaf is on record as elsewhere."""
        def step():
            if self.workload is None:
                return
            identity = lambda item: {key: item.get(key) for key in ('pid', 'start_id', 'boot_id')}
            self.document.update(supervisor=identity(supervisor), invocation_id=invocation_id, processes={name: identity(item) for name, item in processes.items()},
                                 member_cgroups=dict({name: cgroup_of(item['pid']) for name, item in processes.items()}, supervisor=cgroup_of(os.getpid())), bound=self._reading(self.workload))
        self._guarded(step)

    def primary_exited(self, primary, facts, alive):
        """Right after the reap and before any signal from here. The workload's kill, if there was one, is already counted."""
        def step():
            if self.workload is not None:
                self.document['primary_exit'] = dict(self._reading(self.workload) or dict(unreadable=True), primary=primary, returncode=facts.get('returncode'), signal=facts.get('signal'), alive=sorted(alive))
        self._guarded(step)

    def finish(self, path):
        def step():
            if self.workload is not None:
                self.document['final'] = self._reading(self.workload)
        self._guarded(step)
        with contextlib.suppress(OSError):
            atomic_json(path, self.document)


def launch_supervisor(host, run_dir, plan):
    command = [sys.executable, os.path.abspath(__file__), '--root', str(host.root), 'supervise', '--run-dir', str(run_dir)]
    if plan['unit_mode'] == SYSTEMD:
        # The unit is the second bound, for a supervisor that dies. KillMode takes everything in its cgroup with it.
        # OOMPolicy=continue: the default stops the whole unit when one process is OOM-killed, which would stop the supervisor before it has reaped the victim and read the kernel's count.
        # Delegate=memory: the supervisor may put the workload in a leaf of its own, the one place the kernel's OOM count names a process. KillMode and RuntimeMaxSec still cover the whole subtree, and systemd trims it when the unit ends.
        limit = plan['bound_s'] + plan['stop_grace_s'] + 5
        code, _ = run_command(['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=' + plan['unit'], '--uid=' + str(os.getuid()),
                               '--property=RuntimeMaxSec=%d' % max(1, int(limit)), '--property=KillMode=control-group', '--property=TimeoutStopSec=15',
                               '--property=Restart=no', '--property=LimitCORE=0', '--property=LimitNOFILE=65536', '--property=CPUAccounting=yes',
                               '--property=MemoryAccounting=yes', '--property=OOMPolicy=continue', '--property=Delegate=memory'] + command, timeout=20)
        if code != 0:
            raise Refused('unit_start_failed', 'systemd-run exited %s' % code)
        return
    if plan['unit_mode'] != PROCESS_GROUP:
        raise Refused('bad_request', 'unknown unit mode')
    with (run_dir / 'supervisor.log').open('ab') as log:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)


def _await_handshake(run_dir):
    deadline = time.monotonic() + HANDSHAKE_WAIT_S
    while time.monotonic() < deadline:
        identity = read_json(run_dir / 'identity.json')
        if identity is not None:
            return identity
        result = read_json(run_dir / 'result.json')
        if result is not None:
            if result.get('refused'):
                raise Refused(result['refused'], result.get('stop_reason'))
            raise Refused('launch_failed', result.get('stop_reason') or 'the supervisor ended before identifying its processes')
        time.sleep(0.05)
    raise Refused('launch_unconfirmed', 'no identity from the supervisor')


def sampler_socket_inodes(path):
    """Every socket an --identity sampler saw this run's processes own, so a later run can be held to them."""
    found = set()
    for row in read_ndjson(path):
        for facts in (row.get('procs') or {}).values():
            for item in (facts.get('sockets') or ()) if isinstance(facts, dict) else ():
                if item.get('inode'):
                    found.add(item['inode'])
    return found


def cmd_clock(args, host):
    """Nothing else: the controller brackets this call, and any extra work here would widen its uncertainty."""
    wall_ns = time.time_ns()
    return dict(wall_ns=wall_ns, monotonic_ns=time.monotonic_ns(), boot_id=boot_id())


def cmd_status(args, host):
    return run_summary(_existing_run_dir(host, args.run_id, args.role))


def _existing_run_dir(host, run_id, role):
    run_dir = host.run_dir(run_id, role)
    if not run_dir.is_dir():
        raise Refused('unknown_run', str(run_dir))
    return run_dir


def cmd_inspect(args, host):
    return dict(fence=host.fence(), active=host.active(), runs=inventory(host), boot_id=boot_id(), ledger=host.ledger(), grants_consumed=host.consumed_grants())


def _signal_identity(identity, signum):
    """Never a process that merely has the same number. A mismatch is reported, not signalled."""
    if not same_process(identity):
        return False
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(identity['pid'], signum)
    return True


def cmd_stop(args, host):
    """Ask the supervisor first. If it is gone, signal each process only after proving it is still that process."""
    run_dir = _existing_run_dir(host, args.run_id, args.role)
    plan = read_json(run_dir / 'plan.json') or {}
    with host.locked():
        host.require_current_token(plan, args.token)
    if not (run_dir / SEAL).exists():
        with contextlib.suppress(FileExistsError):
            create_json(run_dir / 'stop.request', dict(reason=args.reason, wall=time.time()))
    started = time.monotonic()
    deadline = started + args.wait_s
    escalated = False
    while time.monotonic() < deadline:
        summary = run_summary(run_dir)
        # A start that died before the handshake may have left a supervisor about to identify itself, so wait that out.
        unidentified = not summary['supervisor'] and not summary['result']
        if not running_anything(summary) and not (unidentified and plan and time.monotonic() - started < HANDSHAKE_WAIT_S):
            return dict(summary, stopped=True, escalated=escalated)
        if not (summary.get('supervisor') or {}).get('alive') and summary['processes']:
            escalated = True
            for item in summary['processes'].values():
                _signal_identity(item, signal.SIGKILL)
        time.sleep(0.05)
    summary = run_summary(run_dir)
    if plan.get('unit_mode') == SYSTEMD and plan.get('unit'):
        run_command(['sudo', '-n', 'systemctl', 'kill', '--signal=SIGKILL', plan['unit']], timeout=10)
    return dict(summary, stopped=not running_anything(summary), escalated=escalated)


def cmd_seal(args, host):
    """Hash everything and make it read-only. An interrupted run seals too: its bytes are evidence, whatever they hold."""
    run_dir = _existing_run_dir(host, args.run_id, args.role)
    with host.locked():
        plan = read_json(run_dir / 'plan.json') or {}
        host.require_current_token(plan, args.token)
        seal_path = run_dir / SEAL
        if not seal_path.exists():
            summary = run_summary(run_dir)
            if running_anything(summary):
                raise Refused('still_running', 'stop the run first')
            after = host_facts(host, plan) if plan else {}
            final = dict(sealed_by_token=args.token, interrupted=args.interrupted, wall_ns=time.time_ns(), boot_id=boot_id(), ports_free=after.get('ports_free'),
                         leftovers=after.get('leftovers'), impairment=after.get('impairment'), units=after.get('units'))
            if not (run_dir / 'final.json').exists():
                create_json(run_dir / 'final.json', final)
            files = []
            for path in sorted(p for p in run_dir.rglob('*') if p.is_file() and p.name != SEAL):
                files.append(dict(path=str(path.relative_to(run_dir)), sha256=sha256_file(path), size=path.stat().st_size))
            sockets = read_ndjson(run_dir / 'sockets.ndjson')
            inodes = {row['inode'] for row in sockets if row.get('inode')} | sampler_socket_inodes(run_dir / 'sampler.ndjson')
            host.append_ledger(dict(run_id=args.run_id, role=args.role, sealed=True, socket_inodes=sorted(inodes)))
            create_json(seal_path, dict(schema=SCHEMA, run_id=args.run_id, role=args.role, interrupted=args.interrupted, final=final, files=files,
                                        result=summary['result'], identity=read_json(run_dir / 'identity.json')))
        # Also after a crash between the seal and these modes: a sealed tree is read-only however it got here.
        for path in run_dir.rglob('*'):
            os.chmod(str(path), 0o550 if path.is_dir() else 0o440)
        os.chmod(str(run_dir), 0o550)
        active = host.active()
        if active is not None and active.get('run_id') == args.run_id and active.get('role') == args.role:
            os.unlink(str(host.active_path))
            _fsync_directory(host.control)
        return dict(run_summary(run_dir), seal=read_json(seal_path))


# ---- the supervisor -------------------------------------------------------------------------------

def _child_limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))


def _spawn(spec, run_dir, placeholder, cgroup=None):
    argv = [part.replace('{run_dir}', placeholder) for part in spec['argv']]
    env = dict(os.environ, **{k: v.replace('{run_dir}', placeholder) for k, v in spec.get('env', {}).items()})
    for directory in spec.get('make_dirs', ()):
        pathlib.Path(directory.replace('{run_dir}', placeholder)).mkdir(parents=True, exist_ok=True)
    out = (run_dir / (spec['name'] + '.stdout.log')).open('ab')
    err = (run_dir / (spec['name'] + '.stderr.log')).open('ab')

    def before_exec():
        _child_limits()
        if cgroup is not None:
            _enter_cgroup(cgroup)
    try:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, cwd=str(run_dir), start_new_session=True,
                                close_fds=True, preexec_fn=before_exec)
    finally:
        out.close()
        err.close()


def _exit_facts(code):
    return dict(returncode=code if code >= 0 else None, signal=-code if code < 0 else None)


def _launch_gate(host, run_dir, plan):
    """The very last look, from the process about to create the workload. Scheduling can delay this past anything checked earlier.

    Read without the host lock: the start holds it through the handshake, and if that start died, a fence raised after this
    read finds this directory in its inventory and stops it.
    """
    host.require_open(plan['session_id'], plan['fencing_token'])
    _require_launch_window(host, plan)
    if (run_dir / 'stop.request').exists():
        raise Refused('stop_requested', 'a stop arrived before the workload existed')
    return _remaining_bound(plan)


def _spawned_too_late(host, plan):
    """Asked once the workload exists, because nothing can check the instant between the last look and the fork.

    A fence raised in that instant, or a pause longer than the slack, ends the workload now. What the fence came with named this run.
    """
    grant = plan.get('grant') or {}
    if _grant_elapsed_s(read_json(host.grant_path(grant.get('id')))) > grant.get('ttl_s', 0) + GRANT_COMMIT_SLACK_S:
        return 'launch_refused:grant_outlived_after_spawn'
    try:
        host.require_open(plan['session_id'], plan['fencing_token'])
    except Refused as refused:
        return 'launch_refused:%s_after_spawn' % refused.code
    return None


def cmd_supervise(args, host):
    """Start the workload and the sampler, keep identity and socket facts, and stop everything at the bound, alone if need be."""
    run_dir = pathlib.Path(args.run_dir)
    plan = read_json(run_dir / 'plan.json')
    started_mono = time.monotonic()
    processes = {}
    children = {}
    exits = {}
    stop_reason = None
    polite_stops = {spec['name']: spec['stop_signal'] for spec in plan['processes'] if spec.get('stop_signal') in ('SIGINT', 'SIGTERM')}
    try:
        bound_s = _launch_gate(host, run_dir, plan)
    except Refused as refused:
        atomic_json(run_dir / 'result.json', dict(stop_reason='launch_refused:%s: %s' % (refused.code, refused.detail), refused=refused.code, completed=False, processes={},
                                                  ended_wall=time.time(), elapsed_s=0.0, bound_s=0.0))
        return dict(ok=False)

    def finish(reason):
        atomic_json(run_dir / 'result.json', dict(stop_reason=reason, completed=True, processes=exits, ended_wall=time.time(),
                                                  elapsed_s=time.monotonic() - started_mono, bound_s=bound_s))

    def stop_children(signum):
        for name, child in children.items():
            if name not in exits:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(child.pid, signum)

    def ask_children_to_stop():
        """The polite stop a process declared, so a recorder can finish its footer. SIGKILL still follows after the grace."""
        for name, child in children.items():
            if name not in exits:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(child.pid, getattr(signal, polite_stops.get(name, 'SIGTERM')))

    def reap():
        for name, child in children.items():
            code = child.poll()
            if code is not None and name not in exits:
                exits[name] = dict(_exit_facts(code), elapsed_s=time.monotonic() - started_mono)

    interrupted = []
    signal.signal(signal.SIGTERM, lambda *_: interrupted.append('supervisor_terminated'))
    oom_watch = OomWatch(plan)      # before any child exists, so its count covers their whole lives
    try:
        for spec in plan['processes']:
            child = _spawn(spec, run_dir, str(run_dir), cgroup=oom_watch.workload if spec.get('primary') else None)
            children[spec['name']] = child
            processes[spec['name']] = dict(identity_of(child.pid), path=spec['argv'][0], primary=bool(spec.get('primary')))
        if plan.get('sampler'):
            pids = run_dir / 'sampler.pids'
            pids.write_text(''.join('%s=%d\n' % (name, item['pid']) for name, item in processes.items()))
            child = _spawn(plan['sampler'], run_dir, str(run_dir))
            children['sampler'] = child
            processes['sampler'] = dict(identity_of(child.pid), path=plan['sampler']['argv'][0], primary=False)
    except OSError as error:
        stop_children(signal.SIGKILL)
        finish('spawn_failed:' + type(error).__name__)
        return dict(ok=False)
    supervisor_identity = identity_of(os.getpid())
    atomic_json(run_dir / 'identity.json', dict(supervisor=supervisor_identity, processes=processes, invocation_id=os.environ.get('INVOCATION_ID'),
                                                started_wall=time.time(), bound_s=bound_s, stop_by_wall=plan['stop_by_wall']))
    oom_watch.bind(supervisor_identity, processes, os.environ.get('INVOCATION_ID'))
    primary = next(name for name, item in processes.items() if item['primary'])
    watched_port = plan.get('watch_socket_port')
    next_socket = 0.0
    sampler_exited_early = False
    stop_reason = _spawned_too_late(host, plan)

    while stop_reason is None:
        reap()
        # Nothing has been signalled yet, so a sampler already gone died by itself, even in the same poll as the primary's exit.
        sampler_exited_early = sampler_exited_early or 'sampler' in exits
        if primary in exits:
            stop_reason = 'primary_exited'
            oom_watch.primary_exited(primary, exits[primary], [name for name in children if name not in exits])
            break
        now = time.monotonic()
        if watched_port is not None and now >= next_socket:
            row = observe_socket(processes[primary]['pid'], watched_port)
            if row is not None:     # keep looking until it appears; the controller is waiting on this first row
                next_socket = now + SOCKET_SAMPLE_S
                with (run_dir / 'sockets.ndjson').open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(dict(row, pid=processes[primary]['pid'], start_id=processes[primary]['start_id'], boot_id=processes[primary]['boot_id'], mono_ns=time.monotonic_ns(), wall_ns=time.time_ns()),
                                            sort_keys=True) + '\n')
        request = read_json(run_dir / 'stop.request')
        if request is not None:
            stop_reason = 'stop_requested:' + str(request.get('reason'))
            break
        if interrupted:
            stop_reason = interrupted[0]
            break
        if now - started_mono >= bound_s or time.time() >= plan['stop_by_wall']:
            stop_reason = 'bound_exhausted'
            break
        time.sleep(SUPERVISOR_POLL_S)

    # Before any signal: a sampler seen gone with this file present is winding down, not lost.
    atomic_json(run_dir / 'stopping.json', dict(reason=stop_reason, wall=time.time()))
    if watched_port is not None and primary not in exits:
        row = observe_socket(processes[primary]['pid'], watched_port)
        if row is not None:
            with (run_dir / 'sockets.ndjson').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(dict(row, pid=processes[primary]['pid'], start_id=processes[primary]['start_id'], boot_id=processes[primary]['boot_id'], mono_ns=time.monotonic_ns(), wall_ns=time.time_ns(), final=True),
                                        sort_keys=True) + '\n')
    ask_children_to_stop()
    grace_ends = time.monotonic() + plan['stop_grace_s']
    while time.monotonic() < grace_ends:
        reap()
        if len(exits) == len(children):
            break
        time.sleep(0.05)
    stop_children(signal.SIGKILL)
    while len(exits) < len(children):
        reap()
        time.sleep(0.02)
    escalated = [name for name, item in exits.items() if item.get('signal') == signal.SIGKILL]
    oom_watch.finish(run_dir / OOM_EVIDENCE)
    atomic_json(run_dir / 'result.json', dict(stop_reason=stop_reason, completed=True, processes=exits, ended_wall=time.time(), elapsed_s=time.monotonic() - started_mono,
                                              bound_s=bound_s, sampler_exited_early=sampler_exited_early, killed=escalated))
    return dict(ok=True)


COMMANDS = dict(fence=cmd_fence, grant_prepare=cmd_grant_prepare, preflight=cmd_preflight, start=cmd_start, status=cmd_status, inspect=cmd_inspect, stop=cmd_stop, seal=cmd_seal, supervise=cmd_supervise, clock=cmd_clock)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest='command', required=True)
    fence = sub.add_parser('fence')
    fence.add_argument('--session', required=True)
    fence.add_argument('--token', type=int, required=True)
    fence.add_argument('--close', help='no process may start on this host again; the reason')
    prepare = sub.add_parser('grant_prepare')
    prepare.add_argument('--session', required=True)
    prepare.add_argument('--token', type=int, required=True)
    for name in ('preflight', 'start'):
        sub.add_parser(name).add_argument('--plan-json', required=True)
    sub.add_parser('inspect')
    sub.add_parser('clock')
    status = sub.add_parser('status')
    status.add_argument('--run-id', required=True)
    status.add_argument('--role', required=True, choices=('game', 'bot'))
    stop = sub.add_parser('stop')
    stop.add_argument('--run-id', required=True)
    stop.add_argument('--role', required=True, choices=('game', 'bot'))
    stop.add_argument('--token', type=int, required=True)
    stop.add_argument('--reason', required=True)
    stop.add_argument('--wait-s', type=float, default=20.0)
    seal = sub.add_parser('seal')
    seal.add_argument('--run-id', required=True)
    seal.add_argument('--role', required=True, choices=('game', 'bot'))
    seal.add_argument('--token', type=int, required=True)
    seal.add_argument('--interrupted', default=None)
    sub.add_parser('supervise').add_argument('--run-dir', required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    host = Host(args.root)
    try:
        document = COMMANDS[args.command](args, host)
        if args.command == 'supervise':
            return 0
        print(json.dumps(dict(document, schema=SCHEMA, ok=True), sort_keys=True))
    except Refused as refused:
        print(json.dumps(dict(schema=SCHEMA, ok=False, code=refused.code, detail=refused.detail), sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
