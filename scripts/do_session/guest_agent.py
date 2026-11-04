#!/usr/bin/env python3
"""Runs on a test guest: one subcommand, one JSON document on stdout. Standard library only.

The controller uploads this file over verified SSH and judges its output in ``readiness.py``, so it reports facts
and decides nothing. It holds no credential and needs none: source comes from a public repository at an exact SHA,
and the ENet smoke uses the unsigned load-test mode. Fresh measured processes belong to the later run slice (#67).
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import socket
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
    pids.write_text('self=%d\n' % os.getpid())
    process = subprocess.Popen([sys.executable, str(RELEASE_DIR / 'sample_host.py'), '--out', str(out), '--pids', str(pids),
                                '--udp-port', str(GAME_PORT), '--interval', '1'])
    time.sleep(args.seconds)
    alive = process.poll() is None
    process.terminate()
    process.wait(timeout=10)
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
    log = (RESULTS_DIR / 'readiness-game.log').open('w')
    process = subprocess.Popen([str(RELEASE_DIR / 'omega-server'), '--config', str(RELEASE_DIR / 'server_config.json'), '--mode', 'arena',
                                '--port', str(GAME_PORT), '--allow-unsigned-tickets'], stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True, cwd=str(RELEASE_DIR))
    (RESULTS_DIR / 'readiness-game.pid').write_text(str(process.pid))
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
    return dict(pid=process.pid, running=process.poll() is None, listeners=listeners, metrics_loopback_ok=metrics_ok)


def cmd_smoke_bot(args):
    report = RESULTS_DIR / 'readiness-bot.json'
    code, _, _ = run([str(RELEASE_DIR / 'omega-load-test'), '--server', args.server, '--bots', str(SMOKE_BOTS), '--duration', str(SMOKE_DURATION_S),
                      '--output', str(report)], timeout=args.timeout_s)
    try:
        aggregated = json.loads(report.read_text())['aggregated']
    except (OSError, ValueError, KeyError):
        return dict(rc=code, report=False)
    fields = ('connected_bots', 'disconnected_bots', 'total_errors', 'total_decode_failures', 'total_send_failures', 'total_panics',
              'total_packets_sent', 'total_packets_received')
    return dict(rc=code, report=True, requested_bots=SMOKE_BOTS, report_sha256=sha256_file(report), **{f: aggregated.get(f) for f in fields})


def cmd_smoke_game_stop(args):
    pid_file = RESULTS_DIR / 'readiness-game.pid'
    exited = True
    if pid_file.exists():
        pid = int(pid_file.read_text())
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.5)
                os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            exited = False
        except ProcessLookupError:
            pass
        pid_file.unlink()
    _, out, _ = run(['ss', '-H', '-lntu'])
    _, procs, _ = run(['pgrep', '-x', '-c', 'omega-server'])
    return dict(exited_on_signal=exited, listeners=parse_listeners(out), processes=int(procs.strip() or 0))


COMMANDS = dict(probe=cmd_probe, clock=cmd_clock, wait_cloud_init=cmd_wait_cloud_init, fetch_source=cmd_fetch_source, build=cmd_build,
                install_release=cmd_install_release, sampler=cmd_sampler, tcp_probe=cmd_tcp_probe, smoke_game_start=cmd_smoke_game_start,
                smoke_bot=cmd_smoke_bot, smoke_game_stop=cmd_smoke_game_stop)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('probe').add_argument('--role', required=True, choices=('game', 'bot'))
    sub.add_parser('clock')
    sub.add_parser('wait_cloud_init').add_argument('--timeout-s', type=int, required=True)
    fetch = sub.add_parser('fetch_source')
    fetch.add_argument('--sha', required=True)
    fetch.add_argument('--timeout-s', type=int, required=True)
    build = sub.add_parser('build')
    build.add_argument('--toolchain', required=True)
    build.add_argument('--target', required=True)
    build.add_argument('--timeout-s', type=int, required=True)
    build.add_argument('--flag', action='append', default=[])
    install = sub.add_parser('install_release')
    install.add_argument('--role', required=True, choices=('game', 'bot'))
    install.add_argument('--incoming', required=True)
    sub.add_parser('sampler').add_argument('--seconds', type=int, default=4)
    probe = sub.add_parser('tcp_probe')
    probe.add_argument('--host', required=True)
    probe.add_argument('--port', type=int, required=True)
    probe.add_argument('--timeout-s', type=float, default=5.0)
    sub.add_parser('smoke_game_start').add_argument('--wait-s', type=int, default=20)
    bot = sub.add_parser('smoke_bot')
    bot.add_argument('--server', required=True)
    bot.add_argument('--timeout-s', type=int, default=60)
    sub.add_parser('smoke_game_stop')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    print(json.dumps(COMMANDS[args.command](args), sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
