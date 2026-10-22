#!/usr/bin/env python3
"""One bounded issue-38 frozen-build CPU profile; private evidence only.

Remote modes use only the standard library plus the existing host collector.
The local controller refuses a second launch in its fixed namespace.
"""
import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import os
import pathlib
import re
import resource
import shlex
import signal
import subprocess
import sys
import time

NAMESPACE = 'udp-profile-20261021'
REMOTE = '/home/deploy/omega-results/' + NAMESPACE
UNIT = 'omega-' + NAMESPACE
SERVICE = 'omega-loadtest-arena.service'
OVERRIDE = '/run/systemd/system/' + SERVICE + '.d/zz-udp-profile.conf'
BINARIES = {
    'game': '/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server',
    'bots': '/home/deploy/omega-measured/rust/target/release/omega-load-test',
}
PINNED = {
    'game': 'f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2',
    'bots': '8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf',
}
RAMP_SECONDS = 180
STEADY_SECONDS = 120


def dump(path, value):
    pathlib.Path(path).write_text(json.dumps(value, indent=2) + '\n')


def collect(role):
    import host_collect
    directory = pathlib.Path(REMOTE) / role
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    with gzip.open(directory / 'host.ndjson.gz', 'xt') as output:
        while not stopped and time.monotonic() - started < 350:
            before = time.monotonic()
            sample = host_collect.sample(role, UNIT + '-swarm' if role == 'bots' else None)
            sample['socket_before_utc_ns'] = time.time_ns()
            sample['ss'] = host_collect.command(['ss', '-u', '-a', '-m', '-n', '-p', '-e'])
            sample['socket_after_utc_ns'] = time.time_ns()
            sample['proc_udp'] = host_collect.read('/proc/net/udp')
            sample['proc_udp6'] = host_collect.read('/proc/net/udp6')
            sample['collector_self_stat'] = host_collect.read('/proc/self/stat')
            sample['collector_cpu_s'] = {
                scope: (usage.ru_utime + usage.ru_stime)
                for scope, usage in (
                    ('self', resource.getrusage(resource.RUSAGE_SELF)),
                    ('children', resource.getrusage(resource.RUSAGE_CHILDREN)),
                )
            }
            sample['total_sample_duration_ns'] = int((time.monotonic() - before) * 1e9)
            output.write(json.dumps(sample) + '\n')
            output.flush()
            time.sleep(max(0, 1 - (time.monotonic() - before)))


def swarm():
    """Remote watchdog enforces join failure and time bounds even without SSH."""
    directory = pathlib.Path(REMOTE) / 'bots'
    spec = json.loads((directory / 'invocation.json').read_text())
    env = dict(os.environ)
    for key in ('OMEGA_TICKET_API', 'OMEGA_LOAD_TEST_SECRET'):
        env.pop(key, None)
    env['OMEGA_MEASURE_DIR'] = str(directory)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    started = time.monotonic()
    reason = None
    failure = re.compile(r'\bBot \d+ (?:ticket fetch failed|failed to start|failed to connect):')
    with (directory / 'bot.log').open('xb') as output:
        child = subprocess.Popen(['/bin/sh', '-c', 'kill -STOP $$; exec "$@"',
                                  'profile-gated-bot', *spec['argv']],
                                 stdout=output, stderr=subprocess.STDOUT, env=env)
        dump(directory / 'bot-pid.json', {'pid': child.pid, 'created_utc_ns': time.time_ns()})
        try:
            subprocess.run(['sudo', '-n', 'systemd-run', '--quiet', '--unit=' + UNIT + '-bots-profile',
                            '--property=RuntimeMaxSec=59', '--property=TimeoutStopSec=1',
                            '--property=LimitFSIZE=67108864', 'python3', REMOTE + '/udp_profile_record.py',
                            'record', '--pid', str(child.pid), '--directory', str(directory)],
                           check=True, timeout=8)
            ready_deadline = time.monotonic() + 6
            while not (directory / 'profile-ready.json').exists():
                if time.monotonic() >= ready_deadline:
                    raise RuntimeError('Bot perf not ready before workload exec')
                time.sleep(.05)
            dump(directory / 'workload-start.json', {'pid': child.pid, 'utc_ns': time.time_ns(),
                                                    'monotonic_ns': time.monotonic_ns()})
            child.send_signal(signal.SIGCONT)
            started = time.monotonic()
            while child.poll() is None:
                log = (directory / 'bot.log').read_text(errors='replace')
                hit = next((line for line in log.splitlines() if failure.search(line)), None)
                phase = directory / 'phase.json'
                if hit:
                    reason = {'kind': 'join-failure', 'line': hit}
                    break
                if stopped:
                    reason = {'kind': 'controller-stop'}
                    break
                if not phase.exists() and time.monotonic() - started >= RAMP_SECONDS:
                    reason = {'kind': 'ramp-timeout'}
                    break
                if phase.exists():
                    stamp = json.loads(phase.read_text())['phase2_utc_ns']
                    if time.time_ns() >= stamp + STEADY_SECONDS * 1_000_000_000:
                        reason = {'kind': 'diagnostic-steady-time-limit'}
                        break
                if (directory / 'bot.log').stat().st_size > 8 * 1024**2:
                    reason = {'kind': 'bounded-log-limit'}
                    break
                time.sleep(0.5)
        finally:
            if child.poll() is None:
                child.terminate()
                child.send_signal(signal.SIGCONT)
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            dump(directory / 'guard-result.json', {
                'reason': reason, 'exit_code': child.returncode,
                'elapsed_s': time.monotonic() - started, 'ended_utc_ns': time.time_ns(),
            })


