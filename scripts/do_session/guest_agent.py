#!/usr/bin/env python3
"""Runs on a test guest: one subcommand, one JSON document on stdout. Standard library only.

The controller uploads this file over verified SSH and judges its output in ``readiness.py``, so it reports facts
and decides nothing. It holds no credential and needs none: source comes from a public repository at an exact SHA,
and the ENet smoke uses the unsigned load-test mode. Fresh measured processes belong to the later run slice (#67).

The exception is authority, which cannot wait for the controller. Every step that changes the host or starts a process
carries the session and fencing token, checked against the same rising fence file and lock as ``guest_runner``. A step that
starts a process also carries a window of a few seconds of registry time, and runs under ``bounded``, a small helper that
ends it by itself with no controller left. The registry cannot reach a guest, so a start already on its way when an abort
commits still lands if it arrives inside its window. The window is what bounds that, and no claim of more is made.
"""
import argparse
import contextlib
import ctypes
import fcntl
import functools
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

SCHEMA = 'omega.do-session.guest-observation/1'
REPOSITORY = 'https://github.com/Operatorr/godot-networking-poc.git'
SOURCE_DIR = pathlib.Path('/home/deploy/omega-source')
RELEASE_DIR = pathlib.Path('/home/deploy/omega-release')
AGENT_DIR = pathlib.Path('/home/deploy/omega-agent')
RESULTS_DIR = pathlib.Path('/home/deploy/omega-results')
SERVER_CONFIG = 'deployment/server_config.loadtest.json'
SAMPLER = 'scripts/quick_stress/sample_host.py'
CONTENT_PATHS = ('rust', SERVER_CONFIG, SAMPLER)
GAME_PORT = 8081
METRICS_PORT = 9100
SMOKE_BOTS = 2
SMOKE_DURATION_S = 5
ROLE_FILES = dict(game=('omega-server', 'server_config.json', 'sample_host.py'),
                  bot=('omega-load-test', 'sample_host.py'))
SECRET_PATTERNS = (re.compile(rb'dop_v1_[0-9a-f]{64}'), re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'))
SECRET_SCAN_ROOTS = ('/var/lib/cloud/instance/user-data.txt', '/var/log/cloud-init-output.log', '/var/log/cloud-init.log',
                     '/home/deploy')
MAX_SCAN_BYTES = 8 * 1024 * 1024
PACKAGE_FORMAT = '${Package} ${Version}\n'
LOCK_WAIT_S = 20.0
CLOCK_TOLERANCE_S = 1.0             # readiness proves the guest clock within this of true time
START_CONFIRM_S = 15.0
STOP_GRACE_S = 5.0
SMOKE_GAME_LIFETIME_S = 120.0       # outlasts the bot's own bound, and ends the server if no controller ever returns
SAMPLER_EXTRA_LIFETIME_S = 15.0
FENCE_CODES = ('stale_fence', 'foreign_session', 'session_closed')


class Refused(Exception):
    """This host will not do that: printed as ``ok: false`` with a stable code, so nothing about it looks like a transport failure."""

    def __init__(self, code, detail=''):
        super().__init__(code)
        self.code = code
        self.detail = detail


def run(argv, timeout=60, env=None, cwd=None):
    """A missing tool is a reported fact, never a crash: the controller rejects what cannot be observed."""
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env, cwd=cwd, check=False)
    except OSError as error:
        return 127, '', type(error).__name__
    return result.returncode, result.stdout.decode('utf-8', 'replace'), result.stderr.decode('utf-8', 'replace')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path, default=None):
    try:
        return pathlib.Path(path).read_text()
    except OSError:
        return default


