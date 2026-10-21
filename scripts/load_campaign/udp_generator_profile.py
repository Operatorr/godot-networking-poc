#!/usr/bin/env python3
"""Exactly one Strategy 150 diagnostic under GENERATOR-PROFILE-PLAN.md.

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
from atomic_publish import publish_file

NAMESPACE = 'udp-generator-profile-20261021'
REMOTE = '/home/deploy/omega-results/' + NAMESPACE
UNIT = 'omega-' + NAMESPACE
SERVICE = 'omega-loadtest-arena.service'
OVERRIDE = '/run/systemd/system/' + SERVICE + '.d/zz-udp-generator-profile.conf'
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
CANDIDATE_CHECKOUT = '/home/deploy/omega-udp-buffer-f1cc5d6'
CANDIDATE_REVISION = 'f1cc5d645217ddc14a4069c3fe40992d496270ae'
COLLECTOR_REVISION = '994cce8c7cb2f689cd59f4d09e93e270057aba7e'
EXPERIMENT_BINARIES = dict(CONTROL_BINARIES, game=CANDIDATE_CHECKOUT + '/rust/target/release/omega-server')
EXPECTED_CONTROL = {
    'game': '5a36a7aaf3bed4db46efd2a4200c4e02825ef3598d0c4990a672d279c051a202',
    'bots': '831be66a76278a39513c8c229811a951264604af0ddbc911d2852b9e0f72bbf3',
}
RAMP_SECONDS = 180
STEADY_SECONDS = 360
EXPECTED_CANDIDATE = "dd0bd322940ac9cff94e8e5191c0a4a22606634f647dfffd8953bf47570d1b56"


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
    boundaries = None
    with gzip.open(directory / 'host.ndjson.gz', 'xt') as output:
        while not stopped and time.monotonic() - started < 600:
            before = time.monotonic()
            if boundaries is None and (directory/'window.json').exists():
                boundaries = json.loads((directory/'window.json').read_text())
            sample = host_collect.sample(role, UNIT + '-swarm' if role == 'bots' else None)
            if boundaries:
                due = [(name,stamp) for name,stamp in boundaries.items() if stamp <= sample['utc_ns']]
                if due:
                    name,stamp = min(due,key=lambda item:item[1])
                    sample['boundary'] = name
                    sample['target_utc_ns'] = stamp
                    boundaries.pop(name)
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
                if time.monotonic() - started >= 550:
                    reason = {'kind': 'workload-hard-time-limit'}
                    break
                if not phase.exists() and time.monotonic() - started >= RAMP_SECONDS:
                    reason = {'kind': 'ramp-timeout'}
                    break
                if phase.exists():
                    stamp = json.loads(phase.read_text())['phase2_utc_ns']
                    if time.time_ns() >= stamp + (STEADY_SECONDS + 10) * 1_000_000_000:
                        reason = {'kind': 'postjoin-exit-timeout'}
                        break
                if (directory / 'bot.log').stat().st_size > 24 * 1024**2:
                    reason = {'kind': 'bounded-log-limit'}
                    break
                time.sleep(0.5)
        finally:
            decision_ns = time.time_ns()
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            dump(directory / 'guard-result.json', {
                'reason': reason, 'decision_utc_ns': decision_ns, 'exit_code': child.returncode,
                'elapsed_s': time.monotonic() - started, 'ended_utc_ns': time.time_ns(),
            })


def command(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=8)
    if result.returncode: raise RuntimeError('Status command failed: '+args[0])
    return result.stdout


def tail_json(path):
    if not path.exists(): return None
    with path.open('rb') as f:
        f.seek(max(0,path.stat().st_size-512*1024))
        lines=f.read().splitlines()
    for line in reversed(lines):
        try: return json.loads(line)
        except (ValueError,UnicodeDecodeError): pass
    return None


def status(role):
    import csv
    d=pathlib.Path(REMOTE)/role
    def read(name):
        try:return json.loads((d/name).read_text())
        except FileNotFoundError:return None
    result={'utc_ns':time.time_ns(),'parser':read('parser-status.json') or {},
            'capture_resource':read('capture-resource.json'),
            'mapping':[[int(r['port']),int(r['bot_id'])] for r in csv.DictReader((d/'port-bot.csv').open())] if (d/'port-bot.csv').exists() else [],
            'host_fresh':(d/'host.ndjson.gz').exists() and time.time()-(d/'host.ndjson.gz').stat().st_mtime<10}
    if role=='game':
        props=command(['systemctl','show',SERVICE,'-p','MainPID','-p','InvocationID','-p','ActiveState','-p','NRestarts'])
        result['identity']=dict(line.split('=',1) for line in props.splitlines())
        pid=result['identity']['MainPID']
        result['exe_sha256']=hashlib.sha256(pathlib.Path('/proc/'+pid+'/exe').read_bytes()).hexdigest() if pid!='0' else None
        result['sockets']=command(['sudo','-n','ss','-u','-a','-m','-n','-p','-e','( sport = :8081 )'])
        result['server']=tail_json(d/'server.ndjson')
        result['metrics']=command(['curl','-fsS','--max-time','3','http://127.0.0.1:9100/metrics'])
    else:
        result['profile_supervisor']=read('profile-supervisor-status.json')
        result['profiles']={name:read(name+'/profile-status.json') for name in ('early','late')}
        result['phase']=read('phase.json')
        result['guard']=read('guard-result.json')
        start=read('workload-start.json')
        if start and pathlib.Path('/proc/'+str(start['pid'])).exists():
            from udp_generator_profile_record import identity
            result['bot_identity']=identity(start['pid'])
        row=tail_json(d/'bots.ndjson')
        result['bots_stamp']=row['utc_ns'] if row else None
        result['sockets']=command(['sudo','-n','ss','-u','-a','-m','-n','-p','-e'])
    print(json.dumps(result))


def journal(since_ns, until_ns):
    from udp_generator_profile_journal import export
    export(pathlib.Path(REMOTE)/'game', since_ns, until_ns)


def controller():
    import run
    root = run.ROOT
    local = root / 'deployment/hetzner/results' / NAMESPACE
    local.mkdir(mode=0o700, exist_ok=False)
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
            'bitmap_binary': 'sha256sum /home/deploy/omega-udp-bitmap-1d15d84/rust/target/release/omega-server' if role == 'game' else 'true',
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
    for helper in ('atomic_publish.py', 'udp_capacity150_capture.py', 'udp_generator_profile_record.py', 'udp_generator_profile_journal.py'):
        (sources / helper).write_bytes((root / 'scripts/load_campaign' / helper).read_bytes())
    (local / 'udp_generator_profile.executed.py').write_bytes(pathlib.Path(__file__).read_bytes())
    if (sources/'atomic_publish.py').read_bytes() != subprocess.check_output(['git','show','d2dfe73:scripts/load_campaign/atomic_publish.py']):
        raise RuntimeError('Atomic helper differs from frozen plan')
    for helper in ('udp_generator_profile_record.py','udp_generator_profile_journal.py'):
        (local/(helper+'.executed')).write_bytes((sources/helper).read_bytes())
    expected_candidate = EXPECTED_CANDIDATE
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
            if parts[1] in ('omega-load-test', 'tcpdump', 'perf', 'bpftrace', 'apt', 'apt-get', 'dpkg', 'rustc', 'cargo') or any(x in parts[2] for x in ('host_collect.py', 'capture.py', 'flow-record', 'udp_control.py', 'udp_profile.py', 'udp_baseline.py', 'udp_control_capture.py', 'udp_capacity150.py', 'udp_generator_profile', 'udp_buffer.py', 'udp_bounded.py', 'udp_bitmap.py')):
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
    if states['game']['bitmap_binary'].split()[0] != '29f8f71eea24ca6490620dc2235831298e52503839ff8cf5ae2309a11cf09421':
        raise RuntimeError('Bitmap executable changed')
    original_config = json.loads(states['game']['config'])
    candidate_config = dict(original_config, udp_receive_buffer_bytes=2097152)
    config_bytes = (json.dumps(candidate_config, indent=2) + '\n').encode()
    (local / 'arena-buffer.json').write_bytes(config_bytes)
    config_proof = {'original_sha256': hashlib.sha256(states['game']['config'].encode()).hexdigest(), 'candidate_sha256': hashlib.sha256(config_bytes).hexdigest(), 'semantic_diff': {'udp_receive_buffer_bytes': {'before': original_config.get('udp_receive_buffer_bytes'), 'after': 2097152}}}
    if config_proof['candidate_sha256'] != '642b257dc4248a24286132facbca1c9994dfef69b7d380c9da38caff08819183':
        raise RuntimeError('Unexpected candidate config bytes')
    dump(local / 'config-proof.json', config_proof)
    dump(local / 'preflight-proof.json', {'passed': True, 'utc_ns': time.time_ns(), 'pinned': PINNED})
    manifest = {'namespace': NAMESPACE, 'requested_bots': 150, 'behavior': 'strategy',
                'ramp_limit_s': RAMP_SECONDS, 'steady_limit_s': STEADY_SECONDS,
                'input_hz': 30, 'seed': 30, 'stagger_ms': 100, 'difficulty': 1.0,
                'game_config': candidate_config, 'config_proof': config_proof, 'pinned': PINNED,
                'ramp_input_cadence': 'collected; analyze separately', 'generator_valid': None,
                'classification': 'diagnostic-profile-only', 'intervention': 'Only generator CPU profiles added: phase2 +0..25 and +180..205; journal byte handling corrected', 'workloads_launched': 0, 'collector_cadence_s': 1,
                'capture_duration_change_s': [300, 600], 'host_limit_s': 600, 'workload_limit_s': 550, 'restoration_limit_s': 720, 'poll_sleep_s': 2, 'map_polling': 'combined with existing status query; no extra map SSH reads', 'collector_overhead_effect': None, 'packet_capture': 'compact-article-plus-per-port-1Hz',
                'experiment_binary_sha256': {r: s['experiment_binary'].split()[0] for r, s in states.items()},
                'candidate_revision': CANDIDATE_REVISION, 'collector_revision': COLLECTOR_REVISION,
                'collector_source_sha256': {n: hashlib.sha256((sources / n).read_bytes()).hexdigest() for n in names},
                'control_binary_sha256': {r: s['control_binary'].split()[0] for r, s in states.items()},
                'controller_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                'host_collector_sha256': hashlib.sha256((sources / 'host_collect.py').read_bytes()).hexdigest(),
                'abort_policy': 'First join failure; ramp 180s; phase2 360s; authenticated <65% of peak >=100 for two 2s polls; missing game progress >10s; log >24MiB',
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
            copy(role, pathlib.Path(__file__), REMOTE + '/udp_generator_profile.py')
            for name in (*names, 'atomic_publish.py', 'udp_capacity150_capture.py', 'udp_generator_profile_record.py', 'udp_generator_profile_journal.py'):
                copy(role, sources / name, REMOTE + '/' + name)
            ssh(role, 'source /home/deploy/.cargo/env; rustc --edition=2021 -O ' + REMOTE + '/udp_control_record.rs -o ' + REMOTE + '/flow-record')
            ssh(role, 'sha256sum ' + REMOTE + '/*.py ' + REMOTE + '/*.rs ' + REMOTE + '/flow-record > ' + REMOTE + '/' + role + '/collector-sha256.txt')
        copy('game', local / 'arena-buffer.json', REMOTE + '/arena-buffer.json')
        restore = '#!/bin/sh\nset -e\nif test -f ' + OVERRIDE + '; then\n systemctl stop ' + SERVICE + '\n mv ' + OVERRIDE + ' ' + REMOTE + '/retired-runtime-override.conf\n systemctl daemon-reload\nfi\nsystemctl start ' + SERVICE + '\n'
        (local / 'restore.sh').write_text(restore)
        copy('game', local / 'restore.sh', REMOTE + '/restore.sh')
        ssh('game', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-restore --on-active=720s /bin/sh ' + REMOTE + '/restore.sh')
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
        override = '[Service]\nExecStart=\nExecStart=' + EXPERIMENT_BINARIES['game'] + ' --config ' + REMOTE + '/arena-buffer.json --allow-unsigned-tickets\nEnvironment=OMEGA_MEASURE_DIR=' + REMOTE + '/game\nReadWritePaths=' + REMOTE + '/game\n'
        (local / 'diagnostic.conf').write_text(override)
        copy('game', local / 'diagnostic.conf', REMOTE + '/diagnostic.conf')
        ssh('game', 'sudo -n mkdir -p ' + str(pathlib.PurePosixPath(OVERRIDE).parent) + '; sudo -n install -m 0644 ' + REMOTE + '/diagnostic.conf ' + OVERRIDE + '; sudo -n systemctl daemon-reload')
        override_installed = True
        manifest['experiment_service_start_ns'] = time.time_ns()
        ssh('game', 'sudo -n systemctl start ' + SERVICE)
        time.sleep(2)
        invocation = ssh('game', 'systemctl show ' + SERVICE + ' -p InvocationID --value').strip()
        manifest['service_invocation'] = invocation
        manifest['running_game_executable_sha256'] = ssh('game', 'pid=$(systemctl show ' + SERVICE + ' -p MainPID --value); sha256sum /proc/$pid/exe').split()[0]
        if manifest['running_game_executable_sha256'] != manifest['experiment_binary_sha256']['game']:
            raise RuntimeError('Running game is not candidate build')
        manifest['fresh_socket'] = ssh('game', 'sudo -n ss -u -a -m -n -p -e "( sport = :8081 )"')
        if 'd0)' not in manifest['fresh_socket'] or 'rb4194304' not in manifest['fresh_socket'] or 'tb524288' not in manifest['fresh_socket']:
            raise RuntimeError('Fresh socket buffer/drop gate failed')
        manifest['startup_log'] = ssh('game', 'journalctl _SYSTEMD_INVOCATION_ID=' + invocation + ' --no-pager -o cat')
        dump(local / 'manifest.json', manifest)
        if '2097152' not in manifest['startup_log'] or '4194304' not in manifest['startup_log']:
            raise RuntimeError('Requested/effective startup buffer not confirmed')
        if ssh('game', 'sha256sum ' + REMOTE + '/arena-buffer.json').split()[0] != config_proof['candidate_sha256']:
            raise RuntimeError('Candidate config hash mismatch')
        for role in ('game', 'bots'):
            command = 'exec python3 ' + REMOTE + '/udp_generator_profile.py collect --role ' + role
            ssh(role, 'sudo -n systemd-run --quiet --unit=' + UNIT + '-' + role + '-collect --property=RuntimeMaxSec=600 --property=TimeoutStopSec=8 /bin/sh -c ' + shlex.quote(command))
        time.sleep(2)
        for role in ('game', 'bots'):
            peer = run.HOSTS['bots' if role == 'game' else 'game']['ipv4']
            command = 'exec python3 ' + REMOTE + '/udp_capacity150_capture.py ' + REMOTE + '/' + role + ' eth0 ' + peer
            ssh(role, 'sudo -n systemd-run --quiet --unit=' + UNIT + '-' + role + '-capture --property=KillMode=mixed --property=RuntimeMaxSec=600 --property=TimeoutStopSec=12 --property=MemoryMax=536870912 --property=LimitFSIZE=67108864 /bin/sh -c ' + shlex.quote(command))
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
                '--bots', '150', '--behavior', 'strategy', '--duration', str(STEADY_SECONDS),
                '--input-hz', '30', '--seed', '30', '--stagger', '100', '--difficulty', '1.0',
                '--bandwidth-budget', '0', '--assertions', 'strict', '--aoi-exit-radius', '1100',
                '--output', REMOTE + '/bots/bot.json']
        dump(local / 'invocation.json', {'argv': argv})
        copy('bots', local / 'invocation.json', REMOTE + '/bots/invocation.json')
        manifest['command'] = shlex.join(argv)
        ssh('bots', 'sudo -n systemd-run --quiet --unit='+UNIT+'-profile-supervisor --property=RuntimeMaxSec=550 --property=TimeoutStopSec=3 --property=MemoryMax=536870912 python3 '+REMOTE+'/udp_generator_profile_record.py supervise --directory '+REMOTE+'/bots --unit '+UNIT)
        ssh('bots', 'test -f '+REMOTE+'/bots/profile-supervisor-ready.json')
        # Last gate immediately before traffic: direct runtime proof, no cached identity.
        ssh('game', 'test ! -e '+REMOTE+'/game/window.json')
        fresh = json.loads(ssh('game', 'python3 ' + REMOTE + '/udp_generator_profile.py status --role game'))
        manifest['pre_swarm_runtime'] = fresh
        if fresh['identity']['InvocationID'] != invocation:
            raise RuntimeError('Candidate restarted before swarm')
        if fresh['exe_sha256'] != EXPECTED_CANDIDATE or fresh['identity']['ActiveState'] != 'active':
            raise RuntimeError('Fresh runtime identity gate failed')
        if not re.search(r'^players_online 0$', fresh['metrics'], re.M):
            raise RuntimeError('Fresh zero population gate failed')
        if not all(s in fresh['sockets'] for s in ('rb4194304','tb524288','d0)', 'pid='+fresh['identity']['MainPID']+',')):
            raise RuntimeError('Fresh effective buffer/drop gate failed')
        manifest['swarm_start_utc_ns'] = time.time_ns()
        manifest['workload_launch_attempted'] = True
        dump(local / 'manifest.json', manifest)
        ssh('bots', 'sudo -n systemd-run --quiet --unit=' + UNIT + '-swarm --uid=deploy --property=LimitNOFILE=8192 --property=KillMode=mixed --property=TimeoutStopSec=10 --property=RuntimeMaxSec=550 python3 ' + REMOTE + '/udp_generator_profile.py swarm')
        manifest['workloads_launched'] = 1
        dump(local / 'manifest.json', manifest)
        print('Single Strategy 150 generator diagnostic started', flush=True)
        started = time.monotonic()
        peak = collapsed = 0
        scheduled = False
        while time.monotonic() - started < 550:
            poll_start = time.time_ns()
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                futures = {role: pool.submit(ssh, role, 'python3 ' + REMOTE + '/udp_generator_profile.py status --role ' + role) for role in ('game','bots')}
                observations = {role: json.loads(f.result()) for role,f in futures.items()}
            with (local / 'status-polls.ndjson').open('a') as output:
                output.write(json.dumps({'start_ns':poll_start, 'end_ns':time.time_ns(), 'observations':observations})+'\n')
            g,b = observations['game'],observations['bots']
            if g['identity'] != fresh['identity'] or g['exe_sha256'] != EXPECTED_CANDIDATE:
                manifest['controller_abort'] = 'game-runtime-identity-changed'
                break
            for role,obs in observations.items():
                if obs['parser'].get('status') != 'running' or obs.get('capture_resource'):
                    manifest['controller_abort'] = role+'-collector-failed-or-ended'
                    break
                if not obs['host_fresh']:
                    manifest['controller_abort'] = role+'-host-collector-stale'
                    break
                pairs = obs['mapping']
                if len({x[0] for x in pairs}) != len(pairs) or len({x[1] for x in pairs}) != len(pairs):
                    manifest['controller_abort'] = role+'-mapping-not-unique'
                    break
            if manifest.get('controller_abort'): break
            if not all(x in g['sockets'] for x in ('rb4194304','tb524288','pid='+fresh['identity']['MainPID']+',')):
                manifest['controller_abort']='game-effective-buffers-or-socket-owner-changed'
                break
            if b.get('bot_identity'):
                if b['bot_identity']['exe_sha256']!=EXPECTED_CONTROL['bots'] or (manifest.get('bot_identity') and b['bot_identity']!=manifest['bot_identity']):
                    manifest['controller_abort']='bot-runtime-identity-changed'
                    break
                manifest['bot_identity']=b['bot_identity']
            bot_limits = re.findall(r'omega-load-test[^\n]*\n\s*skmem:\(r\d+,rb(\d+),t\d+,tb(\d+)', b['sockets'])
            if bot_limits and any((int(rb),int(tb)) != (212992,212992) for rb,tb in bot_limits):
                manifest['controller_abort']='bot-effective-buffers-differ'
                break
            profile_problem=(b.get('profile_supervisor') or {}).get('error')
            for name,profile in b.get('profiles',{}).items():
                if profile and (profile.get('error') or profile.get('rc')!=0 or profile.get('reason')!='nominal-window-end'):
                    profile_problem=name+'-recording-failed'
            for name,dispatch in (b.get('profile_supervisor') or {}).get('profiles',{}).items():
                if dispatch.get('rc',0)!=0 or (time.time_ns()-dispatch['dispatch_utc_ns']>35e9 and not b.get('profiles',{}).get(name)):
                    profile_problem=name+'-dispatch-or-status-failed'
            if profile_problem:
                manifest['controller_abort']='profile-failure:'+profile_problem
                break
            if b.get('guard'):
                manifest['guard_result'] = b['guard']
                break
            if b.get('phase') and not scheduled:
                phase = b['phase']['phase2_utc_ns']
                window = {'start':phase+60_000_000_000, 'end':phase+360_000_000_000}
                if time.time_ns() >= window['start']-10_000_000_000:
                    raise RuntimeError('Insufficient schedule publication lead time')
                dump(local/'window.json',window)
                for role in ('game','bots'):
                    publish_file(copy,ssh,role,local/'window.json',REMOTE+'/'+role+'/window.json')
                manifest['window'] = window
                manifest['window_published_ns'] = time.time_ns()
                scheduled = True
                dump(local/'manifest.json',manifest)
                print('Phase 2 reached; exact 60s warmup / 300s window published atomically',flush=True)
            if scheduled:
                # Handshakes precede Phase 2; allow one bounded capture flush interval.
                if time.time_ns() >= manifest['window']['start']-50_000_000_000:
                    gm,bm = dict(g['mapping']),dict(b['mapping'])
                    if len(gm)!=150 or len(bm)!=150 or gm!=bm or set(gm.values())!=set(range(1,151)):
                        manifest['controller_abort']='identity-mapping-incomplete-or-disagrees'
                        break
            sample = g.get('server')
            if not sample or time.time_ns()-sample['utc_ns'] > 10e9:
                manifest['controller_abort']='game-observation-stale-over-10s'
                break
            if b.get('bots_stamp') and time.time_ns()-b['bots_stamp'] > 10e9:
                manifest['controller_abort']='bot-observation-stale-over-10s'
                break
            population=len(sample['players']);peak=max(peak,population)
            collapsed=collapsed+1 if peak>=100 and population<.65*peak else 0
            if collapsed>=2:
                manifest['controller_abort']='authenticated-population-below-65-percent-peak'
                break
            if int(time.monotonic()-started)//30 > int(max(0,time.monotonic()-started-4))//30:
                print('Observation ongoing: authenticated='+str(population),flush=True)
            time.sleep(2)
        else:
            manifest['controller_abort']='overall-time-limit'
        manifest['controller_decision_utc_ns']=time.time_ns()
        manifest['controller_observed_peak']=peak
    except Exception as error:
        manifest['controller_error'] = str(error)
        raise
    finally:
        manifest.setdefault('controller_decision_utc_ns',time.time_ns())
        dump(local/'manifest.json',manifest)
        def clean(role,label,command):
            cleanup.setdefault(role,{})
            try:
                ssh(role,command)
                cleanup[role][label]=True
                return True
            except Exception as error:
                cleanup[role][label+'_error']=type(error).__name__
                return False
        # Bots first; captures and game continue through termination and a quiet tail.
        bots_exited=True
        if 'bots' in staged:
            bots_exited=clean('bots','swarm_stop','sudo -n systemctl stop '+UNIT+'-swarm; test "$(systemctl show '+UNIT+'-swarm -p MainPID --value)" = 0')
            if bots_exited:
                manifest['bots_exit_verified_utc_ns']=time.time_ns()
                time.sleep(5)
        for role in staged:
            clean(role,'final_socket_snapshot','sudo -n ss -u -a -m -n -p -e > '+REMOTE+'/'+role+'/final-sockets.txt; cat /proc/net/snmp > '+REMOTE+'/'+role+'/final-snmp.txt')
        if game_stopped and bots_exited:
            clean('game','game_stop','sudo -n systemctl stop '+SERVICE)
            manifest['game_stopped_utc_ns']=time.time_ns()
        for role in staged:
            for suffix in ('capture','collect'):
                clean(role,suffix+'_stop','sudo -n systemctl stop '+UNIT+'-'+role+'-'+suffix+'; test "$(systemctl show '+UNIT+'-'+role+'-'+suffix+' -p MainPID --value)" = 0')
        if 'bots' in staged:
            for suffix in ('profile-supervisor','profile-early','profile-late'):
                clean('bots',suffix+'_stop','sudo -n systemctl stop '+UNIT+'-'+suffix+' 2>/dev/null || true; test -z "$(systemctl list-units --state=active --no-legend '+UNIT+'-'+suffix+'.service)"')
        if game_stopped and manifest.get('experiment_service_start_ns'):
            try:
                workload=json.loads(ssh('bots','cat '+REMOTE+'/bots/workload-start.json'))
                guard=json.loads(ssh('bots','cat '+REMOTE+'/bots/guard-result.json'))
                dump(local/'workload-period.json',[workload['utc_ns'],guard['ended_utc_ns']])
                publish_file(copy,ssh,'game',local/'workload-period.json',REMOTE+'/game/workload-period.json')
            except Exception:
                cleanup.setdefault('game',{})['workload_journal_period_missing']=True
            clean('game','all_invocation_logs','timeout 75s python3 '+REMOTE+'/udp_generator_profile.py journal --since-ns '+str(manifest['experiment_service_start_ns'])+' --until-ns '+str(manifest['game_stopped_utc_ns']))
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
                cleanup[role]['bitmap_binary_unchanged'] = after['bitmap_binary'] == states[role]['bitmap_binary']
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
        dump(local / 'manifest.json', manifest)
        dump(local / 'cleanup.json', cleanup)
        print(json.dumps({'completed': True, 'controller_abort': manifest.get('controller_abort'),
                          'guard_reason': ((manifest.get('guard_result') or {}).get('reason') or {}).get('kind'),
                          'cleanup_archive_roles': [r for r in cleanup if 'archive_sha256' in cleanup[r]]}), flush=True)


def verify():
    """Read-only independent final audit; no workload can be launched here."""
    import run
    local = run.ROOT / 'deployment/hetzner/results' / NAMESPACE
    manifest = json.loads((local / 'manifest.json').read_text())
    results = {}
    for role in ('game', 'bots'):
        before = json.loads((local / (role + '-before.json')).read_text())
        commands = {
            'processes': 'ps -eo pid,comm,args',
            'units': 'systemctl list-units --all --no-legend ' + shlex.quote(UNIT + '-*'),
            'maintenance': 'systemctl show apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service -p Id -p ActiveState -p UnitFileState',
            'buffers': 'sysctl net.core.rmem_default net.core.rmem_max net.core.wmem_default net.core.wmem_max',
            'original_binary': 'sha256sum ' + BINARIES[role],
            'experiment_binary': 'sha256sum ' + EXPERIMENT_BINARIES[role],
            'control_binary': 'sha256sum ' + CONTROL_BINARIES[role],
            'bitmap_binary': 'sha256sum /home/deploy/omega-udp-bitmap-1d15d84/rust/target/release/omega-server' if role == 'game' else 'true',
            'archive': 'sha256sum ' + REMOTE + '/' + role + '.tar.gz',
            'owned_original': 'sha256sum ' + REMOTE + '/original/' + pathlib.PurePosixPath(BINARIES[role]).name,
            'disk': 'df --output=avail -B1 /home/deploy | tail -1',
            'qdisc': 'tc -j qdisc show dev eth0',
            'egress': 'tc -j filter show dev eth0 egress',
            'ingress': 'tc -j filter show dev eth0 ingress',
            'nft': 'sudo -n nft list ruleset',
            'prior_archives': "set -o pipefail; find /home/deploy/omega-results -maxdepth 2 -type f \\( -name '*.tar.gz' -o -name '*sha256*' \\) ! -path '" + REMOTE + "/*' -exec sha256sum {} \\; | sort",
            'namespace_inventory': "find /home/deploy/omega-results -mindepth 1 -maxdepth 1 -type d ! -name '" + NAMESPACE + "' -printf '%f\\n' | sort",
            'closed_states': "find /home/deploy/omega-results/campaign-20261013 /home/deploy/omega-results/one-pass-20261014 -maxdepth 1 -name '*state*.json' -exec sha256sum {} \\;",
        }
        if role == 'game':
            commands.update(service='systemctl is-active ' + SERVICE,
                executable='pid=$(systemctl show ' + SERVICE + ' -p MainPID --value); sha256sum /proc/$pid/exe',
                unit='systemctl cat ' + SERVICE, config='sha256sum /etc/omega-loadtest/arena.json',
                metrics='curl -fsS --max-time 3 http://127.0.0.1:9100/metrics',
                sockets='sudo -n ss -u -a -m -n -p -e \"( sport = :8081 )\"',
                override_absent='test ! -e ' + OVERRIDE + ' && echo absent',
                preserved='cd ' + REMOTE + '/original/measurement-current; sha256sum -c ../measurement-sha256.txt',
                current_measurement='systemctl show ' + SERVICE + ' -p Environment; stat /var/lib/omega-measure/current/server.ndjson /var/lib/omega-measure/current/ticks.csv',
                candidate_source='git -C ' + CANDIDATE_CHECKOUT + ' rev-parse HEAD; git -C ' + CANDIDATE_CHECKOUT + ' status --porcelain')
        raw = {key: run.ssh(role, cmd) for key, cmd in commands.items()}
        dump(local / (role + '-final-verification.json'), raw)
        competing = []
        for line in raw['processes'].splitlines()[1:]:
            parts = line.split(None, 2)
            if len(parts) < 3 or parts[1] in ('bash', 'sshd', 'sshd-session'): continue
            if parts[1] in ('omega-load-test', 'tcpdump', 'perf', 'bpftrace', 'rustc', 'cargo') or any(x in parts[2] for x in ('host_collect.py', 'capture.py', 'flow-record', NAMESPACE + '/udp_generator_profile')):
                competing.append(parts[1])
        summary = {'utc_ns':time.time_ns(), 'commands_successful':True,
            'competing_or_owned_processes':competing,
            'owned_active_units_absent':not re.search(r'\sactive\s',raw['units']),
            'original_binary_unchanged':raw['original_binary'].split()[0] == PINNED[role],
            'owned_original_matches':raw['owned_original'].split()[0] == PINNED[role],
            'experiment_binary_unchanged':raw['experiment_binary'].split()[0] == manifest['experiment_binary_sha256'][role],
            'control_binary_unchanged':raw['control_binary'] == before['control_binary'],
            'bitmap_binary_unchanged':raw['bitmap_binary'] == before['bitmap_binary'],
            'archive_remote_local_equal':raw['archive'].split()[0] == hashlib.sha256((local/(role+'.tar.gz')).read_bytes()).hexdigest(),
            'buffers_unchanged':raw['buffers'] == before['buffers'],
            'maintenance':raw['maintenance'], 'available_disk_bytes':int(raw['disk'])}
        for key in ('qdisc','egress','ingress','prior_archives','namespace_inventory','closed_states'):
            summary[key+'_unchanged'] = raw[key] == before[key]
        strip = lambda v: re.sub(r'counter packets \d+ bytes \d+', 'counter', v)
        summary['firewall_unchanged'] = strip(raw['nft']) == strip(before['nft'])
        if role == 'game':
            summary.update(service_active=raw['service'].strip() == 'active',
                ordinary_effective_buffers=all(x in raw['sockets'] for x in ('rb524288','tb524288')),
                zero_players=bool(re.search(r'^players_online 0$',raw['metrics'],re.M)),
                original_executable_active=raw['executable'].split()[0] == PINNED['game'],
                unit_restored=raw['unit'] == before['unit'],
                config_sha256=raw['config'].split()[0],
                config_unchanged=raw['config'].split()[0] == manifest['config_proof']['original_sha256'],
                override_absent=raw['override_absent'].strip() == 'absent',
                preserved_measurement_verified=bool(raw['preserved']) and all(x.endswith(': OK') for x in raw['preserved'].splitlines()),
                original_measurement_destination_restored='OMEGA_MEASURE_DIR=/var/lib/omega-measure/current' in raw['current_measurement'],
                candidate_source_clean=raw['candidate_source'].strip() == CANDIDATE_REVISION)
        results[role] = summary
    dump(local/'final-verification-summary.json',results)
    if any(v is False for r in results.values() for v in r.values()) or any(r['competing_or_owned_processes'] for r in results.values()):
        raise RuntimeError('Independent cleanup verification failed; private evidence retained')
    print('Independent final verification passed on both hosts; no workload launched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'collect', 'swarm', 'verify', 'status', 'journal'))
    parser.add_argument('--role', choices=('game', 'bots'))
    parser.add_argument('--since-ns', type=int)
    parser.add_argument('--until-ns', type=int)
    args = parser.parse_args()
    if args.mode == 'status':
        status(args.role)
    elif args.mode == 'journal':
        journal(args.since_ns, args.until_ns)
    elif args.mode == 'collect':
        collect(args.role)
    elif args.mode == 'verify':
        verify()
    elif args.mode == 'swarm':
        swarm()
    else:
        try:
            controller()
        except Exception as error:
            # Detailed subprocess errors/addresses stay in the private command journal.
            print('Receive buffer diagnostic stopped: ' + type(error).__name__, file=sys.stderr)
            sys.exit(1)
