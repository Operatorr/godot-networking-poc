#!/usr/bin/env python3
"""One issue-38 collector-only comparison against the completed bitmap diagnostic; private evidence, no historical campaign imports.

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
import shutil
import subprocess
import sys
import time

NAMESPACE = 'udp-bounded-20261021'
REMOTE = '/home/deploy/omega-results/' + NAMESPACE
UNIT = 'omega-' + NAMESPACE
SERVICE = 'omega-loadtest-arena.service'
OVERRIDE = '/run/systemd/system/' + SERVICE + '.d/zz-udp-bounded.conf'
BINARIES = {
    'game': '/home/deploy/omega-stabilized-b1266c1/rust/target/release/omega-server',
    'bots': '/home/deploy/omega-measured/rust/target/release/omega-load-test',
}
PINNED = {
    'game': 'f2bf76c6fa3c28b7fb9b5d52f216061e9c3239999d67bf8a42acadf44dada3a2',
    'bots': '8af491831304e1ab913089e3b8f1750ea701e4ccd8993d834bcc30ecfa3e8bdf',
}
CONTROL_CHECKOUT = '/home/deploy/omega-udp-control-cc86869'
CONTROL_BINARIES = {role: CONTROL_CHECKOUT + '/rust/target/release/' + ('omega-server' if role == 'game' else 'omega-load-test') for role in ('game', 'bots')}
CANDIDATE_CHECKOUT = '/home/deploy/omega-udp-bitmap-1d15d84'
CANDIDATE_REVISION = '1d15d84a86164af4e2d34db633bcd3828836b3d6'
COLLECTOR_REVISION = '30ec7925008ffd882bd5d46d32810d4ec39f754f'
EXPERIMENT_BINARIES = dict(CONTROL_BINARIES, game=CANDIDATE_CHECKOUT + '/rust/target/release/omega-server')
EXPECTED_CONTROL = {
    'game': '5a36a7aaf3bed4db46efd2a4200c4e02825ef3598d0c4990a672d279c051a202',
    'bots': '831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3',
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
    if hashlib.sha256(pathlib.Path(spec['argv'][0]).read_bytes()).hexdigest() != EXPECTED_CONTROL['bots']:
        raise RuntimeError('Bot executable hash mismatch')
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
        child = subprocess.Popen(spec['argv'], stdout=output, stderr=subprocess.STDOUT, env=env)
        dump(directory / 'workload-start.json', {'pid': child.pid, 'utc_ns': time.time_ns(), 'runtime_sha256': hashlib.sha256(pathlib.Path(f'/proc/{child.pid}/exe').read_bytes()).hexdigest()})
        try:
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
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            dump(directory / 'guard-result.json', {
                'reason': reason, 'exit_code': child.returncode,
                'elapsed_s': time.monotonic() - started, 'ended_utc_ns': time.time_ns(),
            })


def controller():
    import run
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
            'experiment_binary': 'sha256sum ' + EXPERIMENT_BINARIES[role],
            'experiment_revision': 'git -C ' + (CANDIDATE_CHECKOUT if role == 'game' else CONTROL_CHECKOUT) + ' rev-parse HEAD',
            'experiment_status': 'git -C ' + (CANDIDATE_CHECKOUT if role == 'game' else CONTROL_CHECKOUT) + ' status --porcelain',
            'control_binary': 'sha256sum ' + CONTROL_BINARIES[role],
            'revision': 'git -C ' + CONTROL_CHECKOUT + ' rev-parse HEAD',
            'toolchain': 'source /home/deploy/.cargo/env; rustc -Vv; cargo -V; uname -a; chronyc tracking',
            'buffers': 'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
            'disk': 'df --output=avail -B1 /home/deploy | tail -1',
            'qdisc': 'tc -j qdisc show dev eth0',
            'egress': 'tc -j filter show dev eth0 egress',
            'ingress': 'tc -j filter show dev eth0 ingress',
            'nft': 'sudo -n nft list ruleset',
            'namespace_absent': 'test ! -e ' + REMOTE + '; echo $?',
            'prior_archives': "set -o pipefail; find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) ! -path '" + REMOTE + "/*' -exec sha256sum {} \\; | sort",
            'namespace_inventory': "find /home/deploy/omega-results -mindepth 1 -maxdepth 1 -type d ! -name '" + NAMESPACE + "' -printf '%f\\n' | sort",
            'services': 'systemctl show ' + SERVICE + ' apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState -p MainPID -p NRestarts',
            'processes': 'ps -eo pid,comm,args',
            'sockets': 'sudo -n ss -u -a -m -n -p -e',
            'closed_states': "find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
        }
        if role == 'game':
            commands.update(config='cat /etc/omega-loadtest/arena.json',
                            unit='systemctl cat ' + SERVICE,
                            running_executable='pid=$(systemctl show ' + SERVICE + ' -p MainPID --value); sha256sum /proc/$pid/exe',
                            service_active='systemctl is-active ' + SERVICE,
                            metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics')
        data = {key: ssh(role, command) for key, command in commands.items()}
        dump(local / f'{role}-{label}.json', data)
        return data

    # Freeze repaired collectors and unchanged dependencies from the requested commit, never the moving working tree.
    sources = local / 'staged'
    sources.mkdir(exist_ok=True)
    names = ('host_collect.py', 'capture.py', 'udp_control_capture.py', 'udp_control_record.rs', 'udp_control_flow.rs')
    for name in names:
        blob = subprocess.check_output(['git', '-C', str(root), 'show', COLLECTOR_REVISION + ':scripts/load_campaign/' + name])
        (sources / name).write_bytes(blob)
    (local / 'udp_bounded.executed.py').write_bytes(pathlib.Path(__file__).read_bytes())
    expected_candidate = '29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421'
    if shutil.disk_usage(local).free < 8 * 1024**3:
        raise RuntimeError('Insufficient local evidence disk')
    states = {}
    for role in ('game', 'bots'):
        state = snapshot(role, 'before')
        states[role] = state
        if state['namespace_absent'].strip() != '0':
            raise RuntimeError(role + ' namespace already exists')
        if state['revision'].strip() != 'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb':
            raise RuntimeError(role + ' incorrect control revision')
        if state['experiment_binary'].split()[0] != (expected_candidate if role == 'game' else EXPECTED_CONTROL['bots']):
            raise RuntimeError(role + ' experiment artifact changed since build')
        if state['control_binary'].split()[0] != EXPECTED_CONTROL[role]:
            raise RuntimeError(role + ' control binary mismatch')
        if state['experiment_revision'].strip() != (CANDIDATE_REVISION if role == 'game' else 'cc86869f1cc0f3d5d219e880d08b2cfda312f4eb') or state['experiment_status'].strip():
            raise RuntimeError(role + ' incorrect experiment source')
        if state['binary'].split()[0] != PINNED[role]:
            raise RuntimeError(role + ' binary mismatch')
        if int(state['disk']) < 8 * 1024**3:
            raise RuntimeError(role + ' insufficient disk')
        if any(q['kind'] != 'fq_codel' for q in json.loads(state['qdisc'])):
            raise RuntimeError(role + ' nonnative qdisc')
        if json.loads(state['egress']) or json.loads(state['ingress']):
            raise RuntimeError(role + ' unexpected network filters')
        for block in state['services'].split('\n\n'):
            if 'Id=apt-daily.service' in block or 'Id=apt-daily-upgrade.service' in block:
                if 'ActiveState=inactive' not in block:
                    raise RuntimeError(role + ' maintenance job active')
        if 'omega_measure' in state['nft']:
            raise RuntimeError(role + ' existing network collector')
        for line in state['processes'].splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 3 or parts[1] in ('bash', 'sshd', 'sshd-session'):
                continue
            if parts[1] in ('omega-load-test', 'tcpdump', 'perf', 'bpftrace', 'apt', 'apt-get', 'dpkg', 'rustc', 'cargo') or any(x in parts[2] for x in ('host_collect.py', 'capture.py', 'flow-record', 'udp_control.py', 'udp_profile.py', 'udp_baseline.py', 'udp_control_capture.py', 'udp_bounded.py', 'udp_bitmap.py')):
                raise RuntimeError(role + ' occupied host')
        if role == 'game':
            if state['service_active'].strip() != 'active' or state['running_executable'].split()[0] != PINNED['game']:
                raise RuntimeError('Original service not active on original executable')
            if 'rb524288' not in state['sockets'] or 'tb524288' not in state['sockets']:
                raise RuntimeError('Original game socket buffers differ')
            expected = json.loads((root / 'deployment/server_config.loadtest.json').read_text())
            if hashlib.sha256(state['config'].encode()).hexdigest() != 'bac0bf8947937a334b4fd9e814e1e3a4e15b9753fd3f1c02e185285d26f0d68c':
                raise RuntimeError('Native config hash differs from control')
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
                'ramp_input_cadence': 'collected; analyze separately', 'generator_valid': None,
                'classification': 'diagnostic-only', 'intervention': 'collector 30ec792 only; game and bots unchanged from bitmap', 'workloads_launched': 0, 'collector_cadence_s': 1,
                'collector_overhead_effect': None, 'packet_capture': 'compact-article-plus-per-port-1Hz',
                'experiment_binary_sha256': {r: s['experiment_binary'].split()[0] for r, s in states.items()},
                'candidate_revision': CANDIDATE_REVISION, 'collector_revision': COLLECTOR_REVISION,
                'collector_source_sha256': {n: hashlib.sha256((sources / n).read_bytes()).hexdigest() for n in names},
                'control_binary_sha256': {r: s['control_binary'].split()[0] for r, s in states.items()},
                'controller_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                'host_collector_sha256': hashlib.sha256((sources / 'host_collect.py').read_bytes()).hexdigest(),
                'abort_policy': 'First join failure; ramp 180s; phase2 120s; authenticated <65% of peak >=100 for two 2s polls; missing game progress >10s; log >8MiB',
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    dump(local / 'manifest.json', manifest)
    staged = []
    game_stopped = False
    override_installed = False
    restoration_armed = False
    cleanup = {}
    try:
        for role in ('game', 'bots'):
            ssh(role, 'umask 077; mkdir ' + REMOTE + '; mkdir ' + REMOTE + '/' + role + ' ' + REMOTE + '/original')
            staged.append(role)
            ssh(role, 'cp --reflink=auto ' + BINARIES[role] + ' ' + REMOTE + '/original/; sha256sum ' + REMOTE + '/original/*')
            copy(role, pathlib.Path(__file__), REMOTE + '/udp_bounded.py')
            for name in names:
                copy(role, sources / name, REMOTE + '/' + name)
            ssh(role, 'source /home/deploy/.cargo/env; rustc --edition=2021 -O ' + REMOTE + '/udp_control_record.rs -o ' + REMOTE + '/flow-record')
            ssh(role, 'sha256sum ' + REMOTE + '/*.py ' + REMOTE + '/*.rs ' + REMOTE + '/flow-record > ' + REMOTE + '/' + role + '/collector-sha256.txt')
        restore = '#!/bin/sh\nset -e\nif test -f ' + OVERRIDE + '; then\n systemctl stop ' + SERVICE + '\n rm ' + OVERRIDE + '\n systemctl daemon-reload\nfi\nsystemctl start ' + SERVICE + '\n'
        (local / 'restore.sh').write_text(restore)
        copy('game', local / 'restore.sh', REMOTE + '/restore.sh')
        ssh('game', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-restore --on-active=420s /bin/sh ' + REMOTE + '/restore.sh')
        restoration_armed = True
        # Freeze old evidence before any service restart can truncate it.
        game_stopped = True
        ssh('game', 'sudo -n systemctl stop ' + SERVICE)
        preserve = ('set -e; cp -a --reflink=auto /var/lib/omega-measure/current ' + REMOTE + '/original/measurement-current; '
                    'cp -a /etc/omega-loadtest/arena.json ' + REMOTE + '/original/arena.json; '
                    'cp -a /etc/systemd/system/omega-loadtest-arena.service.d/measurement.conf ' + REMOTE + '/original/measurement.conf; '
                    'cd /var/lib/omega-measure/current; find . -type f -exec sha256sum {} \\; > ' + REMOTE + '/original/measurement-sha256.txt; '
                    'cd ' + REMOTE + '/original/measurement-current; sha256sum -c ../measurement-sha256.txt')
        ssh('game', preserve)
        backup_proof = ssh('game', 'cat ' + REMOTE + '/original/measurement-sha256.txt')
        (local / 'preserved-measurement-sha256.txt').write_text(backup_proof)
        override = '[Service]\nExecStart=\nExecStart=' + EXPERIMENT_BINARIES['game'] + ' --config /etc/omega-loadtest/arena.json --allow-unsigned-tickets\nEnvironment=OMEGA_MEASURE_DIR=' + REMOTE + '/game\nReadWritePaths=' + REMOTE + '/game\n'
        (local / 'diagnostic.conf').write_text(override)
        copy('game', local / 'diagnostic.conf', REMOTE + '/diagnostic.conf')
        ssh('game', 'sudo -n mkdir -p ' + str(pathlib.PurePosixPath(OVERRIDE).parent) + '; sudo -n install -m 0644 ' + REMOTE + '/diagnostic.conf ' + OVERRIDE + '; sudo -n systemctl daemon-reload')
        override_installed = True
        ssh('game', 'sudo -n systemctl start ' + SERVICE)
        time.sleep(2)
        invocation = ssh('game', 'systemctl show ' + SERVICE + ' -p InvocationID --value').strip()
        manifest['service_invocation'] = invocation
        manifest['running_game_executable_sha256'] = ssh('game', 'pid=$(systemctl show ' + SERVICE + ' -p MainPID --value); sha256sum /proc/$pid/exe').split()[0]
        if manifest['running_game_executable_sha256'] != manifest['experiment_binary_sha256']['game']:
            raise RuntimeError('Running game is not candidate build')
        manifest['fresh_socket'] = ssh('game', 'sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"')
        if 'd0)' not in manifest['fresh_socket'] or 'rb524288' not in manifest['fresh_socket'] or 'tb524288' not in manifest['fresh_socket']:
            raise RuntimeError('Fresh socket buffer/drop gate failed')
        for role in ('game', 'bots'):
            command = 'exec python3 ' + REMOTE + '/udp_bounded.py collect --role ' + role
            ssh(role, 'sudo -n systemd-run --quiet --unit=' + UNIT + '-' + role + '-collect --property=RuntimeMaxSec=350 --property=TimeoutStopSec=8 /bin/sh -c ' + shlex.quote(command))
        time.sleep(2)
        for role in ('game', 'bots'):
            dump(local / 'capture-window.json', {'start': 0, 'end': time.time_ns() + 310_000_000_000})
            copy(role, local / 'capture-window.json', REMOTE + '/' + role + '/window.json')
            peer = run.HOSTS['bots' if role == 'game' else 'game']['ipv4']
            command = 'exec python3 ' + REMOTE + '/udp_control_capture.py ' + REMOTE + '/' + role + ' eth0 ' + peer
            ssh(role, 'sudo -n systemd-run --quiet --unit=' + UNIT + '-' + role + '-capture --property=KillMode=mixed --property=RuntimeMaxSec=310 --property=TimeoutStopSec=12 --property=MemoryMax=536870912 --property=LimitFSIZE=67108864 /bin/sh -c ' + shlex.quote(command))
            ready = False
            for _ in range(15):
                if 'listening on' in ssh(role, 'cat ' + REMOTE + '/' + role + '/capture.log 2>/dev/null || true'):
                    ready = True
                    break
                time.sleep(.2)
            if not ready:
                raise RuntimeError(role + ' capture not ready')
            parser_state = json.loads(ssh(role, 'cat ' + REMOTE + '/' + role + '/parser-status.json'))
            if parser_state.get('status') != 'running':
                raise RuntimeError(role + ' parser not running')
        argv = [EXPERIMENT_BINARIES['bots'], '--server', run.HOSTS['game']['ipv4'] + ':8081',
                '--bots', '200', '--behavior', 'strategy', '--duration', str(STEADY_SECONDS),
                '--input-hz', '30', '--seed', '30', '--stagger', '100', '--difficulty', '1.0',
                '--bandwidth-budget', '0', '--assertions', 'strict', '--aoi-exit-radius', '1100',
                '--output', REMOTE + '/bots/bot.json']
        dump(local / 'invocation.json', {'argv': argv})
        copy('bots', local / 'invocation.json', REMOTE + '/bots/invocation.json')
        manifest['command'] = shlex.join(argv)
        manifest['swarm_start_utc_ns'] = time.time_ns()
        dump(local / 'manifest.json', manifest)
        ssh('bots', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-swarm --uid=deploy --property=LimitNOFILE=8192 --property=KillMode=mixed --property=TimeoutStopSec=10 --property=RuntimeMaxSec=305 python3 ' + REMOTE + '/udp_bounded.py swarm')
        manifest['workloads_launched'] = 1
        dump(local / 'manifest.json', manifest)
        print('Single Strategy 200 collector diagnostic started', flush=True)
        started = time.monotonic()
        peak = 0
        collapsed = 0
        while time.monotonic() - started < 305:
            status = ssh('bots', 'if test -f ' + REMOTE + '/bots/guard-result.json; then cat ' + REMOTE + '/bots/guard-result.json; fi')
            if status:
                manifest['guard_result'] = json.loads(status)
                break
            for role in ('game', 'bots'):
                check = ssh(role, 'for f in capture-resource.json parser-status.json; do if test -f ' + REMOTE + '/' + role + '/$f; then cat ' + REMOTE + '/' + role + '/$f; fi; done')
                statuses = [json.loads(line) for line in check.splitlines() if line]
                if any(s.get('status') in ('error', 'eof') or 'reason' in s for s in statuses):
                    manifest['controller_abort'] = role + '-collector-ended-during-workload'
                    manifest['collector_guard_status'] = statuses
                    break
            if manifest.get('controller_abort'):
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
        # Each stop is independent: a failed snapshot must not skip termination.
        for role in staged:
            cleanup[role] = {}
            actions = [('final_socket_snapshot', 'sudo -n ss -u -a -m -n -p -e > ' + REMOTE + '/' + role + '/final-sockets.txt; cat /proc/net/snmp > ' + REMOTE + '/' + role + '/final-snmp.txt')]
            if role == 'bots':
                actions.append(('swarm_stop', 'sudo -n systemctl stop ' + UNIT + '-swarm || { test "$(systemctl show ' + UNIT + '-swarm -p ActiveState --value)" = inactive; }'))
            elif game_stopped:
                actions.append(('game_stop', 'sudo -n systemctl stop ' + SERVICE))
                if manifest.get('service_invocation'):
                    actions.append(('game_log', 'journalctl _SYSTEMD_INVOCATION_ID=' + manifest['service_invocation'] + ' --no-pager -o short-iso-precise -n 4000 > ' + REMOTE + '/game/game.log'))
            for suffix in ('capture', 'collect'):
                unit = UNIT + '-' + role + '-' + suffix
                actions.append((suffix + '_stop', 'sudo -n systemctl stop ' + unit + ' || { test "$(systemctl show ' + unit + ' -p ActiveState --value)" = inactive; }'))
            for label, command in actions:
                try:
                    ssh(role, command)
                    cleanup[role][label] = True
                except Exception as error:
                    cleanup[role][label + '_error'] = type(error).__name__
        if game_stopped:
            try:
                if restoration_armed:
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
                cleanup[role]['experiment_binary_unchanged'] = after['experiment_binary'] == states[role]['experiment_binary']
                cleanup[role]['control_binary_unchanged'] = after['control_binary'] == states[role]['control_binary']
                cleanup[role]['binary_unchanged'] = after['binary'] == states[role]['binary']
                cleanup[role]['qdisc_unchanged'] = after['qdisc'] == states[role]['qdisc']
                cleanup[role]['filters_unchanged'] = all(after[k] == states[role][k] for k in ('egress', 'ingress'))
                # Firewall counters naturally increase; compare rules with counters stripped.
                strip = lambda value: re.sub(r'counter packets \d+ bytes \d+', 'counter', value)
                cleanup[role]['firewall_unchanged'] = strip(after['nft']) == strip(states[role]['nft'])
                cleanup[role]['buffers_unchanged'] = after['buffers'] == states[role]['buffers']
                cleanup[role]['prior_archives_unchanged'] = after['prior_archives'] == states[role]['prior_archives']
                cleanup[role]['namespace_inventory_unchanged'] = after['namespace_inventory'] == states[role]['namespace_inventory']
                maintenance = lambda value: re.sub(r'^MainPID=.*$', '', value, flags=re.M)
                cleanup[role]['maintenance_states_unchanged'] = maintenance(after['services']) == maintenance(states[role]['services'])
                cleanup[role]['closed_states_unchanged'] = after['closed_states'] == states[role]['closed_states']
                if role == 'game':
                    cleanup[role]['config_unchanged'] = after['config'] == states[role]['config']
                    cleanup[role]['unit_restored'] = after['unit'] == states[role]['unit']
                    cleanup[role]['original_executable_active'] = after['service_active'].strip() == 'active' and after['running_executable'].split()[0] == PINNED['game']
                    cleanup[role]['zero_players'] = bool(re.search(r'^players_online 0$', after['metrics'], re.M))
                    ssh(role, 'cd ' + REMOTE + '/original/measurement-current; sha256sum -c ../measurement-sha256.txt')
                    cleanup[role]['preserved_measurement_verified'] = True
                live = ssh(role, 'systemctl list-units --all --no-legend ' + shlex.quote(UNIT + '-*'))
                cleanup[role]['owned_active_units_absent'] = not re.search(r'\sactive\s', live)
                if not cleanup[role]['owned_active_units_absent']:
                    raise RuntimeError('Owned units still active; refusing archive')
                ssh(role, 'sudo -n chown -R deploy:deploy ' + REMOTE + '/' + role + '; tar -czf ' + REMOTE + '/' + role + '.tar.gz -C ' + REMOTE + ' ' + role)
                # run.copy verifies remote/local SHA-256 before its atomic rename.
                run.copy(role, REMOTE + '/' + role + '.tar.gz', local / (role + '.tar.gz'), download=True)
                cleanup[role]['archive_sha256'] = hashlib.sha256((local / (role + '.tar.gz')).read_bytes()).hexdigest()
                cleanup[role]['archive_remote_sha256'] = ssh(role, 'sha256sum ' + REMOTE + '/' + role + '.tar.gz').split()[0]
                if cleanup[role]['archive_remote_sha256'] != cleanup[role]['archive_sha256']:
                    raise RuntimeError('Independent archive checksum mismatch')
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
    parser.add_argument('mode', choices=('run', 'collect', 'swarm'))
    parser.add_argument('--role', choices=('game', 'bots'))
    args = parser.parse_args()
    if args.mode == 'collect':
        collect(args.role)
    elif args.mode == 'swarm':
        swarm()
    else:
        try:
            controller()
        except Exception as error:
            # Detailed subprocess errors/addresses stay in the private command journal.
            print('Bounded collector diagnostic stopped: ' + type(error).__name__, file=sys.stderr)
            sys.exit(1)