def read_json(path):
    try:
        with open(str(path), encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def atomic_json(path, document):
    path = pathlib.Path(path)
    temporary = path.with_name(path.name + '.tmp%d' % os.getpid())
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(document, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(str(temporary), str(path))


# ---- the host's authority --------------------------------------------------------------------------
# The same files as guest_runner.Host. This program runs before the runner is ever uploaded, so it cannot import it.

def control_dir():
    path = RESULTS_DIR / 'do-runs' / 'control'
    path.mkdir(parents=True, exist_ok=True, mode=0o750)
    return path


@contextlib.contextmanager
def host_lock():
    with (control_dir() / 'lock').open('a') as handle:
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise Refused('lock_timeout', 'another command holds the host lock')
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def hold_fence(args, require_open=True):
    """Under the host lock. A higher token raises the fence, because tokens only rise and the newest controller is the newest."""
    path = control_dir() / 'fence.json'
    fence = read_json(path)
    if fence is not None and fence.get('session_id') != args.session:
        raise Refused('foreign_session', 'this host is fenced by another session')
    if fence is not None and args.token < fence.get('token'):
        raise Refused('stale_fence', 'fence is at %s, request carries %s' % (fence.get('token'), args.token))
    closed = (fence or {}).get('closed')
    if fence is None or args.token > fence.get('token'):
        atomic_json(path, dict(session_id=args.session, token=args.token, closed=closed))
    if require_open and closed:
        raise Refused('session_closed', 'no process may start: %s' % closed)


def require_authority(args):
    with host_lock():
        hold_fence(args)


def require_window(args):
    if time.time() > args.not_after_wall + CLOCK_TOLERANCE_S:
        raise Refused('authorization_expired', 'this start is past its authorization')


# ---- process identity: the same rules as guest_runner, kept equal by test_guest_runner ----------------

@functools.lru_cache(maxsize=1)
def boot_id():
    try:
        return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        code, out, _ = run(['sysctl', '-n', 'kern.boottime'])
        return out.split(',')[0].strip() if code == 0 and out else None


def process_start_id(pid):
    try:
        with open('/proc/%d/stat' % pid, encoding='utf-8', errors='replace') as handle:
            fields = handle.read().rsplit(')', 1)[1].split()
        return None if fields[0] in ('Z', 'X') else 'ticks:' + fields[19]
    except (OSError, IndexError):
        pass
    return None if os.path.isdir('/proc') else _darwin_start_id(pid)


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
    if not identity or not identity.get('start_id') or not identity.get('boot_id') or identity['boot_id'] != boot_id():
        return False
    return process_start_id(identity['pid']) == identity['start_id']


def signal_identity(identity, signum):
    """Never a process that merely has the same number."""
    if same_process(identity):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(identity['pid'], signum)


# ---- a process that ends by itself -------------------------------------------------------------------

def bounded_paths(name):
    return RESULTS_DIR / (name + '.json'), RESULTS_DIR / (name + '.stop'), RESULTS_DIR / (name + '.log')


def start_bounded(name, argv, args, lifetime_s, cwd):
    """Hold the host lock around this, so a fence cannot rise between the helper's look and its process appearing."""
    state, stop, log = bounded_paths(name)
    for path in (state, stop):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    command = [sys.executable, os.path.abspath(__file__), 'bounded', '--state', str(state), '--stop', str(stop), '--log', str(log), '--control', str(control_dir()),
               '--session', args.session, '--token', str(args.token), '--not-after-wall', str(args.not_after_wall), '--lifetime-s', str(lifetime_s), '--cwd', str(cwd), '--'] + [str(a) for a in argv]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    deadline = time.monotonic() + START_CONFIRM_S
    while time.monotonic() < deadline:
        record = read_json(state)
        if record is not None and record.get('refused'):
            raise Refused(record['refused'], record.get('detail') or '')
        if record is not None and record.get('process'):
            return record
        time.sleep(0.02)
    raise Refused('start_unconfirmed', 'no identity from the helper')


def _die_with_parent():
    """Linux: a helper killed outright takes its process with it. Nothing more can be done from here on macOS, a development path."""
    with contextlib.suppress(OSError, AttributeError):
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)      # 1 is PR_SET_PDEATHSIG


def cmd_bounded(args):
    """Started by ``start_bounded``. Takes the last look at authority, runs one process, and ends it by its lifetime with or without a controller."""
    state, stop = pathlib.Path(args.state), pathlib.Path(args.stop)
    record = dict(supervisor=identity_of(os.getpid()), process=None, ended=False)
    fence = read_json(pathlib.Path(args.control) / 'fence.json') or {}
    refused = None
    if fence.get('session_id') != args.session or fence.get('token') != args.token:
        refused = 'stale_fence'
    elif fence.get('closed'):
        refused = 'session_closed'
    elif time.time() > args.not_after_wall + CLOCK_TOLERANCE_S:
        refused = 'authorization_expired'
    elif stop.exists():
        refused = 'stop_requested'
    if refused is not None:
        atomic_json(state, dict(record, refused=refused, ended=True))
        return {}
    terminated = []
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, lambda *_: terminated.append(True))
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    try:
        with open(args.log, 'w', encoding='utf-8') as log:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=args.cwd, preexec_fn=_die_with_parent)
    except OSError as error:
        atomic_json(state, dict(record, refused='spawn_failed', detail=type(error).__name__, ended=True))
        return {}
    atomic_json(state, dict(record, process=identity_of(child.pid)))
    ends = time.monotonic() + args.lifetime_s
    reason = None
    while child.poll() is None and reason is None:
        if terminated:
            reason = 'helper_terminated'
        elif stop.exists():
            reason = 'stop_requested'
        elif time.monotonic() >= ends:
            reason = 'lifetime_exhausted'
        else:
            time.sleep(0.05)
    killed = False
    if child.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(child.pid, signal.SIGTERM)
        grace_ends = time.monotonic() + STOP_GRACE_S
        while child.poll() is None and time.monotonic() < grace_ends:
            time.sleep(0.05)
        if child.poll() is None:
            killed = True
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(child.pid, signal.SIGKILL)
    child.wait()
    atomic_json(state, dict(read_json(state) or record, ended=True, reason=reason or 'exited', returncode=child.returncode, killed=killed))
    return {}