def preflight():
    import run
    os.umask(0o077)
    root = run.ROOT / 'deployment/hetzner/results' / NAMESPACE
    root.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = root / ('preflight-' + stamp)
    directory.mkdir(mode=0o700)
    result = {'namespace': NAMESPACE, 'experiment_started': False,
              'profile_samples': None, 'remote_mutations': False, 'hosts': {}}

    def inspect(role, label, command):
        host = run.HOSTS[role]
        try:
            proc = subprocess.run(
                ['ssh', '-i', str(run.KEY), *run.SSH_OPTIONS,
                 host['ssh_user'] + '@' + host['ipv4'], command],
                capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            raise RuntimeError(role + ' read-only inspection timed out') from None
        record = {'command': command, 'returncode': proc.returncode,
                  'stdout': proc.stdout, 'stderr': proc.stderr}
        (directory / (role + '-' + label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        if proc.returncode:
            raise RuntimeError(role + ' inspection failed: ' + label)
        return proc.stdout

    for role in ('game', 'bots'):
        binary = inspect(role, 'binary', 'sha256sum ' + BINARIES[role]).split()[0]
        disk = int(inspect(role, 'disk', 'df --output=avail -B1 /home/deploy | tail -1'))
        processes = inspect(role, 'processes', 'ps -eo pid,comm,args')
        occupied = []
        for line in processes.splitlines()[1:]:
            fields = line.split(None, 2)
            if len(fields) != 3 or fields[1] in ('bash', 'sshd', 'sshd-session'):
                continue
            if fields[1] in ('omega-load-test', 'perf', 'bpftrace', 'tcpdump', 'strace',
                              'apt', 'apt-get', 'dpkg', 'rustc', 'cargo') or any(
                    name in fields[2] for name in ('host_collect.py', 'udp_baseline.py',
                                                   'udp_profile.py', 'capture.py', 'flow-record')):
                occupied.append(int(fields[0]))
        qdisc = json.loads(inspect(role, 'qdisc', 'tc -j qdisc show dev eth0'))
        filters = [json.loads(inspect(role, direction, 'tc -j filter show dev eth0 ' + direction))
                   for direction in ('ingress', 'egress')]
        nft = inspect(role, 'firewall', 'sudo -n nft list ruleset')
        services = inspect(role, 'services', 'systemctl show ' + SERVICE +
                           ' apt-daily.timer apt-daily-upgrade.timer apt-daily.service'
                           ' apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState -p MainPID')
        inspect(role, 'timers', 'systemctl list-timers apt-daily.timer apt-daily-upgrade.timer --no-pager')
        tools = inspect(role, 'samplers', 'for tool in perf bpftrace gdb eu-stack sysprof-cli strace; do '
                        'command -v "$tool" || true; done; '
                        'for p in /usr/lib/linux-tools/*/perf /usr/lib/linux-tools-*/perf /opt/*/bin/perf; '
                        'do test ! -x "$p" || printf "%s\\n" "$p"; done; true')
        inspect(role, 'perf-policy', 'cat /proc/sys/kernel/perf_event_paranoid; uname -r; '
                'apt-cache policy linux-tools-$(uname -r) linux-perf')
        validation = inspect(role, 'validation', 'sudo -n cat /home/deploy/omega-results/udp-profile-tools-20261021/' + ('validation-v2' if role == 'game' else 'validation') + '/validation.json')
        gates_validation = json.loads(validation).get('validated', False)
        inspect(role, 'symbols', 'readelf -SW ' + BINARIES[role])
        namespace_absent = inspect(role, 'namespace',
                                  'if test -e ' + REMOTE + '; then echo exists; else echo absent; fi').strip() == 'absent'
        bundle = 'game.tar.gz' if role == 'game' else 'bots-final.tar.gz'
        previous = '/home/deploy/omega-results/udp-diagnosis-20261021/'
        remote_sha = inspect(role, 'baseline-bundle', 'sha256sum ' + previous + bundle).split()[0]
        with (run.ROOT / 'deployment/hetzner/results/udp-diagnosis-20261021' / bundle).open('rb') as stream:
            local_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        inspect(role, 'closed-states', "find /home/deploy/omega-results/campaign-20261013 "
                "/home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' "
                "-exec sha256sum {} \\;")
        gates = {'validated_sampler': gates_validation, 'pinned_binary': binary == PINNED[role], 'disk_at_least_8_gib': disk >= 8 * 1024**3,
                 'idle_ownership': not occupied, 'native_qdisc': all(q['kind'] == 'fq_codel' for q in qdisc),
                 'no_filters': not any(filters), 'no_measurement_firewall': 'omega_measure' not in nft,
                 'remote_namespace_absent': namespace_absent, 'baseline_bundle_verified': remote_sha == local_sha}
        if role == 'game':
            metrics = inspect(role, 'metrics', 'curl -fsS --max-time 3 http://127.0.0.1:9100/metrics')
            config = inspect(role, 'config', 'cat /etc/omega-loadtest/arena.json')
            inspect(role, 'unit', 'systemctl cat ' + SERVICE)
            gates['zero_players'] = bool(re.search(r'^players_online 0$', metrics, re.M))
            gates['one_game_process'] = len(re.findall(r'^\s*\d+ omega-server\s', processes, re.M)) == 1
            gates['native_config'] = json.loads(config) == json.loads((run.ROOT / 'deployment/server_config.loadtest.json').read_text())
        blocks = services.strip().split('\n\n')
        states = {part.split('=', 1)[1]: dict(line.split('=', 1) for line in block.splitlines())
                  for block in blocks for part in block.splitlines() if part.startswith('Id=')}
        gates['updates_idle'] = all(states[name]['ActiveState'] == 'inactive'
                                    for name in ('apt-daily.service', 'apt-daily-upgrade.service'))
        gates['maintenance_timers_active'] = all(states[name]['ActiveState'] == 'active'
                                                 for name in ('apt-daily.timer', 'apt-daily-upgrade.timer'))
        result['hosts'][role] = {'gates': gates, 'disk_available_bytes': disk,
                                'sampler_paths': tools.splitlines(),
                                'perf_installed': any(pathlib.PurePosixPath(p).name == 'perf' for p in tools.splitlines()),
                                'baseline_bundle_sha256': remote_sha}
    if not all(all(host['gates'].values()) for host in result['hosts'].values()):
        result['status'] = 'blocked-preflight-gate'
    elif not all(host['perf_installed'] for host in result['hosts'].values()):
        result['status'] = 'blocked-no-validated-cpu-sampler'
    else:
        result['status'] = 'ready'
    result['execution_implemented'] = True
    result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (directory / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'ready' else 2



def controller():
    import run
    if preflight():
        raise RuntimeError('Profile readiness gate failed')
    root = run.ROOT
    local = root / 'deployment/hetzner/results' / NAMESPACE
    local.mkdir(mode=0o700, exist_ok=True)
    os.umask(0o077)
    # Exclusive creation is the once-only experiment gate; never remove this marker.
    with (local / 'launch-reserved.json').open('x') as stream:
        json.dump({'utc_ns': time.time_ns(), 'pid': os.getpid()}, stream)

    def ssh(role, command):
        host = run.HOSTS[role]
        try:
            result = subprocess.run(
                ['ssh', '-i', str(run.KEY), *run.SSH_OPTIONS,
                 host['ssh_user'] + '@' + host['ipv4'], command],
                capture_output=True, text=True, timeout=90,
            )
        except subprocess.TimeoutExpired:
            # TimeoutExpired includes the SSH address in its default message.
            raise RuntimeError(role + ' remote command timed out') from None
        with (local / 'commands.ndjson').open('a') as output:
            output.write(json.dumps({'utc_ns': time.time_ns(), 'role': role,
                                    'command': command, 'rc': result.returncode,
                                    'stdout': result.stdout, 'stderr': result.stderr}) + '\n')
        if result.returncode:
            raise RuntimeError(role + ' remote command failed; see private commands.ndjson')
        return result.stdout

    def copy(role, source, destination):
        host = run.HOSTS[role]
        result = subprocess.run(['scp', '-q', '-i', str(run.KEY), *run.SSH_OPTIONS,
                                 str(source), host['ssh_user'] + '@' + host['ipv4'] + ':' + destination],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(role + ' upload failed')

    def snapshot(role, label):
        commands = {
            'binary': 'sha256sum ' + BINARIES[role],
            'disk': 'df --output=avail -B1 /home/deploy | tail -1',
            'qdisc': 'tc -j qdisc show dev eth0',
            'egress': 'tc -j filter show dev eth0 egress',
            'ingress': 'tc -j filter show dev eth0 ingress',
            'nft': 'sudo -n nft list ruleset',
            'services': 'systemctl show ' + SERVICE + ' apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState -p MainPID -p NRestarts',
            'processes': 'ps -eo pid,comm,args',
            'sockets': 'sudo -n ss -u -a -m -n -p -e',
            'closed_states': "find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
        }
        if role == 'game':
            commands.update(config='cat /etc/omega-loadtest/arena.json',
                            unit='systemctl cat ' + SERVICE,
                            metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics')
        data = {key: ssh(role, command) for key, command in commands.items()}
        dump(local / f'{role}-{label}.json', data)
        return data

    states = {}
    for role in ('game', 'bots'):
        state = snapshot(role, 'before')
        states[role] = state
        if state['binary'].split()[0] != PINNED[role]:
            raise RuntimeError(role + ' binary mismatch')
        if int(state['disk']) < 8 * 1024**3:
            raise RuntimeError(role + ' insufficient disk')
        if any(q['kind'] != 'fq_codel' for q in json.loads(state['qdisc'])):
            raise RuntimeError(role + ' nonnative qdisc')
        if json.loads(state['egress']) or json.loads(state['ingress']):
            raise RuntimeError(role + ' unexpected network filters')
        if 'omega_measure' in state['nft']:
            raise RuntimeError(role + ' existing network collector')
        for line in state['processes'].splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 3 or parts[1] in ('bash', 'sshd', 'sshd-session'):
                continue
            if parts[1] in ('omega-load-test', 'tcpdump', 'perf', 'bpftrace', 'apt', 'apt-get', 'dpkg', 'rustc', 'cargo') or any(x in parts[2] for x in ('host_collect.py', 'capture.py', 'flow-record', 'udp_profile.py')):
                raise RuntimeError(role + ' occupied host')
        if role == 'game':
            expected = json.loads((root / 'deployment/server_config.loadtest.json').read_text())
            if json.loads(state['config']) != expected:
                raise RuntimeError('Native config differs')
            if not re.search(r'^players_online 0$', state['metrics'], re.M):
                raise RuntimeError('Game host has players or unavailable population')
            if len(re.findall(r'^\s*\d+ omega-server\s', state['processes'], re.M)) != 1:
                raise RuntimeError('Unexpected game process ownership')
    dump(local / 'preflight-proof.json', {'passed': True, 'utc_ns': time.time_ns(), 'pinned': PINNED})
    manifest = {'namespace': NAMESPACE, 'requested_bots': 200, 'behavior': 'strategy',
                'ramp_limit_s': RAMP_SECONDS, 'steady_limit_s': STEADY_SECONDS,
                'input_hz': 30, 'seed': 30, 'stagger_ms': 100, 'difficulty': 1.0,
                'game_config': json.loads(states['game']['config']), 'pinned': PINNED,
                'ramp_input_cadence': None, 'generator_valid': None,
                'profile': {'event': 'cpu-clock', 'frequency_hz': 99, 'call_graph': 'dwarf,8192', 'duration_s': 58, 'max_file_bytes': 67108864},
                'classification': 'diagnostic-only', 'collector_cadence_s': 1,
                'collector_overhead_effect': None, 'packet_capture': False,
                'controller_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                'host_collector_sha256': hashlib.sha256((root / 'scripts/load_campaign/host_collect.py').read_bytes()).hexdigest(),
                'abort_policy': 'First join failure; ramp 180s; phase2 120s; authenticated <65% of peak >=100 for two 2s polls; missing game progress >10s; log >8MiB',
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    dump(local / 'manifest.json', manifest)
    (local / 'udp_profile.executed.py').write_bytes(pathlib.Path(__file__).read_bytes())
    (local / 'udp_profile_record.executed.py').write_bytes((root / 'scripts/load_campaign/udp_profile_record.py').read_bytes())
    staged = []
    game_stopped = False
    override_installed = False
    cleanup = {}
    try:
        for role in ('game', 'bots'):
            ssh(role, 'umask 077; mkdir ' + REMOTE + '; mkdir ' + REMOTE + '/' + role + ' ' + REMOTE + '/original')
            staged.append(role)
            ssh(role, 'cp --reflink=auto ' + BINARIES[role] + ' ' + REMOTE + '/original/; sha256sum ' + REMOTE + '/original/*')
            for name in ('udp_profile.py', 'udp_profile_record.py', 'host_collect.py'):
                copy(role, root / 'scripts/load_campaign' / name, REMOTE + '/' + name)
        # Freeze old evidence before any service restart can truncate it.
        ssh('game', 'sudo -n systemctl stop ' + SERVICE)
        game_stopped = True
        preserve = ('set -e; cp -a --reflink=auto /var/lib/omega-measure/current ' + REMOTE + '/original/measurement-current; '
                    'cp -a /etc/omega-loadtest/arena.json ' + REMOTE + '/original/arena.json; '
                    'cp -a /etc/systemd/system/omega-loadtest-arena.service.d/measurement.conf ' + REMOTE + '/original/measurement.conf; '
                    'cd /var/lib/omega-measure/current; find . -type f -exec sha256sum {} \\; > ' + REMOTE + '/original/measurement-sha256.txt; '
                    'cd ' + REMOTE + '/original/measurement-current; sha256sum -c ../measurement-sha256.txt')
        ssh('game', preserve)
        backup_proof = ssh('game', 'cat ' + REMOTE + '/original/measurement-sha256.txt')
        (local / 'preserved-measurement-sha256.txt').write_text(backup_proof)
        override = '[Service]\nEnvironment=OMEGA_MEASURE_DIR=' + REMOTE + '/game\nReadWritePaths=' + REMOTE + '/game\n'
        (local / 'diagnostic.conf').write_text(override)
        copy('game', local / 'diagnostic.conf', REMOTE + '/diagnostic.conf')
        restore = '#!/bin/sh\nset -e\nif test -f ' + OVERRIDE + '; then\n systemctl stop ' + SERVICE + '\n rm ' + OVERRIDE + '\n systemctl daemon-reload\n systemctl start ' + SERVICE + '\nfi\n'
        (local / 'restore.sh').write_text(restore)
        copy('game', local / 'restore.sh', REMOTE + '/restore.sh')
        ssh('game', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-restore --on-active=420s /bin/sh ' + REMOTE + '/restore.sh')
        ssh('game', 'sudo -n mkdir -p ' + str(pathlib.PurePosixPath(OVERRIDE).parent) + '; sudo -n install -m 0644 ' + REMOTE + '/diagnostic.conf ' + OVERRIDE + '; sudo -n systemctl daemon-reload')
        override_installed = True
        ssh('game', 'sudo -n systemctl start ' + SERVICE)
        time.sleep(2)
        invocation = ssh('game', 'systemctl show ' + SERVICE + ' -p InvocationID --value').strip()
        manifest['service_invocation'] = invocation
        manifest['fresh_socket'] = ssh('game', 'sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"')
        if 'd0)' not in manifest['fresh_socket'] or 'rb524288' not in manifest['fresh_socket']:
            raise RuntimeError('Fresh socket buffer/drop gate failed')
        for role in ('game', 'bots'):
            command = 'exec python3 ' + REMOTE + '/udp_profile.py collect --role ' + role
            ssh(role, 'sudo -n systemd-run --quiet --unit=' + UNIT + '-' + role + '-collect --property=RuntimeMaxSec=350 --property=TimeoutStopSec=8 /bin/sh -c ' + shlex.quote(command))
        time.sleep(2)
        argv = [BINARIES['bots'], '--server', run.HOSTS['game']['ipv4'] + ':8081',
                '--bots', '200', '--behavior', 'strategy', '--duration', str(STEADY_SECONDS),
                '--input-hz', '30', '--seed', '30', '--stagger', '100', '--difficulty', '1.0',
                '--bandwidth-budget', '0', '--assertions', 'strict', '--aoi-exit-radius', '1100',
                '--output', REMOTE + '/bots/bot.json']
        dump(local / 'invocation.json', {'argv': argv})
        copy('bots', local / 'invocation.json', REMOTE + '/bots/invocation.json')
        manifest['command'] = shlex.join(argv)
        game_pid = int(ssh('game', 'systemctl show ' + SERVICE + ' -p MainPID --value'))
        manifest['game_pid'] = game_pid
        ssh('game', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-game-profile '
            '--property=RuntimeMaxSec=59 --property=TimeoutStopSec=1 --property=LimitFSIZE=67108864 '
            'python3 ' + REMOTE + '/udp_profile_record.py record --pid ' + str(game_pid) +
            ' --directory ' + REMOTE + '/game')
        ssh('game', 'for i in $(seq 1 40); do test ! -f ' + REMOTE +
            '/game/profile-ready.json || exit 0; sleep .1; done; exit 1')
        manifest['swarm_start_utc_ns'] = time.time_ns()
        dump(local / 'manifest.json', manifest)
        ssh('bots', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-swarm --uid=deploy --property=LimitNOFILE=8192 --property=KillMode=mixed --property=TimeoutStopSec=10 --property=RuntimeMaxSec=305 python3 ' + REMOTE + '/udp_profile.py swarm')
        print('Single Strategy 200 diagnostic started', flush=True)
        started = time.monotonic()
        peak = 0
        collapsed = 0
        while time.monotonic() - started < 305:
            status = ssh('bots', 'if test -f ' + REMOTE + '/bots/guard-result.json; then cat ' + REMOTE + '/bots/guard-result.json; fi')
            if status:
                manifest['guard_result'] = json.loads(status)
                break
            latest = ssh('game', 'tail -1 ' + REMOTE + '/game/server.ndjson')
            if latest:
                sample = json.loads(latest)
                if time.time_ns() - sample['utc_ns'] > 10e9:
                    manifest['controller_abort'] = 'game-observation-stale-over-10s'
                    break
                population = len(sample['players'])
                peak = max(peak, population)
                collapsed = collapsed + 1 if peak >= 100 and population < .65 * peak else 0
                if collapsed >= 2:
                    manifest['controller_abort'] = 'authenticated-population-below-65-percent-peak'
                    break
            time.sleep(2)
        else:
            manifest['controller_abort'] = 'overall-time-limit'
        manifest['controller_observed_peak'] = peak
    except Exception as error:
        manifest['controller_error'] = str(error)
        raise
    finally:
        # Attempt both endpoints even if one fails. Do not remove remote evidence.
        for role in reversed(staged):
            for suffix in (role + '-profile',):
                try:
                    ssh(role, 'sudo -n systemctl stop ' + UNIT + '-' + suffix + ' || '
                        '{ test "$(systemctl show ' + UNIT + '-' + suffix + ' -p ActiveState --value)" = inactive; }')
                except Exception as error:
                    cleanup.setdefault(role, {})['profile_stop_error'] = str(error)
            # Evidence collection must not prevent any independent release.
            actions = [('final_socket_snapshot', 'sudo -n ss -u -a -m -n -p -e > ' + REMOTE + '/' + role + '/final-sockets.txt; cat /proc/net/snmp > ' + REMOTE + '/' + role + '/final-snmp.txt')]
            if role == 'bots':
                actions.append(('swarm_stop', 'sudo -n systemctl stop ' + UNIT + '-swarm || { test "$(systemctl show ' + UNIT + '-swarm -p ActiveState --value)" = inactive; }'))
            elif game_stopped:
                actions.append(('game_stop', 'sudo -n systemctl stop ' + SERVICE))
                if manifest.get('service_invocation'):
                    actions.append(('game_log', 'journalctl _SYSTEMD_INVOCATION_ID=' + manifest['service_invocation'] + ' --no-pager -o short-iso-precise -n 4000 > ' + REMOTE + '/game/game.log'))
            for suffix in ('collect',):
                unit = UNIT + '-' + role + '-' + suffix
                actions.append((suffix + '_stop', 'sudo -n systemctl stop ' + unit + ' || { test "$(systemctl show ' + unit + ' -p ActiveState --value)" = inactive; }'))
            for label, command in actions:
                try:
                    ssh(role, command)
                    cleanup.setdefault(role, {})[label] = True
                except Exception as error:
                    cleanup.setdefault(role, {})[label + '_error'] = type(error).__name__
        if game_stopped:
            try:
                if override_installed:
                    ssh('game', 'sudo -n /bin/sh ' + REMOTE + '/restore.sh')
                else:
                    ssh('game', 'sudo -n systemctl start ' + SERVICE)
                ssh('game', 'sudo -n systemctl stop ' + UNIT + '-restore.timer')
                cleanup.setdefault('game', {})['restored'] = True
            except Exception as error:
                cleanup.setdefault('game', {})['restore_error'] = str(error)
        for role in staged:
            try:
                after = snapshot(role, 'after')
                cleanup[role]['binary_unchanged'] = after['binary'] == states[role]['binary']
                cleanup[role]['qdisc_unchanged'] = after['qdisc'] == states[role]['qdisc']
                cleanup[role]['filters_unchanged'] = all(after[k] == states[role][k] for k in ('egress', 'ingress'))
                # Firewall counters naturally increase; compare rules with counters stripped.
                strip = lambda value: re.sub(r'counter packets \d+ bytes \d+', 'counter', value)
                cleanup[role]['firewall_unchanged'] = strip(after['nft']) == strip(states[role]['nft'])
                cleanup[role]['closed_states_unchanged'] = after['closed_states'] == states[role]['closed_states']
                if role == 'game':
                    cleanup[role]['config_unchanged'] = after['config'] == states[role]['config']
                    cleanup[role]['unit_restored'] = after['unit'] == states[role]['unit']
                ssh(role, 'sudo -n env DEBUGINFOD_URLS= timeout 45 perf script --ns -i ' + REMOTE + '/' + role + '/perf.data '
                    '-F comm,pid,tid,time,event,ip,sym,dso,period > ' + REMOTE + '/' + role + '/perf-script.txt '
                    '2> ' + REMOTE + '/' + role + '/perf-script.log')
                ssh(role, 'sudo -n env DEBUGINFOD_URLS= timeout 30 perf report --stdio --header-only -i ' +
                    REMOTE + '/' + role + '/perf.data > ' + REMOTE + '/' + role + '/perf-header.txt 2>&1; '
                    'sudo -n env DEBUGINFOD_URLS= timeout 30 perf script -D -i ' + REMOTE + '/' + role +
                    '/perf.data | gzip > ' + REMOTE + '/' + role + '/perf-records.txt.gz')
                ssh(role, 'sudo -n chown -R deploy:deploy ' + REMOTE + '/' + role + '; tar -czf ' + REMOTE + '/' + role + '.tar.gz -C ' + REMOTE + ' ' + role)
                # run.copy verifies remote/local SHA-256 before its atomic rename.
                run.copy(role, REMOTE + '/' + role + '.tar.gz', local / (role + '.tar.gz'), download=True)
                cleanup[role]['archive_sha256'] = hashlib.sha256((local / (role + '.tar.gz')).read_bytes()).hexdigest()
                cleanup[role]['remote_evidence_retained'] = True
            except Exception as error:
                cleanup.setdefault(role, {})['verification_error'] = type(error).__name__
        manifest['ended_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            dump(local / 'manifest.json', manifest)
        except Exception as error:
            cleanup.setdefault('controller', {})['manifest_write_error'] = type(error).__name__
        dump(local / 'cleanup.json', cleanup)
        print(json.dumps({'completed': True, 'controller_abort': manifest.get('controller_abort'),
                          'guard_reason': ((manifest.get('guard_result') or {}).get('reason') or {}).get('kind'),
                          'cleanup_archive_roles': [r for r in cleanup if 'archive_sha256' in cleanup[r]]}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('preflight', 'run', 'collect', 'swarm'))
    parser.add_argument('--role', choices=('game', 'bots'))
    args = parser.parse_args()
    if args.mode == 'preflight':
        raise SystemExit(preflight())
    elif args.mode == 'collect':
        collect(args.role)
    elif args.mode == 'swarm':
        swarm()
    else:
        try:
            controller()
        except Exception as error:
            # Detailed subprocess errors/addresses stay in the private command journal.
            print('Profile stopped: ' + str(error), file=sys.stderr)
            sys.exit(1)