def await_bounded_end(state, limit_s):
    """True if the helper ended its process without having to kill it. A helper that is gone or stuck is settled here, by identity only."""
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        record = read_json(state)
        if record is None:
            return True
        if record.get('ended'):
            return not record.get('killed')
        if not same_process(record.get('supervisor')):
            orphan = same_process(record.get('process'))
            signal_identity(record.get('process'), signal.SIGKILL)
            return not orphan
        time.sleep(0.05)
    record = read_json(state) or {}
    signal_identity(record.get('process'), signal.SIGKILL)
    signal_identity(record.get('supervisor'), signal.SIGKILL)
    return False


def key_values(text, separator='='):
    pairs = {}
    for line in (text or '').splitlines():
        if separator in line:
            key, value = line.split(separator, 1)
            pairs[key.strip()] = value.strip().strip('"')
    return pairs


def content_digest(ls_tree_output):
    """Digest over ``git ls-tree -r`` lines, so the controller can compute it without the guest's tar or git version."""
    return hashlib.sha256(''.join(sorted(line + '\n' for line in ls_tree_output.splitlines() if line.strip())).encode('utf-8')).hexdigest()


def parse_listeners(ss_output):
    """Parse ``ss -H -lntu``: netid, state, recv-q, send-q, local address:port, peer."""
    listeners = []
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) < 5 or ':' not in fields[4]:
            continue
        address, _, port = fields[4].rpartition(':')
        if port.isdigit():
            listeners.append(dict(protocol=fields[0], address=address.strip('[]').split('%')[0], port=int(port)))
    return listeners


def fingerprint_authorized_keys(path):
    code, out, _ = run(['ssh-keygen', '-lf', str(path), '-E', 'sha256'])
    return [line.split()[1] for line in out.splitlines() if len(line.split()) >= 2] if code == 0 else []


def secret_findings(roots=SECRET_SCAN_ROOTS):
    """Paths that hold credential material. Values are never returned."""
    found = []

    def scan(path):
        try:
            if path.is_symlink() or not path.is_file():
                return
            with path.open('rb') as handle:
                content = handle.read(MAX_SCAN_BYTES)
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                found.append(str(path))
        except OSError:
            pass

    for root in roots:
        root = pathlib.Path(root)
        if root.is_dir():
            for directory, names, files in os.walk(str(root)):
                # Source and compiled artifacts may spell these markers legitimately, and they are identified by hash.
                names[:] = [n for n in names if n not in ('.cargo', '.rustup', 'omega-source', 'omega-release')]
                for name in files:
                    scan(pathlib.Path(directory) / name)
        else:
            scan(root)
    return sorted(found)


def effective_sshd():
    code, out, _ = run(['sudo', '-n', 'sshd', '-T'])
    values = key_values(out, ' ')
    return dict(rc=code, passwordauthentication=values.get('passwordauthentication'),
                kbdinteractiveauthentication=values.get('kbdinteractiveauthentication'),
                pubkeyauthentication=values.get('pubkeyauthentication'), authenticationmethods=values.get('authenticationmethods'),
                permitrootlogin=values.get('permitrootlogin'))


def cloud_init_status(wait_s=None):
    argv = ['cloud-init', 'status', '--format', 'json'] + (['--wait'] if wait_s else [])
    try:
        code, out, _ = run(argv, timeout=wait_s or 30)
    except subprocess.TimeoutExpired:
        return dict(rc=None, status='timeout', errors=[], recoverable_errors={}, boot_finished=False)
    try:
        document = json.loads(out)
    except ValueError:
        document = {}
    return dict(rc=code, status=document.get('status'), extended_status=document.get('extended_status'),
                errors=document.get('errors') or [], recoverable_errors=document.get('recoverable_errors') or {},
                boot_finished=os.path.exists('/var/lib/cloud/instance/boot-finished'))


def cpu_facts():
    count = os.cpu_count()
    fields = key_values(read_text('/proc/cpuinfo', ''), ':')
    return dict(count=count, vendor=fields.get('vendor_id'), model=fields.get('model name'))


def memory_facts():
    fields = key_values(read_text('/proc/meminfo', ''), ':')

    def mib(name):
        try:
            return int(fields[name].split()[0]) // 1024
        except (KeyError, ValueError, IndexError):
            return None
    return dict(total_mib=mib('MemTotal'), swap_total_mib=mib('SwapTotal'))


def disk_facts():
    root = shutil.disk_usage('/')
    results_free = writable = None
    try:
        results_free = shutil.disk_usage(str(RESULTS_DIR)).free
        with tempfile.NamedTemporaryFile(dir=str(RESULTS_DIR)) as handle:
            handle.write(b'x')
            writable = True
    except OSError:
        writable = False
    return dict(root_total_gib=root.total // 2 ** 30, results_free_gib=None if results_free is None else results_free // 2 ** 30,
                results_writable=writable)


def nofile_facts():
    code, out, _ = run(['bash', '-lc', 'ulimit -Sn; ulimit -Hn'])
    values = out.split()
    return dict(soft=int(values[0]), hard=int(values[1])) if code == 0 and len(values) == 2 and all(v.isdigit() for v in values) else {}


def clock_facts():
    _, sync, _ = run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'])
    _, service, _ = run(['systemctl', 'is-active', 'systemd-timesyncd'])
    return dict(ntp_synchronized=sync.strip() == 'yes', service=service.strip(), wall_ns=time.time_ns(),
                monotonic_ns=time.monotonic_ns(), boot_id=read_text('/proc/sys/kernel/random/boot_id', '').strip())


def release_hashes():
    return {path.name: sha256_file(path) for path in sorted(RELEASE_DIR.glob('*')) if path.is_file()}


def package_inventory():
    """Every installed package and version, with the command's status. Failing to read it is a reported fact.

    A line without exactly two fields, or output not ending in a newline, means the list was cut or misread. It is reported
    as incomplete with whatever did parse, because a digest of a list nobody retained could not identify anything later.
    """
    argv = ['dpkg-query', '-W', '-f', PACKAGE_FORMAT]
    command = ' '.join(argv[:2] + ['-f', PACKAGE_FORMAT.encode('unicode_escape').decode('ascii')])
    try:
        code, out, _ = run(argv)
    except subprocess.TimeoutExpired:
        return dict(command=command, rc=None, complete=False, incomplete='timed out', count=0, sha256=None, inventory=[])
    inventory, malformed = [], 0
    for line in out.splitlines():
        fields = line.split(' ')
        if len(fields) == 2 and all(fields):
            inventory.append(dict(name=fields[0], version=fields[1]))
        else:
            malformed += 1
    incomplete = []
    if malformed:
        incomplete.append('%d unreadable lines' % malformed)
    if out and not out.endswith('\n'):
        incomplete.append('output does not end its last line')
    if not inventory:
        incomplete.append('no packages listed')
    return dict(command=command, rc=code, complete=code == 0 and not incomplete, incomplete='; '.join(incomplete) or None,
                count=len(inventory), sha256=hashlib.sha256(out.encode('utf-8')).hexdigest(), inventory=inventory)


def cmd_probe(args):
    ss_code, ss_out, _ = run(['ss', '-H', '-lntu'])
    _, kernel, _ = run(['uname', '-r'])
    _, machine, _ = run(['uname', '-m'])
    _, route, _ = run(['ip', '-j', 'route', 'show', 'default'])
    _, addresses, _ = run(['ip', '-j', '-4', 'address', 'show', 'scope', 'global'])
    os_release = key_values(read_text('/etc/os-release', ''))
    return dict(
        schema=SCHEMA, role=args.role, os=dict(id=os_release.get('ID'), version_id=os_release.get('VERSION_ID')),
        kernel=kernel.strip(), architecture=machine.strip(), cpu=cpu_facts(), memory=memory_facts(), disk=disk_facts(),
        nofile=nofile_facts(), cloud_init=cloud_init_status(), sshd=effective_sshd(),
        authorized_keys=fingerprint_authorized_keys(pathlib.Path.home() / '.ssh' / 'authorized_keys'),
        listeners=parse_listeners(ss_out) if ss_code == 0 else None, clock=clock_facts(),
        packages=package_inventory(),
        network=dict(default_route=route.strip(), addresses=addresses.strip()), secrets=dict(findings=secret_findings()),
        release=release_hashes())


def cmd_clock(args):
    """Nothing else: the controller brackets this call, so any extra work here would widen the uncertainty."""
    return dict(wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())


def cmd_wait_cloud_init(args):
    return cloud_init_status(args.timeout_s)


def cmd_fetch_source(args):
    require_authority(args)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for argv in (['git', 'init', '-q', '.'], ['git', 'fetch', '-q', '--depth', '1', REPOSITORY, args.sha],
                 ['git', 'checkout', '-q', '--detach', 'FETCH_HEAD']):
        code, _, err = run(argv, timeout=args.timeout_s, cwd=str(SOURCE_DIR))
        if code != 0:
            return dict(ok=False, failed=argv[1], detail=err[-400:])
    _, head, _ = run(['git', 'rev-parse', 'HEAD'], cwd=str(SOURCE_DIR))
    _, porcelain, _ = run(['git', 'status', '--porcelain'], cwd=str(SOURCE_DIR))
    _, tree, _ = run(['git', 'ls-tree', '-r', '--full-tree', 'HEAD'] + list(CONTENT_PATHS), cwd=str(SOURCE_DIR))
    return dict(ok=True, head=head.strip(), clean=not porcelain.strip(), cargo_lock_sha256=sha256_file(SOURCE_DIR / 'rust' / 'Cargo.lock'),
                server_config_sha256=sha256_file(SOURCE_DIR / SERVER_CONFIG), content_sha256=content_digest(tree))


def cmd_build(args):
    """Install the exact toolchain, then build both binaries with locked dependencies from the clean checkout."""
    require_authority(args)
    environment = {k: v for k, v in os.environ.items() if k not in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'CARGO_BUILD_RUSTFLAGS')}
    rustup_init = AGENT_DIR / 'rustup-init'
    url = 'https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init'
    with urllib.request.urlopen(url, timeout=120) as response, rustup_init.open('wb') as handle:
        shutil.copyfileobj(response, handle)
    rustup_init.chmod(0o700)
    cargo_bin = pathlib.Path.home() / '.cargo' / 'bin'
    log = RESULTS_DIR / 'build.log'
    with log.open('w') as handle:
        for argv in ([str(rustup_init), '-y', '--profile', 'minimal', '--default-toolchain', args.toolchain],
                     [str(cargo_bin / 'cargo'), '+' + args.toolchain, 'build', '--release', '--locked', '--target', args.target,
                      '-p', 'omega-server', '-p', 'omega-load-test'] + args.flag):
            code = subprocess.run(argv, stdout=handle, stderr=subprocess.STDOUT, timeout=args.timeout_s, env=environment,
                                  cwd=str(SOURCE_DIR / 'rust'), check=False).returncode
            if code != 0:
                return dict(ok=False, rc=code, failed=argv[0], log_sha256=sha256_file(log))
    _, porcelain, _ = run(['git', 'status', '--porcelain'], cwd=str(SOURCE_DIR))
    _, rustc, _ = run([str(cargo_bin / 'rustc'), '+' + args.toolchain, '-Vv'])
    _, cargo, _ = run([str(cargo_bin / 'cargo'), '+' + args.toolchain, '-V'])
    target = SOURCE_DIR / 'rust' / 'target' / args.target / 'release'
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    for source, name in ((target / 'omega-server', 'omega-server'), (target / 'omega-load-test', 'omega-load-test'),
                         (SOURCE_DIR / SERVER_CONFIG, 'server_config.json'), (SOURCE_DIR / SAMPLER, 'sample_host.py')):
        shutil.copy2(str(source), str(RELEASE_DIR / name))
    return dict(ok=True, rc=0, clean_after_build=not porcelain.strip(), rustc=rustc.strip(), cargo=cargo.strip(), toolchain=args.toolchain,
                target=args.target, flags=args.flag, rustup_init_sha256=sha256_file(rustup_init), log_sha256=sha256_file(log),
                release=release_hashes())


def cmd_install_release(args):
    """Move relayed files into place. The controller compares the reported hashes with those on the builder."""
    require_authority(args)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ROLE_FILES[args.role]:
        source = pathlib.Path(args.incoming) / name
        shutil.move(str(source), str(RELEASE_DIR / name))
    (RELEASE_DIR / ROLE_FILES[args.role][0]).chmod(0o755)
    return dict(ok=True, release=release_hashes())


def cmd_sampler(args):
    """Run the host sampler briefly: readiness needs a live, advancing sampler, not just a file on disk."""
    out = RESULTS_DIR / 'readiness-sampler.ndjson'
    pids = RESULTS_DIR / 'readiness-sampler.pids'
    state, stop, _ = bounded_paths('readiness-sampler')
    with host_lock():
        hold_fence(args)
        require_window(args)
        with contextlib.suppress(FileNotFoundError):
            out.unlink()    # the sampler appends, and a second pass after a resume must not read as its clock going backward
        pids.write_text('self=%d\n' % os.getpid())
        record = start_bounded('readiness-sampler', [sys.executable, str(RELEASE_DIR / 'sample_host.py'), '--out', str(out), '--pids', str(pids),
                                                     '--udp-port', str(GAME_PORT), '--interval', '1'], args, args.seconds + SAMPLER_EXTRA_LIFETIME_S, RESULTS_DIR)
    time.sleep(args.seconds)
    alive = same_process(record['process'])
    atomic_json(stop, dict(wall=time.time()))
    await_bounded_end(state, STOP_GRACE_S + 5)
    rows = []
    for line in read_text(out, '').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    stamps = [row['mono_s'] for row in rows if isinstance(row.get('mono_s'), (int, float))]
    return dict(samples=len(stamps), alive_until_stopped=alive, monotonic_advancing=len(stamps) >= 2 and stamps == sorted(stamps) and stamps[0] < stamps[-1],
                sha256=sha256_file(out) if out.exists() else None)


def cmd_tcp_probe(args):
    """One TCP connection attempt. Reports only what happened: connected, refused or timeout."""
    try:
        socket.create_connection((args.host, args.port), timeout=args.timeout_s).close()
        return dict(outcome='connected')
    except socket.timeout:
        return dict(outcome='timeout')
    except ConnectionRefusedError:
        return dict(outcome='refused')
    except OSError as error:
        return dict(outcome='error', detail=type(error).__name__)


def cmd_smoke_game_start(args):
    """A server that ends by itself at ``--lifetime-s``, so a reply lost after this point can only cost that long."""
    state, stop, _ = bounded_paths('readiness-game')
    with host_lock():
        hold_fence(args)
        require_window(args)
        if (read_json(stop) or {}).get('smoke_id') == args.smoke_id:
            raise Refused('smoke_stopped', 'this smoke was already stopped, so this start arrived after its stop')
        if read_json(control_dir() / 'active.json') is not None:
            raise Refused('overlap', 'a test run is active on this host')
        previous = read_json(state) or {}
        if not previous.get('ended') and (same_process(previous.get('supervisor')) or same_process(previous.get('process'))):
            raise Refused('overlap', 'an earlier smoke is still running')
        record = start_bounded('readiness-game', [RELEASE_DIR / 'omega-server', '--config', RELEASE_DIR / 'server_config.json', '--mode', 'arena', '--port', GAME_PORT,
                                                  '--allow-unsigned-tickets'], args, args.lifetime_s, RELEASE_DIR)
    process = record['process']
    listeners = []
    for _ in range(args.wait_s):
        time.sleep(1)
        _, out, _ = run(['ss', '-H', '-lntu'])
        listeners = parse_listeners(out)
        if any(l['port'] == GAME_PORT and l['protocol'] == 'udp' for l in listeners) and any(l['port'] == METRICS_PORT for l in listeners):
            break
    metrics_ok = False
    try:
        with urllib.request.urlopen('http://127.0.0.1:%d/metrics' % METRICS_PORT, timeout=5) as response:
            metrics_ok = response.status == 200
    except OSError:
        pass
    return dict(pid=process['pid'], running=same_process(process), listeners=listeners, metrics_loopback_ok=metrics_ok, supervisor=record['supervisor'], process=process)


def cmd_smoke_bot(args):
    report = RESULTS_DIR / 'readiness-bot.json'
    state, _, _ = bounded_paths('readiness-bot')
    with host_lock():
        hold_fence(args)
        require_window(args)
        with contextlib.suppress(FileNotFoundError):
            report.unlink()
        start_bounded('readiness-bot', [RELEASE_DIR / 'omega-load-test', '--server', args.server, '--bots', SMOKE_BOTS, '--duration', SMOKE_DURATION_S, '--output', report],
                      args, args.timeout_s, RESULTS_DIR)
    deadline = time.monotonic() + args.timeout_s + STOP_GRACE_S + 2
    while time.monotonic() < deadline and not (read_json(state) or {}).get('ended'):
        time.sleep(0.05)
    code = (read_json(state) or {}).get('returncode')
    try:
        aggregated = json.loads(report.read_text())['aggregated']
    except (OSError, ValueError, KeyError):
        return dict(rc=code, report=False)
    fields = ('connected_bots', 'disconnected_bots', 'total_errors', 'total_decode_failures', 'total_send_failures', 'total_panics',
              'total_packets_sent', 'total_packets_received')
    return dict(rc=code, report=True, requested_bots=SMOKE_BOTS, report_sha256=sha256_file(report), **{f: aggregated.get(f) for f in fields})


def cmd_smoke_game_stop(args):
    """Works through cleanup, but only for the current token. Leaves a mark, so a start still on its way for this smoke is refused."""
    state, stop, _ = bounded_paths('readiness-game')
    with host_lock():
        hold_fence(args, require_open=False)
        atomic_json(stop, dict(smoke_id=args.smoke_id, wall=time.time()))
    exited = await_bounded_end(state, STOP_GRACE_S + 5)
    _, out, _ = run(['ss', '-H', '-lntu'])
    _, procs, _ = run(['pgrep', '-x', '-c', 'omega-server'])
    return dict(exited_on_signal=exited, listeners=parse_listeners(out), processes=int(procs.strip() or 0))


COMMANDS = dict(probe=cmd_probe, clock=cmd_clock, wait_cloud_init=cmd_wait_cloud_init, fetch_source=cmd_fetch_source, build=cmd_build,
                install_release=cmd_install_release, sampler=cmd_sampler, tcp_probe=cmd_tcp_probe, smoke_game_start=cmd_smoke_game_start,
                smoke_bot=cmd_smoke_bot, smoke_game_stop=cmd_smoke_game_stop, bounded=cmd_bounded)


def add_authority(parser, start=False):
    parser.add_argument('--session', required=True)
    parser.add_argument('--token', type=int, required=True)
    if start:
        parser.add_argument('--not-after-wall', type=float, required=True, help='wall time this start stops being authorized')
    return parser


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('probe').add_argument('--role', required=True, choices=('game', 'bot'))
    sub.add_parser('clock')
    sub.add_parser('wait_cloud_init').add_argument('--timeout-s', type=int, required=True)
    fetch = sub.add_parser('fetch_source')
    fetch.add_argument('--sha', required=True)
    fetch.add_argument('--timeout-s', type=int, required=True)
    add_authority(fetch)
    build = sub.add_parser('build')
    build.add_argument('--toolchain', required=True)
    build.add_argument('--target', required=True)
    build.add_argument('--timeout-s', type=int, required=True)
    build.add_argument('--flag', action='append', default=[])
    add_authority(build)
    install = sub.add_parser('install_release')
    install.add_argument('--role', required=True, choices=('game', 'bot'))
    install.add_argument('--incoming', required=True)
    add_authority(install)
    add_authority(sub.add_parser('sampler'), start=True).add_argument('--seconds', type=int, default=4)
    probe = sub.add_parser('tcp_probe')
    probe.add_argument('--host', required=True)
    probe.add_argument('--port', type=int, required=True)
    probe.add_argument('--timeout-s', type=float, default=5.0)
    game = add_authority(sub.add_parser('smoke_game_start'), start=True)
    game.add_argument('--smoke-id', required=True)
    game.add_argument('--wait-s', type=int, default=20)
    game.add_argument('--lifetime-s', type=float, default=SMOKE_GAME_LIFETIME_S)
    bot = add_authority(sub.add_parser('smoke_bot'), start=True)
    bot.add_argument('--server', required=True)
    bot.add_argument('--timeout-s', type=int, default=60)
    add_authority(sub.add_parser('smoke_game_stop')).add_argument('--smoke-id', required=True)
    bounded = add_authority(sub.add_parser('bounded'), start=True)
    for name in ('--state', '--stop', '--log', '--control', '--cwd'):
        bounded.add_argument(name, required=True)
    bounded.add_argument('--lifetime-s', type=float, required=True)
    bounded.add_argument('argv', nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        document = COMMANDS[args.command](args)
    except Refused as refused:
        document = dict(schema=SCHEMA, ok=False, code=refused.code, detail=refused.detail)
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
